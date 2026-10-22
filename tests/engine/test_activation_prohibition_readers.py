"""CR 602.5 has one predicate, and every reader of it agrees.

"A player can't begin to activate an ability that's prohibited from being
activated." The activation path refused a prohibited ability through ten
inline checks; the AI's chooser asked three of them, the wire none, and an
ability activated from a hand or a graveyard — a parallel entry point — asked
one at most. So an AI seat under a City of Solitude, a Hand to Hand, a
Faith's Fetters or a Katabatic Winds proposed the same refused activation
every turn; the client's ability menu offered every ability the text prints
and the click was a 400; and a card was cycled on an opponent's turn.

``engine/activation_prohibitions.py`` is the fold: one table, in the order the
activation path asked them. This file holds it four ways:

* **by row** — every row of ``ACTIVATION_PROHIBITIONS`` has a scenario here (a
  row without one fails), built so the activation is accepted without the
  prohibition and refused with it; the engine, the predicate, the AI and the
  wire are each asked both ways;
* **by pool** — every permanent in the pool printing a sentence shaped like a
  prohibition on activating, on either side of the table, through a matrix of
  situations and subjects. Wherever the engine activates without it and
  refuses with it, no other reader may say yes. Derived from the printed
  text, so a ban a later set brings is swept without being listed;
* **by door** — the three entry points (a permanent, a hand, a graveyard) all
  refuse for the rows that reach their kind of source;
* **by construction** — none of the readers this fold touched calls a row's
  predicate itself, so there is no second list to fall behind.

Validated backwards: with the AI's one call and the wire's one call taken out,
the pool sweep names City of Solitude, Hand to Hand, Faith's Fetters and
Katabatic Winds.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState, ai_abilities
from engine import activation_prohibitions
from engine.activation_prohibitions import (ACTIVATION_PROHIBITIONS,
                                            activation_prohibition)
from engine.auras import attach_aura
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.spell_prohibitions import (forbid_nonmana_activations_this_turn,
                                       forbid_permanent_activations_this_turn)
from tests.helpers import resolve_stack
from web.app import app, store

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]
_POOL = {card.name: card for card in load_catalog()}

OWN_MAIN = "own main"
OPPONENTS_TURN = "an opponent's turn"
OWN_COMBAT = "own combat"
SITUATIONS = (OWN_MAIN, OPPONENTS_TURN, OWN_COMBAT)


@pytest.fixture(scope="module")
def session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4611,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return store.get(sid)


def _board(session, situation, subject_name, *, ban=None, ban_seat=1, arm=None):
    """A fresh game in *session*: *subject_name* on seat 0's battlefield with
    mana for anything, a creature across the table to aim at, optionally one
    prohibiting permanent, in *situation*. Returns the game and the subject."""
    library = [_POOL["Grizzly Bears"]] * 20
    game = Game(players=[
        PlayerState(name="Host", library=list(library)),
        PlayerState(name="Guest", library=list(library)),
    ])
    game.enforce_mana_costs = True
    subject = Permanent(card=_POOL[subject_name])
    game._put_permanent_onto_battlefield(0, subject, None)
    game._put_permanent_onto_battlefield(1, Permanent(card=_POOL["Grizzly Bears"]), None)
    if ban is not None:
        banning = Permanent(card=_POOL[ban])
        game._put_permanent_onto_battlefield(ban_seat, banning, None)
        if "Aura" in _POOL[ban].type_line:
            attach_aura(banning, subject)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()
    game.players[0].mana_pool.update({"W": 9, "U": 9, "B": 9, "R": 9, "G": 9})
    game.turn = 3
    session.game = game
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    if situation == OPPONENTS_TURN:
        session.current_turn = 1
        game.active_player_index = 1
    elif situation == OWN_COMBAT:
        game.current_phase = "combat"
        game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    if arm is not None:
        arm(game, subject)
    game.start_priority_window(0)
    return game, subject


def _engine_activates(session, situation, subject_name, **board) -> "tuple[bool, str]":
    game, subject = _board(session, situation, subject_name, **board)
    result = game.queue_permanent_ability(
        0, subject.card.name,
        permanent_index=game.battlefield_index_of(subject), ability_index=0,
        target_player_index=1,
    )
    return bool(result.supported), result.details


def _predicate(session, situation, subject_name, **board):
    game, subject = _board(session, situation, subject_name, **board)
    ability = game.usable_abilities_of(subject)[0]
    return activation_prohibition(game, 0, subject, ability)


def _ai_proposes(session, situation, subject_name, **board) -> bool:
    game, subject = _board(session, situation, subject_name, **board)
    action = ai_abilities.choose_activation_action(game, 0)
    return action is not None and (
        game.permanent_at(0, action.permanent_index) is subject
    )


def _wire_prohibits(session, situation, subject_name, **board) -> "str | None":
    game, subject = _board(session, situation, subject_name, **board)
    state = client.get(f"/api/sessions/{session.id}/state", params={"seat": 0}).json()
    for entry in state["players"][0]["battlefield"]:
        if entry["id"] == subject.permanent_id:
            return (entry.get("ability_denials") or [None])[0]
    raise AssertionError("the subject is not on the wire")


# --- by row -----------------------------------------------------------------


def _interdict(game, subject):
    forbid_permanent_activations_this_turn(game, subject)


def _abeyance(game, subject):
    forbid_nonmana_activations_this_turn(game, 0)


#: ``row kind -> (situation, subject, prohibiting permanent or None, its seat,
#: arm)``. Every scenario is a board on which the activation path accepts the
#: subject's first ability without the prohibition and refuses it with.
_SCENARIOS: dict[str, tuple] = {
    "permanent_shut_off_this_turn": (OWN_MAIN, "Prodigal Sorcerer", None, 1, _interdict),
    "nonmana_shut_off_this_turn": (OWN_MAIN, "Prodigal Sorcerer", None, 1, _abeyance),
    "global_play_timing": (OPPONENTS_TURN, "Prodigal Sorcerer", "City of Solitude", 1, None),
    "combat_play_ban": (OWN_COMBAT, "Prodigal Sorcerer", "Hand to Hand", 1, None),
    "global_activation_ban": (OWN_MAIN, "Prodigal Sorcerer", "Cursed Totem", 1, None),
    "aura_nonmana_shut_off": (OWN_MAIN, "Prodigal Sorcerer", "Faith's Fetters", 1, None),
    "aura_all_shut_off": (OWN_MAIN, "Prodigal Sorcerer", "Volrath's Curse", 1, None),
    "tap_abilities_shut_off": (OWN_MAIN, "Birds of Paradise", "Katabatic Winds", 1, None),
}

#: The two rows whose prohibition is printed on the ability itself: there is
#: no board without it, so the "accepted without" half is another situation.
_PRINTED: dict[str, tuple] = {
    # "Any player may activate this ability but only during their turn."
    "printed_restriction": ("Volrath's Dungeon", OPPONENTS_TURN, OWN_MAIN),
    # "Only your opponents may activate this ability."
    "printed_permission": ("Clergy of the Holy Nimbus", OWN_MAIN, None),
}


def test_every_row_has_a_scenario():
    kinds = {row.kind for row in ACTIVATION_PROHIBITIONS}
    assert kinds == set(_SCENARIOS) | set(_PRINTED), (
        "a row of ACTIVATION_PROHIBITIONS has no scenario here, or a scenario "
        f"names no row: {sorted(kinds ^ (set(_SCENARIOS) | set(_PRINTED)))}"
    )


@pytest.mark.parametrize("kind", sorted(_SCENARIOS))
def test_a_row_is_refused_by_every_reader(session, kind):
    situation, subject, ban, seat, arm = _SCENARIOS[kind]
    without = {}
    with_it = {"ban": ban, "ban_seat": seat, "arm": arm}

    accepted, details = _engine_activates(session, situation, subject, **without)
    assert accepted, f"the scenario is not clean without the prohibition: {details}"
    assert _predicate(session, situation, subject, **without) is None
    assert _wire_prohibits(session, situation, subject, **without) is None

    accepted, details = _engine_activates(session, situation, subject, **with_it)
    assert not accepted, f"{kind}: the engine activated it anyway"
    found = _predicate(session, situation, subject, **with_it)
    assert found is not None and found.kind == kind, (kind, found)
    # The same prohibition in the same words, by all three.
    assert details == found.details
    assert _wire_prohibits(session, situation, subject, **with_it) == found.details
    assert not _ai_proposes(session, situation, subject, **with_it), (
        f"{kind}: the AI proposes an activation the engine refuses"
    )


def test_the_ai_proposes_the_subject_where_nothing_forbids_it(session):
    """The other half of the row test's AI assertion: the chooser does want
    this ability, so its silence under a prohibition is the gate's doing."""
    assert _ai_proposes(session, OWN_MAIN, "Prodigal Sorcerer")
    assert _ai_proposes(session, OPPONENTS_TURN, "Prodigal Sorcerer")


@pytest.mark.parametrize("kind", sorted(_PRINTED))
def test_a_printed_clause_is_a_row_too(session, kind):
    subject, refused_in, accepted_in = _PRINTED[kind]

    accepted, details = _engine_activates(session, refused_in, subject)
    assert not accepted
    found = _predicate(session, refused_in, subject)
    assert found is not None and found.kind == kind, (kind, found)
    assert details == found.details
    assert _wire_prohibits(session, refused_in, subject) == found.details
    assert not _ai_proposes(session, refused_in, subject)
    if accepted_in is not None:
        assert _predicate(session, accepted_in, subject) is None
        assert _wire_prohibits(session, accepted_in, subject) is None


# --- by pool ----------------------------------------------------------------

_PROHIBITION_SHAPED = re.compile(
    r"can't be activated|activate abilities|can't activate", re.I
)

#: One subject per kind of ability a prohibition tells apart: a creature's
#: {T} ability, a flyer's mana ability, an artifact's, a mana ability on a
#: creature without flying, and a land's non-mana ability.
_SUBJECTS = (
    "Prodigal Sorcerer", "Birds of Paradise", "Rod of Ruin", "Llanowar Elves",
    "Mishra's Factory",
)


def _prohibiting_permanents():
    return sorted(
        card.name for card in compilation_units(_POOL.values())
        if _PROHIBITION_SHAPED.search(card.oracle_text or "")
        and not {"instant", "sorcery"} & set(card.type_line.lower().split())
        and compile_card_oracle(card).supported
    )


def _sweep(session):
    counts: Counter = Counter()
    disagreements = []
    for ban in _prohibiting_permanents():
        for ban_seat in (0, 1):
            for situation in SITUATIONS:
                for subject in _SUBJECTS:
                    if subject == ban:
                        continue
                    board = {"ban": ban, "ban_seat": ban_seat}
                    try:
                        accepted, _details = _engine_activates(session, situation, subject)
                        if not accepted:
                            continue
                        refused = not _engine_activates(
                            session, situation, subject, **board
                        )[0]
                    except Exception:  # noqa: BLE001 — a board the subject cannot stand on
                        continue
                    counts["boards"] += 1
                    if not refused:
                        continue
                    counts["refusals"] += 1
                    row = (ban, ban_seat, situation, subject)
                    if _predicate(session, situation, subject, **board) is None:
                        disagreements.append(("predicate", *row))
                    if _wire_prohibits(session, situation, subject, **board) is None:
                        disagreements.append(("wire", *row))
                    if _ai_proposes(session, situation, subject, **board):
                        disagreements.append(("ai", *row))
    return counts, disagreements


def test_no_reader_offers_what_a_pool_permanent_forbids(session):
    counts, disagreements = _sweep(session)

    # Floors: a sweep that reaches nothing passes. Measured 300 boards, 116
    # of them refused for the prohibiting permanent — every one of which the
    # wire offered and 44 of which the AI proposed, before the fold.
    assert counts["boards"] >= 250 and counts["refusals"] >= 90, counts
    assert disagreements == [], (
        f"{len(disagreements)} readings offer an activation the engine "
        f"refuses: {disagreements[:15]}"
    )


def test_the_sweep_names_a_reader_with_a_list_of_its_own(session, monkeypatch):
    """Backwards: the AI's one call and the wire's taken out, which is each of
    them as it was — the AI asking the three gates it had always asked, the
    wire asking none."""
    import web.serialization

    monkeypatch.setattr(ai_abilities, "activation_prohibition", lambda *args: None)
    monkeypatch.setattr(web.serialization, "activation_prohibition", lambda *args: None)

    _counts, disagreements = _sweep(session)

    named_ai = {row[1] for row in disagreements if row[0] == "ai"}
    named_wire = {row[1] for row in disagreements if row[0] == "wire"}
    assert {"City of Solitude", "Hand to Hand", "Faith's Fetters"} <= named_ai, named_ai
    assert {"City of Solitude", "Cursed Totem", "Null Rod", "Hand to Hand"} <= named_wire


# --- by door ----------------------------------------------------------------


def _cycler():
    """A pool card with a hand ability that costs mana and nothing else to
    name: plain cycling."""
    from engine.activation_zones import HAND
    from engine.targeting import usable_activated_abilities

    return next(
        card.name
        for card in sorted(compilation_units(_POOL.values()), key=lambda card: card.name)
        if "cycling {2}" in (card.oracle_text or "").lower()
        and usable_activated_abilities(compile_card_oracle(card), zone=HAND)
    )


@pytest.mark.parametrize("ban,situation", [
    ("City of Solitude", OPPONENTS_TURN), ("Hand to Hand", OWN_COMBAT),
])
def test_a_hand_ability_is_refused_for_the_rows_that_reach_a_card(session, ban, situation):
    """Cycling on an opponent's turn under a City of Solitude. The hand's door
    is a parallel entry point and asked no prohibition at all."""
    name = _cycler()

    game, _subject = _board(session, situation, "Prodigal Sorcerer")
    game.players[0].hand = [_POOL[name]]
    result = game.activate_from_hand(0, name)
    assert result.supported, result.details

    game, _subject = _board(session, situation, "Prodigal Sorcerer", ban=ban)
    game.players[0].hand = [_POOL[name]]
    hand_before = list(game.players[0].hand)
    pool_before = dict(game.players[0].mana_pool)
    result = game.activate_from_hand(0, name)
    assert not result.supported
    assert ban in result.details
    # Nothing paid and nothing discarded (CR 602.5: it cannot be begun).
    assert game.players[0].hand == hand_before
    assert dict(game.players[0].mana_pool) == pool_before
    assert game.stack == [] and game.players[0].graveyard == []

    # …and the wire's button says so, in the same words.
    state = client.get(f"/api/sessions/{session.id}/state", params={"seat": 0}).json()
    entry = next(e for e in state["hand_abilities"] if e["name"] == name)
    assert entry["payable"] is False and entry["prohibited"] == result.details


def test_an_abeyance_does_not_stop_a_mana_ability_but_stops_cycling(session):
    name = _cycler()

    def arm(game, subject):
        forbid_nonmana_activations_this_turn(game, 0)

    game, _subject = _board(session, OWN_MAIN, "Llanowar Elves", arm=arm)
    elves = _subject
    result = game.queue_permanent_ability(
        0, "Llanowar Elves", permanent_index=game.battlefield_index_of(elves),
        ability_index=0,
    )
    assert result.supported, result.details

    game, _subject = _board(session, OWN_MAIN, "Prodigal Sorcerer", arm=arm)
    game.players[0].hand = [_POOL[name]]
    result = game.activate_from_hand(0, name)
    assert not result.supported
    assert "aren't mana abilities" in result.details


# --- by construction --------------------------------------------------------

#: The predicates the table's rows are built from. A reader calling one of
#: these beside the table has started a list of its own.
_ROW_PREDICATES = frozenset({
    "permanent_activations_forbidden", "nonmana_activations_forbidden",
    "global_play_timing", "combat_play_ban", "global_activation_ban",
    "activation_denial", "activation_permission_denial",
    "aura_restriction_active",
})

#: ``file -> the functions in it that read the table``. ``ai_policy`` is not
#: here: its choosers still ask four of the predicates beside the one call,
#: which is redundant rather than wrong and is that file's owner's to remove.
_READERS = {
    "engine/mixins/stack/activation.py": (
        "_activate_onto_stack", "activate_from_hand", "activate_from_graveyard",
    ),
    "engine/board_payment.py": ("source_tap_yields",),
    "web/serialization.py": None,
    "web/state_view.py": None,
}


def _calls_in(node) -> set[str]:
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            found.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return found


@pytest.mark.parametrize("path", sorted(_READERS))
def test_no_reader_calls_a_rows_predicate_itself(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    wanted = _READERS[path]
    scopes = [tree] if wanted is None else [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    if wanted is not None:
        assert {node.name for node in scopes} == set(wanted), (
            f"{path} no longer defines {sorted(set(wanted) - {n.name for n in scopes})}"
        )
    calls = set().union(*(_calls_in(scope) for scope in scopes))
    assert "activation_prohibition" in calls, f"{path} does not ask the table"
    assert not calls & _ROW_PREDICATES, (
        f"{path} calls {sorted(calls & _ROW_PREDICATES)} beside the table: "
        "add a row to ACTIVATION_PROHIBITIONS instead"
    )


def test_the_table_is_the_only_place_the_rows_are_ordered():
    kinds = [row.kind for row in ACTIVATION_PROHIBITIONS]
    assert len(kinds) == len(set(kinds))
    assert set(activation_prohibitions.__all__) >= {
        "ACTIVATION_PROHIBITIONS", "activation_prohibition",
    }
