"""Champions of Kamigawa instants — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), library=None, opponent_library=None,
                opponent_hand=(), mine=(), theirs=(), interactive=()):
    """Two seats on seat 0's first main phase, costs off; libraries top
    first. Names resolve in CHK first, then the older sets the tests use."""
    pools = [set_pool(code) for code in ("CHK", "LEA", "MRD", "TMP")]

    def named(name):
        for pool in pools:
            if name in pool:
                return pool[name]
        raise KeyError(name)

    game = _W1G7Game(players=[
        _W1G7PlayerState(
            "P0", hand=[named(n) for n in hand],
            library=[named(n) for n in (library or ["Forest"] * 10)],
        ),
        _W1G7PlayerState(
            "P1", hand=[named(n) for n in opponent_hand],
            library=[named(n) for n in (opponent_library or ["Island"] * 10)],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G7Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def test_w1g7_peer_through_depths_takes_an_instant_or_sorcery(set_pool):
    game = _w1g7_table(
        set_pool, hand=["Peer Through Depths"],
        library=["Forest", "Grizzly Bears", "Lightning Bolt", "Wrath of God",
                 "Craw Wurm", "Island"],
        interactive={0},
    )
    assert game.cast_from_hand(0, "Peer Through Depths").supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "look_top_pick"
    offered = game.live_look_top_candidates(asked)
    assert [game.players[0].library[i].name for i in offered] == [
        "Lightning Bolt", "Wrath of God",
    ]
    assert not game.confirm_look_top_pick(0, 1)          # a creature card
    assert game.confirm_look_top_pick(0, 3)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Wrath of God"]
    library = _w1g7_names(game.players[0].library)
    assert library[0] == "Island"
    assert sorted(library[1:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt", "Craw Wurm"]
    )


def _w1g7_hinder_a_bolt(set_pool, interactive):
    game = _w1g7_table(
        set_pool, hand=["Hinder"], opponent_hand=["Lightning Bolt"],
        opponent_library=["Island", "Swamp"], interactive=interactive,
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Hinder", target_stack_index=0).supported
    return game


def test_w1g7_hinder_puts_the_countered_card_on_the_end_its_caster_picks(set_pool):
    """Its ruling (2020-08-07): Hinder's controller chooses the end."""
    for to_bottom, expected in (
        (False, ["Lightning Bolt", "Island", "Swamp"]),
        (True, ["Island", "Swamp", "Lightning Bolt"]),
    ):
        game = _w1g7_hinder_a_bolt(set_pool, interactive={0, 1})
        asked = _w1g7_settle(game, defaults=False)
        assert asked.kind == "library_end_choice" and asked.player_index == 0
        assert asked.data["moved_name"] == "Lightning Bolt"
        _w1g7_settle(game, answers={
            "library_end_choice":
                lambda g, c: g.confirm_library_end_choice(c.player_index, to_bottom),
        })
        assert _w1g7_names(game.players[1].library) == expected
        assert game.players[1].graveyard == []
        assert game.players[0].life == 20          # the Bolt was countered
        assert _w1g7_names(game.players[0].graveyard) == ["Hinder"]


def _w1g7_sift_after(set_pool, casts):
    game = _w1g7_table(
        set_pool, hand=[*casts, "Sift Through Sands", "Lightning Bolt"],
        library=["Forest", "Island", "The Unspeakable", "Swamp", "Mountain",
                 "Plains", "Island", "Forest"],
    )
    for name in casts:
        assert game.cast_from_hand(0, name).supported
        _w1g7_settle(game)
    assert game.cast_from_hand(0, "Sift Through Sands").supported
    _w1g7_settle(game)
    return game


def test_w1g7_sift_through_sands_finds_the_unspeakable_after_both_spells(set_pool):
    game = _w1g7_sift_after(set_pool, ["Peer Through Depths", "Reach Through Mists"])
    assert [p.card.name for p in game.all_permanents()] == ["The Unspeakable"]
    assert "The Unspeakable" not in _w1g7_names(game.players[0].library)


def test_w1g7_sift_through_sands_needs_both_names_cast_this_turn(set_pool):
    """Either spell alone answers one half of the record and not the other:
    the draw and the discard happen, the search does not."""
    for casts in ([], ["Peer Through Depths"], ["Reach Through Mists"]):
        game = _w1g7_sift_after(set_pool, casts)
        assert list(game.all_permanents()) == [], casts
        assert "The Unspeakable" in _w1g7_names(game.players[0].library) + _w1g7_names(
            game.players[0].hand
        ) + _w1g7_names(game.players[0].graveyard), casts
        assert any("drew 2 card(s)" in line for line in game.log)


_W1G7_GIFTS_LIBRARY = [
    "Lightning Bolt", "Lightning Bolt", "Grizzly Bears", "Craw Wurm",
    "Dark Ritual", "Forest", "Island",
]


def _w1g7_gifts(set_pool, interactive):
    game = _w1g7_table(
        set_pool, hand=["Gifts Ungiven"], library=_W1G7_GIFTS_LIBRARY,
        interactive=interactive,
    )
    assert game.cast_from_hand(0, "Gifts Ungiven", target_player_index=1).supported
    return game


def _w1g7_find(game, names):
    library = _w1g7_names(game.players[0].library)
    return game.resolve_pending_choice("search_library", 0, picks=[
        {"zone": "library", "index": library.index(name)} for name in names
    ])


def test_w1g7_gifts_ungiven_the_opponent_splits_four_different_names(set_pool):
    game = _w1g7_gifts(set_pool, interactive={0, 1})
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "search_library" and asked.data["up_to"]
    # "with different names": two Lightning Bolts are refused, nothing moves.
    library = _w1g7_names(game.players[0].library)
    assert not game.resolve_pending_choice("search_library", 0, picks=[
        {"zone": "library", "index": 0}, {"zone": "library", "index": 1},
    ])
    assert _w1g7_names(game.players[0].library) == library
    assert _w1g7_find(game, ["Lightning Bolt", "Grizzly Bears", "Craw Wurm", "Dark Ritual"])
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "opponent_picks_revealed" and asked.player_index == 1
    assert asked.data["cards"] == ["Lightning Bolt", "Grizzly Bears", "Craw Wurm", "Dark Ritual"]
    assert game.confirm_opponent_picks_revealed(1, 0)
    asked = _w1g7_settle(game, defaults=False)
    # The second of two picks, the first one no longer on offer.
    assert asked.kind == "opponent_picks_revealed" and asked.data["legal_indices"] == [1, 2, 3]
    assert not game.confirm_opponent_picks_revealed(1, 0)
    assert game.confirm_opponent_picks_revealed(1, 3)
    _w1g7_settle(game)
    player = game.players[0]
    assert _w1g7_names(player.hand) == ["Grizzly Bears", "Craw Wurm"]
    assert _w1g7_names(player.graveyard) == ["Lightning Bolt", "Dark Ritual", "Gifts Ungiven"]
    assert sorted(_w1g7_names(player.library)) == ["Forest", "Island", "Lightning Bolt"]


def test_w1g7_gifts_ungiven_finding_two_puts_both_in_the_graveyard(set_pool):
    """Its ruling (2017-03-14): with one or two found, the opponent must
    choose them for the graveyard — so nobody is asked."""
    game = _w1g7_gifts(set_pool, interactive={0, 1})
    _w1g7_settle(game, defaults=False)
    assert _w1g7_find(game, ["Lightning Bolt", "Craw Wurm"])
    assert _w1g7_settle(game, defaults=False) is None
    player = game.players[0]
    assert player.hand == []
    assert _w1g7_names(player.graveyard) == ["Lightning Bolt", "Craw Wurm", "Gifts Ungiven"]


def test_w1g7_gifts_ungiven_at_seats_nobody_asks(set_pool):
    game = _w1g7_gifts(set_pool, interactive=())
    _w1g7_settle(game)
    player = game.players[0]
    found = _w1g7_names(player.hand) + _w1g7_names(player.graveyard)[:-1]
    assert len(player.hand) == 2 and len(found) == 4
    assert len(set(found)) == 4                         # four different names
    assert _w1g7_names(player.graveyard)[-1] == "Gifts Ungiven"


def test_w1g7_hinder_at_a_seat_nobody_asks_buries_the_card(set_pool):
    game = _w1g7_hinder_a_bolt(set_pool, interactive=())
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].library) == ["Island", "Swamp", "Lightning Bolt"]
    assert game.players[0].life == 20

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Yamabushi's Flame --------------------------------------------------------
# "Yamabushi's Flame deals 3 damage to any target. If a creature dealt damage
# this way would die this turn, exile it instead." A replacement on what the
# damage was *dealt* to (CR 615.1a), for the rest of the turn and by any
# means of dying (CR 700.4).


def test_w1g8_yamabushis_flame_exiles_the_creature_it_kills(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (hill,) = _w1g8_table([], [giant], hand=[flame])
    cast = game.cast_from_hand(
        0, "Yamabushi's Flame", target_permanent_ids=[hill.permanent_id]
    )
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_yamabushis_flame_exiles_a_survivor_that_dies_later_this_turn(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    terror = set_pool("LEA")["Terror"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (wurm,) = _w1g8_table([], [craw], hand=[flame, terror])
    assert game.cast_from_hand(
        0, "Yamabushi's Flame", target_permanent_ids=[wurm.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.is_on_battlefield(wurm)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[wurm.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Craw Wurm"]


def test_w1g8_yamabushis_flame_at_a_player_is_plain_damage(set_pool):
    flame = set_pool("CHK")["Yamabushi's Flame"]
    game, _, _ = _w1g8_table([], [], hand=[flame])
    assert game.cast_from_hand(0, "Yamabushi's Flame", target_player_index=1).supported
    _w1g8_settle(game)
    assert game.players[1].life == 17


# --- Otherworldly Journey -----------------------------------------------------
# "Exile target creature. At the beginning of the next end step, return that
# card to the battlefield under its owner's control with a +1/+1 counter on
# it." Liberate's delayed return (CR 603.7) with Sand Golem's counter rider:
# a new object (CR 400.7) with one +1/+1 counter (the 2004-12-01 ruling).


def test_w1g8_otherworldly_journey_returns_the_creature_with_a_counter(set_pool):
    journey = set_pool("CHK")["Otherworldly Journey"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, _, (bear,) = _w1g8_table([], [bears], hand=[journey])
    cast = game.cast_from_hand(
        0, "Otherworldly Journey", target_permanent_ids=[bear.permanent_id]
    )
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Grizzly Bears"]
    assert not game.is_on_battlefield(bear)

    game._set_phase_and_step("ending", "end")
    game.resolve_end_step(0)
    _w1g8_settle(game)
    returned = [p for p in game.controlled_by(game.players[1])]
    assert [p.card.name for p in returned] == ["Grizzly Bears"]
    back = returned[0]
    assert back is not bear
    assert (back.effective_power, back.effective_toughness) == (3, 3)
    assert _w1g8_zone_names(game, 1, "exile") == []


def test_w1g8_otherworldly_journey_returns_a_stolen_creature_to_its_owner(set_pool):
    from engine.control import change_control

    journey = set_pool("CHK")["Otherworldly Journey"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, _, (bear,) = _w1g8_table([], [bears], hand=[journey])
    change_control(bear, 0, source="a test")
    game._sync_control()
    assert game.controller_index_of(bear) == 0
    assert game.cast_from_hand(
        0, "Otherworldly Journey", target_permanent_ids=[bear.permanent_id]
    ).supported
    _w1g8_settle(game)
    game._set_phase_and_step("ending", "end")
    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert [p.card.name for p in game.controlled_by(game.players[1])] == ["Grizzly Bears"]
    assert [p.card.name for p in game.controlled_by(game.players[0])] == []



# --- Crushing Pain (drive list) -----------------------------------------------
# "Crushing Pain deals 6 damage to target creature that was dealt damage this
# turn." Supported on arrival and wrong: the narrowing rode the instruction's
# filter, but a ``deal_damage`` cast is judged by the target spec alone, which
# dropped it (``target_descriptions._narrowing_flags``) — an undamaged
# creature was a legal announcement and took the 6 (CR 601.2c).


def test_w1g8_crushing_pain_targets_only_a_creature_dealt_damage_this_turn(set_pool):
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pain = set_pool("CHK")["Crushing Pain"]
    shock = set_pool("LEA")["Lightning Bolt"]
    craw = set_pool("LEA")["Craw Wurm"]
    assert derive_cast_spec(pain, compile_card_oracle(pain)) == {
        "kind": "creature", "filter": {"dealt_damage_this_turn": True},
    }
    game, _, (wurm,) = _w1g8_table([], [craw], hand=[pain, shock])
    refused = game.cast_from_hand(
        0, "Crushing Pain", target_permanent_ids=[wurm.permanent_id]
    )
    assert not refused.supported
    assert wurm.damage_marked == 0
    assert "Crushing Pain" in _w1g8_zone_names(game, 0, "hand")

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[wurm.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(
        0, "Crushing Pain", target_permanent_ids=[wurm.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(wurm)

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
