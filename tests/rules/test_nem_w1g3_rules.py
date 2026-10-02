"""Rules tests earned by Nemesis wave 1, group 3 — combat restrictions, evasion
and becomes-blocked triggers.

**An effect can block a creature, and what that means to a trigger is its own
rule.** CR 509.1h lets an effect say an attacking creature "becomes blocked";
CR 509.3c says a "whenever [a creature] becomes blocked" ability triggers on
that too, *but only if the creature was unblocked at that time*; and CR 509.3d
says "becomes blocked **by a creature**" never does, because nothing blocked it.
The engine had the state (Dazzling Beauty, Choking Vines and Trap Runner all
shipped marking their creature blocked) and no announcement — so a
becomes-blocked trigger on the creature they blocked simply never fired.
Fog Patch, which blocks every attacker at once, is the card that made the
missing half impossible to miss; every test here uses a shipped spell and an
invented creature, so the rule is pinned independently of the set that found it.

**A blocked creature with no blocker assigns its damage to nobody — unless it
has trample** (CR 702.19d), which then sends all of it to the player.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _nem_g3_catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _nem_g3_creature(name: str, power: int, toughness: int, text: str = "",
                     keywords: tuple = ()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


#: The bare CR 509.3c wording, on an invented creature.
_BARE = "Whenever this creature becomes blocked, you gain 3 life."
#: CR 509.3d's wording — "by a creature" — which an effect never satisfies.
_BY_A_CREATURE = "Whenever this creature becomes blocked by a creature, you gain 3 life."


def _nem_g3_combat(attackers, defenders, spell_name):
    """Seat 0 attacks with every creature among *attackers*; seat 1 holds
    *defenders* and *spell_name* in hand. Stops at declare blockers with no
    block made."""
    mine = [Permanent(card=card) for card in attackers]
    theirs = [Permanent(card=card) for card in defenders]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(mine)),
        PlayerState(name="P1", battlefield=list(theirs),
                    hand=[_nem_g3_catalog()[spell_name]]),
    ])
    game.enforce_mana_costs = False
    for permanent in (*mine, *theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    creatures = [slot for slot, perm in enumerate(mine) if perm.is_creature]
    assert game.declare_attackers(0, creatures)[0]
    game.advance_combat_phase()
    return game, mine, theirs


@pytest.mark.cr("509.1h", "509.3c")
def test_an_effect_that_blocks_an_unblocked_attacker_fires_becomes_blocked():
    game, (attacker,), _ = _nem_g3_combat(
        [_nem_g3_creature("Watcher", 2, 2, _BARE)], [], "Dazzling Beauty",
    )
    game.declare_blockers(1, {})

    game.cast_from_hand(1, "Dazzling Beauty", target_permanent_ids=[attacker.permanent_id])
    resolve_stack(game)

    assert attacker.blocked
    assert game.players[0].life == 23


@pytest.mark.cr("509.3c")
def test_a_board_wide_becomes_blocked_watcher_hears_an_effect_block():
    """Close Quarters' "whenever a creature you control becomes blocked" is the
    same bare wording printed about a set, announced through the event bus
    rather than read off the attacker — so the effect-made block has to reach
    that announcement too, or the enchantment sleeps through Dazzling Beauty."""
    catalog = _nem_g3_catalog()
    game, (attacker, _quarters), _ = _nem_g3_combat(
        [_nem_g3_creature("Raider", 2, 2), catalog["Close Quarters"]],
        [], "Dazzling Beauty",
    )
    game.declare_blockers(1, {})

    game.cast_from_hand(1, "Dazzling Beauty", target_permanent_ids=[attacker.permanent_id])
    resolve_stack(game)

    assert attacker.blocked
    assert "Close Quarters dealt 1 damage" in game.log
    assert game.players[1].life == 19


@pytest.mark.cr("509.3d")
def test_becomes_blocked_by_a_creature_does_not_fire_for_an_effect():
    game, (attacker,), _ = _nem_g3_combat(
        [_nem_g3_creature("Watcher", 2, 2, _BY_A_CREATURE)], [], "Dazzling Beauty",
    )
    game.declare_blockers(1, {})

    game.cast_from_hand(1, "Dazzling Beauty", target_permanent_ids=[attacker.permanent_id])
    resolve_stack(game)

    assert attacker.blocked
    assert game.players[0].life == 20


@pytest.mark.cr("509.3c")
def test_an_already_blocked_attacker_does_not_trigger_again():
    """Choking Vines may target a creature that already has a blocker. It was
    a blocked creature at that time, so CR 509.3c's "only if the attacking
    creature was an unblocked creature" keeps the bare trigger silent."""
    game, (attacker,), (wall,) = _nem_g3_combat(
        [_nem_g3_creature("Watcher", 2, 2, _BARE)],
        [_nem_g3_creature("Wall", 0, 5)], "Choking Vines",
    )
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)
    assert game.players[0].life == 23

    game.cast_from_hand(
        1, "Choking Vines", x_value=1, target_permanent_ids=[attacker.permanent_id]
    )
    resolve_stack(game)

    assert game.players[0].life == 23
    assert attacker.effective_toughness - attacker.damage_marked == 1


@pytest.mark.cr("509.1h", "702.19d")
def test_a_trampler_blocked_by_an_effect_assigns_everything_to_the_player():
    game, (trampler, plain), _ = _nem_g3_combat(
        [
            _nem_g3_creature("Trampler", 4, 4, "Trample", ("Trample",)),
            _nem_g3_creature("Plain", 3, 3),
        ],
        [], "Choking Vines",
    )
    game.declare_blockers(1, {})
    game.cast_from_hand(
        1, "Choking Vines", x_value=2,
        target_permanent_ids=[trampler.permanent_id, plain.permanent_id],
    )
    resolve_stack(game)
    assert trampler.blocked and plain.blocked

    for _ in range(4):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        resolve_stack(game)

    # 4 from the trampler; the plain 3/3 is blocked by nothing and deals none.
    assert game.players[1].life == 16
