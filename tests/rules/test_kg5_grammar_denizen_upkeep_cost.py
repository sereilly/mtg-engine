"""Infernal Denizen with one Swamp sacrifices neither: CR 118.12, not 609.3.

"At the beginning of your upkeep, sacrifice two Swamps. If you can't, tap this
creature, and an opponent may gain control of a creature you control of their
choice for as long as this creature remains on the battlefield."

kg4 filed this as a ruling to check: the test that pinned "sacrifices neither"
had cited CR 701.17b (Mill), and CR 609.3 ("If an effect attempts to do
something impossible, it does only as much as possible") seemed to read the
other way. It does not apply. The sentence is CR 118.12's template — "[Do
something]. If [a player] [does, doesn't, or can't], [effect]. … The action [do
something] is a **cost**, paid when the spell or ability resolves" — and CR
118.3: "A player can't pay a cost without having the necessary resources to pay
it fully." One Swamp cannot pay "two Swamps", so nothing is paid and the "If
you can't" branch happens. The card's rulings (2004-10-04, Scryfall) agree as
far as they go: "You must sacrifice the Swamps if you can. You can't choose not
to pay if you have them." The handler was right; its comment now cites the rule
(``handlers/sacrifices.sacrifice_matching_permanent``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(swamps: int, interactive) -> tuple[Game, Permanent]:
    def placed(name: str) -> Permanent:
        permanent = Permanent(card=_CARDS[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    denizen = placed("Infernal Denizen")
    game = Game(players=[
        PlayerState(
            name="P0", library=[_CARDS["Swamp"]] * 10,
            battlefield=[denizen, placed("Grizzly Bears")]
            + [placed("Swamp") for _ in range(swamps)],
        ),
        PlayerState(name="P1", library=[_CARDS["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._recompute_continuous_effects()
    return game, denizen


def _swamps(game: Game) -> int:
    return sum(1 for perm in game.controlled_by(0) if perm.card.name == "Swamp")


@pytest.mark.cr("118.12", "118.3")
@pytest.mark.parametrize("interactive", [(), (0, 1)])
@pytest.mark.parametrize(("swamps", "left"), [(1, 1), (2, 0), (3, 1)])
def test_two_swamps_are_paid_whole_or_not_at_all(interactive, swamps, left):
    game, denizen = _table(swamps, interactive)
    game.resolve_upkeep(0)
    settle(game)
    assert _swamps(game) == left, game.log[-6:]
    swamp_cards = sum(1 for card in game.players[0].graveyard if card.name == "Swamp")
    assert swamp_cards == swamps - left
    # The penalty follows exactly the case the cost could not be paid in.
    assert denizen.tapped is (swamps < 2), game.log[-6:]
