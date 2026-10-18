"""Four prompts that said the wrong thing, and one button that stalled.

Each was read off the screen while driving the promoted Apocalypse set in a
browser, fixed, and clicked again; these are ratchets on the text of what was
clicked, not a substitute for it.

* Squee's Revenge — "choose a number between 0 and **null**": the open form of
  ``number_choice`` carries ``maximum: None`` and the client printed it.
* Pernicious Deed — an *activated* ``{X}`` was described as "part of this
  spell's additional cost … tapping lands won't raise it", because the question
  was asked of the card's mana cost.
* A painland's "{T}: Add {C}." opened the Blue/Red fan of its other ability.
* One target under a Flagbearer — the single-slot prompt gave no reason for the
  one glowing permanent, and "any target" still invited a life-pill click.
* End Turn, pressed with a creature able to attack, stopped at Declare
  Attackers: nobody has priority while the declaration is owed, and the branch
  that declares no attackers sat behind a priority check.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    match = re.search(rf"\n(?:async )?function {name}\(.*?\n\}}\n", APP_JS, re.S)
    assert match, f"{name} is not a top-level function in app.js"
    return match.group(0)


def test_an_open_number_choice_does_not_print_its_missing_maximum():
    body = _function("applyNumberChoicePrompt")
    assert "Number.isInteger(info.maximum)" in body
    assert "or more" in body


def test_an_abilitys_x_is_read_off_its_activation_cost():
    render = _function("renderActivationPrompt")
    asked = render.index("const xIsPaidInMana")
    assert 'pendingCastX.castAction === "activate"' in render[asked:asked + 200]
    assert "pendingCastX.costString" in render[asked:asked + 260]
    assert "!xIsPaidInMana" in render[asked:asked + 420]


def test_a_chosen_mana_ability_offers_only_the_colours_its_own_line_prints():
    body = _function("abilityManaColors")
    assert "__abilityIndex" in body and "own.length >= 2" in body
    assert "abilityManaColors(card)" in _function("startActivationPrompt")


def test_the_single_target_prompt_shows_a_binding_target_requirement():
    render = _function("renderActivationPrompt")
    owed = render.index("const owed = targetRequirementRowsHtml(pendingCastTarget.card, [])")
    # In the branch every one-click picker falls out through, before Channel's.
    assert owed < render.index("if (pendingChannel)")
    assert "Click a glowing permanent on the battlefield" in render[owed:owed + 500]


def test_end_turn_declares_no_attackers_rather_than_waiting_for_priority():
    body = _function("maybeAutoPassUntilTurnEnd")
    owes = body.index("const owesOwnAttack")
    gate = body.index("state.priority_player !== seat && !owesOwnAttack")
    assert owes < gate < body.index('action: "declare_attackers"')
    # A block is never declared on the player's behalf by this path.
    assert 'autoPassMode === "self"' in body[owes:gate]
