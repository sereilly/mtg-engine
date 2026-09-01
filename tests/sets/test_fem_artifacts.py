"""Per-card tests for Fallen Empires' artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G2: self-clocks, delayed self-sacrifice and card-flow order ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent


def _g2_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _g2_artifact_game(card, *, hand, library, opponent_hand=()):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    player = PlayerState(
        name="P1", battlefield=[permanent], hand=list(hand), library=list(library)
    )
    opponent = PlayerState(name="P2", hand=list(opponent_hand))
    game = Game(players=[player, opponent])
    game.enforce_mana_costs = False
    game._settle()
    return game, player, opponent, permanent


def _g2_use(game, name):
    result = game.activate_permanent_ability(0, name, permanent_index=0)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return result


def test_conch_horn_draws_two_then_puts_one_back_on_top(set_pool):
    """"{1}, {T}, Sacrifice this artifact: Draw two cards, then put a card from
    your hand on top of your library."

    The order is the card. Drawing first is what makes the choice worth
    anything, and the card put back is one *chosen* from the hand -- so the
    hand is up one card, the library is down one, and the chosen card is on
    top. No "in any order" is printed because one card has none to give.
    """
    lea = _g2_lea()
    game, player, _opponent, horn = _g2_artifact_game(
        set_pool("FEM")["Conch Horn"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    result = _g2_use(game, "Conch Horn")

    assert result.supported, result.details
    assert sorted(card.name for card in player.hand) == [
        "Black Lotus", "Forest", "Mountain",
    ]
    assert [c.kind for c in game.pending_choices] == ["hand_to_library"]

    lotus_slot = [card.name for card in player.hand].index("Black Lotus")
    assert game.confirm_hand_to_library(0, [lotus_slot]) is True
    game._settle()

    assert sorted(card.name for card in player.hand) == ["Forest", "Mountain"]
    assert player.library[0].name == "Black Lotus"
    assert len(player.library) == 2


def test_conch_horn_is_sacrificed_as_a_cost_and_still_resolves(set_pool):
    """"Sacrifice this artifact" is part of the activation cost (CR 601.2h), so
    the Horn is in the graveyard before its ability resolves -- and the ability
    resolves anyway."""
    lea = _g2_lea()
    game, player, _opponent, _horn = _g2_artifact_game(
        set_pool("FEM")["Conch Horn"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    _g2_use(game, "Conch Horn")

    assert [p.card.name for p in player.battlefield] == []
    assert "Conch Horn" in [card.name for card in player.graveyard]
    assert len(player.hand) == 3


def test_ring_of_renewal_discards_its_own_controllers_card_at_random(set_pool):
    """"{5}, {T}: Discard a card at random, then draw two cards."

    The sentence names no target, so CR 608.2's unwritten subject is the
    ability's controller -- and the *sampling* discard handler reads a targeted
    seat by default, which for an activation nobody targeted with is the
    opponent. The opponent's hand is the assertion that matters here.
    """
    lea = _g2_lea()
    game, player, opponent, ring = _g2_artifact_game(
        set_pool("FEM")["Ring of Renewal"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
        opponent_hand=[lea["Healing Salve"], lea["Ancestral Recall"]],
    )

    result = _g2_use(game, "Ring of Renewal")

    assert result.supported, result.details
    assert [card.name for card in player.graveyard] == ["Black Lotus"]
    assert sorted(card.name for card in opponent.hand) == [
        "Ancestral Recall", "Healing Salve",
    ]
    assert opponent.graveyard == []
    assert ring.tapped is True


def test_ring_of_renewal_discards_before_it_draws(set_pool):
    """"Discard a card at random, **then** draw two cards." The order decides
    which cards the sample could have taken: run the other way round, a card
    just drawn could be pitched, which is a different card.

    With exactly one card in hand the sample has one candidate, so the discard
    is knowable -- and the two drawn cards are still in hand afterwards.
    """
    lea = _g2_lea()
    game, player, _opponent, _ring = _g2_artifact_game(
        set_pool("FEM")["Ring of Renewal"],
        hand=[lea["Black Lotus"]],
        library=[lea["Mountain"], lea["Forest"], lea["Island"]],
    )

    _g2_use(game, "Ring of Renewal")

    assert [card.name for card in player.graveyard] == ["Black Lotus"]
    assert sorted(card.name for card in player.hand) == ["Forest", "Mountain"]
    assert len(player.library) == 1
