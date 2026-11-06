"""A loop or a count printed in *front* of the sentence it governs.

"**For each creature that died this way,** put a creature card …" (Glyph of
Reincarnation); "**For each land,** destroy that land unless any player pays 1
life" (Cleansing); "**The controller of each of those artifacts** gains life …"
(Seeds of Innocence); "**For each land target player controls in excess of the
number you control,** choose a land …" (Equipoise). One question, eight
spellings: something is repeated or counted, and the clause saying so comes
*before* the sentence rather than trailing it where `phrases._parse_for_each`
reads it.

Split off `statements.py` at Weatherlight's Phase 0, when that module sat at
exactly the thousand-line guard with a wave about to open on it — and every one
of the three caps Visions crossed was crossed at integration, by two groups'
additions summing, on nobody's branch. The block was contiguous in
`_parse_statement_body` and asks one question, which is the line this file
draws: a leading iteration is read here, a leading *duration* stays there.

The statement layer is reached only through what the caller hands down —
`parse_body`, `parse_optional_action`, `accept_trailing_toll` — which is the
convention `statements.py` already uses for `conditions` and `subject_verb`
("handed back what they need from here rather than importing upward"). Every
production this calls declines without consuming, so the caller's chain keeps
every reading it had.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .cost_records import accept_mana_per_colored_symbol
from .effects import (_parse_for_each_destroy_unless_paid,
                      _parse_have_source_deal_damage)
from .effects.attachments import parse_excess_choice_paragraph
from .effects.cards import _parse_for_each_revealed_discard
from .sentence_clauses import (_parse_leading_controller_of_each,
                               _parse_leading_count_scale,
                               _parse_leading_for_each,
                               _parse_leading_recorded_count)
from .stream import TokenStream
from .subject_verb import parse_subject_verb


#: The verbs a seat loop's distributive subject may govern, each of which reads
#: its seat off the loop's binding once its elided "you" is rebound. The life
#: gain is Reward the Faithful's ("…each gain life equal to …").
_LOOP_SEAT_DEEDS = (ast.Discard, ast.Draw, ast.GainLife)

#: The seat sets "any number of target <players> each" may announce, by the
#: printed noun: Wheel and Deal's opponents, and Reward the Faithful's and
#: Cabal Conditioning's players — the caster included (CR 115.1, 601.2c), each
#: player once (CR 115.3).
_ANY_NUMBER_OF_SEATS: dict[str, str] = {
    "opponents": "any_number_of_target_opponents",
    "players": "any_number_of_target_players",
}


def _parse_any_number_of_target_opponents_each(
    stream: TokenStream, parse_optional_action,
) -> "ast.ForEach | None":
    """``Any number of target opponents|players each <verb> …[, then <verb>
    …]``.

    The head names the iterator; each verb phrase behind it is read by the
    imperative reader — which hands its elided subject "you" — and rebound to
    the loop's "that player", the seat each iteration binds. Only the deeds a
    seat loop body is known to read its seat for (:data:`_LOOP_SEAT_DEEDS`) are
    admitted: any other verb refuses the whole sentence rather than being
    performed by the caster. Returns None with the cursor untouched.
    """
    mark = stream.mark()
    seats = None
    if stream.accept_phrase("any", "number", "of", "target"):
        seats = _ANY_NUMBER_OF_SEATS.get(stream.peek_word() or "")
        if seats is not None:
            stream.advance()
    if seats is None or not stream.accept_word("each"):
        stream.reset(mark)
        return None
    steps: list = []
    while True:
        try:
            step = parse_subject_verb(
                stream, ast.PlayerRef("that_player"),
                parse_optional_action=parse_optional_action,
            )
        except GrammarError:
            stream.reset(mark)
            return None
        if not (
            isinstance(step, _LOOP_SEAT_DEEDS)
            and isinstance(step.player, ast.PlayerRef)
            and step.player.kind in ("you", "that_player")
        ):
            stream.reset(mark)
            return None
        steps.append(dataclasses.replace(step, player=ast.PlayerRef("that_player")))
        joined = stream.mark()
        if stream.accept_punct(",") and stream.accept_word("then"):
            continue
        stream.reset(joined)
        break
    effect = steps[0] if len(steps) == 1 else ast.Sequence(tuple(steps))
    return ast.ForEach(ast.PlayerRef(seats), effect)


def _parse_choose_targets_for_each(
    stream: TokenStream, parse_body,
) -> "ast.ForEach | None":
    """``Choose any number of target players or planeswalkers. For each of
    them, <step>, <step>, then <step>.`` (Kaboom!.)

    Two sentences and one loop: the first is CR 601.2c's announcement (any
    number of objects of CR 115.4's union, zero included) and names nothing on
    its own, the second is performed once per object it chose — "them" — in
    turn order (the card's 2022-09-09 ruling). Read whole, for the paragraph
    rule: apart, the first is a choice nothing reads and the second a pronoun
    nothing binds.

    The body's steps are ordinary statements joined by commas and a final
    "then", read one at a time by the caller's body reader; "that player or
    planeswalker" inside them is the loop's object
    (``lowering`` honours it only under ``LOOP_BOUND_TARGET``). Returns None
    with the cursor untouched.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "choose", "any", "number", "of", "target", "players", "or",
        "planeswalkers",
    ):
        stream.reset(mark)
        return None
    if not (
        stream.accept_punct(".")
        and stream.accept_phrase("for", "each", "of", "them")
        and stream.accept_punct(",")
    ):
        stream.reset(mark)
        return None
    steps: list = []
    while True:
        try:
            step = parse_body(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        steps.extend(step.steps if isinstance(step, ast.Sequence) else (step,))
        joined = stream.mark()
        if stream.accept_punct(","):
            stream.accept_word("then")
            if not (stream.exhausted or stream.at_punct(".")):
                continue
        stream.reset(joined)
        break
    if not (stream.exhausted or stream.at_punct(".")):
        stream.reset(mark)
        return None
    effect = steps[0] if len(steps) == 1 else ast.Sequence(tuple(steps))
    return ast.ForEach(
        ast.PlayerRef("any_number_of_target_players_or_planeswalkers"), effect,
    )


def parse_leading_iteration(
    stream: TokenStream,
    *,
    parse_body,
    parse_optional_action,
    accept_trailing_toll,
) -> "ast.Statement | None":
    """The leading-iteration readings, in the order the chain always tried them.

    Returns the statement, or None having consumed nothing — every production
    below refuses without consuming, so the caller's chain continues exactly
    where it did.
    """
    # "**For each creature that died this way,** put a creature card …" (Glyph
    # of Reincarnation) — the iteration clause in its *leading* printed
    # position, where `phrases._parse_for_each` reads the trailing one. Read at
    # the statement level rather than inside the effect behind it, because it
    # governs a whole sentence: the same rule the leading duration a few
    # branches below follows, and for the same reason — an effect that read its
    # own "for each" would be one production per effect that can carry one.
    # "**For each land,** destroy that land unless any player pays 1 life."
    # (Cleansing.) Read before the "this way" windows below, because both open
    # with the same two words and only this one names a set on the battlefield
    # — the window reader would take the noun phrase and then fail the line on
    # the missing participle, losing it to a less specific error.
    # "**Have this enchantment deal 5 damage to that player**" (Worms of the
    # Earth) — a damage event printed as something a player chooses to do, so
    # it opens with a verb rather than with the subject `subject_verb` wants.
    have_deal = _parse_have_source_deal_damage(stream)
    if have_deal is not None:
        return have_deal
    # "**Any number of target opponents each** discard their hands, then draw
    # seven cards." (Wheel and Deal.) A loop over the seats the announcement
    # named (CR 601.2c: zero or more opponents, each once), with its subject
    # printed in front of the verbs the way "the controller of each of those
    # artifacts" is (Seeds of Innocence, below).
    any_number = _parse_any_number_of_target_opponents_each(
        stream, parse_optional_action
    )
    if any_number is not None:
        return any_number
    # "**Choose any number of target players or planeswalkers. For each of
    # them,** …" (Kaboom!.) The same announced loop with its announcement in a
    # sentence of its own, and over CR 115.4's union rather than seats alone.
    chosen_each = _parse_choose_targets_for_each(stream, parse_body)
    if chosen_each is not None:
        return chosen_each
    # "**For each colored mana symbol in the milled card's mana cost,** add one
    # mana of that color." (Charmed Pendant.) A rate over a card the ability's
    # own cost consumed, read whole and before the counts below — "colored
    # mana symbol" is not a noun phrase any of them has a reading for.
    per_symbol = accept_mana_per_colored_symbol(stream)
    if per_symbol is not None:
        return per_symbol
    each_bought_off = _parse_for_each_destroy_unless_paid(stream)
    if each_bought_off is not None:
        return each_bought_off
    # The *count* reading of the same leading words, tried first because it is
    # the narrower one: it requires the phrase to name a zone other than the
    # battlefield, which the loop's sentences never do.
    per_count = _parse_leading_count_scale(parse_body, stream)
    if per_count is not None:
        return per_count
    # "**For each card discarded this way,** put two +1/+1 counters on this
    # creature." (Mind Maggots.) A leading **rate** over what an earlier step of
    # this same effect recorded — not the count scale above, which is gated on
    # the phrase naming a zone to go and count, and a scratchpad is not one.
    #
    # Read after that one and before the general loop below, and the participle
    # is what makes the order safe: this refuses every phrase that does not end
    # in "<participle> this way", so a set-naming "For each …" never reaches it,
    # and it refuses without consuming so the loop keeps every line it had.
    per_record = _parse_leading_recorded_count(parse_body, stream)
    if per_record is not None:
        return per_record
    # "**For each blue instant card revealed this way,** that player discards
    # that card unless they pay 4 life." (Sirocco.) Read before the general
    # leading loop below, which would take the noun phrase and then fail the
    # line on a body it has no reading for — the discard names "that card",
    # which is one turn of a loop rather than a subject anything else parses.
    # Refuses without consuming, so every other "For each …" keeps its reading.
    revealed_discard = _parse_for_each_revealed_discard(stream)
    if revealed_discard is not None:
        return revealed_discard

    # "**The controller of each of those artifacts** gains life equal to its
    # mana value." (Seeds of Innocence.) The loop with its subject printed in
    # front of it. Read here, beside the "for each …" spelling it is a word
    # order of and before the subject-verb reader below, which would take "the
    # controller" as a bare back-reference and then loop over nothing.
    controller_of_each = _parse_leading_controller_of_each(stream)
    if controller_of_each is not None:
        return ast.ForEach(
            controller_of_each,
            parse_subject_verb(
                stream, ast.PlayerRef("controller"),
                parse_optional_action=parse_optional_action,
            ),
        )
    # "**For each land target player controls in excess of the number you
    # control,** choose a land that player controls, then the chosen permanents
    # phase out." (Equipoise.) A head clause that is a *count* rather than a
    # set, so it is not the loop below and cannot be read as one: lowered as a
    # repetition it would arm one prompt per excess land and leave the plural
    # sentence behind it naming one of them. Read first because both open on
    # the same two words, and it refuses without consuming.
    excess_choice = parse_excess_choice_paragraph(stream)
    if excess_choice is not None:
        return excess_choice
    per_death = _parse_leading_for_each(parse_body, stream)
    if per_death is not None:
        # The repeated act may be printed as a choice of two ("pay 4 life **or**
        # put the card on top of your library"), so it is read through the same
        # alternatives reader "you may …" uses. One reader, so a statement-level
        # "or" means one thing wherever the pool prints it — and neither
        # position can quietly take the first half and drop the rest.
        repeated = parse_optional_action(stream)
        # "…sacrifice a permanent other than this enchantment **unless you
        # discard a card**" (Oath of Lim-Dûl). The toll belongs to the repeated
        # sentence, not to the loop around it: the offer is made once per
        # repetition, and read outside the loop it would be one offer buying
        # off every repetition at once.
        return ast.ForEach(per_death, accept_trailing_toll(parse_body, stream, repeated) or repeated)
    return None
