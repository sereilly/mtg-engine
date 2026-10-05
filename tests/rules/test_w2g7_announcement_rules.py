"""Rules tests earned by Invasion wave 2, group 7 — what a cast may announce.

CR 601.2c in its two directions. A spell that requires a target cannot be
proposed while no legal target exists; and "up to N", "any number of" and an X
of zero are announcements that legally name nobody. The engine answered the
first for eleven instruction kinds and refused the second for four of them, so
each test here watches the cast path itself decide — a refusal with nothing
spent, or a resolution that does what is left of the card.

The pool-wide sweeps behind these are in
``tests/regressions/test_cast_announcements_w2g7.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.cast_costs import kicker_cost
from engine.models import Permanent
from tests.helpers import _mk_card, _nosick, resolve_stack


def _w2g7_game(card, *, mine=(), theirs=(), graveyard=()) -> Game:
    filler = _mk_card(name="Filler", type_line="Land")
    game = Game(players=[
        PlayerState(
            "A", library=[filler] * 10, hand=[card], graveyard=list(graveyard),
            battlefield=[_nosick(Permanent(card=c)) for c in mine],
        ),
        PlayerState(
            "B", library=[filler] * 10,
            battlefield=[_nosick(Permanent(card=c)) for c in theirs],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def _w2g7_refused_with_nothing_spent(game, card, **announcement) -> str:
    result = game.cast_from_hand(0, card.name, **announcement)
    assert not result.supported, f"{card.name} was cast: {result.details}"
    assert not game.stack
    assert card in game.players[0].hand, f"{card.name} left the hand on a refused cast"
    return result.details


_BEAR = _mk_card(name="W2G7 Bear", type_line="Creature - Bear", power=2, toughness=2)
_RELIC = _mk_card(name="W2G7 Relic", type_line="Artifact")


# ---------------------------------------------------------------------------
# CR 601.2c — a required target must exist
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2c", "601.2e")
@pytest.mark.parametrize(
    "name, why",
    [
        # sequence: the target sits on the first of two sentences
        ("Divine Offering", "Destroy target artifact. You gain life…"),
        # may: an offer about a target already chosen
        ("Twiddle", "You may tap or untap target artifact, creature, or land."),
        # if_then: the target is named inside the condition's arms
        ("Blood Lust", "If target creature has toughness 5 or greater, …"),
        # a kind whose noun phrase rides the payload, in a sequence
        ("Snap", "Return target creature to its owner's hand. Untap up to two lands."),
        # one or more: a floor of one
        ("Heaven's Gate", "One or more target creatures become white…"),
    ],
)
def test_w2g7_601_2c_a_spell_that_requires_a_target_is_not_cast_at_nothing(
    catalog_by_name, name, why
):
    """Whatever wraps the targeting sentence, CR 601.2c asks for the choice as
    the spell is proposed and CR 601.2e returns the game to before the proposal
    when it cannot be made."""
    card = catalog_by_name[name]
    game = _w2g7_game(card)

    details = _w2g7_refused_with_nothing_spent(game, card)

    assert "no valid target" in details, (why, details)
    assert len(game.players[0].library) == 10


@pytest.mark.cr("601.2c")
def test_w2g7_601_2c_the_refusal_is_about_the_board_not_the_card(catalog_by_name):
    """The same Divine Offering with an artifact to name resolves in full —
    and named by id, across the table, with no seat supplied."""
    card = catalog_by_name["Divine Offering"]
    game = _w2g7_game(card, theirs=[_RELIC])
    relic = game.players[1].battlefield[0]

    result = game.cast_from_hand(0, card.name, target_permanent_ids=[relic.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert not game.players[1].battlefield


@pytest.mark.cr("601.2c")
def test_w2g7_601_2c_target_spell_or_permanent_needs_one_of_the_two(catalog_by_name):
    """"Target spell or permanent becomes black." (Deathlace.) Two zones can
    answer; with neither holding anything the spell has no target."""
    card = catalog_by_name["Deathlace"]

    details = _w2g7_refused_with_nothing_spent(_w2g7_game(card), card)
    assert "no valid target" in details

    game = _w2g7_game(card, mine=[_BEAR])
    bear = game.players[0].battlefield[0]
    assert game.cast_from_hand(0, card.name, target_permanent_ids=[bear.permanent_id]).supported
    resolve_stack(game)
    assert "B" in bear.effective_colors, game.log


# ---------------------------------------------------------------------------
# CR 601.2c — zero is a legal number of targets where the card says so
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2c")
@pytest.mark.parametrize(
    "name",
    [
        "Frost Breath",      # Tap up to two target creatures.
        "Tidal Surge",       # Tap up to three target creatures without flying.
        "Energy Arc",        # Untap any number of target creatures.
        "Phyrexian Purge",   # Destroy any number of target creatures.
    ],
)
def test_w2g7_601_2c_up_to_and_any_number_may_be_announced_at_zero(catalog_by_name, name):
    card = catalog_by_name[name]
    game = _w2g7_game(card)

    result = game.cast_from_hand(0, card.name)
    resolve_stack(game)

    assert result.supported, result.details
    assert card in game.players[0].graveyard
    assert game.players[0].life == 20 and game.players[1].life == 20


@pytest.mark.cr("601.2c", "107.3a")
def test_w2g7_601_2c_x_targets_follow_the_x_that_was_announced(catalog_by_name):
    """"Tap X target creatures. Winter Blast deals 2 damage to each of those
    creatures with flying." CR 107.3a has X announced first (CR 601.2b), and
    601.2c then needs exactly that many targets: none at X=0, two at X=2."""
    card = catalog_by_name["Winter Blast"]

    assert _w2g7_game(card).cast_from_hand(0, card.name, x_value=0).supported

    details = _w2g7_refused_with_nothing_spent(_w2g7_game(card), card, x_value=2)
    assert "no valid target" in details


# ---------------------------------------------------------------------------
# CR 702.33g — a kicked-only target is chosen only if the spell was kicked
# ---------------------------------------------------------------------------


_KICKED_ONLY = _mk_card(
    name="W2G7 Footnote", mana_cost="{1}{U}", type_line="Instant",
    oracle_text="Kicker {2}\nDraw a card. If this spell was kicked, destroy target artifact.",
)


@pytest.mark.cr("702.33g", "601.2c")
def test_w2g7_702_33g_an_unkicked_spell_does_not_need_its_kicked_only_target():
    game = _w2g7_game(_KICKED_ONLY)

    result = game.cast_from_hand(0, _KICKED_ONLY.name, optional_cost_payments={})
    resolve_stack(game)

    assert result.supported, result.details
    assert len(game.players[0].hand) == 1, "the card was cast and one was drawn"
    assert len(game.players[0].library) == 9


@pytest.mark.cr("702.33g", "601.2c")
def test_w2g7_702_33g_a_kicked_spell_needs_the_target_its_kicker_bought():
    kicker = kicker_cost(_KICKED_ONLY.oracle_text)

    game = _w2g7_game(_KICKED_ONLY)
    details = _w2g7_refused_with_nothing_spent(
        game, _KICKED_ONLY, optional_cost_payments={kicker: 1}
    )
    assert "no valid target" in details
    assert len(game.players[0].library) == 10, "the unconditional half ran anyway"

    game = _w2g7_game(_KICKED_ONLY, theirs=[_RELIC])
    relic = game.players[1].battlefield[0]
    result = game.cast_from_hand(
        0, _KICKED_ONLY.name, optional_cost_payments={kicker: 1},
        target_permanent_ids=[relic.permanent_id],
    )
    resolve_stack(game)
    assert result.supported, result.details
    assert not game.players[1].battlefield
    assert len(game.players[0].library) == 9


# ---------------------------------------------------------------------------
# CR 709.3a — only the chosen half of a split card is asked
# ---------------------------------------------------------------------------


@pytest.mark.cr("709.3a", "601.2c")
def test_w2g7_709_3a_each_half_of_a_split_card_answers_for_its_own_target(set_pool):
    """Pain // Suffering: "Target player discards a card." and "Destroy target
    land." On a board with no land one half has a target and the other has
    none, and the card is castable as exactly the half that does."""
    card = set_pool("INV")["Pain // Suffering"]

    game = _w2g7_game(card)
    result = game.cast_from_hand(0, "Suffering")
    assert not result.supported and "no valid target" in result.details
    assert card in game.players[0].hand

    result = game.cast_from_hand(0, "Pain", target_player_index=1)
    assert result.supported, result.details


# ---------------------------------------------------------------------------
# CR 609.7a — a source of your choice is chosen, not targeted
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.7a", "115.1")
def test_w2g7_609_7a_a_source_of_your_choice_is_not_a_target_the_cast_can_lack(catalog_by_name):
    """"The next time a source of your choice would deal damage to you this
    turn, prevent that damage." (Reverse Damage.) CR 115.1 makes a target only
    what the word "target" names; the picker for a chosen source being empty
    is not CR 601.2c's business, and the spell stays castable."""
    card = catalog_by_name["Reverse Damage"]
    game = _w2g7_game(card)

    result = game.cast_from_hand(0, card.name)

    assert result.supported, result.details


# ---------------------------------------------------------------------------
# CR 115.1b / 303.4a — an Aura's target, named as the object it is
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.1b", "303.4a", "400.7")
def test_w2g7_115_1b_an_aura_spell_is_targeted_at_the_object_its_id_names(catalog_by_name):
    """An Aura spell is always targeted (CR 115.1b) and the target is the
    object, not the slot it happens to occupy (CR 400.7). Named by id alone,
    with a look-alike in the same slot of the other battlefield."""
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_game(aura, mine=[_BEAR], theirs=[_BEAR])
    mine, theirs = game.players[0].battlefield[0], game.players[1].battlefield[0]

    result = game.cast_from_hand(0, aura.name, target_permanent_ids=[mine.permanent_id])
    resolve_stack(game)

    assert result.supported, result.details
    assert (mine.effective_power, mine.effective_toughness) == (3, 4), game.log
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2), game.log


@pytest.mark.cr("303.4a", "601.2c")
def test_w2g7_303_4a_an_aura_with_no_target_named_is_still_not_cast(catalog_by_name):
    aura = catalog_by_name["Holy Strength"]
    game = _w2g7_game(aura, mine=[_BEAR])

    details = _w2g7_refused_with_nothing_spent(game, aura)

    assert "requires a target" in details
