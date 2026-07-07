"""Regression tests for the eighteenth batch of bugs reported in-game
(CARD_VERIFICATION.md failures) — the fifteen Arabian Nights failures.

Clusters covered in this batch:
- Aladdin's Lamp: the ability arms a REPLACEMENT for the next draw this turn
  (look at the top X, draw one, bottom the rest) instead of drawing outright;
  X can't be 0; a human gets a card-choice prompt, headless keeps the top card.
- Ali Baba: "Tap target Wall" carries a Wall-only target filter — the target
  spec offers only Walls and an explicitly chosen non-Wall fizzles.
- Army of Allah: "Attacking creatures get +2/+0" buffs only creatures that are
  attacking at resolution, not every creature.
- Cuombajj Witches: the second point of damage goes to "any target of an
  opponent's choice" — a human chooser gets a prompt, an AI chooser picks
  deterministically (kill the activator's creature if lethal, else their face).
- Ghazbán Ogre: control moves to the strict life leader at the controller's
  upkeep, in both directions (and not on a tie).
- Hasran Ogress: the attack trigger offers "pay {2}" — declining (or being
  unable to pay) deals 3 damage to the controller.
- Island of Wak-Wak: a land with no mana ability produces NO mana (previously
  a phantom green); its real ability sets a flier's base power to 0.
- Khabál Ghoul: the end-step trigger adds one +1/+1 counter per creature that
  died this turn (and doesn't fire when none died).
- Library of Alexandria: the draw ability works and is gated on exactly seven
  cards in hand; the mana ability still taps for {C}.
- Merchant Ship: the defending-player-controls-an-Island attack gate honors
  Magical Hack/Phantasmal Terrain land-type overrides.
- Metamorphosis: adds X mana of the CHOSEN color where X is 1 PLUS the
  sacrificed creature's mana value (was: always black, and only X).
- Old Man of the Sea: "you may choose not to untap" — the untap step honors a
  keep-tapped choice, and AI/headless keeps it tapped while its steal is live.
- Pyramids: "{2}: Choose one —" compiles into one activated ability per mode
  (never a cast-time modal); mode 1 destroys only Auras attached to lands,
  mode 2 shields a land from its next destruction this turn.
- Sandals of Abdallah: grants islandwalk until end of turn and is destroyed
  when that creature dies this turn.
- Sindbad: the drawn card is revealed and discarded unless it's a land.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C
from web.app import app, store, _begin_turn

client = TestClient(app)


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
# Aladdin's Lamp — "I activated the ability on my upkeep and it didn't trigger
# on my draw step"
# ---------------------------------------------------------------------------

class TestAladdinsLamp:
    def _lamp_game(self, arn_by_name):
        lamp = _nosick(Permanent(card=arn_by_name["Aladdin's Lamp"]))
        library = [_C["Lightning Bolt"], _C["Forest"], _C["Island"], _C["Grizzly Bears"], _C["Swamp"]]
        p1 = PlayerState(name="P1", battlefield=[lamp], library=list(library))
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.turn = 3  # avoid the first-turn draw skip (CR 103.8a)
        return game, p1, lamp

    def test_x_zero_is_rejected(self, arn_by_name):
        game, p1, lamp = self._lamp_game(arn_by_name)
        result = game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=0)
        assert not result.supported
        assert "X can't be 0" in result.details

    def test_activation_arms_replacement_not_a_draw(self, arn_by_name):
        game, p1, lamp = self._lamp_game(arn_by_name)
        result = game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=3)
        assert result.supported
        assert p1.hand == []  # nothing drawn yet — the draw is replaced later
        assert game.lamp_draw_replacements == {0: 3}

    def test_interactive_draw_step_prompts_and_confirm_draws_chosen_card(self, arn_by_name):
        game, p1, lamp = self._lamp_game(arn_by_name)
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=3)
        game.interactive_seats = {0}
        game.resolve_draw_step(0)
        pending = game.pending_lamp_draw
        assert pending is not None
        assert pending["card_names"] == ["Lightning Bolt", "Forest", "Island"]
        assert game.confirm_lamp_draw(0, 2) is True
        assert [c.name for c in p1.hand] == ["Island"]
        # The other two revealed cards went to the bottom, not the top.
        assert {c.name for c in p1.library[-2:]} == {"Lightning Bolt", "Forest"}
        assert p1.library[0].name == "Grizzly Bears"

    def test_headless_draw_keeps_top_card(self, arn_by_name):
        game, p1, lamp = self._lamp_game(arn_by_name)
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=2)
        game.resolve_draw_step(0)
        assert [c.name for c in p1.hand] == ["Lightning Bolt"]

    def test_replacement_expires_with_the_turn(self, arn_by_name):
        game, p1, lamp = self._lamp_game(arn_by_name)
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=3)
        game.begin_turn_bookkeeping(0)  # a new turn begins
        assert game.lamp_draw_replacements == {}
        game.resolve_draw_step(0)
        assert [c.name for c in p1.hand] == ["Lightning Bolt"]  # a normal draw


# ---------------------------------------------------------------------------
# Ali Baba — "Didn't get a target selection prompt"
# ---------------------------------------------------------------------------

class TestAliBaba:
    def _baba_game(self, arn_by_name):
        baba = _nosick(Permanent(card=arn_by_name["Ali Baba"]))
        wall = _nosick(Permanent(card=_C["Wall of Stone"]))
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[baba], mana_pool={"R": 2})
        p2 = PlayerState(name="P2", battlefield=[bear, wall])
        return _game(p1, p2), p1, p2, wall, bear

    def test_target_spec_offers_only_walls(self, arn_by_name):
        game, p1, p2, wall, bear = self._baba_game(arn_by_name)
        spec = game.activation_target_spec(0, 0)
        assert spec["kind"] == "creature"
        assert spec.get("wall_only") is True
        assert [t["name"] for t in spec["valid_targets"]] == ["Wall of Stone"]

    def test_taps_the_chosen_wall(self, arn_by_name):
        game, p1, p2, wall, bear = self._baba_game(arn_by_name)
        result = game.activate_permanent_ability(
            0, "Ali Baba", target_player_index=1, target_permanent_index=p2.battlefield.index(wall)
        )
        assert result.supported
        assert wall.tapped is True
        assert bear.tapped is False

    def test_explicit_non_wall_target_fizzles(self, arn_by_name):
        game, p1, p2, wall, bear = self._baba_game(arn_by_name)
        game.activate_permanent_ability(
            0, "Ali Baba", target_player_index=1, target_permanent_index=p2.battlefield.index(bear)
        )
        assert bear.tapped is False
        assert wall.tapped is False


# ---------------------------------------------------------------------------
# Army of Allah — "This should only buff attacking creatures"
# ---------------------------------------------------------------------------

class TestArmyOfAllah:
    def test_only_attacking_creatures_get_the_buff(self, arn_by_name):
        attacker = _nosick(Permanent(card=_C["Grizzly Bears"]))
        attacker.attacking = True
        idle = _nosick(Permanent(card=_C["Scryb Sprites"]))
        p1 = PlayerState(name="P1", hand=[arn_by_name["Army of Allah"]], battlefield=[attacker, idle])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Army of Allah", target_player_index=1)
        game.resolve_stack()
        assert attacker.effective_power == 4  # 2 + 2
        assert idle.effective_power == 1  # untouched

    def test_compile_carries_attacking_only(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Army of Allah"])
        instr = next(i for i in program.instructions if i.kind == "buff_creatures_global")
        assert instr.payload.get("attacking_only") is True


# ---------------------------------------------------------------------------
# Cuombajj Witches — "The opponent didn't get to choose a target to take 1
# damage"
# ---------------------------------------------------------------------------

class TestCuombajjWitches:
    def test_ai_chooser_kills_activators_creature(self, arn_by_name):
        witches = _nosick(Permanent(card=arn_by_name["Cuombajj Witches"]))
        sprite = _nosick(Permanent(card=_C["Scryb Sprites"]))  # 1/1 — dies to 1
        p1 = PlayerState(name="P1", battlefield=[witches, sprite], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        result = game.activate_permanent_ability(0, "Cuombajj Witches", target_player_index=1)
        assert result.supported
        assert p2.life == 19  # the controller's chosen point (face fallback)
        assert sprite not in p1.battlefield  # the AI chooser's point killed the sprite

    def test_human_chooser_gets_pending_choice_and_confirm_applies_it(self, arn_by_name):
        witches = _nosick(Permanent(card=arn_by_name["Cuombajj Witches"]))
        p1 = PlayerState(name="P1", battlefield=[witches], life=20)
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.interactive_seats = {1}
        game.activate_permanent_ability(0, "Cuombajj Witches", target_player_index=1)
        pending = game.pending_opponent_damage
        assert pending is not None and pending["chooser_index"] == 1
        assert game.confirm_opponent_damage_choice(1, 0, None) is True
        assert p1.life == 19
        assert game.pending_opponent_damage is None

    def test_prompt_blocks_chooser_actions_via_api(self):
        sid, session, game = _session()
        game.pending_opponent_damage = {
            "chooser_index": 0, "caster_index": 1, "amount": 1, "card_name": "Cuombajj Witches",
        }
        resp = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
        )
        assert resp.status_code == 400
        assert "opponent-choice damage" in resp.json()["detail"]
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "opponent_damage_choose", "target_seat": 1},
        )
        assert resp.status_code == 200
        assert game.players[1].life == 19


# ---------------------------------------------------------------------------
# Ghazbán Ogre — "When my opponent controls ghazban and has less life, it
# should give it back to me during their upkeep"
# ---------------------------------------------------------------------------

class TestGhazbanOgre:
    def _ogre(self, arn_by_name):
        return Permanent(card=arn_by_name["Ghazbán Ogre"])

    def test_moves_to_life_leader_on_controllers_upkeep(self, arn_by_name):
        ogre = self._ogre(arn_by_name)
        p1 = PlayerState(name="P1", life=20)
        p2 = PlayerState(name="P2", life=15, battlefield=[ogre])
        game = _game(p1, p2)
        game.active_player_index = 1
        game.resolve_upkeep(1)
        game.resolve_stack()
        assert ogre in p1.battlefield
        assert ogre not in p2.battlefield

    def test_moves_away_from_controller_on_their_own_upkeep(self, arn_by_name):
        ogre = self._ogre(arn_by_name)
        p1 = PlayerState(name="P1", life=10, battlefield=[ogre])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game.resolve_upkeep(0)
        game.resolve_stack()
        assert ogre in p2.battlefield

    def test_no_transfer_on_a_life_tie(self, arn_by_name):
        ogre = self._ogre(arn_by_name)
        p1 = PlayerState(name="P1", life=20, battlefield=[ogre])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.resolve_upkeep(0)
        game.resolve_stack()
        assert ogre in p1.battlefield

    def test_does_not_fire_on_noncontrollers_upkeep(self, arn_by_name):
        ogre = self._ogre(arn_by_name)
        p1 = PlayerState(name="P1", life=10, battlefield=[ogre])
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.active_player_index = 1
        game.resolve_upkeep(1)  # NOT the controller's upkeep
        game.resolve_stack()
        assert ogre in p1.battlefield


# ---------------------------------------------------------------------------
# Hasran Ogress — "When I attacked it didn't give me a prompt to pay or take
# damage"
# ---------------------------------------------------------------------------

class TestHasranOgress:
    def _attack(self, arn_by_name, mana_pool=None):
        ogress = _nosick(Permanent(card=arn_by_name["Hasran Ogress"]))
        p1 = PlayerState(name="P1", battlefield=[ogress], life=20, mana_pool=mana_pool or {})
        p2 = PlayerState(name="P2", life=20)
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.declare_attackers(0, [0])
        game.resolve_stack()
        return game, p1

    def test_attack_arms_a_pay_or_damage_choice(self, arn_by_name):
        game, p1 = self._attack(arn_by_name)
        assert len(game.pending_optional_pays) == 1
        entry = game.pending_optional_pays[0]
        assert entry["card_name"] == "Hasran Ogress"
        assert entry["cost"] == 2
        assert entry["damage"] == 3

    def test_declining_deals_three_damage_to_controller(self, arn_by_name):
        game, p1 = self._attack(arn_by_name)
        game.confirm_optional_pay(0, "Hasran Ogress", accept=False)
        assert p1.life == 17

    def test_paying_prevents_the_damage(self, arn_by_name):
        game, p1 = self._attack(arn_by_name, mana_pool={"B": 2})
        game.confirm_optional_pay(0, "Hasran Ogress", accept=True)
        assert p1.life == 20
        assert sum(p1.mana_pool.values()) == 0

    def test_headless_auto_resolve_without_mana_takes_damage(self, arn_by_name):
        game, p1 = self._attack(arn_by_name)
        game.auto_resolve_pending_optional_pays()
        assert p1.life == 17
        assert game.pending_optional_pays == []


# ---------------------------------------------------------------------------
# Island of Wak-Wak — "The activated ability didn't work and instead gave 1
# green mana. It should not provide any mana."
# ---------------------------------------------------------------------------

class TestIslandOfWakWak:
    def test_tap_land_for_mana_refuses_mana_less_land(self, arn_by_name):
        wak = Permanent(card=arn_by_name["Island of Wak-Wak"])
        p1 = PlayerState(name="P1", battlefield=[wak])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        assert game.tap_land_for_mana(0, "Island of Wak-Wak", permanent_index=0) is False
        assert wak.tapped is False
        assert sum(p1.mana_pool.values()) == 0

    def test_ability_sets_fliers_base_power_to_zero(self, arn_by_name):
        wak = _nosick(Permanent(card=arn_by_name["Island of Wak-Wak"]))
        flier = _nosick(Permanent(card=_C["Phantom Monster"]))
        p1 = PlayerState(name="P1", battlefield=[wak])
        p2 = PlayerState(name="P2", battlefield=[flier])
        game = _game(p1, p2)
        spec = game.activation_target_spec(0, 0)
        assert spec["kind"] == "creature" and spec.get("flying_only") is True
        result = game.activate_permanent_ability(
            0, "Island of Wak-Wak", target_player_index=1, target_permanent_index=0
        )
        assert result.supported
        game.resolve_stack()
        assert flier.effective_power == 0
        assert sum(p1.mana_pool.values()) == 0

    def test_web_tap_action_fails_and_activate_works(self, arn_by_name):
        sid, session, game = _session()
        wak = _nosick(Permanent(card=arn_by_name["Island of Wak-Wak"]))
        game.players[0].battlefield.append(wak)
        flier = _nosick(Permanent(card=_C["Phantom Monster"]))
        game.players[1].battlefield.append(flier)
        widx = game.players[0].battlefield.index(wak)
        fidx = game.players[1].battlefield.index(flier)

        resp = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "tap", "permanent_index": widx}
        )
        assert resp.status_code == 400
        assert sum(game.players[0].mana_pool.values()) == 0

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "activate", "permanent_index": widx,
                  "target_seat": 1, "target_permanent_index": fidx},
        )
        assert resp.status_code == 200
        game.resolve_stack()
        assert flier.effective_power == 0
        assert sum(game.players[0].mana_pool.values()) == 0


# ---------------------------------------------------------------------------
# Khabál Ghoul — "Ability didn't trigger"
# ---------------------------------------------------------------------------

class TestKhabalGhoul:
    def test_counters_equal_creature_deaths_this_turn(self, arn_by_name):
        ghoul = _nosick(Permanent(card=arn_by_name["Khabál Ghoul"]))
        p1 = PlayerState(name="P1", battlefield=[ghoul])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.creatures_died_this_turn = 2
        game.active_player_index = 0
        game.resolve_end_step(0)
        game.resolve_stack()
        assert ghoul.effective_power == 3  # 1 + 2 counters
        assert ghoul.effective_toughness == 3

    def test_no_counters_when_nothing_died(self, arn_by_name):
        ghoul = _nosick(Permanent(card=arn_by_name["Khabál Ghoul"]))
        p1 = PlayerState(name="P1", battlefield=[ghoul])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.resolve_end_step(0)
        game.resolve_stack()
        assert ghoul.effective_power == 1

    def test_counts_a_real_death(self, arn_by_name):
        ghoul = _nosick(Permanent(card=arn_by_name["Khabál Ghoul"]))
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[ghoul], hand=[_C["Lightning Bolt"]])
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
        game.resolve_stack()
        assert bear not in p2.battlefield
        game.resolve_end_step(0)
        game.resolve_stack()
        assert ghoul.effective_power == 2


# ---------------------------------------------------------------------------
# Library of Alexandria — "The ability to draw a card doesn't work. Also, the
# button for that ability should only be enabled if it meets the hand size
# restriction"
# ---------------------------------------------------------------------------

class TestLibraryOfAlexandria:
    def _library_session(self, arn_by_name):
        sid, session, game = _session()
        lib = _nosick(Permanent(card=arn_by_name["Library of Alexandria"]))
        game.players[0].battlefield.append(lib)
        return sid, session, game, lib, game.players[0].battlefield.index(lib)

    def test_draw_requires_exactly_seven_cards(self, arn_by_name):
        sid, session, game, lib, idx = self._library_session(arn_by_name)
        game.players[0].hand = [_C["Forest"]] * 4
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "activate", "permanent_index": idx, "ability_index": 1},
        )
        assert resp.status_code == 400
        assert "exactly seven cards" in resp.json()["detail"]
        assert lib.tapped is False

    def test_draw_works_with_seven_cards(self, arn_by_name):
        sid, session, game, lib, idx = self._library_session(arn_by_name)
        game.players[0].hand = [_C["Forest"]] * 7
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "activate", "permanent_index": idx, "ability_index": 1},
        )
        assert resp.status_code == 200
        game.resolve_stack()
        assert len(game.players[0].hand) == 8
        assert lib.tapped is True

    def test_tap_still_produces_colorless(self, arn_by_name):
        sid, session, game, lib, idx = self._library_session(arn_by_name)
        resp = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "tap", "permanent_index": idx}
        )
        assert resp.status_code == 200
        assert game.players[0].mana_pool.get("C") == 1

    def test_client_greys_out_gated_ability(self):
        from pathlib import Path

        app_js = (Path(__file__).resolve().parent.parent.parent / "web" / "static" / "app.js").read_text(encoding="utf-8")
        assert "abilityOptionDisabledReason" in app_js
        assert "exactly seven cards in hand" in app_js


# ---------------------------------------------------------------------------
# Merchant Ship — "If I use magical hack to change a basic land to an island,
# that should satisfy the attack restriction"
# ---------------------------------------------------------------------------

class TestMerchantShip:
    def _ship_game(self, arn_by_name, defender_battlefield):
        ship = _nosick(Permanent(card=arn_by_name["Merchant Ship"]))
        island = Permanent(card=_C["Island"])  # keeps the ship alive ("no Islands" sac)
        p1 = PlayerState(name="P1", battlefield=[ship, island])
        p2 = PlayerState(name="P2", battlefield=defender_battlefield)
        game = _game(p1, p2)
        return game, ship

    def test_cannot_attack_without_defending_island(self, arn_by_name):
        game, ship = self._ship_game(arn_by_name, [Permanent(card=_C["Mountain"])])
        assert game.can_attack(ship, 1) is False

    def test_printed_island_allows_attack(self, arn_by_name):
        game, ship = self._ship_game(arn_by_name, [Permanent(card=_C["Island"])])
        assert game.can_attack(ship, 1) is True

    def test_hacked_land_type_override_counts_as_island(self, arn_by_name):
        mountain = Permanent(card=_C["Mountain"])
        mountain.metadata["land_type_override"] = "island"
        game, ship = self._ship_game(arn_by_name, [mountain])
        assert game.can_attack(ship, 1) is True


# ---------------------------------------------------------------------------
# Metamorphosis — "I didn't get to choose which color. Also it gave me X mana
# instead of X + 1"
# ---------------------------------------------------------------------------

class TestMetamorphosis:
    def test_adds_cmc_plus_one_of_chosen_color(self, arn_by_name):
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))  # mana value 2
        p1 = PlayerState(name="P1", hand=[arn_by_name["Metamorphosis"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(
            0, "Metamorphosis", target_player_index=0, target_permanent_index=0, new_color="U"
        )
        game.resolve_stack()
        # "Spend this mana only to cast creature spells": the mana now lands in
        # the creature-spells-only bucket, not the unrestricted pool.
        assert p1.creature_only_mana.get("U") == 3  # 2 + 1
        assert p1.mana_pool.get("U", 0) == 0
        assert p1.creature_only_mana.get("B", 0) == 0
        assert any(c.name == "Grizzly Bears" for c in p1.graveyard)

    def test_lea_sacrifice_still_adds_black_equal_to_cmc(self):
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
        p1 = PlayerState(name="P1", hand=[_C["Sacrifice"]], battlefield=[bear])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Sacrifice", target_player_index=0, target_permanent_index=0)
        game.resolve_stack()
        assert p1.mana_pool.get("B") == 2  # unchanged: exactly the mana value


# ---------------------------------------------------------------------------
# Old Man of the Sea — "I didn't get a prompt asking me if I want to untap the
# card"
# ---------------------------------------------------------------------------

class TestOldManOfTheSea:
    def test_engine_reports_optional_untap_choices(self, arn_by_name):
        old_man = Permanent(card=arn_by_name["Old Man of the Sea"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[old_man])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        assert game.get_optional_untap_permanents(0) == [{"index": 0, "name": "Old Man of the Sea"}]

    def test_keep_tapped_choice_is_honored(self, arn_by_name):
        old_man = Permanent(card=arn_by_name["Old Man of the Sea"], tapped=True)
        p1 = PlayerState(name="P1", battlefield=[old_man])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.resolve_untap_step(0, keep_tapped_indices=[0])
        assert old_man.tapped is True
        game.resolve_untap_step(0, keep_tapped_indices=[])
        assert old_man.tapped is False

    def test_headless_keeps_it_tapped_while_steal_is_live(self, arn_by_name):
        old_man = _nosick(Permanent(card=arn_by_name["Old Man of the Sea"], tapped=True))
        stolen = _nosick(Permanent(card=_C["Grizzly Bears"]))
        old_man.metadata["stolen_while_tapped_and_weaker"] = True
        old_man.metadata["stolen_permanent"] = stolen
        p1 = PlayerState(name="P1", battlefield=[old_man, stolen])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.resolve_untap_step(0)
        assert old_man.tapped is True  # keeping the steal is the sensible default

    def test_web_prompt_pauses_turn_and_confirm_continues(self, arn_by_name):
        sid, session, game = _session()
        old_man = Permanent(card=arn_by_name["Old Man of the Sea"], tapped=True)
        game.players[0].battlefield.append(old_man)
        idx = game.players[0].battlefield.index(old_man)

        done = _begin_turn(session, 0, defer_untap_selection=True)
        assert done is False
        assert session.optional_untap_pending == [{"index": idx, "name": "Old Man of the Sea"}]

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert state["optional_untap"] == {"permanents": [{"index": idx, "name": "Old Man of the Sea"}]}

        # Other actions are blocked until the choice is made.
        resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
        assert resp.status_code == 400

        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "optional_untap_confirm", "creature_indices": [idx]},
        )
        assert resp.status_code == 200
        assert old_man.tapped is True
        assert session.optional_untap_pending == []


# ---------------------------------------------------------------------------
# Pyramids — "The ability is a modal activated ability, not a cast effect"
# ---------------------------------------------------------------------------

class TestPyramids:
    def test_compiles_to_two_activated_abilities_and_no_cast_modes(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Pyramids"])
        assert program.modes == ()  # NOT a cast-time modal spell
        kinds = [a.instruction.kind for a in program.activated_abilities if a.supported]
        assert kinds == ["destroy_target_permanent", "shield_target_land_from_destruction"]

    def test_casting_is_inert(self, arn_by_name):
        p1 = PlayerState(name="P1", hand=[arn_by_name["Pyramids"]], battlefield=[Permanent(card=_C["Mountain"])])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=_C["Island"])])
        game = _game(p1, p2)
        result = game.cast_from_hand(0, "Pyramids", target_player_index=1)
        assert result.supported
        game.resolve_stack()
        assert any(p.card.name == "Pyramids" for p in p1.battlefield)
        assert any(p.card.name == "Mountain" for p in p1.battlefield)
        assert any(p.card.name == "Island" for p in p2.battlefield)

    def _pyramids_game(self, arn_by_name):
        pyramids = _nosick(Permanent(card=arn_by_name["Pyramids"]))
        island = Permanent(card=_C["Island"])
        venom = Permanent(card=_C["Psychic Venom"])
        venom.metadata["attached_to"] = island
        island.metadata["attached_aura"] = venom
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
        holy = Permanent(card=_C["Holy Strength"])
        holy.metadata["attached_to"] = bear
        p1 = PlayerState(name="P1", battlefield=[pyramids, island], mana_pool={"C": 8})
        p2 = PlayerState(name="P2", battlefield=[venom, bear, holy], hand=[_C["Stone Rain"]])
        game = _game(p1, p2)
        return game, p1, p2, island, venom, holy

    def test_mode_one_targets_only_auras_on_lands(self, arn_by_name):
        game, p1, p2, island, venom, holy = self._pyramids_game(arn_by_name)
        spec = game.activation_target_spec(0, 0, ability_index=0)
        assert [t["name"] for t in spec["valid_targets"]] == ["Psychic Venom"]

    def test_mode_one_destroys_the_aura(self, arn_by_name):
        game, p1, p2, island, venom, holy = self._pyramids_game(arn_by_name)
        result = game.activate_permanent_ability(
            0, "Pyramids", target_player_index=1,
            target_permanent_index=p2.battlefield.index(venom), ability_index=0,
        )
        assert result.supported
        game.resolve_stack()
        assert venom not in p2.battlefield
        assert holy in p2.battlefield

    def test_mode_two_shields_a_land_from_destruction_once(self, arn_by_name):
        game, p1, p2, island, venom, holy = self._pyramids_game(arn_by_name)
        result = game.activate_permanent_ability(
            0, "Pyramids", target_player_index=0,
            target_permanent_index=p1.battlefield.index(island), ability_index=1,
        )
        assert result.supported
        game.resolve_stack()
        assert island.metadata.get("land_destruction_shield_this_turn") is True

        game.cast_from_hand(1, "Stone Rain", target_player_index=0,
                            target_permanent_index=p1.battlefield.index(island))
        game.resolve_stack()
        assert island in p1.battlefield  # the destruction was replaced
        assert island.metadata.get("land_destruction_shield_this_turn") is None  # one-shot

    def test_shield_also_stops_mass_land_destruction(self, arn_by_name):
        game, p1, p2, island, venom, holy = self._pyramids_game(arn_by_name)
        game.activate_permanent_ability(
            0, "Pyramids", target_player_index=0,
            target_permanent_index=p1.battlefield.index(island), ability_index=1,
        )
        game.resolve_stack()
        p2.hand.append(_C["Armageddon"])
        game.cast_from_hand(1, "Armageddon", target_player_index=0)
        game.resolve_stack()
        assert island in p1.battlefield  # shielded
        assert not any(p.card.primary_type == "land" for p in p2.battlefield)


# ---------------------------------------------------------------------------
# Sandals of Abdallah — "I get an error saying ability not implemented"
# ---------------------------------------------------------------------------

class TestSandalsOfAbdallah:
    def _sandals_game(self, arn_by_name):
        sandals = _nosick(Permanent(card=arn_by_name["Sandals of Abdallah"]))
        bear = _nosick(Permanent(card=_C["Grizzly Bears"]))
        p1 = PlayerState(name="P1", battlefield=[sandals, bear], mana_pool={"C": 4})
        p2 = PlayerState(name="P2", hand=[_C["Lightning Bolt"]])
        game = _game(p1, p2)
        return game, p1, p2, sandals, bear

    def test_grants_islandwalk_until_end_of_turn(self, arn_by_name):
        game, p1, p2, sandals, bear = self._sandals_game(arn_by_name)
        result = game.activate_permanent_ability(
            0, "Sandals of Abdallah", target_player_index=0, target_permanent_index=1
        )
        assert result.supported
        game.resolve_stack()
        assert game._has_keyword(bear, "islandwalk")
        assert sandals.tapped is True
        # ... and it expires at cleanup.
        game.resolve_cleanup_step(0)
        assert not game._has_keyword(bear, "islandwalk")

    def test_sandals_destroyed_when_the_creature_dies(self, arn_by_name):
        game, p1, p2, sandals, bear = self._sandals_game(arn_by_name)
        game.activate_permanent_ability(
            0, "Sandals of Abdallah", target_player_index=0, target_permanent_index=1
        )
        game.resolve_stack()
        game.cast_from_hand(1, "Lightning Bolt", target_player_index=0,
                            target_permanent_index=p1.battlefield.index(bear))
        game.resolve_stack()
        assert bear not in p1.battlefield
        assert sandals not in p1.battlefield
        assert any(c.name == "Sandals of Abdallah" for c in p1.graveyard)

    def test_sandals_survives_if_the_creature_survives_the_turn(self, arn_by_name):
        game, p1, p2, sandals, bear = self._sandals_game(arn_by_name)
        game.activate_permanent_ability(
            0, "Sandals of Abdallah", target_player_index=0, target_permanent_index=1
        )
        game.resolve_stack()
        game.resolve_cleanup_step(0)
        # The link expired with the turn: a later death no longer takes Sandals.
        game.cast_from_hand(1, "Lightning Bolt", target_player_index=0,
                            target_permanent_index=p1.battlefield.index(bear))
        game.resolve_stack()
        assert bear not in p1.battlefield
        assert sandals in p1.battlefield


# ---------------------------------------------------------------------------
# Sindbad — "I drew a non-land card but it wasn't discarded"
# ---------------------------------------------------------------------------

class TestSindbad:
    def _sindbad_game(self, arn_by_name, library):
        sindbad = _nosick(Permanent(card=arn_by_name["Sindbad"]))
        p1 = PlayerState(name="P1", battlefield=[sindbad], library=list(library))
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        return game, p1, sindbad

    def test_non_land_is_revealed_and_discarded(self, arn_by_name):
        game, p1, sindbad = self._sindbad_game(arn_by_name, [_C["Lightning Bolt"]])
        result = game.activate_permanent_ability(0, "Sindbad", target_player_index=1)
        assert result.supported
        game.resolve_stack()
        assert p1.hand == []
        assert any(c.name == "Lightning Bolt" for c in p1.graveyard)
        assert any("drew and revealed Lightning Bolt" in line for line in game.log)

    def test_land_stays_in_hand(self, arn_by_name):
        game, p1, sindbad = self._sindbad_game(arn_by_name, [_C["Forest"]])
        game.activate_permanent_ability(0, "Sindbad", target_player_index=1)
        game.resolve_stack()
        assert [c.name for c in p1.hand] == ["Forest"]
        assert p1.graveyard == []
