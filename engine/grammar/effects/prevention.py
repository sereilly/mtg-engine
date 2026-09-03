"""Damage that is stopped or moved (CR 614.9, CR 615).

The productions for a sentence whose subject is a damage event that will
**not** be dealt as it would have been: the shields ("prevent the next N
damage…", "prevent all damage…", the Circles of Protection), the redirects
("…is dealt to <recipient> instead"), and Whippoorwill's lock that forbids
both.

Split out of ``damage.py`` at the 1,000-line guard, along the line the lowering
side had already drawn — ``lowering/prevention.py`` and
``lowering/redirection.py`` left that module for the same reason. What is
different here is that the parse side keeps the two **together**:
``_parse_source_of_choice_effect`` reads one printed sentence and returns
either node, because CR 615.8's "a source of your choice" is a way of *naming*
the damage and the clause after the comma decides what happens to it. Two
modules would be one importing the other, which is the coupling the family
split exists to prevent — so the family is "the damage does not land as
printed", and the name is the half of it the pool mostly prints.
"""

from .. import ast
from ..amounts import parse_amount
from ..references import parse_recipient
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..readers import accept_source_reference
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES, COLOR_WORDS
from ..phrases import (_parse_duration, _parse_opponents_choice,
                       accept_or_planeswalker, parse_bound_subject)


def _parse_prevent(stream: TokenStream) -> ast.PreventDamage:
    """"Prevent the next N damage that would be dealt to <recipient> this turn."

    The recipient decides which handler shape applies, so it is parsed rather
    than skipped: "you" and "this creature" are different shields from "any
    target", and conflating them would put the shield on the wrong thing.
    """
    stream.expect_word("prevent")
    if stream.at_word("all"):
        return _parse_prevent_all(stream)
    if not stream.accept_phrase("the", "next"):
        raise stream.error("expected 'the next' in a prevention effect")
    amount = parse_amount(stream)
    if not stream.accept_word("damage"):
        raise stream.error("expected 'damage'")
    if not stream.accept_phrase("that", "would", "be", "dealt"):
        raise stream.error("expected 'that would be dealt'")
    # "…that would be dealt **this turn to** target creature you control."
    # (Samite Alchemist.) The pre-modern printing puts the duration first, and
    # both orders are the same sentence — the blanket branch below already
    # reads either for Pack Leader's identical swap, and a numeric shield
    # failing on word order is the card lost to a printing convention rather
    # than to a missing effect. Read here, before the "to", so the recipient
    # reader below sees the same stream either way.
    duration = _parse_duration(stream)
    if not stream.accept_word("to"):
        raise stream.error("expected 'to' in a prevention effect")
    recipient = parse_recipient(stream)
    if recipient is None:
        raise stream.error("expected something to shield")
    # "…dealt to target player **or planeswalker** this turn" (Wandering Mage).
    # CR 115.4's union, read from ``phrases`` because damage prints the same two
    # words (Chandra's Magmutt) and the two families may not import each other.
    # Read before the trailing duration, which is where the card prints it.
    recipient = accept_or_planeswalker(stream, recipient)
    # The trailing spelling. Only one of the two may be printed: a duration on
    # both sides is not a sentence this reads, and taking the second silently
    # would let two windows disagree about how long the shield lasts.
    if duration.kind is None:
        duration = _parse_duration(stream)
    alternate = _parse_instead_rider(stream)
    if alternate is None:
        return ast.PreventDamage(amount, to=recipient, duration=duration)
    described, larger = alternate
    return ast.PreventDamage(
        amount, to=recipient, duration=duration,
        alternate_amount=larger, alternate_subject=described,
    )


def _parse_instead_rider(
    stream: TokenStream,
) -> "tuple[ast.ObjectFilter, ast.Amount] | None":
    """``. If it's <noun phrase>, prevent the next N damage instead.`` (Elvish
    Healer.)

    A rider on the shield in front of it rather than a sentence of its own: it
    prevents nothing by itself, and "instead" says so — the two sentences arm
    **one** shield whose size depends on what the first one's target turns out
    to be. Read here for the same reason the upkeep toll's trailing sentence is
    read inside its own production: a statement layer that split them would arm
    two shields and prevent three.

    Every part is required. The pronoun must be "it" (the target the sentence
    in front of it chose), the noun phrase is what decides which size applies,
    and the printed "instead" is the difference between a larger shield and a
    second one.

    Refuses with the cursor untouched, so a prevention sentence followed by any
    other sentence keeps the reading it has.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    if not stream.accept_phrase("if", "it", "'s"):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("prevent", "the", "next"):
        stream.reset(mark)
        return None
    try:
        larger = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("damage", "instead"):
        stream.reset(mark)
        return None
    return described, larger


def _parse_prevent_all(stream: TokenStream) -> ast.PreventDamage:
    """"Prevent all [combat] damage that would be dealt [to <recipient>] <duration>."

    A blanket shield rather than a numeric one, so the quantity is
    :class:`ast.AllOf` and there is nothing to count down. Three parts are read
    rather than skipped, because each one names a *different* card:

    * "combat" — Fog stops only combat damage; a card stopping all damage is a
      strictly larger effect and must not borrow Fog's handler.
    * the recipient — "…dealt to you this turn" is a shield on one player, which
      is not what the turn-wide flag implements.
    * the duration — a blanket prevention with no duration is a continuous
      static ability, not a one-shot effect.

    All three reach lowering, which refuses every combination but the one a
    handler exists for. Parsing them and refusing there (rather than declining
    to parse) is what keeps the backlog honest about which wording is missing.
    """
    stream.expect_word("all")
    combat_only = bool(stream.accept_word("combat"))
    stream.expect_word("damage")
    if not stream.accept_phrase("that", "would", "be", "dealt"):
        raise stream.error("expected 'that would be dealt' in a prevention effect")
    recipient: ast.Recipient | None = None
    dealt_by: ast.Recipient | None = None
    to_and_by = False
    if stream.accept_word("to"):
        # "…that would be dealt **to and dealt by** that creature this turn."
        # (Ebony Horse, Maze of Ith.) One printed object standing at both ends
        # of the event, named once. Read here rather than as a second "by"
        # clause below, because these words come *before* the noun: a reader
        # expecting them after it would leave "and dealt by" unconsumed and
        # fail the line at the noun instead of at the wording.
        to_and_by = bool(stream.accept_phrase("and", "dealt", "by"))
        recipient = parse_recipient(stream)
        if recipient is None and to_and_by:
            recipient = parse_bound_subject(stream)
        if recipient is None:
            raise stream.error("expected something to shield")
        if to_and_by:
            dealt_by = recipient
    elif stream.accept_word("by"):
        # "…that would be dealt **by** target creature this turn." The word is
        # the whole difference between a creature that cannot be hurt and one
        # that cannot hurt anything, so it is read rather than skipped.
        #
        # ``parse_recipient`` first and the bound reader second, the order
        # ``statements.py`` uses for the same pair: "that creature**'s
        # controller**" is a player reference the first already reads, and a
        # bound reader that got there first would eat the noun and strand the
        # possessive.
        dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
        if dealt_by is None:
            raise stream.error("expected whose damage to prevent")
    duration = _parse_duration(stream)
    # "…dealt to and dealt by that creature **this combat**." (Winter's Chill.)
    # Read here rather than in the shared duration table, and the narrowness is
    # the point: "this combat" appears mid-sentence on six other cards in the
    # pool ("blocked by only that creature this combat", "can't be blocked this
    # combat except by …"), and a trailing-duration reader that claimed it
    # everywhere would swallow those words from productions that do not mean a
    # duration by them. Its own kind rather than ``until_end_of_combat``'s for
    # the reason "this turn" is not ``until_end_of_turn``: two printed spellings
    # of one window are two kinds here, and the sweep is what makes them one.
    if duration.kind is None and stream.accept_phrase("this", "combat"):
        duration = ast.Duration("this_combat")
    # "…that would be dealt **this turn to Dogs you control**" (Pack Leader).
    # The printed order puts the duration first, and both orders are the same
    # sentence — so the recipient is read on either side rather than the card
    # failing on word order. Only one of the two may appear: a line naming a
    # recipient twice is not a wording this reads.
    if recipient is None and stream.accept_word("to"):
        recipient = parse_recipient(stream)
        if recipient is None:
            raise stream.error("expected something to shield")
    # "…that would be dealt **this turn by target creature you control**" (Kry
    # Shield), and "…dealt **to you this turn by attacking creatures without
    # flying**" (Al-abara's Carpet). The same word-order swap as the recipient
    # above, on the other end of the event — read on either side rather than the
    # card failing on the order its printing happens to use. Both ends may
    # appear: a shield naming who is protected *and* whose damage is stopped is
    # a narrower effect than either half, and dropping one would widen it.
    if dealt_by is None and stream.accept_word("by"):
        dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
        if dealt_by is None:
            raise stream.error("expected whose damage to prevent")
    # "…by that creature **and each creature blocking it**." (Feint.) More than
    # one source, joined by the printed "and". Read here rather than in either
    # of the two "by" branches above because it belongs to the conjunct *list*
    # and not to the word order — the same argument `_parse_condition` makes for
    # reading its own "and" once. The loop backtracks: an "and" that does not
    # introduce another source belongs to whatever follows the clause.
    dealt_by_others: list[ast.Recipient] = []
    while dealt_by is not None:
        mark = stream.mark()
        if not stream.accept_word("and"):
            break
        further = parse_recipient(stream) or parse_bound_subject(stream)
        if further is None:
            stream.reset(mark)
            break
        dealt_by_others.append(further)
    return ast.PreventDamage(
        ast.AllOf(), to=recipient, duration=duration, combat_only=combat_only,
        dealt_by=dealt_by, dealt_by_others=tuple(dealt_by_others),
        to_and_by=to_and_by,
    )


def _finish_named_source_shield(
    stream: TokenStream, source_filter: "ast.ObjectFilter", mark
) -> "ast.PreventDamage | None":
    """The tail of "The next time <named source> would deal damage to
    <recipient> <duration>, prevent that damage." (Mercenaries.)

    Split out because the sibling branch reads seven more words before reaching
    the same clause; keeping the tail in one function is what stops the two from
    drifting into two readings of one sentence.

    Only "prevent that damage" — the halving and the redirect the chosen-source
    branch also reads have no printing with a *named* source, and refusing here
    names that rather than lowering one of them onto a shield that answers to
    the wrong object.
    """
    recipient = parse_recipient(stream)
    if recipient is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    return ast.PreventDamage(
        ast.Fixed(1), to=recipient, from_filter=source_filter, duration=duration
    )


def _parse_source_of_choice_effect(
    stream: TokenStream,
) -> "ast.PreventDamage | ast.RedirectDamage | None":
    """"The next time a <colour> source of your choice would deal damage to you
    this turn, **prevent that damage**." — the Circles of Protection, and
    Reverse Damage with no colour word.

    …or "…, **that damage is dealt to target creature of an opponent's choice
    instead**" (Nova Pentacle). One production, because everything up to the
    comma is the same printed sentence: CR 615.8's "a source of your choice" is
    a way of *naming* the damage, and what the card then does with it — prevent
    it, or move it — is the clause after. Splitting them would be two
    productions racing on the same seven words, and the second would only ever
    be reached by the first rewinding.

    A whole-instance shield, not a numeric one; the amount is fixed at 1 because
    the handler counts shields, not damage.
    """
    mark = stream.mark()
    # "a red source" / "an artifact source" — the article follows the noun's
    # first letter, so both are accepted here rather than assuming "a".
    if not stream.accept_phrase("the", "next", "time"):
        stream.reset(mark)
        return None
    colours: list[str] = []
    card_type = None
    if not (stream.accept_word("a") or stream.accept_word("an")):
        # "The next time **this creature** would deal damage to you this turn,
        # prevent that damage." (Mercenaries.) The same CR 615.8 sentence with
        # the source *named* instead of chosen — a branch of this production
        # rather than one of its own, because everything from "would deal
        # damage to" onward is the identical clause and two productions racing
        # on "the next time" would differ only in how the second rewinds.
        named = parse_recipient(stream)
        if (
            not isinstance(named, ast.TargetSpec)
            or not named.filter.is_source
            or not stream.accept_phrase("would", "deal", "damage", "to")
        ):
            stream.reset(mark)
            return None
        return _finish_named_source_shield(stream, named.filter, mark)
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word in COLOR_WORDS:
        # "a **black or red** source of your choice" (Greater Realm of
        # Preservation). A list rather than one word, because the printed
        # sentence records one property with several admissible values — one
        # shield the next matching source spends, not one shield per colour.
        # Read as a loop rather than as a two-colour special case: a card
        # printing three needs no code.
        colours.append(COLOR_WORDS[word])
        stream.advance()
        while stream.accept_word("or"):
            token = stream.peek()
            word = str(token.text).lower() if token is not None else ""
            if word not in COLOR_WORDS:
                stream.reset(mark)
                return None
            colours.append(COLOR_WORDS[word])
            stream.advance()
    elif word in CARD_TYPES:
        # "an **artifact** source of your choice" (Circle of Protection:
        # Artifacts). The same Circle keyed on a card type instead of a colour
        # — CR 615.9 rechecks whichever property the shield recorded, so the
        # two are one production with two narrowings rather than two effects.
        card_type = word
        stream.advance()
    if not stream.accept_word("source"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("of", "your", "choice"):
        stream.reset(mark)
        return None
    # "a source of your choice **of the chosen color**" (Prismatic Circle). The
    # same Circle narrowing read one branch above, with the colour deferred to
    # what the permanent recorded as it entered (CR 614.1c) instead of printed
    # in the sentence — so it is read here, after "of your choice", because
    # that is where this card prints it and the branch above reads a colour
    # *word*, which "the chosen color" is not.
    #
    # Refused alongside a printed colour rather than folded in: "a red source
    # of your choice of the chosen color" names two properties, and a shield
    # records one (CR 615.9 rechecks *the* recorded property).
    chosen_color = bool(stream.accept_phrase("of", "the", "chosen", "color"))
    if chosen_color and (colours or card_type):
        raise stream.error("a shield records one source property, not two")
    if not stream.accept_phrase("would", "deal", "damage", "to"):
        stream.reset(mark)
        return None
    recipient = parse_recipient(stream)
    if recipient is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    if stream.accept_phrase("that", "damage", "is", "dealt", "to"):
        # Nova Pentacle. The damage is *moved*, so this leaves with a
        # RedirectDamage: nothing about it is a shield, and the one thing the
        # two share is how the source was named.
        new_recipient = parse_recipient(stream)
        if new_recipient is None:
            raise stream.error("expected who takes the redirected damage")
        chooser, new_recipient = _parse_opponents_choice(stream, new_recipient)
        if not stream.accept_word("instead"):
            raise stream.error("expected 'instead' to end a redirection effect")
        return ast.RedirectDamage(
            to=recipient,
            new_recipient=new_recipient,
            from_chosen_source=True,
            duration=duration,
            one_shot=True,
            chooser=chooser,
        )
    # "…, prevent **half** that damage, rounded down." (Dark Sphere.) The same
    # sentence, absorbing a share of the event instead of all of it — so it is
    # a branch of this production rather than a second one racing it over the
    # same seven opening words. The rounding is read rather than assumed:
    # `amounts.parse_amount` defaults a bare `Half` to "down", so an unread
    # "rounded up" would prevent one point less than the card says.
    half_mark = stream.mark()
    if stream.accept_phrase("prevent", "half", "that", "damage"):
        rounding = "down"
        stream.accept_punct(",")
        if stream.accept_word("rounded"):
            if stream.accept_word("up"):
                rounding = "up"
            elif not stream.accept_word("down"):
                raise stream.error("expected 'up' or 'down' after 'rounded'")
        if colours or card_type or chosen_color:
            # A shield that records a property *and* halves is a card nobody has
            # printed; refusing names the gap rather than dropping one half.
            raise stream.error("no shield both narrows its source and halves")
        return ast.PreventDamage(
            ast.Half(ast.ThatMuch(None), rounding),
            to=recipient,
            from_filter=ast.ObjectFilter(),
        )
    stream.reset(half_mark)
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    if colours:
        filt = ast.ObjectFilter(colors=tuple(colours))
    elif card_type:
        filt = ast.ObjectFilter(card_types=(card_type,))
    elif chosen_color:
        # Not a member of ``colors``: the colour is not in the sentence at all,
        # and folding it in would need a sentinel every ``colors`` reader would
        # then have to know about — the argument ``ObjectFilter.chosen_color``
        # already carries for the noun-phrase side.
        filt = ast.ObjectFilter(chosen_color=True)
    else:
        filt = ast.ObjectFilter()
    return ast.PreventDamage(ast.Fixed(1), to=recipient, from_filter=filt)


def _parse_damage_cant_be_prevented(
    stream: TokenStream,
) -> "ast.DamageCantBePreventedOrRedirected | None":
    """``Damage that would be dealt to <subject> <duration> can't be prevented
    or dealt instead to another permanent or player.`` (Whippoorwill.)

    Returns None with the cursor untouched for anything else opening with
    "damage", so every other sentence about damage keeps its own reader.

    **Both** halves of the printed clause are required. "Can't be prevented"
    alone is a different, weaker card, and a reader that stopped there would
    leave every redirection working while reporting the line claimed — the
    dropped-rider bug class, in the direction that lets the damage walk away.
    """
    mark = stream.mark()
    if not stream.accept_word("damage"):
        return None
    if not stream.accept_phrase("that", "would", "be", "dealt", "to"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream) or parse_bound_subject(stream)
    if subject is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if not accept_cant_be_prevented_tail(stream):
        stream.reset(mark)
        return None
    return ast.DamageCantBePreventedOrRedirected(subject, duration)


def accept_cant_be_prevented_tail(stream: TokenStream) -> bool:
    """``can't be prevented or dealt instead to another permanent or player``.

    The clause's whole predicate, shared by the two sentences that print it:
    Whippoorwill's, which says it of a creature for a turn, and Lava Burst's
    ``If <source> would deal damage to a creature, that damage …``, which says
    it of one spell's own damage. One reader, because reading eleven words in
    two places is two places for the pair of them to come apart — and it is
    exactly the pair that matters. "Can't be prevented" alone is a weaker card
    whose redirections all still work, so a half-read tail is the dropped-rider
    bug in the direction that lets the damage walk away.

    Consumes nothing unless the whole tail is there; the caller rewinds its own
    opening.
    """
    mark = stream.mark()
    for word in (
        "can't", "be", "prevented", "or", "dealt", "instead", "to", "another",
        "permanent", "or", "player",
    ):
        if not stream.accept_word(word):
            stream.reset(mark)
            return False
    return True


def parse_source_damage_lock(stream: TokenStream) -> bool:
    """``If <the source> would deal damage to a creature, that damage can't be
    prevented or dealt instead to another permanent or player.`` (Lava Burst.)

    True when the whole sentence was read, cursor left after it; False with the
    cursor untouched otherwise.

    The subject must be the ability's **own source**. The clause is a statement
    about which effects may modify this object's damage, and the only damage
    the resolution can mark that way is the damage it is itself dealing — a
    sentence naming some other object would be a lock nothing here can arm, so
    it refuses rather than being read as this one.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    if not accept_source_reference(stream):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("would", "deal", "damage", "to", "a", "creature"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("that", "damage"):
        stream.reset(mark)
        return False
    if not accept_cant_be_prevented_tail(stream):
        stream.reset(mark)
        return False
    return True


def _parse_damage_redirect(stream: TokenStream) -> "ast.RedirectDamage | None":
    """"All damage that would be dealt to <recipient> <duration> by <source> is
    dealt to <recipient> instead." (Shimian Night Stalker; Reverberation prints
    the same sentence naming only the source.)

    A redirection (CR 614.9), not a prevention: what changes is who the damage
    is dealt to, and the shield productions above must not be reached for it.

    Non-consuming until the shape is settled, because "All damage that would be
    dealt to you by unblocked creatures is dealt to this creature instead" is
    also the tail of a static ability ``engine/replacements.py`` implements
    whole, and a production that consumed the opening of every "All …" sentence
    would refuse lines other readers claim. Once "is dealt to" has been read the
    sentence is a redirect and nothing else, so from there it raises.

    **Two printed quantities, one production.** "All damage …" moves the whole
    event; "**The next N** damage …" moves N points and leaves the rest where it
    was dealt (Daughter of Autumn, Hazduhr the Abbot — CR 615.7's numeric shield
    read as a redirect). They are one sentence from the quantity onwards, which
    is why they are one production rather than two that would drift; the number
    rides :class:`ast.RedirectDamage`'s ``amount``, and ``None`` is "all".
    """
    mark = stream.mark()
    amount: ast.Amount | None = None
    if not stream.accept_word("all"):
        if not stream.accept_phrase("the", "next"):
            stream.reset(mark)
            return None
        try:
            amount = parse_amount(stream)
        except GrammarError:
            # "The next **time** a source of your choice…" is the shield
            # sentence `_parse_source_of_choice_effect` reads, and it is tried
            # ahead of this one — so refusing here without consuming is what
            # keeps every other "the next …" line with the reader it has.
            stream.reset(mark)
            return None
    # "All **combat** damage that would be dealt to you by unblocked creatures
    # this turn is dealt to this creature instead." (Kjeldoran Royal Guard.)
    # Read rather than skipped, for the reason the blanket shield above reads
    # the same word: with it the redirect catches only the combat damage step,
    # without it an unblocked attacker's ping ability moves too — a strictly
    # larger effect, and one no lowering below would have been told about.
    combat_only = bool(stream.accept_word("combat"))
    if not stream.accept_phrase("damage", "that", "would", "be", "dealt"):
        stream.reset(mark)
        return None
    to: ast.Recipient | None = None
    if stream.accept_word("to"):
        to = parse_recipient(stream) or parse_bound_subject(stream)
        if to is None:
            stream.reset(mark)
            return None
    # The printed order puts the duration on either side of the source clause —
    # "dealt to you **this turn** by target attacking creature" and "dealt
    # **this turn** by target sorcery spell" are the same sentence — so it is
    # read on both sides rather than the card failing on word order, exactly as
    # the blanket shield above reads its own.
    duration = _parse_duration(stream)
    dealt_by: ast.Recipient | None = None
    if stream.accept_word("by"):
        dealt_by = parse_recipient(stream) or parse_bound_subject(stream)
        if dealt_by is None:
            stream.reset(mark)
            return None
    if duration == ast.Duration():
        duration = _parse_duration(stream)
    # "…that would be dealt **this turn to target white creature you control**"
    # (Hazduhr the Abbot). The same swap on the recipient end that the two
    # readings of the duration above are on the source end — Daughter of Autumn
    # prints the identical sentence with the words the other way round — so the
    # recipient is read on either side rather than one of the two cards failing
    # on the order its printing happens to use. Exactly what
    # ``_parse_prevent_all`` does with its own recipient, and only when the
    # first reading found none: a line naming a recipient twice is not a
    # wording this reads.
    if to is None and stream.accept_word("to"):
        to = parse_recipient(stream) or parse_bound_subject(stream)
        if to is None:
            stream.reset(mark)
            return None
    if not stream.accept_phrase("is", "dealt", "to"):
        stream.reset(mark)
        return None
    new_recipient = parse_recipient(stream) or parse_bound_subject(stream)
    if new_recipient is None:
        raise stream.error("expected who takes the redirected damage")
    chooser, new_recipient = _parse_opponents_choice(stream, new_recipient)
    if not stream.accept_word("instead"):
        raise stream.error("expected 'instead' to end a redirection effect")
    return ast.RedirectDamage(
        to=to,
        new_recipient=new_recipient,
        dealt_by=dealt_by,
        duration=duration,
        chooser=chooser,
        combat_only=combat_only,
        amount=amount,
    )


def _parse_optional_damage_redirect(stream: TokenStream) -> "ast.RedirectDamage | None":
    """"If damage would be dealt to <recipients>, you may have that damage
    dealt to <recipient> instead." (Blood of the Martyr, with "Until end of
    turn," in front of it — the leading duration the statement layer
    distributes.)

    The same CR 614.9 redirection ``_parse_damage_redirect`` above reads, in the
    other printed word order and with two differences that are the whole card:
    the protected recipient is a **class** ("any creature") rather than one
    named object, and the replacement is **optional** (CR 614: "you may"). Both
    ride :class:`ast.RedirectDamage` rather than getting a node — the sentence
    is a redirect in every other respect, and a second node would be a second
    reader to keep in step.

    Non-consuming until "you may have that damage dealt to" has been read, for
    the reason the redirect above is: "If damage would be dealt to …" also opens
    a shield sentence ("…prevent that damage") that other productions claim, and
    a production that consumed the opening of every one of them would refuse
    lines with readers of their own. Past that phrase the sentence is this
    redirect and nothing else, so from there it raises.
    """
    mark = stream.mark()
    if not stream.accept_phrase("if", "damage", "would", "be", "dealt", "to"):
        stream.reset(mark)
        return None
    to = parse_recipient(stream) or parse_bound_subject(stream)
    if to is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "you", "may", "have", "that", "damage", "dealt", "to"
    ):
        stream.reset(mark)
        return None
    new_recipient = parse_recipient(stream) or parse_bound_subject(stream)
    if new_recipient is None:
        raise stream.error("expected who takes the redirected damage")
    if not stream.accept_word("instead"):
        raise stream.error("expected 'instead' to end a redirection effect")
    return ast.RedirectDamage(to=to, new_recipient=new_recipient, optional=True)


def _parse_bound_targeting_prevention(stream: TokenStream) -> "ast.PreventDamage | None":
    """"If a spell or ability that targets <bound object> would cause a source
    to deal damage to <bound object> this turn, prevent that damage."
    (Silhouette — the second sentence of a spell whose first one chose the
    object both halves name.)

    Every word is read, because each one is a way the card could mean less than
    the sentence says: "or ability" is half of what it shields against,
    "a source" is any source rather than the spell itself, and the two bound
    references have to name the *same* object — a sentence shielding one
    creature from spells aimed at another is a different card, and dropping the
    difference would shield against every targeted spell in the game.

    Non-consuming on refusal, so every other sentence opening "If …" keeps the
    ordinary conditional reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "a", "spell", "or", "ability", "that", "targets"
    ):
        stream.reset(mark)
        return None
    protected = parse_bound_subject(stream)
    if protected is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "would", "cause", "a", "source", "to", "deal", "damage", "to"
    ):
        stream.reset(mark)
        return None
    damaged = parse_bound_subject(stream)
    if damaged != protected:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    return ast.PreventDamage(
        ast.AllOf(), to=protected, duration=duration, from_targeting_source=True
    )
