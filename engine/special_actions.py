"""CR 116 special actions — what a player may do with priority without the stack.

CR 116.1: "Special actions are actions a player may take when they have priority
that don't use the stack." There are twelve, and this engine implements two of
them. The land drop (CR 116.2a) is the older one and lives where it has always
lived — `Game._land_play_refusal` plus the play path — because moving it is a
refactor over every land in the pool rather than a card's work; this module is
the seam every *other* special action arrives on, and the land drop's home is
named here so the pair is findable.

The one it opens with is CR 116.2e, which is the only rule in the CR that names
a card:

    One card (Circling Vultures) has the ability "You may discard Circling
    Vultures any time you could cast an instant." Doing so is a special action.
    A player can take such an action any time they have priority.

**Text-keyed rather than name-keyed**, even though the rule itself names the
card. What the entry bar in `card_hooks.py` asks is whether a second card, real
or plausibly printable, could share the *shape* — and a sentence of the form
"you may <do this> any time you could cast an instant" is a shape, not a card.
The name in the CR is a fact about the printing history; the sentence is the
thing the engine reads.

Three properties follow, and each is load-bearing:

* **It does not use the stack** (CR 116.1), so there is no instruction to
  compile and no handler to dispatch. That is why the support gate reads this
  table directly (`oracle._derived_static_claims`) — without the row, a card
  whose only other text is a keyword and an upkeep trigger reports unsupported
  however well the action works.
* **It needs priority and nothing else** (CR 116.2e). "Any time you could cast
  an instant" is the printed spelling of exactly that, and it is *not*
  `cast_timing.casts_at_instant_speed`: that function answers about a card
  being cast, and nothing here is cast. What it means is CR 117.1's priority,
  which is what :func:`special_action_refusal` asks.
* **The player receives priority afterward** (CR 116.3), so the action neither
  passes priority nor advances a step. A caller that treated it as a play would
  hand the turn on.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition


#: The kind of special action a printed sentence grants, keyed by the sentence.
#: One row today; a second goes here beside it rather than in a branch, for the
#: reason every derivation table in this engine is a table.
#:
#: The pattern reads "this card", which is how Oracle prints the self-reference
#: and therefore how the ingest carries it. The CR quotes the older wording with
#: the card's name in it, and that spelling is deliberately **not** an
#: alternative here: no card file contains it, so the arm would be dead — and a
#: name in a comparison is dispatch, which `tests/engine/test_card_name_reads.py`
#: allows only in `card_hooks.py`. A card whose printing did spell its own name
#: would arrive through `oracle._collapse_self_references` like every other
#: self-naming card in the pool.
_SPECIAL_ACTION_LINES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^you may discard this card any time you could cast an instant$"
        ),
        "discard_from_hand",
    ),
)


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower().rstrip(".")


def special_action_line(line: str) -> str | None:
    """The special action *line* grants, as its kind, or None.

    Matched on the whole sentence rather than as a substring, for the reason
    `cast_costs.additional_cost_for_line` is: a substring match is how a
    whitelist comes to claim text it does not implement.

    Read by the support gate **and** by `scripts/parse_coverage.py`, so what
    the engine implements and what it claims to have read cannot drift — the
    same seam `enter_effects.enter_effect_line` is.
    """
    normalized = _normalize(line)
    for pattern, kind in _SPECIAL_ACTION_LINES:
        if pattern.match(normalized):
            return kind
    return None


def special_actions_for(card: "CardDefinition") -> tuple[str, ...]:
    """Every special action *card*'s own text grants, in printed order."""
    return tuple(
        kind
        for line in (getattr(card, "oracle_text", "") or "").splitlines()
        if (kind := special_action_line(line)) is not None
    )


def special_action_refusal(
    game: "Game", seat: int, card: "CardDefinition", kind: str
) -> str | None:
    """Why *seat* may not take *kind* with *card* right now, or None.

    One gate, asked by the engine before it acts and by the web layer before it
    offers — the same arrangement `legality.activation_target_refusal` makes,
    and for the same reason: an action the client offers and the engine refuses
    is a button that does nothing.

    The timing is CR 116.2e's "any time they have priority", which is CR 117.1's
    priority and not CR 601.3d's sorcery window. A seat with no priority at all
    (`priority_player_index is None`) is refused: that is a turn-based action
    running or the game not started, and neither is a moment a player may act.
    """
    if kind not in special_actions_for(card):
        return f"{card.name} has no such special action"
    if not any(held is card for held in game.players[seat].hand):
        return f"{card.name} is not in {game.players[seat].name}'s hand"
    if not game.has_priority(seat):
        return f"{game.players[seat].name} does not have priority"
    return None


def take_special_action(
    game: "Game", seat: int, card: "CardDefinition", kind: str
) -> str | None:
    """Perform *kind* with *card* for *seat*; returns a refusal, or None on
    success.

    CR 116.3 gives the player priority again afterwards, which here means the
    action does **not** touch `priority_player_index`, advance a step or pass —
    a caller treating this as a play would hand the turn on.
    """
    refusal = special_action_refusal(game, seat, card, kind)
    if refusal is not None:
        return refusal
    player = game.players[seat]
    if kind == "discard_from_hand":
        # Two seams, and both are load-bearing. ``take_card_from_hand`` removes
        # exactly **one** copy by identity: a deck repeats one immutable
        # ``CardDefinition`` per copy, so an identity *filter* over the hand
        # would delete every copy where this then files one.
        # ``put_card_into_graveyard`` is CR 614's event ("if a card would be
        # put into your graveyard from anywhere", Forbidden Crypt) — a bare
        # append would skip every replacement over it, which is the class
        # `tests/engine/test_graveyard_seam.py` exists to catch and did catch
        # here.
        game.take_card_from_hand(player, card)
        arrived = game.put_card_into_graveyard(player, card)
        game.log.append(
            f"{player.name} discarded {card.name} (CR 116.2e special action)"
            if arrived
            else f"{player.name} discarded {card.name}, and it was diverted"
        )
        return None
    return f"no special action named {kind!r}"


def available_special_actions(game: "Game", seat: int) -> list[dict]:
    """What *seat* may currently do as a special action, one entry per (card,
    kind) — the shape `cast_permissions.playable_from_zones` has, and for the
    same reason: the client needs to know which hand card to badge, and asking
    the same gate the action asks is what stops the two disagreeing.
    """
    entries: list[dict] = []
    for index, card in enumerate(game.players[seat].hand):
        for kind in special_actions_for(card):
            if special_action_refusal(game, seat, card, kind) is None:
                entries.append(
                    {"hand_index": index, "name": card.name, "kind": kind}
                )
    return entries


__all__ = [
    "available_special_actions",
    "special_action_line",
    "special_action_refusal",
    "special_actions_for",
    "take_special_action",
]
