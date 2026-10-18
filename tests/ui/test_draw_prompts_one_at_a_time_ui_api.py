"""One draw at a time, over the wire (CR 121.2).

Phase 5 locked a game with two enchantments: Abundance and Pursuit of
Knowledge on one battlefield and Ancestral Recall on their controller. Draw
one — Pursuit, take the counter. Draw two — Abundance, then "Draw a card".
The state then carried ``effect_order`` and ``draw_becomes_counter``
together, ``draw_becomes_counter_confirm`` was a 400 "choose which effect
applies first" and ``effect_order_confirm`` a 400 "choose whether to take the
counter", and nothing a client could send was accepted.

The engine was arming the third draw's CR 616.1e order while the second
draw's Pursuit offer was still unanswered. A draw now waits for the one in
front of it (``Game._draw_prompt_open``), so the payload carries **one**
prompt of a draw's at a time and each is answered by its own action. These
are the bodies a client sends, in the order Phase 5 sent them.

The pool-wide form is ``tests/engine/test_draw_replacement_pair_census.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import _mk_card
from web.app import app, store

client = TestClient(app)

#: The prompt keys a draw replacement or its ordering can put in the payload.
_DRAW_PROMPTS = (
    "effect_order", "draw_becomes_counter", "reveal_until_kind_draw",
    "reorder_library",
)


def _session(set_pool, *names):
    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 4107},
    ).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.interactive_seats = {0, 1}
    me = game.players[0]
    pools = {"Abundance": "USG", "Pursuit of Knowledge": "STH"}
    permanents = [Permanent(card=set_pool(pools[name])[name]) for name in names]
    me.battlefield.extend(permanents)
    land = lambda n: _mk_card(name=n, type_line="Land")  # noqa: E731
    spell = lambda n: _mk_card(name=n, type_line="Artifact")  # noqa: E731
    me.library = [
        land("L1"), land("L2"), spell("S1"), land("L3"), spell("S2"),
        land("L4"), spell("S3"), land("L5"),
    ]
    me.hand = []
    return sid, game, me, permanents


def _owed(sid: str) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return {key: state[key] for key in _DRAW_PROMPTS if state.get(key)}


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _apply_first(sid: str, label: str):
    options = _owed(sid)["effect_order"]["options"]
    return _act(
        sid, action="effect_order_confirm", option_index=options.index(label),
    )


def test_abundance_and_pursuit_of_knowledge_on_a_three_card_draw(set_pool):
    sid, game, me, (_abundance, pursuit) = _session(
        set_pool, "Abundance", "Pursuit of Knowledge",
    )

    game._draw_with_replacements(me, 3)

    # Draw 1: both apply, so CR 616.1e is asked. Pursuit, and take the counter.
    assert list(_owed(sid)) == ["effect_order"]
    assert _apply_first(sid, "Pursuit of Knowledge").status_code == 200
    assert list(_owed(sid)) == ["draw_becomes_counter"]
    took = _act(sid, action="draw_becomes_counter_confirm", take_the_counter=True)
    assert took.status_code == 200, took.text
    assert counters_on(pursuit, "study") == 1

    # Draw 2: Abundance first, then "Draw a card" — its third option.
    assert list(_owed(sid)) == ["effect_order"]
    assert _apply_first(sid, "Abundance").status_code == 200
    assert list(_owed(sid)) == ["reveal_until_kind_draw"]
    declined = _act(sid, action="reveal_until_kind_draw_confirm", option_index=2)
    assert declined.status_code == 200, declined.text

    # The draw Abundance let through is Pursuit's to replace (CR 616.1f) — and
    # that is the only thing owed. The third draw has not begun: this is the
    # state that used to hold both prompts and accept neither answer.
    assert list(_owed(sid)) == ["draw_becomes_counter"]
    assert len(game.parked_draws) == 1
    drew = _act(sid, action="draw_becomes_counter_confirm", take_the_counter=False)
    assert drew.status_code == 200, drew.text
    assert [card.name for card in me.hand] == ["L1"]

    # Draw 3, released by that answer, asks its own order.
    assert list(_owed(sid)) == ["effect_order"]
    assert not game.parked_draws
    assert _apply_first(sid, "Pursuit of Knowledge").status_code == 200
    last = _act(sid, action="draw_becomes_counter_confirm", take_the_counter=True)
    assert last.status_code == 200, last.text

    assert _owed(sid) == {}
    assert counters_on(pursuit, "study") == 2
    assert [card.name for card in me.hand] == ["L1"]
    assert not game.parked_draws


def test_the_order_of_the_cards_abundance_bottoms_is_asked_before_the_next_draw(
    set_pool,
):
    """CR 401.4, and the neighbour the same lock was recorded under: the order
    prompt sat beside the second draw's Abundance offer and each answer was a
    400 naming the other."""
    sid, game, me, _permanents = _session(set_pool, "Abundance")

    game._draw_with_replacements(me, 2)

    assert list(_owed(sid)) == ["reveal_until_kind_draw"]
    nonland = _act(sid, action="reveal_until_kind_draw_confirm", option_index=0)
    assert nonland.status_code == 200, nonland.text

    owed = _owed(sid)
    assert list(owed) == ["reorder_library"], "the second draw waits for the order"
    prompt = owed["reorder_library"]
    assert prompt["position"] == "bottom" and prompt["top_count"] == 2
    assert [card["name"] for card in prompt["cards"]] == ["L1", "L2"]
    # The offer for the draw behind is refused by name while the order is
    # owed, because it does not exist yet.
    early = _act(sid, action="reveal_until_kind_draw_confirm", option_index=0)
    assert early.status_code == 400

    ordered = _act(sid, action="reorder_library_confirm", card_order=[1, 0])
    assert ordered.status_code == 200, ordered.text
    assert [card.name for card in me.library][-2:] == ["L2", "L1"]

    assert list(_owed(sid)) == ["reveal_until_kind_draw"]
    assert _act(
        sid, action="reveal_until_kind_draw_confirm", option_index=0,
    ).status_code == 200
    assert _owed(sid) == {}
    assert [card.name for card in me.hand] == ["S1", "S2"]
