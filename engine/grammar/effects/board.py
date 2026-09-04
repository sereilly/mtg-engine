"""The battlefield: destruction, bouncing, sacrificing.

Return-to-zone, destroy, sacrifice, and `_parse_that_object` — the
back-reference a delayed effect uses to name the permanent its trigger bound
("destroy *that creature* at end of combat").

Tapping left for ``effects/tapping.py`` when this module reached the
thousand-line guard, and it left under that name because ``lowering/tapping.py``
has carried it since the lowering side crossed the same cap — so the mirror
re-forms rather than forking, which is the whole of the naming rule in
CLAUDE.md. ``attachments`` left the next time the guard fired, under
``lowering/attachments.py``'s name and for that same rule: an attachment is a
relation between two permanents, where everything here acts on one at a time.

**Ten imports had outlived the productions that used them** when
``attachments`` left — ``CARD_TYPES``, ``parse_bound_subject`` and eight more,
stranded by the earlier splits and invisible because an unused import is not an
error. Sweeping the module a split takes functions *out* of is the other half
of taking one.

These productions read a zone through `phrases._parse_zone`; they do not define
one, because "search your library" needs the same fragment and neither family
should own the other's vocabulary.
"""

import dataclasses

from .. import ast
from ..amounts import accept_fraction_head, accept_rounding, parse_amount
from ..errors import GrammarError
from ..lexer import NUMBER
from ..names import accept_original_expansion
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream
from ..phrases import (
    _accept_number, _parse_further_subjects, _parse_mana_payment,
    _parse_pay_life, _parse_per_each_objects, _parse_that_object,
)
from ..sacrifices import _parse_counted_sacrifice, _parse_sacrificed_subject








def _accept_unless_life_cost(stream: TokenStream) -> "ast.Amount | None":
    """The life half of "… unless <player> pays <life>", or None, cursor unmoved.

    Two printed shapes and no third: "**3 life**" and "**life equal to its
    toughness**" (Essence Vortex). The second is not a number this parser could
    count — CR 613 makes toughness computed, so it is whatever the creature has
    when the offer is made — and it travels as the characteristic reference the
    resolution reads.

    None rather than a raise, so the mana payment beside it keeps its reading of
    every clause that is not a life cost.
    """
    mark = stream.mark()
    if stream.accept_word("life"):
        if stream.accept_phrase("equal", "to", "its"):
            for name in ("toughness", "power"):
                if stream.accept_word(name):
                    return ast.CharacteristicOfSubject(name, 0)
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if isinstance(amount, ast.Fixed) and amount.value > 0 and stream.accept_word("life"):
        return amount
    stream.reset(mark)
    return None


def _accept_life_alternative(stream: TokenStream) -> int | None:
    """``or 1 life`` trailing a mana payment (Erosion) — CR 118.8, or None.

    Only the amount is carried, not a whole cost node: this is the second half
    of one offer, and the payer covers it either way. Refuses without consuming
    so any other "or" in the sentence keeps the reading it had.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(amount, ast.Fixed) or not stream.accept_word("life"):
        stream.reset(mark)
        return None
    return amount.value


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


def _accept_per_counter_multiplier(stream: TokenStream) -> str | None:
    """``for each <word> counter on it`` trailing a printed cost, or None.

    "Destroy this creature unless you pay {1} **for each music counter on it**"
    — the ability Musician grants: CR 702.24a's escalation with the keyword's
    name taken off it. The counter word is payload, so a card printing a
    different one needs no production. Returns None with the cursor untouched,
    because a flat cost must keep reading exactly as it did.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    word = stream.peek_word()
    if word is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("counter") or not stream.accept_phrase("on", "it"):
        stream.reset(mark)
        return None
    return str(word)


def _accept_destroyed_this_way_no_regen(stream: TokenStream) -> bool:
    """``A <noun> destroyed this way can't be regenerated.`` (War Barge.)

    CR 701.19c's rider printed as a sentence about the *effect* rather than
    about a pronoun. The wording belongs to cards whose destruction was
    arranged a sentence earlier — War Barge's is inside a delayed ability — so
    there is no "it" left in the reader's hand to point at, and the noun
    restates the type the destroy already named.

    It sets the same ``no_regen`` field the two pronoun spellings do, because
    it says the same thing: this destruction is the one regeneration cannot
    answer. The noun is consumed against the closed type set rather than
    skipped, so a sentence naming something the destroy did not destroy leaves
    the words unread and fails the line loudly.
    """
    mark = stream.mark()
    if (
        stream.accept_word("a", "an")
        and stream.accept_word(*_DESTROYED_THIS_WAY_NOUNS)
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


def _parse_sacrifice(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    """"<player> sacrifices <noun>", with the verb already consumed.

    Two spellings reach it: the bare imperative, whose player is you, and a
    printed subject ("each opponent sacrifices a creature", Goremand). One
    production for both, because who sacrifices is the node's field and the
    sentence is otherwise word-for-word the same — the alternative was a second
    copy that would have had to grow the "another" reading and the unless-pay
    tail again.
    """
    # "sacrifices **a third of the creatures they control** of their choice"
    # (Pox). The fraction's noun is this production's own object phrase, so the
    # head is read here and the count built beside the subject rather than
    # handed to `parse_amount` — the same arrangement `_parse_loses` and
    # `_parse_discard` make, and for their reason. The definite article is
    # consumed here too: the noun parser reads "creatures they control" and not
    # "the creatures they control", because everywhere else the article would be
    # a different noun phrase.
    fraction_mark = stream.mark()
    divisor = accept_fraction_head(stream)
    if divisor is not None:
        stream.accept_word("the")
        try:
            counted_filter = parse_object_filter(stream)
        except GrammarError:
            counted_filter = None
        if counted_filter is not None:
            return ast.Sacrifice(
                player,
                ast.TargetSpec(quantifier="all", filter=counted_filter),
                count=ast.Half(
                    ast.CountOf(counted_filter), accept_rounding(stream), divisor
                ),
            )
    stream.reset(fraction_mark)
    # "Sacrifice **another** creature" (Dire Fleet Warmonger) — the same
    # reading the cost parser gives the word: a restriction on what may be
    # sacrificed, carried on the filter's existing field.
    another = bool(stream.accept_word("another"))
    subject = parse_recipient(stream)
    if subject is None:
        # The two readings `parse_recipient` has none for: a bound object
        # ("sacrifice **that creature**", Phantasmal Mount) and a bare count in
        # front of an untargeted plural ("**two Islands**", Leviathan). Both
        # live in `phrases`, because the counted one is also the phrase the
        # "unless you sacrifice" tail below reads.
        return _parse_sacrificed_subject(stream, player)
    if another and isinstance(subject, ast.TargetSpec):
        subject = dataclasses.replace(
            subject, filter=dataclasses.replace(subject.filter, other_than_source=True)
        )
    # "…sacrifices a Plains or a white permanent of their choice **for each
    # white permanent they control**." (Omen of Fire.) How many, counted off
    # the payer's own board — so it is the same per-seat quantity Pox's
    # fraction is, and it rides `Sacrifice.count` for that field's reason: a
    # `TargetSpec.count` is an `int` and every seat asked has a different
    # answer.
    #
    # Read through the shared `for each <objects>` reader rather than a second
    # copy of it, and only over a *set* — `beyond the first` is a rampage
    # discount that means nothing here, so a phrase carrying it hands the
    # clause back untouched and the line refuses rather than sacrificing one
    # permanent too few.
    counted, beyond_first = _parse_per_each_objects(stream)
    if counted is not None and not beyond_first:
        return ast.Sacrifice(player, subject, count=ast.CountOf(counted))
    # "… unless you pay {W}{W}" — a pay-or-else prompt, kept fused because
    # that is the shape the upkeep dispatcher's handlers implement.
    mark = stream.mark()
    if stream.accept_phrase("unless", "you"):
        # "… unless you **pay 2 life**" (Season of the Witch). CR 118.8's
        # payment as the alternative, decomposed to the same `May` the counted
        # sacrifice below lowers to — not a third fused node. That decomposition
        # is what makes the "cannot afford it" case right for free:
        # `handlers/control_flow._action_is_takeable` asks `can_pay_life`, so a
        # player at 1 life is never offered the payment and the enchantment goes.
        #
        # Read before the mana spelling because both open "unless you pay", and
        # `_parse_mana_payment` raises rather than refusing quietly — a life
        # amount reaching it fails the whole line naming a missing mana cost.
        if player.kind == "you":
            life = _parse_pay_life(stream)
            if life is not None:
                return ast.May(
                    actor=player,
                    action=life,
                    otherwise=ast.Sacrifice(player, subject),
                )
        if stream.accept_word("pay"):
            # "…unless you pay **its mana cost reduced by {2}**" (Flash). The
            # possessive names the object an earlier step of this same sentence
            # put onto the battlefield, so the amount cannot be a printed
            # symbol — only the *reduction* is printed. Read before the plain
            # spelling because both open "pay" and `_parse_mana_payment` raises
            # rather than refusing: an "its" reaching it fails the whole line
            # naming a missing mana cost.
            mark_derived = stream.mark()
            if stream.accept_phrase("its", "mana", "cost"):
                if not stream.accept_phrase("reduced", "by"):
                    raise stream.error(
                        "expected 'reduced by' after a derived mana cost"
                    )
                return ast.SacrificeUnlessPay(
                    subject, _parse_mana_payment(stream),
                    cost_from="its_mana_cost",
                )
            stream.reset(mark_derived)
            return ast.SacrificeUnlessPay(subject, _parse_mana_payment(stream))
    stream.reset(mark)
    # "… unless you **sacrifice two Swamps**" (Mold Demon) — the same
    # alternative with a cost mana cannot express. Not a second fused node: an
    # "unless" is an offer with a penalty, which is exactly what `May` already
    # says, and saying it that way means the offer, the penalty and the "you
    # cannot afford it" case all come from machinery that already works. The
    # mana spelling above stays fused only because two upkeep handlers
    # implement it whole.
    if stream.accept_phrase("unless", "you", "sacrifice"):
        alternative = _parse_counted_sacrifice(stream, player)
        return ast.May(
            actor=player,
            action=alternative,
            otherwise=ast.Sacrifice(player, subject),
        )
    stream.reset(mark)
    # "… unless you **tap an untapped creature you control**." (Koskun Falls.)
    # The third printed alternative, decomposed for the reason the sacrifice
    # above is: an "unless" is an offer with a penalty, and `May` already says
    # that — so the offer, the penalty and the "you have nothing to tap" case
    # all come from machinery that works. Nothing new is fused, because nothing
    # implements a tap-or-else prompt whole.
    if stream.accept_phrase("unless", "you", "tap"):
        tapped = parse_recipient(stream)
        if tapped is not None:
            return ast.May(
                actor=player,
                action=ast.Tap(tapped),
                otherwise=ast.Sacrifice(player, subject),
            )
    stream.reset(mark)
    return ast.Sacrifice(player, subject)


def _parse_sacrifice_expansion_permanents(stream: TokenStream) -> ast.Statement | None:
    """``Each nontoken permanent with a name originally printed in the <Set>
    expansion is sacrificed by its controller.`` (Golgothian Sylex.)

    The printed expansion phrase is read by ``names.accept_original_expansion``,
    the same reader the noun phrase's postmodifier uses for Apocalypse Chime's
    "Destroy all nontoken permanents **with a name originally printed in the
    Homelands expansion**" — one scan, because two scans of one printed phrase
    are two spellings free to disagree about where the set name ends (idiom 36).
    A name the manifest does not know leaves the line unconsumed and its card
    unsupported, which is the right answer: the effect would otherwise sacrifice
    the permanents of whichever set the caller guessed.

    Still its own production, because what the noun phrase is *attached to* here
    is a passive verb no other production reads — "is sacrificed by its
    controller" — and the sentence has no imperative for the statement parser to
    dispatch on.
    """
    mark = stream.mark()
    if not stream.accept_phrase("each", "nontoken", "permanent", "with"):
        stream.reset(mark)
        return None
    set_code = accept_original_expansion(stream)
    if set_code is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("is", "sacrificed", "by", "its", "controller"):
        stream.reset(mark)
        return None
    return ast.SacrificeExpansionPermanents(set_code)


def _parse_delayed_self_action(stream: TokenStream) -> ast.Statement | None:
    """``Destroy this artifact at the beginning of the next end step.`` /
    ``Return this artifact to its owner's hand at the beginning of the next end
    step.`` / ``Return that creature to its owner's hand at the beginning of
    the next end step.``

    The whole sentence, delay included, because the action on its own is
    performed *now* — an artifact that destroys itself the moment its ability
    resolves is a different card from one that survives until the end step.
    Every word of the timing is required for the same reason the "next" in
    ``_parse_doesnt_untap_next_step`` is.
    """
    mark = stream.mark()
    # "**Its controller** sacrifices it at the beginning of the next end step."
    # (Celestial Sword.) The same sentence with its actor written out: a
    # sacrifice is performed by the permanent's controller and by nobody else
    # (CR 701.21a), so naming them narrows nothing and the verb below reads the
    # rest unchanged. Consumed here rather than admitted as "another player
    # sacrificing", which is what the general sacrifice lowering refused it as.
    named_controller = stream.accept_phrase("its", "controller")
    if stream.accept_word("destroy") and not named_controller:
        action = "destroy"
    elif not named_controller and stream.accept_word("return"):
        action = "bounce"
    elif stream.accept_word("sacrifice", "sacrifices"):
        # "Sacrifice **it** at the beginning of the next end step." (Krovikan
        # Elementalist.) It was reaching the general delayed-trigger production
        # instead, which reads the pronoun as the *source* — so the card
        # sacrificed the Elementalist rather than the creature it had just
        # given flying to. One sentence, one production, and the referent
        # decided where the target is known.
        action = "sacrifice"
    else:
        stream.reset(mark)
        return None
    # "Destroy **it** …" (Glyph of Destruction): the object the sentence in
    # front of this one named. The same sentence with a different referent, so
    # it is this production with a different subject — and the referent is not
    # decided here, because the printed pronoun does not say whether the spell
    # chose a target or the ability is its own subject.
    subject = "source"
    if stream.accept_word("it"):
        subject = "bound"
    elif stream.at_word("that"):
        # "Return **that creature** to its owner's hand at the beginning of the
        # next end step." (Barbarian Guides.) The same referent "it" names,
        # written out: the object an earlier sentence of this same ability
        # chose. The noun is read rather than skipped, and only the generic
        # nouns are admitted — a printed narrowing ("that Wall") would be a
        # word this production has nowhere to put, and a narrowing dropped on a
        # delayed bounce returns a permanent the card never named.
        probe = stream.mark()
        stream.advance()
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "land", "permanent"
        ):
            stream.reset(probe)
            stream.reset(mark)
            return None
        subject = "bound"
    else:
        if not stream.accept_word("this"):
            stream.reset(mark)
            return None
        if not stream.accept_word(
            "artifact", "creature", "enchantment", "land", "permanent"
        ):
            stream.reset(mark)
            return None
    if action == "bounce" and not stream.accept_phrase(
        "to", "its", "owner", "'s", "hand"
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "at", "the", "beginning", "of", "the", "next", "end", "step"
    ):
        stream.reset(mark)
        return None
    return ast.DelayedSelfAction(action, subject=subject)


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
