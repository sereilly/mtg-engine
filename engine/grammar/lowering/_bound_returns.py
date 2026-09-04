"""The **floor** of the return family: a return whose object nothing targets.

Split off `returns.py` at the line that file already drew. A sentence names the
object it returns in one of three ways and only one of them is a target: the
firing event recorded it ("return **that card**"), it is the ability's own
source ("return **this card**"), or it is a description the handler sweeps
("return **all** Auras attached to..."). Everything here is one of those three;
the moment a player chooses the object, `returns` handles it.

That distinction is why the refusals in here are so narrow. An untargeted
return has no index to read, so each reading is bound to the one event whose
fire site actually records what it needs. Under any other event the pronoun
names a card nobody wrote down — the handler would find nothing, and the card
would compile supported and do nothing, which is the failure the gates below
exist to refuse rather than to perform.

A floor rather than a second family, because `returns` is its only reader and a
family may not import a sibling; `_sweeps` sits beside `_common` on the same
footing. The two predicates at the top are here for the same reason: both
halves of the split ask them.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import untestable_filter_keys
from .. import ast
from ..errors import LoweringError
from ._events import (BOUND_CARD_EVENTS,
                      CHOSEN_PERMANENT as _ATTACH_HOST_KEY, EVENT_SUBJECT_OWNER,
                      _EVENT_SUBJECT_OWNERS)
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    chargeable_card_filter,
    _filter_payload,
    _is_source,
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
    if len(filt.card_types) > 1:
        return {
            "any_card": False,
            "card_type": None,
            "card_types": list(filt.card_types),
            **subtypes,
        }
    card_type = filt.card_types[0] if filt.card_types else None
    return {"any_card": card_type is None, "card_type": card_type, **subtypes}


def _returns_itself_to_the_battlefield(node: "ast.ReturnToZone", subject) -> bool:
    """Whether "return **it** to the battlefield under <seat>'s control" names
    the ability's *own* card rather than the firing event's object.

    "When this creature dies, return it to the battlefield under its owner's
    control …" (Ivory Gargoyle). ``parse_recipient`` reads a bare "it" as the
    ability's source, and on a self-dies trigger that is exactly what it means —
    but the bound-object branch below claims every "it" first and then refuses,
    because a self-dies event records no card. So the shape is recognised here
    and falls through to the self-return branch further down, which is the one
    that can read it.

    Narrow on purpose. Storm Cauldron's bound "return it" goes to a *hand* and
    Puppet Master's names a card, so neither is reachable; and the controller
    phrase is required because the self-return branch demands one anyway
    (CR 110.2's default is the ability's controller, and a sentence that does
    not say which seat is one this engine will not guess for).
    """
    return (
        subject.quantifier == "it"
        and subject.filter.is_source
        and node.from_zone is None
        and node.to.name == "battlefield"
        and node.to.owner is None
        and node.under_control_of is not None
    )


def lower_untargeted_return(
    node: ast.ReturnToZone,
    subject,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...] | None:
    """The readings that need no target, in printed-specificity order.

    Answers ``None`` only when the sentence names an object a player chooses,
    which is `returns`' half. A `LoweringError` raised in here is final: it
    means the shape *is* one of these readings and the engine has no handler
    for this variant of it.
    """
    # "Return **that card** to its owner's hand." (Puppet Master.) The bound
    # object: the card of the creature whose death fired the trigger, which by
    # resolution is in a graveyard. Nothing is chosen and nothing is targeted —
    # the event named the object — so the handler reads it out of the trigger's
    # context rather than off a target index.
    #
    # Bound to `attached_creature_dies` because that is the only event in the
    # pool whose fire site records the dead card. Under any other event "that
    # card" names a card nobody recorded, and the honest answer is a refusal:
    # the handler would otherwise find nothing and the card would compile
    # supported and do nothing, which is the whole failure this gate exists for.
    if (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("that", "it")
        and (subject.filter.is_card or subject.quantifier == "it")
        and not _returns_itself_to_the_battlefield(node, subject)
    ):
        # "Whenever a land is tapped for mana, **return it** to its owner's
        # hand." (Storm Cauldron.) The pronoun names a *permanent* — the land
        # still on the battlefield, not a card in a graveyard — so it is its own
        # instruction kind rather than a variant of the bound-card return below:
        # what the two do with what they find could not be more different, one
        # moving a card between hidden zones and one taking a permanent off the
        # battlefield.
        #
        # Admitted under ``land_tapped_for_mana`` alone, for the reason the
        # bound-card set exists: that is the one event whose fire site is
        # holding the permanent when it executes the instruction
        # (``mixins/turn_management.tap_land_for_mana``, inline as CR 605.4a
        # requires of its triggered-mana siblings). Under any other condition
        # the word "it" names a permanent nobody recorded.
        if event == "land_tapped_for_mana":
            if node.to.name != "hand" or node.to.owner is None:
                raise LoweringError(
                    "the tapped land returns to a hand alone", node=node
                )
            if node.to.owner.kind != "owner":
                raise LoweringError(
                    f"no tapped-land return reaches {node.to.owner.kind!r}'s hand",
                    node=node,
                )
            # "Return **it**" re-states the set the trigger already narrowed
            # (the condition's own "a land"), so the filter is not a further
            # restriction to honour — but any *other* field is, and a field
            # dropped here is a bounce wider than the card prints.
            leftovers = _restrictions_beyond(
                subject.filter, frozenset({"is_card", "zone", "card_types", "controller"})
            )
            if leftovers:
                raise LoweringError(
                    f"no tapped-land return honours {sorted(leftovers)}", node=node
                )
            return (OracleInstruction("return_tapped_land_to_hand", "", {}),)
        # Which events record the object the pronoun names. Both fire sites
        # stamp ``dead_card``; under anything else the words name a card nobody
        # wrote down, and the honest answer is a refusal — the handler would
        # find nothing and the card would compile supported and do nothing.
        if event not in BOUND_CARD_EVENTS:
            raise LoweringError(
                "'that card' names the firing event's object, and this event "
                "records none",
                node=node,
            )
        # "When enchanted creature dies, **return that card to the battlefield
        # under your control**." (False Demise.) The same move Seraph and
        # Krovikan Vampire print as "put that card onto the battlefield under
        # your control", and CR 400.1 knows only the zone change — "return to"
        # and "put onto" are one event, so they lower to the one instruction
        # rather than to a second handler doing the same move from the same
        # record.
        #
        # The verb is what sends the two spellings down different lowering
        # families (``zones`` reads "put onto"), which is why this is the
        # branch and not a row of a word table: the destination is the whole
        # difference, and it is read here.
        if node.to.name == "battlefield":
            if node.under_control_of is None or node.under_control_of.kind != "you":
                # The handler puts it under the *ability controller's* control
                # and says so. Any other seat would be a card the engine hands
                # to the wrong player, silently.
                raise LoweringError(
                    "the bound-card reanimation only puts it under your control",
                    node=node,
                )
            unread = [
                name for name in (
                    "entering_tapped", "exile_on_leave", "also_stack",
                    "attached_to", "actor", "repetitions",
                    "losing_subtypes", "losing_abilities", "gaining_abilities",
                )
                if getattr(node, name, None)
            ]
            if unread or node.from_zone is not None:
                # ``reanimate_bound_card`` reads none of these. A rider lowered
                # into a payload the handler ignores is a card that reports
                # supported and comes back without the half the sentence spent
                # its words on.
                raise LoweringError(
                    "the bound-card reanimation honours no further rider",
                    node=node,
                )
            if _restrictions_beyond(subject.filter, frozenset({"is_card", "zone"})):
                raise LoweringError(
                    "the bound-card reanimation honours no further narrowing",
                    node=node,
                )
            return (OracleInstruction("reanimate_bound_card", "", {}),)
        if node.to.name != "hand" or node.to.owner is None:
            raise LoweringError(
                "the bound card returns to a hand alone", node=node
            )
        # "…to **its owner's** hand" (Puppet Master) and "…to **your** hand"
        # (Enduring Renewal) are two seats, and the handler is told which.
        # Reading them as one would put an opponent's dead creature into the
        # wrong player's hand the moment a card printed the other word.
        if node.to.owner.kind not in ("owner", "you"):
            raise LoweringError(
                f"no bound-card return reaches {node.to.owner.kind!r}'s hand",
                node=node,
            )
        honoured = frozenset({"is_card", "zone"})
        if subject.quantifier == "it":
            # "Return **it**" carries the event's own subject filter, which the
            # pronoun reader copied off the condition — it re-states the set the
            # trigger already narrowed rather than narrowing this step further,
            # so it is not a restriction to honour. Every *other* field still
            # refuses below.
            honoured = honoured | {"card_types", "controller"}
        leftovers = _restrictions_beyond(subject.filter, honoured)
        if leftovers:
            raise LoweringError(
                f"the bound-card return does not honour {leftovers[0]!r}", node=node
            )
        payload: dict[str, object] = {}
        if node.to.owner.kind == "you":
            payload["to_seat"] = "controller"
        return (
            OracleInstruction("return_bound_card_to_owners_hand", "", payload),
        )
    # "Return **this card** to **your** hand." (Death Spark, Krovikan Horror.)
    #
    # The ability's own source with no printed source zone, like the two
    # readings below and above it, and told from them by whose hand is named.
    # Puppet Master's "its owner's hand" reaches whichever zone the Aura is
    # actually in, because an Aura can still be on the battlefield when its
    # trigger resolves; these two cards can only ever be in a graveyard, because
    # the ability functions nowhere else — the intervening-if in front of it
    # ("if this card is in your graveyard …") is CR 113.6b's statement of that,
    # and ``lower.py`` stamps ``functions_from`` from it onto whatever this
    # lowers to.
    #
    # So the *seat* is the difference that matters and the reason this is
    # ``return_self_from_graveyard`` rather than the owner's-hand kind beside
    # it: CR 108.4a gives a card in a graveyard no controller, so "your" is its
    # owner's seat — the seat the graveyard scan enqueued the trigger under —
    # which is exactly the seat that handler searches. The owner's-hand handler
    # searches *every* graveyard and would return an opponent's copy of the same
    # shared ``CardDefinition``, which is the look-alike bug this codebase keeps
    # finding, in a list of cards instead of on a battlefield.
    #
    # ``functions_from`` is deliberately **not** stamped here: this sentence
    # names no zone, and inventing one would let a card printing it with no
    # graveyard condition be scanned for in a zone it never mentioned.
    if (
        _is_source(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
        and not node.entering_tapped
    ):
        assert isinstance(subject, ast.TargetSpec)
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_source", "card_types"})
        )
        if leftovers:
            raise LoweringError(
                f"the self-return does not honour {leftovers[0]!r}", node=node
            )
        return (
            OracleInstruction("return_self_from_graveyard", "", {"to": "hand"}),
        )
    # "Return **this card** to its owner's hand." (Puppet Master's rider.) The
    # ability's own source, and by the time this resolves the Aura is in its
    # owner's graveyard — CR 704.5m put it there the moment the creature it
    # enchanted left. So the sentence prints no source zone and the handler
    # looks in the graveyard, which is the one place a returning Aura can be.
    if (
        _is_source(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
    ):
        assert isinstance(subject, ast.TargetSpec)
        # ``card_types`` is honoured because on a **self-reference** it is not a
        # restriction: "this creature", "this enchantment" and "this permanent"
        # all name the object the ability is printed on (CR 109.5), and the noun
        # is the word the card happens to call itself by. Nothing is being
        # selected, so there is no set for the type to narrow — which is why the
        # engine's own self-reference collapser treats the three as one phrase.
        #
        # Refusing it cost four Ice Age cards a printed ability apiece (Blinking
        # Spirit, Foul Familiar, Leshrac's Sigil, Freyalise's Charm), each of
        # them "{cost}: Return this <noun> to its owner's hand."
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_source", "card_types"})
        )
        if leftovers:
            raise LoweringError(
                f"the self-return does not honour {leftovers[0]!r}", node=node
            )
        return (OracleInstruction("return_source_card_to_owners_hand", "", {}),)
    # "Return **this card** from your graveyard to the battlefield [tapped]."
    # (Silversmote Ghoul; CR 113.6m's own example is Reassembling Skeleton.)
    # Nothing is chosen — the ability names the object it is printed on — so this
    # is not a targeted return and never reaches `_is_target` below.
    #
    # `functions_from` is the load-bearing key and it is *derived*, not declared:
    # CR 113.6m says an ability whose effect moves the object it is on out of a
    # zone functions only in that zone, so the zone the sentence names as the
    # source is the zone the ability works from. The scan in engine/events.py
    # reads that key rather than a list of instruction kinds, for the reason
    # end_step.py's intervening-if gate is keyed on a payload shape: a list is
    # only ever as complete as the last card that touched it.
    if _is_source(subject) and node.from_zone is not None and node.from_zone.name == "graveyard":
        assert isinstance(subject, ast.TargetSpec)
        if node.from_zone.owner is None or node.from_zone.owner.kind != "you":
            raise LoweringError(
                "a card returns itself from its owner's graveyard", node=node
            )
        # Two destinations, one instruction: the battlefield (Silversmote Ghoul)
        # and the card's own controller's hand (Whiteout). Where it lands is
        # payload rather than a second kind, because everything else about the
        # sentence — the object is the ability's own source, the zone it comes
        # out of is the one the ability functions from (CR 113.6m) — is the
        # same fact in both.
        to_hand = (
            node.to.name == "hand"
            and node.to.owner is not None
            and node.to.owner.kind == "you"
        )
        if not to_hand and (node.to.name != "battlefield" or node.to.owner is not None):
            raise LoweringError(
                f"no handler returns a card from the graveyard to the {node.to.name}",
                node=node,
            )
        if to_hand and node.entering_tapped:
            # "tapped" describes a permanent, and a card in a hand is not one.
            raise LoweringError(
                "a card returned to a hand cannot enter tapped", node=node
            )
        # Every ObjectFilter field beyond the three the phrase "this card from
        # your graveyard" sets. Written against the dataclass, so a restriction
        # added later refuses rather than being silently dropped.
        leftovers = _restrictions_beyond(
            subject.filter, frozenset({"is_source", "zone", "zone_owner"})
        )
        if leftovers:
            raise LoweringError(
                f"the self-return handler does not honour {leftovers[0]!r}", node=node
            )
        payload: dict[str, object] = {
            "tapped": node.entering_tapped, "functions_from": "graveyard",
        }
        if node.entering_counters:
            # "…**with a +1/+1 counter on it**" (Sand Golem). CR 121.2 puts the
            # counters on as part of the move, so they ride this instruction
            # rather than becoming a second one: the permanent does not exist
            # until this handler runs, and a placement behind it would have
            # nothing to name.
            #
            # Refused for a hand, where the exile's own reader would have let
            # them through: a card in a hand is not a permanent and carries no
            # counters (CR 122.1), so admitting the phrase would consume words
            # that then do nothing.
            if to_hand:
                raise LoweringError(
                    "a card returned to a hand carries no counters", node=node
                )
            payload["counters"] = {
                kind: count for kind, count in node.entering_counters
            }
        if to_hand:
            # Emitted only for the newer reading, so the battlefield spelling's
            # payload stays byte-identical and no behaviour signature moves.
            payload["to"] = "hand"
        return (OracleInstruction("return_self_from_graveyard", "", payload),)
    # "Return this card to the battlefield under your control attached to that
    # creature." / "…as a non-Aura enchantment. It loses "enchant creature" and
    # gains "…"." (Takklemaggot.)
    #
    # The ability's own source with **no printed source zone**, which is the
    # same reading ``return_source_card_to_owners_hand`` above takes and for the
    # same reason: by the time this resolves the Aura is wherever the CR 704.5m
    # sweep left it, and a sentence that names no zone reaches it there
    # (CR 400.7 makes what comes back a new object either way).
    #
    # Every rider the sentence prints is payload on one instruction rather than
    # a step of its own, because none of them can name what they act on: the
    # permanent is created by this very move, so no earlier reference reaches
    # it and no later step could be told which object to look at.
    if (
        _is_source(subject)
        and node.from_zone is None
        and node.to.name == "battlefield"
        and node.to.owner is None
    ):
        assert isinstance(subject, ast.TargetSpec)
        leftovers = _restrictions_beyond(subject.filter, frozenset({"is_source"}))
        if leftovers:
            raise LoweringError(
                f"the self-return does not honour {leftovers[0]!r}", node=node
            )
        # Two seats the sentence may name, and it must name one: CR 110.2's
        # default is the ability's controller, so a phrase consumed into nothing
        # is a permanent whose controller the card stated and the engine
        # guessed. "Its owner" (Ivory Gargoyle) is not the same seat as "you"
        # for a creature that changed hands before it died.
        control = getattr(node.under_control_of, "kind", None)
        if control not in ("you", "owner"):
            raise LoweringError(
                "this card returns to the battlefield under its own "
                "controller's or its owner's control", node=node,
            )
        if node.repetitions is not None or node.entering_tapped:
            raise LoweringError(
                "the self-return to the battlefield reads no repetition or "
                "tapped rider", node=node,
            )
        payload: dict[str, object] = {"control": control}
        if node.attached_to is not None:
            # "attached to **that creature**" — the one an earlier step chose.
            # Refused when nothing did: an Aura told to enter attached to a
            # permanent nobody picked would enter attached to nothing and be
            # swept away by CR 704.5m, which is a card that reports supported
            # and does the opposite of what it says.
            if _ATTACH_HOST_KEY not in produced:
                raise LoweringError(
                    "\"attached to that creature\" names a permanent no "
                    "earlier step of this sentence chose", node=node,
                )
            payload["attached_to"] = _ATTACH_HOST_KEY
        if node.losing_subtypes:
            payload["losing_subtypes"] = tuple(node.losing_subtypes)
        if node.losing_abilities:
            payload["losing_abilities"] = tuple(node.losing_abilities)
        if node.gaining_abilities:
            from ...granted_abilities import (bind_chosen_player,
                                              granted_ability_supported)

            granted = []
            for text in node.gaining_abilities:
                # "…gains "At the beginning of **that player's** upkeep, …"".
                # The pronoun names the seat an earlier step of this same
                # sentence asked to choose, and only a sentence that made such a
                # choice can bind it — so the rewrite is gated on the record
                # rather than applied to any quote printing the words.
                bound = (
                    bind_chosen_player(text)
                    if _ATTACH_HOST_KEY in produced else text
                )
                if not granted_ability_supported(bound):
                    raise LoweringError(
                        f"the engine cannot read the granted ability {text!r}",
                        node=node,
                    )
                granted.append(bound)
            payload["gaining_abilities"] = tuple(granted)
        return (
            OracleInstruction("return_source_card_to_battlefield", "", payload),
        )
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
        if _reads_no_return_restriction(subject.filter):
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
