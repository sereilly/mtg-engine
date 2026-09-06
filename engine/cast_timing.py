"""Printed permissions that widen *when* a card may be cast (CR 113.6b).

Two neighbours, and this file is neither of them. ``engine/cast_restrictions.py``
is the mirror: that table holds "Cast this spell only during …", a gate that
*narrows* legal timing, and its failure mode is a card cast too often. This one
holds the sentences that widen it, whose failure mode is the opposite — a card
that could have been cast and was refused, which breaks no rule and fails no
test, because a spell nobody can cast simply never appears.
``engine/cast_permissions.py`` is a different axis again: *where* a spell may be
cast **from** (CR 601.3's zones), which is state on the game rather than text on
the card.

**Mirage's five-card cycle is what this file is for.** Armor of Thorns, Grave
Servitude, Lightning Reflexes, Soar and Ward of Lights each print exactly:

    You may cast this spell as though it had flash. If you cast it any time a
    sorcery couldn't have been cast, the controller of the permanent it becomes
    sacrifices it at the beginning of the next cleanup step.

Two effects in one sentence, and the second is why the first cannot be
implemented alone. A permission dropped costs a card its trick; a **penalty**
dropped makes the card strictly better than the one printed, which is the
silent-wrongness this repo does not ship. So both halves are read here, off the
same line, and a card printing the permission without the rider it cannot
implement leaves the line unclaimed rather than half-claimed.

``CardDefinition.has_flash`` is the printed keyword and stays what it is. This
is the granted form its docstring predicted: "a permission about a card outside
the battlefield, so it will arrive as its own seam". :func:`casts_at_instant_speed`
is that seam, and it is the **one** question the timing gates ask — the web
layer had the printed half written out twice (``web/actions.py`` and
``web/state_view.py``), and a third spelling for the granted half would have
been the second copy this codebase keeps finding on the wrong side of.

The rider is enforced across three places, none of which knows the sentence:
the cast path records whether a sorcery could have been cast
(:data:`CAST_AT_INSTANT_SPEED`, a ``StackItem.choices`` key), the permanent
spell's resolution copies that answer onto the permanent, and the cleanup step
sacrifices what is marked. CR 514.1's cleanup step is where the rule puts it,
and a sweep there rather than a delayed trigger for the reason every other
sweep in this engine exists: there is no single fire site, and a permanent can
reach the battlefield marked by more than one route.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game

#: The metadata / ``StackItem.choices`` key recording that a spell was cast at a
#: time a sorcery could not have been. Stamped only for a card whose text asks —
#: a flag every cast wrote would be a record nothing reads on 1,868 cards.
CAST_AT_INSTANT_SPEED = "cast_at_instant_speed"

#: "You may cast this spell as though it had flash."
_FLASH_PERMISSION = re.compile(
    r"you may cast this spell as though it had flash"
)

#: The rider that always accompanies it in this cycle. Matched as its own
#: pattern rather than as a tail of the one above because the two are separate
#: effects with separate enforcement — but see :func:`cast_permission_line`,
#: which refuses to claim the permission without it.
_CLEANUP_SACRIFICE_RIDER = re.compile(
    r"if you cast it any time a sorcery couldn't have been cast, the "
    r"controller of the permanent it becomes sacrifices it at the beginning "
    r"of the next cleanup step"
)


@dataclass
class FlashGrant:
    """"You may cast creature spells this turn as though they had flash."
    (Winding Canyons.) CR 611.1's continuous effect over CR 702.8a's timing
    ("you may play this card any time you could cast an instant").

    Its own record rather than a :class:`~engine.cast_permissions.CastPermission`
    with a flag, because the two answer different questions and this module's
    docstring already draws the line: that one says **where** a spell may be
    cast from (CR 601.3's zones) and is asked by the cast path before it will
    look outside the hand; this one says **when**, and is asked by the two
    timing gates. Folded together, a timing grant would have to name a zone it
    does not have and would be returned by ``permission_for`` to a caller
    asking about cost waivers.

    ``card_types`` is which spells it covers, by printed card type — the
    rules the grant overrides are the per-type timing ones (CR 302.1 for a
    creature, CR 307.1 for a sorcery). Empty would be every spell, which is
    a strictly different card from the one that prints a class.
    """

    player_index: int
    card_types: tuple[str, ...]
    duration: str | None = "end_of_turn"
    source_name: str = ""


def grant_flash_timing(
    game: "Game",
    player_index: int,
    card_types: tuple[str, ...],
    *,
    duration: str | None = "end_of_turn",
    source_name: str = "",
) -> FlashGrant:
    """Record that *player_index* may cast those spells at instant speed."""
    grant = FlashGrant(
        player_index=player_index,
        card_types=tuple(card_types),
        duration=duration,
        source_name=source_name,
    )
    game.flash_timing_grants.append(grant)
    return grant


def expire_end_of_turn(game: "Game") -> None:
    """CR 514.2: a "this turn" timing grant ends at cleanup.

    Beside ``cast_permissions.expire_end_of_turn`` in the cleanup step and
    swept the same way, because both are CR 611.2a durations on a permission —
    what differs is only which question the permission answers.
    """
    # Slice assignment rather than rebinding, for the reason the zone sweep
    # gives: a caller may be holding the same list.
    game.flash_timing_grants[:] = [
        grant for grant in game.flash_timing_grants
        if grant.duration != "end_of_turn"
    ]


def granted_flash_timing(game: "Game", seat: int, card) -> bool:
    """Whether a live grant lets *seat* cast *card* at instant speed."""
    return any(
        grant.player_index == seat
        and card.primary_type in grant.card_types
        for grant in getattr(game, "flash_timing_grants", ())
    )


# ---------------------------------------------------------------------------
# The *static* half: a permanent that widens the timing of other players' spells
# ---------------------------------------------------------------------------

#: "You may cast Aura spells with enchant creature as though they had flash."
#: (Rootwater Shaman.) A static ability of a permanent on the battlefield, which
#: is the third source of flash timing and the one neither half above could
#: hold: :class:`FlashGrant` is a record an effect *resolved* and left behind,
#: and :func:`grants_flash` reads a card's permission about **itself**. This one
#: is neither — it is derived from a permanent's own text on every question, the
#: same model ``engine/cost_modifiers.py`` and ``engine/cast_restrictions.py``
#: use, so a permanent leaving the battlefield takes the permission with it and
#: there is nothing to undo.
#:
#: The spell class is payload rather than part of the pattern: "creature spells"
#: is the same sentence with a different word, so a card printing it needs no
#: code. The Aura's enchant clause is the one *quality* read, because it is the
#: one this engine can test — ``auras.aura_enchants`` is the reader the cast
#: gate and the picker already share. A sentence naming any other quality
#: refuses here rather than being admitted with the narrowing dropped, which
#: would let a Shaman flash in an Aura that enchants a land.
_STATIC_FLASH_PERMISSION = re.compile(
    r"^you may cast (?P<article>an? )?(?P<klass>[a-z]+) spells?"
    r"(?: with enchant (?P<enchant>[a-z]+))?"
    r" as though (?:it|they) had flash$"
)

#: The spell classes the matcher below can test. A card type is asked of
#: ``search_filters.card_has_type`` (CR 205.2b) and "aura" of the same printed
#: line, which is where a card outside the battlefield keeps its subtypes
#: (CR 613.1 does not reach it). A word outside this set leaves the sentence
#: unclaimed, so the card is reported unsupported rather than granting flash to
#: a class nothing narrows.
_FLASHABLE_CLASSES: frozenset[str] = frozenset(
    {"artifact", "aura", "creature", "enchantment", "instant", "sorcery"}
)


@dataclass(frozen=True)
class StaticFlashPermission:
    """What one printed static timing permission covers.

    ``card_class`` is the printed word before "spells"; ``enchant_noun`` is the
    Aura clause it may narrow to, or None where the sentence named none.
    """

    card_class: str
    enchant_noun: str | None = None

    def covers(self, card) -> bool:
        """Whether *card* is one of the spells this permission names."""
        from .search_filters import card_has_type

        if not card_has_type(card, self.card_class):
            return False
        if self.enchant_noun is None:
            return True
        from .auras import aura_enchants

        return aura_enchants(getattr(card, "oracle_text", "") or "", self.enchant_noun)


def static_flash_permission(line: str) -> StaticFlashPermission | None:
    """The timing permission one printed *line* grants, or None.

    Read by the support gate **and** by :func:`board_flash_timing`, so what the
    engine claims and what it carries out are one table — the arrangement
    ``engine/activation_restrictions.py`` is the model for.
    """
    match = _STATIC_FLASH_PERMISSION.match(_normalize(line).rstrip("."))
    if match is None:
        return None
    klass = match.group("klass")
    if klass not in _FLASHABLE_CLASSES:
        return None
    return StaticFlashPermission(card_class=klass, enchant_noun=match.group("enchant"))


def static_flash_permissions_on(permanent) -> list[StaticFlashPermission]:
    """Every timing permission *permanent* currently grants.

    Off ``effective_card``, never the printed card: a text change (CR 612.1) or
    a copy (CR 707.2) rewrites what the permanent says before anything reads it.
    """
    card = getattr(permanent, "effective_card", None) or getattr(permanent, "card", None)
    text = getattr(card, "oracle_text", "") or ""
    return [
        found
        for line in text.splitlines()
        if (found := static_flash_permission(line)) is not None
    ]


def board_flash_timing(game: "Game", seat: int, card) -> bool:
    """Whether a permanent *seat* controls lets them cast *card* at instant
    speed.

    "**You** may cast …" is the permission's own controller (CR 109.5), so the
    scan is over that seat's permanents rather than over the whole board — a
    Shaman does not flash an opponent's Auras in.
    """
    for permanent in game.controlled_by(seat):
        for permission in static_flash_permissions_on(permanent):
            if permission.covers(card):
                return True
    return False


def a_sorcery_could_be_cast(game: "Game", seat: int) -> bool:
    """CR 601.3d's timing: *seat*'s own main phase, with an empty stack.

    One rule, two readers. ``activation_restrictions`` asks it of "Activate only
    as a sorcery" and the cast path asks it of "any time a sorcery couldn't have
    been cast" — the same sentence in the CR, so the same function, because two
    spellings of one timing rule is how the two come to disagree about a turn.

    Asked of the state *before* the spell being announced reaches the stack,
    which is the only moment it can be asked: by resolution the stack has emptied
    down to this spell and the step may have moved on.
    """
    return (
        game.active_player_index == seat
        and game.current_turn_phase in ("precombat_main", "postcombat_main")
        and not game.stack
    )


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower()


def grants_flash(oracle_text: str) -> bool:
    """Whether *oracle_text* gives its own spell flash timing (CR 702.8b)."""
    return _FLASH_PERMISSION.search(_normalize(oracle_text)) is not None


def sacrifices_at_cleanup_if_cast_at_instant_speed(oracle_text: str) -> bool:
    """Whether the permanent this spell becomes is sacrificed at the next
    cleanup step when the spell was cast at instant speed."""
    return _CLEANUP_SACRIFICE_RIDER.search(_normalize(oracle_text)) is not None


def casts_at_instant_speed(card, game: "Game | None" = None, seat: int | None = None) -> bool:
    """Whether *card* may be cast whenever an instant could be (CR 601.3d).

    The one question both timing gates ask. An instant by type, a card with
    printed flash, a card whose own text grants it, or a **grant on the game**
    covering its type — four sources, one answer, so a card cannot be castable
    in the picker and refused by the action or the other way round.

    *game* and *seat* are what the fourth source needs, and every caller inside
    a game has them: a permission granted by an effect (Winding Canyons) is
    state rather than text, so no reading of the card alone can see it. They
    are optional because the question is legitimately asked *of a card* too —
    a test of Mirage's five Auras, and `engine/oracle.py`'s support gate, ask
    whether the printed text grants flash and have no board to ask about. A
    caller that has one and does not pass it gets the printed half, which is
    the pre-grant answer and never a wider one.
    """
    if (
        card.primary_type == "instant"
        or card.has_flash
        or grants_flash(card.oracle_text or "")
    ):
        return True
    if game is None or seat is None:
        return False
    # **Four** sources with a board, not two, and two waves added one each: a
    # resolved grant (Winding Canyons), a **static** permission derived from a
    # permanent's own text (Rootwater Shaman), and Aluren's, which is one of the
    # three permissions its single printed sentence states. Asked here rather
    # than at each gate, because this function is the one question both timing
    # gates ask and a source added at one of them would be invisible to the
    # other — which is why two independent groups could each add one here
    # without either noticing the other.
    #
    # Aluren's is asked of ``cast_permissions.board_free_cast``'s own reader
    # rather than matched again: a second copy of the phrase would be free to
    # drift, and the direction it drifts is a spell castable for free in a
    # window the card never opened, or one the card opened and this gate
    # refuses.
    from .cast_permissions import board_free_cast

    if board_free_cast(game, card) is not None:
        return True
    return granted_flash_timing(game, seat, card) or board_flash_timing(
        game, seat, card
    )


def cast_permission_line(line: str) -> bool:
    """Whether one printed line is a casting permission this file implements.

    The support gate's reader, and it is deliberately **all or nothing**: the
    permission is claimed only when the rider printed beside it is also one the
    engine enforces. A line claimed for its first sentence alone would ship
    five Auras that can be flashed in and never sacrificed — a strictly better
    card than the one printed, which is exactly the failure the whole-line rule
    in this repo exists to prevent.
    """
    normalized = _normalize(line).rstrip(".")
    if not grants_flash(normalized):
        return False
    return sacrifices_at_cleanup_if_cast_at_instant_speed(normalized)


__all__ = [
    "CAST_AT_INSTANT_SPEED",
    "FlashGrant",
    "a_sorcery_could_be_cast",
    "expire_end_of_turn",
    "grant_flash_timing",
    "granted_flash_timing",
    "cast_permission_line",
    "casts_at_instant_speed",
    "board_flash_timing",
    "grants_flash",
    "StaticFlashPermission",
    "static_flash_permission",
    "static_flash_permissions_on",
    "sacrifices_at_cleanup_if_cast_at_instant_speed",
]
