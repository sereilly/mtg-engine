"""Regression: a *cast* announcing CR 609.7a's "a source of your choice".

The phrase is not a target (CR 115.1), so it rides its own trio of request
fields — ``source_seat``/``source_permanent_index`` (or ``source_permanent_id``,
which the action preamble resolves) and ``source_stack_index``. Those fields
have been in ``web/schemas.py`` since Jade Monolith and were forwarded by the
**activate** branch alone: ``_queue_spell_from_request`` dropped them, and
``mixins/stack/casting.py`` had no parameters to receive them if it hadn't.

So every spell printing the phrase recorded no source and armed the documented
"answers to any source" fallback. Five of the six get away with it because they
name nothing else and their source rides their own target slot; Honorable
Passage names an "any target" as well, so it had nowhere to put the source and
went sourceless every single cast. It is bounded (``uses=1``, spent on one
instance either way), which is why nobody saw it.

Kor Chant is the printing that could not survive the fallback — a *blanket*
record for the turn, so any-source would have moved every point of damage dealt
all turn — and it stayed unsupported until this channel existed. Both are
asserted here, over HTTP, because the wire is where the fields were being lost:
the engine paths and the browser picker were each half-built and neither could
show it alone.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)

_VIS = {c.name: c for c in load_cards(manifest_set_path("VIS"))}
_EXO = {
    c.name: c for c in load_cards(manifest_set_path("EXO", include_measured=True))
}


def _goblin(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{R}", cmc=2.0, type_line="Creature — Goblin",
        oracle_text="", colors=("R",), color_identity=("R",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Goblin", "power": "3",
             "toughness": "3", "colors": ["R"]},
    )


def _session(hand, mine, theirs):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 611,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = list(hand)
    game.players[0].battlefield = list(mine)
    game.players[1].battlefield = list(theirs)
    for permanent in list(mine) + list(theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    session.current_turn = 0
    game.active_player_index = 0
    return sid, game


def test_honorable_passages_shield_answers_the_source_the_cast_named():
    """The bug, on the card that shipped with it. With the source on the wire
    the shield is CR 615.8's — the *next* damage from *that* source — and an
    unchosen source's damage is dealt normally.

    Sent by id, which is the addressing the whole client uses: the preamble in
    ``web/actions.py`` resolves it to the seat and slot the engine takes.
    """
    chosen, other = Permanent(card=_goblin("Chosen")), Permanent(card=_goblin("Other"))
    sid, game = _session([_VIS["Honorable Passage"]], [], [chosen, other])

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Honorable Passage",
            "target_seat": 0,
            "source_permanent_id": chosen.permanent_id,
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    from tests.helpers import _damage_dealt

    assert _damage_dealt(game, game.players[0], 3, source=other) == 3, (
        "the shield was armed against a source the caster never named"
    )
    assert _damage_dealt(game, game.players[0], 3, source=chosen) == 0


def test_kor_chant_carries_two_targets_and_a_source_in_one_request():
    """The three announcements a spell can make at once, all on the wire:
    ``target_permanent_ids`` in role order (CR 601.2c) and the source beside
    them (CR 609.7a).

    The blanket record is what the last assertion checks — the chosen source's
    *second* hit of the turn moves too, which a ``uses`` of 1 would not.
    """
    mine = Permanent(card=_goblin("Mine"))
    taker, source = Permanent(card=_goblin("Taker")), Permanent(card=_goblin("Src"))
    sid, game = _session([_EXO["Kor Chant"]], [mine], [taker, source])

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Kor Chant",
            "target_seat": 0,
            "target_permanent_ids": [mine.permanent_id, taker.permanent_id],
            "source_permanent_id": source.permanent_id,
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    game._mark_damage_on_permanent(mine, 3, source=source)
    assert (mine.damage_marked, taker.damage_marked) == (0, 3)

    game._mark_damage_on_permanent(mine, 2, source=taker)
    assert mine.damage_marked == 2, "only the chosen source's damage moves"

    game._mark_damage_on_permanent(mine, 1, source=source)
    assert taker.damage_marked == 4, "'all damage … this turn' is not one instance"


def test_the_cast_picker_offers_a_source_list_for_every_spell_that_asks():
    """``requires_source`` tells the browser to run a source stage;
    ``source_targets`` is the list it runs *over*, and the stage refuses on an
    empty one. Filled in on the activation path only, so a cast carrying the
    flag read as "no damage source available" — a missing feature wearing a
    plausible refusal.

    Asked of the two shapes that reach it by different routes: an ordinary
    target walk (Honorable Passage) and a **roles** walk (Kor Chant), whose spec
    returns before the function's tail.
    """
    chosen = Permanent(card=_goblin("Chosen"))
    mine = Permanent(card=_goblin("Mine"))
    sid, game = _session(
        [_VIS["Honorable Passage"], _EXO["Kor Chant"]], [mine], [chosen]
    )

    for name in ("Honorable Passage", "Kor Chant"):
        spec = game.cast_target_spec(0, next(
            card for card in game.players[0].hand if card.name == name
        ))
        assert spec.get("requires_source") is True, name
        assert {entry["name"] for entry in spec["source_targets"]} == {
            "Mine", "Chosen",
        }, name



#: Reading one walk's body out of ``app.js`` is asked by two modules now —
#: this one, and ``tests/ui/test_cast_target_kinds.py``, which sweeps the pool
#: for the *kinds* that reach these walks — so it lives in ``tests/helpers``.
_js_function_body = app_js_function_body


def test_both_cast_target_walks_reach_the_chosen_source_stage():
    """The browser half of the same bug, and the shape of it.

    The source stage existed — it is how Jade Monolith's activation asks — but
    it sat inside ``if (pending.castAction === "activate")``, so a *cast* ran
    every other stage and fell straight past this one. There are two cast walks
    that can end at a spell needing a source, and they end in different
    functions: an ordinary single-target walk finishes in
    ``resolvePendingCastTarget`` and a roles walk in ``confirmRoleTargets``,
    which never touches the first at all. A stage wired into one of them is a
    card that silently sends no source, which is the failure this guard is for.
    """
    for walk in ("resolvePendingCastTarget", "confirmRoleTargets"):
        assert "startCastChosenSourceStage(" in _js_function_body(walk), (
            f"{walk} never offers the chosen-source stage, so a spell whose "
            f"cast spec carries requires_source is sent without one"
        )


def test_both_source_clicks_send_the_body_the_stage_stashed():
    """The answer comes back on two different clicks — a permanent on the
    battlefield or a spell on the stack (CR 609.7a admits both) — and each is
    handled by a different function. Both merge into ``__sourceBody``, the cast
    body the stage stashed; a send site that built its own body instead would
    drop whatever the walk before it had collected, which for Kor Chant is both
    of its targets.
    """
    for click in ("resolvePendingCastTarget", "selectStackSpellTarget"):
        body = _js_function_body(click)
        assert "__sourceBody" in body and "sendCastWithChosenSource(" in body, click
