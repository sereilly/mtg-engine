"""The fragment productions more than one effect family reads.

The floor under `effects/`: productions that consume *part* of a sentence
rather than a whole one — a zone destination, a "for each …" multiplier, a
subject filter, a counter kind, a graveyard position — and the two short word
lists they need beside them, the basic land types and the zone names.
Everything above imports from here and nothing here imports back.

`_parse_zone` lives here rather than with the effects for a reason worth
keeping: it and `_parse_mana_payment` were the *only* references crossing
between effect families ("search your library" needs a zone, "unless they pay"
needs a cost). A fragment two families need is not an effect, and filing it as
one is what couples them. **That is the test for what belongs here**, and it is
asked of a reader's callers rather than of its shape: a fragment with one
caller is that caller's, however general it looks.

**The word tables this module opened with have each become a floor of their
own**, and this docstring went on listing them after they had gone — "trigger
events, durations, counter kinds, board counts, zone names". The trigger events
are `trigger_tables`; the board counts are `where_x`; the counter kinds are a
rule `is_pt_counter` asks `engine/pt.py`. The keyword lists, the printed
prices (`_parse_mana_payment` among them) and the back-references followed, to
`keywords`, `prices` and `references`, and are re-exported below under the
names their callers already used. The durations were the last table of any
size, and left for `durations` at the Phase 0 before Invasion with this module
38 lines under the thousand-line guard. That one is **not** re-exported: every
caller imports it from there, and this module reads `_parse_duration` only for
two fragments of its own.

Two readers went *home* at the same Phase 0, on the test above.
`_accept_literal` and its `NUMBER_SLOT` had one caller,
`where_x.accept_board_count` — the table they read left for that module at
Legends, and the reader stayed behind with the comment explaining the table.
`accept_member_state_clause` has had one caller since the day it was written,
and sits beside it in `static_lines` now.
"""

import dataclasses
from dataclasses import replace

from ..pt import pt_counter_deltas
from . import ast
from .amounts import (accept_counter_kind, accept_counters_on_event_subject,
                      accept_counters_on_source, parse_amount)
from .durations import _parse_duration
from .errors import GrammarError
from .lexer import GToken, tokenize
from .nouns import parse_counted_objects, parse_object_filter
# Re-exported under the name this module's callers already use — the
# arrangement `readers` documents for the fragments it holds.
from .readers import _identifies_one_object  # noqa: F401
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
from .zones import accept_zone_possessive
from .vocabulary import KEYWORD_INDEX, NUMBER_WORDS, match_longest
from .keywords import _parse_keywords, parse_keyword_list


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
        # ``parse_counted_objects`` rather than the bare noun parser: this is a
        # count position, so "for each **basic land type among** lands you
        # control" (domain) is one of the things it may say.
        filt = parse_counted_objects(stream)
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


def _parse_per_each_counters(
    stream: TokenStream,
) -> "ast.CountersOnSource | ast.CountersOnEventSubject | None":
    """``for each <word> counter on <the source | that <noun>>`` — the counter
    pile whose size multiplies what the sentence in front of it does.

    "…sacrifices a permanent of their choice **for each soot counter on this
    artifact**" (Smokestack), "…create a 1/1 green Saproling creature token
    **for each fungus counter on that creature**" (Sporogenesis).

    A sibling of :func:`_parse_per_each_objects` and **not** a branch inside it,
    because what it counts is not a set of objects: a counter has no controller,
    no type line and no zone. The distinction is load-bearing rather than tidy —
    "fungus" is a printed creature type, so the object reader claims "for each
    fungus" happily and hands back a line with "counter on that creature" left
    over. Every caller therefore asks **this** one first, exactly as the
    sacrifice production already asks the history reader before the board one
    and for that reader's reason.

    Returns None with the cursor where it was when the clause is not there, so a
    caller that does not find it still owes the rest of its line to full-token
    consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None
    counted = accept_counters_on_source(stream)
    if counted is None:
        counted = accept_counters_on_event_subject(stream)
    if counted is None:
        stream.reset(mark)
        return None
    return counted


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
    # "When **the** creature put onto the battlefield with this enchantment
    # dies" (Diabolic Servitude). The definite article, which names *one*
    # described object where "a" names any — the same reading
    # ``references.parse_recipient`` gives "the token", and for that phrase's
    # reason: a durable record on the object is what says which one.
    #
    # Consumed here rather than admitted as a quantifier, because the noun
    # parser refuses "the" outright in this position and the phrase behind it
    # reads exactly as the indefinite one does. **Guarded**, and the guard is
    # the whole of what makes it safe: the description that follows must
    # actually identify something, so a bare "the creature" refuses rather than
    # becoming "a creature" and firing a trigger on every creature on the
    # table. That widening is the one failure this function's docstring is
    # about.
    definite = not another and bool(stream.accept_word("the"))
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    wanted = "all" if (another or plural or definite) else "a"
    if spec is None or spec.quantifier != wanted:
        stream.reset(mark)
        return None
    if definite and not _identifies_one_object(spec.filter):
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


def _parse_zone(stream: TokenStream, *, self_possessive: str | None = None) -> ast.Zone:
    """A zone destination: ``your hand``, ``the battlefield``, ``its owner's hand``.

    The possessive is part of the zone, not decoration: Unsummon returns a
    creature to *its owner's* hand while Raise Dead returns a card to *your*
    hand, and those are different players whenever you have stolen the creature.
    An unrecognized possessive raises rather than falling through to the bare
    zone name, so the distinction can never be lost by omission.

    *self_possessive* is the extra word this sentence uses for **its own
    actor**. "Each player may search **their** library … put that card into
    **their** hand" (Noble Benefactor, Veteran Explorer) is the same sentence
    Demonic Tutor prints with "your", offered to a set of seats instead of one
    — the pronoun agrees with the subject, exactly as ``_parse_discard`` already
    reads "discard **your** hand" and "that player discards **their** hand" as
    one production. Passed by the caller rather than admitted here for everyone,
    because "their" only means the actor inside a sentence whose subject the
    caller has already read: bare, it is "its owner's" one word shorter.

    Tested **after** the two-word possessives, so "their owner's hand" and
    "their owners' hands" keep their own reading when a caller passes "their".
    """
    owner: ast.PlayerRef | None = None
    if stream.accept_phrase("its", "owner", "'s") or stream.accept_phrase(
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
    elif stream.accept_word("your"):
        owner = ast.PlayerRef("you")
    elif self_possessive is not None and stream.accept_word(self_possessive):
        owner = ast.PlayerRef("you")
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

    Two spellings reach here for each seat word the rider can name. The rider may
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
    # "…put a +1/+1 counter on target creature **of defending player's
    # choice**." (Erithizon.) The same rider naming CR 506.2's seat instead of
    # "an opponent": in a duel they are the same player and at three seats they
    # are not — a combat has one defending player *per attacking creature*
    # (CR 802), and "an opponent" would take the first live one. So it is a
    # spelling of this rider rather than a synonym of the one above, and the
    # seat it returns is the one only a trigger that froze a combat can answer.
    if stream.accept_phrase("of", "defending", "player", "'s", "choice"):
        return ast.PlayerRef("defending_player"), recipient
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

    **What** a counter kind is spells out once, in
    ``amounts.accept_counter_kind``; this function is that reading plus the one
    thing that made it a separate copy — the refusal. Four modules had written
    the same three-line probe, and each of them was a place the next spelling of
    a kind could be forgotten in only three of the four.
    """
    token = accept_counter_kind(stream)
    if token is None:
        raise stream.error("expected a counter kind" + suffix)
    return token




# A fragment three families need — the cost parser one layer up, the exile
# effect in ``effects/zones`` and the "unless you …" offer in ``effects/board``
# — so it lives here for the reason ``_expect_counter_kind`` above does: the
# layering rule sends a production several families share down to ``phrases``,
# and leaving it with any one of them would make the other two import a family.


def accept_graveyard_position(
    stream: TokenStream,
) -> "ast.GraveyardPosition | None":
    """``the top [N] [<described>] card[s] of <whose> graveyard`` at the cursor,
    or None with the cursor unmoved.

    "the top card of your graveyard" (Alms, Nature's Kiss), "the top creature
    card of your graveyard" (Necratog, Zombie Scavengers, Barrow Ghoul,
    Circling Vultures), "the top three black cards of your graveyard" (Spinning
    Darkness), "the bottom card of target player's graveyard" (Phyrexian
    Furnace).

    CR 404.1 puts each card on **top** of its owner's graveyard and CR 404.2
    keeps the pile in that order, so this names cards by **position** and
    nobody chooses. It therefore refuses rather than falling back to the noun
    parser: "the top card" is not a noun phrase, and a reader that let one
    through would produce a filter any card in the pile answers.

    Every word after the count is required. The possessive goes through
    ``zones.accept_zone_possessive``, the engine's one reader of "whose pile",
    and the noun through ``parse_object_filter`` — so "the top **creature** card"
    and "the top **black** cards" are the same production with the phrase read
    once. The filter must be a **card** phrase (``is_card``): "the top creature
    of your graveyard" names a permanent in a zone that holds none, and reading
    it as a card would compile a sentence no card prints.

    A narrowing the phrase carries beyond the card's own characteristics — a
    zone, a controller — refuses too, because the scan below tests a card in a
    graveyard, where CR 613.1 leaves nothing computed to test against.
    """
    mark = stream.mark()
    if not stream.accept_word("the"):
        stream.reset(mark)
        return None
    if stream.accept_word("top"):
        position = "top"
    elif stream.accept_word("bottom"):
        position = "bottom"
    else:
        stream.reset(mark)
        return None
    # The count is optional and printed in front of the noun, which leaves that
    # noun the bare plural `parse_object_filter` reads either way. Only a fixed
    # count of two or more: "the top card" is the singular already, and a
    # variable one would be a number the charger cannot know before the cost is
    # paid (CR 118.3).
    count: "ast.Amount" = ast.Fixed(1)
    counted = stream.mark()
    if not stream.at_word("card", "cards"):
        try:
            amount = parse_amount(stream)
        except GrammarError:
            amount = None
        if isinstance(amount, ast.Fixed) and amount.value >= 2:
            count = amount
        else:
            stream.reset(counted)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not described.is_card:
        stream.reset(mark)
        return None
    for word in ("of",):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    owner = accept_zone_possessive(stream)
    if owner is None or not stream.accept_word("graveyard"):
        stream.reset(mark)
        return None
    narrowed = described.to_payload()
    if narrowed.get("zone") or narrowed.get("zone_owner"):
        # "the top creature card **from your graveyard** of your graveyard" is
        # not a sentence anyone prints, but a filter that read a zone would be
        # one this production then names a *second* pile for. Refused rather
        # than dropped, which is the direction this grammar fails in.
        stream.reset(mark)
        return None
    return ast.GraveyardPosition(
        owner=owner,
        count=count,
        filter=None if not narrowed else described,
        position=position,
    )


def accept_a_card_at_random_from_hand(stream: TokenStream) -> bool:
    """``a card at random from their hand`` — the shared object phrase.

    Two verbs print it and neither is the other's mode: "reveals" (Wand of Ith)
    leaves the card where it is, "exiles" (Elkin Lair) moves it. The words in
    between are identical, so the phrase is a fragment both verb readers accept
    and each builds its own node from — the alternative is two spellings of one
    noun phrase, which is how one card comes to read "from your hand" where the
    other refuses it.

    Consumes on success and nothing at all on failure, so a verb whose object is
    something else keeps its own refusal site.

    Here rather than beside either verb because a **third** family reads it now
    (Cursed Scroll's "reveal a card at random from your hand" is a bare
    imperative, read in ``effects/reveal.py``), and a fragment two families need
    is not one family's property — ``tests/engine/test_grammar_layering.py``
    forbids the import that would otherwise be needed.
    """
    mark = stream.mark()
    if (
        stream.accept_phrase("a", "card", "at", "random", "from")
        and (stream.accept_word("their") or stream.accept_word("your"))
        and stream.accept_word("hand")
    ):
        return True
    stream.reset(mark)
    return False
