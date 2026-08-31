"""The battlefield: destruction, bouncing, sacrificing, attaching.

Return-to-zone, destroy, sacrifice, attach, and `_parse_that_object` — the
back-reference a delayed effect uses to name the permanent its trigger bound
("destroy *that creature* at end of combat").

Tapping left for ``effects/tapping.py`` when this module reached the
thousand-line guard, and it left under that name because ``lowering/tapping.py``
has carried it since the lowering side crossed the same cap — so the mirror
re-forms rather than forking, which is the whole of the naming rule in
CLAUDE.md.

These productions read a zone through `phrases._parse_zone`; they do not define
one, because "search your library" needs the same fragment and neither family
should own the other's vocabulary.
"""

import dataclasses

from .. import ast
from ..amounts import (_parse_for_each_this_way, accept_fraction_head,
                       accept_rounding, parse_amount)
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..lexer import NUMBER
from ..readers import accept_source_reference
from ..references import parse_player_ref, parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, CREATURE_TYPES, NUMBER_WORDS, SUBTYPE_INDEX, match_longest)
from ..phrases import (
    _accept_number, _accept_self_reference, _parse_counted_sacrifice,
    _parse_mana_payment, _parse_pay_life,
    _parse_sacrificed_subject, _parse_that_object, _parse_zone,
    parse_bound_subject, parse_counted_subject, parse_pair_ordinal_subject,
    parse_subject_filter_at,
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
    if stream.accept_phrase("that", "card"):
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
            under_control_of=under_control_of, repetitions=repetitions,
            actor=actor,
            attached_to=attached_to, losing_subtypes=losing_subtypes,
        )

    if further:
        return ast.Conjunction(tuple(_one(each) for each in (subject, *further)))
    return _one(subject)


def _parse_further_subjects(
    stream: TokenStream,
    first: "ast.Recipient | None" = None,
    *,
    several_targets: bool = False,
) -> list[ast.Recipient]:
    """The rest of ``<noun phrase>, <noun phrase>, and <noun phrase>``.

    "Return to your hand all enchantments you both own and control, all Auras
    you own attached to permanents you control, and all Auras you own attached
    to attacking creatures your opponents control." (Remove Enchantments.) One
    verb over a union of three noun phrases, which no single ``ObjectFilter``
    says: its keys are AND'd, so the three folded into one would name an
    enchantment that is simultaneously an Aura on your own permanent and an
    Aura on an attacking creature of an opponent's — nothing at all.

    So the union lives in the *shape*: the caller builds one statement per
    phrase and joins them with :class:`ast.Conjunction`, which lowering already
    turns into a sequence. Two sweeps over overlapping sets are the same
    outcome as one sweep over their union, because both are idempotent — a
    permanent already returned is no longer there to return again.

    Returns an empty list with the cursor untouched unless a separator really
    is followed by another noun phrase, so "destroy target creature **and** you
    gain 2 life" still reads as two effects rather than failing here.
    """
    extra: list[ast.Recipient] = []
    while True:
        mark = stream.mark()
        # A separator is required. Without one, two adjacent noun phrases would
        # be joined by nothing but the parser's willingness to keep reading.
        separated = stream.accept_punct(",")
        separated = stream.accept_word("and") or separated
        nxt = (
            parse_recipient(stream)
            if separated and not stream.at_word("to")
            else None
        )
        # Every phrase in the union must name an *object*, which is the shape
        # this production exists for and the shape it can be sure of. "and" is
        # the commonest word on a Magic card and most of its uses join two
        # effects, not two objects: "destroy this artifact **and** it deals
        # damage to you" (Voodoo Doll) has a perfectly good noun phrase after
        # the "and", and reading it as a second thing to destroy destroyed the
        # artifact and dropped the damage. A quantifier is the one signal
        # available before the verb arrives, so the union takes only the
        # quantifiers that cannot begin a clause and hands every other "and"
        # back to the statement parser.
        #
        # **"target" is one of them**, and it is the safest of the three:
        # "Destroy target creature **and target land**" (Fumarole), "Exile this
        # creature **and target creature** without flying that's attacking you"
        # (Giant Trap Door Spider). The word starts a noun phrase and nothing
        # else, and the shape that looks dangerous — "…**and target player**
        # draws a card" — is excluded by the line above rather than by luck: a
        # targeted *player* parses to ``ast.PlayerRef``, so it was never a
        # candidate for this union at all.
        if (
            not isinstance(nxt, ast.TargetSpec)
            or nxt.quantifier not in ("all", "each", "target", "this")
        ):
            stream.reset(mark)
            return extra
        # **"this <type>" is the fourth, and the only one that needs a second
        # test.** "Destroy it **and this creature** at end of combat" (Goblin
        # Sappers) is a union; "tap all untapped Islands that player controls
        # **and this enchantment deals X damage** to the player" (Monsoon) is
        # two clauses whose second one opens with the very same noun phrase, and
        # so do Earthbind and Vexing Arcanix. The three quantifiers above cannot
        # begin a clause, and this one can — a permanent naming itself is the
        # commonest *subject* on a card.
        #
        # So the union takes it only where the phrase ends the sentence: at a
        # terminator, or in front of the one trailing clause a union may carry
        # (the "at end of combat" delay, read by the caller). Anything else is a
        # verb about to arrive, and the "and" belongs to the statement parser.
        if nxt.quantifier == "this" and not (
            stream.exhausted
            or stream.at_punct(".", ";", ",")
            or stream.at_word("at")
        ):
            stream.reset(mark)
            return extra
        # **At most one targeted phrase in the union, unless the caller can
        # describe several.** The reason used to be flat: the cast picker asks a
        # spell for one target, so "Destroy target creature and target land"
        # (Fumarole) would compile supported and then be uncastable, its second
        # target picked by nobody. That is still true of a union the caller
        # lowers to a ``Conjunction`` — a sequence of instructions whose spec is
        # derived from the first one that describes targets, leaving the rest
        # unasked — and it is *not* true of a caller that folds the phrases into
        # one statement with an ordered ``roles`` description, which the picker,
        # the cast gate and the AI have all read since Glyph of Delusion.
        #
        # So the refusal moves to the callers that cannot: ``several_targets``
        # is the claim "my lowering describes every one of these", and only the
        # destroy production makes it.
        #
        # The unions whose first phrase is the source are unaffected either way:
        # "Exile **this creature** and target creature …" names one target.
        if (
            not several_targets
            and nxt.quantifier == "target"
            and any(
                isinstance(prior, ast.TargetSpec) and prior.quantifier == "target"
                for prior in ((first,) if first is not None else ()) + tuple(extra)
            )
        ):
            raise stream.error(
                "no spell picks two targets from one verb"
            )
        extra.append(nxt)


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
        return ast.DestroyUnlessPay(subject, _parse_mana_payment(stream))
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
            # targets of one spell are one announcement (CR 601.2c), so they are
            # one statement — see ``ast.Destroy.also_targets``. A conjunction
            # here would be two instructions, and only the first would be given
            # a picker. Every phrase must be targeted: a union mixing a target
            # with a swept set is two different things happening, and the sweep
            # half has nothing to ask a caster.
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


def _parse_attach(stream: TokenStream) -> ast.Statement:
    """``Attach <subject> to <host>`` (CR 701.3).

    The sentence CR 702.6a expands equip into — "Attach this permanent to
    target creature you control" — and its one generalisation, a chosen
    Equipment ("Attach target Equipment you control to target creature you
    control"). Both halves go through `parse_recipient`, so a narrowed host
    ("target legendary creature you control", CR 702.6c's "Equip [quality]")
    is read by the noun phrase every other production already uses rather than
    by anything here. The whole line must be consumed: a trailing clause this
    does not read is a refusal, never a silent partial attach.
    """
    stream.expect_word("attach")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to attach")
    if not stream.accept_word("to"):
        raise stream.error("expected 'to' after what is attached")
    host = parse_recipient(stream)
    if host is None:
        raise stream.error("expected what to attach to")
    return ast.Attach(subject, host)


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
    return ast.Sacrifice(player, subject)


def _parse_sacrifice_expansion_permanents(stream: TokenStream) -> ast.Statement | None:
    """``Each nontoken permanent with a name originally printed in the <Set>
    expansion is sacrificed by its controller.`` (Golgothian Sylex.)

    The set *name* is printed and the engine wants its code, so the mapping is
    asked of the manifest — the registry that already holds both — rather than
    written out here. A name the manifest does not know leaves the line
    unconsumed and its card unsupported, which is the right answer: the effect
    would otherwise sacrifice the permanents of whichever set the caller
    guessed, or of none, and neither is what the card says.
    """
    from ...card_loader import set_code_for_expansion_name

    mark = stream.mark()
    if not stream.accept_phrase(
        "each", "nontoken", "permanent", "with", "a", "name",
        "originally", "printed", "in", "the",
    ):
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_word("expansion"):
        word = stream.peek_word()
        if word is None:
            stream.reset(mark)
            return None
        words.append(word)
        stream.advance()
    if not words or not stream.accept_word("expansion"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("is", "sacrificed", "by", "its", "controller"):
        stream.reset(mark)
        return None
    set_code = set_code_for_expansion_name(" ".join(words))
    if set_code is None:
        stream.reset(mark)
        return None
    return ast.SacrificeExpansionPermanents(set_code)


def _parse_shuffle_graveyard_into_library(stream: TokenStream) -> ast.Statement | None:
    """``Shuffle your graveyard into your library.`` (Feldon's Cane.)

    Both possessives are read rather than assumed. A card moving *another*
    player's graveyard is a different effect, and consuming "your" without
    checking it would compile that card onto this one.
    """
    mark = stream.mark()
    # "your graveyard" is a possessive, not a player reference — `parse_player_ref`
    # reads "you" / "target player" / "each opponent" and rightly refuses it —
    # so the word is matched directly, and both occurrences are checked. A card
    # moving *another* player's graveyard is a different effect, and consuming
    # the possessive without reading it would compile that card onto this one.
    if not stream.accept_phrase(
        "shuffle", "your", "graveyard", "into", "your", "library"
    ):
        stream.reset(mark)
        return None
    return ast.ShuffleGraveyardIntoLibrary(ast.PlayerRef("you"))


def _parse_shuffle_hand_into_library(stream: TokenStream) -> ast.Statement | None:
    """``Each player shuffles the cards from their hand into their library,
    then draws that many cards.`` (Winds of Change.)

    Read here beside the graveyard shuffle for the reason that one is read
    outside the subject-verb loop: the sentence's object is a *zone*, not a set
    of objects a filter could test, so the reader that expects a noun phrase has
    nothing to take.

    The possessive has to agree with the subject, which is what makes this the
    sentence it looks like: "each player shuffles the cards from **your** hand"
    would be a different effect, and consuming the word without reading it would
    compile that card onto this one — the check `_parse_shuffle_graveyard_into_library`
    makes for the same reason.

    The draw is part of this production rather than a sentence after it: "that
    many" is the number of cards the shuffle just moved, which nothing else in
    the line knows. Parsed apart it would be a draw with no producer, and a
    producerless back-reference reads as zero.
    """
    mark = stream.mark()
    player = parse_player_ref(stream)
    if player is None or not stream.accept_word("shuffles", "shuffle"):
        stream.reset(mark)
        return None
    whose = "your" if player.kind == "you" else "their"
    # "shuffles **the cards from** their hand" is the current wording and
    # "shuffles their hand" the older one; they name the same cards, so the
    # phrase is optional rather than a second production.
    stream.accept_phrase("the", "cards", "from")
    if not stream.accept_phrase(whose, "hand", "into", whose, "library"):
        stream.reset(mark)
        return None
    then_draw = False
    probe = stream.mark()
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "draws" if whose == "their" else "draw", "that", "many", "cards"
    ):
        then_draw = True
    else:
        stream.reset(probe)
    return ast.ShuffleHandIntoLibrary(player, then_draw=then_draw)


def _parse_delayed_self_action(stream: TokenStream) -> ast.Statement | None:
    """``Destroy this artifact at the beginning of the next end step.`` /
    ``Return this artifact to its owner's hand at the beginning of the next end
    step.``

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


def parse_player_chooses_permanent(
    stream: TokenStream, chooser: "ast.PlayerRef"
) -> "ast.ChoosePermanent | None":
    """``<player> chooses <noun phrase> [that this card could enchant].``

    "That creature's controller chooses a creature that this card could
    enchant." (Takklemaggot.) The subject has already been read, so this starts
    at the verb.

    Nothing is targeted: the sentence prints no "target" and the pick is made as
    the ability resolves (CR 601.2c/115.1b), which is exactly the shape
    ``engine/handlers/permanent_choices.py`` already performs — so this is a
    noun phrase and a seat, not a new mechanism.

    The relative clause is read **here** rather than taught to
    ``parse_object_filter``, the same rule ``_parse_that_object`` follows: it
    is a question about a *pair* of permanents (may this Aura enchant that
    creature?), and the shared filter matcher answers about one. Teaching it to
    the noun parser would hand the words to every line that prints them and
    then drop them.

    Returns None with the cursor untouched when the sentence is a different
    "chooses" — a card name, a colour, a mode — so those keep their own
    readings.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    spec = parse_target_spec(stream)
    if spec is None or spec.targeted or spec.quantifier != "a" or spec.count != 1:
        stream.reset(mark)
        return None
    host_for_source = False
    if stream.accept_phrase("that", "this", "card", "could", "enchant"):
        host_for_source = True
    elif stream.accept_phrase("that", "this", "aura", "could", "enchant"):
        host_for_source = True
    if not host_for_source:
        # Every other narrowing a "chooses" sentence could print is one this
        # production has no answer for, and a choice made from a wider set than
        # the card names is not the card. Refused rather than admitted with the
        # clause dropped.
        stream.reset(mark)
        return None
    # The choice is optional exactly when the sentences behind it print both
    # branches; the rider that reads "If they don't" is what says so, and it
    # sets the flag through `dataclasses.replace`.
    return ast.ChoosePermanent(chooser, spec, host_for_source=host_for_source)


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
    * the payer must be printed "any player" — the lowering has nowhere to put
      a narrower one, and a buyout offered to fewer seats than the card names
      is a different card;
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
    if not stream.accept_phrase("unless", "any", "player", "pays"):
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
    return ast.DestroyEachUnlessPaid(filt, life)
