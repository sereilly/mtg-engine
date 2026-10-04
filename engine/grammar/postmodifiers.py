"""The trailing half of a noun phrase: everything printed **after** the head.

"creature **other than this creature**", "creature **blocking target attacking
creature**", "Equipment **attached to that creature**", "creature **that isn't
enchanted**". Split from `nouns` because that module had grown to 967 lines
around a single 795-line `parse_object_filter`, and this is the half that
grows: a new printed restriction is nearly always a postmodifier.

The two halves are genuinely different readings. Leading adjectives narrow the
*kind* of object — colour, type, state — and each is one word tested against a
vocabulary. A postmodifier names a **relation**: to the controller, to another
object the sentence names, to a zone. That is why this file recurses and the
adjective loop does not.

**That list was never the whole of it, and four of the loop's questions are now
answered one layer down.** Each left with this file at or near the
thousand-line guard, along the line the sentence above draws or fails to draw.
The seat and ownership readings that open the loop ("you control", "an
opponent owns") went to `seat_relations` and the zone scope to `zones` — the
two ends of the list. A **record** of something that already happened ("that
attacked this turn") went to `histories`, which calls it the fourth relation
the list does not name. And at Invasion's Phase 0 the "with …" clause and its
"without" went to `with_clauses`: not a relation at all but what the object
itself *has* — "with flying", "with power 3 or greater" — and the branch that
had grown most. All four are floors this loop calls at the position their
branch always held, and none reads back.

What stays is the middle of the list and the loop around it: the relation to
another object — the ability's own source ("other than this creature", "banded
with it"), the other end of a live block, an attachment's host, a seat or a
target an earlier clause chose — with the "that …" relative clause, the printed
exemptions, and the single branches that are not a run of anything ("named …",
"of their choice", "on the battlefield"). The order they are tried in is the
other thing this file owns, and it is load-bearing: a branch that opens and
cannot finish restores the cursor and **ends** the scan, so one tried too early
takes the phrase away from the reading behind it.

**The recursion arrives as a parameter.** "blocking target attacking creature"
contains a whole nested phrase, so this file needs `parse_object_filter` — which
lives one layer up. Taking it as *parse_filter* rather than importing it keeps
the dependency running one way, the same inversion `lowering/where_x.py` makes
for the same reason — and `histories` and `with_clauses` are handed it on from
here, because each reads a nested phrase of its own.

Everything both halves accumulate lives on the `_FilterDraft` they share; see
its docstring in `filter_draft`, where it has lived since it left `nouns`.
"""

from __future__ import annotations

#: "…other than **the creature tapped this way**" (Veteran's Voice). The
#: production below resolves it to the attached host, which is only the same
#: permanent while the ability's cost is the one that taps the host. Named
#: here so the production and the compiler's gate read one string rather
#: than two spellings of it.
COST_TAPPED_REFERENT = "the creature tapped this way"

from typing import Callable

from . import ast
from .errors import GrammarError
from .histories import accept_history_relation, accept_relative_clause_history
from .lexer import SELF
from .names import parse_card_name
from .readers import (_SELF_NOUNS, _accept_back_referenced_controller,
                      _parse_keyword_list, accept_source_reference)
from .seat_relations import accept_seat_relation
from .stream import TokenStream
from .with_clauses import accept_with_clause
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
        # Whose is it — the seat and ownership readings, in
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
        # "Destroy all creatures **except for Mageta**" (Mageta the Lion): the
        # exemption names the ability's own source, which is "all other
        # creatures" in another word order — the same field.
        if stream.accept_phrase("except", "for") and accept_source_reference(stream):
            d.other_than_source = True
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
            # hand — see ``COST_TAPPED_REFERENT`` above and its reader in
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
        # "with flying", "with power 3 or greater", "with a +1/+1 counter on
        # it", "without flying" — what the object described **has**, which is
        # none of the relations this file's docstring lists and was the loop's
        # single largest branch. It left for `with_clauses` at Invasion's
        # Phase 0 (see that module); the three outcomes ride the return value,
        # exactly as the zone scope's do one branch up.
        had = accept_with_clause(stream, d, parse_filter)
        if had is True:
            continue
        if had is False:
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
            # The relative-clause spelling of "without <keyword>", which
            # `with_clauses` reads — the same restriction and the same field,
            # because the difference is Wizards' templating and nothing else.
            # Both go through the one keyword-list reader so the two printings
            # cannot come to mean two things, and this one stays an arm of the
            # "that …" chain it is printed in. It refuses without consuming
            # when the words behind it are not a keyword list, so every other
            # "that doesn't …" keeps failing on its own words.
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
