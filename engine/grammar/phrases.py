"""Phrase-level vocabularies and the productions that read a *fragment*.

The bottom of the parser: word tables — trigger events, durations, counter
kinds, board counts, zone names — and the handful of productions that consume
part of a sentence rather than a whole one. Everything above imports from here
and nothing here imports back.

`_parse_zone` and `_parse_mana_payment` live here rather than with the effects
for a reason worth keeping: they were the *only* references crossing between
effect families ("search your library" needs a zone, "unless they pay" needs a
cost). A fragment two families need is not an effect, and filing it as one is
what couples them.

Kept as data plus a reader rather than as branches inside the productions that
use them: a table is a thing a new card is added to, a branch is a thing that
has to be found first.
"""

from dataclasses import replace

from ..pt import pt_counter_deltas
from . import ast
from .errors import GrammarError
from .lexer import (MANA, PUNCT, tokenize)
from .nouns import parse_object_filter
from .references import parse_target_spec
from .stream import TokenStream
from .vocabulary import (KEYWORD_INDEX, NUMBER_WORDS, match_longest)
_DURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # "for as long as this artifact remains tapped" (Ashnod's Battle Gear,
    # Tawnos's Weaponry). A *linked* duration: it ends when the source untaps
    # or leaves, so nothing schedules its removal — the effect is contributed
    # while the condition holds and simply stops being contributed when it does
    # not, which is CR 611.3b's "removal is the absence of a contribution".
    # The noun is any permanent word, because the card printing it says what it
    # is and the duration does not care.
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "artifact", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "creature", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "permanent", "remains", "tapped")),
    ("until_end_of_turn", ("until", "end", "of", "turn")),
    ("until_end_of_combat", ("until", "end", "of", "combat")),
    ("until_your_next_turn", ("until", "your", "next", "turn")),
    # "Until your next upkeep" (Xenic Poltergeist). Longer than its own prefix
    # is not the issue here — "until your next turn" and "until your next
    # upkeep" diverge at the last word — but they are different moments (CR 500:
    # the upkeep step is inside the turn), so they are different kinds and the
    # one nothing implements must not fall back to the one that is close.
    ("until_your_next_upkeep", ("until", "your", "next", "upkeep")),
    # "Until the end of your next upkeep" (Halfdane). A step *later* than the
    # entry above: "until your next upkeep" ends as that upkeep begins, this
    # one ends as it ends — which is the whole trick of the card printing it,
    # whose own upkeep trigger re-applies the effect before the old one runs
    # out. Different moments, so different kinds, for the reason the comment
    # above gives about turns and upkeeps.
    ("until_end_of_your_next_upkeep",
     ("until", "the", "end", "of", "your", "next", "upkeep")),
    ("this_turn", ("this", "turn")),
)

def is_pt_counter(kind: str) -> bool:
    """Whether *kind* names a CR 122.1a power/toughness counter.

    The one table in this file that is *not* data: CR 122.1a names a counter by
    the P/T it carries ("a +X/+Y counter … similarly, -X/-Y counters subtract"),
    so which ones exist is a rule and `engine/pt.py` derives the pair from the
    name. The tuple that used to sit here held four kinds and refused "-0/-2"
    (Spirit Shackle) and "-0/-1" (Takklemaggot, Lesser Werewolf) as unsupported
    counter kinds while admitting "-1/-1" beside them — a parser deciding what
    Magic prints.
    """
    return pt_counter_deltas(kind) is not None

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


# Moved here from `effects/characteristics.py` the day a second family needed
# it: "you gain 1 life **for each creature that died this turn**" (Canopy
# Stalker) is the life family asking exactly the question the counter family
# was already asking. A fragment two families want lives in `phrases`, never
# in one of them — that coupling is what makes the grouping stop being
# information, and the layering guard fails on it.
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


def parse_subject_filter(phrase: str, *, plural: bool = False) -> ast.ObjectFilter | None:
    """The set of objects a printed noun phrase names, or None if it refuses.

    The whole phrase must be consumed. That is what makes this safe to give a
    *trigger* its subject: "a creature you control with deathtouch" is a
    narrowing, and a reader that consumed "a creature you control" and stopped
    would announce a trigger firing on a strictly larger set than the card
    prints — the dropped-rider bug class, in the one position where it fires on
    every creature instead of one.

    Public because ``engine/oracle.py``'s trigger-condition table reads its
    subjects through this: both front ends of the pipeline turn one printed
    phrase into one filter, rather than a regex approximating what the noun
    parser does. Held to that by
    ``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides``.

    *plural* is for the one position where the noun phrase is **counted** rather
    than quantified: "whenever you attack with two or more **creatures with
    flying**" (Tide Skimmer). A bare plural is the noun parser's "all", which
    everywhere else would be a sweep and is refused for that reason — here the
    count in front of it is what says how many, so the phrase names a kind and
    "all" is the right reading of it.
    """
    lexed = tokenize(phrase)
    if not lexed.tokens:
        return None
    stream = TokenStream(lexed.tokens, phrase)
    filt = parse_subject_filter_at(stream, plural=plural)
    return filt if filt is not None and stream.exhausted else None


def parse_subject_filter_at(
    stream: TokenStream, *, plural: bool = False
) -> ast.ObjectFilter | None:
    """:func:`parse_subject_filter` over a stream, consuming what it reads.

    Refuses anything but the two articles a trigger subject is printed with —
    "a creature you control …" and "another Rogue you control …". "Target
    creature" and "each creature" name a chosen or an exhaustive set, and a
    condition claiming to fire on one of those would be describing a different
    card. *plural* swaps the admitted quantifier for the counted position; see
    :func:`parse_subject_filter`.
    """
    mark = stream.mark()
    # "another" sits where the article does, so it is read here and folded onto
    # the filter's exclusion field — the idiom `_parse_cost_object` and the
    # counters event above already use, rather than a noun-parser quantifier
    # that would change every targeted line in the pool. It leaves a bare noun
    # behind ("another **Rogue you control**"), which the noun parser quantifies
    # as the sweep "all"; without "another" the article has to be printed.
    another = bool(stream.accept_word("another"))
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if spec is None or spec.quantifier != ("all" if (another or plural) else "a"):
        stream.reset(mark)
        return None
    return replace(spec.filter, other_than_source=True) if another else spec.filter


def _accept_number(stream: TokenStream) -> int | None:
    """A printed number word, consumed. None (nothing consumed) for anything
    else, so the caller can reset and try the next production."""
    word = stream.peek_word()
    if word is None or word not in NUMBER_WORDS:
        return None
    stream.advance()
    return NUMBER_WORDS[word]


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


#: "Protection from the color of your choice" — the keyword whose argument is
#: not known until the effect resolves (CR 609.3). Named once here because the
#: parser writes it, the grant gate reads it and the handler resolves it, and a
#: third spelling of the same string is how those three come apart.
PROTECTION_FROM_CHOSEN_COLOR = "protection from the color of your choice"


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
            # "…from **the color of your choice**" (Feat of Resistance). CR
            # 609.3: the colour is chosen as the effect resolves, so the keyword
            # cannot name it — it names the *choice*, and the grant resolves it.
            # Read before the bare colour word, which would otherwise consume
            # "the" and grant protection from a colour called "the".
            if stream.accept_phrase("the", "color", "of", "your", "choice"):
                name = PROTECTION_FROM_CHOSEN_COLOR
            else:
                colour = stream.peek_word()
                if colour is not None:
                    stream.advance()
                    name = f"protection from {colour}"
        keywords.append(name)
        # "deathtouch or lifelink" (two items) and "banding, flying, first
        # strike, or trample" (four) — English punctuates a list of four
        # differently from a list of two and the card means the same thing
        # either way, which is the same reason the subtype parser reads both.
        # A comma is consumed only when a keyword follows it, so a line that
        # ends its keyword list and goes on keeps the comma for whatever reads
        # the rest.
        if stream.accept_word("and") or stream.accept_word("or"):
            continue
        comma = stream.mark()
        if stream.accept_punct(","):
            stream.accept_word("or")
            if match_longest(stream.words_from(), 0, KEYWORD_INDEX) is not None:
                continue
            stream.reset(comma)
        break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords)


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
    elif stream.accept_phrase("their", "owners'"):
        # "Return up to two target creatures to their owners' hands." (Read
        # the Tides.) The plural possessive is one token to the lexer; each
        # object still goes to its *own* owner's zone (CR 400.3), so the
        # owner reference is the same one the singular spelling records.
        owner = ast.PlayerRef("owner")
    elif stream.accept_phrase("its", "controller", "'s"):
        owner = ast.PlayerRef("controller")
    else:
        stream.accept_word("a", "an", "the")
    name = stream.peek_word()
    # "hands" is the plural template's spelling of "hand" — one zone per
    # object, pluralized because the objects are.
    if name is not None and name.endswith("s") and name[:-1] in _ZONES:
        name = name[:-1]
    elif name not in _ZONES:
        raise stream.error("expected a zone name")
    stream.advance()
    return ast.Zone(name, owner)


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


def _parse_card_alternatives(
    stream: TokenStream,
) -> tuple[ast.ObjectFilter, ...] | None:
    """A printed **card** noun phrase, as alternatives — "a land card or Shrine
    card", "a creature card or Garruk planeswalker card".

    Lives here because two families need it: the discard *cost* that named it
    (Sanctum of Shattered Heights) and the look-and-pick effect that reads the
    same phrase (Garruk's Harbinger). A fragment two families need goes in
    ``phrases``, never in one of them — that coupling is what stops the grouping
    being information.

    "Discard a card" is the whole hand and returns ``()``; "Discard a land card
    or Shrine card" (Sanctum of Shattered Heights) returns one filter per side
    of the "or". A union rather than one narrowed filter because the two sides
    restrict *different* characteristics — a card type and a subtype — and an
    ObjectFilter AND's its fields, so folding them together would name a card
    that is both a land and a Shrine, which is nothing in the pool and a strictly
    harder cost than the card prints.

    None refuses the line, which is what a phrase the charger cannot test has to
    do: dropped instead, the cost would be payable with any card at all. What
    "cannot test" means is not decided here — ``chargeable_card_filter`` decides
    it, and ``engine/oracle.py``'s reader of the same clause asks the same
    function.
    """
    alternatives: list[ast.ObjectFilter] = []
    while True:
        stream.accept_word("a", "an")
        mark = stream.mark()
        try:
            filt = parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        from .lowering._common import chargeable_card_filter

        if chargeable_card_filter(filt) is None:
            stream.reset(mark)
            return None
        alternatives.append(filt)
        if not stream.accept_word("or"):
            break
    # A bare "Discard a card" narrows nothing, and an empty tuple is how the
    # charger is told so — never a filter with no keys set, which would read as
    # a narrowing the charger then ignores.
    from .lowering._common import chargeable_card_filter

    if len(alternatives) == 1 and not chargeable_card_filter(alternatives[0]):
        return ()
    return tuple(alternatives)


def parse_where_x_definition(stream: TokenStream) -> "ast.Amount | None":
    """``[,] where X is <definition>`` — or None when the clause is absent.

    **One parser**, because there were two. `statements._parse_where_x` read the
    sentence-level clause and `effects/characteristics._parse_gets` read the
    pump's own, and the two accepted different definitions: only the pump knew
    "the greatest power among", only the sentence knew "that died under your
    control". Which alternatives a card could use therefore depended on which
    sentence it was printed in, which is not a rule Magic has. Adding "its mana
    value" to one of them would have made a third such difference, so the fork
    is closed instead.

    Refuses anything it cannot read rather than skipping the clause: an
    undefined X silently reads as the *cast's* X, and a permanent's triggered
    ability has no cast at all.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_word("where"):
        stream.reset(mark)
        return None
    if not (stream.accept_word("x") and stream.accept_word("is")):
        raise stream.error("expected 'X is' after 'where'")
    # "…where X is **its** mana value." A characteristic of the object the
    # sentence already named rather than an aggregate over a set, so it carries
    # no filter — read first because it does not open with "the".
    if stream.accept_phrase("its", "mana", "value"):
        return ast.ManaValueOfSubject()
    stream.accept_word("the")
    # Three aggregates over one noun phrase, and the words are what tell them
    # apart: "the number of" counts the objects, "the greatest power among"
    # takes a maximum over them (Carrion Grub).
    if stream.accept_phrase("greatest", "power", "among"):
        return ast.GreatestPowerAmong(parse_object_filter(stream))
    if not stream.accept_phrase("number", "of"):
        raise stream.error("expected 'the number of' in a where-clause")
    filt = parse_object_filter(stream)
    # "…the number of creatures **that died under your control this turn**"
    # (Liliana's Standard Bearer). A history, and the opposite set from the one
    # the bare filter names: these are exactly the creatures the battlefield no
    # longer holds.
    if stream.accept_phrase("that", "died", "under", "your", "control"):
        _parse_duration(stream)
        return ast.CountOfDeaths(filt)
    return ast.CountOf(filt)
