"""Fifth Dawn enchantments, Auras included.

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
# Dawn's Reflection's triggered mana split; Ion Storm's either-kind
# counter cost.

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


def test_w1g7_dawns_reflection_adds_two_mana_split_as_the_tap_says(set_pool):
    """"…its controller adds an additional two mana in any combination of
    colors." Cast on a Forest through the real cast; each tap adds the
    Forest's {G} and two more — the split the tap names ({U}{B}: ruling
    2004-12-01, "The two mana can be of two different colors"), and a split
    that does not add up to two is not honoured part-way: the default takes
    its place whole."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest,), _ = _w1g7_table(
        set_pool, hand=[pool["Dawn's Reflection"]], mine=[lea["Forest"]],
    )
    result = game.cast_from_hand(
        0, "Dawn's Reflection", target_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result
    _w1g7_settle(game)
    assert forest.metadata.get("attached_aura") is not None
    player = game.players[0]

    assert game.tap_land_for_mana(
        0, "Forest", chosen_color="G", permanent_id=forest.permanent_id,
        mana_combination={"U": 1, "B": 1},
    )
    assert _w1g7_pool(player) == {"G": 1, "U": 1, "B": 1}
    assert game.log[-2:] == [
        "Dawn's Reflection: P0 added an additional {U}",
        "Dawn's Reflection: P0 added an additional {B}",
    ]

    forest.tapped = False
    game.clear_mana_pools()
    game.tap_land_for_mana(
        0, "Forest", chosen_color="G", permanent_id=forest.permanent_id,
        mana_combination={"U": 3},
    )
    # Nothing in hand asks for a colour, so the default is the colour the
    # tap asked the land for.
    assert _w1g7_pool(player) == {"G": 3}


def test_w1g7_dawns_reflection_defaults_toward_what_the_hand_asks_for(set_pool):
    """A seat that names no split takes the colours its held cards want
    (`mana_combination.default_split`): a {U}{B} spell in hand makes the
    two extra mana {U}{B} rather than two more of the land's own colour."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest, aura), _ = _w1g7_table(
        set_pool, mine=[lea["Forest"], pool["Dawn's Reflection"]],
    )
    from engine.aura_attachment import attach_aura

    attach_aura(aura, forest)
    game.players[0].hand.append(set_pool("ICE")["Diabolic Vision"])

    game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_id=forest.permanent_id)

    assert _w1g7_pool(game.players[0]) == {"G": 1, "U": 1, "B": 1}


def test_w1g7_dawns_reflection_gives_the_mana_to_the_lands_controller(set_pool):
    """Its ruling (2004-12-01): "The controller of the land gets the
    additional mana, not the controller of the enchantment." Cast on an
    opponent's Island, the opponent's tap makes three mana for them and
    none for the Aura's controller."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, _, (island,) = _w1g7_table(
        set_pool, hand=[pool["Dawn's Reflection"]], theirs=[lea["Island"]],
    )
    game.cast_from_hand(
        0, "Dawn's Reflection", target_permanent_ids=[island.permanent_id],
    )
    _w1g7_settle(game)

    game.tap_land_for_mana(1, "Island", chosen_color="U", permanent_id=island.permanent_id)

    assert _w1g7_pool(game.players[1]) == {"U": 3}
    assert _w1g7_pool(game.players[0]) == {}


def test_w1g7_dawns_reflection_counts_in_the_payment_planner(set_pool):
    """The planner's units for the enchanted land (`board_payment`) are the
    land's own mana and two of any colour, so one Forest pays {1}{U}{B} and
    not {1}{U}{U}{B}."""
    from engine.board_payment import board_can_pay

    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest, aura), _ = _w1g7_table(
        set_pool, mine=[lea["Forest"], pool["Dawn's Reflection"]],
    )
    from engine.aura_attachment import attach_aura

    attach_aura(aura, forest)
    cost = {"U": 1, "B": 1, "generic": 1}
    assert board_can_pay(game, 0, cost)
    assert not board_can_pay(game, 0, {"U": 2, "B": 1, "generic": 1})

