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
        "prevent_combat_damage_by_target_until_eot"
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
