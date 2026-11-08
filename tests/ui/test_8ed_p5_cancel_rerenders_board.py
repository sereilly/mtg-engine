"""Cancelling a cast's target choice redraws the board, so the rail comes back.

Found playing 8ED's Phase 5 smoke game as a human seat: Raise Dead's target
prompt opened, was cancelled, and the rail's Next Phase and End Turn stayed
disabled until the game next moved. ``renderBoard`` disables both while a
client-side pending flag is set (``hasBlockingPromptForAutoPass`` reads
``pendingCastTarget`` and its siblings), and a cancel changes nothing on the
server, so no new state arrives to redraw them. The prompt panel's own Next
Phase still worked; the rail did not.

The handler (``cancelPendingPrompt``) is run here in node, its real source
lifted out of ``app.js``, over stubs that record what it reaches for: it
must redraw the board with the current state, *after* every pending flag is
cleared, so the redraw sees none.
"""

from __future__ import annotations

import shutil

import pytest

from tests.helpers import run_app_js

_PRELUDE = r"""
const SFX = { onMenuCancel() {} };
let pendingManaColor = null, pendingCastTarget = null, pendingCastX = null,
    pendingCastDivision = null, pendingAutoTap = null, pendingModalChoice = null,
    pendingDiscardCost = null, pendingPermanentCost = null, pendingCastOffers = null,
    pendingCastCreatureType = null, pendingActivation = null, pendingModeCollection = null,
    pendingActivationCost = null, pendingAbilityChoice = null, pendingChannel = null,
    pendingChosenAbilityWord = null, pendingAttackTarget = null;
const battlefieldCanvas = null;
const CALLS = [];
const currentState = { revision: 52, current_step: "postcombat_main", priority_player: 0 };
function clearPendingHandCast() {}
function closeZoneRevealIfAutoOpened() {}
function clearFfaTargetingHighlights() {}
function renderCombatControls() {}
function renderActivationPrompt() { CALLS.push(["prompt"]); }
function updateActionHint(text) { CALLS.push(["hint", text]); }
function q() { return { classList: { remove() {} } }; }
function renderBoard(state) {
  CALLS.push(["board", state === currentState, pendingCastTarget, pendingAutoTap]);
}
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_cancelling_a_target_choice_redraws_the_board_with_nothing_pending():
    out = run_app_js(
        ["cancelPendingPrompt"],
        r"""
pendingCastTarget = { cardName: "Raise Dead", targetKind: "graveyard_card" };
cancelPendingPrompt();
return CALLS;
""",
        prelude=_PRELUDE,
    )
    boards = [call for call in out if call[0] == "board"]
    assert boards == [["board", True, None, None]], out
    assert ["hint", "Cast canceled. Any mana in your pool is retained."] in out
    # The board is redrawn after the prompt panel, never before the flags clear.
    assert out.index(["prompt"]) < out.index(boards[0])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_cancelling_an_auto_tap_preview_redraws_the_board_too():
    """The other prompt a cast opens before it is sent — the auto-tap
    preview's Cancel is the same button and the same handler."""
    out = run_app_js(
        ["cancelPendingPrompt"],
        r"""
pendingAutoTap = { cardName: "Birds of Paradise" };
cancelPendingPrompt();
return CALLS;
""",
        prelude=_PRELUDE,
    )
    assert [call for call in out if call[0] == "board"] == [["board", True, None, None]], out
