"""The {T} symbol's two refusals are the server's, per ability.

CR 302.6 / 602.5a: a creature's ability with {T} in its cost can't be
activated unless its controller has controlled it continuously since their
most recent turn began (haste aside). CR 107.5: a tapped permanent can't be
tapped again to pay the cost. The activation path asks both
(``Game.tap_symbol_refusal``, extracted from ``_activation_window``); the wire's
``ability_denials`` did not, and the client kept a copy —
``abilityCostRequiresTap`` with the permanent's ``summoning_sick`` and
``tapped`` flags, which read the **first** ability's printed cost for a {T}
whatever ability was being activated. So a tapped Basalt Monolith was "already
tapped" for its "{3}: Untap", and a summoning-sick creature's ability without
{T} was refused as though it had one.

The census: every pool permanent with a {T} ability, on three boards — clean
(untapped, controlled since the turn began), summoning sick, and tapped — on
its controller's own main phase with an empty stack. Every {T} ability the
clean board leaves undenied is denied on the other two in the engine's
sentence, the activation path refuses it with that sentence, and no ability
without {T} is denied for either reason. On the base the wire was silent on
every one of them (run backwards: the first assertion of each judge fails).
"""
from __future__ import annotations

import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import app_js_function_body, client, resolve_stack, run_app_js, stable_sample
from web.app import store
from web.offers import _ability_denial

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

_SICK = "has summoning sickness"
_TAPPED = "is already tapped"
_SENTENCE = {"sick": _SICK, "tapped": _TAPPED}


def _subjects(every: int):
    """Every permanent card with a usable activated ability whose cost has
    {T} — in the census's one-in-*every* sample by name."""
    found = []
    for unit in faces.compilation_units(_CATALOG):
        if unit is not _CARDS.get(unit.name) or unit.primary_type in ("instant", "sorcery"):
            continue
        if not stable_sample(unit.name, every):
            continue
        usable = usable_activated_abilities(compile_card_oracle(unit))
        if any(ability.cost.requires_tap for ability in usable):
            found.append(unit)
    return found


def _table() -> str:
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4407,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _board(subjects, *, sick: bool, tapped: bool, sid: "str | None" = None):
    """*subjects* on seat 0's battlefield, nothing else on either — on a new
    table, or on *sid*'s, cleared."""
    sid = sid or _table()
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.hand = []
    for card in subjects:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = game.turn if sick else -99
        permanent.tapped = tapped
    game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _row(game, slot, permanent, index, ability, denial, entry=None):
    return {
        "name": permanent.card.name, "id": permanent.permanent_id, "slot": slot,
        "index": index, "tap": bool(ability.cost.requires_tap),
        "sick_now": game._is_summoning_sick(permanent),
        "denial": denial, "card": entry,
    }


def _served(sid, game):
    """Each ability's denial as the wire serves it."""
    payload = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    rows = {}
    for slot, permanent in enumerate(game.controlled_by(0)):
        entry = payload["players"][0]["battlefield"][slot]
        usable = game.usable_abilities_of(permanent, card=permanent.effective_card)
        denials = entry.get("ability_denials") or [None] * len(usable)
        assert len(denials) == len(usable), entry["name"]
        for index, ability in enumerate(usable):
            rows[(permanent.card.name, index)] = _row(
                game, slot, permanent, index, ability, denials[index], entry,
            )
    return rows


def _asked(game):
    """Each ability's denial as the wire's own reader answers it — what
    ``_served`` reads, without building a whole-pool payload."""
    rows = {}
    for slot, permanent in enumerate(game.controlled_by(0)):
        usable = game.usable_abilities_of(permanent, card=permanent.effective_card)
        for index, ability in enumerate(usable):
            rows[(permanent.card.name, index)] = _row(
                game, slot, permanent, index, ability,
                _ability_denial(game, 0, permanent, ability),
            )
    return rows


def _boards(subjects, read):
    boards = {}
    for label, sick, tapped in (("clean", False, False), ("sick", True, False), ("tapped", False, True)):
        sid, game = _board(subjects, sick=sick, tapped=tapped)
        boards[label] = (sid, game, read(sid, game))
    return boards


_SMALL = (
    "Basalt Monolith", "Prodigal Sorcerer", "Llanowar Elves", "Rod of Ruin",
    "Royal Assassin", "Mishra's Factory",
)


@pytest.fixture(scope="module")
def small():
    return _boards([_CARDS[name] for name in _SMALL], _served)


#: How many subjects share one board in the whole-pool census: few enough
#: that one permanent's static (a Cursed Totem, a Blood Moon) reaches few
#: others, and that building the board is not quadratic in the pool.
_CHUNK = 30


def _census_chunks():
    """The whole pool's subjects, a chunk at a time, each chunk on the same
    three tables: ``(boards)`` per chunk, read through ``_asked``."""
    subjects = _subjects(1)
    tables = {label: _table() for label in ("clean", "sick", "tapped")}
    for start in range(0, len(subjects), _CHUNK):
        chunk = subjects[start:start + _CHUNK]
        boards = {}
        for label, sick, tapped in (("clean", False, False), ("sick", True, False), ("tapped", False, True)):
            sid, game = _board(chunk, sick=sick, tapped=tapped, sid=tables[label])
            boards[label] = (sid, game, _asked(game))
        yield boards


def _judge(boards) -> dict:
    """Every ability of every subject, held to CR 302.6 and 107.5 as the
    wire states them. Returns what was judged."""
    clean = boards["clean"][2]
    judged = {"sick": 0, "tapped": 0, "untouched": 0}
    for label, sentence in _SENTENCE.items():
        for key, row in boards[label][2].items():
            if key not in clean:
                # The board changed what the permanent has (another subject's
                # static): nothing to compare it with.
                continue
            before = clean[key]["denial"]
            denial = row["denial"]
            if not row["tap"]:
                # An ability without {T} is never refused for the symbol — the
                # client's copy refused it whenever ability 0 printed one.
                assert denial is None or sentence not in denial, (label, key, denial)
                judged["untouched"] += 1
                continue
            if label == "sick" and not row["sick_now"]:
                # Not a creature, or one with haste: CR 302.6 does not reach it.
                assert denial == before, (label, key, denial, before)
                continue
            if before is not None:
                # Refused for something earlier in the path's order.
                continue
            assert denial == f"{row['name']} {sentence}", (label, key, denial)
            judged[label] += 1
    return judged


def _same_refusal(said: str, denial: str) -> bool:
    """Whether the path's refusal is the wire's denial — or one the path
    makes before it over a choice the denial is asked without: a target the
    board does not have (CR 601.2c), or "X can't be 0" with no X announced."""
    return said == denial or "target" in said or "X can't be 0" in said


def _route_refusals(boards, label: str) -> int:
    """Every {T} ability the wire denies on *label*'s board, activated anyway
    through the route, is refused in the wire's own sentence."""
    sid, _game, rows = boards[label]
    checked = 0
    for row in rows.values():
        if not row["denial"] or _SENTENCE[label] not in row["denial"]:
            continue
        refused = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "activate", "permanent_name": row["name"],
            "permanent_id": row["id"], "ability_index": row["index"], "target_seat": 1,
        })
        assert refused.status_code == 400, (row["name"], row["index"], refused.text)
        detail = refused.json()["detail"]
        assert _same_refusal(detail, row["denial"]), (row["name"], detail)
        checked += 1
    return checked


def _path_refusals(boards, label: str) -> int:
    """The same, asked of the activation path directly (the route's own call)."""
    _sid, game, rows = boards[label]
    checked = 0
    for row in rows.values():
        if not row["denial"] or _SENTENCE[label] not in row["denial"]:
            continue
        result = game.queue_permanent_ability(
            0, row["name"], target_player_index=1, permanent_index=row["slot"],
            ability_index=row["index"], seat_announced=True,
        )
        assert not result.supported, (row["name"], row["index"])
        assert _same_refusal(result.details, row["denial"]), (row["name"], result.details)
        checked += 1
    return checked


def test_basalt_monolith_tapped_is_denied_its_tap_and_offered_its_untap(small):
    rows = small["tapped"][2]
    tap, untap = rows[("Basalt Monolith", 0)], rows[("Basalt Monolith", 1)]
    assert tap["tap"] and tap["denial"] == "Basalt Monolith is already tapped"
    assert not untap["tap"] and untap["denial"] is None


def test_one_of_each_the_wire_states_both_refusals(small):
    judged = _judge(small)
    assert judged["sick"] >= 3 and judged["tapped"] >= 5 and judged["untouched"] >= 2, judged
    assert _route_refusals(small, "sick") >= 3
    assert _route_refusals(small, "tapped") >= 5


def test_a_tapped_monolith_untaps_through_the_route(small):
    sid, game, _rows = small["tapped"]
    monolith = next(p for p in game.controlled_by(0) if p.card.name == "Basalt Monolith")
    assert monolith.tapped
    done = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Basalt Monolith",
        "permanent_id": monolith.permanent_id, "ability_index": 1,
    })
    assert done.status_code == 200, done.text
    resolve_stack(game)
    assert not monolith.tapped


@pytest.mark.full
def test_every_tap_ability_in_the_pool_is_denied_as_the_path_refuses_it():
    judged = {"sick": 0, "tapped": 0, "untouched": 0}
    refused = {"sick": 0, "tapped": 0}
    for boards in _census_chunks():
        for label, count in _judge(boards).items():
            judged[label] += count
        for label in refused:
            refused[label] += _path_refusals(boards, label)
    # A sweep that judged nothing would pass as one that found nothing.
    assert judged["sick"] >= 100 and judged["tapped"] >= 300 and judged["untouched"] >= 50, judged
    assert refused["sick"] >= 100 and refused["tapped"] >= 300, refused


@needs_node
def test_the_menu_greys_the_tap_ability_and_not_the_untap(small):
    card = small["tapped"][2][("Basalt Monolith", 0)]["card"]
    answers = run_app_js(
        ["abilityOptionDisabledReason", "abilityProhibitionOf"],
        "return [0, 1].map((index) => abilityOptionDisabledReason({ index }, INPUT));",
        card,
    )
    assert answers == ["Basalt Monolith is already tapped", None]


def test_the_client_reads_no_cost_text_for_the_tap_symbol():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "abilityCostRequiresTap" not in source
    assert "summoning_sick" not in app_js_function_body("startActivationPrompt")
