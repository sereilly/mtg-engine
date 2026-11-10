"""``explain_cast``: the AI's cast decision, read off the decision's own trace
— and the one place every cast candidate is scored.

An agent at Mirrodin's promotion spent most of a round writing probes to find
that Wail of the Nim's entwined cast lacked the zone's bonus its single modes
carried out of an opened graveyard (``ai_cast_score.zone_cast_bonus``), so it lost
to its own best mode. ``engine/ai_cast_explain.py`` prints that in one call:
every candidate, every term of its score, why each dropped one was dropped.
The terms are recorded where they are summed (``ai_cast_trace``), so the
explanation is the decision's own numbers.

The defect class was "an adjustment added inline by one candidate builder and
not its sibling". The adjustments are added in one function now
(``ai_cast_score.finished_cast_candidate``), and that found one more: an instant
weighed **at instant speed** never had the zone's bonus, so a Lightning Bolt in
a graveyard opened until end of turn was cast from it in the main phase and
left there for the hand's copy at the opponent's end step. The guards at the
bottom hold every builder to the one function.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path

from engine import ai_cast_trace as cast_trace
from engine.ai_cast_explain import explain_cast
from engine.ai_cast_score import EXPIRING_PERMISSION_BONUS
from engine.ai_policy import choose_cast_action, choose_combat_instant_cast_action
from engine.ai_scoring import summed_terms
from tests.regressions import test_ody_w2g2_zone_cast_census as zone

ME, OPP = zone.ME, zone.OPP
ROOT = Path(__file__).resolve().parents[2]


def _at_the_opponents_end_step(game) -> None:
    game.active_player_index = OPP
    game.current_turn_phase = "ending"
    game.current_step = "end"


def _without_the_zone(candidate) -> list:
    return [term for term in candidate.terms if term[0] != "zone bonus"]


# --- the breakdown ----------------------------------------------------------------


def test_every_candidate_of_an_entwined_cast_names_the_zone_bonus():
    """Wail of the Nim out of a graveyard opened until end of turn: each mode
    and the entwined cast of both carry the bonus, the entwined cast wins, and
    the reading from the hand is the same reading less the bonus."""
    wail = zone.BY_NAME["Wail of the Nim"]
    opened = explain_cast(zone.rig(wail, "graveyard_open", floating=zone.FLOATING), ME, wail)
    held = explain_cast(zone.rig(wail, None, floating=zone.FLOATING), ME, wail)

    for explanation, bonus in ((opened, EXPIRING_PERMISSION_BONUS), (held, 0.0)):
        scored = [c for c in explanation.candidates if c.score is not None]
        assert sorted((c.variant, c.mode_index) for c in scored) == [
            ("entwined", None), ("single", 0), ("single", 1),
        ]
        for candidate in scored:
            assert candidate.term("zone bonus") == bonus, candidate
            assert summed_terms(candidate.terms) == candidate.score
            assert candidate.rehearsal is not None
        assert explanation.winner is not None
        assert explanation.winner.variant == "entwined"
        assert explanation.winner.offers == {"{B}": 1}

    assert opened.decision.from_zone == "graveyard"
    assert held.decision.from_zone == "hand"
    assert _without_the_zone(opened.winner) == _without_the_zone(held.winner)
    text = opened.render()
    assert "zone bonus +4.00" in text
    assert "PICKED - this is the decision" in text
    assert "a permission that ends" in text


def test_explaining_reads_the_decision_and_moves_nothing():
    """The explanation's decision is the chooser's, asked before and after;
    explaining draws nothing from the seeded generator; and with nobody
    listening the hooks hold no trace."""
    wail = zone.BY_NAME["Wail of the Nim"]
    game = zone.rig(wail, "graveyard_open", floating=zone.FLOATING)
    random.seed(4242)
    state = random.getstate()
    before = choose_cast_action(game, ME)
    assert random.getstate() == state
    explanation = explain_cast(game, ME, wail)
    assert random.getstate() == state
    after = choose_cast_action(game, ME)

    said = zone.announced(game, explanation.decision)
    assert said == zone.announced(game, before) == zone.announced(game, after)
    assert explanation.decision.score == before.score == after.score
    assert cast_trace.silent()


def test_a_candidate_gated_out_names_the_gate():
    """A card the seat cannot pay for is weighed and dropped, and says so: the
    rig's graveyard holds a {50} sorcery the opened graveyard makes castable."""
    wail = zone.BY_NAME["Wail of the Nim"]
    game = zone.rig(wail, "graveyard_open", floating=zone.FLOATING)
    buried = next(card for card in game.players[ME].graveyard if card.name == "Buried Sorcery")
    explanation = explain_cast(game, ME, buried)

    (candidate,) = explanation.candidates
    assert candidate.action is None
    assert candidate.dropped.startswith("unaffordable")
    assert explanation.winner is None
    assert explanation.decision.card_name == "Wail of the Nim"
    assert "DROPPED: unaffordable" in explanation.render()


# --- the sibling that lacked the bonus -----------------------------------------------


def test_an_instant_under_a_permission_that_ends_goes_first_at_instant_speed_too():
    """Lightning Bolt in the hand and in a graveyard opened until end of turn.
    The main phase casts the graveyard's copy (the hand's is still there
    tomorrow); at the opponent's end step the instant-speed chooser cast the
    hand's, the graveyard's copy tied without the bonus and the tie went to
    the hand. Both choosers finish a candidate in one place now."""
    bolt = zone.BY_NAME["Lightning Bolt"]
    game = zone.rig(bolt, "graveyard_open", lands=["Mountain"] * 2)
    game.players[ME].hand.append(bolt)
    assert choose_cast_action(game, ME).from_zone == "graveyard"

    _at_the_opponents_end_step(game)
    action = choose_combat_instant_cast_action(game, ME)
    assert action is not None and action.from_zone == "graveyard"

    explanation = explain_cast(game, ME, bolt)
    assert explanation.speed == "instant"
    picks = {entry.from_zone: pick for entry, pick in zip(explanation.entries, explanation.picks())}
    assert picks["graveyard"].term("zone bonus") == EXPIRING_PERMISSION_BONUS
    assert picks["hand"].term("zone bonus") == 0.0
    assert _without_the_zone(picks["graveyard"]) == _without_the_zone(picks["hand"])
    assert explanation.winner is picks["graveyard"]


# --- the guards: one place scores a cast ------------------------------------------


def _census_board(speed: str):
    """A hand weighing every builder: one mode and another, an entwined cast,
    "choose one or more" (Sublime Epiphany), a kicker, a creature — each in the
    hand and again in a graveyard opened until end of turn."""
    names = ["Wail of the Nim", "Sublime Epiphany", "Agonizing Demise",
             "Grizzly Bears", "Lightning Bolt"]
    first = zone.BY_NAME[names[0]]
    game = zone.rig(first, "graveyard_open", floating=zone.FLOATING)
    for name in names:
        game.players[ME].hand.append(zone.BY_NAME[name])
    for name in names[1:]:
        game.players[ME].graveyard.append(zone.BY_NAME[name])
    if speed == "instant":
        _at_the_opponents_end_step(game)
    return game


def test_every_candidate_a_chooser_returns_was_finished_in_the_one_place():
    """For every place each chooser weighs, the candidate it returned is one
    the trace saw finished — its terms summing to its score, the zone's bonus
    among them — and every candidate it dropped says why. A builder that
    scored a cast for itself returns a candidate with no terms behind it."""
    seen_variants = set()
    for speed, chooser in (
        ("main", choose_cast_action), ("instant", choose_combat_instant_cast_action),
    ):
        game = _census_board(speed)
        with cast_trace.listening(game, ME, speed) as trace:
            chooser(game, ME)
        returned = [entry for entry in trace.entries if entry.result is not None]
        assert len(returned) >= 4, (speed, [e.card.name for e in returned])
        for entry in trace.entries:
            for candidate in entry.candidates:
                assert candidate.action is not None or candidate.dropped, (
                    speed, entry.card.name, candidate,
                )
        for entry in returned:
            (pick,) = [c for c in entry.candidates if c.action is entry.result]
            seen_variants.add(pick.variant)
            assert summed_terms(pick.terms) == entry.result.score, (speed, entry.card.name)
            expected = EXPIRING_PERMISSION_BONUS if entry.from_zone == "graveyard" else 0.0
            assert pick.term("zone bonus") == expected, (speed, entry.card.name)
    assert {"single", "entwined", "every mode"} <= seen_variants


#: What adds a term to a cast's score. Outside ``ai_scoring`` — whose tutor
#: weighs a card in the abstract, never as a cast candidate — only the one
#: function that finishes a candidate may call them.
_SCORERS = {"_score_cast", "cast_score_terms", "zone_cast_bonus", "stack_response_bonus"}
_FINISHER = ("ai_cast_score.py", "finished_cast_candidate")
#: The one ``CastAction`` built with a score other than 0.0: every mode of a
#: "choose one or more" spell, the best mode's finished score and more.
_DERIVED = ("ai_casts.py", "_one_cast_of_every_mode")


def _calls(path: Path):
    """``(function name, call node)`` for every call in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                yield function.name, node


def _name(call: ast.Call) -> "str | None":
    return getattr(call.func, "attr", None) or getattr(call.func, "id", None)


def test_no_builder_scores_a_cast_for_itself():
    """Every cast candidate is scored by ``ai_cast_score.finished_cast_candidate``:
    the scorer and the zone's and the stack's adjustments are called there
    and nowhere else, and every other ``CastAction`` is built at 0.0 for it
    to finish. An adjustment added inline at one builder is how an entwined
    cast lost to its own best mode."""
    paths = sorted((ROOT / "engine").glob("ai_*.py")) + sorted((ROOT / "web").glob("*.py"))
    scorers, built = [], []
    for path in paths:
        for function, call in _calls(path):
            name = _name(call)
            if name in _SCORERS and path.name != "ai_scoring.py":
                scorers.append((path.name, function, name))
            if name == "CastAction":
                score = next((k.value for k in call.keywords if k.arg == "score"), None)
                zero = isinstance(score, ast.Constant) and score.value == 0.0
                if not zero:
                    built.append((path.name, function))
    stray = sorted({row for row in scorers if row[:2] != _FINISHER})
    assert not stray, f"a cast scored outside finished_cast_candidate: {stray}"
    assert {row[2] for row in scorers} == {"cast_score_terms", "zone_cast_bonus",
                                           "stack_response_bonus"}
    assert set(built) <= {_DERIVED}, f"a CastAction built with its own score: {built}"
