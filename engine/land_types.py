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

from .continuous import Characteristics, next_timestamp

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
# once, the first time a refresh sees the static on the battlefield, so the
# derived contribution it rebuilds every refresh keeps a stable place in the
# order.
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
    """*source*'s own timestamp, stamped the first time a refresh sees it.

    CR 613.7a gives a static ability's continuous effect the timestamp of the
    object the ability is on. The engine has no general per-permanent timestamp
    yet, so this stands in for one: stable across refreshes (which is what the
    derived channel needs) and ordered against everything else by when the
    static first reached a refresh — which, with the continuous-effects refresh
    running after every action, is when it arrived. It used to be stamped only
    when the static first *applied* to some land, which let a static that
    entered earlier but found its first subject later slot in after a
    younger one.
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
    ``_refresh_static_land_types`` compares against a land's computed subtypes.

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
    #: "**Basic** lands of the first chosen type are the second chosen type."
    #: (Illusionary Terrain.) A supertype the subjects must *have*, where
    #: ``from_nonbasic`` above is one they must lack — so it is a third field
    #: rather than a value on that one: a card printing "Basic Mountains are
    #: Plains" would set both this and ``from_type``.
    basic_only: bool = False
    #: Both types come from the source's entry choice rather than from the
    #: sentence ("the first chosen type" / "the second chosen type"). The words
    #: name no land type at all, so ``from_type``/``to_type`` are empty until
    #: :func:`resolve_static_land_type_change` fills them in from the permanent.
    from_chosen: bool = False
    #: "**Lands** you control are Plains." (Celestial Dawn.) The subject names
    #: no land type and no supertype — *every* land answers it — so it is a
    #: fourth way of describing the subjects rather than a value on any of the
    #: three above, each of which narrows by a word the sentence prints.
    #: ``land_animation.py`` has had this form since Living Lands; this table
    #: did not, and the difference was invisible while every printing of the
    #: sentence happened to name a type.
    from_any: bool = False
    #: "Lands **you control** are Plains." The subjects are a *seat's*, not the
    #: board's, which is the one narrowing here that no reading of a land's
    #: characteristics can answer — so the refresh supplies the fact and this
    #: module still owns the decision (see
    #: :func:`static_land_type_change_applies`).
    controller_only: bool = False


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

#: "Lands you control are Plains." (Celestial Dawn.) Every land of one seat,
#: named by no type at all. Its own pattern rather than a "lands" entry in the
#: land-type catalog for `_STATIC_NONBASIC_RE`'s reason exactly: the word is
#: absent from that catalog and its absence would be indistinguishable from a
#: typo, so a sentence naming a type nobody printed would silently become this
#: one.
_STATIC_CONTROLLED_RE = re.compile(
    r"^lands you control are (?P<to>[a-z'-]+)$"
)


#: "Basic lands of the first chosen type are the second chosen type."
#: (Illusionary Terrain.) The one entry here with no word to extract: both
#: types are the ordered pair the permanent's controller chose as it entered
#: (CR 614.1c, ``engine/enter_effects.py``), so the sentence is a template with
#: its parameters somewhere else rather than a literal about one card. A second
#: card printing it — with any two types, chosen by anyone — works.
#:
#: Where the permanent's own record lives. A tuple ``(first, second)``, stamped
#: as the permanent enters and read back here, so the static and the choice
#: cannot disagree about which is which.
CHOSEN_LAND_TYPES = "chosen_land_types"

_STATIC_CHOSEN_RE = re.compile(
    r"^basic lands of the first chosen type are the second chosen type$"
)


def resolve_static_land_type_change(
    payload: dict, source: Any
) -> dict | None:
    """*payload* with the chosen types filled in from *source*, or None.

    None when the sentence names its types by a choice the permanent has not
    made — a static that would otherwise reach every land, or none, depending
    on which empty string won. The refresh skips it, which is the honest answer
    for a permanent that has not chosen yet.

    A pass-through for every payload that names its types outright, so the
    refresh asks once and never branches on which kind it has.
    """
    if not payload.get("from_chosen"):
        return payload
    chosen = getattr(source, "metadata", {}).get(CHOSEN_LAND_TYPES) or ()
    if len(chosen) != 2 or not all(chosen):
        return None
    first, second = str(chosen[0]).lower(), str(chosen[1]).lower()
    return {**payload, "from_type": first, "to_type": second}


def static_land_type_change_for(normalized_line: str) -> StaticLandTypeChange | None:
    """The static land-type change *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), with
    or without its trailing period.
    """
    line = normalized_line.strip().lower().rstrip(".")
    if _STATIC_CHOSEN_RE.match(line) is not None:
        return StaticLandTypeChange(
            from_type=None, to_type="", basic_only=True, from_chosen=True
        )
    controlled = _STATIC_CONTROLLED_RE.match(line)
    if controlled is not None:
        to_type = _land_subtype(controlled.group("to"))
        if to_type is None:
            return None
        return StaticLandTypeChange(
            from_type=None, to_type=to_type, from_any=True, controller_only=True
        )
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
    if change.from_nonbasic or change.from_any:
        # No ``from_type`` for either, and for the same reason: neither
        # sentence prints a land type to put there. Emitted only when set, so
        # every payload written before these keys existed is byte-identical.
        pass
    else:
        payload["from_type"] = change.from_type
    if change.from_nonbasic:
        payload["from_nonbasic"] = True
    # Both emitted only when set, so every payload written before these keys
    # existed is byte-identical.
    if change.basic_only:
        payload["basic_only"] = True
    if change.from_chosen:
        payload["from_chosen"] = True
    if change.from_any:
        payload["from_any"] = True
    if change.controller_only:
        payload["controller_only"] = True
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


def static_supertype_removal_applies(payload: dict, types: Characteristics) -> bool:
    """Whether the static removal *payload* describes reaches a permanent that
    currently presents *types*.

    *types* is the CR 613.7 intermediate state
    (``layer_bridge.types_before_timestamp``): what layer 4 has said so far, at
    this static's own place in timestamp order. It used to ask
    ``permanent.has_type`` — layer 4's *finished* answer — while the refresh
    was still deciding layer 4's inputs, which read the previous pass's result
    back in as this pass's premise. The card-type-or-subtype reading is
    ``has_type``'s own, so an animated land is still a land and a permanent an
    earlier type change reached is judged as what that change made it — the one
    reader of the payload's subject half, so the derivation and the refresh
    cannot disagree.
    """
    from_type = str(payload.get("from_type") or "")
    return bool(from_type) and (
        from_type in types.card_types or from_type in types.subtypes
    )


def static_land_type_change_applies(
    payload: dict, types: Characteristics, *, same_controller: bool | None = None
) -> bool:
    """Whether the static change *payload* describes reaches a permanent that
    currently presents *types*.

    The one reader of what the payload's subject half means, so the derivation
    and the refresh cannot disagree about which lands a source reaches. *types*
    is the CR 613.7 intermediate state
    (``layer_bridge.types_before_timestamp``): the seed — layer 3 runs before
    layer 4, so a land Magical Hack has rewritten into a Mountain is one of the
    "All Mountains" Conversion means — plus every layer-4 effect with an
    earlier timestamp, so a Mountain that Blood Moon (an earlier static) made
    is one of them too. This predicate used to read the layer-3 line while the
    removal one beside it asked layer 4's finished ``has_type``: two answers to
    "what is this land?", neither of them CR 613.7's, and two layer-4 statics
    that could not chain.
    """
    # "Lands **you control** are …" (Celestial Dawn). The one narrowing here a
    # land's characteristics cannot answer, so the caller supplies the fact and
    # this predicate still owns the decision — the alternative was a second
    # filter at the refresh site, which is exactly the gate/dispatch split this
    # module's own docstring exists to prevent. ``None`` means the caller did
    # not answer, which for a payload that asks is refusal rather than a pass:
    # a seat-narrowed static reaching every land is the direction that destroys
    # a board.
    if payload.get("controller_only") and same_controller is not True:
        return False
    # "**Basic** lands of …" (Illusionary Terrain). Asked of the computed
    # supertypes — a nonbasic dual is a Plains and is not one of the "basic
    # lands" the sentence names.
    if payload.get("basic_only") and "basic" not in types.supertypes:
        return False
    if payload.get("from_nonbasic"):
        # CR 205.4a: "basic" is a supertype, and a land without it is nonbasic.
        # Asked of the computed supertypes rather than by searching the line
        # for the word, because "Snow Land — Forest" and a card *named*
        # something with "basic" in it both answer that substring wrongly.
        return "basic" not in types.supertypes
    # "**Lands** you control are …" — no type word at all, so every land the
    # narrowings above admitted is one of them. The refresh has already gated
    # on the candidate being a land, which is what makes "every" safe to say
    # here rather than a second type read.
    if payload.get("from_any"):
        return True
    from_type = str(payload.get("from_type") or "")
    return bool(from_type) and from_type in types.subtypes


__all__ = [
    "DERIVED_LAND_TYPES", "LAND_TYPE_EFFECTS", "MIRE_COUNTER",
    "STATIC_LAND_TYPE_KIND", "STATIC_SOURCE_TIMESTAMP", "StaticLandTypeChange",
    "CHOSEN_LAND_TYPES", "add_derived_land_type", "change_land_type",
    "clear_derived_land_types",
    "end_land_type_change", "end_land_type_changes_from", "land_type_changes",
    "static_land_type_change_applies",
    "static_land_type_change_for", "static_land_type_change_payload",
    "static_source_timestamp", "resolve_static_land_type_change",
]
