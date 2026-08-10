"""Combat assignments the web layer has to ask about.

Ordinary blocking needs no prompt; four things do, because the rules hand a
player a choice the engine cannot make for them — banding's damage assignment
(CR 702.22), a band of blockers, a multi-blocked attacker's damage split
(CR 510.1a), and the pile divisions Raging River and Camouflage impose. Each is
the same triple: work out whether an assignment is outstanding, build the info
the client renders, and let an AI seat answer it immediately.
"""

from __future__ import annotations

from engine.ai_policy import choose_attack_target, choose_attackers, legal_attackers

from .session_store import Session

from .seats import _seat_type
from .serialization import _serialize_card_summary


def _ai_declare_attackers(session: Session) -> None:
    """Active-player (AI) declares attackers — the declare-attackers turn-based action."""
    game = session.game
    if game.current_step != "declare_attackers" or game.combat_attackers_locked:
        return
    if _seat_type(session, game.active_player_index) != "ai":
        return
    # MVP multiplayer target choice (see choose_attack_target): with 2+ living
    # opponents (FFA) there's no single unambiguous defender, so every AI
    # attacker this turn is sent at the same chosen opponent. In 2-player games
    # this always resolves to the only other seat, same as before.
    target = choose_attack_target(game, game.active_player_index)
    if session.force_ai_attack_all:
        # Debug override: attack with every legal attacker, ignoring AI judgement.
        attacker_indices = legal_attackers(game, game.active_player_index, against=target)
    else:
        attacker_indices = choose_attackers(game, game.active_player_index)
    ok, _ = game.declare_attackers(game.active_player_index, attacker_indices, defending_player_index=target)
    if not ok:
        # The chosen set was rejected (e.g. it omitted a creature that must attack
        # if able). Attacking with every legal attacker is always a valid superset:
        # it includes every forced creature, and a forced creature that can't
        # legally attack is never required. Declaring [] would fail identically.
        fallback = legal_attackers(game, game.active_player_index, against=target)
        ok, _ = game.declare_attackers(game.active_player_index, fallback, defending_player_index=target)
        if not ok:
            game.declare_attackers(game.active_player_index, [], defending_player_index=target)


def _banding_blocked_attackers(game) -> list[int]:
    """Attackers blocked by two or more creatures where at least one blocker has
    banding (controlled by the defending player). CR 702.22j: the defending player,
    not the active player, chooses how each such attacker's damage is split."""
    combat = game.get_combat_state()
    defender_index = combat.get("defending_player_index")
    if not isinstance(defender_index, int) or not (0 <= defender_index < len(game.players)):
        return []
    defender = game.players[defender_index]
    by_attacker: dict[int, list[int]] = {}
    for pair in combat.get("blockers", []):
        by_attacker.setdefault(int(pair["attacker_index"]), []).append(int(pair["blocker_index"]))
    result = []
    for attacker_idx, blockers in by_attacker.items():
        if len(blockers) < 2:
            continue
        if any(
            0 <= b < len(defender.battlefield) and game._creature_has_banding(defender.battlefield[b])
            for b in blockers
        ):
            result.append(attacker_idx)
    return sorted(result)


def _banding_assignment_pending(session: Session) -> bool:
    """Whether a human defending player still owes a CR 702.22j banding damage
    assignment for the current combat. While pending, the active player's combat
    damage must not auto-resolve (it would lock in the wrong split)."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return False
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int) or _seat_type(session, defender_index) != "human":
        return False
    return any(a not in game.combat_banding_damage for a in _banding_blocked_attackers(game))


def _build_banding_assignment_info(session: Session, viewer_seat: int | None) -> dict | None:
    """State block shown to the defending player so they can split the damage of
    each attacker blocked by one of their banding creatures (CR 702.22j)."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return None
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int):
        return None
    if viewer_seat is not None and viewer_seat != defender_index:
        return None
    pending = [a for a in _banding_blocked_attackers(game) if a not in game.combat_banding_damage]
    if not pending:
        return None
    return {"defender_seat": defender_index, "attacker_indices": pending}


def _band_blocker_assignments(game) -> list[dict]:
    """CR 702.22k: every blocker that is blocking an attacking band (which always
    contains a creature with banding). For each such blocker, the ACTIVE player —
    not the defender — chooses which band member it damages. Returns
    [{"blocker_idx", "member_indices": [...]}] with the band members (2+) it blocks."""
    if not game.combat_bands:
        return []
    active_index = game.active_player_index
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int) or not (0 <= defender_index < len(game.players)):
        return []
    active = game.players[active_index]
    defender = game.players[defender_index]
    result: list[dict] = []
    seen: set[int] = set()
    for band in game.combat_bands:
        members = [m for m in band if 0 <= m < len(active.battlefield)]
        if len(members) < 2:
            continue
        blockers: set[int] = set()
        for member in members:
            blockers.update(game._attacker_all_blockers(member))
        for b in sorted(blockers):
            if b in seen or not (0 <= b < len(defender.battlefield)):
                continue
            blocker = defender.battlefield[b]
            if blocker.card.primary_type != "creature" or blocker.effective_power <= 0:
                continue
            seen.add(b)
            result.append({"blocker_idx": b, "member_indices": members})
    return result


def _band_blocker_assignment_pending(session: Session) -> bool:
    """Whether a human active player still owes a CR 702.22k band-blocker damage
    assignment. While pending, combat damage must not auto-resolve."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return False
    if _seat_type(session, game.active_player_index) != "human":
        return False
    return bool(_band_blocker_assignments(game))


def _build_band_blocker_assignment_info(session: Session, viewer_seat: int | None) -> dict | None:
    """State block shown to the active player so they can choose which band member
    each creature blocking their band damages (CR 702.22k)."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return None
    active_index = game.active_player_index
    if viewer_seat is not None and viewer_seat != active_index:
        return None
    # The defender resolves their CR 702.22j split first, mirroring the engine order.
    if _banding_assignment_pending(session):
        return None
    blockers = _band_blocker_assignments(game)
    if not blockers:
        return None
    return {"attacker_seat": active_index, "blockers": blockers}


def _multiblock_blocker_splits(game) -> list[dict]:
    """CR 510.1d: every defender creature blocking 2+ attackers whose combat
    damage the defending player may divide among them (Two-Headed Giant of
    Foriys). Blockers blocking an attacking band are excluded — the ACTIVE
    player assigns those (CR 702.22k, the band-blocker flow)."""
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int) or not (0 <= defender_index < len(game.players)):
        return []
    defender = game.players[defender_index]
    band_blockers = {entry["blocker_idx"] for entry in _band_blocker_assignments(game)}
    result: list[dict] = []
    for b_idx, attacker_idxs in sorted(game.combat_blockers.get(defender_index, {}).items()):
        if b_idx in band_blockers or not (0 <= b_idx < len(defender.battlefield)):
            continue
        attackers = sorted(set(attacker_idxs))
        if len(attackers) < 2:
            continue
        blocker = defender.battlefield[b_idx]
        if not blocker.is_creature or blocker.effective_power <= 0:
            continue
        result.append({"blocker_idx": b_idx, "attacker_indices": attackers})
    return result


def _multiblock_split_pending(session: Session) -> bool:
    """Whether a human defending player still owes a CR 510.1d division for a
    creature blocking multiple attackers. While pending, combat damage must not
    auto-resolve."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return False
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int) or _seat_type(session, defender_index) != "human":
        return False
    return any(
        entry["blocker_idx"] not in game.combat_multiblock_damage
        for entry in _multiblock_blocker_splits(game)
    )


def _build_multiblock_assignment_info(session: Session, viewer_seat: int | None) -> dict | None:
    """State block shown to the defending player so they can divide a
    multi-blocking creature's combat damage among the attackers it blocks."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return None
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int):
        return None
    if viewer_seat is not None and viewer_seat != defender_index:
        return None
    blockers = [
        entry
        for entry in _multiblock_blocker_splits(game)
        if entry["blocker_idx"] not in game.combat_multiblock_damage
    ]
    if not blockers:
        return None
    return {"defender_seat": defender_index, "blockers": blockers}


def _build_raging_river_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Raging River: show the defending player the non-flying creatures to divide
    into left/right piles, and the attacking player their attackers to label.
    Only surfaced to a human; AI players keep the default seeded division."""
    game = session.game
    if not game.combat_left_right_active or game.current_step not in ("declare_attackers", "declare_blockers"):
        return None
    if game.combat_damage_resolved:
        return None
    if viewer_seat is None or _seat_type(session, viewer_seat) == "ai":
        return None
    defender_index = game.combat_left_right_defender_index
    attacker_index = game.active_player_index
    info: dict = {"defender_seat": defender_index, "attacker_seat": attacker_index}

    # Non-flying defender creatures that must be divided into a left/right pile.
    divide = []
    if isinstance(defender_index, int) and 0 <= defender_index < len(game.players):
        defender = game.players[defender_index]
        divide = [
            {"index": i, **_serialize_card_summary(p.card), "pile": game.combat_defender_piles.get(i)}
            for i, p in enumerate(defender.battlefield)
            if game._is_creature(p) and not game._has_keyword(p, "flying")
        ]
    # The defender chooses first; the attacker is gated until they finish. With no
    # non-flying creatures to divide there's nothing to decide, so the defender is
    # immediately "done" and the attacker may proceed.
    defender_done = game.combat_left_right_defender_locked or not divide

    if viewer_seat == defender_index and not game.combat_left_right_defender_locked and divide:
        info["divide_creatures"] = divide
    if viewer_seat == attacker_index and defender_done and not game.combat_left_right_attacker_locked:
        attacker = game.players[attacker_index]
        label = [
            {"index": i, **_serialize_card_summary(attacker.battlefield[i].card), "pile": game.combat_attacker_piles.get(i)}
            for i in sorted(game.combat_attackers)
            if 0 <= i < len(attacker.battlefield)
        ]
        if label:
            info["label_attackers"] = label
    if "divide_creatures" not in info and "label_attackers" not in info:
        return None
    return info


def _build_camouflage_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Camouflage: prompt the human defending player to divide their untapped
    creatures into numbered piles (one per attacker; piles may be empty and
    creatures may be left out). The engine then matches each pile to a different
    attacker at random. An AI defender gets random piles instead (_advance_step)."""
    game = session.game
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return None
    if not game.is_camouflage_active() or game.combat_blockers_locked:
        return None
    defender_index = game.combat_defending_player_index
    if not isinstance(defender_index, int) or viewer_seat != defender_index:
        return None
    if _seat_type(session, viewer_seat) == "ai":
        return None
    attackers = [a for a, d in game.combat_attackers.items() if d == defender_index]
    if not attackers:
        return None
    defender = game.players[defender_index]
    creatures = [
        {"index": i, **_serialize_card_summary(p.card)}
        for i, p in enumerate(defender.battlefield)
        if p.is_creature and not p.tapped
    ]
    if not creatures:
        return None
    return {
        "defender_seat": defender_index,
        "pile_count": len(attackers),
        "divide_creatures": creatures,
    }


def _ai_resolve_raging_river(session: Session) -> None:
    """Finalize Raging River's left/right division for any AI player so the human
    flow can proceed. An AI defender keeps its random seeded piles and locks them
    (it "chooses randomly"); an AI attacker locks its labels once the defender has
    finished. Idempotent — safe to call on every state build."""
    game = session.game
    if not game.combat_left_right_active or game.combat_damage_resolved:
        return
    if game.current_step not in ("declare_attackers", "declare_blockers"):
        return
    defender_index = game.combat_left_right_defender_index
    attacker_index = game.active_player_index

    divide_count = 0
    if isinstance(defender_index, int) and 0 <= defender_index < len(game.players):
        divide_count = sum(
            1
            for p in game.controlled_by(defender_index)
            if game._is_creature(p) and not game._has_keyword(p, "flying")
        )

    if (
        isinstance(defender_index, int)
        and not game.combat_left_right_defender_locked
        and divide_count > 0
        and _seat_type(session, defender_index) == "ai"
    ):
        game.combat_left_right_defender_locked = True
        game.log.append(f"{game.players[defender_index].name} randomly divided their creatures left/right")

    defender_done = game.combat_left_right_defender_locked or divide_count == 0
    if (
        defender_done
        and not game.combat_left_right_attacker_locked
        and _seat_type(session, attacker_index) == "ai"
    ):
        game.combat_left_right_attacker_locked = True


def _ai_assign_combat_damage(session: Session) -> None:
    """Active-player (AI) assigns combat damage — the turn-based action the engine
    defers to a player when an attacker is blocked by two or more creatures."""
    game = session.game
    if game.current_step != "combat_damage" or game.combat_damage_resolved:
        return
    if _seat_type(session, game.active_player_index) != "ai":
        return
    # Pause so a human defender can pre-commit their CR 702.22j banding split
    # or CR 510.1d multi-block division before the active AI locks in combat damage.
    if _banding_assignment_pending(session):
        return
    if _multiblock_split_pending(session):
        return
    auto = game._build_auto_damage_assignment()
    # Both strike passes (CR 510.4). One call rather than two, so a first-strike
    # pass that stops to ask a human defender something (CR 616.1e) records the
    # second pass behind it instead of having it re-run the first.
    game.resolve_all_combat_damage(game.active_player_index, attacker_damage=auto)
