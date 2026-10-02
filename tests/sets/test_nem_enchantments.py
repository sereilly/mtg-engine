"""Nemesis enchantments, Auras included.

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
# tests/rules/test_fading.py. These drive the Nemesis enchantments that print it.
from engine import Game as _W1G1EGame
from engine.models import Permanent as _W1G1EPermanent
from engine.models import PlayerState as _W1G1EPlayerState
from engine.named_counters import counters_on as _w1g1e_counters_on
from engine.oracle import compile_card_oracle as _w1g1e_compile

from tests.helpers import resolve_stack as _w1g1e_resolve_stack


def _w1g1e_duel() -> "_W1G1EGame":
    game = _W1G1EGame(players=[
        _W1G1EPlayerState(name="P1", life=20), _W1G1EPlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game


def _w1g1e_dementia_on(game, set_pool, host_name: str):
    """Parallax Dementia cast from P1's hand onto P2's *host_name*."""
    nem = set_pool("NEM")
    host = _W1G1EPermanent(card=nem[host_name])
    game._put_permanent_onto_battlefield(1, host, None)
    game.players[0].hand = [nem["Parallax Dementia"]]
    assert game.cast_from_hand(
        0, "Parallax Dementia", target_player_index=1, target_permanent_index=0,
    ).supported
    _w1g1e_resolve_stack(game)
    [aura] = [p for p in game.players[0].battlefield
              if p.card.name == "Parallax Dementia"]
    return aura, host


def _w1g1e_upkeep(game, seat: int) -> None:
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_upkeep(seat)
    _w1g1e_resolve_stack(game)


def test_w1g1_parallax_dementia_is_an_aura_the_gate_admits(set_pool):
    """It was refused as "unimplemented aura effect: fading 1" — the Aura gate
    reads every line, and the keyword line was one nothing claimed. After the
    rewrite each of its five lines is a claimed one."""
    program = _w1g1e_compile(set_pool("NEM")["Parallax Dementia"])

    assert program.supported, program.reason
    assert sorted(t.condition.kind for t in program.triggered_abilities) == [
        "leaves_battlefield", "upkeep_self",
    ]


def test_w1g1_parallax_dementia_pumps_then_fades_and_takes_its_creature_with_it(set_pool):
    """"Fading 1", "+3/+2", and "When this Aura leaves the battlefield, destroy
    enchanted creature." The creature is a 5/4 for one upkeep of its
    controller's; at the second the Aura finds no counter, is sacrificed, and
    its leave trigger destroys the creature it *was* attached to (CR 608.2h —
    the Aura's teardown has detached it by then)."""
    game = _w1g1e_duel()
    aura, host = _w1g1e_dementia_on(game, set_pool, "Skyshroud Ridgeback")

    assert _w1g1e_counters_on(aura, "fade") == 1
    assert (host.effective_power, host.effective_toughness) == (5, 5)

    _w1g1e_upkeep(game, 1)
    _w1g1e_upkeep(game, 0)
    assert _w1g1e_counters_on(aura, "fade") == 0
    assert game.is_on_battlefield(aura) and game.is_on_battlefield(host)

    _w1g1e_upkeep(game, 1)
    _w1g1e_upkeep(game, 0)

    assert not game.is_on_battlefield(aura)
    assert not game.is_on_battlefield(host)
    assert [c.name for c in game.players[0].graveyard] == ["Parallax Dementia"]
    assert [c.name for c in game.players[1].graveyard] == ["Skyshroud Ridgeback"]
    assert "Parallax Dementia destroyed Skyshroud Ridgeback" in game.log


def test_w1g1_parallax_dementias_creature_cannot_be_regenerated(set_pool):
    """"That creature can't be regenerated." A regeneration shield on the host
    is armed, and the creature goes to the graveyard anyway with it unspent."""
    game = _w1g1e_duel()
    aura, host = _w1g1e_dementia_on(game, set_pool, "Skyshroud Ridgeback")
    host.regeneration_shield = 1

    game.remove_from_battlefield(aura)
    game._permanent_to_graveyard(game.players[0], aura)
    _w1g1e_resolve_stack(game)

    assert not game.is_on_battlefield(host)
    assert [c.name for c in game.players[1].graveyard] == ["Skyshroud Ridgeback"]

# --- end W1G1 ---
