"""The oracle-text parser.

A tokenizer plus a recursive-descent grammar over Magic's card templating,
producing a typed AST (``ast/``) that is lowered to the ``OracleInstruction``
IR (``lower.py``). It replaced the flat ``@parse_rule`` registry in
``engine/parsing/``, which needed roughly one hand-written rule per two cards
and silently dropped any part of a card's text its first matching rule did not
cover.

**It is the only parser.** ``engine/oracle.py`` reads a line through this
package and then through ``card_hooks.CARD_LINE_INSTRUCTIONS``, and there is
nothing after that: a line neither claims produces no instruction, and its card
is reported unsupported naming the clause.

That is what :data:`GRAMMAR_CATEGORIES` now means. It was the migration's
valve — a category switched off fell back to the legacy rules, so work could
land and be measured before it was switched on — and with nothing underneath,
switching a category off does not route its lines elsewhere, it makes cards
unsupported. So the set is held equal to every category ``lower.py`` can emit
(``tests/engine/test_grammar_categories.py``), and adding a lowering without
adding its category fails loudly instead of quietly costing cards their support.

Coverage is tracked in ``GRAMMAR_COVERAGE.md`` via ``scripts/grammar_coverage.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..oracle_types import OracleInstruction
from . import ast
from .errors import GrammarError, LoweringError
from .lower import GRAMMAR_ONLY_PAYLOAD_KEYS, categories_of, lower_ability
from .lowering._common import _filter_payload, _restrictions_beyond
from .parser import parse_line
from .phrases import parse_subject_filter

# Categories whose grammar output is executed. Held equal to every category
# lower.py can emit, by tests/engine/test_grammar_categories.py — see the module
# docstring for why that equality is the invariant now rather than a coincidence.
#
# The history below is why each was *safe* to switch on, and it is the record of
# what was checked before a category's output started running. It is kept
# because that is the argument a new category has to make too; the phase numbers
# are the migration's, and the migration is over.
#
# Phase 1 turned on damage, pump, and life: together they cover every
# grammatical position an effect clause can occupy (spell, activated ability,
# trigger remainder), and both handler families are already generic and
# payload-driven, so the risk sat in the parser — which is where the guards
# point.
#
# Phase 3 added destruction and tapping. Destruction is the clearest
# demonstration of what the grammar buys: five legacy rules whose relative
# precedence had to be hand-numbered ("destroy all creatures" before "destroy
# target", and both before the land-type sweep) collapse into one production
# where the distinction falls out of the noun phrase's quantifier — and the
# lowered instructions are byte-identical for every card in the pool.
#
# Phase 4 added optional, zones and mana. Each had a specific blocker rather
# than a coverage gap, and each blocker was a real bug:
#   optional — "you may pay {N}" had no representation, so six cards were
#              name-keyed hooks; and the dies-trigger fire site dropped any
#              instruction shape it did not recognize.
#   zones    — "you draw" and "target player draws" are different handlers with
#              different drawers, not one handler with a recipient flag.
#   mana     — add_mana_from_text re-read the clause text; it now takes
#              structured pips.
#
# Phase 5 added turns and evasion. Both are single-handler categories whose
# handlers take an empty payload, so the risk is entirely in the noun phrase
# the production accepts — which is where their lowering refusals point:
#   turns    — grant_extra_turn queues a turn for the effect's controller and
#              takes no count, so the production is singular by construction
#              ("two extra turns" fails to parse) and a non-controller taker is
#              refused.
#   evasion  — grant_unblockable_to_low_power_target hardcodes "power 2 or
#              less" in its own source *and* again in legality.py's target
#              enumerator. Lowering checks the parsed comparison against that
#              literal, so a future "power 3 or less" refuses instead of
#              compiling cleanly onto the wrong threshold.
#
# Phase 5 also added tokens. create_token already builds the whole token card
# from its payload (engine/tokens.py), so nothing about a token-making card is
# per-card except the characteristics the production transcribes — which is
# also why the two refusals are about characteristics the *payload* cannot
# carry rather than about the parse: a token with no printed name, and a token
# that is not a creature.
#
# Phase 5 also added counters. The two handlers in it size a counter placement
# by the number of creatures that died this turn, reading that count from the
# trigger's context and nothing at all from their payload — so the whole
# category's risk is that the parse might claim a clause the handlers would
# then ignore, which is exactly what the lowering's equality checks refuse:
# a different subject, a different counted set, or a multiplier other than one
# per death.
#
# Still off, with the reason:
#   (nothing, and nothing may be) — every category with a lowering is switched
#              on, and the guard now requires it. Effects the grammar cannot yet
#              lower (static abilities, multi-mana player-chosen colour, most
#              zone movement) refuse at *lowering* and so never reach a
#              category at all; the coverage report tracks them as "parsed but
#              not lowered", which is the honest place for them.
GRAMMAR_CATEGORIES: frozenset[str] = frozenset(
    {
        "damage", "pump", "life", "destruction", "tapping", "optional", "zones",
        "mana", "regeneration", "counterspells", "prevention", "recolor", "upkeep",
        "turns", "evasion", "tokens", "counters", "text_change", "control",
        # Ending the game (CR 104): "You win the game.", "Target player loses
        # the game.", "The game is a draw." No card in the pool prints one — the
        # legacy registry had rules for all three and they went unexercised by
        # any printing, which is how the gap survived. Switched on with the
        # productions, because with no fallback underneath a category left off
        # is a card reported unsupported rather than a card read by something
        # else.
        "game_end",
        # Enabled after the differential showed the grammar's payloads equal
        # engine/combat_restrictions.py's on every such line in the pool. The
        # two shapes it does NOT claim ("attacks each combat if able",
        # "can't be blocked by Walls") still fail the parser by name rather
        # than lowering to nothing.
        "combat_restrictions",
        # A permanent's continuous anthem or lord buff. Enabled after the
        # differential showed the grammar's payload equal to what
        # engine/lord_buffs.py derives for every such line in the pool — both
        # front ends read that one table, so agreement is structural rather than
        # a coincidence to be re-checked.
        "static_buffs",
        # A board-wide static over lands: Kormus Bell's animation, Conversion's
        # type change. Both arrive through engine/grammar/derived.py, which
        # hands over the derivation table's own instruction rather than building
        # one — so "the grammar agrees with the table" is an identity, not a
        # comparison the differential has to make.
        "land_statics",
        # Flipping a coin (CR 705). Switched on with the production, because
        # with nothing underneath the grammar a category left off is a card
        # reported unsupported rather than a card read by something else. The
        # branches behind a flip carry their own categories, so this switch
        # gates the randomiser and nothing more.
        "coin_flips",
    }
)


@dataclass(frozen=True)
class CompiledLine:
    """Result of running the grammar over one oracle line."""

    line: str
    node: ast.AbilityNode | None = None
    instructions: tuple[OracleInstruction, ...] = ()
    categories: frozenset[str] = field(default_factory=frozenset)
    parse_error: str | None = None
    lowering_error: str | None = None
    # The line carried no rules text at all — it was entirely reminder text,
    # e.g. a basic land's "({T}: Add {G}.)". Not a failure and not a success:
    # coverage measures exclude it, because there is nothing to claim.
    blank: bool = False

    @property
    def parsed(self) -> bool:
        """The grammar accounted for every token of the line."""
        return self.node is not None

    @property
    def lowered(self) -> bool:
        """The AST mapped onto executable instructions."""
        return self.parsed and self.lowering_error is None

    @property
    def usable(self) -> bool:
        """Lowered *and* every category it touches is switched on."""
        return (
            self.lowered
            and bool(self.categories)
            and self.categories <= GRAMMAR_CATEGORIES
        )

    @property
    def failure_reason(self) -> str | None:
        return self.parse_error or self.lowering_error


def compile_line(line: str, *, card_name: str | None = None) -> CompiledLine:
    """Parse and lower one oracle line. Never raises — failures are data.

    Callers integrating with the legacy compiler check :attr:`CompiledLine.usable`;
    the coverage script reads the finer-grained flags to tell "the grammar could
    not read this" apart from "the grammar read it but nothing executes it yet".
    """
    try:
        node = parse_line(line, card_name=card_name)
    except GrammarError as error:
        if error.reason == "empty line":
            return CompiledLine(line=line, blank=True)
        return CompiledLine(line=line, parse_error=error.reason)
    except RecursionError:  # pragma: no cover - defensive
        return CompiledLine(line=line, parse_error="recursion limit")

    # Keyword lines legitimately lower to nothing; they are recorded by the
    # compiler as keyword lines rather than instructions.
    #
    # Registry lines lower to nothing for a different reason: a text-keyed
    # sidecar registry already executes them off the card's raw oracle text
    # (engine/grammar/registries.py). With no instructions they have no
    # categories either, so `usable` stays False — this buys *parse* credit
    # only. The legacy path still handles the card exactly as before, which is
    # what keeps the compiler's stored text — the string those registries match
    # on — byte-identical.
    if isinstance(node, (ast.KeywordLine, ast.RegistryLine)):
        return CompiledLine(line=line, node=node)

    try:
        instructions = lower_ability(node)
    except LoweringError as error:
        return CompiledLine(line=line, node=node, lowering_error=error.reason)

    return CompiledLine(
        line=line,
        node=node,
        instructions=instructions,
        categories=categories_of(instructions),
    )


def behavioural_payload(payload: dict) -> dict:
    """*payload* without the keys that describe rather than execute.

    Today that is ``targets``: what a line points at, recorded so the engine can
    answer targeting from the compiled program (engine/targeting.py) instead of
    re-reading oracle text. No ``EFFECT_HANDLERS`` entry reads it — it decides
    which permanents the *picker* offers, not what the resolution does.

    Its original job is finished. It existed so a grammar instruction could be
    compared against a legacy one without a purely additive description reading
    as a divergence, and both consumers of that comparison are gone: the
    grammar-vs-legacy differential retired with ``engine/parsing/``, and
    ``scripts/parse_coverage.py``'s deletion probe now compares whole payloads,
    which is strictly stricter — dropping ``targets`` was hiding the difference
    between "target attacking creature" and "target creature" from the probe,
    and comparing in full took the probe's accepted findings from 96 entries to
    9.

    What is left is ``tests/engine/test_grammar_lowering.py``, whose golden
    expectations are about what a line *does*. Deleting the helper there would
    mean writing the targeting description into every expectation, which is a
    different test.
    """
    return {k: v for k, v in payload.items() if k not in GRAMMAR_ONLY_PAYLOAD_KEYS}


#: The ``ObjectFilter`` fields ``to_payload`` actually reads. A narrowing
#: outside this set has no payload form at all, so it does not survive the trip
#: to the dispatcher — and the caller's "are all these keys testable?" check
#: cannot see the difference, because what is missing left no key behind.
#: Round 68 hit the same thing on the lowering side and paired the payload gate
#: with ``_restrictions_beyond`` over the AST; this is that pairing on the
#: *trigger* side, where the consequence is a condition that announces itself on
#: a strictly larger set than the card prints.
_PAYLOAD_HONOURED_FILTER_FIELDS = frozenset({
    "card_types", "type_match", "subtypes", "colors", "excluded_colors",
    "excluded_types", "excluded_subtypes", "with_keywords", "without_keywords",
    "controller", "tapped", "attacking", "blocking", "other_than_source",
    "nontoken", "named", "their_choice", "mana_value", "power", "toughness",
    "colored", "with_plus1_counter",
})


def subject_filter_payload(phrase: str, *, plural: bool = False) -> dict | None:
    """The payload form of the set of objects a narrowed trigger names.

    "Whenever a creature you control **with deathtouch** attacks" (Hooded
    Blightfang): the condition's subject is a noun phrase, so it is read by the
    noun parser and carried as the ``ObjectFilter`` payload
    ``permanent_matches_filter`` already tests — the same data a targeted line
    carries, in the one position where getting it wrong fires on every creature
    rather than on one.

    None means refuse, for either of the two ways this can fail: the phrase is
    not a subject the noun parser reads, or it is one carrying a restriction the
    matcher cannot test. The caller (``engine/oracle.py``'s trigger table) makes
    the whole condition refuse, because the alternative is a trigger that
    announces itself on a strictly larger set than the card prints.
    """
    filt = parse_subject_filter(phrase, plural=plural)
    if filt is None:
        return None
    # The AST gate, before the payload one. ``supertypes``, ``is_enchanted`` and
    # ``blocked`` have no ``to_payload`` key, so "a **legendary** creature you
    # control" reduced to exactly the payload of "a creature you control" and the
    # testable-keys check downstream saw a clean, unnarrowed filter — a trigger
    # firing on every creature its controller has. Reading the dataclass rather
    # than a hand-listed tuple also refuses a restriction added to
    # ``ObjectFilter`` after this was written.
    if _restrictions_beyond(filt, _PAYLOAD_HONOURED_FILTER_FIELDS):
        return None
    try:
        return _filter_payload(filt)
    except LoweringError:
        return None


__all__ = [
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "behavioural_payload",
    "CompiledLine", "GRAMMAR_CATEGORIES", "GrammarError", "LoweringError",
    "ast", "compile_line", "parse_line", "subject_filter_payload",
]
