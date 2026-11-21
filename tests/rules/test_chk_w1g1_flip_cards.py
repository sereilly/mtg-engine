"""Flip cards — CR 710 (Champions of Kamigawa's ten).

The layout is two sentences in tension. **In every zone, and on the
battlefield unflipped**, a flip card has only its normal characteristics
(CR 710.2) — its top half. **Once a permanent flips**, its bottom half's name,
text box, type line, power and toughness apply instead, its colour and mana
cost unchanged (CR 710.1b, 710.1c); and it forgets the flip when it leaves
(CR 710.4). ``engine/flip_cards.py`` makes the first true by loading the card
as its top half and the second by substituting the permanent's card — morph's
arrangement — so these tests drive real effects through a real ``Game`` and
read the zones, the names and the layers.

The cards are the set's own, from ``set_pool("CHK")``; the effects around them
(a search, a removal spell, a copy) are the shipped cards that print them.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.flip_cards import flip_permanent, is_flipped
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, hand=(), library=None):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(
            name=f"P{seat}",
            library=list(library) if (seat == 0 and library is not None) else [lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    settle(game)
    return game


def _put(game, card, seat=0):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


@pytest.mark.cr("710.2", "710.1a")
def test_a_search_for_a_legendary_card_cannot_find_an_unflipped_flip_card(set_pool):
    """CR 710.2's own example: "An effect that says 'Search your library for a
    legendary card' can't find this flip card." Time of Need searches for a
    legendary creature card: it takes Isamaru, Hound of Konda and leaves Akki
    Lavarunner — whose bottom half, Tok-Tok, is legendary — where it was."""
    chk = set_pool("CHK")
    game = _table(
        set_pool, hand=[chk["Time of Need"]],
        library=[chk["Akki Lavarunner"], chk["Isamaru, Hound of Konda"]],
    )
    assert game.cast_from_hand(0, "Time of Need").supported
    settle(game)
    assert [card.name for card in game.players[0].hand] == ["Isamaru, Hound of Konda"]
    assert [card.name for card in game.players[0].library] == ["Akki Lavarunner"]


@pytest.mark.cr("710.2", "710.1b", "710.1c")
def test_a_flipped_permanent_has_its_bottom_half_and_keeps_its_cost_and_colour(set_pool):
    """Unflipped, Jushi Apprentice is a nonlegendary 1/2 Human Wizard; flipped,
    the same object is Tomoya the Revealer — legendary 2/3 — still blue with
    the mana cost {1}{U} (CR 710.1c), the same permanent id and tapped state."""
    chk = set_pool("CHK")
    game = _table(set_pool)
    jushi = _put(game, chk["Jushi Apprentice"])
    jushi.tapped = True
    before_id = jushi.permanent_id
    assert (jushi.effective_card.name, jushi.effective_card.is_legendary) == (
        "Jushi Apprentice", False,
    )
    assert flip_permanent(game, jushi)
    card = jushi.effective_card
    assert (card.name, card.type_line) == (
        "Tomoya the Revealer", "Legendary Creature — Human Wizard",
    )
    assert (jushi.effective_power, jushi.effective_toughness) == (2, 3)
    assert card.mana_cost == "{1}{U}" and game._effective_colors(jushi) == {"U"}
    assert jushi.permanent_id == before_id and jushi.tapped


@pytest.mark.cr("710.4")
def test_flipping_is_one_way(set_pool):
    """CR 710.4: "Once a permanent is flipped, it's impossible for it to become
    unflipped." A second flip does nothing and says so."""
    chk = set_pool("CHK")
    game = _table(set_pool)
    jushi = _put(game, chk["Jushi Apprentice"])
    assert flip_permanent(game, jushi)
    assert not flip_permanent(game, jushi)
    assert is_flipped(jushi) and jushi.effective_card.name == "Tomoya the Revealer"


@pytest.mark.cr("710.4", "400.7")
def test_an_exiled_flipped_permanent_is_its_top_half_in_exile(set_pool):
    """Swords to Plowshares exiles a flipped Tomoya: exile holds Jushi
    Apprentice (CR 710.4: "if a flipped permanent leaves the battlefield, it
    retains no memory of its status"), and its controller gains the life the
    departed object's power was — Tomoya's 2 (CR 608.2h's last-known
    information is the flipped object)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _table(set_pool, hand=[lea["Swords to Plowshares"]])
    jushi = _put(game, chk["Jushi Apprentice"], seat=1)
    flip_permanent(game, jushi)
    assert game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[jushi.permanent_id],
    ).supported
    settle(game)
    assert [card.name for card in game.players[1].exile] == ["Jushi Apprentice"]
    assert not game.players[1].exile[0].is_legendary
    assert game.players[1].life == 22


@pytest.mark.cr("707.2", "110.5a")
def test_a_copy_of_a_flipped_permanent_is_the_unflipped_card(set_pool):
    """CR 707.2: status is not copied, and flipped is a status (CR 110.5). A
    Clone entering as a copy of a flipped Tomoya the Revealer copies the flip
    card's copiable values — it is a Jushi Apprentice, nonlegendary 1/2 — so
    no legend rule applies between them."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _table(set_pool, hand=[lea["Clone"]])
    tomoya = _put(game, chk["Jushi Apprentice"])
    flip_permanent(game, tomoya)
    assert game.cast_from_hand(0, "Clone").supported
    settle(game)
    clone = next(p for p in game.all_permanents() if p.card.name == "Clone")
    assert clone.effective_card.name == "Jushi Apprentice", clone.effective_card.name
    assert not clone.effective_card.is_legendary
    assert (clone.effective_power, clone.effective_toughness) == (1, 2)
    assert game.is_on_battlefield(tomoya) and game.is_on_battlefield(clone)


@pytest.mark.cr("707.3", "110.5c")
def test_a_flipped_copy_of_a_flip_card_has_its_bottom_half(set_pool):
    """CR 110.5c's Dimir Doppelganger, with a Clone: copying Jushi Apprentice,
    the Clone has its ability, and flipping through it gives the Clone the
    flipped status (CR 110.5c) — so its copiable values are "modified by the
    copy's status" (CR 707.3) and it is Tomoya the Revealer, while its own
    card stays the Clone it is printed on."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _table(set_pool, hand=[lea["Clone"]] + [lea["Island"]] * 8)
    jushi = _put(game, chk["Jushi Apprentice"], seat=1)
    assert game.cast_from_hand(0, "Clone").supported
    settle(game)
    clone = next(p for p in game.all_permanents() if p.card.name == "Clone")
    assert clone.effective_card.name == "Jushi Apprentice"
    clone.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(
        0, "Clone", permanent_index=game.battlefield_index_of(clone),
    )
    assert result.supported, (result, game.log[-5:])
    settle(game)
    assert len(game.players[0].hand) >= 9
    assert is_flipped(clone)
    assert clone.card.name == "Clone"
    assert clone.effective_card.name == "Tomoya the Revealer"
    assert (clone.effective_power, clone.effective_toughness) == (2, 3)
    assert not is_flipped(jushi)


@pytest.mark.cr("710.5", "201.4c")
def test_a_flip_cards_alternative_name_may_be_chosen(set_pool):
    """CR 710.5: a player choosing a card name may choose a flip card's
    alternative name. The names a chooser is offered for what they can see
    include Tomoya the Revealer beside the Jushi Apprentice in a graveyard;
    and a bounded naming judges the alternative name by the bottom half's
    characteristics (CR 201.4c) — a creature name for "choose a creature card
    name", and refused by "choose a noncreature card name"."""
    from engine.pending_choices import PendingChoice

    chk = set_pool("CHK")
    game = _table(set_pool)
    game.players[1].graveyard.append(chk["Jushi Apprentice"])
    offered = game._nameable_cards(0)
    assert "Jushi Apprentice" in offered and "Tomoya the Revealer" in offered
    creature = PendingChoice("choose_card_name", 0, {"card_type": "creature"})
    assert not game._named_card_breaks_printed_bound(creature, "Tomoya the Revealer")
    noncreature = PendingChoice("choose_card_name", 0, {"excluded_card_type": "creature"})
    assert game._named_card_breaks_printed_bound(noncreature, "Tomoya the Revealer")


def _invented_tenderfoot():
    """Bushi Tenderfoot's top half over a bottom half whose keyword ships —
    "Double strike" — because Kenzo the Hardhearted's bushido is another
    group's keyword this round; the whole-card test is written where the two
    meet. Built the way the loader builds a flip entry."""
    from engine.flip_cards import loaded_flip_card
    from engine.models import CardDefinition, CardFace

    whole = CardDefinition(
        name="Test Tenderfoot // Test Hardheart", mana_cost="{W}", cmc=1.0,
        type_line="Creature — Human Soldier // Legendary Creature — Human Samurai",
        oracle_text="", colors=("W",), color_identity=("W",),
        keywords=("Double strike",), produced_mana=(),
        raw={"keywords": ["Double strike"]}, power="1", toughness="1", layout="flip",
        faces=(
            CardFace(
                "Test Tenderfoot", "{W}", "Creature — Human Soldier",
                "When a creature dealt damage by this creature this turn dies, "
                "flip this creature.", "1", "1",
            ),
            CardFace(
                "Test Hardheart", "", "Legendary Creature — Human Samurai",
                "Double strike", "3", "4",
            ),
        ),
    )
    return loaded_flip_card(whole)


@pytest.mark.cr("603.1", "710.2", "603.10a")
def test_the_tenderfoot_flips_off_its_victim_and_not_off_itself(set_pool):
    """The trigger is about *another* creature's death, which a reading of
    the line as the source's own death got wrong: the Tenderfoot dying flips
    nothing, and a creature it pinged dying this turn flips it."""
    from tests.helpers import declare_attack, drive_combat

    lea = set_pool("LEA")
    game = _table(set_pool, hand=[lea["Lightning Bolt"], lea["Giant Growth"]])
    mine = _put(game, _invented_tenderfoot())
    elves = _put(game, lea["Llanowar Elves"], seat=1)
    declare_attack(game, 0, blocks={game.battlefield_index_of(elves): 0})
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[mine.permanent_id],
    ).supported
    settle(game)
    drive_combat(game)
    assert not game.is_on_battlefield(elves)
    assert is_flipped(mine)
    card = mine.effective_card
    assert (card.name, card.is_legendary) == ("Test Hardheart", True)
    assert game._has_keyword(mine, "double strike")
    # A second Tenderfoot that dies itself, having damaged nothing that
    # died: no flip trigger fires for it or for anyone else.
    other = _put(game, _invented_tenderfoot())
    since = len(game.log)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[other.permanent_id],
    ).supported
    settle(game)
    assert not game.is_on_battlefield(other)
    assert not any("flipped" in line or "flip" in line for line in game.log[since:])
