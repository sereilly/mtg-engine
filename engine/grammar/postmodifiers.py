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
from .amounts import (accept_counter_kind, accept_counters_on_it_bound,
                      accept_source_counter_bound)
from .bounds import (accept_cards_in_hand_bound,
                     accept_comparative_characteristic,
                     accept_source_relative_comparison, accept_superlative,
                     parse_comparison)
from .errors import GrammarError
from .histories import accept_history_relation, accept_relative_clause_history
from .lexer import PT, SELF
from .names import accept_name_comparison, accept_original_expansion, parse_card_name
from .readers import (_SELF_NOUNS, _accept_back_referenced_controller,
                      _parse_keyword_list, _protection_quality,
                      accept_source_reference)
from .seat_relations import accept_seat_relation
from .stream import TokenStream
from .zones import accept_zone_scope
from .vocabulary import singular as _singular


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
        # Whose is it — the ten seat and ownership readings, in
        # `seat_relations` since Weatherlight's Phase 0 (see that file). Tried
        # first because the loop always tried them first, and the branch left
        # between them below opens on a word none of them does.
        if accept_seat_relation(stream, d):
            continue
        # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the
        # object is colored — matching reads the effective colors, so a
        # colorless artifact escapes and a Lace-painted one does not.
        if stream.accept_phrase("that", "'s", "one", "or", "more", "colors"):
            d.colored = True
            continue
        # The six clauses that narrow a noun phrase by a **record** of
        # something that already happened — an attack declaration, a block, a
        # cast, a pick a resolution has already made — rather than by
        # anything a matcher could see on the board. They left for
        # `histories` at Tempest's Phase 0; that module says why a history is
        # none of the three relations this file's docstring names.
        if accept_history_relation(stream, d):
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
        # "…**except for basic lands**" (Eye of Singularity). The third
        # printed exemption here and the first about a card's type rather than
        # about what it did. One field with "other than a basic land" below:
        # this card names one set in two word orders.
        if stream.accept_phrase("except", "for", "basic", "lands"):
            d.excluded_basic_lands = True
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
        # "all creatures **attacking you**" (Watchdog). The participle spelling
        # of the relative clause above, setting the same field: two printings
        # of one relation, and a second field would be a second thing every
        # matcher has to remember to test. Only the "you" form is read here --
        # a bare trailing "attacking" is already the *leading* adjective the
        # noun parser takes ("attacking creature"), and reading it in both
        # positions would let a noun phrase swallow the participle of a verb
        # the sentence still needs.
        if stream.accept_phrase("attacking", "you"):
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
            # "blocking **enchanted creature**" (Coils of the Medusa). The
            # Aura's own attachment, which is neither the source nor anything
            # this sentence chooses: the source *is* the Aura, and an Aura is
            # not in combat, so reading these words as `blocking_source` would
            # make the set empty on every board.
            #
            # Read before the "target" branch below rather than folded into it
            # for `blocking_source`'s reason one branch up: an attachment is
            # named by a record, not by a noun phrase, and there is nothing to
            # recurse into.
            if stream.accept_word("enchanted"):
                noun = stream.peek_word()
                if noun is not None:
                    stream.advance()
                    d.blocking_attached_host = True
                    continue
                stream.reset(probe)
                break
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
            # "a permanent **other than a basic land**" (Eye of Singularity).
            # Not one permanent excluded by identity like the readings around
            # it — a *class*, named by the pair (CR 205.4a's Basic supertype
            # and the land card type).
            elif stream.accept_phrase("than", "a", "basic", "land"):
                # "…a card **other than a basic land card**" (Lobotomy, Booby
                # Trap). The same class named with the head noun repeated, which
                # is how the phrase is printed wherever the *outer* noun is
                # "card" rather than "permanent" — one word, accepted and
                # dropped, because it restates the noun the phrase already has
                # rather than narrowing anything further.
                stream.accept_word("card")
                d.excluded_basic_lands = True
                continue
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
            # "…**with the same name as another permanent**" (Eye of
            # Singularity) and "…**with that name**" (its second line). Read
            # by `names`, one layer down, for the reason
            # `accept_original_expansion` below is: a name comparison is about
            # a literal rather than about a type line. Tried first because both
            # open on words the probes below would take apart, and each
            # consumes its whole phrase or nothing.
            comparison = accept_name_comparison(stream, tuple(d.card_types))
            if comparison == "another":
                d.shares_name_with_another = True
                continue
            if comparison == "event":
                d.name_from_event = True
                continue
            # "…with **lesser power**" (No Quarter). A bound stated against the
            # other object the sentence is about, with no number and no
            # possessive — so it opens on the *adjective* rather than on the
            # characteristic and is tried before the branches that expect the
            # characteristic first. Declines without consuming, so every other
            # "with …" phrase keeps its own reading.
            # "…**with the least toughness**" (Purging Scythe), "…**with the
            # greatest mana value**" (Tariff, Juxtapose). Read before every
            # bound below because it opens on the article rather than on a
            # characteristic, and because what it names is not a bound at all:
            # a superlative picks one object out of the set the rest of the
            # phrase describes, so the payload key it emits is one no matcher
            # answers (see ``ast.Superlative``). Declines without consuming.
            superlative = accept_superlative(stream)
            if superlative is not None:
                d.superlative = superlative
                continue
            comparative = accept_comparative_characteristic(stream)
            if comparative is not None:
                d.characteristic_vs_source = comparative
                continue
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
                # "…**less than or equal to the number of treasure counters on
                # this enchantment**" (Legacy's Allure). A count on the
                # ability's own source rather than a printed number, so it is
                # its own field for the reason the mana-value pair below are
                # two: `parse_comparison` reads an `Amount`, and an amount is
                # answered from the effect's context rather than from whichever
                # permanent the matcher is looking at. Read before that parser,
                # whose "less than" branch would consume the words and then
                # fail on "the".
                source_counters = accept_source_counter_bound(
                    stream, comparison=("less", "than", "or", "equal", "to"),
                )
                if source_counters is not None:
                    d.power_at_most_source_counters = source_counters
                    continue
                hand_bound = accept_cards_in_hand_bound(stream)
                if hand_bound is not None:
                    d.power_greater_than_cards_in_hand = hand_bound
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
            # "with a +1/+1 counter on it" (Tempered Veteran), "with a
            # **bounty** counter on it" (Bounty Hunter), "with **magnet
            # counters** on them" (Magnetic Web).
            #
            # **One production, three printings, and two of them arrived in one
            # wave from two groups.** The singular and the plural are the same
            # restriction — "creatures with magnet counters on them" describes
            # each creature carrying at least one, not a board carrying several
            # — so reading them in two branches would be two readers of one
            # phrase, which is the fork this file has already been split for
            # once. The article is the only other difference and the plural
            # simply drops it.
            #
            # Two *fields*, though: CR 122.1a's +1/+1 counter has rules meaning
            # (layer 7d, ``engine/pt.py``'s channel, the ``plus_counters``
            # record) where every other kind CR 122.1 admits is an inert marker
            # in ``engine/named_counters.py``'s open store. Where the answer is
            # looked up is the matcher's business, not the parser's.
            #
            # This branch used to accept the +1/+1 kind alone, "because the
            # counters the engine records under another name have no matcher".
            # That refusal has expired — ``with_named_counter`` is in
            # ``TESTABLE_SUBJECT_FILTER_KEYS`` with ``counters_on`` behind it —
            # and a kind nothing can answer still fails loudly, one layer down
            # at the key check.
            counter_probe = stream.mark()
            stream.accept_word("a", "an")
            token = stream.peek()
            if token is not None and token.kind == PT and token.text == "+1/+1":
                stream.advance()
                if stream.accept_word("counter", "counters") and (
                    stream.accept_phrase("on", "it")
                    or stream.accept_phrase("on", "them")
                ):
                    d.with_plus1_counter = True
                    continue
            else:
                kind = accept_counter_kind(stream)
                if kind is not None and stream.accept_word(
                    "counter", "counters"
                ) and (
                    stream.accept_phrase("on", "it")
                    or stream.accept_phrase("on", "them")
                ):
                    d.with_named_counter = kind.text
                    continue
            stream.reset(counter_probe)
            # "with mana value X" (Spell Blast). Two words, so it is tried
            # before the keyword list — "mana" alone is not a keyword, but
            # leaving the phrase unmatched would strand "value X" and fail the
            # whole line rather than restricting the noun phrase.
            if stream.accept_phrase("mana", "value"):
                # "…**less than or equal to the number of rust counters on
                # it**" (Corrosion). A bound that is a characteristic of the
                # object being tested rather than a number, which is why it is
                # its own field: `parse_comparison` reads an `Amount`, and an
                # amount is answered from the effect's context and not from
                # whichever permanent the matcher happens to be looking at.
                # Read before the ordinary comparison, whose "less than" branch
                # would otherwise consume the words and then fail on "the".
                counters = accept_counters_on_it_bound(stream)
                if counters is not None:
                    d.mana_value_at_most_counters = counters
                    continue
                # "…**equal to the number of age counters on this
                # enchantment**" (Wave of Terror). The same shape read off the
                # ability's own source instead, and read here for the reason
                # the one above is: `parse_comparison` opens with an amount and
                # would fail on "equal".
                source_counters = accept_source_counter_bound(stream)
                if source_counters is not None:
                    d.mana_value_equals_source_counters = source_counters
                    continue
                d.mana_value = parse_comparison(stream)
                continue
            # "…**with protection from white**" (Escaped Shapeshifter). Read
            # before the keyword list below, which matches "protection" on its
            # own and then strands "from white" — the whole line failing on a
            # phrase whose first word it had already taken.
            #
            # The quality, not the word: `keywords.protection_quality` is the
            # one reader of what a protection clause names, and it is the same
            # one `_protection_qualities` answers the board with — so a phrase
            # naming a quality the shield reader cannot model refuses here
            # rather than describing a set nothing is ever in.
            # "target creature **with the chosen ability**" (Phyrexian
            # Splicer). Read before the keyword list for the protection
            # branch's reason: "the" is not a keyword, so the list would refuse
            # and take the whole line with it — which is the `expected a
            # subject` this phrase refused with for two waves.
            if stream.accept_phrase("the", "chosen", "ability"):
                d.chosen_keyword = True
                continue
            protection_probe = stream.mark()
            if stream.accept_phrase("protection", "from"):
                word = stream.peek_word()
                if word is not None and _protection_quality(word) is not None:
                    stream.advance()
                    d.with_protection_from = word
                    continue
            stream.reset(protection_probe)
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
            # "…**that isn't enchanted**" (Time Elemental). CR 303.4a: a
            # permanent is enchanted while an Aura is attached to it, so this is
            # a question about the candidate alone and the pure matcher answers
            # it. An Equipment attached to the same permanent does *not* make it
            # enchanted, which is why the matcher asks for the Aura subtype
            # rather than for the attachment record this engine shares between
            # the two (CR 301.5f).
            #
            # **"aren't" is the same clause about a plural head noun** — "all
            # creatures **that aren't enchanted**" (Winds of Rath). The number
            # of the verb is agreement with the noun the postmodifier is
            # attached to and says nothing about the restriction, so the two
            # spellings are one branch rather than two: split, the plural half
            # would be an unread relative clause on every sweep in the pool
            # while the singular half went on working, and nothing would fail.
            elif stream.accept_phrase("isn't", "enchanted") or stream.accept_phrase(
                "aren't", "enchanted"
            ):
                d.not_enchanted = True
                continue
            # "…**that are enchanted**" (Song of Serenity). The exact positive
            # of the clause above, and it sets ``enchanted_only`` rather than
            # ``is_enchanted``: this is a *restriction* on any candidate — every
            # creature with an Aura on it — where ``is_enchanted`` is the
            # referent an Aura's own line uses to name the one permanent it is
            # attached to. ``_references.py`` spells out that the two are
            # different questions, and a phrase read as the referent on an
            # enchantment that is not an Aura names nothing at all.
            #
            # Both verb numbers for the negative branch's reason: the agreement
            # is with the head noun and says nothing about the restriction, so
            # splitting them would leave one spelling silently unread.
            elif stream.accept_phrase("is", "enchanted") or stream.accept_phrase(
                "are", "enchanted"
            ):
                d.enchanted_only = True
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
            # "…**that targets a permanent you control**" (Avoid Fate, Ring
            # of Immortals). What the object *chose*, which is a question only
            # a spell or an ability on the stack can be asked — so the inner
            # noun phrase is parsed in full and recorded whole, and every
            # lowering not written for it refuses the field by name.
            elif stream.accept_word("targets"):
                stream.accept_word("a", "an")
                d.targets_object = parse_filter(stream)
                continue
            # The eight arms of this clause that read a **record** — a block, a
            # damage event, or a turn's worth of either — rather than the
            # object's own characteristics. They left for `histories` at
            # Tempest's Phase 0 (see that module) and stay the tail of this
            # chain rather than a branch of their own: an arm that opens and
            # then fails takes no later one, there exactly as here.
            elif accept_relative_clause_history(stream, d, parse_filter):
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
        if stream.at_word("put"):
            # "…creature **put onto the battlefield with this enchantment**"
            # (Diabolic Servitude). The permanent this one's own ability
            # reanimated, read off a record the reanimation stamps — beside
            # ``created with`` below it and for that phrase's reason exactly:
            # what it names is a fact about the object's history, and CR 400.7
            # makes the arrival a new object with nothing on the board to say
            # where it came from.
            probe = stream.mark()
            stream.advance()
            if stream.accept_phrase(
                "onto", "the", "battlefield", "with"
            ) and accept_source_reference(stream):
                d.put_onto_battlefield_by_source = True
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
        if stream.at_word("not"):
            # "…a creature with flying **not named Escaped Shapeshifter**"
            # (Escaped Shapeshifter). The negative of the `named` branch below,
            # and it arrives in **two spellings** of the same reference. The
            # grammar reads the card's own name as a SELF token (the lexer
            # collapsed it); `oracle._restriction_line` has already rewritten it
            # to "this creature" by the time the derivation tables see the line.
            # One field for both, because they are one phrase: two would be two
            # readings of a card excluding itself, free to disagree.
            #
            # A *name*, never an identity — a second copy of the card is
            # excluded too (CR 201.2), which is what the card means and what
            # `exclude_self` would get wrong.
            probe = stream.mark()
            stream.advance()
            if stream.accept_word("named"):
                token = stream.peek()
                if token is not None and token.kind == SELF:
                    stream.advance()
                    d.not_named_source = True
                    continue
                self_probe = stream.mark()
                if stream.accept_word("this"):
                    noun = stream.peek_word()
                    if noun is not None and _singular(noun) in _SELF_NOUNS:
                        stream.advance()
                        d.not_named_source = True
                        continue
                stream.reset(self_probe)
                try:
                    d.not_named = parse_card_name(stream)
                    continue
                except GrammarError:
                    pass
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
