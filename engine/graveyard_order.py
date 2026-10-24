"""Where a card sits in a graveyard, and what "above it" means (CR 404.1).

A graveyard is an **ordered** zone: CR 404.1 puts every card that arrives on
**top** of its owner's graveyard, and CR 404.2 keeps each graveyard as a single
face-up pile whose order a player "normally can't change" — which is what gives
that order a meaning at all. (CR 404.3 is the *other* graveyard-order rule, and
not this one: it is the tie-break for two or more cards arriving at the same
time, which the owner may then arrange. This module cited it for a decade of
sentences it does not say; the citation is corrected here and the sites that
copied it are listed in the W1G1 report.) Three cards in the pool print a sentence about it —
Death Spark and Krovikan Horror ("with a creature card **directly** above it"),
Nether Shadow ("with three or more creature cards above it") — and "above"
means *later in the list*, because a card put into a graveyard more recently is
appended.

One home for that reading, because two readers need it and they need it at
different moments: the intervening-if evaluator asks whether the ability may
fire at all (CR 603.4, checked once when the trigger would fire and again as it
resolves), and the fire site asks the same question a card at a time. A second
copy of the arithmetic is how "above" comes to mean two different things.

**Positions, not a card.** Every function here answers with graveyard *indices*
rather than with the card, and that is not scaffolding. A graveyard holds
``CardDefinition`` objects and ``load_cards`` dedupes by ``oracle_id``, so two
copies of one card in one graveyard are the **same Python object** — a caller
handed only the card cannot say which copy satisfied the clause, and an identity
filter over the list removes both. ``phases/upkeep_step._graveyard_return_candidates``
carries the same index for the same reason, and documents the five cards that
went missing before it did.
"""

from __future__ import annotations

from typing import Any

from .layer_bridge import printed_shape


def is_printed_type(card: Any, wanted: str) -> bool:
    """Whether *card* is printed with the *wanted* card type.

    Through ``printed_shape`` rather than ``primary_type``: CR 205.2a gives a
    card **every** type printed on it, and the collapsed word makes "Artifact
    Creature — Construct" a creature and not an artifact. A graveyard is exactly
    where that matters — nothing there is a permanent, so the layers cannot be
    asked and the printed line is the whole answer.
    """
    types, _subtypes = printed_shape(card)
    return wanted in types


def cards_above(graveyard: list, index: int) -> list:
    """The cards above the one at *index* — CR 404.1's order, later is higher."""
    return graveyard[index + 1:]


def satisfies_above(graveyard: list, index: int, spec: dict) -> bool:
    """Whether the card at *index* has what *spec* says above it.

    *spec* is the lowered ``self_in_graveyard_with_cards_above`` payload:
    ``card_type``, ``count``, ``op`` ("eq"/"ge") and ``directly``.

    "Directly above" is a different question from a count of one, not a
    narrowing of it, which is why it is its own branch: a graveyard holding a
    land on top of the card and a creature above that has one creature card
    above it and nothing directly above it. Death Spark and Nether Shadow
    disagree about exactly that board.
    """
    wanted_type = str(spec.get("card_type", "creature"))
    above = cards_above(graveyard, index)
    if spec.get("directly"):
        return bool(above) and is_printed_type(above[0], wanted_type)
    count = sum(1 for card in above if is_printed_type(card, wanted_type))
    wanted = int(spec.get("count", 1))
    return count >= wanted if spec.get("op") == "ge" else count == wanted


def positions_satisfying(graveyard: list, card: Any, spec: dict) -> list[int]:
    """Every index of *graveyard* holding *card* whose position satisfies *spec*.

    Several, in principle: two copies of one card are the same object, and the
    one lower in the pile may qualify while the one on top does not. The list is
    the honest answer — one ability per card in the zone (CR 113.6b), so a
    caller that fires per position fires the right number of times, and a caller
    that only needs a yes/no can ask whether it is empty.
    """
    return [
        index
        for index, held in enumerate(graveyard)
        if held is card and satisfies_above(graveyard, index, spec)
    ]


def positions_named(graveyard: list, spec: dict) -> list[int]:
    """The graveyard indices "the top <n> <described> cards" names, or ``[]``.

    *spec* is the payload ``grammar.graveyard_position_payload_for`` builds:
    ``count``, ``position`` ("top"/"bottom") and an optional ``filter``.

    "Top" is the **end** of the list: CR 404.1 puts an arriving card on top and
    this engine appends, so the most recently added card is the last element.

    **The scan is what makes the narrowing positional.** "The top creature card
    of your graveyard" (Necratog, Zombie Scavengers, Barrow Ghoul, Circling
    Vultures) is the creature card *nearest the top*, not "the top card, if it
    happens to be a creature" — so the walk starts at the named end and takes
    the first *count* cards that answer the filter, skipping the ones that do
    not. Read the other way Necratog would be unactivatable with a Mountain on
    top of a graveyard full of creatures, which is a strictly worse card than
    the one printed.

    All or nothing. A pile holding fewer matching cards than *count* returns
    ``[]`` rather than a short list, because CR 118.3 lets a cost be paid only
    in full — and the same answer serves the *effect* form (Phyrexian Furnace),
    where an empty pile simply exiles nothing.

    **Indices in scan order**, which is the module's stated reason for answering
    with positions at all: two copies of one card in one graveyard are the same
    Python object, so a caller handed the card cannot say which copy it named,
    and an identity filter over the list would remove both. A caller removing
    several must delete from the highest index down.
    """
    from .handlers._filters import _card_matches_filter

    described = spec.get("filter")
    order = (
        range(len(graveyard) - 1, -1, -1)
        if spec.get("position", "top") == "top"
        else range(len(graveyard))
    )
    wanted = max(int(spec.get("count", 1) or 1), 0)
    found: list[int] = []
    for index in order:
        if described and not _card_matches_filter(graveyard[index], dict(described)):
            continue
        found.append(index)
        if len(found) >= wanted:
            break
    return found if len(found) >= wanted else []


# ---------------------------------------------------------------------------
# When a card got there (CR 613.7d)
# ---------------------------------------------------------------------------


def _held_arrivals(player: Any, pile: list) -> list:
    """``player.graveyard_arrivals`` held to *pile*: one ``(card, stamp)`` per
    position, every stamp an ``int``.

    **Removal never reorders** (CR 404.2: the order "normally can't change"),
    and every arrival goes on top (CR 404.1, the funnel's ``append``), so the
    pile is always a subsequence of the arrival record. The walk matches each
    card with the earliest record *of that object* after the last one it
    matched; a record nothing matches is a card that has left since, and is
    dropped.

    A card with no record was put there by writing the list directly (a test,
    the Debug Menu's state injection) rather than through
    ``Game.put_card_into_graveyard``. It is stamped **now**, the first time
    anything asks — the moment the engine first sees it there, as close to
    "when it entered the zone" as a direct write leaves anyone able to say —
    and the caller keeps the stamp, so every later read gives the same answer.

    The one thing a subsequence cannot say: two copies of one card are the
    **same** ``CardDefinition`` (this module's docstring), so with two records
    of it and one copy left, which copy left is not in the list. The earlier
    stamp is kept. It matters only to a timestamp ordering *between* the two
    arrivals, which no printed pair of effects in the pool asks.
    """
    from .continuous import next_timestamp

    records = list(getattr(player, "graveyard_arrivals", None) or ())
    held: list = []
    cursor = 0
    for card in pile:
        found = next(
            (
                position for position in range(cursor, len(records))
                if records[position][0] is card
            ),
            None,
        )
        if found is None:
            held.append((card, next_timestamp()))
            continue
        held.append(records[found])
        cursor = found + 1
    return held


def record_graveyard_arrival(player: Any, card: Any) -> int:
    """Stamp *card*, just put on top of *player*'s graveyard (CR 613.7d), and
    return the stamp.

    Called by ``Game.put_card_into_graveyard`` after its append — the one road
    every arrival takes. The record is held to the pile **below** the new card
    first, so a card that left and came back is a new object with a new stamp
    (CR 400.7) rather than its old record matched again.
    """
    from .continuous import next_timestamp

    held = _held_arrivals(player, player.graveyard[:-1])
    stamp = next_timestamp()
    held.append((card, stamp))
    player.graveyard_arrivals = held
    return stamp


def graveyard_arrival_stamps(player: Any) -> list[int]:
    """Each position of *player*'s graveyard with its CR 613.7d timestamp, in
    pile order (bottom first).

    Asked by the recompute (``LordBuffsMixin._recalculate_lord_buffs``) for the
    statics that function from a graveyard; it keeps the record in step with
    the pile as it reads, which is why it writes it back.
    """
    held = _held_arrivals(player, player.graveyard)
    player.graveyard_arrivals = held
    return [int(stamp) for _card, stamp in held]
