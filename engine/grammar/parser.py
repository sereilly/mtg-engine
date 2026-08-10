"""Recursive-descent parser for oracle-text ability lines.

Precedence here is *structural*, not numeric. The legacy registry gave every
rule a hand-picked global order integer and ran a linear first-match scan, so
"destroy all creatures" had to be given a lower number than "destroy target
creature" and every new rule author had to reason about the whole ordering
space. In a grammar the same distinction falls out of the noun parser
returning ``quantifier="all"`` versus ``"target"`` from one ``destroy``
production — there is nothing to order.

The controlling invariant is **full token consumption**: a production that
matches must account for every token of its line. Leftover tokens raise
``GrammarError``. That is what makes "parsed" mean "understood in full", and it
is the structural fix for the dropped-rider bug class the parse-coverage
deletion probe was built to detect empirically.
"""

from __future__ import annotations

from . import ast
from .amounts import expect_pt, parse_amount, parse_equal_to
from .errors import GrammarError
from .lexer import (
    BULLET, DASH, GToken, MANA, PT, PUNCT, QUOTE, SELF, WORD, render, tokenize,
)
from .nouns import (
    parse_object_filter,
    parse_player_ref,
    parse_recipient,
    parse_target_spec,
)
from .registries import registry_for_line
from .stream import TokenStream
from .vocabulary import (
    CARD_TYPES,
    COLOR_WORDS,
    KEYWORD_INDEX,
    SUBTYPE_INDEX,
    match_longest,
)

# Trigger-event tables. The kind strings deliberately match the legacy
# compiler's (engine/oracle.py WHENEVER/WHEN/AT tables) so the 23 existing
# `condition_kinds=` dispatch sites keep working while migration is in flight.
_WHENEVER_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_dies", ("a", "land", "is", "put", "into", "a", "graveyard", "from", "the", "battlefield")),
    ("creature_you_control_dies", ("a", "creature", "you", "control", "dies")),
    # Longer phrases first: this list is matched in order, so a prefix entry
    # would claim the shorter reading and strand the rest of the clause.
    ("creature_dealt_damage_by_self_dies",
     ("a", "creature", "dealt", "damage", "by", "this", "creature", "this", "turn", "dies")),
    ("creature_dies", ("a", "creature", "dies")),
    ("creature_deals_combat_damage", ("this", "creature", "deals", "combat", "damage", "to", "a", "player")),
    ("creature_deals_damage", ("this", "creature", "deals", "damage")),
    ("creature_attacks_or_blocks", ("this", "creature", "attacks", "or", "blocks")),
    ("creature_attacks", ("this", "creature", "attacks")),
    ("creature_blocks", ("this", "creature", "blocks")),
    ("creature_becomes_blocked", ("this", "creature", "becomes", "blocked")),
    ("creature_dealt_damage", ("this", "creature", "is", "dealt", "damage")),
    ("enchanted_land_tapped", ("enchanted", "land", "becomes", "tapped")),
    ("self_becomes_tapped", ("this", "land", "becomes", "tapped")),
    ("land_tapped_for_mana", ("a", "player", "taps", "a", "land", "for", "mana")),
    ("spell_cast", ("a", "player", "casts", "a", "spell")),
    ("opponent_casts_spell", ("an", "opponent", "casts", "a", "spell")),
    ("enchantment_cast", ("you", "cast", "an", "enchantment", "spell")),
    ("you_cast_spell", ("you", "cast", "a", "spell")),
    ("creature_enters", ("a", "creature", "enters")),
    ("land_enters", ("a", "land", "enters")),
    ("artifact_enters", ("an", "artifact", "enters")),
    ("draws_card", ("you", "draw", "a", "card")),
)

_AT_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("upkeep_self", ("the", "beginning", "of", "your", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "player", "'s", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "upkeep")),
    # An Aura firing on the upkeep of whoever controls what it enchants
    # (Feedback, Wanderlust, Warp Artifact). Written out per enchanted type
    # rather than as "enchanted <any noun>'s controller" so the set stays
    # exactly the one the legacy condition table admits — `enchanted land's
    # controller` is deliberately NOT here. Cursed Land's upkeep damage is
    # already dealt by the enchant-land pass in phases/upkeep_step.py, so a
    # fourth entry would compile a *second* trigger and the card would deal its
    # damage twice (pinned by test_cursed_land_deals_upkeep_damage_to_land_controller).
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "creature", "'s", "controller")),
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "artifact", "'s", "controller")),
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "enchantment", "'s", "controller")),
    ("upkeep_chosen", ("the", "beginning", "of", "the", "chosen", "player", "'s", "upkeep")),
    ("draw_step_each", ("the", "beginning", "of", "each", "player", "'s", "draw", "step")),
    ("end_step", ("the", "beginning", "of", "the", "end", "step")),
    ("end_step", ("the", "beginning", "of", "each", "end", "step")),
    ("end_step", ("the", "beginning", "of", "your", "end", "step")),
    ("combat", ("the", "beginning", "of", "combat")),
)

_DURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("until_end_of_turn", ("until", "end", "of", "turn")),
    ("until_end_of_combat", ("until", "end", "of", "combat")),
    ("until_your_next_turn", ("until", "your", "next", "turn")),
    ("this_turn", ("this", "turn")),
)

_COUNTER_KINDS = ("+1/+1", "+1/+0", "+0/+1", "-1/-1")

# Board-state counts that bind a clause's X, one literal phrase per name. Not
# parsed compositionally, and that is the design rather than a shortcut: each
# of these is arithmetic an ``ObjectFilter`` cannot express — a count taken at
# an earlier point in the turn, a count of a hidden zone with a constant
# subtracted — so the *handler* computes the whole thing and the grammar's only
# job is to say which count was written. A phrase not listed here fails to
# match, the line fails full-token consumption, and the card falls back rather
# than compiling onto a handler that counts something else.
_BOARD_COUNTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cards_in_hand_minus_four",
        ("the", "number", "of", "cards", "in", "their", "hand", "minus", "4"),
    ),
    (
        "untapped_lands_at_turn_start",
        ("the", "number", "of", "untapped", "lands", "they", "controlled",
         "at", "the", "beginning", "of", "this", "turn"),
    ),
)

# Zone names a destination clause can end in (CR 400.1).
_ZONES = frozenset({"battlefield", "graveyard", "hand", "library", "exile", "stack"})


# ---------------------------------------------------------------------------
# Small shared productions
# ---------------------------------------------------------------------------


def _parse_duration(stream: TokenStream) -> ast.Duration:
    """Parse a trailing duration clause. Absent wording means permanent — one
    node replacing the fifteen places the legacy rules re-literalled these."""
    for kind, phrase in _DURATIONS:
        if stream.accept_phrase(*phrase):
            return ast.Duration(kind)
    return ast.Duration()


def _accept_literal(stream: TokenStream, *phrase: str) -> bool:
    """Consume consecutive tokens by their text, all-or-nothing.

    ``TokenStream.accept_phrase`` requires every token to be a *word*, which
    "…hand minus 4" is not — the 4 lexes as a number. Punctuation is still
    refused, so a phrase can never silently span a sentence boundary.
    """
    if len(stream.tokens) - stream.pos < len(phrase):
        return False
    for offset, text in enumerate(phrase):
        token = stream.tokens[stream.pos + offset]
        if token.kind == PUNCT or token.text != text:
            return False
    stream.advance(len(phrase))
    return True


def _parse_where_x_is(stream: TokenStream) -> ast.BoardCount | None:
    """", where X is <board-state count>" — the trailer that says what the X of
    the preceding clause counts.

    Returning None on an unrecognized count leaves its tokens unconsumed, so the
    line fails the full-consumption invariant and falls back. That is the whole
    value of the production: the alternative — consuming "where X is …" and
    whatever follows — would make every card written this way compile onto
    whichever count the caller happened to assume.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_phrase("where", "x", "is"):
        stream.reset(mark)
        return None
    for name, phrase in _BOARD_COUNTS:
        if _accept_literal(stream, *phrase):
            return ast.BoardCount(name)
    stream.reset(mark)
    return None


def _parse_keywords(stream: TokenStream) -> tuple[str, ...]:
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            break
        name, consumed = matched
        stream.advance(consumed)
        # "protection from red" — the argument belongs to the keyword.
        if name == "protection" and stream.accept_word("from"):
            colour = stream.peek_word()
            if colour is not None:
                stream.advance()
                name = f"protection from {colour}"
        keywords.append(name)
        if not (stream.accept_word("and") or stream.accept_word("or")):
            break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords)


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


def _parse_gets(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gets +N/+N [duration]``."""
    stream.expect_word("gets", "get")
    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    duration = _parse_duration(stream)
    pump = ast.Pump(subject, power, toughness, duration, power_negative, toughness_negative)

    # "gets +3/+3 and gains flying until end of turn" / "get +1/+1 and have
    # mountainwalk" — the same conjunction in the two persons the templating
    # uses. Accepting only "gains" would leave the lordly form ("Other Goblins
    # get +1/+1 and have mountainwalk") stranding "have mountainwalk", which
    # fails full consumption and takes the whole line down.
    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gains", "gain", "has", "have"):
        stream.advance()
        keywords = _parse_keywords(stream)
        keyword_duration = _parse_duration(stream)
        if duration.kind is None and keyword_duration.kind is not None:
            pump = ast.Pump(
                subject, power, toughness, keyword_duration,
                power_negative, toughness_negative,
            )
        return ast.Conjunction((pump, ast.GainKeyword(subject, keywords, keyword_duration)))
    stream.reset(mark)
    return pump


def _parse_gains(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gains <keywords|life> [duration]``."""
    stream.expect_word("gains", "gain")

    # "you gain 3 life" / "you gain life equal to the damage dealt"
    mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.GainLife(player, amount)
    else:
        try:
            amount = parse_amount(stream)
            if stream.accept_word("life"):
                player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
                return ast.GainLife(player, amount)
        except GrammarError:
            pass
        stream.reset(mark)

    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    grant = ast.GainKeyword(subject, keywords, duration)

    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gets", "get"):
        pump = _parse_gets(stream, subject)
        # Berserk: "gains trample and gets +X/+0 until end of turn" — the shared
        # duration sits at the end and applies to both halves.
        if isinstance(pump, ast.Pump) and duration.kind is None and pump.duration.kind:
            grant = ast.GainKeyword(subject, keywords, pump.duration)
        return ast.Conjunction((grant, pump))
    stream.reset(mark)
    return grant


def _parse_loses(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> loses <keywords|life>``."""
    stream.expect_word("loses", "lose")
    mark = stream.mark()
    try:
        amount = parse_amount(stream)
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(player, amount)
    except GrammarError:
        pass
    stream.reset(mark)
    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    return ast.LoseKeyword(subject, keywords, duration)


def _parse_has(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has <keywords>`` / ``<subject> has base power …``.

    "Has" is the third person of "gains" — "Enchanted creature has flying" and
    "Target creature gains flying until end of turn" grant the same thing and
    differ only in duration, so they share :class:`ast.GainKeyword` rather than
    getting a node apiece. What separates them is exactly what lowering acts on:
    a granted keyword with no duration is a continuous effect (CR 613) and is
    refused there, while one with a duration has a handler.

    "Base power" is checked first and delegated, because it is the one reading
    of "has" that is not a keyword grant. Falling through to the keyword list
    instead would make "has base power and toughness 3/3" fail on "base" — which
    is not a keyword — and take the whole line down with it.
    """
    mark = stream.mark()
    stream.expect_word("has", "have")
    if stream.at_word("base"):
        stream.reset(mark)
        return _parse_has_base_pt(stream, subject)
    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    return ast.GainKeyword(subject, keywords, duration)


def _parse_has_base_pt(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has base power [and toughness] N[/N] [duration]``."""
    stream.expect_word("has", "have")
    stream.expect_word("base")
    stream.expect_word("power")

    if stream.accept_phrase("and", "toughness"):
        token = stream.peek()
        if token is not None and token.kind == PT:
            power, _, toughness, _ = expect_pt(stream)
        else:
            power = parse_amount(stream)
            toughness = parse_amount(stream)
        duration = _parse_duration(stream)
        return ast.SetBasePT(subject, power, toughness, duration)

    power = parse_amount(stream)
    duration = _parse_duration(stream)
    return ast.SetBasePT(subject, power, None, duration)


def _expect_counter_kind(stream: TokenStream, suffix: str = "") -> GToken:
    """The counter's written name, as its token.

    The kind must be *written out*. Defaulting a bare "put a counter on it" to
    +1/+1 would silently invent the wrong counter for cards that use any other
    kind — the deletion probe flagged exactly this by removing the "+1/+1"
    token and getting the same instruction back — and reading the head noun as
    the kind would invent a counter called "counter".

    A plain word is admitted as well as a P/T token, because CR 122.1 lets a
    counter have any name and the pool prints several ("corpse", "wind",
    "mire"). Which of those anything can actually *do* is a question for the
    caller: the two callers differ precisely there, so the check stays with
    them rather than being frozen into one shared list here.
    """
    token = stream.peek()
    if token is None or token.kind not in (PT, WORD) or token.is_word("counter", "counters"):
        raise stream.error("expected a counter kind" + suffix)
    stream.advance()
    return token


def _parse_for_each(stream: TokenStream) -> ast.DiedThisTurn | None:
    """``for each <objects> that died this turn`` — a trailing iteration clause.

    The set is a *history*, not a board state, which is why it produces
    :class:`ast.DiedThisTurn` rather than the noun phrase's own filter.

    "This turn" is required rather than defaulted, for the reason the deletion
    probe exists: the engine's death tally resets each turn, so a clause
    counting some other window is a different number — and letting the words be
    absent would let them be *deleted* with no change to the parse.

    Returning None leaves the cursor where it was, so a caller that does not
    find the clause still owes the rest of the line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("that", "died"):
        stream.reset(mark)
        return None
    if _parse_duration(stream).kind != "this_turn":
        stream.reset(mark)
        return None
    return ast.DiedThisTurn(filt)


def _parse_put_counter(stream: TokenStream) -> ast.Statement:
    """``put [up to] N <counter> counter(s) on <subject> [for each …]``."""
    stream.expect_word("put")
    up_to = stream.accept_phrase("up", "to")
    count = parse_amount(stream)

    token = _expect_counter_kind(stream)
    if token.kind == PT and token.text not in _COUNTER_KINDS:
        raise stream.error(f"unsupported counter kind {token.text!r}")
    counter = token.text
    stream.expect_word("counter", "counters")
    stream.expect_word("on")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected a permanent to put counters on")
    placement = ast.PutCounter(subject, counter, count, up_to)

    # "…for each creature that died this turn" multiplies the placement; it is
    # not a rider on it. Modelled as an iteration wrapping the placement so a
    # counter put down once and a counter put down per death are *different*
    # ASTs — the legacy registry told them apart only by giving the per-death
    # rule a lower order number than the plain one.
    iterated = _parse_for_each(stream)
    if iterated is None:
        return placement
    return ast.ForEach(iterated, placement)


def _parse_zone(stream: TokenStream) -> ast.Zone:
    """A zone destination: ``your hand``, ``the battlefield``, ``its owner's hand``.

    The possessive is part of the zone, not decoration: Unsummon returns a
    creature to *its owner's* hand while Raise Dead returns a card to *your*
    hand, and those are different players whenever you have stolen the creature.
    An unrecognized possessive raises rather than falling through to the bare
    zone name, so the distinction can never be lost by omission.
    """
    owner: ast.PlayerRef | None = None
    if stream.accept_word("your"):
        owner = ast.PlayerRef("you")
    elif stream.accept_phrase("its", "owner", "'s") or stream.accept_phrase(
        "their", "owner", "'s"
    ):
        owner = ast.PlayerRef("owner")
    elif stream.accept_phrase("its", "controller", "'s"):
        owner = ast.PlayerRef("controller")
    else:
        stream.accept_word("a", "an", "the")
    name = stream.peek_word()
    if name not in _ZONES:
        raise stream.error("expected a zone name")
    stream.advance()
    return ast.Zone(name, owner)


def _parse_return(stream: TokenStream) -> ast.Statement:
    """``Return <objects> [from <zone>] to <zone>`` (CR 400.7).

    One production for Raise Dead, Regrowth, Resurrection and Unsummon, which
    the legacy registry needed three separately-ordered substring rules for —
    and which it told apart by probing for ``"creature card" not in text``. The
    source zone rides on the noun phrase (``engine/grammar/nouns.py``), because
    "target creature card from your graveyard" is one noun phrase; the
    destination is parsed here.
    """
    stream.expect_word("return")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to return")
    if not stream.accept_word("to"):
        raise stream.error("expected a destination zone after 'return'")
    destination = _parse_zone(stream)

    from_zone: ast.Zone | None = None
    if isinstance(subject, ast.TargetSpec) and subject.filter.zone != "battlefield":
        from_zone = ast.Zone(subject.filter.zone, subject.filter.zone_owner)
    return ast.ReturnToZone(subject, destination, from_zone)


def _parse_destroy(stream: TokenStream) -> ast.Statement:
    """``destroy <objects> [. It can't be regenerated.]``

    One production covers "destroy target creature", "destroy all lands",
    "destroy target tapped creature", and "destroy all Plains" — the
    distinction lives in the noun phrase's quantifier and filter. The legacy
    registry needed five separate rules with hand-ordered precedence numbers to
    keep "destroy all creatures" from being eaten by "destroy target".
    """
    stream.expect_word("destroy")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to destroy")

    no_regen = False
    mark = stream.mark()
    stream.accept_punct(".", ",")
    if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
        "they", "can't", "be", "regenerated"
    ):
        no_regen = True
    else:
        stream.reset(mark)
    return ast.Destroy(subject, no_regen=no_regen)


def _parse_tap_untap(stream: TokenStream) -> ast.Statement:
    """``tap <objects>`` / ``untap <objects>`` / ``tap or untap <objects>``.

    The disjunction (Twiddle) is read here rather than as two statements joined
    by "or": both directions act on the *same* chosen target and only one of
    them happens, so a ``Conjunction`` would tap the permanent and then untap
    it. Only "tap or untap" is a disjunction — "untap or tap" is not printed on
    any card, and inventing it would accept text no card carries.
    """
    verb = stream.expect_word("tap", "untap").text
    either_way = False
    if verb == "tap":
        mark = stream.mark()
        if stream.accept_word("or") and stream.accept_word("untap"):
            either_way = True
        else:
            stream.reset(mark)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error(f"expected something to {verb}")
    if either_way:
        return ast.TapOrUntap(subject)
    return ast.Tap(subject) if verb == "tap" else ast.Untap(subject)


def _parse_draw(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("draws", "draw")
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    return ast.Draw(player, count)


def _parse_discard(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("discards", "discard")
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    at_random = stream.accept_phrase("at", "random")
    return ast.Discard(player, count, at_random)


def _parse_token_keywords(stream: TokenStream) -> tuple[str, ...]:
    """The ``with <keyword>[, <keyword>][ and <keyword>]`` tail of a token spec."""
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            raise stream.error("expected a keyword ability on the token")
        name, consumed = matched
        keywords.append(name)
        stream.advance(consumed)
        if stream.accept_punct(","):
            stream.accept_word("and")
            continue
        if stream.accept_word("and"):
            continue
        break
    return tuple(keywords)


def _parse_create_token(stream: TokenStream) -> ast.Statement:
    """``Create <N> <P/T> <colours> <subtypes> <types> token(s) [with …] [named …]``.

    One production for the whole family, because ``create_token`` is already
    the engine's one generic token maker (engine/tokens.py): everything that
    varies between token cards — count, P/T, colour, types, keywords, name —
    is payload, so there is nothing per-card left for a rule to encode.

    The printed word order *is* the type line's order (CR 205.1a), so the types
    are recorded as written rather than re-sorted. Every word between the
    quantity and the head noun must land in one of the recorded fields; a
    supertype ("a legendary … token") has nowhere to go on
    :class:`ast.CreateToken`, so it raises instead of being dropped.
    """
    stream.expect_word("create")
    count = parse_amount(stream)

    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    if power_negative or toughness_negative:
        raise stream.error("a token's printed power/toughness cannot be negative")
    if not (isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)):
        # ``CreateToken`` stores printed integers, and ``create_token`` reads
        # them with ``int(...)``. A variable "X/X token" has no representation
        # on either side, so it refuses here rather than resolving to a
        # sentinel that would reach the battlefield as a real creature.
        raise stream.error("a token with a variable power/toughness has no representation")

    colors: list[str] = []
    stated_colour = False
    while True:
        word = stream.peek_word()
        if word in COLOR_WORDS:
            colors.append(COLOR_WORDS[word])
            stated_colour = True
            stream.advance()
            stream.accept_punct(",")
            stream.accept_word("and")
            continue
        if word == "colorless":
            stated_colour = True
            stream.advance()
            continue
        break
    if not stated_colour:
        # Every token spec the pool prints states a colour, "colorless"
        # included, and the word has to stay load-bearing: an empty ``colors``
        # tuple already means colourless, so a production that let the word be
        # absent would also let it be *deleted* with no change to the payload —
        # which is precisely what the parse-coverage deletion probe flags as a
        # dropped rider. Refusing keeps the failure loud and keeps the grammar
        # off wordings no card in the pool carries.
        raise stream.error("expected the token's colour, or 'colorless'")

    subtypes: list[str] = []
    card_types: list[str] = []
    while not stream.at_word("token", "tokens"):
        word = stream.peek_word()
        if word is None:
            raise stream.error("expected 'token' after a token's characteristics")
        if word in CARD_TYPES:
            card_types.append(word)
            stream.advance()
            continue
        matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
        if matched is None:
            raise stream.error(f"unrecognized token characteristic {word!r}")
        name, consumed = matched
        subtypes.append(name)
        stream.advance(consumed)
    stream.expect_word("token", "tokens")

    keywords: tuple[str, ...] = ()
    if stream.accept_word("with"):
        keywords = _parse_token_keywords(stream)

    # CR 111.4 — the creating ability may set the token's name. When it does
    # not, the name follows from the subtypes, and lowering (not the parser)
    # decides whether the engine's convention for that is expressible.
    name = ""
    if stream.accept_word("named"):
        parts: list[str] = []
        while stream.peek() is not None and stream.at_kind(WORD):
            parts.append(stream.next().text)
        if not parts:
            raise stream.error("expected a token name after 'named'")
        name = " ".join(parts)

    return ast.CreateToken(
        count=count,
        power=power.value,
        toughness=toughness.value,
        name=name,
        colors=tuple(colors),
        types=tuple(card_types),
        subtypes=tuple(subtypes),
        keywords=keywords,
    )


def _parse_add_mana(stream: TokenStream) -> ast.Statement:
    """``Add {G}`` / ``Add {C}{C}{C}`` / ``Add one mana of any color``."""
    start = stream.mark()
    stream.expect_word("add")

    def _clause() -> str:
        return render(stream.tokens[start:stream.pos])

    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
        # "{B} or {R}" — a dual land's choice, not two mana.
        if stream.at_word("or"):
            mark = stream.mark()
            stream.advance()
            if not stream.at_kind(MANA):
                stream.reset(mark)
                break
    if pips:
        return ast.AddMana(tuple(sorted(pips.items())), source_text=_clause())

    # "Add one mana of any color" / "Add three mana of any one color".
    count = parse_amount(stream)
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.accept_word("any")
    stream.accept_word("one")
    stream.expect_word("color")
    amount = count.value if isinstance(count, ast.Fixed) else 1
    return ast.AddMana((), any_color=amount, source_text=_clause())


def _parse_mana_payment(stream: TokenStream, *, allow_variable: bool = False) -> ast.ManaCost:
    """The mana half of "you may pay {1}" / "unless its controller pays {X}".

    *allow_variable* admits ``{X}``. It is off by default because most payment
    prompts resolve a concrete number: an "unless you pay {X}" whose caller
    cannot supply an X would otherwise become a silent "pay {0}", which is
    never a real choice.
    """
    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit():
            pips["generic"] = pips.get("generic", 0) + int(symbol)
        elif symbol in ("W", "U", "B", "R", "G", "C"):
            pips[symbol] = pips.get(symbol, 0) + 1
        elif allow_variable and symbol == "X":
            pips["X"] = pips.get("X", 0) + 1
        else:
            raise stream.error(f"unsupported mana symbol {token.text!r}")
    if not pips:
        raise stream.error("expected a mana cost to pay")
    return ast.ManaCost(tuple(sorted(pips.items())))


def _parse_counter(stream: TokenStream) -> ast.Statement:
    """``counter <spell> [unless <player> pays <cost>]``.

    The "unless" clause is part of the counter, not a wrapper around it: the
    cost is offered to the *targeted spell's* controller while that spell waits
    on the stack (CR 118.3c). Reading it as a `Conditional` would put the
    decision on the wrong player and the counter in the wrong place.
    """
    stream.expect_word("counter")
    subject = parse_target_spec(stream)
    if subject is None:
        raise stream.error("expected a spell to counter")

    if stream.accept_word("unless"):
        payer = parse_player_ref(stream)
        if payer is None:
            raise stream.error("expected who pays after 'unless'")
        if payer.kind != "controller":
            # Only the countered spell's own controller has a payment flow.
            # Anyone else paying is a different effect, so refuse instead of
            # dropping the distinction.
            raise stream.error("only the spell's controller can pay to avoid a counter")
        stream.expect_word("pays", "pay")
        return ast.CounterSpell(subject, unless_pays=_parse_mana_payment(stream, allow_variable=True))

    return ast.CounterSpell(subject)


# What a card does to the player who declines an "unless … pays" cost, matched
# as one literal shape per penalty. Deliberately not parsed compositionally:
# the sentence is not a step of the spell — the counter flow performs it while
# countering — so the grammar's only job is to say *which* penalty was written
# and account for the tokens. A penalty not listed here fails to match, the
# line fails full-token consumption, and the card falls back rather than
# compiling with a rider nothing performs.
_UNPAID_PENALTIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tap_lands_and_empty_pool",
        (
            "they", "tap", "all", "lands", "with", "mana", "abilities", "they",
            "control", "and", "lose", "all", "unspent", "mana",
        ),
    ),
)


def _parse_unpaid_penalty_sentence(stream: TokenStream) -> str | None:
    """"If that player doesn't, <penalty>." — the declined branch of an
    "unless … pays" cost, as a penalty name."""
    mark = stream.mark()
    if not (
        stream.accept_phrase("if", "that", "player", "doesn't")
        or stream.accept_phrase("if", "that", "player", "does", "not")
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    for name, phrase in _UNPAID_PENALTIES:
        if stream.accept_phrase(*phrase):
            return name
    stream.reset(mark)
    return None


def _parse_enchant(stream: TokenStream) -> ast.Statement:
    """``Enchant creature`` — an Aura's attachment restriction (CR 702.5).

    Not an effect: it declares what the Aura can be attached to. Parsed so the
    line is accounted for; the engine's attachment handling is driven elsewhere.
    """
    stream.expect_word("enchant")
    filt = parse_object_filter(stream, allow_bare=True)
    # "Enchant creature card in a graveyard" (Animate Dead).
    if stream.accept_word("card"):
        if stream.accept_word("in"):
            stream.accept_word("a", "an", "the")
            stream.expect_word("graveyard")
    return ast.RawEffect(f"enchant:{filt}")


def _parse_look_at_hand(stream: TokenStream) -> ast.Statement:
    """``Look at <player>'s hand.`` (Glasses of Urza.)

    Both the possessive marker and the zone noun are expected rather than
    skipped. "Look at" heads a family of information effects that differ only in
    their object — the top card of a library, the cards in a hand, a face-down
    creature — so consuming the object is what keeps this production from
    claiming the others.
    """
    stream.expect_word("look")
    stream.expect_word("at")
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player whose hand is looked at")
    # The lexer splits "player's" into "player" + "'s"; the marker still has to
    # be consumed or the line fails full-token consumption.
    stream.expect_word("'s")
    stream.expect_word("hand")
    return ast.LookAtHand(player)


def _parse_search_library(stream: TokenStream) -> ast.Statement:
    """``Search your library for a <object>, put that card into your hand, then
    shuffle.`` (Demonic Tutor, CR 701.19.)

    Three parts are read rather than skipped, because each one names a
    different effect:

    * **whose library** — the engine's search flow only ever opens the
      searcher's own library, so "search target player's library" is a
      different card, not a wording of this one;
    * **where the found card goes** — onto the battlefield or on top of the
      library are other effects entirely, and the destination is parsed as an
      ordinary zone so lowering can compare it against the one the flow
      implements;
    * **the shuffle** — ``confirm_search_library`` shuffles as it moves the
      card, so it is part of this effect rather than a step of its own. It is
      required, so deleting the word makes the line fail to parse instead of
      quietly claiming a search that never shuffles.

    Singular by construction: the article is *expected* rather than a general
    quantity being parsed. :class:`ast.SearchLibrary` has no count field and
    the confirm flow moves exactly one card, so "search your library for two
    cards" must fail here rather than silently find one.
    """
    stream.expect_word("search")
    if not stream.accept_word("your"):
        raise stream.error("only searching your own library has a search flow")
    stream.expect_word("library")
    stream.expect_word("for")
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    stream.expect_word("put")
    stream.expect_word("that")
    stream.expect_word("card")
    # "into your hand" / "onto the battlefield" — both prepositions are read so
    # the destination reaches lowering, which refuses the ones no flow
    # implements *by name*. Refusing here instead would report the card as an
    # unparsed search rather than an unimplemented destination.
    stream.expect_word("into", "onto")
    destination = _parse_zone(stream)
    stream.accept_punct(",")
    stream.accept_word("then")
    stream.expect_word("shuffle")
    return ast.SearchLibrary(ast.PlayerRef("you"), filt, destination)


def _parse_extra_turn(stream: TokenStream) -> ast.Statement:
    """``Take an extra turn after this one.`` (Time Walk, Time Vault.)

    Singular by construction: the article is *expected* rather than a general
    quantity being parsed, so "take two extra turns after this one" fails to
    parse instead of quietly granting one turn. "after this one" is required for
    the same reason — it is what says the turn is taken immediately, and a card
    that placed it elsewhere would be a different effect.
    """
    stream.expect_word("take")
    stream.expect_word("an")
    stream.expect_word("extra")
    stream.expect_word("turn")
    if not stream.accept_phrase("after", "this", "one"):
        raise stream.error("expected 'after this one'")
    return ast.ExtraTurn(ast.PlayerRef("you"))


# The two printed combat restrictions the engine enforces (CR 506, 509). Both
# are already derived from raw text by engine/combat_restrictions.py for the
# legacy path; this production lets the *grammar* claim them, lowering to the
# same instruction kinds with the same payloads so the differential can hold
# the two to agreement.
#
# The land type and the power threshold are captured, not baked into the
# production, for the same reason they are payload rather than kind names: a
# card naming Mountain, or a threshold of 4, is the same restriction.
_BASIC_LAND_WORDS = ("plains", "island", "swamp", "mountain", "forest")


def _parse_cant_attack_or_block(
    stream: TokenStream, subject: ast.Recipient
) -> ast.Statement:
    """``<subject> can't attack unless defending player controls a <land>`` /
    ``<subject> can't block creatures with power N or greater``."""
    # "can't" is peeked, not consumed, so the fallback to _parse_cant_be (which
    # expects to read it itself) sees an untouched stream.
    mark = stream.mark()
    stream.expect_word("can't", "cannot")

    if stream.accept_word("attack"):
        if not stream.accept_phrase("unless", "defending", "player", "controls"):
            raise stream.error("expected 'unless defending player controls'")
        stream.expect_word("a", "an")
        land = stream.peek_word()
        if land not in _BASIC_LAND_WORDS:
            # A nonbasic or unknown type: the enforcing check scopes its search
            # to basic land types, so claiming this would promise more than the
            # engine does.
            raise stream.error("expected a basic land type")
        stream.advance()
        return ast.CombatRestriction(
            subject, "cant_attack_without_land_type", (("land_type", land),)
        )

    if stream.accept_word("block"):
        stream.expect_word("creatures")
        if not stream.accept_phrase("with", "power"):
            raise stream.error("expected 'with power'")
        token = stream.peek()
        if token is None or not token.text.isdigit():
            raise stream.error("expected a power threshold")
        power = token.text
        stream.advance()
        if not stream.accept_phrase("or", "greater"):
            raise stream.error("expected 'or greater'")
        return ast.CombatRestriction(
            subject, "cant_block_power_n_or_greater", (("power", int(power)),)
        )

    stream.reset(mark)
    return _parse_cant_be(stream, subject)


# Participles this production recognizes after "can't be". A closed list, so a
# restriction the grammar has never seen fails in the parser by name instead of
# being read as one of these.
_CANT_BE_ACTIONS = ("regenerated", "blocked")


def _parse_cant_be(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> can't be <participle> [duration]``.

    Note what is deliberately *not* consumed: a trailing exception clause
    ("… except by Walls", "… by Walls"). Those name creatures the restriction
    does not apply to, so swallowing them would turn a conditional restriction
    into an absolute one. Leaving the tokens makes the line fail the
    full-consumption invariant and fall back — Invisibility and Juggernaut stay
    visibly unclaimed rather than quietly becoming unblockable.
    """
    stream.expect_word("can't", "cannot")
    stream.expect_word("be")
    word = stream.peek_word()
    if word not in _CANT_BE_ACTIONS:
        raise stream.error("unrecognized \"can't be\" restriction")
    stream.advance()
    duration = _parse_duration(stream)
    return ast.CantBe(subject, word, duration)


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


# ---------------------------------------------------------------------------
# Statement productions
# ---------------------------------------------------------------------------


def _parse_subject_verb(stream: TokenStream) -> ast.Statement:
    """``<subject> <verb> …`` — the common imperative-with-subject shape."""
    # "The next time a <colour> source of your choice would deal damage to you
    # this turn, prevent that damage." opens with a noun phrase rather than a
    # verb, so it is tried before the subject-verb shapes below.
    colour_shield = _parse_colour_source_prevention(stream)
    if colour_shield is not None:
        return colour_shield
    # A bare imperative verb has an implied "you"/the source as subject.
    if stream.at_word("destroy"):
        return _parse_destroy(stream)
    if stream.at_word("tap", "untap"):
        return _parse_tap_untap(stream)
    if stream.at_word("put"):
        return _parse_put_counter(stream)
    if stream.at_word("create"):
        return _parse_create_token(stream)
    if stream.at_word("return"):
        return _parse_return(stream)
    if stream.at_word("prevent"):
        return _parse_prevent(stream)
    if stream.at_word("sacrifice"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to sacrifice")
        # "… unless you pay {W}{W}" — a pay-or-else prompt, kept fused because
        # that is the shape the upkeep dispatcher's handlers implement.
        mark = stream.mark()
        if stream.accept_phrase("unless", "you", "pay"):
            return ast.SacrificeUnlessPay(subject, _parse_mana_payment(stream))
        stream.reset(mark)
        return ast.Sacrifice(ast.PlayerRef("you"), subject)
    if stream.at_word("regenerate"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to regenerate")
        return ast.Regenerate(subject)
    if stream.at_word("add"):
        return _parse_add_mana(stream)
    if stream.at_word("look"):
        return _parse_look_at_hand(stream)
    if stream.at_word("search"):
        return _parse_search_library(stream)
    if stream.at_word("take"):
        return _parse_extra_turn(stream)
    if stream.at_word("draw"):
        return _parse_draw(stream, ast.PlayerRef("you"))
    # A bare "discard N cards" is the effect's *controller* discarding, the same
    # implied subject a bare "draw" already carries. Without it "Draw two cards,
    # then discard three cards" strands its second clause and the whole line
    # fails; with it the line parses and lowering decides whether the pair has a
    # handler.
    if stream.at_word("discard"):
        return _parse_discard(stream, ast.PlayerRef("you"))
    if stream.at_word("counter"):
        return _parse_counter(stream)
    if stream.at_word("enchant"):
        return _parse_enchant(stream)

    mark = stream.mark()

    # The self-reference token the lexer emits for the card's own name, plus
    # the "it" of a trigger's remainder clause, both denote the source.
    source_spec: ast.Recipient | None = None
    if stream.at_kind(SELF):
        stream.advance()
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    elif stream.at_word("it"):
        stream.advance()
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    else:
        source_spec = parse_recipient(stream)

    if source_spec is None:
        stream.reset(mark)
        raise stream.error("expected a subject")

    token = stream.peek()
    if token is None:
        stream.reset(mark)
        raise stream.error("expected a verb")

    if token.kind == WORD:
        source_target = source_spec if isinstance(source_spec, ast.TargetSpec) else None
        if token.text in ("deals", "deal"):
            return _parse_damage(stream, source_target)
        if token.text in ("gets", "get"):
            return _parse_gets(stream, source_spec)
        if token.text in ("gains", "gain"):
            return _parse_gains(stream, source_spec)
        if token.text in ("loses", "lose"):
            return _parse_loses(stream, source_spec)
        if token.text in ("has", "have"):
            return _parse_has(stream, source_spec)
        if token.text in ("draws", "draw") and isinstance(source_spec, ast.PlayerRef):
            return _parse_draw(stream, source_spec)
        if token.text in ("discards", "discard") and isinstance(source_spec, ast.PlayerRef):
            return _parse_discard(stream, source_spec)
        if token.text == "becomes":
            return _parse_become_color(stream, source_spec)
        if token.text in ("can't", "cannot"):
            return _parse_cant_attack_or_block(stream, source_spec)

    stream.reset(mark)
    raise stream.error("unrecognized effect verb")


def parse_statement(stream: TokenStream) -> ast.Statement:
    """One sentence's worth of effect, including ``if``/``may`` wrappers."""
    # "if <condition>, <statement>"
    if stream.at_word("if"):
        mark = stream.mark()
        stream.advance()
        try:
            condition = _parse_condition(stream)
            stream.accept_punct(",")
            then = parse_statement(stream)
            return ast.Conditional(condition, then)
        except GrammarError:
            stream.reset(mark)

    # "you may <pay a cost | take an action>"
    if stream.at_word("you"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("may"):
            if stream.at_word("pay"):
                stream.advance()
                cost = _parse_mana_payment(stream)
                return ast.May(ast.PlayerRef("you"), cost=cost)
            try:
                action = parse_statement(stream)
                return ast.May(ast.PlayerRef("you"), action=action)
            except GrammarError:
                stream.reset(mark)
        else:
            stream.reset(mark)

    statement = _parse_subject_verb(stream)

    # "<statement>, then <statement>" / "<statement> and <statement>"
    while True:
        mark = stream.mark()
        joined = False
        if stream.accept_punct(","):
            if stream.accept_word("then"):
                joined = True
            else:
                stream.reset(mark)
                break
        elif stream.accept_word("and"):
            joined = True
        elif stream.accept_word("then"):
            joined = True

        if not joined:
            stream.reset(mark)
            break
        try:
            follow = parse_statement(stream)
        except GrammarError:
            stream.reset(mark)
            break
        statement = ast.Sequence((statement, follow))
    return statement


def _parse_condition(stream: TokenStream) -> ast.Condition:
    """Conditions the grammar models today. Anything else raises so the line
    falls back rather than silently losing the condition — the legacy compiler
    dropped intervening-ifs entirely, making conditional triggers always fire."""
    mark = stream.mark()

    player = parse_player_ref(stream)
    if player is not None:
        if stream.accept_word("control", "controls"):
            negated = stream.accept_word("no")
            # "you control **a** Swamp". The article carries no meaning of its
            # own, but the noun parser refuses it as an unknown adjective, so
            # leaving it would refuse every singular condition in the pool.
            stream.accept_word("a", "an")
            filt = parse_object_filter(stream)
            comparison = None if not negated else ast.Comparison("eq", ast.Fixed(0))
            return ast.Controls(player, filt, comparison)
        stream.reset(mark)

    if stream.accept_phrase("a", "creature", "died"):
        _parse_duration(stream)
        return ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))

    # "it is untapped" and "it's untapped" are the same condition; the lexer
    # splits the contraction into "it" + "'s", so both spellings are listed
    # rather than the apostrophe being skipped wherever it turns up.
    if stream.accept_phrase("it", "is", "untapped") or stream.accept_phrase(
        "it", "'s", "untapped"
    ):
        return ast.IsState(ast.TargetSpec("this", ast.ObjectFilter(is_source=True)), "tapped", negated=True)
    if stream.accept_phrase("this", "is", "untapped"):
        return ast.IsState(ast.TargetSpec("this", ast.ObjectFilter(is_source=True)), "tapped", negated=True)

    raise stream.error("unrecognized condition")


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------


def _is_keyword_line(stream: TokenStream) -> tuple[ast.KeywordInstance, ...] | None:
    """A line that is nothing but keyword abilities.

    The separator is a comma, "and", or a **semicolon**: Magic's templating
    switches to semicolons once one of the keywords carries reminder text
    ("Trample; banding (…)"), and the lexer strips the reminder while leaving
    the semicolon behind. Without it Mesa Pegasus and War Elephant fail on
    their first keyword and are reported as missing a *subject*, which points
    at nothing that exists.
    """
    mark = stream.mark()
    keywords: list[ast.KeywordInstance] = []
    while not stream.exhausted:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            stream.reset(mark)
            return None
        name, consumed = matched
        stream.advance(consumed)
        argument: str | None = None
        if name == "protection" and stream.accept_word("from"):
            word = stream.peek_word()
            if word is None:
                stream.reset(mark)
                return None
            stream.advance()
            argument = word
        keywords.append(ast.KeywordInstance(name, argument))
        if stream.exhausted:
            break
        if not (stream.accept_punct(",", ";") or stream.accept_word("and")):
            stream.reset(mark)
            return None
    return tuple(keywords) if keywords else None


def _parse_registry_line(stream: TokenStream, line: str) -> ast.RegistryLine | None:
    """A line implemented by a text-keyed sidecar registry rather than by any
    instruction — ``engine/grammar/registries.py`` names the implementing code
    for each shape it admits.

    Nothing is matched *structurally* here, and that is deliberate. A
    shape-based production ("cast this spell only" followed by anything, "…
    don't untap during" followed by anything) would parse wordings no registry
    implements and report them as understood, which is worse than the current
    loud refusal. Instead the registry's own matcher is asked whether it claims
    the whole line, so full consumption holds by construction: the tokens are
    advanced past the end only once something has accounted for all of them.

    A line claimed here is never offered to the effect productions, so an entry
    may only exist while the line has no instruction at all. When one grows a
    real lowering, its registry entry has to go — otherwise this would shadow
    it silently.
    """
    registry = registry_for_line(line)
    if registry is None:
        return None
    stream.advance(len(stream) - stream.pos)
    return ast.RegistryLine(registry, line)


def _parse_cost_object(stream: TokenStream, verb: str) -> ast.ObjectFilter:
    """The noun phrase naming what a cost gives up, after *verb*.

    Delegates to the noun parser rather than skipping a token, so "Sacrifice
    this artifact" and "Sacrifice a creature" end up as *different* filters —
    one flagged ``is_source``, one carrying a card type. The old
    ``accept_phrase("sacrifice", "this")`` + ``advance()`` read any word at all
    as the noun and produced the same empty filter either way, which reads as
    "sacrifice any object" to anyone who later lowers these.

    Only the two quantifiers the pool prints are admitted. "Sacrifice two
    creatures" or "Sacrifice target creature" would parse here and mean
    something the rest of the cost machinery has no way to express, so they
    raise instead.
    """
    spec = parse_target_spec(stream)
    if spec is None:
        raise stream.error(f"expected what to {verb} as a cost")
    if spec.quantifier not in ("this", "a") or spec.count != 1:
        raise stream.error(f"unsupported {verb} cost quantifier {spec.quantifier!r}")
    return spec.filter


def _parse_counter_removal_cost(stream: TokenStream) -> ast.RemoveCounterCost:
    """``Remove a <kind> counter from this <permanent>`` (Scavenging Ghoul).

    The counter's name is read as free text, where ``_parse_put_counter``
    additionally rejects a P/T-shaped kind outside the four the engine knows.
    The difference is what happens downstream: a *put* is lowered onto a
    handler, so a P/T counter nothing implements would be silently
    mis-executed, while a cost is recorded and never lowered — the name is
    carried verbatim (CR 122.1 lets a counter have any name) and the
    surrounding words pin the structure.

    The subject must be the ability's own source: :class:`ast.RemoveCounterCost`
    has no subject field, so "remove a counter from target creature" would be
    consumed and then read as the source's counter. That refuses instead.
    """
    stream.expect_word("remove")
    count = ast.Fixed(1) if stream.accept_word("a", "an") else parse_amount(stream)
    counter = _expect_counter_kind(stream, " to remove").text
    stream.expect_word("counter", "counters")
    stream.expect_word("from")
    subject = _parse_cost_object(stream, "remove a counter from")
    if not subject.is_source:
        raise stream.error("a counter-removal cost only reads the ability's own source")
    return ast.RemoveCounterCost(counter, count)


def _parse_costs(stream: TokenStream) -> tuple[ast.Cost, ...]:
    """Parse the cost clause left of an activated ability's colon."""
    costs: list[ast.Cost] = []
    pips: dict[str, int] = {}
    while True:
        token = stream.accept_kind(MANA)
        if token is not None:
            symbol = token.text.strip("{}")
            if symbol == "T":
                costs.append(ast.TapSelf())
            elif symbol.isdigit():
                pips["generic"] = pips.get("generic", 0) + int(symbol)
            elif symbol in ("W", "U", "B", "R", "G", "C"):
                pips[symbol] = pips.get(symbol, 0) + 1
            elif symbol == "X":
                pips["X"] = pips.get("X", 0) + 1
            else:
                raise stream.error(f"unsupported mana symbol {token.text!r}")
            stream.accept_punct(",")
            continue
        if stream.accept_word("sacrifice"):
            costs.append(ast.SacrificeCost(_parse_cost_object(stream, "sacrifice")))
            stream.accept_punct(",")
            continue
        if stream.accept_word("exile"):
            # ``ExileSelf`` names no object, so exiling anything else would be
            # consumed and then read as the source leaving the battlefield.
            exiled = _parse_cost_object(stream, "exile")
            if not exiled.is_source:
                raise stream.error("only exiling the ability's own source is a known cost")
            costs.append(ast.ExileSelf())
            stream.accept_punct(",")
            continue
        if stream.at_word("remove"):
            costs.append(_parse_counter_removal_cost(stream))
            stream.accept_punct(",")
            continue
        if stream.at_word("discard"):
            # Only the one wording the engine can charge. A generic "Discard a
            # card" cost has no field on ``ActivatedAbilityCost``, so accepting
            # it would describe a payment nothing collects — and no card in the
            # pool prints it, which makes it untestable surface area besides.
            stream.advance()
            if not stream.accept_phrase("the", "last", "card", "you", "drew", "this", "turn"):
                raise stream.error("unrecognized discard cost")
            costs.append(ast.DiscardCost(ast.Fixed(1), last_drawn=True))
            stream.accept_punct(",")
            continue
        break
    if pips:
        costs.insert(0, ast.ManaCost(tuple(sorted(pips.items()))))
    if not stream.exhausted:
        raise stream.error("unrecognized activation cost")
    return tuple(costs)


def _split_on_colon(tokens: tuple) -> int | None:
    for index, token in enumerate(tokens):
        if token.kind == PUNCT and token.text == ":":
            return index
    return None


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        # "…casts a *blue* spell" (the Rod/Cup/Sphere cycle). The colour is part
        # of the condition rather than a per-card hook, which is what lets one
        # dispatcher serve every card written this way.
        mark = stream.mark()
        if stream.accept_phrase("a", "player", "casts", "a"):
            colour = stream.peek_word()
            if colour in COLOR_WORDS:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "spell_cast", "whenever",
                        subject=ast.ObjectFilter(colors=(COLOR_WORDS[colour],)),
                    )
        stream.reset(mark)
        for kind, phrase in _WHENEVER_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "whenever")
        return None
    if stream.accept_word("at"):
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        if stream.accept_phrase("this", "creature", "dies"):
            return ast.TriggerEvent("dies", "when")
        if stream.accept_phrase("you", "control", "no", "islands"):
            return ast.TriggerEvent("no_islands", "when")
        if stream.accept_phrase("you", "control", "no", "lands"):
            return ast.TriggerEvent("no_lands", "when")
        mark = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                stream.accept_word("creature", "artifact", "enchantment", "land", "aura")
            if stream.accept_word("enters"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("enters_battlefield", "when")
            if stream.accept_word("leaves"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("leaves_battlefield", "when")
        stream.reset(mark)
        return None
    return None


def _parse_become_color(stream: TokenStream, subject: ast.Recipient) -> ast.BecomeColor:
    """"<subject> becomes <colour>." The colour is the whole effect, so an
    unrecognized word after "becomes" must fail rather than be skipped."""
    stream.expect_word("becomes")
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word not in COLOR_WORDS:
        raise stream.error("expected a colour after 'becomes'")
    stream.advance()
    return ast.BecomeColor(subject, COLOR_WORDS[word])


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


def _parse_activation_restriction(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "Activate only …" / "Any player may activate this ability."
    sentence on an activated ability.

    Recorded on the AST and lowered to nothing. The restriction is *enforced*
    from the raw ability text in ``mixins/stack/activation.py``, which reads
    ``ability.source_line`` — so consuming the sentence here drops no behaviour,
    it only lets the line satisfy the grammar's full-consumption invariant
    instead of failing and sending the whole ability back to the legacy rules.
    """
    mark = stream.mark()
    stream.accept_punct(".", ";")
    words: list[str] = []
    if stream.accept_word("activate"):
        words.append("activate")
    elif stream.accept_phrase("any", "player", "may", "activate"):
        words.extend(["any", "player", "may", "activate"])
    elif stream.accept_phrase("only", "this", "creature", "'s", "owner", "may", "activate"):
        words.extend(["only", "this", "creature", "'s", "owner", "may", "activate"])
    else:
        stream.reset(mark)
        return None
    # Consume the remainder of the sentence verbatim; the enforcing code reads
    # the original text, so the grammar only has to account for the tokens.
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    stream.accept_punct(".")
    return ast.ActivationRestriction(" ".join(words))


def _statements_from_sentences(stream: TokenStream) -> ast.Statement:
    """Parse the remaining tokens as one or more sentences, joining them into a
    ``Sequence``. A rider sentence folds into the effect it modifies instead of
    becoming a step of its own."""
    steps: list[ast.Statement] = []
    while not stream.exhausted:
        if stream.accept_punct(".", ";", ","):
            continue

        if steps:
            riders = _parse_damage_rider_sentence(stream)
            if riders is not None:
                steps[-1] = _attach_riders(steps[-1], riders)
                continue
            penalty = _parse_unpaid_penalty_sentence(stream)
            if penalty is not None:
                steps[-1] = _attach_unpaid_penalty(steps[-1], penalty)
                continue
            if _attach_if_you_do(stream, steps):
                continue
            # A trailing "Activate only during your upkeep." belongs to the
            # ability, not to the effect. Consuming it here keeps the line
            # fully accounted for; enforcement stays on the raw text.
            if _parse_activation_restriction(stream) is not None:
                continue

        steps.append(parse_statement(stream))
        if not stream.exhausted and not stream.at_punct(".", ";"):
            raise stream.error("unconsumed text")

    if not steps:
        raise GrammarError("empty line", line=stream.line)
    return steps[0] if len(steps) == 1 else ast.Sequence(tuple(steps))


def _attach_if_you_do(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If you do, …" / "If you don't, …" into the preceding ``May``.

    These are branches of the optional action, not steps of their own: "You may
    pay {1}. If you do, you gain 1 life." is one decision with a consequence.
    Parsing them as separate sentences would make the life gain unconditional —
    the same class of mistake as treating "you may pay {2}" as a plain cost.
    """
    if not isinstance(steps[-1], ast.May):
        return False
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    if not stream.accept_word("you"):
        stream.reset(mark)
        return False

    if stream.accept_word("do"):
        declined = False
    elif stream.accept_word("don't") or stream.accept_phrase("do", "not"):
        declined = True
    else:
        stream.reset(mark)
        return False

    stream.accept_punct(",")
    try:
        branch = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False

    may = steps[-1]
    steps[-1] = ast.May(
        actor=may.actor,
        cost=may.cost,
        action=may.action,
        then=branch if not declined else may.then,
        otherwise=branch if declined else may.otherwise,
    )
    return True


def _attach_unpaid_penalty(statement: ast.Statement, penalty: str) -> ast.Statement:
    """Fold "If that player doesn't, …" into the "unless … pays" it belongs to.

    Raises when there is no such effect to attach to. A penalty for declining a
    cost that was never offered is not something the grammar can place, and
    consuming the sentence anyway is precisely the dropped-rider bug the
    full-consumption invariant exists to prevent.
    """
    if isinstance(statement, ast.CounterSpell) and statement.unless_pays is not None:
        return ast.CounterSpell(statement.subject, statement.unless_pays, penalty)
    raise GrammarError("an unpaid-cost penalty with no cost to decline")


def _attach_riders(statement: ast.Statement, riders: ast.DamageRiders) -> ast.Statement:
    """Fold damage riders into the most recent DealDamage of *statement*."""
    if isinstance(statement, ast.DealDamage):
        merged = ast.DamageRiders(
            no_regen=statement.riders.no_regen or riders.no_regen,
            exile_if_dies=statement.riders.exile_if_dies or riders.exile_if_dies,
            divided=statement.riders.divided,
            divided_evenly=statement.riders.divided_evenly,
        )
        return ast.DealDamage(
            statement.source, statement.amount, statement.recipients, merged, statement.chooser
        )
    if isinstance(statement, ast.Sequence) and statement.steps:
        steps = list(statement.steps)
        steps[-1] = _attach_riders(steps[-1], riders)
        return ast.Sequence(tuple(steps))
    if isinstance(statement, ast.Conjunction) and statement.effects:
        effects = list(statement.effects)
        effects[0] = _attach_riders(effects[0], riders)
        return ast.Conjunction(tuple(effects))
    raise GrammarError("damage rider with no damage effect to attach to")


def _looks_static(statement: ast.Statement) -> bool:
    """A continuous effect with no duration on a non-targeted subject is a
    static ability.

    A *conjunction* of them is one too — "Other Goblins get +1/+1 and have
    mountainwalk" is a single static ability with two halves, not a spell
    effect. It reached ``SpellEffectLine`` only because this predicate looked at
    one effect at a time, which put the lord lines on a different lowering path
    from the anthem lines that say exactly the same kind of thing.
    """
    if isinstance(statement, ast.Conjunction):
        return bool(statement.effects) and all(
            _looks_static(effect) for effect in statement.effects
        )
    if isinstance(statement, ast.Pump):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    if isinstance(statement, (ast.GainKeyword, ast.LoseKeyword)):
        return statement.duration.kind is None and (
            not isinstance(statement.subject, ast.TargetSpec)
            or statement.subject.quantifier not in ("target", "up_to")
        )
    return False


def _parse_static_condition_line(stream: TokenStream) -> ast.StaticAbilityNode | None:
    """``<continuous effect> as long as <condition>.`` (CR 613, Sedge Troll,
    Kird Ape, Giant Tortoise.)

    The condition lands on :class:`ast.StaticAbilityNode` rather than becoming
    an ``ast.Conditional``, and the distinction is the whole content of the
    sentence. A ``Conditional`` lowers to ``if_then``: tested once, and if it
    holds the effect happens and then stays. "As long as" says the bonus exists
    exactly while the condition does — it appears and disappears with the
    Swamp. Reading one as the other gives a Kird Ape that keeps +1/+2 after its
    Forest is destroyed.

    Nothing here lowers. ``lower_ability`` refuses every ``StaticAbilityNode``
    until the CR 613 layers engine exists (roadmap phase 6), and the engine
    keeps running these cards off the compiler's static-line path exactly as it
    did. What the production buys is a backlog that points at the right thing —
    the lines move out of "unconsumed text", which reads as a parser gap, into
    the phase they are actually waiting on — plus an AST for phase 6 to lower
    instead of a sentence to re-read.

    Every one of the three gates below can only *reduce* what this claims: an
    unmodelled condition, a token left over, or an effect that is not
    continuous all send the line back to the ordinary path untouched.
    """
    mark = stream.mark()
    try:
        statement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("as", "long", "as"):
        stream.reset(mark)
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.exhausted or not _looks_static(statement):
        stream.reset(mark)
        return None
    return ast.StaticAbilityNode(statement, condition)


def parse_line(line: str, *, card_name: str | None = None) -> ast.AbilityNode:
    """Parse one oracle-text line into an :class:`AbilityNode`.

    Raises :class:`GrammarError` when the line cannot be accounted for in full.
    """
    lexed = tokenize(line, card_name=card_name)
    if not lexed.tokens:
        raise GrammarError("empty line", line=line)

    # A single leading bullet is one mode's clause, handed here by
    # parse_modal_options; parse it as an ordinary effect line. A "choose one"
    # head or several bullets is a whole modal spell, which needs the mode
    # machinery in the compiler rather than this parser.
    bullets = sum(1 for token in lexed.tokens if token.kind == BULLET)
    start = 0
    if bullets == 1 and lexed.tokens[0].kind == BULLET:
        start = 1
    elif bullets or any(token.kind == DASH for token in lexed.tokens):
        raise GrammarError("modal line", line=line)
    if any(token.kind == QUOTE for token in lexed.tokens):
        raise GrammarError("granted ability in quotes", line=line)

    body = lexed.tokens[start:]
    stream = TokenStream(body, line)

    keywords = _is_keyword_line(stream)
    if keywords is not None and stream.exhausted:
        return ast.KeywordLine(keywords)
    stream.reset(0)

    # Lines a text-keyed registry runs off the raw oracle text. Checked against
    # the *original* line, not the lexed tokens: that is the string the
    # registries themselves match on.
    registry_line = _parse_registry_line(stream, line)
    if registry_line is not None:
        return registry_line
    stream.reset(0)

    colon = _split_on_colon(body)
    if colon is not None:
        costs = _parse_costs(TokenStream(body[:colon], line))
        effect_stream = TokenStream(body[colon + 1:], line)
        statement = _statements_from_sentences(effect_stream)
        return ast.ActivatedAbilityNode(costs, statement)

    event = _parse_trigger_event(stream)
    if event is not None:
        stream.accept_punct(",")
        intervening: ast.Condition | None = None
        if stream.at_word("if"):
            mark = stream.mark()
            stream.advance()
            try:
                intervening = _parse_condition(stream)
                stream.accept_punct(",")
            except GrammarError:
                stream.reset(mark)
                intervening = None
        statement = _statements_from_sentences(stream)
        return ast.TriggeredAbilityNode(event, statement, intervening)
    stream.reset(0)

    # "…as long as <condition>" is a whole-line shape: the condition qualifies
    # the ability, not one sentence of it. Tried before the sentence loop
    # because that loop would read the effect, find "as" unaccounted for, and
    # fail the line on unconsumed text.
    static_condition = _parse_static_condition_line(stream)
    if static_condition is not None:
        return static_condition

    statement = _statements_from_sentences(stream)
    if _looks_static(statement):
        return ast.StaticAbilityNode(statement)
    return ast.SpellEffectLine(statement)


__all__ = ["parse_line", "parse_statement"]
