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
from ..names import accept_original_expansion
from ..nouns import parse_object_filter
from ..references import parse_recipient
from ..stream import TokenStream
from ..phrases import (
    _parse_mana_payment, _parse_pay_life, _parse_per_each_objects,
    _parse_that_object, _parse_zone,
)
from ..sacrifices import _parse_counted_sacrifice, _parse_sacrificed_subject










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
