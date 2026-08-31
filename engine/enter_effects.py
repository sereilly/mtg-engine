"""Phrases for the "as/when this permanent enters" entry state (CR 614.1c).

A handful of printed lines describe what a permanent looks like *the moment it
arrives*, or a standing permission its controller gains while it is out: it
enters tapped, it enters with counters, it enters as a copy, its controller
chooses an opponent, has no maximum hand size, may spend white mana as red.
None of them is an effect that goes on the stack, so none of them has an
``OracleInstruction``. They are performed by
:meth:`engine.mixins.permanent_state.PermanentStateMixin._initialize_permanent_state`,
which probes the permanent's own normalized oracle text as it enters.

That probing is the reason this module exists. The phrases used to be string
literals inside the mixin, which meant any other reader of the same behaviour —
the parse-coverage tracker, ``engine/grammar/registries.py`` — had to copy them,
and a copy is free to drift out of sync with the code that actually runs. Here
there is **one** string per behaviour and two readers of it, so a phrase cannot
be renamed on one side only.

:func:`enter_effect_line` answers the second reader's question: does the
*entire* printed line describe entry state the mixin performs? That is
deliberately narrower than the mixin's own substring probes. The mixin asks
"does this card's text mention entering tapped anywhere?"; a line is only
claimed here when the mixin's phrase, plus at most a self-referential subject
and a tail the mixin also implements, is the whole of it. A line that is an
entry effect *plus something else* stays unclaimed — Vesuvan Doppelganger's
copy line carries a granted upkeep ability that this code does not perform, and
claiming it would report as understood a wording nothing implements.
"""

from __future__ import annotations

import re

# --- CR 614.1c entry state, engine/mixins/permanent_state.py ---------------

# "This artifact enters tapped." (Nevinyrral's Disk, Time Vault). The mixin
# probes for this substring and excludes "unless", so a conditional wording
# ("enters tapped unless you pay …") is a different card.
ENTERS_TAPPED = "enters tapped"

# "As this artifact enters, choose an opponent." (Black Vise) and its two-choice
# sibling (Jihad). Separate constants because the mixin branches on them: the
# colour half is what decides whether an interactive caster is prompted.
CHOOSE_OPPONENT_ON_ENTER = "as this artifact enters, choose an opponent"
CHOOSE_COLOR_AND_OPPONENT_ON_ENTER = (
    "as this enchantment enters, choose a color and an opponent"
)

# "As this enchantment enters, choose a color." (Psychic Allergy.) / "As this
# **Aura** enters, choose a color." (Prismatic Ward, Chromatic Armor.) The
# colour half alone, and the noun is *data*: an Aura is an enchantment, and the
# card that spells the subtype is printing the same sentence.
#
# A pattern rather than a constant for exactly that reason — the literal read
# "enchantment" and nothing else, so the two Ice Age Auras printing this
# sentence about themselves reached nothing at all.
#
# Separate from the colour-and-opponent pair above because the mixin branches on
# which seats are asked: this one records no player, so the prompt it arms
# offers a colour and nothing else. The pair's phrase *starts* with this one,
# which is what the negative lookahead is for — without it Jihad's line would be
# claimed here and the opponent it names dropped.
_CHOOSE_COLOR_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose a color(?!s| and)"
)


def chooses_color_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for a colour as the permanent enters.

    A substring probe like the mixin's own, because the mixin asks it of the
    card's whole normalized text; :func:`enter_effect_line` asks the whole-line
    question through this same matcher, so what is performed and what is
    claimed cannot drift.
    """
    return bool(_CHOOSE_COLOR_ON_ENTER_RE.search(text or ""))

# "As this enchantment enters, choose a card name." (Runed Halo.) A *name*
# rather than a quality: nothing on any board constrains it, and the choice is
# made from the whole card pool — which is why the default below is a name the
# chooser can see rather than one derived from the battlefield.
CHOOSE_CARD_NAME_ON_ENTER = "as this enchantment enters, choose a card name"

# "This creature enters with seven +1/+0 counters on it." (Clockwork Beast.)
ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS = "enters with seven +1/+0 counters on it"

#: "This creature enters with **three +1/+1** counters on it." (Triskelion,
#: Tetravus) / "…**four +1/+0**…" (Clockwork Avian) / "…**seven +1/+0**…"
#: (Clockwork Beast). The number and the counter kind are data, the way every
#: other parameter in this file is: the two constants above were literal
#: sentences, so Clockwork Beast's seven worked and Triskelion's three did not,
#: for no reason anyone had decided.
#:
#: The X form stays its own constant — its count is not printed at all, it is
#: the value announced when the spell was cast, so it is read from a different
#: place at a different time.
ENTERS_WITH_PT_COUNTERS = re.compile(
    r"^this [a-z]+ enters with (?P<count>[a-z]+) "
    r"(?P<counter>\+1/\+1|\+1/\+0|\+0/\+1) counters on it$"
)


#: The **X** form of the sentence above: "…enters with X +1/+1 counters on it"
#: (Rock Hydra) / "…X +1/+0 counters…" (Balduvian Hydra). Its own pattern
#: because the count is not printed at all — it is the value announced when the
#: spell was cast, read from a different place at a different time — but the
#: *counter kind* is data here exactly as it is above. It was a literal
#: sentence naming +1/+1, which is why Rock Hydra worked and Balduvian Hydra,
#: printing the identical template one counter kind over, did not.
ENTERS_WITH_X_PT_COUNTERS = re.compile(
    r"^this [a-z]+ enters with x "
    r"(?P<counter>\+1/\+1|\+1/\+0|\+0/\+1) counters on it$"
)


def enters_with_x_pt_counters(line: str, card_name: str | None = None) -> str | None:
    """The counter kind an "enters with X … counters" line places, or None.

    Read by the entry state and by the support gate, like its printed-count
    sibling, so what is placed and what is claimed cannot drift.
    """
    match = ENTERS_WITH_X_PT_COUNTERS.match(_self_normalized(line, card_name))
    return match.group("counter") if match is not None else None


def enters_with_pt_counters(line: str, card_name: str | None = None) -> tuple[int, str] | None:
    """``(count, counter kind)`` the line places, or None.

    Read by the entry state and by the support gate, so what is placed and what
    is claimed cannot drift. A number word the table does not know refuses the
    whole line rather than defaulting to one — a creature entering with one
    counter where the card prints four is a strictly smaller card, silently.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    match = ENTERS_WITH_PT_COUNTERS.match(_self_normalized(line, card_name))
    if match is None:
        return None
    count = NUMBER_WORDS.get(match.group("count"))
    if count is None:
        return None
    return count, match.group("counter")


#: "This Equipment enters with a soul counter on it." (Malefic Scythe) /
#: "Rasputin enters with **seven dream** counters on it." (Rasputin
#: Dreamweaver.) A **named** counter (CR 122.1) rather than a P/T one, so it is
#: matched by shape and both the word and the number are data: a card printing a
#: differently-named counter, or a different many of them, needs no entry.
#: Anchored on the whole sentence — a phrase that matched a prefix would place a
#: counter for a card that says something else afterwards.
#:
#: The count is optional in the printed text and never in the answer: an article
#: is the number one, which is the reading `ENTERS_WITH_PT_COUNTERS` beside this
#: one already gives its own spelled-out number.
ENTERS_WITH_NAMED_COUNTER = re.compile(
    r"^this [a-z]+ enters with (?P<count>a|[a-z]+) (?P<counter>[a-z]+) "
    r"counters? on it$"
)


def enters_with_named_counter(line: str, card_name: str | None = None) -> tuple[int, str] | None:
    """``(count, counter word)`` the line places, or None.

    Read by the entry state and by the support gate, so what is placed and what
    is claimed cannot drift.

    *card_name* collapses a card that names itself ("**Rasputin** enters with
    …") onto the self-reference the pattern is anchored on, through the same
    collapser the restriction tables use — a second one here is how a card
    compiles supported and then enters with nothing.
    """
    match = ENTERS_WITH_NAMED_COUNTER.match(_self_normalized(line, card_name))
    if match is None:
        return None
    printed = match.group("count")
    if printed in ("a", "an"):
        return 1, match.group("counter")
    from .grammar.vocabulary import NUMBER_WORDS

    count = NUMBER_WORDS.get(printed)
    # A number word the table does not know refuses the line rather than
    # defaulting to one, for the reason `enters_with_pt_counters` gives: a
    # permanent entering with one counter where the card prints seven is a
    # strictly smaller card, silently.
    return None if count is None else (count, match.group("counter"))

#: "As this creature enters, sacrifice any number of untapped Forests."
#: (Wood Elemental.) CR 614.1c again: the sacrifice happens *as* the permanent
#: arrives, which is what lets a characteristic-defining P/T read the number
#: back off it before the state-based check ever sees a 0/0.
#:
#: The noun phrase is a capture and is read by the same noun parser every other
#: printed noun phrase in the engine goes through, so "any number of untapped
#: Forests" costs no more code than "any number of creatures you control" would.
SACRIFICE_ANY_NUMBER_ON_ENTER = re.compile(
    r"^as this [a-z]+ enters, sacrifice any number of (?P<phrase>.+)$"
)


def sacrifice_any_number_on_enter(line: str, card_name: str | None = None) -> dict | None:
    """The filter payload naming what may be given up as the permanent enters.

    Read by the entry state that arms the prompt *and* by the support gate, so
    what is offered and what is claimed cannot drift.

    A phrase the noun parser refuses, or one carrying a narrowing the sacrifice
    prompt cannot test, refuses the whole line: the prompt lists one player's
    battlefield with no observer and no source behind it, so a restriction
    outside :data:`subject_filters.OBJECT_ONLY_FILTER_KEYS` would be quietly
    ignored and the player would be offered permanents the card does not name.
    """
    from .grammar.lowering._common import dropped_narrowings
    from .grammar.phrases import parse_subject_filter
    from .subject_filters import object_only_filter

    match = SACRIFICE_ANY_NUMBER_ON_ENTER.match(_self_normalized(line, card_name))
    if match is None:
        return None
    # ``plural=True``: the phrase is *counted* ("any number of") rather than
    # quantified, which is the position parse_subject_filter documents that
    # word for.
    filt = parse_subject_filter(match.group("phrase"), plural=True)
    if filt is None or filt.zone != "battlefield" or filt.is_card:
        return None
    payload = filt.to_payload()
    # A narrowing with no payload form leaves no key behind, so the testable-key
    # check below cannot see it go missing.
    if dropped_narrowings(filt, payload):
        return None
    return object_only_filter(payload)


#: "As this creature enters, pay any amount of life. The amount you pay can't be
#: more than the total number of <objects> your opponents control plus the total
#: number of <cards> in their graveyards." (Nameless Race.)
#:
#: Two printed noun phrases and a cap that adds them. Both are captures read by
#: the same noun parser every other printed phrase in the engine goes through,
#: so what the sentence narrows by costs no code here - and a phrase the parser
#: refuses refuses the whole line, because a cap read wider than printed is a
#: creature its controller may pay more life for than the card allows.
PAY_ANY_LIFE_ON_ENTER = re.compile(
    r"^as this [a-z]+ enters, pay any amount of life\. the amount you pay can't "
    r"be more than the total number of (?P<board_phrase>.+?) your opponents "
    r"control plus the total number of (?P<pile_phrase>.+?) in their graveyards$"
)


def pay_any_life_on_enter(line: str, card_name: str | None = None) -> dict | None:
    """The two count specs the printed cap adds together, or None.

    Read by the entry state that arms the payment *and* by the support gate, so
    what is offered and what is claimed cannot drift - the same pairing every
    other reader in this file is half of.

    The battlefield half is a permanent question and the graveyard half a card
    question, which is why they are two specs rather than one: a card in a zone
    has no computed characteristics at all (CR 613.1).
    """
    from .grammar.lowering._common import dropped_narrowings
    from .grammar.phrases import parse_subject_filter
    from .subject_filters import card_only_filter, object_only_filter

    match = PAY_ANY_LIFE_ON_ENTER.match(_self_normalized(line, card_name))
    if match is None:
        return None
    board = parse_subject_filter(match.group("board_phrase"), plural=True)
    pile = parse_subject_filter(match.group("pile_phrase"), plural=True)
    if board is None or pile is None:
        return None
    if board.zone != "battlefield" or board.is_card:
        return None
    if pile.zone != "battlefield" or not pile.is_card:
        # "white **cards**" prints no zone of its own - "in their graveyards"
        # is the sentence's, and it is what this reader supplies. A phrase that
        # named a zone itself would be one this rule has not read.
        return None
    board_payload = board.to_payload()
    pile_payload = pile.to_payload()
    if dropped_narrowings(board, board_payload) or dropped_narrowings(pile, pile_payload):
        return None
    described_board = object_only_filter(board_payload)
    described_pile = card_only_filter(pile_payload)
    if described_board is None or described_pile is None:
        return None
    return {"battlefield": described_board, "graveyard": described_pile}


#: "As this creature enters, exile X creature cards from your graveyard. If you
#: can't, put this creature into its owner's graveyard instead of onto the
#: battlefield. For each creature card exiled this way, this creature enters
#: with a +2/+0, +1/+1, or +0/+2 counter on it." (Frankenstein's Monster.)
#:
#: Three printed sentences and one CR 614.1c replacement: an entry cost, what
#: happens when it cannot be paid, and the entry state the payment buys. They
#: are one pattern because they are one effect - a claim stopping at the first
#: sentence would admit a card whose "if you can't" nothing performs, which is
#: the rider-claimed-and-not-executed shape ``REPLACEMENT_LINES`` documents.
#:
#: Every parameter is a capture: how many cards, what kind of card, and which
#: counters are offered. The count is ``x`` here and a printed number would read
#: the same way; the noun phrase goes through the same parser every other
#: printed phrase in the engine goes through; and the counters are checked
#: against ``pt.pt_counter_deltas``, so a counter kind the engine cannot place
#: refuses the whole line rather than entering the creature one counter short.
#:
#: Anchored on the whole line, and the back-reference is checked rather than
#: assumed: "for each **creature card** exiled this way" must describe the same
#: cards the first sentence exiles, because a card printing a different noun
#: there is a card this rule has not read.
EXILE_CARDS_ON_ENTER = re.compile(
    r"^as this (?P<self>[a-z]+) enters, exile (?P<count>x|[a-z0-9]+) "
    r"(?P<phrase>.+?) from your graveyard\. if you can't, put this (?P=self) "
    r"into its owner's graveyard instead of onto the battlefield\. for each "
    r"(?P<each>.+?) exiled this way, this (?P=self) enters with "
    r"(?P<counters>.+?) counters? on it$"
)

#: How the counter alternatives are written: "a +2/+0, +1/+1, or +0/+2 counter".
_COUNTER_SPLIT = re.compile(r",\s*or\s+|,\s*|\s+or\s+")


def _counter_options(text: str) -> tuple[str, ...] | None:
    """The P/T counter kinds *text* offers, in printed order, or None if any is
    one the engine cannot place.

    Read through :func:`engine.pt.pt_counter_deltas` rather than a list of the
    kinds the pool happens to print - that function derives what a counter does
    from its *name* (CR 122.1a), so "+2/+0" and "+0/+2" cost nothing here. A
    kind it cannot read refuses the whole line, for the reason every other
    reader in this file refuses: a creature entering with two of the three
    counters its card prints is a strictly smaller card, silently.

    A single kind is a list of one. The sentence reads the same with one
    alternative as with three, so a trivial choice is the caller's business and
    not a second pattern.
    """
    from .pt import pt_counter_deltas

    body = re.sub(r"^an?\s+", "", text.strip())
    options = tuple(part.strip() for part in _COUNTER_SPLIT.split(body) if part.strip())
    if not options:
        return None
    if any(pt_counter_deltas(option) is None for option in options):
        return None
    return options


def exile_cards_on_enter(line: str, card_name: str | None = None) -> dict | None:
    """What the entering permanent must exile, and what each exile buys it.

    ``{"count": "x" | int, "filter": <card filter payload>, "counters":
    (kind, ...)}``, or None when the line is not this template.

    Three readers, one string: the support gate (through
    :func:`enter_effect_line`), the entry state that arms the choice, and the
    CR 614 interceptor in ``engine/replacements.py`` that performs the "if you
    can't" sentence. ``"x"`` is returned as itself rather than resolved here
    because the value is announced on the *spell* (CR 601.2b) and this function
    is handed a line, not a permanent.

    A phrase the noun parser refuses, one carrying a narrowing the card matcher
    cannot test, or a back-reference describing different cards refuses the
    whole line - the picker lists one player's graveyard with no observer and no
    source behind it, so a restriction the matcher cannot answer would be
    quietly ignored and the player offered cards the sentence does not name.
    """
    from .grammar.lowering._common import dropped_narrowings
    from .grammar.phrases import parse_subject_filter
    from .grammar.vocabulary import NUMBER_WORDS
    from .subject_filters import card_only_filter

    match = EXILE_CARDS_ON_ENTER.match(_self_normalized(line, card_name))
    if match is None:
        return None
    printed = match.group("count")
    if printed == "x":
        count: str | int = "x"
    elif printed.isdigit():
        count = int(printed)
    else:
        known = NUMBER_WORDS.get(printed)
        # A number word the table does not know refuses the line rather than
        # defaulting to one, for the reason `enters_with_pt_counters` gives.
        if known is None:
            return None
        count = known
    # ``plural=True`` for both halves: the first phrase is *counted* ("X
    # creature cards") and the second names one of the same pile, which is the
    # position that flag documents.
    described = parse_subject_filter(match.group("phrase"), plural=True)
    each = parse_subject_filter(match.group("each"), plural=True)
    if described is None or each is None:
        return None
    if described.zone != "battlefield" or not described.is_card:
        # "creature **cards**" prints no zone of its own - "from your graveyard"
        # is the sentence's, and it is what this reader supplies. A phrase that
        # named a zone itself would be one this rule has not read.
        return None
    payload = described.to_payload()
    # A narrowing with no payload form leaves no key behind, so the card-only
    # check below cannot see it go missing.
    if dropped_narrowings(described, payload):
        return None
    if each.to_payload() != payload:
        return None
    counters = _counter_options(match.group("counters"))
    if counters is None:
        return None
    described_cards = card_only_filter(payload)
    if described_cards is None:
        return None
    return {"count": count, "filter": described_cards, "counters": counters}


def entry_exile_requirement(card, x_value: int | None = None) -> dict | None:
    """The entry exile *card*'s own lines demand, with the announced X folded in.

    ``{"count": int, "filter": ..., "counters": ...}``, or None for a card that
    prints no such line.

    Two readers need the same answer about the same permanent - the CR 614
    interceptor in ``engine/replacements.py`` that performs "if you can't", and
    the entry state that performs the exile - and the count is the one part of
    the answer that is not on the printed line: ``X`` is the value announced
    when the spell was cast (CR 601.2b), read off the permanent. One function so
    the two cannot disagree about how many cards are owed, which would be a
    creature that entered when the card says it could not.

    Through :func:`engine.oracle.expand_card_lines` rather than a split of
    ``oracle_text``, for the reason that function documents: a reader that
    splits the raw text is reading a different card from the gate above it.
    """
    from .oracle import expand_card_lines

    for line in expand_card_lines(card):
        spec = exile_cards_on_enter(line, card.name)
        if spec is None:
            continue
        count = spec["count"]
        if count == "x":
            count = int(x_value or 0)
        return {**spec, "count": max(0, int(count))}
    return None


#: "As this creature enters, choose a number between 0 and 7." (Shapeshifter.)
#: The bounds are data, like every other parameter in this file: a card printed
#: "between 1 and 5" is the same choice. Matched by shape rather than listed as
#: a phrase for that reason, and anchored so a sentence continuing past the
#: range is not claimed by a rule that stops reading at the number.
CHOOSE_NUMBER_ON_ENTER = re.compile(
    r"^as this [a-z]+ enters, choose a number between (?P<low>\d+) and (?P<high>\d+)$"
)


def choose_number_on_enter(line: str) -> tuple[int, int] | None:
    """``(low, high)`` the entry choice is bounded by, or None.

    Read by the entry state that arms the choice *and* by the support gate, so
    what is asked and what is claimed cannot drift. Reversed bounds refuse
    rather than being sorted: a range nobody prints is a line this does not
    understand, and quietly repairing it would admit the card on a guess.
    """
    match = CHOOSE_NUMBER_ON_ENTER.match((line or "").strip().lower().rstrip("."))
    if match is None:
        return None
    low, high = int(match.group("low")), int(match.group("high"))
    return (low, high) if low <= high else None


# Copy-on-enter (CR 707.2). Clone's line is exactly the creature phrase; Copy
# Artifact adds a tail the mixin also performs (it appends "Enchantment" to the
# copied type line), which is why the tail is spelled out below rather than
# being an open-ended "and whatever follows".
COPY_CREATURE_ON_ENTER = (
    "you may have this creature enter as a copy of any creature on the battlefield"
)
COPY_ARTIFACT_ON_ENTER = (
    "you may have this enchantment enter as a copy of any artifact on the battlefield"
)

# Standing permissions stamped on the controller as the permanent enters.
NO_MAXIMUM_HAND_SIZE = "you have no maximum hand size"
SPEND_WHITE_AS_RED = "you may spend white mana as though it were red mana"
#: "You may spend mana as though it were mana of any color." (Chromatic Orrery.)
#: The general form of the line above, and separate from it rather than a
#: parameter of it: the narrow one substitutes *one* colour for one other, this
#: one makes every unit in the pool fungible for a coloured pip. Colourless is
#: included as a *source* — the Orrery's own five {C} are the point of the card
#: — but a {C} in a cost still wants colourless, because colourless is not a
#: colour (CR 105.1) and this line says "as though it were mana of any color".
SPEND_ANY_COLOR = "you may spend mana as though it were mana of any color"

# "As this enchantment enters, you lose life equal to your life total." (Lich.)
LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER = (
    "as this enchantment enters, you lose life equal to your life total"
)


# A line may name the permanent it is printed on before the phrase the mixin
# probes for ("**This artifact** enters tapped"). The empty string is included
# so a phrase that already starts at the beginning of the line still matches.
_SELF_SUBJECTS: tuple[str, ...] = (
    "",
    "this artifact ",
    "this creature ",
    "this enchantment ",
    "this land ",
    "this permanent ",
)

# (phrase the mixin probes for, trailing clause the mixin also implements).
# A tail is written out in full: it is the one place a claim here could
# otherwise swallow text nothing performs.
_ENTRY_LINES: tuple[tuple[str, str], ...] = (
    (ENTERS_TAPPED, ""),
    (CHOOSE_OPPONENT_ON_ENTER, ""),
    (CHOOSE_COLOR_AND_OPPONENT_ON_ENTER, ""),
    (CHOOSE_CARD_NAME_ON_ENTER, ""),
    (COPY_CREATURE_ON_ENTER, ""),
    # CR 707.9b — the mixin builds the copied type line with "Enchantment"
    # added when the copied artifact is not already one, which is exactly what
    # this tail asks for.
    (COPY_ARTIFACT_ON_ENTER, ", except it's an enchantment in addition to its other types"),
    (NO_MAXIMUM_HAND_SIZE, ""),
    (SPEND_WHITE_AS_RED, ""),
    (SPEND_ANY_COLOR, ""),
    (LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER, ""),
)


def _self_normalized(line: str, card_name: str | None = None) -> str:
    """:func:`_normalized`, with a card that names itself collapsed first.

    Pre-modern and legendary templating writes the subject as the card's name
    ("**Rasputin** enters with seven dream counters on it") where the patterns
    here are anchored on "this <noun>". Through ``oracle._restriction_line``
    rather than a collapser of its own, for the reason ``target_immunity``
    gives at the same seam: the *gate* already reads a line that way, and a
    runtime reader normalizing differently is exactly how a card compiles
    supported and then does nothing.
    """
    if not card_name:
        return _normalized(line)
    from .oracle import _restriction_line

    return _normalized(_restriction_line(line, card_name))


def _normalized(line: str) -> str:
    """The line as ``_initialize_permanent_state`` sees it.

    ``OracleProgram.normalized_text`` is the card's text lowercased with runs of
    whitespace collapsed, so comparing against that reduction is comparing
    against what the mixin really probes. The trailing full stop is dropped
    because the mixin's probes are substrings that never include it.
    """
    return " ".join(line.strip().lower().split()).rstrip(".")


def copy_on_enter_type(normalized_text: str) -> str | None:
    """``"creature"`` / ``"artifact"`` if *normalized_text* offers a copy choice
    as the permanent enters (CR 707.9a), else ``None``.

    The substring probe :meth:`_initialize_permanent_state` runs, asked as a
    question instead of repeated as a literal. Two callers need the answer for
    different reasons — the mixin to *perform* the copy, and
    ``engine/targeting.py`` to raise the picker that chooses what to copy — and
    the pair must never disagree about which cards offer one.

    Deliberately a substring probe rather than :func:`enter_effect_line`, which
    is whole-line and therefore declines Vesuvan Doppelganger (its copy line
    carries a granted upkeep ability the mixin does not perform). The card still
    copies as it enters, so it still needs the picker; asking the narrower
    question here would silently drop its prompt.
    """
    if COPY_CREATURE_ON_ENTER in normalized_text:
        return "creature"
    if COPY_ARTIFACT_ON_ENTER in normalized_text:
        return "artifact"
    return None


def enter_effect_line(line: str, card_name: str | None = None) -> str | None:
    """The entry-state phrase *line* consists of in full, or ``None``.

    The return value is the phrase itself, used only to label the AST node —
    nothing dispatches on it, because there is nothing to dispatch: the mixin
    has already applied the effect from the permanent's own text.
    """
    normalized = _self_normalized(line, card_name)
    for phrase, tail in _ENTRY_LINES:
        for subject in _SELF_SUBJECTS:
            if normalized == subject + phrase + tail:
                return phrase
    # "This Equipment enters with a soul counter on it." (Malefic Scythe.) The
    # one entry line matched by shape rather than by a fixed phrase, asked of
    # the same reader the mixin places the counter with — so the claim and the
    # placement cannot drift. It was placed and *not* claimed: nothing gated an
    # Equipment's effect lines, so the omission cost nothing until the
    # Equipment gate (engine/oracle.py) started asking.
    if enters_with_named_counter(normalized) is not None:
        return "enters with named counters"
    if enters_with_pt_counters(normalized) is not None:
        return "enters with P/T counters"
    if enters_with_x_pt_counters(normalized) is not None:
        return "enters with X P/T counters"
    if chooses_color_on_enter(normalized):
        return "chooses a color as it enters"
    if choose_number_on_enter(normalized) is not None:
        return "chooses a number as it enters"
    if sacrifice_any_number_on_enter(normalized) is not None:
        return "sacrifices any number as it enters"
    if pay_any_life_on_enter(normalized) is not None:
        return "pays any amount of life as it enters"
    # The three-sentence entry cost (Frankenstein's Monster). Claimed here
    # because all three sentences are one CR 614.1c replacement: the exile and
    # the counters are performed by the entry state, and the "if you can't"
    # half by the interceptor in engine/replacements.py, which self-selects off
    # this same reader. One string, three readers, so what is claimed and what
    # is carried out cannot describe different cards.
    if exile_cards_on_enter(normalized) is not None:
        return "exiles cards from your graveyard as it enters"
    return None


__all__ = [
    "CHOOSE_CARD_NAME_ON_ENTER",
    "CHOOSE_COLOR_AND_OPPONENT_ON_ENTER",
    "CHOOSE_OPPONENT_ON_ENTER",
    "chooses_color_on_enter",
    "COPY_ARTIFACT_ON_ENTER",
    "COPY_CREATURE_ON_ENTER",
    "ENTERS_TAPPED",
    "ENTERS_WITH_NAMED_COUNTER",
    "ENTERS_WITH_PT_COUNTERS",
    "ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS",
    "enters_with_pt_counters",
    "enters_with_named_counter",
    "ENTERS_WITH_X_PT_COUNTERS",
    "enters_with_x_pt_counters",
    "EXILE_CARDS_ON_ENTER",
    "exile_cards_on_enter",
    "entry_exile_requirement",
    "LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER",
    "NO_MAXIMUM_HAND_SIZE",
    "PAY_ANY_LIFE_ON_ENTER",
    "pay_any_life_on_enter",
    "SACRIFICE_ANY_NUMBER_ON_ENTER",
    "sacrifice_any_number_on_enter",
    "SPEND_ANY_COLOR",
    "SPEND_WHITE_AS_RED",
    "copy_on_enter_type",
    "enter_effect_line",
]


# "As this creature enters, it becomes your choice of a 3/3 artifact creature,
# a 2/2 artifact creature with flying, or a 1/6 Wall artifact creature with
# defender in addition to its other types." (Primal Clay.)
#
# The bodies are parsed from the text rather than listed, so this is the
# template and not the card: any "your choice of <body>, <body>, or <body>"
# creature reads the same way.
CHOOSE_BODY_ON_ENTER = "it becomes your choice of"

_BODY_RE = re.compile(
    r"a (?P<power>\d+)/(?P<toughness>\d+)(?P<rest>[^,]*?)(?=,|$| or )"
)


def choosable_bodies(oracle_text: str) -> tuple[dict, ...]:
    """The bodies a "your choice of" creature may enter as.

    Each is ``{"power", "toughness", "keyword", "subtypes"}``. The keyword is
    whatever the body grants ("with flying", "with defender"); a body granting
    none has an empty string, which is a body, not a missing one.

    ``subtypes`` is every creature type the body names — "a 1/6 **Wall**
    artifact creature with defender". It was missing, and the omission is not
    cosmetic: twelve shipped cards ask whether a creature is a Wall (Juggernaut
    can't be blocked by one, Tunnel destroys one, Animate Wall enchants one,
    Keldon Warlord counts the ones that aren't), and a Primal Clay that chose
    that body answered "no" to all of them while sitting there as a 1/6 with
    defender. Read against ``CREATURE_TYPES`` rather than a literal, so the
    template covers any body naming any tribe.
    """
    from .grammar.vocabulary import CREATURE_TYPES

    lowered = " ".join(oracle_text.lower().split())
    if CHOOSE_BODY_ON_ENTER not in lowered:
        return ()
    clause = lowered.split(CHOOSE_BODY_ON_ENTER, 1)[1]
    bodies: list[dict] = []
    for match in _BODY_RE.finditer(clause):
        rest = match.group("rest")
        keyword = ""
        with_match = re.search(r"with (\w+)", rest)
        if with_match:
            keyword = with_match.group(1)
        bodies.append({
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
            "keyword": keyword,
            "subtypes": tuple(
                word for word in re.findall(r"[a-z']+", rest) if word in CREATURE_TYPES
            ),
        })
    return tuple(bodies)
