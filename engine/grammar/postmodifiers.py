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

#: "…other than **the creature tapped this way**" (Veteran's Voice). The
#: production above resolves it to the attached host, which is only the same
#: permanent while the ability's cost is the one that taps the host. Named
#: here so the production and the compiler's gate read one string rather
#: than two spellings of it.
COST_TAPPED_REFERENT = "the creature tapped this way"

from typing import Callable

from . import ast
from .amounts import accept_source_relative_comparison, parse_comparison
from .errors import GrammarError
from .lexer import PT, SELF
from .names import accept_original_expansion, parse_card_name
from .readers import (_SELF_NOUNS, _accept_back_referenced_controller,
                      _parse_keyword_list, accept_source_reference)
from .stream import TokenStream
from .zones import accept_zone_scope
from .vocabulary import CARD_TYPES, singular as _singular

# "…attached to that creature" / "…attached to it" — the trailing clause naming
# what an Aura or Equipment is on, and the referent each consumer resolves.
# Every consumer must answer every entry: a referent nothing resolves is a
# relation dropped, and a dropped relation on a sweep takes the whole board.
_ATTACHED_TO_REFERENTS = {("that", "creature"): "target", ("it",): "source"}



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
        # "you **own or control**" (Telim'Tor's Edict). Read beside the "both
        # own and control" branch above and before the bare "you control",
        # whose prefix it also is: matched there, "or control" would strand
        # "own" — and, worse, would compile the card as the strictly *smaller*
        # set, dropping the permanent an opponent has taken from you, which is
        # half of what this card is for.
        if stream.accept_phrase("you", "own", "or", "control"):
            d.owner_or_controller = "you"
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
        # "each creature **each opponent** controls" (Aku Djinn) — the
        # distributive spelling of the two above. CR 109.5 reads "opponent"
        # against the ability's controller, and "each opponent" names exactly
        # the set "your opponents" does, so it is the same filter key rather
        # than a third one: a quantifier over the seats is not a narrowing of
        # the objects. Kept beside its siblings so the three spellings of one
        # scope are read in one place.
        if stream.accept_phrase("each", "opponent", "controls"):
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
        # "Creatures **of the chosen type**" (An-Zerrin Ruins). The same
        # CR 614.1c choice one characteristic over — a creature type recorded
        # on the source as it entered — so it is its own filter key for the
        # colour's reason: the pure matcher has no source and refuses the key
        # outright, and the readers that do hold one resolve it into the
        # ordinary subtype key before matching.
        if stream.accept_phrase("of", "the", "chosen", "type"):
            # Which catalog the chosen word came from is spelled once, in the
            # **head noun**: "Each *land* of the chosen type" (Shimmer) is a
            # land type (CR 205.3i) and "*Creatures* of the chosen type"
            # (An-Zerrin Ruins) a creature type (CR 205.3m). The phrase itself
            # is identical, so reading it as one key would store Shimmer's
            # Desert under a creature type's name — and the two choices are
            # recorded separately on the source, which is what the reader
            # holding that source resolves them from.
            if "land" in d.card_types:
                d.chosen_land_type = True
            else:
                d.chosen_creature_type = True
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
        # "target creature **you cast this turn**" (Cycle of Life). A narrowing
        # of the noun phrase like the combat records above it, off a different
        # record: CR 701.5a's cast, stamped as the permanent entered. Not "you
        # control" and not "that entered this turn" — a creature you cast and
        # then gave away is still one you cast, and a reanimated one never was.
        if stream.accept_phrase("you", "cast", "this", "turn"):
            d.cast_by_you_this_turn = True
            continue
        # "destroy all Plains **that weren't chosen this way by any player**"
        # (Raiding Party). A narrowing of the noun phrase rather than an
        # exception clause on the verb, for the reason Season of the Witch's
        # pair above is: the sweep destroys exactly what the phrase names, and
        # an exclusion read anywhere else would have to be re-applied by every
        # verb that could carry it.
        #
        # "By any player" is the whole of what makes it one narrowing: the
        # choices were made by several seats over several iterations, and the
        # words ask about all of the answers at once — which is why the record
        # behind it accumulates instead of holding the last seat's pick.
        if stream.accept_phrase(
            "that", "weren't", "chosen", "this", "way", "by", "any", "player"
        ):
            d.not_chosen_this_way = True
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
        # "target creature **this creature is blocking**" (Wall of Corpses).
        # The same relation the pronoun spelling above names, written out — the
        # lexer collapses a card's own name to SELF, so "this creature" here is
        # the same referent "it" is under a self-scoped ability. Beside it and
        # not folded into it, because the two are different token runs and the
        # `accept_phrase` above consumes nothing when it fails.
        spelled_out = stream.mark()
        if stream.accept_word("this") and stream.accept_word(*_SELF_NOUNS):
            if stream.accept_word("is") and stream.accept_word("blocking"):
                d.blocked_by_source = True
                continue
        stream.reset(spelled_out)
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
        # "all creatures **banded with it**" (Icatian Skirmishers), "creatures
        # **banded with this creature**" (Camel). CR 702.22e's band, which is a
        # relation to the ability's own source rather than a state of the
        # creature described — so it is a relative filter field like
        # `blocked_by_source` above it. Both printed referents name the source:
        # the lexer has already collapsed a card's own name into SELF, and "it"
        # under a trigger whose subject is the source means the same object.
        banded = stream.mark()
        if stream.accept_phrase("banded", "with"):
            if stream.accept_word("it") or stream.accept_kind(SELF) is not None:
                d.banded_with_source = True
                continue
            if stream.accept_word("this") and stream.accept_word(*_SELF_NOUNS):
                d.banded_with_source = True
                continue
        stream.reset(banded)
        if stream.accept_phrase("that", "'s", "attacking", "you"):
            d.attacking_you = True
            continue
        # "target nonartifact, nonblack creature **that attacked you this
        # turn**" (Jabari's Influence). The past tense of the clause above and
        # a different question: that one reads the live combat relation, this
        # one a record the declaration wrote — and the card printing it may
        # only be cast *after* combat, where the live relation has been reset.
        # Read beside its present-tense twin rather than under the general
        # "that attacked this turn" below, whose prefix it is.
        if stream.accept_phrase("that", "attacked", "you", "this", "turn"):
            d.attacked_you_this_turn = True
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
            # "target creature **other than enchanted creature**" (Kjeldoran
            # Pride). Not ``other_than_source``: the Aura is the source, and
            # excluding *it* from a set of creatures excludes nothing at all —
            # an Aura is not a creature, so the restriction would read as
            # satisfied by every creature on the board including the one the
            # card names. Its own field, tested by ``subject_matches`` off the
            # attachment record.
            elif stream.accept_phrase("than", "enchanted"):
                noun = stream.peek_word()
                if noun is not None:
                    stream.advance()
                    d.other_than_attached_host = True
                    continue
            # "target creature **other than the creature tapped this way**"
            # (Veteran's Voice). The referent is whatever this ability's *cost*
            # taps, and the only cost in this engine that taps a named permanent
            # is "Tap enchanted creature" — so the phrase resolves to the
            # attached host, the same field the sentence beside it reads.
            #
            # It cannot be answered off the cost-tap record
            # (``engine/cost_tap_records.py``), which is what Vodalian War
            # Machine's "tapped this turn to pay for its abilities" reads:
            # CR 601.2h pays costs **after** targets are chosen, so at
            # announcement that record is still empty and the picker would
            # cheerfully offer the very creature the card excludes — then fizzle
            # at resolution, once the record had filled in. A picker and an
            # enforcement disagreeing about one list is the failure
            # ``legality.activation_target_refusal`` exists to prevent.
            #
            # Resolving the pronoun to the host is only true while the cost is
            # the one that taps it, which no filter can check. The compiler
            # checks it instead, where the cost and the effect are both in
            # hand — see ``COST_TAPPED_REFERENT`` below and its reader in
            # ``oracle._parse_activated_ability``.
            elif stream.accept_phrase(
                "than", "the", "creature", "tapped", "this", "way",
            ):
                d.other_than_attached_host = True
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
        # "the number of green creatures **on the battlefield**" (An-Havva
        # Constable, An-Havva Inn). Not one of ``_ZONE_NOUNS`` and deliberately
        # not added to them: CR 403.1 makes the battlefield one shared zone,
        # ``zone`` already says "battlefield", and consuming the words into it
        # would leave no trace that they were read — which is the exact silent
        # drop that set's docstring refuses. So they set a field of their own,
        # and what that field records is the *scope*: the set is scoped to
        # nobody. That is not the same as saying nothing, because a count whose
        # filter names no controller is taken on the caster's own board.
        if stream.accept_phrase("on", "the", "battlefield"):
            d.on_the_battlefield = True
            continue
        # "from your graveyard" / "in an opponent's graveyard" — which zone the
        # objects are in, and whose. Both halves are one answer (CR 404.1), and
        # they left for `zones` at the size guard; the loop's three outcomes ride
        # the return value.
        scoped = accept_zone_scope(stream, d)
        if scoped is True:
            continue
        if scoped is False:
            break
        if stream.at_word("with"):
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("power"):
                # "…with power **equal to or greater than the enchanted
                # creature's toughness**" (Ironclaw Curse). Tried before the
                # printed-number bound, and it declines without consuming, so
                # every phrase that reading already took is untouched: the two
                # are told apart by the word after the characteristic, not by
                # one of them failing.
                relative = accept_source_relative_comparison(stream, "power")
                if relative is not None:
                    d.characteristic_vs_source = relative
                    continue
                d.power = parse_comparison(stream)
                continue
            if stream.accept_word("toughness"):
                relative = accept_source_relative_comparison(stream, "toughness")
                if relative is not None:
                    d.characteristic_vs_source = relative
                    continue
                d.toughness = parse_comparison(stream)
                continue
            # "…**with a name originally printed in the <Set> expansion**"
            # (Apocalypse Chime, Golgothian Sylex). Read before the two "a …"
            # probes below, which open on the same article and reset cleanly
            # either way. An expansion the manifest does not know refuses
            # without consuming, so the line fails loudly rather than sweeping
            # the set the reader guessed.
            expansion_probe = stream.mark()
            expansion = accept_original_expansion(stream)
            if expansion is not None:
                d.original_expansion = expansion
                continue
            stream.reset(expansion_probe)
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
            # "…all creatures **that blocked this creature this turn**"
            # (Joven's Ferrets). The active voice of the passive clause above,
            # with the ability's own source as the referent — so it sets its
            # own field rather than either of theirs: which object the block
            # record is read against decides which permanent the sweep names,
            # and one field meaning either would leave the matcher guessing.
            #
            # Read *after* "blocked or were blocked by", whose first word this
            # is: tried first it would take the word and strand the "or".
            # "This turn" is required for that clause's reason — the record is
            # kept per turn, and a clause naming another window is a different
            # sentence.
            elif stream.at_word("blocked"):
                blocked_probe = stream.mark()
                stream.advance()
                if accept_source_reference(stream) and stream.accept_phrase(
                    "this", "turn"
                ):
                    d.blocked_source_this_turn = True
                    continue
                stream.reset(blocked_probe)
                stream.reset(probe)
                break
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
        # "…**blocking or [being] blocked by this creature**" (Sentinel, the
        # noun-phrase half of Abu Ja'far's sentence, Sworn Defender) is the
        # two-sided relation to the ability's own source (CR 509) — never a
        # payload key: the lowering written for it carries the relation itself
        # and every other one refuses it. "Being" is English, not a second
        # relation, so it is an optional word rather than a second branch.
        if stream.at_word("blocking") and stream.peek_word(1) == "or":
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("or"):
                stream.accept_word("being")
                if stream.accept_phrase("blocked", "by") and accept_source_reference(stream):
                    d.in_combat_with_source = True
                    continue
            stream.reset(probe)
            break
        # "…with flying **blocked by this creature**" (Whip Vine): the passive
        # voice of "target creature **it's blocking**" (Goblin Snowman) above,
        # one relation printed from either end, so it sets that same field
        # rather than a second one every matcher must remember to test. The
        # "that …" clauses further down read a *history* off a record; both of
        # these read the live combat fact.
        if stream.at_word("blocked") and stream.peek_word(1) == "by":
            probe = stream.mark()
            stream.advance(2)
            if accept_source_reference(stream):
                d.blocked_by_source = True
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
                # "…attached to **Hakim**" (Hakim, Loreweaver) — the card
                # naming itself where the table above reads "it". The lexer has
                # already collapsed the name to one SELF token, so the two
                # spellings are one referent and the *general* defect is that
                # only the pronoun was listed: any card printing "attached to
                # <its own name>" refused its whole line on unconsumed text.
                # Read through ``accept_source_reference``, which is the one
                # production for the three spellings ("it", "this <noun>", the
                # name) — a fourth word list here would be a second answer to
                # "does this phrase name the source?".
                #
                # It sits below the table and above the noun-phrase branch,
                # which is what "this creature" needs: the noun parser reads it
                # as an *ObjectFilter* whose ``is_source`` the payload then drops
                # — an attachment sweep over every creature on the board rather
                # than over the source.
                if accept_source_reference(stream):
                    d.attached_to = "source"
                    continue
                # "…attached to **target permanent you own**" (Scarab of the
                # Unseen). The host as a chosen object rather than as a
                # back-reference: the same relation the table above reads, with
                # the spell picking the host itself instead of pointing at
                # something an earlier clause picked. Read here rather than
                # through ``references.parse_target_spec`` for the reason
                # ``_accept_back_referenced_controller`` is read inline — that
                # module sits two layers above this one, so the recursion has to
                # run the other way — and the word is the whole of what it adds:
                # everything after it is the ordinary noun phrase.
                chosen = stream.mark()
                if stream.accept_word("target"):
                    try:
                        host_target = parse_filter(stream)
                    except GrammarError:
                        host_target = None
                    # A phrase that narrowed nothing would make the picker offer
                    # every permanent on the board, which is not what any card
                    # printing this says; the nested branch below refuses an
                    # empty filter for the same reason.
                    if host_target is not None and host_target != ast.ObjectFilter():
                        d.attached_to_target = host_target
                        continue
                stream.reset(chosen)
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
