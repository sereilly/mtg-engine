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
    assert filt.get("any_states") == ["attacking", "blocking"]
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
# Poison (round 11) — CR 122.1f, the counter on a *player*
# ---------------------------------------------------------------------------


def test_pit_scorpion_poisons_the_player_it_damages(set_pool):
    """"Whenever this creature deals damage to a player, that player gets a
    poison counter." The counter lands on the damaged player — read out of the
    trigger's own context, not on whoever controls the scorpion."""
    scorpion = Permanent(card=set_pool("LEG")["Pit Scorpion"])
    p1 = PlayerState(name="P1", battlefield=[scorpion])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    game._deal_damage_to_player(p2, 1, source=scorpion)
    game._settle()

    assert p2.poison_counters == 1
    assert p1.poison_counters == 0
    assert p2.life == 19, "the counter is in addition to the damage, not instead"


def test_pit_scorpion_damage_to_a_creature_gives_no_poison(set_pool):
    """The condition's narrowing: "…deals damage **to a player**". Damage the
    scorpion deals to a blocker announces the same event with a permanent as
    its recipient, and the trigger must not fire."""
    scorpion = Permanent(card=set_pool("LEG")["Pit Scorpion"])
    bear = Permanent(card=_vanilla("Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[scorpion])
    p2 = PlayerState(name="P2", battlefield=[bear])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    game._mark_damage_on_permanent(bear, 1, source=scorpion)
    game._settle()

    assert p1.poison_counters == 0
    assert p2.poison_counters == 0


def test_a_lookalike_scorpion_gives_no_poison_for_the_real_ones_damage(set_pool):
    """"**This** creature deals damage" is identity, not name: a second copy on
    the same battlefield must not piggyback on the first one's ping."""
    scorpion = Permanent(card=set_pool("LEG")["Pit Scorpion"])
    lookalike = Permanent(card=set_pool("LEG")["Pit Scorpion"])
    p1 = PlayerState(name="P1", battlefield=[scorpion, lookalike])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    game._deal_damage_to_player(p2, 1, source=scorpion)
    game._settle()

    assert p2.poison_counters == 1, "one damage event, one counter — not one per copy"


# ---------------------------------------------------------------------------
# The "named <card name>" filter (round 11) — Rohgahh, Ivory Guardians, Akron
# ---------------------------------------------------------------------------


def _red_bear(name: str, *, token: bool = False) -> Permanent:
    card = CardDefinition(
        name=name, mana_cost="{R}{R}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("R",), color_identity=("R",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )
    return Permanent(card=card, metadata={"is_token": True} if token else {})


def _artifact_soldier(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0,
        type_line="Artifact Creature - Soldier",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Artifact Creature - Soldier",
             "power": "2", "toughness": "2"},
    )


def _statics_game(*battlefields) -> tuple[Game, list[PlayerState]]:
    players = [
        PlayerState(name=f"P{i + 1}", battlefield=list(perms))
        for i, perms in enumerate(battlefields)
    ]
    game = Game(players=players)
    game._recompute_continuous_effects()
    return game, players


def test_rohgahh_buffs_only_kobolds_of_kher_keep_you_control(set_pool):
    """"Creatures you control named Kobolds of Kher Keep get +2/+2." The name
    is a filter key, so the 0/1 Kobolds reads 2/3 while an opponent's copy and
    the lord's own differently-named self are untouched."""
    pool = set_pool("LEG")
    rohgahh = Permanent(card=pool["Rohgahh of Kher Keep"])
    mine = Permanent(card=pool["Kobolds of Kher Keep"])
    bystander = Permanent(card=_vanilla("Bystander", 2, 2))
    theirs = Permanent(card=pool["Kobolds of Kher Keep"])
    _statics_game([rohgahh, mine, bystander], [theirs])

    assert (mine.effective_power, mine.effective_toughness) == (2, 3)
    assert (bystander.effective_power, bystander.effective_toughness) == (2, 2)
    # "you control" scopes the anthem to the lord's controller.
    assert (theirs.effective_power, theirs.effective_toughness) == (0, 1)
    # Rohgahh is a Kobold, but "named" asks the name, not the tribe.
    assert (rohgahh.effective_power, rohgahh.effective_toughness) == (5, 5)


def test_the_name_filter_matches_by_name_never_by_identity(set_pool):
    """A token wearing the name — a different CardDefinition object entirely —
    is buffed exactly as the real card is (CR 201.2a: same name means names in
    common, nothing else)."""
    pool = set_pool("LEG")
    rohgahh = Permanent(card=pool["Rohgahh of Kher Keep"])
    twin = CardDefinition(
        name="Kobolds of Kher Keep", mana_cost="", cmc=0.0,
        type_line="Creature - Kobold", oracle_text="", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "Kobolds of Kher Keep",
             "type_line": "Creature - Kobold", "power": "0", "toughness": "1"},
    )
    token = Permanent(card=twin, metadata={"is_token": True})
    _statics_game([rohgahh, token])

    assert (token.effective_power, token.effective_toughness) == (2, 3)


def test_ivory_guardians_buff_holds_only_while_an_opponent_has_a_nontoken_red_permanent(set_pool):
    """"Creatures named Ivory Guardians get +1/+1 as long as an opponent
    controls a nontoken red permanent." No "other": each copy's anthem buffs
    itself *and* its twin, and the two anthems stack — so a pair reads 5/5
    while the condition holds, exactly as two Crusades would. The condition is
    re-derived on recompute, so both bonuses leave with the red permanent."""
    pool = set_pool("LEG")
    first = Permanent(card=pool["Ivory Guardians"])
    second = Permanent(card=pool["Ivory Guardians"])
    red = _red_bear("Crimson Bear")
    game, players = _statics_game([first, second], [red])

    assert (first.effective_power, first.effective_toughness) == (5, 5)
    assert (second.effective_power, second.effective_toughness) == (5, 5)

    players[1].battlefield.remove(red)
    game._recompute_continuous_effects()
    assert (first.effective_power, first.effective_toughness) == (3, 3)
    assert (second.effective_power, second.effective_toughness) == (3, 3)

    # A lone Guardian still buffs itself: no "other" in the sentence.
    alone = Permanent(card=pool["Ivory Guardians"])
    _statics_game([alone], [_red_bear("Lone Bear")])
    assert (alone.effective_power, alone.effective_toughness) == (4, 4)


def test_ivory_guardians_condition_refuses_a_token_and_your_own_red_permanent(set_pool):
    """The two words that narrow the condition, one at a time: a red *token*
    does not satisfy "nontoken", and your own red permanent does not satisfy
    "an opponent controls"."""
    pool = set_pool("LEG")
    guardians = Permanent(card=pool["Ivory Guardians"])
    _statics_game([guardians], [_red_bear("Ember Token", token=True)])
    assert (guardians.effective_power, guardians.effective_toughness) == (3, 3)

    guardians = Permanent(card=pool["Ivory Guardians"])
    _statics_game([guardians, _red_bear("Own Bear")], [])
    assert (guardians.effective_power, guardians.effective_toughness) == (3, 3)


def test_akron_legionnaire_grounds_all_but_akrons_and_artifact_creatures(set_pool):
    """"Except for creatures named Akron Legionnaire and artifact creatures,
    creatures you control can't attack." The exception union is tested member
    by member: the Legionnaire itself, a second bearer of the name, and an
    artifact creature may attack; an ordinary creature may not."""
    pool = set_pool("LEG")
    akron = Permanent(card=pool["Akron Legionnaire"])
    second_akron = Permanent(card=pool["Akron Legionnaire"])
    golem = Permanent(card=_artifact_soldier("Clay Soldier"))
    bear = Permanent(card=_vanilla("Ground Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[akron, second_akron, golem, bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert game.can_attack(akron, 1)
    assert game.can_attack(second_akron, 1)
    assert game.can_attack(golem, 1)
    assert not game.can_attack(bear, 1)


def test_akron_legionnaire_restricts_its_controller_only(set_pool):
    """"Creatures **you control**": the restriction reaches the Legionnaire's
    controller's creatures and nobody else's."""
    pool = set_pool("LEG")
    bear = Permanent(card=_vanilla("Free Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool["Akron Legionnaire"])])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert game.can_attack(bear, 1)


def test_rohgahh_upkeep_unpaid_taps_the_pile_and_an_opponent_takes_it(set_pool):
    """The decline consequence, whole: tap Rohgahh and every creature named
    Kobolds of Kher Keep — the opponent's included — then the opponent gains
    control of all of them. The change has no duration and no revert."""
    pool = set_pool("LEG")
    rohgahh = Permanent(card=pool["Rohgahh of Kher Keep"])
    mine = Permanent(card=pool["Kobolds of Kher Keep"])
    theirs = Permanent(card=pool["Kobolds of Kher Keep"])
    bystander = Permanent(card=_vanilla("Bystander", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[rohgahh, mine, bystander])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert rohgahh.tapped and mine.tapped and theirs.tapped
    assert not bystander.tapped
    for perm in (rohgahh, mine, theirs):
        assert game.controller_index_of(perm) == 1
    assert game.controller_index_of(bystander) == 0


def test_rohgahh_upkeep_paid_keeps_the_kobolds_home(set_pool):
    pool = set_pool("LEG")
    rohgahh = Permanent(card=pool["Rohgahh of Kher Keep"])
    mine = Permanent(card=pool["Kobolds of Kher Keep"])
    p1 = PlayerState(
        name="P1", battlefield=[rohgahh, mine],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 3, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_upkeep(0)

    assert not rohgahh.tapped and not mine.tapped
    assert game.controller_index_of(rohgahh) == 0
    assert game.controller_index_of(mine) == 0
    assert p1.mana_pool["R"] == 0


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


# ---------------------------------------------------------------------------
# Linked-duration control changes (round 11) — CR 611.2b
# ---------------------------------------------------------------------------


def _legend(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    tl = "Legendary Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=tl,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": tl,
             "power": str(power), "toughness": str(toughness)},
    )


def test_willow_satyr_steals_only_while_it_stays_tapped(set_pool):
    """"…for as long as you control this creature and this creature remains
    tapped." The steal holds while both conditions do, and the state-based
    sweep ends it the moment the Satyr untaps (CR 611.2b) — nothing waits for
    a turn boundary."""
    satyr = Permanent(card=set_pool("LEG")["Willow Satyr"])
    legend = Permanent(card=_legend("Legend Bear"))
    p1 = PlayerState(name="P1", battlefield=[satyr])
    p2 = PlayerState(name="P2", battlefield=[legend])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Willow Satyr", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._settle()

    assert result.supported
    assert satyr.tapped, "the {T} cost was paid"
    assert game.controller_index_of(legend) == 0

    game.become_untapped(satyr)
    game.check_state_based_actions()
    assert game.controller_index_of(legend) == 1, (
        "untapping the Satyr breaks the linked condition and control reverts"
    )


def test_willow_satyr_offers_only_legendary_creatures(set_pool):
    """"target **legendary** creature" — the supertype rides the payload, and
    the picker offers exactly what the resolution will accept (the round-48
    guard's rule)."""
    satyr = Permanent(card=set_pool("LEG")["Willow Satyr"])
    legend = Permanent(card=_legend("Legend Bear"))
    plain = Permanent(card=_vanilla("Plain Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[satyr]),
        PlayerState(name="P2", battlefield=[legend, plain]),
    ])
    game.start_turn(0)

    spec = game.activation_target_spec(0, game.battlefield_index_of(satyr), 0)
    offered = {t["name"] for t in spec["valid_targets"]}

    assert offered == {"Legend Bear"}


def test_willow_satyr_untapped_in_response_never_starts_the_steal(set_pool):
    """CR 611.2b: a "for as long as" duration already over when the effect
    would first apply means the effect never starts — it does not steal for
    an instant and bounce back. Untapping the Satyr while its ability is on
    the stack is the rule's own scenario."""
    satyr = Permanent(card=set_pool("LEG")["Willow Satyr"])
    legend = Permanent(card=_legend("Legend Bear"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[satyr]),
        PlayerState(name="P2", battlefield=[legend]),
    ])
    game.start_turn(0)

    queued = game.queue_permanent_ability(
        0, "Willow Satyr", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert queued.supported and queued.details == "queued"
    game.become_untapped(satyr)   # in response, while the ability is stacked
    game._settle()

    assert game.controller_index_of(legend) == 1
    assert not any(
        "gains control" in line for line in game.log
    ), "the control change never began"


def test_rubinia_soulsinger_compiles_with_both_her_lines(set_pool):
    """Rubinia spells her own name where Willow Satyr says "this creature" —
    both mean the source (CR 201.4c), so she compiles to the same steal, and
    her optional-untap line is claimed by the untap-restriction registry
    rather than left refusing the card."""
    program = compile_card_oracle(set_pool("LEG")["Rubinia Soulsinger"])
    assert program.supported, program.reason
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "steal_target_linked_to_source"
    assert ability.instruction.payload["link_conditions"] == [
        "you_control_source", "source_remains_tapped",
    ]


def test_rubinia_dying_returns_the_stolen_creature(set_pool):
    """"…for as long as you control Rubinia Soulsinger" — a source that has
    left the battlefield satisfies no condition, and the sweep reads the
    contribution from the stolen side, so the steal ends even though its
    source is gone (CR 611.2b)."""
    rubinia = Permanent(card=set_pool("LEG")["Rubinia Soulsinger"])
    bear = Permanent(card=_vanilla("Stolen Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[rubinia]),
        PlayerState(name="P2", battlefield=[bear]),
    ])
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Rubinia Soulsinger", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._settle()
    assert result.supported
    assert game.controller_index_of(bear) == 0

    game.remove_from_battlefield(rubinia)
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 1


def test_rubinia_may_stay_tapped_at_her_untap_step(set_pool):
    """"You may choose not to untap Rubinia Soulsinger during your untap
    step." The prompt offers her by name, and headless play keeps her tapped
    while her steal is live — untapping would end the control change."""
    rubinia = Permanent(card=set_pool("LEG")["Rubinia Soulsinger"])
    bear = Permanent(card=_vanilla("Stolen Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[rubinia]),
        PlayerState(name="P2", battlefield=[bear]),
    ])
    game.start_turn(0)
    game.activate_permanent_ability(
        0, "Rubinia Soulsinger", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._settle()
    assert game.controller_index_of(bear) == 0

    offered = game.get_optional_untap_permanents(0)
    assert [entry["name"] for entry in offered] == ["Rubinia Soulsinger"]

    game.resolve_untap_step(0)
    game.check_state_based_actions()
    assert rubinia.tapped, "headless play keeps her tapped while the steal lives"
    assert game.controller_index_of(bear) == 0

    game.resolve_untap_step(0, keep_tapped_indices=[])
    game.check_state_based_actions()
    assert not rubinia.tapped, "an explicit choice to untap is honoured"
    assert game.controller_index_of(bear) == 1


def _wretched_combat(set_pool, blocker_count: int):
    """The Wretched attacks and *blocker_count* creatures block it; run the
    combat through end of combat and return the game and the blockers."""
    wretch = Permanent(card=set_pool("LEG")["The Wretched"])
    blockers = [
        Permanent(card=_vanilla(f"Blocker {i}", 1, 9)) for i in range(blocker_count)
    ]
    p1 = PlayerState(name="P1", battlefield=[wretch])
    p2 = PlayerState(name="P2", battlefield=list(blockers))
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    ok, msg = game.declare_blockers(1, {i: 0 for i in range(blocker_count)})
    assert ok, msg
    game.advance_combat_phase()   # combat_damage (multiblock waits for a split)
    if not game.combat_damage_resolved:
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg
    game.advance_combat_phase()   # end_of_combat fires the trigger
    game.advance_combat_phase()   # postcombat main
    return game, wretch, blockers


def test_the_wretched_takes_every_creature_blocking_it(set_pool):
    """"At end of combat, gain control of **all** creatures blocking this
    creature" — the set was fixed when the trigger fired (CR 611.2c), so both
    blockers change sides even though the combat record is cleared before the
    trigger resolves."""
    game, wretch, blockers = _wretched_combat(set_pool, 2)

    assert game.is_on_battlefield(wretch)
    assert [game.controller_index_of(b) for b in blockers] == [0, 0]


def test_the_wretched_leaving_returns_its_blockers(set_pool):
    """"…for as long as you control this creature": one condition, several
    stolen permanents — every contribution The Wretched recorded ends
    together when it leaves (CR 611.2b)."""
    game, wretch, blockers = _wretched_combat(set_pool, 2)
    assert [game.controller_index_of(b) for b in blockers] == [0, 0]

    game.remove_from_battlefield(wretch)
    game.check_state_based_actions()
    assert [game.controller_index_of(b) for b in blockers] == [1, 1]


def test_the_wretched_unblocked_steals_nothing(set_pool):
    """The trigger still fires at end of combat (CR 511.1); with nothing
    blocking, it resolves and takes nothing — and does not crash."""
    game, wretch, blockers = _wretched_combat(set_pool, 0)
    assert game.is_on_battlefield(wretch)


# ---------------------------------------------------------------------------
# "Can't attack" restrictions (round 12) — CR 506/508.1c, filter payloads and
# per-turn history
# ---------------------------------------------------------------------------


def test_evil_eye_grounds_its_controllers_other_creatures_but_not_itself(set_pool):
    """"Non-Eye creatures **you control** can't attack." The negated subtype is
    a filter payload (`exclude_subtypes`), so the Eye itself — and any other
    Eye — walks through its own restriction."""
    pool = set_pool("LEG")
    eye = Permanent(card=pool["Evil Eye of Orms-by-Gore"])
    bear = Permanent(card=_vanilla("Grounded Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[eye, bear])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert game.can_attack(eye, 1)
    assert not game.can_attack(bear, 1)


def test_evil_eye_restricts_its_controller_only(set_pool):
    """"You control" is relative to the permanent carrying the restriction
    (CR 109.5), so the opponent's creatures attack freely."""
    bear = Permanent(card=_vanilla("Free Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=set_pool("LEG")["Evil Eye of Orms-by-Gore"])]
    )
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert game.can_attack(bear, 1)


def test_evil_eye_is_blockable_only_by_walls(set_pool):
    """The second line — "can't be blocked except by Walls" — was already read
    by the round-7 whitelist; what round 12 bought is the first line, and with
    it the card. Both halves must work on the same compiled program."""
    eye = set_pool("LEG")["Evil Eye of Orms-by-Gore"]

    assert _may_block(eye, Permanent(card=_wall("Some Wall")))
    assert not _may_block(eye, Permanent(card=_vanilla("Ground Bear", 2, 2)))


def test_giant_turtle_rests_for_exactly_one_of_its_controllers_turns(set_pool):
    """"…can't attack if it attacked during your last turn." The record is the
    per-attacker stamp declaration writes, compared by the controller's own
    turn ordinal — so the Turtle attacks, sits out the controller's next turn,
    and attacks again the turn after."""
    turtle = Permanent(card=set_pool("LEG")["Giant Turtle"])
    p1 = PlayerState(name="P1", battlefield=[turtle])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    game.start_next_turn()   # P2's turn
    game.start_next_turn()   # P1's next turn: it attacked during P1's last turn
    assert not game.can_attack(turtle, 1)

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1 again: last turn it rested
    assert game.can_attack(turtle, 1)


def test_giant_turtle_that_never_attacked_is_unrestricted(set_pool):
    turtle = Permanent(card=set_pool("LEG")["Giant Turtle"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[turtle]), PlayerState(name="P2"),
    ])
    game.start_turn(0)

    assert game.can_attack(turtle, 1)


def test_a_returned_giant_turtle_is_a_new_object_with_no_attack_record(set_pool):
    """CR 400.7: the record belongs to the permanent, and a Turtle that leaves
    and returns is a new object — free to attack however hard the old one
    fought."""
    turtle = Permanent(card=set_pool("LEG")["Giant Turtle"])
    p1 = PlayerState(name="P1", battlefield=[turtle])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    # It leaves and returns: a new Permanent wearing the same card.
    game.remove_from_battlefield(turtle)
    returned = Permanent(card=set_pool("LEG")["Giant Turtle"])
    game._put_permanent_onto_battlefield(0, returned, None)

    game.start_next_turn()
    game.start_next_turn()
    from tests.helpers import _nosick
    assert game.can_attack(_nosick(returned), 1)


def test_wall_of_dust_holds_its_victim_home_for_one_turn(set_pool):
    """"Whenever this creature blocks a creature, that creature can't attack
    during its controller's next turn." — the blocked attacker is stamped when
    the trigger resolves, refused on its controller's next turn, and free the
    turn after. The Wall itself never attacks (Defender)."""
    bear = Permanent(card=_vanilla("Charging Bear", 1, 1))
    wall = Permanent(card=set_pool("LEG")["Wall of Dust"])
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(name="P2", battlefield=[wall])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    game.start_next_turn()   # P2's turn
    game.start_next_turn()   # P1's next turn — the stamped window
    assert not game.can_attack(bear, 1)

    game.start_next_turn()
    game.start_next_turn()   # P1's turn after — the window has passed
    assert game.can_attack(bear, 1)


def test_wall_of_dust_restriction_does_not_leak_onto_a_bystander(set_pool):
    """Only the blocked creature is stamped: an attacker the Wall did not
    block attacks again next turn as usual."""
    blocked = Permanent(card=_vanilla("Blocked Bear", 1, 1))
    free = Permanent(card=_vanilla("Free Bear", 1, 1))
    wall = Permanent(card=set_pool("LEG")["Wall of Dust"])
    p1 = PlayerState(name="P1", battlefield=[blocked, free])
    p2 = PlayerState(name="P2", battlefield=[wall])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game.advance_combat_phase()
    ok, msg = game.declare_blockers(1, {0: 0})   # the Wall blocks only the first
    assert ok, msg
    game._settle()

    game.start_next_turn()
    game.start_next_turn()
    assert not game.can_attack(blocked, 1)
    assert game.can_attack(free, 1)


# ---------------------------------------------------------------------------
# Round 15 — "blocks or becomes blocked by <subject>", both halves
# ---------------------------------------------------------------------------


def _to_declare_blockers(game: Game) -> None:
    """Advance a freshly built game to declare_blockers with seat 0 attacking."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"


def _blocking(set_pool, own_name: str, foe: CardDefinition):
    """*own_name* blocking on seat 1, *foe* attacking from seat 0."""
    mine = Permanent(card=set_pool("LEG")[own_name])
    theirs = Permanent(card=foe)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[theirs]),
        PlayerState(name="P2", battlefield=[mine]),
    ])
    _to_declare_blockers(game)
    return game, mine, theirs


def _attacking(set_pool, own_name: str, foe: CardDefinition):
    """*own_name* attacking from seat 0, *foe* blocking on seat 1."""
    mine = Permanent(card=set_pool("LEG")[own_name])
    theirs = Permanent(card=foe)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    _to_declare_blockers(game)
    return game, mine, theirs


def _test_creature(name: str, colors: tuple[str, ...]) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def test_abomination_destroys_a_white_attacker_it_blocks(set_pool):
    """The *blocks* half. "That creature" is the attacker, which the fire site
    names by id rather than by the stack item's target — the target there is
    Abomination itself, so a handler reading it would destroy the blocker."""
    game, _abom, attacker = _blocking(
        set_pool, "Abomination", _test_creature("Pale Knight", ("W",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert attacker.metadata.get("destroy_at_end_of_combat") is True


def test_abomination_destroys_a_green_blocker_when_it_attacks(set_pool):
    """The *becomes blocked by* half, and the "or" in the colour phrase: green
    is the other alternative, so a matcher requiring both colours destroys
    nothing."""
    game, _abom, blocker = _attacking(
        set_pool, "Abomination", _test_creature("Wild Thing", ("G",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert blocker.metadata.get("destroy_at_end_of_combat") is True


def test_abomination_spares_a_blue_attacker(set_pool):
    """The narrowing is what the round bought: the same sentence with a
    different colour word. Blue is neither alternative, and a dispatcher that
    ignored the filter would destroy it."""
    game, _abom, attacker = _blocking(
        set_pool, "Abomination", _test_creature("Cold Fish", ("U",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert attacker.metadata.get("destroy_at_end_of_combat") is not True


def test_aisling_leprechaun_recolours_what_it_blocks(set_pool):
    """A block-pair binding driving something other than a destroy — which is
    the reason the fire site fires whatever instruction the trigger carries
    rather than only the delayed destroy it used to look for."""
    game, _aisling, attacker = _blocking(
        set_pool, "Aisling Leprechaun", _test_creature("Grey Ogre", ("R",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert "G" in attacker.effective_colors
    assert attacker.metadata.get("destroy_at_end_of_combat") is not True


# ---------------------------------------------------------------------------
# Round 16 — the narrowing decides whether "that creature" names one creature
# ---------------------------------------------------------------------------


def test_infernal_medusa_destroys_what_it_blocks(set_pool):
    """Its *first* line, which lowered to nothing until round 16.

    Medusa prints the two halves as separate sentences, and the blocks half is
    narrowed ("blocks **a creature**"). The gate keyed on the trigger kind alone
    could not see that, so the card was reported supported with half its text
    inert — a card doing less than it prints, which `--hollow-lines` had been
    reporting all along.
    """
    game, _medusa, attacker = _blocking(
        set_pool, "Infernal Medusa", _test_creature("Hill Giant", ("R",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert attacker.metadata.get("destroy_at_end_of_combat") is True


def test_infernal_medusa_still_destroys_a_blocker_that_is_no_wall(set_pool):
    """Its second line, unchanged — asserted beside the first so a regression
    that swapped the two halves' bindings cannot pass on one of them."""
    game, _medusa, blocker = _attacking(
        set_pool, "Infernal Medusa", _test_creature("Hill Giant", ("R",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert blocker.metadata.get("destroy_at_end_of_combat") is True


# ---------------------------------------------------------------------------
# Round 17 — Ayesha Tanaka: an ability waits while its controller is asked
# ---------------------------------------------------------------------------


def _ayesha_board(set_pool, pool: dict):
    """An artifact's ping on the stack from seat 0, Ayesha on seat 1."""
    source = CardDefinition(
        name="Test Pinger", mana_cost="{2}", cmc=2.0, type_line="Artifact",
        oracle_text="{T}: This artifact deals 1 damage to any target.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Test Pinger", "type_line": "Artifact"},
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=source)], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=set_pool("LEG")["Ayesha Tanaka"])], life=20
    )
    game = Game(players=[p1, p2])
    game.start_turn(0)
    assert game.queue_permanent_ability(0, "Test Pinger", target_player_index=1).supported
    p1.mana_pool.update(pool)
    assert game.queue_permanent_ability(1, "Ayesha Tanaka", target_stack_index=0).supported
    game.resolve_stack()
    game._settle()
    return game, p1, p2


def test_ayesha_tanaka_lets_the_ability_through_when_its_controller_pays(set_pool):
    """{W} in the pool answers {W}: the ability is not countered, and the white
    mana is gone."""
    _game, p1, p2 = _ayesha_board(set_pool, {"W": 1})

    assert p2.life == 19, "the ping resolved"
    assert p1.mana_pool.get("W", 0) == 0, "the payment came out of the pool"


def test_ayesha_tanaka_counters_when_the_pool_is_the_wrong_colour(set_pool):
    """The reason the cost is a symbol dict rather than a number.

    One red mana is one mana, so a payment flow that only knew *how many* would
    have let {R} pay {W} — the ability would survive and the white pip would
    have meant nothing. It is the only case that tells the two representations
    apart, which is why it is here and not just the empty-pool one below.
    """
    _game, p1, p2 = _ayesha_board(set_pool, {"R": 1})

    assert p2.life == 20, "the ability was countered"
    assert p1.mana_pool.get("R", 0) == 1, "and the red mana was not taken"


def test_ayesha_tanaka_counters_when_its_controller_cannot_pay(set_pool):
    _game, _p1, p2 = _ayesha_board(set_pool, {})

    assert p2.life == 20


# ---------------------------------------------------------------------------
# Round 18 — a narrowed shroud: "can't be the target of Aura spells"
# ---------------------------------------------------------------------------


def _bartel(set_pool, lea_by_name=None):
    """Bartel Runeaxe on seat 0, an opponent holding spells on seat 1."""
    bartel = Permanent(card=set_pool("LEG")["Bartel Runeaxe"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bartel], life=20),
        PlayerState(name="P2", life=20),
    ])
    return game, bartel


def test_bartel_runeaxe_cannot_be_targeted_by_an_aura_spell(set_pool):
    """CR 115.6 through the one predicate every chooser reaches.

    The line names the card, not "this creature" — pre-modern templating — so
    the runtime reader has to collapse the self-reference the same way the
    support gate does. It did not at first, and the card compiled supported
    while protecting nobody.
    """
    game, bartel = _bartel(set_pool)
    holy_strength = set_pool("LEA")["Holy Strength"]

    assert not game._can_be_targeted(bartel, holy_strength, caster_index=1)


def test_bartel_runeaxe_is_an_ordinary_target_for_anything_else(set_pool):
    """A *narrowed* shroud, not shroud. Giant Growth is not an Aura spell, and
    a restriction read as plain shroud would stop it too."""
    game, bartel = _bartel(set_pool)
    giant_growth = set_pool("LEA")["Giant Growth"]

    assert game._can_be_targeted(bartel, giant_growth, caster_index=1)


def test_bartel_runeaxe_refuses_an_aura_at_the_cast_gate(set_pool):
    """The predicate is what the cast path asks, so the spell is refused with
    nothing paid rather than resolving onto an illegal target."""
    bartel = Permanent(card=set_pool("LEG")["Bartel Runeaxe"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bartel], life=20),
        PlayerState(name="P2", hand=[set_pool("LEA")["Holy Strength"]], life=20),
    ])
    game.start_turn(1)

    result = game.cast_from_hand(
        1, "Holy Strength", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported


# ---------------------------------------------------------------------------
# Round 19 — a state union is any pair, not the pair the pingers printed
# ---------------------------------------------------------------------------


def _tetsuo_board(set_pool, *, tapped: bool):
    """Tetsuo on seat 0 with its cost floating, a Grizzly Bears on seat 1."""
    tetsuo = Permanent(card=set_pool("LEG")["Tetsuo Umezawa"])
    victim = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    victim.tapped = tapped
    game = Game(players=[
        PlayerState(name="P1", battlefield=[tetsuo], life=20),
        PlayerState(name="P2", battlefield=[victim], life=20),
    ])
    game.start_turn(0)
    game.players[0].mana_pool.update({"U": 1, "B": 2, "R": 1})
    return game


def test_tetsuo_umezawa_destroys_a_tapped_creature(set_pool):
    """"Target **tapped or blocking** creature" — the half the pinger cycle's
    hardcoded pair could not express."""
    game = _tetsuo_board(set_pool, tapped=True)

    result = game.activate_permanent_ability(
        0, "Tetsuo Umezawa", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert not any(p.card.name == "Grizzly Bears" for p in game.players[1].battlefield)


def test_tetsuo_umezawa_refuses_a_creature_in_neither_state(set_pool):
    """A union narrows; it does not widen. CR 602.2b refuses the activation
    outright when no legal target exists, so an untapped creature that is not
    blocking costs Tetsuo nothing rather than being destroyed anyway."""
    game = _tetsuo_board(set_pool, tapped=False)

    result = game.activate_permanent_ability(
        0, "Tetsuo Umezawa", target_player_index=1, target_permanent_index=0
    )

    assert not result.supported
    assert any(p.card.name == "Grizzly Bears" for p in game.players[1].battlefield)


# Wall of Wonder (round 20) — CR 609.4, an "as though" attack permission
# ---------------------------------------------------------------------------


def _wall_of_wonder_game(set_pool) -> tuple[Game, Permanent]:
    wall = Permanent(card=set_pool("LEG")["Wall of Wonder"])
    p1 = PlayerState(name="P1", battlefield=[wall])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game, wall


def test_wall_of_wonder_compiles_both_halves_of_its_one_sentence(set_pool):
    """The pump and the permission are one printed sentence joined by "and".
    A production that read the pump and shrugged at the rest would have left
    a Wall that pumps and still cannot attack."""
    program = compile_card_oracle(set_pool("LEG")["Wall of Wonder"])
    assert program.supported, program.reason
    instruction = program.activated_abilities[0].instruction
    assert instruction.kind == "sequence"
    assert [step.kind for step in instruction.payload["steps"]] == [
        "pump_self", "attack_as_though_no_defender_until_eot"
    ]


def test_wall_of_wonder_pumps_itself_and_may_then_attack(set_pool):
    game, wall = _wall_of_wonder_game(set_pool)
    assert (wall.effective_power, wall.effective_toughness) == (1, 5)

    result = game.activate_permanent_ability(0, "Wall of Wonder", permanent_index=0)
    game._settle()

    assert result.supported
    assert (wall.effective_power, wall.effective_toughness) == (5, 1)
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg


def test_the_permission_does_not_take_defender_away(set_pool):
    """CR 609.4: the effect applies only to the stated effect. Removing the
    keyword instead would change what "creatures with defender" counts and
    what layer 6 reports, none of which the card says."""
    game, wall = _wall_of_wonder_game(set_pool)
    game.activate_permanent_ability(0, "Wall of Wonder", permanent_index=0)
    game._settle()

    assert game._has_keyword(wall, "defender")


def test_an_unactivated_wall_of_wonder_still_cannot_attack(set_pool):
    game, _wall = _wall_of_wonder_game(set_pool)
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, _msg = game.declare_attackers(0, [0])
    assert not ok


def test_the_attack_permission_wears_off_at_cleanup(set_pool):
    """"…this turn" is the cleanup sweep and nothing else — a permission that
    survived it would be a Wall that could attack for the rest of the game."""
    game, wall = _wall_of_wonder_game(set_pool)
    game.activate_permanent_ability(0, "Wall of Wonder", permanent_index=0)
    game._settle()

    game.resolve_cleanup_step(0)
    assert (wall.effective_power, wall.effective_toughness) == (1, 5)
    assert not game._ignores_defender(wall)


# ---------------------------------------------------------------------------
# Psionic Entity (round 20) — "and 3 damage to **itself**"
# ---------------------------------------------------------------------------


def _psionic_board(set_pool, victims: list[Permanent]):
    from tests.helpers import _nosick

    entity = _nosick(Permanent(card=set_pool("LEG")["Psionic Entity"]))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[entity], life=20),
        PlayerState(name="P2", battlefield=list(victims), life=20),
    ])
    game.start_turn(0)
    return game, entity


def test_psionic_entity_damages_the_face_and_kills_itself(set_pool):
    """Both clauses run: 2 to the chosen target, 3 to the Entity — which is a
    2/2, so the self-damage is lethal (CR 704.5g)."""
    game, entity = _psionic_board(set_pool, [])

    result = game.activate_permanent_ability(0, "Psionic Entity", target_player_index=1)

    assert result.supported, result.details
    assert game.players[1].life == 18
    assert not any(p.card.name == "Psionic Entity" for p in game.players[0].battlefield)


def test_psionic_entitys_self_damage_does_not_land_on_its_own_target(set_pool):
    """The Detonate bug class: the second clause resolves with the first
    clause's target still in the resolution context, so a self-damage with no
    named recipient would be dealt to the chosen creature — 5 damage to one
    creature and none to the Entity."""
    victim = Permanent(card=set_pool("LEA")["Hill Giant"])   # 3/3, survives 2
    game, entity = _psionic_board(set_pool, [victim])

    result = game.activate_permanent_ability(
        0, "Psionic Entity", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    # The Bears took exactly 2 and lived; the Entity took its own 3 and died.
    assert any(p.card.name == "Hill Giant" for p in game.players[1].battlefield)
    assert victim.damage_marked == 2
    assert not any(p.card.name == "Psionic Entity" for p in game.players[0].battlefield)
    assert game.players[1].life == 20

# ---------------------------------------------------------------------------
# Round 20: a keyword taken away for good, by a trigger
# ---------------------------------------------------------------------------


def test_elder_land_wurm_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Elder Land Wurm"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    # "**When** this creature blocks" is the event the "whenever" spelling
    # names; the printed word is not a difference the fire site can act on.
    assert trigger.condition.kind == "creature_blocks"
    assert trigger.instruction.kind == "remove_self_keyword"
    assert trigger.instruction.payload["keywords"] == ("defender",)


def test_elder_land_wurm_loses_defender_when_it_blocks(set_pool):
    wurm = Permanent(card=set_pool("LEG")["Elder Land Wurm"])
    attacker = Permanent(card=_vanilla("Bear", 2, 2))

    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[wurm])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers

    assert game._has_keyword(wurm, "defender")

    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    # A layer-6 removal with no expiry stamped on it: the word is gone, and
    # trample — printed on the same card and untouched — is still there.
    assert not game._has_keyword(wurm, "defender")
    assert game._has_keyword(wurm, "trample")


def test_elder_land_wurm_can_attack_after_it_has_blocked(set_pool):
    """The point of the card: the loss outlives the turn it happened on, so a
    cleanup sweep that dropped it would leave the Wurm unable to attack ever."""
    wurm = Permanent(card=set_pool("LEG")["Elder Land Wurm"])
    attacker = Permanent(card=_vanilla("Bear", 2, 2))

    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[wurm])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game._settle()

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(1, [0])
    assert ok, msg


# ---------------------------------------------------------------------------
# Round 20: an "unless" whose alternative is not mana
# ---------------------------------------------------------------------------


def _swamp() -> CardDefinition:
    """A Swamp built here rather than taken from a pool: Legends printed no
    basic lands, and a per-set test reads its own set's cards."""
    return CardDefinition(
        name="Swamp", mana_cost="", cmc=0.0, type_line="Basic Land - Swamp",
        oracle_text="", colors=(), color_identity=("B",), keywords=(),
        produced_mana=("B",),
        raw={"name": "Swamp", "type_line": "Basic Land - Swamp"},
    )


def _mold_demon_board(set_pool, swamps: int, *, interactive: bool = False):
    """Mold Demon entering under a player who controls *swamps* Swamps.

    *interactive* is what decides whether the Swamps are *chosen*: a
    non-interactive seat takes the forced sacrifice's default the moment it is
    armed, so the prompt is only visible when a person owns the seat.
    """
    pool = set_pool("LEG")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=_swamp()) for _ in range(swamps)],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    if interactive:
        game.interactive_seats = {0}
    demon = Permanent(card=pool["Mold Demon"])
    game._put_permanent_onto_battlefield(0, demon, None)
    game._settle()
    return game, p1, demon


def _names(player) -> list[str]:
    return [perm.card.name for perm in player.battlefield]


def test_mold_demon_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Mold Demon"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "enters_battlefield"
    # An "unless" is an offer with a penalty, which is what `may` already says
    # — never a second fused kind, and never a cost the payer cannot express.
    assert trigger.instruction.kind == "may"
    (action,) = trigger.instruction.payload["action"]
    assert action.kind == "sacrifice_matching_permanent"
    # The printed number is payload on the one prompt.
    assert action.payload == {"filter": {"subtype_filter": "swamp"}, "count": 2}
    (otherwise,) = trigger.instruction.payload["otherwise"]
    assert otherwise.kind == "sacrifice_self"


def test_mold_demon_paying_the_alternative_sacrifices_two_swamps(set_pool):
    game, p1, demon = _mold_demon_board(set_pool, swamps=3)

    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert _names(p1) == ["Swamp", "Mold Demon"]
    assert [card.name for card in p1.graveyard] == ["Swamp", "Swamp"]
    assert game.is_on_battlefield(demon)


def test_mold_demon_asks_an_interactive_seat_which_two_swamps(set_pool):
    """The cost is two permanents its controller chooses (CR 701.21a), so a
    person owning the seat gets the standing prompt, sized by the printed
    number rather than by the one the lowering used to pass."""
    game, p1, demon = _mold_demon_board(set_pool, swamps=3, interactive=True)

    game.confirm_optional_pay(0, accept=True)
    game._settle()

    state = game.pending_sacrifice_state()
    assert state is not None
    assert state["count"] == 2
    assert len(state["valid_indices"]) == 3

    game.confirm_sacrifice(0, state["valid_indices"][:2])
    game._settle()

    assert _names(p1) == ["Swamp", "Mold Demon"]
    assert game.is_on_battlefield(demon)


def test_mold_demon_declining_sacrifices_itself(set_pool):
    game, p1, demon = _mold_demon_board(set_pool, swamps=3)

    game.confirm_optional_pay(0, accept=False)
    game._settle()

    assert not game.is_on_battlefield(demon)
    assert [card.name for card in p1.graveyard] == ["Mold Demon"]
    assert _names(p1) == ["Swamp", "Swamp", "Swamp"]


def test_mold_demon_with_one_swamp_is_never_offered_the_choice(set_pool):
    """Two is the printed number, so one Swamp cannot pay it. The offer is not
    made at all — accepting it would have run the cost half-paid and skipped
    the penalty the card prints for not paying."""
    game, p1, demon = _mold_demon_board(set_pool, swamps=1)

    assert not game.pending_choices
    assert not game.is_on_battlefield(demon)
    assert _names(p1) == ["Swamp"]


# ---------------------------------------------------------------------------
# Round 20: pay or be destroyed, and the rider that asks whether you were
# ---------------------------------------------------------------------------


_BLACK_MANA = {"W": 0, "U": 0, "B": 3, "R": 0, "G": 0, "C": 3}


def _cosmic_horror(set_pool, mana=None):
    horror = Permanent(card=set_pool("LEG")["Cosmic Horror"])
    p1 = PlayerState(
        name="P1", battlefield=[horror],
        mana_pool=dict(mana) if mana else {},
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, p1, horror


def test_cosmic_horror_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Cosmic Horror"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.kind == "upkeep_pay_or_destroy_self"
    payload = trigger.instruction.payload
    assert payload["mana"]["B"] == 3 and payload["mana"]["generic"] == 3
    # The rider is folded onto the same node, because it is a question about
    # what that node did.
    assert payload["damage_if_destroyed"] == 7


def test_cosmic_horror_paid_survives_and_spends_the_mana(set_pool):
    game, p1, horror = _cosmic_horror(set_pool, _BLACK_MANA)

    game.resolve_upkeep(0)
    game._settle()

    assert game.is_on_battlefield(horror)
    assert p1.life == 20
    assert p1.mana_pool["B"] == 0


def test_cosmic_horror_unpaid_is_destroyed_and_deals_seven(set_pool):
    game, p1, horror = _cosmic_horror(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert not game.is_on_battlefield(horror)
    assert [card.name for card in p1.graveyard] == ["Cosmic Horror"]
    assert p1.life == 13


@pytest.mark.parametrize("shield", [1])
def test_cosmic_horror_regenerated_takes_no_damage(set_pool, shield):
    """"If this creature is **destroyed this way**" — a creature that
    regenerated was not destroyed (CR 701.7c), so the rider does not happen.
    Nothing but the destroy itself can answer that, which is why the number
    rides the same instruction rather than being a second step."""
    game, p1, horror = _cosmic_horror(set_pool)
    horror.regeneration_shield = shield

    game.resolve_upkeep(0)
    game._settle()

    assert game.is_on_battlefield(horror)
    assert horror.tapped
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Round 21 — the CR 613 statics
# ---------------------------------------------------------------------------


def _basic(subtype: str) -> CardDefinition:
    line = f"Basic Land - {subtype}"
    return CardDefinition(
        name=subtype, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": subtype, "type_line": line},
    )


def test_dakkon_blackblade_counts_every_land_you_control(set_pool):
    """"…power and toughness are each equal to the number of lands you
    control." Every land, whatever it is called — and the opponent's do not
    count."""
    dakkon = Permanent(card=set_pool("LEG")["Dakkon Blackblade"])
    mine = [Permanent(card=_basic(name)) for name in ("Swamp", "Island", "Plains")]
    p1 = PlayerState(name="P1", battlefield=[dakkon] + mine)
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_basic("Forest"))])
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()

    assert (dakkon.effective_power, dakkon.effective_toughness) == (3, 3)

    game.remove_from_battlefield(mine[0])
    game._refresh_dynamic_creatures()
    assert (dakkon.effective_power, dakkon.effective_toughness) == (2, 2)


def test_arcades_sabboth_buffs_only_untapped_non_attacking_creatures(set_pool):
    """"Each untapped creature you control gets +0/+2 as long as it's not
    attacking." Both halves describe the same set, and a creature failing
    either one gets nothing. Arcades has no "other", so it buffs itself
    (CR 613)."""
    arcades = Permanent(card=set_pool("LEG")["Arcades Sabboth"])
    ready = _vanilla("Ready", 2, 2)
    resting = Permanent(card=ready)
    tapped = Permanent(card=ready)
    tapped.tapped = True
    charging = Permanent(card=ready)
    theirs = Permanent(card=ready)
    p1 = PlayerState(name="P1", battlefield=[arcades, resting, tapped, charging])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game._recompute_continuous_effects()

    assert resting.effective_toughness == 4
    assert tapped.effective_toughness == 2
    assert theirs.effective_toughness == 2

    charging.attacking = True
    assert charging.effective_toughness == 2
    assert resting.effective_toughness == 4

    game.remove_from_battlefield(arcades)
    game._recompute_continuous_effects()
    assert resting.effective_toughness == 2


def test_rabid_wombat_grows_with_every_aura_on_it(set_pool):
    """"This creature gets +2/+2 for each Aura attached to it." Printed 0/1."""
    from engine.auras import attach_aura, detach_aura

    def _aura(name: str) -> CardDefinition:
        return CardDefinition(
            name=name, mana_cost="{1}", cmc=1.0, type_line="Enchantment - Aura",
            oracle_text="Enchant creature", colors=(), color_identity=(),
            keywords=(), produced_mana=(),
            raw={"name": name, "type_line": "Enchantment - Aura"},
        )

    wombat = Permanent(card=set_pool("LEG")["Rabid Wombat"])
    auras = [Permanent(card=_aura(f"Aura {n}")) for n in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[wombat, *auras]),
        PlayerState(name="P2"),
    ])
    game._refresh_dynamic_creatures()
    assert (wombat.effective_power, wombat.effective_toughness) == (0, 1)

    for aura in auras:
        attach_aura(aura, wombat)
    game._refresh_dynamic_creatures()
    assert (wombat.effective_power, wombat.effective_toughness) == (4, 5)

    detach_aura(auras[0], wombat)
    game._refresh_dynamic_creatures()
    assert (wombat.effective_power, wombat.effective_toughness) == (2, 3)


# ---------------------------------------------------------------------------
# Bronze Horse (round 22) - a conditional static shield against targeting spells
# ---------------------------------------------------------------------------


def _bronze_horse_game(set_pool, *, with_friend: bool):
    """Bronze Horse and a Lightning Bolt in hand, with or without the other
    creature its condition counts.

    The Bolt comes from Alpha because Legends prints no spell that deals damage
    to a single chosen target - and what this card is about is the *targeting*,
    so the test needs a spell that does it.
    """
    horse = Permanent(card=set_pool("LEG")["Bronze Horse"])
    battlefield = [horse]
    if with_friend:
        battlefield.append(Permanent(card=_vanilla("Friend", 1, 1)))
    p1 = PlayerState(name="P1", battlefield=battlefield)
    p2 = PlayerState(name="P2", hand=[set_pool("LEA")["Lightning Bolt"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    return game, horse, p1, p2


def _bolt_the_horse(game) -> None:
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    assert result.supported, result.reason


def test_bronze_horse_is_supported(set_pool):
    """Its whole text: a conditional static prevention plus one keyword line."""
    program = compile_card_oracle(set_pool("LEG")["Bronze Horse"])
    assert program.supported, program.reason


def test_bronze_horse_prevents_a_spell_that_targets_it(set_pool):
    """"...prevent all damage that would be dealt to this creature by spells
    that target it." The narrowing is a fact about the spell on the stack, not
    a property of the source object, so it is read off the stack at the moment
    the damage would be dealt (CR 608.2m: the spell is still there)."""
    game, horse, _p1, _p2 = _bronze_horse_game(set_pool, with_friend=True)

    _bolt_the_horse(game)

    assert horse.damage_marked == 0
    assert game.controller_index_of(horse) == 0, "and it is still on the battlefield"


def test_bronze_horse_needs_the_other_creature_its_condition_counts(set_pool):
    """"**As long as you control another creature**" - CR 611.2. The clause is
    rechecked on the event rather than latched, so a Horse standing alone is a
    3/4 that dies to a Bolt like any other."""
    game, horse, _p1, _p2 = _bronze_horse_game(set_pool, with_friend=False)

    _bolt_the_horse(game)

    assert horse.damage_marked == 3, "the condition did not hold"


def test_bronze_horse_only_shields_what_the_spell_aimed_at(set_pool):
    """"spells that **target it**". The same Bolt pointed at the other creature
    is not shielded against - the shield is about this permanent being the
    chosen target, not about the spell existing."""
    game, horse, p1, _p2 = _bronze_horse_game(set_pool, with_friend=True)
    friend = p1.battlefield[1]

    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert result.supported, result.reason
    assert horse.damage_marked == 0, "it was never the target"
    assert friend not in game.controlled_by(0), "and the Bolt killed what it aimed at"


def test_bronze_horse_still_takes_damage_nothing_targeted_it_with(set_pool):
    """A shield admitting the phrase and then ignoring "spells that target it"
    would be a Horse that cannot be damaged at all. Combat damage from a
    creature is neither a spell nor a targeting, and it lands."""
    from engine.damage_events import deal_damage

    game, horse, _p1, _p2 = _bronze_horse_game(set_pool, with_friend=True)
    ogre = Permanent(card=_vanilla("Ogre", 3, 3))
    game.players[1].battlefield.append(ogre)

    dealt = deal_damage(game, {
        "recipient": horse, "amount": 3, "source": ogre, "combat": True,
    }).dealt
    assert dealt == 3


# ---------------------------------------------------------------------------
# Round 23 — triggers narrowed by a history or an ordinal
# ---------------------------------------------------------------------------


def _rig(p1_perms, p2_perms=(), *, p2_hand=()):
    from tests.helpers import _game

    p1 = PlayerState(name="P1", battlefield=list(p1_perms), life=20)
    p2 = PlayerState(
        name="P2", battlefield=list(p2_perms), life=20, hand=list(p2_hand)
    )
    return _game(p1, p2), p1, p2


def _ready(card) -> Permanent:
    from tests.helpers import _nosick

    return _nosick(Permanent(card=card))


def _attack_alone(game, attacker_seat, defender_seat):
    """Declare the seat's only creature as an attacker and deal combat damage."""
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = defender_seat
    game.declare_attackers(attacker_seat, [0], defender_seat)
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(attacker_seat)
    game.resolve_stack()


def test_whirling_dervish_grows_only_after_it_damaged_an_opponent(set_pool):
    """"At the beginning of each end step, **if this creature dealt damage to
    an opponent this turn**, put a +1/+1 counter on it." CR 603.4's
    intervening-if over a history no board read can answer — so the damage seam
    records whom each permanent damaged, and the gate asks that record."""
    dervish = _ready(set_pool("LEG")["Whirling Dervish"])
    game, _p1, p2 = _rig([dervish])

    _attack_alone(game, 0, 1)
    game.resolve_end_step(0)
    game.resolve_stack()

    assert p2.life == 19
    assert (dervish.effective_power, dervish.effective_toughness) == (2, 2)


def test_whirling_dervish_does_not_even_trigger_on_an_idle_turn(set_pool):
    """The other half of CR 603.4: a trigger whose intervening-if is false does
    not trigger at all. Not "resolves to nothing" — nothing goes on the stack,
    so nobody may respond to it and the Dervish stays a 1/1."""
    dervish = _ready(set_pool("LEG")["Whirling Dervish"])
    game, _p1, _p2 = _rig([dervish])

    game.active_player_index = 0
    game.resolve_end_step(0)

    assert game.stack == []
    assert (dervish.effective_power, dervish.effective_toughness) == (1, 1)


def test_axelrod_gunnarson_pays_off_when_a_creature_it_damaged_dies(set_pool, cards):
    """"Whenever a creature dealt damage by Axelrod Gunnarson this turn dies,
    you gain 1 life and Axelrod deals 1 damage to target player."

    The condition Sengir Vampire prints, spelled the pre-Sixth-Edition way —
    the card names itself — with a different effect behind it."""
    axelrod = _ready(set_pool("LEG")["Axelrod Gunnarson"])
    giant = _ready(cards["Hill Giant"])
    game, p1, p2 = _rig([axelrod], [giant])

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    game.combat_defending_player_index = 0
    game.declare_attackers(1, [0], 0)
    game._set_phase_and_step("combat", "declare_blockers")
    game.declare_blockers(0, {0: 0})
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(1)
    game.resolve_stack()

    assert giant not in game.controlled_by(1), "Axelrod killed it"
    assert p1.life == 21, "you gain 1 life"
    assert p2.life == 19, "and it deals 1 damage"


def test_axelrod_gunnarson_ignores_a_death_it_had_no_part_in(set_pool, cards):
    """The narrowing is the whole card: a creature Axelrod never damaged dying
    is not this trigger's event."""
    axelrod = _ready(set_pool("LEG")["Axelrod Gunnarson"])
    bear = _ready(cards["Grizzly Bears"])
    game, p1, p2 = _rig([axelrod], [bear])
    p1.hand.append(cards["Lightning Bolt"])

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    game.resolve_stack()

    assert bear not in game.controlled_by(1), "the Bolt killed it"
    assert p1.life == 20 and p2.life == 20, "but Axelrod had not damaged it"


def test_ichneumon_druid_exempts_the_first_instant_each_turn(set_pool, cards):
    """"Whenever an opponent casts an instant spell **other than the first
    instant spell that player casts each turn**, this creature deals 4 damage
    to that player."

    An ordinal exclusion, counted over the same set the trigger fires on."""
    druid = _ready(set_pool("LEG")["Ichneumon Druid"])
    hand = [cards["Healing Salve"], cards["Giant Growth"], cards["Lightning Bolt"]]
    game, _p1, p2 = _rig([druid], p2_hand=hand)
    game.active_player_index = 1

    lives = []
    for name in ("Healing Salve", "Giant Growth", "Lightning Bolt"):
        game.cast_from_hand(1, name, target_player_index=0)
        game.resolve_stack()
        lives.append(p2.life)

    assert lives[0] == 20, "the first instant is the one the card exempts"
    assert lives[1] == 16, "the second is not"
    assert lives[2] == 12, "and neither is the third"


def test_ichneumon_druid_counts_only_the_type_the_card_names(set_pool, cards):
    """The ordinal counts the *narrowed* set: a sorcery is neither an instant
    the trigger fires on nor one that uses up the exemption."""
    druid = _ready(set_pool("LEG")["Ichneumon Druid"])
    hand = [cards["Disintegrate"], cards["Healing Salve"]]
    game, _p1, p2 = _rig([druid], p2_hand=hand)
    game.active_player_index = 1

    game.cast_from_hand(1, "Disintegrate", target_player_index=0, x_value=1)
    game.resolve_stack()
    assert p2.life == 20, "a sorcery is not this trigger's event"

    game.cast_from_hand(1, "Healing Salve", target_player_index=0)
    game.resolve_stack()
    assert p2.life == 20, "and it did not spend the first-instant exemption"


def test_nicol_bolas_empties_the_hand_of_the_player_it_damaged(set_pool, cards):
    """"Whenever Nicol Bolas deals damage to an opponent, that player discards
    their hand." The card names itself, which is what kept both front ends from
    reading a condition this engine already announces."""
    bolas = _ready(set_pool("LEG")["Nicol Bolas"])
    hand = [cards["Healing Salve"], cards["Lightning Bolt"]]
    game, p1, p2 = _rig([bolas], p2_hand=hand)

    _attack_alone(game, 0, 1)

    assert p2.life == 13
    assert p2.hand == [], "the damaged player discarded their hand"
    assert p1.hand == [], "and not the ability's controller"


# ---------------------------------------------------------------------------
# Firestorm Phoenix (round 24) - CR 614 over a death, and the rider that costs
# the card more printed words than the replacement does.
# ---------------------------------------------------------------------------


def _phoenix_board(set_pool, *, extra_hand: list | None = None):
    """A Firestorm Phoenix on P1's board with a source that can kill it.
    Returns (game, phoenix, p1, p2)."""
    phoenix = Permanent(card=set_pool("LEG")["Firestorm Phoenix"])
    source = Permanent(card=_vanilla("Zap", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[phoenix], hand=list(extra_hand or []))
    p2 = PlayerState(name="P2", battlefield=[source])
    game = Game(players=[p1, p2])
    # A seat ordinal to compare "that player's next turn" against; nothing has
    # begun a turn in a hand-built game.
    game.seat_turn_counts = {0: 1, 1: 0}
    game.active_player_index = 0
    game.enforce_mana_costs = False
    return game, phoenix, p1, p2


def _kill(game, permanent) -> None:
    game._mark_damage_on_permanent(permanent, 9, source=None, combat=False)
    game.check_state_based_actions()


def test_firestorm_phoenix_goes_to_hand_instead_of_the_graveyard(set_pool):
    """"If this creature would die, return it to its owner's hand instead." The
    graveyard never sees it, which is the whole difference between a CR 614
    replacement and a dies-trigger."""
    game, phoenix, p1, _p2 = _phoenix_board(set_pool)

    _kill(game, phoenix)

    assert list(game.controlled_by(0)) == []
    assert p1.graveyard == []
    assert [card.name for card in p1.hand] == ["Firestorm Phoenix"]


def test_firestorm_phoenix_cannot_be_played_until_its_owners_next_turn(set_pool):
    """The rider, executed rather than parsed: "that player ... can't play it"."""
    from engine.hand_locks import locked_hand_indices

    game, phoenix, p1, _p2 = _phoenix_board(set_pool)
    _kill(game, phoenix)

    assert locked_hand_indices(game, 0) == frozenset({0})
    refused = game.cast_from_hand(0, "Firestorm Phoenix")
    assert not refused.supported
    assert "can't be played" in refused.details
    assert [card.name for card in p1.hand] == ["Firestorm Phoenix"], "still held"


def test_firestorm_phoenixs_lock_survives_the_opponents_turn(set_pool):
    """"Until **that player's** next turn" - an opponent's turn passing is not
    that player's next turn."""
    from engine.hand_locks import locked_hand_indices

    game, phoenix, _p1, _p2 = _phoenix_board(set_pool)
    _kill(game, phoenix)

    game.begin_turn_bookkeeping(1)
    assert locked_hand_indices(game, 0) == frozenset({0})

    game.begin_turn_bookkeeping(0)
    assert locked_hand_indices(game, 0) == frozenset()


def test_firestorm_phoenix_can_be_cast_once_the_lock_expires(set_pool):
    """And the restriction really lifts - a lock that never ended would be a
    card removed from the game rather than returned to a hand."""
    game, phoenix, p1, _p2 = _phoenix_board(set_pool)
    _kill(game, phoenix)
    game.begin_turn_bookkeeping(1)
    game.begin_turn_bookkeeping(0)

    assert game.cast_from_hand(0, "Firestorm Phoenix").supported
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Firestorm Phoenix"]
    assert p1.hand == []


def test_firestorm_phoenix_locks_one_copy_not_the_card(set_pool):
    """Two copies in a hand are the same CardDefinition object, so the record
    has to be a count: with one locked the player may still play the other."""
    from engine.hand_locks import locked_hand_indices

    pool = set_pool("LEG")
    game, phoenix, p1, _p2 = _phoenix_board(
        set_pool, extra_hand=[pool["Firestorm Phoenix"]]
    )
    _kill(game, phoenix)

    assert len(p1.hand) == 2
    assert locked_hand_indices(game, 0) == frozenset({0}), "one of the two"
    assert game.cast_from_hand(0, "Firestorm Phoenix").supported
    assert [card.name for card in p1.hand] == ["Firestorm Phoenix"], "the locked one"


def test_firestorm_phoenix_leaves_another_creatures_death_alone(set_pool):
    """The event outside the sentence: "**this creature**" is the Phoenix, and a
    bear dying beside it still goes to the graveyard."""
    game, _phoenix, _p1, p2 = _phoenix_board(set_pool)
    bear = Permanent(card=_vanilla("Bear", 2, 2))
    p2.battlefield.append(bear)

    _kill(game, bear)

    assert [card.name for card in p2.graveyard] == ["Bear"]
    assert p2.hand == []



# ---------------------------------------------------------------------------
# Round 24 — Lesser Werewolf: a power gate, a P/T counter that is not +1/+1,
# and a target named by its combat relation to the ability's own source.
# ---------------------------------------------------------------------------


def _werewolf_in_combat(set_pool):
    """Lesser Werewolf blocking one of two identically named attackers.

    The bystander shares the blocked creature's name so that a handler locating
    its victim by value rather than by identity would find the wrong one — and
    it is *not* in combat with the Werewolf, which is the whole restriction.
    """
    werewolf = Permanent(card=set_pool("LEG")["Lesser Werewolf"])
    blocked = Permanent(card=_vanilla("Ogre", 3, 3))
    bystander = Permanent(card=_vanilla("Ogre", 3, 3))
    p1 = PlayerState(name="P1", battlefield=[blocked, bystander])
    p2 = PlayerState(name="P2", battlefield=[werewolf])
    p2.mana_pool.update({"B": 3})
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    return game, werewolf, blocked, bystander


def test_lesser_werewolf_shrinks_the_creature_it_is_in_combat_with(set_pool):
    game, werewolf, blocked, bystander = _werewolf_in_combat(set_pool)

    result = game.activate_permanent_ability(
        1, "Lesser Werewolf", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported, result.reason
    # The printed counter is -0/-1, not +1/+1: a handler that placed the kind
    # it has always placed would have made the blocker bigger.
    assert blocked.effective_toughness == 2
    assert blocked.effective_power == 3
    # The source shrank itself by the printed -1/-0.
    assert werewolf.effective_power == 1
    assert werewolf.effective_toughness == 4


def test_lesser_werewolf_offers_only_the_creature_it_is_in_combat_with(set_pool):
    """"…blocking or blocked by this creature." The bystander is attacking and
    shares the blocked creature's name — neither fact makes it a legal target,
    and the picker is derived from the compiled program, so it offers exactly
    what the resolution will accept."""
    game, werewolf, blocked, bystander = _werewolf_in_combat(set_pool)

    spec = game.activation_target_spec(1, 0)

    offered = {(t["seat"], t["index"]) for t in spec["valid_targets"]}
    assert offered == {(0, 0)}, spec["valid_targets"]


def test_lesser_werewolf_puts_no_counter_on_a_creature_outside_the_combat(set_pool):
    """CR 608.2b: the relation is re-checked as the ability resolves, so a
    creature named outside it takes nothing rather than a counter meant for the
    blocker with the same printed name."""
    game, werewolf, blocked, bystander = _werewolf_in_combat(set_pool)

    game.activate_permanent_ability(
        1, "Lesser Werewolf", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert bystander.effective_toughness == 3
    assert blocked.effective_toughness == 3


def test_lesser_werewolf_is_refused_outside_the_declare_blockers_step(set_pool):
    """"Activate only during the declare blockers step." A restriction nothing
    enforced would be an ability that works more often than the card allows."""
    werewolf = Permanent(card=set_pool("LEG")["Lesser Werewolf"])
    foe = Permanent(card=_vanilla("Ogre", 3, 3))
    p1 = PlayerState(name="P1", battlefield=[foe])
    p2 = PlayerState(name="P2", battlefield=[werewolf])
    p2.mana_pool.update({"B": 3})
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        1, "Lesser Werewolf", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert foe.effective_toughness == 3


def test_lesser_werewolf_stops_when_its_own_power_reaches_zero(set_pool):
    """"If this creature's power is 1 or more" — the gate reads the *computed*
    power (CR 613 layer 7), so the second activation sees what the first did."""
    game, werewolf, blocked, bystander = _werewolf_in_combat(set_pool)

    for _ in range(2):
        game.activate_permanent_ability(
            1, "Lesser Werewolf", target_player_index=0, target_permanent_index=0
        )
        game._settle()
    assert werewolf.effective_power == 0
    assert blocked.effective_toughness == 1

    # Power 0: the condition fails, so neither half of the sentence happens.
    game.activate_permanent_ability(
        1, "Lesser Werewolf", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    assert werewolf.effective_power == 0
    assert blocked.effective_toughness == 1


# ---------------------------------------------------------------------------
# Round 25 — "bands with other" (CR 702.22b). Master of the Hunt's token
# carries the ability; Shelkin Brownie takes it away.
# ---------------------------------------------------------------------------


_WOLF_BAND = "bands with other creatures named wolves of the hunt"


def _legendary(name: str, colors: tuple[str, ...] = ("G",)):
    type_line = "Legendary Creature - Test"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _wolves(set_pool, count: int = 2):
    """Activate Master of the Hunt *count* times and hand back the tokens."""
    from tests.helpers import _nosick

    master = Permanent(card=set_pool("LEG")["Master of the Hunt"])
    p1 = PlayerState(name="P1", battlefield=[master])
    p1.mana_pool.update({"G": 20, "C": 20})
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    for _ in range(count):
        result = game.activate_permanent_ability(0, "Master of the Hunt")
        assert result.supported, result
        game._settle()
    wolves = [p for p in p1.battlefield if p.card.name == "Wolves Of The Hunt"]
    assert len(wolves) == count, [p.card.name for p in p1.battlefield]
    # The tokens were created this turn; the band is about what they may be
    # declared as, not about CR 302.6.
    for wolf in wolves:
        _nosick(wolf)
    return game, p1, wolves


def test_master_of_the_hunt_makes_wolves_that_carry_the_band(set_pool):
    """The quoted ability on the token is read by the compiler as the token's
    printed text, so the band arrives with the token rather than being stamped
    on by a handler that knows the card."""
    _game, _p1, pack = _wolves(set_pool)

    assert all(w.has_keyword(_WOLF_BAND) for w in pack)
    # It is not banding: the parenthetical in CR 702.22c is explicit.
    assert not any(w.has_keyword("banding") for w in pack)


def test_two_wolves_attack_as_a_band(set_pool):
    game, _p1, _pack = _wolves(set_pool)
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers

    ok, msg = game.declare_attackers(0, [1, 2], bands=[[1, 2]])
    assert ok, msg
    assert game.combat_bands == [[1, 2]]


def test_a_creature_not_named_wolves_of_the_hunt_cannot_join(set_pool):
    """The quality is a *name*, and it is the only thing that admits a member.
    A colour dropped from the filter would let anything green in; a name
    dropped would let anything in at all."""
    game, p1, _pack = _wolves(set_pool)
    p1.battlefield.append(Permanent(card=_vanilla("Timber Wolf", 1, 1)))
    game._sync_control()
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, _ = game.declare_attackers(0, [1, 2, 3], bands=[[1, 2, 3]])
    assert not ok


def test_shelkin_brownie_strips_a_granted_band(set_pool):
    """"Target creature loses all "bands with other" abilities until end of
    turn." The *family*, not one quality — the printed clause names no quality
    at all, so a removal that took the word literally would take nothing."""
    pool = set_pool("LEG")
    brownie = Permanent(card=pool["Shelkin Brownie"])
    guildhouse = Permanent(card=pool["Adventurers' Guildhouse"])
    legend = Permanent(card=_legendary("Green Legend"))
    p1 = PlayerState(name="P1", battlefield=[guildhouse, legend])
    p2 = PlayerState(name="P2", battlefield=[brownie])
    game = Game(players=[p1, p2])
    game._recalculate_lord_buffs()
    assert legend.has_keyword("bands with other legendary creatures")

    game.start_turn(0)
    game._close_current_priority_step()
    result = game.activate_permanent_ability(
        1, "Shelkin Brownie", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert result.supported, result
    assert not legend.has_keyword("bands with other legendary creatures")


def test_shelkin_brownie_leaves_plain_banding_alone(set_pool):
    """CR 702.22b runs one way: losing banding loses the bands, but losing the
    bands is not losing banding. Shelkin Brownie prints only the second half."""
    from engine.keywords import grant_keyword

    pool = set_pool("LEG")
    brownie = Permanent(card=pool["Shelkin Brownie"])
    bander = Permanent(card=_vanilla("Bander", 2, 2))
    grant_keyword(bander, "banding")
    p1 = PlayerState(name="P1", battlefield=[bander])
    p2 = PlayerState(name="P2", battlefield=[brownie])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        1, "Shelkin Brownie", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported, result
    assert bander.has_keyword("banding")


def test_shelkin_brownie_breaks_up_the_wolf_band(set_pool):
    """End to end: with the ability gone the band is no longer declarable."""
    pool = set_pool("LEG")
    game, p1, _pack = _wolves(set_pool)
    # Two Brownies, because the ability's cost is {T}: one creature can strip
    # one wolf, and a band needs both members to lose the ability.
    for _ in range(2):
        p1.battlefield.append(Permanent(card=pool["Shelkin Brownie"]))
    game._sync_control()
    for offset, wolf_index in enumerate((1, 2)):
        result = game.activate_permanent_ability(
            0, "Shelkin Brownie", target_player_index=0,
            target_permanent_index=wolf_index,
            permanent_index=3 + offset,
        )
        game._settle()
        assert result.supported, result
    game.advance_combat_phase()
    game.advance_combat_phase()

    ok, _ = game.declare_attackers(0, [1, 2], bands=[[1, 2]])
    assert not ok
