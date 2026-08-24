"""Per-card tests for Legends' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _vanilla(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _blocked_by(attacker: Permanent, blockers: list[Permanent]) -> tuple[Game, PlayerState]:
    """Attack with *attacker* into *blockers*, all of which block it, and let
    every trigger the declaration put on the stack resolve."""
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=list(blockers))
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    ok, msg = game.declare_blockers(1, {i: 0 for i in range(len(blockers))})
    assert ok, msg
    game._settle()
    return game, p1


# ---------------------------------------------------------------------------
# Rampage (round 1) — CR 702.23, the keyword Legends brings to the pool
# ---------------------------------------------------------------------------

_RAMPAGERS = {
    "Aerathi Berserker": 3,
    "Chromium": 2,
    "Craw Giant": 2,
    "Frost Giant": 2,
    "Hunding Gjornersen": 1,
    "Marhault Elsdragon": 1,
    "Wolverine Pack": 2,
}


@pytest.mark.parametrize("name,amount", sorted(_RAMPAGERS.items()))
def test_every_rampage_card_compiles_to_the_ability_the_rule_defines(name, amount, set_pool):
    """CR 702.23a defines rampage as a triggered ability, so each of these
    compiles to one — not to a keyword line something else has to remember to
    act on. The seven of them are the whole of rampage in the pool."""
    program = compile_card_oracle(set_pool("LEG")[name])
    assert program.supported, program.reason
    rampage = [
        trig for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "rampage_pump"
    ]
    assert len(rampage) == 1, f"{name} should carry exactly one rampage ability"
    assert rampage[0].condition.kind == "creature_becomes_blocked"
    assert rampage[0].instruction.payload["amount"] == amount


def test_craw_giant_grows_by_two_for_each_blocker_past_the_first(set_pool):
    """Craw Giant is 6/4 with trample and rampage 2. Three blockers is two
    beyond the first, so +4/+4."""
    giant = Permanent(card=set_pool("LEG")["Craw Giant"])
    _, p1 = _blocked_by(giant, [Permanent(card=_vanilla(f"Blocker {i}", 1, 1)) for i in range(3)])

    assert p1.battlefield[0].effective_power == 10
    assert p1.battlefield[0].effective_toughness == 8


def test_craw_giant_keeps_the_rest_of_its_printed_line(set_pool):
    """The rampage half of a keyword line must not eat the other half. Craw
    Giant prints "Trample, rampage 2" as one line, and admitting rampage there
    is what would quietly drop the trample beside it."""
    giant = Permanent(card=set_pool("LEG")["Craw Giant"])
    assert giant.has_keyword("trample")


def test_hunding_gjornersen_gets_nothing_from_a_lone_blocker(set_pool):
    """Rampage 1, one blocker: the ability still triggers and resolves, and
    grants nothing (CR 702.23a's "beyond the first")."""
    hunding = Permanent(card=set_pool("LEG")["Hunding Gjornersen"])
    base = hunding.effective_power
    _, p1 = _blocked_by(hunding, [Permanent(card=_vanilla("Blocker", 1, 1))])

    assert p1.battlefield[0].effective_power == base


# ---------------------------------------------------------------------------
# Landwalk negation (round 2) — the creatures printing it. CR 509.1b
# ---------------------------------------------------------------------------


def _islandwalker() -> CardDefinition:
    return CardDefinition(
        name="Islandwalker", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="Islandwalk", colors=(), color_identity=(),
        keywords=("Islandwalk",), produced_mana=(),
        raw={"name": "Islandwalker", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _island() -> CardDefinition:
    return CardDefinition(
        name="Island", mana_cost="", cmc=0.0, type_line="Basic Land - Island",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("U",),
        raw={"name": "Island", "type_line": "Basic Land - Island"},
    )


def _blocked_declaration(defender_extra: list[Permanent]) -> tuple[Game, bool]:
    """An islandwalker attacks a defender who controls an Island; report
    whether the block the defender attempts is legal."""
    attacker = Permanent(card=_islandwalker())
    blocker = Permanent(card=_vanilla("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(
        name="P2",
        battlefield=[blocker, Permanent(card=_island()), *defender_extra],
    )
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    ok, _ = game.declare_blockers(1, {0: 0})
    return game, ok


def test_islandwalk_stops_the_block_with_no_undertow_out(set_pool):
    """The control: CR 702.14c, the defender controls an Island."""
    _, ok = _blocked_declaration([])
    assert not ok


def test_undertow_lets_an_islandwalker_be_blocked(set_pool):
    """"Creatures with islandwalk can be blocked as though they didn't have
    islandwalk." The Island is still there and the attacker still has the
    keyword; what is gone is the blocking restriction (CR 509.1b)."""
    undertow = Permanent(card=set_pool("LEG")["Undertow"])
    game, ok = _blocked_declaration([undertow])
    assert ok
    assert game.players[0].battlefield[0].has_keyword("islandwalk"), (
        "the ability is lifted for blocking only — the creature still has it"
    )


def test_a_negation_of_a_different_landwalk_does_not_help(set_pool):
    """Quagmire names swampwalk; the attacker walks islands. Matching on the
    keyword rather than on the sentence is what keeps these apart."""
    quagmire = Permanent(card=set_pool("LEG")["Quagmire"])
    _, ok = _blocked_declaration([quagmire])
    assert not ok


def test_gosta_dirk_negates_islandwalk_from_a_creature(set_pool):
    """The same sentence printed on a creature rather than an enchantment. It
    is a board-wide static either way, so the card that carries it is not the
    card it acts on."""
    gosta = Permanent(card=set_pool("LEG")["Gosta Dirk"])
    _, ok = _blocked_declaration([gosta])
    assert ok


def test_lord_magnus_negates_both_of_the_landwalks_it_names(set_pool):
    """Two of these lines on one card. Answering with the first would leave the
    second silently unenforced, which is why the reader returns a set."""
    from engine.evasion_negation import negated_evasion_abilities

    magnus = set_pool("LEG")["Lord Magnus"]
    assert negated_evasion_abilities(magnus.oracle_text) == {"plainswalk", "forestwalk"}
    assert compile_card_oracle(magnus).supported


# ---------------------------------------------------------------------------
# The pinger cycle (round 4) — "target attacking or blocking creature"
# ---------------------------------------------------------------------------

_PINGERS = ("Crimson Manticore", "D'Avenant Archer", "Lady Caleria", "Tor Wauki")


@pytest.mark.parametrize("name", _PINGERS)
def test_the_pingers_compile_with_the_union_filter(name, set_pool):
    """"attacking **or** blocking" is one restriction, not two ANDed — a
    creature cannot be doing both, so setting both booleans would describe an
    always-empty set."""
    program = compile_card_oracle(set_pool("LEG")[name])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    filt = (ability.instruction.payload.get("targets") or {}).get("filter") or {}
    assert filt.get("attacking_or_blocking") is True
    assert "attacking_only" not in filt and "blocking_only" not in filt


def _combat_board(set_pool, pinger_name: str):
    """The pinger's controller is attacked by one creature, which one of their
    own creatures blocks — so the board holds one attacker, one blocker and two
    creatures in no combat at all."""
    pinger = Permanent(card=set_pool("LEG")[pinger_name])
    blocker = Permanent(card=_vanilla("Blocker", 2, 2))
    bystander = Permanent(card=_vanilla("Bystander", 2, 2))
    attacker = Permanent(card=_vanilla("Attacker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[pinger, blocker, bystander])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    ok, msg = game.declare_blockers(1, {1: 0})
    assert ok, msg
    game._settle()
    return game, pinger, attacker, blocker, bystander


def test_tor_wauki_may_shoot_either_end_of_the_combat(set_pool):
    """The attacker and the creature blocking it are both legal; the two
    creatures standing outside combat are not."""
    game, pinger, attacker, blocker, bystander = _combat_board(set_pool, "Tor Wauki")
    spec = game.activation_target_spec(1, game.battlefield_index_of(pinger), 0)
    offered = {t["name"] for t in spec["valid_targets"]}

    assert offered == {"Attacker", "Blocker"}
    assert "Bystander" not in offered
    assert "Tor Wauki" not in offered


def test_a_pinger_cannot_be_activated_outside_combat(set_pool):
    """CR 602.2b: an ability with a mandatory target it cannot fill is refused
    with nothing paid, rather than activated to hit whatever the picker
    happened to offer. Nothing is attacking or blocking here."""
    pinger = Permanent(card=set_pool("LEG")["Tor Wauki"])
    idle = Permanent(card=_vanilla("Idle", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[pinger])
    p2 = PlayerState(name="P2", battlefield=[idle])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Tor Wauki", permanent_index=0)

    assert not result.supported
    # The *reason* matters: a refusal for any other cause would pass this test
    # while leaving the restriction unenforced.
    assert result.details == "no valid target for Tor Wauki"
    assert not pinger.tapped, "a refused activation pays no cost"


# ---------------------------------------------------------------------------
# Evasion (round 7) — "can't be blocked by X" and its whitelist twin
# ---------------------------------------------------------------------------


def _wall(name: str, power: int = 0, toughness: int = 4) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="Defender", colors=(), color_identity=(),
        keywords=("Defender",), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Wall",
             "power": str(power), "toughness": str(toughness)},
    )


def _flier(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bird",
        oracle_text="Flying", colors=(), color_identity=(),
        keywords=("Flying",), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bird",
             "power": "2", "toughness": "2"},
    )


def _may_block(attacker_card, blocker_perm) -> bool:
    """Whether *blocker_perm* may legally block a creature with *attacker_card*."""
    attacker = Permanent(card=attacker_card)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker_perm])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    return game.declare_blockers(1, {0: 0})[0]


def test_amrou_kithkin_dodges_the_big_creatures_only(set_pool):
    """"…can't be blocked by creatures with power 3 or greater." The threshold
    is payload, and it is read against *effective* power."""
    kithkin = set_pool("LEG")["Amrou Kithkin"]

    assert not _may_block(kithkin, Permanent(card=_vanilla("Big", 3, 3)))
    assert _may_block(kithkin, Permanent(card=_vanilla("Small", 2, 2)))


def test_elven_riders_admits_either_half_of_its_union(set_pool):
    """"…except by Walls **and/or** creatures with flying" — a whitelist, so a
    blocker matching either member is legal and one matching neither is not."""
    riders = set_pool("LEG")["Elven Riders"]

    assert _may_block(riders, Permanent(card=_wall("Some Wall")))
    assert _may_block(riders, Permanent(card=_flier("Some Bird")))
    assert not _may_block(riders, Permanent(card=_vanilla("Ground Bear", 2, 2)))


def test_a_whitelist_is_not_a_blacklist(set_pool):
    """The distinction the two kinds exist for. Elven Riders lets through only
    what it names; Amrou Kithkin lets through everything it does *not* name."""
    riders = set_pool("LEG")["Elven Riders"]
    kithkin = set_pool("LEG")["Amrou Kithkin"]
    ordinary = Permanent(card=_vanilla("Ordinary", 1, 1))

    assert not _may_block(riders, ordinary)
    assert _may_block(kithkin, Permanent(card=_vanilla("Ordinary", 1, 1)))


# ---------------------------------------------------------------------------
# Base power/toughness rewrites (CR 613.4b) — Sentinel, Wall of Tombstones,
# Halfdane, Brine Hag: "change …'s base [power and] toughness to <value>"
# ---------------------------------------------------------------------------


def _noncreature_card(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Sorcery"},
    )


def test_sentinel_reads_the_power_of_the_creature_it_blocks(set_pool):
    """"{0}: Change this creature's base toughness to 1 plus the power of
    target creature blocking or blocked by this creature." — and the reminder
    text's "indefinitely" means the rewrite survives cleanup (CR 611.2a)."""
    sentinel = Permanent(card=set_pool("LEG")["Sentinel"])
    attacker = Permanent(card=_vanilla("Attacker", 4, 4))
    game, _p1 = _blocked_by(attacker, [sentinel])

    result = game.activate_permanent_ability(
        1, "Sentinel", permanent_index=0, target_permanent_index=0
    )

    assert result.supported, result.details
    assert sentinel.effective_toughness == 5  # 1 plus the attacker's power
    game.resolve_cleanup_step(0)
    assert sentinel.effective_toughness == 5, "the rewrite has no duration"


def test_sentinel_cannot_be_activated_outside_combat(set_pool):
    """CR 602.2b via 601.2c: no creature is blocking or blocked by Sentinel,
    so the mandatory target cannot be filled and the ability is refused —
    not aimed at a bystander the printed restriction excludes."""
    sentinel = Permanent(card=set_pool("LEG")["Sentinel"])
    bystander = Permanent(card=_vanilla("Bystander", 6, 6))
    p1 = PlayerState(name="P1", battlefield=[bystander])
    p2 = PlayerState(name="P2", battlefield=[sentinel])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    result = game.activate_permanent_ability(
        1, "Sentinel", permanent_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert result.details == "no valid target for Sentinel"
    assert sentinel.effective_toughness == 1, "a refused activation changes nothing"


def test_wall_of_tombstones_counts_the_graveyard_when_the_trigger_resolves(set_pool):
    """"…change this creature's base toughness to 1 plus the number of
    creature cards in your graveyard." The count is taken as the trigger
    resolves (CR 608.2) and the rewrite then holds still — a card that dies
    later grows the Wall at the *next* upkeep, not immediately."""
    wall = Permanent(card=set_pool("LEG")["Wall of Tombstones"])
    p1 = PlayerState(
        name="P1", battlefield=[wall],
        graveyard=[
            _vanilla("Dead Bear", 2, 2),
            _vanilla("Dead Bird", 1, 1),
            _vanilla("Dead Ogre", 3, 3),
            _noncreature_card("Dead Ritual"),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)
    game._settle()

    assert wall.effective_toughness == 4  # 1 plus three creature *cards*

    p1.graveyard.append(_vanilla("Dead Wurm", 4, 4))
    assert wall.effective_toughness == 4, "the count was fixed at resolution"

    game.resolve_upkeep(0)
    game._settle()
    assert wall.effective_toughness == 5


def test_halfdane_copies_the_stats_and_reverts_after_his_next_upkeep(set_pool):
    """"…change Halfdane's base power and toughness to the power and toughness
    of target creature other than Halfdane until the end of your next upkeep."

    The timeline the duration prints: the copy holds through the turn cycle,
    and when the next upkeep's trigger cannot re-apply (no legal target), the
    old rewrite runs out as that upkeep ends — not at its start, and not a
    turn later."""
    halfdane = Permanent(card=set_pool("LEG")["Halfdane"])
    brute = Permanent(card=_vanilla("Brute", 5, 5))
    p1 = PlayerState(name="P1", battlefield=[halfdane],
                     library=[_vanilla("Card A", 1, 1), _vanilla("Card B", 1, 1)])
    p2 = PlayerState(name="P2", battlefield=[brute])
    game = Game(players=[p1, p2])

    game.turn = 1
    game.resolve_upkeep(0)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (5, 5)
    game.resolve_draw_step(0)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (5, 5), \
        "the rewrite lasts past its own upkeep's end"

    game.turn = 3
    game.remove_from_battlefield(brute)
    game.resolve_upkeep(0)  # no legal target: nothing re-applies (CR 603.3d)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (5, 5), \
        "the old rewrite holds *through* the next upkeep"
    game.resolve_draw_step(0)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (3, 3), \
        "and ends as that upkeep ends"


def test_halfdane_rereads_the_chosen_creature_each_upkeep(set_pool):
    """Each upkeep's trigger takes a fresh reading (CR 608.2) and its own
    rewrite outlives the old one's expiry, so the copy never flickers."""
    from engine.pt import add_pt_counters

    halfdane = Permanent(card=set_pool("LEG")["Halfdane"])
    brute = Permanent(card=_vanilla("Brute", 5, 5))
    p1 = PlayerState(name="P1", battlefield=[halfdane],
                     library=[_vanilla("Card A", 1, 1), _vanilla("Card B", 1, 1)])
    p2 = PlayerState(name="P2", battlefield=[brute])
    game = Game(players=[p1, p2])

    game.turn = 1
    game.resolve_upkeep(0)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (5, 5)

    add_pt_counters(brute, "+1/+1")

    game.turn = 3
    game.resolve_upkeep(0)
    game.resolve_draw_step(0)
    assert (halfdane.effective_power, halfdane.effective_toughness) == (6, 6), \
        "this upkeep's reading survives this upkeep's end"


def test_halfdane_is_never_offered_himself_and_honours_the_chosen_target(set_pool):
    """"…other than Halfdane": the prompt's candidate list excludes him by
    identity, and a human's pick through the trigger-target channel wins over
    the deterministic first candidate."""
    halfdane = Permanent(card=set_pool("LEG")["Halfdane"])
    own = Permanent(card=_vanilla("Own Bear", 2, 2))
    theirs = Permanent(card=_vanilla("Their Ogre", 4, 4))
    p1 = PlayerState(name="P1", battlefield=[halfdane, own])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    prompts = [t for t in game.get_upkeep_target_triggers(0) if t["card_name"] == "Halfdane"]
    assert len(prompts) == 1
    offered = {t["name"] for t in prompts[0]["valid_targets"]}
    assert offered == {"Own Bear", "Their Ogre"}

    game.resolve_upkeep(0, trigger_targets={"Halfdane": (1, 0)})
    assert (halfdane.effective_power, halfdane.effective_toughness) == (4, 4)


def test_brine_hag_turns_her_killer_into_an_0_2(set_pool):
    """"When this creature dies, change the base power and toughness of all
    creatures that dealt damage to it this turn to 0/2." The classic trade:
    the 5/5 that kills her has 2 combat damage marked, so the rewrite hands
    it to the next state-based check (CR 704.5g)."""
    hag = Permanent(card=set_pool("LEG")["Brine Hag"])
    brute = Permanent(card=_vanilla("Brute", 5, 5))
    p1 = PlayerState(name="P1", battlefield=[brute])
    p2 = PlayerState(name="P2", battlefield=[hag])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(brute, 2, source=hag, combat=True)
    game._mark_damage_on_permanent(hag, 5, source=brute, combat=True)
    game.check_state_based_actions()
    game._settle()

    assert not game.is_on_battlefield(hag)
    assert not game.is_on_battlefield(brute), \
        "0/2 with 2 damage marked does not survive the next state-based check"


def test_brine_hag_records_noncombat_damage_and_both_look_alikes(set_pool):
    """Two identical pingers each chip her outside combat: both are in the
    damage record (deduped by identity, not by value — a look-alike is a
    different permanent) and both are rewritten when she dies."""
    hag = Permanent(card=set_pool("LEG")["Brine Hag"])
    twin_a = Permanent(card=_vanilla("Twin", 3, 3))
    twin_b = Permanent(card=_vanilla("Twin", 3, 3))
    p1 = PlayerState(name="P1", battlefield=[twin_a, twin_b])
    p2 = PlayerState(name="P2", battlefield=[hag])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(hag, 1, source=twin_a)
    game._mark_damage_on_permanent(hag, 1, source=twin_b)
    game.check_state_based_actions()
    game._settle()

    assert not game.is_on_battlefield(hag)
    assert (twin_a.effective_power, twin_a.effective_toughness) == (0, 2)
    assert (twin_b.effective_power, twin_b.effective_toughness) == (0, 2)


def test_brine_hag_cannot_rewrite_a_damager_that_already_left(set_pool):
    """CR 400.7: a permanent that left is a new object wherever it turns up
    next — the record still names it, and the rewrite skips it by identity."""
    hag = Permanent(card=set_pool("LEG")["Brine Hag"])
    raider = Permanent(card=_vanilla("Raider", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[raider])
    p2 = PlayerState(name="P2", battlefield=[hag])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(hag, 1, source=raider)
    game.remove_from_battlefield(raider)
    p1.graveyard.append(raider.card)
    game._mark_damage_on_permanent(hag, 1, source=Permanent(card=_vanilla("Other", 1, 1)))
    game.check_state_based_actions()
    game._settle()

    assert not game.is_on_battlefield(hag)
    assert "absolute_power" not in raider.metadata, \
        "a departed damager is out of the effect's reach"
