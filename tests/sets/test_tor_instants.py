"""Torment instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_policy as _w1g6_ai_policy  # noqa: E402
from tests.helpers import resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_liquify_table(set_pool, catalog_by_name, spell: str, **cast) -> _W1G6Game:
    """Seat 1 has *spell* on the stack; seat 0 holds Liquify. Mana off."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[set_pool("TOR")["Liquify"]]),
        _W1G6PlayerState(
            name="P2", hand=[catalog_by_name[spell]],
            library=[catalog_by_name["Island"]] * 5,
        ),
    ])
    game.players[0].hand.extend([catalog_by_name["Island"]] * 4)
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, spell, **cast).supported
    return game


def test_w1g6_liquify_counters_a_small_spell_and_exiles_it(set_pool, catalog_by_name):
    """"Counter target spell with mana value 3 or less. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." A Grizzly Bears (mana value 2) is offered, countered and
    exiled."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Grizzly Bears")
    spec = game.cast_target_spec(0, set_pool("TOR")["Liquify"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == [] and list(game.controlled_by(1)) == []
    assert [c.name for c in game.players[0].graveyard] == ["Liquify"]


def test_w1g6_liquify_cannot_be_announced_at_a_spell_with_mana_value_four(
    set_pool, catalog_by_name,
):
    """A Hill Giant (mana value 4) is not offered, a cast naming it is refused
    with nothing spent (CR 601.2c), and the AI does not propose it."""
    game = _w1g6_liquify_table(set_pool, catalog_by_name, "Hill Giant")
    liquify = set_pool("TOR")["Liquify"]
    assert game.cast_target_spec(0, liquify)["valid_targets"] == []
    refused = game.cast_from_hand(0, "Liquify", target_stack_index=0)
    assert not refused.supported
    assert "Liquify" in [c.name for c in game.players[0].hand]
    assert len(game.stack) == 1
    assert _w1g6_ai_policy._cast_candidate(
        game, 0, liquify, game.players[0].hand.index(liquify),
    ) is None
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Hill Giant"]


def test_w1g6_liquify_reads_mana_value_on_the_stack_with_its_x(set_pool, catalog_by_name):
    """CR 202.3b: on the stack an {X} counts at the announced value. Mind Twist
    ({X}{B}) cast for X=2 is a three and is countered; cast for X=3 it is a
    four and Liquify cannot be aimed at it."""
    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=2,
    )
    assert game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Mind Twist"]
    assert len(game.players[0].hand) == 4, "Mind Twist was countered: nothing discarded"

    game = _w1g6_liquify_table(
        set_pool, catalog_by_name, "Mind Twist", target_player_index=0, x_value=3,
    )
    assert not game.cast_from_hand(0, "Liquify", target_stack_index=0).supported
    _w1g6_resolve_stack(game)
    assert [c.name for c in game.players[1].graveyard] == ["Mind Twist"]
    assert len(game.players[0].hand) == 2, "Liquify stayed in hand; three Islands went"

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
