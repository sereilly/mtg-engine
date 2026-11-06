"""A defending seat nobody sits in, assigning a trampler's combat damage, keeps
it on the creature blocking it (CR 702.22j, CR 702.19b).

Where the **defending** player assigns an attacker's combat damage — a
creature with banding is blocking it (CR 702.22j), or the defender controls
Defensive Formation ("Rather than the attacking player, you assign the combat
damage of each creature attacking you") — a trampler blocked by one creature,
with more than lethal damage to assign, is a choice: lethal damage to the
blocker first, and the excess "as its controller chooses among those blocking
creatures and the player" (CR 702.19b), which under banding is the defender's
choice. A person is asked (kg3, ``trample_assignments_to_ask``). A seat nobody
sits in was handed nothing and kept the engine's default — lethal to the
blocker and the rest *to itself*: the split the attacker would have chosen
(Known gap "An AI defender under banding never weighs a trampler's excess").

The blocker dies either way (it is assigned at least lethal damage), so the
excess is the whole decision, and the least damage to the defending player is
all of it on the blocker. ``Game.defender_assignments_owed`` now lists the
trampler for every defending seat, and the defender's chooser
(``ai_combat.choose_defender_damage_assignment``) keeps it on the blocker.

The census is every supported trampler in the pool attacking alone into one
vanilla 0/1 with banding and reach, with an AI on both seats, through the
engine's own steps; whether the board is the choice is read off the board
before the damage step. Measured backwards (the defender's chooser switched
off — what the base did, since the list left the trampler out for a seat
nobody sits in): every trampler examined trampled over.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from engine import Game, PlayerState
from engine import ai_combat
from engine.ai_combat import run_ai_combat_phase
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import combat_damage_assigned_by
from engine.models import Permanent
from engine.oracle import compiled_units
from tests.helpers import _mk_creature_card

LIFE = 100


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


@pytest.fixture(scope="module")
def tramplers(pool):
    return [
        card for card, program in compiled_units(pool.values())
        if program.supported
        and "Creature" in (card.type_line or "")
        and "trample" in (card.oracle_text or "").lower()
    ]


def _bander(name="Census Bander", power=0, toughness=1):
    card = _mk_creature_card(name, power, toughness, "Banding\nReach")
    return replace(card, keywords=("Banding", "Reach"))


def _combat(attacker_card, blocker_card, *, beside=()):
    """*attacker_card* attacking alone for seat 0 into *blocker_card* (seat
    1), stopped with the block declared. Returns ``(game, attacker, blocker,
    choice)`` — *choice* read off the board at the block: trample through the
    layers, one creature blocking, more than its lethal damage to assign, and
    the defending seat the one assigning — or None where the board cannot be
    reached. Both seats are AI seats."""
    me, opp = PlayerState(name="Me"), PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    me.life = opp.life = LIFE
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    blocker = Permanent(card=blocker_card)
    game._put_permanent_onto_battlefield(1, blocker, None)
    for card in beside:
        game._put_permanent_onto_battlefield(1, Permanent(card=card), None)
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    if game.current_step != "declare_attackers":
        return None
    if not game.declare_attackers(0, [0], defending_player_index=1)[0]:
        return None
    game.advance_combat_phase()
    if game.current_step != "declare_blockers":
        return None
    if not game.declare_blockers(1, {0: 0})[0]:
        return None
    lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
    if lethal and game._has_keyword(attacker, "deathtouch"):
        lethal = 1
    choice = (
        game.is_on_battlefield(attacker)
        and game._has_keyword(attacker, "trample")
        and game._attacker_all_blockers(0) == [0]
        and combat_damage_assigned_by(attacker) > lethal
        and game.combat_damage_assigner(0) == 1
    )
    return game, attacker, blocker, choice


def _combat_damage_to(game, seat_name: str) -> list[str]:
    """The log's combat damage lines naming *seat_name* as the recipient —
    combat damage only: a trigger's damage (Axelrod Gunnarson's) is not the
    assignment under test."""
    return [line for line in game.log if line.startswith(f"{seat_name} took") and "combat damage" in line]


def _census(tramplers) -> dict:
    found = {
        "unreached": [], "no_choice": [], "two_steps": [], "kept": [],
        "trampled_over": [], "unresolved": [],
    }
    for card in tramplers:
        built = _combat(card, _bander())
        if built is None:
            found["unreached"].append(card.name)
            continue
        game, attacker, blocker, choice = built
        if not choice:
            found["no_choice"].append(card.name)
            continue
        if game._has_keyword(attacker, "double strike"):
            # Its second step finds no creature blocking it, and CR 702.19d
            # sends that step's damage to the player whoever assigns: not the
            # choice under test.
            found["two_steps"].append(card.name)
            continue
        game.advance_combat_phase()
        if not game.combat_damage_resolved:
            found["unresolved"].append(card.name)
            continue
        over = _combat_damage_to(game, "Opp")
        if not over and not game.is_on_battlefield(blocker):
            found["kept"].append(card.name)
        else:
            found["trampled_over"].append((card.name, over[:1]))
    return found


@pytest.mark.cr("702.22j", "702.19b")
def test_every_banded_trampler_is_kept_on_its_blocker(tramplers):
    found = _census(tramplers)

    assert len(tramplers) >= 140, f"only {len(tramplers)} tramplers in the pool"
    examined = len(found["kept"]) + len(found["trampled_over"])
    assert examined >= 85, f"only {examined} tramplers reached the choice: {found['no_choice'][:8]}"
    assert found["unresolved"] == [], found["unresolved"][:8]
    assert found["trampled_over"] == [], found["trampled_over"][:8]


@pytest.mark.cr("702.22j", "702.19b")
def test_the_census_names_every_trampler_with_the_chooser_switched_off(tramplers, monkeypatch):
    """Backwards, every run: with the defender's chooser answering nothing —
    the base, where the trampler was not on the defender's list — every
    trampler examined goes over its blocker for the excess."""
    monkeypatch.setattr(ai_combat, "choose_defender_damage_assignment", lambda game, seat: ({}, []))
    found = _census(tramplers)

    assert len(found["trampled_over"]) >= 85, len(found["trampled_over"])
    assert found["kept"] == [], found["kept"][:8]


def _war_mammoth_into(pool, blocker_card, *, beside=(), site: str):
    game, attacker, blocker, choice = _combat(pool["War Mammoth"], blocker_card, beside=beside)
    assert choice
    if site == "driver":
        run_ai_combat_phase(game, 0)
    else:
        game.advance_combat_phase()
    assert game.combat_damage_resolved or game.current_turn_phase != "combat"
    return game, blocker


@pytest.mark.cr("702.22j", "702.19b")
@pytest.mark.parametrize("site", ["driver", "step"])
def test_war_mammoth_into_a_benalish_hero(pool, site):
    """War Mammoth (3/3, trample) blocked by Benalish Hero (1/1, banding):
    the defender assigns, and keeps all three on the Hero — which dies as it
    would have to one point — rather than taking two."""
    game, hero = _war_mammoth_into(pool, pool["Benalish Hero"], site=site)
    assert game.players[1].life == LIFE
    assert not game.is_on_battlefield(hero)
    assert not any("Opp took" in line for line in game.log), game.log[-6:]


@pytest.mark.cr("510.1c", "702.19b")
def test_under_defensive_formation_it_is_the_same_choice(pool):
    """Defensive Formation: "Rather than the attacking player, you assign the
    combat damage of each creature attacking you." No banding anywhere — the
    printed substitution is the other road to the defender's chair."""
    game, chump = _war_mammoth_into(
        pool, _mk_creature_card("Their Chump", 1, 1), beside=(pool["Defensive Formation"],),
        site="step",
    )
    assert game.players[1].life == LIFE
    assert not game.is_on_battlefield(chump)


@pytest.mark.cr("702.22j")
def test_a_blocker_that_would_survive_lethal_still_takes_it_all(pool):
    """A 0/5 with banding in front of the Mammoth: lethal is five, the
    Mammoth assigns three, so there is no excess and no choice — all of it
    on the blocker, which lives."""
    built = _combat(pool["War Mammoth"], _bander("Their Bulwark", 0, 5))
    game, _attacker, wall, choice = built
    assert not choice
    game.advance_combat_phase()
    assert game.players[1].life == LIFE
    assert game.is_on_battlefield(wall) and wall.damage_marked == 3
