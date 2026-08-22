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

from dataclasses import replace

from . import ast
from .errors import GrammarError
from .lexer import (MANA, PT, PUNCT, SELF, tokenize)
from .nouns import (parse_object_filter, parse_target_spec)
from .stream import TokenStream
from .vocabulary import (CARD_TYPES, COLOR_WORDS, CREATURE_TYPES, KEYWORD_INDEX,
                         NUMBER_WORDS, match_longest)
_WHENEVER_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_dies", ("a", "land", "is", "put", "into", "a", "graveyard", "from", "the", "battlefield")),
    # Longest first: the explicit-self spelling (Basri's Lieutenant) names the
    # same set as the bare one below it — see the oracle table's note.
    ("creature_you_control_dies",
     ("this", "creature", "or", "another", "creature", "you", "control", "dies")),
    ("creature_you_control_dies", ("a", "creature", "you", "control", "dies")),
    ("creature_opponent_controls_dies",
     ("a", "creature", "an", "opponent", "controls", "dies")),
    # Longer phrases first: this list is matched in order, so a prefix entry
    # would claim the shorter reading and strand the rest of the clause.
    ("creature_dealt_damage_by_self_dies",
     ("a", "creature", "dealt", "damage", "by", "this", "creature", "this", "turn", "dies")),
    ("creature_dies", ("a", "creature", "dies")),
    # "Whenever **equipped** creature dies" (Malefic Scythe) / "When
    # **enchanted** creature dies" (Creature Bond). One condition for both
    # words: an Equipment and an Aura attach the same way here, and the trigger
    # is about the permanent this one is attached to either way. Both spellings
    # are listed because both are printed, and neither is a wording of the other
    # in a way this table could derive.
    ("attached_creature_dies", ("equipped", "creature", "dies")),
    ("attached_creature_dies", ("enchanted", "creature", "dies")),
    # "…becomes the target of a spell or ability an opponent controls" (Warden
    # of the Woods). Longest first, as everywhere in this table: the narrowed
    # wording has the unnarrowed one as a strict prefix, so matching that first
    # would strand "an opponent controls" — and *both* front ends would then
    # name a condition that fires on the controller's own spells too.
    ("self_becomes_target",
     ("this", "creature", "becomes", "the", "target", "of", "a", "spell",
      "or", "ability", "an", "opponent", "controls")),
    ("self_becomes_target",
     ("this", "creature", "becomes", "the", "target", "of", "a", "spell",
      "or", "ability", "you", "control")),
    ("self_becomes_target",
     ("this", "creature", "becomes", "the", "target", "of", "a", "spell",
      "or", "ability")),
    # Longest first: the union form's phrase has the bare one as a strict
    # prefix, so matching the bare one first would leave "or planeswalker"
    # unaccounted and fail the line.
    ("creature_deals_combat_damage_to_player_or_walker",
     ("this", "creature", "deals", "combat", "damage", "to", "a", "player", "or", "planeswalker")),
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
    ("permanent_becomes_untapped", ("this", "creature", "becomes", "untapped")),
    ("permanent_becomes_untapped", ("this", "artifact", "becomes", "untapped")),
    ("permanent_becomes_untapped", ("this", "permanent", "becomes", "untapped")),
    ("self_becomes_tapped", ("this", "land", "becomes", "tapped")),
    ("land_tapped_for_mana", ("a", "player", "taps", "a", "land", "for", "mana")),
    ("spell_cast", ("a", "player", "casts", "a", "spell")),
    # Longest first: the bare phrase below is a strict prefix of this one, so
    # matching it first would leave "from anywhere other than their hand"
    # unaccounted and fail the line.
    ("opponent_attackers_declared",
     ("an", "opponent", "attacks", "with", "creatures")),
    ("opponent_casts_nth_spell_each_turn",
     ("an", "opponent", "casts", "their", "second", "spell", "each", "turn")),
    ("opponent_casts_spell",
     ("an", "opponent", "casts", "a", "spell", "from", "anywhere", "other",
      "than", "their", "hand")),
    ("opponent_casts_spell", ("an", "opponent", "casts", "a", "spell")),
    ("enchantment_cast", ("you", "cast", "an", "enchantment", "spell")),
    ("you_cast_spell", ("you", "cast", "a", "spell")),
    # Ankh of Mishra's, which has its own fire site. The bare creature and
    # artifact entries that used to sit beside it are gone: they had no
    # dispatcher and no card, and the subject-led production below reads the
    # same words as `matching_permanent_enters`, which does fire.
    ("land_enters", ("a", "land", "enters")),
    # "…your second card each turn" (Mystic Skyfish, Jolrael) — a different
    # article, so no prefix collision with the bare draw event above.
    ("draws_second_card", ("you", "draw", "your", "second", "card", "each", "turn")),
    ("draws_card", ("you", "draw", "a", "card")),
    # "Whenever you gain life …" (Vito). No amount in the phrase: how much was
    # gained is the event's, and a "that much" in the effect reads it out of the
    # trigger's captured context rather than out of these words.
    ("you_gain_life", ("you", "gain", "life")),
    # "Whenever you sacrifice a permanent …" (Havoc Jester). Announced from
    # ``Game.sacrifice_permanent``, the one place CR 701.21a happens. Bare, like
    # the life gain above: what was sacrificed is the event's, and no card in
    # the pool narrows it — a "…sacrifice a creature" entry would go above this
    # one, and does not collide with it.
    ("you_sacrifice_permanent", ("you", "sacrifice", "a", "permanent")),
    # "Whenever a source you control deals noncombat damage to an opponent …"
    # (Chandra's Pyreling). The amount is the event's, not the phrase's, so a
    # "that much" in the effect reads it out of the trigger's captured context —
    # which is what Chandra's Incinerator's second line wants.
    ("source_you_control_damages_opponent",
     ("a", "source", "you", "control", "deals", "noncombat", "damage",
      "to", "an", "opponent")),
)

# Events whose subject is an object *filter* the trigger carries, keyed by the
# fixed words printed in front of it. The mirror of the `_subject`-group
# patterns in engine/oracle.py's table: one printed phrase, read by the same
# noun parser on both sides of the pipeline, and held equal by
# `test_a_narrowed_trigger_reads_the_same_subject_on_both_sides`.
_FILTERED_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("this", "creature", "blocks"), "creature_blocks"),
    (("this", "creature", "becomes", "blocked", "by"), "creature_becomes_blocked"),
    # "Whenever you activate a loyalty ability of **a Chandra planeswalker**"
    # (Keral Keep Disciples) — the same pair the oracle regex table carries, so
    # the two front ends turn one printed phrase into one filter.
    (("you", "activate", "a", "loyalty", "ability", "of"),
     "you_activate_loyalty_ability"),
)

# The same, for events whose subject comes *first* — "a creature you control
# with deathtouch **attacks**". The verb behind the noun phrase names the event,
# so the phrase is read speculatively and these decide whether it was one.
# Longest first, per the ordering rule the whenever table follows.
_SUBJECT_LED_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("deals", "damage", "to", "a", "planeswalker"),
     "matching_creature_damages_planeswalker"),
    (("attacks",), "matching_creature_attacks"),
    (("enters", "the", "battlefield"), "matching_permanent_enters"),
    (("enters",), "matching_permanent_enters"),
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
    # "Your draw step" beside "each player's", the same pair as the upkeep two
    # above and for the same reason: the scope is what the dispatcher reads, and
    # a narrowing present on one side of the pipeline and absent on the other
    # compiles the card supported and fires it on the wrong event (round 7).
    ("draw_step_self", ("the", "beginning", "of", "your", "draw", "step")),
    ("draw_step_each", ("the", "beginning", "of", "each", "player", "'s", "draw", "step")),
    # CR 505.1a — the precombat main phase, the only one that is "first". Both
    # printed spellings; the M21 Shrines say "first" and modern templating says
    # "precombat". The oracle regex table carries the same pair, because a
    # condition narrowed on one side of the pipeline and not the other compiles
    # the card supported and fires it on the wrong event (round 7).
    ("main_phase_first", ("the", "beginning", "of", "your", "first", "main", "phase")),
    ("main_phase_first", ("the", "beginning", "of", "your", "precombat", "main", "phase")),
    # "Your" is a scope narrowing and so a separate kind, the same pair the
    # oracle regex table carries: a condition narrowed on one side of the
    # pipeline and not the other compiles the card supported and fires it on the
    # wrong event (round 7).
    ("end_step_self", ("the", "beginning", "of", "your", "end", "step")),
    ("end_step", ("the", "beginning", "of", "the", "end", "step")),
    ("end_step", ("the", "beginning", "of", "each", "end", "step")),
    # The narrowed form precedes its own prefix, per the rule above.
    ("combat_your_turn", ("the", "beginning", "of", "combat", "on", "your", "turn")),
    ("combat", ("the", "beginning", "of", "combat")),
)

_DURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # "for as long as this artifact remains tapped" (Ashnod's Battle Gear,
    # Tawnos's Weaponry). A *linked* duration: it ends when the source untaps
    # or leaves, so nothing schedules its removal — the effect is contributed
    # while the condition holds and simply stops being contributed when it does
    # not, which is CR 611.3b's "removal is the absence of a contribution".
    # The noun is any permanent word, because the card printing it says what it
    # is and the duration does not care.
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "artifact", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "creature", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "permanent", "remains", "tapped")),
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


# Moved here from `effects/characteristics.py` the day a second family needed
# it: "you gain 1 life **for each creature that died this turn**" (Canopy
# Stalker) is the life family asking exactly the question the counter family
# was already asking. A fragment two families want lives in `phrases`, never
# in one of them — that coupling is what makes the grouping stop being
# information, and the layering guard fails on it.
def _parse_for_each(stream: TokenStream) -> ast.DiedThisTurn | None:
    """``for each <objects> that died this turn`` — a trailing iteration clause.

    The set is a *history*, not a board state, which is why it produces
    :class:`ast.DiedThisTurn` rather than the noun phrase's own filter.

    "This turn" is required rather than defaulted, for the reason the deletion
    probe exists: the engine's death tally resets each turn, so a clause
    counting some other window is a different number — and letting the words be
    absent would let them be *deleted* with no change to the parse.

    Returning None leaves the cursor where it was, so a caller that does not
    find the clause still owes the rest of the line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("that", "died"):
        stream.reset(mark)
        return None
    if _parse_duration(stream).kind != "this_turn":
        stream.reset(mark)
        return None
    return ast.DiedThisTurn(filt)


def parse_subject_filter(phrase: str, *, plural: bool = False) -> ast.ObjectFilter | None:
    """The set of objects a printed noun phrase names, or None if it refuses.

    The whole phrase must be consumed. That is what makes this safe to give a
    *trigger* its subject: "a creature you control with deathtouch" is a
    narrowing, and a reader that consumed "a creature you control" and stopped
    would announce a trigger firing on a strictly larger set than the card
    prints — the dropped-rider bug class, in the one position where it fires on
    every creature instead of one.

    Public because ``engine/oracle.py``'s trigger-condition table reads its
    subjects through this: both front ends of the pipeline turn one printed
    phrase into one filter, rather than a regex approximating what the noun
    parser does. Held to that by
    ``test_a_narrowed_trigger_reads_the_same_subject_on_both_sides``.

    *plural* is for the one position where the noun phrase is **counted** rather
    than quantified: "whenever you attack with two or more **creatures with
    flying**" (Tide Skimmer). A bare plural is the noun parser's "all", which
    everywhere else would be a sweep and is refused for that reason — here the
    count in front of it is what says how many, so the phrase names a kind and
    "all" is the right reading of it.
    """
    lexed = tokenize(phrase)
    if not lexed.tokens:
        return None
    stream = TokenStream(lexed.tokens, phrase)
    filt = parse_subject_filter_at(stream, plural=plural)
    return filt if filt is not None and stream.exhausted else None


def parse_subject_filter_at(
    stream: TokenStream, *, plural: bool = False
) -> ast.ObjectFilter | None:
    """:func:`parse_subject_filter` over a stream, consuming what it reads.

    Refuses anything but the two articles a trigger subject is printed with —
    "a creature you control …" and "another Rogue you control …". "Target
    creature" and "each creature" name a chosen or an exhaustive set, and a
    condition claiming to fire on one of those would be describing a different
    card. *plural* swaps the admitted quantifier for the counted position; see
    :func:`parse_subject_filter`.
    """
    mark = stream.mark()
    # "another" sits where the article does, so it is read here and folded onto
    # the filter's exclusion field — the idiom `_parse_cost_object` and the
    # counters event above already use, rather than a noun-parser quantifier
    # that would change every targeted line in the pool. It leaves a bare noun
    # behind ("another **Rogue you control**"), which the noun parser quantifies
    # as the sweep "all"; without "another" the article has to be printed.
    another = bool(stream.accept_word("another"))
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if spec is None or spec.quantifier != ("all" if (another or plural) else "a"):
        stream.reset(mark)
        return None
    return replace(spec.filter, other_than_source=True) if another else spec.filter


def _accept_number(stream: TokenStream) -> int | None:
    """A printed number word, consumed. None (nothing consumed) for anything
    else, so the caller can reset and try the next production."""
    word = stream.peek_word()
    if word is None or word not in NUMBER_WORDS:
        return None
    stream.advance()
    return NUMBER_WORDS[word]


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


#: "Protection from the color of your choice" — the keyword whose argument is
#: not known until the effect resolves (CR 609.3). Named once here because the
#: parser writes it, the grant gate reads it and the handler resolves it, and a
#: third spelling of the same string is how those three come apart.
PROTECTION_FROM_CHOSEN_COLOR = "protection from the color of your choice"


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
            # "…from **the color of your choice**" (Feat of Resistance). CR
            # 609.3: the colour is chosen as the effect resolves, so the keyword
            # cannot name it — it names the *choice*, and the grant resolves it.
            # Read before the bare colour word, which would otherwise consume
            # "the" and grant protection from a colour called "the".
            if stream.accept_phrase("the", "color", "of", "your", "choice"):
                name = PROTECTION_FROM_CHOSEN_COLOR
            else:
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
    elif stream.accept_phrase("their", "owners'"):
        # "Return up to two target creatures to their owners' hands." (Read
        # the Tides.) The plural possessive is one token to the lexer; each
        # object still goes to its *own* owner's zone (CR 400.3), so the
        # owner reference is the same one the singular spelling records.
        owner = ast.PlayerRef("owner")
    elif stream.accept_phrase("its", "controller", "'s"):
        owner = ast.PlayerRef("controller")
    else:
        stream.accept_word("a", "an", "the")
    name = stream.peek_word()
    # "hands" is the plural template's spelling of "hand" — one zone per
    # object, pluralized because the objects are.
    if name is not None and name.endswith("s") and name[:-1] in _ZONES:
        name = name[:-1]
    elif name not in _ZONES:
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


# ---------------------------------------------------------------------------
# Trigger events (the condition half of a triggered ability line)
# ---------------------------------------------------------------------------
#
# Fragment productions over the word tables above: they read the clause
# between the trigger word and the comma, and nothing about a whole line.
# They lived in parser.py until the counters-put-on production pushed that
# module past the thousand-line guard, which is the guard working as
# documented — the family that should absorb this work is the one whose
# tables the productions already read.

_CAST_TYPE_FILTERS: dict[str, "ast.ObjectFilter"] = {
    "noncreature": ast.ObjectFilter(excluded_types=("creature",)),
    "nonartifact": ast.ObjectFilter(excluded_types=("artifact",)),
    "creature": ast.ObjectFilter(card_types=("creature",)),
    "artifact": ast.ObjectFilter(card_types=("artifact",)),
    "instant": ast.ObjectFilter(card_types=("instant",)),
    "sorcery": ast.ObjectFilter(card_types=("sorcery",)),
}

#: The printed type *unions* the same narrowing may name, longest first. A
#: union is not a filter this table can hold as one word, and the event filter
#: has to test "any of these" rather than "this one" — so it is its own table
#: and its own key, and the filter reads them apart.
_CAST_TYPE_UNIONS: tuple[tuple[tuple[str, ...], "ast.ObjectFilter"], ...] = (
    (("instant", "or", "sorcery"),
     ast.ObjectFilter(card_types=("instant", "sorcery"))),
)


def _accept_ability_activated_tail(stream: TokenStream) -> bool:
    """"…or a player activates an artifact's ability without {T} in its
    activation cost" — the second trigger event of a tap-or-activate ability.

    All-or-nothing: a partial match rewinds, so a line that says something else
    after "becomes tapped" keeps its tokens and the plain tap reading stands.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        stream.reset(mark)
        return False
    if not (
        stream.accept_phrase("a", "player", "activates")
        or stream.accept_phrase("an", "opponent", "activates")
    ):
        stream.reset(mark)
        return False
    # "an artifact's ability" / "an ability of enchanted artifact" — the object
    # whose ability it is repeats the subject already parsed, so it is consumed
    # rather than re-read. Whatever it named, the ability belongs to the same
    # set of permanents the tap half describes; a card pairing two *different*
    # subjects would not consume its line and would fall back.
    while not stream.exhausted and not stream.at_word("without"):
        stream.advance()
    if not stream.accept_word("without"):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != MANA or token.text != "{T}":
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_phrase("in", "its", "activation", "cost"):
        stream.reset(mark)
        return False
    return True


def _parse_quantified_tap_event(stream: TokenStream) -> ast.TriggerEvent | None:
    """"Whenever **a Forest an opponent controls** becomes tapped" (Lifetap) /
    "Whenever **a Mountain** is tapped for mana" (Gauntlet of Might).

    The two tapping events whose subject is *quantified* rather than named. The
    literal phrases in ``_WHENEVER_EVENTS`` cover the named subjects ("enchanted
    land", "this land", "a player taps a land"); here the subject is a noun
    phrase, so it is parsed and carried on the event instead of being spelled
    out once per printed land type.

    Tried only after that table, which is what keeps "whenever enchanted land
    becomes tapped" reading as ``enchanted_land_tapped``: ``parse_target_spec``
    would happily claim "enchanted land" as a quantified subject and name a
    condition the legacy table does not, which is precisely the disagreement
    ``test_every_executed_trigger_agrees_with_the_legacy_condition_table``
    exists to catch.
    """
    mark = stream.mark()
    spec = parse_target_spec(stream)
    # Only the indefinite "a <filter>" reading. "each"/"all"/"target" would be a
    # different event, and "this"/"enchanted" belong to the table above.
    if spec is not None and spec.quantifier == "a" and spec.filter is not None:
        if stream.accept_phrase("becomes", "tapped"):
            # "…**or a player activates an artifact's ability without {T} in
            # its activation cost**" (Haunting Wind, Powerleech). One printed
            # ability with two trigger events, so one kind — and read here,
            # attached to the tap reading, because the tap clause is its
            # prefix: returning the plain tap event first would leave the
            # second half of the *condition* to be parsed as the effect, and a
            # card whose effect happened to parse anyway would fire on half the
            # events it prints.
            if _accept_ability_activated_tail(stream):
                return ast.TriggerEvent(
                    "permanent_tapped_or_ability_activated",
                    "whenever",
                    subject=spec.filter,
                )
            return ast.TriggerEvent(
                "permanent_becomes_tapped", "whenever", subject=spec.filter
            )
        if stream.accept_phrase("is", "tapped", "for", "mana"):
            return ast.TriggerEvent(
                "land_tapped_for_mana", "whenever", subject=spec.filter
            )
    stream.reset(mark)
    return None


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        # "…one or more +1/+1 counters are put on <noun phrase>" (Wildwood
        # Scourge). The subject is parsed as a noun phrase and carried on the
        # event, so the exclusion and the controller scope are data — the same
        # shape the quantified tap events above use.
        mark = stream.mark()
        if stream.accept_phrase("one", "or", "more"):
            token = stream.peek()
            if token is not None and token.kind == PT and token.text == "+1/+1":
                stream.advance()
                if stream.accept_phrase("counters", "are", "put", "on"):
                    # "another" sits where the article does, so it is read here
                    # and folded onto the filter's existing exclusion field —
                    # the idiom `_parse_cost_object` and the condition parser
                    # already use, rather than a noun-parser quantifier that
                    # would change every targeted line in the pool.
                    another = bool(stream.accept_word("another"))
                    subject = parse_target_spec(stream)
                    if subject is not None:
                        filt = subject.filter
                        if another:
                            filt = replace(filt, other_than_source=True)
                        return ast.TriggerEvent(
                            "counters_put_on_creature", "whenever", subject=filt,
                        )
        stream.reset(mark)
        # "…casts a *blue* spell" (the Rod/Cup/Sphere cycle). The colour is part
        # of the condition rather than a per-card hook, which is what lets one
        # dispatcher serve every card written this way.
        mark = stream.mark()
        if stream.accept_phrase("a", "player", "casts", "a"):
            colour = stream.peek_word()
            if colour in COLOR_WORDS:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "spell_cast", "whenever",
                        subject=ast.ObjectFilter(colors=(COLOR_WORDS[colour],)),
                    )
        stream.reset(mark)
        # "…casts an **artifact** spell" (Urza's Chalice, Citanul Druid). The
        # type narrowing beside the colour one above, and for the same reason:
        # one dispatcher for every card printed this way. Both scopes are read
        # here because both are printed, and the bare spellings in the phrase
        # table below are strict prefixes of these — so a table entry would
        # claim the shorter reading and strand the type word, which is the
        # failure this whole file orders longest-first to avoid.
        for scope, opener in (
            ("spell_cast", ("a", "player", "casts")),
            ("opponent_casts_spell", ("an", "opponent", "casts")),
        ):
            mark = stream.mark()
            if stream.accept_phrase(*opener) and (
                stream.accept_word("a") or stream.accept_word("an")
            ):
                type_word = stream.peek_word()
                if type_word in CARD_TYPES:
                    stream.advance()
                    if stream.accept_word("spell"):
                        return ast.TriggerEvent(
                            scope, "whenever",
                            subject=ast.ObjectFilter(card_types=(type_word,)),
                        )
            stream.reset(mark)
        # "…you cast a spell that's white, blue, black, or red" (Quirion
        # Dryad): a colour-list narrowing of you_cast_spell. Read before the
        # phrase table, whose bare "you cast a spell" entry is its prefix.
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "a", "spell", "that", "'s"):
            colors: list[str] = []
            while True:
                word = stream.peek_word()
                if word not in COLOR_WORDS:
                    break
                stream.advance()
                colors.append(COLOR_WORDS[word])
                if stream.accept_punct(","):
                    stream.accept_word("or")
                    continue
                if stream.accept_word("or"):
                    continue
                break
            if len(colors) >= 2:
                return ast.TriggerEvent(
                    "you_cast_spell", "whenever",
                    subject=ast.ObjectFilter(colors=tuple(colors)),
                )
        stream.reset(mark)
        # "…you cast a noncreature spell" (Spellgorger Weird): a type
        # narrowing of the same condition. The word list mirrors the oracle
        # table's — only what the cast filter tests may be consumed, so a
        # subtype word ("Dog spell") keeps refusing the line rather than
        # compiling a trigger that fires on every spell. Read before the
        # phrase table, whose bare "you cast a spell" entry is its prefix.
        # "Whenever you cast **your first** instant or sorcery spell **each
        # turn**" (Double Vision). An ordinal: the trigger fires on the first
        # such spell of the turn and on no other, so the count is part of the
        # condition rather than of the effect. Read before the bare forms, whose
        # phrases are its strict prefixes.
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "your", "first"):
            for phrase, narrowed in _CAST_TYPE_UNIONS:
                if stream.accept_phrase(*phrase):
                    if stream.accept_phrase("spell", "each", "turn"):
                        return ast.TriggerEvent(
                            "you_cast_first_spell_each_turn", "whenever",
                            subject=narrowed,
                        )
                    break
            word = stream.peek_word()
            narrowed = _CAST_TYPE_FILTERS.get(word or "")
            if narrowed is not None:
                stream.advance()
                if stream.accept_phrase("spell", "each", "turn"):
                    return ast.TriggerEvent(
                        "you_cast_first_spell_each_turn", "whenever",
                        subject=narrowed,
                    )
        stream.reset(mark)
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "an"):
            for phrase, narrowed in _CAST_TYPE_UNIONS:
                if stream.accept_phrase(*phrase) and stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever", subject=narrowed,
                    )
        stream.reset(mark)
        mark = stream.mark()
        if stream.accept_phrase("you", "cast", "a"):
            word = stream.peek_word()
            narrowed = _CAST_TYPE_FILTERS.get(word or "")
            if narrowed is not None:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever", subject=narrowed,
                    )
            # "…you cast a **Dog** spell" (Rin and Seri, Inseparable). A
            # creature subtype, which this production refused until the cast
            # filter learned to test one. Read from the vocabulary rather than a
            # literal list, and *after* the type words above so a card type
            # keeps its own narrowing — "creature" is both a type word and, in
            # no set, a subtype, but the ordering is what guarantees it.
            if word in CREATURE_TYPES:
                stream.advance()
                if stream.accept_word("spell"):
                    return ast.TriggerEvent(
                        "you_cast_spell", "whenever",
                        subject=ast.ObjectFilter(subtypes=(word,)),
                    )
        stream.reset(mark)
        # Events whose *subject* is a noun phrase rather than the source. Each
        # is read before the phrase table below, whose bare entry is its strict
        # prefix — matching that first is what left Snarespinner compiled to an
        # unnarrowed "this creature blocks" with its rider on the floor.
        for phrase, kind in _FILTERED_EVENTS:
            mark = stream.mark()
            if stream.accept_phrase(*phrase):
                subject = parse_subject_filter_at(stream)
                if subject is not None:
                    return ast.TriggerEvent(kind, "whenever", subject=subject)
            stream.reset(mark)
        # The two triggers on the *declaration* (CR 508.1) — how many creatures
        # attacked, which no per-creature event can answer. Both read a printed
        # number, and both are tried before the phrase table below, whose
        # "this creature attacks" entry is the generic reading of the second.
        mark = stream.mark()
        if stream.accept_phrase("you", "attack", "with"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase("or", "more"):
                # The counted position: a bare plural names a *kind* here, and
                # the number in front of it is what says how many.
                subject = parse_subject_filter_at(stream, plural=True)
                if subject is not None:
                    return ast.TriggerEvent(
                        "attackers_declared", "whenever", subject=subject
                    )
        stream.reset(mark)
        if stream.accept_phrase("this", "creature", "and", "at", "least"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase("other", "creatures", "attack"):
                return ast.TriggerEvent("attackers_declared", "whenever")
        stream.reset(mark)
        # "Whenever **enchanted artifact** becomes tapped or a player
        # activates an ability of enchanted artifact without {T} in its
        # activation cost" (Artifact Possession). The named-subject spelling of
        # the compound event; read before the phrase table because that table's
        # "enchanted land becomes tapped" is this line's prefix and would claim
        # it, stranding the second half of the condition.
        attached_mark = stream.mark()
        if stream.accept_word("enchanted"):
            noun = stream.peek_word()
            if noun is not None:
                stream.advance()
                if stream.accept_phrase("becomes", "tapped") and _accept_ability_activated_tail(stream):
                    return ast.TriggerEvent(
                        "permanent_tapped_or_ability_activated",
                        "whenever",
                        subject=ast.ObjectFilter(is_enchanted=True),
                    )
        stream.reset(attached_mark)
        for kind, phrase in _WHENEVER_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "whenever")
        # "Whenever an **artifact you control** is put into a graveyard from
        # the battlefield" (Tablet of Epityr, Urza's Miter). Subject-led, so it
        # sits **after** the phrase table for the reason stated just below: the
        # table holds the specific readings, and "a land is put into a
        # graveyard from the battlefield" is Dingus Egg's own event with its own
        # fire site and its own damage shape. Read first, this production would
        # claim that line as a generic death and Dingus Egg would stop working.
        #
        # The article is consumed here rather than by the noun parser, which
        # refuses "an" as an unknown adjective — the same split the condition
        # parser makes for "you control **a** Swamp".
        grave_mark = stream.mark()
        stream.accept_word("a", "an")
        try:
            dying = parse_object_filter(stream)
        except GrammarError:
            dying = None
        if dying is not None and stream.accept_phrase(
            "is", "put", "into", "a", "graveyard", "from", "the", "battlefield"
        ):
            return ast.TriggerEvent("permanent_dies", "whenever", subject=dying)
        stream.reset(grave_mark)
        # "Whenever a creature you control with deathtouch attacks / deals
        # damage to a planeswalker" (Hooded Blightfang): the subject leads, so
        # there is no fixed prefix to key on — the noun phrase is tried and the
        # verb behind it decides whether it was one. *After* the phrase table,
        # because that table's entries are the specific readings: "a land
        # enters" is Ankh of Mishra's own event with its own fire site, and this
        # production would otherwise claim it as a generic entry.
        # "Whenever **one or more** Cats you control deal combat damage to a
        # player" (Feline Sovereign). Counted rather than quantified, which is
        # what the plural subject reading is for — and read before the
        # subject-led table below, whose productions expect the phrase to lead.
        batch_mark = stream.mark()
        if stream.accept_phrase("one", "or", "more"):
            batched = parse_subject_filter_at(stream, plural=True)
            if batched is not None and stream.accept_phrase(
                "deal", "combat", "damage", "to", "a", "player"
            ):
                return ast.TriggerEvent(
                    "one_or_more_deal_combat_damage", "whenever", subject=batched
                )
        stream.reset(batch_mark)
        mark = stream.mark()
        # "Whenever **this creature or** another Rogue you control enters"
        # (Thieves' Guild Enforcer) — the source's own entry spelled out. The
        # subject that follows is the same noun phrase the bare form reads, and
        # the difference is exactly the word "another": with the prefix the
        # source is *included*, so the exclusion the noun parser folds on for
        # "another" has to be undone here rather than left to narrow a set the
        # card widened.
        explicit_self = bool(stream.accept_phrase("this", "creature", "or"))
        subject = parse_subject_filter_at(stream)
        if subject is not None:
            if explicit_self:
                subject = replace(subject, other_than_source=False)
            for phrase, kind in _SUBJECT_LED_EVENTS:
                if stream.accept_phrase(*phrase):
                    return ast.TriggerEvent(kind, "whenever", subject=subject)
        stream.reset(mark)
        return _parse_quantified_tap_event(stream)
    if stream.accept_word("at"):
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        if stream.accept_phrase("this", "creature", "dies"):
            return ast.TriggerEvent("dies", "when")
        # "When there are four or more page counters on this artifact"
        # (Mazemind Tome). CR 603.8's state trigger. Read here as well as in
        # `engine/oracle.py`'s table because both front ends see the whole line,
        # and a condition only one of them reads leaves the other refusing the
        # effect behind it.
        if stream.accept_phrase("there", "are"):
            count = stream.peek_word()
            if count in NUMBER_WORDS:
                stream.advance()
                if stream.accept_phrase("or", "more"):
                    kind = stream.peek_word()
                    if kind:
                        stream.advance()
                        if stream.accept_word("counters") and stream.accept_word("on"):
                            if stream.at_kind(SELF) or stream.at_word("this"):
                                stream.advance()
                                stream.accept_word(
                                    "artifact", "creature", "enchantment",
                                    "permanent", "land",
                                )
                                return ast.TriggerEvent(
                                    "counters_reach_threshold", "when",
                                )
        if stream.accept_phrase("you", "control", "no", "islands"):
            return ast.TriggerEvent("no_islands", "when")
        if stream.accept_phrase("you", "control", "no", "lands"):
            return ast.TriggerEvent("no_lands", "when")
        mark = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                stream.accept_word("creature", "artifact", "enchantment", "land", "aura")
            if stream.accept_word("enters"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("enters_battlefield", "when")
            if stream.accept_word("leaves"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("leaves_battlefield", "when")
        stream.reset(mark)
        return None
    return None


def _parse_card_alternatives(
    stream: TokenStream,
) -> tuple[ast.ObjectFilter, ...] | None:
    """A printed **card** noun phrase, as alternatives — "a land card or Shrine
    card", "a creature card or Garruk planeswalker card".

    Lives here because two families need it: the discard *cost* that named it
    (Sanctum of Shattered Heights) and the look-and-pick effect that reads the
    same phrase (Garruk's Harbinger). A fragment two families need goes in
    ``phrases``, never in one of them — that coupling is what stops the grouping
    being information.

    "Discard a card" is the whole hand and returns ``()``; "Discard a land card
    or Shrine card" (Sanctum of Shattered Heights) returns one filter per side
    of the "or". A union rather than one narrowed filter because the two sides
    restrict *different* characteristics — a card type and a subtype — and an
    ObjectFilter AND's its fields, so folding them together would name a card
    that is both a land and a Shrine, which is nothing in the pool and a strictly
    harder cost than the card prints.

    None refuses the line, which is what a phrase the charger cannot test has to
    do: dropped instead, the cost would be payable with any card at all. What
    "cannot test" means is not decided here — ``chargeable_card_filter`` decides
    it, and ``engine/oracle.py``'s reader of the same clause asks the same
    function.
    """
    alternatives: list[ast.ObjectFilter] = []
    while True:
        stream.accept_word("a", "an")
        mark = stream.mark()
        try:
            filt = parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        from .lowering._common import chargeable_card_filter

        if chargeable_card_filter(filt) is None:
            stream.reset(mark)
            return None
        alternatives.append(filt)
        if not stream.accept_word("or"):
            break
    # A bare "Discard a card" narrows nothing, and an empty tuple is how the
    # charger is told so — never a filter with no keys set, which would read as
    # a narrowing the charger then ignores.
    from .lowering._common import chargeable_card_filter

    if len(alternatives) == 1 and not chargeable_card_filter(alternatives[0]):
        return ()
    return tuple(alternatives)
