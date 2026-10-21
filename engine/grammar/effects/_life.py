"""A player's **life total** under the verbs a permanent shares: "you gain 3
life", "loses half their life", "gain 2 life for each card revealed this way"
(CR 119.3).

A floor under ``effects/characteristics.py``, pre-split out of it at the Phase 0
before Torment, with that module 51 lines under the thousand-line guard and
the next set's life-gain sentence — Transcendence's "you gain 2 life for each
1 life you lost" — stopping inside it. A floor rather than a family for
``_reveal_until``'s reason: the printed verb keeps one entry point. "Gains" and
"loses" are each one production, ``_parse_gains`` and ``_parse_loses``, which
four modules (``subject_verb``, ``conjuncts``, ``pronouns``, ``control_flow``)
hand a subject and nothing else; by the time a life total is the question a
family has read the verb, and a family may not be called from another one.
``characteristics`` is the one importer, and nothing here reads back.

**The seam is that module's own first line.** It is "what a permanent *is*"
(CR 613's layers 6 and 7), and a life total is a number a **player** has
(CR 119) that no layer touches. The arms that moved shared no helper with
anything left behind — not the keyword list, not the pump's P/T, not the
quoted-ability reader — and most of what they imported came with them: what
stayed imported by both halves is the amount parser, the noun parser and the
"for each … this way" record reader the pump reads too. ``lowering/life.py``
drew the same line from the other side when it left ``lowering/game.py`` at
Mirage, and said then that the parse side had no module to mirror; this is the
parse half of the gain and the loss it lowers, under its name. (The exchange
and the set of a life total stay in ``effects/game.py``, and a payment of life
is a price ``prices.py`` reads, as that docstring says.)

**And it is the half that grows.** Thirteen commits wrote the gain arm, most of
them a new answer to what the printed number multiplies: Icatian Moneychanger's
counters on the source, Rysorian Badger's and Multani's Decree's rate times a
record, Taste of Paradise's payments, Essence Bottle's counters a cost removed,
Jasmine Seer's revealed cards, Renounce's sacrifices, Gerrard's Verdict's
discards. 53 of its 133 lines are dated after ``base_pt`` left
``characteristics`` at Tempest, more than any other arm of that module (Humble's
"loses all abilities" is next, at 47); Transcendence's "for each 1 life you
lost" is the next reading, and it is taught here.

**Two names, one per verb**, each returning None with the cursor where it
found it when the sentence is not about life, so the production that called it
goes on exactly as it did when these were inline arms:

* ``accept_life_gain`` — "gain N life [for each …]", "gain life equal to …".
* ``accept_life_loss`` — "lose N life [for each …]", "lose life equal to …",
  "lose half their life".

Both bodies moved byte for byte, and each call sits where its arm did: the gain
after the control a player "gains control of" and before the quoted grant, the
loss after "loses the game" and the quoted removal and before the counters.

"Loses the game" stayed in ``_parse_loses``. It is CR 104.3e rather than a life
total, it lowers in ``lowering/game.py`` rather than ``lowering/life.py``, and
it is the one reading whose own comment keeps it "visibly separate" from the
life beside it.
"""

from .. import ast
from ..amounts import (accept_counters_on_source, accept_fraction_head,
                       accept_rounding, parse_amount, parse_equal_to)
from ..bounds import accept_life_gain_cap
from ..cost_records import accept_counters_removed_for_cost
from ..distinct import parse_counted_objects
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..phrases import _parse_for_each
from ..records import (_parse_for_each_this_way, accept_each_life_lost,
                       accept_plus_per_cost_paid,
                       parse_for_each_discarded_this_way,
                       parse_for_each_sacrificed_this_way,
                       scaled_by_recorded_count)
from ..stream import TokenStream


def accept_life_gain(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.GainLife | None":
    """``<subject> gains N life [for each …]`` / ``… gains life equal to …``
    (CR 119.3), read from just after the verb; None with the cursor where it
    found it when the words are not a life gain.

    Moved whole out of ``characteristics._parse_gains``, which calls it where
    this arm sat: after the control a player "gains control of" and before
    the quoted grant and the keyword list. A subject that is not a player
    gains as "you", as it always has.
    """
    # "you gain 3 life" / "you gain life equal to the damage dealt"
    mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            # "…, but not more life than the player's life total before the
            # damage was dealt, …" (Drain Life, Soul Burn). Read here rather
            # than folded as a rider by the sentence layer because it is not a
            # separate effect: it is part of how much life this gain is, and a
            # rider that failed to attach would leave the gain uncapped —
            # strictly better than the printed card.
            return ast.GainLife(player, amount, capped_by=accept_life_gain_cap(stream))
    else:
        try:
            amount = parse_amount(stream)
            if stream.accept_word("life"):
                player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
                # "…for each creature you control with flying" (Aven
                # Gagglemaster) — recorded rather than consumed-and-dropped,
                # mirroring the loses-life multiplier.
                #
                # The *history* clause is read first: "for each creature that
                # died this turn" (Canopy Stalker) counts exactly the creatures
                # the battlefield no longer holds, and the board reading of the
                # same words counts the opposite set. The noun parser consumes
                # "creature" and stops, so without this the trailing words were
                # unconsumed and the line failed loudly — which was right, and
                # is why the ordering matters rather than the fallback.
                # "Whenever you lose life, you gain 2 life **for each 1 life
                # you lost**." (Transcendence.) The firing event's loss as a
                # count, read before ``_parse_for_each`` below — which would
                # take "1 life" for a quantified object and strand the rest.
                # The node is the leading form's (Oath of Lim-Dûl), and the
                # lowering holds it to the event that records a loss.
                per_each: object | None = accept_each_life_lost(stream)
                if per_each is None:
                    per_each = _parse_for_each(stream)
                # "…you gain 1 life **for each card exiled this way**."
                # (Rysorian Badger.) A *count* an earlier step of this same
                # effect recorded, not a set the board holds — so it replaces
                # the gain's number instead of multiplying it, exactly as the
                # counter placement one family over treats the same clause.
                #
                # Read after the history clause above, which declines without
                # consuming. The printed number is a **rate**: "gain 1 life for
                # each card exiled this way" (Rysorian Badger) is the record
                # itself, "**gain 2 life** for each enchantment destroyed this
                # way" (Multani's Decree) is twice it, and so is "You gain **2**
                # life for each card revealed this way" (Jasmine Seer, Scent of
                # Jasmine). All three go through
                # ``records.scaled_by_recorded_count``, the reader the counter
                # family one file over already uses for the same clause — so the
                # two effects cannot come to read one printed sentence as two
                # numbers, and a printed 1 still folds away to the bare record
                # rather than to ``Times(1, …)``.
                #
                # This refused a printed 2 outright until those cards, on the
                # reading that ``ThatMuch`` cannot carry a multiplication. True
                # of that node and beside the point: ``ast.Times`` is the node
                # for one and the shared reader had been minting it for the
                # counter spelling of this very clause since Mind Maggots. Two
                # groups of one wave found it independently and wrote the same
                # three lines of code; refusing had kept it loud rather than
                # wrong, which is why the fix is the multiplier and not a wider
                # gate.
                if per_each is None:
                    counted = _parse_for_each_this_way(stream)
                    if counted is not None:
                        return ast.GainLife(
                            player, scaled_by_recorded_count(amount, counted, stream)
                        )
                if per_each is None:
                    # "You gain 2 life **for each permanent sacrificed this
                    # way**." (Renounce.) A count of what the sentence in front
                    # of this one took off the battlefield, which no reading of
                    # a board or of ``_THIS_WAY_COUNTS`` can answer: "any
                    # number" prints no count, and the record holds the *cards*
                    # rather than a number — which is exactly why that table
                    # declines the phrase and this production owns it.
                    #
                    # Read **before** the plain noun-phrase fallback below for
                    # the reason the draw one file over states: that reading
                    # consumes "permanent" and leaves "sacrificed this way" as
                    # unconsumed text, having already claimed the clause for a
                    # count of the whole battlefield — a strictly larger number
                    # than the card prints, and the failure that took this line
                    # down.
                    per_each = parse_for_each_sacrificed_this_way(
                        stream, parse_object_filter
                    )
                if per_each is None:
                    # "You gain 3 life **for each land card discarded this
                    # way**." (Gerrard's Verdict.) The same shape one record
                    # over, read here for the reason the reader above is: the
                    # noun fallback below would take "land card" for a count of
                    # the battlefield and strand the participle.
                    per_each = parse_for_each_discarded_this_way(
                        stream, parse_object_filter
                    )
                if per_each is None:
                    for_each_mark = stream.mark()
                    if stream.accept_phrase("for", "each"):
                        # "…**for each credit counter on this creature**"
                        # (Icatian Moneychanger). A count of the source's own
                        # counters rather than a set of objects, so it is read
                        # by the one production that reads that phrase
                        # (`accept_counters_on_source`) and before the noun
                        # parser, which refuses a counter word as an unknown
                        # noun and would take the whole line down with it.
                        per_each = accept_counters_on_source(stream)
                        if per_each is None:
                            # "You gain 2 life **for each elixir counter
                            # removed this way**." (Essence Bottle.) The
                            # counters the ability's own cost took off, which
                            # after CR 601.2h is the complement of what the
                            # reader above counts: by resolution the artifact
                            # holds none, so "on this artifact" would answer
                            # zero on every activation. One reader for the
                            # phrase, shared with the damage and mana families
                            # that print it (`records`).
                            per_each = accept_counters_removed_for_cost(stream)
                        if per_each is None:
                            try:
                                per_each = parse_counted_objects(stream)
                            except GrammarError:
                                stream.reset(for_each_mark)
                if per_each is None:
                    # "…**plus an additional 3 life for each additional {1}{G}
                    # you paid**" (Taste of Paradise) — one gain whose amount
                    # scales with a CR 601.2b payment.
                    scaled = accept_plus_per_cost_paid(stream, amount, "life")
                    if scaled is not None:
                        return ast.GainLife(player, scaled)
                return ast.GainLife(player, amount, per_each=per_each)
        except GrammarError:
            pass
        stream.reset(mark)
    return None


def accept_life_loss(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.LoseLife | None":
    """``<subject> loses N life [for each …]`` / ``… loses life equal to …`` /
    ``… loses half their life`` (CR 119.3), read from just after the verb;
    None with the cursor where it found it when the words are not a life loss.

    Moved whole out of ``characteristics._parse_loses``, which calls it where
    these three arms sat: after "loses the game" and the quoted removal, and
    before the counters, the chosen ability and the keyword list. The mark
    the last arm resets to is this function's own now, taken at the cursor
    ``_parse_loses`` took its own at — nothing between the two consumes a
    token and falls through.
    """
    mark = stream.mark()
    # "loses **half their life**" (Peer into the Abyss). Read here rather than in
    # `parse_amount`, because the trailing "life" is the *production's* word
    # everywhere else ("loses 3 life") and here it belongs to the quantity —
    # "half their life" is one amount, not a half followed by a life keyword. A
    # quantity parser that consumed it would leave every other printing of this
    # verb without its noun.
    half_mark = stream.mark()
    # "half" and "a third of" are one printed idea with two spellings, so the
    # head is read by one function (`accept_fraction_head`) and the denominator
    # rides the node. Pox's "loses a third of their life" is this branch with a
    # 3 in it.
    divisor = accept_fraction_head(stream)
    if divisor is not None and stream.accept_word("their", "your", "his"):
        stream.accept_phrase("or", "her")
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(
                player,
                ast.Half(
                    ast.BoardCount("their_life"), accept_rounding(stream), divisor
                ),
            )
    stream.reset(half_mark)
    # "loses **life equal to its power**" (Death Watch, Lich, Illicit Auction).
    # The mirror of the gain production's own first branch, in the word order
    # this shape prints: "life" comes *before* the quantity, so the
    # amount-then-noun reading below cannot see it — `parse_amount` refuses on
    # the word "life", the whole production falls through to the keyword list,
    # and the line dies on "expected a keyword ability" naming a word the
    # sentence does not contain.
    #
    # One printed idea, two verbs. A gain and a loss of the same amount are the
    # same clause with the sign flipped (CR 119.3), and reading it for one
    # verb only is what made "you gain life equal to its toughness" legal and
    # "its controller loses life equal to its power" not — on the two halves of
    # a single printed sentence.
    equal_mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(equal_mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(player, amount)
    try:
        amount = parse_amount(stream)
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            # "loses 2 life for each creature card in their graveyard"
            # (Liliana, Death Mage) — a multiplier over a count of objects,
            # recorded rather than consumed-and-dropped.
            #
            # The *history* spellings are read first and through
            # ``phrases._parse_for_each``, the reader the gain-life production
            # already uses: "for each creature that died this way" (Reign of
            # Terror) has a relative clause the bare noun phrase below stops in
            # front of, so it used to leave "that died this way" as unconsumed
            # text and take the whole line down. A second inline reader here is
            # what made one printed idiom mean two things depending on the verb
            # in front of it.
            per_each: object | None = _parse_for_each(stream, allow_this_way=True)
            if per_each is None:
                for_each_mark = stream.mark()
                if stream.accept_phrase("for", "each"):
                    try:
                        per_each = parse_counted_objects(stream)
                    except GrammarError:
                        stream.reset(for_each_mark)
            return ast.LoseLife(player, amount, per_each=per_each)
    except GrammarError:
        pass
    stream.reset(mark)
    return None
