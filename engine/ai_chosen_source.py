"""Which source an AI seat names when its spell asks for "a source of your
choice" (CR 609.7a, 615.8) — and that it names one.

"The next X damage that a source of your choice would deal to you and/or
creatures you control this turn is dealt instead to any target." (Shining
Shoal; and Kor Chant's redirect, Honorable Passage's shield.) The choice is
announced with the cast (``queue_from_hand``'s ``chosen_source_seat`` /
``chosen_source_permanent_index`` / ``chosen_source_stack_index``, read by
``handlers/prevention.chosen_shield_source``) and the seat named none, so its
record fell back to the next damage from **any** source — wider than the
card, in its caster's favour, and invisible to every census because the
fallback is the convenience headless play relies on.

So a spell whose cast spec asks for a source (``requires_source``, the
engine's own derivation, ``targeting.derive_cast_spec``) names one: out of the
engine's own list of what may be chosen (``Game._enumerate_targets`` over
"any permanent or spell", the list a person's source stage offers, CR 609.7a:
not a target, so shroud and protection do not bear on it) the objects another
seat controls — a spell on the stack first (top first: the one about to
resolve), then that seat's creatures in combat, then its other creatures,
the most powerful first — at most :data:`SOURCES_WEIGHED` of them, each
**rehearsed** as the cast it would be (``ai_scoring._rehearse_announcement``,
through the turn's fight where the cast is made before it), and the one its
rehearsal measures most is named. With none of them rehearsed, the first is
named: an object the card names is never worse than the fallback the card
does not print. With no other seat's object to name, nothing is named, and
the cast's own rehearsal finds that it does nothing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import ai_cast_trace as cast_trace

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


#: The most sources weighed for one cast, each a rehearsal.
SOURCES_WEIGHED = 3


def asks_for_a_source(card: "CardDefinition", action: "CastAction") -> bool:
    """Whether *action*'s cast of *card* announces CR 609.7a's chosen source
    (its cast spec's ``requires_source``)."""
    from .oracle import compile_card_oracle
    from .targeting import derive_cast_spec

    if "of your choice" not in (card.oracle_text or "").lower():
        # Asked of every candidate cast: the spec is derived only for a card
        # whose text could ask (CR 609.7a's own words); the spec decides.
        return False
    spec = derive_cast_spec(
        card, compile_card_oracle(card), from_zone=action.from_zone,
        mode_index=action.mode_index,
        optional_cost_payments=action.optional_cost_payments or {},
    )
    return isinstance(spec, dict) and bool(spec.get("requires_source"))


def source_announcements(game: "Game", seat: int, card: "CardDefinition") -> "list[dict]":
    """The chosen-source keywords to weigh for *seat*'s cast of *card*, most
    promising first (the module docstring's order), at most
    :data:`SOURCES_WEIGHED`."""
    listed = game._enumerate_targets(
        seat, card, {"kind": "permanent", "also_stack": True}, for_cast=False,
    )
    spells: list[tuple] = []
    bodies: list[tuple] = []
    for entry in listed:
        if entry.get("kind") == "stack":
            index = entry.get("stack_index")
            if not isinstance(index, int) or not 0 <= index < len(game.stack):
                continue
            if game.stack[index].caster_index == seat:
                continue
            spells.append((-index, {"chosen_source_stack_index": index}))
            continue
        owner = entry.get("seat")
        slot = entry.get("index")
        if owner == seat or not isinstance(owner, int) or not isinstance(slot, int):
            continue
        permanent = game.permanent_at(owner, slot)
        if permanent is None or not permanent.is_creature:
            continue
        fighting = bool(
            permanent.attacking or permanent.blocking_attacker_index is not None
        )
        bodies.append((
            (not fighting, -max(0, permanent.effective_power), slot),
            {"chosen_source_seat": owner, "chosen_source_permanent_index": slot},
        ))
    ranked = [keys for _key, keys in sorted(spells, key=lambda each: each[0])]
    ranked += [keys for _key, keys in sorted(bodies, key=lambda each: each[0])]
    return ranked[:SOURCES_WEIGHED]


def cast_naming_its_source(
    game: "Game", seat: int, card: "CardDefinition", action: "CastAction",
) -> "CastAction":
    """*action* naming the source its spell asks for (the module docstring),
    or *action* as it is for a spell that asks for none, one already named,
    or a table with no other seat's object to name."""
    from .ai_actions import cast_announcement
    from .ai_scoring import _rehearse_announcement, _weighed_through_the_fight

    if (
        action.chosen_source_seat is not None
        or action.chosen_source_stack_index is not None
        or not asks_for_a_source(card, action)
    ):
        return action
    candidates = source_announcements(game, seat, card)
    if not candidates:
        cast_trace.note("no other seat's object to name as the chosen source (CR 609.7a)")
        return action
    best, best_swing = None, None
    for keys in candidates:
        variant = replace(action, **keys)
        rehearsal = _rehearse_announcement(
            game, seat, card, cast_announcement(variant), planned=variant,
        )
        rehearsal = _weighed_through_the_fight(
            game, seat, card, cast_announcement(variant), rehearsal, planned=variant,
        )
        named = _named(game, keys)
        if rehearsal is None or not rehearsal.accepted:
            cast_trace.note(f"chosen source {named}: not rehearsed or refused")
            continue
        cast_trace.note(f"chosen source {named}: swing {rehearsal.swing:+.2f}")
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = variant, rehearsal.swing
    return best if best is not None else replace(action, **candidates[0])


def _named(game: "Game", keys: dict) -> str:
    """The object *keys* name, for an explanation's note."""
    if "chosen_source_stack_index" in keys:
        return f"{game.stack[keys['chosen_source_stack_index']].card.name} (on the stack)"
    found = game.permanent_at(keys["chosen_source_seat"], keys["chosen_source_permanent_index"])
    return found.card.name if found is not None else "a permanent"


__all__ = [
    "SOURCES_WEIGHED",
    "asks_for_a_source",
    "cast_naming_its_source",
    "source_announcements",
]
