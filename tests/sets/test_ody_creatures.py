"""Odyssey creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.control import change_control as _w1g1_change_control
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, hand=(), mana=None):
    """A two-seat game with mana costs enforced; *hand* names Odyssey cards
    (or Alpha ones) in seat 0's hand."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[ody[name] if name in ody else lea[name] for name in hand],
        ),
        _W1G1PlayerState("Opponent", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    return game  # _w1g1_table (creatures)


def _w1g1_put(game, set_pool, seat, name):
    """*name* (Odyssey first, then Alpha) onto *seat*'s battlefield, able to
    act this turn."""
    ody = set_pool("ODY")
    card = ody[name] if name in ody else set_pool("LEA")[name]
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (creatures)


def _w1g1_graveyard(game, set_pool, seat, count):
    """Give *seat* exactly *count* cards in its graveyard, then let the
    state-based sweep recompute — a conditional static is re-asked there
    (CR 611.3a), and a probe that skips it reads last pass's answer."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * count
    game.check_state_based_actions()  # _w1g1_graveyard (creatures)


def _w1g1_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


@_w1g1_pytest.mark.parametrize(
    "name, printed, with_threshold",
    [
        ("Werebear", (1, 1), (4, 4)),
        ("Krosan Beast", (1, 1), (8, 8)),
        ("Metamorphic Wurm", (3, 3), (7, 7)),
        ("Nimble Mongoose", (1, 1), (3, 3)),
        ("Springing Tiger", (3, 3), (5, 5)),
    ],
)
def test_w1g1_threshold_bonus_turns_on_at_seven_and_off_again_below_it(
    set_pool, name, printed, with_threshold,
):
    """"Threshold — This creature gets +N/+N as long as there are seven or
    more cards in your graveyard." The bonus is there exactly while the count
    is: the seventh card arriving turns it on, an eighth changes nothing, and
    a card leaving turns it off — with no cast and no turn boundary between,
    and whatever the *opponent's* graveyard holds."""
    assert _w1g1_compile(set_pool("ODY")[name]).supported
    game = _w1g1_table(set_pool)
    creature = _w1g1_put(game, set_pool, 0, name)

    seen = []
    for count in (0, 6, 7, 8, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append(_w1g1_pt(creature))
    assert seen == [printed, printed, with_threshold, with_threshold, printed]

    _w1g1_graveyard(game, set_pool, 1, 9)
    assert _w1g1_pt(creature) == printed, "an opponent's graveyard is not yours"


def test_w1g1_a_creature_that_loses_threshold_with_damage_on_it_dies(set_pool):
    """A 4/4 Werebear carrying 2 damage is alive; the moment a card leaves its
    controller's graveyard it is a 1/1 with 2 damage and the same state-based
    sweep that recomputed its toughness puts it in the graveyard (CR 704.5g)."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game._mark_damage_on_permanent(bear, 2, source=None)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bear) and _w1g1_pt(bear) == (4, 4)

    game.players[0].graveyard.pop()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(bear)
    assert game.players[0].graveyard[-1].name == "Werebear"


def test_w1g1_a_stolen_threshold_creature_counts_its_new_controllers_graveyard(
    set_pool,
):
    """"Your graveyard" is the controller's (CR 109.5), read through the
    control seam: a Werebear its owner has threshold for is a 1/1 the moment an
    opponent with an empty graveyard takes it, and a 4/4 again once *that*
    player has seven cards there."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)
    assert _w1g1_pt(bear) == (4, 4)

    _w1g1_change_control(bear, 1, source="test")
    game._sync_control()
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 1
    assert _w1g1_pt(bear) == (1, 1)

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(bear) == (4, 4)


def test_w1g1_werebear_still_taps_for_green_beside_its_threshold_line(set_pool):
    """The mana ability on the line above the threshold sentence is untouched
    by it: {T}: Add {G}, with threshold or without."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)

    result = game.activate_permanent_ability(0, "Werebear", ability_index=0)

    assert result.supported, result.details
    assert bear.tapped and game.players[0].mana_pool["G"] == 1


def test_w1g1_mystic_visionary_flies_only_with_threshold(set_pool):
    """"This creature has flying as long as there are seven or more cards in
    your graveyard." A keyword and no bonus: the 2/1 body never changes, and
    layer 6 has the word exactly while the count holds."""
    game = _w1g1_table(set_pool)
    visionary = _w1g1_put(game, set_pool, 0, "Mystic Visionary")

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((game._has_keyword(visionary, "flying"), _w1g1_pt(visionary)))

    assert seen == [(False, (2, 1)), (True, (2, 1)), (False, (2, 1))]


def test_w1g1_gorilla_titan_is_bigger_only_with_an_empty_graveyard(set_pool):
    """"This creature gets +4/+4 as long as there are **no** cards in your
    graveyard." The same condition with a different comparison — exactly zero,
    so one card is enough to turn it off — and the printed trample is there
    throughout."""
    game = _w1g1_table(set_pool)
    titan = _w1g1_put(game, set_pool, 0, "Gorilla Titan")

    seen = []
    for count in (0, 1, 7, 0):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append(_w1g1_pt(titan))

    assert seen == [(8, 8), (4, 4), (4, 4), (8, 8)]
    assert game._has_keyword(titan, "trample")
    _w1g1_graveyard(game, set_pool, 1, 5)
    assert _w1g1_pt(titan) == (8, 8), "an opponent's graveyard is not yours"


def test_w1g1_nut_collector_buffs_every_squirrel_while_its_controller_has_threshold(
    set_pool,
):
    """"Threshold — All Squirrels get +2/+2 as long as there are seven or more
    cards in your graveyard." An anthem over *every* Squirrel on the table —
    the opponent's as well as its controller's — gated on the Collector's
    controller's graveyard. The Collector is a Human Druid and gets nothing."""
    from engine.tokens import make_token_card

    game = _w1g1_table(set_pool)
    collector = _w1g1_put(game, set_pool, 0, "Nut Collector")
    squirrel = make_token_card(
        "Squirrel", 1, 1, "Token Creature — Squirrel", colors=("G",)
    )
    mine = _W1G1Permanent(card=squirrel)
    theirs = _W1G1Permanent(card=squirrel)
    game._put_permanent_onto_battlefield(0, mine, None)
    game._put_permanent_onto_battlefield(1, theirs, None)

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((_w1g1_pt(mine), _w1g1_pt(theirs), _w1g1_pt(collector)))
    assert seen == [
        ((1, 1), (1, 1), (1, 1)),
        ((3, 3), (3, 3), (1, 1)),
        ((1, 1), (1, 1), (1, 1)),
    ]

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(theirs) == (1, 1), "the opponent's graveyard is not the Collector's"


def test_w1g1_nut_collector_makes_a_squirrel_each_upkeep(set_pool):
    """"At the beginning of your upkeep, you may create a 1/1 green Squirrel
    creature token." Driven through the upkeep step and its "you may"; the
    token arrives 3/3 when its maker's controller already has threshold."""
    game = _w1g1_table(set_pool)
    _w1g1_put(game, set_pool, 0, "Nut Collector")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    squirrels = [p for p in game.controlled_by(0) if p.has_type("squirrel")]
    assert len(squirrels) == 1
    assert _w1g1_pt(squirrels[0]) == (3, 3)

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

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
