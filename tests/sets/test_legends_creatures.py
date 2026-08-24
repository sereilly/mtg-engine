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
