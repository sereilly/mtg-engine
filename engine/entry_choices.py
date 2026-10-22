"""What a permanent chooses as it enters, and the table that records it.

"As this enters, choose an opponent", "… a color", "… a creature type", "… a
basic land type", "… a card name", "… a number", "pay any amount of life",
"it becomes your choice of …": a replacement effect's choice, made before the
permanent enters (CR 614.1c, 614.12a). The readers here are the ones
``_initialize_permanent_state`` asks, and ``ENTRY_CHOICES`` is the table of
what each choice records on the permanent and how the client shows it
(``chosen_as_entered``, read by ``web/serialization``).

The two normalizers every entry reader reads a line through (``_normalized``,
``_self_normalized``) are here too, beneath ``engine/enter_effects.py``, which
imports them.

Split out of ``engine/enter_effects.py`` at the 2,000-line cap. Its
``enter_effect_line`` claims each choice line through the reader here, and it
still exports every name in its ``__all__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Callable


# "As this artifact enters, choose an opponent." (Black Vise) / "As this
# **creature** enters, choose an opponent." (Lost Order of Jarkeld.) The printed
# noun is *data*, for the reason the colour-only sibling below states in full:
# the literal read "artifact" and nothing else, so a creature printing the same
# sentence about itself reached nothing at all. That is the same bug the colour
# reader was converted for, one card later.
#
# The negative lookahead is that reader's, for the same reason: Jihad's line
# starts with these words and continues "and a color", and without it the
# two-choice sentence would be claimed here with its colour dropped.
_CHOOSE_OPPONENT_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose an opponent(?! and)"
)


def chooses_opponent_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for an opponent as the permanent
    enters.

    A substring probe like the mixin's own, because the mixin asks it of the
    card's whole normalized text; :func:`enter_effect_line` asks the whole-line
    question through this same matcher, so what is performed and what is
    claimed cannot drift.
    """
    return bool(_CHOOSE_OPPONENT_ON_ENTER_RE.search(text or ""))


# Its two-choice sibling (Jihad, Call to Arms). A separate reader because the
# mixin branches on them: the colour half is what decides whether an interactive
# caster is prompted.
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


#: "As this artifact enters, choose an opponent **and a card name other than a
#: basic land card name**." (Booby Trap.) The opponent-and-colour pair's sibling
#: one characteristic over, and a separate reader for that pair's reason: the
#: mixin branches on *which* second value is asked for, because the prompt it
#: arms offers a different thing.
#:
#: The exclusion is part of the phrase and not a tail this drops. It is the one
#: restriction CR 201.2 leaves on naming a card, and the resolver enforces it —
#: a reader that matched without it would claim a line whose restriction nothing
#: then applied.
#:
#: The noun is data (``[a-z]+``) for ``_CHOOSE_OPPONENT_ON_ENTER_RE``'s stated
#: reason: a creature or an enchantment printing this sentence about itself is
#: printing the same sentence.
_CHOOSE_OPPONENT_AND_CARD_NAME_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose an opponent and a card name other than a "
    r"basic land card name"
)


def chooses_opponent_and_card_name_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for an opponent **and** a card name as
    the permanent enters.

    A substring probe like the mixin's own, for the reason its two siblings
    above give: the mixin asks it of the card's whole normalized text, and
    asking the whole-line question through the same matcher is what keeps what
    is performed and what is claimed from drifting.
    """
    return bool(_CHOOSE_OPPONENT_AND_CARD_NAME_ON_ENTER_RE.search(text or ""))


def chooses_color_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for a colour as the permanent enters.

    A substring probe like the mixin's own, because the mixin asks it of the
    card's whole normalized text; :func:`enter_effect_line` asks the whole-line
    question through this same matcher, so what is performed and what is
    claimed cannot drift.
    """
    return bool(_CHOOSE_COLOR_ON_ENTER_RE.search(text or ""))

#: "This creature is the chosen color. (It's still an artifact.)" (Alloy Golem.)
#: The sentence that *spends* the entry choice above on the permanent itself: a
#: static ability setting its own colour (CR 613 layer 5) to whatever was
#: recorded as it entered (CR 614.1c). Here beside the choice rather than in a
#: module of its own, because the pair is one printed idea and this is the file
#: that owns the record's key — and whole-line, reminder text included or not,
#: so a sentence saying anything more is not claimed.
#:
#: The noun is data, for ``_CHOOSE_COLOR_ON_ENTER_RE``'s reason.
_IS_THE_CHOSEN_COLOR_RE = re.compile(
    r"^this [a-z]+ is the chosen color\.?(?: \(it's still an? [a-z]+\.?\))?$"
)


def is_the_chosen_color_line(text: str) -> bool:
    """Whether *text* is, in full, "This <permanent> is the chosen color."

    Asked by :func:`enter_effect_line` (the claim) and by
    :func:`own_chosen_color` (the effect), so what is claimed and what layer 5
    is handed cannot describe different cards.
    """
    return bool(_IS_THE_CHOSEN_COLOR_RE.match(_normalized(text or "")))


@lru_cache(maxsize=None)
def _says_it_is_the_chosen_color(oracle_text: str) -> bool:
    return any(is_the_chosen_color_line(line) for line in oracle_text.splitlines())


def own_chosen_color(permanent, card=None) -> str | None:
    """The colour *permanent*'s own "is the chosen color" static gives it, or
    ``None`` when it prints no such line or has not chosen yet.

    Read off the card layers 1 and 3 leave — the copy and the text change are
    both below layer 5 (CR 613.1), so a Clone of an Alloy Golem is the colour
    the *Clone* chose as it entered — and off the record the entry choice
    wrote. Derived on every recompute rather than stamped onto the colour
    override when the choice is answered: a late answer to the entry prompt
    would have nothing to re-read.

    *card* is that card, when the caller holds the one layer 5 should read:
    ``Permanent.card_before_layer_6``, the text **before** layer 6 takes
    abilities away. An Alloy Golem under Humility is still the colour it
    chose — the ability is removed a layer after its colour is decided
    (CR 613.1e, 613.1f) — and the default here, ``effective_card``, has
    already struck it out.
    """
    chosen = permanent.metadata.get(CHOSEN_COLOR_KEY)
    if not chosen:
        return None
    text = (card if card is not None else permanent.effective_card).oracle_text
    if not _says_it_is_the_chosen_color(text or ""):
        return None
    return str(chosen)


#: "This creature has protection from the chosen color." (Voice of All.) The
#: second sentence that spends the entry choice on the permanent itself, one
#: layer up from :data:`_IS_THE_CHOSEN_COLOR_RE`: CR 613 layer 6 rather than
#: layer 5, and CR 702.16 rather than CR 105. The Wards say it of the creature
#: they enchant ("Enchanted creature has protection from the chosen color",
#: ``aura_grants.CHOSEN_PROTECTION_COLOR``); this is the same grant with the
#: permanent that chose as the permanent that has it.
#:
#: Whole-line, and the noun is data, for the reasons its neighbour gives.
_HAS_PROTECTION_FROM_THE_CHOSEN_COLOR_RE = re.compile(
    r"^this [a-z]+ has protection from the chosen color\.?$"
)


def has_protection_from_the_chosen_color_line(text: str) -> bool:
    """Whether *text* is, in full, "This <permanent> has protection from the
    chosen color."

    Asked by :func:`enter_effect_line` (the claim) and by
    :func:`own_chosen_protection_color` (the effect), so what is claimed and
    what the protection reader is handed cannot describe different cards.
    """
    return bool(
        _HAS_PROTECTION_FROM_THE_CHOSEN_COLOR_RE.match(_normalized(text or ""))
    )


@lru_cache(maxsize=None)
def _says_it_has_protection_from_the_chosen_color(oracle_text: str) -> bool:
    return any(
        has_protection_from_the_chosen_color_line(line)
        for line in oracle_text.splitlines()
    )


def own_chosen_protection_color(permanent) -> str | None:
    """The colour *permanent*'s own "has protection from the chosen color"
    static protects it from, or ``None`` when it prints no such line or has not
    chosen yet.

    :func:`own_chosen_color`'s contract exactly, and for its reasons: read off
    ``effective_card`` — so a Clone of a Voice of All has protection from the
    colour the *Clone* chose, and a Voice that has lost its abilities
    (CR 613.1f) has none — and off the record the entry choice wrote, on every
    ask rather than stamped into the turn-long ``protection_from_<colour>``
    channel when the choice is answered. A stamp would outlive the ability and
    a late answer to the entry prompt would have nothing to re-read.

    No record means no protection rather than a guessed colour: a shield from
    a colour nobody named is one the card never gave.
    """
    chosen = permanent.metadata.get(CHOSEN_COLOR_KEY)
    if not chosen:
        return None
    if not _says_it_has_protection_from_the_chosen_color(
        permanent.effective_card.oracle_text or ""
    ):
        return None
    return str(chosen)


#: "As this artifact enters, choose **a color and a creature type**."
#: (Volrath's Laboratory.) Two of the qualities this one sentence can name, on
#: one line — the pair shape ``CHOOSE_COLOR_AND_OPPONENT_ON_ENTER`` and Booby
#: Trap's opponent-and-card-name already have, with both halves being *catalog*
#: choices rather than one of them being a seat.
#:
#: Its own reader rather than letting the two singular probes both match,
#: because ``_CHOOSE_COLOR_ON_ENTER_RE`` declines "choose a color and …" by
#: design: that lookahead is what keeps Jihad's opponent from being dropped,
#: and widening it would drop this card's creature type the same way. So the
#: pair is read once, here, and armed as one prompt with two answers.
_CHOOSE_COLOR_AND_CREATURE_TYPE_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose a color and a creature type"
)


def chooses_color_and_creature_type_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for a colour **and** a creature type
    as the permanent enters.

    A substring probe like its two singular siblings above, because the mixin
    asks it of the card's whole normalized text; :func:`enter_effect_line` asks
    the whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    return bool(_CHOOSE_COLOR_AND_CREATURE_TYPE_ON_ENTER_RE.search(text or ""))


#: "As this enchantment enters, choose **black or red**." (Mangara's Equity) /
#: "As this enchantment enters, choose **Island or Swamp**." (Roots of Life.)
#: The same CR 614.1c choice as the colour and land-type readers around it, with
#: the card printing the **options** instead of naming a catalog: the choice is
#: still one word, still recorded under the same key, and still read back by "of
#: the chosen color" / "of the chosen type" — what differs is that the sentence
#: has already narrowed what may be chosen.
#:
#: One reader for both, and the catalog the two printed words come from is what
#: says which record they write. Two readers would be one idea spelled twice
#: with a metadata key changed — the argument ``_CHOSEN_SUBTYPE_KEYS`` makes one
#: module over — and a card printing "choose Forest or Plains" or "choose white
#: or green" then needs no code at all.
#:
#: Both words must come from the **same** catalog. A mixed pair ("choose black
#: or Swamp") is a sentence nobody prints, and admitting it would have to guess
#: which record the answer lands in.
_CHOOSE_ONE_OF_TWO_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose (?P<first>[a-z']+) or (?P<second>[a-z']+)$"
)

#: What the pair of printed words can name, mapped to the metadata key the
#: choice is recorded under — the same two keys ``chooses_color_on_enter`` and
#: ``chooses_land_type_on_enter`` above write, because this is those choices
#: with the offer narrowed rather than a third kind of record.
#
#: Deliberately out of ``enter_effects.__all__``, beside
#: ``enter_effects.ENTERED_BATTLEFIELD_TURN`` and ``CAST_THIS_TURN_STAMP`` and
#: for their reason: what that list exports is a *phrase*, one string per
#: behaviour, and
#: ``test_the_entry_phrases_have_exactly_one_spelling`` holds the mixin to not
#: re-spelling one. A metadata key is the other kind of shared string — a
#: channel the mixin writes and a matcher reads — and the mixin has spelled
#: both of these since the catalog-named choices were built.
CHOSEN_COLOR_KEY = "chosen_color"
CHOSEN_LAND_TYPE_KEY = "chosen_land_type"


@lru_cache(maxsize=None)
def _entry_choice_catalogs() -> "tuple[tuple[str, dict[str, str]], ...]":
    """``(metadata key, printed word -> recorded value)`` for each catalog a
    two-option entry choice may draw from.

    Built from ``data/vocabulary`` and the shared colour table rather than
    listed here, so a land type the pool gains is offerable without an edit.
    Imported lazily for :func:`_land_types`' reason one module over: the grammar
    package imports engine-level derivation modules, so a module-level import
    would close a cycle.
    """
    from .grammar.vocabulary import COLOR_WORDS, LAND_TYPES

    return (
        (CHOSEN_COLOR_KEY, dict(COLOR_WORDS)),
        (CHOSEN_LAND_TYPE_KEY, {word: word for word in LAND_TYPES}),
    )


def choose_one_of_two_on_enter(
    line: str, card_name: str | None = None
) -> "tuple[str, tuple[str, str]] | None":
    """``(metadata key, the two recorded options)``, or None.

    Read by the entry state that arms the prompt *and* by the support gate
    (through :func:`enter_effects.enter_effect_line`), like every other reader
    in this file, so what is offered and what is claimed cannot drift. The
    options travel with the key because the prompt has to offer exactly them
    and the resolver has to refuse everything else — a picker offering the
    whole catalog where the card prints two words is a strictly better card,
    silently.

    Two identical words refuse: "choose black or black" is not a choice, and a
    sentence nobody prints is one this rule has not read.
    """
    match = _CHOOSE_ONE_OF_TWO_ON_ENTER_RE.match(_self_normalized(line, card_name))
    if match is None:
        return None
    first, second = match.group("first"), match.group("second")
    if first == second:
        return None
    for key, catalog in _entry_choice_catalogs():
        if first in catalog and second in catalog:
            return key, (catalog[first], catalog[second])
    return None


#: "As this enchantment enters, choose **two basic land types**." (Illusionary
#: Terrain.) An *ordered pair* — the static line beside it names "the first
#: chosen type" and "the second chosen type" — which is what separates it from
#: the colour choice above and why the record it stamps is a tuple rather than
#: a word.
#:
#: Matched by shape rather than listed as a phrase, so the printed noun is data
#: the way it is for the colour: an artifact or a creature printing the same
#: sentence is the same choice.
_CHOOSE_TWO_LAND_TYPES_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose two basic land types"
)


def chooses_two_land_types_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for two basic land types as the
    permanent enters.

    A substring probe like the colour one above, because the mixin asks it of
    the card's whole normalized text; :func:`enter_effect_line` asks the
    whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    return bool(_CHOOSE_TWO_LAND_TYPES_ON_ENTER_RE.search(text or ""))


#: "As this enchantment enters, choose **a land type**." (Shimmer.) The
#: *fourth* quality this one sentence can name, beside a colour, a creature
#: type and the ordered pair of basic land types above — and a different
#: catalog from that pair, not a singular of it: CR 205.3i's land types
#: include Desert and Urza's, which no "basic land type" clause may name.
#:
#: Matched by shape like the three above, so the printed noun is data.
#:
#: Read **before** the two-basic-land-types probe would matter and after it in
#: :func:`enter_effect_line`, because neither phrase is a prefix of the other:
#: "choose two basic land types" and "choose a land type" share no cursor.
_CHOOSE_LAND_TYPE_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose a land type"
)


def chooses_land_type_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for a land type as the permanent
    enters.

    A substring probe like the colour one above, because the mixin asks it of
    the card's whole normalized text; :func:`enter_effect_line` asks the
    whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    return bool(_CHOOSE_LAND_TYPE_ON_ENTER_RE.search(text or ""))


#: "As this enchantment enters, choose **a creature type**." (An-Zerrin Ruins.)
#: The third quality this sentence can name, beside a colour and a pair of basic
#: land types — and matched by shape for their reason, so the printed noun is
#: data: a creature or an artifact printing the same sentence is the same
#: choice.
#:
#: CR 205.3m: the choice is any creature type, not one on a board — which is
#: what the resolver checks the answer against, and why the picker offers the
#: whole catalog rather than what happens to be in play.
_CHOOSE_CREATURE_TYPE_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose a creature type"
)


def chooses_creature_type_on_enter(text: str) -> bool:
    """Whether *text* asks its controller for a creature type as the permanent
    enters.

    A substring probe like the colour one above, because the mixin asks it of
    the card's whole normalized text; :func:`enter_effect_line` asks the
    whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    return bool(_CHOOSE_CREATURE_TYPE_ON_ENTER_RE.search(text or ""))


#: "As this enchantment enters, **you and an opponent each** choose a card name
#: other than a basic land card name." (Null Chamber.) Two names, chosen by two
#: *different seats* — which is what separates it from Runed Halo's single
#: choice below and from Illusionary Terrain's ordered pair: those are one
#: player answering once, and this is two players answering once each.
#:
#: A pattern rather than a literal, for the reason every other row here is one:
#: the printed noun is data, and so is the exclusion. The exclusion is
#: *required* rather than optional — CR 201.2 lets a player name any card, and
#: this card's whole cost is that it may not name a Forest, so a wording without
#: it is a strictly better card and refuses here.
_CHOOSE_TWO_CARD_NAMES_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, you and an opponent each choose a card name "
    r"other than a basic land card name"
)


def chooses_two_card_names_on_enter(text: str) -> bool:
    """Whether *text* asks two seats for a card name each as it enters.

    A substring probe like the colour one above, because the mixin asks it of
    the card's whole normalized text; :func:`enter_effect_line` asks the
    whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    return bool(_CHOOSE_TWO_CARD_NAMES_ON_ENTER_RE.search(text or ""))


# "As this enchantment enters, choose a card name." (Runed Halo.) A *name*
# rather than a quality: nothing on any board constrains it, and the choice is
# made from the whole card pool — which is why the default below is a name the
# chooser can see rather than one derived from the battlefield.
CHOOSE_CARD_NAME_ON_ENTER = "as this enchantment enters, choose a card name"

#: "As this **creature** enters, choose a **nonland** card name." (Meddling
#: Mage.) Runed Halo's choice with the two words that card happens not to vary
#: read as data: which noun the permanent names itself by, and CR 201.4a's bound
#: on the choice ("a card name with certain characteristics"). One chooser and
#: one name, which is what separates it from Null Chamber's pair above and from
#: Booby Trap's seat-and-name.
#:
#: **Anchored on the end of the sentence**, and that is the load-bearing half:
#: "choose a card name **other than a basic land card name**" is a different
#: bound, and a pattern that stopped at "card name" would admit it with the
#: exclusion dropped — a strictly better card than the one printed.
#:
#: Only the *excluded* type is read. "Choose a creature card name" is a real
#: sentence (CR 201.4a's own example prints one) and no card in this pool
#: prints it as it enters, so it refuses here rather than being admitted on a
#: bound no test has ever seen enforced at this prompt.
_CHOOSE_CARD_NAME_ON_ENTER_RE = re.compile(
    r"as this [a-z]+ enters, choose a "
    r"(?:non(?P<excluded>artifact|creature|enchantment|instant|land"
    r"|planeswalker|sorcery) )?card name(?=\.|$)"
)


def chooses_card_name_on_enter(text: str) -> dict | None:
    """What *text* bounds its one chosen card name by, or None when it asks
    for none.

    ``{}`` is the unbounded choice (Runed Halo) and ``{"excluded_card_type":
    "land"}`` is "a **nonland** card name" (Meddling Mage) — the key
    ``mixins/stack/choices/card_names._named_card_breaks_printed_bound`` enforces and the
    default obeys, so the prompt, the headless seat and the answer path read
    one bound.

    A substring probe like the colour one above, because the mixin asks it of
    the card's whole normalized text; :func:`enter_effect_line` asks the
    whole-line question through this same matcher, so what is performed and
    what is claimed cannot drift.
    """
    match = _CHOOSE_CARD_NAME_ON_ENTER_RE.search(text or "")
    if match is None:
        return None
    excluded = match.group("excluded")
    return {"excluded_card_type": excluded} if excluded else {}


#: "As this creature enters, pay any amount of life. The amount you pay can't be
#: more than the total number of <objects> your opponents control plus the total
#: number of <cards> in their graveyards." (Nameless Race.)
#:
#: Two printed noun phrases and a cap that adds them. Both are captures read by
#: the same noun parser every other printed phrase in the engine goes through,
#: so what the sentence narrows by costs no code here - and a phrase the parser
#: refuses refuses the whole line, because a cap read wider than printed is a
#: creature its controller may pay more life for than the card allows.
#: The cap sentence is **optional**, and the card without it is Minion of the
#: Wastes: "As this creature enters, pay any amount of life." Uncapped, the
#: ceiling is the one CR 119.4 already imposes — a player may pay an amount of
#: life greater than 0 only up to their life total — so there is nothing for the
#: card to say and nothing here to read. One pattern rather than two, because
#: the printed sentence the two cards share is the whole entry cost and the cap
#: is a rider on it: two rows would be two claims on one sentence, and the
#: reader that dropped the rider would let Nameless Race's controller pay more
#: life than the card allows.
#: Where the amount paid by the entry replacement below is recorded, on the
#: permanent that paid it.
#:
#: A named constant because four readers now spell it: the choice that records
#: it (``mixins/stack/choices/``), the CR 604.3 recompute that reads it back
#: (Nameless Race, ``characteristic_defining.py`` → ``permanent_state.py``), the
#: reset that clears it, and the where-clause that sizes a token from it
#: (Phyrexian Processor). One key has one name, exactly as
#: ``lowering/_deaths.py`` argues for the death records — a second spelling is
#: a record written in one place and read from another.
LIFE_PAID_AS_ENTERED = "life_paid_as_entered"

PAY_ANY_LIFE_ON_ENTER = re.compile(
    r"^as this [a-z]+ enters, pay any amount of life"
    r"(?:\. the amount you pay can't "
    r"be more than the total number of (?P<board_phrase>.+?) your opponents "
    r"control plus the total number of (?P<pile_phrase>.+?) in their graveyards)?$"
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
    if match.group("board_phrase") is None:
        # Uncapped (Minion of the Wastes): an empty spec, which is not None —
        # the sentence *is* claimed and the entry state does arm the payment.
        # The ceiling is CR 119.4's, read off the payer's life total by the
        # caller rather than off two noun phrases the card never printed.
        return {}
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


def _self_normalized(line: str, card_name: str | None = None) -> str:
    """:func:`_normalized`, with a card that names itself collapsed first.

    Pre-modern and legendary templating writes the subject as the card's name
    ("**Rasputin** enters with seven dream counters on it") where the patterns
    here are anchored on "this <noun>". Through ``self_reference._restriction_line``
    rather than a collapser of its own, for the reason ``target_immunity``
    gives at the same seam: the *gate* already reads a line that way, and a
    runtime reader normalizing differently is exactly how a card compiles
    supported and then does nothing.
    """
    if not card_name:
        return _normalized(line)
    from .self_reference import _restriction_line

    return _normalized(_restriction_line(line, card_name))


def _normalized(line: str) -> str:
    """The line as ``_initialize_permanent_state`` sees it.

    ``OracleProgram.normalized_text`` is the card's text lowercased with runs of
    whitespace collapsed, so comparing against that reduction is comparing
    against what the mixin really probes. The trailing full stop is dropped
    because the mixin's probes are substrings that never include it.
    """
    return " ".join(line.strip().lower().split()).rstrip(".")


# --- what was chosen, as a thing a table can be told -------------------------

#: The metadata keys the entry state records its other choices under. Spelled by
#: the mixin that writes them and named here for the one reader below — and kept
#: out of ``__all__`` for :data:`CHOSEN_COLOR_KEY`'s reason: they are channels,
#: not phrases, and ``test_the_entry_phrases_have_exactly_one_spelling`` holds
#: the mixin to not re-spelling a *phrase*.
CHOSEN_PLAYER_KEY = "chosen_player_index"
CHOSEN_CARD_NAME_KEY = "chosen_card_name"
CHOSEN_CARD_NAMES_KEY = "chosen_card_names"
CHOSEN_LAND_TYPES_KEY = "chosen_land_types"
CHOSEN_CREATURE_TYPE_KEY = "chosen_creature_type"
CHOSEN_NUMBER_KEY = "chosen_number"

_COLOR_SYMBOL_WORDS = {
    "W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
}


def _shown_word(game, value) -> str:
    return str(value)


def _shown_color(game, value) -> str:
    return _COLOR_SYMBOL_WORDS.get(str(value).upper(), str(value))


def _shown_player(game, value) -> str:
    try:
        return game.players[int(value)].name
    except (IndexError, TypeError, ValueError):
        return ""


def _shown_card_name(game, value) -> str:
    # Naming nothing is a legal answer (CR 201.4 bounds the choice, it does not
    # require a useful one) and it is said rather than left blank: an empty
    # value would read as "no choice was made".
    return str(value) if value else "nothing"


def _shown_each(game, value) -> str:
    return ", ".join(str(part) if part else "nothing" for part in (value or ()))


@dataclass(frozen=True)
class EntryChoice:
    """One thing a permanent records as it enters, as a player would say it.

    ``key`` is the metadata record the entry state writes, ``label`` what the
    table calls it, ``asked`` whether a card's text makes that choice as it
    enters — built from the same readers ``_perform_entry_state`` branches on,
    so the two cannot name different sentences — and ``shown`` turns the
    recorded value into words (a seat into its player's name, a colour symbol
    into the colour).
    """

    key: str
    label: str
    asked: "Callable[[str, tuple[str, ...], str], bool]"
    shown: "Callable[[object, object], str]"


def _two_options_record(lines: "tuple[str, ...]", card_name: str) -> "str | None":
    for line in lines:
        found = choose_one_of_two_on_enter(line, card_name)
        if found is not None:
            return found[0]
    return None


#: Every choice a permanent makes **as it enters** (CR 614.1c) that it then
#: goes on reading: the opponent a Black Vise watches, the colour a Ward
#: protects from, the name a Meddling Mage forbids. One row per *record*, each
#: built out of this module's own readers of the printed sentence.
#:
#: It exists because the records were invisible. The engine wrote each one,
#: read it at every seam that needed it, and told nobody: the wire carried no
#: chosen colour, name, type or player, so a player facing an opponent's Voice
#: of All learned what it was protected from by having a spell fizzle, and the
#: log line one shape got (the single name) was the only place any of it
#: surfaced. :func:`chosen_as_entered` is what a client is sent, and
#: ``tests/engine/test_entry_choices_reach_the_client.py`` holds this table to
#: the writer in both directions over every permanent in the pool: a row that
#: claims a card finds its record written, and a ``chosen_*`` record the entry
#: writes belongs to a row.
#:
#: **Not here, on purpose**: a body chosen as it enters (Primal Clay — the
#: answer *is* the permanent's power, toughness, keyword and type, which the
#: card face already shows) and what was sacrificed or exiled as it entered
#: (Wood Elemental, Frankenstein's Monster — likewise its size and counters).
#: These rows are the choices nothing else on the card displays.
ENTRY_CHOICES: "tuple[EntryChoice, ...]" = (
    EntryChoice(
        CHOSEN_PLAYER_KEY, "Chosen player",
        lambda text, lines, name: bool(
            CHOOSE_COLOR_AND_OPPONENT_ON_ENTER in text
            or chooses_opponent_and_card_name_on_enter(text)
            or chooses_opponent_on_enter(text)
        ),
        _shown_player,
    ),
    EntryChoice(
        CHOSEN_COLOR_KEY, "Chosen color",
        lambda text, lines, name: bool(
            CHOOSE_COLOR_AND_OPPONENT_ON_ENTER in text
            or chooses_color_on_enter(text)
            or chooses_color_and_creature_type_on_enter(text)
            or _two_options_record(lines, name) == CHOSEN_COLOR_KEY
        ),
        _shown_color,
    ),
    EntryChoice(
        CHOSEN_CARD_NAME_KEY, "Named card",
        lambda text, lines, name: bool(
            chooses_opponent_and_card_name_on_enter(text)
            or chooses_card_name_on_enter(text) is not None
        ),
        _shown_card_name,
    ),
    EntryChoice(
        CHOSEN_CARD_NAMES_KEY, "Named cards",
        lambda text, lines, name: chooses_two_card_names_on_enter(text),
        _shown_each,
    ),
    EntryChoice(
        CHOSEN_LAND_TYPES_KEY, "Chosen land types (first, second)",
        lambda text, lines, name: chooses_two_land_types_on_enter(text),
        _shown_each,
    ),
    EntryChoice(
        CHOSEN_CREATURE_TYPE_KEY, "Chosen creature type",
        lambda text, lines, name: bool(
            chooses_creature_type_on_enter(text)
            or chooses_color_and_creature_type_on_enter(text)
        ),
        _shown_word,
    ),
    EntryChoice(
        CHOSEN_LAND_TYPE_KEY, "Chosen land type",
        lambda text, lines, name: bool(
            chooses_land_type_on_enter(text)
            or _two_options_record(lines, name) == CHOSEN_LAND_TYPE_KEY
        ),
        _shown_word,
    ),
    EntryChoice(
        CHOSEN_NUMBER_KEY, "Chosen number",
        lambda text, lines, name: any(
            choose_number_on_enter(line) is not None for line in lines
        ),
        _shown_word,
    ),
    EntryChoice(
        LIFE_PAID_AS_ENTERED, "Life paid as it entered",
        lambda text, lines, name: any(
            pay_any_life_on_enter(line, name) is not None for line in lines
        ),
        _shown_word,
    ),
)


def entry_choices_of(card) -> "tuple[EntryChoice, ...]":
    """The rows of :data:`ENTRY_CHOICES` *card*'s text makes as it enters.

    Read the way the entry state reads it — the compiled program's normalized
    text for the substring probes and ``line_rewrites.expand_card_lines`` for the
    whole-line ones — so "does this card choose a colour as it enters" has the
    answer the mixin acted on. Imported late for :func:`_entry_choice_catalogs`'
    reason: ``engine/oracle.py`` imports ``engine/enter_effects.py``, which
    imports this module.
    """
    # Cached by what the two readings below are functions of: a client polls,
    # and every poll asks this of every permanent on the table.
    key = (card.name, card.oracle_text, card.is_legendary)
    found = _ENTRY_CHOICES_OF.get(key)
    if found is None:
        from .oracle import compile_card_oracle
        from .line_rewrites import expand_card_lines

        text = compile_card_oracle(card).normalized_text
        lines = tuple(expand_card_lines(card))
        found = _ENTRY_CHOICES_OF[key] = tuple(
            row for row in ENTRY_CHOICES if row.asked(text, lines, card.name)
        )
    return found


_ENTRY_CHOICES_OF: "dict[tuple, tuple[EntryChoice, ...]]" = {}


def chosen_as_entered(game, permanent) -> "list[dict[str, str]]":
    """What *permanent* chose as it entered: ``[{"label", "value"}, …]``.

    One entry per row its text asks for **and** its metadata holds a record of,
    in table order. Asked of ``effective_card`` — a Clone of a Voice of All
    chose a colour of its own as it entered (CR 707.2, CR 614.1c) — and gated
    on the text as well as the record, because two of these keys are also
    written by effects that are not entry choices ("choose a color" on a
    resolving ability): what a permanent *currently says it chose as it
    entered* is the claim, and a stale record under a sentence it no longer
    prints is not one.

    Every choice here is public. CR 614.1c's choices are made as the permanent
    enters, in the open, and no sentence these rows read says "secretly" —
    ``test_entry_choices_reach_the_client.py`` fails if one ever does, because
    a hidden choice must not be sent to a viewer who may not see it.

    **A choice still being asked has not been made.** The entry state stamps a
    provisional default on the permanent before it arms the prompt, so that no
    reader ever meets the record missing; until the seat answers, that value
    is the engine's placeholder and not anything a player chose. Reported, it
    read "Chosen color: white" beside a Voice of All whose colour prompt was
    still on the screen — found by driving the card in a browser, since every
    test of this field entered its permanent at a seat nobody asks. The
    question is the one the state-based sweep already asks of a permanent
    whose entry is unfinished (``Game.permanent_is_entering``), so it covers
    every prompt kind an entry arms: the colour and name choices, a number
    (Shapeshifter), a life payment (Phyrexian Processor).
    """
    if game.permanent_is_entering(permanent):
        return []
    shown = []
    for row in entry_choices_of(permanent.effective_card):
        if row.key not in permanent.metadata:
            continue
        shown.append({
            "label": row.label,
            "value": row.shown(game, permanent.metadata[row.key]),
        })
    return shown


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
