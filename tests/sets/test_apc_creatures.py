"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _w1g4c_Game, PlayerState as _w1g4c_Player  # noqa: E402
from engine.models import Permanent as _w1g4c_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4c_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4c_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order — one pool per card.
_W1G4C_POOLS = ("APC", "LEA")


def _w1g4c_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4C_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 creatures: no pool here prints that name


def _w1g4c_table(set_pool, *, mine=(), hand0=(), hand1=(), lib0=(), lib1=(),
                 interactive=()):
    """A duel with seat 0 in its precombat main phase and costs not enforced."""
    def cards(names):
        return [_w1g4c_card(set_pool, name) for name in names]

    board0 = [_w1g4c_Permanent(card=card) for card in cards(mine)]
    game = _w1g4c_Game(players=[
        _w1g4c_Player(name="P0", battlefield=board0, hand=cards(hand0),
                      library=cards(lib0)),
        _w1g4c_Player(name="P1", hand=cards(hand1), library=cards(lib1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0  # W1G4 creatures: the table


def _w1g4c_names(cards):
    return [card.name for card in cards]  # W1G4 creatures: a zone, by name


def _w1g4c_whirlpool(game, seat, held_before):
    """The whirlpool, asserted off the zones: a hand of the same size as the
    one that went in, and every card that was in the hand or the library still
    in one of the two."""
    player = game.players[seat]
    assert len(player.hand) == held_before
    return sorted(_w1g4c_names(player.hand) + _w1g4c_names(player.library))  # W1G4


_W1G4C_LIBRARY = ["Grizzly Bears", "Hill Giant", "Black Lotus", "Mox Ruby", "Mox Jet"]


def test_w1g4_whirlpool_rider_trades_its_controllers_hand_for_a_new_one(set_pool):
    """"When this creature enters, shuffle the cards from your hand into your
    library, then draw that many cards." Three cards in hand as the Rider
    enters, three afterwards, the same eight cards between hand and library —
    and the trigger is a stack object, so nothing has moved until it resolves."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Rider")).supported
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Rider", "Forest", "Island", "Sol Ring"],
        lib0=_W1G4C_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Whirlpool Rider").supported
    game.resolve_top_of_stack()

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Whirlpool Rider"]
    assert len(game.stack) == 1, "the entry trigger is waiting to resolve"
    assert _w1g4c_names(game.players[0].hand) == ["Forest", "Island", "Sol Ring"]
    assert game.stack[-1].ability_effect_kind == "triggered_library"

    _w1g4c_resolve_stack(game)
    assert _w1g4c_whirlpool(game, 0, 3) == sorted(
        _W1G4C_LIBRARY + ["Forest", "Island", "Sol Ring"]
    )
    assert len(game.players[0].library) == 5
    assert "P0 shuffled 3 card(s) from their hand into their library" in game.log
    assert game.players[1].hand == [], "only the Rider's controller"


def test_w1g4_whirlpool_rider_with_an_empty_hand_draws_nothing(set_pool):
    """"That many" of none is none: the Rider cast as the last card in hand
    shuffles nothing in and draws nothing, and the library is still whole."""
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Rider"], lib0=_W1G4C_LIBRARY,
    )
    assert game.cast_from_hand(0, "Whirlpool Rider").supported
    _w1g4c_resolve_stack(game)

    assert game.players[0].hand == []
    assert sorted(_w1g4c_names(game.players[0].library)) == sorted(_W1G4C_LIBRARY)


def test_w1g4_whirlpool_drake_whirls_as_it_enters_and_again_as_it_dies(set_pool):
    """"Flying" and the Rider's trigger twice over: once as the Drake enters
    and once when it dies, each for the hand its controller holds *then*."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Drake")).supported
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Drake", "Forest", "Island"], hand1=["Terror"],
        lib0=_W1G4C_LIBRARY,
    )
    everything = sorted(_W1G4C_LIBRARY + ["Forest", "Island"])
    assert game.cast_from_hand(0, "Whirlpool Drake").supported
    _w1g4c_resolve_stack(game)

    (drake,) = game.controlled_by(0)
    assert drake.has_keyword("flying")
    assert (drake.effective_power, drake.effective_toughness) == (2, 2)
    assert _w1g4c_whirlpool(game, 0, 2) == everything
    assert game.log.count("P0 shuffled 2 card(s) from their hand into their library") == 1

    game.players[0].hand.append(game.players[0].library.pop())
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[drake.permanent_id]
    ).supported
    _w1g4c_resolve_stack(game)
    game._settle()
    _w1g4c_resolve_stack(game)

    assert _w1g4c_names(game.players[0].graveyard) == ["Whirlpool Drake"]
    assert _w1g4c_whirlpool(game, 0, 3) == everything
    assert "P0 shuffled 3 card(s) from their hand into their library" in game.log
    assert "Whirlpool Drake triggered (died)" in game.log


def test_w1g4_whirlpool_warrior_sacrificed_whirls_every_players_hand(set_pool):
    """"{R}, Sacrifice this creature: **Each player** shuffles the cards from
    their hand into their library, then draws that many cards." Both seats,
    each for its own count out of its own library; the Warrior is the cost."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Warrior")).supported
    theirs = ["Air Elemental", "Counterspell", "Time Walk", "Mox Pearl"]
    game, mine = _w1g4c_table(
        set_pool, mine=["Whirlpool Warrior"], hand0=["Forest", "Island"],
        hand1=["Swamp", "Plains", "Mountain"],
        lib0=["Grizzly Bears", "Hill Giant", "Black Lotus"], lib1=theirs,
    )
    result = game.activate_permanent_ability(0, "Whirlpool Warrior", ability_index=0)
    assert result.supported, result.details
    assert result.effect_kind == "activated_library"
    _w1g4c_resolve_stack(game)

    assert not game.is_on_battlefield(mine[0])
    assert _w1g4c_names(game.players[0].graveyard) == ["Whirlpool Warrior"]
    assert _w1g4c_whirlpool(game, 0, 2) == sorted(
        ["Forest", "Island", "Grizzly Bears", "Hill Giant", "Black Lotus"]
    )
    assert _w1g4c_whirlpool(game, 1, 3) == sorted(
        theirs + ["Swamp", "Plains", "Mountain"]
    )
    assert len(game.players[0].library) == 3 and len(game.players[1].library) == 4


def test_w1g4_whirlpool_warrior_enters_whirling_only_its_own_controller(set_pool):
    """The Warrior's *entry* trigger is the Rider's — "your hand", one seat —
    where its activated ability is every player's."""
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Warrior", "Forest"], hand1=["Swamp", "Plains"],
        lib0=["Grizzly Bears", "Hill Giant"], lib1=["Air Elemental"],
    )
    assert game.cast_from_hand(0, "Whirlpool Warrior").supported
    _w1g4c_resolve_stack(game)

    assert _w1g4c_whirlpool(game, 0, 1) == ["Forest", "Grizzly Bears", "Hill Giant"]
    assert _w1g4c_names(game.players[1].hand) == ["Swamp", "Plains"]
    assert _w1g4c_names(game.players[1].library) == ["Air Elemental"]

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
