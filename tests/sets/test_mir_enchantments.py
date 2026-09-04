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


# --- W1G3: damage / prevention / life ---

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def test_prismatic_circle_shields_against_the_colour_it_chose(set_pool):
    """"{1}: The next time a source of your choice **of the chosen color**
    would deal damage to you this turn, prevent that damage."

    Reported *supported* before this round while compiling to no instruction at
    all: the Circle branch reads a colour **word**, and this card prints the
    colour as a back-reference to what it recorded on entering (CR 614.1c). So
    the whole ability was a hollow line — the worst shape a card can have,
    because nothing was missing to report.

    Both directions, because a shield that fires on everything passes the
    positive half: a blue source is stopped and a black one is not.
    """
    from tests.helpers import _damage_dealt

    pool = set_pool("MIR")
    circle = _W1G3Permanent(card=pool["Prismatic Circle"])
    drake = _W1G3Permanent(card=pool["Azimaet Drake"])        # blue
    zombie = _W1G3Permanent(card=pool["Cadaverous Knight"])   # black
    p1 = _W1G3PlayerState(name="P1", battlefield=[circle], life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[drake, zombie], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    circle.metadata["chosen_color"] = "U"

    result = game.activate_permanent_ability(0, "Prismatic Circle")
    assert result.supported, result.details

    assert _damage_dealt(game, p1, 4, source=zombie) == 4, "a black source"
    assert _damage_dealt(game, p1, 4, source=drake) == 0, "the chosen colour"


def test_prismatic_circle_arms_nothing_when_no_colour_was_recorded(set_pool):
    """A shield that recorded no property answers to *every* source, which is
    the widest possible reading of a sentence naming one colour.

    The static half of the same phrase (``prevention._resolved_chosen_color``)
    already refuses that way; this is the one-shot half held to it.
    """
    from tests.helpers import _damage_dealt

    pool = set_pool("MIR")
    circle = _W1G3Permanent(card=pool["Prismatic Circle"])
    drake = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(name="P1", battlefield=[circle], life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[drake], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.activate_permanent_ability(0, "Prismatic Circle")

    assert _damage_dealt(game, p1, 4, source=drake) == 4


def test_prismatic_circle_records_a_colour_when_it_enters(set_pool):
    """The ability is only as good as the record it reads, so the entry half is
    checked in the same game rather than assumed from the fixture above."""
    pool = set_pool("MIR")
    drake = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(name="P1", hand=[pool["Prismatic Circle"]],
                          library=[pool["Island"]] * 5, life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[drake], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    assert game.cast_from_hand(0, "Prismatic Circle").supported
    game.resolve_stack()

    circle = next(p for p in game.controlled_by(0)
                  if p.card.name == "Prismatic Circle")
    assert circle.metadata.get("chosen_color") == "U", (
        "the only nontoken permanent an opponent controls is blue"
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


# --- W1G2: a phase-out lock with a sweep behind it (CR 702.26) ---
#
# Spatial Binding is the set's one *restriction* on phasing, and the read it
# needs was already in the engine with nothing writing it: `resolve_phasing_for`
# has asked `metadata["cant_phase_out"]` since phasing landed, and no card, test
# or handler had ever set it. So the round is as much about the second reader as
# the first — CR 702.26a's alternation is only one of the ways a permanent
# phases out, and a lock enforced there alone is one an activated ability walks
# straight past.

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.phasing_locks import phase_out_forbidden


def _w1g2_binding_board(set_pool):
    """Spatial Binding on seat 0, a creature with phasing on seat 1."""
    binding = Permanent(card=set_pool("MIR")["Spatial Binding"])
    drake = Permanent(card=set_pool("MIR")["Teferi's Drake"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[binding], life=20),
        PlayerState(name="P2", battlefield=[drake], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game, binding, drake


def _w1g2_bind(game):
    result = game.activate_permanent_ability(
        0, "Spatial Binding", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()


def test_spatial_binding_compiles_and_charges_its_life(set_pool):
    """"**Pay 1 life**: Until your next upkeep, target permanent can't phase
    out."

    The cost is CR 118.8's and the activation path already charged it; what
    refused was the effect, on "expected 'be'" — the `can't` production is the
    combat one, and it reads "can't **be** blocked/regenerated".
    """
    program = compile_card_oracle(set_pool("MIR")["Spatial Binding"])
    assert program.supported, program.reason

    game, _binding, drake = _w1g2_binding_board(set_pool)
    _w1g2_bind(game)

    assert game.players[0].life == 19, game.log
    assert phase_out_forbidden(drake), game.log


def test_a_phasing_creature_phases_out_without_the_lock(set_pool):
    """The baseline the assertion below is only meaningful against: CR 702.26a's
    alternation happens at the creature's controller's untap step."""
    game, _binding, drake = _w1g2_binding_board(set_pool)

    game.start_next_turn()

    assert drake.metadata.get("phased_out") is True, game.log


def test_spatial_binding_stops_the_untap_steps_alternation(set_pool):
    """CR 702.26a's event reads the board before it applies either half, so a
    locked permanent has to be kept out of the *set* rather than skipped
    afterwards — one excluded after the sets were taken would still have counted
    as leaving."""
    game, _binding, drake = _w1g2_binding_board(set_pool)
    _w1g2_bind(game)

    game.start_next_turn()

    assert drake.metadata.get("phased_out") is None, game.log


def test_spatial_binding_stops_a_one_shot_phase_out_too(set_pool):
    """The reader that did not exist.

    Reality Ripple, Mist Dragon, Vaporous Djinn and Taniwha all phase a
    permanent out without waiting for an untap step, so a lock enforced only at
    the alternation is one the target's controller escapes by activating an
    ability. Asked at ``Game.phase_out_permanent`` — the one transition every
    phase-out passes through.
    """
    game, _binding, drake = _w1g2_binding_board(set_pool)
    _w1g2_bind(game)

    assert game.phase_out_permanent(drake) is False
    assert drake.metadata.get("phased_out") is None, game.log


def test_the_lock_ends_at_its_controllers_next_upkeep(set_pool):
    """"Until **your** next upkeep" is CR 109.5's seat — the Binding's
    controller, not the locked permanent's — so an opponent's upkeep passes
    without lifting it and the creature phases out on the untap step after the
    sweep."""
    game, _binding, drake = _w1g2_binding_board(set_pool)
    _w1g2_bind(game)

    game.start_next_turn()          # P2's turn: the lock holds
    assert phase_out_forbidden(drake), game.log
    game.start_next_turn()          # P1's upkeep sweeps it
    assert not phase_out_forbidden(drake), game.log
    game.start_next_turn()          # P2's untap step: it phases out again

    assert drake.metadata.get("phased_out") is True, game.log


# --- W1G2: an Aura's protection from a colour nobody printed ---


def _w1g2_warded(set_pool, colour):
    """A vanilla creature under Ward of Lights, its chosen colour forced."""
    host = Permanent(card=set_pool("MIR")["Viashino Warrior"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host],
                    hand=[set_pool("MIR")["Ward of Lights"]], life=20),
        PlayerState(name="P2", hand=[set_pool("MIR")["Kaervek's Torch"]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    assert game.cast_from_hand(
        0, "Ward of Lights", target_player_index=0, target_permanent_index=0
    ).supported
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    aura = next(p for p in game.players[0].battlefield
                if p.card.name == "Ward of Lights")
    aura.metadata["chosen_color"] = colour
    game._recompute_continuous_effects()
    game.check_state_based_actions()
    return game, host, aura


def test_ward_of_lights_compiles_with_a_chosen_colour(set_pool):
    """"Enchanted creature has protection from **the chosen color**. This effect
    doesn't remove this Aura."

    The Ward cycle's channel read the five printed colour words and nothing
    else, so a colour the Aura *chose* as it entered had no value to travel
    under. It reaches the same reader as a sentinel, because that reader already
    maps words to symbols and is the only one holding the Aura the choice was
    recorded on.
    """
    program = compile_card_oracle(set_pool("MIR")["Ward of Lights"])
    assert program.supported, program.reason

    game, _host, aura = _w1g2_warded(set_pool, "R")
    assert aura.metadata.get("chosen_color") == "R"


def test_ward_of_lights_stops_a_spell_of_the_chosen_colour(set_pool):
    """CR 702.16b: a permanent with protection from a colour can't be targeted
    by a spell of that colour."""
    game, _host, _aura = _w1g2_warded(set_pool, "R")
    game.start_next_turn()

    result = game.cast_from_hand(
        1, "Kaervek's Torch", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported, game.log


def test_ward_of_lights_lets_every_other_colour_through(set_pool):
    """The other direction, and the one that says the choice is being *read*: a
    grant that answered "yes" to every colour would pass the test above while
    making the creature untargetable by anything."""
    game, _host, _aura = _w1g2_warded(set_pool, "W")
    game.start_next_turn()

    result = game.cast_from_hand(
        1, "Kaervek's Torch", target_player_index=0, target_permanent_index=0
    )

    assert result.supported, game.log


def test_ward_of_lights_survives_choosing_its_own_colour(set_pool):
    """"**This effect doesn't remove this Aura.**"

    Ward of Lights is white, so naming white would ordinarily make the Aura
    unable to enchant what it enchants (CR 303.4h) and CR 704.5m would put it in
    the graveyard. The printed sentence is the exception, and it is claimed as
    part of the same line rather than left as unread text.
    """
    game, _host, aura = _w1g2_warded(set_pool, "W")

    assert game.is_on_battlefield(aura), game.log
    assert aura.metadata.get("attached_to") is not None, game.log


# --- W1G2: an upkeep offer whose payer is also who gains what it buys ---


def test_emberwilde_djinn_hands_itself_to_the_player_who_pays(set_pool):
    """"At the beginning of each player's upkeep, that player may pay {R}{R} or
    2 life. If the player does, **they** gain control of this creature."

    Two halves, and each was a hole. CR 118.8's alternative had a life reader
    and a mana reader and the offered-cost position called only the mana one;
    and "they" is a seat the *firing event* froze rather than one anything
    targeted or chose, which the control lowering had no branch for. The seat is
    read through the same table the offer in front of it already used for its
    own actor, so the player who pays and the player who gains cannot come
    apart.
    """
    program = compile_card_oracle(set_pool("MIR")["Emberwilde Djinn"])
    assert program.supported, program.reason

    djinn = Permanent(card=set_pool("MIR")["Emberwilde Djinn"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[djinn], life=20),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    game.resolve_stack()
    # P1's own upkeep offers P1 the deal it already has; declining changes
    # nothing, which is what leaves the next upkeep's assertion meaningful.
    assert game.confirm_optional_pay(0, "Emberwilde Djinn", accept=False)
    game.resolve_stack()
    assert game.controller_index_of(djinn) == 0, game.log

    game.start_next_turn()
    game.resolve_stack()
    assert game.confirm_optional_pay(1, "Emberwilde Djinn", accept=True)
    game.resolve_stack()

    assert game.controller_index_of(djinn) == 1, game.log
    # No red mana anywhere, so the alternative is what was spent (CR 118.8).
    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 20, game.log


def test_emberwilde_djinn_stays_put_when_the_offer_is_declined(set_pool):
    """The decline branch — an offer that moved the creature either way would
    read identically in the test above."""
    djinn = Permanent(card=set_pool("MIR")["Emberwilde Djinn"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[djinn], life=20),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    game.resolve_stack()
    game.confirm_optional_pay(0, "Emberwilde Djinn", accept=False)
    game.start_next_turn()
    game.resolve_stack()
    assert game.confirm_optional_pay(1, "Emberwilde Djinn", accept=False)
    game.resolve_stack()

    assert game.controller_index_of(djinn) == 0, game.log
    assert game.players[1].life == 20, game.log


# --- W1G2: two supported cards that were playing the wrong game ---
#
# Neither was visible to any instrument. Both compile supported, carry no hollow
# line and claim every printed sentence; the census, `--hollow-lines` and
# `parse_coverage` all ask whether a line produced *something*, and these two
# produced something wrong. Found by reading the compiled programs of this
# group's family line by line and then giving each card a game.


def test_forsaken_wastes_drains_the_player_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** loses 1 life."

    The lowering had a branch for "that player" under an event about an
    **object** (the dead creature's controller, Massacre Wurm) and none for an
    event about a **player** — so the phrase fell through to the ordinary
    chosen-target reading, which under a trigger nobody targeted lands on
    ``context.target``. The Wastes drained the *opponent* on both upkeeps and
    never its own controller: a strictly one-sided card, compiled clean.

    The same table and the same frozen key the offer above it in that module
    already read for the same printed word.
    """
    wastes = Permanent(card=set_pool("MIR")["Forsaken Wastes"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[wastes], life=20),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.start_turn(0)
    game.resolve_stack()
    assert (game.players[0].life, game.players[1].life) == (19, 20), game.log

    game.start_next_turn()
    game.resolve_stack()
    assert (game.players[0].life, game.players[1].life) == (19, 19), game.log


def test_mangaras_blessing_gains_its_life_now_not_an_end_step_later(set_pool):
    """"…you gain 2 life, **and** you return this card from your graveyard to
    your hand **at the beginning of the next end step**."

    A trailing delay attaches to the clause it follows: Magic prints a
    whole-sentence delay as an *opener*. Read as governing the whole sentence,
    the life arrived an end step late — on a card printed to be discarded, the
    difference between surviving the turn and not.
    """
    blessing = set_pool("MIR")["Mangara's Blessing"]
    game = Game(players=[
        PlayerState(name="P1", hand=[blessing], life=20),
        PlayerState(name="P2", hand=[set_pool("MIR")["Stupor"]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)

    assert game.cast_from_hand(1, "Stupor", target_player_index=0).supported
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    # The life is the trigger's own step; only the return waits for the end step.
    assert game.players[0].life == 22, game.log
    assert [c.name for c in game.players[0].hand] == [], game.log

    game.resolve_end_step(1)
    game.resolve_stack()

    assert [c.name for c in game.players[0].hand] == ["Mangara's Blessing"], game.log
    assert game.players[0].life == 22, game.log


# --- W1G2: borrowing the land an Aura is attached to ---


def _w1g2_wellspring(set_pool):
    """Wellspring cast on a tapped Forest the *opponent* controls."""
    forest = Permanent(card=set_pool("MIR")["Forest"], tapped=True)
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("MIR")["Wellspring"]], life=20),
        PlayerState(name="P2", battlefield=[forest], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    assert game.cast_from_hand(
        0, "Wellspring", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_stack()
    return game, forest


def test_wellspring_borrows_the_land_as_it_enters(set_pool):
    """"When this Aura enters, gain control of **enchanted land** until end of
    turn."

    The Aura's own host is neither a target (an Aura's effect on what it
    enchants chooses nothing) nor a record an earlier step wrote, so the control
    lowering refused it outright — "the linked-control handler needs a named
    target". Only "until end of turn" is admitted: the untimed spelling (Mind
    Harness' "You control enchanted creature") is a *static* line `auras.py`
    derives on every recompute and ends by detaching, where a one-shot
    contribution with no lifetime would outlive the Aura.
    """
    program = compile_card_oracle(set_pool("MIR")["Wellspring"])
    assert program.supported, program.reason

    game, forest = _w1g2_wellspring(set_pool)

    assert game.controller_index_of(forest) == 0, game.log
    # The entry trigger borrows it; only the upkeep line untaps it.
    assert forest.tapped, game.log


def test_wellspring_untaps_and_reborrows_each_upkeep(set_pool):
    """"At the beginning of your upkeep, untap enchanted land. **You gain
    control of that land** until end of turn."

    Two halves, and the second reads the first. "That land" is the permanent the
    untap in front of it acted on, and the attached untap wrote no record — the
    lowering that reads one has existed since Disharmony and had no producer to
    read. And "**You** gain control" reached the verb table's keyword branch,
    which refuses with "expected a keyword ability"; CR 101.1 makes the pronoun
    say nothing the bare imperative did not.
    """
    game, forest = _w1g2_wellspring(set_pool)

    game.start_next_turn()          # the opponent's turn — the loan lapses
    game.start_next_turn()          # back to the Aura's controller
    game.resolve_stack()

    assert not forest.tapped, game.log
    assert game.controller_index_of(forest) == 0, game.log


# --- W2G1: combat triggers and their bound referents ---

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g1_creature(name, power, toughness, keywords=()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g1_nosick(perm: Permanent) -> Permanent:
    perm.summoning_sick = False
    return perm


def _w2g1_combat(*seats) -> Game:
    """A game sitting in the declare-attackers step, one battlefield per seat."""
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(board))
        for i, board in enumerate(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def _w2g1_resolve(game: Game) -> None:
    for _ in range(40):
        if not game.stack:
            return
        game.resolve_top_of_stack()


def test_barbed_foliage_compiles_both_triggers_with_the_defender_narrowing(set_pool):
    """"Whenever a creature attacks **you**" is CR 506.2's defending player as a
    narrowing of the trigger's *subject*, and the word had been unread.

    The bare ``matching_creature_attacks`` row is a strict prefix of this one, so
    before the narrowed row existed the regex matched "whenever a creature
    attacks" and left "you" in the effect clause -- the silent widening the
    negative lookahead beside it exists to stop. Both front ends carry it: the
    grammar sets ``attacking_you`` on the parsed subject and the oracle table
    folds it in from an empty marker group, so the condition cannot be narrowed
    on one side of the pipeline and not the other.
    """
    program = compile_card_oracle(set_pool("MIR")["Barbed Foliage"])

    assert program.supported, program.reason
    conditions = [trig.condition for trig in program.triggered_abilities]
    assert [c.kind for c in conditions] == [
        "matching_creature_attacks", "matching_creature_attacks"
    ]
    assert all(
        c.payload["attacker_filter"].get("attacking_you") for c in conditions
    ), conditions
    # …and the second trigger keeps its own printed narrowing beside it.
    assert conditions[1].payload["attacker_filter"]["without_keywords"] == ["flying"]


def test_barbed_foliage_takes_flanking_off_the_attacker_and_gives_it_back(set_pool):
    """The first line, and the reason it needed a channel of its own.

    CR 702.25a *defines* flanking as a triggered ability, so the compiler builds
    it out of the printed keyword line and layer 6's word set is not where its
    reader looks -- a ``remove_keyword`` there would have recorded a removal and
    taken nothing away. ``remove_ability_keyword`` strikes the keyword out of the
    line instead, and the cleanup sweep puts it back (CR 611.2c).
    """
    flanker = _w2g1_nosick(Permanent(card=set_pool("MIR")["Mtenda Herder"]))
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([flanker], [foliage])

    assert game._has_keyword(flanker, "flanking")
    assert game.declare_attackers(0, [0])[0]
    _w2g1_resolve(game)

    assert not game._has_keyword(flanker, "flanking"), game.log
    assert "flanking" not in flanker.effective_card.oracle_text.lower()

    game.resolve_cleanup_step(0)
    assert game._has_keyword(flanker, "flanking")
    assert "Flanking" in flanker.effective_card.oracle_text


def test_barbed_foliage_takes_a_granted_flanking_too(set_pool):
    """Agility grants flanking as a printed *line* and as the word, so a removal
    that struck only the line would leave the creature counting as "with
    flanking" for the next flanker's own filter.

    The order in ``Permanent.effective_card`` is what makes the line half work:
    the keyword strip runs after the grants are folded in, so it reaches a line
    that was not there when the removal was recorded.
    """
    host = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    agility = Permanent(card=set_pool("MIR")["Agility"])
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([host, agility], [foliage])
    attach_aura(agility, host)
    game._recompute_continuous_effects()

    assert game._has_keyword(host, "flanking")
    assert game.declare_attackers(0, [0])[0]
    _w2g1_resolve(game)

    assert not game._has_keyword(host, "flanking"), game.log
    assert "flanking" not in host.effective_card.oracle_text.lower()


def test_barbed_foliage_pings_the_ground_and_spares_the_flier(set_pool):
    """The second line: "**it**" is the attacker the event was about, not the
    enchantment that says the word.

    A bare "it" reads as the ability's own source, which is what it means on a
    line whose trigger names nothing else; here the pronoun is rebound to the
    condition's subject, so the damage needed a recipient that says so. Left to
    fall through, a targetless trigger's damage lands on whatever the resolution
    context was carrying.
    """
    ground = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    flier = _w2g1_nosick(
        Permanent(card=_w2g1_creature("Skyguard", 2, 2, ("Flying",)))
    )
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([ground, flier], [foliage])

    assert game.declare_attackers(0, [0, 1])[0]
    _w2g1_resolve(game)

    assert ground.damage_marked == 1, game.log
    assert flier.damage_marked == 0, game.log
    assert game.players[1].life == 20


def test_barbed_foliage_ignores_an_attack_aimed_at_somebody_else(set_pool):
    """The narrowing the word "you" is, shown where it is visible: a duel has
    one defender, so only a third seat can tell "attacks" from "attacks you".

    Dropped, the enchantment would ping a creature attacking a player it is not
    defending against -- and in a duel that difference never shows, which is
    exactly why the widening would have shipped.
    """
    attacker = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    victim = _w2g1_nosick(Permanent(card=_w2g1_creature("Bystander", 1, 1)))
    game = _w2g1_combat([attacker], [foliage], [victim])

    # Seat 2 is the defender; the Foliage sits on seat 1's battlefield.
    assert game.declare_attackers(0, [0], defending_player_index=2)[0]
    _w2g1_resolve(game)

    assert attacker.damage_marked == 0, game.log
    assert game._has_keyword(attacker, "flanking") is False  # it never had it


def _w2g1_reparations(set_pool, catalog_by_name, spell: str, mine_extra=()):
    """Reparations on seat 1's battlefield, with *spell* in seat 0's hand.

    The spell comes from the shipped catalog and the enchantment from MIR,
    which is still ``measured`` -- ``catalog_by_name`` is the shipped pool and
    does not carry it.
    """
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[_w2g1_nosick(Permanent(card=_w2g1_creature("Ogre", 3, 3)))],
            hand=[catalog_by_name[spell]],
        ),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=set_pool("MIR")["Reparations"]), *mine_extra],
            library=[_w2g1_creature("Top", 1, 1) for _ in range(5)],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_reparations_narrows_on_what_the_spell_targets(set_pool):
    """"Whenever an opponent casts a spell **that targets you or a creature you
    control**."

    The bare ``opponent_casts_spell`` row is a strict prefix of this condition
    and claimed it, leaving the clause unread -- an enchantment that drew a card
    off every spell an opponent cast. The narrowing is not about the spell at
    all, so it rides as a marker the cast filter reads against what the
    announcement froze (CR 601.2c settles a spell's targets as it goes on the
    stack, and by resolution the spell may have been countered).
    """
    program = compile_card_oracle(set_pool("MIR")["Reparations"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    assert "targets_you_or_your_creature" in trig.condition.payload
    assert trig.condition.raw_text.endswith("you or a creature you control")


@pytest.mark.parametrize(
    "spell, kwargs, mine_extra, fires",
    [
        ("Lightning Bolt", {"target_player_index": 1}, 0, True),
        ("Lightning Bolt", {"target_player_index": 0, "target_permanent_index": 0}, 0, False),
        ("Lightning Bolt", {"target_player_index": 1, "target_permanent_index": 1}, 1, True),
        ("Wrath of God", {}, 0, False),
    ],
    ids=["my face", "their own creature", "my creature", "targets nothing"],
)
def test_reparations_fires_only_on_a_spell_aimed_at_its_controller(
    set_pool, catalog_by_name, spell, kwargs, mine_extra, fires
):
    """The four readings the clause distinguishes, in a game.

    "You" is the trigger's own controller (CR 109.5), which is what keeps the
    enchantment silent while its opponents shoot at each other -- and a spell
    that targets nothing at all fires it never. The middle case is the one the
    unread clause got wrong: ``target_player_index`` beside a permanent index is
    a *battlefield* rather than a target, so a filter that read the field would
    have drawn off every removal spell pointed at anybody.
    """
    extra = [
        _w2g1_nosick(Permanent(card=_w2g1_creature("Bear", 2, 2)))
        for _ in range(mine_extra)
    ]
    game = _w2g1_reparations(set_pool, catalog_by_name, spell, mine_extra=extra)

    game.queue_from_hand(0, spell, **kwargs)
    game.resolve_stack()

    offered = [c for c in game.pending_choices if c.player_index == 1]
    assert bool(offered) is fires, game.log


def test_reparations_draws_when_its_controller_takes_the_offer(set_pool, catalog_by_name):
    """"…you **may** draw a card" -- the offer goes to the enchantment's
    controller, who is not the player whose turn it is."""
    game = _w2g1_reparations(set_pool, catalog_by_name, "Lightning Bolt")

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.resolve_stack()
    assert game.confirm_optional_pay(1, accept=True)

    assert len(game.players[1].hand) == 1, game.log
    assert len(game.players[1].library) == 4
