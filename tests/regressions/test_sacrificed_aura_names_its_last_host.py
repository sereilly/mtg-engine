"""Regression: an Aura sacrificed to pay for its own ability still names the
creature it enchanted.

"Sacrifice this Aura: Enchanted creature gets +3/+3 until end of turn."
(Briar Shield, Weatherlight — shipped.) The cost takes the Aura on the way to
the stack (CR 602.2b, 601.2h), so by the time the ability resolves the Aura is
in a graveyard and attached to nothing. CR 608.2h makes "enchanted creature"
the creature it was last attached to — and ``handlers/_targets.attached_host``
has answered exactly that since Cocoon, *provided the caller does not opt out*.

``pump_enchanted_creature`` opted out (``last_known=False``), for an Equipment
that unattaches and stays on the battlefield with its old host written on it.
``attached_host`` already asks last-known information only of a source **off**
the battlefield, so the opt-out guarded nothing — and cost the one card whose
ability is a pump behind a self-sacrifice its whole effect: Briar Shield
fizzled with "aura not attached to a creature" every time it was activated.
No census saw it: the card compiled, reported supported, and the activation
reported resolved. Onslaught's Crowns print the same instruction as the first
half of their sacrifice ability, which is how it was found.

The Equipment half is asserted too, because it is what the opt-out was for.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(card_names, catalog_by_name):
    me = PlayerState(
        name="Me", hand=[catalog_by_name[name] for name in card_names],
        library=[catalog_by_name["Plains"]] * 6,
    )
    opp = PlayerState(name="Opp", library=[catalog_by_name["Forest"]] * 6)
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _put(game, card):
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def test_briar_shield_sacrificed_pumps_the_creature_it_enchanted(catalog_by_name):
    game = _table(["Briar Shield"], catalog_by_name)
    bears = _put(game, catalog_by_name["Grizzly Bears"])
    game._recompute_continuous_effects()
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, "Briar Shield", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)

    assert game.activate_permanent_ability(0, "Briar Shield").supported
    resolve_stack(game)

    assert "Briar Shield" in [card.name for card in game.players[0].graveyard]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5), game.log
    assert "Briar Shield grants Grizzly Bears +3/+3 until end of turn" in game.log
    assert not any("fizzled" in line for line in game.log), game.log


def test_an_unattached_aura_still_on_the_battlefield_pumps_nobody(catalog_by_name):
    """The case the opt-out was written for, read the way ``attached_host``
    now reads it: a source still on the battlefield and attached to nothing
    names no creature — the old host is not pumped from a stale record."""
    from engine.aura_attachment import attach_aura, detach_aura
    from engine.game_types import OracleExecutionContext
    from engine.handlers.pump import pump_enchanted_creature
    from engine.oracle_types import OracleInstruction

    game = _table([], catalog_by_name)
    bears = _put(game, catalog_by_name["Grizzly Bears"])
    shield = _put(game, catalog_by_name["Briar Shield"])
    attach_aura(shield, bears)
    game._recompute_continuous_effects()
    detach_aura(shield, bears)
    assert shield.metadata.get("last_attached_to") is bears
    game._recompute_continuous_effects()
    assert game.is_on_battlefield(shield)

    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=shield.card,
        source_permanent=shield,
    )
    resolved, detail = pump_enchanted_creature(
        game,
        OracleInstruction("pump_enchanted_creature", "", {"power": 3, "toughness": 3}),
        context,
    )
    assert not resolved and detail == "aura not attached to a creature"
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
