"""Regression tests for the twelfth batch of bugs reported in-game.

Clusters covered in this batch:
- Kormus Bell / Living Lands: an animated land is a creature for ALL purposes —
  it can be targeted by creature-targeting spells and abilities, enchanted by
  creature Auras, declared as an attacker, and offered as a blocker. Previously
  only attacking worked; targeting paths checked the printed card type.
- Hand reveals (Glasses of Urza's look, Word of Command's forced-play choice):
  the target player's hand serializes face-up to the viewer while the reveal is
  pending, so the opponent hand fan shows the actual cards, not just a prompt
  listing names. Other viewers still see hidden card backs.
"""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, load_cards
from engine.models import Permanent
from engine.land_types import change_land_type
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store

client = TestClient(app)



def _animated_swamp_game(cards):
    """Seat 0 controls Kormus Bell and one (animated) Swamp."""
    bell = Permanent(card=cards["Kormus Bell"])
    swamp = _nosick(Permanent(card=cards["Swamp"]))
    p1 = PlayerState(name="P1", battlefield=[bell, swamp])
    p2 = PlayerState(name="P2", life=20)
    game = _game(p1, p2)
    game._refresh_dynamic_creatures()
    assert swamp.metadata.get("land_animated") is True
    return game, p1, p2, swamp


# ---------------------------------------------------------------------------
# Kormus Bell — "when a land is turned into a creature, I should be able to
# target it with auras and other creature targeting spells and abilities, and
# be able to declare it as an attacker."
# ---------------------------------------------------------------------------

class TestAnimatedLandTargeting:
    def test_cast_target_spec_offers_animated_swamp_for_creature_spell(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        spec = game.cast_target_spec(0, cards["Giant Growth"])
        assert spec["kind"] == "creature"
        assert {"kind": "permanent", "seat": 0, "index": 1, "key": "0-1", "name": "Swamp"} in spec["valid_targets"]

    def test_plain_land_not_offered_without_animation(self, cards):
        forest = Permanent(card=cards["Forest"])
        p1 = PlayerState(name="P1", battlefield=[forest])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        spec = game.cast_target_spec(0, cards["Giant Growth"])
        assert spec["valid_targets"] == []

    def test_giant_growth_resolves_on_animated_swamp(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        p1.hand.append(cards["Giant Growth"])
        result = game.cast_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=1)
        assert result.supported
        assert (swamp.effective_power, swamp.effective_toughness) == (4, 4)

    def test_aura_enchants_animated_swamp(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        spec = game.cast_target_spec(0, cards["Holy Strength"])
        assert any(t["seat"] == 0 and t["index"] == 1 for t in spec["valid_targets"])
        p1.hand.append(cards["Holy Strength"])
        result = game.cast_from_hand(0, "Holy Strength", target_player_index=0, target_permanent_index=1)
        assert result.supported
        aura = next(perm for perm in p1.battlefield if perm.card.name == "Holy Strength")
        assert aura.metadata.get("attached_to") is swamp
        # Holy Strength grants +1/+2 on top of the animated 1/1.
        assert (swamp.effective_power, swamp.effective_toughness) == (2, 3)

    def test_unsummon_bounces_animated_swamp(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        p2.hand.append(cards["Unsummon"])
        result = game.cast_from_hand(1, "Unsummon", target_player_index=0, target_permanent_index=1)
        assert result.supported
        assert swamp not in p1.battlefield
        assert cards["Swamp"] in p1.hand

    def test_activated_ability_targets_animated_swamp(self, cards):
        # Nettling Imp: "Choose target non-Wall creature the active player has
        # controlled continuously since the turn began ... must attack" — the
        # ability-instruction filter must accept the animated land.
        game, p1, p2, swamp = _animated_swamp_game(cards)
        imp = _nosick(Permanent(card=cards["Nettling Imp"]))
        p2.battlefield.append(imp)
        game.active_player_index = 0
        spec = game.activation_target_spec(1, p2.battlefield.index(imp))
        assert spec["kind"] == "creature"
        assert any(t["seat"] == 0 and t["index"] == 1 for t in spec["valid_targets"])


class TestAnimatedLandTypeOverride:
    def test_kormus_bell_animates_land_overridden_to_swamp(self, cards):
        # Evil Presence makes the enchanted land a Swamp (replacing its printed
        # type, CR 305.7) — Kormus Bell must then animate it.
        bell = Permanent(card=cards["Kormus Bell"])
        mountain = _nosick(Permanent(card=cards["Mountain"]))
        p1 = PlayerState(name="P1", battlefield=[bell, mountain], hand=[cards["Evil Presence"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Evil Presence", target_player_index=0, target_permanent_index=1)
        assert result.supported
        assert mountain.changed_land_types == ("swamp",)
        game._refresh_dynamic_creatures()
        assert mountain.metadata.get("land_animated") is True
        assert (mountain.effective_power, mountain.effective_toughness) == (1, 1)

    def test_kormus_bell_does_not_animate_swamp_overridden_away(self, cards):
        # The reverse: a printed Swamp whose type was replaced with a non-Swamp
        # type is no longer a Swamp, so Kormus Bell must NOT animate it.
        bell = Permanent(card=cards["Kormus Bell"])
        swamp = _nosick(Permanent(card=cards["Swamp"]))
        change_land_type(swamp, "mountain", source="test")
        p1 = PlayerState(name="P1", battlefield=[bell, swamp])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        assert swamp.metadata.get("land_animated") is not True


class TestAnimatedLandCombat:
    def test_animated_swamp_declares_as_attacker(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        assert 1 in game.legal_attacker_indices(0)
        ok, msg = game.declare_attackers(0, [1], 1)
        assert ok, msg
        assert swamp.tapped is True

    def test_animated_swamp_survives_combat_pruning_and_deals_damage(self, cards):
        # The original in-game failure: declaration succeeded but
        # _prune_combat_state dropped the animated land (printed type "land"),
        # so the step completed with 0 attackers and no damage was dealt.
        game, p1, p2, swamp = _animated_swamp_game(cards)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [1], 1)
        assert ok, msg
        game._prune_combat_state()
        assert 1 in game.combat_attackers
        assert swamp.attacking is True
        game._set_phase_and_step("combat", "combat_damage")
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg
        assert p2.life == 19  # unblocked 1/1 animated Swamp connected

    def test_animated_swamp_offered_as_blocker(self, cards):
        game, p1, p2, swamp = _animated_swamp_game(cards)
        attacker = _nosick(Permanent(card=cards["Grizzly Bears"]))
        attacker.attacking = True
        p2.battlefield.append(attacker)
        game.active_player_index = 1
        game._set_phase_and_step("combat", "declare_blockers")
        game.combat_defending_player_index = 0
        game.combat_attackers = {p2.battlefield.index(attacker): 0}
        pairs = game.legal_blocker_assignments(0)
        assert {"blocker_index": 1, "attacker_index": p2.battlefield.index(attacker)} in pairs


# ---------------------------------------------------------------------------
# Hand reveals — "when the player's hand is revealed, such as with word of
# command, it should actually reveal the cards that represent the opponent's
# hand, not just show them in a prompt."
# ---------------------------------------------------------------------------

def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session, session.game


def _hand_names(state, seat):
    return [c if isinstance(c, str) else c["name"] for c in state["players"][seat]["hand"]]


class TestHandRevealSerialization:
    def test_word_of_command_reveals_target_hand_to_caster(self):
        sid, session, game = _session()
        game.players[0].hand = [_C["Word of Command"]]
        game.players[1].hand = [_C["Lightning Bolt"], _C["Grizzly Bears"]]
        game.enforce_mana_costs = False
        game.cast_from_hand(0, "Word of Command", target_player_index=1)
        assert game.pending_word_of_command is not None

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert _hand_names(state, 1) == ["Lightning Bolt", "Grizzly Bears"]
        # The revealed cards carry real payloads (art for the hand fan).
        assert all(isinstance(c, dict) for c in state["players"][1]["hand"])

    def test_word_of_command_does_not_reveal_casters_hand_to_target(self):
        sid, session, game = _session()
        game.players[0].hand = [_C["Word of Command"], _C["Black Lotus"]]
        game.players[1].hand = [_C["Lightning Bolt"]]
        game.enforce_mana_costs = False
        game.cast_from_hand(0, "Word of Command", target_player_index=1)

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        # The target still sees the caster's hand as card backs.
        assert all(c == "<hidden>" for c in state["players"][0]["hand"])

    def test_glasses_of_urza_reveals_target_hand_to_viewer_only(self):
        sid, session, game = _session()
        game.players[0].battlefield = [Permanent(card=_C["Glasses of Urza"])]
        game.players[1].hand = [_C["Grizzly Bears"]]
        game.arm_pending_choice(
            "hand_reveal", 0, target_index=1, card_names=["Grizzly Bears"]
        )

        viewer_state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert _hand_names(viewer_state, 1) == ["Grizzly Bears"]

        target_state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        # Own hand is always visible to its owner; nothing leaks the other way.
        assert _hand_names(target_state, 1) == ["Grizzly Bears"]
        assert all(c == "<hidden>" for c in target_state["players"][0]["hand"])

    def test_hand_hidden_again_after_reveal_dismissed(self):
        sid, session, game = _session()
        game.players[1].hand = [_C["Grizzly Bears"]]
        game.arm_pending_choice("hand_reveal", 0, target_index=1, card_names=["Grizzly Bears"])
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "dismiss_hand_reveal"},
        )
        assert resp.status_code == 200
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert all(c == "<hidden>" for c in state["players"][1]["hand"])
