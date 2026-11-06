"""A search prompt sends the zones it searches and no other (SCG Phase 5, C4).

Parallel Thoughts' search-exile payload carried ``graveyard_cards`` with
every graveyard index marked legal, though its ``zones`` was ``['library']``.
The client hid that grid, so nothing went wrong on screen; a client that drew
what it is sent would have offered cards the engine will not take.

**The census is every search instruction the pool compiles that names the
zones it looks in** (``search_library``, ``search_and_exile_matching``), plus
the library-only default, each run through its own handler at a table with a
person, the armed prompt rendered into the state that person is served, and
its zone fields held to its ``zones``: the library's cards only when the
library is searched, the graveyard's and the hand's only when they are.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle
from web.session_store import Session
from web.state_view import build_state

_POOL = {card.name: card for card in load_catalog()}
#: The search prompts and the state key each is served under.
_PROMPTS = {"search_library": "search_library", "search_and_exile_matching": "search_exile"}
#: Each zone's fields in a search payload.
_ZONE_FIELDS = {
    "library": ("cards", "legal_indices"),
    "graveyard": ("graveyard_cards", "legal_graveyard_indices"),
    "hand": ("hand_cards", "legal_hand_indices"),
}


def _walk(instruction):
    if instruction is None:
        return
    yield instruction
    for value in (getattr(instruction, "payload", None) or {}).values():
        values = value if isinstance(value, (list, tuple)) else (value,)
        for inner in values:
            if hasattr(inner, "kind") and hasattr(inner, "payload"):
                yield from _walk(inner)


def _search_instructions() -> list[tuple[str, object]]:
    """``(card name, instruction)`` for every searching instruction the pool
    compiles, one per (kind, zones) pair a card prints."""
    found: dict = {}
    for card in compilation_units(_POOL.values()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = list(program.instructions) + [
            getattr(ability, "instruction", None)
            for ability in list(program.activated_abilities) + list(program.triggered_abilities)
        ]
        for root in roots:
            for instruction in _walk(root):
                if instruction.kind not in _PROMPTS:
                    continue
                zones = tuple(instruction.payload.get("zones") or ())
                found.setdefault((instruction.kind, zones, card.name), instruction)
    return sorted(
        ((name, instruction) for (_kind, _zones, name), instruction in found.items()),
        key=lambda row: (row[1].kind, tuple(row[1].payload.get("zones") or ()), row[0]),
    )


_ROWS = _search_instructions()


def _served(card_name: str, instruction) -> tuple[dict, tuple]:
    """Run *instruction* for seat 0 at a table where seat 0 is a person, with
    a library, a graveyard and a hand of Grizzly Bears and Islands; the
    prompt it arms as seat 0 is served it, and the zones it searched."""
    stock = [_POOL["Grizzly Bears"], _POOL["Island"]] * 3
    game = Game(players=[
        PlayerState(name="P0", library=list(stock), graveyard=list(stock), hand=list(stock)),
        PlayerState(name="P1", library=list(stock), graveyard=list(stock), hand=list(stock)),
    ])
    game.interactive_seats = {0}
    game._set_phase_and_step("precombat_main", "precombat_main")
    session = Session(
        id=f"c4-{card_name}", mode="human_vs_human", host_name="P0", guest_name="P1",
        game=game, seat_types={0: "human", 1: "human"},
    )
    context = OracleExecutionContext(caster=game.players[0], target=game.players[1], card=_POOL[card_name])
    EFFECT_HANDLERS[instruction.kind](game, instruction, context)
    waiting = game.waiting_prompt(0)
    if waiting is None:
        # A count an earlier step writes ("search … for up to that many",
        # Rites of Spring; a name recorded first, Head Games): run alone, the
        # search has nothing to look for and arms nothing.
        return None, ()
    zones = tuple(waiting.data.get("zones") or ("library",))
    return build_state(session, viewer_seat=0)[_PROMPTS[instruction.kind]], zones


def test_the_census_reaches_every_kind_of_zone_search():
    shapes = {(instruction.kind, tuple(instruction.payload.get("zones") or ())) for _n, instruction in _ROWS}
    assert ("search_and_exile_matching", ("library",)) in shapes
    assert ("search_library", ("graveyard",)) in shapes
    assert ("search_library", ("library", "graveyard", "hand")) in shapes
    assert len(_ROWS) >= 20, len(_ROWS)


@pytest.mark.parametrize(
    "card_name, instruction", _ROWS, ids=[f"{name}-{ins.kind}" for name, ins in _ROWS],
)
def test_a_search_prompt_sends_only_the_zones_it_searches(card_name, instruction):
    payload, zones = _served(card_name, instruction)
    if payload is None:
        pytest.skip("the search counts what an earlier step of its card writes")
    assert payload["zones"] == list(zones)
    for zone, fields in _ZONE_FIELDS.items():
        for field in fields:
            sent = payload.get(field)
            if zone in zones:
                assert sent is not None, (card_name, field, zones)
            else:
                assert not sent, (card_name, field, zones, sent)


def test_parallel_thoughts_sends_its_library_alone():
    """The report's card: "search your library for seven cards, exile them in
    a face-down pile" — the library and nothing else."""
    rows = [ins for name, ins in _ROWS if name == "Parallel Thoughts"]
    assert rows, "Parallel Thoughts compiles no search"
    payload, zones = _served("Parallel Thoughts", rows[0])
    assert zones == ("library",)
    assert payload["cards"] and "graveyard_cards" not in payload
    assert "legal_graveyard_indices" not in payload
