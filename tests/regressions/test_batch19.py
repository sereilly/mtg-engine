"""Regression tests for the nineteenth batch of bugs reported in-game
(CARD_VERIFICATION.md failures).

Clusters covered in this batch:
- Aladdin's Lamp: the replaced draw's revealed cards are sent to the client as
  serialized cards (art + hover preview), not just names, so the picker can be a
  visual card grid instead of a list of text buttons.
- Erhnam Djinn: "target non-Wall creature an opponent controls" is CHOSEN by the
  controller — a mandatory targeted upkeep trigger surfaced through the upkeep
  decision channel — rather than auto-picking the first legal creature.
- Eye for an Eye: the caster picks "a source of your choice", and only damage
  from that source mirrors back to its controller (matched by identity, like
  Reverse Damage's shield).
- Guardian Beast: the indestructible (and can't-be-enchanted) it grants
  continuously to noncreature artifacts reaches the client, which previously
  read the raw metadata flag the grant never writes. Indestructible also shows
  in the keyword strip, including on noncreature permanents.
- Jandor's Ring: "Discard the last card you drew this turn" is a real additional
  cost — unpayable (so unactivatable) with no such card in hand, and it discards
  that card on activation.
- King Suleiman: "Destroy target Djinn or Efreet" prompts for a target (fixed in
  d4ad920; pinned here so the subtype-derived prompt can't regress).
- Ring of Ma'rûf: sideboards ("outside the game", CR 100.4) exist end to end —
  deck store, import, session build — and the Ring's replaced draw takes a card
  from the sideboard instead of drawing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine import PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store
from web.deck_store import parse_decklist_text
from tests.helpers import _game, _nosick
from tests.helpers import CARDS_BY_NAME as _C

client = TestClient(app)


def _ring_of_maruf(arn_by_name):
    """Ring of Ma'rûf by prefix — its name carries a circumflex."""
    return next(card for name, card in arn_by_name.items() if name.startswith("Ring of Ma"))


# ---------------------------------------------------------------------------
# Erhnam Djinn — "I didn't get to choose a target"
# ---------------------------------------------------------------------------

class TestErhnamDjinn:
    def _djinn_game(self, arn_by_name):
        djinn = _nosick(Permanent(card=arn_by_name["Erhnam Djinn"]))
        p1 = PlayerState(name="P1", battlefield=[djinn])
        p2 = PlayerState(
            name="P2",
            battlefield=[
                Permanent(card=_C["Grizzly Bears"]),
                Permanent(card=_C["Wall of Wood"]),
                Permanent(card=_C["Hill Giant"]),
            ],
        )
        return _game(p1, p2), p1, p2

    def test_upkeep_trigger_offers_a_target_choice(self, arn_by_name):
        game, _, _ = self._djinn_game(arn_by_name)
        triggers = game.get_upkeep_target_triggers(0)
        assert len(triggers) == 1
        trigger = triggers[0]
        assert trigger["card_name"] == "Erhnam Djinn"
        # Mandatory: the player picks a target but can't decline the trigger.
        assert trigger["mandatory"] is True
        assert trigger["needs_target"] == "creature"
        # The Wall is excluded; both non-Wall opponent creatures are offered.
        assert [t["name"] for t in trigger["valid_targets"]] == ["Grizzly Bears", "Hill Giant"]

    def test_chosen_target_gets_the_forestwalk_not_the_first_creature(self, arn_by_name):
        game, _, p2 = self._djinn_game(arn_by_name)
        # Hill Giant is index 2 — deliberately NOT the first legal candidate,
        # which is what the old auto-target always picked.
        game.resolve_upkeep(0, trigger_targets={"Erhnam Djinn": (1, 2)})
        assert p2.battlefield[2].metadata.get("has_forestwalk") is True
        assert p2.battlefield[0].metadata.get("has_forestwalk") is None

    def test_no_choice_falls_back_to_the_first_legal_creature(self, arn_by_name):
        # AI/headless play supplies no target and must still resolve.
        game, _, p2 = self._djinn_game(arn_by_name)
        game.resolve_upkeep(0)
        assert p2.battlefield[0].metadata.get("has_forestwalk") is True

    def test_a_target_that_left_the_battlefield_falls_back(self, arn_by_name):
        game, _, p2 = self._djinn_game(arn_by_name)
        game.resolve_upkeep(0, trigger_targets={"Erhnam Djinn": (1, 99)})
        assert p2.battlefield[0].metadata.get("has_forestwalk") is True

    def test_no_legal_target_offers_no_trigger(self, arn_by_name):
        djinn = _nosick(Permanent(card=arn_by_name["Erhnam Djinn"]))
        p1 = PlayerState(name="P1", battlefield=[djinn])
        # Only a Wall — not a legal target.
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=_C["Wall of Wood"])])
        game = _game(p1, p2)
        assert game.get_upkeep_target_triggers(0) == []


# ---------------------------------------------------------------------------
# Eye for an Eye — "I didn't get to choose a source"
# ---------------------------------------------------------------------------

class TestEyeForAnEye:
    def test_cast_spec_offers_a_source_of_choice(self, arn_by_name):
        bear = Permanent(card=_C["Grizzly Bears"])
        p1 = PlayerState(name="P1")
        p2 = PlayerState(name="P2", battlefield=[bear])
        game = _game(p1, p2)
        spec = game.cast_target_spec(0, arn_by_name["Eye for an Eye"])
        # Same shape as Reverse Damage: any permanent, or a spell on the stack.
        assert spec["kind"] == "permanent"
        assert spec["requires_target"] is True
        assert spec.get("source_of_choice") is True
        assert spec.get("also_stack") is True
        assert any(t["key"] == "1-0" for t in spec["valid_targets"])

    def _armed_game(self, arn_by_name):
        chosen = Permanent(card=_C["Grizzly Bears"])
        other = Permanent(card=_C["Hill Giant"])
        p1 = PlayerState(name="P1", hand=[arn_by_name["Eye for an Eye"]])
        p2 = PlayerState(name="P2", battlefield=[chosen, other])
        game = _game(p1, p2)
        game.cast_from_hand(0, "Eye for an Eye", target_player_index=1, target_permanent_index=0)
        game.resolve_top_of_stack()
        return game, p1, p2, chosen, other

    def test_chosen_source_is_recorded_by_identity(self, arn_by_name):
        game, p1, _, chosen, _ = self._armed_game(arn_by_name)
        assert p1.mirror_damage_sources == [chosen]
        # No generic charge when a specific source was picked.
        assert p1.mirror_damage_charges == 0

    def test_only_the_chosen_source_mirrors(self, arn_by_name):
        game, p1, p2, chosen, other = self._armed_game(arn_by_name)
        # Damage from a source that wasn't chosen hits normally, no mirror.
        game._deal_damage_to_player(p1, 3, source=other)
        assert p1.life == 17
        assert p2.life == 20
        assert p1.mirror_damage_sources == [chosen]

        # Damage from the chosen source is mirrored to its controller.
        game._deal_damage_to_player(p1, 2, source=chosen)
        assert p1.life == 15
        assert p2.life == 18
        # One-shot: the entry is consumed.
        assert p1.mirror_damage_sources == []

    def test_headless_cast_keeps_the_generic_charge(self, arn_by_name):
        # AI/headless casts pick no source, so any source's damage mirrors.
        p1 = PlayerState(name="P1", hand=[arn_by_name["Eye for an Eye"]])
        p2 = PlayerState(name="P2")
        game = _game(p1, p2)
        game.cast_from_hand(0, "Eye for an Eye")
        game.resolve_top_of_stack()
        assert p1.mirror_damage_charges == 1
        game._deal_damage_to_player(p1, 4)
        assert (p1.life, p2.life) == (16, 16)
        assert p1.mirror_damage_charges == 0

    def test_sources_expire_at_cleanup(self, arn_by_name):
        game, p1, _, _, _ = self._armed_game(arn_by_name)
        game.resolve_cleanup_step(0)
        assert p1.mirror_damage_sources == []


# ---------------------------------------------------------------------------
# King Suleiman — "Ability didn't let me choose a target"
# ---------------------------------------------------------------------------

class TestKingSuleiman:
    def test_activation_prompts_for_a_djinn_or_efreet(self, arn_by_name):
        # "Destroy target Djinn or Efreet" never says "creature", so the prompt
        # comes from the compiled instruction's subtype filter.
        king = _nosick(Permanent(card=arn_by_name["King Suleiman"]))
        p1 = PlayerState(name="P1", battlefield=[king])
        p2 = PlayerState(
            name="P2",
            battlefield=[Permanent(card=_C["Grizzly Bears"]), Permanent(card=arn_by_name["Erhnam Djinn"])],
        )
        game = _game(p1, p2)
        spec = game.activation_target_spec(0, 0)
        assert spec["requires_target"] is True
        assert spec["kind"] == "creature"
        # Only the Djinn is a legal target — the Bears aren't offered.
        assert [t["name"] for t in spec["valid_targets"]] == ["Erhnam Djinn"]


# ---------------------------------------------------------------------------
# Jandor's Ring — "It didn't discard the last card I drew this turn"
# ---------------------------------------------------------------------------

class TestJandorsRing:
    def _ring_game(self, arn_by_name):
        ring = _nosick(Permanent(card=arn_by_name["Jandor's Ring"]))
        p1 = PlayerState(
            name="P1",
            battlefield=[ring],
            library=[_C["Hill Giant"], _C["Black Lotus"], _C["Plains"]],
        )
        return _game(p1, PlayerState(name="P2")), p1

    def test_discard_cost_is_parsed(self, arn_by_name):
        program = compile_card_oracle(arn_by_name["Jandor's Ring"])
        (ability,) = program.activated_abilities
        assert ability.cost.discard_last_drawn is True
        assert ability.cost.requires_tap is True
        assert ability.cost.mana["generic"] == 2

    def test_unactivatable_with_nothing_drawn_this_turn(self, arn_by_name):
        game, p1 = self._ring_game(arn_by_name)
        result = game.queue_permanent_ability(0, "Jandor's Ring")
        assert not result.supported
        assert "no card drawn this turn" in result.details
        # The cost was never paid: the artifact stays untapped.
        assert p1.battlefield[0].tapped is False

    def test_activation_discards_the_last_drawn_card(self, arn_by_name):
        game, p1 = self._ring_game(arn_by_name)
        p1.draw(1)
        assert [c.name for c in p1.hand] == ["Hill Giant"]

        assert game.queue_permanent_ability(0, "Jandor's Ring").supported
        # Discarded on activation, before the ability resolves.
        assert p1.hand == []
        assert [c.name for c in p1.graveyard] == ["Hill Giant"]

        game.resolve_top_of_stack()
        assert [c.name for c in p1.hand] == ["Black Lotus"]

    def test_it_discards_the_last_card_drawn_not_the_first(self, arn_by_name):
        game, p1 = self._ring_game(arn_by_name)
        p1.draw(2)
        assert game.queue_permanent_ability(0, "Jandor's Ring").supported
        assert [c.name for c in p1.graveyard] == ["Black Lotus"]
        assert [c.name for c in p1.hand] == ["Hill Giant"]

    def test_a_drawn_card_no_longer_in_hand_cannot_pay(self, arn_by_name):
        game, p1 = self._ring_game(arn_by_name)
        p1.draw(1)
        p1.hand.clear()  # played it
        result = game.queue_permanent_ability(0, "Jandor's Ring")
        assert not result.supported

    def test_draw_tracking_resets_each_turn(self, arn_by_name):
        game, p1 = self._ring_game(arn_by_name)
        p1.draw(1)
        game.begin_turn_bookkeeping(0)
        assert p1.cards_drawn_this_turn == []
        assert p1.last_card_drawn_this_turn() is None

    def test_a_lamp_replaced_draw_still_counts_as_drawn(self, arn_by_name):
        # Aladdin's Lamp's replacement ends in "then draw a card", so the card it
        # puts in hand is the last card drawn this turn.
        lamp = _nosick(Permanent(card=arn_by_name["Aladdin's Lamp"]))
        p1 = PlayerState(name="P1", battlefield=[lamp], library=[_C["Plains"], _C["Island"]])
        game = _game(p1, PlayerState(name="P2"))
        game.turn = 3
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=2)
        game.resolve_draw_step(0)
        assert p1.last_card_drawn_this_turn() is p1.hand[0]


# ---------------------------------------------------------------------------
# Guardian Beast — granted indestructible must be visible on the affected cards
# ---------------------------------------------------------------------------

class TestGuardianBeastDisplay:
    def _beast_game(self, arn_by_name):
        beast = _nosick(Permanent(card=arn_by_name["Guardian Beast"]))
        mox = Permanent(card=_C["Mox Jet"])
        p1 = PlayerState(name="P1", battlefield=[beast, mox])
        return _game(p1, PlayerState(name="P2")), p1, beast, mox

    def test_serialized_permanent_reports_the_granted_indestructible(self, arn_by_name):
        from web.app import _serialize_permanent

        game, p1, beast, mox = self._beast_game(arn_by_name)
        # The grant is computed continuously and never written to metadata, so
        # reading metadata directly (the old bug) always reported False.
        assert mox.metadata.get("is_indestructible") is None

        payload = _serialize_permanent(mox, game)
        assert payload["is_indestructible"] is True
        assert payload["cant_be_enchanted_by_auras"] is True

        # Tapping the Beast turns the grant off again.
        beast.tapped = True
        payload = _serialize_permanent(mox, game)
        assert payload["is_indestructible"] is False
        assert payload["cant_be_enchanted_by_auras"] is False

    def test_indestructible_shows_in_the_keyword_strip(self, arn_by_name):
        from web.app import _effective_keywords

        game, p1, beast, mox = self._beast_game(arn_by_name)
        # A noncreature permanent gets a keyword strip solely for this.
        assert _effective_keywords(mox, game) == ["Indestructible"]
        beast.tapped = True
        assert _effective_keywords(mox, game) == []

    def test_creature_keywords_still_render_alongside_it(self, arn_by_name):
        from web.app import _effective_keywords

        angel = Permanent(card=_C["Serra Angel"])
        p1 = PlayerState(name="P1", battlefield=[angel])
        game = _game(p1, PlayerState(name="P2"))
        keywords = _effective_keywords(angel, game)
        assert "Flying" in keywords and "Vigilance" in keywords
        assert "Indestructible" not in keywords


# ---------------------------------------------------------------------------
# Aladdin's Lamp — the picker needs card art, not just names
# ---------------------------------------------------------------------------

class TestAladdinsLampPayload:
    def test_pending_draw_payload_carries_serialized_cards(self, arn_by_name):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
        ).json()
        sid = created["session_id"]
        session = store.get(sid)
        game = session.game
        session.current_turn = 0
        game.turn = 3
        game.enforce_mana_costs = False

        p1 = game.players[0]
        p1.battlefield.append(_nosick(Permanent(card=arn_by_name["Aladdin's Lamp"])))
        p1.library = [_C["Lightning Bolt"], _C["Forest"], _C["Island"], _C["Grizzly Bears"]]
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=3)
        game.interactive_seats = {0}
        game.resolve_draw_step(0)
        assert game.pending_lamp_draw is not None

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        lamp = state["lamp_draw"]
        assert lamp["card_names"] == ["Lightning Bolt", "Forest", "Island"]
        # The visual picker needs the cards themselves, one per revealed name.
        assert [c["name"] for c in lamp["cards"]] == lamp["card_names"]
        assert all("image_uri" in c and "oracle_text" in c for c in lamp["cards"])

    def test_opponent_does_not_see_the_revealed_cards(self, arn_by_name):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_human", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 6},
        ).json()
        sid = created["session_id"]
        session = store.get(sid)
        game = session.game
        session.current_turn = 0
        game.turn = 3
        game.enforce_mana_costs = False

        p1 = game.players[0]
        p1.battlefield.append(_nosick(Permanent(card=arn_by_name["Aladdin's Lamp"])))
        p1.library = [_C["Lightning Bolt"], _C["Forest"]]
        game.activate_permanent_ability(0, "Aladdin's Lamp", target_player_index=0, x_value=2)
        game.interactive_seats = {0}
        game.resolve_draw_step(0)

        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        assert state["lamp_draw"] is None


# ---------------------------------------------------------------------------
# Ring of Ma'rûf — the sideboard ("outside the game", CR 100.4)
# ---------------------------------------------------------------------------

class TestSideboardDeckModel:
    def test_decklist_text_parses_a_sideboard_section(self):
        entries, warnings, sideboard, commander = parse_decklist_text(
            "4 Lightning Bolt\n2 Forest\n\nSideboard\n3 Disenchant\n1 Black Lotus\n"
        )
        assert entries == [
            {"name": "Lightning Bolt", "count": 4},
            {"name": "Forest", "count": 2},
        ]
        assert sideboard == [
            {"name": "Disenchant", "count": 3},
            {"name": "Black Lotus", "count": 1},
        ]
        assert commander == []
        assert warnings == []

    def test_decklist_text_parses_a_commander_section(self):
        entries, warnings, sideboard, commander = parse_decklist_text(
            "Commander\n1 Norin the Wary\n\nDeck\n1 Sol Ring\n99 Forest\n"
        )
        assert commander == [{"name": "Norin the Wary", "count": 1}]
        assert entries == [
            {"name": "Sol Ring", "count": 1},
            {"name": "Forest", "count": 99},
        ]
        assert sideboard == []
        assert warnings == []

    def test_maybeboard_is_still_discarded(self):
        entries, _, sideboard, commander = parse_decklist_text(
            "4 Lightning Bolt\n\nMaybeboard\n2 Shatter\n"
        )
        assert entries == [{"name": "Lightning Bolt", "count": 4}]
        assert sideboard == []
        assert commander == []

    def test_deck_store_round_trips_a_sideboard(self, tmp_path):
        from web.deck_store import DeckStore, deck_sideboard

        deck_store = DeckStore(tmp_path)
        deck = deck_store.create(
            "T", [{"name": "Forest", "count": 4}], sideboard=[{"name": "Shatter", "count": 2}]
        )
        assert deck_sideboard(deck_store.get(deck["id"])) == [{"name": "Shatter", "count": 2}]

        deck_store.update(deck["id"], "T", [{"name": "Forest", "count": 4}])
        assert deck_sideboard(deck_store.get(deck["id"])) == []

    def test_a_deck_saved_before_sideboards_reads_as_empty(self):
        from web.deck_store import deck_sideboard

        assert deck_sideboard({"id": "x", "name": "old", "cards": []}) == []

    def test_deck_store_round_trips_a_commander(self, tmp_path):
        from web.deck_store import DeckStore, deck_commander

        deck_store = DeckStore(tmp_path)
        deck = deck_store.create(
            "T", [{"name": "Forest", "count": 99}], format="commander",
            commander=[{"name": "Norin the Wary", "count": 1}],
        )
        assert deck_commander(deck_store.get(deck["id"])) == [{"name": "Norin the Wary", "count": 1}]

        deck_store.update(deck["id"], "T", [{"name": "Forest", "count": 99}], format="commander")
        assert deck_commander(deck_store.get(deck["id"])) == []

    def test_a_deck_saved_before_commander_zones_reads_as_empty(self):
        from web.deck_store import deck_commander

        assert deck_commander({"id": "x", "name": "old", "cards": []}) == []

    def test_session_creation_puts_the_sideboard_in_the_players_zone(self):
        created = client.post(
            "/api/sessions",
            json={
                "mode": "human_vs_ai",
                "host_name": "H",
                "host_colors": 2,
                "guest_colors": 2,
                "seed": 7,
                "host_deck_cards": [{"name": "Forest", "count": 60}],
                "host_deck_sideboard": [{"name": "Black Lotus", "count": 1}, {"name": "Shatter", "count": 2}],
            },
        ).json()
        session = store.get(created["session_id"])
        sideboard = session.game.players[0].sideboard
        assert [c.name for c in sideboard] == ["Black Lotus", "Shatter", "Shatter"]
        # The sideboard is not part of the library.
        assert all(c.name == "Forest" for c in session.game.players[0].library)

    def test_sideboard_is_private_to_its_owner(self):
        created = client.post(
            "/api/sessions",
            json={
                "mode": "human_vs_human",
                "host_name": "H",
                "host_colors": 2,
                "guest_colors": 2,
                "seed": 8,
                "host_deck_cards": [{"name": "Forest", "count": 60}],
                "host_deck_sideboard": [{"name": "Black Lotus", "count": 1}],
            },
        ).json()
        sid = created["session_id"]

        own = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        assert [c["name"] for c in own["players"][0]["sideboard"]] == ["Black Lotus"]
        assert own["players"][0]["sideboard_count"] == 1

        other = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
        assert other["players"][0]["sideboard"] == []
        # The count is public even though the contents aren't.
        assert other["players"][0]["sideboard_count"] == 1


class TestRingOfMaruf:
    def _ring_game(self, arn_by_name, *, interactive: bool, sideboard=None):
        ring_card = _ring_of_maruf(arn_by_name)
        p1 = PlayerState(
            name="P1",
            battlefield=[_nosick(Permanent(card=ring_card))],
            library=[_C["Plains"]] * 5,
            sideboard=list(sideboard if sideboard is not None else [_C["Black Lotus"], _C["Time Walk"]]),
        )
        game = _game(p1, PlayerState(name="P2"))
        game.turn = 3  # avoid the first-turn draw skip (CR 103.8a)
        if interactive:
            game.interactive_seats = {0}
        return game, p1, ring_card

    def test_activation_exiles_the_ring_as_a_cost(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True)
        assert game.queue_permanent_ability(0, ring_card.name).supported
        assert p1.battlefield == []
        assert [c.name for c in p1.exile] == [ring_card.name]

    def test_ability_arms_a_draw_replacement(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True)
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        assert game.outside_game_draw_replacements == {0}
        assert p1.hand == []  # nothing taken yet — the draw is replaced later

    def test_interactive_draw_prompts_and_takes_the_chosen_card(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True)
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        game.resolve_draw_step(0)

        pending = game.pending_outside_game_draw
        assert pending is not None
        assert pending["card_names"] == ["Black Lotus", "Time Walk"]
        # The draw was replaced, so the library is untouched.
        assert len(p1.library) == 5

        assert game.confirm_outside_game_draw(0, 1) is True
        assert [c.name for c in p1.hand] == ["Time Walk"]
        assert [c.name for c in p1.sideboard] == ["Black Lotus"]
        assert len(p1.library) == 5

    def test_headless_draw_takes_the_first_sideboard_card(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=False)
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        game.resolve_draw_step(0)
        assert [c.name for c in p1.hand] == ["Black Lotus"]
        assert len(p1.library) == 5

    def test_an_empty_sideboard_draws_nothing_and_spends_the_replacement(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True, sideboard=[])
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        game.resolve_draw_step(0)
        assert game.pending_outside_game_draw is None
        assert p1.hand == []
        assert len(p1.library) == 5
        assert game.outside_game_draw_replacements == set()

    def test_the_replacement_expires_with_the_turn(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True)
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        game.begin_turn_bookkeeping(0)
        assert game.outside_game_draw_replacements == set()
        game.resolve_draw_step(0)
        assert len(p1.library) == 4  # a normal draw

    def test_only_the_first_draw_is_replaced(self, arn_by_name):
        game, p1, ring_card = self._ring_game(arn_by_name, interactive=True)
        game.queue_permanent_ability(0, ring_card.name)
        game.resolve_top_of_stack()
        # Draw two: the first is replaced, the second is a real draw.
        game._draw_with_lamp(p1, 2)
        assert game.pending_outside_game_draw["remaining_draws"] == 1
        game.confirm_outside_game_draw(0, 0)
        assert [c.name for c in p1.hand] == ["Black Lotus", "Plains"]
        assert len(p1.library) == 4
