"""Two offers on one printed line each say what *their* yes does.

Chain of Vapor: "Return target nonland permanent to its owner's hand. Then
that permanent's controller may sacrifice a land of their choice. If the
player does, they may copy this spell and may choose a new target for that
copy." Both offers are ``may`` steps of the one line — the second nested in
the first's accept branch — and ``web/prompt_values.offer_wording`` could not
tell them apart, so the person deciding whether to sacrifice a land and the
person deciding whether to copy were both shown the whole line (the
"Face-down leftovers on the wire" Known-gaps entry). The offer's own step now
rides the prompt (``_offer``) and is paired with its sentence by position
among the unit's ``may`` steps (``_paired_offer``), only where the two lists
are as long as each other.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store
from web.prompt_values import _offer_sentences, _paired_offer, _preorder

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

_SACRIFICE = "Then that permanent's controller may sacrifice a land of their choice."
_COPY = (
    "If the player does, they may copy this spell and may choose a new target "
    "for that copy."
)


def _chain_of_vapor_at_my_own_bears():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Island", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.players[1].hand.clear()
    placed = {}
    for name in ("Grizzly Bears", "Island", "Mountain"):
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        placed[name] = permanent
    game.players[0].hand.append(_CARDS["Chain of Vapor"])
    game.start_priority_window(0)
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Chain of Vapor",
        "hand_index": len(game.players[0].hand) - 1,
        "target_permanent_id": placed["Grizzly Bears"].permanent_id,
    })
    assert cast.status_code == 200, cast.text
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_chain_of_vapors_two_offers_each_carry_their_own_sentence():
    sid, game = _chain_of_vapor_at_my_own_bears()
    shown = []
    for _ in range(12):
        state = _state(sid)
        if state.get("optional_pay"):
            offer = state["optional_pay"]["pending"][0]
            shown.append(offer["card_text"])
            answer = client.post(f"/api/sessions/{sid}/action", json={
                "seat": 0, "action": "resolve_optional_pay",
                "card_name": "Chain of Vapor", "accept": True,
            })
            assert answer.status_code == 200, answer.text
        elif state.get("sacrifice_select"):
            pick = state["sacrifice_select"]["permanents"][0]["index"]
            answer = client.post(f"/api/sessions/{sid}/action", json={
                "seat": 0, "action": "sacrifice_confirm", "sacrifice_indices": [pick],
            })
            assert answer.status_code == 200, answer.text
        elif not state["stack"]:
            break
        else:
            client.post(f"/api/sessions/{sid}/action", json={
                "seat": 0, "action": "pass_priority",
            })
    assert shown == [_SACRIFICE, _COPY], shown
    assert any("sacrificed" in line and "(Chain of Vapor)" in line for line in game.log)
    assert any("copied Chain of Vapor" in line for line in game.log), game.log[-10:]


def test_a_pairing_is_made_only_where_the_steps_and_sentences_agree():
    chain = _CARDS["Chain of Vapor"]
    program = compile_card_oracle(chain)
    mays = [
        step for root in program.instructions for step in _preorder(root)
        if step.kind == "may"
    ]
    assert len(mays) == 2
    line = chain.oracle_text
    assert [_paired_offer(chain, step, line) for step in mays] == [_SACRIFICE, _COPY]
    # A step of another card, or none at all, pairs nothing.
    assert _paired_offer(chain, None, line) is None
    other = _CARDS["Grizzly Bears"]
    assert _paired_offer(other, mays[0], other.oracle_text or "") is None


def test_every_line_whose_offers_pair_is_one_the_census_reads():
    """The census of what this changes: every shipped unit whose ``may``
    steps and offer sentences pair up two or more — each of which used to show
    its whole line for every offer. Floor of one (Chain of Vapor's)."""
    paired = []
    for unit in compilation_units(load_catalog()):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        candidates = [(tuple(program.instructions), unit.oracle_text or "")]
        for ability in (*program.activated_abilities, *program.triggered_abilities):
            if ability.instruction is not None:
                candidates.append(((ability.instruction,), ability.source_line or ""))
        for steps, line in candidates:
            mays = [s for root in steps for s in _preorder(root) if s.kind == "may"]
            if len(mays) < 2:
                continue
            sentences = _offer_sentences(line)
            if len(sentences) != len(mays):
                continue
            got = [_paired_offer(unit, step, line) for step in mays]
            assert got == sentences, (unit.name, got, sentences)
            paired.append(unit.name)
    assert "Chain of Vapor" in paired, paired
