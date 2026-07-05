"""Replacement-effect registry (CR 614).

"If X would happen, do Y instead" effects intercept an event before the
default action applies. Each event kind has an ordered interceptor list; an
interceptor inspects the game/payload and either passes (returns None),
modifies the event amount, or consumes the event entirely (the default action
does not happen).

Interceptors self-select from game state (metadata flags, oracle-text
probes), so the registry stays name-free — bespoke per-card registration
belongs in engine/card_hooks.py. Registration order within a kind is the
order interceptors run, mirroring how the inline checks were historically
sequenced.

Event kinds and their payload keys:

- ``life_gain``:          {player, amount, source_name}
- ``damage_to_creature``: {permanent, amount, source}
- ``would_die``:          {player, permanent}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ReplacementOutcome:
    """What an interceptor did to the event.

    replaced   -- True: the event is consumed; the default action must not run.
    new_amount -- when set, the event continues with this amount (partial
                  replacement, e.g. "the next 1 damage ... instead").
    """

    replaced: bool = False
    new_amount: int | None = None


Interceptor = Callable[[Any, dict], Optional[ReplacementOutcome]]

REPLACEMENTS: dict[str, list[Interceptor]] = {}


def replacement_effect(kind: str) -> Callable[[Interceptor], Interceptor]:
    """Register an interceptor for an event kind (run in registration order)."""

    def decorator(fn: Interceptor) -> Interceptor:
        REPLACEMENTS.setdefault(kind, []).append(fn)
        return fn

    return decorator


def apply_replacements(game, kind: str, payload: dict) -> tuple[bool, dict]:
    """Run *kind*'s interceptors over the event.

    Returns ``(consumed, payload)`` — when ``consumed`` is True the caller
    must skip the default action; otherwise ``payload["amount"]`` may have
    been reduced by partial replacements.
    """
    for interceptor in REPLACEMENTS.get(kind, ()):
        outcome = interceptor(game, payload)
        if outcome is None:
            continue
        if outcome.new_amount is not None:
            payload["amount"] = outcome.new_amount
        if outcome.replaced:
            return True, payload
    return False, payload


# ---------------------------------------------------------------------------
# LEA interceptors
# ---------------------------------------------------------------------------

@replacement_effect("life_gain")
def _draw_instead_of_life_gain(game, payload: dict) -> ReplacementOutcome | None:
    """Lich: "If you would gain life, draw that many cards instead."""
    player = payload["player"]
    amount = payload["amount"]
    if not game._player_controls_text(
        player, "if you would gain life, draw that many cards instead"
    ):
        return None
    drawn = player.draw(amount)
    source = f" from {payload['source_name']}" if payload.get("source_name") else ""
    game.log.append(
        f"{player.name} would gain {amount} life{source}; drew {drawn} card(s) instead (Lich)"
    )
    return ReplacementOutcome(replaced=True)


@replacement_effect("damage_to_creature")
def _redirect_damage_to_player(game, payload: dict) -> ReplacementOutcome | None:
    """Jade Monolith: "The next time a source of your choice would deal damage
    to target creature this turn, that source deals that damage to you
    instead." Redirects the whole instance (combat damage included) — but only
    when the damage comes from the chosen source."""
    permanent = payload["permanent"]
    amount = payload["amount"]
    redirect_idx = permanent.metadata.get("redirect_damage_to_player")
    if not (
        isinstance(redirect_idx, int)
        and 0 <= redirect_idx < len(game.players)
        and amount > 0
    ):
        return None
    chosen_source = permanent.metadata.get("redirect_damage_source")
    if not game._damage_source_matches(chosen_source, payload.get("source")):
        return None
    permanent.metadata.pop("redirect_damage_to_player", None)
    permanent.metadata.pop("redirect_damage_source", None)
    game._deal_damage_to_player(game.players[redirect_idx], amount)
    game.log.append(
        f"Damage to {permanent.card.name} redirected to {game.players[redirect_idx].name} (Jade Monolith)"
    )
    return ReplacementOutcome(replaced=True)


@replacement_effect("damage_to_creature")
def _redirect_one_damage_to_owner(game, payload: dict) -> ReplacementOutcome | None:
    """Personal Incarnation: "The next 1 damage that would be dealt to this
    creature this turn is dealt to its owner instead." One point per charge,
    replaced before the rest is marked."""
    permanent = payload["permanent"]
    amount = payload["amount"]
    redirect = int(permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0))
    if not (redirect > 0 and amount > 0):
        return None
    permanent.metadata["redirect_one_damage_to_owner_until_eot"] = redirect - 1
    owner = next((p for p in game.players if permanent in p.battlefield), None)
    if owner is not None:
        game._deal_damage_to_player(owner, 1)
        game.log.append(f"1 damage redirected from {permanent.card.name} to {owner.name}")
    return ReplacementOutcome(new_amount=amount - 1)


@replacement_effect("would_die")
def _exile_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Disintegrate-style: "if it would die this turn, exile it instead." The
    permanent never reaches the graveyard, so no dies-triggers fire (CR 614)."""
    permanent = payload["permanent"]
    if not permanent.metadata.get("exile_if_dies_this_turn"):
        return None
    if not permanent.metadata.get("is_token", False):
        payload["player"].exile.append(permanent.card)
    game.log.append(f"{permanent.card.name} was exiled instead of dying")
    return ReplacementOutcome(replaced=True)
