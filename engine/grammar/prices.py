"""The **price** a printed sentence names — a cost demanded or an offer made.

The floor under `costs.py`, which reads a whole activation cost, and under the
three effect families that print one inside a sentence: "unless they pay {2}",
"unless you pay 2 life", "pay {4} **and** 2 life", "for each age counter on it".

Split out of `phrases` when that module crossed the thousand-line guard at
Mirage's second wave — at *integration*, on nobody's branch, two groups' price
fragments merely summing. The seam is the one `phrases` had already written down
in prose: `_accept_mana_alternatives` lived there and its three life-cost
siblings did not, so one printed offer was read in two modules. They are one
family, and the family is "what does this sentence charge".

Below `phrases` rather than beside it: `phrases` reads it and it reads nothing
back. It carries no vocabulary of its own — the mana lexing is the lexer's and
the counter kinds are `phrases`' — which is what keeps it a floor rather than a
sixth reader of the same words.
"""

from __future__ import annotations

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import MANA
from .readers import accept_source_reference
from .stream import TokenStream

def _parse_mana_payment(stream: TokenStream, *, allow_variable: bool = False) -> ast.ManaCost:
    """The mana half of "you may pay {1}" / "unless its controller pays {X}".

    *allow_variable* admits ``{X}``. It is off by default because most payment
    prompts resolve a concrete number: an "unless you pay {X}" whose caller
    cannot supply an X would otherwise become a silent "pay {0}", which is
    never a real choice.
    """
    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit():
            pips["generic"] = pips.get("generic", 0) + int(symbol)
        elif symbol in ("W", "U", "B", "R", "G", "C"):
            pips[symbol] = pips.get(symbol, 0) + 1
        elif allow_variable and symbol == "X":
            pips["X"] = pips.get("X", 0) + 1
        else:
            raise stream.error(f"unsupported mana symbol {token.text!r}")
    if not pips:
        raise stream.error("expected a mana cost to pay")
    return ast.ManaCost(tuple(sorted(pips.items())))
def _accept_mana_alternatives(stream: TokenStream) -> tuple["ast.ManaCost", ...]:
    """``or <mana>`` runs trailing a mana payment — "…unless they pay {B} **or
    {3}**" (Lim-Dûl's Hex). CR 118.8's alternative cost.

    One offer the payer may cover either way, so the alternatives ride the same
    payment rather than arming a second prompt: two prompts would be two
    decisions and two penalties, and declining the first would deal the damage
    before the second was ever made.

    Whole costs, where ``_accept_life_alternative`` carries only an amount: the
    other currency there is life, which has exactly one number, and this one is
    mana, which is a symbol dict. Refuses without consuming, so any other "or"
    in the sentence keeps the reading it had.
    """
    alternatives: list[ast.ManaCost] = []
    while True:
        mark = stream.mark()
        if not stream.accept_word("or"):
            return tuple(alternatives)
        try:
            alternatives.append(_parse_mana_payment(stream))
        except GrammarError:
            stream.reset(mark)
            return tuple(alternatives)
def _accept_unless_life_cost(stream: TokenStream) -> "ast.Amount | None":
    """The life half of "… unless <player> pays <life>", or None, cursor unmoved.

    Two printed shapes and no third: "**3 life**" and "**life equal to its
    toughness**" (Essence Vortex). The second is not a number this parser could
    count — CR 613 makes toughness computed, so it is whatever the creature has
    when the offer is made — and it travels as the characteristic reference the
    resolution reads.

    None rather than a raise, so the mana payment beside it keeps its reading of
    every clause that is not a life cost.
    """
    mark = stream.mark()
    if stream.accept_word("life"):
        if stream.accept_phrase("equal", "to", "its"):
            for name in ("toughness", "power"):
                if stream.accept_word(name):
                    return ast.CharacteristicOfSubject(name, 0)
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if isinstance(amount, ast.Fixed) and amount.value > 0 and stream.accept_word("life"):
        return amount
    stream.reset(mark)
    return None
def _accept_life_alternative(stream: TokenStream) -> int | None:
    """``or 1 life`` trailing a mana payment (Erosion) — CR 118.8, or None.

    Only the amount is carried, not a whole cost node: this is the second half
    of one offer, and the payer covers it either way. Refuses without consuming
    so any other "or" in the sentence keeps the reading it had.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(amount, ast.Fixed) or not stream.accept_word("life"):
        stream.reset(mark)
        return None
    return amount.value
def _accept_conjoined_life_cost(stream: TokenStream) -> "ast.Amount | None":
    """``and 2 life`` trailing a mana payment (Purgatory) — or None, unmoved.

    CR 118.8's alternative reads "**or** 1 life" and is one offer the payer may
    cover either way; this is "**and** 2 life" and is one offer with two
    prices, both of which have to be paid. One word apart in print and opposite
    in meaning, which is why it is its own reader beside
    :func:`_accept_life_alternative` rather than a flag on it — folded
    together, a player with the mana and no life would take Purgatory's offer
    for free.

    Refuses without consuming, so any other "and" in the sentence keeps its own
    reading — "you may pay {4} and draw a card" is a conjunction of an offer
    and an effect, and this must not eat its "and".
    """
    mark = stream.mark()
    if not stream.accept_word("and"):
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if (
        isinstance(amount, ast.Fixed)
        and amount.value > 0
        and stream.accept_word("life")
    ):
        return amount
    stream.reset(mark)
    return None
def _accept_per_counter_multiplier(stream: TokenStream) -> str | None:
    """``for each <word> counter on <the source>`` trailing a printed cost, or
    None with the cursor untouched.

    "Destroy this creature unless you pay {1} **for each music counter on it**"
    — the ability Musician grants: CR 702.24a's escalation with the keyword's
    name taken off it — and "…unless they pay {1} **for each vortex counter on
    this enchantment**" (Energy Vortex), which is the same clause with the
    source spelled out. Both go through ``accept_source_reference``, the one
    reader of that phrase, so the two spellings cannot come apart.

    The counter word is payload, so a card printing a different one needs no
    production. Returns None with the cursor untouched, because a flat cost
    must keep reading exactly as it did.

    Here in ``phrases`` rather than in either family: it is a fragment the
    destruction productions and the damage ones both read, and a fragment two
    families need goes in ``phrases`` — never in one of them.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    word = stream.peek_word()
    if word is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("counter", "counters") or not stream.accept_word("on"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    return str(word)
def _parse_pay_life(stream: TokenStream) -> "ast.PayLife | None":
    """``pay 4 life`` (Sylvan Library) — CR 119.4.

    A bare imperative whose subject is the effect's controller, like the bare
    draw and discard beside it. Refuses without consuming, so "pay {R}{R}" and
    every other payment sentence keeps the reading it had.

    Here rather than with the life effects because two families read it: the
    `game` family's whole sentence, and the `board` family's "sacrifice this
    enchantment **unless you pay 2 life**" (Season of the Witch), where the
    payment is the alternative to the destruction. A fragment two families need
    is not an effect — the same rule `_parse_zone` and `_parse_mana_payment`
    above are here for — and a second reading of the phrase is how the offer
    and the payment come to disagree about what was paid.
    """
    mark = stream.mark()
    if not stream.accept_word("pay", "pays"):
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("life"):
        stream.reset(mark)
        return None
    return ast.PayLife(player=ast.PlayerRef("you"), amount=amount)
