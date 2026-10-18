"""CR 601.2h: a spell's additional cost is paid **as announced**, or the spell
is not cast. It is not a different cast paid with something else.

The cast-side twin of ``test_named_cost_permanent_is_not_substituted`` (an
activation's chosen cost, fixed at Seventh Edition). A spell that chooses what
it pays with — "sacrifice a creature", "sacrifice two creatures", "exile a
creature you control", "return X Swamps you control to their owner's hand",
"Buyback—Sacrifice a land" — carries that choice with the cast. Every charger
in ``_pay_additional_costs`` honoured a named permanent "where it is legal" and
otherwise took the default pick: Diabolic Intent told to sacrifice a Forest
sacrificed a creature.

``StackCastingMixin._named_cast_cost_refusal`` is the one check.
``tests/engine/test_named_cast_cost_census.py`` asks it of all 43 spells in the
pool that print such a cost; the cards here are the shapes, one each, with the
board, the zones and the log read at each step.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


def _table(catalog_by_name, mine, theirs=(), *, hand, library=("Forest",) * 6):
    """Seat 0 at its main phase with *hand*, and each side's permanents in the
    order named. Returns ``(game, seat 0's permanents, seat 1's permanents)``."""
    ours = [_nosick(Permanent(card=catalog_by_name[name])) for name in mine]
    far = [_nosick(Permanent(card=catalog_by_name[name])) for name in theirs]
    game = Game(players=[
        PlayerState(name="Caster", hand=[catalog_by_name[name] for name in hand],
                    battlefield=ours, library=[catalog_by_name[name] for name in library]),
        PlayerState(name="Other", battlefield=far,
                    library=[catalog_by_name[name] for name in library]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, ours, far


def _untouched(game, permanents, card_name) -> bool:
    """Nothing was paid and nothing was cast: every permanent is where it was,
    the card is in hand, and the stack is empty."""
    return (
        all(game.is_on_battlefield(permanent) for permanent in permanents)
        and [card.name for card in game.players[0].hand] == [card_name]
        and not game.stack
    )


def test_diabolic_intent_told_to_sacrifice_a_forest_is_not_cast(catalog_by_name):
    """"As an additional cost to cast this spell, sacrifice a creature."

    The repro the defect was measured on. The Forest cannot pay, so the cast is
    refused with the board whole — it used to report ``queued`` with the Bears
    in the graveyard.
    """
    game, mine, _ = _table(
        catalog_by_name, ["Forest", "Grizzly Bears"], hand=["Diabolic Intent"],
    )
    forest, bears = mine

    refused = game.queue_from_hand(
        0, "Diabolic Intent", cost_permanent_ids=[forest.permanent_id],
    )

    assert not refused.supported
    assert refused.details == (
        "Diabolic Intent can't be cast: Forest cannot pay its additional cost "
        "(CR 601.2h)"
    )
    assert refused.details in game.log
    assert _untouched(game, mine, "Diabolic Intent")
    assert game.players[0].graveyard == []


def test_diabolic_intent_cannot_be_paid_with_the_other_seats_creature(catalog_by_name):
    """An opposing creature answers "a creature" and not "sacrifice": only the
    caster's own permanents can pay (CR 701.21a: a player sacrifices a
    permanent they control). Named, it refuses the cast — it used to cost the
    caster one of their own."""
    game, mine, theirs = _table(
        catalog_by_name, ["Grizzly Bears"], ["Hill Giant"], hand=["Diabolic Intent"],
    )

    refused = game.queue_from_hand(
        0, "Diabolic Intent", cost_permanent_ids=[theirs[0].permanent_id],
    )

    assert not refused.supported and "Hill Giant cannot pay" in refused.details
    assert _untouched(game, mine + theirs, "Diabolic Intent")


def test_diabolic_intent_sacrifices_the_creature_its_caster_named(catalog_by_name):
    """The half that must keep working, in both channels: of two creatures the
    one named is the one sacrificed — and it is the one the default would have
    kept. A cast naming nobody still takes the default."""
    for channel in ("id", "slot", "nobody"):
        game, mine, _ = _table(
            catalog_by_name, ["Grizzly Bears", "Hill Giant"],
            hand=["Diabolic Intent"], library=["Forest", "Sol Ring", "Forest"],
        )
        bears, giant = mine
        assert game.default_sacrifice_pick([bears, giant]) is bears
        named = {
            "id": {"cost_permanent_ids": [giant.permanent_id]},
            "slot": {"cost_permanent_index": game.battlefield_index_of(giant)},
            "nobody": {},
        }[channel]

        result = game.queue_from_hand(0, "Diabolic Intent", **named)

        assert result.supported, (channel, result.details)
        paid, kept = (bears, giant) if channel == "nobody" else (giant, bears)
        assert not game.is_on_battlefield(paid), channel
        assert game.is_on_battlefield(kept), channel
        assert f"Caster sacrificed {paid.card.name} to cast Diabolic Intent" in game.log


def test_phyrexian_tribute_named_one_creature_short_is_not_cast(catalog_by_name):
    """"…, sacrifice two creatures." CR 601.2h: "Partial payments are not
    allowed." One creature named is a payment of one; topping it up from the
    default pays with a creature the caster did not name, which is the same
    substitution as replacing it."""
    game, mine, theirs = _table(
        catalog_by_name, ["Grizzly Bears", "Hill Giant", "Llanowar Elves"],
        ["Sol Ring"], hand=["Phyrexian Tribute"],
    )
    bears, giant, elves = mine
    aimed = {"target_permanent_ids": [theirs[0].permanent_id]}

    short = game.queue_from_hand(
        0, "Phyrexian Tribute", cost_permanent_ids=[giant.permanent_id], **aimed,
    )
    assert not short.supported
    assert "takes 2 permanent(s) to sacrifice and 1 were named" in short.details
    assert _untouched(game, mine + theirs, "Phyrexian Tribute")

    twice = game.queue_from_hand(
        0, "Phyrexian Tribute",
        cost_permanent_ids=[giant.permanent_id, giant.permanent_id], **aimed,
    )
    assert not twice.supported and "named twice" in twice.details
    assert _untouched(game, mine + theirs, "Phyrexian Tribute")

    long = game.queue_from_hand(
        0, "Phyrexian Tribute",
        cost_permanent_ids=[p.permanent_id for p in mine], **aimed,
    )
    assert not long.supported and "beyond what its additional cost takes" in long.details
    assert _untouched(game, mine + theirs, "Phyrexian Tribute")

    paid = game.queue_from_hand(
        0, "Phyrexian Tribute",
        cost_permanent_ids=[giant.permanent_id, elves.permanent_id], **aimed,
    )
    assert paid.supported, paid.details
    assert game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(giant) and not game.is_on_battlefield(elves)
    resolve_stack(game)
    assert not game.is_on_battlefield(theirs[0]), "the artifact it was aimed at"


def test_soul_exchange_exiles_the_creature_named_by_id(catalog_by_name):
    """"As an additional cost to cast this spell, exile a creature you
    control." The exile charger read the slot channel alone, so a creature
    named by id — the only way the wire names one — was not read at all and the
    default went instead. The census found it going the *legal* way."""
    game, mine, _ = _table(
        catalog_by_name, ["Grizzly Bears", "Hill Giant"], hand=["Soul Exchange"],
    )
    bears, giant = mine
    game.players[0].graveyard.append(catalog_by_name["Llanowar Elves"])
    assert game.default_sacrifice_pick([bears, giant]) is bears

    result = game.queue_from_hand(
        0, "Soul Exchange", cost_permanent_ids=[giant.permanent_id],
        target_player_index=0, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[0].exile] == ["Hill Giant"]
    assert "Caster exiled Hill Giant to cast Soul Exchange" in game.log


def test_infernal_harvest_returns_the_swamps_named_and_only_a_full_list(catalog_by_name):
    """"…, return X Swamps you control to their owner's hand." The count is
    the announced X (CR 107.3a): two Swamps named for an X of two are the two
    returned, and one Swamp named for an X of two is a partial payment."""
    game, mine, theirs = _table(
        catalog_by_name, ["Swamp", "Swamp", "Swamp", "Forest"], ["Grizzly Bears"],
        hand=["Infernal Harvest"],
    )
    first, second, third, forest = mine
    aimed = {"x_value": 2, "divided_targets": [(1, 0)]}

    short = game.queue_from_hand(
        0, "Infernal Harvest", cost_permanent_ids=[third.permanent_id], **aimed,
    )
    assert not short.supported
    assert "takes 2 permanent(s) to return and 1 were named" in short.details
    assert _untouched(game, mine + theirs, "Infernal Harvest")

    wrong = game.queue_from_hand(
        0, "Infernal Harvest",
        cost_permanent_ids=[third.permanent_id, forest.permanent_id], **aimed,
    )
    assert not wrong.supported and "Forest cannot pay" in wrong.details
    assert _untouched(game, mine + theirs, "Infernal Harvest")

    paid = game.queue_from_hand(
        0, "Infernal Harvest",
        cost_permanent_ids=[third.permanent_id, second.permanent_id], **aimed,
    )
    assert paid.supported, paid.details
    assert game.is_on_battlefield(first) and game.is_on_battlefield(forest)
    assert not game.is_on_battlefield(second) and not game.is_on_battlefield(third)
    assert [card.name for card in game.players[0].hand] == ["Swamp", "Swamp"]


def test_constant_mists_buyback_is_held_only_when_it_is_bought(catalog_by_name):
    """"Buyback—Sacrifice a land." An offer taken is a price like any other: a
    creature named for it refuses the cast. An offer declined charges nothing,
    so a stray name pays nothing and substitutes nothing — the spell is cast
    and the land stays."""
    offer = {"sacrifice a land": 1}
    game, mine, _ = _table(
        catalog_by_name, ["Forest", "Grizzly Bears"], hand=["Constant Mists"],
    )
    forest, bears = mine

    refused = game.queue_from_hand(
        0, "Constant Mists", optional_cost_payments=offer,
        cost_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported and "Grizzly Bears cannot pay" in refused.details
    assert _untouched(game, mine, "Constant Mists")

    declined = game.queue_from_hand(
        0, "Constant Mists", cost_permanent_ids=[forest.permanent_id],
    )
    assert declined.supported, declined.details
    assert game.is_on_battlefield(forest) and game.is_on_battlefield(bears)
    resolve_stack(game)
    assert [card.name for card in game.players[0].graveyard] == ["Constant Mists"]

    game.players[0].hand.append(catalog_by_name["Constant Mists"])
    bought = game.queue_from_hand(
        0, "Constant Mists", optional_cost_payments=offer,
        cost_permanent_ids=[forest.permanent_id],
    )
    assert bought.supported, bought.details
    assert not game.is_on_battlefield(forest)
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Constant Mists"]
