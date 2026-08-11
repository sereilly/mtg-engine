"""Phrase-level vocabularies and the productions that read a *fragment*.

The bottom of the parser: word tables — trigger events, durations, counter
kinds, board counts, zone names — and the handful of productions that consume
part of a sentence rather than a whole one. Everything above imports from here
and nothing here imports back.

`_parse_zone` and `_parse_mana_payment` live here rather than with the effects
for a reason worth keeping: they were the *only* references crossing between
effect families ("search your library" needs a zone, "unless they pay" needs a
cost). A fragment two families need is not an effect, and filing it as one is
what couples them.

Kept as data plus a reader rather than as branches inside the productions that
use them: a table is a thing a new card is added to, a branch is a thing that
has to be found first.
"""

from . import ast
from .lexer import (MANA, PUNCT)
from .stream import TokenStream
from .vocabulary import (KEYWORD_INDEX, match_longest)
_WHENEVER_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_dies", ("a", "land", "is", "put", "into", "a", "graveyard", "from", "the", "battlefield")),
    ("creature_you_control_dies", ("a", "creature", "you", "control", "dies")),
    # Longer phrases first: this list is matched in order, so a prefix entry
    # would claim the shorter reading and strand the rest of the clause.
    ("creature_dealt_damage_by_self_dies",
     ("a", "creature", "dealt", "damage", "by", "this", "creature", "this", "turn", "dies")),
    ("creature_dies", ("a", "creature", "dies")),
    ("creature_deals_combat_damage", ("this", "creature", "deals", "combat", "damage", "to", "a", "player")),
    # Narrowed to an opponent (Hypnotic Specter). Must precede the unnarrowed
    # form below, which is a strict prefix of it: matching that first would name
    # a condition the legacy table does not — the disagreement
    # `test_every_executed_trigger_agrees_with_the_legacy_condition_table`
    # exists to catch — and strand "to an opponent" besides.
    ("creature_deals_damage_to_opponent",
     ("this", "creature", "deals", "damage", "to", "an", "opponent")),
    ("creature_deals_damage", ("this", "creature", "deals", "damage")),
    # The Basilisk cycle's event. Precedes "this creature blocks", which is a
    # strict prefix of it: matching that first would name a condition nothing
    # dispatches for these cards and strand the rest of the clause.
    ("creature_blocks_or_blocked_by_nonwall",
     ("this", "creature", "blocks", "or", "becomes", "blocked", "by", "a", "non-wall", "creature")),
    ("creature_attacks_or_blocks", ("this", "creature", "attacks", "or", "blocks")),
    ("creature_attacks", ("this", "creature", "attacks")),
    ("creature_blocks", ("this", "creature", "blocks")),
    ("creature_becomes_blocked", ("this", "creature", "becomes", "blocked")),
    ("creature_dealt_damage", ("this", "creature", "is", "dealt", "damage")),
    ("enchanted_land_tapped", ("enchanted", "land", "becomes", "tapped")),
    ("self_becomes_tapped", ("this", "land", "becomes", "tapped")),
    ("land_tapped_for_mana", ("a", "player", "taps", "a", "land", "for", "mana")),
    ("spell_cast", ("a", "player", "casts", "a", "spell")),
    ("opponent_casts_spell", ("an", "opponent", "casts", "a", "spell")),
    ("enchantment_cast", ("you", "cast", "an", "enchantment", "spell")),
    ("you_cast_spell", ("you", "cast", "a", "spell")),
    ("creature_enters", ("a", "creature", "enters")),
    ("land_enters", ("a", "land", "enters")),
    ("artifact_enters", ("an", "artifact", "enters")),
    ("draws_card", ("you", "draw", "a", "card")),
)

_AT_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("upkeep_self", ("the", "beginning", "of", "your", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "player", "'s", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "upkeep")),
    # An Aura firing on the upkeep of whoever controls what it enchants
    # (Feedback, Wanderlust, Warp Artifact). Written out per enchanted type
    # rather than as "enchanted <any noun>'s controller" so the set stays
    # exactly the one the legacy condition table admits — `enchanted land's
    # controller` is deliberately NOT here. Cursed Land's upkeep damage is
    # already dealt by the enchant-land pass in phases/upkeep_step.py, so a
    # fourth entry would compile a *second* trigger and the card would deal its
    # damage twice (pinned by test_cursed_land_deals_upkeep_damage_to_land_controller).
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "creature", "'s", "controller")),
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "artifact", "'s", "controller")),
    ("upkeep_enchanted_controller",
     ("the", "beginning", "of", "the", "upkeep", "of", "enchanted", "enchantment", "'s", "controller")),
    ("upkeep_chosen", ("the", "beginning", "of", "the", "chosen", "player", "'s", "upkeep")),
    ("draw_step_each", ("the", "beginning", "of", "each", "player", "'s", "draw", "step")),
    ("end_step", ("the", "beginning", "of", "the", "end", "step")),
    ("end_step", ("the", "beginning", "of", "each", "end", "step")),
    ("end_step", ("the", "beginning", "of", "your", "end", "step")),
    # The narrowed form precedes its own prefix, per the rule above.
    ("combat_your_turn", ("the", "beginning", "of", "combat", "on", "your", "turn")),
    ("combat", ("the", "beginning", "of", "combat")),
)

_DURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("until_end_of_turn", ("until", "end", "of", "turn")),
    ("until_end_of_combat", ("until", "end", "of", "combat")),
    ("until_your_next_turn", ("until", "your", "next", "turn")),
    ("this_turn", ("this", "turn")),
)

_COUNTER_KINDS = ("+1/+1", "+1/+0", "+0/+1", "-1/-1")

# Board-state counts that bind a clause's X, one literal phrase per name. Not
# parsed compositionally, and that is the design rather than a shortcut: each
# of these is arithmetic an ``ObjectFilter`` cannot express — a count taken at
# an earlier point in the turn, a count of a hidden zone with a constant
# subtracted — so the *handler* computes the whole thing and the grammar's only
# job is to say which count was written. A phrase not listed here fails to
# match, the line fails full-token consumption, and the card falls back rather
# than compiling onto a handler that counts something else.
_BOARD_COUNTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cards_in_hand_minus_four",
        ("the", "number", "of", "cards", "in", "their", "hand", "minus", "4"),
    ),
    (
        "untapped_lands_at_turn_start",
        ("the", "number", "of", "untapped", "lands", "they", "controlled",
         "at", "the", "beginning", "of", "this", "turn"),
    ),
)

# Zone names a destination clause can end in (CR 400.1).
_ZONES = frozenset({"battlefield", "graveyard", "hand", "library", "exile", "stack"})


# ---------------------------------------------------------------------------
# Small shared productions
# ---------------------------------------------------------------------------


def _parse_duration(stream: TokenStream) -> ast.Duration:
    """Parse a trailing duration clause. Absent wording means permanent — one
    node replacing the fifteen places the legacy rules re-literalled these."""
    for kind, phrase in _DURATIONS:
        if stream.accept_phrase(*phrase):
            return ast.Duration(kind)
    return ast.Duration()


def _accept_literal(stream: TokenStream, *phrase: str) -> bool:
    """Consume consecutive tokens by their text, all-or-nothing.

    ``TokenStream.accept_phrase`` requires every token to be a *word*, which
    "…hand minus 4" is not — the 4 lexes as a number. Punctuation is still
    refused, so a phrase can never silently span a sentence boundary.
    """
    if len(stream.tokens) - stream.pos < len(phrase):
        return False
    for offset, text in enumerate(phrase):
        token = stream.tokens[stream.pos + offset]
        if token.kind == PUNCT or token.text != text:
            return False
    stream.advance(len(phrase))
    return True


def _parse_where_x_is(stream: TokenStream) -> ast.BoardCount | None:
    """", where X is <board-state count>" — the trailer that says what the X of
    the preceding clause counts.

    Returning None on an unrecognized count leaves its tokens unconsumed, so the
    line fails the full-consumption invariant and falls back. That is the whole
    value of the production: the alternative — consuming "where X is …" and
    whatever follows — would make every card written this way compile onto
    whichever count the caller happened to assume.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_phrase("where", "x", "is"):
        stream.reset(mark)
        return None
    for name, phrase in _BOARD_COUNTS:
        if _accept_literal(stream, *phrase):
            return ast.BoardCount(name)
    stream.reset(mark)
    return None


def _parse_keywords(stream: TokenStream) -> tuple[str, ...]:
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            break
        name, consumed = matched
        stream.advance(consumed)
        # "protection from red" — the argument belongs to the keyword.
        if name == "protection" and stream.accept_word("from"):
            colour = stream.peek_word()
            if colour is not None:
                stream.advance()
                name = f"protection from {colour}"
        keywords.append(name)
        if not (stream.accept_word("and") or stream.accept_word("or")):
            break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords)


def _parse_zone(stream: TokenStream) -> ast.Zone:
    """A zone destination: ``your hand``, ``the battlefield``, ``its owner's hand``.

    The possessive is part of the zone, not decoration: Unsummon returns a
    creature to *its owner's* hand while Raise Dead returns a card to *your*
    hand, and those are different players whenever you have stolen the creature.
    An unrecognized possessive raises rather than falling through to the bare
    zone name, so the distinction can never be lost by omission.
    """
    owner: ast.PlayerRef | None = None
    if stream.accept_word("your"):
        owner = ast.PlayerRef("you")
    elif stream.accept_phrase("its", "owner", "'s") or stream.accept_phrase(
        "their", "owner", "'s"
    ):
        owner = ast.PlayerRef("owner")
    elif stream.accept_phrase("its", "controller", "'s"):
        owner = ast.PlayerRef("controller")
    else:
        stream.accept_word("a", "an", "the")
    name = stream.peek_word()
    if name not in _ZONES:
        raise stream.error("expected a zone name")
    stream.advance()
    return ast.Zone(name, owner)


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
