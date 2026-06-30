"""Regression tests for the tenth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, and continuous-effect logic.

Clusters covered in this batch:
- Twiddle taps an opponent's land (and toggles tap/untap on the chosen
  permanent) instead of only ever untapping the first permanent.
- False Orders removes the *chosen* blocker from combat and unblocks the
  attacker(s) it solely blocked, instead of silently doing nothing.
- Goblin King / Lord of Atlantis grant their landwalk to other creatures of the
  subtype regardless of the order the creatures entered the battlefield.
- Wooden Sphere's optional-pay trigger stays on the stack until the controller
  answers the pay prompt (the general "triggered ability with a prompt" pattern).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.game_types import StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import _effective_keywords


_ROOT = Path(__file__).resolve().parent.parent
_C = {c.name: c for c in load_cards(_ROOT / "lea_cards.json")}


@pytest.fixture(scope="module")
def cards():
    return _C


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


# ---------------------------------------------------------------------------
# Twiddle — "I can't use twiddle to tap an opponent's land." The spell compiled
# to untap-only (so it never tapped anything) and the handler ignored the chosen
# permanent. It now toggles the chosen permanent's tapped state on either side.
# ---------------------------------------------------------------------------

class TestTwiddle:
    def test_compiles_to_tap_or_untap(self, cards):
        prog = compile_card_oracle(cards["Twiddle"])
        assert prog.instructions[0].kind == "tap_or_untap_target"

    def test_taps_opponents_untapped_land(self, cards):
        p0 = PlayerState(name="P0", hand=[cards["Twiddle"]], battlefield=[Permanent(card=cards["Island"])])
        opp_creature = Permanent(card=cards["Grizzly Bears"])
        opp_land = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", battlefield=[opp_creature, opp_land])
        game = _game(p0, p1)
        game.cast_from_hand(0, "Twiddle", target_player_index=1, target_permanent_index=1)
        assert opp_land.tapped is True       # the chosen land is tapped
        assert opp_creature.tapped is False  # not the first permanent

    def test_untaps_own_tapped_creature(self, cards):
        mine = Permanent(card=cards["Grizzly Bears"])
        mine.tapped = True
        p0 = PlayerState(name="P0", hand=[cards["Twiddle"]], battlefield=[Permanent(card=cards["Island"]), mine])
        game = _game(p0, PlayerState(name="P2"))
        game.cast_from_hand(0, "Twiddle", target_player_index=0, target_permanent_index=1)
        assert mine.tapped is False


# ---------------------------------------------------------------------------
# False Orders — "I can choose a target but nothing happens after that." The
# removed_from_combat flag was set but never consumed: the blocker stayed in
# combat. Now the chosen blocker is removed and its sole attacker is unblocked.
# ---------------------------------------------------------------------------

class TestFalseOrders:
    def _combat_board(self, cards):
        atk = Permanent(card=cards["Hill Giant"])
        atk.metadata["summoning_sickness_turn"] = -99
        p0 = PlayerState(name="P0", hand=[cards["False Orders"]], battlefield=[atk, Permanent(card=cards["Mountain"])], life=20)
        blk = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[blk], life=20)
        game = _game(p0, p1)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(0, {0: 1})[0]
        game._set_phase_and_step("combat", "declare_blockers")
        assert game.declare_blockers(1, {0: 0})[0]
        return game, atk, blk, p1

    def test_removes_chosen_blocker_and_unblocks_attacker(self, cards):
        game, atk, blk, p1 = self._combat_board(cards)
        assert atk.blocked is True
        res = game.cast_from_hand(0, "False Orders", target_player_index=1, target_permanent_index=0)
        assert res.supported
        assert blk.metadata.get("removed_from_combat") is True
        assert atk.blocked is False
        assert 0 not in game.combat_blockers  # blocker no longer in combat

    def test_unblocked_attacker_deals_damage_to_player(self, cards):
        game, atk, blk, p1 = self._combat_board(cards)
        game.cast_from_hand(0, "False Orders", target_player_index=1, target_permanent_index=0)
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        assert p1.life == 17  # Hill Giant 3/3 hits the unblocked player


# ---------------------------------------------------------------------------
# Sacrifice — "Sacrifice costs should let me choose a creature I control." The
# cast now classifies as an own-creature choice and the chosen creature is the
# one sacrificed for the mana.
# ---------------------------------------------------------------------------

class TestSacrifice:
    def test_offers_only_own_creatures(self, cards):
        p0 = PlayerState(
            name="P0", hand=[cards["Sacrifice"]],
            battlefield=[Permanent(card=cards["Grizzly Bears"]), Permanent(card=cards["Hill Giant"])],
        )
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=cards["Air Elemental"])])
        game = _game(p0, p1)
        spec = game.cast_target_spec(0, cards["Sacrifice"])
        assert spec["kind"] == "creature" and spec["requires_target"]
        seats = {t["seat"] for t in spec["valid_targets"]}
        names = {t["name"] for t in spec["valid_targets"]}
        assert seats == {0}  # only the caster's own creatures
        assert names == {"Grizzly Bears", "Hill Giant"}

    def test_sacrifices_chosen_creature_for_its_mana_value(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])   # mana value 2
        giant = Permanent(card=cards["Hill Giant"])     # mana value 4
        p0 = PlayerState(name="P0", hand=[cards["Sacrifice"]], battlefield=[bear, giant])
        game = _game(p0, PlayerState(name="P1"))
        game.cast_from_hand(0, "Sacrifice", target_player_index=0, target_permanent_index=1)
        assert not any(p.card.name == "Hill Giant" for p in p0.battlefield)
        assert any(p.card.name == "Grizzly Bears" for p in p0.battlefield)
        assert p0.mana_pool["B"] == 4


# ---------------------------------------------------------------------------
# Goblin King / Lord of Atlantis — landwalk granted to other creatures of the
# subtype, regardless of which entered first (recalc runs as permanents enter).
# ---------------------------------------------------------------------------

class TestLandwalkLordsEntryOrder:
    def test_merfolk_cast_before_lord_gets_islandwalk(self, cards):
        lands = [Permanent(card=cards["Island"]) for _ in range(4)]
        for ln in lands:
            ln.metadata["summoning_sickness_turn"] = -99
        p0 = PlayerState(
            name="P0",
            hand=[cards["Lord of Atlantis"], cards["Merfolk of the Pearl Trident"]],
            battlefield=list(lands),
        )
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=cards["Island"]), Permanent(card=cards["Grizzly Bears"])])
        game = _game(p0, p1)
        game.cast_from_hand(0, "Merfolk of the Pearl Trident")
        game.cast_from_hand(0, "Lord of Atlantis")
        mer = next(p for p in p0.battlefield if p.card.name == "Merfolk of the Pearl Trident")
        assert mer.metadata.get("has_islandwalk") is True
        assert game._can_block_attacker(p1.battlefield[1], mer) is False

    def test_goblin_cast_after_king_gets_mountainwalk(self, cards):
        lands = [Permanent(card=cards["Mountain"]) for _ in range(4)]
        for ln in lands:
            ln.metadata["summoning_sickness_turn"] = -99
        p0 = PlayerState(
            name="P0",
            hand=[cards["Goblin King"], cards["Mons's Goblin Raiders"]],
            battlefield=list(lands),
        )
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=cards["Mountain"]), Permanent(card=cards["Grizzly Bears"])])
        game = _game(p0, p1)
        game.cast_from_hand(0, "Goblin King")
        game.cast_from_hand(0, "Mons's Goblin Raiders")
        gob = next(p for p in p0.battlefield if p.card.name == "Mons's Goblin Raiders")
        assert gob.metadata.get("has_mountainwalk") is True
        assert game._can_block_attacker(p1.battlefield[1], gob) is False

    def test_granted_landwalk_shows_on_keyword_strip_not_on_lord(self, cards):
        # The reported failure was a UI one: the granted landwalk label never
        # appeared on the buffed creatures. The web keyword strip
        # (_effective_keywords) must surface it on the *other* creatures but not
        # on the lord itself ("Other Merfolk ...").
        loa = Permanent(card=cards["Lord of Atlantis"])
        mer = Permanent(card=cards["Merfolk of the Pearl Trident"])
        game = _game(PlayerState(name="P1", battlefield=[loa, mer]), PlayerState(name="P2"))
        game._recalculate_lord_buffs()
        assert "Islandwalk" in _effective_keywords(mer, game)
        assert "Islandwalk" not in _effective_keywords(loa, game)

        king = Permanent(card=cards["Goblin King"])
        gob = Permanent(card=cards["Mons's Goblin Raiders"])
        game2 = _game(PlayerState(name="P1", battlefield=[king, gob]), PlayerState(name="P2"))
        game2._recalculate_lord_buffs()
        assert "Mountainwalk" in _effective_keywords(gob, game2)
        assert "Mountainwalk" not in _effective_keywords(king, game2)


# ---------------------------------------------------------------------------
# Wooden Sphere — "The trigger should stay on the stack until I make a choice."
# Its optional-pay trigger is enqueued and, when resolved on the human priority
# path, stays on the stack until the controller answers the pay prompt.
# ---------------------------------------------------------------------------

class TestWoodenSphereTriggerStaysOnStack:
    def test_green_spell_arms_optional_pay_trigger_on_stack(self, cards):
        sphere = Permanent(card=cards["Wooden Sphere"])
        sphere.metadata["summoning_sickness_turn"] = -99
        # The optional "pay {1}" is only offered when the controller can actually
        # pay (CR 603.3 check at resolution), so give P0 a couple of lands.
        lands = [Permanent(card=cards["Forest"]) for _ in range(2)]
        for ln in lands:
            ln.metadata["summoning_sickness_turn"] = -99
        p0 = PlayerState(name="P0", battlefield=[sphere, *lands], hand=[cards["Llanowar Elves"]], life=20)
        game = _game(p0, PlayerState(name="P1", life=20))
        game.active_player_index = 0
        game._set_phase_and_step("precombat_main", "main")
        assert game.queue_from_hand(0, "Llanowar Elves").supported
        game.note_priority_action_taken(0)
        # First priority round resolves Llanowar Elves and enqueues the trigger.
        game.pass_priority(0)
        game.pass_priority(1)
        assert [it.hook_key for it in game.stack] == ["optional_pay"]
        # Second round resolves the trigger, which pauses on the stack for the pay.
        game.pass_priority(game.priority_player_index)
        result = game.pass_priority(game.priority_player_index)
        assert result == "awaiting_choice"
        assert game.stack and game.stack[-1].card.name == "Wooden Sphere"
        assert game.pending_optional_pays
        assert game.pending_optional_pays[0]["player_index"] == 0


# ---------------------------------------------------------------------------
# Power Sink — "I didn't get a prompt to pay mana to stop the spell from getting
# countered." It now arms a pending payment for the targeted spell's controller;
# headless/AI play still auto-resolves deterministically.
# ---------------------------------------------------------------------------

class TestPowerSink:
    def _board(self, cards):
        p1lands = [Permanent(card=cards["Mountain"]) for _ in range(2)]
        p0 = PlayerState(name="P0", hand=[cards["Power Sink"]],
                         battlefield=[Permanent(card=cards["Island"]) for _ in range(3)], life=20)
        p1 = PlayerState(name="P1", battlefield=p1lands, life=20)
        for ln in p0.battlefield + p1lands:
            ln.metadata["summoning_sickness_turn"] = -99
        game = _game(p0, p1)
        game.active_player_index = 0
        # P1's Lightning Bolt is on the stack; P0 responds with Power Sink (X=2).
        game.stack.append(StackItem(card=cards["Lightning Bolt"], caster_index=1,
                                    target_player_index=0, target_permanent_index=None, x_value=None))
        game._set_phase_and_step("precombat_main", "main")
        game.queue_from_hand(0, "Power Sink", target_player_index=1, target_stack_index=0, x_value=2)
        return game, p0, p1, p1lands

    def test_arms_pending_payment_for_controller_on_human_path(self, cards):
        game, p0, p1, p1lands = self._board(cards)
        game.resolve_top_of_stack(pause_for_choices=True)  # resolves Power Sink
        assert game.pending_mana_payment is not None
        assert game.pending_mana_payment["player_index"] == 1
        assert game.pending_mana_payment["amount"] == 2
        # The targeted spell stays on the stack while the controller decides.
        assert any(it.card.name == "Lightning Bolt" for it in game.stack)

    def test_controller_pays_to_keep_spell(self, cards):
        game, p0, p1, p1lands = self._board(cards)
        game.resolve_top_of_stack(pause_for_choices=True)
        for ln in p1lands:
            ln.tapped = True
            p1.mana_pool["R"] += 1
        assert game.confirm_mana_payment(1, True) is True
        assert any(it.card.name == "Lightning Bolt" for it in game.stack)  # survived
        assert game.pending_mana_payment is None

    def test_controller_declines_and_spell_is_countered_with_rider(self, cards):
        game, p0, p1, p1lands = self._board(cards)
        game.resolve_top_of_stack(pause_for_choices=True)
        assert game.confirm_mana_payment(1, False) is True
        assert any(c.name == "Lightning Bolt" for c in p1.graveyard)  # countered
        assert all(ln.tapped for ln in p1lands)  # Power Sink rider taps their lands

    def test_headless_auto_resolves_counter_when_unable_to_pay(self, cards):
        game, p0, p1, p1lands = self._board(cards)
        # No mana available -> the headless path counters without leaving it pending.
        game.resolve_top_of_stack(pause_for_choices=False)
        assert game.pending_mana_payment is None
        assert any(c.name == "Lightning Bolt" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Blaze of Glory — "I'm not able to choose multiple creatures to block with."
# The grant now lands on the chosen creature and the engine lets it block any
# number of attackers (the UI reads can_block_multiple to allow multi-assign).
# ---------------------------------------------------------------------------

class TestBlazeOfGlory:
    def _board(self, cards):
        a1 = Permanent(card=cards["Hill Giant"])
        a2 = Permanent(card=cards["Gray Ogre"])
        for a in (a1, a2):
            a.metadata["summoning_sickness_turn"] = -99
        p0 = PlayerState(name="P0", battlefield=[a1, a2], life=20)
        wall = Permanent(card=cards["Wall of Stone"])
        p1 = PlayerState(name="P1", hand=[cards["Blaze of Glory"]], battlefield=[wall], life=20)
        game = _game(p0, p1)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.declare_attackers(0, {0: 1, 1: 1})
        return game, wall, p1

    def test_grants_unlimited_blocking_to_chosen_creature(self, cards):
        game, wall, p1 = self._board(cards)
        game.cast_from_hand(1, "Blaze of Glory", target_player_index=1, target_permanent_index=0)
        assert wall.metadata.get("can_block_any_number_until_eot") is True
        assert game._max_blocks_for(wall) > 1

    def test_one_creature_blocks_multiple_attackers(self, cards):
        game, wall, p1 = self._board(cards)
        game.cast_from_hand(1, "Blaze of Glory", target_player_index=1, target_permanent_index=0)
        game._set_phase_and_step("combat", "declare_blockers")
        ok, _ = game.declare_blockers(1, {0: [0, 1]})  # the Wall blocks both attackers
        assert ok
        assert game.combat_blockers == {0: [0, 1]}


# ---------------------------------------------------------------------------
# Phantasmal Terrain — "Don't resolve the spell until I finish the color choice
# prompt." The enchanted land's type is not changed until the controller confirms.
# ---------------------------------------------------------------------------

class TestPhantasmalTerrainDefersChoice:
    def test_land_type_unchanged_until_choice_confirmed(self, cards):
        land = Permanent(card=cards["Forest"])
        p0 = PlayerState(name="P0", hand=[cards["Phantasmal Terrain"]])
        p1 = PlayerState(name="P1", battlefield=[land])
        game = _game(p0, p1)
        game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)
        assert land.metadata.get("land_type_override") is None  # not changed yet
        assert game.pending_land_type_choice is not None
        assert game.confirm_land_type(0, "mountain") is True
        assert land.metadata.get("land_type_override") == "mountain"
        assert game.pending_land_type_choice is None
