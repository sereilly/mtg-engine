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
