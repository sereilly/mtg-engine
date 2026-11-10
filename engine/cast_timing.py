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
spell's resolution writes that answer onto the permanent through the one writer
of a delayed mark (``destruction_events.mark_delayed_destruction``: CR 603.7g's
delayed triggered ability, controlled by the caster, its source the card), and
the cleanup step announces what is marked as that ability — it triggers as the
step begins and goes on the stack at CR 514.3a's moment, where it can be
answered (``phases/cleanup_step._cleanup_mark_firings``).
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


#: "You may cast this spell as though it had flash **if you pay {2} more to
#: cast it**." (Invasion's five: Breaking Wave, Ghitu Fire, Rout, Saproling
#: Symbiosis, Twilight's Call.) The permission above with a price on it, and
#: the price is the whole card: CR 601.3c lets the player *begin* to cast as
#: though the spell had flash because the additional cost will be paid, and a
#: reading that kept the permission and dropped the cost is a sorcery that is
#: simply an instant.
#:
#: Which is what these five were. :data:`_FLASH_PERMISSION` is searched for,
#: not matched whole, so it answered yes for this sentence and
#: :func:`casts_at_instant_speed` opened the instant window with nothing
#: charged — Rout was an instant-speed Wrath of God for its sorcery price, on
#: four cards reporting supported with every sentence claimed.
#:
#: The cost is payload (a card printing "{1}{U} more" is this sentence), read
#: whole, and only a **generic** cost is admitted: that is what the cast path's
#: generic tax can charge, and a coloured surcharge folded into it would be
#: payable with any land — cheaper than printed, the one direction a cost may
#: never move.
_FLASH_SURCHARGE = re.compile(
    r"^you may cast this spell as though it had flash if you pay "
    r"\{(?P<generic>\d+)\} more to cast it$"
)

#: Reminder text trailing a line ("(You may cast it any time you could cast an
#: instant.)"). The support gate hands this file printed lines as they are, so
#: the parenthetical is taken off here rather than made part of the pattern —
#: a printing without it is the same sentence.
_TRAILING_REMINDER = re.compile(r"\s*\([^()]*\)\s*$")


def flash_surcharge_line(line: str) -> int | None:
    """The generic mana *line* charges for casting its spell as though it had
    flash, or None when the line is not that sentence."""
    normalized = _TRAILING_REMINDER.sub("", _normalize(line)).rstrip(".")
    match = _FLASH_SURCHARGE.match(normalized)
    return int(match.group("generic")) if match is not None else None


def flash_surcharge(oracle_text: str) -> int | None:
    """What *oracle_text*'s own flash permission costs, or None if it prints
    none (or prints the free one)."""
    for raw_line in (oracle_text or "").splitlines():
        surcharge = flash_surcharge_line(raw_line)
        if surcharge is not None:
            return surcharge
    return None


def flash_surcharge_owed(game: "Game", seat: int, card) -> int:
    """The extra generic mana *seat* owes to cast *card* **right now**.

    CR 601.3c's additional cost, and it is owed exactly when the permission is
    being used: the spell is being cast at a time a sorcery could not be
    (CR 307.5a's test, :func:`a_sorcery_could_be_cast`), and nothing else is
    letting it be. So it is zero in the caster's own main phase with an empty
    stack — paying it there buys nothing and no player would — and zero when
    another effect already grants the timing (a flash grant covering the
    card's type, a board permission), because then the spell is not being cast
    "as though it had flash" by *this* sentence at all.

    Derived from the timing rather than asked as a choice: the two answers a
    prompt could collect are "pay, and cast now" and "do not, and do not cast",
    and the second is simply not casting. One reader for the cast path, the
    AI's affordability and the client's castable badge
    (``cost_modifiers.spell_cost_tax``), so the three cannot disagree about
    what the card costs at this moment.
    """
    surcharge = flash_surcharge(getattr(card, "oracle_text", "") or "")
    if not surcharge:
        return 0
    if not cast_by_its_own_flash_permission(game, seat, card):
        return 0
    return surcharge


def another_source_gives_instant_timing(game: "Game", seat: int, card) -> bool:
    """Whether something other than *card*'s own "you may cast this spell as
    though it had flash" lets *seat* cast it whenever an instant could be:
    its type or printed flash, Aluren's free cast, a resolved grant (Winding
    Canyons) or a permanent's static permission (Rootwater Shaman, Vernal
    Equinox) — :func:`casts_at_instant_speed`'s sources less the card's own
    sentence."""
    if card.primary_type == "instant" or card.has_flash:
        return True
    from .cast_permissions import board_free_cast

    return (
        board_free_cast(game, card) is not None
        or granted_flash_timing(game, seat, card)
        or board_flash_timing(game, seat, card)
    )


def cast_by_its_own_flash_permission(game: "Game", seat: int, card) -> bool:
    """Whether *seat* casting *card* now is casting it **by its own** "as
    though it had flash" sentence: a sorcery could not be cast now (CR 307.1's
    timing, :func:`a_sorcery_could_be_cast`) and nothing else lets the card be
    cast at instant speed (:func:`another_source_gives_instant_timing`).

    The question both of that sentence's riders ask, because each is the
    price of using it. Invasion's surcharge is owed only then
    (:func:`flash_surcharge_owed`), and Mirage's cleanup sacrifice happens only
    then: "The sacrifice occurs only if you cast it using its own ability. If
    you cast it using some other effect (for example, if another effect
    allowed you to cast it as though it had flash), then it won't be
    sacrificed" (the cycle's rulings, 2022-12-08). With both permissions
    open the player casts by whichever they choose, and the one with no
    price is the answer — derived rather than asked, as the surcharge is.
    """
    return not a_sorcery_could_be_cast(game, seat) and not another_source_gives_instant_timing(
        game, seat, card
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
#:
#: "**Any player** may cast **creature and enchantment** spells as though they
#: had flash." (Vernal Equinox.) Two more axes, and both are payload for this
#: table's standing reason. **Whose** spells: "you" is the permission's own
#: controller (CR 109.5) and "any player" is every seat, which is a scope the
#: reader answers rather than a second pattern. And **which** spells: a printed
#: union of card types, where an object with either type answers it (CR 205.2b),
#: read as a list so a card naming one class is the same row with one entry.
_STATIC_FLASH_PERMISSION = re.compile(
    r"^(?P<who>you|any player) may cast (?P<article>an? )?"
    r"(?P<klass>[a-z]+(?: and [a-z]+)*) spells?"
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


def _flashable_class(word: str) -> bool:
    """Whether a printed spell class is one :meth:`StaticFlashPermission.covers`
    can test: a card type above, or a **creature type** — "Any player may cast
    **Sliver** spells as though they had flash" (Quick Sliver).

    A creature type is asked of the creature-type catalog (``data/vocabulary``,
    never a list spelled here) and answered by the one reader of a card's
    creature types off the battlefield, ``object_creature_types``.
    """
    if word in _FLASHABLE_CLASSES:
        return True
    from .grammar.vocabulary import CREATURE_TYPES

    return word in CREATURE_TYPES


@dataclass(frozen=True)
class StaticFlashPermission:
    """What one printed static timing permission covers.

    ``card_classes`` are the printed words before "spells" — a **union**, since
    "creature and enchantment spells" (Vernal Equinox) names every spell that is
    either (CR 205.2b) and an object with both types answers it once.
    ``enchant_noun`` is the Aura clause it may narrow to, or None where the
    sentence named none. ``everyone`` is the printed seat word: False for "you"
    (CR 109.5, the permission's own controller) and True for "any player".
    """

    card_classes: tuple[str, ...]
    enchant_noun: str | None = None
    everyone: bool = False

    def covers(self, card, game: "Game | None" = None, seat: int | None = None) -> bool:
        """Whether *card* is one of the spells this permission names.

        A creature-type class ("Sliver spells", Quick Sliver) is a spell with
        that creature type (CR 205.3m), read through
        ``object_creature_types.card_creature_types`` — the card in the
        caster's hand, which has no layers (CR 613.1), told whose it is so an
        effect retyping a seat's cards off the battlefield (Conspiracy) is
        honoured. *game* and *seat* are optional for that reader's reason: a
        caller with neither gets the printed types.
        """
        from .object_creature_types import card_creature_types
        from .search_filters import card_has_type

        def _is(klass: str) -> bool:
            if klass in _FLASHABLE_CLASSES:
                return card_has_type(card, klass)
            return klass in card_creature_types(game, card, seat)

        if not any(_is(klass) for klass in self.card_classes):
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
    classes = tuple(match.group("klass").split(" and "))
    # **Every** word, not the first: a union with one unreadable half would
    # otherwise grant flash to the half this engine can test and silently drop
    # the other, which is a permission narrower than the card prints and
    # invisible from outside a game.
    if any(not _flashable_class(klass) for klass in classes):
        return None
    return StaticFlashPermission(
        card_classes=classes,
        enchant_noun=match.group("enchant"),
        everyone=match.group("who") == "any player",
    )


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

    "**You** may cast …" is the permission's own controller (CR 109.5), so such
    a permission is read off that seat's own permanents — a Shaman does not
    flash an opponent's Auras in.

    "**Any player** may cast …" (Vernal Equinox) is the other scope and is why
    the scan is over the whole board rather than over one battlefield: a
    permission that reaches every seat cannot be found by looking only at the
    asking seat's permanents, and the enchantment is a card whose whole point is
    that it helps the table.
    """
    for controller_index, permanent in game.permanents_with_controller():
        for permission in static_flash_permissions_on(permanent):
            if not permission.everyone and controller_index != seat:
                continue
            if permission.covers(card, game, seat):
                return True
    return False


def a_sorcery_could_be_cast(game: "Game", seat: int) -> bool:
    """CR 307.1's timing: *seat*'s own main phase, with an empty stack.

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
    a test of Mirage's five Auras, and `engine/derived_static_claims.py`'s support gate, ask
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
    # "…if you pay {2} more to cast it." (Invasion's five.) The other rider
    # this file enforces, claimed on the same all-or-nothing rule: the price is
    # charged by ``cost_modifiers.spell_cost_tax`` through
    # :func:`flash_surcharge_owed`, so the permission is never credited without
    # it.
    if flash_surcharge_line(line) is not None:
        return True
    return sacrifices_at_cleanup_if_cast_at_instant_speed(normalized)


def flash_permission_sentence(sentence: str) -> bool:
    """Whether one printed *sentence* is a flash permission this file
    implements **in full** — the coverage census's reader.

    The bare permission (Mirage's cycle prints its rider as a second sentence,
    which the census claims separately) or the priced one. Matched whole on
    purpose: the census used to ask :func:`grants_flash`, which *searches*, so
    "…as though it had flash if you pay {2} more to cast it" was claimed on its
    first nine words and the price was a dropped rider in the one instrument
    built to find them.
    """
    normalized = _TRAILING_REMINDER.sub("", _normalize(sentence)).rstrip(".")
    return (
        _FLASH_PERMISSION.fullmatch(normalized) is not None
        or _FLASH_SURCHARGE.match(normalized) is not None
    )


__all__ = [
    "CAST_AT_INSTANT_SPEED",
    "FlashGrant",
    "a_sorcery_could_be_cast",
    "another_source_gives_instant_timing",
    "cast_by_its_own_flash_permission",
    "expire_end_of_turn",
    "grant_flash_timing",
    "granted_flash_timing",
    "cast_permission_line",
    "flash_permission_sentence",
    "flash_surcharge",
    "flash_surcharge_line",
    "flash_surcharge_owed",
    "casts_at_instant_speed",
    "board_flash_timing",
    "grants_flash",
    "StaticFlashPermission",
    "static_flash_permission",
    "static_flash_permissions_on",
    "sacrifices_at_cleanup_if_cast_at_instant_speed",
]
