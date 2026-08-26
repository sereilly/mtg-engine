"""Per-card tests for Legends' enchantments (Auras included).

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.damage_events import deal_damage
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, power: int = 3, toughness: int = 3) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _enchanted(set_pool, aura_name: str):
    """*aura_name* attached to a creature, with an opposing creature to trade
    damage with. Returns (game, host, other)."""
    host = Permanent(card=_creature("Host"))
    aura = Permanent(card=set_pool("LEG")[aura_name])
    other = Permanent(card=_creature("Other", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, aura]),
        PlayerState(name="P2", battlefield=[other]),
    ])
    attach_aura(aura, host)
    return game, host, other


def _damage(game, recipient, amount, source, *, combat=True) -> int:
    return deal_damage(game, {
        "recipient": recipient, "amount": amount, "source": source, "combat": combat,
    }).dealt


# ---------------------------------------------------------------------------
# The combat-damage shields (round 5) — CR 615, and the direction the printed
# sentence carries.
# ---------------------------------------------------------------------------


def test_gaseous_form_shields_both_ends_of_combat(set_pool):
    """"…dealt **to and dealt by** enchanted creature." Both directions."""
    game, host, other = _enchanted(set_pool, "Gaseous Form")

    assert _damage(game, other, 3, host) == 0
    assert _damage(game, host, 2, other) == 0


def test_gaseous_form_leaves_noncombat_damage_alone(set_pool):
    """"Prevent all **combat** damage" — a Lightning Bolt still kills it."""
    game, host, other = _enchanted(set_pool, "Gaseous Form")

    assert _damage(game, host, 2, other, combat=False) == 2


def test_demonic_torment_shields_only_the_damage_its_host_deals(set_pool):
    """One word apart from Gaseous Form, and the word is the whole card: the
    creature deals nothing and is still perfectly killable in combat. A shield
    that ignored the direction would make it unkillable instead."""
    game, host, other = _enchanted(set_pool, "Demonic Torment")

    assert _damage(game, other, 3, host) == 0
    assert _damage(game, host, 2, other) == 2


def test_demonic_torment_also_stops_its_host_attacking(set_pool):
    """The Aura's other line. "Enchanted creature can't attack" alone needed
    its own row: the table carried only the compound "can't attack or block"."""
    game, host, _ = _enchanted(set_pool, "Demonic Torment")
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, _ = game.declare_attackers(0, [0])
    assert not ok


def test_horn_of_deafening_silences_a_creature_without_protecting_it(set_pool):
    """"Prevent all combat damage that would be dealt **by** target creature
    this turn." The activated form of the same directional shield."""
    horn = Permanent(card=set_pool("LEG")["Horn of Deafening"])
    victim = Permanent(card=_creature("Victim"))
    attacker_side = PlayerState(name="P1", battlefield=[horn, victim])
    other = Permanent(card=_creature("Other", 2, 2))
    game = Game(players=[attacker_side, PlayerState(name="P2", battlefield=[other])])
    game.start_turn(0)
    attacker_side.mana_pool["C"] = 6

    result = game.activate_permanent_ability(
        0, "Horn of Deafening", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported
    assert _damage(game, other, 3, victim) == 0
    assert _damage(game, victim, 2, other) == 2, "the shield is on what it deals"


def test_the_horns_shield_wears_off_at_cleanup(set_pool):
    """"…this turn". Swept by the cleanup step like every other turn-long
    marker, which is what makes the duration real rather than printed."""
    horn = Permanent(card=set_pool("LEG")["Horn of Deafening"])
    victim = Permanent(card=_creature("Victim"))
    other = Permanent(card=_creature("Other", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[horn, victim]),
        PlayerState(name="P2", battlefield=[other]),
    ])
    game.start_turn(0)
    game.players[0].mana_pool["C"] = 6
    game.activate_permanent_ability(
        0, "Horn of Deafening", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()
    assert _damage(game, other, 3, victim) == 0

    game.resolve_cleanup_step(0)
    assert _damage(game, other, 3, victim) == 3


def test_lady_evangela_carries_the_same_ability(set_pool):
    """A creature printing Horn of Deafening's line. One production, so the
    card needed no work of its own."""
    program = compile_card_oracle(set_pool("LEG")["Lady Evangela"])
    assert program.supported, program.reason
    assert [a.instruction.kind for a in program.activated_abilities] == [
        "prevent_damage_by_target_until_eot"
    ]


# ---------------------------------------------------------------------------
# Seeker (round 7) — the whitelist evasion printed on an Aura
# ---------------------------------------------------------------------------


def _seeker_blocked_by(set_pool, blocker: Permanent) -> bool:
    """Whether *blocker* may block a creature enchanted with Seeker."""
    host = Permanent(card=_creature("Host"))
    seeker = Permanent(card=set_pool("LEG")["Seeker"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, seeker]),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    attach_aura(seeker, host)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    return game.declare_blockers(1, {0: 0})[0]


def _typed(name: str, type_line: str, colors=()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def test_seeker_admits_an_artifact_creature(set_pool):
    """"…except by artifact creatures and/or white creatures." The Aura form of
    Elven Riders' whitelist, read through the same subject rewrite — the
    difference between the two cards is whose text the sentence is on."""
    assert _seeker_blocked_by(
        set_pool, Permanent(card=_typed("Golem", "Artifact Creature - Golem"))
    )


def test_seeker_admits_a_white_creature(set_pool):
    assert _seeker_blocked_by(
        set_pool, Permanent(card=_typed("Cleric", "Creature - Cleric", colors=("W",)))
    )


def test_seeker_refuses_a_creature_matching_neither_half(set_pool):
    assert not _seeker_blocked_by(
        set_pool, Permanent(card=_typed("Goblin", "Creature - Goblin", colors=("R",)))
    )


# ---------------------------------------------------------------------------
# Round 9 — the attached "becomes tapped" trigger
# ---------------------------------------------------------------------------


def _land(name: str = "Forest") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",),
        raw={"name": name, "type_line": "Basic Land - Forest"},
    )


def test_blight_destroys_the_land_it_enchants_when_it_becomes_tapped(set_pool):
    """"When enchanted land becomes tapped, destroy it." The pronoun is the
    *land*, not the Aura — resolved as the source it would be on a line whose
    trigger names no other object, this would destroy Blight itself."""
    aura = Permanent(card=set_pool("LEG")["Blight"])
    land = Permanent(card=_land())
    p1 = PlayerState(name="P1", battlefield=[aura])
    p2 = PlayerState(name="P2", battlefield=[land])
    game = Game(players=[p1, p2])
    attach_aura(aura, land)

    game.become_tapped(land)
    assert [item.card.name for item in game.stack] == ["Blight"]
    game.resolve_top_of_stack()

    assert [perm.card.name for perm in p2.battlefield] == []
    assert p2.graveyard[-1].name == "Forest"
    assert any(perm.card.name == "Blight" for perm in p1.battlefield), (
        "the Aura goes to the graveyard by CR 303.4c's state-based action, "
        "which has not been checked yet — not by its own effect"
    )


def test_blight_ignores_a_land_it_does_not_enchant(set_pool):
    """The narrowing is an identity check on the Aura's own host. Two Forests
    on one battlefield compare equal by value, so a filter reading
    characteristics would have Blight fire on the wrong one."""
    aura = Permanent(card=set_pool("LEG")["Blight"])
    enchanted, other = Permanent(card=_land()), Permanent(card=_land())
    p1 = PlayerState(name="P1", battlefield=[aura])
    p2 = PlayerState(name="P2", battlefield=[enchanted, other])
    game = Game(players=[p1, p2])
    attach_aura(aura, enchanted)

    game.become_tapped(other)

    assert game.stack == []


def test_spirit_shackle_puts_a_real_counter_on_its_host(set_pool):
    """"Whenever enchanted creature becomes tapped, put a -0/-2 counter on it."

    Both channels: the P/T the counter carries (CR 122.1a) and the counter
    itself, because a bare P/T bonus is not something CR 704.5q or "a creature
    with a counter on it" can find."""
    host = Permanent(card=_creature("Host", 3, 3))
    aura = Permanent(card=set_pool("LEG")["Spirit Shackle"])
    p1 = PlayerState(name="P1", battlefield=[host, aura])
    game = Game(players=[p1, PlayerState(name="P2")])
    attach_aura(aura, host)

    game.become_tapped(host)
    game.resolve_top_of_stack()

    assert host.effective_power == 3
    assert host.effective_toughness == 1
    assert host.metadata.get("-0/-2_counters") == 1


def test_spirit_shackle_stacks_its_counters(set_pool):
    """Untapping and tapping again is a second event, and a counter is not a
    marker that is already there — CR 122.1a adds each one's toughness."""
    host = Permanent(card=_creature("Host", 3, 5))
    aura = Permanent(card=set_pool("LEG")["Spirit Shackle"])
    p1 = PlayerState(name="P1", battlefield=[host, aura])
    game = Game(players=[p1, PlayerState(name="P2")])
    attach_aura(aura, host)

    for _ in range(2):
        game.become_tapped(host)
        game.resolve_top_of_stack()
        game.become_untapped(host)

    assert host.metadata.get("-0/-2_counters") == 2
    assert host.effective_toughness == 1


def test_spirit_shackle_counters_are_not_the_minus_one_pile(set_pool):
    """CR 122.1: counters are interchangeable with counters *of the same name*.
    A "-0/-2" counter is not a "-1/-1" counter, so it must not land in the pile
    CR 704.5q cancels against +1/+1 counters."""
    host = Permanent(card=_creature("Host", 3, 3))
    aura = Permanent(card=set_pool("LEG")["Spirit Shackle"])
    p1 = PlayerState(name="P1", battlefield=[host, aura])
    game = Game(players=[p1, PlayerState(name="P2")])
    attach_aura(aura, host)

    game.become_tapped(host)
    game.resolve_top_of_stack()

    assert host.metadata.get("minus_counters", 0) == 0


def test_spirit_shackle_survives_the_aura_leaving(set_pool):
    """The counters are on the creature, not a grant from the Aura — detaching
    Spirit Shackle takes back nothing (CR 122.2)."""
    host = Permanent(card=_creature("Host", 3, 4))
    aura = Permanent(card=set_pool("LEG")["Spirit Shackle"])
    p1 = PlayerState(name="P1", battlefield=[host, aura])
    game = Game(players=[p1, PlayerState(name="P2")])
    attach_aura(aura, host)

    game.become_tapped(host)
    game.resolve_top_of_stack()
    game.remove_from_battlefield(aura)

    assert host.effective_toughness == 2
    assert host.metadata.get("-0/-2_counters") == 1


# ---------------------------------------------------------------------------
# Round 10 — the attached "deals damage" trigger
# ---------------------------------------------------------------------------


def _link_board(set_pool, aura_name: str, host_owner: int = 0):
    """*aura_name* on a 3/3, with the Aura's controller as seat 0. ``host_owner``
    says whose battlefield the enchanted creature sits on — Spirit Link goes on
    your own creature, Backfire on theirs."""
    host = Permanent(card=_creature("Host", 3, 3))
    aura = Permanent(card=set_pool("LEG")[aura_name])
    seats = [[aura], []]
    seats[host_owner].append(host)
    game = Game(players=[
        PlayerState(name="P1", battlefield=seats[0], life=20),
        PlayerState(name="P2", battlefield=seats[1], life=20),
    ])
    attach_aura(aura, host)
    return game, host


def test_spirit_link_gains_life_when_its_creature_hits_a_player(set_pool):
    game, host = _link_board(set_pool, "Spirit Link")

    game._deal_damage_to_player(game.players[1], 3, source=host)
    game._settle()

    assert (game.players[0].life, game.players[1].life) == (23, 17)


def test_spirit_link_gains_life_for_damage_dealt_to_a_creature(set_pool):
    """"Deals damage", not "deals combat damage to a player". A blocked
    attacker deals its damage to the blocker, and the life is the same life."""
    game, host = _link_board(set_pool, "Spirit Link")
    blocker = Permanent(card=_creature("Blocker", 2, 5))
    game.players[1].battlefield.append(blocker)

    game._mark_damage_on_permanent(blocker, 3, source=host, combat=True)
    game._settle()

    assert game.players[0].life == 23


def test_spirit_link_gains_for_the_damage_dealt_not_the_life_lost(set_pool):
    """CR 120.4b: the trigger reads what was *dealt*. A shield that stops the
    damage stops the life gain with it — there was no damage to read."""
    game, host = _link_board(set_pool, "Spirit Link")

    game._deal_damage_to_player(game.players[1], 0, source=host)
    game._settle()

    assert game.players[0].life == 20, "CR 120.8: no damage, no event, no trigger"


def test_backfire_burns_the_controller_of_the_creature_that_hit_you(set_pool):
    """"Whenever enchanted creature deals damage **to you**, this Aura deals
    that much damage to **that creature's controller**." Two references, and
    they are different players — the Aura goes on an opponent's creature."""
    game, host = _link_board(set_pool, "Backfire", host_owner=1)

    game._deal_damage_to_player(game.players[0], 4, source=host)
    game._settle()

    assert (game.players[0].life, game.players[1].life) == (16, 16)


def test_backfire_ignores_damage_dealt_to_anyone_else(set_pool):
    """"To you" is the Aura's controller, not any player. In a duel the two
    readings agree; the third seat is what separates them."""
    host = Permanent(card=_creature("Host", 4, 4))
    aura = Permanent(card=set_pool("LEG")["Backfire"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[aura], life=20),
        PlayerState(name="P2", battlefield=[host], life=20),
        PlayerState(name="P3", life=20),
    ])
    attach_aura(aura, host)

    game._deal_damage_to_player(game.players[2], 4, source=host)
    game._settle()

    assert [p.life for p in game.players] == [20, 20, 16]


def test_backfire_ignores_a_creature_it_does_not_enchant(set_pool):
    """The damager narrowing is an identity check on the Aura's own host."""
    host = Permanent(card=_creature("Host", 4, 4))
    other = Permanent(card=_creature("Host", 4, 4))
    aura = Permanent(card=set_pool("LEG")["Backfire"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[aura], life=20),
        PlayerState(name="P2", battlefield=[host, other], life=20),
    ])
    attach_aura(aura, host)

    game._deal_damage_to_player(game.players[0], 4, source=other)
    game._settle()

    assert (game.players[0].life, game.players[1].life) == (16, 20)


# ---------------------------------------------------------------------------
# "Creatures without flying can't attack." (round 12) — CR 506, a board-wide
# restriction whose subject filter is payload
# ---------------------------------------------------------------------------


def test_moat_compiles_to_a_subject_filtered_attack_restriction(set_pool):
    """The whole card is one restriction over a described set — the filter is
    payload on the instruction, never part of the kind, so "creatures without
    trample" would be the same row with a different word in it."""
    program = compile_card_oracle(set_pool("LEG")["Moat"])

    assert program.supported
    kinds = {i.kind: i.payload for i in program.instructions}
    assert kinds["creatures_cant_attack"] == {
        "subject": {"type_filter": "creature", "without_keywords": ["flying"]},
    }


def test_moat_grounds_both_players_creatures_and_lets_flyers_through(set_pool):
    """No "you control" in the sentence, so the Moat's own controller is
    restricted exactly as the opponent is — and a flyer on either side sails
    over it."""
    from engine.card_loader import load_cards, manifest_set_path

    lea = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
    bear = Permanent(card=_creature("Ground Bear"))
    bird = Permanent(card=lea["Air Elemental"])
    moat = Permanent(card=set_pool("LEG")["Moat"])
    own_bear = Permanent(card=_creature("Own Bear"))

    # The opponent's side of the Moat.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bear, bird]),
        PlayerState(name="P2", battlefield=[moat]),
    ])
    game.start_turn(0)
    assert not game.can_attack(bear, 1)
    assert game.can_attack(bird, 1)

    # The Moat's own side.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=set_pool("LEG")["Moat"]), own_bear]),
        PlayerState(name="P2"),
    ])
    game.start_turn(0)
    assert not game.can_attack(own_bear, 1)


def test_moat_asks_layer_six_so_a_granted_wing_escapes(set_pool):
    """"Without flying" is a live layer-6 question at declaration (CR 613.1f):
    a bear granted flying escapes the Moat while the grant lasts, and nothing
    printed on it changed."""
    from engine.keywords import grant_keyword

    bear = Permanent(card=_creature("Hopeful Bear"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bear]),
        PlayerState(name="P2", battlefield=[Permanent(card=set_pool("LEG")["Moat"])]),
    ])
    game.start_turn(0)

    assert not game.can_attack(bear, 1)
    grant_keyword(bear, "flying", until_eot=True)
    assert game.can_attack(bear, 1)


# ---------------------------------------------------------------------------
# Venarian Gold and Cocoon (round 13) — enter-taps with counters, and untap
# restrictions conditioned on the counters. CR 502.3, CR 122.1.
# ---------------------------------------------------------------------------


def test_venarian_gold_taps_and_puts_x_sleep_counters(set_pool):
    """"When this Aura enters, tap enchanted creature and put X sleep counters
    on it." — X is the cast's {X}, and "it" is the creature the tap named, not
    the Aura the pronoun parser would guess."""
    victim = Permanent(card=_creature("Victim"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Venarian Gold"]])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Venarian Gold", target_player_index=1, target_permanent_index=0,
        x_value=3,
    )
    assert result.supported, result.details
    game._settle()

    assert victim.tapped
    assert victim.metadata.get("sleep_counters") == 3
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Venarian Gold")
    assert aura.metadata.get("attached_to") is victim
    assert not aura.metadata.get("sleep_counters"), "the counters go on the creature"


def _gilded(set_pool, counters: int):
    """Venarian Gold attached to an opponent's creature carrying *counters*
    sleep counters."""
    victim = Permanent(card=_creature("Victim"), tapped=True)
    aura = Permanent(card=set_pool("LEG")["Venarian Gold"])
    p1 = PlayerState(name="P1", battlefield=[aura])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(aura, victim)
    if counters:
        victim.metadata["sleep_counters"] = counters
    return game, aura, victim


def test_venarian_gold_holds_the_creature_while_a_sleep_counter_remains(set_pool):
    game, _, victim = _gilded(set_pool, counters=2)

    game.resolve_untap_step(1)
    assert victim.tapped, "a sleep counter keeps it down (CR 502.3)"


def test_venarian_gold_upkeep_removes_a_sleep_counter_from_the_creature(set_pool):
    """"At the beginning of the upkeep of enchanted creature's controller,
    remove a sleep counter from that creature." — the enchanted creature's
    controller's upkeep, and the counter comes off the *creature*."""
    game, _, victim = _gilded(set_pool, counters=2)

    game.resolve_upkeep(1)
    game._settle()
    assert victim.metadata.get("sleep_counters") == 1

    game.resolve_upkeep(0)
    game._settle()
    assert victim.metadata.get("sleep_counters") == 1, (
        "the Aura's controller's own upkeep is not the trigger"
    )


def test_venarian_gold_releases_the_creature_when_the_counters_run_out(set_pool):
    game, _, victim = _gilded(set_pool, counters=1)

    game.resolve_upkeep(1)
    game._settle()
    assert victim.metadata.get("sleep_counters") == 0

    game.resolve_untap_step(1)
    assert not victim.tapped, "no counter, no restriction"


def test_cocoon_refuses_an_opponents_creature(set_pool):
    """"Enchant creature you control" (CR 303.4a): an opponent's creature is
    an illegal choice, and CR 601.2c makes the spell uncastable at it."""
    theirs = Permanent(card=_creature("Theirs"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Cocoon"]])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Cocoon", target_player_index=1, target_permanent_index=0)
    assert result.supported is False
    assert "you control" in result.details


def _cocooned(set_pool, counters: int | None = None):
    """Cocoon cast on its caster's own creature; *counters* overrides the pupa
    count it entered with."""
    mine = Permanent(card=_creature("Mine"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Cocoon"]], battlefield=[mine])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    result = game.cast_from_hand(0, "Cocoon", target_player_index=0, target_permanent_index=0)
    assert result.supported, result.details
    game._settle()
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Cocoon")
    if counters is not None:
        aura.metadata["pupa_counters"] = counters
    return game, aura, mine


def test_cocoon_taps_its_host_and_carries_three_pupa_counters_itself(set_pool):
    """"…tap enchanted creature and put three pupa counters on **this Aura**."
    — the counters are the Aura's, one word apart from Venarian Gold's."""
    game, aura, mine = _cocooned(set_pool)

    assert mine.tapped
    assert aura.metadata.get("pupa_counters") == 3
    assert not mine.metadata.get("pupa_counters"), "the counters go on the Aura"


def test_cocoon_holds_its_host_while_it_has_a_pupa_counter(set_pool):
    game, aura, mine = _cocooned(set_pool)
    mine.tapped = True

    game.resolve_untap_step(0)
    assert mine.tapped

    game.resolve_upkeep(0)
    game._settle()
    assert aura.metadata.get("pupa_counters") == 2, "the upkeep removes one"


def test_cocoon_hatches_when_it_cannot_remove_a_counter(set_pool):
    """"If you can't, sacrifice it, put a +1/+1 counter on enchanted creature,
    and that creature gains flying." — the whole chain, and the flying is a
    grant recorded on the creature (CR 611.2c), so it survives the Aura it
    came from (CR 701.21a's sacrifice)."""
    game, aura, mine = _cocooned(set_pool, counters=0)

    game.resolve_upkeep(0)
    game._settle()

    assert not game.is_on_battlefield(aura), "the Aura sacrificed itself"
    assert any(c.name == "Cocoon" for c in game.players[0].graveyard)
    assert mine.metadata.get("plus_counters") == 1
    assert game._has_keyword(mine, "flying")
    assert game.is_on_battlefield(mine), "the creature stays"

    game.resolve_untap_step(0)
    assert not mine.tapped, "nothing holds it any more"
    assert game._has_keyword(mine, "flying"), "the grant outlives the Aura"


def test_cocoon_does_not_hatch_while_it_can_still_pay(set_pool):
    """"If you can't" is a reading of the removal's record, not a second
    removal: with counters left, nothing hatches."""
    game, aura, mine = _cocooned(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert game.is_on_battlefield(aura)
    assert not mine.metadata.get("plus_counters")
    assert not game._has_keyword(mine, "flying")


def test_cocoon_dies_when_its_host_changes_sides(set_pool):
    """CR 704.5m via CR 303.4c: "Enchant creature you control" makes the
    attachment illegal the moment an opponent controls the creature, and the
    sweep puts the Aura into its owner's graveyard."""
    game, aura, mine = _cocooned(set_pool)

    game.take_control(mine, 1, source=None)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(aura)
    assert any(c.name == "Cocoon" for c in game.players[0].graveyard)


# ---------------------------------------------------------------------------
# Round 14 — "at the beginning of each player's upkeep, … that player …"
# ---------------------------------------------------------------------------


def _sanctuary(set_pool, mine: str, theirs: str):
    """Spiritual Sanctuary on seat 0, with one land each."""
    pool = set_pool("LEG")
    lands = set_pool("LEA")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["Spiritual Sanctuary"]),
            Permanent(card=lands[mine]),
        ],
        life=20,
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=lands[theirs])], life=20)
    return Game(players=[p1, p2]), p1, p2


def test_spiritual_sanctuary_pays_the_player_whose_upkeep_it_is(set_pool):
    """Each seat's own upkeep, each seat's own Plains, each seat's own life.

    The two halves are asserted separately on purpose: the seat that *gains*
    and the seat the condition *asks about* were two different bugs, and each
    one looks correct while the other is being read.
    """
    game, p1, p2 = _sanctuary(set_pool, mine="Plains", theirs="Forest")

    game.resolve_upkeep(0)
    game.resolve_stack()

    assert p1.life == 21, "the controller's own upkeep pays the controller"
    assert p2.life == 20, "and nobody else"


def test_spiritual_sanctuary_pays_an_opponent_on_their_upkeep(set_pool):
    """"Each player's upkeep" is not "your upkeep" — the enchantment's
    controller gets nothing out of an opponent's Plains."""
    game, p1, p2 = _sanctuary(set_pool, mine="Forest", theirs="Plains")

    game.resolve_upkeep(1)
    game.resolve_stack()

    assert p2.life == 21
    assert p1.life == 20


def test_spiritual_sanctuary_asks_about_that_player_not_about_anybody(set_pool):
    """CR 603.4's intervening-if, and the reason this test exists.

    "That player" lowered to a subject `evaluate_condition` had no branch for,
    so it fell through to a scan of *every* player: the enchantment asked "does
    anybody control a Plains", found its controller's, and paid life on an
    upkeep whose player controlled none. A two-player board where only the
    controller has the Plains is the one arrangement that tells the two
    readings apart.
    """
    game, p1, p2 = _sanctuary(set_pool, mine="Plains", theirs="Forest")

    game.resolve_upkeep(1)
    game.resolve_stack()

    assert p2.life == 20, "the opponent controls no Plains"
    assert p1.life == 20, "and the controller's Plains is not their upkeep"


# ---------------------------------------------------------------------------
# Round 18 — Anti-Magic Aura: two clauses, two rules
# ---------------------------------------------------------------------------


def _anti_magic(set_pool):
    """Anti-Magic Aura attached to a Grizzly Bears on seat 0."""
    from engine.auras import attach_aura

    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    aura = Permanent(card=set_pool("LEG")["Anti-Magic Aura"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bear, aura], life=20),
        PlayerState(name="P2", life=20),
    ])
    attach_aura(aura, bear)
    game._sync_control()
    return game, bear, aura


def test_anti_magic_aura_stops_every_spell_targeting_the_creature(set_pool):
    """"…can't be the target of **spells**" is unnarrowed, so Giant Growth is
    stopped as surely as an Aura is — the class is payload, and this card's
    class is every spell."""
    game, bear, _aura = _anti_magic(set_pool)

    assert not game._can_be_targeted(bear, set_pool("LEA")["Holy Strength"], caster_index=1)
    assert not game._can_be_targeted(bear, set_pool("LEA")["Giant Growth"], caster_index=1)


def test_anti_magic_aura_survives_its_own_clause(set_pool):
    """"…by **other** Auras". Read without the word, the Aura makes its own
    attachment illegal and CR 704.5m bins it the moment it lands."""
    game, _bear, aura = _anti_magic(set_pool)

    game.check_state_based_actions()

    assert game.is_on_battlefield(aura)


def test_anti_magic_aura_bins_another_aura_on_the_same_creature(set_pool):
    """CR 303.4c: an Aura enchanting an illegal object "as defined by its
    enchant ability **and other applicable effects**" is put into its owner's
    graveyard (CR 704.5m). This clause is such an effect, so the other Aura is
    illegally attached — the half a targeting-only reading would have missed,
    since Holy Strength was already attached and never targeted anything."""
    from engine.auras import attach_aura

    game, bear, aura = _anti_magic(set_pool)
    holy = Permanent(card=set_pool("LEA")["Holy Strength"])
    game.players[0].battlefield.append(holy)
    game._sync_control()
    attach_aura(holy, bear)

    game.check_state_based_actions()

    assert not game.is_on_battlefield(holy)
    assert game.is_on_battlefield(aura), "and the source is still exempt"


# --- Round 20: an opponent's draw is the same event, asked of another seat ---


def _dreams_board(set_pool, *, seats: int = 2):
    """Underworld Dreams on P1's battlefield, every other seat holding a
    library to draw from."""
    dreams = Permanent(card=set_pool("LEG")["Underworld Dreams"])
    filler = _creature("Filler")
    players = [PlayerState(name="P1", battlefield=[dreams], library=[filler] * 5)]
    for index in range(1, seats):
        players.append(
            PlayerState(name=f"P{index + 1}", library=[filler] * 5)
        )
    return Game(players=players), players


def test_underworld_dreams_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Underworld Dreams"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    # One condition kind for both printed seats: which seat drew is the event's,
    # and the printed "an opponent" is the trigger's own narrowing.
    assert trigger.condition.kind == "draws_card"
    assert trigger.condition.payload == {"drawer": "an opponent"}
    assert trigger.instruction.kind == "deal_damage"
    # "That player" is the seat the fire site froze, not a chosen target.
    assert trigger.instruction.payload["recipient"] == "event_subject_player"


def test_underworld_dreams_damages_the_opponent_who_drew(set_pool):
    game, (p1, p2) = _dreams_board(set_pool)

    game._draw_with_replacements(p2, 1)
    game._settle()

    assert p2.life == 19
    assert p1.life == 20


def test_underworld_dreams_is_silent_on_its_own_controllers_draw(set_pool):
    """"An opponent" is not "a player": the controller drawing is the event
    happening to the wrong seat, and the trigger must not fire at all."""
    game, (p1, p2) = _dreams_board(set_pool)

    game._draw_with_replacements(p1, 1)
    game._settle()

    assert p1.life == 20
    assert p2.life == 20


def test_underworld_dreams_fires_once_per_card_drawn(set_pool):
    """CR 121.2: drawing three cards is three draws, so three damage."""
    game, (_p1, p2) = _dreams_board(set_pool)

    game._draw_with_replacements(p2, 3)
    game._settle()

    assert p2.life == 17


def test_underworld_dreams_damages_the_seat_that_drew_not_the_first_opponent(set_pool):
    """The seat is frozen by the fire site rather than re-derived. With two
    opponents, "that player" and "an opponent" are different answers — which is
    what a targetless resolution's default would have got wrong."""
    game, (p1, p2, p3) = _dreams_board(set_pool, seats=3)

    game._draw_with_replacements(p3, 1)
    game._settle()

    assert p3.life == 19
    assert p2.life == 20
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Invoke Prejudice (round 21) — "Whenever an opponent casts a creature spell
# that doesn't share a color with a creature you control, counter that spell
# unless that player pays {X}, where X is its mana value."
#
# Three things had to be true at once: the condition's colour comparison
# (CR 105.2) against a board rather than against a word, "that spell" meaning
# what "it" means when a *trigger* bound it, and the event carrying the spell it
# fired on so the counter has something to find.
# ---------------------------------------------------------------------------


def _prejudice_creature(name: str, colors: tuple[str, ...]) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Creature — Bear",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )


def _prejudice_game(set_pool, mine: tuple[str, ...], theirs: tuple[str, ...], mana: dict):
    guard = Permanent(card=_prejudice_creature("Guard", mine))
    prejudice = Permanent(card=set_pool("LEG")["Invoke Prejudice"])
    p1 = PlayerState(name="P1", battlefield=[guard, prejudice])
    p2 = PlayerState(name="P2", hand=[_prejudice_creature("Threat", theirs)])
    game = Game(players=[p1, p2])
    game.start_turn(1)
    # After the turn starts: a pool empties at every step boundary (CR 500.4).
    p2.mana_pool.update(mana)
    game.cast_from_hand(1, "Threat")
    game._settle()
    return game, p1, p2


def test_invoke_prejudice_compiles_its_colour_comparison_as_a_board(set_pool):
    """The narrowing is a *noun phrase*, not a colour word — what it compares
    against is whatever is on the battlefield when the spell is cast."""
    program = compile_card_oracle(set_pool("LEG")["Invoke Prejudice"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "opponent_casts_spell"
    assert trigger.condition.payload["cast_type"] == "creature"
    assert trigger.condition.payload["unshared_color_filter"] == {
        "type_filter": "creature", "controller": "you",
    }
    assert trigger.instruction.payload["bound_to_trigger"] is True
    assert trigger.instruction.payload["x_from_count"] == {
        "object_characteristic": {
            "object": "triggering_spell",
            "characteristic": "mana_value",
            "offset": 0,
        }
    }


def test_invoke_prejudice_counters_an_unshared_colour_that_goes_unpaid(set_pool):
    """"…counter **that spell**." The words used to demand an "instead" and mean
    Lofty Denial's replacement amount; here they mean the spell the trigger's own
    condition bound, exactly as "counter it" does elsewhere."""
    game, _p1, p2 = _prejudice_game(set_pool, ("G",), ("U",), {})

    assert not game.stack
    assert [c.name for c in p2.graveyard] == ["Threat"]
    assert not any(p.card.name == "Threat" for p in p2.battlefield)


def test_invoke_prejudice_lets_a_paid_spell_through(set_pool):
    """"…unless that player pays {X}, where X is **its** mana value." The tax is
    sized from the countered spell, so a caster holding it keeps the creature."""
    game, _p1, p2 = _prejudice_game(set_pool, ("G",), ("U",), {"generic": 2})

    assert [p.card.name for p in p2.battlefield] == ["Threat"]
    assert any("is not countered" in line for line in game.log)


def test_invoke_prejudice_stays_silent_on_a_shared_colour(set_pool):
    """The narrowing in the direction that matters. A trigger that ignored it
    would tax every creature spell an opponent casts — a strictly harsher card,
    and one that never announces itself as wrong."""
    game, _p1, p2 = _prejudice_game(set_pool, ("G",), ("G",), {})

    assert [p.card.name for p in p2.battlefield] == ["Threat"]
    assert not any("Invoke Prejudice" in line for line in game.log)


def test_invoke_prejudice_taxes_a_colorless_spell(set_pool):
    """CR 105.2: colours are a set, so a colourless spell shares a colour with
    nothing — which is what makes an artifact creature answer this trigger."""
    game, _p1, p2 = _prejudice_game(set_pool, ("G",), (), {})

    assert [c.name for c in p2.graveyard] == ["Threat"]

# ---------------------------------------------------------------------------
# Land Tax (round 21) — an intervening-if upkeep trigger over an optional
# counted search. CR 603.4, CR 701.19, CR 701.20.
# ---------------------------------------------------------------------------


def _land_tax(set_pool, catalog_by_name, *, opponent_lands: int, own_lands: int):
    plains = catalog_by_name["Plains"]
    forest = catalog_by_name["Forest"]
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=set_pool("LEG")["Land Tax"])]
        + [Permanent(card=plains) for _ in range(own_lands)],
        library=[plains, forest, plains, catalog_by_name["Black Lotus"], plains],
    )
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=forest) for _ in range(opponent_lands)]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.resolve_upkeep(0)
    game._settle()
    return game, p1, p2


def test_land_tax_offers_a_three_card_search_when_an_opponent_is_ahead(
    set_pool, catalog_by_name
):
    """The whole printed sentence: the intervening if is met, the offer is
    made, and the search that follows it finds three rather than one."""
    game, p1, _p2 = _land_tax(set_pool, catalog_by_name, opponent_lands=2, own_lands=0)

    assert [entry["card_name"] for entry in game.pending_optional_pays] == ["Land Tax"]
    assert game.confirm_optional_pay(0, accept=True)
    game._settle()

    prompt = game.pending_search_library
    assert prompt is not None, game.log
    assert prompt["count"] == 3
    assert prompt["up_to"] is True
    assert prompt["destinations"] == ["hand", "hand", "hand"]
    assert prompt["restrictions"] == {"supertypes": ["basic"]}


def test_land_tax_puts_all_three_finds_into_the_hand(set_pool, catalog_by_name):
    """Every find goes to the same place, so all three arrive — a count read
    without its destinations would have found three and placed one."""
    game, p1, _p2 = _land_tax(set_pool, catalog_by_name, opponent_lands=2, own_lands=0)
    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert game.confirm_search_library_picks(
        0,
        [
            {"zone": "library", "index": 0},
            {"zone": "library", "index": 2},
            {"zone": "library", "index": 4},
        ],
    )
    game._settle()

    assert [card.name for card in p1.hand] == ["Plains", "Plains", "Plains"], game.log
    assert sorted(card.name for card in p1.library) == ["Black Lotus", "Forest"]


def test_land_tax_does_not_trigger_without_the_land_advantage(
    set_pool, catalog_by_name
):
    """"If an opponent controls more lands than you" is checked, not decorative
    — with the counts the other way round no offer is made at all."""
    game, p1, _p2 = _land_tax(set_pool, catalog_by_name, opponent_lands=0, own_lands=3)

    assert game.pending_optional_pays == [], game.log
    assert p1.hand == []


def test_land_tax_refuses_a_pick_that_is_not_a_basic_land(set_pool, catalog_by_name):
    """The restriction reaches the picker rather than only the prompt label:
    naming the Black Lotus is rejected, and the search is still owed."""
    game, p1, _p2 = _land_tax(set_pool, catalog_by_name, opponent_lands=2, own_lands=0)
    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert not game.confirm_search_library_picks(0, [{"zone": "library", "index": 3}])
    assert p1.hand == []
    assert game.pending_search_library is not None

# ---------------------------------------------------------------------------
# Round 21 — the CR 613 statics
# ---------------------------------------------------------------------------


def _basic_land(subtype: str) -> CardDefinition:
    line = f"Basic Land - {subtype}"
    return CardDefinition(
        name=subtype, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": subtype, "type_line": line},
    )


def test_living_plane_animates_lands_of_every_type_on_both_sides(set_pool):
    """"All lands are 1/1 creatures that are still lands." The head noun is the
    card type, so nothing is narrowed — including the opponent's lands, which
    the sentence never scoped to a controller."""
    plane = Permanent(card=set_pool("LEG")["Living Plane"])
    mine = Permanent(card=_basic_land("Swamp"))
    theirs = Permanent(card=_basic_land("Plains"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[plane, mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game._refresh_dynamic_creatures()

    for land in (mine, theirs):
        assert land.is_creature
        assert land.has_type("land")
        assert (land.effective_power, land.effective_toughness) == (1, 1)

    game.remove_from_battlefield(plane)
    game._refresh_dynamic_creatures()
    assert not mine.is_creature
    assert not theirs.is_creature


def test_kismet_taps_the_three_types_it_names_on_the_opponents_side(set_pool):
    """"Artifacts, creatures, and lands your opponents control enter tapped."
    Three types and one side, both read off the printed noun phrase."""
    kismet = Permanent(card=set_pool("LEG")["Kismet"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[kismet]),
        PlayerState(name="P2"),
    ])

    def _enters(seat: int, type_line: str) -> Permanent:
        card = CardDefinition(
            name="Subject", mana_cost="", cmc=0.0, type_line=type_line,
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(),
            raw={"name": "Subject", "type_line": type_line,
                 "power": "2", "toughness": "2"},
        )
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, perm, None)
        return perm

    for type_line in ("Creature - Bear", "Artifact", "Basic Land - Forest"):
        assert _enters(1, type_line).tapped, type_line
        assert not _enters(0, type_line).tapped, type_line
    # An enchantment is not one of the three types the card names.
    assert not _enters(1, "Enchantment").tapped


# ---------------------------------------------------------------------------
# Greater Realm of Preservation (round 22) — a Circle over two colours
# ---------------------------------------------------------------------------


def _coloured(name: str, colors: tuple[str, ...]) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _realm_game(set_pool):
    realm = Permanent(card=set_pool("LEG")["Greater Realm of Preservation"])
    goblin = Permanent(card=_coloured("Red Source", ("R",)))
    zombie = Permanent(card=_coloured("Black Source", ("B",)))
    elf = Permanent(card=_coloured("Green Source", ("G",)))
    p1 = PlayerState(name="P1", battlefield=[realm])
    p2 = PlayerState(name="P2", battlefield=[goblin, zombie, elf])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    p1.mana_pool["W"] = 4
    p1.mana_pool["C"] = 4
    return game, goblin, zombie, elf, p1, p2


def _arm(game):
    result = game.activate_permanent_ability(
        0, "Greater Realm of Preservation", permanent_index=0
    )
    game._settle()
    assert result.supported, result.reason


def test_greater_realm_answers_to_either_printed_colour(set_pool):
    """"The next time a **black or red** source of your choice would deal damage
    to you this turn, prevent that damage." One shield recording one property
    with two admissible values (CR 615.9), so either colour spends it."""
    game, goblin, zombie, _elf, p1, _p2 = _realm_game(set_pool)

    _arm(game)
    assert _damage(game, p1, 4, zombie, combat=False) == 0

    _arm(game)
    assert _damage(game, p1, 4, goblin, combat=False) == 0


def test_greater_realm_leaves_a_third_colour_alone(set_pool):
    """CR 615.9 rechecks the recorded property against the source: a green
    source matches neither value, so the damage lands and the shield is not
    used up — the narrowing has to be enforced or the card is a Circle of
    Protection: Everything."""
    game, _goblin, zombie, elf, p1, _p2 = _realm_game(set_pool)
    _arm(game)

    assert _damage(game, p1, 3, elf, combat=False) == 3
    assert _damage(game, p1, 3, zombie, combat=False) == 0, "the shield was still armed"


def test_greater_realms_shield_is_spent_by_one_event(set_pool):
    """"The **next time**": one activation, one instance prevented. Two colours
    is not two shields — a second black source after the first is prevented gets
    through."""
    game, goblin, zombie, _elf, p1, _p2 = _realm_game(set_pool)
    _arm(game)

    assert _damage(game, p1, 2, zombie, combat=False) == 0
    assert _damage(game, p1, 2, goblin, combat=False) == 2


def test_greater_realm_offers_only_sources_of_the_printed_colours(set_pool):
    """The picker narrows to exactly what the shield will answer to, so the
    source a player chooses and the recheck at damage time agree."""
    from engine.targeting import derive_activation_spec

    pool = set_pool("LEG")
    program = compile_card_oracle(pool["Greater Realm of Preservation"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec["any_colors"] == ["B", "R"]

    game, _goblin, _zombie, _elf, _p1, _p2 = _realm_game(set_pool)
    offered = game._enumerate_targets(
        0, pool["Greater Realm of Preservation"], spec, for_cast=False
    )
    assert sorted(t["name"] for t in offered) == ["Black Source", "Red Source"]


# ---------------------------------------------------------------------------
# The CR 614 replacements (round 24) - a draw and an entry, each with a rider
# the printed sentence spends more words on than the replacement itself.
# ---------------------------------------------------------------------------


def _spell(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def _plain_land(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Land"},
    )


def _chains_game(set_pool, *, hand: int = 2, library: int = 8):
    """Chains of Mephistopheles on P1's board, with a stocked hand and library
    for both seats. Returns (game, p1, p2)."""
    chains = Permanent(card=set_pool("LEG")["Chains of Mephistopheles"])
    p1 = PlayerState(
        name="P1", battlefield=[chains],
        hand=[_spell(f"H{i}") for i in range(hand)],
        library=[_spell(f"L{i}") for i in range(library)],
    )
    p2 = PlayerState(
        name="P2",
        hand=[_spell(f"h{i}") for i in range(hand)],
        library=[_spell(f"l{i}") for i in range(library)],
    )
    return Game(players=[p1, p2]), p1, p2


def _settle_discards(game) -> None:
    """Answer every discard the replacement armed, in order - each answer can
    arm the next, which is the shape of "draw three" under Chains."""
    for _ in range(10):
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices(kinds=("discard",))


def test_chains_of_mephistopheles_turns_a_draw_into_discard_then_draw(set_pool):
    """"That player discards a card instead. If the player discards a card this
    way, they draw a card." Both halves, in that order - the hand ends the same
    size and one card of it has been traded for the top of the library."""
    game, p1, _p2 = _chains_game(set_pool)

    game._draw_with_replacements(p1, 1)
    _settle_discards(game)

    assert [card.name for card in p1.graveyard] == ["H0"]
    assert [card.name for card in p1.hand] == ["H1", "L0"]
    assert len(p1.library) == 7


def test_chains_of_mephistopheles_mills_when_there_is_nothing_to_discard(set_pool):
    """"If the player doesn't discard a card this way, they mill a card." The
    only way not to discard is to hold nothing (CR 701.9a) - and then no card
    is drawn either, which is the branch that makes the card a lock."""
    game, p1, _p2 = _chains_game(set_pool, hand=0)

    assert game._draw_with_replacements(p1, 1) == 0
    assert [card.name for card in p1.graveyard] == ["L0"]
    assert p1.hand == []
    assert len(p1.library) == 7


def test_chains_of_mephistopheles_exempts_the_first_draw_step_draw(set_pool):
    """"...except the first one they draw in each of their draw steps." The
    turn-based draw is untouched, and nothing is even queued."""
    game, p1, _p2 = _chains_game(set_pool)

    assert game._draw_with_replacements(p1, 1, turn_based=True) == 1
    assert game.pending_choices == []
    assert [card.name for card in p1.hand] == ["H0", "H1", "L0"]
    assert p1.graveyard == []


def test_chains_of_mephistopheles_exempts_one_draw_not_one_event(set_pool):
    """A draw step with a Howling Mine out is 1 + 1 individual draws (CR 121.2),
    and only the first of the two is the one drawn first in the step."""
    game, p1, _p2 = _chains_game(set_pool)

    game._draw_with_replacements(p1, 2, turn_based=True)
    _settle_discards(game)

    assert [card.name for card in p1.graveyard] == ["H0"], "the second draw only"
    assert [card.name for card in p1.hand] == ["H1", "L0", "L1"]


def test_chains_of_mephistopheles_replaces_its_controllers_draws_too(set_pool):
    """"If **a player** would draw a card" - the enchantment is symmetrical, and
    reading it off the controller's board alone would have made it one-sided."""
    game, _p1, p2 = _chains_game(set_pool)

    game._draw_with_replacements(p2, 1)

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]


def test_chains_of_mephistopheles_does_not_replace_the_draw_it_created(set_pool):
    """CR 614.5: an effect gets one opportunity at an event and at the events
    that result from it. Without that the replacement draw would be replaced
    again and again until the hand was empty."""
    game, p1, _p2 = _chains_game(set_pool, hand=3)

    game._draw_with_replacements(p1, 1)
    _settle_discards(game)

    assert len(p1.hand) == 3, "one card traded, not the whole hand"
    assert [card.name for card in p1.graveyard] == ["H0"]


def test_chains_of_mephistopheles_leaves_a_board_without_it_alone(set_pool):
    """The event outside the sentence: with the enchantment gone, a draw is a
    draw."""
    game, p1, _p2 = _chains_game(set_pool)
    game.remove_all_from_battlefield(list(game.controlled_by(0)))

    assert game._draw_with_replacements(p1, 2) == 2
    assert game.pending_choices == []
    assert p1.graveyard == []


def _equilibrium_game(set_pool, mine: int, theirs: int):
    """Land Equilibrium on P1's board, with *mine* other lands for P1 and
    *theirs* for P2."""
    equilibrium = Permanent(card=set_pool("LEG")["Land Equilibrium"])
    p1 = PlayerState(
        name="P1",
        battlefield=[equilibrium] + [Permanent(card=_plain_land(f"F{i}")) for i in range(mine)],
    )
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=_plain_land(f"G{i}")) for i in range(theirs)]
    )
    return Game(players=[p1, p2]), p1, p2


def _put_land(game, seat: int, name: str = "NewLand") -> Permanent:
    permanent = Permanent(card=_plain_land(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _lands_controlled(game, seat: int) -> int:
    return sum(1 for perm in game.controlled_by(seat) if perm.has_type("land"))


def test_land_equilibrium_taxes_an_opponent_who_has_caught_up(set_pool):
    """"...who controls **at least as many** lands as you do": equal counts, so
    the land arrives and one goes."""
    game, _p1, p2 = _equilibrium_game(set_pool, mine=3, theirs=3)

    _put_land(game, 1)

    assert _lands_controlled(game, 1) == 3
    assert len(p2.graveyard) == 1


def test_land_equilibrium_leaves_an_opponent_who_is_behind_alone(set_pool):
    """Two lands against five is not "at least as many", so nothing is owed and
    the land simply enters."""
    game, _p1, p2 = _equilibrium_game(set_pool, mine=5, theirs=2)

    _put_land(game, 1)

    assert _lands_controlled(game, 1) == 3
    assert p2.graveyard == []


def test_land_equilibrium_never_taxes_its_own_controller(set_pool):
    """"If an **opponent** ... would put a land onto the battlefield." The word
    is a clause of the applicability, not a decoration."""
    game, p1, _p2 = _equilibrium_game(set_pool, mine=3, theirs=3)

    _put_land(game, 0)

    assert p1.graveyard == []
    assert _lands_controlled(game, 0) == 4


def test_land_equilibrium_counts_lands_before_the_new_one_arrives(set_pool):
    """A replacement is asked about the event that *would* happen (CR 614.1).
    With two lands against three the opponent is behind at that moment, even
    though the land they are playing would tie the count."""
    game, _p1, p2 = _equilibrium_game(set_pool, mine=3, theirs=2)

    _put_land(game, 1)

    assert p2.graveyard == []


def test_land_equilibrium_ignores_a_permanent_that_is_not_a_land(set_pool):
    """The event outside the sentence: a creature entering under the same board
    is not "a land onto the battlefield"."""
    game, _p1, p2 = _equilibrium_game(set_pool, mine=3, theirs=3)
    creature = Permanent(card=_creature("Bear", 2, 2))
    game._put_permanent_onto_battlefield(1, creature, None)

    assert p2.graveyard == []
    assert game.pending_choices == []



# ---------------------------------------------------------------------------
# Horror of Horrors — "Sacrifice a Swamp: Regenerate target black creature."
# ---------------------------------------------------------------------------


def _coloured_creature(name: str, colors: tuple[str, ...]) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _horror_game(set_pool, lea_cards, *, black_creature: bool = True):
    """Horror of Horrors, a Swamp to feed it, and a white creature to prove the
    colour narrowing with — plus, by default, the black one it may shield.

    The Swamp sits **before** the creatures on purpose: paying the cost
    renumbers every later slot (CR 400.7), so a resolution that read the slot it
    was handed rather than the identity would shield the wrong creature.
    """
    pool = set_pool("LEG")
    battlefield = [
        Permanent(card=pool["Horror of Horrors"]),
        Permanent(card=lea_cards["Swamp"]),
    ]
    black = None
    if black_creature:
        black = Permanent(card=_coloured_creature("Black Creature", ("B",)))
        battlefield.append(black)
    white = Permanent(card=_coloured_creature("White Creature", ("W",)))
    battlefield.append(white)
    game = Game(players=[
        PlayerState(name="P1", battlefield=battlefield),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    return game, black, white


def test_horror_of_horrors_regenerates_a_black_creature(set_pool, cards):
    """The whole card: the Swamp is eaten as the cost (CR 601.2h) and the black
    creature — not the white one that slides into its slot — comes back with a
    regeneration shield."""
    game, black, white = _horror_game(set_pool, cards)

    result = game.activate_permanent_ability(
        0, "Horror of Horrors", permanent_index=0, target_player_index=0,
        target_permanent_index=2,
    )
    game._settle()

    assert result.supported, result.details
    assert black.regeneration_shield == 1
    assert white.regeneration_shield == 0
    assert not any(
        p.card.name == "Swamp" for p in game.players[0].battlefield
    ), "the Swamp was not sacrificed"


def test_horror_of_horrors_will_not_shield_a_white_creature(set_pool, cards):
    """"target **black** creature": the colour is the narrowing, and a narrowing
    the effect ignores is an effect wider than the card."""
    game, _black, white = _horror_game(set_pool, cards)

    game.activate_permanent_ability(
        0, "Horror of Horrors", permanent_index=0, target_player_index=0,
        target_permanent_index=3,
    )
    game._settle()

    assert white.regeneration_shield == 0


def test_horror_of_horrors_is_refused_with_no_black_creature_to_shield(
    set_pool, cards
):
    """CR 602.2b via 601.2c: an ability whose only object target cannot be
    filled is refused with nothing paid — so the Swamp survives rather than
    being eaten for an effect that could never land."""
    game, _black, _white = _horror_game(set_pool, cards, black_creature=False)

    result = game.activate_permanent_ability(
        0, "Horror of Horrors", permanent_index=0, target_player_index=0,
        target_permanent_index=2,
    )

    assert not result.supported
    assert any(
        p.card.name == "Swamp" for p in game.players[0].battlefield
    ), "the cost was paid for a refused activation"


# ---------------------------------------------------------------------------
# Land's Edge — "Discard a card: If the discarded card was a land card, this
# enchantment deals 2 damage to target player or planeswalker. Any player may
# activate this ability."
# ---------------------------------------------------------------------------


def _lands_edge_game(set_pool, lea_cards, held: str, opponent_holds: str = "Forest"):
    edge = Permanent(card=set_pool("LEG")["Land's Edge"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[edge], hand=[lea_cards[held]]),
        PlayerState(name="P2", hand=[lea_cards[opponent_holds]]),
    ])
    game.enforce_mana_costs = False
    return game


def test_lands_edge_burns_when_the_discard_was_a_land(set_pool, cards):
    game = _lands_edge_game(set_pool, cards, "Mountain")

    result = game.activate_permanent_ability(
        0, "Land's Edge", permanent_index=0, target_player_index=1, cost_hand_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert game.players[1].life == 18
    assert [c.name for c in game.players[0].graveyard] == ["Mountain"]


def test_lands_edge_burns_nobody_when_the_discard_was_not_a_land(set_pool, cards):
    """The condition reads what the *cost* ate (CR 608.2h) — the card is in the
    graveyard by the time the ability resolves, so an ability that read the
    board instead would answer off whatever else is lying around."""
    game = _lands_edge_game(set_pool, cards, "Lightning Bolt")

    result = game.activate_permanent_ability(
        0, "Land's Edge", permanent_index=0, target_player_index=1, cost_hand_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert game.players[1].life == 20, "a non-land discard dealt damage"
    assert [c.name for c in game.players[0].graveyard] == ["Lightning Bolt"]


def test_lands_edge_may_be_activated_by_the_other_player(set_pool, cards):
    """"Any player may activate this ability." The opponent pays out of their
    own hand and aims it at the enchantment's controller."""
    game = _lands_edge_game(set_pool, cards, "Mountain", opponent_holds="Forest")

    result = game.activate_permanent_ability(
        1, "Land's Edge", target_player_index=0, cost_hand_index=0,
        source_controller_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert game.players[0].life == 18
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]
    assert [c.name for c in game.players[0].hand] == ["Mountain"], (
        "the activator's own hand pays the cost"
    )


# ---------------------------------------------------------------------------
# Round 27 — Angelic Voices. "Creatures you control get +1/+1 as long as you
# control no nonartifact, nonwhite creatures." A conditional anthem whose
# condition carries a printed *threshold* — read as presence it would be its
# own negation, which is why the lowering refused a counted condition until the
# evaluator counted.
# ---------------------------------------------------------------------------


def _r27_body(name: str, colors: tuple[str, ...], type_line: str = "Creature — Bear") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _r27_voices_board(set_pool):
    angel = Permanent(card=_r27_body("Angel", ("W",)))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Angelic Voices"]], battlefield=[angel]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    assert game.cast_from_hand(0, "Angelic Voices").supported
    game.resolve_top_of_stack()
    return game, p1, angel


def test_angelic_voices_carries_the_printed_threshold(set_pool):
    """"No …" is `== 0`, and both halves ride the payload. A condition lowered
    without them would be "at least one", which is the sentence inverted."""
    program = compile_card_oracle(set_pool("LEG")["Angelic Voices"])
    assert program.supported, program.reason
    condition = program.instructions[0].payload["condition"]
    assert (condition["count"], condition["op"]) == (0, "eq")
    assert condition["who"] == "you"


def test_angelic_voices_buffs_while_the_board_stays_white(set_pool):
    game, seat, angel = _r27_voices_board(set_pool)
    assert (angel.effective_power, angel.effective_toughness) == (3, 3)


def test_angelic_voices_stops_when_an_off_colour_creature_arrives(set_pool):
    """And starts again when it goes — CR 611.3a, the condition is asked on
    every recompute rather than locked in at resolution."""
    game, seat, angel = _r27_voices_board(set_pool)
    intruder = Permanent(card=_r27_body("Grizzly", ("G",)))

    seat.battlefield.append(intruder)
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert angel.effective_power == 2

    seat.battlefield.remove(intruder)
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert angel.effective_power == 3


def test_angelic_voices_ignores_an_artifact_creature(set_pool):
    """"Nonartifact, nonwhite" is two exclusions, and a colourless artifact
    creature fails the first — so the condition still holds. Dropping either
    word would turn the card off on a board it is printed to work on."""
    game, seat, angel = _r27_voices_board(set_pool)

    seat.battlefield.append(
        Permanent(card=_r27_body("Golem", (), "Artifact Creature — Golem"))
    )
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()

    assert angel.effective_power == 3


# ---------------------------------------------------------------------------
# Round 27 — two Auras whose effect the engine could already carry out and
# whose *claim* was the thing missing.
#
# The Brute: "{R}{R}{R}: Regenerate enchanted creature." The claim pattern read
# a one-symbol activation cost, so the card was unsupported for the width of
# its mana cost.
#
# Spectral Cloak: "Enchanted creature has shroud as long as it's untapped."
# Shroud is the first question `_can_be_targeted` asks and has been for a long
# time; the word was simply outside the keyword registry, so no card could
# grant it.
# ---------------------------------------------------------------------------


def _r27_aura_on_a_bear(set_pool, aura_name: str):
    host = Permanent(card=_creature("Host", 2, 2))
    aura = Permanent(card=set_pool("LEG")[aura_name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, aura]),
        PlayerState(name="P2"),
    ])
    attach_aura(aura, host)
    return game, host, aura


def test_the_brute_compiles_its_three_symbol_activation(set_pool):
    """The cost is read whole. Charging {R} for a {R}{R}{R} ability would be a
    worse failure than the refusal this replaces, so the parsed cost is asserted
    rather than just the card's support."""
    program = compile_card_oracle(set_pool("LEG")["The Brute"])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    assert ability.cost.mana["R"] == 3
    assert ability.instruction.kind == "grant_regeneration_to_enchanted_creature"


def test_the_brute_regenerates_the_creature_it_enchants(set_pool):
    """CR 614.8 — the shield replaces the destroy, taps the creature and is
    spent. The Aura's ability reaches its *host*, not itself."""
    game, host, aura = _r27_aura_on_a_bear(set_pool, "The Brute")
    game.players[0].mana_pool["R"] = 3

    assert game.activate_permanent_ability(0, "The Brute").supported
    game.resolve_top_of_stack()
    assert host.regeneration_shield == 1

    game.players[1].hand.append(CardDefinition(
        name="Terror", mana_cost="{B}", cmc=1.0, type_line="Instant",
        oracle_text="Destroy target creature.", colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(), raw={"name": "Terror", "type_line": "Instant"},
    ))
    game.cast_from_hand(1, "Terror", target_player_index=0, target_permanent_index=0)

    assert host in game.players[0].battlefield
    assert (host.tapped, host.regeneration_shield) == (True, 0)


def test_the_brute_still_grants_its_printed_bonus(set_pool):
    """The activated ability is a second line, not a replacement for the first —
    a claim that swallowed the whole card would have lost the +1/+0."""
    game, host, aura = _r27_aura_on_a_bear(set_pool, "The Brute")
    game._refresh_dynamic_creatures()

    assert (host.effective_power, host.effective_toughness) == (3, 2)


def test_spectral_cloak_grants_shroud_only_while_untapped(set_pool):
    """The condition is asked on every recompute (CR 611.3a), so tapping takes
    the word away at once — a grant recorded when the Aura attached could not
    do that."""
    game, host, aura = _r27_aura_on_a_bear(set_pool, "Spectral Cloak")

    assert host.has_keyword("shroud")
    host.tapped = True
    assert not host.has_keyword("shroud")
    host.tapped = False
    assert host.has_keyword("shroud")


def test_spectral_cloak_shroud_actually_stops_a_spell(set_pool):
    """CR 702.18 — and seat-blind: the check is asked of the object, so the
    grant buys the creature real protection rather than a word nothing reads."""
    game, host, aura = _r27_aura_on_a_bear(set_pool, "Spectral Cloak")
    terror = CardDefinition(
        name="Terror", mana_cost="{B}", cmc=1.0, type_line="Instant",
        oracle_text="Destroy target creature.", colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(), raw={"name": "Terror", "type_line": "Instant"},
    )

    assert not game._can_be_targeted(host, terror, caster_index=1)
    host.tapped = True
    assert game._can_be_targeted(host, terror, caster_index=1)


def test_spectral_cloak_takes_shroud_with_it(set_pool):
    """Removal is the Aura ceasing to be attached; there is no remembered
    delta, which is why nothing has to undo the grant."""
    from engine.auras import detach_aura

    game, host, aura = _r27_aura_on_a_bear(set_pool, "Spectral Cloak")
    assert host.has_keyword("shroud")

    detach_aura(aura, host)

    assert not host.has_keyword("shroud")
