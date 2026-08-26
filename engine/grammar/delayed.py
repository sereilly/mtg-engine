"""Delayed triggered abilities (CR 603.7), and the opener that binds one.

Split from `statements` at the thousand-line guard, along the section boundary
that module already drew. A delayed trigger is not a statement like the others:
the rest of `statements` reads a sentence that *does* something now, while these
read one that arranges for something later, and the arrangement is what the
parse has to get right — which event, and what the later sentence is allowed to
refer back to.

`Choose target <noun>.` lives here for the same reason. It performs nothing on
its own and parses **only** when the sentence binding what it chose follows; a
spell whose one instruction chose a target and did nothing would otherwise
report itself supported.

**The recursion arrives as a parameter.** A delayed trigger contains a whole
statement, so this file needs `parse_statement`, which is the roof one layer up.
Taking it as an argument keeps the dependency running one way — the inversion
`lowering/where_x.py` and `postmodifiers.py` both make, for the same reason.
"""

from __future__ import annotations

from . import ast
from .effects.damage import _parse_bound_targeting_prevention
from .errors import GrammarError
from .nouns import parse_object_filter
from .phrases import _parse_duration, parse_bound_subject
from .references import parse_target_spec
from .stream import TokenStream

# ---------------------------------------------------------------------------
# Delayed triggered abilities (CR 603.7)
# ---------------------------------------------------------------------------

# Which printed opener names which delayed-trigger event, and what the two
# words CR 603.7 turns into fields say:
#
#   ``once``        CR 603.7b — "when" triggers once, "whenever" keeps
#                   triggering for as long as the ability lasts.
#   ``duration``    how long an ability that never triggers survives. "This
#                   turn" expires with the turn; an ability naming a future
#                   step waits for that step however many turns away it is.
#   ``binds``       whether the opener is about "**that** <noun>" — the object
#                   the creating spell targeted (CR 603.7c).
#
# A table rather than a production each, because the difference between these
# rows is four values and no structure at all. The event names are keys of
# ``engine/delayed_triggers.DELAYED_EVENTS``; one that is not is refused when
# the sentence is lowered, so a new row cannot arm an ability nothing announces.
_DELAYED_OPENERS: tuple[tuple[tuple[str, ...], str, bool, str, bool], ...] = (
    # "At the beginning of your next main phase, …" (Mana Drain). Either main
    # phase of the controller's — whichever one comes next.
    (("at", "the", "beginning", "of", "your", "next", "main", "phase"),
     "controllers_next_main_phase", True, "until_it_triggers", False),
    # "At this turn's next end of combat, …" (Glyph of Doom).
    (("at", "this", "turn", "'s", "next", "end", "of", "combat"),
     "next_end_of_combat", True, "end_of_turn", True),
)


def _delayed_bound_subject(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``that creature`` — the noun phrase naming the object an earlier
    sentence of the same spell chose, as a filter.

    :func:`phrases.parse_bound_subject` is the one reader of the phrase; this
    only asks for the singular half of it and hands back the filter. "Those
    creatures" is a *list* the delayed-trigger machinery has no shape for —
    one entry binds one permanent id — so it is refused rather than silently
    bound to whichever one the reader returned first.

    The phrase is read rather than skipped, and travels as the delayed
    ability's own subject filter, for the reason
    ``delayed_destroy_blocked_or_blocker`` states about "destroy that
    **Wall**": the id already names the object exactly, so the noun re-states
    rather than narrows — but a word consumed and never read is a word that
    could be deleted with no change to what the card does, and this engine
    does not leave one lying in a payload.
    """
    spec = parse_bound_subject(stream)
    if spec is None or spec.quantifier != "that":
        return None
    return spec.filter


def _parse_create_delayed_trigger(stream: TokenStream, parse_statement) -> "ast.CreateDelayedTrigger | None":
    """A sentence that **creates** a delayed triggered ability (CR 603.7).

    ``When that creature dies this turn, <effect>.`` (Reincarnation)
    ``Whenever that creature is dealt damage by <phrase> this turn, <effect>.``
      (Glyph of Life)
    ``At the beginning of your next main phase, <effect>.`` (Mana Drain)

    The whole sentence, delay included, for the reason
    ``_parse_delayed_self_action`` gives: the effect on its own is performed
    *now*, and a spell that gains the life immediately is a different card from
    one that gains it when a creature is next damaged.

    The inner effect is parsed by the ordinary sentence parser, so a delayed
    ability's effect is every effect this engine has, and one that fails to
    parse refuses the whole line rather than arming an ability that fires into
    nothing.
    """
    mark = stream.mark()
    event: str | None = None
    once = True
    duration = "end_of_turn"
    binds = False
    subject = None
    agent = None

    if stream.accept_word("when"):
        # "When that creature dies this turn, …"
        subject = _delayed_bound_subject(stream)
        if subject is not None and stream.accept_phrase("dies", "this", "turn"):
            event, binds = "bound_permanent_dies", True
    elif stream.accept_word("whenever"):
        # "Whenever that creature is dealt damage by an attacking creature this
        # turn, …" — "this turn" is CR 603.7b's stated duration, so this one
        # fires every time for as long as it lasts.
        subject = _delayed_bound_subject(stream)
        if subject is not None and stream.accept_phrase("is", "dealt", "damage", "by"):
            # The indefinite article is the noun parser's caller's business
            # everywhere in this grammar: `parse_object_filter` reads the
            # phrase from the noun onward.
            stream.accept_word("a", "an")
            try:
                agent = parse_object_filter(stream)
            except GrammarError:
                agent = None
            if agent is not None and stream.accept_phrase("this", "turn"):
                event, binds, once = "bound_permanent_dealt_damage", True, False
    else:
        for phrase, kind, kind_once, kind_duration, kind_binds in _DELAYED_OPENERS:
            if stream.accept_phrase(*phrase):
                event, once, duration, binds = kind, kind_once, kind_duration, kind_binds
                break

    if event is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        effect = parse_statement(stream, top_level=False)
    except GrammarError:
        stream.reset(mark)
        return None
    # The delay governs its whole sentence, so the effect has to run to the end
    # of one. Without this the production would accept a *prefix* — "destroy
    # all creatures" out of "destroy all creatures that were blocked by that
    # creature this turn" — and the words left over would either fail the line
    # somewhere that says nothing about what happened or, worse, parse as a
    # sentence of their own and be performed **now** rather than when the
    # ability fires. Declining instead leaves the refusal the line already had.
    if not stream.exhausted and not stream.at_punct(".", ";"):
        stream.reset(mark)
        return None
    return ast.CreateDelayedTrigger(
        event=event, effect=effect, once=once, duration=duration,
        binds_target=binds, subject=subject, agent=agent,
    )


def _parse_choose_target(stream: TokenStream, parse_statement) -> "ast.ChooseTarget | None":
    """``Choose target creature.`` — a sentence whose whole content is
    CR 601.2c's choosing of targets (Reincarnation, Glyph of Life).

    **It is only a sentence when the next one binds what it chose.** A spell
    whose only instruction chose a target and then did nothing would report
    itself supported while doing nothing at all, which is the failure this
    engine refuses loudly everywhere else. So the following sentence is parsed
    as a probe and the tokens handed straight back: if it is not a delayed
    triggered ability about "that <noun>", this production declines and the
    line fails on whatever it really says.
    """
    mark = stream.mark()
    if not stream.accept_phrase("choose", "target"):
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    after_filter = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    delayed = _parse_create_delayed_trigger(stream, parse_statement)
    binds = delayed is not None and delayed.binds_target
    if not binds:
        # …or a shield the following sentence hangs on what was chosen
        # (Silhouette). The probe asks the same question either way — does the
        # next sentence bind this choice — and a second binder is a second
        # answer to it, not a second production of this one.
        binds = _parse_bound_targeting_prevention(stream) is not None
    stream.reset(after_filter)
    if not binds:
        stream.reset(mark)
        return None
    return ast.ChooseTarget(ast.TargetSpec("target", filt, targeted=True))
