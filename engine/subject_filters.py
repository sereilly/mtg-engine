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
    "type_filter", "subtype_filter", "subtype_filter_all", "color_filter",
    "exclude_colors", "exclude_types", "exclude_subtypes",
    "tapped_only", "untapped_only",
    "mana_value", "power", "toughness", "with_plus1_counter",
    "nontoken", "named", "supertypes",
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

#: The keys ``_card_matches_filter`` answers about a **card** — an object in a
#: hand, a graveyard or a library. A far smaller set than the two above, and
#: smaller for a reason rather than for want of code: CR 613.1 applies the layer
#: system to permanents, so a card in a zone has no computed characteristics at
#: all. It is not tapped, it has no controller, its colour and P/T are whatever
#: is printed and nothing can have changed them. What is printed on the face is
#: the whole of what is testable.
#:
#: "Discard a land card or Shrine card" (Sanctum of Shattered Heights) is read
#: through this set, and a phrase reaching outside it refuses the cost rather
#: than charging the wider one — the same rule ``object_only_filter`` states for
#: a sacrifice, in the same direction.
#: ``supertypes`` is here and not in the paragraph above's list of things a
#: card cannot answer, because it is the one restriction beyond type and name
#: that a card *can*: it is printed on the face, in the same words, and nothing
#: could have changed it.
CARD_ONLY_FILTER_KEYS = frozenset(
    {"type_filter", "subtype_filter", "named", "supertypes", "mana_value"}
)


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


def card_only_filter(payload: dict) -> dict | None:
    """*payload* as a filter ``_card_matches_filter`` can answer about a card in
    a zone, or ``None`` when it names something outside that.

    The card twin of :func:`object_only_filter`, and separate from it because
    the two answer about different kinds of object: a permanent's colour and
    tapped state are live questions, a card's are not questions at all.
    """
    if set(payload) - CARD_ONLY_FILTER_KEYS:
        return None
    return dict(payload)


def card_matches_any(card, alternatives) -> bool:
    """Whether *card* answers any one of the printed alternatives.

    "Discard a land card **or** Shrine card" is a union across two different
    characteristics, and a single filter cannot say it: an ObjectFilter's keys
    are AND'd, so "land" and "shrine" folded together would name a card that is
    both. The disjunction therefore lives in the *shape* of what is carried — a
    tuple of filters — and this is where it is read.

    No alternatives is no narrowing, which is the honest reading of "Discard a
    card": every card in hand pays it.
    """
    from .handlers._common import _card_matches_filter

    if not alternatives:
        return True
    return any(_card_matches_filter(card, dict(alt)) for alt in alternatives)


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
        # "**That player** controls" is not a seat this can compare against.
        # It names a player the *event* picked — the one who was dealt damage,
        # the one whose creature died — and the only place that seat is known is
        # the resolution holding the trigger's context. Answered here it would
        # reduce to "not you", which is "any opponent": right in a two-player
        # game by coincidence and wrong the moment there are three.
        #
        # So it refuses, and the handler that has the context resolves it —
        # the same split "another" and ``attached_to`` already make.
        if controller == "that_player":
            return False
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
    "CARD_ONLY_FILTER_KEYS",
    "OBJECT_ONLY_FILTER_KEYS",
    "TESTABLE_SUBJECT_FILTER_KEYS",
    "card_matches_any",
    "card_only_filter",
    "filter_head_noun",
    "object_only_filter",
    "subject_matches",
]
