"""A return whose object the sentence names by **description**.

Split off `_bound_returns.py` at Exodus' Phase 0, at the comma that module's
own docstring had already written: a sentence names the object it returns
either by reference — the firing event recorded it, or it is the ability's own
source — or by description, and resolving the two is different work. A
reference is resolved by *following* it, so the whole question is where the
object is now and every printed adjective is a restatement that refuses the
moment it is anything more. A description is resolved by *looking at the
board*, so the noun phrase **is** the instruction: it travels into the payload,
and the question every branch here asks is whether the narrowing survives to a
reader that can test it.

The two predicates came with it for that reason rather than by proximity. Both
answer "which narrowing does a return handler actually read", `returns` asks
them of its targeted branches, and every call to either one was already on this
side of the cut — the referencing half asks neither.

**The prose the cut followed was one clause short of the code, and the missing
clause is four of the six readings below.** "A description the handler sweeps"
names the two sweeps (Remove Enchantments, All Hallow's Eve). The other four
are *chosen, not targeted* (CR 115.1): a card out of your own graveyard
(Experimental Overload), Reincarnation's pick under two event-bound seats, Sun
Clasp's attachment — which CR 303.4b names rather than chooses, but which is
still whatever the Aura is on when this resolves — and the pick-then-act price
Shrieking Drake and Bull Elephant print. Nothing about them is announced, so
`returns` never sees them; what they share with the sweeps is that the printed
noun phrase decides which objects move, which is this module's question and not
the other's.

A floor rather than a family, for `_bound_returns`' reason exactly:
`_bound_returns` reads it — its last act is to hand the sentence down here —
`returns` reads the two predicates, and it reads neither of them back.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import CHOSEN_THIS_WAY_OBJECTS, OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._events import (EVENT_SUBJECT_OWNER, EVENT_SUBJECT_PLAYER,
                      _EVENT_SUBJECT_OWNERS, _EVENT_SUBJECT_PLAYERS)
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    chargeable_card_filter,
    _filter_payload,
    _is_enchanted,
    _restrictions_beyond,
)



def _reads_no_return_restriction(filt: ast.ObjectFilter) -> bool:
    """Whether *filt* carries a narrowing none of the zone-change handlers reads.

    All three take their whole instruction from the card: two read an empty
    payload and the third reads one boolean. So any adjective beyond the card
    type is invisible to them, and a filter carrying one has to refuse — "return
    target *black* creature card from your graveyard to your hand" lowered to
    Raise Dead's instruction would happily return a white one.
    """
    tri_state = (filt.tapped, filt.attacking, filt.blocking, filt.blocked)
    return bool(
        filt.supertypes or filt.subtypes or filt.colors or filt.excluded_colors
        or filt.excluded_types or filt.excluded_subtypes or filt.with_keywords
        or filt.without_keywords or filt.controller or filt.power or filt.toughness
        or filt.mana_value or filt.named or filt.other_than_source
        or filt.is_source or filt.is_enchanted
        or any(state is not None for state in tri_state)
    )



def _graveyard_to_hand_payload(filt: ast.ObjectFilter) -> dict[str, object]:
    """The card-type half of a graveyard-to-hand return's payload.

    One function because the one-card and several-card branches have to narrow
    *identically*: the named card type is a filter the handler applies, so it is
    carried rather than collapsed - reading "artifact card" as "any card" would
    let Reconstruction return a creature. A *union* ("instant or sorcery card",
    Shipwreck Dowser) travels as its own additive key, so Raise Dead's payload
    stays byte-identical. Two copies of this is how "up to two target artifact
    cards" ends up returning a creature.
    """
    # "Return target **Griffin** card from your graveyard to your hand."
    # (Mtenda Griffin.) A printed subtype, carried the way the reanimation's
    # colours are: its own additive key, tested by the same
    # ``graveyard_card_matches`` the picker and the cast gate ask, so a payload
    # written before this is byte-identical. Only the targeted graveyard-to-hand
    # branch lifts it out of ``_reads_no_return_restriction``; every other
    # caller here still refuses a subtype at that gate, so the key is absent for
    # all of them.
    subtypes = {"graveyard_subtypes": list(filt.subtypes)} if filt.subtypes else {}
    # "…return a **basic** land card from your graveyard to your hand."
    # (Harvest Wurm.) CR 205.4a's supertype, carried on the key
    # ``graveyard_card_matches`` already reads — it was written for Lodestone
    # Bauble's "basic land cards" and asks the printed type line, which for a
    # card in a graveyard is the whole of what there is (CR 613.1). Additive
    # like the subtype above, so every payload written before this is
    # byte-identical, and lifted out of ``_reads_no_return_restriction`` only by
    # the branch whose handler asks that predicate.
    if filt.supertypes:
        subtypes = {**subtypes, "supertypes": list(filt.supertypes)}
    if len(filt.card_types) > 1:
        return {
            "any_card": False,
            "card_type": None,
            "card_types": list(filt.card_types),
            **subtypes,
        }
    card_type = filt.card_types[0] if filt.card_types else None
    return {"any_card": card_type is None, "card_type": card_type, **subtypes}



def lower_described_return(
    node: ast.ReturnToZone,
    subject,
    event: str | None = None,
) -> tuple[OracleInstruction, ...] | None:
    """The untargeted readings whose object is a **described** set.

    Reached from :func:`_bound_returns.lower_untargeted_return`, after every
    reading that names its object by reference has refused the shape — so these
    continue that function's printed-specificity order rather than starting a
    new one. ``None`` means the sentence names an object a player *targets*,
    which is `returns`' half; a `LoweringError` raised in here is final.

    ``produced`` is not a parameter, and its absence is the seam stated as a
    signature: a described set is read off the board, so no earlier step of the
    sentence has anything to hand it.
    """
    # "…you may return **an** instant or sorcery card from your graveyard to
    # your hand." (Experimental Overload.) Chosen but not targeted (CR 115.1):
    # the card is in the chooser's own graveyard, so there is nothing for
    # targeting to protect — no shroud, no protection, no "changes target"
    # effect can reach it — and the picker the targeted spelling already uses is
    # the same picker. Admitted only in that shape: a *bare* quantifier over
    # anyone else's zone, or over the battlefield, still refuses.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
        and subject.filter.zone_owner is not None
        and subject.filter.zone_owner.kind == "you"
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
    ):
        # The supertype is lifted out of the blanket refusal here because this
        # is the branch whose handler asks ``graveyard_card_matches``, which
        # tests it — everywhere else in this file the gate still refuses one,
        # and a phrase whose adjective no reader tests is a return wider than
        # the card prints.
        if _reads_no_return_restriction(
            dataclasses.replace(subject.filter, supertypes=())
        ):
            raise LoweringError("no return handler honours this restriction", node=node)
        return (
            OracleInstruction(
                "return_creature_from_graveyard_to_hand", "",
                _graveyard_to_hand_payload(subject.filter),
            ),
        )
    # "Return a creature card from **its owner's** graveyard to the battlefield
    # **under the control of that creature's owner**." (Reincarnation.)
    #
    # Both possessives name one player and it is neither of the two a return
    # normally knows: not the chooser (CR 608.2c makes that the ability's
    # controller, who picks the card) and not the card's own owner in the
    # tautological sense (CR 404.2 puts every card in its owner's graveyard, so
    # that reading would admit every graveyard on the table). They name the
    # object *this sentence is about* — the creature the delayed ability was
    # bound to — which is why this shape is admitted only under an event whose
    # fire site actually froze that owner. Under any other trigger the words
    # name a player nobody recorded.
    #
    # It lowers to the ordinary open-zone pick, with the two seats as payload:
    # the picker, the AI and the resolver all read them through
    # `engine.search_filters.searched_seat` / `landing_seat`, so one answer
    # decides whose graveyard is shown and whose battlefield receives.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "a"
        and subject.count == 1
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
        and subject.filter.zone_owner is not None
        and subject.filter.zone_owner.kind == "owner"
        and node.to.name == "battlefield"
        and node.under_control_of is not None
        and node.under_control_of.kind == "owner"
    ):
        if event not in _EVENT_SUBJECT_OWNERS:
            raise LoweringError(
                "\"its owner\" names the object this sentence is about, and no "
                "trigger here recorded one",
                node=node,
            )
        if node.entering_tapped or _reads_no_return_restriction(subject.filter):
            raise LoweringError("no return handler honours this restriction", node=node)
        if len(subject.filter.card_types) != 1:
            raise LoweringError("the graveyard pick reads one card type", node=node)
        return (
            OracleInstruction(
                "search_library", "",
                {
                    "zones": ("graveyard",),
                    "card_type": subject.filter.card_types[0],
                    "destination": "battlefield",
                    "zone_owner": EVENT_SUBJECT_OWNER,
                    "battlefield_owner": EVENT_SUBJECT_OWNER,
                },
            ),
        )
    # "Return to your hand all enchantments you both own and control" (Remove
    # Enchantments). A *sweep* bounce: not one chosen object but every
    # permanent a noun phrase names, which is the bounce path below with the
    # picker taken out — same destination, same CR 400.3 owner's hand, same
    # question about whether the narrowing can be tested.
    #
    # Held to the two gates the targeted bounce is held to, and for the reason
    # a sweep makes louder: a narrowing dropped from a pick returns the wrong
    # permanent, and a narrowing dropped from a sweep returns the table.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
        and node.to.name == "hand"
        and node.from_zone is None
        and not subject.filter.is_card
        and subject.filter.zone == "battlefield"
    ):
        if node.entering_tapped or node.under_control_of or node.repetitions:
            raise LoweringError("the sweep bounce reads no rider", node=node)
        filt = subject.filter
        attached_referent: str | None = None
        # "…all white Auras you own **attached to it**" (Word of Undoing). A
        # relation rather than a characteristic, so it rides beside the filter
        # the way the sweep *destroy* already carries it (Turn to Slag) — and
        # it is honoured here rather than left in the unread set, because a
        # dropped attachment relation on a sweep returns every white Aura on
        # the board rather than the ones on the creature.
        unread = _restrictions_beyond(
            filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {
                "attached_to", "attached_to_target",
            }
        )
        if unread:
            raise LoweringError(
                "the sweep bounce cannot read " + ", ".join(sorted(unread)), node=node
            )
        swept = _filter_payload(filt)
        untestable = untestable_filter_keys(swept)
        if untestable:
            raise LoweringError(
                "the sweep bounce cannot test " + ", ".join(sorted(untestable)),
                node=node,
            )
        if filt.attached_to is not None:
            # Added **after** the testability check, because it is not a key
            # ``subject_matches`` answers: no read of the Aura alone can say
            # what it is attached to, so the handler resolves the referent and
            # compares hosts by identity — the same split ``exclude_self``
            # makes, and the same one the sweep destroy already makes for this
            # very key.
            #
            # Only the referent the resolution can name. "source" is a
            # permanent's own attachments (Rabid Wombat's count clause);
            # `rebinding` points the pronoun at the sentence's target where one
            # was chosen, so what arrives here is "target" — and anything else
            # refuses rather than sweeping the board.
            if filt.attached_to != "target":
                raise LoweringError(
                    "the sweep bounce resolves an attachment to the spell's "
                    f"target, not to the {filt.attached_to}", node=node,
                )
            attached_referent = filt.attached_to
        host_target: dict[str, object] | None = None
        if filt.attached_to_target is not None:
            # "Return all Auras attached to **target permanent you own** to
            # their owners' hands." (Scarab of the Unseen.) The same relation
            # the referent above carries, with this spell choosing the host
            # instead of pointing at a host an earlier clause chose — so the
            # handler resolves it exactly the same way (``attached_to:
            # "target"``, compared by id) and the only extra thing this shape
            # owes is the target *description*, which is what the picker offers.
            # Without it the ability targets a permanent no picker names, and
            # the sweep would find nothing on a host nobody chose.
            if attached_referent is not None:
                raise LoweringError(
                    "the sweep bounce names one host, not a referent and a "
                    "target", node=node,
                )
            attached_referent = "target"
            host_target = {
                "quantifier": "target",
                "kind": "object",
                "filter": _filter_payload(filt.attached_to_target),
            }
        # Every permanent goes to *its owner's* hand (CR 400.3), which is what
        # the handler does whatever the card printed. "…to your hand" is
        # therefore only the same sentence when the noun phrase says you own
        # them — the distinction Obelisk of Undoing already makes for the
        # targeted bounce, and the one that matters the moment a permanent has
        # been stolen.
        owner_ref = node.to.owner
        if owner_ref is None or owner_ref.kind not in ("owner", "you"):
            raise LoweringError("the sweep bounce returns a permanent to its owner", node=node)
        if owner_ref.kind == "you" and filt.owner != "you":
            raise LoweringError(
                "\"to your hand\" is not \"to its owner's hand\" unless the "
                "phrase says you own it", node=node,
            )
        bounce_payload: dict[str, object] = {"filter": swept}
        if attached_referent is not None:
            # Beside the filter, never inside it: the handler resolves the
            # referent and compares hosts by identity, and a key inside the
            # filter would reach ``subject_matches``, which has no answer for it.
            bounce_payload["attached_to"] = attached_referent
        if host_target is not None:
            bounce_payload["targets"] = host_target
        return (OracleInstruction("return_all_matching", "", bounce_payload),)
    # "**Each player** returns all creature cards from their graveyard to the
    # battlefield." (All Hallow's Eve.) A sweep *reanimation*: every card a
    # noun phrase names, out of a graveyard and onto the battlefield, with
    # nothing chosen and nothing targeted.
    #
    # Who returns them is the whole difference between this card and a card
    # that wins the game, so the actor and the graveyard's owner are checked
    # **against each other** rather than either being read alone: "each player
    # … from their graveyard" is one claim said twice, and a pairing this
    # cannot resolve refuses instead of picking one half.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("all", "each")
        and not subject.targeted
        and subject.filter.is_card
        and subject.filter.zone == "graveyard"
        and node.to.name == "battlefield"
        and node.to.owner is None
    ):
        if (
            node.entering_tapped
            or node.under_control_of
            or node.repetitions
            or node.also_stack
        ):
            raise LoweringError("the sweep reanimation reads no rider", node=node)
        actor = node.actor.kind if node.actor is not None else None
        owner = (
            subject.filter.zone_owner.kind
            if subject.filter.zone_owner is not None
            else None
        )
        if actor == "each_player" and owner in ("owner", "each_player"):
            who = "each_player"
        elif actor is None and owner == "you":
            who = "you"
        else:
            raise LoweringError(
                "the sweep reanimation reads \"each player … their graveyard\" "
                "or an unnamed subject over your own",
                node=node,
            )
        # Through the *card* gate every other printed card phrase runs through,
        # with the zone taken off first: the zone is read above, by this
        # production, and leaving it on would make the shared gate refuse a
        # phrase it can answer. Everything else — the narrowing, the keys the
        # card matcher cannot test — is that gate's answer and not a second
        # copy of it here.
        scoped = dataclasses.replace(
            subject.filter, zone="battlefield", zone_owner=None
        )
        swept = chargeable_card_filter(scoped)
        if swept is None:
            raise LoweringError(
                "the sweep reanimation cannot read this card phrase", node=node
            )
        return (
            OracleInstruction(
                "return_all_cards_from_graveyard", "",
                {"filter": swept, "who": who},
            ),
        )
    # "{W}: Return **enchanted creature** to its owner's hand." (Sun Clasp.)
    # The Aura's own attachment, which CR 303.4b names rather than chooses — so
    # there is no target, no picker and nothing in the resolution context to
    # read. Its own instruction kind for `destroy_attached_permanent`'s reason
    # one family over: what the handler has to *find* is different from every
    # other bounce here, and a payload flag on the targeted kind would leave a
    # handler that resolves an index looking for one nobody collected.
    #
    # The card types are honoured because on this phrase they are not a
    # restriction: "enchanted creature" is the Aura's enchant clause said again
    # (CR 303.4a), and an Aura attached to something its own clause excludes has
    # already been swept away by CR 704.5m. Any *other* narrowing refuses —
    # dropping one would bounce a permanent the sentence spared.
    if (
        _is_enchanted(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
    ):
        assert isinstance(subject, ast.TargetSpec)
        if node.entering_tapped or node.under_control_of or node.repetitions:
            raise LoweringError("the attached bounce reads no rider", node=node)
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_enchanted", "card_types"})
        )
        if leftovers:
            raise LoweringError(
                f"the attached bounce does not honour {leftovers[0]!r}", node=node
            )
        return (OracleInstruction("return_attached_permanent_to_hand", "", {}),)
    # "Return **a creature you control** to its owner's hand." (Shrieking Drake,
    # Stampeding Wildebeests.) "…**two Forests** you control to their owner's
    # hand" (Bull Elephant), "…**three basic lands** you control" (Ovinomancer),
    # "…**an untapped Island** you control" (the Karoo land cycle, Waterspout
    # Djinn) — one production, the count and the noun phrase as data.
    #
    # Chosen, not targeted (CR 115.1): the sentence names a set on the
    # controller's own battlefield and the controller picks out of it, so
    # nothing is announced, nothing is re-checked at CR 608.2b, and shroud
    # cannot save a permanent from its own controller's hand. That makes it the
    # pick-then-act pair three other lowering families already emit
    # (`tapping`'s Koskun Falls price, `counters`, `destruction`): the prompt
    # records which permanents, the step behind it acts on the record.
    #
    # Narrow on purpose, and every clause below is load-bearing:
    #
    # * the quantifier is an article or a bare count — "target" is `returns`'
    #   bounce and "all" is the sweep above, and reading either here would take
    #   a picker away from a card that prints one;
    # * `controller == "you"` is what makes this a price the offered seat pays,
    #   which is the question `_action_is_takeable` puts in front of the
    #   "sacrifice it unless you return …" offer;
    # * every remaining key must be one `subject_matches` answers, or the
    #   prompt would offer permanents the printed phrase excludes — "an
    #   **untapped** Island" being exactly that.
    # "…**that player** returns a land **they control** to its owner's hand."
    # (Mana Breach.) The same sentence with the seat named by the firing event
    # rather than by the word "you": one seat says who is asked and which
    # battlefield is drawn from, exactly as `controller == "you"` does below,
    # and the only difference is where the seat comes from. Admitted only under
    # an event that actually froze one (`_EVENT_SUBJECT_PLAYERS`) — under any
    # other trigger the words name a player nobody recorded, and the prompt
    # would go to whichever seat the resolution happened to be carrying.
    #
    # The actor and the possessive are checked **against each other** for the
    # sweep reanimation's reason two branches up: "that player returns … they
    # control" is one claim said twice, and a pairing this cannot resolve
    # refuses rather than picking a half.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("a", "an")
        and not subject.targeted
        and not subject.filter.is_card
        and subject.filter.zone == "battlefield"
        and subject.filter.controller in ("you", "that_player")
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
    ):
        if (
            node.entering_tapped
            or node.under_control_of
            or node.repetitions
            or node.also_stack
            or node.attached_to is not None
        ):
            raise LoweringError("the chosen bounce reads no rider", node=node)
        chooser = "you"
        if subject.filter.controller == "that_player":
            actor = node.actor.kind if node.actor is not None else None
            if actor != "that_player":
                raise LoweringError(
                    "\"a land they control\" names the seat this sentence "
                    "already named, and no subject here names one",
                    node=node,
                )
            if event not in _EVENT_SUBJECT_PLAYERS:
                raise LoweringError(
                    f"no event named {event!r} freezes the seat 'that player' "
                    "names",
                    node=node,
                )
            chooser = EVENT_SUBJECT_PLAYER
        elif node.actor is not None and node.actor.kind != "you":
            # The "you control" reading is the controller's own price, so a
            # sentence naming somebody *else* as the one who returns it is a
            # different card. Refused rather than dropped: the prompt would go
            # to the ability's controller and the printed subject would mean
            # nothing.
            raise LoweringError(
                f"the chosen bounce is not made by {node.actor.kind!r}", node=node
            )
        # The seat clause is read *here* — it becomes the prompt's
        # ``controlled_by`` — so it is taken off the filter rather than left on
        # it, exactly as the tap price one family over does. Leaving it would
        # be the one narrowing named twice, and a phrase named twice is a
        # phrase two readers are free to disagree about.
        described = _filter_payload(
            dataclasses.replace(subject.filter, controller=None)
        )
        untestable = untestable_filter_keys(described)
        if untestable:
            raise LoweringError(
                "the chosen bounce cannot test " + ", ".join(sorted(untestable)),
                node=node,
            )
        count = int(subject.count or 1)
        return (
            OracleInstruction(
                "choose_permanents", "",
                {
                    "result_key": CHOSEN_THIS_WAY_OBJECTS,
                    "chooser": chooser,
                    # Off the *chooser's* own battlefield, which is what "you
                    # control" says — named once as the seat asked and once as
                    # the board drawn from.
                    "controlled_by": "chooser",
                    "filter": described,
                    "up_to": count,
                    # **A floor as well as a ceiling**, and this is the half
                    # "up to two Plains" never needed. The printed count here
                    # is indivisible: returning one of Bull Elephant's two
                    # Forests is not paying its price, and a prompt that
                    # accepted one would let the Elephant stay for half of what
                    # it costs. CR 601.2h asks what a player is *able* to do,
                    # and a partial answer is not one of them.
                    "at_least": count,
                    "prompt": (
                        "Choose a permanent to return to its owner's hand."
                        if count == 1 else
                        f"Choose {count} permanents to return to their "
                        "owners' hands."
                    ),
                },
            ),
            OracleInstruction(
                "return_recorded_permanents_to_hand", "",
                {"permanents_from": CHOSEN_THIS_WAY_OBJECTS},
            ),
        )
