"""Returning an object to a zone — "Return <object> [from <zone>] to <zone>".

Split out of ``effects/board.py`` when Mirage's second wave took that module
past the thousand-line guard, and it left under ``lowering/returns.py``'s name
for the rule CLAUDE.md states and this package has now followed five times
(``tapping``, ``attachments``, ``prevention``, ``counters``, and now this): a
family that already exists on the other side re-forms rather than forking a
second vocabulary. The seam is the one ``board``'s own docstring drew when it
opened "Return-to-zone, destroy, sacrifice" — a return names **two** zones, the
one an object leaves and the one it goes to, and that pair is what picks the
handler; everything left behind acts on a permanent where it stands.

``_parse_further_subjects`` went down out of ``board`` rather than travelling
with either half. Both the return here and the destroy left behind read it, and
a production two families need has no home inside one of them — the same move
``_expect_counter_kind`` made when ``counters`` left ``characteristics``. It
came to rest in ``references`` a wave later, one layer further down again, for
the reason recorded there; ``phrases`` re-exports it, so the import above still
reads as it was written.
"""

from .. import ast
from ..errors import GrammarError
from ..readers import _parse_entering_counters, accept_source_reference
from ..records import _parse_for_each_this_way
from ..references import parse_player_ref, parse_recipient
from ..sacrifices import parse_counted_subject
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES
from ..phrases import _parse_further_subjects, _parse_zone


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
        # "Return **two Islands** you control to their owner's hand." (Flooded
        # Shoreline's cost, Bull Elephant's price.) A bare printed count in
        # front of an untargeted plural, which `parse_recipient` has no reading
        # for — the counted position is the one the noun parser wants told about
        # — so it goes through the same floor the sacrifice clauses use. One
        # reading of "two Islands", which is what keeps a cost, an offer and an
        # effect printing the phrase from meaning three different things.
        counted = parse_counted_subject(stream)
        if counted is not None:
            count, described = counted
            subject = ast.TargetSpec("a", described, count=count)
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
        if (
            stream.accept_phrase("that", "creature")
            or stream.accept_phrase("that", "permanent")
        ):
            attached_to = "chosen"
        # "…to the battlefield **attached to Hakim**." (Hakim, Loreweaver.) The
        # ability's own source rather than something an earlier step chose, and
        # a second referent rather than a second reading of "chosen": nothing
        # earlier in this sentence picks a host, so the scratchpad key would be
        # read and found empty, and the Aura would arrive attached to nothing.
        elif accept_source_reference(stream):
            attached_to = "source"
        else:
            raise stream.error("expected the permanent it is attached to")

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


def _parse_return_instead_of_untapping(
    stream: TokenStream,
) -> "ast.Statement | None":
    """``During your next untap step, as you untap your permanents, return this
    land to its owner's hand.`` (Undiscovered Paradise.)

    None with the cursor untouched when the sentence is not this one, because it
    is tried in front of the ordinary sentence reader: "during" opens no effect
    the subject-verb reader has, so a refusal here has to leave the line to
    whatever comes next rather than failing it.

    Read whole rather than as "a fronted window plus a return". Every word of it
    is fixed — the window is the controller's next untap step, the object is the
    ability's own source, the destination is CR 400.3's owner's hand — so there
    is nothing for a general reader to vary, and a version that consumed the
    window and handed the tail to `_parse_return` would produce an ordinary
    self-bounce with the timing dropped. That is the failure this grammar
    refuses by construction: the card would report supported and return the land
    the moment the ability resolved, which is a strictly better card.

    The middle clause is the one that has to be consumed rather than skipped:
    "as you untap your permanents" is CR 502.2's turn-based action, and it is
    what makes this a replacement of the untap instead of a delayed trigger.
    """
    mark = stream.mark()
    if not stream.accept_phrase("during", "your", "next", "untap", "step"):
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("as", "you", "untap", "your", "permanents"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_word("return"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("to", "its", "owner", "'s", "hand"):
        stream.reset(mark)
        return None
    return ast.ReturnSelfInsteadOfUntapping()
