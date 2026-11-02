"""The order a loop over an announcement's **roles** handles its targets in.

"Choose any number of target players or planeswalkers. For each of them, …"
(Kaboom!). The card's ruling (2022-09-09): "those targets will be handled one
at a time in turn order. Start with targets that are either the player whose
turn it is … or permanents that player controls. **You choose the relative
order of targets within that group.** … After that group is done, move on to
targets that are either the next player in turn order or permanents they
control." The announcement's canonical order is already turn order between
groups (``target_roles.LATER_IN_TURN_ORDER_ROLE``), so what is left to ask is
the order inside one player's group — the player and their planeswalkers, or
two of their planeswalkers — and only where a group holds two or more.

So the loop ``handlers.control_flow.for_each`` walks is, where there is a
choice, ``[ask, the 1st target in the chosen order, the 2nd, …]``: the ask
arms the `target_roles.TARGET_GROUP_ORDER` prompt (CR 608.2: the resolution
waits on it — ``suspends``), and each later step reads the answer off the
resolution's records when it runs. A seat nobody asks answers as the prompt
is armed (``default_at_arm``) with the slot order, so a table with no
interactive seat runs exactly the loop it ran before — and with no group of
two there is no ask at all.

The steps are this module's; the loop, and the body each step runs, are
``for_each``'s.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Callable

from ..target_roles import TARGET_GROUP_ORDER


@dataclasses.dataclass(frozen=True)
class RoleTurn:
    """One turn of a loop over an announcement's **roles** — "Choose any
    number of target players or planeswalkers. For each of them, …" (Kaboom!):
    the role whose object this iteration is about."""

    role: str


@dataclasses.dataclass(frozen=True)
class AskGroupOrder:
    """The step in front of the turns: arm the order prompt over *targets*
    (one entry per live target, in slot order)."""

    targets: tuple


@dataclasses.dataclass(frozen=True)
class OrderedTurn:
    """The turn at *position* in the order the caster chose — *canonical* is
    the role in that position in slot order, the answer where none was
    recorded."""

    position: int
    canonical: str


def role_turns(
    game, context, roles: "list[str]", object_of: Callable[[str], object],
) -> list:
    """The items a loop over *roles* walks: one `RoleTurn` per role, or —
    where one player's group holds two or more live targets — an
    `AskGroupOrder` and one `OrderedTurn` per live target.

    *object_of* names a role's object now (a ``PlayerState`` or a
    ``Permanent``), or None for a role that named nothing or whose object
    CR 608.2b found illegal — which has no turn in either shape."""
    turns = [RoleTurn(role) for role in roles]
    if _seat_of(game, context.caster) is None:
        return turns
    entries = []
    for role in roles:
        obj = object_of(role)
        if obj is None:
            continue
        player_seat = _seat_of(game, obj)
        if player_seat is not None:
            seat, permanent_id, name = player_seat, None, obj.name
        else:
            seat = game.controller_index_of(obj)
            permanent_id = getattr(obj, "permanent_id", None)
            name = obj.card.name
        if seat is None:
            continue
        entries.append({
            "role": role, "seat": seat, "permanent_id": permanent_id,
            "name": name,
            # The group's place from the active player (CR 101.4) — the
            # ruling's "next player in turn order".
            "group": (seat - game.active_player_index) % len(game.players),
        })
    if not any(count > 1 for count in Counter(e["group"] for e in entries).values()):
        return turns
    return [
        AskGroupOrder(tuple(entries)),
        *(OrderedTurn(position, entry["role"]) for position, entry in enumerate(entries)),
    ]


def _seat_of(game, obj) -> "int | None":
    """*obj*'s seat when it is one of *game*'s players — by identity, since a
    ``PlayerState`` compares by value."""
    return next(
        (seat for seat, player in enumerate(game.players) if player is obj), None,
    )


def ask_group_order(game, context, item: AskGroupOrder) -> None:
    """Arm the order prompt for the caster (a seat nobody asks answers it
    there and then, with the slot order)."""
    # The kind spelled out, as every arm site spells it (the registry's
    # "every registered kind is armed" scan reads the literal); it is
    # ``TARGET_GROUP_ORDER``.
    game.arm_pending_choice(
        "target_group_order", _seat_of(game, context.caster),
        card_name=getattr(context.card, "name", ""),
        targets=[dict(entry) for entry in item.targets],
        _context=context,
    )


def ordered_role(context, item: OrderedTurn) -> str:
    """The role *item* is the turn of: the chosen order's entry at its
    position, or the slot order's where nothing was recorded."""
    chosen = context.results.get(TARGET_GROUP_ORDER)
    if isinstance(chosen, list) and 0 <= item.position < len(chosen):
        return str(chosen[item.position])
    return item.canonical


def group_order_refusal(targets: list, order) -> "str | None":
    """Why *order* — indices into the prompt's *targets* — is not an order the
    ruling allows, or None: every target once, and the groups still in turn
    order (only the order *within* a group is the caster's)."""
    if not isinstance(order, list) or sorted(
        index for index in order if isinstance(index, int) and not isinstance(index, bool)
    ) != list(range(len(targets))) or len(order) != len(targets):
        return "name every target once"
    groups = [targets[index]["group"] for index in order]
    if groups != sorted(groups):
        return "each player's group is handled in turn order; only the order within a group is chosen"
    return None


__all__ = [
    "AskGroupOrder",
    "OrderedTurn",
    "RoleTurn",
    "ask_group_order",
    "group_order_refusal",
    "ordered_role",
    "role_turns",
]
