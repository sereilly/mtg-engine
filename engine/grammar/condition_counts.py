"""Conditions that are a **count** — how many, and of what.

The second split off ``conditions`` at the thousand-line guard, and it is not
the same cut its sibling made. ``condition_clauses`` was cut by *shape*: the
long readers ``_parse_single_condition`` hands a whole sentence to, whatever
they ask about. This one is cut by *subject*. Every clause here takes a count
off the game and compares it against a printed bound — what a seat controls
("you control an Urza's Mine **and** an Urza's Tower"), how tall a pile is
("your library has ten or more cards in it"), a life total and the difference
between two of them, what is on the battlefield at all ("there are no Zombies
on the battlefield"), how many creatures are blocking the one a block event
named, and the *parity* of a count an earlier sentence already took ("if the
number is odd").

What stays in the dispatcher is asked of one **object**: the ability's own
source and the pronouns that may name it — its state, its type, its zone, its
keywords, the histories the turn wrote about it — plus the spell's own
additional cost, the flip this resolution made, and whose turn it is. Those are
yes-or-no questions about a thing; these are "how many?" about a set. The
imports are the evidence rather than the claim: after the cut ``conditions``
reads neither the object-filter parser, nor a seat reference, nor a life total,
nor ``parse_amount``, nor the colour table, and this module reads all five.

Two clauses sit on the wrong side of that sentence and are named here rather
than left to be rediscovered. "Two or more of those creatures are attacking
you" (Mangara) is a count, but of the batch *this attack* froze rather than of
anything a board holds; "this creature's power is 1 or more" (Lesser Werewolf)
is a bound, but on one object's characteristic. Both stay with the object half,
because the subject is what decides the side and the bound is not.

No mirror name to reuse: ``lowering/conditions.py`` lowers both halves and has
never split, so nothing on that side is forked by taking a new one here. The
name is ``condition_clauses``' prefix, which marks the same contract — a reader
the dispatcher hands a sentence to, non-consuming on refusal so the next branch
below it keeps its say. Below ``conditions``, which calls it and is never
imported back.

The blocker count is read here as well as dispatched here, since the Phase 0
before Nemesis. ``_parse_blockers_of_bound_creature`` had stayed in
``condition_clauses`` when this module was cut, as that module's one clause
about a count and this module's one import from a sibling; it is a count by the
first paragraph above and nothing else called it, so it came across and the
edge went with it.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .bounds import parse_comparison
from .errors import GrammarError
from .nouns import parse_object_filter
from .references import parse_player_ref
from .seat_comparisons import accept_margin
from .seats import accept_life_total_of
from .stream import TokenStream
from .vocabulary import CARD_TYPES, COLOR_WORDS


def _parse_count_bound(stream: TokenStream) -> ast.Comparison:
    """The bound a "has …" clause states, including the printed **zero**.

    "if you have **no** cards in hand" (Brink of Madness). ``parse_comparison``
    reads a quantity and a printed "no" is not one — ``parse_amount`` refuses
    the word outright rather than folding it onto zero, which is the lenient
    reading that file exists to have deleted. So the zero is read here, where
    the sentence has already said it is counting.

    The same word the ``controls`` clause below already reads as its own
    ``negated`` flag ("you control **no** lands"), producing the identical
    ``Comparison("eq", 0)`` — one printed word, one meaning, on both of this
    module's counted verbs. Reading it for one and not the other is what left
    "you have no cards in hand" refusing while "you control no lands" parsed.

    Both of the callers, for this module's standing arrangement: "your hand has
    no cards" and "you have no cards in hand" are one question in two printed
    word orders, and a bound one spelling admits and the other refuses is the
    fork the two branches were written to avoid.
    """
    if stream.accept_word("no"):
        return ast.Comparison("eq", ast.Fixed(0))
    return parse_comparison(stream)


def _parse_blockers_of_bound_creature(
    stream: TokenStream,
) -> ast.BlockersOfBoundCreature | None:
    """"<quantifier> <noun phrase> is/are blocking that creature".

    The quantifier is what the clause *counts*, and every spelling the pool
    prints is read here rather than being split across productions: "no" is a
    zero, "at least N" and "N or more" are the same minimum written two ways,
    and a bare "a"/"an" is that minimum with the one left implicit. None of
    them is baked into a kind — the number rides the comparison, so a card
    printed "at least two" needs no code.

    Returns None (rather than raising) when the words parse as a noun phrase
    that is simply not followed by this relation, so the caller's reset hands
    the sentence back to the productions after it.
    """
    negated = bool(stream.accept_word("no"))
    at_least: int | None = None
    if not negated:
        if stream.accept_phrase("at", "least"):
            amount = parse_amount(stream)
            if not isinstance(amount, ast.Fixed):
                # The evaluator compares an integer; an X or a board count
                # would be compared against a node. Refused rather than
                # coerced, exactly as `SubjectPowerIs` refuses one.
                raise stream.error("the blocker count is a printed number")
            at_least = amount.value
        else:
            count_mark = stream.mark()
            try:
                amount = parse_amount(stream)
            except GrammarError:
                amount = None
            if isinstance(amount, ast.Fixed) and stream.accept_phrase("or", "more"):
                at_least = amount.value
            else:
                stream.reset(count_mark)
                # "a Wall is blocking that creature" — the minimum left
                # implicit. Accepted with the article consumed so the noun
                # parser below reads the same phrase either way; the article is
                # not required, because "creatures blocking that creature" is
                # the same clause with the plural doing the work.
                stream.accept_word("a", "an")
                at_least = 1
    other = bool(stream.accept_word("other"))
    filt = parse_object_filter(stream)
    if other:
        # "at least one **other** Wall creature": the asking permanent never
        # satisfies its own condition — it is already blocking that creature,
        # which is why the trigger fired at all.
        filt = dataclasses.replace(filt, other_than_source=True)
    if not (stream.accept_word("is") or stream.accept_word("are")):
        return None
    if not stream.accept_phrase("blocking", "that", "creature"):
        return None
    comparison = (
        ast.Comparison("eq", ast.Fixed(0))
        if negated
        else ast.Comparison("ge", ast.Fixed(at_least or 1))
    )
    return ast.BlockersOfBoundCreature(filt, comparison)


#: The set a colour census is taken over, as printed. One phrase today — "among
#: all permanents" is every permanent on the battlefield, either seat's, tokens
#: and lands included — and required whole: a narrower set ("among nontoken
#: permanents the chosen player controls", Call to Arms) is a different count
#: with a different answer, and this reader must refuse it rather than answer
#: it about the whole board.
_CENSUS_SCOPE: tuple[str, ...] = ("among", "all", "permanents")

#: The two tails of "<colour> is the most common color …", as ``(words, tied)``.
#: Both required — the bare superlative says nothing about a level board, and
#: the two tails are opposite answers there.
_CENSUS_TIE_TAILS: tuple[tuple[tuple[str, ...], bool], ...] = (
    (("or", "is", "tied", "for", "most", "common"), True),
    (("but", "isn't", "tied", "for", "most", "common"), False),
)


def accept_target_pronoun(stream: TokenStream) -> bool:
    """``it`` / ``that <noun>`` naming the object the guarded effect targets.

    "Destroy target creature if **it** shares a color with …" (Tsabo's
    Assassin) and "Return target permanent to its owner's hand if **that
    permanent** shares a color with …" (Barrin's Unmaking) are one referent in
    two spellings: the repeated noun restates what the effect in front already
    chose, which is the arrangement ``record_conditions`` keeps for "that land
    was nonbasic". Which object that is — a permanent, a spell — is the
    lowering's question (``pronoun_target_referent``), asked beside the effect.

    Consumes nothing unless one of the two is there.
    """
    if stream.accept_word("it"):
        return True
    mark = stream.mark()
    if stream.accept_word("that"):
        noun = stream.peek_word()
        if noun == "permanent" or noun in CARD_TYPES:
            stream.advance()
            return True
    stream.reset(mark)
    return False


def _accept_color_census_condition(stream: TokenStream) -> "ast.Condition | None":
    """A question about **the most common color among all permanents**, or
    None with the cursor untouched.

    Two printed askers of one count (``engine/color_census.py``):

    * "**white is** the most common color among all permanents **or is tied
      for most common**" — the five Invasion Djinns. A printed colour against
      the census.
    * "**it shares a color with** the most common color among all permanents
      **or a color tied for most common**" — Tsabo's Assassin, Barrin's
      Unmaking. The effect's own target against the census.

    Every word is required in both. The scope is what the count is *of*, and
    the tail is what the card says about a level board; a reader that stopped
    at the superlative would be picking one of those for the card.
    """
    mark = stream.mark()
    colour = stream.peek_word()
    if colour in COLOR_WORDS and stream.peek_word(1) == "is":
        stream.advance(2)
        if stream.accept_phrase("the", "most", "common", "color", *_CENSUS_SCOPE):
            for tail, tied in _CENSUS_TIE_TAILS:
                if stream.accept_phrase(*tail):
                    return ast.ColorIsMostCommon(COLOR_WORDS[colour], tied=tied)
        stream.reset(mark)
        return None
    if accept_target_pronoun(stream) and stream.accept_phrase(
        "shares", "a", "color", "with", "the", "most", "common", "color",
        *_CENSUS_SCOPE, "or", "a", "color", "tied", "for", "most", "common",
    ):
        return ast.SharesMostCommonColor()
    stream.reset(mark)
    return None


def accept_counted_condition(stream: TokenStream) -> "ast.Condition | None":
    """One counted condition, or None without consuming when it is something else.

    Non-consuming on refusal, which is the whole of the contract the dispatcher
    relies on: every branch below marks and resets, and the last one leaves the
    stream where this function found it, so the caller's next branch reads the
    same tokens it read before the split.
    """
    # The block's own entry mark. It was ``_parse_single_condition``'s, and the
    # "you control …" branch still resets to it after reading a player
    # reference the rest of the clause then refuses — the same position, since
    # the dispatcher resets to its own mark immediately before calling here.
    mark = stream.mark()

    # "…as long as **white is the most common color among all permanents** or
    # is tied for most common" (the Invasion Djinns) / "…if **it shares a color
    # with the most common color among all permanents** or a color tied for
    # most common" (Tsabo's Assassin). A count of the whole battlefield by
    # colour. Read first: the first form opens on a colour word, which no other
    # clause here does, and the second on a pronoun followed by "shares", which
    # nothing below reads — and it consumes nothing when neither is there.
    census = _accept_color_census_condition(stream)
    if census is not None:
        return census

    # "if **that opponent reveals exactly the chosen number of cards of the
    # chosen color**" (Scrying Glass). A count of a *record* rather than of a
    # zone: the hand this asks about was shown by the sentence in front, and
    # what is counted in it are cards nobody may look at again once the
    # resolution is over.
    #
    # Read first, before every branch below that opens on a player reference:
    # "that opponent" is one, and the readers under this would each consume it,
    # fail on "reveals" and reset — which is correct but leaves the refusal
    # naming whichever of them happened to be last. This one is settled by the
    # verb straight after the seat and consumes nothing when it is not there.
    #
    # The seat is read and dropped. It restates the reveal's own target, which
    # is the only hand the record holds, so carrying it would be a second
    # answer to a question that already has one — but it is *read*, because a
    # production that skipped the words would claim a sentence naming somebody
    # else.
    reveal_mark = stream.mark()
    revealer = parse_player_ref(stream)
    if revealer is not None and revealer.kind in ("that_player", "target_opponent"):
        if stream.accept_word("reveals", "reveal") and stream.accept_word("exactly"):
            if stream.accept_phrase(
                "the", "chosen", "number", "of", "cards", "of", "the", "chosen",
                "color",
            ):
                return ast.RevealedChosenColorCount("eq")
    stream.reset(reveal_mark)

    # "if **the difference between your life total and target player's life
    # total is 5 or less**" (Psychic Transfer). Read before the zone count and
    # the player reference below because it opens on "the", which neither of
    # them can start on — and the two life totals inside it are possessives,
    # which ``parse_player_ref`` does not read, so a fragment reader is needed
    # either way.
    diff_mark = stream.mark()
    if stream.accept_phrase("the", "difference", "between"):
        first = accept_life_total_of(stream)
        if first is not None and stream.accept_word("and"):
            second = accept_life_total_of(stream)
            if second is not None and stream.accept_word("is"):
                comparison = parse_comparison(stream)
                return ast.LifeTotalDifference(first, second, comparison)
    stream.reset(diff_mark)

    # "if **your library has ten or more cards in it**" (Phyrexian Portal).
    # How tall a pile is, which is a different question from every other clause
    # here that reads a player: those ask what the board holds and answer
    # through the layer system, and this one counts a zone nobody can see into.
    #
    # Read before the player reference below because the possessive determiner
    # is its own reading of the seat - ``parse_player_ref`` reads "you", never
    # "your", so the reference parser cannot open this clause at all. Both
    # spellings are here rather than one, because "target opponent's library
    # has …" is the same question about a pile this player may not look at.
    zone_mark = stream.mark()
    zone_owner = None
    if stream.accept_word("your"):
        zone_owner = ast.PlayerRef("you")
    else:
        possessive = parse_player_ref(stream)
        if possessive is not None and stream.accept_word("'s"):
            zone_owner = possessive
    if zone_owner is not None:
        zone = stream.peek_word()
        if zone in ("library", "graveyard", "hand") and stream.peek_word(1) == "has":
            stream.advance(2)
            comparison = _parse_count_bound(stream)
            stream.expect_word("cards", "card")
            # "…in it" is printed by this template and dropped: it names the
            # zone the sentence has already said.
            stream.accept_phrase("in", "it")
            return ast.ZoneHasCards(zone_owner, zone, comparison)
    stream.reset(zone_mark)

    # "if **that player has five or more cards in hand**" (Misers' Cage,
    # Paupers' Cage) / "if **that player has 5 or less life**" (Razor Pendulum).
    #
    # The hand half is the *same question* the possessive spelling above asks
    # ("your hand has five or more cards"), so it produces the same node and
    # reaches the same evaluator — one behaviour, two printed word orders, which
    # is the arrangement this file keeps for every clause a card can spell two
    # ways. Read here, before the "controls" reference below, because both
    # openers are a player reference and this one is settled by the word after
    # it.
    have_mark = stream.mark()
    # "if **a player** has more life than each other player" (Wild Dogs). An
    # existential rather than a reference: nobody chose this seat and no event
    # froze it, and the clause is asking whether *some* player is ahead. Read
    # here rather than in `parse_player_ref`, and deliberately: "a player" in a
    # subject position would be a sentence nobody can perform ("a player draws
    # a card" is not printed), so admitting the words generally would let one
    # into every effect the grammar reads.
    any_player = stream.accept_phrase("a", "player")
    counted = ast.PlayerRef("any_player") if any_player else parse_player_ref(stream)
    if counted is not None and stream.accept_word("has", "have"):
        # "if **a player has more life than each other player**" (Wild Dogs).
        # A superlative rather than a bound: the seat must beat every other
        # one, and the phrase names no number for `parse_comparison` to read.
        # The same op the controls clause below carries for the identical
        # printed tail, so one word means one thing on both sides of "has".
        #
        # Strictly more, so a tie fails — which is the whole of what keeps Wild
        # Dogs still on a level board.
        if stream.accept_phrase("more", "life", "than", "each", "other", "player"):
            return ast.PlayerLifeIs(
                counted,
                ast.Comparison("more_than_each_other_player", ast.Fixed(0)),
            )
        comparison = _parse_count_bound(stream)
        if stream.accept_word("life"):
            return ast.PlayerLifeIs(counted, comparison)
        if stream.accept_word("cards", "card") and stream.accept_phrase("in", "hand"):
            return ast.ZoneHasCards(counted, "hand", comparison)
    stream.reset(have_mark)

    # "if **a player controls more creatures than each other player**" (Wild
    # Mammoth). The existential Wild Dogs opened the "has" clause with, now on
    # the "controls" one: read here for the reason given there, and only as the
    # subject of *this* clause — and only in front of "controls more", so no
    # other clause this branch reads ("gained … this turn", a plain count) can
    # be handed a seat nobody named. The lowering admits it under the
    # superlative alone, for the life gate's reason.
    seat_negated = False
    if (
        stream.peek_word() == "a"
        and stream.peek_word(1) == "player"
        and stream.peek_word(2) == "controls"
        and stream.peek_word(3) == "more"
    ):
        stream.advance(2)
        player = ast.PlayerRef("any_player")
    elif (
        stream.peek_word() == "no"
        and stream.peek_word(1) == "opponent"
        and stream.peek_word(2) == "controls"
    ):
        # "…as long as **no opponent controls** a white or blue creature"
        # (Kavu Runner, Skittish Kavu). The negation printed on the *seat*
        # rather than on the noun or the verb — the third word order of one
        # condition, and the same node as "your opponents control **no** white
        # or blue creatures" (Kezzerdrix's spelling): CR 102.2 makes "no
        # opponent" a statement about every opponent at once, so it is the
        # ``each_opponent`` seat with a count of zero, which is the one
        # comparison where a pooled tally and an every-one-of-them test agree
        # (``lowering/conditions.py`` admits that seat for nothing else).
        #
        # Not ``opponent`` with a zero: that seat is "**an** opponent", an
        # `any` over the seats, and "an opponent controls none" holds in a
        # three-seat game the moment one of two opponents has an empty board.
        stream.advance(2)
        player = ast.PlayerRef("each_opponent")
        seat_negated = True
    else:
        player = parse_player_ref(stream)
    if player is not None:
        # "if **you don't control** a creature named Keeper of Kookus" (Kookus).
        # The negation on the verb rather than on the noun, which is the same
        # condition as "you control **no** creatures named …" below and produces
        # the same `Comparison("eq", 0)` — one behaviour, two printed word
        # orders, which is this file's standing arrangement. The lexer keeps
        # "don't" as one word.
        verb_negated = bool(stream.accept_word("don't", "doesn't"))
        if stream.accept_word("control", "controls"):
            # "if an opponent controls more creatures than you" (Garruk,
            # Unleashed). The comparison is against the asker's own count, so
            # it is an op of its own rather than a number to compare with.
            #
            # "…controls **at least four** more creatures than you" (Avatar of
            # Might). The margin the lead must reach, read by the reader the
            # seat-comparison clause ("who has at least two fewer…") already
            # uses, and carried as the comparison's value — 0 for the bare
            # "more", which the evaluator reads as a lead of one.
            margin = accept_margin(stream)
            if margin is not None and not stream.at_word("more"):
                raise stream.error("expected 'more' after the printed margin")
            if seat_negated and (margin is not None or stream.at_word("more")):
                # "No opponent controls more creatures than you" is a sentence
                # nothing prints, and the comparison below carries no negation
                # — read on, the "no" would be consumed and dropped.
                raise stream.error("'no opponent controls' takes a plain noun phrase")
            if stream.accept_word("more"):
                filt = parse_object_filter(stream)
                # "if that player controls more lands than **each other
                # player**" (Greener Pastures). A *superlative*: the seat must
                # beat every other one, where "than you" beside it names a
                # single rival. Two ops rather than one with a payload flag,
                # because the two answer different questions of different sets
                # — "than you" is a comparison against the asker's own count,
                # and this is a comparison against all the rest — and a reader
                # that had learned only one would answer the other on the
                # wrong seats.
                #
                # Strictly more, and a tie therefore fails: "more … than each
                # other player" is not satisfied by an equal count, which is
                # what makes the card do nothing on a mirrored board.
                if stream.accept_phrase("than", "each", "other", "player"):
                    if margin is not None:
                        # A superlative with a margin is a sentence nothing
                        # prints and nothing evaluates; read as the bare
                        # superlative it would hold on a lead of one.
                        raise stream.error("a superlative carries no margin")
                    return ast.Controls(
                        player, filt,
                        ast.Comparison("more_than_each_other_player", ast.Fixed(0)),
                    )
                if not stream.accept_phrase("than", "you"):
                    raise stream.error(
                        "expected 'than you' or 'than each other player' after "
                        "the count"
                    )
                return ast.Controls(
                    player, filt,
                    ast.Comparison("more_than_you", ast.Fixed(margin or 0)),
                )
            negated = bool(stream.accept_word("no")) or verb_negated or seat_negated
            # "you control **a** Swamp". The article carries no meaning of its
            # own, but the noun parser refuses it as an unknown adjective, so
            # leaving it would refuse every singular condition in the pool.
            # "**another** creature…" (Turret Ogre) is an article carrying the
            # source-exclusion — CR 109.5's "other", contracted — so it sets
            # the same field the leading adjective "other" does.
            another = stream.accept_word("another")
            if not another:
                stream.accept_word("a", "an")
            # "you control **two or more** nonland, nontoken permanents…"
            # (Chrome Replicator) / "you control **three or fewer** lands"
            # (Sheltered Valley). Read where it is printed, in front of the
            # noun phrase, and only when "or more"/"or fewer" follows the
            # number: a bare number here would be a different condition
            # ("exactly two"), and no card in the pool prints one, so guessing
            # which it meant is the kind of silent widening a threshold must
            # never take.
            #
            # The two directions are one production because they are one
            # sentence with one word changed, and the word rides the comparison
            # rather than the kind — the evaluator (`handlers/control_flow.
            # _compare_count`) already answers "le" and always did; nothing had
            # ever printed the word that reaches it.
            bound: tuple[str, int] | None = None
            if not negated and not another:
                count_mark = stream.mark()
                try:
                    amount = parse_amount(stream)
                except GrammarError:
                    amount = None
                if isinstance(amount, ast.Fixed) and stream.accept_phrase("or", "more"):
                    bound = ("ge", amount.value)
                elif isinstance(amount, ast.Fixed) and stream.accept_phrase(
                    "or", "fewer"
                ):
                    bound = ("le", amount.value)
                else:
                    stream.reset(count_mark)
            filt = parse_object_filter(stream)
            if another:
                filt = dataclasses.replace(filt, other_than_source=True)
            # "…**with the same name as one another**". A relation over the set
            # just counted, so it is read after the noun phrase and kept off the
            # filter — see `ast.Controls.shared_name`.
            shared_name = bool(
                stream.accept_phrase("with", "the", "same", "name", "as", "one", "another")
            )
            comparison = None
            if negated:
                comparison = ast.Comparison("eq", ast.Fixed(0))
            elif bound is not None:
                comparison = ast.Comparison(bound[0], ast.Fixed(bound[1]))
            first = ast.Controls(player, filt, comparison, shared_name)

            # "you control an Urza's Mine **and** an Urza's Tower" (the
            # Antiquities cycle). The conjunction shares one player and one
            # verb and repeats only the noun, so it is desugared into the same
            # `AllOf` the clause-level "and" builds — "control X and control Y"
            # is what the shared-verb form means, and having one node for both
            # keeps the evaluator from needing a second shape.
            #
            # Only for the plain form. A negated, counted or shared-name clause
            # ("you control no creatures and…") would need the qualifier
            # distributed over each conjunct to stay faithful, and no card in
            # the pool prints one — so it refuses to widen instead of guessing
            # which of the two readings was meant.
            if not negated and bound is None and not shared_name:
                parts = [first]
                while True:
                    conj = stream.mark()
                    if not stream.accept_word("and"):
                        break
                    stream.accept_word("a", "an")
                    try:
                        extra = parse_object_filter(stream)
                    except GrammarError:
                        stream.reset(conj)
                        break
                    parts.append(ast.Controls(player, extra))
                if len(parts) > 1:
                    return ast.EveryOf(tuple(parts))
            return first
        # "you gained 3 or more life this turn" (Indulging Patrician). "Or more"
        # is the only printed comparison on this clause, so the threshold is a
        # plain minimum rather than a Comparison: inventing "or less" here would
        # be a production no card exercises.
        # Read only where the verb was not negated: "you don't gain 3 or more
        # life this turn" is a sentence no card prints, and admitting it here
        # would be a condition with no evaluator behind its negation.
        if not verb_negated and stream.accept_word("gained"):
            amount = parse_amount(stream)
            if isinstance(amount, ast.Fixed) and stream.accept_phrase(
                "or", "more", "life", "this", "turn"
            ):
                return ast.LifeGainedThisTurn(player, amount.value)
        stream.reset(mark)

    # "if at least one other Wall creature is blocking that creature and no
    # non-Wall creatures are blocking that creature" (Wall of Caltrops). CR
    # 603.4 over CR 509.1a's relation: the clause counts what else is blocking
    # the creature the firing block event named, so its far end is neither the
    # source nor a target and no `ObjectFilter` can carry it — see
    # `ast.BlockersOfBoundCreature`.
    #
    # Read before the source-reference clauses below and after the "you
    # control" one, because it opens on a quantifier rather than on a pronoun
    # and so overlaps neither; the mark/reset is what lets a noun phrase that
    # is *not* followed by "is blocking that creature" fall through unchanged.
    blockers_mark = stream.mark()
    try:
        blocking = _parse_blockers_of_bound_creature(stream)
    except GrammarError:
        blocking = None
    if blocking is not None:
        return blocking
    stream.reset(blockers_mark)

    # "if **all nonland permanents you control are white**" (Zealots en-Dal).
    # A universal quantification over a board, and it is read as the count it
    # already is: "all A are white" holds exactly when the seat controls no A
    # that is not white, which is the :class:`ast.Controls` clause every
    # reading below already produces — vacuous truth included, since a seat
    # controlling no A controls no non-white A either.
    #
    # The rewrite is in the **parse** rather than in a node of its own, for the
    # reason the toll one family over gives about "unless": an offer with a
    # penalty is what ``ast.May`` already says, and a board this seat has none
    # of is what ``Controls`` already says. A separate node would be a second
    # evaluator for one question, free to disagree about the empty board — and
    # the printed colour is a filter key ``subject_matches`` tests
    # (``exclude_colors``, which a colourless permanent also answers, so a Mox
    # falsifies the sentence exactly as the card intends).
    #
    # Read before the existential "there are …" below and before the "you
    # control …" clause above, because "all" opens neither of them; and refused
    # in full rather than narrowed, so a phrase already carrying a colour, a
    # seat this reference parser cannot name, or a trailing word is a line that
    # fails loudly instead of a condition asking something else.
    all_mark = stream.mark()
    if stream.accept_word("all"):
        try:
            described = parse_object_filter(stream)
        except GrammarError:
            described = None
        if (
            described is not None
            and described.controller is not None
            and not described.colors
            and not described.excluded_colors
            and stream.accept_word("are")
        ):
            colour_word = stream.peek_word()
            if colour_word in COLOR_WORDS:
                stream.advance()
                # The seat word travels as it was parsed and the *lowering*
                # decides whether it names one (``_condition_seat``). Deciding
                # here would be a second reading of the same question, and the
                # one that refuses is the one every other clause in this file
                # already relies on.
                return ast.Controls(
                    who=ast.PlayerRef(described.controller),
                    filter=dataclasses.replace(
                        described,
                        controller=None,
                        excluded_colors=(COLOR_WORDS[colour_word],),
                    ),
                    comparison=ast.Comparison("eq", ast.Fixed(0)),
                )
    stream.reset(all_mark)

    # "if **there are no Zombies on the battlefield**" (Sarcomancy) / "if
    # **there are no Reflection tokens on the battlefield**" (Spirit Mirror).
    # The same question the clause below asks, printed with an existential
    # "there" instead of the noun phrase in subject position — one behaviour,
    # two printed word orders, which is the arrangement this file keeps for
    # every clause a card can spell two ways (the possessive/"that player"
    # hand-count pair above is the precedent).
    #
    # `parse_object_filter` reads "on the battlefield" itself and records it as
    # a flag, so the trailing words may already be gone by the time this looks
    # for them. The flag is stripped rather than carried: `to_payload` has no
    # spelling for it and would drop it silently, and the zone is what
    # `OnBattlefield` *is*. Accepting either shape — flag set, or the three
    # words still on the stream — is what makes the production independent of
    # how greedy the noun parser happens to be.
    there_mark = stream.mark()
    if stream.accept_word("there") and (
        stream.accept_word("are") or stream.accept_word("is")
    ):
        # "if there are **two or more** other creatures on the battlefield"
        # (Portcullis). A printed threshold where the two quantifiers below are
        # English articles, so the comparison is read rather than derived from a
        # word — through ``parse_comparison``, the one reader of "N or more" /
        # "N or fewer" in this grammar, so a threshold here and a threshold on a
        # power cannot come to mean different things.
        #
        # Tried first because "two" is neither "no" nor "a": the two readings
        # cannot both match, and a number left unread used to fall out of this
        # production entirely and be taken as *presence* by the clause below —
        # a condition that holds on a board the card does not name.
        there_comparison = None
        number_mark = stream.mark()
        # The two English articles are **not** numbers here, whatever
        # ``parse_amount`` makes of them: "there is **a** creature on the
        # battlefield" is the quantifier below and means one *or more*, and
        # reading it as the number 1 would turn Pestilence's sibling clause into
        # an exact count that a second creature falsifies.
        if stream.peek_word() not in ("a", "an", "no"):
            try:
                there_comparison = parse_comparison(stream)
            except GrammarError:
                stream.reset(number_mark)
                there_comparison = None
        if there_comparison is not None and not isinstance(
            there_comparison.value, ast.Fixed
        ):
            # A variable threshold has no number to compare against here — the
            # board count is taken at once — so the words go back and the clause
            # refuses rather than being read as a different bound.
            stream.reset(number_mark)
            there_comparison = None
        there_quantifier = None
        if there_comparison is None:
            there_quantifier = "no" if stream.accept_word("no") else (
                "a" if stream.accept_word("a", "an") else None
            )
        if there_comparison is not None or there_quantifier is not None:
            try:
                there_filter = parse_object_filter(stream)
            except GrammarError:
                there_filter = None
            if there_filter is not None and (
                there_filter.on_the_battlefield
                or stream.accept_phrase("on", "the", "battlefield")
            ):
                if there_comparison is None:
                    there_comparison = (
                        ast.Comparison("eq", ast.Fixed(0))
                        if there_quantifier == "no"
                        else ast.Comparison("ge", ast.Fixed(1))
                    )
                return ast.OnBattlefield(
                    dataclasses.replace(there_filter, on_the_battlefield=False),
                    there_comparison,
                )
            # "if there are **ten or more creature cards total in all
            # graveyards**" (Avatar of Woe). The same existential with the
            # noun phrase scoped to a pile instead of the battlefield, which
            # the noun parser has already read onto the filter's zone and
            # owner ("total" is the zone reader's) — so what is left is to say
            # which count it is. *Cards*, printed: a phrase about permanents
            # scoped to a graveyard is not a sentence Magic prints.
            if (
                there_filter is not None
                and there_filter.zone != "battlefield"
                and there_filter.is_card
                and not there_filter.on_the_battlefield
            ):
                if there_comparison is None:
                    there_comparison = (
                        ast.Comparison("eq", ast.Fixed(0))
                        if there_quantifier == "no"
                        else ast.Comparison("ge", ast.Fixed(1))
                    )
                return ast.CardsInZones(there_filter, there_comparison)
    stream.reset(there_mark)

    # "if **no creatures are on the battlefield**" (Pestilence, Withering
    # Wisps). The board's own count, with no seat in it — read here, beside the
    # "you control" clause it is *not*: that one asks a player what they have,
    # and this one asks the zone. Pestilence used to reach a name-keyed hook
    # whose key was this whole sentence, so the identical line on a second card
    # reached nothing at all.
    #
    # The quantifier carries the comparison and only the two English articles
    # are read: a printed number ("if two or more creatures are on the
    # battlefield") is a threshold this does not model, and it falls through
    # rather than being taken as presence.
    zone_mark = stream.mark()
    # "if **another** creature is on the battlefield" (Lifeline). The
    # determiner spelling of the adjective the noun parser already reads as
    # ``other``: "another creature" and "another creature you control" are one
    # word where the phrase prints two ("an other creature" is not English), so
    # it is read here — where the quantifier is — and turned into the exclusion
    # the noun parser would have recorded. Which object the word excludes is
    # then decided in one place, the lowering, exactly as Portcullis' "other"
    # is: the trigger's frozen subject where the event has one, and the
    # ability's own source otherwise.
    another = stream.accept_word("another")
    quantifier = "a" if another else (
        "no" if stream.accept_word("no") else (
            "a" if stream.accept_word("a", "an") else None
        )
    )
    if quantifier is not None:
        try:
            present = parse_object_filter(stream)
        except GrammarError:
            present = None
        if present is not None and another:
            present = dataclasses.replace(present, other_than_source=True)
        if present is not None and (
            stream.accept_phrase("are", "on", "the", "battlefield")
            or stream.accept_phrase("is", "on", "the", "battlefield")
        ):
            return ast.OnBattlefield(
                present,
                ast.Comparison("eq", ast.Fixed(0)) if quantifier == "no"
                else ast.Comparison("ge", ast.Fixed(1)),
            )
    stream.reset(zone_mark)

    # "if **the number is odd**" (Chaos Moon). The parity below with the noun
    # phrase replaced by a back-reference: the number is whatever the "Count the
    # number of permanents." sentence in front of it recorded, so nothing is
    # counted here at all. Read *before* that branch, whose phrase this one is a
    # prefix of — "the number of" would consume "the number" and then fail on
    # "is", taking the line with it.
    counted_mark = stream.mark()
    if stream.accept_phrase("the", "number", "is"):
        for word in ("even", "odd"):
            if stream.accept_word(word):
                return ast.CountedNumber(ast.Comparison(word, ast.Fixed(0)))
    stream.reset(counted_mark)

    # "if **the number of permanents is even**" (Chaos Lord). The same board
    # count as the branch above, compared by *parity* rather than against a
    # threshold — so it is the same node with a different operator, not a
    # second condition kind: what is counted, and where, is identical.
    #
    # The noun phrase is read rather than assumed. "The number of permanents"
    # is the whole board (CR 110.1 makes every object on the battlefield a
    # permanent, whoever controls it), and a card counting something narrower
    # is this same sentence with a different phrase.
    parity_mark = stream.mark()
    if stream.accept_phrase("the", "number", "of"):
        try:
            counted = parse_object_filter(stream)
        except GrammarError:
            counted = None
        if counted is not None and stream.accept_word("is"):
            for word in ("even", "odd"):
                if stream.accept_word(word):
                    return ast.OnBattlefield(
                        counted,
                        # The parity is the whole comparison: the sentence
                        # prints no threshold, and a zero here would read as
                        # one to anything that looked. `lowering/conditions.py`
                        # emits no count for these operators for that reason.
                        ast.Comparison(word, ast.Fixed(0)),
                    )
    stream.reset(parity_mark)

    return None
