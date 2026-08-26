"""The trailing half of a noun phrase: everything printed **after** the head.

"creature **you control**", "creature **with flying**", "creature **other than
this creature**", "creature **blocking target attacking creature**". Split from
`nouns` because that module had grown to 967 lines around a single 795-line
`parse_object_filter`, and this is the half that grows: a new printed
restriction is nearly always a postmodifier.

The two halves are genuinely different readings. Leading adjectives narrow the
*kind* of object — colour, type, state — and each is one word tested against a
vocabulary. A postmodifier names a **relation**: to the controller, to another
object the sentence names, to a zone. That is why this file recurses and the
adjective loop does not.

**The recursion arrives as a parameter.** "blocking target attacking creature"
contains a whole nested phrase, so this file needs `parse_object_filter` — which
lives one layer up. Taking it as *parse_filter* rather than importing it keeps
the dependency running one way, the same inversion `lowering/where_x.py` makes
for the same reason.

Everything both halves accumulate lives on the `_FilterDraft` they share; see
its docstring in `nouns`.
"""

from __future__ import annotations

from typing import Callable

from . import ast
from .abilities import _accept_ability_source
from .amounts import parse_comparison
from .errors import GrammarError
from .lexer import NUMBER, PT, PUNCT, SELF, WORD
from .names import parse_card_name
from .readers import _SELF_NOUNS, accept_source_reference
from .stream import TokenStream
from .vocabulary import (ALL_SUBTYPES, CARD_TYPES, COLOR_WORDS, CREATURE_TYPES,
                         GENERIC_NOUNS as _GENERIC_NOUNS, KEYWORD_INDEX,
                         LAND_TYPES, NUMBER_WORDS, SUPERTYPES, match_longest,
                         singular as _singular)

# "…attached to that creature" / "…attached to it" — the trailing clause naming
# what an Aura or Equipment is on, and the referent each consumer resolves.
# Every consumer must answer every entry: a referent nothing resolves is a
# relation dropped, and a dropped relation on a sweep takes the whole board.
_ATTACHED_TO_REFERENTS = {("that", "creature"): "target", ("it",): "source"}


# Zones a noun phrase can be scoped to ("target creature card **from your
# graveyard**"). The battlefield is deliberately absent: it is already the
# default, so consuming "from the battlefield" here would leave no trace that
# the phrase had been read at all — exactly the silent-drop this parser exists
# to prevent. A production that needs it should say so explicitly.
_ZONE_NOUNS = frozenset({"graveyard", "hand", "library", "exile"})


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


def _parse_zone_owner_of(stream: TokenStream) -> "ast.PlayerRef | None":
    """The player named after "from the <zone> **of** …", or None.

    Its own small reader rather than a call into ``references.parse_player_ref``
    because that module sits *above* this one — it reads noun phrases, which are
    built from what this file parses — and the phrases printed in this position
    are not the ones a recipient clause prints. Widening it means adding a
    spelling here, and a spelling nothing lists refuses the whole noun phrase
    rather than silently naming some other player's graveyard.

    "…the graveyard of **the player who controlled that creature the last time
    it became blocked by that Wall**" (Glyph of Reincarnation) is a seat no read
    of the board can answer: control is CR 613 layer 2 and moves, and by the
    time the sentence is read the creature is a card in a graveyard with no
    controller at all. The block seam freezes the seat as the block happens, and
    this referent names that record — "the last time" being exactly the
    overwrite-on-each-block that seam performs. Every word is required, and the
    noun after "by that" is checked rather than skipped: a dropped word here
    leaves a phrase naming some other player, and a reanimation out of the wrong
    graveyard is a different card.
    """
    probe = stream.mark()
    if stream.accept_phrase(
        "the", "player", "who", "controlled", "that", "creature",
        "the", "last", "time", "it", "became", "blocked", "by", "that",
    ):
        noun = stream.peek_word()
        if noun is not None and (
            _singular(noun) in CARD_TYPES or _singular(noun) in CREATURE_TYPES
        ):
            stream.advance()
            return ast.PlayerRef("controller_when_blocked")
    stream.reset(probe)
    return None


def _parse_postmodifiers(
    stream: TokenStream,
    d,
    parse_filter: Callable[..., "ast.ObjectFilter"],
) -> None:
    """Read every postmodifier the cursor is at, onto *d*."""
    # --- postmodifiers ---------------------------------------------------
    while True:
        # "you both own and control" (Obelisk of Undoing). Read before the bare
        # "you control", which is its suffix: matching that first would consume
        # "control" and strand "own", and — worse — would compile the card as
        # though it read "any permanent you control", which is exactly the
        # stolen permanent it is printed to exclude.
        if stream.accept_phrase("you", "both", "own", "and", "control"):
            d.controller = "you"
            d.owned_by = "you"
            continue
        if stream.accept_phrase("you", "control"):
            d.controller = "you"
            continue
        # "you don't control" (Teferi, Master of Time's −3). The lexer keeps
        # "don't" as one word.
        if stream.accept_phrase("you", "don't", "control"):
            d.controller = "not_you"
            continue
        if stream.accept_phrase("an", "opponent", "controls"):
            d.controller = "opponent"
            continue
        # "target nontoken permanent an opponent **owns**" (Bronze Tablet).
        # Ownership, not control (CR 108.3 against CR 613 layer 2) — a card
        # printed with "owns" excludes the permanent it stole from that
        # opponent, and reading one as the other is exactly the mistake round
        # 13 recorded about Obelisk of Undoing.
        if stream.accept_phrase("an", "opponent", "owns"):
            d.owned_by = "opponent"
            continue
        # "creatures **your opponents** control" (Massacre Wurm, Waker of
        # Waves) — the plural spelling of the same scope: every opponent's
        # creatures, and none of the controller's own.
        if stream.accept_phrase("your", "opponents", "control"):
            d.controller = "opponent"
            continue
        # "each creature target opponent controls" (Teferi, Timeless Voyager's
        # −8): the controller is a chosen player — the spell targets the
        # opponent, not the creatures.
        if stream.accept_phrase("target", "opponent", "controls"):
            d.controller = "target_opponent"
            continue
        # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the
        # object is colored — matching reads the effective colors, so a
        # colorless artifact escapes and a Lace-painted one does not.
        if stream.accept_phrase("that", "'s", "one", "or", "more", "colors"):
            colored = True
            continue
        # "target artifact **defending player controls**" (Floral Spuzzem).
        # A seat only the combat that fired the trigger knows, so it is carried
        # like `that_player` beside it — refused by the pure matcher and
        # resolved by whoever holds the event's context. Reading it as
        # "opponent" would be right in a duel by coincidence and wrong the
        # moment a third seat is not the one being attacked.
        if stream.accept_phrase("defending", "player", "controls"):
            d.controller = "defending_player"
            continue
        if stream.accept_phrase("that", "player", "controls"):
            d.controller = "that_player"
            continue
        if stream.accept_phrase("they", "control"):
            d.controller = "that_player"
            continue
        # "creatures **blocking this creature**" (The Wretched) — the set of
        # blockers declared against the ability's own source (CR 509.1a).
        # "…blocking **target attacking creature**" and "…blocking **it**"
        # (Feint) are that relation with the other end on an object this same
        # sentence names. Which of the three it is decides the field; what the
        # three fields mean is on `ObjectFilter` itself.
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
                d.blocking_source = True
                continue
            if stream.accept_word("this"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in _SELF_NOUNS:
                    stream.advance()
                    d.blocking_source = True
                    continue
            # "blocking **target** <noun phrase>": chosen as this spell is cast
            # (CR 601.2c), so the phrase is read whole by recursing here — which
            # is what makes it a description rather than a second vocabulary.
            if stream.accept_word("target"):
                d.blocking_target = parse_filter(stream)
                continue
            # "blocking **it**" / "blocking **that creature**": nothing is parsed
            # because nothing is printed — the referent is this spell's target.
            if stream.accept_word("it"):
                d.blocking_bound_target = True
                continue
            if stream.accept_word("that"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in _SELF_NOUNS:
                    stream.advance()
                    d.blocking_bound_target = True
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
                    d.other_than_source = True
                    continue
            elif stream.accept_word("than"):
                # "other than Halfdane" — the card excluding itself by name,
                # which the lexer already collapsed to one SELF token. The same
                # restriction as "other than this creature", so it sets the
                # same field rather than minting a second one.
                token = stream.peek()
                if token is not None and token.kind == SELF:
                    stream.advance()
                    d.other_than_source = True
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
            # "from **its owner's** graveyard" (Reincarnation). The same
            # referent `_parse_zone` already reads on the destination side, and
            # the same kind: "the owner of the object this sentence is about".
            # Which object that is depends on the sentence, and is the
            # lowering's question rather than the noun parser's.
            elif stream.accept_phrase("its", "owner", "'s"):
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
                # "from **the graveyard of** <player>" (Glyph of
                # Reincarnation) — the possessive said the other way round.
                # Tried only when the possessive spellings above found nothing,
                # so a phrase naming its owner twice cannot quietly keep the
                # second answer; and the referent has to be one this file
                # reads, because "the graveyard of" followed by words nothing
                # claims names a graveyard that cannot be found.
                if owner is None and stream.accept_word("of"):
                    owner = _parse_zone_owner_of(stream)
                    if owner is None:
                        stream.reset(probe)
                        break
                d.zone = noun
                d.zone_owner = owner
                continue
            stream.reset(probe)
            break
        if stream.at_word("with"):
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("power"):
                d.power = parse_comparison(stream)
                continue
            if stream.accept_word("toughness"):
                d.toughness = parse_comparison(stream)
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
                        d.with_plus1_counter = True
                        continue
                stream.reset(counter_probe)
            # "with mana value X" (Spell Blast). Two words, so it is tried
            # before the keyword list — "mana" alone is not a keyword, but
            # leaving the phrase unmatched would strand "value X" and fail the
            # whole line rather than restricting the noun phrase.
            if stream.accept_phrase("mana", "value"):
                d.mana_value = parse_comparison(stream)
                continue
            try:
                d.with_keywords.extend(_parse_keyword_list(stream))
                continue
            except Exception:
                stream.reset(probe)
                break
        if stream.at_word("without"):
            probe = stream.mark()
            stream.advance()
            try:
                d.without_keywords.extend(_parse_keyword_list(stream))
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
                    d.not_ability_targeted_by_same_name = True
                    continue
            # "…**that dealt damage to it this turn**" (Brine Hag). A history
            # relative to the ability's source, answered from the damage record
            # the victim carries rather than from the object's characteristics
            # — so it is a flag the one lowering written for it reads, and every
            # other one refuses (see ``ObjectFilter``). "This turn" is required:
            # without it the sentence says something the record cannot answer.
            # "…**that targets a permanent you control**" (Avoid Fate, Ring
            # of Immortals). What the object *chose*, which is a question only
            # a spell or an ability on the stack can be asked — so the inner
            # noun phrase is parsed in full and recorded whole, and every
            # lowering not written for it refuses the field by name.
            # "…**that isn't enchanted**" (Time Elemental). CR 303.4a: a
            # permanent is enchanted while an Aura is attached to it, so this is
            # a question about the candidate alone and the pure matcher answers
            # it. An Equipment attached to the same permanent does *not* make it
            # enchanted, which is why the matcher asks for the Aura subtype
            # rather than for the attachment record this engine shares between
            # the two (CR 301.5f).
            elif stream.accept_phrase("isn't", "enchanted"):
                d.not_enchanted = True
                continue
            elif stream.accept_word("targets"):
                stream.accept_word("a", "an")
                d.targets_object = parse_filter(stream)
                continue
            # "…that **were blocked by that creature this turn**" (Glyph of
            # Doom). "That creature" is the object the sentence's delayed
            # ability was bound to, and "this turn" is what makes the record
            # outlive the combat the block happened in — both required, for the
            # reason the damage clause below requires its own.
            elif stream.accept_phrase("were", "blocked", "by", "that"):
                noun = stream.peek_word()
                if noun is not None and _singular(noun) in CARD_TYPES:
                    stream.advance()
                    if stream.accept_phrase("this", "turn"):
                        d.blocked_by_bound_object = True
                        continue
            # "…that were blocked by **target Wall** this turn" (Glyph of
            # Reincarnation). The same history against the *spell's own target*
            # instead of a bound object, so the blocker's own noun phrase is
            # read and travels with the relation — the lowering hoists it into
            # the instruction's `targets` description, which is what makes the
            # picker offer Walls. "This turn" is required here for the reason it
            # is required above: the record is kept per turn, and a clause
            # naming some other window is a different sentence.
            elif stream.accept_phrase("were", "blocked", "by", "target"):
                blocker = parse_filter(stream)
                if stream.accept_phrase("this", "turn"):
                    d.blocked_by_target_object = blocker
                    continue
            # "…that **target Wall blocked this turn**" (Glyph of Delusion). The
            # same relation as the passive clause directly above, printed with
            # the blocker as the sentence's subject rather than its agent — so
            # it sets the same field, and everything downstream (the lowering's
            # hoist, the role picker, the block record the handler reads) is
            # written once for both voices. Spelling it as its own field would
            # have been two names for one fact, and the second would need its
            # own reader everywhere the first already has one.
            elif stream.accept_word("target"):
                blocker = parse_filter(stream)
                if stream.accept_phrase("blocked", "this", "turn"):
                    d.blocked_by_target_object = blocker
                    continue
            elif stream.accept_phrase("dealt", "damage", "to"):
                if accept_source_reference(stream) and stream.accept_phrase(
                    "this", "turn"
                ):
                    d.dealt_damage_to_source_this_turn = True
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
                d.in_combat_with_source = True
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
                    d.created_with_source = True
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
                d.named = parse_card_name(stream)
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
                    d.attached_to = matched[1]
                    continue
                # "target Aura **attached to a creature or land**" (Enchantment
                # Alteration). Not a back-reference but a type: what the
                # attachment is on, asked of the attachment itself. Read
                # through the same noun-phrase parser rather than by a word
                # list here, and admitted only when the phrase is *nothing but*
                # card types — anything else in it would be a restriction the
                # matcher drops, which on an Aura-mover is the wrong Aura moved.
                nested = stream.mark()
                stream.accept_word("a", "an")
                try:
                    host = parse_filter(stream)
                except GrammarError:
                    host = None
                if host is not None and host.card_types and host == ast.ObjectFilter(
                    card_types=host.card_types, type_match=host.type_match
                ):
                    d.attached_to_types = host.card_types
                    continue
                stream.reset(nested)
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
                d.their_choice = True
                continue
            # "another permanent **of that type**" (Enchantment Alteration) —
            # the type of the object the sentence's earlier clause named.
            # Recorded, never resolved here: the noun phrase cannot know what
            # that object was, and a lowering with no answer for it refuses.
            if stream.accept_phrase("that", "type"):
                d.of_bound_type = True
                continue
            stream.reset(probe)
            break
        break
