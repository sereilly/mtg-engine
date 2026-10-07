"""The auto-tap dialog's plan pays for every card the state calls castable.

A hand card glows when its seat *could* pay for it — the pool plus what a tap
would add, non-land mana sources included
(``state_view._card_castable_now`` asking ``board_can_pay(…,
nonland_sources=True)``). The click sends the cast, the engine spends the pool,
and a short pool opens the "Insufficient mana" dialog with an Auto-Tap button.

The browser used to plan that tap itself (``computeAutoTapPlan`` in
``app.js``): lands only, one mana a land, the colour off the printed
``produced_mana`` summary, the printed cost, each tap its own ``tap`` action.
Measured on the tree where the highlight first counted a Sol Ring, over the
first ten boards below and one card per distinct mana cost: of **194**
(board, card) pairs the state called castable the dialog's own plan paid for
**92** — 77 with the button disabled, 25 with taps that did not pay.

The plan is the server's now (``web/payment_plan.py``): the dialog asks
``POST …/payment_plan`` with the action that was refused and sends that action
back with ``auto_tap``. This census holds the two answers together, both ways,
through the wire: every castable card's preview is ``payable`` and the
``auto_tap`` cast returns 200 having tapped exactly the previewed permanents;
no dark card's preview is payable.

``_legacy_plan`` is the planner this replaced, ported, and
``test_the_census_names_the_planner_it_replaced`` is the census run backwards:
it must find that planner short on these boards, or the boards have stopped
measuring anything.
"""
from __future__ import annotations

import copy
import re

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

#: label -> (battlefield, the names that arrived this turn). The first ten are
#: the boards the defect was measured on.
BOARDS: dict[str, tuple[list[str], tuple[str, ...]]] = {
    "lands alone": (["Forest", "Forest", "Mountain", "Island"], ()),
    "a Sol Ring": (["Sol Ring", "Forest"], ()),
    "a Llanowar Elves": (["Llanowar Elves", "Forest", "Forest"], ()),
    "a Birds of Paradise": (["Birds of Paradise", "Forest", "Mountain"], ()),
    "a summoning-sick Birds of Paradise": (
        ["Birds of Paradise", "Forest", "Mountain"], ("Birds of Paradise",)
    ),
    "a Mana Flare": (["Mana Flare", "Forest", "Mountain"], ()),
    "two-colour lands": (["Taiga", "Tropical Island", "Forest"], ()),
    "painlands": (["Karplusan Forest", "Karplusan Forest", "Forest"], ()),
    "a Ring, an Elf and a painland": (
        ["Sol Ring", "Llanowar Elves", "Karplusan Forest"], ()
    ),
    "a Mox and a City of Brass": (["Mox Emerald", "City of Brass", "Island"], ()),
    # Restricted mana, a tap that makes two, a source that hurts, a source
    # another permanent turns off, and one that is only ever sacrificed.
    "a Mishra's Workshop": (["Mishra's Workshop", "Forest"], ()),
    "an Ancient Tomb and a Mox": (["Ancient Tomb", "Mox Ruby", "Mountain"], ()),
    "a Mana Vault and an Elves of Deep Shadow": (
        ["Mana Vault", "Elves of Deep Shadow", "Swamp"], ()
    ),
    "a Sol Ring under a Null Rod": (["Sol Ring", "Null Rod", "Forest", "Forest"], ()),
    "an Elf under a Cursed Totem": (
        ["Llanowar Elves", "Cursed Totem", "Forest", "Forest"], ()
    ),
    "a Black Lotus": (["Black Lotus", "Forest"], ()),
}

#: Every (board, card) pair is previewed where the card glows; one dark pair
#: in this many is, because a dark card is the common case and a preview is a
#: copy of the game.
_DARK_STRIDE = 4


def _hand_cards() -> list[str]:
    """One card per distinct mana cost of mana value five or less: creatures
    and artifacts that announce nothing as they are cast."""
    seen: dict[str, str] = {}
    # By compilation unit, the pool-loop convention: a split card's halves
    # are read as the spells they are (and, being instants and sorceries,
    # are none of these).
    for card in compilation_units(_CARDS.values()):
        cost = (card.mana_cost or "").strip()
        if not cost or "X" in cost.upper() or "/" in cost or card.cmc > 5:
            continue
        if card.primary_type not in ("creature", "artifact"):
            continue
        if "Aura" in card.type_line or "Equipment" in card.type_line:
            continue
        text = (card.oracle_text or "").lower()
        if any(word in text for word in (
            "as an additional cost", "kicker", "target", "choose", "as this",
            " enters", "cast",
        )):
            continue
        if not compile_card_oracle(card).supported:
            continue
        seen.setdefault(cost, card.name)
    return sorted(seen.values())


def _session(board, hand, *, sick=(), mode="human_vs_human"):
    created = client.post("/api/sessions", json={
        "mode": mode, "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = (
            game.turn if name in sick else -99
        )
        permanent.tapped = False
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.stack.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session


def _state(sid):
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _preview(sid, body):
    response = client.post(f"/api/sessions/{sid}/payment_plan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _act(sid, body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _tapped_ids(game) -> list[int]:
    return sorted(p.permanent_id for p in game.controlled_by(0) if p.tapped)


# --- the planner the dialog used to run, ported ----------------------------

def _legacy_plan_pays(mana_cost: str, pool: dict, battlefield: list[dict]) -> bool:
    """``computeAutoTapPlan(...).ok`` as ``app.js`` had it: untapped lands
    alone, one mana each, of a symbol the payload's ``produced_mana`` lists."""
    required = {symbol: 0 for symbol in "WUBRGC"}
    generic = 0
    for token in re.findall(r"\{([^}]+)\}", (mana_cost or "").upper()):
        if token.isdigit():
            generic += int(token)
        elif token in required:
            required[token] += 1
    held = {symbol: int(pool.get(symbol, 0) or 0) for symbol in "WUBRGC"}
    lands = [
        {"produces": [str(s).upper() for s in perm.get("produced_mana") or []], "used": False}
        for perm in battlefield
        if "land" in (perm.get("type") or "").lower()
        and not perm.get("tapped") and perm.get("taps_for_mana") is not False
    ]
    lands = [land for land in lands if land["produces"]]
    for colour in "WUBRGC":
        deficit = max(0, required[colour] - held[colour])
        for land in sorted(lands, key=lambda entry: len(entry["produces"])):
            if deficit <= 0:
                break
            if land["used"] or colour not in land["produces"]:
                continue
            land["used"] = True
            held[colour] += 1
            deficit -= 1
        if deficit > 0:
            return False
    owed = sum(required.values()) + generic - sum(held.values())
    return owed <= sum(1 for land in lands if not land["used"])


# --- the census ------------------------------------------------------------

@pytest.fixture(scope="module")
def census():
    hand = _hand_cards()
    found = {
        "castable": 0, "paid": 0, "dark_previewed": 0, "legacy_short": 0,
        "unpaid": [], "taps_differ": [], "dark_payable": [], "legacy_boards": set(),
    }
    for label, (board, sick) in BOARDS.items():
        sid, session = _session(board, hand, sick=sick)
        me = _state(sid)["players"][0]
        glowing = set(me["playable_hand_indices"])
        table = copy.deepcopy(session.game)
        dark_seen = 0
        for index, name in enumerate(hand):
            body = {"seat": 0, "action": "cast", "card_name": name, "target_seat": 1}
            if index not in glowing:
                dark_seen += 1
                if dark_seen % _DARK_STRIDE:
                    continue
                found["dark_previewed"] += 1
                if _preview(sid, body)["payable"]:
                    found["dark_payable"].append((label, name))
                continue
            found["castable"] += 1
            if not _legacy_plan_pays(
                me["hand"][index]["mana_cost"], me["mana_pool"], me["battlefield"]
            ):
                found["legacy_short"] += 1
                found["legacy_boards"].add(label)
            plan = _preview(sid, body)
            if not plan["payable"]:
                found["unpaid"].append((label, name, plan["reason"]))
                continue
            response = _act(sid, {**body, "auto_tap": True})
            game = session.game
            if response.status_code != 200:
                found["unpaid"].append((label, name, response.text))
            else:
                found["paid"] += 1
                if _tapped_ids(game) != sorted(tap["id"] for tap in plan["taps"]):
                    found["taps_differ"].append((label, name, plan["taps"]))
            session.game = copy.deepcopy(table)
    return found


def test_every_castable_card_is_paid_by_the_dialogs_own_plan(census):
    """The state says castable; the preview says payable; the ``auto_tap``
    cast is a 200. 102 of 194 were not, on ten of these boards."""
    assert census["unpaid"] == []
    assert census["paid"] == census["castable"]


def test_the_action_taps_exactly_what_the_preview_showed(census):
    """The dialog lists what will be tapped. Nothing else is, and nothing on
    the list is spared."""
    assert census["taps_differ"] == []


def test_no_dark_card_has_a_paying_plan(census):
    """The other direction: a card the state calls uncastable for want of mana
    is one the dialog cannot pay for either — so the button is disabled
    exactly where the glow is off. A Black Lotus is on a board for this: the
    plan never sacrifices, which is also where the highlight draws its line."""
    assert census["dark_payable"] == []


def test_the_census_examined_enough(census):
    assert census["castable"] >= 200, census["castable"]
    assert census["dark_previewed"] >= 250, census["dark_previewed"]


def test_the_census_names_the_planner_it_replaced(census):
    """Run backwards: the lands-only planner is short on these boards — every
    one that pays with a Sol Ring, an Elf, a Birds or a Mana Flare's second
    mana — so a census that reads zero here is not measuring this defect."""
    assert census["legacy_short"] >= 60, census["legacy_short"]
    for label in (
        "a Sol Ring", "a Llanowar Elves", "a Birds of Paradise", "a Mana Flare",
    ):
        assert label in census["legacy_boards"], label
    assert "lands alone" not in census["legacy_boards"]


# --- named boards, each through the wire -----------------------------------

def test_the_preview_is_a_read():
    """Nothing is tapped, logged, spent or snapshotted by asking."""
    sid, session = _session(["Sol Ring", "Forest", "Llanowar Elves"], ["Juggernaut"])
    game = session.game
    before = _state(sid)
    log = list(game.log)
    history = len(getattr(session, "history", []) or [])

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Juggernaut"})

    assert plan["payable"] is True
    assert [tap["name"] for tap in plan["taps"]] == ["Forest", "Sol Ring", "Llanowar Elves"]
    assert {tap["name"]: tap["land"] for tap in plan["taps"]} == {
        "Forest": True, "Sol Ring": False, "Llanowar Elves": False,
    }
    assert plan["cost"]["generic"] == 4
    assert plan["reason"] is None
    assert game.log == log
    assert _tapped_ids(game) == []
    assert len(getattr(session, "history", []) or []) == history
    after = _state(sid)
    assert after["players"] == before["players"]
    assert after["stack"] == before["stack"] == []


def test_a_creature_is_tapped_through_its_own_mana_ability():
    """A Llanowar Elves pays by being *activated* — the log says the ability
    produced the mana, and the pool is empty again once the spell is paid."""
    sid, session = _session(["Forest", "Llanowar Elves"], ["Grizzly Bears"])
    game = session.game

    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Grizzly Bears", "auto_tap": True,
    })

    assert response.status_code == 200, response.text
    assert "Llanowar Elves produced {G}" in game.log
    assert "Host tapped Forest for mana" in game.log
    assert all(p.tapped for p in game.controlled_by(0))
    assert not any(game.players[0].mana_pool.values())
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]


def test_nothing_is_tapped_for_a_cost_no_tapping_pays():
    sid, session = _session(["Forest", "Llanowar Elves"], ["Craw Wurm"])
    game = session.game

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Craw Wurm"})
    assert plan["payable"] is False and plan["taps"] == []
    assert plan["cost"] == {"W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 0, "generic": 4}
    assert plan["reason"] == "insufficient mana for Craw Wurm"

    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Craw Wurm", "auto_tap": True,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "insufficient mana for Craw Wurm"
    assert _tapped_ids(game) == [] and game.stack == []
    assert [card.name for card in game.players[0].hand] == ["Craw Wurm"]


def test_a_pool_that_already_pays_taps_nothing():
    sid, session = _session(["Forest", "Forest"], ["Grizzly Bears"])
    game = session.game
    game.players[0].mana_pool["G"] = 2

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Grizzly Bears"})
    assert plan == {"payable": True, "taps": [], "cost": None, "reason": None}

    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Grizzly Bears", "auto_tap": True,
    })
    assert response.status_code == 200, response.text
    assert _tapped_ids(game) == []


def test_floating_mana_is_spent_before_a_land_is_tapped():
    sid, session = _session(["Forest", "Forest"], ["Grizzly Bears"])
    game = session.game
    game.players[0].mana_pool["G"] = 1

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Grizzly Bears"})

    assert plan["payable"] is True and len(plan["taps"]) == 1
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Grizzly Bears", "auto_tap": True,
    })
    assert response.status_code == 200, response.text
    assert len(_tapped_ids(game)) == 1
    assert not any(game.players[0].mana_pool.values())


def test_a_permanent_is_never_sacrificed_for_the_mana():
    """A Black Lotus would pay for it; the AI's plan would count it. A
    person's Auto-Tap button does not make that choice, and the card is dark."""
    sid, session = _session(["Black Lotus"], ["Phyrexian Hulk"])
    game = session.game

    assert _state(sid)["players"][0]["playable_hand_indices"] == []
    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Phyrexian Hulk"})
    assert plan["payable"] is False and plan["taps"] == []
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Phyrexian Hulk", "auto_tap": True,
    })
    assert response.status_code == 400
    assert [p.card.name for p in game.controlled_by(0)] == ["Black Lotus"]


def test_the_plan_pays_what_the_engine_charges_not_what_is_printed():
    """"White spells cost {3} more to cast." (Gloom.) The client's planner
    read the printed {W}; the preview's ``cost`` is the engine's {3}{W}."""
    sid, session = _session(
        ["Gloom", "Plains", "Plains", "Plains", "Plains"], ["Savannah Lions"],
    )
    game = session.game

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Savannah Lions"})
    assert plan["payable"] is True
    assert plan["cost"]["W"] == 1 and plan["cost"]["generic"] == 3
    assert len(plan["taps"]) == 4

    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Savannah Lions", "auto_tap": True,
    })
    assert response.status_code == 200, response.text
    assert len(_tapped_ids(game)) == 4
    assert not any(game.players[0].mana_pool.values())


def test_an_announced_kicker_is_planned_for():
    """CR 601.2b's optional cost is part of what the pool is asked for, so it
    is part of what is tapped: Kavu Titan kicked is {1}{G} and {2}{G}."""
    sid, session = _session(["Forest"] * 5, ["Kavu Titan"])
    game = session.game
    kicked = {
        "seat": 0, "action": "cast", "card_name": "Kavu Titan",
        "optional_cost_payments": {"{2}{G}": 1},
    }

    plain = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Kavu Titan"})
    plan = _preview(sid, kicked)
    assert len(plain["taps"]) == 2 and len(plan["taps"]) == 5
    assert plan["cost"]["G"] == 2 and plan["cost"]["generic"] == 3

    response = _act(sid, {**kicked, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert len(_tapped_ids(game)) == 5


def test_a_tap_that_triggers_does_not_cost_the_cast_its_timing():
    """City of Brass's "whenever this land becomes tapped" goes on the stack.
    Sent as separate ``tap`` actions the trigger was there when the cast
    arrived, and a creature "can only be cast when the stack is empty"; the
    route's own gates have passed before the server taps anything."""
    sid, session = _session(["City of Brass", "City of Brass"], ["Grizzly Bears"])
    game = session.game

    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Grizzly Bears", "auto_tap": True,
    })

    assert response.status_code == 200, response.text
    assert "Grizzly Bears" in [getattr(item.card, "name", None) for item in game.stack]
    assert len(_tapped_ids(game)) == 2


def test_an_abilitys_cost_is_paid_without_tapping_its_own_source():
    """{3}, {T}: Rod of Ruin's mana comes from the rest of the board."""
    sid, session = _session(
        ["Rod of Ruin", "Sol Ring", "Forest", "Forest"], [],
    )
    game = session.game
    rod = next(p for p in game.controlled_by(0) if p.card.name == "Rod of Ruin")
    body = {
        "seat": 0, "action": "activate", "permanent_name": "Rod of Ruin",
        "permanent_id": rod.permanent_id, "target_seat": 1,
    }
    refused = _act(sid, body)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "insufficient mana to activate Rod of Ruin"

    plan = _preview(sid, body)
    assert plan["payable"] is True
    assert "Rod of Ruin" not in [tap["name"] for tap in plan["taps"]]
    assert plan["cost"]["generic"] == 3

    response = _act(sid, {**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert rod.tapped
    assert not any(game.players[0].mana_pool.values())
    assert len(game.stack) == 1


def test_a_hand_ability_is_paid_from_the_board():
    """Cycling {2}: ``hand_abilities`` calls it payable over two untapped
    lands, the bare click is refused (the pool is empty), and the same action
    with ``auto_tap`` taps them and cycles."""
    sid, session = _session(["Forest", "Forest"], ["Drifting Meadow", "Grizzly Bears"])
    game = session.game
    game.players[0].library = [_CARDS["Forest"]] * 5
    (entry,) = _state(sid)["hand_abilities"]
    assert entry["payable"] is True
    body = {
        "seat": 0, "action": "activate_hand", "card_name": entry["name"],
        "hand_index": entry["hand_index"], "ability_index": entry["ability_index"],
    }

    refused = _act(sid, body)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Host cannot pay for Drifting Meadow's ability"

    plan = _preview(sid, body)
    assert plan["payable"] is True and len(plan["taps"]) == 2

    response = _act(sid, {**body, "auto_tap": True})
    assert response.status_code == 200, response.text
    assert len(_tapped_ids(game)) == 2
    assert "Drifting Meadow" not in [card.name for card in game.players[0].hand]


def test_the_preview_reports_a_refusal_that_is_not_about_mana():
    sid, session = _session(["Forest", "Forest"], ["Grizzly Bears"])
    session.game.stack.clear()
    session.game.priority_player_index = 1

    plan = _preview(sid, {"seat": 0, "action": "cast", "card_name": "Grizzly Bears"})

    assert plan["payable"] is False and plan["taps"] == []
    assert plan["reason"] == "you do not currently have priority"


def test_only_an_action_that_pays_mana_has_a_plan():
    sid, _session_ = _session(["Forest"], ["Grizzly Bears"])

    response = client.post(f"/api/sessions/{sid}/payment_plan", json={
        "seat": 0, "action": "pass_priority",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "that action pays no mana"
