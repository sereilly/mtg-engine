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
from .amounts import parse_pt_pair
from .lexer import PT
from .names import parse_card_name
from .stream import TokenStream
from .abilities import _accept_ability_noun, _accept_ability_source
from .postmodifiers import _parse_postmodifiers
from .bounds import parse_comparison  # re-exported: a comparison bounds an amount
# Re-exported: the draft and its builder left for `filter_draft` at the size
# guard, and every caller — `_parse_postmodifiers`' annotation, the mirror guard
# in `tests/engine/test_grammar_parser.py` — keeps the import it had.
from .filter_draft import _FilterDraft, _build_object_filter
from .readers import _SELF_NOUNS, accept_source_reference
from .vocabulary import GENERIC_NOUNS as _GENERIC_NOUNS
from .vocabulary import singular as _singular
from .vocabulary import (ALL_SUBTYPES, CARD_TYPES, COLOR_WORDS, CREATURE_TYPES,
                         SUBTYPE_INDEX, SUPERTYPES, TYPE_LINE_SUPERTYPES, match_longest)

# Head nouns that are not card types but name a set of objects. "target" is one
# of them: Fireball's "among any number of targets" uses it as a bare noun.



_STATE_ADJECTIVES = {
    "tapped": ("tapped", True),
    "untapped": ("tapped", False),
    "attacking": ("attacking", True),
    # "target **nonattacking, nonblocking** creature" (Unlikely Alliance).
    # CR 506.3/509.1g: attacking and blocking are states of the permanent, so
    # their negations are the same two axes read the other way — the pair
    # "blocked"/"unblocked" already below has exactly this shape. A word with no
    # entry here is not an adjective at all and ends the noun phrase, which is
    # how this card refused with "expected a subject".
    "nonattacking": ("attacking", False),
    "blocking": ("blocking", True),
    "nonblocking": ("blocking", False),
    "blocked": ("blocked", True),
    "unblocked": ("blocked", False),
}






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


def _color_alternative_offset(stream: TokenStream) -> int | None:
    """How many tokens ahead the next "…or <colour>" alternative's colour word
    sits, or None when there is not one there.

    English writes the same list four ways, and all four are one union:

    * ``or blue permanent`` (Nature's Wrath),
    * ``or **a** white permanent`` (Omen of Fire) — a repeated article,
    * ``**,** mountain, black permanent`` — a comma with no connector,
    * ``**, or** red permanent`` (Royal Decree) — the last item of a list,
      which carries both.

    A pure lookahead, so nothing is consumed until the caller has committed:
    the separator is what tells this from a phrase that simply ended, and a
    half-consumed one refuses the whole line.
    """
    offset = 1 if stream.at_punct(",") else 0
    if stream.peek_word(offset) == "or":
        offset += 1
    elif offset == 0:
        # No separator at all: an adjacent colour word is an adjective on this
        # noun phrase, not another member of a union.
        return None
    if stream.peek_word(offset) in ("a", "an"):
        offset += 1
    return offset if stream.peek_word(offset) in COLOR_WORDS else None


def _negated_color_type(
    stream: TokenStream,
) -> "tuple[tuple[str, ...], str, int] | None":
    """``non<colour> <card type>`` at the cursor: the excluded colours, the
    card type, and how many tokens it spans — or None, cursor unmoved.

    "target land or **nonblack creature**" (Befoul). One member of a type union
    carrying its own colour negation, which the union's flat ``card_types``
    list cannot express and the filter's ``excluded_colors`` must not be asked
    to: that key is ANDed across the whole phrase, so the exclusion would reach
    the *land* half too and Befoul would stop destroying a Swamp its black
    opponent controls.

    A pure lookahead, like :func:`_color_alternative_offset` above and for its
    reason: the caller has already consumed the separator's alternatives and a
    half-consumed member refuses the whole line.

    More than one negation is read ("nonblack nonartifact creature" would be
    two), because the loop that reads them on an ordinary noun phrase reads any
    number and a member of a union is the same phrase.
    """
    excluded: list[str] = []
    offset = 0
    while True:
        word = stream.peek_word(offset)
        if word is None or not word.startswith("non") or len(word) <= 3:
            break
        body = word[3:].lstrip("-")
        if body not in COLOR_WORDS:
            break
        excluded.append(COLOR_WORDS[body])
        offset += 1
    if not excluded:
        return None
    head = stream.peek_word(offset)
    if head is None or _singular(head) not in CARD_TYPES:
        return None
    return tuple(excluded), _singular(head), offset + 1


def _match_subtype_or_plural(stream: TokenStream, start: int = 0) -> tuple[str, int] | None:
    """:func:`_match_subtype`, and the plural spelling of one.

    "Destroy all Islands", "exile all Sand **Warriors**" — the catalog stores
    singulars (except where the singular is itself plural, Plains), so a printed
    plural has to be singularized before it can be looked up. Only a one-token
    match is taken from the singularized probe: singularizing the *first* word
    of a multi-word run says nothing about the words behind it.
    """
    matched = _match_subtype(stream, start)
    if matched is not None:
        return matched
    words = stream.words_from(start)
    if not words:
        return None
    singular = _singular(words[0])
    if singular == words[0]:
        return None
    probe = match_longest((singular,) + words[1:], 0, SUBTYPE_INDEX)
    return probe if probe is not None and probe[1] == 1 else None


def _accept_card_noun(stream: TokenStream) -> bool:
    """Consume a "card"/"cards" head noun trailing a type word.

    "Creature" names a permanent; "creature card" names a card, which is what a
    graveyard or a hand holds (CR 400.1). Leaving the word unconsumed used to
    fail the whole line on the full-consumption invariant; consuming it without
    recording it would be worse, so the caller stores the answer on the filter.
    """
    return stream.accept_word("card", "cards")


def parse_object_filter(stream: TokenStream, *, allow_bare: bool = False) -> ast.ObjectFilter:
    """Parse the noun phrase describing a set of objects.

    *allow_bare* permits a phrase with no head noun (used by "each creature
    without flying"-style sweeps where the type word doubles as the head).
    """
    d = _FilterDraft()

    # --- an ability on the stack ----------------------------------------
    # "activated or triggered ability" / "activated ability" / "triggered
    # ability" (Sublime Epiphany). Read first and whole, because none of the
    # machinery below applies: an ability on the stack has no card, no type
    # line and no permanent behind it (CR 113.7a), so every adjective the loop
    # further down collects would be a question with no object to ask it of.
    # A **local**, and the first thing the slots guard on the draft found: this
    # used to be written as `d.ability_kinds`, a field `_FilterDraft` does not
    # declare and `_build_object_filter` therefore never copies. It happened to
    # work — the branch reads it back two lines later and returns a filter it
    # builds itself, so nothing ever went through the builder — but it is the
    # exact spelling that loses a narrowing anywhere else in this file, and a
    # value that never reaches the draft's builder is not a field of the draft.
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
            d.is_source = True
            d.saw_head = True
            if _singular(noun) in CARD_TYPES:
                d.card_types.append(_singular(noun))
        else:
            stream.reset(probe)

    if not d.saw_head and stream.accept_word("enchanted"):
        noun = stream.peek_word()
        if noun is None:
            raise stream.error("expected a noun after 'enchanted'")
        stream.advance()
        d.is_enchanted = True
        d.saw_head = True
        if _singular(noun) in CARD_TYPES:
            d.card_types.append(_singular(noun))

    # --- adjectives ------------------------------------------------------
    while not d.saw_head:
        # Adjectives may be comma-separated: "target nonartifact, nonblack
        # creature" (Terror). The comma carries no meaning of its own, but it
        # must be consumed or full-token consumption fails the whole line.
        if stream.at_punct(",") and stream.peek_word(1) is not None:
            stream.advance()

        # "target **1/1** creature" (Pendelhaven) — a printed power/toughness
        # pair standing as an adjective (CR 208.1). It says exactly what the
        # postmodifier "with power 1 and toughness 1" says, so it sets the same
        # two comparison fields rather than minting a third representation of
        # the same restriction. Read here rather than at the head, because the
        # lexer gives it a `pt` token and `peek_word` is None for one — the
        # loop below would `break` and the whole line would refuse, which is
        # how Pendelhaven's pump refused with "expected a subject".
        #
        # Signed pairs are not adjectives: "+1/+2" is the *amount* of a pump
        # and belongs to the verb, so only an unsigned pair is taken.
        if stream.at_kind(PT):
            token = stream.peek()
            if token is not None and token.text[:1] not in ("+", "-", "−"):
                power, _, toughness, _ = parse_pt_pair(token.text)
                stream.advance()
                d.power = ast.Comparison("eq", power)
                d.toughness = ast.Comparison("eq", toughness)
                continue

        word = stream.peek_word()
        if word is None:
            break

        if word.startswith("non") and len(word) > 3:
            body = word[3:].lstrip("-")
            if body in COLOR_WORDS:
                d.excluded_colors.append(COLOR_WORDS[body])
                stream.advance()
                continue
            if body in CARD_TYPES:
                d.excluded_types.append(body)
                stream.advance()
                continue
            if body in ALL_SUBTYPES:
                d.excluded_subtypes.append(body)
                stream.advance()
                continue
            # "**nonsnow** land" (Hallowed Ground), "**nonbasic** land". A
            # negated *supertype* (CR 205.4), which no layer computes — the
            # matcher reads it off the effective type line, exactly as it reads
            # the positive `supertypes` key. Its own field for the reason the
            # excluded type and subtype above have theirs: three different
            # readers answer them, and folding a supertype into either would ask
            # `has_type` a question the type system does not answer.
            if body in TYPE_LINE_SUPERTYPES:
                d.excluded_supertypes.append(body)
                stream.advance()
                continue
            # "nontoken" (Lich, Gadrak, Chrome Replicator). CR 111.1: a token is
            # not a card and has no card type of its own, so it is neither an
            # excluded type nor an excluded subtype — it is its own restriction,
            # read off the permanent the same way the forced-sacrifice prompt has
            # always read it.
            if body == "token":
                d.nontoken = True
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
            d.other_than_source = True
            stream.advance()
            continue

        if word in COLOR_WORDS:
            # "a **green or white** creature" (Abomination) — a union of colour
            # adjectives, read as one the way "attacking or blocking" below is.
            # Taking "green" alone would end the noun phrase at "or", leaving
            # "or white creature" unconsumed and refusing the whole line, which
            # is exactly how Abomination refused.
            d.colors.append(COLOR_WORDS[word])
            stream.advance()
            while True:
                # "each **white and/or blue** creature" (Evaporate) — the same
                # union with the printed conjunction spelled out. The lexer
                # drops the slash, so it arrives as the two words "and or", and
                # it means what "or" alone means here: CR 105.2 gives an object
                # one or more colours, so "white and/or blue" names every object
                # that is either, which is what ``colors`` already describes.
                # Read inside this loop rather than as a filter of its own,
                # because taking "white" alone would end the noun phrase at
                # "and" — which is exactly how Evaporate refused.
                joined = stream.mark()
                stream.accept_word("and")
                if stream.at_word("or") and stream.peek_word(1) in COLOR_WORDS:
                    stream.advance()
                    d.colors.append(COLOR_WORDS[str(stream.peek_word())])
                    stream.advance()
                    continue
                stream.reset(joined)
                break
            # "a **black or artifact** creature" (Soldevi Adnate, Viscerid
            # Drone's snow twin one card over). The union straddles two axes —
            # CR 105 colour against CR 205.2 card type — and the head noun is
            # still to come, so this is a *conjunct*: a creature that is black
            # or is an artifact. Collected into `any_classes`, which already
            # holds exactly this shape one axis over ("instant or Aura spell"),
            # rather than into `colors` and `card_types`, which the engine ANDs
            # — that reading describes a black creature that is also an
            # artifact, a set most of these cards can never match.
            #
            # `colors` is cleared as the union takes it over: left in, the AND
            # would put the colour back as a requirement and the union would
            # only ever narrow.
            cross = stream.mark()
            if stream.at_word("or") and _singular(
                str(stream.peek_word(1) or "")
            ) in CARD_TYPES:
                alternatives: list[tuple[str, str]] = [
                    ("color", color) for color in d.colors
                ]
                while stream.at_word("or") and _singular(
                    str(stream.peek_word(1) or "")
                ) in CARD_TYPES:
                    stream.advance()
                    alternatives.append(
                        ("card_type", _singular(str(stream.peek_word())))
                    )
                    stream.advance()
                d.any_classes = tuple(alternatives)
                d.colors = []
                continue
            stream.reset(cross)
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
            d.any_states = tuple(states)
            continue

        if word in _STATE_ADJECTIVES:
            attribute, value = _STATE_ADJECTIVES[word]
            if attribute == "tapped":
                d.tapped = value
            elif attribute == "attacking":
                d.attacking = value
            elif attribute == "blocking":
                d.blocking = value
            else:
                d.blocked = value
            stream.advance()
            continue

        # "any number of **tokens** created with this creature" (Tetravus),
        # "Sacrifice a **token** named Wood" (Jungle Patrol). Not a card type
        # and not a generic noun: CR 111.1 makes "token" a fact about the
        # object, so it is a restriction the same way "nontoken" is one, and it
        # must not fall through to a head noun that restricts nothing.
        #
        # **Above the supertype branch, because Scryfall's supertype list
        # contains "Token".** That list is fetched data (a token's printed line
        # really does read "Token Creature — Wall"), and CR 205.4a's supertypes
        # are basic, legendary, ongoing, snow and world — so the word arriving
        # here as a supertype was the data disagreeing with the rules. It cost
        # Jungle Patrol its whole second ability: the singular "token" was eaten
        # as an adjective, the phrase then had no head noun, and the line
        # refused with "expected what to sacrifice as a cost". Only the plural
        # reached this branch, which is why "any number of tokens" worked and
        # "a token" did not.
        if word in ("token", "tokens"):
            d.token_only = True
            stream.advance()
            # "a token **creature**" prints the fact as an adjective in front of
            # a head noun, where "sacrifice a token" prints it *as* the head.
            # Both are read: a following noun keeps the loop going, so the head
            # is still the type word, and nothing else changes.
            following = stream.peek_word()
            if following is not None and (
                _singular(following) in CARD_TYPES
                or _singular(following) in _GENERIC_NOUNS
                or _match_subtype(stream, 0) is not None
            ):
                continue
            d.saw_head = True
            break

        if word in SUPERTYPES:
            d.supertypes.append(word)
            stream.advance()
            continue

        # A card type or subtype word ends the adjective run and becomes the
        # head noun — but "artifact creature" is two types, so keep going
        # while consecutive type words appear.
        singular = _singular(word)
        if singular in CARD_TYPES:
            d.card_types.append(singular)
            stream.advance()
            # Collect further type words: "artifact creature" stacks two types,
            # "artifact or enchantment" and "artifact, creature, or land" list
            # alternatives. All three are type unions as far as matching goes,
            # so one loop covers them — the separators are optional.
            cross_axis: list[tuple[str, str]] = []
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
                # "target land or **nonblack creature**" (Befoul). A union
                # member carrying its own narrowing: the alternatives straddle
                # nothing new — both are card types — but one of them is
                # further restricted, which `card_types` cannot say. Collected
                # into `any_classes` beside the cross-axis alternatives below,
                # as a card type *with* the colours it excludes, because the
                # union is over whole noun phrases and `excluded_colors` on the
                # filter would exclude black from **both** halves: Befoul would
                # stop destroying a black opponent's Swamp.
                #
                # Only after a separator, for the reason the subtype branch
                # below states: an adjacent adjective belongs to the phrase
                # this loop is already reading.
                negated = _negated_color_type(stream) if separated else None
                if negated is not None:
                    excluded, card_type, width = negated
                    cross_axis.extend(
                        ("card_type", name) for name in d.card_types
                    )
                    cross_axis.append(("card_type", card_type, excluded))
                    d.card_types = []
                    stream.advance(width)
                    continue
                if following is not None and _singular(following) in CARD_TYPES:
                    d.card_types.append(_singular(following))
                    # No separator means juxtaposition ("artifact creature"),
                    # which names one permanent holding both types rather than
                    # either of two.
                    if not separated:
                        d.type_match = "all"
                    stream.advance()
                    continue
                # "instant or **Aura** spell" (Avoid Fate, Ring of Immortals).
                # The alternatives straddle two axes — a card type and a
                # subtype (CR 205.2 against CR 205.3) — so the union cannot be
                # collected into `card_types`, and collecting the subtype into
                # `subtypes` beside it would describe an instant that is *also*
                # an Aura, which nothing is. Only after a separator: an
                # adjacent subtype is a conjunction, and the branch below reads
                # it as one.
                if separated:
                    alternative = _match_subtype(stream, 0)
                    if alternative is not None:
                        cross_axis.append(("subtype", alternative[0]))
                        stream.advance(alternative[1])
                        continue
                stream.reset(probe)
                break
            if cross_axis:
                # The alternatives already collected the head types where a
                # negated member was read (it empties ``card_types`` as it
                # goes), so this only has to add them when the cross-axis
                # branches below did.
                if d.card_types:
                    cross_axis = [
                        ("card_type", name) for name in d.card_types
                    ] + cross_axis
                    d.card_types = []
                if d.type_match == "all":
                    # "artifact creature or Aura" — a conjunction and a union in
                    # one phrase. No card prints it and one field cannot hold
                    # both readings, so it refuses rather than picking one.
                    raise stream.error(
                        "a class union cannot also be a conjunction of types"
                    )
                d.any_classes = tuple(cross_axis)
            d.is_card = _accept_card_noun(stream)
            # "target instant or sorcery **spell**" (Miscast): the head noun
            # after a type union may be "spell", naming an object on the stack
            # rather than a permanent of those types. Recorded as the zone so
            # a lowering that resolves battlefield objects refuses the line
            # instead of reading it as "target instant or sorcery".
            if not d.is_card and stream.accept_word("spell", "spells"):
                d.zone = "stack"
            d.saw_head = True
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
            d.subtypes.append(name)
            stream.advance(consumed)
            # "Djinn or Efreet", and the comma-separated form a longer list is
            # printed in: "Bird, Cat, Dog, Goat, Ox, or Snake" (Animal
            # Sanctuary). Both spellings are one union — English punctuates a
            # list of six differently from a list of two, and the card means the
            # same thing either way.
            #
            # "the number of **Soldiers and Warriors** you control" (Aysen
            # Crusader) is the third spelling and the same union: a Soldier is
            # in the set and a Warrior is in the set, and one creature that is
            # both is in it once. English writes a union of two sets this way as
            # readily as with "or", which is why the branch above this one has
            # read "artifact **and** enchantment" as a type union since it was
            # written — this is the same word doing the same job one axis over
            # (CR 205.2 against CR 205.3), and reading it as a conjunction would
            # make the set every creature that is a Soldier *and* a Warrior,
            # which on Aysen Crusader's own board is almost always empty.
            #
            # A comma or connector is only consumed when a subtype follows it,
            # so a phrase that ends its noun and goes on ("destroy target Wall,
            # then draw a card" / "destroy target Wall and draw a card") keeps
            # the word for whatever reads the rest.
            while stream.at_word("or", "and") or stream.at_punct(","):
                probe = stream.mark()
                stream.advance()
                # "…, or Snake" — the final item carries both, and the comma
                # above already moved past its own token.
                stream.accept_word("or", "and")
                # The plural spelling too ("Soldiers and **Warriors**"), through
                # the same reader the head noun used. `match_longest` alone
                # matches singulars, so a printed plural after the connector was
                # a non-match and took the whole union with it — the head of the
                # list is nearly always plural where a count is being taken, so
                # the tail almost always is as well.
                alternative = _match_subtype_or_plural(stream)
                if alternative is None:
                    stream.reset(probe)
                    break
                d.subtypes.append(alternative[0])
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
            if len(d.subtypes) == 1:
                while True:
                    # The plural spelling too: "all Sand **Warriors**" prints
                    # the conjunction's last word plural, exactly as the
                    # single-subtype branch above does, and a reader that knew
                    # only the singular stopped after "Sand" — narrowing a
                    # board sweep to every Sand, Warriors included or not.
                    adjacent = _match_subtype_or_plural(stream)
                    if adjacent is None:
                        break
                    d.subtypes.append(adjacent[0])
                    stream.advance(adjacent[1])
                    d.subtype_match = "all"
            # "an **Island or blue** permanent" (Nature's Wrath), "a
            # **Plains or a white** permanent" (Omen of Fire). The mirror of
            # the colour branch's cross-axis probe above, one axis over: the
            # union straddles CR 205.3 subtypes against CR 105 colours, and the
            # head noun ("permanent") is still to come. Collected into
            # `any_classes` for that branch's reason — `subtypes` plus `colors`
            # is ANDed by the matcher and would describe a *blue Island*, which
            # is not a set either card can ever mean.
            #
            # The second article is optional because English writes the same
            # union both ways: Nature's Wrath prints "an Island or blue
            # permanent" and Omen of Fire "a Plains or **a** white permanent",
            # one clause apart in the same block of rules text.
            cross_colors = stream.mark()
            if (
                d.subtype_match != "all"
                and _color_alternative_offset(stream) is not None
            ):
                alternatives: list[tuple[str, str]] = [
                    ("subtype", name) for name in d.subtypes
                ]
                # "a **Swamp, Mountain, black permanent, or red permanent**"
                # (Royal Decree) repeats the head noun on each coloured member;
                # "an **Island or blue permanent**" (Nature's Wrath) prints it
                # once at the end. Both are read here — a repeated head is the
                # phrase's head all the same, so seeing one ends the noun phrase
                # instead of looping back for another.
                saw_head_noun = False
                while _color_alternative_offset(stream) is not None:
                    stream.accept_punct(",")
                    stream.accept_word("or")
                    stream.accept_word("a", "an")
                    alternatives.append(
                        ("color", COLOR_WORDS[str(stream.peek_word())])
                    )
                    stream.advance()
                    if stream.accept_word("permanent", "permanents"):
                        saw_head_noun = True
                d.any_classes = tuple(alternatives)
                d.subtypes = []
                if saw_head_noun:
                    d.saw_head = True
                    break
                continue
            stream.reset(cross_colors)
            following = stream.peek_word()
            if following is not None and _singular(following) in CARD_TYPES:
                continue
            # "a **Goblin permanent** card" (Goblin Wizard). A *generic* head
            # noun after a subtype, read by looping back to the branch that
            # already knows how to read one rather than by a second copy of it
            # here — which is also what keeps "permanent card" a card and not a
            # permanent.
            #
            # Two of the generic nouns and not the whole set. "Goblin **spell**"
            # names an object on the stack, and the branch below records that as
            # ``zone`` only for a *type* union — reaching it from here would read
            # a spell as a battlefield permanent, which is the widening this
            # detour has to be narrow to avoid. It keeps refusing until a card
            # prints one.
            if following is not None and _singular(following) in ("permanent", "card"):
                continue
            # "a **Caribou token**" (Caribou Range's sacrifice cost). CR 111.1's
            # fact about the object, printed *after* the subtype rather than in
            # front of a bare noun — the branch below reads "tokens created with
            # this creature" (Tetravus), where the word is the head. Here it is a
            # narrowing on a head already read, so it is consumed here: left
            # unread it is one unconsumed word, which refuses the whole line.
            if following in ("token", "tokens"):
                d.token_only = True
                stream.advance()
            d.is_card = _accept_card_noun(stream)
            d.saw_head = True
            break

        if singular in _GENERIC_NOUNS:
            d.is_card = singular == "card"
            # The **bare** head noun "spell" names an object on the stack
            # (CR 111.1 / CR 608), and recording that is what keeps it from
            # meaning the same as "permanent". Without it the two produced
            # byte-identical filters, so `{T}: Target spell becomes colorless.`
            # (Ersatz Gnomes) derived the same picker as "target spell **or**
            # permanent" (Chaoslace) and could be aimed at a permanent the card
            # does not allow — CR 601.2c makes that an illegal announcement.
            #
            # Set here rather than only after a type union (the "instant or
            # sorcery **spell**" branch above), because the zone is a fact about
            # the head noun and not about what narrows it.
            bare_spell = singular == "spell"
            stream.advance()
            # "permanent card(s)" (Ugin, the Spirit Dragon's −10): a card whose
            # type would make it a permanent. The trailing noun is recorded the
            # same way a type word's is — see _accept_card_noun.
            if not d.is_card and _accept_card_noun(stream):
                d.is_card = True
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
                # "target spell **or permanent**" is not a spell: the union
                # widens the phrase back to either zone, so the narrowing this
                # branch would otherwise record has to be withdrawn. Only a
                # union with another *spell* word leaves it standing.
                if _singular(following) != "spell":
                    bare_spell = False
                stream.advance()
            if bare_spell:
                d.zone = "stack"
            d.saw_head = True
            break

        break

    if not d.saw_head and not allow_bare:
        raise stream.error("expected an object noun")

    # "**White creatures and blue creatures** can't block." (Magistrate's Veto.)
    # The colour union with the head noun printed twice — one set, spelled the
    # long way. "White or blue creatures" is the short spelling and the
    # adjective loop above has read it since Abomination; this is the same
    # narrowing, and reading it as two noun phrases would leave "and blue
    # creatures" unconsumed and refuse the line.
    #
    # Read **before** the postmodifiers, which is what makes "white creatures
    # and blue creatures **you control**" apply the seat to the whole union
    # rather than to its second half alone — the printed reading.
    #
    # Gated hard, because "and" between two noun phrases usually joins two
    # different sets and folding those would name a set neither half prints:
    # the first half must already have named a colour and exactly one card
    # type with no subtype, and the second must be colour words and the **same
    # plural head noun** and nothing else. "Destroy all creatures and all
    # lands" fails on the article, "…and blue enchantments" on the head noun,
    # and "…creatures you control and blue creatures" on the postmodifier that
    # has not been read yet.
    if d.card_types and not d.subtypes and d.colors:
        union = stream.mark()
        if stream.accept_word("and"):
            more: list[str] = []
            while stream.peek_word() in COLOR_WORDS:
                more.append(COLOR_WORDS[str(stream.peek_word())])
                stream.advance()
                if stream.at_word("or") and stream.peek_word(1) in COLOR_WORDS:
                    stream.advance()
                    continue
                break
            tail = stream.peek_word()
            if (
                more
                and tail is not None
                and tail != _singular(tail)
                and _singular(tail) == d.card_types[-1]
            ):
                stream.advance()
                for colour in more:
                    if colour not in d.colors:
                        d.colors.append(colour)
            else:
                stream.reset(union)

    _parse_postmodifiers(stream, d, parse_object_filter)


    # A creature subtype implies the creature type: "destroy target Wall" means
    # a creature. Land/artifact subtypes ("destroy all Plains") must not, so the
    # implication is keyed on the vocabulary the subtype came from.
    # It survives a *generic* head noun too: "a Goblin **permanent** card"
    # (Goblin Wizard) is still a creature card, because CR 205.3 puts a creature
    # type only on a creature — the printed "permanent" is future-proofing, not
    # a wider set.
    if d.subtypes and not d.card_types and all(s in CREATURE_TYPES for s in d.subtypes):
        d.card_types.append("creature")

    return _build_object_filter(d)


__all__ = [
    "accept_source_reference", "parse_card_name", "parse_comparison",
    "parse_object_filter",
]
