"""Judgment lands.

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
#
# Riftstone Portal: 'As long as this card is in your graveyard, lands you
# control have "{T}: Add {G} or {W}."' — a granted *mana ability* from a
# graveyard (CR 113.6b), driven through the tap seam and the payment planner,
# the two readers a granted mana ability has to reach.

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.board_payment import board_can_pay as _w1g1_board_can_pay
from engine.board_payment import tap_alone_symbols as _w1g1_tap_alone_symbols
from engine.models import Permanent as _W1G1Permanent


def _w1g1_lands_table(set_pool, *lands):
    """Seat 0 on its first main phase with *lands* (card names) on its side."""
    pool = {**set_pool("LEA"), **set_pool("JUD")}
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", life=20, library=[pool["Island"]] * 10)
        for seat in range(2)
    ])
    game.interactive_seats = set()
    game.start_turn(0)
    placed = []
    for name in lands:
        permanent = _W1G1Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        placed.append(permanent)
    game._settle()
    return game, placed


def _w1g1_pool(game, seat=0):
    return {symbol: n for symbol, n in game.players[seat].mana_pool.items() if n}


def test_w1g1_riftstone_portal_in_the_graveyard_lets_a_swamp_tap_for_green_or_white(set_pool):
    """With Riftstone Portal in its owner's graveyard a Swamp has the granted
    ability **beside its own**: asked for {G} it makes {G}, asked for {W} it
    makes {W}, and asked for {B} it still makes {B} — the Swamp's CR 305.6
    ability is no text, and the grant used to be the only mana ability the
    tap seam could find. Through ``tap_land_for_mana``, the one seam every tap
    goes through."""
    for colour in ("G", "W", "B"):
        game, (swamp,) = _w1g1_lands_table(set_pool, "Swamp")
        assert game.put_card_into_graveyard(0, set_pool("JUD")["Riftstone Portal"])
        game._settle()

        assert sorted(_w1g1_tap_alone_symbols(game, swamp)) == sorted(["B", "G", "W"])
        assert game.tap_land_for_mana(0, "Swamp", colour, permanent_id=swamp.permanent_id)
        assert _w1g1_pool(game) == {colour: 1}, game.log[-3:]


def test_w1g1_riftstone_portal_lets_the_planner_pay_green_and_white_from_swamps(set_pool):
    """The automatic payment's question (``board_can_pay``): two Swamps pay
    {G}{W} only while the Portal is in the graveyard."""
    game, _ = _w1g1_lands_table(set_pool, "Swamp", "Swamp")
    assert not _w1g1_board_can_pay(game, 0, {"G": 1, "W": 1})
    assert game.put_card_into_graveyard(0, set_pool("JUD")["Riftstone Portal"])
    game._settle()
    assert _w1g1_board_can_pay(game, 0, {"G": 1, "W": 1})
    # …and the Swamps' own {B} is still counted beside the grant.
    assert _w1g1_board_can_pay(game, 0, {"B": 1, "G": 1})
    assert _w1g1_board_can_pay(game, 0, {"B": 2})


def test_w1g1_riftstone_portal_on_the_battlefield_taps_for_colourless_only(set_pool):
    """CR 113.6b: on the battlefield the graveyard ability does nothing — the
    Portal taps for its own {C}, and the Swamp beside it for {B} alone."""
    game, (portal, swamp) = _w1g1_lands_table(set_pool, "Riftstone Portal", "Swamp")

    assert not _w1g1_board_can_pay(game, 0, {"G": 1})
    assert game.tap_land_for_mana(0, "Swamp", "G", permanent_id=swamp.permanent_id)
    assert game.tap_land_for_mana(
        0, "Riftstone Portal", "G", permanent_id=portal.permanent_id
    )
    assert _w1g1_pool(game) == {"B": 1, "C": 1}, game.log[-3:]


def test_w1g1_riftstone_portal_leaving_the_graveyard_takes_the_ability_away(set_pool):
    """The grant lasts exactly as long as the card is there (CR 611.3b): the
    Portal is put into the graveyard by being destroyed on the battlefield,
    then exiled from it, and the Swamp's colours follow."""
    game, (portal, swamp) = _w1g1_lands_table(set_pool, "Riftstone Portal", "Swamp")
    game.sacrifice_permanent(portal)
    game._settle()
    assert "Riftstone Portal" in [card.name for card in game.players[0].graveyard]
    assert sorted(_w1g1_tap_alone_symbols(game, swamp)) == sorted(["B", "G", "W"])

    graveyard = game.players[0].graveyard
    game.players[0].exile.append(graveyard.pop(graveyard.index(
        next(card for card in graveyard if card.name == "Riftstone Portal")
    )))
    game._settle()
    assert not _w1g1_board_can_pay(game, 0, {"G": 1})
    assert game.tap_land_for_mana(0, "Swamp", "G", permanent_id=swamp.permanent_id)
    assert _w1g1_pool(game) == {"B": 1}, game.log[-3:]


def test_w1g1_riftstone_portal_grants_only_its_owners_lands(set_pool):
    """"Lands **you** control": the graveyard's owner's (CR 108.4a), not the
    opponent's."""
    game, _ = _w1g1_lands_table(set_pool)
    theirs = _W1G1Permanent(card=set_pool("LEA")["Swamp"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    assert game.put_card_into_graveyard(0, set_pool("JUD")["Riftstone Portal"])
    game._settle()
    assert not _w1g1_board_can_pay(game, 1, {"G": 1})
    assert game.tap_land_for_mana(1, "Swamp", "G", permanent_id=theirs.permanent_id)
    assert _w1g1_pool(game, 1) == {"B": 1}

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _W1G10Game, PlayerState as _W1G10PlayerState
from engine.models import Permanent as _W1G10Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_verge_table(set_pool, library, *, interactive=(0,)):
    """Seat 0 with an untapped Krosan Verge and *library* (card names)."""
    pool = {**set_pool("LEA"), **set_pool("JUD")}
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name="P0", life=20, library=[pool[name] for name in library]
        ),
        _W1G10PlayerState(name="P1", life=20, library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    verge = _W1G10Permanent(card=pool["Krosan Verge"])
    game._put_permanent_onto_battlefield(0, verge, None)
    verge.metadata["summoning_sickness_turn"] = -99
    verge.tapped = False
    return game, verge


_W1G10_VERGE_LIBRARY = ["Island", "Forest", "Grizzly Bears", "Plains", "Savannah", "Forest"]


def _w1g10_picks(*indices):
    return [{"zone": "library", "index": index} for index in indices]


def test_w1g10_krosan_verge_finds_a_forest_and_a_plains_tapped(set_pool):
    """"{2}, {T}, Sacrifice this land: Search your library for a Forest card
    and a Plains card, put them onto the battlefield tapped, then shuffle."
    Two finds, one per description: two Forests are no answer, a Savannah (a
    Forest Plains) answers either description but not both, and the two found
    enter tapped (CR 110.5b). The Verge itself is sacrificed as the cost."""
    game, verge = _w1g10_verge_table(set_pool, _W1G10_VERGE_LIBRARY)

    result = game.activate_permanent_ability(0, "Krosan Verge", ability_index=1)
    assert result.supported, result.details
    assert not game.is_on_battlefield(verge)
    assert [card.name for card in game.players[0].graveyard] == ["Krosan Verge"]
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert prompt["count"] == 2 and prompt["up_to"]
    assert prompt["destinations"] == ["battlefield", "battlefield"]
    assert not game.confirm_search_library_picks(0, _w1g10_picks(1, 5)), "two Forests"
    assert not game.confirm_search_library_picks(0, _w1g10_picks(1, 2)), "not a land"
    assert not game.confirm_search_library_picks(0, _w1g10_picks(0, 3)), "an Island"
    # The Savannah as the Forest, the basic Plains as the Plains.
    assert game.confirm_search_library_picks(0, _w1g10_picks(4, 3))
    _w1g10_resolve_stack(game)
    game._settle()

    found = sorted((perm.card.name, perm.tapped) for perm in game.controlled_by(0))
    assert found == [("Plains", True), ("Savannah", True)]
    assert sorted(card.name for card in game.players[0].library) == [
        "Forest", "Forest", "Grizzly Bears", "Island",
    ]
    assert game.pending_choices == []


def test_w1g10_krosan_verge_may_find_only_one(set_pool):
    """CR 701.23b: a search for a card with a stated quality may fail to find
    it. With no Plains in the library the Forest alone is a legal answer — and
    a headless seat takes the finds it can."""
    game, _ = _w1g10_verge_table(
        set_pool, ["Island", "Forest", "Grizzly Bears"], interactive=(),
    )
    assert game.activate_permanent_ability(0, "Krosan Verge", ability_index=1).supported
    _w1g10_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert [(perm.card.name, perm.tapped) for perm in game.controlled_by(0)] == [
        ("Forest", True),
    ]
    assert sorted(card.name for card in game.players[0].library) == [
        "Grizzly Bears", "Island",
    ]

# ==== end W1G10 ======================================================
