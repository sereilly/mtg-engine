"""Damage replaced by an event that is not damage (CR 614.1a): "if damage would
be dealt …, <something else> instead".

Counters put on the creature the damage was headed for, or on the player's own
permanent; echo counters removed from the enchantment that armed the
replacement (Soul Echo); cards exiled from the top of a library, or out of a
graveyard (Nefarious Lich), one for each point. In each the damage is not
dealt at all, so nothing that watches damage sees it — which is the difference
from a redirect, where the same damage is still dealt to someone else.

Split out of ``replacements.py`` at the 2,000-line cap's split round, beside
``damage.py`` (how much damage) and ``redirects.py`` (to whom).
"""

from __future__ import annotations

import re

from ..models import PlayerState
from .registry import (DAMAGE_BECOMES_COUNTERS, DAMAGE_BECOMES_GRAVEYARD_EXILE,
                       DAMAGE_BECOMES_LIBRARY_EXILE, DAMAGE_TO_COUNTER_REMOVAL,
                       DAMAGE_TO_YOU_BECOMES_COUNTERS, ReplacementOutcome,
                       replacement_effect)


#: Where the armed counter-removal replacement is written: on the **permanent**
#: whose counters it spends (Soul Echo), never on the player it covers. The
#: counters, the sacrifice that reads them and the replacement are one card's,
#: and CR 122.2 takes the counters with the permanent when it leaves — so a
#: record on the seat would outlive the store it spends and replace damage with
#: nothing.
DAMAGE_TO_COUNTER_REMOVAL_RECORD = "damage_to_counter_removal"


def _counter_removal_source(game, payload: dict):
    """The permanent whose counters would absorb this damage, or None.

    Pure, like every other applicability predicate here (``effect_ordering``
    counts the contenders before any of them runs), and it answers None the
    moment the store is empty: a replacement that could remove no counter has
    nothing to do instead, and CR 614.6's "as much as possible" is about the
    *event*, not about an effect with nothing to give.
    """
    from ..named_counters import counters_on
    from ..models import PlayerState

    recipient = payload["recipient"]
    if payload["amount"] <= 0 or not isinstance(recipient, PlayerState):
        return None
    seat = game.players.index(recipient)
    for permanent in game.all_permanents():
        record = permanent.metadata.get(DAMAGE_TO_COUNTER_REMOVAL_RECORD)
        if not isinstance(record, dict) or record.get("seat") != seat:
            continue
        if counters_on(permanent, str(record.get("counter", ""))) > 0:
            return permanent
    return None


def _applies_damage_to_counter_removal(game, payload: dict) -> bool:
    return _counter_removal_source(game, payload) is not None


@replacement_effect(
    "damage_to_player", DAMAGE_TO_COUNTER_REMOVAL,
    applies=_applies_damage_to_counter_removal,
)
def _damage_removes_counters_instead(game, payload: dict) -> ReplacementOutcome | None:
    """Soul Echo: "For each 1 damage that would be dealt to you until your next
    upkeep, you remove an echo counter from this enchantment instead."

    One counter per point, and **as much as possible** (CR 614.6): a store
    smaller than the damage gives up what it has and the rest is dealt. That is
    what makes the card finite — the counters run down, the upkeep trigger
    finds none and sacrifices the enchantment, and the "you don't lose the game
    for having 0 or less life" static goes with it.

    Applied once for the whole event rather than once per point, which is what
    CR 616.1 asks of a replacement: the printed "for each 1 damage" is the
    *rate*, not a count of applications.
    """
    from ..named_counters import counters_on, remove_counters

    permanent = _counter_removal_source(game, payload)
    counter = str(permanent.metadata[DAMAGE_TO_COUNTER_REMOVAL_RECORD]["counter"])
    amount = payload["amount"]
    removed = min(amount, counters_on(permanent, counter))
    remove_counters(permanent, counter, removed)
    game.log.append(
        f"{removed} of {amount} damage becomes {removed} {counter} counter(s) "
        f"removed from {permanent.card.name}"
    )
    return ReplacementOutcome(new_amount=amount - removed)


_DAMAGE_BECOMES_COUNTERS_RE = re.compile(
    r"^if damage would be dealt to this creature, put that many "
    r"(?P<counter>[+-]\d+/[+-]\d+) counters on it instead$"
)


def damage_becomes_counters(line: str) -> str | None:
    """The counter kind *line* turns damage into, or None if it is not that
    sentence.

    "If damage would be dealt to this creature, put that many **-1/-1**
    counters on it instead." (Lichenthrope.) Phytohydra prints the identical
    sentence with **+1/+1**, which is why the kind is payload and this is a
    shape rather than a constant in ``REPLACEMENT_LINES``: two cards, one
    sentence, and a literal would buy one of them.

    One reader for the support gate and for the interceptor, so what is claimed
    and what fires cannot drift — the pairing every text-keyed table in this
    engine keeps.
    """
    match = _DAMAGE_BECOMES_COUNTERS_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    kind = match.group("counter")
    # A kind ``engine/pt.py`` cannot read is a counter nothing would place, so
    # the line stays unclaimed and its card visibly unsupported rather than
    # entering play with the substitution silently absent. `pt_counter_deltas`
    # derives the deltas from the *name* (CR 122.1a), so any printed pair works
    # and no list of kinds has to be maintained here.
    from ..pt import pt_counter_deltas

    return kind if pt_counter_deltas(kind) is not None else None


def _counters_instead_of_damage(game, payload: dict) -> str | None:
    """The counter kind the damaged creature's own text substitutes, or None.

    Pure, like every applicability predicate here: ``effect_ordering`` counts
    the contenders before any of them runs.

    Read off ``effective_card`` rather than the printed text, because a Clone of
    a Lichenthrope has the sentence (CR 707.2) and a Lichenthrope whose text was
    changed does not.
    """
    recipient = payload["recipient"]
    if payload["amount"] <= 0 or isinstance(recipient, PlayerState):
        return None
    for line in (recipient.effective_card.oracle_text or "").splitlines():
        kind = damage_becomes_counters(line)
        if kind is not None:
            return kind
    return None


def _applies_damage_becomes_counters(game, payload: dict) -> bool:
    return _counters_instead_of_damage(game, payload) is not None


@replacement_effect(
    "damage_to_creature", DAMAGE_BECOMES_COUNTERS,
    applies=_applies_damage_becomes_counters,
)
def _damage_becomes_counters(game, payload: dict) -> ReplacementOutcome | None:
    """Lichenthrope: "If damage would be dealt to this creature, put that many
    -1/-1 counters on it instead."

    CR 614's substitution: the damage is **not dealt at all** — no lifelink
    (CR 120.3f), no "whenever ~ deals damage", nothing marked — and that many
    counters arrive instead. Which is why it returns ``replaced=True`` rather
    than a new amount: an amount effect leaves a damage event happening, and
    this sentence removes it.

    ``add_pt_counters`` rather than a P/T poke, because the counters are real
    CR 122.1a counters: the 704.5q sweep cancels them against +1/+1, the card
    face renders them, and Lichenthrope's own upkeep trigger takes one off.
    """
    kind = _counters_instead_of_damage(game, payload)
    if kind is None:
        return None
    from ..pt import add_pt_counters

    recipient = payload["recipient"]
    amount = int(payload["amount"])
    add_pt_counters(recipient, kind, amount)
    game.log.append(
        f"{recipient.card.name}: {amount} damage becomes {amount} {kind} "
        "counter(s) instead"
    )
    return ReplacementOutcome(replaced=True)


#: "If damage would be dealt to a player, that player exiles that many cards
#: from the top of their library instead." (Crumbling Sanctuary.)
#:
#: A constant rather than a shape, unlike ``damage.py``'s multiplier: the sentence has
#: no payload at all — no source narrowing, no seat, no number — so a matcher
#: would have nothing to capture and the phrase *is* the rule.
DAMAGE_BECOMES_LIBRARY_EXILE_TEXT = (
    "if damage would be dealt to a player, that player exiles that many cards "
    "from the top of their library instead"
)


def _library_exile_source(game, payload: dict):
    """The permanent whose text substitutes this damage, or None. Pure.

    Every battlefield, because the sentence names no controller and no
    recipient: "a player" is either of them, and the permanent is only the place
    the rule is *written*. That is what makes the card symmetric — its own
    controller pays out of their library too.

    Read off ``effective_card`` for ``_counters_instead_of_damage``'s reason one
    reader up: a copy of this artifact carries the sentence (CR 707.2) and one
    whose text was changed does not.
    """
    if payload["amount"] <= 0 or not isinstance(payload["recipient"], PlayerState):
        return None
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            if line.strip().lower().rstrip(".") == DAMAGE_BECOMES_LIBRARY_EXILE_TEXT:
                return permanent
    return None


def _applies_damage_becomes_library_exile(game, payload: dict) -> bool:
    return _library_exile_source(game, payload) is not None


@replacement_effect(
    "damage_to_player", DAMAGE_BECOMES_LIBRARY_EXILE,
    applies=_applies_damage_becomes_library_exile,
)
def _damage_becomes_library_exile(game, payload: dict) -> ReplacementOutcome | None:
    """Crumbling Sanctuary: "If damage would be dealt to a player, that player
    exiles that many cards from the top of their library instead."

    CR 614's substitution rather than CR 615's prevention, and the difference is
    the whole card: the damage is **not dealt**, so no life is lost and nothing
    that watches damage being dealt to a player fires — but the exile happens
    even where the library cannot pay for it in full.

    ``replaced=True`` whatever was exiled, which is CR 609.3 read literally: an
    effect that cannot do all of something does as much as possible, and "as
    much as possible" is a statement about the *cards*, not about the damage —
    CR 614.6 has already said the replaced event never happens. A library with
    two cards left against six damage exiles two and the player still takes
    nothing —
    which is what makes this artifact a way to lose by decking rather than a way
    to survive one more turn. An empty library is not a loss until a draw is
    attempted (CR 104.3c), and this is not a draw.
    """
    permanent = _library_exile_source(game, payload)
    if permanent is None:  # pragma: no cover - the predicate just said otherwise
        return None
    recipient = payload["recipient"]
    amount = int(payload["amount"])
    taken = min(amount, len(recipient.library))
    exiled = [recipient.library.pop(0) for _ in range(taken)]
    recipient.exile.extend(exiled)
    game.log.append(
        f"{permanent.card.name}: {amount} damage to {recipient.name} becomes "
        + (
            f"{taken} card(s) exiled from the top of their library"
            if exiled else "no cards, their library being empty"
        )
    )
    return ReplacementOutcome(replaced=True)


#: "If damage would be dealt to **you**, put that many **delay** counters on
#: this **enchantment** instead." (Delaying Shield.) Lichenthrope's sentence
#: with the two ends moved: the damage was headed for a *player*, and the
#: counters land on the permanent printing the line rather than on what was
#: hit. The counter word and the noun the card calls itself are payload, the
#: way Pursuit of Knowledge's are — a creature printing the sentence with
#: another word is printing the same replacement.
_DAMAGE_TO_YOU_BECOMES_COUNTERS_RE = re.compile(
    r"^if damage would be dealt to you, put that many "
    r"(?P<counter>[a-z][a-z'-]*) counters on this "
    r"(?:creature|artifact|enchantment|land|permanent) instead$"
)


def damage_to_you_becomes_counters(line: str) -> str | None:
    """The counter *line* turns its controller's damage into, or None.

    One reader for the interceptor and for the support gate
    (``replacement_claims_line``), so what is claimed and what fires cannot
    drift.
    """
    match = _DAMAGE_TO_YOU_BECOMES_COUNTERS_RE.match(
        " ".join((line or "").split()).strip().lower().rstrip(".")
    )
    return match.group("counter") if match is not None else None


def _own_counter_substitutions(game, payload: dict) -> list:
    """``(permanent, counter)`` for every permanent of the damaged player's
    that turns this damage into counters on itself. Pure.

    "Dealt to **you**" is the permanent's controller (CR 109.5), so the scan is
    the recipient's own battlefield — an opponent's Shield does nothing for
    the player being hit. Read off ``effective_card`` (CR 707.2, CR 612.1).
    """
    recipient = payload["recipient"]
    if payload["amount"] <= 0 or not isinstance(recipient, PlayerState):
        return []
    found = []
    for permanent in game.controlled_by(recipient):
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            counter = damage_to_you_becomes_counters(line)
            if counter is not None:
                found.append((permanent, counter))
                break
    return found


def _applies_damage_to_you_becomes_counters(game, payload: dict) -> bool:
    return bool(_own_counter_substitutions(game, payload))


@replacement_effect(
    "damage_to_player", DAMAGE_TO_YOU_BECOMES_COUNTERS,
    applies=_applies_damage_to_you_becomes_counters,
)
def _damage_to_you_becomes_counters(game, payload: dict) -> ReplacementOutcome | None:
    """Delaying Shield: "If damage would be dealt to you, put that many delay
    counters on this enchantment instead."

    CR 614's substitution, not CR 615's prevention — the card's ruling says so
    in as many words ("the damage is replaced and is not 'prevented'. This
    means it can replace damage that 'can't be prevented'"), which is why this
    is registered without ``prevents=True``: an event locked against
    prevention still reaches it. The damage is **not dealt**: no life is lost,
    no lifelink, nothing that watches damage being dealt to a player fires.

    One permanent takes the counters — the oldest, by ``permanent_id`` — for
    the reason Pursuit of Knowledge's offer names one source: the event is
    consumed by the first replacement applied to it, so a second Shield has
    nothing left to replace.
    """
    found = _own_counter_substitutions(game, payload)
    if not found:  # pragma: no cover - the predicate just said otherwise
        return None
    from ..named_counters import add_counters

    permanent, counter = min(found, key=lambda entry: entry[0].permanent_id)
    amount = int(payload["amount"])
    total = add_counters(permanent, counter, amount)
    game.log.append(
        f"{permanent.card.name}: {amount} damage to {payload['recipient'].name} "
        f"becomes {amount} {counter} counter(s) instead ({total} on it)"
    )
    return ReplacementOutcome(replaced=True)


#: Nefarious Lich. One printed line, two sentences, and the constant is both
#: because the interceptor performs both — the exile, and CR 104.3e behind a
#: graveyard that cannot pay. A claim stopping at the first sentence would
#: admit a card whose drawback is the second.
DAMAGE_BECOMES_GRAVEYARD_EXILE_TEXT = (
    "if damage would be dealt to you, exile that many cards from your "
    "graveyard instead. if you can't, you lose the game"
)


def _damage_graveyard_exile_source(game, payload: dict):
    """The damaged player's own permanent whose text substitutes this damage,
    or None. Pure. "To **you**" is its controller (CR 109.5)."""
    recipient = payload["recipient"]
    if payload["amount"] <= 0 or not isinstance(recipient, PlayerState):
        return None
    for permanent in game.controlled_by(recipient):
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            if (
                " ".join(line.split()).strip().lower().rstrip(".")
                == DAMAGE_BECOMES_GRAVEYARD_EXILE_TEXT
            ):
                return permanent
    return None


def _applies_damage_becomes_graveyard_exile(game, payload: dict) -> bool:
    return _damage_graveyard_exile_source(game, payload) is not None


def _graveyard_cards_already_owed(game, seat: int) -> int:
    """How many cards of *seat*'s graveyard an unanswered exile pick has
    already spoken for.

    A pick is a prompt, so the cards it will take are still in the pile when
    the next damage event asks whether the pile can pay — three attackers are
    three events, and the third must not count cards the first two are about
    to exile.
    """
    return sum(
        int(choice.data.get("count", 0))
        for choice in game.pending_choices
        if choice.kind == "graveyard_exile_pick"
        and int(choice.data.get("owner_index", -1)) == seat
        and not choice.data.get("up_to")
    )


@replacement_effect(
    "damage_to_player", DAMAGE_BECOMES_GRAVEYARD_EXILE,
    applies=_applies_damage_becomes_graveyard_exile,
)
def _damage_becomes_graveyard_exile(game, payload: dict) -> ReplacementOutcome | None:
    """Nefarious Lich: "If damage would be dealt to you, exile that many cards
    from your graveyard instead. If you can't, you lose the game."

    CR 614's substitution: the damage is **not dealt** — no life is lost, and
    nothing that watches damage dealt to a player fires. What it becomes is a
    price paid out of the graveyard, and the second sentence is this
    replacement's own failure branch rather than a separate ability (Forbidden
    Crypt's shape, one zone over): with fewer cards than damage the player
    loses the game on the spot (CR 104.3e), applied here and not left to a
    state-based action.

    **Which cards go is the player's choice**, and in this block it matters —
    a flashback card and a land are not the same card to give up. So it is
    asked through the pick that already exists for "exile N cards from that
    graveyard" (``arm_graveyard_exile_pick``, Rysorian Badger's prompt): an
    interactive seat is queued and the stack object that dealt the damage
    waits on the answer, every other seat takes the stated default — the first
    N in pile order — where the effect stands. A pile holding exactly the
    number owed is no choice, and is exiled without asking.
    """
    from types import SimpleNamespace

    source = _damage_graveyard_exile_source(game, payload)
    if source is None:  # pragma: no cover - the predicate just said otherwise
        return None
    recipient = payload["recipient"]
    seat = game.players.index(recipient)
    amount = int(payload["amount"])
    available = len(recipient.graveyard) - _graveyard_cards_already_owed(game, seat)
    if available < amount:
        if not recipient.lost:
            recipient.lost = True
            game.log.append(
                f"{source.card.name}: {recipient.name} could not exile {amount} "
                f"card(s) from their graveyard and lost the game (104.3e)"
            )
        return ReplacementOutcome(replaced=True)
    game.log.append(
        f"{source.card.name}: {amount} damage to {recipient.name} becomes "
        f"{amount} card(s) exiled from their graveyard instead"
    )
    game.arm_graveyard_exile_pick(
        seat, seat, {"count": amount, "any_card": True},
        # The pick's resolver records what was exiled on its context's
        # scratchpad, for a sentence that reads it back. Nothing here does, so
        # this is a context with a name to show and nowhere a result goes.
        SimpleNamespace(card=source.card, results={}),
    )
    return ReplacementOutcome(replaced=True)
