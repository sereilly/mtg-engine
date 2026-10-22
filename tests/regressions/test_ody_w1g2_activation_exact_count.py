"""An ability printing an exact number of targets is not activated naming
fewer (CR 601.2c through CR 602.2b) — W1G2, found driving Nomad Decoy.

"Threshold — {W}{W}, {T}: Tap **two** target creatures." named at one creature
was accepted, paid for, and tapped one. The cast side has counted since
Planeshift (``legality_cast_gates.cast_target_count_refusal``); ROADMAP carried the
activation side as a leftover. Measured on the tree before the gate: five
abilities in both manifest roles print an exact count of two or more, and
four of the four that could be driven accepted a list of one (Argothian
Elder, Wintermoon Mesa, Nomad Decoy, Twigwalker).

A census rather than a test of those names, so the next card printing a count
on an ability is held to it the day it is ingested. It carries floors, because
a sweep that examined nothing passes on the broken engine.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.faces import compilation_units
from engine.legality import exact_target_count
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import activation_target_slot

_W1G2_LEA = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
_W1G2_POOL = load_cards(manifest_set_paths(include_measured=True))

#: A board with something of each common kind on both sides, so a picker for
#: "two target creatures" or "two target lands" has two to offer.
_W1G2_BOARD = ("Grizzly Bears", "Grizzly Bears", "Forest", "Forest", "Sol Ring", "Sol Ring")


def _w1g2_counted_abilities():
    """``(card, ability index, required)`` for every supported activated
    ability whose slot prints an exact count of two or more, and how many
    abilities were looked at to find them."""
    examined, found = 0, []
    for card in compilation_units(_W1G2_POOL):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(program.activated_abilities):
            if not ability.supported or ability.instruction is None:
                continue
            examined += 1
            slot = activation_target_slot(ability)
            if slot is None:
                continue
            required = exact_target_count(slot[0], slot[1], None)
            if required is not None and required >= 2:
                found.append((card, index, required))
    return examined, found


def _w1g2_game_with(card):
    forest = _W1G2_LEA["Forest"]
    game = Game(players=[
        PlayerState("A", library=[forest] * 10, hand=[forest] * 3),
        PlayerState("B", library=[forest] * 10, hand=[forest] * 3),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    # Enough cards for a threshold clause to be met: the count gate is the
    # question here, not the restriction in front of it.
    game.players[0].graveyard.extend([_W1G2_LEA["Grizzly Bears"]] * 9)
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, None)
    source.tapped = False
    source.metadata["summoning_sickness_turn"] = -99
    for seat in (0, 1):
        for name in _W1G2_BOARD:
            permanent = Permanent(card=_W1G2_LEA[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game, source


def test_an_exact_target_count_on_an_ability_refuses_a_shorter_list():
    examined, counted = _w1g2_counted_abilities()
    assert examined >= 2000, examined
    assert len(counted) >= 3, [card.name for card, _index, _required in counted]

    driven, accepted = [], []
    for card, index, required in counted:
        game, source = _w1g2_game_with(card)
        spec = game.activation_target_spec(
            0, game.battlefield_index_of(source), ability_index=index,
        )
        offered = [
            entry for entry in (spec or {}).get("valid_targets") or ()
            if entry.get("kind") == "permanent"
        ]
        if len(offered) < required:
            # Not a board this sweep can build (General Jarkeld wants blocking
            # creatures): the gate is the same code either way, and the floor
            # below is what says enough of them were driven.
            continue
        driven.append(card.name)
        named = game.permanent_at(offered[0]["seat"], offered[0]["index"])
        tapped_before = source.tapped

        short = game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=index, target_permanent_ids=[named.permanent_id],
        )

        if short.supported:
            accepted.append((card.name, index, required, short.details))
            continue
        assert f"needs {required} targets, not 1" in short.details, (card.name, short.details)
        assert game.stack == [] and source.tapped is tapped_before, card.name

        full = [
            game.permanent_at(entry["seat"], entry["index"]).permanent_id
            for entry in offered[:required]
        ]
        whole = game.queue_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(source),
            ability_index=index, target_permanent_ids=full,
        )
        assert whole.supported, (card.name, whole.details)

    assert len(driven) >= 2, driven
    assert not accepted, f"a printed count read as a ceiling: {accepted}"
