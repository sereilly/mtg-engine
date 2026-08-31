"""Regression tests for the eleventh batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, continuous-effect logic, and the
backend legality/targeting queries the web UI relies on.

Clusters covered in this batch:
- Fireball / Volcanic Eruption: divided targets may mix creatures and player
  faces across BOTH battlefields (no "same side" restriction).
- Drain Life: only black mana may be spent on X.
- Jade Monolith: the activation carries a second choice — the damage source —
  and only that source's damage is redirected.
- Magical Hack: a land-word swap on a creature with no matching landwalk is a
  no-op (no islandwalk from nothing); the "from" word must exist on the target.
- Mana Vault / Paralyze: choosing "pay {4}" with no mana does not untap for
  free; the cost is genuinely paid (pool first, then tapping lands).
- Verduran Enchantress: the draw trigger resolves while the enchantment that
  fired it is still on the stack (CR 603.3).
- Vesuvan Doppelganger: the copy keeps its own blue color (ETB and re-copy) and
  offers the upkeep prompt to become a copy of a different creature; Clone (no
  exclusion clause) copies the creature's color.
- Zombie Master: other Zombies get "{B}: Regenerate this permanent." — granted
  dynamically (Zombies entering later gain it; it ends when the Master leaves)
  and costing {B} to activate.
"""
from __future__ import annotations


import pytest

from engine import Game, PlayerState, load_cards
from engine.models import Permanent
from tests.helpers import _game




# ---------------------------------------------------------------------------
# Fireball — "error saying all creature targets must be on the same side but I
# should be able to target any combination of creatures or player I want".
# ---------------------------------------------------------------------------

class TestFireballDividedTargets:
    def test_splits_damage_across_both_battlefields_and_a_face(self, cards):
        mine = Permanent(card=cards["Grizzly Bears"])       # 2/2 on seat 0
        theirs = Permanent(card=cards["Hill Giant"])        # 3/3 on seat 1
        p1 = PlayerState(name="P1", hand=[cards["Fireball"]], battlefield=[mine])
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = _game(p1, p2)

        # X=9 divided among 3 targets => 3 each: my bears die, their giant dies,
        # and the opponent's face takes 3.
        result = game.cast_from_hand(
            0, "Fireball", x_value=9,
            divided_targets=[(0, 0), (1, 0), (1, None)],
        )
        assert result.supported
        assert mine not in p1.battlefield
        assert theirs not in p2.battlefield
        assert p2.life == 17

    def test_divided_damage_rounds_down(self, cards):
        theirs = Permanent(card=cards["Hill Giant"])  # 3/3
        p1 = PlayerState(name="P1", hand=[cards["Fireball"]])
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = _game(p1, p2)

        # X=5 over 2 targets => 2 each (rounded down): the 3/3 survives with 2.
        result = game.cast_from_hand(
            0, "Fireball", x_value=5,
            divided_targets=[(1, 0), (1, None)],
        )
        assert result.supported
        assert theirs in p2.battlefield
        assert theirs.damage_marked == 2
        assert p2.life == 18

    def test_extra_targets_are_taxed_one_generic_each(self, cards):
        mine = Permanent(card=cards["Grizzly Bears"])
        theirs = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", hand=[cards["Fireball"]])
        p1.battlefield = [mine]
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = True
        # {X}{R} with X=2 plus 2 extra targets => needs R + 2 + 2 = 5 mana.
        p1.mana_pool.update({"R": 1, "C": 3})
        result = game.cast_from_hand(
            0, "Fireball", x_value=2,
            divided_targets=[(0, 0), (1, 0), (1, None)],
        )
        assert not result.supported
        assert "insufficient mana" in result.details

    def test_engine_rejects_stale_divided_index(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Fireball"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Fireball", x_value=3, divided_targets=[(1, 5)])
        assert not result.supported


# ---------------------------------------------------------------------------
# Volcanic Eruption — "Says all targets must be on the same side": the chosen
# Mountains may sit on both battlefields at once.
# ---------------------------------------------------------------------------

class TestVolcanicEruptionCrossSideMountains:
    def test_destroys_mountains_on_both_sides(self, cards):
        my_mountain = Permanent(card=cards["Mountain"])
        their_mountain = Permanent(card=cards["Mountain"])
        their_forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Volcanic Eruption"]], battlefield=[my_mountain])
        p2 = PlayerState(name="P2", battlefield=[their_mountain, their_forest])
        game = _game(p1, p2)

        # By stable ids — the wire shape the X-targets picker sends (an id
        # needs no seat, which is exactly what lets the slots sit on two
        # boards). ``divided_targets`` was the retired hook's picker shape.
        result = game.cast_from_hand(
            0, "Volcanic Eruption", x_value=2,
            target_permanent_ids=[
                my_mountain.permanent_id, their_mountain.permanent_id,
            ],
        )
        assert result.supported
        assert my_mountain not in p1.battlefield
        assert their_mountain not in p2.battlefield
        assert their_forest in p2.battlefield  # non-Mountain untouched
        # 2 Mountains destroyed => 2 damage to each player.
        assert p1.life == 18
        assert p2.life == 18


# ---------------------------------------------------------------------------
# Drain Life — "I was able to spend blue mana on X even though the card says
# 'Spend only black mana on X'".
# ---------------------------------------------------------------------------

class TestDrainLifeBlackXOnly:
    def _hand_game(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Drain Life"]])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = True
        return game, p1, p2

    def test_blue_mana_cannot_pay_x(self, cards):
        game, p1, p2 = self._hand_game(cards)
        # {X}{1}{B}: B for the pip, U for the {1}, but X=2 has only blue left.
        p1.mana_pool.update({"B": 1, "U": 3})
        result = game.cast_from_hand(0, "Drain Life", x_value=2, target_player_index=1)
        assert not result.supported
        assert "insufficient mana" in result.details

    def test_black_mana_pays_x(self, cards):
        game, p1, p2 = self._hand_game(cards)
        p1.mana_pool.update({"B": 3, "U": 1})  # X=2 black + B pip + U for {1}
        result = game.cast_from_hand(0, "Drain Life", x_value=2, target_player_index=1)
        assert result.supported
        assert p2.life == 18
        assert p1.life == 22  # gained life equal to the damage dealt

    def test_inferred_x_counts_only_black(self, cards):
        game, p1, p2 = self._hand_game(cards)
        # Pool B=2, U=4: {1} paid from blue, B pip from black => X can only be 1.
        p1.mana_pool.update({"B": 2, "U": 4})
        result = game.cast_from_hand(0, "Drain Life", target_player_index=1)
        assert result.supported
        assert p2.life == 19  # X inferred as 1, not 4


# ---------------------------------------------------------------------------
# Jade Monolith — "I should get 2 targeting prompts. One for the creature and
# one for the source."
# ---------------------------------------------------------------------------

class TestJadeMonolithSourceChoice:
    def _setup(self, cards):
        monolith = Permanent(card=cards["Jade Monolith"])
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[monolith, bears], hand=[cards["Lightning Bolt"], cards["Fireball"]])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Hill Giant"])])
        game = _game(p1, p2)
        return game, p1, p2, bears

    def test_activation_spec_offers_creature_and_source_lists(self, cards):
        game, p1, p2, _ = self._setup(cards)
        spec = game.activation_target_spec(0, 0)
        assert spec["kind"] == "creature"
        assert spec.get("requires_source") is True
        # Source list covers permanents on both battlefields.
        source_seats = {(t["seat"], t["index"]) for t in spec["source_targets"] if t["kind"] == "permanent"}
        assert (0, 0) in source_seats and (1, 0) in source_seats

    def test_only_the_chosen_source_is_redirected(self, cards):
        game, p1, p2, bears = self._setup(cards)
        # Choose: protect my Bears from my own Lightning Bolt... i.e. the chosen
        # source is the Bolt (cast from hand => match by card identity is not
        # possible for a hand card, so choose the opposing Hill Giant instead
        # and verify a Bolt does NOT get redirected).
        result = game.activate_permanent_ability(
            0, "Jade Monolith",
            target_player_index=0, target_permanent_index=1,
            source_seat=1, source_permanent_index=0,
        )
        assert result.supported
        assert bears.metadata.get("redirect_damage_to_player") == 0
        assert bears.metadata.get("redirect_damage_source") is p2.battlefield[0]

        # A Lightning Bolt (a different source) is NOT redirected: it hits the Bears.
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=0, target_permanent_index=1)
        assert p1.life == 20  # nothing redirected
        assert bears not in p1.battlefield  # 3 damage killed the 2/2
        # The shield is still waiting for its chosen source.
        assert any(
            perm.metadata.get("redirect_damage_source") is not None
            for perm in p1.battlefield
        ) is False  # (the bears died; shield died with them)

    def test_chosen_spell_source_is_redirected(self, cards):
        game, p1, p2, bears = self._setup(cards)
        result = game.activate_permanent_ability(
            0, "Jade Monolith",
            target_player_index=0, target_permanent_index=1,
        )
        assert result.supported
        # No source recorded (legacy/AI path): any source redirects, as before.
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=0, target_permanent_index=1)
        assert bears in p1.battlefield
        assert bears.damage_marked == 0
        assert p1.life == 17  # the 3 damage went to the controller

    def test_combat_damage_from_chosen_attacker_is_redirected(self, cards):
        monolith = Permanent(card=cards["Jade Monolith"])
        blocker = Permanent(card=cards["Grizzly Bears"])
        blocker.metadata["summoning_sickness_turn"] = -99
        attacker = Permanent(card=cards["Hill Giant"])  # 3/3
        attacker.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[monolith, blocker], life=20)  # defender
        p2 = PlayerState(name="P2", battlefield=[attacker], life=20)           # attacker, active
        game = _game(p1, p2)
        game.start_turn(1)
        game._close_current_priority_step()
        game.advance_combat_phase()  # beginning_of_combat
        game.advance_combat_phase()  # declare_attackers
        game.declare_attackers(1, [0])
        game.advance_combat_phase()  # declare_blockers
        game.declare_blockers(0, {1: 0})  # P1's Grizzly (idx 1) blocks the attacker
        result = game.activate_permanent_ability(
            0, "Jade Monolith", permanent_index=0,
            target_player_index=0, target_permanent_index=1,
            source_seat=1, source_permanent_index=0,  # chosen source: the attacker
        )
        assert result.supported
        game.advance_combat_phase()  # combat damage
        game.check_state_based_actions()
        # The Hill Giant's 3 damage to the Bears goes to P1 instead.
        assert blocker.damage_marked == 0
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert p1.life == 17


# ---------------------------------------------------------------------------
# Magical Hack — "I was able to give islandwalk to white knight even though it
# doesn't have any landwalk keywords".
# ---------------------------------------------------------------------------

class TestMagicalHackRequiresExistingWord:
    def test_no_walk_grant_on_creature_without_landwalk(self, cards):
        knight = Permanent(card=cards["White Knight"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[knight])
        game = _game(p1, p2)
        result = game.cast_from_hand(
            0, "Magical Hack",
            target_player_index=1, target_permanent_index=0,
            old_color="B", new_color="U",  # swamp -> island
        )
        assert result.supported  # the spell resolves; the swap is a no-op
        assert not knight.metadata.get("has_islandwalk")
        assert not knight.metadata.get("lost_swampwalk")
        assert not game._has_keyword(knight, "islandwalk")

    def test_still_remaps_a_real_landwalk(self, cards):
        wraith = Permanent(card=cards["Bog Wraith"])  # Swampwalk
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[wraith])
        game = _game(p1, p2)
        result = game.cast_from_hand(
            0, "Magical Hack",
            target_player_index=1, target_permanent_index=0,
            old_color="B", new_color="U",
        )
        assert result.supported
        assert game._has_keyword(wraith, "islandwalk")
        assert not game._has_keyword(wraith, "swampwalk")

    def test_land_swap_requires_the_old_type(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[forest])
        game = _game(p1, p2)
        # island -> mountain on a Forest: no island word to replace, no-op.
        result = game.cast_from_hand(
            0, "Magical Hack",
            target_player_index=1, target_permanent_index=0,
            old_color="U", new_color="R",
        )
        assert result.supported
        assert forest.changed_land_types == ()
        # forest -> mountain works.
        p1.hand.append(cards["Magical Hack"])
        game.cast_from_hand(
            0, "Magical Hack",
            target_player_index=1, target_permanent_index=0,
            old_color="G", new_color="R",
        )
        assert forest.changed_land_types == ("mountain",)


# ---------------------------------------------------------------------------
# Verduran Enchantress — "The enchantment triggering this card should stay on
# the stack until the trigger has resolved" (CR 603.3).
# ---------------------------------------------------------------------------

class TestVerduranEnchantressStackOrder:
    def test_trigger_resolves_before_the_enchantment(self, cards):
        enchantress = Permanent(card=cards["Verduran Enchantress"])
        p1 = PlayerState(name="P1", battlefield=[enchantress], hand=[cards["Bad Moon"]])
        p1.library = [cards["Forest"]]
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Bad Moon")
        log = game.log
        trigger_idx = next(i for i, line in enumerate(log) if "Verduran Enchantress ability resolved" in line)
        resolve_idx = next(i for i, line in enumerate(log) if "put Bad Moon onto battlefield" in line)
        assert trigger_idx < resolve_idx, (
            "the cast trigger must resolve while the enchantment is still on the stack"
        )

    def test_trigger_sits_above_the_spell_on_the_stack(self, cards):
        enchantress = Permanent(card=cards["Verduran Enchantress"])
        p1 = PlayerState(name="P1", battlefield=[enchantress], hand=[cards["Bad Moon"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.queue_from_hand(0, "Bad Moon")
        assert [item.card.name for item in game.stack] == ["Bad Moon", "Verduran Enchantress"]


# ---------------------------------------------------------------------------
# Vesuvan Doppelganger — "Card doesn't retain its color when I copy a creature.
# Also I don't get the upkeep prompt to change into a different creature".
# ---------------------------------------------------------------------------

class TestVesuvanDoppelganger:
    def _enter_as_copy(self, cards, target_name="Craw Wurm"):
        target = Permanent(card=cards[target_name])
        p1 = PlayerState(name="P1", hand=[cards["Vesuvan Doppelganger"]], battlefield=[target])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Black Knight"])])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Vesuvan Doppelganger", target_player_index=0, target_permanent_index=0)
        dop = p1.battlefield[-1]
        return game, p1, p2, dop

    def test_copy_stays_blue(self, cards):
        game, p1, p2, dop = self._enter_as_copy(cards)
        assert dop.copied_from == "Craw Wurm"
        assert dop.effective_power == 6 and dop.effective_toughness == 4
        assert game._effective_colors(dop) == {"U"}

    def test_upkeep_offers_recopy_prompt_with_targets(self, cards):
        game, p1, p2, dop = self._enter_as_copy(cards)
        triggers = game.get_optional_upkeep_triggers(0)
        recopy = next(t for t in triggers if t["kind"] == "upkeep_recopy")
        assert recopy["card_name"] == "Vesuvan Doppelganger"
        assert recopy["needs_target"] == "creature"
        names = {t["name"] for t in recopy["valid_targets"]}
        assert names == {"Craw Wurm", "Black Knight"}

    def test_recopy_applies_and_still_stays_blue(self, cards):
        game, p1, p2, dop = self._enter_as_copy(cards)
        game.resolve_upkeep(
            0,
            optional_choices={"Vesuvan Doppelganger": True},
            trigger_targets={"Vesuvan Doppelganger": (1, 0)},
        )
        assert dop.copied_from == "Black Knight"
        assert dop.effective_power == 2 and dop.effective_toughness == 2
        assert game._effective_colors(dop) == {"U"}
        # The granted ability persists — it offers the prompt again next upkeep.
        assert any(t["kind"] == "upkeep_recopy" for t in game.get_optional_upkeep_triggers(0))

    def test_declined_recopy_keeps_the_current_copy(self, cards):
        game, p1, p2, dop = self._enter_as_copy(cards)
        game.resolve_upkeep(0, optional_choices={"Vesuvan Doppelganger": False})
        assert dop.copied_from == "Craw Wurm"

    def test_clone_copies_color(self, cards):
        wurm = Permanent(card=cards["Craw Wurm"])
        p1 = PlayerState(name="P1", hand=[cards["Clone"]], battlefield=[wurm])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Clone", target_player_index=0, target_permanent_index=0)
        clone = p1.battlefield[-1]
        assert clone.copied_from == "Craw Wurm"
        assert game._effective_colors(clone) == {"G"}


# ---------------------------------------------------------------------------
# Zombie Master — "It should give a {B}: regenerate activated ability to other
# zombies".
# ---------------------------------------------------------------------------

class TestZombieMasterRegenGrant:
    def test_grant_reaches_zombies_entering_later(self, cards):
        master = Permanent(card=cards["Zombie Master"])
        p1 = PlayerState(name="P1", battlefield=[master], hand=[cards["Scathe Zombies"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Scathe Zombies")
        zombie = p1.battlefield[-1]
        assert zombie.metadata.get("granted_regen_ability") is True
        assert game._has_keyword(zombie, "swampwalk")

    def test_grant_ends_when_master_leaves(self, cards):
        master = Permanent(card=cards["Zombie Master"])
        zombie = Permanent(card=cards["Scathe Zombies"])
        p1 = PlayerState(name="P1", battlefield=[master, zombie])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert zombie.metadata.get("granted_regen_ability") is True
        p1.battlefield.remove(master)
        game._recompute_continuous_effects()
        assert not zombie.metadata.get("granted_regen_ability")
        assert not game._has_keyword(zombie, "swampwalk")

    def test_activation_charges_black_mana(self, cards):
        master = Permanent(card=cards["Zombie Master"])
        zombie = Permanent(card=cards["Scathe Zombies"])
        p1 = PlayerState(name="P1", battlefield=[master, zombie])
        p2 = PlayerState(name="P2")
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = True
        game._recalculate_lord_buffs()

        # Without {B} the activation is refused.
        result = game.activate_permanent_ability(0, "Scathe Zombies")
        assert not result.supported
        assert zombie.regeneration_shield == 0

        # With {B} it pays and grants the shield.
        p1.mana_pool["B"] = 1
        result = game.activate_permanent_ability(0, "Scathe Zombies")
        assert result.supported
        assert zombie.regeneration_shield == 1
        assert p1.mana_pool["B"] == 0

    def test_granted_ability_is_serialized_for_the_ui(self, cards):
        from web.app import _serialize_permanent

        master = Permanent(card=cards["Zombie Master"])
        zombie = Permanent(card=cards["Scathe Zombies"])
        p1 = PlayerState(name="P1", battlefield=[master, zombie])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        data = _serialize_permanent(zombie, game)
        assert data["granted_abilities"] == ["{B}: Regenerate this permanent."]
        # The Master itself ("other") gets nothing.
        assert _serialize_permanent(master, game)["granted_abilities"] == []


# ---------------------------------------------------------------------------
# Mana Vault / Paralyze upkeep pays are covered in
# tests/test_failed_cards_regressions_batch9.py (updated in the same change):
# accepting the pay with an empty pool no longer untaps for free, and paying
# genuinely spends the {4} (pool first, then tapping lands).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Round 2 fixes (re-reported failures)
# ---------------------------------------------------------------------------

# Jade Monolith — "Source targeting should also include spells on the stack."
class TestJadeMonolithStackSource:
    def test_source_targets_include_stack_spells(self, cards):
        monolith = Permanent(card=cards["Jade Monolith"])
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[monolith, bears], hand=[cards["Lightning Bolt"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.queue_from_hand(0, "Lightning Bolt", target_player_index=0, target_permanent_index=1)
        spec = game.activation_target_spec(0, 0)
        stack_sources = [t for t in spec["source_targets"] if t["kind"] == "stack"]
        assert [t["name"] for t in stack_sources] == ["Lightning Bolt"]

    def test_spell_chosen_as_source_is_redirected(self, cards):
        monolith = Permanent(card=cards["Jade Monolith"])
        bears = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[monolith, bears], hand=[cards["Lightning Bolt"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.queue_from_hand(0, "Lightning Bolt", target_player_index=0, target_permanent_index=1)
        # Choose the queued Bolt (engine bottom-first index 0) as the source; the
        # activation resolves first, then the Bolt's damage is redirected to P1.
        result = game.activate_permanent_ability(
            0, "Jade Monolith", permanent_index=0,
            target_player_index=0, target_permanent_index=1,
            source_stack_index=0,
        )
        assert result.supported
        assert bears in p1.battlefield
        assert bears.damage_marked == 0
        assert p1.life == 17  # the Bolt's 3 damage hit the controller instead


# Volcanic Eruption — "It should make me target Mountains, not creatures": the
# backend target list for the divided prompt must contain only Mountains (the
# UI rejects clicks outside this list).
class TestVolcanicEruptionTargetList:
    def test_cast_spec_offers_only_mountains(self, cards):
        mountain = Permanent(card=cards["Mountain"])
        bears = Permanent(card=cards["Grizzly Bears"])
        their_mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", hand=[cards["Volcanic Eruption"]], battlefield=[mountain, bears])
        p2 = PlayerState(name="P2", battlefield=[their_mountain])
        game = _game(p1, p2)
        spec = game.cast_target_spec(0, cards["Volcanic Eruption"])
        # The hook's hand-written "divided" spec is retired; the grammar's
        # derivation narrows the same way — a land picker whose ``filter``
        # carries the printed subtype, applied by the enumeration itself.
        assert spec["kind"] == "land"
        assert spec["filter"] == {"subtype_filter": "mountain"}
        names = sorted(t.get("name", "player") for t in spec["valid_targets"])
        assert names == ["Mountain", "Mountain"]  # no creatures, no player faces


# Vesuvan Doppelganger / Clone — "The copy should not inherit modified
# power/toughness": copies take PRINTED P/T; continuous effects then re-apply
# dynamically based on the copy's own qualities.
class TestCopyUsesPrintedStats:
    def test_vesuvan_ignores_lord_buff_on_the_source(self, cards):
        moon = Permanent(card=cards["Bad Moon"])
        zombie = Permanent(card=cards["Scathe Zombies"])  # black 2/2, 3/3 under Bad Moon
        p1 = PlayerState(name="P1", hand=[cards["Vesuvan Doppelganger"]], battlefield=[moon, zombie])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert zombie.effective_power == 3  # sanity: the source is buffed
        game.cast_from_hand(0, "Vesuvan Doppelganger", target_player_index=0, target_permanent_index=1)
        dop = p1.battlefield[-1]
        # The blue copy gets the printed 2/2; Bad Moon doesn't buff a blue creature.
        assert (dop.effective_power, dop.effective_toughness) == (2, 2)

    def test_clone_copy_is_rebuffed_dynamically_not_doubled(self, cards):
        moon = Permanent(card=cards["Bad Moon"])
        zombie = Permanent(card=cards["Scathe Zombies"])
        p1 = PlayerState(name="P1", hand=[cards["Clone"]], battlefield=[moon, zombie])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        game.cast_from_hand(0, "Clone", target_player_index=0, target_permanent_index=1)
        clone = p1.battlefield[-1]
        # Black copy: printed 2/2 plus Bad Moon's +1/+1 applied once — never 4/4.
        assert (clone.effective_power, clone.effective_toughness) == (3, 3)


# Magical Hack — "I tried using magical hack to change mountainwalk to
# islandwalk on goblin king, so that other goblins would get islandwalk but it
# didn't work. Also the card text didn't get updated to show the change."
class TestMagicalHackRewritesGrantedText:
    def _hacked_king(self, cards):
        king = Permanent(card=cards["Goblin King"])
        raider = Permanent(card=cards["Mons's Goblin Raiders"])
        p1 = PlayerState(name="P1", hand=[cards["Magical Hack"]])
        p2 = PlayerState(name="P2", battlefield=[king, raider])
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert game._has_keyword(raider, "mountainwalk")  # sanity: grant active
        result = game.cast_from_hand(
            0, "Magical Hack",
            target_player_index=1, target_permanent_index=0,
            old_color="R", new_color="U",  # mountain -> island
        )
        assert result.supported
        return game, king, raider

    def test_other_goblins_get_islandwalk_after_the_hack(self, cards):
        game, king, raider = self._hacked_king(cards)
        assert game._has_keyword(raider, "islandwalk")
        assert not game._has_keyword(raider, "mountainwalk")

    def test_goblins_entering_later_get_the_remapped_walk(self, cards):
        game, king, raider = self._hacked_king(cards)
        newcomer = Permanent(card=cards["Mons's Goblin Raiders"])
        game.players[1].battlefield.append(newcomer)
        game._recalculate_lord_buffs()
        assert game._has_keyword(newcomer, "islandwalk")
        assert not game._has_keyword(newcomer, "mountainwalk")

    def test_text_change_is_serialized_for_the_ui(self, cards):
        from web.app import _text_change_replacements

        game, king, raider = self._hacked_king(cards)
        changes = _text_change_replacements(king)
        assert {"from": "mountainwalk", "to": "islandwalk"} in changes
