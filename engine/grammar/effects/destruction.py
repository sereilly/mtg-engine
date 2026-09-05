"""Destroying a permanent — CR 701.8, and the riders printed around it.

Split out of ``effects/board.py`` at the thousand-line guard, under the name
``lowering/destruction.py`` has carried since it left the same family one
package over — the mirror re-forming rather than forking, after ``prevention``,
``counters``, ``tapping`` and ``attachments``. That module's own note recorded
the asymmetry as settled ("the parse side stays in ``effects/board.py``, where
destroy is one production reading the same noun phrase as the rest"); it was a
claim about a size, and the size changed.

The line is the CR's own keyword action, and it is the same one the lowering
side drew: **destroying** a permanent (CR 701.8) is not sacrificing one
(CR 701.21), returning one to a hand, phasing one out (CR 702.26) or attaching
one — which is what ``board`` keeps. What comes with the verb comes with it:
the "unless its controller pays" offer and its life half, the
"destroyed this way … can't be regenerated" rider (CR 701.19c) and the
per-payer sweep, none of which appears anywhere else in the family.

The offer's three price fragments do **not** travel with them, and that is the
integration correcting the split rather than the split being wrong. This module
and ``prices`` were cut in the same wave, one on a branch and one at the merge,
and both reached for ``_accept_life_alternative``: it is the life half of *this*
offer and it is also one of the prices a printed sentence names anywhere. The
second reading is the wider one and it already had a module, so they are
imported from there — the alternative was the same fragment defined twice, which
merges clean and shadows silently.
"""

from __future__ import annotations

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..lexer import NUMBER
from ..nouns import parse_object_filter
from ..references import (_parse_further_subjects, parse_player_ref,
                          parse_recipient)
from ..stream import TokenStream
from ..prices import (_accept_life_alternative, _accept_per_counter_multiplier,
                      _accept_unless_life_cost)
from ..sacrifices import _parse_counted_sacrifice
from ..phrases import _accept_number, _parse_mana_payment, _parse_that_object


def _parse_destroy(stream: TokenStream) -> ast.Statement:
    """``destroy <objects> [. It can't be regenerated.]``

    One production covers "destroy target creature", "destroy all lands",
    "destroy target tapped creature", and "destroy all Plains" — the
    distinction lives in the noun phrase's quantifier and filter. The legacy
    registry needed five separate rules with hand-ordered precedence numbers to
    keep "destroy all creatures" from being eaten by "destroy target".
    """
    stream.expect_word("destroy")
    subject = _parse_that_object(stream) or parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to destroy")
    # "…all other enchantments you control, all other Auras attached to
    # permanents you control, and all other Auras attached to attacking
    # creatures your opponents control" (Remove Enchantments). One verb, three
    # noun phrases; see `_parse_further_subjects` for why the union is a shape
    # and not a filter.
    further = _parse_further_subjects(stream, subject, several_targets=True)

    # "…at end of combat" (CR 603.7). Only this one delay: a destruction
    # deferred to the next end step is a different handler, so leaving those
    # tokens unconsumed is what keeps Stone Giant and Nettling Imp failing
    # loudly instead of being destroyed a step early.
    delay = "end_of_combat" if stream.accept_phrase("at", "end", "of", "combat") else ""

    # "… unless **that player** pays {1} **or 1 life**" (Erosion). Two readings
    # away from the fused node below, and both of them matter: the payer is the
    # seat the trigger's condition named rather than the ability's controller,
    # and the cost has an alternative mana cannot express. So it decomposes into
    # the `May` an "unless" already is — an offer with a penalty — the same
    # decomposition the sacrifice alternatives take, which puts the offer on the
    # generic pending-choice queue with the destruction as its decline branch
    # and gets "they can afford neither" from machinery that already works.
    #
    # Read above the fused "unless you pay" below and guarded on the payer, so
    # Cosmic Horror keeps the upkeep handler that implements it whole.
    mark = stream.mark()
    if not further and stream.accept_word("unless"):
        payer = parse_player_ref(stream)
        if (
            payer is not None
            and payer.kind != "you"
            and stream.accept_word("pays", "pay")
        ):
            # "… unless its controller pays **life equal to its toughness**."
            # (Essence Vortex.) A life cost with no mana half, so it is read
            # before the mana payment below — which would refuse the word
            # "life" and take the whole line with it. The trailing "A creature
            # destroyed this way can't be regenerated" belongs to the *decline*
            # branch, and is read here because this production returns before
            # the tail reader further down ever runs.
            life = _accept_unless_life_cost(stream)
            if life is not None:
                stream.accept_punct(".", ",")
                unregenerable = _accept_destroyed_this_way_no_regen(stream)
                return ast.May(
                    actor=payer,
                    life_cost=life,
                    otherwise=ast.Destroy(
                        subject, no_regen=unregenerable, delay=""
                    ),
                )
            cost = _parse_mana_payment(stream)
            return ast.May(
                actor=payer,
                cost=cost,
                life_alternative=_accept_life_alternative(stream),
                otherwise=ast.Destroy(subject, no_regen=False, delay=""),
            )
    stream.reset(mark)

    # "… unless you pay {3}{B}{B}{B}" (Cosmic Horror) — the destroy twin of the
    # sacrifice tail below, and read here for the same reason: the cost is the
    # alternative to the destruction, not a second sentence, so a line that
    # left it unconsumed would be destroyed unconditionally.
    mark = stream.mark()
    if stream.accept_phrase("unless", "you", "pay") and not further:
        cost = _parse_mana_payment(stream)
        return ast.DestroyUnlessPay(
            subject, cost, per_counter=_accept_per_counter_multiplier(stream)
        )
    stream.reset(mark)

    # "… unless you **sacrifice two Islands**" (Psychic Allergy) — the destroy
    # side of the alternative `_parse_sacrifice` already reads below, and the
    # same decomposition into `May(action=…, otherwise=…)` rather than a fourth
    # fused node. `_parse_counted_sacrifice` is the one reading of the counted
    # noun phrase, so the two verbs cannot come to disagree about what "two
    # Islands" asks for, and the takeability check that already knows a player
    # with one Island cannot pay it applies unchanged.
    mark = stream.mark()
    if not further and stream.accept_phrase("unless", "you", "sacrifice"):
        payer = ast.PlayerRef("you")
        alternative = _parse_counted_sacrifice(stream, payer)
        return ast.May(
            actor=payer,
            action=alternative,
            otherwise=ast.Destroy(subject, no_regen=False, delay=""),
        )
    stream.reset(mark)

    no_regen = False
    mark = stream.mark()
    stream.accept_punct(".", ",")
    # "…destroy that creature **and** it can't be regenerated" (Consuming
    # Ferocity) against "Destroy target creature. It can't be regenerated"
    # (Terror). One printed word apart, and without it the conjunction loop one
    # layer up takes the "and" and then fails the line on a clause that is a
    # rider rather than a statement — W1G3's Burning Palm Efreet finding, in a
    # second family.
    stream.accept_word("and")
    if (
        stream.accept_phrase("it", "can't", "be", "regenerated")
        or stream.accept_phrase("they", "can't", "be", "regenerated")
        or _accept_destroyed_this_way_no_regen(stream)
    ):
        no_regen = True
    else:
        stream.reset(mark)
    if further:
        targeted = [
            each for each in (subject, *further)
            if isinstance(each, ast.TargetSpec) and each.quantifier == "target"
        ]
        if len(targeted) > 1:
            # "Destroy target creature **and target land**." (Fumarole.) Two
            # targets of one spell are one announcement (CR 601.2c), so one
            # statement — see ``ast.Destroy.also_targets``. Every phrase must be
            # targeted: a union mixing a target with a sweep is two different
            # things happening, and the sweep half has nothing to ask a caster.
            if len(targeted) != len(further) + 1:
                raise stream.error(
                    "a union naming a target and a sweep is not one announcement"
                )
            return ast.Destroy(
                subject,
                no_regen=no_regen,
                delay=delay,
                also_targets=tuple(targeted[1:]),
            )
        return ast.Conjunction(tuple(
            ast.Destroy(each, no_regen=no_regen, delay=delay)
            for each in (subject, *further)
        ))
    return ast.Destroy(subject, no_regen=no_regen, delay=delay)


def _accept_destroyed_this_way_no_regen(stream: TokenStream) -> bool:
    """Every printed spelling of CR 701.19c's rider: ``It can't be
    regenerated.`` / ``They can't be regenerated.`` / ``A <noun> destroyed this
    way can't be regenerated.`` (War Barge.)

    One reader for all three, because they say one thing — this destruction is
    the one regeneration cannot answer — and because two readers is how a card
    comes to depend on which spelling it printed. ``_parse_destroy`` read the
    two pronoun forms inline and this noun form through here, so
    ``riders._attach_no_regeneration`` (which reaches a destroy the sentence
    layer has already wrapped) could fold only the noun spelling: Reign of
    Terror prints "**They** can't be regenerated" after a modal destroy, which
    is exactly the wrapped case, and the sentence became a standalone
    restriction nothing could lower.

    The noun form belongs to cards whose destruction was arranged a sentence
    earlier — War Barge's is inside a delayed ability — so there is no "it"
    left in the reader's hand to point at, and the noun restates the type the
    destroy already named. It is consumed against the closed type set rather
    than skipped, so a sentence naming something the destroy did not destroy
    leaves the words unread and fails the line loudly.
    """
    mark = stream.mark()
    if stream.accept_phrase("it", "can't", "be", "regenerated"):
        return True
    stream.reset(mark)
    if stream.accept_phrase("they", "can't", "be", "regenerated"):
        return True
    stream.reset(mark)
    if (
        stream.accept_word("a", "an")
        and stream.accept_word(*_DESTROYED_THIS_WAY_NOUNS)
        and stream.accept_phrase("destroyed", "this", "way")
        and stream.accept_phrase("can't", "be", "regenerated")
    ):
        return True
    stream.reset(mark)
    # "**That creature** can't be regenerated." (Nekrataal.) The fifth printed
    # spelling, and a *back-reference* rather than a pronoun: the sentence
    # before it destroyed one creature and this one names it again by its noun.
    # Read here rather than left to ``_parse_cant_be`` because that production
    # produces a standalone ``CantBe`` with no duration, which lowers to
    # nothing — the destroy has already happened by then and the restriction has
    # no permanent to attach to. It is the same rule as "It can't be
    # regenerated" with the pronoun spelled out, so it belongs in the one reader
    # of that rule.
    #
    # The sentence must **end** here, which the four spellings above do not have
    # to check: "that creature can't be regenerated **this turn**" is
    # ``_parse_cant_be``'s durationed sentence (Lim-Dûl's Cohort), a restriction
    # armed on a creature the trigger bound rather than a rider on a destroy.
    # Consuming the words and leaving the duration unread would take that
    # production's line away and mis-read the card.
    if (
        stream.accept_word("that")
        and stream.accept_word(*_DESTROYED_THIS_WAY_NOUNS)
        and stream.accept_phrase("can't", "be", "regenerated")
        and (stream.exhausted or stream.at_punct("."))
    ):
        return True
    stream.reset(mark)
    # "**Artifacts** destroyed this way can't be regenerated." (Corrosion.) The
    # plural of the noun form above and the fourth printed spelling of one rule:
    # a sweep destroys a set, so its rider names a set, where War Barge's delayed
    # destroy names one permanent. Against the same closed noun set and with the
    # plural required, so a sentence about something the destroy did not touch
    # still leaves its words unread and fails the line loudly.
    if (
        stream.accept_word(*(noun + "s" for noun in _DESTROYED_THIS_WAY_NOUNS))
        and stream.accept_phrase("destroyed", "this", "way")
        and stream.accept_phrase("can't", "be", "regenerated")
    ):
        return True
    stream.reset(mark)
    return False


#: The nouns "…destroyed this way…" is printed about. A closed set for the
#: reason every other type word in this grammar is one: an open read would
#: claim a sentence about something the destroy never touched.


_DESTROYED_THIS_WAY_NOUNS: tuple[str, ...] = (
    "creature", "artifact", "enchantment", "land", "permanent",
)


def _parse_for_each_destroy_unless_paid(
    stream: TokenStream,
) -> "ast.DestroyEachUnlessPaid | None":
    """``For each <objects>, destroy that <object> unless any player pays N life.``
    (Cleansing.)

    Read as one production rather than as `phrases._parse_for_each` over a
    destroy, because the buyout is *per member*: the offer is made about one
    permanent at a time and paying for one says nothing about the next. A
    decomposed reading would have had to invent an iteration node whose body
    could suspend, and the only thing that node would ever carry is this
    sentence.

    Every part is required and nothing is dropped:

    * the back-reference must name the same noun the loop does ("for each
      **land** … destroy that **land**"), so a sentence iterating one set and
      destroying another refuses rather than compiling into the wrong sweep;
    * the payer must be one of the two printed spellings — "any player", the
      offer that goes round every seat in turn (Cleansing), or "**its
      controller**", the offer made to exactly the seat that permanent belongs
      to (Giant Albatross). They are different cards, so the word is carried on
      the node and the loop is told which; anything else refuses, because a
      buyout offered to a different set of seats than the card names is a
      different card again.
    * the cost must be a printed number of life, since the loop charges it
      literally.

    Returns None with the cursor untouched for every other sentence opening
    "for each", so `statements._parse_leading_for_each`'s "this way" windows
    keep their own reader.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not (stream.accept_punct(",") and stream.accept_word("destroy")):
        stream.reset(mark)
        return None
    if not stream.accept_word("that"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    # The printed noun, compared against the set the loop named rather than
    # skipped: "that land" is a back-reference (idiom 20) and a production that
    # accepted any word there would happily read "destroy that creature".
    if noun is None or noun not in filt.card_types:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("unless"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("any", "player", "pays"):
        payer = "any_player"
    elif stream.accept_phrase("its", "controller", "pays"):
        # "…destroy that creature unless **its controller** pays 2 life."
        # (Giant Albatross.) "Its" is the loop's own member — the same
        # back-reference the noun two words earlier is — so the seat varies per
        # round of the loop and is never a seat the sentence chose.
        payer = "controller"
    else:
        stream.reset(mark)
        return None
    # A printed integer, read straight off the token rather than through
    # `parse_amount`: the loop charges the number literally, and an `Amount`
    # this production cannot evaluate would be a cost nobody is asked for.
    life_token = stream.accept_kind(NUMBER)
    if life_token is None:
        word = _accept_number(stream)
        if word is None:
            stream.reset(mark)
            return None
        life = word
    else:
        life = int(life_token.text)
    if not stream.accept_word("life"):
        stream.reset(mark)
        return None
    # "**A creature destroyed this way can't be regenerated.**" (Giant
    # Albatross.) CR 701.19c, printed as a sentence of its own about the whole
    # loop rather than as a pronoun about one member — the same clause the
    # ordinary destroy reads at the same point in its own production, and read
    # here because this production returns before that one is ever reached.
    tail = stream.mark()
    stream.accept_punct(".", ",")
    no_regen = _accept_destroyed_this_way_no_regen(stream)
    if not no_regen:
        stream.reset(tail)
    return ast.DestroyEachUnlessPaid(filt, life, payer, no_regen)
