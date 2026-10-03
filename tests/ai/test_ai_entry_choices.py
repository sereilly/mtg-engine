"""What a seat nobody asks names for a choice whose answer helps or hurts.

Two of the NEM wave-1 misplays, both in a default the engine states for an
AI or headless seat:

* "As this enters, choose a creature type" took the **opponents'** most common
  type for every card printing it — right for the cards that hose the type
  (An-Zerrin Ruins, Engineered Plague) and backwards for the ones that feed it
  (Belbe's Portal paid {3} every turn to put a creature of the opponent's type
  out of a hand that held none). ``ai_valuation.chosen_creature_type_side``
  reads which from what the card does with the word.
* "Each player chooses a card in their hand" (Stronghold Gambit) took the first
  card in hand order, revealing a land as often as a creature.
  ``ai_policy.order_hand_pick`` reads what the next sentence does with the pick.
"""
from __future__ import annotations

import pytest

from engine.ai_valuation import chosen_creature_type_side
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _mk_card, resolve_stack


def _creature(name, subtype, mana_cost="{1}"):
    card = _mk_card(
        name=name, mana_cost=mana_cost, type_line=f"Creature — {subtype}",
    )
    return card


def _board(entering, set_pool):
    """The caster holds Goblins in every zone; the opponent fields Elves."""
    goblins = [_creature(f"Goblin {i}", "Goblin") for i in range(4)]
    elves = [Permanent(card=_creature(f"Elf {i}", "Elf")) for i in range(3)]
    me = PlayerState(
        name="AI", hand=[entering, goblins[0]], library=goblins[1:3],
        battlefield=[Permanent(card=goblins[3])],
    )
    them = PlayerState(name="Opp", battlefield=elves)
    game = Game(players=[me, them])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


@pytest.mark.parametrize(
    "name,code,side",
    [
        ("Belbe's Portal", "NEM", "you"),
        ("Urza's Incubator", "UDS", "you"),
        ("Volrath's Laboratory", "STH", "you"),
        ("An-Zerrin Ruins", "HML", "opponent"),
        ("Engineered Plague", "ULG", "opponent"),
    ],
)
def test_the_chosen_type_names_the_board_the_card_acts_on(set_pool, name, code, side):
    card = set_pool(code)[name]
    assert chosen_creature_type_side(card) == side

    game = _board(card, set_pool)
    assert game.cast_from_hand(0, name).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    permanent = next(p for p in game.controlled_by(0) if p.card.name == name)
    expected = "goblin" if side == "you" else "elf"
    assert permanent.metadata.get("chosen_creature_type") == expected


def test_a_card_whose_type_neither_helps_nor_hurts_keeps_the_standing_default(set_pool):
    """Conspiracy makes its controller's creatures the chosen type: nothing on
    it says whose type is worth naming, so the opponents' reading stands."""
    conspiracy = set_pool("MMQ")["Conspiracy"]
    assert chosen_creature_type_side(conspiracy) is None


def test_an_invented_feeder_is_answered_without_its_name():
    """The derivation reads the compiled program and the cost table, so a card
    printed tomorrow with the Incubator's sentence is answered the same."""
    feeder = _mk_card(
        name="Hatchery Probe", mana_cost="{2}", type_line="Artifact",
        oracle_text=(
            "As this artifact enters, choose a creature type.\n"
            "Creature spells of the chosen type cost {1} less to cast."
        ),
    )
    assert chosen_creature_type_side(feeder) == "you"


def test_stronghold_gambit_reveals_the_cheapest_creature_card(set_pool):
    """The pick feeds "the owner of each creature card revealed this way with
    the lowest mana value puts it onto the battlefield", so a seat nobody asks
    reveals a creature card, and the cheapest one it holds."""
    from dataclasses import replace

    gambit = set_pool("NEM")["Stronghold Gambit"]
    rock = _mk_card(name="Plain Rock", mana_cost="{1}", type_line="Artifact")
    big = replace(_creature("Big Ogre", "Ogre", mana_cost="{4}{R}"), cmc=5.0)
    small = replace(_creature("Small Goblin", "Goblin", mana_cost="{R}"), cmc=1.0)
    me = PlayerState(name="AI", hand=[gambit, rock, big, small])
    them = PlayerState(name="Opp", hand=[_mk_card(name="Their Rock", mana_cost="{1}", type_line="Artifact")])
    game = Game(players=[me, them])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert game.cast_from_hand(0, "Stronghold Gambit").supported
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Small Goblin"]
    assert [c.name for c in me.hand] == ["Plain Rock", "Big Ogre"]


def test_stronghold_gambit_is_not_cast_holding_no_creature_card(set_pool):
    """With no creature card of its own to pick, the caster's Gambit can only
    put the *opponent's* pick onto the battlefield."""
    from engine.ai_policy import choose_cast_action

    gambit = set_pool("NEM")["Stronghold Gambit"]
    rock = _mk_card(name="Plain Rock", mana_cost="{1}", type_line="Artifact")
    game = Game(players=[PlayerState(name="AI", hand=[gambit, rock]), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Stronghold Gambit"

    game.players[0].hand.append(_creature("Small Goblin", "Goblin"))
    action = choose_cast_action(game, 0)
    assert action is not None


def test_belbes_portal_is_not_activated_with_no_card_of_the_type_in_hand(set_pool):
    """"{3}, {T}: You may put a creature card of the chosen type from your hand
    onto the battlefield." The cost buys nothing without such a card, and the
    simulator watched the AI pay it every turn."""
    from engine.ai_policy import choose_activation_action

    portal = Permanent(card=set_pool("NEM")["Belbe's Portal"])
    portal.metadata["chosen_creature_type"] = "goblin"
    portal.metadata["summoning_sickness_turn"] = -99
    me = PlayerState(name="AI", battlefield=[portal], hand=[_creature("Elf", "Elf")])
    game = Game(players=[me, PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game._sync_control()
    assert choose_activation_action(game, 0) is None

    me.hand.append(_creature("Goblin", "Goblin"))
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Belbe's Portal"
