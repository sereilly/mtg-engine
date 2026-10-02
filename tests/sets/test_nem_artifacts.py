"""Nemesis artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: fading ---
# Fading (CR 702.32) is the rewrite in `engine/fading.py`; its rules tests are
# tests/rules/test_fading.py. These drive the Nemesis artifacts that print it.
from engine import Game as _W1G1AGame
from engine.models import Permanent as _W1G1APermanent
from engine.models import PlayerState as _W1G1APlayerState
from engine.named_counters import counters_on as _w1g1a_counters_on

from tests.helpers import resolve_stack as _w1g1a_resolve_stack


def _w1g1a_duel() -> "_W1G1AGame":
    game = _W1G1AGame(players=[
        _W1G1APlayerState(name="P1", life=20), _W1G1APlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game


def _w1g1a_upkeep(game, seat: int) -> None:
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_upkeep(seat)
    _w1g1a_resolve_stack(game)
    for perm in game.all_permanents():
        perm.tapped = False


def test_w1g1_rejuvenation_chamber_gains_life_until_it_fades_out(set_pool):
    """"Fading 2" and "{T}: You gain 2 life." It reported supported before the
    rewrite with its fading line unread — a life-gain rock that never left.
    Now it taps for 2 life on each of three turns and is sacrificed at its
    controller's third upkeep."""
    game = _w1g1a_duel()
    p1 = game.players[0]
    p1.hand = [set_pool("NEM")["Rejuvenation Chamber"]]
    assert game.cast_from_hand(0, "Rejuvenation Chamber").supported
    _w1g1a_resolve_stack(game)
    [chamber] = [p for p in p1.battlefield if p.card.name == "Rejuvenation Chamber"]
    assert _w1g1a_counters_on(chamber, "fade") == 2

    for expected_life in (22, 24, 26):
        assert game.activate_permanent_ability(0, "Rejuvenation Chamber").supported
        _w1g1a_resolve_stack(game)
        assert p1.life == expected_life
        _w1g1a_upkeep(game, 1)
        _w1g1a_upkeep(game, 0)

    assert not game.is_on_battlefield(chamber)
    assert [c.name for c in p1.graveyard] == ["Rejuvenation Chamber"]
    assert "Rejuvenation Chamber was sacrificed" in game.log


# --- end W1G1 ---
