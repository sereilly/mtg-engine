"""Per-card tests for Legends' instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
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
