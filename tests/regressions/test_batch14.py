"""Regression tests for the fourteenth batch of bugs reported in-game
(CARD_VERIFICATION.md failures).

Clusters covered in this batch:
- Blaze of Glory: the marked creature "blocks each attacking creature this turn
  if able" is ENFORCED at declare-blockers (previously the marker was written
  but never read), and the AI blocker chooser satisfies it.
- Channel: the activation prompt renders (the priority-prompt guard in app.js
  must include pendingChannel or the emblem click is swallowed).
- Copy Artifact: the copy is a runtime overlay (like Clone / Vesuvan
  Doppelganger) — permanent.card stays Copy Artifact so the card reverts when
  it changes zones; abilities/mana come from effective_card.
- Gloom: activated abilities of white enchantments cost {3} more to activate.
- Illusionary Mask: a face-down creature is turned face up when it takes
  damage, deals damage, or becomes tapped.
- Kormus Bell: an animated Swamp can block (engine legality + the serialized
  is_creature flag the client-side check relies on).
- Library of Leng: a random/forced discard (Mind Twist on yourself) routes the
  discarded cards to the top of the library.
- Living Artifact: the upkeep trigger is optional — surfaced as a yes/no
  prompt and honoring the player's decision.
- Regrowth: returns ANY card type from your graveyard (not creatures only),
  honoring the chosen graveyard index.
- Reverse Damage: the chosen-source shield prevents that source's combat
  damage and gains that much life; source is threaded through non-combat
  damage paths (Manabarbs-style) so shields can match them.
- Rock Hydra: "{R}: Prevent the next 1 damage that would be dealt to this
  creature" arms the shield on Rock Hydra itself (not the opponent player).
- Scavenging Ghoul: counter badges stack above the P/T badge on the canvas.
- Smoke: over-selecting untap creatures names the constrained type
  ("creatures", not "lands").
- Two-Headed Giant of Foriys: the defending player divides a multi-blocking
  creature's combat damage among the attackers it blocks (CR 510.1d), via the
  engine pre-commit and the assign_multiblock_damage web action.
- Word of Command: the game cannot advance past a human caster's pending
  card choice.
"""
from __future__ import annotations

import random
from engine.keywords import grant_keyword, remove_keyword
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, load_cards
from engine.ai_policy import choose_combat_blockers
from engine.models import CardDefinition, Permanent
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store

client = TestClient(app)

_ROOT = Path(__file__).resolve().parent.parent.parent


def _mk_creature(name: str, power: int, toughness: int, keywords=()) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text="\n".join(keywords),
        colors=(),
        color_identity=(),
        keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _new_session(mode="human_vs_ai", seed=7) -> str:
    payload = {"mode": mode, "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": seed}
    if mode == "human_vs_human":
        payload["guest_name"] = "G"
    created = client.post("/api/sessions", json=payload).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "J"})
    return sid


# ---------------------------------------------------------------------------
# Blaze of Glory — "It didn't force me to block all valid block targets"
# ---------------------------------------------------------------------------

class TestBlazeOfGloryForcedBlocks:
    def _combat(self, cards):
        a1 = _nosick(Permanent(card=_mk_creature("Attacker One", 2, 2)))
        a2 = _nosick(Permanent(card=_mk_creature("Attacker Two", 2, 2)))
        blocker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        blocker.metadata["can_block_any_number_until_eot"] = True
        blocker.metadata["must_block_all_until_eot"] = True
        p1 = PlayerState(name="P1", battlefield=[a1, a2])
        p2 = PlayerState(name="P2", battlefield=[blocker])
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], 1)
        assert ok, msg
        game.advance_combat_phase()  # declare_blockers
        return game

    def test_partial_block_is_rejected(self, cards):
        game = self._combat(cards)
        ok, msg = game.declare_blockers(1, {0: [0]})
        assert not ok
        assert "must block" in msg and "Blaze of Glory" in msg

    def test_declining_to_block_is_rejected(self, cards):
        game = self._combat(cards)
        ok, msg = game.declare_blockers(1, {})
        assert not ok
        assert "Blaze of Glory" in msg

    def test_blocking_every_attacker_is_accepted(self, cards):
        game = self._combat(cards)
        ok, msg = game.declare_blockers(1, {0: [0, 1]})
        assert ok, msg

    def test_unblockable_attackers_are_not_required(self, cards):
        game = self._combat(cards)
        # Attacker One gains flying; the ground blocker can't block it, so only
        # Attacker Two is required ("if able").
        grant_keyword(game.players[0].battlefield[0], "flying", until_eot=True)
        ok, msg = game.declare_blockers(1, {0: [1]})
        assert ok, msg

    def test_ai_blocker_chooser_satisfies_requirement(self, cards):
        game = self._combat(cards)
        assignments = choose_combat_blockers(game, 1)
        ok, msg = game.declare_blockers(1, assignments)
        assert ok, msg
        assert sorted(game.combat_blockers.get(1, {}).get(0, [])) == [0, 1]


# ---------------------------------------------------------------------------
# Channel — "I don't get a prompt when I activate channel's emblem ability"
# ---------------------------------------------------------------------------

def test_channel_prompt_guard_includes_pending_channel():
    # The priority-prompt block in renderActivationPrompt must skip rendering
    # while a Channel activation is pending, or the Channel prompt (which is
    # rendered later in the function) never appears.
    app_js = (_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
    guard = next(
        (line for line in app_js.splitlines()
         if "!pendingActivation && !pendingCastTarget && !pendingCastX" in line),
        None,
    )
    assert guard is not None
    assert "!pendingChannel" in guard


# ---------------------------------------------------------------------------
# Copy Artifact — "should work similar to Vesuvan Doppelganger ... when the
# card changes zones it reverts back to Copy Artifact"
# ---------------------------------------------------------------------------

class TestCopyArtifactOverlay:
    def _copy_of_sol_ring(self, cards):
        sol = Permanent(card=cards["Sol Ring"])
        p1 = PlayerState(name="P1", hand=[cards["Copy Artifact"]], battlefield=[sol])
        game = _game(p1, PlayerState(name="P2"))
        result = game.cast_from_hand(0, "Copy Artifact", target_player_index=0, target_permanent_index=0)
        assert result.supported
        copy = next(p for p in p1.battlefield if p is not sol and p.copied_from == "Sol Ring")
        return game, p1, copy

    def test_copy_is_an_overlay_not_a_card_swap(self, cards):
        game, p1, copy = self._copy_of_sol_ring(cards)
        assert copy.card.name == "Copy Artifact"  # underlying identity kept
        assert copy.effective_card.name == "Sol Ring"
        assert "artifact" in copy.effective_card.type_line.lower()
        assert "enchantment" in copy.effective_card.type_line.lower()
        assert tuple(copy.effective_produced_mana) == tuple(cards["Sol Ring"].produced_mana)

    def test_copy_reverts_when_it_changes_zones(self, cards):
        game, p1, copy = self._copy_of_sol_ring(cards)
        game._permanent_to_graveyard(p1, copy)
        p1.battlefield.remove(copy)
        # The card that reaches the graveyard is Copy Artifact, not Sol Ring.
        assert any(c.name == "Copy Artifact" for c in p1.graveyard)
        assert not any(c.name == "Sol Ring" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Gloom — "The activated ability cost of white enchantments didn't increase"
# ---------------------------------------------------------------------------

class TestGloomActivationSurcharge:
    def _cop_game(self, cards, with_gloom: bool):
        cop = Permanent(card=cards["Circle of Protection: Red"])
        p1 = PlayerState(name="P1", battlefield=[cop])
        p2 = PlayerState(name="P2")
        if with_gloom:
            p2.battlefield.append(Permanent(card=cards["Gloom"]))
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = True
        return game, p1

    def test_printed_cost_suffices_without_gloom(self, cards):
        game, p1 = self._cop_game(cards, with_gloom=False)
        p1.mana_pool["W"] = 1
        result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=1, permanent_index=0)
        assert result.supported, result.details

    def test_printed_cost_is_insufficient_under_gloom(self, cards):
        game, p1 = self._cop_game(cards, with_gloom=True)
        p1.mana_pool["W"] = 1
        result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=1, permanent_index=0)
        assert not result.supported
        assert "insufficient mana" in result.details

    def test_cost_plus_three_succeeds_under_gloom(self, cards):
        game, p1 = self._cop_game(cards, with_gloom=True)
        p1.mana_pool["W"] = 4
        result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=1, permanent_index=0)
        assert result.supported, result.details

    def test_nonwhite_enchantment_ability_is_untaxed(self, cards):
        # Gloom itself only taxes WHITE enchantments' abilities.
        cop_blue = Permanent(card=cards["Circle of Protection: Blue"])
        p1 = PlayerState(name="P1", battlefield=[cop_blue])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Gloom"])])
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = True
        p1.mana_pool["W"] = 1
        # CoP: Blue is a white enchantment too — use an artifact ability instead
        # to prove type/color scoping: Rod of Ruin (artifact) stays untaxed.
        rod = Permanent(card=cards["Rod of Ruin"])
        _nosick(rod)
        p1.battlefield.append(rod)
        p1.mana_pool["C"] = 3
        result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1, permanent_index=1)
        assert result.supported, result.details


# ---------------------------------------------------------------------------
# Illusionary Mask — "face down cards aren't being turned face up when they
# take damage, deal damage or become tapped"
# ---------------------------------------------------------------------------

class TestIllusionaryMaskTurnsFaceUp:
    def _face_down_bear(self, cards, extra_hand=()):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Grizzly Bears"], *[cards[n] for n in extra_hand]],
            battlefield=[Permanent(card=cards["Illusionary Mask"])],
        )
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]], life=20)
        game = _game(p1, p2)
        result = game.queue_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert result.supported, result.details
        game.resolve_top_of_stack()
        assert game.confirm_face_down_cast(0, 0) is True
        face_down = p1.battlefield[-1]
        assert face_down.metadata.get("face_down") is True
        assert face_down.card.oracle_text == ""
        return game, p1, p2, face_down

    def test_turned_face_up_when_dealt_damage(self, cards):
        game, p1, p2, perm = self._face_down_bear(cards)
        idx = p1.battlefield.index(perm)
        result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=idx)
        assert result.supported
        assert perm.metadata.get("face_down") is None
        assert perm.card.name == "Grizzly Bears"
        assert perm.effective_toughness == 2

    def test_turned_face_up_when_tapped(self, cards):
        game, p1, p2, perm = self._face_down_bear(cards)
        _nosick(perm)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [p1.battlefield.index(perm)], 1)
        assert ok, msg
        assert perm.metadata.get("face_down") is None
        assert perm.card.name == "Grizzly Bears"

    def test_turned_face_up_when_dealing_combat_damage(self, cards):
        game, p1, p2, perm = self._face_down_bear(cards)
        _nosick(perm)
        blocker = Permanent(card=_mk_creature("Wall Dummy", 0, 4, keywords=("Vigilance",)))
        p2.battlefield.append(blocker)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [p1.battlefield.index(perm)], 1)
        assert ok, msg
        game.advance_combat_phase()
        ok, msg = game.declare_blockers(1, {0: p1.battlefield.index(perm)})
        assert ok, msg
        # Attacking already tapped (and flipped) — re-arm face-down state to
        # isolate the deals-damage event before damage auto-resolves on advance.
        perm.metadata["face_down"] = True
        perm.metadata["face_down_real_card"] = perm.card
        game.advance_combat_phase()  # auto-resolves combat damage (single block)
        assert game.combat_damage_resolved
        assert perm.metadata.get("face_down") is None


# ---------------------------------------------------------------------------
# Kormus Bell — "I'm not able to block with swamps that are made creatures"
# ---------------------------------------------------------------------------

class TestKormusBellSwampBlocks:
    def _animated_swamp_combat(self, cards):
        bell = Permanent(card=cards["Kormus Bell"])
        swamp = Permanent(card=cards["Swamp"])
        swamp.metadata["summoning_sickness_turn"] = -99
        attacker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[bell, swamp])
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert swamp.is_creature
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0], 1)
        assert ok, msg
        game.advance_combat_phase()
        return game, p2, swamp

    def test_animated_swamp_may_block(self, cards):
        game, p2, swamp = self._animated_swamp_combat(cards)
        ok, msg = game.declare_blockers(1, {p2.battlefield.index(swamp): 0})
        assert ok, msg

    def test_animated_swamp_serializes_is_creature_for_the_client(self, cards):
        # The client-side "Only creatures can block." check reads is_creature;
        # the printed type line has no "creature" for an animated Swamp.
        sid = _new_session(seed=21)
        session = store.get(sid)
        bell = Permanent(card=_C["Kormus Bell"])
        swamp = Permanent(card=_C["Swamp"])
        session.game.players[0].battlefield = [bell, swamp]
        session.game._refresh_dynamic_creatures()
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        serialized = state["players"][0]["battlefield"][1]
        assert "creature" not in serialized["type"].lower()
        assert serialized["is_creature"] is True

    def test_client_block_check_uses_is_creature_flag(self):
        app_js = (_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        assert "blockerCard.is_creature" in app_js


# ---------------------------------------------------------------------------
# Library of Leng — "I tried playing mind twist on myself to trigger library
# of leng but it didn't work"
# ---------------------------------------------------------------------------

def test_mind_twist_on_self_routes_discards_to_library_top(cards):
    random.seed(3)
    leng = Permanent(card=cards["Library of Leng"])
    p1 = PlayerState(
        name="P1",
        hand=[cards["Mind Twist"], cards["Forest"], cards["Island"], cards["Grizzly Bears"]],
        battlefield=[leng],
    )
    game = _game(p1, PlayerState(name="P2"))
    result = game.cast_from_hand(0, "Mind Twist", target_player_index=0, x_value=2)
    assert result.supported, result.details
    # Both discarded cards went on top of the library, none to the graveyard
    # (Mind Twist itself is the only graveyard card).
    assert len(p1.hand) == 1
    assert len(p1.library) == 2
    assert [c.name for c in p1.graveyard] == ["Mind Twist"]
    assert any("Library of Leng" in line for line in game.log)


# ---------------------------------------------------------------------------
# Living Artifact — "The upkeep trigger is optional so it should give me a
# prompt"
# ---------------------------------------------------------------------------

class TestLivingArtifactOptionalUpkeep:
    def _aura_game(self, cards, counters=2):
        aura = Permanent(card=cards["Living Artifact"])
        aura.metadata["vitality_counters"] = counters
        p1 = PlayerState(name="P1", battlefield=[aura], life=15)
        game = _game(p1, PlayerState(name="P2"))
        game.active_player_index = 0
        return game, p1, aura

    def test_optional_trigger_is_surfaced(self, cards):
        game, p1, aura = self._aura_game(cards)
        triggers = game.get_optional_upkeep_triggers(0)
        assert any(t["kind"] == "upkeep_remove_vitality_counter" for t in triggers)

    def test_not_surfaced_without_counters(self, cards):
        game, p1, aura = self._aura_game(cards, counters=0)
        triggers = game.get_optional_upkeep_triggers(0)
        assert not any(t["kind"] == "upkeep_remove_vitality_counter" for t in triggers)

    def test_declining_keeps_counter_and_life(self, cards):
        game, p1, aura = self._aura_game(cards)
        game.resolve_upkeep(0, optional_choices={"Living Artifact": False})
        assert aura.metadata["vitality_counters"] == 2
        assert p1.life == 15

    def test_accepting_removes_counter_and_gains_life(self, cards):
        game, p1, aura = self._aura_game(cards)
        game.resolve_upkeep(0, optional_choices={"Living Artifact": True})
        assert aura.metadata["vitality_counters"] == 1
        assert p1.life == 16

    def test_headless_default_still_gains(self, cards):
        game, p1, aura = self._aura_game(cards)
        game.resolve_upkeep(0)
        assert aura.metadata["vitality_counters"] == 1
        assert p1.life == 16


# ---------------------------------------------------------------------------
# Regrowth — '"no valid target for Regrowth" when I click on a card in my
# graveyard'
# ---------------------------------------------------------------------------

class TestRegrowthReturnsAnyCard:
    @pytest.mark.parametrize("card_name", ["Lightning Bolt", "Forest", "Sol Ring"])
    def test_returns_chosen_noncreature_card(self, cards, card_name):
        p1 = PlayerState(name="P1", hand=[cards["Regrowth"]], graveyard=[cards["Grizzly Bears"], cards[card_name]])
        game = _game(p1, PlayerState(name="P2"))
        result = game.cast_from_hand(0, "Regrowth", target_player_index=0, target_permanent_index=1)
        assert result.supported, result.details
        assert any(c.name == card_name for c in p1.hand)
        assert not any(c.name == card_name for c in p1.graveyard)

    def test_returns_chosen_creature_card(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Regrowth"]], graveyard=[cards["Lightning Bolt"], cards["Grizzly Bears"]])
        game = _game(p1, PlayerState(name="P2"))
        result = game.cast_from_hand(0, "Regrowth", target_player_index=0, target_permanent_index=1)
        assert result.supported, result.details
        assert any(c.name == "Grizzly Bears" for c in p1.hand)

    def test_raise_dead_still_rejects_noncreature(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Raise Dead"]], graveyard=[cards["Lightning Bolt"]])
        game = _game(p1, PlayerState(name="P2"))
        result = game.cast_from_hand(0, "Raise Dead", target_player_index=0, target_permanent_index=0)
        assert not result.supported
        assert "no valid target" in result.details


# ---------------------------------------------------------------------------
# Reverse Damage — "Effect didn't work"
# ---------------------------------------------------------------------------

class TestReverseDamage:
    def test_chosen_attacker_combat_damage_is_prevented_and_gained(self, cards):
        attacker = _nosick(Permanent(card=cards["Hill Giant"]))  # 3/3
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", hand=[cards["Reverse Damage"]], life=10)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0], 1)
        assert ok, msg
        # Defender casts Reverse Damage choosing the attacker as the source.
        result = game.cast_from_hand(1, "Reverse Damage", target_player_index=0, target_permanent_index=0)
        assert result.supported, result.details
        game.advance_combat_phase()  # declare_blockers
        ok, msg = game.declare_blockers(1, {})
        assert ok, msg
        game.advance_combat_phase()  # combat damage auto-resolves (no blocks)
        assert game.combat_damage_resolved
        # 3 damage prevented AND gained: 10 -> 13.
        assert p2.life == 13

    def test_source_is_threaded_through_manabarbs_damage(self, cards):
        # Manabarbs: "Whenever a player taps a land for mana, Manabarbs deals 1
        # damage to that player." This path used to pass source=None, so a
        # chosen-source Reverse Damage shield could never match it.
        barbs = Permanent(card=cards["Manabarbs"])
        mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", battlefield=[barbs])
        p2 = PlayerState(name="P2", battlefield=[mountain], life=10)
        game = _game(p1, p2)
        p2.reverse_damage_sources.append(barbs)
        assert game.tap_land_for_mana(1, "Mountain", permanent_index=0)
        # 1 damage prevented and gained: 10 -> 11.
        assert p2.life == 11
        assert not p2.reverse_damage_sources


# ---------------------------------------------------------------------------
# Rock Hydra — "The damage shield ability isn't working"
# ---------------------------------------------------------------------------

class TestRockHydraDamageShield:
    def _hydra_game(self, cards):
        hydra = Permanent(card=cards["Rock Hydra"])
        _nosick(hydra)
        hydra.power_bonus = 3
        hydra.toughness_bonus = 3
        p1 = PlayerState(name="P1", battlefield=[hydra])
        p2 = PlayerState(name="P2", hand=[cards["Lightning Bolt"]])
        game = _game(p1, p2)
        return game, hydra, p2

    def test_shield_arms_on_hydra_not_the_opponent(self, cards):
        game, hydra, p2 = self._hydra_game(cards)
        result = game.queue_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=0)
        assert result.supported, result.details
        game.resolve_stack()
        assert hydra.damage_prevention_pool == 1
        assert p2.damage_prevention_pool == 0

    def test_shield_prevents_one_damage(self, cards):
        game, hydra, p2 = self._hydra_game(cards)
        game.queue_permanent_ability(0, "Rock Hydra", permanent_index=0, ability_index=0)
        game.resolve_stack()
        result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
        assert result.supported
        game.resolve_stack()
        # Bolt's 3 damage: 1 prevented, 2 marked.
        assert hydra.damage_marked == 2
        assert hydra.damage_prevention_pool == 0


# ---------------------------------------------------------------------------
# Scavenging Ghoul — "The corpse counters are covering the power and
# toughness. Move them to a different place on the card."
# ---------------------------------------------------------------------------

def test_counter_badges_offset_above_the_pt_badge():
    canvas_js = (_ROOT / "web" / "static" / "battlefield-canvas.js").read_text(encoding="utf-8")
    # The counter stack starts one slot above the bottom edge when the P/T
    # badge occupies the bottom-right corner.
    assert "counterBaseSlot" in canvas_js
    assert "ptBadgeDrawn" in canvas_js


# ---------------------------------------------------------------------------
# Smoke — 'error "already selected maximum untap lands". It should say
# creatures instead'
# ---------------------------------------------------------------------------

def test_smoke_overselection_error_names_creatures():
    sid = _new_session(seed=9)
    session = store.get(sid)
    game = session.game
    smoke = Permanent(card=_C["Smoke"])
    tapped1 = Permanent(card=_C["Grizzly Bears"], tapped=True)
    tapped2 = Permanent(card=_C["Hill Giant"], tapped=True)
    game.players[0].battlefield = [smoke, tapped1, tapped2]
    session.current_turn = 0
    game.active_player_index = 0
    options = game.get_untap_land_selection_options(0)
    assert options is not None
    session.untap_required_lands = int(options["max_count"])
    session.untap_candidate_indices = [int(i) for i in options["candidate_indices"]]
    session.untap_selected_indices = []
    game._set_phase_and_step("beginning", "untap")

    resp1 = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "untap_select", "permanent_index": 1},
    )
    assert resp1.status_code == 200, resp1.text
    resp2 = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "untap_select", "permanent_index": 2},
    )
    assert resp2.status_code == 400
    detail = resp2.json()["detail"]
    assert "creatures" in detail
    assert "lands" not in detail


# ---------------------------------------------------------------------------
# Two-Headed Giant of Foriys — "The owner should get to divide the damage as
# they choose if they block more than 1 creature"
# ---------------------------------------------------------------------------

class TestTwoHeadedGiantDamageDivision:
    def _double_block(self, cards):
        a1 = _nosick(Permanent(card=_mk_creature("Bear One", 2, 2)))
        a2 = _nosick(Permanent(card=_mk_creature("Bear Two", 2, 2)))
        giant = Permanent(card=cards["Two-Headed Giant of Foriys"])  # 4/4, blocks 2
        giant.metadata["summoning_sickness_turn"] = -99
        p1 = PlayerState(name="P1", battlefield=[a1, a2], life=20)
        p2 = PlayerState(name="P2", battlefield=[giant], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], 1)
        assert ok, msg
        game.advance_combat_phase()
        ok, msg = game.declare_blockers(1, {0: [0, 1]})
        assert ok, msg
        game.advance_combat_phase()
        assert game.current_step == "combat_damage"
        return game, p1, p2

    def test_defender_precommits_division_and_both_attackers_die(self, cards):
        game, p1, p2 = self._double_block(cards)
        ok, msg = game.assign_multiblock_blocker_damage(1, {0: {0: 2, 1: 2}})
        assert ok, msg
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg
        assert not any(p.card.name == "Bear One" for p in p1.battlefield)
        assert not any(p.card.name == "Bear Two" for p in p1.battlefield)

    def test_division_exceeding_power_is_rejected(self, cards):
        game, p1, p2 = self._double_block(cards)
        ok, msg = game.assign_multiblock_blocker_damage(1, {0: {0: 4, 1: 1}})
        assert not ok
        assert "exceeds" in msg

    def test_division_assigning_less_than_total_power_is_rejected(self, cards):
        game, p1, p2 = self._double_block(cards)
        # CR 510.1d: the 4-power Giant must assign ALL its combat damage — a
        # division totalling only 3 is illegal.
        ok, msg = game.assign_multiblock_blocker_damage(1, {0: {0: 2, 1: 1}})
        assert not ok
        assert "all" in msg

    def test_division_to_unblocked_creature_is_rejected(self, cards):
        game, p1, p2 = self._double_block(cards)
        ok, msg = game.assign_multiblock_blocker_damage(1, {0: {5: 2}})
        assert not ok

    def test_only_defender_may_divide(self, cards):
        game, p1, p2 = self._double_block(cards)
        ok, msg = game.assign_multiblock_blocker_damage(0, {0: {0: 2, 1: 2}})
        assert not ok

    def test_default_without_division_hits_first_attacker(self, cards):
        game, p1, p2 = self._double_block(cards)
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg
        assert not any(p.card.name == "Bear One" for p in p1.battlefield)
        assert any(p.card.name == "Bear Two" for p in p1.battlefield)

    def test_division_via_web_action(self, cards):
        sid = _new_session(mode="human_vs_human", seed=13)
        session = store.get(sid)
        game = session.game
        game.enforce_mana_costs = False
        a1 = _nosick(Permanent(card=_mk_creature("Bear One", 2, 2)))
        a2 = _nosick(Permanent(card=_mk_creature("Bear Two", 2, 2)))
        giant = Permanent(card=_C["Two-Headed Giant of Foriys"])
        giant.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield = [a1, a2]
        game.players[1].battlefield = [giant]
        session.current_turn = 0
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], 1)
        assert ok, msg
        game.advance_combat_phase()
        ok, msg = game.declare_blockers(1, {0: [0, 1]})
        assert ok, msg
        game.advance_combat_phase()
        assert game.current_step == "combat_damage"

        # The defending seat sees the division block; the attacker does not.
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        info = state["multiblock_blocker_assignment"]
        assert info is not None and info["defender_seat"] == 1
        assert info["blockers"][0]["blocker_idx"] == 0
        assert info["blockers"][0]["attacker_indices"] == [0, 1]
        attacker_state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert attacker_state["multiblock_blocker_assignment"] is None

        # Until the defender divides, the attacker cannot resolve combat damage.
        game.priority_player_index = 0
        blocked = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "assign_combat_damage"},
        )
        assert blocked.status_code == 400
        assert "divide" in blocked.json()["detail"]

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 1, "action": "assign_multiblock_damage",
                  "blocker_damage_split": {"0": {"0": 2, "1": 2}}},
        )
        assert resp.status_code == 200, resp.text
        game.priority_player_index = 0
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "assign_combat_damage"},
        )
        assert resp.status_code == 200, resp.text
        assert game.combat_damage_resolved
        assert not any(p.card.name == "Bear One" for p in game.players[0].battlefield)
        assert not any(p.card.name == "Bear Two" for p in game.players[0].battlefield)


# ---------------------------------------------------------------------------
# Word of Command — "should stay on the stack until I choose which card to
# play from the opponent's hand"
# ---------------------------------------------------------------------------

class TestWordOfCommandHoldsTheGame:
    def _armed_session(self):
        sid = _new_session(mode="human_vs_human", seed=17)
        session = store.get(sid)
        game = session.game
        game.players[1].hand = [_C["Lightning Bolt"], _C["Forest"]]
        game.arm_pending_choice(
            "word_of_command", 0,
            target_index=1, card_name="Word of Command",
            hand=[c.name for c in game.players[1].hand],
        )
        return sid, session, game

    def test_caster_actions_are_blocked_until_the_choice(self):
        sid, session, game = self._armed_session()
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "next_phase"},
        )
        assert resp.status_code == 400
        assert "Word of Command" in resp.json()["detail"]

    def test_phase_cannot_advance_past_a_pending_choice(self):
        sid, session, game = self._armed_session()
        from web.app import _advance_phase
        phase, step = game.current_turn_phase, game.current_step
        _advance_phase(session)
        assert (game.current_turn_phase, game.current_step) == (phase, step)

    def test_confirming_the_choice_unblocks(self):
        sid, session, game = self._armed_session()
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "word_of_command_confirm", "hand_index": 1},
        )
        assert resp.status_code == 200, resp.text
        assert game.pending_word_of_command is None
