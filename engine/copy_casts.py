"""Casting a copy of an exiled card during a resolution (CR 707.12).

"{2}, {T}: You may copy the exiled card. If you do, you may cast the copy
without paying its mana cost." (Isochron Scepter.)

CR 707.12: "An effect that instructs a player to cast a copy of an object (and
not just copy a spell) follows the rules for casting spells, except that the
copy is created in the same zone the object is in and then cast while another
spell or ability is resolving." So the copy is made **in exile** — where the
imprinted card is (Spellweaver Helix's 2004-12-01 ruling says so of its own
copy) — and cast from there, during the ability's resolution, the way
``engine/madness.py``'s offer casts a card (CR 608.2g: the spell becomes the
topmost object and the ability then finishes).

**One offer per copy** (CR 707.12a: a player "may cast" each copy, chosen
individually; CR 607.3 makes "the exiled card" every card the linked exile
holds). Both halves of the printed sentence are optional (Spellweaver Helix's
2005-03-01 ruling), and a copy made and not cast ceases to exist the next time
state-based actions are checked (CR 707.10a; Isochron Scepter's 2020-08-07
ruling) — nothing can see it in between, so a copy is made only when the offer
is taken and the cast fails or is declined at the same answer, and it is taken
out of exile again then.

The pieces:

* :data:`COPY_CAST_KIND`'s handler (``handlers/stack.cast_copy_of_exiled_card``)
  reads the cards (``linked_exile.cards_still_exiled_with`` — a card that left
  exile while the ability waited makes no copy, the ruling's case) and arms
  :data:`COPY_CAST_PROMPT` for each;
* the copy is a distinct ``CardDefinition`` equal to the card (CR 707.2: the
  copiable values), put into the caster's exile through
  ``Game.put_card_into_exile`` and covered by one :class:`CastPermission`
  that waives the mana cost (``free``, CR 118.9 — X is 0, CR 107.3b; the
  additional costs stay, CR 118.9d) and says the spell is a copy
  (``cast_as_copy``: the cast path stamps ``StackItem.is_copy``, so it
  resolves and ceases to exist, CR 707.10a);
* the answer casts it through ``Game.queue_from_hand`` (``from_zone="exile"``),
  or declines; either way the offer's permission is retired and a copy still
  in exile is taken out of the game.

A seat nobody asks answers as the offer is armed, with the AI's rehearsed cast
chooser (``ai_policy.choose_copy_cast``) — the madness offer's arrangement.
"""

from __future__ import annotations

import dataclasses

#: The instruction: "You may copy the exiled card. If you do, you may cast the
#: copy without paying its mana cost." ``other`` in the payload is Spellweaver
#: Helix's "copy **the other**".
COPY_CAST_KIND = "cast_copy_of_exiled_card"

#: The prompt each copy is offered on.
COPY_CAST_PROMPT = "copy_cast"

#: The permission's duration: the offer's own, retired by its answer.
COPY_CAST_OFFER = "copy_cast_offer"


def make_copy_in_exile(game, seat: int, card):
    """A copy of *card* (CR 707.2) in seat *seat*'s exile, the object the
    exile now holds."""
    copy = dataclasses.replace(card)
    return game.put_card_into_exile(game.players[seat], copy)


def offer_permission(game, seat: int, copy, source_name: str):
    """The grant the offer opens: *copy* out of *seat*'s exile, free of its
    mana cost, cast as a copy."""
    from .cast_permissions import grant_permission

    return grant_permission(
        game, player_index=seat, zone="exile", mode="cast", cards=[copy],
        free=True, duration=COPY_CAST_OFFER, source_name=source_name,
        cast_as_copy=True,
    )


def retire_offer(game, permission) -> None:
    """End the offer's permission, used or not."""
    game.cast_permissions[:] = [
        held for held in game.cast_permissions if held is not permission
    ]


def cease_to_exist(game, seat: int, copy) -> None:
    """A copy of a card outside the stack and the battlefield ceases to exist
    (CR 707.10a): taken out of the exile it was made in, by identity, and put
    nowhere."""
    game.take_card_from_exile(seat, copy)


def arm_copy_cast(game, seat: int, card, source_name: str, *, one_of=None) -> None:
    """Offer *seat* a cast of a copy of *card*.

    *one_of* is the record an offer shares with its siblings when the
    sentence copies **one** of the exiled cards ("a card exiled with this
    artifact", Panoptic Mirror; CR 607.3's "a" card, chosen by the
    controller): the offers are made card by card, and the first one taken
    is the choice — it marks the record (:func:`one_of_taken`) and its
    siblings still owed are withdrawn. Declining one passes to the next, so
    every card is a choice and so is none."""
    data = {"card_name": card.name, "source_name": source_name, "_card": card}
    if one_of is not None:
        data[ONE_OF] = one_of
    game.arm_pending_choice("copy_cast", seat, **data)


#: The pending choice's key for the record its sibling offers share.
ONE_OF = "_one_of"


def new_one_of() -> dict:
    """A fresh record for one "copy a card exiled with this" choice."""
    return {"taken": False}


def one_of_taken(one_of) -> bool:
    """Whether a copy has been cast under *one_of* already."""
    return bool(isinstance(one_of, dict) and one_of.get("taken"))


def _take_one_of(game, choice) -> None:
    """The offer *choice* was taken: mark its record and withdraw every
    sibling offer still owed (they were the other cards it could have been)."""
    one_of = choice.data.get(ONE_OF)
    if not isinstance(one_of, dict):
        return
    one_of["taken"] = True
    for sibling in list(game.pending_choices):
        if (
            sibling is not choice
            and sibling.kind == COPY_CAST_PROMPT
            and sibling.data.get(ONE_OF) is one_of
        ):
            game.discard_pending_choice(sibling)


def _in_exile(game, card) -> int | None:
    """The seat whose exile holds *card*, by identity, or None."""
    for seat, player in enumerate(game.players):
        if any(held is card for held in player.exile):
            return seat
    return None


def resolve_copy_cast_offer(game, choice, response: dict) -> bool:
    """Answer the ``copy_cast`` prompt.

    ``accept`` false (or absent) declines: no copy. True makes the copy and
    casts it — announced by *announcement* (the keywords ``queue_from_hand``
    takes) or by *perform*, a callable making the engine call. A cast the
    engine refuses leaves the prompt owed and nothing made; the refusal is
    appended to *outcome* when the caller passed a list.
    """
    card = choice.data.get("_card")
    seat = choice.player_index
    if not response.get("accept"):
        game.log.append(
            f"{game.players[seat].name} did not cast a copy of "
            f"{getattr(card, 'name', 'the card')}"
        )
        game.discard_pending_choice(choice)
        return True
    if card is None or _in_exile(game, card) is None:
        game.log.append(
            f"{getattr(card, 'name', 'The card')} is no longer exiled, so no copy is made"
        )
        game.discard_pending_choice(choice)
        return True
    result = _cast_a_copy(
        game, seat, card, str(choice.data.get("source_name") or ""),
        perform=response.get("perform"),
        announcement=dict(response.get("announcement") or {}),
    )
    outcome = response.get("outcome")
    if isinstance(outcome, list):
        outcome.append(result)
    if not getattr(result, "supported", False):
        return False
    _take_one_of(game, choice)
    game.discard_pending_choice(choice)
    return True


def _cast_a_copy(
    game, seat: int, card, source_name: str, *, perform=None, announcement=None,
    choose=None,
):
    """Make the copy, cast it, and clean up whatever the cast did not take.

    *choose*, for a seat nobody asks, is called with ``(copy, permission)``
    and returns the announcement to cast with, or None to decline — so the
    AI weighs the very object it would cast."""
    copy = make_copy_in_exile(game, seat, card)
    permission = offer_permission(game, seat, copy, source_name)
    result = None
    try:
        if choose is not None:
            announcement = choose(copy, permission)
            if announcement is None:
                return None
        if perform is None:
            keywords = dict(announcement or {})
            keywords["from_zone"] = "exile"
            name = keywords.pop("card_name", None) or copy.name

            def perform(table):
                return table.queue_from_hand(seat, name, **keywords)

        result = perform(game)
    finally:
        retire_offer(game, permission)
        if any(held is copy for held in game.players[seat].exile):
            cease_to_exist(game, seat, copy)
    if getattr(result, "supported", False):
        game.log.append(
            f"{game.players[seat].name} cast a copy of {card.name} without "
            f"paying its mana cost ({source_name})"
        )
    return result


def default_copy_cast_offer(game, choice) -> None:
    """What a seat nobody asks does: the AI's rehearsed cast chooser over the
    copy (``ai_policy.choose_copy_cast``); a cast it would not make, or one the
    engine refuses, declines."""
    from .ai_actions import cast_announcement
    from .ai_payment import tap_planned_lands
    from .ai_policy import choose_copy_cast

    card = choice.data.get("_card")
    seat = choice.player_index
    source_name = str(choice.data.get("source_name") or "")

    def choose(copy, permission):
        action = choose_copy_cast(game, seat, copy, permission)
        if action is None:
            return None
        return cast_announcement(tap_planned_lands(game, seat, action))

    if card is not None and _in_exile(game, card) is not None:
        result = _cast_a_copy(game, seat, card, source_name, choose=choose)
        if getattr(result, "supported", False):
            _take_one_of(game, choice)
            game.discard_pending_choice(choice)
            return
    game.log.append(
        f"{game.players[seat].name} did not cast a copy of "
        f"{getattr(card, 'name', 'the card')}"
    )
    game.discard_pending_choice(choice)


__all__ = [
    "COPY_CAST_KIND",
    "COPY_CAST_OFFER",
    "COPY_CAST_PROMPT",
    "ONE_OF",
    "arm_copy_cast",
    "cease_to_exist",
    "default_copy_cast_offer",
    "make_copy_in_exile",
    "new_one_of",
    "offer_permission",
    "one_of_taken",
    "resolve_copy_cast_offer",
    "retire_offer",
]
