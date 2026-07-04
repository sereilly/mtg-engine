"""Regression tests for the sixteenth batch of bugs reported in-game.

Clusters covered in this batch:
- Undo endpoint: pressing Undo returned a plain-text 500 ("Internal Server
  Error" — surfaced in the client as "Unexpected token 'I' ... is not valid
  JSON") because the undo route restored ``upkeep_mana_prevention_choices`` /
  ``upkeep_mana_prevention_resolved`` from the snapshot, but ``GameSnapshot``
  never defined or saved those fields, raising AttributeError.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from web.app import app, store

client = TestClient(app)


class TestUndoEndpoint:
    def test_undo_after_action_returns_json_state(self):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "seed": 7},
        ).json()
        sid = created["session_id"]

        acted = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )
        assert acted.status_code == 200
        assert len(store.get(sid).history) >= 1

        undone = client.post(f"/api/sessions/{sid}/undo?seat=0")
        assert undone.status_code == 200
        payload = undone.json()
        assert payload["session_id"] == sid

    def test_snapshot_round_trips_mana_prevention_fields(self):
        created = client.post(
            "/api/sessions",
            json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "seed": 7},
        ).json()
        session = store.get(created["session_id"])

        session.upkeep_mana_prevention_choices = [{"controller": 0, "permanent_id": 3}]
        session.upkeep_mana_prevention_resolved = {"0:3": 2}
        session.history.save(session)

        snapshot = session.history.undo()
        assert snapshot.upkeep_mana_prevention_choices == [{"controller": 0, "permanent_id": 3}]
        assert snapshot.upkeep_mana_prevention_resolved == {"0:3": 2}
