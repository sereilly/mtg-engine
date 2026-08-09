"""Regression tests for the fifteenth batch of bugs reported in-game
(CARD_VERIFICATION.md failures).

Clusters covered in this batch:
- Channel: a player may pay their ENTIRE life total (CR 118.4) — the engine
  accepts paying down to 0 (then loses to SBAs), rejects overpaying, and the
  client no longer caps the prompt at life - 1.
- Copy Artifact: the copy is an enchantment IN ADDITION to the copied types —
  it counts as both an artifact and an enchantment for targeting and mass
  destruction, and the serialized type line shows both.
- Kormus Bell: animated Swamps are creatures for ALL purposes — "any target"
  damage spells (Lightning Bolt) can target and destroy them.
- Library of Leng: the discard replacement is OPTIONAL ("you may") — a human
  controller gets a per-card graveyard/top-of-library prompt; AI/headless play
  keeps the beneficial top-of-library default.
- Scavenging Ghoul: the end-step trigger fires only when creatures actually
  died THIS turn — the web turn flow now resets the per-turn death counter
  (it previously only reset in the headless start_turn path).
- Word of Command: the spell STAYS ON THE STACK (and out of the graveyard)
  while the caster's card choice is pending. On the interactive path the
  choice is only recorded (defer_resolution) — the spell keeps waiting on the
  stack and finishes resolving when priority is released; headless/AI confirms
  still finish immediately.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, load_cards
from engine.models import Permanent
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store

client = TestClient(app)

_ROOT = Path(__file__).resolve().parent.parent.parent


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session, session.game


# ---------------------------------------------------------------------------
# Channel — "I should be able to pay my entire life pool for channel's
# ability, even if it kills me"
# ---------------------------------------------------------------------------

class TestChannelFullLifePayment:
    def _channel_game(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Channel"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Channel", target_player_index=1)
        assert result.supported
        return game, p1

    def test_can_pay_entire_life_pool_and_loses_to_sbas(self, cards):
        game, p1 = self._channel_game(cards)
        assert p1.life == 20
        result = game.use_channel_mana(0, 20)
        assert result.supported
        assert p1.life == 0
        assert p1.mana_pool.get("C", 0) == 20
        # 704.5a: paying down to 0 is legal; the player then loses the game.
        assert p1.lost is True

    def test_cannot_pay_more_life_than_you_have(self, cards):
        game, p1 = self._channel_game(cards)
        result = game.use_channel_mana(0, 21)
        assert not result.supported
        assert p1.life == 20
        assert p1.mana_pool.get("C", 0) == 0
        assert p1.lost is False

    def test_client_prompt_allows_full_life_total(self):
        # The web prompt previously capped the payable amount at life - 1.
        app_js = (_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")
        assert "Math.max(1, me?.life ?? 1)" in app_js
        assert "(me?.life ?? 1) - 1" not in app_js


# ---------------------------------------------------------------------------
# Copy Artifact — "should be an enchantment in addition to whatever it's
# copying ... an artifact enchantment for example"
# ---------------------------------------------------------------------------

class TestCopyArtifactIsBothTypes:
    def _copy_game(self, cards, extra_hand=()):
        p1 = PlayerState(
            name="P1",
            hand=[cards["Copy Artifact"]],
            battlefield=[Permanent(card=cards["Black Lotus"])],
        )
        p2 = PlayerState(name="P2", hand=[cards[name] for name in extra_hand])
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Copy Artifact", target_player_index=1)
        assert result.supported
        perm = next(p for p in p1.battlefield if p.metadata.get("copied_from") == "Black Lotus")
        return game, p1, p2, perm

    def test_copy_has_both_types(self, cards):
        _, _, _, perm = self._copy_game(cards)
        type_line = perm.effective_card.type_line.lower()
        assert "artifact" in type_line
        assert "enchantment" in type_line
        assert perm.has_type("artifact")
        assert perm.has_type("enchantment")

    def test_destroy_all_enchantments_destroys_the_copy(self, cards):
        game, p1, p2, perm = self._copy_game(cards, extra_hand=("Tranquility",))
        result = game.cast_from_hand(1, "Tranquility", target_player_index=0)
        assert result.supported
        assert perm not in p1.battlefield
        assert any(c.name == "Copy Artifact" for c in p1.graveyard)

    def test_destroy_target_artifact_destroys_the_copy(self, cards):
        game, p1, p2, perm = self._copy_game(cards, extra_hand=("Shatter",))
        idx = p1.battlefield.index(perm)
        result = game.cast_from_hand(
            1, "Shatter", target_player_index=0, target_permanent_index=idx
        )
        assert result.supported
        assert perm not in p1.battlefield
        assert any(c.name == "Copy Artifact" for c in p1.graveyard)

    def test_serialized_type_line_shows_both_types(self, cards):
        sid, session, game = _session()
        game.players[0].battlefield.append(Permanent(card=_C["Black Lotus"]))
        game.players[0].hand.append(_C["Copy Artifact"])
        game.enforce_mana_costs = False
        game.cast_from_hand(0, "Copy Artifact", target_player_index=1)
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        copy_entry = next(
            p for p in state["players"][0]["battlefield"] if p["name"] == "Copy Artifact"
        )
        assert "artifact" in copy_entry["type"].lower()
        assert "enchantment" in copy_entry["type"].lower()


# ---------------------------------------------------------------------------
# Kormus Bell — "I'm not able to destroy swamps with lightning bolt when
# Kormus bell is out. Swamps should be treated as creatures for all purposes"
# ---------------------------------------------------------------------------

class TestKormusBellAnimatedSwampsTakeSpellDamage:
    def test_lightning_bolt_destroys_animated_swamp(self, cards):
        swamp = _nosick(Permanent(card=cards["Swamp"]))
        bell = Permanent(card=cards["Kormus Bell"])
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"]])
        p2 = PlayerState(name="P2", battlefield=[bell, swamp])
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert swamp.metadata.get("land_animated") is True

        idx = p2.battlefield.index(swamp)
        result = game.cast_from_hand(
            0, "Lightning Bolt", target_player_index=1, target_permanent_index=idx
        )
        assert result.supported
        assert swamp not in p2.battlefield
        assert any(c.name == "Swamp" for c in p2.graveyard)
        assert not any(
            "is not a valid 'any target' target" in line for line in game.log
        )

    def test_animated_swamp_death_counts_as_creature_death(self, cards):
        # "for all purposes": an animated land dying is a creature dying, so
        # Scavenging Ghoul's end-step trigger must count it.
        swamp = _nosick(Permanent(card=cards["Swamp"]))
        bell = Permanent(card=cards["Kormus Bell"])
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"]])
        p2 = PlayerState(name="P2", battlefield=[bell, swamp])
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        idx = p2.battlefield.index(swamp)
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=idx)
        assert game.creatures_died_this_turn == 1

    def test_living_lands_forest_also_boltable(self, cards):
        forest = _nosick(Permanent(card=cards["Forest"]))
        lands = Permanent(card=cards["Living Lands"])
        p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"]])
        p2 = PlayerState(name="P2", battlefield=[lands, forest])
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert forest.metadata.get("land_animated") is True

        idx = p2.battlefield.index(forest)
        result = game.cast_from_hand(
            0, "Lightning Bolt", target_player_index=1, target_permanent_index=idx
        )
        assert result.supported
        assert forest not in p2.battlefield
        assert any(c.name == "Forest" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Library of Leng — "The effect is optional, add a prompt"
# ---------------------------------------------------------------------------

class TestLibraryOfLengOptionalPrompt:
    def _leng_player(self, cards):
        leng = Permanent(card=cards["Library of Leng"])
        p1 = PlayerState(name="P1", battlefield=[leng])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        return game, p1

    def test_interactive_discard_arms_a_pending_choice(self, cards):
        game, p1 = self._leng_player(cards)
        game.interactive_seats = {0}
        bears = cards["Grizzly Bears"]
        game._discard_card(p1, bears)
        assert len(game.pending_leng_discards) == 1
        entry = game.pending_leng_discards[0]
        assert entry["player_index"] == 0
        assert entry["card"] is bears
        # The card is in limbo until the choice is made — in no zone yet.
        assert bears not in p1.graveyard
        assert bears not in p1.library

    def test_confirm_routes_to_top_of_library(self, cards):
        game, p1 = self._leng_player(cards)
        game.interactive_seats = {0}
        bears = cards["Grizzly Bears"]
        game._discard_card(p1, bears)
        assert game.confirm_leng_discard(0, True) is True
        assert game.pending_leng_discards == []
        assert p1.library[0] is bears
        assert bears not in p1.graveyard

    def test_confirm_routes_to_graveyard(self, cards):
        game, p1 = self._leng_player(cards)
        game.interactive_seats = {0}
        bears = cards["Grizzly Bears"]
        game._discard_card(p1, bears)
        assert game.confirm_leng_discard(0, False) is True
        assert game.pending_leng_discards == []
        assert bears in p1.graveyard
        assert bears not in p1.library

    def test_headless_discard_keeps_top_of_library_default(self, cards):
        # AI/headless play (no interactive seats) resolves inline as before.
        game, p1 = self._leng_player(cards)
        bears = cards["Grizzly Bears"]
        game._discard_card(p1, bears)
        assert game.pending_leng_discards == []
        assert p1.library[0] is bears

    def _arm_leng_discard(self, game, card):
        """Arm the prompt the way play does — a forced discard while the seat
        controls Library of Leng — rather than hand-building engine state, so
        this still covers the real path if the queue's shape changes."""
        game.interactive_seats = {0}
        game.players[0].battlefield.append(Permanent(card=_C["Library of Leng"]))
        game._discard_card(game.players[0], card)

    def test_prompt_surfaces_via_api_and_blocks_other_actions(self):
        sid, session, game = _session()
        bears = _C["Grizzly Bears"]
        self._arm_leng_discard(game, bears)

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        info = state["leng_discard"]
        assert info is not None
        assert info["player_seat"] == 0
        assert info["card"]["name"] == "Grizzly Bears"
        assert info["remaining"] == 1

        # Other actions are blocked until the destination is chosen.
        resp = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
        )
        assert resp.status_code == 400
        assert "Library of Leng" in resp.json()["detail"]

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "leng_discard_confirm", "to_library": True},
        )
        assert resp.status_code == 200
        assert game.pending_leng_discards == []
        assert game.players[0].library[0].name == "Grizzly Bears"

    def test_prompt_hidden_from_opponent(self):
        sid, session, game = _session()
        self._arm_leng_discard(game, _C["Grizzly Bears"])
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        assert state["leng_discard"] is None


# ---------------------------------------------------------------------------
# Scavenging Ghoul — "The effect is triggering even when no creatures died
# during the turn"
# ---------------------------------------------------------------------------

class TestScavengingGhoulTriggersOnlyOnDeaths:
    def test_no_corpse_counters_when_nothing_died(self, cards):
        ghoul = _nosick(Permanent(card=cards["Scavenging Ghoul"]))
        p1 = PlayerState(name="P1", battlefield=[ghoul])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0
        assert game.creatures_died_this_turn == 0

        game.resolve_end_step(0)
        game.resolve_stack()

        assert ghoul.metadata.get("corpse_counters", 0) == 0
        assert not any("corpse counter" in line for line in game.log)

    def test_begin_turn_bookkeeping_resets_death_counter(self, cards):
        p1 = PlayerState(name="P1")
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.creatures_died_this_turn = 3
        p1.damage_taken_this_turn = 5
        game.begin_turn_bookkeeping(0)
        assert game.creatures_died_this_turn == 0
        assert p1.damage_taken_this_turn == 0

    def test_web_turn_flow_resets_death_counter(self):
        # The web layer drives turns step-by-step instead of via start_turn;
        # it must still perform the per-turn resets, or Scavenging Ghoul
        # triggers on deaths from previous turns.
        from web.app import _begin_turn

        sid, session, game = _session()
        game.creatures_died_this_turn = 4
        _begin_turn(session, session.current_turn, defer_untap_selection=False)
        assert game.creatures_died_this_turn == 0


# ---------------------------------------------------------------------------
# Word of Command — "Card should stay on the stack until I finish the prompt"
# ---------------------------------------------------------------------------

class TestWordOfCommandStaysOnStack:
    def _cast_woc(self, cards):
        p1 = PlayerState(name="P1", hand=[cards["Word of Command"]])
        p2 = PlayerState(
            name="P2", hand=[cards["Lightning Bolt"], cards["Grizzly Bears"]], life=20
        )
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Word of Command", target_player_index=1)
        assert result.supported
        assert game.pending_word_of_command is not None
        return game, p1, p2

    def test_spell_stays_on_stack_while_choice_pending(self, cards):
        game, p1, p2 = self._cast_woc(cards)
        assert any(item.card.name == "Word of Command" for item in game.stack)
        assert not any(c.name == "Word of Command" for c in p1.graveyard)
        # Further stack resolution must not pop (or re-resolve) the paused spell.
        game.resolve_stack()
        assert any(item.card.name == "Word of Command" for item in game.stack)
        assert game.pending_word_of_command is not None

    def test_confirm_finishes_resolution(self, cards):
        game, p1, p2 = self._cast_woc(cards)
        assert game.confirm_word_of_command(0, 0) is True
        assert game.pending_word_of_command is None
        assert not any(item.card.name == "Word of Command" for item in game.stack)
        assert any(c.name == "Word of Command" for c in p1.graveyard)
        # The forced card was played (Lightning Bolt at its own controller).
        assert p2.life == 17

    def test_decline_also_finishes_resolution(self, cards):
        game, p1, p2 = self._cast_woc(cards)
        assert game.confirm_word_of_command(0, -1) is True
        assert game.pending_word_of_command is None
        assert not any(item.card.name == "Word of Command" for item in game.stack)
        assert any(c.name == "Word of Command" for c in p1.graveyard)
        assert len(p2.hand) == 2  # nothing was forced

    def test_deferred_confirm_waits_for_priority_release(self, cards):
        # Interactive path: the card choice alone must NOT resolve the spell —
        # it stays on the stack until both players release priority.
        game, p1, p2 = self._cast_woc(cards)
        assert game.confirm_word_of_command(0, 0, defer_resolution=True) is True
        assert game.pending_word_of_command is not None
        assert game.pending_word_of_command["chosen_hand_index"] == 0
        assert any(item.card.name == "Word of Command" for item in game.stack)
        assert not any(c.name == "Word of Command" for c in p1.graveyard)
        assert p2.life == 20  # nothing forced yet
        # The caster holds priority after choosing; releasing it resolves the
        # spell and puts the forced Lightning Bolt on the stack for its own
        # priority round.
        assert game.has_priority(0)
        game.pass_priority(0)
        game.pass_priority(1)
        assert game.pending_word_of_command is None
        assert any(c.name == "Word of Command" for c in p1.graveyard)
        assert any(item.card.name == "Lightning Bolt" for item in game.stack)
        assert p2.life == 20
        game.pass_priority(game.priority_player_index)
        game.pass_priority(game.priority_player_index)
        assert p2.life == 17  # forced to bolt themselves

    def test_stack_visible_via_api_while_pending(self):
        sid, session, game = _session()
        game.players[0].hand = [_C["Word of Command"]]
        # A creature-only hand keeps the AI from responding with an instant.
        game.players[1].hand = [_C["Grizzly Bears"]]
        game.enforce_mana_costs = False
        game.cast_from_hand(0, "Word of Command", target_player_index=1)
        assert game.pending_word_of_command is not None

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert any(item["label"] == "Word of Command" for item in state["stack"])

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "word_of_command_confirm", "hand_index": 0},
        )
        assert resp.status_code == 200
        # The choice is recorded but the spell still waits on the stack (the
        # prompt itself is gone) until the caster releases priority.
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert any(item["label"] == "Word of Command" for item in state["stack"])
        assert state["word_of_command"] is None
        assert game.pending_word_of_command is not None

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )
        assert resp.status_code == 200
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert not any(item["label"] == "Word of Command" for item in state["stack"])
        assert game.pending_word_of_command is None
