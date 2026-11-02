"""Which source-keyed "next time" sentences can meet a sweep — named, because
whether a sweep's simultaneous chunks are one "next instance of damage from
that source" (CR 615.8) is still open.

The rules reading (kg3 `events`, with the sources): CR 615.8 says such an
effect prevents "the next instance of damage from that source, regardless of
how much damage that is", and never defines an instance. Every ruling found
on a "next time" card speaks to the **recipient-keyed** template — Mirrorwood
Treefolk and Glarecaster (2004-10-04): "the next time damage is dealt" covers
every chunk dealt at that time — or to a **numeric** source-keyed one: Harm's
Way (2009-10-01) redirects "just 2" of a Pyroclasm's or an Earthquake's
simultaneous damage, "not the next 2 damage that would be dealt to each
recipient". None of the source-keyed cards below has a ruling on the
question, and none was found for any card printing the template (fifty-six
"the next time … would deal damage" cards' rulings were read). Shadowbane's
own "you **and/or** creatures you control" is the strongest hint — the "and/or"
only means something if one time can reach both — but it is a reading, not a
ruling. So the engine is left as it is: each of these spends itself on the
first chunk.

This census names the cards that can meet the question — a source-keyed
"next time" whose recipient is not one object — so the playbook entry stays
true: a card leaving the pool fails here, and a new one is listed beside them.
"""

from __future__ import annotations

import re

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units

#: "The next time <a source> would deal [combat] damage <rest>", read off the
#: printed line with reminder text removed. The recipient-keyed template
#: ("the next time damage would be dealt to …") never matches: it has no
#: source before "would deal".
_SOURCE_KEYED = re.compile(
    r"\bthe next time (?!damage\b)(?P<source>[^.,]*?) would deal (?:combat )?damage"
    r"(?P<rest>[^.]*)",
    re.IGNORECASE,
)
#: A recipient that is one object or one player: no sweep can hand it two
#: chunks from one source.
_ONE_RECIPIENT = re.compile(
    r"^ to (?:you|target (?:creature|player)|this creature|that creature)\b(?! and/or)",
    re.IGNORECASE,
)

#: The cards the Known-gaps entry names, each still in the pool and still
#: reaching more than one recipient.
_NAMED = {
    "Penance", "Pilgrim of Justice", "Pilgrim of Virtue", "Shadowbane",
    "Reflect Damage", "Desperate Gambit", "Impulsive Maneuvers",
}


def _open_question():
    found: dict[str, str] = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        for line in (card.oracle_text or "").split("\n"):
            printed = re.sub(r"\([^)]*\)", "", line)
            for match in _SOURCE_KEYED.finditer(printed):
                if not _ONE_RECIPIENT.match(match.group("rest")):
                    found.setdefault(card.name, printed.strip())
    return found


def test_the_cards_a_sweep_can_meet_are_named():
    found = _open_question()
    missing = sorted(_NAMED - set(found))
    assert missing == [], (
        "a card the playbook's open 'next instance' entry names no longer "
        f"prints a source-keyed next time reaching several recipients: {missing}"
    )
    assert len(found) >= len(_NAMED), found
