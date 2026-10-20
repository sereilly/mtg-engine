"""CR 704.3: "Whenever a player would get priority, the game checks for any of
the listed conditions for state-based actions." CR 117.3b: after a spell or
ability resolves, the active player receives priority. So the check is made
between two resolutions, not only once the stack is empty.

The step's priority window (``_resolve_priority_window``) drained the whole
stack before checking: its plain branch called ``resolve_stack``, and the
branch a driven table takes (the AI simulator's) checked only after a prompt
was answered. ``_settle``, the drain ``cast_from_hand`` runs, has always
checked each time round its loop, which is why a main-phase cast never
showed this. A creature dealt lethal damage by the object on top was still on
the battlefield while the object beneath resolved.
"""

from __future__ import annotations

import pytest

from engine.game import Game
from engine.models import Permanent, PlayerState


def _table(cards, *, driven: bool):
    island = cards["Island"]
    players = [
        PlayerState(name="A", library=[island] * 10),
        PlayerState(name="B", library=[island] * 10),
    ]
    game = Game(players=players)
    if driven:
        # The shape of the AI simulator's table: a driver answers prompts, so
        # the window resolves one object at a time. This one answers nothing.
        game.prompt_driver = lambda _game: False
    game._put_permanent_onto_battlefield(0, Permanent(card=cards["Grizzly Bears"]), None)
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    return game, bears


@pytest.mark.cr("704.3", "117.3b", "704.5g", "608.2b")
@pytest.mark.parametrize("driven", [False, True], ids=["plain window", "driven window"])
def test_a_creature_dealt_lethal_damage_dies_before_the_next_object_resolves(
    catalog_by_name, driven
):
    """A's Giant Growth on its Grizzly Bears, with B's Lightning Bolt at the
    Bears on top. The Bolt resolves and the Bears have lethal damage. The
    state-based check a player makes before receiving priority puts them in
    the graveyard, so the Growth beneath has no legal target and does not
    resolve. Without the check between them, the Growth resolved on a 2/2 with
    3 damage marked and the Bears lived on as a 5/5."""
    game, bears = _table(catalog_by_name, driven=driven)
    a, b = game.players
    a.hand.append(catalog_by_name["Giant Growth"])
    b.hand.append(catalog_by_name["Lightning Bolt"])
    a.mana_pool["G"] = 1
    b.mana_pool["R"] = 1

    growth = game.queue_from_hand(
        0, "Giant Growth", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert growth.supported, growth.details
    bolt = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert bolt.supported, bolt.details

    game._resolve_priority_window()

    assert not game.stack
    assert not any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0)), (
        "the Bears survived: the Giant Growth resolved before the state-based check"
    )
    assert any(card.name == "Grizzly Bears" for card in a.graveyard)
    assert any("Giant Growth" in line and "608.2b" in line for line in game.log)
