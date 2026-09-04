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


# --- W3G2: Tombstone Stairwell ---
#
# The set's one *hollow* card: it compiled, reported supported on the strength
# of the substring "destroy all", and did nothing at all. Three abilities, and
# what they need is one thing — a permanent that keeps a record of the tokens it
# made and later destroys exactly those. The record already existed
# (`engine/tokens.CREATED_WITH_PERMANENT_ID`, stamped by the `create_token`
# handler for Tetravus and Dance of Many); what was missing was permission to
# *test* it as a noun-phrase narrowing, so `destroy all tokens created with this
# enchantment` parsed and then refused at the lowering with "no sweep handler
# for this narrowing".
#
# The other half is CR 603.4's intervening-if "if this enchantment is on the
# battlefield", which is the clause that makes the cumulative upkeep matter: the
# turn its controller cannot pay, the enchantment is sacrificed during the very
# upkeep step the Zombie trigger fired in, and the gate is what stops it
# repopulating the board on its way out.

from engine import Game as _w3g2_Game, PlayerState as _w3g2_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g2_load,  # noqa: E402
                                manifest_set_path as _w3g2_path)
from engine.models import Permanent as _w3g2_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g2_compile  # noqa: E402
from engine.tokens import (CREATED_WITH_PERMANENT_ID as _w3g2_made_by,  # noqa: E402
                           make_token_card as _w3g2_make_token)


def _w3g2_lea():
    return {card.name: card for card in _w3g2_load(_w3g2_path("LEA"))}


def _w3g2_board(set_pool, *, stairwells=1, enforce_costs=False):
    """A two-seat game with *stairwells* Tombstone Stairwells under P1.

    P1's graveyard holds two creature cards and P2's holds one, so the upkeep
    trigger's "for each creature card in **their** graveyard" has a different
    answer per seat — the ``per_recipient`` half of the count, which a single
    evaluation on the caster's board would get wrong in the direction nobody
    notices (both seats getting the caster's number).
    """
    lea = _w3g2_lea()
    game = _w3g2_Game(players=[
        _w3g2_PlayerState(
            name="P1", library=[lea["Island"]] * 10,
            graveyard=[lea["Grizzly Bears"], lea["Hurloon Minotaur"]],
        ),
        _w3g2_PlayerState(
            name="P2", library=[lea["Island"]] * 10,
            graveyard=[lea["Grizzly Bears"]],
        ),
    ])
    game.enforce_mana_costs = enforce_costs
    game.interactive_seats = set()
    made = []
    for _ in range(stairwells):
        permanent = _w3g2_Permanent(card=set_pool("MIR")["Tombstone Stairwell"])
        game._put_permanent_onto_battlefield(0, permanent, None)
        made.append(permanent)
    return game, made


def _w3g2_names(player):
    return sorted(perm.card.name for perm in player.battlefield)


def test_w3g2_tombstone_stairwell_is_no_longer_hollow(set_pool):
    """Every one of the three abilities compiles to an instruction.

    The card reported ``supported`` before this round and carried three
    instruction-less ability parts — the shape SET_PLAYBOOK Phase 4 exists to
    catch, and the one Legends shipped fourteen of. Asserted as a census over
    the program rather than on one line, because "supported" was never the
    thing that was wrong.
    """
    program = _w3g2_compile(set_pool("MIR")["Tombstone Stairwell"])
    assert program.supported, program.reason
    hollow = [
        trig.source_line for trig in program.triggered_abilities
        if trig.instruction is None
    ]
    assert hollow == [], hollow


def test_w3g2_tombstone_stairwell_fills_both_graveyards_worth_of_zombies(set_pool):
    """"At the beginning of each upkeep ... each player creates a 2/2 black
    Zombie creature token with haste named Tombspawn for each creature card in
    **their** graveyard."

    Two creature cards in P1's graveyard and one in P2's, so the count is per
    recipient rather than per caster.
    """
    game, _ = _w3g2_board(set_pool)

    game.start_next_turn()
    game.resolve_stack()

    assert _w3g2_names(game.players[0]) == [
        "Tombspawn", "Tombspawn", "Tombstone Stairwell",
    ], game.log
    assert _w3g2_names(game.players[1]) == ["Tombspawn"], game.log
    zombie = next(
        perm for perm in game.controlled_by(game.players[1])
        if perm.card.name == "Tombspawn"
    )
    # 2/2 black with haste, as printed — the token maker's own payload, checked
    # once so the sweeps below are about the record and not about the card.
    assert (zombie.effective_power, zombie.effective_toughness) == (2, 2)
    assert game._has_keyword(zombie, "haste")


def test_w3g2_end_step_destroys_its_own_tokens_and_leaves_a_look_alike(set_pool):
    """"At the beginning of each end step, destroy all tokens created with this
    enchantment."

    The narrowing is a *record*, not a description: a 2/2 black Zombie named
    Tombspawn that this enchantment did not make is not one of them. Without a
    matcher for the phrase the lowering refused the line outright; with the
    phrase dropped instead it would have swept every token on the table, which
    is why the key had to be testable rather than merely carried.
    """
    game, _ = _w3g2_board(set_pool)
    game.start_next_turn()
    game.resolve_stack()

    decoy = _w3g2_Permanent(
        card=_w3g2_make_token(
            name="Tombspawn", power=2, toughness=2,
            type_line="Creature - Zombie", colors=("B",), keywords=("Haste",),
        ),
        metadata={"is_token": True},
    )
    game._put_permanent_onto_battlefield(0, decoy, None)

    game.resolve_end_step(0)
    game.resolve_stack()

    assert _w3g2_names(game.players[0]) == ["Tombspawn", "Tombstone Stairwell"], game.log
    assert _w3g2_names(game.players[1]) == [], game.log
    assert game.is_on_battlefield(decoy), game.log


def test_w3g2_another_makers_tombspawn_survives_the_sweep(set_pool):
    """The record is keyed by the maker's ``permanent_id``, so a token some
    *other* permanent made is not one of these.

    The look-alike bug class this repo keeps finding, in its token form: a sweep
    that asked "is this a Tombspawn?" — or that compared ``Permanent`` by value
    — would take the other maker's Zombies too, and every assertion about
    counts would still pass.

    Two Stairwells cannot be the second maker: CR 704.5k's world rule puts the
    older one into its owner's graveyard the moment the second enters (the test
    below plays that out). So the second maker here is an ordinary permanent
    with the record the ``create_token`` handler would have stamped on its
    token — the same field, written the same way, by hand because the board
    state that writes it is one this card forbids.
    """
    game, (stair,) = _w3g2_board(set_pool)
    game.start_next_turn()
    game.resolve_stack()

    other_maker = next(iter(game.controlled_by(game.players[1])))
    assert other_maker.permanent_id != stair.permanent_id
    theirs = _w3g2_Permanent(
        card=_w3g2_make_token(
            name="Tombspawn", power=2, toughness=2,
            type_line="Creature - Zombie", colors=("B",), keywords=("Haste",),
        ),
        metadata={"is_token": True, _w3g2_made_by: other_maker.permanent_id},
    )
    game._put_permanent_onto_battlefield(1, theirs, None)

    game.resolve_end_step(0)
    game.resolve_stack()

    assert game.is_on_battlefield(theirs), game.log
    assert _w3g2_names(game.players[1]) == ["Tombspawn"], game.log
    assert _w3g2_names(game.players[0]) == ["Tombstone Stairwell"], game.log


def test_w3g2_the_world_rule_takes_the_first_stairwell_and_its_zombies(set_pool):
    """CR 704.5k: a second Tombstone Stairwell makes the first one a
    state-based casualty, and the leaves-the-battlefield trigger fires on the
    way out.

    Worth its own test because it is the board state the sweep above cannot be
    written against, and because it is the one that would have hidden a
    record read by *card* rather than by maker id: the incoming Stairwell has
    the same name, the same text and none of the outgoing one's Zombies.
    """
    game, (first,) = _w3g2_board(set_pool)
    game.start_next_turn()
    game.resolve_stack()
    assert len(_w3g2_names(game.players[0])) == 3, game.log

    second = _w3g2_Permanent(card=set_pool("MIR")["Tombstone Stairwell"])
    game._put_permanent_onto_battlefield(0, second, None)
    game.check_state_based_actions()
    game.resolve_stack()

    assert not game.is_on_battlefield(first), game.log
    assert _w3g2_names(game.players[0]) == ["Tombstone Stairwell"], game.log
    assert _w3g2_names(game.players[1]) == [], game.log


def test_w3g2_leaving_the_battlefield_takes_its_zombies_with_it(set_pool):
    """"When this enchantment leaves the battlefield, destroy all tokens created
    with this enchantment."

    The reader that fires *after* its source is gone. It works because the
    record lives on the tokens and names the maker by id — the maker's
    ``Permanent`` is still a live object with a stable id once it has left, and
    the trigger carries it as the ability's source.
    """
    game, (stair,) = _w3g2_board(set_pool)
    game.start_next_turn()
    game.resolve_stack()
    assert len(_w3g2_names(game.players[0])) == 3, game.log

    game.remove_from_battlefield(stair)
    game._permanent_to_graveyard(game.players[0], stair)
    game.resolve_stack()

    assert _w3g2_names(game.players[0]) == [], game.log
    assert _w3g2_names(game.players[1]) == [], game.log


def test_w3g2_unpaid_cumulative_upkeep_makes_no_zombies_on_its_way_out(set_pool):
    """CR 603.4: "if this enchantment is on the battlefield" is checked again
    once the enchantment has gone, and the ability then does nothing.

    This is the whole card's timing, not a contrived case. Both abilities fire
    at the beginning of the same upkeep; the cumulative upkeep goes unpaid, the
    enchantment is sacrificed, and the Zombie trigger finds nothing to be on the
    battlefield. Without the gate it would repopulate two boards on the way out
    and the leaves-the-battlefield trigger — which resolved first — would not be
    there to clean up after it.
    """
    game, (stair,) = _w3g2_board(set_pool, enforce_costs=True)
    game.start_next_turn()            # P2's upkeep: the Zombies arrive
    game.resolve_stack()
    assert len(_w3g2_names(game.players[0])) == 3, game.log

    game.start_next_turn()            # P1's upkeep: cumulative upkeep, unpaid
    game.resolve_stack()

    assert "Tombstone Stairwell" in [card.name for card in game.players[0].graveyard]
    assert _w3g2_names(game.players[0]) == [], game.log
    assert _w3g2_names(game.players[1]) == [], game.log


# --- W3G2: Forbidden Crypt ---
#
# Two CR 614 replacements and nothing else, which is why the card reported
# "no ability of this permanent is implemented": an interceptor produces no
# instruction, so a permanent whose whole text is one is held up by
# REPLACEMENT_LINES.
#
# The second line is the one that needed building. "If a card would be put into
# your graveyard **from anywhere**" has no single fire site — a death, a
# discard, a mill, a sacrifice and a spell finishing on the stack are one event
# with twenty-six spellings — so it needed the graveyard seam
# (`Game.put_card_into_graveyard`) that `put_card_into_hand` and
# `put_card_into_library` already had for CR 903.9b's identical problem. The
# tests below drive four of those paths, because the interesting failure of a
# rule like this is not that it does nothing, it is that it works on the path
# you tested and nowhere else.

from engine import Game as _w3g2c_Game, PlayerState as _w3g2c_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g2c_load,  # noqa: E402
                                manifest_set_path as _w3g2c_path)
from engine.models import Permanent as _w3g2c_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g2c_compile  # noqa: E402


def _w3g2c_lea():
    return {card.name: card for card in _w3g2c_load(_w3g2c_path("LEA"))}


def _w3g2c_board(set_pool, *, graveyard=(), seat=0, interactive=()):
    """A two-seat game with a Forbidden Crypt under *seat*.

    ``graveyard`` fills P1's graveyard by LEA card name — the pile the first
    line spends and the second line keeps empty.
    """
    lea = _w3g2c_lea()
    game = _w3g2c_Game(players=[
        _w3g2c_PlayerState(
            name="P1", library=[lea["Island"]] * 10,
            graveyard=[lea[name] for name in graveyard],
        ),
        _w3g2c_PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    crypt = _w3g2c_Permanent(card=set_pool("MIR")["Forbidden Crypt"])
    game._put_permanent_onto_battlefield(seat, crypt, None)
    return game, crypt


def test_w3g2_forbidden_crypt_is_supported_by_its_replacements(set_pool):
    """The card's whole text is two interceptors, so nothing it does reaches
    the compiled program — the support gate has to read REPLACEMENT_LINES for
    it, which is exactly the gap Fiery Emancipation opened."""
    program = _w3g2c_compile(set_pool("MIR")["Forbidden Crypt"])
    assert program.supported, program.reason


def test_w3g2_a_draw_returns_a_card_from_the_graveyard_instead(set_pool):
    """"If you would draw a card, return a card from your graveyard to your
    hand instead."

    Nothing is drawn: the replacement consumes the event, so a "whenever you
    draw a card" effect correctly sees no draw and the library is untouched.
    """
    game, _ = _w3g2c_board(set_pool, graveyard=["Black Lotus", "Grizzly Bears"])
    player = game.players[0]
    library_before = len(player.library)

    drawn = game._draw_with_replacements(player, 1)

    assert drawn == 0
    assert len(player.library) == library_before
    assert [card.name for card in player.hand] == ["Black Lotus"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_w3g2_an_interactive_seat_picks_which_card_comes_back(set_pool):
    """The return is a choice, so it is offered rather than taken. An
    interactive seat queues it and the draw suspends; every other seat takes
    the default at once, through the same resolver."""
    game, _ = _w3g2c_board(
        set_pool, graveyard=["Black Lotus", "Grizzly Bears"], interactive=(0,),
    )
    player = game.players[0]

    assert game._draw_with_replacements(player, 1) == 0
    [choice] = game.pending_replacement_choices
    assert choice.kind == "return_from_graveyard_instead_of_draw"
    assert choice.options == ("Black Lotus", "Grizzly Bears")

    assert game.resolve_replacement_choice(0, 1) is True
    assert [card.name for card in player.hand] == ["Grizzly Bears"]
    assert [card.name for card in player.graveyard] == ["Black Lotus"]


def test_w3g2_an_empty_graveyard_loses_the_game(set_pool):
    """"If you can't, you lose the game." (CR 104.3e.)

    The decline branch of the replacement, and the clause that makes Forbidden
    Crypt a real card rather than a slow Regrowth. It is not a state-based
    action waiting to be noticed: the effect states the player loses, so they
    have, and the opponent has won.
    """
    game, _ = _w3g2c_board(set_pool)
    player = game.players[0]

    assert game._draw_with_replacements(player, 1) == 0
    assert player.lost
    assert game.get_winner() is game.players[1]


def test_w3g2_the_second_draw_of_a_pair_finds_the_graveyard_empty(set_pool):
    """CR 121.2: a two-card draw is two draws, each replaced on its own.

    The first spends the only card in the graveyard and the second has nothing
    to return, so the loss lands on the second — which a replacement written
    once per *event* rather than once per draw would have missed entirely.
    """
    game, _ = _w3g2c_board(set_pool, graveyard=["Black Lotus"])
    player = game.players[0]

    assert game._draw_with_replacements(player, 2) == 0
    assert [card.name for card in player.hand] == ["Black Lotus"]
    assert player.lost


def test_w3g2_a_dying_creature_is_exiled_and_did_not_die(set_pool):
    """"If a card would be put into your graveyard from anywhere, exile that
    card instead."

    A death is one of the paths, and the consequence goes further than the
    pile: CR 700.4 defines dying as being put into a graveyard *from the
    battlefield*, so a creature exiled instead did not die — no dies trigger,
    and no creature counted toward "a creature died this turn".
    """
    game, _ = _w3g2c_board(set_pool)
    player = game.players[0]
    bear = _w3g2c_Permanent(card=_w3g2c_lea()["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bear, None)

    game.remove_from_battlefield(bear)
    game._permanent_to_graveyard(player, bear)

    assert [card.name for card in player.exile] == ["Grizzly Bears"]
    assert player.graveyard == []
    assert getattr(game, "creatures_died_this_turn", 0) == 0
    assert player.creatures_died_under_your_control_this_turn == 0


def test_w3g2_a_discard_a_mill_and_a_resolved_spell_are_all_exiled(set_pool):
    """The other three paths into a graveyard, driven one at a time.

    A rule written "from anywhere" fails by working on the path its author
    tested. These are the three that reach a different module each: the
    discard seam in ``mixins/effects.py``, the mill handler in
    ``handlers/zones.py``, and the stack's leave-the-stack transition in
    ``mixins/stack/resolution.py``.
    """
    lea = _w3g2c_lea()

    game, _ = _w3g2c_board(set_pool)
    player = game.players[0]
    player.hand.append(lea["Black Lotus"])
    game.take_card_from_hand(player, player.hand[0])
    game._discard_card(player, lea["Black Lotus"])
    assert [card.name for card in player.exile] == ["Black Lotus"]
    assert player.graveyard == []

    game, _ = _w3g2c_board(set_pool)
    player = game.players[0]
    millstone = _w3g2c_Permanent(
        card={c.name: c for c in _w3g2c_load(_w3g2c_path("ATQ"))}["Millstone"]
    )
    game._put_permanent_onto_battlefield(0, millstone, None)
    millstone.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game.activate_permanent_ability(0, "Millstone", target_player_index=0)
    game._settle()
    assert len(player.exile) == 2, game.log
    assert player.graveyard == [], game.log

    game, _ = _w3g2c_board(set_pool)
    player = game.players[0]
    player.hand.append(lea["Lightning Bolt"])
    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    game._settle()
    assert [card.name for card in player.exile] == ["Lightning Bolt"]
    assert player.graveyard == []
    assert game.players[1].life == 17


def test_w3g2_an_opponents_crypt_leaves_your_graveyard_alone(set_pool):
    """"**Your** graveyard" is read relative to the enchantment's controller
    (CR 109.5), so a Crypt across the table exiles nothing of yours and does
    not replace your draws either.

    The direction that would be invisible: a scope word read as "anybody's"
    would empty both graveyards and lose both players the game, and every
    assertion about the controller's own side would still pass.
    """
    game, _ = _w3g2c_board(set_pool, seat=1)
    victim = game.players[0]
    victim.hand.append(_w3g2c_lea()["Black Lotus"])
    game.take_card_from_hand(victim, victim.hand[0])
    game._discard_card(victim, _w3g2c_lea()["Black Lotus"])

    assert [card.name for card in victim.graveyard] == ["Black Lotus"]
    assert victim.exile == []
    assert game._draw_with_replacements(victim, 1) == 1
    assert not victim.lost


def test_w3g2_the_scope_word_is_payload_not_a_constant(set_pool):
    """"If a card would be put into **a** graveyard from anywhere, exile it
    instead." (Rest in Peace's sentence, Planar Void's.)

    The same production with a different seat in it, so the matcher takes the
    scope as payload rather than pinning Forbidden Crypt's wording. Checked
    with an invented card carrying the printed line, which is the "would a
    second card work?" test the card-hook bar asks for — and the answer has to
    be yes, or the phrase belongs in ``card_hooks``.
    """
    from engine.replacements import graveyard_exile_scope

    assert graveyard_exile_scope(
        "If a card would be put into your graveyard from anywhere, exile that "
        "card instead."
    ) == "you"
    assert graveyard_exile_scope(
        "If a card would be put into a graveyard from anywhere, exile it instead."
    ) == "any"
    assert graveyard_exile_scope(
        "If a card would be put into an opponent's graveyard from anywhere, "
        "exile it instead."
    ) == "opponent"
    assert graveyard_exile_scope("Destroy target creature.") is None

    from tests.helpers import _mk_card as _w3g2c_mk_card

    lea = _w3g2c_lea()
    void = _w3g2c_mk_card(
        "Planar Void (test)", "{B}", "Enchantment",
        "If a card would be put into a graveyard from anywhere, exile it "
        "instead.",
    )
    game = _w3g2c_Game(players=[
        _w3g2c_PlayerState(name="P1", library=[lea["Island"]] * 5),
        _w3g2c_PlayerState(name="P2", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, _w3g2c_Permanent(card=void), None)

    for seat in (0, 1):
        player = game.players[seat]
        assert game.put_card_into_graveyard(player, lea["Black Lotus"]) is False
        assert player.graveyard == []
        assert [card.name for card in player.exile] == ["Black Lotus"]
    assert _w3g2c_compile(void).supported, "the shape claims its own line"


# --- W3G-solo: Celestial Dawn, three sentences that had to land together ---
#
# The set's last card, and the one W3G1 declined with its pieces named. Every
# test here exists because the card compiled **supported** with only its first
# line implemented: a card is supported when *any* of its lines is, so the
# land-type sentence alone made a three-sentence card read as done.

from engine import Game as _dawn_Game, PlayerState as _dawn_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _dawn_load,  # noqa: E402
                                manifest_set_path as _dawn_path)
from engine.models import Permanent as _dawn_Permanent  # noqa: E402
from engine.handlers._common import _card_matches_filter as _dawn_matches  # noqa: E402
from engine.search_filters import search_matches as _dawn_search  # noqa: E402


def _dawn_lea():
    return {card.name: card for card in _dawn_load(_dawn_path("LEA"))}


def _dawn_game(set_pool, mine=(), theirs=(), hand=(), with_dawn=True):
    """Seat 0 with *mine* (plus Celestial Dawn) and seat 1 with *theirs*."""
    lea = _dawn_lea()
    pool = set_pool("MIR")
    battlefield = [_dawn_Permanent(card=lea[name]) for name in mine]
    if with_dawn:
        battlefield.append(_dawn_Permanent(card=pool["Celestial Dawn"]))
    game = _dawn_Game(players=[
        _dawn_PlayerState(name="P1", battlefield=battlefield,
                          hand=[lea[name] for name in hand]),
        _dawn_PlayerState(name="P2",
                          battlefield=[_dawn_Permanent(card=lea[n]) for n in theirs]),
    ])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game


def test_celestial_dawn_needs_all_three_sentences(set_pool):
    """The card is supported and every printed sentence is claimed.

    The guard against the failure this card was declined for: with the
    land-type line alone it compiled green, because a card is supported when
    *any* line is. Asked of `parse_coverage`'s claim registry rather than of
    the support flag, which cannot tell one line from three.
    """
    from engine.oracle import compile_card_oracle
    from engine.global_statics import global_static_for
    from engine.land_types import static_land_type_change_for
    from engine.mana_spending import mana_spending_for

    card = set_pool("MIR")["Celestial Dawn"]
    assert compile_card_oracle(card).supported

    lines = [line for line in card.oracle_text.splitlines() if line.strip()]
    assert len(lines) == 3, "the card prints three lines; the claims below are per line"
    assert static_land_type_change_for(lines[0].lower().rstrip(".")) is not None
    static = global_static_for(lines[1])
    assert static is not None and static.sets_colors == ("white",)
    assert static.extends_to_spells_and_cards, (
        "the second sentence is what reaches the stack and the other zones"
    )
    assert mana_spending_for(lines[2]) is not None


def test_celestial_dawn_makes_only_your_lands_plains(set_pool):
    """CR 305.7 over a subject named by no land type and one seat."""
    game = _dawn_game(set_pool, mine=["Mountain"], theirs=["Mountain"])
    mine = game.players[0].battlefield[0]
    theirs = game.players[1].battlefield[0]
    assert mine.basic_land_types == ("plains",)
    assert theirs.basic_land_types == ("mountain",), (
        "'lands you control' is a seat, and the opponent is not it"
    )


def test_celestial_dawn_recolours_your_nonland_permanents(set_pool):
    """CR 613 layer 5, and the two things the sentence does not reach."""
    game = _dawn_game(set_pool, mine=["Black Knight", "Swamp"],
                      theirs=["Black Knight"])
    knight, swamp = game.players[0].battlefield[0], game.players[0].battlefield[1]
    assert sorted(knight.effective_colors) == ["W"]
    assert sorted(swamp.effective_colors) == [], "a land is not a nonland permanent"
    assert sorted(game.players[1].battlefield[0].effective_colors) == ["B"]


def test_celestial_dawn_recolours_the_cards_you_own_elsewhere(set_pool):
    """The second sentence, over a hand and over a library search.

    Three readers of one fact (`engine/object_colors.py`) — a filter payload, a
    library search and a spell on the stack — and this pins the two that had
    documented the printed reading as deliberate.
    """
    lea = _dawn_lea()
    ritual = lea["Dark Ritual"]
    for with_dawn, expect_white in ((False, False), (True, True)):
        game = _dawn_game(set_pool, with_dawn=with_dawn)
        seat = game.players[0]
        assert _dawn_matches(ritual, {"color_filter": "W"},
                             game=game, owner=seat) is expect_white
        assert _dawn_matches(ritual, {"color_filter": "B"},
                             game=game, owner=seat) is not expect_white
        assert _dawn_search(
            ritual, {"card_type": "any", "restrictions": {"any_colors": ["W"]}},
            game=game, owner=0,
        ) is expect_white


def test_celestial_dawn_land_cards_in_hand_keep_their_colour(set_pool):
    """"nonland cards you own" — a Swamp in hand is a land wherever it is."""
    game = _dawn_game(set_pool)
    swamp = _dawn_lea()["Swamp"]
    assert _dawn_matches(swamp, {"color_filter": "W"},
                         game=game, owner=game.players[0]) is False


def test_celestial_dawn_spends_white_for_anything_and_nothing_else(set_pool):
    """CR 106.6 both ways: the permission *and* the restriction.

    The restriction is the half that is easy to drop and the half that is most
    of the card — without it the Dawn would let a seat cast everything its own
    lands could have cast anyway, plus everything white pays for.
    """
    game = _dawn_game(set_pool)
    seat = game.players[0]
    cost = lambda **kw: {sym: kw.get(sym, 0) for sym in
                         ("W", "U", "B", "R", "G", "C")} | {"generic": kw.get("generic", 0)}

    seat.mana_pool.update({"W": 1})
    assert game._pay_mana_cost(seat, cost(R=1)) is True, "white pays any colour"

    seat.mana_pool.clear()
    seat.mana_pool.update({"B": 1})
    assert game._pay_mana_cost(seat, cost(B=1)) is False, (
        "'only as though it were colorless' takes away the unit's own colour too"
    )

    seat.mana_pool.clear()
    seat.mana_pool.update({"B": 2})
    assert game._pay_mana_cost(seat, cost(generic=2)) is True, (
        "colorless mana still pays generic"
    )


# --- W4G4: an entry choice the sentence itself narrows (CR 614.1c) ---
#
# "As this enchantment enters, choose Island or Swamp." (Roots of Life) and
# "...choose black or red." (Mangara's Equity) are the CR 614.1c choice the pool
# already makes six ways, with the *offer* printed on the card instead of named
# by a catalog. One reader for both, because the two printed words are what say
# which record the answer lands in.
#
# The half of this that was already built is the half worth writing down: the
# records (`chosen_color`, `chosen_land_type`), the phrases that read them back
# ("of the chosen color", "of the chosen type"), the matcher resolvers and
# `TESTABLE_SUBJECT_FILTER_KEYS` all existed. What did not was one entry in
# `_PAYLOAD_HONOURED_FILTER_FIELDS` - so `subject_filter_payload` refused every
# phrase carrying one, and Roots of Life's second sentence compiled to **no
# trigger at all** while the card reported supported and `parse_coverage`
# claimed the line.

import pytest as _w4g4_pytest  # noqa: E402

from engine import Game as _w4g4_Game, PlayerState as _w4g4_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w4g4_load,  # noqa: E402
                                manifest_set_path as _w4g4_path)
from engine.enter_effects import (  # noqa: E402
    choose_one_of_two_on_enter as _w4g4_two_options,
    enter_effect_line as _w4g4_entry_line,
)
from engine.grammar import subject_filter_payload as _w4g4_subject_payload  # noqa: E402
from engine.models import Permanent as _w4g4_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w4g4_compile  # noqa: E402
from engine.subject_filters import (  # noqa: E402
    TESTABLE_SUBJECT_FILTER_KEYS as _w4g4_TESTABLE,
)


def _w4g4_basics():
    return {card.name: card for card in _w4g4_load(_w4g4_path("LEA"))}


def _w4g4_roots_board(pool, answer=None, opponent_lands=("Island", "Swamp")):
    """Roots of Life on seat 0 and *opponent_lands* on seat 1, choice answered.

    ``answer=None`` leaves the prompt standing, which is how the default is
    read: the record is stamped as the permanent enters so a headless or AI
    seat never blocks, and the prompt only overwrites it.
    """
    lea = _w4g4_basics()
    roots = _w4g4_Permanent(card=pool["Roots of Life"])
    lands = [_w4g4_Permanent(card=lea[name]) for name in opponent_lands]
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[roots]),
        _w4g4_PlayerState(name="P2", battlefield=lands),
    ])
    game.enforce_mana_costs = False
    # Interactive, so the choice is *queued* rather than defaulted away at the
    # arming - a queued prompt is the only one anybody ever answers.
    game.interactive_seats = {0}
    game._initialize_permanent_state(roots, 0, 1)
    if answer is not None:
        assert game.confirm_enter_choice(0, land_type=answer) is True
    return game, roots, dict(zip(opponent_lands, lands))


def test_w4g4_a_chosen_value_phrase_is_a_payload_the_trigger_table_can_read():
    """The one-line gap, named directly.

    All three "of the chosen ..." narrowings are in
    ``TESTABLE_SUBJECT_FILTER_KEYS`` - ``subject_matches`` resolves each off the
    source and answers it - so a trigger condition delimiting one as a
    ``_subject`` group must get a payload back rather than a refusal.
    """
    described = _w4g4_subject_payload("a land of the chosen type an opponent controls")

    assert described == {
        "type_filter": "land", "controller": "opponent", "chosen_land_type": True,
    }
    assert not set(described) - _w4g4_TESTABLE
    assert _w4g4_subject_payload("a creature of the chosen color") == {
        "type_filter": "creature", "chosen_color": True,
    }


def test_w4g4_roots_of_life_compiles_both_of_its_sentences(set_pool):
    """The entry choice is claimed by the entry-state reader and the sentence
    behind it is a real trigger - not a card supported on one line of two."""
    card = set_pool("MIR")["Roots of Life"]
    program = _w4g4_compile(card)

    assert program.supported
    assert _w4g4_entry_line(
        "As this enchantment enters, choose Island or Swamp.", card.name
    ) == "chooses one of two printed options as it enters"
    conditions = [trig.condition for trig in program.triggered_abilities]
    assert [c.kind for c in conditions] == ["permanent_becomes_tapped"]
    assert conditions[0].payload == {
        "tapped_filter": {
            "type_filter": "land", "controller": "opponent", "chosen_land_type": True,
        }
    }


def test_w4g4_the_entry_prompt_offers_exactly_the_two_printed_words(set_pool):
    """CR 205.3i's catalog is not what bounds this answer - the sentence is."""
    game, roots, _ = _w4g4_roots_board(set_pool("MIR"))
    pending = game.pending_enter_choice

    assert pending["needs_land_type"] is True
    assert pending["entry_choice_options"] == ["island", "swamp"]
    # Stamped before the prompt, so a seat that never answers still has a
    # choice on record rather than an inert enchantment.
    assert roots.metadata["chosen_land_type"] in ("island", "swamp")


def test_w4g4_an_unprinted_land_type_is_refused_not_repaired(set_pool):
    """A third type here is a strictly better card. Refused with the prompt
    still standing, so the player can answer it properly."""
    game, roots, _ = _w4g4_roots_board(set_pool("MIR"))

    assert game.confirm_enter_choice(0, land_type="forest") is False
    assert roots.metadata["chosen_land_type"] != "forest"
    assert game.pending_enter_choice is not None


@_w4g4_pytest.mark.parametrize("answer", ["island", "swamp"])
def test_w4g4_the_trigger_follows_the_answer_either_way(set_pool, answer):
    """Both answers, because a trigger that fires on either type passes a test
    that only ever chose one."""
    game, roots, lands = _w4g4_roots_board(set_pool("MIR"), answer=answer)
    assert roots.metadata["chosen_land_type"] == answer

    gains = {}
    for name, land in lands.items():
        before = game.players[0].life
        game.become_tapped(land)
        game.resolve_stack()
        gains[name.lower()] = game.players[0].life - before

    assert gains.pop(answer) == 1
    assert set(gains.values()) == {0}


def test_w4g4_a_permanent_that_has_not_chosen_gains_nothing(set_pool):
    """The habit ``resolve_static_land_type_change`` records, kept here: an
    entry choice that was never made must not behave as though every type had
    been chosen. The matcher refuses on the unresolved key rather than dropping
    it, which would gain life off every land an opponent taps."""
    lea = _w4g4_basics()
    roots = _w4g4_Permanent(card=set_pool("MIR")["Roots of Life"])
    island = _w4g4_Permanent(card=lea["Island"])
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[roots]),
        _w4g4_PlayerState(name="P2", battlefield=[island]),
    ])
    game.enforce_mana_costs = False
    # No `_initialize_permanent_state`: the record is absent, which is what a
    # permanent that arrived by a road with no entry state looks like.
    assert "chosen_land_type" not in roots.metadata

    game.become_tapped(island)
    game.resolve_stack()

    assert game.players[0].life == 20


def test_w4g4_the_two_option_reader_needs_one_catalog_and_two_words():
    """The printed words decide which record the answer lands in, so a pair
    spanning two catalogs has no record to name and refuses."""
    assert _w4g4_two_options(
        "As this enchantment enters, choose Island or Swamp."
    ) == ("chosen_land_type", ("island", "swamp"))
    assert _w4g4_two_options(
        "As this enchantment enters, choose black or red."
    ) == ("chosen_color", ("B", "R"))
    # A card nobody printed, in three flavours: mixed catalogs, a repeat (which
    # is not a choice) and a sentence that says more than the offer.
    assert _w4g4_two_options("As this enchantment enters, choose black or Swamp.") is None
    assert _w4g4_two_options("As this enchantment enters, choose black or black.") is None
    assert _w4g4_two_options(
        "As this enchantment enters, choose black or red, then draw a card."
    ) is None


# --- W4G4 (continued): a damage trigger narrowed on both ends ---
#
# "Whenever a creature of the chosen color deals damage to you or a white
# creature you control, this enchantment deals that much damage to that
# creature." (Mangara's Equity.) CR 120.4b's event with three printed
# narrowings, every one of them a thing the pool already half-had:
#
#  * the **damager** goes through the noun parser like Justice's "a red
#    creature", now that a chosen-value phrase is a payload it can return;
#  * the **recipient** is a seat word *or* a noun phrase, which no single word
#    in `_DAMAGE_RECIPIENT_TESTS` can say - so the seat stays a word and the
#    object half is a `_subject` group. "you" being a strict prefix of "you
#    or ..." is what took the whole condition down before: the fixed list
#    matched the seat and then failed the comma bound;
#  * "**that much**" is the damage *dealt* (CR 120.4b), which is what a shield
#    reduces and what a life-total cap does not.
#
# And "that creature" names the damager. It lowers to the `event_subject`
# recipient the bare pronoun "it" already used - two spellings of one
# back-reference - which needed `damage_events._announce` to freeze the
# damager's id beside the damaged permanent's. The two are opposite ends of one
# event, and only one of them had a key.

from engine.handlers._common import (  # noqa: E402
    apply_damage_to_creature as _w4g4_damage_creature,
)
from engine.shields import (Shield as _w4g4_Shield,  # noqa: E402
                            add_shield as _w4g4_add_shield,
                            PREVENT_NEXT_N as _w4g4_PREVENT_N)
from tests.helpers import _mk_card as _w4g4_mk  # noqa: E402


def _w4g4_body(name, colour, power=3):
    return _w4g4_mk(
        name, "Creature - Ogre", "", power=power, toughness=power, colors=(colour,)
    )


def _w4g4_equity_board(pool, answer):
    """Mangara's Equity with the colour answered, a white and a green creature
    under it, and a black and a red creature opposite."""
    equity = _w4g4_Permanent(card=pool["Mangara's Equity"])
    mine = {
        "white": _w4g4_Permanent(card=_w4g4_body("White Bear", "W", power=2)),
        "green": _w4g4_Permanent(card=_w4g4_body("Green Bear", "G", power=2)),
    }
    theirs = {
        "black": _w4g4_Permanent(card=_w4g4_body("Black Ogre", "B")),
        "red": _w4g4_Permanent(card=_w4g4_body("Red Ogre", "R")),
    }
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[equity, *mine.values()]),
        _w4g4_PlayerState(name="P2", battlefield=list(theirs.values())),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._initialize_permanent_state(equity, 0, 1)
    assert game.confirm_enter_choice(0, mana_color=answer) is True
    assert equity.metadata["chosen_color"] == answer
    return game, equity, mine, theirs


def _w4g4_hit(game, damager, victim):
    """*damager* deals 3 to *victim*, and the trigger behind it resolves."""
    if isinstance(victim, _w4g4_PlayerState):
        game._deal_damage_to_player(victim, 3, source=damager)
    else:
        _w4g4_damage_creature(game, victim, 3, damager)
    game.resolve_stack()
    return damager.damage_marked


def test_w4g4_mangaras_equity_compiles_its_third_sentence(set_pool):
    """Both ends of the condition and the effect between them."""
    program = _w4g4_compile(set_pool("MIR")["Mangara's Equity"])
    assert program.supported

    trig = next(
        t for t in program.triggered_abilities if t.condition.kind == "damage_dealt"
    )
    assert trig.condition.payload == {
        "damage_recipient_seat": "you",
        "damager_filter": {"type_filter": "creature", "chosen_color": True},
        "damaged_filter": {
            "type_filter": "creature", "color_filter": "W", "controller": "you",
        },
    }
    assert trig.instruction.kind == "deal_damage"
    assert trig.instruction.payload == {
        "amount_from_trigger": "amount",
        "recipient": "event_subject",
        "filter": {"type_filter": "creature"},
    }


@_w4g4_pytest.mark.parametrize("answer", ["B", "R"])
def test_w4g4_the_damager_must_be_the_chosen_colour(set_pool, answer):
    """Both answers, because a trigger that fires on either colour passes a
    test that only ever chose one."""
    other = "R" if answer == "B" else "B"
    names = {"B": "black", "R": "red"}

    game, _, _, theirs = _w4g4_equity_board(set_pool("MIR"), answer)
    assert _w4g4_hit(game, theirs[names[answer]], game.players[0]) == 3

    game, _, _, theirs = _w4g4_equity_board(set_pool("MIR"), answer)
    assert _w4g4_hit(game, theirs[names[other]], game.players[0]) == 0


def test_w4g4_the_recipient_is_a_seat_or_a_noun_phrase_and_nothing_else(set_pool):
    """"you **or** a white creature you control" is one recipient described two
    ways, so whichever the event's recipient *is* decides which half answers.
    The green creature and the opponent are the two halves' misses."""
    pool = set_pool("MIR")

    game, _, mine, theirs = _w4g4_equity_board(pool, "B")
    assert _w4g4_hit(game, theirs["black"], mine["white"]) == 3

    game, _, mine, theirs = _w4g4_equity_board(pool, "B")
    assert _w4g4_hit(game, theirs["black"], mine["green"]) == 0

    game, _, _, theirs = _w4g4_equity_board(pool, "B")
    assert _w4g4_hit(game, theirs["black"], game.players[1]) == 0


def test_w4g4_that_much_is_the_damage_dealt_not_the_power(set_pool):
    """CR 120.4b's number. A shield over the recipient reduces what was dealt,
    and the reflection is that — a read of the creature's power would send
    three back through a shield that let two through."""
    game, _, _, theirs = _w4g4_equity_board(set_pool("MIR"), "B")
    _w4g4_add_shield(
        game.players[0],
        _w4g4_Shield(kind=_w4g4_PREVENT_N, amount=1, uses=None, source_name="probe"),
    )

    reflected = _w4g4_hit(game, theirs["black"], game.players[0])

    assert game.players[0].life == 18
    assert reflected == 2


def test_w4g4_an_unprinted_colour_is_refused_not_repaired(set_pool):
    """White is a legal answer to "choose a color" and is not one here."""
    equity = _w4g4_Permanent(card=set_pool("MIR")["Mangara's Equity"])
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[equity]),
        _w4g4_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._initialize_permanent_state(equity, 0, 1)

    assert game.pending_enter_choice["entry_choice_options"] == ["B", "R"]
    assert game.confirm_enter_choice(0, mana_color="W") is False
    assert equity.metadata["chosen_color"] in ("B", "R")
    # A board answering neither option falls to the first printed word rather
    # than to an alphabetical accident.
    assert equity.metadata["chosen_color"] == "B"


def test_w4g4_the_default_is_the_option_the_opponents_answer_most(set_pool):
    """idiom 8: an option nobody's board answers makes the enchantment inert,
    which is legal and is not a choice any player would make."""
    equity = _w4g4_Permanent(card=set_pool("MIR")["Mangara's Equity"])
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[equity]),
        _w4g4_PlayerState(name="P2", battlefield=[
            _w4g4_Permanent(card=_w4g4_body("Red Ogre", "R")),
            _w4g4_Permanent(card=_w4g4_body("Other Red Ogre", "R")),
            _w4g4_Permanent(card=_w4g4_body("Black Ogre", "B")),
        ]),
    ])
    game.enforce_mana_costs = False
    game._initialize_permanent_state(equity, 0, 1)

    assert equity.metadata["chosen_color"] == "R"


# --- W4G4 (continued): two effects in one draw-step trigger ---
#
# "At the beginning of each opponent's draw step, that player draws an
# additional card for each growth counter on this enchantment, then this
# enchantment deals damage to the player equal to the number of cards they drew
# this way." (Malignant Growth.)
#
# Three pieces, none of them fused into a kind:
#
#  * the **scope** is payload on `draw_step_each`, exactly as `upkeep_scope` is
#    one step of the turn earlier - a condition kind is a dispatcher's address,
#    and spelling the subject into it gives one card its own fire site;
#  * the **count** is `for each <word> counter on <the source>`, read through
#    the same `accept_counters_on_source` the where-clause spelling of the
#    identical phrase already goes through, so the two word orders count the
#    same thing;
#  * the two halves compose through `sequence`, and the second reads what the
#    first *did* - the number that arrived, not the number asked for.
#
# And "that player" is the seat the fire site froze. Left to `context.target` a
# trigger that chooses nothing carries whatever the resolution was holding,
# which here is the enchantment's own controller: the card would have drawn its
# controller the cards and dealt its controller the damage.

from engine.named_counters import add_counters as _w4g4_add_counters  # noqa: E402


def _w4g4_growth_board(pool, counters, library=40):
    """Malignant Growth on seat 0 with *counters* growth counters."""
    lea = _w4g4_basics()
    growth = _w4g4_Permanent(card=pool["Malignant Growth"])
    game = _w4g4_Game(players=[
        _w4g4_PlayerState(name="P1", battlefield=[growth],
                          library=[lea["Island"]] * 40),
        _w4g4_PlayerState(name="P2", library=[lea["Forest"]] * library),
    ])
    game.enforce_mana_costs = False
    if counters:
        _w4g4_add_counters(growth, "growth", counters)
    return game, growth


def _w4g4_draw_step(game, seat):
    """Run *seat*'s draw-step trigger batch and report what it did to them."""
    player = game.players[seat]
    before = (len(player.hand), player.life, len(player.library))
    game._enqueue_draw_step_triggers(seat)
    game.resolve_stack()
    return (
        len(player.hand) - before[0],
        before[1] - player.life,
        before[2] - len(player.library),
    )


def test_w4g4_malignant_growth_compiles_its_third_sentence(set_pool):
    """Two instructions in a sequence, not one fused kind - and the second
    reads the first's record rather than recomputing the count."""
    program = _w4g4_compile(set_pool("MIR")["Malignant Growth"])
    assert program.supported

    trig = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "draw_step_each"
    )
    assert trig.condition.payload == {"draw_step_scope": "opponent"}
    assert trig.instruction.kind == "sequence"
    draw, damage = trig.instruction.payload["steps"]
    assert draw.kind == "draw_target_cards"
    assert draw.payload == {
        "amount": "x",
        "x_from_count": {"source_counters": "growth"},
        "drawer_seat_record": "event_subject_player",
    }
    assert damage.kind == "deal_damage"
    assert damage.payload == {
        "amount_from": "drew_count", "recipient": "event_subject_player",
    }


@_w4g4_pytest.mark.parametrize("counters", [0, 1, 2, 3])
def test_w4g4_the_draw_and_the_damage_both_follow_the_counter_count(set_pool, counters):
    """A different count each turn, because a trigger sized from one number
    passes a test that only ever put one counter on it."""
    game, _ = _w4g4_growth_board(set_pool("MIR"), counters)

    drawn, damage, milled = _w4g4_draw_step(game, 1)

    assert (drawn, damage, milled) == (counters, counters, counters)


def test_w4g4_the_controllers_own_draw_step_is_not_an_opponents(set_pool):
    """"each **opponent's** draw step" — whose opponents is CR 109.5's answer,
    the source's controller, so the card's own draw step is not one of them."""
    game, _ = _w4g4_growth_board(set_pool("MIR"), 3)

    assert _w4g4_draw_step(game, 0) == (0, 0, 0)


def test_w4g4_the_damage_is_what_was_drawn_not_what_was_asked_for(set_pool):
    """"the number of cards they drew **this way**" is a record of the step in
    front of it. Three counters over a two-card library draw two, so two is the
    damage — a recomputation of the counters would deal three."""
    game, _ = _w4g4_growth_board(set_pool("MIR"), 3, library=2)

    drawn, damage, _ = _w4g4_draw_step(game, 1)

    assert (drawn, damage) == (2, 2)


def test_w4g4_the_cards_and_the_damage_go_to_the_opponent(set_pool):
    """The seat the fire site froze, not the one the resolution was carrying:
    read as ``context.target`` this trigger drew for its own controller."""
    game, _ = _w4g4_growth_board(set_pool("MIR"), 2)
    controller = game.players[0]
    before = (len(controller.hand), controller.life)

    _w4g4_draw_step(game, 1)

    assert (len(controller.hand), controller.life) == before
    assert len(game.players[1].hand) == 2
    assert game.players[1].life == 18


def test_w4g4_a_drew_this_way_count_needs_a_draw_in_front_of_it():
    """idiom 7: a back-reference with no producer names nothing, and a zero is a
    number the card never printed. The words parse either way; what refuses is
    the lowering, which is where the producer is known."""
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    node = parse_line(
        "This enchantment deals damage to that player equal to the number of "
        "cards they drew this way."
    )
    with _w4g4_pytest.raises(LoweringError):
        lower_ability(node, event="draw_step_each")


def test_w4g4_the_drew_this_way_count_names_bare_cards_and_nothing_narrower():
    """The record holds how many arrived, not what they were — so a phrase
    asking it a question about the cards refuses rather than counting all of
    them."""
    from engine.grammar.errors import GrammarError
    from engine.grammar import parse_line

    with _w4g4_pytest.raises(GrammarError):
        parse_line(
            "That player draws two cards, then this enchantment deals damage "
            "to that player equal to the number of creature cards they drew "
            "this way."
        )
