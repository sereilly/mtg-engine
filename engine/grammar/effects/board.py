"""The battlefield: destruction, bouncing, tapping, control.

Return-to-zone, destroy, tap/untap, gain control, and `_parse_that_object` —
the back-reference a delayed effect uses to name the permanent its trigger
bound ("destroy *that creature* at end of combat").

These productions read a zone through `phrases._parse_zone`; they do not define
one, because "search your library" needs the same fragment and neither family
should own the other's vocabulary.
"""

import dataclasses

from .. import ast
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..lexer import NUMBER
from ..readers import accept_source_reference
from ..references import parse_player_ref, parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, CREATURE_TYPES, NUMBER_WORDS, SUBTYPE_INDEX, match_longest)
from ..phrases import (
    _accept_number, _accept_self_reference, _parse_counted_sacrifice,
    _parse_for_each_this_way, _parse_mana_payment, _parse_pay_life, _parse_zone,
    parse_counted_subject, parse_pair_ordinal_subject, parse_subject_filter_at,
)


def _parse_gain_control(
    stream: TokenStream, *, leading_duration: str | None = None
) -> ast.GainControl | None:
    """``Gain control of <subject> <duration>.``

    Returns None — cursor untouched — unless the line really opens "gain
    control": "gains flying", "you gain 3 life" and "gains control of this
    creature" (Ghazbán Ogre, whose subject comes first) all begin with the same
    verb and are read elsewhere.

    The duration clause is *required*, and only the shapes a handler implements
    are admitted: "until end of turn", "for as long as you control this
    <noun>" (Aladdin, The Wretched), and that clause with "…and this <noun>
    remains tapped" behind it (Willow Satyr, Rubinia Soulsinger). An untimed
    "gain control of target creature" is a permanent control change; a
    differently-conditioned one (Old Man of the Sea's power comparison)
    reverts on things nothing here watches. Each would be this production's
    sentence with the ending changed, so each has to fail rather than borrow
    a linked duration it does not print.
    """
    mark = stream.mark()
    stream.expect_word("gain")
    if not stream.accept_word("control"):
        stream.reset(mark)
        return None
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    # "that creature" (Disharmony) — the object a previous sentence already
    # chose, read by the same back-reference the destroy production uses so
    # the two cannot drift apart about what the phrase names.
    subject = _parse_that_object(stream) or parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to gain control of")
    # "…until end of turn" (Traitorous Greed). A lifetime of its own rather than
    # one tied to a permanent that is still there: the spell that granted it is
    # in a graveyard by the time the turn ends, so nothing can be watched for —
    # CR 611.2c ends it at cleanup instead.
    if leading_duration is not None:
        # "**For as long as this creature remains tapped,** gain control of …"
        # (Preacher.) The duration printed in front of the verb instead of
        # behind it, read by the statement layer and handed down — the same
        # sentence either way, so there is one production and one lowering. A
        # card printing *both* is refused rather than having one silently win.
        if stream.at_word("until", "for"):
            raise stream.error("this sentence prints two different durations")
        return ast.GainControl(subject, leading_duration)
    if stream.accept_phrase("until", "end", "of", "turn"):
        return ast.GainControl(subject, "until_end_of_turn")
    if not stream.accept_phrase("for", "as", "long", "as"):
        raise stream.error(
            "no handler for a control change without a duration the engine ends"
        )
    # "…for as long as **this creature remains on the battlefield**" (Scarwood
    # Bandits). A weaker link than "you control this creature": an opponent who
    # steals the Bandits breaks that one and not this one, so the two are
    # different durations and the sweep tests them separately. Read before the
    # control clause because the two share only the four words above.
    mark = stream.mark()
    if _accept_self_reference(stream) and stream.accept_phrase(
        "remains", "on", "the", "battlefield"
    ):
        return ast.GainControl(subject, "while_source_on_battlefield")
    stream.reset(mark)
    if not stream.accept_phrase("you", "control"):
        raise stream.error(
            "no handler for a control change without a duration the engine ends"
        )
    if not _accept_self_reference(stream):
        raise stream.error("expected the permanent the control change is linked to")
    # "…and this creature remains tapped" — the second condition of the linked
    # duration (CR 611.2b). Only the self-referential spelling is admitted:
    # a condition about any other object would be one the sweep has no record
    # to check, so the words stay unconsumed and the line fails loudly.
    if stream.accept_word("and"):
        if not _accept_self_reference(stream) or not stream.accept_phrase(
            "remains", "tapped"
        ):
            raise stream.error(
                "the only compound linked duration is "
                "'…and this permanent remains tapped'"
            )
        return ast.GainControl(subject, "while_you_control_source_tapped")
    return ast.GainControl(subject, "while_you_control_source")


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
    further = _parse_further_subjects(stream)
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


def _parse_further_subjects(stream: TokenStream) -> list[ast.Recipient]:
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
        # Every phrase in the union must be a *sweep*, which is the shape this
        # production exists for and the shape it can be sure of. "and" is the
        # commonest word on a Magic card and most of its uses join two effects,
        # not two objects: "destroy this artifact **and** it deals damage to
        # you" (Voodoo Doll) has a perfectly good noun phrase after the "and",
        # and reading it as a second thing to destroy destroyed the artifact
        # and dropped the damage. A quantifier is the one signal available
        # before the verb arrives, so the union takes only "all …, all …, and
        # all …" and hands every other "and" back to the statement parser.
        if (
            not isinstance(nxt, ast.TargetSpec)
            or nxt.quantifier not in ("all", "each")
        ):
            stream.reset(mark)
            return extra
        extra.append(nxt)


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
    further = _parse_further_subjects(stream)

    # "…at end of combat" (CR 603.7). Only this one delay: a destruction
    # deferred to the next end step is a different handler, so leaving those
    # tokens unconsumed is what keeps Stone Giant and Nettling Imp failing
    # loudly instead of being destroyed a step early.
    delay = "end_of_combat" if stream.accept_phrase("at", "end", "of", "combat") else ""

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
    if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
        "they", "can't", "be", "regenerated"
    ):
        no_regen = True
    else:
        stream.reset(mark)
    if further:
        return ast.Conjunction(tuple(
            ast.Destroy(each, no_regen=no_regen, delay=delay)
            for each in (subject, *further)
        ))
    return ast.Destroy(subject, no_regen=no_regen, delay=delay)


def _parse_that_object(stream: TokenStream) -> ast.TargetSpec | None:
    """``that <card type>`` — the object a trigger already named.

    Not a target: the trigger bound it when it fired, so nothing is chosen on
    resolution. It gets its own quantifier rather than being read as an ordinary
    noun phrase, so a lowering written for "target creature" can never receive
    it — the two reach completely different handlers, and the ones that take a
    bound object read it out of the trigger's context instead of the payload.

    Deliberately local to the destroy production. The phrase turns up all over
    the pool ("tap that creature", "that player discards"), and teaching the
    shared noun parser to claim it would let every one of those lines lower
    through a filter naming a card type nobody bound.
    """
    # "destroy **the other** creature" (Infinite Authority) — the second member
    # of a pair the trigger bound, read through the shared ordinal production
    # so the counter clause in the same sentence names it the same way.
    ordinal = parse_pair_ordinal_subject(stream)
    if ordinal is not None:
        return ordinal
    mark = stream.mark()
    if not stream.accept_word("that"):
        return None
    noun = stream.peek_word()
    if noun is not None and noun in CARD_TYPES:
        stream.advance()
        return ast.TargetSpec("that", ast.ObjectFilter(card_types=(noun,)))
    # "destroy that **Wall**" (Battering Ram). A subtype names the bound object
    # just as a card type does — the trigger that fired required it, so the word
    # is describing what was bound rather than narrowing a fresh choice. Read
    # through the vocabulary, so a made-up noun still refuses.
    matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
    if matched is not None and matched[0] in CREATURE_TYPES:
        stream.advance(matched[1])
        return ast.TargetSpec(
            "that",
            ast.ObjectFilter(card_types=("creature",), subtypes=(matched[0],)),
        )
    stream.reset(mark)
    return None


def _parse_doesnt_untap_next_step(
    stream: TokenStream, subject: ast.Recipient
) -> ast.Statement:
    """``<subject> don't untap during their controller's next untap step.``

    The verb is already at the cursor; the subject was read by the sentence's
    subject position and is passed in.

    Every word of the duration is consumed literally, and two of them are the
    production's whole safety:

    * **"next"** is required. Drop it and the sentence is "…don't untap during
      their controller's untap step", which is the *permanent* restriction
      ``engine/auras.py`` derives for Paralyze and Capture Sphere — a strictly
      larger effect. Refusing the wording without "next" is what makes the
      deletion probe's rider check pass honestly rather than by accident.
    * **"their/its controller's"** is required, and "your" is refused. They are
      different effects: this one is per-creature, and "your next untap step"
      (exert's wording, CR 701.43a) is the *controller of the effect's* step,
      which the marker this lowers to carries no seat to express.
    """
    stream.expect_word("don't", "doesn't")
    stream.expect_word("untap")
    stream.expect_word("during")
    stream.expect_word("their", "its")
    stream.expect_word("controller")
    stream.expect_word("'s")
    # "…untap step **for as long as this creature remains tapped**" (Phyrexian
    # Gremlins). No "next": the restriction is continuous and ends when the
    # source untaps, which is a different effect from Frost Breath's one-shot
    # and gets a different node. Tried before requiring "next" so the two
    # spellings do not have to be told apart by their prefixes.
    linked = stream.mark()
    if stream.accept_phrase("untap", "step", "for", "as", "long", "as", "this"):
        # The noun is required. Accepted-but-optional, it could be deleted with
        # no change to what was lowered — which is what the parse-coverage
        # deletion probe reports, and the shape three productions in
        # `paragraphs.py` were tightened out of at the same time.
        if stream.accept_word(
            "creature", "artifact", "enchantment", "land", "permanent"
        ) and stream.accept_phrase("remains", "tapped"):
            return ast.DoesntUntapWhileSourceTapped(subject)
    stream.reset(linked)
    stream.expect_word("next")
    # "…next **two** untap steps" (Telekinesis). The number is read rather than
    # skipped: a restriction that survived one untap step where the card says
    # two is the creature back a turn early, and one that skipped the word would
    # report supported while doing it.
    count = 1
    counted = stream.mark()
    word = stream.peek_word()
    if word in NUMBER_WORDS:
        count = NUMBER_WORDS[word]
        stream.advance()
        if not (stream.at_word("untap") and stream.peek_word(1) == "steps"):
            # A number with the singular noun after it is not this sentence.
            stream.reset(counted)
            count = 1
    stream.expect_word("untap")
    stream.expect_word("step", "steps")
    return ast.DoesntUntapNextStep(subject, count=count)


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


def _parse_exchange_control(stream: TokenStream) -> ast.Statement:
    """``Exchange control of <first> and <second>.`` (CR 701.12b — Gauntlets of
    Chaos.)

    Both halves go through ``parse_recipient``, so the printed type list
    ("target artifact, creature, or land you control") and the printed
    controller ("target permanent an opponent controls") are read by the noun
    phrase every other production already uses.

    "…that shares one of those types with it" is read *here* rather than by the
    noun parser, and that is the point: it compares the second permanent with
    the **first**, and an ``ObjectFilter`` describes one permanent with nothing
    to compare against. Parsed there it could only have been dropped, and a
    dropped restriction is an exchange the card does not allow — a Mox traded
    for a Forest. The production that holds both slots is the one that can
    carry it.
    """
    stream.expect_word("exchange")
    stream.expect_word("control")
    stream.expect_word("of")
    first = parse_recipient(stream)
    if first is None:
        raise stream.error("expected what to exchange control of")
    if not stream.accept_word("and"):
        raise stream.error("expected 'and' between the two permanents exchanged")
    second = parse_recipient(stream)
    if second is None:
        raise stream.error("expected the other permanent of the exchange")
    shares = stream.accept_phrase(
        "that", "shares", "one", "of", "those", "types", "with", "it"
    )
    return ast.ExchangeControl(first, second, shares_a_type=bool(shares))


def _parse_tap_untap(stream: TokenStream) -> ast.Statement:
    """``tap <objects>`` / ``untap <objects>`` / ``tap or untap <objects>``.

    The disjunction (Twiddle) is read here rather than as two statements joined
    by "or": both directions act on the *same* chosen target and only one of
    them happens, so a ``Conjunction`` would tap the permanent and then untap
    it. Only "tap or untap" is a disjunction — "untap or tap" is not printed on
    any card, and inventing it would accept text no card carries.
    """
    verb = stream.expect_word("tap", "untap").text
    either_way = False
    if verb == "tap":
        mark = stream.mark()
        if stream.accept_word("or") and stream.accept_word("untap"):
            either_way = True
        else:
            stream.reset(mark)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error(f"expected something to {verb}")
    if either_way:
        return ast.TapOrUntap(subject)
    return ast.Tap(subject) if verb == "tap" else ast.Untap(subject)


def _parse_sacrifice(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    """"<player> sacrifices <noun>", with the verb already consumed.

    Two spellings reach it: the bare imperative, whose player is you, and a
    printed subject ("each opponent sacrifices a creature", Goremand). One
    production for both, because who sacrifices is the node's field and the
    sentence is otherwise word-for-word the same — the alternative was a second
    copy that would have had to grow the "another" reading and the unless-pay
    tail again.
    """
    # "Sacrifice **another** creature" (Dire Fleet Warmonger) — the same
    # reading the cost parser gives the word: a restriction on what may be
    # sacrificed, carried on the filter's existing field.
    another = bool(stream.accept_word("another"))
    subject = parse_recipient(stream)
    if subject is None:
        # "You may sacrifice **two Islands**." (Leviathan.) A bare count in
        # front of an untargeted plural, which `parse_recipient` has no reading
        # for — the same noun phrase the "unless you sacrifice" tail below
        # already reads, so it is the same production rather than a second
        # spelling of "two Islands". Without it the offer refused, and
        # Leviathan's whole upkeep line with it.
        counted = _parse_counted_sacrifice(stream, player)
        if counted is not None:
            return counted
        raise stream.error("expected something to sacrifice")
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
    if stream.accept_word("destroy"):
        action = "destroy"
    elif stream.accept_word("return"):
        action = "bounce"
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
