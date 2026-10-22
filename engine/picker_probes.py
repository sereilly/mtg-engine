"""Should casting this card raise a picker? Probes asked of the printed card.

``targeting.derive_cast_spec`` answers what a cast picks from the compiled
program. These answer from the other side, off the card's printed lines, so a
ratchet can hold the two to each other: every card whose line names a cast
target derives a prompt (:func:`line_names_a_cast_target`,
:func:`cast_picker_expected`), and no card derives a prompt its text never
asks for (:func:`card_names_a_chooser`).

One probe per question, each with two readers —
``tests/engine/test_targeting.py`` over the shipped pool and
``scripts/picker_sweep.py`` over a measured set during Phase 3 — so the
script's census and the ratchet cannot drift apart. Split out of
``engine/targeting.py`` at the 2,000-line cap; a caller
(``engine/stack_targets.py`` among them) imports a name from here.
"""

from __future__ import annotations

import re

from .enchant_targets import _REMINDER_TEXT, card_enchant_subject
from .cost_pickers import _cost_picker_spec


#: Every printed way a card hands its caster a choice as it is cast.
#:
#: Deliberately *looser* than the target-word probes above, because the two
#: directions ask opposite questions. "This card targets — does it derive a
#: prompt?" has to be sure the word means a cast target; "this card derives a
#: prompt — is there anything on it to choose?" hands the card back to its twin
#: on any choosing word at all. A card with none of these words that still
#: derives a picker is asking a question its own text never poses.
#:
#: "of your choice" is CR 608.2d's choice (Circle of Protection, Reverse
#: Damage), and "card in a graveyard" / "card from your graveyard" is a card
#: picked out of a zone (Animate Dead's CR 115.1b enchant line, Experimental
#: Overload's return) — neither is the word "target" and both are real prompts.
_CAST_CHOOSER = re.compile(
    r"\btargets?\b|\bof your choice\b|\bchoose\b|\bchosen\b"
    r"|card in a graveyard|card from your graveyard"
)


def card_names_a_chooser(card, program) -> bool:
    """Whether anything about *card* asks its caster to pick something.

    The evidence sources :func:`derive_cast_spec` consults, asked of the *card*
    rather than of the derivation, plus the printed words above. A card that
    answers False here has nothing for a cast picker to be about.

    One function with two readers, on purpose: the ratchet in
    ``tests/engine/test_targeting.py`` (no card derives a prompt its text never
    asks for) and ``scripts/picker_sweep.py`` (the same sweep runnable over a
    measured set during Phase 3). A private copy in either would let the
    script's census and the shipped-pool ratchet drift apart.
    """
    from engine.cast_costs import additional_costs
    from engine.enter_effects import copy_on_enter_type

    if _CAST_CHOOSER.search(_REMINDER_TEXT.sub("", card.oracle_text or "").lower()):
        return True
    if card_enchant_subject(card.oracle_text) is not None:
        return True                                     # CR 115.1b
    if copy_on_enter_type(program.normalized_text or "") is not None:
        return True                                     # CR 707.9a
    return any(
        _cost_picker_spec(cost) is not None for cost in additional_costs(card)
    )


# A cast line that picks a target as the spell resolves. Reminder text is
# stripped by callers first: protection's "(… can't be blocked, **targeted**,
# dealt damage …)" is describing what may not happen to the creature, not
# something the card chooses. Triggered-ability lines are excluded because
# their target is chosen when the trigger goes on the stack (CR 603.3d), not as
# the permanent is cast — Erhnam Djinn's upkeep forestwalk grant is not a
# cast-time prompt. The optional "until …," in front is a **delayed** triggered
# ability saying how long it is armed (CR 603.7a) before it says when it fires
# (Gaze of Pain). Deliberately a *prefix* and not a search: eight shipped cards
# print a trigger word mid-line after a real cast target (Berserk, Mana Drain,
# Reincarnation, the three Glyphs, Sacred Boon, Ray of Command), and every one
# of those lines opens with the cast effect that does the targeting.
_TRIGGER_PREFIX = re.compile(
    r"^\s*(?:until [^,]{1,40}, )?(when|whenever|at the beginning)\b"
)
_TARGET_WORD = re.compile(r"\btargets?\b")
#: The one delayed line that *is* a cast target: a stated window, then an
#: opener whose own subject is "target <noun>". The window is required — a bare
#: "whenever target creature …" on a spell is an activated ability's effect
#: (Acidic Dagger), which ``_cast_lines`` has already split away from its cost.
_DELAY_OPENER_CHOOSES_ITS_TARGET = re.compile(
    r"^\s*until [^,]{1,40}, (?:when|whenever) target\b", re.I
)

# Line shapes whose target is not a *cast* target, each excluded for the reason
# the trigger prefix above is. `legality._cast_lines` cannot drop them: it
# splits on the activated-ability cost syntax, which none of these has.
#
# * A **loyalty ability** ("+1:", "−3:") is activated (CR 606.3), so its target
#   is chosen when the ability goes on the stack — `derive_activation_spec`
#   answers for it.
# * A **modal bullet** is one alternative, and a mode derives its own spec;
#   the card as a whole names no single target ("Choose one" means exactly
#   that).
# * A **static cost tax** that says "spells your opponents cast that **target**
#   this creature cost more" (Pursued Whale) uses the word about somebody
#   else's spell.
# * A **static effect keyed on what another object targeted** — Bronze Horse's
#   "prevent all damage … by spells that target it", Wall of Shadows'
#   "abilities that can target only Walls".
_LOYALTY_PREFIX = re.compile(r"^\s*[+−-]?\s*[0-9x]+\s*:", re.I)
_MODAL_BULLET = re.compile(r"^\s*•")
_TAXES_TARGETING_SPELLS = re.compile(r"spells .*that target .*cost")
_OTHERS_TARGETING = re.compile(r"(?:spells|abilities)[^.]*? that (?:can )?target")

# A **shroud-shaped prohibition** — "can't be the target of Aura spells"
# (Bartel Runeaxe), "players and permanents can't be the targets of spells or
# activated abilities" (Peace Talks). The word is what somebody else's spell
# may *not* do, so it names no choice this card's caster makes; the plural is
# the same prohibition and used to read as a cast target.
#
# **Erased from the line, not a veto over it.** The other five exclusions above
# are shapes of a whole line, so vetoing the line loses nothing; a prohibition
# is one clause of a sentence that may also contain a real cast target
# ("Destroy target creature. It can't be the target of spells this turn."), and
# a veto would read such a line as naming nothing at all. Erasing runs to the
# end of the clause, which every printing in the pool ends at the sentence.
_CANT_BE_TARGETED = re.compile(r"can't be the targets? of[^.;]*")

# A **granted quoted ability** — All Slivers have "{2}, Sacrifice this
# permanent: Target player discards a card at random." (Mindwhip Sliver). The
# quotation marks are the card handing an ability to somebody else, and the
# target inside them is chosen when *that* ability is activated (CR 602.2b),
# never as this creature is cast. `legality._cast_lines` cannot drop the line:
# it splits on the activated-ability cost syntax, and this line opens with
# "All Slivers have", so the whole grant reads as a cast effect.
#
# Erased rather than vetoed, for `_CANT_BE_TARGETED`'s reason exactly: a
# printed sentence may grant a quoted ability *and* target something itself
# ("Target creature gains “{T}: ...” until end of turn"), and a veto
# would read such a line as naming nothing at all. The activation-side probe in
# ``tests/engine/test_activation_targeting.py`` has stripped quoted text since
# Liliana's emblem for the same reason, one level down; this is the half that
# was missing on the cast side.
#: Both the straight and the curly pair, because the ingested oracle text
#: prints the curly ones and a hand-written test fixture prints the straight.
_QUOTED_ABILITY = re.compile("[\"“][^\"”]*[\"”]")


# **Somebody else's announcement, described** — "While an opponent **is
# choosing targets** as part of casting a spell they control…, that player
# must choose at least one Flagbearer" (Standard Bearer). The word is about the
# targets an *opponent's* spell chooses, so the creature printing it raises no
# picker of its own: `picker_sweep.py` reported both Flagbearers as the Roots
# class the day they compiled. Erased, for `_CANT_BE_TARGETED`'s reason — the
# clause is one part of a sentence, and ends at its comma.
_OTHERS_CHOOSING_TARGETS = re.compile(r"(?:is|are) choosing targets[^,.;]*")


def line_names_a_cast_target(line: str) -> bool:
    """Whether *line* names a target the caster chooses as the spell is cast.

    One probe with two readers: the forward ratchet in
    ``tests/engine/test_targeting.py`` (every card that targets as it is cast
    derives its own prompt) and ``scripts/picker_sweep.py``, which asks the
    same question of a measured set during Phase 3. The exclusions above are
    each a way to make the ratchet pass by looking at less, so the test also
    asserts the size of the examined set.
    """
    if not _TARGET_WORD.search(line):
        return False
    if _DELAY_OPENER_CHOOSES_ITS_TARGET.match(line):
        # "Until end of turn, whenever **target creature** deals damage, you
        # gain that much life." (Spiritualize.) The trigger prefix below is
        # right about every delayed line whose target sits *behind* the
        # opener's comma — that one is chosen when the delayed ability fires —
        # and wrong about this one: the object the ability watches is named by
        # the opener itself, so it is chosen as the spell is cast (CR 601.2c)
        # and bound as the ability is created (CR 603.7c). Read first, because
        # the veto below would otherwise make the spell an object with no
        # target at all: nothing announced it, and CR 608.2b had nothing to
        # re-check.
        return True
    if (
        _TRIGGER_PREFIX.match(line)
        or _LOYALTY_PREFIX.match(line)
        or _MODAL_BULLET.match(line)
        or _TAXES_TARGETING_SPELLS.search(line)
        or _OTHERS_TARGETING.search(line)
    ):
        return False
    # Last, because these subtract rather than veto: whatever the prohibition
    # and the quoted grant do not cover still has to name a target for this to
    # be one.
    remaining = _QUOTED_ABILITY.sub("", _CANT_BE_TARGETED.sub("", line))
    remaining = _OTHERS_CHOOSING_TARGETS.sub("", remaining)
    return bool(_TARGET_WORD.search(remaining))


def cast_picker_expected(card, program) -> bool:
    """The forward question the picker sweep asks: should casting this card
    raise a picker?

    :func:`line_names_a_cast_target` over the cast-relevant lines, plus the
    three evidence sources that choose without the word "target" — an Aura's
    enchant subject (CR 115.1b: Roots, the card this instrument exists for,
    prints no "target" at all), a copy-on-enter phrase (CR 707.9a), and an
    additional cost with a picker. Strictly stronger than the forward ratchet's
    own composition, which reads only the printed lines — the enchant half is
    exactly what let Roots ship uncastable.
    """
    from engine.cast_costs import additional_costs
    from engine.enter_effects import copy_on_enter_type
    from engine.legality import _cast_lines

    if any(
        line_names_a_cast_target(_REMINDER_TEXT.sub("", line))
        for line in _cast_lines(card)
    ):
        return True
    if card_enchant_subject(card.oracle_text) is not None:
        return True                                     # CR 115.1b
    if copy_on_enter_type(program.normalized_text or "") is not None:
        return True                                     # CR 707.9a
    return any(
        _cost_picker_spec(cost) is not None for cost in additional_costs(card)
    )
