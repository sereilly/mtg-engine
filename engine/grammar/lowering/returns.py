"""Lowering a **return** — "Return <object> [from <zone>] to <zone>" (CR 400).

Split out of `lowering/zones.py` when that file crossed 1,000 lines, along the
boundary the file already had: one function was 618 of its 1,004 lines, and it
answers a question the rest does not. The rest of `zones` decides where an
object *goes* when something puts it there — onto the battlefield, on top of a
library, into an exile, shuffled away. A return also names where it comes
**from**, and the pair of zones is what picks the handler: graveyard→hand,
graveyard→battlefield and battlefield→owner's hand are three unrelated handlers
reading three different kinds of index. Every refusal in here is about a pair
this engine has no handler for.

Sits beside `zones` in the layer order and imports from it, never the other way.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from ...subject_filters import (TESTABLE_SUBJECT_FILTER_KEYS,
                                untestable_filter_keys)
from .. import ast
from ..errors import LoweringError
from ._events import (BOUND_CARD_EVENTS,
                      CHOSEN_PERMANENT as _ATTACH_HOST_KEY, EVENT_SUBJECT_OWNER,
                      _EVENT_SUBJECT_OWNERS, _back_reference_payload)
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS,
    chargeable_card_filter,
    _describe_targets,
    _filter_payload,
    _is_source,
    _is_target,
    _restrictions_beyond,
    _describe_several_card_targets,
    _describe_several_targets,
    _names_several_targets,
)


# The filter both exile shapes are compared against. Two readers, one
# definition — an equality check written twice is two chances to widen one
# of them.
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


def _lower_reanimate_enchanted_card(
    node: ast.ReanimateEnchantedCard,
) -> tuple[OracleInstruction, ...]:
    """The reanimation Aura's entry line (Animate Dead, Dance of the Dead).

    The same instruction the ordinary graveyard-to-battlefield return lowers to,
    because it is the same move — what differs is who chose the card (the Aura's
    own enchant clause, at cast time) and what happens around it, and both of
    those are ``_apply_aura_effect``'s to perform off the Aura's text.

    So this lowering carries no payload. The printed "tapped" is on the node
    because the node describes the sentence, but the *reader* of that word is
    ``engine/auras.AURA_REANIMATION_TAPPED``, asked once at the fire site — a
    payload copy here would be a second answer to which printing this is, and
    the gate in `engine/auras.py` reads the first.
    """
    return (OracleInstruction("reanimate_creature", "", {}),)


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
    if len(filt.card_types) > 1:
        return {
            "any_card": False,
            "card_type": None,
            "card_types": list(filt.card_types),
        }
    card_type = filt.card_types[0] if filt.card_types else None
    return {"any_card": card_type is None, "card_type": card_type}


def _record_optional_card_target(
    payload: dict[str, object], subject: ast.TargetSpec
) -> None:
    """Record that this graveyard target was printed "**up to** one".

    "Target" and "up to one target" resolve one chosen card either way, so the
    handler, the picker and the narrowing are identical and the payload was the
    same for both — the quantifier was simply dropped. What cannot read it off
    the printed line is the gate that asks whether an ability may be activated
    at all: CR 601.2c lets an "up to" announcement name *no* target, so Liliana,
    Death Mage's "+1: Return **up to one** target creature card from your
    graveyard to your hand" is legal with an empty graveyard and Adun
    Oakenshield's bare "target" is not.

    Recorded only for the "up to" spelling, so every card printing the bare word
    keeps emitting its payload byte for byte. ``count`` is 1 here, which is
    below the several-targets threshold every other reader tests
    (``targets["count"] > 1``), so nothing that walks for a list of targets sees
    a new one.
    """
    if subject.quantifier == "up_to":
        payload["targets"] = {
            "quantifier": "up_to",
            "kind": "card",
            "count": subject.count,
        }


def _lower_put_source_into_zone(node) -> tuple[OracleInstruction, ...]:
    """``Put it into your graveyard.`` (All Hallow's Eve.)

    The zone stays payload — the handler switches on it — but only the
    destination that has a handler is admitted here. A "put it into your hand"
    lowered to the same kind would be a card reporting itself supported and
    then doing whatever the graveyard branch does, which is the silent failure
    this grammar refuses by construction.

    "your graveyard" and "its owner's graveyard" are one destination for a card
    the ability's controller owns, and CR 400.3 sends a card to its owner's
    graveyard whatever the effect printed — so both spellings are admitted and
    the handler does the owner lookup. A named third player's graveyard is a
    different sentence and refuses.
    """
    zone = node.zone
    if zone.name != "graveyard":
        raise LoweringError(
            f"no handler puts a source into a {zone.name}", node=node
        )
    if zone.owner is not None and zone.owner.kind not in ("you", "owner"):
        raise LoweringError(
            "the source goes to its owner's graveyard, not a named player's",
            node=node,
        )
    return (OracleInstruction("put_self_into_zone", "", {"zone": "graveyard"}),)


def _lower_return_to_zone(
    node: ast.ReturnToZone,
    event: str | None = None,
    produced: frozenset[str] = frozenset(),
) -> tuple[OracleInstruction, ...]:
    """"Return <object> [from <zone>] to <zone>" — Raise Dead, Regrowth,
    Resurrection and Unsummon.

    The *pair* of zones picks the handler, which is why they are both parsed
    rather than pattern-matched out of the sentence: graveyard→hand,
    graveyard→battlefield and battlefield→owner's hand are three unrelated
    handlers reading three different target indices (a graveyard position, a
    graveyard position, a battlefield position). The legacy rules told them
    apart by substring, and told Raise Dead from Regrowth by probing for
    ``"creature card" not in text`` — which is why "return target artifact card
    from your graveyard to your hand" would have returned a creature.

    Nothing here is described for engine/targeting.py. The `targets` vocabulary
    names battlefield permanents, so describing a graveyard card with it would
    tell the picker to offer creatures in play for a reanimation spell — the
    exact bug the Animate Dead targeting test pins.
    """
    # "Return target spell or creature to its owner's hand." (Unsubstantiate):
    # a spell on the stack goes back to its owner's hand (CR 608.2b never
    # applies — the spell is the target, not a resolver of it), a creature is
    # the ordinary bounce. One instruction; the handler branches on which kind
    # of object was chosen.
    if node.also_stack:
        return (OracleInstruction("return_spell_or_creature_to_hand", "", {}),)
    subject = node.subject
    if node.repetitions is not None:
        # "Return a card from your graveyard to your hand **for each card
        # discarded this way**." (Recall.) A count nobody knows until an earlier
        # step of this resolution has been answered, so the cards cannot be
        # chosen as targets when the spell is cast (CR 601.2c) — they are picked
        # while it resolves, out of the chooser's own graveyard, which is a
        # public zone with nothing for targeting to protect.
        #
        # Admitted in exactly the shape the handler performs, and refused
        # otherwise: a clause that parsed and then lowered onto the single-card
        # return would silently return one card however many were discarded.
        if not (
            isinstance(subject, ast.TargetSpec)
            and not subject.targeted
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
            raise LoweringError(
                "no repeated return handler for this shape", node=node
            )
        if _reads_no_return_restriction(subject.filter):
            raise LoweringError("no return handler honours this restriction", node=node)
        payload: dict[str, object] = dict(_graveyard_to_hand_payload(subject.filter))
        # Where the number comes from, decided in the one place that decides it
        # for every back-reference — and refused outright when no step of this
        # effect records the key, because "for each card discarded this way"
        # with no discard in front of it names nothing at all.
        payload.update(_back_reference_payload(node.repetitions, produced, event))
        return (
            OracleInstruction(
                "return_chosen_cards_from_graveyard_to_hand", "", payload
            ),
        )
    # "Return up to two target creatures to their owners' hands." (Read the
    # Tides' second mode.) Same instruction as the single-target bounce — the
    # effect per creature is identical — described with the several-targets
    # opt-in so the handler resolves a list and the picker collects up to N.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
        and not subject.filter.is_card
        and subject.filter.card_types == ("creature",)
    ):
        several: dict[str, object] = {}
        _describe_several_targets(several, subject)
        return (OracleInstruction("bounce_target_creature", "", several),)
    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The same instruction as the one-card return - the
    # effect per card is identical, and `_graveyard_to_hand_payload` is the same
    # narrowing - plus the several-targets opt-in, which is what says the handler
    # resolves a list and the picker collects up to N.
    #
    # Gated to exactly the shape that handler reads: the caster's own graveyard,
    # their own hand, and nothing `_reads_no_return_restriction` refuses for the
    # one-card path, since the several path reads the same payload keys and no
    # more. "Up to two target **black** creature cards" therefore refuses rather
    # than returning any two.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.from_zone.owner is not None
        and node.from_zone.owner.kind == "you"
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "you"
        and subject.filter.is_card
    ):
        if _reads_no_return_restriction(subject.filter):
            # Raised here rather than left to the generic refusal below, so the
            # named clause says which half is missing: the arity is fine and the
            # adjective is not.
            raise LoweringError("no return handler honours this restriction", node=node)
        several_cards = _graveyard_to_hand_payload(subject.filter)
        _describe_several_card_targets(several_cards, subject)
        return (
            OracleInstruction(
                "return_creature_from_graveyard_to_hand", "", several_cards
            ),
        )
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
        if node.under_control_of is None or node.under_control_of.kind != "you":
            raise LoweringError(
                "this card returns to the battlefield under its own "
                "controller's control", node=node,
            )
        if node.repetitions is not None or node.entering_tapped:
            raise LoweringError(
                "the self-return to the battlefield reads no repetition or "
                "tapped rider", node=node,
            )
        payload: dict[str, object] = {"control": "you"}
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
            filt, _PAYLOAD_HONOURED_FILTER_FIELDS | {"attached_to"}
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
    if not _is_target(subject):
        # "target" and "up to one target" (Liliana, Death Mage's +1) both
        # resolve one chosen object; anything wider has no handler.
        raise LoweringError("no handler for returning a non-targeted object", node=node)
    assert isinstance(subject, ast.TargetSpec)
    filt = subject.filter

    # The blanket refusal is the *graveyard* returns' gate, and only theirs:
    # each of those takes a fixed payload and reads at most a card type, so any
    # adjective beyond it would be invisible to them. The bounce path below
    # gates itself instead, against what ``subject_matches`` can test — a
    # stronger question than a hand-kept list of exceptions to this one, which
    # is what it used to be (``excluded_subtypes``, ``other_than_source``,
    # ``controller``, ``excluded_types``, stripped before asking).
    # "Return target **white or black** creature card from your graveyard to
    # the battlefield." (Dreams of the Dead.) The one adjective the reanimation
    # *does* read: it travels as ``colors`` on the payload, and the picker, the
    # activation gate and the handler all test it through the one predicate
    # (``graveyard_card_matches``). Lifted out of the blanket refusal here
    # rather than weakened inside it, so every other zone-change handler keeps
    # refusing every adjective — none of them reads one.
    gated = filt
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "battlefield"
        and filt.colors
    ):
        gated = dataclasses.replace(filt, colors=())
    if node.from_zone is not None and _reads_no_return_restriction(gated):
        raise LoweringError("no return handler honours this restriction", node=node)
    # The leave-the-battlefield rider is armed by exactly one handler (the
    # reanimation below). Every other move here would carry the word and do
    # nothing with it, and this rider is a *drawback* — dropped, the card is
    # strictly better than the one printed, which is the one direction a
    # dropped rider must never fail in.
    if node.exile_on_leave and not (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "battlefield"
    ):
        raise LoweringError(
            "only a reanimation arms the leave-the-battlefield replacement",
            node=node,
        )

    source, destination = node.from_zone, node.to

    if source is not None and source.name == "graveyard":
        # Both graveyard handlers search the caster's own graveyard and nowhere
        # else, so "from a graveyard" is a different card, not a wording of this
        # one.
        if source.owner is None or source.owner.kind != "you":
            raise LoweringError("no handler searches a graveyard but your own", node=node)
        if not filt.is_card:
            raise LoweringError("a graveyard holds cards, not permanents", node=node)

        if destination.name == "hand":
            if destination.owner is None or destination.owner.kind != "you":
                raise LoweringError("this handler returns cards to your own hand", node=node)
            to_hand = _graveyard_to_hand_payload(filt)
            _record_optional_card_target(to_hand, subject)
            return (
                OracleInstruction(
                    "return_creature_from_graveyard_to_hand", "", to_hand,
                ),
            )

        if destination.name == "battlefield":
            if destination.owner is not None:
                raise LoweringError("no handler for a reanimation under another's control", node=node)
            # `reanimate_creature` only ever puts a creature onto the
            # battlefield. Regrowth's untyped "target card" has no lowering
            # here: claiming it would silently narrow the player's choice.
            if filt.card_types != ("creature",):
                raise LoweringError("the reanimation handler only moves creature cards", node=node)
            # A printed colour narrowing rides the payload; a card with none
            # keeps emitting the empty payload byte for byte.
            payload: dict[str, object] = (
                {"colors": tuple(filt.colors)} if filt.colors else {}
            )
            # "…**If the creature would leave the battlefield, exile it instead
            # of putting it anywhere else.**" (Dreams of the Dead.) Folded onto
            # the move by the parse, because the permanent it applies to does
            # not exist until this instruction runs — the same reason the
            # keyword grant after a reanimation folds.
            if node.exile_on_leave:
                payload["exile_on_leave"] = True
            _record_optional_card_target(payload, subject)
            return (OracleInstruction("reanimate_creature", "", payload),)

        raise LoweringError(f"no handler moves a card to the {destination.name}", node=node)

    if source is None and destination.name == "hand":
        # A permanent going home. `bounce_target_creature` returns it to its
        # owner's hand by construction, so "to your hand" is a different effect
        # (it matters the moment you have stolen the creature) and refuses.
        if destination.owner is None or destination.owner.kind != "owner":
            # "…to **your** hand" is a different place from "its owner's hand"
            # — the moment you have stolen the permanent, they are two players'
            # hands — so the bounce handler, which always returns a permanent
            # to its owner, cannot carry it.
            #
            # Unless the card says you own it. "Return target permanent you
            # both own and control to your hand" (Obelisk of Undoing) narrows
            # the target to the case where the two hands are the same hand, so
            # the handler is exactly right and the refusal below would be
            # refusing on a distinction the card already made.
            owns_it = (
                isinstance(node.subject, ast.TargetSpec)
                and node.subject.filter is not None
                and node.subject.filter.owner == "you"
            )
            if not (owns_it and destination.owner is not None
                    and destination.owner.kind == "you"):
                raise LoweringError(
                    "the bounce handler returns a permanent to its owner", node=node
                )
        if filt.is_card:
            raise LoweringError("no handler bounces a card that is not in play", node=node)
        # **The printed noun is payload, not a kind.** A bounce returns whatever
        # the phrase named to its owner's hand — a creature (Unsummon), any
        # permanent (Boomerang), an Island (Flash Flood), a nonland permanent
        # (Sublime Epiphany) — and the effect per object is the same one. So
        # what the line has to clear is not "does it say creature?" but "can the
        # narrowing it *does* say be tested?", asked in the two places a filter
        # can go missing:
        #
        # * ``_filter_payload`` refuses a narrowing with no payload form at all,
        #   so it cannot be dropped between the AST and the dispatcher;
        # * ``TESTABLE_SUBJECT_FILTER_KEYS`` refuses one that has a form
        #   ``subject_matches`` cannot answer, so it cannot be dropped between
        #   the dispatcher and the permanent.
        #
        # Everything surviving both is honoured by the same ``subject_matches``
        # the picker, the cast gate and the handler's predicate each ask, which
        # is what lets a phrase nobody wrote a branch for still bounce exactly
        # what it printed. This replaced a hand-kept list of the four narrowings
        # the branch below carried, under which "target permanent" refused for
        # want of an adjective and "target artifact" refused for being the wrong
        # noun.
        # The first half, over the AST: a field ``to_payload`` does not read at
        # all leaves no key for the second half to inspect, so "target
        # **enchanted** creature" would reduce to "target creature" and bounce
        # one that was never enchanted.
        unread = _restrictions_beyond(filt, _PAYLOAD_HONOURED_FILTER_FIELDS)
        if unread:
            raise LoweringError(
                "the bounce handler cannot read " + ", ".join(sorted(unread)),
                node=node,
            )
        bounce_filter = _filter_payload(filt)
        untestable = set(bounce_filter) - TESTABLE_SUBJECT_FILTER_KEYS
        if untestable:
            raise LoweringError(
                "the bounce handler cannot test "
                + ", ".join(sorted(untestable)),
                node=node,
            )
        if bounce_filter == {"type_filter": "creature"}:
            # Unsummon's payload, byte-identical: the bare bounce carries no
            # filter because "creature" is what every reader of this kind
            # already defaults to.
            return (OracleInstruction("bounce_target_creature", "", {}),)
        payload: dict[str, object] = {"filter": bounce_filter}
        _describe_targets(payload, subject)
        return (OracleInstruction("bounce_target_creature", "", payload),)

    raise LoweringError("no handler for this zone change", node=node)
