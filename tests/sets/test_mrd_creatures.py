"""Mirrodin creatures (legendary ones too).

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


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
import pytest
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_game(set_pool, mine=(), hand=(), theirs=(), their_hand=(), interactive=(),
               library=None):
    pool = set_pool("MRD")
    other = set_pool("LEA")

    def card(name):
        return pool[name] if name in pool else other[name]

    p1 = _w1g7_PlayerState(
        name="P1",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in mine],
        hand=[card(n) for n in hand],
        library=(
            [card(n) for n in library] if library is not None
            else [other["Island"]] * 10
        ),
    )
    p2 = _w1g7_PlayerState(
        name="P2",
        battlefield=[_w1g7_nosick(_w1g7_Permanent(card=card(n))) for n in theirs],
        hand=[card(n) for n in their_hand], library=[other["Island"]] * 10,
    )
    game = _w1g7_Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _w1g7_until_owed(game, kind, seat=0):
    """Resolve the top of the stack until *kind* is owed by *seat* — the
    interactive seat's turn to answer, which ``resolve_stack`` would answer by
    default."""
    for _ in range(10):
        if game.pending_choice_of(kind, seat) is not None:
            return game.pending_choice_of(kind, seat)
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game.pending_choice_of(kind, seat)


def _w1g7_settle(game):
    """Drain the stack and answer, as a headless seat, what a bare table left
    on the queue (an offer made by a trigger that resolved with nobody held)."""
    _w1g7_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g7_resolve(game)


def test_w1g7_leonin_elder_gains_on_any_artifact_entering(set_pool):
    """"Whenever **an** artifact enters, you may gain 1 life." The condition
    table read only "a"/"another", so the line was no trigger and the Elder
    refused as text too complex. An opponent's artifact counts (no "you
    control"); a nonartifact creature does not."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Grizzly Bears"],
        their_hand=["Ornithopter"],
    )
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert p1.life == 21
    assert "P1 gained 1 life from Leonin Elder (20 -> 21)" in game.log

    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert p1.life == 21, "a nonartifact creature is not an artifact"


def test_w1g7_leonin_elder_may_decline(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Leonin Elder"], hand=["Ornithopter"], interactive=(0,),
    )
    game.cast_from_hand(0, "Ornithopter")
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    _w1g7_resolve(game)
    assert p1.life == 20


def test_w1g7_vermiculos_grows_per_artifact_this_turn(set_pool):
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vermiculos"], hand=["Ornithopter", "Ornithopter"],
    )
    vermiculos = p1.battlefield[0]
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (5, 5)
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert (vermiculos.effective_power, vermiculos.effective_toughness) == (9, 9)


def test_w1g7_lumengrid_sentinel_taps_on_its_controllers_artifact_only(set_pool):
    """"…an artifact **you control** enters": the narrowing is enforced — the
    opponent's artifact fires nothing — and the seat chooses the target as the
    trigger goes on the stack (CR 603.3d)."""
    game, _p1, p2 = _w1g7_game(
        set_pool, mine=["Lumengrid Sentinel"], hand=["Ornithopter"],
        theirs=["Grizzly Bears"], their_hand=["Ornithopter"], interactive=(0,),
    )
    bears = p2.battlefield[0]
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert game.pending_choices == [] and not bears.tapped

    game.cast_from_hand(0, "Ornithopter")
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert "Grizzly Bears" in [t["name"] for t in prompt.data["targets"]]
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id, seat=1)
    assert _w1g7_until_owed(game, "optional_pay") is not None, game.log
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g7_resolve(game)
    assert bears.tapped
    assert "Tapped Grizzly Bears" in game.log


def test_w1g7_vedalken_archmage_draws_for_artifact_spells_only(set_pool):
    """"Whenever you cast **an** artifact spell, draw a card." The table's type
    row carried "artifact" and read "a" before it, so no card could reach it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, mine=["Vedalken Archmage"],
        hand=["Ornithopter", "Grizzly Bears"], their_hand=["Ornithopter"],
    )
    game.cast_from_hand(0, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 2, "cast one, drew one"
    game.cast_from_hand(0, "Grizzly Bears")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "a creature spell is not an artifact spell"
    game.cast_from_hand(1, "Ornithopter")
    _w1g7_settle(game)
    assert len(p1.hand) == 1, "an opponent's artifact spell is not yours"

@pytest.mark.parametrize(
    "top,zone",
    [("Ornithopter", "hand"), ("Leonin Elder", "graveyard"), ("Island", "graveyard")],
)
def test_w1g7_neurok_familiar_sorts_the_revealed_card(set_pool, top, zone):
    """"…reveal the top card of your library. If it's an artifact card, put it
    into your hand. **Otherwise, put it into your graveyard.**" The reveal-top
    template knew one "otherwise" (the library's bottom). Ornithopter is an
    *artifact creature* card, which is an artifact card (CR 205.2) — the handler
    asked ``primary_type``, which answers "creature" for it."""
    game, p1, _p2 = _w1g7_game(
        set_pool, hand=["Neurok Familiar"], library=[top, "Island", "Island"],
    )
    game.cast_from_hand(0, "Neurok Familiar")
    _w1g7_settle(game)
    names = {
        "hand": [c.name for c in p1.hand],
        "graveyard": [c.name for c in p1.graveyard],
    }
    assert names[zone] == [top], game.log
    assert len(p1.library) == 2
    put = "hand" if zone == "hand" else "graveyard"
    assert f"P1 revealed {top} and put it into their {put}" in game.log

# ==== end W1G7 ======================================================
