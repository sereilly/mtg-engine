"""CR rules W1G2 pinned while implementing Urza's Destiny's name-matched search.

Two claims, both about a sentence that talks about an object the sentence in
front of it has already taken off the board — which is the shape all five of
Eradicate, Scour, Splinter, Sowing Salt and Quash print, and the reason this
family needs *records* rather than a board read.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.control import change_control
from engine.models import Permanent
from engine.oracle_types import COUNTERED_SPELL_CONTROLLER, COUNTERED_SPELL_NAME
from tests.helpers import resolve_stack


def _g2r_pool():
    """Every card the manifest carries, both roles — the cards these two rules
    need sit in four different sets and one of them is still `measured`."""
    return {card.name: card for card in load_cards(
        manifest_set_paths(include_measured=True)
    )}


def _g2r_game(*players):
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


@pytest.mark.cr("608.2c", "701.6a")
def test_608_2c_a_counters_later_sentences_run_when_the_spell_cannot_be_countered():
    """CR 701.6a cancels the spell; CR 608.2c runs the rest of the instructions
    in the order written, and "can't be countered" cancels only the cancelling.

    Arcane Denial is the shipped card that shows it: "Counter target spell.
    **Its controller** may draw up to two cards at the beginning of the next
    turn's upkeep." Against Scragnoth the counter does nothing and the draw
    still belongs to Scragnoth's controller — so the seat has to be recorded
    when the counter *chooses* its spell, not when it succeeds. Recorded on
    success alone, the whole second sentence silently disappeared.

    Asserted on the records rather than on the delayed draw, because the two
    are one fact and the record is the one this rule is about: a resolution
    that wrote nothing down has nothing for a later sentence to name, whatever
    that sentence is.
    """
    pool = _g2r_pool()
    game = _g2r_game(
        PlayerState(name="G2r-A", hand=[pool["Arcane Denial"]]),
        PlayerState(name="G2r-B", hand=[pool["Scragnoth"]]),
    )
    assert game.queue_from_hand(1, "Scragnoth").details == "queued"
    assert game.queue_from_hand(
        0, "Arcane Denial", target_stack_index=0,
    ).details == "queued"
    resolve_stack(game)

    # CR 701.6a did nothing: Scragnoth resolved onto the battlefield.
    assert [p.card.name for p in game.players[1].battlefield] == ["Scragnoth"]
    # …and CR 608.2c still ran the sentence behind the counter. The delayed
    # ability it armed carries what the resolution wrote down, which is where
    # "its controller" is answered a turn later (CR 109.4 gives a card in a
    # graveyard no controller to ask by then).
    captured = [trigger.captured for trigger in game.delayed_triggers]
    assert any(
        entry.get(COUNTERED_SPELL_CONTROLLER) == 1
        and entry.get(COUNTERED_SPELL_NAME) == "Scragnoth"
        for entry in captured
    ), captured


@pytest.mark.cr("109.4", "108.3", "400.3")
def test_109_4_its_controller_is_read_before_the_permanent_leaves_the_battlefield():
    """CR 109.4: a card in exile is controlled by nobody, so "**its**
    controller's graveyard, hand, and library" cannot be answered after the
    exile — only before it.

    A stolen creature is what tells the two seats apart. CR 108.3 keeps the
    owner as the player who started with the card, and CR 400.3 sends the
    exiled card to *that* player's exile; the zones the search opens are the
    other one's. A strip that read the record after the fact, or read ownership
    instead, would empty the wrong player's library — quietly, and in the
    caster's favour.
    """
    pool = _g2r_pool()
    bears = pool["Grizzly Bears"]
    stolen = Permanent(card=bears)
    game = _g2r_game(
        PlayerState(name="G2r-A", hand=[pool["Eradicate"]]),
        PlayerState(
            name="G2r-B", battlefield=[stolen], hand=[bears], library=[bears],
        ),
    )
    # Seat 2 takes the Bears from its owner (CR 613 layer 2, a contribution).
    thief = PlayerState(name="G2r-C", hand=[bears], library=[bears])
    game.players.append(thief)
    change_control(stolen, 2, source="test")
    game._sync_control()
    assert game.controller_index_of(stolen) == 2

    assert game.queue_from_hand(
        0, "Eradicate", target_player_index=2, target_permanent_index=0,
    ).details == "queued"
    resolve_stack(game)

    # The thief's zones are the ones the sentence names.
    assert thief.hand == [] and thief.library == []
    # The owner keeps theirs, and CR 400.3 sends the exiled card to their exile.
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].library] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
