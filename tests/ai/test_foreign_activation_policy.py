"""The AI and "Any player may activate this ability" (CR 602.1b).

Two choosers read one compiled program in opposite directions.
`choose_activation_action` walks the seat's own board and must never pay to
remove or hamper its own source — it bounced its own Quicksilver Wall for {4}
and paid 5 life to destroy its own Volrath's Dungeon. The new
`choose_foreign_activation_action` walks every *other* seat's board, where the
same effect is the reason to pay. Which effects a seat wants is
`ai_valuation.foreign_activation_use`, and each class below is driven through
the simulator's own executor so the activation really resolves.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.activation_permissions import card_widens_activation
from engine.ai_policy import (
    FOREIGN_ACTIVATION_LIFE_RESERVE,
    choose_activation_action,
    choose_foreign_activation_action,
)
from engine.ai_simulator import SimulationReport, _execute_foreign_activation
from engine.ai_valuation import foreign_activation_use, harms_its_own_source
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_card


@pytest.fixture(scope="module")
def pool(catalog_by_name, set_pool):
    found = dict(catalog_by_name)
    found.update(set_pool("PCY"))
    return found


def _w2g3_board(pool, *, mine=(), theirs=(), lands=6, life=20, land="Mountain"):
    """Seat 0 active in its precombat main phase with *lands* untapped basic
    *land*s; *mine* and *theirs* on the two battlefields, none summoning
    sick. Mana costs are enforced, so the chooser has to plan the taps."""
    library = [pool["Island"]] * 10
    game = Game(players=[
        PlayerState(name="AI", life=life, library=list(library)),
        PlayerState(name="Foe", life=20, library=list(library)),
    ])
    game.enforce_mana_costs = True
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = {0: [], 1: []}
    for seat, cards in ((0, [land] * lands + list(mine)), (1, list(theirs))):
        for card in cards:
            permanent = Permanent(card=pool[card] if isinstance(card, str) else card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, placed


def _w2g3_run(game, action):
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _execute_foreign_activation(game, 0, action, report, 1, 1)
    return report


def _w2g3_on_board(game, permanent) -> bool:
    return any(p is permanent for p in game.all_permanents())


# --- removal of the source --------------------------------------------------


def test_the_ai_pays_life_to_destroy_an_opponents_volraths_dungeon(pool):
    game, placed = _w2g3_board(pool, theirs=["Volrath's Dungeon"])
    dungeon = placed[1][0]

    action = choose_foreign_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Volrath's Dungeon"
    assert action.source_controller_index == 1
    report = _w2g3_run(game, action)
    assert report.refused_activations == {}, dict(report.refused_activations)
    assert not _w2g3_on_board(game, dungeon)
    assert game.players[0].life == 15, "the activator pays the life, not the controller"
    assert game.players[1].life == 20


def test_the_life_reserve_keeps_a_low_seat_from_paying(pool):
    game, _ = _w2g3_board(
        pool, theirs=["Volrath's Dungeon"], life=FOREIGN_ACTIVATION_LIFE_RESERVE + 4,
    )
    assert choose_foreign_activation_action(game, 0) is None


def test_the_ai_never_destroys_its_own_dungeon(pool):
    """The other direction of the same program: on its own board the effect is
    a loss, and the own-seat chooser rated it 2.5 like anything else."""
    game, placed = _w2g3_board(pool, mine=["Volrath's Dungeon", "Aether Storm"])

    assert choose_activation_action(game, 0) is None
    assert choose_foreign_activation_action(game, 0) is None, "nothing to activate abroad"


def test_a_bounce_is_tempo_paid_for_only_to_clear_a_blocker(pool):
    """"{4}: Return this creature to its owner's hand" on a three-mana wall
    costs the activator more than it costs the owner to recast, so it is worth
    it only with an attack to make past it — measured in a PCY run, a seat
    with nobody to attack with bounced the wall every turn and its owner
    recast it every turn."""
    game, _ = _w2g3_board(pool, theirs=["Quicksilver Wall"])
    assert choose_foreign_activation_action(game, 0) is None

    game, placed = _w2g3_board(pool, mine=["Grizzly Bears"], theirs=["Quicksilver Wall"])
    wall = placed[1][0]
    action = choose_foreign_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Quicksilver Wall"
    _w2g3_run(game, action)
    assert not _w2g3_on_board(game, wall)
    assert pool["Quicksilver Wall"] in game.players[1].hand
    assert sum(1 for p in game.controlled_by(0) if p.tapped) == 4, "the activator paid {4}"


# --- a lethal shrink, and the hampers it is not -----------------------------


def test_a_shrink_is_used_only_when_it_kills(pool):
    """Flailing Soldier's *second* ability ("-1/-1"), never its first
    ("+1/+1", a gift to the opponent's creature) — and only when the -1/-1
    finishes it."""
    game, _ = _w2g3_board(pool, theirs=["Flailing Soldier"])
    assert choose_foreign_activation_action(game, 0) is None

    game, placed = _w2g3_board(pool, theirs=["Flailing Soldier"])
    soldier = placed[1][0]
    soldier.damage_marked = 1
    action = choose_foreign_activation_action(game, 0)
    assert action is not None and action.ability_index == 1
    _w2g3_run(game, action)
    assert not _w2g3_on_board(game, soldier)
    assert soldier.card in game.players[1].graveyard


@pytest.mark.parametrize("name", [
    "Glittering Lion", "Ribbon Snake", "Clergy of the Holy Nimbus", "Mercenaries",
    "Squallmonger",
])
def test_an_enabler_or_a_symmetric_effect_is_not_paid_for(pool, name):
    """"Loses flying", "loses 'Prevent all damage …'", "can't be regenerated"
    are worth paying for only with something lined up to cash them in this
    turn, which a one-activation main-phase chooser does not have; Mercenaries'
    shield is about its own damage and Squallmonger hits every player. The
    seat has the mana and a creature to attack with — it still declines."""
    game, _ = _w2g3_board(pool, mine=["Grizzly Bears"], theirs=[name])
    assert choose_foreign_activation_action(game, 0) is None


# --- an aimed ability is the activator's own --------------------------------


def test_task_mage_assembly_pings_the_opponents_creature(pool):
    game, placed = _w2g3_board(
        pool, mine=["Grizzly Bears"], theirs=["Task Mage Assembly", "Llanowar Elves"],
    )
    elves = placed[1][1]

    action = choose_foreign_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Task Mage Assembly"
    assert action.target_player_index == 1
    _w2g3_run(game, action)
    assert not _w2g3_on_board(game, elves)
    assert _w2g3_on_board(game, placed[0][-1]), "the activator's own Bears untouched"


def test_wishmonger_protects_the_activators_creature_not_the_owners(pool):
    """A colour choice and then a grant: read as one instruction the sequence
    had no side, and the biggest creature on either board — the opponent's —
    got protection paid for by the AI."""
    game, placed = _w2g3_board(pool, mine=["Grizzly Bears"], theirs=["Wishmonger"])

    action = choose_foreign_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Wishmonger"
    assert (action.target_player_index, action.target_permanent_index) == (
        0, game.battlefield_index_of(placed[0][-1]),
    )


# --- the own-seat chooser asks the gates the engine enforces ----------------


@pytest.mark.parametrize("mine, subject, land", [
    (["Svyelunite Priest", "Grizzly Bears"], "Svyelunite Priest", "Island"),  # your upkeep
    (["Arcum's Sleigh", "Grizzly Bears"], "Arcum's Sleigh", "Mountain"),  # during combat
    (["Phyrexian Furnace", "Null Rod"], "Phyrexian Furnace", "Mountain"),  # a board-wide ban
])
def test_the_own_chooser_does_not_propose_what_the_engine_refuses(
    pool, mine, subject, land,
):
    """CR 602.5's printed timing and a Null Rod: the chooser runs in a main
    phase and asked neither, so it proposed these every turn and the engine
    refused them — the seat's one activation of the turn spent on a refusal.
    The default seeded runs (every shipped set plus PCY) logged 184 refused
    activations; asking these two gates took it to 47."""
    game, placed = _w2g3_board(pool, mine=mine, land=land)
    action = choose_activation_action(game, 0)
    assert action is None or action.permanent_name != subject, action


# --- in a real game ----------------------------------------------------------


def test_a_simulated_seat_destroys_its_opponents_dungeon():
    """The Rock Hydra test: whole games through `run_ai_simulation`, the
    Dungeon pinned into both decks. Three seeds rather than one, because what
    is asserted is that the pass exists and resolves, not a seed's story —
    and the controller's own copy must never be the one it pays for."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    foreign, own, refused = 0, [], {}
    for seed in (2, 3, 4):
        report = run_ai_simulation(
            [manifest_set_path("EXO")], games=2, seed=seed, max_turns=10,
            required_cards=["Volrath's Dungeon"],
        )
        foreign += report.foreign_activations
        refused.update({k: v for k, v in report.refused_activations.items() if "Dungeon" in k})
        own += [
            line for line in report.log_lines
            if line.startswith("G") and line.endswith("activate Volrath's Dungeon -> resolved")
        ]
        destroyed = [line for line in report.log_lines if "Volrath's Dungeon was destroyed" in line]
        paid = [line for line in report.log_lines if "paid 5 life to activate Volrath's Dungeon" in line]
        assert len(destroyed) >= len(paid)

    assert foreign >= 1, "no seat ever paid to destroy an opponent's Volrath's Dungeon"
    assert refused == {}, refused
    assert own == [], own


# --- derived, not named -----------------------------------------------------


def test_an_invented_card_is_read_the_same_way():
    """Which cards a weight reaches is a claim about the compiled program."""
    relic = _mk_card(
        "Invented Relic", "{3}", "Artifact",
        "{2}: Destroy this artifact. Any player may activate this ability.",
    )
    snake = _mk_card(
        "Invented Snake", "{1}{U}", "Creature — Snake",
        "Flying\n{1}: This creature loses flying until end of turn. "
        "Any player may activate this ability.",
    )
    assert card_widens_activation(relic) and card_widens_activation(snake)
    relic_ability = usable_activated_abilities(compile_card_oracle(relic))[0]
    snake_ability = usable_activated_abilities(compile_card_oracle(snake))[0]
    assert foreign_activation_use(relic_ability) == "removes_source"
    assert foreign_activation_use(snake_ability) is None
    assert harms_its_own_source(relic_ability.instruction)
    assert harms_its_own_source(snake_ability.instruction)


def test_no_own_ability_that_harms_its_source_is_ever_proposed(catalog, set_pool):
    """Pool-wide, both manifest roles: put each card whose first usable ability
    removes or hampers its own source on the AI's own board with mana to spare,
    and ask the own-seat chooser. Before `harms_its_own_source` it proposed
    them — Quicksilver Wall, Ribbon Snake, Volrath's Dungeon, Blinking Spirit
    — and the floor keeps a later narrowing from passing by examining
    nothing."""
    cards = {card.name: card for card in catalog}
    cards.update(set_pool("PCY"))
    mountain = cards["Mountain"]
    examined, proposed = [], []
    for name, card in sorted(cards.items()):
        usable = usable_activated_abilities(compile_card_oracle(card))
        if not usable or not harms_its_own_source(usable[0].instruction):
            continue
        if "Aura" in (card.type_line or "") or card.primary_type in ("instant", "sorcery"):
            continue
        game = Game(players=[
            PlayerState(name="AI", library=[mountain] * 5),
            PlayerState(name="Foe", library=[mountain] * 5),
        ])
        game.turn = 5
        game.active_player_index = 0
        game._set_phase_and_step("precombat_main", "precombat_main")
        for _ in range(8):
            game._put_permanent_onto_battlefield(0, Permanent(card=mountain), None)
        game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
        for permanent in game.all_permanents():
            permanent.metadata["summoning_sickness_turn"] = -99
        examined.append(name)
        action = choose_activation_action(game, 0)
        if action is not None and action.permanent_name == name:
            proposed.append(name)

    assert len(examined) >= 40, examined
    assert {"Quicksilver Wall", "Ribbon Snake", "Volrath's Dungeon"} <= set(examined)
    assert proposed == [], proposed
