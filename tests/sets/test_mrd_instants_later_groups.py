"""Mirrodin instants, the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


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

from engine.game import Game as _W1G11Game
from engine.models import PlayerState as _W1G11PlayerState

from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, hand, *, library=(), bob_library=()):
    lea = set_pool("LEA")
    alice = _W1G11PlayerState(
        name="Alice", hand=list(hand),
        library=list(library) or [lea["Plains"]] * 6,
    )
    bob = _W1G11PlayerState(
        name="Bob", library=list(bob_library) or [lea["Island"]] * 6,
    )
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def test_w1g11_spoils_of_the_vault_digs_to_the_name_and_pays_a_life_per_exile(set_pool):
    """A person names Shivan Dragon, three cards down: three exiled, 3 life."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Swamp"], lea["Plains"], lea["Shivan Dragon"],
               lea["Forest"]]
    game, alice, _bob = _w1g11_table(set_pool, [mrd["Spoils of the Vault"]],
                                     library=library)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    assert not game.resolve_top_of_stack(), "held for the name (CR 608.2)"
    (choice,) = [c for c in game.pending_choices if c.kind == "name_then_consult"]
    assert choice.player_index == 0
    assert game.confirm_name_then_consult(0, "Shivan Dragon")
    _w1g11_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Shivan Dragon"]
    assert sorted(c.name for c in alice.exile) == ["Island", "Plains", "Swamp"]
    assert [c.name for c in alice.library] == ["Forest"]
    assert alice.life == 20 - 3
    assert [c.name for c in alice.graveyard] == ["Spoils of the Vault"]


def test_w1g11_spoils_of_the_vault_naming_a_missing_card_exiles_the_library(set_pool):
    """The ruling (2018-12-07): a name the library does not hold exiles the
    library and costs a life for each card."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g11_table(
        set_pool, [mrd["Spoils of the Vault"]], library=[lea["Island"]] * 4,
    )
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    assert not game.resolve_top_of_stack(), "held for the name (CR 608.2)"
    assert game.confirm_name_then_consult(0, "Shivan Dragon")
    _w1g11_resolve_stack(game)
    assert alice.hand == []
    assert alice.library == []
    assert len(alice.exile) == 4
    assert alice.life == 16


def test_w1g11_spoils_of_the_vault_left_to_itself_names_from_its_own_library(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Shivan Dragon"], lea["Shivan Dragon"]]
    game, alice, _bob = _w1g11_table(set_pool, [mrd["Spoils of the Vault"]],
                                     library=library)
    assert game.cast_from_hand(0, "Spoils of the Vault").supported
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Shivan Dragon"]
    assert [c.name for c in alice.exile] == ["Island"]
    assert alice.life == 19

def _w1g11_reminder_table(set_pool, *, bob_cast=("Shivan Dragon",)):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    library = [lea["Island"], lea["Shivan Dragon"], lea["Lightning Bolt"],
               lea["Forest"]]
    game, alice, bob = _w1g11_table(set_pool, [mrd["Grim Reminder"]],
                                    library=library)
    bob.spells_cast_this_turn.extend(lea[name] for name in bob_cast)
    return game, alice, bob


def _w1g11_index_of(library, name):
    return next(i for i, card in enumerate(library) if card.name == name)


def test_w1g11_grim_reminder_punishes_the_opponent_who_cast_the_revealed_name(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Grim Reminder").supported
    assert not game.resolve_top_of_stack(), "held for the search"
    (choice,) = [c for c in game.pending_choices if c.kind == "search_library"]
    # A land is not a nonland card: the pick is refused.
    assert not game.confirm_search_library(0, _w1g11_index_of(alice.library, "Island"))
    assert game.confirm_search_library(
        0, _w1g11_index_of(alice.library, "Shivan Dragon"),
    )
    _w1g11_resolve_stack(game)
    assert bob.life == 14
    assert alice.life == 20
    # Revealed, never moved: the Dragon is still in the (shuffled) library.
    assert sorted(c.name for c in alice.library) == [
        "Forest", "Island", "Lightning Bolt", "Shivan Dragon",
    ]
    assert alice.hand == []
    assert any("revealed Shivan Dragon" in line for line in game.log)


def test_w1g11_grim_reminder_revealing_another_name_costs_nobody_life(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool)
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Grim Reminder").supported
    game.resolve_top_of_stack()
    assert game.confirm_search_library(
        0, _w1g11_index_of(alice.library, "Lightning Bolt"),
    )
    _w1g11_resolve_stack(game)
    assert bob.life == 20


def test_w1g11_grim_reminder_left_to_itself_shows_a_name_an_opponent_cast(set_pool):
    game, alice, bob = _w1g11_reminder_table(set_pool, bob_cast=("Lightning Bolt",))
    assert game.cast_from_hand(0, "Grim Reminder").supported
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g11_resolve_stack(game)
    assert bob.life == 14


def test_w1g11_grim_reminder_returns_from_the_graveyard_only_during_upkeep(set_pool):
    mrd = set_pool("MRD")
    game, alice, _bob = _w1g11_table(set_pool, [])
    alice.graveyard.append(mrd["Grim Reminder"])
    refused = game.activate_from_graveyard(0, "Grim Reminder")
    assert not refused.supported
    game.current_phase = "beginning"
    game.current_turn_phase, game.current_step = "beginning", "upkeep"
    result = game.activate_from_graveyard(0, "Grim Reminder")
    assert result.supported, result.details
    _w1g11_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Grim Reminder"]
    assert alice.graveyard == []

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
