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
from .nouns import (parse_target_spec)
from .stream import TokenStream
from .vocabulary import (COLOR_WORDS, KEYWORD_INDEX, match_longest)
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
)

# Events whose subject is an object *filter* the trigger carries, keyed by the
# fixed words printed in front of it. The mirror of the `_subject`-group
# patterns in engine/oracle.py's table: one printed phrase, read by the same
# noun parser on both sides of the pipeline, and held equal by
# `test_a_narrowed_trigger_reads_the_same_subject_on_both_sides`.
_FILTERED_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("this", "creature", "blocks"), "creature_blocks"),
    (("this", "creature", "becomes", "blocked", "by"), "creature_becomes_blocked"),
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


def parse_subject_filter(phrase: str) -> ast.ObjectFilter | None:
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
    """
    lexed = tokenize(phrase)
    if not lexed.tokens:
        return None
    stream = TokenStream(lexed.tokens, phrase)
    filt = parse_subject_filter_at(stream)
    return filt if filt is not None and stream.exhausted else None


def parse_subject_filter_at(stream: TokenStream) -> ast.ObjectFilter | None:
    """:func:`parse_subject_filter` over a stream, consuming what it reads.

    Refuses anything but the two articles a trigger subject is printed with —
    "a creature you control …" and "another Rogue you control …". "Target
    creature" and "each creature" name a chosen or an exhaustive set, and a
    condition claiming to fire on one of those would be describing a different
    card.
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
    if spec is None or spec.quantifier != ("all" if another else "a"):
        stream.reset(mark)
        return None
    return replace(spec.filter, other_than_source=True) if another else spec.filter


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
        for kind, phrase in _WHENEVER_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "whenever")
        # "Whenever a creature you control with deathtouch attacks / deals
        # damage to a planeswalker" (Hooded Blightfang): the subject leads, so
        # there is no fixed prefix to key on — the noun phrase is tried and the
        # verb behind it decides whether it was one. *After* the phrase table,
        # because that table's entries are the specific readings: "a land
        # enters" is Ankh of Mishra's own event with its own fire site, and this
        # production would otherwise claim it as a generic entry.
        mark = stream.mark()
        subject = parse_subject_filter_at(stream)
        if subject is not None:
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
