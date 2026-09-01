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

from dataclasses import dataclass, field

from . import ast
from .amounts import parse_amount, parse_pt_pair
from .errors import GrammarError
from .lexer import PT, SELF, WORD
from .names import parse_card_name
from .stream import TokenStream
from .abilities import _accept_ability_noun, _accept_ability_source
from .postmodifiers import _parse_postmodifiers
from .amounts import parse_comparison  # re-exported: a comparison bounds an amount
from .readers import _SELF_NOUNS, accept_source_reference
from .vocabulary import GENERIC_NOUNS as _GENERIC_NOUNS
from .vocabulary import singular as _singular
from .vocabulary import (
    ALL_SUBTYPES,
    CARD_TYPES,
    COLOR_WORDS,
    CREATURE_TYPES,
    KEYWORD_INDEX,
    SUBTYPE_INDEX,
    SUPERTYPES,
    TYPE_LINE_SUPERTYPES,
    match_longest,
)

# Head nouns that are not card types but name a set of objects. "target" is one
# of them: Fireball's "among any number of targets" uses it as a bare noun.



_STATE_ADJECTIVES = {
    "tapped": ("tapped", True),
    "untapped": ("tapped", False),
    "attacking": ("attacking", True),
    "blocking": ("blocking", True),
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








@dataclass
class _FilterDraft:
    """The half-built filter a noun phrase accumulates, one field per
    restriction the phrase can print.

    Mutable, and a mirror of the frozen `ast.ObjectFilter` it becomes. It
    exists because `parse_object_filter` reads a phrase in sections — a head
    noun, then leading adjectives, then trailing postmodifiers — and each
    section may set any of them. Passing forty-seven locals between those
    sections is what kept them in one 795-line function; passing one draft
    is what lets the postmodifiers live in their own module.

    No `build()` here on purpose: the sole caller constructs the
    `ObjectFilter` itself, because several fields are massaged on the way
    out (tuples from lists, a zone dropped when it is the default) and a
    builder would be a second place that knows those rules.
    """

    card_types: list[str] = field(default_factory=list)
    supertypes: list[str] = field(default_factory=list)
    subtypes: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    excluded_colors: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    excluded_subtypes: list[str] = field(default_factory=list)
    excluded_supertypes: list[str] = field(default_factory=list)
    with_keywords: list[str] = field(default_factory=list)
    without_keywords: list[str] = field(default_factory=list)
    controller: str | None = None
    owned_by: str | None = None
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    any_states: tuple[str, ...] = field(default_factory=tuple)
    blocking_source: bool = False
    blocking_target: ast.ObjectFilter | None = None
    blocking_bound_target: bool = False
    blocked_by_bound_object: bool = False
    in_combat_with_bound_object: bool = False
    blocked_by_target_object: ast.ObjectFilter | None = None
    blocked_by_source: bool = False
    banded_with_source: bool = False
    attacking_you: bool = False
    power: ast.Comparison | None = None
    mana_value: ast.Comparison | None = None
    toughness: ast.Comparison | None = None
    other_than_source: bool = False
    is_source: bool = False
    is_enchanted: bool = False
    not_enchanted: bool = False
    is_card: bool = False
    with_plus1_counter: bool = False
    nontoken: bool = False
    # "permanents **of the chosen color**" (Psychic Allergy) — see
    # ``ast.ObjectFilter.chosen_color``.
    chosen_color: bool = False
    # "…that didn't attack this turn" / "…that couldn't attack" — see
    # ``ast.ObjectFilter``.
    attacked_this_turn: bool | None = None
    could_attack_this_turn: bool | None = None
    # "…except for creatures the player hasn't controlled continuously since
    # the beginning of the turn" (Total War) — see ``ast.ObjectFilter``.
    controlled_since_turn_start: bool | None = None
    token_only: bool = False
    their_choice: bool = False
    chosen_by_opponent: bool = False
    named: str | None = None
    attached_to: str | None = None
    attached_to_filter: ast.ObjectFilter | None = None
    of_bound_type: bool = False
    # Five relative narrowings the postmodifier scan writes. Declared here like
    # every other field rather than defaulted onto the instance mid-parse, which
    # is where they used to live: two conventions for "a field of the draft" is
    # one convention too many, and only a declared field can be checked against
    # what `_build_object_filter` copies.
    not_ability_targeted_by_same_name: bool = False
    created_with_source: bool = False
    in_combat_with_source: bool = False
    was_dealt_damage_this_turn: bool = False
    dealt_damage_to_source_this_turn: bool = False
    zone: str = "battlefield"
    zone_owner: ast.PlayerRef | None = None
    saw_head: bool = False
    type_match: str = "any"
    subtype_match: str = "any"
    any_classes: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    targets_object: ast.ObjectFilter | None = None
    target_count: int | None = None


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
    d.ability_kinds = _accept_ability_noun(stream)
    if d.ability_kinds:
        return ast.ObjectFilter(
            zone="stack",
            ability_kinds=d.ability_kinds,
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
            while stream.at_word("or") and stream.peek_word(1) in COLOR_WORDS:
                stream.advance()
                d.colors.append(COLOR_WORDS[str(stream.peek_word())])
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
                if d.type_match == "all":
                    # "artifact creature or Aura" — a conjunction and a union in
                    # one phrase. No card prints it and one field cannot hold
                    # both readings, so it refuses rather than picking one.
                    raise stream.error(
                        "a class union cannot also be a conjunction of types"
                    )
                d.any_classes = tuple(
                    [("card_type", name) for name in d.card_types] + cross_axis
                )
                d.card_types = []
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

        # "any number of **tokens** created with this creature" (Tetravus). Not
        # a card type and not a generic noun: CR 111.1 makes "token" a fact
        # about the object, so it is a restriction the same way "nontoken" is
        # one, and it must not fall through to a head noun that restricts
        # nothing.
        if word in ("token", "tokens"):
            d.token_only = True
            stream.advance()
            d.saw_head = True
            break

        if singular in _GENERIC_NOUNS:
            d.is_card = singular == "card"
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
                stream.advance()
            d.saw_head = True
            break

        break

    if not d.saw_head and not allow_bare:
        raise stream.error("expected an object noun")

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


def _build_object_filter(d: "_FilterDraft") -> ast.ObjectFilter:
    """*d* as the frozen filter it becomes.

    A free function rather than a method on the draft, and rather than the
    inline expression it used to be: the mirror is hand-written, so a field the
    postmodifier parsers set and this does not copy is **silently dropped** — a
    draft is an ordinary dataclass, so the assignment succeeds, the phrase
    parses, and the restriction vanishes. "target creature it's blocking" was
    written that way and dropped its whole relation.

    Naming it is what lets `tests/engine/test_grammar_parser.py` build an empty
    draft and check that every declared field arrives, which no reading of an
    inline expression could do.
    """
    return ast.ObjectFilter(
        card_types=tuple(d.card_types),
        type_match=d.type_match,
        subtype_match=d.subtype_match,
        supertypes=tuple(d.supertypes),
        subtypes=tuple(d.subtypes),
        colors=tuple(d.colors),
        excluded_colors=tuple(d.excluded_colors),
        excluded_types=tuple(d.excluded_types),
        excluded_subtypes=tuple(d.excluded_subtypes),
        excluded_supertypes=tuple(d.excluded_supertypes),
        with_keywords=tuple(d.with_keywords),
        without_keywords=tuple(d.without_keywords),
        not_ability_targeted_by_same_name=d.not_ability_targeted_by_same_name,
        any_classes=d.any_classes,
        targets_object=d.targets_object,
        target_count=d.target_count,
        created_with_source=d.created_with_source,
        controller=d.controller,
        owner=d.owned_by,
        tapped=d.tapped,
        attacking=d.attacking,
        blocking=d.blocking,
        any_states=d.any_states,
        blocking_source=d.blocking_source,
        blocking_target=d.blocking_target,
        blocking_bound_target=d.blocking_bound_target,
        blocked_by_bound_object=d.blocked_by_bound_object,
        in_combat_with_bound_object=d.in_combat_with_bound_object,
        blocked_by_target_object=d.blocked_by_target_object,
        blocked_by_source=d.blocked_by_source,
        banded_with_source=d.banded_with_source,
        attacking_you=d.attacking_you,
        blocked=d.blocked,
        power=d.power,
        toughness=d.toughness,
        mana_value=d.mana_value,
        zone=d.zone,
        zone_owner=d.zone_owner,
        is_card=d.is_card,
        with_plus1_counter=d.with_plus1_counter,
        nontoken=d.nontoken,
        chosen_color=d.chosen_color,
        attacked_this_turn=d.attacked_this_turn,
        could_attack_this_turn=d.could_attack_this_turn,
        controlled_since_turn_start=d.controlled_since_turn_start,
        token_only=d.token_only,
        their_choice=d.their_choice,
        named=d.named,
        other_than_source=d.other_than_source,
        is_source=d.is_source,
        is_enchanted=d.is_enchanted,
        not_enchanted=d.not_enchanted,
        attached_to=d.attached_to,
        attached_to_filter=d.attached_to_filter,
        of_bound_type=d.of_bound_type,
        in_combat_with_source=d.in_combat_with_source,
        was_dealt_damage_this_turn=d.was_dealt_damage_this_turn,
        chosen_by_opponent=d.chosen_by_opponent,
        dealt_damage_to_source_this_turn=d.dealt_damage_to_source_this_turn,
    )


__all__ = [
    "accept_source_reference", "parse_card_name", "parse_comparison",
    "parse_object_filter",
]
