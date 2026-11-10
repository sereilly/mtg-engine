"""A permanent's mana value is the cost it *has*: a copy's, a face-down one's.

CR 707.2: a copy's copiable values — its mana cost among them — are the copied
object's, so a Clone that is a Craw Wurm has mana value 6. CR 708.2a: a
face-down permanent has no mana cost, so its mana value is 0. And CR 608.2h:
an object an effect asks about after it has left (sacrificed for a cost,
returned to a hand) answers with its last known information — the permanent as
it last existed on the battlefield, which is what the departed ``Permanent``
the resolution holds still says (its copy effect stays on it; a face-down one
reads its face-down values, ``copies.FACE_DOWN_AS_IT_LEFT``, although its card
is the revealed one).

Four readers read the printed card instead (round kg5's census of every
``handlers/_amounts`` read of a permanent's characteristic, and of the two
sibling readers outside it):

* ``_amounts``' sacrificed-for-a-cost mana value (Bosh, Iron Golem; Burnt
  Offering; Faith Healer; Forge Armor; Homarid Spawning Bed; Metamorphosis)
  read ``sacrificed.card`` — so a sacrificed Clone of a Craw Wurm paid 4, and a
  face-down Exalted Angel paid **6**: three mana to cast face down, six back.
  The tapped-for-a-cost read beside it had the same shape (no card prints it
  with mana value yet);
* ``_amounts._characteristic_of_object`` (Subdue, Kry Shield, Monkey Cage, …)
  read ``perm.card`` for the targeted, source or attached permanent;
* ``returns._mana_value_of`` (Aether Mutation) read the returned permanent's
  printed card, on the claim that a departed object has no layers;
* ``permanent_choices._SUPERLATIVE_READS`` (Juxtapose's "highest mana value"),
  a defect its own docstring reported and left.

Power and toughness were already read through the layers on every one of these
channels. Backwards on the base (59f133e63) every test below fails.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.face_down import turn_face_down
from engine.models import Permanent
from tests.helpers import settle

_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _table(hand=(), mine=(), theirs=()):
    game = Game(players=[
        PlayerState("A", library=[_POOL["Forest"]] * 10, hand=[_POOL[n] for n in hand]),
        PlayerState("B", library=[_POOL["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed[0], placed[1]


def _copy_of(game, copier: str, original, seat: int = 0):
    """*copier* (Clone, Copy Artifact) cast from *seat*'s hand copying
    *original*, settled; the copy."""
    game.players[seat].hand.append(_POOL[copier])
    result = game.queue_from_hand(seat, copier, target_permanent_ids=[original.permanent_id])
    assert result.supported, result.details
    settle(game)
    copy = next(p for p in game.controlled_by(seat) if p.card.name == copier)
    assert copy.effective_card.name == original.card.name
    return copy


def _mana_made(game, spell: str) -> int:
    """How much mana *spell*'s production line logged."""
    line = next(line for line in reversed(game.log) if line.startswith(f"{spell} produced "))
    return line.split(" produced ", 1)[1].split(" ")[0].count("{")


# --- sacrificed for a cost ---------------------------------------------------


def test_kg5_layers_burnt_offering_sacrificing_a_clone_pays_the_copied_mana_value():
    game, (wurm,), _ = _table(hand=["Burnt Offering"], mine=["Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)
    assert clone.card.cmc == 4 and clone.effective_card.cmc == 6

    result = game.queue_from_hand(0, "Burnt Offering", cost_permanent_ids=[clone.permanent_id])
    assert result.supported, result.details
    settle(game)

    assert not game.is_on_battlefield(clone)
    pool = game.players[0].mana_pool
    assert pool["B"] + pool["R"] == 6, pool


def test_kg5_layers_burnt_offering_sacrificing_a_face_down_creature_pays_nothing():
    game, (angel,), _ = _table(hand=["Burnt Offering"], mine=["Exalted Angel"])
    assert turn_face_down(game, angel)

    result = game.queue_from_hand(0, "Burnt Offering", cost_permanent_ids=[angel.permanent_id])
    assert result.supported, result.details
    settle(game)

    # It left revealed (CR 708.9) — and paid as the 2/2 with no cost it was.
    assert any("it is Exalted Angel" in line for line in game.log)
    pool = game.players[0].mana_pool
    assert pool["B"] + pool["R"] == 0, pool


def test_kg5_layers_metamorphosis_counts_a_sacrificed_clone_as_what_it_copied():
    game, (wurm,), _ = _table(hand=["Metamorphosis"], mine=["Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)
    result = game.queue_from_hand(0, "Metamorphosis", cost_permanent_ids=[clone.permanent_id])
    assert result.supported, result.details
    settle(game)
    assert _mana_made(game, "Metamorphosis") == 7  # its mana value plus one


def test_kg5_layers_an_activated_sacrifice_reads_the_copy_too():
    """Bosh (an artifact) and Faith Healer (an enchantment) eating one Copy
    Artifact that is a Jayemdae Tome: mana value 4, not Copy Artifact's 2."""
    game, (bosh, tome), (_,) = _table(mine=["Bosh, Iron Golem", "Jayemdae Tome"], theirs=["Craw Wurm"])
    copy = _copy_of(game, "Copy Artifact", tome)
    life = game.players[1].life
    result = game.activate_permanent_ability(
        0, "Bosh, Iron Golem", target_player_index=1, cost_permanent_ids=[copy.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    assert game.players[1].life == life - 4

    game, (healer, tome), _ = _table(mine=["Faith Healer", "Jayemdae Tome"])
    copy = _copy_of(game, "Copy Artifact", tome)
    life = game.players[0].life
    result = game.activate_permanent_ability(
        0, "Faith Healer", cost_permanent_ids=[copy.permanent_id],
    )
    assert result.supported, result.details
    settle(game)
    assert game.players[0].life == life + 4


# --- a permanent the effect names ---------------------------------------------


def test_kg5_layers_subdue_on_a_clone_reads_the_copied_mana_value():
    game, (wurm,), _ = _table(hand=["Subdue"], mine=["Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)
    result = game.queue_from_hand(0, "Subdue", target_permanent_ids=[clone.permanent_id])
    assert result.supported, result.details
    settle(game)
    assert clone.effective_toughness == 4 + 6


def test_kg5_layers_aether_mutation_returning_a_clone_counts_the_copy():
    game, (wurm,), _ = _table(hand=["Aether Mutation"], mine=["Craw Wurm"])
    clone = _copy_of(game, "Clone", wurm)
    result = game.queue_from_hand(0, "Aether Mutation", target_permanent_ids=[clone.permanent_id])
    assert result.supported, result.details
    settle(game)
    assert any(c.name == "Clone" for c in game.players[0].hand)
    assert sum(1 for p in game.controlled_by(0) if p.metadata.get("is_token")) == 6


def test_kg5_layers_aether_mutation_returning_a_face_down_creature_counts_nothing():
    game, (angel,), _ = _table(hand=["Aether Mutation"], mine=["Exalted Angel"])
    assert turn_face_down(game, angel)
    result = game.queue_from_hand(0, "Aether Mutation", target_permanent_ids=[angel.permanent_id])
    assert result.supported, result.details
    settle(game)
    assert any(c.name == "Exalted Angel" for c in game.players[0].hand)
    assert sum(1 for p in game.controlled_by(0) if p.metadata.get("is_token")) == 0


def test_kg5_layers_juxtapose_weighs_a_clone_at_the_copied_mana_value():
    """"…exchange control of the creature you each control with the highest
    mana value." A Clone that is a Craw Wurm (6) outranks an Air Elemental
    (5); read off the printed card it was a 4, and the Elemental went."""
    game, (wurm, elemental), (bears,) = _table(
        hand=["Juxtapose"], mine=["Craw Wurm", "Air Elemental"], theirs=["Grizzly Bears"],
    )
    clone = _copy_of(game, "Clone", wurm)
    # The Wurm itself is the highest; take it off the table so the copy is.
    game.remove_from_battlefield(wurm)
    game._sync_control()
    result = game.queue_from_hand(0, "Juxtapose", target_player_index=1)
    assert result.supported, result.details
    settle(game)
    assert game.controller_index_of(clone) == 1
    assert game.controller_index_of(elemental) == 0
    assert game.controller_index_of(bears) == 0
