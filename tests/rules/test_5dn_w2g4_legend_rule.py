"""CR 704.5j, the legend rule, as the player's choice (5DN W2G4).

    704.5j If two or more legendary permanents with the same name are
    controlled by the same player, that player chooses one of them, and the
    rest are put into their owners' graveyards.

The check kept the first and asked nobody (W1G4's report, §4): Helm of
Kaldra's second activation binned the new, fully equipped Kaldra. Now a seat a
person decides for is asked (``legend_rule``), the game waits on the answer,
and the answer makes the check again; a seat nobody asks keeps the one worth
most to it (``ai_prompt_picks.legend_rule_keep``), the first between equals.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_prompt_picks import legend_rule_keep
from engine.aura_attachment import attach_aura
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import settle
from web.prompts import blocking_prompt

_SHANDLAR = "Sir Shandlar of Eberyn"


def _perm(card, **metadata) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.metadata.update(metadata)
    return permanent


def _table(mine=(), theirs=(), *, interactive=(), active=0, set_pool=None) -> Game:
    """Two seats in the active seat's main phase with a priority window open;
    *mine* / *theirs* are permanents already on each battlefield."""
    island = set_pool("LEA")["Island"]
    game = Game(
        players=[
            PlayerState(name="P0", library=[island] * 10, battlefield=list(mine)),
            PlayerState(name="P1", library=[island] * 10, battlefield=list(theirs)),
        ],
        interactive_seats=set(interactive),
        active_player_index=active,
        current_turn_phase="precombat_main",
        current_step="precombat_main",
    )
    game.enforce_mana_costs = False
    return game


def _named(game, seat, name):
    return [perm for perm in game.controlled_by(seat) if perm.effective_card.name == name]


def _owed(game, seat=None):
    return [
        choice for choice in game.pending_choices
        if choice.kind == "legend_rule" and (seat is None or choice.player_index == seat)
    ]


# -- Helm of Kaldra, activated twice -----------------------------------------


def _kaldra_board(set_pool, *, interactive=()):
    game = _table(interactive=interactive, set_pool=set_pool)
    helm = _perm(set_pool("5DN")["Helm of Kaldra"])
    for permanent in (
        helm, _perm(set_pool("MRD")["Sword of Kaldra"]), _perm(set_pool("DST")["Shield of Kaldra"]),
    ):
        game._put_permanent_onto_battlefield(0, permanent, None)
    game._sync_control()
    settle(game)
    return game, helm


def _activate_helm(game, helm):
    result = game.activate_permanent_ability(
        0, helm.card.name, permanent_index=game.battlefield_index_of(helm), ability_index=0,
    )
    assert result.supported, result.details


@pytest.mark.cr("704.5j", "111.7")
def test_a_seat_nobody_asks_keeps_the_equipped_kaldra(set_pool):
    """The defect W1G4 measured: the second Kaldra is the one all three
    Equipment were just moved onto, and the check kept the first — a bare 4/4.
    A seat nobody asks now keeps the 9/9; the bare token goes to the graveyard
    and ceases to exist (CR 111.7)."""
    game, helm = _kaldra_board(set_pool)
    _activate_helm(game, helm)
    settle(game)
    (first,) = _named(game, 0, "Kaldra")
    _activate_helm(game, helm)
    settle(game)

    (kept,) = _named(game, 0, "Kaldra")
    assert kept is not first
    assert (kept.effective_power, kept.effective_toughness) == (9, 9)
    assert not game.is_on_battlefield(first)
    assert "Kaldra put into graveyard (704.5j: legend rule)" in game.log
    assert not _owed(game)


@pytest.mark.cr("704.5j", "704.5n")
def test_an_asked_seat_keeps_the_kaldra_it_chooses(set_pool):
    """A person is asked, the game waits, and the answer is what stays — the
    old bare Kaldra here, against the default's pick: the new one goes, and
    the three Equipment it carried become unattached and stay (CR 704.5n)."""
    game, helm = _kaldra_board(set_pool, interactive={0})
    _activate_helm(game, helm)
    settle(game)
    (first,) = _named(game, 0, "Kaldra")
    _activate_helm(game, helm)
    choice = settle(game, defaults=False)

    assert choice is not None and choice.kind == "legend_rule"
    second = next(perm for perm in _named(game, 0, "Kaldra") if perm is not first)
    assert choice.data["name"] == "Kaldra"
    assert choice.data["candidates"] == [first.permanent_id, second.permanent_id]
    assert game.waiting_prompt() is choice
    assert len(_named(game, 0, "Kaldra")) == 2, "nothing goes before the answer"

    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=first.permanent_id)
    settle(game)
    assert _named(game, 0, "Kaldra") == [first]
    assert (first.effective_power, first.effective_toughness) == (4, 4)
    assert not game.is_on_battlefield(second)
    equipment = [perm for perm in game.controlled_by(0) if perm.card.name.endswith("of Kaldra")]
    assert len(equipment) == 3
    assert all(perm.metadata.get("attached_to") is None for perm in equipment)


@pytest.mark.cr("704.5j", "117.3b")
def test_the_prompt_holds_the_game_and_refuses_what_it_does_not_offer(set_pool):
    """While the choice is owed nobody acts around it (the web gate refuses a
    pass), an answer naming anything but one of the namesakes is refused with
    the prompt still owed, and the accepted answer gives the active player
    priority (CR 117.3b)."""
    leg = set_pool("LEG")
    bystander = _perm(set_pool("LEA")["Grizzly Bears"])
    old = _perm(leg[_SHANDLAR])
    game = _table(mine=[old, bystander], interactive={0, 1}, active=0, set_pool=set_pool)
    game.start_priority_window(0)
    game.players[0].hand.append(leg[_SHANDLAR])
    game.cast_from_hand(0, _SHANDLAR)
    (choice,) = _owed(game, 0)
    new = next(perm for perm in _named(game, 0, _SHANDLAR) if perm is not old)

    gate = blocking_prompt(game, 0, "pass_priority", frozenset())
    assert gate is not None and gate[1] is choice
    assert not game.resolve_pending_choice("legend_rule", 0, permanent_id=bystander.permanent_id)
    assert not game.resolve_pending_choice("legend_rule", 0, permanent_id=None)
    assert _owed(game, 0) == [choice]

    game.priority_player_index = 1  # as the priority pass leaves it: with the owing seat
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=new.permanent_id)
    assert _named(game, 0, _SHANDLAR) == [new]
    assert [card.name for card in game.players[0].graveyard] == [_SHANDLAR]
    assert game.waiting_prompt() is None
    assert game.priority_player_index == 0


@pytest.mark.cr("704.5j")
def test_between_equals_a_seat_nobody_asks_keeps_the_first(set_pool):
    """Two untouched copies are worth the same: the default keeps the one that
    was there first — what the rule always did, so a seeded game that never
    sees two different copies plays as it did."""
    leg = set_pool("LEG")
    first, second = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    game = _table(mine=[first, second], set_pool=set_pool)
    assert _named(game, 0, _SHANDLAR) == [first]
    assert not game.is_on_battlefield(second)


@pytest.mark.cr("704.5j")
def test_the_ai_keeps_counters_untapped_and_its_own_aura_over_an_opponents(set_pool):
    """The pick is read off the board, never the name: a creature with a +1/+1
    counter over one without, an untapped one over a tapped one, and the copy
    carrying the seat's own Holy Strength over the one under an opponent's
    Pacifism (each Aura goes to the graveyard with the copy it is on, CR
    704.5m)."""
    leg, lea = set_pool("LEG"), set_pool("LEA")
    plain, countered = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    add_counters(countered, "+1/+1", 1)
    game = _table(set_pool=set_pool)
    game.players[0].battlefield.extend([plain, countered])
    assert legend_rule_keep(game, 0, [plain, countered]) is countered

    untapped, tapped = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    tapped.tapped = True
    assert legend_rule_keep(game, 0, [tapped, untapped]) is untapped

    pacified, blessed = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    pacifism = _perm(set_pool("MIR")["Pacifism"])
    strength = _perm(lea["Holy Strength"])
    game = _table(mine=[pacified, blessed, strength], theirs=[pacifism], set_pool=set_pool)
    # (Game() has already applied the rule once; put both copies back for the
    # pick itself.)
    for permanent in (pacified, blessed):
        if not game.is_on_battlefield(permanent):
            game.players[0].battlefield.append(permanent)
    attach_aura(pacifism, pacified)
    attach_aura(strength, blessed)
    game._recompute_continuous_effects()
    assert legend_rule_keep(game, 0, [pacified, blessed]) is blessed
    # …and with the Holy Strength gone, the opponent's Pacifism alone still
    # decides it: the unenchanted copy, though it is the later one.
    assert legend_rule_keep(game, 0, [pacified, _perm(leg[_SHANDLAR])]) is not pacified


@pytest.mark.cr("704.5j", "101.4")
def test_two_players_at_once_are_asked_active_player_first(set_pool):
    """Each player owes a choice in the same check: both are asked, the active
    player's prompt first (CR 101.4), and each answer keeps that player's own
    choice and nothing of the other's."""
    leg = set_pool("LEG")
    mine = [_perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])]
    theirs = [_perm(leg["Jacques le Vert"]), _perm(leg["Jacques le Vert"])]
    game = _table(mine=mine, theirs=theirs, interactive={0, 1}, active=1, set_pool=set_pool)

    owed = _owed(game)
    assert [choice.player_index for choice in owed] == [1, 0]
    assert game.waiting_prompt().player_index == 1
    assert game.resolve_pending_choice("legend_rule", 1, permanent_id=theirs[1].permanent_id)
    assert _named(game, 1, "Jacques le Vert") == [theirs[1]]
    assert len(_named(game, 0, _SHANDLAR)) == 2, "seat 0 has not answered"
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=mine[1].permanent_id)
    assert _named(game, 0, _SHANDLAR) == [mine[1]]
    assert not _owed(game)


@pytest.mark.cr("704.5j", "101.4")
def test_a_seat_nobody_asks_does_not_wait_for_one_that_is(set_pool):
    """A person and a seat nobody asks in the same check: the person is asked,
    and the other keeps its pick at once."""
    leg = set_pool("LEG")
    mine = [_perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])]
    theirs = [_perm(leg["Jacques le Vert"]), _perm(leg["Jacques le Vert"])]
    game = _table(mine=mine, theirs=theirs, interactive={0}, set_pool=set_pool)

    assert [choice.player_index for choice in _owed(game)] == [0]
    assert _named(game, 1, "Jacques le Vert") == [theirs[0]]
    assert len(_named(game, 0, _SHANDLAR)) == 2


@pytest.mark.cr("704.5j")
def test_an_owed_choice_whose_group_is_gone_is_dropped(set_pool):
    """A namesake leaves while the choice is owed (here by hand; in play, by
    another state-based action of a later pass): the rule no longer applies,
    and the next check drops the prompt rather than holding the game on it."""
    leg = set_pool("LEG")
    first, second = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    game = _table(mine=[first, second], interactive={0}, set_pool=set_pool)
    assert len(_owed(game, 0)) == 1

    game.remove_from_battlefield(second)
    game.check_state_based_actions()
    assert not _owed(game)
    assert game.waiting_prompt() is None
    assert _named(game, 0, _SHANDLAR) == [first]


@pytest.mark.cr("704.5j")
def test_an_owed_choice_drained_by_default_keeps_the_pick(set_pool):
    """The default a queued prompt is drained with (an AI seat at a person's
    table, ``settle``) is the same pick as the one taken at the check: the
    countered copy, though it is the later one."""
    leg = set_pool("LEG")
    first, second = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    add_counters(second, "+1/+1", 2)
    game = _table(mine=[first, second], interactive={0}, set_pool=set_pool)
    (choice,) = _owed(game, 0)

    game.auto_resolve_choice(choice)
    assert _named(game, 0, _SHANDLAR) == [second]
    assert not _owed(game)


@pytest.mark.cr("704.5j", "700.4")
def test_the_binned_legend_dies_and_its_death_is_seen(set_pool):
    """The rest go to the graveyard by the rule: the copy not kept *dies* (CR
    700.4), and Black Market's "whenever a creature dies" hears it once the
    answer's check puts it there — not before the answer."""
    leg = set_pool("LEG")
    first, second = _perm(leg[_SHANDLAR]), _perm(leg[_SHANDLAR])
    market = _perm(set_pool("MMQ")["Black Market"])
    game = _table(mine=[market, first, second], interactive={0}, set_pool=set_pool)
    assert len(_owed(game, 0)) == 1
    assert not game.stack and game.players[0].graveyard == []

    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=second.permanent_id)
    settle(game)
    assert [card.name for card in game.players[0].graveyard] == [_SHANDLAR]
    assert _named(game, 0, _SHANDLAR) == [second]
    assert counters_on(market, "charge") == 1
