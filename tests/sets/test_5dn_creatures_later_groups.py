"""Fifth Dawn creatures (legendary ones too) — the later groups' sections.

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
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from tests.helpers import settle as _w1g5_settle


def _w1g5_table(set_pool, *, mine=(), theirs=(), interactive=()):
    """Costs not enforced, every permanent past summoning sickness, seat 0
    active in its first main phase. Cards from Fifth Dawn, else Alpha."""
    pools = [set_pool("5DN"), set_pool("LEA")]

    def w1g5_card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="W1G5-A", library=[w1g5_card("Forest")] * 10),
        _W1G5PlayerState(name="W1G5-B", library=[w1g5_card("Forest")] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    rows = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            perm = _W1G5Permanent(card=w1g5_card(name))
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            row.append(perm)
        rows.append(row)
    game.start_turn(0)
    _w1g5_settle(game)
    return game, rows[0], rows[1]  # _w1g5_table


def test_w1g5_ouphe_vandals_counters_an_artifact_ability_and_destroys_its_source(set_pool):
    """"{G}, Sacrifice this creature: Counter target activated ability from an
    artifact source and destroy that artifact if it's on the battlefield."
    Rod of Ruin's ping is countered (seat 1 keeps its life) and the Rod is
    destroyed; the Vandals paid with themselves."""
    game, mine, theirs = _w1g5_table(set_pool, mine=["Rod of Ruin"], theirs=["Ouphe Vandals"])
    rod, vandals = mine[0], theirs[0]
    assert game.queue_permanent_ability(0, "Rod of Ruin", target_player_index=1).supported
    vandal = game.queue_permanent_ability(1, "Ouphe Vandals", target_stack_index=0)
    assert vandal.supported, vandal.details
    assert not game.is_on_battlefield(vandals), "the sacrifice is the cost"
    _w1g5_settle(game)
    assert game.players[1].life == 20, "Rod of Ruin's ability was countered"
    assert not game.is_on_battlefield(rod)
    assert [c.name for c in game.players[0].graveyard] == ["Rod of Ruin"]
    assert "Ouphe Vandals destroyed Rod of Ruin" in game.log


def test_w1g5_ouphe_vandals_destroys_nothing_once_the_artifact_has_left(set_pool):
    """"…if it's on the battlefield": the Rod leaves in response (CR 400.7 —
    whatever comes back is a new object), so the ability is countered and
    nothing is destroyed, the Rod returned to the battlefield included."""
    game, mine, _theirs = _w1g5_table(set_pool, mine=["Rod of Ruin"], theirs=["Ouphe Vandals"])
    rod = mine[0]
    game.queue_permanent_ability(0, "Rod of Ruin", target_player_index=1)
    assert game.queue_permanent_ability(1, "Ouphe Vandals", target_stack_index=0).supported
    game.remove_from_battlefield(rod)
    again = _W1G5Permanent(card=rod.card)
    game._put_permanent_onto_battlefield(0, again, None)
    _w1g5_settle(game)
    assert game.players[1].life == 20
    assert game.is_on_battlefield(again), "the new object was never the source"
    assert "Ouphe Vandals: nothing to destroy" in game.log


def test_w1g5_ouphe_vandals_names_only_an_artifact_source(set_pool):
    """The picker offers activated abilities from an artifact source (CR
    605.3b: never a mana ability), so Prodigal Sorcerer's ping cannot be
    named and nothing is paid finding out."""
    game, _mine, theirs = _w1g5_table(
        set_pool, mine=["Prodigal Sorcerer"], theirs=["Ouphe Vandals"]
    )
    (ability,) = _w1g5_compile(theirs[0].card).activated_abilities
    assert _w1g5_activation_spec(ability) == {
        "kind": "stack", "stack_ability_kinds": ["activated"],
        "stack_ability_source_types": ["artifact"],
    }
    assert game.queue_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1).supported
    refused = game.queue_permanent_ability(1, "Ouphe Vandals", target_stack_index=0)
    assert not refused.supported
    assert game.is_on_battlefield(theirs[0])

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
