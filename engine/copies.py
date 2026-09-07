"""CR 613 layer 1 — copy effects, as copiable values rather than overrides.

CR 613.2a puts copy effects in layer 1a, and CR 613.2c says what layer 1 is
*for*: once it has been applied, the object's characteristics **are** its
copiable values. Every other layer starts from that result. So layer 1 is not
an effect applied over a seed — it is the thing that produces the seed, which
is why this module answers with a :class:`~engine.models.CardDefinition` and
not with a :class:`~engine.continuous.ContinuousEffect`.

CR 707.2 draws the boundary this module exists to hold::

    The copiable values are the values derived from the text printed on the
    object … as modified by other copy effects, by its face-down status, and by
    "as … enters" … abilities that set power and toughness. **Other effects
    (including type-changing and text-changing effects), status, counters, and
    stickers are not copied.**

The engine used to model a copy by *stamping the results*: ``copied_card`` for
the types and abilities, ``copied_colors`` for the colours, ``copied_keywords``
for the keywords, and ``absolute_power``/``absolute_toughness`` — the shared
layer-7b channel — for the P/T. Stamping cannot hold that boundary, because a
stamp records an answer and the boundary is a question about where the answer
came from:

* ``absolute_power`` is 7b's channel, so a copy read whatever a *non-copy*
  effect had set on the source. A creature whose P/T had been set to 0/5 was
  copied as a 0/5.
* ``copied_card`` was the source permanent's own ``card``, which is not its
  copiable values when the source is itself a copy. A Clone copying a Clone
  came out a 0/0 blue Shapeshifter named Clone instead of the Craw Wurm the
  first one was.
* Copy Artifact read the source's ``effective_card``, which layer 3 has already
  rewritten — so a text change on the source was copied, which CR 707.2's last
  sentence forbids.
* And an exception expressed by *not writing a stamp* is indistinguishable from
  a stamp nobody happened to write. ``copied_colors`` was only recorded when the
  copied artifact had colours, so a copy of a colourless Sol Ring kept Copy
  Artifact's own blue.

A copy is a recorded contribution now, like a control change or a land-type
change: the copied object's copiable values, the set of characteristics this
effect *takes*, the CR 707.9 modifications it declares, a source and a CR 613.7
timestamp. :func:`copiable_card` folds them oldest-first.

**Exceptions are named positively.** ``copies`` lists the characteristics the
effect hands over, so Vesuvan Doppelganger's "except it doesn't copy that
creature's color" is ``copies=EXCEPT_COLOR`` — an effect that takes name, mana
cost, types, text and P/T — and CR 707.9c's "the affected object instead
retains its original value" is then a *rule of the fold*, not an absent write.
That is what makes the printed blue survive for a reason a test can read.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Iterable, Mapping

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CardDefinition, Permanent

# Key under which a permanent's layer-1 contributions live.
COPY_EFFECTS = "copy_effects"

#: Key under which a permanent's **derived** layer-1 contributions live — a copy
#: whose source is not a moment but a standing question about the game state
#: ("as long as the top card of your graveyard is a creature card…",
#: ``engine/zone_copies.py``).
#:
#: Its own channel beside :data:`COPY_EFFECTS` rather than an entry in it,
#: because the two are written by different things and cleared by different
#: things: a recorded contribution is written once by the effect that made the
#: copy and lasts until something ends it, while a derived one is rebuilt from
#: the board by ``_refresh_dynamic_creatures`` on every recompute and carries no
#: copied card at all — only *where to look*. Folding them into one list would
#: make a rebuild able to drop a Clone's contribution, which is the accident the
#: derived land-type channel is kept separate to avoid one file over.
DERIVED_COPY_SOURCES = "derived_copy_sources"

# CR 707.2's copiable values, grouped as the card object stores them. A copy
# effect names the ones it takes; whatever it does not name is retained from
# the object being copied *onto* (CR 707.9c).
NAME = "name"
MANA_COST = "mana_cost"
TYPES = "types"
TEXT = "text"
POWER_TOUGHNESS = "power_toughness"
COLOR = "color"

ALL_VALUES = frozenset({NAME, MANA_COST, TYPES, TEXT, POWER_TOUGHNESS, COLOR})
# CR 707.9c: Vesuvan Doppelganger takes everything a copy effect can take
# *except* colour, so the copier keeps the colour derived from its own mana
# cost (CR 707.2a). Spelled as its own name because that is the exception, and
# an exception the engine can only express by omitting something is one no test
# can tell from an oversight.
EXCEPT_COLOR = ALL_VALUES - {COLOR}

# CR 707.9a: an ability the copy effect grants as part of the copying process.
# Vesuvan Doppelganger's re-copy trigger is the pool's only one.
RECOPY_EACH_UPKEEP = "recopy_each_upkeep"

# The card fields each copiable value owns. Colour is its own group because
# CR 707.9c lets an effect decline it while copying the mana cost it is
# normally derived from (CR 707.2a).
_FIELDS: dict[str, tuple[str, ...]] = {
    NAME: ("name",),
    MANA_COST: ("mana_cost", "cmc"),
    TYPES: ("type_line",),
    TEXT: ("oracle_text", "keywords", "produced_mana"),
    POWER_TOUGHNESS: ("power", "toughness"),
    COLOR: ("colors", "color_identity"),
}


# ---------------------------------------------------------------------------
# CR 707.9 — what a copy effect's own text says it does differently
# ---------------------------------------------------------------------------

# "except it doesn't copy that creature's color" (Vesuvan Doppelganger).
_NOT_COPIED_COLOR = re.compile(r"doesn't copy that [a-z]+'s color")
# "except it's an enchantment in addition to its other types" (Copy Artifact).
# The whole phrase between the article and "in addition", so a printing that
# adds two words ("a legendary artifact") adds both rather than silently
# dropping one — a partial match here would be a type the copy never gets.
_ADDED_TYPE = re.compile(r"it's an? ([a-z]+(?: [a-z]+)*) in addition to its other types")
# The granted ability inside Vesuvan Doppelganger's "and it has \"…\"" clause.
_GRANTS_RECOPY = "become a copy of target creature"


def copy_exceptions(copier_text: str) -> dict:
    """The CR 707.9 modifications *copier_text* declares, as :func:`become_copy`
    keyword arguments.

    Text-keyed, not name-keyed: "except it doesn't copy that creature's color"
    and "except it's an <type> in addition to its other types" are templates
    Magic reprints, so a later card printed with either needs no entry here. The
    default — no exception clause at all — is Clone: every copiable value, no
    modification.
    """
    text = " ".join((copier_text or "").lower().split())
    copies = EXCEPT_COLOR if _NOT_COPIED_COLOR.search(text) else ALL_VALUES
    added = _ADDED_TYPE.search(text)
    grants = (RECOPY_EACH_UPKEEP,) if _GRANTS_RECOPY in text else ()
    return {
        "copies": copies,
        "adds_types": tuple(word.capitalize() for word in added.group(1).split()) if added else (),
        "grants": grants,
    }


# ---------------------------------------------------------------------------
# The write API
# ---------------------------------------------------------------------------


def become_copy(
    permanent: "Permanent",
    source: "Permanent",
    *,
    copies: Iterable[str] = ALL_VALUES,
    adds_types: Iterable[str] = (),
    grants: Iterable[str] = (),
    grants_text: Iterable[str] = (),
    effect_source: "Permanent | None" = None,
    label: str = "",
) -> None:
    """Record that *permanent* is a copy of *source* (CR 707.2, layer 1a).

    What is stored is *source*'s copiable values — :func:`copiable_card`, not
    its ``card`` and not its ``effective_card``. That is CR 707.2's "as modified
    by other copy effects" in one call: copying a copy takes what the first copy
    became, and copying a permanent under a text change or an animation takes
    neither.

    One contribution per *effect_source* (the copier itself unless something
    else made the copy), replaced on re-record with a fresh timestamp — which is
    what Vesuvan Doppelganger's upkeep re-copy needs, and what stops a
    once-per-upkeep ability accumulating an entry per turn.
    """
    owner = effect_source if effect_source is not None else permanent
    kept = [entry for entry in copy_effects(permanent) if entry["source"] is not owner]
    kept.append({
        "source": owner,
        "card": copiable_card(source),
        "copies": frozenset(copies),
        "adds_types": tuple(adds_types),
        "grants": tuple(grants),
        # CR 707.9a's "**except it has this ability**" (Unstable Shapeshifter):
        # printed lines the copy has *in addition to* the copiable values.
        #
        # Beside ``grants`` rather than in it, because the two are read by
        # different things: that one holds marker names a fire site looks up
        # (``RECOPY_EACH_UPKEEP``), and this one holds oracle text that the
        # compiler reads like any other line — which is what makes the granted
        # trigger fire again without anything knowing which card granted it.
        "grants_text": tuple(grants_text),
        # 613.7b: an effect is stamped when it is created.
        "timestamp": next_timestamp(),
        "label": label or source.card.name,
    })
    permanent.metadata[COPY_EFFECTS] = kept


def end_copy(permanent: "Permanent", *, source: "Permanent") -> bool:
    """Drop *source*'s copy contribution. Returns whether there was one.

    Nothing in this pool ends a copy effect — Clone and Vesuvan Doppelganger
    copy for as long as they are on the battlefield — but ending one is the
    absence of a contribution here, the same as in ``engine/control.py``, rather
    than a stamp somebody has to remember to un-stamp.
    """
    existing = copy_effects(permanent)
    kept = [entry for entry in existing if entry["source"] is not source]
    if len(kept) == len(existing):
        return False
    if kept:
        permanent.metadata[COPY_EFFECTS] = kept
    else:
        permanent.metadata.pop(COPY_EFFECTS, None)
    return True


def copy_effects(permanent: "Permanent") -> list[dict]:
    """Every layer-1 contribution on *permanent*, oldest first (CR 613.7)."""
    entries = permanent.metadata.get(COPY_EFFECTS)
    if not entries:
        return []
    return sorted(entries, key=lambda entry: entry["timestamp"])


def is_copy(permanent: "Permanent") -> bool:
    """Whether any copy effect applies — the fast path every characteristic
    read takes, so a board with no copy on it never pays for layer 1.

    A **derived** source counts only while its condition holds: an armed
    "as long as the top card of your graveyard is a creature card" over a
    graveyard topped by a land is a copy effect that does not apply, and saying
    otherwise here would report a Shapeshifter as a copy of nothing.
    """
    if permanent.metadata.get(COPY_EFFECTS):
        return True
    return bool(_derived_entries(permanent))


def grants_ability(permanent: "Permanent", ability: str) -> bool:
    """Whether a copy effect granted *permanent* this ability (CR 707.9a)."""
    return any(ability in entry["grants"] for entry in copy_effects(permanent))


# ---------------------------------------------------------------------------
# The derived channel — a copy whose source is a standing question
# ---------------------------------------------------------------------------

# CR 613.7a stamps a continuous effect generated by a static ability with the
# timestamp of the object the ability is on, which is always earlier than
# anything that later copies *onto* that object. Every derived contribution
# therefore sorts ahead of every recorded one, and one sentinel expresses that
# without a per-permanent stamp to keep in step — the same convention
# ``layer_bridge._DERIVED_TIMESTAMP`` uses for the channels it rebuilds.
_DERIVED_TIMESTAMP = 0


def set_derived_copy_source(
    permanent: "Permanent", *, owner, spec, key: str
) -> None:
    """Record where *permanent*'s derived layer-1 copy reads its source from.

    *owner* is the ``PlayerState`` whose zone is read (CR 109.5's "your"), *spec*
    the :class:`~engine.zone_copies.ZoneTopCopy` saying which zone and what the
    card there must be, and *key* names the sentence that armed it so a second
    printing on the same permanent replaces its own entry rather than stacking.

    **Nothing about the copied card is stored** — that is the whole point. What
    is stored is where to look, and :func:`copiable_card` looks every time it
    folds, so a card arriving on the graveyard changes what this permanent is
    with no event to catch and nothing to invalidate.
    """
    kept = [
        record
        for record in (permanent.metadata.get(DERIVED_COPY_SOURCES) or ())
        if record["key"] != key
    ]
    kept.append({"key": key, "owner": owner, "spec": spec})
    permanent.metadata[DERIVED_COPY_SOURCES] = kept


def clear_derived_copy_sources(permanent: "Permanent") -> None:
    """Drop every derived layer-1 source on *permanent*.

    Called by the refresh before it rebuilds them, so a permanent that has lost
    the static ability (or left the battlefield, or changed controller) stops
    copying by *not being re-armed* rather than by something remembering to undo
    a stamp — CR 611.3b as the derived land-type channel already reads it.
    """
    permanent.metadata.pop(DERIVED_COPY_SOURCES, None)


def derived_copy_sources(permanent: "Permanent") -> list[dict]:
    """The derived layer-1 sources armed on *permanent*."""
    return list(permanent.metadata.get(DERIVED_COPY_SOURCES) or ())


def _derived_entries(permanent: "Permanent") -> list[dict]:
    """*permanent*'s derived layer-1 contributions, resolved against the board.

    A source whose condition is false right now contributes nothing — an empty
    zone, or a top card of the wrong type — which is the sentence's own "as long
    as" with no separate off switch.
    """
    records = permanent.metadata.get(DERIVED_COPY_SOURCES)
    if not records:
        return []
    # Imported here rather than at module scope: ``zone_copies`` reaches the
    # grammar's vocabulary, and this module is imported by ``models``.
    from .zone_copies import copied_card_for
    from .zone_positions import zone_cards

    entries: list[dict] = []
    for record in records:
        spec = record["spec"]
        card = copied_card_for(zone_cards(record["owner"], spec.zone), spec)
        if card is None:
            continue
        entries.append({
            "source": permanent,
            "card": card,
            "copies": ALL_VALUES,
            "adds_types": (),
            "grants": (),
            "grants_text": tuple(spec.grants_text),
            "timestamp": _DERIVED_TIMESTAMP,
            "label": card.name,
        })
    return entries


# ---------------------------------------------------------------------------
# Applying the recorded contributions
# ---------------------------------------------------------------------------

# Folded cards, keyed by the identity fields of the two cards involved and the
# exception the effect declares — never ``id()``, which a freed temporary could
# hand to something else. ``copiable_card`` sits under ``effective_card``, which
# is read on nearly every rules query, and ``compile_card_oracle`` caches on the
# text, so a stable object keeps a copy compiling exactly once.
_COPIED_CARDS: dict[tuple, "CardDefinition"] = {}


def _identity(card: "CardDefinition") -> tuple:
    return (
        card.name, card.mana_cost, card.cmc, card.type_line, card.oracle_text,
        card.colors, card.color_identity, card.keywords, card.produced_mana,
        card.printed_power, card.printed_toughness,
    )


def _with_added_types(type_line: str, added: tuple[str, ...]) -> str:
    """*type_line* with CR 707.9b's "in addition to its other types" applied.

    Inserted before the em dash, because everything after it is a subtype:
    appending to "Artifact — Equipment" would make Enchantment an Equipment
    subtype rather than a card type.
    """
    lowered = type_line.lower()
    missing = [word for word in added if word.lower() not in lowered]
    if not missing:
        return type_line
    head, dash, tail = type_line.partition("—")
    if dash:
        return f"{' '.join([head.strip(), *missing])} {dash} {tail.strip()}"
    return " ".join([type_line.strip(), *missing]).strip()


def _apply_one(base: "CardDefinition", entry: Mapping) -> "CardDefinition":
    """One copy effect over *base*, the values the object had without it."""
    copied: "CardDefinition" = entry["card"]
    copies: frozenset[str] = entry["copies"]
    added: tuple[str, ...] = entry["adds_types"]
    # ``get``, because entries written before this key existed are still valid
    # contributions — the same tolerance every optional key here has.
    granted_text: tuple[str, ...] = tuple(entry.get("grants_text") or ())

    # Start from everything the copy effect hands over and put back what it
    # declines (CR 707.9c: "the affected objects instead retain their original
    # values"). Retention is the fold's rule, so an effect that copies
    # everything allocates nothing at all — it *is* the copied card.
    #
    # ``raw`` always comes from the copied card, and is deliberately not one of
    # the groups above: it is the loader's untyped mirror of the printed fields,
    # so splitting it per characteristic would be a second place for the same
    # values to disagree. No card in the pool declines power/toughness, which is
    # the only value it would matter for.
    overrides: dict = {}
    for value, fields in _FIELDS.items():
        if value in copies:
            continue
        for field in fields:
            overrides[field] = getattr(base, field)
    if added:
        overrides["type_line"] = _with_added_types(
            overrides.get("type_line", copied.type_line), added
        )
    if granted_text:
        # CR 707.9a: the ability is *in addition to* the copiable values, so it
        # is appended to whatever text the fold has arrived at rather than
        # replacing it. A line already present is not added twice — a
        # Shapeshifter copying another Shapeshifter would otherwise accumulate
        # one copy of the sentence per copy effect, and the trigger would fire
        # that many times.
        base_text = overrides.get("oracle_text", copied.oracle_text) or ""
        lines = [line for line in base_text.splitlines() if line]
        for line in granted_text:
            if line not in lines:
                lines.append(line)
        overrides["oracle_text"] = "\n".join(lines)
    if not overrides:
        return copied
    return dataclasses.replace(copied, **overrides)


def _fold(base: "CardDefinition", entries: list[dict]) -> "CardDefinition":
    """*entries* applied over *base*, in the order given."""
    result = base
    for entry in entries:
        key = (
            _identity(result), _identity(entry["card"]),
            entry["copies"], entry["adds_types"],
            tuple(entry.get("grants_text") or ()),
        )
        cached = _COPIED_CARDS.get(key)
        if cached is None:
            cached = _apply_one(result, entry)
            _COPIED_CARDS[key] = cached
        result = cached
    return result


def copiable_card(permanent: "Permanent") -> "CardDefinition":
    """*permanent*'s copiable values after layer 1 (CR 613.2c).

    Returns the permanent's own ``card`` — the same object, unallocated — when
    no copy effect applies, which is every permanent on almost every board.

    Both channels, derived first (see :data:`_DERIVED_TIMESTAMP`). The derived
    ones are resolved against the live zone on **every call**, which is what
    lets ``engine/zone_copies.py``'s standing question be answered without an
    event: reordering a graveyard changes the answer and nothing has to notice.
    """
    entries = permanent.metadata.get(COPY_EFFECTS)
    derived = _derived_entries(permanent)
    if not entries and not derived:
        return permanent.card
    ordered = derived + sorted(entries or (), key=lambda item: item["timestamp"])
    return _fold(permanent.card, ordered)


def recorded_copiable_card(permanent: "Permanent") -> "CardDefinition":
    """*permanent*'s copiable values from the **recorded** channel alone.

    What the permanent would say with its derived copy switched off, which is
    the card the refresh has to read to decide whether the derived copy applies
    at all. Reading ``effective_card`` there instead would be self-referential:
    the copy replaces the rules text, so the static ability that generated it
    would be gone from what the next pass looks at, and the copy would flicker
    on and off one recompute at a time.

    That is also what CR 613.6 says to do — an effect that has started to apply
    keeps applying "even if the ability generating the effect is removed during
    this process" — so the reading is the rule rather than a way around it.
    """
    entries = permanent.metadata.get(COPY_EFFECTS)
    if not entries:
        return permanent.card
    return _fold(permanent.card, sorted(entries, key=lambda item: item["timestamp"]))


def copied_name(permanent: "Permanent") -> str | None:
    """The name of the object *permanent* is currently a copy of, or None.

    Derived from the newest contribution rather than stamped alongside it, so a
    permanent cannot be reported as a copy of something it no longer copies —
    and over the same ordered pair of channels :func:`copiable_card` folds, so
    the reported name is the one whose text the permanent actually has.
    """
    entries = copy_effects(permanent) or _derived_entries(permanent)
    return entries[-1]["card"].name if entries else None


__all__ = [
    "ALL_VALUES", "COLOR", "COPY_EFFECTS", "DERIVED_COPY_SOURCES",
    "EXCEPT_COLOR", "MANA_COST", "NAME",
    "POWER_TOUGHNESS", "RECOPY_EACH_UPKEEP", "TEXT", "TYPES", "become_copy",
    "clear_derived_copy_sources", "copiable_card", "copied_name",
    "copy_effects", "copy_exceptions", "derived_copy_sources",
    "end_copy", "grants_ability", "is_copy", "recorded_copiable_card",
    "set_derived_copy_source",
]
