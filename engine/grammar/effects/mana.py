"""Mana: producing it.

Split out of `effects/cards.py`, and named for the family `lowering/mana.py`
already carried. The axis between the productions is *whose* mana and *when*:

    _parse_add_mana             "Add {G}" — the ability's own controller, now
    _parse_player_adds_mana     "…that player adds …" — a referent the enclosing
                                trigger binds
    _parse_activates_each_lands_mana_ability
                                "<player> activates a mana ability of each land
                                they control" — somebody else's lands, into
                                somebody else's pool
    _parse_loses_unspent_mana   "<player> loses all unspent mana" — the pool
                                emptied as an effect, and the amount recorded

`_parse_mana_multiplier` is shared between the first two and lives here for
that reason; nothing outside this family reads it.

**Changing what a permanent produces** left for
`effects/production_changes.py` at Urza's Destiny's Phase 0, along the seam the
first line of this docstring used to name in the same breath as producing. Its
three sentences add no mana at all — they record a standing swap (CR 611.2) a
mana ability reads back later — where every production below counts pips,
multipliers and amounts. That module carries the reason the line is there.
"""


from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..lexer import (MANA, render)
from ..nouns import parse_object_filter
from ..records import accept_counters_removed_for_cost
from ..references import parse_player_ref
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

    The phrase itself is ``records.accept_counters_removed_for_cost``'s, and
    this is the "for each" front end of it. It used to be a private copy, which
    is the fork the shared reader was written to close: Essence Bottle prints
    the identical clause after a *life gain* and Torture Chamber after a
    *damage*, so which sentences could read the words depended on what the card
    did with the number. What stays here is the leading "for each" and the
    unwrapping to a bare kind, both of which are this family's payload shape.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    removed = accept_counters_removed_for_cost(stream)
    if removed is not None:
        return removed.counter
    stream.reset(mark)
    return None


def _parse_combination_symbols(stream: TokenStream) -> tuple[str, ...]:
    """``{R} and/or {G}`` — the symbols an "in any combination of" clause lists.

    The lexer splits "and/or" into the two words, so the separator is read as
    either or both. Every listed symbol must be a colour or {C}: a generic or
    variable symbol here would name a quantity rather than a kind of mana, and
    the payload it produced would be a colour nothing can add.

    At least two, because "in any combination of {R}" is not a combination — a
    single-symbol list is "Add N {R}" with extra words, and admitting it here
    would give the same clause two readings.
    """
    symbols: list[str] = []
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol not in ("W", "U", "B", "R", "G", "C"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        if symbol not in symbols:
            symbols.append(symbol)
        # "and/or", "and" or "or" — the separator between two alternatives, in
        # whichever of the three spellings the card prints.
        joined = stream.accept_word("and")
        joined = stream.accept_word("or") or joined
        if not joined:
            break
    if len(symbols) < 2:
        raise stream.error("a mana combination lists at least two symbols")
    return tuple(symbols)


def _parse_note_mana_spent(stream: TokenStream) -> "ast.NoteManaSpent | None":
    """``Note the type [and amount] of mana spent to pay this activation cost.``
    (Jeweled Amulet, Ice Cauldron.)

    Every word is read. "to pay **this activation cost**" is what says the
    record is of the ability's own payment rather than of anything else the turn
    spent, and a production that stopped at "of mana spent" would claim a
    sentence about some other payment and note the wrong symbols.

    None rather than a raise, so a sentence opening with "note" that this cannot
    read keeps whatever other production would have had it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("note", "the", "type"):
        stream.reset(mark)
        return None
    with_amount = bool(stream.accept_phrase("and", "amount"))
    if stream.accept_phrase(
        "of", "mana", "spent", "to", "pay", "this", "activation", "cost"
    ):
        return ast.NoteManaSpent(with_amount=with_amount)
    stream.reset(mark)
    return None


def _accept_noted_mana(stream: TokenStream) -> str | None:
    """``[one mana of] this <noun>'s last noted type [and amount] [of mana]``.

    Both printed spellings of the same record, read by one function so the two
    cards cannot come to disagree about what "last noted" means: Jeweled Amulet
    adds "one mana of this artifact's last noted **type**", Ice Cauldron adds
    "this artifact's last noted **type and amount** of mana".

    The noun is consumed rather than matched, for ``_parse_counter_removal_cost``'s
    reason: "this artifact" names the ability's own source and nothing about the
    permanent's characteristics is consulted.
    """
    mark = stream.mark()
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("'s", "last", "noted", "type"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("and", "amount", "of", "mana"):
        return "type_and_amount"
    return "type"


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

    # "Add **this artifact's last noted type and amount** of mana." (Ice
    # Cauldron.) Read before the pip loop because the clause names no mana
    # symbol at all — the quantity *is* the record, so there is nothing here for
    # the loop or for `parse_amount` below to count.
    noted = _accept_noted_mana(stream)
    if noted is not None:
        return ast.AddMana((), from_noted=noted, source_text=_clause())

    # "…and you add **the mana lost this way**." (Drain Power.) No symbol and
    # no count: what is added is exactly the mana an earlier step of this same
    # effect emptied out of a pool, colour for colour. Read before the pip loop
    # for `_accept_noted_mana`'s reason above — the clause names no mana symbol
    # for the loop to find.
    if stream.accept_phrase("the", "mana", "lost", "this", "way"):
        return ast.AddMana(
            (), mana_lost_in_kind=True, source_text=_clause(),
        )

    pips: dict[str, int] = {}
    choice = False
    # One dict per alternative of a printed "or", in printed order. Kept apart
    # rather than merged away, because the older payload can express a choice
    # only between **single** symbols: `pips_choice` is ``(symbol, count)``
    # pairs, one per alternative, which says "one of these colours" and cannot
    # say "{U}, or {C} and {U} together". Every dual land in the pool is the
    # first shape; Adarkar Unicorn ("Add {U} or {C}{U}") is the first card that
    # is not, and merging it produced a bag reading "either one {C} or two {U}"
    # — neither of the two things the card prints. A run longer than one symbol
    # therefore ships as `runs_choice`, its own key, and `pips` stays empty.
    runs: list[dict[str, int]] = [{}]
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
        runs[-1][symbol] = runs[-1].get(symbol, 0) + 1
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
            runs.append({})
    if choice and any(len(run) != 1 or sum(run.values()) != 1 for run in runs):
        # At least one alternative is a written-out quantity rather than a bare
        # colour, so the whole choice goes down the `runs_choice` branch: the
        # alternatives are pip lists and the seat picks one of them entire.
        return ast.AddMana(
            (),
            runs_choice=tuple(tuple(sorted(run.items())) for run in runs),
            source_text=_clause(),
            additional=additional,
        )
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
            # "…equal to **the amount of mana that player lost this way**."
            # (Pygmy Hippo.) A fourth referent for this printed shape, and the
            # first that is not a mana value: the number is how much an earlier
            # step of this effect emptied out of the named seat's pool. Every
            # word is matched — "that player" is the seat the same sentence
            # drained, and a production that stopped at "the amount of mana"
            # would read a quantity nobody recorded.
            if stream.accept_phrase(
                "equal", "to", "the", "amount", "of", "mana", "that", "player",
                "lost", "this", "way",
            ):
                return ast.AddMana(
                    (), source_text=_clause(), from_mana_lost=symbol,
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
    # "Add three mana **in any combination of {R} and/or {G}**" (Orcish
    # Lumberjack); "Add X mana in any combination of {B} and/or {R}" (Burnt
    # Offering). Read before the "of any color" branch below, which the words
    # would otherwise refuse on "in" — a per-unit choice among *named* symbols,
    # which is neither "any colour" (unrestricted, one choice for the whole
    # clause) nor a choice between written-out quantities.
    if stream.accept_phrase("in", "any", "combination", "of"):
        symbols = _parse_combination_symbols(stream)
        return ast.AddMana(
            (),
            combination=symbols,
            combination_count=count,
            source_text=_clause(),
        )
    stream.expect_word("of")
    # "Add one mana of **this artifact's last noted type**." (Jeweled Amulet.)
    # Read before "any … color", which would refuse the pronoun. The printed
    # count is the amount already parsed, and only "one" is admitted: the record
    # holds one type, and a card asking for two of it would be adding a quantity
    # nothing noted.
    noted = _accept_noted_mana(stream)
    if noted is not None:
        if not (isinstance(count, ast.Fixed) and count.value == 1):
            raise stream.error("only one mana of a noted type can be added")
        return ast.AddMana((), from_noted=noted, source_text=_clause())
    # "Add one mana of **the chosen color**." (Sol Grail.) Read before the
    # "any … color" branch, which refuses on the article: this is not a colour
    # the activating player names, it is the one the artifact recorded as it
    # entered, so the two must not share a node field however alike they read.
    # Only "one" is admitted, for `_accept_noted_mana`'s reason above — the
    # record holds a colour and not a quantity, so a card asking for two of it
    # would be adding a number nothing chose.
    if stream.accept_phrase("the", "chosen", "color"):
        if not (isinstance(count, ast.Fixed) and count.value == 1):
            raise stream.error("only one mana of the chosen color can be added")
        return ast.AddMana((), from_chosen_color=True, source_text=_clause())
    stream.accept_word("any")
    stream.accept_word("one")
    # "Add one mana of any **type that land could produce**." (Benthic
    # Explorers.) Read before the colour branch, which would refuse the word:
    # CR 106.1b's six *types* are the five colours plus colourless, so a phrase
    # printing "type" is asking for a strictly larger set than one printing
    # "color" and the two cannot share a branch. Every word after it is
    # required — the phrase names the land the ability's own cost untapped, and
    # a production that consumed "type" and stopped would add a colour of the
    # payer's choosing off any land at all.
    if stream.accept_word("type"):
        # Which land the phrase names is which payment the ability's own cost
        # made: "that land" is the one it untapped (Benthic Explorers), "the
        # sacrificed land" the one it ate (Squandered Resources). Two printed
        # phrases, two back-references, one node field -- and the *value* is
        # what the lowering gates on, so a card printing either on an ability
        # whose cost makes no such payment is refused rather than adding a
        # colour off a land nobody named.
        if stream.accept_phrase("that", "land", "could", "produce"):
            reference = "cost_untapped_land"
        elif stream.accept_phrase("the", "sacrificed", "land", "could", "produce"):
            reference = "cost_sacrificed_land"
        elif stream.accept_phrase(
            "that", "a", "land", "you", "control", "could", "produce"
        ):
            # "…of any type **that a land you control** could produce."
            # (Reflecting Pool.) A described *board* rather than a
            # back-reference to what this ability's cost paid, which is why it
            # rides its own node field: the two back-references above are
            # refused on an ability whose cost makes no such payment, and this
            # sentence makes none to refuse. The mirror of Fellwar Stone's
            # colour phrase one branch below, one CR 106.1b type wider.
            return ast.AddMana(
                (), any_color=count, source_text=_clause(),
                any_type_from_lands="controlled_lands",
            )
        else:
            raise stream.error(
                "the only mana type this reads is one a named land could produce"
            )
        return ast.AddMana(
            (), any_color=count, source_text=_clause(),
            any_type_from=reference,
        )
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


def _parse_pip_run(stream: TokenStream) -> dict[str, int]:
    """A run of written-out mana symbols at the cursor, as ``{symbol: count}``.

    Shared by the base clause and its snow alternative below, which read the
    same run in two sentences of one printed ability.
    """
    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
    return pips


def _parse_supertype_alternative(
    stream: TokenStream, recipient: ast.PlayerRef
) -> "tuple[str, tuple[tuple[str, int], ...]] | None":
    """``. If that <noun> is <supertype>, <player> may add an additional <pips>
    instead`` — Snowfall's second sentence, as ``(supertype, pips)``.

    Read here rather than as a step of its own or as `riders`'
    conditional-instead fold, and the reason is the same one that keeps the
    spend restriction out of the statement list: the whole printed ability is
    **one triggered mana ability** (CR 605.4a), fired inline by the tap seam
    off a single instruction. A `Conditional` wrapping two mana productions
    would hide both of them from the only code that runs them.

    Every word is required and non-consuming on refusal:

    * the noun is checked against the land-type catalog (``data/vocabulary/``)
      or the bare word "land", because "that Island" can only mean the land the
      enclosing trigger named — an alternative about anything else is a
      sentence this cannot place;
    * the recipient must be the **same** reference the base clause names, since
      one bucket of mana is produced and a second seat would be a second
      production;
    * "instead" is required, because without it the sentence *adds* to the base
      clause rather than replacing it, and reading one as the other doubles or
      halves the mana.
    """
    from ..vocabulary import LAND_TYPES, TYPE_LINE_SUPERTYPES

    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    if not stream.accept_phrase("if", "that"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun is None or (noun != "land" and noun not in LAND_TYPES):
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("is"):
        stream.reset(mark)
        return None
    supertype = stream.peek_word()
    if supertype is None or supertype not in TYPE_LINE_SUPERTYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    alt_recipient = parse_player_ref(stream)
    if alt_recipient != recipient:
        stream.reset(mark)
        return None
    if not stream.accept_word("may"):
        stream.reset(mark)
        return None
    if not stream.accept_word("add", "adds"):
        stream.reset(mark)
        return None
    stream.accept_phrase("an", "additional")
    pips = _parse_pip_run(stream)
    if not pips or not stream.accept_word("instead"):
        stream.reset(mark)
        return None
    return supertype, tuple(sorted(pips.items()))


def _parse_spend_restriction(stream: TokenStream) -> str | None:
    """``. Spend this mana only to …`` — the restriction key, or None.

    The same delegation `riders._attach_spend_only` makes for the ordinary
    "Add {G}" clause, made here because this production reads its own sentences
    to the end: which restrictions exist is `engine/restricted_mana.py`'s
    question, asked through its matcher so a copy of the phrase cannot drift
    from the predicate that enforces it.
    """
    from ...restricted_mana import mana_restriction_for

    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    start = stream.pos
    while not stream.exhausted and not stream.at_punct(".", ";"):
        stream.advance()
    restriction = mana_restriction_for(stream.text_between(start, stream.pos))
    if restriction is None:
        stream.reset(mark)
        return None
    return restriction.key


def _parse_player_adds_mana(
    stream: TokenStream, recipient: ast.PlayerRef, *, optional: bool = False
) -> ast.AddManaForTappedLand:
    """``<player> adds an additional {R}`` / ``<player> adds one mana of any type
    that land produced`` — the effect half of a triggered mana ability on a land
    being tapped (Gauntlet of Might, Mana Flare).

    Distinct from :func:`_parse_add_mana`, whose bare "Add {G}" always means the
    ability's own controller. Here the subject is a *player reference* bound by
    the trigger, so the mana can land in someone else's pool, and "any type that
    land produced" names a quantity no pip list can express.

    *optional* is the printed "may" the caller has already consumed
    (`subject_verb`), recorded on the node rather than dropped.

    **The pip form reads its own trailing sentences.** Snowfall prints three —
    the base production, a snow alternative that replaces it, and the
    restriction on what the mana may pay for — and all three are one triggered
    mana ability (CR 605.4a). Parsed apart, the second would add on top of the
    first instead of replacing it and the third would be an effect nothing
    performs.
    """
    if recipient.kind == "you" and not optional:
        # "…**you add** an amount of {C} equal to …" (Pygmy Hippo), "…and
        # **you add** the mana lost this way" (Drain Power). The subject is
        # the ability's own controller, which is exactly what the bare
        # imperative "Add {C}" means — so it is the same production, and the
        # printed pronoun is the only difference. Read here rather than in
        # `subject_verb`, because this is the function that knows what its
        # node can express: `AddManaForTappedLand` has no "you" recipient at
        # all (`_TAPPED_LAND_MANA_RECIPIENTS` holds "that player" and "its
        # controller"), so every such sentence refused at lowering with a
        # message about a trigger the card does not print.
        return _parse_add_mana(stream)
    stream.expect_word("adds", "add")
    additional = bool(stream.accept_phrase("an", "additional"))

    pips = _parse_pip_run(stream)
    if pips:
        alternative = _parse_supertype_alternative(stream, recipient)
        alt_supertype, alt_pips = alternative or (None, ())
        return ast.AddManaForTappedLand(
            recipient, pips=tuple(sorted(pips.items())), additional=additional,
            optional=optional, alt_supertype=alt_supertype, alt_pips=alt_pips,
            spend_only=_parse_spend_restriction(stream),
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
        recipient, of_type_produced=amount, additional=additional,
        optional=optional,
    )


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


def _parse_activates_each_lands_mana_ability(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.ActivateEachLandsManaAbility | None":
    """``<player> activates a mana ability of each land they control``
    (Drain Power, Pygmy Hippo).

    The subject has already been read and the verb is the current token, which
    is the shape every player-action production in ``subject_verb`` has.
    Declines **without consuming** on anything else: "activate" opens sentences
    this has no business claiming (a cost, a restriction on when an ability may
    be activated), and one it cannot finish keeps the refusal the line had.

    Every word after the verb is required. "A mana ability" is CR 605.1a's
    class, "each land" is which permanents, and "they control" is whose board —
    a production that consumed "a mana ability" and stopped would read Pygmy
    Hippo's clause as being about the *ability's controller's* lands, which is
    the opposite board.
    """
    mark = stream.mark()
    stream.expect_word("activates", "activate")
    if not stream.accept_phrase(
        "a", "mana", "ability", "of", "each", "land", "they", "control"
    ):
        stream.reset(mark)
        return None
    return ast.ActivateEachLandsManaAbility(player)


def _parse_loses_unspent_mana(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.LoseUnspentMana | None":
    """``<player> loses all unspent mana`` (Drain Power, Mana Short, Pygmy
    Hippo).

    Read in front of ``_parse_loses``, which is about life and keywords, and
    declining without consuming so that every other "loses …" keeps its own
    reading. The word "unspent" is matched rather than skipped: mana in a pool
    is by definition unspent, but the clause is what the card prints and a
    production that dropped the word could not tell it from a sentence about
    mana somewhere else.
    """
    mark = stream.mark()
    stream.expect_word("loses", "lose")
    if not stream.accept_phrase("all", "unspent", "mana"):
        stream.reset(mark)
        return None
    return ast.LoseUnspentMana(player)

