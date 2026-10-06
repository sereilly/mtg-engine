"""Census: does an AI seat reach every mode of every modal instant and sorcery?

The pool-wide half of ``test_ai_mode_chooser.py``. 34 instants and sorceries
print a "Choose one —" head their caster answers, 88 modes between them, and
until the policy had a mode to name (``CastAction.mode_index``) an AI seat
cast every one of them as its first bullet — and held the card whenever that
bullet had nothing to point at.

**How it is built, so it can be read backwards.** Stable public surfaces only:

* the **population** is every supported instant or sorcery whose compiled
  program has modes its caster chooses (``mode_chooser is None``);
* the **board** for one ``(card, mode)`` comes from the engine's own per-mode
  picker (``Game.cast_target_spec(mode_index=)``): one bait the mode may
  target **and does something to** (the mode cast at it by hand and the board
  compared — "destroy target permanent if it's blue" may name any permanent
  and touches only a blue one), on the side its effect wants, and for every
  other mode a decoy on the side that mode does *not* want — "its target exists and is the
  opponent's; the others have no legal target, or only the caster's own
  things";
* the **proposal** is ``choose_cast_action`` in the seat's own main phase, or
  ``choose_combat_instant_cast_action`` in the two windows the web AI answers
  in — a spell on the stack, and the declare-blockers step;
* the **executor** is ``ai_simulator._play_one_cast``, the real one, with a
  spy on ``Game._cast_onto_stack`` reading the mode the cast was announced
  with. A proposal naming no mode is mode 0: that is what the engine resolves
  a cast naming none as, so on the tree before the chooser this census reads
  **0 modes other than the first reached**, and 30 of 87.

Two legs per mode:

``natural``
    the chooser, unaided, on the mode's own board. Where the board makes this
    the **only** mode worth casting (41 of them) it must be the one proposed.
    Where it cannot — a sibling needs no target, or targets a player, or may
    name the very same permanent — the sibling may win, and which one did is
    pinned in ``SHADOWED`` below: that list is this policy's *valuation*,
    written down.
``forced``
    the same board with ``Game.announceable_modes`` answering only this mode:
    "were this the one mode on offer, is it proposed, is the cast accepted in
    that mode, and does the resolution do anything?" Every mode but one has a
    board, and all 87 pass — which is the claim that no bullet in the pool is
    out of an AI seat's reach.

Run it as a module (``python -m tests.ai.test_ai_mode_chooser_census``) for the
whole table.
"""
from __future__ import annotations

import sys
from collections import Counter
from unittest import mock

import pytest

from engine import Game, PlayerState
from engine import ai_simulator
from engine.ai_policy import (choose_cast_action,
                              choose_combat_instant_cast_action)
from engine.ai_valuation import instruction_target_side
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_roles
from tests.helpers import _mk_card, resolve_stack

PLAYER_KINDS = {"player", "player_or_planeswalker", "any", "opponent"}
ME, OPP = 0, 1


def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


POOL = pool()


def population() -> list:
    """Every caster-chosen modal instant and sorcery, by name."""
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or len(program.modes) < 2:
            continue
        if program.mode_chooser is not None:
            continue  # CR 700.2e: an opponent chooses
        found.append(card)
    return found


# -- the zoo ------------------------------------------------------------------

def _creature(name, colors=(), power=2, toughness=2, text="", type_line=None):
    return _mk_card(
        name=name, type_line=type_line or "Creature - Beast", colors=colors,
        power=power, toughness=toughness, oracle_text=text,
    )


ZOO = {
    "white creature": _creature("Bait White", ("W",)),
    "blue flyer": _creature("Bait Blue Flyer", ("U",), 1, 1, "Flying"),
    "black creature": _creature("Bait Black", ("B",), 3, 3),
    "red creature": _creature("Bait Red", ("R",)),
    "green creature": _creature("Bait Green", ("G",), 4, 4),
    "wall": _creature("Bait Wall", (), 0, 4, "Defender", "Creature - Wall"),
    "artifact creature": _creature("Bait Golem", (), 3, 3, "", "Artifact Creature - Golem"),
    "artifact": _mk_card(name="Bait Artifact", type_line="Artifact"),
    "enchantment": _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
    "nonbasic land": _mk_card(name="Bait Nonbasic", type_line="Land"),
    "plains": POOL["Plains"], "island": POOL["Island"], "swamp": POOL["Swamp"],
    "mountain": POOL["Mountain"], "forest": POOL["Forest"],
    # An Aura is placed with the creature it enchants (`place`).
    "aura": _mk_card(
        name="Bait Aura", type_line="Enchantment - Aura", colors=("G",),
        oracle_text="Enchant creature",
    ),
}
_AURA_HOST = _creature("Bait Host", (), 2, 2)
#: Graveyard baits: a creature card and a noncreature card.
GRAVE = {
    "creature card": _creature("Bait Dead Bear", ("G",)),
    "sorcery card": _mk_card(name="Bait Dead Spell", type_line="Sorcery"),
}
#: Stack baits: a creature spell of each colour the pool's stack modes read.
SPELLS = {
    "red spell": _mk_card(
        name="Bait Red Spell", mana_cost="{R}", type_line="Creature - Goblin",
        colors=("R",), power=1, toughness=1,
    ),
    "blue spell": _mk_card(
        name="Bait Blue Spell", mana_cost="{U}", type_line="Creature - Bird",
        colors=("U",), power=1, toughness=1,
    ),
}


#: The one card in the opponent's hand: a discard needs something to take.
SPARE = _mk_card(name="Bait Spare Card", type_line="Sorcery")


def place(game, seat: int, key: str) -> Permanent:
    """Put zoo unit *key* onto *seat*'s battlefield; the bait permanent."""
    if key == "aura":
        host = Permanent(card=_AURA_HOST)
        game._put_permanent_onto_battlefield(seat, host, seat)
        host.metadata["summoning_sickness_turn"] = -99
        aura = Permanent(card=ZOO["aura"])
        game._put_permanent_onto_battlefield(seat, aura, seat)
        attach_aura(aura, host)
        return aura
    permanent = Permanent(card=ZOO[key])
    game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def board(card, placements=(), *, window=None, grave=(), stack=None):
    """A duel with *card* alone in seat 0's hand and nothing on the table but
    *placements* (``(seat, zoo key)``).

    *window* is None for seat 0's own main phase, ``"combat"`` for seat 1's
    declare-blockers step (seat 1's creatures attacking seat 0), ``"stack"``
    for seat 1's main phase with *stack* (a ``SPELLS`` key) cast and waiting.
    Seat 0 pays out of a mana pool, so the board holds no land the census did
    not put there.
    """
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", hand=[SPARE], library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    placed = {}
    for seat, key in placements:
        placed[(seat, key)] = place(game, seat, key)
    for seat, key in grave:
        game.players[seat].graveyard.append(GRAVE[key])
    if window == "combat":
        game.start_turn(OPP)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.current_step == "declare_attackers", game.current_step
        attackers = [
            index for index, perm in enumerate(game.players[OPP].battlefield)
            if perm.is_creature and "Defender" not in (perm.card.oracle_text or "")
        ]
        game.declare_attackers(OPP, attackers, defending_player_index=ME)
    elif window == "stack":
        game.start_turn(OPP)
        game._close_current_priority_step()
        spell = SPELLS[stack]
        game.players[OPP].hand.append(spell)
        game.players[OPP].mana_pool.update({"R": 3, "U": 3})
        queued = game.queue_from_hand(OPP, spell.name)
        assert queued.supported, queued.details
    game.players[ME].mana_pool.update({symbol: 6 for symbol in "WUBRG"})
    return game, placed


# -- what a mode is -----------------------------------------------------------

def mode_spec(card, index):
    return derive_cast_spec(card, compile_card_oracle(card), mode_index=index) or {}


def mode_shape(card, index) -> str:
    spec = mode_spec(card, index)
    kind = spec.get("kind")
    if spec_roles(spec):
        return "roles"
    if kind in (None, "none"):
        return "untargeted"
    if kind in PLAYER_KINDS:
        return "player"
    if kind == "stack":
        return "stack"
    if kind == "graveyard_creature":
        return "graveyard"
    return "object"


def mode_side(card, index) -> "str | None":
    """Whose permanent this mode's object target should be -- the reading the
    one-target chooser makes (denial wins), over this mode's own steps."""
    instruction = compile_card_oracle(card).modes[index].instruction
    sides: set = set()

    def walk(step) -> None:
        payload = getattr(step, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") in ("object", "roles"):
            side = instruction_target_side(step)
            if side is not None:
                sides.add(side)
        for key in ("steps", "then", "else", "action", "otherwise"):
            for nested in payload.get(key) or ():
                walk(nested)

    if instruction is not None:
        walk(instruction)
    if "opponent" in sides:
        return "opponent"
    if "you" in sides:
        return "you"
    return None


def legal_permanents(game, card, index) -> list:
    """The permanents the engine's own picker offers mode *index*."""
    listed = game.cast_target_spec(ME, card, mode_index=index).get("valid_targets") or []
    return [entry for entry in listed if entry.get("kind") == "permanent"]


def wanted_seat(side) -> int:
    return ME if side == "you" else OPP


def worth_casting(game, card, index) -> "str | None":
    """Why mode *index* is worth casting on this board, or None when it is not:
    it has a legal announcement and what it names is not on the side its own
    effect does not want."""
    if index not in game.announceable_modes(ME, card):
        return None
    shape = mode_shape(card, index)
    if shape == "untargeted":
        return "needs no target"
    if shape == "player":
        return "targets a player"
    if shape in ("stack", "graveyard"):
        return f"has a {shape} target"
    side = mode_side(card, index)
    if shape == "roles":
        chains = game.cast_target_spec(ME, card, mode_index=index).get("valid_targets") or []
        if side is None:
            return "has a chain" if chains else None
        seat = wanted_seat(side)

        def on_side(options) -> bool:
            return any(
                option.get("seat") == seat
                and (not option.get("next") or on_side(option["next"]))
                for option in options
            )

        return "has a chain on its side" if on_side(chains) else None
    legal = legal_permanents(game, card, index)
    if side is None:
        return "has a target" if legal else None
    seat = wanted_seat(side)
    return "has a target on its side" if any(e["seat"] == seat for e in legal) else None


# -- building one mode's board --------------------------------------------------

def _zoo_keys_legal(card, index, seat, window=None, grave=(), stack=None) -> list:
    """Which zoo units mode *index* may target when they sit on *seat*."""
    keys = []
    for key in ZOO:
        game, placed = board(card, [(seat, key)], window=window, grave=grave, stack=stack)
        bait = placed[(seat, key)]
        slot = (game.controller_index_of(bait), game.battlefield_index_of(bait))
        if any((e["seat"], e["index"]) == slot for e in legal_permanents(game, card, index)):
            keys.append(key)
    return keys


def zones(game, spell) -> str:
    """Where every card is, with no object identity in it: comparable between
    two boards built the same way, which `signature` is not (a permanent's id
    is a process-wide counter)."""
    parts = []
    for seat, player in enumerate(game.players):
        hand = sorted(c.name for c in player.hand)
        yard = sorted(c.name for c in player.graveyard)
        if seat == ME:
            for pile in (hand, yard):
                if spell.name in pile:
                    pile.remove(spell.name)
        parts.append((
            player.life, hand, yard, sorted(c.name for c in player.exile),
            len(player.library),
            sorted(
                (perm.card.name, perm.tapped,
                 perm.is_creature and perm.effective_power,
                 perm.is_creature and perm.effective_toughness)
                for perm in player.battlefield
            ),
        ))
    return repr(parts)


def untouched(card, built) -> str:
    """Where every card ends up on *built*'s board when seat 0 casts
    **nothing**: whatever is already on the stack resolves, and that is all.
    What a cast in a stack window is measured against — the opposing spell
    changes the board by resolving, so "the board changed" would say nothing
    about the counterspell."""
    game, _ = board(
        card, built["placements"], window=built["window"],
        grave=built["grave"], stack=built["stack"],
    )
    resolve_stack(game)
    return zones(game, card)


def mode_acts_on(card, index, candidate) -> bool:
    """Whether mode *index*, cast by hand at the candidate board's one bait
    (a permanent, or the spell on the stack), resolves doing anything — the
    engine's answer, with no policy in it."""
    game, placed = board(
        card, candidate["placements"], window=candidate["window"],
        grave=candidate["grave"], stack=candidate["stack"],
    )
    x_value = 2 if "{X}" in (card.mana_cost or "").upper() else None
    in_response = candidate["window"] == "stack"
    if in_response:
        named = {"target_stack_index": len(game.stack) - 1}
    else:
        bait = next(iter(placed.values()))
        named = {
            "target_player_index": game.controller_index_of(bait),
            "target_permanent_ids": [bait.permanent_id],
        }
    before = signature(game, card)
    result = game.queue_from_hand(
        ME, card.name, mode_index=index, x_value=x_value, **named,
    )
    if not result.supported:
        return False
    resolve_stack(game)
    if in_response:
        return zones(game, card) != untouched(card, candidate)
    return signature(game, card) != before


def plan(card, index) -> dict:
    """The board for one mode: ``placements``, ``window``, ``grave``, ``stack``
    -- or ``{"unbuildable": reason}``."""
    program = compile_card_oracle(card)
    shape = mode_shape(card, index)
    side = mode_side(card, index)
    seat = wanted_seat(side)
    instant = card.primary_type == "instant"
    base = {"placements": [], "window": None, "grave": [], "stack": None}

    if shape in ("untargeted", "player"):
        candidates = [dict(base)]
    elif shape == "stack":
        if not instant:
            return {"unbuildable": "a sorcery cannot be cast with a spell on the stack"}
        candidates = []
        for key in SPELLS:
            game, _ = board(card, window="stack", stack=key)
            if index in game.announceable_modes(ME, card):
                candidates.append({**base, "window": "stack", "stack": key})
        if not candidates:
            return {"unbuildable": "no census spell on the stack is a legal target"}
        # "Counter target spell if it's red" may be announced at any spell;
        # the census wants the one it counters.
        candidates = [c for c in candidates if mode_acts_on(card, index, c)] or candidates
    elif shape == "graveyard":
        candidates = []
        for owner in (ME, OPP):
            for key in GRAVE:
                game, _ = board(card, grave=[(owner, key)])
                if index in game.announceable_modes(ME, card):
                    candidates.append({**base, "grave": [(owner, key)]})
        if not candidates:
            return {"unbuildable": "no census graveyard card is a legal target"}
    elif shape == "roles":
        candidates = []
        keys = list(ZOO)
        for first in keys:
            for second in keys:
                if first == second:
                    continue
                placements = [(seat, first), (seat, second)]
                game, _ = board(card, placements)
                if index in game.announceable_modes(ME, card):
                    candidates.append({**base, "placements": placements})
        if not candidates:
            return {"unbuildable": "no pair of census permanents fills its roles"}
    else:
        window = None
        keys = _zoo_keys_legal(card, index, seat)
        if not keys and instant:
            window = "combat"
            seat = OPP
            keys = _zoo_keys_legal(card, index, seat, window="combat")
        if not keys:
            return {"unbuildable": "no census permanent is a legal target on the side it wants"}
        candidates = [
            {**base, "placements": [(seat, key)], "window": window} for key in keys
        ]
        # ...and of those, the baits this mode *does something to*: "Destroy
        # target permanent if it's blue" may legally name any permanent and
        # touches only a blue one. Judged by the engine — the mode cast at
        # that bait, resolved, and the board compared — never by the policy
        # under test.
        acted_on = [
            candidate for candidate in candidates
            if mode_acts_on(card, index, candidate)
        ]
        candidates = acted_on or candidates

    def shadows(candidate) -> dict:
        game, _ = board(
            card, candidate["placements"], window=candidate["window"],
            grave=candidate["grave"], stack=candidate["stack"],
        )
        return {
            other: reason
            for other in range(len(program.modes))
            if other != index
            and (reason := worth_casting(game, card, other)) is not None
        }

    def announceable(candidate) -> bool:
        game, _ = board(
            card, candidate["placements"], window=candidate["window"],
            grave=candidate["grave"], stack=candidate["stack"],
        )
        return index in game.announceable_modes(ME, card)

    candidates = [c for c in candidates if announceable(c)]
    if not candidates:
        return {"unbuildable": "the engine offers this mode on no census board"}
    chosen = min(candidates, key=lambda c: len(shadows(c)))
    chosen = dict(chosen)
    # Decoys: for every other object mode with a side, something it could
    # target on the side it does not want -- kept only while it makes no other
    # mode worth casting.
    before = shadows(chosen)
    for other in range(len(program.modes)):
        if other == index or mode_shape(card, other) != "object":
            continue
        other_side = mode_side(card, other)
        if other_side is None:
            continue
        wrong = ME if other_side == "opponent" else OPP
        for key in _zoo_keys_legal(
            card, other, wrong, window=chosen["window"], grave=chosen["grave"],
            stack=chosen["stack"],
        ):
            if (wrong, key) in chosen["placements"]:
                break
            trial = {**chosen, "placements": [*chosen["placements"], (wrong, key)]}
            if shadows(trial) == before and announceable(trial):
                chosen = trial
                break
    chosen["shadowed_by"] = before
    chosen["shape"] = shape
    chosen["side"] = side
    return chosen


# -- running a board ------------------------------------------------------------

#: What every cast changes whatever it does: the zones the spell itself moves
#: through, the mana that paid for it and the turn's record of spells cast.
#: Left in, a resolution that did nothing still read as a change.
_BOOKKEEPING = frozenset({
    "hand", "graveyard", "library", "mana_pool", "battlefield",
    "spells_cast_this_turn",
})


def signature(game, spell) -> str:
    """Everything a resolution could have changed, with the spell's own trip
    from hand to graveyard taken out."""
    parts = []
    for seat, player in enumerate(game.players):
        hand = sorted(c.name for c in player.hand)
        yard = sorted(c.name for c in player.graveyard)
        if seat == ME:
            for pile in (hand, yard):
                if spell.name in pile:
                    pile.remove(spell.name)
        rest = {
            key: value for key, value in vars(player).items()
            if key not in _BOOKKEEPING
        }
        parts.append((hand, yard, len(player.library), repr(sorted(rest.items(), key=lambda kv: kv[0]))))
        parts.append(sorted(
            (perm.permanent_id, repr(perm), perm.is_creature and perm.effective_power,
             perm.is_creature and perm.effective_toughness)
            for perm in player.battlefield
        ))
    parts.append(len(getattr(game, "delayed_triggers", ()) or ()))
    return repr(parts)


def proposed_modes(action) -> "list | None":
    """The modes a proposal names -- ``[0]`` for one that names none, which is
    what the engine resolves such a cast as; several for a "choose one or
    more" announcement."""
    if action is None:
        return None
    choices = getattr(action, "mode_choices", None)
    if choices:
        return sorted(choice.get("index") for choice in choices)
    named = getattr(action, "mode_index", None)
    return [0 if named is None else named]


def run(card, index, built, *, forced: bool) -> dict:
    """One leg on one board: what was proposed, what the cast announced, and
    whether it was accepted and did anything."""
    window = built["window"]
    chooser = choose_cast_action if window is None else choose_combat_instant_cast_action

    def fresh():
        return board(
            card, built["placements"], window=window, grave=built["grave"],
            stack=built["stack"],
        )

    def only_this_mode(self, caster_index, asked, **kwargs):
        offered = real(self, caster_index, asked, **kwargs)
        return [index] if asked.name == card.name and index in offered else (
            offered if asked.name != card.name else []
        )

    real = Game.announceable_modes
    patches = []
    if forced:
        patches.append(mock.patch.object(Game, "announceable_modes", only_this_mode))
    announced: list = []
    real_cast = Game._cast_onto_stack

    def spy(self, caster_index, card_name, *args, **kwargs):
        if caster_index == ME and card_name == card.name:
            choices = kwargs.get("mode_choices")
            named = kwargs.get("mode_index")
            announced.append(
                sorted(c.get("index") for c in choices) if choices
                else [0 if named is None else named]
            )
        return real_cast(self, caster_index, card_name, *args, **kwargs)

    patches.append(mock.patch.object(Game, "_cast_onto_stack", spy))
    outcome = {"proposed": None, "announced": None, "accepted": None, "changed": None, "error": None}
    for patch in patches:
        patch.start()
    try:
        game, _ = fresh()
        action = chooser(game, ME)
        if action is not None and action.card_name != card.name:
            action = None
        outcome["proposed"] = proposed_modes(action)
        outcome["score"] = None if action is None else round(action.score, 3)
        if action is None:
            return outcome
        game, _ = fresh()
        before = signature(game, card)
        if window is None:
            report = ai_simulator.SimulationReport(
                games_requested=1, games_completed=0, interaction_count=0,
            )
            cast = ai_simulator._play_one_cast(game, ME, report, 1, 1)
            outcome["accepted"] = bool(cast) and not report.refused_casts
            if report.refused_casts:
                outcome["error"] = "; ".join(report.refused_casts)
            if report.issues:
                outcome["error"] = "; ".join(issue.message for issue in report.issues)
        else:
            # The web AI's window: the executor there needs a session, and is
            # driven by tests/ui; here the announcement is made the way it is.
            from engine.ai_policy import spell_being_cast, tap_planned_lands

            action = chooser(game, ME)
            spell = spell_being_cast(game.players[ME].hand, action)
            tap_planned_lands(game, ME, action)
            if hasattr(sys.modules["engine.ai_policy"], "cast_announcement"):
                keywords = sys.modules["engine.ai_policy"].cast_announcement(action)
            else:
                keywords = dict(
                    target_player_index=action.target_player_index,
                    target_permanent_index=action.target_permanent_index,
                    target_permanent_ids=action.target_permanent_ids,
                    x_value=action.x_value,
                    divided_targets=action.divided_targets,
                )
            result = game.queue_from_hand(ME, spell.name, **keywords)
            outcome["accepted"] = bool(result.supported)
            if not result.supported:
                outcome["error"] = result.details
            else:
                resolve_stack(game)
        outcome["announced"] = announced[-1] if announced else None
        # In response to a spell, "did something" is measured against the same
        # board with nothing cast: the opposing spell resolving is a change
        # whatever the answer to it did.
        outcome["changed"] = (
            zones(game, card) != untouched(card, built) if window == "stack"
            else signature(game, card) != before
        )
    except Exception as exc:  # a crash is a finding, not a pass
        outcome["error"] = f"EXC {type(exc).__name__}: {exc}"
    finally:
        for patch in patches:
            patch.stop()
    return outcome


#: Modes whose whole effect is over a board the census leaves empty (or over a
#: later moment), so a resolution that changed nothing is not a finding.
def may_change_nothing(card, index) -> bool:
    return mode_shape(card, index) == "untargeted"


def census() -> dict:
    rows = []
    for card in population():
        program = compile_card_oracle(card)
        for index, mode in enumerate(program.modes):
            row = {
                "card": card.name, "mode": index, "label": mode.label,
                "supported": bool(mode.supported),
            }
            rows.append(row)
            if not mode.supported:
                row["unbuildable"] = "the mode is unsupported"
                continue
            built = plan(card, index)
            if "unbuildable" in built:
                row["unbuildable"] = built["unbuildable"]
                continue
            row.update(
                shape=built["shape"], side=built["side"],
                placements=built["placements"], window=built["window"],
                grave=built["grave"], stack=built["stack"],
                shadowed_by=built["shadowed_by"],
            )
            row["natural"] = run(card, index, built, forced=False)
            row["forced"] = run(card, index, built, forced=True)
    return {"rows": rows}


def findings(result: dict) -> dict:
    """The census read as failures, by leg."""
    out: dict = {"unbuildable": [], "natural": [], "forced": [], "shadowed": []}
    for row in result["rows"]:
        tag = f"{row['card']} [{row['mode']}] {row['label'][:48]!r}"
        if "unbuildable" in row:
            out["unbuildable"].append((tag, row["unbuildable"]))
            continue
        for leg in ("natural", "forced"):
            got = row[leg]
            exclusive = leg == "forced" or not row["shadowed_by"]
            problems = []
            if got["error"]:
                problems.append(got["error"])
            named = got["proposed"]
            if named is None or row["mode"] not in named:
                if exclusive:
                    problems.append(f"proposed {named}")
            else:
                if got["announced"] != named:
                    problems.append(f"the cast announced {got['announced']}")
                if not got["accepted"]:
                    problems.append("the cast was refused")
                elif not got["changed"] and not may_change_nothing(POOL[row["card"]], row["mode"]):
                    problems.append("the resolution changed nothing")
            if named is not None and not exclusive:
                strays = [m for m in named if m != row["mode"] and m not in row["shadowed_by"]]
                if strays:
                    problems.append(
                        f"proposed {named}: {strays} the board does not make worth casting"
                    )
                elif row["mode"] not in named:
                    out["shadowed"].append((tag, "; ".join(
                        f"mode {m} proposed ({row['shadowed_by'][m]})" for m in named
                    ) + f" at {got.get('score')}; forced {row['forced'].get('score')}"))
            if named is None and not exclusive:
                problems.append("nothing proposed")
            if problems:
                out[leg].append((tag, "; ".join(problems)))
    return out


def hit(row: dict, leg: str) -> bool:
    """Whether *leg* proposed this row's own mode."""
    return row["mode"] in (row[leg]["proposed"] or ())


def counts(result: dict) -> dict:
    rows = result["rows"]
    built = [row for row in rows if "unbuildable" not in row]
    exclusive = [row for row in built if not row["shadowed_by"]]
    return {
        "cards": len({row["card"] for row in rows}),
        "modes": len(rows),
        "boards_built": len(built),
        "exclusive_boards": len(exclusive),
        "shadowed_boards": len(built) - len(exclusive),
        "natural_proposed_as_mode": sum(
            1 for row in built if hit(row, "natural")
        ),
        "natural_exclusive_proposed_as_mode": sum(
            1 for row in exclusive if hit(row, "natural")
        ),
        "forced_proposed_as_mode": sum(
            1 for row in built if hit(row, "forced")
        ),
        "forced_cast_accepted_in_mode": sum(
            1 for row in built
            if hit(row, "forced")
            and row["forced"]["accepted"] and row["forced"]["announced"] == [row["mode"]]
        ),
        "modes_reached": sum(
            1 for row in built
            if hit(row, "natural")
            or hit(row, "forced")
        ),
        "nonzero_modes_reached": sum(
            1 for row in built
            if row["mode"] != 0 and (
                hit(row, "natural")
                or hit(row, "forced")
            )
        ),
        "proposals_by_natural_mode": dict(sorted(Counter(
            str(row["natural"]["proposed"]) for row in built
        ).items())),
    }



# -- the tests ----------------------------------------------------------------

#: Modes the census cannot build a board for, each with why. Named rather than
#: skipped: a sweep that silently drops what it cannot reach reports a smaller
#: pool as a clean one.
UNBUILDABLE = {
    # "Counter target activated or triggered ability": the census puts spells
    # on the stack, not abilities. The mode is announceable only in response
    # to one, which is `choose_combat_instant_cast_action`'s window.
    ("Sublime Epiphany", 1): "no census spell on the stack is a legal target",
}

#: Modes whose own board leaves a sibling worth casting too, and the sibling
#: the policy takes there: ``(card, mode) -> the modes proposed instead``.
#:
#: **This is the policy's valuation, pinned**, not a list of defects: on each
#: of these boards two bullets are legal and aimed at the side they want, and
#: the score picks. Most are right or arguable (three damage to a face over a
#: Giant Growth; three cards over a bounce). Six are the scorer's crude probes
#: showing through, named in ROADMAP-style rather than hidden:
#:
#: * Crosis's Charm bounces a creature it could destroy — the bounce weight
#:   counts the creature's power, the destroy weight does not;
#: * Treva's Charm loots rather than destroy an enchantment or exile an
#:   attacker — "draw" in the bullet's text scores as a card gained;
#: * Dromar's Charm gains five life at twenty rather than give -2/-2, Hearth
#:   Charm pumps attackers that are not attacking and Ivory Charm shrinks
#:   creatures in its own main phase — each a tie at the unread-effect floor,
#:   which printed order breaks.
#:
#: A change to a weight moves an entry here, and moving it is the review.
SHADOWED = {
    ("Alabaster Potion", 1): [0],
    ("Crosis's Charm", 1): [0],
    ("Darigaaz's Charm", 0): [1],
    ("Darigaaz's Charm", 2): [1],
    ("Dromar's Charm", 2): [0],
    ("Ebony Charm", 1): [0],
    ("Ebony Charm", 2): [0],
    ("Energy Bolt", 1): [0],
    ("Funeral Charm", 1): [0],
    ("Funeral Charm", 2): [0],
    ("Healing Salve", 1): [0],
    ("Hearth Charm", 2): [1],
    ("Ivory Charm", 1): [0],
    ("Ivory Charm", 2): [0],
    ("Parch", 1): [0],
    ("Pestilent Haze", 1): [0],
    ("Read the Tides", 1): [0],
    ("Rith's Charm", 2): [1],
    ("Sapphire Charm", 1): [0],
    ("Sapphire Charm", 2): [0],
    ("Thunderbolt", 1): [0],
    ("Treva's Charm", 0): [2],
    ("Treva's Charm", 1): [2],
    ("Vision Charm", 1): [0],
    ("Vision Charm", 2): [0],
}


@pytest.fixture(scope="module")
def result() -> dict:
    return census()


def test_the_census_examined_the_pool(result):
    """The floor: a sweep that reaches nothing passes everything."""
    counted = counts(result)
    assert counted["cards"] >= 34
    assert counted["modes"] >= 88
    assert counted["boards_built"] >= 87
    assert counted["exclusive_boards"] >= 41


def test_the_modes_with_no_board_are_the_named_ones(result):
    unbuildable = {
        (row["card"], row["mode"]): row["unbuildable"]
        for row in result["rows"] if "unbuildable" in row
    }
    assert unbuildable == UNBUILDABLE


def test_a_mode_that_is_the_only_one_worth_casting_is_the_one_cast(result):
    """The natural leg. Before the chooser: 16 of these 41 (the first
    bullets), and for the other 25 either mode 0 aimed at whatever the board
    held or no cast at all."""
    found = findings(result)
    assert found["natural"] == [], "\n".join(
        f"{tag}: {what}" for tag, what in found["natural"]
    )
    counted = counts(result)
    assert (
        counted["natural_exclusive_proposed_as_mode"] == counted["exclusive_boards"]
    )


def test_every_mode_is_within_reach(result):
    """The forced leg: offered alone, every mode with a board is proposed,
    announced as itself through the simulator's own executor, accepted by the
    cast gates, and resolves doing something. Before the chooser: the first
    bullets, 30 of 87, and no other."""
    found = findings(result)
    assert found["forced"] == [], "\n".join(
        f"{tag}: {what}" for tag, what in found["forced"]
    )
    counted = counts(result)
    assert counted["forced_cast_accepted_in_mode"] == counted["boards_built"]
    assert counted["nonzero_modes_reached"] >= 53


def test_where_a_sibling_wins_it_is_the_pinned_one(result):
    """The valuation, as a ratchet both ways: a new entry is a mode that
    stopped being chosen on its own board, a missing one is a pin gone
    stale."""
    shadowed = {}
    for row in result["rows"]:
        if "unbuildable" in row or not row["shadowed_by"]:
            continue
        named = row["natural"]["proposed"]
        if named is not None and row["mode"] not in named:
            shadowed[(row["card"], row["mode"])] = named
    assert shadowed == SHADOWED


if __name__ == "__main__":
    result = census()
    verbose = "-v" in sys.argv
    for row in result["rows"]:
        if "unbuildable" in row:
            print(f"-- {row['card']} [{row['mode']}] UNBUILDABLE: {row['unbuildable']}")
            continue
        natural, forced = row["natural"], row["forced"]
        print(
            f"{row['card']} [{row['mode']}] {row['shape']}/{row['side']} "
            f"board={row['placements']} win={row['window']} grave={row['grave']} stack={row['stack']} "
            f"shadow={row['shadowed_by']} | natural: mode={natural['proposed']} score={natural.get('score')} "
            f"ann={natural['announced']} ok={natural['accepted']} chg={natural['changed']} err={natural['error']} "
            f"| forced: mode={forced['proposed']} score={forced.get('score')} ann={forced['announced']} "
            f"ok={forced['accepted']} chg={forced['changed']} err={forced['error']}"
        )
    found = findings(result)
    for leg in ("unbuildable", "natural", "forced", "shadowed"):
        print(f"== {leg}: {len(found[leg])}")
        for tag, what in found[leg]:
            print(f"   {tag}: {what}")
    print("counts:", counts(result))
