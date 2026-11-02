"""The combat wire names creatures by permanent id (CR 400.7).

Known gap "The combat wire names permanents by slot" (kg3/wire's
``COMBAT_BY_SLOT``): ``declare_attackers`` (``attacker_indices``, ``bands``),
``declare_blockers`` (``blocker_pairs``), ``assign_combat_damage``
(``attacker_damage``, ``blocker_damage[_split]``), ``assign_banding_damage``,
``assign_multiblock_damage``, the Raging River and Camouflage piles. Each is
announced whole in one request — written against the board the client last
polled. A creature that left between that poll and the post handed its slot to
whichever creature slid into it, and the request named that one.

The wire now takes each by id (``web.actions.COMBAT_ID_FIELDS``: ``attacker_ids``,
``band_ids``, ``blocker_pairs_by_id``, ``attacker_damage_by_id`` …), turned into
the engine's slots once at the top of the dispatch against the board of the
request, and **refuses the slot fields from a client**. The engine's combat
maps stay slot-keyed (``_renumber_combat_after_removal``).

Measured backwards with the conversion switched off (the slot fields passed
through, as on ``f6c44277``): after a land ahead of them left, the Bear's
polled slot declared the Giant as the attacker, and Wall A's polled slot
declared Wall B as the blocker. The client census over ``f6c44277``'s
``app.js`` named 21 combat bodies by slot (``test_kg3_wire_prompt_ids``).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.actions import COMBAT_ID_FIELDS
from web.app import app, store

from tests.helpers import _mk_creature_card, run_app_js

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_POOL: dict = {}
for _path in manifest_set_paths():
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _table(mine, theirs):
    """Two people; seat 0 is active in its declare attackers step, with
    *mine* and *theirs* on the two battlefields."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 40711,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.players[0].battlefield = list(mine)
    game.players[1].battlefield = list(theirs)
    game._sync_control()
    for player in game.players:
        player.hand = []
        player.life = 20
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    return sid, game


def _creature(name, power=2, toughness=2, text=""):
    return Permanent(card=_mk_creature_card(name, power, toughness, text))


def _land(name="Plains"):
    return Permanent(card=_POOL[name])


def _attacking(game):
    return sorted(game.permanent_at(0, slot).card.name for slot in game.combat_attackers)


# ---------------------------------------------------------------------------
# A slot field from a client is refused, naming its id form
# ---------------------------------------------------------------------------

#: A value of each slot field's shape, and the action it rides on.
_SLOT_SAMPLES = {
    "attacker_indices": ("declare_attackers", [0]),
    "bands": ("declare_attackers", [[0, 1]]),
    "attacker_planeswalker_ids": ("declare_attackers", {"0": 7}),
    "blocker_pairs": ("declare_blockers", {"0": 0}),
    "attacker_damage": ("assign_combat_damage", {"0": {"0": 2}}),
    "blocker_damage": ("assign_combat_damage", {"0": 0}),
    "blocker_damage_split": ("assign_combat_damage", {"0": {"0": 2}}),
    "banding_damage": ("assign_banding_damage", {"0": {"0": 2}}),
    "piles": ("assign_defender_piles", {"0": "left"}),
    "camouflage_piles": ("assign_camouflage_piles", {"0": 0}),
}


def test_every_slot_field_has_a_sample():
    assert set(_SLOT_SAMPLES) == set(COMBAT_ID_FIELDS.values())
    assert len(COMBAT_ID_FIELDS) == 10


@pytest.mark.parametrize("by_id", sorted(COMBAT_ID_FIELDS))
def test_a_slot_field_is_refused_naming_its_id_form(by_id):
    slot_field = COMBAT_ID_FIELDS[by_id]
    action, value = _SLOT_SAMPLES[slot_field]
    sid, game = _table([_creature("Bear A"), _creature("Bear B")], [_creature("Guard")])

    refused = _act(sid, seat=0, action=action, **{slot_field: value})

    assert refused.status_code == 400, refused.text
    detail = refused.json()["detail"]
    assert slot_field in detail and by_id in detail, detail
    assert game.combat_attackers == {} and not game.combat_attackers_locked


# ---------------------------------------------------------------------------
# Declaring attackers
# ---------------------------------------------------------------------------


def test_an_attacker_named_by_id_is_the_one_that_attacks_after_the_board_renumbers():
    plains, bear, giant = _land(), _creature("Bear", 2, 2), _creature("Giant", 3, 3)
    sid, game = _table([plains, bear, giant], [])
    polled = _state(sid, 0)["players"][0]["battlefield"]
    assert [card["id"] for card in polled] == [p.permanent_id for p in (plains, bear, giant)]

    # The Plains leaves between the poll and the post: every slot after it
    # moves down one, and the Giant's polled slot (2) now names nothing.
    game.remove_from_battlefield(plains)
    declared = _act(sid, seat=0, action="declare_attackers",
                    attacker_ids=[polled[2]["id"]], target_seat=1)

    assert declared.status_code == 200, declared.text
    assert _attacking(game) == ["Giant"]


def test_an_attacker_that_left_since_the_poll_is_a_404_and_nothing_is_declared():
    bear, giant = _creature("Bear"), _creature("Giant", 3, 3)
    sid, game = _table([bear, giant], [])
    ids = [card["id"] for card in _state(sid, 0)["players"][0]["battlefield"]]

    game.remove_from_battlefield(bear)
    stale = _act(sid, seat=0, action="declare_attackers", attacker_ids=ids, target_seat=1)

    assert stale.status_code == 404, stale.text
    assert game.combat_attackers == {} and not game.combat_attackers_locked
    # The same seat then declares what is there.
    assert _act(sid, seat=0, action="declare_attackers",
                attacker_ids=[giant.permanent_id], target_seat=1).status_code == 200
    assert _attacking(game) == ["Giant"]


def test_an_attacker_on_another_battlefield_is_a_400():
    """The same slot on the opponent's battlefield is another creature: an id
    there is refused, not read as the active player's slot."""
    bear, theirs = _creature("Bear"), _creature("Their Bear")
    sid, game = _table([bear], [theirs])

    refused = _act(sid, seat=0, action="declare_attackers",
                   attacker_ids=[theirs.permanent_id], target_seat=1)

    assert refused.status_code == 400, refused.text
    assert "Their Bear" in refused.json()["detail"]
    assert game.combat_attackers == {}


def test_a_band_is_declared_by_its_members_ids():
    hero = Permanent(card=_POOL["Benalish Hero"])
    plains, bear = _land(), _creature("Bear")
    sid, game = _table([plains, hero, bear], [])
    game.remove_from_battlefield(plains)

    declared = _act(sid, seat=0, action="declare_attackers",
                    attacker_ids=[hero.permanent_id, bear.permanent_id],
                    band_ids=[[hero.permanent_id, bear.permanent_id]], target_seat=1)

    assert declared.status_code == 200, declared.text
    [band] = game.combat_bands
    assert sorted(game.permanent_at(0, slot).card.name for slot in band) == ["Bear", "Benalish Hero"]


# ---------------------------------------------------------------------------
# Declaring blockers
# ---------------------------------------------------------------------------


def _to_blocks(theirs, attackers=None):
    giant = _creature("Giant", 3, 3)
    sid, game = _table(attackers or [giant], theirs)
    mine = game.players[0].battlefield
    assert _act(sid, seat=0, action="declare_attackers",
                attacker_ids=[p.permanent_id for p in mine], target_seat=1).status_code == 200
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert game.current_step == "declare_blockers"
    return sid, game, mine


def test_a_blocker_named_by_id_blocks_after_the_board_renumbers():
    swamp, wall_a, wall_b = _land("Swamp"), _creature("Wall A", 0, 5), _creature("Wall B", 0, 5)
    sid, game, (giant,) = _to_blocks([swamp, wall_a, wall_b])
    polled = _state(sid, 1)["players"][1]["battlefield"]

    game.remove_from_battlefield(swamp)
    blocked = _act(sid, seat=1, action="declare_blockers",
                   blocker_pairs_by_id={str(polled[2]["id"]): giant.permanent_id})

    assert blocked.status_code == 200, blocked.text
    blocks = game.combat_blockers.get(1, {})
    assert [game.permanent_at(1, slot).card.name for slot in blocks] == ["Wall B"]


def test_a_blocker_that_left_since_the_poll_is_a_404_and_the_blocks_stay_open():
    wall_a, wall_b = _creature("Wall A", 0, 5), _creature("Wall B", 0, 5)
    sid, game, (giant,) = _to_blocks([wall_a, wall_b])
    gone = wall_a.permanent_id
    game.remove_from_battlefield(wall_a)

    stale = _act(sid, seat=1, action="declare_blockers",
                 blocker_pairs_by_id={str(gone): giant.permanent_id})

    assert stale.status_code == 404, stale.text
    assert not game.combat_blockers_locked and game.combat_blockers.get(1, {}) == {}


def test_a_blocker_on_the_attackers_battlefield_is_a_400():
    wall = _creature("Wall", 0, 5)
    bystander = _creature("Bystander")
    sid, game, (giant, _b) = _to_blocks([wall], attackers=[_creature("Giant", 3, 3), bystander])

    refused = _act(sid, seat=1, action="declare_blockers",
                   blocker_pairs_by_id={str(bystander.permanent_id): giant.permanent_id})

    assert refused.status_code == 400, refused.text
    assert not game.combat_blockers_locked


# ---------------------------------------------------------------------------
# Assigning combat damage
# ---------------------------------------------------------------------------


def _to_damage(theirs, blocking):
    """Seat 0's 3/3 Ogre blocked by the *blocking* subset of *theirs*."""
    ogre = _creature("Ogre", 3, 3)
    sid, game, _mine = _to_blocks(theirs, attackers=[ogre])
    blocked = _act(sid, seat=1, action="declare_blockers",
                   blocker_pairs_by_id={str(p.permanent_id): ogre.permanent_id for p in blocking})
    assert blocked.status_code == 200, blocked.text
    assert _act(sid, seat=0, action="next_phase").status_code == 200
    assert game.current_step == "combat_damage" and not game.combat_damage_resolved
    return sid, game, ogre


def test_a_division_named_by_id_lands_on_the_creatures_named_after_the_board_renumbers():
    swamp, wall_a, wall_b = _land("Swamp"), _creature("Wall A", 0, 5), _creature("Wall B", 0, 5)
    sid, game, ogre = _to_damage([swamp, wall_a, wall_b], [wall_a, wall_b])

    game.remove_from_battlefield(swamp)
    assigned = _act(sid, seat=0, action="assign_combat_damage",
                    attacker_damage_by_id={str(ogre.permanent_id): {
                        str(wall_a.permanent_id): 1, str(wall_b.permanent_id): 2}})

    assert assigned.status_code == 200, assigned.text
    assert (wall_a.damage_marked, wall_b.damage_marked) == (1, 2)


def test_a_division_naming_a_creature_that_left_is_a_404_and_nothing_is_dealt():
    wall_a, wall_b, wall_c = (_creature(f"Wall {x}", 0, 5) for x in "ABC")
    sid, game, ogre = _to_damage([wall_a, wall_b, wall_c], [wall_a, wall_b, wall_c])
    gone = wall_c.permanent_id
    game.remove_from_battlefield(wall_c)

    stale = _act(sid, seat=0, action="assign_combat_damage",
                 attacker_damage_by_id={str(ogre.permanent_id): {
                     str(wall_a.permanent_id): 1, str(gone): 2}})

    assert stale.status_code == 404, stale.text
    assert not game.combat_damage_resolved
    assert (wall_a.damage_marked, wall_b.damage_marked) == (0, 0)


# ---------------------------------------------------------------------------
# The piles
# ---------------------------------------------------------------------------


def test_the_camouflage_offer_carries_ids_and_takes_piles_by_id():
    swamp, wall_a, wall_b = _land("Swamp"), _creature("Wall A", 0, 5), _creature("Wall B", 0, 5)
    sid, game, _mine = _to_blocks([swamp, wall_a, wall_b])
    # Camouflage's turn: the blocks are a division into piles.
    game.camouflage_active_turn = game.turn
    offer = _state(sid, 1)["camouflage"]
    assert [item["id"] for item in offer["divide_creatures"]] == [wall_a.permanent_id, wall_b.permanent_id]

    game.remove_from_battlefield(swamp)
    answered = _act(sid, seat=1, action="assign_camouflage_piles",
                    camouflage_piles_by_id={str(wall_b.permanent_id): 0})

    assert answered.status_code == 200, answered.text
    assert [game.permanent_at(1, slot).card.name for slot in game.combat_blockers.get(1, {})] == ["Wall B"]


# ---------------------------------------------------------------------------
# The client: a draft by slot goes out by id, off the board it was drawn on
# ---------------------------------------------------------------------------


@needs_node
def test_the_clients_helpers_send_the_blocks_the_board_showed():
    """``combatIdKeyed`` / ``combatIdsAt`` over the state the server served:
    the blocker draft (``{blocker slot: [attacker slots]}``) becomes the
    by-id body ``handleCombatPromptOk`` sends, and the server takes it."""
    swamp, wall_a, wall_b = _land("Swamp"), _creature("Wall A", 0, 5), _creature("Wall B", 0, 5)
    sid, game, (giant,) = _to_blocks([swamp, wall_a, wall_b])
    state = _state(sid, 1)

    body = run_app_js(
        ["combatIdAt", "combatIdsAt", "combatIdKeyed"],
        """
        const state = INPUT;
        return combatIdKeyed(state, 1, { 2: [0] }, (attackers) => combatIdsAt(state, 0, attackers));
        """,
        state,
    )

    assert body == {str(wall_b.permanent_id): [giant.permanent_id]}
    game.remove_from_battlefield(swamp)
    blocked = _act(sid, seat=1, action="declare_blockers", blocker_pairs_by_id=body)
    assert blocked.status_code == 200, blocked.text
    assert [game.permanent_at(1, slot).card.name for slot in game.combat_blockers.get(1, {})] == ["Wall B"]


@needs_node
def test_a_draft_slot_with_nothing_in_it_is_refused_by_the_client():
    sid, _game = _table([_creature("Bear")], [])
    state = _state(sid, 0)

    message = run_app_js(
        ["combatIdAt", "combatIdsAt"],
        """
        try { combatIdsAt(INPUT, 0, [0, 3]); return "sent"; }
        catch (e) { return e.message; }
        """,
        state,
    )

    assert message == "The battlefield changed before this was sent; choose again."


@needs_node
def test_a_parked_declaration_is_read_again_by_id():
    """The 3+ seat declaration waits for an opponent to be picked: parked by
    id, its cost prompt reads the slots the ids sit in when it is sent."""
    plains, bear, giant = _land(), _creature("Bear"), _creature("Giant", 3, 3)
    sid, game = _table([plains, bear, giant], [])
    game.remove_from_battlefield(plains)
    state = _state(sid, 0)

    slots = run_app_js(
        ["combatSlotsOfIds"], "return combatSlotsOfIds(INPUT.state, 0, INPUT.ids);",
        {"state": state, "ids": [giant.permanent_id, 999999]},
    )

    assert slots == [game.battlefield_index_of(giant)]


_DRAFT_PRELUDE = """
let seat = 0; let currentState = null;
let combatDraftStepKey = ""; let combatAttackerDraft = []; let combatBandDraft = false;
let combatBlockerDraft = {}; let combatDamageDraft = {}; let combatDamageOfferDraft = {};
let combatBandBlockerDraft = {}; let combatMultiblockDraft = {};
let combatDividedDraft = { key: "", byAttacker: {} }; let combatDamageDialogKey = "";
const hints = []; let closed = 0;
function updateActionHint(message, isError) { hints.push([message, !!isError]); }
function closeCombatDamageDialog() { closed += 1; }
"""

_DRAFT_FUNCTIONS = [
    "syncCombatDrafts", "combatBoardKey", "getCombatDraftStepKey", "getCombatState",
    "isCombatStep", "iDeclareBlocks", "blockDeclarationDefender",
]


@needs_node
def test_a_draft_drawn_on_a_board_that_renumbers_is_started_again():
    """The drafts are kept by slot: a permanent leaving mid-declaration would
    leave the Bear's selected slot naming the Giant, and the request would
    send the Giant's id. The client starts the draft again, says so, and
    closes any open damage dialog; a poll of the same board keeps it."""
    plains, bear, giant = _land(), _creature("Bear"), _creature("Giant", 3, 3)
    sid, game = _table([plains, bear, giant], [])
    before = _state(sid, 0)
    game.remove_from_battlefield(plains)
    after = _state(sid, 0)

    seen = run_app_js(
        _DRAFT_FUNCTIONS,
        """
        syncCombatDrafts(INPUT.before);
        combatAttackerDraft = [1];               // the Bear, on the polled board
        combatDamageDraft = { 1: { 0: 2 } };
        syncCombatDrafts(INPUT.before);          // the same board polled again
        const kept = [...combatAttackerDraft];
        syncCombatDrafts(INPUT.after);           // the Plains has left
        return { kept, after: combatAttackerDraft, damage: combatDamageDraft, hints, closed };
        """,
        {"before": before, "after": after},
        prelude=_DRAFT_PRELUDE,
    )

    assert seen == {
        "kept": [1],
        "after": [],
        "damage": {},
        "hints": [["The battlefield changed; choose again.", True]],
        "closed": 1,
    }
