"""Every prompt the server can emit has a browser renderer.

``web/prompts.py``'s ``render_prompts`` iterates the choice registry, so the
server side of a new prompt is covered by construction. The client is not: a
``ChoiceSpec`` whose ``prompt_key`` nothing in ``app.js`` reads is a prompt the
seat owing it can never see, and the game sits blocked on it. Six shipped that
way — scry (every Temple), ``mode_choice`` (Trufflesnout, Elder Gargaroth),
``name_and_strip`` (Necromentia), ``reflexive_target`` (Tolarian Kraken),
``revealed_hand_pick`` (Duress, Kitesail Freebooter) and ``tap_any_number``
(Siege Striker). This holds the set of unrendered prompts at empty.
"""
from __future__ import annotations

import re
from pathlib import Path

from engine.mixins.stack.choices import CHOICE_SPECS

APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"


def _client_reads(js: str, key: str) -> bool:
    escaped = re.escape(key)
    return re.search(rf'state\.{escaped}\b|state\["{escaped}"\]', js) is not None


def test_every_prompt_has_a_client_renderer():
    js = APP_JS.read_text(encoding="utf-8")
    missing = sorted(
        spec.prompt_key
        for spec in CHOICE_SPECS.values()
        if not _client_reads(js, spec.prompt_key)
    )
    assert not missing, (
        f"prompts the client never renders: {missing} — add a getter reading "
        "state.<key> and a renderer in web/static/app.js"
    )


def test_every_prompt_action_is_sent_by_the_client():
    """The other half of the wire: the action that answers the prompt has to
    be one the client actually sends, or the renderer is a picture."""
    js = APP_JS.read_text(encoding="utf-8")
    missing = sorted(
        spec.action
        for spec in CHOICE_SPECS.values()
        if spec.action and f'action: "{spec.action}"' not in js
    )
    assert not missing, f"prompt answers the client never sends: {missing}"
