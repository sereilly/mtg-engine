"""A toll put to **each** seat of a set — "each opponent sacrifices a
permanent of their choice unless they pay {3}" (Rishadan Brigand, Cutpurse,
Footpad) — is offered to every one of them, and each decline is that seat's
own (CR 118.12a: "[do something] unless [a player does something else]" is
"[that player] may [do something else]; if they don't, [do something]", once
per player the sentence is about).

The trailing toll read "they" as the one pronoun every "unless they pay"
starts as, so the offer went to the resolution's single target seat and that
seat's decline made **every** opponent sacrifice: at three seats the second
opponent was never asked (Legions' W2G3 probe). The lowering now puts the toll
to the set (``lowering/_collapses.each_seat_pays_its_own_toll``), and the
seats answer in APNAP order (CR 101.4).

The census reads every compiled offer in both manifest roles: an offer put to
"that player" may not carry a penalty naming a set of seats (one seat's answer
would decide for all of them), and every printed "each <seat> … unless they
pay" line compiles to an offer per seat. Validated backwards: on the tree
before the fix it names the three Rishadans.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, resolve_stack

_SEAT_SETS = frozenset({"each_opponent", "each_player"})
_PER_SEAT_TOLL = re.compile(
    r"\beach (?:other )?(?:opponent|player)\b[^.]*\bunless (?:they|that player) pays?\b",
    re.I,
)
#: Rows when this was written: the three Rishadans, Lim-Dûl's Hex and Tariff.
_TOLL_LINE_FLOOR = 5
_OFFER_FLOOR = 100


def _walk(instructions):
    for instruction in instructions or ():
        yield instruction
        payload = instruction.payload if isinstance(instruction.payload, dict) else {}
        for value in payload.values():
            if isinstance(value, tuple) and value and hasattr(value[0], "kind"):
                yield from _walk(value)
            elif hasattr(value, "kind") and hasattr(value, "payload"):
                yield from _walk((value,))


def _program_roots(program):
    yield from program.instructions
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield ability.instruction
    for trigger in program.triggered_abilities:
        if trigger.instruction is not None:
            yield trigger.instruction


#: Handlers that walk the seats themselves and offer each its own toll
#: (Tariff's paragraph, ``each_player_pays_or_sacrifices_greatest``).
_SEAT_LOOP_KINDS = frozenset({"each_player_pays_or_sacrifices_greatest"})


def _per_seat_offers(instructions, in_seat_loop: bool = False):
    """Whether each offer under *instructions* is put to one seat of a set:
    a seat-set actor, a ``that_player`` offer inside a loop over the seats
    ("for each player, … unless they pay", Lim-Dûl's Hex), or a handler that
    loops over the seats itself."""
    for instruction in instructions or ():
        payload = instruction.payload if isinstance(instruction.payload, dict) else {}
        if instruction.kind in _SEAT_LOOP_KINDS:
            yield True
        if instruction.kind == "may":
            actor = payload.get("actor")
            yield actor in _SEAT_SETS or (in_seat_loop and actor == "that_player")
        loop = in_seat_loop or (
            instruction.kind == "for_each"
            and (payload.get("iterator") or {}).get("players") in _SEAT_SETS
        )
        for value in payload.values():
            if isinstance(value, tuple) and value and hasattr(value[0], "kind"):
                yield from _per_seat_offers(value, loop)
            elif hasattr(value, "kind") and hasattr(value, "payload"):
                yield from _per_seat_offers((value,), loop)


def _names_a_seat_set(instruction) -> bool:
    payload = instruction.payload if isinstance(instruction.payload, dict) else {}
    return any(
        payload.get(key) in _SEAT_SETS
        for key in ("who", "recipient", "player", "payer", "actor")
    )


def _units():
    pool: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        pool.setdefault(card.name, card)
    return pool


def test_no_offer_to_one_seat_charges_its_decline_to_a_set_of_seats():
    offers = 0
    charged: list[str] = []
    toll_lines: list[tuple[str, str]] = []
    for name, card in sorted(_units().items()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for root in _program_roots(program):
            for step in _walk((root,)):
                if step.kind != "may":
                    continue
                offers += 1
                if step.payload.get("actor") != "that_player":
                    continue
                branches = tuple(step.payload.get("otherwise") or ()) + tuple(
                    step.payload.get("action") or ()
                )
                if any(_names_a_seat_set(inner) for inner in _walk(branches)):
                    charged.append(name)
        for line in (card.oracle_text or "").split("\n"):
            if _PER_SEAT_TOLL.search(line):
                toll_lines.append(
                    (name, any(_per_seat_offers(tuple(_program_roots(program)))))
                )
    assert offers >= _OFFER_FLOOR, offers
    assert len(toll_lines) >= _TOLL_LINE_FLOOR, toll_lines
    assert not charged, sorted(set(charged))
    unasked = [name for name, per_seat in toll_lines if not per_seat]
    assert not unasked, unasked


def _brigand_table(set_pool, *, interactive: bool, active: int = 0) -> Game:
    pool = set_pool("MMQ")
    game = Game(players=[PlayerState(name=f"P{i}") for i in range(4)])
    game.enforce_mana_costs = True
    if interactive:
        game.interactive_seats = {0, 1, 2, 3}
    game.active_player_index = active
    for seat in (1, 2, 3):
        for _ in range(3):
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool["Mountain"]), None)
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=_mk_creature_card(f"Bear{seat}", 2, 2)), None
        )
    resolve_stack(game)
    game.pending_choices.clear()
    return game


def _enter_brigand(game, set_pool) -> None:
    pool = set_pool("MMQ")
    brigand = Permanent(card=pool["Rishadan Brigand"])
    game._put_permanent_onto_battlefield(0, brigand, None)
    for _ in range(3):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack()


def _names(game, seat) -> list[str]:
    return sorted(perm.card.name for perm in game.controlled_by(seat))


@pytest.mark.parametrize("active, order", [(0, [1, 2, 3]), (2, [2, 3, 1])])
def test_every_opponent_is_offered_the_toll_in_apnap_order(set_pool, active, order):
    game = _brigand_table(set_pool, interactive=True, active=active)
    _enter_brigand(game, set_pool)
    answers = {order[0]: True, order[1]: False, order[2]: False}
    asked: list[int] = []
    for _ in range(12):
        owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
        if not owed:
            sacrifices = [c for c in game.pending_choices if c.kind == "sacrifice"]
            if not sacrifices:
                break
            # The seat that declined chooses what it gives up (CR 701.21a):
            # its own creature, which the default would not have picked.
            choice = sacrifices[0]
            bear = next(
                perm for perm in game.controlled_by(choice.player_index)
                if perm.card.name.startswith("Bear")
            )
            assert game.resolve_pending_choice(
                "sacrifice", choice.player_index, permanent_ids=[bear.permanent_id]
            )
            continue
        seat = owed[0].player_index
        asked.append(seat)
        assert game.resolve_pending_choice("optional_pay", seat, accept=answers[seat])
    resolve_stack(game)
    assert asked == order, game.log[-20:]
    payer, *decliners = order
    assert _names(game, payer) == ["Bear%d" % payer, "Mountain", "Mountain", "Mountain"]
    assert all(perm.tapped for perm in game.controlled_by(payer)
               if perm.card.name == "Mountain")
    for seat in decliners:
        assert _names(game, seat) == ["Mountain", "Mountain", "Mountain"], game.log[-20:]
    assert sum("sacrificed" in line for line in game.log) == 2, game.log[-20:]


def test_a_seat_nobody_asks_answers_its_own_toll(set_pool):
    game = _brigand_table(set_pool, interactive=False)
    # Seat 3 cannot pay {3}: it declines by being unable to, and sacrifices.
    for perm in list(game.controlled_by(3)):
        if perm.card.name == "Mountain":
            perm.tapped = True
    _enter_brigand(game, set_pool)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    for seat in (1, 2):
        assert len(_names(game, seat)) == 4, game.log[-20:]
    assert len(_names(game, 3)) == 3, game.log[-20:]
    assert sum("sacrificed" in line for line in game.log) == 1, game.log[-20:]
