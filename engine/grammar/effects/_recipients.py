"""Whom a damage clause deals its damage to.

"…deals 1 damage to each creature with flying **and each player**" is one
clause with one amount and a list of recipients, and ``damage.py`` reads the
first half of it: the verb, the amount and the riders. Everything after the
word "to" (or "among", for a divided clause) is read here, with every narrowing
and union a damage sentence prints on a recipient and no other verb does — the
"or planeswalker" union, the accusative "them", the seat narrowings ("who
attacked this turn", "previously dealt damage by it", "who sacrificed a Plains
this way", "who controls a white creature"), the plural and ordinal spellings
of "any target" (Firestorm, Cone of Flame), the conjunct loop and where it
stops (Mind Whip, Hail Storm), a divided clause's targets and their printed
ceiling (Arc Lightning), and the history The Fallen names instead of a board.

Pre-split out of ``damage.py`` at Torment's Phase 0, with that module 42 lines
under the thousand-line guard and every damage sentence of the set passing
through it. The seam is the one the lowering side drew at Urza's Legacy's
first wave, when ``lowering/_recipients.py`` left ``lowering/damage.py``: a
damage event happening has two halves, how much and to whom, and this is the
second — so the name is that module's, and the mirror re-forms rather than
forking. It is also the half that grows. Of the 385 lines ``damage.py`` gained
between its split at Ice Age and this one, 260 were the readers below, and the
other 125 were spread across the amount, the riders and the "unless" tail.

Every reader here is damage-only on purpose, and each says why where it is
read: a narrowing parsed where no lowering honours it is a card that hits
anybody. That is why this is not ``references.py``, which holds the recipient
reader every verb shares and is called from here for the plain cases.

A **floor**, not a family, and a single-importer one exactly as ``_strips`` and
``_reveal_until`` are: ``damage`` is the only family that asks, and families
may not import each other. It reads the noun, seat and bound-object readers a
layer down and imports nothing back.
"""

import dataclasses

from .. import ast
from ..amounts import parse_amount
from ..bounds import accept_target_bound
from ..seat_comparisons import accept_player_control
from ..nouns import parse_object_filter
from ..records import accept_player_deed
from ..references import parse_recipient
from ..lexer import NUMBER, WORD
from ..stream import TokenStream
from ..vocabulary import NUMBER_WORDS
from ..phrases import accept_or_planeswalker, parse_bound_subject


#: The two spellings of CR 115.4's "any target" a sentence uses for its
#: **second and third** one: "…1 damage to any target, 2 damage to **another
#: target**, and 3 damage to **a third target**" (Cone of Flame). The words are
#: the printed way of saying "and not one you have already named", which is
#: exactly ``TargetSpec.distinct_from_prior``; the ordinal says which clause it
#: was printed in and nothing about the object, so it is read and dropped.
_FURTHER_ANY_TARGET = (("another", "target"), ("a", "third", "target"))


def _at_bare_words(stream: TokenStream, words: tuple[str, ...]) -> bool:
    """Whether the cursor is at *words* with **no further word after them**.

    "another target" ends Cone of Flame's second clause and "another target
    creature" opens Garruk's, and the only thing that tells them apart is
    whether a noun follows. Looked ahead rather than tried-and-rewound, because
    the shorter reading succeeds on a prefix of the longer one and would take
    it — the same reason ``references._at_counted_target`` looks ahead.
    """
    if any(stream.peek_word(i) != word for i, word in enumerate(words)):
        return False
    after = stream.peek(len(words))
    return after is None or after.kind != WORD


def _accept_several_any_targets(stream: TokenStream) -> "ast.TargetSpec | None":
    """``[each of] <count> targets`` — CR 115.4's phrase in the **plural**.

    "Firestorm deals X damage to **each of X targets**." One announcement of a
    cross-seat list, which is what ``divided_targets`` is, so the lowering
    hands it to that channel; here it is read as an ordinary ``any_target``
    carrying a count, because that is what the words say.

    Read in the damage family rather than beside ``any target`` in
    ``references`` for that production's own stated reason: only damage prints
    this phrase, and a plural "any target" admitted everywhere would hand a
    two-target picker to the dozens of lowerings that resolve exactly one.

    The count may be a printed number or the announced X (CR 107.3a) — the two
    spellings ``_describe_several_targets`` already carries — and nothing else:
    a phrase with no count is the ordinary singular one screen up.
    """
    mark = stream.mark()
    stream.accept_phrase("each", "of")
    ceiling = stream.accept_phrase("up", "to")  # "…each of up to three targets"
    token = stream.peek()
    word = stream.peek_word()
    counted = token is not None and (
        token.kind == NUMBER or word in NUMBER_WORDS or word == "x"
    )
    if not counted or stream.peek_word(1) != "targets" or (ceiling and word == "x"):
        stream.reset(mark)
        return None
    amount = parse_amount(stream)
    stream.expect_word("targets")
    fixed = isinstance(amount, ast.Fixed)
    return ast.TargetSpec(
        "any_target",
        count=amount.value if fixed else 0,
        count_from_x=not fixed,
        targeted=True, max_count=amount.value if ceiling else None,
    )


def _parse_damage_recipient(stream: TokenStream) -> ast.Recipient | None:
    """A damage recipient, plus the one union only damage prints: "target
    player or planeswalker" (Chandra's Magmutt). Read here rather than in
    ``parse_player_ref`` so the flag exists only where the damage lowering —
    the one consumer that honours it — can receive it.

    The two plural/ordinal spellings of "any target" are read here for that
    same reason, and they are probed **first**: "a third target" would
    otherwise be taken by the article quantifier and refused on the missing
    noun, and the rewind that follows is invisible to the caller either way.
    """
    for opener in _FURTHER_ANY_TARGET:
        if _at_bare_words(stream, opener):
            stream.advance(len(opener))
            return ast.TargetSpec(
                "any_target", targeted=True, distinct_from_prior=True
            )
    several = _accept_several_any_targets(stream)
    if several is not None:
        return several
    # "…this enchantment deals 2 damage to **them**." (Rivalry.) Singular
    # "they" in the accusative, naming the seat the trigger froze — which is
    # what ``that_player`` means to every consumer downstream, and exactly what
    # the nominative spelling of the same sentence ("…deals 2 damage to **that
    # player**") already produced. One referent, two printed word forms.
    #
    # Read here rather than in ``parse_player_ref``, beside the "or
    # planeswalker" union below and for the identical reason: the word is
    # ambiguous *in this grammar* in a way its nominative is not. "Them" after
    # a verb is also how a card names a set of cards an earlier clause produced
    # — "Create three … tokens. Exile **them**" (Waylay) — so a general reading
    # takes those for a seat. A damage recipient cannot be a pile of cards in a
    # library, so here the seat is the only thing it can be.
    #
    # Before ``parse_recipient`` because that reader would not claim the word
    # at all; the position is what makes the branch legible next to the two
    # narrowings below, not a precedence.
    if stream.accept_word("them"):
        return ast.PlayerRef("that_player")
    recipient = parse_recipient(stream)
    # "target player **or planeswalker**" (Chandra's Magmutt). Two words behind
    # the noun phrase, read by ``phrases`` because prevention prints them too
    # (Wandering Mage) and the two families may not import each other.
    widened = accept_or_planeswalker(stream, recipient)
    if widened is not recipient:
        return widened
    if (
        isinstance(recipient, ast.PlayerRef)
        # "…deals 2 damage to **each player who sacrificed a Plains this way**."
        # (Desolation.) The relative clause the sentence in front of it also
        # prints, read here beside the two narrowings below and for their exact
        # reason: this lowering is what carries it to the handler that loops the
        # seats, so a clause read anywhere else would be one nobody applies —
        # and unapplied, the card damages every player at the table.
        #
        # Not restricted to the chosen forms the two below are: "who sacrificed
        # … this way" is answered by a record rather than by a picker, so the
        # seat sets are exactly the kinds that can carry it.
        and recipient.kind in ("each_player", "each_opponent")
    ):
        deed = accept_player_deed(stream, parse_object_filter)
        if deed is not None:
            return dataclasses.replace(recipient, did=deed)
    if (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind in ("target_player", "target_opponent")
        # "target player **who attacked this turn**" (Fire and Brimstone). Read
        # here, beside the union above and for the same reason: damage is the
        # only effect in the pool that prints it, and the narrowing is only
        # honoured by the picker this lowering feeds. A restriction parsed
        # somewhere no reader enforces is a card that hits anybody.
        and stream.accept_phrase("who", "attacked", "this", "turn")
    ):
        return dataclasses.replace(recipient, attacked_this_turn=True)
    if (
        isinstance(recipient, ast.PlayerRef)
        and recipient.kind in ("target_player", "target_opponent")
        # "target opponent **previously dealt damage by it**" (Diseased
        # Vermin). Beside the attack narrowing above and read the same way: the
        # restriction is only honoured by the picker this lowering feeds, so a
        # parse anywhere else would be a clause nobody enforces.
        #
        # "By it" is the ability's own source — the only referent the sentence
        # has — and every word is required: "previously" is the whole window,
        # and a printing naming another one would be a different record.
        and stream.accept_phrase("previously", "dealt", "damage", "by", "it")
    ):
        return dataclasses.replace(recipient, damaged_by_source=True)
    if recipient is None:
        # "This creature deals 2 damage to **that creature** at end of combat."
        # (Dwarven Sea Clan.) The back-reference every other family already
        # reads through ``parse_bound_subject`` — the object an earlier sentence
        # of the same effect chose, which ``parse_recipient`` deliberately does
        # not claim because a bare definite noun phrase is nobody's target.
        #
        # Read only where that reader found nothing, so no phrase it already
        # takes changes meaning; and refused by default at the lowering, which
        # accepts the quantifier under a bound-object delayed event and names
        # what is missing under any other. A parse without that gate would deal
        # the damage to whatever the resolution context happened to carry.
        return parse_bound_subject(stream)
    return recipient


def _ends_the_recipient_list(stream: TokenStream) -> bool:
    """Whether the noun phrase just read really was another recipient.

    "…deals 2 damage to that player **and you tap that creature**." (Mind
    Whip.) The conjunct loop reads "you" as a second recipient perfectly
    happily, and the verb after it then belongs to nothing — which is the
    greedy half of a genuine ambiguity: "and <noun phrase>" is a further
    recipient when the clause ends there, and the *subject of the next clause*
    when a predicate follows.

    A recipient list ends the clause it is in. Everything a damage sentence
    prints after one — a rider, a duration, a second sentence — opens with
    punctuation or ends the line, so a bare word at the cursor is the verb of a
    new predicate and the conjunct is its subject.

    Refusing here rather than in the sentence loop is what keeps the reading
    honest in both directions: the whole conjunct is rewound, so the "and" is
    left for the statement layer to split on, and Mind Whip's tap lands in the
    branch the card prints it in instead of running unconditionally.

    Two printed words are the exceptions, and each is an exception to the
    premise rather than to the rule — a word that continues *this* sentence and
    is never the verb of a new predicate, so the conjunct in front of it really
    was a recipient and rewinding would cost the card the second half of its
    recipient list:

    - "…deals 2 damage to each creature and each player **instead**."
      (Gangrenous Zombies) — the conditional-instead rider's marker for the
      sentence it closes.
    - "…deals damage to each creature and each player **equal to** the number
      of Mountains put into a graveyard this way." (Volcanic Eruption) — the
      deferred quantity of the same clause, in the word order that puts it
      after the recipients. No statement in this grammar opens with "equal".
    """
    token = stream.peek()
    if token is None or token.kind != WORD:
        return True
    return token.text in ("instead", "equal")


def _parse_recipient_list(stream: TokenStream) -> list[ast.Recipient]:
    """The recipients of one damage clause, with the "and" conjuncts it prints.

    "each creature with flying **and each player**" is one recipient list, not
    a second damage event — and `_ends_the_recipient_list` is what keeps the
    conjunct loop from swallowing the subject of the next sentence.

    The first recipient goes through `_parse_damage_recipient` rather than
    `parse_recipient`, because only damage prints the "or planeswalker" union
    and the "who attacked this turn" narrowing.
    """
    recipient = _parse_damage_recipient(stream)
    if recipient is None:
        raise stream.error("expected a damage recipient")
    recipients = [_with_control_narrowing(stream, recipient)]
    while True:
        mark = stream.mark()
        if not stream.accept_word("and"):
            break
        extra = parse_recipient(stream)
        if extra is None:
            stream.reset(mark)
            break
        extra = _with_control_narrowing(stream, extra)
        if not _ends_the_recipient_list(stream):
            stream.reset(mark)
            break
        recipients.append(extra)
    return recipients


def _with_control_narrowing(stream: TokenStream, recipient: ast.Recipient):
    """*recipient* with a trailing ``who controls <noun phrase>`` folded in.

    "…deals 2 damage to each white creature and **each player who controls a
    white creature**." (Disorder.) Read at this call site rather than inside
    ``parse_player_ref``, which is where ``accept_player_deed`` is read too and
    for the same reason: a seat narrowing is only safe where a lowering carries
    it, and reading it everywhere would let a clause be consumed under a verb
    that then acts on every player. Left on the stream anywhere else, the words
    fail full-token consumption and the line refuses — the loud direction.
    """
    if not isinstance(recipient, ast.PlayerRef):
        return recipient
    described = accept_player_control(stream, parse_object_filter)
    if described is None:
        return recipient
    return dataclasses.replace(recipient, controls=described)


def _parse_divided_recipients(stream: TokenStream) -> ast.Recipient:
    """The recipient set a divided damage clause divides among.

    Two printed spellings of CR 601.2d's "one or more targets", and the second
    is what separates them: "among **any number of** targets" leaves the count
    open (Fireball, Pyrotechnics), and "among **one, two, or three** targets"
    prints its ceiling (Arc Lightning). The enumeration is read by the same
    ``bounds.accept_target_bound`` Contagion's distributed counters use — CR
    601.2d covers damage and counters in one sentence, so the two clauses are
    the same clause and read by the same production.

    The bound rides on ``TargetSpec.max_count``, which the lowering turns into
    the ordinary ``max_targets`` every other picker spec carries. Dropped
    instead, "one, two, or three" would parse as "any number" and let a
    3-damage spell be announced over four targets that CR 601.2c forbids —
    except that CR 601.2d's "at least 1 to each" already caps *this* card at
    three, which is exactly why the word has to be carried rather than reasoned
    about: the next card printing it need not have the amount to match.
    """
    if not stream.accept_phrase("any", "number", "of"):
        bound = accept_target_bound(stream)
    else:
        bound = None
    recipient = parse_recipient(stream)
    if recipient is None:
        raise stream.error("expected damage recipients")
    if bound is not None:
        if not isinstance(recipient, ast.TargetSpec):
            # A ceiling on a count is a fact about *targets*; a bound printed
            # in front of a recipient that chooses none would be read and
            # dropped, which is the silent-widening class this grammar refuses.
            raise stream.error("a target ceiling needs targets to bound")
        recipient = dataclasses.replace(recipient, max_count=bound)
    return recipient


#: The printed classes a "it has dealt damage to this game" phrase may name,
#: singular form first. A closed set, read as words rather than through the noun
#: parser, because what follows them is not a filter at all — the phrase names a
#: *history*, and `parse_object_filter` would build a description of the board
#: instead and quietly widen the card.
_HISTORY_CLASSES = {
    "opponent": "opponent", "opponents": "opponent",
    "player": "player", "players": "player",
    "planeswalker": "planeswalker", "planeswalkers": "planeswalker",
    "creature": "creature", "creatures": "creature",
}


def _accept_damaged_this_game(stream: TokenStream) -> tuple[str, ...] | None:
    """``each <class>[ and <class>…] it has dealt damage to this game``.

    Returns the classes the phrase named, or None without consuming when the
    words are something else — every other damage recipient keeps its own
    reading.

    The whole trailing clause is expected once the class list has been read:
    "each opponent" alone is a board sweep and a strictly larger effect, so a
    production that read the nouns and shrugged at the history would turn The
    Fallen into a Pestilence.
    """
    mark = stream.mark()
    if not stream.accept_word("each"):
        stream.reset(mark)
        return None
    classes: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or word not in _HISTORY_CLASSES:
            break
        classes.append(_HISTORY_CLASSES[word])
        stream.advance()
        if not stream.accept_word("and"):
            break
    if not classes or not stream.accept_phrase(
        "it", "has", "dealt", "damage", "to", "this", "game"
    ):
        stream.reset(mark)
        return None
    return tuple(classes)
