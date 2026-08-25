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
