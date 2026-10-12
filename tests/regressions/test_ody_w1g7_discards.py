"""ODY W1G7: readings of a discard that no single card owns.

Three things wave 1's hands-and-libraries group found while building the
Rites, each a sentence nothing in the pool printed and the grammar read
wrongly or too narrowly all the same:

* **"up to"** was dropped. "Target player discards up to two cards" lowered as
  exactly two, and so did four more spellings; only the two shapes that never
  reached ``_lower_discard`` (Kinetic Augur's fused draw, Mind Bomb's
  each-player offer) carried the ceiling. The two prompts that can offer one
  carry it now and every other reading refuses.
* **"that many" after a draw sized by the hand it fills** was counted twice.
  The discard was handed the draw's own count *spec*, which is right for a
  count of Islands and wrong for a count of cards in hand: three in hand drew
  three and then discarded six.
* **a mill sized by a count** read only the cost-sacrifice record.

Pool-wide and about no one card, which is why they are here and not in a
per-set file.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.oracle_types import X_FROM_COUNT
from tests.helpers import _mk_card, resolve_stack


def _program(text: str, name: str = "Probe Spell"):
    return compile_card_oracle(_mk_card(name, "{1}", "Sorcery", text))


def _game(*, hand0=(), hand1=(), lib0=(), lib1=(), interactive=()):
    seats = [
        PlayerState(name="P0", life=20, hand=list(hand0), library=list(lib0)),
        PlayerState(name="P1", life=20, hand=list(hand1), library=list(lib1)),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _steps(program):
    """The program's steps: a spell of several sentences compiles to one
    ``sequence`` holding them, and a spell of one compiles to that one."""
    (only,) = program.instructions
    if only.kind == "sequence" and X_FROM_COUNT not in only.payload:
        return tuple(only.payload["steps"])
    return (only,)


def _cards(count: int, name: str = "Card"):
    return [_mk_card(f"{name} {index}", "", "Sorcery", "") for index in range(count)]


# --- "up to" is a ceiling the discarding player chooses under ------------------

def test_a_targeted_up_to_discard_lets_the_player_stop_early():
    spell = _mk_card("Mild Coercion", "{B}", "Sorcery", "Target player discards up to two cards.")
    assert compile_card_oracle(spell).instructions[0].payload["up_to"] is True
    game = _game(hand0=[spell], hand1=_cards(3), interactive=(1,))
    assert game.cast_from_hand(0, "Mild Coercion", target_player_index=1).supported
    (choice,) = game.pending_choices
    assert (choice.data["count"], choice.data["up_to"]) == (2, True)
    assert game.confirm_discard(1, [2])
    assert len(game.players[1].hand) == 2 and not game.stack


def test_a_controllers_up_to_discard_may_be_answered_with_none():
    spell = _mk_card("Own Choice", "{B}", "Sorcery", "Discard up to two cards.")
    game = _game(hand0=[spell, *_cards(3)], interactive=(0,))
    assert game.cast_from_hand(0, "Own Choice").supported
    assert game.pending_choices[0].data["up_to"] is True
    assert game.confirm_discard(0, [])
    assert len(game.players[0].hand) == 3


def test_an_exact_discard_is_still_exact():
    spell = _mk_card("Coercion Two", "{B}", "Sorcery", "Target player discards two cards.")
    assert "up_to" not in compile_card_oracle(spell).instructions[0].payload
    game = _game(hand0=[spell], hand1=_cards(3), interactive=(1,))
    game.cast_from_hand(0, "Coercion Two", target_player_index=1)
    assert not game.confirm_discard(1, [0])
    assert game.confirm_discard(1, [0, 1])


@pytest.mark.parametrize("text", [
    # A sample has no chooser, so there is nobody to stop early.
    "Target player discards up to two cards at random.",
    "Discard up to two cards at random.",
    # Seats armed with a count: no prompt of theirs offers a ceiling.
    "Each opponent discards up to two cards.",
])
def test_an_up_to_discard_no_prompt_can_offer_is_refused(text):
    assert not _program(text).supported


def test_no_shipped_card_prints_a_bare_up_to_discard():
    """The census behind the change: the two pool cards that print "up to" on
    a discard reach it through other lowerings, so nothing shipped moved."""
    import re

    printers = sorted(
        card.name for card in load_catalog()
        if re.search(r"discards? up to", card.oracle_text or "", re.I)
    )
    assert printers == ["Kinetic Augur", "Mind Bomb"]
    for card in load_catalog():
        if card.name in printers:
            kinds = [i.kind for i in compile_card_oracle(card).instructions]
            assert "discard_target_cards" not in kinds
            assert "discard_controller_cards" not in kinds


# --- "that many" after a draw the count itself depends on ----------------------

def test_a_discard_of_that_many_after_a_hand_sized_draw_shares_one_count():
    (wrapper,) = _steps(_program(
        "Draw cards equal to the number of cards in your hand, then discard "
        "that many cards."
    ))
    assert wrapper.kind == "sequence"
    assert wrapper.payload[X_FROM_COUNT] == {"zone": "hand", "owner": "you", "filter": {}}
    draw, discard = wrapper.payload["steps"]
    assert (draw.kind, discard.kind) == ("draw_controller_cards", "discard_controller_cards")
    assert draw.payload == {"amount": "x"} and discard.payload == {"amount": "x"}
    assert X_FROM_COUNT not in draw.payload and X_FROM_COUNT not in discard.payload


def test_a_hand_sized_draw_then_discard_moves_the_number_it_counted():
    """Two other cards in hand: two drawn, two discarded — not four."""
    spell = _mk_card(
        "Churn", "{U}", "Sorcery",
        "Draw cards equal to the number of cards in your hand, then discard "
        "that many cards.",
    )
    game = _game(hand0=[spell, *_cards(2, "Held")], lib0=_cards(6, "Deck"), interactive=(0,))
    assert game.cast_from_hand(0, "Churn").supported
    (choice,) = game.pending_choices
    assert choice.data["count"] == 2
    assert len(game.players[0].hand) == 4
    assert game.confirm_discard(0, [0, 1])
    assert len(game.players[0].hand) == 2 and len(game.players[0].library) == 4


def test_the_shared_count_holds_in_the_middle_of_a_longer_effect():
    lowered = _steps(_program(
        "You gain 1 life. Draw cards equal to the number of cards in your "
        "hand, then discard that many cards."
    ))
    assert [i.kind for i in lowered] == ["target_gains_life", "sequence"]
    assert lowered[1].payload[X_FROM_COUNT]["zone"] == "hand"


def test_a_board_sized_draw_then_discard_is_lowered_as_it_was():
    """A count of Islands is the same before and after the draw, so that
    sentence keeps the shape it has always had (and its shipped card its
    program)."""
    draw, discard = _steps(_program(
        "Draw a card for each Island you control, then discard that many cards."
    ))
    assert (draw.kind, discard.kind) == ("draw_controller_cards", "discard_controller_cards")
    assert draw.payload[X_FROM_COUNT] == discard.payload[X_FROM_COUNT]


# --- a mill sized by a count ---------------------------------------------------

def test_a_mill_reads_the_count_spec_a_draw_reads():
    mill = _program("Target player mills cards equal to the number of cards in their hand.")
    draw = _program("Target player draws cards equal to the number of cards in their hand.")
    assert mill.supported and draw.supported
    assert mill.instructions[0].payload[X_FROM_COUNT] == draw.instructions[0].payload[X_FROM_COUNT]

    spell = _mk_card(
        "Grind", "{U}", "Sorcery",
        "Target player mills cards equal to the number of cards in their hand.",
    )
    game = _game(hand0=[spell], hand1=_cards(2, "Held"), lib1=_cards(5, "Deck"))
    assert game.cast_from_hand(0, "Grind", target_player_index=1).supported
    resolve_stack(game)
    assert len(game.players[1].graveyard) == 2 and len(game.players[1].library) == 3
