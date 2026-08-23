"""Per-card tests for Limited Edition Alpha's enchantment cards.

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
from engine.land_types import change_land_type
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


def test_feedback_oracle_supported(all_cards):
    feedback = _get(all_cards, "Feedback")
    program = compile_card_oracle(feedback)
    assert program.supported
    # Should expose an "at the beginning" triggered ability
    assert any(t.condition.trigger == "at" for t in program.triggered_abilities)


def test_feedback_deals_damage_at_enchanted_enchantment_upkeep(all_cards):
    feedback = _get(all_cards, "Feedback")
    bad_moon = _get(all_cards, "Bad Moon")

    # P1 will cast Feedback enchanting P2's Bad Moon
    p1 = PlayerState(name="P1", hand=[feedback])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)], life=20)
    game = Game(players=[p1, p2])

    # Cast Feedback targeting the enchantment on P2's battlefield
    result = game.cast_from_hand(0, "Feedback", target_player_index=1, target_permanent_index=0)
    assert result.supported

    # Resolve upkeep for P2 (controller of the enchanted enchantment)
    game.resolve_upkeep(1)

    # Feedback should have dealt 1 damage to P2
    assert p2.life == 19


def test_fear_enchanted_creature_unblockable_by_non_artifact_non_black(all_cards):
    fear = _get(all_cards, "Fear")
    grizzly = _get(all_cards, "Grizzly Bears")

    # Controller casts Fear on their creature
    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Fear", target_player_index=0, target_permanent_index=0)
    assert cast_result.supported

    # Attack with the enchanted creature
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)

    # Non-artifact non-black Grizzly should not be able to block creature with fear
    assert blockers == {}


def test_fear_cannot_be_cast_without_target(all_cards):
    """Regression: Fear (an Aura) was cast without a target and resolved unattached.

    All Aura spells require a target chosen at cast time (Rules 115.1b, 601.2c).
    """
    fear = _get(all_cards, "Fear")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fear", target_player_index=0)

    assert not result.supported
    assert "requires a target" in result.details
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)
    # No creature was silently enchanted
    assert all(perm.metadata.get("attached_aura") is None for perm in p1.battlefield)
    assert all(perm.metadata.get("attached_aura") is None for perm in p2.battlefield)


def test_fear_cannot_be_cast_targeting_a_land(all_cards):
    """Regression companion: Fear can only target a creature, never a land."""
    fear = _get(all_cards, "Fear")
    swamp = _get(all_cards, "Swamp")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=swamp), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Index 0 is the Swamp — illegal target for "Enchant creature"
    result = game.cast_from_hand(0, "Fear", target_player_index=0, target_permanent_index=0)

    assert not result.supported
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)


def test_firebreathing_pumps_enchanted_creature(all_cards):
    fire = _get(all_cards, "Firebreathing")
    grizzly = _get(all_cards, "Grizzly Bears")

    # Place a creature and the aura on the battlefield and attach the aura
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=grizzly), Permanent(card=fire)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Manually attach the aura to the creature (simulates casting and attaching)
    aura_perm = p1.battlefield[1]
    creature_perm = p1.battlefield[0]
    aura_perm.metadata["attached_to"] = creature_perm
    creature_perm.metadata["attached_aura"] = aura_perm

    # Activate the aura's ability (no mana enforcement required for this test)
    result = game.activate_permanent_ability(0, "Firebreathing")

    assert result.supported
    # The enchanted creature should have received the +1 power bonus
    assert creature_perm.power_bonus >= 1


def test_flight_grants_flying(all_cards):
    flight = _get(all_cards, "Flight")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[flight], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Flight", target_player_index=0, target_permanent_index=0)
    assert result.supported

    creature_perm = p1.battlefield[0]
    assert (
        creature_perm.has_keyword("flying")
        or creature_perm.has_keyword("flying")
        or "Flying" in creature_perm.card.keywords
    )


def test_bad_moon_applies_global_black_creature_buff(all_cards):
    bad_moon = _get(all_cards, "Bad Moon")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", hand=[bad_moon])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(card=black_knight))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bad Moon")

    assert result.supported
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


def test_animate_dead_reanimates_creature(all_cards):
    animate_dead = _get(all_cards, "Animate Dead")
    dead_creature = _mk_card("Dead Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[animate_dead], graveyard=[dead_creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)

    assert result.supported
    # Creature should be returned to the battlefield under caster's control
    assert any(perm.card.name == "Dead Bear" for perm in p1.battlefield)
    # The Animate Dead aura itself should be on the battlefield
    assert any(perm.card.name == "Animate Dead" for perm in p1.battlefield)


def test_animate_artifact_makes_artifact_into_creature(all_cards):
    animate = _get(all_cards, "Animate Artifact")
    # Create a test artifact with mana value 3
    relic = _mk_card("Test Relic", "Artifact")
    relic_def = CardDefinition(
        name=relic.name,
        mana_cost="{3}",
        cmc=3.0,
        type_line=relic.type_line,
        oracle_text=relic.oracle_text,
        colors=relic.colors,
        color_identity=relic.color_identity,
        keywords=relic.keywords,
        produced_mana=relic.produced_mana,
        raw={**relic.raw},
    )

    p1 = PlayerState(name="P1", hand=[animate])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=relic_def)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    # Target artifact should become an artifact creature with power/toughness equal to its mana value
    perm = p2.battlefield[0]
    # Animation is a CR 613 layer-4 effect owned by the Aura, so the printed
    # card is untouched — ask whether the permanent *is* a creature.
    assert perm.is_creature is True
    assert perm.effective_power == 3
    assert perm.effective_toughness == 3
    # The Aura should be on the caster's battlefield and attached
    assert any(a.card.name == "Animate Artifact" for a in p1.battlefield)
    aura = next(a for a in p1.battlefield if a.card.name == "Animate Artifact")
    assert aura.metadata.get("attached_to") is perm


def test_orcish_oriflamme_applies_power_bonus(all_cards):
    oriflamme = _get(all_cards, "Orcish Oriflamme")
    creature = _mk_card("Attacker", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[oriflamme], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Orcish Oriflamme", target_player_index=0)

    assert result.supported
    attacker = p1.battlefield[0]
    # "Attacking creatures you control get +1/+0": no bonus while idle.
    assert attacker.effective_power == 2
    # The bonus applies only while the creature is actually attacking.
    attacker.attacking = True
    game._refresh_dynamic_creatures()
    assert attacker.effective_power == 3
    attacker.attacking = False
    game._refresh_dynamic_creatures()
    assert attacker.effective_power == 2


def test_aspect_of_wolf_applies_half_forest_buff(all_cards):
    aspect = _get(all_cards, "Aspect of Wolf")
    forest = _get(all_cards, "Forest")
    creature = _mk_card("Test Bear", "Creature — Bear")

    # Set up controller with 3 Forests -> floor(3/2)=1, ceil(3/2)=2 -> +1/+2
    p1 = PlayerState(
        name="P1",
        hand=[aspect],
        battlefield=[Permanent(card=creature), Permanent(card=forest), Permanent(card=forest), Permanent(card=forest)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Aspect of Wolf", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # Creature is the first permanent on battlefield
    assert p1.battlefield[0].effective_power == 3
    assert p1.battlefield[0].effective_toughness == 4


def test_stasis_skips_untap_step(all_cards):
    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island, tapped=True)])
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 0
    assert p2.battlefield[0].tapped is True


def test_stasis_upkeep_prompts_human_player(all_cards):
    """Regression: Stasis must pause for a pay/sacrifice choice via real turn-end flow."""
    from web.app import _end_turn

    stasis = _get(all_cards, "Stasis")
    island = _get(all_cards, "Island")

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": 77},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p1 = session.game.players[0]
    p1.battlefield = [Permanent(card=stasis), Permanent(card=island)]
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    p1.hand = []

    # End P0's first turn → starts P1's turn.
    _end_turn(session, allow_manual_cleanup_selection=False)
    # Stasis must NOT have fired on the opponent's upkeep.
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must survive opponent's upkeep (upkeep_self should not fire on opponent's turn)"

    # End P1's turn → starts P0's second turn, which should defer at upkeep.
    _end_turn(session, allow_manual_cleanup_selection=False)

    assert session.game.current_step == "upkeep", "game must be paused at upkeep step"
    assert session.upkeep_pay_choices, "upkeep_pay_choices must be populated"
    assert any(c["card_name"] == "Stasis" for c in session.upkeep_pay_choices)
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must not be auto-sacrificed before player decides"

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    upkeep_pay = state["upkeep_pay"]
    assert upkeep_pay is not None, "upkeep_pay info must be present for the human player"
    assert any(c["card_name"] == "Stasis" for c in upkeep_pay["choices"])

    # Tap Island to add {U}, then pay.
    tap_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "tap", "permanent_name": "Island"},
    )
    assert tap_resp.status_code == 200

    pay_resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "pay_upkeep", "card_name": "Stasis"},
    )
    assert pay_resp.status_code == 200
    assert any(p.card.name == "Stasis" for p in p1.battlefield), \
        "Stasis must remain on battlefield after paying"
    assert session.game.current_turn_phase == "precombat_main", \
        "game should have advanced to main phase after paying"


def test_stasis_upkeep_engine_get_triggers(all_cards):
    """get_upkeep_pay_triggers returns Stasis as a pending choice."""
    stasis = _get(all_cards, "Stasis")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=stasis)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    triggers = game.get_upkeep_pay_triggers(0)

    assert len(triggers) == 1
    assert triggers[0]["card_name"] == "Stasis"
    assert "U" in triggers[0]["mana"] or triggers[0]["mana"]  # has a mana cost
    assert triggers[0]["kind"] == "upkeep_pay_or_sacrifice_enchantment"


def test_smoke_limits_creature_untap(all_cards):
    smoke = _get(all_cards, "Smoke")
    c1 = _mk_card("Bear A", "Creature — Bear")
    c2 = _mk_card("Bear B", "Creature — Bear")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=smoke)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=c1, tapped=True), Permanent(card=c2, tapped=True)],
    )
    game = Game(players=[p1, p2])

    untapped = game.resolve_untap_step(1)

    assert untapped == 1
    assert sum(1 for perm in p2.battlefield if not perm.tapped) == 1


def test_mana_flare_adds_extra_mana(all_cards):
    mana_flare = _get(all_cards, "Mana Flare")
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare), Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(0, "Island")

    assert ok
    assert p1.mana_pool["U"] == 2


def test_animate_wall_allows_wall_to_attack(all_cards):
    animate_wall = _get(all_cards, "Animate Wall")
    wall = _get(all_cards, "Wall of Stone")
    p1 = PlayerState(name="P1", hand=[animate_wall])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Animate Wall", target_player_index=1, target_permanent_index=0)

    assert result.supported
    wall_perm = p2.battlefield[0]
    assert game.can_attack(wall_perm, defending_player_index=0) is True


def test_castle_buffs_untapped_creatures_toughness(all_cards):
    castle = _get(all_cards, "Castle")
    bear = _mk_card("Guard", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[castle], battlefield=[Permanent(card=bear, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Castle", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].effective_toughness >= 4


def test_conversion_sacrifices_on_upkeep_without_white_mana(all_cards):
    conversion = _get(all_cards, "Conversion")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=conversion)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not p1.battlefield
    assert any(card.name == "Conversion" for card in p1.graveyard)


def test_gloom_tax_log_on_white_spell(all_cards):
    gloom = _get(all_cards, "Gloom")
    white_spell = _mk_card("White Test", "Sorcery", "Target player loses 3 life.", colors=("W",))
    p1 = PlayerState(name="P1", hand=[gloom])
    p2 = PlayerState(name="P2", hand=[white_spell], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Gloom", target_player_index=1)
    result = game.cast_from_hand(1, "White Test", target_player_index=0)

    assert result.supported
    assert any("taxed by gloom" in line.lower() for line in game.log)


def test_living_lands_cast_from_hand_animates_forests(all_cards):
    living = _get(all_cards, "Living Lands")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[living], battlefield=[Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Living Lands", target_player_index=1)

    assert result.supported
    game._refresh_dynamic_creatures()
    assert p1.battlefield[0].metadata.get("land_animated") is True
    assert p1.battlefield[0].effective_power == 1
    assert p1.battlefield[0].effective_toughness == 1


def test_raging_river_casts_as_supported_permanent(all_cards):
    river = _get(all_cards, "Raging River")
    p1 = PlayerState(name="P1", hand=[river])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Raging River", target_player_index=1)

    assert result.supported
    assert any(perm.card.name == "Raging River" for perm in p1.battlefield)


def test_copy_artifact_copies_artifact_on_entry(all_cards):
    copy_artifact = _get(all_cards, "Copy Artifact")
    lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(name="P1", hand=[copy_artifact], battlefield=[Permanent(card=lotus)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Copy Artifact", target_player_index=1)

    assert result.supported
    # Copy Artifact becomes a copy of the artifact (its name/types/abilities),
    # except it's also an Enchantment. The copy is an overlay: the underlying
    # card stays Copy Artifact so it reverts when it changes zones.
    perm = next(perm for perm in p1.battlefield if perm.copied_from == "Black Lotus")
    assert perm.effective_card.name == "Black Lotus"
    assert "enchantment" in perm.effective_card.type_line.lower()
    assert perm.card.name == "Copy Artifact"


def test_holy_strength_gives_static_buff_to_enchanted_creature(all_cards):
    holy_strength = _get(all_cards, "Holy Strength")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[holy_strength])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Holy Strength", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 3
    assert perm.effective_toughness == 4


def test_holy_armor_gives_static_toughness_and_activates_for_more(all_cards):
    holy_armor = _get(all_cards, "Holy Armor")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[holy_armor], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Holy Armor", target_player_index=0, target_permanent_index=0)

    assert result.supported
    creature_perm = p1.battlefield[0]
    assert creature_perm.effective_toughness == 4

    aura_perm = next(p for p in p1.battlefield if p.card.name == "Holy Armor")
    aura_perm.metadata["attached_to"] = creature_perm
    creature_perm.metadata["attached_aura"] = aura_perm

    before_t = creature_perm.effective_toughness
    activate_result = game.activate_permanent_ability(0, "Holy Armor", target_player_index=0)

    assert activate_result.supported
    assert creature_perm.effective_toughness == before_t + 1


def test_paralyze_taps_creature_on_enter_and_prevents_untap(all_cards):
    paralyze = _get(all_cards, "Paralyze")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[paralyze])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Paralyze", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.tapped is True
    game.resolve_untap_step(1)
    assert creature_perm.tapped is True


def test_fastbond_allows_extra_land_and_deals_damage():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 92334,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})

    session = store.get(sid)
    fastbond = _mk_card(
        name="Fastbond",
        mana_cost="{G}",
        type_line="Enchantment",
        oracle_text=(
            "You may play any number of lands on each of your turns.\n"
            "Whenever you play a land, if it wasn't the first land you played this turn, "
            "this enchantment deals 1 damage to you."
        ),
    )
    plains_a = _mk_card(
        name="Plains A",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    plains_b = _mk_card(
        name="Plains B",
        mana_cost="",
        type_line="Basic Land - Plains",
        oracle_text="{T}: Add {W}.",
        produced_mana=("W",),
    )
    session.game.players[0].hand = [fastbond, plains_a, plains_b]
    session.game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 1, "C": 0}
    session.game.players[0].life = 20

    cast_fastbond = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Fastbond", "target_seat": 0},
    )
    assert cast_fastbond.status_code == 200
    _resolve_top_stack(sid, 0)

    first_land = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains A", "target_seat": 0},
    )
    assert first_land.status_code == 200

    second_land_same_turn = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Plains B", "target_seat": 0},
    )
    assert second_land_same_turn.status_code == 200
    assert store.get(sid).game.players[0].life == 19


def test_lance_grants_first_strike_to_enchanted_creature(all_cards):
    """Lance aura gives enchanted creature first strike."""
    lance = _get(all_cards, "Lance")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[lance], battlefield=[bear_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Lance",
        target_player_index=0,
        target_permanent_index=0,
    )
    assert result.supported
    enchanted = p1.battlefield[0]
    assert enchanted.has_keyword("first strike") is True, \
        "Enchanted creature should have gains_first_strike=True in metadata"


def test_regeneration_aura_activated_ability_grants_regen_shield(all_cards):
    """Regeneration enchants a creature; its activated ability grants the enchanted creature a regeneration shield."""
    regeneration = _get(all_cards, "Regeneration")
    bear = _mk_creature_card("Test Bear", power=2, toughness=2)

    bear_perm = Permanent(card=bear)
    p1 = PlayerState(name="P1", hand=[regeneration], battlefield=[bear_perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Cast Regeneration enchanting the bear
    cast_result = game.cast_from_hand(
        0, "Regeneration",
        target_player_index=0,
        target_permanent_index=0,
    )
    assert cast_result.supported

    # Activate Regeneration's ability to grant the bear a regeneration shield
    activate_result = game.activate_permanent_ability(
        0, "Regeneration",
        target_player_index=0,
    )
    assert activate_result.supported, \
        "Regeneration's activated ability should be supported"

    # The enchanted bear should now have a regeneration shield
    assert bear_perm.regeneration_shield >= 1, \
        "Enchanted creature should have regeneration_shield >= 1 after activating Regeneration"


def test_black_ward_grants_protection_from_black(all_cards):
    ward = _get(all_cards, "Black Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Black Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    # Protection is read off the attached Aura (engine/auras.py), not a flag
    # stamped on the creature, so this asks what the creature is protected
    # from rather than how the engine records it.
    assert "B" in game._protection_colors(creature_perm)


def test_burrowing_grants_mountainwalk_to_enchanted_creature(all_cards):
    burrowing = _get(all_cards, "Burrowing")
    creature = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[burrowing])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Burrowing", target_player_index=1, target_permanent_index=0)

    assert result.supported
    bear_perm = p2.battlefield[0]
    assert bear_perm.metadata.get("attached_aura") is not None
    # The grant is a CR 613 layer-6 effect owned by the Aura, not a flag
    # stamped on the creature, so this asks what the creature *has* rather than
    # how the engine happens to record it.
    assert game._has_keyword(bear_perm, "mountainwalk") is True
    assert any("mountainwalk" in line.lower() for line in game.log)


def test_circle_of_protection_green_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Green")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Green", target_player_index=0)

    assert result.supported
    assert p1.color_prevention_shields == ["G"]


def test_circle_of_protection_red_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: Red")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: Red", target_player_index=0)

    assert result.supported
    assert p1.color_prevention_shields == ["R"]


def test_circle_of_protection_white_activation_sets_prevention(all_cards):
    cop = _get(all_cards, "Circle of Protection: White")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=cop)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Circle of Protection: White", target_player_index=0)

    assert result.supported
    assert p1.color_prevention_shields == ["W"]


def test_consecrate_land_grants_indestructible_to_enchanted_land(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)

    assert result.supported
    land_perm = p1.battlefield[0]
    # Both grants derive from the attached Aura (engine/auras.py), so these ask
    # what the land *is* rather than which flags were stamped on it.
    assert game._is_indestructible(land_perm) is True
    assert game._cant_be_enchanted(land_perm) is True
    aura_perm = next(p for p in p1.battlefield if p.card.name == "Consecrate Land")
    assert aura_perm.metadata.get("attached_to") is land_perm


def test_consecrate_land_indestructible_survives_destroy(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    stone_rain = _get(all_cards, "Stone Rain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2", hand=[stone_rain])
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported

    # The enchanted Plains has indestructible: Stone Rain can target it but can't destroy it.
    result = game.cast_from_hand(1, "Stone Rain", target_player_index=0, target_permanent_index=0)
    assert result.supported
    assert any(p.card.name == "Plains" for p in p1.battlefield)
    assert not any(c.name == "Plains" for c in p1.graveyard)


def test_consecrate_land_blocks_other_auras(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    plains = _get(all_cards, "Plains")

    # Two copies of Consecrate Land in hand; the second can't enchant the protected land.
    p1 = PlayerState(name="P1", hand=[consecrate, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    second = game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)
    assert not second.supported
    assert "can't be enchanted" in second.details.lower()


def test_consecrate_land_grant_ends_when_aura_leaves(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    disenchant = _get(all_cards, "Disenchant")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2", hand=[disenchant])
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    land = p1.battlefield[0]
    assert game._is_indestructible(land) is True
    assert game._cant_be_enchanted(land) is True

    # Destroying the Aura ends both continuous grants on the land — by the Aura
    # no longer being attached, not by anything clearing what it wrote.
    result = game.cast_from_hand(1, "Disenchant", target_player_index=0, target_permanent_index=1)
    assert result.supported
    assert game._is_indestructible(land) is False
    assert game._cant_be_enchanted(land) is False


def test_consecrate_land_graveyards_existing_other_auras_on_enter(all_cards):
    consecrate = _get(all_cards, "Consecrate Land")
    wild_growth = _get(all_cards, "Wild Growth")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[wild_growth, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # The land is already enchanted by another Aura.
    assert game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0).supported
    assert any(p.card.name == "Wild Growth" for p in p1.battlefield)

    # Consecrate Land entering attached to it sends the other Aura to the graveyard.
    assert game.cast_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0).supported
    assert not any(p.card.name == "Wild Growth" for p in p1.battlefield)
    assert any(c.name == "Wild Growth" for c in p1.graveyard)
    assert any(p.card.name == "Consecrate Land" for p in p1.battlefield)


def test_consecrate_land_graveyards_other_auras_via_priority_resolution(all_cards):
    # Regression: in real play the Aura resolves through the priority-pass path,
    # which must check state-based actions afterward (the immediate cast_from_hand
    # path always did, masking the bug).
    consecrate = _get(all_cards, "Consecrate Land")
    wild_growth = _get(all_cards, "Wild Growth")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[wild_growth, consecrate], battlefield=[Permanent(card=plains)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0).supported

    # Resolve Consecrate Land via a priority window rather than cast_from_hand.
    game.queue_from_hand(0, "Consecrate Land", target_player_index=0, target_permanent_index=0)
    game.start_priority_window(0)
    game.pass_priority(0)
    game.pass_priority(1)

    assert not any(p.card.name == "Wild Growth" for p in p1.battlefield)
    assert any(c.name == "Wild Growth" for c in p1.graveyard)
    assert any(p.card.name == "Consecrate Land" for p in p1.battlefield)


def test_control_magic_steals_opponent_creature(all_cards):
    control_magic = _get(all_cards, "Control Magic")
    creature = _mk_card("Target Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[control_magic])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Control Magic", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert any(p.card.name == "Target Bear" for p in p1.battlefield)
    assert not any(p.card.name == "Target Bear" for p in p2.battlefield)
    aura_perm = next((p for p in p1.battlefield if p.card.name == "Control Magic"), None)
    assert aura_perm is not None
    stolen = next(p for p in p1.battlefield if p.card.name == "Target Bear")
    assert aura_perm.metadata.get("attached_to") is stolen


def test_crusade_buffs_white_creatures(all_cards):
    crusade = _get(all_cards, "Crusade")
    white_knight = _get(all_cards, "White Knight")

    p1 = PlayerState(name="P1", hand=[crusade])
    p2 = PlayerState(name="P2")
    p1.battlefield.append(Permanent(card=white_knight))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Crusade")

    assert result.supported
    knight_perm = p1.battlefield[0]
    assert knight_perm.effective_power == 3
    assert knight_perm.effective_toughness == 3


def test_cursed_land_deals_upkeep_damage_to_land_controller(all_cards):
    cursed_land = _get(all_cards, "Cursed Land")
    forest = _mk_card("Forest", "Basic Land - Forest")

    p1 = PlayerState(name="P1", hand=[cursed_land], life=20)
    p2 = PlayerState(name="P2", life=20)
    p2.battlefield.append(Permanent(card=forest))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Cursed Land", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.resolve_upkeep(1)

    assert p2.life == 19


def test_creature_bond_deals_damage_when_enchanted_creature_dies(all_cards):
    creature_bond = _get(all_cards, "Creature Bond")
    bear = _mk_card("Test Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[creature_bond], life=20)
    p2 = PlayerState(name="P2", life=20)
    p2.battlefield.append(Permanent(card=bear))
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Creature Bond", target_player_index=1, target_permanent_index=0)
    assert result.supported

    # Destroy the enchanted creature; P2 (controller) should take damage equal to toughness (2)
    game._destroy_target_permanent(p2, type_filter="creature")
    # The Aura's death trigger goes on the stack and resolves off it (CR 603.3).
    game.resolve_stack()

    assert p2.life == 18


def test_death_ward_grants_regeneration_shield(all_cards):
    # Death Ward: "Regenerate target creature." — grants a regeneration shield to a target creature
    death_ward = _get(all_cards, "Death Ward")
    bear = _mk_card("Test Bear", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[death_ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Death Ward", target_player_index=1)

    assert result.supported
    assert p2.battlefield[0].regeneration_shield >= 1


def test_deathgrip_counters_green_spell_on_stack(all_cards):
    # Deathgrip: "{B}{B}: Counter target green spell."
    deathgrip = _get(all_cards, "Deathgrip")
    giant_growth = _get(all_cards, "Giant Growth")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=deathgrip)])
    p2 = PlayerState(name="P2", hand=[giant_growth], battlefield=[Permanent(card=_get(all_cards, "Llanowar Elves"))])
    game = Game(players=[p1, p2])

    # Queue green spell on stack
    game.queue_from_hand(1, "Giant Growth", target_player_index=1)
    assert game.stack

    # Activate Deathgrip to counter it
    result = game.activate_permanent_ability(0, "Deathgrip")

    assert result.supported
    assert not game.stack
    assert any(card.name == "Giant Growth" for card in p2.graveyard)


def test_regeneration_shield_saves_creature_from_lethal_damage(all_cards):
    # A regenerated creature dealt lethal direct damage (e.g. Lightning Bolt) is
    # destroyed as a state-based action, which the shield replaces: it stays on the
    # battlefield tapped with its damage cleared, rather than going to the graveyard.
    wall = _get(all_cards, "Wall of Bone")  # 0/4
    bolt = _get(all_cards, "Lightning Bolt")  # deals 3

    p1 = PlayerState(name="P1", hand=[bolt, bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=wall, regeneration_shield=1)])
    game = Game(players=[p1, p2])

    # First bolt: 3 damage on a 0/4 — not lethal, survives.
    r1 = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert r1.supported
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].damage_marked == 3

    # Second bolt: 6 total >= toughness 4 — lethal. Regeneration replaces the
    # destruction: shield consumed, damage cleared, creature tapped, still on battlefield.
    r2 = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    assert r2.supported
    assert len(p2.battlefield) == 1, "Regenerated wall should survive lethal damage"
    assert p2.battlefield[0].card.name == "Wall of Bone"
    assert p2.battlefield[0].regeneration_shield == 0
    assert p2.battlefield[0].damage_marked == 0
    assert p2.battlefield[0].tapped is True
    assert not any(c.name == "Wall of Bone" for c in p2.graveyard)


def test_earthbind_damages_flying_creature_and_strips_flying(all_cards):
    earthbind = _get(all_cards, "Earthbind")
    serra = _get(all_cards, "Serra Angel")
    p1 = PlayerState(name="P1", hand=[earthbind])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=serra)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthbind", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.damage_marked == 2
    assert creature_perm.has_keyword("flying") is False


def test_earthbind_no_damage_on_non_flying_creature(all_cards):
    earthbind = _get(all_cards, "Earthbind")
    bear = _get(all_cards, "Grizzly Bears")
    p1 = PlayerState(name="P1", hand=[earthbind])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Earthbind", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    assert creature_perm.damage_marked == 0
    # Earthbind only acts on a flier; the creature is untouched and still has
    # no flying to strip.
    assert creature_perm.has_keyword("flying") is False


def test_evil_presence_makes_land_a_swamp(all_cards):
    evil_presence = _get(all_cards, "Evil Presence")
    mountain = _get(all_cards, "Mountain")
    p1 = PlayerState(name="P1", hand=[evil_presence])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Evil Presence", target_player_index=1, target_permanent_index=0)

    assert result.supported
    land_perm = p2.battlefield[0]
    assert land_perm.changed_land_types == ("swamp",)


def test_farmstead_grants_life_at_upkeep_when_paid(all_cards):
    farmstead = _get(all_cards, "Farmstead")
    plains = _get(all_cards, "Plains")
    farm_perm = Permanent(card=farmstead)
    plains_perm = Permanent(card=plains)
    # Attach Farmstead to Plains manually (simulating resolved cast)
    farm_perm.metadata["attached_to"] = plains_perm
    plains_perm.metadata["attached_aura"] = farm_perm
    p1 = PlayerState(name="P1", life=20, mana_pool={"W": 2},
                     battlefield=[plains_perm, farm_perm])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    # Player paid {W}{W} and gained 1 life
    assert p1.life == 21
    assert p1.mana_pool.get("W", 0) == 0


def test_farmstead_no_life_gain_without_mana(all_cards):
    farmstead = _get(all_cards, "Farmstead")
    plains = _get(all_cards, "Plains")
    farm_perm = Permanent(card=farmstead)
    plains_perm = Permanent(card=plains)
    farm_perm.metadata["attached_to"] = plains_perm
    plains_perm.metadata["attached_aura"] = farm_perm
    p1 = PlayerState(name="P1", life=20, battlefield=[plains_perm, farm_perm])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    # No mana to pay → no life gain
    assert p1.life == 20


def test_green_ward_grants_protection_from_green(all_cards):
    ward = _get(all_cards, "Green Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)

    p1 = PlayerState(name="P1", hand=[ward], battlefield=[Permanent(card=creature)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Green Ward", target_player_index=0, target_permanent_index=0)

    assert result.supported
    creature_perm = p1.battlefield[0]
    # Protection is read off the attached Aura (engine/auras.py), not a flag
    # stamped on the creature, so this asks what the creature is protected
    # from rather than how the engine records it.
    assert "G" in game._protection_colors(creature_perm)


def test_instill_energy_grants_haste_to_enchanted_creature(all_cards):
    instill = _get(all_cards, "Instill Energy")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[instill], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    grizzly_perm = p1.battlefield[0]
    grizzly_perm.metadata["summoning_sickness_turn"] = game.turn

    result = game.cast_from_hand(0, "Instill Energy", target_player_index=0, target_permanent_index=0)
    assert result.supported

    # The creature should be able to attack despite summoning sickness due to Instill Energy's haste grant
    assert game.can_attack(grizzly_perm, defending_player_index=1) is True


def test_instill_energy_untap_ability(all_cards):
    instill = _get(all_cards, "Instill Energy")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[instill], battlefield=[Permanent(card=grizzly, tapped=True)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Instill Energy", target_player_index=0, target_permanent_index=0)
    assert result.supported

    grizzly_perm = p1.battlefield[0]
    assert grizzly_perm.tapped is True

    activate_result = game.activate_permanent_ability(0, "Instill Energy", target_player_index=0)
    assert activate_result.supported
    assert grizzly_perm.tapped is False


def test_invisibility_only_blockable_by_walls(all_cards):
    invis = _get(all_cards, "Invisibility")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[invis], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Invisibility", target_player_index=0, target_permanent_index=0)
    assert cast_result.supported

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)
    # Non-wall Grizzly Bears should not be able to block a creature with Invisibility
    assert blockers == {}


def test_karma_deals_damage_based_on_swamps(all_cards):
    karma = _get(all_cards, "Karma")
    swamp = _get(all_cards, "Swamp")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=karma)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=swamp), Permanent(card=swamp)], life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 18


def test_kudzu_destroys_land_when_tapped(all_cards):
    kudzu = _get(all_cards, "Kudzu")
    plains = _get(all_cards, "Plains")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", hand=[kudzu])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains), Permanent(card=forest)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Kudzu", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.tap_land_for_mana(1, "Plains")

    assert not any(perm.card.name == "Plains" for perm in p2.battlefield)
    kudzu_perm = next((perm for perm in p1.battlefield if perm.card.name == "Kudzu"), None)
    assert kudzu_perm is not None
    assert kudzu_perm.metadata.get("attached_to") is not None


def test_island_sanctuary_grants_protection_after_skipping_draw(all_cards):
    sanctuary = _get(all_cards, "Island Sanctuary")
    grizzly = _get(all_cards, "Grizzly Bears")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[sanctuary], library=[island])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])
    game.turn = 2  # an ordinary turn - turn 1 skips the draw (CR 103.8a)

    result = game.cast_from_hand(0, "Island Sanctuary", target_player_index=0)
    assert result.supported

    # Resolve draw step — Island Sanctuary causes P1 to skip draw for protection
    drawn = game.resolve_draw_step(0)
    assert drawn == 0

    # Non-flying, non-islandwalk Grizzly Bears cannot attack P1
    assert game.can_attack(p2.battlefield[0], defending_player_index=0) is False


def test_lich_loses_life_equal_to_life_total_on_entry(all_cards):
    lich = _get(all_cards, "Lich")
    p1 = PlayerState(name="P1", hand=[lich], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lich")

    assert result.supported
    assert any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert p1.life == 0


def test_lich_controller_does_not_lose_at_zero_or_less_life(all_cards):
    """'You don't lose the game for having 0 or less life.'"""
    lich = _get(all_cards, "Lich")
    p1 = PlayerState(name="P1", hand=[lich], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Lich")
    assert p1.life == 0

    game.check_state_based_actions()
    assert p1.lost is False

    p1.life = -5
    game.check_state_based_actions()
    assert p1.lost is False


def test_lich_life_gain_draws_cards_instead(all_cards):
    """'If you would gain life, draw that many cards instead.'"""
    lich = _get(all_cards, "Lich")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=lich)],
        library=[forest, forest, forest, forest],
        life=5,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game._gain_life(p1, 3)

    assert p1.life == 5  # life total unchanged
    assert len(p1.hand) == 3  # drew 3 cards instead
    assert len(p1.library) == 1


def test_lich_life_gain_from_spell_draws_cards_instead(all_cards):
    """The replacement applies to life gained from resolving spells too."""
    lich = _get(all_cards, "Lich")
    stream = _get(all_cards, "Stream of Life")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(
        name="P1",
        hand=[stream],
        battlefield=[Permanent(card=lich)],
        library=[forest, forest, forest],
        life=5,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Stream of Life", target_player_index=0, x_value=2)

    assert result.supported
    assert p1.life == 5
    assert len(p1.hand) == 2


def test_lich_damage_without_enough_permanents_loses_the_game(all_cards):
    """'If you can't [sacrifice that many], you lose the game.'"""
    lich = _get(all_cards, "Lich")
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lich)], life=10)
    p2 = PlayerState(name="P2", hand=[bolt])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)

    assert result.supported
    assert p1.lost is True


def test_lich_put_into_graveyard_from_battlefield_loses_the_game(all_cards):
    """'When this enchantment is put into a graveyard from the battlefield, you lose the game.'"""
    lich = _get(all_cards, "Lich")
    disenchant = _get(all_cards, "Disenchant")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lich)], life=10)
    p2 = PlayerState(name="P2", hand=[disenchant])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Disenchant", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert not any(perm.card.name == "Lich" for perm in p1.battlefield)
    assert any(card.name == "Lich" for card in p1.graveyard)
    assert p1.lost is True
    assert game.get_winner() is p2


def test_lifeforce_counters_black_spell(all_cards):
    lifeforce = _get(all_cards, "Lifeforce")
    black_knight = _get(all_cards, "Black Knight")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifeforce)])
    p2 = PlayerState(name="P2", hand=[black_knight])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Black Knight")
    result = game.activate_permanent_ability(0, "Lifeforce", target_player_index=0)

    assert result.supported
    assert not game.stack
    assert any(card.name == "Black Knight" for card in p2.graveyard)


def test_lifeforce_requires_black_spell_on_stack(all_cards):
    lifeforce = _get(all_cards, "Lifeforce")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifeforce)])
    p1.mana_pool["G"] = 2
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # No black spell on stack — activation should be rejected
    result = game.queue_permanent_ability(0, "Lifeforce")
    assert not result.supported
    assert p1.mana_pool.get("G", 0) == 2  # mana not spent


def test_lifetap_gains_life_when_opponent_forest_tapped(all_cards):
    lifetap = _get(all_cards, "Lifetap")
    forest = _get(all_cards, "Forest")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifetap)], life=20)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest)])
    game = Game(players=[p1, p2])

    ok = game.tap_land_for_mana(1, "Forest")

    assert ok
    # The trigger uses the stack (CR 605.5a — it gains life, so it is not a
    # mana ability), so the life arrives when it resolves, not at fire time.
    assert p1.life == 20
    game.resolve_stack()
    assert p1.life == 21


def test_lifetap_gains_life_when_an_opponents_forest_attacks(all_cards):
    """"Becomes tapped" is the event, not "tapped for mana".

    An animated Forest (Living Lands) tapping to attack is the same transition,
    and the trigger has to see it. This is a *different route into
    Game.become_tapped* than the mana one the card's other tests use — the bug
    the choke point was built for was exactly a trigger wired into one route.
    """
    lifetap = _get(all_cards, "Lifetap")
    living_lands = _get(all_cards, "Living Lands")
    forest = Permanent(card=_get(all_cards, "Forest"))

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifetap)], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=living_lands), forest], life=20
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    forest.metadata["summoning_sickness_turn"] = -99
    game._refresh_dynamic_creatures()
    assert forest.is_creature, "Living Lands must animate the Forest for this route"

    declared, _ = game.declare_attackers(1, [1])

    assert declared
    assert forest.tapped
    game.resolve_stack()
    assert p1.life == 21


def test_lifetap_reads_the_current_forest_type_not_the_printed_one(all_cards):
    """A Plains turned into a Forest by Magical Hack IS a Forest (CR 613 layer
    4), so tapping it triggers Lifetap — and the printed Forest it replaced no
    longer does."""
    lifetap = _get(all_cards, "Lifetap")
    plains = Permanent(card=_get(all_cards, "Plains"))
    change_land_type(plains, "forest", source="test")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=lifetap)], life=20)
    p2 = PlayerState(name="P2", battlefield=[plains], life=20)
    game = Game(players=[p1, p2])

    assert game.tap_land_for_mana(1, "Plains")
    game.resolve_stack()

    assert p1.life == 21


def test_mana_flare_gives_the_extra_mana_to_the_player_who_tapped(all_cards):
    """"That player" is the one who tapped the land, not Mana Flare's
    controller."""
    mana_flare = _get(all_cards, "Mana Flare")
    mountain = _get(all_cards, "Mountain")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=mana_flare)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)])
    game = Game(players=[p1, p2])

    assert game.tap_land_for_mana(1, "Mountain")

    assert p2.mana_pool["R"] == 2
    assert p1.mana_pool.get("R", 0) == 0


def test_living_artifact_upkeep_removes_counter_and_gains_life(all_cards):
    living = _get(all_cards, "Living Artifact")
    lotus = _get(all_cards, "Black Lotus")

    aura_perm = Permanent(card=living)
    artifact_perm = Permanent(card=lotus)
    aura_perm.metadata["attached_to"] = artifact_perm
    aura_perm.metadata["vitality_counters"] = 2

    p1 = PlayerState(name="P1", battlefield=[artifact_perm, aura_perm], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)
    # The trigger goes on the stack (CR 603.3) and asks through the general
    # `optional_pay` prompt — "you **may** remove a vitality counter" is a
    # decision, and this is the seat making it.
    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert p1.life == 21
    assert aura_perm.metadata.get("vitality_counters") == 1


def test_living_wall_gains_regeneration_shield(all_cards):
    wall = _get(all_cards, "Living Wall")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Living Wall", target_player_index=0)

    assert result.supported
    assert p1.battlefield[0].regeneration_shield == 1


def test_lure_forces_all_creatures_to_block(all_cards):
    lure = _get(all_cards, "Lure")
    attacker = _mk_card("Bait", "Creature — Bear")
    blocker1 = _mk_card("Guard1", "Creature — Bear")
    blocker2 = _mk_card("Guard2", "Creature — Bear")

    p1 = PlayerState(name="P1", hand=[lure], battlefield=[Permanent(card=attacker)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=blocker1), Permanent(card=blocker2)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lure", target_player_index=0, target_permanent_index=0)
    assert result.supported

    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"
    game.declare_attackers(0, [0], defending_player_index=1)
    game.current_step = "declare_blockers"

    # Assigning only one blocker when two can block a Lure creature should fail
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok

    # Assigning all capable blockers should succeed
    ok2, _ = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok2


def test_manabarbs_deals_damage_when_land_tapped(all_cards):
    manabarbs = _get(all_cards, "Manabarbs")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[manabarbs])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)], life=20)
    game = Game(players=[p1, p2])

    cast_result = game.cast_from_hand(0, "Manabarbs")
    assert cast_result.supported

    game.tap_land_for_mana(1, "Island")

    assert p2.life == 19


def test_pestilence_activation_deals_1_damage_to_all_creatures_and_players(all_cards):
    pestilence = _get(all_cards, "Pestilence")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence), Permanent(card=grizzly)], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Pestilence")

    assert result.supported
    assert p1.life == 19
    assert p2.life == 19
    creature_perm = next(p for p in p1.battlefield if p.card.name == "Grizzly Bears")
    assert creature_perm.damage_marked >= 1


def test_pestilence_sacrificed_at_end_step_when_no_creatures(all_cards):
    pestilence = _get(all_cards, "Pestilence")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_end_step(0)
    # The end-step trigger goes on the stack and resolves off it (CR 603.3).
    game.resolve_stack()

    assert not any(p.card.name == "Pestilence" for p in p1.battlefield)
    assert any(card.name == "Pestilence" for card in p1.graveyard)


def test_pestilence_not_sacrificed_at_end_step_when_creatures_present(all_cards):
    pestilence = _get(all_cards, "Pestilence")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pestilence), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_end_step(0)

    assert any(p.card.name == "Pestilence" for p in p1.battlefield)


def test_phantasmal_terrain_overrides_enchanted_land_type(all_cards):
    terrain = _get(all_cards, "Phantasmal Terrain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(name="P1", hand=[terrain])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=plains)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Phantasmal Terrain", target_player_index=1, target_permanent_index=0)

    assert result.supported
    # The land type is not changed until the controller finishes the basic-land-type
    # choice (the spell does not resolve the change before the prompt is answered).
    assert p2.battlefield[0].changed_land_types == ()
    assert game.pending_land_type_choice is not None
    assert game.confirm_land_type(0, "swamp") is True
    assert p2.battlefield[0].changed_land_types == ("swamp",)


def test_power_leak_deals_upkeep_damage_to_enchanted_enchantment_controller(all_cards):
    power_leak = _get(all_cards, "Power Leak")
    bad_moon = _get(all_cards, "Bad Moon")

    p1 = PlayerState(name="P1", hand=[power_leak])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bad_moon)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Power Leak", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.resolve_upkeep(1)

    assert p2.life == 18


def test_power_surge_upkeep_deals_damage_equal_to_untapped_lands_at_turn_start(all_cards):
    surge = _get(all_cards, "Power Surge")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=surge)])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=island), Permanent(card=island)],
        life=20,
    )
    game = Game(players=[p1, p2])

    game.resolve_untap_step(1)
    game.resolve_upkeep(1)

    assert p2.life == 18


def test_psychic_venom_deals_damage_when_enchanted_land_tapped(all_cards):
    psychic_venom = _get(all_cards, "Psychic Venom")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[psychic_venom])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=island)], life=20)
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Psychic Venom", target_player_index=1, target_permanent_index=0)
    assert result.supported

    game.tap_land_for_mana(1, "Island", "U")

    assert p2.life == 18


def test_red_ward_grants_protection_from_red(all_cards):
    red_ward = _get(all_cards, "Red Ward")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[red_ward], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Red Ward", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert "R" in game._protection_colors(p1.battlefield[0])


def test_steal_artifact_attaches_to_target_artifact(all_cards):
    steal = _get(all_cards, "Steal Artifact")
    target_artifact = _mk_card("Test Artifact", "Artifact")

    p1 = PlayerState(name="P1", hand=[steal])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=target_artifact)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Steal Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    steal_perm = next(p for p in p1.battlefield if p.card.name == "Steal Artifact")
    assert steal_perm.metadata.get("attached_to") is not None


def test_unholy_strength_buffs_enchanted_creature(all_cards):
    unholy = _get(all_cards, "Unholy Strength")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[unholy])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Unholy Strength", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 4
    assert perm.effective_toughness == 3


def test_uthden_troll_regeneration_activated_ability(all_cards):
    troll = _get(all_cards, "Uthden Troll")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=troll)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Uthden Troll")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


def test_wall_of_bone_regeneration_activated_ability(all_cards):
    wall = _get(all_cards, "Wall of Bone")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=wall)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(0, "Wall of Bone")

    assert result.supported
    assert p1.battlefield[0].regeneration_shield >= 1


def test_wanderlust_attaches_to_enchanted_creature(all_cards):
    wanderlust = _get(all_cards, "Wanderlust")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[wanderlust])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wanderlust", target_player_index=1, target_permanent_index=0)

    assert result.supported
    aura_perm = next(p for p in p1.battlefield if p.card.name == "Wanderlust")
    assert aura_perm.metadata.get("attached_to") is not None
    assert aura_perm.metadata["attached_to"].card.name == "Test Bear"


def test_warp_artifact_attaches_to_enchanted_artifact(all_cards):
    warp = _get(all_cards, "Warp Artifact")
    target_artifact = _mk_card("Test Artifact", "Artifact")

    p1 = PlayerState(name="P1", hand=[warp])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=target_artifact)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Warp Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    warp_perm = next(p for p in p1.battlefield if p.card.name == "Warp Artifact")
    assert warp_perm.metadata.get("attached_to") is not None


def test_weakness_debuffs_enchanted_creature(all_cards):
    weakness = _get(all_cards, "Weakness")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[weakness])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Weakness", target_player_index=1, target_permanent_index=0)

    assert result.supported
    perm = p2.battlefield[0]
    assert perm.effective_power == 0
    assert perm.effective_toughness == 1


def test_white_ward_grants_protection_from_white(all_cards):
    white_ward = _get(all_cards, "White Ward")
    bear = _mk_creature_card("Test Bear", 2, 2)

    p1 = PlayerState(name="P1", hand=[white_ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "White Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    creature_perm = p2.battlefield[0]
    # Protection is read off the attached Aura (engine/auras.py), not a flag
    # stamped on the creature, so this asks what the creature is protected
    # from rather than how the engine records it.
    assert "W" in game._protection_colors(creature_perm)


def test_wild_growth_attaches_to_target_land(all_cards):
    wild_growth = _get(all_cards, "Wild Growth")
    forest = _get(all_cards, "Forest")
    p1 = PlayerState(name="P1", hand=[wild_growth], battlefield=[Permanent(card=forest)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wild Growth", target_player_index=0, target_permanent_index=0)

    assert result.supported
    wg_perm = next(p for p in p1.battlefield if p.card.name == "Wild Growth")
    assert wg_perm.metadata.get("attached_to") is not None
    assert wg_perm.metadata["attached_to"].card.name == "Forest"


def test_blue_ward_grants_protection_from_blue(all_cards):
    ward = _get(all_cards, "Blue Ward")
    creature = _mk_creature_card("Test Knight", power=2, toughness=2)
    p1 = PlayerState(name="P1", hand=[ward])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Blue Ward", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert "U" in game._protection_colors(p2.battlefield[0])


def test_animate_dead_creature_sacrificed_when_aura_leaves(all_cards):
    animate = _get(all_cards, "Animate Dead")
    p1 = PlayerState(name="P1", hand=[animate, _get(all_cards, "Disenchant")])
    p2 = PlayerState(name="P2", graveyard=[_get(all_cards, "Grizzly Bears")])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Animate Dead", target_player_index=1, target_permanent_index=0)
    game.resolve_stack()
    assert any(p.card.name == "Grizzly Bears" for p in p1.battlefield)

    ad_idx = next(i for i, p in enumerate(p1.battlefield) if p.card.name == "Animate Dead")
    game.cast_from_hand(0, "Disenchant", target_player_index=0, target_permanent_index=ad_idx)
    game.resolve_stack()

    # "When this Aura leaves the battlefield, that creature's controller
    # sacrifices it." — the reanimated creature dies with the Aura.
    assert not any(p.card.name == "Grizzly Bears" for p in p1.battlefield)
    assert any(c.name == "Grizzly Bears" for c in p2.graveyard)  # owner's graveyard


def test_web_grants_toughness_bonus_and_reach(all_cards):
    web = _get(all_cards, "Web")
    bears = _get(all_cards, "Grizzly Bears")
    flyer = _get(all_cards, "Air Elemental")
    bears_perm = Permanent(card=bears)
    p1 = PlayerState(name="P1", hand=[web], battlefield=[bears_perm])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=flyer)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Web", target_player_index=0, target_permanent_index=0)

    assert result.supported
    # "Enchanted creature gets +0/+2"
    assert bears_perm.effective_power == 2
    assert bears_perm.effective_toughness == 4
    # "and has reach" — it can now block creatures with flying
    assert game._has_keyword(bears_perm, "reach")
    assert game._can_block_attacker(bears_perm, p2.battlefield[0]) is True


def test_sirens_call_cannot_be_cast_during_your_own_turn(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])  # P1 is the active player by default

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_cannot_be_cast_after_attackers_declared(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported is False
    assert any(c.name == "Siren's Call" for c in p1.hand)


def test_sirens_call_marks_active_player_creatures(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Opposing Bear", "Creature - Bear")
    wall = _mk_card("Test Wall", "Creature - Wall")
    home_bear = _mk_card("Home Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call], battlefield=[Permanent(card=home_bear)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear), Permanent(card=wall)], library=[island])
    game = Game(players=[p1, p2])
    game.start_turn(1)

    # Entered the battlefield this turn: exempt from the delayed destruction
    # ("didn't control continuously since the beginning of the turn").
    fresh = Permanent(card=_mk_card("Fresh Bear", "Creature - Bear"))
    fresh.metadata["summoning_sickness_turn"] = game.turn
    p2.battlefield.append(fresh)

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported
    assert any(c.name == "Siren's Call" for c in p1.graveyard)

    bear_perm, wall_perm = p2.battlefield[0], p2.battlefield[1]
    assert bear_perm.metadata.get("must_attack_until_eot") is True
    assert bear_perm.metadata.get("destroy_if_did_not_attack_eot") is True
    # Walls are never destroyed by Siren's Call
    assert wall_perm.metadata.get("destroy_if_did_not_attack_eot") is None
    assert fresh.metadata.get("destroy_if_did_not_attack_eot") is None
    # The caster's own creatures are unaffected
    assert p1.battlefield[0].metadata.get("must_attack_until_eot") is None


def test_sirens_call_forces_creatures_to_attack(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = _mk_card("Reluctant Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)], library=[island])
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers

    ok, reason = game.declare_attackers(1, [])
    assert not ok
    assert "must attack" in reason

    ok, _ = game.declare_attackers(1, [0])
    assert ok


def test_sirens_call_destroys_non_attackers_at_end_step(all_cards):
    call = _get(all_cards, "Siren's Call")
    attacker = _mk_card("Eager Bear", "Creature - Bear")
    slacker = _mk_card("Lazy Bear", "Creature - Bear")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[call])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=attacker), Permanent(card=slacker)],
        library=[island],
    )
    game = Game(players=[p1, p2])

    game.start_turn(1)
    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)
    assert result.supported

    # A tapped creature can't attack, but it still didn't attack this turn,
    # so it is destroyed at the beginning of the next end step.
    p2.battlefield[1].tapped = True

    game._close_current_priority_step()
    game.advance_combat_phase()  # -> beginning_of_combat
    game.advance_combat_phase()  # -> declare_attackers
    ok, _ = game.declare_attackers(1, [0])
    assert ok

    game.resolve_end_step(1)

    names = [perm.card.name for perm in p2.battlefield]
    assert "Eager Bear" in names
    assert "Lazy Bear" not in names
    assert any(c.name == "Lazy Bear" for c in p2.graveyard)


def test_sirens_call_exempts_creature_stolen_this_turn(all_cards):
    call = _get(all_cards, "Siren's Call")
    bear = Permanent(card=_mk_card("Traded Bear", "Creature - Bear"))
    veteran = Permanent(card=_mk_card("Veteran Bear", "Creature - Bear"))
    theft_source = Permanent(card=_mk_card("Theft Source", "Artifact"))
    island = _get(all_cards, "Island")
    p1 = PlayerState(name="P1", hand=[call], battlefield=[bear])
    p2 = PlayerState(name="P2", battlefield=[theft_source, veteran], library=[island])
    game = Game(players=[p1, p2])
    game.start_turn(1)

    # The active player steals P1's bear mid-turn: it is summoning-sick again
    # (CR 302.6) and was not controlled continuously since the turn began.
    assert game.take_control(bear, p2, source=theft_source) is True
    assert bear.metadata.get("summoning_sickness_turn") == game.turn
    assert game._is_summoning_sick(bear) is True

    result = game.cast_from_hand(0, "Siren's Call", target_player_index=1)

    assert result.supported
    assert veteran.metadata.get("destroy_if_did_not_attack_eot") is True
    assert bear.metadata.get("destroy_if_did_not_attack_eot") is None
