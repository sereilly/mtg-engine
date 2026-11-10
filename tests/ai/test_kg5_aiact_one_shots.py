"""A one-shot artifact is cracked only for what its effect does now (kg5 aiact).

A noncreature artifact whose every ability gives it up
(``ai_abilities._exists_to_be_given_up``) kept its flat score in the
main-phase chooser and was never rehearsed — a rehearsal of the whole cost
prices the artifact's own card above almost anything it does — so Feldon's
Cane was cracked over an empty graveyard and Tormod's Crypt aimed at one,
each the seat's one activation of the turn.

It is now asked what every other ability is asked (``ai_activation_rehearsal.
_moves_something(one_shot=True)``) with the source **given up on both
copies** (``_rehearse_activation(cost_neutral=True)``), so what is weighed is
the effect; and a rehearsal whose only change is a library's order
(``Rehearsal.reordered_only``: CR 701.24a, 701.24c — the Cane shuffles even
an empty graveyard in) moves nothing.

Validated backwards: on the base the Cane, Thran Foundry and Tormod's Crypt
are each proposed on a board with nothing in any graveyard; with the
library-order reading switched off the Cane and Thran Foundry still are.
"""

from __future__ import annotations

from engine.ai_abilities import _abilities_weighed, _exists_to_be_given_up, choose_activation_action
from engine.ai_activation_rehearsal import _gives_up_its_source
from engine.ai_simulator import SimulationReport, _play_activations
from engine.ai_valuation import is_mana_ability
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import CARDS_BY_NAME


def _library():
    """Thirty cards of five different names: a library whose order a shuffle
    changes (thirty Islands shuffle to themselves)."""
    return [CARDS_BY_NAME[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")] * 6


def _board(mine=(), theirs=(), *, graveyard=(), opponent_graveyard=()):
    """The AI's precombat main phase, costs enforced, nothing summoning sick."""
    game = Game(players=[
        PlayerState(name="AI", graveyard=list(graveyard), library=_library()),
        PlayerState(name="Opp", graveyard=list(opponent_graveyard), library=_library()),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, group in ((0, mine), (1, theirs)):
        for card in group:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _activate(game):
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    return report


def test_feldons_cane_waits_for_a_graveyard_to_shuffle_in(set_pool):
    """"{T}, Exile this artifact: Shuffle your graveyard into your library."
    Over an empty graveyard the shuffle is all it does (CR 701.24c), and no
    one knows a shuffled library's order: nothing is proposed. With two cards
    in the graveyard the Cane is cracked and they are in the library."""
    lea, cane = set_pool("LEA"), set_pool("ATQ")["Feldon's Cane"]
    empty = _board(mine=[cane])
    assert choose_activation_action(empty, 0) is None

    game = _board(mine=[cane], graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"]])
    library = len(game.players[0].library)
    _activate(game)
    assert game.players[0].graveyard == []
    assert len(game.players[0].library) == library + 2
    assert [card.name for card in game.players[0].exile] == ["Feldon's Cane"]


def test_tormods_crypt_is_not_spent_on_an_empty_graveyard(set_pool):
    """"{T}, Sacrifice this artifact: Exile target player's graveyard." With
    every graveyard empty nothing is proposed; with a card in the opponent's
    it is cracked at the opponent, and the card is exiled."""
    lea, crypt = set_pool("LEA"), set_pool("DRK")["Tormod's Crypt"]
    assert choose_activation_action(_board(mine=[crypt]), 0) is None

    game = _board(mine=[crypt], opponent_graveyard=[lea["Grizzly Bears"]])
    action = choose_activation_action(game, 0)
    assert action is not None and action.target_player_index == 1
    _activate(game)
    assert game.players[1].graveyard == []
    assert [card.name for card in game.players[1].exile] == ["Grizzly Bears"]


#: One-shots whose whole effect reads a graveyard: on a board where every
#: graveyard is empty each does nothing at all.
_GRAVEYARD_ONE_SHOTS = frozenset({
    "Feldon's Cane", "Thran Foundry", "Tormod's Crypt", "Crystal Chimes",
    "Lodestone Bauble",
})


def test_no_one_shot_is_spent_on_an_empty_board_for_nothing(set_pool):
    """Census over both manifest roles: every one-shot artifact's non-mana
    ability on a board of lands of every colour, every graveyard empty and no
    creature anywhere. The graveyard one-shots are never proposed there; the
    ones whose effect does something on that board (damage to a player, a
    card drawn, life) still are — the gate weighs, it does not refuse. Floors
    on both."""
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.faces import compilation_units

    lea = set_pool("LEA")
    lands = [lea[name] for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")] * 4
    examined, proposed, wrong = [], set(), []
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if "Artifact" not in card.type_line or "Creature" in card.type_line:
            continue
        if not _exists_to_be_given_up(Permanent(card=card)):
            continue
        game = _board(mine=[card, *lands])
        source = game.players[0].battlefield[0]
        weighed = [
            ability for _index, ability in _abilities_weighed(game, source)
            if ability.instruction is not None and not is_mana_ability(ability.instruction)
            and _gives_up_its_source(ability.cost)
        ]
        if not weighed:
            continue
        examined.append(card.name)
        action = choose_activation_action(game, 0)
        if action is not None and action.permanent_name == card.name:
            proposed.add(card.name)
            if card.name in _GRAVEYARD_ONE_SHOTS:
                wrong.append(card.name)
    assert not wrong, wrong
    assert _GRAVEYARD_ONE_SHOTS <= set(examined), sorted(_GRAVEYARD_ONE_SHOTS - set(examined))
    assert len(examined) >= 40, len(examined)
    assert {"Aeolipile", "Pyrite Spellbomb"} <= proposed, sorted(proposed)
