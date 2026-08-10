"""Grammar-based oracle-text front end.

A tokenizer plus a recursive-descent grammar over Magic's card templating,
producing a typed AST (``ast.py``) that is lowered to the existing
``OracleInstruction`` IR (``lower.py``). It is replacing the flat
``@parse_rule`` registry in ``engine/parsing/``, which needed roughly one
hand-written rule per two cards and silently dropped any part of a card's text
its first matching rule did not cover.

**Migration model — strangler fig.** The grammar runs on every line as soon as
this package is imported, but its output is only *used* when the categories it
lowered to are switched on in :data:`GRAMMAR_CATEGORIES`. Everything else falls
back to the legacy rules untouched. That means:

* new grammar work is exercised against the whole card pool from day one,
  because failures and disagreements are recorded even while unused;
* enabling a category is a one-line change made only after the differential
  guard (``tests/engine/test_grammar_differential.py``) is already green for it;
* the legacy rules for a category are deleted only once the ratchet shows every
  line they used to claim is executed through the grammar instead.

Progress is tracked in ``GRAMMAR_COVERAGE.md`` via ``scripts/grammar_coverage.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..oracle_types import OracleInstruction
from . import ast
from .errors import GrammarError, LoweringError
from .lower import GRAMMAR_ONLY_PAYLOAD_KEYS, categories_of, lower_ability
from .parser import parse_line

# Categories whose grammar output is authoritative. Everything else is parsed
# in shadow for the ratchet but executed by the legacy rules.
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
#   (nothing) — every category with a lowering is switched on. Effects the
#              grammar cannot yet lower (static abilities, multi-mana
#              player-chosen colour, most zone movement) refuse at lowering and
#              fall back, which the coverage report tracks as "parsed but not
#              lowered".
GRAMMAR_CATEGORIES: frozenset[str] = frozenset(
    {
        "damage", "pump", "life", "destruction", "tapping", "optional", "zones",
        "mana", "regeneration", "counterspells", "prevention", "recolor", "upkeep",
        "turns", "evasion", "tokens", "counters", "text_change", "control",
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
    """*payload* without the keys only the grammar emits.

    The grammar records what a line targets so the engine can answer targeting
    from the compiled program (engine/targeting.py). No handler reads those
    keys, so they cannot change behaviour — but every tool that compares a
    grammar instruction against a legacy one must drop them first, or a purely
    additive description reads as a divergence. Comparing on this subset is
    what keeps the grammar-vs-legacy differential and the parse-coverage
    deletion probe meaningful while two front ends coexist.
    """
    return {k: v for k, v in payload.items() if k not in GRAMMAR_ONLY_PAYLOAD_KEYS}


__all__ = [
    "GRAMMAR_ONLY_PAYLOAD_KEYS",
    "behavioural_payload",
    "CompiledLine", "GRAMMAR_CATEGORIES", "GrammarError", "LoweringError",
    "ast", "compile_line", "parse_line",
]
