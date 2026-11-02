"""Every prompt whose answer names a permanent names it by ``id`` (CR 400.7).

Known gap "Four prompts answer a permanent by index": ``untap_select`` stored
battlefield slots across requests (its offer too), ``opponent_damage_choose``
took an id on the wire but the engine dealt the damage to a slot,
``optional_untap_confirm`` had no id form — and the fourth, unnamed, was
``balance_confirm`` (kg's notes: "balance_confirm/sacrifice_confirm/
optional_untap_confirm no id form"). A slot names whatever is in it when it is
read; a request is written against the board the client last polled.

Three halves, none a hand list of the prompts:

* **The server.** The population is every action that answers a prompt —
  the ``action`` of every registered ``ChoiceSpec``, the session-level prompts
  ``web.actions.do_action`` gates every other action behind, and the combat
  assignments (``web/action_combat.py``). Each handler is read (and every
  ``web`` helper it hands the request to) for the request fields it reads: a
  handler reading a battlefield **slot** field and no id field answers by
  index. That set must be exactly the combat family in ``COMBAT_BY_SLOT`` —
  the measured remainder, named with its reason.
* **The client.** Every body ``web/static`` builds for a prompt answer outside
  that family carries an id field wherever it carries a slot field
  (``tests/ui/js_requests.py``'s census of request bodies).
* **The game.** Each prompt this entry named is armed through the app: each
  offered entry carries ``id``, the answer by id lands on that permanent, and
  a stale id is refused with the prompt still owed.

Measured backwards on the base (``49f558ae``): the server half named
``balance_confirm``, ``opponent_damage_choose``, ``optional_untap_confirm`` and
``untap_select``; the client half named the same four bodies.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import typing
from functools import lru_cache

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.pending_choices import CHOICE_SPECS
from web import actions as web_actions
from web.action_registry import ACTION_HANDLERS
from web.app import app, store
from web.debug_actions import _DEBUG_ANYTIME_ACTIONS
from web.schemas import ActionKind, GameActionRequest

from tests.helpers import _mk_creature_card
from .test_kg_client_request_schemas import census

client = TestClient(app)

#: Request fields that name a permanent by its battlefield slot, each with
#: the fields that name the same permanent(s) by id — empty where the wire
#: has none. (``divided_targets`` is not here: each entry carries its own
#: ``id`` beside the slot, ``DividedTargetRef.id``.)
SLOT_FIELDS = {
    "permanent_index": {"permanent_id"},
    "target_permanent_index": {"target_permanent_id"},
    "target_permanent_indices": {"target_permanent_ids"},
    "cost_permanent_index": {"cost_permanent_id", "cost_permanent_ids"},
    "source_permanent_index": {"source_permanent_id"},
    "land_indices": {"target_permanent_ids"},
    "creature_indices": {"target_permanent_ids"},
    "sacrifice_indices": {"sacrifice_permanent_ids"},
    "attacker_indices": set(), "bands": set(), "blocker_pairs": set(),
    "attacker_damage": set(), "blocker_damage": set(),
    "blocker_damage_split": set(), "banding_damage": set(), "piles": set(),
    "camouflage_piles": set(),
}
#: Request fields that name a permanent by ``permanent_id``.
ID_FIELDS = frozenset({
    "permanent_id", "target_permanent_id", "target_permanent_ids",
    "cost_permanent_id", "cost_permanent_ids", "source_permanent_id",
    "sacrifice_permanent_ids", "as_though_unblocked_ids", "prompt_permanent_id",
    "divided_among_defenders",
})
#: The priority actions a payment prompt admits beside its answer
#: (``ChoiceSpec.also_answers``) — casting and activating, not answers.
PRIORITY_ACTIONS = frozenset({"tap", "activate", "cast"})

#: The measured remainder: the combat declarations and assignments, which
#: answer by battlefield slot. The engine's combat maps are slot-keyed by
#: design and follow their creatures as the board renumbers
#: (``_renumber_combat_after_removal``); each is announced whole, in one
#: request, read against the board of that request (no selection is kept
#: across requests); and the combat damage step gives nobody priority between
#: the poll and the post. An id form for the combat wire is its own round.
COMBAT_BY_SLOT = {
    "declare_attackers": "attacker_indices, bands",
    "declare_blockers": "blocker_pairs",
    "assign_combat_damage": "attacker_damage (and blocker_damage[_split])",
    "assign_banding_damage": "banding_damage",
    "assign_multiblock_damage": "blocker_damage_split",
    "assign_defender_piles": "piles (Raging River)",
    "assign_attacker_piles": "piles (Raging River)",
    "assign_camouflage_piles": "camouflage_piles",
}


def test_the_field_tables_are_fields_of_the_request():
    fields = set(GameActionRequest.model_fields)
    assert set(SLOT_FIELDS) <= fields and ID_FIELDS <= fields
    assert set().union(*SLOT_FIELDS.values()) <= ID_FIELDS
    # Every field whose name says it is a battlefield slot is in the table: a
    # new one cannot arrive unread.
    named = {f for f in fields if "permanent_ind" in f}
    assert named <= set(SLOT_FIELDS), named - set(SLOT_FIELDS)


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------


def _gate_sets() -> set:
    """The session-level prompts: every action named in a ``req.action not in
    {...}`` gate of ``do_action`` (the ones every other action waits behind)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(web_actions.do_action)))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Set):
            found |= {
                elt.value for elt in node.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    return found


@lru_cache(maxsize=1)
def prompt_answers() -> frozenset:
    kinds = {spec.action for spec in CHOICE_SPECS.values()}
    kinds |= _gate_sets()
    kinds |= {
        kind for kind, spec in ACTION_HANDLERS.items()
        if spec.handler.__module__ == "web.action_combat"
    }
    kinds -= set(_DEBUG_ANYTIME_ACTIONS) | PRIORITY_ACTIONS
    return frozenset(kinds & set(ACTION_HANDLERS))


def _fields_read(func, param_index: int = 1, depth: int = 0) -> set:
    """The request fields *func* reads off its *param_index*-th parameter —
    and off it in every ``web`` function it hands the request to."""
    fn = ast.parse(textwrap.dedent(inspect.getsource(func))).body[0]
    params = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    name = params[param_index]
    found = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            found.add(node.attr)
        if depth < 3 and isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            callee = func.__globals__.get(node.func.id)
            if not (inspect.isfunction(callee) and callee.__module__.startswith("web.")):
                continue
            for position, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and arg.id == name:
                    found |= _fields_read(callee, position, depth + 1)
    return found


def slot_only(read) -> list:
    """The slot fields in *read* whose id alternative is not read beside
    them — a permanent the answer can only name by slot."""
    return sorted(f for f in read if f in SLOT_FIELDS and not read & SLOT_FIELDS[f])


@lru_cache(maxsize=1)
def by_slot() -> dict:
    """``kind -> slot-only fields`` for every prompt answer that names some
    permanent by slot alone."""
    out = {}
    for kind in sorted(prompt_answers()):
        only = slot_only(_fields_read(ACTION_HANDLERS[kind].handler))
        if only:
            out[kind] = only
    return out


def test_the_population_is_derived_and_large_enough():
    kinds = prompt_answers()
    assert len(kinds) >= 100, len(kinds)
    # The shapes it has to find: a registry prompt, a session-level one, a
    # combat assignment — and each of the four this entry named.
    assert {"sacrifice_confirm", "untap_select", "optional_untap_confirm",
            "assign_combat_damage", "balance_confirm", "opponent_damage_choose"} <= kinds
    assert set(typing.get_args(ActionKind)) >= kinds
    # The reader follows the request into a helper: the upkeep answers read
    # their address through `_answered_upkeep_prompt`.
    assert "prompt_permanent_id" in _fields_read(ACTION_HANDLERS["pay_upkeep"].handler)
    readers = [k for k in kinds if _fields_read(ACTION_HANDLERS[k].handler) & (set(SLOT_FIELDS) | ID_FIELDS)]
    assert len(readers) >= 25, sorted(readers)


def test_no_prompt_answers_a_permanent_by_slot_but_the_combat_family():
    assert by_slot().keys() == COMBAT_BY_SLOT.keys(), (
        "answers a permanent by slot only: "
        + ", ".join(f"{k} ({', '.join(v)})" for k, v in by_slot().items() if k not in COMBAT_BY_SLOT)
        + " | named but answering by id now: "
        + ", ".join(k for k in COMBAT_BY_SLOT if k not in by_slot())
    )


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def test_every_client_answer_outside_the_combat_family_names_its_permanent_by_id():
    examined, missing = 0, []
    for site, body in census().read:
        if site.url != "/api/sessions/{}/action" or body.kinds is None:
            continue
        kinds = set(body.kinds) & prompt_answers()
        if not kinds or kinds <= COMBAT_BY_SLOT.keys():
            continue
        examined += 1
        only = slot_only(set(body.keys))
        if only:
            missing.append(f"{body.where()} {sorted(kinds)}: {only}")
    assert examined >= 100, examined
    assert missing == [], missing


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------

_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4007,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _untap_board(sid, session, game):
    """Winter Orb with three tapped lands; the untap step waiting on a pick."""
    lands = [Permanent(card=_POOL[n], tapped=True) for n in ("Forest", "Island", "Swamp")]
    game.players[0].battlefield = [Permanent(card=_POOL["Winter Orb"]), *lands]
    game.players[1].battlefield = []
    game._sync_control()
    game._set_phase_and_step("beginning", "untap")
    session.untap_required_lands = 1
    return lands


def test_untap_select_offers_ids_keeps_the_pick_by_id_and_refuses_a_stale_one():
    sid, session, game = _session()
    forest, island, swamp = _untap_board(sid, session, game)
    offer = _state(sid)["untap_land_selection"]
    assert offer["candidate_ids"] == [forest.permanent_id, island.permanent_id, swamp.permanent_id]
    assert offer["candidate_indices"] == [game.battlefield_index_of(p) for p in (forest, island, swamp)]

    assert _act(sid, seat=0, action="untap_select", permanent_id=swamp.permanent_id).status_code == 200
    # The board renumbers between two requests (the Forest leaves): the pick
    # is still the Swamp, not whatever slid into its slot.
    game.remove_from_battlefield(forest)
    offer = _state(sid)["untap_land_selection"]
    assert offer["selected_ids"] == [swamp.permanent_id]
    assert offer["selected_indices"] == [game.battlefield_index_of(swamp)]

    stale = _act(sid, seat=0, action="untap_select", permanent_id=forest.permanent_id)
    assert stale.status_code == 404
    assert _act(sid, seat=0, action="untap_confirm").status_code == 200
    assert (swamp.tapped, island.tapped) == (False, True)


def test_untap_select_by_slot_is_read_once_on_arrival():
    sid, session, game = _session()
    _forest, island, _swamp = _untap_board(sid, session, game)
    slot = game.battlefield_index_of(island)
    assert _act(sid, seat=0, action="untap_select", permanent_index=slot).status_code == 200
    assert session.untap_selected_ids == [island.permanent_id]


def test_the_pick_survives_the_phasing_event_before_anything_untaps():
    """CR 702.26a: the untap step's phasing event phases permanents out
    before anything untaps, and a phased-out permanent leaves the battlefield
    list — so a slot chosen before the step resolved named the neighbour
    after it (or nothing). The engine is handed the pick by id and turns it
    into a slot after the event (``resolve_untap_step(selected_ids_by_type=)``)."""
    sid, session, game = _session()
    keeper = Permanent(card=_POOL["Breezekeeper"])
    forest, island = (Permanent(card=_POOL[n], tapped=True) for n in ("Forest", "Island"))
    game.players[0].battlefield = [Permanent(card=_POOL["Winter Orb"]), keeper, forest, island]
    game.players[1].battlefield = []
    game._sync_control()
    game._set_phase_and_step("beginning", "untap")
    session.untap_required_lands = 1

    assert _act(sid, seat=0, action="untap_select", permanent_id=island.permanent_id).status_code == 200
    confirmed = _act(sid, seat=0, action="untap_confirm")

    assert confirmed.status_code == 200, confirmed.text
    assert not game.is_on_battlefield(keeper), "it phased out"
    assert (island.tapped, forest.tapped) == (False, True)


def _old_man_board(sid, session, game):
    from web.turn_steps import _begin_turn

    old_man = Permanent(card=_POOL["Old Man of the Sea"], tapped=True)
    bears = Permanent(card=_POOL["Grizzly Bears"], tapped=True)
    game.players[0].battlefield = [bears, old_man]
    game._sync_control()
    assert _begin_turn(session, 0, defer_untap_selection=True) is False
    return old_man, bears


def test_optional_untap_offers_ids_and_keeps_tapped_by_id():
    sid, session, game = _session()
    old_man, bears = _old_man_board(sid, session, game)
    [entry] = _state(sid)["optional_untap"]["permanents"]
    assert entry["id"] == old_man.permanent_id
    # Renumbered after the offer: the payload draws it where it is now.
    game.remove_from_battlefield(bears)
    [entry] = _state(sid)["optional_untap"]["permanents"]
    assert entry["index"] == game.battlefield_index_of(old_man)

    answered = _act(sid, seat=0, action="optional_untap_confirm", target_permanent_ids=[old_man.permanent_id])
    assert answered.status_code == 200, answered.text
    assert old_man.tapped is True


def test_optional_untap_refuses_an_id_it_did_not_offer():
    sid, session, game = _session()
    old_man, bears = _old_man_board(sid, session, game)
    refused = _act(sid, seat=0, action="optional_untap_confirm", target_permanent_ids=[bears.permanent_id])
    assert refused.status_code == 400
    assert _state(sid)["optional_untap"] is not None


def _witches_board(game):
    witches = Permanent(card=_POOL["Cuombajj Witches"])
    witches.metadata["summoning_sickness_turn"] = -99
    giant = Permanent(card=_POOL["Hill Giant"])
    bear = Permanent(card=_POOL["Grizzly Bears"])
    game.players[1].battlefield = [witches]
    game.players[0].battlefield = [bear, giant]
    game._sync_control()
    game.arm_pending_choice(
        "opponent_damage", 0, caster_index=1, amount=1, card_name="Cuombajj Witches",
        _source_permanent=witches,
    )
    return witches, giant, bear


def test_opponent_damage_offers_ids_and_deals_to_the_permanent_named():
    sid, session, game = _session()
    _witches, giant, bear = _witches_board(game)
    targets = _state(sid)["opponent_damage_choice"]["valid_targets"]
    creatures = {t["name"]: t for t in targets if t["kind"] == "permanent"}
    assert creatures["Hill Giant"]["id"] == giant.permanent_id
    # The bear leaves before the answer arrives: the giant's slot moves.
    game.remove_from_battlefield(bear)

    answered = _act(sid, seat=0, action="opponent_damage_choose", target_seat=0,
                    target_permanent_id=giant.permanent_id)
    assert answered.status_code == 200, answered.text
    assert giant.damage_marked == 1
    assert _state(sid)["opponent_damage_choice"] is None


def test_opponent_damage_refuses_a_stale_id_and_stays_owed():
    sid, session, game = _session()
    _witches, _giant, bear = _witches_board(game)
    gone = bear.permanent_id
    game.remove_from_battlefield(bear)
    refused = _act(sid, seat=0, action="opponent_damage_choose", target_seat=0, target_permanent_id=gone)
    assert refused.status_code == 404
    assert game.pending_opponent_damage is not None


def test_the_engine_deals_the_default_to_a_permanent_not_a_slot():
    """The headless default: the largest creature the damage kills, found
    through the control seam and dealt to by identity."""
    _sid, _session_, game = _session()
    game.interactive_seats = set()
    sprite = Permanent(card=_mk_creature_card("Sprite", 1, 1))
    wall = Permanent(card=_mk_creature_card("Wall", 0, 5))
    game.players[1].battlefield = [wall, sprite]
    game._sync_control()
    game.arm_pending_choice(
        "opponent_damage", 0, caster_index=1, amount=1, card_name="Cuombajj Witches",
    )
    game.auto_resolve_pending_choices()
    assert not game.is_on_battlefield(sprite) or sprite.damage_marked == 1
    assert wall.damage_marked == 0


def _balance_board(game):
    game.players[0].hand = [_POOL["Balance"]]
    game.players[0].battlefield = [Permanent(card=_POOL[n]) for n in ("Plains", "Plains", "Plains")]
    game.players[1].battlefield = [Permanent(card=_POOL["Island"])]
    game._sync_control()
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    assert game.cast_from_hand(0, "Balance").supported
    game.resolve_top_of_stack()


def test_balance_offers_ids_and_takes_the_round_by_id():
    sid, session, game = _session()
    _balance_board(game)
    prompt = _state(sid)["balance_select"]
    assert prompt["stage"] == "lands" and prompt["lands_to_sacrifice"] == 2
    offered = [entry["id"] for entry in prompt["lands"]]
    keep, *gone = game.players[0].battlefield
    assert offered == [p.permanent_id for p in game.players[0].battlefield]

    answered = _act(sid, seat=0, action="balance_confirm",
                    target_permanent_ids=[p.permanent_id for p in gone])
    assert answered.status_code == 200, answered.text
    assert [p.permanent_id for p in game.controlled_by(0)] == [keep.permanent_id]


def test_balance_refuses_an_id_it_did_not_offer():
    sid, session, game = _session()
    _balance_board(game)
    island = game.players[1].battlefield[0]
    refused = _act(sid, seat=0, action="balance_confirm",
                   target_permanent_ids=[island.permanent_id, game.players[0].battlefield[0].permanent_id])
    assert refused.status_code == 400
    assert _state(sid)["balance_select"] is not None


@pytest.mark.parametrize("kind", sorted(COMBAT_BY_SLOT))
def test_the_combat_remainder_still_reads_slots(kind):
    """The exemption is a measurement, not a wish: each still reads a slot
    field (when one gains an id form, this names it so the table shrinks)."""
    assert kind in by_slot()
