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
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES, COLOR_WORDS
from ..phrases import _parse_duration, _parse_opponents_choice, parse_bound_subject


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
    if not stream.accept_phrase("that", "would", "be", "dealt", "to"):
        raise stream.error("expected 'that would be dealt to'")
    recipient = parse_recipient(stream)
    if recipient is None:
        raise stream.error("expected something to shield")
    duration = _parse_duration(stream)
    return ast.PreventDamage(amount, to=recipient, duration=duration)


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
    if not (stream.accept_word("a") or stream.accept_word("an")):
        stream.reset(mark)
        return None
    colours: list[str] = []
    card_type = None
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
    if not stream.accept_phrase("of", "your", "choice", "would", "deal", "damage", "to"):
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
        if colours or card_type:
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
    for word in (
        "can't", "be", "prevented", "or", "dealt", "instead", "to", "another",
        "permanent", "or", "player",
    ):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    return ast.DamageCantBePreventedOrRedirected(subject, duration)


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
    """
    mark = stream.mark()
    if not stream.accept_word("all"):
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
