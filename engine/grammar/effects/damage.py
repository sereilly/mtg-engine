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
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS)
from ..phrases import _parse_duration, _parse_mana_payment, _parse_where_x_is


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
        and recipient.kind == "target_player"
        and stream.accept_phrase("or", "planeswalker")
    ):
        return ast.PlayerRef("target_player", or_planeswalker=True)
    return recipient


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

    recipients: list[ast.Recipient] = []
    chooser: ast.PlayerRef | None = None
    if stream.accept_word("to"):
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
    if stream.accept_word("and"):
        try:
            second_amount = parse_amount(stream)
            stream.expect_word("damage")
            stream.expect_word("to")
            second_recipient = parse_recipient(stream)
            if second_recipient is None:
                raise stream.error("expected a damage recipient")
            second_chooser: ast.PlayerRef | None = None
            if stream.accept_phrase("of", "an", "opponent", "'s", "choice"):
                second_chooser = ast.PlayerRef("target_opponent")
            second = ast.DealDamage(
                source, second_amount, (second_recipient,), ast.DamageRiders(), second_chooser
            )
            return ast.Conjunction((first, second))
        except GrammarError:
            stream.reset(mark)

    return first


def _parse_damage_unless_pay(
    stream: TokenStream, damage: ast.DealDamage
) -> ast.DamageUnlessPay | None:
    """``… unless <player> pays <cost>`` trailing a damage clause.

    The mana payment is *expected* once "unless … pay" has matched: an
    unrecognized cost raises out of ``_parse_mana_payment`` rather than
    rewinding, because a card that offers a cost the grammar cannot read is a
    card whose damage is conditional on something unmodelled — silently
    dropping the condition would make the damage unconditional, which is the
    strictly worse of the two failures.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None:
        stream.reset(mark)
        return None
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
    if stream.accept_word("to"):
        recipient = parse_recipient(stream)
        if recipient is None:
            raise stream.error("expected something to shield")
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
    return ast.PreventDamage(
        ast.AllOf(), to=recipient, duration=duration, combat_only=combat_only
    )


def _parse_colour_source_prevention(stream: TokenStream) -> ast.PreventDamage | None:
    """"The next time a <colour> source of your choice would deal damage to you
    this turn, prevent that damage." — the Circles of Protection, and Reverse
    Damage with no colour word.

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
    colour = None
    card_type = None
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word in COLOR_WORDS:
        colour = COLOR_WORDS[word]
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
    _parse_duration(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    if colour:
        filt = ast.ObjectFilter(colors=(colour,))
    elif card_type:
        filt = ast.ObjectFilter(card_types=(card_type,))
    else:
        filt = ast.ObjectFilter()
    return ast.PreventDamage(ast.Fixed(1), to=recipient, from_filter=filt)
