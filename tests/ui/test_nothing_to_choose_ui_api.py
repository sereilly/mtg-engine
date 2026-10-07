"""A picker with nothing in it, for an ability that owes no target.

"{2}: The next time an artifact source of your choice would deal damage to you
this turn, prevent that damage." (Circle of Protection: Artifacts.) A source is
*chosen*, not targeted (CR 609.7a: "The source is chosen when the effect is
created"), so the ability owes no target and may be activated on a table with
no artifact at all. The engine has always accepted that activation — it arms
the shield against the next source of the printed kind — but a person could
not make it: the browser's activation cascade refuses an empty picker ("No
valid artifact targets in play") for every kind alike, and the wire called the
picker ``requires_target``.

The wire says what is true now. ``web/serialization.py`` asks the engine's own
"does this ability owe a target?" (``legality.activation_target_obligation``)
and marks the spec ``may_name_nothing`` — with ``requires_target`` false
beside it — and the client turns an empty picker of that kind into a question
("Nothing to choose … activate it anyway?") instead of a refusal.

The census is over the whole pool: every activated ability whose picker is one
object or player and owes nothing. **38** of them, the colour and type Circles
and Runes first, and a planeswalker's "+1: … up to one target creature" with
them. Each is put alone on a table (so there is nothing to pick), read off the
wire, and activated bare.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.legality import activation_target_obligation
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import app_js_function_body, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)
_POOL = load_catalog()
_CARDS = {card.name: card for card in _POOL}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session(board, opposing=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.graveyard = []
        player.hand = []
    for seat, names in ((0, board), (1, opposing)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            permanent.tapped = False
    game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _permanent(sid, name):
    """*name*'s payload on seat 0's battlefield, or None where it is not there
    (a land that enters only by sacrificing another did not enter)."""
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return next(
        (p for p in state["players"][0]["battlefield"] if p["name"] == name), None
    )


def _spec(entry, index):
    specs = entry.get("ability_target_specs")
    return specs[index] if specs else entry["target_spec"]


def _candidates():
    """``(card name, ability index)`` for every shipped ability the program
    says owes no target while still deriving a picker — the cheap half of the
    question, asked of the compiled program so the wire is built only for
    these."""
    found = []
    for card in _POOL:
        if card.primary_type in ("instant", "sorcery"):
            continue
        usable = usable_activated_abilities(compile_card_oracle(card))
        for index, ability in enumerate(usable):
            derived = derive_activation_spec(ability)
            if not derived or derived.get("kind") in (None, "none"):
                continue
            if activation_target_obligation(ability) is None:
                found.append((card.name, index))
    return found


@pytest.fixture(scope="module")
def census():
    rows = []
    for name, index in _candidates():
        sid, game = _session([name])
        entry = _permanent(sid, name)
        if entry is None:
            continue
        spec = _spec(entry, index)
        if not spec.get("may_name_nothing"):
            rows.append({"name": name, "index": index, "marked": False, "spec": spec})
            continue
        response = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "activate", "permanent_name": name,
            "permanent_id": entry["id"], "ability_index": index,
        })
        rows.append({
            "name": name, "index": index, "marked": True, "spec": spec,
            "card": entry, "status": response.status_code,
            "detail": response.json().get("detail") if response.status_code != 200 else None,
        })
    return rows


def test_every_picker_the_wire_calls_unowed_is_one_the_engine_takes_bare(census):
    marked = [row for row in census if row["marked"]]

    assert len(marked) >= 30, len(marked)
    for row in marked:
        # Nothing is targeted, so nothing is owed — and the field that said
        # otherwise says so too.
        assert row["spec"]["requires_target"] is False, row["name"]
        # Whatever else may refuse it (a loyalty cost, a timing clause), the
        # activation is never refused for want of a target.
        assert "needs a target" not in str(row["detail"] or ""), row


def test_the_circles_and_runes_are_all_there(census):
    """The cards the defect was reported on, by what makes them this shape: a
    chosen source, flagged ``source_of_choice`` or offered the stack beside
    the battlefield."""
    marked = {row["name"]: row for row in census if row["marked"]}

    for name in (
        "Circle of Protection: Artifacts", "Circle of Protection: Red",
        "Circle of Protection: Black", "Rune of Protection: Lands",
        "Rune of Protection: Artifacts", "Rune of Protection: Red",
        "Circle of Protection: Shadow", "Greater Realm of Preservation",
    ):
        row = marked[name]
        assert row["spec"].get("source_of_choice") or row["spec"].get("also_stack"), name
        assert row["spec"]["valid_targets"] == [], name
        assert row["status"] == 200, row
    # …and the other shape, which the same refusal met: "up to one target".
    assert marked["Basri Ket"]["spec"]["kind"] == "creature"
    assert marked["Basri Ket"]["status"] == 200


def test_an_ability_that_owes_its_target_is_not_marked():
    """The negative control, on the same route: Prodigal Sorcerer's "any
    target" and Royal Assassin's "target tapped creature" owe one, are not
    marked, and a bare activation of either is the 400 it always was."""
    for name in ("Prodigal Sorcerer", "Royal Assassin", "Rod of Ruin"):
        sid, _game = _session([name])
        entry = _permanent(sid, name)

        assert "may_name_nothing" not in entry["target_spec"], name
        assert entry["target_spec"]["requires_target"] is True, name
        response = client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "activate", "permanent_name": name,
            "permanent_id": entry["id"],
        })
        assert response.status_code == 400, name
        assert "target" in response.json()["detail"], name


def test_a_cost_and_a_counted_list_are_not_this_question():
    """A sacrifice is paid, not named-or-not, and "X target lands" has a
    prompt of its own: neither is offered "activate it anyway"."""
    for name in ("Atog", "Candelabra of Tawnos"):
        sid, _game = _session([name])
        entry = _permanent(sid, name)
        assert "may_name_nothing" not in entry["target_spec"], name


def test_a_source_less_circle_shields_against_its_printed_kind():
    """What the engine does with the activation the client can now send: no
    source named, so the shield answers to the next *artifact* source — and
    to nothing else."""
    from engine.damage_events import deal_damage

    sid, game = _session(["Circle of Protection: Artifacts"])
    entry = _permanent(sid, "Circle of Protection: Artifacts")
    assert entry["target_spec"]["valid_targets"] == []

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate",
        "permanent_name": "Circle of Protection: Artifacts",
        "permanent_id": entry["id"],
    })
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert "Host sets a Circle of Protection shield against an artifact source" in game.log

    giant = Permanent(card=_CARDS["Hill Giant"])
    game._put_permanent_onto_battlefield(1, giant, None)
    juggernaut = Permanent(card=_CARDS["Juggernaut"])
    game._put_permanent_onto_battlefield(1, juggernaut, None)
    host = game.players[0]
    red = deal_damage(game, {"recipient": host, "amount": 3, "source": giant, "combat": False})
    assert red.dealt == 3
    artifact = deal_damage(
        game, {"recipient": host, "amount": 5, "source": juggernaut, "combat": False}
    )
    assert artifact.dealt == 0
    assert game.log[-1] == (
        "Circle of Protection prevented 5 damage to Host from a artifact source"
    )


def test_with_a_source_to_choose_the_picker_still_offers_it():
    sid, _game = _session(["Circle of Protection: Artifacts"], opposing=["Juggernaut"])
    entry = _permanent(sid, "Circle of Protection: Artifacts")

    spec = entry["target_spec"]
    assert spec["may_name_nothing"] is True and spec["source_of_choice"] is True
    assert [t["name"] for t in spec["valid_targets"]] == ["Juggernaut"]


# --- the client ---------------------------------------------------------------

_PRELUDE = r'''
const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };
'''


@needs_node
def test_the_client_asks_instead_of_refusing(census):
    """The client's own reading of every marked payload: with nothing to pick
    it is a question, the question says whether a source or a target is
    missing, and the answer "yes" leaves a spec no target branch will stop."""
    marked = [row for row in census if row["marked"]]
    asked = [
        {"card": row["card"], "index": row["index"], "name": row["name"]}
        for row in marked
    ]

    answers = run_app_js(
        ["targetSpecOf", "abilityMayNameNothing", "abilityHasNothingToChoose",
         "abilityChoosesASource", "nothingToChooseText", "withNothingChosen"],
        """
        return INPUT.map((q) => {
          const specs = q.card.ability_target_specs;
          const card = specs ? { ...q.card, target_spec: specs[q.index] } : q.card;
          const answered = withNothingChosen(card, q.index);
          return {
            mayNameNothing: abilityMayNameNothing(card),
            nothingToChoose: abilityHasNothingToChoose(card),
            source: abilityChoosesASource(card),
            text: nothingToChooseText(card, q.name),
            after: {
              kind: answered.target_spec.kind,
              stillAsks: abilityHasNothingToChoose(answered) && !answered.__choseNothing,
              index: answered.__abilityIndex,
              name: answered.name,
            },
          };
        });
        """,
        asked, prelude=_PRELUDE,
    )

    for row, answer in zip(marked, answers):
        assert answer["mayNameNothing"] is True, row["name"]
        assert answer["nothingToChoose"] is (row["spec"]["valid_targets"] == []), row["name"]
        chooses_source = bool(
            row["spec"].get("source_of_choice") or row["spec"].get("also_stack")
        )
        assert answer["source"] is chooses_source, row["name"]
        assert ("CR 609.7a" in answer["text"]) is chooses_source, row["name"]
        assert answer["after"] == {
            "kind": "none", "stillAsks": False, "index": row["index"], "name": row["name"],
        }
    assert sum(1 for answer in answers if answer["nothingToChoose"]) >= 20


@needs_node
def test_an_owed_target_is_never_asked_this_way():
    sid, _game = _session(["Prodigal Sorcerer"])
    entry = _permanent(sid, "Prodigal Sorcerer")

    answer = run_app_js(
        ["targetSpecOf", "abilityMayNameNothing", "abilityHasNothingToChoose"],
        "return [abilityMayNameNothing(INPUT), abilityHasNothingToChoose(INPUT), "
        "abilityHasNothingToChoose('a string'), abilityHasNothingToChoose(null)];",
        entry, prelude=_PRELUDE,
    )

    assert answer == [False, False, False, False]


def test_the_cascade_asks_before_any_branch_can_refuse_the_empty_list():
    """Text-level, because ``startActivationPrompt`` is a DOM-bound cascade.
    The question sits ahead of every branch that says "No valid … targets",
    and behind the prohibition check: a forbidden ability is not asked
    anything."""
    cascade = app_js_function_body("startActivationPrompt")

    asked = cascade.index("abilityHasNothingToChoose(card)")
    assert cascade.index("abilityProhibitionOf(card, abilityIndex)") < asked
    refusals = [
        at for at in range(len(cascade))
        if cascade.startswith("updateActionHint(`No valid", at)
    ]
    assert len(refusals) >= 6
    assert all(asked < at for at in refusals)
    assert "nothingToChoose: { card, text: nothingToChooseText(card, cardName) }" in cascade

    confirm = app_js_function_body("confirmPendingActivation")
    assert "withNothingChosen(pending.nothingToChoose.card, pending.abilityIndex)" in confirm
    # The auto-submit loop pays a cost once the pool covers it; a question is
    # not a payment and must not be answered by a full mana pool.
    assert "pendingActivation.nothingToChoose" in app_js_function_body(
        "attemptPendingActivation"
    )


def test_a_chosen_source_is_called_a_source_in_its_prompt():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert 'pendingSpec?.source_of_choice && !isSacrificeCost ? "source" : "target"' in source
    assert "`Choose a source for ${pendingCastTarget.cardName}`" in source
