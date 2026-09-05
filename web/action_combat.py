"""Handlers for combat declarations and damage assignment (CR 508-510),
including banding's defender-assigned damage (CR 702.22j-k), multi-block
divisions (CR 510.1d), and the Raging River / Camouflage pile assignments.
"""

from __future__ import annotations

from fastapi import HTTPException
from .action_registry import HUMAN_ONLY, action_handler
from .combat_prompts import (
    _ai_assign_combat_damage,
    _banding_assignment_pending,
    _multiblock_split_pending,
)
from .seats import _seat_type


@action_handler("declare_attackers", human_only=HUMAN_ONLY)
def _action_declare_attackers(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    # Declaring attackers is the active player's turn-based action (CR 508.1),
    # taken before any player has priority — so no spells may be cast during
    # the assignment and a priority window is *not* required here. The engine
    # grants the active player priority once attackers are declared (CR 508.2).
    # CR 508.1b: an attacker may be sent at a planeswalker rather than at
    # its controller. JSON object keys arrive as strings; the engine keys
    # its combat maps by int battlefield slot.
    walker_targets = {
        int(k): int(v) for k, v in (req.attacker_planeswalker_ids or {}).items()
    }
    ok, details = session.game.declare_attackers(
        req.seat,
        req.attacker_indices or [],
        defending_player_index=req.target_seat,
        bands=req.bands,
        attacker_planeswalker_ids=walker_targets or None,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=details)

@action_handler("declare_blockers", human_only=HUMAN_ONLY)
def _action_declare_blockers(session, req, seat_type):
    # CR 802.4: with attack-multiple-players (FFA), 2+ defending players may
    # each declare blocks in the same combat — any of them may act here, not
    # just a single pre-picked defender. With zero attackers this turn nobody
    # is formally "a defending player" yet, but any non-active seat may still
    # submit a trivial no-op declaration (mirrors the engine's own check).
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser may be a seat that is not defending
    # at all, so "who may act here" is asked of the engine's one answer rather
    # than of the defender list — and the declaration is still made *for* the
    # defending player, whose creatures block and whose costs are charged.
    # `target_seat` names which defender when the acting seat is choosing for
    # someone else; with none given the rail's next pending declarer is meant,
    # which is the only unambiguous reading in a two-player game.
    game = session.game
    defending_players = game.combat_defending_players()
    declaring_for = req.seat
    if req.seat not in defending_players:
        pending = (
            req.target_seat if req.target_seat is not None
            else game._pending_block_declarer()
        )
        if isinstance(pending, int) and game.block_chooser_index(pending) == req.seat:
            declaring_for = pending
    if defending_players:
        if declaring_for not in defending_players:
            raise HTTPException(status_code=400, detail="only a defending player may declare blockers")
    elif declaring_for == game.active_player_index or not (0 <= declaring_for < len(game.players)):
        raise HTTPException(status_code=400, detail="only a defending player may declare blockers")
    # Declaring blockers is the defending player's turn-based action (CR 509.1),
    # not a priority action: no spells may be cast during the assignment, and the
    # defender declares even while no priority window is open. The engine grants
    # the active player priority once blockers are declared (CR 509.2), so the
    # AI's turn can resume / the attacker may respond.
    raw_pairs = req.blocker_pairs or {}
    # A value may be a single attacker index or a list (one creature blocking
    # several attackers — Two-Headed Giant of Foriys). Normalize to lists.
    blocker_pairs = {
        int(k): [int(a) for a in (v if isinstance(v, list) else [v])]
        for k, v in raw_pairs.items()
    }
    ok, details = game.declare_blockers(
        declaring_for, blocker_pairs, acting_index=req.seat
    )
    if not ok:
        raise HTTPException(status_code=400, detail=details)

@action_handler("assign_combat_damage", human_only=HUMAN_ONLY)
def _action_assign_combat_damage(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")
    # CR 702.22j: the defender pre-commits banding-blocked attackers' damage
    # before the active player resolves; block resolution until they have.
    if _banding_assignment_pending(session):
        raise HTTPException(
            status_code=400,
            detail="waiting for the defending player to assign banding combat damage",
        )
    # CR 510.1d: likewise a defender's multi-block division (Two-Headed Giant
    # of Foriys) is pre-committed before combat damage resolves.
    if _multiblock_split_pending(session):
        raise HTTPException(
            status_code=400,
            detail="waiting for the defending player to divide blocker combat damage",
        )
    # Distinguish "no assignment given" (None -> engine default/auto) from an
    # explicit empty assignment ({} -> deal nothing). This lets a caller supply
    # only blocker_damage (banding, CR 702.22k) and have attackers deal normally.
    if req.attacker_damage is None:
        attacker_damage = None
    else:
        attacker_damage = {
            int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
            for attacker_idx, blockers in req.attacker_damage.items()
        }
    blocker_damage = (
        {int(b): int(a) for b, a in req.blocker_damage.items()}
        if req.blocker_damage
        else None
    )
    blocker_damage_split = (
        {
            int(b): {int(m): int(v) for m, v in split.items()}
            for b, split in req.blocker_damage_split.items()
        }
        if req.blocker_damage_split
        else None
    )
    ok, details = session.game.resolve_combat_damage(
        req.seat,
        attacker_damage=attacker_damage,
        blocker_damage=blocker_damage,
        blocker_damage_split=blocker_damage_split,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=details)
    session.game.note_priority_action_taken(req.seat)

@action_handler("assign_banding_damage", human_only=HUMAN_ONLY)
def _action_assign_banding_damage(session, req, seat_type):
    # CR 702.22j: the defending player pre-commits how attackers blocked by a
    # creature with banding split their combat damage.
    banding_raw = req.banding_damage or {}
    banding_damage = {
        int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
        for attacker_idx, blockers in banding_raw.items()
    }
    ok, details = session.game.assign_banding_combat_damage(req.seat, banding_damage)
    if not ok:
        raise HTTPException(status_code=400, detail=details)
    # The defender has pre-committed their CR 702.22j split. If the attacker is
    # the AI, it was paused waiting for this — resolve its combat damage now.
    if (
        not _banding_assignment_pending(session)
        and _seat_type(session, session.game.active_player_index) == "ai"
    ):
        _ai_assign_combat_damage(session)

@action_handler("assign_multiblock_damage", human_only=HUMAN_ONLY)
def _action_assign_multiblock_damage(session, req, seat_type):
    # CR 510.1d: the defending player pre-commits how each of their creatures
    # blocking multiple attackers (Two-Headed Giant of Foriys) divides its
    # combat damage among them.
    split_raw = req.blocker_damage_split or {}
    blocker_split = {
        int(b): {int(a): int(v) for a, v in split.items()}
        for b, split in split_raw.items()
    }
    ok, details = session.game.assign_multiblock_blocker_damage(req.seat, blocker_split)
    if not ok:
        raise HTTPException(status_code=400, detail=details)
    # If the attacker is the AI, it was paused waiting for this division —
    # resolve its combat damage now.
    if (
        not _multiblock_split_pending(session)
        and not _banding_assignment_pending(session)
        and _seat_type(session, session.game.active_player_index) == "ai"
    ):
        _ai_assign_combat_damage(session)

@action_handler("assign_defender_piles")
def _action_assign_defender_piles(session, req, seat_type):
    piles = {int(k): str(v) for k, v in (req.piles or {}).items()}
    ok, details = session.game.assign_defender_piles(req.seat, piles)
    if not ok:
        raise HTTPException(status_code=400, detail=details)

@action_handler("assign_attacker_piles")
def _action_assign_attacker_piles(session, req, seat_type):
    piles = {int(k): str(v) for k, v in (req.piles or {}).items()}
    ok, details = session.game.assign_attacker_piles(req.seat, piles)
    if not ok:
        raise HTTPException(status_code=400, detail=details)

@action_handler("assign_camouflage_piles")
def _action_assign_camouflage_piles(session, req, seat_type):
    # Camouflage: the defending player's chosen division of their creatures
    # into piles (0-based pile numbers, one pile per attacker). Piles are then
    # matched to attackers at random by the engine.
    camo_piles: dict[int, int | list[int]] = {
        int(k): ([int(p) for p in v] if isinstance(v, list) else int(v))
        for k, v in (req.camouflage_piles or {}).items()
    }
    ok, details = session.game.assign_camouflage_piles(req.seat, camo_piles)
    if not ok:
        raise HTTPException(status_code=400, detail=details)
