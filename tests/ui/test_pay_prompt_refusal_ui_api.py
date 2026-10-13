""" "Pay" over the wire: an answer, or a 400 that keeps the prompt.

Phase 5: Mana Leak ({3}) on a human's Lightning Bolt with mana untapped that
the engine does not tap for a payer — a filter land, a Sol Ring.
``{"action":"confirm_mana_payment","accept":true}`` was a 200, the log read
"Lightning Bolt was countered by Mana Leak", nothing was tapped and nothing
was said. The engine plans free land taps only, and a plan that came up short
was carried out as a decline.

What a client is sent and may send now:

* the prompt carries ``payable`` — whether "pay" would be accepted as the
  board stands;
* an accept that would not be is a **400** naming what to do, and the prompt
  is still owed;
* while it is owed the seat may tap for mana — ``tap`` on a land, ``activate``
  on a *mana* ability, whoever holds priority (CR 605.3a) — and nothing else;
* then the same accept is a 200.

The rules are ``tests/rules/test_pay_is_not_read_as_decline.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.game_types import StackItem
from engine.models import Permanent
from tests.helpers import _mk_card
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.turn_steps import _gather_upkeep_decisions

client = TestClient(app)


def _ready(name: str) -> Permanent:
    permanent = Permanent(card=CARD_BY_NAME[name.lower()])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _session(*names):
    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 2207},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    game.interactive_seats = {0, 1}
    me = game.players[0]
    me.battlefield = [_ready(name) for name in names]
    me.mana_pool = {symbol: 0 for symbol in me.mana_pool}
    game._settle()
    return sid, session, game, me


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _mana_leak(game) -> StackItem:
    bolt = StackItem(
        card=CARD_BY_NAME["lightning bolt"], caster_index=0,
        target_player_index=1, target_permanent_index=None, x_value=None,
    )
    game.stack.append(bolt)
    game.arm_pending_choice(
        "mana_payment", 0, amount=3, card_name="Mana Leak",
        counter_card=CARD_BY_NAME["mana leak"], stack_item=bolt,
    )
    return bolt


def test_pay_with_a_sol_ring_untapped_is_refused_then_paid_by_hand():
    sid, _session_, game, me = _session("Island", "Sol Ring", "Prodigal Sorcerer")
    bolt = _mana_leak(game)

    prompt = _state(sid)["mana_payment"]
    assert prompt["cost"] == "{3}" and prompt["payable"] is False

    refused = _act(sid, action="confirm_mana_payment", accept=True)
    assert refused.status_code == 400
    assert "tap for the mana first" in refused.json()["detail"]
    # Still owed, still on the stack, and nothing was tapped for it.
    assert _state(sid)["mana_payment"] is not None
    assert any(item is bolt for item in game.stack)
    assert not any(permanent.tapped for permanent in me.battlefield)
    assert not any("countered" in line for line in game.log)

    # Not a way to act around the prompt: only a mana ability is admitted.
    ping = _act(
        sid, action="activate", permanent_name="Prodigal Sorcerer", target_seat=1,
    )
    assert ping.status_code == 400
    assert "only a mana ability" in ping.json()["detail"]
    assert len(game.stack) == 1

    # …and a bare tap of the Ring would tap it for nothing: refused too.
    bare = _act(sid, action="tap", permanent_name="Sol Ring")
    assert bare.status_code == 400
    assert "activate the permanent's mana ability" in bare.json()["detail"]
    assert not any(permanent.tapped for permanent in me.battlefield)

    # The Ring is the payer's own to tap (CR 605.3a), mid-resolution.
    ring = _act(sid, action="activate", permanent_name="Sol Ring")
    assert ring.status_code == 200, ring.text
    assert me.mana_pool.get("C", 0) == 2
    assert _state(sid)["mana_payment"]["payable"] is True

    paid = _act(sid, action="confirm_mana_payment", accept=True)
    assert paid.status_code == 200, paid.text
    assert _state(sid)["mana_payment"] is None
    assert any(item is bolt for item in game.stack), "paid for, not countered"
    assert all(
        permanent.tapped for permanent in me.battlefield
        if permanent.card.name in ("Island", "Sol Ring")
    )
    assert sum(me.mana_pool.values()) == 0


def test_an_ability_that_draws_is_not_a_way_to_pay():
    """CR 605.1a's fourth criterion on the wire. "{1}, {T}, Sacrifice this
    artifact: Add one mana of any color. Draw a card." (Chromatic Sphere)
    moves a card from a library, so it is not a mana ability - its ruling of
    2026-08-05: "it can't be activated in the middle of paying for a cost."
    The payment prompt admits a mana ability and nothing else, so the Sphere
    is refused where the Sol Ring beside it is not, and it is still on the
    battlefield, untapped, afterwards."""
    sid, _session_, game, me = _session("Island", "Chromatic Sphere", "Sol Ring")
    me.mana_pool["C"] = 1          # the Sphere's own {1} is not what refuses it
    bolt = _mana_leak(game)

    sphere = _act(sid, action="activate", permanent_name="Chromatic Sphere", mana_color="U")
    assert sphere.status_code == 400
    assert "only a mana ability" in sphere.json()["detail"]
    assert [p.card.name for p in me.battlefield] == ["Island", "Chromatic Sphere", "Sol Ring"]
    assert not any(permanent.tapped for permanent in me.battlefield)
    assert len(game.stack) == 1 and me.mana_pool.get("C", 0) == 1

    ring = _act(sid, action="activate", permanent_name="Sol Ring")
    assert ring.status_code == 200, ring.text
    assert me.mana_pool.get("C", 0) == 3
    paid = _act(sid, action="confirm_mana_payment", accept=True)
    assert paid.status_code == 200, paid.text
    assert any(item is bolt for item in game.stack), "paid for, not countered"


def test_declining_is_still_one_request():
    sid, _session_, game, me = _session("Island", "Sol Ring")
    bolt = _mana_leak(game)

    declined = _act(sid, action="confirm_mana_payment", accept=False)

    assert declined.status_code == 200, declined.text
    assert not any(item is bolt for item in game.stack)
    assert [card.name for card in me.graveyard][-1:] == ["Lightning Bolt"]


def test_an_optional_offer_says_whether_yes_would_be_accepted():
    """ "…unless you pay {2}" beside a Sol Ring: offered to a person (it used
    not to be), ``payable`` false until they tap, and a "yes" before that is a
    400 that keeps the offer."""
    from engine.game_types import OracleExecutionContext
    from engine.oracle import compile_card_oracle

    sid, _session_, game, me = _session("Sol Ring")
    card = _mk_card(
        "Census Toll", "{2}", "Enchantment",
        "At the beginning of your upkeep, return Census Toll to its owner's "
        "hand unless you pay {2}.",
    )
    toll = Permanent(card=card)
    me.battlefield.append(toll)
    game._execute_oracle_instruction(
        compile_card_oracle(card).triggered_abilities[0].instruction,
        OracleExecutionContext(caster=me, target=me, card=card, source_permanent=toll),
    )

    (offer,) = _state(sid)["optional_pay"]["pending"]
    assert offer["card_name"] == "Census Toll" and offer["payable"] is False

    early = _act(sid, action="resolve_optional_pay", accept=True, card_name="Census Toll")
    assert early.status_code == 400
    assert "tap for the mana first" in early.json()["detail"]
    assert game.is_on_battlefield(toll)

    assert _act(sid, action="activate", permanent_name="Sol Ring").status_code == 200
    assert _state(sid)["optional_pay"]["pending"][0]["payable"] is True
    paid = _act(sid, action="resolve_optional_pay", accept=True, card_name="Census Toll")
    assert paid.status_code == 200, paid.text
    assert game.is_on_battlefield(toll)
    assert _state(sid)["optional_pay"] is None


def test_a_second_upkeep_price_the_board_cannot_also_cover_is_refused():
    """Two Breeding Pits ({B}{B} each) and {B}{B} floating. Each read "can
    pay" on its own, both accepts were taken, the first was paid — and the
    second, unpayable when its turn came, was sacrificed: a "Pay" carried out
    as a "don't"."""
    sid, session, game, me = _session()
    kept, other = _ready("Breeding Pit"), _ready("Breeding Pit")
    me.battlefield = [kept, other]
    me.mana_pool["B"] = 2
    game._settle()
    game._set_phase_and_step("beginning", "upkeep")
    _gather_upkeep_decisions(session, 0)

    can_pay = _state(sid)["upkeep_pay"]["can_pay"]
    assert can_pay == {str(kept.permanent_id): True, str(other.permanent_id): True}

    first = _act(
        sid, action="pay_upkeep", card_name="Breeding Pit",
        prompt_permanent_id=kept.permanent_id,
    )
    assert first.status_code == 200, first.text
    assert _state(sid)["upkeep_pay"]["can_pay"][str(other.permanent_id)] is False

    second = _act(
        sid, action="pay_upkeep", card_name="Breeding Pit",
        prompt_permanent_id=other.permanent_id,
    )
    assert second.status_code == 400
    assert "cannot pay upkeep cost" in second.json()["detail"]
    # Still theirs to answer — with the answer they can give.
    assert [c["permanent_id"] for c in _state(sid)["upkeep_pay"]["pending"]] == [
        other.permanent_id
    ]
