"""Offering — CR 702.48.

CR 702.48a: "'[Quality] offering' means 'As an additional cost to cast this
spell, you may sacrifice a [quality] permanent. If you chose to pay the
additional cost, this spell's total cost is reduced by the sacrificed
permanent's mana cost, and you may cast this spell any time you could cast an
instant.'" ``engine/offering.py`` rewrites the keyword line into the cost
sentence (read by the cost table as an optional sacrifice), reduces the cast
by what it sacrificed and opens the instant window CR 601.3c describes.

These tests use invented cards printing the keyword, so what is read is the
printed line and nothing else; the Patrons' own tests are in
``tests/sets/test_bok_creatures.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.line_rewrites import expand_ability_lines
from engine.models import CardDefinition, Permanent, PlayerState
from engine.offering import (OFFERING_COST_TEXT, offering_costs,
                             offering_reduction, unread_offering_line)
from engine.oracle import compile_card_oracle

from tests.helpers import settle

_REMINDER = (
    " (You may cast this spell any time you could cast an instant by "
    "sacrificing a {q} and paying the difference in mana costs between this "
    "and the sacrificed {q}. Mana cost includes color.)"
)


def _card(name, mana_cost, cmc, type_line, text="", power="2", toughness="2"):
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(cmc), type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power,
             "toughness": toughness},
    )


def _patron(quality="Wolf", mana_cost="{4}{G}{G}", cmc=6):
    return _card(
        f"Test Patron of {quality}s", mana_cost, cmc, "Creature — Spirit",
        f"{quality} offering" + _REMINDER.format(q=quality), "5", "5",
    )


def _table(*, hand=(), mana=True) -> Game:
    from engine.card_loader import load_cards, manifest_set_path

    forest = next(
        card for card in load_cards(manifest_set_path("LEA")) if card.name == "Forest"
    )
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[forest] * 20,
                    hand=list(hand) if seat == 0 else [])
        for seat in range(2)
    ])
    game.enforce_mana_costs = mana
    game.start_turn(0)
    settle(game)
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    settle(game)
    return permanent


@pytest.mark.cr("702.48a")
def test_the_keyword_line_is_the_rules_optional_sacrifice():
    """The printed line becomes CR 702.48a's cost sentence before anything
    reads it, and the cost table reads that as an optional sacrifice of the
    quality — the card compiles supported with the line claimed."""
    card = _patron()
    expanded = expand_ability_lines(card.oracle_text, card_name=card.name)
    assert expanded == OFFERING_COST_TEXT.format(quality="Wolf")
    (cost,) = offering_costs(card)
    assert cost.optional_key == "sacrifice a wolf"
    assert cost.sacrifice_filter == {"subtype_filter": "wolf"}
    assert compile_card_oracle(card).supported


@pytest.mark.cr("702.48a")
def test_a_quality_the_vocabulary_does_not_know_stays_unread():
    """A quality no subtype or card type spells is left as printed, and the
    support gate names it rather than dropping the keyword."""
    card = _card("Test Blurp Patron", "{3}", 3, "Artifact",
                 "Blurpish offering\n{T}: You gain 1 life.")
    assert unread_offering_line(
        expand_ability_lines(card.oracle_text, card_name=card.name)
    ) == "Blurpish offering"
    assert not compile_card_oracle(card).supported


@pytest.mark.cr("702.48c")
def test_coloured_mana_reduces_its_own_type_and_the_excess_comes_off_generic():
    """A {1}{B}{B} Wolf offered for a {4}{G}{G} Patron: the {1} comes off
    generic, the two {B} find no black to reduce and come off generic too —
    {G}{G} left. A {G}{G} Wolf takes the two green and leaves {4}."""
    from engine.cost_modifiers import reduce_cost

    patron_cost = {"generic": 4, "G": 2}
    black_wolf = Permanent(card=_card("Test Black Wolf", "{1}{B}{B}", 3, "Creature — Wolf"))
    green_wolf = Permanent(card=_card("Test Green Wolf", "{G}{G}", 2, "Creature — Wolf"))
    def left(wolf):
        owed = reduce_cost(patron_cost, offering_reduction(wolf))
        return {symbol: amount for symbol, amount in owed.items() if amount}

    assert left(black_wolf) == {"generic": 1, "G": 2}
    assert left(green_wolf) == {"generic": 4}


@pytest.mark.cr("702.48c")
def test_a_token_has_no_mana_cost_and_reduces_nothing():
    """CR 202.1b: a token that is not a copy has no mana cost, so offering it
    pays the cost in full and buys only the timing."""
    from engine.tokens import make_token_card

    token = Permanent(card=make_token_card("Wolf", 2, 2, "Token Creature — Wolf"))
    assert not offering_reduction(token)


@pytest.mark.cr("702.48b", "702.48c")
def test_the_cast_sacrifices_the_wolf_and_pays_the_difference():
    """Cast in a main phase with {G}{G}{G}{G} floating and a {G}{G} Wolf:
    the Wolf is sacrificed as the cost is paid and the four green pay the {4}
    left — nothing floats."""
    patron = _patron()
    game = _table(hand=[patron])
    wolf = _put(game, _card("Test Green Wolf", "{G}{G}", 2, "Creature — Wolf"))
    game.players[0].mana_pool.update({"G": 4})
    result = game.cast_from_hand(
        0, patron.name, optional_cost_payments={"sacrifice a wolf": 1},
    )
    assert result.supported, result
    settle(game)
    assert not game.is_on_battlefield(wolf)
    assert [p.card.name for p in game.controlled_by(0)] == [patron.name]
    assert not any(game.players[0].mana_pool.values())


@pytest.mark.cr("702.48a", "601.3c")
def test_cast_at_instant_speed_only_by_paying_the_offering():
    """On the opponent's turn, with a Wolf: the cast that declines the
    offering is refused (CR 601.3c lets it begin; CR 601.2e makes it
    illegal), the cast that pays it is made. Declining in the caster's own
    main phase is an ordinary cast."""
    patron = _patron()
    game = _table(hand=[patron, patron], mana=False)
    _put(game, _card("Test Wolf", "{1}{G}", 2, "Creature — Wolf"))
    game.active_player_index = 1
    refused = game.queue_from_hand(0, patron.name)
    assert not refused.supported
    assert "only by paying its offering (sacrifice a Wolf)" in refused.details
    assert game.queue_from_hand(
        0, patron.name, optional_cost_payments={"sacrifice a wolf": 1},
    ).supported
    settle(game)
    game.active_player_index = 0
    assert game.cast_from_hand(0, patron.name).supported


@pytest.mark.cr("702.48a")
def test_the_offer_is_named_offering_and_payable_only_with_a_wolf():
    """The cast-cost offer the client reads: the optional sacrifice, labelled
    "offering", payable once a Wolf is on the caster's side."""
    patron = _patron()
    game = _table(hand=[patron])
    (offer,) = game.cast_cost_offers(0, patron, spell_hand_index=0)
    assert (offer["label"], offer["symbols"], offer["max_times"]) == (
        "offering", "sacrifice a wolf", 0,
    )
    _put(game, _card("Test Wolf", "{1}{G}", 2, "Creature — Wolf"))
    (offer,) = game.cast_cost_offers(0, patron, spell_hand_index=0)
    assert offer["max_times"] == 1
