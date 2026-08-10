"""Which text-keyed registry, if any, implements a whole oracle line.

Some printed lines carry no ``OracleInstruction`` at all. Their behaviour lives
in a sidecar registry that matches on the card's *raw oracle text*: the untap
step's restriction table (CR 502), the cast-timing gate, the cost-tax table
(CR 601.2f), the draw-step bonus table (CR 504), and the CR 614 replacement
interceptors. Nothing the grammar could lower would run them — the registry
already does, from the card's text, on every relevant event.

Before this module those lines failed the grammar with "unrecognized effect
verb" or "expected a subject", which is a misleading backlog entry: the engine
implements them, just not through an instruction. :class:`ast.RegistryLine`
records them as accounted-for instead.

**Every claim here delegates to the implementing code itself.** A table of
phrases copied into the grammar would be free to drift out of sync with the
registry, and a drifted copy would claim a line nothing implements — precisely
the silent-wrongness the full-consumption invariant exists to remove. So each
predicate below calls the registry's own matcher, and each must account for the
**whole** line: a registry that recognizes only part of a sentence does not get
to claim the rest of it.

Adding an entry is therefore not a parser decision. It requires naming the code
that runs the line; if that code is deleted or generalized into a real
instruction, the entry goes with it.
"""

from __future__ import annotations

from ..auras import aura_continuous_claim
from ..cast_restrictions import CAST_RESTRICTIONS
from ..cost_modifiers import cost_modifier_claims_line
from ..draw_step_modifiers import draw_step_bonus_for
from ..enter_effects import enter_effect_line
from ..replacements import (
    DAMAGE_LIFE_FLOOR_TEXT,
    LIFE_GAIN_TO_DRAW_TEXT,
    TOP_OF_LIBRARY_DISCARD_TEXT,
)
from ..targeting import enchant_line_subject
from ..untap_restrictions import self_untap_line, untap_restriction_for


def _normalized(line: str) -> str:
    """The line as the text-keyed registries see it: lowercased, no full stop.

    Every registry below applies this same reduction internally before matching
    (``untap_restriction_for`` and ``draw_step_bonus_for`` do it per line;
    ``check_cast_timing`` receives ``card.oracle_text.lower()``), so comparing
    against it is comparing against what the engine really tests.
    """
    return line.strip().lower().rstrip(".")


# CR 614 replacement interceptors, engine/replacements.py. Each entry is
# (phrase the interceptor self-selects on, trailing clause that same interceptor
# also implements). The tail is spelled out in full rather than being an
# open-ended "and whatever follows" — it is the one place a claim here could
# otherwise swallow text nothing implements.
_REPLACEMENT_LINES: tuple[tuple[str, str], ...] = (
    # _draw_instead_of_life_gain (Lich): the phrase is the whole line.
    (LIFE_GAIN_TO_DRAW_TEXT, ""),
    # _floor_life_at_one (Ali from Cairo): the phrase is the whole line.
    (DAMAGE_LIFE_FLOOR_TEXT, ""),
    # _top_of_library_instead_of_graveyard (Library of Leng). The constant the
    # interceptor probes for stops at "...on top of your library instead"; the
    # ReplacementChoice it raises offers exactly the two destinations the tail
    # names ("top of library", "graveyard"), so the interceptor implements the
    # tail as well.
    (TOP_OF_LIBRARY_DISCARD_TEXT, " of into your graveyard"),
)


def registry_for_line(line: str) -> str | None:
    """The registry implementing *line* in full, or ``None``.

    The return value is the registry's module name, used only to label the AST
    node — dispatch never reads it, because there is nothing to dispatch.
    """
    normalized = _normalized(line)

    # engine/cast_restrictions.py — "Cast this spell only during …" (CR 601.3e),
    # looped by check_cast_timing() from mixins/stack/casting.cast_from_hand.
    # That consumer matches by substring against the card's whole text; the
    # equality here is deliberately stricter, so a line that is a timing
    # restriction *plus something else* stays unaccounted for.
    if any(restriction.phrase == normalized for restriction in CAST_RESTRICTIONS):
        return "cast_restrictions"

    # engine/untap_restrictions.py — CR 502 "don't untap" templates (Stasis,
    # Winter Orb, Smoke, Meekstone, Magnetic Mountain), read by
    # phases/untap_step.py. Its patterns are ^…$ anchored and applied per line,
    # so a match already covers the line end to end.
    if untap_restriction_for(line) is not None:
        return "untap_restrictions"

    # engine/untap_restrictions.py — the per-source half of CR 502: "This
    # artifact doesn't untap during your untap step." and "You may choose not to
    # untap this creature during your untap step.", enforced by
    # phases/untap_step.py's per-permanent text scan. `self_untap_line` is the
    # whole-line form of that scan and is built from the same two phrase
    # constants the scan tests, so the claim cannot outlive the enforcement.
    if self_untap_line(line) is not None:
        return "untap_restrictions"

    # engine/targeting.py + engine/mixins/stack/casting.py — an Aura's
    # "Enchant <subject>" attachment restriction (CR 702.5). It is not an effect
    # at all: `aura_enchant_noun` reads it to decide which permanents the Aura
    # may legally be cast onto, and `derive_cast_target` reads it to tell the UI
    # what to offer. There is no instruction to store, and there never will be
    # while attachment stays a cast-time question rather than a resolution one.
    #
    # Deliberately narrower than `aura_enchant_noun`, which treats an unknown
    # noun as "any permanent is legal". A wording outside the five subjects
    # targeting.py knows is not really implemented — it is defaulted — so it
    # stays unclaimed and visible in the backlog.
    if enchant_line_subject(line) is not None:
        return "auras"

    # engine/auras.py — an Aura's *continuous* effect lines: the P/T grant
    # (layer 7c), the keyword grants (layer 6), the protection cycle, the combat
    # and untap restrictions, the control and type changes. Since phase 6 these
    # are derived from the attached Aura's own text on every recompute, so there
    # is no instruction to lower and emitting one would apply the effect twice.
    #
    # This is not a phase-6 gap, which is what the backlog said: the layers
    # carry these already. `aura_continuous_claim` is narrower than
    # `aura_effect_claim` on purpose — it stops before the Aura's triggered and
    # activated abilities, which do compile to instructions and which a claim
    # here would silently shadow.
    if aura_continuous_claim(line) is not None:
        return "auras"

    # engine/draw_step_modifiers.py — CR 504 symmetric bonus draw (Howling
    # Mine), read by phases/draw_step.py. Also ^…$ anchored per line.
    if draw_step_bonus_for(line) is not None:
        return "draw_step_modifiers"

    # engine/cost_modifiers.py — CR 601.2f cost taxes (Gloom), applied by
    # spell_cost_tax / ability_cost_tax. The helper is the whole-line form of
    # the scan those two use.
    if cost_modifier_claims_line(line):
        return "cost_modifiers"

    if any(normalized == phrase + tail for phrase, tail in _REPLACEMENT_LINES):
        return "replacements"

    # engine/enter_effects.py — CR 614.1c entry state ("This artifact enters
    # tapped.", "As this artifact enters, choose an opponent.", the
    # copy-on-enter lines) and the standing permissions stamped alongside them,
    # applied by mixins/permanent_state._initialize_permanent_state from the
    # permanent's own text as it arrives. There is no instruction to store: the
    # permanent is already on the battlefield in the state the line describes by
    # the time anything could resolve one.
    #
    # `enter_effect_line` is deliberately narrower than that mixin's substring
    # probes — it requires the phrase to be the whole line, give or take a
    # self-referential subject and a tail the mixin also performs — so a line
    # that is an entry effect *plus* something else stays unclaimed. Vesuvan
    # Doppelganger is the case that matters: its copy clause fires, but the
    # granted upkeep ability trailing it does not live here.
    if enter_effect_line(line) is not None:
        return "enter_effects"

    return None


__all__ = ["registry_for_line"]
