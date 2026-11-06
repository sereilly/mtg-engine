"""Scourge enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
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
#
# Faces of the Past's choice made as its death trigger resolves, read off the
# dead creature as it last existed; Unspeakable Symbol (supported on arrival)
# driven.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import counters_on as _w1g9_counters_on
from engine.type_changes import gain_types as _w1g9_gain_types
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_permanent(card, *, tapped=False):
    permanent = _W1G9Permanent(card=card, tapped=tapped)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_game(mine=(), theirs=(), *, interactive=False):
    p1 = _W1G9PlayerState(name="A", battlefield=list(mine),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game, p1, p2


def _w1g9_elf_board(set_pool, *, interactive):
    """Faces of the Past and an Elf on seat 0; on seat 1 an untapped Elf, a
    tapped Elf and an untapped Bear."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    untapped_elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    tapped_elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"], tapped=True)
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game(
        [faces, dying], [untapped_elf, tapped_elf, bear], interactive=interactive,
    )
    return game, dying, untapped_elf, tapped_elf, bear


@_w1g9_pytest.mark.parametrize("mode", [0, 1])
def test_w1g9_faces_of_the_past_asks_tap_or_untap_as_it_resolves(set_pool, mode):
    """"Whenever a creature dies, tap all untapped creatures that share a
    creature type with it or untap all tapped creatures that share a creature
    type with it." The 2004-10-04 rulings: the choice is made on resolution,
    and it is all of one or all of the other. An Elf dies: tapping taps the
    untapped Elf, untapping untaps the tapped one, and the Bear (no shared
    type) is never touched."""
    game, dying, untapped_elf, tapped_elf, bear = _w1g9_elf_board(set_pool, interactive=True)
    game.sacrifice_permanent(dying)
    assert [item.card.name for item in game.stack] == ["Faces of the Past"]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [item.card.name for item in game.stack] == ["Faces of the Past"], (
        "held on the stack for the choice (CR 608.2)"
    )
    (choice,) = game.pending_choices_of("mode_choice", 0)
    assert len(choice.data["labels"]) == 2
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode)
    _w1g9_resolve_stack(game)
    if mode == 0:
        assert untapped_elf.tapped and tapped_elf.tapped
    else:
        assert not untapped_elf.tapped and not tapped_elf.tapped
    assert not bear.tapped
    assert not game.stack and not game.pending_choices


def test_w1g9_faces_of_the_past_default_taps(set_pool):
    """A seat nobody asks takes the first printed alternative, the tap."""
    game, dying, untapped_elf, tapped_elf, bear = _w1g9_elf_board(set_pool, interactive=False)
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert untapped_elf.tapped and tapped_elf.tapped and not bear.tapped
    assert any(
        'Faces of the Past: chose "tap all untapped creatures' in line for line in game.log
    )


def test_w1g9_faces_of_the_past_reads_the_dead_creatures_last_known_types(set_pool):
    """"It" is the creature that died, as it last existed on the battlefield
    (CR 608.2h): a Bear an effect had made a Goblin dies a Goblin, so the
    Goblin is tapped and the other Bear is not."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    _w1g9_gain_types(
        dying, subtypes=["goblin"], source="test", duration="permanent",
        replaces_creature_types=True,
    )
    goblin = _w1g9_permanent(_W1G9_CATALOG["Raging Goblin"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, _p1, _p2 = _w1g9_game([faces, dying], [goblin, bear])
    assert dying.has_type("goblin") and not dying.has_type("bear")
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert goblin.tapped
    assert not bear.tapped


def test_w1g9_faces_of_the_past_with_nobody_of_the_type_turns_nothing(set_pool):
    """A creature that shares a type with nothing on the battlefield taps
    nothing — the relation is never dropped into "every creature"."""
    faces = _w1g9_permanent(set_pool("SCG")["Faces of the Past"])
    dying = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    elf = _w1g9_permanent(_W1G9_CATALOG["Llanowar Elves"])
    game, _p1, _p2 = _w1g9_game([faces, dying], [elf])
    game.sacrifice_permanent(dying)
    _w1g9_resolve_stack(game)
    assert not elf.tapped
    assert any("Faces of the Past: nothing to tap or untap" in line for line in game.log)


# --- Supported on arrival, driven: Unspeakable Symbol ---------------------------


def test_w1g9_unspeakable_symbol_buys_a_counter_with_three_life(set_pool):
    """"Pay 3 life: Put a +1/+1 counter on target creature." Paid at 20, and
    refused at 2 life (CR 119.4) with nothing paid."""
    symbol = _w1g9_permanent(set_pool("SCG")["Unspeakable Symbol"])
    bear = _w1g9_permanent(_W1G9_CATALOG["Grizzly Bears"])
    game, p1, _p2 = _w1g9_game([symbol, bear])
    result = game.activate_permanent_ability(
        0, "Unspeakable Symbol", ability_index=0, target_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    assert p1.life == 17 and _w1g9_counters_on(bear, "+1/+1") == 1
    p1.life = 2
    refused = game.activate_permanent_ability(
        0, "Unspeakable Symbol", ability_index=0, target_permanent_ids=[bear.permanent_id],
    )
    assert not refused.supported
    assert p1.life == 2 and _w1g9_counters_on(bear, "+1/+1") == 1

# ==== end W1G9 ======================================================
