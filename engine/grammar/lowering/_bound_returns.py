"""A return whose object the sentence names by **reference**.

Split off `returns.py` at the line that file already drew: a return whose
object nothing targets, against one a player chooses (CR 115). Split again at
Exodus' Phase 0, when the readings underneath it had reached 989 lines with two
of the wave's groups due to land here — this half keeps the readings that
*name* their object, and `_described_returns` took the ones that describe it.

There are two references and the module is named for both. The firing event
recorded the object ("return **that card**", "return **it**"), or it is the
ability's own source ("return **this card**"). Either way the object was fixed
before this sentence ran, so nothing is matched and nothing is picked: the only
question left is where that object is *now*, and the answer is a seat, a zone
and a rider — never a filter. Which is why every narrowing check below is a
**refusal** rather than a payload. The noun phrase restates the reference (CR
109.5: "this creature" is the word the card happens to call itself by), and an
adjective beyond the restatement is one no handler here reads. Not one branch
in this file carries a filter to a handler; every branch in the other file
does.

That distinction is also why these refusals are so narrow. An untargeted return
has no index to read, so each *event*-bound reading is bound to the one event
whose fire site actually records what it needs. Under any other event the
pronoun names a card nobody wrote down — the handler would find nothing, and
the card would compile supported and do nothing, which is the failure the gates
below exist to refuse rather than to perform.

A floor rather than a second family, because `returns` is its only reader and a
family may not import a sibling; `_sweeps` sits beside `_common` on the same
footing. It reads `_described_returns`, and nothing reads back: the last thing
:func:`lower_untargeted_return` does is hand the sentence down to the described
half, so one call still covers every untargeted reading in printed-specificity
order and `returns`' call site did not move.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._deaths import BOUND_CARD_EVENTS
from ._delays import _BOUND_OBJECT_DELAYED_EVENTS
from ._described_returns import lower_described_return
from ._events import CHOSEN_PERMANENT as _ATTACH_HOST_KEY
from ._common import (
    _is_attached_host_pronoun,
    _is_source,
    _restrictions_beyond,
    _source_return_reach,
)



def _returns_its_own_source(node: "ast.ReturnToZone", subject) -> bool:
    """Whether "return **it**" names the ability's *own* card rather than the
    firing event's object.

    ``parse_recipient`` reads a bare "it" as the ability's source, and under a
    trigger whose own subject *is* that source ("When **this Aura** is put into
    a graveyard from the battlefield, ...") that is exactly what it means. The
    bound-object branch below claims every "it" first, though, so the shape has
    to be recognised in front of it and fall through to the self-return branches
    further down, which are the ones that can read it.

    Two readings, one per branch below that takes this pronoun, each spelled out
    rather than collapsed into a bare ``is_source`` test so that a *third*
    spelling refuses loudly instead of arriving at whichever branch happens to
    claim it:

    * "When this creature dies, return it to the battlefield under its owner's
      control ..." (Ivory Gargoyle), which
      :func:`return_source_card_to_battlefield` performs. The controller phrase
      is required because that branch demands one anyway (CR 110.2's default is
      the ability's controller, and a sentence that does not say which seat is
      one this engine will not guess for).
    * "When this Aura is put into a graveyard from the battlefield, return it to
      **its owner's** hand." (Brilliant Halo and its five Urza's Saga
      siblings), which :func:`return_source_card_to_owners_hand` performs --
      reaching whichever zone the card is actually in, the graveyard CR 704.5m
      left it in or the battlefield when nothing has swept yet.

    The bound-card branch is not merely unable to read the second; it would read
    it **wrongly**, which is why this is a fall-through and not a widening of
    that branch's honoured set. ``permanent_dies`` is in ``BOUND_CARD_EVENTS``
    and its fire site does stamp ``dead_card``, so admitting ``is_source`` there
    compiles a card that appears to work -- right up to a resolution where the
    Aura is still on the battlefield, which the graveyard-only handler cannot
    see and cannot remove. The two branches are told apart by which object the
    sentence names, and this one names the source.

    Narrow on purpose in the other direction too. Storm Cauldron's bound "return
    it" goes to a hand and Puppet Master's names a card, so neither is
    reachable; and "...to **your** hand" is deliberately absent, because that
    spelling lowers to ``return_self_from_graveyard``, which searches one seat's
    graveyard alone -- a different reading, which no card in the pool prints
    under a self-event.
    """
    if subject.quantifier != "it" or not subject.filter.is_source:
        return False
    if node.from_zone is not None:
        return False
    if (
        node.to.name == "battlefield"
        and node.to.owner is None
        and node.under_control_of is not None
    ):
        return True
    return (
        node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
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

    The referencing readings are here and the describing ones are one module
    over, and the tail call at the bottom is what keeps that a *file* boundary
    rather than a change of contract: one call, one order, one answer.
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
        and not _returns_its_own_source(node, subject)
        # An *attached* trigger's "it" names the Aura's host, not a card this
        # event recorded, so it falls past to the two readings that find it.
        and not _is_attached_host_pronoun(subject)
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
            # Which seat the card comes back under, in the same
            # ``control``/``you``/``owner`` vocabulary the self-return one
            # screen down already uses — one spelling of one fact, so a fire
            # site or a handler taught about it reaches both readings.
            #
            # **An unspoken seat is not an unknown seat.** CR 110.2a makes the
            # controller of the spell or ability the default, so "return that
            # card to the battlefield" (Angelic Renewal) and "…under your
            # control" (False Demise) name the same player, and refusing the
            # first was refusing a card for saying nothing.
            #
            # "…under **its owner's** control" (Abduction) is the seat that
            # really differs, and it differs exactly when the printed line
            # matters: an Aura that stole the creature and then watched it die
            # gives it *back*, so reading the phrase as "you" would hand the
            # thief a permanent the card returns to its owner. CR 400.3 —
            # control moves, ownership never did.
            control = getattr(node.under_control_of, "kind", None) or "you"
            if control not in ("you", "owner"):
                raise LoweringError(
                    "the bound-card reanimation only puts it under your or "
                    "its owner's control",
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
            # The default seat rides no key, so every card already compiling
            # this instruction keeps the payload it had — the differential over
            # the pool is the check that says so.
            payload = {"control": "owner"} if control == "owner" else {}
            return (OracleInstruction("reanimate_bound_card", "", payload),)
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
    # "Whenever this creature blocks a creature, return **that creature** to
    # its owner's hand at end of combat." (Wall of Tears.) The bound
    # **permanent**, which is a different object from the bound *card* above
    # and needs a different handler: this one is still on a battlefield when
    # the delayed ability fires, so what happens is CR 400.7's zone change off
    # the board rather than a search through graveyards.
    #
    # Told apart from that reading by ``is_card`` alone, which is the noun
    # phrase the trigger's own condition wrote — "that creature" under a block
    # or a damage trigger is a permanent, and "that card" under a dies trigger
    # is not.
    #
    # Admitted only under a delayed event that names an object (CR 603.7c), the
    # same gate ``destroy_bound_permanent`` is held to one family over: under
    # any other event the words name a permanent nobody recorded, and the
    # handler would bounce nothing while the card compiled supported.
    #
    # "When enchanted creature attacks, return **it** … at end of combat."
    # (Contempt.) The pronoun spelling, here and not with the attachment branch
    # below for this branch's own reason: CR 603.7c is about the object as it
    # was when the ability was created, so an Aura destroyed in between still
    # returns the creature, where reading the attachment would find no host.
    if (
        isinstance(subject, ast.TargetSpec)
        and (
            (subject.quantifier == "that" and not subject.filter.is_card)
            or _is_attached_host_pronoun(subject)
        )
        and event in _BOUND_OBJECT_DELAYED_EVENTS
    ):
        if (
            node.to.name != "hand"
            or node.to.owner is None
            or node.to.owner.kind != "owner"
        ):
            raise LoweringError(
                "the bound permanent goes to its owner's hand alone", node=node
            )
        unread = [
            name for name in (
                "entering_tapped", "entering_counters", "exile_on_leave",
                "under_control_of", "repetitions", "actor", "attached_to",
                "losing_subtypes", "losing_abilities", "gaining_abilities",
                "also_stack",
            )
            if getattr(node, name, None)
        ]
        if unread or node.from_zone is not None:
            # A rider lowered into a payload the handler ignores is a card that
            # reports supported and does half of what it prints.
            raise LoweringError(
                "the bound-permanent bounce honours no further rider", node=node
            )
        # The noun restates what the trigger's own condition already required,
        # so the card type is not a narrowing to honour; every other field is.
        # ``is_enchanted`` is that restatement one word shorter.
        if _restrictions_beyond(
            subject.filter, frozenset({"card_types", "is_enchanted"})
        ):
            raise LoweringError(
                "the bound-permanent bounce honours no further narrowing",
                node=node,
            )
        return (OracleInstruction("return_bound_permanent_to_hand", "", {}),)
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
        payload = _source_return_reach(event)
        return (
            OracleInstruction("return_source_card_to_owners_hand", "", payload),
        )
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
    # Everything past here names its object by describing it — a set swept
    # whole, or a set the controller picks out of — which is
    # `_described_returns`' question and not this one. Handed down rather than
    # returned to `returns`, so the printed-specificity order stays one list in
    # one place and the caller keeps one call.
    return lower_described_return(node, subject, event)
