"""The API's target keywords: **each zone its own** (CR 115.1, CR 400.7).

Every entry point that announces a target — a cast (``queue_from_hand`` /
``cast_from_hand``, a mode of a "choose one or more" cast), an activation
(``activate_permanent_ability``, ``activate_from_graveyard``) and the AI's
actions that become them (``ai_actions.cast_announcement`` /
``activation_announcement``) — names what it targets in the spelling of the
zone the object is in:

* **a permanent, by its id** — ``target_permanent_ids``. CR 400.7 makes the id
  the object for one stay on the battlefield; a battlefield slot renumbers
  under anything that leaves before it, and a slot is a position on *one*
  battlefield, so it cannot say two;
* **a card in a graveyard, by its place in that pile** —
  ``target_graveyard_indices``. A card in a graveyard has no id (two copies of
  one card in one pile are one ``CardDefinition``), and the pile is the one the
  spell's spec reads (``Game.graveyard_target_seat``: the seat named beside the
  slots, else the announcer's own, else what the spec fixes);
* **a card in the ante, by its place there** — ``target_ante_index``.
  "You own target card in the ante" (Darkpact): the spec is ``"kind": "none"``
  — nothing is offered, so a picker never shows it — and the handler
  (``handlers/ownership.exchange_ante_with_top_library``) reads the slot.

**Behind the boundary the announcement gates read one slot beside the ids**
(``cast_target_validation``, ``legality_cast_gates``, ``legality_abilities``,
the per-target taxes): an Aura's enchant target, a graveyard card, a destroy
arm's named permanent. :func:`announced_slot` derives that slot here, once, at
the moment the board and the announcement agree — the translation
``web/actions.py`` made at the top of every request, made by the engine for
every caller.

``target_permanent_index`` — the keyword every entry point took before these:
one slot whose *zone* the card's spec decided (a battlefield slot on the named
seat, a graveyard slot, an ante slot), in either arity — is still accepted,
unchanged, as **the tests' adapter**. No module in ``engine/`` or ``web/``
passes it to an entry point (``tests/engine/test_kg5_ids_target_keywords.py``
holds that), and a call naming it beside one of the zone keywords is refused:
one target said twice, in two spellings, is two answers to one question.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game

#: The zones a target keyword names.
BATTLEFIELD = "battlefield"
GRAVEYARD = "graveyard"
ANTE = "ante"

#: The instruction kinds whose announced slot is **a card in the ante**. A kind,
#: never a card: "You own target card in the ante. Exchange that card with the
#: top card of your library." (Darkpact) is the pool's one printing, and its
#: handler is the reader.
ANTE_TARGET_KINDS = frozenset({"exchange_ante_with_top_library"})

#: The ``StackItem.choices`` key an announced ante card rides to resolution
#: (``game_types.CHOICE_KEYS``): the slot channel is a battlefield's, consumed
#: into ids at the push, so an ante slot left there never reached its handler.
ANTE_INDEX = "ante_index"

#: The keywords, by the zone each names (the legacy ``target_permanent_index``
#: names whichever the spec says).
ZONE_KEYWORDS = {
    BATTLEFIELD: "target_permanent_ids",
    GRAVEYARD: "target_graveyard_indices",
    ANTE: "target_ante_index",
}


def _names_ante(instructions) -> bool:
    for instruction in instructions or ():
        if instruction is None:
            continue
        if instruction.kind in ANTE_TARGET_KINDS:
            return True
        payload = getattr(instruction, "payload", None) or {}
        if _names_ante(payload.get("steps") or ()):
            return True
    return False


def cast_target_zone(card, *, mode_index: int | None = None) -> str:
    """The zone a cast of *card* (announcing *mode_index*) names its target
    in: a graveyard where its spec addresses one (``graveyard_target_spec`` —
    Raise Dead, Animate Dead's enchant, Gravedigger's entry trigger), the ante
    where its effect reads an ante slot (Darkpact), else the battlefield."""
    # Imported here: the handlers read this module's key, and the compiler
    # imports the handlers.
    from .oracle import compile_card_oracle
    from .targeting import graveyard_target_spec

    program = compile_card_oracle(card)
    if graveyard_target_spec(card, program, mode_index=mode_index) is not None:
        return GRAVEYARD
    if _names_ante(program.instructions):
        return ANTE
    return BATTLEFIELD


def ability_target_zone(ability) -> str:
    """:func:`cast_target_zone` for an activated ability, read off the
    ability's own spec (``derive_activation_spec``) — the question
    ``_activate_onto_stack`` asks before it reads a bare slot as a seat's."""
    from .target_descriptions import GRAVEYARD_TARGET_KIND
    from .targeting import derive_activation_spec

    spec = derive_activation_spec(ability) or {}
    if spec.get("kind") == GRAVEYARD_TARGET_KIND:
        return GRAVEYARD
    if _names_ante((getattr(ability, "instruction", None),)):
        return ANTE
    return BATTLEFIELD


def _one_or_several(slots: list):
    """A slot list in the announcement's arity: one slot bare, several (or
    none) as the list — the shape every caller's slot always arrived in."""
    return slots[0] if len(slots) == 1 else list(slots)


def slot_from_ids(game: "Game", permanent_ids, seat=None):
    """``(seat, slot)``: the battlefield seat and slot(s) *permanent_ids* name
    **now**, or None where they do not settle one.

    Positional — an entry that is not an id (a player's or a spell's place in
    a roles announcement) is a ``None`` slot — and only where every id names
    a live permanent and all of them stand on **one** battlefield, the one
    *seat* names when it names one: a slot is a position on one board, so a
    pair of targets on two (Garruk, Savage Herald's -2) or a seat beside the
    ids naming another board (a player the spell also targets) has no slot to
    derive, and is read by its ids alone, as it always was.
    """
    listed = list(permanent_ids or ())
    if not any(isinstance(pid, int) and not isinstance(pid, bool) for pid in listed):
        return None
    seats: set = set()
    slots: list = []
    for pid in listed:
        if not isinstance(pid, int) or isinstance(pid, bool):
            slots.append(None)
            continue
        found = game.find_permanent_by_id(pid)
        if found is None:
            return None
        found_seat, permanent = found
        seats.add(found_seat)
        slots.append(game.battlefield_index_of(permanent))
    if len(seats) != 1:
        return None
    board = seats.pop()
    if seat is not None and seat != board:
        return None
    return board, _one_or_several(slots)


def announced_slot(
    game: "Game", zone: str, *, name: str,
    target_player_index=None, target_permanent_index=None,
    target_permanent_ids=None, target_graveyard_indices=None,
    target_ante_index=None,
):
    """The announcement in the form the gates behind the boundary read:
    ``(target_player_index, target_permanent_index, refusal)``.

    *zone* is the zone the spell or ability names its target in
    (:func:`cast_target_zone` / :func:`ability_target_zone`) and *name* the
    card, for a refusal's words. A refusal is the reason the announcement
    cannot be carried out — a keyword for a zone the target is not in, or one
    target said in two spellings — and the slot fields are then unchanged.

    * ``target_graveyard_indices`` / ``target_ante_index`` become the slot;
    * ``target_permanent_ids`` alone (no slot beside it) gives the slot the
      ids name now and, where no seat was named, the board they stand on
      (:func:`slot_from_ids`) — ids naming nothing on one board leave the slot
      unset, read by their ids;
    * ``target_permanent_index`` — the legacy keyword — passes unchanged.
    """
    seat, slot = target_player_index, target_permanent_index
    spelled = [
        keyword for keyword, value in (
            ("target_graveyard_indices", target_graveyard_indices),
            ("target_ante_index", target_ante_index),
        )
        if value is not None
    ]
    if len(spelled) > 1 or (spelled and slot is not None):
        return seat, slot, (
            f"{name}: one target is named once — "
            f"{' and '.join(spelled + (['target_permanent_index'] if slot is not None else []))}"
            " name it twice"
        )
    named_ids = [
        pid for pid in (target_permanent_ids or ())
        if isinstance(pid, int) and not isinstance(pid, bool)
    ]
    if target_graveyard_indices is not None:
        if zone != GRAVEYARD:
            return seat, slot, f"{name} targets no card in a graveyard"
        if named_ids:
            return seat, slot, (
                f"{name}: a card in a graveyard has no permanent id — name it "
                "by its place in the pile (target_graveyard_indices)"
            )
        return seat, _one_or_several(list(target_graveyard_indices)), None
    if target_ante_index is not None:
        if zone != ANTE:
            return seat, slot, f"{name} targets no card in the ante"
        return seat, target_ante_index, None
    if slot is None and named_ids:
        if zone != BATTLEFIELD:
            return seat, slot, (
                f"{name}: its target is a card in the {zone}, which has no "
                f"permanent id — name it with {ZONE_KEYWORDS[zone]}"
            )
        derived = slot_from_ids(game, target_permanent_ids, seat)
        if derived is not None:
            seat, slot = derived
    return seat, slot, None


def slot_keywords(game: "Game", zone: str, announcer: int, seat, slot, ids=None) -> dict:
    """A target given as a picker gives it — *slot* (one, or a list) on
    *seat*'s battlefield or in its pile, and any *ids* already held — as the
    zone keywords an entry point takes: ``target_graveyard_indices`` for a card
    in a graveyard, ``target_ante_index`` for one in the ante, and
    ``target_permanent_ids`` for a permanent — the ids held, else the id of
    what stands in each slot **now** (None for a slot that holds nothing,
    which the caller refuses or announces as named nothing).

    The one translation from a slot to an announcement, for the two callers
    that still hold slots: the AI's choosers, which read the picker's entries
    (``ai_actions.target_keywords``), and the wire's old slot fields, accepted
    for one more round (``web/action_helpers.wire_target_keywords``). A slot
    named beside no seat counts into the board the gates always read it on
    (``bare_announcements.seat_of_unseated_slot``).
    """
    from .bare_announcements import seat_of_unseated_slot
    from .game_types import target_slots

    if zone == GRAVEYARD:
        return {"target_graveyard_indices": None if slot is None else target_slots(slot)}
    if zone == ANTE:
        return {"target_ante_index": None if slot is None else target_slots(slot)[0]}
    if ids and any(isinstance(pid, int) and not isinstance(pid, bool) for pid in ids):
        return {"target_permanent_ids": list(ids)}
    if slot is None:
        return {"target_permanent_ids": None}
    slots = target_slots(slot)
    if not slots:
        return {"target_permanent_ids": []}
    board = seat
    if board is None:
        default = 1 - announcer if len(game.players) == 2 else announcer
        board = seat_of_unseated_slot(game, announcer, slots[0], default)
        board = default if board is None else board
    named = [game.permanent_at(board, index) for index in slots]
    return {"target_permanent_ids": [
        None if permanent is None else permanent.permanent_id for permanent in named
    ]}
