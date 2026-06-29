"""Regression tests for the eighth batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, continuous-effect logic, and the
backend legality/targeting queries the web UI relies on.

Clusters covered in this batch:
- Cluster A: the "lace" recolor spells (Purelace, Chaoslace, Deathlace,
  Lifelace, Thoughtlace) may target a permanent *or* a spell on the stack.
- Cluster B: the Circles of Protection (Blue/Green/Red/White) let the player
  choose a source on activation, and the shield only prevents damage from a
  source of the matching color.
- Cluster D: landwalk-granting lords (Goblin King, Lord of Atlantis) make other
  creatures of their subtype unblockable through the matching basic land, and a
  Vesuvan Doppelganger copying a lord becomes that subtype and grants its buffs.
- Cluster G: continuous effects end / reevaluate correctly (Animate Wall and
  Steal Artifact stop their effect when the Aura leaves, Wild Growth's bonus mana
  ends, Aspect of Wolf is recomputed as Forests change, Gaea's Liege reverts the
  lands it forested when it leaves the battlefield).
- Cluster H: spells/abilities that "didn't let me choose a target" now classify a
  target and enumerate legal ones (Blaze of Glory, False Orders, Regrowth,
  Twiddle, Dwarven Warriors, Icy Manipulator), and Royal Assassin offers only
  tapped creatures.
- Cluster J: characteristic-defining P/T is recomputed as a state-based action
  (Plague Rats shrink when one dies) and Living Artifact accrues vitality
  counters when its controller is dealt damage.
- Cluster E (engine choice): Lord of the Pit's upkeep sacrifice and the Sacrifice
  spell's as-cost sacrifice now honor an explicitly chosen creature (the engine
  foundation for the player's choice; the prompt is the web layer's job).
- Cluster L: Drain Life can hit a creature (and gains life from that), Crusade
  buffs a creature recolored white by a lace spell, Demonic Tutor shuffles the
  library after the search, and Copy Artifact becomes a true copy of the artifact.
- Cluster I/K: optional "you may pay {1}" triggers (Crystal Rod cycle, Soul Net)
  prompt and can be paid by tapping a land; Hypnotic Specter makes the defending
  player discard at random when it deals combat damage.
- Cluster K (more): Zombie Master grants other Zombies swampwalk; animated lands
  (Kormus Bell, Living Lands) can be declared as attackers; Dragon Whelp is
  sacrificed at the end step after its firebreathing is used four+ times.
- Cluster K (even more): Jade Statue animates into a 3/6 that can attack; Instill
  Energy's untap is once per turn; Veteran Bodyguard redirects unblocked combat
  damage from its controller to itself.
- Cluster K (final batch here): Berserk destroys the pumped creature at the end
  step if it attacked; Personal Incarnation redirects the next 1 damage to its
  owner; Jade Monolith redirects a creature's (combat) damage to a chosen player.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import Permanent


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
# Cluster A — "Lace" recolor spells. Bug: "Should be able to target both
# permanents and spells." They were classified as permanent-only, so the UI
# never offered a spell on the stack as a target.
# ---------------------------------------------------------------------------

class TestLaceTargetsSpellOrPermanent:
    LACE = {
        "Purelace": "W",
        "Chaoslace": "R",
        "Deathlace": "B",
        "Lifelace": "G",
        "Thoughtlace": "U",
    }

    def test_target_spec_kind_is_spell_or_permanent(self, cards):
        for name in self.LACE:
            p1 = PlayerState(name="P1", hand=[cards[name]])
            p2 = PlayerState(name="P2")
            game = _game(p1, p2)
            spec = game.cast_target_spec(0, cards[name])
            assert spec["kind"] == "spell_or_permanent", name
            assert spec["requires_target"] is True, name

    def test_offers_battlefield_permanent_as_target(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Purelace"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)
        spec = game.cast_target_spec(0, cards["Purelace"])
        perms = [t for t in spec["valid_targets"] if t["kind"] == "permanent"]
        assert any(t["name"] == "Grizzly Bears" for t in perms)

    def test_offers_spell_on_the_stack_as_target(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Purelace"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        spec = game.cast_target_spec(0, cards["Purelace"])
        stack_targets = [t for t in spec["valid_targets"] if t["kind"] == "stack"]
        assert any(t["name"] == "Lightning Bolt" for t in stack_targets)

    def test_recolors_targeted_permanent(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Deathlace"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Deathlace", target_player_index=1, target_permanent_index=0)
        assert bear.metadata.get("color_override") == "B"

    def test_recolors_spell_on_the_stack(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Chaoslace"]])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)  # stack=[bolt]
        game.queue_from_hand(0, "Chaoslace", target_stack_index=0)        # targets the bolt
        game.resolve_stack()
        assert any("became R" in line for line in game.log)


# ---------------------------------------------------------------------------
# Cluster B — Circles of Protection. Bug: "doesn't let me choose a source", and
# the shield wasn't restricted to the named color. Now activation prompts for a
# matching-color source (permanent or stack spell) and prevention is color-scoped.
# ---------------------------------------------------------------------------

class TestCirclesOfProtection:
    COP = {
        "Circle of Protection: Red": "R",
        "Circle of Protection: Blue": "U",
        "Circle of Protection: Green": "G",
        "Circle of Protection: White": "W",
    }

    def _game_with_cop(self, cards, cop_name):
        cop = Permanent(card=cards[cop_name])
        p1 = PlayerState(name="P1", battlefield=[cop])
        p2 = PlayerState(name="P2")
        return _game(p1, p2)

    def test_activation_requires_choosing_a_color_filtered_source(self, cards):
        for name, color in self.COP.items():
            game = self._game_with_cop(cards, name)
            spec = game.activation_target_spec(0, 0)
            assert spec["kind"] == "permanent", name
            assert spec["color_filter"] == color, name
            assert spec.get("also_stack") is True, name

    def test_offers_matching_color_spell_on_stack_as_source(self, cards):
        game = self._game_with_cop(cards, "Circle of Protection: Red")
        game.players[1].hand = [cards["Lightning Bolt"]]
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        spec = game.activation_target_spec(0, 0)
        names = [t["name"] for t in spec["valid_targets"] if t["kind"] == "stack"]
        assert "Lightning Bolt" in names

    def test_activation_arms_a_color_scoped_shield(self, cards):
        game = self._game_with_cop(cards, "Circle of Protection: Red")
        game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)
        assert game.players[0].color_prevention_shields == ["R"]

    def test_prevents_damage_from_matching_color_source(self, cards):
        game = self._game_with_cop(cards, "Circle of Protection: Red")
        game.players[1].hand = [cards["Lightning Bolt"]]
        game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.resolve_stack()
        assert game.players[0].life == 20  # 3 red damage fully prevented

    def test_does_not_prevent_damage_from_other_color(self, cards):
        game = self._game_with_cop(cards, "Circle of Protection: Red")
        game.players[1].hand = [cards["Psionic Blast"]]  # blue
        game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)
        game.queue_from_hand(1, "Psionic Blast", target_player_index=0)
        game.resolve_stack()
        assert game.players[0].life < 20  # blue damage unaffected by CoP: Red

    def test_shield_cleared_at_cleanup(self, cards):
        game = self._game_with_cop(cards, "Circle of Protection: Red")
        game.activate_permanent_ability(0, "Circle of Protection: Red", permanent_index=0)
        assert game.players[0].color_prevention_shields == ["R"]
        game.resolve_cleanup_step(0)
        assert game.players[0].color_prevention_shields == []


# ---------------------------------------------------------------------------
# Cluster D — landwalk-granting lords. Bug: Goblin King "not giving other goblins
# mountainwalk", Lord of Atlantis "isn't giving other merfolk islandwalk", and a
# Vesuvan Doppelganger copying Lord of Atlantis "didn't get the merfolk effects."
# ---------------------------------------------------------------------------

class TestLandwalkLords:
    def test_goblin_king_grants_mountainwalk_to_other_goblins(self, cards):
        king = Permanent(card=cards["Goblin King"])
        gob = Permanent(card=cards["Mons's Goblin Raiders"])
        p1 = PlayerState(name="P1", battlefield=[king, gob])
        mountain = Permanent(card=cards["Mountain"])
        blocker = Permanent(card=cards["Grizzly Bears"])
        p2 = PlayerState(name="P2", battlefield=[mountain, blocker])
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert gob.metadata.get("has_mountainwalk") is True
        # The goblin can't be blocked while the defender controls a Mountain.
        assert game._can_block_attacker(blocker, gob) is False
        # The King itself has no mountainwalk ("other" Goblins), so it is blockable.
        assert game._can_block_attacker(blocker, king) is True

    def test_lord_of_atlantis_grants_islandwalk_to_other_merfolk(self, cards):
        loa = Permanent(card=cards["Lord of Atlantis"])
        mer = Permanent(card=cards["Merfolk of the Pearl Trident"])
        p1 = PlayerState(name="P1", battlefield=[loa, mer])
        island = Permanent(card=cards["Island"])
        blocker = Permanent(card=cards["Grizzly Bears"])
        p2 = PlayerState(name="P2", battlefield=[island, blocker])
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert mer.metadata.get("has_islandwalk") is True
        assert game._can_block_attacker(blocker, mer) is False

    def test_lord_buff_removed_when_lord_leaves(self, cards):
        king = Permanent(card=cards["Goblin King"])
        gob = Permanent(card=cards["Mons's Goblin Raiders"])
        p1 = PlayerState(name="P1", battlefield=[king, gob])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert gob.metadata.get("has_mountainwalk") is True
        p1.battlefield.remove(king)
        game._recalculate_lord_buffs()
        assert not gob.metadata.get("has_mountainwalk")

    def test_vesuvan_doppelganger_copying_lord_of_atlantis(self, cards):
        loa = Permanent(card=cards["Lord of Atlantis"])
        mer = Permanent(card=cards["Merfolk of the Pearl Trident"])
        p1 = PlayerState(name="P1", battlefield=[loa, mer])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        dop = Permanent(card=cards["Vesuvan Doppelganger"])
        dop.metadata["copy_target"] = (0, 0)  # copy the Lord of Atlantis
        game._put_permanent_onto_battlefield(0, dop, None)
        # The copy becomes a Merfolk lord: it receives the other lord's buff/walk...
        assert dop.metadata.get("has_islandwalk") is True
        assert dop.metadata.get("static_buff_power") == 1
        # ...and the plain merfolk now benefits from BOTH lords.
        assert mer.metadata.get("static_buff_power") == 2
        assert mer.metadata.get("has_islandwalk") is True


# ---------------------------------------------------------------------------
# Cluster G — continuous effects must end / be recomputed correctly.
# ---------------------------------------------------------------------------

class TestContinuousEffectCleanup:
    def _remove(self, game, player, name):
        aura = next(p for p in player.battlefield if p.card.name == name)
        player.battlefield.remove(aura)
        game._permanent_to_graveyard(player, aura)

    def test_animate_wall_effect_ends_when_aura_removed(self, cards):
        wall = Permanent(card=cards["Wall of Stone"])
        p1 = PlayerState(name="P1", hand=[cards["Animate Wall"]], battlefield=[wall])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Animate Wall", target_player_index=0, target_permanent_index=0)
        assert wall.metadata.get("can_attack_as_though_no_defender") is True
        self._remove(game, p1, "Animate Wall")
        assert not wall.metadata.get("can_attack_as_though_no_defender")

    def test_wild_growth_bonus_mana_ends_when_aura_removed(self, cards):
        land = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", hand=[cards["Wild Growth"]], battlefield=[land])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)
        assert land.metadata.get("attached_aura") is not None
        self._remove(game, p1, "Wild Growth")
        assert land.metadata.get("attached_aura") is None

    def test_steal_artifact_returns_control_when_destroyed(self, cards):
        art = Permanent(card=cards["Sol Ring"])
        owner = PlayerState(name="Owner", battlefield=[art])
        thief = PlayerState(name="Thief", hand=[cards["Steal Artifact"]])
        game = _game(thief, owner)
        game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)
        assert any(p.card.name == "Sol Ring" for p in thief.battlefield)
        self._remove(game, thief, "Steal Artifact")
        assert any(p.card.name == "Sol Ring" for p in owner.battlefield)
        assert not any(p.card.name == "Sol Ring" for p in thief.battlefield)

    def test_aspect_of_wolf_recomputes_as_forests_change(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # 2/2
        forests = [Permanent(card=cards["Forest"]) for _ in range(3)]
        p1 = PlayerState(name="P1", hand=[cards["Aspect of Wolf"]], battlefield=[bear, *forests])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)
        # 3 Forests -> +1/+2 -> 3/4
        assert (bear.effective_power, bear.effective_toughness) == (3, 4)
        # A 4th Forest enters -> +2/+2 -> 4/4 (recomputed as a state reevaluation)
        game._put_permanent_onto_battlefield(0, Permanent(card=cards["Forest"]), None)
        assert (bear.effective_power, bear.effective_toughness) == (4, 4)

    def test_gaeas_liege_reverts_forested_lands_when_it_leaves(self, cards):
        liege = Permanent(card=cards["Gaea's Liege"])
        forest = Permanent(card=cards["Forest"])  # keeps Liege at 1/1 so it survives
        plains = Permanent(card=cards["Plains"])
        p1 = PlayerState(name="P1", battlefield=[liege, forest])
        p2 = PlayerState(name="P2", battlefield=[plains])
        game = _game(p1, p2)
        game.activate_permanent_ability(
            0, "Gaea's Liege", permanent_index=0, target_player_index=1, target_permanent_index=0
        )
        assert plains.metadata.get("land_type_override") == "forest"
        p1.battlefield.remove(liege)
        game._permanent_to_graveyard(p1, liege)
        assert plains.metadata.get("land_type_override") is None


# ---------------------------------------------------------------------------
# Cluster H — target selection prompts. Bug: several spells/abilities "didn't let
# me choose a target" because they classified as targetless.
# ---------------------------------------------------------------------------

class TestTargetSelectionPrompts:
    def _board(self):
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=_C["Grizzly Bears"])])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=_C["Hill Giant"])])
        return _game(p1, p2)

    def test_blaze_of_glory_targets_a_creature(self):
        game = self._board()
        spec = game.cast_target_spec(0, _C["Blaze of Glory"])
        assert spec["kind"] == "creature" and spec["requires_target"]
        assert len(spec["valid_targets"]) >= 1

    def test_false_orders_targets_a_creature(self):
        game = self._board()
        spec = game.cast_target_spec(0, _C["False Orders"])
        assert spec["kind"] == "creature" and spec["requires_target"]

    def test_twiddle_targets_any_permanent(self):
        game = self._board()
        spec = game.cast_target_spec(0, _C["Twiddle"])
        assert spec["kind"] == "permanent" and spec["requires_target"]

    def test_regrowth_targets_any_card_in_own_graveyard(self):
        game = self._board()
        game.players[0].graveyard.extend([_C["Lightning Bolt"], _C["Grizzly Bears"]])
        spec = game.cast_target_spec(0, _C["Regrowth"])
        assert spec["kind"] == "graveyard_creature" and spec["requires_target"]
        names = {t["name"] for t in spec["valid_targets"]}
        # Includes the noncreature card (Lightning Bolt), not just creatures.
        assert "Lightning Bolt" in names and "Grizzly Bears" in names

    def test_dwarven_warriors_targets_a_creature(self):
        game = self._board()
        dw = Permanent(card=_C["Dwarven Warriors"])
        dw.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(dw)
        spec = game.activation_target_spec(0, len(game.players[0].battlefield) - 1)
        assert spec["kind"] == "creature" and spec["requires_target"]

    def test_icy_manipulator_targets_any_permanent(self):
        game = self._board()
        icy = Permanent(card=_C["Icy Manipulator"])
        icy.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(icy)
        spec = game.activation_target_spec(0, len(game.players[0].battlefield) - 1)
        assert spec["kind"] == "permanent" and spec["requires_target"]

    def test_royal_assassin_offers_only_tapped_creatures(self):
        game = self._board()
        tapped = Permanent(card=_C["Hurloon Minotaur"])
        tapped.tapped = True
        game.players[1].battlefield.append(tapped)  # opp: Hill Giant (untapped) + Hurloon (tapped)
        ra = Permanent(card=_C["Royal Assassin"])
        ra.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(ra)
        spec = game.activation_target_spec(0, len(game.players[0].battlefield) - 1)
        names = {t["name"] for t in spec["valid_targets"]}
        assert names == {"Hurloon Minotaur"}


# ---------------------------------------------------------------------------
# Cluster J — characteristic-defining P/T recount (SBA) and counters.
# ---------------------------------------------------------------------------

class TestCountersAndRecount:
    def test_plague_rats_shrink_when_one_dies(self, cards):
        rats = [Permanent(card=cards["Plague Rats"]) for _ in range(3)]
        p1 = PlayerState(name="P1", battlefield=list(rats))
        game = _game(p1, PlayerState(name="P2"))
        game._refresh_dynamic_creatures()
        assert all((r.effective_power, r.effective_toughness) == (3, 3) for r in rats)
        dead = rats[0]
        p1.battlefield.remove(dead)
        game._permanent_to_graveyard(p1, dead)
        game.check_state_based_actions()
        assert all((r.effective_power, r.effective_toughness) == (2, 2) for r in p1.battlefield)

    def test_living_artifact_gains_vitality_counters_when_dealt_damage(self, cards):
        art = Permanent(card=cards["Mox Pearl"])
        p1 = PlayerState(name="P1", hand=[cards["Living Artifact"]], battlefield=[art])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Living Artifact", target_player_index=0, target_permanent_index=0)
        aura = next(p for p in p1.battlefield if p.card.name == "Living Artifact")
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.resolve_stack()
        assert aura.metadata.get("vitality_counters") == 3


# ---------------------------------------------------------------------------
# Cluster L — assorted engine fixes.
# ---------------------------------------------------------------------------

class TestMiscEngineFixes:
    def test_drain_life_gains_life_when_hitting_a_player(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Drain Life"]], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Drain Life", target_player_index=1, x_value=3)
        assert p2.life == 17
        assert p1.life == 23

    def test_drain_life_can_target_a_creature_and_gain_life(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", hand=[cards["Drain Life"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[bear], life=20)
        game = _game(p1, p2)
        game.cast_from_hand(0, "Drain Life", target_player_index=1, target_permanent_index=0, x_value=2)
        assert p2.life == 20            # the player is untouched
        assert p1.life == 22            # life gained from the creature damage
        assert not any(p.card.name == "Grizzly Bears" for p in p2.battlefield)  # 2 lethal to a 2/2

    def test_crusade_buffs_creature_recolored_white(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # green 2/2
        p1 = PlayerState(name="P1", hand=[cards["Purelace"], cards["Crusade"]], battlefield=[bear])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Crusade")
        assert (bear.effective_power, bear.effective_toughness) == (2, 2)  # not white yet
        game.cast_from_hand(0, "Purelace", target_player_index=0, target_permanent_index=0)
        game._recalculate_lord_buffs()
        assert bear.metadata.get("color_override") == "W"
        assert (bear.effective_power, bear.effective_toughness) == (3, 3)  # Crusade now applies

    def test_demonic_tutor_shuffles_library_after_search(self, cards):
        import random
        lib = [cards["Forest"], cards["Mountain"], cards["Swamp"], cards["Island"], cards["Plains"]]
        p1 = PlayerState(name="P1", hand=[cards["Demonic Tutor"]], library=list(lib))
        game = _game(p1, PlayerState(name="P2"))
        random.seed(1)
        game.cast_from_hand(0, "Demonic Tutor")
        assert game.pending_search_library is not None
        game.confirm_search_library(0, 0)  # take the Forest
        assert any(c.name == "Forest" for c in p1.hand)
        remaining = [c.name for c in p1.library]
        assert sorted(remaining) == sorted(["Mountain", "Swamp", "Island", "Plains"])
        # Shuffled: order differs from the original library minus the tutored card.
        assert remaining != ["Mountain", "Swamp", "Island", "Plains"]

    def test_copy_artifact_becomes_a_copy_of_the_artifact(self, cards):
        sol = Permanent(card=cards["Sol Ring"])
        p1 = PlayerState(name="P1", hand=[cards["Copy Artifact"]], battlefield=[sol])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Copy Artifact", target_player_index=0, target_permanent_index=0)
        copy = next(p for p in p1.battlefield if p is not sol and p.metadata.get("copied_from") == "Sol Ring")
        # It copies the artifact's name, abilities and produced mana, and is also an Enchantment.
        assert copy.card.name == "Sol Ring"
        assert "enchantment" in copy.card.type_line.lower()
        assert "artifact" in copy.card.type_line.lower()
        assert tuple(copy.card.produced_mana) == tuple(cards["Sol Ring"].produced_mana)


# ---------------------------------------------------------------------------
# Cluster E (engine) — sacrifice effects honor the player's chosen creature.
# ---------------------------------------------------------------------------

class TestSacrificeChoice:
    def test_lord_of_the_pit_sacrifices_the_chosen_creature(self, cards):
        lotp = Permanent(card=cards["Lord of the Pit"])
        grizzly = Permanent(card=cards["Grizzly Bears"])
        giant = Permanent(card=cards["Hill Giant"])
        p1 = PlayerState(name="P1", battlefield=[lotp, grizzly, giant], life=20)
        game = _game(p1, PlayerState(name="P2"))
        game.resolve_upkeep(0, sacrifice_choices={"Lord of the Pit": 2})  # choose Hill Giant
        names = [p.card.name for p in p1.battlefield]
        assert "Hill Giant" not in names
        assert "Grizzly Bears" in names and "Lord of the Pit" in names
        assert p1.life == 20  # had a creature to sacrifice, so no 7 damage

    def test_lord_of_the_pit_auto_picks_when_no_choice_given(self, cards):
        lotp = Permanent(card=cards["Lord of the Pit"])
        grizzly = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[lotp, grizzly], life=20)
        game = _game(p1, PlayerState(name="P2"))
        game.resolve_upkeep(0)
        assert not any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    def test_sacrifice_spell_uses_chosen_creatures_mana_value(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])   # CMC 2
        giant = Permanent(card=cards["Hill Giant"])     # CMC 4 ({3}{R})
        p1 = PlayerState(name="P1", hand=[cards["Sacrifice"]], battlefield=[bear, giant])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Sacrifice", target_player_index=0, target_permanent_index=1)  # the Giant
        assert not any(p.card.name == "Hill Giant" for p in p1.battlefield)
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
        assert p1.mana_pool["B"] == 4  # equal to the sacrificed creature's mana value


# ---------------------------------------------------------------------------
# Cluster I / K — optional "you may pay {1}" triggers and combat-damage triggers.
# ---------------------------------------------------------------------------

class TestOptionalTriggersAndCombatDamage:
    def test_crystal_rod_prompts_and_pays_by_tapping_a_land(self, cards):
        rod = Permanent(card=cards["Crystal Rod"])
        island = Permanent(card=cards["Island"])  # untapped land, no floating mana
        p1 = PlayerState(name="P1", battlefield=[rod, island], life=20)
        p2 = PlayerState(name="P2", hand=[cards["Merfolk of the Pearl Trident"]])  # blue
        game = _game(p1, p2)
        game.queue_from_hand(1, "Merfolk of the Pearl Trident")
        game.resolve_stack()
        assert any(e["card_name"] == "Crystal Rod" for e in game.pending_optional_pays)
        game.confirm_optional_pay(0, "Crystal Rod", accept=True)
        assert p1.life == 21
        assert island.tapped is True  # paid the {1} by tapping the land

    def test_soul_net_prompts_when_a_creature_dies(self, cards):
        net = Permanent(card=cards["Soul Net"])
        swamp = Permanent(card=cards["Swamp"])  # untapped land to pay with
        victim = Permanent(card=cards["Grizzly Bears"])
        p1 = PlayerState(name="P1", battlefield=[net, swamp], life=20)
        p2 = PlayerState(name="P2", battlefield=[victim])
        game = _game(p1, p2)
        p2.battlefield.remove(victim)
        game._permanent_to_graveyard(p2, victim)
        # The dies-trigger goes on the stack; its pay-prompt is raised on resolution.
        game.resolve_stack()
        assert any(e["card_name"] == "Soul Net" for e in game.pending_optional_pays)
        game.confirm_optional_pay(0, "Soul Net", accept=True)
        assert p1.life == 21
        assert swamp.tapped is True

    def test_hypnotic_specter_forces_random_discard_on_combat_damage(self, cards):
        spec = Permanent(card=cards["Hypnotic Specter"])
        spec.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[spec])
        p2 = PlayerState(name="P2", hand=[cards["Forest"], cards["Mountain"]])
        game = _game(p1, p2)
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # beginning_of_combat
        game.advance_combat_phase()  # declare_attackers
        game.declare_attackers(0, [0])
        game.advance_combat_phase()  # declare_blockers
        game.declare_blockers(1, {})  # no blocks -> unblocked
        game.advance_combat_phase()  # combat_damage resolves
        assert p2.life == 18  # 2 flying damage
        assert len(p2.hand) == 1  # discarded one card at random
        assert len(p2.graveyard) == 1


# ---------------------------------------------------------------------------
# Cluster K (more) — keyword-granting lords, animated lands, delayed sacrifice.
# ---------------------------------------------------------------------------

class TestMoreCombatAndAbilities:
    def test_zombie_master_grants_swampwalk_to_other_zombies(self, cards):
        zm = Permanent(card=cards["Zombie Master"])
        zombie = Permanent(card=cards["Scathe Zombies"])
        p1 = PlayerState(name="P1", battlefield=[zm, zombie])
        swamp = Permanent(card=cards["Swamp"])
        blocker = Permanent(card=cards["Grizzly Bears"])
        p2 = PlayerState(name="P2", battlefield=[swamp, blocker])
        game = _game(p1, p2)
        game._recalculate_lord_buffs()
        assert zombie.metadata.get("has_swampwalk") is True
        assert game._can_block_attacker(blocker, zombie) is False

    def test_kormus_bell_swamp_can_attack(self, cards):
        bell = Permanent(card=cards["Kormus Bell"])
        swamp = Permanent(card=cards["Swamp"])
        swamp.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[bell, swamp])
        game = _game(p1, PlayerState(name="P2"))
        game._refresh_dynamic_creatures()
        assert 1 in game.legal_attacker_indices(0)  # the animated Swamp

    def test_living_lands_forest_can_attack(self, cards):
        ll = Permanent(card=cards["Living Lands"])
        forest = Permanent(card=cards["Forest"])
        forest.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[ll, forest])
        game = _game(p1, PlayerState(name="P2"))
        game._refresh_dynamic_creatures()
        assert 1 in game.legal_attacker_indices(0)  # the animated Forest

    def test_dragon_whelp_sacrificed_after_four_activations(self, cards):
        dw = Permanent(card=cards["Dragon Whelp"])
        dw.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[dw])
        game = _game(p1, PlayerState(name="P2"))
        for _ in range(4):
            game.activate_permanent_ability(0, "Dragon Whelp", permanent_index=0)
        assert dw.metadata.get("sacrifice_at_next_end_step") is True
        game.resolve_end_step(0)
        assert not any(p.card.name == "Dragon Whelp" for p in p1.battlefield)
        assert any(c.name == "Dragon Whelp" for c in p1.graveyard)

    def test_dragon_whelp_survives_three_activations(self, cards):
        dw = Permanent(card=cards["Dragon Whelp"])
        dw.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[dw])
        game = _game(p1, PlayerState(name="P2"))
        for _ in range(3):
            game.activate_permanent_ability(0, "Dragon Whelp", permanent_index=0)
        game.resolve_end_step(0)
        assert any(p.card.name == "Dragon Whelp" for p in p1.battlefield)

    def test_jade_statue_animates_and_can_attack(self, cards):
        js = Permanent(card=cards["Jade Statue"])
        js.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[js])
        game = _game(p1, PlayerState(name="P2"))
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # beginning_of_combat
        game.advance_combat_phase()  # declare_attackers
        result = game.activate_permanent_ability(0, "Jade Statue", permanent_index=0)
        assert result.supported
        assert (js.effective_power, js.effective_toughness) == (3, 6)
        assert game._is_creature(js)
        assert 0 in game.legal_attacker_indices(0)

    def test_instill_energy_untap_is_once_per_turn(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        bear.tapped = True
        p1 = PlayerState(name="P1", hand=[cards["Instill Energy"]], battlefield=[bear])
        game = _game(p1, PlayerState(name="P2"))
        game.start_turn(0)
        game.cast_from_hand(0, "Instill Energy", target_player_index=0, target_permanent_index=0)
        ie_idx = next(i for i, p in enumerate(p1.battlefield) if p.card.name == "Instill Energy")
        assert game.activate_permanent_ability(0, "Instill Energy", permanent_index=ie_idx).supported
        assert bear.tapped is False
        bear.tapped = True  # re-tap to attempt a second untap
        second = game.activate_permanent_ability(0, "Instill Energy", permanent_index=ie_idx)
        assert not second.supported  # only once each turn
        assert bear.tapped is True

    def test_veteran_bodyguard_redirects_unblocked_combat_damage(self, cards):
        attacker = Permanent(card=cards["Hill Giant"])  # 3/3
        attacker.metadata["summoning_sickness_turn"] = -99
        bg = Permanent(card=cards["Veteran Bodyguard"])  # untapped
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[bg], life=20)
        game = _game(p1, p2)
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # beginning_of_combat
        game.advance_combat_phase()  # declare_attackers
        game.declare_attackers(0, [0])
        game.advance_combat_phase()  # declare_blockers
        game.declare_blockers(1, {})  # no blocks
        game.advance_combat_phase()  # combat damage
        game.check_state_based_actions()
        assert p2.life == 20            # the player took no damage
        assert bg.damage_marked == 3    # the bodyguard took it instead

    def test_berserk_destroys_attacker_at_end_step(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])
        bear.metadata["attacked_this_turn"] = True
        p1 = PlayerState(name="P1", hand=[cards["Berserk"]], battlefield=[bear])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Berserk", target_player_index=0, target_permanent_index=0)
        assert bear.effective_power == 4  # +X/+0 where X = power (2)
        assert bear.metadata.get("destroy_if_attacked_eot") is True
        game.resolve_end_step(0)
        assert not any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    def test_berserk_does_not_destroy_a_creature_that_did_not_attack(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # never attacked
        p1 = PlayerState(name="P1", hand=[cards["Berserk"]], battlefield=[bear])
        game = _game(p1, PlayerState(name="P2"))
        game.cast_from_hand(0, "Berserk", target_player_index=0, target_permanent_index=0)
        game.resolve_end_step(0)
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    def test_personal_incarnation_redirects_one_damage_to_owner(self, cards):
        pi = Permanent(card=cards["Personal Incarnation"])
        pi.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[pi], life=20)
        game = _game(p1, PlayerState(name="P2"))
        game.activate_permanent_ability(0, "Personal Incarnation", permanent_index=0)
        assert pi.metadata.get("redirect_one_damage_to_owner_until_eot") == 1
        dealt = game._mark_damage_on_permanent(pi, 3)
        assert dealt == 2          # one point was redirected away from the creature
        assert pi.damage_marked == 2
        assert p1.life == 19       # the owner took the redirected point

    def test_jade_monolith_redirects_combat_damage_to_chosen_player(self, cards):
        jm = Permanent(card=cards["Jade Monolith"])
        blocker = Permanent(card=cards["Grizzly Bears"])
        blocker.metadata["summoning_sickness_turn"] = -99
        attacker = Permanent(card=cards["Hill Giant"])  # 3/3
        attacker.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[jm, blocker], life=20)  # defender
        p2 = PlayerState(name="P2", battlefield=[attacker], life=20)     # attacker, active
        game = _game(p1, p2)
        game.start_turn(1)
        game._close_current_priority_step()
        game.advance_combat_phase()  # beginning_of_combat
        game.advance_combat_phase()  # declare_attackers
        game.declare_attackers(1, [0])
        game.advance_combat_phase()  # declare_blockers
        game.declare_blockers(0, {1: 0})  # P1's Grizzly (idx 1) blocks the attacker
        game.activate_permanent_ability(
            0, "Jade Monolith", permanent_index=0, target_player_index=0, target_permanent_index=1
        )
        game.advance_combat_phase()  # combat damage
        game.check_state_based_actions()
        assert blocker.damage_marked == 0  # the creature's damage was redirected
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)  # survived
        assert p1.life == 17  # the controller took the 3 damage instead
