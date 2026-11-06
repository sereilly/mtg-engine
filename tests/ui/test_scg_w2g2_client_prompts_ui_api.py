"""The wire a person answers Scourge's prompts on, as the browser client
(SCG W2G2) reads and sends it.

Scourge is still under ``measured``, so no deck holds its cards; the board is
placed on the session's game directly, as the Debug Menu does for a shipped
card, and every answer goes through the real action route in the body the
client builds:

* a storm copy's ``copy_spell_target`` says which copy it is and what it is
  aimed at, and ``accept: false`` keeps it there (the "Keep" button);
* a storm copy's ``retarget_choice`` (a card in a graveyard) is numbered too;
* a cast-side "exile X cards from your graveyard" (Chill Haunting, Skeletal
  Scrying) describes its cost — the graveyard slots it may take, and that the
  number picked is the X — and the cast route takes the client's answer:
  ``cost_graveyard_indices`` with ``x_value`` = how many;
* Forgotten Ancient's ``counter_distribution`` is answered with the
  ``divided_targets`` list the client builds from the payload;
* Parallel Thoughts' ``pile_top_draw`` is answered by ``option_index``.
"""

from __future__ import annotations

import shutil

import pytest

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import client, run_app_js, seat_plays_first
from web.app import store


def _pool():
    names = {}
    for code in ("LEA", "ODY"):
        names.update({card.name: card for card in load_cards(manifest_set_path(code))})
    names.update({
        card.name: card
        for card in load_cards(manifest_set_path("SCG", include_measured=True))
    })
    return names


def _session(hand, *, mine=(), theirs=(), graveyard=(), library=None):
    pool = _pool()
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "seed": 4002,
    }).json()
    session_id = created["session_id"]
    client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    seat_plays_first(session_id)
    game = store.get(session_id).game
    game.enforce_mana_costs = False
    game.players[0].hand = [pool[name] for name in hand]
    game.players[0].graveyard = [pool[name] for name in graveyard]
    if library is not None:
        game.players[0].library = [pool[name] for name in library]
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game._recompute_continuous_effects()
    return session_id, game, placed


def _act(session_id: str, **body):
    return client.post(f"/api/sessions/{session_id}/action", json=body)


def _state(session_id: str, seat: int):
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


def _resolve_top(session_id: str):
    for seat in (0, 1):
        _act(session_id, seat=seat, action="pass_priority")


def _cast_rituals(session_id, game, count):
    for _ in range(count):
        assert _act(session_id, seat=0, action="cast", card_name="Dark Ritual").status_code == 200
        _resolve_top(session_id)
    assert not game.stack


def _hand_card(session_id, name):
    return next(
        card for card in _state(session_id, 0)["players"][0]["hand"]
        if isinstance(card, dict) and card.get("name") == name
    )


# ---- storm copies ---------------------------------------------------------


def test_a_storm_copy_prompt_names_its_copy_and_its_target_and_keep_keeps_it():
    """Two copies of Scattershot, each asked in turn: the first is kept on the
    original's Bear (``accept: false``, the client's Keep), the second moved
    to another. The payload says "copy 1 of 2", then "copy 2 of 2", and what
    each is aimed at now."""
    session_id, game, placed = _session(
        ["Dark Ritual", "Dark Ritual", "Scattershot"],
        theirs=["Grizzly Bears", "Grizzly Bears", "Grizzly Bears"],
    )
    bears = placed[1]
    _cast_rituals(session_id, game, 2)
    assert _act(
        session_id, seat=0, action="cast", card_name="Scattershot",
        target_seat=1, target_permanent_id=bears[0].permanent_id,
    ).status_code == 200
    _resolve_top(session_id)  # the storm trigger

    first = _state(session_id, 0)["copy_spell_target"]
    assert (first["copy_number"], first["copy_count"]) == (1, 2)
    assert first["current_target"]["id"] == bears[0].permanent_id
    assert first["remaining"] == 2
    assert _act(
        session_id, seat=0, action="copy_spell_target_confirm", accept=False,
    ).status_code == 200

    second = _state(session_id, 0)["copy_spell_target"]
    assert (second["copy_number"], second["copy_count"]) == (2, 2)
    assert second["current_target"]["id"] == bears[0].permanent_id
    assert _act(
        session_id, seat=0, action="copy_spell_target_confirm",
        target_permanent_id=bears[1].permanent_id,
    ).status_code == 200
    assert _state(session_id, 0)["copy_spell_target"] is None
    for _ in range(3):
        _resolve_top(session_id)
    assert [bear.damage_marked for bear in bears] == [2, 1, 0], game.log


def test_keep_is_refused_from_a_seat_that_was_not_asked():
    session_id, game, placed = _session(
        ["Dark Ritual", "Scattershot"], theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    _cast_rituals(session_id, game, 1)
    assert _act(
        session_id, seat=0, action="cast", card_name="Scattershot",
        target_seat=1, target_permanent_id=placed[1][0].permanent_id,
    ).status_code == 200
    _resolve_top(session_id)
    assert _state(session_id, 0)["copy_spell_target"] is not None
    assert _act(
        session_id, seat=1, action="copy_spell_target_confirm", accept=False,
    ).status_code == 400
    # A single copy is not numbered: there is nothing to count.
    assert "copy_number" not in _state(session_id, 0)["copy_spell_target"]


def test_a_storm_copy_aimed_at_a_graveyard_card_is_asked_by_number():
    session_id, game, _ = _session(
        ["Dark Ritual", "Dark Ritual", "Reaping the Graves"],
        graveyard=["Grizzly Bears", "Craw Wurm", "Hill Giant"],
    )
    _cast_rituals(session_id, game, 2)
    assert game.queue_from_hand(0, "Reaping the Graves", target_permanent_index=0).supported
    _resolve_top(session_id)
    prompt = _state(session_id, 0)["retarget_choice"]
    assert prompt["prompt"].startswith(
        "Choose a new target for copy 1 of 2 of Reaping the Graves"
    )


# ---- a cast's graveyard exile cost ------------------------------------------


def test_chill_haunting_describes_its_graveyard_cost_and_the_route_takes_the_pick():
    """The hand card's spec carries the cost beside the creature target, its
    candidates the creature cards in the caster's own graveyard by slot; the
    client sends the slots it picked and their number as X."""
    session_id, game, placed = _session(
        ["Chill Haunting"],
        theirs=["Hill Giant"],
        graveyard=["Grizzly Bears", "Swamp", "Craw Wurm", "Hill Giant"],
    )
    spec = _hand_card(session_id, "Chill Haunting")["target_spec"]
    assert spec["kind"] == "creature"
    cost = spec["cost_spec"]
    assert cost["exile_cost"] and cost["announces_x"] and cost["own_graveyard_only"]
    offered = {(option["seat"], option["index"]) for option in cost["valid_targets"]}
    assert offered == {(0, 0), (0, 2), (0, 3)}  # the Swamp is no creature card

    giant = placed[1][0]
    assert _act(
        session_id, seat=0, action="cast", card_name="Chill Haunting",
        target_seat=1, target_permanent_id=giant.permanent_id,
        cost_graveyard_indices=[2, 3], x_value=2,
    ).status_code == 200
    _resolve_top(session_id)
    assert sorted(card.name for card in game.players[0].exile) == ["Craw Wurm", "Hill Giant"]
    assert (giant.effective_power, giant.effective_toughness) == (1, 1), game.log


def test_skeletal_scrying_is_a_cost_only_spec_and_the_pick_is_its_x():
    session_id, game, _ = _session(
        ["Skeletal Scrying"],
        graveyard=["Swamp", "Grizzly Bears", "Swamp"],
        library=["Swamp"] * 6,
    )
    spec = _hand_card(session_id, "Skeletal Scrying")["target_spec"]
    assert spec["kind"] == "graveyard_creature"
    assert spec["exile_cost"] and spec["any_card"] and spec["announces_x"]
    assert {option["index"] for option in spec["valid_targets"]} == {0, 1, 2}
    life = game.players[0].life
    assert _act(
        session_id, seat=0, action="cast", card_name="Skeletal Scrying",
        cost_graveyard_indices=[0, 2], x_value=2,
    ).status_code == 200
    _resolve_top(session_id)
    assert [card.name for card in game.players[0].exile] == ["Swamp", "Swamp"]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears", "Skeletal Scrying"]
    assert game.players[0].life == life - 2 and len(game.players[0].hand) == 2


# ---- Forgotten Ancient and Parallel Thoughts --------------------------------


def test_forgotten_ancients_distribution_is_answered_with_the_clients_list():
    session_id, game, placed = _session(
        [], mine=["Forgotten Ancient", "Grizzly Bears"], theirs=["Hill Giant"],
    )
    ancient, bear = placed[0]
    giant = placed[1][0]
    game.place_plus1_counters(ancient, 3)
    game.turn = 2
    game.start_turn(0)
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    prompt = _state(session_id, 0)["counter_distribution"]
    assert prompt["maximum"] == 3 and prompt["counter"] == "+1/+1"
    by_id = {c["id"]: c for c in prompt["candidates"]}
    assert set(by_id) == {bear.permanent_id, giant.permanent_id}
    # The client's body: one {seat, id, amount} per creature given any.
    body = [
        {"seat": by_id[bear.permanent_id]["seat"], "id": bear.permanent_id, "amount": 2},
        {"seat": by_id[giant.permanent_id]["seat"], "id": giant.permanent_id, "amount": 1},
    ]
    assert _act(
        session_id, seat=0, action="counter_distribution_confirm", divided_targets=body,
    ).status_code == 200
    assert _state(session_id, 0)["counter_distribution"] is None
    assert counters_on(bear, "+1/+1") == 2 and counters_on(giant, "+1/+1") == 1
    assert counters_on(ancient, "+1/+1") == 0


def test_parallel_thoughts_pile_offer_is_answered_by_option_index():
    session_id, game, placed = _session(
        ["Parallel Thoughts"], library=["Hill Giant"] * 7 + ["Forest"] * 5,
    )
    assert _act(session_id, seat=0, action="cast", card_name="Parallel Thoughts").status_code == 200
    for _ in range(3):
        _resolve_top(session_id)
        search = _state(session_id, 0).get("search_exile")
        if search:
            picks = [{"zone": "library", "index": i} for i in search["legal_indices"][:7]]
            assert _act(
                session_id, seat=0, action="search_exile_confirm", search_picks=picks,
            ).status_code == 200
    assert len(game.players[0].exile) == 7, game.log
    me = game.players[0]
    game._draw_with_replacements(me, 1)
    offer = _state(session_id, 0)["pile_top_draw"]
    assert offer["pile_size"] == 7 and len(offer["options"]) == 2
    assert _state(session_id, 1)["pile_top_draw"] is None
    hand_before = len(me.hand)
    assert _act(session_id, seat=0, action="pile_top_draw_confirm", option_index=1).status_code == 200
    assert len(me.hand) == hand_before + 1 and len(me.exile) == 6


# ---- the client's own branches, run in node on the payload the server sent --

_needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_STUBS = (
    "let seat = 0; let currentState = INPUT.state; let pendingPermanentCost = null;"
    " let specialActionXFor = null; let specialActionXFields = {};"
    " let pendingCastCost = null; const SENT = [];"
    " const sendAction = async (body) => { SENT.push(body); return body; };"
    " function renderActivationPrompt() {} function updateActionHint() {}"
    " function renderSpecialActions() {}"
)


@_needs_node
def test_the_turn_face_up_picker_sends_the_bird_the_player_chose(set_pool):
    """Raven Guild Initiate's "Morph—Return a Bird you control to its owner's
    hand" with two Birds: the offer opens the set picker over its own
    candidates (no send yet), and the confirm sends the one picked on
    ``cost_permanent_ids`` — which the route then honours."""
    from engine.face_down import face_down_card

    scg = set_pool("SCG")
    session_id, game, placed = _session([], mine=["Island"])
    game.enforce_mana_costs = True
    initiate = Permanent(card=face_down_card(scg["Raven Guild Initiate"]))
    game._put_permanent_onto_battlefield(0, initiate, None)
    farseer, liberator = Permanent(card=scg["Aven Farseer"]), Permanent(card=scg["Aven Liberator"])
    for bird in (farseer, liberator):
        game._put_permanent_onto_battlefield(0, bird, None)
    game._recompute_continuous_effects()
    state = _state(session_id, 0)
    (entry,) = [e for e in state["special_actions"] if e["kind"] == "turn_face_up"]

    out = run_app_js(
        ["takeMorphOffer", "morphCostSteps", "morphStepFields", "openMorphCostStep",
         "turnFaceUpHiddenName", "permanentCostVerbLabel", "confirmPermanentCost",
         "sendSpecialAction"],
        "takeMorphOffer(INPUT.entry);"
        " const opened = { options: pendingPermanentCost.options.map((o) => o.id),"
        " verb: pendingPermanentCost.verb, count: pendingPermanentCost.count,"
        " sentence: pendingPermanentCost.costSentence, sentBefore: SENT.length };"
        " pendingPermanentCost.picked = [INPUT.pick]; confirmPermanentCost();"
        " return { opened, sent: SENT };",
        {"state": state, "entry": entry, "pick": liberator.permanent_id},
        prelude=_STUBS,
    )
    assert out["opened"] == {
        "options": [farseer.permanent_id, liberator.permanent_id], "verb": "return",
        "count": 1, "sentence": "Morph—Return a Bird you control to its owner's hand",
        "sentBefore": 0,
    }
    (body,) = out["sent"]
    assert body["cost_permanent_ids"] == [liberator.permanent_id]
    assert body["special_action_kind"] == "turn_face_up"
    assert _act(session_id, **body).status_code == 200
    assert [card.name for card in game.players[0].hand] == ["Aven Liberator"]
    assert initiate.card.name == "Raven Guild Initiate"


@_needs_node
def test_the_cast_graveyard_cost_picker_announces_its_x_and_goes_on_to_the_target():
    """Chill Haunting from the hand: the cost stage opens the graveyard set
    picker (not the battlefield one), and confirming two cards writes the
    slots and X = 2 onto the cast, then runs the target cascade."""
    session_id, game, _ = _session(
        ["Chill Haunting"], theirs=["Hill Giant"],
        graveyard=["Grizzly Bears", "Swamp", "Craw Wurm"],
    )
    state = _state(session_id, 0)
    card = next(c for c in state["players"][0]["hand"] if c["name"] == "Chill Haunting")
    out = run_app_js(
        ["startCastCostPrompt", "startCastGraveyardCostPrompt", "castCostSpec", "specIsACost",
         "castCostIsSeparate", "targetSpecOf", "graveyardCardNoun", "costNounPlural",
         "confirmPermanentCost", "continueCastAfterCost"],
        "const opened = startCastCostPrompt(INPUT.card);"
        " const pending = pendingPermanentCost;"
        " const offered = pending.options.map((o) => o.id);"
        " pending.picked = [0, 2]; confirmPermanentCost();"
        " return { opened, zone: pending.zone, offered, announcesX: pending.announcesX,"
        " cost: pendingCastCost, cascaded: CASCADE };",
        {"state": state, "card": card},
        prelude=_STUBS + (
            " let pendingCastCreatureType = null; let CASCADE = null;"
            " const EMPTY_TARGET_SPEC = { kind: 'none', requires_target: false, valid_targets: [] };"
            " const ACTIVATION_COST_FLAGS = ['sacrifice_cost', 'discard_cost', 'exile_cost',"
            " 'tap_cost', 'return_cost', 'untap_cost', 'put_counter_cost',"
            " 'remove_counter_cost', 'library_top_cost', 'library_bottom_cost'];"
            " function startCastCreatureTypePrompt() { return false; }"
            " function normalizeCardName(card) { return card.name; }"
            " function startCastTargetCascade(card) { CASCADE = card.name; return true; }"
        ),
    )
    assert out["opened"] is True and out["zone"] == "graveyard" and out["announcesX"] is True
    assert out["offered"] == [0, 2]  # the Swamp is no creature card
    assert out["cost"] == {"cost_graveyard_indices": [0, 2], "x_value": 2}
    assert out["cascaded"] == "Chill Haunting"
