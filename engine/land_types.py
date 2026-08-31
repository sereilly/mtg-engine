"""Single write API for basic-land-type changes (CR 613 layer 4, CR 305.7).

"Enchanted land is a Swamp" (Evil Presence), "that land is a Swamp for as long
as it has a mire counter on it" (Cyclopean Tomb), "target land becomes a Forest
until this creature leaves the battlefield" (Gaea's Liege), "All Mountains are
Plains" (Conversion). Each *sets* a land's subtype, and CR 305.7 makes that a
replacement: the land no longer has its old land types.

The engine used to record all of them by stamping one string on the land, so
every effect had to remember to un-stamp exactly what it stamped — and could
only ever un-stamp everything. Two of those effects on one land meant the second
silently overwrote the first, and whichever ended first took the other with it.

This module records each one as a **contribution**: what it makes the land, who
made it, and when (CR 613.7). ``layer_bridge.collect_type_effects`` turns each
contribution into its own layer-4 effect, so the layer engine — not the order
the writes happened to run in — decides which applies last. Removal is dropping
one contribution, which is why nothing here has a delta to get wrong: an
effect ending restores whatever the *other* contributions still say, not the
printed type line.

Two channels, for the same reason ``engine/keywords.py`` has two: a recorded
effect is stamped once and lives until its source ends it, while a *derived*
one (Conversion's static ability) is recomputed from the board on every
continuous-effects refresh and would otherwise accumulate one entry per pass,
forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

# Key under which a land's ordered, recorded type changes live.
LAND_TYPE_EFFECTS = "land_type_effects"

# Key under which the *derived* ones live — a static ability's, rebuilt from the
# board each recompute. Split from the recorded channel so the rebuild cannot
# turn into an accumulation.
DERIVED_LAND_TYPES = "derived_land_type_changes"

# Key under which a static source's own timestamp lives (CR 613.7a: a static
# ability's continuous effect has the timestamp of the object it is on). Stamped
# once, the first time the static applies, so the derived contribution it
# rebuilds every refresh keeps a stable place in the order.
STATIC_SOURCE_TIMESTAMP = "static_land_type_timestamp"

# The source label for Cyclopean Tomb's mire counter. The counter, not the
# artifact, is what the type change hangs on ("for as long as it has a mire
# counter on it"), so the Tomb leaving the battlefield does not end it.
MIRE_COUNTER = "mire counter"


def _same_source(recorded: Any, wanted: Any) -> bool:
    """Identity for live objects, equality for the string labels.

    ``Permanent`` is a plain dataclass, so ``==`` would deep-compare two
    permanents — including metadata holding references back to permanents.
    Sources are compared by identity for that reason; a label is a str and has
    no identity worth preserving across a copy.
    """
    if isinstance(wanted, str) or isinstance(recorded, str):
        return isinstance(recorded, str) and isinstance(wanted, str) and recorded == wanted
    return recorded is wanted


def change_land_type(
    perm: Permanent, land_type: str, *, source: Any, label: str = ""
) -> None:
    """Layer 4: *perm*'s land subtype becomes *land_type* from now (CR 613.7b).

    *source* is whatever ends the effect — the Aura, the activating creature, or
    a label such as :data:`MIRE_COUNTER` for a change that outlives its card.
    Passing the same source twice replaces its earlier contribution rather than
    stacking a second one, because one effect applies once however often it is
    re-resolved.
    """
    lowered = str(land_type).strip().lower()
    if not lowered:
        return
    effects = [
        entry
        for entry in (perm.metadata.get(LAND_TYPE_EFFECTS) or [])
        if not _same_source(entry.get("source"), source)
    ]
    effects.append(
        {
            "land_type": lowered,
            "source": source,
            "timestamp": next_timestamp(),
            "label": label,
        }
    )
    perm.metadata[LAND_TYPE_EFFECTS] = effects


def end_land_type_change(perm: Permanent, *, source: Any) -> bool:
    """Drop *source*'s contribution (CR 611.3: the duration ended).

    Returns whether anything was dropped, so a caller that logs the reversion
    still knows it happened. What the land is afterwards is whatever the
    remaining contributions say — this does not restore the printed type, and
    that is the point: an Evil Presence Swamp survives Gaea's Liege's Forest
    ending.
    """
    effects = perm.metadata.get(LAND_TYPE_EFFECTS)
    if not effects:
        return False
    remaining = [
        entry for entry in effects if not _same_source(entry.get("source"), source)
    ]
    if len(remaining) == len(effects):
        return False
    if remaining:
        perm.metadata[LAND_TYPE_EFFECTS] = remaining
    else:
        perm.metadata.pop(LAND_TYPE_EFFECTS, None)
    return True


def end_land_type_changes_from(perm: Permanent, *, prefix: str) -> int:
    """Drop every recorded contribution whose *label source* starts with
    *prefix*, and report how many went.

    The sweep half of a **windowed** land-type change. "Target land becomes a
    Swamp until its controller's next untap step" (Orcish Farmer) outlives the
    permanent that made it, so its contribution is keyed on a per-activation
    label rather than on a source object — and the untap step has to be able to
    find those labels without reading the channel itself, which is what
    ``tests/engine/test_layer_reads.py`` reserves to this module and the layer
    bridge. Here rather than there for that reason: the sweep is a question
    about the store, and the store has one reader.
    """
    dropped = 0
    for entry in list(perm.metadata.get(LAND_TYPE_EFFECTS) or ()):
        source = entry.get("source")
        if isinstance(source, str) and source.startswith(prefix):
            dropped += int(end_land_type_change(perm, source=source))
    return dropped


def clear_derived_land_types(perm: Permanent) -> None:
    """Drop the contributions derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them; splitting the clear from the
    rebuild is how a derived channel turns into an accumulating one.
    """
    perm.metadata.pop(DERIVED_LAND_TYPES, None)


def add_derived_land_type(
    perm: Permanent, land_type: str, *, timestamp: int, label: str = ""
) -> None:
    """Layer 4: *perm* is *land_type* for as long as a static keeps saying so."""
    derived = perm.metadata.setdefault(DERIVED_LAND_TYPES, [])
    derived.append(
        {
            "land_type": str(land_type).strip().lower(),
            "source": label,
            "timestamp": int(timestamp),
            "label": label,
        }
    )


def static_source_timestamp(source: Permanent) -> int:
    """*source*'s own timestamp, stamped the first time its static applies.

    CR 613.7a gives a static ability's continuous effect the timestamp of the
    object the ability is on. The engine has no general per-permanent timestamp
    yet, so this stands in for one: stable across refreshes (which is what the
    derived channel needs) and ordered against everything else by when the
    static first mattered.
    """
    stamp = source.metadata.get(STATIC_SOURCE_TIMESTAMP)
    if stamp is None:
        stamp = next_timestamp()
        source.metadata[STATIC_SOURCE_TIMESTAMP] = stamp
    return int(stamp)


def land_type_changes(perm: Permanent) -> tuple[dict, ...]:
    """Every layer-4 land-type contribution on *perm*, in **storage** order.

    Deliberately not sorted here. Each contribution becomes its own
    :class:`ContinuousEffect` carrying its own timestamp, and CR 613.7 is what
    orders them — sorting first would make the timestamps decorative, since the
    two channels' storage order would then be doing the work and a
    contribution stamped wrongly would still come out right. The recorded and
    derived channels are concatenated precisely so that storage order and
    timestamp order need not agree.

    Read by ``layer_bridge`` and nothing else: "what type is this?" has one
    answer, ``Permanent.has_type`` / ``Permanent.basic_land_types``, and a
    second reader of this list would be a second opinion about CR 305.7.
    """
    return (
        *(perm.metadata.get(LAND_TYPE_EFFECTS) or ()),
        *(perm.metadata.get(DERIVED_LAND_TYPES) or ()),
    )


def lost_abilities_to_type_change(perm: Permanent) -> bool:
    """Whether CR 305.7 has taken *perm*'s printed abilities away.

    "If an effect **sets** a land's subtype to one or more of the basic land
    types … it loses all abilities generated from its rules text, its old land
    types, and any copiable effects affecting that land, and it gains the
    appropriate mana ability for each new basic land type."

    The engine implemented only the gaining half for ten sets: with Blood Moon
    out, Mishra's Factory read as a Mountain and produced {R} — and still
    animated itself and pumped, and City of Brass still had its damage trigger.
    Every basic-land-type change in this engine is a *set* (that is what
    :func:`change_land_type` records and what the "All X are Y" statics derive),
    so the presence of a contribution is the rule's own condition.

    Deliberately **not** answered from the layer-4 result. "Is this land a
    Mountain?" is true of a printed Mountain too, and a printed Mountain has
    lost nothing; the question here is whether an *effect* set the type, which
    only the contributions can say. The last sentence of 305.7 — a land that
    gains a type *in addition* keeps its rules text — is the same distinction,
    and those are recorded on the separate ``GAINED_TYPES`` channel that this
    deliberately does not read.

    Three readers, because an ability can act in three ways: layer 6 drops the
    keywords, the activation gate refuses the activated ones, and the trigger
    scan skips the triggered ones. One predicate for all three, so a land
    cannot lose half its abilities.
    """
    return bool(land_type_changes(perm))


# ---------------------------------------------------------------------------
# The static reading: "All <type>s are <type>s." (Conversion, Blood Moon)
# ---------------------------------------------------------------------------
#
# A derivation table for the same reason engine/land_animation.py is one. The
# rule this replaces spelled the five basics into a regex of its own and matched
# with `.search` over the card's whole collapsed text, so "All Deserts are
# Islands" was unsupported while `_recalculate_derived_land_types` — which reads
# only the payload — had every line of code it needed, and a sentence saying
# more than this could match on a fragment.
#
# The support gate and the grammar both delegate here, so what is claimed and
# what is applied are one function.

# The instruction kind a derived static land-type change compiles to.
STATIC_LAND_TYPE_KIND = "static_land_type_change"


@dataclass(frozen=True)
class StaticLandTypeChange:
    """Lands of one type are another type while the source is on the battlefield.

    Both types are singular and lowercase, which is the form
    ``_refresh_static_land_types`` compares against a land's type line.

    ``from_type`` is None exactly when ``from_nonbasic`` is set: "**Nonbasic**
    lands are Mountains" (Blood Moon) describes its subjects by a supertype
    they lack rather than by a land type they have, so there is no word to put
    there. The two are one field-pair rather than two tables because what
    changes between Conversion and Blood Moon is *which lands*, and the change
    itself — CR 305.7's replacement of every land type — is the same effect.
    """

    from_type: str | None
    to_type: str
    from_nonbasic: bool = False


@lru_cache(maxsize=1)
def _land_types() -> frozenset[str]:
    # Imported lazily: the grammar package imports engine-level derivation
    # modules, so a module-level import here would close a cycle.
    from .grammar import vocabulary

    return vocabulary.LAND_TYPES


def _land_subtype(word: str) -> str | None:
    """The land type *word* names, however it was pluralised.

    The catalog stores singulars and "Plains" is its own plural, so each
    candidate stem is tried *against the catalog* instead of a shape being
    assumed — the same reason ``land_animation._land_subtype`` works this way.
    """
    land_types = _land_types()
    for candidate in (word, word[:-1]):
        if candidate and candidate in land_types:
            return candidate
    return None


# Anchored at both ends. "All Mountains are 1/1 red creatures that are still
# lands" is a *different* template (engine/land_animation.py) and must not be
# read as a type change with its animation clause dropped, so the pattern
# admits nothing after the second noun.
_STATIC_TYPE_RE = re.compile(r"^all (?P<from>[a-z'-]+) are (?P<to>[a-z'-]+)$")

#: "Nonbasic lands are Mountains." (Blood Moon.) The same replacement over a
#: set named by a *missing supertype*, which no land-subtype word can express —
#: so it is its own pattern and its own flag, rather than "nonbasic" being
#: looked up in the land-type catalog, where it is absent and its absence would
#: be indistinguishable from a typo.
_STATIC_NONBASIC_RE = re.compile(r"^nonbasic lands are (?P<to>[a-z'-]+)$")


def static_land_type_change_for(normalized_line: str) -> StaticLandTypeChange | None:
    """The static land-type change *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), with
    or without its trailing period.
    """
    line = normalized_line.strip().lower().rstrip(".")
    nonbasic = _STATIC_NONBASIC_RE.match(line)
    if nonbasic is not None:
        to_type = _land_subtype(nonbasic.group("to"))
        if to_type is None:
            return None
        return StaticLandTypeChange(
            from_type=None, to_type=to_type, from_nonbasic=True
        )
    match = _STATIC_TYPE_RE.match(line)
    if match is None:
        return None
    from_type = _land_subtype(match.group("from"))
    to_type = _land_subtype(match.group("to"))
    if from_type is None or to_type is None:
        return None
    return StaticLandTypeChange(from_type=from_type, to_type=to_type)


def static_land_type_change_payload(change: StaticLandTypeChange) -> dict[str, object]:
    """*change* as an ``OracleInstruction`` payload.

    ``from_nonbasic`` is emitted only when set, so every payload written before
    this key existed is byte-identical.
    """
    payload: dict[str, object] = {"to_type": change.to_type}
    if change.from_nonbasic:
        payload["from_nonbasic"] = True
    else:
        payload["from_type"] = change.from_type
    return payload


# ---------------------------------------------------------------------------
# The other static: "All lands are no longer snow." (Melting)
# ---------------------------------------------------------------------------
#
# A sibling of the table above rather than a field on it: CR 305.7's replacement
# of a land's *subtypes* and CR 205.4a's removal of a **supertype** are different
# effects that happen to share a layer, and folding the second into
# ``StaticLandTypeChange`` would give every Conversion a supertype field it must
# not set.
#
# It is a derivation table, and not a production in ``engine/grammar/``, for the
# reason "All Mountains are Plains" is one: a board-wide static is a continuous
# effect recomputed from the board, and the grammar's one-shot lowering for the
# targeted spelling (Arcum's Weathervane) would fire it once and never again.

STATIC_SUPERTYPE_REMOVAL_KIND = "static_supertype_removal"


@dataclass(frozen=True)
class StaticSupertypeRemoval:
    """Permanents of one card type lose a supertype while the source is out.

    ``from_type`` is the printed noun the sentence names ("lands"), singular and
    lowercase — a *card* type rather than a land subtype, because the sentence
    reaches every land whatever its subtypes.
    """

    from_type: str
    supertype: str


# Anchored at both ends, so a sentence saying more than this is not read as this
# one with its rider dropped.
_STATIC_NO_LONGER_RE = re.compile(
    r"^all (?P<from>[a-z'-]+) are no longer (?P<supertype>[a-z]+)$"
)


def static_supertype_removal_for(normalized_line: str) -> StaticSupertypeRemoval | None:
    """The static supertype removal *normalized_line* imposes, or None.

    Both words are validated: the noun against the engine's card types and the
    supertype against ``data/vocabulary``. A word neither catalog has heard of
    would produce a static that reaches nothing, and a static reaching nothing
    is indistinguishable from one nobody implemented — so the line refuses and
    its card is reported unsupported instead.
    """
    from .grammar.vocabulary import CARD_TYPES, TYPE_LINE_SUPERTYPES

    match = _STATIC_NO_LONGER_RE.match(
        normalized_line.strip().lower().rstrip(".")
    )
    if match is None:
        return None
    word = match.group("from")
    singular = word[:-1] if word.endswith("s") else word
    if singular not in CARD_TYPES:
        return None
    supertype = match.group("supertype")
    if supertype not in TYPE_LINE_SUPERTYPES:
        return None
    return StaticSupertypeRemoval(from_type=singular, supertype=supertype)


def static_supertype_removal_payload(
    removal: StaticSupertypeRemoval,
) -> dict[str, object]:
    """*removal* as an ``OracleInstruction`` payload."""
    return {"from_type": removal.from_type, "supertype": removal.supertype}


def static_supertype_removal_applies(payload: dict, permanent) -> bool:
    """Whether the static removal *payload* describes reaches *permanent*.

    Through ``has_type``, so an animated land is still a land and a permanent
    a type change made one is reached — the one reader of the payload's subject
    half, so the derivation and the refresh cannot disagree.
    """
    from_type = str(payload.get("from_type") or "")
    return bool(from_type) and permanent.has_type(from_type)


def static_land_type_change_applies(payload: dict, permanent) -> bool:
    """Whether the static change *payload* describes reaches *permanent*.

    The one reader of what the payload's subject half means, so the derivation
    and the refresh cannot disagree about which lands a source reaches. The
    type line it asks is the **effective** one: layer 3 runs before layer 4, so
    a land Magical Hack has rewritten into a Mountain is one of the "All
    Mountains" Conversion means, and a supertype a text change removed really
    is gone.
    """
    type_line = permanent.effective_card.type_line
    if payload.get("from_nonbasic"):
        # CR 205.4a: "basic" is a supertype, and a land without it is nonbasic.
        # Asked of ``has_supertype`` rather than by searching the line for the
        # word, because "Snow Land — Forest" and a card *named* something with
        # "basic" in it both answer that substring wrongly — and because layer 4
        # computes the word, so a Blood Moon reads whatever the board says now.
        return not permanent.has_supertype("basic")
    from_type = payload.get("from_type") or ""
    return bool(from_type) and from_type in type_line.lower()


__all__ = [
    "DERIVED_LAND_TYPES", "LAND_TYPE_EFFECTS", "MIRE_COUNTER",
    "STATIC_LAND_TYPE_KIND", "STATIC_SOURCE_TIMESTAMP", "StaticLandTypeChange",
    "add_derived_land_type", "change_land_type", "clear_derived_land_types",
    "end_land_type_change", "end_land_type_changes_from", "land_type_changes",
    "static_land_type_change_applies",
    "static_land_type_change_for", "static_land_type_change_payload",
    "static_source_timestamp",
]
