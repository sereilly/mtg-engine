"""CR 608.2b for an **activated ability** whose target was a card in a
graveyard: if the card has left by the time the ability resolves, the ability
does not resolve. It does not find another card.

"A target that's no longer in the zone it was in when it was targeted is
illegal. … If all its targets, for every instance of the word 'target', are
now illegal, the spell or ability doesn't resolve."

A spell has had this since the stamp (``GraveyardTarget``) existed:
``legality.illegal_targets_refusal`` reads a stamp with no surviving copy as a
target that is gone. An ability never reached that gate, and its resolution
re-located the vanished stamp to *no index* — exactly what a bare, headless
activation carries — so every graveyard handler took its own pick: exile the
creature card Adun Oakenshield was activated at in response, and it returned
the creature card beside it. W1G3 fixed which cards that fallback may take
(``test_narrowed_graveyard_return_keeps_its_narrowing.py``) and left the
fallback itself.

``legality.vanished_graveyard_target_refusal`` is the gate, asked above the
instructions. The sweep drives every activated ability in the pool whose
picker is a graveyard card: announce the first card the picker offers, take
that card out of the graveyard in response, resolve, and require that no zone
moved.

Measured on the tree before this file (33 such abilities in the pool, 26 of
which reach a resolution on the sweep's board): **19 of 26** acted on a card
nobody named, or carried on with the sentence behind the target. 0 here.

The ambiguity ROADMAP records is left alone on purpose and is held below: two
copies of one card in one pile are one ``CardDefinition``, so while a copy
survives the target is legal and the ability resolves on it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compiled_units
from engine.targeting import (
    GRAVEYARD_TARGET_KIND, derive_activation_spec, spec_is_a_cost,
    usable_activated_abilities,
)
from tests.helpers import _nosick, resolve_stack

#: Two different cards of each printed type in every pile, so that with the
#: named card gone another card answering the same phrase is still there for a
#: fallback to take — on a pile holding one of each, the defect has nothing to
#: act on and the sweep passes on any tree.
_PILE = (
    "Grizzly Bears", "Hill Giant", "Scathe Zombies", "Lightning Bolt", "Shock",
    "Fireball", "Sol Ring", "Ornithopter", "Island", "Forest", "Swamp",
    "Crusade", "Wild Growth", "Giant Growth", "Counterspell",
)


@pytest.fixture(scope="module")
def _catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def _by_name(_catalog):
    return {card.name: card for card in _catalog}


def _graveyard_abilities(catalog, only=None):
    """Every supported activated ability whose target is a card in a
    graveyard — ``(card, index)``."""
    for card, program in compiled_units(catalog):
        if not program.supported or (only is not None and card.name not in only):
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            spec = derive_activation_spec(ability)
            if spec is None or spec.get("kind") != GRAVEYARD_TARGET_KIND:
                continue
            if spec_is_a_cost(spec):
                continue
            yield card, index


def _board(card, by_name):
    # Nothing a cost could put into a graveyard — a sacrificed creature, a
    # discarded card, a milled one — is a card the piles already hold: a
    # second copy of the named card arriving there would keep the target
    # legal (see ``test_a_surviving_copy_keeps_the_target_legal``), and the
    # sweep would be measuring that instead.
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Plains"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    _nosick(source)
    for seat in (0, 1):
        for name in ("Gray Ogre", "Mountain"):
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
        game.players[seat].graveyard.extend(by_name[name] for name in _PILE)
        game.players[seat].hand.extend([by_name["Plains"], by_name["Mountain"]])
    return game, source


def _zones(game) -> tuple:
    return (
        tuple(tuple(card.name for card in player.graveyard) for player in game.players),
        tuple(tuple(card.name for card in player.hand) for player in game.players),
        tuple(tuple(card.name for card in player.exile) for player in game.players),
        tuple(len(player.library) for player in game.players),
        tuple(sorted(perm.card.name for perm in game.all_permanents())),
        tuple(player.life for player in game.players),
    )


def _sweep(catalog, by_name, only=None):
    """``(examined, acted)``: every ability announced at the first graveyard
    card its picker offers, that card removed in response, then resolved.
    *acted* lists the abilities after which any zone had moved."""
    examined = 0
    acted: list[tuple] = []
    for card, index in _graveyard_abilities(catalog, only):
        game, source = _board(card, by_name)
        if not game.is_on_battlefield(source):
            continue
        slot = game.battlefield_index_of(source)
        spec = game.activation_target_spec(0, slot, ability_index=index)
        offered = [
            entry for entry in spec.get("valid_targets") or ()
            if entry.get("kind") == "graveyard"
        ]
        if not offered:
            continue
        seat, pile_slot = offered[0]["seat"], offered[0]["index"]
        named = game.players[seat].graveyard[pile_slot]
        result = game.queue_permanent_ability(
            0, card.name, permanent_index=slot, ability_index=index,
            target_player_index=seat, target_permanent_index=pile_slot,
        )
        if not result.supported or not game.stack:
            continue
        # In response, the named card leaves its graveyard (a Scavenging Ooze,
        # a Tormod's Crypt). By identity: the cost may have added to the pile.
        pile = game.players[seat].graveyard
        position = next(
            (i for i, held in enumerate(pile) if held is named), None,
        )
        if position is None:
            continue
        game.players[seat].exile.append(pile.pop(position))
        before = _zones(game)
        resolve_stack(game)
        examined += 1
        if _zones(game) != before:
            acted.append((f"{card.name}[{index}]", named.name))
    return examined, acted


def test_no_activated_ability_acts_after_its_graveyard_target_has_left(
    _catalog, _by_name
):
    examined, acted = _sweep(_catalog, _by_name)

    assert examined >= 22, f"only {examined} abilities driven"
    assert acted == [], (
        "CR 608.2b: the named graveyard card was gone and the ability acted "
        f"anyway: {acted}"
    )


def test_the_sweep_finds_the_fallback_with_the_gate_switched_off(
    _catalog, _by_name, monkeypatch
):
    only = frozenset({"Adun Oakenshield", "Scavenging Ooze", "Hell's Caretaker"})
    assert _sweep(_catalog, _by_name, only=only)[1] == []

    monkeypatch.setattr(
        Game, "vanished_graveyard_target_refusal", lambda self, item: None
    )
    _examined, acted = _sweep(_catalog, _by_name, only=only)

    assert ("Adun Oakenshield[0]", "Grizzly Bears") in acted


def _table(by_name, name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 8)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    source = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(0, source, None)
    return game, _nosick(source)


def test_adun_oakenshield_does_not_return_the_card_beside_its_target(_by_name):
    """"{B}{R}{G}, {T}: Return target creature card from your graveyard to
    your hand." The Bears are exiled in response; the Hill Giant under them
    was never a target and stays where it is."""
    game, adun = _table(_by_name, "Adun Oakenshield")
    game.players[0].graveyard.extend(
        [_by_name["Grizzly Bears"], _by_name["Hill Giant"]]
    )

    queued = game.queue_permanent_ability(
        0, "Adun Oakenshield", target_player_index=0, target_permanent_index=0,
    )
    assert queued.supported
    game.players[0].exile.append(game.players[0].graveyard.pop(0))
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Hill Giant"]
    assert game.players[0].hand == []
    assert adun.tapped    # the cost stays paid (CR 608.2b counters, it does not refund)
    assert any("no longer in the graveyard (608.2b)" in line for line in game.log)


def test_a_surviving_copy_keeps_the_target_legal(_by_name):
    """The ambiguity left alone: two copies of one card in one pile are one
    object, so the engine cannot know which of them left, and while one
    survives the ability resolves on it."""
    game, _adun = _table(_by_name, "Adun Oakenshield")
    bears = _by_name["Grizzly Bears"]
    game.players[0].graveyard.extend([bears, bears, _by_name["Hill Giant"]])

    queued = game.queue_permanent_ability(
        0, "Adun Oakenshield", target_player_index=0, target_permanent_index=0,
    )
    assert queued.supported
    game.players[0].exile.append(game.players[0].graveyard.pop(0))
    resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]
    assert [card.name for card in game.players[0].graveyard] == ["Hill Giant"]


def test_a_bare_activation_still_takes_the_handlers_pick(_by_name):
    """Nothing was announced, so nothing went away: the headless caller's
    unnamed target is the handler's standing pick, exactly as before."""
    game, _adun = _table(_by_name, "Adun Oakenshield")
    game.players[0].graveyard.extend(
        [_by_name["Lightning Bolt"], _by_name["Hill Giant"]]
    )

    result = game.activate_permanent_ability(0, "Adun Oakenshield")
    resolve_stack(game)

    assert result.supported
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]


def test_a_triggered_ability_is_not_answered_by_this_gate(_by_name):
    """The bound, held: ``StackItem.activated`` is what the gate reads, and a
    triggered ability on the stack does not carry it."""
    game, _adun = _table(_by_name, "Adun Oakenshield")
    game.players[0].graveyard.append(_by_name["Grizzly Bears"])
    assert game.queue_permanent_ability(
        0, "Adun Oakenshield", target_player_index=0, target_permanent_index=0,
    ).supported
    item = game.stack[-1]
    assert item.activated

    item.activated = False
    game.players[0].exile.append(game.players[0].graveyard.pop(0))

    assert game.vanished_graveyard_target_refusal(item) is None
