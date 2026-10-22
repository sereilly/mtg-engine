"""A card's lines classified into abilities, one loop per card type.

:func:`_parse_creature_program` walks a creature's lines in printed order —
modal trigger, keyword line, cast costs, special action, triggered, activated,
static — and refuses the card at the first line nothing reads, naming it. A
noncreature card's lines are read by three passes the compiler assembles
(:func:`_parse_noncreature_abilities`, :func:`_parse_noncreature_triggered`,
:func:`_noncreature_line_instructions`), and a land's static text nothing reads
is named by :func:`_unread_land_text`. A planeswalker (CR 306, CR 606) is an
all-of program of its own — loyalty abilities, the "any time you could cast
an instant" static, triggers and keywords (:func:`_parse_planeswalker_program`)
— and an emblem's quoted text compiles through the same trigger parser
(:func:`compile_emblem_text`, CR 114.4).

The gates around these loops — layout, uncharged costs, unread keyword
rewrites, the Aura and Equipment gates, the hollow-support contract — stay in
``engine/oracle.py``'s compiler, which calls them. Split out of it at the
2,000-line cap.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .oracle_types import (OracleInstruction, OracleProgram,
                           ParsedActivatedAbility, ParsedTriggeredAbility,
                           TriggerCondition, compilation_cache)
from .characteristic_defining import dynamic_pt_for
from .alternative_costs import alternative_cost_claims_line
from .cast_costs import cast_cost_claims_line
from .special_actions import special_action_line
from .combat_restrictions import combat_restriction_for
from .enter_effects import enter_effect_line
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .static_bonuses import static_bonus_for
from .line_normalization import _normalize_text, normalize_creature_line
from .self_reference import _collapse_self_references, _restriction_line
from .keyword_lines import _is_supported_keyword_line, keyword_line_triggers
from .activation_costs import parse_activated_ability_cost
from .front_ends import _line_instruction, _reading
from .ability_lines import (_modal_trigger_ability, _parse_activated_ability,
                            _parse_delayed_attack_trigger,
                            _parse_triggered_ability,
                            _split_trailing_delayed_trigger)
from .static_line_support import (_grammar_static_creature_instructions,
                                  _is_supported_static_creature_line)
from .derived_static_claims import (SUPPORTED_SPELL_PATTERNS,
                                    _derived_static_claims)


# ---------------------------------------------------------------------------
# Planeswalker program parser (CR 306, 606)
# ---------------------------------------------------------------------------

# A loyalty ability line: "+1: …", "−2: …", "0: …", "−X: …" (CR 606.2). The
# whole clause left of the colon is one loyalty symbol; anything wider is an
# ordinary activated-ability line and is read by _parse_activated_ability.
_LOYALTY_LINE_RE = re.compile(r"^\s*[+\-−]?\s*(?:\d+|[xX])\s*:")

# CR 306.5d relaxed by the card itself: "You may activate loyalty abilities of
# <name> on any player's turn any time you could cast an instant." (Teferi,
# Master of Time — a template several Teferi printings share). Stored as this
# canonical static line; the activation gate in mixins/stack/activation.py
# reads it back from OracleProgram.static_lines.
LOYALTY_ANY_TIME_STATIC = (
    "you may activate loyalty abilities of this planeswalker on any player's "
    "turn any time you could cast an instant"
)


def _planeswalker_static_line(line: str, card_name: str | None) -> str | None:
    """The canonical form of a recognized planeswalker static line, or None."""
    normalized = _collapse_self_references(
        normalize_creature_line(line), card_name, "this planeswalker"
    )
    if normalized == LOYALTY_ANY_TIME_STATIC:
        return normalized
    return None


@compilation_cache
@lru_cache(maxsize=None)
def compile_emblem_text(emblem_name: str, text: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities an emblem's quoted text carries (CR 114.4).

    Compiled through the same trigger parser every permanent's lines go
    through, once per distinct emblem text per process. A line the parser does
    not read comes back unsupported, which is what the walker's support gate
    checks before the card carrying the emblem may compile.
    """
    parsed: list[ParsedTriggeredAbility] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        trig = _parse_triggered_ability(line, emblem_name)
        if trig is None:
            return ()
        parsed.append(trig)
    return tuple(parsed)


def _emblem_texts(instruction: OracleInstruction) -> list[str]:
    """Every emblem text *instruction* creates, walking sequence steps."""
    if instruction.kind == "create_emblem":
        return [str(instruction.payload.get("text", ""))]
    if instruction.kind == "sequence":
        return [
            text
            for step in instruction.payload.get("steps", ())
            for text in _emblem_texts(step)
        ]
    return []


def _parse_loyalty_ability(line: str, card_name: str | None) -> ParsedActivatedAbility | None:
    """Parse one loyalty-ability line, or None when *line* is not one.

    The cost half is the loyalty symbol (read by parse_activated_ability_cost);
    the effect half goes to the same front ends every other clause does. The
    effect clause is what is handed over — the grammar has no production for a
    loyalty symbol, and the symbol is a cost, not part of the effect's text.
    """
    if not _LOYALTY_LINE_RE.match(line):
        return None
    cost = parse_activated_ability_cost(line)
    if not cost.is_loyalty:
        return None
    effect_clause = line.split(":", 1)[1].strip()

    # A "whenever … this turn" effect clause creates a delayed trigger on
    # resolution (CR 603.7) — read here rather than by the grammar, whose
    # trigger classification would compile it as an ability of the permanent
    # and execute the inner effect immediately.
    delayed = _parse_delayed_attack_trigger(effect_clause, card_name)
    if delayed is not None:
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=normalize_creature_line(effect_clause),
            supported=True,
            cost=cost,
            effect_kind="activated_delayed_trigger",
            instruction=delayed,
        )
    if normalize_creature_line(effect_clause).startswith("whenever "):
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=normalize_creature_line(effect_clause),
            supported=False,
            cost=cost,
            effect_kind="unsupported",
            instruction=None,
        )

    instruction, effect_kind = _reading(
        _line_instruction(effect_clause, card_name, activated=True)
    )
    # An emblem's quoted ability must itself compile (CR 114.3: the emblem has
    # only that ability, so an unreadable one is an emblem that does nothing).
    if instruction is not None:
        for text in _emblem_texts(instruction):
            emblem_name = f"{card_name} Emblem" if card_name else "Emblem"
            compiled = compile_emblem_text(emblem_name, text)
            if not compiled or not all(t.supported for t in compiled):
                return ParsedActivatedAbility(
                    source_line=line,
                    normalized_effect=normalize_creature_line(effect_clause),
                    supported=False,
                    cost=cost,
                    effect_kind="unsupported",
                    instruction=None,
                )
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=normalize_creature_line(effect_clause),
        supported=instruction is not None,
        cost=cost,
        effect_kind=effect_kind if instruction is not None else "unsupported",
        instruction=instruction,
    )


def _parse_planeswalker_program(
    oracle_text: str, card_name: str | None
) -> OracleProgram:
    """Compile a planeswalker's text (CR 306).

    The support gate is **all-of**: every loyalty line, static line and trigger
    line must be readable, or the card is unsupported naming the first clause
    that is not. A planeswalker with one dead ability would otherwise enter
    play offering three abilities and performing two — the Mazemind Tome shape,
    which the hollow-support contract exists to refuse.
    """
    normalized_text = _normalize_text(oracle_text)
    instructions: list[OracleInstruction] = []
    activated: list[ParsedActivatedAbility] = []
    triggered: list[ParsedTriggeredAbility] = []
    static_lines: list[str] = []

    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        ability = _parse_loyalty_ability(line, card_name)
        if ability is not None:
            if not ability.supported:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"planeswalker ability not implemented: {line!r}",
                    normalized_text,
                )
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        static = _planeswalker_static_line(line, card_name)
        if static is not None:
            instructions.append(OracleInstruction("static_line", static))
            static_lines.append(static)
            continue

        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            if not trig.supported:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"planeswalker ability not implemented: {line!r}",
                    normalized_text,
                )
            triggered.append(trig)
            if trig.instruction is not None:
                instructions.append(trig.instruction)
            continue

        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            continue

        return OracleProgram(
            False,
            "unsupported",
            f"planeswalker text too complex: {line!r}",
            normalized_text,
        )

    if not activated:
        # CR 306.5d: each planeswalker has loyalty abilities. Text with none
        # readable is text this parser did not actually understand.
        return OracleProgram(
            False, "unsupported", "no loyalty abilities found", normalized_text
        )

    return OracleProgram(
        True,
        "planeswalker_loyalty",
        "planeswalker support",
        normalized_text,
        tuple(instructions),
        tuple(activated),
        tuple(triggered),
        tuple(static_lines),
    )


# ---------------------------------------------------------------------------
# Creature program parser
# ---------------------------------------------------------------------------

def _parse_creature_program(
    oracle_text: str,
    card_name: str | None = None,
) -> tuple[bool, str, str, tuple[OracleInstruction, ...], tuple[ParsedActivatedAbility, ...], tuple[ParsedTriggeredAbility, ...], tuple[str, ...]]:
    text = oracle_text.strip()
    if not text:
        return True, "creature_simple", "simple creature support", (), (), (), ()

    instructions: list[OracleInstruction] = []
    activated: list[ParsedActivatedAbility] = []
    triggered: list[ParsedTriggeredAbility] = []
    static_lines: list[str] = []

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        index += 1
        line = raw_line.strip()
        if not line:
            continue

        # 0. Modal triggered ability — a head plus the bullet run below it,
        # consumed together so the bullets never reach the per-line steps
        # (where each would refuse as an orphaned fragment).
        modal_trigger = _modal_trigger_ability(lines, index - 1, card_name)
        if isinstance(modal_trigger, str):
            return False, "unsupported", modal_trigger, (), (), (), ()
        if modal_trigger is not None:
            trig, consumed = modal_trigger
            triggered.append(trig)
            instructions.append(trig.instruction)
            index += consumed
            continue

        # 1. Plain keyword line (e.g. "Flying, Trample")
        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            for trig in keyword_line_triggers(normalized):
                triggered.append(trig)
                instructions.append(trig.instruction)
            continue

        # 1b. An additional cost to cast this spell (CR 601.2b). Not an effect
        # and so not an instruction: it is collected and paid by
        # `queue_from_hand`, which reads the same table this asks. A creature
        # spell prints one as readily as an instant does (Goremand), and
        # without this step the line was the reason the whole card came back
        # "text too complex".
        if cast_cost_claims_line(line):
            continue

        # 1c. An **alternative** cost (CR 118.9) — "You may pay 1 life and exile
        # a blue card from your hand rather than pay this spell's mana cost."
        # The other half of the step above and read the same way, because it is
        # the same kind of sentence: a price, not an effect, collected by
        # `queue_from_hand` from the table this asks. Without this the line was
        # claimed by nothing at all, and Force of Will and Pyrokinesis reported
        # `supported` on their *other* line while the one they are famous for
        # did nothing — the population a refusal census cannot see, because the
        # card is not refused.
        if alternative_cost_claims_line(line):
            continue

        # 1d. A CR 116 **special action** — "You may discard this card any time
        # you could cast an instant" (Circling Vultures, the one card CR 116.2e
        # names). Not an effect and so not an instruction, for the reason the
        # two costs above are not: CR 116.1 says a special action does not use
        # the stack, so there is nothing to put on it and nothing to dispatch.
        # `engine/special_actions.py` performs it and this asks that table, so
        # what is claimed and what acts cannot drift.
        #
        # A creature is where the pool prints it, and the noncreature path
        # reaches the same table through `_derived_static_claims`.
        if special_action_line(line) is not None:
            continue

        # 2. Triggered ability
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            if trig.supported:
                triggered.append(trig)
                if trig.instruction is not None:
                    instructions.append(trig.instruction)
                continue
            # Trigger condition recognized but effect is unsupported.
            # Before giving up, check if the full line is listed as a supported
            # static pattern (e.g. "at the beginning of your upkeep, unless you
            # pay …" for Demonic Hordes, or "when this creature dies …" for
            # Personal Incarnation).
            if _is_supported_static_creature_line(line):
                normalized = normalize_creature_line(line)
                instructions.append(OracleInstruction("static_line", normalized))
                static_lines.append(normalized)
                continue
            triggered.append(trig)
            continue

        # 3. Activated ability
        ability = _parse_activated_ability(line, card_name)
        if ability is not None and ability.supported:
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # 4. Static text
        if _is_supported_static_creature_line(line, card_name):
            normalized = normalize_creature_line(line)
            grammar_static = _grammar_static_creature_instructions(line, card_name)
            if grammar_static:
                instructions.extend(grammar_static)
                static_lines.append(normalized)
                continue
            # Characteristic-defining P/T (CR 604.3). One instruction kind
            # carrying what to count: these were four branches matching literals
            # that embedded the card's own name, so a reprint or any
            # functionally identical card compiled as unsupported.
            if (dynamic_pt := dynamic_pt_for(normalized)) is not None:
                instructions.append(
                    OracleInstruction(dynamic_pt.kind, "", dynamic_pt.payload)
                )
            elif (bonus := static_bonus_for(_restriction_line(line, card_name))) is not None:
                instructions.append(OracleInstruction(bonus.kind, "", bonus.payload))
            elif (
                lord := lord_buff_for(normalized)
                or lord_buff_for(_restriction_line(line, card_name))
            ) is not None:
                # The lord line the gate just admitted, carried as data. The
                # consumer used to re-parse `static_line`'s text with two
                # regexes of its own, which is how the gate and the dispatch came
                # to disagree about what "other " meant.
                instructions.append(
                    OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(lord))
                )
            elif (
                restriction := combat_restriction_for(
                    _restriction_line(line, card_name), card_name
                )
            ) is not None:
                # Combat restrictions are templates, derived rather than listed
                # (engine/combat_restrictions.py). The chain that used to sit
                # here matched exact strings and hardcoded Island, so a card
                # naming any other land type fell through to `static_line` and
                # attacked freely while still reporting supported.
                #
                # One sentence may name several prohibitions over one noun
                # phrase (``CombatRestriction.also_kinds``); each gets its own
                # instruction over the same payload, because each is answered
                # at a different step. Emitting only the first is a card that
                # enforces one clause of its sentence and drops the rest.
                for kind in (restriction.kind, *restriction.also_kinds):
                    instructions.append(
                        OracleInstruction(kind, "", dict(restriction.payload))
                    )
            else:
                instructions.append(OracleInstruction("static_line", normalized))
            static_lines.append(normalized)
            continue

        # Name the offending line so support_report on a new set pinpoints
        # exactly which clause needs a parse rule.
        return False, "unsupported", f"creature text too complex: {line!r}", (), (), (), ()

    # **Every** trigger, not merely one of them. The gate used to ask whether
    # *any* trigger was supported, so a creature printing two of them shipped
    # as supported with the second one inert — Hazezon Tamar compiled its
    # enters-the-battlefield half, reported "simple creature support", and
    # exiled no Sand Warrior at all when it left, because nothing announced a
    # trigger whose effect had never lowered. No creature in the pool relies
    # on the looser reading; a trigger the engine cannot run is a card the
    # engine cannot play, however many others on it work.
    if any(not trig.supported for trig in triggered):
        return False, "unsupported", "unsupported triggered ability", (), (), tuple(triggered), tuple(static_lines)

    return (
        True,
        "creature_simple",
        "simple creature support",
        tuple(instructions),
        tuple(activated),
        tuple(triggered),
        tuple(static_lines),
    )



def _unread_land_text(
    oracle_text: str,
    card_name: str | None,
    abilities: tuple[Any, ...] = (),
) -> str | None:
    """A land's first printed line that nothing in the engine reads, or None.

    Reminder text (CR 305.6) is dropped first: a basic's whole "ability" is a
    parenthetical, and a dual's is too. What remains is rules text, and a land
    printing rules text no reader claims is a land that taps for mana and does
    nothing else while reporting supported.

    *abilities* are the land's parsed activated and triggered abilities, whose
    printed lines are read by definition and are skipped here. It used to be
    asked only of a land with **no** parsed ability, which is a different
    question and answered a weaker one: a land with an ability was exempt from
    the check entirely, so an unread *static* beside a working ability went
    unreported. Halls of Mist is what showed it — its cumulative upkeep was the
    unread line the old guard caught, and teaching the engine that keyword
    turned the card supported while "Creatures that attacked during their
    controller's last turn can't attack" stayed unimplemented and now invisible.
    A line is claimed or it is not; whether some *other* line on the card parsed
    is not part of that question.
    """
    ability_lines = {
        re.sub(r"\([^)]*\)", "", ability.source_line or "").strip()
        for ability in abilities
    }
    for raw in (oracle_text or "").splitlines():
        line = re.sub(r"\([^)]*\)", "", raw).strip()
        if not line or line in ability_lines:
            continue
        # A keyword line the CR defines *as* an ability (cumulative upkeep,
        # rampage) is claimed by the rewrite that turns it into one, and reaches
        # here only when the rewrite refused it — a cost this engine cannot
        # charge. Then it is genuinely unread and naming it is the point.
        if keyword_line_triggers(normalize_creature_line(line)):
            continue
        # …and a plain keyword line, which a land can print too: Teferi's Isle
        # has phasing (CR 702.26). The creature front end classifies these and
        # this one did not, so a land whose only extra text is a keyword the
        # engine implements was reported as carrying an unread static. Through
        # the same `IMPLEMENTED_KEYWORDS` reader the creature gate uses, so what
        # is admitted here and what is admitted there cannot drift.
        if _is_supported_keyword_line(line):
            continue
        # Through the same collapse every other static reader uses: a land that
        # names itself ("Tapped Land enters tapped") is saying "this permanent",
        # and a reader anchored on the self-reference sees nothing otherwise.
        # That mismatch between a gate and a runtime reader is the bug round 18
        # found on Bartel Runeaxe, and this is the same one line lower.
        collapsed = _restriction_line(line, card_name)
        if _is_supported_static_creature_line(line, card_name):
            continue
        # The **raw** line and the card's name, never the pre-collapsed one:
        # `enter_effect_line` runs `_self_normalized` itself, and handing it a
        # line whose self-references are already rewritten costs it the printed
        # text. Sheltered Valley is what showed the difference — "each other
        # permanent **named Sheltered Valley** you control" arrives here as
        # "named this creature", so the reader that claims the line and the
        # reader that carries it out were looking at two different cards, which
        # is the exact mismatch `_self_normalized`'s own docstring warns about.
        if enter_effect_line(line, card_name) is not None:
            continue
        if _derived_static_claims(collapsed, collapsed, card_name):
            continue
        if any(pattern in collapsed for pattern in SUPPORTED_SPELL_PATTERNS):
            continue
        return line
    return None


def _parse_noncreature_abilities(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedActivatedAbility, ...]:
    abilities: list[ParsedActivatedAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        ability = _parse_activated_ability(line, card_name)
        if ability is not None:
            abilities.append(ability)
    return tuple(abilities)


def _parse_noncreature_triggered(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedTriggeredAbility, ...]:
    """Extract triggered abilities from non-creature oracle text.

    A **modal** trigger is a head plus the bullet run below it, consumed
    together exactly as ``_parse_creature_program`` consumes one. Reading this
    side line by line was not a missing feature but a disagreement: the Aura
    support gate asks ``_modal_trigger_ability`` whether the whole run is
    carried out, and this loop then produced an *unsupported* trigger for the
    head alone with no instruction behind it — a card admitted by one front end
    and left inert by the other. Relic Bind is the card that showed it.
    """
    abilities: list[ParsedTriggeredAbility] = []
    lines = oracle_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        modal = _modal_trigger_ability(lines, index, card_name)
        if isinstance(modal, tuple):
            trig, consumed = modal
            abilities.append(trig)
            index += 1 + consumed
            continue
        if isinstance(modal, str):
            # A recognized modal head the engine cannot carry out. Recorded as
            # an unsupported ability rather than dropped, so the "every trigger
            # is unsupported" gate below sees the card the way the Aura gate
            # does instead of finding no trigger at all.
            abilities.append(ParsedTriggeredAbility(
                source_line=line,
                condition=TriggerCondition(kind="unsupported", trigger="when", raw_text=line),
                instruction=None,
                supported=False,
                effect_kind="unsupported",
            ))
            index += 1
            continue
        index += 1
        if not line:
            continue
        # A keyword line the CR defines *as* a triggered ability, read on this
        # side too — see `keyword_line_triggers` for why both loops ask.
        keyword_triggers = keyword_line_triggers(normalize_creature_line(line))
        if keyword_triggers:
            abilities.extend(keyword_triggers)
            continue
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            abilities.append(trig)
    return tuple(abilities)


def _by_source_line(abilities) -> dict[str, list]:
    """Parsed abilities grouped by the line they came from, in printed order.

    A list per line rather than one entry: a card may print the same line twice,
    and the assembly below consumes them in order so the second occurrence is
    not silently the first one again.
    """
    grouped: dict[str, list] = {}
    for ability in abilities:
        grouped.setdefault(ability.source_line, []).append(ability)
    return grouped


def _noncreature_line_instructions(
    oracle_text: str,
    card_name: str | None,
    activated: tuple[ParsedActivatedAbility, ...],
    triggered: tuple[ParsedTriggeredAbility, ...],
    *,
    whole_card: bool,
) -> list[OracleInstruction]:
    """The card-level instruction each line of a noncreature card contributes,
    in printed order.

    Assembled from the reading the compiler has *already* produced for that
    line. The legacy fallback this replaced collapsed the card's entire text to
    one string and kept the first rule that matched it, so an artifact whose
    activated ability the grammar reads in full still had its card-level
    instruction produced by re-reading the whole card — two front ends answering
    the same question about the same line, and only one of them per line. That
    whole-text pass is gone with the registry; a line nothing claims now
    contributes nothing, rather than borrowing a sentence from elsewhere on the
    card.

    Reusing the ability parse rather than re-running the grammar is what keeps
    the assembly per line, so a production claiming one line cannot delete the
    reading of any other.

    *whole_card* tells the list's two meanings apart. For an instant or sorcery
    it is the program that *resolves* — the stack runs every
    non-``spell_pattern`` instruction in it, in printed order, fused into one
    ``sequence`` by ``_select_executable_instruction`` — so only plain effect
    lines belong in it.
    For a permanent it is a mirror of everything the card does, scanned by kind
    by the layer bridge, the upkeep pass and the AI: the same mirror
    ``_parse_creature_program`` has always built for creatures, and which
    ``engine/ai_valuation.py``'s ``SPELL_TYPES`` gate already documents. A
    permanent's abilities keep their own entries in ``activated_abilities`` and
    ``triggered_abilities``; nothing resolves this list on its own.
    """
    acts = _by_source_line(activated) if whole_card else {}
    trigs = _by_source_line(triggered) if whole_card else {}

    instructions: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        # Modal bullets are alternatives collected into `modes`, not effects the
        # card performs. Letting one into the top-level list would make a
        # "Choose one" spell always resolve whichever bullet was claimed.
        if not line or line.startswith("•"):
            continue

        found = _line_instruction(line, card_name, spell_line_only=True)
        if found is not None:
            instructions.append(found[0])
            continue
        # "Whenever a creature blocks this turn, it gets +0/+1 until end of
        # turn." (Battle Cry.) A spell whose own line creates a delayed
        # triggered ability (CR 603.7) — the same clause Basri Ket's loyalty
        # ability and Subira's activated one print, and the same table, asked
        # here so the shape has one home. Read after the grammar and before the
        # ability lookup, which is where a spell's plain effect lines are read.
        #
        # Without it the sentence was claimed by nothing: the card was
        # `supported` on its *first* line and the second one silently did
        # nothing, which is what `parse_coverage.py` reports and what a
        # promotion gates on.
        delayed = _parse_delayed_attack_trigger(line, card_name)
        if delayed is not None:
            instructions.append(delayed)
            continue
        # "Mill four cards. **Whenever a creature attacks this turn**, …"
        # (Song of Blood.) The same clause printed as a line's *last* sentence
        # rather than as the whole of it — one resolution that does something
        # and then arranges for something later, so the two sentences fuse into
        # a `sequence` here instead of being split into two abilities.
        fused = _split_trailing_delayed_trigger(line, card_name)
        if fused is not None:
            instructions.append(fused)
            continue
        if not whole_card:
            continue

        # An ability line: take the instruction its own parse produced.
        ability = None
        for group in (trigs, acts):
            pending = group.get(line)
            if pending:
                ability = pending.pop(0)
                break
        if ability is not None:
            if ability.supported and ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # Neither — a static ability ("Black creatures get +1/+1."), or a
        # triggered one whose condition the trigger table refuses (Cursed Land).
        # Its instruction used to arrive from the whole-text parse or from
        # parse_static_coeffects re-reading the card; it comes from this line
        # or from nowhere.
        static = _line_instruction(line, card_name)
        if static is not None:
            instructions.append(static[0])
            continue
        # A combat restriction printed on a noncreature permanent ("Creatures
        # without flying can't attack.", Moat; Arboria's whole card). The same
        # table the creature path consults, asked through the same
        # name-substituting reader, and emitting the same instruction — so the
        # enforcement site's board scan in `can_attack` reads a Moat and an
        # Evil Eye identically, and the gate and the dispatch stay one table.
        restriction = combat_restriction_for(
            _restriction_line(line, card_name), card_name
        )
        if restriction is not None:
            # Every kind the one sentence names — see the creature path above.
            for kind in (restriction.kind, *restriction.also_kinds):
                instructions.append(
                    OracleInstruction(kind, "", dict(restriction.payload))
                )
    return instructions
