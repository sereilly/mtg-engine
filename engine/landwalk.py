"""Landwalk (CR 702.14) — the ability's printed quality, and the land it looks for.

CR 702.14a spells the family as "[type]walk", where the type "is usually a land
type, but it can also be the card type land plus any combination of land types,
card types, and/or supertypes". So the pool prints two shapes:

``islandwalk``, ``forestwalk``, …
    the quality is a **land subtype**, welded onto the word.
``legendary landwalk`` (Livonya Silone), ``nonbasic landwalk``
    the quality is a **supertype** (optionally negated) sitting in front of the
    family word ``landwalk``.
``snow forestwalk``, ``snow swampwalk`` (Ice Age)
    "any combination" taken literally: a supertype **and** a subtype, and the
    defending player must control a land answering both. This is why a
    requirement is a *tuple* of qualities rather than one — a reader that kept
    only the last word would let Rime Dryad through against any Forest, which
    is a strictly better creature than the one printed, and one that kept only
    the first would make it unblockable against any snow land at all.

Both are one question — "does the defending player control a land like this?"
(CR 702.14c) — so both are one requirement here rather than two enforcement
sites. The quality is **payload**: a card printing ``snow landwalk`` or
``world landwalk`` needs no code, because the supertype comes from
``data/vocabulary`` like every other type word, and a set printing a new land
subtype needs ``scripts/fetch_vocabulary.py`` and nothing else.

This module is also the *gate*: ``engine.oracle``'s keyword-line admission asks
:func:`landwalk_requirement` whether a printed quality is one the check below
can actually test. A quality admitted with nothing testing it would ship a
creature whose evasion silently never applies — the quiet failure the keyword
registry exists to prevent, in the one spelling ``IMPLEMENTED_KEYWORDS`` cannot
hold, since the ability's name *is* the printed quality.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple

from .oracle_types import compilation_cache, strip_ability_word

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import Permanent

#: The family word a quality-first landwalk is printed in front of.
LANDWALK = "landwalk"


class LandQuality(NamedTuple):
    """One of the qualities a landwalk names.

    ``kind`` is ``"subtype"`` (``islandwalk`` → an Island) or ``"supertype"``
    (``legendary landwalk`` → a legendary land). ``negated`` is CR 702.14c's
    "without the specified type or supertype" — ``nonbasic landwalk``.
    """

    kind: str
    quality: str
    negated: bool = False


class LandwalkRequirement(NamedTuple):
    """What land the defending player must control for this landwalk to apply.

    Every quality must hold of the **same** land (CR 702.14c): "snow
    forestwalk" asks for one land that is both, not for a snow land and,
    separately, a Forest.
    """

    qualities: tuple[LandQuality, ...]


@lru_cache(maxsize=None)
def landwalk_requirement(ability: str) -> LandwalkRequirement | None:
    """The requirement *ability* names, or None if it is not landwalk at all.

    None is also the answer for the bare family word ``landwalk``: Scryfall's
    keywords field lists it beside the concrete ability (Livonya Silone is
    ``("Landwalk", "First strike", "Legendary landwalk")``), and a landwalk with
    no quality names no land, so it restricts no block.
    """
    from .grammar.vocabulary import LAND_TYPES, TYPE_LINE_SUPERTYPES

    ability = (ability or "").strip().lower().rstrip(".")
    if not ability:
        return None
    words = ability.split()
    if not words[-1].endswith("walk"):
        return None
    qualities: list[LandQuality] = []
    # Every word but the last is a supertype, optionally negated ("nonbasic
    # landwalk", "snow forestwalk"). An unknown one refuses the whole ability
    # rather than being skipped: a quality dropped from an evasion restriction
    # widens it, which is the one direction this must never go.
    for head in words[:-1]:
        negated = head.startswith("non")
        quality = head[3:] if negated else head
        if quality not in TYPE_LINE_SUPERTYPES:
            return None
        qualities.append(LandQuality("supertype", quality, negated))
    tail = words[-1]
    if tail != LANDWALK:
        subtype = tail[: -len("walk")]
        if subtype not in LAND_TYPES:
            return None
        qualities.append(LandQuality("subtype", subtype))
    if not qualities:
        # The bare family word, which names no land and so restricts no block.
        return None
    return LandwalkRequirement(tuple(qualities))


def landwalk_abilities_of(permanent: "Permanent") -> tuple[str, ...]:
    """The landwalk abilities *permanent*'s own land types name (CR 702.14a).

    "Target creature gains landwalk of each of the land types of the sacrificed
    land until end of turn." (Excavator.) A land's types are read here rather
    than by the handler, so the word a grant builds and the word a block check
    reads are built by one module: every name this returns is one
    :func:`landwalk_requirement` answers, because it is built out of the land's
    own subtype.

    Through the computed accessor, so a Dwarven Hold that Blood Moon has made a
    Mountain grants mountainwalk and a basic Forest that Conversion has turned
    into Plains grants plainswalk. Ordered by the type line rather than sorted,
    because a dual land grants two and the printed order is the only order there
    is. Anything that is not a land — and any land with no subtype — grants
    nothing, which is the direction that cannot invent an evasion.
    """
    from .layer_bridge import computed_types
    from .grammar.vocabulary import LAND_TYPES

    card_types, subtypes = computed_types(permanent)
    if "land" not in card_types:
        return ()
    seen: list[str] = []
    for subtype in subtypes:
        word = str(subtype).lower()
        if word not in LAND_TYPES:
            continue
        ability = f"{word}walk"
        if ability not in seen:
            seen.append(ability)
    return tuple(seen)


def is_landwalk(ability: str) -> bool:
    """Whether *ability* is a landwalk the engine can enforce."""
    return landwalk_requirement(ability) is not None


def land_satisfies(permanent: "Permanent", requirement: LandwalkRequirement) -> bool:
    """Whether *permanent* is the land CR 702.14c asks the defender to control.

    Types go through the computed accessors, so an animated land, a copy or a
    basic-land-type change answers with what it *currently* is — and the
    supertype arm does too, since layer 4 computes those as well: a land Arcum's
    Weathervane has thawed is no longer the snow Forest a snow forestwalker
    needs.
    """
    if not permanent.has_type("land"):
        return False
    supertypes = None
    for quality in requirement.qualities:
        if quality.kind == "subtype":
            if not permanent.has_type(quality.quality):
                return False
            continue
        if supertypes is None:
            supertypes = permanent.effective_supertypes
        held = quality.quality in supertypes
        if held == quality.negated:
            return False
    return True


# ---------------------------------------------------------------------------
# A landwalk named by the board (CR 702.14a, CR 604.1)
# ---------------------------------------------------------------------------
#
# "For each basic land type among lands you control, this creature has landwalk
# of that type." (Magnigoth Treefolk.) A *static* ability whose granted words
# are not in the text: which landwalks the creature has is a fact about its
# controller's lands, re-read at every recompute (CR 611.3a — a static ability
# applies whenever its criteria are met; nothing is locked in).
#
# The third way this pool builds a landwalk's name out of something other than
# a printed word, after the land a cost ate (Excavator —
# :func:`landwalk_abilities_of`) and the type an Aura chose as it entered
# (Traveler's Cloak — ``auras.chosen_landwalk_grants``), and it follows the
# second one's arrangement exactly: **one reader, two callers**. The support
# gate and the grammar's registry claim ask :func:`landwalk_per_type_spec`
# whether a line is one this can carry out, and the layer-6 pass asks
# :func:`board_named_landwalks`, which reads the same lines through the same
# function — so a line claimed here is a line granted here.
#
# What the types are counted *among* is an ordinary noun phrase in an ordinary
# count position, so it is read by the grammar's own per-each reader
# (``grammar.per_each_count_spec_for``) and answered by the one scan every
# count in the engine uses (``handlers/_common.basic_land_types_among``). The
# subject is the ability's own creature and nothing else: a sentence granting
# the words to another object would need a recipient this reader does not
# resolve, so it refuses rather than granting them to the source.
_PER_TYPE_LANDWALK = re.compile(
    r"^(?P<counted>for each .+?), this creature has landwalk of that type$"
)

#: The only characteristic "landwalk of that type" can name a landwalk from —
#: the count aggregate ``grammar/distinct.py`` gives "basic land type[s] among".
_LAND_TYPE_AGGREGATE = "distinct_basic_land_types"

#: ``Permanent.metadata`` key holding the landwalks a permanent's own text
#: currently names off the board, as a tuple of words. Written by
#: ``mixins/permanent_state._refresh_dynamic_creatures`` (cleared and rebuilt on
#: every pass, behind that pass's layer-4 refreshes) and read by
#: ``layer_bridge.collect_ability_effects`` as a layer-6 grant. A derived value
#: and never a record: nothing may write it but that refresh.
BOARD_NAMED_LANDWALKS = "board_named_landwalks"


def _static_line_text(line: str) -> str:
    """*line* as this table reads it: no ability word (CR 207.2c), no reminder
    text, lowercased, no full stop. Idempotent, so a caller that has already
    normalized the line and one holding it as printed read the same thing."""
    from .grammar.lexer import strip_reminder_text

    text, _reminders = strip_reminder_text(strip_ability_word(line or ""))
    return " ".join(text.lower().split()).rstrip(".").strip()


# ``@compilation_cache``: the spec comes out of the grammar's lowering, so a
# caller that swaps a piece of that out and back must be able to empty this
# (``oracle_types.clear_compilation_caches``) — a None cached while the
# aggregate was switched off would leave the card unsupported for the rest of
# the process.
@compilation_cache
@lru_cache(maxsize=None)
def landwalk_per_type_spec(line: str) -> dict | None:
    """The count spec whose basic land types *line* turns into landwalks on its
    own creature — or None when the line is not that sentence in full.

    None for a characteristic no landwalk can be built from ("for each creature
    you control, this creature has landwalk of that type" names no type), and
    for a set this cannot scope (another player's lands), because the grammar's
    reader refuses both. The spec is the one a domain *count* carries, so the
    types granted are exactly the types that count would have counted.
    """
    match = _PER_TYPE_LANDWALK.match(_static_line_text(line))
    if match is None:
        return None
    from .grammar import per_each_count_spec_for

    spec = per_each_count_spec_for(match.group("counted"))
    if spec is None or spec.get("aggregate") != _LAND_TYPE_AGGREGATE:
        return None
    return spec


def _per_type_landwalk_specs(oracle_text: str) -> tuple[dict, ...]:
    """Every such spec a card's text prints, one per line that is the sentence.

    Not cached itself: the layer-6 pass asks it of every permanent on every
    recompute, and each line's answer is already one lookup in the cache
    above — a second cache over the same answers would be one more to empty
    and nothing saved."""
    return tuple(
        spec for spec in (
            landwalk_per_type_spec(line) for line in (oracle_text or "").splitlines()
        )
        if spec is not None
    )


def board_named_landwalks(game, seat: int, permanent: "Permanent") -> tuple[str, ...]:
    """The landwalk abilities *permanent*'s own text gives it **right now**,
    named by the basic land types among the lands *seat* controls.

    Read off ``effective_card`` (CR 707.2: a copy of the Treefolk walks by the
    copy's controller's lands; CR 612: a text change is the text) and counted
    for *seat*, the permanent's current controller — the walker's lands name
    the types, and the *defending* player's lands decide whether each one
    applies (CR 702.14c, ``declare_blockers_step``), which are two different
    boards. Every word is put to :func:`landwalk_requirement`, the reader that
    enforces the ability, so a grant nothing would enforce is never made.
    """
    specs = _per_type_landwalk_specs(permanent.effective_card.oracle_text or "")
    if not specs:
        return ()
    from .handlers._common import basic_land_types_among

    owner = game.players[seat]
    walks: list[str] = []
    for spec in specs:
        for land_type in basic_land_types_among(game, owner, spec, source=permanent):
            walk = f"{land_type}walk"
            if walk not in walks and landwalk_requirement(walk) is not None:
                walks.append(walk)
    return tuple(walks)


__all__ = [
    "BOARD_NAMED_LANDWALKS",
    "LANDWALK",
    "LandQuality",
    "LandwalkRequirement",
    "board_named_landwalks",
    "is_landwalk",
    "landwalk_abilities_of",
    "landwalk_per_type_spec",
    "land_satisfies",
    "landwalk_requirement",
]
