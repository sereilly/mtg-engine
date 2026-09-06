"""What one seat may not do for the rest of a turn (CR 601.3, CR 602.5).

"Until end of turn, target player can't cast instant or sorcery spells, and that
player can't activate abilities that aren't mana abilities." (Abeyance.)

**A record, not a table.** ``engine/cast_restrictions.py`` next door is
text-keyed: it reads a printed clause off a card and answers "may *this* spell be
cast right now", and every one of its rows is a sentence some permanent or spell
prints about itself. This module is the other half — a *resolved effect* said a
named seat may not do something until the turn ends, and there is no card text to
re-read at the moment the question is asked. ``engine/land_play_allowance.py``
draws exactly this line one permission over, and its two halves are the model
followed here: a derivation table for what a permanent says, and a per-turn seat
record for what an effect did.

Two records rather than one, because the two prohibitions are two rules and a
card may print either alone:

* **casting** is CR 601.3 — "no rule or effect prohibits that player from
  casting it" — and is narrowed by *card type*: Abeyance names instants and
  sorceries, and a card naming creatures is the same sentence with one word
  changed, so the types are payload;
* **activating** is CR 602.5 — "a player can't begin to activate an ability
  that's prohibited from being activated" — and its exception is not a type at
  all: a mana ability (CR 605.1a) is defined by what the ability *does*, so the
  record is a bare seat and the gate asks the engine's own mana-ability reader.

Folding them into one flag would make "can't cast instants" also stop every
activated ability, which is a different and much larger card.

**Where they are read** is the two gates CR names: ``mixins/stack/casting.py``
at CR 601.2 beside the board-scanned cast bans, and ``mixins/stack/activation.py``
at CR 602.5 beside the printed activation restrictions. A prohibition that is
recorded and not asked is an effect that resolves, logs itself, and changes
nothing — which is the failure this module exists to make impossible, so each
record has exactly one writer and one reader and they are named for each other.

Both are cleared at the turn boundary by :func:`clear_turn_spell_prohibitions`,
in the same sweep the land-play records use and for that sweep's stated reason:
a prohibition that outlived its turn is a seat that quietly stops playing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game


def forbid_casting_this_turn(game: "Game", seat: int, card_types) -> None:
    """*seat* can't cast spells of *card_types* for the rest of this turn.

    The types **accumulate** rather than replace: two Abeyances on one player
    are two prohibitions, and a second resolution that overwrote the first would
    make a narrower copy of the effect undo a wider one.
    """
    existing = set(game.spell_types_forbidden_this_turn.get(int(seat), ()))
    existing.update(str(card_type).lower() for card_type in card_types)
    game.spell_types_forbidden_this_turn[int(seat)] = tuple(sorted(existing))


def casting_forbidden_this_turn(game: "Game", seat: int, card) -> str | None:
    """The card type stopping *seat* casting *card*, or None.

    The type test is ``search_filters.card_has_type`` for the reason the board
    ban beside this one gives: a card has **every** type its line names
    (CR 205.2), so an artifact creature is stopped by a ban on either word.
    """
    from .search_filters import card_has_type

    for card_type in game.spell_types_forbidden_this_turn.get(int(seat), ()):
        if card_has_type(card, card_type):
            return card_type
    return None


def forbid_nonmana_activations_this_turn(game: "Game", seat: int) -> None:
    """*seat* can't activate anything but a mana ability this turn (CR 602.5)."""
    game.nonmana_activations_forbidden_this_turn.add(int(seat))


def nonmana_activations_forbidden(game: "Game", seat: int) -> bool:
    """Whether an effect has taken *seat*'s non-mana activations for this turn."""
    return int(seat) in game.nonmana_activations_forbidden_this_turn


def forbid_permanent_activations_this_turn(game: "Game", permanent) -> None:
    """*permanent*'s activated abilities can't be activated this turn
    (CR 602.5c, Interdict).

    Keyed by ``permanent_id`` rather than by the object, and that is the whole
    care this record needs: CR 400.7 stamps a fresh id on anything that returns,
    so a permanent that leaves and comes back is a new object the ban does not
    follow — which is the rule rather than a limitation. Storing the object
    itself would keep the ban on it across that boundary.

    A *permanent* record beside the seat one above rather than a second
    mechanism: both are turn-scoped prohibitions read by one gate and dropped by
    the one reset below, so neither can be forgotten on its own.
    """
    game.permanent_activations_forbidden_this_turn.add(int(permanent.permanent_id))


def permanent_activations_forbidden(game: "Game", permanent) -> bool:
    """Whether an effect has taken *permanent*'s activations for this turn."""
    return int(
        getattr(permanent, "permanent_id", -1)
    ) in game.permanent_activations_forbidden_this_turn


def clear_turn_spell_prohibitions(game: "Game") -> None:
    """Drop both records at the turn boundary.

    One function so the turn reset has one line and neither record can be
    forgotten on its own — the arrangement
    ``land_play_allowance.clear_turn_land_play_effects`` already makes, and for
    its reason: a prohibition that outlived its turn is a seat that silently
    stops casting, with no test able to say which turn it came from.
    """
    game.spell_types_forbidden_this_turn = {}
    game.nonmana_activations_forbidden_this_turn = set()
    game.permanent_activations_forbidden_this_turn = set()


__all__ = [
    "casting_forbidden_this_turn",
    "clear_turn_spell_prohibitions",
    "forbid_casting_this_turn",
    "forbid_nonmana_activations_this_turn",
    "forbid_permanent_activations_this_turn",
    "nonmana_activations_forbidden",
    "permanent_activations_forbidden",
]
