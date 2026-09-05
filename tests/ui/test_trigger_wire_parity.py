"""Triggers that only the *wire* can miss — the headless/wire parity guard.

Every per-set test drives a ``Game`` directly. The running app drives
``web/actions.py``, which resolves ``target_permanent_ids`` off the request and
then takes a **different branch** into the engine. For as long as those two
branches can diverge, a card can be green in the whole suite and dead for every
real player — and that is not a hypothetical:

``Game._stack_push_object`` used to stamp a target's identity through three
exits and announce the targeting at the end of the last of them. The middle exit
is the one the web layer always takes. So **every "becomes the target" trigger
in the pool fired in every test and never once in the app**. Warden of the Woods
is shipped and manually verified; it never worked. No instrument in this repo
could see it: the cards compile supported, carry no hollow line, claim every
printed sentence, and their tests drive the path that happens to announce.

The fix split the function so the announcement cannot be skipped. This file is
the guard against the *class*, and it is deliberately a **runtime parity** test
rather than a static one. A static rule was tried first — "a seam call at a
function's top level must not sit behind an early return" — and it does catch
the original bug, but it flags 33 sites in today's engine and every one of them
is a legitimate guard clause returning before anything happened. A gate whose
findings are ~100% false positives is not a gate; it trains its reader to skip
it, which is worse than not having it.

What is asked here instead is the property that actually matters: **drive the
same board through both entry points and demand the same outcome.** No false
positives are possible, because the oracle is the other path rather than a
guess about shape.
"""

from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_LEA = {c.name: c for c in load_cards(LEA_PATH)}

#: An invented watcher, so this is about the *shape* rather than about one
#: printed card. Any permanent whose trigger fires on being targeted will do,
#: and the pool's real ones (Warden of the Woods, Skulking Ghost, Forsaken
#: Wastes) are covered by their own set tests.
#:
#: A **creature**, because the spell pointed at it has to be one the targeting
#: rules admit: "any target" (CR 115.4) reaches a creature, a player or a
#: planeswalker, and an enchantment is none of those. The first draft of this
#: file made the watcher an enchantment and the wire answered "no valid target"
#: — a refusal that is correct, and that would have been read as the trigger
#: failing.
_WATCHER_TEXT = (
    "Whenever this creature becomes the target of a spell, "
    "that spell's controller loses 5 life."
)


def _watcher_card():
    template = _LEA["Grizzly Bears"]
    return dataclasses.replace(
        template,
        name="Watcher",
        oracle_text=_WATCHER_TEXT,
        keywords=(),
    )


def _session(seed: int = 4242):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai", "host_name": "H",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0

    watcher = Permanent(card=_watcher_card())
    game.players[1].battlefield = [watcher]
    game.players[0].battlefield = []
    game.players[0].hand = [_LEA["Lightning Bolt"]]
    game.players[0].life = 20
    game._recompute_continuous_effects()
    return sid, game, watcher


def test_a_becomes_target_trigger_fires_when_the_cast_comes_off_the_wire():
    """The regression, on the path that was broken.

    The cast names its target by ``target_permanent_ids`` — the **plural**
    field, which is the one that matters. ``web/actions.py`` resolves the
    singular ``target_permanent_id`` to an index before it reaches the engine,
    so a test using it takes the ordinary path and would have passed against the
    bug; the plural list is what routes through the exit that skipped the
    announcement. Proven by reintroducing the regression and watching the
    singular version stay green while this one goes red. Asserted on the *life total* rather than on the log, because
    a log line is a description and the life loss is the effect.
    """
    sid, game, watcher = _session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Lightning Bolt",
            "target_seat": 1,
            "target_permanent_ids": [watcher.permanent_id],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert game.players[0].life == 15, (
        "the caster did not lose 5 life, so the becomes-target trigger never "
        "fired on the wire path — the exact shape that made every such trigger "
        "in the pool dead in the running app while green in every test"
    )


def test_the_wire_and_the_engine_agree_about_the_trigger():
    """Parity, which is the general form of the test above.

    Two identical boards; one cast driven through ``web/actions.py`` and one
    driven straight at the engine. Any divergence between the entry points
    shows up here whatever causes it — a skipped announcement, a target
    resolved differently, a step the wire takes and the engine does not. The
    oracle is the other path, so this cannot produce a false positive the way a
    static shape rule does.
    """
    sid, wire_game, wire_watcher = _session(seed=11)
    client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Lightning Bolt",
            "target_seat": 1,
            "target_permanent_ids": [wire_watcher.permanent_id],
        },
    )
    wire_game._settle()

    _sid2, engine_game, engine_watcher = _session(seed=11)
    engine_game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_index=engine_game.players[1].battlefield.index(
            engine_watcher
        ),
    )
    engine_game._settle()

    assert wire_game.players[0].life == engine_game.players[0].life, (
        "the two entry points disagree about the caster's life: wire "
        f"{wire_game.players[0].life}, engine {engine_game.players[0].life}"
    )
    assert wire_game.players[1].life == engine_game.players[1].life
    assert (
        [p.card.name for p in wire_game.players[1].battlefield]
        == [p.card.name for p in engine_game.players[1].battlefield]
    ), "the two entry points left different boards behind"


def test_the_singular_and_plural_target_fields_take_the_same_path():
    """The divergence underneath the bug, pinned directly.

    ``web/actions.py`` accepts a target as ``target_permanent_id`` (resolved to
    an index before it reaches the engine) *or* as ``target_permanent_ids`` (a
    list handed down as identities). Those are two entry points into the engine
    and they were not equivalent: the list form took the exit that skipped the
    targeting announcement, and the singular form did not.

    That asymmetry is what made the bug survivable — a test written with either
    field passes, and only one of them exercises the path the client uses. So
    the two fields are held to the same outcome here, which generalises past
    the one trigger above: any future divergence between them fails, whatever
    it is about.
    """
    outcomes = {}
    for label, payload in (
        ("singular", lambda w: {"target_permanent_id": w.permanent_id}),
        ("plural", lambda w: {"target_permanent_ids": [w.permanent_id]}),
    ):
        sid, game, watcher = _session(seed=77)
        resp = client.post(
            f"/api/sessions/{sid}/action",
            json={
                "seat": 0,
                "action": "cast",
                "card_name": "Lightning Bolt",
                "target_seat": 1,
                **payload(watcher),
            },
        )
        assert resp.status_code == 200, f"{label}: {resp.text}"
        game._settle()
        outcomes[label] = (
            game.players[0].life,
            game.players[1].life,
            [p.card.name for p in game.players[1].battlefield],
        )

    assert outcomes["singular"] == outcomes["plural"], (
        "naming the same target by the singular field and by the list produced "
        f"different games: {outcomes}"
    )
