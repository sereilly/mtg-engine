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


# --- W1G5: the statics / characteristics / control family ---

from engine import Game, PlayerState
from engine.auras import (
    attach_aura, aura_combat_restriction, aura_keyword_grants, detach_aura,
)
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g5_vanilla(name: str, power: int = 2, toughness: int = 2,
                type_line: str = "Creature - Test") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def test_favorable_destiny_grants_shroud_off_the_hosts_controller(set_pool):
    """"Enchanted creature has shroud **as long as its controller controls
    another creature**."

    Two things were missing and they are one referent. ``who: "controller"`` is
    a *pronoun* seat — CR 109.5 makes the ability the Aura's, so "you control"
    would be the Aura's controller, and this clause follows the **host's**
    instead. And "another creature" is CR 109.5's exclusion measured against the
    same permanent, which the gate refused outright because ``exclude_self`` is
    out of ``OBJECT_ONLY_FILTER_KEYS`` — a set written for callers that have no
    source, where this one is handed the permanent the static is about.

    Both halves pivot on the host, and answering them off different objects is
    what would count the enchanted creature as "the other creature".
    """
    pool = set_pool("MIR")
    aura = Permanent(card=pool["Favorable Destiny"])
    host = Permanent(card=_g5_vanilla("Host"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[aura, host], library=[pool["Island"]] * 5),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, host)
    game._settle()

    # Its controller controls the host and nothing else — "another creature" is
    # false, and reading the exclusion off the Aura instead would make it true.
    assert not game._has_keyword(host, "shroud")

    friend = Permanent(card=_g5_vanilla("Friend"))
    game.players[0].battlefield.append(friend)
    game._settle()
    assert game._has_keyword(host, "shroud")

    # Derived, not recorded: the second creature leaving takes the grant with it.
    game.remove_from_battlefield(friend)
    game._settle()
    assert not game._has_keyword(host, "shroud")


def test_favorable_destiny_reads_the_hosts_seat_not_the_auras(set_pool):
    """The whole reason ``who: "controller"`` is not a synonym for "you".

    The Aura is on seat 0 and the creature it enchants is on seat 1, so "its
    controller" is seat 1 — and seat 1's second creature is what switches the
    grant on, while seat 0's board says nothing about it.
    """
    pool = set_pool("MIR")
    aura = Permanent(card=pool["Favorable Destiny"])
    host = Permanent(card=_g5_vanilla("Host"))
    mine = Permanent(card=_g5_vanilla("Mine"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[aura, mine], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[host], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, host)
    game._settle()

    assert not game._has_keyword(host, "shroud"), (
        "seat 0's other creature is not the host's controller's"
    )

    theirs = Permanent(card=_g5_vanilla("Theirs"))
    game.players[1].battlefield.append(theirs)
    game._settle()
    assert game._has_keyword(host, "shroud")


def test_an_anthem_refuses_the_controller_pronoun():
    """"Its controller" needs one permanent to be the "it" of, and an anthem
    describes a set — so the seat word the Aura path admits has no referent
    there. Refused rather than allowed to default to the lord's own seat, which
    would silently read the clause as the "you control" it exists to be
    distinguished from."""
    from engine.grammar import compile_line

    result = compile_line(
        "Creatures get +1/+1 as long as its controller controls another creature."
    )
    assert result.instructions == ()


def test_cloak_of_invisibility_grants_phasing_and_the_block_restriction(set_pool):
    """"Enchanted creature has phasing **and** can't be blocked except by Walls."

    Both halves already had readers — the keyword grant is layer 6 and the
    restriction is ``combat_restrictions``' own table asked with the subject
    rewritten — and the card was unsupported because the *compound line* matched
    neither pattern whole. One pattern, both halves captured, each handed to the
    reader that already owned it.
    """
    pool = set_pool("MIR")
    cloak = pool["Cloak of Invisibility"]
    assert compile_card_oracle(cloak).supported

    line = cloak.oracle_text.splitlines()[1]
    assert aura_keyword_grants(line) == ("phasing",)
    restriction = aura_combat_restriction(line)
    assert restriction is not None
    assert restriction.kind == "cant_be_blocked_except_by"


def _g5_cloak_combat(set_pool, *, attach: bool):
    """Seat 0's creature attacking into a Wall and a Soldier, in declare blockers.

    The Aura is attached **after** the untap step on purpose. A permanent with
    phasing phases out at its controller's next untap step (CR 702.26a), which
    is round 2's mechanic working — and a creature in the phased-out zone cannot
    be declared as an attacker, so setting the board up before the turn began
    would test the alternation instead of the restriction.
    """
    pool = set_pool("MIR")
    cloak = Permanent(card=pool["Cloak of Invisibility"])
    attacker = Permanent(card=_g5_vanilla("Sneak", 2, 2))
    wall = Permanent(card=_g5_vanilla("Barricade", 0, 4, "Creature - Wall"))
    soldier = Permanent(card=_g5_vanilla("Soldier", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, cloak]),
        PlayerState(name="P2", battlefield=[wall, soldier]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    if attach:
        attach_aura(cloak, attacker)
        game._settle()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    return game, attacker


def test_cloak_of_invisibility_is_blockable_only_by_a_wall(set_pool):
    """The restriction half, in a game. A tail the combat table cannot read
    leaves the whole line unmatched rather than granting the keyword alone —
    which is why this is asserted at the block and not off the payload."""
    game, attacker = _g5_cloak_combat(set_pool, attach=True)

    assert game._has_keyword(attacker, "phasing")

    ok, message = game.declare_blockers(1, {1: 0})
    assert not ok and "cannot block" in message, "a Soldier is not a Wall"
    assert game.declare_blockers(1, {0: 0})[0]


def test_without_the_cloak_the_soldier_blocks(set_pool):
    """The control arm. Derived on every read, so the restriction exists only
    while the Aura is attached — there is no flag anyone has to clear."""
    game, attacker = _g5_cloak_combat(set_pool, attach=False)

    assert not game._has_keyword(attacker, "phasing")
    assert game.declare_blockers(1, {1: 0})[0]
