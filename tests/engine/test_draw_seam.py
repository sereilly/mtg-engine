"""Guard: every in-game draw goes through one seam.

``Game._draw_with_replacements`` is where drawing becomes an *event*: CR 614
lets a replacement take it (Aladdin's Lamp, Ring of Ma'rûf) or change how many
cards it is (Teferi's Ageless Insight), and CR 121.2 makes a multi-card
instruction that many individual draws, each replaceable on its own.
``PlayerState.draw`` is the library operation underneath — it moves cards and
knows nothing about the game.

Reaching for the library operation directly is how a replacement gets skipped,
and unlike the counter seam this one **acquired the debt before it was
guarded**: five handlers took their cards off the library themselves, so a Wheel
of Fortune drew seven cards past an armed Teferi's Ageless Insight and a Sindbad
drew past an armed Lamp. The counter guard beside this one was written to stop
that shape spreading (round 31) and cites this debt by name; this is the debt
being paid.

Three calls remain and all three are **pregame**: CR 103.4's opening hand and
the two mulligan redraws. Nothing is on any battlefield then, so there is no
permanent for a CR 614 replacement to come from — routing them through the seam
would announce a draw event to an empty board, which is not more correct, only
more machinery.
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "engine"

#: ``file:function`` for every place the library operation may still be named.
#: The seam itself, the two replacements that *are* the draw they replace, and
#: the pregame draws — each named with its reason in this module's docstring, so
#: an entry can only be added by someone who wrote one down.
ALLOWED = {
    "mixins/effects.py:_draw_with_replacements",
    "mixins/turn_management.py:deal_opening_hands",
    "mixins/turn_management.py:take_mulligan",
    "mixins/turn_management.py:pregame_mulligan_draw",
}


def _draw_calls(path: Path) -> list[tuple[str, int]]:
    """``(enclosing function, line)`` for each ``<something>.draw(...)`` call."""
    tree = source_tree(path)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "draw"
            ):
                found.append((node.name, inner.lineno))
    return found


def test_only_the_seam_takes_cards_off_the_library():
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        relative = path.relative_to(ENGINE).as_posix()
        for function, line in _draw_calls(path):
            if f"{relative}:{function}" in ALLOWED:
                continue
            offenders.append(f"{relative}:{line} (in {function})")
    assert not offenders, (
        "player.draw called outside Game._draw_with_replacements — a draw taken "
        "this way skips every CR 614 draw replacement:\n  " + "\n  ".join(offenders)
    )


def test_the_allowed_list_names_places_that_exist():
    """A stale exemption is an unguarded call site that looks guarded."""
    present = {
        f"{path.relative_to(ENGINE).as_posix()}:{function}"
        for path in ENGINE.rglob("*.py")
        for function, _ in _draw_calls(path)
    }
    assert ALLOWED <= present, sorted(ALLOWED - present)


# ---------------------------------------------------------------------------
# The two interactions the guard protects
# ---------------------------------------------------------------------------


import pytest  # noqa: E402

from engine import Game  # noqa: E402
from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.models import Permanent, PlayerState  # noqa: E402
from tests.source_index import source_tree


@pytest.fixture(scope="module")
def pool():
    return {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}


def test_a_wheel_is_doubled_by_an_armed_draw_replacement(pool):
    """Wheel of Fortune took its seven cards off the library itself, so a
    Teferi's Ageless Insight beside it did nothing at all — the card reported
    supported, the replacement was armed, and the seven cards arrived anyway.

    The opponent's seven are the control: the doubler is on one battlefield.
    """
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=pool["Teferi's Ageless Insight"])],
        library=[pool["Island"]] * 30,
        hand=[pool["Wheel of Fortune"]],
    )
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Wheel of Fortune")
    game._settle()

    assert len(p1.hand) == 14
    assert len(p2.hand) == 7


def test_an_armed_lamp_takes_the_first_card_of_a_bazaar_draw(pool):
    """The shipped-pool half, and it needs no card from the measured set:
    Aladdin's Lamp arms "the next time you would draw a card this turn", and
    Bazaar of Baghdad's two draws walked straight past it."""
    bazaar = Permanent(card=pool["Bazaar of Baghdad"])
    p1 = PlayerState(
        name="P1",
        battlefield=[bazaar],
        library=[pool["Island"]] * 10,
        hand=[pool["Mountain"]] * 3,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.lamp_draw_replacements[0] = 3

    game.activate_permanent_ability(0, "Bazaar of Baghdad", permanent_index=0)
    game._settle()

    assert game.lamp_draw_replacements == {}, "the charge is spent (CR 614.1)"
    assert any("Aladdin's Lamp" in line for line in game.log)
