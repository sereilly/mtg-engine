"""An activated ability's cost, read off its printed line (CR 602.1a, CR 118).

:func:`parse_activated_ability_cost` turns everything left of an ability's
activation colon into the ``ActivatedAbilityCost`` the activation path
charges: the mana symbols and {T}, a loyalty symbol (CR 606.4), and every
prose payment beside them — life, a sacrifice, an exile, a discard, a
counter, a mill, the attached permanent's tap, sacrifice or mana cost, a
chosen keyword, "... or {N}". Where that colon is, is
:func:`activation_colon_index`'s answer, and a colon inside a quoted granted
ability is not one.

A noun phrase in a cost is charged through the charger's own reader
(``engine/chargeable_costs.py``), the one the grammar's cost side asks too,
so what is admitted and what is collected cannot disagree;
``tests/engine/test_activation_costs.py`` compares the two readings over the
whole pool.

Split out of ``engine/oracle.py`` at the 2,000-line cap; ``engine.oracle``
still exports :func:`parse_activated_ability_cost`, which is in its
``__all__``.
"""

from __future__ import annotations

import re

from .oracle_types import ActivatedAbilityCost, _MANA_TOKEN_RE, _NUMBER_WORDS
from .cast_costs import read_discard_clause
from .grammar.readers import _SELF_NOUNS
from .self_reference import _collapse_self_references
from .chargeable_costs import (_chargeable_counter_target,
                               _chargeable_exile_filter,
                               _chargeable_return_to_hand_cost,
                               _chargeable_sacrifice_filter,
                               _chargeable_tap_cost, _chargeable_untap_cost)


#: The nouns a card uses for **itself** in a cost - "sacrifice this
#: **Aura**", "exile this **artifact**", "return this **enchantment** to
#: its owner's hand".
#:
#: Derived from the grammar's one list rather than spelled again. It *was*
#: spelled again, three times, as a shorter hand-written alternation
#: carrying only card types - so "Sacrifice this **Aura**" matched nothing
#: and the cost was never charged. That is the quiet direction: nothing
#: crashed, nothing read as unsupported, and Thrull Retainer and Carapace
#: regenerated the creature they enchant every turn for free, for as long
#: as the game lasted. ``Aura`` and ``Equipment`` are *subtypes*
#: (CR 205.3h), which is exactly why a list of card types looked complete.
#:
#: ``card`` and ``spell`` are dropped: neither is a permanent, so neither
#: can be sacrificed, exiled from the battlefield or returned to a hand as
#: *this object* - and a cost regex admitting them would read "exile this
#: card" on a line about somebody else's graveyard.
_SELF_COST_NOUNS = "|".join(sorted(_SELF_NOUNS - {"card", "spell"}))


# CR 606.2: a loyalty ability's cost is a loyalty symbol — "+1", "−2", "0",
# "−X". Scryfall prints the minus as U+2212; an ASCII hyphen is accepted too so
# hand-written fixtures behave like ingested text.
_LOYALTY_COST_RE = re.compile(r"^\s*([+\-−]?)\s*(\d+|[xX])\s*$")


def _parse_loyalty_cost(cost_part: str) -> tuple[int | None, int | None]:
    """The ``(loyalty, loyalty_x_sign)`` a cost clause spells, or ``(None, None)``.

    Matches only when the whole clause is one loyalty symbol: a planeswalker's
    cost clause is nothing else (CR 606.5 combines multiples, and no card in the
    pool prints a combined form), and anything wider must keep reading as the
    mana/prose cost it is.
    """
    match = _LOYALTY_COST_RE.match(cost_part)
    if match is None:
        return None, None
    sign = -1 if match.group(1) in ("-", "−") else 1
    magnitude = match.group(2)
    if magnitude in ("x", "X"):
        return None, sign
    return sign * int(magnitude), None


#: "**Tap enchanted land**: Target blocking creature gets +1/+2 until end of
#: turn." (Earthlore.) One comma-separated cost segment, whole — anchored for
#: the reason every pattern in `activation_restrictions.py` is: a rule matching
#: a prefix would charge a *narrower* cost than the card prints.
_TAP_ATTACHED_COST_RE = re.compile(r"^tap (?:enchanted|equipped) \w+$")


def _taps_the_attached_permanent(cost_lower: str) -> bool:
    """Whether a cost clause taps the permanent this Aura or Equipment is on.

    The payment is the *host*, which `{T}` cannot say: that symbol taps the
    permanent the ability is printed on, and here the ability is printed on the
    attachment. A pre-symbol templating of the same payment, so nothing else
    can pay it — there is no picker and no filter, only the attachment record.

    CR 303.4m reads "enchanted [object]" as whatever the permanent is attached
    to and CR 301.5f reads "equipped" the same way, so both words are read: an
    Equipment printing the clause charges the same cost.
    """
    return any(
        _TAP_ATTACHED_COST_RE.match(segment.strip())
        for segment in cost_lower.split(",")
    )


#: "**Sacrifice enchanted creature**: Creatures you control get +2/+0 until end
#: of turn." (Betrothed of Fire.) :data:`_TAP_ATTACHED_COST_RE` one payment
#: over, anchored per cost segment for that pattern's reason: a rule matching a
#: prefix would charge a *narrower* cost than the card prints. CR 303.4m reads
#: "enchanted [object]" as whatever the permanent is attached to and CR 301.5f
#: reads "equipped" the same way, so an Equipment printing the clause charges
#: the same cost with no second row.
_SACRIFICE_ATTACHED_COST_RE = re.compile(
    r"^sacrifice (?:enchanted|equipped) \w+$"
)


def _sacrifices_the_attached_permanent(cost_lower: str) -> bool:
    """Whether a cost clause sacrifices the permanent this Aura is attached to.

    :func:`_taps_the_attached_permanent` one payment over, and the same shape:
    the host is the whole answer, nothing is picked, and there is no filter to
    narrow. It needs its own reader because the two fields
    ``ActivatedAbilityCost`` already had are each wrong here in a direction —
    ``sacrifice_self`` eats the Aura and ``sacrifice_filter`` eats any matching
    creature on the board, while the enchanted one lives.

    The grammar's half of the same clause is ``costs._is_chargeable_sacrifice``,
    which admits the line on ``ObjectFilter.is_enchanted``; the payload that
    filter produces drops the word entirely, so a reader that went through it
    would charge "sacrifice a creature" and never know.
    """
    return any(
        _SACRIFICE_ATTACHED_COST_RE.match(segment.strip())
        for segment in cost_lower.split(",")
    )


#: "Pay enchanted creature's mana cost" (Merseine). Anchored per cost segment
#: for :data:`_TAP_ATTACHED_COST_RE`'s reason: a rule matching a prefix would
#: charge a *narrower* cost than the card prints. The apostrophe is admitted in
#: both spellings, straight and curly, because the two readers of this clause —
#: this one and the grammar's, which sees a lexed ``'s`` token — must agree
#: about the same printed line.
_PAY_ATTACHED_MANA_COST_RE = re.compile(
    r"^pay (?:enchanted|equipped) \w+['’]s mana cost$"
)


def _pays_the_attached_permanents_mana_cost(cost_lower: str) -> bool:
    """Whether a cost clause spends the mana cost of the permanent this Aura or
    Equipment is on.

    :func:`_taps_the_attached_permanent` one payment over, and the same shape:
    the payment is the *host's*, nothing is picked, and the attachment record
    is the whole answer. What differs is that this one can be **unpayable** —
    the activator has to produce the mana — so the activation path builds the
    symbols from the host rather than reading a fixed dict.

    CR 303.4m reads "enchanted [object]" as whatever the permanent is attached
    to and CR 301.5f reads "equipped" the same way, so both words are read.
    """
    return any(
        _PAY_ATTACHED_MANA_COST_RE.match(segment.strip())
        for segment in cost_lower.split(",")
    )


def _life_payment_cost(cost_lower: str) -> int:
    """The life a "Pay N life" activation cost charges, or 0 for no such cost.

    The regex only **delimits** the number; ``_NUMBER_WORDS`` and ``int`` read
    it — the same split round 34 drew for a narrowed trigger's noun phrase and
    round 56 for a sacrifice cost's, and for the same reason: a second reader
    approximating the first drifts, and the direction a cost drifts in is a cost
    nobody pays. The grammar admits only a fixed positive amount, and
    ``tests/engine/test_activation_costs.py`` compares the two over the whole
    pool, so a clause the grammar admitted and this read as 0 fails there rather
    than shipping a free ability.
    """
    match = re.search(r"\bpay (\w+) life\b", cost_lower)
    if match is None:
        return 0
    word = match.group(1)
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)


_HALF_LIFE_PAYMENT_RE = re.compile(r"\bpay half your life, rounded up\b")


def _life_payment_is_half_rounded_up(cost_lower: str) -> bool:
    """Whether the cost is "Pay half your life, rounded up" (Lurking Evil).

    :func:`_life_payment_cost`'s neighbour, and separate for that function's
    own reason: the two answer different questions — how much is printed, and
    which rule computes it — and only one of them has a number to read at all.
    The rounding word is part of the pattern because CR 107.2 leaves a fraction
    unrounded without it, so a printing without the word is a cost this does
    not recognize; the grammar's cost side refuses that line in the same
    breath, and ``tests/engine/test_activation_costs.py`` compares the two
    readings over the whole pool.
    """
    return _HALF_LIFE_PAYMENT_RE.search(cost_lower) is not None


def _life_payment_per_counter(cost_lower: str) -> str | None:
    """The counter kind a "Pay N life **for each <kind> counter on this
    <noun>**" cost multiplies by, or None when the payment is a flat amount.

    Beside :func:`_life_payment_cost` rather than folded into it because the
    two answer different questions — how much per unit, and how many units —
    and the grammar carries them as two fields for the same reason. Only the
    ability's own source is read ("on **this** <noun>"), which is the one
    permanent a cost charger has in hand.
    """
    match = re.search(
        r"\bpay \w+ life for each ([a-z+/0-9-]+) counters? on this [a-z]+\b",
        cost_lower,
    )
    return match.group(1) if match is not None else None


def activation_colon_index(line: str) -> int | None:
    """The index of the colon that separates an activated ability's cost from
    its effect — or None when the line has none.

    **A colon inside quotation marks is not one.** An Aura that grants an
    ability writes the whole ability inside quotes ("Enchanted land has \"{T}:
    Counter target spell …\"", Equinox), and that colon belongs to the granted
    ability rather than to any ability of the Aura. Split on it, the Aura reads
    as a permanent with a {T} cost and an effect of "counter target spell" —
    which is how Equinox reported an activated ability that compiled to nothing
    while its printed static line, which ``engine/auras.py`` implements in full,
    was never classified as one.

    The grammar's parser has had this rule since it learned to read a granted
    ability (``parser._split_on_colon`` over the tokens before the first
    quote); this is that rule on the string the compiler's line classifier
    reads, so the two front ends agree about where an ability begins.
    """
    in_quotes = False
    for index, character in enumerate(line):
        if character == '"':
            in_quotes = not in_quotes
        elif character == ":" and not in_quotes:
            return index
    return None


_MANA_ALTERNATIVE_RE = re.compile(
    r"\bpay \w+ life\b[^,:]*?\s+or\s+((?:\{[^}]+\})+)\s*$", re.IGNORECASE
)


def _split_mana_alternative(cost_part: str) -> tuple[str, dict[str, int] | None]:
    """*cost_part* with a trailing "… or {N}" removed, and the mana it named.

    "Pay 2 life **or {2}**" (Tidal Control) is one cost with a choice, and the
    two halves have to be told apart before anything reads either: the mana scan
    is a findall over the whole clause, so an alternative left in becomes part of
    ``required`` and the ability charges the life **and** the mana.

    Anchored to the end of the clause and to a preceding life payment, which is
    the only printed shape — a bare "or" elsewhere in a cost clause is not this,
    and returning the clause unchanged leaves whatever reads it next to refuse.
    """
    match = _MANA_ALTERNATIVE_RE.search(cost_part)
    if match is None:
        return cost_part, None
    alternative: dict[str, int] = {}
    for token in _MANA_TOKEN_RE.findall(match.group(1).upper()):
        if token.isdigit():
            alternative["generic"] = alternative.get("generic", 0) + int(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            alternative[token] = alternative.get(token, 0) + 1
        else:
            # A symbol this cannot price ({X}, {T} inside the alternative) —
            # leave the clause whole so the ability refuses rather than being
            # charged a cost nobody can pay.
            return cost_part, None
    if not alternative:
        return cost_part, None
    return cost_part[: match.start(1)].rstrip()[: -len("or")].rstrip(), alternative


#: "**Choose flying, first strike, trample, or shadow**" (Phyrexian Splicer),
#: as the cost clause leaves it. Delimited here and read by the keyword
#: vocabulary below, which is the split every other list in this file makes:
#: the regex says where the words are, the registry says what they mean.
_CHOOSE_KEYWORD_COST = re.compile(r"\bchoose ([a-z, ]+?)(?:,|$)\s*$")


def _chosen_keyword_options(cost_lower: str) -> tuple[str, ...]:
    """The keywords a "Choose A, B, or C" cost clause offers, or ``()``.

    The second reader of a cost clause this file keeps (the grammar's is
    ``engine/grammar/costs.py``), and it has to agree with the first or the
    ability compiles and then charges a cost nobody announced. So the gate is
    the same one: two or more options, every one of them a keyword the engine
    implements. Anything else is ``()``, which the grammar has already refused
    the line for — the pair fails closed rather than half-open.
    """
    match = _CHOOSE_KEYWORD_COST.search(cost_lower.strip())
    if match is None:
        return ()
    from .grammar.vocabulary import IMPLEMENTED_KEYWORDS
    from .keywords import keyword_ability_name

    words = [
        part.strip()
        for chunk in match.group(1).split(",")
        for part in [chunk.strip()]
        if part
    ]
    options = [
        word[len("or "):].strip() if word.startswith("or ") else word
        for word in words
    ]
    if len(options) < 2 or any(
        keyword_ability_name(option) not in IMPLEMENTED_KEYWORDS
        for option in options
    ):
        return ()
    return tuple(options)


#: "Pay {1} for each +1/+1 counter on this creature" (Skeleton Scavengers).
#: The grammar's ``_accept_mana_run`` + ``_accept_per_counter`` pair, read as
#: prose because this is the reader that *builds the cost*: the grammar
#: consumes the clause so the line parses, and nothing lowers a cost node.
#: The two therefore have to admit the same clauses, which is why both require
#: the "for each" tail and both count only the ability's own source.
_MANA_PER_COUNTER_COST = re.compile(
    r"\bpay ((?:\{[^{}]+\})+) for each ([a-z]+|[+-]\d+/[+-]\d+) counters? "
    r"on this [a-z]+\b"
)


def _split_mana_per_counter(
    cost_part: str,
) -> tuple[str, dict[str, int] | None, str | None]:
    """*cost_part* with a per-counter mana payment removed, plus what it costs.

    ``(remaining clause, one counter's symbols, the counter's name)``. The
    clause is **taken out** rather than merely read, because the mana scan that
    follows would otherwise add the rate to the flat cost as well -- a cost
    charged twice at the first counter and far too little at the fifth.
    """
    match = _MANA_PER_COUNTER_COST.search(cost_part.lower())
    if match is None:
        return cost_part, None, None
    rate = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    for token in _MANA_TOKEN_RE.findall(match.group(1).upper()):
        if token.isdigit():
            rate["generic"] += int(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            rate[token] += 1
        else:
            # {T} or {X} in a rate: a shape neither reader charges. Left in the
            # clause so the mana scan sees it and the grammar refuses the line,
            # rather than being silently dropped.
            return cost_part, None, None
    remaining = cost_part[: match.start()] + cost_part[match.end():]
    return remaining, rate, match.group(2)


_MILL_COST = re.compile(r"\bmill (an?|\w+) cards?\s*(?=,|$)")


def _mill_cost(cost_lower: str) -> int:
    """How many cards a "**Mill a card**" cost clause mills, or 0.

    "{T}, Mill a card: Add {C}." (Millikin.) The charging half of
    ``grammar/costs.py``'s mill branch, admitting exactly what that admits: an
    article or a printed number, and nothing after the noun — "mill a card
    from target player's library" is not this cost and has no payment path.
    The regex delimits the count and ``_NUMBER_WORDS`` reads it, the split
    every counted clause in this file makes; a word that is not a number
    charges nothing, which the pool-wide cost guard names.
    """
    match = _MILL_COST.search(cost_lower)
    if match is None:
        return 0
    word = match.group(1)
    if word in ("a", "an"):
        return 1
    number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
    return number if number >= 2 else 0


_CONJOINED_SELF_COST = re.compile(
    rf"\b(sacrifice|exile) (?!this\b)([^,:]+?) and this (?:{_SELF_COST_NOUNS})\b"
    r"\s*(?=,|$)"
)


def _split_conjoined_self(cost_lower: str) -> tuple[str, frozenset[str]]:
    """*cost_lower* with every "… **and this <permanent>**" tail removed, plus
    the verbs whose tail it was.

    "{T}, Sacrifice two lands **and this artifact**" (Sandstone Deadfall);
    "{T}, Exile two cards from your graveyard **and this creature**" (Zombie
    Assassin). One printed verb naming a chosen set *and* the ability's own
    source, source last — the mirror of Kyscu Drake's "Sacrifice this creature
    and a creature named …", which names it first and has its own reader.

    The tail is **taken out** rather than merely noticed, for the reason
    :func:`_split_mana_per_counter` takes its clause out: every reader below
    delimits a noun phrase to the end of its cost segment, so "two lands and
    this artifact" reached the noun parser whole, was refused whole, and the
    cost was charged as *nothing* — Sandstone Deadfall destroyed an attacker
    for {T} and stayed on the battlefield with its controller's lands.

    One reader for both verbs because it is one shape: what differs is which
    flag the source rides (``sacrifice_self`` / ``exile_self``), and the caller
    sets that only once the chosen half has been read. ``(?!this\\b)`` keeps the
    source-first spelling with its own reader, and ``[^,:]`` keeps an Oxford
    list ("a creature named …, a creature named …, and this creature") with
    the list reader, which already counts its source.
    """
    verbs: set[str] = set()

    def strip(match: "re.Match[str]") -> str:
        verbs.add(match.group(1))
        return f"{match.group(1)} {match.group(2)}"

    return _CONJOINED_SELF_COST.sub(strip, cost_lower), frozenset(verbs)


def parse_activated_ability_cost(
    line: str, card_name: str | None = None
) -> ActivatedAbilityCost:
    required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    requires_tap = False
    colon = activation_colon_index(line or "")
    if colon is None:
        return ActivatedAbilityCost(required, requires_tap)

    cost_part = line[:colon]
    # "Pay 2 life **or {2}**" (Tidal Control). CR 601.2h's choice between two
    # printed payments, split off the clause *before* the mana scan below — a
    # scan that read the whole clause would put the alternative into `required`
    # beside the life and charge both halves of an "or", which is exactly what
    # this reader did until the split existed.
    cost_part, alternative_mana = _split_mana_alternative(cost_part)
    # "**Pay {1} for each +1/+1 counter on this creature**" (Skeleton
    # Scavengers). Split off before the mana scan below for
    # ``_split_mana_alternative``'s reason: a scan that read the whole clause
    # would put the *rate* into ``required`` and charge it flat, which is a
    # regeneration that stays {1} however large the creature has grown.
    cost_part, per_counter_mana, per_counter_counter = (
        _split_mana_per_counter(cost_part)
    )
    loyalty, loyalty_x_sign = _parse_loyalty_cost(cost_part)
    if loyalty is not None or loyalty_x_sign is not None:
        # A loyalty symbol is the whole cost (CR 606.4); reading the clause
        # again as prose would misread "+1" as a bare number and charge nothing.
        return ActivatedAbilityCost(
            required, False, loyalty=loyalty, loyalty_x_sign=loyalty_x_sign
        )
    for token in _MANA_TOKEN_RE.findall(cost_part.upper()):
        if token == "T":
            requires_tap = True
            continue
        if token.isdigit():
            required["generic"] += int(token)
            continue
        if token in {"W", "U", "B", "R", "G", "C"}:
            required[token] += 1
    # Non-mana additional costs written as prose in the cost clause. Only the
    # clause left of the ":" counts — "Draw a card" as an effect must not be read
    # as a cost.
    #
    # "{1}{W}, Sacrifice **Lieutenant Kirtar**: …" A legendary permanent names
    # itself where every other card prints "this creature" (CR 201.5), and the
    # grammar reads the two as one reference - the lexer collapses the name to
    # a SELF token. Collapsed here to the same words, so the self-cost readers
    # below see one sentence: unread, the grammar admitted the line and this
    # charger collected the mana and no sacrifice, which is the card kept on
    # the battlefield and its ability repeatable.
    cost_lower = _collapse_self_references(
        cost_part.lower(), card_name, "this permanent"
    )
    # "{T}, Sacrifice two lands **and this artifact**" (Sandstone Deadfall);
    # "{T}, Exile two cards from your graveyard **and this creature**" (Zombie
    # Assassin). Taken off the clause before any reader below sees it — see
    # :func:`_split_conjoined_self` — and put back as the source's own flag
    # once the chosen half has been read.
    cost_lower, conjoined_self = _split_conjoined_self(cost_lower)
    discard_last_drawn = "discard the last card you drew this turn" in cost_lower
    exile_self = bool(
        re.search(rf"\bexile this ({_SELF_COST_NOUNS})\b", cost_lower)
    )
    # "**Exile this card from your hand**: Add {G}." (Elvish Spirit Guide.)
    # The source, named as a *card* because that is what it is where this cost
    # can be paid — and "card" is deliberately not among ``_SELF_COST_NOUNS``,
    # so the line above read nothing and the ability compiled with **no cost
    # at all**: on the battlefield the Guide made {G} for free as often as it
    # was asked, and in a hand, where the card says the ability is, it could
    # not be activated. Both halves are one fact (CR 113.6j) and it rides the
    # two fields that already say it: the source is what is exiled, and the
    # zone it is exiled from is a hand. ``activation_zones`` reads that pair.
    exile_self_from_hand = bool(
        re.search(r"\bexile this card from your hand\b", cost_lower)
    )
    exile_self = exile_self or exile_self_from_hand
    # "Exile a creature you control" (City of Shadows) / "Exile a creature
    # card from your graveyard" (Necropolis) - a *chosen* object rather than
    # the source. The regex only **delimits** the noun phrase to the end of
    # its comma-separated cost segment, exactly as the sacrifice one below
    # does; what the phrase names is read by the noun parser, because a regex
    # approximating it is a second reader of one clause and the direction
    # those drift in is a cost charged more widely than the card prints.
    # "Exile **the top card of your library**" / "…the top **two** cards…"
    # (Royal Herbalist, Whirling Catapult, Phyrexian Devourer). The one exile
    # cost whose tail is not a noun phrase — the cards are named by position —
    # so it is read here rather than handed to the noun parser, and read
    # *before* the chosen-object patterns below, which would otherwise find
    # nothing at all and charge the cost as none.
    #
    # The count is delimited by the regex and read by ``_NUMBER_WORDS``, the
    # split every other counted clause in this file makes. A word that is not a
    # number leaves the cost unread, which keeps this reader and the grammar's
    # (``grammar/costs._accept_exile_top_of_library``, which admits only a fixed
    # positive count) admitting exactly the same clauses.
    # "**Put a card from your hand on top of your library**:" (Hidden Retreat).
    # The cost's twin of the grammar's ``PutHandCardOnLibraryCost``, admitting
    # exactly the words that one admits — a second reader of one clause is how
    # a cost comes to be charged more widely than the card prints. Anchored on
    # the whole phrase for that reason: "put a card on top of your library" with
    # no zone named is a different payment and has no charger.
    hand_to_library_top = 1 if re.search(
        r"\bput a card from your hand on top of your library\b",
        cost_lower,
    ) else 0
    exile_top_of_library = 0
    top_exile = re.search(
        r"\bexile the top (?:(\w+) cards|card) of your library\b", cost_lower
    )
    if top_exile is not None:
        word = top_exile.group(1)
        if word is None:
            exile_top_of_library = 1
        else:
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            exile_top_of_library = number if number >= 2 else 0
    # "Exile **the top card of your graveyard**" (Alms, Nature's Kiss), "...the
    # top **creature** card..." (Necratog, Zombie Scavengers). The library
    # form's twin one zone over, read the same way and in the same position:
    # the cards are named by position (CR 404.3), so the chosen-object patterns
    # below would find nothing at all and charge the cost as none.
    #
    # The regex only **delimits** the phrase to the end of its comma-separated
    # cost segment; what it names is read by the grammar's own production
    # (``phrases.accept_graveyard_position``, through
    # ``grammar.graveyard_position_payload_for``), because a regex approximating
    # it is a second reader of one clause and the direction those drift in is a
    # cost charged more widely than the card prints. ``seats={"you"}`` is the
    # same narrowing ``grammar/costs.py`` applies: an activation cost paid out
    # of somebody else's graveyard is a shape no payment path has a seat for.
    exile_graveyard_position = None
    if not exile_self and not exile_top_of_library:
        from .grammar import graveyard_position_payload_for

        graveyard_exile = re.search(
            r"\bexile (the (?:top|bottom) [^,:]+?)\s*(?=,|$)", cost_lower
        )
        if graveyard_exile is not None:
            exile_graveyard_position = graveyard_position_payload_for(
                graveyard_exile.group(1), seats=frozenset({"you"})
            )
    chosen_exile = (
        None if exile_self or exile_top_of_library or exile_graveyard_position
        else re.search(r"\bexile ((?:another|an?) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    exile_filter = (
        _chargeable_exile_filter(chosen_exile.group(1)) if chosen_exile else None
    )
    # Which zone it comes out of. Read off the same phrase rather than
    # guessed: a graveyard payment enumerates cards and a battlefield one
    # enumerates permanents, and answering the wrong one exiles nothing while
    # the ability still resolves.
    # "…**from your hand**" (Cadaverous Bloom) is the third zone, read off the
    # same phrase for the same reason the graveyard is: a hand payment
    # enumerates cards the payer holds, and answering "battlefield" would look
    # for a permanent that is not there and charge nothing while the ability
    # still resolved.
    exile_zone = "hand" if exile_self_from_hand else "battlefield"
    if chosen_exile is not None:
        phrase = chosen_exile.group(1)
        if "from your graveyard" in phrase:
            exile_zone = "graveyard"
        elif "from your hand" in phrase:
            exile_zone = "hand"
    exile_zone_owner: str | None = "you"
    exile_count = 1
    exile_same_zone = False
    # "Exile **two** creature cards **from a single graveyard**" (Night Soil).
    # The counted twin of the singular above, and the sacrifice's twin one zone
    # over: "an?" cannot match "two", so the singular pattern found nothing at
    # all and the cost was charged as none.
    #
    # "a single graveyard" is two facts in three words — the pile may be
    # anybody's, and every card must come out of the same one. The first is
    # rewritten to the phrase the noun parser already reads ("a graveyard") so
    # there is one reader of a zone tail; the second has no filter to live on
    # and is recorded beside the count.
    if (
        exile_filter is None
        and not exile_self
        and not exile_top_of_library
        and exile_graveyard_position is None
    ):
        counted_exile = re.search(
            r"\bexile (\w+) ([^,:]+?)\s*(?=,|$)", cost_lower
        )
        if counted_exile is not None:
            word = counted_exile.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            phrase = counted_exile.group(2)
            if number >= 2:
                if "from a single graveyard" in phrase:
                    phrase = phrase.replace(
                        "from a single graveyard", "from a graveyard"
                    )
                    exile_same_zone = True
                narrowed = _chargeable_exile_filter(phrase, plural=True)
                if narrowed is not None:
                    exile_filter = narrowed
                    exile_count = number
                    if "graveyard" in phrase:
                        exile_zone = "graveyard"
                        exile_zone_owner = (
                            "you" if "from your graveyard" in phrase else None
                        )
    # "Exile **any number of** cards from your graveyard" (Painbringer). The
    # count left to the payer, which is the sacrifice's "any number of" one
    # verb over and is carried the same way: the same filter field, with the
    # count saying it is a choice. The counted row above read "any" as a word
    # that is not a number and charged nothing.
    #
    # Only "from your graveyard" — anchored in the regex rather than checked
    # afterwards, because the activation path names the set by graveyard slot
    # (``cost_graveyard_indices``) and has no such channel for a battlefield or
    # a hand; the grammar refuses the other zones with the same words.
    if exile_filter is None and not exile_self:
        any_exile = re.search(
            r"\bexile any number of ([^,:]+? from your graveyard)\s*(?=,|$)",
            cost_lower,
        )
        if any_exile is not None:
            narrowed = _chargeable_exile_filter(any_exile.group(1), plural=True)
            if narrowed is not None:
                exile_filter = narrowed
                exile_count = "any"
                exile_zone = "graveyard"
                exile_zone_owner = "you"
    # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman). Older
    # printings name the card instead of saying "this artifact", so accept
    # either wording.
    #
    # **"Aura" is one of the words a card prints for its own type**, and it was
    # missing from this list for as long as the list existed. Scryfall's oracle
    # text for an Aura says "Sacrifice this **Aura**" and never "this
    # enchantment", so five shipped cards — Briar Shield, Carapace, Fire Whip,
    # Phantom Wings and Thrull Retainer — carried an activation cost nothing
    # charged: the ability was repeatable at will and the Aura never left the
    # battlefield. Nothing failed, because a cost this reader cannot see is not
    # a missing feature but a *cheaper card*, which is the direction
    # ``engine/cast_costs.py`` exists to refuse one announcement step earlier.
    #
    # A subtype among card types because those are the two vocabularies a
    # permanent uses to name itself (CR 205.3g, CR 301.5). Two wave-2
    # branches found this bug independently and fixed it twice - one by
    # adding "aura" to the hand-written alternation, one by deriving the
    # whole set from the grammar's ``_SELF_NOUNS``. The derived one is what
    # survived the merge, because the alternation *was* the bug: a second
    # copy of a list this file already owns, which went stale the moment a
    # subtype was printed.
    sacrifice_self = bool(
        re.search(rf"\bsacrifice this ({_SELF_COST_NOUNS})\b", cost_lower)
        # "Remove five fuse counters from this enchantment **and sacrifice
        # it**" (Goblin Bomb). The pronoun names the permanent the clause in
        # front of it just named, so it is read as part of that clause rather
        # than on its own: a bare "sacrifice it" anywhere in a cost would be a
        # referent this reader cannot resolve, and charging the source for it
        # would be a guess. The grammar reads the same two words in the same
        # position (``costs._parse_costs``'s remove branch), so the two halves
        # of the clause cannot admit different sentences.
        or re.search(
            rf"\bfrom this ({_SELF_COST_NOUNS}) and sacrifice it\b",
            cost_lower,
        )
    )
    # "Return this enchantment to its owner's hand" (Cycle of Life) — the same
    # shape one zone over, anchored the same way and admitting the same nouns,
    # because which word a card prints for its own type is not a difference the
    # cost has.
    return_self_to_hand = bool(
        re.search(
            rf"\breturn this ({_SELF_COST_NOUNS}) to its owner's hand\b",
            cost_lower,
        )
    )
    # "Sacrifice a creature" / "Sacrifice another creature" / "Sacrifice a
    # creature with defender" — a *chosen* permanent (Atog, Hobblefiend,
    # Portcullis Vine). The regex only **delimits** the noun phrase, to the end
    # of its comma-separated cost segment; what the phrase names is read by the
    # noun parser, exactly as a narrowed trigger condition's `_subject` group is
    # (round 34). A regex approximating the noun parser is a second reader of
    # one clause, and the direction those drift in is a cost charged more widely
    # than the card prints.
    # "Sacrifice **a creature named Feral Shadow, a creature named
    # Breathstealer, and this creature**" (Urborg Panther). An Oxford list of
    # objects under one printed verb, which the single-object delimiter below
    # cannot see at all: it stops at the first comma, so it read the Shadow,
    # missed the Breathstealer and missed the source — a cost charged as one
    # third of what the card prints, which is the direction that activates an
    # ability for less than it says.
    #
    # Found *before* that delimiter and consumed after it, so the two cannot
    # both claim the phrase. The whole match must end in "and <object>", which
    # is what keeps a comma separating two *costs* ("Sacrifice a creature, {T}:
    # …") from reading as a separator inside one. The grammar reads the same
    # shape (`costs._accept_sacrifice_list_tail`) and caps it at what these
    # three fields can hold, which is what keeps the two readers of this clause
    # from admitting different sentences.
    sacrifice_list = re.search(
        r"\bsacrifice ((?:(?:another|an?|this) [^,:]+, )+"
        r"and (?:another|an?|this) [^,:]+?)\s*(?=,|$)",
        cost_lower,
    )
    sacrifice_list_items = (
        [
            part.strip()
            for part in sacrifice_list.group(1).replace(", and ", ", ").split(", ")
            if part.strip()
        ]
        if sacrifice_list is not None
        else None
    )
    chosen_sacrifice = (
        None if sacrifice_self or sacrifice_list_items is not None
        else re.search(r"\bsacrifice ((?:another|an?) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    sacrifice_filter = (
        _chargeable_sacrifice_filter(chosen_sacrifice.group(1))
        if chosen_sacrifice
        else None
    )
    # "Sacrifice a creature **and a Swamp**" (Viscerid Drone). One printed verb
    # naming two different objects, which the delimiter above swallows whole —
    # and the noun parser then refuses "a creature and a swamp", so the cost was
    # charged as *none at all*. Split only after the whole phrase has been
    # tried, so every reading that worked before is byte-identical: a noun
    # phrase that legitimately contains "and" keeps it.
    sacrifice_also_filter = None
    if (
        sacrifice_filter is None
        and chosen_sacrifice is not None
        and " and " in chosen_sacrifice.group(1)
        and "any number of" not in chosen_sacrifice.group(1)
    ):
        first, _, second = chosen_sacrifice.group(1).partition(" and ")
        first_filter = _chargeable_sacrifice_filter(first.strip())
        second_filter = _chargeable_sacrifice_filter(second.strip())
        if first_filter is not None and second_filter is not None:
            sacrifice_filter = first_filter
            sacrifice_also_filter = second_filter
    if sacrifice_list_items is not None:
        # "…and **this creature**" is the source, which has its own flag and
        # no filter — the charger sacrifices the ability's own source rather
        # than picking a permanent that matches a phrase.
        chosen_items = [
            item for item in sacrifice_list_items if not item.startswith("this ")
        ]
        filters = [_chargeable_sacrifice_filter(item) for item in chosen_items]
        if len(chosen_items) <= 2 and all(f is not None for f in filters):
            sacrifice_self = sacrifice_self or len(chosen_items) < len(
                sacrifice_list_items
            )
            sacrifice_filter = filters[0] if filters else None
            sacrifice_also_filter = filters[1] if len(filters) > 1 else None
    # "Sacrifice this artifact **and any number of creatures you control**"
    # (Sword of the Ages). One printed cost naming two things: the source, read
    # above, and a *set* whose size the payer chooses. The same field carries
    # the noun phrase — it is the same question, "what may pay this?" — with
    # ``sacrifice_count`` saying how many, exactly as ``remove_counter_count``
    # does one cost up. Without this the tail matched nothing at all and the
    # ability sacrificed only itself, so its X was always zero.
    sacrifice_count: int | str = 1
    # "Sacrifice **two** Goblins" (Goblin Warrens). The count is printed in
    # front of the noun phrase, which leaves that phrase the bare plural
    # ``plural=True`` reads — the same split the "any number of" tail below
    # makes, with a number where that one has a choice. Read *before* the
    # singular match above could have run, which is why it is a separate regex
    # rather than a widening of it: "an?" cannot match "two", so the singular
    # pattern found nothing at all and the cost was charged as none.
    if sacrifice_filter is None and not sacrifice_self:
        counted = re.search(
            r"\bsacrifice (\w+) ([^,:]+?)\s*(?=,|$)", cost_lower
        )
        if counted is not None:
            word = counted.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            # "Sacrifice **X** lands" (Copper-Leaf Angel): the announced count,
            # carried as ``"x"`` the way ``remove_counter_count`` carries Kyren
            # Toy's — "x" is not in ``_NUMBER_WORDS``, so it read as 0 and the
            # cost as none at all.
            if number >= 2 or word == "x":
                narrowed = _chargeable_sacrifice_filter(
                    counted.group(2), plural=True
                )
                if narrowed is not None:
                    sacrifice_filter = narrowed
                    sacrifice_count = "x" if word == "x" else number
    any_number_sacrifice = re.search(
        r"\bsacrifice [^,:]*?\band any number of ([^,:]+?)\s*(?=,|$)", cost_lower
    )
    if sacrifice_filter is None and any_number_sacrifice is not None:
        sacrifice_filter = _chargeable_sacrifice_filter(
            any_number_sacrifice.group(1), plural=True
        )
        if sacrifice_filter is not None:
            sacrifice_count = "any"
    # "Sacrifice this creature **and a creature named Spitting Drake**" (Kyscu
    # Drake). The source and one chosen permanent under one printed verb, joined
    # by a bare "and" with no comma in front of it — which is exactly the shape
    # every reader above declines. The Oxford-list regex needs at least one
    # comma to match; the single-object delimiter is switched off entirely once
    # "sacrifice this ..." has set ``sacrifice_self``; and "any number of" reads
    # a set rather than one object. So the second half was read by nothing and
    # the ability cost the source alone — an activation cheaper than the card,
    # which is the direction that never crashes and never shows.
    #
    # Encoded the way the Oxford-list path already encodes the same facts: the
    # source in its flag, the chosen permanent in ``sacrifice_filter``. Guarded
    # on that field being empty so it runs only where every earlier reader
    # declined, which keeps Sword of the Ages' "and any number of creatures you
    # control" with the reader that understands its count.
    if sacrifice_self and sacrifice_filter is None:
        conjoined = re.search(
            r"\bsacrifice this \w+ and ((?:another|an?) [^,:]+?)\s*(?=,|$)",
            cost_lower,
        )
        if conjoined is not None:
            sacrifice_filter = _chargeable_sacrifice_filter(conjoined.group(1))
    # "Discard a card" (Seasoned Hallowblade), "Discard a land card or Shrine
    # card" (Sanctum of Shattered Heights). Jandor's Ring's history-named card is
    # read above; counting it here too would charge the Ring twice.
    #
    # The regex only **delimits** the noun phrase, to the end of its
    # comma-separated cost segment, exactly as the sacrifice one above does; what
    # the phrase names is read by the noun parser through
    # `_chargeable_discard_filters`. The count comes off that reader rather than
    # off a second regex, so a phrase it refuses charges no discard at all
    # instead of charging the unnarrowed one.
    #
    # "Discard **two** cards" (Prophecy's spellshapers) is the same clause with
    # a printed count, and the regex admits a leading number word beside the
    # article. What the whole phrase means — the count off the front, "at
    # random" off the back, the noun phrase through
    # `_chargeable_discard_filters` — is `cast_costs.read_discard_clause`, the
    # reader Forbid's identically printed buyback is charged through, so the
    # count is one answer on both sides of CR 602.2b's "as 601.2b–h".
    discarded = (
        None if discard_last_drawn
        else re.search(r"\bdiscard ((?:an?|\w+) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    discard_phrase = discarded.group(1) if discarded else None
    if discard_phrase is not None:
        # Only an article or a count of two or more opens a chosen discard:
        # "discard your hand" and "discard this card" are their own fields
        # below, and a phrase opening on any other word is not this cost.
        head = discard_phrase.split(" ", 1)[0]
        if head not in ("a", "an") and not (
            int(head) if head.isdigit() else _NUMBER_WORDS.get(head, 0)
        ) >= 2:
            discard_phrase = None
    discard_read = read_discard_clause(discard_phrase) if discard_phrase else None
    if discard_read is not None and discard_read[3]:
        # Counted by an X: no activation announces one (the head test above
        # admits only an article or a printed number), so such a reading would
        # be a quantity nothing charges.
        discard_read = None
    discard_filters = None if discard_read is None else discard_read[0]
    discard_count = 0 if discard_read is None else discard_read[1]
    # "Discard a card **at random**" (Coral Helm). Recorded so the payment path
    # draws rather than lets the payer name one.
    discard_at_random = bool(discard_read and discard_read[2])
    # "Tap two untapped Spirits you control" (Shacklegeist). The {T} symbol was
    # already consumed above as mana; this is the spelled-out form, which taps
    # *other* permanents.
    tap_cost = _chargeable_tap_cost(cost_lower)
    # "Return a Forest you control to its owner's hand" (Quirion Ranger).
    # The same shape one zone over, and read after the tap cost for no reason
    # but that the two never share a segment.
    return_cost = _chargeable_return_to_hand_cost(cost_lower)
    # "Discard your hand" (Subira). Matched here rather than folded into the
    # phrase above, because it is not a count: there is no card for the payer to
    # name and no filter to test, and it is payable with an empty hand.
    discard_whole_hand = bool(re.search(r"\bdiscard your hand\b", cost_lower))
    # "Discard this card" (Waker of Waves) - the card itself, from the hand.
    discard_self = bool(re.search(r"\bdiscard this card\b", cost_lower))
    # "Put a page counter on this artifact" (Mazemind Tome). The kind runs
    # ``[a-z]+`` **or** the P/T spelling, for the reason the removal regex below
    # states in full: a P/T counter is written in symbols (CR 122.1a), and a
    # cost clause that matches nothing is not a refused ability but a free one.
    counter_cost = re.search(
        r"\bput an? ([a-z]+|[+-]\d+/[+-]\d+) counter on this ", cost_lower
    )
    put_counter = counter_cost.group(1) if counter_cost else None
    # "Put a **-1/-1** counter on **a creature you control**" (Wandering Mage) —
    # the same cost aimed somewhere other than the source. The regex only
    # *delimits* the noun phrase, to the end of its cost segment, exactly as the
    # sacrifice and discard ones above do; what the phrase names is read by the
    # noun parser through ``_chargeable_counter_target``, so a phrase it refuses
    # charges no counter at all rather than charging an unnarrowed one.
    put_counter_filter = None
    if put_counter is None:
        chosen_counter = re.search(
            r"\bput an? ([a-z]+|[+-]\d+/[+-]\d+) counter on (an? [^,:]+?)\s*(?=,|:|$)",
            cost_lower,
        )
        if chosen_counter is not None:
            put_counter_filter = _chargeable_counter_target(chosen_counter.group(2))
            if put_counter_filter is not None:
                put_counter = chosen_counter.group(1)
    # "Remove a corpse counter from this creature" (Scavenging Ghoul), and the
    # ability Life Matrix grants with its own counter's word. Read out of the
    # phrase rather than listed, for the reason CR 122.1 gives: the kinds are
    # open, and a card - or a grant - may invent one.
    # A P/T counter is spelled in symbols, not letters (CR 122.1a), so
    # ``[a-z]+`` matched nothing at all for it — and an activation cost that
    # matches nothing is not a refused ability, it is a **free** one. Triskelion
    # ("Remove a +1/+1 counter from this creature: It deals 1 damage to any
    # target.") pinged for one damage per activation forever, with its three
    # counters untouched; Balduvian Hydra's "+1/+0" prevention shield did the
    # same. Both compiled clean, and nothing could have caught it but reading
    # the parsed cost.
    # "{2}, Remove a +1/+1 counter from **a creature you control**" (Spike
    # Rogue) — the same cost paid off a permanent the payer picks. The mirror of
    # ``put_counter_filter`` above and read exactly as it is: the regex only
    # *delimits* the noun phrase to the end of its cost segment, and what the
    # phrase names is read by the noun parser through
    # ``_chargeable_counter_target``, so a phrase it refuses charges no counter
    # at all rather than charging an unnarrowed one.
    #
    # Read **before** every self-referring row below and not after them, which
    # is the whole of what makes it correct: the plain row's "from " matches
    # anything at all, so a chosen phrase read second is read as the *source's*
    # counter — Spike Rogue paying by shrinking itself and growing itself back,
    # an ability that costs nothing and can be activated for ever. The chosen
    # regex cannot make the opposite mistake: it requires the phrase to open
    # with "a"/"an", which no self-reference does.
    remove_counter_filter = None
    remove_counter = None
    remove_counter_count: int | str = 1
    chosen_removal = re.search(
        r"\bremove an? ([a-z]+|[+-]\d+/[+-]\d+) counter from "
        r"(an? [^,:]+?)\s*(?=,|:|$)",
        cost_lower,
    )
    if chosen_removal is not None:
        remove_counter_filter = _chargeable_counter_target(chosen_removal.group(2))
        if remove_counter_filter is not None:
            remove_counter = chosen_removal.group(1)
    if remove_counter is None:
        removal_cost = re.search(
            r"\bremove an? ([a-z]+|[+-]\d+/[+-]\d+) counter from ", cost_lower
        )
        remove_counter = removal_cost.group(1) if removal_cost else None
    if remove_counter is None:
        # "Remove **any number of** charge counters from this artifact" (the
        # five Mana Batteries). The same cost with the count left to the payer,
        # so it is the same field plus how many — not a second cost. Without
        # this row the clause matched nothing at all: the ability was activated
        # for free, forever, and its effect had no number to read.
        any_number = re.search(
            r"\bremove any number of ([a-z]+) counters from ", cost_lower
        )
        if any_number is not None:
            remove_counter = any_number.group(1)
            remove_counter_count = "any"
    if remove_counter is None:
        # "Remove **all** elixir counters from this artifact" (Essence Bottle,
        # Torture Chamber). The fourth row this pattern has needed, and the
        # fourth for one reason: a spelling nothing matched is not a refused
        # ability, it is a **free** one — both cards were activated without
        # paying and their effects, which count what the cost removed, had no
        # number to read. The grammar had already parsed the clause into a
        # `RemoveCounterCost` with an `AllOf` count; this derivation is the
        # second reader, and the two disagreed.
        #
        # "All" is not "any number": there is no choice to announce, so an
        # announced X never narrows it. Payable with none on the permanent —
        # removing all of zero counters removes zero (CR 601.2h has nothing
        # that cannot be done), which is the printed card: Essence Bottle
        # activated empty gains no life.
        all_of = re.search(
            r"\bremove all ([a-z]+|[+-]\d+/[+-]\d+) counters from ", cost_lower
        )
        if all_of is not None:
            remove_counter = all_of.group(1)
            remove_counter_count = "all"
    if remove_counter is None:
        # "Remove **X** charge counters from this artifact" (Kyren Toy,
        # Mercadian Lift). The count the *activator* announces (CR 601.2b),
        # which is what separates it from the three rows around it: a printed
        # number is on the card, "all" is on the permanent, and this one is not
        # known until the ability is activated.
        #
        # Its own row rather than a letter added to the counted row below,
        # because that row reads its word through ``_NUMBER_WORDS`` and "x" is
        # not a number -- it looked up to 0, failed the ``>= 2`` gate and left
        # ``remove_counter`` None, so the whole clause matched nothing and the
        # ability would have been activated for free. The grammar refused it,
        # which is the only reason that was invisible rather than exploitable.
        x_removal = re.search(
            r"\bremove x ([a-z]+) counters from ", cost_lower
        )
        if x_removal is not None:
            remove_counter = x_removal.group(1)
            remove_counter_count = "x"
    if remove_counter is None:
        # "Remove **three spore** counters from this creature" (Thallid and the
        # rest of Fallen Empires' Saproling engine), "Remove **two carrion**
        # counters from this creature" (Osai Vultures). A *printed* count, and
        # the third row this pattern has needed for one reason: the singular
        # "an?" matched nothing at all, so the ability was activated for free
        # and could be activated forever -- Osai Vultures has been shipping an
        # unlimited +1/+1 since Legends was ingested, with its carrion counters
        # untouched.
        #
        # The regex only **delimits** the number; ``_NUMBER_WORDS`` reads it,
        # which is the split every other counted clause in this file makes. Read
        # after the "any number of" row above, whose opening words it would
        # otherwise have to exclude by hand.
        counted_removal = re.search(
            r"\bremove (\w+) ([a-z]+|[+-]\d+/[+-]\d+) counters from ",
            cost_lower,
        )
        if counted_removal is not None:
            word = counted_removal.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            if number >= 2:
                remove_counter = counted_removal.group(2)
                remove_counter_count = number
    # The source a conjoined tail named, charged only where the chosen half in
    # front of it was read: with that half unread the clause charges nothing at
    # all, which is the answer the pool-wide guard compares against the
    # grammar's and names — a source charged alone would be a third of the
    # printed cost passing as the whole of it.
    if "sacrifice" in conjoined_self and sacrifice_filter is not None:
        sacrifice_self = True
    if "exile" in conjoined_self and exile_filter is not None:
        exile_self = True
    return ActivatedAbilityCost(
        required, requires_tap, discard_last_drawn, exile_self, sacrifice_self,
        return_self_to_hand=return_self_to_hand,
        sacrifice_filter=sacrifice_filter,
        exile_filter=exile_filter,
        exile_zone=exile_zone,
        exile_zone_owner=exile_zone_owner,
        exile_count=exile_count,
        exile_same_zone=exile_same_zone,
        sacrifice_count=sacrifice_count,
        tap_filter=tap_cost[1] if tap_cost else None,
        tap_count=tap_cost[0] if tap_cost else 0,
        return_to_hand_filter=return_cost[1] if return_cost else None,
        return_to_hand_count=return_cost[0] if return_cost else 0,
        discard_cards=discard_count,
        discard_filters=discard_filters or (),
        discard_at_random=discard_at_random,
        discard_whole_hand=discard_whole_hand,
        discard_self=discard_self,
        put_counter=put_counter,
        put_counter_filter=put_counter_filter,
        sacrifice_also_filter=sacrifice_also_filter,
        remove_counter=remove_counter,
        remove_counter_count=remove_counter_count,
        remove_counter_filter=remove_counter_filter,
        pay_life=_life_payment_cost(cost_lower),
        pay_life_per_counter=_life_payment_per_counter(cost_lower),
        pay_life_half_rounded_up=_life_payment_is_half_rounded_up(cost_lower),
        mana_per_counter=per_counter_counter,
        mana_per_counter_cost=per_counter_mana,
        alternative_mana=alternative_mana,
        tap_attached=_taps_the_attached_permanent(cost_lower),
        sacrifice_attached=_sacrifices_the_attached_permanent(cost_lower),
        mana_from_attached=_pays_the_attached_permanents_mana_cost(cost_lower),
        exile_top_of_library=exile_top_of_library,
        hand_to_library_top=hand_to_library_top,
        exile_graveyard_position=exile_graveyard_position,
        untap_filter=_chargeable_untap_cost(cost_lower),
        chosen_keyword_options=_chosen_keyword_options(cost_lower),
        mill_cards=_mill_cost(cost_lower),
    )
