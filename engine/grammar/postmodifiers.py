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


def _accept_back_referenced_controller(stream: TokenStream) -> bool:
    """``that player|opponent [or that <type>'s controller] control[s]`` — True
    with the phrase consumed, or False with the cursor unmoved.

    One reader for both spellings, because they are one referent. Goblin Lyre
    targets "target opponent **or planeswalker**" (CR 115.4 without the creature
    half) and then counts "the number of creatures **that opponent or that
    planeswalker's controller** controls" — a seat either way, and the same seat
    the earlier sentence chose. So the disjunction is a *spelling* of
    `that_player`, the way `references.py` already reads Chain Lightning's "that
    player or that permanent's controller"; a kind of its own would be one
    card's private address for a referent every consumer already has.

    Read inline rather than through `parse_player_ref`: that reader is in
    `references`, two layers above this file, which sits below `nouns` so the
    recursion can run one way.
    """
    mark = stream.mark()
    if stream.accept_phrase("that", "player") or stream.accept_phrase(
        "that", "opponent"
    ):
        _accept_same_seat_disjunct(stream)
        if stream.accept_word("controls", "control"):
            return True
    stream.reset(mark)
    return False


def _accept_same_seat_disjunct(stream: TokenStream) -> None:
    """The optional ``or that <type>'s controller`` arm, consumed only when it
    really names the same seat as the arm in front of it.

    Any other "or" is left where it is, for whatever production reads a
    disjunction of two *different* things — consuming it here would silently
    merge them.
    """
    mark = stream.mark()
    if not stream.accept_word("or"):
        return
    if stream.accept_word("that", "this", "the"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in CARD_TYPES:
            stream.advance()
            if stream.accept_phrase("'s", "controller"):
                return
    stream.reset(mark)


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
        # "all Auras **you own** attached to permanents you control" (Remove
        # Enchantments). Ownership alone, with no word about control: the card
        # is deliberately naming a different seat for the Aura than for its
        # host, so reading this as "you control" would return an Aura you own
        # that an opponent has taken — and dropping it would return theirs.
        # Read *after* the "both own and control" branch above, which this is a
        # suffix of.
        if stream.accept_phrase("you", "own"):
            d.owned_by = "you"
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
        # "nontoken permanents **of the chosen color** they control" (Psychic
        # Allergy). CR 614.1c's choice, made as the source entered and stored on
        # it — so the phrase narrows by a colour the sentence never names and
        # only a reader holding the *source* can answer. That is why it is its
        # own filter key rather than a colour: `permanent_matches_filter` is the
        # pure half and refuses the key outright, and the two readers that do
        # have a source (`subject_matches`, `evaluate_count`) resolve it before
        # matching.
        if stream.accept_phrase("of", "the", "chosen", "color"):
            d.chosen_color = True
            continue
        # "all untapped creatures **that didn't attack this turn**, **except
        # for creatures that couldn't attack**" (Season of the Witch). Two
        # narrowings of one noun phrase, both about the same combat: the first
        # is the set the sweep takes, the second is the exemption the card
        # prints. Read here rather than as a sentence-level exception clause
        # because they narrow the *subject* — the sweep destroys exactly what
        # the noun phrase names, and an exemption read anywhere else would have
        # to be re-applied by every verb.
        if stream.accept_phrase("that", "didn't", "attack", "this", "turn"):
            d.attacked_this_turn = False
            continue
        # "…creatures that player controls **that didn't attack**" (Total War).
        # The same narrowing with the two words the card does not print, and
        # the same record answers it: `attacked_this_turn` is stamped at the
        # declaration, so "didn't attack" asked during the combat it fired in
        # names exactly the creatures left at home. Read *after* the longer
        # spelling above, which it is a strict prefix of.
        if stream.accept_phrase("that", "didn't", "attack"):
            d.attacked_this_turn = False
            continue
        if stream.accept_phrase("that", "attacked", "this", "turn"):
            d.attacked_this_turn = True
            continue
        except_mark = stream.mark()
        stream.accept_punct(",")
        if stream.accept_phrase(
            "except", "for", "creatures", "that", "couldn't", "attack"
        ):
            d.could_attack_this_turn = True
            continue
        # "…**except for creatures the player hasn't controlled continuously
        # since the beginning of the turn**" (Total War). The second printed
        # exemption in the pool and the same shape as Season of the Witch's
        # above: an exception clause narrowing the noun phrase, so the sweep
        # takes exactly what the phrase names and no verb has to re-apply it.
        #
        # Stored as the *positive* — controlled that long — because that is the
        # set the sentence leaves behind, and an inversion carried downstream is
        # an inversion each reader has to get right.
        if stream.accept_phrase(
            "except", "for", "creatures", "the", "player", "hasn't",
            "controlled", "continuously", "since", "the", "beginning",
            "of", "the", "turn",
        ):
            d.controlled_since_turn_start = True
            continue
        stream.reset(except_mark)
        # "…creatures **that player** controls" and "…the number of creatures
        # **that opponent or that planeswalker's controller** controls" (Goblin
        # Lyre) are one reader: both name the seat the sentence in front of this
        # one already chose, which is exactly what `that_player` means to every
        # consumer downstream.
        if _accept_back_referenced_controller(stream):
            d.controller = "that_player"
            continue
        if stream.accept_phrase("they", "control"):
            d.controller = "that_player"
            continue
        # "target creature **whose controller controls an Island**"
        # (Seasinger). Not a seat this object's controller *is*, but a fact
        # about what that seat has elsewhere — so it is its own field rather
        # than a value of ``controller``, which every reader takes as a
        # comparison against the ability's own seat. The thing they must
        # control is a whole noun phrase, read by the same reader that read
        # the phrase this modifies.
        whose = stream.mark()
        if stream.accept_phrase("whose", "controller", "controls"):
            # The article, for the same reason the host phrase below strips
            # one: the noun parser reads what comes *after* a quantifier, so
            # "an Island" reaches it as "Island". A phrase that narrows nothing
            # is not this clause — "whose controller controls a permanent" says
            # only that somebody controls it, which every permanent on a
            # battlefield already does.
            stream.accept_word("a", "an")
            try:
                required = parse_filter(stream)
            except GrammarError:
                required = None
            if required is not None and required != ast.ObjectFilter():
                d.controller_controls = required
                continue
            stream.reset(whose)
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
        # "target creature **it's blocking**" (Goblin Snowman, Tinder Wall) and
        # "target creature **that's attacking you**" (Ice Floe, Snow Fortress).
        # Both are a relation to somebody other than the creature described, so
        # both are relative filter fields rather than state adjectives — see
        # `ObjectFilter.blocked_by_source` / `attacking_you`.
        #
        # Read before the "blocking …" branch below because that one probes on
        # the bare word: "it's blocking" would enter it, fail to find a subject
        # after "blocking", reset, and break the whole postmodifier scan.
        if stream.accept_phrase("it", "'s", "blocking"):
            d.blocked_by_source = True
            continue
        # "…all Merfolk **tapped this turn to pay for its abilities**"
        # (Vodalian War Machine). Every word is required. "Tapped this turn" on
        # its own is a strictly larger set — a creature tapped to attack is in
        # it — so a clause that stopped there would destroy Merfolk the card
        # does not name; and "its abilities" is what makes the set relative to
        # the ability's own source rather than to anybody's.
        if stream.accept_phrase(
            "tapped", "this", "turn", "to", "pay", "for", "its", "abilities",
        ):
            d.tapped_to_pay_for_source_this_turn = True
            continue
        if stream.accept_phrase("that", "'s", "attacking", "you"):
            d.attacking_you = True
            continue
        # "…for each green creature they control **that's attacking**"
        # (Flooded Woodlands, Reclamation). The relative-clause spelling of the
        # bare adjective "attacking", so it sets the same field: two spellings of
        # one state, and a second field would be a second thing every matcher
        # has to remember to test. Read *after* the "attacking you" branch
        # above, whose prefix this is — tried first it would take those words and
        # strand the "you".
        if stream.accept_phrase("that", "'s", "attacking"):
            d.attacking = True
            continue
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
            # "in **target opponent's** graveyard" (Spoils of Evil). The same
            # chosen seat with CR 115.4's own-seat exclusion, and its own kind
            # rather than `target_player`, because that exclusion is the whole
            # difference: read as "target player" the card would let its caster
            # count their own graveyard.
            elif stream.accept_phrase("target", "opponent", "'s"):
                owner = ast.PlayerRef("target_opponent")
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
            # "…**with a single target**" (Reflecting Mirror; Deflection and
            # Divert print the same three words). CR 115.9a counts what the
            # object chose as it was put on the stack, so the phrase describes
            # a spell or an ability on the stack and nothing on a battlefield.
            # Read before the counter probe below, which opens on the same "a"
            # and resets cleanly either way.
            if stream.accept_phrase("a", "single", "target"):
                d.target_count = 1
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
            # "…**that doesn't have cumulative upkeep**" (Balduvian Shaman).
            # The relative-clause spelling of "without <keyword>" a few lines
            # up — the same restriction and the same field, because the
            # difference is Wizards' templating and nothing else. Read here so
            # the two printings cannot come to mean two things, and refusing
            # without consuming when the words behind it are not a keyword
            # list, so every other "that doesn't …" keeps failing on its own
            # words.
            elif stream.at_word("doesn't"):
                keyword_probe = stream.mark()
                stream.advance()
                if stream.accept_word("have"):
                    try:
                        d.without_keywords.extend(_parse_keyword_list(stream))
                        continue
                    except Exception:
                        pass
                stream.reset(keyword_probe)
                stream.reset(probe)
                break
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
            # "…that **blocked or were blocked by it this turn**" (Venomous
            # Breath). The two-way reading of the clause directly above: the
            # bound object stood on one side of a block and the sentence names
            # whichever creatures stood on the other, whichever side that was.
            # Its own field, not a widening of the one-way one — the set is
            # strictly larger, and a lowering written for "were blocked by"
            # answering this phrase would destroy creatures the card does not
            # name.
            #
            # "It" and "that creature" are one referent here and both are
            # admitted: this is the `that …` postmodifier run, whose subject is
            # the sentence's own object, so neither spelling can be read as the
            # ability's source. The present-participle relation
            # (`in_combat_with_source`, "blocking or blocked by it") is a
            # different production reached by a different first word, which is
            # what keeps the two "it"s apart.
            elif stream.accept_phrase("blocked", "or", "were", "blocked", "by"):
                probe = stream.mark()
                named_bound = stream.accept_word("it")
                if not named_bound and stream.accept_word("that"):
                    noun = stream.peek_word()
                    if noun is not None and _singular(noun) in CARD_TYPES:
                        stream.advance()
                        named_bound = True
                if named_bound and stream.accept_phrase("this", "turn"):
                    d.in_combat_with_bound_object = True
                    continue
                stream.reset(probe)
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
            # "…that **has been dealt damage this turn**" (Giant Shark). The
            # passive voice with no agent, which is the whole difference from
            # the clause above: that one asks who dealt it, this one only that
            # some damage was. Both halves required — a clause naming another
            # window is a different sentence, and the record is kept per turn.
            elif stream.accept_phrase("has", "been", "dealt", "damage"):
                if stream.accept_phrase("this", "turn"):
                    d.was_dealt_damage_this_turn = True
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
                # Alteration) / "…Auras you own **attached to permanents you
                # control**" (Remove Enchantments). Not a back-reference but a
                # noun phrase: what the attachment is on, asked of the
                # attachment itself. Read through the same noun-phrase parser
                # rather than by a word list here, and carried whole rather
                # than reduced to its card types — the seat in "permanents you
                # control" has nowhere to live in a tuple of types, and a
                # dropped seat on an Aura sweep is every Aura on the board.
                #
                # It is *carried* whole; whether it can be *tested* whole is
                # the lowering's question, asked of the nested payload by the
                # same key set that gates the outer one.
                nested = stream.mark()
                stream.accept_word("a", "an")
                try:
                    host = parse_filter(stream)
                except GrammarError:
                    host = None
                # Any narrowing at all is a host phrase; none at all is not.
                # "attached to a permanent" says only "attached", which the
                # filter already has a word for (``is_enchanted``) — and an
                # empty nested filter would read as "attached to anything",
                # widening the sweep to every Aura rather than narrowing it. So
                # the phrase has to have said *something*: "permanents you
                # control" says a seat, "a creature or land" says two types.
                if host is not None and host != ast.ObjectFilter():
                    d.attached_to_filter = host
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
            # "…**of an opponent's choice** they control" (Preacher). A
            # different fact from "of their choice" above and deliberately a
            # different field: that one says the seat already named picks, this
            # one names a seat that is not the ability's controller. Reading one
            # as the other would hand Preacher's pick to the Preacher's own
            # player, which is the opposite of what it prints.
            #
            # "They control" is read here rather than as a controller clause of
            # its own, because "they" is the opponent this phrase just named —
            # a pronoun naming the object the sentence already named (idiom 20),
            # and there is nowhere else in the phrase it could point.
            if stream.accept_phrase("an", "opponent", "'s", "choice"):
                d.chosen_by_opponent = True
                if stream.accept_phrase("they", "control"):
                    d.controller = "opponent"
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
