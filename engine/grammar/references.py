"""What a printed noun phrase *points at*: a player, or a quantified set of objects.

`nouns.py` answers the other half — what those objects have to be — and this
module reads it. Splitting on that line rather than anywhere else is the CR's
own: CR 109 is what an object is, CR 115 is how a spell chooses one, and a
player (CR 102) is not an object at all. The three player forms, the quantifier
table and the recipient union are the productions that need the second question
and not the first.

Everything a caller used to import from `nouns` still exists; the names simply
moved, so a production that reads "target creature" imports the quantifier from
here and the filter from there.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .lexer import NUMBER, WORD
from .nouns import (
    _GENERIC_NOUNS,
    _singular,
    parse_object_filter,
)
from .stream import TokenStream
from .vocabulary import ALL_SUBTYPES, CARD_TYPES, NUMBER_WORDS


def parse_player_ref(stream: TokenStream) -> ast.PlayerRef | None:
    """Parse a player reference at the cursor, or return None."""
    mark = stream.mark()

    if stream.accept_word("you"):
        return ast.PlayerRef("you")

    if stream.accept_phrase("each", "player"):
        return ast.PlayerRef("each_player")
    if stream.accept_phrase("each", "opponent"):
        return ast.PlayerRef("each_opponent")
    # "…deals 2 damage to **each other player**" (Syphon Soul). CR 102.2/102.3:
    # a player's opponents are every player not on their team, and this engine
    # has no teams (the team rules are `EXCLUDED` in `rules_progress.py`
    # because the mechanic does not exist here) — so "each other player" and
    # "each opponent" name the same seats, in a duel and in a free-for-all
    # alike. An alias rather than a fourth referent, the way "they" is an alias
    # for "that player" below: a second kind would be a second answer that
    # every recipient table, picker and handler would then have to learn.
    if stream.accept_phrase("each", "other", "player"):
        return ast.PlayerRef("each_opponent")
    # "**Any player** may sacrifice two lands …" (Worms of the Earth.) CR 101.4:
    # an offer made to "any player" is made to each of them in turn, which is
    # the set "each player" already names and the set `handlers/control_flow`
    # already arms one prompt per seat of. An alias for the reason "each other
    # player" above is one — a kind of its own would be one card's private
    # address for a set the engine has (idiom 19), and every table, picker and
    # handler would have to learn it.
    if stream.accept_phrase("any", "player"):
        return ast.PlayerRef("each_player")
    if stream.accept_phrase("target", "player"):
        return ast.PlayerRef("target_player")
    if stream.accept_phrase("target", "opponent"):
        return ast.PlayerRef("target_opponent")
    if stream.accept_phrase("that", "player"):
        # "…**that player or that permanent's controller** may pay {R}{R}."
        # (Chain Lightning.) One referent printed as a disjunction, because the
        # sentence in front of it named "any target" (CR 115.4) and the seat it
        # landed on is a player in one case and a permanent's controller in the
        # other. Both arms are the seat the previous step already recorded,
        # which is exactly what `that_player` means to every consumer
        # downstream — so this is a *spelling*, the way "they" is, and a second
        # kind would be a second answer to a question with one.
        #
        # Consumed only when the second arm really is that same referent; any
        # other "or" is left for the productions that read a disjunction of
        # different things.
        mark_or = stream.mark()
        if stream.accept_word("or"):
            other = parse_player_ref(stream)
            if other is not None and other.kind == "that_player":
                return ast.PlayerRef("that_player")
        stream.reset(mark_or)
        return ast.PlayerRef("that_player")
    # "…**they** gain 1 life" (Spiritual Sanctuary). The pronoun back-refers to
    # the player the sentence has already named, which is exactly what
    # `that_player` means to every consumer downstream — so it is an alias, not
    # a fourth referent. `nouns.py` set the precedent the other way round when
    # it read "they control" as a `that_player` narrowing; the two spellings
    # disagreeing about the same word is the fork this repo closes elsewhere.
    if stream.accept_word("they"):
        return ast.PlayerRef("that_player")
    # "…**the player** discards it unless they pay …" (Wand of Ith). The
    # definite article back-refers to the player the sentence in front of this
    # one named, which is what `that_player` means downstream — an alias, like
    # "they" above, and not a fourth referent. Only the bare two words: "the
    # player who …" is a *description* of a seat and belongs to the productions
    # that read one.
    mark_the_player = stream.mark()
    if stream.accept_phrase("the", "player"):
        if stream.exhausted or not stream.at_word("who", "with", "whose"):
            return ast.PlayerRef("that_player")
    stream.reset(mark_the_player)
    if stream.accept_phrase("its", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("their", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("defending", "player"):
        return ast.PlayerRef("defending_player")
    if stream.accept_phrase("the", "chosen", "player"):
        return ast.PlayerRef("chosen_player")
    # "**An** opponent" is *not* "target opponent", and reading it as one was a
    # fork: CR 601.2c chooses nothing here, so the phrase names whichever
    # opponent the effect eventually reaches -- every one of them in turn for
    # "unless an opponent pays {2}" (Scarwood Bandits), and the seat the
    # resolution happens to carry for anything that guessed. The two spellings
    # shared a kind until Amulet of Quoz printed "**target** opponent may ante
    # the top card of their library" and needed that kind to mean a chosen seat.
    #
    # ``opponent`` is not a new referent: ``_OPPONENT_PAYERS`` and the noun
    # parser's controller narrowing ("a permanent **an opponent** controls")
    # have spelled the article's reading that way all along.
    if stream.accept_phrase("an", "opponent"):
        return ast.PlayerRef("opponent")

    # "that land's controller" / "this creature's controller" / "**the**
    # Wall's controller" (Word of Blasting) — a possessive noun phrase resolving
    # to a player. The lexer split "land's" into "land" + "'s".
    #
    # The definite article is the same referent as "that": a sentence that has
    # already named the object refers back to it either way, and English picks
    # between them by how far back it was. Reading only "that" left Word of
    # Blasting refusing a phrase it prints twice in one line.
    if stream.at_word("that", "this", "the"):
        probe = stream.mark()
        stream.advance()
        noun = stream.peek_word()
        # "…that **ability's** controller" (Ayesha Tanaka). An ability on the
        # stack is an object with a controller (CR 113.7a) but no card, so the
        # word is not in `_GENERIC_NOUNS` — that set is what a *noun phrase* may
        # head, and admitting it there would let "an ability" be parsed as a set
        # of objects the matcher cannot test.
        if noun is not None and (
            _singular(noun) in CARD_TYPES
            or _singular(noun) in _GENERIC_NOUNS
            or _singular(noun) in ALL_SUBTYPES
            or _singular(noun) == "ability"
        ):
            stream.advance()
            if stream.accept_word("'s"):
                # "that **creature's or spell's** controller" (Justice). The
                # event named *one* object — a red creature or a red spell —
                # and English prints the possessive once per noun, so the
                # alternation is two spellings of one referent rather than two
                # referents. Whichever half the event was, the seat is the same
                # one, which is why every branch below returns the same
                # ``PlayerRef``. A loop rather than a second `or` clause: a
                # third noun would be the same sentence again.
                while stream.at_word("or"):
                    alternative = stream.mark()
                    stream.advance()
                    other = stream.peek_word()
                    if other is not None and (
                        _singular(other) in CARD_TYPES
                        or _singular(other) in _GENERIC_NOUNS
                        or _singular(other) in ALL_SUBTYPES
                        or _singular(other) == "ability"
                    ):
                        stream.advance()
                        if stream.accept_word("'s"):
                            continue
                    stream.reset(alternative)
                    break
                if stream.accept_word("controller"):
                    return ast.PlayerRef("that_player")
                # "…under the control of **that creature's owner**"
                # (Reincarnation). Ownership is CR 108.3 and never changes;
                # control is CR 613 layer 2 and does, so the two words are two
                # referents and reading one as the other would put the card
                # back under whoever had stolen the creature.
                if stream.accept_word("owner"):
                    return ast.PlayerRef("owner")
        stream.reset(probe)

    stream.reset(mark)
    return None


def _at_counted_target(stream: TokenStream) -> bool:
    """Whether the cursor is at "<number> target …" — a bare count, no "up to".

    Looked ahead rather than tried-and-rewound because the number is also the
    opening of several other phrases ("two or more", "three cards"), and only
    the word after it says which this is.
    """
    word = stream.peek_word()
    token = stream.peek()
    if token is None:
        return False
    is_number = token.kind == NUMBER or word in NUMBER_WORDS or word == "x"
    return bool(is_number) and stream.peek_word(1) == "target"


def parse_target_spec(stream: TokenStream) -> ast.TargetSpec | None:
    """Parse a quantified object reference, or return None if the cursor is not
    at one."""
    mark = stream.mark()

    # CR 115.4 "any target" — creatures, players, planeswalkers, battles.
    if stream.accept_phrase("any", "target"):
        return ast.TargetSpec("any_target", targeted=True)

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
    # "X target lands": the count is the announced X rather than a printed
    # number, so it is not known until the ability is activated.
    exactly_x = False

    # Whether the word "target" is printed — recorded, not merely consumed:
    # "up to four lands" (Rewind) names no targets and is chosen on
    # resolution, where "up to two target creatures" is chosen at cast.
    targeted = False

    # "tap **any number of** untapped creatures you control" (Siege Striker).
    # Its own quantifier rather than an "up to" with a very large count: an "up
    # to" prints a maximum a picker shows and a re-check enforces, and there is
    # none here — the bound is the set itself. Untargeted by construction, like
    # Rewind's "up to four lands": no "target" is printed, so nothing is chosen
    # until the effect resolves (CR 115.1b).
    if stream.accept_phrase("any", "number", "of"):
        # "any number of **target** artifact cards" (Drafna's Restoration). The
        # word is recorded, not merely consumed, for the reason it is
        # everywhere else here: with it the objects are chosen as the spell is
        # cast (CR 601.2c) and every one of them is a target; without it
        # nothing is chosen until the effect resolves (CR 115.1b), which is
        # Siege Striker's "tap any number of untapped creatures you control".
        targeted_any = bool(stream.accept_word("target"))
        return ast.TargetSpec(
            "any_number", parse_object_filter(stream), count=0, targeted=targeted_any
        )

    # "**one or more** target creatures" (the five Legends colour spells). Its
    # own quantifier rather than an "any number of" with a floor bolted on: the
    # two differ in exactly the thing a picker enforces — "any number" may
    # legally name none (CR 601.2c) and this one may not — and they differ in
    # nothing else, so the distinction has to be the quantifier or it is
    # nowhere. Unbounded above, like "any number of": the sentence prints no
    # maximum, so the cap is however many legal targets exist.
    if stream.accept_phrase("one", "or", "more"):
        targeted_one_or_more = bool(stream.accept_word("target"))
        return ast.TargetSpec(
            "one_or_more", parse_object_filter(stream), count=0,
            targeted=targeted_one_or_more,
        )

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
        targeted = bool(stream.accept_word("target")) or other_before_target
    elif stream.accept_word("target"):
        quantifier = "target"
        targeted = True
    elif _at_counted_target(stream):
        # "**X** target lands" (Candelabra of Tawnos) / "two target creatures".
        # A bare count where "up to" prints a maximum: the player chooses
        # *exactly* this many, so it is the same several-target shape with a
        # different floor — and reading it as "up to" would let a card that
        # must untap four untap one and report itself supported, which is the
        # bug `_names_several_targets` was written after.
        amount = parse_amount(stream)
        count = amount.value if isinstance(amount, ast.Fixed) else 0
        exactly_x = not isinstance(amount, ast.Fixed)
        stream.expect_word("target")
        quantifier = "exactly"
        targeted = True
        # "…to **a target creature**" (Gaze of Pain) / "one target creature".
        # Older templating writes the article where modern templating writes
        # nothing, and CR 115.1 makes them the same phrase: one chosen object.
        # Collapsed to the ordinary `target` quantifier here rather than taught
        # to every lowering, because "exactly one target" is not a *different*
        # shape from "target" — it is the same shape spelled longer, and a
        # second spelling is what makes half the productions refuse a sentence
        # the other half reads.
        #
        # Only a printed **one**: "two target creatures" really is the
        # several-target shape, and "X target lands" has no number until the
        # cost is paid.
        if not exactly_x and count == 1:
            quantifier = "target"
    elif stream.at_word("another") and stream.peek_word(1) == "target":
        # "another target creature" (Garruk, Savage Herald) — a second chosen
        # object, distinct from the sentence's earlier choice. Guarded on the
        # following "target" so the sacrifice-cost reading of "another
        # <object>" is untouched.
        stream.advance(2)
        quantifier = "target"
        targeted = True
        distinct_from_prior = True
    elif stream.at_word("those"):
        # "each of **those creatures with flying**" (Winter Blast) — the objects
        # an earlier sentence of this same effect already acted on, narrowed by
        # a printed adjective. The bound plural `phrases.parse_bound_subject`
        # reads in the *subject* position, reached here in the object position
        # and with the filter read in full rather than from the noun alone:
        # this is the one place the adjective can select a subset of the bound
        # set, and a filter dropped here would damage every creature the earlier
        # sentence tapped.
        #
        # Safe to admit widely for the reason that bound subject is: every
        # lowering refuses quantifier "those" unless it says otherwise, so a
        # sentence reaching one fails by name rather than failing to parse.
        stream.advance()
        return ast.TargetSpec("those", parse_object_filter(stream))
    elif stream.at_word("another") and stream.peek_word(1) != "target":
        # "…to **another permanent** of that type" (Enchantment Alteration) —
        # the untargeted twin of the branch above: one object, distinct from the
        # one the sentence already named, chosen as the effect resolves rather
        # than declared as a target (CR 601.2c). Same quantifier as a bare "a",
        # because that is what it is; the word "another" is only the exclusion.
        stream.advance()
        quantifier = "a"
        distinct_from_prior = True
    elif stream.accept_word("each"):
        quantifier = "each"
    elif stream.accept_word("all"):
        quantifier = "all"
    elif stream.at_word("any") and stream.peek_word(1) != "target":
        # "if damage would be dealt to **any creature**" (Blood of the Martyr).
        # In a sentence about what *would* happen, "any <noun>" is the whole
        # class — CR 614's replacements are written about every object that
        # answers the phrase — so it is the sweep quantifier and not a choice.
        # Guarded on the following word because CR 115.4's "any target" is a
        # quantifier of its own and is read at the top of this function; every
        # other "any …" (a colour, a type, a number of) is claimed before the
        # cursor reaches here, and one that is not still fails in the noun
        # parser below and rewinds.
        stream.advance()
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
    if targeted and filt.is_enchanted:
        # "Destroy **target enchanted creature**." (Ramses Overdark.) The noun
        # parser reads "enchanted <noun>" as the referent CR 303.4b gives an
        # Aura — the permanent this Aura is attached to — because that is what
        # the phrase means on the cards that print it alone. With "target" in
        # front of it the same words are a *restriction*: nothing is attached to
        # Ramses, and the creature is picked from every enchanted creature on
        # the board. This is the one place both halves are known, so it is where
        # the referent becomes the restriction rather than in each lowering that
        # would otherwise have to ask the question again.
        filt = dataclasses.replace(filt, is_enchanted=False, enchanted_only=True)
    return ast.TargetSpec(
        quantifier, filt, count,
        count_from_x=exactly_x,
        distinct_from_prior=distinct_from_prior, targeted=targeted,
    )


def parse_recipient(stream: TokenStream) -> ast.Recipient | None:
    """Parse either a player reference or a quantified object reference."""
    player = parse_player_ref(stream)
    if player is not None:
        return player
    # A bare "it" refers back to the object the sentence already named. Its own
    # quantifier, because *which* object that is depends on the sentence: under
    # a trigger whose subject is the source ("whenever this creature attacks,
    # put a +1/+1 counter on it") it is the source, and under one whose subject
    # is a different named object ("when enchanted land becomes tapped, destroy
    # it") it is that object. `parser.py` rebinds it once the whole line is in
    # hand — see `rebind_pronoun_to_event_subject`.
    #
    # The source reading is the default rather than a placeholder: it is what
    # "it" means on every line with no trigger subject to name, which is every
    # line in the pool before this one. A card naming itself mid-sentence
    # ("this Aura deals 2 damage") is the SELF branch below and keeps
    # quantifier "this", which is the whole reason the two are not one node —
    # an Aura's own name and the permanent it enchants are different objects.
    if stream.at_word("it"):
        stream.advance()
        return ast.TargetSpec("it", ast.ObjectFilter(is_source=True))
    # "…and 3 damage to **itself**" (Psionic Entity). The same referent the
    # SELF token below names — the object the ability is on — reached by the
    # reflexive pronoun instead of by the printed name. One node for both, so a
    # card that spells its own name and a card that says "itself" mean the same
    # thing to every consumer; a second quantifier would be a second answer to
    # "which object is this sentence about?".
    #
    # Not folded into the bare "it" above: that pronoun back-refers to whatever
    # object the sentence already named and `parser.py` rebinds it against the
    # trigger's event subject, while "itself" is reflexive and can only be the
    # source (CR 109.2 — a self-reference in an ability names the object it is
    # on).
    if stream.at_word("itself"):
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    # "…tap **the creature**, remove it from combat" (Imprison), "…untap **the
    # creature**." (Paralyze). The definite article back-refers to the object
    # the sentence has already named, which under a trigger is that trigger's
    # event subject — exactly what a bare "it" means there. So it is that same
    # pronoun rather than a referent of its own, and `rebinding.py` points both
    # at the condition's subject in one place.
    #
    # Admitted only where the noun **ends the phrase**. Every other printed
    # "the <noun>" in the pool runs on into a possessive or a relative clause —
    # "the creature's controller" (Creature Bond), "the creature with the least
    # power" (Drop of Honey), "the creature that spell becomes" (Illusionary
    # Mask) — and each of those names a set the sentence is choosing from, not
    # an object it already holds. Claiming those two words there would take the
    # phrase away from the noun parser that reads the rest of them.
    mark_definite = stream.mark()
    if stream.accept_word("the"):
        # "…**the attacking creature** assigns no combat damage this turn"
        # (Farrel's Mantle). The same back-reference with the state the trigger
        # already established spelled out: the sentence is under "whenever
        # enchanted creature **attacks** and isn't blocked", so "the attacking
        # creature" and "the creature" name one object. Read as an adjective
        # here rather than as a noun phrase for the reason the bare form is:
        # the words point at an object the sentence already has, and the noun
        # parser would go looking for a set to choose from.
        #
        # One word, and only the one a printed sentence pairs with this shape.
        # A wider list would let a state the trigger did **not** establish
        # ("the blocking creature" under an attack trigger) resolve to the
        # attacker, which is a referent nothing checked.
        stated = stream.accept_word("attacking")
        noun = stream.peek_word()
        if noun is not None and noun in CARD_TYPES:
            stream.advance()
            if stream.exhausted or stream.at_punct(".", ",", ";"):
                return ast.TargetSpec("it", ast.ObjectFilter(is_source=True))
            # …and in the **subject** position, where a verb follows instead of
            # the end of the phrase. Admitted only with the state word printed:
            # bare "the creature" as a subject is read as a bound back-reference
            # by ``phrases.parse_bound_subject``, and claiming it here would take
            # every one of those sentences away from the lowerings written for
            # them. A possessive is left alone for the same reason the bare form
            # is — "the creature's controller" names a player, and the reader
            # below this one reads it.
            if stated and not stream.at_word("'s"):
                return ast.TargetSpec("it", ast.ObjectFilter(is_source=True))
    stream.reset(mark_definite)
    # "**that token**" — the token an earlier sentence of this same effect
    # created ("Exile that token when Stangg leaves the battlefield").
    #
    # A referent, like the two pronouns above, and not a noun phrase: no read
    # of a permanent alone can say whether *this* resolution made it, so the
    # token maker writes the id to the resolution scratchpad and this reads it
    # back. Which is also why the lowering refuses the phrase with no token
    # maker in front of it, exactly as "its controller creates" refuses with no
    # exile in front of it — a dropped referent here would exile whatever
    # permanent happened to answer.
    mark_token = stream.mark()
    if stream.accept_phrase("that", "token"):
        return ast.TargetSpec("that", ast.ObjectFilter(is_created_token=True))
    stream.reset(mark_token)
    # "**the token**" — the token this *permanent* created, a longer reach than
    # the phrase above and a different record.
    #
    # Dance of Many prints Stangg's pair of sentences as separate ability
    # lines: one makes the token, and two more name it when either permanent
    # leaves the battlefield, turns later. "That token" reads the resolution
    # scratchpad and there is none by then, so the referent here is the durable
    # record the token maker stamps on what it made — the same
    # ``created_with_source`` relation Tetravus's "tokens created with this
    # creature" reads, asked of one token rather than of any number.
    mark_the_token = stream.mark()
    if stream.accept_phrase("the", "token"):
        return ast.TargetSpec(
            "that",
            ast.ObjectFilter(token_only=True, created_with_source=True),
        )
    stream.reset(mark_the_token)
    # The card naming itself mid-sentence ("put a loyalty counter on Garruk") —
    # the lexer already collapsed the name to one SELF token.
    token = stream.peek()
    if token is not None and token.kind == "self":
        stream.advance()
        return ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    return parse_target_spec(stream)


__all__ = ["parse_player_ref", "parse_recipient", "parse_target_spec"]
