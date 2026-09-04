"""CR 106.6 — what a seat may spend a unit of mana *as*.

"You may spend white mana as though it were mana of any color. You may spend
other mana only as though it were colorless mana." (Celestial Dawn.) "You may
spend white mana as though it were red mana." (Sunglasses of Urza.) "You may
spend mana as though it were mana of any color." (Chromatic Orrery.)

One text table, read off the board on every continuous refresh, for the reason
every other derivation table in this engine is one: the sentence is a **static
ability** (CR 611.3a), so it lasts exactly as long as its source is on the
battlefield and not one moment longer. The three permissions this replaces were
*stamped* onto the seat as the source entered and never cleared — so destroying
Sunglasses of Urza or Chromatic Orrery left the player spending mana its way for
the rest of the game. Nothing failed, because a stamp that is never read again
is indistinguishable from a permission that is still true.

**The restriction travels with the permission.** Celestial Dawn's second
sentence is not a second card's worth of behaviour: it is the price of the
first, and a reader that took the widening and dropped the narrowing would give
a seat every colour for free. So one printed *line* produces one
:class:`ManaSpending`, both sentences folded, and a line carrying only half of a
pair the pool prints together refuses rather than being read as the generous
half.

``as_colors`` and ``fungible_colors`` are both "empty means every", which reads
backwards until you notice they describe the *unrestricted* case: no narrowing
printed means no narrowing applies. Sunglasses narrows both ends (white mana,
red pips), Celestial Dawn narrows only the source, and the Orrery narrows
neither.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The five colours, as the payment code spells them.
COLOR_SYMBOLS: tuple[str, ...] = ("W", "U", "B", "R", "G")

_WORD_TO_SYMBOL = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

_REMINDER = re.compile(r"\([^)]*\)")


def _normalize(raw: str) -> str:
    return " ".join(_REMINDER.sub("", raw or "").strip().lower().split())


@dataclass(frozen=True)
class ManaSpending:
    """One seat's standing permission to spend mana as something else.

    ``fungible_colors`` is which mana the permission covers and ``as_colors``
    is what it may be spent as; **empty means every colour** in both, which is
    the unrestricted reading rather than the empty one — a sentence that prints
    no narrowing imposes none.

    ``others_colorless_only`` is the half that takes something away: every unit
    *outside* ``fungible_colors`` may pay only generic and ``{C}``, never a
    coloured pip. It is a field here rather than a table of its own because no
    card in the pool prints it alone, and a restriction with no permission in
    front of it would be a seat that cannot cast a coloured spell at all.
    """

    fungible_colors: tuple[str, ...] = ()
    as_colors: tuple[str, ...] = ()
    others_colorless_only: bool = False

    def covers(self, symbol: str) -> bool:
        """Whether a unit of *symbol* mana may be spent as another colour."""
        return not self.fungible_colors or symbol in self.fungible_colors

    def may_pay(self, symbol: str, pip: str) -> bool:
        """Whether a unit of *symbol* mana may pay a coloured *pip*.

        **"Only as though it were colorless mana" takes away the unit's own
        colour too**, which is the one line here worth reading twice. CR 106.6b
        makes an "only" clause a restriction rather than a permission, so under
        Celestial Dawn a Swamp's ``{B}`` does not pay ``{B}`` — it is colorless
        mana now, good for generic and for ``{C}`` and for nothing else. Written
        the other way round (equality first, as the obvious reading has it) the
        card would let a seat cast anything its own lands could have cast
        anyway, which is most of what the restriction exists to stop.
        """
        if self.covers(symbol):
            return symbol == pip or not self.as_colors or pip in self.as_colors
        if self.others_colorless_only:
            return False
        return symbol == pip


#: One printed sentence to the permission it grants — the *widening* half only.
#: The narrowing is read separately and folded in, because it is a sentence
#: about the mana these rows did **not** name.
_PERMISSIONS: tuple[re.Pattern[str], ...] = (
    # Chromatic Orrery. Neither end narrowed.
    re.compile(r"^you may spend mana as though it were mana of any color$"),
    # Celestial Dawn. The source is narrowed and the destination is not.
    re.compile(
        r"^you may spend (?P<from>white|blue|black|red|green) mana as though "
        r"it were mana of any color$"
    ),
    # Sunglasses of Urza. Both ends narrowed, and one row rather than twenty:
    # the two colour words are payload for the reason the noun is payload in
    # `global_statics.py`, so a card printing any other pair works with no code.
    re.compile(
        r"^you may spend (?P<from>white|blue|black|red|green) mana as though "
        r"it were (?P<to>white|blue|black|red|green) mana$"
    ),
)

#: "You may spend other mana **only** as though it were colorless mana."
#: (Celestial Dawn.) Matched on its own so the two sentences can be printed in
#: either order and read the same.
_RESTRICTION = re.compile(
    r"^you may spend other mana only as though it were colorless mana$"
)


def mana_spending_for(line: str) -> ManaSpending | None:
    """The spending permission one printed *line* grants, or None.

    A whole line, which may carry both sentences: the pool prints them together
    and the restriction is meaningless without the permission it qualifies, so
    they are read together and a line that is *only* the restriction returns
    None — an unsupported card rather than a seat forbidden every coloured pip.
    """
    normalized = _normalize(line).rstrip(".")
    if not normalized:
        return None
    permission: ManaSpending | None = None
    restricted = False
    for sentence in (part.strip() for part in normalized.split(".")):
        if not sentence:
            continue
        if _RESTRICTION.match(sentence) is not None:
            restricted = True
            continue
        for pattern in _PERMISSIONS:
            match = pattern.match(sentence)
            if match is None:
                continue
            groups = match.groupdict()
            source = _WORD_TO_SYMBOL.get(groups.get("from") or "")
            target = _WORD_TO_SYMBOL.get(groups.get("to") or "")
            permission = ManaSpending(
                fungible_colors=(source,) if source else (),
                as_colors=(target,) if target else (),
            )
            break
        else:
            # A sentence this table does not read. The whole line refuses,
            # because a permission half-read is a permission wrongly widened.
            return None
    if permission is None:
        return None
    return ManaSpending(
        fungible_colors=permission.fungible_colors,
        as_colors=permission.as_colors,
        others_colorless_only=restricted,
    )


def spending_permission_line(oracle_text: str) -> str | None:
    """The first line of *oracle_text* this module implements, or None.

    The support gate's reader. A permission that works but is claimed by
    nothing makes its card report unsupported, which is the false negative
    ``_derived_static_claims`` exists to close.
    """
    for line in (oracle_text or "").splitlines():
        if mana_spending_for(line) is not None:
            return line.strip()
    return None


def permissions_for_seat(game, seat: int) -> tuple[ManaSpending, ...]:
    """Every spending permission *seat* currently has, off the board.

    Derived rather than stored, so a source leaving ends its permission by no
    longer being in the list — the same model ``global_statics.py`` uses and for
    the same rule (CR 611.3a).
    """
    found: list[ManaSpending] = []
    for perm in game.controlled_by(seat):
        # ``effective_card``, not ``card``: a permanent that copies one of these
        # grants the permission, and one whose text has been changed no longer
        # grants what it no longer says.
        text = getattr(perm.effective_card, "oracle_text", "") or ""
        for line in text.splitlines():
            permission = mana_spending_for(line)
            if permission is not None:
                found.append(permission)
    return tuple(found)


__all__ = [
    "COLOR_SYMBOLS", "ManaSpending", "mana_spending_for",
    "permissions_for_seat", "spending_permission_line",
]
