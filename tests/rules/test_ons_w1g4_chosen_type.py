"""A creature type chosen — while an effect resolves (CR 608.2d), by each
player in turn (CR 101.4), and by an opponent as a permanent enters
(CR 614.1c) — and the effects that read it.

Every card here is invented with the sentence under test, so what is shown is
the production and not one card's name: Onslaught's printings (Defensive
Maneuvers, Harsh Mercy, Patriarch's Bidding, Callous Oppressor, Circle of
Solace, Walking Desecration) are driven in ``tests/sets/test_ons_*.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.type_changes import gain_types
from tests.helpers import _damage_dealt, _mk_card, _nosick, resolve_stack

_PUMP = _mk_card(
    name="W1G4 Rally", mana_cost="{1}{W}", type_line="Instant",
    oracle_text="Creatures of the creature type of your choice get +2/+2 until end of turn.",
    colors=("W",),
)
_EACH_SWEEP = _mk_card(
    name="W1G4 Census", mana_cost="{2}{W}", type_line="Sorcery",
    oracle_text=(
        "Each player chooses a creature type. Destroy all creatures that "
        "aren't of a type chosen this way."
    ),
    colors=("W",),
)
_OPPONENT_CHOOSER = _mk_card(
    name="W1G4 Warden", mana_cost="{1}{U}", type_line="Creature — Human Wizard",
    oracle_text=(
        "As this creature enters, an opponent chooses a creature type.\n"
        "{T}: Gain control of target creature that isn't of the chosen type "
        "for as long as this creature remains tapped."
    ),
    colors=("U",), power=1, toughness=1,
)
_CLASS_SHIELD = _mk_card(
    name="W1G4 Ward", mana_cost="{W}", type_line="Enchantment",
    oracle_text=(
        "As this enchantment enters, choose a creature type.\n"
        "{W}: The next time a creature of the chosen type would deal damage to "
        "you this turn, prevent that damage."
    ),
    colors=("W",),
)
_REQUIREMENT = _mk_card(
    name="W1G4 Drummer", mana_cost="{B}", type_line="Creature — Zombie",
    oracle_text=(
        "{T}: Creatures of the creature type of your choice attack this turn "
        "if able."
    ),
    colors=("B",), power=1, toughness=1,
)


def _creature(name, subtype):
    return _nosick(Permanent(card=_mk_card(name, "{2}", f"Creature - {subtype}", "")))


def _game(*boards, hand=(), interactive=(), active=0):
    game = Game(players=[
        PlayerState(
            name=f"P{seat + 1}", battlefield=list(board),
            hand=list(hand) if seat == 0 else [],
        )
        for seat, board in enumerate(boards)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    return game


@pytest.mark.cr("608.2d")
def test_the_type_is_chosen_while_the_spell_resolves_and_holds_it_on_the_stack():
    """CR 608.2d: a choice the effect offers is announced while the effect is
    applied. The spell is mid-resolution — still on the stack, nothing pumped
    — until its controller names the type."""
    goblin = _creature("Goblin", "Goblin")
    game = _game([goblin], [], hand=[_PUMP], interactive=[0])
    assert game.cast_from_hand(0, "W1G4 Rally").supported

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("creature_type_choice", 0)
    ]
    assert [item.card.name for item in game.stack] == ["W1G4 Rally"]
    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2)

    assert game.confirm_creature_type_choice(0, "goblin")
    resolve_stack(game)
    assert game.stack == []
    assert (goblin.effective_power, goblin.effective_toughness) == (4, 4)


@pytest.mark.cr("611.2c", "613.1d")
def test_the_pumped_set_is_fixed_when_the_effect_begins():
    """CR 611.2c: the set a resolving pump affects is fixed as it begins, read
    through layer 4 (CR 613.1d) — a creature that *is* a Goblin by an effect is
    pumped, and one that becomes a Goblin afterwards is not."""
    became = _creature("Shifted", "Elf")
    gain_types(became, subtypes=("goblin",), source="test")
    late = _creature("Late", "Elf")
    game = _game([became, late], [], hand=[_PUMP], interactive=[0])
    game.cast_from_hand(0, "W1G4 Rally")
    assert game.confirm_creature_type_choice(0, "goblin")
    resolve_stack(game)
    gain_types(late, subtypes=("goblin",), source="test")

    assert became.effective_power == 4
    assert late.effective_power == 2


@pytest.mark.cr("101.4", "101.4b")
def test_each_player_chooses_in_apnap_order_knowing_the_earlier_choices():
    """CR 101.4: the active player chooses first, then each other player in
    turn order, and only then does the action happen. CR 101.4b: each knows
    the choices before theirs. Three seats with P2 active: asked P2, P3, P1 —
    one at a time, each prompt carrying the earlier answers — and the sweep
    waits for the last."""
    p1 = [_creature("P1 Elf", "Elf")]
    p2 = [_creature("P2 Goblin", "Goblin")]
    p3 = [_creature("P3 Zombie", "Zombie"), _creature("P3 Bear", "Bear")]
    game = _game(p1, p2, p3, hand=[_EACH_SWEEP], interactive=[0, 1, 2], active=1)
    assert game.cast_from_hand(0, "W1G4 Census").supported

    asked = []
    for word in ("goblin", "zombie", "elf"):
        (owed,) = game.pending_choices
        asked.append((owed.player_index, owed.data.get("chosen_so_far")))
        assert len(list(game.all_permanents())) == 4, "nothing dies mid-round"
        assert game.confirm_creature_type_choice(owed.player_index, word)
    resolve_stack(game)

    assert asked == [(1, []), (2, ["goblin"]), (0, ["goblin", "zombie"])]
    assert sorted(perm.card.name for perm in game.all_permanents()) == [
        "P1 Elf", "P2 Goblin", "P3 Zombie",
    ]


@pytest.mark.cr("101.4b")
def test_a_later_seats_default_counts_what_earlier_seats_already_named():
    """A seat nobody asks names a type with the earlier answers in view: P2's
    Goblin is already spared by P1's "goblin", so P2 names its Zombie rather
    than the Goblin it holds more of."""
    p1 = [_creature("P1 Goblin", "Goblin")]
    p2 = [_creature("P2 Goblin A", "Goblin"), _creature("P2 Goblin B", "Goblin"),
          _creature("P2 Zombie", "Zombie")]
    game = _game(p1, p2, hand=[_EACH_SWEEP], interactive=[0])
    game.cast_from_hand(0, "W1G4 Census")
    assert game.confirm_creature_type_choice(0, "goblin")
    resolve_stack(game)

    assert sorted(perm.card.name for perm in game.all_permanents()) == [
        "P1 Goblin", "P2 Goblin A", "P2 Goblin B", "P2 Zombie",
    ]


@pytest.mark.cr("614.1c", "614.12a")
def test_an_opponent_makes_the_entry_choice_and_the_controller_cannot():
    """CR 614.1c: "As [this permanent] enters …" is a replacement effect, and
    CR 614.12a makes its choice before the permanent enters — here a choice the
    card gives an *opponent*. The prompt is the opponent's; the controller's
    answer is refused."""
    game = _game([], [_creature("Their Zombie", "Zombie")],
                 hand=[_OPPONENT_CHOOSER], interactive=[0, 1])
    assert game.cast_from_hand(0, "W1G4 Warden").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 1)]
    assert not game.confirm_enter_choice(0, creature_type="goblin")
    assert game.confirm_enter_choice(1, creature_type="zombie")
    warden = next(p for p in game.controlled_by(0) if p.card.name == "W1G4 Warden")
    assert warden.metadata["chosen_creature_type"] == "zombie"


@pytest.mark.cr("611.2b")
def test_for_as_long_as_it_remains_tapped_ends_when_it_untaps_or_leaves():
    """CR 611.2b: a "for as long as" duration ends the moment its condition
    stops holding — untapping the source, or the source leaving the battlefield
    (a permanent that has left is not tapped)."""
    for ending in ("untap", "leave"):
        goblin = _creature("Their Goblin", "Goblin")
        game = _game([], [goblin], hand=[_OPPONENT_CHOOSER], interactive=[1])
        game.cast_from_hand(0, "W1G4 Warden")
        assert game.confirm_enter_choice(1, creature_type="zombie")
        warden = _nosick(next(p for p in game.controlled_by(0) if p.card.name == "W1G4 Warden"))
        assert game.activate_permanent_ability(
            0, "W1G4 Warden", target_permanent_ids=[goblin.permanent_id],
        ).supported
        resolve_stack(game)
        assert game.controller_index_of(goblin) == 0

        if ending == "untap":
            game.become_untapped(warden)
        else:
            game.remove_from_battlefield(warden)
        game.check_state_based_actions()
        assert game.controller_index_of(goblin) == 1, ending


@pytest.mark.cr("615.8", "615.3")
def test_the_class_shield_prevents_one_whole_instance_from_the_next_match():
    """CR 615.8: the next instance of damage, regardless of how much; CR
    615.3: used up once applied. The shield names a class rather than a chosen
    source, so it answers whichever creature of the type deals damage first —
    and only that one, once."""
    goblin_a, goblin_b = _creature("Goblin A", "Goblin"), _creature("Goblin B", "Goblin")
    elf = _creature("Elf", "Elf")
    game = _game([], [goblin_a, goblin_b, elf], hand=[_CLASS_SHIELD])
    game.cast_from_hand(0, "W1G4 Ward")
    resolve_stack(game)
    ward = next(p for p in game.controlled_by(0) if p.card.name == "W1G4 Ward")
    assert ward.metadata["chosen_creature_type"] == "goblin"
    game.activate_permanent_ability(0, "W1G4 Ward")
    resolve_stack(game)

    me = game.players[0]
    assert _damage_dealt(game, me, 2, source=elf) == 2
    assert _damage_dealt(game, me, 7, source=goblin_b) == 0
    assert _damage_dealt(game, me, 1, source=goblin_a) == 1


@pytest.mark.cr("508.1d")
def test_the_attack_requirement_reaches_only_the_named_type():
    """CR 508.1d: the active player obeys the most requirements possible — and
    only the creatures the requirement names carry one. The Goblin must attack;
    the Elf beside it may stay home."""
    drummer = _nosick(Permanent(card=_REQUIREMENT))
    goblin = _creature("Their Goblin", "Goblin")
    elf = _creature("Their Elf", "Elf")
    game = _game([drummer], [goblin, elf], interactive=[0])
    assert game.activate_permanent_ability(0, "W1G4 Drummer").supported
    assert game.confirm_creature_type_choice(0, "goblin")
    resolve_stack(game)

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    slot = {id(perm): index for index, perm in enumerate(game.players[1].battlefield)}
    ok, _ = game.declare_attackers(1, [slot[id(elf)]], defending_player_index=0)
    assert not ok, "the Goblin's requirement is unobeyed"
    ok, why = game.declare_attackers(1, [slot[id(goblin)]], defending_player_index=0)
    assert ok, why
