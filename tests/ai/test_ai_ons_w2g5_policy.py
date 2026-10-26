"""The AI pile ONS's wave 1 measured in seeded games and left (ONS W2G5).

Each section is one piece of policy, with the board that shows it and, where
the shape reaches past Onslaught, the pool-wide reading.

* **An activation that gives up its own source, or comes back at its own
  activator, is rehearsed** (`ai_abilities._gives_up_its_source`,
  `ai_valuation.reaches_both_sides`). Crown of Vigor was cast and sacrificed in
  the same main phase — a lasting +1/+1 traded for a fleeting one with nothing
  able to attack — and Shepherd of Rot drained both players from any position,
  its controller's losing one included: both were scored a flat 2.5.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.aura_attachment import attach_aura
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w2g5_card(set_pool, name):
    ons = set_pool("ONS")
    return ons[name] if name in ons else set_pool("LEA")[name]


def _w2g5_board(set_pool, mine, theirs=(), *, hand=(), life=(20, 20), sick=()):
    """Seat 0 in its own precombat main phase with *mine* (ONS names first,
    then Alpha's), costs enforced; seat 1 with *theirs*. Nothing is summoning
    sick except the names in *sick*."""
    def card(name):
        return _w2g5_card(set_pool, name)

    game = Game(players=[
        PlayerState(
            name="A", battlefield=[Permanent(card=card(n)) for n in mine],
            hand=[card(n) for n in hand], library=[card("Island")] * 10,
            life=life[0],
        ),
        PlayerState(
            name="B", battlefield=[Permanent(card=card(n)) for n in theirs],
            library=[card("Island")] * 10, life=life[1],
        ),
    ], enforce_mana_costs=True)
    game.interactive_seats = set()
    game.start_turn(0)
    game._sync_control()
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = (
            game.turn if permanent.card.name in sick else -99
        )
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w2g5_crowned(set_pool, theirs=(), *, life=20, sick=()):
    """Two Grizzly Bears, the first wearing Crown of Vigor, against *theirs*
    at *life*."""
    game = _w2g5_board(
        set_pool, ["Grizzly Bears", "Grizzly Bears", "Forest"], theirs,
        life=(20, life), sick=sick,
    )
    bears = next(iter(game.controlled_by(0)))
    crown = Permanent(card=_w2g5_card(set_pool, "Crown of Vigor"))
    game.players[0].battlefield.append(crown)
    game._sync_control()
    attach_aura(crown, bears)
    crown.metadata["summoning_sickness_turn"] = -99
    return game, crown


@pytest.mark.parametrize("sick", [(), ("Grizzly Bears",)])
def test_w2g5_a_crown_is_not_sacrificed_for_a_point_nothing_needs(set_pool, sick):
    """At twenty life across an empty board the sacrifice buys one damage this
    turn for the +1/+1 the Aura gives every turn — and with the Bears unable
    to attack, nothing at all. The Crown stays on."""
    game, _crown = _w2g5_crowned(set_pool, sick=sick)
    assert choose_activation_action(game, 0) is None


def test_w2g5_a_crown_is_sacrificed_when_it_is_the_lethal_point(set_pool):
    """At six life the Crown's +1/+1 to both Bears (they share a type) is the
    sixth damage: the rehearsal fights the combat, sees the game end, and the
    sacrifice is proposed — and carried out it pumps both."""
    game, crown = _w2g5_crowned(set_pool, life=6)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Crown of Vigor"
    assert game.activate_permanent_ability(
        0, action.permanent_name, permanent_index=action.permanent_index,
    ).supported
    resolve_stack(game)
    assert crown not in game.players[0].battlefield
    assert sorted(
        (p.effective_power, p.effective_toughness)
        for p in game.controlled_by(0) if p.is_creature
    ) == [(3, 3), (3, 3)]


@pytest.mark.parametrize(("life", "activated"), [
    ((20, 20), False),  # level: a point each is nothing gained
    ((5, 20), False),   # behind: the race is the opponent's
    ((20, 5), True),    # ahead: the last points are the dear ones
])
def test_w2g5_shepherd_of_rot_drains_only_from_ahead(set_pool, life, activated):
    """Two Zombies on the table, so each player loses two. Worth it only to the
    seat whose two points are worth less than the opponent's
    (`ai_rehearsal.life_worth` is concave)."""
    game = _w2g5_board(
        set_pool, ["Shepherd of Rot", "Gluttonous Zombie", "Swamp"], ["Grizzly Bears"],
        life=life,
    )
    action = choose_activation_action(game, 0)
    assert (action is not None and action.permanent_name == "Shepherd of Rot") is activated


# ==== Riptide Entrancer: a priced trade, weighed ==============================
#
# "Whenever this creature deals combat damage to a player, you may sacrifice it.
# If you do, gain control of target creature that player controls." The
# optional-pay default's "make no trades" declined it every time it connected
# (nine declines in one seeded ONS game, W1G10's report); its two halves are
# permanents a standing prices (`ai_prompt_readers.offer_trade`'s
# ``("source", "target_permanent")``, weighed by
# `ai_prompts.offer_trade_is_worth_taking`).


def _w2g5_entrancer_connects(set_pool, theirs):
    from engine.ai_combat import run_ai_combat_phase

    game = _w2g5_board(set_pool, ["Riptide Entrancer", "Island"], theirs)
    game.prompt_driver = lambda played: played.auto_resolve_pending_choices()
    for permanent in game.controlled_by(1):
        permanent.tapped = True  # nothing to block with
    run_ai_combat_phase(game, 0)
    game._resolve_priority_window()
    game.auto_resolve_pending_choices()
    return game


def test_w2g5_riptide_entrancer_is_sacrificed_for_the_creature_it_targets(set_pool):
    """A 1/1 that has connected is traded for the Hill Giant across the table:
    the Entrancer is in its owner's graveyard and the Giant is seat 0's."""
    game = _w2g5_entrancer_connects(set_pool, ["Hill Giant"])
    assert any("Riptide Entrancer: targets Hill Giant" in line for line in game.log)
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == ["Riptide Entrancer"]
    assert not any(p.is_creature for p in game.controlled_by(1))


def test_w2g5_thalakos_deceiver_takes_the_same_trade(set_pool):
    """Stronghold's "Whenever this creature attacks and isn't blocked, you may
    sacrifice it. If you do, gain control of target creature." — the one other
    card the reader names, and the same weighing: unblocked, the Deceiver is
    traded for the Hill Giant rather than for the seat's own Bears."""
    from engine.ai_combat import run_ai_combat_phase

    game = _w2g5_board(set_pool, ["Island"], ["Hill Giant"])
    deceiver = Permanent(card=set_pool("STH")["Thalakos Deceiver"])
    game.players[0].battlefield.insert(0, deceiver)
    game._sync_control()
    deceiver.metadata["summoning_sickness_turn"] = -99
    game.prompt_driver = lambda played: played.auto_resolve_pending_choices()
    for permanent in game.controlled_by(1):
        permanent.tapped = True
    run_ai_combat_phase(game, 0)
    game._resolve_priority_window()
    game.auto_resolve_pending_choices()
    assert [p.card.name for p in game.controlled_by(0) if p.is_creature] == ["Hill Giant"]
    assert [card.name for card in game.players[0].graveyard] == ["Thalakos Deceiver"]
