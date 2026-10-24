"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# Cards in a graveyard as targets. Nantuko Tracer's entry trigger targets a
# card in any graveyard and bottoms it into its owner's library (CR 404.1:
# the pile a card is in is its owner's).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_tracer_game(set_pool, *, interactive, mine=("Swamp",),
                      theirs=("Grizzly Bears", "Terror")):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Nantuko Tracer"]],
            graveyard=[lea[name] for name in mine], library=[lea["Forest"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in theirs],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_nantuko_tracer_bottoms_an_opponents_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)          # the creature

    # CR 603.3d: the target is chosen as the trigger is put on the stack, out
    # of every graveyard (the Tracer's own controller's included).
    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert {(t["seat"], t["name"]) for t in asked.data["targets"]} == {
        (0, "Swamp"), (1, "Grizzly Bears"), (1, "Terror"),
    }
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=1)

    # "You may": asked as it resolves (CR 608.2d).
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    victim = game.players[1]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    assert victim.library[-1].name == "Terror" and len(victim.library) == 6
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert len(game.players[0].library) == 5


def test_w1g3_nantuko_tracer_bottoms_its_controllers_own_card_into_their_library(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=True)
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g3_resolve(game)

    assert game.players[0].graveyard == []
    assert game.players[0].library[-1].name == "Swamp"
    assert len(game.players[1].library) == 5


def test_w1g3_nantuko_tracer_declined_or_whose_card_left_moves_nothing(set_pool):
    declined = _w1g3_tracer_game(set_pool, interactive=True)
    assert declined.queue_from_hand(0, "Nantuko Tracer").supported
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_trigger_target(0, seat=1, graveyard_index=0)
    declined.resolve_top_of_stack(pause_for_choices=True)
    assert declined.confirm_optional_pay(0, accept=False)
    _w1g3_resolve(declined)
    assert [c.name for c in declined.players[1].graveyard] == ["Grizzly Bears", "Terror"]
    assert len(declined.players[1].library) == 5

    # CR 608.2b: the named card leaves in response, and the trigger does
    # nothing — it does not bottom the card that slid into its slot.
    left = _w1g3_tracer_game(set_pool, interactive=True)
    assert left.queue_from_hand(0, "Nantuko Tracer").supported
    left.resolve_top_of_stack(pause_for_choices=True)
    assert left.confirm_trigger_target(0, seat=1, graveyard_index=0)
    victim = left.players[1]
    victim.exile.append(victim.graveyard.pop(0))           # the Bears, in response
    _w1g3_resolve(left)
    left.auto_resolve_pending_choices()
    assert [c.name for c in victim.graveyard] == ["Terror"]
    assert len(victim.library) == 5


def test_w1g3_nantuko_tracer_under_an_ai_seat_names_and_bottoms_a_card(set_pool):
    game = _w1g3_tracer_game(set_pool, interactive=False, mine=())
    assert game.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()

    victim = game.players[1]
    assert len(victim.graveyard) == 1 and len(victim.library) == 6
    assert victim.library[-1].name in ("Grizzly Bears", "Terror")

    # With every graveyard empty the trigger has no target and is removed
    # (CR 603.3d); the creature still resolves.
    empty = _w1g3_tracer_game(set_pool, interactive=False, mine=(), theirs=())
    assert empty.queue_from_hand(0, "Nantuko Tracer").supported
    _w1g3_resolve(empty)
    empty.auto_resolve_pending_choices()
    assert any(p.card.name == "Nantuko Tracer" for p in empty.controlled_by(0))
    assert empty.pending_choices == [] and empty.stack == []

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
