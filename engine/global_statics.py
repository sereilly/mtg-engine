"""Static abilities one permanent applies to objects it does not own.

"Each noncreature artifact loses all abilities and becomes an artifact creature
with power and toughness each equal to its mana value." (Titania's Song.) The
effect belongs to the source, but it changes the *characteristics* of other
permanents, so it has to reach the CR 613 layer system for objects the source
has no relationship with.

``layer_bridge``'s collectors take ``(perm, oid)`` and cannot see the board, so
this follows the model that already works for Auras: the affected permanent
holds a reference to the **source permanent**, and the effects are derived from
that source's text on every recompute. Nothing is materialised onto the
affected object, so a source leaving the battlefield ends its effects by no
longer being in the list — there is no flag to clear and no delta to subtract.

``engine/mixins/permanent_state.py`` rebuilds the lists each refresh; this
module owns *what the text means*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_REMINDER = re.compile(r"\([^)]*\)")


def _line(raw: str) -> str:
    return " ".join(_REMINDER.sub("", raw).strip().lower().split()).rstrip(".")


@dataclass(frozen=True)
class GlobalStatic:
    """What a global static does, and to which permanents.

    ``applies_to`` is a predicate name the refresh pass understands, kept as a
    string so this module stays free of engine imports (the same reason
    ``oracle_types`` does).
    """

    name: str
    applies_to: str
    removes_abilities: bool = False
    adds_creature_type: bool = False
    pt_from_mana_value: bool = False
    # An ability the static *grants*, as the text the granted ability would be
    # printed with. Appending it to the affected permanent's effective card
    # means the compiler produces the ability normally and every consumer — the
    # upkeep step, the UI, the coverage scripts — sees it without knowing this
    # module exists.
    grants_ability: str = ""


_TEMPLATES: tuple[tuple[re.Pattern[str], GlobalStatic], ...] = (
    (
        # Energy Flux. The granted ability is a whole printed sentence, so it is
        # captured and re-emitted rather than described: anything else would be
        # this module deciding what "sacrifice unless you pay" means, which the
        # upkeep tables already know.
        re.compile(r"^all artifacts have \"(?P<ability>.+)\"$"),
        GlobalStatic(name="energy_flux", applies_to="artifact"),
    ),
    (
        re.compile(
            r"^each noncreature artifact loses all abilities and becomes an "
            r"artifact creature with power and toughness each equal to its "
            r"mana value$"
        ),
        GlobalStatic(
            name="titanias_song",
            applies_to="noncreature_artifact",
            removes_abilities=True,
            adds_creature_type=True,
            pt_from_mana_value=True,
        ),
    ),
)


def global_static_for(oracle_text: str) -> GlobalStatic | None:
    """The global static *oracle_text* grants, or None.

    Whole-line matches only. A line that merely *contains* one of these phrases
    is not this ability, and claiming it would apply a board-wide effect on the
    strength of a substring.
    """
    for raw_line in oracle_text.splitlines():
        line = _line(raw_line)
        for pattern, static in _TEMPLATES:
            match = pattern.match(line)
            if match is None:
                continue
            granted = match.groupdict().get("ability")
            if granted:
                return GlobalStatic(
                    name=static.name,
                    applies_to=static.applies_to,
                    removes_abilities=static.removes_abilities,
                    adds_creature_type=static.adds_creature_type,
                    pt_from_mana_value=static.pt_from_mana_value,
                    grants_ability=granted,
                )
            return static
    return None


def global_statics_applying_to(permanent) -> list[GlobalStatic]:
    """Every global static currently applying to *permanent*.

    Read from the source permanents recorded on it, so a source that has left
    the battlefield contributes nothing the moment the refresh drops it.
    """
    found: list[GlobalStatic] = []
    for source in permanent.metadata.get("global_static_sources") or ():
        static = global_static_for(source.card.oracle_text)
        if static is not None:
            found.append(static)
    return found
