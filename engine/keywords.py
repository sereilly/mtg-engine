"""Single write API for keyword abilities (CR 613 layer 6).

Granting and removing an ability share one layer, so which one wins is decided
by **timestamp**, not by which code path happened to run last (CR 613.9's
worked example is exactly this: an Aura granting flying and one removing it,
resolved by whichever is newer). Recording each grant and removal in order is
what makes that answerable.

The engine previously stored one metadata flag per keyword per direction —
``gains_flying``, ``gains_flying_until_eot``, ``loses_flying``,
``gains_trample_until_eot`` and so on — read by an if-chain that checked
removals first and so made removal always win. That is a rule the rules do not
have, and it needed a new flag and a new branch for every keyword.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .continuous import next_timestamp

if TYPE_CHECKING:
    from .models import Permanent

# Key under which a permanent's ordered grants/removals live.
ABILITY_EFFECTS = "ability_effects"

# Key under which *derived* grants live — abilities a permanent has because of
# something else on the battlefield right now (a lord's "other Goblins have
# mountainwalk"). They carry no timestamp of their own because they are not
# recorded: the channel is cleared and rebuilt from the board on every
# continuous-effects recompute, exactly like the derived layer-7c P/T channels.
#
# Recording them through :func:`grant_keyword` instead would append one entry
# per recompute forever, and CR 611.3a means the recompute runs constantly.
DERIVED_GRANTS = "derived_ability_grants"

# Key under which granted **printed ability lines** live — the third channel in
# this file, and the one for an ability layer 6's word-set cannot carry.
#
# Most keywords are behaviour the engine reads off the word: `has_keyword`
# answers, and flying, trample and the rest are checked wherever they apply. A
# few are not, because the CR *defines* them as an ability rather than
# describing one — CR 702.23a says "Rampage N" **means** "Whenever this creature
# becomes blocked, …", and `engine/rampage.py` accordingly rewrites the printed
# line into the trigger it already is. Nothing downstream of the compiler knows
# the word, which is exactly why granting one as a layer-6 keyword would grant
# nothing at all: the compiler has already run, over a card that did not say it.
#
# So a grant of such an ability grants the *line*, and `Permanent.effective_card`
# folds it into the rules text — the same channel a board-wide static's granted
# ability already uses (`engine/global_statics.py`), for the same reason. From
# there the compiler produces the ability like any printed one and the
# becomes-blocked dispatcher fires it without knowing a spell granted it.
GRANTED_ABILITY_LINES = "granted_ability_lines"

#: Which keyword words that applies to. One entry today, and the membership test
#: is not "does it have a number": it is "does the compiler build this keyword's
#: behaviour out of the printed line". Prowess and lifelink also have behaviour
#: the layer system does not store, but `has_keyword` is what reads them, so a
#: layer-6 grant reaches them. Rampage's reader is `compile_card_oracle`.
LINE_DERIVED_KEYWORDS = frozenset({"rampage"})


def keyword_ability_name(keyword: str) -> str:
    """*keyword* without its argument — the name of the ability itself.

    "Protection from black" is the keyword *protection* carrying a quality
    (CR 702.16a) and "rampage 2" is *rampage* carrying its N (CR 702.23a); the
    registries in this engine list abilities, not every argument one can take.

    Here rather than in the grammar because both sides of the colon need it: the
    lowering asks whether a grant names an implemented ability, and the handler
    asks which channel to put it on. Two spellings of "strip the argument" is
    how those two come to disagree about what a card said.

    Which keywords take a number is the parser's vocabulary — imported here
    rather than restated, and imported inside the function because this module
    sits underneath the grammar in the import order.
    """
    from .banding import BANDS_WITH_OTHER, is_bands_with_other
    from .grammar.vocabulary import NUMERIC_ARGUMENT_KEYWORDS

    if keyword.startswith("protection from "):
        return "protection"
    # "Bands with other legendary creatures" is the ability *bands with other*
    # carrying a quality (CR 702.22b) — the same shape protection has one line
    # up, so the registry holds one entry and every printed quality strips to
    # it. Without this, asking the registry about a granted band would be asking
    # about a word no list can contain: the quality is whatever the card prints.
    if is_bands_with_other(keyword):
        return BANDS_WITH_OTHER
    head = keyword.split(" ")[0]
    return head if head in NUMERIC_ARGUMENT_KEYWORDS else keyword


def _record(perm: Permanent, keyword: str, *, grant: bool, until_eot: bool) -> None:
    effects = perm.metadata.setdefault(ABILITY_EFFECTS, [])
    effects.append(
        {
            "keyword": keyword.lower(),
            "grant": grant,
            "until_eot": until_eot,
            "timestamp": next_timestamp(),
        }
    )


def grant_keyword(perm: Permanent, keyword: str, *, until_eot: bool = False) -> None:
    """Layer 6: give *perm* a keyword ability from now (613.7b)."""
    _record(perm, keyword, grant=True, until_eot=until_eot)


def remove_keyword(perm: Permanent, keyword: str, *, until_eot: bool = False) -> None:
    """Layer 6: take a keyword ability away. Whether this beats a grant is
    decided by timestamp, so a later grant restores the ability."""
    _record(perm, keyword, grant=False, until_eot=until_eot)


def clear_until_eot_keywords(perm: Permanent) -> None:
    """Drop the until-end-of-turn grants and removals during cleanup."""
    effects = perm.metadata.get(ABILITY_EFFECTS)
    if not effects:
        return
    remaining = [entry for entry in effects if not entry.get("until_eot")]
    if remaining:
        perm.metadata[ABILITY_EFFECTS] = remaining
    else:
        perm.metadata.pop(ABILITY_EFFECTS, None)


def ability_effects(perm: Permanent) -> list[dict]:
    """The recorded grants and removals, oldest first."""
    return list(perm.metadata.get(ABILITY_EFFECTS) or ())


def clear_derived_grants(perm: Permanent) -> None:
    """Drop the grants derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them. Splitting the clear from the
    rebuild is how a derived channel turns into an accumulating one.
    """
    perm.metadata.pop(DERIVED_GRANTS, None)


def grant_ability_line(perm: Permanent, line: str, *, until_eot: bool = False) -> None:
    """Layer 6: give *perm* a printed ability *line* (see GRANTED_ABILITY_LINES).

    Recorded rather than applied, and read back in grant order, because the
    compiler is what turns the line into an ability — this channel only has to
    say what the permanent now says.
    """
    lines = perm.metadata.setdefault(GRANTED_ABILITY_LINES, [])
    lines.append({"line": line, "until_eot": until_eot})


def granted_ability_lines(perm: Permanent) -> tuple[str, ...]:
    """The printed ability lines *perm* has been granted, oldest first."""
    return tuple(entry["line"] for entry in perm.metadata.get(GRANTED_ABILITY_LINES) or ())


def clear_until_eot_granted_ability_lines(perm: Permanent) -> None:
    """Drop the until-end-of-turn granted lines during cleanup.

    The twin of :func:`clear_until_eot_keywords`, called beside it: a grant that
    outlived the turn would leave the permanent compiling an ability it no
    longer has.
    """
    lines = perm.metadata.get(GRANTED_ABILITY_LINES)
    if not lines:
        return
    remaining = [entry for entry in lines if not entry.get("until_eot")]
    if remaining:
        perm.metadata[GRANTED_ABILITY_LINES] = remaining
    else:
        perm.metadata.pop(GRANTED_ABILITY_LINES, None)


def add_derived_grant(perm: Permanent, keyword: str) -> None:
    """Layer 6: *perm* has *keyword* for as long as the source keeps granting it."""
    granted = perm.metadata.setdefault(DERIVED_GRANTS, [])
    lowered = keyword.lower()
    if lowered not in granted:
        granted.append(lowered)


def derived_grants(perm: Permanent) -> tuple[str, ...]:
    """The abilities *perm* currently has from a board-wide source."""
    return tuple(perm.metadata.get(DERIVED_GRANTS) or ())


__all__ = [
    "ABILITY_EFFECTS", "DERIVED_GRANTS", "GRANTED_ABILITY_LINES",
    "LINE_DERIVED_KEYWORDS", "ability_effects", "add_derived_grant",
    "clear_derived_grants", "clear_until_eot_granted_ability_lines",
    "clear_until_eot_keywords", "derived_grants", "grant_ability_line",
    "keyword_ability_name",
    "granted_ability_lines", "grant_keyword", "remove_keyword",
]
