"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: untapped lands and untap steps ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_sorcery_duel(*bodies_by_seat):
    """A duel with each seat's creatures on the battlefield, ready, seat 0
    active and mana costs off. Returns the game and the two permanent lists."""
    w1g4_game = _W1G4Game(
        players=[_W1G4PlayerState(name="W1G4-A"), _W1G4PlayerState(name="W1G4-B")]
    )
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_placed = []
    for w1g4_seat, w1g4_cards in enumerate(bodies_by_seat):
        w1g4_row = []
        for w1g4_card in w1g4_cards:
            w1g4_perm = _W1G4Permanent(card=w1g4_card)
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_perm.metadata["summoning_sickness_turn"] = -99
            w1g4_row.append(w1g4_perm)
        w1g4_placed.append(w1g4_row)
    return w1g4_game, w1g4_placed


def test_w1g4_panic_attack_offers_three_targets_at_announcement(set_pool):
    """CR 601.2c: "up to three" is announced as up to three distinct targets.
    The picker must offer that many, or the client sends a one-target cast and
    two thirds of the card are unreachable."""
    card = set_pool("PCY")["Panic Attack"]
    spec = _w1g4_cast_spec(card, _w1g4_compile(card))
    assert spec["max_targets"] == 3 and spec["distinct_targets"]


def test_w1g4_panic_attack_stops_exactly_the_three_it_named(set_pool):
    """Cast through the real entry point with three of four blockers named; at
    the declaration the three are refused and the fourth may still block."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game, (mine, theirs) = _w1g4_sorcery_duel(
        [lea["Grizzly Bears"]], [lea["Grizzly Bears"]] * 4
    )
    game.players[0].hand.append(pcy["Panic Attack"])
    named = theirs[:3]
    assert game.cast_from_hand(
        0, "Panic Attack", target_player_index=1,
        target_permanent_ids=[perm.permanent_id for perm in named],
    ).supported
    _w1g4_resolve(game)
    assert game.log.count("Grizzly Bears can't block this turn") == 3

    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"
    for slot in range(3):
        ok, _why = game.declare_blockers(1, {slot: 0})
        assert not ok, f"blocker {slot} was named by Panic Attack"
    assert game.declare_blockers(1, {3: 0})[0]
