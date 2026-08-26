"""Per-card tests for Legends' creatures, from round 20 onward.

Split from `test_legends_creatures.py` at the 2,600-line readability cap. The
type axis has no room left here — every card in both files is a creature — so
the cut is a **round boundary**, which `tests/sets/README.md` names as the next
division once a printed type outgrows a file. Each round section is
self-contained and written up in ROADMAP.md under the round that bought its
cards, so cutting between sections keeps every section whole and keeps a test
findable from its round.
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
# Round 25 — "chooses a card name, then reveals the top card of their library"
# ---------------------------------------------------------------------------


def _petra_game(set_pool, library: list[CardDefinition]):
    """Petra Sphinx on seat 1, aimed at seat 0, whose library is *library*."""
    sphinx = Permanent(card=set_pool("LEG")["Petra Sphinx"])
    victim = PlayerState(name="P1", library=list(library))
    game = Game(players=[victim, PlayerState(name="P2", battlefield=[sphinx])])
    game.start_turn(1)
    return game, victim


def test_petra_sphinx_puts_a_correctly_named_card_into_its_owners_hand(set_pool):
    """The chooser, the library, the hand and the graveyard are all the
    *targeted* player's — the card never says "you"."""
    top = _vanilla("Guessed Card", 1, 1)
    game, victim = _petra_game(set_pool, [top, _vanilla("Under It", 1, 1)])

    result = game.activate_permanent_ability(1, "Petra Sphinx", target_player_index=0)
    assert result.supported, result.details
    game._settle()

    pending = next(iter(game.pending_choices_of("name_then_reveal_top")), None)
    assert pending is not None and pending.player_index == 0
    assert game.confirm_name_then_reveal_top(0, "Guessed Card")

    assert [c.name for c in victim.hand] == ["Guessed Card"]
    assert victim.graveyard == []
    assert len(victim.library) == 1


def test_petra_sphinx_mills_a_wrongly_named_card(set_pool):
    """The miss half. A name no card in the game bears is a legal choice
    (CR 202.1) and simply misses — it is not refused."""
    top = _vanilla("Guessed Card", 1, 1)
    game, victim = _petra_game(set_pool, [top, _vanilla("Under It", 1, 1)])

    game.activate_permanent_ability(1, "Petra Sphinx", target_player_index=0)
    game._settle()
    assert game.confirm_name_then_reveal_top(0, "Not In This Game")

    assert victim.hand == []
    assert [c.name for c in victim.graveyard] == ["Guessed Card"]
    assert len(victim.library) == 1


def test_petra_sphinx_compares_the_revealed_card_not_the_one_beneath_it(set_pool):
    """Naming the *second* card is a miss: the reveal is the top card only, and
    a search of the whole library would make this a hit."""
    game, victim = _petra_game(
        set_pool, [_vanilla("Top", 1, 1), _vanilla("Second", 1, 1)]
    )

    game.activate_permanent_ability(1, "Petra Sphinx", target_player_index=0)
    game._settle()
    assert game.confirm_name_then_reveal_top(0, "Second")

    assert victim.hand == []
    assert [c.name for c in victim.graveyard] == ["Top"]


def test_petra_sphinx_asks_nothing_of_an_empty_library(set_pool):
    """No card to reveal means no name to choose — the ability resolves and
    leaves no prompt owed."""
    game, victim = _petra_game(set_pool, [])

    game.activate_permanent_ability(1, "Petra Sphinx", target_player_index=0)
    game._settle()

    assert not list(game.pending_choices_of("name_then_reveal_top"))
    assert victim.hand == [] and victim.graveyard == []


def test_petra_sphinx_default_names_the_commonest_card_in_that_library(set_pool):
    """A non-interactive seat's answer. A player knows what is in their own
    library, only not its order (CR 400.2), so naming its commonest remaining
    card is a choice a human could make — and it is deterministic, which a
    seeded replay needs."""
    game, victim = _petra_game(set_pool, [
        _vanilla("Rare Thing", 1, 1),
        _vanilla("Common Thing", 1, 1),
        _vanilla("Common Thing", 1, 1),
    ])

    game.activate_permanent_ability(1, "Petra Sphinx", target_player_index=0)
    game._settle()
    game.auto_resolve_pending_choices(kinds=("name_then_reveal_top",))

    # "Common Thing" was named; the top card was "Rare Thing", so it misses.
    assert [c.name for c in victim.graveyard] == ["Rare Thing"]
    assert victim.hand == []
    assert not list(game.pending_choices_of("name_then_reveal_top"))



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


# ---------------------------------------------------------------------------
# Quarum Trench Gnomes (round 26) — a standing change to what a land produces
# ---------------------------------------------------------------------------


def _gnomes_game(set_pool, land_name="Plains", extra=()):
    pool = set_pool("LEG")
    gnomes = Permanent(card=pool["Quarum Trench Gnomes"])
    lands = [Permanent(card=set_pool("LEA")[land_name])]
    lands += [Permanent(card=set_pool("LEA")[name]) for name in extra]
    p1 = PlayerState(name="P1", battlefield=[gnomes, *lands])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    gnomes.summoning_sick = False
    return game, p1, gnomes, lands


def _aim_gnomes(game, index):
    result = game.activate_permanent_ability(
        0, "Quarum Trench Gnomes", permanent_index=0,
        target_permanent_index=index, target_player_index=0,
    )
    game._settle()
    return result


def test_quarum_trench_gnomes_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Quarum Trench Gnomes"])
    assert program.supported, program.reason


def test_quarum_trench_gnomes_turns_a_plains_colorless(set_pool):
    """The whole card: tap the Gnomes, then tap the Plains and see what came
    out. Asking the compiler alone would have been happy with an ability that
    resolved and changed nothing."""
    game, p1, _gnomes, lands = _gnomes_game(set_pool)
    plains = lands[0]
    assert plains.effective_produced_mana == ("W",)

    assert _aim_gnomes(game, 1).supported
    assert plains.effective_produced_mana == ("C",)

    p1.mana_pool = {sym: 0 for sym in ("W", "U", "B", "R", "G", "C")}
    game.tap_land_for_mana(0, "Plains", permanent_index=1)
    assert p1.mana_pool["C"] == 1
    assert p1.mana_pool["W"] == 0, "the white mana is replaced, not added to"


def test_quarum_trench_gnomes_changes_only_the_land_it_named(set_pool):
    """"Target Plains" is one land, not the type — a second Plains keeps making
    white, which is what separates this from a board-wide static."""
    game, p1, _gnomes, lands = _gnomes_game(set_pool, extra=("Plains",))

    assert _aim_gnomes(game, 1).supported

    assert lands[0].effective_produced_mana == ("C",)
    assert lands[1].effective_produced_mana == ("W",), "the other Plains is untouched"


def test_quarum_trench_gnomes_refuses_a_land_that_is_not_a_plains(set_pool):
    """The printed noun narrows the target, and the gate that reads it is the
    one the picker reads (CR 602.2b) — so the ability is refused with the
    Gnomes still untapped rather than activated onto a land it cannot change."""
    game, _p1, gnomes, lands = _gnomes_game(set_pool, land_name="Swamp")

    result = _aim_gnomes(game, 1)

    assert not result.supported
    assert not gnomes.tapped, "nothing was paid"
    assert lands[0].effective_produced_mana == ("B",)


def test_quarum_trench_gnomes_effect_lasts_past_the_turn(set_pool):
    """"(This effect lasts indefinitely.)" — no duration, so no cleanup sweep
    takes it back."""
    game, p1, _gnomes, lands = _gnomes_game(set_pool)
    assert _aim_gnomes(game, 1).supported

    game.resolve_cleanup_step(0)
    game.start_turn(1)
    game.start_turn(0)

    assert lands[0].effective_produced_mana == ("C",)


def test_quarum_trench_gnomes_swap_is_read_by_the_payment_planner(set_pool):
    """`plan_payment` asks what a land can produce through the same property,
    so a Plains the Gnomes have changed no longer pays a {W} pip."""
    from engine.mana_payment import plan_payment

    game, p1, _gnomes, lands = _gnomes_game(set_pool)
    empty = {sym: 0 for sym in ("W", "U", "B", "R", "G", "C")}
    assert plan_payment(empty, lands, {"W": 1}) is not None

    assert _aim_gnomes(game, 1).supported

    assert plan_payment(empty, lands, {"W": 1}) is None
    assert plan_payment(empty, lands, {"generic": 1}) is not None


# ---------------------------------------------------------------------------
# Nebuchadnezzar (round 26) — a named card, a random reveal, and "this way"
# ---------------------------------------------------------------------------


def _nebuchadnezzar_game(set_pool, opponent_hand, *, active=0):
    leg = set_pool("LEG")
    lea = set_pool("LEA")
    king = Permanent(card=leg["Nebuchadnezzar"])
    p1 = PlayerState(name="P1", battlefield=[king])
    p2 = PlayerState(name="P2", hand=[lea[name] for name in opponent_hand])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(active)
    king.summoning_sick = False
    return game, p1, p2


def _name(game, x, named, *, seat=1):
    result = game.activate_permanent_ability(
        0, "Nebuchadnezzar", permanent_index=0,
        target_player_index=seat, x_value=x,
    )
    game._settle()
    if result.supported and game.pending_choices:
        game.confirm_name_and_random_reveal(0, named)
    return result


def test_nebuchadnezzar_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Nebuchadnezzar"])
    assert program.supported, program.reason


def test_nebuchadnezzar_discards_every_revealed_copy(set_pool):
    """X equal to the whole hand reveals all of it, so what is left is exactly
    the cards that do not carry the named name."""
    game, _p1, p2 = _nebuchadnezzar_game(
        set_pool, ["Plains", "Plains", "Plains", "Swamp", "Swamp"],
    )

    assert _name(game, 5, "Plains").supported

    assert sorted(c.name for c in p2.hand) == ["Swamp", "Swamp"]
    assert sorted(c.name for c in p2.graveyard) == ["Plains"] * 3


def test_nebuchadnezzar_discards_only_what_the_reveal_turned_up(set_pool):
    """"…all cards with that name **revealed this way**." Four copies in hand
    and X of 1: exactly one is revealed, so exactly one is discarded. A discard
    over the hand rather than over the revealed pile would take all four and
    make the randomness decoration."""
    game, _p1, p2 = _nebuchadnezzar_game(set_pool, ["Plains"] * 4)

    assert _name(game, 1, "Plains").supported

    assert len(p2.hand) == 3
    assert len(p2.graveyard) == 1


def test_nebuchadnezzar_a_name_nothing_matches_discards_nothing(set_pool):
    """CR 202.1 lets a player name any card, including one nobody holds — the
    reveal still happens and nothing is discarded."""
    game, _p1, p2 = _nebuchadnezzar_game(set_pool, ["Plains", "Swamp"])

    assert _name(game, 2, "Black Lotus").supported

    assert len(p2.hand) == 2 and p2.graveyard == []


def test_nebuchadnezzar_x_larger_than_the_hand_reveals_the_hand(set_pool):
    """X is announced before the hand is looked at, so it may exceed it. The
    reveal is capped rather than refused."""
    game, _p1, p2 = _nebuchadnezzar_game(set_pool, ["Plains"])

    assert _name(game, 6, "Plains").supported

    assert p2.hand == [] and len(p2.graveyard) == 1


def test_nebuchadnezzar_activates_only_during_your_turn(set_pool):
    """"Activate only during your turn." (CR 602.5.) Refused with nothing
    paid."""
    game, _p1, p2 = _nebuchadnezzar_game(set_pool, ["Plains"], active=1)
    king = game.players[0].battlefield[0]

    result = _name(game, 1, "Plains")

    assert not result.supported
    assert not king.tapped, "nothing was paid"
    assert len(p2.hand) == 1


def test_nebuchadnezzar_names_an_opponent_and_only_an_opponent(set_pool):
    """"Target **opponent**" — the picker offers no other seat, and an ability
    aimed at its own controller reveals nothing."""
    game, p1, _p2 = _nebuchadnezzar_game(set_pool, ["Plains"])
    p1.hand = [set_pool("LEA")["Plains"]] * 3
    offered = game._enumerate_targets(
        0, set_pool("LEG")["Nebuchadnezzar"],
        {"kind": "player", "opponents_only": True}, for_cast=False,
    )

    assert [t["seat"] for t in offered] == [1]

    _name(game, 3, "Plains", seat=0)
    assert len(p1.hand) == 3, "the controller's own hand is untouched"



# ---------------------------------------------------------------------------
# Shimian Night Stalker (round 26) — damage redirected, not prevented
# ---------------------------------------------------------------------------


def _night_stalker_combat(set_pool, attackers=(2, 3)):
    """The Stalker's controller (seat 0) being attacked by *attackers*, each a
    vanilla creature of that power, with the ability's {B} already in the pool.

    The attack is declared before the ability is activated, because the ability
    names a *target attacking creature* — there is nothing legal to point it at
    until the attackers step has run.
    """
    stalker = Permanent(card=set_pool("LEG")["Shimian Night Stalker"])
    raiders = [
        Permanent(card=_vanilla(f"Raider {index}", power, power))
        for index, power in enumerate(attackers)
    ]
    p1 = PlayerState(name="P1", battlefield=[stalker])
    p2 = PlayerState(name="P2", battlefield=raiders)
    game = Game(players=[p1, p2])
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(1, list(range(len(raiders))))
    assert ok, msg
    p1.mana_pool.update({"B": 1})
    return game, p1, stalker, raiders


def _through_combat_damage(game):
    game.advance_combat_phase()   # declare_blockers
    ok, msg = game.declare_blockers(0, {})
    assert ok, msg
    game.advance_combat_phase()   # combat_damage
    game._settle()


def test_shimian_night_stalker_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Shimian Night Stalker"])

    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "redirect_damage_from_target_until_eot"


def test_shimian_night_stalker_takes_the_named_attackers_damage(set_pool):
    """"All damage that would be dealt to you this turn by target attacking
    creature is dealt to this creature instead." The damage is *moved*: the
    player takes none of it and the Stalker is marked with all of it."""
    game, p1, stalker, _raiders = _night_stalker_combat(set_pool, attackers=(2,))
    result = game.activate_permanent_ability(
        0, "Shimian Night Stalker", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result

    _through_combat_damage(game)

    assert p1.life == 20
    assert stalker.damage_marked == 2


def test_shimian_night_stalker_leaves_every_other_attacker_alone(set_pool):
    """The narrowing is the card. One attacker was named; the other's damage
    goes through untouched, which is what says the target was honoured rather
    than dropped."""
    game, p1, stalker, _raiders = _night_stalker_combat(set_pool, attackers=(2, 3))
    game.activate_permanent_ability(
        0, "Shimian Night Stalker", target_player_index=1, target_permanent_index=0
    )

    _through_combat_damage(game)

    assert p1.life == 17, "only the unnamed raider's 3 damage arrived"
    assert stalker.damage_marked == 2


def test_shimian_night_stalker_redirects_damage_outside_combat_too(set_pool):
    """"All damage", not "all combat damage". An ability of the named creature
    is redirected exactly as its combat damage is."""
    game, p1, stalker, raiders = _night_stalker_combat(set_pool, attackers=(2,))
    game.activate_permanent_ability(
        0, "Shimian Night Stalker", target_player_index=1, target_permanent_index=0
    )

    game._deal_damage_to_player(p1, 4, source=raiders[0])

    assert p1.life == 20
    assert stalker.damage_marked == 4


def test_shimian_night_stalker_gone_means_the_damage_lands_as_normal(set_pool):
    """CR 614.9: with nothing to redirect the damage *to*, the effect does
    nothing — which is the player taking it, not the damage disappearing."""
    game, p1, stalker, raiders = _night_stalker_combat(set_pool, attackers=(2,))
    game.activate_permanent_ability(
        0, "Shimian Night Stalker", target_player_index=1, target_permanent_index=0
    )
    game.remove_from_battlefield(stalker)

    game._deal_damage_to_player(p1, 4, source=raiders[0])

    assert p1.life == 16


def test_shimian_night_stalker_redirect_expires_with_the_turn(set_pool):
    """"…this turn." The record carries its own lifetime, so the cleanup sweep
    ends it without a turn step naming this card."""
    game, p1, stalker, raiders = _night_stalker_combat(set_pool, attackers=(2,))
    game.activate_permanent_ability(
        0, "Shimian Night Stalker", target_player_index=1, target_permanent_index=0
    )
    game.resolve_cleanup_step(1)

    game._deal_damage_to_player(p1, 4, source=raiders[0])

    assert p1.life == 16
    assert stalker.damage_marked == 0


# ---------------------------------------------------------------------------
# Round 27 — creature abilities
# ---------------------------------------------------------------------------


def _r27_land(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _r27_attack_into(attacker: Permanent, defender_board: list[Permanent]):
    """Attack with *attacker* alone; the defender's first permanent tries to
    block it. Returns whether the declaration was legal."""
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=defender_board)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    return game.declare_blockers(1, {0: 0})


def test_livonya_silone_is_unblockable_through_a_legendary_land(set_pool):
    """"Legendary landwalk" — CR 702.14a's quality-first shape, where the
    quality is a supertype rather than a land subtype welded into the word."""
    blocker = Permanent(card=_vanilla("Blocker", 2, 2))
    ok, msg = _r27_attack_into(
        Permanent(card=set_pool("LEG")["Livonya Silone"]),
        [blocker, Permanent(card=_r27_land("Karakas", "Legendary Land"))],
    )

    assert not ok, msg


def test_livonya_silone_is_blockable_when_the_land_is_not_legendary(set_pool):
    """The control. A land alone is not the quality the ability names, so the
    restriction does not apply — a supertype dropped from the payload would
    have made every land answer and every block illegal."""
    blocker = Permanent(card=_vanilla("Blocker", 2, 2))
    ok, msg = _r27_attack_into(
        Permanent(card=set_pool("LEG")["Livonya Silone"]),
        [blocker, Permanent(card=_r27_land("Wasteland", "Land"))],
    )

    assert ok, msg


def test_livonya_silone_is_blockable_with_no_land_at_all(set_pool):
    blocker = Permanent(card=_vanilla("Blocker", 2, 2))
    ok, msg = _r27_attack_into(
        Permanent(card=set_pool("LEG")["Livonya Silone"]), [blocker]
    )

    assert ok, msg


def _r27_gwendlyn(set_pool, active_seat: int):
    leg = set_pool("LEG")
    gwendlyn = Permanent(card=leg["Gwendlyn Di Corci"])
    p1 = PlayerState(name="P1", battlefield=[gwendlyn])
    p2 = PlayerState(
        name="P2",
        hand=[leg["Livonya Silone"], leg["Hyperion Blacksmith"], leg["Time Elemental"]],
    )
    game = Game(players=[p1, p2])
    game.start_turn(active_seat)
    game._close_current_priority_step()
    return game, p2


def test_gwendlyn_di_corci_discards_one_card_at_random(set_pool):
    """"Target player discards a card at random." The count is payload on the
    random handler — the chooser is what picks the handler, and it is nobody
    here exactly as it is for Mind Twist's X."""
    game, victim = _r27_gwendlyn(set_pool, active_seat=0)

    result = game.activate_permanent_ability(
        0, "Gwendlyn Di Corci", target_player_index=1
    )
    game._settle()

    assert result.supported
    assert len(victim.hand) == 2


def test_gwendlyn_di_corci_cannot_be_activated_on_an_opponents_turn(set_pool):
    """"Activate only during your turn." (CR 602.5.) A restriction nothing
    enforced would be an ability that works more often than the card allows,
    which is the silent direction."""
    game, victim = _r27_gwendlyn(set_pool, active_seat=1)

    result = game.activate_permanent_ability(
        0, "Gwendlyn Di Corci", target_player_index=1
    )
    game._settle()

    assert not result.supported
    assert len(victim.hand) == 3


def _r27_blacksmith(set_pool):
    leg = set_pool("LEG")
    smith = Permanent(card=leg["Hyperion Blacksmith"])
    mine = Permanent(card=leg["Alchor's Tomb"])
    theirs = Permanent(card=leg["Knowledge Vault"])
    theirs.tapped = True
    p1 = PlayerState(name="P1", battlefield=[smith, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    return game, smith, mine, theirs


def test_hyperion_blacksmith_untaps_an_opponents_artifact(set_pool):
    game, _smith, _mine, theirs = _r27_blacksmith(set_pool)

    game.activate_permanent_ability(
        0, "Hyperion Blacksmith", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert not theirs.tapped


def test_hyperion_blacksmith_offers_only_the_opponents_artifacts(set_pool):
    """"…an opponent controls" is a seat comparison, so the picker carries it
    rather than the permanent matcher. A picker that offered the activator's own
    own artifact would let them choose a target the effect then declines to
    affect — and the resolution agrees, so naming it does nothing."""
    game, smith, mine, _theirs = _r27_blacksmith(set_pool)
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    ability = compile_card_oracle(smith.card).activated_abilities[0]
    spec = derive_activation_spec(ability)
    offered = game._enumerate_targets(
        0, smith.card, spec, for_cast=False,
        ability_instruction=ability.instruction, ability_source=smith,
    )

    assert spec["opponent_only"] is True
    assert [t["seat"] for t in offered] == [1]

    game.activate_permanent_ability(
        0, "Hyperion Blacksmith", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    game.auto_resolve_pending_optional_pays()
    game._settle()

    assert not mine.tapped

# Round 27 — Beasts of Bogardan. "This creature gets +1/+1 as long as an
# opponent controls a nontoken white permanent." A conditional static (CR 613
# layer 7c) whose condition is a printed noun phrase about *another player's*
# board — read by the grammar's noun parser and answered by `subject_matches`,
# the one place a phrase is tested against a permanent.
# ---------------------------------------------------------------------------


def _r27_permanent(name: str, colors: tuple[str, ...], *, token: bool = False) -> Permanent:
    card = CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Bear", oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    return Permanent(card=card, metadata={"is_token": True} if token else {})


def _r27_bogardan_board(set_pool):
    beast = Permanent(card=set_pool("LEG")["Beasts of Bogardan"])
    p1 = PlayerState(name="P1", battlefield=[beast])
    p2 = PlayerState(name="P2")
    return Game(players=[p1, p2]), p1, p2, beast


def _r27_power(game, beast) -> int:
    game._refresh_dynamic_creatures()
    return beast.effective_power


def test_beasts_of_bogardan_carries_both_halves_of_its_noun_phrase(set_pool):
    """The colour *and* the "nontoken" ride the condition's filter. Either one
    dropped is a condition looser than printed, and the bonus would appear on a
    board the card says nothing about."""
    program = compile_card_oracle(set_pool("LEG")["Beasts of Bogardan"])
    assert program.supported, program.reason
    condition = next(
        i.payload["condition"]
        for i in program.instructions
        if i.kind == "conditional_static"
    )
    assert condition["who"] == "opponent"
    assert condition["filter"] == {"color_filter": "W", "nontoken": True}


def test_beasts_of_bogardan_reads_the_opponents_board_not_yours(set_pool):
    """"An opponent controls" is a question about a seat. Asked of the wrong one
    it would answer off the controller's own white permanents, which is a
    different card entirely."""
    game, mine, theirs, beast = _r27_bogardan_board(set_pool)
    assert _r27_power(game, beast) == 3

    mine.battlefield.append(_r27_permanent("Mine", ("W",)))
    assert _r27_power(game, beast) == 3

    theirs.battlefield.append(_r27_permanent("Theirs", ("W",)))
    assert _r27_power(game, beast) == 4


def test_beasts_of_bogardan_ignores_a_token(set_pool):
    """"Nontoken" is the whole difference between this card and one that turns
    on against any white board at all."""
    game, mine, theirs, beast = _r27_bogardan_board(set_pool)

    theirs.battlefield.append(_r27_permanent("Soldier", ("W",), token=True))

    assert _r27_power(game, beast) == 3


def test_beasts_of_bogardan_loses_the_bonus_when_the_board_changes(set_pool):
    """CR 611.3a — the condition is asked on every recompute, not locked in."""
    game, mine, theirs, beast = _r27_bogardan_board(set_pool)
    white = _r27_permanent("Theirs", ("W",))
    theirs.battlefield.append(white)
    assert _r27_power(game, beast) == 4

    theirs.battlefield.remove(white)

    assert _r27_power(game, beast) == 3


# --- round 28: Johan ---------------------------------------------------------


def _r28_johan_board(set_pool, *, accept: bool, tap_johan: bool = False):
    """Johan and a Bear on the battlefield, through the beginning of combat.

    Returns the game, Johan and the Bear with the beginning-of-combat trigger
    already answered *accept*-ways. The prompt only exists once the trigger has
    resolved, which is why the settle comes first — answering before it is
    armed silently declines, and that is what made the first run of this card
    look inert while every compile-time assertion passed.
    """
    johan = Permanent(card=set_pool("LEG")["Johan"])
    bear = Permanent(card=_vanilla("Bear", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[johan, bear])
    p2 = PlayerState(name="P2", battlefield=[])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game._settle()
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    game.confirm_optional_pay(0, accept=accept)
    game._settle()
    if tap_johan:
        game.become_tapped(johan)
    game.advance_combat_phase()   # declare_attackers
    return game, johan, bear


def test_johan_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Johan"])
    assert program.supported, program.reason

    (ability,) = program.triggered_abilities
    assert ability.instruction.kind == "may"
    grant, = ability.instruction.payload["action"]
    assert grant.kind == "grant_self_ability_text"
    # The quoted ability rides as printed text and the duration names the sweep
    # that ends it — end of combat, not end of turn.
    assert grant.payload["abilities"] == ("Johan can't attack",)
    assert grant.payload["duration"] == "end_of_combat"
    rider, = ability.instruction.payload["then"]
    assert rider.kind == "exempt_from_attack_tapping"
    # Both noun phrases are payload: which creatures, and what must stay true.
    assert rider.payload["filter"] == {"type_filter": "creature", "controller": "you"}
    assert rider.payload["gate_filter"] == {"untapped_only": True}


def test_johan_lets_your_creatures_attack_without_tapping(set_pool):
    """The rider, executed: CR 508.1f's tap is switched off while Johan is
    untapped, so the Bear attacks and stays untapped."""
    game, _johan, bear = _r28_johan_board(set_pool, accept=True)

    ok, message = game.declare_attackers(0, [1])

    assert ok, message
    assert bear.tapped is False


def test_johan_grants_himself_the_quoted_ability(set_pool):
    """The grant is the printed line, and the ordinary compiler reads it back
    off the permanent — so "Johan can't attack" is a real restriction rather
    than a recorded string (CR 113.3)."""
    game, johan, _bear = _r28_johan_board(set_pool, accept=True)

    assert game.can_attack(johan, 0) is False


def test_johan_taps_your_creatures_again_once_he_is_tapped(set_pool):
    """The "if Johan is untapped" clause is a *standing* test. Tested once at
    resolution and forgotten, the exemption would outlive the condition — which
    is the whole reason it lowers to a filter rather than to a condition."""
    game, _johan, bear = _r28_johan_board(set_pool, accept=True, tap_johan=True)

    ok, message = game.declare_attackers(0, [1])

    assert ok, message
    assert bear.tapped is True


def test_johan_declined_leaves_combat_alone(set_pool):
    """"You may" — declining grants nothing and arms nothing."""
    game, johan, bear = _r28_johan_board(set_pool, accept=False)

    ok, message = game.declare_attackers(0, [1])

    assert ok, message
    assert bear.tapped is True
    assert game.can_attack(johan, 0) is True


def test_johans_grant_and_exemption_both_end_with_the_combat(set_pool):
    """"Until end of combat" / "this combat". Both halves are swept at the end
    of combat step; a grant kept to end of turn would silently stop Johan
    attacking in the postcombat main phase's combat that never comes, and the
    exemption would still be running next turn."""
    game, johan, _bear = _r28_johan_board(set_pool, accept=True)
    game.declare_attackers(0, [1])

    game.advance_combat_phase()   # declare_blockers
    game.advance_combat_phase()   # combat_damage
    game.advance_combat_phase()   # end_of_combat
    game._settle()

    assert game.attack_tap_exemptions == []
    assert johan.metadata.get("granted_ability_lines") is None
    assert game.can_attack(johan, 0) is True

# ---------------------------------------------------------------------------
# Round 28 — an "unless" printed before its penalty, and a colour a blocker
# cannot be
# ---------------------------------------------------------------------------


def _r28_island() -> CardDefinition:
    """An Island built here for the reason `_swamp` above is: Legends printed
    no basic lands, and a per-set test reads its own set's cards."""
    return CardDefinition(
        name="Island", mana_cost="", cmc=0.0, type_line="Basic Land - Island",
        oracle_text="", colors=(), color_identity=("U",), keywords=(),
        produced_mana=("U",),
        raw={"name": "Island", "type_line": "Basic Land - Island"},
    )


def _r28_colored_creature(name: str, colors: tuple[str, ...]) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "3", "toughness": "3"},
    )


def _r28_elder_spawn_upkeep(set_pool, islands: int):
    """Elder Spawn's controller at the beginning of their upkeep, holding
    *islands* Islands, with the trigger on the stack awaiting its answer."""
    pool = set_pool("LEG")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=_r28_island()) for _ in range(islands)],
    )
    spawn = Permanent(card=pool["Elder Spawn"])
    p1.battlefield.append(spawn)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._settle()
    return game, p1, spawn


def test_elder_spawn_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Elder Spawn"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_self"
    # An "unless" is an offer with a penalty however it is printed, so the
    # leading spelling lowers to the same `may` the trailing one does — never a
    # second fused kind.
    assert trigger.instruction.kind == "may"
    (action,) = trigger.instruction.payload["action"]
    assert action.kind == "sacrifice_matching_permanent"
    assert action.payload["filter"] == {"subtype_filter": "island"}
    # The penalty is a whole statement, which is what the leading spelling buys:
    # the trailing one can only ever punish with the verb it follows.
    assert [step.kind for step in trigger.instruction.payload["otherwise"]] == [
        "sacrifice_self", "deal_damage",
    ]


def test_elder_spawn_paying_the_alternative_sacrifices_an_island(set_pool):
    game, p1, spawn = _r28_elder_spawn_upkeep(set_pool, islands=2)

    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert game.is_on_battlefield(spawn)
    assert [card.name for card in p1.graveyard] == ["Island"]
    assert p1.life == 20


def test_elder_spawn_declining_sacrifices_itself_and_deals_six(set_pool):
    game, p1, spawn = _r28_elder_spawn_upkeep(set_pool, islands=2)

    game.confirm_optional_pay(0, accept=False)
    game._settle()

    assert not game.is_on_battlefield(spawn)
    assert [card.name for card in p1.graveyard] == ["Elder Spawn"]
    assert p1.life == 14
    assert _names(p1) == ["Island", "Island"]


def test_elder_spawn_with_no_island_takes_the_penalty_unasked(set_pool):
    """An offer nobody can afford is not an offer: the penalty applies with no
    prompt at all, which is the reading that makes "unless" a `may`."""
    game, p1, spawn = _r28_elder_spawn_upkeep(set_pool, islands=0)

    assert not game.is_on_battlefield(spawn)
    assert p1.life == 14


def _r28_elder_spawn_blocked_by(set_pool, colors: tuple[str, ...]):
    """Elder Spawn attacking into one blocker of *colors*. It pays its own
    upkeep first, because a trigger owed an answer holds the turn where it is."""
    pool = set_pool("LEG")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=_r28_island()),
                     Permanent(card=pool["Elder Spawn"])],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=_r28_colored_creature("Blocker", colors))],
    )
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._settle()
    game.confirm_optional_pay(0, accept=True)
    game._settle()
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    attacker = next(
        i for i, perm in enumerate(p1.battlefield) if perm.card.name == "Elder Spawn"
    )
    ok, msg = game.declare_attackers(0, [attacker])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    return game.declare_blockers(1, {0: attacker})


def test_elder_spawn_cannot_be_blocked_by_a_red_creature(set_pool):
    ok, msg = _r28_elder_spawn_blocked_by(set_pool, ("R",))
    assert not ok
    assert "cannot block" in msg


def test_elder_spawn_can_be_blocked_by_any_other_colour(set_pool):
    """The colour is payload: the restriction reads the blocker's colour, and a
    green one is not caught by it."""
    ok, msg = _r28_elder_spawn_blocked_by(set_pool, ("G",))
    assert ok, msg


# ---------------------------------------------------------------------------
# Round 28 — one named counter, five printed lines
# ---------------------------------------------------------------------------


def _r28_rasputin(set_pool):
    """Rasputin Dreamweaver on the battlefield, entry state applied."""
    pool = set_pool("LEG")
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])
    rasputin = Permanent(card=pool["Rasputin Dreamweaver"])
    game._put_permanent_onto_battlefield(0, rasputin, None)
    game._settle()
    return game, p1, rasputin


def _r28_dream_counters(permanent) -> int:
    from engine.named_counters import counters_on

    return counters_on(permanent, "dream")


def _r28_spend_a_dream_counter(game, player, rasputin, ability_index: int = 0):
    index = next(
        i for i, perm in enumerate(player.battlefield) if perm is rasputin
    )
    result = game.activate_permanent_ability(
        0, rasputin.card.name, permanent_index=index, ability_index=ability_index
    )
    game._settle()
    return result


def test_rasputin_compiles_supported(set_pool):
    """Five printed lines, all about one counter the card invents (CR 122.1)."""
    program = compile_card_oracle(set_pool("LEG")["Rasputin Dreamweaver"])
    assert program.supported, program.reason

    # Both activated abilities spend a counter, and the counter's *name* is
    # payload on the cost — never part of an instruction kind.
    assert [ability.cost.remove_counter for ability in program.activated_abilities] == [
        "dream", "dream",
    ]
    (trigger,) = program.triggered_abilities
    assert trigger.instruction.kind == "add_named_counter_to_self"
    assert trigger.instruction.payload["counter"] == "dream"
    assert trigger.instruction.payload["intervening_if"] == {
        "kind": "started_turn_state", "state": "tapped", "negated": True,
    }


def test_rasputin_enters_with_seven_dream_counters(set_pool):
    _game, _p1, rasputin = _r28_rasputin(set_pool)
    assert _r28_dream_counters(rasputin) == 7


def test_rasputin_spends_a_counter_for_colorless_mana(set_pool):
    game, p1, rasputin = _r28_rasputin(set_pool)

    result = _r28_spend_a_dream_counter(game, p1, rasputin)

    assert result.supported, result.details
    assert _r28_dream_counters(rasputin) == 6
    assert p1.mana_pool["C"] == 1


def test_rasputin_cannot_activate_with_no_counters_left(set_pool):
    """The cost is a counter, so an empty store is an ability nobody can pay —
    not one that resolves for free."""
    game, p1, rasputin = _r28_rasputin(set_pool)
    for _ in range(7):
        _r28_spend_a_dream_counter(game, p1, rasputin)
    assert _r28_dream_counters(rasputin) == 0

    result = _r28_spend_a_dream_counter(game, p1, rasputin)

    assert not result.supported
    assert _r28_dream_counters(rasputin) == 0


def test_rasputin_regrows_a_counter_at_upkeep_when_it_started_untapped(set_pool):
    game, p1, rasputin = _r28_rasputin(set_pool)
    _r28_spend_a_dream_counter(game, p1, rasputin)
    assert _r28_dream_counters(rasputin) == 6

    game.start_turn(0)
    game._settle()

    assert _r28_dream_counters(rasputin) == 7


def test_rasputin_regrows_nothing_when_it_started_the_turn_tapped(set_pool):
    """The board cannot answer this at the upkeep — the untap step has already
    run — so it is the record taken before untapping that decides."""
    game, p1, rasputin = _r28_rasputin(set_pool)
    _r28_spend_a_dream_counter(game, p1, rasputin)
    rasputin.tapped = True

    game.start_turn(0)
    game._settle()

    assert not rasputin.tapped, "the untap step still untaps it"
    assert _r28_dream_counters(rasputin) == 6


def test_rasputin_never_exceeds_seven_dream_counters(set_pool):
    """"…can't have more than seven dream counters on it" is a maximum on the
    store, so it holds however the counter was arriving."""
    game, _p1, rasputin = _r28_rasputin(set_pool)
    assert _r28_dream_counters(rasputin) == 7

    game.start_turn(0)
    game._settle()

    assert _r28_dream_counters(rasputin) == 7


def test_rasputin_prevents_one_damage_for_a_counter(set_pool):
    game, p1, rasputin = _r28_rasputin(set_pool)

    result = _r28_spend_a_dream_counter(game, p1, rasputin, ability_index=1)
    assert result.supported, result.details
    assert _r28_dream_counters(rasputin) == 6

    from engine.damage_events import deal_damage

    outcome = deal_damage(
        game,
        {"recipient": rasputin, "amount": 3, "source": rasputin, "combat": False},
    )

    assert outcome.dealt == 2, "the shield absorbs exactly the next 1 damage"


# ---------------------------------------------------------------------------
# Round 29 — Hazezon Tamar: a delay that reaches a later turn, and a count
# taken when it gets there.
# ---------------------------------------------------------------------------


def _r29_hazezon(set_pool, lands: int = 3):
    """Hazezon Tamar resolved onto a board of *lands* Forests."""
    pool = set_pool("LEG")
    p1 = PlayerState(name="P1", hand=[pool["Hazezon Tamar"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    for _ in range(lands):
        p1.battlefield.append(Permanent(card=set_pool("LEA")["Forest"]))
    game.queue_from_hand(0, "Hazezon Tamar")
    game.resolve_stack()
    game._settle()
    return game, p1, p2


def _r29_sand_warriors(player):
    return [
        perm for perm in player.battlefield
        if perm.card.name == "Sand Warrior Token"
    ]


def test_hazezon_compiles_both_of_its_triggers(set_pool):
    """The card's two abilities, and the reason the support gate had to be
    tightened to see the second: a creature carrying one working trigger and
    one that never lowered used to report itself supported."""
    program = compile_card_oracle(set_pool("LEG")["Hazezon Tamar"])

    assert program.supported, program.reason
    kinds = [trig.condition.kind for trig in program.triggered_abilities]
    assert kinds == ["enters_battlefield", "leaves_battlefield"]
    assert all(trig.supported for trig in program.triggered_abilities)


def test_hazezon_makes_no_tokens_when_it_enters(set_pool):
    """The whole sentence is delayed: nothing is created until the upkeep."""
    _game, p1, _p2 = _r29_hazezon(set_pool)

    assert _r29_sand_warriors(p1) == []


def test_hazezon_arms_one_ability_for_the_controllers_next_upkeep(set_pool):
    game, _p1, _p2 = _r29_hazezon(set_pool)

    entry, = game.delayed_triggers
    assert entry.event == "controllers_next_upkeep"
    assert entry.controller_index == 0


def test_hazezon_counts_the_lands_at_the_upkeep_not_at_the_trigger(set_pool):
    """"…where X is the number of lands you control **at that time**" — the
    clause that decides which card this is. Three lands when it entered, five
    when the upkeep arrives, and five is the answer."""
    game, p1, _p2 = _r29_hazezon(set_pool, lands=3)
    for _ in range(2):
        p1.battlefield.append(Permanent(card=set_pool("LEA")["Forest"]))

    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()

    assert len(_r29_sand_warriors(p1)) == 5


def test_hazezon_tokens_are_one_one_red_green_and_white_sand_warriors(set_pool):
    """The colours are printed *after* the subtypes ("tokens that are red,
    green, and white"), which is the same colour run in the other word order."""
    game, p1, _p2 = _r29_hazezon(set_pool, lands=2)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()

    token, _other = _r29_sand_warriors(p1)
    assert token.effective_power == 1 and token.effective_toughness == 1
    assert set(token.card.colors) == {"R", "G", "W"}
    assert token.has_type("sand") and token.has_type("warrior")


def test_hazezon_does_not_fire_on_the_opponents_upkeep(set_pool):
    """"**Your** next upkeep" — an upkeep belongs to one player."""
    game, p1, _p2 = _r29_hazezon(set_pool)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()

    assert _r29_sand_warriors(p1) == []
    assert len(game.delayed_triggers) == 1


def test_hazezon_survives_the_turn_it_entered_on(set_pool):
    """The delay names a future step rather than a duration, so the cleanup
    sweep must not take it (CR 603.7b)."""
    game, _p1, _p2 = _r29_hazezon(set_pool)

    game.resolve_cleanup_step(0)

    assert len(game.delayed_triggers) == 1


def test_hazezon_exiles_its_sand_warriors_when_it_leaves(set_pool):
    """"Exile all Sand Warriors" — two adjacent subtypes, which is a
    conjunction: the sweep used to stop reading after "Sand"."""
    game, p1, _p2 = _r29_hazezon(set_pool, lands=3)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()
    assert len(_r29_sand_warriors(p1)) == 3

    hazezon = next(p for p in p1.battlefield if p.card.name == "Hazezon Tamar")
    game.remove_from_battlefield(hazezon)
    p1.graveyard.append(hazezon.card)
    game._settle()
    game.resolve_stack()
    game._settle()

    assert _r29_sand_warriors(p1) == []


def test_hazezon_leaves_a_bystander_creature_alone(set_pool):
    """The sweep is narrowed by the printed noun phrase, so a creature that is
    not a Sand Warrior is not exiled."""
    game, p1, _p2 = _r29_hazezon(set_pool, lands=1)
    bystander = Permanent(card=_vanilla("Bystander", 2, 2))
    p1.battlefield.append(bystander)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    game._settle()

    hazezon = next(p for p in p1.battlefield if p.card.name == "Hazezon Tamar")
    game.remove_from_battlefield(hazezon)
    p1.graveyard.append(hazezon.card)
    game._settle()
    game.resolve_stack()
    game._settle()

    assert [perm.card.name for perm in p1.battlefield].count("Bystander") == 1
    assert _r29_sand_warriors(p1) == []
