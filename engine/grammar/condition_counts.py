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
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .bounds import parse_comparison
from .condition_clauses import _parse_blockers_of_bound_creature
from .errors import GrammarError
from .nouns import parse_object_filter
from .references import parse_player_ref
from .seats import accept_life_total_of
from .stream import TokenStream
from .vocabulary import COLOR_WORDS


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
            comparison = parse_comparison(stream)
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
        comparison = parse_comparison(stream)
        if stream.accept_word("life"):
            return ast.PlayerLifeIs(counted, comparison)
        if stream.accept_word("cards", "card") and stream.accept_phrase("in", "hand"):
            return ast.ZoneHasCards(counted, "hand", comparison)
    stream.reset(have_mark)

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
                    return ast.Controls(
                        player, filt,
                        ast.Comparison("more_than_each_other_player", ast.Fixed(0)),
                    )
                if not stream.accept_phrase("than", "you"):
                    raise stream.error(
                        "expected 'than you' or 'than each other player' after "
                        "the count"
                    )
                return ast.Controls(player, filt, ast.Comparison("more_than_you", ast.Fixed(0)))
            negated = bool(stream.accept_word("no")) or verb_negated
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
