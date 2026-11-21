"""Mana with a rider: an effect on the spell the mana is spent on (CR 106.6).

"{T}, Pay 2 life: Add {C}. If that mana is spent on an instant or sorcery
spell, that spell can't be countered." (Boseiju, Who Shelters All.) "{T}, Pay
3 life: Add {C}. If that mana is spent on a creature spell, it gains haste."
(Hall of the Bandit Lord.) CR 106.6 names three things a mana ability may say
about the mana it makes — a restriction on what it may be spent on, "an
additional effect that affects the spell or ability that mana is spent on", or
a delayed trigger — and ``engine/restricted_mana.py`` is the first of them.
This module is the second.

**The units travel in a bucket of their own.** The pool is a count per symbol,
so a {C} from Boseiju and a {C} from a Wastes are indistinguishable there, and
"if *that* mana is spent" is a question about one unit. A restricted bucket
already answers it — a payment draws on the buckets it is admitted to and
attributes what it spent to them (``restricted_mana.debit_restricted_mana``) —
so a rider's row in that table admits every payment
(``restricted_mana._any_payment``) and its bucket says afterwards whether its
units were taken. Spent first, by that attribution: the payer chooses which
mana pays (CR 601.2h), and a rider that only ever helps its spell is the mana
a payer spends on it.

**When it applies is the cast's payment.** Every unit of mana a cast pays is
paid inside ``PoolPaymentMixin._pay_cast_mana`` — the mana cost or what is
paid in its place, the additional costs, the taxes — so the cast measures
:func:`rider_units` across that call, and a rider bucket it drew on is a rider
the spell gets (Boseiju's 2004-12-01 ruling: "if the mana produced by Boseiju
is spent to cover any cost of the spell, even an additional cost such as a
splice cost"). Which spells a rider is about is asked of the spell as it is
cast (:func:`applying_riders`), and what it does is written where the spell's
other cast-time stamps are: "can't be countered" on the stack object
(``StackItem.uncounterable_by``, read by ``counter_conditions.cant_be_countered``;
a copy is not cast and is not given it, the ruling's second half), and haste on
the permanent the spell becomes, with no duration (Hall of the Bandit Lord's
2004-12-01 ruling: "The effect that grants haste doesn't wear off at end of
turn").

Mana spent on anything else — an activation, an upkeep cost, a spell the
rider is not about — is spent like any other mana, and its rider does nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .restricted_mana import is_kept_key, is_rider_key

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import Permanent

#: The ``StackItem.choices`` key a cast's applying riders ride on to the
#: permanent the spell becomes (``game_types.CHOICE_KEYS``).
MANA_RIDERS_SPENT = "mana_riders_spent"

UNCOUNTERABLE = "uncounterable"
HASTE = "haste"

#: Each rider key (``restricted_mana``'s row) to the card types of the spell it
#: is about and what it does to that spell.
_RIDERS: dict[str, tuple[tuple[str, ...], str]] = {
    "rider_uncounterable_instant_or_sorcery": (("instant", "sorcery"), UNCOUNTERABLE),
    "rider_haste_creature": (("creature",), HASTE),
}


_NOTES = {
    UNCOUNTERABLE: "if spent on {types} spell, that spell can't be countered",
    HASTE: "if spent on {types} spell, it gains haste",
}


def spend_note(key, restricted: str) -> str:
    """The log's parenthetical for mana made into the bucket *key*: a rider's
    own words, or *restricted* (the producer's "spendable only on …") for
    every other key, or "" for unrestricted mana."""
    if not key:
        return ""
    if is_kept_key(key):
        # Not a restriction at all: the mana pays for anything, and what the
        # sentence changed is when it empties (``restricted_mana``'s kept row).
        return " (kept until end of turn)"
    if not is_rider_key(key):
        return restricted
    types, effect = _RIDERS.get(str(key), ((), ""))
    article = "an" if types and types[0][:1] in "aeiou" else "a"
    return " (" + _NOTES.get(effect, "{types}").format(
        types=f"{article} {' or '.join(types)}"
    ) + ")"


def rider_units(player) -> dict[str, int]:
    """How many units each rider bucket of *player*'s holds right now."""
    return {
        str(key): sum(int(amount or 0) for amount in bucket.values())
        for key, bucket in (getattr(player, "restricted_mana", None) or {}).items()
        if is_rider_key(key)
    }


def riders_spent(before: dict[str, int], after: dict[str, int]) -> tuple[str, ...]:
    """The rider keys whose buckets a payment drew on: *before* against
    *after* (:func:`rider_units` both), sorted so the record is stable."""
    return tuple(sorted(
        key for key, held in before.items() if held > int(after.get(key, 0))
    ))


def applying_riders(game: "Game", card, caster_index: int, riders) -> tuple[str, ...]:
    """The riders in *riders* that are about the spell *card* — "spent on an
    instant or sorcery spell" asked of what is being cast (CR 205.2: a card has
    every type its line names)."""
    from .search_filters import card_has_type

    applying = []
    for key in riders or ():
        types, _effect = _RIDERS.get(str(key), ((), ""))
        if any(
            card_has_type(card, wanted, game=game, owner=caster_index)
            for wanted in types
        ):
            applying.append(str(key))
    return tuple(applying)


def _effect_of(key: str) -> str:
    return _RIDERS.get(str(key), ((), ""))[1]


def apply_cast_riders(game: "Game", item: "StackItem", riders) -> None:
    """Give the just-cast spell *item* what the riders it was paid with say.

    Called once, from the push of a cast spell (``cast_completion``), with the
    rider buckets its payment drew on. The ones about this spell are recorded
    on its choices for the permanent it becomes, and "can't be countered" is
    written on the stack object now.
    """
    # What the spell *is* (CR 612.1: a stack object read through its text
    # change, ``spell_text_card``), the question "spent on an instant or
    # sorcery spell" asks.
    from .text_changes import spell_text_card

    applying = applying_riders(game, spell_text_card(item), item.caster_index, riders)
    if not applying:
        return
    item.choices[MANA_RIDERS_SPENT] = applying
    if any(_effect_of(key) == UNCOUNTERABLE for key in applying):
        item.uncounterable_by = "the mana spent on it"
        game.log.append(
            f"{item.card.name} can't be countered (the mana spent on it, CR 106.6)"
        )


def apply_resolution_riders(game: "Game", permanent: "Permanent", choices) -> None:
    """Carry the riders a permanent spell was paid with onto the permanent it
    becomes: haste, from now on (layer 6, no duration)."""
    applying = (choices or {}).get(MANA_RIDERS_SPENT) or ()
    if not any(_effect_of(key) == HASTE for key in applying):
        return
    from .keywords import grant_keyword

    grant_keyword(permanent, "haste")
    game.log.append(
        f"{permanent.card.name} has haste (the mana spent on it, CR 106.6)"
    )


__all__ = [
    "HASTE",
    "MANA_RIDERS_SPENT",
    "UNCOUNTERABLE",
    "apply_cast_riders",
    "apply_resolution_riders",
    "applying_riders",
    "rider_units",
    "riders_spent",
    "spend_note",
]
