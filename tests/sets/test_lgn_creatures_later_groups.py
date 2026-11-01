"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Libraries, graveyards and exile: a two-card search, a three-zone search for
# a named card, a chosen-type graveyard shuffle, a revealed top card put onto
# the battlefield by type, a dies trigger that exiles itself and returns
# targets, and an exile of every creature until the next end step.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve


def _w1g6_card(set_pool, name):
    for code in ("LGN", "ONS", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_game(set_pool, *, library=(), opp_library=(), interactive=False):
    """Two seats in seat 0's precombat main phase, mana costs off."""
    me = _w1g6_PlayerState(
        name="Me", library=[_w1g6_card(set_pool, n) for n in library],
    )
    opp = _w1g6_PlayerState(
        name="Opp",
        library=[_w1g6_card(set_pool, n) for n in (opp_library or ["Forest"] * 5)],
    )
    game = _w1g6_Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game, me, opp


def _w1g6_put(game, seat, set_pool, name):
    perm = _w1g6_Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# --- Corpse Harvester -------------------------------------------------------


def _w1g6_harvester(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool,
        library=["Forest", "Withered Wretch", "Forest", "Swamp", "Grizzly Bears"],
        interactive=interactive,
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Corpse Harvester")).supported
    _w1g6_put(game, 0, set_pool, "Corpse Harvester")
    fodder = _w1g6_put(game, 0, set_pool, "Grizzly Bears")
    result = game.activate_permanent_ability(
        0, "Corpse Harvester", cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result.details
    assert [c.name for c in me.graveyard] == ["Grizzly Bears"], "the sacrifice is paid"
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, me


def test_w1g6_corpse_harvester_finds_a_zombie_and_a_swamp_and_reveals_them(set_pool):
    """"Search your library for a Zombie card and a Swamp card, reveal them,
    put them into your hand, then shuffle." Answered as an interactive seat:
    one pick per printed description, both shown to the table (CR 701.20)."""
    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    # A pick that fills the Swamp slot with a Forest is no answer.
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Forest")},
    ])
    # Nor are two cards for one description (the Bears is not a Zombie).
    assert not game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Grizzly Bears")},
    ])
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": library.index("Withered Wretch")},
        {"zone": "library", "index": library.index("Swamp")},
    ])
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]
    assert sorted(c.name for c in me.library) == ["Forest", "Forest", "Grizzly Bears"]
    assert any(e["cards"] == ["Withered Wretch", "Swamp"] for e in game.reveal_events)
    assert "Me revealed Withered Wretch, Swamp" in game.log


def test_w1g6_corpse_harvester_default_seat_finds_both_and_may_find_one(set_pool):
    """A default seat takes both finds; the ruling (2004-10-04) lets a player
    find fewer, which an interactive seat states with one pick."""
    game, me = _w1g6_harvester(set_pool, interactive=False)
    game.auto_resolve_pending_choices()
    assert sorted(c.name for c in me.hand) == ["Swamp", "Withered Wretch"]

    game, me = _w1g6_harvester(set_pool, interactive=True)
    library = [c.name for c in me.library]
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": library.index("Swamp")}],
    )
    _w1g6_resolve(game)
    assert [c.name for c in me.hand] == ["Swamp"]


# --- Elvish Soultiller ------------------------------------------------------


def _w1g6_soultiller_dies(set_pool, *, interactive):
    game, me, _opp = _w1g6_game(
        set_pool, library=["Forest"] * 3, interactive=interactive,
    )
    me.graveyard.extend(
        _w1g6_card(set_pool, name) for name in (
            "Elvish Warrior", "Llanowar Elves", "Goblin Sky Raider", "Forest",
            "Llanowar Elves",
        )
    )
    assert _w1g6_compile(_w1g6_card(set_pool, "Elvish Soultiller")).supported
    soultiller = _w1g6_put(game, 0, set_pool, "Elvish Soultiller")
    game.sacrifice_permanent(soultiller)
    assert [item.card.name for item in game.stack] == ["Elvish Soultiller"]
    return game, me


def test_w1g6_elvish_soultiller_shuffles_back_only_the_chosen_type(set_pool):
    """"When this creature dies, choose a creature type. Shuffle all creature
    cards of that type from your graveyard into your library." Answered as an
    interactive seat with Goblin: the Goblin goes, the Elves and the land
    stay — the narrowing is the chosen word, not every creature card."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=True)
    game.resolve_top_of_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "creature_type_choice"
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g6_resolve(game)
    assert sorted(c.name for c in me.graveyard) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Llanowar Elves",
        "Llanowar Elves",
    ]
    assert sorted(c.name for c in me.library) == [
        "Forest", "Forest", "Forest", "Goblin Sky Raider",
    ]
    assert "Me shuffled 1 card(s) from their graveyard into their library" in game.log


def test_w1g6_elvish_soultiller_default_names_its_own_commonest_graveyard_type(set_pool):
    """A seat nobody asks names the type its own graveyard holds most of —
    the shuffle is a gift to the chooser — and the Soultiller, an Elf
    Mutant already in the graveyard, goes back with the Elves."""
    game, me = _w1g6_soultiller_dies(set_pool, interactive=False)
    _w1g6_resolve(game)
    assert "Elvish Soultiller: chose elf" in game.log
    assert sorted(c.name for c in me.graveyard) == ["Forest", "Goblin Sky Raider"]
    assert sorted(c.name for c in me.library) == [
        "Elvish Soultiller", "Elvish Warrior", "Forest", "Forest", "Forest",
        "Llanowar Elves", "Llanowar Elves",
    ]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
