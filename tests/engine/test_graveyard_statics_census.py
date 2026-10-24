"""Pool-wide: every static ability stated to function from a graveyard
(CR 113.6b) is gathered from there, changes the board from there, and from
nowhere else.

"As long as this card is in your graveyard …" — Judgment's five Incarnations
and Riftstone Portal print it. CR 611.3b says such an effect "applies at all
times that … the object generating it is in the appropriate zone", and every
board-wide static the engine applied was gathered from the battlefield, so the
sentence parsed, lowered and reported supported while nothing looked for it.

Three questions, over both manifest roles:

1. **Every printed such line compiles to a static stamped
   ``functions_from: graveyard``.** Validated backwards: part-way through the
   round that wrote this, Riftstone Portal reported supported with *no*
   instruction at all — its land builder skipped any line with a colon in it,
   the quoted "{T}: Add {G} or {W}." included — and this is the question that
   named it.
2. **Every instruction so stamped that is not a trigger's or an activated
   ability's is of a kind a gatherer reads from a graveyard**
   (``graveyard_statics.GRAVEYARD_STATIC_KINDS``) — a static stamped for a
   zone nothing scans is one that compiles clean and never applies.
3. **Each such card changes its owner's board from the graveyard and not from
   the battlefield.** Driven: one of each basic land and a Grizzly Bears on
   seat 0, the card put into the graveyard through the zone seam (or onto the
   battlefield), the statics recomputed, and every permanent's power,
   toughness, text and keywords read through the CR 613 accessors.
"""

from __future__ import annotations

import functools
import re

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.graveyard_statics import (GRAVEYARD_STATIC_KINDS,
                                      functions_from_graveyard)
from engine.lord_buffs import grantable_keywords
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_PRINTED = re.compile(r"^as long as this card is in your graveyard\b", re.IGNORECASE)
_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


@functools.lru_cache(maxsize=1)
def _pool() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _printed_population():
    """Supported cards printing a line that states it works from a graveyard."""
    return [
        card for card in _pool().values()
        if compile_card_oracle(card).supported
        and any(
            _PRINTED.match(line.strip())
            for line in (card.oracle_text or "").splitlines()
        )
    ]


def _walk(instruction):
    yield instruction
    for key in ("steps", "then", "action", "otherwise"):
        for step in (instruction.payload or {}).get(key) or ():
            if hasattr(step, "kind"):
                yield from _walk(step)


def test_every_printed_graveyard_static_compiles_to_a_graveyard_static():
    population = _printed_population()
    missing = [
        card.name for card in population
        if not any(
            instruction.kind in GRAVEYARD_STATIC_KINDS
            and functions_from_graveyard(instruction)
            for instruction in compile_card_oracle(card).instructions
        )
    ]
    assert not missing, sorted(missing)
    # The floor: the five Incarnations and Riftstone Portal.
    assert len(population) >= 6, sorted(card.name for card in population)


def test_every_instruction_stamped_for_a_graveyard_has_a_reader_there():
    """A trigger's and an activated ability's stamp is read by their own scans
    (``events.graveyard_trigger_events``, ``Game.activate_from_graveyard``);
    anything else must be a kind the recompute gathers from a graveyard."""
    examined = 0
    stray: list[str] = []
    for card in _pool().values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        carried = {
            id(part.instruction)
            for part in (*program.triggered_abilities, *program.activated_abilities)
            if part.instruction is not None
        }
        for instruction in program.instructions:
            if id(instruction) in carried:
                continue
            for part in _walk(instruction):
                if functions_from_graveyard(part) and part.kind not in GRAVEYARD_STATIC_KINDS:
                    stray.append(f"{card.name}: {part.kind}")
    assert not stray, sorted(stray)
    assert examined >= 4000, examined


def _board(where: str, card):
    """Seat 0 with one of each basic and a Grizzly Bears; *card* put
    ``"graveyard"``-side through the zone seam or onto the battlefield."""
    pool = _pool()
    game = Game(players=[
        PlayerState(name=f"P{seat}", life=20, library=[pool["Island"]] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    watched = []
    for name in (*_BASICS, "Grizzly Bears"):
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        watched.append(permanent)
    game._settle()
    before = [_reading(game, permanent) for permanent in watched]
    if where == "graveyard":
        assert game.put_card_into_graveyard(0, card)
    else:
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    game._settle()
    after = [_reading(game, permanent) for permanent in watched]
    return before, after


def _reading(game, permanent):
    """What the CR 613 accessors say about *permanent*."""
    return (
        permanent.effective_power if permanent.is_creature else None,
        permanent.effective_toughness if permanent.is_creature else None,
        permanent.effective_card.oracle_text,
        frozenset(word for word in grantable_keywords() if permanent.has_keyword(word)),
    )


def test_each_graveyard_static_changes_the_board_from_the_graveyard_only():
    population = _printed_population()
    inert, leaking = [], []
    for card in population:
        before, after = _board("graveyard", card)
        if before == after:
            inert.append(card.name)
        before, after = _board("battlefield", card)
        if before != after:
            leaking.append(card.name)
    assert not inert, f"nothing changed from the graveyard: {sorted(inert)}"
    assert not leaking, f"changed the board from the battlefield: {sorted(leaking)}"
    assert len(population) >= 6, sorted(card.name for card in population)
