"""A human seat's cleanup discard is counted against the engine's maximum.

CR 514.1's discard is deferred for an interactive seat: the engine reports the
step unfinished and the web layer asks how many cards are owed. It asked its
own copy of the rule — a player flag nothing sets any more, and a literal
seven — so under Recycle ("Your maximum hand size is two.") or a Cursed Rack
the engine deferred, the prompt said nothing was owed, and advancing began the
next turn with the cards still in hand. The Thought beasts would have been the
same card in the browser.
"""

from fastapi.testclient import TestClient

from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)


def _card(name: str, type_line: str, oracle_text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


def _session_in_second_main(hand_size: int, *statics: str):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 99002,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.current_turn_phase = "postcombat_main"
    game.current_step = "postcombat_main"
    game.current_phase = "main"
    game.players[0].hand = [
        _card(f"Spell {index}", "Sorcery", "") for index in range(hand_size)
    ]
    for index, text in enumerate(statics):
        permanent = Permanent(card=_card(f"Static {index}", "Enchantment", text))
        game._put_permanent_onto_battlefield(0, permanent, None)
    return sid, session


def _to_cleanup(sid: str) -> dict:
    end_step = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"}
    )
    assert end_step.status_code == 200, end_step.text
    cleanup = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"}
    )
    assert cleanup.status_code == 200, cleanup.text
    return cleanup.json()


def test_a_lowered_maximum_is_what_the_cleanup_prompt_counts_against():
    sid, _session = _session_in_second_main(
        5, "Your maximum hand size is reduced by three."
    )
    payload = _to_cleanup(sid)

    assert payload["current_phase"] == "cleanup"
    assert payload["current_turn"] == 0, "the turn waits for the discard"
    assert payload["cleanup_discard"]["required_count"] == 1

    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"}
    )
    assert refused.status_code == 400
    assert "select cleanup discards" in refused.json()["detail"].lower()

    picked = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cleanup_select", "hand_index": 0},
    ).json()
    assert picked["current_turn"] == 1
    assert len(picked["players"][0]["graveyard"]) == 1
    assert len(picked["players"][0]["hand"]) == 4


def test_a_printed_limit_is_what_the_cleanup_prompt_counts_against():
    """Recycle's sentence, shipped since Tempest: five cards against a limit
    of two is three owed, where the literal seven owed none."""
    sid, _session = _session_in_second_main(5, "Your maximum hand size is two.")
    payload = _to_cleanup(sid)

    assert payload["current_turn"] == 0
    assert payload["cleanup_discard"]["required_count"] == 3


def test_no_maximum_owes_nothing_however_large_the_hand():
    sid, _session = _session_in_second_main(10, "You have no maximum hand size.")
    payload = _to_cleanup(sid)

    assert payload["cleanup_discard"] is None
    assert payload["current_turn"] == 1
    assert len(payload["players"][0]["hand"]) == 10


def test_a_later_limit_after_no_maximum_is_asked_for():
    """CR 613.11's order reaches the prompt: no maximum, then a limit of two."""
    sid, _session = _session_in_second_main(
        4, "You have no maximum hand size.", "Your maximum hand size is two."
    )
    payload = _to_cleanup(sid)

    assert payload["cleanup_discard"]["required_count"] == 2
