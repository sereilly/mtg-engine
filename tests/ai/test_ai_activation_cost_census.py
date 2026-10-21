"""Census: does an AI seat propose an activation whose **cost** the board
cannot pay?

CR 601.2h, reached through CR 602.2b: unpayable costs can't be paid, and CR
118.3 says when a cost is unpayable — the payer lacks the resources to pay it
fully. The activation path refuses such an activation with nothing spent, and
the simulator counts the refusal (``SimulationReport.refused_activations``):
the seat proposed the one thing it cannot do, and will propose it again next
turn, because nothing about the board has changed.

``ai_policy.choose_activation_action`` asked about the costs it knew one at a
time — a sacrifice, a discard, life, a counter on the source — and nothing
else, while the path's checks were inline, one refusal per cost block, with
no gate to ask. Torment's Grim Lavamancer ("{R}, {T}, Exile two cards from
your graveyard: …") was proposed over an empty graveyard eight times in six
seeded games. Now both ask one gate, ``Game.unpayable_activation_cost``.

**How it is built.** The population is every supported permanent in the
shipped pool and the measured sets whose first usable activated ability (the
one the chooser looks at) pays in something other than mana. Each is put on
seat 0's battlefield, with a full mana pool, on two boards:

``poor``
    nothing else of the seat's: no other permanent, an empty hand, an empty
    graveyard, ten cards of library — the board on which every cost that
    names a resource the seat does not have is unpayable;
``rich``
    the seat holds the zoo the opponent holds (creatures, an artifact, an
    enchantment, an Island), three cards in hand and a graveyard.

The proposal is ``choose_activation_action`` and the activation is the
simulator's own executor (``ai_simulator._play_activations``), so "refused"
is the engine's answer counted exactly as a seeded run counts it.

Validated backwards on the tree before the gate (053649ac): of 378 examined,
81 proposed on the poor board and 26 of them refused for their cost
(``REFUSED_BEFORE``), 88 and 12 on the rich one. After: 55 and 76 proposed,
none refused — exactly the refused ones held back. Over every permanent with
an activated ability (1,748, the scratch sweep this census was cut from) the
proposals the engine accepted are the same 896 and 1,021 before and after.
"""
from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState, ai_simulator
from engine.ai_policy import choose_activation_action
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.ai import test_ai_mode_chooser_census as modes

ME, OPP = 0, 1
UNITS = ("white creature", "black creature", "artifact", "enchantment", "island")

#: The cost fields that pay in something other than mana. ``requires_tap``
#: and the source's own sacrifice or exile are left out: neither can be
#: short on a board where the source stands untapped.
NON_MANA_COSTS = (
    "remove_counter", "discard_last_drawn", "discard_cards",
    "exile_graveyard_position", "hand_to_library_top", "exile_top_of_library",
    "mill_cards", "pay_life", "pay_life_per_counter", "pay_life_half_rounded_up",
    "sacrifice_filter", "sacrifice_attached", "tap_count", "return_to_hand_count",
    "untap_filter", "put_counter_filter", "remove_counter_filter",
    "sacrifice_also_filter", "tap_attached", "exile_filter", "mana_from_attached",
)

#: Proposed and refused for their cost on the poor board, on 053649ac.
REFUSED_BEFORE = frozenset({
    "Balduvian Dead", "Bearscape", "Bloodfire Infusion", "Diversionary Tactics",
    "Drudge Spell", "Flooded Shoreline", "Grim Lavamancer", "Hand of Justice",
    "Hecatomb", "Jandor's Ring", "Karplusan Giant", "Kyren Negotiations",
    "Necropolis", "Night Soil", "Opposition", "Organ Grinder", "Quirion Ranger",
    "Sarcatog", "Screams of the Damned", "Shacklegeist", "Soul Shepherd",
    "Symbiotic Deployment", "Tradewind Rider", "Vodalian War Machine",
    "Volrath's Gardens", "Zombie Assassin",
})

#: …and of those, the ones the rich board *can* pay for, which the gate must
#: leave proposed: a graveyard to exile from, untapped creatures to tap.
PAID_ON_THE_RICH_BOARD = frozenset({
    "Grim Lavamancer", "Bearscape", "Sarcatog", "Zombie Assassin",
    "Soul Shepherd", "Necropolis", "Screams of the Damned", "Balduvian Dead",
    "Diversionary Tactics", "Opposition", "Tradewind Rider",
    "Kyren Negotiations", "Symbiotic Deployment", "Volrath's Gardens",
})


def _pool() -> dict:
    cards: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


POOL = _pool()
FOREST = POOL["Forest"]


def _pays_beyond_mana(card) -> bool:
    ability = next(iter(usable_activated_abilities(compile_card_oracle(card))), None)
    if ability is None or ability.instruction is None:
        return False
    # A filter of ``{}`` is "a card" — present, and falsy — so a field counts
    # as printed unless it holds its own "no such cost" value.
    return any(
        getattr(ability.cost, field, None) not in (None, False, 0, "", ())
        for field in NON_MANA_COSTS
    )


def population() -> list:
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        if not compile_card_oracle(card).supported:
            continue
        if _pays_beyond_mana(card):
            found.append(card)
    return found


POPULATION = population()


def board(card, rich: bool) -> "tuple[Game, Permanent]":
    game = Game(players=[
        PlayerState(name="AI", hand=[FOREST] * (3 if rich else 0), library=[FOREST] * 10),
        PlayerState(name="Opp", hand=[FOREST], library=[FOREST] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat in ((ME, OPP) if rich else (OPP,)):
        for key in UNITS:
            modes.place(game, seat, key)
        game.players[seat].graveyard.extend(modes.GRAVE.values())
    subject = Permanent(card=card)
    game._put_permanent_onto_battlefield(ME, subject, ME)
    subject.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRGC"})
    return game, subject


def run(card, rich: bool) -> dict:
    row = {"proposed": False, "refused": None, "error": None}
    try:
        random.seed(1337)
        game, subject = board(card, rich)
        action = choose_activation_action(game, ME)
        if action is None or game.permanent_at(ME, action.permanent_index) is not subject:
            return row
        row["proposed"] = True
        report = ai_simulator.SimulationReport(
            games_requested=1, games_completed=0, interaction_count=0,
        )
        ai_simulator._play_activations(game, ME, report, 1, 1)
        row["refused"] = "; ".join(report.refused_activations) or None
    except Exception as exc:  # a crash is a finding, not a pass
        row["error"] = f"EXC {type(exc).__name__}: {exc}"
    return row


@pytest.fixture(scope="module")
def rows() -> dict:
    return {
        card.name: {"poor": run(card, False), "rich": run(card, True)}
        for card in POPULATION
    }


def test_the_census_examines_what_it_says(rows):
    """The floor: a census that reaches nothing passes everything."""
    assert len(rows) >= 350, len(rows)
    assert REFUSED_BEFORE <= set(rows), sorted(REFUSED_BEFORE - set(rows))
    assert sum(row["poor"]["proposed"] for row in rows.values()) >= 50
    assert sum(row["rich"]["proposed"] for row in rows.values()) >= 70


def test_no_proposal_crashed(rows):
    errors = {
        (name, leg): row[leg]["error"]
        for name, row in rows.items() for leg in ("poor", "rich")
        if row[leg]["error"]
    }
    assert errors == {}


@pytest.mark.parametrize("leg", ("poor", "rich"))
def test_nothing_proposed_is_refused(rows, leg):
    refused = {
        name: row[leg]["refused"] for name, row in rows.items() if row[leg]["refused"]
    }
    assert refused == {}


def test_a_cost_the_board_can_pay_is_still_proposed(rows):
    """The gate's other direction: what it holds back on the poor board it
    leaves alone where the cost can be paid — and the engine takes it."""
    for name in PAID_ON_THE_RICH_BOARD:
        assert not rows[name]["poor"]["proposed"], name
        assert rows[name]["rich"]["proposed"], name
        assert rows[name]["rich"]["refused"] is None, (name, rows[name]["rich"])


def test_the_gate_is_the_door_s_refusal():
    """The engine half: Grim Lavamancer over an empty graveyard is refused by
    the gate's own words, before anything is paid — the mana stays in the
    pool and the creature stays untapped — and the gate says so beforehand."""
    card = POOL["Grim Lavamancer"]
    game, subject = board(card, rich=False)
    ability = next(iter(game.usable_abilities_of(subject)))
    expected = game.unpayable_activation_cost(ME, subject, ability)
    assert expected == "Grim Lavamancer: nothing available to exile as a cost"
    pool_before = dict(game.players[ME].mana_pool)
    result = game.activate_permanent_ability(ME, card.name, target_player_index=OPP)
    assert not result.supported and result.details == expected
    assert game.log[-1] == expected
    assert dict(game.players[ME].mana_pool) == pool_before
    assert not subject.tapped
    # Two cards in the graveyard pay it: the gate is quiet and the cards go.
    game.players[ME].graveyard.extend([FOREST, FOREST])
    assert game.unpayable_activation_cost(ME, subject, ability) is None
    result = game.activate_permanent_ability(ME, card.name, target_player_index=OPP)
    assert result.supported, result.details
    assert game.players[ME].graveyard == []
    assert game.players[OPP].life == 18
