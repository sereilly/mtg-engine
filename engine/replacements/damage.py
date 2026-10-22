"""Damage as it is dealt, and what it does to a life total (CR 120.4b-c): how
much of it there is.

The interceptors that change an event's **amount** — a cap on what a source
class may deal (Forethought Amulet's instant-or-sorcery cap, the "4 or more"
cap of any source), a spell's damage shifted up or down by a printed delta, a
multiplier and its turn-long and combat-long doublers, the next damage from a
chosen source doubled — and the one that floors a result instead (Ali from
Cairo: the damage is dealt in full, only the life lost is capped). The
source-class matchers they share with the redirects (``_source_answers_class``)
are here, and so is the Desert shield (Camel, Desert Nomads): CR 615
prevention printed as such, registered in this registry for its text-keyed
guard.

Split out of ``replacements.py`` at the 2,000-line cap's split round. Damage
sent to **another recipient** is ``redirects.py``'s; damage replaced by an
event that is not damage at all is ``damage_substitutions.py``'s.
"""

from __future__ import annotations

import re

from ..effect_ordering import CAP, MULTIPLIER
from ..damage_redirects import _is_permanent
from ..next_damage import (DAMAGE_DOUBLED_NEXT, armed_for_event,
                           spend_for_event)
from .registry import (
    COMBAT_DAMAGE_DOUBLER, DAMAGE_MULTIPLIER, DAMAGE_SOURCE_CAP,
    DAMAGE_SOURCE_DELTA, LIFE_FLOOR, NEXT_DAMAGE_DOUBLED, SOURCE_TYPE_SHIELD,
    TURN_DAMAGE_BECOMES, ReplacementOutcome, replacement_effect,
)


DAMAGE_LIFE_FLOOR_TEXT = (
    "damage that would reduce your life total to less than 1 reduces it to 1 instead"
)


#: "**If you control a creature,** damage that would reduce your life total to
#: less than 1 reduces it to 1 instead." (Worship.) Ali from Cairo's sentence
#: with CR 611.2's condition in front of it, and the condition is **payload**
#: for the reason every parameter in this file is: a card printing another noun
#: phrase in the same clause is the same effect.
#:
#: Anchored at both ends, so the condition cannot be read as optional decoration
#: on a line that does not carry one — and read as a *line* rather than through
#: ``_player_controls_text``, which is a substring test. That distinction is the
#: whole card: Worship's text contains Ali from Cairo's constant, so a substring
#: reader answers yes for a Worship on an empty board and floors the life total
#: of a player who controls nothing, which is precisely the game Worship is
#: printed not to give.
_DAMAGE_LIFE_FLOOR_RE = re.compile(
    r"^(?:if you control (?P<condition>[^,]+), )?"
    + re.escape(DAMAGE_LIFE_FLOOR_TEXT)
    + r"$"
)


def damage_life_floor_condition(line: str) -> dict | None:
    """What *line* requires before it floors its controller's life, or None when
    it is not that line at all.

    ``{}`` — empty and therefore falsy, but **not** None — is the unconditional
    printing (Ali from Cairo, Sustaining Spirit). Callers must test ``is None``.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is floored and what is claimed
    cannot drift.
    """
    match = _DAMAGE_LIFE_FLOOR_RE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    phrase = match.group("condition")
    if phrase is None:
        return {}
    # The grammar's own noun-phrase reader, lazily imported because the
    # grammar's parse claim imports this module. A phrase it cannot read
    # answers None, which leaves the card unsupported rather than flooring
    # unconditionally — a condition dropped is an effect strictly wider than
    # the card prints.
    from ..grammar import subject_filter_payload

    filt = subject_filter_payload(phrase)
    if filt is None:
        return None
    return {"condition": {"kind": "controls", "who": "you", "filter": filt}}


def _life_floor_holder(game, player):
    """The permanent whose printed floor covers *player* right now, or None.

    Scanned over the seat's own battlefield, because the printed sentence says
    "**your** life total" (CR 109.5): an opponent's Worship does nothing for the
    player being burned. Through the control seam rather than a battlefield
    list, so a Worship somebody has taken control of floors *them*.

    Rechecked on every event rather than latched, for ``_condition_holds``'
    reason one file over: the creature the clause counts may leave, and a floor
    that outlived its condition is one the card does not print.
    """
    seat = game.players.index(player) if player in game.players else None
    if seat is None:
        return None
    from ..static_bonuses import conditional_static_holds

    for permanent in game.controlled_by(seat):
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            described = damage_life_floor_condition(line)
            if described is None:
                continue
            condition = described.get("condition")
            if condition is not None and not conditional_static_holds(
                game, seat, permanent, condition
            ):
                continue
            return permanent
    return None


def _floored_amount(game, payload: dict) -> int | None:
    """How much life this damage would still cost once the floor applies, or
    None when the floor has nothing to do. Shared by the predicate and the
    interceptor so "does the floor apply" and "what does it floor to" have one
    answer."""
    recipient = payload["recipient"]
    amount = payload["amount"]
    if amount <= 0 or not hasattr(recipient, "life"):
        return None
    if _life_floor_holder(game, recipient) is None:
        return None
    floor_amount = max(0, recipient.life - 1)
    return None if floor_amount >= amount else floor_amount


def _applies_life_floor(game, payload: dict) -> bool:
    return _floored_amount(game, payload) is not None


@replacement_effect("life_loss", LIFE_FLOOR, applies=_applies_life_floor)
def _floor_life_at_one(game, payload: dict) -> ReplacementOutcome | None:
    """Ali from Cairo: "Damage that would reduce your life total to less than
    1 reduces it to 1 instead."

    A CR 120.4c effect — it modifies the damage's *result*, not the damage. The
    damage is dealt in full, so lifelink gains the full amount (CR 120.3f) and a
    "deals damage to a player" trigger sees the full amount; only the life loss
    is capped. ``payload["dealt"]`` is that full amount, kept beside the life
    loss so the difference is readable rather than lost.
    """
    return ReplacementOutcome(new_amount=_floored_amount(game, payload))


#: "If an **instant or sorcery** source would deal **3** or more damage to you,
#: it deals **2** damage to you instead." (Forethought Amulet.) All three of the
#: bold parts are payload, for the reason every parameter in this engine is: a
#: card printing a different source class, threshold or cap is the same
#: sentence. The class is spelled as the card spells it and split on "or" below,
#: so "an artifact source" and "an instant or sorcery source" are one row.
_SOURCE_DAMAGE_CAP = re.compile(
    r"^if an? (?P<source_class>[a-z ]+?) source would deal (?P<threshold>\d+) or "
    r"more damage to you, it deals (?P<capped>\d+) damage to you instead$"
)


def source_damage_cap(line: str) -> tuple[tuple[str, ...], int, int] | None:
    """``(source types, threshold, capped amount)`` *line* imposes, or None.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is capped and what is claimed
    cannot drift. The types come back as a tuple because the printed class may
    name several ("an instant or sorcery source") and every one of them answers
    the class.
    """
    match = _SOURCE_DAMAGE_CAP.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    types = tuple(
        word.strip() for word in match.group("source_class").split(" or ") if word.strip()
    )
    # A class naming no readable type refuses the line rather than capping
    # everything: `source_has_type` answers False for a word it does not know,
    # so an unread class would be a cap that never fires — the silent shape this
    # module's claim reader exists to keep out of the supported pool.
    if not types:
        return None
    return types, int(match.group("threshold")), int(match.group("capped"))


#: "If a source would deal **4** or more damage to a permanent or player, that
#: source deals **3** damage to that permanent or player instead." (Divine
#: Presence.) The cap above with both of its narrowings taken off: no source
#: class, and no "you" — every source, every recipient, every seat's. The
#: threshold and the cap are payload exactly as they are there.
#:
#: Its own pattern rather than two more optional groups on
#: ``_SOURCE_DAMAGE_CAP``, because the two sentences differ in *where the board
#: is read from* and not only in their words: "to you" is the controller of the
#: permanent printing it (so the scan is the damaged player's own battlefield),
#: and "to a permanent or player" names nobody (so the scan is every
#: battlefield). One permissive pattern would have to hand that difference back
#: out as a flag, which is the two readers again with a regex between them.
#:
#: The recipient phrase is spelled twice with a backreference, for
#: ``_SOURCE_DAMAGE_DELTA``'s reason one screen down: the two halves have to
#: name the same thing.
_ANY_SOURCE_DAMAGE_CAP = re.compile(
    r"^if a source would deal (?P<threshold>\d+) or more damage to a "
    r"(?P<recipients>permanent or player|creature or player), "
    r"(?:that source|it) deals (?P<capped>\d+) damage to that "
    r"(?P=recipients) instead$"
)


def any_source_damage_cap(line: str) -> tuple[int, int] | None:
    """``(threshold, capped amount)`` *line* imposes on every damage event, or
    None.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is capped and what is claimed
    cannot drift — ``source_damage_cap``'s arrangement, for its unnarrowed
    twin.
    """
    match = _ANY_SOURCE_DAMAGE_CAP.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    return int(match.group("threshold")), int(match.group("capped"))


def _capped_source_damage(game, payload: dict) -> int | None:
    """The amount a printed source cap would leave, or None when none applies.

    Both the applicability predicate and the effect call this, which is what
    keeps applicability *pure* (CR 616.1f re-asks the contenders after each
    applied effect, so an effect that answered "do I apply?" by applying itself
    would make them uncountable).

    **Two printings, one answer.** Forethought Amulet's cap is read off the
    damaged *player's* own battlefield (CR 109.5: "to you"); Divine Presence's
    is read off every battlefield and covers a permanent as readily as a
    player. Both are the sentence "deals N instead", so the lowest cap that
    applies is the one number this event becomes — one candidate, applied once
    (CR 614.5), rather than a second interceptor that would cap a capped event
    again after something else had raised it.
    """
    from ..prevention import source_has_type

    recipient = payload["recipient"]
    amount = payload["amount"]
    source = payload.get("source")
    if amount <= 0:
        return None
    best: int | None = None
    if hasattr(recipient, "life"):
        for permanent in game.controlled_by(recipient):
            for line in (permanent.effective_card.oracle_text or "").splitlines():
                read = source_damage_cap(line)
                if read is None:
                    continue
                types, threshold, capped = read
                if amount < threshold or capped >= amount:
                    continue
                if not any(source_has_type(game, source, word) for word in types):
                    continue
                best = capped if best is None else min(best, capped)
    # "…to **a permanent or player**" (Divine Presence): every battlefield,
    # because the sentence names no controller — an opponent's Presence caps
    # the damage their own creature would deal to yours. "A source" is every
    # source there is, a turn-based one included, so nothing is asked of it.
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            read_any = any_source_damage_cap(line)
            if read_any is None:
                continue
            threshold, capped = read_any
            if amount < threshold or capped >= amount:
                continue
            best = capped if best is None else min(best, capped)
    return best


def _applies_source_damage_cap(game, payload: dict) -> bool:
    return _capped_source_damage(game, payload) is not None


@replacement_effect(
    "damage_to_player", DAMAGE_SOURCE_CAP, applies=_applies_source_damage_cap,
    amount_role=CAP,
)
@replacement_effect(
    "damage_to_creature", DAMAGE_SOURCE_CAP, applies=_applies_source_damage_cap,
    amount_role=CAP,
)
def _cap_damage_from_source_class(game, payload: dict) -> ReplacementOutcome | None:
    """Forethought Amulet: "If an instant or sorcery source would deal 3 or more
    damage to you, it deals 2 damage to you instead." Divine Presence: "If a
    source would deal 4 or more damage to a permanent or player, that source
    deals 3 damage to that permanent or player instead."

    One interceptor on both recipient kinds, because "a permanent or player" is
    one sentence — the arrangement ``_shift_spell_damage`` has one screen down.
    A **replacement** and not a prevention (CR 614.1a: the word is "instead"),
    which is rules-visible twice over: damage that "can't be prevented" is
    capped all the same, and nothing downstream is told that any damage was
    prevented.

    A CR 120.4b effect — it changes the damage *dealt*, not its result, so the
    capped number is what lifelink gains and what a "deals damage to a player"
    trigger sees. That is the difference from Ali from Cairo two entries up,
    which caps the life lost and leaves the damage whole.

    "To you" is the Amulet's controller (CR 109.5), which is why the scan is over
    the recipient's own battlefield: an opponent's Amulet does nothing for the
    player being burned.
    """
    capped = _capped_source_damage(game, payload)
    recipient = payload["recipient"]
    game.log.append(
        f"{getattr(recipient, 'name', None) or recipient.card.name} takes "
        f"{capped} damage instead of {payload['amount']} (source cap)"
    )
    return ReplacementOutcome(new_amount=capped)


#: "If a **spell** would deal damage to a permanent or player, it deals that
#: much damage minus **1** to that permanent or player instead." (Benevolent
#: Unicorn.) "…that much damage **plus 1**…", for a **red spell** (Sulfuric
#: Vapors). The source class, the direction and the number of points are all
#: payload, exactly as the cap above has them: a card printing "minus 2", or
#: naming a narrower class of source, is this same sentence.
#:
#: The **direction** is payload for that same reason and no other — "plus" and
#: "minus" are one sentence one word apart, and a second pattern for the second
#: word would be a second answer to "how much does this event become". Signed
#: and summed, which is what makes a Unicorn and a Vapors on one board right in
#: either CR 616.1 order: addition commutes, and the clamp at zero is reached
#: only from below.
#:
#: The recipient phrase is spelled out twice, because the two halves of the
#: sentence have to name the same thing: a card reducing damage to a permanent
#: and then dealing the reduced amount to a *player* is not this effect, and
#: matching the two independently would read it as though it were. Which
#: second half answers which first half is :data:`_DELTA_RECIPIENTS`.
_SOURCE_DAMAGE_DELTA = re.compile(
    r"^if an? (?P<source_class>[a-z ]+?) would deal damage to a "
    r"(?P<recipients>permanent or player|creature or player|"
    r"creature you control), it deals that "
    r"much damage (?P<direction>minus|plus) (?P<points>\d+) to that "
    r"(?P<echo>permanent or player|creature or player|creature) instead$"
)

#: Who a delta line covers, by the printed phrase behind "to a": the words the
#: second half must echo it with, and the noun phrase the damaged object has to
#: answer — as a filter payload ``subject_matches`` reads — or None where the
#: sentence narrows nothing ("a permanent or player" is every recipient a
#: damage event has).
#:
#: "…to **a creature you control**, … to **that creature** instead" (Lashknife
#: Barrier) is the first narrowed printing, and the narrowing is the whole
#: card: the seat is the Barrier's own controller (CR 109.5), so an opponent's
#: creature is hit for the printed amount and a player always is. A phrase
#: rather than a second pattern, for the reason the source class and the
#: direction are payload — it is the same sentence with one clause changed,
#: and a second interceptor would be a second answer to "how much does this
#: event become".
_DELTA_RECIPIENTS: dict[str, tuple[str, dict | None]] = {
    "permanent or player": ("permanent or player", None),
    "creature or player": ("creature or player", None),
    "creature you control": (
        "creature", {"type_filter": "creature", "controller": "you"},
    ),
}


def _read_damage_delta(line: str) -> tuple[str, int, dict | None] | None:
    """``(source class, signed points, protected phrase)`` for a delta line.

    The one reader of the sentence; :func:`source_damage_delta` is its first
    two answers, which is everything the unnarrowed printings have.
    """
    match = _SOURCE_DAMAGE_DELTA.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    echo, protected = _DELTA_RECIPIENTS[match.group("recipients")]
    if match.group("echo") != echo:
        return None
    points = int(match.group("points"))
    return match.group("source_class"), (
        -points if match.group("direction") == "minus" else points
    ), protected


def source_damage_delta(line: str) -> tuple[str, int] | None:
    """``(source class, signed points)`` *line* moves the event by, or None.

    Negative for the printed word "minus" and positive for "plus", so the two
    printings are one number rather than two branches — the sign *is* the word.

    One matcher, asked by the interceptors below and by
    :func:`replacement_claims_line`, so what is changed and what is claimed
    cannot drift — the arrangement ``source_damage_cap`` above already has.

    The class is checked against :func:`_source_answers_class` at fire time
    rather than here, so a class that reader cannot answer leaves the effect
    inert rather than unclaimed. That is the opposite of the cap's rule one
    function up, and deliberately: this pattern's class is a printed *phrase*
    ("a spell", "a red spell"), not a list of card types to be split, so a
    class nobody reads is a typo in this file rather than a card the pool
    prints.

    Which recipients the line covers is :func:`damage_delta_recipients`.
    """
    read = _read_damage_delta(line)
    return None if read is None else read[:2]


def damage_delta_recipients(line: str) -> dict | None:
    """The noun phrase a delta line's damaged object must answer, as a filter
    payload — or None, both for a line that narrows nothing and for a line
    that is not a delta at all (ask :func:`source_damage_delta` first).

    "…to **a creature you control**" (Lashknife Barrier). Relative to the seat
    controlling the permanent that prints it, which the caller supplies as the
    observer.
    """
    read = _read_damage_delta(line)
    return None if read is None else read[2]


def _delta_covers(game, holder, recipient, protected: dict | None) -> bool:
    """Whether *holder*'s delta line reaches a damage event on *recipient*.

    Asked through ``subject_matches`` with the holder's controller as the
    observer, so "a creature" is layer 4's answer and "you control" is layer
    2's — a land animated this turn is covered, a creature stolen this turn is
    covered by its new controller's Barrier and not by its old one. A player
    is never an object a noun phrase describes, so a narrowed line never
    covers one.
    """
    if protected is None:
        return True
    if not _is_permanent(recipient):
        return False
    from ..subject_filters import subject_matches

    return subject_matches(
        game, recipient, protected, observer=game.controller_index_of(holder),
    )


def _spell_damage_delta(game, payload: dict) -> int:
    """How many points every such line on the board moves this event by.

    **Summed** across the battlefield rather than applied one permanent at a
    time. CR 616.1 would apply two Unicorns as two replacements in an order the
    affected player picks, and addition commutes — so the number is the same
    either way, and one candidate per registration is the model
    ``apply_in_order`` has ("an effect applies once per event"). A second
    candidate per permanent would be a change to that model for no change in
    any answer.

    Every battlefield, unlike the cap beside it: the printed sentence names no
    controller at all, so an opponent's Unicorn softens a burn spell aimed at
    its own controller exactly as it softens one aimed at anybody — and an
    opponent's Sulfuric Vapors sharpens it.
    """
    amount = payload.get("amount") or 0
    if amount <= 0:
        return 0
    total = 0
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            read = _read_damage_delta(line)
            if read is None:
                continue
            source_class, points, protected = read
            if not _source_answers_class(
                game, payload.get("source"), source_class,
                payload.get("source_seat"),
            ):
                continue
            # "…to **a creature you control**" (Lashknife Barrier): the one
            # printing that narrows the recipient, so two Barriers under two
            # controllers each shave their own side's creatures and nobody
            # else's. Summed like every other line here — two under one
            # controller are minus 2, in either CR 616.1 order.
            if not _delta_covers(
                game, permanent, payload.get("recipient"), protected
            ):
                continue
            total += points
    return total


def _applies_spell_damage_delta(game, payload: dict) -> bool:
    return _spell_damage_delta(game, payload) != 0


@replacement_effect(
    "damage_to_player", DAMAGE_SOURCE_DELTA,
    applies=_applies_spell_damage_delta,
)
@replacement_effect(
    "damage_to_creature", DAMAGE_SOURCE_DELTA,
    applies=_applies_spell_damage_delta,
)
def _shift_spell_damage(game, payload: dict) -> ReplacementOutcome | None:
    """Benevolent Unicorn: "If a spell would deal damage to a permanent or
    player, it deals that much damage minus 1 to that permanent or player
    instead." Sulfuric Vapors: the same sentence with "plus 1", for a red spell.

    A **replacement** and not a prevention shield, and the difference is the
    whole card. A shield absorbs points and reports damage prevented; this
    changes the number the source would deal (CR 120.4b), so a 1-damage spell
    reduced to 0 is a source that deals no damage at all (CR 120.8) — nothing is
    dealt, nothing is marked, and no "deals damage" trigger fires. Written as a
    shield it would have prevented 1 of 1 and *still* announced an event. The
    other direction has no shield form at all, which is the second reason these
    are one interceptor rather than two: a card that *adds* damage is a
    replacement or it is nothing.

    One interceptor on both recipient kinds, because "a permanent or player" is
    one sentence and a second copy is two answers to it.

    Lashknife Barrier: "If **a source** would deal damage to **a creature you
    control**, it deals that much damage minus 1 to that creature instead." The
    same sentence with both ends changed, and both are parameters of the one
    reader (``_read_damage_delta``) rather than a second interceptor: any
    source at all, combat damage included, and only the Barrier's controller's
    creatures. Per recipient, because a damage event is per recipient — a
    sweep dealing 2 to each creature is 1 to each of that side's.
    """
    delta = _spell_damage_delta(game, payload)
    shifted = max(0, int(payload["amount"]) + delta)
    recipient = payload["recipient"]
    game.log.append(
        f"{getattr(recipient, 'name', None) or recipient.card.name} takes "
        f"{shifted} damage instead of {payload['amount']} (damage "
        f"{'reduced by' if delta < 0 else 'increased by'} {abs(delta)})"
    )
    return ReplacementOutcome(new_amount=shifted)


def _source_answers_class(
    game, source, source_class: str, seat: int | None = None
) -> bool:
    """Whether *source* is in the class a redirect or a delta names.

    A leading **colour word** is peeled off first and tested through
    ``damage_source_colors`` — the one reader every shield in this engine asks
    — so "a **red** spell" (Sulfuric Vapors) is "a spell" with a recorded
    property rather than a class of its own. Peeled rather than listed, because
    the noun behind it is untouched: a card printing "a blue spell" or "a green
    creature" needs no entry here.

    The colour is rechecked at damage time along with the class, which is what
    CR 615.9 asks of a recorded property and what a Vapors deserves: a spell
    recoloured on the stack is red or not when its damage would be dealt.
    """
    from ..damage_source_colors import damage_source_colors
    from ..grammar.vocabulary import COLOR_WORDS

    word, _, rest = source_class.partition(" ")
    if rest and word in COLOR_WORDS:
        if COLOR_WORDS[word] not in damage_source_colors(game, source, seat=seat):
            return False
        source_class = rest
    if source_class == "unblocked creatures":
        return _unblocked_attacker(source)
    if source_class == "source":
        # "If **a source** would deal damage to a creature you control…"
        # (Lashknife Barrier). CR 609.7's widest class and no narrowing at
        # all: a spell, an ability's permanent and a creature in combat are
        # each a source, so nothing is asked of it — the reading the cap one
        # function up already gives Divine Presence's identical two words.
        # A colour word in front ("a red source") was peeled and tested above.
        return True
    if source_class == "spell":
        return _source_is_a_spell(game, source)
    from ..prevention import source_has_type

    return source_has_type(game, source, source_class.rstrip("s"))


def _source_is_a_spell(game, source) -> bool:
    """Whether the damage's source is a **spell** (CR 609.7a).

    Asked of ``Game.resolving_items`` — the object whose instructions are
    running — for the reason ``damage_redirects.resolving_object_redirects``
    states about the same question: **that is the only way a spell can be
    recognised**. The object is popped off the stack before its instructions
    run, so a stack scan finds nothing; and its damage source is the printed
    ``CardDefinition`` (one object per *card*, shared by every copy), so the
    source alone cannot say whether a spell or a permanent's ability is dealing
    it. A ``StackItem`` is one object per cast, and it knows which.

    A stack item is a spell exactly when nothing stamped an ability on it: the
    activation and trigger paths both fill ``ability_instruction``. The
    innermost item, because a resolution can nest — a replacement re-running an
    event is inside whatever armed it.

    Two boundaries are stated rather than hidden. A permanent source is never a
    spell, checked first so a creature's combat damage never reaches the list.
    And ``resolving_items`` is empty while a resolution waits on a prompt, so
    damage dealt after a CR 616.1e question was asked mid-resolution is outside
    this — the same limit the redirect reader records, and the same safe
    direction: the damage lands as it would have without the effect.
    """
    if source is None or hasattr(source, "permanent_id"):
        return False
    items = getattr(game, "resolving_items", None) or ()
    if not items:
        return False
    top = items[-1]
    return top.card is source and top.ability_instruction is None


def _unblocked_attacker(source) -> bool:
    """Whether *source* is an unblocked attacking creature (CR 509.1h).

    Delegated to ``handlers/_filters.unblocked_attacker``, which is the same word
    the ``unblocked_only`` filter key answers to — Kjeldoran Royal Guard prints
    Veteran Bodyguard's source class with a duration on it, so the static read
    here and the recorded redirect's filter must not be two readings.
    """
    from ..handlers._filters import unblocked_attacker

    return unblocked_attacker(source)


def _is_desert(source) -> bool:
    card = getattr(source, "card", source)
    return (
        card is not None
        and getattr(card, "primary_type", None) == "land"
        and "desert" in card.type_line.lower()
    )


_CAMEL_SHIELD_TEXT = "prevent all damage deserts would deal to this creature"


def _banded_desert_shield(game, permanent) -> bool:
    """Camel's second clause: the shield also covers "creatures banded with
    this creature" (CR 702.22e).

    Through ``banding.creatures_banded_with``, which is the one reader of that
    set — the same one ``subject_matches`` asks for the printed noun phrase
    (Icatian Skirmishers' "all creatures banded with it"). Two walks of
    ``combat_bands`` would be two answers to "who is in this band", and this
    one used to be the second: it resolved the slot itself and read the
    battlefield positionally to get there.

    The band lasts for the rest of combat and attacking creatures stay
    attacking until the end of combat step ends (CR 511.3), so the shield still
    covers a band-mate a Desert aims at during that step.
    """
    if not permanent.attacking:
        return False
    from ..banding import creatures_banded_with

    return any(
        mate.attacking
        and _CAMEL_SHIELD_TEXT in (mate.effective_card.oracle_text or "").lower()
        for mate in creatures_banded_with(game, permanent)
    )


def _applies_desert_shield(game, payload: dict) -> bool:
    """The whole of this effect is its guard — being shielded from Deserts does
    not do anything to the event beyond consuming it — so the predicate carries
    all three ways a creature can be covered."""
    permanent = payload["recipient"]
    if not _is_desert(payload.get("source")):
        return False
    text = (permanent.effective_card.oracle_text or "").lower()
    return (
        "prevent all damage that would be dealt to this creature by deserts" in text
        or (_CAMEL_SHIELD_TEXT in text and permanent.attacking)
        or _banded_desert_shield(game, permanent)
    )


@replacement_effect(
    "damage_to_creature", SOURCE_TYPE_SHIELD, applies=_applies_desert_shield, prevents=True
)
def _prevent_desert_damage(game, payload: dict) -> ReplacementOutcome | None:
    """Desert Nomads: "Prevent all damage that would be dealt to this
    creature by Deserts." / Camel: same shield while attacking, extended to
    creatures banded with it. Checked against oracle text directly (like
    Lich's life-gain replacement) rather than a compiled instruction."""
    return ReplacementOutcome(replaced=True)


#: The damage-multiplier sentence, with **two** words as payload: the factor
#: and whether the source is narrowed to the reader's own. It replaced a
#: ``TRIPLE_DAMAGE_TEXT`` constant, which was one card's printing of it and
#: which nothing reads any more. Fiery Emancipation prints "a source
#: **you control** ... **triple**"; Furnace of Rath prints "a source ...
#: **double**" and so applies to every source in the game, its controller's
#: opponents' included. A second constant would have been a second card's worth
#: of one sentence - and, worse, would have kept the narrowing implicit, where
#: the whole difference between the two cards is that Furnace has none.
_DAMAGE_MULTIPLIER_RE = re.compile(
    r"^if a source(?P<yours> you control)? would deal damage to a permanent or "
    r"player, it deals (?P<factor>double|triple) that damage to that permanent "
    r"or player instead$"
)

#: The printed multiplier words. A factor this table cannot read leaves the line
#: unclaimed rather than admitted with the damage unchanged.
_MULTIPLIER_WORDS = {"double": 2, "triple": 3}


def damage_multiplier_line(line: str) -> tuple[int, bool] | None:
    """``(factor, only sources its controller controls)`` for *line*, or None.

    One reader for the support gate, the parse claim and the interceptor, so
    what is claimed and what fires cannot drift - the pairing every text-keyed
    table in this engine keeps.
    """
    match = _DAMAGE_MULTIPLIER_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    return _MULTIPLIER_WORDS[match.group("factor")], match.group("yours") is not None


def _damage_multiplier(game, payload: dict) -> int:
    """How much this event's damage is multiplied by, or 1 for not at all.

    A **narrowed** multiplier is read off the seat that controls the *source*
    (CR 109.5), which is the whole reason a damage event carries one — the
    payload's ``source`` is a bare ``CardDefinition`` for a spell, so a
    Permanent-only reading would triple a creature's damage and silently not a
    burn spell's. An unnarrowed one (Furnace of Rath) names no seat at all and
    so applies to every source there is — including one no seat can be derived
    for, which is why the ``seat is None`` early return moved inside the
    narrowing test rather than staying above it.

    **One candidate stands in for every copy — and for every card.** CR 616.1
    would apply two Fiery Emancipations one at a time, and the affected player
    would choose where the shields go among them; but every copy is the same
    effect at the same order, so applying them together is exactly the sequence
    the default choice produces. Registering one interceptor and taking the
    **product** of what the board says is therefore the same game, where
    returning one card's factor and being asked once would be a different one:
    an effect applies once per event (``engine/effect_ordering.py``), so the
    second multiplier would be dropped rather than deferred. A Furnace of Rath
    beside a Fiery Emancipation is 6, in either order (CR 616.1 leaves the order
    to the affected player and multiplication does not care).
    """
    seat = payload.get("source_seat")
    if payload["amount"] <= 0:
        return 1
    product = 1
    for source_seat, perm in game.permanents_with_controller():
        for line in (perm.effective_card.oracle_text or "").splitlines():
            read = damage_multiplier_line(line)
            if read is None:
                continue
            factor, only_yours = read
            if only_yours and (seat is None or source_seat != seat):
                continue
            product *= factor
    return product


def _applies_damage_multiplier(game, payload: dict) -> bool:
    return _damage_multiplier(game, payload) > 1


@replacement_effect(
    "damage_to_creature", DAMAGE_MULTIPLIER, applies=_applies_damage_multiplier,
    amount_role=MULTIPLIER,
)
@replacement_effect(
    "damage_to_player", DAMAGE_MULTIPLIER, applies=_applies_damage_multiplier,
    amount_role=MULTIPLIER,
)
def _multiply_damage_dealt(game, payload: dict) -> ReplacementOutcome | None:
    """Fiery Emancipation: "If a source **you control** would deal damage to a
    permanent or player, it deals **triple** that damage to that permanent or
    player instead." Furnace of Rath: the same sentence with no narrowing and
    **double**.

    A CR 120.4b effect, so the bigger number is the damage *dealt*: lifelink
    gains it (CR 120.3f), a "deals damage to a player" trigger sees it, and
    deathtouch and trample read it. One body for both recipients because the
    card makes no distinction — "a permanent or player" is the whole of its
    scope — and the two kinds differ only in which list they are registered in.
    """
    multiplier = _damage_multiplier(game, payload)
    amount = payload["amount"]
    game.log.append(f"{amount} damage becomes {amount * multiplier}")
    return ReplacementOutcome(new_amount=amount * multiplier)


def _turn_damage_records(game, payload: dict, *, multiplying: bool) -> list:
    """The turn-long damage replacements a resolution armed that answer to this
    event (``engine/turn_replacements.py``) — the multiplying ones or the
    setting ones. Pure.

    Every printed narrowing is a field on the record and is tested by
    ``damage_record_answers`` rather than spelled here, so Blind Fury's
    "combat … a creature … to a creature" and Equal Treatment's "any source …
    1 or more … a permanent or player" are one reader.
    """
    from ..turn_replacements import (DAMAGE, armed_turn_replacements,
                                    damage_record_answers)

    return [
        record for record in armed_turn_replacements(game, DAMAGE)
        if ((record.multiplier > 1) if multiplying else (record.becomes is not None))
        and damage_record_answers(record, payload)
    ]


def _applies_turn_damage_multiplier(game, payload: dict) -> bool:
    """Whether a turn-long doubling (Blind Fury) answers to this event."""
    return bool(_turn_damage_records(game, payload, multiplying=True))


@replacement_effect(
    "damage_to_creature", COMBAT_DAMAGE_DOUBLER,
    applies=_applies_turn_damage_multiplier, amount_role=MULTIPLIER,
)
@replacement_effect(
    "damage_to_player", COMBAT_DAMAGE_DOUBLER,
    applies=_applies_turn_damage_multiplier, amount_role=MULTIPLIER,
)
def _multiply_turn_damage(game, payload: dict) -> ReplacementOutcome | None:
    """Blind Fury: "If a creature would deal combat damage to a creature this
    turn, it deals double that damage to that creature instead."

    A CR 120.4b effect like Fiery Emancipation's, so the bigger number is the
    damage *dealt*: lifelink gains it, deathtouch and trample read it, and a
    "deals damage" trigger sees it.

    Two copies square rather than adding, for the reason ``_damage_multiplier``
    records: each is its own effect at its own moment, and applying them
    together is the sequence CR 616.1's default choice produces.

    Registered on both recipients and narrowed by the record: Blind Fury's
    record says "to a creature", so a player is never doubled — the test is
    the card's, not the registration's.
    """
    records = _turn_damage_records(game, payload, multiplying=True)
    multiplier = 1
    for record in records:
        multiplier *= record.multiplier
    amount = payload["amount"]
    game.log.append(
        f"{amount} {'combat ' if payload.get('combat') else ''}damage becomes "
        f"{amount * multiplier} ({records[0].source_name})"
    )
    return ReplacementOutcome(new_amount=amount * multiplier)


def _applies_turn_damage_becomes(game, payload: dict) -> bool:
    """Whether a turn-long "it deals N damage instead" (Equal Treatment)
    changes this event. Pure.

    An event already at the printed number is left alone: replacing 2 with 2
    changes nothing, and counting it as a contender would put a CR 616.1e
    question to the affected player about an effect that cannot matter.
    """
    return any(
        record.becomes != payload["amount"]
        for record in _turn_damage_records(game, payload, multiplying=False)
    )


@replacement_effect(
    "damage_to_creature", TURN_DAMAGE_BECOMES,
    applies=_applies_turn_damage_becomes, amount_role=CAP,
)
@replacement_effect(
    "damage_to_player", TURN_DAMAGE_BECOMES,
    applies=_applies_turn_damage_becomes, amount_role=CAP,
)
def _turn_damage_becomes(game, payload: dict) -> ReplacementOutcome | None:
    """Equal Treatment: "If any source would deal 1 or more damage to a
    permanent or player this turn, it deals 2 damage to that permanent or
    player instead."

    A CR 120.4b effect: the 2 is the damage *dealt*, so lifelink gains 2 and a
    "deals damage" trigger sees 2. Two copies set the same number, and the
    newest record names the effect in the log.
    """
    records = [
        record for record in _turn_damage_records(game, payload, multiplying=False)
        if record.becomes != payload["amount"]
    ]
    record = records[-1]
    amount = payload["amount"]
    game.log.append(
        f"{amount} damage becomes {record.becomes} ({record.source_name})"
    )
    return ReplacementOutcome(new_amount=int(record.becomes))


def _applies_next_damage_doubled(game, payload: dict) -> bool:
    """Whether this event's source is carrying Desperate Gambit's winning half.

    Pure — it reads the count and never spends it, which is what CR 616.1's
    counting round requires of every predicate in this file.
    """
    if payload["amount"] <= 0:
        return False
    # "…would deal **combat** damage…" (Impulsive Maneuvers) answers only to a
    # combat event; the unnarrowed rider (Desperate Gambit) to every one.
    return armed_for_event(
        payload.get("source"), DAMAGE_DOUBLED_NEXT,
        combat=bool(payload.get("combat")),
    ) > 0


@replacement_effect(
    "damage_to_creature", NEXT_DAMAGE_DOUBLED, applies=_applies_next_damage_doubled,
    amount_role=MULTIPLIER,
)
@replacement_effect(
    "damage_to_player", NEXT_DAMAGE_DOUBLED, applies=_applies_next_damage_doubled,
    amount_role=MULTIPLIER,
)
def _double_next_damage_from_chosen_source(
    game, payload: dict
) -> ReplacementOutcome | None:
    """Desperate Gambit's winning flip: "the next time that source would deal
    damage this turn, it deals double that damage instead."

    A CR 120.4b effect like the two multipliers above it, so the bigger number
    is the damage *dealt*: lifelink gains it (CR 120.3f), a "deals damage"
    trigger sees it, and deathtouch and trample read it.

    One body for both recipients, because the sentence makes no distinction —
    it names no recipient at all, which is the whole of what separates this
    from Blind Fury. The two kinds differ only in which list the registration
    lands in.

    Spent here and not in the predicate, and by *instance* rather than by
    points: "the next time" is one damage event however large it is, so a
    source that deals damage twice this turn has only its first event doubled.
    """
    source = payload.get("source")
    amount = int(payload["amount"])
    spend_for_event(
        source, DAMAGE_DOUBLED_NEXT, combat=bool(payload.get("combat"))
    )
    card = getattr(source, "card", source)
    game.log.append(
        f"{amount} damage from {getattr(card, 'name', 'a chosen source')} "
        f"becomes {amount * 2} (the next time it would deal damage this turn)"
    )
    return ReplacementOutcome(new_amount=amount * 2)
