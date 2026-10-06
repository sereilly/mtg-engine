"""Every card that arms the keep prompt, asked what answers it accepts (W2G1).

``keep_permanents`` is one prompt for a handful of cards — Cataclysm, Global
Ruin, Planar Overlay, Limited Resources, Keldon Firebombers — and what a legal
answer *is* was one rule applied to all of them: exactly as many permanents as
a maximum matching of permanents to keeps. Three of those cards carry a ruling
that says otherwise ("you can choose that same permanent for more than one of
the choices if you want to"), and the rule made Planar Overlay return lands the
card lets a player keep.

So this asks the prompt itself, for every card in the pool that arms it (both
manifest roles): over one mixed board, **which answers does the resolver
accept?** — by trying them, smallest first and then largest first, rather than
by asking the helper that computes the range. Three statements come out:

* a card whose keeps are **several printed slots** accepts a *range* over this
  board — the artifact creature for artifact and creature, the dual land for
  both its types — and the smallest answer is strictly smaller than the
  largest;
* a card whose keeps are **one slot with a count** accepts one size only:
  "five lands" is five different lands;
* the engine's own ``fewest_keeps`` and its matching agree with what the
  resolver was found to accept, and the headless default lands on the end the
  fate makes the seat's best play.

Validated backwards: on the tree before the change the first statement fails
for all three ranged cards (smallest == largest), which is the defect.

The floors are on what was examined. A census that found no card arming the
prompt, or no card with a range, would pass every assertion above over nothing.
"""

from __future__ import annotations

from itertools import combinations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compiled_units
from engine.oracle_types import RETURN_CHOSEN_TO_HAND

KIND = "keep_chosen_sacrifice_rest"

#: Seat 0's board, in board order. One permanent of every kind the pool's keep
#: sentences name, and two that answer two slots at once: the Tropical Island
#: (Forest and Island) and the Clockwork Beast (artifact and creature).
BOARD = (
    "Tropical Island", "Forest", "Island", "Plains", "Clockwork Beast",
    "Grizzly Bears", "Black Lotus", "Crusade",
)


def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)


def _arming_instructions():
    """``{card name: instruction}`` for every card whose compiled text arms
    the keep prompt, shipped or measured."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    found: dict[str, object] = {}
    for card, program in compiled_units(pool):
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.triggered_abilities]
        roots += [
            getattr(ability, "instruction", None)
            for ability in program.activated_abilities
        ]
        for root in roots:
            for instruction in _walk(root):
                if instruction.kind == KIND:
                    found.setdefault(card.name, instruction)
    return found


def _armed(lea, payload):
    """A fresh game with seat 0's board down and the prompt armed for it."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.interactive_seats = {0}
    for name in BOARD:
        game._put_permanent_onto_battlefield(0, Permanent(card=lea[name]), None)
    game.arm_keep_permanents(
        0, pool=dict(payload.get("pool") or {}), slots=list(payload["slots"]),
        reason="census", fate=payload.get("fate"),
    )
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]
    return game


def _first_accepted(lea, payload, sizes):
    """The first answer the resolver takes, trying *sizes* in order and every
    set of each size in board order. A refused answer moves nothing, so one
    game serves until one is accepted."""
    game = _armed(lea, payload)
    ids = [perm.permanent_id for perm in game.controlled_by(0)]
    for size in sizes:
        for answer in combinations(ids, size):
            if game.confirm_keep_permanents(0, list(answer)):
                return len(answer)
    raise AssertionError("the prompt accepts no answer at all")


def test_w2g1_every_keep_prompt_accepts_the_range_its_slots_print(set_pool):
    lea = set_pool("LEA")
    arming = _arming_instructions()
    ranged, single = [], []
    for name, instruction in sorted(arming.items()):
        payload = instruction.payload
        sizes = range(0, len(BOARD) + 1)
        smallest = _first_accepted(lea, payload, sizes)
        largest = _first_accepted(lea, payload, reversed(sizes))

        probe = _armed(lea, payload)
        choice = probe.pending_choices[0]
        live = probe.keep_choice_candidates(0, payload.get("pool") or {})
        slots = choice.data["slots"]
        assert len(probe.fewest_keeps(live, slots)) == smallest, name
        assert len(
            probe._match_keeps(live, probe._keep_slot_filters(slots))
        ) == largest, name

        if len(slots) > 1:
            assert smallest < largest, (
                f"{name} prints {len(slots)} slots and this board holds a "
                "permanent that answers two of them, but only one answer "
                f"size ({largest}) is accepted"
            )
            ranged.append(name)
        else:
            assert smallest == largest == min(int(slots[0]["count"]), len(live)), name
            single.append(name)

        # The headless default: the end of the range that leaves this seat the
        # most permanents — the fewest where the chosen are what leaves.
        headless = _armed(lea, payload)
        before = len(list(headless.controlled_by(0)))
        headless.auto_resolve_pending_choices()
        assert not headless.pending_choices, name
        left = len(list(headless.controlled_by(0)))
        if payload.get("fate") == RETURN_CHOSEN_TO_HAND:
            assert before - left == smallest, name
        else:
            assert left == before - len(live) + largest, name

    assert len(arming) >= 5, sorted(arming)
    assert {"Cataclysm", "Global Ruin", "Planar Overlay"} <= set(ranged), ranged
    assert {"Limited Resources", "Keldon Firebombers"} <= set(single), single
