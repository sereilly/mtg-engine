"""Every target kind an *activated ability* can report is one the browser's
activation cascade collects.

``test_cast_target_kinds.py`` holds the cast side to this: a kind the server
names and the client has no prompt for is not a missing feature, it is an
announcement sent with no target at all. The activation side had no such
sweep, and two kinds had slipped through it:

* ``spell_or_permanent`` — Blind Seer's "{1}{U}: Target spell or permanent
  becomes the color of your choice until end of turn", the day its spec stopped
  being read as "target permanent". The cast side has prompted for this kind
  since the Lace cycle; no activation branch read it.
* ``planeswalker`` — Sparkhunter Masticore's "{1}: This creature deals 1 damage
  to target planeswalker", shipped with Core Set 2021. Driven in a browser it
  opened a cost prompt, sent a bare activation and got the server's 400, "this
  ability needs a target (CR 602.2b)": the ability could not be activated by a
  human seat at all.

The activation cascade is a run of predicates rather than a switch, so the
kinds it routes are read off the predicates it calls (``app.js`` is DOM-coupled
and cannot be loaded here; the comparisons are the real answer, not a
paraphrase). A **cost** picker is not a target (CR 601.2b vs 601.2c) and is
collected by flag before the cascade runs, so cost specs are left out.

Also here, for the same cascade: the life pills. A roles walk standing on a
player role is answered by a click on a pill, and the gate in front of that
click did not list the kind — six shipped cards (Donate, Lunge, Shower of
Sparks, Soldevi Heretic, Planeswalker's Favor, Planeswalker's Scorn) whose
announcement could be started in the browser and never finished. Found by
driving Shower of Sparks; the text checks below are what is left behind, not
the drive.
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, spec_is_a_cost
from tests.helpers import app_js_function_body

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)

#: Kinds that name no choice, so no prompt collects them.
_NO_PROMPT = frozenset({"none"})


def _function_text(name: str) -> str | None:
    """The body of a top-level function, whether it is written on one line
    (most of the kind predicates are) or over several."""
    one_line = re.search(
        r"^function " + re.escape(name) + r"\([^)]*\)\s*\{(.*)\}\s*$", APP_JS, re.M
    )
    if one_line is not None:
        return one_line.group(1)
    several = re.search(
        r"^function " + re.escape(name) + r"\([^)]*\)\s*\{\n(.*?)^\}$",
        APP_JS, re.S | re.M,
    )
    return None if several is None else several.group(1)


def _routed_activation_kinds() -> frozenset[str]:
    """Every spec kind a predicate called by ``startActivationPrompt`` compares
    against."""
    cascade = app_js_function_body("startActivationPrompt")
    predicates = sorted(set(re.findall(r"\b((?:activatedAbility|card)[A-Z]\w+)\(", cascade)))
    kinds: set[str] = set()
    for name in predicates:
        text = _function_text(name)
        if text is not None:
            kinds.update(re.findall(r'===\s*"([a-z_]+)"', text))
    return frozenset(kinds)


def _activation_spec_kinds() -> dict[str, list[str]]:
    """Every target kind an activated ability in the pool reports, with the
    cards reporting it. Shipped and measured, for ``test_cast_target_kinds``'
    reason: the ingest of the set that first prints a kind is when this should
    fail."""
    found: dict[str, list[str]] = {}
    for path in manifest_set_paths(include_measured=True):
        # `compilation_units`: a split card compiled whole is a supported
        # program with nothing in it, so its halves are what is read.
        for card in compilation_units(load_cards(path)):
            if card.primary_type in ("instant", "sorcery"):
                continue
            for ability in compile_card_oracle(card).activated_abilities:
                spec = derive_activation_spec(ability)
                if spec is None or spec_is_a_cost(spec):
                    continue
                found.setdefault(spec["kind"], []).append(card.name)
    return found


def test_the_scan_reads_kinds_off_both_sides():
    """Both enumerations read source rather than a list, so a rename on either
    side would quietly empty one and the comparison below would pass over
    nothing."""
    routed = _routed_activation_kinds()
    assert {"creature", "permanent", "land", "stack", "roles"} <= routed
    reported = _activation_spec_kinds()
    assert len(reported) > 8 and "creature" in reported


def test_every_activation_spec_kind_has_a_prompt():
    reported = _activation_spec_kinds()
    missing = {
        kind: sorted(set(cards))[:5]
        for kind, cards in reported.items()
        if kind not in _routed_activation_kinds() and kind not in _NO_PROMPT
    }
    assert not missing, (
        "derive_activation_spec reports these kinds for an ability in the pool "
        "and no branch of startActivationPrompt asks for them — the activation "
        f"is sent with no target: {missing}"
    )


def test_the_two_kinds_that_slipped_are_routed_to_the_permanent_prompt():
    routed = _function_text("activatedAbilityRequiresTargetPermanent")
    assert '"spell_or_permanent"' in routed and '"planeswalker"' in routed


def test_a_life_pill_answers_a_roles_walk_standing_on_a_player():
    """The gate in front of ``handlePlayerTargetClick`` lists the roles kind,
    so the branch there that hands the click to the walk is reachable."""
    gate = app_js_function_body("handlePlayerPillClick")
    assert 'pendingCastTarget.targetKind !== "roles"' in gate
    assert gate.index('targetKind !== "roles"') < gate.index("handlePlayerTargetClick(targetSeat)")

    click = app_js_function_body("handlePlayerTargetClick")
    assert "chooseRolePlayer(targetSeat)" in click
