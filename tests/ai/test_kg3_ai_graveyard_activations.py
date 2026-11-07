"""An AI seat activates the abilities its graveyard holds (CR 113.6b/m).

Until the kg3 round no AI path called ``Game.activate_from_graveyard`` — the
only caller outside the tests was the web route a person clicks — so Ashen
Ghoul, Carrionette, Glory, Hammer of Bogardan, Necrosavant, Shard Phoenix,
Whiteout and Gangrenous Goliath were cards a simulated seat put in its
graveyard and left there. ``engine/ai_graveyard_activations.py`` is the
chooser (the engine's zone read, its CR 602.5 prohibitions, a rehearsal per
candidate), the simulator asks it in the main phase, in its priority windows
and in the seat's **own upkeep** — where most of these may only be activated
— and ``SimulationReport.activations_from_graveyard`` counts what it took.

The census below holds every graveyard ability in the shipped pool to a board
on which the seat activates it: a card printed with a new one fails here until
a board shows the AI using it.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import ai_simulator
from engine import ai_priority
from engine.activation_zones import GRAVEYARD, ability_functions_from
from engine.ai_graveyard_activations import (
    activate_chosen_graveyard_ability,
    choose_graveyard_activation_action,
)
from engine.card_loader import (load_catalog, load_cards, manifest_set_path,
                                manifest_set_paths)
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack

#: The boards are built from **both** manifest roles, so a measured set's
#: graveyard ability can be given its board before the promotion that brings
#: it into the census (Scourge's Eternal Dragon, at its rehearsal). The
#: census itself reads the shipped pool alone (`_pool_graveyard_abilities`).
_CARDS = {card.name: card for card in load_cards(manifest_set_paths(include_measured=True))}


def _board(*, graveyard, lands=(), mine=(), theirs=(), hand=(), step="precombat_main"):
    """Seat 0 to act in its own *step*, mana enforced, holding *graveyard*
    (in pile order: the last name is on top) and the permanents named."""
    phase = {"upkeep": "beginning", "precombat_main": "precombat_main"}[step]
    game = Game(players=[
        PlayerState(
            name="AI", graveyard=[_CARDS[name] for name in graveyard],
            hand=[_CARDS[name] for name in hand], library=[_CARDS["Swamp"]] * 10,
        ),
        PlayerState(name="Opp", library=[_CARDS["Swamp"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 3
    game.active_player_index = 0
    for seat, names in ((0, (*lands, *mine)), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game.current_turn_phase = phase
    game.current_step = step
    return game


def _names(cards) -> list[str]:
    return sorted(card.name for card in cards)


def _on_board(game, seat) -> list[str]:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


#: One board per graveyard ability in the pool, and what the board reads once
#: the seat has activated it: ``(board, (seat 0's hand, seat 0's battlefield,
#: seat 1's battlefield))``.
_BOARDS = {
    "Ashen Ghoul": (
        dict(graveyard=["Ashen Ghoul", "Balduvian Bears", "Brown Ouphe", "Tor Giant"],
             lands=["Swamp"], step="upkeep"),
        ([], ["Ashen Ghoul", "Swamp"], []),
    ),
    # A spare snow land: a land a seat needs is worth more than the card.
    "Whiteout": (
        dict(graveyard=["Whiteout"], lands=["Snow-Covered Forest", *["Forest"] * 7]),
        (["Whiteout"], ["Forest"] * 7, []),
    ),
    "Hammer of Bogardan": (
        dict(graveyard=["Hammer of Bogardan"], lands=["Mountain"] * 5, step="upkeep"),
        (["Hammer of Bogardan"], ["Mountain"] * 5, []),
    ),
    "Necrosavant": (
        dict(graveyard=["Necrosavant"], lands=["Swamp"] * 5, mine=["Llanowar Elves"],
             step="upkeep"),
        ([], ["Necrosavant", *["Swamp"] * 5], []),
    ),
    "Carrionette": (
        dict(graveyard=["Carrionette"], lands=["Swamp"] * 4, theirs=["Serra Angel"]),
        ([], ["Swamp"] * 4, []),
    ),
    "Shard Phoenix": (
        dict(graveyard=["Shard Phoenix"], lands=["Mountain"] * 3, step="upkeep"),
        (["Shard Phoenix"], ["Mountain"] * 3, []),
    ),
    "Gangrenous Goliath": (
        dict(graveyard=["Gangrenous Goliath"], mine=["Daru Healer"] * 3),
        (["Gangrenous Goliath"], ["Daru Healer"] * 3, []),
    ),
    # Two of the six Swamps, the door's default pick (the engine's door
    # refused a two-permanent sacrifice for anyone before the kg3 round).
    "Coffin Puppets": (
        dict(graveyard=["Coffin Puppets"], lands=["Swamp"] * 6, step="upkeep"),
        ([], ["Coffin Puppets", *["Swamp"] * 4], []),
    ),
    # The cheapest card in hand pays the discard (the door had a discard on
    # its deny list): the Island, not the Hill Giant.
    "Undead Gladiator": (
        dict(graveyard=["Undead Gladiator"], lands=["Swamp"] * 2,
             hand=["Hill Giant", "Island"], step="upkeep"),
        (["Hill Giant", "Undead Gladiator"], ["Swamp"] * 2, []),
    ),
    # Scourge, at its promotion rehearsal: Shard Phoenix's shape at five mana
    # ("{3}{W}{W}: Return this card from your graveyard to your hand. Activate
    # only during your upkeep."). Every Plains taps for it, and a 5/5 flyer in
    # hand outweighs the five untapped lands it costs for one upkeep.
    "Eternal Dragon": (
        dict(graveyard=["Eternal Dragon"], lands=["Plains"] * 5, step="upkeep"),
        (["Eternal Dragon"], ["Plains"] * 5, []),
    ),
}

#: Glory's is a shield: worth activating only where something is coming,
#: which its own test below drives (in response to a burn spell).
_DRIVEN_ELSEWHERE = {"Glory"}


def _pool_graveyard_abilities() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for card in compilation_units(load_catalog()):
        program = compile_card_oracle(card)
        for index, ability in enumerate(program.activated_abilities):
            if ability.supported and ability_functions_from(ability) == GRAVEYARD:
                found.setdefault(card.name, []).append(index)
    return found


def test_every_graveyard_ability_in_the_pool_has_a_board_the_ai_uses_it_on():
    """The census, with its floor: ten abilities on ten cards at the kg3
    round (the playbook's entry named eight). Each is driven below or by
    its own test."""
    found = _pool_graveyard_abilities()
    assert len(found) >= 10, found
    covered = set(_BOARDS) | _DRIVEN_ELSEWHERE
    assert set(found) <= covered, sorted(set(found) - covered)


@pytest.mark.parametrize("name", sorted(_BOARDS))
def test_the_ai_activates_the_graveyard_ability(name):
    board, (hand, mine, theirs) = _BOARDS[name]
    game = _board(**board)

    action = choose_graveyard_activation_action(game, 0)

    assert action is not None and action.card_name == name
    result = activate_chosen_graveyard_ability(game, 0, action)
    assert result.supported, result.details
    assert f"{name} ability added to stack from the graveyard" in game.log
    resolve_stack(game)
    assert _names(game.players[0].hand) == sorted(hand), game.log[-6:]
    assert _on_board(game, 0) == sorted(mine), game.log[-6:]
    assert _on_board(game, 1) == sorted(theirs), game.log[-6:]
    assert name not in _names(game.players[0].graveyard)


def test_an_ability_the_board_cannot_pay_for_is_never_proposed():
    """One Swamp is not "two lands": the rehearsal carries the engine's
    refusal back, and nothing is proposed — rather than a refusal every
    upkeep."""
    game = _board(graveyard=["Coffin Puppets"], lands=["Swamp"], step="upkeep")

    assert choose_graveyard_activation_action(game, 0) is None
    assert [card.name for card in game.players[0].graveyard] == ["Coffin Puppets"]


def test_an_upkeep_ability_is_not_proposed_in_the_main_phase():
    """CR 602.5: "Activate only during your upkeep" is the engine's
    prohibition, asked before anything is weighed."""
    game = _board(graveyard=["Shard Phoenix"], lands=["Mountain"] * 3)

    assert choose_graveyard_activation_action(game, 0) is None
    assert not any(permanent.tapped for permanent in game.controlled_by(0))


def test_a_land_the_seat_needs_is_not_given_up_for_the_card():
    """The other half of Whiteout's board: with two lands, the land is worth
    more than the card it buys back (`ai_standing.seat_standing`), and the
    rehearsal says so."""
    game = _board(graveyard=["Whiteout"], lands=["Snow-Covered Forest", "Forest"])

    assert choose_graveyard_activation_action(game, 0) is None


def test_the_target_is_on_the_side_the_effect_wants():
    """Carrionette's "Exile this card and target creature …": the opposing
    creature, never the seat's own, though the picker offers both."""
    game = _board(
        graveyard=["Carrionette"], lands=["Swamp"] * 4,
        mine=["Grizzly Bears"], theirs=["Serra Angel"],
    )

    action = choose_graveyard_activation_action(game, 0)

    angel = next(iter(game.controlled_by(1)))
    assert action is not None and action.target_permanent_ids == [angel.permanent_id]


# --- the simulator --------------------------------------------------------------


def _simulated(*, active=0, graveyards=((), ()), boards=((), ()), hands=((), ())):
    """A two-seat table built the way `run_ai_simulation` builds one: mana
    enforced, both drivers set."""
    players = [
        PlayerState(
            name=name, hand=[_CARDS[card] for card in hand],
            graveyard=[_CARDS[card] for card in graveyard],
            library=[_CARDS["Forest"]] * 8,
        )
        for name, hand, graveyard in zip(("AI-A", "AI-B"), hands, graveyards)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate(boards):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    return game, report


def test_the_seat_answers_its_own_upkeep_for_its_graveyard():
    """CR 117.3a: the active player receives priority in the upkeep, and the
    simulator now answers it (`ai_priority.instant_speed_window`'s ``"upkeep"``) — the
    one moment "Activate only during your upkeep" allows."""
    game, report = _simulated(
        graveyards=(("Shard Phoenix",), ()), boards=(["Mountain"] * 3, ()),
    )
    game._set_phase_and_step("beginning", "upkeep")
    assert ai_priority.instant_speed_window(game, 0) == "upkeep"

    game._resolve_priority_window()

    assert _names(game.players[0].hand) == ["Shard Phoenix"]
    assert game.players[0].graveyard == []
    assert report.activations_from_graveyard == Counter({"Shard Phoenix": 1})
    assert report.activations_at_instant_speed == Counter({"upkeep": 1})
    assert report.log_lines == [
        "G1 T1 AI-A activate Shard Phoenix from graveyard -> queued [in the upkeep]"
    ]


def test_the_upkeep_window_weighs_nothing_but_the_graveyard():
    """Every other card is played where it always was: an instant the seat
    could cast, or a battlefield ability it could activate, is not weighed in
    its upkeep — so the window moves no game that holds no graveyard ability."""
    game, report = _simulated(
        hands=(("Lightning Bolt",), ()),
        boards=(("Mountain", "Prodigal Sorcerer"), ("Grizzly Bears",)),
    )
    game._set_phase_and_step("beginning", "upkeep")

    game._resolve_priority_window()

    assert _names(game.players[0].hand) == ["Lightning Bolt"]
    assert not any(permanent.tapped for permanent in game.controlled_by(0))
    assert report.priority_offers == 0 and report.log_lines == []


def test_glory_is_raised_in_front_of_the_burn_spell():
    """At instant speed, where it lasts: AI-A Bolts AI-B's Grizzly Bears and
    AI-B answers from its graveyard — Glory's protection from red makes the
    Bolt's only target illegal (CR 608.2b), and the Bears live."""
    game, report = _simulated(
        hands=(("Lightning Bolt",), ()), graveyards=((), ("Glory",)),
        boards=(("Mountain",), ("Grizzly Bears", "Plains", "Plains", "Plains")),
    )
    bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
    game.players[0].mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])

    assert result.supported, result.details
    assert game.is_on_battlefield(bears) and bears.damage_marked == 0
    assert _names(game.players[1].graveyard) == ["Glory"]
    assert report.activations_from_graveyard == Counter({"Glory": 1})
    assert report.activations_at_instant_speed == Counter({"response": 1})
    assert report.log_lines == [
        "G1 T1 AI-B activate Glory from graveyard -> queued [in response to Lightning Bolt]"
    ]


def test_glory_with_nothing_coming_is_not_raised():
    """The rehearsal's veto: protection until end of turn with nothing to
    stop changes nothing that lasts, in the main phase and at the end of the
    opponent's turn alike."""
    game, report = _simulated(
        active=0, graveyards=((), ("Glory",)),
        boards=((), ("Grizzly Bears", "Plains", "Plains", "Plains")),
    )
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()

    assert report.activations_from_graveyard == Counter()
    assert not any(permanent.tapped for permanent in game.controlled_by(1))


def test_the_main_phase_pass_activates_and_settles_it():
    """`_play_activations`' graveyard pass: the ability is put on the stack,
    resolved before the phase goes on (the queue form, settled as the hand's
    is), logged and counted."""
    game, report = _simulated(
        graveyards=(("Gangrenous Goliath",), ()), boards=(["Daru Healer"] * 3, ()),
    )
    game._set_phase_and_step("precombat_main", "precombat_main")

    ai_simulator._play_activations(game, 0, report, 1, 1)

    assert game.stack == []
    assert _names(game.players[0].hand) == ["Gangrenous Goliath"]
    assert all(permanent.tapped for permanent in game.controlled_by(0))
    assert report.activations_from_graveyard == Counter({"Gangrenous Goliath": 1})
    assert "G1 T1 AI-A activate Gangrenous Goliath from graveyard -> queued" in report.log_lines


@pytest.mark.full
def test_a_seeded_run_activates_a_graveyard_ability():
    """Hammer of Bogardan pinned into both decks of a seeded Mirage run: a
    seat returns it from its graveyard in its upkeep at least once, and the
    run is clean."""
    report = ai_simulator.run_ai_simulation(
        manifest_set_path("MIR"), games=3, seed=11, max_turns=12,
        required_cards=["Hammer of Bogardan"],
    )
    assert report.activations_from_graveyard["Hammer of Bogardan"] >= 1
    assert any(
        "activate Hammer of Bogardan from graveyard -> queued" in line
        for line in report.log_lines
    )
    assert not report.issues, report.issues
    assert not report.steps_left_owing
