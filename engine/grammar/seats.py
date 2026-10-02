"""Which **seat** a printed phrase names — CR 102's player, not CR 109's object.

Split out of ``references`` at Urza's Saga's wave-2 integration, when that
module reached the thousand-line guard with **one** line to spare and a third
wave still to come. The seam is that module's own opening paragraph, which has
stated it since the day it was written: "CR 109 is what an object is, CR 115 is
how a spell chooses one, and **a player (CR 102) is not an object at all**".
``references`` keeps the two halves of CR 115 — what a phrase points at and how
many — and this is the third question it had been carrying.

It reuses the name ``_seats`` has carried on the ``ast`` side since Weatherlight
and on the ``lowering`` side since it left ``_common``, so the mirror re-forms
across all three rather than forking a fourth vocabulary for one idea.

**A floor, not a family**: nothing here reads ``references`` back, and
``references`` re-exports ``parse_player_ref`` under the name every caller
already imports — the arrangement its own docstring says ``readers`` has one
layer further down, and the same promise the back-references' move made.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .nouns import _GENERIC_NOUNS, _singular, parse_object_filter
from .stream import TokenStream
from .vocabulary import ALL_SUBTYPES, CARD_TYPES


def parse_player_ref(stream: TokenStream) -> ast.PlayerRef | None:
    """Parse a player reference at the cursor, or return None."""
    mark = stream.mark()

    if stream.accept_word("you"):
        return ast.PlayerRef("you")

    if stream.accept_phrase("each", "player"):
        return ast.PlayerRef("each_player")
    if stream.accept_phrase("each", "opponent"):
        return ast.PlayerRef("each_opponent")
    # "if **your opponents** control no creatures" (Kezzerdrix). CR 102.2/102.3
    # again: a player's opponents are every player who is not them, which is the
    # set "each opponent" already names — so this is a third spelling of that
    # seat, not a fourth referent, exactly as "each other player" below is.
    #
    # The plural matters and is required: "your opponent" singular is a phrase
    # no modern printing uses, and reading it here would give a duel-only card
    # the same reading in a free-for-all, where the two differ.
    if stream.accept_phrase("your", "opponents"):
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
    # "**Target spell's controller** exiles it …" (Ertai's Meddling). The seat
    # is not what the sentence targets: "target" modifies *spell*, so the
    # announcement chooses an object on the stack (CR 115.1) and the player is
    # read off it (CR 109.5). That is what makes it a referent of its own rather
    # than a spelling of `target_player` — a picker handed `target_player` would
    # offer the seats and the spell would never be chosen at all.
    #
    # Only "spell", and the narrowness is the point: a spell on the stack is the
    # one object whose controller this engine can name from the announcement
    # (the chosen stack item's caster). "Target creature's controller" is a
    # different lookup with a different picker, and reading it here would hand
    # every lowering a seat it cannot resolve.
    mark_spells_controller = stream.mark()
    if stream.accept_phrase("target", "spell", "'s", "controller"):
        return ast.PlayerRef("target_spells_controller")
    stream.reset(mark_spells_controller)
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
    # "You and **that opponent** each gain control of …" (Reins of Power). The
    # seat the sentence in front of this one chose, which is exactly what
    # `that_player` means to every consumer downstream — so it is a spelling of
    # that referent, not a fourth one, and `readers.py` has read the two words
    # through a single branch (`_accept_back_referenced_controller`) since it
    # read "that player controls". Splitting them here would be the fork this
    # repo closes elsewhere: which reading a card got would depend on whether
    # its seat turned up in a noun phrase or in a subject.
    #
    # An **opponent** rather than any player is a narrowing the announcement
    # already made — the earlier sentence targeted one — so nothing here has to
    # carry the word.
    if stream.accept_phrase("that", "opponent"):
        return ast.PlayerRef("that_player")
    # "…**they** gain 1 life" (Spiritual Sanctuary). The pronoun back-refers to
    # the player the sentence has already named, which is exactly what
    # `that_player` means to every consumer downstream — so it is an alias, not
    # a fourth referent. `nouns.py` set the precedent the other way round when
    # it read "they control" as a `that_player` narrowing; the two spellings
    # disagreeing about the same word is the fork this repo closes elsewhere.
    #
    # **The accusative "them" is deliberately not here**, and the asymmetry is
    # the grammar's rather than English's. "They" only ever opens a predicate,
    # and no plural set of *cards* is ever a sentence subject in this pool — so
    # the nominative has one possible referent and belongs in the shared
    # reader. "Them" sits after a verb or a preposition, which is exactly where
    # a set of cards an earlier clause produced also sits: "Create three …
    # tokens. Exile **them**" (Waylay), "…reveal **them**, put **them** into
    # your hand" (Cultivate). Claiming it here took Waylay's tokens for a seat
    # and cost the card its support. So the word is read where the *consumer*
    # needs a player and nothing else could be meant — `effects/damage.py` for
    # Rivalry's recipient, `paragraphs.py` for Vexing Arcanix's — which is the
    # same arrangement damage's "or planeswalker" union already has.
    if stream.accept_word("they"):
        return ast.PlayerRef("that_player")
    # "…**the player** discards it unless they pay …" (Wand of Ith). The
    # definite article back-refers to the player the sentence in front of this
    # one named, which is what `that_player` means downstream — an alias, like
    # "they" above, and not a fourth referent. Only the bare two words: "the
    # player who …" is a *description* of a seat and belongs to the productions
    # that read one.
    # "…**The first player** may reveal cards from the top of their library"
    # (the Exodus Oaths). Wizards' own disambiguator for a sentence with two
    # players in it: the one that *chose* is "the first player" and the one
    # chosen is "the second". So the first is the seat the sentence in front of
    # this one named — which is what `that_player` means to every consumer
    # downstream, and which under those cards' trigger the upkeep loop froze —
    # and the second is the target that sentence announced, read off the record
    # the choosing step wrote.
    #
    # Two words each and both required. The ordinals are the whole content: a
    # reader that took "the first player" for "the player" would collapse the
    # two seats the card printed apart.
    if stream.accept_phrase("the", "first", "player"):
        return ast.PlayerRef("that_player")
    if stream.accept_phrase("the", "second", "player"):
        return ast.PlayerRef("chosen_player")
    mark_the_player = stream.mark()
    if stream.accept_phrase("the", "player"):
        # "…**the player with the most life** gains control of this creature."
        # (Wild Dogs.) A *description* of a seat rather than a back-reference:
        # nobody chose it and no event froze it, so it is read off the life
        # totals when the ability resolves.
        #
        # Its own referent and not an alias of ``that_player``, because the two
        # answer different questions: the alias means "the seat the sentence in
        # front named", and this one is answered by the board — under a "your
        # upkeep" trigger the frozen seat is the *controller*, which is the
        # player Wild Dogs is trying to leave.
        #
        # A **tie names nobody**, which the evaluator answers and the card's own
        # intervening-if states in front of it ("if a player has more life than
        # each other player"): the two agree because both are strict.
        if stream.accept_phrase("with", "the", "most", "life"):
            return ast.PlayerRef("most_life")
        # "…**the player who controls the most creatures** gains control of
        # this creature." (Wild Mammoth.) The same description over a board
        # count instead of a life total, and the same reading: answered by the
        # board as the ability resolves, and a tie names nobody.
        #
        # The counted phrase rides ``controls`` — the field that already says
        # "the noun phrase this seat's board is described by" — and the *kind*
        # says how: presence for "each player who controls a white creature"
        # (Disorder), the strict maximum here. Every lowering that reads the
        # field reads it beside a kind it knows, and one that does not know
        # this kind refuses it by name rather than reading the phrase as a
        # presence test.
        most_mark = stream.mark()
        if stream.accept_phrase("who", "controls", "the", "most"):
            try:
                counted = parse_object_filter(stream)
            except GrammarError:
                counted = None
            if counted is not None and counted != ast.ObjectFilter():
                return ast.PlayerRef("controls_the_most", controls=counted)
        stream.reset(most_mark)
        if stream.exhausted or not stream.at_word("who", "with", "whose"):
            return ast.PlayerRef("that_player")
    stream.reset(mark_the_player)
    if stream.accept_phrase("its", "controller"):
        return ast.PlayerRef("controller")
    # "Destroy target creature. **Its owner** gains 4 life." (Path of Peace.)
    # CR 108.3's seat, and a different one from the possessive above it for
    # every permanent anybody has ever stolen — which is the whole reason it is
    # a second kind rather than a spelling of "controller". Read as that one,
    # Path of Peace heals whoever took the creature.
    #
    # What it may *mean* is left to the lowerings, which refuse it wherever no
    # step of the same effect recorded an object: a bare "its owner" with
    # nothing in front of it names nobody, and a seat nobody named is the
    # failure this file's neighbours all refuse rather than default.
    if stream.accept_phrase("its", "owner"):
        return ast.PlayerRef("owner")
    if stream.accept_phrase("their", "controller"):
        return ast.PlayerRef("controller")
    if stream.accept_phrase("defending", "player"):
        return ast.PlayerRef("defending_player")
    if stream.accept_phrase("the", "chosen", "player"):
        return ast.PlayerRef("chosen_player")
    # "the controller of **the last red instant or sorcery spell that dealt
    # damage to you this turn**" (Suffocation). A seat read out of a *history*,
    # which is neither of the two referents this file already has: `that_player`
    # is a seat an event froze and `target_player` is one the spell chose, and
    # this one was chosen by nobody and frozen by nothing — the turn's damage
    # record is asked for it when the spell resolves.
    #
    # The noun phrase is read by `parse_object_filter`, the same reader the
    # matcher that answers it goes through, so "red instant or sorcery spell"
    # cannot mean one thing here and another where the seat is looked up. Every
    # word after it is required: "that dealt damage to you this turn" is the
    # whole of the window and a printing naming another one would be a
    # different record.
    mark_last_damager = stream.mark()
    if stream.accept_phrase("the", "controller", "of", "the", "last"):
        try:
            described = parse_object_filter(stream)
        except GrammarError:
            described = None
        if described is not None and stream.accept_phrase(
            "that", "dealt", "damage", "to", "you", "this", "turn"
        ):
            return ast.PlayerRef("last_damager_controller", last_damager=described)
    stream.reset(mark_last_damager)
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
        if _heads_a_possessive(noun):
            stream.advance()
            # "that **creature's or spell's** controller" (Justice) / "that
            # **spell or ability's** controller" (Retromancer). The event named
            # *one* object, so the alternation is two spellings of one referent
            # and every branch below returns the same ``PlayerRef``. A loop
            # rather than a second `or` clause: a third noun is this sentence
            # again. English writes the possessive on every noun or on the last
            # alone, and both cards are printed — so the marker is optional per
            # noun and required *somewhere*, which is what keeps "that creature
            # or player", a disjunction of two different referents that other
            # productions read, out of this production.
            saw_possessive = stream.accept_word("'s")
            while stream.at_word("or"):
                alternative = stream.mark()
                stream.advance()
                other = stream.peek_word()
                if _heads_a_possessive(other):
                    stream.advance()
                    if stream.accept_word("'s"):
                        saw_possessive = True
                        continue
                stream.reset(alternative)
                break
            if saw_possessive:
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

def _heads_a_possessive(noun: str | None) -> bool:
    """Whether *noun* can head a "…'s controller/owner" phrase.

    One reader rather than the same four-way disjunction spelled twice, which
    is what let a head noun and its alternatives drift while looking identical.
    ``ability`` is listed here and not in ``_GENERIC_NOUNS`` because an ability
    on the stack is an object with a controller (CR 113.7a) and no card, and
    that set is what a *noun phrase* may head (Ayesha Tanaka).
    """
    if noun is None:
        return False
    singular = _singular(noun)
    return (
        singular in CARD_TYPES
        or singular in _GENERIC_NOUNS
        or singular in ALL_SUBTYPES
        or singular == "ability"
    )


def accept_life_total_of(stream: TokenStream) -> "ast.PlayerRef | None":
    """``<player>'s life total`` — one operand of a life comparison.

    Both spellings of the possessive, for the reason the zone-count clause
    below carries both: "your" is a determiner ``parse_player_ref`` does not
    read at all, and "target player's" is that reader plus an apostrophe. A
    fragment rather than an arm of the clause above it because the sentence
    prints it twice, and two copies would be two answers to which seats a life
    comparison may name.

    Returns None with the cursor where it was, so the caller can rewind the
    whole clause rather than the half it consumed.

    Here rather than in ``conditions``, where it was written: what it answers is
    "which seat does this phrase name?", which is this module's whole subject,
    and the possessive is a suffix on the reader beside it rather than anything
    about a condition. It came down at Urza's Saga's third wave, when
    ``conditions`` needed the room for a clause that really is one.
    """
    mark = stream.mark()
    if stream.accept_word("your"):
        who: "ast.PlayerRef | None" = ast.PlayerRef("you")
    else:
        who = parse_player_ref(stream)
        if who is None or not stream.accept_word("'s"):
            stream.reset(mark)
            return None
    if not stream.accept_phrase("life", "total"):
        stream.reset(mark)
        return None
    return who
