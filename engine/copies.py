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
    read takes, so a board with no copy on it never pays for layer 1."""
    return bool(permanent.metadata.get(COPY_EFFECTS))


def grants_ability(permanent: "Permanent", ability: str) -> bool:
    """Whether a copy effect granted *permanent* this ability (CR 707.9a)."""
    return any(ability in entry["grants"] for entry in copy_effects(permanent))


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
    if not overrides:
        return copied
    return dataclasses.replace(copied, **overrides)


def copiable_card(permanent: "Permanent") -> "CardDefinition":
    """*permanent*'s copiable values after layer 1 (CR 613.2c).

    Returns the permanent's own ``card`` — the same object, unallocated — when
    no copy effect applies, which is every permanent on almost every board.
    """
    entries = permanent.metadata.get(COPY_EFFECTS)
    if not entries:
        return permanent.card
    result = permanent.card
    for entry in sorted(entries, key=lambda item: item["timestamp"]):
        key = (
            _identity(result), _identity(entry["card"]),
            entry["copies"], entry["adds_types"],
        )
        cached = _COPIED_CARDS.get(key)
        if cached is None:
            cached = _apply_one(result, entry)
            _COPIED_CARDS[key] = cached
        result = cached
    return result


def copied_name(permanent: "Permanent") -> str | None:
    """The name of the object *permanent* is currently a copy of, or None.

    Derived from the newest contribution rather than stamped alongside it, so a
    permanent cannot be reported as a copy of something it no longer copies.
    """
    entries = copy_effects(permanent)
    return entries[-1]["card"].name if entries else None


__all__ = [
    "ALL_VALUES", "COLOR", "COPY_EFFECTS", "EXCEPT_COLOR", "MANA_COST", "NAME",
    "POWER_TOUGHNESS", "RECOPY_EACH_UPKEEP", "TEXT", "TYPES", "become_copy",
    "copiable_card", "copied_name", "copy_effects", "copy_exceptions",
    "end_copy", "grants_ability", "is_copy",
]
