"""What a noun phrase says its object **has**: the "with …" clause, and "without".

"creature **with flying**", "creature **with power 3 or greater**", "permanent
**with a bounty counter on it**", "spell **with a single target**", "creature
**with the least toughness**", "creature **without flying**". Every reading here
opens on one of those two words, and what it asks is always a fact about the
object the phrase describes — an ability it has, its power, toughness or mana
value against a bound, a counter on it, its name, how many targets it chose —
and never who controls it, what it is fighting or where it is.

That is neither of the two readings `postmodifiers`' docstring names. It is not
a leading adjective, which "is one word tested against a vocabulary": a bound
takes an amount, a superlative a whole comparison set. And it is not one of the
*relations* that file lists — "to the controller, to another object the
sentence names, to a zone". Several arms here do measure against something else
("with power equal to or greater than the enchanted creature's toughness", "with
lesser power", "with the greatest power among creatures on the battlefield"),
but what is measured is the described object's own, and the other end only says
how much. `histories` found a fourth thing that sentence does not list and this
is the fifth; it sat in the middle of `_parse_postmodifiers`' loop as its single
largest branch.

Pre-split off `postmodifiers.py` at Invasion's Phase 0, when that module stood
32 lines under the thousand-line guard with eight groups about to open — the
shared-module case SET_PLAYBOOK.md says to pre-split rather than to brief. The
cut is the half that grows, and that was measured rather than assumed. Since
`histories` left at Tempest the live combat relations, "attached to …", "of …"
and the controller and zone branches have not gained a line between them, while
this run gained more than any other branch — 57 of the 149 lines that module
has added and kept, for the comparative, the superlative, the chosen ability,
protection and a third name comparison. And 57 undercounts it: at Urza's Saga
the run had already outgrown the file once, and gave the hidden-zone bound to
`bounds` and the protection reader to `readers`. A set adds a way to say what
an object *has* far more often than a new relation for it to be in.

**One function with three answers**, the contract `zones.accept_zone_scope` has
one branch earlier in the same loop: the caller's loop always had three
outcomes at this branch — `continue`, `break`, and fall through — and both words
keep all three. A floor rather than a family, the shape `seat_relations` and
`histories` are: `postmodifiers` reads this and it reads nothing
back. It sits directly under that module and above `bounds` and `names`, where
the readers of a bound and of a name comparison already live — the arms here
are mostly the *order* those readers are tried in, and the order is
load-bearing: nearly every one opens on a word a later one would take apart ("a
single target" against "a … counter on it", "mana value" and "protection from"
against the keyword list that ends the chain), so an arm that does not find its
own opening words leaves the cursor where it was and the keyword list goes last.

**The recursion arrives as a parameter here too.** "…with the greatest power
**among creatures on the battlefield**" nests a whole noun phrase, so the
superlative needs `nouns.parse_object_filter`, two layers up; it is handed down
through `postmodifiers` as *parse_filter*, for the reason that module takes it
that way.

**One spelling of "without" stayed behind.** "…that doesn't have cumulative
upkeep" (Balduvian Shaman) writes the same field the bare word does, but it is
an arm of `postmodifiers`' "that …" relative clause and is reached only after
that clause's "that" has been consumed, so it could not come without a second
call site in the middle of an `elif` chain.

No mirror name to reuse. Nothing on the lowering side is about this clause —
`ast/_payloads.py` writes every field of an `ObjectFilter` alike, and
`lowering/_filters.py` asks of all of them together which ones a handler
honours — and `characteristics`, the word CR 109.3 would suggest, is taken
three times over (`ast/`, `effects/`, `lowering/`) for the effects that
*change* one, besides being wrong about part of what is read here: that rule's
list holds neither the counters on an object nor how many targets it chose, and
"any other information about an object isn't a characteristic". The name is
the one the fields themselves carry — ``with_keywords``, ``without_keywords``,
``with_named_counter``, ``with_plus1_counter``, ``with_protection_from`` on the
draft, the filter and the payload alike.
"""

from __future__ import annotations

from .amounts import (accept_counter_kind, accept_counters_on_it_bound,
                      accept_source_counter_bound)
from .bounds import (accept_cards_in_hand_bound,
                     accept_comparative_characteristic,
                     accept_source_relative_comparison, accept_superlative,
                     parse_comparison)
from .lexer import PT
from .names import accept_name_comparison, accept_original_expansion
from .readers import _parse_keyword_list, _protection_quality
from .stream import TokenStream


def accept_with_clause(stream: TokenStream, d, parse_filter) -> bool | None:
    """Read one "with …" or "without …" clause onto *d*, if one is here.

    True when a clause was read and the postmodifier loop should carry on;
    False when the cursor is at one of the two words and nothing behind it is
    a reading this knows — the cursor is put back in front of the word and the
    loop must stop; None when the cursor was at neither word and nothing was
    looked at.

    Three answers rather than two for `zones.accept_zone_scope`'s reason: the
    caller's loop has three outcomes here and always did. Collapsing the last
    two would let a "with …" this cannot finish fall into the branches behind
    it with the word still unread.

    Not every failure is a False. An arm that has committed to its reading —
    "with power" followed by something `parse_comparison` cannot read — raises
    `GrammarError` out of the whole noun phrase, as it did before the split.

    *parse_filter* is ``nouns.parse_object_filter``, handed on from
    `postmodifiers` rather than imported: the superlative's "among …" set is a
    whole noun phrase, and that parser is two layers up.
    """
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
            return True
        if comparison == "event":
            d.name_from_event = True
            return True
        # "…**with the same name as that card**" (Assembly Hall) — the
        # card an earlier step of this same effect revealed, which is a
        # different place to look than the firing event's object above.
        if comparison == "recorded":
            d.name_from_recorded_card = True
            return True
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
        superlative = accept_superlative(stream, parse_filter=parse_filter)
        if superlative is not None:
            d.superlative = superlative
            return True
        comparative = accept_comparative_characteristic(stream)
        if comparative is not None:
            d.characteristic_vs_source = comparative
            return True
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
                return True
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
                return True
            hand_bound = accept_cards_in_hand_bound(stream)
            if hand_bound is not None:
                d.power_greater_than_cards_in_hand = hand_bound
                return True
            d.power = parse_comparison(stream)
            return True
        if stream.accept_word("toughness"):
            relative = accept_source_relative_comparison(stream, "toughness")
            if relative is not None:
                d.characteristic_vs_source = relative
                return True
            d.toughness = parse_comparison(stream)
            return True
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
            return True
        stream.reset(expansion_probe)
        # "…**with a single target**" (Reflecting Mirror; Deflection and
        # Divert print the same three words). CR 115.9a counts what the
        # object chose as it was put on the stack, so the phrase describes
        # a spell or an ability on the stack and nothing on a battlefield.
        # Read before the counter probe below, which opens on the same "a"
        # and resets cleanly either way.
        if stream.accept_phrase("a", "single", "target"):
            d.target_count = 1
            return True
        # "with a +1/+1 counter on it" (Tempered Veteran), "with a
        # **bounty** counter on it" (Bounty Hunter), "with **magnet
        # counters** on them" (Magnetic Web).
        #
        # **One production, three printings, and two of them arrived in one
        # wave from two groups.** The singular and the plural are the same
        # restriction — "creatures with magnet counters on them" describes
        # each creature carrying at least one, not a board carrying several
        # — so reading them in two branches would be two readers of one
        # phrase, which is the fork `postmodifiers` — where this branch was
        # written — had already been split for once. The article is the only
        # other difference and the plural simply drops it.
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
                return True
        else:
            kind = accept_counter_kind(stream)
            if kind is not None and stream.accept_word(
                "counter", "counters"
            ) and (
                stream.accept_phrase("on", "it")
                or stream.accept_phrase("on", "them")
            ):
                d.with_named_counter = kind.text
                return True
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
                return True
            # "…**equal to the number of age counters on this
            # enchantment**" (Wave of Terror). The same shape read off the
            # ability's own source instead, and read here for the reason
            # the one above is: `parse_comparison` opens with an amount and
            # would fail on "equal".
            source_counters = accept_source_counter_bound(stream)
            if source_counters is not None:
                d.mana_value_equals_source_counters = source_counters
                return True
            # "…**equal to that number**" / "…**equal to the number**" (Void,
            # which prints both). The number a "Choose a number." sentence in
            # front of this one recorded — read here for the reason the two
            # bounds above are, and never when "of" follows: "equal to the
            # number of <things>" is a count, which is `parse_comparison`'s.
            chosen_probe = stream.mark()
            if stream.accept_phrase("equal", "to") and (
                stream.accept_phrase("that", "number")
                or stream.accept_phrase("the", "chosen", "number")
                or stream.accept_phrase("the", "number")
            ) and not stream.at_word("of"):
                d.mana_value_equals_chosen_number = True
                return True
            stream.reset(chosen_probe)
            d.mana_value = parse_comparison(stream)
            return True
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
            return True
        protection_probe = stream.mark()
        if stream.accept_phrase("protection", "from"):
            word = stream.peek_word()
            if word is not None and _protection_quality(word) is not None:
                stream.advance()
                d.with_protection_from = word
                return True
        stream.reset(protection_probe)
        try:
            d.with_keywords.extend(_parse_keyword_list(stream))
            return True
        except Exception:
            stream.reset(probe)
            return False
    if stream.at_word("without"):
        probe = stream.mark()
        stream.advance()
        try:
            d.without_keywords.extend(_parse_keyword_list(stream))
            return True
        except Exception:
            stream.reset(probe)
            return False
    return None
