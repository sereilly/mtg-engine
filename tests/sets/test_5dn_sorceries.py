"""Fifth Dawn sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.
#
# Mana Geyser's count of the opponents' tapped lands; Vicious Betrayal's
# sacrifice as a cast cost; Rude Awakening's lands become creatures.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G7Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    _w1g7_settle(game)
    return game, placed[0], placed[1]


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_mana_geyser_counts_only_the_opponents_tapped_lands(set_pool):
    """"Add {R} for each tapped land your opponents control." Three of the
    opponent's four lands are tapped and so is one of the caster's own: three
    {R}, the caster's tapped Mountain and the opponent's untapped Plains
    counted for nothing."""
    lea = set_pool("LEA")
    game, mine, theirs = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"], lea["Mountain"]],
        theirs=[lea["Forest"], lea["Forest"], lea["Island"], lea["Plains"]],
    )
    mine[0].tapped = True
    for land in theirs[:3]:
        land.tapped = True

    result = game.cast_from_hand(0, "Mana Geyser")
    assert result.supported, result
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {"R": 3}
    assert _w1g7_pool(game.players[1]) == {}
    assert "Mana Geyser produced {R}{R}{R}" in game.log


def test_w1g7_mana_geyser_with_no_tapped_opposing_land_adds_nothing(set_pool):
    lea = set_pool("LEA")
    game, mine, _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Mana Geyser"]],
        mine=[lea["Mountain"]], theirs=[lea["Forest"]],
    )
    mine[0].tapped = True

    game.cast_from_hand(0, "Mana Geyser")
    _w1g7_settle(game)

    assert _w1g7_pool(game.players[0]) == {}


def test_w1g7_vicious_betrayal_counts_the_creatures_its_cost_sacrificed(set_pool):
    """"As an additional cost to cast this spell, sacrifice any number of
    creatures. Target creature gets +2/+2 until end of turn for each creature
    sacrificed this way." Three named creatures go as the cost is paid
    (CR 601.2h) and the Giant gets +6/+6; the picker asks for a set of any
    size (``any_number``)."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    betrayal = set_pool("5DN")["Vicious Betrayal"]
    spec = derive_cast_spec(betrayal, compile_card_oracle(betrayal))
    assert spec["cost_spec"] == {
        "kind": "creature", "own_only": True, "sacrifice_cost": True,
        "any_number": True,
    }
    lea = set_pool("LEA")
    game, (bear, other_bear, giant, elves), _ = _w1g7_table(
        set_pool, hand=[betrayal],
        mine=[lea["Grizzly Bears"], lea["Grizzly Bears"], lea["Hill Giant"],
              lea["Llanowar Elves"]],
    )

    result = game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[bear.permanent_id, other_bear.permanent_id,
                            elves.permanent_id],
    )
    assert result.supported, result
    _w1g7_settle(game)

    assert [p.card.name for p in game.players[0].battlefield] == ["Hill Giant"]
    assert (giant.effective_power, giant.effective_toughness) == (9, 9)
    assert "Vicious Betrayal gives Hill Giant +6/+6 until end of turn" in game.log


def test_w1g7_vicious_betrayal_with_its_target_sacrificed_does_nothing(set_pool):
    """CR 601.2c chooses the target before CR 601.2h pays the cost, so the
    target may be among the creatures sacrificed — then its only target is
    gone and the spell is removed as it would resolve (CR 608.2b)."""
    lea = set_pool("LEA")
    game, (bear, giant), _ = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Vicious Betrayal"]],
        mine=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )

    game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[bear.permanent_id, giant.permanent_id],
    )
    _w1g7_settle(game)

    assert game.players[0].battlefield == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Grizzly Bears", "Hill Giant", "Vicious Betrayal",
    ]
    assert any("every target is illegal" in line for line in game.log)


def test_w1g7_vicious_betrayal_sacrifices_only_what_was_named(set_pool):
    """None is a number: a cast naming nobody sacrifices nothing and pumps
    +0/+0 (no default pick eats a board for a cost of zero), and a creature
    the caster does not control cannot pay — the cast is refused with
    nothing spent (CR 601.2h)."""
    lea = set_pool("LEA")
    game, (bear, giant), (theirs,) = _w1g7_table(
        set_pool, hand=[set_pool("5DN")["Vicious Betrayal"]],
        mine=[lea["Grizzly Bears"], lea["Hill Giant"]],
        theirs=[lea["Grizzly Bears"]],
    )

    refused = game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert theirs in game.players[1].battlefield

    game.cast_from_hand(
        0, "Vicious Betrayal", target_permanent_ids=[giant.permanent_id],
    )
    _w1g7_settle(game)

    assert bear in game.players[0].battlefield
    assert giant.effective_power == 3
    assert "P0 sacrificed no permanents to cast Vicious Betrayal" in game.log

# ==== end w1g7 ======================================================
