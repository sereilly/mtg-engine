"""What a printed noun phrase means, tested against one permanent.

``engine/handlers/_common.py``'s ``permanent_matches_filter`` is the pure half of
that question: every key it answers is readable off the permanent alone, so it
needs no game and every filter reader in the engine already shares it. Three
keys are not readable that way — a keyword is a layer-6 question (CR 613.1f),
"you control" is a seat comparison, and "another" is an identity comparison
against the ability's own source (CR 109.5) — so a caller that needs those needs
the game as well.

Until this module there was exactly one such caller: the trigger fire sites,
which tested the three inline next to ``TESTABLE_SUBJECT_FILTER_KEYS``. That
made the key set a claim about *triggers* when it reads as a claim about noun
phrases, and the second caller is what found the difference. **A sacrifice names
its victim with the same noun phrase a trigger names its subject** — "Sacrifice a
creature with defender" (Portcullis Vine), "Target opponent sacrifices a creature
of their choice with flying" (Run Afoul) — and both the activation-cost charger
and the forced-sacrifice prompt tested a filter payload with the pure matcher
alone. A keyword narrowing was therefore untestable, so the grammar refused both
lines rather than drop the rider (``_is_chargeable_sacrifice``,
``_lower_sacrifice``): correct, and correct for a reason that had nothing to do
with sacrifice.

One matcher and one testable-key set is what turns that refusal into an answer.
Everything that reads a noun phrase against a permanent asks :func:`subject_matches`
and refuses exactly what it cannot test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .handlers._common import permanent_matches_filter

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


# The filter-payload keys :func:`subject_matches` implements. A narrowed trigger
# condition, sacrifice cost or sacrifice effect carrying anything outside this
# set is refused where it is *compiled* (engine/oracle.py::_resolve_subject_groups
# for a trigger, engine/grammar for the other two), not silently ignored where it
# is dispatched: a restriction the matcher cannot test would make the effect
# reach a strictly larger set than the card prints, which is the one thing it
# must never do.
#
# Everything down to ``nontoken`` is delegated to ``permanent_matches_filter``;
# the last three need the game and are tested below.
TESTABLE_SUBJECT_FILTER_KEYS = frozenset({
    "type_filter", "subtype_filter", "color_filter",
    "exclude_colors", "exclude_types", "exclude_subtypes",
    "tapped_only", "mana_value", "power", "toughness", "with_plus1_counter",
    "nontoken", "named",
    "with_keywords", "controller", "exclude_self",
})

#: The keys :func:`subject_matches` answers from the object alone. The other two
#: are *relative*: "you control" needs the seat whose ability this is, and
#: "another" needs the ability's source. A caller that already names its own
#: subject set — the forced-sacrifice prompt lists one player's battlefield and
#: takes the excluded permanent as its own argument — has neither to give, so a
#: payload it hands over must stay inside this set or the narrowing would be
#: quietly ignored.
OBJECT_ONLY_FILTER_KEYS = TESTABLE_SUBJECT_FILTER_KEYS - {"controller", "exclude_self"}


def filter_head_noun(payload: dict | None) -> str:
    """The one word a filter payload's head noun is, for a log line and for the
    picker's ``kind``.

    "permanent" whenever the phrase names no single card type — which is the
    honest answer for "a nontoken permanent" and the safe one for a type union,
    because a picker keyed "permanent" offers everything and the filter it
    carries alongside is what narrows the list.
    """
    type_filter = (payload or {}).get("type_filter")
    return type_filter if isinstance(type_filter, str) else "permanent"


def object_only_filter(
    payload: dict, *, carried_separately: frozenset[str] = frozenset()
) -> dict | None:
    """*payload* as a filter :func:`subject_matches` can answer with no observer
    and no source, or ``None`` when it names something outside that.

    *carried_separately* lists keys the caller performs itself and therefore
    removes rather than refuses — a sacrifice prompt takes the excluded permanent
    as its own argument, so ``exclude_self`` is neither tested here nor dropped.
    Naming them at the call site is deliberate: each one is a claim that the
    caller really does carry it out, and an unnamed key is a refusal.
    """
    remaining = {k: v for k, v in payload.items() if k not in carried_separately}
    if set(remaining) - OBJECT_ONLY_FILTER_KEYS:
        return None
    return remaining


def subject_matches(
    game: "Game",
    obj: "Permanent | None",
    described: dict | None,
    *,
    observer: int | None = None,
    source: "Permanent | None" = None,
) -> bool:
    """Whether *obj* is in the set the filter payload *described* names.

    An absent or empty filter is no narrowing at all, so it matches everything —
    "whenever this creature blocks" is the same event as "…blocks a creature"
    minus the restriction, and "sacrifice a permanent" really does admit any
    permanent.

    *observer* is the seat "you control" is relative to (CR 109.5: the controller
    of the permanent whose ability this is, never the controller of the event).
    A payload that asks about a controller with no observer to compare against
    refuses, which is the safe direction: a caller that cannot say whose ability
    this is must not be handed a narrowing it would then ignore.

    *source* is the ability's own source, for "another".
    """
    if not described:
        return True
    if obj is None:
        return False
    if not permanent_matches_filter(obj, described):
        return False
    controller = described.get("controller")
    if controller is not None:
        seat = game.controller_index_of(obj)
        if seat is None or observer is None:
            return False
        if (seat == observer) != (controller == "you"):
            return False
    # Keywords are asked of layer 6, so a creature *granted* defender answers a
    # defender-narrowed filter exactly as a printed one does.
    for keyword in described.get("with_keywords") or ():
        if not game._has_keyword(obj, keyword):
            return False
    # "Another" (CR 109.5) excludes the ability's own source by identity — a
    # look-alike on the same battlefield is a different permanent.
    if described.get("exclude_self") and source is not None and obj is source:
        return False
    return True


__all__ = [
    "OBJECT_ONLY_FILTER_KEYS",
    "TESTABLE_SUBJECT_FILTER_KEYS",
    "filter_head_noun",
    "object_only_filter",
    "subject_matches",
]
