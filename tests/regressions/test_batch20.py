"""Regression tests for the twentieth batch of bugs reported in-game
(CARD_VERIFICATION.md failures) — the six Arabian Nights failures.

Clusters covered in this batch:
- Bazaar of Baghdad: the discard prompt is a click-the-hand selection showing
  only "N of M selected", not a list of card-name buttons. The old list sent
  one index per click, which confirm_discard rejects whenever more than one
  card must go — so Bazaar's three-card discard was unclearable.
- Camel: "prevent all damage Deserts would deal to this creature and to
  creatures banded with this creature" now covers the band-mates too, not just
  the Camel.
- Diamond Valley: "{T}, Sacrifice a creature:" is recognized as an activated
  ability (the classifier's cost regex only accepted mana/tap symbols), so the
  player is prompted to pick which creature to sacrifice instead of the engine
  silently taking the first one.
- Metamorphosis: the creature-spells-only mana bucket reaches the client, which
  renders it as its own labelled tracker.
- Nafs Asp: "unless they pay {1} before that draw step" is a real decision —
  the victim is prompted at their upkeep instead of the engine auto-paying
  (and auto-tapping their lands) on their behalf.
- Sandstorm: "deals 1 damage to each attacking creature" is a creature-only
  sweep; it previously fell through to the generic single-target damage rule
  and hit the defending player in the face instead.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import PlayerState
from engine.legality import _activated_lines, _classify_activation
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store, _end_turn

client = TestClient(app)

APP_JS = (Path(__file__).resolve().parent.parent.parent / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Sandstorm — "I declared attackers but sandstorm didn't deal damage to them"
# ---------------------------------------------------------------------------

class TestSandstorm:
    def test_compiles_to_the_attacking_creature_sweep(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Sandstorm"])
        kinds = [ins.kind for ins in program.instructions]
        assert "deal_damage_each_attacking_creature" in kinds
        # The generic "deals N damage" fallback must NOT claim it — that rule is
        # what sent the damage to the defending player's face.
        assert "deal_damage" not in kinds

    def _sandstorm_game(self, arn_by_name):
        attacker = _nosick(Permanent(card=_C["Grizzly Bears"], attacking=True))
        home = Permanent(card=_C["Hill Giant"])  # not attacking
        p1 = PlayerState(name="P1", battlefield=[attacker, home])
        p2 = PlayerState(name="P2", hand=[arn_by_name["Sandstorm"]])
        return _game(p1, p2), p1, p2

    def test_damages_every_attacking_creature(self, arn_by_name):
        game, p1, p2 = self._sandstorm_game(arn_by_name)
        game.cast_from_hand(1, "Sandstorm")
        assert p1.battlefield[0].damage_marked == 1

    def test_leaves_non_attacking_creatures_and_players_alone(self, arn_by_name):
        game, p1, p2 = self._sandstorm_game(arn_by_name)
        game.cast_from_hand(1, "Sandstorm")
        assert p1.battlefield[1].damage_marked == 0
        # The reported bug: the damage landed on the defending player instead.
        assert p1.life == 20
        assert p2.life == 20

    def test_kills_a_lethally_damaged_attacker(self, arn_by_name):
        attacker = _nosick(Permanent(card=_C["Savannah Lions"], attacking=True))  # 2/1
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", hand=[arn_by_name["Sandstorm"]])
        game = _game(p1, p2)
        game.cast_from_hand(1, "Sandstorm")
        assert p1.battlefield == []
        assert [c.name for c in p1.graveyard] == ["Savannah Lions"]

    def test_hits_attackers_on_every_battlefield(self, arn_by_name):
        """Attacking-ness is per-permanent, not per-side: whoever is attacking
        when it resolves takes the point."""
        mine = _nosick(Permanent(card=_C["Grizzly Bears"], attacking=True))
        theirs = _nosick(Permanent(card=_C["Hill Giant"], attacking=True))
        p1 = PlayerState(name="P1", battlefield=[mine], hand=[arn_by_name["Sandstorm"]])
        p2 = PlayerState(name="P2", battlefield=[theirs])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Sandstorm")
        assert mine.damage_marked == 1
        assert theirs.damage_marked == 1


# ---------------------------------------------------------------------------
# Camel — "I banded a grizzly bears to camel and attacked, then used a desert
# to hit the grizzly for 1 damage during end of combat. The camel should have
# prevented the damage but the bear died."
# ---------------------------------------------------------------------------

class TestCamel:
    def _banded_game(self, arn_by_name, band=True, attacking=True):
        camel = _nosick(Permanent(card=arn_by_name["Camel"], attacking=attacking))
        bears = _nosick(Permanent(card=_C["Grizzly Bears"], attacking=attacking))
        desert = Permanent(card=arn_by_name["Desert"])
        p1 = PlayerState(name="P1", battlefield=[desert])
        p2 = PlayerState(name="P2", battlefield=[camel, bears])
        game = _game(p1, p2)
        if band:
            game.combat_bands = [[0, 1]]
        return game, p1, camel, bears, desert

    def test_band_mate_is_shielded_from_desert_damage(self, arn_by_name):
        game, p1, camel, bears, desert = self._banded_game(arn_by_name)
        game._mark_damage_on_permanent(bears, 1, source=desert)
        assert bears.damage_marked == 0

    def test_the_camel_itself_is_still_shielded(self, arn_by_name):
        game, p1, camel, bears, desert = self._banded_game(arn_by_name)
        game._mark_damage_on_permanent(camel, 1, source=desert)
        assert camel.damage_marked == 0

    def test_a_creature_outside_the_band_is_not_shielded(self, arn_by_name):
        """The shield follows band membership, not "attacking alongside a Camel"."""
        game, p1, camel, bears, desert = self._banded_game(arn_by_name, band=False)
        game._mark_damage_on_permanent(bears, 1, source=desert)
        assert bears.damage_marked == 1

    def test_band_mate_is_unshielded_once_it_stops_attacking(self, arn_by_name):
        # "As long as this creature is attacking" — the whole clause is
        # conditional on the Camel's attack, so a stale band grants nothing.
        game, p1, camel, bears, desert = self._banded_game(arn_by_name, attacking=False)
        game._mark_damage_on_permanent(bears, 1, source=desert)
        assert bears.damage_marked == 1

    def test_non_desert_damage_still_gets_through_to_a_band_mate(self, arn_by_name):
        game, p1, camel, bears, desert = self._banded_game(arn_by_name)
        bolt = _C["Lightning Bolt"]
        game._mark_damage_on_permanent(bears, 3, source=bolt)
        assert bears.damage_marked == 3

    def test_desert_ability_targeting_the_band_mate_deals_nothing(self, arn_by_name):
        """End to end through Desert's real ability, as reported in-game."""
        game, p1, camel, bears, desert = self._banded_game(arn_by_name)
        game._set_phase_and_step("combat", "end_of_combat")
        game.activate_permanent_ability(
            0, "Desert", target_player_index=1, target_permanent_index=1, ability_index=1
        )
        assert bears.damage_marked == 0
        assert bears in game.players[1].battlefield


# ---------------------------------------------------------------------------
# Diamond Valley — "I should get a prompt to sacrifice a creature of my choice
# by selecting the creature I control on the battlefield"
# ---------------------------------------------------------------------------

class TestDiamondValley:
    def test_prose_cost_line_classifies_as_an_activated_ability(self, arn_by_name):
        """The classifier's cost regex used to require mana/tap symbols all the
        way to the colon, so "{T}, Sacrifice a creature:" read as a cast effect
        and no activation target spec was produced."""
        lines = _activated_lines(arn_by_name["Diamond Valley"])
        assert len(lines) == 1
        assert lines[0].startswith("{t}, sacrifice a creature:")

    def test_activation_spec_asks_for_one_of_your_own_creatures(self, arn_by_name):
        spec = _classify_activation(arn_by_name["Diamond Valley"])
        assert spec["kind"] == "creature"
        assert spec["own_only"] is True
        # Labels the prompt "sacrifice", not "target".
        assert spec["sacrifice_cost"] is True

    def _valley_game(self, arn_by_name):
        valley = _nosick(Permanent(card=arn_by_name["Diamond Valley"]))
        bears = Permanent(card=_C["Grizzly Bears"])  # 2/2, the first creature
        wall = Permanent(card=_C["Wall of Stone"])  # 0/8
        p1 = PlayerState(name="P1", battlefield=[valley, bears, wall])
        p2 = PlayerState(name="P2")
        return _game(p1, p2), p1

    def test_the_chosen_creature_is_sacrificed_not_the_first_one(self, arn_by_name):
        game, p1 = self._valley_game(arn_by_name)
        result = game.activate_permanent_ability(
            0, "Diamond Valley", target_player_index=0, target_permanent_index=2
        )
        assert result.supported
        assert [p.card.name for p in p1.battlefield] == ["Diamond Valley", "Grizzly Bears"]
        # Life equal to the sacrificed creature's toughness — the Wall's 8.
        assert p1.life == 28

    def test_other_symbol_prefixed_prose_costs_still_classify(self, arn_by_name):
        """The widened regex must not mis-file the other prose-cost abilities
        it newly matches (they were previously read as cast effects)."""
        for name in ("Black Lotus", "Jandor's Ring", "Bottle of Suleiman"):
            card = _C.get(name) or arn_by_name[name]
            assert len(_activated_lines(card)) == 1, name
            # None of them target anything on activation.
            assert _classify_activation(card)["kind"] == "none", name

    def test_client_labels_the_pick_as_a_sacrifice(self):
        assert "sacrifice_cost" in APP_JS
        assert "Click a creature you control on the battlefield to sacrifice it." in APP_JS


# ---------------------------------------------------------------------------
# Nafs Asp — "I should get a prompt on my upkeep (before draw) asking if I want
# to pay 1 or take the damage"
# ---------------------------------------------------------------------------

def _nafs_session(with_land: bool):
    """A human-vs-human session paused at seat 0's upkeep with a Nafs Asp
    obligation armed against them."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": 77},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})
    session = store.get(sid)
    game = session.game
    p0 = game.players[0]
    p0.battlefield = [Permanent(card=_C["Forest"])] if with_land else []
    p0.hand = []
    game.pending_draw_step_life_loss.append(
        {"player_index": 0, "amount": 1, "cost": 1, "source_name": "Nafs Asp"}
    )
    # Advance until seat 0's own upkeep, where the decision must surface.
    for _ in range(4):
        if session.current_turn == 0 and game.current_step == "upkeep":
            break
        _end_turn(session, allow_manual_cleanup_selection=False)
    return sid, session, game, p0


class TestNafsAsp:
    def test_the_obligation_surfaces_as_an_upkeep_decision(self, arn_by_name):
        choices = [
            c for c in _nafs_session(with_land=True)[1].upkeep_pay_choices
            if c["card_name"] == "Nafs Asp"
        ]
        assert len(choices) == 1
        assert choices[0]["kind"] == "draw_step_life_loss_unless_pay"
        assert choices[0]["mana"] == {"generic": 1}
        assert choices[0]["life_loss"] == 1

    def test_the_game_pauses_at_upkeep_before_the_draw(self):
        _, session, game, p0 = _nafs_session(with_land=True)
        assert game.current_step == "upkeep"
        # Nothing has been paid or lost yet, and no land was auto-tapped.
        assert p0.life == 20
        assert p0.battlefield[0].tapped is False

    def test_the_prompt_reaches_the_client(self):
        sid, session, game, p0 = _nafs_session(with_land=True)
        info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["upkeep_pay"]
        assert info is not None
        choice = next(c for c in info["pending"] if c["card_name"] == "Nafs Asp")
        assert choice["kind"] == "draw_step_life_loss_unless_pay"
        assert info["can_pay"]["Nafs Asp"] is True

    def test_paying_avoids_the_life_loss(self):
        sid, session, game, p0 = _nafs_session(with_land=True)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pay_upkeep", "card_name": "Nafs Asp"},
        )
        assert resp.status_code == 200, resp.text
        assert p0.life == 20
        assert game.pending_draw_step_life_loss == []
        assert game.current_turn_phase == "precombat_main"

    def test_declining_loses_the_life(self):
        sid, session, game, p0 = _nafs_session(with_land=True)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "sacrifice_upkeep", "card_name": "Nafs Asp"},
        )
        assert resp.status_code == 200, resp.text
        assert p0.life == 19
        # Declining costs life, not the land — nothing was tapped to pay.
        assert p0.battlefield[0].tapped is False
        assert game.pending_draw_step_life_loss == []

    def test_a_player_who_cannot_pay_is_shown_as_unable(self):
        sid, session, game, p0 = _nafs_session(with_land=False)
        info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["upkeep_pay"]
        assert info["can_pay"]["Nafs Asp"] is False

    def test_the_answer_does_not_leak_into_the_next_turn(self):
        sid, session, game, p0 = _nafs_session(with_land=True)
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pay_upkeep", "card_name": "Nafs Asp"},
        )
        assert session.draw_step_life_loss_choices == {}

    def test_headless_play_still_auto_pays(self, arn_by_name):
        """No human answer supplied (AI seats, scripted duels): the engine keeps
        its pay-when-able default rather than blocking."""
        p1 = PlayerState(name="P1", battlefield=[Permanent(card=_C["Forest"])])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.turn = 3
        game.pending_draw_step_life_loss.append(
            {"player_index": 0, "amount": 1, "cost": 1, "source_name": "Nafs Asp"}
        )
        game.resolve_draw_step(0)
        assert p1.life == 20
        assert p1.battlefield[0].tapped is True

    def test_client_labels_the_decline_as_a_life_loss(self):
        assert "draw_step_life_loss_unless_pay" in APP_JS
        assert "Lose ${current?.life_loss || 1} life" in APP_JS


# ---------------------------------------------------------------------------
# Bazaar of Baghdad — "The discard card prompt should not list the cards in
# hand. It should only show the number of cards selected and the total that
# need to be selected. Cards should be selected by clicking on cards in hand."
# ---------------------------------------------------------------------------

def _bazaar_session(arn_by_name):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "H", "guest_name": "G", "seed": 4242},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "J"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    p0 = game.players[0]
    p0.battlefield = [Permanent(card=arn_by_name["Bazaar of Baghdad"])]
    p0.hand = [_C["Forest"], _C["Island"]]
    p0.library = [_C["Swamp"], _C["Mountain"], _C["Plains"], _C["Badlands"]]
    session.current_turn = 0
    game.active_player_index = 0
    game.activate_permanent_ability(0, "Bazaar of Baghdad")
    return sid, session, game, p0


class TestBazaarOfBaghdad:
    def test_the_prompt_asks_for_all_three_at_once(self, arn_by_name):
        sid, session, game, p0 = _bazaar_session(arn_by_name)
        info = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["discard_select"]
        assert info["count"] == 3
        assert len(p0.hand) == 4  # two drawn on top of the starting two

    def test_a_single_index_is_rejected(self, arn_by_name):
        """The old name-button list sent one index per click, which
        confirm_discard rejects — the prompt could never be cleared."""
        sid, session, game, p0 = _bazaar_session(arn_by_name)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "discard_confirm", "discard_indices": [0]},
        )
        assert resp.status_code == 400
        assert game.pending_discard is not None

    def test_the_full_batch_discards_exactly_the_chosen_cards(self, arn_by_name):
        sid, session, game, p0 = _bazaar_session(arn_by_name)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "discard_confirm", "discard_indices": [0, 2, 3]},
        )
        assert resp.status_code == 200, resp.text
        assert [c.name for c in p0.hand] == ["Island"]
        assert sorted(c.name for c in p0.graveyard) == ["Forest", "Mountain", "Swamp"]
        assert game.pending_discard is None

    def test_client_selects_from_hand_and_shows_only_a_count(self):
        # Hand cards become selectable, and the batch is submitted in one go.
        assert "discardSelectable" in APP_JS
        assert "toggleDiscardSelection" in APP_JS
        assert "Selected ${selectedCount} of ${target}" in APP_JS
        assert "click cards in your hand to select" in APP_JS
        # The card-name button list is gone.
        assert "data-discard-index" not in APP_JS


# ---------------------------------------------------------------------------
# Metamorphosis — "When I get the mana from metamorphosis, show a special mana
# tracker that when hovered says this mana can only be used to cast creature
# spells."
# ---------------------------------------------------------------------------

class TestMetamorphosis:
    def _metamorphosis_session(self, arn_by_name):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_human", "host_name": "H", "guest_name": "G", "seed": 909},
        ).json()
        sid = created["session_id"]
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "J"})
        session = store.get(sid)
        game = session.game
        game.enforce_mana_costs = False
        p0 = game.players[0]
        p0.battlefield = [Permanent(card=_C["Grizzly Bears"])]
        p0.hand = [arn_by_name["Metamorphosis"]]
        session.current_turn = 0
        game.active_player_index = 0
        game.cast_from_hand(0, "Metamorphosis", target_permanent_index=0, new_color="G")
        return sid, session, game, p0

    def test_restricted_mana_is_kept_out_of_the_ordinary_pool(self, arn_by_name):
        sid, session, game, p0 = self._metamorphosis_session(arn_by_name)
        assert p0.creature_only_mana.get("G") == 3  # 1 + Grizzly Bears' mana value
        assert p0.mana_pool.get("G", 0) == 0

    def test_the_client_is_told_which_mana_is_restricted(self, arn_by_name):
        sid, session, game, p0 = self._metamorphosis_session(arn_by_name)
        me = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["players"][0]
        assert me["creature_only_mana"] == {"G": 3}
        # Not double-counted into the spendable-on-anything pool.
        assert me["mana_pool"]["G"] == 0

    def test_an_empty_bucket_is_serialized_as_empty(self):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_human", "host_name": "H", "guest_name": "G", "seed": 910},
        ).json()
        sid = created["session_id"]
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "J"})
        me = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["players"][0]
        assert me["creature_only_mana"] == {}

    def test_client_renders_a_distinct_tracker_with_a_hover_explanation(self):
        assert "creature_only_mana" in APP_JS
        assert "This mana can only be used to cast creature spells." in APP_JS
        assert "mana-symbol-restricted" in APP_JS
        styles = (
            Path(__file__).resolve().parent.parent.parent / "web" / "static" / "styles.css"
        ).read_text(encoding="utf-8")
        assert ".mana-symbol-restricted" in styles
