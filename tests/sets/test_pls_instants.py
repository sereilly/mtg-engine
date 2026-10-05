"""Planeshift instants.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour ---
# Becoming a colour and protection from one, on the spells. Colour is read
# through CR 613's layer 5 (`Game._effective_colors`), never off the card.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine import targeting as _w1g6_targeting
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(f"no such card: {name}")  # _w1g6_card (instants)


def _w1g6_table(set_pool, mine=(), theirs=(), *, hand=(), mana=False, interactive=(0,)):
    """Seat 0 holds *mine* (and *hand* in hand), seat 1 *theirs*, on seat 0's
    turn. Returns the game and the two lists of permanents."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_boards = []
    for seat, names in ((0, mine), (1, theirs)):
        board = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            board.append(perm)
        w1g6_boards.append(board)
    w1g6_game.players[0].hand.extend(_w1g6_card(set_pool, name) for name in hand)
    return w1g6_game, w1g6_boards[0], w1g6_boards[1]  # _w1g6_table (instants)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (instants)


def test_w1g6_singe_burns_one_creature_and_turns_that_creature_black(set_pool):
    """"Singe deals 1 damage to target creature. That creature becomes black
    until end of turn." Both sentences act on the one announced creature
    (CR 601.2c): the red Giant takes 1 and is black — instead of red, CR 105.3
    — while the Bears beside it are neither hurt nor recoloured; at cleanup the
    Giant is red again."""
    singe = _w1g6_card(set_pool, "Singe")
    assert _w1g6_targeting.derive_cast_spec(singe, _w1g6_compile(singe)) == {"kind": "creature"}
    game, mine, theirs = _w1g6_table(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Grizzly Bears"],
        hand=["Singe"], mana=True,
    )
    giant, their_bears = theirs
    game.players[0].mana_pool["R"] = 1

    assert game.queue_from_hand(0, "Singe", target_permanent_ids=[giant.permanent_id]).supported
    _w1g6_resolve_stack(game)

    assert giant.damage_marked == 1 and _w1g6_colors(game, giant) == ["B"]
    assert their_bears.damage_marked == 0 and _w1g6_colors(game, their_bears) == ["G"]
    assert mine[0].damage_marked == 0 and _w1g6_colors(game, mine[0]) == ["G"]
    assert [card.name for card in game.players[0].graveyard] == ["Singe"]

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, giant) == ["R"]


def test_w1g6_singe_recolours_its_casters_own_creature_and_kills_a_one_toughness_one(set_pool):
    """Aimed at its caster's own Bears, the Bears — not an opponent's creature —
    are the black ones. Aimed at a 1/1, the damage is lethal and the creature is
    in the graveyard at the next state-based check; nothing else on the board
    turned black in its place."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Grizzly Bears"], ["Llanowar Elves", "Hill Giant"],
        hand=["Singe", "Singe"],
    )
    bears, (elves, giant) = mine[0], theirs

    assert game.queue_from_hand(0, "Singe", target_permanent_ids=[bears.permanent_id]).supported
    _w1g6_resolve_stack(game)
    assert _w1g6_colors(game, bears) == ["B"] and bears.damage_marked == 1
    assert _w1g6_colors(game, giant) == ["R"]

    assert game.queue_from_hand(0, "Singe", target_permanent_ids=[elves.permanent_id]).supported
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()
    assert [card.name for card in game.players[1].graveyard] == ["Llanowar Elves"]
    assert _w1g6_colors(game, giant) == ["R"] and giant.damage_marked == 0


def _w1g6_judgment(set_pool, lands, *, creatures=("Grizzly Bears", "Savannah Lions")):
    """Seat 0 with *lands* and *creatures* casts Dominaria's Judgment and it
    resolves. Returns the game and seat 0's creatures."""
    game, mine, _theirs = _w1g6_table(
        set_pool, [*lands, *creatures], ["Hill Giant", "Swamp", "Island"],
        hand=["Dominaria's Judgment"],
    )
    cast = game.queue_from_hand(0, "Dominaria's Judgment")
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    return game, mine[len(lands):]  # _w1g6_judgment


@_w1g6_pytest.mark.parametrize("lands, colours", [
    (["Plains"], {"W"}),
    (["Island", "Mountain"], {"U", "R"}),
    (["Plains", "Island", "Swamp", "Mountain", "Forest"], {"W", "U", "B", "R", "G"}),
    (["Plains", "Plains", "Forest"], {"W", "G"}),
    ([], set()),
])
def test_w1g6_dominarias_judgment_gives_one_protection_per_basic_land_type_controlled(
    set_pool, lands, colours,
):
    """"Until end of turn, creatures you control gain protection from white if
    you control a Plains, from blue if you control an Island, from black if you
    control a Swamp, from red if you control a Mountain, and from green if you
    control a Forest." Five grants, each behind its own condition, and each
    asked of its *caster's* lands: the opponent's Swamp and Island buy nothing.
    Every creature the caster controls gets exactly the colours earned."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Dominaria's Judgment")).supported
    game, creatures = _w1g6_judgment(set_pool, lands)
    for creature in creatures:
        assert game._protection_colors(creature) == colours, creature.card.name
    giant = next(p for p in game.controlled_by(1) if p.card.name == "Hill Giant")
    assert game._protection_colors(giant) == set()


def test_w1g6_dominarias_judgment_locks_in_its_creatures_and_ends_with_the_turn(set_pool):
    """CR 611.2c: the creatures are the ones there as it resolves — one that
    enters afterwards gains nothing — and the protection ends at cleanup. It
    costs {2}{W}: with no mana the spell is not cast at all."""
    game, mine, _theirs = _w1g6_table(
        set_pool, ["Plains", "Grizzly Bears"], [], hand=["Dominaria's Judgment"], mana=True,
    )
    bears = mine[1]
    assert not game.queue_from_hand(0, "Dominaria's Judgment").supported
    game.players[0].mana_pool.update({"W": 1, "G": 2})
    assert game.queue_from_hand(0, "Dominaria's Judgment").supported
    _w1g6_resolve_stack(game)
    assert game._protection_colors(bears) == {"W"}

    late = _W1G6Permanent(card=_w1g6_card(set_pool, "Llanowar Elves"))
    game._put_permanent_onto_battlefield(0, late, None)
    assert game._protection_colors(late) == set()

    game.resolve_cleanup_step(0)
    assert game._protection_colors(bears) == set()


def test_w1g6_dominarias_judgment_reads_land_types_through_the_layers(set_pool):
    """The lands are asked what they *are* (CR 613 layer 4), not what they
    print: a Forest an Evil Presence has made a Swamp earns protection from
    black and none from green. And the protection is real — a black Terror may
    not then name the caster's creature."""
    game, mine, _theirs = _w1g6_table(
        set_pool, ["Forest", "Grizzly Bears"], [],
        hand=["Evil Presence", "Dominaria's Judgment"],
    )
    forest, bears = mine
    assert game.queue_from_hand(
        0, "Evil Presence", target_permanent_ids=[forest.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)
    assert forest.has_type("swamp") and not forest.has_type("forest")

    assert game.queue_from_hand(0, "Dominaria's Judgment").supported
    _w1g6_resolve_stack(game)
    assert game._protection_colors(bears) == {"B"}

    game.players[1].hand.append(_w1g6_card(set_pool, "Terror"))
    refused = game.queue_from_hand(1, "Terror", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
