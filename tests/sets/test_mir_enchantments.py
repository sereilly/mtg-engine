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


# --- W2G2: upkeep, delayed triggers and counters ---

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_color_grants, detach_aura
from engine.linked_exile import linked_entries
from engine.named_counters import add_counters, counters_on, remove_counters
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g2_vanilla(name: str, power: int = 2, toughness: int = 2,
                  colors: tuple[str, ...] = ("G",)) -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="{G}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g2_game(*battlefield, opponent=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(battlefield), life=20),
        PlayerState(name="P2", battlefield=list(opponent), life=20),
    ])
    game.interactive_seats = set()
    game._settle()
    return game


def test_grave_servitude_makes_the_creature_black_and_gives_back_its_colour(set_pool):
    """"Enchanted creature gets +3/-1 **and is black**."

    CR 105.3: a granted colour **replaces** every colour the object had, and
    CR 613.1e puts it in layer 5. Derived from the Aura's own text on each
    recompute like every other half of ``auras.py``, so detaching it gives the
    printed colour back with nothing having to be undone — which is the whole
    reason the grant is not a ``color_override`` stamped onto the creature: an
    override that replaced every colour would leave nothing to put back.
    """
    pool = set_pool("MIR")
    aura = Permanent(card=pool["Grave Servitude"])
    host = Permanent(card=_w2g2_vanilla("Host", 2, 2, colors=("W",)))
    game = _w2g2_game(aura, host)

    assert host.effective_colors == {"W"}

    attach_aura(aura, host)
    game._settle()
    assert host.effective_colors == {"B"}, game.log
    # The P/T half of the same printed line still reads, which is the point of
    # `aura_static_pt_grant` searching rather than anchoring.
    assert (host.effective_power, host.effective_toughness) == (5, 1)

    detach_aura(aura, host)
    game._settle()
    assert host.effective_colors == {"W"}
    assert (host.effective_power, host.effective_toughness) == (2, 2)


def test_the_aura_colour_reader_takes_the_bare_sentence_too():
    """The grant is read off the printed line, and the P/T half in front of it
    is optional — a card printing "Enchanted creature is black" alone reaches
    the same layer-5 contribution. Asserted on the reader rather than on a
    card, because no card in this pool prints the bare form yet and a
    production that only worked with a P/T prefix in front of it is one the
    next such card would have to discover.
    """
    assert aura_color_grants("Enchanted creature gets +3/-1 and is black.") == ("black",)
    assert aura_color_grants("Enchanted creature is red.") == ("red",)
    # "as long as" is a condition this does not implement, so the anchored end
    # of the pattern refuses it rather than granting the colour unconditionally.
    assert aura_color_grants(
        "Enchanted creature is blue as long as you control a Forest."
    ) == ()


def test_purgatory_exiles_what_dies_and_buys_it_back_for_mana_and_life(set_pool):
    """Both halves of Purgatory, and the link between them (CR 610.3).

    The death trigger's "exile **that card**" prints no zone, because its own
    condition already said which one — so the card is the ``dead_card`` the
    death seam froze, found by identity. The exile is recorded against the
    enchantment, which is the only thing that can answer "a card exiled with
    this enchantment" a turn later.

    The upkeep offer charges "{4} **and** 2 life": one offer with two prices,
    where CR 118.8's "or" would be an alternative. Both are taken.
    """
    pool = set_pool("MIR")
    purgatory = Permanent(card=pool["Purgatory"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    lands = [Permanent(card=pool["Plains"]) for _ in range(5)]
    game = _w2g2_game(purgatory, bear, *lands)

    game._permanent_to_graveyard(game.players[0], bear)
    game.remove_from_battlefield(bear)
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == []
    assert [c.name for c in game.players[0].exile] == ["Bear"]
    assert [e["card"].name for e in linked_entries(purgatory)] == ["Bear"], game.log

    game.start_turn(0)
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert game.confirm_optional_pay(0, "Purgatory", accept=True), game.log
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert game.players[0].life == 18, game.log
    assert [c.name for c in game.players[0].exile] == []
    assert "Bear" in [p.card.name for p in game.players[0].battlefield], game.log
    # CR 610.3: the pile gives up one entry, and is not drained wholesale.
    assert linked_entries(purgatory) == ()


def test_purgatory_declines_its_own_offer_when_the_life_is_missing(set_pool):
    """"You may pay {4} **and** 2 life" is one price with two halves, so a
    player who can cover only one of them is never offered it at all
    (CR 601.2h asked of the whole cost).

    The direction matters: read as CR 118.8's alternative the offer would be
    takeable on the mana alone, and Purgatory would reanimate for free at one
    life.
    """
    pool = set_pool("MIR")
    purgatory = Permanent(card=pool["Purgatory"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    lands = [Permanent(card=pool["Plains"]) for _ in range(5)]
    game = _w2g2_game(purgatory, bear, *lands)

    game._permanent_to_graveyard(game.players[0], bear)
    game.remove_from_battlefield(bear)
    game.resolve_stack()

    game.players[0].life = 1
    game.start_turn(0)
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert not game.pending_choices_of("optional_pay"), game.log
    assert game.players[0].life == 1
    assert [c.name for c in game.players[0].exile] == ["Bear"]


def test_purgatory_returns_the_card_under_its_controllers_control(set_pool):
    """"…return a card exiled with this enchantment **to the battlefield**" —
    the one destination with no possessive to print, so CR 110.2a decides: the
    card enters under the control of the player the effect instructed, which is
    this ability's controller.

    Its opposite is Safe Haven, which prints "under **its owner's** control"
    out loud; the two are different sentences and lower to different seats.
    """
    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Purgatory"])
    upkeep = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "upkeep_self"
    )
    assert upkeep.supported
    step = upkeep.instruction.payload["then"][0]
    assert step.kind == "put_exiled_with_source"
    assert step.payload["under_control_of"] == "chooser"
    # And no "you own" narrowing, which Purgatory does not print: its pile is
    # every card the enchantment exiled.
    assert "owned_by_chooser" not in step.payload


def test_afiya_grove_moves_a_counter_each_upkeep_and_dies_empty(set_pool):
    """Three lines, of which the engine used to run one: it entered with three
    +1/+1 counters and then did nothing at all, for ever.

    The upkeep line is CR 121.6's **move** — one action, not a removal and a
    placement — and the last line is CR 603.8's state trigger in the direction
    the threshold sweep could not express: the store being *empty*.
    """
    pool = set_pool("MIR")
    grove = Permanent(card=pool["Afiya Grove"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Forest"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, grove, None)
    game._put_permanent_onto_battlefield(0, bear, None)
    game._settle()

    assert counters_on(grove, "+1/+1") == 3
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    for expected in (2, 1, 0):
        game.start_next_turn()
        if game.active_player_index != 0:
            game.start_next_turn()
        game.auto_resolve_pending_choices()
        game.resolve_stack()
        game._settle()
        assert counters_on(grove, "+1/+1") == expected, game.log

    # The counter really moved: what the Grove lost the Bear gained, and the
    # P/T came with it (CR 122.1a).
    assert (bear.effective_power, bear.effective_toughness) == (5, 5), game.log

    game.check_state_based_actions()
    game.resolve_stack()
    assert grove not in game.players[0].battlefield, game.log
    assert "Afiya Grove" in [c.name for c in game.players[0].graveyard]


def test_afiya_grove_moves_nothing_when_it_has_nothing(set_pool):
    """CR 121.6: with no counter on the source the move does not happen — to
    **either** end.

    The direction that matters: written as a ``sequence`` of the removal and
    the placement beside it, an empty Grove would still put a counter on the
    target, and its own last line would then never fire because it would be
    sacrificed the turn it emptied and grow the board every turn until then.
    """
    pool = set_pool("MIR")
    grove = Permanent(card=pool["Afiya Grove"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Forest"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, grove, None)
    game._put_permanent_onto_battlefield(0, bear, None)
    game._settle()
    remove_counters(grove, "+1/+1", 3)
    assert counters_on(grove, "+1/+1") == 0

    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2), game.log
    assert counters_on(bear, "+1/+1") == 0


def test_energy_vortex_tolls_the_chosen_player_per_counter(set_pool):
    """"At the beginning of **the chosen player's** upkeep, this enchantment
    deals 3 damage to that player unless they pay {1} **for each vortex
    counter** on this enchantment."

    Two things stood between this and firing, and both were gates written when
    ``upkeep_self`` was the only upkeep condition either pay-or-else flow could
    reach: the lowering refused every other upkeep condition outright, and the
    per-counter escalation had a reader only behind a *destruction*. The seat
    was never the problem — the upkeep step has frozen it on every ordinary
    firing since Takklemaggot.

    The price is read at resolution (CR 608.2), which is what makes the card
    work: its own upkeep trigger strips the counters a step earlier on its
    controller's turn, so the toll is whatever was put back since.
    """
    pool = set_pool("MIR")
    vortex = Permanent(card=pool["Energy Vortex"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Island"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Island"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, vortex, None)
    game._settle()

    # "As this enchantment enters, choose an opponent."
    assert vortex.metadata.get("chosen_player_index") == 1
    add_counters(vortex, "vortex", 2)

    game.start_turn(1)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    # Two counters, so the offer is {2}; P2 has no mana and takes the damage.
    assert any("may pay {2}" in line for line in game.log), game.log
    assert game.players[1].life == 17, game.log
    # The counters are not spent by the toll — only the controller's own upkeep
    # trigger removes them.
    assert counters_on(vortex, "vortex") == 2


def test_energy_vortex_offers_nothing_to_the_controller(set_pool):
    """The seat is the one the enters-choice recorded, not the ability's
    controller — so the Vortex's own upkeep brings the counter wipe and no
    toll at all.
    """
    pool = set_pool("MIR")
    vortex = Permanent(card=pool["Energy Vortex"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Island"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Island"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, vortex, None)
    game._settle()
    add_counters(vortex, "vortex", 3)

    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    # "At the beginning of your upkeep, remove all vortex counters from this
    # enchantment" — the half that already worked, and the reason the toll is
    # read at resolution rather than when the trigger was put on the stack.
    assert counters_on(vortex, "vortex") == 0, game.log
