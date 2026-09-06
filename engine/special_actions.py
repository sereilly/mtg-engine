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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .models import CardDefinition, Permanent


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



# ---------------------------------------------------------------------------
# CR 116.2c / 116.2d — an offer a *permanent* makes, taken from the battlefield
# ---------------------------------------------------------------------------
#
# The row above is about a card in a **hand**. These two subrules are about
# something already on the battlefield, and they are why this file is a seam
# rather than one card's exception:
#
#   116.2c  Some effects allow a player to take an action at a later time,
#           usually to end a continuous effect … Doing so is a special action.
#   116.2d  Some effects from static abilities allow a player to take an action
#           to ignore the effect from that ability for a duration.
#
# Tempest prints both. Every Licid ends its own type change with "You may pay
# {C} to end this effect" (116.2c) and Volrath's Curse lets the *enchanted*
# creature's controller buy a turn off its restriction (116.2d) — two cards,
# one rule, and neither of them a trigger, an activated ability or anything
# else that uses the stack. A `PendingChoice` is the wrong shape for both: that
# queue is a decision somebody **owes**, and this is a decision that simply
# stands, for as long as the effect does, and may never be taken at all.

#: The sentence a permanent prints to make one of these offers, and the kind of
#: offer it is. Matched against a whole **sentence** rather than a whole line,
#: because a Licid prints its offer as the third sentence of an activated
#: ability's line — where the two before it are the effect the offer undoes.
_PERMANENT_ACTION_SENTENCES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^you may pay (?P<cost>(?:\{[^}]+\})+) to end this effect$"),
        "end_own_continuous_effect",
    ),
)


@dataclass(frozen=True)
class PermanentSpecialAction:
    """One kind of battlefield offer, and the two questions it answers.

    ``offer`` is what *permanent* is offering **right now**, as the mana cost of
    taking it, or None when it is making no such offer. One question rather than
    a separate "is it open?" and "what does it cost?", because CR 116.2c's offer
    is made by an **effect** and not by a card: the sentence table above says
    which sentence *creates* one, and by the time a Licid's offer can be taken
    the sentence has gone from the permanent's text — CR 613 layer 6 took the
    whole ability away, which is the other half of what the ability did. The
    effect outlives its ability (CR 611.2a), and so does the offer.

    ``take`` performs it, with the cost already paid.

    A registration rather than a branch, for this file's own stated reason: the
    sentence table says what a card *offers* and this says what the engine
    *does about it*, and a kind in one without the other is either an offer
    nothing performs or a performance nothing offers.
    """

    kind: str
    offer: "Callable[[Game, Permanent], dict[str, int] | None]"
    take: "Callable[[Game, int, Permanent], None]"


#: Registered by the modules that create the effects these offers end.
#: `engine/auras.py` holds the only entry today — it owns the record a
#: became-an-Aura permanent carries, so it is the only place that can say
#: whether the effect is still running or take it back.
PERMANENT_SPECIAL_ACTIONS: dict[str, PermanentSpecialAction] = {}


def register_permanent_special_action(spec: PermanentSpecialAction) -> None:
    """Register *spec*. A duplicate kind raises at import, as every other
    registry in this engine does."""
    if spec.kind in PERMANENT_SPECIAL_ACTIONS:
        raise ValueError(f"duplicate permanent special action {spec.kind!r}")
    PERMANENT_SPECIAL_ACTIONS[spec.kind] = spec


def _load_registrations() -> None:
    """Import the modules that register the offers above.

    Function-level and idempotent: this module imports nothing from the engine
    at module scope (which is what lets `engine/oracle.py` import it from the
    top), and the registry would otherwise be empty for any caller that had not
    happened to import `engine/auras.py` first — an offer that exists or not
    depending on import order.
    """
    from . import auras  # noqa: F401


def _split_sentences(line: str) -> list[str]:
    """*line* split on the full stops that end its sentences.

    Naive on purpose: a mana symbol carries no full stop and neither does any
    number in this pool, so splitting on "." is exact for the sentences the
    table above reads. A printing that broke that would fail to match and leave
    its card unsupported, which is the direction every reader in this file
    fails in.
    """
    return [part.strip() for part in (line or "").split(".") if part.strip()]


def permanent_special_action_sentence(
    sentence: str,
) -> "tuple[str, dict[str, int]] | None":
    """The ``(kind, mana cost)`` one printed *sentence* offers, or None.

    Matched whole, for :func:`special_action_line`'s reason: a substring match
    is how a whitelist comes to claim text it does not implement.

    Read by the support gate, by `scripts/parse_coverage.py` and by the offer
    enumerator below — so what the engine claims to have read and what it
    actually offers are one table.
    """
    from .mana_payment import mana_cost_from_symbols

    normalized = _normalize(sentence).rstrip(".")
    for pattern, kind in _PERMANENT_ACTION_SENTENCES:
        match = pattern.match(normalized)
        if match is None:
            continue
        cost = mana_cost_from_symbols(match.group("cost").upper())
        if cost is None:
            return None
        return kind, cost
    return None


def permanent_special_action_line(line: str) -> str | None:
    """The kind of offer *line* carries, or None — asked of a whole printed
    line rather than of one sentence.

    A Licid's offer is the last sentence of an activated ability's line, so the
    line is split here and every sentence asked. The support gate and the
    grammar's sentence reader both come through this, which is what keeps the
    claim and the offer describing the same words.
    """
    for sentence in _split_sentences(line):
        found = permanent_special_action_sentence(sentence)
        if found is not None:
            return found[0]
    return None


def permanent_special_actions_for(
    card: "CardDefinition",
) -> "tuple[tuple[str, dict[str, int]], ...]":
    """Every offer *card*'s own text makes, in printed order."""
    return tuple(
        found
        for line in (getattr(card, "oracle_text", "") or "").splitlines()
        for sentence in _split_sentences(line)
        if (found := permanent_special_action_sentence(sentence)) is not None
    )


def _payment_plan(game: "Game", seat: int, cost: "dict[str, int]"):
    """How *seat* would pay *cost*, or None.

    Over the pool **and** the seat's untapped lands. CR 116.2c gives the player
    priority for this, so they could have tapped for mana first — which is
    exactly what this plan does on their behalf, through the one reader every
    other "you may pay" in this engine goes through
    (``mana_payment.plan_payment``).
    """
    from .mana_payment import plan_payment, untapped_mana_lands

    if not any(cost.values()):
        return {}
    return plan_payment(
        game.players[seat].mana_pool,
        untapped_mana_lands(game.controlled_by(seat)),
        cost,
        produces=game._land_payment_colors,
    )


def permanent_special_action_refusal(
    game: "Game", seat: int, permanent: "Permanent", kind: str
) -> str | None:
    """Why *seat* may not take *kind* with *permanent* right now, or None.

    The battlefield twin of :func:`special_action_refusal`, asked by the engine
    before it acts and by the web layer before it offers — the same arrangement,
    and the same reason.

    Four questions, and the first is what a hand card has no equivalent of: the
    permanent must still be making the offer (CR 116.2c's "for as long as the
    effect allows it"), which is asked of the registered offer rather than of
    the card's text — see :class:`PermanentSpecialAction`.
    """
    _load_registrations()
    spec = PERMANENT_SPECIAL_ACTIONS.get(kind)
    if spec is None:
        return f"no special action named {kind!r}"
    if not game.is_on_battlefield(permanent):
        return f"{permanent.card.name} is no longer on the battlefield"
    cost = spec.offer(game, permanent)
    if cost is None:
        return f"{permanent.card.name} is not making that offer"
    if game.controller_index_of(permanent) != seat:
        return f"{game.players[seat].name} does not control {permanent.card.name}"
    if not game.has_priority(seat):
        return f"{game.players[seat].name} does not have priority"
    if _payment_plan(game, seat, cost) is None:
        return f"{game.players[seat].name} can't pay for it"
    return None


def take_permanent_special_action(
    game: "Game", seat: int, permanent: "Permanent", kind: str
) -> str | None:
    """Perform *kind* with *permanent* for *seat*; a refusal, or None on success.

    CR 116.3 again: the player receives priority afterwards, so nothing here
    passes, advances a step or touches ``priority_player_index``.
    """
    refusal = permanent_special_action_refusal(game, seat, permanent, kind)
    if refusal is not None:
        return refusal
    spec = PERMANENT_SPECIAL_ACTIONS[kind]
    plan = _payment_plan(game, seat, spec.offer(game, permanent) or {})
    if plan:
        game._spend_payment_plan(game.players[seat], plan)
    spec.take(game, seat, permanent)
    return None


def available_permanent_special_actions(game: "Game", seat: int) -> list[dict]:
    """What *seat* may currently do with a permanent, one entry per
    (permanent, kind) — the battlefield half of
    :func:`available_special_actions`.

    Addressed by ``permanent_id`` rather than by a battlefield slot, for the
    reason every other wire-borne permanent reference in this engine is: a slot
    renumbers the moment anything leaves (CR 400.7).
    """
    _load_registrations()
    entries: list[dict] = []
    for permanent in game.controlled_by(seat):
        for kind in PERMANENT_SPECIAL_ACTIONS:
            if permanent_special_action_refusal(game, seat, permanent, kind) is None:
                entries.append({
                    "permanent_id": permanent.permanent_id,
                    "name": permanent.card.name,
                    "kind": kind,
                })
    return entries


__all__ = [
    "PERMANENT_SPECIAL_ACTIONS",
    "PermanentSpecialAction",
    "available_permanent_special_actions",
    "available_special_actions",
    "permanent_special_action_line",
    "permanent_special_action_refusal",
    "permanent_special_action_sentence",
    "permanent_special_actions_for",
    "register_permanent_special_action",
    "take_permanent_special_action",
    "special_action_line",
    "special_action_refusal",
    "special_actions_for",
    "take_special_action",
]
