"""Per-card tests for Limited Edition Alpha's instant cards.

Split out of the 9,400-line test_lea_cards.py by the type of the
card each test names. See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine.ai_policy import (
    choose_cast_action,
    choose_activation_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
    choose_reorder_library_order,
)
from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, lex_oracle_text, parse_activated_ability_cost
from engine.text_changes import changed_words
import json
from web.app import app, store
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)
from tests.sets.lea_helpers import (
    _forest,
    _grizzly,
    _island,
    _mountain,
    _plains,
    _start_session_with_p0_graveyard,
    _swamp,
)


def test_choose_cast_action_targets_self_for_ancestral_recall(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")
    # Provide enough library cards so self-targeting is safe (≥ 3 required).
    p1 = PlayerState(
        name="P1",
        hand=[recall],
        library=[island, island, island, island, island],
        mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Ancestral Recall"
    assert action.target_player_index == 0


def test_choose_cast_action_finds_lethal_lightning_bolt(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    salve = _get(all_cards, "Healing Salve")
    mountain = _get(all_cards, "Mountain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(
        name="P1",
        hand=[salve, bolt],
        battlefield=[Permanent(card=mountain), Permanent(card=plains)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Lightning Bolt"
    assert action.target_player_index == 1
    assert action.land_tap_indices


def test_choose_cast_action_skips_unsummon_without_target(all_cards):
    unsummon = _get(all_cards, "Unsummon")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[unsummon], battlefield=[Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is None


def test_ancestral_recall_draws_three(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", library=[island, island, island, island])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=1)

    assert result.supported
    assert len(p2.hand) == 3


def test_counterspell_counters_spell_on_stack(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    counterspell = _get(all_cards, "Counterspell")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[recall])
    p2 = PlayerState(name="P2", hand=[counterspell], library=[island, island, island, island])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 1
    assert p2.graveyard[0].name == "Counterspell"
    assert len(p1.graveyard) == 1
    assert p1.graveyard[0].name == "Ancestral Recall"


def test_disenchant_destroys_target_artifact(all_cards):
    disenchant = _get(all_cards, "Disenchant")
    lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(name="P1", hand=[disenchant])
    p2 = PlayerState(name="P2")
    p2.battlefield.append(Permanent(card=lotus))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Disenchant", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard
    assert p2.graveyard[0].name == "Black Lotus"


def test_unsummon_returns_target_creature(all_cards):
    unsummon = _get(all_cards, "Unsummon")
    creature = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert any(card.name == "Bear" for card in p2.hand)


def test_unsummon_bounces_the_chosen_creature(all_cards):
    # With several creatures in play, Unsummon must return the one the player
    # targeted (index 1), not simply the first creature found.
    unsummon = _get(all_cards, "Unsummon")
    bear = _mk_card("Bear", "Creature — Bear")
    ogre = _mk_card("Ogre", "Creature — Ogre")
    wall = _mk_card("Wall", "Creature — Wall")
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=bear), Permanent(card=ogre), Permanent(card=wall)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unsummon", target_player_index=1, target_permanent_index=1)

    assert result.supported
    assert [p.card.name for p in p2.battlefield] == ["Bear", "Wall"]
    assert [c.name for c in p2.hand] == ["Ogre"]


def test_sacrifice_spell_adds_black_mana(all_cards):
    sacrifice = _get(all_cards, "Sacrifice")
    creature = _mk_card("Mana Bear", "Creature — Bear")
    creature = CardDefinition(
        name=creature.name,
        mana_cost=creature.mana_cost,
        cmc=3.0,
        type_line=creature.type_line,
        oracle_text=creature.oracle_text,
        colors=creature.colors,
        color_identity=creature.color_identity,
        keywords=creature.keywords,
        produced_mana=creature.produced_mana,
        raw=creature.raw,
    )
    p1 = PlayerState(name="P1", hand=[sacrifice], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sacrifice", target_player_index=0)

    assert result.supported
    assert p1.mana_pool["B"] == 3
    assert not p1.battlefield


def test_stasis_upkeep_sacrifice_removes_stasis(all_cards):
    """Player choosing to sacrifice Stasis at upkeep removes it correctly."""
    from web.app import _end_turn

    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": 80},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p1 = session.game.players[0]
    p1.battlefield = [Permanent(card=stasis), Permanent(card=island)]
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    p1.hand = []

    _end_turn(session, allow_manual_cleanup_selection=False)  # P1's turn
    _end_turn(session, allow_manual_cleanup_selection=False)  # P0 turn 2, deferred at upkeep

    assert session.game.current_step == "upkeep"

    sacrifice_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "sacrifice_upkeep", "card_name": "Stasis"},
    )
    assert sacrifice_resp.status_code == 200
    assert not any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must be gone after sacrifice"
    assert any(c.name == "Stasis" for c in p1.graveyard), \
        "Stasis must be in graveyard after sacrifice"
    assert session.game.current_turn_phase == "precombat_main", \
        "game should have advanced to main phase after sacrifice"


def test_natural_selection_reorders_top_three(all_cards):
    natural = _get(all_cards, "Natural Selection")
    a = _mk_card("A", "Sorcery")
    b = _mk_card("B", "Sorcery")
    c = _mk_card("C", "Sorcery")
    d = _mk_card("D", "Sorcery")
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=[a, b, c, d])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Natural Selection", target_player_index=1)

    assert result.supported
    pending = game.pending_reorder_library
    assert pending is not None
    assert pending["caster_index"] == 0
    assert pending["target_index"] == 1
    assert pending["top_count"] == 3

    # Confirm with order [2, 1, 0] -> C, B, A on top
    ok = game.confirm_reorder_library(0, [2, 1, 0])
    assert ok
    assert [card.name for card in p2.library] == ["C", "B", "A", "D"]
    assert game.pending_reorder_library is None


def test_natural_selection_preserves_rest_of_library(all_cards):
    natural = _get(all_cards, "Natural Selection")
    cards = [_mk_card(name, "Sorcery") for name in ["A", "B", "C", "D", "E"]]
    p1 = PlayerState(name="P1", hand=[natural])
    p2 = PlayerState(name="P2", library=cards)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Natural Selection", target_player_index=1)
    # Keep original order [0, 1, 2] -> no change to top 3
    game.confirm_reorder_library(0, [0, 1, 2])

    assert [card.name for card in p2.library] == ["A", "B", "C", "D", "E"]


def test_word_of_command_forces_play_from_hand(all_cards):
    word = _get(all_cards, "Word of Command")
    card_in_hand = _mk_card("Victim Spell", "Sorcery")
    p1 = PlayerState(name="P1", hand=[word])
    p2 = PlayerState(name="P2", hand=[card_in_hand])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Word of Command", target_player_index=1)
    assert result.supported
    # The caster looks at the target's hand and chooses which card to force.
    assert game.pending_word_of_command is not None
    assert game.confirm_word_of_command(0, 0) is True
    assert len(p2.hand) == 0
    assert any(card.name == "Victim Spell" for card in p2.graveyard)


def test_magical_hack_marks_target_text_modified(all_cards):
    hack = _get(all_cards, "Magical Hack")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[hack])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Magical Hack", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True


def test_sleight_of_mind_marks_target_text_modified(all_cards):
    sleight = _get(all_cards, "Sleight of Mind")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[sleight])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Sleight of Mind", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("text_modified") is True


def test_sleight_of_mind_retargets_lifeforce_counter_to_red(all_cards):
    # Sleight of Mind changes Lifeforce's "Counter target black spell" to
    # "Counter target red spell"; Lifeforce can then counter a Lightning Bolt.
    sleight = _get(all_cards, "Sleight of Mind")
    lifeforce = _get(all_cards, "Lifeforce")
    lightning_bolt = _get(all_cards, "Lightning Bolt")

    p1 = PlayerState(name="P1", hand=[sleight], battlefield=[Permanent(card=lifeforce)])
    p2 = PlayerState(name="P2", hand=[lightning_bolt])
    game = Game(players=[p1, p2])

    # Change Lifeforce's text: black -> red.
    result = game.cast_from_hand(
        0,
        "Sleight of Mind",
        target_player_index=0,
        target_permanent_index=0,
        old_color="B",
        new_color="R",
    )
    assert result.supported
    lifeforce_perm = p1.battlefield[0]
    assert changed_words(lifeforce_perm) == [{"from": "black", "to": "red"}]

    # P2 casts Lightning Bolt (a red spell); Lifeforce can now counter it.
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.activate_permanent_ability(0, "Lifeforce", target_player_index=0)

    assert result.supported
    assert not game.stack
    assert any(card.name == "Lightning Bolt" for card in p2.graveyard)


def test_sleight_of_mind_lifeforce_no_longer_counters_black(all_cards):
    # After black -> red, Lifeforce may no longer counter a black spell.
    sleight = _get(all_cards, "Sleight of Mind")
    lifeforce = _get(all_cards, "Lifeforce")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", hand=[sleight], battlefield=[Permanent(card=lifeforce)])
    p2 = PlayerState(name="P2", hand=[black_knight])
    game = Game(players=[p1, p2])

    game.cast_from_hand(
        0, "Sleight of Mind", target_player_index=0, target_permanent_index=0,
        old_color="B", new_color="R",
    )
    game.queue_from_hand(1, "Black Knight")
    result = game.queue_permanent_ability(0, "Lifeforce", target_player_index=0)

    assert not result.supported
    assert any(item.card.name == "Black Knight" for item in game.stack)


def test_blaze_of_glory_sets_forced_blocking_marker(all_cards):
    blaze = _get(all_cards, "Blaze of Glory")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[blaze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])
    # Blaze of Glory may be cast only during combat before blockers are declared.
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # → beginning_of_combat
    game.advance_combat_phase()  # → declare_attackers

    result = game.cast_from_hand(0, "Blaze of Glory", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("must_block_all_until_eot") is True


def test_camouflage_resolves_supported(all_cards):
    camouflage = _get(all_cards, "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # → beginning_of_combat
    game.advance_combat_phase()  # → declare_attackers

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert result.supported
    assert any("pile blocking" in line.lower() for line in game.log)


def test_camouflage_requires_declare_attackers_step(all_cards):
    """Camouflage cannot be cast outside the declare attackers step."""
    camouflage = _get(all_cards, "Camouflage")
    p1 = PlayerState(name="P1", hand=[camouflage])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    # Default step is precombat_main, not declare_attackers
    assert game.current_step != "declare_attackers"

    result = game.cast_from_hand(0, "Camouflage", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Camouflage"


def test_false_orders_marks_creature_removed_from_combat(all_cards):
    false_orders = _get(all_cards, "False Orders")
    bear = _mk_card("Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[false_orders])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # False Orders may only be cast during the declare blockers step.
    game._set_phase_and_step("combat", "declare_blockers")
    result = game.cast_from_hand(0, "False Orders", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("removed_from_combat") is True


def test_fork_copies_top_spell_effect(all_cards):
    fork = _get(all_cards, "Fork")
    bolt = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    p1 = PlayerState(name="P1", hand=[bolt], life=20)
    p2 = PlayerState(name="P2", hand=[fork], life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt Test", target_player_index=0)
    game.queue_from_hand(1, "Fork", target_player_index=0)
    game.resolve_stack()

    assert p1.life == 14


def test_parse_activated_ability_cost_handles_sacrifice_clause():
    cost = parse_activated_ability_cost("{T}, Sacrifice this artifact: Add three mana of any one color.")

    assert cost.requires_tap is True
    assert cost.mana["generic"] == 0


def test_howl_from_beyond_pumps_target_creature_by_x(all_cards):
    howl = _get(all_cards, "Howl from Beyond")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[howl])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    before_power = p2.battlefield[0].effective_power
    result = game.cast_from_hand(0, "Howl from Beyond", target_player_index=1, x_value=4)

    assert result.supported
    assert p2.battlefield[0].effective_power == before_power + 4
    assert p2.battlefield[0].effective_toughness == 2


def test_guardian_angel_prevents_x_damage(all_cards):
    angel = _get(all_cards, "Guardian Angel")

    p1 = PlayerState(name="P1", hand=[angel], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Guardian Angel", target_player_index=0, x_value=3)

    assert result.supported
    assert p1.damage_prevention_pool == 3
    # The second sentence grants a repeatable "pay {1}: prevent next 1 damage"
    # emblem until end of turn, locked to the spell's original target (player 0).
    assert len(p1.prevent_one_damage_emblems) == 1
    assert p1.prevent_one_damage_emblems[0]["target_player_index"] == 0


def test_guardian_angel_emblem_reuses_player_target_and_cleanup(all_cards):
    angel = _get(all_cards, "Guardian Angel")

    p1 = PlayerState(name="P1", hand=[angel], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=False)
    # Cast targeting the controller themselves; the emblem is locked to player 0.
    game.cast_from_hand(0, "Guardian Angel", target_player_index=0, x_value=0)
    assert len(p1.prevent_one_damage_emblems) == 1

    # Activation needs no target — it reuses the stored one (player 0).
    before = p1.damage_prevention_pool
    result = game.activate_prevent_one_emblem(0)
    assert result.supported
    assert p1.damage_prevention_pool == before + 1

    # Repeatable: activating again grants another shield (emblem is not consumed).
    game.activate_prevent_one_emblem(0)
    assert p1.damage_prevention_pool == before + 2

    # The emblem (and its shields) expire at cleanup.
    game.resolve_cleanup_step(0)
    assert p1.prevent_one_damage_emblems == []
    assert p1.damage_prevention_pool == 0


def test_guardian_angel_emblem_reuses_creature_target(all_cards):
    angel = _get(all_cards, "Guardian Angel")
    bears = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[angel], life=20, battlefield=[Permanent(card=bears)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=False)
    # Cast targeting the controller's own Grizzly Bears.
    game.cast_from_hand(0, "Guardian Angel", target_player_index=0, target_permanent_index=0, x_value=0)
    entry = p1.prevent_one_damage_emblems[0]
    assert entry["target_player_index"] == 0
    assert entry["target_permanent_index"] == 0

    # Activation protects that same creature, no re-targeting.
    game.activate_prevent_one_emblem(0)
    assert p1.battlefield[0].damage_prevention_pool == 1

    # If the creature leaves play, the emblem has no legal target and does nothing.
    p1.battlefield.clear()
    result = game.activate_prevent_one_emblem(0)
    assert not result.supported


def test_guardian_angel_emblem_requires_mana_when_enforced(all_cards):
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    # Grant the emblem directly (target = player 0) to isolate activation-cost
    # behavior from the Angel's own casting cost.
    p1.prevent_one_damage_emblems = [{"target_player_index": 0, "target_permanent_index": None}]

    # No mana in pool: activation fails and grants no shield.
    result = game.activate_prevent_one_emblem(0)
    assert not result.supported
    assert p1.damage_prevention_pool == 0

    # With {1} available, it succeeds and spends the mana.
    p1.mana_pool["C"] = 1
    result = game.activate_prevent_one_emblem(0)
    assert result.supported
    assert p1.damage_prevention_pool == 1
    assert p1.mana_pool["C"] == 0


def test_power_sink_counters_spell_and_taps_controller_lands(all_cards):
    """Power Sink counters the target spell and taps all of the controller's lands."""
    power_sink = _get(all_cards, "Power Sink")
    ancestral_recall = _get(all_cards, "Ancestral Recall")
    island = _mk_card("Island", type_line="Basic Land - Island", mana_cost="")

    island1 = Permanent(card=island, tapped=False)
    island2 = Permanent(card=island, tapped=False)
    p1 = PlayerState(name="P1", hand=[power_sink])
    p2 = PlayerState(
        name="P2",
        hand=[ancestral_recall],
        battlefield=[island1, island2],
    )
    game = Game(players=[p1, p2])

    # p2 queues Ancestral Recall targeting themselves (don't auto-resolve)
    game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
    assert len(game.stack) == 1

    # p1 counters with Power Sink, X=5 (more than p2 can pay)
    # cast_from_hand will queue Power Sink then resolve the entire stack
    result = game.cast_from_hand(0, "Power Sink", target_player_index=1, x_value=5)
    assert result.supported

    # Ancestral Recall should have been countered (removed from stack)
    assert len(game.stack) == 0
    # All of p2's lands should be tapped
    land_perms = [perm for perm in p2.battlefield if perm.card.primary_type == "land"]
    assert land_perms, "P2 should still have lands on battlefield"
    assert all(perm.tapped for perm in land_perms), \
        "Power Sink should tap all of the countered spell controller's lands"
    # p2's mana pool should be empty
    assert all(v == 0 for v in p2.mana_pool.values()), \
        "Power Sink should drain all mana from countered spell controller's mana pool"


def test_berserk_doubles_power_and_grants_trample(all_cards):
    berserk = _get(all_cards, "Berserk")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[berserk])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Berserk", target_player_index=1, target_permanent_index=0)

    assert result.supported
    target_perm = p2.battlefield[0]
    # power doubles: base 2 + bonus 2 = 4
    assert target_perm.effective_power == 4
    assert target_perm.has_keyword("trample") is True


def test_blue_elemental_blast_counters_red_spell(all_cards):
    """Blue Elemental Blast's first mode counters a red spell on the stack."""
    beb = _get(all_cards, "Blue Elemental Blast")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert result.supported
    # The round-19 wording: the one _bin_spell_card line carries the verb.
    assert any("Lightning Bolt was countered by Blue Elemental Blast" in line for line in game.log)
    assert not game.stack, "Stack should be empty after counterspell resolves"


def test_blue_elemental_blast_cannot_be_cast_without_valid_target(all_cards):
    """Blue Elemental Blast cannot be cast if there are no valid red targets."""
    beb = _get(all_cards, "Blue Elemental Blast")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Blue Elemental Blast"


def test_blue_elemental_blast_cannot_be_cast_with_empty_battlefield(all_cards):
    """Blue Elemental Blast cannot be cast if target player has no permanents."""
    beb = _get(all_cards, "Blue Elemental Blast")
    p1 = PlayerState(name="P1", hand=[beb])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Elemental Blast", target_player_index=1)

    assert not result.supported
    assert p1.hand and p1.hand[0].name == "Blue Elemental Blast"


def test_chaoslace_makes_target_permanent_red(all_cards):
    chaoslace = _get(all_cards, "Chaoslace")
    creature = _mk_card("Forest Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[chaoslace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Chaoslace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "R"


def test_dark_ritual_adds_three_black_mana(all_cards):
    dark_ritual = _get(all_cards, "Dark Ritual")

    p1 = PlayerState(name="P1", hand=[dark_ritual])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Dark Ritual")

    assert result.supported
    assert p1.mana_pool.get("B", 0) == 3


def test_giant_growth_gives_target_creature_plus_three_three(all_cards):
    growth = _get(all_cards, "Giant Growth")
    bear = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[growth], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Giant Growth", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_power == 5
    assert p1.battlefield[0].effective_toughness == 5


def test_jump_grants_flying_until_eot(all_cards):
    jump = _get(all_cards, "Jump")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[jump])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Jump", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].has_keyword("flying") is True


def test_lich_damage_forces_sacrifice_of_that_many_nontoken_permanents(all_cards):
    """'Whenever you're dealt damage, sacrifice that many nontoken permanents.'"""
    lich = _get(all_cards, "Lich")
    forest = _get(all_cards, "Forest")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=lich),
            Permanent(card=forest),
            Permanent(card=forest),
            Permanent(card=forest),
            Permanent(card=forest),
        ],
        life=10,
    )
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported
    assert p1.life == 7
    # Sacrificed 3 of the 4 Forests; Lich itself is spared while other permanents exist
    assert sum(1 for perm in p1.battlefield if perm.card.name == "Forest") == 1
    assert any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert sum(1 for card in p1.graveyard if card.name == "Forest") == 3
    assert p1.lost is False


def test_lifelace_changes_target_permanent_to_green(all_cards):
    lifelace = _get(all_cards, "Lifelace")
    creature = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[lifelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lifelace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "G"


def test_mana_short_taps_target_lands_and_drains_mana(all_cards):
    mana_short = _get(all_cards, "Mana Short")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[mana_short])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island), Permanent(card=island)], mana_pool={"U": 3})
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Mana Short", target_player_index=1)

    assert result.supported
    assert all(perm.tapped for perm in p2.battlefield)
    assert p2.mana_pool["U"] == 0


def test_healing_salve_choose_one_gains_life(all_cards):
    """Regression: real LEA Healing Salve should gain 3 life (first mode), not
    apply a prevention shield. The oracle parser previously matched the second
    bullet 'prevent the next 3 damage' before 'gains 3 life'."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0)

    assert result.supported
    assert p1.life == 20, "Healing Salve should gain 3 life (first mode), not apply prevention"
    assert p1.damage_prevention_pool == 0, "Prevention shield should not be applied when gaining life"


def test_healing_salve_choose_one_compiles_to_life_gain(all_cards):
    """Regression: the primary oracle instruction for real LEA Healing Salve must
    be target_gains_life, not grant_prevention_shield."""
    salve = _get(all_cards, "Healing Salve")
    program = compile_card_oracle(salve)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "target_gains_life", (
        f"Expected target_gains_life but got {primary.kind}; "
        "choose-one parsing should use the first bullet"
    )


def test_blue_elemental_blast_choose_one_compiles_to_counter(all_cards):
    """Regression: Blue Elemental Blast's first mode is 'counter target red spell'.
    The oracle previously matched the second mode 'destroy target red permanent' first."""
    beb = _get(all_cards, "Blue Elemental Blast")
    program = compile_card_oracle(beb)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "counter_top_stack_spell", (
        f"Expected counter_top_stack_spell but got {primary.kind}"
    )
    assert primary.payload.get("color_filter") == "R"


def test_red_elemental_blast_choose_one_compiles_to_counter(all_cards):
    """Regression: Red Elemental Blast's first mode is 'counter target blue spell'.
    The oracle previously matched the second mode 'destroy target blue permanent' first."""
    reb = _get(all_cards, "Red Elemental Blast")
    program = compile_card_oracle(reb)
    primary = next(
        (instr for instr in program.instructions if instr.kind != "spell_pattern"), None
    )
    assert primary is not None
    assert primary.kind == "counter_top_stack_spell", (
        f"Expected counter_top_stack_spell but got {primary.kind}"
    )
    assert primary.payload.get("color_filter") == "U"


def test_healing_salve_compiles_both_modes(all_cards):
    """The modal compiler exposes each "Choose one —" bullet as a selectable mode
    so the game can resolve the player's pick rather than always the first."""
    salve = _get(all_cards, "Healing Salve")
    program = compile_card_oracle(salve)
    assert len(program.modes) == 2
    assert program.modes[0].instruction is not None
    assert program.modes[0].instruction.kind == "target_gains_life"
    assert program.modes[0].supported
    assert program.modes[1].instruction is not None
    assert program.modes[1].instruction.kind == "grant_prevention_shield"
    assert program.modes[1].supported
    # Labels keep human-readable, original-case text for the UI prompt.
    assert program.modes[0].label == "Target player gains 3 life"


def test_healing_salves_modes_come_from_a_head_line_the_parser_read(all_cards):
    """The mode list is grouped with the head *line* that announces it, and that
    line is read by the grammar (CR 700.2).

    It used to be a substring test over the card's whole collapsed text —
    "choose one" anywhere plus a bullet anywhere. That could not tell a head
    from a trigger's head, could not read any count but one, and matched inside
    "choose one **or more**". Here the head parses to a node carrying the count,
    and the modes are the bullets directly beneath it."""
    from engine.grammar import ast as grammar_ast, compile_line

    salve = _get(all_cards, "Healing Salve")
    head, *bullets = salve.oracle_text.splitlines()
    node = compile_line(head, card_name=salve.name).node

    assert isinstance(node, grammar_ast.SpellEffectLine)
    assert node.statement == grammar_ast.ModalNode(1)
    assert [line.startswith("•") for line in bullets] == [True, True]
    assert len(compile_card_oracle(salve).modes) == 2


def test_healing_salve_resolves_chosen_prevention_mode(all_cards):
    """Casting Healing Salve with mode_index=1 applies the prevention shield mode
    instead of the default life-gain mode."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0, mode_index=1)

    assert result.supported
    assert p1.life == 17, "Prevention mode should not gain life"
    assert p1.damage_prevention_pool == 3, "Prevention mode should grant a 3-damage shield"


def test_healing_salve_resolves_chosen_life_mode(all_cards):
    """mode_index=0 gains life; the default (no mode) matches this first mode."""
    salve = _get(all_cards, "Healing Salve")
    p1 = PlayerState(name="P1", hand=[salve], life=17)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Healing Salve", target_player_index=0, mode_index=0)

    assert result.supported
    assert p1.life == 20
    assert p1.damage_prevention_pool == 0


def test_healing_salve_prevention_shields_targeted_creature(all_cards):
    """Regression: the prevention mode aimed at a 1/1 creature must shield that
    creature, so a later Lightning Bolt is reduced and the creature survives."""
    salve = _get(all_cards, "Healing Salve")
    bolt = _get(all_cards, "Lightning Bolt")
    bear = _grizzly(all_cards)  # 2/2

    p1 = PlayerState(name="P1", hand=[salve, bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # Shield the opponent's creature, then bolt it.
    salved = game.cast_from_hand(
        0, "Healing Salve", target_player_index=1, target_permanent_index=0, mode_index=1
    )
    assert salved.supported
    assert p2.battlefield[0].damage_prevention_pool == 3

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    # 3 prevented from 3 damage → creature takes 0 and survives.
    assert len(p2.battlefield) == 1, "Prevention shield should keep the creature alive"
    assert p2.battlefield[0].damage_marked == 0
    assert p2.battlefield[0].damage_prevention_pool == 0


def test_psionic_blast_deals_four_to_target_and_two_to_caster(all_cards):
    blast = _get(all_cards, "Psionic Blast")

    p1 = PlayerState(name="P1", hand=[blast], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Psionic Blast", target_player_index=1)

    assert result.supported
    assert p2.life == 16
    assert p1.life == 18


def test_purelace_changes_target_to_white(all_cards):
    purelace = _get(all_cards, "Purelace")
    bear = _mk_card("Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Purelace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "W"


def test_purelace_targets_specific_permanent_by_index(all_cards):
    """Purelace with a target_permanent_index must recolor that specific permanent,
    not always the first one (targeting regression)."""
    purelace = _get(all_cards, "Purelace")
    bear1 = _mk_card("Bear Alpha", "Creature — Bear")
    bear2 = _mk_card("Bear Beta", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear1), Permanent(card=bear2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Purelace", target_player_index=1, target_permanent_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") is None, "first permanent must not be recolored"
    assert p2.battlefield[1].metadata.get("color_override") == "W", "second permanent must be recolored"


def test_purelace_fails_when_no_permanents_in_play(all_cards):
    """Purelace must fail validation when there are no valid targets on the battlefield."""
    purelace = _get(all_cards, "Purelace")

    p1 = PlayerState(name="P1", hand=[purelace])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Purelace", target_player_index=1)

    assert not result.supported


def test_red_elemental_blast_counters_blue_spell(all_cards):
    """Red Elemental Blast's first mode counters a blue spell on the stack."""
    reb = _get(all_cards, "Red Elemental Blast")
    recall = _get(all_cards, "Ancestral Recall")
    p1 = PlayerState(name="P1", hand=[reb])
    p2 = PlayerState(name="P2", hand=[recall])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
    result = game.cast_from_hand(0, "Red Elemental Blast", target_player_index=1)

    assert result.supported
    # The round-19 wording: the one _bin_spell_card line carries the verb.
    assert any("Ancestral Recall was countered by Red Elemental Blast" in line for line in game.log)
    assert not game.stack, "Stack should be empty after counterspell resolves"


def test_reverse_damage_classifies_supported(all_cards):
    reverse_damage = _get(all_cards, "Reverse Damage")
    assert classify_card(reverse_damage).supported


def test_righteousness_pumps_blocking_creature_plus_seven(all_cards):
    righteousness = _get(all_cards, "Righteousness")
    bear = _mk_card("Blocker", "Creature — Bear")
    attacker = Permanent(card=_grizzly(all_cards))
    attacker.metadata["summoning_sickness_turn"] = -99

    p1 = PlayerState(name="P1", hand=[righteousness], battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])
    # Righteousness can only target a *blocking* creature, so set up a block.
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 1
    game.declare_attackers(0, [0], 1)
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(1, {0: 0})

    result = game.cast_from_hand(0, "Righteousness", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert p2.battlefield[0].effective_power == 9
    assert p2.battlefield[0].effective_toughness == 9


def test_shatter_destroys_target_artifact(all_cards):
    shatter = _get(all_cards, "Shatter")
    sol_ring = _mk_card("Test Ring", "Artifact")

    p1 = PlayerState(name="P1", hand=[shatter])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=sol_ring)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shatter", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Test Ring"


def test_simulacrum_resolves_without_error(all_cards):
    simulacrum = _get(all_cards, "Simulacrum")
    grizzly = _get(all_cards, "Grizzly Bears")
    # Simulacrum targets a creature you control, so it needs one to be cast.
    p1 = PlayerState(name="P1", hand=[simulacrum], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Simulacrum", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Simulacrum" for c in p1.graveyard)


def test_swords_to_plowshares_resolves_without_error(all_cards):
    swords = _get(all_cards, "Swords to Plowshares")
    bear = _mk_creature_card("Test Bear", 2, 2)
    p1 = PlayerState(name="P1", hand=[swords])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Swords to Plowshares", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert not p1.hand
    assert any(c.name == "Swords to Plowshares" for c in p1.graveyard)


def test_terror_destroys_target_creature(all_cards):
    terror = _get(all_cards, "Terror")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Terror", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Test Bear"


def test_thoughtlace_changes_target_to_blue(all_cards):
    thoughtlace = _get(all_cards, "Thoughtlace")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[thoughtlace])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Thoughtlace", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].metadata.get("color_override") == "U"


def test_tunnel_destroys_target_wall(all_cards):
    tunnel = _get(all_cards, "Tunnel")
    wall = _get(all_cards, "Wall of Stone")

    p1 = PlayerState(name="P1", hand=[tunnel])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Tunnel", target_player_index=1)

    assert result.supported
    assert not p2.battlefield
    assert p2.graveyard[0].name == "Wall of Stone"


def test_twiddle_untaps_target_permanent(all_cards):
    twiddle = _get(all_cards, "Twiddle")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[twiddle])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear, tapped=True)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Twiddle", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].tapped is False


def test_spell_blast_counters_spell_with_matching_x(all_cards):
    blast = _get(all_cards, "Spell Blast")
    elemental = _get(all_cards, "Air Elemental")  # mana value 5
    p1 = PlayerState(name="P1", hand=[blast])
    p2 = PlayerState(name="P2", hand=[elemental])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Air Elemental")
    result = game.cast_from_hand(0, "Spell Blast", target_player_index=1, x_value=5)

    assert result.supported
    # The round-19 wording: the one _bin_spell_card line carries the verb.
    assert any("Air Elemental was countered by Spell Blast" in line for line in game.log)
    assert not game.stack
    assert not p2.battlefield


def test_spell_blast_does_not_counter_spell_with_wrong_x(all_cards):
    blast = _get(all_cards, "Spell Blast")
    elemental = _get(all_cards, "Air Elemental")  # mana value 5
    p1 = PlayerState(name="P1", hand=[blast])
    p2 = PlayerState(name="P2", hand=[elemental])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Air Elemental")
    result = game.cast_from_hand(0, "Spell Blast", target_player_index=1, x_value=2)

    assert result.supported
    assert not any("Spell Blast countered" in line for line in game.log)
    # The Air Elemental still resolves
    assert any(p.card.name == "Air Elemental" for p in p2.battlefield)
