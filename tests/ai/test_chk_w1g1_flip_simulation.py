"""The AI plays Champions of Kamigawa's flip cards (CR 710) through whole turns.

A seeded batch with the nine supported flip cards pinned into both decks: the
games finish, no activation of a flip card or its bottom half is refused, no
rehearsal raises, and at least one permanent flips — the subject exercised, a
floor of one, never a count (the seed decides how often).
"""

from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

_FLIP_CARDS = (
    "Jushi Apprentice", "Student of Elements", "Nezumi Graverobber",
    "Nezumi Shortfang", "Akki Lavarunner", "Initiate of Blood",
    "Budoka Gardener", "Orochi Eggwatcher", "Kitsune Mystic",
)
_BOTTOM_HALVES = (
    "Tomoya the Revealer", "Tobita, Master of Winds", "Nighteyes the Desecrator",
    "Stabwhisker the Odious", "Tok-Tok, Volcano Born", "Goka the Unjust",
    "Dokai, Weaver of Life", "Shidako, Broodmistress", "Autumn-Tail, Kitsune Sage",
)


@pytest.mark.full
def test_the_ai_plays_flip_cards_and_some_flip():
    report = run_ai_simulation(
        manifest_set_path("CHK", include_measured=True),
        games=6, seed=7, max_turns=16, required_cards=_FLIP_CARDS,
    )
    assert report.games_completed == report.games_requested
    names = _FLIP_CARDS + _BOTTOM_HALVES
    refused = [
        entry for entry in (report.refused_activations or [])
        if any(name in str(entry) for name in names)
    ]
    assert refused == []
    assert not report.rehearsals_raised
    lines = [str(line) for line in report.log_lines or ()]
    assert any(name in line for line in lines for name in _FLIP_CARDS), "no flip card was played"
    assert any(" flipped: it is " in line for line in lines), "no permanent flipped"
