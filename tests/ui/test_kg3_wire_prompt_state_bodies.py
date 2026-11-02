"""The bodies the client builds for the handlers that refuse on the prompt's
own state, posted with that state armed.

Known gap "The request-body guard derives presence, not shape": the static
guard (``test_kg_client_request_schemas.py``) reads a handler's refusals off
its source, and a refusal whose test reads anything but the request — "a
discard that is not *up to* needs its cards", "a choice that is not optional
needs its permanent", "in a game of three seats an activation names a seat" —
is conditional, so it is not held. The entry named ten such handlers.

So each is reached with its prompt armed: the scenario table every prompt kind
already has (``tests/regressions/test_kg_prompts_answered_choice_leaves_queue
.py``: a shipped card arms the kind for an interactive seat) arms it, the
census of request bodies (``tests/ui/js_requests.py``) gives every body the
client builds for its action, and each body is posted **with the keys the
client sends and no others** — a literal the client wrote as itself, any
other value the one the scenario's control sends for that key. A body naming
a key the scenario has no value for is the client's body for another shape of
the prompt and is not posted here; each kind posts at least one. Every posted
body must be taken (200) and the prompt answered.

The population is the entry's ten and every handler a refusal of which reads
the request beside the prompt's state, derived from the handlers' source
(``state_refusals``) — the derivation must stay inside the population.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

from tests.regressions.test_kg_prompts_answered_choice_leaves_queue import (
    SCENARIOS, _armed, _session_around, client, duel, on_board, wedges)
from web.action_registry import ACTION_HANDLERS
from engine.pending_choices import spec_for

from .js_requests import Script, load_scripts
from .test_kg_client_request_schemas import Census, census

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"

#: The entry's ten, each by the prompt kind that arms it (``activate`` is the
#: table of three seats, below), and the two the derivation adds.
POPULATION = {
    "discard_confirm": "discard",
    "enter_choice_confirm": "enter_choice",
    "face_down_cast_confirm": "face_down_cast",
    "outside_game_pick_confirm": "outside_game_pick",
    "permanent_choice_confirm": "permanent_choice",
    "pile_search_confirm": "pile_search",
    "put_from_hand_confirm": "put_from_hand_choice",
    "trigger_target_confirm": "trigger_target",
    "word_of_command_confirm": "word_of_command",
    "opponent_damage_choose": "opponent_damage",
    "activate": None,
    "resolve_optional_trigger": None,
}


# ---------------------------------------------------------------------------
# Which handlers refuse on state
# ---------------------------------------------------------------------------


def _missing_fields(node, req) -> set:
    found = set()
    for n in ast.walk(node):
        if (
            isinstance(n, ast.Compare) and isinstance(n.left, ast.Attribute)
            and isinstance(n.left.value, ast.Name) and n.left.value.id == req
            and len(n.ops) == 1 and isinstance(n.ops[0], (ast.Is, ast.IsNot))
            and isinstance(n.comparators[0], ast.Constant) and n.comparators[0].value is None
        ):
            found.add(n.left.attr)
        if (
            isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
            and isinstance(n.operand, ast.Attribute)
            and isinstance(n.operand.value, ast.Name) and n.operand.value.id == req
        ):
            found.add(n.operand.attr)
    return found


_PURE = {"None", "True", "False", "len", "int", "bool", "isinstance"}


def _reads_state(node, req) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id != req and n.id not in _PURE
        for n in ast.walk(node)
    )


def _lone_raise(body) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.Raise)


def state_refusals(func) -> list:
    """Every refusal of *func* (a handler) whose test reads a request field
    as missing **and** something that is not the request — ``if not
    req.discard_indices and not pending.get("up_to"): raise`` — or that ends
    an ``if``/``elif`` chain whose tests do (``else: raise`` after "a seat
    was named", "an id was sent", "two players")."""
    fn = ast.parse(textwrap.dedent(inspect.getsource(func))).body[0]
    req = fn.args.args[1].arg
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if _lone_raise(node.body) and _missing_fields(node.test, req) and _reads_state(node.test, req):
            found.append(frozenset(_missing_fields(node.test, req)))
        chain, tests = node, [node.test]
        while len(chain.orelse) == 1 and isinstance(chain.orelse[0], ast.If):
            chain = chain.orelse[0]
            tests.append(chain.test)
        if len(tests) > 1 and chain.orelse and _lone_raise(chain.orelse):
            fields = {
                n.attr for t in tests for n in ast.walk(t)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == req
            }
            if fields and any(_reads_state(t, req) for t in tests):
                found.append(frozenset(fields))
    return found


def test_the_derivation_reads_each_shape_and_stays_inside_the_population():
    derived = {
        kind for kind, spec in ACTION_HANDLERS.items() if state_refusals(spec.handler)
    }
    assert {"discard_confirm", "permanent_choice_confirm", "activate"} <= derived, derived
    assert frozenset({"permanent_id", "target_seat"}) in state_refusals(
        ACTION_HANDLERS["activate"].handler
    ), "the seat-or-id chain of a table of three"
    assert derived <= set(POPULATION), sorted(derived - set(POPULATION))


# ---------------------------------------------------------------------------
# The client's bodies, posted with the prompt armed
# ---------------------------------------------------------------------------


def _census_of(scripts) -> list:
    return Census(scripts).read


def _shipped() -> list:
    return census().read


def client_keys(action: str, read=None) -> tuple:
    """``(keys, declines, sites)`` of the bodies the client builds for
    *action*: every key any of them sends (``seat`` and ``action`` aside),
    the bodies that are nothing but ``accept: false`` (a decline, which the
    client offers only where the prompt says it may — not posted here), and
    where they are built."""
    keys, declines, sites = set(), 0, []
    for site, body in (read if read is not None else _shipped()):
        if site.url != "/api/sessions/{}/action" or not body.kinds or action not in body.kinds:
            continue
        sent = set(body.keys) - {"seat", "action"}
        if sent == {"accept"} and any(
            site.script.code[slice(*_trimmed(value))] == "false" for value in body.value_of("accept")
        ):
            declines += 1
            continue
        keys |= sent
        sites.append(body.where())
    return keys, declines, sites


def _trimmed(value):
    script, a, b, _ctx = value
    from .js_requests import _trim

    return _trim(script.code, a, b)


def _post_with_client_keys(game, choice, action: str, wire: dict, keys: set):
    """Post, with the prompt armed, every field the scenario's control sends
    that the client also sends — no field the client never builds."""
    body = {"seat": choice.player_index, "action": action}
    body.update({key: value for key, value in wire.items() if key in keys})
    sid = _session_around(game)
    return body, client.post(f"/api/sessions/{sid}/action", json=body)


@pytest.mark.parametrize(
    "action", sorted(a for a, kind in POPULATION.items() if kind is not None)
)
def test_what_the_armed_prompt_requires_is_what_the_client_sends(action):
    kind = POPULATION[action]
    assert spec_for(kind).action == action
    keys, _declines, sites = client_keys(action)
    assert sites, f"the client builds no {action} body"
    s, game, choice = _armed(kind)
    wire = s.wire(game, choice)
    missing = sorted(set(wire) - keys)
    assert missing == [], f"{action}: the armed prompt takes {missing}, which no client body sends ({sites})"
    held = choice.data.get("_stack_item")
    body, answered = _post_with_client_keys(game, choice, action, wire, keys)
    assert answered.status_code == 200, (body, answered.text)
    assert wedges(game, choice, held) == [], body
    if s.then is not None:
        s.then(game)


def test_an_activation_at_a_table_of_three_names_its_permanent_or_a_seat():
    """``activate`` refuses a body naming neither ``target_seat`` nor
    ``permanent_id`` once a third seat is at the table — a refusal on the
    table's state. Every activation body the client builds names one, and
    one built of the client's own keys is taken at a table of three
    (Pestilence, no target)."""
    read = _shipped()
    bodies = [
        (site, body) for site, body in read
        if site.url == "/api/sessions/{}/action" and body.kinds and "activate" in body.kinds
    ]
    assert len(bodies) >= 10, len(bodies)
    naming_neither = [
        body.where() for _site, body in bodies
        if not body.open and not ({"permanent_id", "target_seat"} & set(body.keys))
    ]
    assert naming_neither == [], naming_neither

    game = duel(boards=(("Pestilence",), (), ()), seats=3)
    pest = on_board(game, 0, "Pestilence")
    keys, _declines, _sites = client_keys("activate")
    body = {"seat": 0, "action": "activate"}
    body.update({
        key: value for key, value in {
            "permanent_id": pest.permanent_id, "ability_index": 0,
        }.items() if key in keys
    })
    sid = _session_around(game)
    answered = client.post(f"/api/sessions/{sid}/action", json=body)
    assert answered.status_code == 200, (body, answered.text)
    assert game.stack, "the ability is on the stack"


def test_a_mandatory_upkeep_trigger_is_answered_with_the_keys_the_client_sends():
    """``resolve_optional_trigger`` refuses ``accept: false`` for a mandatory
    trigger and refuses an answer without its address where the prompt has
    one (the prompt's state). Erhnam Djinn's upkeep trigger — mandatory, aimed
    at a creature, addressed by its permanent — is answered with the client's
    keys."""
    from tests.ui.test_upkeep_prompt_wire import _erhnam_upkeep

    sid, game, _bears, giant = _erhnam_upkeep()
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = state["optional_trigger"]["pending"]
    wire = {
        "card_name": entry["card_name"], "accept": True,
        "target_permanent_id": giant.permanent_id,
    }
    if entry.get("permanent_id") is not None:
        wire["prompt_permanent_id"] = entry["permanent_id"]
    keys, _declines, sites = client_keys("resolve_optional_trigger")
    assert sorted(set(wire) - keys) == [], sites
    body = {"seat": 0, "action": "resolve_optional_trigger", **wire}
    answered = client.post(f"/api/sessions/{sid}/action", json=body)
    assert answered.status_code == 200, (body, answered.text)
    assert game._has_keyword(giant, "forestwalk")


def test_a_client_body_missing_what_the_state_requires_is_named():
    """Backwards, every run: the discard body without its cards — required
    only while the discard is not *up to*, so the static guard cannot see it
    — in a copy of ``app.js``, is named against the armed prompt, and posted
    without them the server refuses it."""
    path = STATIC / "app.js"
    source = path.read_text(encoding="utf-8")
    old = 'action: "discard_confirm", discard_indices: indices, to_library: toLibrary'
    assert source.count(old) == 1
    broken = source.replace(old, 'action: "discard_confirm", to_library: toLibrary')
    scripts = [Script(path, source=broken) if s.name == "app.js" else s for s in load_scripts(STATIC)]
    keys, _declines, _sites = client_keys("discard_confirm", read=_census_of(scripts))
    s, game, choice = _armed("discard")
    wire = s.wire(game, choice)
    assert set(wire) - keys == {"discard_indices"}
    _body, refused = _post_with_client_keys(game, choice, "discard_confirm", wire, keys)
    assert refused.status_code == 400 and "discard_indices" in refused.json()["detail"]
