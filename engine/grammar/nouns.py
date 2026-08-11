"""Object- and player-reference sub-parser.

Produces :class:`~engine.grammar.ast.ObjectFilter` /
:class:`~engine.grammar.ast.TargetSpec` / :class:`~engine.grammar.ast.PlayerRef`
from a noun phrase.

The rule that matters here: **every word in the phrase must be consumed**. The
legacy ``parse_target_filter`` scanned for a handful of known words and threw
the rest away, so "destroy target creature an opponent controls" and "destroy
target creature" produced identical instructions. Here an adjective the parser
does not recognize raises, which turns a silent mis-resolution into a visible
unsupported card.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .lexer import NUMBER, WORD
from .stream import TokenStream
from .vocabulary import (
    ALL_SUBTYPES,
    CARD_TYPES,
    COLOR_WORDS,
    CREATURE_TYPES,
    KEYWORD_INDEX,
    SUBTYPE_INDEX,
    SUPERTYPES,
    match_longest,
)

# Head nouns that are not card types but name a set of objects. "target" is one
# of them: Fireball's "among any number of targets" uses it as a bare noun.
_GENERIC_NOUNS = frozenset({
    "permanent", "permanents", "card", "cards", "spell", "spells",
    "source", "sources", "target", "targets",
})

# "this <self-word>" refers to the ability's own source.
_SELF_NOUNS = frozenset({
    "creature", "artifact", "enchantment", "land", "permanent", "spell", "aura", "card",
})

_STATE_ADJECTIVES = {
    "tapped": ("tapped", True),
    "untapped": ("tapped", False),
    "attacking": ("attacking", True),
    "blocking": ("blocking", True),
    "blocked": ("blocked", True),
    "unblocked": ("blocked", False),
}

_COMPARISON_WORDS = {
    "less": "le",       # "2 or less"
    "greater": "ge",    # "3 or greater"
    "more": "ge",
}

# Zones a noun phrase can be scoped to ("target creature card **from your
# graveyard**"). The battlefield is deliberately absent: it is already the
# default, so consuming "from the battlefield" here would leave no trace that
# the phrase had been read at all — exactly the silent-drop this parser exists
# to prevent. A production that needs it should say so explicitly.
_ZONE_NOUNS = frozenset({"graveyard", "hand", "library", "exile"})


def _singular(word: str) -> str:
    """Best-effort singularization for vocabulary lookup. Only trims when the
    trimmed form is itself known, so "wall"/"walls" both resolve but a real
    word ending in s is left alone."""
    if word.endswith("s"):
        stem = word[:-1]
        if stem in CARD_TYPES or stem in ALL_SUBTYPES or stem in _GENERIC_NOUNS:
            return stem
        if word.endswith("es"):
            stem2 = word[:-2]
            if stem2 in CARD_TYPES or stem2 in ALL_SUBTYPES:
                return stem2
    return word


def _accept_card_noun(stream: TokenStream) -> bool:
    """Consume a "card"/"cards" head noun trailing a type word.

    "Creature" names a permanent; "creature card" names a card, which is what a
    graveyard or a hand holds (CR 400.1). Leaving the word unconsumed used to
    fail the whole line on the full-consumption invariant; consuming it without
    recording it would be worse, so the caller stores the answer on the filter.
    """
    return stream.accept_word("card", "cards")


def parse_player_ref(stream: TokenStream) -> ast.PlayerRef | None:
    """Parse a player reference at the cursor, or return None."""
    mark = stream.mark()

    if stream.accept_word("you"):
        return ast.PlayerRef("you")

    if stream.accept_phrase("each", "player"):
        return ast.PlayerRef("each_player")
    if stream.accept_phrase("each", "opponent"):
        return ast.PlayerRef("each_opponent")
    if stream.accept_phrase("target", "player"):
        return ast.PlayerRef("target_player")
    if stream.accept_phrase("target", "opponent"):
        return ast.PlayerRef("target_opponent")
    if stream.accept_phrase("that", "player"):
        return ast.PlayerRef("that_player")
    if stream.accept_phrase("its", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("their", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("defending", "player"):
        return ast.PlayerRef("defending_player")
    if stream.accept_phrase("the", "chosen", "player"):
        return ast.PlayerRef("chosen_player")
    if stream.accept_phrase("an", "opponent"):
        return ast.PlayerRef("target_opponent")

    # "that land's controller" / "this creature's controller" — a possessive
    # noun phrase resolving to a player. The lexer split "land's" into
    # "land" + "'s".
    if stream.at_word("that", "this"):
        probe = stream.mark()
        stream.advance()
        noun = stream.peek_word()
        if noun is not None and (
            _singular(noun) in CARD_TYPES or _singular(noun) in _GENERIC_NOUNS
        ):
            stream.advance()
            if stream.accept_word("'s") and stream.accept_word("controller"):
                return ast.PlayerRef("that_player")
        stream.reset(probe)

    stream.reset(mark)
    return None


def _parse_keyword_list(stream: TokenStream) -> tuple[str, ...]:
    """Parse one or more keyword names ("flying", "first strike and trample").

    The conjunction is only consumed when a keyword actually follows it:
    "each creature without flying and each player" continues with a second
    *recipient*, not a second keyword, and eating that "and" would strand the
    rest of the clause.
    """
    keywords: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, KEYWORD_INDEX)
        if matched is None:
            break
        name, consumed = matched
        keywords.append(name)
        stream.advance(consumed)
        conjunction = stream.mark()
        if not (stream.accept_word("and") or stream.accept_word("or")):
            break
        if match_longest(stream.words_from(), 0, KEYWORD_INDEX) is None:
            stream.reset(conjunction)
            break
    if not keywords:
        raise stream.error("expected a keyword ability")
    return tuple(keywords)


def _parse_comparison(stream: TokenStream) -> ast.Comparison:
    """Parse "N or less" / "N or greater" / "N" following power/toughness."""
    amount = parse_amount(stream)
    if stream.accept_word("or"):
        token = stream.peek()
        word = token.text if token is not None and token.kind == WORD else None
        if word in _COMPARISON_WORDS:
            stream.advance()
            return ast.Comparison(_COMPARISON_WORDS[word], amount)
        raise stream.error("expected 'less' or 'greater'")
    return ast.Comparison("eq", amount)


def parse_object_filter(stream: TokenStream, *, allow_bare: bool = False) -> ast.ObjectFilter:
    """Parse the noun phrase describing a set of objects.

    *allow_bare* permits a phrase with no head noun (used by "each creature
    without flying"-style sweeps where the type word doubles as the head).
    """
    card_types: list[str] = []
    supertypes: list[str] = []
    subtypes: list[str] = []
    colors: list[str] = []
    excluded_colors: list[str] = []
    excluded_types: list[str] = []
    excluded_subtypes: list[str] = []
    with_keywords: list[str] = []
    without_keywords: list[str] = []
    controller: str | None = None
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    power: ast.Comparison | None = None
    mana_value: ast.Comparison | None = None
    toughness: ast.Comparison | None = None
    other_than_source = False
    is_source = False
    is_enchanted = False
    is_card = False
    zone = "battlefield"
    zone_owner: ast.PlayerRef | None = None
    saw_head = False
    type_match = "any"

    # --- self / enchanted references ------------------------------------
    if stream.at_word("this"):
        probe = stream.mark()
        stream.advance()
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in _SELF_NOUNS:
            stream.advance()
            is_source = True
            saw_head = True
            if _singular(noun) in CARD_TYPES:
                card_types.append(_singular(noun))
        else:
            stream.reset(probe)

    if not saw_head and stream.accept_word("enchanted"):
        noun = stream.peek_word()
        if noun is None:
            raise stream.error("expected a noun after 'enchanted'")
        stream.advance()
        is_enchanted = True
        saw_head = True
        if _singular(noun) in CARD_TYPES:
            card_types.append(_singular(noun))

    # --- adjectives ------------------------------------------------------
    while not saw_head:
        # Adjectives may be comma-separated: "target nonartifact, nonblack
        # creature" (Terror). The comma carries no meaning of its own, but it
        # must be consumed or full-token consumption fails the whole line.
        if stream.at_punct(",") and stream.peek_word(1) is not None:
            stream.advance()
        word = stream.peek_word()
        if word is None:
            break

        if word.startswith("non") and len(word) > 3:
            body = word[3:].lstrip("-")
            if body in COLOR_WORDS:
                excluded_colors.append(COLOR_WORDS[body])
                stream.advance()
                continue
            if body in CARD_TYPES:
                excluded_types.append(body)
                stream.advance()
                continue
            if body in ALL_SUBTYPES:
                excluded_subtypes.append(body)
                stream.advance()
                continue

        # "Other Goblins", "Other Zombie creatures" — the lord template. It
        # means the same as the postmodifier "other than this creature" handled
        # below (exclude the ability's own source), so it sets the same field
        # rather than minting a second one that every lowering would then have
        # to learn about separately.
        #
        # Guarded on the *next* word so it can never eat the postmodifier form:
        # "other than this creature" is not a leading adjective, and consuming
        # its "other" here would leave "than this creature" to be read as a noun
        # phrase.
        if word == "other" and stream.peek_word(1) != "than":
            other_than_source = True
            stream.advance()
            continue

        if word in COLOR_WORDS:
            colors.append(COLOR_WORDS[word])
            stream.advance()
            continue

        if word in _STATE_ADJECTIVES:
            attribute, value = _STATE_ADJECTIVES[word]
            if attribute == "tapped":
                tapped = value
            elif attribute == "attacking":
                attacking = value
            elif attribute == "blocking":
                blocking = value
            else:
                blocked = value
            stream.advance()
            continue

        if word in SUPERTYPES:
            supertypes.append(word)
            stream.advance()
            continue

        # A card type or subtype word ends the adjective run and becomes the
        # head noun — but "artifact creature" is two types, so keep going
        # while consecutive type words appear.
        singular = _singular(word)
        if singular in CARD_TYPES:
            card_types.append(singular)
            stream.advance()
            # Collect further type words: "artifact creature" stacks two types,
            # "artifact or enchantment" and "artifact, creature, or land" list
            # alternatives. All three are type unions as far as matching goes,
            # so one loop covers them — the separators are optional.
            while True:
                probe = stream.mark()
                separated = stream.accept_punct(",")
                separated = stream.accept_word("or", "and") or separated
                following = stream.peek_word()
                if following is not None and _singular(following) in CARD_TYPES:
                    card_types.append(_singular(following))
                    # No separator means juxtaposition ("artifact creature"),
                    # which names one permanent holding both types rather than
                    # either of two.
                    if not separated:
                        type_match = "all"
                    stream.advance()
                    continue
                stream.reset(probe)
                break
            is_card = _accept_card_noun(stream)
            saw_head = True
            break

        matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
        if matched is None and singular != word:
            # A pluralized subtype ("Destroy all Islands", "can't be blocked by
            # Walls"). The catalog stores singulars, except where the singular
            # is itself plural (Plains).
            probe = match_longest((singular,) + stream.words_from(1), 0, SUBTYPE_INDEX)
            if probe is not None and probe[1] == 1:
                matched = probe
        if matched is not None:
            name, consumed = matched
            subtypes.append(name)
            stream.advance(consumed)
            # "Djinn or Efreet" — collect alternatives.
            while stream.at_word("or"):
                probe = stream.mark()
                stream.advance()
                alternative = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
                if alternative is None:
                    stream.reset(probe)
                    break
                subtypes.append(alternative[0])
                stream.advance(alternative[1])
            following = stream.peek_word()
            if following is not None and _singular(following) in CARD_TYPES:
                continue
            is_card = _accept_card_noun(stream)
            saw_head = True
            break

        if singular in _GENERIC_NOUNS:
            is_card = singular == "card"
            stream.advance()
            # "permanent card(s)" (Ugin, the Spirit Dragon's −10): a card whose
            # type would make it a permanent. The trailing noun is recorded the
            # same way a type word's is — see _accept_card_noun.
            if not is_card and _accept_card_noun(stream):
                is_card = True
            # "target spell or permanent" (the Lace cycle) unions two *generic*
            # nouns. Neither contributes a card type, so the union restricts
            # nothing and the filter is unchanged — but the tokens still have to
            # be consumed, or the line fails the full-consumption invariant and
            # the whole card falls back to the legacy rules.
            while True:
                probe = stream.mark()
                if not stream.accept_word("or", "and"):
                    break
                following = stream.peek_word()
                if following is None or _singular(following) not in _GENERIC_NOUNS:
                    stream.reset(probe)
                    break
                stream.advance()
            saw_head = True
            break

        break

    if not saw_head and not allow_bare:
        raise stream.error("expected an object noun")

    # --- postmodifiers ---------------------------------------------------
    while True:
        if stream.accept_phrase("you", "control"):
            controller = "you"
            continue
        # "you don't control" (Teferi, Master of Time's −3). The lexer keeps
        # "don't" as one word.
        if stream.accept_phrase("you", "don't", "control"):
            controller = "not_you"
            continue
        if stream.accept_phrase("an", "opponent", "controls"):
            controller = "opponent"
            continue
        # "each creature target opponent controls" (Teferi, Timeless Voyager's
        # −8): the controller is a chosen player — the spell targets the
        # opponent, not the creatures.
        if stream.accept_phrase("target", "opponent", "controls"):
            controller = "target_opponent"
            continue
        # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the
        # object is colored — matching reads the effective colors, so a
        # colorless artifact escapes and a Lace-painted one does not.
        if stream.accept_phrase("that", "'s", "one", "or", "more", "colors"):
            colored = True
            continue
        if stream.accept_phrase("that", "player", "controls"):
            controller = "that_player"
            continue
        if stream.accept_phrase("they", "control"):
            controller = "that_player"
            continue
        if stream.at_word("other"):
            probe = stream.mark()
            stream.advance()
            # "other than this creature" — the noun is required, so that
            # deleting it changes the parse rather than being quietly ignored.
            if stream.accept_phrase("than", "this"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in _SELF_NOUNS:
                    stream.advance()
                    other_than_source = True
                    continue
            stream.reset(probe)
            break
        if stream.at_word("from", "in"):
            # "from your graveyard" / "in a graveyard" — which zone the objects
            # are in, and whose. Both halves are recorded: a handler that only
            # searches the caster's own graveyard must be able to refuse
            # "from a graveyard" rather than search the wrong one.
            probe = stream.mark()
            stream.advance()
            owner: ast.PlayerRef | None = None
            if stream.accept_word("your"):
                owner = ast.PlayerRef("you")
            elif stream.accept_word("their"):
                owner = ast.PlayerRef("owner")
            else:
                stream.accept_word("a", "an", "the")
            noun = stream.peek_word()
            if noun in _ZONE_NOUNS:
                stream.advance()
                zone = noun
                zone_owner = owner
                continue
            stream.reset(probe)
            break
        if stream.at_word("with"):
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("power"):
                power = _parse_comparison(stream)
                continue
            if stream.accept_word("toughness"):
                toughness = _parse_comparison(stream)
                continue
            # "with mana value X" (Spell Blast). Two words, so it is tried
            # before the keyword list — "mana" alone is not a keyword, but
            # leaving the phrase unmatched would strand "value X" and fail the
            # whole line rather than restricting the noun phrase.
            if stream.accept_phrase("mana", "value"):
                mana_value = _parse_comparison(stream)
                continue
            try:
                with_keywords.extend(_parse_keyword_list(stream))
                continue
            except Exception:
                stream.reset(probe)
                break
        if stream.at_word("without"):
            probe = stream.mark()
            stream.advance()
            try:
                without_keywords.extend(_parse_keyword_list(stream))
                continue
            except Exception:
                stream.reset(probe)
                break
        break

    # A creature subtype implies the creature type: "destroy target Wall" means
    # a creature. Land/artifact subtypes ("destroy all Plains") must not, so the
    # implication is keyed on the vocabulary the subtype came from.
    if subtypes and not card_types and all(s in CREATURE_TYPES for s in subtypes):
        card_types.append("creature")

    return ast.ObjectFilter(
        card_types=tuple(card_types),
        type_match=type_match,
        supertypes=tuple(supertypes),
        subtypes=tuple(subtypes),
        colors=tuple(colors),
        excluded_colors=tuple(excluded_colors),
        excluded_types=tuple(excluded_types),
        excluded_subtypes=tuple(excluded_subtypes),
        with_keywords=tuple(with_keywords),
        without_keywords=tuple(without_keywords),
        controller=controller,
        tapped=tapped,
        attacking=attacking,
        blocking=blocking,
        blocked=blocked,
        power=power,
        toughness=toughness,
        mana_value=mana_value,
        zone=zone,
        zone_owner=zone_owner,
        is_card=is_card,
        other_than_source=other_than_source,
        is_source=is_source,
        is_enchanted=is_enchanted,
    )


def parse_target_spec(stream: TokenStream) -> ast.TargetSpec | None:
    """Parse a quantified object reference, or return None if the cursor is not
    at one."""
    mark = stream.mark()

    # CR 115.4 "any target" — creatures, players, planeswalkers, battles.
    if stream.accept_phrase("any", "target"):
        return ast.TargetSpec("any_target")

    # "each of up to two target creatures you control" — a distributive wrapper
    # over the noun phrase rather than a quantifier of its own. It names exactly
    # the objects the phrase behind it names and says the effect applies to each
    # of them, which is already what a per-object effect does with a list, so
    # the count and the filter come from the wrapped phrase. Consumed here so
    # "each" is not mistaken for the sweep quantifier below, which would turn
    # "up to two target creatures" into every creature on the battlefield.
    stream.accept_phrase("each", "of")

    quantifier: str | None = None
    count = 1

    # "up to two **other** target creatures you control" prints "other" between
    # the count and the word "target" — the one position `parse_object_filter`
    # cannot reach, because it reads the filter from after "target". Recorded
    # here and folded into that filter below, so this spelling and the
    # postmodifier one ("target creature other than this creature") set the same
    # field and no lowering has to learn two names for one restriction.
    other_before_target = False
    distinct_from_prior = False

    if stream.accept_phrase("up", "to"):
        quantifier = "up_to"
        token = stream.peek()
        if token is not None and (token.kind == NUMBER or token.kind == WORD):
            amount = parse_amount(stream)
            count = amount.value if isinstance(amount, ast.Fixed) else 1
        if stream.at_word("other") and stream.peek_word(1) == "target":
            stream.advance()
            other_before_target = True
        # "up to one target creature", "up to two target creatures" — the word
        # "target" is part of the printed quantifier phrase, not the filter.
        stream.accept_word("target")
    elif stream.accept_word("target"):
        quantifier = "target"
    elif stream.at_word("another") and stream.peek_word(1) == "target":
        # "another target creature" (Garruk, Savage Herald) — a second chosen
        # object, distinct from the sentence's earlier choice. Guarded on the
        # following "target" so the sacrifice-cost reading of "another
        # <object>" is untouched.
        stream.advance(2)
        quantifier = "target"
        distinct_from_prior = True
    elif stream.accept_word("each"):
        quantifier = "each"
    elif stream.accept_word("all"):
        quantifier = "all"
    elif stream.at_word("this"):
        quantifier = "this"
    elif stream.at_word("enchanted"):
        quantifier = "this"
    elif stream.accept_word("a", "an"):
        quantifier = "a"

    if quantifier is None:
        # A bare plural noun phrase ("black creatures get +1/+1") is an
        # implicit "all".
        try:
            filt = parse_object_filter(stream)
        except Exception:
            stream.reset(mark)
            return None
        return ast.TargetSpec("all", filt)

    try:
        filt = parse_object_filter(stream)
    except Exception:
        stream.reset(mark)
        return None
    if other_before_target:
        filt = dataclasses.replace(filt, other_than_source=True)
    return ast.TargetSpec(quantifier, filt, count, distinct_from_prior=distinct_from_prior)


def parse_recipient(stream: TokenStream) -> ast.Recipient | None:
    """Parse either a player reference or a quantified object reference."""
    player = parse_player_ref(stream)
    if player is not None:
        return player
    # A bare "it" refers back to the ability's own source ("put a +1/+1 counter
    # on it" on a trigger whose subject was "this creature").
    if stream.at_word("it"):
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    # The card naming itself mid-sentence ("put a loyalty counter on Garruk") —
    # the lexer already collapsed the name to one SELF token.
    token = stream.peek()
    if token is not None and token.kind == "self":
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    return parse_target_spec(stream)


__all__ = [
    "parse_object_filter", "parse_player_ref", "parse_recipient", "parse_target_spec",
]
