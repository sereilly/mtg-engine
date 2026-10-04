"""The colour census: which colour is the most common among a set of permanents.

"This creature gets -2/-2 as long as white is **the most common color among all
permanents** or is tied for most common." (Invasion's five Djinns.) "Return
target permanent to its owner's hand if that permanent **shares a color with
the most common color among all permanents** or a color tied for most common."
(Barrin's Unmaking; Tsabo's Assassin.) "…as long as the chosen color is the
most common color among nontoken permanents the chosen player controls but
isn't tied for most common." (Call to Arms.)

One count with several askers, and what the count *is* was the part worth
writing once:

* **A colour is read through the layers** (CR 105.1, CR 613.1e), so a Lace or a
  Sway of Illusion changes the answer and an Alloy Golem counts as the colour
  it was given.
* **A multicoloured permanent counts once for each of its colours.** CR 105.2:
  it is one object *of* several colours, not several objects, and each of those
  colours is a colour it has.
* **A colourless permanent counts for nothing** — lands, most artifacts. It is
  still one of "all permanents"; it simply adds to no colour's tally.
* **With no coloured permanent at all, no colour is most common.** Every colour
  is "tied" at zero, and reading that as a five-way tie would shrink every
  Djinn on an empty board and let the two spells act on… nothing, since a
  permanent that could share the colour would have made the count non-zero. So
  the set is empty, the Djinns keep their size and the spells do nothing.

The census is a pure read of the board: nothing here is stored, so a permanent
entering, leaving or being recoloured changes the answer at the next ask with
nothing to invalidate.
"""

from __future__ import annotations

from typing import Iterable


def color_counts(game, permanents: Iterable | None = None) -> dict[str, int]:
    """How many of *permanents* are each colour (CR 105.2 — one per colour held).

    *permanents* defaults to every permanent on the battlefield, both seats',
    tokens and lands included: that is what "among all permanents" says. A
    caller with a narrower printed set (Call to Arms' "nontoken permanents the
    chosen player controls") hands that set in and gets the same arithmetic.

    Only colours that occur are keys, so an empty dict is "no coloured permanent
    here" rather than five zeroes a caller could mistake for a tie.
    """
    counts: dict[str, int] = {}
    pool = game.all_permanents() if permanents is None else permanents
    for permanent in pool:
        for color in game._effective_colors(permanent):
            counts[color] = counts.get(color, 0) + 1
    return counts


def most_common_colors(game, permanents: Iterable | None = None) -> frozenset[str]:
    """The colour(s) most common among *permanents* — **ties included**.

    One colour when it leads alone, every leader when several are level, and
    the empty set when no permanent has a colour. "Is tied for most common" is
    therefore ``len(result) > 1``, and "is the most common or is tied" is plain
    membership — the two readings the printed clauses pair up.
    """
    counts = color_counts(game, permanents)
    if not counts:
        return frozenset()
    best = max(counts.values())
    return frozenset(color for color, count in counts.items() if count == best)


def color_is_most_common(
    game, color: str, *, tied: bool = True, permanents: Iterable | None = None
) -> bool:
    """Whether *color* is the most common colour among *permanents*.

    *tied* is the printed half that follows: "…**or is tied** for most common"
    (the Djinns) admits a level count, "…**but isn't tied** for most common"
    (Call to Arms) is a strict lead. The flag is read off the card rather than
    assumed, because the two are opposite answers on every level board.
    """
    leaders = most_common_colors(game, permanents)
    if color not in leaders:
        return False
    return True if tied else len(leaders) == 1


def shares_most_common_color(game, permanent, *, permanents: Iterable | None = None) -> bool:
    """Whether *permanent* is one of the most common colours, ties included.

    "…if it shares a color with the most common color among all permanents **or
    a color tied for most common**." A colourless permanent shares a colour with
    nothing (CR 105.2), and on a board with no coloured permanent there is no
    colour to share.
    """
    if permanent is None:
        return False
    leaders = most_common_colors(game, permanents)
    return bool(leaders & set(game._effective_colors(permanent)))


__all__ = [
    "color_counts",
    "color_is_most_common",
    "most_common_colors",
    "shares_most_common_color",
]
