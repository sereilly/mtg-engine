"""Dealing damage, and preventing it.

`<source> deals N damage to <recipients>`, its riders ("it can't be
regenerated", "if it would die this turn, exile it instead"), the
"unless they pay" variant, and the CR 615 prevention shields — a fixed amount,
all damage, or all damage from sources of one colour.

Prevention sits with damage rather than in a module of its own because the two
parse the same recipient and duration vocabulary, and a card that prevents is
always describing a damage event it expects.
"""

from .. import ast
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..nouns import (parse_player_ref, parse_recipient)
from ..stream import TokenStream
from ..vocabulary import (COLOR_WORDS)
from ..phrases import _parse_duration, _parse_mana_payment, _parse_where_x_is


# ---------------------------------------------------------------------------
# Effect productions
# ---------------------------------------------------------------------------


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
        recipient = parse_recipient(stream)
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
    elif not stream.at_word("it"):
        stream.reset(mark)
        return None

    while True:
        if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
            "it", "cannot", "be", "regenerated"
        ):
            _parse_duration(stream)
            no_regen = True
        elif stream.accept_phrase("if", "it", "would", "die"):
            _parse_duration(stream)
            stream.accept_punct(",")
            if stream.accept_phrase("exile", "it", "instead"):
                exile_if_dies = True
            else:
                stream.reset(mark)
                return None
        else:
            break
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
    if not stream.accept_phrase("the", "next", "time", "a"):
        stream.reset(mark)
        return None
    colour = None
    token = stream.peek()
    if token is not None and str(token.text).lower() in COLOR_WORDS:
        colour = COLOR_WORDS[str(stream.next().text).lower()]
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
    filt = ast.ObjectFilter(colors=(colour,)) if colour else ast.ObjectFilter()
    return ast.PreventDamage(ast.Fixed(1), to=recipient, from_filter=filt)
