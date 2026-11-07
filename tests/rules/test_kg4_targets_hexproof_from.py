"""Hexproof from a colour is that colour's alone (CR 702.11d).

    702.11d "Hexproof from [quality]" is a variant of the hexproof ability.
    "Hexproof from [quality]" on a permanent means "This permanent can't be
    the target of [quality] spells your opponents control or abilities your
    opponents control from [quality] sources." A "hexproof from [quality]"
    ability is a hexproof ability.

Scryfall's keywords field lists a hexproof-from creature under both "Hexproof
from" and "Hexproof" (the rule's last sentence: the variant *is* a hexproof
ability), and the printed-ability seed took the field as written — so Sporeweb
Weaver ("Reach, hexproof from blue") and Garruk's Harbinger ("Hexproof from
black") had bare hexproof (CR 702.11b): no spell or ability an opponent
controlled could target them, of any colour, and the colour their text names
was never in the ability set at all.

Measured backwards on 313bd09d: a red Lightning Bolt aimed at either was
refused at the cast ("is an illegal target").
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(creature: str) -> tuple[Game, Permanent]:
    game = Game(players=[
        PlayerState("P0", library=[_POOL["Island"]] * 5),
        PlayerState("P1", hand=[_POOL["Lightning Bolt"], _POOL["Terror"],
                                _POOL["Unsummon"]],
                    library=[_POOL["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    permanent = Permanent(card=_POOL[creature])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(0, permanent, None)
    game.start_turn(1)
    game._close_current_priority_step()
    return game, permanent


@pytest.mark.cr("702.11d")
@pytest.mark.parametrize("creature, allowed, refused", [
    ("Sporeweb Weaver", "Lightning Bolt", "Unsummon"),
    ("Garruk's Harbinger", "Lightning Bolt", "Terror"),
])
def test_hexproof_from_a_colour_refuses_that_colour_and_admits_another(creature, allowed, refused):
    game, permanent = _table(creature)
    assert permanent.has_keyword("hexproof from " + ("blue" if creature == "Sporeweb Weaver" else "black"))
    assert not permanent.has_keyword("hexproof")

    refusal = game.queue_from_hand(1, refused, target_permanent_ids=[permanent.permanent_id])
    assert not refusal.supported, game.log[-4:]
    assert game.stack == [], game.log[-4:]

    assert game.queue_from_hand(
        1, allowed, target_permanent_ids=[permanent.permanent_id],
    ).supported, game.log[-4:]
    resolve_stack(game)
    assert any(f"Lightning Bolt dealt 3 damage to {creature}" in line for line in game.log), game.log[-6:]


@pytest.mark.cr("702.11d")
def test_hexproof_from_a_colour_does_not_stop_its_controllers_own_spell():
    """"…spells **your opponents** control": its controller's own blue spell
    may target Sporeweb Weaver."""
    game, weaver = _table("Sporeweb Weaver")
    game.players[0].hand = [_POOL["Unsummon"]]
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[weaver.permanent_id],
    ).supported, game.log[-4:]
    resolve_stack(game)
    assert weaver.card in game.players[0].hand, game.log[-4:]
