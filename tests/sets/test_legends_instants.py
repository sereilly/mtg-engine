"""Per-card tests for Legends' instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, colors: tuple[str, ...] = ("G",)) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


# ---------------------------------------------------------------------------
# Colour change (round 3) — "One or more target creatures become <colour>
# until end of turn." CR 105.2, CR 613 layer 5.
# ---------------------------------------------------------------------------

_COLOR_SPELLS = {
    "Dwarven Song": "R",
    "Heaven's Gate": "W",
    "Sea Kings' Blessing": "U",
    "Sylvan Paradise": "G",
    "Touch of Darkness": "B",
}


@pytest.mark.parametrize("name,symbol", sorted(_COLOR_SPELLS.items()))
def test_the_colour_spells_compile_to_one_instruction(name, symbol, set_pool):
    """One sentence, five cards, one production — the colour is payload."""
    program = compile_card_oracle(set_pool("LEG")[name])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["recolor_targets_until_eot"]
    assert program.instructions[0].payload["target_color"] == symbol


def test_touch_of_darkness_recolours_every_creature_it_names(set_pool):
    """"One or more target creatures" — several, not one. A lowering that
    dropped the count would recolour the first and report itself supported."""
    spell = set_pool("LEG")["Touch of Darkness"]
    first = Permanent(card=_creature("First"))
    second = Permanent(card=_creature("Second"))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[first, second])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(
        0, "Touch of Darkness", target_player_index=0, target_permanent_index=[0, 1]
    )
    game._settle()

    assert result.supported
    assert first.effective_colors == {"B"}
    assert second.effective_colors == {"B"}


def test_the_colour_change_wears_off_at_cleanup(set_pool):
    """"…until end of turn" is carried by its own metadata channel, so the
    cleanup sweep takes it and an indefinite lace beside it would survive."""
    spell = set_pool("LEG")["Sylvan Paradise"]
    bear = Permanent(card=_creature("Bear", colors=("R",)))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[bear])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Sylvan Paradise", target_player_index=0, target_permanent_index=[0])
    game._settle()
    assert bear.effective_colors == {"G"}

    game.resolve_cleanup_step(0)
    assert bear.effective_colors == {"R"}


def test_a_permanent_lace_outlives_a_turn_long_colour_change(set_pool):
    """The reason for two channels rather than one. Chaoslace's change is
    indefinite (CR 105 and the Lace cycle print no duration); Dwarven Song's
    ends with the turn. Sharing a key would make cleanup drop both."""
    laced = Permanent(card=_creature("Laced", colors=("G",)))
    laced.metadata["color_override"] = "R"
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Heaven's Gate"]], battlefield=[laced])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Heaven's Gate", target_player_index=0, target_permanent_index=[0])
    game._settle()
    assert laced.effective_colors == {"W"}, "the newer change wins while it lasts"

    game.resolve_cleanup_step(0)
    assert laced.effective_colors == {"R"}, "the indefinite lace is still there"


# ---------------------------------------------------------------------------
# Great Defender (round 8) — "where X is its mana value"
# ---------------------------------------------------------------------------


def _costed(name: str, mana_cost: str, cmc: float) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


def test_great_defender_reads_the_targets_mana_value(set_pool):
    """"Target creature gets +0/+X until end of turn, where X is **its** mana
    value." The other kind of where-clause: not a count of a set, but a
    characteristic of the one object the sentence already named."""
    bear = Permanent(card=_costed("Costly Bear", "{3}{G}{G}", 5.0))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Great Defender"]], battlefield=[bear]
    )
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Great Defender", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert bear.effective_power == 2, "only toughness is variable in +0/+X"
    assert bear.effective_toughness == 7


def test_great_defender_gives_nothing_to_a_free_creature(set_pool):
    """CR 202.3: mana value is the printed cost's, so a 0-cost creature gets
    +0/+0 — the honest answer rather than a default."""
    ornithopter = Permanent(card=_costed("Free Bear", "{0}", 0.0))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Great Defender"]], battlefield=[ornithopter]
    )
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Great Defender", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert ornithopter.effective_toughness == 2


# ---------------------------------------------------------------------------
# Disharmony (round 11) — untap, remove from combat, steal until end of turn
# ---------------------------------------------------------------------------


def _attacker_board(set_pool):
    """P1 attacks with one creature; P2 holds Disharmony."""
    attacker = Permanent(card=_creature("Raging Bull"))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", hand=[set_pool("LEG")["Disharmony"]])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    return game, attacker


def test_disharmony_untaps_steals_and_removes_the_attacker(set_pool):
    """All three sentences of the spell, in a real combat: the attacker is
    untapped, leaves combat (CR 506.4c — the maps and the permanent state
    agree), and fights for the caster until end of turn."""
    game, attacker = _attacker_board(set_pool)
    assert attacker.tapped and attacker.attacking

    result = game.cast_from_hand(
        1, "Disharmony", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert not attacker.tapped
    assert not attacker.attacking
    assert not game.combat_attackers, "removed from combat, not merely unblocked"
    assert game.controller_index_of(attacker) == 1

    game.resolve_cleanup_step(1)
    assert game.controller_index_of(attacker) == 0, (
        "until end of turn — cleanup ends it (CR 611.2a)"
    )


def test_disharmony_is_castable_only_before_blockers(set_pool):
    """"Cast this spell only during combat before blockers are declared." —
    a restriction is only done when something enforces it; a main-phase cast
    must refuse with the spell still in hand."""
    disharmony = set_pool("LEG")["Disharmony"]
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=_creature("Idle Bull"))])
    p2 = PlayerState(name="P2", hand=[disharmony])
    game = Game(players=[p1, p2])
    game.start_turn(0)

    result = game.cast_from_hand(
        1, "Disharmony", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert disharmony in game.players[1].hand


# ---------------------------------------------------------------------------
# Reset (round 13) — a cast window after the opponent's upkeep, and an untap
# over a described set. CR 601.3, CR 502.
# ---------------------------------------------------------------------------


def _land(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land — Island",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=("U",),
        raw={"name": name, "type_line": "Basic Land — Island"},
    )


def test_reset_compiles_to_the_untap_sweep(set_pool):
    """"Untap all lands you control." — untargeted, so it is a sweep over a
    described set, and the description is payload the matcher can test."""
    program = compile_card_oracle(set_pool("LEG")["Reset"])
    assert program.supported, program.reason
    kinds = [i.kind for i in program.instructions if i.kind != "spell_pattern"]
    assert kinds == ["untap_all_matching"]
    payload = next(i for i in program.instructions if i.kind == "untap_all_matching").payload
    assert payload == {"type_filter": "land", "controller": "you"}


def _reset_game(set_pool):
    mine = [Permanent(card=_land("Island A"), tapped=True),
            Permanent(card=_land("Island B"), tapped=True)]
    bear = Permanent(card=_creature("Bear"))
    bear.tapped = True
    theirs = Permanent(card=_land("Their Island"), tapped=True)
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Reset"]],
                     battlefield=mine + [bear])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, mine, bear, theirs


def test_reset_refuses_to_cast_on_your_own_turn(set_pool):
    """"Cast this spell only during an opponent's turn after their upkeep
    step." — your own turn is never in the window (CR 601.3: an effect
    prohibits the cast)."""
    game, mine, _, _ = _reset_game(set_pool)
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = None

    result = game.cast_from_hand(0, "Reset")
    assert result.supported is False
    assert "opponent's turn" in result.details
    assert all(land.tapped for land in mine)


def test_reset_refuses_during_the_opponents_upkeep_itself(set_pool):
    """"**After** their upkeep step" excludes the upkeep — the window opens at
    their draw step, not during the step the card names."""
    game, _, _, _ = _reset_game(set_pool)
    game.active_player_index = 1
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"

    result = game.cast_from_hand(0, "Reset")
    assert result.supported is False
    assert "after their upkeep step" in result.details


def test_reset_untaps_exactly_the_lands_its_caster_controls(set_pool):
    """In the window, the sweep untaps all the caster's lands — not the
    opponent's land and not the caster's tapped creature: "all lands you
    control" is the whole description, and every word of it is enforced."""
    game, mine, bear, theirs = _reset_game(set_pool)
    game.active_player_index = 1
    game.current_turn_phase = "beginning"
    game.current_step = "draw"

    result = game.cast_from_hand(0, "Reset")
    assert result.supported, result.details
    game._settle()

    assert all(not land.tapped for land in mine), "caster's lands untapped"
    assert bear.tapped, "a creature is not a land"
    assert theirs.tapped, "an opponent's land is not 'you control'"


# ---------------------------------------------------------------------------
# Round 17 — countering an ability, narrowed by the source it came from
# ---------------------------------------------------------------------------


_PINGER = "{T}: This artifact deals 1 damage to any target."
_CREATURE_PINGER = "{T}: This creature deals 1 damage to any target."


def _source(name: str, *, artifact: bool) -> CardDefinition:
    type_line = "Artifact" if artifact else "Creature - Test"
    raw = {"name": name, "type_line": type_line}
    if not artifact:
        raw |= {"power": "2", "toughness": "2"}
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=_PINGER if artifact else _CREATURE_PINGER,
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw=raw,
    )


def _ability_on_the_stack(set_pool, source: CardDefinition, spell: str):
    """*source*'s ping aimed at seat 1, waiting on the stack with *spell* in hand.

    `queue_permanent_ability` rather than `activate_permanent_ability`: the
    latter settles, which drains the stack and leaves nothing to counter — the
    ability would have resolved before any answer to it could be cast.
    """
    src = Permanent(card=source)
    p1 = PlayerState(name="P1", battlefield=[src], life=20)
    p2 = PlayerState(name="P2", hand=[set_pool("LEG")[spell]], life=20)
    game = Game(players=[p1, p2])
    game.start_turn(0)
    assert game.queue_permanent_ability(0, source.name, target_player_index=1).supported
    assert len(game.stack) == 1, "the ability must be waiting, not resolved"
    return game, p1, p2


def test_rust_counters_an_activated_ability_from_an_artifact(set_pool):
    """CR 113.7a: an ability on the stack is an object, and CR 701.5a removes
    it. Nothing else happens — there is no card to bin."""
    game, _p1, p2 = _ability_on_the_stack(set_pool, _source("Test Pinger", artifact=True), "Rust")

    assert game.cast_from_hand(1, "Rust", target_stack_index=0).supported
    game.resolve_stack()

    assert p2.life == 20, "the ping never happened"


def test_rust_leaves_an_ability_from_a_creature_alone(set_pool):
    """The narrowing is the round's point. "From an artifact source" describes
    the *permanent the ability came from* — the ability has no card of its own
    — and a counter that ignored the phrase would reach every activated ability
    in the game."""
    game, _p1, p2 = _ability_on_the_stack(set_pool, _source("Test Beast", artifact=False), "Rust")

    assert game.cast_from_hand(1, "Rust", target_stack_index=0).supported
    game.resolve_stack()

    assert p2.life == 19, "the creature's ability is not Rust's business"


# ---------------------------------------------------------------------------
# Power/toughness and characteristic effects (round 20)
# ---------------------------------------------------------------------------


def _sized(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _artifact(name: str, mana_cost: str, cmc: float) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def test_transmutation_compiles_to_the_switch_the_layer_already_applies(set_pool):
    """Layer 7d has been live since the P/T channels were written; what was
    missing was an instruction that sets it."""
    program = compile_card_oracle(set_pool("LEG")["Transmutation"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["switch_target_pt_until_eot"]


def test_transmutation_swaps_the_printed_stats(set_pool):
    spell = set_pool("LEG")["Transmutation"]
    bear = Permanent(card=_sized("Bear", 4, 1))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[bear])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(
        0, "Transmutation", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert (bear.effective_power, bear.effective_toughness) == (1, 4)


def test_transmutation_switches_after_a_pump_rather_than_before_it(set_pool):
    """CR 613.4d: 7d acts on the values as they stand after 7c. A switch
    written as a mirrored pump would fix the numbers when it resolved and be
    wrong the moment anything else touched them."""
    spell = set_pool("LEG")["Transmutation"]
    bear = Permanent(card=_sized("Bear", 4, 1))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[bear])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Transmutation", target_player_index=0, target_permanent_index=0)
    game._settle()
    assert (bear.effective_power, bear.effective_toughness) == (1, 4)

    from engine.pt import add_pt_counters

    add_pt_counters(bear, "+1/+1")
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)


def test_the_switch_wears_off_at_cleanup(set_pool):
    spell = set_pool("LEG")["Transmutation"]
    bear = Permanent(card=_sized("Bear", 4, 1))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[bear])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Transmutation", target_player_index=0, target_permanent_index=0)
    game._settle()
    assert (bear.effective_power, bear.effective_toughness) == (1, 4)

    game.resolve_cleanup_step(0)
    assert (bear.effective_power, bear.effective_toughness) == (4, 1)


def test_divine_offering_destroys_the_artifact_and_pays_its_mana_value(set_pool):
    """"You gain life equal to **its** mana value" — the destroyed object's,
    read from the record the destruction left rather than from a battlefield
    the permanent has already left."""
    spell = set_pool("LEG")["Divine Offering"]
    relic = Permanent(card=_artifact("Relic", "{4}", 4.0))
    p1 = PlayerState(name="P1", hand=[spell], life=20)
    p2 = PlayerState(name="P2", battlefield=[relic])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Divine Offering", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert p2.battlefield == []
    assert p1.life == 24


def test_divine_offering_gains_nothing_for_a_zero_cost_artifact(set_pool):
    """A Mox is a real target and a real four-less life gain — the number is
    the artifact's, not a default."""
    spell = set_pool("LEG")["Divine Offering"]
    mox = Permanent(card=_artifact("Mox", "{0}", 0.0))
    p1 = PlayerState(name="P1", hand=[spell], life=20)
    p2 = PlayerState(name="P2", battlefield=[mox])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Divine Offering", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert p2.battlefield == []
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Avoid Fate (round 21) — "Counter target instant or Aura spell that targets a
# permanent you control." Two narrowings on one sentence: a union of classes
# that straddles the card-type and subtype axes (CR 205.2/205.3), and a
# restriction on what the chosen spell itself chose (CR 601.2c).
# ---------------------------------------------------------------------------


def _avoid_fate_game(set_pool, threat: str, seat: int):
    """Seat 1 puts *threat* on the stack aimed at the creature *seat* controls;
    seat 0 holds Avoid Fate and a creature of its own."""
    pool = set_pool("LEG")
    mine = Permanent(card=_creature("Mine"))
    theirs = Permanent(card=_creature("Theirs"))
    p1 = PlayerState(name="P1", hand=[pool["Avoid Fate"]], battlefield=[mine])
    p2 = PlayerState(name="P2", hand=[pool[threat]], battlefield=[theirs])
    game = Game(players=[p1, p2])
    queued = game.queue_from_hand(
        1, threat, target_player_index=seat, target_permanent_index=0
    )
    assert queued.supported, queued.details
    return game, p1, p2


def test_avoid_fate_compiles_the_union_across_both_axes(set_pool):
    """"instant or Aura" is one union over two axes. Recorded as a card type and
    a subtype side by side it would describe an instant that is also an Aura —
    a set nothing is in, so the card would counter nothing at all."""
    program = compile_card_oracle(set_pool("LEG")["Avoid Fate"])
    assert program.supported, program.reason
    counter = next(i for i in program.instructions if i.kind == "counter_top_stack_spell")
    assert counter.payload["any_classes"] == [
        ["card_type", "instant"], ["subtype", "aura"]
    ]
    assert "card_types" not in counter.payload
    assert "subtype_filter" not in counter.payload
    assert counter.payload["targets_filter"] == {"controller": "you"}


def test_avoid_fate_counters_an_aura_aimed_at_your_permanent(set_pool):
    """An Aura is not an instant, and the whole point of the union is that it is
    countered anyway."""
    game, _p1, p2 = _avoid_fate_game(set_pool, "Divine Transformation", 0)

    result = game.cast_from_hand(0, "Avoid Fate", target_stack_index=0)
    game._settle()

    assert result.supported, result.details
    assert not game.stack
    assert [c.name for c in p2.graveyard] == ["Divine Transformation"]


def test_avoid_fate_counters_an_instant_aimed_at_your_permanent(set_pool):
    """The other half of the union, on the other axis."""
    game, _p1, p2 = _avoid_fate_game(set_pool, "Transmutation", 0)

    result = game.cast_from_hand(0, "Avoid Fate", target_stack_index=0)
    game._settle()

    assert result.supported, result.details
    assert not game.stack
    assert "Transmutation" in [c.name for c in p2.graveyard]


def test_avoid_fate_leaves_a_spell_aimed_at_a_permanent_you_do_not_control(set_pool):
    """The narrowing is the card. A counter that ignored it would counter every
    instant on the stack, which is a strictly better and different card — so the
    spell has to *resolve*, and its effect has to land."""
    game, _p1, p2 = _avoid_fate_game(set_pool, "Transmutation", 1)
    theirs = p2.battlefield[0]

    result = game.cast_from_hand(0, "Avoid Fate", target_stack_index=0)
    game._settle()

    assert result.supported, result.details
    assert not game.stack
    assert theirs.card.name == "Theirs"
    assert any(
        "Transmutation switched" in line for line in game.log
    ), "the spell outside the narrowing resolved"


def test_avoid_fate_leaves_a_sorcery_alone(set_pool):
    """A sorcery aimed at your own permanent satisfies the second narrowing and
    fails the first — the two are tested separately, so neither can carry the
    other."""
    game, p1, _p2 = _avoid_fate_game(set_pool, "Psychic Purge", 0)

    result = game.cast_from_hand(0, "Avoid Fate", target_stack_index=0)
    game._settle()

    assert result.supported, result.details
    assert not game.stack
    assert any(
        "Psychic Purge dealt 1 damage to Mine" in line for line in game.log
    ), "a sorcery is outside the printed class union"

# ---------------------------------------------------------------------------
# Storm Seeker (round 21) — "damage … equal to the number of cards in **that
# player's** hand". The possessive is a back-reference to the damage's target,
# and reading it as the caster is the whole bug this card can have.
# ---------------------------------------------------------------------------


def _spell_card(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Sorcery", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Sorcery"},
    )


def _storm_seeker(set_pool, caster_hand: int, target_hand: int):
    p1 = PlayerState(
        name="P1",
        hand=[set_pool("LEG")["Storm Seeker"]]
        + [_spell_card(f"A{i}") for i in range(caster_hand)],
    )
    p2 = PlayerState(name="P2", hand=[_spell_card(f"B{i}") for i in range(target_hand)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_storm_seeker_counts_the_targets_hand(set_pool):
    """Four cards opposite, four damage — and the caster's own six-card hand is
    not what the sentence asked about."""
    game, p1, p2 = _storm_seeker(set_pool, caster_hand=6, target_hand=4)

    result = game.cast_from_hand(0, "Storm Seeker", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert p2.life == 16, game.log
    assert p1.life == 20


def test_storm_seeker_deals_nothing_to_an_empty_hand(set_pool):
    """Zero cards is zero damage rather than a fallback amount — the control on
    a count that answers with a default when it finds nothing."""
    game, p1, p2 = _storm_seeker(set_pool, caster_hand=3, target_hand=0)

    game.cast_from_hand(0, "Storm Seeker", target_player_index=1)
    game._settle()

    assert p2.life == 20, game.log


# ---------------------------------------------------------------------------
# Telekinesis (round 22) — three sentences about one chosen creature
# ---------------------------------------------------------------------------


def _telekinesis_game(set_pool):
    victim = Permanent(card=_creature("Victim"))
    other = Permanent(card=_creature("Other"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Telekinesis"]])
    p2 = PlayerState(name="P2", battlefield=[victim, other])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, victim, other, p1, p2


def _cast_telekinesis(game):
    result = game.cast_from_hand(
        0, "Telekinesis", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    assert result.supported, result.reason


def _dealt(game, recipient, amount, source, *, combat=True) -> int:
    from engine.damage_events import deal_damage

    return deal_damage(game, {
        "recipient": recipient, "amount": amount, "source": source, "combat": combat,
    }).dealt


def test_telekinesis_carries_out_all_three_of_its_sentences(set_pool):
    """"Tap target creature. Prevent all combat damage that would be dealt by
    that creature this turn. It doesn't untap during its controller's next two
    untap steps." Each sentence acts on the one creature the first chose, and a
    rider that were dropped would leave the card doing less than it prints."""
    game, victim, other, _p1, p2 = _telekinesis_game(set_pool)
    _cast_telekinesis(game)

    assert victim.tapped, "sentence one"
    assert _dealt(game, p2, 2, victim) == 0, "sentence two"
    assert victim.metadata.get("skip_next_untap") == 2, "sentence three"
    assert _dealt(game, p2, 2, other) == 2, "and only that creature"


def test_telekinesis_leaves_the_creature_able_to_be_damaged(set_pool):
    """"…dealt **by** that creature". The direction is the whole difference
    between a silenced creature and an invulnerable one."""
    game, victim, other, _p1, _p2 = _telekinesis_game(set_pool)
    _cast_telekinesis(game)

    assert _dealt(game, victim, 2, other) == 2


def test_telekinesis_leaves_a_ping_of_that_creature_alone(set_pool):
    """"Prevent all **combat** damage": the word is payload on one shield, and
    a shield that ignored it would stop an ability's damage as well — which is
    the strictly larger effect Kry Shield prints and this card does not."""
    game, victim, _other, _p1, p2 = _telekinesis_game(set_pool)
    _cast_telekinesis(game)

    assert _dealt(game, p2, 2, victim, combat=False) == 2


def test_telekinesis_holds_the_creature_down_for_two_untap_steps(set_pool):
    """"…next **two** untap steps." The marker is a count, so the first untap
    step spends one and the creature is still held for the second — a flag
    would give it back a turn early."""
    game, victim, _other, _p1, _p2 = _telekinesis_game(set_pool)
    _cast_telekinesis(game)

    game.start_turn(1)
    assert victim.tapped, "the first of its controller's untap steps"
    assert victim.metadata.get("skip_next_untap") == 1

    game.start_turn(1)
    assert victim.tapped, "the second"
    assert "skip_next_untap" not in victim.metadata

    game.start_turn(1)
    assert not victim.tapped, "and then it untaps"

# ---------------------------------------------------------------------------
# Delayed triggered abilities (round 22) — CR 603.7. The effect creates an
# ability now; it fires later, if it fires at all.
# ---------------------------------------------------------------------------


def _wall() -> CardDefinition:
    return CardDefinition(
        name="Test Wall", mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="Defender", colors=(), color_identity=(),
        keywords=("Defender",), produced_mana=(),
        raw={"name": "Test Wall", "type_line": "Creature - Wall",
             "power": "0", "toughness": "6"},
    )


def _glyph_of_life_board(set_pool):
    """P1's Wall, P2's attacker, and Glyph of Life in P1's hand."""
    wall = Permanent(card=_wall())
    attacker = Permanent(card=_creature("Attacker"), attacking=True)
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Glyph of Life"]],
                     battlefield=[wall], life=20)
    p2 = PlayerState(name="P2", battlefield=[attacker], life=20)
    game = Game(players=[p1, p2])
    game.cast_from_hand(
        0, "Glyph of Life", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    return game, p1, wall, attacker


def _hit(game, recipient, amount, source, *, combat=True) -> None:
    from engine.damage_events import deal_damage

    deal_damage(game, {
        "recipient": recipient, "amount": amount,
        "source": source, "combat": combat,
    })
    game._settle()


def test_glyph_of_life_compiles_to_a_targeting_half_and_a_delayed_ability(set_pool):
    """Two printed sentences, two instructions: the target is chosen as the
    spell is cast, and the ability that watches it is created on resolution."""
    program = compile_card_oracle(set_pool("LEG")["Glyph of Life"])
    assert program.supported, program.reason
    # Two sentences are one `sequence` (CR 608.2), and the tail carries a
    # second `spell_pattern` marker the compiler appends to every spell.
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "choose_target_permanent", "create_delayed_trigger",
    ]
    payload = steps[1].payload
    assert payload["event"] == "bound_permanent_dealt_damage"
    # "by an attacking creature" is a filter of its own, tested against what
    # *dealt* the damage — not folded into the subject, which is what took it.
    assert payload["agent_filter"] == {"type_filter": "creature", "attacking_only": True}
    assert payload["once"] is False


def test_glyph_of_life_gains_the_damage_an_attacker_deals_its_wall(set_pool):
    game, p1, wall, attacker = _glyph_of_life_board(set_pool)

    _hit(game, wall, 3, attacker)

    assert p1.life == 23


def test_glyph_of_life_keeps_gaining_all_turn(set_pool):
    """"Whenever" is CR 603.7b's stated duration: the ability is not spent by
    firing once."""
    game, p1, wall, attacker = _glyph_of_life_board(set_pool)

    _hit(game, wall, 3, attacker)
    _hit(game, wall, 2, attacker)

    assert p1.life == 25


def test_glyph_of_life_ignores_a_source_that_is_not_attacking(set_pool):
    """The narrowing is the whole card: without it any ping into the Wall
    would gain life."""
    game, p1, wall, _attacker = _glyph_of_life_board(set_pool)
    pinger = Permanent(card=_creature("Pinger"))
    game.players[1].battlefield.append(pinger)

    _hit(game, wall, 3, pinger, combat=False)

    assert p1.life == 20


def test_glyph_of_life_ignores_damage_to_another_creature(set_pool):
    """The ability is bound to the creature the spell chose, by id — a
    look-alike beside it is not the object the sentence named."""
    game, p1, _wall_perm, attacker = _glyph_of_life_board(set_pool)
    bystander = Permanent(card=_wall())
    game.players[0].battlefield.append(bystander)

    _hit(game, bystander, 3, attacker)

    assert p1.life == 20


def test_glyph_of_life_expires_with_the_turn(set_pool):
    """"This turn" is how long the ability lives (CR 603.7b); the cleanup
    sweep is what ends it."""
    game, p1, wall, attacker = _glyph_of_life_board(set_pool)

    game.resolve_cleanup_step(0)
    assert game.delayed_triggers == []

    _hit(game, wall, 3, attacker)
    assert p1.life == 20


def _mana_drain_board(set_pool):
    """P1 casts a six-drop; P2 answers with Mana Drain."""
    p1 = PlayerState(name="P1", hand=[set_pool("LEA")["Shivan Dragon"]])
    p2 = PlayerState(name="P2", hand=[set_pool("LEG")["Mana Drain"]])
    game = Game(players=[p1, p2])
    game.queue_from_hand(0, "Shivan Dragon")
    game.queue_from_hand(1, "Mana Drain", target_player_index=0)
    game.resolve_stack()
    game._settle()
    return game, p1, p2


def test_mana_drain_counters_and_arms_one_delayed_ability(set_pool):
    game, p1, _p2 = _mana_drain_board(set_pool)

    assert [card.name for card in p1.graveyard] == ["Shivan Dragon"]
    entry, = game.delayed_triggers
    assert entry.event == "controllers_next_main_phase"
    assert entry.controller_index == 1
    # CR 608.2h: the mana value was read while the spell was still on the
    # stack. Nothing later can ask a countered spell what it cost.
    assert entry.captured["countered_spell_mana_value"] == 6


def test_mana_drain_survives_the_turn_it_was_cast_in(set_pool):
    """"Your next main phase" names no duration, so the ability waits however
    many turns it takes — the cleanup sweep must not take it."""
    game, _p1, _p2 = _mana_drain_board(set_pool)

    game.resolve_cleanup_step(0)

    assert len(game.delayed_triggers) == 1


def test_mana_drain_does_not_fire_on_the_other_players_main_phase(set_pool):
    game, p1, _p2 = _mana_drain_board(set_pool)

    game.active_player_index = 0
    game._enter_main_phase(precombat=True)
    game._settle()

    assert not any(p1.mana_pool.values())
    assert len(game.delayed_triggers) == 1


def test_mana_drain_adds_the_countered_spells_mana_value_once(set_pool):
    game, _p1, p2 = _mana_drain_board(set_pool)

    game.active_player_index = 1
    game._enter_main_phase(precombat=True)
    game._settle()
    assert p2.mana_pool["C"] == 6
    assert game.delayed_triggers == []

    # CR 603.7b: "only once". A second main phase is a second entry into the
    # same fire site, and the ability is no longer there to answer it.
    game._enter_main_phase(precombat=False)
    game._settle()
    assert p2.mana_pool["C"] == 6


# ---------------------------------------------------------------------------
# Reincarnation — the delayed ability's *other* seat: its controller chooses
# (CR 608.2c) out of a graveyard that may be somebody else's.
# ---------------------------------------------------------------------------


def _reincarnation_board(set_pool, graveyard):
    """P1 casts Reincarnation on P2's creature; *graveyard* is P2's."""
    victim = Permanent(card=_creature("Victim"))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Reincarnation"]],
                     graveyard=[set_pool("LEA")["Grizzly Bears"]])
    p2 = PlayerState(name="P2", battlefield=[victim], graveyard=list(graveyard))
    game = Game(players=[p1, p2])
    game.cast_from_hand(
        0, "Reincarnation", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    return game, p1, p2, victim


def _kill(game, permanent):
    seat = game.controller_index_of(permanent)
    game._destroy_swept_permanents(
        game.players[seat], lambda perm: perm is permanent
    )
    game._settle()


def test_reincarnation_arms_a_one_shot_death_watch(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Reincarnation"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "choose_target_permanent", "create_delayed_trigger",
    ]
    payload = steps[1].payload
    assert payload["event"] == "bound_permanent_dies"
    # "When", not "whenever": CR 603.7b's default.
    assert payload["once"] is True
    inner = payload["instruction"]
    # Both possessives name the dead creature's owner, and both travel as
    # seats rather than as a hard-coded "the chooser".
    assert inner.payload["zone_owner"] == "event_subject_owner"
    assert inner.payload["battlefield_owner"] == "event_subject_owner"


def test_reincarnation_offers_the_dead_creatures_owners_graveyard(set_pool):
    """The spell's controller chooses (CR 608.2c); the graveyard is the dead
    creature's owner's."""
    game, _p1, _p2, victim = _reincarnation_board(
        set_pool, [set_pool("LEA")["Shivan Dragon"]]
    )

    _kill(game, victim)

    prompt, = game.pending_choices
    assert prompt.kind == "search_library"
    assert prompt.player_index == 0
    assert prompt.data["zone_seat"] == 1
    assert prompt.data["battlefield_seat"] == 1


def test_reincarnation_returns_the_card_under_its_owners_control(set_pool):
    """CR 110.2's default is the spell's controller; "under the control of that
    creature's owner" is the effect saying otherwise."""
    game, _p1, p2, victim = _reincarnation_board(
        set_pool, [set_pool("LEA")["Shivan Dragon"]]
    )
    _kill(game, victim)

    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="graveyard"
    )

    assert [p.card.name for p in game.controlled_by(1)] == ["Shivan Dragon"]
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert "Shivan Dragon" not in [card.name for card in p2.graveyard]


def test_reincarnation_refuses_a_card_that_is_not_a_creature(set_pool):
    """The printed noun is re-checked against the answer: a payload is a hint
    to the picker and never a permission."""
    game, _p1, _p2, victim = _reincarnation_board(
        set_pool, [set_pool("LEA")["Lightning Bolt"], set_pool("LEA")["Grizzly Bears"]]
    )
    _kill(game, victim)

    assert not game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="graveyard"
    )
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=1, zone="graveyard"
    )
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_a_non_interactive_seat_reads_the_same_graveyard(set_pool):
    """The AI answers out of the zone the choice names, not out of its own —
    an index into the wrong graveyard is an answer the resolver refuses, which
    would silently become a fail-to-find."""
    game, _p1, _p2, victim = _reincarnation_board(
        set_pool, [set_pool("LEA")["Shivan Dragon"]]
    )
    _kill(game, victim)

    game._default_search_library(game.pending_choices[0])

    assert [p.card.name for p in game.controlled_by(1)] == ["Shivan Dragon"]


def test_reincarnation_does_not_watch_a_creature_it_never_named(set_pool):
    game, p1, p2, _victim = _reincarnation_board(
        set_pool, [set_pool("LEA")["Shivan Dragon"]]
    )
    bystander = Permanent(card=_creature("Bystander"))
    p2.battlefield.append(bystander)

    _kill(game, bystander)

    assert game.pending_choices == []
    assert len(game.delayed_triggers) == 1


# ---------------------------------------------------------------------------
# Glyph of Doom — a delayed ability that fires at a *step* and reads its bound
# object when it resolves, rather than waiting for something to happen to it.
# ---------------------------------------------------------------------------


def _glyph_of_doom_board(set_pool):
    """P1 attacks with two; P2's Wall is ready to block one of them."""
    wall = Permanent(card=CardDefinition(
        name="Big Wall", mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="Defender", colors=(), color_identity=(),
        keywords=("Defender",), produced_mana=(),
        raw={"name": "Big Wall", "type_line": "Creature - Wall",
             "power": "0", "toughness": "9"},
    ))
    first = Permanent(card=_creature("Attacker One"))
    second = Permanent(card=_creature("Attacker Two"))
    p1 = PlayerState(name="P1", battlefield=[first, second])
    p2 = PlayerState(name="P2", battlefield=[wall],
                     hand=[set_pool("LEG")["Glyph of Doom"]])
    game = Game(players=[p1, p2])
    game.cast_from_hand(
        1, "Glyph of Doom", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    return game, p1, wall, first, second


def _one_combat(game, blocks):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    game.declare_attackers(0, [0, 1])
    game.advance_combat_phase()   # declare_blockers
    game.declare_blockers(1, blocks)
    game.advance_combat_phase()   # combat damage
    game.end_combat(step_already_started=True)
    game._settle()


def test_glyph_of_doom_arms_a_step_trigger_that_reads_its_wall(set_pool):
    """The ability fires at a step, not at something happening to the Wall —
    so the Wall is a *reference* the effect reads, not the event's subject."""
    program = compile_card_oracle(set_pool("LEG")["Glyph of Doom"])
    assert program.supported, program.reason
    payload = program.instructions[0].payload["steps"][1].payload
    assert payload["event"] == "next_end_of_combat"
    assert payload["binds_target"] is True
    assert payload["instruction"].payload["blocked_by_bound_object"] is True


def test_glyph_of_doom_destroys_what_its_wall_blocked(set_pool):
    game, p1, _wall, first, _second = _glyph_of_doom_board(set_pool)

    _one_combat(game, {0: 0})

    assert [p.card.name for p in game.controlled_by(0)] == ["Attacker Two"]
    assert [card.name for card in p1.graveyard] == ["Attacker One"]


def test_glyph_of_doom_spares_a_creature_its_wall_never_blocked(set_pool):
    """The relation is the whole card: dropped, the sweep is "destroy all
    creatures" and takes the board."""
    game, p1, _wall, _first, _second = _glyph_of_doom_board(set_pool)

    _one_combat(game, {})

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Attacker One", "Attacker Two",
    ]
    assert p1.graveyard == []


def test_glyph_of_doom_fires_once(set_pool):
    """"At this turn's next end of combat" — CR 603.7b's default, and a turn
    can hold a second combat."""
    game, _p1, _wall, _first, _second = _glyph_of_doom_board(set_pool)

    _one_combat(game, {0: 0})

    assert game.delayed_triggers == []


# ---------------------------------------------------------------------------
# Teleport (round 23) — "Cast this spell only during the declare attackers
# step." / "Target creature can't be blocked this turn."
#
# Two mechanisms: a row in engine/cast_restrictions.py (the step is shared, so
# the clause names no seat — unlike Camouflage's "your declare attackers step")
# and `grant_unblockable_to_target`, the unrestricted printing of a grant the
# engine only had in Dwarven Warriors' "power 2 or less" narrowing.
# ---------------------------------------------------------------------------


def _teleport_board(set_pool):
    """P1 holds Teleport; P1 has a bear that could attack, P2 one that could
    block it."""
    from tests.helpers import _nosick

    attacker = _nosick(Permanent(card=_creature("Attacker")))
    blocker = _nosick(Permanent(card=_creature("Blocker")))
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Teleport"]], battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p1, p2, attacker, blocker


def test_teleport_compiles_to_the_unrestricted_unblockable_grant(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Teleport"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["grant_unblockable_to_target"]


def test_teleport_is_refused_outside_the_declare_attackers_step(set_pool):
    """The failure a timing clause has when nothing enforces it is silent: the
    spell simply works more often than the card allows. So this drives the real
    cast path in the precombat main phase and asserts the card stays in hand."""
    game, p1, _p2, _attacker, blocker = _teleport_board(set_pool)
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Teleport", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is False
    assert any(card.name == "Teleport" for card in p1.hand)
    assert blocker.metadata.get("cant_be_blocked_until_eot") is None


def test_teleport_resolves_in_the_declare_attackers_step_and_stops_the_block(set_pool):
    """The window the clause opens, checked by what a blocker may then do."""
    game, p1, _p2, attacker, blocker = _teleport_board(set_pool)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, _msg = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok

    result = game.cast_from_hand(
        0, "Teleport", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported is True
    assert attacker.metadata.get("cant_be_blocked_until_eot") is True
    assert game._can_block_attacker(blocker, attacker) is False


def test_teleport_is_castable_in_an_opponents_declare_attackers_step(set_pool):
    """The clause says "the" declare attackers step, not "your" — the step is
    shared, so the non-active player is inside the window too. A predicate that
    copied Camouflage's would have refused this seat."""
    game, p1, _p2, _attacker, blocker = _teleport_board(set_pool)
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"

    result = game.cast_from_hand(
        0, "Teleport", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert result.supported is True
    assert blocker.metadata.get("cant_be_blocked_until_eot") is True


@pytest.mark.parametrize(
    "name,legal_phase,legal_step,illegal_phase,illegal_step,denial",
    [
        # Rapid Fire — "only before blockers are declared". No phase floor at
        # all: the whole turn up to that step is the window, which is what
        # separates it from Blaze of Glory's "during combat before blockers are
        # declared".
        (
            "Rapid Fire", "precombat_main", "precombat_main",
            "combat", "declare_blockers",
            "can only be cast before blockers are declared",
        ),
        # Glyph of Reincarnation — "only after combat". The end of combat step
        # is still combat, so the window opens at the postcombat main phase.
        (
            "Glyph of Reincarnation", "postcombat_main", "postcombat_main",
            "combat", "end_of_combat",
            "can only be cast after combat",
        ),
    ],
)
def test_the_remaining_legends_timing_clauses_are_enforced(
    set_pool, name, legal_phase, legal_step, illegal_phase, illegal_step, denial
):
    """The two siblings Teleport's row brought in.

    Neither card is supported yet — their *effect* lines are still refused — so
    the table row is checked directly against the printed text. The row is what
    would otherwise be an unenforced clause the day the effect lands.
    """
    from engine.cast_restrictions import check_cast_timing

    text = set_pool("LEG")[name].oracle_text.lower()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.start_turn(0)

    game.current_turn_phase, game.current_step = legal_phase, legal_step
    assert check_cast_timing(game, 0, text) is None

    game.current_turn_phase, game.current_step = illegal_phase, illegal_step
    assert check_cast_timing(game, 0, text) == denial

# ---------------------------------------------------------------------------
# Enchantment Alteration (round 23) — an Aura moved onto a permanent chosen as
# the spell resolves. CR 701.3 attach, CR 303.4j legality, CR 400.7 identity.
# ---------------------------------------------------------------------------


def _alteration_board(set_pool, aura_name: str, host_name: str, other_names):
    """One Aura already attached to *host_name*, plus *other_names* beside it.

    The hosts are deliberately same-named where a test wants two: an index would
    address either of them and locating by value would find the first, which is
    the bug class ``tests/engine/test_control_reads.py`` exists for.
    """
    leg, lea = set_pool("LEG"), set_pool("LEA")
    pool = {**lea, **leg}
    p1 = PlayerState(name="P1", hand=[leg["Enchantment Alteration"]])
    p2 = PlayerState(name="P2")
    host = Permanent(card=pool[host_name])
    others = [Permanent(card=pool[name]) for name in other_names]
    aura = Permanent(card=pool[aura_name])
    p1.battlefield = [host, *others, aura]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    attach_aura(aura, host)
    return game, aura, host, others


def _cast_alteration(game, aura):
    return game.cast_from_hand(
        0, "Enchantment Alteration",
        target_player_index=0, target_permanent_ids=[aura.permanent_id],
    )


def test_enchantment_alteration_compiles_to_a_choice_and_an_attach(set_pool):
    """Two steps, not one fused kind: the host is picked on resolution."""
    program = compile_card_oracle(set_pool("LEG")["Enchantment Alteration"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["choose_permanent", "attach_source_to_target"]
    choice = steps[0].payload
    # Both printed riders survive lowering: "another" and "of that type".
    assert choice["exclude_relative_host"] and choice["shares_type_with_relative_host"]
    assert steps[1].payload["host_from"] == choice["result_key"]


def test_enchantment_alteration_moves_the_aura_to_the_chosen_creature(set_pool):
    """Two identically named Bears: the Aura lands on the one the seat named,
    which only a stable id can say."""
    game, aura, host, (other,) = _alteration_board(
        set_pool, "Holy Strength", "Grizzly Bears", ["Grizzly Bears"],
    )
    game.interactive_seats = {0}

    _cast_alteration(game, aura)
    choice = game.pending_choice_of("permanent_choice", 0)
    assert choice is not None
    assert [p.permanent_id for p in game.live_permanent_choices(choice)] == [
        other.permanent_id
    ]

    assert game.confirm_permanent_choice(0, other.permanent_id)
    assert aura.metadata["attached_to"] is other
    assert other.effective_power == 3 and host.effective_power == 2


def test_enchantment_alteration_offers_only_the_type_it_is_on(set_pool):
    """"another permanent **of that type**" — an Aura on a land is offered
    lands, never the creature standing beside them."""
    game, aura, _host, others = _alteration_board(
        set_pool, "Wild Growth", "Forest", ["Forest", "Grizzly Bears"],
    )
    game.interactive_seats = {0}
    second_forest, bear = others

    _cast_alteration(game, aura)
    choice = game.pending_choice_of("permanent_choice", 0)
    assert [p.permanent_id for p in game.live_permanent_choices(choice)] == [
        second_forest.permanent_id
    ]
    # The engine re-checks the answer, so naming the creature is refused rather
    # than obeyed — a client cannot widen the choice.
    assert not game.confirm_permanent_choice(0, bear.permanent_id)
    assert game.confirm_permanent_choice(0, second_forest.permanent_id)
    assert aura.metadata["attached_to"] is second_forest


def test_enchantment_alteration_leaves_the_aura_alone_with_nowhere_legal(set_pool):
    """CR 303.4j: with no legal new host the Aura **doesn't move**. Not the same
    as falling off — dropping it would bin a card nothing destroyed."""
    game, aura, host, _others = _alteration_board(
        set_pool, "Holy Strength", "Grizzly Bears", ["Forest"],
    )
    game.interactive_seats = {0}

    _cast_alteration(game, aura)

    assert game.pending_choice_of("permanent_choice", 0) is None
    assert aura.metadata["attached_to"] is host
    assert game.is_on_battlefield(aura)


def test_enchantment_alteration_takes_a_default_for_a_non_interactive_seat(set_pool):
    """AI and headless play never queue it: the stated default (the first live
    candidate) is taken where the effect stands, so the sentence finishes."""
    game, aura, _host, (other,) = _alteration_board(
        set_pool, "Holy Strength", "Grizzly Bears", ["Grizzly Bears"],
    )

    _cast_alteration(game, aura)

    assert game.pending_choices == []
    assert aura.metadata["attached_to"] is other


# ---------------------------------------------------------------------------
# Round 24 — a noun phrase narrowed by a combat relation to another object the
# same sentence names: "all creatures blocking target attacking creature".
# ---------------------------------------------------------------------------


def _feint_board(set_pool):
    """Two identically named attackers, each with its own blocker.

    Same-named on purpose: the whole point of the relation is that only the
    blockers of the *chosen* attacker are touched, and a handler that located
    its creatures by value rather than by identity would find the first of the
    two and be wrong half the time.
    """
    chosen = Permanent(card=_creature("Ogre", ("R",)))
    other = Permanent(card=_creature("Ogre", ("R",)))
    mine = Permanent(card=_creature("Wall A", ("W",)))
    bystander = Permanent(card=_creature("Wall B", ("W",)))
    spell = set_pool("LEG")["Feint"]
    p1 = PlayerState(name="P1", battlefield=[chosen, other])
    p2 = PlayerState(name="P2", hand=[spell], battlefield=[mine, bystander])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    ok, msg = game.declare_blockers(1, {0: 0, 1: 1})
    assert ok, msg
    game._settle()
    return game, chosen, other, mine, bystander


def test_feint_compiles_to_the_relation_and_the_two_source_shield(set_pool):
    program = compile_card_oracle(set_pool("LEG")["Feint"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "tap_creatures_blocking_target",
        "prevent_damage_by_target_until_eot",
    ]
    # The attacking creature is what the spell picks, and the picker is derived
    # from that description rather than from a second reading of the text.
    assert steps[0].payload["targets"]["filter"]["attacking_only"] is True
    # The second printed source ("and each creature blocking it") survived.
    assert steps[1].payload["also_blocking_target"] is True


def test_feint_taps_only_the_blockers_of_the_creature_it_chose(set_pool):
    game, chosen, other, mine, bystander = _feint_board(set_pool)

    result = game.cast_from_hand(
        1, "Feint", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert mine.tapped, "the blocker of the chosen attacker was not tapped"
    assert not bystander.tapped, "a blocker of the *other* attacker was tapped"


def test_feint_prevents_the_damage_of_the_creature_and_its_blockers(set_pool):
    """Both printed sources are shielded, and nothing outside the relation is:
    the other attacker still trades with its own blocker."""
    game, chosen, other, mine, bystander = _feint_board(set_pool)
    game.cast_from_hand(1, "Feint", target_player_index=0, target_permanent_index=0)
    game._settle()

    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert chosen.damage_marked == 0, "the blocker's damage was not prevented"
    assert mine.damage_marked == 0, "the chosen attacker's damage was not prevented"
    assert other.damage_marked == 2, "an unrelated attacker was shielded"
    assert bystander.damage_marked == 2, "an unrelated blocker was shielded"


# ---------------------------------------------------------------------------
# Round 24 — Glyph of Destruction: three sentences about one chosen Wall, an
# until-end-of-combat P/T channel, and a delayed destroy on a bound object.
# ---------------------------------------------------------------------------


def _named_wall(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="Defender", colors=("W",), color_identity=("W",),
        keywords=("Defender",), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Wall",
             "power": "0", "toughness": "4"},
    )


def _glyph_board(set_pool):
    """Two identically named Walls on the defending seat; only one blocks."""
    attacker = Permanent(card=_creature("Ogre", ("R",)))
    blocking = Permanent(card=_named_wall("Stone Wall"))
    idle = Permanent(card=_named_wall("Stone Wall"))
    spell = set_pool("LEG")["Glyph of Destruction"]
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", hand=[spell], battlefield=[blocking, idle])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    return game, attacker, blocking, idle


def test_glyph_of_destruction_compiles_all_three_sentences(set_pool):
    """Two of the three are riders on a pronoun. A lowering that dropped either
    would leave a Wall that is +10/+0 and neither shielded nor doomed."""
    program = compile_card_oracle(set_pool("LEG")["Glyph of Destruction"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "pump_target_creature_until_eot",
        "prevent_damage_to_target_until_eot",
        "arm_self_action_at_next_end_step",
    ]
    # "…until end of combat", not until end of turn: the word rides the payload
    # and names the sweep that takes the boost back.
    assert steps[0].payload["duration"] == "end_of_combat"
    # "Prevent all damage", with no "combat" printed — a shield against a burn
    # spell too, which is a strictly larger effect than Fog's.
    assert steps[1].payload["combat_only"] is False
    # "Destroy **it**" — the Wall the spell chose, not the spell itself.
    assert steps[2].payload["subject"] == "bound"


def test_glyph_of_destruction_kills_the_attacker_and_saves_its_wall(set_pool):
    game, attacker, blocking, idle = _glyph_board(set_pool)

    result = game.cast_from_hand(
        1, "Glyph of Destruction", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    assert result.supported
    assert blocking.effective_power == 10

    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert attacker not in game.players[0].battlefield
    # The shield is on the Wall the spell chose, and on nothing else.
    assert blocking.damage_marked == 0
    assert idle.effective_power == 0


def test_glyph_of_destruction_boost_ends_with_the_combat(set_pool):
    """"…until end of combat." A pump lowered onto the end-of-turn channel
    would still be there in the second main phase."""
    game, attacker, blocking, idle = _glyph_board(set_pool)
    game.cast_from_hand(
        1, "Glyph of Destruction", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    game.advance_combat_phase()  # combat_damage
    game.advance_combat_phase()  # end_of_combat
    game._settle()

    assert blocking.effective_power == 0


def test_glyph_of_destruction_destroys_the_wall_at_the_end_step(set_pool):
    """"Destroy it at the beginning of the next end step" — the Wall the spell
    chose, and not the identically named one beside it."""
    game, attacker, blocking, idle = _glyph_board(set_pool)
    game.cast_from_hand(
        1, "Glyph of Destruction", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    game.resolve_end_step(0)
    game._settle()

    survivors = [perm.card.name for perm in game.players[1].battlefield]
    assert survivors == ["Stone Wall"]
    assert any(perm is idle for perm in game.players[1].battlefield)



# ---------------------------------------------------------------------------
# Rapid Fire — "Target creature gains first strike until end of turn. If it
# doesn't have rampage, that creature gains rampage 2 until end of turn."
# ---------------------------------------------------------------------------


def _plain(name: str, power: int = 3, toughness: int = 3, **kwargs) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=kwargs.get("oracle_text", ""), colors=(), color_identity=(),
        keywords=kwargs.get("keywords", ()), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _rapid_fire_game(set_pool, attacker: CardDefinition):
    """*attacker* with Rapid Fire in its controller's hand and two 1/1s to be
    blocked by — two, because rampage pays "for each creature blocking it
    beyond the first"."""
    perm = Permanent(card=attacker)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm],
                    hand=[set_pool("LEG")["Rapid Fire"]]),
        PlayerState(name="P2", battlefield=[
            Permanent(card=_plain("B1", 1, 1)), Permanent(card=_plain("B2", 1, 1)),
        ]),
    ])
    game.enforce_mana_costs = False
    return game, perm


def _cast_rapid_fire(game):
    result = game.cast_from_hand(
        0, "Rapid Fire", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    assert result.supported, result.details


def _attack_into_two_blockers(game):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare_blockers
    assert game.declare_blockers(1, {0: 0, 1: 0})[0]


def test_rapid_fire_grants_first_strike(set_pool):
    game, creature = _rapid_fire_game(set_pool, _plain("Vanilla"))
    _cast_rapid_fire(game)

    assert game._has_keyword(creature, "first strike")


def test_rapid_fire_grants_rampage_that_actually_triggers(set_pool):
    """CR 702.23a *defines* rampage as a triggered ability, so a grant of it has
    to produce one: the creature is blocked by two 1/1s and gets +2/+2 for the
    blocker beyond the first. A grant that only wrote the word somewhere would
    leave this at 3 power."""
    game, creature = _rapid_fire_game(set_pool, _plain("Vanilla"))
    _cast_rapid_fire(game)
    assert game._has_keyword(creature, "rampage")

    _attack_into_two_blockers(game)
    assert [item.ability_instruction.kind for item in game.stack] == ["rampage_pump"]

    game._settle()
    assert game.players[0].battlefield[0].effective_power == 5


def test_rapid_fire_leaves_a_creature_that_already_has_rampage_alone(set_pool):
    """"**If it doesn't have rampage**": the condition is the whole difference
    between this card and one that stacks a second instance on (CR 702.23c —
    each instance triggers separately, so a dropped condition would be worth a
    whole extra trigger). The printed Rampage 1 fires, and only it."""
    game, _creature = _rapid_fire_game(
        set_pool,
        _plain("Rampager", oracle_text="Rampage 1", keywords=("Rampage 1",)),
    )
    _cast_rapid_fire(game)

    _attack_into_two_blockers(game)
    assert [item.ability_instruction.kind for item in game.stack] == ["rampage_pump"]

    game._settle()
    assert game.players[0].battlefield[0].effective_power == 4


def test_rapid_fires_rampage_ends_with_the_turn(set_pool):
    game, creature = _rapid_fire_game(set_pool, _plain("Vanilla"))
    _cast_rapid_fire(game)

    game.resolve_cleanup_step(0)

    assert not game._has_keyword(creature, "rampage")
    assert not game._has_keyword(creature, "first strike")


# ---------------------------------------------------------------------------
# Blood Lust (round 25) — a condition about the spell's own target, a second
# arm, and an X read off a characteristic rather than a count.
# ---------------------------------------------------------------------------


def _sized(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _blood_lust(set_pool, power: int, toughness: int):
    """Cast Blood Lust at a creature of the given printed size."""
    victim = Permanent(card=_sized("Bear", power, toughness))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Blood Lust"]], battlefield=[victim]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Blood Lust", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    return game, victim, result


@pytest.mark.parametrize("toughness,expected", [(5, 1), (6, 2), (9, 5)])
def test_blood_lust_takes_the_flat_arm_at_five_toughness_or_more(
    set_pool, toughness, expected
):
    """"If target creature has toughness 5 or greater, it gets +4/-4." The
    condition reads the *target's* computed toughness (CR 613), not the
    source's — the spell is on the stack and has none."""
    _game, victim, result = _blood_lust(set_pool, 2, toughness)

    assert result.supported
    assert victim.effective_power == 6
    assert victim.effective_toughness == expected


@pytest.mark.parametrize("toughness", [1, 2, 4])
def test_blood_lust_takes_the_computed_arm_below_five(set_pool, toughness):
    """"Otherwise, it gets +4/-X, where X is its toughness minus 1." The second
    arm leaves the creature on exactly 1 toughness whatever it started at,
    which is the whole reason the card prints two arms: a flat -4 would kill
    everything smaller than a 5-toughness creature outright."""
    _game, victim, result = _blood_lust(set_pool, 2, toughness)

    assert result.supported
    assert victim.effective_power == 6
    assert victim.effective_toughness == 1, "the printed minus 1 is honoured"


def test_blood_lust_leaves_its_target_alive_on_the_computed_arm(set_pool):
    """The dropped-rider reading — "-X where X is its toughness" with the minus
    1 lost — would put a 1/1 on 0 toughness and CR 704.5f would bury it."""
    game, victim, _result = _blood_lust(set_pool, 1, 1)

    assert victim in game.players[0].battlefield


def test_blood_lust_reads_the_toughness_a_pump_already_changed(set_pool):
    """CR 613 layer 7: the gate asks what the creature's toughness *is* at
    resolution. A 2/2 given +0/+3 by something else takes the flat arm, which
    reading the printed card would get wrong."""
    from engine.pt import add_pt_modifier

    victim = Permanent(card=_sized("Bear", 2, 2))
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEG")["Blood Lust"]], battlefield=[victim]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    add_pt_modifier(victim, 0, 3)

    game.cast_from_hand(
        0, "Blood Lust", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert victim.effective_toughness == 1, "5 - 4, the flat arm"


def test_blood_lust_targets_a_creature(set_pool):
    """The condition is where the word "target" is printed, so the target the
    picker offers has to be derived from it — without that the spell announces
    no target and both arms resolve against nothing."""
    from engine.targeting import derive_cast_spec

    card = set_pool("LEG")["Blood Lust"]
    program = compile_card_oracle(card)

    assert program.supported, program.reason
    assert derive_cast_spec(card, program) == {"kind": "creature"}


# ---------------------------------------------------------------------------
# Silhouette (round 26) — a shield against what *aimed* at the creature
# ---------------------------------------------------------------------------


def _silhouette_board(set_pool):
    """The chosen creature, a second one beside it, and an opponent holding two
    Bolts and a Rod — a spell and an ability, which is both halves of "a spell
    or ability"."""
    from tests.helpers import _mk_creature_card

    lea = set_pool("LEA")
    victim = Permanent(card=_mk_creature_card("Victim", 2, 5))
    other = Permanent(card=_mk_creature_card("Other", 2, 5))
    p1 = PlayerState(
        name="P1", battlefield=[victim, other], hand=[set_pool("LEG")["Silhouette"]]
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=lea["Rod of Ruin"])],
        hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    result = game.cast_from_hand(
        0, "Silhouette", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result
    game._settle()
    return game, victim, other


def test_silhouette_compiles_supported(set_pool):
    """Two sentences, and the first one is the targeting: "Choose target
    creature" only reads as a sentence when what follows binds what it chose,
    and this shield is the second thing that does."""
    from engine.targeting import derive_cast_spec

    card = set_pool("LEG")["Silhouette"]
    program = compile_card_oracle(card)

    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_target_permanent", "prevent_damage_from_targeting_sources_until_eot"
    ]
    assert derive_cast_spec(card, program) == {"kind": "creature"}


def test_silhouette_prevents_a_spell_that_targets_the_creature(set_pool):
    game, victim, _other = _silhouette_board(set_pool)

    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert victim.damage_marked == 0


def test_silhouette_prevents_an_ability_that_targets_the_creature(set_pool):
    """"a spell **or ability**". Bronze Horse's static says "spells that target
    it" and is the same seam asked with the narrowing; this card asks it
    without."""
    game, victim, _other = _silhouette_board(set_pool)
    game.players[1].mana_pool.update({"generic": 3})

    result = game.activate_permanent_ability(
        1, "Rod of Ruin", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported, result
    assert victim.damage_marked == 0


def test_silhouette_shields_only_the_creature_it_chose(set_pool):
    """The relation is between the spell and *this* creature. A Bolt aimed at
    the creature standing next to it is not prevented, which is what says the
    shield reads the target rather than the card type of whatever is
    resolving."""
    game, _victim, other = _silhouette_board(set_pool)

    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert other.damage_marked == 3


def test_silhouette_does_not_prevent_combat_damage(set_pool):
    """Combat damage is caused by no spell or ability at all, so the condition
    is simply not met — and it is not met by construction rather than by a flag
    somebody remembered to set."""
    game, victim, other = _silhouette_board(set_pool)

    game._mark_damage_on_permanent(victim, 2, source=other, combat=True)

    assert victim.damage_marked == 2


def test_silhouette_shield_expires_with_the_turn(set_pool):
    """"…this turn." The shield carries its own lifetime, so the cleanup sweep
    ends it without a turn step naming this card."""
    game, victim, _other = _silhouette_board(set_pool)
    game.resolve_cleanup_step(0)

    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert victim.damage_marked == 3


# ---------------------------------------------------------------------------
# Reverberation (round 26) — a redirect that names a *spell*
# ---------------------------------------------------------------------------


def _reverberation_board(set_pool, copies: int = 2):
    """A player holding Reverberation, and an opponent holding *copies* of one
    damage sorcery — two copies deliberately, because they are literally one
    ``CardDefinition`` and telling them apart is the whole difficulty."""
    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Reverberation"]])
    p2 = PlayerState(name="P2", hand=[lea["Disintegrate"]] * copies)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._close_current_priority_step()
    return game, p1, p2


def test_reverberation_compiles_supported(set_pool):
    from engine.targeting import derive_cast_spec

    card = set_pool("LEG")["Reverberation"]
    program = compile_card_oracle(card)

    assert program.supported, program.reason
    assert program.instructions[0].kind == "redirect_damage_from_target_spell_until_eot"
    # The picker is the one a counterspell derives, narrowed the same way: the
    # spec describes what is *chosen*, not what is then done to it.
    assert derive_cast_spec(card, program) == {
        "kind": "stack", "stack_card_types": ["sorcery"],
    }


def test_reverberation_sends_the_sorcerys_damage_to_its_controller(set_pool):
    game, p1, p2 = _reverberation_board(set_pool)
    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=3)

    result = game.cast_from_hand(0, "Reverberation", target_stack_index=0)
    game.resolve_stack()

    assert result.supported, result
    assert p1.life == 20, "none of it reached the player it was aimed at"
    assert p2.life == 17, "and all of it reached the spell's controller"


def test_reverberation_does_not_move_a_second_copy_of_the_same_card(set_pool):
    """The reason this card waited: a spell's damage source is its printed
    ``CardDefinition`` (CR 109.5), one object per *card*, so two copies in one
    deck are the same object and a record matching on the source would move
    both. The record hangs off the ``StackItem`` — one object per cast — and is
    reached through ``Game.resolving_items``."""
    game, p1, p2 = _reverberation_board(set_pool)
    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=3)
    game.cast_from_hand(0, "Reverberation", target_stack_index=0)
    game.resolve_stack()
    assert (p1.life, p2.life) == (20, 17)

    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=2)
    game.resolve_stack()

    assert p1.life == 18, "the second cast is a different spell"
    assert p2.life == 17


def test_reverberation_leaves_a_spell_it_did_not_name_alone(set_pool):
    game, p1, p2 = _reverberation_board(set_pool, copies=1)
    p2.hand.append(set_pool("LEA")["Lightning Bolt"])
    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=3)
    game.cast_from_hand(0, "Reverberation", target_stack_index=0)
    game.resolve_stack()

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.resolve_stack()

    assert p1.life == 17, "the Bolt is not the sorcery Reverberation named"


def test_reverberation_named_spell_gone_arms_nothing(set_pool):
    """CR 608.2b: with its target no longer on the stack there is nothing to
    record, and a record armed anyway would move the next sorcery's damage
    instead."""
    game, p1, p2 = _reverberation_board(set_pool)
    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=3)
    stale = game.stack[0]
    game.resolve_stack()
    assert p1.life == 17

    game.cast_from_hand(0, "Reverberation", target_stack_index=0)
    game.resolve_stack()
    game.queue_from_hand(1, "Disintegrate", target_player_index=0, x_value=2)
    game.resolve_stack()

    assert stale not in game.stack
    assert p1.life == 15, "the later sorcery was never the one it named"
    assert p2.life == 20


# ---------------------------------------------------------------------------
# Bounce (round 27) — "Return target <noun> to its owner's hand." One
# instruction for every noun the sentence can print: Unsummon's creature,
# Boomerang's permanent, and the Island / Mountain the two modal mirrors name.
# CR 400.3 (the card goes to its *owner's* hand), CR 601.2c (an illegal choice
# makes the cast illegal rather than ineffective).
# ---------------------------------------------------------------------------


def _r27_land(set_pool, name: str) -> CardDefinition:
    """A basic land card, by printed name — Island and Mountain are what the
    two modal bounces narrow to, and the narrowing is a *subtype* (CR 205.3i)
    rather than a card type, so it has to be tested on real land cards."""
    return set_pool("LEA")[name]


def test_boomerang_returns_a_land_its_narrower_cousin_could_not(set_pool):
    """"Return target **permanent**" names no card type at all. The bounce used
    to refuse the line for want of an adjective, on the reasoning that a phrase
    with nothing left to test would bounce a land — which is exactly what this
    card prints."""
    boomerang = set_pool("LEG")["Boomerang"]
    p1 = PlayerState(name="P1", hand=[boomerang])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_creature("Bear")),
            Permanent(card=_r27_land(set_pool, "Mountain")),
        ],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Boomerang", target_player_index=1, target_permanent_index=1
    )

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == ["Bear"]
    assert [c.name for c in p2.hand] == ["Mountain"]


def test_boomerang_offers_every_permanent_to_the_picker(set_pool):
    """The picker and the resolution have to agree about what "permanent"
    means, or the caster is offered a target the cast then refuses."""
    boomerang = set_pool("LEG")["Boomerang"]
    p1 = PlayerState(name="P1", hand=[boomerang])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_r27_land(set_pool, "Island")),
            Permanent(card=_creature("Bear")),
        ],
    )
    game = Game(players=[p1, p2])

    spec = game.cast_target_spec(0, boomerang)

    assert spec["kind"] == "permanent"
    assert sorted(t["name"] for t in spec["valid_targets"]) == ["Bear", "Island"]


def test_unsummon_still_refuses_a_land(set_pool):
    """The generalisation is of the *subject*, not of the effect: a card that
    printed "creature" still names only creatures."""
    unsummon = set_pool("LEA")["Unsummon"]
    p1 = PlayerState(name="P1", hand=[unsummon])
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=_r27_land(set_pool, "Mountain"))]
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Unsummon", target_player_index=1, target_permanent_index=0
    )

    assert not result.supported
    assert [p.card.name for p in p2.battlefield] == ["Mountain"]


_R27_MODAL_BOUNCES = {
    # card -> (the land its bounce mode names, a land outside the narrowing)
    "Active Volcano": ("Island", "Mountain"),
    "Flash Flood": ("Mountain", "Island"),
}


@pytest.mark.parametrize(
    "name,named,other", [(k, *v) for k, v in sorted(_R27_MODAL_BOUNCES.items())]
)
def test_the_modal_bounce_returns_the_land_type_it_names(
    name, named, other, set_pool
):
    """Two cards, one sentence with the land type swapped — so the type is
    payload and neither card needs a line of its own."""
    card = set_pool("LEG")[name]
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_r27_land(set_pool, other)),
            Permanent(card=_r27_land(set_pool, named)),
        ],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, name, target_player_index=1, target_permanent_index=1, mode_index=1
    )

    assert result.supported, result.details
    assert [p.card.name for p in p2.battlefield] == [other]
    assert [c.name for c in p2.hand] == [named]


@pytest.mark.parametrize(
    "name,named,other", [(k, *v) for k, v in sorted(_R27_MODAL_BOUNCES.items())]
)
def test_the_modal_bounce_refuses_the_other_land_type(
    name, named, other, set_pool
):
    """The half of the narrowing a dropped rider would lose: a permanent
    *outside* the printed noun is untouched, and the cast never happens."""
    card = set_pool("LEG")[name]
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=_r27_land(set_pool, other))]
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, name, target_player_index=1, target_permanent_index=0, mode_index=1
    )

    assert not result.supported
    assert [p.card.name for p in p2.battlefield] == [other]
    assert not p2.hand


@pytest.mark.parametrize(
    "name,named,other", [(k, *v) for k, v in sorted(_R27_MODAL_BOUNCES.items())]
)
def test_the_modal_bounce_offers_only_the_land_it_names(
    name, named, other, set_pool
):
    """The mode's own picker. Its instruction is named ``bounce_target_creature``
    and the mode kind used to be read off that name, which sent every noun but
    "creature" to the fall-through and offered the caster a *player*."""
    from web.serialization import _serialize_modes

    card = set_pool("LEG")[name]
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_r27_land(set_pool, other)),
            Permanent(card=_r27_land(set_pool, named)),
            Permanent(card=_creature("Bear")),
        ],
    )
    game = Game(players=[p1, p2])

    mode = _serialize_modes(card, game, 0)[1]

    assert mode["target_kind"] == "permanent"
    assert [t["name"] for t in mode["valid_targets"]] == [named]
