"""Cycling (CR 702.29), the keyword the rules define as a rewrite.

CR 702.29a: *"Cycling is an activated ability that functions only while the
card with cycling is in a player's hand. 'Cycling [cost]' means '[Cost],
Discard this card: Draw a card.'"*

So this module is ``engine/equipment.py``'s equip half one keyword over, and
for the identical reason: a keyword whose definition **is** a sentence gets one
reader — the rewrite — rather than a second path beside every seam an activated
ability already passes through. :func:`expand_cycling_lines` turns the printed
line into that sentence before the compiler classifies anything, and from there
the grammar reads the effect, ``engine/activation_costs.py``'s cost parser reads the
"Discard this card" cost, ``engine/activation_zones.py`` reads CR 113.6j off
that cost, and the web layer offers it like any other hand-activatable ability.
Nothing downstream knows the word.

**The half that is not the rewrite is CR 702.29b**, and it is the half a naive
expansion gets wrong: *"Although the cycling ability can be activated only if
the card is in a player's hand, it continues to exist while the object is on
the battlefield and in all other zones."* Six of Urza's Saga's cycling cards
are lands and eight are creatures, so after this rewrite every one of them is a
permanent carrying an activated ability it must not be able to activate. That
is not enforced here — it is CR 113.6j ("an activated ability that has a cost
that can't be paid while the object is on the battlefield functions from any
zone in which its cost can be paid"), which is a rule about *costs* and not
about this keyword, and it lives in ``engine/activation_zones.py`` where every
activation path asks it.

**Typecycling (CR 702.29e) is the same rewrite with a search for its effect.**
*"'[Type]cycling [cost]' means '[Cost], Discard this card: Search your library
for a [type] card, reveal it, and put it into your hand. Then shuffle your
library.'"* So "Plainscycling {2}" becomes "{2}, Discard this card: Search your
library for a Plains card, reveal it, put it into your hand, then shuffle." —
the sentence the printed reminder text spells, which the grammar already reads
as a ``search_library`` with the type as its restriction. The type is "usually
a subtype … but can be any card type, subtype, supertype, or combination
thereof (as in 'basic landcycling')", so it is read word by word against
``data/vocabulary/`` and never against a list of the five basic land types: a
word no catalog knows leaves the line unrewritten, and the support gate refuses
it naming the line rather than searching for a type nothing defines.

CR 702.29f makes the result a cycling ability for every purpose — "Any cards
that trigger when a player cycles a card will trigger …", "Any effect that
stops players from cycling cards will stop players from activating cards'
typecycling abilities", "Any effect that increases or reduces a cycling cost
will increase or reduce a typecycling cost". All three are one question,
:func:`is_cycling_ability`, and it answers yes about a typecycling ability
without being told: it is the rewrite run backwards, and the rewrite now reads
the line.

:func:`is_cycling_line` is deliberately the *wide* shape, exactly as
``equipment.is_equip_line`` is: a variant the expansion cannot read reaches the
support gate in ``engine/oracle.py`` and is refused naming the line.

**"Players can't cycle cards."** (Stabilizer.) CR 702.29f's other sentence, and
the board half of CR 602.5: a line read here (:func:`cycling_ban_line`), off
the board (:func:`cycling_ban`), and asked through one row of
``engine/activation_prohibitions.py`` by every door an ability is activated
through. The row asks :func:`is_cycling_ability`, so the ban reaches a
typecycling ability by construction.
"""

from __future__ import annotations

import re

#: "Cycling {2}", "Cycling {1}{U}". Matched on the printed line with its
#: reminder text removed, case-insensitively; the cost is taken from the
#: printed line so a coloured pip keeps its letter.
_CYCLING_LINE = re.compile(
    r"^cycling\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)
_REMINDER = re.compile(r"\([^)]*\)")
#: Any line that *is* a cycling keyword line, readable or not — CR 702.29e's
#: "Plainscycling {2}" and "Basic landcycling {1}{G}" included. The wider shape
#: is what the support gate asks, so a variant the expansion refuses is reported
#: as an unimplemented cycling line rather than falling through to a gate that
#: never heard of the keyword. `\w*cycling` and not `cycling`, because
#: typecycling's type name is glued to the word.
_CYCLING_SHAPE = re.compile(r"^[a-z ]*cycling\b", re.IGNORECASE)

#: The rules text CR 702.29a gives the keyword.
CYCLING_RULES_TEXT = "{cost}, Discard this card: Draw a card."

#: "Plainscycling {2}", "Basic landcycling {1}{G}" — CR 702.29e's variant, the
#: type glued to the front of the word. The type is captured lazily so the
#: word "cycling" is never part of it; whether it *is* a type is the
#: vocabulary's question (:func:`_typecycling_type`), not this pattern's.
_TYPECYCLING_LINE = re.compile(
    r"^(?P<type>[a-z][a-z' -]*?)cycling\s+(?P<cost>(?:\{[^{}]+\})+)$",
    re.IGNORECASE,
)

#: The rules text CR 702.29e gives the variant, in the spelling the printed
#: reminder text uses ("…, reveal it, put it into your hand, then shuffle.") —
#: the CR's "…, and put it into your hand. Then shuffle your library." says the
#: same thing in two sentences, and the one-sentence form is the one the
#: grammar reads as one search.
TYPECYCLING_RULES_TEXT = (
    "{cost}, Discard this card: Search your library for {article} {type} card, "
    "reveal it, put it into your hand, then shuffle."
)


def _printed_keyword_line(line: str) -> str:
    """*line* with its reminder text and trailing full stop removed."""
    return " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")


def cycling_cost(line: str) -> str | None:
    """The cost of a printed **plain** cycling keyword line, or None.

    None for a typecycling line (CR 702.29e) — its cost is readable but its
    *effect* is a library search, and a caller asking for the draw's cost must
    not be handed one (:func:`typecycling_parts` is that line's reader).
    """
    match = _CYCLING_LINE.match(_printed_keyword_line(line))
    return match.group("cost") if match is not None else None


def _typecycling_type(printed: str) -> str | None:
    """The type phrase of a typecycling keyword, spelled for the search
    sentence, or None when a word of it is no type.

    CR 702.29e: "any card type, subtype, supertype, or combination thereof".
    Read word by word against the catalogs in ``data/vocabulary/`` — a
    multiword subtype by the longest match, as the noun parser reads one — so
    "basic land" is a supertype and a card type, "Plains" a land subtype and
    "Sliver" a creature type, while a word in none of them returns None and the
    line is left for the support gate to refuse. A supertype or card type is
    spelled lowercase and a subtype with its capital, which is how a search
    sentence prints each ("a basic land card", "a Plains card").
    """
    from .grammar.vocabulary import (CARD_TYPES, SUBTYPE_INDEX,
                                     TYPE_LINE_SUPERTYPES, display_type_word,
                                     match_longest)

    words = tuple(printed.lower().split())
    if not words:
        return None
    spelled: list[str] = []
    index = 0
    while index < len(words):
        subtype = match_longest(words, index, SUBTYPE_INDEX)
        if subtype is not None:
            matched, consumed = subtype
            spelled.append(display_type_word(matched))
            index += consumed
            continue
        word = words[index]
        if word not in TYPE_LINE_SUPERTYPES and word not in CARD_TYPES:
            return None
        spelled.append(word)
        index += 1
    return " ".join(spelled)


def typecycling_parts(line: str) -> tuple[str, str] | None:
    """``(type phrase, cost)`` of a printed typecycling line (CR 702.29e), or
    None — for plain cycling, for anything that is not the keyword, and for a
    type phrase no vocabulary catalog knows."""
    printed = _printed_keyword_line(line)
    if _CYCLING_LINE.match(printed):
        return None
    match = _TYPECYCLING_LINE.match(printed)
    if match is None:
        return None
    type_phrase = _typecycling_type(match.group("type").strip())
    if type_phrase is None:
        return None
    return type_phrase, match.group("cost")


def is_cycling_line(line: str) -> bool:
    """Whether *line* is a printed cycling keyword line, whether or not
    :func:`expand_cycling_line` can read it (CR 702.29e's typecycling is one
    it cannot)."""
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip()
    if not stripped or not _CYCLING_SHAPE.match(stripped):
        return False
    # The shape is a *keyword line*: the word (with an optional type glued to
    # its front) and a cost, and nothing else. Fluctuator's "Cycling abilities
    # you activate cost {2} less to activate" begins with the word and is a
    # static ability about other cards' cycling, not a cycling line — reading it
    # as one would refuse a card whose ability is a cost modifier.
    return bool(re.fullmatch(r"[a-z ]*cycling\s+(?:\{[^{}]+\})+\.?", stripped, re.IGNORECASE))


def expand_cycling_line(line: str) -> str | None:
    """The rules text for one printed cycling line, or None: CR 702.29a's
    draw for "Cycling [cost]", CR 702.29e's search for "[Type]cycling
    [cost]"."""
    cost = cycling_cost(line)
    if cost is not None:
        return CYCLING_RULES_TEXT.format(cost=cost)
    typed = typecycling_parts(line)
    if typed is None:
        return None
    type_phrase, cost = typed
    return TYPECYCLING_RULES_TEXT.format(
        cost=cost, type=type_phrase,
        article="an" if type_phrase[:1].lower() in "aeiou" else "a",
    )


def expand_cycling_lines(oracle_text: str) -> str:
    """*oracle_text* with every cycling keyword line rewritten to its rules text.

    Text without a cycling line is returned unchanged, so applying this to every
    card costs nothing but a scan. Applied by the compiler before any line is
    classified — beside ``expand_equip_lines`` and for the same reason: what the
    compiler reads and what every other reader of a card's lines (targeting,
    parse coverage, hook reliance) reads must be one text.
    """
    if not oracle_text or "ycling" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_cycling_line(line) or line for line in oracle_text.split("\n")
    )


def is_cycling_ability(card, ability) -> bool:
    """Whether *ability* — a compiled ``ParsedActivatedAbility`` of *card* — is
    a **cycling ability** (CR 702.29).

    The rewrite erases the word, which is what makes every downstream seam able
    to ignore the keyword; a card that asks *about* cycling abilities
    (Fluctuator: "Cycling abilities you activate cost {2} less to activate")
    has to get the word back, and this is the one place it is derived.

    The derivation is the rewrite run backwards: an ability is a cycling
    ability exactly when some printed line of its card is a cycling line whose
    :func:`expand_cycling_line` is that ability's ``source_line``. So it is the
    same equality ``web/state_view._printed_ability_line`` already walks to put
    "Cycling {2}" on the button, lifted here rather than copied — the button
    and the cost reduction must not be able to disagree about which ability the
    keyword named.

    **Not "has a ``discard_self`` cost".** That is CR 113.6j's zone question,
    not this one: Waker of Waves prints "{1}{U}, Discard this card: ..." and is
    not cycling, so keying on the cost would discount an ability the card never
    calls cycling — a cost charged too low is a free ability, the direction
    every cost reader here is written against.

    CR 702.29f makes typecycling a cycling ability too, and the derivation
    gives that free: :func:`expand_cycling_line` reads "Plainscycling {2}" into
    its search, so the search ability's ``source_line`` is that expansion and
    this answers yes about it without being told — for the cycle trigger, the
    cost modifiers and Stabilizer's ban alike.
    """
    wanted = (getattr(ability, "source_line", "") or "").strip()
    if not wanted:
        return False
    return any(
        (expand_cycling_line(line) or "").strip() == wanted
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    )


def unread_cycling_line(oracle_text: str) -> str | None:
    """A printed cycling-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run: a line still reading as cycling by then is one
    :func:`expand_cycling_line` declined — a typecycling line whose type no
    catalog knows — and the card is unsupported naming it. Without this such an
    instant would report supported off its *other* line and silently drop the
    keyword — the population a refusal census cannot reach, which is exactly
    what the fourteen already-"supported" cycling cards in Urza's Saga were
    before this module existed.
    """
    for line in (oracle_text or "").split("\n"):
        if is_cycling_line(line):
            return " ".join(_REMINDER.sub("", line).split()).strip()
    return None


#: "Players can't cycle cards." (Stabilizer.) The sentence names every player,
#: so it binds its own controller as thoroughly as anybody — the shape of
#: ``cast_bans``' board-wide sentences, read the same way.
_CYCLING_BAN = re.compile(r"^players can't cycle cards$")

#: The claim name the support gate, the grammar's registry and the parse
#: census give the line — its own, for ``cast_bans.COMBAT_PLAY_BAN_CLAIM``'s
#: reason: it is the whole of what the permanent does.
CYCLING_BAN_CLAIM = "cycling_ban"


def cycling_ban_line(line: str) -> bool:
    """Whether *line* is "Players can't cycle cards."

    One reader, three callers, as every board-wide ban has: the grammar's
    registry and the support gate ask it so the line is *claimed*, and
    :func:`cycling_ban` asks it so the line is *enforced* — a claim that
    outlives its enforcement is an artifact reporting supported while every
    seat keeps cycling.
    """
    normalized = (line or "").strip().lower().rstrip(".").replace("’", "'")
    return _CYCLING_BAN.match(normalized) is not None


def cycling_ban(game) -> str | None:
    """The name of a permanent saying players can't cycle cards, or None.

    Every battlefield and no seat comparison. Read off ``effective_card`` for
    the reason ``activation_restrictions.global_activation_ban`` reads it: a
    text change (CR 613 layer 3) or a lost ability is the board's question,
    and this table should not have to know text can change.
    """
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if cycling_ban_line(raw_line):
                return permanent.card.name
    return None


__all__ = [
    "CYCLING_BAN_CLAIM",
    "CYCLING_RULES_TEXT",
    "TYPECYCLING_RULES_TEXT",
    "cycling_ban",
    "cycling_ban_line",
    "cycling_cost",
    "expand_cycling_line",
    "expand_cycling_lines",
    "is_cycling_ability",
    "is_cycling_line",
    "typecycling_parts",
    "unread_cycling_line",
]
