"""A divided announcement whose targets are **not interchangeable**, through
the spec a browser receives and the order of the list it sends.

"The next X damage that would be dealt to target creature, planeswalker, or
player this turn is dealt to another target creature, planeswalker, or player
instead." (Captain's Maneuver.) "…1 damage to any target, 2 damage to another
target, and 3 damage to a third target." (Cone of Flame.)

Both are answered through the ``divided`` picker, and both are read by the
engine **by position**: the Maneuver's first target is the one protected and
its second the one that takes the damage; the Cone's first gets 1. The picker
said neither — and it sent every creature before every face whatever order
they were clicked in, so a face clicked first took the *second* target's job.
Two things are pinned:

* the spec names the positions (``target_roles``), in the engine's order, and
  carries nothing of the kind for a spell whose targets are interchangeable;
* the list on the wire is read in the order it is sent, which is the order the
  client now sends its clicks in.

It also carries the card's own per-target increase (``per_target_tax``), so a
divided spell that prints none is not taxed Fireball's.

Driven in a browser as a human seat for wave 2: Captain's Maneuver with the
caster's own face clicked first and an opposing Hill Giant second (X offered up
to the whole pool; a Lightning Bolt at the caster then dealt 2 to the Giant and
1 to the caster); Cone of Flame at a face, a creature and a face in that order
(1, 2 and 3 landed in click order); Fireball as the neighbour (still taxed, the
old words). The text-level test is the ratchet on that.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from tests.helpers import app_js_function_body

client = TestClient(app)


def _session(set_pool, hand):
    """Seat 0 to act holding *hand*, with a Hill Giant under seat 1."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 6014,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
        player.hand.clear()
    giant = Permanent(card=set_pool("LEA")["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    game.players[0].hand.extend(hand)
    session.current_turn = 0
    game.start_turn(0)
    game._settle()
    game.current_phase = "main"
    return sid, game, giant


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _spec(sid: str, name: str) -> dict:
    return next(
        c for c in _state(sid)["players"][0]["hand"] if c["name"] == name
    )["target_spec"]


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_a_card_that_shares_by_position_names_its_positions(set_pool):
    """Cone of Flame, shipped: the first target gets 1, the second 2, the
    third 3 — said on the spec, in that order."""
    sid, _game, _giant = _session(set_pool, [set_pool("WTH")["Cone of Flame"]])

    spec = _spec(sid, "Cone of Flame")

    assert spec["kind"] == "divided" and spec["divided_target_count"] == 3
    assert spec["target_roles"] == [
        "target that gets 1", "target that gets 2", "target that gets 3",
    ]
    assert "per_target_tax" not in spec


def test_a_spell_whose_targets_are_interchangeable_names_none(set_pool):
    """The neighbour: Fireball divides evenly, so no position means anything —
    and it is the card that prints the per-target increase."""
    sid, _game, _giant = _session(set_pool, [set_pool("LEA")["Fireball"]])

    spec = _spec(sid, "Fireball")

    assert spec["kind"] == "divided" and "target_roles" not in spec
    assert spec["per_target_tax"] == {"amount": 1, "life": False, "beyond_first": True}


def test_the_list_is_read_in_the_order_it_is_sent(set_pool):
    """A face first and a creature second, the order the old client could not
    send: the face takes the 1 and the Giant the 2."""
    sid, game, giant = _session(set_pool, [set_pool("WTH")["Cone of Flame"]])

    sent = _act(
        sid, seat=0, action="cast", card_name="Cone of Flame",
        divided_targets=[{"seat": 1}, {"seat": 1, "index": 0}, {"seat": 0}],
    )
    assert sent.status_code == 200, sent.text
    game.resolve_top_of_stack()

    assert game.players[1].life == 19 and game.players[0].life == 17
    assert giant.damage_marked == 2


def test_the_client_names_the_slots_and_sends_its_clicks_in_order():
    """The ratchet on what was driven: the picker reads ``target_roles``, keeps
    one click-ordered list beside its two by-kind ones, builds the wire list
    from it, refuses a click past the printed count, and prices extra targets
    from the spec rather than from an assumption."""
    assert "target_roles" in app_js_function_body("dividedSlotRoles")
    start = app_js_function_body("startCastDividedPrompt")
    assert "dividedOrder: []" in start

    for toggle in ("toggleDividedCreatureTarget", "setDividedFaceTarget"):
        body = app_js_function_body(toggle)
        assert "p.dividedOrder = " in body, toggle
        assert "dividedPicksAreFull(p)" in body, toggle

    confirm = app_js_function_body("confirmDividedTargets")
    assert "dividedPicksInOrder(p).map(" in confirm
    # The old spelling — every creature, then every face — is gone.
    assert "...p.dividedTargets.map((t) => ({ seat: t.seat, index: t.idx }))" not in confirm
    assert "dividedExtraTargetTax(card, n)" in confirm

    rows = app_js_function_body("dividedSlotRowsHtml")
    assert "dividedPicksInOrder(p)" in rows and "data-divided-slot" in rows
    panel = app_js_function_body("renderActivationPrompt")
    assert "dividedSlotRowsHtml()" in panel

    tax = app_js_function_body("dividedExtraTargetTax")
    assert "per_target_tax" in tax and "tax.beyond_first" in tax
    hint = app_js_function_body("dividedTargetsHint")
    assert "dividedSlotRoles(pendingCastTarget?.card)" in hint
    assert "dividedExtraTargetTax(pendingCastTarget?.card, n)" in hint
