"""A named alternative-cost payment is the whole payment, or the spell is not
cast (CR 601.2h: "Partial payments are not allowed").

"You may return two Islands you control to their owner's hand rather than pay
this spell's mana cost" (Gush) owes its caster a choice of *which* two, and the
announcement carries it (``alternative_cost_permanent_ids``). A list naming one
of the two was accepted and the other Island was picked by the engine's
default — the caster paid with a land they did not name. The counted
*additional* cost has refused a short list since Apocalypse
(``_named_cast_cost_refusal``); this is its twin, in
``_resolve_alternative_cost_permanents``.

The census is every card in the pool whose alternative cost takes more than
one permanent, cast three ways: naming one too few (refused, nothing spent),
naming exactly the count (those permanents and no others pay) and naming
nobody (the deterministic default, which the AI and the test corpus stand on).

Before the fix: every one of them accepted the short list.
"""
from __future__ import annotations

from functools import lru_cache

from engine import Game, PlayerState
from engine.alternative_costs import alternative_costs
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_LANDS = ("Forest", "Island", "Swamp", "Mountain", "Plains")


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _counted() -> list[tuple]:
    """``(card, alternative cost, verb, count)`` for every supported card
    whose printed alternative cost takes two or more permanents."""
    found = []
    for unit in compilation_units(_pool().values()):
        if unit.face_of is not None or not compile_card_oracle(unit).supported:
            continue
        for cost in alternative_costs(unit):
            payment = Game.alternative_cost_permanent_payment(cost)
            if payment is not None and payment[1] >= 2:
                found.append((unit, cost, *payment))
    return sorted(found, key=lambda entry: entry[0].name)


def _board(card) -> Game:
    by_name = _pool()
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = True
    for seat in (0, 1):
        for name in _LANDS * 4 + ("Grizzly Bears",) * 4:
            permanent = Permanent(card=by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
        game.players[seat].library.extend([by_name["Forest"]] * 10)
    game.players[0].hand.append(card)
    return game


def _announce(game, card) -> dict:
    spec = game.cast_target_spec(0, card)
    if spec.get("kind") == "stack":
        game.enforce_mana_costs = False
        game.players[1].hand.append(_pool()["Giant Growth"])
        bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
        game.queue_from_hand(1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
        game.enforce_mana_costs = True
        spec = game.cast_target_spec(0, card)
    for entry in spec.get("valid_targets") or []:
        if entry.get("kind") == "permanent" and entry.get("seat") == 1:
            permanent = game.permanent_at(entry["seat"], entry["index"])
            return {
                "target_permanent_ids": [permanent.permanent_id],
                "target_player_index": entry["seat"],
            }
        if entry.get("kind") == "player":
            return {"target_player_index": entry["seat"]}
        if entry.get("kind") == "stack":
            return {"target_stack_index": len(game.stack) - 1 - entry["stack_index"]}
    return {}


def _board_ids(game) -> set[int]:
    return {permanent.permanent_id for permanent in game.controlled_by(0)}


def test_a_short_list_of_alternative_cost_permanents_is_refused():
    population = _counted()
    examined = 0
    topped_up, wrong_payers, default_refused = [], [], []
    for card, cost, verb, count in population:
        # Named in full, and from the far end of the candidate list — the
        # default pick takes the near end, so the two are told apart.
        game = _board(card)
        announcement = _announce(game, card)
        candidates = game._additional_cost_candidates(0, cost, giving_up=verb)
        if len(candidates) < count + 1:
            continue
        named = [permanent.permanent_id for permanent in candidates[-count:]]
        before = _board_ids(game)
        cast = game.queue_from_hand(
            0, card.name, alternative_cost=True,
            alternative_cost_permanent_ids=named, **announcement,
        )
        if not cast.supported:
            continue  # this board cannot cast it for the cost at all
        examined += 1
        if verb != "tap" and before - _board_ids(game) != set(named):
            wrong_payers.append(f"{card.name}: {sorted(before - _board_ids(game))} != {named}")
        if verb == "tap" and {
            p.permanent_id for p in game.controlled_by(0) if p.tapped
        } != set(named):
            wrong_payers.append(f"{card.name}: tapped others than {named}")

        # One too few: half a payment.
        game = _board(card)
        announcement = _announce(game, card)
        candidates = game._additional_cost_candidates(0, cost, giving_up=verb)
        before = (_board_ids(game), len(game.players[0].hand), game.players[0].life)
        short = game.queue_from_hand(
            0, card.name, alternative_cost=True,
            alternative_cost_permanent_ids=[
                permanent.permanent_id for permanent in candidates[-(count - 1):]
            ],
            **announcement,
        )
        after = (_board_ids(game), len(game.players[0].hand), game.players[0].life)
        if short.supported or "CR 601.2h" not in short.details or before != after:
            topped_up.append(f"{card.name} ({verb} {count}): {short.details}")

        # Nobody named: the default, unchanged.
        game = _board(card)
        announcement = _announce(game, card)
        unnamed = game.queue_from_hand(
            0, card.name, alternative_cost=True, **announcement,
        )
        if not unnamed.supported:
            default_refused.append(f"{card.name}: {unnamed.details}")

    assert not topped_up, f"a short list was accepted and filled in: {topped_up}"
    assert not wrong_payers, wrong_payers
    assert not default_refused, default_refused
    # Measured: seven cards (Ensnare, Fireblast, Gush, Pulverize, Thwart, …).
    assert examined >= 5, [entry[0].name for entry in population]
