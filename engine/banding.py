"""CR 702.22's "bands with other [quality]" — the parameterised half of banding.

Plain banding is a word: a creature has it or does not, and the three combat
sites that read it (the attacking-band declaration, and the two damage-division
exceptions) ask ``has_keyword("banding")``. **"Bands with other" is not a
word.** CR 702.22c and 702.22j/k both spell it ``[quality] creature with "bands
with other [quality]"``, and the quality is printed on the card: *legendary
creatures* on Legends' five lands, *creatures named Wolves of the Hunt* on the
token Master of the Hunt makes. Two cards, two qualities, one ability.

So the quality is **payload**, and this module is the one place that reads it.
The ability itself stays a string in CR 613 layer 6's word set — the same
channel every other keyword lives in, which is what makes a grant (a lord line),
a removal (Shelkin Brownie) and a printed line (the Wolves token) compose by
timestamp instead of by three flags. What the string *means* is a noun phrase,
so it is read by the noun parser and carried as the filter payload
``subject_matches`` already tests: a card printing "bands with other Zombies"
needs no code here, and one printing a quality the matcher cannot test refuses
its line rather than banding with everything.

Three readers, and they ask different questions — which is why they are three
functions rather than one predicate everybody reuses wrongly:

``band_quality_filter``
    what one ability means, as a filter payload.
``bands_with_other_pair``
    CR 702.22j/k: does this group of creatures contain a [quality] creature
    with "bands with other [quality]" **and another** [quality] creature? Two
    of them, not all of them — the rule says "by both … and another".
``bands_with_other_band``
    CR 702.22c: may this whole set be declared as one attacking band? **All**
    of them must be [quality], because the rule says "one or more attacking
    [quality] creatures with 'bands with other [quality]' and any number of
    other attacking [quality] creatures".

The family name — ``"bands with other"`` with no quality — is not an ability
anything has. It is what a *removal* names ("loses all 'bands with other'
abilities", Shelkin Brownie), and CR 702.22b makes removing plain banding name
the same set. :func:`engine.keywords.expand_ability_removal` is where both of
those become the concrete abilities layer 6 takes away — beside the removal API
rather than here, because banding is not the only family a removal can name.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent

#: The ability family's name, as CR 702.22b and every printed removal spell it.
#: Also what :func:`engine.keywords.keyword_ability_name` strips a quality down
#: to, so the registry lists one ability rather than one per printed quality.
BANDS_WITH_OTHER = "bands with other"

_PREFIX = BANDS_WITH_OTHER + " "


def is_bands_with_other(ability: str) -> bool:
    """Whether *ability* is this family — the bare family name or one quality."""
    ability = (ability or "").strip().lower()
    return ability == BANDS_WITH_OTHER or ability.startswith(_PREFIX)


def band_quality(ability: str) -> str | None:
    """The quality *ability* names, or None for the bare family name.

    None is not "no restriction": a bands-with-other ability with no quality is
    not an ability a permanent can have, and every caller below treats None as
    "this grants nothing".
    """
    ability = (ability or "").strip().lower().rstrip(".")
    if not ability.startswith(_PREFIX):
        return None
    quality = ability[len(_PREFIX):].strip()
    return quality or None


@lru_cache(maxsize=None)
def band_quality_filter(quality: str) -> dict | None:
    """*quality* as a filter payload ``subject_matches`` can test, or None.

    None means refuse — the phrase is not one the noun parser reads, or it
    carries a restriction the matcher cannot answer from the object alone. Both
    have to refuse the *card*, because a quality that is parsed and then not
    tested would let any creature join the band, which is a strictly larger set
    than the card prints.

    Object-only: a band's quality is a question about each creature ("legendary
    creatures"), never about a seat — "you control" is the granting line's own
    scope, not the band's, and CR 702.22c lets a band contain only creatures one
    player is attacking with anyway.
    """
    from .grammar import subject_filter_payload
    from .subject_filters import object_only_filter

    payload = subject_filter_payload(quality, plural=True)
    if payload is None:
        return None
    payload = object_only_filter(payload)
    if payload is None:
        return None
    # A quality that narrowed to nothing would match every permanent on the
    # battlefield, lands included. "Creatures" narrows to `type_filter`, so an
    # empty payload here means the phrase said nothing testable at all.
    return payload or None


def is_implemented(ability: str) -> bool:
    """Whether the engine can carry out *ability* — the gate a card passes.

    The family name alone is implemented as a *removal* target and never as a
    grant, which is why this asks for a quality: a card granting bare "bands
    with other" would be granting nothing.
    """
    quality = band_quality(ability)
    return quality is not None and band_quality_filter(quality) is not None


def abilities_of(abilities: Iterable[str]) -> tuple[str, ...]:
    """The bands-with-other abilities in a computed ability set, quality-first
    ones only — sorted, so a log line and a test read the same order."""
    return tuple(sorted(a for a in abilities if band_quality(a) is not None))


# ---------------------------------------------------------------------------
# The two combat questions
# ---------------------------------------------------------------------------

def _matches_quality(game: "Game", perm: "Permanent", quality: str) -> bool:
    from .subject_filters import subject_matches

    described = band_quality_filter(quality)
    if described is None:
        return False
    return subject_matches(game, perm, described)


def bands_with_other_pair(
    game: "Game", creatures: Sequence["Permanent"]
) -> bool:
    """CR 702.22j/k: is there a [quality] creature with "bands with other
    [quality]" among *creatures*, **and another** [quality] creature?

    Two members, not all of them. The rule describes a pair inside whatever set
    is blocking or being blocked — "by both a [quality] creature with 'bands
    with other [quality]' and another [quality] creature" — so a third blocker
    of some unrelated type does not stop the division from moving.
    """
    for holder in creatures:
        for ability in abilities_of(computed_abilities_of(holder)):
            quality = band_quality(ability)
            if quality is None or not _matches_quality(game, holder, quality):
                continue
            if any(
                other is not holder and _matches_quality(game, other, quality)
                for other in creatures
            ):
                return True
    return False


def bands_with_other_band(
    game: "Game", creatures: Sequence["Permanent"]
) -> bool:
    """CR 702.22c's second sentence: may *creatures* be declared as one band?

    Stricter than the pair above, and deliberately: the declaration form says
    "one or more attacking [quality] creatures with 'bands with other
    [quality]' and any number of **other** [quality] creatures", so every
    member has to be a [quality] creature. Reading it as the pair test would
    let one legendary creature with the ability drag an arbitrary creature into
    the band, which is the plain-banding form's allowance (one non-banding
    creature) and not this one's.
    """
    if len(creatures) < 2:
        return False
    for holder in creatures:
        for ability in abilities_of(computed_abilities_of(holder)):
            quality = band_quality(ability)
            if quality is None:
                continue
            if all(_matches_quality(game, member, quality) for member in creatures):
                return True
    return False


def creatures_banded_with(game: "Game", permanent: "Permanent | None") -> list["Permanent"]:
    """The **other** members of the attacking band *permanent* is in (CR 702.22e).

    "All creatures banded with it" (Icatian Skirmishers) and "creatures banded
    with this creature" (Camel) are the same set printed two ways, and this is
    the one reader of it: ``Game.combat_bands`` holds attacker *indices* into
    the active player's battlefield, so a caller reaching for it has to resolve
    slots — which is a positional battlefield read, and the kind of second
    opinion this codebase keeps finding wrong.

    Empty when the permanent is in no band, which is the honest answer for a
    lone attacker: CR 702.22c makes a band a declaration, so a creature nobody
    banded with is banded with nobody. The index is found by **identity**, never
    by value: a ``Permanent`` compares field by field, and a look-alike on the
    same battlefield would hand back a different creature's band.
    """
    if permanent is None:
        return []
    for player in game.players:
        index = next(
            (i for i, perm in enumerate(player.battlefield) if perm is permanent),
            None,
        )
        if index is None:
            continue
        band = game._attacker_band(index)
        if not band:
            return []
        return [
            player.battlefield[other]
            for other in band
            if other != index and 0 <= other < len(player.battlefield)
        ]
    return []


def computed_abilities_of(perm: "Permanent") -> frozenset[str]:
    """*perm*'s abilities after layer 6, as this module's callers want them.

    A one-line indirection so the three readers above name the layer system
    rather than reaching for a metadata channel — the same rule
    ``tests/engine/test_layer_reads.py`` holds every other characteristic to.
    """
    from .layer_bridge import computed_abilities

    return frozenset(computed_abilities(perm))


__all__ = [
    "BANDS_WITH_OTHER", "abilities_of", "band_quality", "band_quality_filter",
    "bands_with_other_band", "bands_with_other_pair",
    "is_bands_with_other", "is_implemented",
]
