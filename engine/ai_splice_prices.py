"""What pays a splice cost that is not mana (CR 702.47a, 601.2b, 601.2h), when
an AI seat splices — `ai_splice`'s price half.

"Splice onto Arcane—Sacrifice two Mountains." (Torrent of Stone; and tap an
untapped white creature you control, exile four cards from your graveyard,
an opponent gains 5 life, return a blue creature you control to its owner's
hand — Betrayers of Kamigawa's five.) The seat never spliced one: the chooser
priced a splice in mana only and dropped every such offer, so each was cast
alone.

**What pays is named** (``SpliceChoice.cost_permanent_ids`` /
``cost_graveyard_indices``, the keys of a ``splice_cards`` entry) — CR
601.2b's choice, made here so the rehearsal pays with the objects the cast
will: the engine's own candidates (``Game._additional_cost_candidates``,
``Game._graveyard_exile_candidates``), less what the splices before it
already claimed (one object pays one splice cost, ``splice._settled_price``),
what the spell and its gained texts aim at, and what the spell's own plan
spends:

* a **sacrifice** — the lands this turn has already tapped, and those the
  cast's own plan taps, first (their mana is spent either way); then the
  one cheapest to lose (``ai_sacrifice_victims.cheapest_to_lose``, through
  ``ai_standing.permanent_loss``: a land beyond the ones a seat needs is a
  spare, so a Mountain's lost future mana is priced by how many the seat
  holds);
* a **tap** — the body the seat misses least
  (``ai_mana_sources._spent_on_a_tap_cost_first``: a creature that could not
  attack this turn, then the one worth least), never one the plan taps for
  mana;
* a **return** — the smallest loss (``ai_cast_gates.given_back_first``);
* a **graveyard exile** — the cards least worth keeping there
  (``ai_prompt_readers.graveyard_price_order``: a flashback card last).

**Whether the price is worth paying** is the rehearsal's, which pays it on
the copy (``ai_splice._rehearsed``): the standing reads a sacrificed land and
a returned creature as gone, an opponent's life as theirs, and a tapped
creature's body as missing for the rest of the turn
(``ai_standing.TAPPED_SHARE``) — through the turn's fight for a cast made
before it — so a splice is kept only where what the text adds outweighs it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


def _claimed(chosen: "list[dict]") -> "tuple[set[int], set[int]]":
    """The permanent ids and graveyard slots the splices in *chosen* already
    pay with."""
    ids: set[int] = set()
    slots: set[int] = set()
    for entry in chosen:
        ids.update(each for each in (entry.get("cost_permanent_ids") or ()) if isinstance(each, int))
        slots.update(each for each in (entry.get("cost_graveyard_indices") or ()) if isinstance(each, int))
    return ids, slots


def splice_price_answer(
    game: "Game", seat: int, host: "CardDefinition", current: "CastAction",
    chosen: "list[dict]", spliced: "CardDefinition", offer, *, named: "set[int]",
) -> "dict | str":
    """The keys naming what pays *spliced*'s splice price on *current* (the
    host's cast with *chosen* already spliced), as a ``splice_cards`` entry
    carries them — ``{}`` for a price that names nothing (an opponent's life)
    — or why it cannot be paid. *named* is every permanent the spell and its
    gained texts aim at, by id."""
    price = offer.price
    spell_slot = current.hand_index if current.from_zone == "graveyard" else None
    refusal = game._unpayable_alternative_cost(
        seat, host, price, spell_hand_index=None, spell_graveyard_slot=spell_slot,
    )
    if refusal is not None:
        return f"{spliced.name}'s splice cost cannot be paid: {refusal}"
    player = game.players[seat]
    claimed_ids, claimed_slots = _claimed(chosen)
    if price.pay_life and price.pay_life >= player.life:
        # A life price is never paid with the seat's last point
        # (``ai_casts._announced_candidate``'s rule; no splice card prints
        # one, and two of them would want their sum asked).
        return (
            f"{spliced.name}'s splice cost would spend the seat's last life"
            " (CR 119.4, 704.5a)"
        )
    answer: dict = {}
    demand = game.alternative_cost_permanent_payment(price)
    if demand is not None:
        verb, count = demand
        ids = _permanents_paying(
            game, seat, current, price, verb, count,
            excluded=claimed_ids | set(current.cost_permanent_ids or ()), named=named,
        )
        if ids is None:
            return (
                f"{spliced.name}'s splice cost wants {count} permanent(s) to {verb}"
                " beyond what the spell and its other splices take (CR 601.2h)"
            )
        answer["cost_permanent_ids"] = ids
    if price.exile_graveyard_filter is not None:
        from .ai_prompt_readers import graveyard_price_order

        wanted = price.exiled_from_graveyard(None)
        slots = [
            slot for slot in game._graveyard_exile_candidates(seat, price, spell_slot=spell_slot)
            if slot not in claimed_slots
        ]
        if len(slots) < wanted:
            return (
                f"{spliced.name}'s splice cost exiles {wanted} graveyard card(s) and"
                " fewer are left once the other splices are paid (CR 601.2h)"
            )
        # The engine's own default's order (the top of the pile first between
        # equals), named so the explanation shows it.
        answer["cost_graveyard_indices"] = list(
            graveyard_price_order(game, seat, list(reversed(slots)))
        )[:wanted]
    return answer


def _permanents_paying(
    game: "Game", seat: int, current: "CastAction", price, verb: str, count: int,
    *, excluded: "set[int]", named: "set[int]",
) -> "list[int] | None":
    """The ids of the *count* permanents that pay *price*'s *verb*, in the
    order the module docstring gives, or None when too few can. A permanent
    the spell aims at is used only when nothing else can pay."""
    from .ai_cast_gates import given_back_first
    from .ai_mana_sources import _spent_on_a_tap_cost_first
    from .ai_sacrifice_victims import cheapest_to_lose

    planned = {
        id(permanent) for permanent in (
            game.permanent_at(seat, slot) for slot in (current.land_tap_indices or ())
        ) if permanent is not None
    }
    candidates = [
        permanent
        for permanent in game._additional_cost_candidates(seat, price, giving_up=verb)
        if permanent.permanent_id not in excluded
        # Tapped for this cast's mana: it cannot also be the creature the
        # price taps, and the plan was drawn counting on it.
        and not (verb == "tap" and id(permanent) in planned)
    ]
    if verb == "sacrifice":
        ranked = cheapest_to_lose(game, seat, candidates)
        spent = [p for p in ranked if p.tapped or id(p) in planned]
        ranked = spent + [p for p in ranked if not any(p is s for s in spent)]
    elif verb == "tap":
        ranked = sorted(candidates, key=_spent_on_a_tap_cost_first(game, seat))
    else:
        ranked = given_back_first(candidates, None)
    ranked = [p for p in ranked if p.permanent_id not in named] + [
        p for p in ranked if p.permanent_id in named
    ]
    if len(ranked) < count:
        return None
    return [permanent.permanent_id for permanent in ranked[:count]]


def describe_price_answer(game: "Game", answer: dict) -> str:
    """What *answer* pays with, for an explanation's note."""
    parts = []
    for permanent_id in answer.get("cost_permanent_ids") or ():
        found = game.permanent_by_id(permanent_id)
        parts.append(found.card.name if found is not None else f"#{permanent_id}")
    if answer.get("cost_graveyard_indices"):
        parts.append(f"graveyard cards {answer['cost_graveyard_indices']}")
    return ", ".join(parts) or "nothing named"


__all__ = [
    "describe_price_answer",
    "splice_price_answer",
]
