"""Every card that targets must produce a targeting prompt.

``engine/legality.py`` decides what the UI prompts for by re-parsing raw oracle
text, independently of the ``engine/parsing`` rules that decide what the effect
does. When the two disagree the UI shows no prompt and the spell/ability
silently auto-targets the first legal permanent (``pick_target_permanent``'s
fallback) — the player never gets to choose. These tests pin the cases that
used to slip through and sweep the whole pool so a new card can't reintroduce
the divergence.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.legality import _activated_lines, _cast_lines
from engine.models import Permanent
from engine.oracle import compile_card_oracle

# A line that targets. "of your choice" covers the Circle of Protection /
# Forcefield / Jade Monolith style choices, which also need a prompt.
_TARGETY = re.compile(r"\btarget\b|\bof your choice\b")

# Cards whose targeting choice is deliberately not prompted, with the reason.
# Anything added here is a known approximation, not an oversight.
_ACKNOWLEDGED = {
    "Darkpact": "targets a card in the ante zone, which this engine doesn't model",
    "Eye for an Eye": (
        "the mirror-damage charge is modeled source-agnostically (like Reverse "
        "Damage's), so there is no chosen source to prompt for"
    ),
    "Erhnam Djinn": (
        "its target is chosen by an upkeep trigger; no interactive target-choice "
        "channel exists for upkeep triggers yet"
    ),
}


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _game(*battlefields: list[Permanent]) -> Game:
    players = [
        PlayerState(name=f"P{i + 1}", battlefield=list(bf))
        for i, bf in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game


# ===========================================================================
# Regression cases: each of these used to report kind "none" (no prompt)
# ===========================================================================

def test_king_suleiman_prompts_for_djinn_or_efreet_only(arn_by_name, cards):
    """"{T}: Destroy target Djinn or Efreet." names no creature type, so the
    text classifiers saw no target and the ability auto-destroyed the first
    creature it found."""
    suleiman = _nosick(Permanent(card=arn_by_name["King Suleiman"]))
    djinn = Permanent(card=arn_by_name["Erhnam Djinn"])
    bears = Permanent(card=cards["Grizzly Bears"])
    game = _game([suleiman], [djinn, bears])

    spec = game.activation_target_spec(0, 0)

    assert spec["requires_target"] is True
    assert spec["kind"] == "creature"
    # Only the Djinn — the Bears are not a legal target.
    assert [t["name"] for t in spec["valid_targets"]] == ["Erhnam Djinn"]


def test_elephant_graveyard_prompts_for_elephants_only(arn_by_name, cards):
    """"{T}: Regenerate target Elephant." — ability_index 1, since index 0 is
    the land's mana ability."""
    graveyard = _nosick(Permanent(card=arn_by_name["Elephant Graveyard"]))
    elephant = Permanent(card=arn_by_name["War Elephant"])
    bears = Permanent(card=cards["Grizzly Bears"])
    game = _game([graveyard, elephant, bears], [])

    spec = game.activation_target_spec(0, 0, ability_index=1)

    assert spec["requires_target"] is True
    assert spec["kind"] == "creature"
    assert [t["name"] for t in spec["valid_targets"]] == ["War Elephant"]


def test_aladdin_prompts_for_artifacts_only(arn_by_name, cards):
    """"{1}{R}{R}, {T}: Gain control of target artifact ..." — no activated-side
    artifact classifier existed, so Aladdin stole the first artifact on the
    opponent's battlefield without asking."""
    aladdin = _nosick(Permanent(card=arn_by_name["Aladdin"]))
    lotus = Permanent(card=cards["Black Lotus"])
    bears = Permanent(card=cards["Grizzly Bears"])
    game = _game([aladdin], [lotus, bears])

    spec = game.activation_target_spec(0, 0)

    assert spec["requires_target"] is True
    assert spec["kind"] == "artifact"
    assert [t["name"] for t in spec["valid_targets"]] == ["Black Lotus"]


def test_word_of_command_prompts_for_an_opponent(cards):
    """"Look at target opponent's hand ..." — only "target player" was
    recognized, so the seat defaulted to ``1 - caster_index``. That happens to
    be right in a duel and wrong in a 3+ player game."""
    word = cards["Word of Command"]
    game = _game([], [], [])

    spec = game.cast_target_spec(0, word)

    assert spec["requires_target"] is True
    assert spec["kind"] == "player"
    # Every opponent is offered, and the caster's own seat is not (CR 115.4).
    assert sorted(t["seat"] for t in spec["valid_targets"]) == [1, 2]


def test_icy_manipulator_still_targets_any_permanent(cards):
    """Guard for the new activated-artifact classifier: "target artifact,
    creature, or land" must stay an any-permanent target, not artifact-only."""
    icy = _nosick(Permanent(card=cards["Icy Manipulator"]))
    bears = Permanent(card=cards["Grizzly Bears"])
    game = _game([icy], [bears])

    spec = game.activation_target_spec(0, 0)

    assert spec["kind"] == "permanent"
    # Both are offered — Icy Manipulator is itself a legal "target artifact".
    assert [t["name"] for t in spec["valid_targets"]] == ["Icy Manipulator", "Grizzly Bears"]


def test_death_ward_still_targets_any_creature(cards):
    """Guard for the new regeneration target filter: Death Ward's payload
    carries no subtype, so every creature stays legal."""
    ward = cards["Death Ward"]
    bears = Permanent(card=cards["Grizzly Bears"])
    game = _game([bears], [])

    spec = game.cast_target_spec(0, ward)

    assert spec["kind"] == "creature"
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]


# ===========================================================================
# Whole-pool sweep
# ===========================================================================

def _targeting_cards(all_cards, arn_cards):
    seen: set[str] = set()
    for card in list(all_cards) + list(arn_cards):
        if card.name in seen:
            continue
        seen.add(card.name)
        if not compile_card_oracle(card).supported:
            continue
        cast = [l for l in _cast_lines(card) if _TARGETY.search(l)]
        act = [l for l in _activated_lines(card) if _TARGETY.search(l)]
        if cast:
            yield pytest.param(card, "cast", cast[0], id=f"{card.name}-cast")
        if act:
            yield pytest.param(card, "activated", act[0], id=f"{card.name}-activated")


def test_every_targeting_card_is_swept(all_cards, arn_cards):
    """The sweep below is only meaningful if it actually covers the pool."""
    assert len(list(_targeting_cards(all_cards, arn_cards))) > 100


def test_no_targeting_card_lacks_a_prompt(all_cards, arn_cards):
    """Every supported card whose oracle text targets must classify to a target
    kind, so the UI raises a prompt instead of the engine auto-targeting.

    A genuine exception goes in ``_ACKNOWLEDGED`` with its reason.
    """
    game = _game([], [])
    missing: list[str] = []
    for param in _targeting_cards(all_cards, arn_cards):
        card, side, line = param.values
        if card.name in _ACKNOWLEDGED:
            continue
        if side == "cast":
            kind = game.cast_target_spec(0, card)["kind"]
        else:
            perm = _nosick(Permanent(card=card))
            game.players[0].battlefield.append(perm)
            idx = len(game.players[0].battlefield) - 1
            kind = game.activation_target_spec(0, idx)["kind"]
            game.players[0].battlefield.pop()
        if kind == "none":
            missing.append(f"{card.name} ({side}): {line.strip()!r}")
    assert not missing, (
        "these cards target but produce no targeting prompt — the engine will "
        "silently auto-target:\n  " + "\n  ".join(missing)
    )


def test_acknowledged_exceptions_still_target(all_cards, arn_cards):
    """Keeps ``_ACKNOWLEDGED`` honest: an entry whose card no longer targets (or
    no longer exists) is stale and should be deleted."""
    targeting = {p.values[0].name for p in _targeting_cards(all_cards, arn_cards)}
    stale = sorted(set(_ACKNOWLEDGED) - targeting)
    assert not stale, f"stale _ACKNOWLEDGED entries: {stale}"
