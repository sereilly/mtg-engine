"""A divided spell that prints a bound takes the *divided* picker.

"Fire deals 2 damage divided as you choose among one or two targets." Its spec
is ``kind: divided`` with ``max_targets: 2`` — the bound on the division, in
the key every other picker uses for "up to N". Every cast cascade in the client
asks ``cardRequiresSeveralTargets`` before it asks for a division, and that
predicate read ``max_targets`` alone, so Fire, Arc Lightning, Contagion, Elven
Rite, Flameshot and Bounty of the Hunt were handed the several-*permanents*
picker: a life pill could not be chosen, nothing was divided, and the prompt
said choosing none was legal. Found at the Apocalypse promotion by trying to
aim Fire at a player.

These read the client's text, as ``test_cast_target_kinds.py`` beside them
does; each is a ratchet on a flow that was clicked in a browser (Fire at a face
and a creature, Arc Lightning at three, and the neighbours that must not move:
Fireball, Cone of Flame, Captain's Maneuver, Frost Breath).
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.oracle import compile_card_oracle
from engine import targeting

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(encoding="utf-8")

#: The pool's divided spells that print a bound, as the Phase 5 census found
#: them. A seventh joins by being printed; the picker needs nothing for it.
BOUNDED = {"Arc Lightning": 3, "Bounty of the Hunt": 3, "Contagion": 2, "Elven Rite": 2, "Fire": 2, "Flameshot": 3}


def _function(name: str) -> str:
    match = re.search(rf"\nfunction {name}\(.*?\n\}}\n", APP_JS, re.S)
    assert match, f"{name} is not a top-level function in app.js"
    return match.group(0)


def test_a_divided_spell_is_never_a_several_targets_spell():
    body = _function("cardRequiresSeveralTargets")
    refuses = body.index('specKind(card) === "divided"')
    assert "return false" in body[refuses:refuses + 60]
    # …and it is asked before the count is read, or the count answers first.
    assert refuses < body.index("severalTargetMaximum(card) !== null")


def test_the_divided_picker_stops_at_the_printed_bound():
    assert "dividedPickCeiling(" in _function("dividedPicksAreFull")
    ceiling = _function("dividedPickCeiling")
    assert "divided_target_count" in ceiling and "max_targets" in ceiling


def test_the_bounded_divided_spells_are_the_ones_the_census_found(catalog_by_name):
    from engine import faces

    found = {}
    for card in faces.compilation_units(catalog_by_name.values()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        spec = targeting.derive_cast_spec(card, program)
        if spec and spec.get("kind") == "divided" and isinstance(spec.get("max_targets"), int) and spec["max_targets"] > 1:
            found[card.name] = spec["max_targets"]
    assert found == BOUNDED
