"""Flashback (CR 702.34), the keyword the rules define as two static abilities.

CR 702.34a: *"Flashback appears on some instants and sorceries. It represents
two static abilities: one that functions while the card is in a player's
graveyard and another that functions while the card is on the stack.
'Flashback [cost]' means 'You may cast this card from your graveyard if the
resulting spell is an instant or sorcery spell by paying [cost] rather than
paying its mana cost' and 'If the flashback cost was paid, exile this card
instead of putting it anywhere else any time it would leave the stack.'
Casting a spell using its flashback ability follows the rules for paying
alternative costs in rules 601.2b and 601.2f–h."*

So flashback is three things this engine already had and had never joined:

* **a permission** to cast from a zone the rules alone do not open
  (CR 601.3, ``engine/cast_permissions.py``) — the card's own, derived from its
  text for as long as it sits in its owner's graveyard, exactly as Demonic
  Embrace's "You may cast this card from your graveyard by paying …" is;
* **an alternative cost that permission requires** (CR 118.9b: "an effect that
  allows you to cast a spell may require a certain alternative cost to be
  paid") — an :class:`~engine.alternative_costs.AlternativeCost`, which is
  where a cost that is not only mana already has its gate, its pickers and
  its payment. Its ``mana`` field is the one thing that class lacked: every
  alternative cost in the pool before this was paid in life, cards or
  permanents, and a flashback cost is paid in mana;
* **a destination** for the card as it leaves the stack
  (``mixins/stack/resolution._bin_spell_card``), wider than the "if that spell
  would be put into your graveyard" rider that seam already carried — see
  :func:`leaves_stack_to_exile`.

**The keyword line is a rewrite**, composed into
``oracle.expand_ability_lines`` beside cycling, buyback and kicker and for
their reason: every reader of a card's lines has to see the same sentence.
The rewritten sentence is the rule's own first one. The second has no
sentence to rewrite into, for the reason buyback's second half has none: it is
a fact about one *cast*, stamped on the stack object, and the card's text
cannot say whether it holds.

Before this module 27 Odyssey cards compiled ``supported`` on their other
line with the keyword dropped — buyback's old failure exactly: nothing
refused, nothing crashed, and Firebolt could never be cast from a graveyard.

**A card "has flashback"** (Tombfire: "exiles all cards with flashback") when
it prints the keyword *or was granted it* (Recoup). The second half is why
:func:`has_flashback` takes the game: a grant is a record with a duration,
and no reading of the card can see it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .alternative_costs import AlternativeCost
    from .cast_permissions import CastPermission

#: The keyword, as :attr:`AlternativeCost.keyword` carries it. One spelling,
#: because three readers compare against it: the cast path (the wider exile),
#: ``cost_modifiers`` (Catalyst Stone's "Flashback costs you pay cost {2}
#: less") and :func:`has_flashback`.
FLASHBACK = "flashback"

#: What a permission the keyword itself grants calls its source — the label a
#: log line and the browser's zone badge show where a granted permission names
#: the card that granted it.
FLASHBACK_SOURCE = "flashback"

#: The claim name the support gate and ``engine/grammar/registries.py`` use
#: for the rewritten sentence. Its own name beside the keyword, because it
#: answers a different question: this says a *line* is read, that says what a
#: *cost* is the price of.
FLASHBACK_CLAIM = "flashback"

#: "Flashback {4}{R}". The cost is a run of mana symbols taken from the printed
#: line so a coloured pip keeps its letter, as ``cycling._CYCLING_LINE`` takes
#: its own.
_FLASHBACK_LINE = re.compile(
    r"^flashback\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)

#: "Flashback—{1}{G}, Pay 3 life." (Torment prints it; nothing in Odyssey
#: does.) CR 702.34a's cost is any cost, and the printed form for one that is
#: not only mana puts it behind an em dash — the arrangement
#: ``cast_costs._BUYBACK_COST_LINE`` reads for buyback.
_FLASHBACK_COST_LINE = re.compile(
    r"^flashback\s*[—–-]\s*(?P<cost>.+)$", re.IGNORECASE
)

#: Any line that *is* a flashback keyword line, readable or not. What follows
#: the word has to open a cost — a mana symbol, or the dash a non-mana cost is
#: printed behind — so "Flashback costs you pay cost {2} less." (Catalyst
#: Stone) is not one: that is a static ability *about* flashback costs, read
#: in full by ``engine/cost_modifiers.py``. The same narrowing
#: ``cast_costs._BUYBACK_SHAPE`` learned from Memory Crystal.
_FLASHBACK_SHAPE = re.compile(r"^flashback\s*(?:[—–-]|\{)", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")

#: CR 702.34a's first static ability, in the rule's own words — less its "if
#: the resulting spell is an instant or sorcery spell", which is a condition
#: on the *cast* (asked by :func:`flashback_permission`) rather than part of
#: the price.
FLASHBACK_RULES_TEXT = (
    "You may cast this card from your graveyard by paying {cost} rather than "
    "paying its mana cost."
)

#: The rewritten sentence, as its readers match it: the whole line, lowercased
#: and without its period.
_FLASHBACK_SENTENCE = re.compile(
    r"^you may cast this card from your graveyard by paying (?P<cost>.+?) "
    r"rather than paying its mana cost$"
)

#: The cost of that sentence: an optional run of mana symbols, then whatever
#: clauses follow it. Either half may be absent and not both.
_COST_PARTS = re.compile(
    r"^(?P<mana>(?:\{[^{}]+\})+)?(?:(?:,\s*|\s+and\s+)?(?P<rest>[^{].*))?$"
)


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")


def _lowered_clauses(printed: str) -> str:
    """*printed* with the first letter of each clause lowercased — Magic
    capitalizes every item of a cost list ("{1}{G}, Pay 3 life") and the
    clause readers are lowercase. Only the first letter, so a printed subtype
    keeps its case (``cast_costs._lowered_clauses``' rule, and its split)."""
    from .cast_costs import _lowered_clauses as lowered

    return lowered(printed)


def flashback_cost_text(line: str) -> str | None:
    """The cost of one printed flashback keyword line, as the rewritten
    sentence spells it — or None when this module cannot charge it.

    A cost :func:`_read_cost` refuses returns None, which leaves
    :func:`unread_flashback_line` reporting the card rather than letting it
    compile on its other line with the keyword dropped.
    """
    stripped = _stripped(line)
    match = _FLASHBACK_LINE.match(stripped)
    if match is None:
        match = _FLASHBACK_COST_LINE.match(stripped)
    if match is None:
        return None
    cost = _lowered_clauses(match.group("cost").strip())
    return cost if _read_cost(cost.lower()) is not None else None


def _read_cost(cost: str) -> "AlternativeCost | None":
    """The alternative cost a (lowercased) flashback cost names, or None.

    Mana first, read as mana; whatever follows goes through
    ``alternative_costs._read_cost_clauses`` — the reader every other printed
    alternative cost goes through, so what "pay 3 life" or "sacrifice a land"
    charges is one answer whichever rule prints it, and the gate and the
    payment behind those fields already exist.

    **{X} is refused.** A flashback cost with an X in it announces a number
    the cast path has no channel for when the card's own mana cost prints
    none, and charging it as 0 is a spell cast for less than it prints.
    (A *granted* flashback cost equal to the card's mana cost may carry an X,
    because then the mana cost announced it — see :func:`granted_cost`.)
    """
    from .alternative_costs import AlternativeCost, _read_cost_clauses
    from .mana_payment import mana_cost_from_symbols

    parts = _COST_PARTS.match(cost.strip())
    if parts is None:
        return None
    mana, rest = parts.group("mana"), parts.group("rest")
    if not mana and not rest:
        return None
    if mana and mana_cost_from_symbols(mana) is None:
        # A hybrid, Phyrexian or {X} symbol: a cost this cannot express must
        # refuse its line rather than be charged as the part that was read.
        return None
    fields: dict = {}
    if rest:
        read = _read_cost_clauses(rest)
        if read is None:
            return None
        fields = read
    return AlternativeCost(
        FLASHBACK_RULES_TEXT.format(cost=cost).rstrip(".").lower(),
        mana=mana.upper() if mana else None,
        keyword=FLASHBACK,
        **fields,
    )


def is_flashback_line(line: str) -> bool:
    """Whether *line* is a printed flashback keyword line, whether or not
    :func:`expand_flashback_line` can read it."""
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip()
    return bool(stripped) and _FLASHBACK_SHAPE.match(stripped) is not None


def expand_flashback_line(line: str) -> str | None:
    """The CR 702.34a rules text for one printed flashback line, or None."""
    cost = flashback_cost_text(line)
    return None if cost is None else FLASHBACK_RULES_TEXT.format(cost=cost)


def expand_flashback_lines(oracle_text: str) -> str:
    """*oracle_text* with every flashback keyword line rewritten to its rules
    text.

    Text without one is returned unchanged, so applying this to every card
    costs a substring test. Applied by the compiler before any line is
    classified — beside ``expand_cycling_lines`` and for its reason: what the
    compiler reads and what every other reader of a card's lines reads must be
    one text.
    """
    if not oracle_text or "lashback" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_flashback_line(line) or line for line in oracle_text.split("\n")
    )


def unread_flashback_line(oracle_text: str) -> str | None:
    """A printed flashback-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run (``cycling.unread_cycling_line``'s arrangement): a line still reading
    as flashback by then is one :func:`flashback_cost_text` refused, and the
    card is unsupported naming it. Without this a flashback instant would
    report supported off its other line and silently drop the keyword — which
    is what all 27 of Odyssey's did before this module existed.
    """
    for line in (oracle_text or "").split("\n"):
        if is_flashback_line(line):
            return " ".join(_REMINDER.sub("", line).split()).strip()
    return None


def flashback_cost_for_line(line: str) -> "AlternativeCost | None":
    """The flashback cost the **rewritten** sentence *line* states, or None.

    Matched on the whole line, for ``alternative_cost_for_line``'s reason: a
    substring match is how a table comes to claim text it does not implement.
    """
    normalized = " ".join((line or "").strip().lower().split()).rstrip(".")
    match = _FLASHBACK_SENTENCE.match(normalized)
    if match is None:
        return None
    return _read_cost(match.group("cost"))


def flashback_claims_line(line: str) -> bool:
    """Whether this module reads *line* — the seam the support gate, the
    grammar's registry claim and the parse-coverage census all ask, so what is
    claimed and what is charged cannot drift."""
    return flashback_cost_for_line(line) is not None


@lru_cache(maxsize=None)
def _printed_cost(oracle_text: str) -> "AlternativeCost | None":
    if "lashback" not in (oracle_text or ""):
        return None
    for line in (oracle_text or "").split("\n"):
        rewritten = expand_flashback_line(line)
        if rewritten is not None:
            return flashback_cost_for_line(rewritten)
    return None


def printed_flashback_cost(card) -> "AlternativeCost | None":
    """The flashback cost *card* prints, or None.

    Read off the **printed** text through the rewrite, which is what a card in
    a graveyard still carries: the rewrite happens inside the compiler and
    nothing writes it back onto the card (``cast_costs.buyback_cost``'s
    arrangement). Cached on the text, because this is asked of every card in
    every graveyard on every poll.
    """
    return _printed_cost(getattr(card, "oracle_text", "") or "")


def granted_cost(card, cost: str) -> "AlternativeCost | None":
    """The flashback cost an effect grants *card*, or None.

    ``cost == "mana_cost"`` is "The flashback cost is equal to its mana cost"
    (Recoup), the only spelling the pool prints: the card's own printed mana
    cost, X included — an X the mana cost prints is one the cast announces, so
    it is charged as announced. A card with no mana cost (CR 118.6) has an
    unpayable flashback cost and is granted nothing a player could use; that
    is the cast path's refusal to make, so the cost is still returned.
    """
    from .alternative_costs import AlternativeCost

    if cost != "mana_cost":
        return None
    printed = (getattr(card, "mana_cost", "") or "").strip()
    return AlternativeCost(
        f"flashback {printed.lower() or 'with no mana cost'}",
        mana=printed.upper(), keyword=FLASHBACK,
    )


def is_flashback(cost) -> bool:
    """Whether *cost* — an ``AlternativeCost`` or None — is a flashback cost."""
    return cost is not None and getattr(cost, "keyword", None) == FLASHBACK


def flashback_permission(
    game, player_index: int, card, spell=None,
) -> "CastPermission | None":
    """The permission *card*'s own printed flashback gives *player_index*, or
    None.

    CR 702.34a's first static ability, derived on demand for the reason
    ``cast_permissions.self_permission_zone`` is: it functions for as long as
    the card is in the graveyard, so there is nothing to grant and nothing to
    expire.

    * **"your graveyard"** — the card must be in *player_index*'s own pile, by
      identity. A graveyard is an owner's zone (CR 404.1), so that is also the
      card's owner, and nobody else's flashback card is theirs to cast.
    * **"if the resulting spell is an instant or sorcery spell"** — asked of
      *spell*, what the card is being cast as.

    The permission carries the cost (CR 118.9b) and both exile riders: the
    graveyard one every bin site already routes on, and the wider one the
    stack object is stamped with (see :func:`leaves_stack_to_exile`).
    """
    from .cast_permissions import CastPermission
    from .search_filters import card_has_type

    spell = card if spell is None else spell
    cost = printed_flashback_cost(spell)
    if cost is None:
        return None
    if not (card_has_type(spell, "instant") or card_has_type(spell, "sorcery")):
        return None
    if not 0 <= player_index < len(game.players):
        return None
    if not any(entry is card for entry in game.players[player_index].graveyard):
        return None
    return CastPermission(
        player_index=player_index, zone="graveyard", mode="cast",
        cards=[card], duration=None, source_name=FLASHBACK_SOURCE,
        exile_instead=True, cost=cost,
    )


def has_flashback(card, *, game=None, owner_seat: int | None = None) -> bool:
    """Whether *card* has flashback: it prints the keyword, or an effect has
    granted it (Recoup's "gains flashback until end of turn").

    The printed half needs nothing but the card and is asked of the keyword
    line's *shape*, readable or not — a card whose flashback cost this engine
    cannot charge still has flashback. The granted half is a live record on
    ``Game.cast_permissions``, so it needs the game and whose graveyard the
    card is in; a caller that cannot say gets the printed answer.

    **A grant names a card by identity, and a deck repeats one immutable
    definition per copy**, so with two copies of one sorcery in one graveyard
    a grant over one of them answers yes for both. The grant itself is honest
    about it (``cast_permissions.consume`` retires one use); a reader counting
    cards with flashback over-counts by the second copy for the rest of that
    turn.
    """
    if any(
        is_flashback_line(line)
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    ):
        return True
    if game is None or owner_seat is None:
        return False
    for permission in getattr(game, "cast_permissions", ()):
        if not is_flashback(permission.cost) or permission.zone != "graveyard":
            continue
        if permission.zone_seat != owner_seat or not permission.cards:
            continue
        if any(entry is card for entry in permission.cards) and any(
            entry is card for entry in game.players[owner_seat].graveyard
        ):
            return True
    return False


def leaves_stack_to_exile(item) -> bool:
    """CR 702.34a's second static ability, asked of a stack object: "If the
    flashback cost was paid, exile this card instead of putting it **anywhere
    else** any time it would leave the stack."

    Wider than ``StackItem.exile_instead_of_graveyard``, which is the "if that
    spell would be put into your graveyard" rider and says nothing about a
    hand or a library: Memory Lapse puts a countered spell on top of its
    owner's library and Unsubstantiate returns one to its owner's hand, and a
    flashed-back spell goes to neither. Every site that would send a spell's
    card somewhere other than a graveyard asks this first; the ones that send
    it to a graveyard are already covered, because a flashback cast is stamped
    with the narrower rider too.

    False for a copy (CR 707.10: a copy is not cast, so no flashback cost was
    paid for it — and it has no card to exile in any case).
    """
    return bool(getattr(item, "flashback", False)) and not getattr(
        item, "is_copy", False
    )


__all__ = [
    "FLASHBACK",
    "FLASHBACK_CLAIM",
    "FLASHBACK_RULES_TEXT",
    "FLASHBACK_SOURCE",
    "expand_flashback_line",
    "expand_flashback_lines",
    "flashback_claims_line",
    "flashback_cost_for_line",
    "flashback_cost_text",
    "flashback_permission",
    "granted_cost",
    "has_flashback",
    "is_flashback",
    "is_flashback_line",
    "leaves_stack_to_exile",
    "printed_flashback_cost",
    "unread_flashback_line",
]
