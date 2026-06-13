from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock


VALID_STATUSES = {"pass", "fail"}


class VerificationStore:
    """Persists manual card-verification results to a single JSON file.

    This file is the master record of which cards have been manually validated
    in-game. Shape:

        {"results": {card_name: {"status": "pass"|"fail",
                                 "reason": str,
                                 "updated_at": float}}}

    Only cards that have been tested appear here; everything else in the catalog
    is implicitly "untested".
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"results": {}}
        if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
            return {"results": {}}
        return data

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def results(self) -> dict:
        """Return the raw {card_name: entry} mapping of recorded results."""
        return self._load()["results"]

    def record(self, card_name: str, status: str, reason: str = "") -> dict:
        name = card_name.strip()
        if not name:
            raise ValueError("card_name is required")
        if status not in VALID_STATUSES:
            raise ValueError("status must be 'pass' or 'fail'")
        entry = {
            "status": status,
            "reason": reason.strip() if status == "fail" else "",
            "updated_at": time.time(),
        }
        with self._lock:
            data = self._load()
            data["results"][name] = entry
            self._save(data)
        return {"card_name": name, **entry}
