"""A text change aimed at a face-down creature (CR 612, 708.5, 708.8).

Artificial Evolution: "Change the text of target spell or permanent by
replacing all instances of one creature type with another. The new creature
type can't be Wall." Its words are chosen as it resolves (its ruling,
2004-10-04: "You choose the words to change on resolution"), and any creature
type may be named ("can target a card with no appropriate words on it").

A face-down creature has no text and no subtypes (CR 708.2a), but an effect
applied to it goes on applying once it is face up (CR 708.8) — Putrid Raptor's
ruling (2004-10-04): "You can use a text-changing effect that changes creature
types on this card while is it face down to change Zombie to something else.
This will change the type of card you have to discard to turn it face up."

So what may be named is the whole catalog, face down or not — and what the
**default** names is the question: the first creature type written on the
target, read off the blank 2/2, was no word at all, and a seat nobody asks
"chose no creature type" for every face-down target, its own Putrid Raptor
included. Now the default reads the target as the chooser sees it
(``text_changes.text_seen_by``): the hidden card's face-up words to its
controller, who may look at it (CR 708.5), and nothing to anybody else, who
may not — so the default never names a word only the hidden card could tell.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.face_down import face_down_card, morph_cost
from engine.models import Permanent
from engine.text_changes import face_up_text_card
from tests.helpers import _nosick, resolve_stack


def _cards(set_pool) -> dict:
    scg, ons = set_pool("SCG"), set_pool("ONS")
    catalog = {card.name: card for card in load_catalog()}
    return {
        "raptor": scg["Putrid Raptor"],
        "evolution": ons["Artificial Evolution"],
        "bears": catalog["Grizzly Bears"],
        "island": catalog["Island"],
    }


def _table(cards, *, raptor_seat: int, interactive=()):
    raptor = _nosick(Permanent(card=face_down_card(cards["raptor"])))
    bears = _nosick(Permanent(card=cards["bears"]))
    seats = [
        PlayerState(name="Caster", hand=[cards["evolution"]], battlefield=[bears],
                    library=[cards["island"]] * 5),
        PlayerState(name="Other", library=[cards["island"]] * 5),
    ]
    seats[raptor_seat].battlefield.append(raptor)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game, raptor


def _cast_at(game, raptor) -> None:
    result = game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[raptor.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)


@pytest.mark.cr("708.5", "708.8", "612.1")
def test_on_your_own_face_down_creature_the_default_reads_the_card_you_may_look_at(set_pool):
    game, raptor = _table(_cards(set_pool), raptor_seat=0)
    _cast_at(game, raptor)
    game.auto_resolve_pending_choices()

    # The word replaced is the hidden card's first — Zombie — and the word
    # written is the chooser's own tribe on the board (Bear).
    assert "Artificial Evolution: chose Zombie" in game.log, game.log[-6:]
    assert "Artificial Evolution: chose Bear" in game.log, game.log[-6:]
    assert morph_cost(face_up_text_card(raptor)).lower() == "discard a bear card"
    # Still face down, and the table was never told what it is.
    assert raptor.card.name != "Putrid Raptor"
    assert not any("Putrid Raptor" in line for line in game.log)


@pytest.mark.cr("708.5", "708.2a")
def test_on_an_opponents_face_down_creature_the_default_reads_nothing_hidden(set_pool):
    game, raptor = _table(_cards(set_pool), raptor_seat=1)
    _cast_at(game, raptor)
    game.auto_resolve_pending_choices()

    # The caster may not look at it (CR 708.5), so no default word comes from
    # it: the blank has none (CR 708.2a), and the hidden card is unchanged.
    assert "Artificial Evolution: chose no creature type" in game.log, game.log[-6:]
    assert morph_cost(face_up_text_card(raptor)).lower() == "discard a zombie card"
    assert not any("Putrid Raptor" in line for line in game.log)


@pytest.mark.cr("708.5", "708.8", "612.1")
def test_a_person_may_name_any_type_for_a_face_down_target_and_it_changes_the_hidden_card(set_pool):
    """The interactive half: the prompt offers the whole catalog — the word
    replaced need not be visible — its default is none, so the client shows no
    word read off the hidden card, and the change lands on the card face up."""
    from web.prompt_registry import PromptContext  # noqa: F401  (renderer table)
    from web.prompt_values import _creature_type_choice

    game, raptor = _table(_cards(set_pool), raptor_seat=1, interactive=(0,))
    _cast_at(game, raptor)
    (owed,) = [c for c in game.pending_choices if c.kind == "creature_type_choice"]
    rendered = _creature_type_choice(
        type("Ctx", (), {"game": game})(), [owed],
    )
    assert "zombie" in rendered["creature_types"]
    assert rendered["default_creature_type"] is None
    assert rendered["word_role"] == "replaced"

    assert game.confirm_creature_type_choice(0, "zombie")
    assert game.confirm_creature_type_choice(0, "elf")
    resolve_stack(game)
    assert morph_cost(face_up_text_card(raptor)).lower() == "discard a elf card"
    assert not any("Putrid Raptor" in line for line in game.log)
