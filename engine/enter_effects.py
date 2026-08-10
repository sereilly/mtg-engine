"""Phrases for the "as/when this permanent enters" entry state (CR 614.1c).

A handful of printed lines describe what a permanent looks like *the moment it
arrives*, or a standing permission its controller gains while it is out: it
enters tapped, it enters with counters, it enters as a copy, its controller
chooses an opponent, has no maximum hand size, may spend white mana as red.
None of them is an effect that goes on the stack, so none of them has an
``OracleInstruction``. They are performed by
:meth:`engine.mixins.permanent_state.PermanentStateMixin._initialize_permanent_state`,
which probes the permanent's own normalized oracle text as it enters.

That probing is the reason this module exists. The phrases used to be string
literals inside the mixin, which meant any other reader of the same behaviour —
the parse-coverage tracker, ``engine/grammar/registries.py`` — had to copy them,
and a copy is free to drift out of sync with the code that actually runs. Here
there is **one** string per behaviour and two readers of it, so a phrase cannot
be renamed on one side only.

:func:`enter_effect_line` answers the second reader's question: does the
*entire* printed line describe entry state the mixin performs? That is
deliberately narrower than the mixin's own substring probes. The mixin asks
"does this card's text mention entering tapped anywhere?"; a line is only
claimed here when the mixin's phrase, plus at most a self-referential subject
and a tail the mixin also implements, is the whole of it. A line that is an
entry effect *plus something else* stays unclaimed — Vesuvan Doppelganger's
copy line carries a granted upkeep ability that this code does not perform, and
claiming it would report as understood a wording nothing implements.
"""

from __future__ import annotations

import re

# --- CR 614.1c entry state, engine/mixins/permanent_state.py ---------------

# "This artifact enters tapped." (Nevinyrral's Disk, Time Vault). The mixin
# probes for this substring and excludes "unless", so a conditional wording
# ("enters tapped unless you pay …") is a different card.
ENTERS_TAPPED = "enters tapped"

# "As this artifact enters, choose an opponent." (Black Vise) and its two-choice
# sibling (Jihad). Separate constants because the mixin branches on them: the
# colour half is what decides whether an interactive caster is prompted.
CHOOSE_OPPONENT_ON_ENTER = "as this artifact enters, choose an opponent"
CHOOSE_COLOR_AND_OPPONENT_ON_ENTER = (
    "as this enchantment enters, choose a color and an opponent"
)

# "This creature enters with seven +1/+0 counters on it." (Clockwork Beast) and
# "… with X +1/+1 counters on it." (Rock Hydra).
ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS = "enters with seven +1/+0 counters on it"
ENTERS_WITH_X_PLUS_1_1_COUNTERS = "enters with x +1/+1 counters on it"

# Copy-on-enter (CR 707.2). Clone's line is exactly the creature phrase; Copy
# Artifact adds a tail the mixin also performs (it appends "Enchantment" to the
# copied type line), which is why the tail is spelled out below rather than
# being an open-ended "and whatever follows".
COPY_CREATURE_ON_ENTER = (
    "you may have this creature enter as a copy of any creature on the battlefield"
)
COPY_ARTIFACT_ON_ENTER = (
    "you may have this enchantment enter as a copy of any artifact on the battlefield"
)

# Standing permissions stamped on the controller as the permanent enters.
NO_MAXIMUM_HAND_SIZE = "you have no maximum hand size"
SPEND_WHITE_AS_RED = "you may spend white mana as though it were red mana"

# "As this enchantment enters, you lose life equal to your life total." (Lich.)
LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER = (
    "as this enchantment enters, you lose life equal to your life total"
)


# A line may name the permanent it is printed on before the phrase the mixin
# probes for ("**This artifact** enters tapped"). The empty string is included
# so a phrase that already starts at the beginning of the line still matches.
_SELF_SUBJECTS: tuple[str, ...] = (
    "",
    "this artifact ",
    "this creature ",
    "this enchantment ",
    "this land ",
    "this permanent ",
)

# (phrase the mixin probes for, trailing clause the mixin also implements).
# A tail is written out in full: it is the one place a claim here could
# otherwise swallow text nothing performs.
_ENTRY_LINES: tuple[tuple[str, str], ...] = (
    (ENTERS_TAPPED, ""),
    (CHOOSE_OPPONENT_ON_ENTER, ""),
    (CHOOSE_COLOR_AND_OPPONENT_ON_ENTER, ""),
    (ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS, ""),
    (ENTERS_WITH_X_PLUS_1_1_COUNTERS, ""),
    (COPY_CREATURE_ON_ENTER, ""),
    # CR 706.10c — the mixin builds the copied type line with "Enchantment"
    # added when the copied artifact is not already one, which is exactly what
    # this tail asks for.
    (COPY_ARTIFACT_ON_ENTER, ", except it's an enchantment in addition to its other types"),
    (NO_MAXIMUM_HAND_SIZE, ""),
    (SPEND_WHITE_AS_RED, ""),
    (LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER, ""),
)


def _normalized(line: str) -> str:
    """The line as ``_initialize_permanent_state`` sees it.

    ``OracleProgram.normalized_text`` is the card's text lowercased with runs of
    whitespace collapsed, so comparing against that reduction is comparing
    against what the mixin really probes. The trailing full stop is dropped
    because the mixin's probes are substrings that never include it.
    """
    return " ".join(line.strip().lower().split()).rstrip(".")


def copy_on_enter_type(normalized_text: str) -> str | None:
    """``"creature"`` / ``"artifact"`` if *normalized_text* offers a copy choice
    as the permanent enters (CR 707.9a), else ``None``.

    The substring probe :meth:`_initialize_permanent_state` runs, asked as a
    question instead of repeated as a literal. Two callers need the answer for
    different reasons — the mixin to *perform* the copy, and
    ``engine/targeting.py`` to raise the picker that chooses what to copy — and
    the pair must never disagree about which cards offer one.

    Deliberately a substring probe rather than :func:`enter_effect_line`, which
    is whole-line and therefore declines Vesuvan Doppelganger (its copy line
    carries a granted upkeep ability the mixin does not perform). The card still
    copies as it enters, so it still needs the picker; asking the narrower
    question here would silently drop its prompt.
    """
    if COPY_CREATURE_ON_ENTER in normalized_text:
        return "creature"
    if COPY_ARTIFACT_ON_ENTER in normalized_text:
        return "artifact"
    return None


def enter_effect_line(line: str) -> str | None:
    """The entry-state phrase *line* consists of in full, or ``None``.

    The return value is the phrase itself, used only to label the AST node —
    nothing dispatches on it, because there is nothing to dispatch: the mixin
    has already applied the effect from the permanent's own text.
    """
    normalized = _normalized(line)
    for phrase, tail in _ENTRY_LINES:
        for subject in _SELF_SUBJECTS:
            if normalized == subject + phrase + tail:
                return phrase
    return None


__all__ = [
    "CHOOSE_COLOR_AND_OPPONENT_ON_ENTER",
    "CHOOSE_OPPONENT_ON_ENTER",
    "COPY_ARTIFACT_ON_ENTER",
    "COPY_CREATURE_ON_ENTER",
    "ENTERS_TAPPED",
    "ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS",
    "ENTERS_WITH_X_PLUS_1_1_COUNTERS",
    "LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER",
    "NO_MAXIMUM_HAND_SIZE",
    "SPEND_WHITE_AS_RED",
    "copy_on_enter_type",
    "enter_effect_line",
]


# "As this creature enters, it becomes your choice of a 3/3 artifact creature,
# a 2/2 artifact creature with flying, or a 1/6 Wall artifact creature with
# defender in addition to its other types." (Primal Clay.)
#
# The bodies are parsed from the text rather than listed, so this is the
# template and not the card: any "your choice of <body>, <body>, or <body>"
# creature reads the same way.
CHOOSE_BODY_ON_ENTER = "it becomes your choice of"

_BODY_RE = re.compile(
    r"a (?P<power>\d+)/(?P<toughness>\d+)(?P<rest>[^,]*?)(?=,|$| or )"
)


def choosable_bodies(oracle_text: str) -> tuple[dict, ...]:
    """The bodies a "your choice of" creature may enter as.

    Each is ``{"power", "toughness", "keyword"}``. The keyword is whatever the
    body grants ("with flying", "with defender"); a body granting none has an
    empty string, which is a body, not a missing one.
    """
    lowered = " ".join(oracle_text.lower().split())
    if CHOOSE_BODY_ON_ENTER not in lowered:
        return ()
    clause = lowered.split(CHOOSE_BODY_ON_ENTER, 1)[1]
    bodies: list[dict] = []
    for match in _BODY_RE.finditer(clause):
        rest = match.group("rest")
        keyword = ""
        with_match = re.search(r"with (\w+)", rest)
        if with_match:
            keyword = with_match.group(1)
        bodies.append({
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
            "keyword": keyword,
        })
    return tuple(bodies)
