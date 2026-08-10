"""Board-building helpers shared by the LEA per-card test files.

Not a test module (pytest collects ``test_*.py`` only), so the split
files import the one definition instead of each carrying a copy.
"""

from __future__ import annotations

import json
from web.app import app, store
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)


def _start_session_with_p0_graveyard(graveyard, seed):
    """Create a joined human_vs_human session, give P0 the supplied graveyard, and
    advance to P0's second upkeep (the empty battlefield avoids an untap prompt)."""
    from web.app import _end_turn

    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "guest_name": "P2", "seed": seed},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})

    session = store.get(sid)
    p0 = session.game.players[0]
    p0.battlefield = []
    p0.hand = []
    p0.graveyard = list(graveyard)

    # Advance turns until P0 begins its own upkeep and pauses for the optional
    # trigger. Whether that takes one or two end-turns depends on which seat the
    # seed sends first, so loop rather than assume.
    for _ in range(6):
        if (
            session.current_turn == 0
            and session.game.current_step == "upkeep"
            and session.optional_trigger_choices
        ):
            break
        _end_turn(session, allow_manual_cleanup_selection=False)
    return sid, session


def _grizzly(all_cards):
    return _get(all_cards, "Grizzly Bears")


def _island(all_cards):
    return _get(all_cards, "Island")


def _plains(all_cards):
    return _get(all_cards, "Plains")


def _swamp(all_cards):
    return _get(all_cards, "Swamp")


def _mountain(all_cards):
    return _get(all_cards, "Mountain")


def _forest(all_cards):
    return _get(all_cards, "Forest")
