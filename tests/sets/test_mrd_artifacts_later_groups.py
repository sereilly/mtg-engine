"""Mirrodin artifacts, the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# Farsight Mask: "Whenever a source an opponent controls deals damage to you,
# if this artifact is untapped, you may draw a card." The `damage_dealt` row's
# seat narrowing on the damager's side ("a source **an opponent** controls"),
# once per source (each attacker separately, 2004-12-01), with CR 603.4's
# intervening "if" asked as it triggers and again as it resolves.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                 interactive=()):
    """Seat 0 (A) in its first main phase, mana off; each named permanent
    untapped and able to act."""
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
        ),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Island")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g12_settle(game):
    """Drain the stack and take every offer a headless seat is owed."""
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()


def test_w1g12_farsight_mask_draws_once_per_opposing_source(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Alpha Myr", "Grizzly Bears"],
    )
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 16
    assert len(game.players[0].hand) == 2


def test_w1g12_farsight_mask_ignores_your_own_source_and_a_tapped_mask(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Farsight Mask", "Pyrite Spellbomb"],
    )
    assert game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_player_index=0, ability_index=0,
    ).supported
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], theirs=["Grizzly Bears"],
    )
    mask.tapped = True
    _w1g12_declare_attack(game, 1)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[0].life == 18
    assert game.players[0].hand == []


def test_w1g12_farsight_mask_tapped_before_it_resolves_draws_nothing(set_pool):
    # 2004-12-01: "Farsight Mask must be untapped both when the damage is
    # dealt and when you would draw the card." Bolted, the trigger waits on
    # the stack, and the Mask is tapped in response.
    game, (mask,), _ = _w1g12_table(
        set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
    )
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Farsight Mask"]
    mask.tapped = True
    _w1g12_settle(game)
    assert game.players[0].hand == []
    assert "Farsight Mask ability did nothing: its condition is no longer true" in game.log


def test_w1g12_farsight_mask_asks_an_interactive_seat(set_pool):
    for accept, drawn in ((True, 1), (False, 0)):
        game, _, _ = _w1g12_table(
            set_pool, mine=["Farsight Mask"], opponent_hand=["Lightning Bolt"],
            interactive=(0,),
        )
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        game.resolve_top_of_stack()
        game.resolve_top_of_stack()
        assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=accept)
        _w1g12_settle(game)
        assert len(game.players[0].hand) == drawn

# ==== end W1G12 ======================================================
