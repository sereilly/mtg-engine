"""Urza's Destiny wave 1, group 1: what a **reveal** out of a hand is.

Three rules, none of them about a printing — which is the line SET_PLAYBOOK.md
draws between `tests/sets/` and here:

* **CR 701.20a** — to reveal a card is to show it *to all players*. The
  structured record beside the log is what a client reads to show a revealed
  face, so a reveal nothing recorded is a reveal the rest of the table has to
  take on trust.
* **CR 701.20b** — revealing a card does not cause it to leave the zone it is
  in. Twelve Urza's Destiny cards spend a count of revealed cards, and every
  one of them would be a different card if the reveal were a discard.
* **CR 608.2** — the resolution does as much as it can and finishes: an offer
  of "any number" answered with none is a resolution, not a refusal, and the
  record it leaves is a zero rather than an absence.

The noun is an invented card, because the mechanism is what is under test: any
card printing the same sentence gets these for free.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition
from engine.oracle_types import REVEALED_HAND_CARDS, REVEALED_THIS_WAY
from tests.helpers import resolve_stack


def _g1r_card(name: str, type_line: str, text: str) -> CardDefinition:
    body = {"name": name, "type_line": type_line}
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=body,
    )


def _g1r_blue(name: str) -> CardDefinition:
    """A blue card with no text at all, so the only thing about it that can
    matter to a "reveal any number of blue cards" is its colour."""
    body = {"name": name, "type_line": "Instant"}
    return CardDefinition(
        name=name, mana_cost="{U}", cmc=1.0, type_line="Instant",
        oracle_text="", colors=("U",), color_identity=("U",), keywords=(),
        produced_mana=(), raw=body,
    )


def _g1r_showing_hand(hand, *, interactive=False):
    """Alice about to cast a spell that reveals any number of blue cards and
    then gains one life for each."""
    spell = _g1r_card(
        "Blue Census", "Instant",
        "Reveal any number of blue cards in your hand. "
        "You gain 1 life for each card revealed this way.",
    )
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    alice.hand = [spell] + list(hand)
    alice.life = 20
    return game, alice


@pytest.mark.cr("701.20a", "701.20b")
def test_a_reveal_shows_the_cards_to_every_player_and_moves_none():
    """CR 701.20a's "show that card to all players", and CR 701.20b's "revealing
    a card doesn't cause it to leave the zone it's in".

    Both halves in one assertion pair, because a reveal that failed either way
    looks identical from the effect that spends it: a hand of three that gains
    three life proves the count, and says nothing about whether the table saw
    the cards or whether they are still in the hand.
    """
    hand = [_g1r_blue(f"Blue {n}") for n in ("One", "Two", "Three")]
    game, alice = _g1r_showing_hand(hand)

    game.cast_from_hand(0, "Blue Census")
    resolve_stack(game)

    assert [event["cards"] for event in game.reveal_events] == [
        ["Blue One", "Blue Two", "Blue Three"]
    ], "one event per reveal, naming what was shown (CR 701.20a)"
    assert game.reveal_events[-1]["seat"] == 0
    assert [card.name for card in alice.hand] == [
        "Blue One", "Blue Two", "Blue Three"
    ], "the cards are still in the hand (CR 701.20b)"
    assert [card.name for card in alice.graveyard] == ["Blue Census"], (
        "and nowhere else: only the spell itself moved"
    )
    assert alice.life == 23


@pytest.mark.cr("701.20a")
def test_a_reveal_that_showed_nothing_is_not_an_event():
    """Nought cards shown is nought to show: CR 701.20a is about *cards*, and
    an empty reveal publishes nothing.

    The pair with the test above is what separates "the reveal happened and
    showed none" from "the reveal did not happen" — indistinguishable from the
    life total, which is 20 either way.
    """
    game, alice = _g1r_showing_hand([_g1r_card("Red Thing", "Instant", "")])

    game.cast_from_hand(0, "Blue Census")
    resolve_stack(game)

    assert game.reveal_events == []
    assert alice.life == 20


@pytest.mark.cr("608.2")
def test_revealing_none_of_an_offer_records_a_zero_rather_than_nothing():
    """CR 608.2: the resolution follows its instructions as far as it can and
    then finishes.

    "Any number of" answered with none is an answer, so the step *ran* — and
    the record it leaves is the number nought rather than an absent key. The
    difference is load-bearing rather than pedantic: an absent key is a
    back-reference with no producer, which this grammar refuses at lowering, so
    a step that wrote nothing would make the sentence behind it unreadable
    instead of zero.
    """
    hand = [_g1r_blue("Blue One"), _g1r_blue("Blue Two")]
    game, alice = _g1r_showing_hand(hand, interactive=True)

    game.cast_from_hand(0, "Blue Census")
    assert game.confirm_choose_cards_in_hand(0, [])
    resolve_stack(game)

    item = next(
        entry for entry in game.log if "Blue Census" in entry and "resolved" in entry
    )
    assert item, "the spell resolved rather than waiting on the offer"
    assert alice.life == 20
    assert [card.name for card in alice.hand] == ["Blue One", "Blue Two"]


@pytest.mark.cr("701.20a", "608.2")
def test_the_reveal_records_both_the_count_and_the_cards_it_showed():
    """The two records one reveal writes, read off the resolution itself.

    A count is what every sentence in the pool spends ("for each card revealed
    this way"), and the cards are what a *narrowed* one would have to ask
    ("for each blue instant card revealed this way"). Asserted here rather than
    inferred from a life total, because a handler that wrote only one of them
    would still gain the right life today and refuse the narrowed sentence the
    day a card printed it.
    """
    seen: dict[str, object] = {}
    hand = [_g1r_blue("Blue One"), _g1r_blue("Blue Two")]
    game, alice = _g1r_showing_hand(hand)

    from engine.handlers.registry import EFFECT_HANDLERS

    original = EFFECT_HANDLERS["target_gains_life"]

    def _spy(game_, instruction, context):
        seen.update(context.results)
        return original(game_, instruction, context)

    EFFECT_HANDLERS["target_gains_life"] = _spy
    try:
        game.cast_from_hand(0, "Blue Census")
        resolve_stack(game)
    finally:
        EFFECT_HANDLERS["target_gains_life"] = original

    assert seen[REVEALED_THIS_WAY] == 2
    assert [card.name for card in seen[REVEALED_HAND_CARDS]] == [
        "Blue One", "Blue Two"
    ]


@pytest.mark.cr("608.2")
def test_a_revealed_this_way_count_needs_a_reveal_in_the_same_resolution():
    """CR 608.2 is what scopes "this way": a resolution follows its own
    instructions in the order written, so the record a later sentence reads is
    one an *earlier step of that same resolution* wrote.

    A sentence printed with no reveal in front of it therefore names nothing.
    The engine refuses it rather than reading a zero, and the direction matters:
    a zero compiles, reports supported and does nothing at all — a Metalworker
    that always adds no mana, a counter offer of {0} every board covers. Each
    of the four sentences this group spends the record on is asked separately,
    because a gate on three of them is a gate.
    """
    from engine.oracle import compile_card_oracle

    orphans = (
        "You gain 2 life for each card revealed this way.",
        "Add {C}{C} for each card revealed this way.",
        "Counter target spell unless its controller pays {1} "
        "for each card revealed this way.",
        "Target creature gets +X/+X until end of turn, where X is the number "
        "of cards revealed this way.",
    )
    for text in orphans:
        program = compile_card_oracle(_g1r_card("Orphan Clause", "Instant", text))
        assert not program.supported, text
