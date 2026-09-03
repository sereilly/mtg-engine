"""Per-card tests for Mirage's enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 1: flanking (CR 702.25) ---

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _r1_bear() -> CardDefinition:
    return CardDefinition(
        name="Bear", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Bear", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _r1_enchanted(set_pool, aura_name: str):
    aura = Permanent(card=set_pool("MIR")[aura_name])
    host = Permanent(card=_r1_bear())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, aura]),
        PlayerState(name="P2", battlefield=[]),
    ])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    return game, aura, host


def test_agility_grants_both_halves_of_flanking(set_pool):
    """"Enchanted creature gets +1/+1 and has flanking."

    The card that made flanking's two channels a requirement rather than a
    detail. A keyword grant is normally one word into CR 613 layer 6, and every
    reader of "does it have flying?" looks there — but CR 702.25a *defines*
    flanking as a triggered ability the compiler builds out of a printed line,
    so the word alone would make this bear count as a flanker for the *next*
    flanker's filter while giving it no ability at all. The grant is therefore a
    grant of the line, and the word comes back because layer 6 seeds itself from
    the compiled keyword lines.
    """
    game, _aura, host = _r1_enchanted(set_pool, "Agility")

    assert (host.effective_power, host.effective_toughness) == (3, 3)
    assert game._has_keyword(host, "flanking")
    kinds = [
        trig.instruction.kind
        for trig in compile_card_oracle(host.effective_card).triggered_abilities
        if trig.instruction is not None
    ]
    assert kinds == ["pump_block_pair"]


def test_agility_takes_the_ability_back_when_it_leaves(set_pool):
    """CR 611.3b: removal is the absence of a contribution. The granted line is
    derived from the attachment on every read, so detaching restores the printed
    card with nothing to undo."""
    game, aura, host = _r1_enchanted(set_pool, "Agility")

    detach_aura(aura, host)
    game._recompute_continuous_effects()

    assert (host.effective_power, host.effective_toughness) == (2, 2)
    assert not game._has_keyword(host, "flanking")
    assert compile_card_oracle(host.effective_card).triggered_abilities == ()


# --- Round 3: the flash-Aura cycle (CR 113.6b / 514.1) ---

import pytest

from engine.cast_timing import CAST_AT_INSTANT_SPEED, casts_at_instant_speed

_R3_CYCLE = [
    "Armor of Thorns", "Grave Servitude", "Lightning Reflexes", "Soar",
    "Ward of Lights",
]


def _r3_board(set_pool, aura_name: str):
    """The Aura in hand on seat 0, with a creature of its own to enchant."""
    pool = set_pool("MIR")
    host = Permanent(card=pool["Femeref Knight"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[host], hand=[pool[aura_name]],
            library=[pool["Island"]] * 8,
        ),
        PlayerState(name="P2", library=[pool["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game, host


@pytest.mark.parametrize("name", _R3_CYCLE)
def test_the_cycle_casts_at_instant_speed(set_pool, name):
    """"You may cast this spell as though it had flash."

    All five, because the sentence is identical on all five and this is the
    largest single production in the set — the only place Mirage's refusal
    census had more than one card behind one printed line.
    """
    assert casts_at_instant_speed(set_pool("MIR")[name])


def test_an_aura_cast_at_sorcery_speed_stays(set_pool):
    """The rider reads CR 601.3d's timing, so casting it when a sorcery *could*
    have been cast marks nothing and the Aura is a permanent like any other."""
    game, host = _r3_board(set_pool, "Soar")

    result = game.cast_from_hand(
        0, "Soar", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    aura = next(p for p in game.players[0].battlefield if p.card.name == "Soar")
    assert not aura.metadata.get(CAST_AT_INSTANT_SPEED)
    assert (host.effective_power, host.effective_toughness) == (2, 3)

    game.resolve_cleanup_step(0)
    assert any(p.card.name == "Soar" for p in game.players[0].battlefield)


def test_an_aura_flashed_in_is_sacrificed_at_the_next_cleanup(set_pool):
    """"…the controller of the permanent it becomes sacrifices it at the
    beginning of the next cleanup step."

    The half that had to be built with the permission rather than after it: a
    permission granted without its penalty is a strictly better card than the
    one printed, which is the silent wrongness the whole-line claim rule exists
    to stop. The answer is frozen as the spell is announced — by the cleanup
    step the stack is empty and the step has moved on, so nothing on the board
    could be asked the question then.
    """
    game, host = _r3_board(set_pool, "Soar")
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"

    result = game.cast_from_hand(
        0, "Soar", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    aura = next(p for p in game.players[0].battlefield if p.card.name == "Soar")
    assert aura.metadata.get(CAST_AT_INSTANT_SPEED) is True
    assert (host.effective_power, host.effective_toughness) == (2, 3)

    game.resolve_cleanup_step(0)

    assert not any(p.card.name == "Soar" for p in game.players[0].battlefield)
    assert (host.effective_power, host.effective_toughness) == (2, 2)


# --- Round 5: the Enchant clause's fourth quality (CR 702.5) ---

from engine.targeting import (enchant_clause_nouns, enchant_line_subject,
                              enchant_subject_spec)


def _r5_cast(set_pool, aura_name: str, host_name: str):
    """*aura_name* cast from seat 0 at seat 1's *host_name*.

    Cast rather than attached, because the half these cards were failing on is
    what happens at resolution — `attach_aura` skips the branch that takes
    control and the branch that picks a host by type.
    """
    pool = set_pool("MIR")
    host = Permanent(card=pool[host_name])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool[aura_name]], library=[pool["Island"]] * 6),
        PlayerState(name="P2", battlefield=[host], library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, aura_name, target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()
    return game, host


@pytest.mark.parametrize(
    "line,spec",
    [
        ("Enchant black creature", {"kind": "creature", "any_colors": ["B"]}),
        ("Enchant nonblack creature", {"kind": "creature", "exclude_colors": ["B"]}),
        ("Enchant red or green creature",
         {"kind": "creature", "any_colors": ["R", "G"]}),
        ("Enchant artifact or creature", {"kind": "permanent"}),
    ],
)
def test_the_enchant_clause_reads_a_colour_and_a_noun_union(line, spec):
    """CR 702.5's [quality] has a fourth independent half — a colour — and one
    half that cannot compose, a union of nouns. Four Mirage Auras print them and
    the clause reader had neither, so all four refused at the *attachment* line
    while every other line on them read fine."""
    subject = enchant_line_subject(line)
    assert subject is not None, line
    assert enchant_subject_spec(subject) == spec


def test_mind_harness_takes_control_of_what_it_enchants(set_pool):
    """"Enchant red or green creature" / "You control enchanted creature."

    The defect widening the clause exposed. `aura_enchants` asked
    ``clause.startswith(noun)``, so "red or green creature" answered **no** to
    every branch of the attach cascade: the Aura resolved, reported supported,
    attached to nothing and stole nothing. The clause is reduced through the
    same splitters the picker uses now.
    """
    game, host = _r5_cast(set_pool, "Mind Harness", "Brushwagg")

    assert game.controller_index_of(host) == 0


def test_teferis_curse_enchants_either_of_its_two_printed_types(set_pool):
    """"Enchant artifact or creature."

    The other half of the same defect, and the harder direction: a union answers
    yes to *both* branches of the cascade, so the first one won and looked for a
    host of the wrong type — the Aura went to the graveyard reporting "no legal
    target" over a target the picker had offered and the cast gate had accepted.
    A union dispatches on what was chosen.
    """
    game, creature = _r5_cast(set_pool, "Teferi's Curse", "Femeref Knight")
    assert game._has_keyword(creature, "phasing")

    game, artifact = _r5_cast(set_pool, "Teferi's Curse", "Charcoal Diamond")
    assert game._has_keyword(artifact, "phasing")


def test_a_union_clause_reduces_to_its_nouns(set_pool):
    """The reducer both readers share, asserted directly — a graveyard clause
    still reads as a creature Aura, which is what keeps Animate Dead on the
    reanimation branch."""
    assert enchant_clause_nouns("artifact or creature") == ("artifact", "creature")
    assert enchant_clause_nouns("red or green creature") == ("creature",)
    assert enchant_clause_nouns("nonblack creature") == ("creature",)
    assert enchant_clause_nouns("creature card in a graveyard") == (
        "creature card in a graveyard",
    )


# --- W1G1: the combat family ---
#
# Chaosphere is the enchantment half of the combat group: one card, two
# board-wide lines, and neither of them a restriction printed on the creature it
# restricts.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g1e_creature(name: str, power: int, toughness: int, keywords=()) -> CardDefinition:
    """A creature whose only text is the keyword line, if any."""
    text = "\n".join(word.capitalize() for word in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(),
        keywords=tuple(word.capitalize() for word in keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g1e_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g1e_combat(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def test_chaosphere_compiles_both_of_its_lines(set_pool):
    """Neither line is printed on the creature it affects.

    "Creatures with flying can block only creatures with flying" is the
    self-scoped block restriction printed about the *board*, which makes it a
    different rule with a different enforcement site -- one kind read by both
    loops would ground every blocker in the game the moment a Chaosphere was in
    play. "Creatures without flying have reach" is the anthem with its subject
    narrowed by a keyword the creature must *not* have, which
    ``LordBuffFilter`` had no field for.
    """
    program = compile_card_oracle(set_pool("MIR")["Chaosphere"])
    assert program.supported, program.reason
    kinds = {i.kind for i in program.instructions}
    assert kinds == {"subject_can_block_only", "lord_buff"}


def test_chaosphere_grounds_a_flier_that_wants_to_block_a_ground_creature(set_pool):
    """CR 509.1b, and the reason this is a board scan: the restriction belongs
    to an enchantment that is neither attacking nor blocking, and the sentence
    says "creatures" -- so it reaches both seats, its own controller's included.
    """
    sphere = Permanent(card=set_pool("MIR")["Chaosphere"])
    flier_attacker = _w1g1e_nosick(
        Permanent(card=_w1g1e_creature("Skyraider", 2, 2, ("flying",)))
    )
    ground_attacker = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Footman", 2, 2)))
    flier_blocker = _w1g1e_nosick(
        Permanent(card=_w1g1e_creature("Skyguard", 2, 2, ("flying",)))
    )
    game = _w1g1e_combat(
        [flier_attacker, ground_attacker], [sphere, flier_blocker]
    )
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()

    assert game._can_block_attacker(flier_blocker, flier_attacker)
    assert not game._can_block_attacker(flier_blocker, ground_attacker)


def test_chaosphere_gives_the_ground_reach_and_not_the_sky(set_pool):
    """The anthem's negated narrowing, which is the half that makes the card
    playable rather than purely punitive. Dropped, every creature would get
    reach -- the fliers the sentence excludes included, which is not what the
    card says and, on this card, not even a difference anyone could see in
    combat. The keyword read is what shows it."""
    sphere = Permanent(card=set_pool("MIR")["Chaosphere"])
    ground = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Footman", 2, 2)))
    flier = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Skyguard", 2, 2, ("flying",))))
    game = _w1g1e_combat([], [sphere, ground, flier])

    assert game._has_keyword(ground, "reach")
    assert not game._has_keyword(flier, "reach")


def test_chaospheres_reach_lets_the_ground_block_a_flier(set_pool):
    """And the two lines together, which is the card: a ground creature may
    block a flier, and a flier may not block it back."""
    sphere = Permanent(card=set_pool("MIR")["Chaosphere"])
    flier_attacker = _w1g1e_nosick(
        Permanent(card=_w1g1e_creature("Skyraider", 2, 2, ("flying",)))
    )
    ground_blocker = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Footman", 2, 2)))
    game = _w1g1e_combat([flier_attacker], [sphere, ground_blocker])
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    assert game._can_block_attacker(ground_blocker, flier_attacker)
    # The map is blocker slot -> attacker slot, and the Chaosphere sits at slot
    # 0 of its controller's battlefield.
    assert game.declare_blockers(1, {1: 0})[0]


def test_without_the_chaosphere_neither_half_applies(set_pool):
    """The control. Both halves are derived from a permanent on the
    battlefield, so removing it removes both with nothing to undo."""
    flier_attacker = _w1g1e_nosick(
        Permanent(card=_w1g1e_creature("Skyraider", 2, 2, ("flying",)))
    )
    ground_attacker = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Footman", 2, 2)))
    flier_blocker = _w1g1e_nosick(
        Permanent(card=_w1g1e_creature("Skyguard", 2, 2, ("flying",)))
    )
    ground_blocker = _w1g1e_nosick(Permanent(card=_w1g1e_creature("Pikeman", 2, 2)))
    game = _w1g1e_combat(
        [flier_attacker, ground_attacker], [flier_blocker, ground_blocker]
    )
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()

    assert game._can_block_attacker(flier_blocker, ground_attacker)
    assert not game._has_keyword(ground_blocker, "reach")
    assert not game._can_block_attacker(ground_blocker, flier_attacker)
