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
from ..records import _parse_for_each_history
from ..references import parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..phrases import (
    _parse_mana_payment, _parse_pay_life, _parse_per_each_counters,
    _parse_per_each_objects,
    _parse_that_object, _parse_zone, accept_graveyard_position,
)
from ..sacrifices import (_parse_counted_sacrifice, _parse_sacrificed_subject,
                         parse_counted_subject)










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
    # "…sacrifices a creature of their choice **for each creature put into your
    # graveyard from the battlefield this turn**." (Urborg Justice.) A count of
    # the *turn's history* rather than of anybody's board, and asked **before**
    # the board reader below: that one consumes "for each creature" and hands it
    # back as a set, which left "put into your graveyard from the battlefield
    # this turn" as unconsumed text and refused the line. This reader declines
    # with the cursor unmoved, so asking it first costs the board reading
    # nothing.
    history = _parse_for_each_history(stream, parse_object_filter)
    if history is not None:
        return ast.Sacrifice(player, subject, count=history)
    # "…that player sacrifices a permanent of their choice **for each soot
    # counter on this artifact**." (Smokestack.) A pile of counters rather than
    # a set of objects, read through the same shared fragment the token count
    # reads and asked here for the reason the history reader above is asked
    # here: the board reader below would claim a counter word that happens to
    # also be a creature type and hand the rest of the clause back as
    # unconsumed text.
    per_counter = _parse_per_each_counters(stream)
    if per_counter is not None:
        return ast.Sacrifice(player, subject, count=per_counter)
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
    # "… unless you **return an untapped Island you control to its owner's
    # hand**." (Coral Atoll, Dormant Volcano, Everglades, Jungle Basin, Karoo,
    # Waterspout Djinn; "two Forests" on Bull Elephant, "three basic lands" on
    # Ovinomancer.) The fourth printed alternative, decomposed for the reason
    # the sacrifice and the tap above are: an "unless" is an offer with a
    # penalty, which is what `May` already says — so the offer, the penalty and
    # the "you have nothing to return" case all come from machinery that works.
    #
    # Read out of the two floors the other alternatives use rather than by
    # calling the return family's own production, because families do not
    # import each other. The count and the noun phrase are
    # `sacrifices.parse_counted_subject`, which is the *same* reader "unless you
    # sacrifice two Islands" uses — one reading of "two Forests", so the offer,
    # the takeability gate and the prompt cannot disagree about what the card
    # asks for. The destination is `phrases._parse_zone`, the engine's one
    # reader of a printed zone. Every rider `_parse_return` reads past that
    # phrase ("tapped", "under your control", entering counters) describes a
    # permanent entering the battlefield, which is a destination this price
    # cannot have.
    # "… unless you **exile the top creature card of your graveyard**." (Barrow
    # Ghoul, Circling Vultures.) The fifth printed alternative, decomposed for
    # the reason the three above are: an "unless" is an offer with a penalty,
    # which is what `May` already says — so the offer, the penalty and the "your
    # graveyard holds no creature card" case all come from machinery that
    # works, the last through `_action_is_takeable`'s entry for the kind.
    #
    # Read out of the shared fragment three families use
    # (`phrases.accept_graveyard_position`) rather than by calling the exile
    # family's own production, because families do not import each other — the
    # same arrangement the return tail below makes with `sacrifices` and
    # `phrases._parse_zone`. One reading of "the top creature card of your
    # graveyard", so the offer, the takeability gate and the payment cannot
    # disagree about which card the card asks for.
    if stream.accept_phrase("unless", "you", "exile"):
        priced = accept_graveyard_position(stream)
        if priced is not None:
            return ast.May(
                actor=player,
                action=ast.ExileGraveyardPosition(priced),
                otherwise=ast.Sacrifice(player, subject),
            )
    stream.reset(mark)
    if stream.accept_phrase("unless", "you", "return"):
        counted = parse_counted_subject(stream)
        if counted is not None and stream.accept_word("to"):
            count, described = counted
            return ast.May(
                actor=player,
                action=ast.ReturnToZone(
                    ast.TargetSpec("a", described, count=count),
                    _parse_zone(stream),
                    None,
                ),
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


def parse_simultaneous_phasing(
    stream: TokenStream,
) -> "ast.SimultaneousPhasing | None":
    """``Simultaneously, all phased-out creatures phase in and all creatures
    with phasing phase out.`` (Time and Tide, CR 702.26.)

    One production for both halves, because the printed adverb is what joins
    them: both sets are read before either is applied, and two statements in a
    sequence would apply in order — phasing a creature in and then straight back
    out again, which is the opposite of what the word says.

    Read as a whole sentence in ``parse_imperative``, ahead of the subject
    readers: it opens on an adverb no other production claims, and it refuses
    without consuming, so a sentence beginning "Simultaneously" that this cannot
    finish keeps whatever refusal it already had.

    "Phased-out" is consumed as *structure* rather than parsed as an adjective:
    CR 702.26b says a phased-out permanent is treated as though it does not
    exist, so it is not on any battlefield and no ``ObjectFilter`` over one can
    name it. What the word says is which collection the sentence is about. The
    noun phrase after it is read normally, so it still narrows.
    """
    mark = stream.mark()
    if not stream.accept_word("simultaneously"):
        return None
    stream.accept_punct(",")
    if not stream.accept_word("all"):
        stream.reset(mark)
        return None
    if not stream.accept_word("phased-out"):
        stream.reset(mark)
        return None
    returning = parse_object_filter(stream)
    if not stream.accept_phrase("phase", "in"):
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    leaving = parse_target_spec(stream)
    if leaving is None:
        stream.reset(mark)
        return None
    # The outgoing half is the ordinary sweep sentence ("all creatures with
    # phasing phase out"), which the phase-out production already reads on its
    # own — so it is the *subject* that is parsed here and the verb that is
    # checked, and nothing about which permanents it names is decided twice.
    if not stream.accept_phrase("phase", "out"):
        stream.reset(mark)
        return None
    return ast.SimultaneousPhasing(returning, leaving)


def _accept_keep_slot(stream: TokenStream) -> "ast.KeepSlot | None":
    """One printed keep — ``an artifact`` / ``five lands they control`` — or
    None with the cursor untouched.

    The noun phrase is ``parse_counted_subject``, the same reader the sacrifice
    clause beside it uses: "five lands they control" here and "two Islands"
    behind an attack cost are one phrase, and one reading is what keeps the
    keeps and the complement agreeing about what a card asked for.
    """
    mark = stream.mark()
    try:
        counted = parse_counted_subject(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if counted is None:
        stream.reset(mark)
        return None
    count, described = counted
    return ast.KeepSlot(count, described)


def parse_keep_then_sacrifice_rest(
    stream: TokenStream, chooser: "ast.PlayerRef"
) -> "ast.KeepChosenSacrificeRest | None":
    """``<player> chooses [from among <pool>] <slots>, then sacrifices the
    rest.`` The subject has been read, so this starts at the verb.

    "Each player chooses from among the permanents they control an artifact, a
    creature, an enchantment, and a land, then sacrifices the rest." (Cataclysm.)
    "Each player chooses five lands they control and sacrifices the rest."
    (Limited Resources.)

    One production for both spellings, and one node, because **"the rest" is a
    complement and only the first half of the sentence says what of**. Split at
    the comma the sacrifice would name every permanent on the table and the
    choice would be a record nothing reads — which is exactly what
    ``paragraphs._parse_rebalance_lands`` says about the same clause inside
    Natural Balance, where the words are word-for-word these.

    The pool is the printed "from among …" where the card prints one and the
    single slot's own noun where it does not, so the lowering has one shape to
    read. **Several slots with no printed pool refuses**: "chooses an artifact
    and a creature, then sacrifices the rest" leaves "the rest" naming either
    the union of the two nouns or the whole battlefield, and a production that
    picked one would be guessing at a sentence no card prints.

    Refuses without consuming for anything that is not this shape — every other
    "chooses …" keeps the reading it had — and the tail is required in full: a
    keep list with no complement behind it is a card that sacrifices nothing
    while reporting supported.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    pool = None
    if stream.accept_phrase("from", "among"):
        stream.accept_word("the")
        try:
            pool = parse_object_filter(stream)
        except GrammarError:
            pool = None
        if pool is None:
            stream.reset(mark)
            return None
    first = _accept_keep_slot(stream)
    if first is None:
        stream.reset(mark)
        return None
    slots = [first]
    while True:
        loop = stream.mark()
        stream.accept_punct(",")
        stream.accept_word("and")
        following = _accept_keep_slot(stream)
        if following is None:
            # The separator belongs to the tail below ("…, **and** a land,
            # **then** sacrifices…" prints both), so it goes back rather than
            # being eaten here.
            stream.reset(loop)
            break
        slots.append(following)
    stream.accept_punct(",")
    if not stream.accept_word("then", "and"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_word("sacrifices", "sacrifice")
        and stream.accept_phrase("the", "rest")
        and (stream.exhausted or stream.at_punct(".", ";"))
    ):
        stream.reset(mark)
        return None
    if pool is None:
        if len(slots) != 1:
            stream.reset(mark)
            return None
        pool = slots[0].filter
    return ast.KeepChosenSacrificeRest(chooser, pool, tuple(slots))
