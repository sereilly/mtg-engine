"""Mana: producing it, and changing what a permanent produces.

Split out of `effects/cards.py`, and named for the family `lowering/mana.py`
already carried. Three productions, and the axis between them is *whose* mana
and *when*:

    _parse_add_mana             "Add {G}" — the ability's own controller, now
    _parse_player_adds_mana     "…that player adds …" — a referent the enclosing
                                trigger binds
    _parse_produces_instead     "If target Plains is tapped for mana, it
                                produces … instead of …" — nothing now, and a
                                different symbol every time afterwards

`_parse_mana_multiplier` is shared between the first two and lives here for
that reason; nothing outside this family reads it.
"""

import dataclasses

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..lexer import (MANA, render)
from ..nouns import parse_object_filter
from ..references import parse_target_spec
from ..stream import TokenStream


def _parse_mana_multiplier(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``for each <objects>`` after a mana clause (Leafkin Avenger).

    A multiplier over the whole clause, read where the pips are so the two stay
    one statement: parsed apart, the count would be a sentence nothing performs
    and the mana would come out flat. Both pip spellings ask this, because
    "Add {G} for each …" and "Add two {G} for each …" differ only in how the
    symbols were written.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        return parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None


def _parse_source_counter_multiplier(stream: TokenStream) -> str | None:
    """``for each <kind> counter on this <noun>`` after a mana clause (City of
    Shadows), as the counter's printed kind.

    Read beside :func:`_parse_removed_counter_multiplier` and for its reason:
    the noun-phrase reader below would take "storage counter" as an object
    filter and then choke on "on this land", refusing a whole line the engine
    can answer.

    The counters are still *on the source* when this resolves, which is what
    separates it from the removed-this-way spelling one function down — those
    are gone by then, so the two clauses name numbers that differ by exactly
    what the cost ate.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    kind = stream.peek_word()
    if kind is not None and kind not in ("counter", "counters"):
        stream.advance()
        if stream.accept_word("counter", "counters") and stream.accept_word("on"):
            # "on **this** land" — the source, and nothing else. A counter on
            # some other permanent is a number this reads off the wrong object,
            # so the pronoun is required rather than assumed.
            if stream.accept_word("this") and stream.peek_word() is not None:
                stream.advance()
                return kind
    stream.reset(mark)
    return None


def _parse_removed_counter_multiplier(stream: TokenStream) -> str | None:
    """``for each <kind> counter removed this way`` after a mana clause (the
    five Mana Batteries), as the counter's printed kind.

    Read before :func:`_parse_mana_multiplier`, whose noun-phrase reader would
    take "charge counter" as an object filter and then choke on "removed this
    way" — leaving the whole line refused for a clause the engine can answer.

    "This way" is what makes it a *payment* rather than a board count: the
    counters were removed to pay this ability's own cost and are gone by the
    time the mana is added, so nothing on the battlefield can be counted.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    kind = stream.peek_word()
    if kind is not None and kind not in ("counter", "counters"):
        stream.advance()
        if (
            stream.accept_word("counter", "counters")
            and stream.accept_phrase("removed", "this", "way")
        ):
            return kind
    stream.reset(mark)
    return None


def _parse_add_mana(stream: TokenStream) -> ast.Statement:
    """``Add {G}`` / ``Add {C}{C}{C}`` / ``Add one mana of any color``."""
    start = stream.mark()
    stream.expect_word("add")

    def _clause() -> str:
        return render(stream.tokens[start:stream.pos])

    # "add **an additional** {B}" (the Mana Batteries). The word belongs to this
    # clause rather than to the pips, and it is recorded rather than dropped:
    # the sentence it appears in is "Add {B}, then add an additional {B} …", two
    # statements whose second one only makes sense as an addition to the first.
    additional = bool(stream.accept_phrase("an", "additional"))

    pips: dict[str, int] = {}
    choice = False
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
        # "{B} or {R}" — a dual land's choice, not two mana. The word is
        # *recorded* on the node, because a parse that merely consumed it would
        # read "Add {B} or {R}" and "Add {B}{R}" as the same clause.
        if stream.at_word("or"):
            mark = stream.mark()
            stream.advance()
            if not stream.at_kind(MANA):
                stream.reset(mark)
                break
            choice = True
    if pips:
        removed = _parse_removed_counter_multiplier(stream)
        on_source = (
            _parse_source_counter_multiplier(stream) if removed is None else None
        )
        return ast.AddMana(
            tuple(sorted(pips.items())),
            choice=choice,
            source_text=_clause(),
            additional=additional,
            per_each_counter_removed=removed,
            per_each_counter_on_source=on_source,
            per_each=(
                _parse_mana_multiplier(stream)
                if removed is None and on_source is None else None
            ),
        )

    # "Add **an amount of {B} equal to the sacrificed artifact's mana value**."
    # (Priest of Yawgmoth.) The amount is a back-reference to what the ability's
    # own sacrifice cost ate, which only the resolution holding that cost can
    # read (CR 608.2h) — so the node records *which* back-reference and the
    # handler does the arithmetic, the same split every other computed amount
    # in the grammar makes.
    #
    # Read before `parse_amount`, which would take "an" as the number one and
    # then fail on "amount" — a failure that says nothing about what the
    # sentence actually is.
    sacrificed_mark = stream.mark()
    if stream.accept_phrase("an", "amount", "of"):
        if stream.at_kind(MANA):
            symbol_token = stream.next()
            symbol = symbol_token.text.strip("{}")
            # "…equal to **that spell's** mana value." (Mana Drain.) The other
            # object this printed shape back-refers to; the noun is read rather
            # than skipped, because "that spell" and "that creature" would be
            # two different back-references and only one of them is recorded.
            if stream.accept_phrase("equal", "to", "that", "spell", "'s", "mana", "value"):
                return ast.AddMana(
                    (), source_text=_clause(), from_countered_spell=symbol,
                )
            # "…equal to **that creature's** mana value." (Energy Tap.) A
            # third referent for the same printed shape: the creature an
            # earlier sentence of this effect acted on. Read as either of the
            # two above it would name an object nothing recorded and add no
            # mana at all, so the noun is matched rather than skipped.
            if stream.accept_phrase(
                "equal", "to", "that", "creature", "'s", "mana", "value"
            ):
                return ast.AddMana(
                    (), source_text=_clause(), from_bound_creature=symbol,
                )
            if stream.accept_phrase("equal", "to", "the", "sacrificed") and stream.peek_word():
                # The noun repeats what the cost already named ("artifact"), so
                # it is consumed rather than re-read: the cost decided what was
                # sacrificed, and a second reading here could only disagree.
                stream.advance()
                if stream.accept_phrase("'s", "mana", "value"):
                    return ast.AddMana(
                        (),
                        source_text=_clause(),
                        from_sacrificed_cost=symbol,
                    )
        stream.reset(sacrificed_mark)

    count = parse_amount(stream)
    # "Add six {R}." (Chandra, Heart of Fire's −9) — a counted single symbol,
    # the same pips as "{R}{R}{R}{R}{R}{R}" spelled with a number word.
    if stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        amount = count.value if isinstance(count, ast.Fixed) else 0
        if amount <= 0:
            raise stream.error("expected a fixed number of mana symbols")
        return ast.AddMana(
            ((symbol, amount),),
            source_text=_clause(),
            per_each=_parse_mana_multiplier(stream),
        )

    # "Add one mana of any color" / "Add three mana of any one color".
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.accept_word("any")
    stream.accept_word("one")
    stream.expect_word("color")
    # "Add **X** mana of any one color" (Sanctum of Fruitful Harvest). The count
    # travels as the amount it was parsed as — it used to be forced to an int
    # here and a variable one refused, which was right while the handler read the
    # clause *text* and could only recognize the literal "one mana of any color".
    # The handler takes a number now, so any amount the enclosing sentence can
    # define is one it can add.
    # "…**that a land an opponent controls could produce**." (Fellwar Stone.)
    # A restriction on which colours the choice may name, not a second effect -
    # so it rides the same node, and a line printing words this cannot read
    # leaves them unconsumed and refuses (the full-consumption invariant) rather
    # than adding any colour at all.
    any_color_from = None
    if stream.accept_phrase(
        "that", "a", "land", "an", "opponent", "controls", "could", "produce"
    ):
        any_color_from = "opponent_lands"
    return ast.AddMana(
        (), any_color=count, source_text=_clause(), any_color_from=any_color_from
    )


def _parse_player_adds_mana(
    stream: TokenStream, recipient: ast.PlayerRef
) -> ast.AddManaForTappedLand:
    """``<player> adds an additional {R}`` / ``<player> adds one mana of any type
    that land produced`` — the effect half of a triggered mana ability on a land
    being tapped (Gauntlet of Might, Mana Flare).

    Distinct from :func:`_parse_add_mana`, whose bare "Add {G}" always means the
    ability's own controller. Here the subject is a *player reference* bound by
    the trigger, so the mana can land in someone else's pool, and "any type that
    land produced" names a quantity no pip list can express.
    """
    stream.expect_word("adds", "add")
    additional = bool(stream.accept_phrase("an", "additional"))

    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
    if pips:
        return ast.AddManaForTappedLand(
            recipient, pips=tuple(sorted(pips.items())), additional=additional
        )

    # "one mana of any type that land produced". Every word is read: "any type
    # **that land** produced" is what ties the mana to the land the trigger
    # names, and a production that skipped the tail would read the same as an
    # unrestricted "one mana of any type" — a strictly larger effect.
    count = parse_amount(stream)
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.expect_word("any")
    stream.expect_word("type")
    if not stream.accept_phrase("that", "land", "produced"):
        raise stream.error("expected 'that land produced'")
    amount = count.value if isinstance(count, ast.Fixed) else 0
    if amount <= 0:
        raise stream.error("expected a fixed amount of mana")
    return ast.AddManaForTappedLand(
        recipient, of_type_produced=amount, additional=additional
    )


# The colour words a "produces X instead of Y" clause may name, mapped to the
# symbol produced. "Colorless" is here rather than beside the five colours in
# `oracle_types` because {C} is not a colour (CR 105.1) — it is the *absence*
# of one, and only a clause about produced mana treats the two as alternatives
# in the same slot.
_PRODUCED_MANA_WORDS = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
    "colorless": "C",
}


def _parse_produced_mana_word(stream: TokenStream) -> str | None:
    """``<colour|colorless> mana`` — the symbol named, or None."""
    mark = stream.mark()
    word = stream.peek_word()
    symbol = _PRODUCED_MANA_WORDS.get(word or "")
    if symbol is None:
        return None
    stream.advance()
    if not stream.accept_word("mana"):
        stream.reset(mark)
        return None
    return symbol


def _parse_produces_instead(stream: TokenStream) -> "ast.ProducesManaInstead | None":
    """``If <object> is tapped for mana, it produces <X> mana instead of <Y> mana.``

    Quarum Trench Gnomes. Refuses without consuming, because "if" opens every
    intervening-if and every conditional sentence in the pool and this is one
    printed shape among them.

    Both symbols are read, in both slots. A production that consumed "instead
    of white mana" without recording the colour would read a card that swapped
    a land's *green* mana as though it swapped its white — and, worse, would
    fire on a land that never made white at all.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    try:
        target = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if target is None or not stream.accept_phrase("is", "tapped", "for", "mana"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    # "**it** produces" — the same object the condition named. Read rather than
    # skipped: a different subject here would be a different card.
    if not stream.accept_phrase("it", "produces"):
        stream.reset(mark)
        return None
    produced = _parse_produced_mana_word(stream)
    if produced is None or not stream.accept_phrase("instead", "of"):
        stream.reset(mark)
        return None
    replaced = _parse_produced_mana_word(stream)
    if replaced is None:
        stream.reset(mark)
        return None
    return ast.ProducesManaInstead(target, replaced=replaced, produced=produced)


def _parse_spend_mana_as_though(stream: TokenStream) -> "ast.SpendManaAsThough | None":
    """``For <N> spell(s) this turn, you may spend mana as though it were mana
    of any color/type to pay that spell's mana cost.``

    North Star. Refuses without consuming: "for" opens "for each …" and a
    dozen other clauses, and this production must add a reading rather than
    take one away.

    Every word after the comma is matched. The clause names *which* cost the
    permission covers — "that spell's **mana cost**" — and a production that
    stopped at "any type" would read the same as one covering the additional
    costs the reminder text explicitly excludes.
    """
    mark = stream.mark()
    if not stream.accept_word("for"):
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value <= 0:
        stream.reset(mark)
        return None
    if not (stream.accept_word("spell") or stream.accept_word("spells")):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn") or not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "you", "may", "spend", "mana", "as", "though", "it", "were", "mana", "of", "any"
    ):
        stream.reset(mark)
        return None
    # "any **type**" is CR 106.1b's five colours plus colorless; "any **color**"
    # is the five. Recorded rather than collapsed: the difference is whether a
    # {C} in the cost may be paid by coloured mana, and reading the narrower
    # word as the wider one makes a spell castable that is not.
    if stream.accept_word("type"):
        any_type = True
    elif stream.accept_word("color"):
        any_type = False
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "to", "pay", "that", "spell", "'s", "mana", "cost"
    ):
        stream.reset(mark)
        return None
    return ast.SpendManaAsThough(count=count.value, any_type=any_type)
