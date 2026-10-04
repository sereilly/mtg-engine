"""Regressions (PCY W3G2): "the color of your choice" is named while the effect
is applied, and an announced colour no longer recolours the object announced.

CR 608.2d: a choice a spell or ability offers, other than the ones made as it
was put on the stack, is announced *while applying the effect*. CR 601.2b-c and
CR 602.2b do not announce a colour, so the colour of "protection from the color
of your choice" is named after every response has resolved — Mother of Runes'
controller sees the Lightning Bolt and *then* names red.

The engine read it off the activation instead, on ``choices["new_color"]`` —
the wire field an any-colour mana ability names its colour on. Eleven shipped
cards did (W2G5's seven, Dream Coat, and the three "Choose a color." spells
whose choosing step read the cast): an interactive seat was never asked, a
client that sent no colour granted nothing, and the web client asked before
the opponent could respond.

The same key was what a Lace writes to recolour a spell on the stack, so every
object announced *with* a colour was that colour while it waited: a white Feat
of Resistance cast "for red" was a red spell, a blue Sleight of Mind cast to
write "red" was a red spell. Two facts, one key; they are two keys now.

The pool-wide guard is ``tests/engine/test_color_choice_timing.py``; these
drive the shapes through a real response.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack

_W3G2_POOL: dict = {}
for _w3g2_card in load_cards(manifest_set_paths()):
    _W3G2_POOL.setdefault(_w3g2_card.name, _w3g2_card)


def _w3g2_onto(game, seat, name):
    perm = Permanent(card=_W3G2_POOL[name])
    perm.metadata["summoning_sick"] = False
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    return perm


def _w3g2_bolted(interactive):
    """Seat 1's Lightning Bolt on the stack, aimed at seat 0's Grizzly Bears."""
    game = Game(players=[
        PlayerState(name="P0", life=20),
        PlayerState(name="P1", life=20, hand=[_W3G2_POOL["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    bears = _w3g2_onto(game, 0, "Grizzly Bears")
    bolt = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert bolt.supported, bolt.details
    return game, bears  # _w3g2_bolted


@pytest.mark.cr("608.2d", "702.16b")
def test_mother_of_runes_names_the_colour_after_the_response():
    """The Bolt is already on the stack when Mother's ability resolves, so the
    colour is named against it — and red makes the Bolt's only target illegal
    (CR 702.16b), so it does not resolve (CR 608.2b)."""
    game, bears = _w3g2_bolted(interactive={0})
    _w3g2_onto(game, 0, "Mother of Runes")
    queued = game.queue_permanent_ability(
        0, "Mother of Runes", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert queued.supported, queued.details

    game.resolve_top_of_stack()
    owed = [choice for choice in game.pending_choices if choice.kind == "color_choice"]
    assert [choice.player_index for choice in owed] == [0], "the activator is asked"
    assert [item.card.name for item in game.stack][0] == "Lightning Bolt"

    assert game.confirm_color_choice(0, "R")
    resolve_stack(game)

    assert game.is_on_battlefield(bears), game.log
    assert game._protection_colors(bears) == {"R"}
    # The log names the colour that was chosen, not the printed choice.
    assert any("gains protection from red" in line for line in game.log), game.log


@pytest.mark.cr("608.2d")
def test_an_announced_colour_is_not_the_answer():
    """A caller that still sends a colour with the activation is not answering
    the question: the seat is asked anyway, and its answer is what lands."""
    game, bears = _w3g2_bolted(interactive={0})
    _w3g2_onto(game, 0, "Mother of Runes")
    game.queue_permanent_ability(
        0, "Mother of Runes", target_player_index=0,
        target_permanent_ids=[bears.permanent_id], mana_color="G",
    )
    # …and the ability on the stack is not green for having been announced so.
    assert "G" not in game._stack_item_colors(game.stack[-1])

    game.resolve_top_of_stack()
    assert game.confirm_color_choice(0, "R")
    resolve_stack(game)

    assert game._protection_colors(bears) == {"R"}


def test_a_seat_nobody_asks_names_the_colour_of_the_threat():
    """The non-interactive default (an AI seat, a headless run) reads the board
    the response left: the topmost opposing object on the stack is the Bolt, so
    red — not the colour of whatever the opponent happens to control most of."""
    game, bears = _w3g2_bolted(interactive=())
    # A green permanent across the table: the board-wide fallback would name it.
    _w3g2_onto(game, 1, "Grizzly Bears")
    _w3g2_onto(game, 0, "Mother of Runes")
    game.queue_permanent_ability(
        0, "Mother of Runes", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    resolve_stack(game)

    assert game.is_on_battlefield(bears), game.log
    assert game._protection_colors(bears) == {"R"}


@pytest.mark.cr("608.2d", "608.2")
def test_feat_of_resistance_asks_once_the_counter_is_on():
    """The spell shape: "Put a +1/+1 counter on target creature you control. It
    gains protection from the color of your choice until end of turn." The
    question sits between the two sentences — the counter is already on when the
    colour is asked (CR 608.2 follows the instructions in order)."""
    game, bears = _w3g2_bolted(interactive={0})
    game.players[0].hand.append(_W3G2_POOL["Feat of Resistance"])
    cast = game.queue_from_hand(
        0, "Feat of Resistance", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert cast.supported, cast.details

    game.resolve_top_of_stack()
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert game._protection_colors(bears) == set()
    assert game.confirm_color_choice(0, "R")
    resolve_stack(game)

    assert game.is_on_battlefield(bears), game.log
    assert game._protection_colors(bears) == {"R"}


def test_a_text_change_announced_with_a_colour_keeps_its_own_colour():
    """Sleight of Mind is blue. Cast to write "red" over "green", it used to be a
    *red* spell on the stack — the replacement word rode the key a Lace's
    recolour is read from — so Red Elemental Blast ("counter target blue
    spell") could not touch it. It is blue while it waits, and the Blast counters
    it."""
    game = Game(players=[
        PlayerState(name="P0", hand=[_W3G2_POOL["Sleight of Mind"]]),
        PlayerState(name="P1", hand=[_W3G2_POOL["Red Elemental Blast"]]),
    ])
    game.enforce_mana_costs = False
    target = _w3g2_onto(game, 1, "Grizzly Bears")
    sleight = game.queue_from_hand(
        0, "Sleight of Mind", target_player_index=1,
        target_permanent_ids=[target.permanent_id], old_color="G", new_color="R",
    )
    assert sleight.supported, sleight.details
    assert game._stack_item_colors(game.stack[-1]) == ("U",)

    blast = game.queue_from_hand(1, "Red Elemental Blast", target_stack_index=0, mode_index=0)
    assert blast.supported, blast.details
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Sleight of Mind"]
    assert not target.metadata.get("text_modified"), "countered before it changed anything"
