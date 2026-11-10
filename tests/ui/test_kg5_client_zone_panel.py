"""The zone panel names whose zone it shows, shows that seat's, and gets out
of the way once a card is played from it.

Two Mirrodin leftovers (Shared Fate's board, three seats):

* **Whose zone.** The panel had one set of opponent sections ("opp-"),
  rendered from the *classic* opponent's zones, and every opponent's pile
  opened it: in a Free-For-All a click on a corner seat's exile pile opened
  "Opponent Exile" listing **another** player's exile — so a Shared Fate card
  exiled from that seat's library was never shown to its exiler, and a
  graveyard target in that seat's pile was never offered. Each corner seat
  now has its own sections (``seat<N>-``, ``renderFfaZoneSections``), and an
  opponent's section is titled with the seat's name wherever "Opponent"
  could mean more than one.
* **After a play.** The panel stayed open over the piles after the card was
  played ("Opponent Exile (0)"); the click that plays from it closes it.

Driven in a browser at three seats (Shared Fate exiling AI Serra's Shock,
played from her exile; Animate Dead offered a creature card in each opponent's
graveyard); here the client functions are run over the payload shape.
"""
from __future__ import annotations

import shutil

import pytest

from tests.helpers import app_js_function_body, run_app_js

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

_FUNCTIONS = [
    "classicOppSeat", "zoneRevealSectionFor", "zoneRevealOwnerLabel", "zoneRevealTitleFor",
]
_PRELUDE = """
let seat = 0;
let currentState = null;
const ZONE_REVEAL_KIND_LABELS = {
  graveyard: "Graveyard", exile: "Exile", ante: "Ante",
  command: "Command Zone", sideboard: "Cards Outside the Game",
};
"""


def _players(*names):
    return {"players": [{"name": name} for name in names]}


@needs_node
def test_every_opponent_has_a_section_of_its_own_at_three_and_four_seats():
    out = run_app_js(
        _FUNCTIONS,
        """
        const read = (state) => {
          currentState = state;
          return state.players.map((_, s) => zoneRevealSectionFor(s, "exile"));
        };
        return { three: read(INPUT.three), four: read(INPUT.four), two: read(INPUT.two) };
        """,
        {
            "three": _players("Me", "Mishra", "Serra"),
            "four": _players("Me", "B", "C", "D"),
            "two": _players("Me", "AI"),
        },
        prelude=_PRELUDE,
    )
    # The classic opponent keeps the static "opp-" sections (index.html);
    # every other opponent is a section of its own — no two seats share one.
    assert out["two"] == ["self-exile", "opp-exile"]
    assert out["three"] == ["self-exile", "opp-exile", "seat2-exile"]
    assert out["four"] == ["self-exile", "seat1-exile", "opp-exile", "seat3-exile"]


@needs_node
def test_a_section_is_titled_by_whose_zone_it_is():
    out = run_app_js(
        _FUNCTIONS,
        """
        currentState = INPUT.three;
        const ffa = ["self-exile", "opp-exile", "seat2-exile", "seat2-graveyard", "self-sideboard"]
          .map((s) => zoneRevealTitleFor(s));
        currentState = INPUT.two;
        const duel = ["opp-exile", "self-graveyard"].map((s) => zoneRevealTitleFor(s));
        return { ffa, duel };
        """,
        {"three": _players("Me", "AI Mishra", "AI Serra"), "two": _players("Me", "AI")},
        prelude=_PRELUDE,
    )
    assert out["ffa"] == [
        "Your Exile", "AI Mishra's Exile", "AI Serra's Exile", "AI Serra's Graveyard",
        "Your Cards Outside the Game",
    ]
    # Two seats: "Opponent" names one player, and stays.
    assert out["duel"] == ["Opponent Exile", "Your Graveyard"]


def test_the_board_renders_every_corner_seats_sections():
    """``renderBoard`` builds them each state (the classic opponent's are the
    static ones); the click on a castable card in any of them plays from it."""
    body = app_js_function_body("renderBoard")
    assert "renderFfaZoneSections(state, viewerSeat, oppSeat);" in body


def test_a_play_from_the_panel_closes_it_before_the_cast_asks_anything():
    """The castable card's click closes the panel and then starts the play —
    the madness answer and the ordinary zone cast alike — after the one guard
    that refuses the click (a cast already under way) has passed."""
    body = app_js_function_body("renderZoneCards")
    guard = body.index("Finish the current cast before starting another.")
    closes = body.index("closeZoneReveal();", guard)
    assert closes < body.index("beginMadnessCast(madness)", guard)
    assert closes < body.index("beginZoneCast(zoneEntry?.card || card, zoneKind, zoneEntry)", guard)
