"""Fifth Dawn instants.

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
from tests.helpers import settle as _w1g5_settle


def _w1g5_fold_table(set_pool, victim, *, their_hand=(), interactive=()):
    """Seat 1 has *victim* on the stack and *their_hand* in hand; seat 0 has
    answered it with Fold into Aether. Costs not enforced."""
    pools = [set_pool("5DN"), set_pool("LEA"), set_pool("TMP")]

    def w1g5_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A", hand=[w1g5_card("Fold into Aether")],
                         library=[w1g5_card("Island")] * 10),
        _W1G5PlayerState(name="W1G5-B",
                         hand=[w1g5_card(victim)] + [w1g5_card(n) for n in their_hand],
                         library=[w1g5_card("Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(1)
    _w1g5_settle(game)
    assert game.queue_from_hand(1, victim).supported
    fold = game.queue_from_hand(0, "Fold into Aether", target_stack_index=0)
    assert fold.supported, fold.details
    return game


def _w1g5_names(cards):
    return sorted(card.name for card in cards)


def test_w1g5_fold_into_aether_lets_the_countered_spells_controller_put_a_creature(set_pool):
    """"Counter target spell. If that spell is countered this way, its
    controller may put a creature card from their hand onto the battlefield."
    The Bears are countered; their controller — seat 1, not the Fold's caster
    — puts the Craw Wurm from *their* hand onto the battlefield under their
    own control, and keeps the non-creature card."""
    game = _w1g5_fold_table(set_pool, "Grizzly Bears", their_hand=["Craw Wurm", "Lightning Bolt"])
    _w1g5_settle(game)
    caster, victim = game.players
    assert _w1g5_names(victim.graveyard) == ["Grizzly Bears"]
    assert [p.card.name for p in game.controlled_by(victim)] == ["Craw Wurm"]
    assert _w1g5_names(victim.hand) == ["Lightning Bolt"]
    assert list(game.controlled_by(caster)) == []
    assert "W1G5-B put Craw Wurm onto the battlefield (Fold into Aether)" in game.log


def test_w1g5_fold_into_aether_does_nothing_more_to_a_spell_that_cant_be_countered(set_pool):
    """The ruling (2004-12-01): "If the spell isn't countered (because it's a
    spell that can't be countered, for example), nothing happens." Scragnoth
    resolves and the Craw Wurm stays in hand."""
    game = _w1g5_fold_table(set_pool, "Scragnoth", their_hand=["Craw Wurm"])
    _w1g5_settle(game)
    victim = game.players[1]
    assert [p.card.name for p in game.controlled_by(victim)] == ["Scragnoth"]
    assert _w1g5_names(victim.hand) == ["Craw Wurm"]


def test_w1g5_fold_into_aether_asks_the_countered_spells_controller(set_pool):
    """The offer is the countered spell's controller's to take or decline: at
    an interactive seat 1 the "may" prompt is seat 1's, the Fold waits on the
    stack for it, and a decline leaves the Wurm in hand."""
    game = _w1g5_fold_table(
        set_pool, "Grizzly Bears", their_hand=["Craw Wurm"], interactive=(1,)
    )
    owed = _w1g5_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert owed.player_index == 1
    assert [item.card.name for item in game.stack] == ["Fold into Aether"]
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5_settle(game)
    victim = game.players[1]
    assert list(game.controlled_by(victim)) == []
    assert _w1g5_names(victim.hand) == ["Craw Wurm"]


def test_w1g5_fold_into_aether_on_your_own_spell_offers_you_the_creature(set_pool):
    """The ruling (2004-12-01): "If your Fold into Aether counters a spell you
    control, you get to put a creature card from your hand onto the
    battlefield." The seat is the countered spell's controller, whoever that
    is."""
    pools = [set_pool("5DN"), set_pool("LEA")]

    def w1g5_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A", hand=[
            w1g5_card("Fold into Aether"), w1g5_card("Grizzly Bears"),
            w1g5_card("Craw Wurm"),
        ], library=[w1g5_card("Island")] * 10),
        _W1G5PlayerState(name="W1G5-B", hand=[w1g5_card("Craw Wurm")],
                         library=[w1g5_card("Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g5_settle(game)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.queue_from_hand(0, "Fold into Aether", target_stack_index=0).supported
    _w1g5_settle(game)
    caster, other = game.players
    assert [p.card.name for p in game.controlled_by(caster)] == ["Craw Wurm"]
    assert list(game.controlled_by(other)) == []
    assert _w1g5_names(other.hand) == ["Craw Wurm"]

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
