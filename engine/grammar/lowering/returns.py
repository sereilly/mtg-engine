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
from .. import ast
from ..errors import LoweringError
from ._events import _back_reference_payload
from ._bound_returns import lower_untargeted_return
from ._described_returns import (_graveyard_to_hand_payload,
                                 _reads_no_return_restriction)
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, _describe_targets, _is_target,
    _restrictions_beyond, _describe_several_card_targets,
    _describe_several_targets, _names_several_targets, testable_filter_payload
)

#: The printed noun phrases a graveyard-to-battlefield return may name.
#: Four of CR 110.4a's six permanent card types (there is no battle and no
#: planeswalker return template in the pool), because the instruction puts the
#: card onto the battlefield and only a permanent card can be there — an
#: instant card named here would be a sentence with no legal outcome, so it
#: refuses rather
#: than lowering to a move that finds nothing.
#:
#: The empty tuple is deliberately **absent**: Regrowth's untyped "target card"
#: would be admitted by any type the handler happened to scan for, which is a
#: silent narrowing of the player's choice rather than a card.
_REANIMABLE_CARD_TYPES = frozenset({
    ("creature",), ("artifact",), ("enchantment",), ("land",),
})


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


def subject_names_another(subject) -> bool:
    """Whether this return's object was printed "**another**".

    Read off the ``TargetSpec`` rather than off its filter because that is where
    the parser puts it: ``references.parse_target_spec`` records the printed
    word as ``distinct_from_prior`` on the spec, and the filter's
    ``other_than_source`` is the *other* spelling of the same restriction ("up
    to two **other** target creatures", "target creature other than this
    creature"). Both are asked, so a sentence printing either reaches the same
    answer here.
    """
    return bool(
        isinstance(subject, ast.TargetSpec)
        and (subject.distinct_from_prior or subject.filter.other_than_source)
    )


def _honours_printed_another(node: ast.ReturnToZone) -> bool:
    """Whether this return's zone pair has a reader for the printed "another".

    Exactly one does: the *one-card* targeted graveyard-to-hand return, whose
    payload carries ``exclude_source_card`` and whose three readers — the
    picker, the CR 608.2b re-check and the handler — all resolve it through
    ``handlers/_common.excluded_graveyard_slot``. The several-card branch is
    deliberately **not** here: its handler resolves a list of slots through
    ``_resolve_graveyard_slots``, which reads a per-card predicate and has
    nowhere to put a per-slot exclusion, and no card in either manifest role
    prints the pair.
    """
    return bool(
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "hand"
        and not _names_several_targets(node.subject)
    )


def _lower_return_self_instead_of_untapping(
    node,
) -> tuple[OracleInstruction, ...]:
    """``During your next untap step, as you untap your permanents, return this
    land to its owner's hand.`` (Undiscovered Paradise.)

    One instruction with no payload, because the node has no fields: the window,
    the object and the destination are the sentence, and every one of them would
    make it a different sentence if it varied.

    What the handler does is *arm* the replacement rather than perform the
    return — the return happens a step later, inside the untap step, through
    ``engine/replacements.py``'s ``would_untap`` seam. That split is the card:
    performed now it would be an ordinary self-bounce, and the land would never
    have produced its mana at all.
    """
    return (OracleInstruction("return_self_instead_of_untapping", "", {}),)


def _lower_put_source_into_zone(
    node, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """``Put it into your graveyard.`` (All Hallow's Eve.)

    ``Reveal the top card of your library. … Otherwise, put it into your
    graveyard.`` (Call of the Wild.) **The same printed words about a different
    card**, and the parse cannot tell them apart: ``_parse_put_source_into_zone``
    reads "it" as a self-reference and claims the clause before the
    revealed-card production is ever asked. What separates them is whether an
    earlier step of this same effect turned a card up, which is only in view
    here — the arrangement ``RevealedCardIs`` already documents for "if it's a
    …", and CR 608.2c is why it can be: the sentences are one effect.

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
    if "revealed_card" in produced:
        # A reveal claims the pronoun first, and only a line with no reveal at
        # all falls through to the source reading below. ``bin_revealed_card``
        # is the instruction that already moves that card — out of whatever
        # library it is still sitting in (CR 701.20 moves nothing) and into its
        # owner's graveyard (CR 400.3).
        return (OracleInstruction("bin_revealed_card", "", {}),)
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
    # "Return **another** target artifact card from your graveyard to your
    # hand." (Junk Diver; Sylvan Hierophant one card type over.) CR 113.7 —
    # **not** CR 109.5, which is about the words "you" and "your" and is what
    # the neighbouring comments in this engine miscite for this: "the source of
    # a triggered ability … is the object whose ability triggered". With
    # no earlier choice in the sentence for "another" to differ from — and
    # ``_lower_steps``'s ``_refuse_unfused_distinctness`` is what guarantees
    # there is none by the time a lowering sees the word — the only object left
    # for it to exclude is the ability's own source, which for a dies-trigger
    # is a card sitting in the very graveyard being searched.
    #
    # Refused for every *graveyard* zone pair but the one below, and refused
    # rather than dropped because dropping it is the direction that matters: the
    # word is on the ``TargetSpec`` and not on the ``ObjectFilter``, so
    # ``_reads_no_return_restriction`` — which does refuse ``other_than_source``
    # — never saw it, and Junk Diver returned **itself** to its owner's hand
    # from an otherwise empty graveyard.
    #
    # Scoped to the graveyard family for that blanket refusal's own reason (see
    # its comment below): the **bounce** gates itself against what
    # ``subject_matches`` can test and has carried this word since
    # ``_targets_payload`` learned it — Niambi, Esteemed Speaker's "return
    # another target creature you control to its owner's hand" already lowers
    # with ``exclude_self`` on the chosen slot, and refusing it here would take
    # a shipped card's only ability away.
    if (
        subject_names_another(subject)
        and node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and not _honours_printed_another(node)
    ):
        raise LoweringError(
            'only a one-card graveyard-to-hand return reads a printed "another"',
            node=node,
        )
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
    #
    # "Return up to X target **permanents** to their owners' hands."
    # (Recantation.) The same sentence over the widest noun there is, which
    # reaches here as an *empty* filter — CR 109.1 already makes "permanent" the
    # unnarrowed word — so the two card-type shapes are one branch. The
    # singular path beside it has read the empty filter as a bounce since
    # Boomerang and for the same reason; what kept the plural out was a literal
    # naming one card type rather than anything the handler cannot do.
    if (
        isinstance(subject, ast.TargetSpec)
        and _names_several_targets(subject)
        and node.from_zone is None
        and node.to.name == "hand"
        and node.to.owner is not None
        and node.to.owner.kind == "owner"
        and not subject.filter.is_card
        and subject.filter.card_types in ((), ("creature",))
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
        # "**target**" is what this branch is: it describes the picks for the
        # cast-time picker, which `_describe_several_card_targets` refuses to
        # do for a phrase that announces nothing. An untargeted "up to three
        # cards from their graveyard" is a choice made on resolution
        # (Ill-Gotten Gains) and belongs to the untargeted readings below —
        # without this it reached the describer and died there, so the whole
        # sentence refused on a branch it was never in.
        and subject.targeted
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
    # Every reading that needs no target is the floors'. `_bound_returns`
    # takes the ones that name their object by reference — the event recorded
    # it, or it is the ability's own source — and hands the rest down to
    # `_described_returns`, whose object is a set the sentence describes and
    # the board decides. One call either way: they are one
    # printed-specificity order split across two files, not two contracts.
    # It answers None only for an object a player chooses, which is the
    # targeted path below; a refusal raised in there is final.
    untargeted = lower_untargeted_return(node, subject, event, produced)
    if untargeted is not None:
        return untargeted
    if not _is_target(subject) and not (
        isinstance(subject, ast.TargetSpec) and subject.quantifier == "top"
    ):
        # "target" and "up to one target" (Liliana, Death Mage's +1) both
        # resolve one chosen object; anything wider has no handler.
        #
        # "**The top** creature card of your graveyard" (Shallow Grave) is the
        # one subject here that names a card without choosing one — CR 404.3's
        # ordered pile, read by position — so it passes to the graveyard branch
        # below rather than being refused for having no target. Its own
        # quantifier is what makes that safe: nothing else produces it, and the
        # branch that reads it refuses every destination but the battlefield.
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
    # "Return target **Griffin** card from your graveyard to your hand."
    # (Mtenda Griffin.) The second adjective the graveyard family reads, lifted
    # here for the colour's reason one branch up rather than weakened inside
    # the blanket refusal: it travels as ``graveyard_subtypes`` and the picker,
    # the cast gate and the handler all test it through the one predicate
    # (``graveyard_card_matches``). Every other zone-change handler goes on
    # refusing every adjective, because none of them reads one.
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "hand"
        and filt.subtypes
    ):
        gated = dataclasses.replace(gated, subtypes=())
    # "Return target **green** card from your graveyard to your hand." (Revive.)
    # The colour the reanimation one branch up has read since Dreams of the
    # Dead, on the *other* graveyard destination — and lifted rather than
    # weakened for that branch's reason: it travels as ``graveyard_colors``, and
    # the picker, the cast gate and the handler all test it through the one
    # predicate (``graveyard_card_matches``). Scoped to this zone pair, so every
    # other zone-change handler goes on refusing an adjective it cannot read.
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "hand"
        and filt.colors
    ):
        gated = dataclasses.replace(gated, colors=())
    # "Return target **basic** land card from your graveyard to your hand."
    # (Groundskeeper.) CR 205.4a's supertype, on the same key
    # ``graveyard_card_matches`` already reads for Lodestone Bauble and
    # ``_graveyard_to_hand_payload`` already emits — so the phrase was carried
    # onto the payload all along and only this gate stood in front of it. Read
    # off the printed type line, which for a card in a graveyard is the whole of
    # what there is (CR 613.1).
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "hand"
        and filt.supertypes
    ):
        gated = dataclasses.replace(gated, supertypes=())
    # "Return target **Aura** card from your graveyard to the battlefield
    # attached to Hakim." The third adjective the graveyard family reads, lifted
    # out of the blanket refusal for the colour's and the subtype's reason above
    # rather than weakened inside it: it travels as ``graveyard_subtypes``, and
    # the picker, the activation gate and the handler all test it through the
    # one predicate (``graveyard_card_matches``). Scoped to the attachment
    # phrase, so every other graveyard-to-battlefield return goes on refusing a
    # printed subtype it has no way to honour.
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "battlefield"
        and node.attached_to == "source"
        and filt.subtypes
    ):
        gated = dataclasses.replace(gated, subtypes=())
    # "Return target creature card **with mana value 3 or less** from your
    # graveyard to the battlefield." (Unearth.) The fourth narrowing the
    # graveyard family reads, lifted out of the blanket refusal for the three
    # above it rather than weakened inside it. It travels as
    # ``graveyard_mana_value`` and the picker, the cast-time re-check and the
    # handler all test it through the one predicate
    # (``graveyard_card_matches``) — which can answer it at all because CR 202.3
    # computes a mana value from the printed cost, so a card in a graveyard has
    # one where it has no power and no keyword. Scoped to the reanimation, so
    # every other zone-change handler goes on refusing a bound it cannot honour.
    if (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "battlefield"
        and node.attached_to is None
        and filt.mana_value is not None
    ):
        gated = dataclasses.replace(gated, mana_value=None)
    # "…**attached to** <something>" on a *targeted* return. Exactly one pair of
    # zones below reads it (the Aura reanimation), and this is what keeps the
    # phrase from being dropped by any of the others: an Aura that arrived
    # attached to nothing is swept away by CR 704.5m, so a return admitted with
    # the words consumed and unread is a card that reports supported and does
    # nothing. Read here rather than per branch, above the shapes that would
    # otherwise fall through to a bounce.
    if node.attached_to is not None and not (
        node.from_zone is not None
        and node.from_zone.name == "graveyard"
        and node.to.name == "battlefield"
        and node.attached_to == "source"
    ):
        raise LoweringError(
            "only the Aura reanimation attaches what it returns", node=node
        )
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
        # "Return target creature card **from a graveyard to its owner's
        # hand**." (Endbringer's Revel.) The one pairing that lets the pile be
        # anybody's: a card in a graveyard is in its owner's (CR 404.1, 400.3),
        # so "its owner's hand" is the hand beside the pile the card was chosen
        # from and the handler needs only the announced seat. Every other
        # destination keeps the refusal — "from a graveyard to **your** hand" is
        # a theft this handler does not perform, and the reanimation's own
        # any-graveyard reading lives with the "put onto the battlefield"
        # sentence in ``lowering/zones.py``.
        any_graveyard = (
            source.owner is None
            and destination.name == "hand"
            and destination.owner is not None
            and destination.owner.kind == "owner"
        )
        if not any_graveyard and (source.owner is None or source.owner.kind != "you"):
            raise LoweringError("no handler searches a graveyard but your own", node=node)
        if not filt.is_card:
            raise LoweringError("a graveyard holds cards, not permanents", node=node)

        if destination.name == "hand":
            if not any_graveyard and (
                destination.owner is None or destination.owner.kind != "you"
            ):
                raise LoweringError("this handler returns cards to your own hand", node=node)
            to_hand = _graveyard_to_hand_payload(filt)
            if any_graveyard:
                to_hand["any_graveyard"] = True
            if subject_names_another(subject):
                # The printed "another", on the key the picker
                # (``targeting._graveyard_return_spec``), the announcement gate
                # and the handler all read through one predicate
                # (``handlers/_common.excluded_graveyard_slot``). Its own key
                # rather than the ``exclude_self`` a *permanent* narrowing
                # lowers to, because the two matchers are different: this one
                # is asked about a card in a zone, which has no
                # ``permanent_id`` and no controller, and a key
                # ``graveyard_card_matches`` did not know would be dropped in
                # silence — which is the bug this line exists to close.
                to_hand["exclude_source_card"] = True
            _record_optional_card_target(to_hand, subject)
            return (
                OracleInstruction(
                    "return_creature_from_graveyard_to_hand", "", to_hand,
                ),
            )

        if destination.name == "battlefield":
            if destination.owner is not None:
                raise LoweringError("no handler for a reanimation under another's control", node=node)
            # "Return target **Aura** card from your graveyard to the
            # battlefield **attached to Hakim**." (Hakim, Loreweaver.) Its own
            # kind rather than a payload on the reanimation below, because
            # CR 303.4f makes the attachment part of the *entry*: an Aura put
            # onto the battlefield attached to nothing is swept away by
            # CR 704.5m before anyone can move it, so "which card comes back"
            # and "what it comes back onto" are one event and not a rider on
            # one.
            #
            # Gated on every word of the phrase. The subtype is what the
            # picker offers and the handler re-checks (one predicate,
            # ``graveyard_card_matches``); the host is the ability's own
            # source, which is the only host this sentence can name — nothing
            # earlier in it chooses one, so ``attached_to == "chosen"`` here
            # would read an empty scratchpad key.
            if node.attached_to == "source":
                if filt.card_types not in ((), ("enchantment",)):
                    raise LoweringError(
                        "the Aura reanimation reads an Aura card, not a "
                        f"{filt.card_types[0]} one", node=node,
                    )
                if filt.subtypes != ("aura",):
                    raise LoweringError(
                        "only an Aura is returned attached to the source",
                        node=node,
                    )
                leftover = _restrictions_beyond(
                    filt,
                    frozenset({"card_types", "subtypes", "zone", "zone_owner",
                               "is_card"}),
                )
                if leftover:
                    raise LoweringError(
                        "the Aura reanimation does not honour "
                        f"{leftover[0]!r}", node=node,
                    )
                return (
                    OracleInstruction(
                        "reanimate_aura_onto_source", "",
                        {"graveyard_subtypes": ["aura"],
                         "card_type": "enchantment"},
                    ),
                )
            # Which *kind* of card comes back is the sentence's own word, so it
            # travels as payload the way the colour narrowing below does.
            # Restricted to four of CR 110.4a's six permanent card types because the
            # instruction puts the card **onto the battlefield**: an instant
            # card returned there is CR 111.1's nothing, and a phrase naming
            # one is a card this engine has not got. Regrowth's untyped "target
            # card" still has no lowering here — claiming it would silently
            # narrow the player's choice to whatever the handler happened to
            # scan for.
            if filt.card_types not in _REANIMABLE_CARD_TYPES:
                raise LoweringError(
                    "the reanimation handler only moves permanent cards",
                    node=node,
                )
            # A printed colour narrowing rides the payload; a card with none
            # keeps emitting the empty payload byte for byte.
            payload: dict[str, object] = (
                {"colors": tuple(filt.colors)} if filt.colors else {}
            )
            # "…**with mana value 3 or less**" (Unearth). Emitted only when the
            # card prints a bound, so every reanimation written before this
            # keeps a byte-identical payload and no behaviour signature moves.
            # On the key ``graveyard_card_matches`` reads, which is what the
            # picker, the CR 601.2c re-check and the handler all ask — a bound
            # only one of the three knew about is a target one offers and
            # another declines.
            if filt.mana_value is not None:
                bound = filt.mana_value.value
                if not isinstance(bound, ast.Fixed):
                    # An X-valued bound is a number nobody knows until the cast
                    # is announced, and the picker enumerates before that. It
                    # refuses rather than being dropped, which would return a
                    # card of any cost.
                    raise LoweringError(
                        "the reanimation reads a printed mana value, not an X",
                        node=node,
                    )
                payload["graveyard_mana_value"] = {
                    "op": filt.mana_value.op, "value": bound.value,
                }
            # Emitted only when the card prints something other than "creature",
            # so every reanimation written before this keeps a byte-identical
            # payload and no behaviour signature moves. The handler, the picker
            # and the cast-time re-check all read it through
            # ``graveyard_card_matches``/``card_has_type``, which is CR 205.2a's
            # answer — an Artifact Creature card in a graveyard *is* an artifact
            # card, and `primary_type` says it is only a creature one.
            if filt.card_types[0] != "creature":
                payload["card_type"] = filt.card_types[0]
            # "…**If the creature would leave the battlefield, exile it instead
            # of putting it anywhere else.**" (Dreams of the Dead.) Folded onto
            # the move by the parse, because the permanent it applies to does
            # not exist until this instruction runs — the same reason the
            # keyword grant after a reanimation folds.
            if node.exile_on_leave:
                payload["exile_on_leave"] = True
            # "Return **the top** creature card of your graveyard to the
            # battlefield." (Shallow Grave.) CR 404.1 puts an arriving card on
            # top and CR 404.2 keeps the pile in that order, so the card is
            # named by position and nobody chooses: the handler takes the most
            # recently added creature card rather than offering a picker the
            # card never printed. (CR 404.3 is the *simultaneous-arrival*
            # tie-break and is not this rule; ``engine/graveyard_order.py``
            # records the correction.)
            #
            # A payload rather than a second kind, for the reason the colour
            # narrowing above is one: what changes is *which* card in the
            # pile, and everything after it — the arrival, the record the
            # sentences behind it read — is the same work.
            if (
                isinstance(subject, ast.TargetSpec)
                and subject.quantifier == "top"
            ):
                payload["from_top"] = True
                return (
                    OracleInstruction("reanimate_creature", "", payload),
                )
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
        bounce_filter = testable_filter_payload(
            filt,
            refusal="the bounce handler cannot test",
            node=node,
            require_narrowing=False,
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
