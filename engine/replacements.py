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
- ``damage_to_player``:   {player, amount}
- ``would_die``:          {player, permanent}
- ``discard``:            {player, card}
- ``draw``:               {player, count, drawn}

The last two are *interactive*: their interceptors offer a
:class:`~engine.replacement_choices.ReplacementChoice` rather than applying
the effect outright, and report what they did through ``payload["drawn"]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)


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

# The oracle phrases these interceptors self-select on. Named constants rather
# than inline literals because a second reader now needs the *exact* string:
# engine/grammar/registries.py claims these lines for the grammar on the
# strength of this file implementing them. A copy over there would be free to
# drift, and a drifted copy would claim a line nothing implements — the silence
# the grammar's full-consumption invariant exists to remove.
LIFE_GAIN_TO_DRAW_TEXT = "if you would gain life, draw that many cards instead"
DAMAGE_LIFE_FLOOR_TEXT = (
    "damage that would reduce your life total to less than 1 reduces it to 1 instead"
)


@replacement_effect("life_gain")
def _draw_instead_of_life_gain(game, payload: dict) -> ReplacementOutcome | None:
    """Lich: "If you would gain life, draw that many cards instead."""
    player = payload["player"]
    amount = payload["amount"]
    if not game._player_controls_text(player, LIFE_GAIN_TO_DRAW_TEXT):
        return None
    drawn = player.draw(amount)
    source = f" from {payload['source_name']}" if payload.get("source_name") else ""
    game.log.append(
        f"{player.name} would gain {amount} life{source}; drew {drawn} card(s) instead (Lich)"
    )
    return ReplacementOutcome(replaced=True)


@replacement_effect("damage_to_player")
def _floor_life_at_one(game, payload: dict) -> ReplacementOutcome | None:
    """Ali from Cairo: "Damage that would reduce your life total to less than
    1 reduces it to 1 instead." Clamped via new_amount (the damage instance
    still "happened" for tracking purposes; only how much it reduces life is
    capped), matching how Personal Incarnation's partial redirect already
    treats amount adjustments."""
    player = payload["player"]
    amount = payload["amount"]
    if amount <= 0:
        return None
    if not game._player_controls_text(player, DAMAGE_LIFE_FLOOR_TEXT):
        return None
    floor_amount = max(0, player.life - 1)
    if floor_amount >= amount:
        return None
    return ReplacementOutcome(new_amount=floor_amount)


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


def _is_desert(source) -> bool:
    card = getattr(source, "card", source)
    return (
        card is not None
        and getattr(card, "primary_type", None) == "land"
        and "desert" in card.type_line.lower()
    )


_CAMEL_SHIELD_TEXT = "prevent all damage deserts would deal to this creature"


def _banded_desert_shield(game, permanent) -> bool:
    """Camel's second clause: the shield also covers "creatures banded with
    this creature". Bands are only declared for the attacking player, so find
    the damaged creature's attacker index and scan its band for an attacking
    Camel.

    The band lasts for the rest of combat (CR 702.22e) and attacking creatures
    stay attacking until the end of combat step ends (CR 511.3), so the shield
    still covers a band-mate targeted by a Desert during that step.

    The index lookup is by identity: Permanent is a plain dataclass, so
    ``list.index`` compares field-by-field and would return a *different*,
    identically-stated attacker — losing the shield on the creature that
    actually is in the band.
    """
    if not permanent.attacking:
        return False
    for player in game.players:
        index = next(
            (i for i, perm in enumerate(player.battlefield) if perm is permanent), None
        )
        if index is None:
            continue
        band = game._attacker_band(index)
        if not band:
            return False
        for other in band:
            if other == index or not (0 <= other < len(player.battlefield)):
                continue
            mate = player.battlefield[other]
            if mate.attacking and _CAMEL_SHIELD_TEXT in (mate.card.oracle_text or "").lower():
                return True
        return False
    return False


@replacement_effect("damage_to_creature")
def _prevent_desert_damage(game, payload: dict) -> ReplacementOutcome | None:
    """Desert Nomads: "Prevent all damage that would be dealt to this
    creature by Deserts." / Camel: same shield while attacking, extended to
    creatures banded with it. Checked against oracle text directly (like
    Lich's life-gain replacement) rather than a compiled instruction."""
    permanent = payload["permanent"]
    if not _is_desert(payload.get("source")):
        return None
    text = (permanent.card.oracle_text or "").lower()
    if "prevent all damage that would be dealt to this creature by deserts" in text:
        return ReplacementOutcome(replaced=True)
    if _CAMEL_SHIELD_TEXT in text and permanent.attacking:
        return ReplacementOutcome(replaced=True)
    if _banded_desert_shield(game, permanent):
        return ReplacementOutcome(replaced=True)
    return None


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


# ---------------------------------------------------------------------------
# Interactive replacements (CR 614 + engine/replacement_choices.py)
#
# Each of these is optional or offers a choice, so it cannot simply mutate the
# event: it offers a ReplacementChoice and the paired resolver finishes the job
# once the chooser answers (immediately, for a non-interactive seat).
# ---------------------------------------------------------------------------

TOP_OF_LIBRARY_DISCARD_TEXT = (
    "if an effect causes you to discard a card, discard it, but you may put it "
    "on top of your library instead"
)


@replacement_effect("discard")
def _top_of_library_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Library of Leng: "If an effect causes you to discard a card, discard it,
    but you may put it on top of your library instead of into your graveyard."

    The discarded card is in no zone until the choice is answered — it has left
    the hand and its destination is still undecided (CR 701.9c)."""
    player = payload["player"]
    if not game._player_controls_text(player, TOP_OF_LIBRARY_DISCARD_TEXT):
        return None
    card = payload["card"]
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="leng_discard",
            player_index=game.players.index(player),
            options=("top of library", "graveyard"),
            default_option=0,
            data={"card": card},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} discarded {card.name} — Library of Leng: "
            "choose graveyard or top of library"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("leng_discard")
def _resolve_leng_discard(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    card = choice.data["card"]
    if option_index == 0:
        player.library.insert(0, card)
        game.log.append(
            f"{player.name} put discarded {card.name} on top of their library (Library of Leng)"
        )
    else:
        player.graveyard.append(card)
        game.log.append(f"{player.name} put discarded {card.name} into their graveyard")
    return 0


@replacement_effect("draw")
def _draw_from_outside_the_game(game, payload: dict) -> ReplacementOutcome | None:
    """Ring of Ma'rûf: the next draw is replaced by putting a card you own from
    outside the game into your hand.

    Nothing is drawn from the library, so this reports 0 cards drawn and a
    "whenever you draw a card" effect correctly sees no draw. With no eligible
    card there is nothing to take and the replacement is spent anyway
    (CR 614.1). CR 407.3 keeps ante cards out of a game not played for ante.
    """
    player = payload["player"]
    player_index = game.players.index(player)
    if player_index not in game.outside_game_draw_replacements:
        return None
    game.outside_game_draw_replacements.discard(player_index)
    available = game._outside_game_choices(player_index)
    remaining = payload["count"] - 1
    if not available:
        game.log.append(
            f"{player.name} has no cards outside the game to take (Ring of Ma'rûf)"
        )
        if remaining > 0:
            player.draw(remaining)
        payload["drawn"] = 0
        return ReplacementOutcome(replaced=True)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="outside_game_draw",
            player_index=player_index,
            options=tuple(player.sideboard[i].name for i in available),
            default_option=0,
            # Sideboard positions behind each offered name, so a choice made
            # against the filtered list still pulls the right card.
            data={"sideboard_indices": available, "remaining_draws": remaining},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks through the cards they own from outside the game (Ring of Ma'rûf)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("outside_game_draw")
def _resolve_outside_game_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    indices = choice.data.get("sideboard_indices") or list(range(len(choice.options)))
    game._finish_outside_game_draw(choice.player_index, indices[option_index])
    remaining = int(choice.data.get("remaining_draws", 0))
    if remaining > 0:
        game.players[choice.player_index].draw(remaining)
    return 0


@replacement_effect("draw")
def _look_at_top_cards_and_draw_one(game, payload: dict) -> ReplacementOutcome | None:
    """Aladdin's Lamp: the next draw is replaced by "look at the top X cards of
    your library, draw one of them, then put the rest on the bottom in a random
    order". The charge is spent even when the library is too short to look at
    anything, in which case the draw happens normally (CR 614.1)."""
    player = payload["player"]
    player_index = game.players.index(player)
    x = game.lamp_draw_replacements.get(player_index)
    if not x:
        return None
    game.lamp_draw_replacements.pop(player_index, None)
    x = min(int(x), len(player.library))
    if x <= 0:
        return None
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="lamp_draw",
            player_index=player_index,
            options=tuple(card.name for card in player.library[:x]),
            default_option=0,
            data={"remaining_draws": payload["count"] - 1},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks at the top {x} card(s) of their library (Aladdin's Lamp)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("lamp_draw")
def _resolve_lamp_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    looked_at = min(len(choice.options), len(player.library))
    drawn = game._finish_lamp_draw(choice.player_index, option_index, looked_at)
    remaining = int(choice.data.get("remaining_draws", 0))
    if remaining > 0:
        drawn += player.draw(remaining)
    return drawn
