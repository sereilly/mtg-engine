"""Board-wide "<permanents> enter tapped" statics (CR 614.1c).

"Artifacts, creatures, and lands your opponents control enter tapped." (Kismet,
Frozen Aether's mirror, Root Maze.) A replacement effect that applies to
somebody *else's* permanent as it enters, which is a different sentence from
the one ``engine/enter_effects.py`` already reads: that one is
"**this** artifact enters tapped", a property of the card being read off its
own text as it arrives.

Two things vary and both are payload: **which** permanents (a printed noun
phrase) and **whose** (the same phrase's controller clause). The noun phrase is
parsed by ``engine/grammar/phrases.parse_subject_filter`` — the one reader that
turns a printed phrase into a filter — so "artifacts, creatures, and lands your
opponents control" means here exactly what it means on a trigger's subject or
in a sweep, rather than being approximated by a second regex.

The gate is narrow on purpose. A filter payload carrying a key
``subject_matches`` cannot answer refuses the whole line, because a restriction
the matcher would ignore is a static that taps a strictly larger set than the
card prints — the failure this repo keeps finding, and the one that reads as
"works fine" on the two-card board anybody would test it on.
"""

from __future__ import annotations

import re

from .subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

# One kind for the family: which permanents and whose are payload, so a card
# printed "Lands your opponents control enter tapped" needs no dispatch.
ENTER_TAPPED_STATIC_KIND = "others_enter_tapped"

# Anchored at both ends. A line saying anything more — "…enter tapped and don't
# untap during their controller's next untap step" — carries a rider nothing
# here performs, and admitting it would be the loose-gate defect one level down.
_PATTERN = re.compile(r"^(?P<subject>.+?) enters? tapped$")


def enter_tapped_static_for(normalized_line: str) -> dict | None:
    """The subject filter payload *normalized_line* taps on entry, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), with
    or without its trailing period.
    """
    match = _PATTERN.match(normalized_line.strip().rstrip("."))
    if match is None:
        return None
    # Imported lazily: the grammar package imports the engine's derivation
    # modules, so a module-level import here would close a cycle.
    from .grammar.phrases import parse_subject_filter

    filt = parse_subject_filter(match.group("subject"), plural=True)
    if filt is None:
        return None
    payload = filt.to_payload()
    # "**This** artifact enters tapped" is the other sentence entirely — the
    # permanent's own entry state, already read by engine/enter_effects.py.
    # Claiming it here would apply it twice and, worse, would let this table
    # shadow a phrase whose implementation lives somewhere else.
    if filt.is_source or not payload:
        return None
    if set(payload) - TESTABLE_SUBJECT_FILTER_KEYS:
        return None
    # A phrase naming no controller ("Creatures enter tapped") would be every
    # creature including the source's own, which is a card nobody has printed;
    # refusing keeps the reading the printed cards actually have rather than
    # guessing at one.
    if payload.get("controller") is None:
        return None
    return payload


def enter_tapped_static_payload(described: dict) -> dict[str, object]:
    """*described* as an ``OracleInstruction`` payload."""
    return {"filter": dict(described)}


def enter_tapped_filter_from_payload(payload: dict) -> dict:
    """The subject filter an ``others_enter_tapped`` instruction carries."""
    return dict(payload.get("filter") or {})


__all__ = [
    "ENTER_TAPPED_STATIC_KIND",
    "enter_tapped_filter_from_payload",
    "enter_tapped_static_for",
    "enter_tapped_static_payload",
]
