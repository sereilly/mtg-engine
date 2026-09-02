"""Dealing damage.

`<source> deals N damage to <recipients>`, its riders ("it can't be
regenerated", "if it would die this turn, exile it instead"), the "unless they
pay" variant, the fight (CR 701.14), and Runesword's grant of those riders to a
creature for the turn.

Prevention and redirection used to sit here, on the argument that they parse the
same recipient and duration vocabulary. They are `prevention.py` now: the
argument was true and the module still reached 1,000 lines, which is the guard
saying the family stopped absorbing new work. The line between them is the CR's
— everything here *deals* damage, and everything there stops it or moves it.
"""

import dataclasses

from .. import ast
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..readers import accept_source_reference_spec
from ..references import parse_player_ref, parse_recipient
from ..lexer import WORD
from ..stream import TokenStream
from ..where_x import _parse_where_x_is
from ..phrases import (
    _accept_mana_alternatives,
    _parse_duration, _parse_mana_payment, _parse_opponents_choice,
    _parse_per_each_objects, _parse_that_object, accept_or_planeswalker,
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
    # "target player **or planeswalker**" (Chandra's Magmutt). Two words behind
    # the noun phrase, read by ``phrases`` because prevention prints them too
    # (Wandering Mage) and the two families may not import each other.
    widened = accept_or_planeswalker(stream, recipient)
    if widened is not recipient:
        return widened
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
    recipients = [recipient]
    while True:
        mark = stream.mark()
        if not stream.accept_word("and"):
            break
        extra = parse_recipient(stream)
        if extra is None or not _ends_the_recipient_list(stream):
            stream.reset(mark)
            break
        recipients.append(extra)
    return recipients


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
        evenly = bool(stream.accept_word("evenly"))
        stream.accept_punct(",")
        rounding = ""
        if stream.accept_word("rounded"):
            rounding = stream.accept_word("down", "up") or ""
        riders = ast.DamageRiders(
            divided=True, divided_evenly=evenly, rounding=rounding,
        )
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
        recipients.extend(_parse_recipient_list(stream))

    if deferred_amount:
        found = parse_equal_to(stream)
        if found is None:
            raise stream.error("expected 'equal to' quantity for damage")
        amount = found
        # "deals damage equal to its power **to another target creature**"
        # (Garruk, Savage Herald's −2) — this word order puts the recipient
        # after the amount clause rather than before it.
        if not recipients and stream.accept_word("to"):
            # The **same** list reader the other word order uses, and that is
            # the point: this branch read one recipient and stopped, so "deals
            # damage equal to the number of time counters on it to each
            # creature **and each player**" (Time Bomb) stranded half its
            # recipients and failed the line. A recipient list is a property of
            # the clause, not of which side of it the quantity was printed on.
            recipients.extend(_parse_recipient_list(stream))

    # "deals X damage to that player, where X is <count>" — the trailer *is* the
    # quantity, so it replaces the variable rather than riding alongside it.
    # Only an X can be bound this way; a clause with a literal amount followed
    # by "where X is …" would be talking about some other X.
    if isinstance(amount, ast.Var):
        bound = _parse_where_x_is(stream)
        if bound is not None:
            amount = bound

    # "…deals 2 damage to each creature **for each Aura attached to that
    # creature**." (Baki's Curse.) A multiplier on the printed amount, read
    # through the one reader that reads this clause — `phrases`, where it moved
    # the day this became its second caller. "…beyond the first" comes back
    # from it and is refused rather than dropped: it discounts the *set* being
    # counted, and no damage handler applies that, so a clause printing it
    # would deal one repetition too many on every recipient.
    per_each, per_each_beyond_first = _parse_per_each_objects(stream)
    if per_each_beyond_first:
        raise stream.error("no damage clause discounts the first of a counted set")

    first = ast.DealDamage(
        source, amount, tuple(recipients), riders, chooser, per_each
    )

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
            # The **same** list reader the first clause uses, and for the same
            # reason the deferred-amount branch above was made to share it:
            # this read one recipient and stopped, so "deals 2 damage to each
            # attacking creature and 1 damage to you **and each creature you
            # control**" (Hail Storm) stranded the third recipient and failed
            # the whole line. A recipient list is a property of a damage
            # clause, not of whether it is the first one in the sentence.
            second_recipients = _parse_recipient_list(stream)
            # "…of an opponent's choice" rides the recipient it was printed
            # after, so it is lifted off the last of them — the only position
            # the rider can occupy — and the rest of the list is untouched.
            second_chooser, lifted = _parse_opponents_choice(
                stream, second_recipients[-1]
            )
            if lifted is not None:
                second_recipients[-1] = lifted
            second = ast.DealDamage(
                source, second_amount, tuple(second_recipients),
                ast.DamageRiders(), second_chooser,
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
    cost = _parse_mana_payment(stream)
    # "…unless they pay {B} **or {3}**" (Lim-Dûl's Hex). CR 118.8's alternative,
    # which the fused node cannot carry — it holds one cost, and both engine
    # flows behind it charge one number. So the clause decomposes into the
    # ``May`` an "unless" already is, exactly as the sacrifice alternative above
    # does and for the same reason: the offer, the penalty and the "they can
    # afford neither" case all come from machinery that already works.
    #
    # Only when an alternative is printed, so Force of Nature and Hasran Ogress
    # keep the fused node the upkeep dispatcher and the optional-pay prompt
    # implement whole.
    alternatives = _accept_mana_alternatives(stream)
    if alternatives:
        return ast.May(
            actor=payer, cost=cost, cost_alternatives=alternatives,
            otherwise=damage,
        )
    return ast.DamageUnlessPay(damage, payer, cost)


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

    if _accept_damaged_this_way_no_regen(stream):
        return ast.DamageRiders(no_regen=True)

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


def _accept_damaged_this_way_no_regen(stream: TokenStream) -> bool:
    """``A creature dealt damage this way can't be regenerated [this turn].``
    (Incinerate.)

    CR 701.19c's rider written as a sentence about the *effect* rather than
    about a pronoun — the damage twin of ``board.py``'s "A <noun> destroyed
    this way can't be regenerated", and it exists for the same reason: by the
    time the sentence is read there is no "it" left in the reader's hand, so
    the noun restates what the damage already named.

    The noun is **only** "creature", and the single-word set is the honest one
    rather than a stub of a wider one. It is what the rider means: regeneration
    replaces a destruction (CR 701.19a), and the payload key it sets is read at
    the damage handler under an ``is_creature`` test. A card printed "a
    permanent dealt damage this way" would be admitted here and then silently
    skipped there for every non-creature it hit, which is the drop this
    grammar's closed sets exist to prevent.
    """
    mark = stream.mark()
    if (
        stream.accept_word("a", "an")
        and stream.accept_word("creature")
        and stream.accept_phrase("dealt", "damage", "this", "way")
        and stream.accept_phrase("can't", "be", "regenerated")
    ):
        _parse_duration(stream)
        return True
    stream.reset(mark)
    return False


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
    # Through the spec reader rather than the predicate, so **which word was
    # printed** survives: a bare "it" is a pronoun and, under a trigger whose
    # condition named an object, means that object (CR 109.5 names the source;
    # the pronoun does not). "Its controller may have **it** deal damage equal
    # to its power" on an Aura (Farrel's Mantle) is the enchanted creature —
    # collapsed to "this", the Aura itself would have dealt the damage, and an
    # Aura's power is nothing at all.
    biter = accept_source_reference_spec(stream)
    if biter is None:
        stream.reset(mark)
        return None
    if not stream.at_word("deal", "deals"):
        stream.reset(mark)
        return None
    return _parse_damage(stream, biter)


#: How Runesword's two sentences name the creature its own ability targeted.
#: Longest first, because "the creature" is a prefix of "the targeted creature"
#: and a first-match reader would take the shorter one and then fail on the
#: leftover word.
_ABILITY_TARGET_REFERENTS: tuple[tuple[str, ...], ...] = (
    ("the", "targeted", "creature"),
    ("the", "creature"),
)


def _accept_ability_target(stream: TokenStream) -> bool:
    """``the creature`` / ``the targeted creature`` — the creature this same
    ability already chose (CR 601.2c), not a new target."""
    for phrase in _ABILITY_TARGET_REFERENTS:
        mark = stream.mark()
        if stream.accept_phrase(*phrase):
            return True
        stream.reset(mark)
    return False


def _parse_damage_dealt_riders(stream: TokenStream) -> "ast.DamageRidersUntilEndOfTurn | None":
    """Runesword's two trailing sentences:

    ``If the creature deals damage to a creature this turn, the creature dealt
    damage can't be regenerated this turn.``
    ``If a creature dealt damage by the targeted creature would die this turn,
    exile that creature instead.``

    Both open like a conditional and neither is one. Nothing is tested when the
    ability resolves: what they create is a standing property of the creature
    the ability targeted, so that damage it deals for the rest of the turn
    carries the two riders `Disintegrate` applies to one event of its own. That
    is the same shape as ``_parse_bound_targeting_prevention`` (Silhouette),
    read in the same position and for the same reason — the generic conditional
    below would take the clause as an intervening-if over a sentence it has no
    production for.

    Returns None with the cursor untouched for every other "If …", so a
    sentence this is not keeps the refusal it already had.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    if _accept_ability_target(stream):
        if not stream.accept_phrase(
            "deals", "damage", "to", "a", "creature", "this", "turn"
        ):
            stream.reset(mark)
            return None
        stream.accept_punct(",")
        # The victim is named again — "**the creature dealt damage**" — and the
        # words are consumed rather than skipped: they say which creature of the
        # event carries the rider, and a reader that dropped them would put it
        # on whichever one it happened to hold.
        if not stream.accept_phrase(
            "the", "creature", "dealt", "damage", "can't", "be", "regenerated"
        ):
            stream.reset(mark)
            return None
        _parse_duration(stream)
        return ast.DamageRidersUntilEndOfTurn(
            "ability_target", ast.DamageRiders(no_regen=True)
        )
    if not stream.accept_phrase("a", "creature", "dealt", "damage", "by"):
        stream.reset(mark)
        return None
    if not (
        _accept_ability_target(stream)
        and stream.accept_phrase("would", "die")
    ):
        stream.reset(mark)
        return None
    _parse_duration(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("exile", "that", "creature", "instead"):
        stream.reset(mark)
        return None
    return ast.DamageRidersUntilEndOfTurn(
        "ability_target", ast.DamageRiders(exile_if_dies=True)
    )
