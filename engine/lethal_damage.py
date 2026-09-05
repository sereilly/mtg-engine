"""When lethal damage does **not** destroy a creature (CR 704.5g).

CR 704.5g is one sentence — a creature with toughness greater than 0 and damage
marked on it greater than or equal to that toughness is destroyed — and a
handful of printed cards narrow it. Ogre Enforcer is this pool's:

    This creature can't be destroyed by lethal damage unless lethal damage
    dealt by a **single source** is marked on it.

Two Ogre Enforcers each hit by a 3/3 have 3 damage marked apiece and neither
dies; one hit by a 5/5 does. The rule the sentence changes is a state-based
action, so there is nothing to compile: the clause produces no instruction and
no ability, and a card whose whole text is it would report unsupported however
well the exception worked. So this is a **derivation table** in the shape
``combat_restrictions.py`` and ``untap_restrictions.py`` already have — the
sweep reads it off the permanent's own text, and the support gate reads the
same function, which is what stops the two from drifting into a claim nothing
enforces.

**Only the 704.5g half.** CR 704.5h destroys a creature with any nonzero damage
from a deathtouch source, and that is not destruction "by lethal damage" — the
clause does not reach it, and Ogre Enforcer dies to a 1/1 deathtoucher exactly
as it would without the ability.

**Per-source totals come from the damage ledger**, because marked damage is one
number and this question is about several. ``engine/damage_ledger.py`` records
every event of the turn with the identity of what dealt it, which is the only
place the split survives; the ledger's lifetime is the turn and marked damage's
is the cleanup step, which are the same window from either end. The one place
they come apart is a regeneration mid-turn: it wipes the marked damage and not
the ledger, so a creature damaged, regenerated and damaged again can be read as
having taken more from one source than is marked on it. That can only matter
once the *total* marked damage is lethal again, since this narrowing is an
"unless" on top of 704.5g rather than a replacement for it — noted here rather
than papered over, because the honest reading is that the ledger is what the
engine has.
"""

from __future__ import annotations

import re

#: The one printed clause this file implements, as it is normalized. A regex
#: rather than a literal only so the leading subject can be either spelling the
#: engine's own normalizer produces.
_SINGLE_SOURCE_LETHAL = re.compile(
    r"^this creature can't be destroyed by lethal damage unless lethal damage "
    r"dealt by a single source is marked on it$"
)

#: What the support gate reports for a card carrying the clause.
CLAIM = "lethal_damage"


def single_source_lethal_line(line: str) -> bool:
    """Whether *line* is the clause above.

    One reader for the gate and the sweep, so what is claimed and what is
    enforced cannot drift — the pairing every text-keyed table in this engine
    keeps.
    """
    return _SINGLE_SOURCE_LETHAL.match(line.strip().lower().rstrip(".")) is not None


def requires_single_source_lethal(permanent) -> bool:
    """Whether *permanent* prints the clause.

    ``effective_card`` rather than the printed card: a Clone of an Ogre
    Enforcer has the sentence (CR 707.2) and an Ogre Enforcer whose text was
    changed does not.
    """
    text = getattr(permanent.effective_card, "oracle_text", "") or ""
    return any(single_source_lethal_line(line) for line in text.splitlines())


def _source_key(entry) -> object:
    """What counts as "a single source" for one ledger entry.

    The same three-step identity ``engine/damage_ledger.py`` writes, read back:
    a permanent is one object per time on the battlefield (CR 400.7), a spell is
    one object per **cast** — its ``CardDefinition`` is the card as printed and
    shared by every copy — and anything else falls back to the printed name,
    which is the most an event with neither can say about itself.
    """
    if entry.source_permanent_id is not None:
        return ("permanent", entry.source_permanent_id)
    if entry.source_cast is not None:
        return ("cast", id(entry.source_cast))
    return ("name", entry.source_name)


def largest_single_source_damage(game, permanent) -> int:
    """The most damage any one source has dealt *permanent* this turn."""
    from .damage_ledger import ledger

    totals: dict[object, int] = {}
    for entry in ledger(game).entries:
        if entry.recipient_permanent_id != permanent.permanent_id:
            continue
        key = _source_key(entry)
        totals[key] = totals.get(key, 0) + entry.amount
    return max(totals.values(), default=0)


def lethal_damage_destroys(game, permanent) -> bool:
    """CR 704.5g's answer for *permanent*, as its own text modifies it.

    True for every creature that does not print the clause, which is all but
    one card in this pool — the sweep asks this of every permanent it is about
    to bury, so the common answer has to be the cheap one.
    """
    if not requires_single_source_lethal(permanent):
        return True
    return largest_single_source_damage(game, permanent) >= permanent.effective_toughness


__all__ = [
    "CLAIM",
    "largest_single_source_damage",
    "lethal_damage_destroys",
    "requires_single_source_lethal",
    "single_source_lethal_line",
]
