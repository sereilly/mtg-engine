"""Pool census: every trampler a person attacks with into one blocker, with
damage to spare, is **asked** where its excess goes (CR 702.19b) — and a seat
nobody sits in keeps the lethal-then-the-rest split it always had.

Known gap "Trample damage is assigned without asking a human attacker": with
one blocker the combat damage step resolved as it was entered, lethal to the
blocker and the rest to the player, so the attacker could not put more on the
blocker (Scion of Darkness: a 3/3 split). No compiled-program instrument sees
it — every trampler compiled, and played the default.

The population is every supported creature in both manifest roles whose text
says "trample", each attacking alone into a vanilla 0/1 with reach (so a
flyer is blockable) through the engine's own steps. Whether the board is a
choice is read **before** the damage step from the board itself — the
attacker has trample (layer 6), exactly one creature blocks it, and it
assigns more than that creature's lethal 1 — so a step that resolves without
asking is a miss, not a creature without a choice. Cards that cannot reach
that board (a "can't be blocked by" restriction, an entry prompt that holds
the turn, a 0-power body) are counted and left out; the floors say how much
was examined.

Measured backwards (the fix switched off, ``trample_assignments_to_ask``
answering nothing): asked 0 of 93; with it, 93 of 93. The default half reads
93 of 93 on both trees.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import combat_damage_assigned_by
from engine.models import Permanent
from engine.oracle import compiled_units

from tests.helpers import _mk_creature_card


@pytest.fixture(scope="module")
def tramplers():
    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return [
        card for card, program in compiled_units(pool.values())
        if program.supported
        and "Creature" in (card.type_line or "")
        and "trample" in (card.oracle_text or "").lower()
    ]


def _combat(card, blockers: int, interactive):
    """*card* attacking alone for seat 0 into *blockers* 0/1 reach chumps.
    Returns ``(game, attacker, chumps, choice)`` — *choice* read at the block,
    before the damage step — or None where the board cannot be reached."""
    me, opp = PlayerState(name="Me"), PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    me.life = opp.life = 100
    attacker = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    chumps = []
    for number in range(blockers):
        chump = Permanent(card=_mk_creature_card(f"Census Chump {number}", 0, 1, "Reach"))
        game._put_permanent_onto_battlefield(1, chump, None)
        chumps.append(chump)
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    if not game.declare_attackers(0, [0], defending_player_index=1)[0]:
        return None
    game.advance_combat_phase()
    if not game.declare_blockers(1, {slot: 0 for slot in range(blockers)})[0]:
        return None
    choice = (
        game.is_on_battlefield(attacker)
        and game._has_keyword(attacker, "trample")
        and len(game._attacker_all_blockers(0)) == blockers
        and combat_damage_assigned_by(attacker) > 1
    )
    game.advance_combat_phase()
    return game, attacker, chumps, choice


def _waiting(game, chumps) -> bool:
    return (
        game.current_step == "combat_damage"
        and not game.combat_damage_resolved
        and game.players[1].life == 100
        and all(chump.damage_marked == 0 for chump in chumps)
    )


def _census(tramplers) -> dict:
    found = {"unreached": [], "no_choice": [], "asked": [], "missed": [],
             "answered": [], "default": [], "default_moved": []}
    for card in tramplers:
        built = _combat(card, 1, (0,))
        if built is None:
            found["unreached"].append(card.name)
            continue
        game, attacker, chumps, choice = built
        if not choice:
            found["no_choice"].append(card.name)
            continue
        if not _waiting(game, chumps):
            found["missed"].append(card.name)
            continue
        found["asked"].append(card.name)
        power = combat_damage_assigned_by(attacker)
        # The answer a person could not give before: all of it on the blocker.
        ok, _why = game.resolve_combat_damage(0, attacker_damage={0: {0: power}})
        if ok and game.players[1].life == 100 and not any(
            "Opp took" in line for line in game.log
        ):
            found["answered"].append(card.name)
        # …and a seat nobody sits in: lethal to the blocker, the rest past it.
        game, attacker, chumps, _choice = _combat(card, 1, ())
        power = combat_damage_assigned_by(attacker)
        if game.combat_damage_resolved and any(
            f"Opp took {power - 1} combat damage" in line for line in game.log
        ):
            found["default"].append(card.name)
        else:
            found["default_moved"].append(card.name)
    return found


def test_every_trampler_with_damage_to_spare_is_asked(tramplers):
    found = _census(tramplers)

    assert len(tramplers) >= 140, f"only {len(tramplers)} tramplers in the pool"
    assert len(found["asked"]) >= 85, (
        f"only {len(found['asked'])} tramplers reached a single block with a choice"
    )
    assert found["missed"] == [], "resolved without asking: " + ", ".join(found["missed"])
    assert sorted(found["answered"]) == sorted(found["asked"]), (
        "an answer the gate refused: "
        + ", ".join(sorted(set(found["asked"]) - set(found["answered"])))
    )


def test_a_seat_nobody_sits_in_keeps_the_lethal_then_rest_split(tramplers):
    found = _census(tramplers)

    assert len(found["default"]) >= 85
    assert found["default_moved"] == [], ", ".join(found["default_moved"])


def test_two_blockers_are_a_division_and_not_a_second_question(tramplers):
    """The arm that already stopped every seat, unchanged by this one."""
    examined = 0
    for card in tramplers:
        built = _combat(card, 2, (0,))
        if built is None or not built[3]:
            continue
        game, _attacker, chumps, _choice = built
        examined += 1
        assert _waiting(game, chumps), card.name
        assert game.trample_assignments_to_ask() == [], card.name
    assert examined >= 80, examined


def test_the_census_names_a_miss_when_the_question_is_switched_off(tramplers, monkeypatch):
    """Backwards, every run: with the list answering nothing the step resolves
    on entering and the census names every trampler it examined."""
    monkeypatch.setattr(Game, "trample_assignments_to_ask", lambda self, seat=None: [])
    found = _census(tramplers)

    assert found["asked"] == []
    assert len(found["missed"]) >= 85
