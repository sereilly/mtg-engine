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
from .lexer import NUMBER, PT
from .nouns import parse_object_filter
from .phrases import _parse_mana_payment
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


def _accept_counter_word(stream: TokenStream, *, plural: bool = False) -> str | None:
    """The counter kind named in front of the word "counter", or None.

    Two token kinds, because Magic prints two sorts of counter word: a bare
    noun ("wage", "age", "wind") lexes as a WORD, and a P/T counter ("+1/+1")
    lexes as PT. One reader for both, so the paragraph below does not have to
    know which the card printed — the kind is payload either way, and
    ``engine/named_counters.py`` already stores both through one key function.
    """
    token = stream.peek()
    if token is None:
        return None
    if token.kind == PT:
        if stream.peek_word(1) != ("counters" if plural else "counter"):
            return None
        stream.advance()
        return token.text
    word = stream.peek_word()
    # Rejected against the following word rather than against a list of counter
    # names: the names are open (CR 122.1 lets a card invent one), so what
    # identifies the phrase is that "counter" comes next.
    # Checked against the *following* word rather than against a list of counter
    # names: the names are open (CR 122.1 lets a card invent one), so what
    # identifies the phrase is the noun that comes next. Both numbers, because
    # one printed paragraph uses both — "put a wage counter" and "remove all
    # wage counters" — and the caller says which it expects.
    if word is None or stream.peek_word(1) != ("counters" if plural else "counter"):
        return None
    stream.advance()
    return word


def _parse_upkeep_counter_toll(stream: TokenStream) -> "ast.UpkeepCounterToll | None":
    """CR 702.24a's ability printed longhand, in both of its spellings.

    ``Put a +1/+1 counter on this creature, then sacrifice this creature unless
    you pay {1} for each +1/+1 counter on it.`` (Phantasmal Sphere.)
    ``Put a wage counter on this creature. You may pay {2} for each wage counter
    on it. If you don't, remove all wage counters from this creature and an
    opponent gains control of it.`` (Rogue Skycaptain.)

    Tried before the ordinary counter-placement production, which would read the
    first clause and strand everything after it — a permanent that grows a
    counter every upkeep and is never asked to pay for it. Refuses without
    consuming.

    **The counter word must be the same in both halves.** "Pay {1} for each
    <other> counter on it" is a different card: the escalation would be counted
    off a store this ability never writes, which is a cost that never grows.

    The keyword spelling is not read here. ``engine/cumulative_upkeep.py``
    rewrites "Cumulative upkeep [cost]" into this same ability before any line
    is classified, so the two front ends meet at the instruction rather than at
    the sentence — and Cyclone, which prints this paragraph *plus* a rider
    sentence of its own, fails full-token consumption here and keeps the card
    hook that reads the rider.
    """
    mark = stream.mark()
    if not stream.accept_phrase("put", "a"):
        return None
    counter = _accept_counter_word(stream)
    if counter is None or not stream.accept_word("counter"):
        stream.reset(mark)
        return None
    if not stream.accept_word("on") or not accept_source_reference(stream):
        stream.reset(mark)
        return None
    optional = _accept_toll_frame(stream)
    if optional is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None
    if _accept_counter_word(stream) != counter:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("counter", "on", "it"):
        stream.reset(mark)
        return None
    consequence = "sacrifice" if not optional else _accept_toll_consequence(
        stream, counter
    )
    if consequence is None:
        stream.reset(mark)
        return None
    return ast.UpkeepCounterToll(
        counter, dict(cost.pips), consequence=consequence
    )


def _accept_toll_frame(stream: TokenStream) -> bool | None:
    """Which of CR 118.12a's two spellings frames the payment, or None.

    ``False`` for ", then sacrifice this <noun> unless you …" — the consequence
    is stated *before* the cost and is fixed by the sentence. ``True`` for ".
    You may pay … " — the consequence comes after, in its own sentence, and the
    caller reads it there.

    One reader rather than two productions because CR 118.12a says the two are
    the same sentence; what differs is only where the consequence is printed.
    """
    mandatory = stream.mark()
    if stream.accept_punct(",") and stream.accept_phrase("then", "sacrifice"):
        if accept_source_reference(stream) and stream.accept_phrase("unless", "you"):
            return False
    stream.reset(mandatory)
    if stream.accept_punct(".") and stream.accept_phrase("you", "may"):
        return True
    return None


def _accept_toll_consequence(stream: TokenStream, counter: str) -> str | None:
    """What the "If you don't, …" sentence does, as a consequence word.

    Only Rogue Skycaptain's shape today, and every word of it is required: the
    counters are cleared **and** the permanent changes hands, so a printing that
    did one without the other would be a different card and must refuse rather
    than borrow this one's handler.

    The counter word is checked against the one the ability places, for the
    reason the cost's is: "remove all <other> counters" would clear a store this
    ability never wrote.
    """
    if not stream.accept_punct("."):
        return None
    if not (
        stream.accept_word("if")
        and (stream.accept_word("you") or True)
        and (stream.accept_word("don't") or stream.accept_phrase("do", "not"))
    ):
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("remove", "all"):
        return None
    if _accept_counter_word(stream, plural=True) != counter:
        return None
    if not stream.accept_phrase("counters", "from"):
        return None
    if not accept_source_reference(stream):
        return None
    if not stream.accept_phrase(
        "and", "an", "opponent", "gains", "control", "of", "it"
    ):
        return None
    return "cede_control"


def parse_upkeep_paragraph(stream: TokenStream) -> "ast.Statement | None":
    """Every printed paragraph whose frame is an upkeep obligation, tried in
    turn. Each refuses without consuming, so the order decides only which one
    claims a line both could read — and none of them overlaps today.

    One entry point rather than three call sites, because the dispatcher lives
    in ``subject_verb`` and these all occupy the same position in it: before the
    ordinary damage and counter productions, which would each read the
    paragraph's first sentence and strand the rest.
    """
    for production in (
        _parse_upkeep_counter_toll,
        _parse_upkeep_damage_unless_cost,
        _parse_pay_mana_to_prevent_upkeep_damage,
    ):
        node = production(stream)
        if node is not None:
            return node
    return None
