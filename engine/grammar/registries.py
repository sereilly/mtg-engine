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
from ..cast_restrictions import CAST_RESTRICTIONS, cast_condition_line
from ..cost_modifiers import cost_modifier_claims_line
from ..cost_x_definitions import cast_x_ceiling_line, cast_x_definition_line
from ..damage_source_colors import colorless_source_line
from ..draw_step_modifiers import draw_step_bonus_for, skips_own_draw_step
from ..enter_effects import enter_effect_line
from ..named_counters import CAP_CLAIM, counter_cap_line
from ..extra_triggers import extra_trigger_line
from ..land_play_allowance import land_play_line
from ..prevention import prevention_claims_line
from ..regeneration import denies_regeneration_line, self_regeneration_line
from ..replacements import replacement_claims_line
from ..revealed_hands import revealed_hands_line
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


def registry_for_line(line: str, card_name: str | None = None) -> str | None:
    """The registry implementing *line* in full, or ``None``.

    The return value is the registry's module name, used only to label the AST
    node — dispatch never reads it, because there is nothing to dispatch.
    *card_name* reaches the one matcher whose patterns are anchored on a
    self-reference a card may spell as its own name (``self_untap_line``).
    """
    normalized = _normalized(line)

    # engine/cast_restrictions.py — "Cast this spell only during …" (CR 601.3e),
    # looped by check_cast_timing() from mixins/stack/casting.cast_from_hand.
    # That consumer matches by substring against the card's whole text; the
    # equality here is deliberately stricter, so a line that is a timing
    # restriction *plus something else* stays unaccounted for.
    if any(restriction.phrase == normalized for restriction in CAST_RESTRICTIONS):
        return "cast_restrictions"

    # engine/cast_restrictions.py — the board half of CR 601.3: "Cast this
    # spell only if you control a snow land." (Blizzard.) A row whose noun
    # phrase is payload, so the claim asks the reader that answers it rather
    # than comparing against a literal the table would be free to drift from.
    if cast_condition_line(normalized) is not None:
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
    if self_untap_line(line, card_name) is not None:
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

    # engine/cost_x_definitions.py — "X is the number of artifact and/or
    # creature cards in an opponent's graveyard as you cast this spell."
    # (Spoils of War.) CR 107.3c: the card defines X, so there is no effect to
    # lower — the cast path computes the number before the caster is asked for
    # one. Claimed through the module that computes it, so a definition no row
    # implements leaves the card unsupported rather than admitted with the
    # caster free to announce any X they like.
    if cast_x_definition_line(line):
        return "cost_x_definitions"

    # engine/cost_x_definitions.py — "X can't be greater than the number of
    # snow lands you control." (Winter's Chill.) CR 601.2b's announcement still
    # belongs to the caster; this bounds it, so there is no effect to lower —
    # the cast path refuses an X above the board's number and the picker never
    # offers one. Claimed through the module that counts it, so a bound no row
    # can read leaves the card unsupported rather than admitted with the caster
    # free to announce past it.
    if cast_x_ceiling_line(line) is not None:
        return "cost_x_definitions"

    # engine/damage_source_colors.py — "Black and/or red permanents and spells
    # are colorless sources of damage." (Ghostly Flame.) CR 609.7b's recheck
    # reads the board at the moment a source's colour matters, so there is no
    # instruction to lower and one would be a layer-5 colour change instead —
    # a strictly different card, because the permanent stays black.
    if colorless_source_line(line) is not None:
        return "damage_source_colors"

    # engine/regeneration.py — "If this creature would be destroyed, regenerate
    # it." (Clergy of the Holy Nimbus.) CR 701.19b's static form: both
    # destruction paths derive it from the permanent's own text at the moment a
    # destruction would happen, so there is no instruction to lower and one
    # would apply the replacement a second time.
    if self_regeneration_line(line) or denies_regeneration_line(line):
        return "regeneration"

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
    # engine/draw_step_modifiers.py — CR 614.10's mandatory skip ("Skip your
    # draw step.", Necropotence), read by phases/draw_step.py off the
    # permanent's own text.
    if skips_own_draw_step(line):
        return "draw_step_modifiers"

    # engine/cost_modifiers.py — CR 601.2f cost taxes (Gloom), applied by
    # spell_cost_tax / ability_cost_tax. The helper is the whole-line form of
    # the scan those two use.
    if cost_modifier_claims_line(line):
        return "cost_modifiers"

    # engine/land_play_allowance.py — CR 305.2/505.5b extra land plays
    # (Fastbond), derived from the permanent's own text by the land-drop path in
    # mixins/turn_management and by the support gate. Both halves of the
    # template are claimed: the permission clause and the self-damage rider that
    # may accompany it, which `land_play_allowance_for` reads together into one
    # allowance. `land_play_line` is the per-line form of that derivation and is
    # anchored at both ends, so a sentence saying more than either half stays
    # unclaimed.
    #
    # The rider is a "whenever" trigger by wording and *not* one by
    # implementation: no trigger table matches it, and the damage is dealt by
    # the land-drop path itself. Claiming it here is what stops the compiler's
    # whole-text fallback inventing a bare `deal_damage` for the card — an
    # instruction on the permanent's mirror that nothing reading that mirror
    # ever dispatches.
    if land_play_line(line) is not None:
        return "land_play_allowance"

    # engine/extra_triggers.py — CR 603.2d "that ability triggers an additional
    # time" (Sanctum of All). Carried out where an ability is put onto the
    # stack, from the permanent's own text, so there is no instruction to
    # produce and the line would otherwise read as unclaimed.
    if extra_trigger_line(line):
        return "extra_triggers"

    # engine/revealed_hands.py — "Players play with their hands revealed."
    # (Revelation, CR 701.20a). The effect is who may *see* a hidden zone, so
    # the consumer is the web layer's per-seat serialization asking the
    # derived predicate — there is no instruction to lower, and the claim asks
    # the implementing module's own matcher. The library-top twin is
    # engine/library_top.py's, claimed the way Conspicuous Snoop's line
    # already is rather than here.
    if revealed_hands_line(line):
        return "revealed_hands"

    # engine/replacements.py — CR 614 interceptors. The phrase table lives there
    # rather than here, because the support gate reads it too: what the engine
    # implements and what it claims to have read cannot drift while both
    # readers ask the implementer.
    if replacement_claims_line(line):
        return "replacements"

    # engine/prevention.py — CR 615 shields. The same arrangement one layer
    # over: a permanent's *static* prevention applies from its own text at
    # damage time, so there is nothing to lower, and the matcher the
    # interceptor self-selects on is the matcher asked here.
    if prevention_claims_line(line):
        return "prevention"

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
    if enter_effect_line(line, card_name) is not None:
        return "enter_effects"

    # engine/named_counters.py — "Rasputin can't have more than seven dream
    # counters on it." A maximum on the store, enforced at the one write that
    # store has, so there is no instruction to lower and the claim asks the
    # implementing module's own matcher.
    if counter_cap_line(line, card_name) is not None:
        return CAP_CLAIM

    return None


__all__ = ["registry_for_line"]
