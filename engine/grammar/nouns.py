"""What a printed noun phrase *describes*: the objects it would match.

Produces :class:`~engine.grammar.ast.ObjectFilter` from the head noun and the
adjectives and postmodifiers around it. The other half of a noun phrase — how
many of those objects it names, whether they are targets, and the player forms
that are not objects at all — is `references.py`, which reads this one. The cut
is CR 109 against CR 115: what an object *is* and how many of them an effect
*chooses* are separate questions, asked by separate callers, and holding them in
one module took it past the thousand-line guard.

The rule that matters here: **every word in the phrase must be consumed**. The
legacy ``parse_target_filter`` scanned for a handful of known words and threw
the rest away, so "destroy target creature an opponent controls" and "destroy
target creature" produced identical instructions. Here an adjective the parser
does not recognize raises, which turns a silent mis-resolution into a visible
unsupported card.
"""

from __future__ import annotations

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import PT, SELF, WORD, render
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
    # "Sacrifice this **token**" — modern templating for a token's own printed
    # ability (the Treasure token). Not a card type: it is what the object is,
    # exactly as "this permanent" is, and it names the same source.
    "token",
    # "Sacrifice this **Equipment**" / "put a soul counter on this Equipment"
    # (Malefic Scythe). An Equipment subtype used as the card's own noun, the
    # same way "this Aura" already is above.
    "equipment",
})

# "…attached to that creature" — the trailing clause naming what an Aura or
# Equipment is on. Only "that creature" is admitted: it is the referent the
# spell's own target supplies, and any other noun would be a set the handler has
# no way to resolve.
_ATTACHED_TO_REFERENTS = {("that", "creature"): "target"}

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


def _match_subtype(stream: TokenStream, start: int) -> tuple[str, int] | None:
    """The subtype at *start*, and how many **tokens** it consumes.

    Wraps ``match_longest`` for one reason the plain call cannot handle: the
    lexer splits a possessive into two tokens, so "Urza's" arrives as
    ``urza`` + ``'s`` and the land type ``urza's`` can never match. That is not
    a silent miss — it is a silent *wrong* match, because ``Urza`` on its own
    is a planeswalker type, so "target Urza's Mine" read as "target Urza
    planeswalker" and left ``'s mine`` for someone else to choke on.

    The join is tried only when the joined form is itself in the vocabulary, so
    a grammatical possessive ("that artifact's controller", "the sacrificed
    artifact's mana value") is untouched — ``artifact's`` is not a subtype.
    Deciding this here rather than in the lexer is deliberate: the lexer is
    vocabulary-free on purpose, and the question "is this word a subtype" only
    has an answer in the noun position.
    """
    words = stream.words_from(start)
    if not words:
        return None
    if len(words) >= 2 and words[1] == "'s":
        possessive = (words[0] + "'s",) + words[2:]
        matched = match_longest(possessive, 0, SUBTYPE_INDEX)
        if matched is not None:
            # +1 token: the possessive marker the join swallowed.
            return matched[0], matched[1] + 1
    return match_longest(words, 0, SUBTYPE_INDEX)


def _accept_card_noun(stream: TokenStream) -> bool:
    """Consume a "card"/"cards" head noun trailing a type word.

    "Creature" names a permanent; "creature card" names a card, which is what a
    graveyard or a hand holds (CR 400.1). Leaving the word unconsumed used to
    fail the whole line on the full-consumption invariant; consuming it without
    recording it would be worse, so the caller stores the answer on the filter.
    """
    return stream.accept_word("card", "cards")


def accept_source_reference(stream: TokenStream) -> bool:
    """Consume a reference to the ability's own source — "it", "this", or
    "this <noun the card calls itself>" — and say whether one was there.

    A predicate rather than a filter, because the callers that need it are
    asking about *identity* and not about characteristics: an intervening-if
    naming the source is answered from ``context.source_permanent``, so an
    ``ObjectFilter`` built here would carry a narrowing nothing consults. The
    three spellings are one production so a card printing "this artifact" is
    read the same way as one printing "it", which is the whole difference
    between Mana Vault's draw-step clause and Basalt Monolith's.
    """
    if stream.accept_word("it"):
        return True
    # The card naming itself ("blocked by Sentinel") — the lexer has already
    # collapsed the name to one SELF token, so this spelling and "this
    # creature" are the same reference here as everywhere else.
    token = stream.peek()
    if token is not None and token.kind == SELF:
        stream.advance()
        return True
    mark = stream.mark()
    if stream.accept_word("this"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in _SELF_NOUNS:
            stream.advance()
        return True
    stream.reset(mark)
    return False


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


#: The printed kinds of ability a spell may name on the stack, longest first so
#: "activated or triggered" is read whole rather than as its first half.
_ABILITY_KIND_PHRASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("activated", "or", "triggered"), ("activated", "triggered")),
    (("triggered", "or", "activated"), ("activated", "triggered")),
    (("activated",), ("activated",)),
    (("triggered",), ("triggered",)),
)


def _accept_ability_noun(stream: TokenStream) -> tuple[str, ...]:
    """The ability kinds a phrase like "activated or triggered ability" names,
    or () when the cursor is not at one.

    The word "ability" is required. Without it "triggered" is an adjective
    looking for a noun and the phrase is somebody else's — and a phrase that
    consumed "activated" and then found no "ability" would have eaten a word
    the rest of the parse needs.
    """
    for phrase, kinds in _ABILITY_KIND_PHRASES:
        mark = stream.mark()
        if not stream.accept_phrase(*phrase):
            stream.reset(mark)
            continue
        if stream.accept_word("ability", "abilities"):
            return kinds
        stream.reset(mark)
    return ()


def _accept_ability_source(stream: TokenStream) -> tuple[str, ...]:
    """``from an <card type> source`` after an ability noun, or () if absent.

    The one adjective an ability on the stack can carry: it has no card and no
    type line (CR 113.7a), so "artifact" here describes the *permanent the
    ability came from*, not the ability. Consumed here rather than by the
    adjective loop below for the same reason the ability noun returns early —
    that loop asks questions of a card.

    A word that is not a card type leaves the cursor where it was, so the line
    fails full-token consumption and the card falls back, rather than the
    narrowing being dropped and the counter reaching every ability.
    """
    mark = stream.mark()
    if not stream.accept_word("from"):
        stream.reset(mark)
        return ()
    stream.accept_word("a", "an")
    word = stream.peek_word()
    if word is None or _singular(word) not in CARD_TYPES:
        stream.reset(mark)
        return ()
    stream.advance()
    if not stream.accept_word("source"):
        stream.reset(mark)
        return ()
    return (_singular(word),)


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
    owned_by: str | None = None
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    any_states: tuple[str, ...] = ()
    blocking_source = False
    power: ast.Comparison | None = None
    mana_value: ast.Comparison | None = None
    toughness: ast.Comparison | None = None
    other_than_source = False
    is_source = False
    is_enchanted = False
    is_card = False
    with_plus1_counter = False
    nontoken = False
    token_only = False
    their_choice = False
    named: str | None = None
    attached_to: str | None = None
    zone = "battlefield"
    zone_owner: ast.PlayerRef | None = None
    saw_head = False
    type_match = "any"
    subtype_match = "any"

    # --- an ability on the stack ----------------------------------------
    # "activated or triggered ability" / "activated ability" / "triggered
    # ability" (Sublime Epiphany). Read first and whole, because none of the
    # machinery below applies: an ability on the stack has no card, no type
    # line and no permanent behind it (CR 113.7a), so every adjective the loop
    # further down collects would be a question with no object to ask it of.
    ability_kinds = _accept_ability_noun(stream)
    if ability_kinds:
        return ast.ObjectFilter(
            zone="stack",
            ability_kinds=ability_kinds,
            ability_source_types=_accept_ability_source(stream),
        )

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
            # "nontoken" (Lich, Gadrak, Chrome Replicator). CR 111.1: a token is
            # not a card and has no card type of its own, so it is neither an
            # excluded type nor an excluded subtype — it is its own restriction,
            # read off the permanent the same way the forced-sacrifice prompt has
            # always read it.
            if body == "token":
                nontoken = True
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
            # "a **green or white** creature" (Abomination) — a union of colour
            # adjectives, read as one the way "attacking or blocking" below is.
            # Taking "green" alone would end the noun phrase at "or", leaving
            # "or white creature" unconsumed and refusing the whole line, which
            # is exactly how Abomination refused.
            colors.append(COLOR_WORDS[word])
            stream.advance()
            while stream.at_word("or") and stream.peek_word(1) in COLOR_WORDS:
                stream.advance()
                colors.append(COLOR_WORDS[str(stream.peek_word())])
                stream.advance()
            continue

        # "attacking **or** blocking creature" (the four Legends pingers),
        # "**tapped or blocking** creature" (Tetsuo Umezawa) — a union of state
        # adjectives, read before either of them is taken on its own. Consuming
        # "attacking" first and leaving "or blocking" would end the noun phrase
        # mid-sentence, which is how the pingers refused.
        #
        # Any pair, not the one the pingers happened to print. Spelling that
        # pair in made every other union a non-match: Tetsuo's line refused with
        # "expected something to destroy" for a template the engine implements —
        # the same false-negative the land type in `combat_restrictions.py` and
        # the colour union above this one document.
        if (
            word in _STATE_ADJECTIVES
            and stream.peek_word(1) == "or"
            and stream.peek_word(2) in _STATE_ADJECTIVES
        ):
            states = [word]
            stream.advance()
            while stream.at_word("or") and stream.peek_word(1) in _STATE_ADJECTIVES:
                stream.advance()
                states.append(str(stream.peek_word()))
                stream.advance()
            any_states = tuple(states)
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
                if stream.accept_word("and"):
                    # "and/or" lexes as two words; as a union separator the
                    # two readings coincide ("instant and/or sorcery cards",
                    # Chandra, Heart of Fire's −9), so the "or" is absorbed.
                    stream.accept_word("or")
                    separated = True
                elif stream.accept_word("or"):
                    separated = True
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
            # "target instant or sorcery **spell**" (Miscast): the head noun
            # after a type union may be "spell", naming an object on the stack
            # rather than a permanent of those types. Recorded as the zone so
            # a lowering that resolves battlefield objects refuses the line
            # instead of reading it as "target instant or sorcery".
            if not is_card and stream.accept_word("spell", "spells"):
                zone = "stack"
            saw_head = True
            break

        matched = _match_subtype(stream, 0)
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
            # "Djinn or Efreet", and the comma-separated form a longer list is
            # printed in: "Bird, Cat, Dog, Goat, Ox, or Snake" (Animal
            # Sanctuary). Both spellings are one union — English punctuates a
            # list of six differently from a list of two, and the card means the
            # same thing either way.
            #
            # A comma is only consumed when a subtype follows it, so a phrase
            # that ends its noun and goes on ("destroy target Wall, then draw a
            # card") keeps the comma for whatever reads the rest.
            while stream.at_word("or") or stream.at_punct(","):
                probe = stream.mark()
                stream.advance()
                # "…, or Snake" — the final item carries both, and the comma
                # above already moved past its own token.
                stream.accept_word("or")
                alternative = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
                if alternative is None:
                    stream.reset(probe)
                    break
                subtypes.append(alternative[0])
                stream.advance(alternative[1])
            # **Adjacent subtypes are a conjunction, not a union.** "Urza's
            # Power-Plant" is two land types on one permanent (CR 205.3i), and
            # a type line lists them exactly this way. The union spellings
            # above all carry a connector ("or", or the comma of a longer
            # list); a subtype following another with no connector at all can
            # only be narrowing it further.
            #
            # Only entered when no union was collected, so "Djinn or Efreet"
            # cannot acquire an "all" it would then fail.
            if len(subtypes) == 1:
                while True:
                    adjacent = _match_subtype(stream, 0)
                    if adjacent is None:
                        break
                    subtypes.append(adjacent[0])
                    stream.advance(adjacent[1])
                    subtype_match = "all"
            following = stream.peek_word()
            if following is not None and _singular(following) in CARD_TYPES:
                continue
            is_card = _accept_card_noun(stream)
            saw_head = True
            break

        # "any number of **tokens** created with this creature" (Tetravus). Not
        # a card type and not a generic noun: CR 111.1 makes "token" a fact
        # about the object, so it is a restriction the same way "nontoken" is
        # one, and it must not fall through to a head noun that restricts
        # nothing.
        if word in ("token", "tokens"):
            token_only = True
            stream.advance()
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
            # the card reports unsupported naming the clause.
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

    not_ability_targeted_by_same_name = False
    created_with_source = False
    in_combat_with_source = False
    dealt_damage_to_source_this_turn = False

    # --- postmodifiers ---------------------------------------------------
    while True:
        # "you both own and control" (Obelisk of Undoing). Read before the bare
        # "you control", which is its suffix: matching that first would consume
        # "control" and strand "own", and — worse — would compile the card as
        # though it read "any permanent you control", which is exactly the
        # stolen permanent it is printed to exclude.
        if stream.accept_phrase("you", "both", "own", "and", "control"):
            controller = "you"
            owned_by = "you"
            continue
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
        # "target nontoken permanent an opponent **owns**" (Bronze Tablet).
        # Ownership, not control (CR 108.3 against CR 613 layer 2) — a card
        # printed with "owns" excludes the permanent it stole from that
        # opponent, and reading one as the other is exactly the mistake round
        # 13 recorded about Obelisk of Undoing.
        if stream.accept_phrase("an", "opponent", "owns"):
            owned_by = "opponent"
            continue
        # "creatures **your opponents** control" (Massacre Wurm, Waker of
        # Waves) — the plural spelling of the same scope: every opponent's
        # creatures, and none of the controller's own.
        if stream.accept_phrase("your", "opponents", "control"):
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
        # "creatures **blocking this creature**" (The Wretched) — the set of
        # blockers declared against the ability's own source (CR 509.1a). Only
        # a self-reference is admitted after "blocking": "blocking that
        # creature" would name an object this filter has no way to carry, so
        # the words stay unconsumed and the line fails loudly instead.
        # "blocking **or**…" is not this branch: "blocking or blocked by this
        # creature" (Sentinel) is the two-sided in-combat relation read further
        # down, and this alternative testing first would probe, fail on "or"
        # and break the whole postmodifier scan before that one is asked —
        # the round-11 merge found exactly that.
        if stream.at_word("blocking") and stream.peek_word(1) != "or":
            probe = stream.mark()
            stream.advance()
            token = stream.peek()
            if token is not None and token.kind == "self":
                stream.advance()
                blocking_source = True
                continue
            if stream.accept_word("this"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in _SELF_NOUNS:
                    stream.advance()
                    blocking_source = True
                    continue
            stream.reset(probe)
            break
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
            elif stream.accept_word("than"):
                # "other than Halfdane" — the card excluding itself by name,
                # which the lexer already collapsed to one SELF token. The same
                # restriction as "other than this creature", so it sets the
                # same field rather than minting a second one.
                token = stream.peek()
                if token is not None and token.kind == SELF:
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
            # "their <zone>", and the spelled-out "that player's <zone>" (Storm
            # Seeker): one node for both, because `parse_player_ref` already reads
            # "they" as an alias of "that player", and a second kind here would be
            # a second answer every count lowering had to learn.
            elif stream.accept_word("their") or stream.accept_phrase("that", "player", "'s"):
                owner = ast.PlayerRef("owner")
            # "from **target player's** graveyard" (Drafna's Restoration): a
            # chosen player rather than a fixed one, and a *second* target on the
            # same line — the cards are targets too.
            elif stream.accept_phrase("target", "player", "'s"):
                owner = ast.PlayerRef("target_player")
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
            # "with a +1/+1 counter on it" (Tempered Veteran). Only the +1/+1
            # kind is accepted: the counters the engine records under another
            # name have no matcher, so a phrase naming one fails the line
            # loudly rather than matching every creature.
            if stream.at_word("a", "an"):
                counter_probe = stream.mark()
                stream.advance()
                token = stream.peek()
                if (
                    token is not None
                    and token.kind == PT
                    and token.text == "+1/+1"
                ):
                    stream.advance()
                    if stream.accept_word("counter") and stream.accept_phrase("on", "it"):
                        with_plus1_counter = True
                        continue
                stream.reset(counter_probe)
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
        if stream.at_word("that"):
            # "…**that isn't the target of an ability from another creature
            # named ~**" (Goblin Artisans). A guard against two copies aiming
            # their abilities at the same spell, printed as a restriction on the
            # noun phrase. The source is named by the asking card's own name,
            # which the lexer has already collapsed to one SELF token — so
            # nothing here knows a card name, and a second card printing the
            # clause about itself gets it for free.
            probe = stream.mark()
            stream.advance()
            if stream.accept_phrase(
                "isn't", "the", "target", "of", "an", "ability",
                "from", "another", "creature", "named",
            ):
                token = stream.peek()
                if token is not None and token.kind == SELF:
                    stream.advance()
                    not_ability_targeted_by_same_name = True
                    continue
            # "…**that dealt damage to it this turn**" (Brine Hag). A history
            # relative to the ability's source, answered from the damage record
            # the victim carries rather than from the object's characteristics
            # — so it is a flag the one lowering written for it reads, and every
            # other one refuses (see ``ObjectFilter``). "This turn" is required:
            # without it the sentence says something the record cannot answer.
            elif stream.accept_phrase("dealt", "damage", "to"):
                if accept_source_reference(stream) and stream.accept_phrase(
                    "this", "turn"
                ):
                    dealt_damage_to_source_this_turn = True
                    continue
            stream.reset(probe)
            break
        if stream.at_word("blocking") and stream.peek_word(1) == "or":
            # "…**blocking or blocked by this creature**" (Sentinel, and the
            # noun-phrase half of Abu Ja'far's sentence). The object is in
            # combat with the ability's own source (CR 509) — a relation, not a
            # characteristic, so the field is never emitted as a payload key;
            # the lowering written for it carries the relation itself and every
            # other one refuses the phrase. Both words are required: bare
            # "blocking" is the state adjective the premodifier run already
            # reads, and "blocked by" without an "or" would be a different
            # (one-sided) relation this does not implement.
            probe = stream.mark()
            stream.advance()
            if stream.accept_phrase("or", "blocked", "by") and accept_source_reference(stream):
                in_combat_with_source = True
                continue
            stream.reset(probe)
            break
        if stream.at_word("created"):
            # "…tokens **created with this creature**" (Tetravus). Which
            # permanent made them — a fact about their history, so it is read
            # off a record the token maker stamps rather than off the token's
            # characteristics.
            probe = stream.mark()
            stream.advance()
            if stream.accept_phrase("with", "this"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in _SELF_NOUNS:
                    stream.advance()
                    created_with_source = True
                    continue
            stream.reset(probe)
            break
        if stream.at_word("named"):
            # "a card **named** Frantic Inventory" — a restriction on what the
            # object *is*, so it belongs on the filter beside every other one.
            # The search production used to read it alone, which is why a count
            # of cards by name had nowhere to say so.
            probe = stream.mark()
            stream.advance()
            try:
                named = parse_card_name(stream)
            except GrammarError:
                stream.reset(probe)
                break
            continue
        if stream.at_word("attached"):
            # "all Equipment **attached to that creature**" (Turn to Slag). Only
            # the referents the table names are admitted: an attachment clause
            # whose object nothing can resolve would be dropped and the sweep
            # would take every Equipment on the board.
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("to"):
                matched = next(
                    (
                        (words, key)
                        for words, key in _ATTACHED_TO_REFERENTS.items()
                        if stream.accept_phrase(*words)
                    ),
                    None,
                )
                if matched is not None:
                    attached_to = matched[1]
                    continue
            stream.reset(probe)
            break
        if stream.at_word("of"):
            # "sacrifices a creature **of their choice** with flying" (Run
            # Afoul) — who picks, printed between the head noun and the rest of
            # the restrictions, which is why it cannot be handled by the verb's
            # production: consuming the phrase there would strand "with flying"
            # outside the noun phrase it narrows.
            #
            # Only "their" is read. "of your choice" would be a different card —
            # the *effect's* controller choosing what someone else sacrifices —
            # and no production wants that reading by accident.
            probe = stream.mark()
            stream.advance()
            if stream.accept_phrase("their", "choice"):
                their_choice = True
                continue
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
        subtype_match=subtype_match,
        supertypes=tuple(supertypes),
        subtypes=tuple(subtypes),
        colors=tuple(colors),
        excluded_colors=tuple(excluded_colors),
        excluded_types=tuple(excluded_types),
        excluded_subtypes=tuple(excluded_subtypes),
        with_keywords=tuple(with_keywords),
        without_keywords=tuple(without_keywords),
        not_ability_targeted_by_same_name=not_ability_targeted_by_same_name,
        created_with_source=created_with_source,
        controller=controller,
        owner=owned_by,
        tapped=tapped,
        attacking=attacking,
        blocking=blocking,
        any_states=any_states,
        blocking_source=blocking_source,
        blocked=blocked,
        power=power,
        toughness=toughness,
        mana_value=mana_value,
        zone=zone,
        zone_owner=zone_owner,
        is_card=is_card,
        with_plus1_counter=with_plus1_counter,
        nontoken=nontoken,
        token_only=token_only,
        their_choice=their_choice,
        named=named,
        other_than_source=other_than_source,
        is_source=is_source,
        is_enchanted=is_enchanted,
        attached_to=attached_to,
        in_combat_with_source=in_combat_with_source,
        dealt_damage_to_source_this_turn=dealt_damage_to_source_this_turn,
    )


__all__ = [
    "accept_source_reference", "parse_card_name", "parse_object_filter",
]


# Words that cannot be part of a card's name here because they start the next
# clause of the printed template. A name scan running past one of them would
# swallow "and/or a card named Igneous Cur" into the first name and report
# Alpine Houndmaster as a card that finds one card — so the scan stops, and the
# production then refuses the line at "put".
#
# The verbs are stops because a *subject* can carry a name too: "Creatures you
# control named Kobolds of Kher Keep get +2/+2" (Rohgahh of Kher Keep) ends the
# name where the sentence's verb begins, and without the stop the scan swallowed
# "get +2/+2" and the statement parser found no verb at all. No card in the pool
# has any of these words in its name (checked against every set file), so the
# stop can only end a scan the verb was never part of.
_NAME_STOPS = ("reveal", "put", "then", "and", "or", "in", "get", "gets", "has", "have")


def parse_card_name(stream: TokenStream) -> str:
    """The card name after ``named``, wherever a noun phrase carries one.

    Read token by token rather than as one word, because a legendary name
    carries the same punctuation the sentence does — "Chandra, Flame's
    Catalyst, reveal it," holds two commas and only the second ends the name. A
    comma is taken as part of the name only when a name word follows it, and
    the rendered text is compared through ``search_filters.name_key``, which
    ignores punctuation and case on both sides.
    """
    start = stream.mark()
    while not stream.exhausted:
        if stream.at_punct(".") or stream.at_word(*_NAME_STOPS):
            break
        if stream.at_punct(","):
            mark = stream.mark()
            stream.advance()
            if stream.exhausted or stream.at_punct(".") or stream.at_word(*_NAME_STOPS):
                stream.reset(mark)
                break
            continue
        stream.advance()
    if stream.mark() == start:
        raise stream.error("expected the name the search is for")
    return render(stream.tokens[start:stream.mark()])
