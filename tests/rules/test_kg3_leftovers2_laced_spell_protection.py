"""Protection reads a spell's colour on the stack, a Lace's recolour included.

Found by kg3/aiplay: Purelace on a Lightning Bolt aimed at a Black Knight
(protection from white) — the Bolt became white and still dealt its 3. CR
702.16b: a permanent with protection from white can't be the target of white
spells, so at resolution every target is illegal and the Bolt does nothing
(CR 608.2b); and a white spell's damage to it is prevented (CR 702.16e).

Protection asked a spell's colours of the printed card through the
controller's board (``object_colors.card_colors``: Celestial Dawn), never of
the stack object, where a Lace's recolour lives
(``StackItem.choices["color_override"]``, read by
``Game._stack_item_colors``). The colour of the spell now resolving comes off
that object (``object_colors.spell_colors``), for the targeting check and for
the damage it deals — so a Lace-recoloured spell is checked against
protection from its new colour and no longer against its old one.

Measured backwards on 90bef6d1: the Laced Bolt killed the Knight, and a Laced
Pyroclasm killed the Knight and spared the Repentant Blacksmith (protection
from red).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table() -> Game:
    def perm(name: str) -> Permanent:
        permanent = Permanent(card=_POOL[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    game = Game(players=[
        PlayerState("P0", battlefield=[perm("Plains"), perm("Black Knight"), perm("Repentant Blacksmith")],
                    hand=[_POOL["Purelace"]], library=[_POOL["Island"]] * 5),
        PlayerState("P1", battlefield=[perm("Mountain")],
                    hand=[_POOL["Lightning Bolt"], _POOL["Pyroclasm"]], library=[_POOL["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._sync_control()
    return game


def _on(game: Game, name: str) -> Permanent | None:
    return next((p for p in game.all_permanents() if p.card.name == name), None)


def _lace_the_spell(game: Game) -> None:
    assert game.queue_from_hand(0, "Purelace", target_player_index=1, target_stack_index=0).supported


@pytest.mark.cr("702.16b", "608.2b", "105.3")
def test_a_bolt_made_white_at_a_black_knight_is_countered_on_resolution():
    game = _table()
    knight = _on(game, "Black Knight")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_ids=[knight.permanent_id],
    ).supported
    _lace_the_spell(game)
    resolve_stack(game)

    assert game.is_on_battlefield(knight) and knight.damage_marked == 0, game.log[-6:]
    assert any("Lightning Bolt" in line and "608.2b" in line for line in game.log), game.log[-6:]


@pytest.mark.cr("702.16e", "105.3")
def test_a_pyroclasm_made_white_spares_protection_from_white_and_not_from_red():
    game = _table()
    knight, smith = _on(game, "Black Knight"), _on(game, "Repentant Blacksmith")
    assert game.queue_from_hand(1, "Pyroclasm").supported
    _lace_the_spell(game)
    resolve_stack(game)

    assert knight.damage_marked == 0, game.log[-6:]
    assert smith.damage_marked == 2, game.log[-6:]


@pytest.mark.cr("702.16e")
def test_an_unlaced_pyroclasm_is_red():
    """The control: the printed colour still decides where nothing moved it."""
    game = _table()
    knight, smith = _on(game, "Black Knight"), _on(game, "Repentant Blacksmith")
    assert game.queue_from_hand(1, "Pyroclasm").supported
    resolve_stack(game)

    assert knight.damage_marked == 2, game.log[-6:]
    assert smith.damage_marked == 0, game.log[-6:]
