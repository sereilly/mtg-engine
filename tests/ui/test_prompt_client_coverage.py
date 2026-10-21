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


#: Prompts whose **server half** a wave-1 group built while the client half is
#: the next wave's first group (a wave-1 group does not edit ``web/static/``),
#: each with what the client must do. Not a waiver: the test beside each one
#: fails the moment the client reads the key, so the entry is deleted with the
#: client change rather than left behind as a blanket.
_AWAITING_CLIENT: dict[str, str] = {
    # Torment W1G1, madness (CR 702.35a): render the offer (card, cost, the
    # exile slot), let the seat tap lands while it is open (``tap`` /
    # ``activate`` answer it), open the ordinary cast dialog on the exiled
    # card and send its fields as ``madness_cast_confirm`` with
    # ``accept: true`` — or ``accept: false`` to decline. Ignore the exile
    # card's ``castable_now``: no priority is held during a resolution.
    "madness_cast": "madness_cast_confirm",
}


def test_every_prompt_has_a_client_renderer():
    js = APP_JS.read_text(encoding="utf-8")
    missing = sorted(
        spec.prompt_key
        for spec in CHOICE_SPECS.values()
        if not _client_reads(js, spec.prompt_key)
        and spec.prompt_key not in _AWAITING_CLIENT
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
        and spec.action not in _AWAITING_CLIENT.values()
    )
    assert not missing, f"prompt answers the client never sends: {missing}"


def test_a_prompt_awaiting_its_client_is_still_awaiting_it():
    """Each ``_AWAITING_CLIENT`` entry names a registered prompt the client
    neither reads nor answers yet. Once it does, the entry is stale and goes."""
    js = APP_JS.read_text(encoding="utf-8")
    keys = {spec.prompt_key: spec.action for spec in CHOICE_SPECS.values()}
    for key, action in _AWAITING_CLIENT.items():
        assert keys.get(key) == action, f"{key} is not a registered prompt answered by {action}"
        assert not _client_reads(js, key), f"the client reads {key} now: delete its entry"
        assert f'action: "{action}"' not in js, f"the client sends {action} now: delete its entry"


def test_the_auto_pass_asks_the_server_whether_a_prompt_is_owed():
    """The client's auto-pass must not pass priority while its seat owes a
    decision. It decided that from a hand-written list of prompt getters, which
    named 49 of the registry's 86 blocking kinds — with a library reorder, a
    search, a look-and-pick, a trigger's target or 33 others open it sent a
    ``pass_priority`` the server refused, and one that crossed the answer on
    the wire was accepted on the empty stack behind it. The state payload now
    carries the action gate's own answer (``waiting_on_prompt``), and the
    client reads it before anything it lists for itself."""
    js = APP_JS.read_text(encoding="utf-8")
    body = re.search(r"\nfunction hasBlockingPromptForAutoPass\(.*?\n\}\n", js, re.S).group(0)
    assert "state?.waiting_on_prompt" in body
    assert body.index("state?.waiting_on_prompt") < body.index("getCleanupDiscardInfo(state)")
