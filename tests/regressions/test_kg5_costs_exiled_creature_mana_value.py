"""What a cost ate is read **as it last existed** — and goes where it went.

"Exile a creature you control: Add X mana of any one color, where X is 1 plus
**the exiled creature's** mana value." (Food Chain.) The creature is gone
before the ability resolves, so its mana value is its last known information
(CR 608.2h) — the creature's, not its card's: a Clone that was a Craw Wurm is
6 (CR 707.2), a face-down creature 0 (CR 708.2a). The rulings on the
sacrifice twins say so outright: "Use the sacrificed creature's power as it
last existed on the battlefield" (Fling, 2024-04-12); "A token that is a copy
or a creature that has become a copy of another permanent has the mana value
of what it's copying" (Eldritch Evolution, 2016-07-13).

On the base of round kg5 wave 2 (e245e624c), each test here fails:

* the activation's exile cost recorded the exiled **card**
  (``activation_charges._pay_exile_cost``), so Food Chain counted a Clone at
  its printed 4;
* ``sacrifice_creature_for_mana`` (Sacrifice, Priest of Yawgmoth, Soldevi
  Adnate) read the sacrificed permanent's printed card — the read kg5's
  ``layers`` fixed in ``_amounts`` and this handler kept: a Copy Artifact that
  was a Juggernaut paid two, a face-down Exalted Angel six;
* and both exile costs (the activation's, and the cast's for Soul Exchange)
  read the permanent's card *before* removing it, so a face-down creature's
  stand-in went into exile and the creature card was never seen again
  (CR 708.9: it is revealed as it leaves). Food Chain's "0" for it was that
  accident.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.face_down import turn_face_down
from engine.models import Permanent
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}


def _table(hand=(), mine=(), graveyard=()):
    game = Game(players=[
        PlayerState("A", library=[_POOL["Forest"]] * 10,
                    hand=[_POOL[n] for n in hand],
                    graveyard=[_POOL[n] for n in graveyard]),
        PlayerState("B", library=[_POOL["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = []
    for name in mine:
        permanent = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed


def _copy_of(game, copier: str, original):
    game.players[0].hand.append(_POOL[copier])
    result = game.queue_from_hand(0, copier, target_permanent_ids=[original.permanent_id])
    assert result.supported, result.details
    settle(game)
    copy = next(p for p in game.controlled_by(0) if p.card.name == copier)
    assert copy.effective_card.name == original.card.name
    return copy


def _creature_mana(game) -> int:
    return sum((game.players[0].restricted_mana.get("creature") or {}).values())


def _exiled(game) -> list[str]:
    return [card.name for card in game.players[0].exile]


# --- Food Chain: an activation's exile cost ----------------------------------


def test_food_chain_counts_an_exiled_clone_as_what_it_copied():
    game, (_chain, wurm) = _table(mine=["Food Chain", "Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)
    assert clone.card.cmc == 4 and clone.effective_card.cmc == 6

    result = game.activate_permanent_ability(
        0, "Food Chain", mana_color="G", cost_permanent_ids=[clone.permanent_id],
    )

    assert result.supported, result.details
    assert _exiled(game) == ["Clone"]
    assert _creature_mana(game) == 7


def test_food_chain_counts_a_face_down_creature_as_nothing_and_exiles_its_card():
    game, (_chain, angel) = _table(mine=["Food Chain", "Exalted Angel"])
    assert turn_face_down(game, angel)

    result = game.activate_permanent_ability(
        0, "Food Chain", mana_color="G", cost_permanent_ids=[angel.permanent_id],
    )

    assert result.supported, result.details
    assert _creature_mana(game) == 1
    # Revealed as it left (CR 708.9), and the card in exile is the Angel.
    assert any("it is Exalted Angel" in line for line in game.log)
    assert _exiled(game) == ["Exalted Angel"]


def test_city_of_shadows_exiles_a_face_down_creature_s_own_card():
    game, (_city, angel) = _table(mine=["City of Shadows", "Exalted Angel"])
    assert turn_face_down(game, angel)

    result = game.activate_permanent_ability(
        0, "City of Shadows", cost_permanent_ids=[angel.permanent_id],
    )
    assert result.supported, result.details
    settle(game)

    assert _exiled(game) == ["Exalted Angel"]


def test_necropolis_still_reads_the_exiled_card_s_printed_mana_value():
    """The zone exile is a card, which is all it ever was (CR 202.3)."""
    game, (necropolis,) = _table(mine=["Necropolis"], graveyard=["Craw Wurm"])

    result = game.activate_permanent_ability(0, "Necropolis")
    assert result.supported, result.details
    settle(game)

    assert _exiled(game) == ["Craw Wurm"]
    assert necropolis.effective_toughness == 1 + 6


# --- a cast's exile cost -----------------------------------------------------


def test_soul_exchange_exiles_a_face_down_creature_s_own_card():
    game, (angel,) = _table(
        hand=["Soul Exchange"], mine=["Exalted Angel"], graveyard=["Grizzly Bears"],
    )
    assert turn_face_down(game, angel)

    result = game.queue_from_hand(
        0, "Soul Exchange", cost_permanent_ids=[angel.permanent_id],
    )
    assert result.supported, result.details
    settle(game)

    assert _exiled(game) == ["Exalted Angel"]
    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))


# --- the sacrifice-for-mana handler ------------------------------------------


def test_sacrifice_pays_a_sacrificed_clone_s_copied_mana_value():
    game, (wurm,) = _table(hand=["Sacrifice"], mine=["Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)

    result = game.queue_from_hand(0, "Sacrifice", cost_permanent_ids=[clone.permanent_id])
    assert result.supported, result.details
    settle(game)

    assert game.players[0].mana_pool["B"] == 6


def test_sacrifice_pays_nothing_for_a_face_down_creature():
    game, (angel,) = _table(hand=["Sacrifice"], mine=["Exalted Angel"])
    assert turn_face_down(game, angel)

    result = game.queue_from_hand(0, "Sacrifice", cost_permanent_ids=[angel.permanent_id])
    assert result.supported, result.details
    settle(game)

    assert game.players[0].mana_pool["B"] == 0


def test_priest_of_yawgmoth_pays_a_copy_artifact_s_copied_mana_value():
    game, (_priest, juggernaut) = _table(mine=["Priest of Yawgmoth", "Juggernaut"])
    copy = _copy_of(game, "Copy Artifact", juggernaut)

    result = game.activate_permanent_ability(
        0, "Priest of Yawgmoth", cost_permanent_ids=[copy.permanent_id],
    )
    assert result.supported, result.details
    settle(game)

    assert game.players[0].mana_pool["B"] == 4
