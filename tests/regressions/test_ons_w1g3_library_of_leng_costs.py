"""Library of Leng redirects a discard an **effect** causes, never a cost.

"If an effect causes you to discard a card, discard it, but you may put it on
top of your library instead of into your graveyard." Ruling, 2004-10-04: "You
can't use the Library of Leng ability to place a discarded card on top of your
library when you discard a card as a cost, because costs aren't effects."

The engine applied it to every discard. With the Library out, a cycled card
went on top of its owner's library and the cycling ability's draw brought it
straight back — and ONS's "when you cycle this card" triggers turned that into
a loop (found by ONS W1G3: Renewed Faith gained 2 life for {1}{W} and stayed
in hand). The cost sites now pass ``as_cost`` (``tests/engine/
test_discard_cost_seam.py``); an effect's discard is still offered.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState

from tests.helpers import resolve_stack


def _catalog():
    found = getattr(_catalog, "_cache", None)
    if found is None:
        found = {card.name: card for card in load_catalog()}
        _catalog._cache = found
    return found


def _leng_table(set_pool, *hand):
    ons = set_pool("ONS")
    pool = {**_catalog(), **ons}
    alice = PlayerState(
        name="Alice", hand=[pool[name] for name in hand], library=[ons["Plains"]] * 5,
    )
    bob = PlayerState(name="Bob", library=[ons["Plains"]] * 5)
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    leng = Permanent(card=_catalog()["Library of Leng"])
    game._put_permanent_onto_battlefield(0, leng, None)
    game._sync_control()
    return game, alice, bob


def test_a_cycled_card_goes_to_the_graveyard_under_library_of_leng(set_pool):
    game, alice, _bob = _leng_table(set_pool, "Renewed Faith")

    assert game.activate_from_hand(0, "Renewed Faith").supported
    assert [c.name for c in alice.graveyard] == ["Renewed Faith"]
    assert [c.name for c in alice.library] == ["Plains"] * 5
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Plains"], "it drew a new card"
    assert not any("Library of Leng" in line for line in game.log)


def test_a_discard_cost_on_a_permanent_is_not_redirected_either(set_pool):
    """Wild Mongrel's "Discard a card:" — a cost on the battlefield path."""
    game, alice, _bob = _leng_table(set_pool, "Lay Waste")
    mongrel = Permanent(card=_catalog()["Wild Mongrel"])
    game._put_permanent_onto_battlefield(0, mongrel, None)
    mongrel.metadata["summoning_sickness_turn"] = -99
    game._sync_control()

    assert game.activate_permanent_ability(0, "Wild Mongrel", cost_hand_index=0).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.graveyard] == ["Lay Waste"]
    assert [c.name for c in alice.library] == ["Plains"] * 5


def test_a_discard_an_effect_causes_is_still_offered_to_the_library(set_pool):
    """Hymn to Tourach's "Target player discards two cards at random" is an
    effect: the Library still applies, offering each card its top. A seat
    nobody asks answers each as ``ai_prompt_picks.takes_library_top`` does
    (kg5): the six life of Renewed Faith goes back on top, a Lay Waste with
    no land of the opponent's to destroy is let go to the graveyard."""
    from engine.ai_prompt_picks import takes_library_top

    game, alice, bob = _leng_table(set_pool, "Lay Waste", "Renewed Faith")
    bob.hand.append(_catalog()["Hymn to Tourach"])
    kept = {
        name: takes_library_top(game, 0, _catalog()[name])
        for name in ("Lay Waste", "Renewed Faith")
    }

    assert game.queue_from_hand(1, "Hymn to Tourach", target_player_index=0).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    assert alice.hand == [], game.log
    assert kept["Renewed Faith"], kept
    for name, top in kept.items():
        where = alice.library[:2] if top else alice.graveyard
        assert name in [c.name for c in where], (name, top, game.log)
    # Each card was offered: taken, the line names the Library; declined,
    # the card is put into the graveyard by the Library's own answer.
    assert any(
        "on top of their library (Library of Leng)" in line for line in game.log
    ), game.log
    assert sum("put discarded" in line for line in game.log) == 2, game.log
