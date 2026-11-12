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

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_reversal(set_pool, their_hand, *, interactive=(), theirs=("Mountain", "Forest")):
    """Seat 0 casts Reversal of Fortune at seat 1, who holds *their_hand*.
    Costs not enforced. Returns the game with the spell on the stack."""
    pools = [set_pool("5DN"), set_pool("LEA")]

    def w1g5_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A", hand=[w1g5_card("Reversal of Fortune")],
                         library=[w1g5_card("Mountain")] * 10),
        _W1G5PlayerState(name="W1G5-B", hand=[w1g5_card(n) for n in their_hand],
                         library=[w1g5_card("Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for name in theirs:
        perm = _W1G5Permanent(card=w1g5_card(name))
        game._put_permanent_onto_battlefield(1, perm, None)
    game.start_turn(0)
    _w1g5_settle(game)
    cast = game.queue_from_hand(0, "Reversal of Fortune", target_player_index=1)
    assert cast.supported, cast.details
    return game


def test_w1g5_reversal_of_fortune_casts_a_copy_of_a_card_in_the_revealed_hand(set_pool):
    """"Target opponent reveals their hand. You may copy an instant or sorcery
    card in it. If you do, you may cast the copy without paying its mana
    cost." A seat nobody asks copies the most expensive one (Stone Rain over
    Lightning Bolt; the Craw Wurm is not an instant or sorcery) and casts it
    at seat 1's land. The original never leaves seat 1's hand, and the copy
    ceases to exist (CR 707.10a): nothing of it is left anywhere."""
    game = _w1g5_reversal(set_pool, ["Lightning Bolt", "Stone Rain", "Craw Wurm"])
    _w1g5_settle(game)
    caster, victim = game.players
    assert "W1G5-B reveals their hand: Lightning Bolt, Stone Rain, Craw Wurm" in game.log
    assert [p.card.name for p in game.controlled_by(victim)] == ["Forest"]
    assert sorted(c.name for c in victim.hand) == ["Craw Wurm", "Lightning Bolt", "Stone Rain"]
    assert caster.exile == [] and [c.name for c in caster.graveyard] == ["Reversal of Fortune"]
    assert [c.name for c in victim.graveyard] == ["Mountain"], "the copy's land"


def test_w1g5_reversal_of_fortune_lets_a_person_choose_which_card_to_copy(set_pool):
    """The caster's choice, card by card: declining the first offer (Stone
    Rain) passes to the next (Lightning Bolt), whose copy is cast free with a
    target the caster names. Reversal of Fortune waits on the stack for the
    answers (CR 608.2, the ruling: the copy is cast "while this ability is
    resolving")."""
    game = _w1g5_reversal(
        set_pool, ["Lightning Bolt", "Stone Rain", "Craw Wurm"], interactive=(0,),
    )
    first = _w1g5_settle(game, defaults=False)
    assert first is not None and first.kind == "copy_cast"
    assert first.data["card_name"] == "Stone Rain"
    assert [item.card.name for item in game.stack] == ["Reversal of Fortune"]
    assert game.confirm_copy_cast(0, accept=False)
    second = _w1g5_settle(game, defaults=False)
    assert second is not None and second.data["card_name"] == "Lightning Bolt"
    assert game.confirm_copy_cast(0, accept=True, target_player_index=1)
    _w1g5_settle(game)
    victim = game.players[1]
    assert victim.life == 17
    assert len(list(game.controlled_by(victim))) == 2, "no Stone Rain was cast"
    assert sorted(c.name for c in victim.hand) == ["Craw Wurm", "Lightning Bolt", "Stone Rain"]


def test_w1g5_reversal_of_fortune_with_no_instant_or_sorcery_copies_nothing(set_pool):
    """A revealed hand with no instant or sorcery card offers nothing; the
    reveal still happens."""
    game = _w1g5_reversal(set_pool, ["Craw Wurm", "Grizzly Bears"])
    _w1g5_settle(game)
    assert "W1G5-B reveals their hand: Craw Wurm, Grizzly Bears" in game.log
    assert not [c for c in game.pending_choices if c.kind == "copy_cast"]
    assert game.players[1].life == 20


def test_w1g5_reversal_of_fortune_copy_needs_its_targets(set_pool):
    """The ruling (2004-12-01): "You can't cast the copy unless all of its
    targets, if any, can be chosen." With no land on the table Stone Rain's
    copy cannot be cast, and the seat nobody asks casts the Bolt instead."""
    game = _w1g5_reversal(set_pool, ["Lightning Bolt", "Stone Rain"], theirs=())
    _w1g5_settle(game)
    assert game.players[1].life == 17

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
