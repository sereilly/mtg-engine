"""A discard paid as a cost takes the card the seat least wants to lose.

``ai_prompt_picks.discard_order`` is how a seat nobody asks answers a chosen
discard (a card whose madness cost the board can pay first, CR 702.35a, then
the least ``discard_worth``: a card with a road back from the graveyard keeps
part of its worth). kg5's ``aivalue`` gave it to the discard prompt and left
the three roads where a **cost** discards a card the payer chooses (CR
601.2b, 602.2b), each with its own pick:

* a spell's printed additional discard — 17 shipped spells (the Dreams,
  Firestorm, Thrill of Possibility, Forbid's buyback…): the AI's cast named
  nothing (``CastAction`` had no field for it), so the engine paid with the
  first cards the phrase names in hand order — a Shivan Dragon in front of a
  spare Mountain;
* a graveyard ability's discard (Undead Gladiator): the card of least mana
  value, so a Lightning Bolt went before a Firebolt that flashes back;
* a battlefield ability's discard, which the AI makes only to take a card
  with madness (``ai_abilities._madness_discard_index``): the first such card
  in hand, not the cheapest of them.

Each now asks ``discard_order``. The census holds every shipped spell's
named discard to the payers the engine admits and to the reading; the boards
drive the real choosers and executors, and fail on the base.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState, faces
from engine.ai_abilities import _madness_discard_index
from engine.ai_actions import CastAction
from engine.ai_casts import _cast_naming_its_discards
from engine.ai_graveyard_activations import (activate_chosen_graveyard_ability,
                                             choose_graveyard_activation_action)
from engine.ai_policy import cast_chosen_instant, choose_cast_action
from engine.ai_prompt_picks import discard_worth
from engine.card_loader import load_catalog
from engine.cast_costs import additional_costs
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, settle

#: A hand every phrase in the pool can be paid out of: creatures, a red and a
#: green spell, lands, a card with flashback.
_HAND = (
    "Shivan Dragon", "Craw Wurm", "Lightning Bolt", "Giant Growth", "Firebolt",
    "Mountain", "Forest", "Swamp",
)


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _seat(hand, *, mine=(), graveyard=(), mana=False) -> Game:
    cards = _catalog()
    game = Game(players=[
        PlayerState(name="A", hand=[cards[n] for n in hand],
                    graveyard=[cards[n] for n in graveyard],
                    library=[cards["Forest"]] * 10),
        PlayerState(name="B", library=[cards["Forest"]] * 10),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set()
    for name in mine:
        permanent = Permanent(card=cards[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game.start_turn(0)
    game._settle()
    return game


def _spells_with_a_chosen_discard() -> list:
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        if not compile_card_oracle(unit).supported:
            continue
        for cost in additional_costs(unit):
            if (
                cost.discard_cards and not cost.discard_at_random
                and not cost.discard_whole_hand and cost.from_zone in (None, "hand")
            ):
                found.append((unit, cost))
                break
    return found


def test_every_spell_names_the_cards_its_discard_is_paid_with():
    """Every shipped spell whose additional cost discards cards its caster
    chooses, cast from a hand holding something of every kind: the cast
    names its discard (never the engine's first-in-hand default), the engine
    takes the named cards as the payment (``_resolve_discard_cost_cards``), and
    no payer left in hand is worth less to lose than one named."""
    rows = _spells_with_a_chosen_discard()
    assert len(rows) >= 15, [unit.name for unit, _cost in rows]
    named_rows = 0
    for unit, cost in rows:
        game = _seat([unit.name, *_HAND])
        x_value = 1 if cost.discard_count_x else None
        offers = {cost.optional_key: 1} if cost.optional_key else None
        action = CastAction(
            card_name=unit.name, target_player_index=1, x_value=x_value,
            land_tap_indices=(), score=0.0, hand_index=0,
            optional_cost_payments=offers,
        )
        named = _cast_naming_its_discards(game, 0, unit, action, offers).cost_hand_indices
        assert named, unit.name
        hand = game.players[0].hand
        assert 0 not in named, unit.name
        assert len(named) == cost.discarded_count(x_value), (unit.name, named)
        chosen, denial = game._resolve_discard_cost_cards(
            0, unit, tuple(additional_costs(unit)),
            cost_hand_index=named[0], cost_other_hand_indices=list(named[1:]) or None,
            spell_hand_index=0, x_value=x_value,
        )
        assert denial is None, (unit.name, denial)
        assert chosen == [hand[slot] for slot in named], unit.name
        payers = game._discard_cost_payers(0, cost, spell_hand_index=0)
        kept = [
            slot for slot, held in enumerate(hand)
            if slot and slot not in named and any(held is payer for payer in payers)
        ]
        dearest_named = max(discard_worth(game, 0, hand[slot]) for slot in named)
        assert all(discard_worth(game, 0, hand[slot]) >= dearest_named - 1e-9 for slot in kept), (
            unit.name, [hand[slot].name for slot in named],
        )
        named_rows += 1
    assert named_rows >= 15


@pytest.mark.parametrize("hand", [
    ("Shivan Dragon", "Thrill of Possibility", "Mountain"),
    ("Mountain", "Thrill of Possibility", "Shivan Dragon"),
])
def test_thrill_of_possibility_is_paid_with_the_spare_land(hand):
    """"As an additional cost to cast this spell, discard a card. Draw two
    cards." Two Mountains in play, so the Dragon waits: the AI casts Thrill
    and pays with the Mountain wherever it sits in the hand. On the base the
    cast named nothing and the engine discarded the Dragon when it came
    first."""
    game = _seat(hand, mine=["Mountain", "Mountain"], mana=True)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Thrill of Possibility", action
    cast_chosen_instant(game, 0, action)
    settle(game)
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Mountain", "Thrill of Possibility",
    ], game.log[-8:]
    assert "Shivan Dragon" in [card.name for card in game.players[0].hand]


@pytest.mark.parametrize("hand", [
    ("Lightning Bolt", "Firebolt"), ("Firebolt", "Lightning Bolt"),
])
def test_undead_gladiator_discards_the_card_that_flashes_back(hand):
    """"{1}{B}, Discard a card: Return this card from your graveyard to your
    hand. Activate only during your upkeep." With a Lightning Bolt and a
    Firebolt in hand — one mana value — the Firebolt is the card that costs
    less to lose (it flashes back, CR 702.34a). The pick was the least mana
    value, the earlier of equals: the Bolt whenever it came first."""
    game = _seat(hand, mine=["Swamp"] * 4, graveyard=["Undead Gladiator"], mana=True)
    game.current_turn_phase = game.current_step = "upkeep"
    action = choose_graveyard_activation_action(game, 0)
    assert action is not None and action.card_name == "Undead Gladiator", action
    assert game.players[0].hand[action.cost_hand_index].name == "Firebolt"
    result = activate_chosen_graveyard_ability(game, 0, action)
    assert getattr(result, "supported", False), result
    settle(game)
    assert [card.name for card in game.players[0].graveyard] == ["Firebolt"], game.log[-8:]
    assert sorted(card.name for card in game.players[0].hand) == [
        "Lightning Bolt", "Undead Gladiator",
    ]


@pytest.mark.parametrize("hand", [
    ("Arrogant Wurm", "Basking Rootwalla"), ("Basking Rootwalla", "Arrogant Wurm"),
])
def test_a_madness_discard_takes_the_card_least_worth_holding(hand):
    """Wild Mongrel's "Discard a card" is proposed only for a card with
    madness the board can pay for; of two, the one the seat least wants to
    hold (``discard_worth``), not whichever came first. With four Forests
    Arrogant Wurm's {4}{G} is out of reach and its madness {2}{G} is not, so
    the Wurm is the card worth less in hand than the Rootwalla castable now —
    and the one madness turns into a 4/4. On the base the Rootwalla went
    whenever it came first."""
    game = _seat(hand, mine=["Wild Mongrel", "Forest", "Forest", "Forest", "Forest"], mana=True)
    mongrel = next(p for p in game.controlled_by(0) if p.card.name == "Wild Mongrel")
    ability = next(
        a for a in compile_card_oracle(mongrel.card).activated_abilities if a.cost.discard_cards
    )
    slot = _madness_discard_index(game, 0, ability, dict(ability.cost.mana), paying_for=mongrel)
    assert slot is not None and hand[slot] == "Arrogant Wurm", slot
