"""Damage **moved or changed** rather than stopped (CR 614).

The other half of the family ``prevention`` names. Both modules read one
printed sentence about a damage event that will not happen as announced; the
line between them is CR 615's: a shield removes the damage, and everything
here leaves it happening and changes one of its terms — its recipient
(Shimian Night Stalker, Blood of the Martyr), what it becomes (Soul Echo's
counters), or how much of it there is (Blind Fury's doubling).

**The name is the lowering side's**, which has carried it since it split off
``lowering/damage.py``: all four productions below lower in
``lowering/redirection.py`` and none of them lowers in ``lowering/prevention.py``,
so the mirror re-forms rather than forking a third vocabulary. That the parse
halves sat in ``prevention`` while their lowering halves sat here is the
asymmetry this split closes.

What does **not** move is ``_parse_source_of_choice_effect``. It reads CR
615.8's seven opening words and returns *either* node — a shield if the clause
after the comma prevents, a redirect if it moves the damage (Nova Pentacle) —
so a module holding half of it would import the other half, which is the
coupling the family rule exists to prevent. One printed sentence, one
production, and the family it lives in is the one the pool mostly prints.
There is no import between the two modules in either direction.
"""

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..lexer import NUMBER
from ..readers import accept_source_reference
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream
from ..phrases import (_parse_duration, _parse_opponents_choice,
                       parse_bound_subject)


def _parse_damage_becomes_counter_removal(
    stream: TokenStream,
) -> "ast.DamageBecomesCounterRemoval | None":
    """``For each 1 damage that would be dealt to <player> <duration>, <player>
    remove(s) a <kind> counter from <source> instead.`` (Soul Echo.)

    CR 614's replacement, tried beside the redirect below because it is the
    same kind of sentence — one *about* a damage event rather than one dealing
    damage — and refused without consuming for the same reason: "For each …"
    opens the ordinary per-object loop too, and a production that ate its first
    two words would take every one of those lines with it.

    Both halves of the sentence name the same player, and both are required to
    agree: an effect draining one player's counters for damage dealt to another
    is a card this does not implement, and admitting it with the second player
    dropped is how the wrong seat pays.

    The **source is the ability's own permanent**, which every printing of this
    sentence says out loud. It has to be: the counters and the sacrifice that
    reads them are the same card's, and a wording naming another permanent
    would be a store nothing in this effect can find.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    # The printed "1" is a NUMBER token, not a word — and it is required
    # rather than read as a quantity: this replacement removes one counter per
    # point, and a card printing "for each 2 damage" would be a different
    # exchange rate the handler does not carry.
    one = stream.peek()
    if one is None or one.kind != NUMBER or one.text != "1":
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("damage", "that", "would", "be", "dealt", "to"):
        stream.reset(mark)
        return None
    recipient = parse_player_ref(stream)
    if recipient is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    payer = parse_player_ref(stream)
    if payer is None or payer.kind != recipient.kind:
        stream.reset(mark)
        return None
    if not stream.accept_word("removes", "remove"):
        stream.reset(mark)
        return None
    if not stream.accept_word("a", "an"):
        stream.reset(mark)
        return None
    counter = stream.peek_word()
    if counter is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("counter", "counters"):
        stream.reset(mark)
        return None
    if not stream.accept_word("from"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    # "…**instead**" is CR 614's word and the whole difference from a
    # prevention, so it is required rather than optional: without it the
    # sentence says the counter comes off *as well as* the damage.
    if not stream.accept_word("instead"):
        stream.reset(mark)
        return None
    return ast.DamageBecomesCounterRemoval(recipient, str(counter), duration)


def _parse_double_combat_damage(stream: TokenStream) -> "ast.DoubleCombatDamage | None":
    """``If a creature would deal combat damage to a creature this turn, it
    deals double that damage to that creature instead.`` (Blind Fury —
    CR 614.)

    Beside the redirect below rather than in a family of its own, for this
    module's own stated reason: one printed sentence returns either node, and
    two parse modules would be one importing the other.

    **Every word is required**, and each is a narrowing the interceptor tests:
    "combat" (a ping ability is not), "a creature" on each end (the face is not,
    which is what makes this a trick for blockers rather than a burn spell), and
    "this turn". A wording that dropped any of them would be a different card
    wearing this one's head, so the production refuses rather than reading it as
    this one — and refuses **without consuming**, so every other "If a creature
    would …" sentence keeps the reader it has.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "a", "creature", "would", "deal", "combat", "damage", "to",
        "a", "creature", "this", "turn",
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "it", "deals", "double", "that", "damage", "to", "that", "creature",
        "instead",
    ):
        stream.reset(mark)
        return None
    return ast.DoubleCombatDamage()


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
