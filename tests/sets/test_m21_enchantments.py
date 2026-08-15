"""Core Set 2021 (M21) enchantments — the Auras among them.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.auras import detach_aura
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- An Aura is more than its first line ------------------------------------


@pytest.mark.parametrize("name", ["Capture Sphere", "Dub", "Furor of the Bitten"])
def test_round_36_aura_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _enchant(set_pool, aura_name, victim_name, victim_seat=0):
    pool = set_pool("M21")
    victim = Permanent(card=pool[victim_name])
    hand = [pool[aura_name]]
    if victim_seat == 0:
        p1 = PlayerState(
            name="P1", battlefield=[victim], hand=hand, library=[pool["Plains"]] * 4
        )
        p2 = PlayerState(name="P2")
    else:
        p1 = PlayerState(name="P1", hand=hand, library=[pool["Plains"]] * 4)
        p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    result = game.cast_from_hand(
        0, aura_name, target_player_index=victim_seat, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()
    aura = next(p for p in p1.battlefield if p.card.name == aura_name)
    return game, aura, victim


def test_capture_sphere_attaches_even_though_flash_is_printed_first(set_pool):
    """The enchant clause is *found*, not assumed to be line 0. Capture Sphere
    prints "Flash" above it, and every reader of that clause answered no — so
    the Aura resolved, entered the battlefield, and attached to nothing while
    reporting itself supported."""
    game, aura, victim = _enchant(set_pool, "Capture Sphere", "Alpine Watchdog", 1)

    assert aura.metadata.get("attached_to") is victim
    assert victim.tapped, "its enters trigger taps what it enchants"

    game.start_turn(1)
    assert victim.tapped, "and it does not untap during its controller's untap step"


def test_dub_grants_a_creature_type_alongside_its_pt_and_keyword(set_pool):
    """One printed line in three CR 613 layers — 7c, 6 and 4 — and each half is
    read by the reader that owns that layer. A Dog stays a Dog: the type is
    added, never replacing (which is what separates this from a land-type
    change, CR 305.7)."""
    game, aura, victim = _enchant(set_pool, "Dub", "Alpine Watchdog")

    assert (victim.effective_power, victim.effective_toughness) == (4, 4)
    assert game._has_keyword(victim, "first strike")
    assert victim.has_type("knight")
    assert victim.has_type("dog"), "'in addition to its other types'"


def test_dubs_grants_all_end_when_it_leaves(set_pool):
    """Derived from the Aura's own text on every recompute, so detaching is
    simply ceasing to contribute — there is no remembered delta to undo, which
    is the whole reason the type grant is a layer-4 effect and not a stamp."""
    game, aura, victim = _enchant(set_pool, "Dub", "Alpine Watchdog")

    detach_aura(aura, victim)
    game.remove_from_battlefield(aura)
    game._recompute_continuous_effects()

    assert (victim.effective_power, victim.effective_toughness) == (2, 2)
    assert not victim.has_type("knight")
    assert not game._has_keyword(victim, "first strike")


def test_furor_of_the_bitten_forces_its_creature_to_attack(set_pool):
    """CR 508.1a. The requirement is asked of the attached Auras rather than
    stamped on the creature, so it ends with the Aura."""
    pool = set_pool("M21")
    bitten = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    other = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(
        name="P1", battlefield=[bitten, other],
        hand=[pool["Furor of the Bitten"]], library=[pool["Swamp"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(
        0, "Furor of the Bitten", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert (bitten.effective_power, bitten.effective_toughness) == (4, 4), "the P/T half too"

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers

    ok, msg = game.declare_attackers(0, [1])
    assert not ok and "must attack" in msg
    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg


def test_an_invented_creature_type_refuses_the_whole_line(set_pool):
    """The gate and the grant read the same vocabulary. A type outside it would
    be claimed here and granted nothing — the hollow-support shape this module
    exists to prevent — so the line is unclaimed instead."""
    from engine.auras import aura_effect_claim, aura_type_grants
    from engine.oracle import normalize_creature_line

    real = normalize_creature_line(
        "Enchanted creature gets +2/+2, has flying, and is a Demon in addition to its other types."
    )
    invented = normalize_creature_line(
        "Enchanted creature gets +2/+2, has flying, and is a Glorb in addition to its other types."
    )

    assert aura_effect_claim(real) is not None
    assert aura_type_grants(real) == ("demon",)
    assert aura_effect_claim(invented) is None
    assert aura_type_grants(invented) == ()
