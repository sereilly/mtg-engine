"""A player is a target like any other (CR 601.2c, CR 608.2b).

``legality.cast_target_refusal`` held a named *permanent* to the list the
picker offers and never read a named *player*: the seat rides one field with
the battlefield a permanent target sits on, so the gate left it alone. Every
narrowing a player phrase prints was therefore the picker's and nobody else's.

The cards here are the shapes the pool-wide sweeps in
``tests/engine/test_player_target_census.py`` and
``test_player_target_resolution_census.py`` count; each is driven to the board
it leaves, because a refusal that still spent the mana — or a spell "countered
by the rules" whose second sentence still ran — would pass a test that only
read the result object.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import resolve_stack


def _duel(pool, hand, *, opp_hand=(), board=(), opp_board=(), mana=None, seats=2):
    """A table with *hand* in seat 0's hand and exactly *mana* in its pool.

    *pool* is the whole catalog by name: the cards here come from eight sets
    and the subject is the rule, not any one of them."""
    find = pool.__getitem__
    players = [
        PlayerState(
            f"P{seat}", library=[find("Forest")] * 12,
            hand=[find(name) for name in (hand if seat == 0 else opp_hand if seat == 1 else ())],
        )
        for seat in range(seats)
    ]
    game = Game(players=players)
    game.interactive_seats = set()
    for symbol, amount in (mana or {}).items():
        game.players[0].mana_pool[symbol] = amount
    for seat, names in ((0, board), (1, opp_board)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, Permanent(card=find(name)), None)
    return game


def _names(cards):
    return [card.name for card in cards]


@pytest.mark.cr("601.2c", "102.2")
def test_target_opponent_cannot_be_the_caster(catalog_by_name):
    """Duress: "Target **opponent** reveals their hand. You choose a
    noncreature, nonland card from it. That player discards that card."

    The picker offered seat 1 and the cast accepted seat 0, so the caster's own
    Giant Growth was discarded. Refused now with nothing spent — CR 601.2c makes
    an illegal announcement an uncastable spell, not an ineffective one."""
    game = _duel(
        catalog_by_name, ["Duress", "Giant Growth"], opp_hand=["Giant Growth"], mana={"B": 1},
    )

    assert game.cast_target_spec(0, game.players[0].hand[0])["valid_targets"] == [
        {"kind": "player", "seat": 1}
    ]
    refused = game.cast_from_hand(0, "Duress", target_player_index=0)

    assert not refused.supported
    assert refused.details == "no valid target for Duress"
    assert _names(game.players[0].hand) == ["Duress", "Giant Growth"]
    assert game.players[0].mana_pool["B"] == 1, "nothing was spent"
    assert game.stack == [] and game.players[0].graveyard == []

    cast = game.cast_from_hand(0, "Duress", target_player_index=1)
    game.auto_resolve_pending_choices()

    assert cast.supported
    assert _names(game.players[1].graveyard) == ["Giant Growth"]
    assert _names(game.players[0].hand) == ["Giant Growth"]


@pytest.mark.cr("601.2c", "702.18a")
def test_a_player_with_shroud_cannot_be_named(catalog_by_name):
    """Ivory Mask: "You have shroud." CR 702.18a says a *player* with shroud
    can't be the target of spells, and Lightning Bolt dealt its 3 anyway —
    the Mask's controller was missing from the picker and from nowhere else."""
    game = _duel(catalog_by_name, ["Lightning Bolt"], opp_board=["Ivory Mask"], mana={"R": 1})

    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert not refused.supported
    assert game.players[1].life == 20
    assert _names(game.players[0].hand) == ["Lightning Bolt"]
    assert game.players[0].mana_pool["R"] == 1

    # The caster is still a legal target, and "any target" still reaches a
    # creature: the shroud is the Mask's controller's alone.
    own_face = game.cast_from_hand(0, "Lightning Bolt", target_player_index=0)
    assert own_face.supported
    assert game.players[0].life == 17


@pytest.mark.cr("601.2c", "702.18a")
def test_a_cast_naming_nobody_is_not_aimed_at_a_player_with_shroud(catalog_by_name):
    """The headless default is a target too. A bare Lightning Bolt resolves at
    the opposing seat; with that seat behind an Ivory Mask the default is one
    the picker would not offer, and the cast says so instead of resolving."""
    game = _duel(catalog_by_name, ["Lightning Bolt"], opp_board=["Ivory Mask"], mana={"R": 1})

    refused = game.cast_from_hand(0, "Lightning Bolt")

    assert not refused.supported
    assert refused.details == (
        "Lightning Bolt has to name its target: P1 can't be chosen (CR 601.2c)"
    )
    assert game.players[1].life == 20
    assert game.players[0].mana_pool["R"] == 1

    # Nothing about an unprotected table changes: the bare cast is the bolt to
    # the opposing face it has always been.
    plain = _duel(catalog_by_name, ["Lightning Bolt"], mana={"R": 1})
    assert plain.cast_from_hand(0, "Lightning Bolt").supported
    assert plain.players[1].life == 17


@pytest.mark.cr("601.2c")
def test_a_player_who_has_left_the_game_cannot_be_named(catalog_by_name):
    game = _duel(catalog_by_name, ["Lightning Bolt"], mana={"R": 1}, seats=3)
    game.players[2].lost = True

    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=2)

    assert not refused.supported
    assert game.players[2].life == 20
    assert _names(game.players[0].hand) == ["Lightning Bolt"]


@pytest.mark.cr("601.2c", "601.2d")
def test_each_entry_of_a_division_is_a_target(catalog_by_name):
    """Fireball: "…deals X damage divided evenly, rounded down, among any
    number of targets." The division list was bounds-checked and nothing more,
    so an entry could name a land, a creature with protection from red, or a
    player with shroud."""
    game = _duel(
        catalog_by_name, ["Fireball"], opp_board=["Forest", "Grizzly Bears", "Ivory Mask"],
        mana={"R": 4},
    )
    forest, bears = game.players[1].battlefield[0], game.players[1].battlefield[1]

    at_a_land = game.cast_from_hand(
        0, "Fireball", x_value=2, divided_targets=[(1, game.battlefield_index_of(forest))],
    )
    at_the_mask = game.cast_from_hand(0, "Fireball", x_value=2, divided_targets=[(1, None)])

    assert not at_a_land.supported and not at_the_mask.supported
    assert _names(game.players[0].hand) == ["Fireball"]
    assert game.players[0].mana_pool["R"] == 4
    assert game.players[1].life == 20 and game.is_on_battlefield(forest)

    legal = game.cast_from_hand(
        0, "Fireball", x_value=2, divided_targets=[(1, game.battlefield_index_of(bears))],
    )
    assert legal.supported
    assert not game.is_on_battlefield(bears)


@pytest.mark.cr("608.2b", "702.18a")
def test_a_spell_whose_only_target_gained_shroud_does_not_resolve(catalog_by_name):
    """Soul Feast: "Target player loses 4 life and you gain 4 life."

    CR 608.2b's own worked example is this shape (Sorin's Thirst: "Its
    controller doesn't gain any life"). The rule was not asked of a spell whose
    target may be a player, so with an Ivory Mask arriving in response the
    opponent lost 4 from behind it and the caster gained 4."""
    game = _duel(catalog_by_name, ["Soul Feast"], mana={"B": 5})
    mask = catalog_by_name["Ivory Mask"]

    assert game.queue_from_hand(0, "Soul Feast", target_player_index=1).supported
    game._put_permanent_onto_battlefield(1, Permanent(card=mask), None)
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert _names(game.players[0].graveyard) == ["Soul Feast"]
    assert any(
        "Soul Feast was removed from the stack: every target is illegal (608.2b)" in line
        for line in game.log
    )


@pytest.mark.cr("608.2b")
def test_a_burn_spell_whose_creature_left_does_not_run_its_second_sentence(catalog_by_name):
    """Psionic Blast: "Psionic Blast deals 4 damage to any target and 2 damage
    to you." Aimed at a creature that leaves in response, the spell has no
    legal target and does not resolve — it used to, dealing its 2 to the caster
    for a blast that hit nothing."""
    game = _duel(catalog_by_name, ["Psionic Blast"], opp_board=["Grizzly Bears"], mana={"U": 3})
    bears = game.players[1].battlefield[0]

    assert game.queue_from_hand(
        0, "Psionic Blast", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.remove_from_battlefield(bears)
    game._permanent_to_graveyard(game.players[1], bears)
    resolve_stack(game)

    assert game.players[0].life == 20, "the rider belongs to a spell that did not resolve"
    assert game.players[1].life == 20
    assert _names(game.players[0].graveyard) == ["Psionic Blast"]


@pytest.mark.cr("608.2b", "702.33g")
def test_an_unkicked_spell_is_not_judged_by_a_target_it_did_not_announce(catalog_by_name):
    """Probe: "Kicker {1}{B}. Draw three cards, then discard two cards. If
    this spell was kicked, target player discards two cards."

    The web route sends a seat with every cast. Unkicked, Probe has no target
    (CR 702.33g), so a seat that came to have shroud is not a target that
    became illegal — the spell resolves and draws."""
    game = _duel(catalog_by_name, ["Probe"], mana={"U": 3})
    mask = catalog_by_name["Ivory Mask"]

    assert game.queue_from_hand(0, "Probe", target_player_index=1).supported
    game._put_permanent_onto_battlefield(1, Permanent(card=mask), None)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 1, "drew three, discarded two"
    assert not any("(608.2b)" in line for line in game.log)


@pytest.mark.cr("608.2b", "702.33g")
def test_an_unkicked_spell_with_a_kicked_only_second_target_still_resolves(catalog_by_name):
    """Rushing River: "Kicker—Sacrifice a land. Return target nonland permanent
    to its owner's hand. If this spell was kicked, return another target
    nonland permanent to its owner's hand."

    CR 608.2b re-asks the announcement's question, and the announcement was
    made under the kicker that was paid. Asked as the card's every arm, the
    unkicked spell's one target was probed as half of a two-target
    announcement and read illegal."""
    game = _duel(catalog_by_name, ["Rushing River"], opp_board=["Grizzly Bears"], mana={"U": 3})
    bears = game.players[1].battlefield[0]

    cast = game.cast_from_hand(
        0, "Rushing River", target_permanent_ids=[bears.permanent_id],
        optional_cost_payments={},
    )

    assert cast.supported
    assert not game.is_on_battlefield(bears)
    assert _names(game.players[1].hand) == ["Grizzly Bears"]
    assert not any("(608.2b)" in line for line in game.log)
