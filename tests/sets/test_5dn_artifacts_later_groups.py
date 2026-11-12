"""Fifth Dawn artifacts — the later groups' sections.

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


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_card(set_pool, name):
    for code in ("5DN", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g5_table(set_pool, *, mine=(), theirs=(), hand=(), opponent_hand=(),
                interactive=()):
    """Costs not enforced, every permanent past summoning sickness, seat 0
    active in its first main phase. Cards from Fifth Dawn, else Alpha."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A",
                         hand=[_w1g5_card(set_pool, n) for n in hand],
                         library=[_w1g5_card(set_pool, "Island")] * 10),
        _W1G5PlayerState(name="W1G5-B",
                         hand=[_w1g5_card(set_pool, n) for n in opponent_hand],
                         library=[_w1g5_card(set_pool, "Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G5Permanent(card=_w1g5_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g5_settle(game)
    return game, rows[0], rows[1]  # _w1g5_table


def _w1g5_shackle(set_pool, *, islands=2, theirs=("Grizzly Bears", "Craw Wurm"), **kwargs):
    game, mine, theirs = _w1g5_table(
        set_pool, mine=["Vedalken Shackles"] + ["Island"] * islands,
        theirs=list(theirs), **kwargs,
    )
    return game, mine[0], mine[1:], theirs


def test_w1g5_vedalken_shackles_steals_only_a_creature_within_your_island_count(set_pool):
    """"{2}, {T}: Gain control of target creature with power less than or
    equal to the number of Islands you control for as long as this artifact
    remains tapped." With two Islands the Craw Wurm (6) cannot be named and
    nothing is paid finding out; the Grizzly Bears (2) are taken."""
    game, shackles, _islands, (bears, wurm) = _w1g5_shackle(set_pool)
    refused = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[wurm.permanent_id]
    )
    assert not refused.supported
    assert not shackles.tapped, "a refused activation pays nothing"
    taken = game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    )
    assert taken.supported, taken.details
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    assert game.controller_index_of(wurm) == 1
    assert shackles.tapped


def test_w1g5_vedalken_shackles_keeps_a_creature_that_grows_past_the_count(set_pool):
    """The ruling (2004-12-01): "The creature's power and the number of
    Islands you control matter only when the ability is activated and when it
    resolves. After that, only the fact that Vedalken Shackles remains tapped
    matters." Giant Growth on the stolen Bears changes nothing."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(
        set_pool, opponent_hand=["Giant Growth"],
    )
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    grown = game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert grown.supported, grown.details
    _w1g5_settle(game)
    assert bears.effective_power == 5
    assert game.controller_index_of(bears) == 0


def test_w1g5_vedalken_shackles_counts_your_islands_as_it_resolves(set_pool):
    """CR 608.2b: the bound is asked again on resolution. An Island leaving
    in response leaves one, the Bears' 2 power is past it, and the ability does
    nothing."""
    game, _shackles, islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    assert game.queue_permanent_ability(
        0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.remove_from_battlefield(islands[0])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untapped_in_response_steals_nothing(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles becomes untapped before
    its ability resolves, you won't gain control of the creature." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    assert game.become_untapped(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_untap_choice_is_the_whole_card(set_pool):
    """"You may choose not to untap this artifact during your untap step."
    The choice is offered at seat 0's untap step; a seat nobody sits in keeps
    the Shackles tapped while the steal is live, and choosing to untap it
    (the person's answer, ``keep_tapped_ids=[]``) gives the Bears back —
    as does the Shackles leaving the battlefield (the ruling: "it's no longer
    tapped, so the control-changing effect ends")."""
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0

    assert [entry["id"] for entry in game.get_optional_untap_permanents(0)] == [
        shackles.permanent_id
    ]
    game.start_turn(1)
    _w1g5_settle(game)
    game.start_turn(0)
    _w1g5_settle(game)
    assert shackles.tapped, "headless play keeps a live steal"
    assert game.controller_index_of(bears) == 0

    game.start_turn(1)
    _w1g5_settle(game)
    game.resolve_untap_step(0, keep_tapped_ids=[])
    _w1g5_settle(game)
    assert not shackles.tapped
    assert game.controller_index_of(bears) == 1


def test_w1g5_vedalken_shackles_leaving_ends_the_steal(set_pool):
    """The ruling (2004-12-01): "If Vedalken Shackles leaves the battlefield,
    it's no longer tapped, so the control-changing effect ends." """
    game, shackles, _islands, (bears, _wurm) = _w1g5_shackle(set_pool)
    game.queue_permanent_ability(0, "Vedalken Shackles", target_permanent_ids=[bears.permanent_id])
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 0
    game.remove_from_battlefield(shackles)
    _w1g5_settle(game)
    assert game.controller_index_of(bears) == 1

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
