"""Regressions: a graveyard target is a slot, and a slot is not an identity.

``Game._stack_push`` stamps a stable ``permanent_id`` for a battlefield target
because "a stack object is the engine's only structure that outlives the moment
it was built" — its own docstring. A card in a **graveyard** had no such stamp:
``load_cards`` dedupes by ``oracle_id``, so two copies of one card are literally
one ``CardDefinition`` and neither an id nor ``is`` separates them. Resolution
therefore re-read a raw index against a list that had since shifted.

Three separate defects came out of that one gap, all measured on the shipped
pool before the fix:

* Raise Dead named Grizzly Bears, one card left the graveyard in response, and
  it returned **Hill Giant**.
* Reconstruction was **uncastable**: its picker offered artifact cards while its
  cast-time re-check demanded a creature, so the only card a player could name
  was one the check refused.
* A spell targeting a *graveyard* card asked a protection question about
  ``battlefield[slot]`` — so a White Knight the spell never targeted refused
  Raise Dead.

The identity is a card plus which copy of it. The residual is stated rather than
hidden: with two copies of one card the engine cannot know which one left, so the
read clamps to the last surviving copy and reports "gone" only when none remain.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState

_CATALOG = {c.name: c for c in load_catalog()}


def _duel(**p1_kwargs):
    p1 = PlayerState(name="P1", **p1_kwargs)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1


def test_a_graveyard_target_survives_another_card_leaving_the_pile():
    """The announcement named a card, not a position (CR 601.2c)."""
    game, p1 = _duel(
        hand=[_CATALOG["Raise Dead"]],
        graveyard=[
            _CATALOG["Scryb Sprites"],
            _CATALOG["Grizzly Bears"],
            _CATALOG["Hill Giant"],
        ],
    )

    game.queue_from_hand(0, "Raise Dead", target_player_index=0, target_permanent_index=1)
    p1.graveyard.pop(0)          # something else leaves while the spell waits
    game._settle()

    assert [c.name for c in p1.hand] == ["Grizzly Bears"], (
        "the slot shifted down one; the card it named did not change"
    )


def test_several_graveyard_targets_survive_the_same_shift():
    """The several-card path had it worse — it returned one card of the two."""
    m21 = load_catalog()  # Sanguine Indulgence is measured, so build it by hand
    del m21
    from engine.card_loader import load_cards, manifest_set_path

    pool = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}
    game, p1 = _duel(
        hand=[pool["Sanguine Indulgence"]],
        graveyard=[
            _CATALOG["Scryb Sprites"],
            _CATALOG["Grizzly Bears"],
            _CATALOG["Hill Giant"],
        ],
    )

    game.queue_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[1, 2]
    )
    p1.graveyard.pop(0)
    game._settle()

    assert sorted(c.name for c in p1.hand) == ["Grizzly Bears", "Hill Giant"]


def test_reconstruction_can_be_cast_on_the_artifact_it_offers():
    """The picker and the cast-time re-check asked different questions, so the
    only card a player could name was one the check then refused. A shipped card
    that could not be played at all."""
    game, p1 = _duel(
        hand=[_CATALOG["Reconstruction"]], graveyard=[_CATALOG["Black Lotus"]]
    )

    spec = game.cast_target_spec(0, _CATALOG["Reconstruction"])
    offered = [t.get("name") for t in (spec.get("valid_targets") or [])]
    result = game.cast_from_hand(
        0, "Reconstruction", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert offered == ["Black Lotus"]
    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Black Lotus"], "what it offered, it returns"


def test_a_protection_check_does_not_read_a_battlefield_slot_for_a_graveyard_target():
    """Raise Dead targets a card in a graveyard, so no permanent's protection has
    anything to say about it — but the check indexed ``battlefield[slot]`` without
    asking which zone the slot belonged to, and slot 0 was a White Knight."""
    knight = Permanent(card=_CATALOG["White Knight"])
    game, p1 = _duel(
        hand=[_CATALOG["Raise Dead"]],
        graveyard=[_CATALOG["Grizzly Bears"]],
        battlefield=[knight],
    )

    result = game.cast_from_hand(
        0, "Raise Dead", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Grizzly Bears"]
