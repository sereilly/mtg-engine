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

**…and the same offer on the card itself** (:data:`ORIGINAL`): "{3}, {T},
Sacrifice Shell of the Last Kappa: You may cast a spell from among cards exiled
with Shell of the Last Kappa without paying its mana cost." Cast while the
ability resolves (CR 608.2g), free of its mana cost (CR 118.9), out of the
exile that holds it — its owner's, which need not be the caster's
(``CastPermission.zone_player_index``) — and no copy is made, so nothing ceases
to exist afterwards and the spell is not one (it resolves to its owner's
graveyard). The prompt, its answer and the AI's default are the copy offer's:
one question ("cast this card from exile for free?") either way.

**…and on a card in a graveyard, paid for** (:data:`FROM_GRAVEYARD_OF`):
"Whenever a creature an opponent controls dies, you may cast target instant
card from your graveyard. If that spell would be put into a graveyard, exile
it instead." (Toshiro Umezawa; Chandra, Flame's Catalyst's −2.) With no stated
duration the sentence is a cast during the resolution (CR 608.2g), not a
lasting permission: the card itself, out of the caster's graveyard, its mana
cost **paid** (Toshiro's 2005-02-01 ruling) under a permission carrying the
exile rider (``exile_instead``), which the cast path stamps on the spell. The
one offer here that is not free; the same prompt, answer and AI default.
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


def offer_permission(
    game, seat: int, copy, source_name: str, *, original: bool = False,
    zone_seat: int | None = None, zone: str = "exile", free: bool = True,
    exile_instead: bool = False,
):
    """The grant the offer opens: *copy* out of *seat*'s exile, free of its
    mana cost, cast as a copy — or, *original*, the exiled card itself out of
    *zone_seat*'s exile (its owner's), cast as itself.

    *zone*, *free* and *exile_instead* are the graveyard offer's
    (:data:`FROM_GRAVEYARD_OF`): the card itself out of its owner's
    graveyard, its mana cost paid, and "If that spell would be put into a
    graveyard, exile it instead" stamped on the spell by the cast path."""
    from .cast_permissions import grant_permission

    return grant_permission(
        game, player_index=seat, zone=zone, mode="cast", cards=[copy],
        free=free, duration=COPY_CAST_OFFER, source_name=source_name,
        cast_as_copy=not original, exile_instead=exile_instead,
        zone_player_index=zone_seat if original else None,
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


def arm_copy_cast(
    game, seat: int, card, source_name: str, *, one_of=None,
    from_hand_of: int | None = None, original: bool = False,
    from_graveyard_of: int | None = None, exile_instead: bool = False,
) -> None:
    """Offer *seat* a cast of a copy of *card*.

    *from_hand_of* is the seat whose **hand** holds *card*, when it is not in
    exile: "Target opponent reveals their hand. You may copy an instant or
    sorcery card in it." (Reversal of Fortune.) The offer then asks after the
    card in that hand rather than in exile, and nothing else changes — the
    copy is still made in the caster's exile and cast from there, the one
    road this module casts by (CR 707.12 would create it in the hand it
    copies; the engine has no cast out of another player's hand).

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
    # *original*: the offer casts *card* itself rather than a copy of it
    # (Shell of the Last Kappa) — see the module docstring.
    if original:
        data[ORIGINAL] = True
    if from_hand_of is not None:
        data[FROM_HAND_OF] = int(from_hand_of)
    # *from_graveyard_of*: "you may cast target instant card from your
    # graveyard. If that spell would be put into a graveyard, exile it
    # instead." (Toshiro Umezawa; Chandra, Flame's Catalyst's −2.) The card
    # itself, out of that seat's graveyard, during the resolution that
    # allows it (CR 608.2g) — and its mana cost is **paid** (Toshiro's
    # 2005-02-01 ruling: "You must still pay the mana cost"), so it is the
    # one offer here that is not free.
    if from_graveyard_of is not None:
        data[ORIGINAL] = True
        data[FROM_GRAVEYARD_OF] = int(from_graveyard_of)
        if exile_instead:
            data[EXILE_INSTEAD] = True
    game.arm_pending_choice("copy_cast", seat, **data)


def arm_graveyard_cast(
    game, seat: int, card, source_name: str, *, exile_instead: bool = False,
) -> None:
    """Offer *seat* a cast of *card* out of its own graveyard during this
    resolution, paying its costs (CR 608.2g) — the offer
    :func:`arm_copy_cast` makes with :data:`FROM_GRAVEYARD_OF`."""
    arm_copy_cast(
        game, seat, card, source_name, from_graveyard_of=seat,
        exile_instead=exile_instead,
    )


#: The pending choice's key for the record its sibling offers share.
ONE_OF = "_one_of"

#: The pending choice's key for the seat whose hand holds the copied card.
FROM_HAND_OF = "_from_hand_of"

#: The pending choice's key saying the offer casts the exiled card **itself**,
#: not a copy (Shell of the Last Kappa).
ORIGINAL = "_original"

#: The pending choice's key for the seat whose **graveyard** holds the card
#: the offer casts itself, paying its mana cost (Toshiro Umezawa).
FROM_GRAVEYARD_OF = "_from_graveyard_of"

#: The graveyard offer's printed rider: "If that spell would be put into a
#: graveyard, exile it instead" (the permission's ``exile_instead``).
EXILE_INSTEAD = "_exile_instead"


def _graveyard_seat(choice) -> int | None:
    """The seat whose graveyard holds the offered card, or None."""
    seat = choice.data.get(FROM_GRAVEYARD_OF)
    return seat if isinstance(seat, int) else None


def _what(choice) -> str:
    """How the log names what the offer casts: the card, or a copy of it."""
    name = getattr(choice.data.get("_card"), "name", "the card")
    return name if choice.data.get(ORIGINAL) else f"a copy of {name}"


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


def _still_there(game, choice) -> bool:
    """Whether the card *choice* copies is still where the offer found it —
    in exile, or in the hand :data:`FROM_HAND_OF` names. A card that left
    makes no copy (Isochron Scepter's ruling)."""
    card = choice.data.get("_card")
    if card is None:
        return False
    hand_of = choice.data.get(FROM_HAND_OF)
    if isinstance(hand_of, int) and 0 <= hand_of < len(game.players):
        return any(held is card for held in game.players[hand_of].hand)
    # A graveyard card that left is a new object (CR 400.7) the ability no
    # longer names: nothing is cast.
    graveyard_of = _graveyard_seat(choice)
    if graveyard_of is not None and 0 <= graveyard_of < len(game.players):
        return any(held is card for held in game.players[graveyard_of].graveyard)
    return _in_exile(game, card) is not None


def _gone_line(game, choice) -> str:
    """The log line for a copy that cannot be made: the card left."""
    card = choice.data.get("_card")
    name = getattr(card, "name", "The card")
    hand_of = choice.data.get(FROM_HAND_OF)
    if isinstance(hand_of, int) and 0 <= hand_of < len(game.players):
        return (
            f"{name} is no longer in {game.players[hand_of].name}'s hand, "
            "so no copy is made"
        )
    graveyard_of = _graveyard_seat(choice)
    if graveyard_of is not None and 0 <= graveyard_of < len(game.players):
        return (
            f"{name} is no longer in {game.players[graveyard_of].name}'s "
            "graveyard, so it is not cast"
        )
    return f"{name} is no longer exiled, so no copy is made"


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
        game.log.append(f"{game.players[seat].name} did not cast {_what(choice)}")
        game.discard_pending_choice(choice)
        return True
    if not _still_there(game, choice):
        game.log.append(_gone_line(game, choice))
        game.discard_pending_choice(choice)
        return True
    result = _cast_a_copy(
        game, seat, card, str(choice.data.get("source_name") or ""),
        perform=response.get("perform"),
        announcement=dict(response.get("announcement") or {}),
        original=bool(choice.data.get(ORIGINAL)),
        **_graveyard_offer(choice),
    )
    outcome = response.get("outcome")
    if isinstance(outcome, list):
        outcome.append(result)
    if not getattr(result, "supported", False):
        return False
    _take_one_of(game, choice)
    game.discard_pending_choice(choice)
    return True


def _graveyard_offer(choice) -> dict:
    """The keywords :func:`_cast_a_copy` takes for the graveyard offer, or
    none for every other one."""
    graveyard_of = _graveyard_seat(choice)
    if graveyard_of is None:
        return {}
    return {
        "graveyard_of": graveyard_of,
        "exile_instead": bool(choice.data.get(EXILE_INSTEAD)),
    }


def _cast_a_copy(
    game, seat: int, card, source_name: str, *, perform=None, announcement=None,
    choose=None, original: bool = False, graveyard_of: int | None = None,
    exile_instead: bool = False,
):
    """Make the copy, cast it, and clean up whatever the cast did not take.

    *choose*, for a seat nobody asks, is called with ``(copy, permission)``
    and returns the announcement to cast with, or None to decline — so the
    AI weighs the very object it would cast.

    *original* casts *card* itself out of the exile holding it (Shell of the
    Last Kappa): no copy is made and none ceases to exist.

    *graveyard_of* casts *card* itself out of that seat's graveyard, its mana
    cost paid (Toshiro Umezawa), under a permission carrying *exile_instead*."""
    zone = "exile"
    if graveyard_of is not None:
        zone = "graveyard"
        copy = card
        permission = offer_permission(
            game, seat, card, source_name, original=True, zone_seat=graveyard_of,
            zone="graveyard", free=False, exile_instead=exile_instead,
        )
    elif original:
        copy = card
        permission = offer_permission(
            game, seat, card, source_name, original=True,
            zone_seat=_in_exile(game, card),
        )
    else:
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
            keywords["from_zone"] = zone
            name = keywords.pop("card_name", None) or copy.name

            def perform(table):
                return table.queue_from_hand(seat, name, **keywords)

        result = perform(game)
    finally:
        retire_offer(game, permission)
        if (
            not original and graveyard_of is None
            and any(held is copy for held in game.players[seat].exile)
        ):
            cease_to_exist(game, seat, copy)
    if getattr(result, "supported", False):
        what = card.name if (original or graveyard_of is not None) else f"a copy of {card.name}"
        if graveyard_of is not None:
            game.log.append(
                f"{game.players[seat].name} cast {what} from their graveyard "
                f"({source_name})"
            )
        else:
            game.log.append(
                f"{game.players[seat].name} cast {what} without paying its mana "
                f"cost ({source_name})"
            )
    return result


def default_copy_cast_offer(game, choice) -> None:
    """What a seat nobody asks does: the AI's rehearsed cast chooser over the
    copy (``ai_policy.choose_copy_cast``); a cast it would not make, or one the
    engine refuses, declines."""
    from .ai_actions import cast_announcement
    from .ai_payment import tap_planned_lands
    from .ai_policy import choose_copy_cast

    from .ai_rehearsal import rehearsing

    card = choice.data.get("_card")
    seat = choice.player_index
    source_name = str(choice.data.get("source_name") or "")
    # **Inside a rehearsal, one card of a group is weighed.** Each offer of
    # "copy **a** card …" is weighed by rehearsing its cast one level down
    # (``ai_policy.choose_copy_cast``), and a rehearsal of anything with the
    # offering spell on the stack resolves it — so Reversal of Fortune over a
    # hand of three instants and sorceries rehearsed every one of them inside
    # every rehearsal the table made while it waited, and one seeded game ran
    # for over ten minutes. The group is offered best first (most expensive,
    # ``handlers/stack.cast_copy_of_revealed_card``), so a rehearsal weighs
    # that one and declines the rest unweighed; the record is the scratch
    # copy's own, so the real table still weighs every offer.
    #
    # **…and none is weighed a level further down.** A copy weighed one level
    # down (``ai_prompt_picks._one_level_deeper``) may itself offer copies —
    # Reversal of Fortune copying the other player's Reversal of Fortune —
    # and weighing those would be the third level that function promises is
    # never opened: inside a rehearsal already one level down, the offer is
    # declined unweighed, as every prompt of such a rehearsal is answered.
    from .ai_prompt_picks import _DEEPER

    # **A copy of the spell that is offering it is never taken.** Reversal of
    # Fortune shown the other player's Reversal of Fortune may copy it, and
    # the copy — aimed at the same opponent, whose hand still holds the
    # original — offers exactly the same cards again: an optional loop
    # (CR 732.1b; every pass a "may") a seat nobody asks took without end,
    # one seeded game casting copies until it was stopped. Taking it never
    # offers more than declining it and picking from the same hand now, so
    # a seat nobody asks declines it; a person may still loop as long as
    # they like.
    if card is not None and card.name == source_name:
        game.log.append(f"{game.players[seat].name} did not cast {_what(choice)}")
        game.discard_pending_choice(choice)
        return

    one_of = choice.data.get(ONE_OF)
    if rehearsing() and (
        _DEEPER.get() or (isinstance(one_of, dict) and one_of.get("weighed"))
    ):
        game.discard_pending_choice(choice)
        return
    if rehearsing() and isinstance(one_of, dict):
        one_of["weighed"] = True

    def choose(copy, permission):
        action = choose_copy_cast(game, seat, copy, permission)
        if action is None:
            return None
        return cast_announcement(tap_planned_lands(game, seat, action))

    if _still_there(game, choice):
        result = _cast_a_copy(
            game, seat, card, source_name, choose=choose,
            original=bool(choice.data.get(ORIGINAL)),
            **_graveyard_offer(choice),
        )
        if getattr(result, "supported", False):
            _take_one_of(game, choice)
            game.discard_pending_choice(choice)
            return
    game.log.append(f"{game.players[seat].name} did not cast {_what(choice)}")
    game.discard_pending_choice(choice)


__all__ = [
    "COPY_CAST_KIND",
    "COPY_CAST_OFFER",
    "COPY_CAST_PROMPT",
    "FROM_HAND_OF",
    "ONE_OF",
    "ORIGINAL",
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
