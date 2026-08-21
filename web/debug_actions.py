"""The Debug Menu's board manipulation, and raw-state injection.

Testing aids, not rules: put a card in a hand, tap or destroy a permanent, or
replace a whole board with a JSON description so a reported bug can be
reproduced from the state it happened in. Kept apart from :mod:`web.actions`
because none of it is a legal game action — it sets up positions the rules would
otherwise have to be played into.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.models import Permanent

from .session_store import Session

from .runtime import CARD_BY_NAME
from .serialization import _printed_stat


# Debug actions that stay available while the game is waiting on a pending
# decision (a cleanup discard, a search, an upkeep payment…). They set up board
# state rather than answering the question the game is asking, so blocking them
# would strand a tester who needs, say, a creature destroyed before they can
# make the choice in front of them.
_DEBUG_ANYTIME_ACTIONS = {
    "debug_add_to_hand",
    "debug_add_to_sideboard",
    "debug_cast_free",
    "debug_add_mana",
    "debug_clear_summoning_sickness",
    "debug_tap_permanent",
    "debug_untap_permanent",
    "debug_return_to_hand",
    "debug_destroy_permanent",
    "debug_exile_permanent",
    "debug_create_copy",
    "debug_send_to_opponent",
}


def _debug_target_permanent(session: Session, req) -> tuple[int, Permanent]:
    """Resolve the battlefield permanent a debug board action addresses, from
    ``target_seat`` (defaulting to the acting seat) + ``target_permanent_index``.
    Returns ``(controller_seat, permanent)``."""
    controller_seat = req.target_seat if req.target_seat is not None else req.seat
    if not (0 <= controller_seat < len(session.game.players)):
        raise HTTPException(status_code=400, detail="target seat out of range for this session")
    battlefield = session.game.players[controller_seat].battlefield
    index = req.target_permanent_index
    if index is None or not (0 <= index < len(battlefield)):
        raise HTTPException(status_code=404, detail="permanent not found on that battlefield")
    return controller_seat, battlefield[index]


def _debug_move_permanent_off_battlefield(game, controller_seat: int, index: int, zone: str) -> None:
    """Move a permanent from the battlefield to its owner's hand or exile,
    running the same leave-the-battlefield cleanup a real bounce/exile effect
    does: the Aura's continuous grants end (CR 611.3), an Aura enchanting it
    gets its "when that creature dies" trigger, and lord buffs are recomputed.
    The card goes to its *owner's* zone (CR 400.3), which differs from the
    controller's for a stolen permanent; a token ceases to exist (CR 704.5e)."""
    controller = game.players[controller_seat]
    permanent = controller.battlefield[index]
    # Resolve the owner while the permanent is still on a battlefield —
    # owner_index_of falls back to the current controller, which is unfindable
    # once it has been popped.
    owner_index = game.owner_index_of(permanent)
    owner = game.players[owner_index] if owner_index is not None else controller

    game.remove_from_battlefield(permanent)
    if "Aura" in permanent.card.type_line:
        game._remove_aura_effects(permanent)
    game._trigger_aura_death_effects(permanent, controller)
    if not permanent.metadata.get("is_token", False):
        (owner.hand if zone == "hand" else owner.exile).append(permanent.card)
    game._recompute_continuous_effects()


def _lookup_card_for_raw_state(name: str):
    card = CARD_BY_NAME.get(str(name).strip().casefold())
    if card is None:
        raise HTTPException(status_code=400, detail=f"unknown card: {name!r}")
    return card


def _cards_from_raw(entries) -> list:
    """Rebuild a list of CardDefinitions from serialized cards (or `<hidden>`
    placeholders, which carry no identity and are skipped)."""
    cards = []
    for entry in entries or []:
        if isinstance(entry, str):
            # `<hidden>` placeholder — no card identity to restore.
            continue
        if isinstance(entry, dict) and entry.get("name"):
            cards.append(_lookup_card_for_raw_state(entry["name"]))
    return cards


def _permanent_from_raw(raw: dict) -> Permanent:
    card = _lookup_card_for_raw_state(raw["name"])
    perm = Permanent(card=card)
    perm.tapped = bool(raw.get("tapped", False))
    perm.damage_marked = int(raw.get("damage_marked") or 0)
    perm.attacking = bool(raw.get("attacking", False))
    perm.defending_player_index = raw.get("defending_player_index")
    perm.blocked = bool(raw.get("blocked", False))
    perm.blocking_attacker_controller = raw.get("blocking_attacker_controller")
    perm.blocking_attacker_index = raw.get("blocking_attacker_index")
    if raw.get("is_token"):
        perm.metadata["is_token"] = True
    # Power/toughness are effective (post-layer) values; honor a manual edit by
    # carrying the delta over the printed base as a flat bonus.
    base_power = _printed_stat(card, "power")
    base_toughness = _printed_stat(card, "toughness")
    if isinstance(raw.get("power"), int) and isinstance(base_power, int):
        perm.power_bonus = raw["power"] - base_power
    if isinstance(raw.get("toughness"), int) and isinstance(base_toughness, int):
        perm.toughness_bonus = raw["toughness"] - base_toughness
    return perm


def _apply_raw_state(session: Session, raw: dict) -> None:
    """Overwrite the live game's visible state from a pasted raw-state object.

    Rebuilds every visible zone (hands, graveyards, exile, battlefields) and
    per-permanent flags, plus life totals, mana pools and turn/phase tracking.
    Hidden information that the serialization omits — library contents and an
    opponent's `<hidden>` hand — is left untouched, since the text cannot
    describe it. Anything malformed raises HTTPException(400) before the live
    game is mutated, so a bad paste never half-applies.
    """
    game = session.game
    players_raw = raw.get("players")
    if not isinstance(players_raw, list) or len(players_raw) != len(game.players):
        raise HTTPException(status_code=400, detail="raw state must list both players")

    # Build everything up-front so a parse error aborts before any mutation.
    rebuilt: list[dict] = []
    for seat, p_raw in enumerate(players_raw):
        if not isinstance(p_raw, dict):
            raise HTTPException(status_code=400, detail=f"player {seat} is malformed")
        battlefield_raw = p_raw.get("battlefield") or []
        rebuilt.append({
            "hand_hidden": any(c == "<hidden>" for c in (p_raw.get("hand") or [])),
            "hand": _cards_from_raw(p_raw.get("hand")),
            "graveyard": _cards_from_raw(p_raw.get("graveyard")),
            "exile": _cards_from_raw(p_raw.get("exile")),
            "ante": _cards_from_raw(p_raw.get("ante")),
            "battlefield": [_permanent_from_raw(pr) for pr in battlefield_raw],
            "battlefield_raw": battlefield_raw,
        })

    for seat, player in enumerate(game.players):
        p_raw = players_raw[seat]
        built = rebuilt[seat]
        if isinstance(p_raw.get("name"), str) and p_raw["name"]:
            player.name = p_raw["name"]
        if isinstance(p_raw.get("life"), int):
            player.life = p_raw["life"]
        mana = p_raw.get("mana_pool")
        if isinstance(mana, dict):
            player.mana_pool = {
                color: int(mana.get(color, 0) or 0)
                for color in ("W", "U", "B", "R", "G", "C")
            }
        # A `<hidden>` hand belongs to the other player and isn't ours to rewrite.
        if not built["hand_hidden"]:
            player.hand = built["hand"]
        player.graveyard = built["graveyard"]
        player.exile = built["exile"]
        player.ante = built["ante"]
        player.battlefield = built["battlefield"]

    # Second pass: reconnect aura attachments now that every permanent exists.
    for seat, player in enumerate(game.players):
        for perm, p_raw in zip(player.battlefield, rebuilt[seat]["battlefield_raw"]):
            target_seat = p_raw.get("attached_to_seat")
            target_index = p_raw.get("attached_to_index")
            if target_seat is None or target_index is None:
                continue
            targets = game.players[target_seat].battlefield
            if 0 <= target_index < len(targets):
                perm.metadata["attached_to"] = targets[target_index]

    # Turn / phase / priority tracking.
    if isinstance(raw.get("turn_number"), int):
        game.turn = raw["turn_number"]
    if isinstance(raw.get("current_turn"), int) and raw["current_turn"] in (0, 1):
        session.current_turn = raw["current_turn"]
        game.active_player_index = raw["current_turn"]
    phase = raw.get("current_turn_phase")
    step = raw.get("current_step")
    if isinstance(phase, str) and isinstance(step, str):
        game._set_phase_and_step(phase, step)
    priority = raw.get("priority_player")
    if priority is None or priority in (0, 1):
        game.priority_player_index = priority
    if isinstance(raw.get("priority_pass_count"), int):
        game.priority_pass_count = raw["priority_pass_count"]

    game.check_state_based_actions()
    game.log.append("[Debug] Game state replaced from pasted raw state.")
