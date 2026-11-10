"""A copy of a spell with **several targets or a mode** is offered new
targets (CR 707.10c), slot by slot (CR 115.7d) — the census.

    707.10c Some effects copy a spell or ability and state that its
    controller may choose new targets for the copy. The player may leave any
    number of the targets unchanged, even if those targets would be illegal.

    115.8. … An effect that allows a player to change the target(s) of a
    modal spell or ability, or to choose new targets for a modal spell or
    ability, doesn't allow that player to change its mode.

``spell_copies._offer_copy_new_target`` offered one permanent or player
(``copy_spell_target``), or one card in a graveyard or one spell
(``retarget_choice``) — and kept every other copy on its original's targets:
``stack_targets.change_slots`` refused a modal spell outright, and the offer
declined any copy with more than one slot (the Known-gaps "AI leftovers"
entry, kg4). So a Forked Funeral Charm, Reckless Spite, Arc Lightning or
Consume Strength aimed at the forker's own creatures hit them again.

The population is every pool instant and sorcery (both manifest roles,
``faces.compilation_units``) with a targeted mode, or whose one announcement
can name several targets (a printed count, "up to", "any number", a division,
or the word "target" printed more than once), read off the compiled program.
Each is cast by seat 1 at seat 0's permanents through the engine's own
picker list (``_enumerate_targets``), then Forked by seat 0 — an interactive
seat — and seat 0 must be asked for the copy's new targets, unless the copy's
announcement is a shape ``change_slots`` names a refusal for
(:data:`_DECLINED`), or there is nowhere else to aim it.
"""

from __future__ import annotations

import re
from collections import Counter

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.divided_damage import spread_shares
from engine.faces import compilation_units
from engine.legality import _cast_lines, exact_target_count
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.picker_probes import line_names_a_cast_target
from engine.stack_targets import (
    _REMINDER_TEXT, _spec_targets, _target_instances, change_slots,
    new_target_options,
)
from engine.targeting import _from_instructions, derive_cast_spec, spec_roles

#: The refusals ``change_slots`` keeps for a copy — each an under-offer (the
#: copy keeps its original's targets), never a target it could not have
#: chosen — and why. Asserted to be the only reasons seen.
_DECLINED = {
    # "Tap target creature. It deals damage … to another target creature"
    # (Deadshot), "Target player shuffles up to three target cards from their
    # graveyard" (Gaea's Blessing): instances with different descriptions, or
    # a second instance the one spec does not carry.
    'it uses the word "target" more than once',
    # Donate, Decimate: one spec per role, each its own candidate walk.
    "its targets answer different descriptions",
}

#: Floors on what the census examined (kg5: 213 rows, 136 asked).
_ROWS_FLOOR = 180
_ASKED_FLOOR = 120

_BOARD = (
    "Grizzly Bears", "Hill Giant", "Gray Ogre", "Ornithopter", "Crusade",
    "Forest", "Wall of Stone",
)


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()


def _population() -> list:
    """``(unit, mode index or None, spec, instruction)`` for every row."""
    rows = []
    for unit in compilation_units(list(_POOL.values())):
        printed = (unit.type_line or "").lower()
        if "instant" not in printed and "sorcery" not in printed:
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if program.modes:
            for index, option in enumerate(program.modes):
                if option.instruction is None:
                    continue
                spec = _from_instructions((option.instruction,))
                if _spec_targets(spec):
                    rows.append((unit, index, spec, option.instruction))
            continue
        spec = derive_cast_spec(unit, program)
        if not _spec_targets(spec):
            continue
        instances = sum(
            _target_instances(line) for line in _cast_lines(unit)
            if line_names_a_cast_target(_REMINDER_TEXT.sub("", line))
        )
        several = (
            spec.get("max_targets") not in (None, 1) or spec.get("unbounded_targets")
            or spec.get("kind") == "divided" or spec_roles(spec) or instances > 1
        )
        if several:
            rows.append((unit, None, spec, program.instructions[0] if program.instructions else None))
    return rows


_ROWS = _population()


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(spell) -> Game:
    seats = [
        PlayerState(
            name=name, battlefield=[_permanent(each) for each in _BOARD],
            library=[_POOL["Island"]] * 10,
            graveyard=[_POOL["Grizzly Bears"], _POOL["Hill Giant"]],
        )
        for name in ("A", "B")
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(1)
    seats[1].hand = [spell]
    seats[0].hand = [_POOL["Fork"]]
    return game


def _how_many(spec, instruction) -> int:
    count = exact_target_count(spec, instruction, 2)
    if count:
        return count
    top = spec.get("max_targets")
    if isinstance(top, int) and top > 1:
        return top
    return 2 if spec.get("unbounded_targets") else 1


def _announcement(game, unit, spec, mode_index, instruction, *, total=None, exact=None):
    """An announcement out of the picker's own list, seat 0's things first,
    or None where this census cannot write one (a role, a spell target)."""
    entries = game._enumerate_targets(1, unit, spec, for_cast=True, mode_index=mode_index)
    permanents = sorted(
        (e for e in entries if e.get("kind") == "permanent"), key=lambda e: e["seat"] != 0,
    )
    yards = sorted(
        (e for e in entries if e.get("kind") == "graveyard"), key=lambda e: e["seat"] != 0,
    )
    players = [e for e in entries if e.get("kind") == "player"]
    announced: dict = {"x_value": 2}
    if mode_index is not None:
        announced["mode_index"] = mode_index
    if spec.get("kind") == "divided":
        count = exact or 2
        picks = permanents[:count]
        if len(picks) < count:
            return None
        if total is not None:
            shares = spread_shares(total, count)
            announced["divided_targets"] = [
                (e["seat"], e["index"], share) for e, share in zip(picks, shares)
            ]
        elif spec.get("division") == "chosen":
            announced["divided_targets"] = [(e["seat"], e["index"], 1) for e in picks]
        else:
            announced["divided_targets"] = [(e["seat"], e["index"]) for e in picks]
        return announced
    count = _how_many(spec, instruction)
    if yards and not permanents:
        same = [e for e in yards if e["seat"] == yards[0]["seat"]][:count]
        if len(same) < count:
            return None
        announced["target_player_index"] = same[0]["seat"]
        announced["target_permanent_index"] = (
            [e["index"] for e in same] if count > 1 else same[0]["index"]
        )
        return announced
    if permanents:
        picks = permanents[:count]
        if len(picks) < count:
            return None
        announced["target_permanent_ids"] = [
            game.permanent_at(e["seat"], e["index"]).permanent_id for e in picks
        ]
        announced["target_player_index"] = picks[0]["seat"]
        return announced
    if players:
        announced["target_player_index"] = (
            0 if any(p["seat"] == 0 for p in players) else players[0]["seat"]
        )
        return announced
    return None


def _forked(unit, mode_index, spec, instruction):
    """The table after seat 1 casts the row and seat 0's Fork resolves, or a
    string saying why the row was not cast."""
    game = _table(unit)
    announced = _announcement(game, unit, spec, mode_index, instruction)
    if announced is None:
        return "unannounced"
    cast = game.queue_from_hand(1, unit.name, **announced)
    if not cast.supported:
        # The division's printed total, or its exact count, said by the gate.
        total = re.search(r"must total (\d+)", cast.details or "")
        exact = re.search(r"has exactly (\d+) targets", cast.details or "")
        if not (total or exact):
            return "refused"
        game = _table(unit)
        announced = _announcement(
            game, unit, spec, mode_index, instruction,
            total=int(total.group(1)) if total else None,
            exact=int(exact.group(1)) if exact else None,
        )
        if announced is None:
            return "unannounced"
        cast = game.queue_from_hand(1, unit.name, **announced)
        if not cast.supported:
            return "refused"
    game.priority_player_index = 0
    fork = game.queue_from_hand(0, "Fork", target_stack_index=0)
    assert fork.supported, (unit.name, fork.details)
    game.resolve_top_of_stack()
    return game


def test_every_copy_with_several_targets_or_a_mode_is_offered_new_targets():
    outcome: Counter = Counter()
    wrong, reasons = [], set()
    examined = 0
    for unit, mode_index, spec, instruction in _ROWS:
        examined += 1
        game = _forked(unit, mode_index, spec, instruction)
        if isinstance(game, str):
            outcome[game] += 1
            continue
        copy = next((item for item in game.stack if item.is_copy), None)
        assert copy is not None, (unit.name, game.log[-4:])
        if any(choice.player_index == 0 for choice in game.pending_choices):
            outcome["asked"] += 1
            continue
        slots = change_slots(game, copy)
        if isinstance(slots, str):
            reasons.add(slots)
            outcome["declined"] += 1
            continue
        if not any(new_target_options(slots, [], p) for p in range(len(slots))):
            outcome["nowhere to go"] += 1
            continue
        wrong.append((unit.name, mode_index, len(slots)))
    assert wrong == [], wrong
    assert reasons <= _DECLINED, reasons - _DECLINED
    assert examined == len(_ROWS) >= _ROWS_FLOOR, examined
    assert outcome["asked"] >= _ASKED_FLOOR, outcome
