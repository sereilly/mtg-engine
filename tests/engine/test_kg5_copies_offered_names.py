"""Guard: a list the engine or the web offers names a permanent by its name.

CR 707.2 puts the name first among a copy's copiable values: Sculpting Steel
copying Iron Myr *is* named Iron Myr, and the board's name plate says so
(kg5's ``client`` group: the wire's ``name`` is ``effective_card.name``, its
``printed_name`` the card the copy is printed on). Fourteen candidate lists the
engine builds — a cast's targets, a trigger's targets, a mode's targets, an
alternative cost's permanents, the optional untap list, Vesuvan Doppelganger's
and the printed upkeep triggers' targets, the special actions' payers, a
target requirement's binding set — went on offering the copy as "Sculpting
Steel", each spelled ``{"name": perm.card.name}``. A person picked an "Iron
Myr" off the board and a "Sculpting Steel" out of the prompt, which were one
permanent.

So: an entry offering a permanent under ``"name"`` is ``perm.effective_card.name``,
and this guard holds the spelling — every dict literal in ``engine/`` and
``web/`` whose ``"name"`` is ``<x>.card.name`` — to the entries that name a
**card**, not a permanent. A card in a graveyard, in exile or in a hand has
no copy effect on it (CR 400.7: a copy effect does not follow its object out
of the battlefield), and its printed name is its name.

Backwards: on the round's base this listed the fourteen engine sites.
"""

from __future__ import annotations

import ast
import pathlib

from tests.source_index import python_files, source_text, source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: ``(module, receiver)`` pairs whose ``"name": <receiver>.card.name`` names a
#: card in a zone that is not the battlefield, each with why.
CARD_ENTRIES: dict[tuple[str, str], str] = {
    # A trigger's graveyard target (Gravedigger): the stamp is a card in a
    # graveyard, which no copy effect reaches (CR 400.7).
    ("engine/mixins/stack/trigger_targets.py", "stamp"): "a card in a graveyard",
    # Exiled-card records offered back (``_exiled_card_return_choice``): cards
    # in exile.
    ("web/prompt_cards.py", "records[index]"): "a card in exile",
}


def _offered_printed_names(path: pathlib.Path) -> list[tuple[int, str]]:
    """``(line, receiver)`` for every ``{"name": <receiver>.card.name}``."""
    found = []
    for node in ast.walk(source_tree(path)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant) and key.value == "name"
                and isinstance(value, ast.Attribute) and value.attr == "name"
                and isinstance(value.value, ast.Attribute)
                and value.value.attr == "card"
            ):
                found.append((value.lineno, ast.unparse(value.value.value)))
    return found


def _named_entries() -> tuple[int, list[tuple[str, int, str]]]:
    """How many ``"name"`` dict entries were read, and the printed ones."""
    examined = 0
    printed = []
    for path in python_files("engine", "web"):
        if '"name"' not in source_text(path):
            continue
        module = str(path.relative_to(ROOT)).replace("\\", "/")
        for node in ast.walk(source_tree(path)):
            if isinstance(node, ast.Dict):
                examined += sum(
                    isinstance(key, ast.Constant) and key.value == "name"
                    for key in node.keys
                )
        printed += [(module, line, receiver) for line, receiver in _offered_printed_names(path)]
    return examined, printed


def test_an_offered_permanent_is_named_by_its_name():
    examined, printed = _named_entries()
    # The floor: the sweep read the offers it is about (118 "name" entries
    # across engine/ and web/ as this was written).
    assert examined >= 100, f"only {examined} \"name\" entries read — the sweep broke"
    wrong = [
        f"{module}:{line}: \"name\": {receiver}.card.name"
        for module, line, receiver in printed
        if (module, receiver) not in CARD_ENTRIES
    ]
    assert not wrong, (
        "an offered permanent is named by its printed card; a copy's name is the "
        "copied object's (CR 707.2) — use .effective_card.name, or, if the entry "
        "names a card outside the battlefield, add it to CARD_ENTRIES with why:\n"
        + "\n".join(wrong)
    )


def test_the_card_entries_are_not_stale():
    """Each excepted entry is still there — an exception nothing uses is a
    standing allowance to put a permanent's printed name back."""
    _examined, printed = _named_entries()
    present = {(module, receiver) for module, _line, receiver in printed}
    stale = sorted(set(CARD_ENTRIES) - present)
    assert not stale, f"CARD_ENTRIES names entries that are gone: {stale}"
