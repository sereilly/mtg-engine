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

import dataclasses
from dataclasses import replace

from ..pt import pt_counter_deltas
from . import ast

from .errors import GrammarError
from .lexer import GToken, NUMBER, PT, PUNCT, WORD, tokenize
from .nouns import _STATE_ADJECTIVES, parse_object_filter
# The price fragments, re-exported so every existing caller keeps its import
# — the arrangement `readers` already has one layer down.
from .prices import (_accept_conjoined_life_cost,  # noqa: F401
                     _accept_life_alternative,
                     _accept_mana_alternatives,
                     _accept_per_counter_multiplier,
                     _parse_mana_payment, _parse_pay_life,
                     _accept_life_only_offer)
# The back-references left for `references` when this module crossed the
# thousand-line guard — they answer CR 115's question with an earlier step as
# the referent, which is that module's subject and not this one's word tables.
# Re-exported under the names this module used, so no caller changed.
from .references import (PAIR_ORDINALS,  # noqa: F401
                         _parse_further_subjects, _parse_that_object,
                         parse_bound_subject, parse_pair_ordinal_subject,
                         parse_target_spec)
from .stream import TokenStream
from .vocabulary import KEYWORD_INDEX, NUMBER_WORDS, match_longest
from .keywords import (PROTECTION_FROM_CHOSEN_COLOR, _parse_keywords,
                       parse_keyword_list)


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
    # "for as long as this creature remains **on the battlefield**" (Stromgald
    # Spy). The other linked duration, and linked the same way: nothing
    # schedules its removal, because the effect is contributed while the source
    # is in the scan and simply stops being contributed when it is not
    # (CR 611.2b, and CR 400.7 makes a returning permanent a new object that
    # contributes nothing). Its own kind rather than the tapped one's: an
    # opponent who taps the source breaks that link and not this one.
    #
    # The value has been in the grammar since Scarwood Bandits, read inline by
    # the control-change production because it was the only sentence printing
    # the words. A second sentence now prints them, which is what moves the
    # phrase into the one duration table — and the entry makes it available to
    # every production, which is safe because a lowering handed a duration it
    # has no sweep for refuses by name rather than dropping the words.
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "artifact", "remains", "on", "the",
      "battlefield")),
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "creature", "remains", "on", "the",
      "battlefield")),
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "permanent", "remains", "on", "the",
      "battlefield")),
    ("until_end_of_turn", ("until", "end", "of", "turn")),
    ("until_end_of_combat", ("until", "end", "of", "combat")),
    ("until_your_next_turn", ("until", "your", "next", "turn")),
    # "Until your next upkeep" (Xenic Poltergeist). Longer than its own prefix
    # is not the issue here — "until your next turn" and "until your next
    # upkeep" diverge at the last word — but they are different moments (CR 500:
    # the upkeep step is inside the turn), so they are different kinds and the
    # one nothing implements must not fall back to the one that is close.
    ("until_your_next_upkeep", ("until", "your", "next", "upkeep")),
    # "Until **the beginning of** your next upkeep" (Elkin Bottle). The same
    # moment spelled out, so the same kind: CR 500's upkeep step begins once,
    # and a second kind would be a second name for one instant. Longest-match
    # is not at risk against the entry below it — "beginning" and "end" diverge
    # on the third word.
    ("until_your_next_upkeep",
     ("until", "the", "beginning", "of", "your", "next", "upkeep")),
    # "Until the end of your next upkeep" (Halfdane). A step *later* than the
    # entry above: "until your next upkeep" ends as that upkeep begins, this
    # one ends as it ends — which is the whole trick of the card printing it,
    # whose own upkeep trigger re-applies the effect before the old one runs
    # out. Different moments, so different kinds, for the reason the comment
    # above gives about turns and upkeeps.
    ("until_end_of_your_next_upkeep",
     ("until", "the", "end", "of", "your", "next", "upkeep")),
    # "…until **its controller's next untap step**." (Orcish Farmer.) A moment
    # in someone else's turn, which is what separates it from every entry above:
    # the four "your next …" kinds all name a step of the seat the effect
    # belongs to, and this one names a step of whoever controls the *object*.
    # Read before "this turn" only by being longer; they share no prefix.
    # The possessive is two tokens: the lexer splits "controller's" into the
    # noun and the clitic, which is what `_parse_doesnt_untap_next_step` spells
    # out one family over.
    ("until_controllers_next_untap_step",
     ("until", "its", "controller", "'s", "next", "untap", "step")),
    ("this_turn", ("this", "turn")),
    # "…until the end of **that** turn" (Giant Slug). Which turn "that" names
    # is not in the sentence: it comes from the delay the sentence sits inside
    # ("at the beginning of your next upkeep, …"). So it is its own kind, and
    # ``delayed.resolve_that_turn`` is the one place that turns it into an
    # ordinary end of turn — inside a delay, where "that turn" is the turn the
    # ability resolves in. Outside one nothing lowers it, which is the honest
    # answer: the phrase names a turn the reader cannot identify.
    ("until_end_of_that_turn", ("until", "the", "end", "of", "that", "turn")),
)

#: The five types CR 205.3i calls **basic** land types, in the printed order
#: (WUBRG) every card that lists them uses. Not read out of
#: ``data/vocabulary/land_types.json``: that catalog holds every land subtype
#: Magic prints, and "a basic land type" is a strictly smaller question with a
#: fixed answer the rules give rather than a set that grows with each release.
#:
#: Here rather than in one effect family because two of them need it — the
#: combat restriction ("can't attack unless defending player controls a
#: Forest") and the choose-a-type grant (Giant Slug) — and a fragment two
#: families share is what this module is for.


BASIC_LAND_WORDS: tuple[str, ...] = (
    "plains", "island", "swamp", "mountain", "forest",
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
#
# A ``NUMBER_SLOT`` in a phrase matches any printed number and captures it as
# the count's ``base``. The constant is the one part of these phrases that is
# *data*: Black Vise prints "minus 4" and The Rack "3 minus", one arithmetic
# with one number changed, and spelling the 4 in made every other threshold a
# non-match. That is why The Rack was a name-keyed hook — not because its
# sentence was bespoke, but because its number was 3.


NUMBER_SLOT = "<n>"

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


# Moved here from `effects/characteristics.py` the day a *second* family needed
# it, which is the same day and the same reason `_parse_for_each` above moved:
# "Baki's Curse deals 2 damage to each creature **for each Aura attached to
# that creature**" is the damage family asking exactly the question the P/T
# family was already asking of Rabid Wombat. The two clauses are one printed
# idiom, so one reader — a second would be two answers to "which sets may
# multiply a printed number", and which answer a card got would depend on which
# sentence it printed the words in.


def _parse_per_each_objects(
    stream: TokenStream,
) -> tuple[ast.ObjectFilter | None, bool]:
    """``for each <objects> [beyond the first]`` — the set whose size
    multiplies a printed P/T, and whether the first of them is discounted.

    "This creature gets +2/+2 **for each Aura attached to it**" (Rabid Wombat).
    Distinct from ``phrases._parse_for_each``, which reads the *history* form
    ("for each creature that died this turn"): a history is not a set anything
    can scan, so the two produce different nodes and this one hands the history
    spelling back rather than reading it as a board count.

    "…**beyond the first**" (Johtull Wurm; CR 702.23a's reminder text for
    rampage) is read here rather than left to the caller, because it modifies
    the clause this production claimed — a trailing phrase the count's own
    reader does not consume is unconsumed text that takes the whole line down.

    Returns ``(None, False)`` with the cursor where it was when the clause is
    not there, so a caller that does not find it still owes the rest of its
    line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None, False
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None, False
    # "…that died this turn" / "…that died this way" belong to the productions
    # that know what those sets are; a relative clause this cannot read would
    # otherwise be left as unconsumed text with the count already claimed.
    if stream.at_word("that"):
        stream.reset(mark)
        return None, False
    beyond_first = stream.accept_phrase("beyond", "the", "first")
    return filt, beyond_first


def _parse_for_each(
    stream: TokenStream, *, allow_this_way: bool = False
) -> "ast.DiedThisTurn | ast.DiedThisWay | None":
    """``for each <objects> that died this turn`` — a trailing iteration clause.

    The set is a *history*, not a board state, which is why it produces
    :class:`ast.DiedThisTurn` rather than the noun phrase's own filter.

    "This turn" is required rather than defaulted, for the reason the deletion
    probe exists: the engine's death tally resets each turn, so a clause
    counting some other window is a different number — and letting the words be
    absent would let them be *deleted* with no change to the parse.

    *allow_this_way* additionally admits "…that died **this way**"
    (:class:`ast.DiedThisWay`), the same two spellings the *leading* position
    already reads through ``statement_dispatch``. Off by default because they
    are emphatically not one set — "this turn" is a window anything may have
    contributed to and "this way" is exactly what an earlier step of this
    effect destroyed — so a caller with no producer to read gets the refusal it
    has always had rather than a clause it would count off the wrong record.

    One reader for both, and that is the point: ``_parse_loses`` had grown its
    own inline "for each" over a bare noun phrase, so which spellings a card
    could use depended on whether it gained life or lost it. Reign of Terror
    ("You lose 2 life **for each creature that died this way**") is the card
    that found the fork.

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
    if allow_this_way and stream.accept_phrase("this", "way"):
        return ast.DiedThisWay(filt)
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


def accept_or_planeswalker(
    stream: TokenStream, recipient: "ast.Recipient | None"
) -> "ast.Recipient | None":
    """*recipient* with "**or planeswalker**" folded in, if those two words
    follow it (CR 115.4's redirection union).

    "…deals 2 damage to target player or planeswalker" (Chandra's Magmutt) and
    "Prevent the next 2 damage that would be dealt to target player or
    planeswalker this turn" (Wandering Mage) are the same two words behind the
    same noun phrase, read by two families — damage and prevention — that may
    not import each other. So the fragment sits here rather than in either of
    them, which is this package's rule for a phrase two families need.

    Deliberately *not* inside ``parse_player_ref``: the union is honoured only
    where a lowering knows what to do with it, and a recipient that could carry
    the flag anywhere would let a production that ignores it drop the
    planeswalker half silently. Anything but a targeted player ref is returned
    untouched with the cursor unmoved.
    """
    if (
        isinstance(recipient, ast.PlayerRef)
        # "target **opponent** or planeswalker" (Eternal Flame) is the same
        # union with the caster's own seat struck out of it, which is a
        # narrowing the recipient already carries.
        and recipient.kind in ("target_player", "target_opponent")
        and stream.accept_phrase("or", "planeswalker")
    ):
        return dataclasses.replace(recipient, or_planeswalker=True)
    return recipient


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


def _parse_can_attack_as_though(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.AttackAsThough | None":
    """``can attack [duration] as though it didn't have <keyword>`` — the
    permission clause, without its subject.

    Here rather than with either effect family because two of them read it: the
    pump conjunction prints it as the tail of one sentence ("This creature gets
    +4/-4 until end of turn **and can attack this turn as though it didn't have
    defender**", Wall of Wonder) and the subject-verb table reads it as a
    sentence of its own. A fragment two families need is not an effect.

    Non-consuming on refusal, so every other "can …" sentence keeps the reading
    it has today — "can't be blocked" and the Auras' durationless printing among
    them.
    """
    mark = stream.mark()
    if not stream.accept_word("can"):
        return None
    if not stream.accept_word("attack"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if not stream.accept_phrase("as", "though", "it", "didn't", "have"):
        stream.reset(mark)
        return None
    matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
    if matched is None:
        stream.reset(mark)
        return None
    keyword, consumed = matched
    stream.advance(consumed)
    return ast.AttackAsThough(subject, keyword, duration)


def _accept_literal(stream: TokenStream, *phrase: str) -> tuple[bool, int | None]:
    """Consume consecutive tokens by their text, all-or-nothing.

    ``TokenStream.accept_phrase`` requires every token to be a *word*, which
    "…hand minus 4" is not — the 4 lexes as a number. Punctuation is still
    refused, so a phrase can never silently span a sentence boundary.

    A :data:`NUMBER_SLOT` element matches any number token and is returned
    beside the match, so the phrase says *where* the constant goes and the
    caller keeps the constant itself as data.
    """
    if len(stream.tokens) - stream.pos < len(phrase):
        return False, None
    captured: int | None = None
    for offset, text in enumerate(phrase):
        token = stream.tokens[stream.pos + offset]
        if token.kind == PUNCT:
            return False, None
        if text is NUMBER_SLOT:
            if token.kind != NUMBER:
                return False, None
            captured = int(token.text)
            continue
        if token.text != text:
            return False, None
    stream.advance(len(phrase))
    return True, captured


#: "Protection from the color of your choice" — the keyword whose argument is
#: not known until the effect resolves (CR 609.3). Named once here because the
#: parser writes it, the grant gate reads it and the handler resolves it, and a
#: third spelling of the same string is how those three come apart.


def _accept_self_reference(stream: TokenStream) -> bool:
    """Consume one reference to the ability's own source, or leave the cursor.

    Two printed spellings: "this <noun>" (Willow Satyr, The Wretched), and the
    card naming itself — which the lexer has already collapsed to one SELF
    token (Rubinia Soulsinger's "you control Rubinia Soulsinger"). The noun
    after "this" names the source's own type and adds nothing a payload would
    carry, but it still has to be consumed for the line to be accounted for in
    full.
    """
    token = stream.peek()
    if token is not None and token.kind == "self":
        stream.advance()
        return True
    mark = stream.mark()
    if stream.accept_word("this") and stream.peek_word() is not None:
        stream.advance()
        return True
    stream.reset(mark)
    return False


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


def accept_member_state_clause(stream: TokenStream) -> tuple[str, bool] | None:
    """``it's [not] <state>`` — the ``(ObjectFilter field, value)`` it names.

    The trailing half of "Each untapped creature you control gets +0/+2 **as
    long as it's not attacking**" (Arcades Sabboth). "It" is a member of the set
    the sentence already described, so what the clause states is one more
    adjective on that noun phrase — which is why this returns a filter field
    rather than an :class:`ast.Condition`. Read as a condition it would ask the
    question of the ability's *source*, and Arcades would hand its whole team
    +0/+2 whenever Arcades itself stayed home.

    The state vocabulary is ``nouns._STATE_ADJECTIVES``, the same table the
    *leading* adjectives are read from, so "attacking" cannot mean one field
    here and another in front of the noun. The negation is a word read in front
    of the adjective rather than rows of its own, because Magic prints "not
    <adjective>" for every one of them.

    Returns None with the cursor where it was when the clause is not this.
    """
    mark = stream.mark()
    if not stream.accept_word("it"):
        stream.reset(mark)
        return None
    # The lexer splits the contraction, so "it's" and "it is" are the same two
    # tokens with a different second one — both copulas are accepted here for
    # the reason `conditions._parse_single_condition` accepts both.
    if not (stream.accept_word("'s") or stream.accept_word("is")):
        stream.reset(mark)
        return None
    negated = bool(stream.accept_word("not"))
    word = stream.peek_word()
    state = _STATE_ADJECTIVES.get(word) if word else None
    if state is None:
        stream.reset(mark)
        return None
    stream.advance()
    field_name, value = state
    return field_name, (not value) if negated else value



# ---------------------------------------------------------------------------
# "…of an opponent's choice"
# ---------------------------------------------------------------------------
#
# Down here rather than in `effects/` because two families read it: the damage
# clause that hands one of its recipients to the other seat (Rocket Launcher's
# second half) and the redirect that names the creature the damage moves to
# (Nova Pentacle). A fragment several families want is what this module is for
# — the rule the layering guard states, and the reason `_parse_zone` and
# `_parse_mana_payment` live here too.


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


# A fragment two ``effects/`` families need, so it lives here rather than in
# either of them — the layering rule sends a production two families share down
# to ``phrases``. ``counters`` reads it for "put a <kind> counter on…" and
# ``characteristics`` for "<player> gets a <kind> counter"; leaving it with
# either would have made one family import the other.


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


