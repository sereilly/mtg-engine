"""Every instrument that reads a card's lines reads a split card's **halves**.

A split card's own text box is empty and its own compiled program has no
instructions (CR 709.3a: only the chosen half is evaluated, so the halves are
what compile — ``engine/faces.py``). That makes the default outcome for every
census in the repo the same and the same wrong: handed the card whole, it finds
no sentence, no ability and no picker, and reports the card *clean* — fully
claimed over zero sentences, no hollow line among zero abilities, auto-passed
as "no abilities at all".

Each test here is written **backwards**: it asserts the finding an instrument
must make about a half, on a card built so that the old reading (the top-level
text) finds nothing. A census that passes because it looked at nothing fails
these.

The rules themselves are ``tests/rules/test_split_cards.py``; the five Invasion
cards are ``tests/sets/test_inv_instants.py`` / ``test_inv_sorceries.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from engine import Game
from engine.ai_simulator import _zone_counter
from engine.behaviour_signature import behaviour_signature
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import (CAST_FACE_LAYOUTS, castable_faces, combined_oracle_text,
                          face_cards, is_multi_face)
from engine.models import CardDefinition, CardFace, PlayerState
from engine.oracle import (SUPPORTED_LAYOUTS, compile_card_oracle, compiled_faces,
                           simple_card_keywords)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import hook_reliance  # noqa: E402
import oracle_diff  # noqa: E402
import parse_coverage  # noqa: E402
import picker_sweep  # noqa: E402
import support_report  # noqa: E402


def _split(left: CardFace, right: CardFace) -> CardDefinition:
    return CardDefinition(
        name=f"{left.name} // {right.name}",
        mana_cost=f"{left.mana_cost} // {right.mana_cost}",
        cmc=5.0,
        type_line=f"{left.type_line} // {right.type_line}",
        oracle_text="",
        colors=("G", "R"),
        color_identity=("G", "R"),
        keywords=(),
        produced_mana=(),
        raw={},
        layout="split",
        faces=(left, right),
    )


LEFT = CardFace("Left", "{R}", "Sorcery", "Left deals 2 damage to any target.")
RIGHT = CardFace("Right", "{3}{G}", "Sorcery", "Create a 3/3 green Elephant creature token.")
GOOD = _split(LEFT, RIGHT)
#: One readable half and one nothing reads.
HALF_BAD = _split(LEFT, CardFace("Wrong", "{G}", "Sorcery", "Frobnicate the gribble until morning."))


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------


def test_every_multi_face_card_in_the_manifest_compiles_through_its_faces():
    """Both manifest roles. Every card in a layout the compiler admits by its
    faces must *have* faces (a card file that dropped ``card_faces`` loads as a
    blank), and every face must be a spell: supported, with instructions, and
    with a mana cost the cast path can charge."""
    multi = [
        card
        for card in load_cards(manifest_set_paths(include_measured=True))
        if card.layout in CAST_FACE_LAYOUTS
    ]
    for card in multi:
        assert is_multi_face(card), f"{card.name} lost its faces"
        assert card.oracle_text == "", "the whole card has no text box of its own"
        assert compile_card_oracle(card).instructions == ()
        for face, program in compiled_faces(card):
            assert program.supported, f"{card.name} [{face.name}]: {program.reason}"
            assert program.instructions, f"{card.name} [{face.name}] does nothing"
            assert face.mana_cost and face.layout == "normal" and face.face_of is card
    assert CAST_FACE_LAYOUTS <= SUPPORTED_LAYOUTS


def test_the_combined_text_is_what_a_reader_shows_for_the_whole_card():
    assert combined_oracle_text(GOOD) == (
        "Left — Left deals 2 damage to any target.\n"
        "Right — Create a 3/3 green Elephant creature token."
    )
    bolt = CardDefinition(
        name="Test Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="Test Bolt deals 3 damage to any target.", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(), raw={},
    )
    assert combined_oracle_text(bolt) == bolt.oracle_text
    assert castable_faces(bolt) == (bolt,)


# ---------------------------------------------------------------------------
# parse_coverage
# ---------------------------------------------------------------------------


def test_parse_coverage_claims_the_sentences_of_both_halves():
    """Read whole, the card has no sentence: nothing claimed, nothing
    unclaimed, "fully claimed". Both halves' sentences must be in the claims."""
    coverage = parse_coverage.analyze_card(
        GOOD, parse_coverage._hooked_names(), run_probe=False
    )
    assert coverage.name == "Left // Right" and coverage.supported
    claimed = [sentence for sentence, _channel in coverage.claims]
    assert claimed == [
        "left deals 2 damage to any target",
        "create a 3/3 green elephant creature token",
    ]
    assert coverage.unclaimed == []


def test_parse_coverage_reports_a_halfs_unclaimed_sentence_under_the_card(monkeypatch):
    """The finding itself: a sentence on a half that nothing claims is the
    card's finding. Made deterministic by taking one claim channel away, so the
    test does not depend on which sentences the parser happens to read today."""
    hooked = parse_coverage._hooked_names()
    real = parse_coverage.analyze_card

    def half_with_a_gap(card, hooked_names, run_probe=True):
        coverage = real(card, hooked_names, run_probe=run_probe)
        if card.name == "Right":
            coverage.unclaimed.append("a sentence nothing implements")
        return coverage

    monkeypatch.setattr(parse_coverage, "analyze_card", half_with_a_gap)
    coverage = real(GOOD, hooked, run_probe=False)

    assert coverage.unclaimed == ["a sentence nothing implements"]
    assert coverage.name == "Left // Right"


# ---------------------------------------------------------------------------
# support_report
# ---------------------------------------------------------------------------


def test_the_refusals_census_quotes_the_refused_line_of_the_half_that_failed():
    ((name, _primary, headline, lines),) = support_report.refusals_report([GOOD, HALF_BAD])

    assert name == "Left // Wrong"
    assert headline.startswith("Wrong: ")
    assert [(status, line) for status, line, _detail in lines] == [
        ("refused", "Frobnicate the gribble until morning."),
    ], "the half that compiles is not part of why the card is refused"


def test_the_hollow_lines_census_reads_each_halfs_program(monkeypatch):
    """A hollow ability on a half is the card's hollow line. The whole card's
    own program has no abilities at all, so the old reading reports none."""
    from engine import oracle
    from engine.oracle_types import ParsedActivatedAbility

    hollow = ParsedActivatedAbility.__new__(ParsedActivatedAbility)
    object.__setattr__(hollow, "supported", True)
    object.__setattr__(hollow, "instruction", None)
    object.__setattr__(hollow, "source_line", "{T}: A line with nothing behind it.")
    real = oracle.compiled_faces

    def with_a_hollow_half(card):
        pairs = list(real(card))
        if card is GOOD:
            face, program = pairs[1]
            pairs[1] = (face, program.__class__(
                True, program.effect_kind, program.reason, program.normalized_text,
                program.instructions, (hollow,),
            ))
        return tuple(pairs)

    monkeypatch.setattr(oracle, "compiled_faces", with_a_hollow_half)

    assert support_report.hollow_lines_report([GOOD]) == [
        ("Left // Right", "activated", "{T}: A line with nothing behind it."),
    ]


# ---------------------------------------------------------------------------
# picker_sweep
# ---------------------------------------------------------------------------


def test_the_picker_sweep_asks_each_half_for_its_picker(monkeypatch):
    """The Roots class on a half: its line names a target and no picker is
    derived. Forced by taking the half's spec away, so the finding is about the
    sweep and not about today's derivation."""
    assert picker_sweep.sweep([GOOD]) == {
        "no_picker": [], "phantom_picker": [], "activation_no_picker": [],
        "acknowledged": [],
    }

    real = picker_sweep.derive_cast_spec
    monkeypatch.setattr(
        picker_sweep, "derive_cast_spec",
        lambda card, program: None if card.name == "Left" else real(card, program),
    )
    assert picker_sweep.sweep([GOOD])["no_picker"] == [
        ("Left // Right [Left]", "Left deals 2 damage to any target."),
    ]


# ---------------------------------------------------------------------------
# hook_reliance / oracle_diff / behaviour classes / auto-pass
# ---------------------------------------------------------------------------


def test_hook_reliance_counts_each_halfs_lines_and_a_hook_keyed_on_a_half():
    stats = hook_reliance.Stats()
    hook_reliance._count_card(GOOD, set(), stats)
    assert (stats.cards, stats.supported_cards, stats.lines) == (1, 1, 2)
    assert stats.hooked_cards == 0

    stats = hook_reliance.Stats()
    hook_reliance._count_card(GOOD, {"Right"}, stats)
    assert stats.hooked_cards == 1, "a hook on a half is a hook on the card"


def test_the_program_differential_snapshots_each_half(monkeypatch):
    """The whole card's program is empty by construction, so a snapshot of it
    alone compares equal across any change to what a half does."""
    monkeypatch.setattr(oracle_diff, "load_pool", lambda: [GOOD])
    snapshot = oracle_diff.snapshot_pool()

    assert sorted(snapshot) == [
        "Left // Right", "Left // Right [Left]", "Left // Right [Right]",
    ]
    assert snapshot["Left // Right"]["instructions"] == "()"
    assert "deal_damage" in snapshot["Left // Right [Left]"]["instructions"]
    assert "create_token" in snapshot["Left // Right [Right]"]["instructions"]

    moved = _split(
        CardFace("Left", "{R}", "Sorcery", "Left deals 3 damage to any target."), RIGHT,
    )
    monkeypatch.setattr(oracle_diff, "load_pool", lambda: [moved])
    _added, _removed, changed = oracle_diff.compare_snapshots(
        snapshot, oracle_diff.snapshot_pool()
    )
    assert list(changed) == ["Left // Right [Left]"]


def test_a_split_cards_behaviour_signature_is_its_halves():
    """Two split cards that differ in what one half *does* are different
    behaviour classes, and a split card is never the peer of a card with one
    face — its signature carries a ``faces`` key no single-face card has."""
    signature = json.loads(behaviour_signature(GOOD))
    assert [face["instructions"][0][0] for face in signature["faces"]] == [
        "deal_damage", "create_token",
    ]
    other = _split(
        LEFT, CardFace("Right", "{3}{G}", "Sorcery", "Draw two cards."),
    )
    assert behaviour_signature(other) != behaviour_signature(GOOD)
    for face in face_cards(GOOD):
        assert "faces" not in json.loads(behaviour_signature(face))


def test_a_split_card_is_never_auto_passed():
    """``simple_card_keywords`` answers ``()`` — "no abilities at all" — for any
    supported card with an empty text box and no abilities on its program,
    which describes every split card exactly. The verification tracker would
    then record a two-spell card as passing with no check."""
    assert compile_card_oracle(GOOD).supported and GOOD.oracle_text == ""
    assert simple_card_keywords(GOOD) is None


def test_the_simulators_conservation_audit_counts_a_half_as_its_card():
    """A spell on the stack is the half, under the half's name; every other
    zone holds the whole card. The audit compares name counts before and after
    an action, so a suspended half must count as the card it is half of —
    and a half that reached a graveyard *without* becoming whole is then
    visible as a card under a name the deck never held."""
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.players[0].hand.append(GOOD)
    before = _zone_counter(game)

    assert game.queue_from_hand(0, "Left", target_player_index=1).supported
    assert game.stack[-1].card.name == "Left"
    assert _zone_counter(game) == before == {"Left // Right": 1}

    game.resolve_stack()
    assert _zone_counter(game) == before

    # The leak the audit exists to see, made by hand.
    game.players[0].graveyard[0] = face_cards(GOOD)[0]
    assert _zone_counter(game) == {"Left": 1}
