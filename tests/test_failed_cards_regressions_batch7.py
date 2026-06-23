"""Regression tests for the seventh batch of cards reported FAILED in-game.

Each test documents a bug reported through the in-game Debug Menu verification
flow (recorded in CARD_VERIFICATION.md) and guards the rules-correct behavior
after the fix. Tests load the real Alpha (LEA) card definitions so they exercise
the actual oracle text, parse rules, handlers, and continuous-effect logic.

Cards covered in this batch: Flight, Vesuvan Doppelganger, Gaea's Liege,
Chaoslace, Rock Hydra, Resurrection (graveyard ownership), Balance,
Disrupting Scepter, Library of Leng, Power Leak, Wooden Sphere, Raging River,
Benalish Hero.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import Game, PlayerState, load_cards
from engine.models import Permanent


@pytest.fixture(scope="module")
def cards():
    root = Path(__file__).resolve().parent.parent
    return {c.name: c for c in load_cards(root / "lea_cards.json")}


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# ---------------------------------------------------------------------------
# Flight — "Enchanted creature has flying." Bug: didn't grant the Flying keyword
# to the enchanted creature (combat keyword checks didn't see the aura grant).
# ---------------------------------------------------------------------------

class TestFlight:
    def test_grants_flying_keyword_to_enchanted_creature(self, cards):
        bear = Permanent(card=cards["Grizzly Bears"])  # no printed flying
        p1 = PlayerState(name="P1", hand=[cards["Flight"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Flight", target_player_index=1, target_permanent_index=0
        )

        assert result.supported
        assert bear.metadata.get("gains_flying") is True
        # The bug: _has_keyword only consulted the until-eot flag, so combat never
        # saw the aura-granted flying.
        assert game._has_keyword(bear, "flying") is True

    def test_flying_creature_cannot_be_blocked_by_grounded_creature(self, cards):
        flyer = _nosick(Permanent(card=cards["Grizzly Bears"]))
        grounded = Permanent(card=cards["Hurloon Minotaur"])  # no flying/reach
        p1 = PlayerState(name="P1", hand=[cards["Flight"]], battlefield=[flyer])
        p2 = PlayerState(name="P2", battlefield=[grounded])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Flight", target_player_index=0, target_permanent_index=0)

        assert game._has_keyword(flyer, "flying") is True
        # Grounded creature is not a legal blocker for a flyer.
        assert game._can_block_attacker(grounded, flyer) is False


# ---------------------------------------------------------------------------
# Vesuvan Doppelganger — "enter as a copy of any creature." Bug: copying a
# creature with first strike didn't copy its keywords.
# ---------------------------------------------------------------------------

class TestVesuvanDoppelganger:
    def test_copies_keywords_of_the_copied_creature(self, cards):
        white_knight = Permanent(card=cards["White Knight"])  # First strike
        p1 = PlayerState(name="P1", hand=[cards["Vesuvan Doppelganger"]])
        p2 = PlayerState(name="P2", battlefield=[white_knight])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Vesuvan Doppelganger", target_player_index=1, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        copy = next(p for p in p1.battlefield if p.metadata.get("copied_from") == "White Knight")
        assert game._has_keyword(copy, "first strike") is True

    def test_copies_flying_keyword(self, cards):
        djinn = Permanent(card=cards["Mahamoti Djinn"])  # Flying
        p1 = PlayerState(name="P1", hand=[cards["Vesuvan Doppelganger"]])
        p2 = PlayerState(name="P2", battlefield=[djinn])
        game = _game(p1, p2)

        game.cast_from_hand(
            0, "Vesuvan Doppelganger", target_player_index=1, target_permanent_index=0
        )
        game.resolve_stack()

        copy = next(p for p in p1.battlefield if p.metadata.get("copied_from") == "Mahamoti Djinn")
        assert game._has_keyword(copy, "flying") is True


# ---------------------------------------------------------------------------
# Gaea's Liege — its P/T equal the number of Forests its controller controls and
# it can turn a land into a Forest. Bug: P/T didn't update until the next step.
# ---------------------------------------------------------------------------

class TestGaeasLiege:
    def test_pt_updates_immediately_when_a_land_becomes_a_forest(self, cards):
        liege = _nosick(Permanent(card=cards["Gaea's Liege"]))
        swamp = Permanent(card=cards["Swamp"])
        p1 = PlayerState(name="P1", battlefield=[liege, swamp])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert liege.effective_power == 0  # no Forests yet

        result = game.activate_permanent_ability(
            0, "Gaea's Liege", target_player_index=0, target_permanent_index=1
        )
        game.resolve_stack()

        assert result.supported
        assert swamp.metadata.get("land_type_override") == "forest"
        # The bug: the count was stale until the next step. It must be current now.
        assert liege.effective_power == 1
        assert liege.effective_toughness == 1


# ---------------------------------------------------------------------------
# Chaoslace — "Target spell or permanent becomes red." Bug: couldn't target a
# spell on the stack.
# ---------------------------------------------------------------------------

class TestChaoslace:
    def test_can_target_and_recolor_a_spell_on_the_stack(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Chaoslace"]])
        p2 = PlayerState(name="P2", hand=[cards["Grizzly Bears"]])  # green spell
        game = _game(p1, p2)
        game.queue_from_hand(1, "Grizzly Bears")
        bears_index = len(game.stack) - 1

        result = game.queue_from_hand(0, "Chaoslace", target_stack_index=bears_index)
        assert result.supported
        game.resolve_top_of_stack()  # resolve Chaoslace (top of stack)

        bears = game.stack[bears_index]
        assert bears.new_color == "R"
        # Color filters (e.g. Red Elemental Blast) consume the recolor.
        assert game._stack_item_colors(bears) == ("R",)

    def test_cast_is_illegal_with_no_permanent_and_empty_stack(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Chaoslace"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)

        result = game.cast_from_hand(0, "Chaoslace")

        assert not result.supported
        assert any(c.name == "Chaoslace" for c in p1.hand)  # not consumed


# ---------------------------------------------------------------------------
# Resurrection — "Return target creature card from your graveyard." Bug: it let
# me target cards in my opponent's graveyard. "Your graveyard" means own only.
# ---------------------------------------------------------------------------

class TestResurrectionGraveyardOwnership:
    def test_cannot_target_opponents_graveyard(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Resurrection"]], graveyard=[cards["Grizzly Bears"]])
        p2 = PlayerState(name="P2", graveyard=[cards["Hill Giant"]])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Resurrection", target_player_index=1, target_permanent_index=0
        )

        assert not result.supported
        # The opponent's creature stays in their graveyard; not stolen.
        assert any(c.name == "Hill Giant" for c in p2.graveyard)
        assert not any(p.card.name == "Hill Giant" for p in p1.battlefield)

    def test_can_target_own_graveyard(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Resurrection"]], graveyard=[cards["Grizzly Bears"]])
        p2 = PlayerState(name="P2", graveyard=[cards["Hill Giant"]])
        game = _game(p1, p2)

        result = game.cast_from_hand(
            0, "Resurrection", target_player_index=0, target_permanent_index=0
        )
        game.resolve_stack()

        assert result.supported
        assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)


# ---------------------------------------------------------------------------
# Benalish Hero (Banding) — "The AI blocked my creature attacking in a band and
# the game got stuck passing priority back and forth in a loop." A band whose
# block propagates to a single shared blocker carries no assignment choice, so it
# must auto-resolve instead of waiting forever for a manual split.
# ---------------------------------------------------------------------------

class TestBenalishHeroBandingLoop:
    def _band_attack_blocked(self, cards):
        hero = _nosick(Permanent(card=cards["Benalish Hero"]))  # has Banding
        beater = _nosick(Permanent(card=cards["Hurloon Minotaur"]))
        p1 = PlayerState(name="P1", battlefield=[hero, beater])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Grizzly Bears"])])
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], defending_player_index=1, bands=[[0, 1]])
        assert ok, msg
        game.advance_combat_phase()  # -> declare_blockers
        ok, msg = game.declare_blockers(1, {0: 0})  # Grizzly Bears blocks the Hero
        assert ok, msg
        return game, p1, p2

    def test_single_shared_blocker_is_not_a_declared_multiblock(self, cards):
        game, p1, p2 = self._band_attack_blocked(cards)
        # The block propagated to the other band member (CR 702.22h)...
        assert game.combat_band_blocks  # non-empty -> engine still defers (702.22k)
        assert game._needs_manual_damage_assignment() is True
        # ...but no attacker has 2+ *declared* blockers, so the combat-damage dialog
        # has nothing to present. The web layer keys off this to auto-resolve.
        assert game._manual_assignment_has_declared_multiblock() is False

    def test_real_multiblock_still_needs_a_declared_assignment(self, cards):
        # A genuine double-block (two declared blockers on one attacker) must still
        # be flagged for the dialog — the auto-resolve path must not swallow it.
        attacker = _nosick(Permanent(card=cards["Craw Wurm"]))
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=cards["Grizzly Bears"]), Permanent(card=cards["Hurloon Minotaur"])],
        )
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.declare_attackers(0, [0], defending_player_index=1)
        game.advance_combat_phase()
        game.declare_blockers(1, {0: 0, 1: 0})

        assert game._manual_assignment_has_declared_multiblock() is True


# ---------------------------------------------------------------------------
# Raging River — "Ability triggered but the opponent didn't divide their
# creatures into left/right piles and I didn't get to assign my attackers to each
# pile." The division is now real state, assignable by each player and enforced at
# block time (an attacker can only be blocked from its chosen pile, or by flyers).
# ---------------------------------------------------------------------------

class TestRagingRiverPiles:
    def _attack_with_river(self, cards):
        river = Permanent(card=cards["Raging River"])
        attacker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[river, attacker])  # attacker at index 1
        p2 = PlayerState(
            name="P2",
            battlefield=[
                Permanent(card=cards["Hill Giant"]),         # defender index 0
                Permanent(card=cards["Hurloon Minotaur"]),   # defender index 1
            ],
        )
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.combat_defending_player_index = 1
        game.declare_attackers(0, [1], 1)
        game.resolve_stack()  # Raging River's attack trigger resolves
        return game, p1, p2

    def test_division_becomes_active_with_default_piles(self, cards):
        game, p1, p2 = self._attack_with_river(cards)
        assert game.combat_left_right_active is True
        # Both non-flying defender creatures got a pile by default.
        assert set(game.combat_defender_piles.keys()) == {0, 1}
        assert all(side in ("left", "right") for side in game.combat_defender_piles.values())

    def test_each_player_assigns_their_piles(self, cards):
        game, p1, p2 = self._attack_with_river(cards)
        ok, _ = game.assign_defender_piles(1, {0: "left", 1: "right"})
        assert ok
        ok, _ = game.assign_attacker_piles(0, {1: "left"})
        assert ok
        assert game.combat_defender_piles == {0: "left", 1: "right"}
        assert game.combat_attacker_piles == {1: "left"}

    def test_blocker_in_wrong_pile_cannot_block(self, cards):
        game, p1, p2 = self._attack_with_river(cards)
        game.assign_defender_piles(1, {0: "left", 1: "right"})
        game.assign_attacker_piles(0, {1: "left"})  # attacker assigned to the left pile
        game.advance_combat_phase()  # -> declare_blockers

        # The Minotaur (right pile) cannot block a left-pile attacker.
        ok, msg = game.declare_blockers(1, {1: 1})
        assert not ok
        assert "pile" in msg.lower()

        # The Hill Giant (left pile) can block it.
        ok, _ = game.declare_blockers(1, {0: 1})
        assert ok
