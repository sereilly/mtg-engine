"""Apocalypse sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4s_pytest  # noqa: E402

from engine import Game as _w1g4s_Game, PlayerState as _w1g4s_Player  # noqa: E402
from engine.grammar import compile_line as _w1g4s_compile_line  # noqa: E402
from engine.models import Permanent as _w1g4s_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4s_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4s_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order. One pool per card, as
#: `tests/sets/README.md` asks; the order only matters for a reprint, and every
#: basic land resolves to Alpha's.
_W1G4S_POOLS = ("APC", "LEA", "ATQ", "MIR")


def _w1g4s_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4S_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 sorceries: no pool here prints that name


def _w1g4s_table(set_pool, *, mine=(), theirs=(), hand0=(), hand1=(), lib0=(),
                 lib1=(), gy0=(), gy1=(), interactive=(), seats=2):
    """A duel (or a table of *seats*) with seat 0 in its precombat main phase.

    Every zone is named card by card, so a test reads as the board it is about;
    libraries are top first. Costs are not enforced unless a test turns them on.
    """
    def cards(names):
        return [_w1g4s_card(set_pool, name) for name in names]

    boards = [
        [_w1g4s_Permanent(card=card) for card in cards(mine)],
        [_w1g4s_Permanent(card=card) for card in cards(theirs)],
    ]
    players = [
        _w1g4s_Player(name="P0", battlefield=boards[0], hand=cards(hand0),
                      library=cards(lib0), graveyard=cards(gy0)),
        _w1g4s_Player(name="P1", battlefield=boards[1], hand=cards(hand1),
                      library=cards(lib1), graveyard=cards(gy1)),
    ]
    for extra in range(2, seats):
        players.append(_w1g4s_Player(name=f"P{extra}", library=cards(["Swamp"] * 3)))
    game = _w1g4s_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in boards[0] + boards[1]:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, boards[0], boards[1]  # W1G4 sorceries: the table


def _w1g4s_names(cards):
    return [card.name for card in cards]  # W1G4 sorceries: a zone, by name


def _w1g4s_picks(*indices):
    """A counted search's answer over a library."""
    return [{"zone": "library", "index": index} for index in indices]  # W1G4


# -- Tahngarth's Glare -------------------------------------------------------

_W1G4S_GLARE_MINE = ["Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Black Lotus"]
_W1G4S_GLARE_THEIRS = ["Island", "Counterspell", "Air Elemental", "Mox Sapphire"]


def test_w1g4_tahngarths_glare_each_player_orders_the_others_top_three(set_pool):
    """"Look at the top three cards of target opponent's library, then put them
    back in any order. That player looks at the top three cards of your
    library, then puts them back in any order."

    Two looks and two seats: the caster orders the opponent's top three, and
    only then does the opponent order the caster's. Each prompt belongs to the
    seat that looks, over the *other* seat's library, and neither seat can
    answer the other's.
    """
    glare = _w1g4s_card(set_pool, "Tahngarth's Glare")
    assert _w1g4s_compile(glare).supported
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS, interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()

    first = game.pending_reorder_library
    assert (first["caster_index"], first["target_index"], first["top_count"]) == (0, 1, 3)
    assert len(game.pending_choices) == 1, "the second look waits for the first"
    assert not game.confirm_reorder_library(1, [2, 1, 0]), "not the opponent's prompt"
    assert game.confirm_reorder_library(0, [2, 1, 0])

    second = game.pending_reorder_library
    assert (second["caster_index"], second["target_index"], second["top_count"]) == (1, 0, 3)
    assert not game.confirm_reorder_library(0, [1, 0, 2]), "not the caster's prompt"
    assert game.confirm_reorder_library(1, [1, 0, 2])
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[1].library) == [
        "Air Elemental", "Counterspell", "Island", "Mox Sapphire",
    ]
    assert _w1g4s_names(game.players[0].library) == [
        "Hill Giant", "Forest", "Grizzly Bears", "Sol Ring", "Black Lotus",
    ]
    assert _w1g4s_names(game.players[0].graveyard) == ["Tahngarth's Glare"]
    assert game.pending_choices == []
    log = "\n".join(game.log)
    assert log.index("P0 is looking at the top 3 cards of P1's library") < log.index(
        "P1 is looking at the top 3 cards of P0's library"
    )


def test_w1g4_tahngarths_glare_targets_an_opponent_and_nobody_else(set_pool):
    """"Target **opponent**": the picker offers the other seat alone, and a
    cast aimed at the caster is refused with the card still in hand."""
    glare = _w1g4s_card(set_pool, "Tahngarth's Glare")
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS,
    )
    spec = game.cast_target_spec(0, glare)
    assert spec["kind"] == "player"
    assert spec["valid_targets"] == [{"kind": "player", "seat": 1}]

    refused = game.cast_from_hand(0, "Tahngarth's Glare", target_player_index=0)
    assert not refused.supported
    assert _w1g4s_names(game.players[0].hand) == ["Tahngarth's Glare"]
    assert game.pending_choices == []


def test_w1g4_tahngarths_glare_looks_at_what_a_short_library_holds(set_pool):
    """CR 609.3: as many as there are. A library of two is a choice between two
    cards; a library of one has no order to choose and is still a *look* — the
    seat is shown the card — and an empty one shows nothing and asks nobody."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=["Forest", "Hill Giant"],
        lib1=["Island"], interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()

    one = game.pending_reorder_library
    assert (one["caster_index"], one["target_index"], one["top_count"]) == (0, 1, 1)
    assert game.confirm_reorder_library(0, [0])
    two = game.pending_reorder_library
    assert (two["caster_index"], two["target_index"], two["top_count"]) == (1, 0, 2)
    assert game.confirm_reorder_library(1, [1, 0])
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].library) == ["Hill Giant", "Forest"]
    assert _w1g4s_names(game.players[1].library) == ["Island"]

    # The caster's own library empty: the first look happens, the second has
    # nothing to show, and the spell finishes with no prompt left behind.
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib1=["Island", "Swamp"],
        interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.resolve_top_of_stack()
    assert game.confirm_reorder_library(0, [1, 0])
    _w1g4s_resolve_stack(game)
    assert game.pending_choices == []
    assert _w1g4s_names(game.players[1].library) == ["Swamp", "Island"]
    assert "P0 has no cards for P1 to look at (Tahngarth's Glare)" in game.log


def test_w1g4_tahngarths_glare_default_seats_bury_and_surface(set_pool):
    """Two seats nobody asks: each look is answered by the stated policy with
    no prompt left behind, and both libraries keep exactly their cards."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Tahngarth's Glare"], lib0=_W1G4S_GLARE_MINE,
        lib1=_W1G4S_GLARE_THEIRS,
    )
    assert game.cast_from_hand(0, "Tahngarth's Glare", target_player_index=1).supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)

    assert game.pending_choices == []
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted(_W1G4S_GLARE_MINE)
    assert sorted(_w1g4s_names(game.players[1].library)) == sorted(_W1G4S_GLARE_THEIRS)
    assert _w1g4s_names(game.players[0].library)[3:] == ["Sol Ring", "Black Lotus"]


def test_w1g4_the_glares_second_look_reads_every_word_or_refuses():
    """The production's refusals. "That player looks at the top three cards of
    your library" with no rearrangement is not this sentence, a "random order"
    is not "any order", and a looker the sentence would have to *choose* is a
    target nothing here has a picker for — refused by name in the lowering."""
    second = (
        "That player looks at the top three cards of your library, then puts "
        "them back in any order."
    )
    assert _w1g4s_compile_line(second).usable
    assert not _w1g4s_compile_line(
        "That player looks at the top three cards of your library."
    ).parsed
    assert not _w1g4s_compile_line(second.replace("any order", "a random order")).parsed
    chosen = _w1g4s_compile_line(second.replace("That player", "Target opponent"))
    assert chosen.parsed and not chosen.lowered
    assert "only \"that player\"" in chosen.lowering_error


# -- Guided Passage ----------------------------------------------------------

#: A creature, a second creature, an artifact creature, two lands, and three
#: cards that are neither.
_W1G4S_PASSAGE_LIBRARY = [
    "Forest", "Hill Giant", "Grizzly Bears", "Sol Ring", "Black Lotus",
    "Island", "Counterspell", "Clockwork Beast",
]


def test_w1g4_guided_passage_an_opponent_picks_one_card_of_each_kind(set_pool):
    """"Reveal the cards in your library. An opponent chooses from among them a
    creature card, a land card, and a noncreature, nonland card. You put the
    chosen cards into your hand. Then shuffle."

    The whole library is shown to everybody, the *opponent* is the seat that is
    asked, and what it picks lands in the caster's hand.
    """
    passage = _w1g4s_card(set_pool, "Guided Passage")
    assert _w1g4s_compile(passage).supported
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
        interactive=(0, 1),
    )
    assert game.cast_target_spec(0, passage)["kind"] == "none"
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert game.reveal_events[-1] == {
        "id": 1, "seat": 0, "cards": list(_W1G4S_PASSAGE_LIBRARY),
    }
    prompt = game.pending_search_library
    assert prompt["caster_index"] == 1, "the opponent chooses"
    assert prompt["zone_seat"] == 0, "out of the caster's library"
    assert prompt["count"] == 3 and not prompt.get("up_to")
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(2, 5, 6)), (
        "the library's owner is not the one asked"
    )
    assert game.confirm_search_library_picks(1, _w1g4s_picks(2, 5, 6))
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == [
        "Grizzly Bears", "Island", "Counterspell",
    ]
    assert game.players[1].hand == []
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted([
        "Forest", "Hill Giant", "Sol Ring", "Black Lotus", "Clockwork Beast",
    ])
    assert _w1g4s_names(game.players[0].graveyard) == ["Guided Passage"]
    assert "P1 searched P0's library and found Grizzly Bears, Island, Counterspell" in game.log


def test_w1g4_guided_passage_holds_the_opponent_to_one_of_each(set_pool):
    """One card **per description**, and none of them optional. Two creatures
    are each a legal pick and together are not an answer; an artifact creature
    is not a "noncreature" card; and the opponent may neither decline nor stop
    at two while the library can answer all three."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
        interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert not game.decline_search_library(1)
    assert not game.confirm_search_library_picks(1, [])
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 0)), "one short"
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 2, 0)), (
        "two creatures fill one description"
    )
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(1, 0, 7)), (
        "Clockwork Beast is a creature card"
    )
    assert _w1g4s_names(game.players[0].library) == _W1G4S_PASSAGE_LIBRARY, (
        "a refused answer moves nothing"
    )
    assert game.confirm_search_library_picks(1, _w1g4s_picks(7, 0, 4))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == [
        "Clockwork Beast", "Forest", "Black Lotus",
    ]


def test_w1g4_guided_passage_skips_a_kind_the_library_does_not_hold(set_pool):
    """The card's ruling: "If you have no cards of any of the specified card
    types, then ignore those types and the opponent only selects cards of the
    types you do have." With no land to find the floor is two, and two is then
    the whole answer."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"],
        lib0=["Hill Giant", "Sol Ring", "Grizzly Bears"], interactive=(0, 1),
    )
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    assert not game.confirm_search_library_picks(1, _w1g4s_picks(0)), "two can be found"
    assert game.confirm_search_library_picks(1, _w1g4s_picks(2, 1))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == ["Grizzly Bears", "Sol Ring"]
    assert _w1g4s_names(game.players[0].library) == ["Hill Giant"]


def test_w1g4_guided_passage_over_an_empty_library_asks_nobody(set_pool):
    game, _, _ = _w1g4s_table(set_pool, hand0=["Guided Passage"], interactive=(0, 1))
    assert game.cast_from_hand(0, "Guided Passage").supported
    _w1g4s_resolve_stack(game)

    assert game.pending_choices == []
    assert game.players[0].hand == []
    assert _w1g4s_names(game.players[0].graveyard) == ["Guided Passage"]


def test_w1g4_guided_passage_default_opponent_hands_over_its_least(set_pool):
    """A seat nobody asks still answers in full — one card for every
    description the library can fill — and what it gives its opponent is the
    weakest card of each kind, not the strongest."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"], lib0=_W1G4S_PASSAGE_LIBRARY,
    )
    assert game.cast_from_hand(0, "Guided Passage").supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)

    hand = _w1g4s_names(game.players[0].hand)
    assert len(hand) == 3 and game.pending_choices == []
    kinds = [_w1g4s_card(set_pool, name).type_line for name in hand]
    assert sum("Creature" in line for line in kinds) == 1
    assert sum("Land" in line for line in kinds) == 1
    assert "Black Lotus" not in hand, "the opponent chose, and not for the caster"
    assert len(game.players[0].library) == len(_W1G4S_PASSAGE_LIBRARY) - 3


def test_w1g4_guided_passage_at_three_seats_the_caster_names_the_opponent(set_pool):
    """CR 608.2d: "an opponent" nobody named is the controller's pick, made as
    the spell resolves. The seat named is then the only one asked."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Guided Passage"],
        # The Swamp is drawn on the way in: CR 103.8a skips the first draw
        # step only at a table of two.
        lib0=["Swamp", "Forest", "Hill Giant", "Sol Ring"],
        interactive=(0, 1, 2), seats=3,
    )
    assert _w1g4s_names(game.players[0].hand) == ["Guided Passage", "Swamp"]
    assert game.queue_from_hand(0, "Guided Passage").supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert (asked.kind, asked.player_index, asked.data["seats"]) == ("player_choice", 0, [1, 2])
    assert game.confirm_player_choice(0, 2)
    prompt = game.pending_search_library
    assert prompt["caster_index"] == 2
    assert not game.confirm_search_library_picks(1, _w1g4s_picks(0, 1, 2))
    assert game.confirm_search_library_picks(2, _w1g4s_picks(0, 1, 2))
    _w1g4s_resolve_stack(game)
    assert sorted(_w1g4s_names(game.players[0].hand)) == [
        "Forest", "Hill Giant", "Sol Ring", "Swamp",
    ]
    assert game.players[2].hand == [] and game.players[1].hand == []


def test_w1g4_guided_passage_reads_all_four_sentences_or_refuses():
    """The production's refusals: no shuffle, no line; a description the
    picker cannot test off a card's face refuses in the lowering by name
    rather than becoming a slot any card fills. A list joined by a bare "and"
    is the same list."""
    printed = (
        "Reveal the cards in your library. An opponent chooses from among them "
        "a creature card, a land card, and a noncreature, nonland card. You "
        "put the chosen cards into your hand. Then shuffle."
    )
    assert _w1g4s_compile_line(printed).usable
    assert not _w1g4s_compile_line(printed.replace(" Then shuffle.", "")).parsed
    assert not _w1g4s_compile_line(
        printed.replace("into your hand", "into your graveyard")
    ).parsed
    untestable = _w1g4s_compile_line(
        printed.replace("a creature card,", "a creature card with flying,")
    )
    assert untestable.parsed and not untestable.lowered
    assert "with_keywords" in untestable.lowering_error
    pair = _w1g4s_compile_line(
        "Reveal the cards in your library. An opponent chooses from among them "
        "a creature card and a land card. You put the chosen cards into your "
        "hand. Then shuffle."
    )
    assert pair.usable
    (sequence,) = pair.instructions
    assert sequence.payload["steps"][1].payload["one_of_each"] == [
        {"card_type": "creature"}, {"card_type": "land"},
    ]


# -- Gaea's Balance ----------------------------------------------------------

#: Two basic Forests, a Forest Island, a Mountain Forest, the other four basic
#: types, a land with no basic type and a card that is no land.
_W1G4S_BALANCE_LIBRARY = [
    "Forest", "Tropical Island", "Grizzly Bears", "Battlefield Forge", "Swamp",
    "Taiga", "Island", "Plains", "Mountain", "Forest",
]
_W1G4S_SIX_LANDS = ["Forest", "Forest", "Forest", "Forest", "Island", "Island"]


def test_w1g4_gaeas_balance_cannot_be_cast_on_four_lands(set_pool):
    """"As an additional cost to cast this spell, sacrifice five lands."
    CR 601.2h: with four the cost cannot be paid, so the spell is not cast —
    nothing is sacrificed, the card stays in hand, and an AI seat does not
    propose it."""
    from engine.ai_policy import choose_cast_action

    game, mine, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:4] + ["Grizzly Bears"],
        hand0=["Gaea's Balance"], lib0=_W1G4S_BALANCE_LIBRARY,
    )
    refused = game.cast_from_hand(0, "Gaea's Balance")

    assert not refused.supported and "601.2h" in refused.details
    assert all(game.is_on_battlefield(permanent) for permanent in mine)
    assert _w1g4s_names(game.players[0].hand) == ["Gaea's Balance"]
    assert choose_cast_action(game, 0) is None


def test_w1g4_gaeas_balance_sacrifices_the_five_lands_its_caster_named(set_pool):
    """The payer chooses which five (CR 601.2b): of six lands and a creature,
    the five named are gone as the spell goes on the stack and the sixth land
    and the creature are still there. The picker is a sacrifice picker over the
    caster's own lands, for five."""
    balance = _w1g4s_card(set_pool, "Gaea's Balance")
    game, mine, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS + ["Grizzly Bears"], theirs=["Mountain"],
        hand0=["Gaea's Balance"], lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    spec = game.cast_target_spec(0, balance)
    assert (spec["kind"], spec["sacrifice_cost"], spec["count"], spec["own_only"]) == (
        "land", True, 5, True,
    )
    assert len(spec["valid_targets"]) == 6, "the opponent's Mountain is not offered"

    kept = mine[0]
    result = game.queue_from_hand(
        0, "Gaea's Balance",
        cost_permanent_ids=[land.permanent_id for land in mine[1:6]],
    )
    assert result.supported, result.details
    assert game.is_on_battlefield(kept) and game.is_on_battlefield(mine[6])
    assert not any(game.is_on_battlefield(land) for land in mine[1:6])
    assert _w1g4s_names(game.players[0].graveyard) == [
        "Forest", "Forest", "Forest", "Island", "Island",
    ]


def test_w1g4_gaeas_balance_finds_one_land_for_each_basic_land_type(set_pool):
    """"Search your library for a land card of each basic land type, put those
    cards onto the battlefield, then shuffle."

    Five descriptions, one find apiece. A Tropical Island is a Forest card and
    an Island card (the ruling: "You can find a nonbasic land card this way as
    long as it has a basic land type"), so it answers one of the two — and
    whether an answer is legal is a question about the whole of it: the dual, a
    basic Forest and a Taiga are three finds only with the dual read as the
    Island and the Taiga as the Mountain.
    """
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert prompt["count"] == 5 and prompt["up_to"]
    assert prompt["destinations"] == ["battlefield"] * 5
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(0, 9)), "two Forests"
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(2)), "not a land"
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(3)), (
        "Battlefield Forge has no basic land type"
    )
    assert not game.confirm_search_library_picks(0, _w1g4s_picks(1, 0, 5, 8)), (
        "four cards over Forest, Island and Mountain"
    )
    assert game.confirm_search_library_picks(0, _w1g4s_picks(1, 0, 5, 4, 7))
    _w1g4s_resolve_stack(game)
    game._settle()

    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Forest", "Plains", "Swamp", "Taiga", "Tropical Island",
    ]
    assert not any(perm.tapped for perm in game.controlled_by(0))
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted([
        "Grizzly Bears", "Battlefield Forge", "Island", "Mountain", "Forest",
    ])
    assert game.pending_choices == []


def test_w1g4_gaeas_balance_may_fail_to_find_any_or_all(set_pool):
    """The ruling: "You can fail to find a land card for any or all basic land
    types, even if a land card with that basic land type is in your library."
    One land is an answer, and so is none — the library is shuffled either way
    and the five lands are gone either way."""
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(0, _w1g4s_picks(8))
    _w1g4s_resolve_stack(game)
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Mountain"]

    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=_W1G4S_BALANCE_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Gaea's Balance").supported
    game.resolve_top_of_stack()
    assert game.decline_search_library(0)
    _w1g4s_resolve_stack(game)
    assert list(game.controlled_by(0)) == []
    assert len(game.players[0].library) == len(_W1G4S_BALANCE_LIBRARY)
    assert "P0 searched and found nothing more" in game.log


def test_w1g4_gaeas_balance_default_seat_takes_as_many_as_can_be_assigned(set_pool):
    """A seat nobody asks finds a land for every type it can — and gets the
    assignment right where a first-fit would not: with only a Tropical Island
    and a basic Island to find, both come out (the dual as the Forest)."""
    game, _, _ = _w1g4s_table(
        set_pool, mine=_W1G4S_SIX_LANDS[:5], hand0=["Gaea's Balance"],
        lib0=["Tropical Island", "Island", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Gaea's Balance").supported
    game.auto_resolve_pending_choices()
    _w1g4s_resolve_stack(game)
    game._settle()

    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Island", "Tropical Island",
    ]
    assert _w1g4s_names(game.players[0].library) == ["Grizzly Bears"]
    assert game.pending_choices == []


def test_w1g4_gaeas_balance_search_reads_its_plural_tail_or_refuses():
    """The production's refusals: "of each basic land type" is several cards,
    so "put it" is a different sentence, and the shuffle is required."""
    printed = (
        "Search your library for a land card of each basic land type, put "
        "those cards onto the battlefield, then shuffle."
    )
    compiled = _w1g4s_compile_line(printed)
    assert compiled.usable
    (search,) = compiled.instructions
    assert [
        slot["restrictions"]["subtypes"]
        for slot in search.payload["restrictions"]["one_of_each"]
    ] == [["plains"], ["island"], ["swamp"], ["mountain"], ["forest"]]
    assert not _w1g4s_compile_line(printed.replace("those cards", "it")).parsed
    assert not _w1g4s_compile_line(printed.replace(", then shuffle", "")).parsed


# -- Squee's Revenge ---------------------------------------------------------


def _w1g4s_revenge(set_pool, monkeypatch, flips, number, library=12):
    """Squee's Revenge cast by an asked seat that names *number*, with the
    coin scripted to come up *flips* in order (True is a win)."""
    script = iter(flips)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda: next(script)
    )
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * library,
        interactive=(0,),
    )
    assert game.queue_from_hand(0, "Squee's Revenge").supported
    game.resolve_top_of_stack()
    assert game.confirm_number_choice(0, number)
    _w1g4s_resolve_stack(game)
    return game, list(script)  # W1G4 sorceries: the game and the flips unused


def test_w1g4_squees_revenge_draws_two_cards_for_each_flip_of_a_clean_run(
    set_pool, monkeypatch,
):
    """"Choose a number. Flip a coin that many times or until you lose a flip,
    whichever comes first. If you win all the flips, draw two cards for each
    flip." Three named, three won: six cards."""
    game, unused = _w1g4s_revenge(set_pool, monkeypatch, [True] * 5, 3)

    assert len(game.players[0].hand) == 6
    assert len(game.players[0].library) == 6
    assert len(unused) == 2, "exactly three coins were flipped"
    assert game.log.count("Squee's Revenge: won the coin flip") == 3
    assert "Squee's Revenge: 3 of 3 flip(s) made, every one won" in game.log


def test_w1g4_squees_revenge_stops_at_the_first_loss_and_draws_nothing(
    set_pool, monkeypatch,
):
    """"…or until you lose a flip, whichever comes first": the third and
    fourth coins are never flipped, and a run with a loss in it pays nothing —
    not even for the two flips that were won."""
    game, unused = _w1g4s_revenge(
        set_pool, monkeypatch, [True, True, False, True, True], 5,
    )

    assert game.players[0].hand == []
    assert len(game.players[0].library) == 12
    assert len(unused) == 2
    assert "Squee's Revenge: 3 of 5 flip(s) made, the last one lost" in game.log
    assert _w1g4s_names(game.players[0].graveyard) == ["Squee's Revenge"]


def test_w1g4_squees_revenge_at_zero_flips_nothing_and_draws_nothing(
    set_pool, monkeypatch,
):
    """Zero is a number (CR 107.1). No coin is flipped, every flip of none was
    won, and two cards for each of no flips is no cards."""
    game, unused = _w1g4s_revenge(set_pool, monkeypatch, [True, True], 0)

    assert game.players[0].hand == []
    assert len(unused) == 2
    assert "Squee's Revenge: 0 of 0 flip(s) made, every one won" in game.log


def test_w1g4_squees_revenge_asks_for_a_number_with_no_ceiling(set_pool):
    """The prompt is the open number prompt: zero or more, no upper bound, and
    a negative answer is refused with the prompt still owed. The flips wait for
    the answer — nothing is flipped while the number is unknown."""
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * 4, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Squee's Revenge").supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "number_choice" and asked.player_index == 0
    assert (asked.data["minimum"], asked.data["maximum"]) == (0, None)
    assert not any("coin flip" in line for line in game.log)
    assert not game.confirm_number_choice(0, -1)
    assert game.pending_choices == [asked]
    assert game.confirm_number_choice(0, 1000), "any number at all"
    _w1g4s_resolve_stack(game)
    assert game.pending_choices == []
    assert any("flip(s) made" in line for line in game.log)


def test_w1g4_squees_revenge_default_seat_flips_the_seeded_coin_twice(set_pool):
    """A seat nobody asks names two (the expectation is the same at one and
    two, and falls from three), and the flips come off the seeded RNG — the
    same seed plays the same game."""
    import random

    outcomes = []
    for _ in range(2):
        random.seed(4)
        game, _, _ = _w1g4s_table(
            set_pool, hand0=["Squee's Revenge"], lib0=["Forest"] * 12,
        )
        assert game.cast_from_hand(0, "Squee's Revenge").supported
        game.auto_resolve_pending_choices()
        _w1g4s_resolve_stack(game)
        assert "Squee's Revenge: chose 2" in game.log
        outcomes.append(
            ([line for line in game.log if "coin flip" in line],
             len(game.players[0].hand))
        )
    assert outcomes[0] == outcomes[1]
    flips, drawn = outcomes[0]
    assert drawn == (4 if flips == ["Squee's Revenge: won the coin flip"] * 2 else 0)


def test_w1g4_squees_run_of_flips_needs_its_number_and_its_reward():
    """The production's refusals. "That many" with no number chosen in front of
    it bounds nothing and refuses in the lowering; the run with no sentence
    saying what a clean one pays is not this card; and a plain "Flip a coin."
    is still one flip."""
    run = (
        "Flip a coin that many times or until you lose a flip, whichever comes "
        "first. If you win all the flips, draw two cards for each flip."
    )
    assert _w1g4s_compile_line("Choose a number. " + run).usable
    unbound = _w1g4s_compile_line(run)
    assert unbound.parsed and not unbound.lowered
    assert "no number chosen" in unbound.lowering_error
    assert not _w1g4s_compile_line(
        "Choose a number. Flip a coin that many times or until you lose a flip, "
        "whichever comes first."
    ).parsed
    (flip,) = _w1g4s_compile_line("Flip a coin.").instructions
    assert flip.kind == "flip_coin"


# -- Lay of the Land ---------------------------------------------------------


def test_w1g4_lay_of_the_land_finds_a_basic_land_and_shows_it(set_pool):
    """"Search your library for a basic land card, reveal it, put it into your
    hand, then shuffle." A nonbasic land and a creature are refused; the find
    is revealed to the table and the rest of the library is still all there."""
    library = ["Grizzly Bears", "Tropical Island", "Forest", "Sol Ring", "Island"]
    game, _, _ = _w1g4s_table(
        set_pool, hand0=["Lay of the Land"], lib0=library, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Lay of the Land").supported
    game.resolve_top_of_stack()

    prompt = game.pending_search_library
    assert (prompt["count"], prompt["card_type"]) == (1, "land")
    assert not game.confirm_search_library(0, 0), "a creature"
    assert not game.confirm_search_library(0, 1), "a land, and not basic"
    assert game.confirm_search_library(0, 2)
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Forest"]
    assert game.reveal_events[-1]["cards"] == ["Forest"]
    assert sorted(_w1g4s_names(game.players[0].library)) == sorted(
        ["Grizzly Bears", "Tropical Island", "Sol Ring", "Island"]
    )
    assert _w1g4s_names(game.players[0].graveyard) == ["Lay of the Land"]


# -- Temporal Spring ---------------------------------------------------------


def test_w1g4_temporal_spring_puts_the_named_permanent_on_its_owners_library(set_pool):
    """"Put target permanent on top of its owner's library." Any permanent is
    a target, the one named is the one moved, and it is the next card that
    library gives up."""
    spring = _w1g4s_card(set_pool, "Temporal Spring")
    game, mine, theirs = _w1g4s_table(
        set_pool, mine=["Forest"], theirs=["Serra Angel", "Sol Ring"],
        hand0=["Temporal Spring"], lib1=["Island", "Island"],
    )
    spec = game.cast_target_spec(0, spring)
    assert spec["kind"] == "permanent" and len(spec["valid_targets"]) == 3

    ring = theirs[1]
    cast = game.cast_from_hand(0, "Temporal Spring", target_permanent_ids=[ring.permanent_id])
    assert cast.supported, cast.details
    _w1g4s_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(ring)
    assert game.is_on_battlefield(theirs[0]) and game.is_on_battlefield(mine[0])
    assert _w1g4s_names(game.players[1].library) == ["Sol Ring", "Island", "Island"]
    assert game.players[1].graveyard == []


def test_w1g4_temporal_spring_sends_a_stolen_permanent_to_its_owner(set_pool):
    """"Its **owner's** library" (CR 400.3): a creature the caster had taken
    goes on top of the library it came out of, not the caster's."""
    from engine.control import change_control

    game, _, theirs = _w1g4s_table(
        set_pool, theirs=["Serra Angel"], hand0=["Temporal Spring"],
        lib0=["Forest"], lib1=["Island"],
    )
    angel = theirs[0]
    change_control(angel, 0, source="test")
    game._sync_control()
    assert game.controller_index_of(angel) == 0

    assert game.cast_from_hand(
        0, "Temporal Spring", target_permanent_ids=[angel.permanent_id]
    ).supported
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[1].library) == ["Serra Angel", "Island"]
    assert _w1g4s_names(game.players[0].library) == ["Forest"]


# -- Urborg Uprising ---------------------------------------------------------

_W1G4S_UPRISING_GRAVEYARD = ["Grizzly Bears", "Sol Ring", "Hill Giant", "Serra Angel"]


def _w1g4s_uprising(set_pool, **kwargs):
    return _w1g4s_table(
        set_pool, hand0=["Urborg Uprising"], gy0=_W1G4S_UPRISING_GRAVEYARD,
        gy1=["Air Elemental"], lib0=["Forest", "Island"], **kwargs,
    )  # W1G4 sorceries: the Uprising's table


def test_w1g4_urborg_uprising_returns_two_creature_cards_and_draws(set_pool):
    """"Return up to two target creature cards from your graveyard to your
    hand. Draw a card.\""""
    uprising = _w1g4s_card(set_pool, "Urborg Uprising")
    game, _, _ = _w1g4s_uprising(set_pool)
    spec = game.cast_target_spec(0, uprising)
    assert (spec["max_targets"], spec["own_graveyard_only"]) == (2, True)
    assert [target["name"] for target in spec["valid_targets"]] == [
        "Grizzly Bears", "Hill Giant", "Serra Angel",
    ]

    cast = game.cast_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[0, 3],
    )
    assert cast.supported, cast.details
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Grizzly Bears", "Serra Angel", "Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == ["Sol Ring", "Hill Giant", "Urborg Uprising"]
    assert _w1g4s_names(game.players[0].library) == ["Island"]


def test_w1g4_urborg_uprising_refuses_what_its_target_phrase_does_not_name(set_pool):
    """Held at the announcement: a card that is no creature, the same card
    twice, a third target, and a card in somebody else's graveyard are each
    refused with the spell still in hand and nothing moved."""
    game, _, _ = _w1g4s_uprising(set_pool)
    for seat, indices in ((0, [1]), (0, [0, 0]), (0, [0, 2, 3]), (1, [0])):
        refused = game.cast_from_hand(
            0, "Urborg Uprising", target_player_index=seat,
            target_permanent_index=indices,
        )
        assert not refused.supported, (seat, indices)
    assert _w1g4s_names(game.players[0].hand) == ["Urborg Uprising"]
    assert _w1g4s_names(game.players[0].graveyard) == _W1G4S_UPRISING_GRAVEYARD
    assert _w1g4s_names(game.players[1].graveyard) == ["Air Elemental"]


def test_w1g4_urborg_uprising_with_no_target_still_draws(set_pool):
    """"Up to two" may be none (CR 601.2c), and a spell that named no target
    is not one whose targets are all illegal: the draw happens."""
    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.cast_from_hand(0, "Urborg Uprising").supported
    _w1g4s_resolve_stack(game)

    assert _w1g4s_names(game.players[0].hand) == ["Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == (
        _W1G4S_UPRISING_GRAVEYARD + ["Urborg Uprising"]
    )


def test_w1g4_urborg_uprising_follows_its_targets_and_fizzles_without_them(set_pool):
    """CR 608.2b at both sizes. With one of two targets exiled in response the
    other still comes back — the card it named, though the pile has shifted
    under it — and the draw happens. With its only target gone the spell is
    removed from the stack and draws nothing."""
    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.queue_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[0, 3],
    ).supported
    game.players[0].exile.append(game.players[0].graveyard.pop(0))
    _w1g4s_resolve_stack(game)
    assert _w1g4s_names(game.players[0].hand) == ["Serra Angel", "Forest"]
    assert _w1g4s_names(game.players[0].graveyard) == ["Sol Ring", "Hill Giant", "Urborg Uprising"]

    game, _, _ = _w1g4s_uprising(set_pool)
    assert game.queue_from_hand(
        0, "Urborg Uprising", target_player_index=0, target_permanent_index=[2],
    ).supported
    game.players[0].exile.append(game.players[0].graveyard.pop(2))
    _w1g4s_resolve_stack(game)
    assert game.players[0].hand == []
    assert _w1g4s_names(game.players[0].library) == ["Forest", "Island"]
    assert any("608.2b" in line for line in game.log)


# -- Whole games -------------------------------------------------------------


@_w1g4s_pytest.mark.slow
def test_w1g4_the_ai_plays_this_groups_spells_through_whole_games():
    """Six simulated games with this group's cards pinned into both decks,
    because a card can compile and do nothing in a turn structure. Each of the
    four sorceries is cast and resolves; the opponent's pick, both looks, the
    run of flips and the five-land search all happen inside the step that owes
    them (`steps_left_owing`); and nothing any of them does is an issue or a
    refused cast.

    The floors are one apiece on purpose: the seed's trajectory moves whenever
    another card in the set changes, and this asks that each was *seen*.
    (The pool is a measured set, so other cards' unsupported casts are in the
    report; only these cards' lines are read.)
    """
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = [
        "Guided Passage", "Squee's Revenge", "Tahngarth's Glare", "Wild Research",
        "Dragon Arch", "Gaea's Balance", "Legacy Weapon",
    ]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    log = report.log_lines

    assert report.games_completed == 6
    assert report.steps_left_owing == {}, dict(report.steps_left_owing)
    for name in names:
        assert not [i.message for i in report.issues if name in i.message], name
        assert not [why for why in report.refused_casts if name in why], name
    w1g4_cast = {
        name for name in names
        if any(f"cast {name} -> resolved" in line for line in log)
    }
    assert len(w1g4_cast) >= 5, sorted(w1g4_cast)
    w1g4_seen = {
        "the run of flips": any("flip(s) made" in line for line in log),
        "the revealed library": any("revealed their library" in line for line in log),
        "the five-land cost": any("to cast Gaea's Balance" in line for line in log),
        "the two looks": sum(
            "is looking at the top 3 cards of" in line for line in log
        ) >= 2,
        "the tutor's random discard": any(
            "discarded 1 cards at random" in line for line in log
        ),
    }
    assert sum(w1g4_seen.values()) >= 4, w1g4_seen

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
