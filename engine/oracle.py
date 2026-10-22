"""Oracle-text compiler.

Turns a card's oracle text into an OracleProgram: a set of instructions,
activated abilities, triggered abilities, and static lines the game engine
can execute. This module owns the per-card compile cache
(:func:`compile_card_oracle`, :func:`_compile_card_oracle`), the gates every
card passes on its way to a program, the multi-face entry points and the
lexer. The readers it calls each have a module of their own — they were this
one's until the 2,000-line cap:

* ``engine/line_rewrites.py`` — every rewrite applied before a line is
  classified (``expand_ability_lines``);
* ``engine/line_classification.py`` — the line loops, one per card type, the
  planeswalker program included;
* ``engine/ability_lines.py`` — one line read as a triggered, activated or
  modal ability, and the delayed trigger a line creates;
* ``engine/trigger_conditions.py`` and ``engine/whenever_triggers.py`` — the
  trigger-condition pattern tables and the reader that matches them;
* ``engine/activation_costs.py`` and ``engine/chargeable_costs.py`` — an
  activated ability's cost, and the charger's reading of a prose cost;
* ``engine/keyword_lines.py`` — the keyword-line classifier;
* ``engine/static_line_support.py`` and ``engine/derived_static_claims.py``
  — support derived from the text-keyed rule tables, creature and
  noncreature;
* ``engine/line_normalization.py`` and ``engine/self_reference.py`` — the
  normalized line every table matches, and a card's name collapsed out of it.

Reading an effect clause is delegated, and ``engine/front_ends.py``'s
``_line_instruction`` is where the two front ends meet, most general first:

1. ``engine/grammar/`` — a real parser over Magic's templating. Whatever it
   claims, it claims for every card printed the same way.
2. ``engine/card_hooks.py``'s ``CARD_LINE_INSTRUCTIONS`` — one printed line of
   one card, for sentences no second card could share. A production for those
   would be a whole-card substring match wearing a grammar hat.

Precedence follows from that ordering: a line the grammar learns to read stops
reaching its card hook, which is what makes a superseded hook dead rather than
wrong.

There is no third. ``engine/parsing/``'s ``@parse_rule`` registry — a flat table
of substring predicates, hand-ordered against one another, which claimed a
clause on a prefix and dropped whatever followed — is deleted. A line no front
end reads now produces no instruction, which is the loud failure the invariant
asks for: the card is reported unsupported and names the clause.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .models import CardDefinition
from .faces import CAST_FACE_LAYOUTS, face_cards, is_multi_face
from .oracle_types import (ActivatedAbilityCost, ModalOption,
                           OracleInstruction, OracleProgram, OracleToken,
                           ParsedActivatedAbility, ParsedTriggeredAbility,
                           TriggerCondition, _COLOR_WORD_TO_SYMBOL,
                           compilation_cache)
from .auras import unclaimed_aura_lines
from .cycling import unread_cycling_line
from .flashback import (FLASHBACK_CLAIM, flashback_x_unannounced,
                        unread_flashback_line)
from .fading import unread_fading_line
from .equipment import expand_equip_lines, has_equip_ability, is_equip_line
from .alternative_costs import (unread_alternative_cost_sentence,
                                unread_granted_alternative_cost_sentence)
from .cast_costs import (unchosen_number_definition,
                         unenforced_x_spend_restriction,
                         unlinked_kicker_question, unread_cost_sentence)
from .combat_restrictions import combat_restriction_for
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .madness import unread_madness_line
from .line_normalization import (_PARENTHETICAL_RE, _normalize_text,
                                 normalize_creature_line)
from .self_reference import _restriction_line
from .keyword_lines import UNSUPPORTED_KEYWORDS, _is_supported_keyword_line
from .front_ends import _grammar_static_coeffects
from .ability_lines import _modal_at_least, _modal_chooser, _modal_options
from .derived_static_claims import (SUPPORTED_SPELL_PATTERNS,
                                    _derived_static_claims)
from .line_rewrites import expand_ability_lines
from .line_classification import (_noncreature_line_instructions,
                                  _parse_creature_program,
                                  _parse_noncreature_abilities,
                                  _parse_noncreature_triggered,
                                  _parse_planeswalker_program,
                                  _unread_land_text)

# Re-exported: names that moved out at the 2,000-line split and are still
# pulled from ``engine.oracle``. Three are ``__all__``'s; the rest are pulled
# by modules other groups were splitting in the same round (``auras``,
# ``cast_costs``, ``enter_effects``, ``prevention``,
# ``activation_restrictions``, ``events``, ``mixins/permanent_state``), whose
# import lines were left alone. New code
# imports a name from the module that defines it.
from .trigger_conditions import trigger_condition_of_line
from .chargeable_costs import (_chargeable_discard_filters,
                               chargeable_exile_payload,
                               chargeable_sacrifice_payload,
                               cost_object_is_chargeable)
from .activation_costs import parse_activated_ability_cost
from .self_reference import _collapse_self_references
from .ability_lines import (_bullets_after, _modal_trigger_ability,
                            _parse_activated_ability, _parse_triggered_ability)
from .line_rewrites import expand_card_lines
from .line_classification import compile_emblem_text


__all__ = [
    "ActivatedAbilityCost",
    "ModalOption",
    "OracleInstruction",
    "OracleProgram",
    "OracleToken",
    "ParsedActivatedAbility",
    "ParsedTriggeredAbility",
    "TriggerCondition",
    "compile_card_oracle",
    "lex_oracle_text",
    "normalize_creature_line",
    "parse_activated_ability_cost",
    "chargeable_sacrifice_payload",
    "trigger_condition_of_line",
]


# Substrings that veto a card before any line is read. Empty, and kept empty
# deliberately: a blanket refusal on a *phrase* is the pre-grammar shape — it
# reports the whole card unsupported without naming a clause, and it goes on
# doing so after the clause is implemented. "exchange control" sat here until
# CR 701.12b's production arrived, at which point Gauntlets of Chaos compiled
# cleanly and was still refused by this line. A line the grammar cannot read
# already refuses itself, naming what it could not read; that is the refusal
# this table is not needed for.
UNSUPPORTED_PATTERNS: tuple[str, ...] = ()


class OracleLexer:
    _TOKEN_RE = re.compile(r"\{[^}]+\}|[A-Za-z']+|\d+|\n|[:.,;+/\-]")

    def tokenize(self, oracle_text: str) -> tuple[OracleToken, ...]:
        if not oracle_text:
            return ()

        tokens: list[OracleToken] = []
        for raw in self._TOKEN_RE.findall(oracle_text):
            if raw == "\n":
                tokens.append(OracleToken("newline", raw))
                continue
            if raw.startswith("{") and raw.endswith("}"):
                tokens.append(OracleToken("mana", raw.upper()))
                continue
            if raw.isdigit():
                tokens.append(OracleToken("number", raw))
                continue
            if raw == ":":
                tokens.append(OracleToken("colon", raw))
                continue
            if raw in {".", ",", ";", "+", "/", "-"}:
                tokens.append(OracleToken("symbol", raw))
                continue
            tokens.append(OracleToken("word", raw.lower()))
        return tuple(tokens)


_LEXER = OracleLexer()


def lex_oracle_text(oracle_text: str) -> tuple[OracleToken, ...]:
    return _LEXER.tokenize(oracle_text)


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------

def _printed_line_for(expanded_line: str | None, printed_text: str) -> str:
    """The printed line *expanded_line* was rewritten from, or the line itself.

    An ability's ``source_line`` is the text the compiler read, which for an
    equip keyword is the CR 702.6a expansion rather than "Equip {1}". The
    Equipment gate asks which of a card's abilities *is* its equip ability, and
    the honest way to answer is to walk the printed lines through the same
    rewrite and compare — not to pattern-match the expansion's English.
    """
    if expanded_line is None:
        return ""
    wanted = expanded_line.strip()
    for line in (printed_text or "").split("\n"):
        if (expand_equip_lines(line) or "").strip() == wanted:
            return line
    return expanded_line


# Layouts the compiler can read straight from the top-level characteristics.
# Every other layout (flip, transform, modal_dfc, adventure, meld, …) leaves
# mana_cost and oracle_text empty and puts the real text in card_faces, so
# compiling one as-is would classify it a supported vanilla — a silently wrong
# answer rather than an error. Those stay explicitly unsupported.
#
# **Split cards are the first multi-face layout admitted** (CR 709), and not by
# teaching `_compile_card_oracle` about faces: `engine/faces.py` derives each
# half as a normal-layout card of its own, that card is what compiles (and what
# the stack holds, CR 709.3b), and `compile_card_oracle` answers for the whole
# card by asking of its halves. `faces.CAST_FACE_LAYOUTS` is the one list of
# layouts read that way, so admitting the next one is an entry there plus the
# cast path's say-so — never an edit to the single-face set below.
SINGLE_FACE_LAYOUTS = frozenset({
    "normal", "leveler", "class", "saga", "case", "planar", "scheme", "vanguard", "token",
})
SUPPORTED_LAYOUTS = SINGLE_FACE_LAYOUTS | CAST_FACE_LAYOUTS


def _effect_handler_kinds() -> frozenset[str]:
    """Instruction kinds with a registered handler.

    Imported lazily and cached: ``engine.handlers`` imports the compiler, so a
    module-level import here would be a cycle.
    """
    global _EFFECT_HANDLER_KINDS
    if _EFFECT_HANDLER_KINDS is None:
        from .handlers import EFFECT_HANDLERS

        _EFFECT_HANDLER_KINDS = frozenset(EFFECT_HANDLERS)
    return _EFFECT_HANDLER_KINDS


_EFFECT_HANDLER_KINDS: frozenset[str] | None = None


#: The ``derived_static_rule`` claims that are **not** evidence a permanent does
#: anything. Each says *when* something may be done with the card, so it is a
#: clause of an ability or of a cast rather than something the permanent does —
#: and when no line of the card is readable, a rule about when is a rule about
#: nothing.
#:
#: * ``activation_restrictions`` — "Activate only during your upkeep."
#:   Amulet of Quoz was reported supported on exactly that evidence, with the
#:   whole of its card in one unreadable ability.
#: * ``cast_timing`` — "You may cast this spell as though it had flash. If you
#:   cast it any time a sorcery couldn't have been cast, …" Necromancy is the
#:   Amulet of Quoz of this row: two printed lines, the first of them this
#:   permission and the second an enters trigger the compiler refuses in full.
#:   Credited as behaviour it read **supported** while reanimating nothing —
#:   the debt Mirage's promotion rehearsal found on eleven cards, arriving from
#:   the gate rather than from a whitelist word.
#: * ``flashback`` — "You may cast this card from your graveyard by paying
#:   {4}{R} rather than paying its mana cost" (CR 702.34a). *From where* and
#:   *for what* rather than when, and the same kind of clause: it is about how
#:   the card may be cast and says nothing about what the spell does. A
#:   flashback sorcery whose effect line nothing reads must stay unsupported
#:   however well it can be cast twice.
_TIMING_ONLY_CLAIMS: frozenset[str] = frozenset({
    "activation_restrictions", "cast_timing", FLASHBACK_CLAIM,
})


def _carries_no_behaviour(instruction: OracleInstruction) -> bool:
    """Whether this card-level instruction is evidence the permanent does
    *nothing* on its own.

    ``spell_pattern`` is the whitelist marker the gate above was written for: it
    records that a substring matched and carries no behaviour at all.

    A ``derived_static_rule`` normally is behaviour — Howling Mine's draw-step
    modifier, Winter Orb's untap restriction, Gloom's cost tax — and thirty
    shipped cards have nothing else. The exceptions are
    :data:`_TIMING_ONLY_CLAIMS`, which says why each is one.
    """
    if instruction.kind == "spell_pattern":
        return True
    return (
        instruction.kind == "derived_static_rule"
        and instruction.value in _TIMING_ONLY_CLAIMS
    )


# Unbounded cache: card definitions are immutable and the pool is finite, so
# every distinct card compiles exactly once per process — even with thousands
# of cards the programs are tiny compared to recompilation cost.
@compilation_cache
@lru_cache(maxsize=None)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
    layout: str = "normal",
    legendary: bool = False,
) -> OracleProgram:
    # Pyramids-style "{cost}: Choose one —" + bullets become one activated
    # ability per bullet, and an equip keyword line becomes the activated
    # ability CR 702.6a defines it as, before any other classification runs.
    # `printed_text` is kept for the one question that is about the card as
    # printed — does it carry an equip line at all (the Equipment gate below).
    printed_text = oracle_text
    oracle_text = expand_ability_lines(
        oracle_text, card_name=name, legendary=legendary
    )
    normalized_text = _normalize_text(oracle_text)

    # The single-face set, not `SUPPORTED_LAYOUTS`: this function reads one
    # text box, and a multi-face card's own is empty. A split card reaches the
    # compiler through `compile_card_oracle`, which hands each half here as the
    # normal-layout card `engine/faces.py` derives — so a multi-face layout
    # arriving *here* was handed in whole, and reading its empty text as a
    # supported vanilla is exactly the silently wrong answer the gate is for.
    if layout not in SINGLE_FACE_LAYOUTS:
        return OracleProgram(
            False, "unsupported", f"unsupported card layout: {layout}", normalized_text
        )

    if any(keyword in keywords for keyword in UNSUPPORTED_KEYWORDS):
        return OracleProgram(False, "unsupported", "unsupported keyword", normalized_text)

    # A printed **cost** neither cost table can charge (CR 601.2b, CR 118.9).
    #
    # Ahead of every classification below, and of every card type, because this
    # is the one defect the rest of this function cannot express. A card is
    # supported when *any* of its lines is, so a spell whose effect line
    # compiles reports supported however many of its other lines were dropped —
    # and a dropped **cost** is not a missing feature, it is a card that
    # resolves for a price it does not print. Kaervek's Spite sacrificed no
    # permanent, Infernal Harvest returned no Swamp, and Fireblast's alternative
    # was simply unavailable; all three read supported, all three read zero
    # hollow lines, and only ``scripts/parse_coverage.py`` could see them,
    # because the card is not refused. That is the population a refusal census
    # cannot reach.
    #
    # Each table answers for its own sentence — the same preambles it matches
    # with, not a third reading of the words — so a clause taught to either one
    # closes this gate for the card in the same edit. There is no whitelist
    # here to fall behind.
    for raw_line in (oracle_text or "").splitlines():
        unread_cost = (
            unread_cost_sentence(raw_line)
            or unread_alternative_cost_sentence(raw_line)
            # …and the granted half (Dream Halls), for the same reason one
            # scope wider: a sentence this table half-reads would be a
            # permanent offering a price nothing collects.
            or unread_granted_alternative_cost_sentence(raw_line)
        )
        if unread_cost is not None:
            return OracleProgram(
                False,
                "unsupported",
                f"printed cost nothing charges: {unread_cost}",
                normalized_text,
            )

    # "…if it was kicked **with its {5} kicker**" on a card whose kicker line
    # offers no {5} (CR 702.33f: the ability is linked to one of the kicker
    # costs *listed on the card*). The sentence parses and lowers -- its key is
    # simply one no payment is ever recorded under -- so the card would report
    # supported with an ability that can never trigger: the uncharged cost's
    # twin, a question nothing can answer yes. Asked of the printed text,
    # because the rewrite above has already turned the kicker line into a
    # sentence that no longer says "kicker".
    unlinked = unlinked_kicker_question(printed_text)
    if unlinked is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"asks about a kicker cost this card does not print: {unlinked}",
            normalized_text,
        )

    # "Spend only colored mana on X. No more than one mana of each color may be
    # spent this way." printed over an X this engine does not charge that way.
    # The sentence is enforced on an optional {X} offer (Emblazoned Golem's
    # "Kicker {X}") and claimed by the cost table for every card type, so on a
    # card whose X lives anywhere else it would be claimed and dropped -- the
    # uncharged cost's twin again, a restriction nothing applies. Asked of the
    # printed text, which the reader expands for itself.
    unenforced = unenforced_x_spend_restriction(printed_text, name, legendary)
    if unenforced is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"restricts an X nothing charges that way: {unenforced}",
            normalized_text,
        )

    # "…, where X is the chosen number" on a card no cast of which chooses one
    # (Liquid Fire prints the cost that does: "As an additional cost to cast
    # this spell, choose a number between 0 and 5"). The words lower to the
    # cast's own X, so without the cost the line compiles and spends an X
    # nobody announced -- the uncharged cost's mirror, a number nothing
    # chooses. A permanent is refused outright: its abilities' X is not its
    # spell's.
    unchosen = unchosen_number_definition(
        printed_text, name, legendary,
        spell=primary_type in {"instant", "sorcery"},
    )
    if unchosen is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"defines X as a number nothing chooses: {unchosen}",
            normalized_text,
        )

    # A **cycling** keyword line the CR 702.29a rewrite could not read
    # (``engine/cycling.py``). Beside the uncharged-cost gate above and for its
    # reason: CR 702.29e's typecycling searches a library rather than drawing, so
    # a card printing one must not be read as though it printed the draw — and
    # for an instant or a sorcery, whose *other* line compiles happily, nothing
    # below this point would refuse it. That is the shape the fourteen already-
    # "supported" cycling cards in Urza's Saga had before the rewrite existed:
    # supported, zero hollow lines, and a whole keyword missing.
    #
    # Asked of the expanded text, so a line the rewrite consumed is already gone
    # and only a variant it declined can reach here.
    unread_cycling = unread_cycling_line(oracle_text)
    if unread_cycling is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"unimplemented cycling ability: {unread_cycling}",
            normalized_text,
        )
    # …and a **fading** line the CR 702.32a rewrite could not read
    # (``engine/fading.py``), for the same reason: an artifact or enchantment
    # whose other line compiles would otherwise report supported with the
    # keyword dropped — a permanent that never fades and is never sacrificed.
    # Rejuvenation Chamber and Saproling Burst were exactly that before the
    # rewrite existed.
    unread_fading = unread_fading_line(oracle_text)
    if unread_fading is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"unimplemented fading ability: {unread_fading}",
            normalized_text,
        )
    # …and a **flashback** line the CR 702.34a rewrite could not read
    # (``engine/flashback.py``) — a cost with an {X} in it, or a clause the
    # alternative-cost reader cannot charge. The case this gate exists for is
    # the one the keyword was in before the rewrite: an instant or sorcery
    # whose *other* line compiles reports supported with the keyword dropped,
    # and 27 of Odyssey's 28 flashback cards did exactly that.
    unread_flashback = unread_flashback_line(oracle_text)
    if unread_flashback is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"unimplemented flashback cost: {unread_flashback}",
            normalized_text,
        )
    # …and a **madness** line `engine/madness.py` cannot read (an {X} or a
    # hybrid cost), for flashback's reason one keyword over: the six madness
    # instants Torment arrived with were supported off their effect line with
    # the keyword dropped, castable from a hand and never for their madness
    # cost.
    unread_madness = unread_madness_line(oracle_text)
    if unread_madness is not None:
        return OracleProgram(
            False,
            "unsupported",
            f"unimplemented madness cost: {unread_madness}",
            normalized_text,
        )

    if any(pattern in normalized_text for pattern in UNSUPPORTED_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text)

    if primary_type == "land":
        # Mana production is driven by CardDefinition.produced_mana, not by
        # parsing oracle text (basic lands' whole ability line is reminder
        # text in parens, e.g. "({T}: Add {W}.)", which normalize_creature_line
        # strips to nothing). A land is therefore at least playable whatever
        # its text does — unlike creatures/artifacts, an unparsed *bonus*
        # ability degrades just that ability, never the land's own castability.
        # Non-reminder-text ability lines (Desert's damage ping, Bazaar of
        # Baghdad's draw-discard, …) are parsed the same way artifacts' are, so
        # lands with abilities beyond mana become activatable too.
        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)

        # **The distinction the paragraph above draws, actually drawn.** The
        # rule is about a *bonus* ability, and for a long time the code did not
        # separate one from a land whose unreadable line is the whole card:
        # every land was passed. Antiquities is where that stopped being
        # theoretical. Urza's Mine, Power Plant and Tower each print one line,
        # that line is the entire card, none of them parsed — and all three
        # reported supported, tapped for the flat {C} that `produced_mana`
        # records, and could never assemble. Mishra's Workshop is the one that
        # hides best: nothing about it looks broken, it just taps for one {C}
        # where the card prints three and spends it on anything.
        #
        # So a land that prints abilities and can read *none* of them is
        # unsupported, naming the clause — the same property the artifact and
        # enchantment gate below asks, for the same reason. A land with some
        # readable ability keeps its support and is degraded by whatever it
        # could not read, which is the documented rule and is what the coverage
        # instruments are for (Mishra's Factory taps and pumps; only its
        # animation is unread).
        #
        # A land with no printed ability at all — a basic, a dual, anything
        # whose whole text is CR 305.6 reminder text — has nothing to fail on
        # and is passed by the `abilities` check, not by an exception to it.
        abilities = (*activated_abilities, *triggered_abilities)
        if abilities and not any(
            ability.supported and ability.instruction is not None
            for ability in abilities
        ):
            return OracleProgram(
                False,
                "unsupported",
                f"no ability of this land is implemented: {abilities[0].source_line}",
                normalized_text,
            )

        # **A land can be hollow without printing an ability**, which the
        # `abilities` check above cannot see. Legends' five "…creatures you
        # control have \"bands with other …\"" lands and The Tabernacle at
        # Pendrell Vale print a *static* line: no activated ability, no
        # triggered ability, and nothing claimed it — so all six reported
        # supported, tapped for mana, and did nothing else. The comment above
        # says a land with no printed ability "has nothing to fail on", and
        # that is true only of reminder text; a static grant is text the engine
        # either implements or does not.
        #
        # Parenthetical spans are dropped first, because CR 305.6 reminder text
        # is exactly what a basic and a dual print and is not an ability.
        #
        # Asked of **every** land, not only of one with no parsed ability. The
        # guard used to be `not any((activated_abilities, triggered_abilities))`,
        # which exempted a land the moment any one of its lines became an
        # ability — so an unread static beside a working ability was invisible.
        # Halls of Mist is the card that showed it: its cumulative upkeep was
        # the unread line the old guard caught, and implementing that keyword
        # turned the land supported with "Creatures that attacked during their
        # controller's last turn can't attack" still unimplemented and now
        # unreported. The abilities are passed in instead, so their own lines
        # are skipped as read — which is the question the guard was standing in
        # for. Two ICE lands are what this newly names; no shipped card moved.
        unread = _unread_land_text(
            oracle_text, name, (*activated_abilities, *triggered_abilities)
        )
        if unread is not None:
            return OracleProgram(
                False,
                "unsupported",
                f"no static ability of this land is implemented: {unread}",
                normalized_text,
            )

        # **Passing the gate is not doing the thing.** The check above says a
        # reader claims the land's static line; this is the line being carried,
        # as the same ``lord_buff`` instruction a creature's anthem compiles to
        # (`_parse_creature_program` step 4). Without it Legends' five banding
        # lands would go back to exactly the state round 24 caught — reported
        # supported, tapping for mana, granting nothing — with the difference
        # that the gate would now agree with them.
        #
        # Only the derivations a *land* can print are read here, one table at a
        # time, rather than the whole creature chain: a land has no P/T for a
        # static bonus to change.
        #
        # It *can* restrict combat, which is what Glacial Chasm showed —
        # "Creatures you control can't attack." The comment here used to say a
        # land had no combat to restrict, and the gate above already asked
        # `combat_restriction_for` through `_is_supported_static_creature_line`,
        # so a land printing one would have been admitted with the restriction
        # nowhere: `declare_attackers_step.can_attack` scans every permanent's
        # compiled *instructions*, and this loop is the only place a land's
        # static line becomes one.
        land_statics: list[OracleInstruction] = []
        land_static_lines: list[str] = []
        for raw_line in (oracle_text or "").splitlines():
            line = _PARENTHETICAL_RE.sub("", raw_line).strip()
            if not line or ":" in line:
                continue
            normalized = normalize_creature_line(line)
            lord = lord_buff_for(normalized)
            if lord is not None:
                land_statics.append(
                    OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(lord))
                )
                land_static_lines.append(normalized)
                continue
            restriction = combat_restriction_for(
                _restriction_line(line, name), name
            )
            if restriction is not None:
                # Every kind the one sentence names — see the creature path.
                for kind in (restriction.kind, *restriction.also_kinds):
                    land_statics.append(
                        OracleInstruction(kind, "", dict(restriction.payload))
                    )
                land_static_lines.append(normalized)

        return OracleProgram(
            True, "land_mana", "basic land support", normalized_text,
            instructions=tuple(land_statics),
            activated_abilities=activated_abilities,
            triggered_abilities=triggered_abilities,
            static_lines=tuple(land_static_lines),
        )

    if primary_type == "creature":
        supported, effect_kind, reason, instructions, activated, triggered, static_lines = _parse_creature_program(oracle_text, name)
        return OracleProgram(supported, effect_kind, reason, normalized_text, instructions, activated, triggered, static_lines)

    if primary_type == "planeswalker":
        return _parse_planeswalker_program(oracle_text, name)

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not normalized_text:
            return OracleProgram(True, "permanent_vanilla", "no oracle text", normalized_text)

        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)

        # Line by line — the only way it is assembled now. The legacy path that
        # stood alongside it collapsed the card's whole text to one string and
        # kept only the first rule that matched, so a second sentence ("Draw a
        # card. Each player discards a card.") was silently dropped and an
        # artifact whose activated ability the grammar reads in full still had
        # its card-level instruction produced by re-reading the card end to end.
        instructions: list[OracleInstruction] = _noncreature_line_instructions(
            oracle_text,
            name,
            activated_abilities,
            triggered_abilities,
            whole_card=primary_type in {"artifact", "enchantment"},
        )
        # "Choose one —" modal spells: parse each bullet as a selectable mode so
        # the game can resolve the player's chosen mode rather than always the
        # first. Built from the original text to keep human-readable labels.
        modes = _modal_options(oracle_text, name)

        # All-of, like the planeswalker gate and for the same reason: the UI
        # offers the whole mode list, so a card with one dead mode is offered
        # a choice it then declines to perform (the Read the Tides finding,
        # round 17 — "a modal spell needs every mode implemented or the card
        # is lying about the ones it isn't").
        dead_mode = next((m for m in modes if m.instruction is None), None)
        if dead_mode is not None:
            return OracleProgram(
                False,
                "unsupported",
                f"modal mode not implemented: {dead_mode.label!r}",
                normalized_text,
            )
        # "An opponent chooses one —" with a mode that **targets** used to be
        # refused here: CR 601.2c announces targets after CR 601.2b picks the
        # mode, and with the mode in somebody else's hands (CR 700.2e) the
        # caster could not name one while casting. There is an announcement
        # shape for it now — `mixins/stack/casting.arm_modal_mode_targets`
        # asks the caster for the mode's targets the moment the chooser
        # answers, inside the same uninterruptible window (CR 601.2i) — so the
        # gate is gone rather than widened.
        #
        # It was also blind in the direction that mattered: it read
        # ``"targets" in payload`` at the top level, and Fatal Lore's mode is a
        # ``sequence`` whose *step* targets. So it never fired on the one card
        # in the pool it was written for.
        chooser = _modal_chooser(oracle_text)

        if not instructions and modes and modes[0].instruction is not None:
            # A modal spell's card-level instruction is its *first* mode's — the
            # bullets are alternatives, so there is no other honest candidate,
            # and the stack executes this list when nothing chose a mode.
            #
            # The whole-text fallback that stood beside this is deleted with the
            # rule registry, and its removal is the last of the silent
            # partial-reads: it collapsed the card to one string, where "counter
            # target red spell. destroy target red permanent" reads as a spell
            # that does both, and where a sentence *no line* produced an
            # instruction for could still hand the card one borrowed from
            # somewhere else in its text. Four cards carried such an instruction
            # (Fastbond, Island Sanctuary, Jihad, Lich) and nothing dispatched
            # any of them.
            instructions.append(modes[0].instruction)

        # Static continuous co-effects (e.g. Conversion's "All Mountains are
        # Plains.") that follow a primary clause already claimed above and that
        # no line above claimed for itself, derived line by line by
        # engine/grammar/derived.py.
        for coeffect in _grammar_static_coeffects(oracle_text, name):
            if coeffect.kind not in {i.kind for i in instructions}:
                instructions.append(coeffect)

        # An Aura used to be classified supported by the single whitelist
        # substring "enchant creature", with nothing ever looking past the
        # enchant clause — so an Aura whose effect the engine does not
        # implement, or one with no effect line at all, entered play and did
        # nothing while reporting support. Every effect line must be claimed
        # (engine/auras.py) or the card is unsupported, with the offending line
        # named.
        aura_lines = [normalize_creature_line(line) for line in oracle_text.split("\n")]
        if any(line.startswith("enchant ") for line in aura_lines):
            unclaimed = unclaimed_aura_lines(aura_lines, name)
            if unclaimed:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"unimplemented aura effect: {unclaimed[0]}",
                    normalized_text,
                )

        # An Equipment (CR 301.5) is gated the same way, and had been gated by
        # nothing: Short Sword was supported on the substring "gets +" below,
        # its "Equipped creature gets +1/+1" never asked of engine/auras.py and
        # its equip line never compiled to anything — so it entered play and
        # could not be attached. Now the equip line has been rewritten into its
        # CR 702.6a activated ability above, and two things are required of
        # the card: that ability must have compiled to an instruction the engine
        # runs, and every *other* effect line must be claimed by the same
        # attached-effect reader an Aura's are (CR 301.5f makes "equipped
        # creature" the same reference as "enchanted creature", and the layer
        # bridge derives both off the attachment). By shape — the printed equip
        # line — because the compiler is not handed the type line, and CR 702.6a
        # makes equip an ability of Equipment cards.
        if has_equip_ability(printed_text):
            equip_abilities = [
                ability for ability in activated_abilities
                if is_equip_line(_printed_line_for(ability.source_line, printed_text))
            ]
            dead = next(
                (a for a in equip_abilities if not a.supported or a.instruction is None),
                None,
            )
            if dead is not None or not equip_abilities:
                offending = (
                    dead.source_line if dead is not None
                    else next(line for line in printed_text.split("\n") if is_equip_line(line))
                )
                return OracleProgram(
                    False,
                    "unsupported",
                    f"equip ability not implemented: {offending}",
                    normalized_text,
                )
            unclaimed = unclaimed_aura_lines(aura_lines, name)
            if unclaimed:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"unimplemented equipment effect: {unclaimed[0]}",
                    normalized_text,
                )

        instructions.extend(
            OracleInstruction("derived_static_rule", claim)
            for claim in _derived_static_claims(oracle_text, normalized_text, name)
        )

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

        # Only mark as unsupported if all triggered abilities are unsupported
        # and no spell-pattern instructions were already matched (e.g. Howling Mine).
        if triggered_abilities and all(not t.supported for t in triggered_abilities) and not instructions:
            return OracleProgram(False, "unsupported", "unsupported triggered ability", normalized_text)

        # A one-shot spell that resolves through no handler does nothing when
        # cast. `spell_pattern` is a marker recording that a whitelist substring
        # matched; it carries no behaviour, so a spell whose every instruction
        # is one is supported on the strength of a string comparison. Shahrazad
        # shipped that way, and ingesting Revised produced two more
        # (Shatterstorm, Crumble) on first contact.
        #
        # tests/engine/test_no_hollow_support.py asserted this as a property of
        # the pool; making it the compiler's own contract is what stops the next
        # set introducing another. Permanents are excluded for the same reason
        # that guard excludes them: they legitimately work through statics,
        # auras, layers and the text-keyed step tables.
        if (
            primary_type in ("instant", "sorcery")
            and instructions
            and not modes
            and not any(instruction.kind in _effect_handler_kinds() for instruction in instructions)
            and not any(a.supported for a in activated_abilities)
            and not triggered_abilities
        ):
            return OracleProgram(
                False,
                "unsupported",
                "no handler implements this spell's effect",
                normalized_text,
            )

        # The permanent half of the same contract, and the reason the exclusion
        # above is narrower than it reads. A permanent legitimately works
        # through statics, layers and the text-keyed step tables — but each of
        # those leaves a real instruction behind (``static_line``,
        # ``derived_static_rule``, an effect kind), never a bare
        # ``spell_pattern``. So a permanent whose *every* card-level instruction
        # is a whitelist marker does nothing on its own, and if every ability
        # line it prints also failed to parse it does nothing at all: Mazemind
        # Tome reported supported with both activated abilities carrying
        # ``instruction=None``, so it entered play, offered two abilities and
        # performed neither.
        #
        # The second conjunct is what keeps a permanent whose text is handled
        # somewhere this cannot see. Auras are excluded outright for that
        # reason: engine/auras.py above is their gate and it is the stricter of
        # the two — it names the first unclaimed effect line, and it knows about
        # the Aura death trigger (Creature Bond) that mixins/effects.py carries
        # with no instruction of its own.
        unreadable = [
            ability
            for ability in (*activated_abilities, *triggered_abilities)
            if not ability.supported or ability.instruction is None
        ]
        # **A line that fails earlier leaves less behind, not more.** This used
        # to require an unreadable *ability*, which reads as "something failed"
        # and is really "something failed late enough to become an object".
        # Sanctum of Stone Fangs' whole text is one triggered line the parser
        # refuses outright, so no ability was ever built, the list was empty and
        # the gate did not fire: the card entered play, reported supported, and
        # did nothing at all. Fiery Emancipation and Teferi's Ageless Insight
        # are the same shape with a replacement effect. The condition is what is
        # *absent* now — nothing supported, nothing static, only markers — and
        # the line named is the first one printed when no ability exists to
        # point at.
        #
        # Auras are excluded by shape rather than by name, and for one reason:
        # they work through engine/auras.py, which this cannot see and which is
        # the stricter gate anyway (it names the first unclaimed effect line).
        # Equipment used to be excluded beside them — Short Sword's "+1/+1" is
        # the same derived grant and left no instruction here. It no longer
        # needs the exclusion: its equip line compiles to a real activated
        # ability (CR 702.6a, above), which is the "something supported" this
        # gate already looks for, and its effect lines are gated by the
        # Equipment branch above. Keeping "equip" here would have exempted an
        # Equipment whose equip ability *failed* to compile from the very check
        # that catches a permanent doing nothing.
        attachment = any(line.startswith("enchant ") for line in aura_lines)
        # ``and instructions`` used to stand here, and it was standing in for
        # "the card produced *something*, but nothing that carries behaviour".
        # A ``spell_pattern`` marker was what usually produced that something —
        # so when the substring whitelist shrank from 73 entries to 5, a
        # permanent that produced nothing at all stopped reaching this branch
        # and fell through to the generic "effect not in basic pattern set"
        # below, losing the clause name. That is the wrong direction: the whole
        # value of refusing is naming what could not be read. The condition is
        # now the honest one — nothing here carries behaviour, vacuously true
        # for the empty case — and a card with no readable line is named rather
        # than dismissed. Everything the branch already caught is unaffected.
        if (
            primary_type in ("artifact", "enchantment")
            and not attachment
            and all(_carries_no_behaviour(instruction) for instruction in instructions)
            and not modes
            and not any(
                ability.supported and ability.instruction is not None
                for ability in (*activated_abilities, *triggered_abilities)
            )
        ):
            offending = (
                unreadable[0].source_line
                if unreadable
                else next((line for line in oracle_text.split("\n") if line.strip()), "")
            )
            return OracleProgram(
                False,
                "unsupported",
                f"no ability of this permanent is implemented: {offending}",
                normalized_text,
            )

        # **Timing evidence alone is not support.** A card whose only
        # instruction says *when* it may be cast or activated
        # (:data:`_TIMING_ONLY_CLAIMS`) has nothing anyone could point at as the
        # card working — the branch above already refuses an artifact or
        # enchantment on exactly that reading, and this is the same rule at the
        # gate every other type reaches. Necromancy is the card that found it:
        # its casting permission is implemented and enforced, its whole second
        # line is not, and credited here it read supported while reanimating
        # nothing.
        if (
            any(not _carries_no_behaviour(i) for i in instructions)
            or any(a.supported for a in activated_abilities)
            or triggered_abilities
        ):
            return OracleProgram(
                True,
                "spell_pattern",
                "pattern-supported effect",
                normalized_text,
                tuple(instructions),
                activated_abilities,
                triggered_abilities,
                modes=modes,
                modes_at_least=_modal_at_least(oracle_text),
                mode_chooser=chooser,
            )

        return OracleProgram(False, "unsupported", "effect not in basic pattern set", normalized_text)

    return OracleProgram(False, "unsupported", "unknown card type", normalized_text)


#: The ``effect_kind`` a whole multi-face card reports. Its own word because
#: the whole card has no effect of its own — each face has one — and a census
#: bucketing it under either half's kind would count one card as that kind and
#: silently lose the other.
MULTI_FACE_EFFECT_KIND = "multi_face"


def face_programs(card: CardDefinition) -> tuple[tuple[CardDefinition, OracleProgram], ...]:
    """Each face of a multi-face *card* with its compiled program, in printed
    order; ``()`` for a single-face card.

    The one way to read "what does this card's text compile to" for a card
    whose text is on its faces. Every instrument that walks a card's lines —
    the coverage scripts, the behaviour signature, the program differential —
    asks this rather than the whole card's program, which has no instructions
    by construction (see :func:`compile_card_oracle`).
    """
    return tuple((face, compile_card_oracle(face)) for face in face_cards(card))


def compiled_faces(card: CardDefinition) -> tuple[tuple[CardDefinition, OracleProgram], ...]:
    """*card* as the list of (card, program) pairs an instrument should read:
    its faces for a multi-face card, and otherwise the card itself. Never
    empty, so a caller loops over it without asking which kind it holds."""
    return face_programs(card) or ((card, compile_card_oracle(card)),)


def compiled_units(cards) -> list[tuple[CardDefinition, OracleProgram]]:
    """A pool as the (card, program) pairs a census over **compiled text**
    reads: :func:`compiled_faces` of every card, flattened. The pool-level form
    of ``faces.compilation_units`` for the common loop that compiles each card
    it visits — ``for card, program in compiled_units(catalog)``."""
    return [pair for card in cards for pair in compiled_faces(card)]


def compile_card_oracle(card: CardDefinition) -> OracleProgram:
    if is_multi_face(card):
        # CR 709.3a: "Only the chosen half is evaluated to see if it can be
        # cast." The whole card is never a spell, so it has no instructions to
        # resolve — its verdict is its faces' verdicts, and it is supported
        # only when **every** face is (a card one half of which does nothing is
        # a card a player can be dealt and cannot fully play). The reason names
        # the face that failed, because "unsupported" on a two-spell card is
        # otherwise a question with two answers.
        programs = face_programs(card)
        text = " // ".join(program.normalized_text for _, program in programs)
        failed = [(face, program) for face, program in programs if not program.supported]
        if failed:
            reason = "; ".join(
                f"{face.name}: {program.reason}" for face, program in failed
            )
            return OracleProgram(False, "unsupported", reason, text)
        return OracleProgram(
            True, MULTI_FACE_EFFECT_KIND,
            f"{card.layout} card: every face supported", text,
        )
    program = _compile_card_oracle(
        card.name, card.primary_type, card.oracle_text, card.keywords, card.layout,
        card.is_legendary,
    )
    # A flashback cost with an {X} the card's mana cost does not print
    # (``flashback.flashback_x_unannounced``): the one support question about
    # the keyword that needs the mana cost, which the text compiler above is
    # never handed. Asked of a program that compiled, so the reason a card
    # fails is still its first one.
    if program.supported:
        unannounced = flashback_x_unannounced(card)
        if unannounced is not None:
            return OracleProgram(
                False, "unsupported",
                f"unimplemented flashback cost: {unannounced} "
                "(an X no announcement supplies)",
                program.normalized_text,
            )
    return program


def simple_card_keywords(card: CardDefinition) -> tuple[str, ...] | None:
    """The keyword abilities a card's printed text consists of entirely.

    A *simple* card either has no abilities at all — a vanilla creature, or a
    basic land whose only text is the reminder text of its intrinsic mana
    ability (CR 305.6) — or has nothing but keyword lines the engine
    implements, the same admission ``_is_supported_keyword_line`` gives a
    creature's keyword line (so protection's and hexproof's qualities are
    read as payload). Returns ``()`` for the first, the normalized keyword
    parts in printed order for the second, and ``None`` for a card with any
    other ability, or one the engine does not support.

    Read by the verification tracker (``web/verification_report.py``), which
    auto-passes a simple card: its behaviour is the engine's generic combat and
    keyword code plus the card's printed numbers, so a manual in-game check
    would exercise no ability-specific path. The decision is made from the
    printed text rather than from the compiled program's shape, because the
    text is what the claim is about — a program with no instructions is also
    what an entry-state line (``enter_effects.py``) or a replacement-only
    permanent compiles to, and neither of those is simple.
    """
    # A multi-face card is never simple, whatever its halves print. Its own
    # text box is empty and its own program has no abilities, so every test
    # below would pass it as "no abilities at all" — and the verification
    # tracker would auto-pass a card whose whole behaviour is a choice between
    # two spells (CR 709.3) that no generic path exercises.
    if is_multi_face(card):
        return None
    program = compile_card_oracle(card)
    if (
        not program.supported
        or program.activated_abilities
        or program.triggered_abilities
        or program.modes
    ):
        return None
    keywords: list[str] = []
    for line in card.oracle_text.splitlines():
        normalized = normalize_creature_line(line)
        if not normalized:
            continue
        if not _is_supported_keyword_line(line):
            return None
        keywords.extend(part.strip() for part in normalized.split(",") if part.strip())
    return tuple(keywords)
