"""CR 601.3 has one predicate and three readers, and they agree.

"A player can begin to cast a spell only if … no rule or effect prohibits that
player from casting it." The cast path refused a prohibited spell through a run
of thirteen predicates; the AI's proposal gate asked seven of them and the
web's castable highlight asked two. So a seat under Steel Golem, Arcane
Laboratory, Cornered Market, City of Solitude, Hand to Hand or Damping Engine
saw a hand that glowed and clicked a card the engine refused, and an AI seat
proposed the same refused cast every turn for the rest of the game — 15 to 55
``refused_casts`` in six simulated games with one of them pinned into a deck.

``engine/cast_prohibitions.py`` is the fold: one table, asked by all three.
This file holds it three ways:

* **by row** — every row of ``CAST_PROHIBITIONS`` has a scenario here (a row
  without one fails), built so the cast path refuses for that row alone; the
  engine, the AI and the wire are each asked, with and without the prohibition;
* **by pool** — every permanent in either manifest role printing a sentence
  shaped like a prohibition, on each side of the table, through a matrix of
  situations and a hand of every card type. Wherever the engine casts without
  it and refuses with it, neither other reader may say yes. Derived from the
  printed text, so a ban a later set brings is swept without being listed;
* **by construction** — none of the three readers calls a row's predicate
  itself, so there is no second list to fall behind.

Validated backwards before the fold (``census_prohibitions.py`` in the W2G3
scratch directory, the same matrix): 81 proposals and 59 glows over 245 engine
refusals, naming all six. Each sweep carries a floor on how much it examined —
a census that reads nothing passes for the wrong reason.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, ai_policy
from engine import cast_prohibitions
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_prohibitions import (CAST_PROHIBITIONS, LAND, SPELL,
                                      cast_prohibition)
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.spell_prohibitions import forbid_casting_this_turn
from tests.helpers import resolve_stack
from web.app import app, store
from web.state_view import _compute_playable_hand_indices

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

#: Seat 0 is ahead on permanents (Damping Engine reads the board for its
#: subject), and the opposing Grizzly Bears and Taiga share a name with cards
#: the hand holds (Cornered Market reads the board for its names).
_MINE = ["Forest"] * 4 + ["Hill Giant"]
_THEIRS = ["Grizzly Bears", "Taiga"]

OWN_MAIN = "own main"
AFTER_A_SPELL = "own main, after a green spell"
OPPONENTS_TURN = "an opponent's turn"
OWN_COMBAT = "own combat"
SITUATIONS = (OWN_MAIN, AFTER_A_SPELL, OPPONENTS_TURN, OWN_COMBAT)


@pytest.fixture(scope="module")
def session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4243,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return store.get(sid)


def _w2g3_board(session, situation: str, hand_name: str, *, ban=None, ban_seat=1):
    """A fresh game in *session*: the standing board, *hand_name* in hand with
    mana to cast anything, optionally one prohibiting permanent, in *situation*.
    Returns the game and the prohibiting permanent (or None)."""
    library = [_POOL["Grizzly Bears"]] * 20
    game = Game(players=[
        PlayerState(name="Host", library=list(library)),
        PlayerState(name="Guest", library=list(library)),
    ])
    game.enforce_mana_costs = True
    mine = [Permanent(card=_POOL[name]) for name in _MINE]
    host = mine[-1]
    game.players[0].battlefield = mine
    game.players[1].battlefield = [Permanent(card=_POOL[name]) for name in _THEIRS]
    banning = None
    if ban is not None:
        banning = Permanent(card=_POOL[ban])
        # What an entry choice would have recorded, for the two permanents
        # whose prohibition names a card: the one being asked about.
        banning.metadata["chosen_card_name"] = hand_name
        banning.metadata["chosen_card_names"] = [hand_name, ""]
        game.players[ban_seat].battlefield.append(banning)
        if "Aura" in _POOL[ban].type_line:
            attach_aura(banning, host)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [_POOL[hand_name]]
    game.players[0].mana_pool.update({"W": 9, "U": 9, "B": 9, "R": 9, "G": 9})
    game.turn = 3
    session.game = game
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    if situation == AFTER_A_SPELL:
        game.players[0].hand.insert(0, _POOL["Llanowar Elves"])
        if game.cast_from_hand(0, "Llanowar Elves").supported:
            resolve_stack(game)
        else:
            # The prohibition under test already stops the turn's first spell
            # (Aether Storm, Steel Golem): the situation is then plain "own
            # main", with the hand as every other situation leaves it.
            assert ban is not None
            game.players[0].hand.pop(0)
        game.start_priority_window(0)
    elif situation == OPPONENTS_TURN:
        session.current_turn = 1
        game.active_player_index = 1
        game.start_priority_window(0)
    elif situation == OWN_COMBAT:
        game.current_phase = "combat"
        game.current_turn_phase, game.current_step = "combat", "declare_attackers"
        game.start_priority_window(0)
    return game, banning


def _w2g3_ai_proposes(game, hand_name: str) -> bool:
    """The AI's whole proposal for the card, not only its first gate."""
    hand = game.players[0].hand
    index = next(i for i, card in enumerate(hand) if card.name == hand_name)
    return ai_policy._cast_candidate(game, 0, hand[index], index) is not None


def _w2g3_glows(session, hand_name: str) -> bool:
    hand = session.game.players[0].hand
    index = next(i for i, card in enumerate(hand) if card.name == hand_name)
    return index in _compute_playable_hand_indices(session, 0)


def _w2g3_glows_on_the_wire(session, hand_name: str) -> bool:
    state = client.get(f"/api/sessions/{session.id}/state", params={"seat": 0}).json()
    names = [card["name"] for card in state["players"][0]["hand"]]
    return names.index(hand_name) in state["players"][0]["playable_hand_indices"]


# --- by row -----------------------------------------------------------------

#: ``row kind -> [(label, situation, hand card, prohibiting permanent or None,
#: its seat, cast keywords, arm)]``. *arm* is called on the game for a
#: prohibition no permanent prints. Every scenario is a board on which the
#: cast path casts the card without the prohibition and refuses it with.
def _forbid_creatures(game):
    forbid_casting_this_turn(game, 0, ("creature",))


def _ban_targeting(game):
    game.targeting_bans.append({"source_name": "Peace Talks", "remaining_turns": 2})


_SCENARIOS: dict[str, list[tuple]] = {
    "set_lockout": [
        ("a spell", OWN_MAIN, "Moorish Cavalry", "City in a Bottle", 1, {}, None),
        ("a land", OWN_MAIN, "Desert", "City in a Bottle", 1, {}, None),
    ],
    "controller_cast_ban": [
        ("the host's controller", OWN_MAIN, "Grizzly Bears", "Brand of Ill Omen", 1, {}, None),
    ],
    "own_cast_ban": [
        ("its own controller", OWN_MAIN, "Grizzly Bears", "Steel Golem", 0, {}, None),
    ],
    "casting_forbidden_this_turn": [
        ("a recorded effect", OWN_MAIN, "Grizzly Bears", None, 0, {}, _forbid_creatures),
    ],
    "global_cast_ban": [
        ("everybody", OWN_MAIN, "Grizzly Bears", "Aether Storm", 1, {}, None),
    ],
    "most_permanents_cast_ban": [
        ("the seat ahead", OWN_MAIN, "Grizzly Bears", "Damping Engine", 1, {}, None),
    ],
    "spell_cap_ban": [
        ("each player", AFTER_A_SPELL, "Grizzly Bears", "Arcane Laboratory", 1, {}, None),
        ("you", AFTER_A_SPELL, "Sol Ring", "Yawgmoth's Agenda", 0, {}, None),
    ],
    "last_cast_color_ban": [
        ("a second green spell", AFTER_A_SPELL, "Grizzly Bears", "Mana Maze", 1, {}, None),
    ],
    "global_play_timing": [
        ("another player's turn", OPPONENTS_TURN, "Fog", "City of Solitude", 1, {}, None),
    ],
    "combat_play_ban": [
        ("an instant in combat", OWN_COMBAT, "Fog", "Hand to Hand", 1, {}, None),
    ],
    "targeting_ban": [
        ("a targeted spell", OWN_MAIN, "Lightning Bolt", None, 0,
         {"target_player_index": 1}, _ban_targeting),
    ],
    "chosen_name_ban": [
        ("two names, a spell", OWN_MAIN, "Grizzly Bears", "Null Chamber", 1, {}, None),
        ("two names, a land", OWN_MAIN, "Taiga", "Null Chamber", 1, {}, None),
        ("one name", OWN_MAIN, "Grizzly Bears", "Meddling Mage", 1, {}, None),
    ],
    "same_name_as_permanent_ban": [
        ("a spell", OWN_MAIN, "Grizzly Bears", "Cornered Market", 1, {}, None),
        ("a nonbasic land", OWN_MAIN, "Taiga", "Cornered Market", 1, {}, None),
    ],
}

_ROW_CASES = [
    pytest.param(kind, *scenario, id=f"{kind}: {scenario[0]}")
    for kind, scenarios in _SCENARIOS.items()
    for scenario in scenarios
]


def test_w2g3_every_prohibition_row_has_a_scenario():
    """A row nobody has shown refusing is a row nobody has shown agreeing."""
    rows = {row.kind: row for row in CAST_PROHIBITIONS}
    assert set(_SCENARIOS) == set(rows)
    assert len(rows) >= 13
    for kind, row in rows.items():
        hands = {scenario[2] for scenario in _SCENARIOS[kind]}
        if LAND in row.binds:
            assert any(_POOL[name].primary_type == "land" for name in hands), (
                f"{kind} binds a land drop and no scenario plays a land"
            )
        assert SPELL not in row.binds or any(
            _POOL[name].primary_type != "land" for name in hands
        )


@pytest.mark.parametrize("kind,label,situation,hand_name,ban,ban_seat,cast,arm", _ROW_CASES)
def test_w2g3_a_prohibited_cast_is_refused_unproposed_and_dark(
    session, kind, label, situation, hand_name, ban, ban_seat, cast, arm
):
    # Without the prohibition: castable, proposed, glowing — so each "no"
    # below is this row's and nothing else's.
    game, _ = _w2g3_board(session, situation, hand_name)
    assert cast_prohibition(game, 0, _POOL[hand_name]) is None
    assert ai_policy._can_cast_with_targets(game, 0, _POOL[hand_name])
    assert _w2g3_ai_proposes(game, hand_name)
    if situation in (OWN_MAIN, AFTER_A_SPELL) or _POOL[hand_name].primary_type == "instant":
        assert _w2g3_glows_on_the_wire(session, hand_name)
    assert game.cast_from_hand(0, hand_name, **cast).supported

    game, _ = _w2g3_board(session, situation, hand_name, ban=ban, ban_seat=ban_seat)
    if arm is not None:
        arm(game)
    card = _POOL[hand_name]
    found = cast_prohibition(game, 0, card)
    assert found is not None and found.kind == kind, found

    # The two other readers, before the cast path is asked to refuse.
    assert not ai_policy._can_cast_with_targets(game, 0, card)
    assert not _w2g3_ai_proposes(game, hand_name)
    assert not _w2g3_glows_on_the_wire(session, hand_name)

    # …and the cast path: refused in that row's words, with nothing spent.
    pool_before = dict(game.players[0].mana_pool)
    logged = len(game.log)
    refused = game.cast_from_hand(0, hand_name, **cast)
    assert not refused.supported
    assert refused.details == found.details
    assert game.log[logged:] == [found.details]
    assert [held.name for held in game.players[0].hand] == [hand_name]
    assert dict(game.players[0].mana_pool) == pool_before
    assert not game.stack


# --- by pool ----------------------------------------------------------------

#: A sentence that reads as a standing prohibition on casting or playing.
_PROHIBITION = re.compile(
    r"can't (?:cast|play)\b|can't be (?:cast|played)\b|can cast spells", re.I
)

#: One card of each type a ban names, none needing a target; a nonbasic land
#: for Cornered Market's second line; and two cards first printed in Arabian
#: Nights for City in a Bottle.
_HAND = [
    "Grizzly Bears", "Fog", "Wrath of God", "Sol Ring", "Castle", "Forest",
    "Taiga", "Moorish Cavalry", "Desert",
]

#: Candidates the matrix cannot make refuse, each with why. Named rather than
#: skipped, so a candidate a later set adds must either refuse something here
#: or be explained.
_REFUSES_NOTHING_HERE = {
    "Firestorm Phoenix": "its sentence locks one returned copy of itself in a hand",
    "Limited Resources": "binds only while ten or more lands are on the battlefield",
}


def _prohibiting_permanents() -> list[str]:
    found = []
    # Through `compilation_units` (a split card read whole has no text). A
    # half is left out: the board below holds whole cards, by name, and every
    # multi-face card in the pool today is an instant or a sorcery anyway.
    for card in compilation_units(_POOL.values()):
        if card.primary_type in ("instant", "sorcery") or card.face_of is not None:
            continue
        if not compile_card_oracle(card).supported:
            continue
        if any(_PROHIBITION.search(line) for line in (card.oracle_text or "").splitlines()):
            found.append(card.name)
    return sorted(found)


def test_w2g3_no_reader_says_yes_to_a_cast_a_permanent_forbids(session):
    """Every prohibiting permanent in the pool × both seats × four situations ×
    a hand of every type: where the engine refuses because of the permanent,
    the AI does not propose the card and the board does not glow it."""
    control = {}
    for situation in SITUATIONS:
        for hand_name in _HAND:
            game, _ = _w2g3_board(session, situation, hand_name)
            proposed = _w2g3_ai_proposes(game, hand_name)
            glows = _w2g3_glows(session, hand_name)
            control[situation, hand_name] = (
                game.cast_from_hand(0, hand_name).supported, proposed, glows,
            )

    names = _prohibiting_permanents()
    examined = 0
    refusals: Counter = Counter()
    wrong: list[str] = []
    for ban in names:
        for ban_seat in (0, 1):
            for situation in SITUATIONS:
                for hand_name in _HAND:
                    cast_without, _proposed, _glowed = control[situation, hand_name]
                    if not cast_without:
                        continue
                    game, _ = _w2g3_board(
                        session, situation, hand_name, ban=ban, ban_seat=ban_seat,
                    )
                    proposed = _w2g3_ai_proposes(game, hand_name)
                    glows = _w2g3_glows(session, hand_name)
                    result = game.cast_from_hand(0, hand_name)
                    examined += 1
                    if result.supported:
                        continue
                    refusals[ban] += 1
                    where = f"{ban} (seat {ban_seat}), {situation}, {hand_name}: {result.details}"
                    if proposed:
                        wrong.append(f"AI proposes — {where}")
                    if glows:
                        wrong.append(f"board glows — {where}")
    assert not wrong, "\n".join(wrong[:40])

    # The floors. Measured: 17 candidates, 1,224 boards, 332 refusals.
    assert len(names) >= 17, names
    assert {"Steel Golem", "Arcane Laboratory", "Cornered Market", "City of Solitude",
            "Hand to Hand", "Damping Engine"} <= set(names)
    assert examined >= 1200, examined
    assert sum(refusals.values()) >= 320, refusals
    silent = set(names) - set(refusals) - set(_REFUSES_NOTHING_HERE)
    assert not silent, f"prohibiting permanents this matrix never saw refuse: {sorted(silent)}"
    assert set(_REFUSES_NOTHING_HERE) <= set(names)


# --- by construction ---------------------------------------------------------

#: The three readers of the one predicate.
_READERS = {
    "engine/mixins/stack/casting.py": "_cast_onto_stack",
    "engine/ai_policy.py": "_can_cast_with_targets",
    "web/state_view.py": "_card_castable_now",
}


def _row_predicate_names() -> set[str]:
    """Every predicate the table's rows call, read off the table's own module:
    what it imports from the modules that own the printed sentences, plus the
    two it reaches as a method and through a late import."""
    tree = ast.parse((ROOT / "engine/cast_prohibitions.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in (
            "auras", "cast_restrictions", "spell_prohibitions", "legality",
        ):
            names.update(alias.name for alias in node.names)
        if isinstance(node, ast.Attribute) and node.attr == "_set_lockout_banning_card":
            names.add(node.attr)
    return names


def test_w2g3_the_readers_ask_the_predicate_and_keep_no_list_of_their_own():
    predicates = _row_predicate_names()
    assert len(predicates) >= 13, predicates
    assert {"own_cast_ban", "spell_cap_ban", "targeting_ban_refusal",
            "_set_lockout_banning_card"} <= predicates
    for path, function in _READERS.items():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        body = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        )
        called = {
            getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            for call in ast.walk(body) if isinstance(call, ast.Call)
        }
        assert "cast_prohibition" in called, f"{path}::{function} does not ask"
        assert not called & predicates, (
            f"{path}::{function} asks {sorted(called & predicates)} itself — add "
            "the ban to cast_prohibitions.CAST_PROHIBITIONS, where every reader sees it"
        )


def test_w2g3_the_predicate_is_pure(session):
    """Asked on every poll and for every card in an AI's hand, so it may not
    move anything: not the log, not the board, not a turn record."""
    game, _ = _w2g3_board(session, AFTER_A_SPELL, "Grizzly Bears", ban="Arcane Laboratory")
    before = (len(game.log), len(game.players[0].spells_cast_this_turn),
              [p.card.name for p in game.all_permanents()], dict(game.players[0].mana_pool))
    for _ in range(3):
        assert cast_prohibition(game, 0, _POOL["Grizzly Bears"]) is not None
    assert before == (
        len(game.log), len(game.players[0].spells_cast_this_turn),
        [p.card.name for p in game.all_permanents()], dict(game.players[0].mana_pool),
    )
    assert cast_prohibitions.action_of(_POOL["Forest"]) == LAND
    assert cast_prohibitions.action_of(_POOL["Grizzly Bears"]) == SPELL
