"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


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

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("BOK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_marauder_attacks(set_pool, theirs=(), interactive=()):
    """Alice's Ogre Marauder declared attacking Bob (CR 508.1), its trigger
    on the stack; returns ``(game, marauder, bob's permanents)``."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", library=[card("Forest")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = []
    for seat, name in [(0, "Ogre Marauder"), *((1, n) for n in theirs)]:
        permanent = _W1G9Permanent(card=card(name))
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    return game, placed[0], placed[1:]


def _w1g9_slot(game, permanent):
    seat = game.controller_index_of(permanent)
    return [p.permanent_id for p in game.players[seat].battlefield].index(
        permanent.permanent_id
    )


# Ogre Marauder: "Whenever this creature attacks, it gains 'this creature
# can't be blocked' until end of turn unless defending player sacrifices a
# creature of their choice." CR 118.12a's toll, offered to the seat the attack
# froze (CR 506.2), who performs the sacrifice themselves.


def test_w1g9_ogre_marauder_defender_sacrifices_a_creature_of_their_choice(set_pool):
    """Bob, asked as a person, pays the toll and picks his Hill Giant out of
    two creatures; the Marauder stays blockable and his Bears blocks it."""
    game, marauder, (bears, giant) = _w1g9_marauder_attacks(
        set_pool, theirs=["Grizzly Bears", "Hill Giant"], interactive=(1,),
    )
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("optional_pay", 1)
    game.confirm_optional_pay(1, accept=True)
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("sacrifice", 1)
    assert game.confirm_sacrifice(1, permanent_ids=[giant.permanent_id])
    _w1g9_settle(game)
    assert [c.name for c in game.players[1].graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(bears)
    assert game.players[0].graveyard == []
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {_w1g9_slot(game, bears): _w1g9_slot(game, marauder)})
    assert ok, why


def test_w1g9_ogre_marauder_declined_toll_makes_it_unblockable(set_pool):
    """Bob declines: nothing is sacrificed and the Marauder gains "this
    creature can't be blocked" — his Bears may not block it."""
    game, marauder, (bears,) = _w1g9_marauder_attacks(
        set_pool, theirs=["Grizzly Bears"], interactive=(1,),
    )
    owed = _w1g9_settle(game, defaults=False)
    assert (owed.kind, owed.player_index) == ("optional_pay", 1)
    game.confirm_optional_pay(1, accept=False)
    _w1g9_settle(game)
    assert game.is_on_battlefield(bears)
    assert "This creature can't be blocked" in marauder.effective_card.oracle_text
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(1, {_w1g9_slot(game, bears): _w1g9_slot(game, marauder)})
    assert not ok


def test_w1g9_ogre_marauder_defender_with_no_creature_cannot_pay(set_pool):
    """2005-02-01 ruling: the defender must sacrifice a creature "or Ogre
    Marauder can't be blocked for the rest of the turn". With no creature the
    toll cannot be paid and nothing is asked: the Marauder is unblockable,
    and the damage lands."""
    game, marauder, _ = _w1g9_marauder_attacks(set_pool, interactive=(1,))
    assert _w1g9_settle(game, defaults=False) is None
    assert "This creature can't be blocked" in marauder.effective_card.oracle_text
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g9_drive_combat(game)
    assert game.players[1].life == 17

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
