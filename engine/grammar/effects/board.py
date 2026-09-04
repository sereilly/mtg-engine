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
from ..readers import _parse_entering_counters
from ..vocabulary import CARD_TYPES
from ..records import _parse_for_each_this_way

from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..names import accept_original_expansion
from ..readers import accept_source_reference
from ..references import (_parse_further_subjects, parse_player_ref,
                          parse_recipient)
from ..stream import TokenStream
from ..phrases import (
    _parse_counted_sacrifice,
    _parse_mana_payment, _parse_pay_life, _parse_per_each_objects,
    _parse_sacrificed_subject, _parse_that_object, _parse_zone,
)


def _parse_put_source_into_zone(stream: TokenStream) -> ast.Statement | None:
    """``Put it into your graveyard.`` (All Hallow's Eve, from exile.)

    The ability moving its own source, which is neither a target nor a noun
    phrase — so it is read here, ahead of the counter production that otherwise
    claims every sentence opening with "put" and refuses this one naming a
    counter kind nobody printed.

    Refuses without consuming unless the whole sentence is there: the word
    after "put" must be a self-reference and the destination must be a zone.
    Anything else is somebody else's "put", and taking part of it would strand
    the rest.
    """
    mark = stream.mark()
    if not stream.accept_word("put"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_word("into"):
        stream.reset(mark)
        return None
    try:
        zone = _parse_zone(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.PutSourceIntoZone(zone)


def _parse_return(
    stream: TokenStream, actor: "ast.PlayerRef | None" = None
) -> ast.Statement:
    """``[<player> ]Return <objects> [from <zone>] to <zone>`` (CR 400.7).

    One production for Raise Dead, Regrowth, Resurrection and Unsummon, which
    the legacy registry needed three separately-ordered substring rules for —
    and which it told apart by probing for ``"creature card" not in text``. The
    source zone rides on the noun phrase (``engine/grammar/nouns.py``), because
    "target creature card from your graveyard" is one noun phrase; the
    destination is parsed here.
    """
    # Both spellings of the verb: a bare imperative prints "Return", and one
    # with a subject prints "returns". Same production — English inflection is
    # not a different effect.
    if not (stream.accept_word("return") or stream.accept_word("returns")):
        raise stream.error("expected 'return'")
    # "Return target spell or creature to its owner's hand." (Unsubstantiate.)
    # A union across two zones — the stack and the battlefield — which no
    # object filter expresses, so the template is read whole and the node
    # carries the stack half as a flag.
    union_mark = stream.mark()
    if stream.accept_phrase("target", "spell", "or", "creature"):
        if stream.accept_word("to"):
            destination = _parse_zone(stream)
            if (
                destination.name == "hand"
                and destination.owner is not None
                and destination.owner.kind == "owner"
            ):
                return ast.ReturnToZone(
                    ast.TargetSpec(
                        "target", ast.ObjectFilter(card_types=("creature",)),
                        targeted=True,
                    ),
                    destination, None, also_stack=True,
                )
        stream.reset(union_mark)
    # "Return **that card** to its owner's hand." (Puppet Master.) The bound
    # object again — the card of the creature the trigger watched die, which by
    # resolution is in a graveyard and so is a *card*, not a permanent anything
    # could target. Read locally, exactly as `_parse_that_object` reads "that
    # creature" for the destroy production and for the same reason: teaching
    # the shared noun parser the phrase would hand it to every line printing
    # those words. The lowering checks a binder exists.
    # "Return **to your hand** all enchantments you both own and control, …"
    # (Remove Enchantments). The destination is printed first when the subject
    # is too long to sit between the verb and it — English, not a different
    # effect — so it is read here and the rest of the production is the same
    # production. Refusing it would cost the card its whole first sentence over
    # a word order.
    destination_first: ast.Zone | None = None
    if stream.at_word("to"):
        stream.advance()
        destination_first = _parse_zone(stream)

    bound = stream.mark()
    subject: ast.Recipient | None
    # "Return **the top creature card of your graveyard** to the
    # battlefield." (Shallow Grave.) A card named by its *position* in an
    # ordered pile (CR 404.3) rather than by a noun phrase, which is why the
    # shared recipient parser refuses it — the same reason the counter
    # family reads "the top card of your graveyard" locally one file over.
    #
    # Its own quantifier, refused by default everywhere: no lowering accepts
    # ``"top"`` unless it says so, so a sentence that reaches one fails **by
    # name** rather than being read as a chosen target the card never offers.
    top_mark = stream.mark()
    top_of_graveyard = None
    if stream.accept_phrase("the", "top"):
        type_word = stream.peek_word()
        if type_word is not None and type_word in CARD_TYPES:
            stream.advance()
            if stream.accept_phrase("card", "of", "your", "graveyard"):
                top_of_graveyard = ast.TargetSpec(
                    "top",
                    ast.ObjectFilter(
                        card_types=(type_word,), is_card=True,
                        zone="graveyard", zone_owner=ast.PlayerRef("you"),
                    ),
                )
    if top_of_graveyard is None:
        stream.reset(top_mark)
    if top_of_graveyard is not None:
        subject = top_of_graveyard
    elif stream.accept_phrase("that", "card"):
        subject = ast.TargetSpec("that", ast.ObjectFilter(is_card=True))
    else:
        stream.reset(bound)
        subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to return")
    further = _parse_further_subjects(stream, subject)
    if destination_first is not None:
        destination = destination_first
    else:
        if not stream.accept_word("to"):
            raise stream.error("expected a destination zone after 'return'")
        destination = _parse_zone(stream)

    # "...to the battlefield **tapped**." (Silversmote Ghoul.) CR 110.5b: a
    # permanent enters untapped unless a spell or ability says otherwise, and
    # this is the ability saying so. Consumed here rather than left to
    # engine/enter_effects.py, which answers for a permanent's *own printed*
    # entry line (a static ability, CR 603.6d) — this rider is printed on the
    # ability that does the moving, and the permanent it makes has no such line.
    # Accepted only for the battlefield, because "to your hand tapped" is not a
    # sentence and silently dropping the word is the bug class this grammar
    # refuses by construction.
    entering_tapped = False
    if destination.name == "battlefield" and stream.accept_word("tapped"):
        entering_tapped = True

    # "…to the battlefield **with a +1/+1 counter on it**." (Sand Golem.)
    # CR 121.2 puts the counters on as part of the move, so the phrase belongs
    # to the return exactly as "tapped" above does — and through the same
    # reader the exile uses, so one printed phrase has one meaning. Battlefield
    # only, for that rider's reason: a card in a hand carries no counters, and
    # consuming the words into nothing is the bug this grammar refuses.
    entering_counters: tuple[tuple[str, int], ...] = ()
    if destination.name == "battlefield":
        entering_counters = _parse_entering_counters(stream)

    # "…to the battlefield **under the control of that creature's owner**."
    # (Reincarnation.) CR 110.2 makes the spell's controller the default, so
    # the phrase is only ever read here — consumed, because a dropped "under
    # the control of" is a permanent entering under the wrong player.
    under_control_of: ast.PlayerRef | None = None
    if destination.name == "battlefield" and stream.accept_phrase(
        "under", "the", "control", "of"
    ):
        under_control_of = parse_player_ref(stream)
        if under_control_of is None:
            raise stream.error("expected a player after 'under the control of'")
    # "…to the battlefield **under your control**." (Takklemaggot.) The
    # possessive spelling of the phrase above and the same field: CR 110.2's
    # default happens to be the same seat, but a phrase left unconsumed is a
    # line the grammar refuses, and one consumed into nothing is a permanent
    # whose controller the card named and the engine guessed.
    elif destination.name == "battlefield" and stream.accept_phrase(
        "under", "your", "control"
    ):
        under_control_of = ast.PlayerRef("you")
    # "…to the battlefield **under its owner's control**." (Ivory Gargoyle.)
    # CR 400.3's default said out loud, on the same field as the two spellings
    # above — the seat is what the phrase names, and reading it as the ability's
    # controller would put a stolen creature back on the thief's side.
    elif destination.name == "battlefield" and stream.accept_phrase(
        "under", "its", "owner", "'s", "control"
    ):
        under_control_of = ast.PlayerRef("owner")

    # "…attached to that creature." (Takklemaggot.) CR 303.4f: an effect that
    # puts an Aura onto the battlefield has to say what it attaches to. "That
    # creature" is the one an earlier step of this same sentence chose, so what
    # is recorded is the *reference* ("chosen"), not a filter; the lowering
    # turns it into the scratchpad key and refuses the phrase when no earlier
    # step of the sentence wrote one.
    attached_to: str | None = None
    if destination.name == "battlefield" and stream.accept_phrase("attached", "to"):
        if not (
            stream.accept_phrase("that", "creature")
            or stream.accept_phrase("that", "permanent")
        ):
            raise stream.error("expected the permanent it is attached to")
        attached_to = "chosen"

    # "…as a **non-Aura** enchantment." (Takklemaggot.) A layer-4 type change
    # (CR 613.1d) on the permanent the move creates. Read as "non-<subtype>
    # <card type>": the card type has to match what the returning object
    # already is, because the sentence is describing it rather than changing
    # it, and the subtype is the whole of what the word "non-" takes away.
    losing_subtypes: tuple[str, ...] = ()
    if destination.name == "battlefield":
        mark_as = stream.mark()
        if stream.accept_phrase("as", "a") or stream.accept_phrase("as", "an"):
            word = stream.peek_word()
            if word is not None and word.startswith("non-"):
                stream.advance()
                subtype = word[len("non-"):]
                if stream.accept_word("enchantment", "artifact", "creature", "land"):
                    losing_subtypes = (subtype,)
                else:
                    stream.reset(mark_as)
            else:
                stream.reset(mark_as)

    from_zone: ast.Zone | None = None
    if isinstance(subject, ast.TargetSpec) and subject.filter.zone != "battlefield":
        from_zone = ast.Zone(subject.filter.zone, subject.filter.zone_owner)
    # "…**for each card discarded this way**." (Recall.) A repetition of the
    # whole return, so it is read here at the end of the clause and carried on
    # the node; lowering refuses a shape it cannot repeat rather than dropping
    # the words.
    repetitions = _parse_for_each_this_way(stream)

    def _one(each: ast.Recipient) -> ast.ReturnToZone:
        each_from = from_zone
        if isinstance(each, ast.TargetSpec) and each.filter.zone != "battlefield":
            each_from = ast.Zone(each.filter.zone, each.filter.zone_owner)
        return ast.ReturnToZone(
            each, destination, each_from, entering_tapped=entering_tapped,
            entering_counters=entering_counters,
            under_control_of=under_control_of, repetitions=repetitions,
            actor=actor,
            attached_to=attached_to, losing_subtypes=losing_subtypes,
        )

    if further:
        return ast.Conjunction(tuple(_one(each) for each in (subject, *further)))
    return _one(subject)


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
