"""CR 613.1d: what a permanent *is* is layer 4's answer, not the first word of
the type line it was printed with.

``CardDefinition.primary_type`` is the printed line collapsed to one word —
the first of land / creature / artifact / enchantment … that appears. Asked of
a permanent it is wrong twice over: no type an effect gave it is there (an
animated land is not a creature, a Clone that copied one is not a land), and
an Artifact Creature answers only "creature". Forty-three sites outside the
AI's policy read it off a permanent or a stack object; thirty-seven of them
meant the permanent and ask ``has_type`` / ``is_creature`` now. One test here
for the first of each shape — and the shape that was live on an ordinary
board is the first one.

The six that stay, and the eight in ``ai_policy.py`` nobody has asked yet, are
in ``tests/engine/test_layer_reads.py``'s ``PRIMARY_TYPE_BASELINE`` with what
each means.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import auras_attached_to
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack

_ENCHANT_ARTIFACT = re.compile(r"^enchant artifact\b", re.I | re.M)


@pytest.fixture(scope="module")
def _by_name():
    catalog = load_catalog()
    named = {card.name: card for card in catalog}
    named.update({unit.name: unit for unit in compilation_units(catalog)})
    return named


def _new_game(by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, by_name, name, seat=0):
    permanent = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._recompute_continuous_effects()
    return permanent


def _cast(game, by_name, name, target=None, seat=0, **announced) -> bool:
    card = whole_card(by_name[name])
    game.players[seat].hand.append(card)
    if target is not None:
        announced["target_permanent_ids"] = [target.permanent_id]
    result = game.cast_from_hand(seat, name, **announced)
    if not result.supported:
        if any(held is card for held in game.players[seat].hand):
            game.take_card_from_hand(game.players[seat], card)
        return False
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()
    return True


# --- an Aura's host, by the whole type line ------------------------------


@pytest.mark.cr("303.4a", "702.5a", "205.2b")
def test_an_enchant_artifact_aura_goes_onto_an_artifact_creature(_by_name):
    """An Artifact Creature is an artifact (CR 205.2b: an object with more
    than one card type is each of them). The cast accepted a Juggernaut as an
    "Enchant artifact" Aura's target; the resolution asked the collapsed
    printed word, got "creature", and put the Aura into the graveyard."""
    game = _new_game(_by_name)
    juggernaut = _put(game, _by_name, "Juggernaut")
    assert juggernaut.card.primary_type == "creature"
    assert _cast(game, _by_name, "Power Artifact", juggernaut)

    assert [aura.card.name for aura in auras_attached_to(juggernaut)] == [
        "Power Artifact"
    ]
    assert not any(card.name == "Power Artifact" for card in game.players[0].graveyard)


@pytest.mark.cr("303.4a", "702.5a")
def test_every_enchant_artifact_aura_in_the_pool_can_enchant_an_artifact_creature(
    _by_name,
):
    """The census for that shape: each Aura printing "Enchant artifact", cast
    at an artifact creature on whichever seat it may be aimed at. Measured on
    the tree before: none of them stayed on the battlefield."""
    auras = sorted(
        unit.name for unit in compilation_units(_by_name.values())
        if "aura" in unit.type_line.lower()
        and _ENCHANT_ARTIFACT.search(unit.oracle_text or "")
    )
    attached, binned = [], []
    for name in auras:
        for host_seat in (0, 1):
            game = _new_game(_by_name)
            host = _put(game, _by_name, "Juggernaut", host_seat)
            if not _cast(game, _by_name, name, host):
                continue
            (attached if auras_attached_to(host) else binned).append(name)
            break
    # The floor: a sweep that casts nothing passes.
    assert len(auras) >= 8, auras
    assert len(attached) >= 8, (attached, binned)
    assert binned == []


# --- "is a creature", of a permanent an effect made one -------------------


@pytest.mark.cr("613.1d", "502.3")
def test_an_aura_that_keeps_a_creature_tapped_holds_an_animated_land(_by_name):
    """"Enchanted creature doesn't untap during its controller's untap step."
    (Paralyze.) On a Forest that Living Lands has made a creature, the untap
    step asked the printed word — "land" — and untapped it."""
    game = _new_game(_by_name)
    forest = _put(game, _by_name, "Forest")
    _put(game, _by_name, "Living Lands")
    assert forest.is_creature and forest.card.primary_type == "land"
    assert _cast(game, _by_name, "Paralyze", forest)
    assert forest.tapped

    game.resolve_untap_step(0)
    assert forest.tapped

    # A Forest nothing holds untaps, on the same board.
    other = _put(game, _by_name, "Forest")
    other.tapped = True
    game.resolve_untap_step(0)
    assert not other.tapped
    assert forest.tapped


@pytest.mark.cr("613.1d", "701.21a")
def test_balance_counts_an_animated_land_among_the_creatures(_by_name):
    """"…each player chooses a number of creatures they control equal to the
    number of creatures controlled by the player who controls the fewest,
    then sacrifices the rest." A Mishra's Factory that is a creature this
    turn is one of them; counted by its printed word it was only a land, and
    its controller kept a creature the opponent's empty board said to lose."""
    game = _new_game(_by_name)
    factory = _put(game, _by_name, "Mishra's Factory")
    _put(game, _by_name, "Forest", 1)
    result = game.activate_permanent_ability(
        0, "Mishra's Factory",
        permanent_index=game.battlefield_index_of(factory), ability_index=1,
    )
    assert result.supported, result
    game._recompute_continuous_effects()
    assert factory.is_creature and factory.has_type("land")

    assert _cast(game, _by_name, "Balance")
    assert not game.is_on_battlefield(factory)
    assert [p.card.name for p in game.controlled_by(1)] == ["Forest"]


# --- "is a land", of a permanent that is not printed as one ---------------


@pytest.mark.cr("613.1d", "707.2")
def test_untap_target_land_reaches_a_clone_that_is_a_forest(_by_name):
    """A Clone that copied a Forest Living Lands had animated is a Forest
    (CR 707.2) on a card printed "Creature — Shapeshifter". "{T}: Untap target
    land." (Ley Druid) accepted it as a target and then asked the printed
    word: "No land to untap"."""
    game = _new_game(_by_name)
    forest = _put(game, _by_name, "Forest")
    _put(game, _by_name, "Living Lands")
    assert _cast(game, _by_name, "Clone", forest)
    clone = next(p for p in game.controlled_by(0) if p.card.name == "Clone")
    assert clone.has_type("land") and clone.card.primary_type == "creature"
    druid = _put(game, _by_name, "Ley Druid")
    clone.tapped = True

    result = game.activate_permanent_ability(
        0, "Ley Druid", permanent_index=game.battlefield_index_of(druid),
        target_permanent_ids=[clone.permanent_id],
    )
    assert result.supported, result
    assert druid.tapped
    assert not clone.tapped
