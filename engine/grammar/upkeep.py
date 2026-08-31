"""Printed paragraphs whose frame is an **upkeep trigger**.

Two productions, and the same shape twice: a triggered ability's effect clause
that is several printed sentences answering one question — how much damage the
upkeep deals, and what the player may spend to hold it down. Power Leak's offer
has no printed bound, so only the damage sentence after it says what the
payment is measured against; Mishra's War Machine taps itself on the *damage*
branch, so its second sentence has nothing to read apart from its first.

Split out of `paragraphs` at the thousand-line guard
(`tests/engine/test_grammar_layering.py`), along a boundary that module already
had: every other paragraph in it is read from a spell's own line or from an
activated ability, and these two are the only ones whose whole reason to be a
paragraph is the upkeep frame around them. The name is the one
`lowering/categories.py` already carries for the kinds they lower to
(``upkeep_pay_to_reduce_damage``, ``upkeep_damage_unless_cost`` — both
``"upkeep"``) and `engine/phases/upkeep_effects.py` carries for the registry
that runs them, so the mirror re-forms rather than forking.

Below `paragraphs` in the layer order, and it imports nothing from it: these
read their own words to the end, exactly as everything in `paragraphs` does.
"""

from __future__ import annotations

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import NUMBER
from .nouns import parse_object_filter
from .readers import accept_source_reference
from .stream import TokenStream


def _parse_pay_mana_to_prevent_upkeep_damage(
    stream: TokenStream,
) -> "ast.DamageReducedByPaidMana | None":
    """``That player may pay any amount of mana. <source> deals N damage to that
    player. Prevent X of that damage, where X is the amount of mana that player
    paid this way.`` (Power Leak, Errant Minion.)

    Three sentences and one effect, for the reason
    :func:`_parse_upkeep_damage_unless_cost` below reads two: the offer has no
    printed bound, so the only thing that limits it is the damage the next
    sentence names, and the third sentence spends the payment against it. Read
    separately, the first would be an offer of nothing in particular and the
    second would deal its damage before the payment existed.

    **This was Power Leak's card hook**, keyed on its whole printed line with
    "enchanted enchantment's controller" in it — so Errant Minion, which prints
    the identical sentence about a creature, reached nothing and compiled
    *supported* on a substring with no instruction behind its only ability. The
    noun is the trigger condition's, not this clause's, which is exactly what
    makes the clause a template.

    Every part is required and none is dropped: the offer must be unbounded
    ("any amount of mana" — a printed cost is a different card and a different
    handler), the damage must be a printed number (the reduction is arithmetic
    against it), and the third sentence must name the same payment back
    ("the amount of mana that player paid **this way**").

    Refuses without consuming, so every other sentence opening "that player may
    …" keeps its own reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "that", "player", "may", "pay", "any", "amount", "of", "mana"
    ):
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_word("deals"):
        stream.reset(mark)
        return None
    token = stream.peek()
    if token is None or token.kind != NUMBER:
        stream.reset(mark)
        return None
    amount = int(token.text)
    stream.advance()
    if not stream.accept_phrase("damage", "to", "that", "player"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("prevent", "x", "of", "that", "damage"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "where", "x", "is", "the", "amount", "of", "mana", "that", "player",
        "paid", "this", "way",
    ):
        stream.reset(mark)
        return None
    return ast.DamageReducedByPaidMana(amount)


def _parse_upkeep_damage_unless_cost(stream: TokenStream) -> "ast.Statement | None":
    """``<source> deals N damage to you unless you <cost>. If it deals damage to
    you this way, tap it.`` (Mishra's War Machine, Minion of Leshrac.)

    Two sentences and one effect: the tap is on the *damage* branch, so the
    second sentence has nothing to read apart from the first.

    **This was Mishra's War Machine's card hook**, keyed on its whole printed
    line with its number and its cost baked in — so Minion of Leshrac, which
    prints the same sentence with 5 for 3 and a sacrifice for the discard,
    reached nothing. Both are payload here, which is the whole difference
    between a hook and a production.

    The trailing sentence is optional because it is a rider: a card printing
    the offer without the tap is this same effect, and demanding it would refuse
    one for text it does not have.
    """
    mark = stream.mark()
    # Every printed spelling of the source, through the reader `nouns` shares
    # upward for exactly this: a card naming itself is one SELF token, "this
    # creature" is two words, and the trigger's effect clause arrives in the
    # second form.
    if not accept_source_reference(stream):
        return None
    if not stream.accept_word("deals"):
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("damage", "to", "you", "unless", "you"):
        stream.reset(mark)
        return None
    discard, sacrifice = 0, None
    if stream.accept_phrase("discard", "a", "card"):
        discard = 1
    elif stream.accept_word("sacrifice"):
        # The same noun phrase the board family's "unless you sacrifice" reads,
        # so what the offer asks for and what the charger collects cannot come
        # to disagree about the words. "…**other than this creature**" (Minion
        # of Leshrac) is part of that phrase and comes back on the filter as
        # ``other_than_source`` — read rather than re-parsed, because a second
        # reading is how the exclusion gets dropped and the card pays by
        # sacrificing the one permanent the sentence rules out.
        stream.accept_word("a", "an")
        try:
            sacrifice = parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
    else:
        stream.reset(mark)
        return None
    taps_source = False
    rider = stream.mark()
    if stream.accept_punct(".") and stream.accept_word("if"):
        if not accept_source_reference(stream):
            stream.reset(rider)
        elif stream.accept_phrase(
            "deals", "damage", "to", "you", "this", "way"
        ) and stream.accept_punct(",") and stream.accept_phrase("tap", "it"):
            taps_source = True
        else:
            stream.reset(rider)
    else:
        stream.reset(rider)
    return ast.UpkeepDamageUnlessCost(
        amount, discard=discard, sacrifice=sacrifice, taps_source=taps_source,
    )
