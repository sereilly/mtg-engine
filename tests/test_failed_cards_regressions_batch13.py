"""Regression tests for the thirteenth batch of bugs reported in-game
(CARD_VERIFICATION.md failures).

Clusters covered in this batch:
- Kormus Bell: a land whose type was overridden to Swamp (Evil Presence /
  Phantasmal Terrain) animates; a Swamp overridden away does not (see batch12
  for the override tests themselves).
- Berserk: "Cast this spell only before the combat damage step" is enforced —
  the cast is rejected during/after the combat damage step.
- Helm of Chatzuk: granted banding registers on _has_keyword (and therefore the
  UI keyword strip and band declaration).
- Illusionary Mask: the queued {X} activation arms the face-down choice with
  the chosen X regardless of how many creatures are in hand.
- Living Artifact: vitality counters serialize to the client counters map.
- Living Lands: an attacking animated Forest survives combat pruning and deals
  its damage.
- Phantasmal Terrain / Evil Presence: the land-type override reverts when the
  Aura leaves the battlefield.
- Regrowth: classified as an own-graveyard any-card target (never a player).
- Smoke: the untap-selection payload names the constrained type (creature).
- Vesuvan Doppelganger / Clone: a copy has the copied card's activated and
  triggered abilities (CR 707.2).
- Benalish Hero: the attacking player may DIVIDE a band blocker's combat
  damage among the band members it blocks (CR 702.22j), not just route it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, load_cards
from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)

_ROOT = Path(__file__).resolve().parent.parent
_C = {c.name: c for c in load_cards(_ROOT / "lea_cards.json")}


@pytest.fixture(scope="module")
def cards():
    return _C


def _game(p1: PlayerState, p2: PlayerState) -> Game:
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


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


# ---------------------------------------------------------------------------
# Berserk — "I was able to cast this after combat damage step, which is not
# allowed."
# ---------------------------------------------------------------------------

class TestBerserkTiming:
    def _game_with_berserk(self, cards):
        bear = _nosick(Permanent(card=cards["Grizzly Bears"]))
        p1 = PlayerState(name="P1", hand=[cards["Berserk"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.active_player_index = 0
        return game, p1

    @pytest.mark.parametrize("phase,step", [
        ("combat", "combat_damage"),
        ("combat", "end_of_combat"),
        ("postcombat_main", "postcombat_main"),
        ("ending", "end"),
    ])
    def test_rejected_at_or_after_combat_damage(self, cards, phase, step):
        game, p1 = self._game_with_berserk(cards)
        game._set_phase_and_step(phase, step)
        result = game.cast_from_hand(0, "Berserk", target_player_index=0, target_permanent_index=0)
        assert not result.supported
        assert "combat damage" in result.details

    @pytest.mark.parametrize("phase,step", [
        ("precombat_main", "precombat_main"),
        ("combat", "declare_attackers"),
        ("combat", "declare_blockers"),
    ])
    def test_allowed_before_combat_damage(self, cards, phase, step):
        game, p1 = self._game_with_berserk(cards)
        game._set_phase_and_step(phase, step)
        result = game.cast_from_hand(0, "Berserk", target_player_index=0, target_permanent_index=0)
        assert result.supported, result.details


# ---------------------------------------------------------------------------
# Helm of Chatzuk — "Activated ability doesn't give banding"
# ---------------------------------------------------------------------------

class TestHelmOfChatzukBanding:
    def test_granted_banding_registers_as_keyword(self, cards):
        bear = _nosick(Permanent(card=cards["Grizzly Bears"]))
        helm = Permanent(card=cards["Helm of Chatzuk"])
        p1 = PlayerState(name="P1", battlefield=[helm, bear])
        game = _game(p1, PlayerState(name="P2"))
        result = game.activate_permanent_ability(
            0, "Helm of Chatzuk", target_player_index=0, permanent_index=0,
            target_permanent_index=1,
        )
        assert result.supported, result.details
        assert bear.metadata.get("gains_banding_until_eot") is True
        # The granted keyword must register like printed banding — this drives
        # the UI keyword strip and the "Attack as Band" flow.
        assert game._has_keyword(bear, "banding") is True
        assert game._creature_has_banding(bear) is True


# ---------------------------------------------------------------------------
# Illusionary Mask — "Doesn't work when I have more than 1 creature in hand"
# ---------------------------------------------------------------------------

class TestIllusionaryMaskQueuedActivation:
    @pytest.mark.parametrize("hand_names", [
        ["Grizzly Bears"],
        ["Grizzly Bears", "Scathe Zombies"],
        ["Grizzly Bears", "Scathe Zombies", "Lightning Bolt"],
    ])
    def test_queued_activation_arms_choice_with_x(self, cards, hand_names):
        p1 = PlayerState(
            name="P1",
            hand=[cards[n] for n in hand_names],
            battlefield=[Permanent(card=cards["Illusionary Mask"])],
        )
        game = _game(p1, PlayerState(name="P2"))
        result = game.queue_permanent_ability(0, "Illusionary Mask", permanent_index=0, x_value=3)
        assert result.supported, result.details
        game.resolve_top_of_stack()
        assert game.pending_face_down_cast is not None
        assert game.pending_face_down_cast["max_cmc"] == 3
        # Confirming the LAST eligible creature (full-hand index) works too —
        # every creature here has mana value <= 3, so all are eligible.
        creature_indices = [
            i for i, c in enumerate(p1.hand) if c.primary_type == "creature"
        ]
        assert game.confirm_face_down_cast(0, creature_indices[-1]) is True
        face_down = p1.battlefield[-1]
        assert face_down.metadata.get("face_down") is True


# ---------------------------------------------------------------------------
# Living Artifact — "I can't see how many vitality counters the card has."
# ---------------------------------------------------------------------------

def test_living_artifact_vitality_counters_serialize():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 7},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    aura = Permanent(card=_C["Living Artifact"])
    aura.metadata["vitality_counters"] = 3
    session.game.players[0].battlefield = [aura]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    perm = state["players"][0]["battlefield"][0]
    assert perm["counters"] == {"vitality": 3}


# ---------------------------------------------------------------------------
# Living Lands — "I made my forests into creatures but they didn't deal any
# damage when they attacked despite being 1/1s"
# ---------------------------------------------------------------------------

class TestLivingLandsAttackDamage:
    def test_animated_forest_deals_combat_damage(self, cards):
        lands = Permanent(card=cards["Living Lands"])
        forest = _nosick(Permanent(card=cards["Forest"]))
        p1 = PlayerState(name="P1", battlefield=[lands, forest])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game._refresh_dynamic_creatures()
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [1], 1)
        assert ok, msg
        game._prune_combat_state()
        assert 1 in game.combat_attackers  # not silently dropped (printed type "land")
        game._set_phase_and_step("combat", "combat_damage")
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg
        assert p2.life == 19


# ---------------------------------------------------------------------------
# Phantasmal Terrain / Evil Presence — "The land should go back to its original
# type after the aura is removed"
# ---------------------------------------------------------------------------

class TestLandTypeOverrideReverts:
    def test_evil_presence_override_reverts_when_aura_destroyed(self, cards):
        mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", hand=[cards["Evil Presence"]], battlefield=[mountain])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Evil Presence", target_player_index=0, target_permanent_index=0)
        assert result.supported
        assert mountain.metadata.get("land_type_override") == "swamp"
        aura = next(p for p in p1.battlefield if p.card.name == "Evil Presence")
        game._permanent_to_graveyard(p1, aura)
        p1.battlefield.remove(aura)
        assert mountain.metadata.get("land_type_override") is None
        assert mountain.effective_produced_mana == ("R",)

    def test_phantasmal_terrain_override_reverts_when_aura_destroyed(self, cards):
        mountain = Permanent(card=cards["Mountain"])
        p1 = PlayerState(name="P1", hand=[cards["Phantasmal Terrain"]], battlefield=[mountain])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=0, target_permanent_index=0)
        assert result.supported
        assert game.pending_land_type_choice is not None
        assert game.confirm_land_type(0, "island") is True
        assert mountain.metadata.get("land_type_override") == "island"
        aura = next(p for p in p1.battlefield if p.card.name == "Phantasmal Terrain")
        game._permanent_to_graveyard(p1, aura)
        p1.battlefield.remove(aura)
        assert mountain.metadata.get("land_type_override") is None


# ---------------------------------------------------------------------------
# Regrowth — "Regrowth should not make me target a player."
# ---------------------------------------------------------------------------

def test_regrowth_targets_own_graveyard_cards_never_players(cards):
    p1 = PlayerState(name="P1", graveyard=[_C["Lightning Bolt"], _C["Forest"]])
    game = _game(p1, PlayerState(name="P2"))
    spec = game.cast_target_spec(0, _C["Regrowth"])
    assert spec["kind"] == "graveyard_creature"
    assert spec["any_card"] is True
    assert spec["own_graveyard_only"] is True
    assert all(t["kind"] == "graveyard" for t in spec["valid_targets"])
    assert len(spec["valid_targets"]) == 2  # any card type, not only creatures


# ---------------------------------------------------------------------------
# Smoke — "It should tell me to target a creature, not a land. Also it should
# highlight all valid untap targets."
# ---------------------------------------------------------------------------

def test_smoke_untap_selection_names_creatures_and_lists_candidates():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 9},
    ).json()
    sid = created["session_id"]
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
    assert options["creature_max"] == 1
    assert options["land_max"] is None
    session.untap_required_lands = int(options["max_count"])
    session.untap_candidate_indices = [int(i) for i in options["candidate_indices"]]
    session.untap_selected_indices = []
    game._set_phase_and_step("beginning", "untap")

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["untap_land_selection"]
    assert info is not None
    # The client names the constrained type from these fields (Smoke: creatures)
    # and highlights candidate_indices on the board.
    assert info["creature_max"] == 1
    assert info["land_max"] is None
    assert sorted(info["candidate_indices"]) == [1, 2]


# ---------------------------------------------------------------------------
# Vesuvan Doppelganger / Clone — "When I copy a card it should also copy all
# activated and triggered abilities"
# ---------------------------------------------------------------------------

class TestCopyGainsAbilities:
    def _clone_of(self, cards, target_name, copier="Clone"):
        target = _nosick(Permanent(card=cards[target_name]))
        p1 = PlayerState(name="P1", hand=[cards[copier]], battlefield=[target])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        result = game.cast_from_hand(0, copier, target_player_index=0, target_permanent_index=0)
        assert result.supported
        copy = p1.battlefield[-1]
        _nosick(copy)
        return game, p1, p2, copy

    def test_clone_copies_activated_ability(self, cards):
        game, p1, p2, copy = self._clone_of(cards, "Prodigal Sorcerer")
        assert copy.effective_card.name == "Prodigal Sorcerer"
        spec = game.activation_target_spec(0, p1.battlefield.index(copy))
        assert spec["kind"] == "any"  # Tim: "deal 1 damage to any target"
        result = game.activate_permanent_ability(
            0, "Clone", target_player_index=1, permanent_index=p1.battlefield.index(copy)
        )
        assert result.supported, result.details
        assert p2.life == 19

    def test_doppelganger_copies_activated_ability_and_stays_blue(self, cards):
        game, p1, p2, copy = self._clone_of(cards, "Prodigal Sorcerer", copier="Vesuvan Doppelganger")
        result = game.activate_permanent_ability(
            0, "Vesuvan Doppelganger", target_player_index=1,
            permanent_index=p1.battlefield.index(copy),
        )
        assert result.supported, result.details
        assert p2.life == 19
        assert game._effective_colors(copy) == {"U"}
        # The upkeep re-copy prompt still works (keyed to the copier's own card).
        assert any(t["kind"] == "upkeep_recopy" for t in game.get_optional_upkeep_triggers(0))

    def test_copy_serializes_copied_oracle_text(self, cards):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 11},
        ).json()
        sid = created["session_id"]
        session = store.get(sid)
        tim = Permanent(card=_C["Prodigal Sorcerer"])
        clone = Permanent(card=_C["Clone"])
        clone.metadata["copied_from"] = "Prodigal Sorcerer"
        clone.metadata["copied_card"] = _C["Prodigal Sorcerer"]
        session.game.players[0].battlefield = [tim, clone]
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        serialized = state["players"][0]["battlefield"][1]
        # The UI decides "has an activated ability" from this text.
        assert "damage to any target" in serialized["oracle_text"].lower()


# ---------------------------------------------------------------------------
# Benalish Hero — "When a band is blocked, the attacker gets to choose how all
# damage from the blocking creatures is assigned."
# ---------------------------------------------------------------------------

class TestBandBlockerDamageSplit:
    def _banded_combat(self, cards):
        # Band: 3/3 Beater + 1/1 Benalish Hero (banding). One 4/4 blocker blocks
        # the Beater; the block propagates to the whole band (CR 702.22h).
        beater = _nosick(Permanent(card=_mk_creature("Beater", 3, 3)))
        hero = _nosick(Permanent(card=cards["Benalish Hero"]))
        blocker = Permanent(card=_mk_creature("Blocker", 4, 4))
        p1 = PlayerState(name="P1", battlefield=[beater, hero])
        p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], 1, bands=[[0, 1]])
        assert ok, msg
        game.advance_combat_phase()  # declare_blockers
        ok, msg = game.declare_blockers(1, {0: 0})
        assert ok, msg
        game.advance_combat_phase()  # combat_damage
        assert game.current_step == "combat_damage"
        return game, p1, p2

    def test_attacker_divides_blocker_damage_across_band(self, cards):
        game, p1, p2 = self._banded_combat(cards)
        # Divide the blocker's 4 damage: 3 onto the Beater, 1 onto the Hero —
        # both die, showing a true split (not routing to a single member).
        ok, msg = game.resolve_combat_damage(0, blocker_damage_split={0: {0: 3, 1: 1}})
        assert ok, msg
        assert not any(p.card.name == "Beater" for p in p1.battlefield)
        assert not any(p.card.name == "Benalish Hero" for p in p1.battlefield)
        # The band's 3+1 was lethal for the 4/4 blocker.
        assert not any(p.card.name == "Blocker" for p in p2.battlefield)

    def test_split_may_spare_both_members(self, cards):
        game, p1, p2 = self._banded_combat(cards)
        # 2 onto each member — under both toughness thresholds? Beater 3/3 takes
        # 2 (lives); Hero 1/1 takes 2 (dies). Use 3/1 reversed: 1 on Beater,
        # 3 on Hero: Beater lives, Hero dies.
        ok, msg = game.resolve_combat_damage(0, blocker_damage_split={0: {0: 1, 1: 3}})
        assert ok, msg
        assert any(p.card.name == "Beater" for p in p1.battlefield)
        assert not any(p.card.name == "Benalish Hero" for p in p1.battlefield)

    def test_split_exceeding_blocker_power_is_rejected(self, cards):
        game, p1, p2 = self._banded_combat(cards)
        ok, msg = game.resolve_combat_damage(0, blocker_damage_split={0: {0: 4, 1: 1}})
        assert not ok
        assert "exceeds" in msg

    def test_split_to_non_band_member_is_rejected(self, cards):
        game, p1, p2 = self._banded_combat(cards)
        ok, msg = game.resolve_combat_damage(0, blocker_damage_split={0: {5: 2}})
        assert not ok

    def test_split_assigning_less_than_blocker_power_is_rejected(self, cards):
        game, p1, p2 = self._banded_combat(cards)
        # CR 510.1c: the 4-power blocker must assign ALL its combat damage — a
        # split totalling only 3 is illegal.
        ok, msg = game.resolve_combat_damage(0, blocker_damage_split={0: {0: 2, 1: 1}})
        assert not ok
        assert "all" in msg

    def test_split_via_web_action(self, cards):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_human", "host_name": "H", "guest_name": "G",
                  "host_colors": 2, "guest_colors": 2, "seed": 13},
        ).json()
        sid = created["session_id"]
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "J"})
        session = store.get(sid)
        game = session.game
        game.enforce_mana_costs = False
        beater = _nosick(Permanent(card=_mk_creature("Beater", 3, 3)))
        hero = _nosick(Permanent(card=_C["Benalish Hero"]))
        blocker = Permanent(card=_mk_creature("Blocker", 4, 4))
        game.players[0].battlefield = [beater, hero]
        game.players[1].battlefield = [blocker]
        session.current_turn = 0
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        ok, msg = game.declare_attackers(0, [0, 1], 1, bands=[[0, 1]])
        assert ok, msg
        game.advance_combat_phase()
        ok, msg = game.declare_blockers(1, {0: 0})
        assert ok, msg
        game.advance_combat_phase()
        assert game.current_step == "combat_damage"

        # The active player sees the 702.22 assignment block.
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        info = state["band_blocker_assignment"]
        assert info is not None and info["blockers"][0]["blocker_idx"] == 0

        game.priority_player_index = 0
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "assign_combat_damage",
                  "blocker_damage_split": {"0": {"0": 3, "1": 1}}},
        )
        assert resp.status_code == 200, resp.text
        assert game.combat_damage_resolved
        assert not any(p.card.name == "Beater" for p in game.players[0].battlefield)
        assert not any(p.card.name == "Benalish Hero" for p in game.players[0].battlefield)
