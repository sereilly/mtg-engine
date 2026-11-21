"""Champions of Kamigawa lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
#
# The drive list's legendary lands: each activated ability names "target
# legendary creature", and a nonlegendary one is refused.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_activate(game, permanent, index, target):
    return game.activate_permanent_ability(
        0, permanent.card.name, permanent_index=game.battlefield_index_of(permanent),
        ability_index=index, target_permanent_ids=[target.permanent_id],
    )


def test_w1g2_the_kamigawa_temples_reach_only_legendary_creatures(set_pool):
    """Okina's +1/+1, Shinka's first strike and Eiganjo Castle's 2-point
    shield all land on Nagao; each refuses a Grizzly Bears. A Lightning Bolt
    then deals Nagao 1 of its 3."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([set_pool("LEA")["Lightning Bolt"]], ()))
    okina = _w1g2_put(game, chk["Okina, Temple to the Grandfathers"], 0)
    shinka = _w1g2_put(game, chk["Shinka, the Bloodsoaked Keep"], 0)
    eiganjo = _w1g2_put(game, chk["Eiganjo Castle"], 0)
    nagao = _w1g2_put(game, chk["Nagao, Bound by Honor"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    for land in (okina, shinka, eiganjo):
        assert not _w1g2_activate(game, land, 1, bears).supported
    for land in (okina, shinka, eiganjo):
        assert _w1g2_activate(game, land, 1, nagao).supported
        _w1g2_settle(game)
    assert (nagao.effective_power, nagao.effective_toughness) == (4, 4)
    assert nagao.has_keyword("first strike")
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[nagao.permanent_id]
    ).supported
    _w1g2_settle(game)
    assert "Prevented 2 damage to Nagao, Bound by Honor" in game.log
    assert "Lightning Bolt dealt 1 damage to Nagao, Bound by Honor" in game.log
    assert game.is_on_battlefield(nagao)

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

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
