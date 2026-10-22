"""A triggered ability's condition, read off its printed line (CR 603.1).

The condition half of a trigger: a regex table names the *event* — the
condition kind a dispatcher is addressed by — and the front ends read the
effect behind it (``engine/front_ends.py``). :func:`trigger_condition_of_line`
is the one reading of a line, and everything that asks "what condition does
the table see here?" asks it, the self-reference fallback included.

Four tables, by the word a condition opens with: "whenever"
(``engine/whenever_triggers.py``, which holds most of the rows), "when", "at
the beginning of", and the trailing ", if ..." clauses an effect may carry
(:func:`_extract_if_condition`). CR 603.1 makes "when" and "whenever" one kind
of ability, so a "when" line the "when" table misses is asked of the
"whenever" table with the word swapped (:func:`_parse_trigger_condition`).

A named group is **delimited** by its pattern and **read** elsewhere:
:func:`_resolve_subject_groups` hands a ``<name>_subject`` to the noun parser
and a ``<name>_count`` to the number table, and a phrase it cannot test
refuses the whole condition rather than falling through to a wider row.

Split out of ``engine/oracle.py`` at the 2,000-line cap; ``engine.oracle``
still exports :func:`trigger_condition_of_line`, which is in its ``__all__``.
"""

from __future__ import annotations

import re

from .oracle_types import TriggerCondition, _NUMBER_WORDS
from .line_normalization import normalize_creature_line
from .whenever_triggers import WHENEVER_TRIGGER_PATTERNS
from .self_reference import _collapse_self_references


# "when" triggers (enter/leave events)
WHEN_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    # `enters_battlefield` **is** the source's own entry, and the `.+` was
    # claiming every other subject for it. "When **another creature** enters,
    # return this creature to its owner's hand" (Timid Drake) matched here and
    # lost the word: the Drake bounced itself the turn it arrived and never
    # fired again — an ability firing on the wrong event, which reads to every
    # census as implemented. The grammar had it right (`matching_permanent_enters`
    # with `other_than_source`), so the two front ends disagreed and the one
    # that dispatches was the wrong one.
    #
    # The lookahead rather than a `matching_permanent_enters` row copied down
    # here, because a kind lives in one table (see the note in the whenever
    # table): a quantified subject falls through to the whenever patterns, where
    # that kind already reads the noun phrase. The bare `.+` still covers a card
    # naming itself by a short form the self-reference collapse leaves behind
    # ("when barrin enters"), which is the source and belongs to this kind.
    # "When this creature **enters or dies**, create two 1/1 red Goblin
    # creature tokens." (Goblin Marshal; Hunting Moa prints the same condition.)
    # CR 603.1's one ability with two trigger events, as one kind announced at
    # both fire sites — `creature_attacks_or_blocks`' arrangement.
    #
    # **Above** the bare entry row, which is its strict prefix and which claimed
    # these lines: that row's span ended at "enters" and left "or dies, create
    # …" as the effect clause, so the grammar refused the remainder and the
    # cards were reported unsupported. Ordered the other way this row would
    # never be reached, which is this table's standing longest-first rule.
    ("enters_or_dies",
     r"when (?!(?:a|an|another) )(?:this|.+?) enters(?: the battlefield)? or dies"),
    ("enters_battlefield",
     r"when (?!(?:a|an|another) )(?:this|.+) enters(?: the battlefield)?"),
    # "When **the token** leaves the battlefield, sacrifice this enchantment."
    # (Dance of Many.) CR 603.6c's event asked about a *different* object from
    # the one whose ability it is — the token this permanent created — which is
    # the same shape as `attached_creature_dies` below, an Aura watching its
    # host. The relation is in the kind because it is the relation the fire
    # site dispatches on; nothing about the token itself narrows it.
    #
    # Above the generic row and deliberately not folded into it: that row's
    # `.+` swallows "the token" and reports the ability as watching the
    # enchantment, which is a trigger firing on the wrong event while the card
    # compiles supported.
    ("created_token_leaves_battlefield",
     r"when the token leaves(?: the battlefield)?"),
    # "**When the chosen player draws a card with the chosen name**, sacrifice
    # this artifact." (Booby Trap.) The same ``draws_card`` announcement the
    # "whenever" table narrows by seat, narrowed here by *two* records the
    # permanent made as it entered (CR 614.1c) — so both are words on the
    # condition and the comparison is a metadata read in ``engine/event_filters.py``,
    # where the permanent is in hand. Nothing the announcement could carry says
    # which player a trap was aimed at.
    #
    # The kind is shared with that table's row deliberately, which is the
    # arrangement the ``attached_creature_dies`` note one table up records: one
    # kind, one dispatcher, one filter, and the printed words decide what it
    # watches. The word here really is "when" and not "whenever" — the artifact
    # sacrifices itself, so the trap springs once.
    ("draws_card",
     r"when (?P<drawer>the chosen player) draws a card"
     r"(?P<drawn_name> with the chosen name)"),
    # "When enchanted creature leaves the battlefield, its controller
    # sacrifices a creature of their choice." (Funeral March.) CR 603.6c's
    # event asked about the permanent this one is *attached to* —
    # `attached_creature_dies` below widened from a death to any move off the
    # battlefield, so an exiled, bounced or tucked host fires it too.
    #
    # Above the generic row and deliberately not folded into it, exactly as
    # `created_token_leaves_battlefield` is: that row's `.+` swallows
    # "enchanted creature" and reports the ability as watching the **Aura**, so
    # the card would compile supported and fire when the Aura itself left. That
    # is idiom 1 in its purest form — a condition narrowed on the grammar side
    # alone, with this table quietly naming a different event.
    ("attached_creature_leaves_battlefield",
     r"when(?:ever)? (?:equipped|enchanted) creature leaves(?: the battlefield)?"),
    # "When this creature **phases out or leaves the battlefield**, mill three
    # cards." (Ertai's Familiar.) CR 603.1's one ability with two trigger
    # events, exactly as `creature_attacks_or_blocks` is — one kind read at
    # both fire sites, never two entries, because the ability is one ability
    # and each of two would be waiting for its own half.
    #
    # Above the generic row for `created_token_leaves_battlefield`'s reason and
    # a sharper one: that row's `.+` swallows "this creature phases out or" and
    # reports the ability as watching the *departure alone*. Ertai's Familiar
    # has phasing, so it phases out every other untap step and never leaves the
    # battlefield at all — the card would have compiled supported and milled
    # nothing for the whole game.
    ("phases_out_or_leaves_battlefield",
     r"when this (?:creature|artifact|enchantment|land|permanent) phases out "
     r"or leaves(?: the battlefield)?"),
    # The lookahead is `enters_battlefield`'s, three rows up, for its reason:
    # "when **a** creature leaves the battlefield" is a quantified subject, not
    # the source, and the `.+` would claim it as the source's own departure. It
    # falls through to the whenever table's `matching_permanent_leaves_battlefield`.
    ("leaves_battlefield",
     r"when (?!(?:a|an|another) )(?:this|.+) leaves(?: the battlefield)?"),
    # "**When you lose control of this artifact**, put all cards exiled with
    # this artifact into their owner's graveyard." (Gustha's Scepter.) A CR
    # 603.10d event — it looks back in time, so the ability exists to trigger
    # even though the permanent is already gone by the time anyone asks. Its
    # own kind rather than a spelling of `leaves_battlefield`: a control change
    # is not a zone change (the permanent is still on the battlefield, under
    # somebody else), and every other card in the pool that prints these words
    # prints them as a *rider* on its own control-gaining sentence, which the
    # rider parser reads and this row must not claim.
    ("lose_control_of_source",      r"when you lose control of (?:this|it|the) ?.*"),
    ("attached_creature_dies",      r"when(?:ever)? (?:equipped|enchanted) creature dies"),
    # CR 701.26a's event with the one-shot trigger word (Blight: "**When**
    # enchanted land becomes tapped, destroy it"). Here for the reason
    # `attached_creature_dies` above is in both tables: which word a card
    # printed is not a difference the dispatcher can act on, and a table holding
    # only one of them leaves the other's cards refusing a condition the engine
    # implements. The *self* spelling has no row here — a permanent becoming
    # tapped is a repeatable event, so every printing of that one says
    # "whenever", the same argument the `you_gain_life` note below makes.
    ("permanent_becomes_tapped",
     r"when(?:ever)? enchanted (?P<tapped_attached>[a-z]+) becomes tapped"),
    # A row per event the "whenever" table already names used to live here —
    # "when this creature blocks" (Elder Land Wurm). It is gone, and so is the
    # whole idea of copying rows between the tables: `_parse_trigger_condition`
    # now falls back to the whenever table for any "when" line this one misses,
    # so **every** event is readable under both printed words. The hand-copied
    # subset was why Time Elemental's "when this creature attacks or blocks" —
    # a condition already in the whenever table, already dispatched — refused.
    # CR 700.4: "dies" means "is put into a graveyard from the battlefield",
    # so Brood of Cockroaches' long spelling is this condition and not a second
    # one. Above the bare row rather than beside it, because that row's `.+`
    # would swallow the whole clause on any line that happened to end in
    # "dies" — and both front ends carry the wording, since a condition only one
    # of them reads leaves the other refusing the effect behind it.
    # The permanent noun and the article are both read rather than fixed.
    # "When **this enchantment** is put into **a** graveyard from the
    # battlefield, you lose the game." (Lich.) Neither front end had this
    # spelling, so the ability compiled to nothing and the card's whole
    # downside never happened — CR 404.1 sends a permanent to its owner's
    # graveyard, so "a" and "your" name the same pile for a card its controller
    # owns, and the noun is the source either way.
    ("dies",
     r"when this (?:creature|artifact|enchantment|land|aura|permanent) is put into "
     r"(?:a|your) graveyard from the battlefield"),
    # "When **this card** is put into your graveyard **from your library**"
    # (Gaea's Blessing). Not a death and not this table's `dies` row: the
    # source zone is a library, which is a move no permanent can make — so
    # CR 113.6k has the condition function wherever it *can* trigger from, and
    # `engine/events.moved_card_trigger_events` is what announces it. Above the
    # bare "dies" row for that row's stated reason: its `.+` would otherwise
    # swallow any line ending in the word.
    ("self_put_into_graveyard_from_library",
     r"when this card is put into your graveyard from your library"),
    # "When **a card** is put into your graveyard **from anywhere**, sacrifice
    # this enchantment." (Energy Field.) Not the row above and not a death:
    # the object is any card, the destination is the watcher's own graveyard,
    # and "from anywhere" names every source zone there is — which is exactly
    # the seam ``Game.put_card_into_graveyard`` was built to be (CR 903.9b's
    # argument, one zone over). Above the bare "dies" row for that row's stated
    # reason: its ``.+`` would otherwise swallow this clause whole.
    ("card_put_into_graveyard",
     r"when a card is put into (?P<your_graveyard>)your graveyard "
     r"from anywhere"),
    # "When **this creature** is put into a graveyard **from anywhere**."
    # (Serra Avatar.) The card's own move, out of any zone — a death, a
    # discard, a mill and a countered spell are all this condition, which is
    # exactly what the bare `dies` row two screens down is *not*: CR 700.4
    # makes dying "from the battlefield", so reading this line as a death would
    # be a trigger that never fires on a milled Avatar.
    #
    # Above the bare "dies" row for that row's stated reason, and above the
    # long "put into a graveyard from the battlefield" row for the mirror one:
    # this line does not end in "dies" and does not say "from the battlefield",
    # so neither can claim it — but a later row written with a `.+` could, and
    # the position is what says it must not.
    #
    # The noun is read rather than fixed, like the battlefield row's: a card
    # names itself by whatever permanent word it likes (CR 109.5), and "card"
    # is here too because a sentence about a move out of any zone is a sentence
    # about a card.
    ("self_put_into_graveyard_from_anywhere",
     r"when this (?:creature|artifact|enchantment|land|aura|permanent|card) is "
     r"put into a graveyard from anywhere"),
    # "When this creature dies **during combat**, …" (Mongrel Pack). CR 506.1's
    # phase, asked of the death rather than of the creature: the same death, in
    # a different part of the turn, is a different card. The marker is an empty
    # named group — the idiom this table uses everywhere a narrowing carries no
    # text of its own — and the death fire site is what compares it against the
    # phase the game is in.
    #
    # **Above** the bare row, which its `.+` would otherwise swallow whole:
    # matched there the words "during combat" are left unread and the trigger
    # fires on every death, which is a strictly more generous card than the one
    # printed and invisible from the outside.
    ("dies",
     r"when this creature dies (?P<dies_during_combat>)during combat"),
    # "When **the creature put onto the battlefield with this enchantment**
    # dies, …" (Diabolic Servitude.) A death the source *watches* rather than
    # its own, so it is the whenever table's `permanent_dies` under the other
    # printed word — and the subject is read by the noun parser rather than
    # matched as words, exactly as that row's is.
    #
    # **Above** the bare row, whose `.+` swallowed it whole: matched there it
    # became `dies`, the source's own death loop, so the trigger fired when the
    # *enchantment* went to the graveyard and never when the creature did. An
    # ability firing on the wrong event, which reads to every census as
    # implemented — the failure this table's neighbouring comments name twice.
    #
    # The definite article is what keeps it off the bare row's other cards: it
    # names one described object where "a"/"an" name any, and the description
    # behind it is what says which. Nothing else in the pool prints "when the …
    # dies".
    ("permanent_dies",
     r"when (?P<dying_subject>the [^,]+) dies"),
    ("dies",                        r"when (?:this creature|.+) dies"),
    # "you_gain_life" was here, spelled "when you gain life", with no dispatcher
    # and no card: a life gain is a repeatable event, so every printing of it is
    # "**Whenever** you gain life" — the row above in the whenever table, which
    # Vito reaches. A kind lives in one table, because the shadowing guard's
    # canonical examples are keyed by kind and an example can only be a wording
    # of one trigger word.
    # "becomes_target" was here, spelled "when (?:this|.+) becomes the target",
    # with no dispatcher and — until Mirage — no card. Skulking Ghost prints the
    # "when" wording ("When this creature becomes the target of a spell or
    # ability, sacrifice it"), which this row swallowed into a kind nothing
    # announces: the card compiled supported and never sacrificed itself.
    # CR 603.1 makes the two trigger words one ability, so the row is gone and
    # the "when" fallback carries the line to `self_becomes_target` in the
    # whenever table, which has the filter and the fire site
    # (`_announce_target_triggers`). Same fix, and the same reason, as the
    # `you_gain_life` row above.
    # "When you remove the last intervention counter from this enchantment, …"
    # (Divine Intervention.) The counter word is payload, like the threshold
    # trigger above it. Announced from the same state-based sweep and for the
    # same reason the draw triggers are: removal has four call sites, so the
    # record `named_counters.remove_counters` writes is what the sweep reads.
    ("last_counter_removed",
     r"when you remove the last (?P<counter_kind>[a-z]+) counter from this "
     r"(?:artifact|aura|creature|enchantment|permanent|land)"),
    # "When the last ore counter **is removed** from this Aura, …" (Orcish
    # Mine.) The same event in the passive voice, and it has to be the same
    # kind: CR 122.1's removal is one event however it happened, and the
    # dispatcher behind it (`mixins/game_ending.py`) reads the record
    # `named_counters.remove_counters` writes rather than any call site — which
    # is exactly why the printed voice cannot matter. Orcish Mine's counters
    # come off through its *own* trigger, so an active-voice-only table would
    # have left the card's whole payoff unreadable.
    ("last_counter_removed",
     r"when the last (?P<counter_kind>[a-z]+) counter is removed from this "
     r"(?:artifact|aura|creature|enchantment|permanent|land)"),
    # "When a spell or ability an opponent controls causes you to discard this
    # card, …" (Psychic Purge.) CR 113.6: an ability that functions from the
    # hand. The one discard seam (`Game._discard_card`) is what announces it,
    # and CR 109.5's "an opponent" is read off the seat resolving the spell or
    # ability that caused the discard.
    # "When **you cast this spell**, counter it unless you sacrifice a land."
    # (Mana Vortex.) CR 603.6d: an ability that triggers on its own object
    # being cast, so it functions from the stack rather than from the
    # battlefield the permanent has not reached yet (CR 113.6a). The cast
    # path is what announces it, over the card it is casting.
    ("self_cast",                   r"when you cast this spell"),
    ("discarded_by_opponent_effect",
     r"when a spell or ability an opponent controls causes you to discard this card"),
    # "When you control **no Islands** / **no Forests**, sacrifice this
    # creature." (Sea Serpent, Island Fish Jasconius; Gorilla Pack in Ice Age.)
    # The negative twin of `controls_matching_permanent` below, with the noun
    # delimited and read by the noun parser. It was a ``no_islands`` kind with
    # the land type welded into the name — the shape idiom 19 exists to
    # prevent — so Gorilla Pack, printing the identical sentence about Forests,
    # was a card the engine could not read.
    #
    # Ordered before the positive row for the reason that one documents in
    # reverse: "no <noun>" is not an "an? " phrase and the two cannot collide,
    # and the specific-before-generic rule holds anyway.
    ("controls_no_matching",
     r"when you control no (?P<controlled_subjects>[^,]+)"),
    # "When there are **no lands on the battlefield**, sacrifice this
    # enchantment." (Mana Vortex.) "When there are **no creatures on the
    # battlefield**, sacrifice this enchantment." (Drop of Honey.) The same
    # state trigger (CR 603.8) asked about every battlefield rather than the
    # source controller's — a different set from the row above, so a different
    # kind: a Mana Vortex whose controller has no land is not sacrificed while
    # an opponent still has one.
    #
    # **The noun is payload**, which is the correction the row above already
    # states in its own comment: this was ``no_lands_anywhere``, with the type
    # welded into the kind, so the second card printing the identical sentence
    # about a second type could not be read at all — and Drop of Honey's
    # printing of it went unimplemented behind a name-keyed hook, whose blanket
    # claim is what kept ``parse_coverage`` from ever naming the line.
    ("no_permanents_anywhere",
     r"when there are no (?P<absent_subjects>[^,]+) on the battlefield"),
    # "When **no creatures are on the battlefield**, sacrifice this
    # enchantment." (Last Laugh.) Drop of Honey's sentence in the other word
    # order — the same state (CR 603.8) over the same set, so the same kind
    # and payload, and a second row rather than a second kind: the kind is the
    # dispatcher's address and the sweep in `mixins/game_ending.py` already
    # answers it. Two rows because a pattern may not name one group twice.
    ("no_permanents_anywhere",
     r"when no (?P<absent_subjects>[^,]+) are on the battlefield"),
    # "When you control a Dwarf, sacrifice this creature." (Goblins of the
    # Flarg.) A state trigger (CR 603.8) like the two above, and the *positive*
    # one: those fire while a described set is empty, this while it is not.
    # Ordered after them because "no islands" is not an `an? ` phrase and so
    # cannot reach this row — the ordering is the specific-before-generic rule
    # holding even where the two cannot currently collide.
    #
    # The noun phrase is delimited, not described: the group is read by the noun
    # parser and refused if `subject_matches` cannot test it, so a card printing
    # any other tribe is the same trigger with different payload.
    #
    # "When **an opponent** controls a creature with power 4 or greater"
    # (Hidden Predators) is the same condition asked of a different seat, so
    # the seat is an *optional* payload group and not a second kind — the
    # arrangement ``land_played`` and ``draws_card`` already use, and the one
    # idiom 19 asks for: a kind is a dispatcher's address, and spelling the
    # seat into it gives one card its own fire site. An absent group never
    # reaches the payload, so Goblins of the Flarg compiles to exactly what it
    # compiled to before.
    ("controls_matching_permanent",
     r"when (?:you control|(?P<controls_seat>an opponent) controls) "
     r"(?P<controlled_subject>an? [^,]+)"),
    # "When **a player has no cards in hand**" (Veiled Crocodile). CR 603.8
    # again, and its own kind rather than a seat on the row above: what is
    # counted is a *hand*, which no board census reaches, and the sweep that
    # answers it walks players rather than permanents.
    ("player_has_no_cards_in_hand",  r"when a player has no cards in hand"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    # "each player's upkeep" / "each upkeep" / "each **opponent's** upkeep"
    # (Psychic Allergy). One event asked of a narrower set of seats, so the
    # narrowing is *payload* and not a second kind — idiom 19: a condition kind
    # is a dispatcher's address, and spelling the subject into it gives one card
    # its own fire site. `phases/upkeep_step.py` reads `upkeep_scope` to decide
    # whether this firing is one the card names.
    ("upkeep_each",         r"at the beginning of each (?:(?P<upkeep_scope>opponent|player)'s )?upkeep"),
    # Cursed Land's "enchanted land's controller" is here too: the deal_damage
    # handler (phases/upkeep_effects.py) reads `attached_to` and does not care
    # what the enchanted permanent is, so a land Aura routes through it like the
    # creature/artifact/enchantment ones. The bespoke enchant-land pass that
    # used to deal it (and the double-fire that excluding `land` guarded against)
    # are both gone.
    ("upkeep_enchanted_controller", r"at the beginning of the upkeep of enchanted (?:creature|artifact|enchantment|land)'s controller"),
    # The same clause naming the **end step** instead (Aggression). A kind of
    # its own rather than a scope on the upkeep one, because the two are
    # dispatched by different steps — CR 513 and CR 502 — and a scope the end
    # step did not read would be an Aura firing at the wrong moment.
    ("end_step_enchanted_controller", r"at the beginning of the end step of enchanted (?:creature|artifact|enchantment|land)'s controller"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    # "Your draw step" is a scope narrowing and so its own kind, exactly as
    # upkeep_self is beside upkeep_each: it fires only on its controller's draw
    # step where the bare form fires on everyone's. Must precede nothing here
    # (neither is a prefix of the other), but it is listed first to match the
    # upkeep pair's order.
    ("draw_step_self",      r"at the beginning of your draw step"),
    # "each **opponent's** draw step" (Malignant Growth) beside "each
    # player's". One event asked of a narrower set of seats, so the narrowing
    # is *payload* and not a second kind — the same shape `upkeep_scope` above
    # takes, and for its reason (idiom 19): a condition kind is a dispatcher's
    # address, and spelling the subject into it gives one card its own fire
    # site. `phases/draw_step.py` reads `draw_step_scope` to decide whether this
    # firing is one the card names.
    ("draw_step_each",      r"at the beginning of each (?:(?P<draw_step_scope>opponent|player)'s )?draw step"),
    # "At the beginning of your first main phase" (the M21 Shrine cycle) —
    # CR 505.1a's precombat main phase, which is the only one that is "first".
    # Both printed spellings, because the modern templating says "precombat".
    ("main_phase_first",    r"at the beginning of your (?:first|precombat) main phase"),
    # "At the beginning of **each player's** first main phase" (Eladamri's
    # Vineyard). The scope narrowing beside its "your" twin, and its own kind
    # for the reason `upkeep_self`/`upkeep_each` and `draw_step_self`/
    # `draw_step_each` are two kinds each: the *dispatch* is what reads the
    # difference, and a scope the fire site did not read would be an
    # enchantment that only ever worked on its controller's turn.
    #
    # `main_phase_scope` is payload rather than a third kind, exactly as
    # `upkeep_scope` is: a card printing "each opponent's first main phase" is
    # the same event asked of a narrower set of seats.
    ("main_phase_first_each",
     r"at the beginning of each (?:(?P<main_phase_scope>opponent|player)'s )?"
     r"(?:first|precombat) main phase"),
    # "At the beginning of **each of your main phases**" (Carpet of Flowers).
    # CR 505.1's two main phases, both of them, on the controller's own turn —
    # so it is neither of the rows above: `main_phase_first` fires once and only
    # precombat, and `main_phase_first_each` fires precombat on everybody's
    # turn. A third kind because the *dispatch* is what reads the difference,
    # which is the reason `upkeep_self`/`upkeep_each` and
    # `draw_step_self`/`draw_step_each` are two kinds each.
    #
    # Ordered here rather than above them because none of the three is a prefix
    # of another ("each of your" and "each player's" diverge on the second
    # word), so the placement is documentation and the specific-before-generic
    # rule holds anyway.
    ("main_phase_each_yours",
     r"at the beginning of each of your main phases"),
    # "Your end step" is a *scope* narrowing, exactly like combat's below and
    # upkeep_self/upkeep_each above: it fires only on its controller's own end
    # step where the bare form fires on everyone's. A separate kind because the
    # dispatch is what reads the difference — with one kind,
    # engine/phases/end_step.py had to infer a scope per instruction kind, and
    # the gated scan inferred "your" for every card that reached it.
    # Must precede its own prefix, per the ordering rule.
    ("end_step_self",       r"at the beginning of your end(?: step)?"),
    # "each **player's** end step" (Monsoon) names the same set as the bare
    # "each end step": CR 513.1 gives every turn exactly one end step, so every
    # end step is some player's. So it is a spelling and not a scope — unlike
    # upkeep_each's `upkeep_scope`, which exists because "each **opponent's**
    # upkeep" really is a narrower set and the dispatcher enforces it. A card
    # printing "each opponent's end step" refuses here rather than being
    # admitted with the narrowing dropped.
    ("end_step",            r"at the beginning of (?:the |each )?(?:player's )?end(?: step)?"),
    # "…of combat on your turn" narrows the bare form to the active player's
    # combat (Adherent of Hope); must precede its own prefix below.
    ("combat_your_turn",    r"at the beginning of combat on your turn"),
    # "…of combat on **each opponent's** turn" (Fight or Flight): the other
    # narrowing of the same step, and a separate kind for `upkeep_self` /
    # `upkeep_each`'s reason — the dispatch is what reads the difference. The
    # seat varies per firing, so the fire site freezes it and "that player"
    # reads it back (CR 603.10). Above the bare row, which is its prefix.
    ("combat_opponent_turn", r"at the beginning of combat on each opponent's turn"),
    # "At the beginning of **each** combat" (Goblin Flotilla). The same event
    # as the bare spelling below it and the same kind: CR 506.1 gives a turn one
    # combat phase per combat, and the fire site announces every one of them —
    # so "each" states what the bare wording already means rather than narrowing
    # it. Above the bare row, which is not its prefix but which the
    # specific-before-generic rule keeps it above anyway.
    ("combat",              r"at the beginning of each combat"),
    ("combat",              r"at the beginning of combat"),
    # "At end of combat, …" (The Wretched) — CR 511.1, the end of combat step.
    # Clockwork Beast's line opens the same way and stays a static line: its
    # effect clause compiles no instruction, so the classifier's static
    # fallback (step 2 of _parse_creature_program) keeps it where
    # phases/end_of_combat_step.py's text probe reads it.
    ("end_of_combat",       r"at end of combat"),
)

# "if" conditions that can appear mid-effect
IF_CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("artifact_untapped",       r"if this artifact is untapped"),
    # The same clause the other way round (Mana Vault's draw-step damage). Both
    # halves are listed because a table holding only one of a pair is how a gate
    # nothing can fail gets written.
    ("artifact_tapped",         r"if this artifact is tapped"),
    ("creature_died_this_turn", r"if a creature died this turn"),
    ("no_creatures_in_hand",    r"if you have no creatures in hand"),
    ("paid_mana",               r"if you paid? .+"),
    ("controls_island",         r"if (?:you |defending player )?controls? an? island"),
    ("controls_swamp",          r"if (?:you |defending player )?controls? an? swamp"),
    ("is_untapped",             r"if (?:this|it) is untapped"),
    ("not_playing_for_ante",    r"if you're not playing for ante"),
)


def _compile_trigger_patterns(
    patterns: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((kind, re.compile(pattern)) for kind, pattern in patterns)


# Precompiled once at import. Python's internal regex cache holds only 512
# entries, so relying on it would thrash as the pattern tables grow.
_COMPILED_WHENEVER_PATTERNS = _compile_trigger_patterns(WHENEVER_TRIGGER_PATTERNS)
_COMPILED_WHEN_PATTERNS = _compile_trigger_patterns(WHEN_TRIGGER_PATTERNS)
_COMPILED_AT_PATTERNS = _compile_trigger_patterns(AT_TRIGGER_PATTERNS)
_COMPILED_IF_PATTERNS = _compile_trigger_patterns(IF_CONDITION_PATTERNS)


# ---------------------------------------------------------------------------
# Trigger condition parsing
# ---------------------------------------------------------------------------

# A named group ending in this holds a printed *noun phrase* rather than a
# word: "whenever a creature you control **with deathtouch** attacks". The regex
# only delimits it — what it names is read by the noun parser, so the two front
# ends of the pipeline turn one phrase into one filter instead of a regex
# approximating what the grammar does.
_SUBJECT_GROUP_SUFFIX = "_subject"

# The same noun phrase where the object is a **card** rather than a permanent:
# "whenever **a black card** is put into an opponent's graveyard from anywhere"
# (Compost). A card in a graveyard, a hand or a library is not on a battlefield,
# so it has no controller, no layer-computed types and no board position —
# `subject_filter_payload` answers None for the phrase and the whole condition
# would refuse. The card twin `card_filter_payload` is the reader, gated on
# `CARD_ONLY_FILTER_KEYS`, which is exactly the set `_card_matches_filter` can
# answer about an object in a pile.
#
# A suffix of its own rather than a second reading of `_subject`, because which
# matcher a phrase is destined for is a fact about the *condition* — the same
# words describe a different testable set in the two zones, and a group that
# guessed would hand a graveyard filter to a battlefield matcher.
_CARD_SUBJECT_GROUP_SUFFIX = "_card_subject"

# The same idea for a printed *number*: "whenever you attack with **two** or
# more creatures with flying". The regex delimits the word and `_NUMBER_WORDS`
# reads it, so a count is data on the condition rather than a pattern per
# number.
_COUNT_GROUP_SUFFIX = "_count"

# The same noun phrase in the one position where it is **counted** rather than
# quantified: "two or more **creatures with flying**". A bare plural is the noun
# parser's sweep quantifier, which every other subject position refuses — so the
# plural spelling of the suffix is how a pattern says which reading it means.
_PLURAL_SUBJECT_GROUP_SUFFIX = "_subjects"

# The same noun phrase where one printed clause narrows **both** halves of a
# blocking pair: "blocks or becomes blocked by a non-Wall creature". English
# distributes the phrase over both verbs, and the engine already has a filter
# key per half — so the group resolves into both rather than into a third key
# nothing reads, and the two general dispatchers need no notion of a joined
# condition at all.
_PAIR_SUBJECT_GROUP_SUFFIX = "_pair_subject"

# The same joined phrase in its **counted** spelling: "blocks or becomes blocked
# by one or more **Orcs**" (Dwarven Soldier). A bare plural is the noun parser's
# sweep quantifier, exactly as it is for `_subjects` one suffix up, and the
# accompanying `_count` group is CR 509.3e's threshold — which is what makes
# this firing once rather than once per creature.
_PLURAL_PAIR_SUBJECT_GROUP_SUFFIX = "_pair_subjects"

# Which filter keys a `_pair_subject` group fans out to, in the order the two
# halves are printed. Named here rather than spelled at the fan-out below,
# because these are the keys the dispatchers read and a fourth spelling of them
# is how the two sides come apart.
_PAIR_SUBJECT_FILTER_KEYS = ("blocked_filter", "blocker_filter")

# What a ``<name>_includes_spells`` marker allows the accompanying noun phrase
# to say. The union "a red creature or spell" describes one object under two
# nouns, and only the words in front of the noun distribute over both — a spell
# on the stack is the printed card (CR 109.5), which has no controller, no
# layer-computed types and no board position to be asked about. ``type_filter``
# is the creature half's own noun (dropped for the spell half) and
# ``color_filter`` is the shared adjective; anything else refuses the condition,
# because a restriction a spell cannot be tested for is one the dispatcher would
# silently ignore on exactly half the sentence.
_SPELL_UNION_FILTER_KEYS = frozenset({"type_filter", "color_filter"})


def _match_trigger_patterns(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    trigger_word: str,
) -> TriggerCondition | None:
    for kind, pattern in patterns:
        m = pattern.match(text)
        if not m:
            continue
        # Named groups become the condition's payload, so a narrowed
        # condition ("…casts a *blue* spell") carries its restriction as
        # data. Event dispatch reads it instead of needing a per-card hook.
        payload = {k: v for k, v in m.groupdict().items() if v is not None}
        payload = _resolve_subject_groups(payload)
        if payload is None:
            # The phrase is not a set of objects this engine can test. Refusing
            # the *condition* — rather than falling through to a later, wider
            # pattern — is the point: a trigger that fires on more than the card
            # prints is the silent wrongness the whole table exists to avoid.
            return None
        return TriggerCondition(
            kind=kind, trigger=trigger_word, raw_text=m.group(0), payload=payload
        )
    return None


def _resolve_subject_groups(payload: dict) -> dict | None:
    """Turn every delimited group in *payload* into the value the dispatcher
    reads, or return None if one of them says something it cannot test.

    Two suffixes, both of which mean "the regex marked this out and something
    else reads it": ``<name>_subject`` is a printed noun phrase, read by the
    noun parser; ``<name>_count`` is a printed number word, read by the same
    table every other text-keyed count uses. A number the table does not know
    refuses the whole condition rather than defaulting to one — a trigger that
    fires on one attacker where the card says three is the same silent widening
    an ignored filter would be.
    """
    from .grammar import card_filter_payload, subject_filter_payload
    from .subject_filters import untestable_filter_keys

    resolved = dict(payload)
    for key, word in payload.items():
        if not key.endswith(_COUNT_GROUP_SUFFIX):
            continue
        # A printed *digit* is a printed number. "When this creature's power
        # is **7** or greater" (Phyrexian Devourer) is the only spelling that
        # card uses, and `_NUMBER_WORDS` holds words alone — so without this
        # the group came back None and the whole condition refused, which is
        # the same shape `_chargeable_tap_cost` hit when "an" was missing from
        # that table. Read the same way every other counted clause in this
        # file reads one.
        text = str(word).strip()
        count = int(text) if text.isdigit() else _NUMBER_WORDS.get(text)
        if count is None:
            return None
        resolved[key] = count
    for key, phrase in payload.items():
        # "…**a black card** is put into an opponent's graveyard" (Compost).
        # Read by the card matcher's own reader, which already refuses a phrase
        # naming anything a card in a pile cannot answer — so the gate the
        # battlefield branch below applies by hand is applied inside this one.
        # Resolved before those branches because its suffix ends in `_subject`
        # and would otherwise be claimed by them and handed to the wrong matcher.
        if key.endswith(_CARD_SUBJECT_GROUP_SUFFIX):
            described = card_filter_payload(str(phrase))
            if not described:
                # None is "not a phrase the noun parser reads" and `{}` is "a
                # phrase that reduced to no restriction at all" — a black card
                # with the colour dropped is every card, which is a trigger
                # firing on the whole game. Both refuse the condition.
                return None
            del resolved[key]
            resolved[key[: -len(_CARD_SUBJECT_GROUP_SUFFIX)] + "_card_filter"] = described
            continue
        pair_plural = key.endswith(_PLURAL_PAIR_SUBJECT_GROUP_SUFFIX)
        if pair_plural or key.endswith(_PAIR_SUBJECT_GROUP_SUFFIX):
            described = subject_filter_payload(str(phrase), plural=pair_plural)
            if described is None or untestable_filter_keys(described):
                return None
            del resolved[key]
            for filter_key in _PAIR_SUBJECT_FILTER_KEYS:
                resolved[filter_key] = described
            continue
        plural = key.endswith(_PLURAL_SUBJECT_GROUP_SUFFIX)
        if not plural and not key.endswith(_SUBJECT_GROUP_SUFFIX):
            continue
        suffix = _PLURAL_SUBJECT_GROUP_SUFFIX if plural else _SUBJECT_GROUP_SUFFIX
        described = subject_filter_payload(str(phrase), plural=plural)
        # The second gate is the load-bearing one: a filter the *dispatcher*
        # cannot test is refused here rather than ignored there, because an
        # ignored restriction is a trigger firing on more than the card says.
        if described is None or untestable_filter_keys(described):
            return None
        del resolved[key]
        # "Whenever **this creature or** another Rogue you control enters"
        # (Thieves' Guild Enforcer). The phrase read above says "another", which
        # the noun parser folds into `exclude_self` — and the words in front of
        # it put the source back in. An empty named group is how a pattern says
        # so: it is present in the match's groupdict exactly when that spelling
        # matched, and it carries no text of its own to be re-read.
        stem = key[: -len(suffix)]
        if f"{stem}_includes_source" in payload:
            described = {k: v for k, v in described.items() if k != "exclude_self"}
            del resolved[f"{stem}_includes_source"]
        # "…attacks **you**" (Barbed Foliage). CR 506.2's defending player,
        # the same empty-marker-group idiom one paragraph up: present in the
        # groupdict exactly when that row matched, carrying no text of its own,
        # and folded into the filter the noun parser already built. Added after
        # the testability gate above because `attacking_you` is in
        # `TESTABLE_SUBJECT_FILTER_KEYS` — it is answered by
        # `subject_filters.subject_matches` like any other key, against the
        # trigger's own controller.
        if f"{stem}_attacking_you" in payload:
            described = {**described, "attacking_you": True}
            del resolved[f"{stem}_attacking_you"]
        if f"{stem}_includes_spells" in payload and (
            set(described) - _SPELL_UNION_FILTER_KEYS or "color_filter" not in described
        ):
            # "…a red creature **or spell**". The noun is the half that does not
            # distribute; every other word in the phrase does, and a spell is
            # the printed card (CR 109.5) with no board, no controller and no
            # layers — so a phrase saying anything a card cannot answer refuses
            # the condition rather than firing on the creature half alone. The
            # colour is required because it is the only thing left to test: a
            # bare "a creature or spell" would fire on every point of damage in
            # the game.
            return None
        resolved[stem + "_filter"] = described
    return resolved


def _parse_trigger_condition(normalized_line: str) -> tuple[TriggerCondition | None, str]:
    """Try to parse a trigger condition from the start of a normalized line.

    Returns (TriggerCondition, remainder_effect_text) or (None, original_line).
    The remainder is the effect clause after the condition, with leading
    punctuation and whitespace stripped.
    """
    if normalized_line.startswith("whenever "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHENEVER_PATTERNS, "whenever")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("when "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHEN_PATTERNS, "when")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder
        # CR 603.1 makes "when" and "whenever" one kind of ability: the words
        # differ in how often it triggers while it exists, never in what
        # triggers it, and no dispatcher in this engine reads the word. So a
        # "when" line this table misses is asked of the *whenever* table with
        # the one word swapped, rather than by copying rows between the two —
        # which is what the tables used to do, one card at a time, leaving every
        # event nobody had copied refusing its "when" printing while the engine
        # fired it happily for "whenever". The remainder is sliced off the
        # rewritten line because that is the string the pattern matched; the
        # condition still reports the word the card printed.
        as_whenever = "whenever " + normalized_line[len("when "):]
        cond = _match_trigger_patterns(
            as_whenever, _COMPILED_WHENEVER_PATTERNS, "when"
        )
        if cond:
            remainder = as_whenever[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("at "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_AT_PATTERNS, "at")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    return None, normalized_line


_TRAILING_IF_RE = re.compile(r",\s*(if .+)$")


def _extract_if_condition(effect_text: str) -> tuple[str | None, str]:
    """Strip a trailing 'if ...' clause from an effect and return (if_kind, clean_effect).

    Returns (None, original_text) if no recognized 'if' condition is present.
    """
    # Look for ", if ..." near the end of the effect text
    if_match = _TRAILING_IF_RE.search(effect_text)
    if not if_match:
        return None, effect_text

    if_clause = if_match.group(1)
    for kind, pattern in _COMPILED_IF_PATTERNS:
        if pattern.match(if_clause):
            clean = effect_text[: if_match.start()].strip()
            return kind, clean

    return None, effect_text


def trigger_condition_of_line(
    line: str, card_name: str | None = None
) -> tuple[TriggerCondition | None, str]:
    """The legacy table's reading of one printed line: ``(condition, remainder)``.

    **This is the only reading.** It used to live inline in
    ``_parse_triggered_ability``, which meant every other caller that wanted to
    know "what condition does the legacy table see here?" — the pool-wide guard
    in ``tests/engine/test_grammar_lowering.py`` most sharply — wrote the
    normalize-and-parse half and dropped the self-reference fallback below. Two
    readings of one table is the bug this project keeps finding: the guard
    reported Axelrod Gunnarson and Nicol Bolas as conditions "the legacy table
    does not name", when the table names both and only the guard could not see
    it.

    The fallback: the card's own name collapsed to "this creature", for the
    reason ``_restriction_line`` gives about the static tables. Every row is
    anchored on the modern templating, and a card that says its own name
    ("Whenever a creature dealt damage by **Axelrod Gunnarson** this turn dies")
    is printing a condition this engine already dispatches, the old way. Without
    it the row matched nothing and the card reported "text too complex" while
    the grammar — whose lexer collapses the same references — read the line. Two
    front ends disagreeing about one printed line is a card refused by the
    stricter of them.

    A *fallback* rather than the first reading, because the collapse is a
    whole-word substitution over the entire line and a card whose name is an
    ordinary word ("Fire", or a test fixture called "Player") would have its
    recipient clause rewritten out from under a row that already matched.
    Nothing this reads is text the uncollapsed pass could read.
    """
    normalized = normalize_creature_line(line)
    condition, remainder = _parse_trigger_condition(normalized)
    if condition is None and card_name:
        collapsed = _collapse_self_references(normalized, card_name, "this creature")
        if collapsed != normalized:
            condition, remainder = _parse_trigger_condition(collapsed)
    return condition, remainder
