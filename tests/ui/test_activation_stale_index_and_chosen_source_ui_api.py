"""Two answers the ``activate`` route gave a client that the engine does not.

* **A stale ``ability_index`` on a land was a mana tap.** The index is the
  position in the menu the server handed the client, and one that names no
  ability of a land that still has its own fell through both arms of the land
  branch: a Mishra's Factory asked for an ability it does not have was tapped
  for mana. Every other permanent refuses the same request; a stale index is
  a 400, never a different action.
* **"A … source of your choice" was sent as "any target".** Circle of
  Protection: Artifacts' picker offered both players and every creature for
  a shield that answers only to artifact sources (CR 609.7a: a source is
  chosen, not targeted). The spec the client is handed is the sources the
  shield can answer to, and a bare ``activate`` is still the whole
  announcement — nothing is owed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.shields import shields_on
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(mine=(), theirs=()):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
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
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            row.append(permanent)
        rows.append(row)
    game.start_priority_window(0)
    return sid, game, rows[0], rows[1]


def _activate(sid, permanent, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": permanent.permanent_id,
        **fields,
    })


def _drain(sid, game):
    for _ in range(6):
        if not game.stack:
            return
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )


# ---------------------------------------------------------------------------
# A stale ability index on a land
# ---------------------------------------------------------------------------


def test_a_land_asked_for_an_ability_it_does_not_have_is_not_tapped_for_mana():
    sid, game, (factory,), _ = _session(["Mishra's Factory"])
    pool_before = dict(game.players[0].mana_pool)

    stale = _activate(sid, factory, ability_index=7)

    assert stale.status_code == 400, stale.text
    assert stale.json()["detail"] == "Mishra's Factory has no ability at index 7"
    assert not factory.tapped
    assert dict(game.players[0].mana_pool) == pool_before


def test_a_land_that_makes_no_mana_does_not_run_its_first_ability_instead():
    """Island of Wak-Wak has one ability and taps for nothing: an index past
    it ran that one ability, because "no ability named" on a land that makes
    no mana means its first."""
    sid, game, (island,), (bird,) = _session(["Island of Wak-Wak"], ["Air Elemental"])

    stale = _activate(sid, island, ability_index=3, target_permanent_id=bird.permanent_id)

    assert stale.status_code == 400, stale.text
    assert not island.tapped and game.stack == []
    assert bird.effective_power == 4


def test_the_indices_a_land_does_have_are_activated_as_before():
    sid, game, (factory,), _ = _session(["Mishra's Factory"])

    # Its menu, in order: the mana ability, then the animation.
    animate = _activate(sid, factory, ability_index=1)
    _drain(sid, game)

    assert animate.status_code == 200, animate.text
    assert factory.is_creature and not factory.tapped

    mana = _activate(sid, factory, ability_index=0)

    assert mana.status_code == 200, mana.text
    assert factory.tapped and game.players[0].mana_pool.get("C") == 1


def test_a_basic_land_is_still_tapped_with_no_index_at_all():
    sid, game, (forest,), _ = _session(["Forest"])

    tapped = _activate(sid, forest)

    assert tapped.status_code == 200, tapped.text
    assert forest.tapped and game.players[0].mana_pool.get("G") == 1


# ---------------------------------------------------------------------------
# A source of your choice
# ---------------------------------------------------------------------------


def _target_spec(sid, permanent):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0})
    assert state.status_code == 200, state.text
    for seat in state.json()["players"]:
        for entry in seat.get("battlefield") or ():
            if entry.get("id") == permanent.permanent_id:
                return entry
    raise AssertionError("permanent not in the state payload")


def test_the_client_is_offered_artifact_sources_and_no_player():
    sid, game, (circle, ring, bears), (thopter, giant) = _session(
        ["Circle of Protection: Artifacts", "Sol Ring", "Grizzly Bears"],
        ["Ornithopter", "Hill Giant"],
    )

    spec = game.activation_target_spec(0, 0, ability_index=0)

    assert spec["kind"] == "artifact" and spec["source_of_choice"] is True
    assert {(entry["kind"], entry["name"]) for entry in spec["valid_targets"]} == {
        ("permanent", "Sol Ring"), ("permanent", "Ornithopter"),
    }

    # …and that is the spec the client is sent with the state.
    sent = _target_spec(sid, circle)["target_spec"]
    assert sent["kind"] == "artifact" and sent["source_of_choice"] is True
    assert {entry["name"] for entry in sent["valid_targets"]} == {"Sol Ring", "Ornithopter"}
    assert not any(entry["kind"] == "player" for entry in sent["valid_targets"])


def test_a_chosen_source_is_sent_and_the_shield_is_the_activators():
    sid, game, (circle, ring), (thopter,) = _session(
        ["Circle of Protection: Artifacts", "Sol Ring"], ["Ornithopter"],
    )

    chosen = _activate(sid, circle, target_permanent_id=thopter.permanent_id)
    _drain(sid, game)

    assert chosen.status_code == 200, chosen.text
    assert len(shields_on(game.players[0])) == 1 and not shields_on(game.players[1])


def test_a_creature_is_not_an_artifact_source():
    sid, game, (circle, bears), _ = _session(
        ["Circle of Protection: Artifacts", "Grizzly Bears"],
    )

    refused = _activate(sid, circle, target_permanent_id=bears.permanent_id)

    assert refused.status_code == 400, refused.text
    assert game.stack == [] and not shields_on(game.players[0])


def test_a_source_of_your_choice_owes_no_target_over_the_wire():
    """With no artifact anywhere the Circle is still activated: a chosen
    source is not a target, so an empty picker does not make the ability
    unactivatable (CR 609.7a, against CR 602.2b's rule for targets)."""
    sid, game, (circle,), _ = _session(["Circle of Protection: Artifacts"])

    bare = _activate(sid, circle)
    _drain(sid, game)

    assert bare.status_code == 200, bare.text
    assert len(shields_on(game.players[0])) == 1
