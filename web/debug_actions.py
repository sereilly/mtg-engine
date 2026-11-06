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

    # Whether it is an Aura is asked *before* the move and through
    # ``has_type`` (CR 613 layer 4). A **Licid** becomes an Aura enchantment
    # without a word of its card moving, so the printed type line that stood
    # here answered "no" and left a Licid's grants on the creature it had been
    # attached to after the Licid itself had been bounced.
    is_aura = permanent.has_type("aura")
    game.remove_from_battlefield(permanent)
    if is_aura:
        game._remove_aura_effects(permanent)
    # An Aura's death trigger used to be announced here as well. It was wrong
    # twice over: this move is a bounce or an exile, and CR 700.4 makes "dies"
    # mean *put into a graveyard from the battlefield* — so "when enchanted
    # creature dies" fired on a creature that had not died. The one death
    # announcement is `_fire_creature_dies_triggers`, reached from the graveyard
    # seam, which this path deliberately does not take.
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


def _pasted_exile(game, seat: int, entries, viewer_seat: int | None) -> list[tuple]:
    """The objects a pasted exile names for *seat*, in its order, each as
    ``(card, kept)`` — *kept* when it is an object the pile holds now.

    A ``<hidden>`` entry names no card: it is the card back the pasting viewer
    was shown (``serialization.exile_hidden_flags``), so it is **that object**,
    kept — the next one of the pile's hidden objects, in pile order. Read as
    "nothing" (it used to be), a paste of a board with a card face down in
    exile deleted the card. A placeholder past the last hidden object names
    nothing and is dropped.

    A named entry is likewise the pile's own next visible object of that name
    when there is one, else the catalog's card: every record about an exiled
    card names its object (``Game.put_card_into_exile``), so a paste that
    leaves an exiled card where it was leaves what is known about it too —
    which is what the paste promises for anything its text cannot describe.
    """
    from .serialization import exile_hidden_flags

    player = game.players[seat]
    flags = exile_hidden_flags(game, player, viewer_seat, seat)
    hidden = [card for card, flag in zip(player.exile, flags) if flag]
    visible: dict[str, list] = {}
    for card, flag in zip(player.exile, flags):
        if not flag:
            visible.setdefault(card.name.casefold(), []).append(card)
    planned: list[tuple] = []
    for entry in entries or []:
        if isinstance(entry, str):
            if entry == "<hidden>" and hidden:
                planned.append((hidden.pop(0), True))
            continue
        if isinstance(entry, dict) and entry.get("name"):
            held = visible.get(str(entry["name"]).strip().casefold())
            if held:
                planned.append((held.pop(0), True))
            else:
                planned.append((_lookup_card_for_raw_state(entry["name"]), False))
    return planned


def _retire_dropped_exiles(game, plans: list[list[tuple]]) -> None:
    """A card the paste no longer names **leaves** its exile, through the seam
    (``take_card_from_exile``): its records and while-exiled grants end with it
    (CR 400.7), so the next effect to exile that object finds nothing stale."""
    kept = {id(card) for plan in plans for card, was_kept in plan if was_kept}
    for seat, player in enumerate(game.players):
        for card in [held for held in player.exile if id(held) not in kept]:
            game.take_card_from_exile(seat, card)


def _restore_exiles(game, plans: list[list[tuple]]) -> None:
    """Put every planned card into its seat's exile, once every pile is empty,
    through ``put_card_into_exile`` — so a paste naming two copies of a card
    names two objects (CR 400.7).

    A card built from a name that *is* a kept object still to be put back (a
    deck repeats one object per copy, so a face-up Forest named beside a
    face-down one is the same object) arrives as a new, equal one, so the kept
    object keeps its identity and with it the record that says it is face
    down. Without that the named copy would land first as the object and the
    face-down one after it as the copy, and the record would hide the wrong
    card.
    """
    from engine.exiled_records import distinct_exile_object

    pending = {id(card) for plan in plans for card, kept in plan if kept}
    for seat, plan in enumerate(plans):
        for card, kept in plan:
            if kept:
                pending.discard(id(card))
            elif id(card) in pending:
                card = distinct_exile_object(card)
            game.put_card_into_exile(seat, card)


def _card_for_raw_permanent(game, raw: dict):
    """The card a pasted permanent is: its name's, or — for a face-down one
    (CR 708.2), whose payload names the blank 2/2 — the face-down object of
    the card it hides.

    Which card that is the paste says when its viewer controls it
    (``hidden_card``, CR 708.5); otherwise it is the hidden object of the
    face-down permanent the payload's ``id`` names, still on the battlefield.
    "Face-down creature" is no card, so a paste of any board holding a morph
    was refused whole, as an unknown card.
    """
    from engine.face_down import face_down_card, hidden_card_of

    if not raw.get("face_down"):
        return _lookup_card_for_raw_state(raw["name"])
    named = raw.get("hidden_card")
    if isinstance(named, dict) and named.get("name"):
        return face_down_card(_lookup_card_for_raw_state(named["name"]))
    current = game.permanent_by_id(raw.get("id")) if isinstance(raw.get("id"), int) else None
    real = hidden_card_of(current) if current is not None else None
    if real is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "a face-down permanent the paste does not name: give its card as "
                '"hidden_card": {"name": ...}'
            ),
        )
    return face_down_card(real)


def _permanent_from_raw(raw: dict, game) -> Permanent:
    card = _card_for_raw_permanent(game, raw)
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


def _apply_raw_state(session: Session, raw: dict, viewer_seat: int | None = None) -> None:
    """Overwrite the live game's visible state from a pasted raw-state object.

    Rebuilds every visible zone (hands, graveyards, exile, battlefields) and
    per-permanent flags, plus life totals, mana pools and turn/phase tracking.
    Hidden information that the serialization omits — library contents, an
    opponent's `<hidden>` hand, a card face down in exile, the card behind a
    face-down permanent — is left untouched, since the text cannot describe
    it: a ``<hidden>`` exile entry keeps the object *viewer_seat* (the seat
    that pasted, whose payload it was) was shown a card back for
    (:func:`_pasted_exile`), and a face-down permanent keeps its card
    (:func:`_card_for_raw_permanent`). Anything malformed raises
    HTTPException(400) before the live game is mutated, so a bad paste never
    half-applies.
    """
    from engine.linked_exile import keep_face_down_after_departure

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
            "exile": _pasted_exile(game, seat, p_raw.get("exile"), viewer_seat),
            "ante": _cards_from_raw(p_raw.get("ante")),
            "battlefield": [_permanent_from_raw(pr, game) for pr in battlefield_raw],
            "battlefield_raw": battlefield_raw,
        })

    # Every permanent is replaced by a new one, so each is a departure as far
    # as what it exiled face down is concerned (CR 406.3 has no ending): its
    # face-down records go to the game's register, as a permanent leaving the
    # battlefield hands them (``keep_face_down_after_departure``), and a card
    # a rebuilt Knowledge Vault exiled stays a card back.
    for perm in list(game.all_permanents()):
        keep_face_down_after_departure(game, perm)
    _retire_dropped_exiles(game, [built["exile"] for built in rebuilt])

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
        player.exile = []
        player.ante = built["ante"]
        player.battlefield = built["battlefield"]

    # Exile arrives through its one transition, once every seat's pile is empty:
    # a paste naming two copies of a card names two objects (no exile holds one
    # object twice, CR 400.7 — `Game.put_card_into_exile`), as a real exiling
    # would have made them. Built from names, both would be the catalog's one.
    _restore_exiles(game, [built["exile"] for built in rebuilt])

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
