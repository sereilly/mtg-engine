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
    ``naming`` reads Demonic Consultation's three sentences together.

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
    folded = False
    if whose is None:
        # "for each land **target player controls** in excess of …": the seat
        # clause is inside the noun phrase, because ``parse_object_filter``
        # reads "target player controls" as a controller narrowing — it has
        # always read "target **opponent** controls" that way, and the wider
        # noun arrived with Mogg Infestation. One printed phrase with two places
        # it can be consumed, so the seat is lifted back off the filter here and
        # both spellings build the same node. Left unread, this card's whole
        # ability went unsupported the day the noun parser learned the word.
        seat = counted.controller
        if seat not in _EXCESS_COUNT_SEATS:
            stream.reset(mark)
            return None
        whose = ast.PlayerRef(seat)
        counted = dataclasses.replace(counted, controller=None)
        folded = True
    if whose.kind not in _EXCESS_COUNT_SEATS:
        stream.reset(mark)
        return None
    if not (
        (folded or stream.accept_word("controls"))
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


def _at_clause_end(stream: TokenStream) -> bool:
    """Whether the cursor is at the end of a clause this production may stop on.

    The end of the line, the end of a sentence, or a conjunction the statement
    layer joins on — ``and``/``then``, bare or after the Oxford comma. Exactly
    the boundaries ``statements.parse_statement``'s joining loop consumes, so a
    production stopping here hands the rest of the line to the reader that can
    take it; anything else left in the stream refuses the line, which is full
    token consumption doing its job.
    """
    return (
        stream.exhausted
        or stream.at_punct(".", ";")
        or stream.at_word("and", "then")
        or (stream.at_punct(",") and stream.peek_word(1) in ("and", "then"))
    )


def parse_player_chooses_permanent(
    stream: TokenStream, chooser: "ast.PlayerRef"
) -> "ast.ChoosePermanent | None":
    """``<player> chooses <noun phrase> [that this card could enchant].``
    ``<player> chooses up to <N> <noun phrase>.``

    "That creature's controller chooses a creature that this card could
    enchant." (Takklemaggot.) The subject has already been read, so this starts
    at the verb.

    Nothing is targeted: the sentence prints no "target" and the pick is made as
    the ability resolves (CR 115.10a, CR 115.10), which is exactly the shape
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
    if spec is None:
        stream.reset(mark)
        return None
    if spec.targeted:
        # "An opponent chooses **target creature they control**." (Echo
        # Chamber.) The printed word is "target" and the seat that picks is not
        # the ability's controller, which CR 601.2c has no room for: a target is
        # announced as the ability is activated, from one seat.
        #
        # So it is read as the same resolution-time pick every other sentence
        # in this production is, and the deviation is the one
        # ``lowering/control_changes.py`` already records for Preacher — what it
        # costs is the 608.2b re-check and shroud on the chosen creature, and
        # what the alternative costs is a second seat inside the announcement
        # step. Preacher spells the same fact as "of an opponent's choice they
        # control"; this card spells it with the chooser as the sentence's
        # subject, and both arrive here as one node.
        #
        # The whole **clause** or nothing: a targeted phrase with anything
        # behind it that is not a clause boundary is a sentence this production
        # has no answer for, and it keeps whatever refusal it had.
        #
        # A conjunction is a boundary. "You choose target creature an opponent
        # controls, **and** that opponent chooses target creature." (Mogg
        # Assassin) is two chooser clauses in one sentence, and the joining loop
        # in ``statements.py`` reads the second one — but only if this
        # production stops at the comma instead of rewinding over the whole
        # line. Reading the rule as "ends the sentence" rather than "ends the
        # clause" is what made two seats' choices unparseable while either one
        # alone parsed.
        if (
            spec.quantifier != "target"
            or spec.count != 1
            or not _at_clause_end(stream)
        ):
            stream.reset(mark)
            return None
        return ast.ChoosePermanent(chooser, spec)
    if spec.quantifier == "any_number":
        # "Target opponent chooses **any number of** creatures they control."
        # (Oracle en-Vec.) The plural above with no printed ceiling — CR 601.2c
        # again, and the bound is the set itself rather than a number a picker
        # shows. Its own quantifier for ``parse_target_spec``'s stated reason
        # ("an 'up to' prints a maximum a picker shows and a re-check enforces,
        # and there is none here"), so it arrives as a different word and the
        # lowering must not silently read it as a ceiling of one.
        #
        # The same node and the same tail rule as "up to": no relative clause
        # is read and none is tolerated, so a phrase with anything behind it
        # refuses the line rather than dropping what it printed.
        return ast.ChoosePermanent(chooser, spec)
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
        # "Defending player **chooses an untapped creature they control**."
        # (Crashing Boars.) The bare sentence: the whole narrowing is the noun
        # phrase, which ``parse_target_spec`` has already read into the filter,
        # so there is nothing printed for this production to drop.
        #
        # Admitted only where the phrase **ends the sentence**, exactly as the
        # targeted branch above requires — that gate is what keeps every other
        # "chooses a …" wording out. "Chooses a card name, then reveals the top
        # card of their library" (Petra Sphinx) runs on into a comma and is
        # refused here, which is what leaves it to the production written for
        # it; and it is the whole reason this branch cannot simply accept
        # whatever the noun parser consumed.
        if (
            (stream.exhausted or stream.at_punct(".", ";"))
            # A **permanent**, which is what this node names and what the
            # handler picks from. "Target opponent chooses **a card in your
            # graveyard**" (Forgotten Lore) ends its sentence exactly the same
            # way and is not this: it opens a paragraph the repeated-pick
            # production reads whole, and claiming its first sentence here cost
            # that card its whole program. The zone gate is what separates them,
            # and it is the noun phrase's own answer rather than a second
            # reading of the words.
            and spec.filter.zone == "battlefield"
            and not spec.filter.is_card
        ):
            return ast.ChoosePermanent(chooser, spec)
        # Anything else this production has no answer for, and a choice made
        # from a wider set than the card names is not the card. Refused rather
        # than admitted with the clause dropped.
        stream.reset(mark)
        return None
    # The choice is optional exactly when the sentences behind it print both
    # branches; the rider that reads "If they don't" is what says so, and it
    # sets the flag through `dataclasses.replace`.
    return ast.ChoosePermanent(chooser, spec, host_for_source=host_for_source)
