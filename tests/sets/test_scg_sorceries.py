"""Scourge sorceries.

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
#
# Storm (CR 702.40, ``engine/storm.py``) on the four storm sorceries, Mind's
# Desire's "until end of turn, you may play that card without paying its mana
# cost" (a cast *and* a land play out of exile), and the drive list's three
# sorceries.

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game
from engine import PlayerState as _w1g1_PlayerState
from engine.cast_permissions import permission_for as _w1g1_permission_for
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_card(set_pool, name):
    """A card by name, from Scourge first and Alpha for the fillers."""
    scg = set_pool("SCG")
    return scg[name] if name in scg else set_pool("LEA")[name]


def _w1g1_table(set_pool, hand=(), *, mine=(), theirs=(), library=None,
                interactive=()):
    card = lambda name: _w1g1_card(set_pool, name)  # noqa: E731
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            "A", hand=[card(n) for n in hand],
            library=[card(n) for n in (library or ["Forest"] * 12)],
        ),
        _w1g1_PlayerState("B", library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g1_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g1_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g1_cast_fillers(game, count):
    for _ in range(count):
        result = game.queue_from_hand(0, "Dark Ritual")
        assert result.supported, result.details
        _w1g1_resolve_stack(game)


def _w1g1_settle(game):
    """Drain the stack and every queued headless decision (a search)."""
    for _ in range(10):
        _w1g1_resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_dragonstorm_puts_a_dragon_onto_the_battlefield_per_copy(set_pool, before):
    library = ["Shivan Dragon"] * 5 + ["Craw Wurm", "Forest"] * 3
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Dragonstorm"], library=library,
    )
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Dragonstorm").supported
    _w1g1_settle(game)
    dragons = [
        permanent for permanent in game.controlled_by(game.players[0])
        if permanent.card.name == "Shivan Dragon"
    ]
    assert len(dragons) == before + 1
    assert not any(
        permanent.card.name == "Craw Wurm"
        for permanent in game.controlled_by(game.players[0])
    )


@_w1g1_pytest.mark.parametrize("before", [0, 1, 3])
def test_w1g1_tendrils_of_agony_drains_two_per_copy(set_pool, before):
    game, _, _ = _w1g1_table(set_pool, ["Dark Ritual"] * before + ["Tendrils of Agony"])
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Tendrils of Agony", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    drained = 2 * (before + 1)
    assert [player.life for player in game.players] == [20 + drained, 20 - drained]


def test_w1g1_temporal_fissure_copies_each_bounce_another_permanent(set_pool):
    game, _, theirs = _w1g1_table(
        set_pool, ["Dark Ritual", "Dark Ritual", "Temporal Fissure"],
        theirs=["Grizzly Bears", "Craw Wurm", "Forest"], interactive=[0],
    )
    _w1g1_cast_fillers(game, 2)
    assert game.queue_from_hand(
        0, "Temporal Fissure", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    assert game.confirm_copy_spell_target(0, permanent_id=theirs[1].permanent_id)
    assert game.confirm_copy_spell_target(0, permanent_id=theirs[2].permanent_id)
    _w1g1_resolve_stack(game)
    assert list(game.controlled_by(game.players[1])) == []
    assert sorted(card.name for card in game.players[1].hand) == [
        "Craw Wurm", "Forest", "Grizzly Bears",
    ]


def test_w1g1_minds_desire_casts_the_exiled_card_for_free(set_pool):
    """A spell exiled by Mind's Desire is cast without paying its mana cost:
    Craw Wurm's {4}{G}{G} out of a board of six Islands, nothing tapped."""
    game, islands, _ = _w1g1_table(
        set_pool, ["Mind's Desire"], mine=["Island"] * 6, library=["Craw Wurm"] * 6,
    )
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    wurm = game.players[0].exile[-1]
    assert wurm.name == "Craw Wurm"
    assert _w1g1_permission_for(game, 0, wurm, "exile") is not None
    game.enforce_mana_costs = True
    result = game.queue_from_hand(0, "Craw Wurm", from_zone="exile")
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(game.players[0])].count("Craw Wurm") == 1
    assert not any(island.tapped for island in islands)


def test_w1g1_minds_desire_plays_an_exiled_land_with_the_land_drop(set_pool):
    """"Play" covers a land (CR 305.1): the exiled Forest is played, and the
    land drop it uses is the turn's (CR 305.2) — the one in hand is refused."""
    game, _, _ = _w1g1_table(
        set_pool, ["Mind's Desire", "Swamp"], library=["Forest"] * 6,
    )
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    game.enforce_mana_costs = True
    assert game.cast_from_hand(0, "Forest", from_zone="exile").supported
    assert game.players[0].exile == []
    assert not game.cast_from_hand(0, "Swamp").supported


@_w1g1_pytest.mark.parametrize("before", [1, 2])
def test_w1g1_minds_desire_copies_each_exile_and_grant_their_own_card(set_pool, before):
    """Each storm copy shuffles, exiles the top card and grants its own play
    (the brief's "storm copies each exile and grant their own card")."""
    game, _, _ = _w1g1_table(
        set_pool, ["Dark Ritual"] * before + ["Mind's Desire"],
        library=["Grizzly Bears"] * 8,
    )
    _w1g1_cast_fillers(game, before)
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    exiled = list(game.players[0].exile)
    assert len(exiled) == before + 1
    for _ in exiled:
        assert game.queue_from_hand(0, "Grizzly Bears", from_zone="exile").supported
        _w1g1_resolve_stack(game)
    assert game.players[0].exile == []
    assert [p.card.name for p in game.controlled_by(game.players[0])] == (
        ["Grizzly Bears"] * (before + 1)
    )


def test_w1g1_minds_desire_card_left_unplayed_stays_exiled(set_pool):
    """2004-10-04: "If the card is not played by end of turn, it remains
    exiled until end of game." The permission ends at cleanup (CR 514.2)."""
    game, _, _ = _w1g1_table(set_pool, ["Mind's Desire"], library=["Craw Wurm"] * 6)
    assert game.queue_from_hand(0, "Mind's Desire").supported
    _w1g1_resolve_stack(game)
    wurm = game.players[0].exile[-1]
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert _w1g1_permission_for(game, 0, wurm, "exile") is None
    assert [card.name for card in game.players[0].exile] == ["Craw Wurm"]
    game.start_next_turn()
    game.start_next_turn()
    assert not game.queue_from_hand(0, "Craw Wurm", from_zone="exile").supported


# -- The drive list: Scourge sorceries supported on arrival -----------------


def test_w1g1_skulltap_sacrifices_the_named_creature_and_draws_two(set_pool):
    game, (bears, elves), _ = _w1g1_table(
        set_pool, ["Skulltap"], mine=["Grizzly Bears", "Llanowar Elves"],
    )
    result = game.queue_from_hand(0, "Skulltap", cost_permanent_ids=[elves.permanent_id])
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(game.players[0])] == ["Grizzly Bears"]
    assert len(game.players[0].hand) == 2
    # No creature, no cast (2013-04-15: "you cannot cast it without
    # sacrificing a creature").
    game, _, _ = _w1g1_table(set_pool, ["Skulltap"])
    assert not game.queue_from_hand(0, "Skulltap").supported


def test_w1g1_misguided_rage_target_player_chooses_the_sacrifice(set_pool):
    game, _, theirs = _w1g1_table(
        set_pool, ["Misguided Rage"], theirs=["Grizzly Bears", "Forest"],
        interactive=[1],
    )
    assert game.queue_from_hand(0, "Misguided Rage", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    owed = game.pending_choices[0]
    assert owed.kind == "sacrifice" and owed.player_index == 1
    game.take_choice_default(owed)
    _w1g1_resolve_stack(game)
    assert len(list(game.controlled_by(game.players[1]))) == 1
    assert len(game.players[1].graveyard) == 1


def test_w1g1_goblin_war_strike_counts_goblins_you_control(set_pool):
    game, _, _ = _w1g1_table(
        set_pool, ["Goblin War Strike"],
        mine=["Goblin King", "Goblin Balloon Brigade", "Grizzly Bears"],
        theirs=["Goblin King"],
    )
    assert game.queue_from_hand(0, "Goblin War Strike", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 18

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

# ==== end W1G9 ======================================================
