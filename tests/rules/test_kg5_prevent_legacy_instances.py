"""Jade Monolith and Eye for an Eye take CR 615.8's **whole instance** — every
chunk their chosen source deals their one recipient in one simultaneous
dealing (the project owner's ruling, 2026-11-07) — now that each arms a record
the dealing reaches.

* Jade Monolith: "{1}: The next time a source of your choice would deal damage
  to target creature this turn, that source deals that damage to you instead."
  A ``damage_redirects.DamageRedirect`` on the creature (it was a metadata
  pair named for the card, spent per chunk, and matched the chosen source by
  *card* — a second Prodigal Sorcerer's ping moved too).
* Eye for an Eye: "The next time a source of your choice would deal damage to
  you this turn, instead that source deals that much damage to you and Eye for
  an Eye deals that much damage to that source's controller." A
  ``next_damage.DamageMirror`` on the caster (it was two ``PlayerState``
  fields, spent per chunk); the mirrored damage for one instance is dealt once,
  for the total, as the dealing finishes — Honorable Passage's shape.

A dealing hits one recipient twice from one source when a split sentence names
it for both halves: Cuombajj Witches ("This creature deals 1 damage to any
target and 1 damage to any target of an opponent's choice"), the opponent
answering with the same object. Validated backwards: on the base
(``59f133e6``) both two-chunk boards and the look-alike board fail; the
one-chunk controls pass on both.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _table(catalog_by_name, interactive, *, hand0=()):
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20,
                    hand=[catalog_by_name[name] for name in hand0]),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    return game


def _put(game, catalog_by_name, seat, name):
    permanent = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _slot(game, seat, permanent) -> int:
    return next(i for i, p in enumerate(game.controlled_by(seat)) if p is permanent)


def _witches(game, *, first: dict, second: dict | None):
    """Bob activates his Cuombajj Witches with *first* as its target; Alice,
    asked for the second half's target (an interactive seat), answers
    *second* — or, nobody asked, takes the prompt's default."""
    game.active_player_index = 1
    result = game.activate_permanent_ability(1, "Cuombajj Witches", **first)
    assert result.supported, result.details
    if second is not None:
        for _ in range(6):
            if game.pending_choices or not game.stack:
                break
            game.resolve_top_of_stack(pause_for_choices=True)
        choice = game.pending_choice_of("opponent_damage")
        assert choice is not None and choice.player_index == 0, game.pending_choices
        assert game.confirm_opponent_damage_choice(0, **second)
    settle(game)


def _lives(game):
    return [player.life for player in game.players]


# ---------------------------------------------------------------------------
# Jade Monolith
# ---------------------------------------------------------------------------


def _jade_on_bears(catalog_by_name, interactive, *, named="Cuombajj Witches"):
    game = _table(catalog_by_name, interactive)
    _put(game, catalog_by_name, 0, "Jade Monolith")
    bears = _put(game, catalog_by_name, 0, "Grizzly Bears")
    source = _put(game, catalog_by_name, 1, named)
    armed = game.activate_permanent_ability(
        0, "Jade Monolith", target_permanent_ids=[bears.permanent_id],
        source_seat=1, source_permanent_index=_slot(game, 1, source),
    )
    assert armed.supported, armed.details
    settle(game)
    return game, bears, source


@pytest.mark.cr("615.8", "614.9", "608.2f")
def test_jade_monolith_moves_both_witches_chunks_at_its_creature(catalog_by_name):
    """Bob's Witches name Alice's Bears for both halves (Alice answers the
    second with the Bears): one dealing, one instance, and both points are
    dealt to Alice instead. The Witches' next dealing is another time."""
    game, bears, witches = _jade_on_bears(catalog_by_name, {0})
    _witches(
        game, first={"target_permanent_ids": [bears.permanent_id]},
        second={"target_seat": 0, "permanent_id": bears.permanent_id},
    )
    assert bears.damage_marked == 0, game.log
    assert _lives(game) == [18, 20], game.log
    assert sum("is dealt to Alice instead (Jade Monolith)" in line for line in game.log) == 2

    witches.tapped = False
    _witches(
        game, first={"target_permanent_ids": [bears.permanent_id]},
        second={"target_seat": 1},
    )
    assert bears.damage_marked == 1, game.log
    assert _lives(game) == [18, 19], game.log


@pytest.mark.cr("615.8", "614.9")
def test_jade_monolith_one_chunk_at_its_creature_nobody_asked(catalog_by_name):
    """The control, at a table nobody is asked at: Alice's default for the
    second half is Bob's face, so the Bears are dealt one chunk, moved."""
    game, bears, _witches_permanent = _jade_on_bears(catalog_by_name, set())
    _witches(game, first={"target_permanent_ids": [bears.permanent_id]}, second=None)
    assert bears.damage_marked == 0, game.log
    assert _lives(game) == [19, 19], game.log


@pytest.mark.cr("615.8", "609.7a")
@pytest.mark.parametrize("interactive", [pytest.param(set(), id="nobody-asked"),
                                         pytest.param({0, 1}, id="interactive")])
def test_jade_monolith_answers_the_named_permanent_not_its_twin(catalog_by_name, interactive):
    """Jade Monolith names one of Bob's two Prodigal Sorcerers. The other's
    ping is another source — it hits the Bears — and the named one's moves.
    (The metadata pair matched by card: both moved.)"""
    game, bears, named = _jade_on_bears(catalog_by_name, interactive, named="Prodigal Sorcerer")
    twin = _put(game, catalog_by_name, 1, "Prodigal Sorcerer")
    game.active_player_index = 1

    def ping(sorcerer) -> None:
        result = game.activate_permanent_ability(
            1, "Prodigal Sorcerer", permanent_index=_slot(game, 1, sorcerer),
            target_permanent_ids=[bears.permanent_id],
        )
        assert result.supported, result.details
        settle(game)

    ping(twin)
    assert bears.damage_marked == 1, game.log
    assert _lives(game) == [20, 20], game.log
    ping(named)
    assert bears.damage_marked == 1, game.log
    assert _lives(game) == [19, 20], game.log


# ---------------------------------------------------------------------------
# Eye for an Eye
# ---------------------------------------------------------------------------


def _eye_on_witches(catalog_by_name, interactive):
    game = _table(catalog_by_name, interactive, hand0=["Eye for an Eye"])
    witches = _put(game, catalog_by_name, 1, "Cuombajj Witches")
    cast = game.cast_from_hand(
        0, "Eye for an Eye", target_player_index=1,
        target_permanent_ids=[witches.permanent_id],
    )
    assert cast.supported, cast.details
    settle(game)
    return game, witches


@pytest.mark.cr("615.8", "614.1a", "608.2f")
def test_eye_for_an_eye_mirrors_both_witches_chunks_at_you_once(catalog_by_name):
    """Bob's Witches name Alice for both halves: she is dealt 2 in one
    dealing, and Eye for an Eye deals that much — 2, one event — to Bob."""
    game, _witches_permanent = _eye_on_witches(catalog_by_name, {0})
    _witches(game, first={"target_player_index": 0}, second={"target_seat": 0})
    assert _lives(game) == [18, 18], game.log
    mirrored = [line for line in game.log if "mirroring the damage" in line]
    assert mirrored == ["2 damage is dealt to Bob, mirroring the damage dealt to Alice"], mirrored


@pytest.mark.cr("615.8", "614.1a")
def test_eye_for_an_eye_one_chunk_at_you_nobody_asked(catalog_by_name):
    """The control: Alice's default for the second half is Bob's face, so she
    is dealt one chunk and mirrors 1 — and Bob is dealt his own 1 too."""
    game, _witches_permanent = _eye_on_witches(catalog_by_name, set())
    _witches(game, first={"target_player_index": 0}, second=None)
    assert _lives(game) == [19, 18], game.log
