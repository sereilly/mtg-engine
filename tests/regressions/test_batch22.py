"""Regression tests for the twenty-second batch of bugs reported in-game
(CARD_VERIFICATION.md failures) — the eleven remaining Arabian Nights failures.

Clusters covered in this batch:
- Abu Ja'far: its "when this creature dies, destroy all creatures blocking or
  blocked by it" trigger never fired at all (and had compiled to the *global*
  destroy_all_creatures sweep). It now fires as a real trigger and destroys only
  the creatures it was in combat with, captured at death (CR 603.10).
- Bottle of Suleiman: the coin flip was missing entirely — the card always dealt
  5 damage, and to the wrong player. It now flips, creating a 5/5 flying Djinn
  token on a win and dealing 5 to its *own controller* on a loss. Its
  "Sacrifice this artifact" cost is also paid on activation now.
- Camel: the band shield resolved the damaged creature's battlefield index with
  list.index, which compares Permanents field-by-field — with a second,
  identically-stated attacker in play it found the wrong index and lost the
  shield on the creature that really was in the band.
- Diamond Valley: "you gain life equal to the sacrificed creature's toughness"
  read the printed toughness, so an untapped Giant Tortoise (+0/+3 while
  untapped) was worth 1 life instead of 4.
- Erhnam Djinn: the targeted upkeep trigger is answered by clicking a
  highlighted creature on the board, and is skipped entirely when the opponent
  controls no legal (non-Wall) creature.
- Eye for an Eye: combat damage to a player applies life loss directly rather
  than through _deal_damage_to_player, so the mirror never fired on an attack —
  exactly the case the card is for.
- Guardian Beast: the artifact's controller was resolved with `in`, so an
  opponent's identically-stated copy of the same artifact was protected too.
- Jeweled Bird: there was no ante zone — the ability just drew a card and left
  the Bird on the battlefield. The ante zone (CR 407) is now real, and the Bird
  antes itself.
- Old Man of the Sea: nothing checked state-based actions after the untap step,
  so untapping it left the stolen creature under the thief's control.
- Ring of Ma'rûf: the replaced draw offers the sideboard picker; a random-deck
  game has no cards outside the game at all, so the debug menu can now put some
  there and the zone is visible on the board.
- Serendib Djinn: "sacrifice a land" always took the first land; the controller
  now picks which one (CR 701.17a).
"""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from engine import PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier
from tests.helpers import CARDS_BY_NAME as _C
from tests.helpers import _game, _mk_creature_card, _nosick
from web.app import app, store, _end_turn

client = TestClient(app)


def _combat_game(attacker_board, defender_board, *, bands=None, blocks=None):
    """A two-player game parked at the combat damage step: seat 0 attacks seat 1
    with every creature it controls."""
    p1 = PlayerState(name="P1", battlefield=[_nosick(p) for p in attacker_board])
    p2 = PlayerState(name="P2", battlefield=[_nosick(p) for p in defender_board])
    game = _game(p1, p2)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.declare_attackers(0, list(range(len(attacker_board))), 1, bands=bands)
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(1, blocks or {})
    return game, p1, p2


# ---------------------------------------------------------------------------
# Abu Ja'far — "I blocked a creature and the blocking creature didn't die"
# ---------------------------------------------------------------------------


class TestAbuJafar:
    def test_compiles_to_the_combat_only_sweep_not_a_board_wipe(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Abu Ja'far"])
        (trigger,) = program.triggered_abilities
        assert trigger.condition.kind == "dies"
        assert trigger.instruction.kind == "destroy_creatures_in_combat_with_source"
        assert trigger.instruction.payload["bypass_regeneration"] is True

    def _blocking_game(self, arn_by_name, attacker_power=2):
        attacker = Permanent(card=_mk_creature_card("Bear", attacker_power, 2))
        onlooker = Permanent(card=_mk_creature_card("Onlooker", 3, 3))
        abu = Permanent(card=arn_by_name["Abu Ja'far"])
        bystander = Permanent(card=_mk_creature_card("Bystander", 3, 3))
        game, p1, p2 = _combat_game(
            [attacker, onlooker], [abu, bystander], blocks={0: [0]}
        )
        return game, p1, p2, attacker, onlooker, abu, bystander

    def test_the_creature_it_blocked_dies_with_it(self, arn_by_name):
        game, p1, p2, attacker, onlooker, abu, bystander = self._blocking_game(arn_by_name)
        game._set_phase_and_step("combat", "combat_damage")
        assert game.resolve_combat_damage(0)[0]
        game._settle()
        assert [p.card.name for p in p1.battlefield] == ["Onlooker"]
        assert any(c.name == "Bear" for c in p1.graveyard)

    def test_uninvolved_creatures_survive(self, arn_by_name):
        """The old compile was a board wipe — every other creature must live."""
        game, p1, p2, attacker, onlooker, abu, bystander = self._blocking_game(arn_by_name)
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        game._settle()
        assert any(p is onlooker for p in p1.battlefield)
        assert any(p is bystander for p in p2.battlefield)

    def test_the_creature_blocking_it_dies_when_abu_attacks(self, arn_by_name):
        """The other half of "blocking or blocked by": Abu Ja'far as the attacker."""
        abu = Permanent(card=arn_by_name["Abu Ja'far"])
        blocker = Permanent(card=_mk_creature_card("Wall", 2, 2))
        game, p1, p2 = _combat_game([abu], [blocker], blocks={0: [0]})
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        game._settle()
        assert p2.battlefield == []
        assert any(c.name == "Wall" for c in p2.graveyard)

    def test_the_victim_cannot_regenerate(self, arn_by_name):
        game, p1, p2, attacker, onlooker, abu, bystander = self._blocking_game(arn_by_name)
        attacker.regeneration_shield = 1
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        game._settle()
        assert any(c.name == "Bear" for c in p1.graveyard), "the shield must not save it"

    def test_dying_outside_combat_destroys_nothing(self, arn_by_name):
        abu = _nosick(Permanent(card=arn_by_name["Abu Ja'far"]))
        bystander = _nosick(Permanent(card=_mk_creature_card("Bystander", 3, 3)))
        p1 = PlayerState(name="P1", battlefield=[abu, bystander])
        p2 = PlayerState(name="P2", battlefield=[_nosick(Permanent(card=_C["Grizzly Bears"]))])
        game = _game(p1, p2)
        p1.battlefield = [bystander]
        game._permanent_to_graveyard(p1, abu)
        game._settle()
        assert any(p is bystander for p in p1.battlefield)
        assert len(p2.battlefield) == 1


# ---------------------------------------------------------------------------
# Bottle of Suleiman — "I won the coin flip but instead of creating a creature
# it did 5 damage to my opponent"
# ---------------------------------------------------------------------------


class TestBottleOfSuleiman:
    def test_compiles_to_the_coin_flip_not_a_bare_damage_effect(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Bottle of Suleiman"])
        (ability,) = program.activated_abilities
        assert ability.instruction.kind == "coin_flip_token_or_self_damage"
        payload = ability.instruction.payload
        assert (payload["power"], payload["toughness"]) == (5, 5)
        assert payload["keywords"] == ("Flying",)
        assert payload["damage"] == 5
        assert ability.cost.sacrifice_self is True

    def _bottle_game(self, arn_by_name):
        bottle = _nosick(Permanent(card=arn_by_name["Bottle of Suleiman"]))
        p1 = PlayerState(name="P1", battlefield=[bottle])
        p2 = PlayerState(name="P2")
        return _game(p1, p2), p1, p2

    def _activate(self, game, win: bool):
        """Activate the Bottle with the coin flip forced to *win*."""
        real_random = random.random
        random.random = lambda: 0.0 if win else 0.99
        try:
            result = game.queue_permanent_ability(0, "Bottle of Suleiman", permanent_index=0)
            assert result.supported, result.details
            while game.stack:
                game.resolve_top_of_stack()
        finally:
            random.random = real_random

    def test_winning_the_flip_creates_the_djinn_token(self, arn_by_name):
        game, p1, p2 = self._bottle_game(arn_by_name)
        self._activate(game, win=True)
        (token,) = [p for p in p1.battlefield if p.metadata.get("is_token")]
        assert token.card.name == "Djinn"
        assert (token.effective_power, token.effective_toughness) == (5, 5)
        assert "Flying" in token.card.keywords
        assert "Artifact Creature" in token.card.type_line

    def test_winning_the_flip_deals_no_damage_to_anyone(self, arn_by_name):
        game, p1, p2 = self._bottle_game(arn_by_name)
        self._activate(game, win=True)
        assert (p1.life, p2.life) == (20, 20)

    def test_losing_the_flip_damages_its_own_controller(self, arn_by_name):
        """"this artifact deals 5 damage to you" — you, not the opponent."""
        game, p1, p2 = self._bottle_game(arn_by_name)
        self._activate(game, win=False)
        assert p1.life == 15
        assert p2.life == 20
        assert not any(p.metadata.get("is_token") for p in p1.battlefield)

    def test_activating_sacrifices_the_bottle(self, arn_by_name):
        game, p1, p2 = self._bottle_game(arn_by_name)
        self._activate(game, win=True)
        assert not any(p.card.name == "Bottle of Suleiman" for p in p1.battlefield)
        assert any(c.name == "Bottle of Suleiman" for c in p1.graveyard)

    def test_black_lotus_still_sacrifices_exactly_once(self):
        """The shared sacrifice_self cost path must not double-move the card."""
        lotus = _nosick(Permanent(card=_C["Black Lotus"]))
        p1 = PlayerState(name="P1", battlefield=[lotus])
        game = _game(p1, PlayerState(name="P2"))
        game.activate_permanent_ability(0, "Black Lotus", permanent_index=0, mana_color="R")
        assert p1.battlefield == []
        assert [c.name for c in p1.graveyard] == ["Black Lotus"]
        assert p1.mana_pool["R"] == 3


# ---------------------------------------------------------------------------
# Camel — "I attacked in a band with camel and then targeted the banded creature
# with a desert on the end combat step and it took damage"
# ---------------------------------------------------------------------------


class TestCamelBandShieldIdentity:
    """CR 511.3 keeps creatures attacking through the end of combat step and
    CR 702.22e keeps the band alive, so the shield still applies. It was lost
    because the band-mate's battlefield index was resolved by value: a second
    attacker with identical stats matched first."""

    def _game_with_an_identical_attacker(self, arn_by_name):
        loner = Permanent(card=_mk_creature_card("Bear", 2, 2))
        camel = Permanent(card=arn_by_name["Camel"])
        mate = Permanent(card=_mk_creature_card("Bear", 2, 2))
        desert = Permanent(card=arn_by_name["Desert"])
        game, p1, p2 = _combat_game([loner, camel, mate], [desert], bands=[[1, 2]])
        game._set_phase_and_step("combat", "end_of_combat")
        return game, p1, p2, loner, camel, mate, desert

    def test_the_band_mate_keeps_its_shield(self, arn_by_name):
        game, p1, p2, loner, camel, mate, desert = self._game_with_an_identical_attacker(
            arn_by_name
        )
        assert loner == mate, "the two attackers really are field-for-field equal"
        assert loner is not mate
        game.activate_permanent_ability(
            1, "Desert", target_player_index=0, target_permanent_index=2, ability_index=1
        )
        assert mate.damage_marked == 0

    def test_the_identical_creature_outside_the_band_is_still_hit(self, arn_by_name):
        game, p1, p2, loner, camel, mate, desert = self._game_with_an_identical_attacker(
            arn_by_name
        )
        game.activate_permanent_ability(
            1, "Desert", target_player_index=0, target_permanent_index=0, ability_index=1
        )
        assert loner.damage_marked == 1


# ---------------------------------------------------------------------------
# Diamond Valley — "I sacrificed a giant tortoise, which should have healed me
# for 4 instead of 1 because it was untapped and had a toughness bonus"
# ---------------------------------------------------------------------------


class TestDiamondValley:
    def _valley_game(self, arn_by_name, victim: Permanent):
        valley = _nosick(Permanent(card=arn_by_name["Diamond Valley"]))
        p1 = PlayerState(name="P1", battlefield=[valley, _nosick(victim)])
        game = _game(p1, PlayerState(name="P2"))
        game._refresh_dynamic_creatures()
        result = game.queue_permanent_ability(
            0, "Diamond Valley", permanent_index=0, target_permanent_index=1
        )
        assert result.supported, result.details
        while game.stack:
            game.resolve_top_of_stack()
        return p1

    def test_gains_the_untapped_tortoises_boosted_toughness(self, arn_by_name):
        """Giant Tortoise is a printed 1/1 that "gets +0/+3 as long as it's
        untapped" — sacrificed untapped it is worth 4 (CR 608.2h)."""
        p1 = self._valley_game(arn_by_name, Permanent(card=arn_by_name["Giant Tortoise"]))
        assert p1.life == 24

    def test_a_tapped_tortoise_is_worth_its_printed_toughness(self, arn_by_name):
        p1 = self._valley_game(
            arn_by_name, Permanent(card=arn_by_name["Giant Tortoise"], tapped=True)
        )
        assert p1.life == 21

    def test_a_pt_modifier_counts_too(self, arn_by_name):
        bears = Permanent(card=_C["Grizzly Bears"])  # 2/2
        add_pt_modifier(bears, 0, 2)  # e.g. Holy Armor's +0/+2
        p1 = self._valley_game(arn_by_name, bears)
        assert p1.life == 24

    def test_the_creature_actually_goes_to_the_graveyard(self, arn_by_name):
        p1 = self._valley_game(arn_by_name, Permanent(card=arn_by_name["Giant Tortoise"]))
        assert [p.card.name for p in p1.battlefield] == ["Diamond Valley"]
        assert any(c.name == "Giant Tortoise" for c in p1.graveyard)


# ---------------------------------------------------------------------------
# Erhnam Djinn — "The creature targeting prompt should highlight all valid
# targets and let me choose one by clicking. If there are no valid targets, the
# prompt should be skipped entirely."
# ---------------------------------------------------------------------------


def _new_session(seat0_board, seat1_board, seed=22001, *, hold_upkeep=False):
    """A human-vs-human session with both battlefields set, before any turn has
    been advanced. ``hold_upkeep`` mirrors the phase-rail upkeep stop, which
    opens the CR 503.1 priority window (so the seat can activate an ability at
    its own upkeep) instead of resolving the upkeep straight through."""
    sid = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": seed},
    ).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    if hold_upkeep:
        session.self_stop_steps = {"upkeep"}
    game.players[0].battlefield = [_nosick(p) for p in seat0_board]
    game.players[1].battlefield = [_nosick(p) for p in seat1_board]
    game.players[0].hand = []
    game.players[1].hand = []
    return sid, session, game


def _upkeep_session(seat0_board, seat1_board, seed=22001, *, hold_upkeep=False):
    """A human-vs-human session parked on seat 0's own upkeep."""
    sid, session, game = _new_session(seat0_board, seat1_board, seed, hold_upkeep=hold_upkeep)
    for _ in range(4):
        if session.current_turn == 0 and game.current_step == "upkeep":
            break
        _end_turn(session, allow_manual_cleanup_selection=False)
    return sid, session, game


def _pending_trigger(sid, seat=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    pending = (state.get("optional_trigger") or {}).get("pending") or []
    return pending[0] if pending else None


class TestErhnamDjinnTargetPrompt:
    def test_the_prompt_carries_clickable_board_targets(self, arn_by_name):
        sid, session, game = _upkeep_session(
            [Permanent(card=arn_by_name["Erhnam Djinn"])],
            [Permanent(card=_C["Grizzly Bears"]), Permanent(card=_C["Wall of Stone"])],
        )
        current = _pending_trigger(sid)
        assert current is not None
        assert current["mandatory"] is True
        assert current["needs_target"] == "creature"
        assert current["valid_targets"] == [
            {"kind": "permanent", "seat": 1, "index": 0, "name": "Grizzly Bears"}
        ], "the Wall is not a legal target and must not be offered"

    def test_clicking_a_target_grants_forestwalk(self, arn_by_name):
        sid, session, game = _upkeep_session(
            [Permanent(card=arn_by_name["Erhnam Djinn"])],
            [Permanent(card=_C["Grizzly Bears"])],
        )
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={
                "seat": 0,
                "action": "resolve_optional_trigger",
                "card_name": "Erhnam Djinn",
                "accept": True,
                "target_seat": 1,
                "target_permanent_index": 0,
            },
        )
        assert resp.status_code == 200, resp.text
        assert game.players[1].battlefield[0].metadata.get("has_forestwalk") is True

    def test_no_legal_target_skips_the_prompt_entirely(self, arn_by_name):
        sid, session, game = _upkeep_session(
            [Permanent(card=arn_by_name["Erhnam Djinn"])],
            [Permanent(card=_C["Wall of Stone"])],
        )
        assert _pending_trigger(sid) is None
        assert game.current_step != "upkeep", "the upkeep must not stall on a dead trigger"

    def test_an_empty_opponent_board_skips_the_prompt(self, arn_by_name):
        sid, session, game = _upkeep_session([Permanent(card=arn_by_name["Erhnam Djinn"])], [])
        assert _pending_trigger(sid) is None


# ---------------------------------------------------------------------------
# Eye for an Eye — "I used this card on an attacking creature. Its controller
# should have taken damage when I took damage from the attack."
# ---------------------------------------------------------------------------


class TestEyeForAnEye:
    def _attack_game(self, arn_by_name, attacker_power=3):
        attacker = Permanent(card=_mk_creature_card("Bear", attacker_power, 3))
        p1 = PlayerState(name="Attacker", battlefield=[_nosick(attacker)])
        p2 = PlayerState(name="Defender", hand=[arn_by_name["Eye for an Eye"]])
        game = _game(p1, p2)
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game.declare_attackers(0, [0], 1)
        return game, p1, p2, attacker

    def test_combat_damage_is_mirrored_to_the_attackers_controller(self, arn_by_name):
        game, p1, p2, attacker = self._attack_game(arn_by_name)
        result = game.cast_from_hand(
            1, "Eye for an Eye", target_player_index=0, target_permanent_index=0
        )
        assert result.supported, result.details
        while game.stack:
            game.resolve_top_of_stack()
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        assert p2.life == 17, "the defender still takes the combat damage"
        assert p1.life == 17, "and the attacker's controller takes the same amount"

    def test_the_charge_is_spent_after_one_damage_event(self, arn_by_name):
        game, p1, p2, attacker = self._attack_game(arn_by_name)
        game.cast_from_hand(1, "Eye for an Eye", target_player_index=0, target_permanent_index=0)
        while game.stack:
            game.resolve_top_of_stack()
        game._set_phase_and_step("combat", "combat_damage")
        game.resolve_combat_damage(0)
        assert p2.mirror_damage_sources == []
        game._deal_damage_to_player(p2, 2, source=attacker)
        assert p2.life == 15
        assert p1.life == 17, "no second mirror"

    def test_damage_from_an_unchosen_source_is_not_mirrored(self, arn_by_name):
        game, p1, p2, attacker = self._attack_game(arn_by_name)
        other = _nosick(Permanent(card=_C["Grizzly Bears"]))
        p1.battlefield.append(other)
        game.cast_from_hand(1, "Eye for an Eye", target_player_index=0, target_permanent_index=0)
        while game.stack:
            game.resolve_top_of_stack()
        game._deal_damage_to_player(p2, 2, source=other)
        assert p2.life == 18
        assert p1.life == 20


# ---------------------------------------------------------------------------
# Guardian Beast — "This card should only affect artifacts I control"
# ---------------------------------------------------------------------------


class TestGuardianBeast:
    def _beast_game(self, arn_by_name, *, tapped=False):
        beast = _nosick(Permanent(card=arn_by_name["Guardian Beast"], tapped=tapped))
        mine = Permanent(card=_C["Mox Jet"])
        theirs = Permanent(card=_C["Mox Jet"])  # field-for-field identical
        p1 = PlayerState(name="P1", battlefield=[beast, mine])
        p2 = PlayerState(name="P2", battlefield=[theirs])
        return _game(p1, p2), mine, theirs

    def test_it_protects_its_controllers_artifact(self, arn_by_name):
        game, mine, theirs = self._beast_game(arn_by_name)
        assert game._is_indestructible(mine) is True
        assert game._cant_be_enchanted(mine) is True

    def test_an_identical_artifact_across_the_table_is_untouched(self, arn_by_name):
        game, mine, theirs = self._beast_game(arn_by_name)
        assert mine == theirs, "the two Moxen really are field-for-field equal"
        assert game._is_indestructible(theirs) is False
        assert game._cant_be_enchanted(theirs) is False

    def test_the_opponents_artifact_can_still_be_destroyed(self, arn_by_name):
        game, mine, theirs = self._beast_game(arn_by_name)
        p2 = game.players[1]
        game._destroy_swept_permanents(p2, lambda p: p.has_type("artifact"))
        assert p2.battlefield == []
        assert any(c.name == "Mox Jet" for c in p2.graveyard)
        assert any(p is mine for p in game.players[0].battlefield)

    def test_tapping_the_beast_drops_the_protection(self, arn_by_name):
        game, mine, theirs = self._beast_game(arn_by_name, tapped=True)
        assert game._is_indestructible(mine) is False


# ---------------------------------------------------------------------------
# Jeweled Bird — "This card should move into the ante zone when its ability
# is used"
# ---------------------------------------------------------------------------


class TestJeweledBird:
    def _bird_game(self, arn_by_name, ante=(), library=()):
        bird = _nosick(Permanent(card=arn_by_name["Jeweled Bird"]))
        p1 = PlayerState(
            name="P1",
            battlefield=[bird],
            ante=[_C[n] for n in ante],
            library=[_C[n] for n in library],
        )
        game = _game(p1, PlayerState(name="P2"))
        result = game.queue_permanent_ability(0, "Jeweled Bird", permanent_index=0)
        assert result.supported, result.details
        while game.stack:
            game.resolve_top_of_stack()
        return p1, bird

    def test_the_bird_moves_from_the_battlefield_into_the_ante(self, arn_by_name):
        p1, bird = self._bird_game(arn_by_name, library=["Island"])
        assert p1.battlefield == []
        assert [c.name for c in p1.ante] == ["Jeweled Bird"]
        assert not any(c.name == "Jeweled Bird" for c in p1.graveyard)

    def test_other_owned_ante_cards_go_to_the_graveyard(self, arn_by_name):
        p1, bird = self._bird_game(
            arn_by_name, ante=["Black Lotus", "Time Walk"], library=["Island"]
        )
        assert [c.name for c in p1.ante] == ["Jeweled Bird"]
        assert {c.name for c in p1.graveyard} == {"Black Lotus", "Time Walk"}

    def test_it_then_draws_a_card(self, arn_by_name):
        p1, bird = self._bird_game(arn_by_name, library=["Island", "Forest"])
        assert [c.name for c in p1.hand] == ["Island"]

    def test_contract_from_below_antes_into_the_ante_zone(self, all_cards):
        """The zone has to be real for the Bird's second clause to find anything."""
        p1 = PlayerState(
            name="P1",
            hand=[_C["Contract from Below"]],
            library=[_C["Black Lotus"]] + [_C["Island"]] * 7,
        )
        game = _game(p1, PlayerState(name="P2"))
        assert game.cast_from_hand(0, "Contract from Below").supported
        assert [c.name for c in p1.ante] == ["Black Lotus"]
        assert len(p1.hand) == 7

    def test_demonic_attorney_antes_for_every_player(self, all_cards):
        p1 = PlayerState(name="P1", hand=[_C["Demonic Attorney"]], library=[_C["Island"]])
        p2 = PlayerState(name="P2", library=[_C["Forest"]])
        game = _game(p1, p2)
        assert game.cast_from_hand(0, "Demonic Attorney").supported
        assert [c.name for c in p1.ante] == ["Island"]
        assert [c.name for c in p2.ante] == ["Forest"]

    def test_the_ante_zone_reaches_the_client(self, arn_by_name):
        sid = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
                  "guest_colors": 2, "seed": 22002},
        ).json()["session_id"]
        session = store.get(sid)
        session.game.players[0].ante = [_C["Black Lotus"]]
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert [c["name"] for c in state["players"][0]["ante"]] == ["Black Lotus"]
        assert state["players"][1]["ante"] == []


# ---------------------------------------------------------------------------
# Old Man of the Sea — "Untapping this card should give control of the
# controlled creature back to its owner"
# ---------------------------------------------------------------------------


class TestOldManOfTheSea:
    def _steal_game(self, arn_by_name):
        old_man = _nosick(Permanent(card=arn_by_name["Old Man of the Sea"]))
        victim = _nosick(Permanent(card=_mk_creature_card("Bear", 1, 1)))
        p1 = PlayerState(name="P1", battlefield=[old_man])
        p2 = PlayerState(name="P2", battlefield=[victim])
        game = _game(p1, p2)
        result = game.queue_permanent_ability(
            0, "Old Man of the Sea", permanent_index=0,
            target_player_index=1, target_permanent_index=0,
        )
        assert result.supported, result.details
        while game.stack:
            game.resolve_top_of_stack()
        assert any(p is victim for p in p1.battlefield), "the steal itself must work"
        assert old_man.tapped is True
        return game, p1, p2, old_man, victim

    def test_the_untap_step_hands_the_creature_back(self, arn_by_name):
        game, p1, p2, old_man, victim = self._steal_game(arn_by_name)
        game.active_player_index = 0
        game.resolve_untap_step(0, keep_tapped_indices=[])
        assert old_man.tapped is False
        assert any(p is victim for p in p2.battlefield)
        assert not any(p is victim for p in p1.battlefield)

    def test_choosing_to_stay_tapped_keeps_the_creature(self, arn_by_name):
        game, p1, p2, old_man, victim = self._steal_game(arn_by_name)
        game.active_player_index = 0
        game.resolve_untap_step(0, keep_tapped_indices=[0])
        assert old_man.tapped is True
        assert any(p is victim for p in p1.battlefield)

    def test_an_identical_creature_on_the_owners_side_is_not_taken_instead(self, arn_by_name):
        """The revert used `in`/`remove`, which match a Permanent by value."""
        game, p1, p2, old_man, victim = self._steal_game(arn_by_name)
        decoy = _nosick(Permanent(card=_mk_creature_card("Bear", 1, 1)))
        p2.battlefield.append(decoy)
        game.active_player_index = 0
        game.resolve_untap_step(0, keep_tapped_indices=[])
        assert [p is victim or p is decoy for p in p2.battlefield] == [True, True]
        assert len(p2.battlefield) == 2

    def test_untapping_through_the_web_untap_prompt_hands_it_back(self, arn_by_name):
        old_man = Permanent(card=arn_by_name["Old Man of the Sea"])
        victim = Permanent(card=_mk_creature_card("Bear", 1, 1))
        sid, session, game = _new_session([old_man], [victim], seed=22003)
        p0, p1 = game.players
        game.queue_permanent_ability(
            0, "Old Man of the Sea", permanent_index=0,
            target_player_index=1, target_permanent_index=0,
        )
        while game.stack:
            game.resolve_top_of_stack()
        assert any(p is victim for p in p0.battlefield)

        # Advance to seat 0's own untap step, where the "you may choose not to
        # untap" prompt is raised.
        for _ in range(4):
            if session.optional_untap_pending:
                break
            _end_turn(session, allow_manual_cleanup_selection=False)
        assert session.optional_untap_pending
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "optional_untap_confirm", "creature_indices": []},
        )
        assert resp.status_code == 200, resp.text
        assert old_man.tapped is False
        assert any(p is victim for p in p1.battlefield)


# ---------------------------------------------------------------------------
# Ring of Ma'rûf — "This ability should replace my next draw with a window that
# shows my sideboard and lets me choose a card from it."
# ---------------------------------------------------------------------------


class TestRingOfMaruf:
    def _armed_session(self, arn_by_name, sideboard=("Black Lotus", "Time Walk")):
        # The replacement lasts only "this turn", so it must be activated during
        # the upkeep priority window — before the draw step it replaces.
        sid, session, game = _upkeep_session(
            [Permanent(card=arn_by_name["Ring of Ma'rûf"])], [], seed=22004, hold_upkeep=True
        )
        p0 = game.players[0]
        p0.sideboard = [_C[n] for n in sideboard]
        p0.library = [_C["Plains"]] * 10
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "activate",
                  "permanent_name": "Ring of Ma'rûf", "permanent_index": 0},
        )
        assert resp.status_code == 200, resp.text
        while game.stack:
            game.resolve_top_of_stack()
        return sid, session, game, p0

    def test_activating_arms_the_replacement_and_exiles_the_ring(self, arn_by_name):
        sid, session, game, p0 = self._armed_session(arn_by_name)
        assert 0 in game.outside_game_draw_replacements
        assert p0.battlefield == []
        assert [c.name for c in p0.exile] == ["Ring of Ma'rûf"]

    def test_the_draw_step_opens_the_sideboard_picker(self, arn_by_name):
        sid, session, game, p0 = self._armed_session(arn_by_name)
        resp = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
        assert resp.status_code == 200, resp.text
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        info = state["outside_game_draw"]
        assert info["card_names"] == ["Black Lotus", "Time Walk"]
        assert [c["name"] for c in info["cards"]] == ["Black Lotus", "Time Walk"]
        assert p0.hand == [], "nothing is drawn until the choice is made"

    def test_the_picker_is_private_to_its_owner(self, arn_by_name):
        sid, session, game, p0 = self._armed_session(arn_by_name)
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        assert state["outside_game_draw"] is None

    def test_choosing_a_card_puts_it_in_hand(self, arn_by_name):
        sid, session, game, p0 = self._armed_session(arn_by_name)
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "outside_game_draw_confirm", "hand_index": 1},
        )
        assert resp.status_code == 200, resp.text
        assert [c.name for c in p0.hand] == ["Time Walk"]
        assert [c.name for c in p0.sideboard] == ["Black Lotus"]

    def test_the_debug_menu_can_stock_the_cards_outside_the_game(self):
        """A random-deck game starts with an empty sideboard, so nothing could
        ever be offered — this is how a test game gets something to pick."""
        sid = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
                  "guest_colors": 2, "seed": 22005},
        ).json()["session_id"]
        session = store.get(sid)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "debug_add_to_sideboard", "card_name": "Black Lotus"},
        )
        assert resp.status_code == 200, resp.text
        assert [c.name for c in session.game.players[0].sideboard] == ["Black Lotus"]
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert [c["name"] for c in state["players"][0]["sideboard"]] == ["Black Lotus"]


# ---------------------------------------------------------------------------
# Serendib Djinn — "I didn't get to choose which land to sacrifice"
# ---------------------------------------------------------------------------


class TestSerendibDjinn:
    def _djinn_session(self, arn_by_name, lands=("Forest", "Island", "Mountain")):
        return _upkeep_session(
            [Permanent(card=arn_by_name["Serendib Djinn"])]
            + [Permanent(card=_C[n]) for n in lands],
            [],
            seed=22006,
        )

    def test_the_prompt_offers_every_land_the_player_controls(self, arn_by_name):
        sid, session, game = self._djinn_session(arn_by_name)
        current = _pending_trigger(sid)
        assert current is not None
        assert current["mandatory"] is True
        assert current["needs_target"] == "land"
        assert [t["name"] for t in current["valid_targets"]] == ["Forest", "Island", "Mountain"]
        assert [t["index"] for t in current["valid_targets"]] == [1, 2, 3]

    def test_the_chosen_land_is_the_one_sacrificed(self, arn_by_name):
        sid, session, game = self._djinn_session(arn_by_name)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "resolve_optional_trigger",
                  "card_name": "Serendib Djinn", "accept": True,
                  "target_seat": 0, "target_permanent_index": 3},
        )
        assert resp.status_code == 200, resp.text
        p0 = game.players[0]
        assert [p.card.name for p in p0.battlefield] == ["Serendib Djinn", "Forest", "Island"]
        assert [c.name for c in p0.graveyard] == ["Mountain"]
        assert p0.life == 20, "a Mountain is not an Island — no damage"

    def test_choosing_an_island_still_deals_the_three_damage(self, arn_by_name):
        sid, session, game = self._djinn_session(arn_by_name)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "resolve_optional_trigger",
                  "card_name": "Serendib Djinn", "accept": True,
                  "target_seat": 0, "target_permanent_index": 2},
        )
        assert resp.status_code == 200, resp.text
        p0 = game.players[0]
        assert [c.name for c in p0.graveyard] == ["Island"]
        assert p0.life == 17

    def test_headless_play_still_sacrifices_the_first_land(self, arn_by_name):
        """No prompt channel (AI / scripted play) keeps the old deterministic
        fallback rather than stalling the upkeep."""
        djinn = _nosick(Permanent(card=arn_by_name["Serendib Djinn"]))
        p1 = PlayerState(
            name="P1",
            battlefield=[djinn, Permanent(card=_C["Forest"]), Permanent(card=_C["Island"])],
        )
        game = _game(p1, PlayerState(name="P2"))
        game.resolve_upkeep(0)
        assert [c.name for c in p1.graveyard] == ["Forest"]

    def test_no_land_means_no_prompt(self, arn_by_name):
        sid, session, game = _upkeep_session(
            [Permanent(card=arn_by_name["Serendib Djinn"])], [], seed=22007
        )
        assert _pending_trigger(sid) is None
