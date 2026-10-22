"""Attaching an Aura: the record, and what it may be attached to.

``attach_aura`` and ``detach_aura`` write the one record an attachment is
(``attached_to`` on the Aura or Equipment, ``attached_auras`` on its host;
CR 303.4, 301.5f), and every derivation in this family reads it back through
``auras_attached_to`` instead of a flag stamped on the host, so removal is the
record ceasing to exist. Beside it: the one predicate every mover asks before
it attaches (``aura_attach_refusal`` / ``enchant_card_refusal``; CR 303.4j,
702.5, 702.16c), the triggers an attachment's own abilities fire about its
host (``attached_subject_triggers``), and the records a permanent that
*became* an Aura carries (Necromancy, the Licids), with the CR 116.2c offer
that ends one.

Split out of ``engine/auras.py`` at the 2,000-line cap, beneath the readers
that ask what an attached Aura does. ``engine/auras.py`` registers the offer
with ``engine/special_actions.py`` and re-exports the names other modules
still pull from it.
"""

from __future__ import annotations


def auras_attached_to(permanent) -> list:
    """Every Aura currently attached to *permanent*, in attachment order.

    ``attached_aura`` is a single slot that a second Aura overwrites, so it
    cannot answer this: a creature can carry any number of Auras (CR 303.4).
    The list is the authority; the slot is kept in step for the callers that
    only ever want "an" Aura.
    """
    return list(permanent.metadata.get("attached_auras") or [])


def attached_subject_triggers(game, host, condition_kinds, payload_key):
    """``(seat, attachment, trig)`` for every trigger of something attached to
    *host* whose condition is about the permanent it is attached to.

    The combat fire sites scan a creature's **own** ``effective_card``, and an
    attached Aura's abilities are not on it — an Aura's ability is the Aura's,
    controlled by the Aura's controller (CR 113.7a), not a granted ability of
    its host. So an Aura printing "whenever enchanted creature attacks or
    blocks" (Imprison) is invisible to those scans, exactly as "when enchanted
    creature dies" was until ``mixins/helpers.py`` grew the branch this
    function generalises.

    *payload_key* is the narrowing the condition's own table wrote when it read
    the word "enchanted" — so a trigger printed about "this creature" is not
    picked up here and one printed about the attachment's host is not picked up
    by the host's own scan. One condition kind, two dispatch scopes, and the
    payload is what tells them apart.
    """
    from .trigger_utils import matching_triggers

    found = []
    for attachment in auras_attached_to(host):
        seat = game.controller_index_of(attachment)
        if seat is None:
            continue
        for trig in matching_triggers(
            attachment.effective_card, condition_kinds=condition_kinds
        ):
            noun = trig.condition.payload.get(payload_key)
            if not noun:
                continue
            # The printed noun is tested rather than assumed: "enchanted
            # **creature** attacks" is not satisfied by an Equipment on an
            # artifact that an animation has not made a creature (CR 613
            # layer 4), and a word consumed and never read is a word that
            # could be deleted.
            if not host.has_type(str(noun)):
                continue
            found.append((seat, attachment, trig))
    return found


#: What a permanent that *became* an Aura was given (Necromancy). The record the
#: sentence "it becomes an Aura with "enchant <quality>."" leaves behind: the
#: subtype is CR 613 layer 4 and goes through ``type_changes.gain_types`` like any
#: other gained type, and this is the other half — the enchant ability (CR 702.5)
#: that says what the permanent may legally be attached to.
#:
#: A record rather than a granted text line, because the readers of an enchant
#: clause ask two different things of it: ``aura_enchant_noun`` reads a *card*
#: and gates on the printed word "Aura" in its type line, which a permanent that
#: became one does not have, and the quality this sentence grants is a relation
#: between two permanents rather than a noun a card's text could state.
#: :func:`enchant_card_refusal` — the one predicate every caller asks — reads it.
BECAME_AURA_ENCHANT = "became_aura_enchant"

#: The permanent whose ability put this one onto the battlefield, by id. What
#: "enchant creature **put onto the battlefield with Necromancy**" is about, and
#: the only thing that can say so: the creature was a card in a graveyard when
#: the ability was activated, and CR 400.7 makes what arrived a new object, so
#: nothing on the board or on the stack records where it came from.
#:
#: Stamped by ``handlers/reanimation.reanimate_creature``, read by
#: :func:`enchant_card_refusal`. Beside the record above rather than in the
#: handler that writes it, for ``tokens.CREATED_WITH_PERMANENT_ID``'s reason:
#: the writer and the reader sit at opposite ends of the pipeline.
PUT_ONTO_BATTLEFIELD_BY = "put_onto_battlefield_by"

#: The mark a layer-4 record carries when :func:`end_became_aura_effect` is the
#: thing that will take it away again. Necromancy's Aura is permanent and
#: carries none; a Licid's is a continuous effect its controller may pay to end
#: (CR 116.2c), so the records that effect wrote have to be findable again —
#: and findable *exactly*, because a permanent may have gained a type from
#: something else in between.
BECAME_AURA_RECORD = "from_became_aura"


def end_became_aura_effect(game, permanent) -> bool:
    """Undo what ``become_aura_with_enchant`` did to *permanent*. CR 116.2c.

    "You may pay {C} to end this effect" (Tempest's five Licids). The effect is
    everything that one instruction recorded — the gained enchantment type and
    Aura subtype (CR 613 layer 4), the creature type and creature subtypes it
    replaced (CR 205.1a), the ability it took away (layer 6) and the enchant
    clause it granted (CR 702.5) — so ending it is dropping exactly those
    records and nothing else. Nothing is *restored*: every one of them is a
    contribution, so the permanent goes back to being what its printed card says
    by the contribution ceasing to exist, which is the same shape
    ``detach_aura`` has one screen up.

    The attachment goes with it. An Aura that stopped being an Aura is not
    attached to anything (CR 301.5f's word only means something while the
    permanent is an Attachment), and leaving the record would make the host go
    on counting a creature among its Auras.

    Returns whether there was an effect to end.
    """
    from .keywords import restore_ability_line
    from .type_changes import end_type_changes

    record = permanent.metadata.pop(BECAME_AURA_ENCHANT, None)
    if record is None:
        return False
    host = permanent.metadata.get("attached_to")
    if host is not None:
        detach_aura(permanent, host)
    end_type_changes(permanent, lambda entry: bool(entry.get(BECAME_AURA_RECORD)))
    line = record.get("ability_line")
    if line:
        restore_ability_line(permanent, str(line))
    game._refresh_dynamic_creatures()
    return True


def _became_aura_offer(game, permanent):
    """What *permanent* is offering to end its became-an-Aura effect for, or None.

    The record is the effect: `become_aura_with_enchant` writes it and
    :func:`end_became_aura_effect` removes it, so "is the offer open?" and "is
    there anything to undo?" are one question with one answer.

    The **cost** comes out of that record rather than off the card, and it has
    to: the printed sentence sits inside the ability the same resolution took
    away (CR 613 layer 6), so by the time anyone can accept, the permanent no
    longer says it. CR 611.2a's effect outlives the ability that made it, and
    CR 116.2c's offer is part of the effect.
    """
    from .special_actions import SpecialActionOffer

    record = permanent.metadata.get(BECAME_AURA_ENCHANT)
    if not record:
        return None
    cost = record.get("end_cost")
    if not cost:
        return None
    seat = game.controller_index_of(permanent)
    if seat is None:
        return None
    # "**You** may pay" — the ability's controller (CR 109.5), which for a
    # permanent that turned itself into an Aura is whoever controls it now.
    return SpecialActionOffer(seat=seat, mana=dict(cost))


def _take_became_aura_offer(game, seat: int, permanent) -> None:
    if end_became_aura_effect(game, permanent):
        game.log.append(
            f"{game.players[seat].name} paid to end {permanent.card.name}'s "
            "effect (CR 116.2c): it is a creature again"
        )


def _became_aura_refusal(game, aura, granted, host) -> str | None:
    """Why a permanent that *became* an Aura may not enchant *host*.

    (Necromancy: ``it becomes an Aura with "enchant creature put onto the
    battlefield with Necromancy."``) The clause was granted rather than printed,
    so it is read off the record :data:`BECAME_AURA_ENCHANT` holds instead of
    off the card's text — but it is asked here, inside the one predicate the
    cast gate, the pickers, the attach and the CR 704.5m sweep all share, so
    what is offered and what is allowed cannot drift.

    The origin rider is the whole of what the sentence adds, and it is tested
    rather than dropped: the Aura may enchant the creature *its own ability* put
    onto the battlefield and no other, so an effect that would move it
    (Enchantment Alteration) finds no legal host and CR 303.4j leaves it where
    it is. Left permissive — which is what an unread noun gets in
    ``permanent_matches_enchant_noun`` — the printed restriction would be
    enforced by nothing.
    """
    from .mixins.stack import permanent_matches_enchant_noun
    from .target_immunity import cannot_be_enchanted

    if host is None or not game.is_on_battlefield(host):
        return "it is no longer on the battlefield"
    noun = str(granted.get("noun") or "")
    if not permanent_matches_enchant_noun(host, noun):
        return f"it isn't a legal {noun}"
    if granted.get("origin") == "source" and (
        host.metadata.get(PUT_ONTO_BATTLEFIELD_BY) != aura.permanent_id
    ):
        return "it wasn't put onto the battlefield with this enchantment"
    if cannot_be_enchanted(host, by_aura=aura):
        return "it can't be enchanted"
    return None


def aura_attach_refusal(game, aura, host) -> str | None:
    """Why *aura* may not become attached to *host*, or None when it may.

    CR 303.4j: an effect that would attach an Aura to something it can't legally
    enchant simply doesn't move it — so this is asked *before* the move, and the
    Aura stays where it is when it answers. One predicate rather than a check at
    each mover, for the reason ``equip_refusal`` is one: a picker and a
    resolution ask the same question, and a second copy is a second chance to
    disagree.

    Every clause is one the engine already reads somewhere else:
    ``aura_enchant_noun`` is what the cast gate matches a target against,
    ``enchant_seat_satisfied`` is the seat half of the same clause (CR 702.5),
    ``cannot_be_enchanted`` is CR 303.4's "can't be enchanted" half, and
    ``_is_protected_from`` is CR 702.16c's — see :func:`enchant_card_refusal`
    for why this is a host being *chosen*, and the state-based sweep's
    question of an attached Aura is a different one.
    """
    if host is aura:
        return "an Aura can't enchant itself"
    return enchant_card_refusal(
        game, aura.effective_card, game.controller_index_of(aura), host, aura=aura
    )


def enchant_card_refusal(game, card, controller_seat, host, *, aura=None) -> str | None:
    """The same question asked of an Aura **card** rather than a permanent.

    "…chooses a creature that this card could enchant" (Takklemaggot) is asked
    while the Aura is in a graveyard: CR 704.5m put it there the moment the
    creature it enchanted left, and the trigger that asks resolves afterwards.
    There is no permanent to read a controller or an effective card off, so both
    are passed in — the ability's controller (CR 108.4a: a card in a graveyard
    has none of its own) and the card as printed.

    One body rather than two, because :func:`aura_attach_refusal` delegates
    here: every picker, every attach and every Aura put onto the battlefield
    with a host ask this, and a second copy is a second chance to disagree
    about what a legal host is.

    **This is the question of a host being *chosen*** — an Aura becoming
    attached, entering attached, or offered a host to enter on — and it asks
    CR 702.16c's first sentence: a permanent with protection "can't be
    enchanted by Auras that have the stated quality". It did not, so a black
    Aura card against a White Knight came back legal: Takklemaggot's picker
    offered the Knight, Hakim's and Iridescent Drake's reanimations attached a
    card to a creature protected from it, Academy Researchers offered one from
    the hand, and in every case the CR 702.16c sweep then put the Aura into a
    graveyard the rules say it never leaves (CR 303.4i: it "remains in its
    current zone"; CR 701.3b: an attach to an illegal host "doesn't move" it).

    It is **not** the question of an Aura already attached, and no state-based
    action asks it. That one is ``Game.check_state_based_actions``' CR 702.16c
    sweep, which carries CR 702.16n's exemption ("this effect doesn't remove
    this Aura", Floating Shield) — an exemption from the *state-based action*
    alone: a creature with protection from white still can't *become* enchanted
    by a white Aura, whatever another Aura on it says. The one grant this
    question leaves out is the Aura's own, on the host it is already on
    (``ignoring_aura``): there the attach is a no-op (CR 701.3b), and asking it
    must not report the Aura illegal on the creature its own protection
    covers. ``tests/regressions/test_aura_host_protection.py`` holds every
    caller.
    """
    refusal = _enchant_clause_refusal(
        game, card, controller_seat, host, aura=aura,
    )
    if refusal is not None:
        return refusal
    # CR 702.16c (and 702.16k's player form, which is why the seat goes along:
    # "can't be enchanted by Auras that player controls"). A permanent Aura is
    # asked through the layers; a card — in a graveyard, a hand, or a permanent
    # not yet on the battlefield — by what it is, under the seat that will
    # control it.
    on_board = aura is not None and game.is_on_battlefield(aura)
    if game._is_protected_from(
        host, aura if on_board else card, seat=controller_seat,
        ignoring_aura=(
            aura if on_board and aura.metadata.get("attached_to") is host
            else None
        ),
    ):
        return f"{host.card.name} has protection from {card.name}"
    return None


def _enchant_clause_refusal(game, card, controller_seat, host, *, aura=None) -> str | None:
    """What the enchant ability and CR 303.4's "can't be enchanted" effects
    say about *host* — :func:`enchant_card_refusal` without protection."""
    from .mixins.stack import (aura_enchant_noun, enchant_seat_satisfied,
                               permanent_matches_enchant_noun)
    from .target_immunity import cannot_be_enchanted

    # An enchant ability the permanent was **given** rather than printed
    # (Necromancy). Asked first, because the printed reading below would find no
    # enchant line at all and refuse every host — the card has none, which is
    # exactly why its own sentence grants one.
    granted = aura.metadata.get(BECAME_AURA_ENCHANT) if aura is not None else None
    if granted is not None:
        return _became_aura_refusal(game, aura, granted, host)
    if host is None or not game.is_on_battlefield(host):
        return "it is no longer on the battlefield"
    noun = aura_enchant_noun(card)
    if noun is None:
        return f"{card.name} has no enchant ability"
    if not permanent_matches_enchant_noun(host, noun):
        return f"it isn't a legal {noun}"
    if not enchant_seat_satisfied(
        game, controller_seat, game.controller_index_of(host), noun
    ):
        return f"{host.card.name} is not {noun}"
    if cannot_be_enchanted(host, by_aura=aura):
        return "it can't be enchanted"
    return None


def attach_aura(aura, target) -> None:
    """Attach *aura* to *target*, recording it as an owned continuous effect.

    Stamps the Aura with a CR 613.7e timestamp at the moment it becomes
    attached, so its contribution sorts against other effects by when it
    started applying rather than sharing one derived timestamp with every other
    Aura on the board. An Equipment attaches through here too — the record is
    the same, and so is the rule (CR 301.5f) — via
    ``engine/equipment.py.attach_equipment``, which owns the legality and the
    move-from-a-previous-host half (CR 701.3).

    Both directions are recorded here so no caller has to remember to keep them
    in step: ``attached_to`` on the Aura, and both ``attached_auras`` (the list,
    which is the authority) and ``attached_aura`` (the single slot kept for the
    callers that only want "an" Aura) on the target.
    """
    from .continuous import next_timestamp

    aura.metadata["attached_to"] = target
    attached = list(target.metadata.get("attached_auras") or [])
    if not any(existing is aura for existing in attached):
        attached.append(aura)
    target.metadata["attached_auras"] = attached
    target.metadata["attached_aura"] = aura
    # CR 613.7e / 701.3c: a new timestamp *each time* it becomes attached. This
    # was `setdefault`, which is the same thing for an Aura (it attaches once
    # and then only leaves) and wrong for an Equipment, which moves: re-equipped
    # onto a second creature it kept the stamp of its first attachment, and so
    # ordered its +1/+1 before an effect that had in fact applied earlier.
    #
    # The **object's** timestamp, which is what the rule says is replaced
    # ("receives a new timestamp each time it becomes attached") — so every
    # static ability on the Aura or Equipment is ordered by the attachment
    # (CR 613.7a), not only the ones a collector remembered to read off the
    # metadata key beside it. That key keeps the same number for the layers
    # that still read it.
    aura.timestamp = next_timestamp()
    aura.metadata["aura_timestamp"] = aura.timestamp


def detach_aura(aura, target) -> None:
    """Stop *aura* applying to *target* (CR 611.3).

    Dropping the Aura from the list is the whole removal: its P/T contribution
    is recomputed from the Auras still attached, so there is no remembered
    delta to subtract and nothing that can fall out of step with what was
    added.
    """
    remaining = [
        existing
        for existing in (target.metadata.get("attached_auras") or [])
        if existing is not aura
    ]
    if remaining:
        target.metadata["attached_auras"] = remaining
        target.metadata["attached_aura"] = remaining[-1]
    else:
        target.metadata.pop("attached_auras", None)
        if target.metadata.get("attached_aura") is aura:
            target.metadata.pop("attached_aura", None)
    # The attachment's own half of the record, kept in step the way
    # `attach_aura` keeps it: an Aura that detaches is leaving anyway, but an
    # Equipment stays on the battlefield (CR 704.5n), and a stale `attached_to`
    # on it is an attachment the state-based sweep finds illegal again on every
    # pass — which is a sweep that never reaches its fixpoint.
    if aura.metadata.get("attached_to") is target:
        aura.metadata.pop("attached_to", None)
        # CR 603.10 last-known information. A triggered ability of the Aura
        # that resolves after the Aura has left — or a later step of the same
        # resolution that removed it, Cocoon's "sacrifice it, put a +1/+1
        # counter on **enchanted creature**" — still knows which creature that
        # was. `handlers/_targets.attached_host` reads this back, and only
        # while the host itself is still on the battlefield.
        aura.metadata["last_attached_to"] = target
