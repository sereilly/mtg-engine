"""A headless table for a probe: cards by name, permanents placed, the turn started.

Every round's groups wrote this again (Mirrodin: `drive_common.py`,
`drive_lib.py` twice, `drive_list.py` six times, `sim.py` ten times). Run a
probe from a tree's root so it imports that tree's engine::

    import sys; sys.path.insert(0, "scripts/integration")
    from board import card, table, tail

    game, mine, theirs = table(hand=["Shock"], mine=["Grizzly Bears"], theirs=["Wall of Stone"])
    game.cast_spell(0, game.players[0].hand[0], targets=[...])   # whatever the probe asks
    tail(game)

Cards resolve by name over **both manifest roles** (a measured set's cards are
the ones a probe is usually about); where printings differ, ``prefer="DST"``
picks that set's. This is a probe's tool, not a test's: a test gets its cards
from ``set_pool("<CODE>")`` (tests/sets/README.md).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, os.getcwd())

from engine import Game, PlayerState  # noqa: E402
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths  # noqa: E402
from engine.models import CardDefinition, Permanent  # noqa: E402

_POOL: dict[str, CardDefinition] = {}
_PREFERRED: dict[str, dict[str, CardDefinition]] = {}


def _pool() -> dict[str, CardDefinition]:
    if not _POOL:
        for path in manifest_set_paths(include_measured=True):
            for each in load_cards(path):
                _POOL.setdefault(each.name, each)
    return _POOL


def card(name: str, *, prefer: str | None = None) -> CardDefinition:
    """The card named *name*; with *prefer*, that set's printing when it has one."""
    if prefer:
        code = prefer.upper()
        if code not in _PREFERRED:
            path = manifest_set_path(code, include_measured=True)
            _PREFERRED[code] = {each.name: each for each in load_cards(path)}
        if name in _PREFERRED[code]:
            return _PREFERRED[code][name]
    try:
        return _pool()[name]
    except KeyError:
        raise KeyError(f"no card named {name!r} in either manifest role") from None


def place(game: Game, seat: int, name: str, *, sick: bool = False, prefer: str | None = None) -> Permanent:
    """Put *name* onto the battlefield under *seat*, through the engine's own
    entry funnel; not summoning sick unless *sick*."""
    permanent = Permanent(card=card(name, prefer=prefer))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def table(
    hand=(), *, opponent_hand=(), mine=(), theirs=(), graveyard=(), opponent_graveyard=(),
    library=None, opponent_library=None, interactive=(), mana: bool = False,
    prefer: str | None = None,
) -> tuple[Game, list[Permanent], list[Permanent]]:
    """A two-seat game on seat 0's first main phase, settled.

    ``mana=False`` turns cost enforcement off (most probes are about what a
    card does, not about paying for it); *interactive* names the seats whose
    prompts wait for an answer instead of being auto-answered."""
    def cards(names):
        return [card(n, prefer=prefer) for n in names]

    game = Game(players=[
        PlayerState("A", hand=cards(hand), library=cards(library or ["Forest"] * 12),
                    graveyard=cards(graveyard)),
        PlayerState("B", hand=cards(opponent_hand), library=cards(opponent_library or ["Forest"] * 12),
                    graveyard=cards(opponent_graveyard)),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    placed = {0: [place(game, 0, n, prefer=prefer) for n in mine],
              1: [place(game, 1, n, prefer=prefer) for n in theirs]}
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def tail(game: Game, n: int = 12) -> None:
    """Print the last *n* lines of the game's log."""
    for line in game.log[-n:]:
        print("   |", line)


if __name__ == "__main__":
    print(__doc__)
    print(f"pool: {len(_pool())} card names over both roles ({Path.cwd()})")
