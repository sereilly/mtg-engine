"""The sorted reveal whose rest goes under the library, and the order it asks for.

"Reveal the top four cards of your library. Put all <filter> cards revealed
this way into your hand and the rest on the bottom of your library in any
order." Apocalypse prints it on seven cards (Goblin Ringleader and five
siblings with the subtype changed, and Brass Herald with "of the chosen
type"); their per-card tests are in ``tests/sets/test_apc_*.py``. What is here
is what is not about one card:

* **the production reads the sentence, not a name** — an invented card
  printing it plays it, and a near miss refuses in the parse rather than
  lowering onto the nearest thing the handler performs;
* **the order of the rest is the owner's** (CR 401.4), asked through
  ``Game.offer_library_bottom_order`` — the ``reorder_library`` prompt pointed
  at the library's other end — of an interactive seat only, with "as they lay"
  for everybody else.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

_HEAD = "Reveal the top four cards of your library. Put all Goblin cards revealed this way into your hand"


def _typed(name: str, type_line: str):
    return _mk_card(name=name, mana_cost="", type_line=type_line)


def _library_game(names, *, interactive=(0,)) -> Game:
    game = Game(players=[
        PlayerState(name="P0", library=[_typed(n, "Artifact") for n in names]),
        PlayerState(name="P1"),
    ])
    game.interactive_seats = set(interactive)
    return game


# ---------------------------------------------------------------------------
# The production
# ---------------------------------------------------------------------------


def test_the_sentence_lowers_to_the_sorted_reveal_with_a_bottom_rest():
    compiled = compile_line(f"{_HEAD} and the rest on the bottom of your library in any order.")

    assert compiled.usable, compiled
    (instruction,) = compiled.instructions
    assert instruction.kind == "reveal_top_sorting_by_filter"
    assert instruction.payload == {
        "amount": 4,
        "filter": {"type_filter": "creature", "subtype_filter": "goblin"},
        "match_zone": "hand",
        "rest_zone": "library_bottom",
    }


@pytest.mark.parametrize("tail", [
    # No order stated at all: CR 401.4 would still give it to the owner, but
    # the sentence is not the one the handler was written against.
    "and the rest on the bottom of your library.",
    # A *stated* order is a different instruction — the cards go down shuffled
    # and nobody chooses — and one this handler does not perform.
    "and the rest on the bottom of your library in a random order.",
    # The other end of the library is a different card: those are the next
    # draws.
    "and the rest on top of your library in any order.",
    # Somebody else's library.
    "and the rest on the bottom of their library in any order.",
    "and the rest on the bottom of target player's library in any order.",
])
def test_a_near_miss_of_the_rest_refuses_in_the_parse(tail: str):
    compiled = compile_line(f"{_HEAD} {tail}")

    assert not compiled.usable
    assert compiled.parse_error is not None, (
        "the sentence parsed — a rest the handler cannot place must be refused "
        "by the production, not carried to a lowering that drops it"
    )


def test_a_filter_no_card_in_a_library_can_answer_is_refused():
    """A pile off a library is cards (CR 400.1). "Tapped" is a question only a
    permanent answers, and dropping it would put every creature card in the
    hand — so the line is not usable rather than read without the word."""
    compiled = compile_line(
        "Reveal the top four cards of your library. Put all tapped creature "
        "cards revealed this way into your hand and the rest on the bottom of "
        "your library in any order."
    )
    assert not compiled.usable


def test_an_invented_card_printing_the_sentence_plays_it():
    """Support by the words: a sorcery nobody has printed, with a card type
    for the filter and three for the count, sorts its pile the same way."""
    survey = _mk_card(
        name="Scrap Survey", mana_cost="{1}{U}", type_line="Sorcery",
        oracle_text=(
            "Reveal the top three cards of your library. Put all artifact "
            "cards revealed this way into your hand and the rest on the "
            "bottom of your library in any order."
        ),
    )
    assert compile_card_oracle(survey).supported
    library = [
        _typed("A Rock", "Artifact"), _typed("A Land", "Land"),
        _typed("A Golem", "Artifact Creature — Golem"), _typed("Fourth", "Artifact"),
    ]
    game = Game(players=[
        PlayerState(name="P0", hand=[survey], library=library), PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    assert game.cast_from_hand(0, "Scrap Survey").supported
    resolve_stack(game)

    me = game.players[0]
    assert [c.name for c in me.hand] == ["A Rock", "A Golem"], game.log
    assert [c.name for c in me.library] == ["Fourth", "A Land"]
    assert "P0 revealed A Rock, A Land, A Golem" in game.log
    assert game.reveal_events[-1]["cards"] == ["A Rock", "A Land", "A Golem"]


def test_of_the_chosen_type_with_no_source_that_chose_keeps_nothing():
    """"…all creature cards **of the chosen type**…" is answered off the
    ability's source (CR 614.1c). A sorcery has no permanent that chose, so
    the phrase names no type — and the whole pile goes to the rest, never
    "every creature card" to the hand. (Nobody prints this; it is the
    direction an unanswerable narrowing has to fail in.)"""
    orphan = _mk_card(
        name="Orphaned Muster", mana_cost="{1}{G}", type_line="Sorcery",
        oracle_text=(
            "Reveal the top four cards of your library. Put all creature cards "
            "of the chosen type revealed this way into your hand and the rest "
            "on the bottom of your library in any order."
        ),
    )
    library = [_typed("An Elf", "Creature — Elf"), _typed("A Goblin", "Creature — Goblin")]
    game = Game(players=[
        PlayerState(name="P0", hand=[orphan], library=library), PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    assert game.cast_from_hand(0, "Orphaned Muster").supported
    resolve_stack(game)

    me = game.players[0]
    assert me.hand == []
    assert [c.name for c in me.library] == ["An Elf", "A Goblin"]
    assert "P0 put no card into their hand and 2 card(s) on the bottom of their library" in game.log


# ---------------------------------------------------------------------------
# CR 401.4 — the order of what went to the bottom
# ---------------------------------------------------------------------------


def test_an_interactive_owner_is_asked_about_exactly_the_cards_that_went_down():
    game = _library_game(["A", "B", "C", "D", "E"])

    assert game.offer_library_bottom_order(game.players[0], 3) is True

    (choice,) = game.pending_choices
    assert choice.kind == "reorder_library" and choice.player_index == 0
    assert choice.data["position"] == "bottom" and choice.data["top_count"] == 3
    assert [c.name for c in game.reorder_library_pile(choice)] == ["C", "D", "E"]

    assert game.confirm_reorder_library(0, [0, 1]) is False
    assert game.confirm_reorder_library(0, [0, 1, 1]) is False
    assert game.confirm_reorder_library(1, [2, 1, 0]) is False
    assert game.confirm_reorder_library(0, [2, 0, 1]) is True

    assert [c.name for c in game.players[0].library] == ["A", "B", "E", "C", "D"]
    assert game.pending_choices == []
    assert game.log[-1] == "P0 put 3 cards on the bottom of their library in an order they chose"


def test_the_order_chosen_is_the_order_the_cards_are_later_drawn_in():
    """Why it is asked at all: the bottom of a library is drawn from once the
    deck runs down to it, in exactly the order the owner laid."""
    game = _library_game(["Top", "X", "Y", "Z"])
    game.offer_library_bottom_order(game.players[0], 3)
    assert game.confirm_reorder_library(0, [2, 1, 0])

    me = game.players[0]
    drawn = [me.library.pop(0).name for _ in range(4)]
    assert drawn == ["Top", "Z", "Y", "X"]


@pytest.mark.parametrize(("count", "interactive"), [
    (3, ()),        # nobody to ask: as they lay
    (1, (0,)),      # one card has one order
    (0, (0,)),
])
def test_nothing_is_queued_when_there_is_nobody_or_nothing_to_ask(count, interactive):
    game = _library_game(["A", "B", "C", "D"], interactive=interactive)

    assert game.offer_library_bottom_order(game.players[0], count) is False

    assert game.pending_choices == []
    assert [c.name for c in game.players[0].library] == ["A", "B", "C", "D"]


def test_the_default_answer_is_the_order_the_cards_went_down_in():
    """A prompt that was armed and is then taken by default (the seat left, an
    auto-resolver drained it) leaves the pile as it lay — the same order a
    seat that was never asked gets, and no shuffle of the next draws."""
    game = _library_game(["A", "B", "C", "D"])
    game.offer_library_bottom_order(game.players[0], 3)

    game.auto_resolve_pending_choices()

    assert game.pending_choices == []
    assert [c.name for c in game.players[0].library] == ["A", "B", "C", "D"]


def test_a_count_longer_than_the_library_is_the_whole_library():
    game = _library_game(["A", "B"])

    assert game.offer_library_bottom_order(game.players[0], 5) is True
    (choice,) = game.pending_choices
    assert [c.name for c in game.reorder_library_pile(choice)] == ["A", "B"]
    assert game.confirm_reorder_library(0, [1, 0])
    assert [c.name for c in game.players[0].library] == ["B", "A"]


def test_another_seat_may_be_the_one_that_arranges():
    """Where a card gives the order to the player doing the looking rather
    than the library's owner, that seat is asked and the owner's library is
    what moves."""
    game = _library_game(["A", "B", "C"], interactive=(1,))

    assert game.offer_library_bottom_order(game.players[0], 2, chooser_index=1) is True
    (choice,) = game.pending_choices
    assert choice.player_index == 1 and choice.data["target_index"] == 0
    assert game.confirm_reorder_library(0, [1, 0]) is False
    assert game.confirm_reorder_library(1, [1, 0]) is True
    assert [c.name for c in game.players[0].library] == ["A", "C", "B"]


def test_a_top_of_library_reorder_reads_the_top_as_it_always_has():
    """The same prompt with no position is the top N — every look-and-put-back
    in the pool — and its reader, its answer and its log line are unchanged."""
    game = _library_game(["A", "B", "C", "D"])
    game.arm_pending_choice(
        "reorder_library", 0, target_index=0, top_count=3, may_shuffle=False,
    )
    (choice,) = game.pending_choices
    assert [c.name for c in game.reorder_library_pile(choice)] == ["A", "B", "C"]

    assert game.confirm_reorder_library(0, [2, 1, 0])
    assert [c.name for c in game.players[0].library] == ["C", "B", "A", "D"]
    assert game.log[-1] == "Top 3 cards of P0's library reordered"
