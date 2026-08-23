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
