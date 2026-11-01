"""Amplify (CR 702.38): what a permanent reveals from its controller's hand as
it enters, and the +1/+1 counters each revealed card buys it.

CR 702.38a: *"Amplify is a static ability. 'Amplify N' means 'As this object
enters, reveal any number of cards from your hand that share a creature type
with it. This permanent enters with N +1/+1 counters on it for each card
revealed this way. You can't reveal this card or any other cards that are
entering the battlefield at the same time as this card.'"* CR 702.38b: *"If a
creature has multiple instances of amplify, each one works separately."*

**The reminder text is not the rule.** Every Legions printing says "for each
Beast card you reveal", naming the creature's own printed type; the rule says
"cards that **share a creature type with it**" — with the permanent *as it
enters*, so a Clone entering as a copy of Kilnmouth Dragon reveals Dragons and a
Dragon that some effect made a Goblin as it entered reveals Goblins too. So the
relation is the one ``engine/object_creature_types.py`` already answers for
every other "share a creature type" sentence, read through the layers for the
permanent (CR 614.12, the entering permanent is judged as it will exist) and
through ``creature_types``' card half for each card in the hand — the one
accessor that knows a card in a hand can have creature types its type line does
not print (Conspiracy's second sentence; Mistform Ultimus's "every creature
type (even if this card isn't on the battlefield)" is the same question, and is
answered wherever that accessor learns it).

**A keyword line read by the reader that implements it**, which is how morph,
madness and rampage are admitted (``keyword_lines._qualified_keyword_part``): a
line naming an amplify with no number, or one this module cannot read, keeps the
card refused rather than shipping a creature whose reveal never happens. The
behaviour is an **entry replacement** (CR 614.1c — "as this object enters"), so
nothing goes on the stack and nothing can be responded to: the entry state
(``PermanentStateMixin._perform_entry_state``) asks :func:`arm_amplify_reveals`
as the permanent arrives, by every road a permanent arrives by.

**The reveal is a choice**, "any number of" cards (CR 702.38a). A person in the
controller's seat is asked (the ``entry_reveal`` prompt, answered with the hand
slots to reveal); a seat nobody asks reveals every eligible card, because
nothing is spent by revealing and every counter is the controller's — the
stated default, which a weight in ``engine/ai_valuation.py`` would have to
argue against. The revealed cards are public (CR 701.20a: they are shown to
every player, and the log names them) and stay in the hand.

**Each instance on its own** (CR 702.38b): two amplify abilities are two
reveals, and the same card may be revealed for both.

**What may not be revealed** is the card entering (it is no longer in the hand
by the time the replacement is applied, so nothing has to exclude it) and any
other card entering at the same time — a Tempting Wurm's opponent putting two
Beasts from hand onto the battlefield. Those leave the hand together before the
first of them enters (``handlers.hand._put_entrants``), so the hand this reads
holds only cards that are staying there.
"""

from __future__ import annotations

import re

#: The prompt kind an interactive controller answers (registered in
#: ``engine/mixins/stack/choices/table.py``). Named for what it asks — "which
#: cards in your hand do you reveal as this enters" — rather than for the
#: keyword, because the counters are payload: a card printing the same sentence
#: without the keyword is this prompt with a different number.
ENTRY_REVEAL = "entry_reveal"

#: "amplify 2" as it survives ``normalize_creature_line`` — lowercased, with
#: the reminder text already stripped. The number is the whole parameter.
_AMPLIFY_PART = re.compile(r"^amplify (\d+)$")


def amplify_amount(part: str) -> int | None:
    """The N of one normalized keyword-line *part*, or None if it isn't amplify.

    Also the keyword-line gate's admission test, for ``rampage.rampage_amount``'s
    reason: an amplify with no number, or one the engine cannot read, is not a
    line this module implements, and the classifier refuses the card rather
    than shipping it with the reveal dropped.
    """
    match = _AMPLIFY_PART.match(part.strip())
    return int(match.group(1)) if match else None


def amplify_amounts(card) -> tuple[int, ...]:
    """Every instance of amplify *card* states, in printed order (CR 702.38b).

    Read off ``line_rewrites.expand_card_lines``, CLAUDE.md's rule for every
    reader of a card's lines, and only off a line the keyword-line gate admits
    — the same decomposition the compiler makes, so a sentence that merely
    contains the word is never read as the keyword. Asked of the permanent's
    ``effective_card`` by the entry state, so a copy amplifies as what it
    copied (CR 707.2), a face-down creature has no amplify at all (CR 708.2:
    the blank prints nothing), and a permanent entering under "creatures lose
    all abilities" has none either (CR 614.12, the fold
    ``Game.fold_board_statics_onto_entering`` writes before the entry state).
    """
    if card is None or "amplify" not in (card.oracle_text or "").lower():
        return ()
    from .keyword_lines import _is_supported_keyword_line
    from .line_normalization import normalize_creature_line
    from .line_rewrites import expand_card_lines

    amounts: list[int] = []
    for line in expand_card_lines(card):
        if not _is_supported_keyword_line(line):
            continue
        for part in normalize_creature_line(line).split(","):
            amount = amplify_amount(part)
            if amount is not None:
                amounts.append(amount)
    return tuple(amounts)


def amplify_filter(game, permanent) -> dict:
    """The card filter naming what *permanent*'s amplify may reveal.

    "…cards from your hand that share a creature type with it": the entering
    permanent's creature types, read once as it enters (CR 614.12) through the
    layers, carried as the resolved key both pure matchers already answer
    (``_chosen.SHARED_CREATURE_TYPES_KEY``). A permanent with no creature type
    — a noncreature copy, say — carries an empty list, which matches nothing,
    and correctly: it shares a creature type with no card.
    """
    from .handlers._chosen import SHARED_CREATURE_TYPES_KEY
    from .object_creature_types import creature_types

    return {SHARED_CREATURE_TYPES_KEY: [sorted(creature_types(game, permanent))]}


def revealable_hand_slots(game, seat: int, described: dict) -> list[int]:
    """The slots of *seat*'s hand the reveal may name, in hand order.

    One list for the prompt's offer, the answer's re-check and a default seat's
    pick (idiom 9), each card asked through the one card matcher with its owner
    named — so a card whose creature types an effect changed off the
    battlefield is read with them, never off its printed line alone.
    """
    from .handlers._filters import _card_matches_filter

    return [
        index
        for index, card in enumerate(game.players[seat].hand)
        if _card_matches_filter(card, described, game=game, owner=seat)
    ]


def arm_amplify_reveals(game, permanent, seat: int) -> None:
    """Ask, or answer, each amplify instance *permanent* has as it enters.

    One ``entry_reveal`` per instance (CR 702.38b), each carrying the number of
    counters a revealed card buys and the filter of what may be revealed. A hand
    holding nothing that qualifies arms nothing — "any number of" none is zero,
    and a prompt with no candidates is a question with one answer. A seat nobody
    asks takes the default as the prompt is armed (``default_at_arm``), inside
    the entry, which is when the counters belong there.
    """
    amounts = amplify_amounts(permanent.effective_card)
    if not amounts:
        return
    described = amplify_filter(game, permanent)
    for amount in amounts:
        if amount <= 0:
            continue
        if not revealable_hand_slots(game, seat, described):
            game.log.append(
                f"{game.players[seat].name} revealed no cards for "
                f"{permanent.card.name}'s amplify"
            )
            continue
        game.arm_pending_choice(
            ENTRY_REVEAL, seat,
            card_name=permanent.card.name,
            permanent=permanent,
            # Stamped here as well as by ``_initialize_permanent_state``, for the
            # entry exile's reason: a seat nobody asks takes its default *at
            # arm*, and the default needs the permanent the counters land on.
            _entering_permanent=permanent,
            counters_each=amount,
            filter=dict(described),
        )


__all__ = [
    "ENTRY_REVEAL",
    "amplify_amount",
    "amplify_amounts",
    "amplify_filter",
    "arm_amplify_reveals",
    "revealable_hand_slots",
]
