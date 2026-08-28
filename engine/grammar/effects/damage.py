"""Dealing damage, and preventing it.

`<source> deals N damage to <recipients>`, its riders ("it can't be
regenerated", "if it would die this turn, exile it instead"), the
"unless they pay" variant, and the CR 615 prevention shields — a fixed amount,
all damage, or all damage from sources of one colour.

Prevention sits with damage rather than in a module of its own because the two
parse the same recipient and duration vocabulary, and a card that prevents is
always describing a damage event it expects.
"""

import dataclasses

from .. import ast
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..readers import accept_source_reference
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS)
from ..where_x import _parse_where_x_is
from ..phrases import (
    _parse_duration, _parse_mana_payment, _parse_that_object,
    parse_bound_subject,
)


# ---------------------------------------------------------------------------
# Effect productions
# ---------------------------------------------------------------------------


def _parse_damage_recipient(stream: TokenStream) -> ast.Recipient | None:
    """A damage recipient, plus the one union only damage prints: "target
    player or planeswalker" (Chandra's Magmutt). Read here rather than in
    ``parse_player_ref`` so the flag exists only where the damage lowering —
    the one consumer that honours it — can receive it."""
    recipient = parse_recipient(stream)
    if (
        isinstance(recipient, ast.PlayerRef)
        # "target **opponent** or planeswalker" (Eternal Flame) is the same
        # union with the caster's own seat struck out of it (CR 115.4). Read
        # from the same two words rather than as a second production, because
        # the difference is entirely in which seats answer the player half —
        # a narrowing the recipient already carries.
        and recipient.kind in ("target_player", "target_opponent")
        and stream.accept_phrase("or", "planeswalker")
    ):
        return ast.PlayerRef(recipient.kind, or_planeswalker=True)
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
    return recipient


def _accept_rounding_rider(stream: TokenStream, amount: ast.Amount) -> ast.Amount:
    """``[,] rounded up|down [,]`` printed *after* the word "damage".

    ``amounts.parse_amount`` already reads "half X, rounded down" — the order
    Backdraft prints, where the rider sits against the quantity. A damage clause
    prints it on the other side of the noun ("half X **damage**, rounded up",
    Banshee, Eternal Flame), so the same rider has to be read here as well; the
    quantity parser cannot, because by then it has handed back a `Half` whose
    rounding defaulted.

    That default is why this refuses a rider on anything else. ``ast.Half``
    starts at "down", so a "rounded up" landing on a quantity that is not a half
    would be silently discarded and the card would deal the rounded-*down*
    amount while reporting itself supported.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_word("rounded"):
        stream.reset(mark)
        return amount
    if stream.accept_word("up"):
        rounding = "up"
    elif stream.accept_word("down"):
        rounding = "down"
    else:
        raise stream.error("expected 'up' or 'down' after 'rounded'")
    if not isinstance(amount, ast.Half):
        raise stream.error("a rounding rider needs a halved quantity")
    stream.accept_punct(",")
    return dataclasses.replace(amount, rounding=rounding)


def _parse_fight(stream: TokenStream, subject: ast.Recipient) -> ast.Fight:
    """``<subject> fights <opponent>.`` (CR 701.14 — Brash Taunter, Primal Might.)

    "Another" is consumed here and folded onto the opponent's filter, the idiom
    the cost parser and the trigger subjects already use; CR 701.14c allows a
    creature to fight itself, so the word is a *restriction* the card printed
    rather than something the rule requires.
    """
    stream.expect_word("fights", "fight")
    another = bool(stream.accept_word("another"))
    opponent = parse_recipient(stream)
    if opponent is None:
        raise stream.error("expected a creature to fight")
    if another and isinstance(opponent, ast.TargetSpec):
        opponent = dataclasses.replace(
            opponent,
            filter=dataclasses.replace(opponent.filter, other_than_source=True),
        )
    return ast.Fight(subject, opponent)


def _parse_damage(stream: TokenStream, source: ast.TargetSpec | None) -> ast.Statement:
    """``<source> deals <amount> damage to <recipients> [riders]``.

    Also covers the two-recipient conjunction ("… and 3 damage to you") that the
    legacy rules encoded as the standalone kinds ``deal_damage_and_self_damage``
    and ``deal_damage_and_opponent_choice`` — here it is just an ``and``.
    """
    stream.expect_word("deals", "deal")

    riders = ast.DamageRiders()
    # "deals damage to X equal to N" puts the quantity after the recipient.
    deferred_amount = False
    if stream.at_word("damage"):
        deferred_amount = True
        amount: ast.Amount = ast.Fixed(0)
    else:
        amount = parse_amount(stream)
        # "…deals **X plus 3** damage to you" (Hellfire). A printed sum, read
        # here rather than folded to a number because the left half is usually
        # not one yet — the same reason `effects/characteristics.py` reads
        # "1 plus the number of …" into an `ast.Plus` instead of adding it up.
        if stream.accept_word("plus"):
            amount = ast.Plus(amount, parse_amount(stream))
    stream.expect_word("damage")

    if stream.accept_word("divided"):
        if stream.accept_word("evenly"):
            riders = ast.DamageRiders(divided=True, divided_evenly=True)
        else:
            riders = ast.DamageRiders(divided=True)
        stream.accept_punct(",")
        if stream.accept_word("rounded"):
            stream.accept_word("down", "up")
        stream.accept_punct(",")
        if stream.accept_word("among", "between"):
            stream.accept_phrase("any", "number", "of")
            recipient = parse_recipient(stream)
            if recipient is None:
                raise stream.error("expected damage recipients")
            return ast.DealDamage(source, amount, (recipient,), riders)
        if stream.accept_phrase("as", "you", "choose", "among"):
            recipient = parse_recipient(stream)
            if recipient is None:
                raise stream.error("expected damage recipients")
            return ast.DealDamage(source, amount, (recipient,), riders)
        raise stream.error("expected 'among' after divided damage")

    amount = _accept_rounding_rider(stream, amount)

    recipients: list[ast.Recipient] = []
    chooser: ast.PlayerRef | None = None
    if stream.accept_word("to"):
        # "…to **each opponent and planeswalker it has dealt damage to this
        # game**." (The Fallen.) Probed before the ordinary recipient parser,
        # which reads "each opponent" happily and then leaves the rest of the
        # phrase as unconsumed text — the narrowing is not a description of a
        # board, so no filter it could build would carry it.
        history = _accept_damaged_this_game(stream)
        if history is not None:
            return ast.DamageThoseDamagedThisGame(source, amount, history)
        recipient = _parse_damage_recipient(stream)
        if recipient is None:
            raise stream.error("expected a damage recipient")
        recipients.append(recipient)
        # "each creature with flying and each player" is one recipient list,
        # not a second damage event.
        while True:
            mark = stream.mark()
            if not stream.accept_word("and"):
                break
            extra = parse_recipient(stream)
            if extra is None:
                stream.reset(mark)
                break
            recipients.append(extra)

    if deferred_amount:
        found = parse_equal_to(stream)
        if found is None:
            raise stream.error("expected 'equal to' quantity for damage")
        amount = found
        # "deals damage equal to its power **to another target creature**"
        # (Garruk, Savage Herald's −2) — this word order puts the recipient
        # after the amount clause rather than before it.
        if not recipients and stream.accept_word("to"):
            # Through `_parse_damage_recipient`, not `parse_recipient`: this
            # word order missed the "or planeswalker" union, so "deals damage
            # equal to its power to target player **or planeswalker**" failed on
            # the two words the other word order reads.
            recipient = _parse_damage_recipient(stream)
            if recipient is None:
                raise stream.error("expected a damage recipient")
            recipients.append(recipient)

    # "deals X damage to that player, where X is <count>" — the trailer *is* the
    # quantity, so it replaces the variable rather than riding alongside it.
    # Only an X can be bound this way; a clause with a literal amount followed
    # by "where X is …" would be talking about some other X.
    if isinstance(amount, ast.Var):
        bound = _parse_where_x_is(stream)
        if bound is not None:
            amount = bound

    first = ast.DealDamage(source, amount, tuple(recipients), riders, chooser)

    # "… unless you pay {2}" — the cost is the alternative to the damage, not a
    # step alongside it, so it is read here and kept fused (see ast.DamageUnlessPay).
    unless = _parse_damage_unless_pay(stream, first)
    if unless is not None:
        return unless

    # A second damage clause sharing the same source: "… and 3 damage to you".
    mark = stream.mark()
    # "…to any target**,** and half X damage, rounded up, to you" (Banshee).
    # The comma is the Oxford separator this printing uses and nothing else in
    # the sentence needs it; consumed inside the mark, so a comma introducing
    # some other clause is put back with the rest of the failed probe.
    stream.accept_punct(",")
    if stream.accept_word("and"):
        try:
            second_amount = parse_amount(stream)
            stream.expect_word("damage")
            second_amount = _accept_rounding_rider(stream, second_amount)
            stream.expect_word("to")
            second_recipient = parse_recipient(stream)
            if second_recipient is None:
                raise stream.error("expected a damage recipient")
            second_chooser, second_recipient = _parse_opponents_choice(
                stream, second_recipient
            )
            second = ast.DealDamage(
                source, second_amount, (second_recipient,), ast.DamageRiders(), second_chooser
            )
            # The trailing "…, where X is the number of Mountains you control"
            # (Eternal Flame) is *not* read here. It defines the X both halves
            # spend, and `statements.py` already wraps the whole sentence in a
            # `WhereX` for exactly that reason — a binder here would consume the
            # same clause one conjunct early and bind only the half it saw.
            return ast.Conjunction((first, second))
        except GrammarError:
            stream.reset(mark)

    return first


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


def _parse_damage_unless_pay(
    stream: TokenStream, damage: ast.DealDamage
) -> "ast.Statement | None":
    """``… unless <player> pays <cost>`` / ``… unless <player> sacrifices
    <object>`` trailing a damage clause.

    The mana payment is *expected* once "unless … pay" has matched: an
    unrecognized cost raises out of ``_parse_mana_payment`` rather than
    rewinding, because a card that offers a cost the grammar cannot read is a
    card whose damage is conditional on something unmodelled — silently
    dropping the condition would make the damage unconditional, which is the
    strictly worse of the two failures.

    The **sacrifice** alternative decomposes into ``May(action=…,
    otherwise=…)`` rather than growing a second fused node, exactly as the two
    "unless you sacrifice" tails in the board family do (Psychic Allergy, Mold
    Demon): an "unless" is an offer with a penalty, which is what ``May``
    already says, and saying it that way means the offer, the penalty and the
    "there is nothing to give up" case all come from machinery that works. The
    mana spelling above stays fused only because two upkeep handlers implement
    it whole.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None:
        stream.reset(mark)
        return None
    # "…unless they **sacrifice that artifact**" (Curse Artifact). The object is
    # the one the trigger already named, read through the shared bound-object
    # fragment so the two families cannot come to disagree about what "that
    # artifact" is — and refused when the words after the verb are something
    # else, rather than silently sacrificing a chosen permanent.
    if stream.accept_word("sacrifices", "sacrifice"):
        subject = _parse_that_object(stream)
        if subject is None:
            stream.reset(mark)
            return None
        return ast.May(
            actor=payer,
            action=ast.Sacrifice(payer, subject),
            otherwise=damage,
        )
    if not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    return ast.DamageUnlessPay(damage, payer, _parse_mana_payment(stream))


def _parse_damage_rider_sentence(stream: TokenStream) -> ast.DamageRiders | None:
    """Disintegrate's trailing sentence: "If it's a creature, it can't be
    regenerated this turn, and if it would die this turn, exile it instead."

    Modeled as riders on the preceding damage rather than as its own effect —
    which is what it is. The legacy compiler matched this by whole-sentence
    substring; here the shape is parsed so a card with only one of the two
    riders still works.
    """
    mark = stream.mark()
    no_regen = False
    exile_if_dies = False

    if stream.accept_phrase("if", "it", "'s", "a", "creature"):
        stream.accept_punct(",")
    elif not stream.at_word("it", "if"):
        stream.reset(mark)
        return None

    def _that_object_would_die() -> bool:
        """``if that creature [or planeswalker] would die`` — the modern
        templating of Disintegrate's ``if it would die`` (Scorching
        Dragonfire). "That <types>" names the damage target the sentence
        before this one chose; the type words are consumed against the same
        closed set the noun parser reads, so a rider on something never
        damaged cannot be claimed."""
        probe = stream.mark()
        if not stream.accept_word("that"):
            return False
        if not stream.accept_word("creature", "planeswalker", "permanent"):
            stream.reset(probe)
            return False
        if stream.accept_word("or") and not stream.accept_word(
            "creature", "planeswalker", "permanent"
        ):
            stream.reset(probe)
            return False
        if not stream.accept_phrase("would", "die"):
            stream.reset(probe)
            return False
        return True

    while True:
        if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
            "it", "cannot", "be", "regenerated"
        ):
            _parse_duration(stream)
            no_regen = True
        else:
            probe = stream.mark()
            matched_die = stream.accept_phrase("if", "it", "would", "die")
            if not matched_die and stream.accept_word("if"):
                matched_die = _that_object_would_die()
            if not matched_die:
                stream.reset(probe)
                break
            _parse_duration(stream)
            stream.accept_punct(",")
            if stream.accept_phrase("exile", "it", "instead"):
                exile_if_dies = True
            else:
                stream.reset(mark)
                return None
        stream.accept_punct(",")
        stream.accept_word("and")

    if not (no_regen or exile_if_dies):
        stream.reset(mark)
        return None
    return ast.DamageRiders(no_regen=no_regen, exile_if_dies=exile_if_dies)


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


def _parse_opponents_choice(
    stream: TokenStream, recipient: "ast.Recipient | None" = None
) -> "tuple[ast.PlayerRef | None, ast.Recipient | None]":
    """"…of an opponent's choice" — the rider that hands the pick to the other
    seat, and the recipient with the rider lifted off it.

    Two spellings reach here, and they are the same three words. The rider may
    still be sitting in the stream (nothing else claimed it), or the noun parser
    may already have consumed it as part of the noun phrase — which is what it
    does when the phrase continues, as "target creature of an opponent's choice
    **they control**" (Preacher) does. One reader either way: two productions
    racing on one phrase is how Nova Pentacle's chooser came to be dropped the
    day the noun parser learned the longer form.

    The flag is *lifted*, not copied: it is not a property of any candidate, and
    every lowering downstream refuses a filter still carrying it rather than
    letting the wrong seat choose.
    """
    if stream.accept_phrase("of", "an", "opponent", "'s", "choice"):
        return ast.PlayerRef("target_opponent"), recipient
    filt = getattr(recipient, "filter", None)
    if filt is not None and getattr(filt, "chosen_by_opponent", False):
        return (
            ast.PlayerRef("target_opponent"),
            dataclasses.replace(
                recipient,
                filter=dataclasses.replace(filt, chosen_by_opponent=False),
            ),
        )
    return None, recipient


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
    if not stream.accept_phrase("all", "damage", "that", "would", "be", "dealt"):
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
    )


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


def _parse_have_source_deal_damage(stream: TokenStream) -> "ast.Statement | None":
    """``have <source> deal <amount> damage to <recipient>`` (Worms of the Earth).

    The same event as "<source> deals <amount> damage to <recipient>" printed as
    something a *player chooses to do* rather than something that happens, which
    is why it is a branch in front of `_parse_damage` and not a node of its own:
    the effect, the riders and the recipients are read by the one production, so
    the alternative a player picks and the damage the engine deals cannot come to
    describe different events.

    Only the ability's own source may be named. A sentence handing a third
    object the verb would be an effect this reading has nothing to point at, so
    it refuses without consuming and every other "have …" sentence keeps its own
    reading.
    """
    mark = stream.mark()
    if not stream.accept_word("have"):
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.at_word("deal", "deals"):
        stream.reset(mark)
        return None
    return _parse_damage(stream, ast.TargetSpec("this", ast.ObjectFilter(is_source=True)))
