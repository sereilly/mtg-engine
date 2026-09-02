"""Guard: ``engine/grammar/derived.py`` stays a delegation, not a second parser.

A derivation table matching on raw text is exactly the shape this migration is
deleting. Three properties are what make these entries something other than
``engine/parsing/`` relocated into the grammar, and none of them holds by
inspection:

* **a table may only reach text no production can read.** ``parse_line`` runs
  every production first and consults the tables only after a ``GrammarError``.
  Reorder that and ``engine/lord_buffs.py`` starts claiming every anthem in the
  pool, silently taking those lines off the production that reads them.
* **the lowered instruction is the table's own output**, not a rebuilt copy of
  it — so a payload the grammar emits and a payload the consumer dispatches on
  cannot describe different effects.
* **every entry is reachable.** A table nothing in the pool routes to is either
  dead weight or, worse, a claim that has quietly stopped matching the line it
  was written for.
"""

from __future__ import annotations

import pytest

from engine import oracle
from engine.card_loader import load_catalog, load_cards, manifest_set_paths
from engine.grammar import ast as grammar_ast, compile_line
from engine.grammar.derived import TABLES, derived_instruction_for_line
from engine.grammar.errors import GrammarError
from engine.grammar.parser import _parse_line


@pytest.fixture(scope="module")
def pool_lines():
    """Every printed line of every card, with the card that printed it.

    The **measured** sets are included, unlike ``load_catalog``'s shipped pool.
    A derivation table is written for the card that needs it, and that card is
    in a measured set for the whole of the set's implementation — so a
    shipped-only reading would call every new table dead on the round that
    added it and force the entry to be written after the promotion instead of
    with the card. This is a reachability question, not a coverage floor, so
    the wider pool is the one it should ask about.
    """
    lines = []
    for card in load_cards(manifest_set_paths(include_measured=True)):
        text = oracle.expand_modal_activated_lines(card.oracle_text or "")
        for raw in text.splitlines():
            line = raw.strip()
            if line:
                lines.append((card.name, line))
    return lines


def _derived_lines(pool_lines):
    for card_name, line in pool_lines:
        compiled = compile_line(line, card_name=card_name)
        if isinstance(compiled.node, grammar_ast.DerivedLine):
            yield card_name, line, compiled


def test_a_derived_claim_only_ever_reaches_a_line_no_production_reads(pool_lines):
    """The ordering property, asserted rather than assumed.

    Every line a table claims must be one the ordinary parser refuses in full.
    If a production later learns to read one of these, this fails and the entry
    has to move — which is the outcome that keeps the grammar authoritative.
    """
    shadowed = []
    for card_name, line, _compiled in _derived_lines(pool_lines):
        try:
            node = _parse_line(line, card_name=card_name)
        except GrammarError:
            continue
        shadowed.append((card_name, line, type(node).__name__))

    assert not shadowed, (
        "a derivation table claimed a line the grammar can parse, shadowing the "
        f"production that reads it: {shadowed}"
    )


def test_a_derived_line_lowers_to_exactly_what_its_table_derives(pool_lines):
    """The claim and the payload are one function call, in both directions."""
    for card_name, line, compiled in _derived_lines(pool_lines):
        derived = derived_instruction_for_line(line)
        assert derived is not None, (card_name, line)
        table, instruction = derived
        assert compiled.node.table == table
        assert compiled.instructions == (instruction,), (card_name, line)


def test_every_derivation_table_is_reachable_from_the_pool(pool_lines):
    """A table nothing routes to is a claim that has stopped matching."""
    reached = {compiled.node.table for _n, _l, compiled in _derived_lines(pool_lines)}
    unreachable = [table.name for table in TABLES if table.name not in reached]

    assert not unreachable, (
        "derivation tables no pool line reaches — either the entry is dead or "
        f"its matcher no longer claims the line it was written for: {unreachable}"
    )


def test_combat_restrictions_match_the_derivation_table_exactly():
    """The grammar's combat restrictions must equal engine/combat_restrictions.py.

    This is what let the category be switched on: not "the grammar produced
    something", but "it produced the same instruction kind and the same payload
    the table the consumer dispatches on produces", on every such line in the
    pool. The land type and the power threshold are payload data on both sides,
    so a card naming Mountain or a threshold of 4 is compared the same way.

    (Inherited from `test_grammar_differential.py`. Its subject was never the
    legacy rule registry: `combat_restriction_for` is a live derivation table,
    read by `phases/declare_attackers_step.py` and by the compiler's support
    gate, so the comparison outlives the deletion.)
    """
    from engine.combat_restrictions import combat_restriction_for
    from engine.oracle import normalize_creature_line

    # Shapes the grammar deliberately does not claim yet. They must keep
    # *failing the parser*, not lowering to an empty instruction list — a line
    # that parses to nothing is the silent drop this whole invariant exists to
    # prevent.
    unclaimed_kinds = {
        # `cant_be_blocked_by` covers both printed spellings — "by Walls" and
        # "by artifact creatures" — since the noun phrase became payload. The
        # grammar reads neither, so the derivation table is still the only
        # implementer and the line must keep failing the parser.
        "must_attack_each_combat", "cant_be_blocked_by", "cant_attack", "cant_block",
        # "This creature can block only creatures with flying." (Shacklegeist,
        # M21's first printing of the shape.) The derivation table implements it
        # and the declare-blockers step dispatches on it; the grammar has no
        # production, so the line fails the parser — which is what the assertion
        # below checks, and is the safe direction.
        "can_block_only_with_keyword",
        # "This creature must be blocked if able." (Canopy Stalker.) Same
        # position: the table implements it, the grammar does not read it.
        "must_be_blocked",
        # --- the nine Legends shipped, all in the same position ---------------
        # Promotion widened `load_catalog()` over Legends and these arrived at
        # once. Every one is implemented by `engine/combat_restrictions.py` and
        # dispatched by the declare-attackers or declare-blockers step, and none
        # has a grammar production — so each fails the parser and the table is
        # the only implementer, which is what the assertion below checks. They
        # are listed one by one rather than as a blanket "any combat
        # restriction": the whole value of this list is that a kind arriving in
        # it was looked at, and a kind the grammar *does* read (the two that
        # reach the comparison below) must not be able to slip in silently.
        #
        # Moat and Evil Eye of Orms-by-Gore, over a described set of creatures
        # rather than over the carrier.
        "creatures_cant_attack",
        # Akron Legionnaire: "Except for creatures named Akron Legionnaire and
        # artifact creatures, creatures you control can't attack." The
        # exceptions are a union of noun-phrase filters in the payload, tested
        # by `subject_matches` at declaration — the self-name among them is
        # *data* in a filter, not a name-keyed dispatch
        # (tests/engine/test_card_name_reads.py draws that line).
        "controlled_creatures_cant_attack",
        # Giant Turtle's "if it attacked during your last turn", read off the
        # attack record the declare-attackers step stamps.
        "cant_attack_if_attacked_last_turn",
        # Arboria: a fact about the *defending player*, off the per-seat
        # last-own-turn record the turn boundary folds.
        "cant_attack_unless_defender_acted",
        # Elven Riders / Evil Eye: "can't be blocked except by …", the whitelist
        # twin of `cant_be_blocked_by` above.
        "cant_be_blocked_except_by",
        # Caverns of Despair, one card printing both halves.
        "max_attackers_each_combat", "max_blockers_each_combat",
        # Marble Priest: "All Walls able to block this creature do so."
        "must_be_blocked_by_all_able",
        # Chaos Lord's "can attack as though it had haste unless it entered
        # this turn" — a CR 609.4 *permission* rather than a restriction, in
        # the same table for the same reason and in the same position: the
        # declare-attackers step dispatches on it and the grammar has no
        # production, so the line fails the parser. Listed now rather than at
        # ICE's promotion, since `load_catalog()` is the shipped pool and this
        # card is in a measured set — the row is what keeps the promotion from
        # turning a silent absence into a red suite.
        "attacks_as_though_hasty_unless_it_entered",
        # Hipparion: "can't block creatures with power 3 or greater **unless you
        # pay {1}**". The trailing-toll production could read this sentence, and
        # did until ICE's promotion put the card in front of this guard: it wrapped
        # the restriction as the `otherwise` branch of a resolution-time offer,
        # which is a moment a static line never has, so the restriction went
        # unenforced. The production now refuses a `CombatRestriction` body, which
        # is the rule CLAUDE.md states for a sentence two readers want — the table
        # is reached only where every production refuses the line in full.
        "cant_block_power_n_or_greater_unless_pay",
        # Halls of Mist: "Creatures that attacked during their controller's last
        # turn can't attack." A board-wide restriction whose subject is a fact
        # about a *previous* turn; the table scans every seat's record in
        # `can_attack` and the grammar has no production, so the line fails the
        # parser — the same shape and the same reason as the two above.
        "creatures_that_attacked_last_turn_cant_attack",
        # Koskun Falls: "Creatures can't attack you unless their controller
        # pays {2} **for each creature they control that's attacking you**."
        # A per-attacker scaling toll, so the cost is not knowable until the
        # whole declaration is: the table implements it in
        # `declare_attackers_step`, where the seat and the attacker list are
        # both in hand, and the grammar has no production — so the line
        # fails the parser and the table is its only implementer. Listed at
        # HML's promotion for the reason the row above gives: the guard
        # reads the *shipped* pool, so a measured set's new kind arrives
        # here the day it ships.
        "creatures_cant_attack_you_unless_pay",
    }

    compared = 0
    for card in load_catalog():
        for raw_line in card.oracle_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            derived = combat_restriction_for(normalize_creature_line(line))
            if derived is None:
                continue
            result = compile_line(line, card_name=card.name)
            if derived.kind in unclaimed_kinds:
                assert not result.parsed, (
                    f"{card.name}: {line!r} is not claimed by the grammar yet, so "
                    "it must fail the parser rather than parse to nothing"
                )
                continue
            got = [(i.kind, i.payload) for i in result.instructions]
            assert got == [(derived.kind, derived.payload)], f"{card.name}: {line!r}"
            compared += 1

    assert compared, "no combat-restriction lines were compared"


def test_a_derived_line_is_a_whole_line_or_nothing():
    """Every matcher is anchored at both ends, so a rider refuses the sentence.

    The near miss that matters is the one between the two land tables: an
    animation clause is a type change *plus* a body the type-change consumer
    would never apply, and admitting it would drop the animation silently.
    """
    animation = "All Swamps are 1/1 black creatures that are still lands."
    assert derived_instruction_for_line(animation)[0] == "land_animation"

    assert derived_instruction_for_line("All Mountains are Plains.")[0] == "land_types"
    assert derived_instruction_for_line("All Mountains are Plains and you gain 2 life") is None
    assert derived_instruction_for_line("All Wombats are Plains") is None
