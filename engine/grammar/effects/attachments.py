"""Parsing a relation between two permanents (CR 301.5, CR 701.3).

The mirror of ``lowering/attachments.py``, which split off ``board`` at the
1,000-line guard the round Takklemaggot's reattachment landed; this half
followed the next time the same module crossed it. Reusing the name is the
point — one template has one home per side, so "attach target Equipment you
control to target creature you control" is findable from the family it is in
on either side rather than from whichever module happened to be small that
week.

The line is the one the lowering side already drew: an attachment is a
*relation between two permanents*, and every production here reads a pair —
the object and the host it goes onto, or the seat that will pick that host and
the legality measured across the pair ("a creature that this card could
enchant", CR 303.4a). Everything left in ``board`` destroys, returns or
sacrifices one permanent at a time.

The two share no fragment with ``board``: both halves of an attachment go
through ``references.parse_recipient`` and ``references.parse_target_spec``,
one layer down, which is what makes this a family rather than a second half of
one.
"""

from __future__ import annotations

import dataclasses

from .. import ast
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_recipient, parse_target_spec
from ..stream import TokenStream


def _parse_attach(stream: TokenStream) -> ast.Statement:
    """``Attach <subject> to <host>`` (CR 701.3).

    The sentence CR 702.6a expands equip into — "Attach this permanent to
    target creature you control" — and its one generalisation, a chosen
    Equipment ("Attach target Equipment you control to target creature you
    control"). Both halves go through `parse_recipient`, so a narrowed host
    ("target legendary creature you control", CR 702.6c's "Equip [quality]")
    is read by the noun phrase every other production already uses rather than
    by anything here. The whole line must be consumed: a trailing clause this
    does not read is a refusal, never a silent partial attach.
    """
    stream.expect_word("attach")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to attach")
    if not stream.accept_word("to"):
        raise stream.error("expected 'to' after what is attached")
    host = parse_recipient(stream)
    if host is None:
        raise stream.error("expected what to attach to")
    return ast.Attach(subject, host)


#: The seats an "in excess of" head clause may count the larger side on. Held to
#: what ``lowering/attachments`` can turn into a scope the counter answers:
#: "that player" is the seat this sentence's own target clause named, and
#: nothing else in the pool prints the phrase. A reference this could not scope
#: would count the *whole* board, which is a strictly bigger number than the
#: card names.
_EXCESS_COUNT_SEATS = frozenset({"target_player", "target_opponent", "that_player"})


def parse_excess_choice_paragraph(stream: TokenStream) -> "ast.Statement | None":
    """``For each <noun> <player> controls in excess of the number you control,
    choose a <noun> that player controls, then the chosen permanents phase
    out.`` (Equipoise.)

    Two printed sentences and one process, read as one production because the
    second names nothing on its own: "the chosen permanents" is whatever the
    first chose, and a reader that took the sentences apart would have to admit
    those words everywhere and then find no record behind them. The same reason
    ``paragraphs`` reads Demonic Consultation's three sentences together.

    What it produces is two ordinary nodes, not one fused one: a plural
    :class:`ast.ChoosePermanent` whose count is the head clause, and an
    ordinary :class:`ast.PhaseOut` over the bound set. So the phase-out is the
    CR 702.26 the rest of the pool already goes through, and the choice is the
    prompt Raiding Party already arms.

    **The head clause is a count, not a loop.** "For each X, choose a Y" says
    how many Ys, and the sentence behind it speaks about all of them at once —
    lowered as a repetition it would arm one prompt per excess land and leave
    the plural back-reference naming one of them.

    Refuses without consuming for anything that is not this shape, so every
    other "For each …" keeps the reading it had. Every half is checked: the two
    nouns must match (a card counting lands and choosing creatures is a
    different card), the possessive must name the same seat the count did, and
    the trailing sentence must be present — a choose with nothing behind it
    would phase out nothing while reporting supported.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        counted = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if counted is None:
        stream.reset(mark)
        return None
    whose = parse_player_ref(stream)
    if whose is None or whose.kind not in _EXCESS_COUNT_SEATS:
        stream.reset(mark)
        return None
    if not (
        stream.accept_word("controls")
        and stream.accept_phrase("in", "excess", "of", "the", "number", "you", "control")
        and stream.accept_punct(",")
        and stream.accept_word("choose")
    ):
        stream.reset(mark)
        return None
    spec = parse_target_spec(stream)
    if (
        spec is None
        or spec.targeted
        or spec.quantifier != "a"
        or spec.count != 1
        or spec.filter.card_types != counted.card_types
    ):
        # The printed article is singular because the head clause is what says
        # how many. A different noun on the two halves is a card this reading
        # would count one set and choose from another.
        stream.reset(mark)
        return None
    if not (
        stream.accept_punct(",")
        and stream.accept_phrase("then", "the", "chosen", "permanents", "phase", "out")
    ):
        stream.reset(mark)
        return None
    # The sentence's own full stop is left where it is: the loop above reads it
    # as the boundary between this paragraph and whatever follows, and eating it
    # here made "Repeat this process for artifacts and creatures." unconsumed
    # text on the one card that prints both.
    # The excess itself, built out of the two halves the clause printed: what
    # that seat controls, less what you do. ``ast.Minus`` clamps at zero, which
    # is what "in excess of" means (CR 107.1b) — a player with fewer lands than
    # you exceeds you by nothing.
    excess = ast.Minus(
        ast.CountOf(dataclasses.replace(counted, controller=whose.kind)),
        ast.CountOf(dataclasses.replace(counted, controller="you")),
    )
    choose = ast.ChoosePermanent(
        ast.PlayerRef("you"),
        dataclasses.replace(spec, quantifier="up_to", count_amount=excess),
    )
    # "the chosen permanents" — the set the step in front of this one recorded,
    # which is the bound plural the tap family reads as "those creatures"; the
    # quantifier is the printed word, so a lowering written for one spelling
    # cannot silently answer the other.
    phase_out = ast.PhaseOut(ast.TargetSpec("chosen", ast.ObjectFilter()))
    return ast.Sequence((choose, phase_out))


def parse_player_chooses_permanent(
    stream: TokenStream, chooser: "ast.PlayerRef"
) -> "ast.ChoosePermanent | None":
    """``<player> chooses <noun phrase> [that this card could enchant].``
    ``<player> chooses up to <N> <noun phrase>.``

    "That creature's controller chooses a creature that this card could
    enchant." (Takklemaggot.) The subject has already been read, so this starts
    at the verb.

    Nothing is targeted: the sentence prints no "target" and the pick is made as
    the ability resolves (CR 601.2c/115.1b), which is exactly the shape
    ``engine/handlers/permanent_choices.py`` already performs — so this is a
    noun phrase and a seat, not a new mechanism.

    The relative clause is read **here** rather than taught to
    ``parse_object_filter``, the same rule ``_parse_that_object`` follows: it
    is a question about a *pair* of permanents (may this Aura enchant that
    creature?), and the shared filter matcher answers about one. Teaching it to
    the noun parser would hand the words to every line that prints them and
    then drop them.

    Returns None with the cursor untouched when the sentence is a different
    "chooses" — a card name, a colour, a mode — so those keep their own
    readings.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    spec = parse_target_spec(stream)
    if spec is None or spec.targeted:
        stream.reset(mark)
        return None
    if spec.quantifier == "up_to":
        # "that player **chooses up to two Plains**" (Raiding Party). The plural
        # of the same sentence, and the same node: how many may be picked is
        # already what ``TargetSpec.quantifier`` and ``count`` say, so a second
        # field here would be a number the spec beside it also carries.
        #
        # No relative clause is read for it, and none is tolerated: the tail
        # below is Takklemaggot's enchant legality, which is a question about a
        # *pair* of permanents and means nothing for a set. Anything else the
        # phrase printed is left in the stream and refuses the line, which is
        # full token consumption doing its job.
        return ast.ChoosePermanent(chooser, spec)
    if spec.quantifier != "a" or spec.count != 1:
        stream.reset(mark)
        return None
    host_for_source = False
    if stream.accept_phrase("that", "this", "card", "could", "enchant"):
        host_for_source = True
    elif stream.accept_phrase("that", "this", "aura", "could", "enchant"):
        host_for_source = True
    if not host_for_source:
        # Every other narrowing a "chooses" sentence could print is one this
        # production has no answer for, and a choice made from a wider set than
        # the card names is not the card. Refused rather than admitted with the
        # clause dropped.
        stream.reset(mark)
        return None
    # The choice is optional exactly when the sentences behind it print both
    # branches; the rider that reads "If they don't" is what says so, and it
    # sets the flag through `dataclasses.replace`.
    return ast.ChoosePermanent(chooser, spec, host_for_source=host_for_source)
