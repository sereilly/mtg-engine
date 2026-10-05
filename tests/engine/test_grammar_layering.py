"""Guard: `engine/grammar/` stays layered, and its families stay independent.

`parser.py`, `lower.py` and `ast.py` were 2,306, 2,428 and 981 lines. They are
the three files that grow with the card pool — every new template lands in all
three — so their size is not cosmetic, it is the cost of the next 25,000 cards.
Splitting them only helps while the split holds, and a split holds by test or
not at all.

Two properties, and they fail differently.

**The layers are ordered.** `phrases -> effects -> conditions -> statements ->
costs -> parser` on the parsing side, `_common/categories -> the families -> statics -> lower` on the
lowering side, `_core -> the families -> statements -> lines` inside the AST. An import that
reaches back up would compile fine and would make the three files three files
again with extra steps.

**The families are independent.** `effects/damage.py` must not import
`effects/board.py`. This is the property that makes "where does prowess go?"
answerable: if the families reference each other, the answer becomes "wherever,
then fix the imports", and the grouping stops being information.

Independence is what the original files did *not* have, and each split started
by finding the exceptions rather than assuming there were none:
`_parse_zone` / `_parse_mana_payment` on the parsing side and
`_full_mana_payload` / `_REST_OF_TURN` on the lowering side were fragments
several families wanted. They live in `phrases` and `_common` for that reason,
not by taxonomy — so the rule below is "families do not import each other",
with no exception list to grow. (The AST needed no such correction: its nodes
only ever reference the shared vocabulary or their own family.)
"""

from __future__ import annotations

import ast
import collections
import pathlib
from pathlib import Path

import pytest
from tests.source_index import source_text, source_tree

GRAMMAR = Path(__file__).resolve().parent.parent.parent / "engine" / "grammar"

# Bottom to top. A module may import from any layer *below* it and none above.
# `conditions` sits below `statements` because that is where its dependencies
# put it: a condition describes an event and is built from nouns, amounts and
# durations alone, so nothing in it can reach a statement production. The
# order is therefore an assertion about the split, not a convention — a
# condition that grew a need for an effect would fail here.
PARSE_LAYERS = [
    # The mutable mirror of `ast.ObjectFilter` a noun phrase accumulates into,
    # and the hand-written copy that freezes it. The bottom of the parse side:
    # it reads `ast` and the dataclass machinery, nothing in it consumes a
    # token, and nothing here is a production. Split out of `nouns` at Exodus'
    # second wave, when the paragraph recording why the draft carries
    # `slots=True` took that module four lines past the guard below.
    #
    # Its own file because the two halves are one *bug*: the field lists are
    # written twice, the filter is frozen and the draft is not, and a field on
    # one and not the other loses a printed narrowing in silence — the phrase
    # parses, the card compiles, and the effect reaches a strictly larger set
    # than the card prints. The guard over the pair is the only instrument in
    # the repo that can see it, and a guard over two halves wants them in one
    # file. The draft is not `nouns`' property either: six modules write onto
    # it, each taking it as a parameter.
    #
    # No mirror name to reuse — `ast/_references.py` holds the `ObjectFilter`
    # and `ast/_payloads.py` the other direction out of it, so both AST words
    # are spoken for and the *draft* has no AST twin at all. `nouns` re-exports
    # both names, as it does `readers` and `bounds`, so no caller moved.
    "filter_draft",
    # Small printed readers `nouns` shares *upward* — a comparison, a
    # self-reference. Below it because nothing about them is about a filter.
    "readers",
    # The **price** a printed sentence names — a cost demanded ("unless they pay
    # {2}") or an offer made ("pay {4} and 2 life"). Split out of `phrases` when
    # that module crossed the guard at Mirage's second wave *integration*, on
    # nobody's branch: two groups' price fragments merely summed. The seam is
    # the one `phrases` had already written down in prose — the mana
    # alternatives lived there and their three life-cost siblings did not, so
    # one printed offer was read in two modules. Below `phrases`, which
    # re-exports it so every existing caller keeps its import, exactly as
    # `readers` above is re-exported.
    "prices",
    # A characteristic of the object a **cost** consumed, named back by the
    # sentence that charged it — "sacrifice a creature: … where X is the
    # sacrificed creature's power". The parse-side mirror of
    # `lowering/_cost_records.py`, carrying that module's name for the reason
    # the entry below carries `_records`'.
    #
    # Pre-split out of `records` at the Phase 0 before the next set, when that
    # module sat 27 lines under the guard and was one of the two the whole
    # parse side reaches. The seam is the mirror's own, not a new one: the
    # lowering halves of these two subjects separated at ULG wave 1, because
    # `_PRODUCES` is keyed by *instruction kind* and a cost has none — it is
    # charged by `engine/mixins/stack/activation.py` on the way to the stack
    # (CR 601.2h, CR 602.2b), not by anything the dispatcher runs. The parse
    # halves had stayed in one file only because neither had yet crossed a cap.
    #
    # The bottom of the parse side with `filter_draft`: it reads `ast` and one
    # token class, and not `readers` — a cost genitive names no source and
    # takes no comparison, so the four importers (`amounts`, `where_x`,
    # `effects/characteristics`, `effects/mana`) were pointed here directly
    # rather than through a re-export, which is the mirror's decision restated.
    "cost_records",
    # A quantity read off a *record* of something that already happened — the
    # parse-side mirror of `lowering/_records.py`, carrying that module's name
    # for that reason. "The sacrificed creature's toughness" names an event,
    # not a set of objects, so it shares no vocabulary with the filter parser
    # above it and sits here, on `readers` alone. Split out of `amounts` when
    # two waves' additions summed past the size guard below — and the split
    # *removed* a cycle rather than needing one: the call-time import these
    # productions carried was there because `nouns` imports `amounts`, which
    # they are no longer in.
    "records",
    # A seat picked out by **comparing a counted quantity against another
    # seat's** — "target player who controls more creatures than they do"
    # (Oath of Druids), "target opponent who has at least two fewer creature
    # cards in their graveyard than you do" (Keeper of the Dead). The
    # board-state twin of `records.accept_player_deed`, and its own module
    # rather than a production in that one because the two differ in what may
    # enforce them: a deed is a record only a resolution holds, and a
    # comparison is a count the *picker* can take while CR 601.2c is choosing.
    #
    # Above `records`, whose printed-number reader it asks for "at least
    # **two** more" — the reason that reader became public rather than being
    # spelled a second time here. Below `nouns`: the counted quantity is a
    # whole noun phrase, handed down as a parameter exactly as
    # `accept_player_deed` takes one, so the clause stays readable from
    # `choices` and `player_verbs` with no edge back up.
    #
    # No mirror name to reuse: the clause rides `ast.PlayerRef.compared` and
    # its payload is written by `lowering/_targets.py` beside every other
    # narrowing a picker reads, so the lowering side has no module of its own.
    "seat_comparisons",
    # CR 615.5's additional effect — "you gain life equal to the damage
    # prevented this way", "for each 1 damage prevented this way, put a +1/+1
    # counter on that creature". Pre-split out of `effects/prevention.py` at
    # Exodus' Phase 0, and it is here rather than in either half for the reason
    # this file's family rule gives: `effects/` has no shared module, so a
    # fragment two of its families need lives one level up or one of them
    # imports the other. The clause is deliberately read by **one** production —
    # two would make which riders a card may carry depend on which shield
    # printed them — so both prevention families call down to it.
    #
    # Above `records`, which it reads for Temper's leading "for each 1 damage
    # prevented this way", and not *in* it: every production there answers
    # "how many?" with an `Amount` where this returns a whole rider, and
    # `amounts` imports `records` at module level, so reaching
    # `amounts.accept_counter_kind` from inside `records` would close the very
    # cycle that module's split removed. No mirror name to reuse — the rider
    # rides on `ast.PreventDamage.prevented_rider` and lowers inside the shield
    # lowering, so the lowering side has no module of its own to fork.
    "prevented_riders",
    # An ability on the stack (CR 113.7a) has no card and no type line, so it
    # shares no vocabulary with the filter parser that reads one. Below
    # `nouns`, which returns the moment one of these matches.
    "abilities",
    # A card **name** is a literal string, not a description of a set of
    # objects, so the scan that reads one shares no vocabulary with the filter
    # parser above it. Split out of `nouns` when the cross-axis class union
    # pushed that module past the guard below — the bottom of the parse side,
    # because it reads tokens and nothing else.
    "names",
    # What a noun phrase *describes* (`nouns`) sits under what it *points at*
    # (`references`): CR 109's "what is this object" against CR 115's "how many
    # does the spell choose, and is a player one of them". They were one module
    # until Antiquities' token phrases pushed it past the guard below, and the
    # order is what keeps the split from folding back — the filter parser must
    # never need the quantifier one.
    # Which zone a noun phrase is scoped to, and whose zone it is ("cards
    # **from an opponent's graveyard**"). Split out of `postmodifiers` at the
    # guard below, along the boundary that module's own docstring draws when it
    # lists what a postmodifier relates an object to: the controller, another
    # object, **or a zone**. A family rather than a cut, because CR 404.1 makes
    # both halves one answer — a card is in the graveyard of the player who owns
    # it, so the pile and the seat are read together or a phrase names the wrong
    # pile. Below `postmodifiers`, which calls it and is never imported back.
    #
    # The name is `lowering/zones.py`'s, and the two are one subject from
    # opposite ends: that module decides which zone an object **goes to**, this
    # reads which zone it is **already in**. Different packages, neither
    # importing the other, so the mirror re-forms rather than colliding — the
    # one thing `statics` could not do.
    "zones",
    # `seat_relations` split off `postmodifiers` at Weatherlight's Phase 0, when
    # that module sat one line from the guard with a wave about to open on it.
    # It is the "whose is it" half of a noun phrase — ten seat and ownership
    # readings that write one key each — and it sits here because
    # `postmodifiers` reads it and it reads nothing back.
    "seat_relations",
    # `histories` split off `postmodifiers` at Tempest's Phase 0, three lines
    # under the guard below and with two wave-3 groups about to open on it —
    # the shared-module case SET_PLAYBOOK.md says to pre-split rather than to
    # brief. The line is the one that module's docstring draws and then does
    # not finish: a postmodifier names a relation "to the controller, to
    # another object the sentence names, to a zone", and the fourteen clauses
    # that moved name a **record** — an attack declaration, a block pairing, a
    # damage ledger, the seat that cast a permanent. Nothing on a board
    # answers one, which is why each has to print "this turn" where the live
    # combat relations left behind must not. It is also the half that grows:
    # a set adds a clause about what happened far more often than it adds a
    # way to say what an object *is*.
    #
    # No mirror name to reuse, and the near miss is the reason to say so:
    # `seat_relations` called this family "records" on its way out of the same
    # module, and `records` one layer down is already the parse-side mirror of
    # `lowering/_records.py`, reading a *quantity* off an event. Taking the
    # word here would fork a name inside one package rather than re-form one
    # across two, which is the opposite of what every note in this file asks a
    # split to do.
    #
    # Below `postmodifiers`, which calls it and is never imported back, and
    # above `readers`, whose source-reference production two of its arms ask.
    "histories",
    # A printed **bound on a quantity** — a threshold it is compared against
    # ("power 3 or greater") or a ceiling it may not exceed ("but not more than
    # the creature's toughness"). Split out of `amounts` at Exodus' wave 1, on
    # the seam that module had already written down in prose: its own comment
    # said a comparison "lives with the amounts it compares rather than with
    # the filter that happens to carry one", and the section below it was
    # headed "Caps on a quantity". The cut is those two sections whole.
    #
    # Ranked where `amounts` cannot be: this reads `parse_amount` and nothing
    # in `amounts` reads back, so unlike its parent it is not half of the
    # `nouns` recursion. Above `readers`, which is where these names could
    # *not* go for that same reason — a comparison takes an amount, and
    # `amounts` reads `readers` through `records`.
    #
    # Below `postmodifiers`, `nouns` and `conditions`, its three callers, and
    # `nouns` still re-exports `parse_comparison` under its own name so no
    # caller of `nouns.parse_comparison` moved.
    "bounds",
    # What a noun phrase says its object **has** — "with flying", "with power 3
    # or greater", "with a bounty counter on it", "without flying". Pre-split
    # off `postmodifiers` at Invasion's Phase 0, 32 lines under the guard below
    # with eight groups about to open and the set's narrowings due on exactly
    # this branch. The line is the one that module's docstring never drew: it
    # says a postmodifier names a *relation* — to the controller, to another
    # object, to a zone — and this clause is none of them, nor the record
    # `histories` added to that list. It asks about the described object alone,
    # and where it measures against something else the other end only says how
    # much. It is also the half that grows, and that was measured: since
    # `histories` left, 57 of the 149 lines `postmodifiers` gained and kept
    # were in this one branch, while the combat relations, "attached to …" and
    # "of …" gained none.
    #
    # No mirror name to reuse — no lowering module is about this clause, and
    # `characteristics` is taken three times over for the effects that *change*
    # one. The name is the prefix the draft, the filter and the payload already
    # give these fields (`with_keywords`, `with_named_counter`, …).
    #
    # Below `postmodifiers`, which calls it and is never imported back, and
    # above `bounds` and `names`, whose readers its arms try in order.
    "with_clauses",
    # The trailing half of a noun phrase. Below `nouns`, which hands it the
    # recursive parser rather than being imported back — "blocking target
    # attacking creature" nests a whole phrase.
    "postmodifiers",
    "nouns",
    # What a **count** may be taken over instead of objects — "for each basic
    # land type **among** lands you control" (domain, CR 207.2c) and "a land
    # **of each** basic land type". New at Invasion's wave 1 rather than split
    # out of anything: the two readers were written into `nouns` and took it
    # from 848 lines to 960 in one round, so they were moved before the wave's
    # colour groups — who all extend the noun parser — found the guard there.
    #
    # Above `nouns`, whose object parser reads the phrase on either side of the
    # words, and never imported back: a count position opts in by calling
    # `parse_counted_objects`, where a target or a sweep calls the plain reader
    # and so cannot read "destroy target basic land type among …". Below
    # `phrases` and `where_x`, the two count readers that import it. No mirror
    # name to reuse — the lowering side is one branch of `_amounts.count_spec`
    # — so it carries the name of the AST field it produces,
    # `ObjectFilter.distinct`.
    "distinct",
    # Which **seat** a printed phrase names — CR 102's player, not CR 109's
    # object. Split out of `references` at Urza's Saga's wave-2 integration,
    # when that module reached the guard with **one** line to spare and a third
    # wave still to come. The line is the one `references`' own opening
    # paragraph has stated since the day it was written: "CR 109 is what an
    # object is, CR 115 is how a spell chooses one, and a player (CR 102) is not
    # an object at all". What stayed is the two halves of CR 115 — what a phrase
    # points at, and how many — and this was the third question it carried.
    #
    # Above `nouns`, which it reads for the possessive's noun phrase, and below
    # `references`, which imports it and re-exports `parse_player_ref` under the
    # name every caller already used. It reuses the name `_seats` carries on the
    # `ast` side since Weatherlight and on the `lowering` side since it left
    # `_common`, so the mirror re-forms across all three rather than forking a
    # fourth vocabulary for one idea.
    "seats",
    # The object an *earlier step of the same effect* already chose — "that
    # creature", "those creatures", "the other creature", "that Wall". Split
    # out of `references` at Tempest's Phase 0, when that module sat four lines
    # from the guard with three of the wave's five groups reaching it and no
    # one of them owning it. The line is the one `references`' own docstring
    # drew when the block arrived: these answer CR 115's question with an
    # earlier step as the referent, where everything left up there reads a
    # phrase a **player** answers as the spell resolves. It is also the half
    # that grows — a set adds a spelling of a restated noun far more often than
    # it adds a quantifier or a player form.
    #
    # Above `nouns`, whose object parser the "that non-Wall creature" branch
    # reads, and below `references`, which re-exports every name so `phrases`
    # and the effect families that read one are untouched. No mirror name to
    # reuse: the `that`/`those` quantifiers are read by eighteen lowering
    # modules and owned by none, and `rebinding` further up is the other
    # question — which object a bare "it" names, answered by an AST walk.
    "back_references",
    "references",
    # Whole printed *paragraphs* that are one effect (Tawnos's Coffin,
    # Transmute Artifact, Mana Clash, Natural Balance). Below `statements`
    # because none of them calls back into the sentence parser — each reads its
    # own words to the end — and split out of it when Antiquities' four-sentence
    # cards pushed that file past the guard below.
    "paragraphs",
    # The paragraphs that change a card's **owner** (CR 108.3): Bronze Tablet,
    # Timmerian Fiends, Tempest Efreet. Split out of `paragraphs` at Mirage's
    # third wave, when Natural Balance's paragraph took that module past the
    # guard below. The seam is what the three cards *change* rather than how
    # they read: Juxtapose is sentence-for-sentence the same shape and exchanges
    # **control** (CR 613 layer 2), a different rule with a different duration,
    # so it stayed behind. Beside `paragraphs` at the same level and for its
    # reason — nothing here calls back into the sentence parser either.
    #
    # The name is not a mirror re-forming, which the module's docstring says
    # outright: these three lower in `lowering/zones.py`, so `zones` is the name
    # the rule would ask for, and `zones` on this side already means something
    # else (which zone an object is *already* in). Reusing it would fork a name
    # rather than re-form one.
    "ownership",
    # The paragraphs that turn on a **choice the board cannot show** — a card
    # name (Necromentia, Demonic Consultation, Nebuchadnezzar, Petra Sphinx,
    # Vexing Arcanix) or a card picked face down from a hand (Stronghold
    # Gambit). Pre-split out of `paragraphs` at Prophecy's Phase 0, when that
    # module sat 37 lines under the guard below with the set's multi-sentence
    # effects about to reach it from more than one group. Half of what the
    # module gained since Antiquities was this run (Petra Sphinx,
    # Nebuchadnezzar, Vexing Arcanix, Demonic Consultation and, at Nemesis,
    # Stronghold Gambit), and it was the one contiguous run that shared a
    # subject the rest did not: what the first sentence chooses, which every
    # later sentence checks.
    #
    # The name is the mirror's: `statement_dispatch_naming` lowers all five
    # nodes these return. Not `names` — that module, under `nouns` far below,
    # reads the literal string a card prints after "named", and no player
    # chooses it — and not `choices`, which probes the sentence after a "Choose …"
    # through `parse_statement`. Everything here reads its own words to the
    # end, so it sits beside `paragraphs` and for its reason.
    "naming",
    # Reading a keyword-ability list off a printed line. Split out of `phrases`
    # at the guard below, reusing the name `lowering/keywords.py` has carried
    # since it left the same family one package over. Below `phrases`, which
    # re-exports it so no caller moved: the boundary is what a phrase *is*
    # (`phrases`) against which keyword abilities it names (here), and nothing
    # in it calls back.
    "keywords",
    # How long an effect lasts (CR 611.2a): the table of printed duration
    # phrases and `_parse_duration`, its one reader. Pre-split out of `phrases`
    # at Invasion's Phase 0, when that module sat 38 lines under the guard below
    # and is the floor every effect family reads — the shared-module case
    # SET_PLAYBOOK.md says to pre-split rather than to brief. The seam is the
    # one `phrases` had been cut along three times already: its docstring listed
    # the word tables it held ("trigger events, durations, counter kinds, board
    # counts, zone names") and each of the others had left along that list.
    # This was the last table of any size, and it is the half that grows with
    # the pool — a row and its paragraph per new printed window — where a
    # fragment production arrives only when a second family asks for one.
    #
    # Below `phrases`, which reads `_parse_duration` for two fragments of its
    # own and is **not** a re-export of it: the twenty other importers were
    # pointed here directly, which is `cost_records`' decision restated. It
    # reads `ast`, the token stream and `engine/turn_state.py`, so it could sit
    # anywhere under its callers; it is here because this is what it left.
    #
    # No mirror name to reuse: no lowering module owns durations (each family
    # maps the kinds it has a sweep for and refuses the rest), and
    # `engine/event_durations.py` — the sweep for the one row that ends on an
    # event — is keyed by this table's kinds, the same word from the other end.
    #
    # The same Phase 0 sent two readers *home* rather than to a new module,
    # because each had exactly one caller and `phrases`' rule is "a fragment
    # two families need": `_accept_literal` / `NUMBER_SLOT` to `where_x`, whose
    # `_BOARD_COUNTS` walk is all that reads them, and
    # `accept_member_state_clause` to `static_lines`.
    "durations",
    "phrases",
    # What a "sacrifice …" clause names, and how it is priced. Split out of
    # `phrases` when Mirage's second wave took that module past the guard below,
    # reusing the name `lowering/_sacrifices.py` has carried since it left the
    # same family one package over — the mirror re-forming rather than forking.
    # The seam is `parse_counted_subject`'s own docstring: these readers are the
    # shared half of one clause, read by three families that never see each
    # other (the board family's sacrifice and its "unless you sacrifice" tails,
    # the combat family's attack cost under CR 508.1g, the stack family's
    # counter tails). **Above `phrases`**, which it reads and which never reads
    # it back: a sacrifice clause is built out of noun phrases and numbers, and
    # none of those is built out of a sacrifice.
    "sacrifices",
    # The paragraphs whose frame is an **upkeep trigger** (Power Leak / Errant
    # Minion, Mishra's War Machine / Minion of Leshrac, Phantasmal Sphere /
    # Rogue Skycaptain). Split out of `paragraphs` along the boundary that
    # module already had: every other paragraph in it is read from a spell's own
    # line or an activated ability, and these are paragraphs only because of the
    # upkeep frame around them. The name is the one `lowering/categories.py`
    # already gives the kinds they lower to and `engine/phases/upkeep_effects.py`
    # gives the registry that runs them, so the mirror re-forms rather than
    # forking.
    #
    # **Above `phrases`**, which it moved past the round the counter-toll
    # paragraph arrived: that production reads a printed mana cost, and
    # `phrases._parse_mana_payment` is the engine's one reader of one. Below
    # `phrases` it would have had to keep a second copy of the symbol loop —
    # the drift this layering exists to prevent — and nothing between the two
    # positions imports this module, so the move costs no other edge.
    "upkeep",
    # The "…, where X is …" clause. Split out of `phrases` at the guard the
    # round two branches both added a definition. The name re-forms the mirror
    # `lowering/where_x.py` has had since round 23.
    #
    # It sat "above `phrases`, whose word tables and literal reader it uses"
    # until Invasion's Phase 0: the literal reader had no other caller and came
    # here, and the one word table it read is `durations` now. It imports
    # nothing from `phrases` any more, so its place above it asserts only that
    # nothing below reads it back.
    "where_x",
    # Which object a bare "it" in an effect names, when the antecedent is
    # **outside** the sentence — a trigger's condition described it, the firing
    # event carried it, an intervening-if recorded a card. Under `triggers`
    # because only one of its rebinders is about a trigger and none needs a
    # production: the walk is about the shape of the AST, so it imports `ast`
    # and nothing else. It also holds `_walk_specs`, the AST walk both halves
    # rewrite through, which is the **whole** edge between them.
    "rebinding",
    # The same question when the antecedent is **in the same sentence**: a
    # target the statement itself announced — the delay's own opener, the
    # clause in front of it, the previous sentence of the printed line, the
    # arm of an alternative. Split out of `rebinding` at the thousand-line
    # guard, on a seam that was measured rather than inherited: no function in
    # either half calls one in the other, and the whole edge between them is
    # one name. The readers were attributed to their callers rather than left
    # in a shared pile — `_announced_target` and `_names_a_target` are read by
    # the in-sentence rebinders and by nothing else, so they came up here,
    # while `statement_bound_target` stayed below where the condition side and
    # `pronouns` read it (`riders` too, until its two possessive readers joined
    # `pronouns`). 493 lines stay and 541 leave, from 977.
    #
    # The two are one *question* and two design problems, which is the honest
    # reason they are two files. An out-of-sentence antecedent is found by
    # asking the condition — one object, known before the effect is read. An
    # in-sentence one is found by walking the statement being rewritten and
    # deciding how far the word reaches, so every rebinder here carries a
    # paragraph about its own narrowness and one of them
    # (`rebind_pump_pronoun_to_sentence_target`) has a whole-pool differential
    # behind it: eight shipped cards print a bare "it" after a targeting
    # sentence and already play correctly, so a walk that rewrote every spec
    # broke all eight.
    #
    # No mirror name to reuse — `back_references` one layer down is the
    # *production* answer to a bound noun and says so in its own docstring,
    # and no lowering family carries this subject. **Nothing is re-exported**:
    # the five callers import from here directly, because a re-export would be
    # an upward import from the layer below and the guard would refuse it —
    # the one case where the `prices` / `readers` arrangement further down
    # this list cannot be copied.
    "sentence_rebinding",
    # Trigger events whose subject the sentence *names* — the source, or the
    # permanent the source is attached to — rather than quantifying it. Split
    # out of `triggers` at the size guard below, along the boundary that module
    # already drew, and under it: these read tokens and build events, and none
    # of them reaches a table.
    # Which printed phrase names which trigger event, as data. Split out of
    # `triggers` at the guard below when two parallel branches' additions summed
    # past it; the boundary is the one that module already had in its own shape,
    # a block of phrase-to-event tables followed by the productions that walk a
    # stream against them. Below `triggers`, and it imports nothing from the
    # reading side, which is what makes it a layer rather than a second half.
    "trigger_tables",
    # ``accept_event_phrase`` alone: matching a table's word run against a line,
    # reading a pre-Sixth-Edition card's self-naming spelling as the modern
    # "this <noun>". A **floor**, not a family — `trigger_matched` walks the
    # `whenever` tables and `triggers` walks the `when` ones, and both owe that
    # substitution the same reading, so it sits under both rather than in
    # either. Above `trigger_tables`, whose nouns it consumes and which is pure
    # data by its own docstring; below both callers, because neither owns it.
    "trigger_phrases",
    "trigger_subjects",
    # CR 603.8's state triggers — a condition that is simply *true* rather than
    # something that happens. The third split off `triggers` and the third along
    # a line the family already had; `triggers` reaches down for the one name,
    # and nothing here reads a word table from up there.
    "state_triggers",
    # What a **cast** trigger's clause narrows on — the fourth split off
    # `triggers` and the fourth along a line the family already had: one
    # chain of productions that all read "…casts a <narrowing> spell" and
    # differ only in which narrowing hangs on the verb. Above `nouns`, whose
    # object parser the unshared-colour clause reads, and below `triggers`,
    # which asks it and is never imported back.
    "trigger_casts",
    # CR 120.4b's damage event and both its ends — who dealt it and who took
    # it. The fifth split off `triggers` and the fifth along a line the family
    # already had: one production reading one event, whose phrase tables are
    # already a module further down. It went when Flesh Reaver's recipient
    # union ("a creature **or opponent**") took `triggers` two lines past the
    # guard below, and it is where the next damage-recipient spelling lands —
    # which is the reason for cutting here rather than shaving the comment that
    # crossed the line. Above `phrases`, whose subject-filter reader both ends
    # of the event use, and below `triggers`, which asks it and is never
    # imported back. No mirror name to reuse: `lowering/damage.py` is a whole
    # family about the *effect* a sentence performs, and this reads the
    # condition that fires one — the split `trigger_casts` already made against
    # `lowering/cards.py`.
    "trigger_damage",
    # The condition clause after `whenever` — every event that word can open.
    # The sixth split off `triggers` and the first that cuts the module rather
    # than lifting a family out of it: `_parse_matched_event` and the three
    # helpers only it calls are the half that **grows with the pool**, and
    # `triggers` keeps the dispatch over the three printed trigger words, which
    # has been stable for sets. `by_node.py`'s rule from Fallen Empires ("the
    # table is a registry either way, and `lower.py` is dispatch") one package
    # over. Above every trigger floor it reads and below `triggers`, which asks
    # it and is never imported back.
    "trigger_matched",
    # The trigger tables and the productions that read them. Split out of
    # `phrases` when Antiquities' trigger work pushed that module past the
    # thousand-line guard below — above `phrases`, whose shared fragments it
    # reads, and below everything that reads a whole line.
    "triggers",
    # The conditions answered by a record kept about a **player** rather than
    # about an object — "one of their opponents was dealt damage this turn"
    # (Antagonism), "that player didn't cast a spell this turn" (Impatience).
    # Split off `condition_clauses` at Urza's Destiny's wave 1, when the second
    # of those clauses took that module past the guard below. The cut is that
    # module's own taken one axis further: it holds every condition answered by
    # a *record*, and every record it holds is about an **object** — a card that
    # left a zone, a creature that died this way. These two are about a seat,
    # and neither touches the noun-phrase vocabulary the rest of the module is
    # built from.
    #
    # Both clauses moved rather than only the new one: a family with one member
    # is a cut, and the point of the guard is to find a boundary that was
    # already there. The name is the one this family already carries on the
    # parse side, beside `seats`, `seat_comparisons` and `seat_relations` —
    # the fourth thing a sentence can say about a player, after which seat it
    # is, how it compares and what it owns: what it **did**.
    #
    # No mirror name to reuse, and the near miss is the reason to say so:
    # `records` is already the parse-side mirror of `lowering/_records.py` and
    # reads a *quantity*, and `histories` reads a record as a narrowing on a
    # noun phrase. These return a whole `Condition`, lowered in
    # `lowering/_record_conditions.py` beside every other condition's, which has
    # never split — so taking either word would fork a name inside one package
    # rather than re-form one across two.
    #
    # Below `record_conditions`, which calls it and is never imported back —
    # that sentence named `condition_clauses` until the record reader these two
    # clauses were cut out of took a module of its own, one entry down.
    "seat_records",
    # The condition clauses answered by a **record** of something already done —
    # "it was a creature card", "a white creature dies this way", "the discarded
    # card was a land card", "you haven't added mana with this ability this
    # turn". Pre-split out of `condition_clauses` at the Phase 0 before Nemesis,
    # when that module sat **fourteen** lines under the guard below: the
    # shared-module case SET_PLAYBOOK.md says to pre-split rather than to brief.
    #
    # The seam was measured, because the two sentences pointing at it disagreed:
    # `seat_records` said `condition_clauses` "holds every condition answered by
    # a *record*" and `conditions` said that module was cut by shape and that
    # the record line "is **not** the line drawn here". Both described one file
    # holding two things. Of the seventeen nodes `_accept_record_condition`
    # builds, sixteen are defined in `ast/records.py`; the imports divided with
    # them (`phrases`, `seat_records`, the colour table and the tokenizer on
    # this side alone; `amounts`, the P/T token and the card-type table on the
    # other alone); and no function in either half called one in the other.
    # 504 of the module's 986 lines were this reader, and it is the half that
    # grows with the pool — ten of the seventeen commits that touched the file
    # grew it, where the counter block has stood still since Tempest.
    #
    # The name is the mirror's: `lowering/_record_conditions.py` took it at
    # Exodus for the reason it is needed here, `records` being already spoken
    # for one layer down as the reader of a record as a *quantity*. So the
    # mirror re-forms across `ast/records.py`, this and the lowering module
    # rather than forking a word. It is not the whole of the subject and its
    # docstring says so — the dispatcher in `conditions` reads eleven short
    # record clauses itself, and three counter records stay with CR 122's chain.
    #
    # Above `seat_records`, which it probes first, and below `conditions`, which
    # imports from here directly: **nothing is re-exported** through
    # `condition_clauses`, which no longer reads either name.
    "record_conditions",
    # The printed clauses a condition is built from — one each, read to its
    # end. Split out of `conditions` at the guard below, along the boundary
    # that module already had in its own shape: `_parse_single_condition` is a
    # dispatcher over the whole vocabulary, and these are the readers it hands
    # a sentence to. The name is `sentence_clauses`' one layer up and for its
    # reason — that module holds the clauses `parse_statement` reads *around* a
    # body, this one the clauses `_parse_condition` reads *inside* one. Below
    # `conditions`, which calls it and is never imported back.
    #
    # What it holds since the Phase 0 before Nemesis is two readers asked of the
    # ability's own source — its card's position in a graveyard, and the
    # counter-state questions (CR 122). The record reader is `record_conditions`
    # above, and the blocker count went to `condition_counts` below, whose
    # docstring had named it as its own subject all along.
    "condition_clauses",
    # The conditions that are a **count** — what a seat controls, how tall a
    # pile is, a life total, what the battlefield holds, the parity of a number
    # an earlier sentence already took. Pre-split out of `conditions` at Urza's
    # Legacy's Phase 0, when that module sat 19 lines under the guard below with
    # three of the wave's groups each about to add an intervening-if to it — a
    # module more than one group reaches is pre-split, because none of them will
    # cross it alone. The cut is by *subject* where `condition_clauses`' was by
    # shape: what stays in the dispatcher is asked of one object — this source,
    # this spell, this flip, this turn — and everything that asks "how many?" of
    # a set is here, which the two modules' imports show rather than assert.
    # No mirror name to reuse: `lowering/conditions.py` lowers both halves and
    # has never split, so nothing over there is forked by taking one. Below
    # `conditions`, which calls it and is never imported back. It sat "above
    # `condition_clauses`, whose blocker count it reads" until that reader came
    # across to its only caller; the two are independent now, and the order
    # between them here asserts nothing.
    "condition_counts",
    "effects", "conditions",
    # The trailing clauses that share a sentence's printed subject — "…gets
    # +2/+0 **and deals 1 damage to you**", "…gains shroud **and doesn't untap
    # during your next untap step**". Split out of `subject_verb` at the guard
    # below, along the boundary that module already had: everything left in it
    # reads a sentence's opening, and these read what is joined onto its end.
    # Above `effects`, because a joiner exists precisely to hold two effect
    # families that may not import each other, and below `subject_verb`, which
    # hands it the statement it has already parsed.
    "conjuncts",
    # Which delayed-trigger event a printed opener names — the table of
    # "at the beginning of <step>" rows and the productions that read a
    # "when <object> <verb>" one. Pre-split out of `delayed` at Tempest's
    # Phase 0, when two of the wave's cards would both have reached that
    # module and neither could own it. The line is the one its own docstring
    # already drew — "which event, and what the later sentence is allowed to
    # refer back to" — and this is the first half, which is also the half that
    # grows with the pool: a row or a production per new printed wording,
    # where what stays is a walk over the dataclass fields that covers a new
    # node by default. **Not** cut between the trailing and leading spellings,
    # which is where the module's shape invites it: both read the same table
    # and the same sub-production, so that cut buys no room. Below `delayed`,
    # which asks these and is never imported back.
    "delay_openers",
    # Delayed triggered abilities, and what the sentence one wraps may refer
    # back to. Below `statements`, which hands it `parse_statement` rather
    # than being imported back — a delayed trigger contains a whole statement.
    "delayed",
    # ``Choose <something>.`` and the sentence that binds what it chose — the
    # target form, the keyword/land-type form, and the probe both live on.
    # Split out of `delayed` at the guard below, along the boundary that
    # module's own docstring drew: it explained why "Choose target <noun>."
    # lived there "for the same reason" a delayed trigger does, and a shared
    # reason is not a shared subject. Below `delayed`, whose delayed-trigger
    # production its binder probe asks and which never imports it back.
    "choices",
    # A sentence that prints no subject — the bare imperative ("Destroy target
    # creature") and the whole paragraphs that open on a noun phrase no subject
    # reader may eat. Split out of `subject_verb` at the guard below, along the
    # boundary that module's own docstring drew: it reads a sentence's opening,
    # and an opening is one of two shapes. Below `subject_verb`, which asks it
    # first and is never imported back.
    # The verb-led half of `imperatives`: a flat dispatch on a sentence's first
    # word. Split out at Mercadian Masques' Phase 0 along the line
    # `imperatives`' own docstring already drew — "an opening is one of two
    # shapes" — with the paragraph openers staying above and the half that
    # **grows with the pool** moving down, since a new printed verb is a new row
    # and a new whole-paragraph shape is rare. Below `imperatives`, which calls
    # it at its tail and is never imported back, and above everything it reads.
    "imperative_verbs",
    "imperatives",
    # The verbs whose subject is a *seat* — "target player draws a card", "each
    # player sacrifices a creature", "that player may pay {R}{R}". Split out of
    # `subject_verb` at the guard below, along the seam that module's dispatch
    # had drawn for itself: one contiguous run of branches, every one gated on
    # `isinstance(source_spec, ast.PlayerRef)`, and nothing between them was.
    # Below `subject_verb`, which asks it in one call at the point the run's
    # first branch sat — the branches are arms of one fall-through chain and
    # their order is the production — and which hands both its upward calls
    # (`parse_optional_action`, and itself for the "you put …" re-entry) rather
    # than being imported back.
    "player_verbs",
    # The `<subject> <verb> …` opening. Split out of `statements` at the guard
    # below, and under it: `statements` hands it `parse_optional_action` rather
    # than being imported back, the same inversion `delayed` makes.
    "subject_verb",
    # The clauses `parse_statement` reads *around* a body — the leading "For
    # each …," and linked-duration openers, the trailing "unless <player> pays
    # <cost>" toll and alternative sweep, and the rounding that distributes
    # across a chain. Split out of `statements` at the guard below when a
    # parallel wave's toll production crossed it, along the boundary
    # `parse_statement` already drew in its own shape: frame, body, frame.
    # Below `statements` and handed `_parse_statement_body` rather than
    # importing it back — the same inversion `subject_verb` and `delayed` make.
    # The **toll** — "unless <player> <pays a price>", and what each way of
    # covering it buys. Split out of `sentence_clauses` at the guard below,
    # along the boundary that module's own docstring drew: everything left
    # there says what a clause does to the *shape* of the sentence, and these
    # say what price is offered, to whom, and what paying it buys. It is the
    # half that grows with the pool — the printed currencies are mana, a
    # discard, a mill, a counter, a card put back on a library and a sacrifice,
    # one more every set or two.
    #
    # Below `sentence_clauses`, which re-exports it so `statements` keeps the
    # one import it had, and above `effects`: these productions read whole
    # *sentences* as prices, which is exactly what separates them from
    # `prices` at the bottom of this list — that one reads printed symbols and
    # is a floor under `phrases`.
    "tolls",
    "sentence_clauses",
    # `leading_iteration` split off `statements` at Weatherlight's Phase 0, when
    # that module sat at exactly the guard with a wave about to open on it. It
    # is the eight spellings of a loop or count printed *in front of* the
    # sentence, and it sits here because it imports `sentence_clauses`,
    # `subject_verb` and `effects` and is imported by `statements` alone. The
    # statement layer is handed down as parameters, never imported up.
    "leading_iteration",
    # Every sentence whose printed first word is "if" — nine spellings that
    # only wear the word (a mana swap, a replacement, a retarget, a rider) and
    # the one intervening-if that means it. Split out of `statements` at Urza's
    # Legacy's Phase 0, when that module stood 14 lines under the guard below
    # with five parallel groups about to add sentence openings to
    # `_parse_statement_body`. The seam is one the cascade had drawn for itself:
    # a contiguous run of ten branches, every one gated on or opening with "if",
    # and nothing between them was — the same shape `player_verbs` was cut on.
    #
    # The generic conditional went with them rather than staying behind,
    # because it is the fall-through the other nine exist to get in front of;
    # an ordering split across two files is an ordering neither file can state.
    # `statements` reads no "if" opener at all now.
    #
    # Here rather than under `conditions`: that is the *event* half and is
    # spoken for on every side (`conditions`, `ast/conditions.py`,
    # `lowering/conditions.py`), and it may not import a statement production
    # by its own docstring. `control_flow` is the mirror word for the `if_then`
    # wrapper these lower through and sits one layer *above* `statements`, so
    # it cannot be imported from below it either — which is why the name says
    # what the file reads, `static_lines`' answer to the same collision.
    #
    # Below `statements`, which hands down `parse_statement` rather than being
    # imported back — the inversion `subject_verb`, `delayed`,
    # `sentence_clauses` and `leading_iteration` all make.
    "if_openings",
    "statements",
    # A sentence whose subject is a pronoun pointing at the sentence before it
    # ("It gains …", "Untap that creature", "It loses \"enchant creature\""). Split
    # out of `riders` at the guard below, along the boundary that module already
    # drew: these answer "what does this pronoun name?", the rest of `riders`
    # answers "which branch does this clause belong to". Below `riders`, which
    # imports the binding and is never imported back.
    #
    # That edge was two functions wide. `riders` imported the binding for "Its
    # controller creates …" and "That creature's controller reveals …" and for
    # nothing else, and those are this module's question — a possessive naming
    # what the sentence before it removed. They came here at Nemesis' Phase 0,
    # `riders` at 976, and no edge is left between the two in either direction.
    "pronouns",
    # The branches of an offer — "if you do", "if you can't", "when you do",
    # "otherwise". Split out of `riders` at the guard below, along the boundary
    # that module already drew: these answer which *branch* of the decision
    # before it a clause belongs to, where the rest of `riders` answers what a
    # clause says about the step before it. The name is `lowering/control_flow.py`'s,
    # which is what these productions lower through, so the mirror re-forms
    # rather than forking. Beside `riders` and not under it — neither imports
    # the other, and both are handed `parse_statement` by `statements`.
    #
    # Two branches that split left in `riders` followed at Nemesis' Phase 0:
    # "If <condition>, … instead", which writes the same second arm "otherwise"
    # does, and "Each opponent who can't …", which is "if you can't" asked of
    # every seat. One sat at the head of the run this module was cut from and
    # the other inside it. `riders` keeps the third question alone — what a
    # clause says *about* the step before it — and nothing left there appends a
    # step.
    "control_flow",
    # "Repeat this process …" — the sentence that says the sentences before it
    # happen again. Three cards print one and no two of them are the same
    # mechanism (see the module docstring), so they are one family rather than
    # one production. Split out of `parser` at the guard below, along the
    # boundary the sentence loop already draws: each of these is a clause
    # *about* the sentences already read, not a step beside them. Above
    # `statements`, whose parser two of them re-enter to read a restatement,
    # and below `parser`, which is the only module that calls them.
    "repeats",
    # The trailing clauses that attach to a sentence already parsed ("if you
    # do", "…, then …"). Above `statements` because reading one means reading
    # the statement it modifies.
    "riders",
    # How a line's sentences join into one statement — the loop that reads
    # sentence after sentence off whatever token stream it is handed, folds a
    # rider into the step in front of it, and returns the single statement or
    # the `Sequence`. Pre-split out of `parser` at Urza's Legacy's Phase 0, ten
    # lines under the guard below with five groups about to open on the parser:
    # the shared-module case SET_PLAYBOOK.md says to pre-split rather than to
    # brief. The seam is the one `parser`'s own docstring draws when it lists
    # what that file is, and the call graph agreed with the prose exactly —
    # six functions calling each other and no line production among them.
    #
    # Above `riders`, `repeats`, `control_flow` and `pronouns`, whose attachers
    # this loop drives: every one of them left `parser` for this same guard, and
    # none reaches back. Below `parser`, its only caller, whose import of
    # `_statements_from_sentences` is also that name's re-export — and only that
    # name, because `test_import_hygiene.py` reads a re-export nobody pulls as
    # the stale binding a move leaves behind. `riders`' docstring records that "the
    # loop that drives them stays behind in `parser.py` with the line-level
    # productions it belongs to" — true of the seam that sentence describes, and
    # not true of the file: the loop is not a line production, it is what a line
    # production is handed.
    #
    # The name is `lowering/sequences.py`'s, and the two are one subject from
    # opposite ends — this builds the `ast.Sequence` out of the printed
    # sentences and that lowers it, threading each step's records forward.
    # Different packages, neither importing the other, so the mirror re-forms
    # rather than forking, exactly as `zones` and `records` already do.
    "sequences",
    # Whole printed lines whose frame is a *condition* rather than a verb —
    # "As long as <condition>, <effect>", "<effect> as long as <condition>",
    # "During your turn, <effect>". Split out of `parser` at the size guard,
    # along the boundary that module already drew in its own shape: the
    # sentence loop would fail every one of these on a subject it never finds,
    # so they are tried ahead of it and each hands back a whole
    # `StaticAbilityNode`. Above `statements` and `conditions`, whose parsers
    # it calls, and never imported back.
    #
    # The mirror's word is `statics`, which the *lowering* half already holds
    # at `engine/grammar/statics.py` — the one place a mirror name cannot be
    # reused, because both halves would be one file. So the name is
    # `OracleProgram.static_lines`' own, which is exactly what these
    # productions produce, rather than a new one.
    "static_lines",
    # Whole printed lines whose **quotation marks** are what delimits them — an
    # emblem's granted ability, the reanimation Aura's entry line, Necromancy's
    # "becomes an Aura with" sentence. The lexer discards quotation marks, so
    # these are matched against the raw text and `parse_line` tries them ahead
    # of the sentence loop, which would refuse every one on punctuation it never
    # sees. Split out of `parser` at the size guard; above nothing, and below
    # `parser`, its only caller — the one production that has to re-enter the
    # line layer takes that entry point as an argument rather than importing it
    # back, which is the cycle this order forbids.
    "quoted_lines",
    # Whether the payment path can collect a printed cost object — the three
    # gates the cost clause asks before admitting a "Sacrifice <noun>",
    # "Exile <noun>" or "Put a counter on <noun>". Split out of `costs` at the
    # size guard; below it, its only caller, and reading noun phrases and the
    # filter floor. The name is the lowering side's own: `lowering/_filters.py`
    # calls these "the two cost gates that answer 'may this phrase be
    # charged?'", so the mirror re-forms rather than forking a vocabulary.
    "chargeable",
    "costs", "parser",
]
# `by_node` is the node-type registry `lower` dispatches through. It left
# `lower.py` when Fallen Empires took that module past the size guard, for
# the reason `lowering/_records.py` records about the two tables that left
# it first: the table is a registry either way, and `lower.py` is dispatch.
# Below `lower` and above `lowering`, which is exactly what it reads.
# `statement_dispatch` left `lower.py` when Alliances' third wave took that
# module past the size guard with **no single branch at fault** — four groups
# each added a few arms under the cap and the sum crossed it. It is the same
# cut `by_node` made and for the same stated reason: `lower.py` is dispatch,
# and the half that *grows* with the pool is the half that moves. Both halves
# are dispatch here, so the chain of 79 type arms goes and the line wrappers
# around it stay. Below `lower`, which re-exports `lower_statement` so the
# name's address is unchanged, and above `by_node`, which it reads.
# `statement_dispatch_naming` is that chain's own split, taken at Tempest's
# Phase 0 rather than at its integration: eight lines of headroom with five
# groups about to land arms is the "shared module" case SET_PLAYBOOK.md says to
# pre-split. Below `statement_dispatch`, which calls it and continues its chain
# on a None — the contract `by_node` already has one layer further down.
LOWER_LAYERS = [
    "lowering", "statics", "by_node",
    "statement_dispatch_naming", "statement_dispatch", "lower",
]

# `library` joined on the parse side when The Dark pushed `effects/cards.py`
# past the size guard: search, look-at and the library's top split off, reusing
# `lowering/library.py`'s name so the two halves mirror rather than fork.
# `prevention` joined on the parse side when `effects/damage.py` reached the
# size guard: the shields, the redirects and Whippoorwill's lock split off,
# reusing `lowering/prevention.py`'s name so the two halves mirror rather than
# fork. It carried the **redirects** as well until Visions gave them
# `effects/redirection.py`, and it carried CR 615.8's until Exodus gave it
# `effects/damage_instances.py`; what it keeps is the shield that names a
# recipient. `_parse_source_of_choice_effect` still reads one printed sentence
# and returns either node (CR 615.8's "a source of your choice" names the
# damage; the clause after the comma decides what happens to it), which is why
# it moved whole rather than being divided — two parse modules would be one
# importing the other, which is precisely the coupling this list exists to
# forbid.
# `counters` joined the parse side when `effects/characteristics.py` reached
# the size guard, reusing the name `lowering/counters.py` had carried since it
# left the same family one package over — the mirror re-forming rather than
# forking, which is what these notes keep asking for. The line is the CR's own
# and is the one the lowering side already drew: a counter (CR 122) is a marker
# on an object, and what a `+1/+1` counter does to power is a layer-7
# consequence rather than the counter itself. The one fragment the two families
# shared, `_expect_counter_kind`, went down into `phrases` rather than staying
# with either — a production two families need has no home inside one of them.
# `returns` joined the parse side when `effects/board.py` reached the size guard
# a third time, reusing the name `lowering/returns.py` has carried since Fallen
# Empires. The line is `board`'s own docstring: a return names **two** zones,
# the one an object leaves and the one it goes to, and that pair is what picks
# the handler, where everything left behind acts on a permanent where it stands.
# The one fragment both halves read, `_parse_further_subjects`, went down into
# `phrases` rather than travelling with either — the same move
# `_expect_counter_kind` made when `counters` left `characteristics`.
# `tapping` joined the parse side when `effects/board.py` reached the size
# guard, reusing the name `lowering/tapping.py` had carried since it left the
# same family one package over — the third time the mirror has re-formed rather
# than forked, after `prevention` and `counters`. The line is the one the
# lowering side already drew: tapping is a keyword action on one permanent
# (CR 701.20) and "doesn't untap during its controller's next untap step" is
# what a card prints beside it, where the rest of `board` destroys, bounces,
# sacrifices or attaches. The two families share no fragment — `parse_recipient`
# and `parse_bound_subject` are `references` and `phrases`, one level down.
# `attachments` joined the parse side the fourth time `effects/board.py`
# reached the size guard, reusing the name `lowering/attachments.py` had
# carried since it left the same family one package over — the mirror
# re-forming rather than forking, for the fourth time after `prevention`,
# `counters` and `tapping`. The line is the one the lowering side already drew:
# an attachment is a **relation between two permanents** (CR 301.5, CR 701.3),
# and both productions read a pair — the object and the host it goes onto, and
# the seat that will pick that host against a legality measured across the pair
# ("a creature that this card could enchant", CR 303.4a). Everything left in
# `board` destroys, returns or sacrifices one permanent at a time. The two
# families share no fragment: both halves of an attachment go through
# `references.parse_recipient`, one layer down.
# `search` joined the parse side when `effects/library.py` reached the size
# guard, along the boundary that module's own docstring had already drawn in
# naming its contents "search, look-at, and the library's top". The line is
# CR 701.19's: a *look* shows a fixed number of cards off the top and leaves the
# pile otherwise untouched, where a **search** walks the whole library for a
# card the sentence describes and ends in a shuffle — and the filter,
# destination, reveal and shuffle vocabulary that reads appears nowhere else in
# the family. `_parse_search_library` is the only name outside the new module
# that anything reaches for, and nothing left in `library` calls into it.
# Asymmetric the *other* way from the families below: the lowering side has no
# `search`, because a tutor lowers to one `search_library` instruction however
# elaborately its sentence is printed. The words are where the work is, so a
# near-empty `lowering/search.py` would buy back the symmetry and cost the
# thing symmetry is for — exactly the reasoning `zones` records in reverse.
# `types` is the *first* family to arrive on the parse side after the lowering
# side already had it — every asymmetry recorded here so far was written the
# other way round, and `lowering/types.py`'s own docstring predicted this file
# would stay unwritten ("a near-empty `effects/types.py` would buy back the
# symmetry and cost the thing symmetry is for"). It was right when it was
# written and wrong two sets later: the `becomes` verb's five branches are 316
# lines on their own, and `effects/characteristics.py` had reached 985 with the
# P/T family beside them, sharing no helper. The prediction was about a size,
# and the size changed.
# `exile` joined the parse side at Alliances' third wave, when two branches
# each grew `effects/cards.py` under the guard and the sum crossed it — the
# integrator's split, because no single branch was at fault. It reuses
# `lowering/exile.py`'s name, which has been a lowering-only family since
# before the parse half existed, so the mirror re-forms rather than forking:
# the same move `prevention` and `counters` made, in the other direction.
# `tokens` joined the parse side at Mirage's second wave, when the token
# production grew a board-count multiplier and `effects/game.py` crossed the
# guard. It reuses `lowering/tokens.py`'s name — a lowering-only family since
# Fallen Empires took *that* module past the cap — so the mirror re-forms rather
# than forking, the same move `exile`, `prevention` and `counters` each made.
# The boundary is CR's: a token is an **object the game creates** (CR 111.1),
# where everything left in `game` changes the state a *player* is in — life,
# extra turns, winning, losing, ante, the choices a sentence makes.

# `destruction` joined the parse side the fifth time `effects/board.py` reached
# the size guard, reusing the name `lowering/destruction.py` has carried since
# it left the same family one package over — the mirror re-forming rather than
# forking, after `prevention`, `counters`, `tapping` and `attachments`. That
# module's own note below records the asymmetry as settled ("the parse side
# stays in `effects/board.py`, where destroy is one production reading the same
# noun phrase as the rest"); like `types`' prediction one paragraph up, it was a
# claim about a *size*, and the size changed. The line is the one the lowering
# side already drew and it is the CR's own keyword action: destroying a
# permanent (CR 701.7) is not sacrificing one (CR 701.17), returning one to a
# hand or phasing one out (CR 702.26), which is what `board` keeps. What travels
# with the verb is what only the verb prints — the "unless its controller pays"
# offer and its life half, CR 701.15c's "destroyed this way … can't be
# regenerated" rider, and the per-payer sweep.
#
# **The split moved one fragment down rather than sideways.**
# `_parse_further_subjects` — the union of noun phrases one verb reaches — was
# in `board` and is now in `references`, because `destruction` needs it too and
# a fragment two families need is not one family's property. It went to
# `references` rather than to `phrases` (where the branch first put it, and
# where a second group's move would have summed past the guard) because it
# reads `parse_recipient` and `parse_bound_subject`, both defined there; five
# modules read it now, `phrases` re-exporting it under its old name.
# `reveal` joined the parse side at Tempest's second wave, the second time
# `effects/library.py` reached the size guard and along the *other* half of the
# line `search` was cut on. CR draws it, inside one rule: a **reveal**
# (CR 701.20a) shows a card to all players, and a **look** (CR 701.20e) follows
# the same rules "except that the card is shown only to the specified player" —
# which is why a reveal is recorded (`Game.record_reveal`) and a look is not, and why a
# card's next sentence may talk about what a reveal turned up. The call graph had
# already fallen apart there: `_parse_reveal_top` and the two acceptors behind it
# are reached from the imperative dispatcher and from each other, and
# `_parse_look_at_hand` and its six tails from the look dispatcher and from each
# other. Neither module calls the other.
# Asymmetric the same way `search` was until Visions: `RevealTop`,
# `RevealTopToHandOrBottom`, `RevealTopOpponentChooses` and `RevealUntil` all
# lower in `lowering/library.py` a few lines from the look-at lowerings, because
# a reveal lowers to one instruction however elaborately its sentence is
# printed. A near-empty `lowering/reveal.py` would buy back the symmetry and
# cost the thing symmetry is for.
# `damage_instances` split off `effects/prevention.py` at Exodus' Phase 0, when
# that module sat **ten** lines under the guard below with two of wave 1's five
# groups about to land productions in it — the shared-module case
# SET_PLAYBOOK.md says to pre-split rather than to brief. The line is the CR's
# own, and both halves of it are printed in rule 615: a CR 615.7 shield is a
# pool spent by points and "count[s] only the amount of damage; the number of
# events or sources dealing it doesn't matter", where CR 615.8 modifies "the
# next instance of damage from that source, regardless of how much damage that
# is". So `prevention` keeps the sentences that name **what is protected** and
# this one takes the sentences that name **whose damage it is** — the Circles of
# Protection, Nova Pentacle, Mercenaries, Soltari Guerrillas and Desperate
# Gambit — whose recipient is optional and, on Penance, absent.
#
# The call graph was already two components with **zero edges between them**,
# and the one coupling was deliberate: both halves called
# `_parse_prevented_this_way_rider`, the single reader of CR 615.5's rider. It
# went down to `grammar/prevented_riders.py` rather than travelling with either
# — the same move `_expect_counter_kind` and `_parse_further_subjects` made when
# `counters` and `destruction` left their families.
#
# `_parse_source_of_choice_effect` returning either node is why this half could
# not go to `redirection`, and moving it whole is what keeps that true: no
# module holds half of it, and this one carries both endings for the reason it
# always did. There is no import between the two modules in either direction.
# Parse-only, the same shape `search`, `reveal`, `text_changes` and
# `damage_locks` record: all six productions lower a few lines from the shields'
# in `lowering/prevention.py` and `lowering/redirection.py`, because a Circle of
# Protection lowers to one shield instruction however many ways its sentence
# spells the source. The words are where the work is.
# `permissions` arrived on the parse side at Exodus' first wave, a set-and-a-half
# after the lowering side split it off `lowering/exile.py` — the mirror
# re-forming under a name that already existed, which is what a split owes
# before it invents one. `effects/cards.py` reached the guard on Manabond's
# reveal-and-empty template, and the line inside it is the CR's own: every other
# production there is a card **moving** (drawn, discarded, milled, searched out,
# revealed), and CR 601.3's permission moves nothing — it grants leave to cast
# or play an object that stays where it is. The call graph had already fallen
# apart along it: `_parse_cast_permission` is reached from the statement
# dispatcher alone and `_accept_spell_type_union` from `_parse_cast_permission`
# alone, and neither calls anything left behind. Both moved byte-identically,
# so no compiled program moves.
# `production_changes` split off `effects/mana.py` at Urza's Destiny's Phase 0,
# when that module sat **twelve** lines under the size guard with a parallel
# wave about to land productions in it — the same pre-split `damage_instances`
# and `prevented_riders` were taken at Exodus' Phase 0, and for the same stated
# reason. The seam is the one `effects/mana.py`'s own first sentence had already
# drawn and named: "Mana: producing it, **and changing what a permanent
# produces**". It is the CR's line as well — CR 605's mana ability resolves into
# a pool *now*, where CR 611.2's continuous effect changes what a land will make
# *later* and adds nothing itself — and it is the one `control_changes` and
# `text_changes` draw beside it. The call graph was already two components with
# zero edges between them: `_parse_produced_mana_word` and its word table are
# read by the three moved productions alone, and `references.parse_target_spec`
# by no production left behind. There is no import between the two modules in
# either direction, and the block moved byte-identically, so no compiled program
# moves. Parse-only, like `search`, `reveal`, `text_changes` and `damage_locks`:
# all three sentences lower within fifty lines of each other in
# `lowering/mana.py`, because a swap lowers to one instruction however many ways
# its sentence spells the tapper. A near-empty `lowering/production_changes.py`
# would buy back the symmetry and cost the thing symmetry is for.
# `retargeting` split off `effects/stack.py` in the same Phase 0 and on the same
# arithmetic — 986 lines, fourteen under the guard, with a wave about to land.
# The seam is the one that module had recorded by **omission**: its docstring
# enumerates its subjects — countering, the two copy templates, the modal head,
# the closed list of unpaid-cost penalties, the activation restrictions — and
# has never named a retarget among them. The line under the omission is the
# CR's: everything left in `stack` acts on a stack object as a *whole*, where
# CR 115.7's re-aim leaves the object where it is, resolving exactly as printed,
# and changes one of the choices made when it was announced (CR 601.2c). The
# call graph was already two components, with the one edge *inside* the moved
# half (`_parse_change_target` reads `_accept_targets_only`) and none across:
# `readers.accept_source_reference_spec` travelled with them because nothing
# left behind reads it, and `parse_target_spec` / `parse_player_ref` are one
# layer down rather than siblings, so both modules keep them. There is no import
# between the two in either direction, and the block moved byte-identically, so
# no compiled program moves. Parse-only for `damage_locks`' reason: all three
# arrangements build one `ast.ChangeTarget` — which is what makes them three
# arrangements rather than three effects.
EFFECT_FAMILIES = ["damage", "characteristics", "base_pt", "types", "board", "cards", "exile", "stack", "retargeting", "combat", "game", "mana", "production_changes", "library", "search", "reveal", "control_changes", "prevention", "damage_instances", "redirection", "damage_locks", "counters", "tapping", "attachments", "tokens", "returns", "text_changes", "destruction", "zones", "hand", "permissions", "requirements",
                   # `separations` arrived whole at Invasion's first wave —
                   # CR 700.3's two piles, on all three sides at once
                   # (`effects/`, `lowering/`, `ast/`). Not a split: nothing
                   # crossed a cap. It is a family because its six printings
                   # share one procedure and no noun — cards off a library,
                   # cards in a graveyard, permanents on a battlefield — so no
                   # existing family's line ("a pile being looked through", "an
                   # object put back", "destruction") holds more than two of
                   # them. Phyrexian Portal's face-down split stays in
                   # `library`, which is where a pile somebody *looks through*
                   # belongs.
                   "separations"]
# `redirection` arrived on the parse side at Visions' first wave, a set after
# the lowering side split it off `lowering/damage.py` — the mirror re-forming
# rather than a new vocabulary, which is what this file asks a split to do.
# `effects/prevention.py` crossed the guard below on Remedy's divided pool and
# Honorable Passage's reflecting rider, and the four productions that came out
# are exactly the four whose lowerings already lived in `lowering/redirection.py`
# and whose lowerings never lived in `lowering/prevention.py`: two redirects
# (Shimian Night Stalker, Blood of the Martyr), Soul Echo's counters-instead-of-
# damage and Blind Fury's doubling. CR 615 removes the damage; all four of those
# leave it happening and change one of its terms.
# `_parse_source_of_choice_effect` did not go with them, and still has not: it
# reads CR 615.8's seven opening words and returns *either* node depending on
# the clause after the comma, so a module holding half of it would import the
# other half — the coupling this file's family rule exists to prevent. At
# Exodus' Phase 0 it moved **whole**, into `damage_instances` above, which
# changes nothing about that: one printed sentence, one production, one module,
# and no import between any of the three in either direction.
# `damage_locks` split off `effects/prevention.py` at Tempest's third wave,
# when Soltari Guerrillas' redirect tail took that module three lines past the
# guard. The line is the one `lowering/prevention.py`'s own section header had
# already drawn and named — *the lock* — and it is neither of the two families
# beside it: "damage … can't be prevented or dealt instead to another permanent
# or player" (Whippoorwill, Lava Burst) is a sentence **about** the shields and
# the redirects rather than a member of either, and it lowers to a mark they
# both read. Which is why it could leave without coupling anything: the split
# adds no import in either direction, and the eleven printed words the two
# sentences share are defined in the new module and read only there.
# The second parse-only family after `search`, `reveal` and `text_changes`, and
# for their reason read the other way round: the words are where the work is,
# and both sentences lower to one instruction apiece beside the shields they
# forbid. A near-empty `lowering/damage_locks.py` would buy back the symmetry
# and cost the thing symmetry is for.
# `hand` arrived on the parse side at the same wave, when `effects/cards.py`
# crossed 1,002 lines and `lowering/cards.py` was nine from the guard. The
# line is CR 402's own word: what a sentence does to a *hand* — reveal it,
# discard from it, take a card at random out of it — against what
# `cards` does to a card wherever it is. Both halves split in the same round,
# so the mirror formed rather than re-formed.
# `zones` used to be one of the asymmetries below — the note read "a near-empty
# `effects/zones.py` would buy back the symmetry and cost the thing symmetry is
# for", because zone movement is one `return`/`exile`/`put` production each on
# the way in and a decision about *which handler moves the object* on the way
# out, so `lowering/board.py` outgrew the cap while `effects/board.py` stayed
# small. That reason expired at Mirage's third wave, the way `library`'s did at
# Alliances': `effects/library.py` crossed the guard and the half that came out
# is not near-empty. What left is every production that moves a pile of cards
# between zones with **nobody looking through it** — a library exiled whole, N
# cards off the top, a card put on a library, a graveyard or a hand shuffled in,
# a bare shuffle — against the looking that stays, which is that module's own
# printed criterion ("a pile being looked through"). Three of the six lower in
# `lowering/zones.py`, so the split re-forms the mirror rather than forking it.
# `library` and `mana` split out of `lowering/cards.py` the same way when it
# reached 959 of the 1,000 lines: the hidden-zone flows and mana production
# each lower to far more than their parse halves read. `mana` is no longer one
# of the asymmetric ones — `effects/cards.py` and `ast/cards.py` reached the cap
# in their turn and split off the same family under the same name, which is the
# mirror re-forming exactly as this note asked for. `library` still has no parse
# half, and `effects/cards.py` keeps the search flows for that reason.
# `counters` split out of `lowering/characteristics.py` at 975 lines, the day
# before a set ingest: a counter (CR 122) is a marker on an object, not a
# characteristic of it, and the two halves shared no imports. `keywords` split
# out of the same module the second time it reached the guard, on the same
# reasoning: CR 208 is what a creature's P/T *is* (layer 7), CR 702 is an
# ability it *has* (layer 6), and the two families shared no helper.
# `prevention` split out of `lowering/damage.py` at 1,011 lines, the round a
# two-source shield landed. The parse side keeps prevention with damage because
# the two read the same recipient and duration vocabulary; the lowering halves
# share not one helper, which is the same asymmetry the families above record.
# `attachments` split out of `lowering/board.py` at 1,008 lines, the round
# Takklemaggot's reattachment landed. An attachment is a *relation between two
# permanents* — every production in it lowers a legality measured across a pair
# (CR 303.4j) — where the rest of `board.py` lowers effects on one permanent at
# a time; the two shared one name, and that already lived in `_events.py`.
# `redirection` split out of `lowering/damage.py` at exactly the 1,000 lines
# that module had been sitting on — twice in one round, by two branches that hit
# the cap independently and cut it in the same place (The Dark's halved damage,
# and Tracker's mutual bite). The line is the CR's own: a redirection is a
# replacement effect (CR 614.9), where every other production in `damage` deals,
# counts or shields it — the damage is still dealt, in full, by the same source,
# and only its recipient moves. The two halves shared no helper, the same
# asymmetry `prevention` recorded above when it left the same module, and the
# parse side keeps all three with damage because they read the same recipient,
# source and duration vocabulary. `fighting` left `damage` the same round on the
# CR's other line: CR 701.14 is a keyword action, an atomic exchange between two
# creatures (701.14b — if either has left, neither deals damage), where
# everything left behind is one source dealing to a recipient.
# `returns` split out of `lowering/zones.py` at 1,004 lines, along a boundary
# the file already had: one function was 618 of them. The rest of `zones`
# decides where an object *goes* when something puts it somewhere; a return
# also names where it comes **from**, and it is the pair of zones that picks
# the handler — graveyard->hand, graveyard->battlefield and
# battlefield->owner's hand read three different kinds of index. Asymmetric
# like `zones` itself and for the same reason: the parse side is one
# production.
# `types` split out of `lowering/characteristics.py` at 982 of the cap, the
# round a targeted land animation (Balduvian Conjurer) and a targeted
# land-type change (Orcish Farmer) landed together. The line is the CR's own
# and the one `engine/land_types.py`, `engine/land_animation.py` and
# `engine/keywords.py` already draw one package over: CR 208 is how big a
# permanent is, CR 105 what colour it is, CR 612 what its text says — and
# CR 205 is what it **is**. The two halves share no helper. Asymmetric like
# `zones` and `returns`: the parse side stays in `effects/characteristics.py`,
# where every one of these is a branch of one `becomes` production reading
# one shared duration clause.
# `destruction` split out of `lowering/board.py` at the cap, and the cap is the
# whole story of where the line is: neither parallel branch crossed it alone —
# one added an activated ability's delayed destroy, the other a per-payer sweep
# — and the sum did. The boundary was already there to be found. It is the CR's
# own keyword action: destroying a permanent (CR 701.7) is not sacrificing one
# (CR 701.17), regenerating one (CR 701.15), phasing one out (CR 702.26) or
# exchanging control of it, which is what `board` keeps. The two halves share no
# name in either direction, checked at the split. Asymmetric like `zones` and
# `types`: the parse side stays in `effects/board.py`, where destroy is one
# production reading the same noun phrase as the rest.
# `counter_removal` split out of `lowering/counters.py` at 1,002, and like
# `destruction` the cap is the whole story of where the line is: **three**
# parallel branches added to that module and none crossed it alone — a bound
# subject for a placement (Soul Exchange), a chosen one (Thelon's Chant,
# Tourach's Chant) and "remove **all** counters" (Homarid, Tidal Influence)
# — and the sum did. The boundary was already there to be found, and it is
# the CR's own: putting counters on is CR 121.1/121.2 and removing them is
# CR 121.3, and the two ask different questions of a payload. A placement
# asks which object and how many; a removal asks which kind, and whether the
# number is even known yet — "all" and "any number of" each need their own
# instruction kind because a fixed decrement would take exactly one counter
# off a permanent the card says to empty. The two halves share no name in
# either direction, checked at the split. Asymmetric like `zones`, `types`
# and `destruction`: the parse side stays in `effects/counters.py`, where
# both halves fit in 321 lines and `_parse_remove_counter` reads the same
# counter-kind vocabulary as `_parse_put_counter`.
# `tokens` split out of `lowering/game.py` at 1,006, the second cap breach of
# the same wave and by the same shape — additions that merely summed. The
# line is CR's and `engine/tokens.py`'s: a token is an **object the game
# creates** (CR 111.1), where everything left in `game` changes the state a
# *player* is in — life, extra turns, ante, winning and losing. Asymmetric
# like `zones`, `types`, `destruction` and `counter_removal`: the parse side
# stays in `effects/game.py`, where a token line is one production over a
# shared body vocabulary.
# `untap_restrictions` split out of `lowering/tapping.py` at 1,001, the round
# Giant Oyster's fronted linked duration landed — along the boundary that
# module's own docstring had already drawn and then argued against. The line is
# the CR's: CR 701.20 is a keyword action a resolving effect performs now, which
# is every production left in `tapping`, and CR 502.3 is "effects can keep one
# or more of a player's permanents from untapping" — a continuous effect
# (CR 611.2a) whose only observable moment is a turn-based action a turn or more
# later, so every production that moved lowers to a *record* the untap step
# reads back. The name is `engine/untap_restrictions.py`'s, which is the same
# sentence read off a permanent's own printed line, so the mirror re-forms
# rather than forking. The two halves share no name in either direction,
# checked at the split: the one thing they had in common was the scratchpad key
# a tap records what it chose under, and that already lived in `_events.py`
# under the same spelling — a second copy of one record key, deleted at the
# split. Asymmetric like `zones`, `types`, `destruction` and `counter_removal`:
# the parse side stays in `effects/tapping.py`, where "tap it" and "it doesn't
# untap" are printed in one sentence on Frost Breath, Telekinesis and Mind Whip.
# `search` is the first family the *parse* side has and the lowering side does
# not — every asymmetry recorded above and below runs the other way. A tutor
# lowers to one `search_library` instruction however elaborately its sentence
# is printed, so `lowering/library.py` is nowhere near the guard while
# `effects/library.py` crossed it; the words are where the work is. Subtracted
# rather than left in, because a family list that named a module nobody wrote
# would fail the "families do not import each other" test on a missing file
# and say nothing true about the package.
# `reveal` left that exclusion the same day it entered it, which is `search`'s
# history at Visions compressed into one wave. The note at `EFFECT_FAMILIES`
# above predicted the lowering side would stay put, "because a reveal lowers to
# one instruction however elaborately its sentence is printed" — a claim about a
# *size*, and Wood Sage's sorted reveal, Phyrexian Grimoire's graveyard pick and
# Scroll Rack's library-to-hand took `lowering/library.py` to 1,001 lines before
# the wave was over. `lowering/reveal.py` reuses the name the parse side had
# carried for an hour, so the mirror formed rather than forked.
# That cut took the reveals of a library's *top* and left every reveal of a
# *hand* in `lowering/library.py` — six lowerings and the picker's field table,
# a third of the module — while `lowering/reveal.py`'s docstring went on saying
# "everything left in `library` is a look". They followed at the Phase 0 between
# Invasion's two waves (970 lines, two groups' additions, one to each half), so
# no family was added and none was renamed: the line stayed where the CR drew
# it and the code that had been on the wrong side of it moved. It is drawn per
# node, which is why each side keeps one flagged form of the other —
# `RevealHandAndChoose`'s `looked_at` in `reveal`, `LookTopPickToHand`'s
# `revealed` in `library` — and neither module imports the other.
# `text_changes` joins `search` in having no twin on the lowering side: the
# instruction one produces (`mark_text_modified`) lowers in
# `lowering/characteristics.py` beside the colour and P/T changes it sits
# with, and the guard that made it a parse family fired on the *productions*
# alone. A near-empty `lowering/text_changes.py` would buy back the symmetry
# and cost the thing symmetry is for.
# `search` left that exclusion at Visions' first wave: `lowering/library.py`
# crossed the guard below and the search lowerings went into
# `lowering/search.py`, reusing the name the parse side has carried since
# Mirage — the mirror re-forming rather than forking, which is what every note
# below asks for. The line is CR 701.23's own and is the one `effects/` already
# drew: `library` is a pile a flow *shows* somebody, and a search is a pile
# nobody may see, so what it has to carry is which cards the phrase admits and
# where each find lands.
LOWERING_FAMILIES = [
    f for f in EFFECT_FAMILIES if f not in (
        "text_changes", "damage_locks",
        # `damage_instances` is `damage_locks`' reason one word over: all six
        # of its productions lower in `lowering/prevention.py` and
        # `lowering/redirection.py`, a few lines from the shields', because a
        # Circle of Protection lowers to one shield instruction however many
        # ways its sentence spells the source. The guard that made it a parse
        # family fired on the *productions*; the lowerings never crossed
        # anything, and a near-empty `lowering/damage_instances.py` would buy
        # back the symmetry and cost the thing symmetry is for.
        "damage_instances",
        # `production_changes` is `damage_instances`' reason one family over:
        # all three of its productions lower in `lowering/mana.py`, within fifty
        # lines of each other and of the pip clauses, because a produced-mana
        # swap lowers to one instruction however many ways its sentence spells
        # the tapper. The guard that made it a parse family fired on the
        # *productions*; `lowering/mana.py` is 750 lines and crossed nothing.
        "production_changes",
        # `retargeting` is that reason a third time in the same Phase 0:
        # `_lower_change_target` is one function in `lowering/stack.py` (752
        # lines), because all three printed arrangements build one
        # `ast.ChangeTarget` and there is nothing for a second lowering to do.
        # The guard fired on the productions; the lowering crossed nothing.
        "retargeting",
    )
# `base_pt` was appended here when it was a lowering family with no parse twin.
# Tempest's first wave gave it one — `effects/characteristics.py` crossed the
# guard a second time and split along the same CR 613.4b line — so it now
# arrives from `EFFECT_FAMILIES` above and naming it twice would be a list
# disagreeing with itself.
# `permissions` was appended here for `base_pt`'s reason and left the list the
# same way: Exodus' first wave gave it a parse twin (`effects/permissions.py`,
# split off `effects/cards.py` at the guard on the CR 601.3 line), so it now
# arrives from `EFFECT_FAMILIES` above and naming it twice would be a list
# disagreeing with itself.
# `requirements` is the third to make that journey, at Urza's Saga's second
# wave. It was declared lowering-only at Tempest with the reason written down —
# "the parse side keeps both productions in `effects/combat.py`, where each is
# one branch of a verb table, and the guard fired on the lowerings" — and this
# is what happens when the parse half crosses the guard too: `effects/combat.py`
# went 27 lines past it on Okk's declaration comparison and Outmaneuver's
# assignment rewrite, and the requirements were what left, taking the two
# paragraph productions (Nettling Imp, Norritt, Arcum's Whistle) with them
# because their middle sentence *is* the requirement. So it now arrives from
# `EFFECT_FAMILIES` above and naming it twice would be a list disagreeing with
# itself.
] + ["returns", "exile", "keywords",
    # `keyword_removal` is `keywords`' other half, split at Tempest's wave-3
    # integration when two groups' additions summed past the cap with neither
    # at fault. The seam is that module's own first line — "granting one, and
    # taking one away" — and granting is the half that grows, so it stayed.
    "keyword_removal", "redirection", "fighting", "where_x", "control_flow", "counter_removal", "tokens", "upkeep", "untap_restrictions", "loops", "sequences", "life", "prohibitions", "delayed",
     # `ownership` split off `lowering/zones.py` at Weatherlight's wave 2,
     # when two branches' additions summed past the guard with neither at
     # fault. The seam is `zones`' own docstring read as a question: it says
     # everything there answers "which zone does this object end up in", and
     # Bronze Tablet, Timmerian Fiends and Tempest Efreet answer a different
     # one — the card may not move at all, and what changes is *whose* it is
     # (CR 108.3, CR 407). It reuses the name `grammar/ownership.py` has
     # carried on the parse side since Alpha's ante cards, so the mirror
     # re-forms rather than forking.
     "ownership",
     # `shuffles` split off `lowering/zones.py` at Urza's Destiny's wave-1
     # integration, when two groups' additions summed fourteen lines past the
     # guard with neither at fault — `ownership`'s shape one set over, and the
     # seam is the same sentence read the same way. `zones`' docstring says
     # everything there answers "which zone does this object end up in"; a
     # shuffle answers "what order is this library in now", which is a
     # different question about a zone nothing moved into.
     #
     # `_chosen_graveyard_cards` did **not** stay behind, and that was measured
     # rather than assumed: `zones`' "put a graveyard's chosen cards on top of
     # a library" and `shuffles`' "shuffle a graveyard into a library" both
     # call it, so it went to `_piles`, the floor that exists for a leaf two
     # families read. `_REVEAL_TOP_PLAYERS` is the mirror check and came out
     # the other way — it is byte-identical to `_SHUFFLE_LIBRARY_PLAYERS` and
     # stayed, because two facts that happen to hold the same four seats are
     # still two facts.
     #
     # Lowering-only, for `zones`' own reason: the shuffle productions are
     # spread across `effects/library.py`, `effects/zones.py` and
     # `effects/search.py` and none of those is near its guard.
     "shuffles",
     # `tolls` split off `lowering/board.py` at Urza's Saga's second wave, when
     # that module sat eight lines under the guard with a 72-card tail still to
     # come. The seam was not found at the cap: `board.py`'s own docstring had
     # been naming it for sets, calling the "… unless <someone> pays"
     # productions "the one place that split cut a production family in half
     # rather than along it". They are cut along it now.
     #
     # The family is an **offer whose refusal is the effect**, which is why its
     # three printed verbs travel together instead of each going to the family
     # it names: lowering "sacrifice this permanent unless you pay" as a
     # sacrifice and "destroy this creature unless you pay" as a destruction
     # would put the *price* in one family and the *consequence* in another. It
     # reuses the name `grammar/tolls.py` has carried on the parse side since it
     # left `sentence_clauses` for exactly this family — one sentence, "what
     # price is offered, to whom, and what does paying it buy" — so the mirror
     # re-forms rather than forking.
     #
     # `_per_payer_count` stayed behind: it reads an `ast.Sacrifice` for
     # `_lower_sacrifice`'s own per-recipient count and no toll calls it. That
     # was measured at the split rather than assumed, which is the check that
     # keeps a seam from taking a neighbour with it.
     "tolls",
     # `requirements` split off `lowering/combat.py` at Tempest's second wave,
     # the **second** time that module crossed the guard and the second time
     # the line was already drawn — `prohibitions` left on the printed voice,
     # this leaves on CR 506.3's own pair of words. A restriction says a
     # creature *can't* and a requirement says it *must*, and CR 509.1c makes
     # the pair asked in a fixed order ("obeyed to the maximum possible number
     # without disobeying any restrictions"), so neither is the negation of the
     # other. It completes `permissions`/`prohibitions` into the trio the rules
     # use. Asymmetric like `zones`, `library` and `mana`: the parse side keeps
     # both productions in `effects/combat.py`, where each is one branch of a
     # verb table, and the guard fired on the lowerings.
     # `phasing` split off `lowering/board.py` at Visions' third wave, when two
     # groups' additions summed past the guard at **integration** — on nobody's
     # branch, for the third time in this one set. The line is CR 702.26's own: a
     # phased-out permanent has not changed zone and has not changed controller
     # (702.26d, which is why a phase-out must not detach an Aura — the bug that
     # had Cloak of Invisibility destroying itself every turn), where everything
     # left in `board` regenerates, sacrifices, bounces, exchanges control or
     # puts a card on a library's bottom. Asymmetric like `zones`, `library`,
     # `redirection`, `delayed` and `prohibitions`: the parse half stays in
     # `effects/board.py` and the guard fired on the lowerings.
     # `assignment` split off `lowering/combat.py` at Urza's Saga's second
     # wave, the third time that module crossed the guard and the third time
     # the line was drawn somewhere else first: `prohibitions` left on the
     # printed voice, `requirements` on CR 506.3's pair of words, and this
     # leaves on the boundary `engine/combat_assignment.py` has argued since
     # Floral Spuzzem. How much combat damage a creature assigns, and to whom,
     # is CR 510.1 — a turn-based action taken after the declarations are over
     # — where everything left in `combat` lowers CR 506, 508 and 509: who may
     # be declared, who must be, and who may not. Asymmetric like `zones`,
     # `library` and `phasing` below it: the parse halves are two branches of
     # the "assigns" verb table and the guard fired on the lowerings.
     "assignment",
     "phasing",
     # `linked_exile` split off `lowering/exile.py` at Tempest's Phase 0, when
     # that module reached the guard a second time with three of the wave's
     # five groups reaching it and none of them owning it. The cut is not a new
     # line: it is the section divider `exile` had carried whole since the
     # block arrived out of `library` — "Cards exiled *with* a source, and the
     # permission to cast them", with the paragraph under it saying the block
     # was a lodger and that the call graph fell apart cleanly around it.
     # It was a lodger in `exile` for the same reason and the graph fell apart
     # in the same place: `exile` moves an object **into** the zone (CR 406)
     # and refuses the shapes no handler implements, where everything here
     # starts from a pile that is already there and asks whose it is, where it
     # goes and what may be done with it. Neither module calls the other.
     # The divider's second clause had already gone — `_lower_cast_permission`
     # left for `permissions` at Alliances — so this is the first clause of it.
     # The name is `engine/linked_exile.py`'s, the record every shape here
     # pivots on, so the mirror re-forms rather than forking a third word for
     # one subject, the reuse `untap_restrictions` and `base_pt` make of their
     # engine modules. `effects/` and `ast/` have no `linked_exile`, for
     # `permissions`' reason: the guard fired on the lowerings, and the nodes
     # are cards in a zone that sit beside the other card ones.
     "linked_exile",
     # The mirror of `grammar/repeats.py`, and it left `lowering/game.py` the
     # moment the family had a second member: `_lower_repeat_process` had been
     # a section of one there, with its parse half in `parser.py` and no mirror
     # at all.
     "repeats",
     # `exchanges` split off `lowering/control_changes.py` at Mercadian
     # Masques' wave 1, on the seam that module's own **first line** had been
     # naming since it existed: "CR 613 layer 2, and CR 701.12's exchange" —
     # two subjects in a title. Layer 2 is the half that grows (every steal,
     # duration and link lands in `_lower_gain_control`) and CR 701.12's three
     # lowerings had been stable since Exodus, so the stable half left.
     #
     # The seam had to be *read against what pointed at it*, and two things
     # did. `control_changes`' own second paragraph said the parse half was in
     # `effects/board.py`, which had been untrue for three sets — it is
     # `effects/control_changes.py`, split off in its own round — and that
     # paragraph is corrected rather than carried. And the file's tail comment
     # argued the opposite conclusion outright ("an exchange of control is a
     # control change made atomic, which is this module's subject"), which is
     # right about the *subject* and is what a family is, not what a file is:
     # `ownership` made exactly this move one rule over, leaving `zones` while
     # still answering "where does this card end up".
     #
     # What every function here has and none left behind does is CR 701.12a's
     # **atomicity**: each describes both sides in one payload and refuses a
     # sentence whose halves it cannot carry together. A one-sided hand-over
     # has nothing to be atomic about.
     #
     # Lowering-only, like `zones`, `library`, `mana` and `redirection`: the
     # parse half is 329 lines and crossed nothing.
     "exchanges"]
# `delayed` is the lowering-only family Visions' second wave split off
# `lowering/stack.py`, when the counter's "unless its controller pays {1} **and
# 1 life**" (Mundungu) took that module past the guard below. The line is the
# one that module's own section divider had already drawn: everything left in
# `stack` lowers a sentence about an object **waiting on the stack right now**
# -- countering it, copying it, retargeting it, choosing a mode for it -- where
# nothing in `delayed` has a stack object at all. What it produces is a
# *record*: a triggered ability for an event that has not happened (CR 603.7),
# or a target chosen now for a sentence that runs later. Neither reads the
# other. `effects/` and `ast/` have no `delayed` for `loops`' reason: the guard
# fired on the lowerings, and `CreateDelayedTrigger` and `ChooseTarget` are
# nodes that sit perfectly well beside the other statement and stack ones.
# **Both wave-2 groups made this split independently in the same round**, each
# pushed over the guard by its own card (Mundungu's conjoined life price and
# Desertion's countered-card redirect), and the seven functions they moved were
# byte-identical. Only their prose differed. The other account adds two reasons
# worth keeping: the half that moved is the half that *grows* — every set prints
# more delayed riders while the counter templates are largely closed, which is
# the playbook's tiebreak — and `_lower_choose_target` / `_lower_waive_shroud`
# travelled with it because each is the *first* sentence of a two-sentence spell
# whose second sentence is the delayed half, so the pair is read together or not
# at all.
# `search` is on both sides of the mirror as of Visions' first wave:
# `lowering/search.py` split off `lowering/library.py` in the same round
# `effects/search.py` had already split off `effects/library.py`, so the
# exclusion that used to sit above is gone rather than carried.
# `prohibitions` split out of `lowering/combat.py` at Visions' first wave, when
# Heat Wave's board-wide block restriction took that module past the guard --
# it had been sitting nineteen lines under it. The line is the printed voice,
# and it is a real one: everything left in `combat` lowers what a permanent may
# or may not **do** (attack, block, be declared, be removed from combat), where
# the one production that left lowers what may not be done **to** one. "Can't
# be blocked" is a restriction on everybody else's blockers rather than on the
# creature carrying it, and "can't be regenerated" is a restriction on a
# replacement nobody has arranged yet.
# The name is `permissions`' mirror on this same list: that family grants a
# player what the rules alone would not allow (CR 601.3) and this one withholds
# what they would otherwise have.
# A family rather than a floor because `combat` does not read it --
# `grammar/statement_dispatch.py` reaches `_lower_cant_be` directly, one layer
# up -- so nothing is below anything and the two share only `_common` and
# `_events`.
# Asymmetric like `life`, `counters`, `base_pt` and `tokens`: the parse side
# stays in `effects/combat.py`, where `_parse_cant_be` is one branch of the
# "can't" verb table, and the guard fired on the lowering.
# `base_pt` split out of `lowering/characteristics.py` at Mirage's third wave,
# the second time that module crossed the guard below (`counters` left it the
# first time). The line is one CR 613 already draws: what stays *modifies* a
# characteristic -- a pump (7c), a switch (7d), a doubling, a colour, a text
# change -- and what left *replaces* the printed value (613.4b), which is the
# only pair of productions in this grammar reaching `pt.set_base_pt`. The name
# is the one `engine/pt.py` and `engine/handlers/base_pt.py` already carry, so
# the mirror re-forms rather than forking a third vocabulary.
# Asymmetric like `life`, `counters` and `tokens` before it: the parse side
# stays in `effects/characteristics.py`, where a base-P/T sentence is one branch
# of the verb table, and the guard fired on the *lowering*.
# `life` split out of `lowering/game.py` at 1,014, the second time that module
# crossed the guard and along the same seam `tokens` left through one set
# earlier: what stays in `game` changes the state of the **game** (an extra
# turn, winning, losing, ante, a repeated round of offers, a whole-game damage
# history) and what left changes one number on one **player** (CR 118). It is
# also the half that grows with the pool — every set prints life gain and life
# loss, and the branch table for their printed shapes is the whole of the new
# module, where the game half has taken one function in five sets.
# The two shared `_player_recipient`, a three-row table mapping a printed
# player reference onto a recipient key, which went **down** into `_seats`
# rather than staying in either: two families reading it is exactly the
# condition that makes something a floor.
# Asymmetric like `zones`, `types`, `counter_removal` and
# `tokens`: the parse side stays in `effects/game.py` and
# `effects/characteristics.py`, where a life sentence is one branch of the
# verb table each.
# `sequences` is the lowering-only family Mirage's wave 1 split off
# `lowering/control_flow.py`, along the line that module's own docstring
# already drew: it names three composers (`sequence`, `may`, `one_of`) and
# `for_each` had already left as `loops`. The two *offers* stay; the sequence —
# threading each step's records forward, and folding a step that reads an
# offer's record into the branch that writes it — moved. Both halves are
# dispatch, so the cut took the half that **grows with the pool**: every round
# that teaches a sentence to read what the sentence in front of it did lands
# there.
# `permissions` is the sixth lowering-only family, split off `lowering/exile.py`
# at Alliances' third wave when that module crossed the guard below. The line is
# the CR's own: everything left in `exile` **moves an object** into or out of
# the exile zone (CR 406), where every production in `permissions` moves nothing
# — it grants a player permission to do something the rules alone would not
# allow (CR 601.3, and CR 611.2a for how long), and the objects it names stay
# where they already were. The two shared no lowering; what they shared was how
# a pile of cards is described to a payload, which is why that went one floor
# down to `_piles` rather than into either of them. `effects/` and `ast/` have
# no `permissions` for `loops`' reason: the guard fired on the lowerings, and
# `CastPermission` is one node that sits perfectly well beside the other card
# nodes — the same asymmetry `zones`/`library` record above.
# `loops` is the fifth lowering-only family and it split off `control_flow.py`
# when that module reached the guard below. The line is the one that module's
# own docstring already drew: `control_flow` is named after the *composers* —
# `sequence`, `may`, `one_of` — which decide whether and in what order a
# sentence runs, while a loop decides how many times, and what it iterates is a
# **set**: seats in turn order (CR 101.4), permanents the board holds as the
# ability resolves (CR 611.2c), or a number an earlier step recorded. One
# question with one answer, which is why the three lowerings there produce one
# `for_each` instruction with three iterator payloads. Nothing in `loops` reads
# an offer and nothing left in `control_flow` reads a set, so neither imports
# the other. `effects/` and `ast/` have no `loops` for `upkeep`'s reason: the
# guard fired on the lowerings, and `ForEach` is one node that sits perfectly
# well beside the other statement nodes.
# `upkeep` is the fourth lowering-only family and the fourth time the same thing
# happened: `lowering/damage.py` reached the guard below and shed the
# pay-or-consequence shapes — the damage a player is *offered the chance not to
# take* — where everything left in it is a damage event happening. The name is
# the one `grammar/upkeep.py` carries one package over, which
# `lowering/categories.py` had already given the kinds they produce, so the
# mirror re-forms rather than forking. `effects/` has no `upkeep`: the parse
# side's module is a top-level `grammar/upkeep.py` (a paragraph reader, not an
# effect production), which is the same asymmetry `zones`/`library` document
# above, one layer over.
# The AST side has no `library`: what a search or a look-at *is* — the pile, the
# filter, the fate of what was found — is a handful of nodes that sit perfectly
# well beside the other card nodes, and the split that made `library` a family
# on the other two sides was a size guard firing on the productions and the
# lowerings, not on the inventory. A near-empty `ast/library.py` would buy back
# the symmetry and cost the thing symmetry is for: one home per node, findable
# from the family name. Same asymmetry, opposite direction, as `zones`/`exile`
# above — which the lowering side carries and the parse side does not.
# `search` exists on the parse and lowering sides but not in the AST, and for
# the same reason: the size guard fired on the *productions* and the
# *lowerings*, never on the inventory. What a search IS — the pile and its
# filter, the fate of what was found — is a handful of nodes that sit perfectly
# well beside the board and card ones, and a near-empty `ast/search.py` would
# buy back the symmetry and cost the thing symmetry is for: one home per node,
# findable from the family name. Same asymmetry, opposite direction, as
# `zones`/`exile` above. (`control_changes` was the second of that pair until
# Exodus's second wave; see the note under the list.)
# `prevention` is the third, and the same reason a third time: `PreventDamage`,
# `RedirectDamage` and `DamageCantBePreventedOrRedirected` are three nodes that
# sit perfectly well beside the damage ones they describe, and the guard that
# made `prevention` a family fired on the *productions*.
# `counters` is the fourth. `PutCounter`, `RemoveCounter` and
# `PlayerGetsCounters` are three nodes beside the characteristics ones, and the
# guards that made `counters` a family on the other two sides fired on the
# lowerings and then, a set later, on the productions — never on the inventory.
# `tapping` **was** the fifth, for the same reason — until Weatherlight's
# Phase 0, when the inventory guard did fire, in effect: `ast/board.py` sat
# three lines from the cap with a wave about to open on it. Its nine tap/untap
# nodes now live in `ast/tapping.py`, and the mirror re-forms on all three
# sides, which is what these notes keep asking a split to do. The rule below
# stands: a near-empty module bought back for symmetry costs the thing symmetry
# is for; this one was bought by the guard.
# `attachments` is the sixth, and the same reason a sixth time: `Attach` and
# `ChoosePermanent` are two nodes that sit perfectly well beside the board ones
# — the pair they relate is what the *production* reads and what the *lowering*
# measures, never a property of the inventory — and the guard that made
# `attachments` a family on the other two sides fired on the lowerings and
# then, five sets later, on the productions.
# `returns` is the seventh, and the same reason a seventh time: `ReturnToZone`
# and `PutSourceIntoZone` are two nodes that sit perfectly well beside the board
# ones — a return is *two zones and a move*, which is what the production reads
# and what the lowering dispatches on, never a property of the inventory — and
# the guard that made `returns` a family on the lowering side fired on the
# lowerings at Fallen Empires and on the productions here.
AST_FAMILIES = [
    family for family in EFFECT_FAMILIES
    if family not in (
        "search", "prevention", "counters",
        "attachments", "returns",
        # `permissions` is `reveal`'s reason one family over: `CastPermission`
        # is a *card* node and sits in `ast/cards.py` with every other one, so
        # splitting it out to match the parse side would put a node in one
        # family with its lowering's reader in another. The guard that made
        # this a parse family fired on the productions; the node inventory
        # never crossed anything.
        "permissions",
        # `requirements` is `permissions`' reason one family over:
        # `AttacksThisTurnIfAble`, `BlocksThisTurnIfAble` and
        # `DestroyChosenThatDidntAttack` are facts about a **combat** and live
        # in `ast/combat.py` with every other one — the same nodes the
        # restrictions build, which is the point, since CR 509.1c asks the two
        # in one breath. The guard that made this a parse family fired on the
        # productions; the node inventory never crossed anything.
        "requirements",
        # `damage_instances` is `prevention`'s own reason, which is why it sits
        # beside it: `PreventDamage`, `RedirectDamage`, `ChooseDamageSource` and
        # `ChosenSourceNextDamage` are facts about a **damage event** and live
        # in `ast/damage.py` with every other one — the same four the shields
        # build, which is the point. The guard that made this a parse family
        # fired on the productions, and splitting the nodes out to match would
        # put a node in one family with its other reader in another.
        "damage_instances",
        # `damage_locks` is `prevention`'s own reason one line up: the node the
        # two sentences build (`DamageCantBePreventedOrRedirected`) is a
        # statement about a damage event, so it sits in `ast/damage.py` with
        # every other one. The guard that made this a parse family fired on the
        # *productions*; the node inventory never crossed anything.
        "damage_locks",
        # `production_changes` is `damage_locks`' reason one family over: all
        # three of its sentences build the one node `ProducesManaInstead`, which
        # is a fact about **mana** and sits in `ast/mana.py` beside `AddMana`
        # and `AddManaForTappedLand` because that is what it is. The guard that
        # made this a parse family fired on the productions; `ast/mana.py` is
        # 362 lines and crossed nothing, and splitting the node out to match
        # would put it in one family with both of its readers in another.
        "production_changes",
        # `retargeting` is that reason one family over: all three arrangements
        # build the one node `ChangeTarget`, which is a fact about an object on
        # the **stack** and sits in `ast/stack.py` beside `CounterSpell`,
        # `CopySpell` and `ModalNode`. The guard that made this a parse family
        # fired on the productions; `ast/stack.py` is 382 lines and crossed
        # nothing.
        "retargeting",
        # `reveal` is `library`'s and `search`'s reason a third time, in the
        # same package: `RevealTop`, `RevealTopToHandOrBottom`,
        # `RevealTopOpponentChooses`, `RevealUntil` and the rest sit perfectly
        # well in `ast/library.py` beside the look-at ones, because what a
        # reveal *is* — a pile, a filter and the fate of what was turned up —
        # is the same inventory a look is. The guards that made `reveal` a parse
        # and a lowering family both fired on functions; the inventory never
        # crossed anything. (`ast/cards.py` did, in the same wave, and what
        # left it was two nodes going to `ast/library.py` where the rest of the
        # reveals already were.)
        "reveal",
        # `redirection` is the fourth of `types`' shape: `RedirectDamage`,
        # `DoubleCombatDamage` and `DamageBecomesCounterRemoval` are all facts
        # about a **damage event**, and they live in `ast/damage.py` beside
        # every other damage node because that is what they are. The guard
        # fired on the productions (`effects/prevention.py` at 1,103), not on
        # the inventory, and splitting the nodes out to match would put a node
        # in one family with both of its readers in another.
        "redirection",
        # `tokens` is a parse family and a lowering family with no AST module
        # of its own, for `types`' reason below: `CreateToken`,
        # `CreateCopyToken` and `CreateEmblem` are things the *game* gains, and
        # they already live in `ast/game.py` beside the extra turns and the
        # ante. Splitting them out would put a node in one family and both of
        # its readers in another.
        "tokens",
        # `base_pt` is a parse family and a lowering family with no AST module
        # of its own, for `types`' reason directly below: `SetBasePT` and
        # `ChangeBasePT` are what a permanent *is*, and they already live in
        # `ast/characteristics.py` beside every other characteristic node. The
        # guard that made it a parse family fired on Tempest's productions and
        # on nothing else, and splitting the two nodes out would put them in one
        # family with both of their readers in another.
        "base_pt",
        # `text_changes` is the eighth, and the same reason again: `ChangeText`
        # is one node that sits perfectly well beside the characteristics ones,
        # and the guard that made `text_changes` a parse family fired on the
        # productions and on nothing else.
        "text_changes",
        # `types` is a parse family and a lowering family with no AST module of
        # its own: what the `becomes` verb produces is `BecomeCreature`,
        # `GainType`, `ChangeSupertype`, `ChangeLandType` **and** `BecomeColor`,
        # and those five already live in `ast/characteristics.py` because they
        # are what a permanent *is*. Splitting them out would put a node in one
        # family and both of its readers in another.
        "types",
        # `hand` is the same shape once more, and the newest: the nodes the
        # hand-to-library productions build are `PutHandCardsOnLibrary` and
        # nothing else, and it lives in `ast/cards.py` beside every other card
        # node because that is what it *is*. The guard fired on the readers
        # (`effects/cards.py` at 1,002 with Teferi's Puzzle Box in it), not on
        # the inventory.
        "hand",
        # `destruction` is the third of that shape, and it arrived on the parse
        # side after the lowering side had carried it for a set. `Destroy`,
        # `DestroyUnlessPay` and `DestroyEachUnlessPaid` are things done to a
        # permanent on the battlefield, and they live in `ast/board.py` beside
        # the sacrifice, the bounce and the phase-out for that reason. The guard
        # fired on the readers (`effects/board.py` at 1,007), not on the
        # inventory.
        "destruction",
        # `zones` is the fourth of that shape. The nodes its six productions
        # build — `ShuffleLibrary`, `ShuffleGraveyardIntoLibrary`,
        # `ShuffleHandIntoLibrary`, `ExileTopOfLibrary`, `ExileEntireLibrary`,
        # `PutIteratedCardOnLibrary` — are cards in a pile, and they live in
        # `ast/cards.py`, `ast/library.py` and (the two exiles, since Tempest's
        # third wave) `ast/exile.py` beside every other card node. The guard
        # fired on the readers (`effects/library.py` at 1,030), not on the
        # inventory, and splitting the nodes out to match would put a node in
        # one family with both of its readers in another — exactly what `types`
        # records.
        "zones",
    )
]
# `library` left this list at Alliances' third wave, when the size guard below
# fired on `ast/cards.py` itself. The note above records why it was excluded —
# a near-empty `ast/library.py` would buy back the symmetry and cost the thing
# symmetry is for — and that reason expired the moment the inventory grew past
# the cap: the module is 280 lines, not near-empty, and it is cut on
# `effects/library.py`'s own line, so a template has one home per side rather
# than two candidates.
#
# `exile` left it at Tempest's third wave, the same way and for the same
# reason: `ast/cards.py` crossed the guard again — on Living Death's per-seat
# return — and the exclusion's own words were what expired. It read "the guard
# fired on the readers, not on the inventory"; this time the inventory is what
# fired. The fourteen nodes that came out are 300 lines, and the cut is by
# **subject** rather than by reader, which the note in `ast/exile.py` argues at
# length: the two reader-side families disagree about four of them and always
# have, so following either would have split the family down the middle. The
# other exclusions above still hold.
#
# `control_changes` left it at Exodus's second wave, the third time and the same
# way. Its exclusion read "a near-empty `ast/control_changes.py` would buy back
# the symmetry"; the module that came out is 205 lines, so the word that expired
# was *near-empty*. The inventory fired again — `ast/board.py` sat at 977 with a
# wave about to add a node to it — and the cut is the line that module's own
# docstring already draws: "destruction, bouncing, control, sacrifice". The five
# nodes that moved (`GainControl`, `BidLifeForControl`, `ExchangeControl`,
# `ExchangeGreatestManaValue`, `MutualControlOfSets`) all answer "which seat
# does this permanent answer to", where the rest of `board` answers what happens
# *to* it. The other exclusions above still hold.
#
# One correction the same reading turned up: the `zones` note below says
# `ShuffleLibrary`, `ShuffleGraveyardIntoLibrary` and `ShuffleHandIntoLibrary`
# "live in `ast/cards.py`, `ast/library.py` and `ast/exile.py`". All three live
# in `ast/board.py` and always have. The exclusion it argues for is still right
# — the guard that made `zones` a family fired on `effects/library.py`, not on
# the inventory — but the module names in it were never checked, because a
# comment naming a module is not something any test reads.


def _imports(path: Path) -> list[tuple[int, str, bool]]:
    """(line, target, is_sibling) for every relative import in *path*.

    *target* is the grammar-level module name, so `from ..phrases import` in
    `effects/damage.py` and `from .phrases import` in `parser.py` both read as
    `phrases` — the layer list uses one spelling regardless of which directory
    the importer sits in.

    *is_sibling* marks an import within the importer's own subpackage
    (`effects/cards.py` importing `effects/board.py`). Those are the
    subpackage's internal business, checked by the family tests below rather
    than by the layer order — conflating the two is what made the first version
    of this guard fail on every legitimate `from ._common import`.
    """
    tree = source_tree(path)
    inside_package = path.parent != GRAMMAR
    out: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        module = (node.module or "").split(".")[0]
        if inside_package and node.level == 1:
            out.append((node.lineno, module, True))
        elif node.level == 1 + (1 if inside_package else 0):
            out.append((node.lineno, module, False))
    return out


def _layer_modules(name: str) -> list[Path]:
    module = GRAMMAR / f"{name}.py"
    if module.exists():
        return [module]
    return sorted((GRAMMAR / name).rglob("*.py"))


@pytest.mark.parametrize(
    "layers", [PARSE_LAYERS, LOWER_LAYERS], ids=["parsing", "lowering"]
)
def test_layers_only_import_downward(layers):
    rank = {name: i for i, name in enumerate(layers)}
    violations = []
    for name in layers:
        paths = _layer_modules(name)
        assert paths, f"layer {name!r} has no modules — the guard would pass vacuously"
        for path in paths:
            for line, target, is_sibling in _imports(path):
                if is_sibling:
                    continue
                if target in rank and rank[target] >= rank[name]:
                    violations.append(
                        f"{path.relative_to(GRAMMAR)}:{line} imports {target}"
                    )
    assert not violations, (
        "engine/grammar/ layering broken — a module imported from its own layer "
        "or above:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize(
    "package,shared,roof",
    [
        # `_strips` is `effects/`’s first floor, split out of `search` at Urza’s
        # Destiny’s wave 1 when that module sat 28 lines from the size guard with
        # five cards’ worth of new reading to land in exactly one of its
        # productions. Shared rather than a family for `lowering/_recipients`’
        # reason: `search` is the only module that asks, and it exists because
        # that family crossed the guard. The seam is a real one — what stayed is
        # CR 701.23’s library walk, and a strip across a graveyard, a hand and a
        # library shares with it the printed word "Search" and no vocabulary at
        # all.
        #
        # `_other_libraries` is the second, pre-split out of `search` at the
        # Phase 0 before Invasion with that module 29 lines under the guard:
        # the production that reads "Search <player>'s library", which the
        # tutor's entry point reaches through one branch and which called
        # nothing that stayed. It is what makes the paragraph above one
        # function out of date — that production was the *only* caller of
        # `_strips`, so `search` now imports `_other_libraries` and
        # `_other_libraries` imports `_strips`. A floor reading a floor, as
        # `_roles` reads `_targets` on the lowering side; nothing reads back.
        ("effects", ("_strips", "_other_libraries"), ()),
        # `_targets` joins the lowering floors at Prophecy's wave 2, when
        # `_roles` — split out of it at Mercadian Masques — first read it back:
        # a printed "another target" is planned as two roles from the
        # sentence's own `TargetSpec`s (`_targeted_specs`, `_targets_payload`).
        # `FAMILY_SHARED` has called it a floor since Tempest; it was missing
        # here only because `_common` was its one importer, and `_common` is
        # skipped. A floor reading a floor, nothing reads back.
        ("lowering", ("_common", "_filters", "_targets", "_events", "_frozen_seats", "_deaths", "_delays", "_amounts", "_counted_damage", "_counted_pumps", "_bites", "_seats", "_sacrifices", "_records", "_sweeps", "_conjuncts", "_bound_returns", "_bound_exiles", "_described_returns", "_piles", "_counter_stores", "_plus_one_counters", "_named_counters", "_blankets", "_counted_redirects", "_instance_redirects", "_prevented_riders", "_pump_categories", "_zone_categories", "_combat_categories", "_record_keys", "_record_conditions", "_cost_records", "_superlatives", "_recipients", "_collapses", "_declaration_costs", "categories", "conditions"), ()),
        # `costs` is shared beside `_core` rather than a family: a cost is
        # charged on the way to the stack and never lowered, so it has no
        # `effects/` or `lowering/` twin to be a family of — and both
        # `conditions` ("if you paid the cost") and the roof read one.
        # `records` is shared beside `costs` for the same shape: it is the half
        # of `conditions` that asks about a *record* rather than about the
        # board, split out at the size guard, and `conditions` reads it because
        # the `Condition` union is the roof over both halves. A floor, not a
        # family — nothing reads back.
        # `_payloads` joins them at Exodus's Phase 0: it is the 307-line body of
        # `ObjectFilter.to_payload`, moved out when `_references` sat three
        # lines under the size guard. A floor like the rest — it imports
        # `_primitives` and the vocabulary, names no node at run time, and
        # nothing reads back.
        # `lines` joins `statements` in the *roof* slot at Invasion's Phase 0:
        # the ability-line nodes and `AbilityNode`, pre-split out of
        # `statements` 25 lines under the size guard. It is a second storey, not
        # a floor — it imports `statements` for the one name `Statement` and no
        # family at all — so it is exempted here and held by the roof tests below.
        ("ast", ("_core", "_payloads", "_primitives", "_references", "_seats", "_targets", "costs", "records"), ("statements", "lines")),
    ],
    ids=["effects", "lowering", "ast"],
)
def test_families_import_only_their_package_shared_module(package, shared, roof):
    """Inside a subpackage, a family may reach the shared module and nothing else.

    `effects/` has no shared module of its own — its shared fragments are one
    level up in `phrases`, which is why its tuple is empty. `lowering/` keeps
    `_common`, `_events` and `categories` beside the families because all three
    are lowering concerns with no reader outside the package. `_events` split
    out of `_common` when it crossed the size guard below, and is shared for the
    same reason `_common` is rather than by taxonomy: six families read a table
    keyed by trigger-condition kind, and a fragment several families need is not
    one family's property. `ast/` keeps `_core`, the vocabulary its nodes are
    built from, and `conditions` beside it for the reason above.

    `ast/` keeps `records` there too, and it is the one entry that is a *half of
    a family* rather than a vocabulary: `conditions` reads it because the
    `Condition` union names both halves of the split, and nothing reads back.

    `roof` names the modules that sit *above* the families rather than below
    them; they are exempted here and checked by their own tests. Only `ast/` has
    one, because `Effect` and `Statement` are unions over every family and so
    cannot live beside any single one. `AbilityNode` was named in that sentence
    until Invasion's Phase 0 and never belonged in it: it is a union over the
    seven line nodes, which reach the families only through the `Statement`
    they hold — so it lives in `lines`, on top of `statements`, and that module
    imports no family.
    """
    violations = []
    for path in sorted((GRAMMAR / package).glob("*.py")):
        if path.stem in ("__init__", *shared, *roof):
            continue
        for line, target, is_sibling in _imports(path):
            if is_sibling and target not in shared:
                violations.append(f"{package}/{path.name}:{line} imports {target}")
    assert not violations, (
        f"a {package}/ family reached sideways instead of down:\n  "
        + "\n  ".join(violations)
    )


def test_the_condition_union_names_every_condition_node():
    """`ast.Condition` is a hand-maintained list, so it needs this.

    It had drifted **twelve** entries behind the module it names by the time
    Mirage split that module in two — `ZoneHasCards`, `MilledThisWay`,
    `CouldNot` and nine more were nodes the parser produced and the union did
    not know about. Nothing failed, because a `Union` alias is documentation at
    runtime; what it costs is a reader who trusts it. This is the assertion that
    turns forgetting into a failure, and it is the third of its kind in this
    file for the reason SET_PLAYBOOK.md gives: a guard that iterates a
    hand-maintained list needs an assertion that the list is complete.
    """
    import dataclasses
    import typing

    from engine.grammar.ast import Condition, conditions, records

    declared = set(typing.get_args(Condition))
    defined = {
        value
        for module in (conditions, records)
        for name, value in vars(module).items()
        if dataclasses.is_dataclass(value)
        and getattr(value, "__module__", "") == module.__name__
    }
    missing = sorted(cls.__name__ for cls in defined - declared)
    stale = sorted(
        cls.__name__ for cls in declared - defined
        if getattr(cls, "__module__", "").startswith("engine.grammar.ast.")
    )
    assert not missing, f"condition nodes missing from ast.Condition: {missing}"
    assert not stale, f"ast.Condition names nodes that no longer exist: {stale}"


def test_the_ast_roof_only_reaches_downward():
    """`ast/statements.py` may name the families; nothing may name it back.

    It is the one module in the three packages that imports a family, and it
    has to be: a union over every leaf node can only be written where every
    leaf node is visible. What keeps that from being a hole is that the edge
    runs one way — the families are held to `_core` by the test above, so a
    family importing `statements` fails there, and `statements` importing the
    package's own `__init__` (the way to smuggle in a cycle) fails here.
    """
    # `conditions` is shared with `_core` rather than a family: a condition is
    # built from every part of `_core` while nothing in `_core` is built from a
    # condition, and every family that lowers a conditional reads one.
    allowed = {"_core", "conditions", "costs", *AST_FAMILIES}
    violations = [
        f"ast/statements.py:{line} imports {target or '__init__'}"
        for line, target, _is_sibling in _imports(GRAMMAR / "ast" / "statements.py")
        if target not in allowed
    ]
    assert not violations, (
        "ast/statements.py is the roof of the package — it may import `_core` "
        "and the families and nothing else:\n  " + "\n  ".join(violations)
    )


def test_the_ast_line_layer_sits_on_the_roof_and_nothing_sits_on_it():
    """`ast/lines.py` may name `statements`; no module in the package names it.

    The line nodes hold a `Statement`, so the edge to the roof is real — and it
    is the *only* edge this module is for. Three things keep it from becoming
    the hole the roof test closes one storey down:

    * it imports the vocabulary and `statements` and **no family**. A line node
      that needed a family's node directly would be an effect that had drifted
      up into the line layer, which is how `parser.py` came to hold four effect
      productions before its first split;
    * `statements` does not import it back — already true by the test above,
      whose `allowed` set does not name `lines`, and restated here because that
      is an accident of a set literal rather than something that test says;
    * nothing else in the package imports it but `__init__`. A family naming a
      line node would be reaching past the roof.
    """
    allowed = {"_core", "conditions", "costs", "statements"}
    violations = [
        f"ast/lines.py:{line} imports {target or '__init__'}"
        for line, target, _is_sibling in _imports(GRAMMAR / "ast" / "lines.py")
        if target not in allowed
    ]
    assert not violations, (
        "ast/lines.py is the line layer — it may import the vocabulary and "
        "`statements` and nothing else:\n  " + "\n  ".join(violations)
    )
    readers = [
        f"ast/{path.name}:{line}"
        for path in sorted((GRAMMAR / "ast").glob("*.py"))
        if path.stem not in ("__init__", "lines")
        for line, target, _is_sibling in _imports(path)
        if target == "lines"
    ]
    assert not readers, (
        "ast/lines.py is the top of the package — only `__init__` may import "
        "it:\n  " + "\n  ".join(readers)
    )


@pytest.mark.parametrize(
    "package,families",
    [
        ("effects", EFFECT_FAMILIES),
        ("lowering", LOWERING_FAMILIES),
        ("ast", AST_FAMILIES),
    ],
)
def test_families_do_not_import_each_other(package, families):
    """The property that makes the grouping mean something."""
    violations = []
    for family in families:
        path = GRAMMAR / package / f"{family}.py"
        assert path.exists(), f"{package}/{family}.py is missing"
        for line, target, _is_sibling in _imports(path):
            if target in families and target != family:
                violations.append(f"{package}/{family}.py:{line} imports {target}")
    shared = {"effects": "phrases", "lowering": "_common", "ast": "_core"}[package]
    assert not violations, (
        f"{package}/ families are supposed to be independent — a fragment two "
        f"families need belongs in the shared module below them ({shared}), "
        "not in one of them:\n  " + "\n  ".join(violations)
    )


@pytest.mark.parametrize("package", ["effects", "lowering", "ast"])
def test_the_front_door_exports_every_family_name(package):
    """`__init__` re-exports flat, so callers never name a family.

    That is what makes moving a production between families a non-event. A name
    that stops being re-exported is an ImportError at startup rather than a
    silent loss, but only if `__all__` and the imports agree — this checks they
    do.

    It bites hardest in `ast/`, where every caller says `ast.DealDamage` through
    `from . import ast`: a node the front door forgets is not a missing export
    but a missing *attribute*, which surfaces card by card at parse time rather
    than once at import. The pre-split `ast.py` had drifted that way already —
    `__all__` had stopped naming three of its own node types.
    """
    init = GRAMMAR / package / "__init__.py"
    tree = source_tree(init)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {a.asname or a.name for a in node.names}
    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__all__":
            declared = {
                el.value for el in node.value.elts if isinstance(el, ast.Constant)
            }
    assert declared, f"{package}/__init__.py has no __all__"
    assert declared <= imported, (
        f"{package}/__init__.py declares names it does not import: "
        f"{sorted(declared - imported)}"
    )
    assert imported <= declared, (
        f"{package}/__init__.py imports names it does not export: "
        f"{sorted(imported - declared)}"
    )


def test_no_module_is_back_to_its_old_size():
    """The point of the split, stated as a number.

    Not a style rule — these three files grow with the card pool, and the reason
    the split was worth doing is that every new template lands in them. A
    module drifting back past a thousand lines means the families stopped
    absorbing new work and something is being appended to whatever was easiest.
    """
    oversized = {
        str(path.relative_to(GRAMMAR)): len(source_text(path).splitlines())
        for path in GRAMMAR.rglob("*.py")
        if len(source_text(path).splitlines()) > 1000
    }
    assert not oversized, (
        f"grammar modules back over 1,000 lines: {oversized}. Split along the "
        "family the new work belongs to rather than raising this number."
    )


# Modules deliberately outside the layer order, each with the reason it is not
# a layer. Named rather than skipped, because an *un-named* module is silently
# unguarded — which is how `amounts`, `riders` and `subject_verb` sat outside
# this test's reach, and how the next split would have too.
UNLAYERED = {
    # The AST is its own family with its own ordering guard below.
    "ast",
    # Infrastructure the whole parser sits on: the token stream, the token
    # kinds, the error type. Every layer may read them, so ranking them says
    # nothing.
    "errors", "lexer", "stream",
    # Word tables refreshed from Scryfall (`scripts/fetch_vocabulary.py`).
    # Data, not a production.
    "vocabulary",
    # `amounts` and `nouns` are mutually recursive and cannot be ranked against
    # each other: a `Comparison` takes an `Amount` and an `ObjectFilter` takes a
    # `Comparison`, so `nouns` imports this at module level and it breaks the
    # cycle with a call-time import back. Ranking it either way would make the
    # test above demand a split that the grammar itself forbids — which is what
    # the first attempt at placing it discovered.
    "amounts",
    # Bridges to `engine/` rather than parsers: they import the derivation
    # tables and the text-keyed registries and no grammar sibling at all, so
    # they have no position among productions.
    "derived", "registries",
}


def test_every_grammar_module_is_placed_or_exempt():
    """A module nobody listed is a module this file does not guard.

    The import-direction test above ranks only what `PARSE_LAYERS` and
    `LOWER_LAYERS` name, so a new module escapes it entirely by being
    forgotten — silently, with the suite green. This is the assertion that
    turns forgetting into a failure.
    """
    declared = set(PARSE_LAYERS) | set(LOWER_LAYERS) | UNLAYERED
    present = {p.stem for p in GRAMMAR.glob("*.py")} | {
        p.name for p in GRAMMAR.iterdir() if p.is_dir() and not p.name.startswith("__")
    }
    present.discard("__init__")
    missing = sorted(present - declared)
    assert not missing, (
        "grammar modules outside the layer order and not exempt: "
        f"{missing}. Place each in PARSE_LAYERS/LOWER_LAYERS, or add it to "
        "UNLAYERED with the reason it is not a layer."
    )


# The modules inside a family package that are *not* families: the floors every
# family may read (`_core`'s vocabulary, `_common`'s helpers, `_events`' tables,
# `conditions`' question — a condition is built from the vocabulary while none
# of the vocabulary is built from a condition, which is why both `ast/` and
# `lowering/` have one and why other families import it) and the roofs built
# from all of them (`statements`' unions, `categories`' dispatch table). Neither
# has an independence to check. Named rather than skipped, for the same reason
# `UNLAYERED` is — see the test below.
FAMILY_SHARED = {
    "_common", "_core", "_events", "conditions", "categories", "statements",
    # `ast/lines`, pre-split out of `ast/statements` at Invasion's Phase 0, 25
    # lines under the size guard. The ability-line nodes and `AbilityNode`:
    # the type of `parser.py` (one printed line) where `statements` is the type
    # of `grammar/statements.py` (one whole sentence), which is the cut both
    # other packages already had. Not a family and not a floor — it is the one
    # module *above* a roof, importing `statements` for `Statement` and no
    # family — so it has no independence to check here and is held by
    # `test_the_ast_line_layer_sits_on_the_roof_and_nothing_sits_on_it`.
    "lines",
    # `lowering/_frozen_seats`, split out of `_events` at Mercadian Masques'
    # second Phase 0 — the seat half of that module's three questions ("that
    # player", "that much", "they"), taken out when `_events` reached 990 of the
    # size guard as a *floor* every lowering family reads, so no single group
    # would have crossed it alone and none could be briefed to expect the split.
    # `_events` re-exports every name under the spelling it had, so this has one
    # importer by construction — the `_recipients` shape below.
    "_frozen_seats",
    # `lowering/_roles`, split out of `lowering/_targets` at Mercadian Masques'
    # wave 3, when the ordered-roles builders took that floor thirteen lines
    # past the size guard. The seam is the last clause of `_targets`' own
    # docstring: that module holds CR 601.2b-d — how many objects a sentence
    # announces and how a division is shared out — and this one holds "which of
    # several slots is asked for first", whose readers are a *walk*
    # (`legality.role_target_options`, the announcement gate, the CR 608.2b
    # re-check) rather than the handler that acts on one chosen object.
    # A floor rather than a family, like `_targets` above it: three lowering
    # families read a builder from here through `_common`.
    "_roles",
    # `lowering/_declaration_costs`, split out of `lowering/combat.py` at
    # Mercadian Masques' wave 2, when War Tax and War Cadence — the same
    # board-wide declaration toll with its cost in mana — took that module three
    # lines past the size guard. The seam is one the rules already draw and the
    # enforcement already honours: a CR 508.1c / CR 509.1b *restriction* is
    # answered by `can_attack` / `_can_block_attacker` asking whether a
    # declaration is legal at all, and a CR 508.1g / CR 509.1d *cost* is
    # answered by the four cost readers and charged over the whole declaration.
    # Everything in the new module lowers into the second half; everything left
    # in `combat` lowers into the first.
    # A single-importer floor, precedented by `_recipients` and `_bites` below
    # and for their reason exactly: `combat` is the only family that asks, and
    # the module exists because that family crossed the guard. It reads
    # `_common` and the AST and nothing back.
    "_declaration_costs",
    # `effects/_strips`, split out of `effects/search.py` at Urza’s Destiny’s
    # wave 1 — the multi-zone strip by a recorded name (Lobotomy; Eradicate and
    # its four siblings). A single-importer floor, precedented by `_recipients`
    # below, and the first one `effects/` has had.
    "_strips",
    # `effects/_other_libraries`, pre-split out of `effects/search.py` at the
    # Phase 0 before Invasion — "Search <player>'s library", the search whose
    # library is not the searcher's own (Jester's Cap, Bribery, Denying Wind).
    # A single-importer floor like `_strips`, and the importer `_strips` has
    # had in fact since it was written: the strip is tried from inside this
    # production and from nowhere else.
    "_other_libraries",
    # `_recipients` split out of `lowering/damage.py` at ULG wave 1, when that
    # module sat 24 lines under the size guard with a new counted-amount branch
    # to land. The seam is the one that module's own docstring already drew
    # twice — the computed amounts left for `_amounts`, the prevention shields
    # for `prevention` — and what stayed was "a damage event happening", which
    # has exactly two halves: how much, and to whom. This is the second.
    # A single-importer floor, precedented by `_bites` and `_conjuncts` beside
    # it: `damage` is the only family that asks, and the module exists because
    # that family crossed the guard. It is *not* folded into `_seats`, which
    # answers a narrower question for three families and must not carry one
    # family's dispatch.
    "_recipients",
    # `_cost_records` split out of `_records` in the same wave and for the same
    # reason, along the seam that module's own docstring has drawn since it was
    # written: `_PRODUCES` is keyed by *instruction kind*, and nothing about a
    # cost can be — a cost is charged by `mixins/stack/activation.py` on the way
    # to the stack (CR 601.2h) rather than by anything the dispatcher runs. Six
    # families and `lower.py` read it and it reads nothing back. Its importers
    # were repointed rather than re-exported through `_records`, which is that
    # module's own complaint about the key names it used to reach through
    # `_events`.
    "_cost_records",
    # `_payloads` split out of `ast/_references` at Exodus's Phase 0, when that
    # module sat three lines under the size guard with five groups about to
    # land noun-phrase work on it. It is `ObjectFilter.to_payload`'s 307-line
    # body and nothing else: it names no node at run time (the class arrives as
    # an argument), reads `_primitives` and the vocabulary, and nothing reads
    # back. A floor under `_references` the way `_filters` is under `_common`.
    "_payloads",
    # `_deaths` split out of `_events` when the Death Watch round pushed it
    # back over the size guard: the tables a *death* freezes (the dying
    # card, its last-known power and toughness, and which fire sites stamp
    # them) are read by five unrelated families, where `_events` answers the
    # same question across every event there is. A floor, not a family.
    "_deaths",
    # `_delays` split out of `_events` at Weatherlight's wave 2, when two
    # branches' additions summed one line past the guard with neither at fault.
    # A narrowing of `_events`' own question rather than a new one: it answers
    # "what did the firing event freeze" across every event there is, and these
    # three tables answer it for the one class that does not fire when it is
    # created — a *delayed* ability (CR 603.7), whose bound object was chosen a
    # step or a whole turn earlier. The same cut `_deaths` took, one event class
    # at a time. A floor: eight lowering families read it and it reads nothing.
    "_delays",
    # `_core` split twice in one round, when The Dark pushed it past the size
    # guard below. `_references` took the object/player/target nodes
    # (`ObjectFilter` alone was 428 lines), `_primitives` took the two literal
    # amounts both halves need — a node `_references` and `_core` both use
    # cannot live in either without one importing the other — and `costs` took
    # the cost nodes. All three are floors, not families: `_core` re-exports
    # what they define, so no family imports them directly.
    "_primitives", "_references", "costs",
    # `_seats` split out of `_references` at Weatherlight's wave 2, when that
    # module reached the guard with four lines of headroom and no owning group.
    # The line is the one `references.py` one layer up already states: CR 109 is
    # what an object is, CR 115 is how a spell chooses one, and a player
    # (CR 102) is not an object at all — so `ObjectFilter` and `TargetSpec` stay
    # and the two nodes naming *which seats* leave. It reuses the name
    # `lowering/_seats.py` has carried since it left `_common`, so the mirror
    # re-forms instead of forking. A floor, not a family: `_references` reads
    # `PlayerDeed` only as an annotation and `_core` re-exports both names.
    "_seats",
    # `_targets` split out of `_references` at Tempest's wave 3, the next time
    # that module crossed the guard — the filter had gained the three keys
    # Escaped Shapeshifter's condition needs. The line is the *other* half of
    # `_references`' own title, and the one `nouns.py` was cut on back at
    # Antiquities: what a noun phrase **describes** (`ObjectFilter` and the
    # comparisons bounding it) against what a sentence **points at**
    # (`TargetSpec`). The two grow with different rules — the first with the
    # vocabulary of printed noun phrases, the second with CR 601.2's
    # announcement — which is what makes the boundary information rather than a
    # place to have put the overflow. A floor, not a family: it reads
    # `ObjectFilter` and `_core` re-exports what it defines, so no family
    # imports it directly.
    "_targets",
    # `_amounts` split out of `lowering/damage.py` the next time that module
    # reached the size guard, along CR 107.2/107.3's line: a quantity that is
    # **counted** — off a board, out of the resolution's own scratchpad, or off
    # a cast the player picked — against the sentence that spends it. A floor
    # rather than a family for `_primitives`' reason exactly: `damage.py` reads
    # it, and inside a package a module a family imports cannot itself be one.
    "_amounts",
    # `_counted_damage` split back out of `_amounts` at Tempest's Phase 0, when
    # that module sat four lines from the guard with three of the wave's five
    # groups reaching it and none of them owning it. The line is the second half
    # of the sentence `_amounts` was itself cut on: a printed quantity that is
    # counted, "**against the sentence that spends it**". Every sentence in
    # there that *spent* a count was a damage sentence — the three cost
    # channels, the difference, the named board count, the per-seat record, the
    # chosen cast — so those left and the counting stayed, which is what the
    # older module's name has said since the first cut. It is also the half that
    # grows: a set adds a printed shape of counted damage far oftener than it
    # teaches `count_spec` a new zone. A floor for `_amounts`' reason exactly —
    # `damage` reads it, `upkeep` its one predicate, `where_x` its one
    # characteristic set, and it reads none of the three back. It reads
    # `_amounts` for `count_spec`, which is a floor reading a floor, the
    # arrangement `_amounts` already has with `_common`.
    "_counted_damage",
    # `_counted_pumps` split out of `lowering/characteristics.py` at Mercadian
    # Masques' first wave, on `_counted_damage`'s line one CR layer over: a
    # printed quantity that is **counted**, against the sentence that spends it
    # — here a CR 613 layer-7c modification rather than a damage event. Every
    # reading of `_lower_pump` whose *size* was a count went with it (the
    # milled-this-way record, the team buff, the bound target, the event's own
    # subject, the source's continuous bonus), and that is the half that grows:
    # a set prints a new shape of counted pump far oftener than it teaches
    # `count_spec` a new zone. `_TARGET_PUMP_DURATIONS` went too, because it
    # has a reader on each side of the cut and a table left behind would have
    # made a floor import the family that reads it. A floor for `_amounts`'
    # reason exactly — `characteristics` reads it and it reads nothing back —
    # and it reads `_amounts`, `_common` and `_events`, which is a floor
    # reading floors.
    "_counted_pumps",
    # `_bites` split out of `lowering/damage.py` at Mirage's third wave, the
    # next time that module reached the guard below. The line is the one the
    # branches had already drawn: everything left in `damage` computes a
    # **quantity** and hands it to the generic `deal_damage`, whose source is
    # the spell or the ability, while a bite reads one object's power at
    # resolution and makes *that object* the source of the damage (CR 120.7) —
    # which is why each is its own instruction kind rather than an amount key.
    # A floor for `_amounts`' reason exactly: `damage` reads it and it reads
    # nothing back.
    "_bites",
    # `_sacrifices` split out of `lowering/board.py` when a *second* family
    # started charging a printed sacrifice cost: Minion of Leshrac's "unless
    # you sacrifice a creature other than this creature" is the damage family's
    # sentence and Mold Demon's "unless you sacrifice two Islands" is the
    # board's, and both reduce the noun phrase with the same reader. A floor
    # for `_amounts`' reason exactly — a module two families import cannot
    # itself be one, and the alternative was `board` and `damage` importing
    # each other.
    "_sacrifices",
    # `_seats` arrived at the `life` split, holding the one thing the two
    # halves shared: which recipient key a printed player reference becomes.
    # A floor for `_amounts`' reason exactly -- `game` asks it for CR 407's
    # ante and `life` for CR 119.5's "that player's life total becomes N", and
    # a module two families import cannot itself be one. Small, and that is
    # not an argument against it: the alternative was `life` importing `game`
    # or a second copy of a three-row seat table, and a seat table that
    # disagrees with itself lands an effect on the wrong player.
    #
    # It grew the *other* half of the same subject at USG's second wave, when
    # Disorder's "each player who controls a white creature" took `damage` to
    # fifteen lines under the guard: a recipient key says which seats a sentence
    # acts on and a narrowing says which **of those**, both read off the same
    # `ast.PlayerRef`, and the two stampers that carry one had no other home
    # they could share. Third-party imports were the price and they are
    # downward: `_common` for the two payload readers, which is where every
    # other floor here reaches.
    "_seats",
    # `_records` split out of `categories` when *that* module crossed the guard:
    # it carried two registries with two different keys — which family a kind
    # belongs to, and what a kind writes into the resolution scratchpad — and
    # only the first is what the module is named for. Shared for `_events`'
    # reason: four lowering families read it (`control_flow` threads what an
    # offer's action records into its `then`, `sequences` threads each step's
    # records forward and asks the primary for "if you do", `repeats` hands a
    # round's records to the condition printed after it, and `where_x` asks
    # whether "this way" has a producer), so it cannot live in any of them.
    "_records",
    # `_sweeps` split out of `lowering/damage.py` the next time *that* module
    # reached the guard, along CR 611.2c's line: a set the sentence **describes**
    # against one it chooses (CR 115). A floor for `_amounts`' reason exactly —
    # `damage` reads it and it reads nothing back.
    #
    # It is also the split that made one idiom one lowering again. The "all"
    # spelling of the sweep had already been exiled into `_common` — the module
    # every family reads — with a comment saying it was there only because
    # `damage.py` was full, while the "each" spelling stayed inline in
    # `damage.py`; the two had drifted, and the inline one was dropping the head
    # noun from the payload it built.
    "_sweeps",
    # `_superlatives` arrived at Urza's Saga with the noun phrase two families
    # print: "the creature with the least **toughness**" is a damage recipient
    # (Purging Scythe) and "the creature with the least **power**" a destroy
    # subject (Drop of Honey), and both lower to the same pick — one
    # `choose_permanent` naming the extreme, whose answer the verb then reads
    # back. A floor for `_amounts`' reason exactly: `damage` and `destruction`
    # both read it and it reads nothing back, and a fragment two families need
    # is not either one's property.
    "_superlatives",
    # `_conjuncts` split out of `lowering/damage.py` the *third* time that
    # module reached the guard, along the boundary its own docstring already
    # listed ("damage conjunctions" is one of the four things it says it
    # holds). One question: how many choices did the sentence announce
    # (CR 601.2c)? One clause naming several recipients announces at most one
    # and may be split; two printed clauses announce their own and may not be
    # fused. Named for `grammar/conjuncts.py`, its mirror one package over.
    #
    # A floor for `_sweeps`' reason, and it stays one **because the callback is
    # an argument**: every shape in it finishes by lowering its pieces as
    # ordinary damage clauses, so `damage.py` hands its own `_lower_damage`
    # down rather than being imported back — `_lower_steps`' `lower_statement`
    # arrangement, one package over.
    "_conjuncts",
    # `_bound_returns` split out of `lowering/returns.py` at Alliances'
    # integration, when three branches each added a reading under the cap and
    # their sum crossed it. The line is the one `returns.py` already drew: a
    # return whose object **nothing targets** — the firing event recorded it,
    # it is the ability's own source, or it is a description the handler sweeps
    # — against one a player chooses (CR 115). A floor for `_sweeps`' reason
    # exactly: `returns` is its only reader and a family may not import a
    # sibling. The two predicates that moved with it are there because both
    # halves of the split ask them, which is what makes this a floor rather
    # than a file that happened to be cut in half.
    "_bound_returns",
    # `_bound_exiles` split out of `lowering/exile.py` at Exodus' second wave,
    # when that module sat four lines under the guard — wave 1 had trimmed its
    # own comment to stay under rather than split mid-round, which was the right
    # call then and is not a state to ship. It is `_bound_returns`' twin one
    # keyword action over and carries its name for its reason: every reading in
    # it names its object by reference rather than choosing one, so nothing is
    # matched and nothing is picked, and every narrowing the sentence prints
    # beyond the reference is a **refusal** rather than a payload. What is left
    # in `exile` picks its object out of the game — an announced target, a swept
    # match, a prompted pile — and carries a filter to its handler; not one
    # branch that moved carries one, which is the same test `_bound_returns`
    # applies to `returns`.
    # It has two entry points rather than one, and that is the cut being
    # faithful rather than tidy: `_lower_exile` reads the restated noun phrase
    # ("that creature") *before* the sweep and hand quantifiers and the pronouns
    # ("the creature", "it", "the token") *after* them, so one function would
    # have moved a branch across the sweep — a behaviour change dressed as a
    # split. Each returns None where the sentence is not its own.
    # A floor for `_bound_returns`' reason exactly: `exile` is its only reader
    # and a family may not import a sibling. `_entering_counter_payload`
    # travelled with it and is read back up, because both halves write the
    # counters a card enters exile with and a fragment two readers share belongs
    # in the one below them.
    "_bound_exiles",
    # `_described_returns` split out of `_bound_returns` at Exodus' Phase 0,
    # eleven lines under the guard with two of wave 1's groups due to land in
    # it and no single group able to cross it alone — a floor every lowering
    # family may read is the case the playbook says is pre-split rather than
    # briefed. The line is the comma its own docstring already wrote: a
    # sentence names the object it returns either by **reference** (the firing
    # event recorded it, or it is the ability's own source) or by
    # **description**, and the two are different work. A reference is resolved
    # by following it, so the only question is where the object is now and
    # every printed adjective is a restatement that refuses the moment it is
    # anything more; a description is resolved by looking at the board, so the
    # noun phrase *is* the instruction and the question is whether its
    # narrowing survives to a reader that can test it. The call graph agrees
    # exactly: `_deaths`, `_delays` and `CHOSEN_PERMANENT` are read only by the
    # referencing half, and every filter-payload helper — `_filter_payload`,
    # `chargeable_card_filter`, `untestable_filter_keys`, both moved predicates
    # — only by the describing one. A floor for `_bound_returns`' reason
    # exactly: `_bound_returns` reads it (its last act is the tail call that
    # keeps one printed-specificity order across two files), `returns` reads
    # the two predicates, and it reads neither back.
    "_described_returns",
    # `_piles` split out of `lowering/exile.py` at Alliances' third wave, when
    # that module crossed the guard on Gustha's Scepter's face-down exile and
    # shed its permission half to `permissions`. It holds the two leaves both
    # halves ask: how a noun phrase over a **pile of cards** reduces to a
    # payload a picker can test (CR 610.3's linked pile on one side, the
    # permission that reads that same pile on the other), and which narrowings
    # such a picker can answer at all. A floor for `_amounts`' reason exactly —
    # a leaf two families read cannot live in either without one importing the
    # other — and it produces no `OracleInstruction`, which is what keeps it a
    # vocabulary rather than a third family.
    "_piles",
    # `_counter_stores` split out of `lowering/counters.py` at Mirage, the
    # second time that module crossed the guard. The line is the one
    # `counter_removal` drew when it left the same file — what the *payload*
    # asks for — read one axis over: a CR 122.1a placement asks which object and
    # how many and leaves the kind as data, while these two ask **which store
    # tracks this kind** and nothing about an object's characteristics. Loyalty
    # is CR 306.5b's life total and price of an ability; poison is CR 122.1f's
    # counter on a *player*, which CR 122.1's own first sentence separates from
    # a counter on an object and which this engine keeps on a different field
    # entirely. Both refuse by name when no store answers, which is the shared
    # shape that makes them one leaf rather than two leftovers. A floor for
    # `_bound_returns`' reason exactly: the loyalty half is reached from inside
    # `counters._lower_put_counter`, so `counters` reads it and it reads nothing
    # back.
    "_counter_stores",
    # `_plus_one_counters` split out of `lowering/counters.py` at Urza's Saga
    # wave 1, the third time that module crossed the guard — sixteen lines
    # under it before the wave started, and Vampiric Embrace's second
    # attached-counter trigger head was what took it over. The line is the
    # gate `_lower_put_counter` had already written for itself: everything
    # above `if node.counter != "+1/+1"` dispatches on *which counter* the
    # sentence names or on a subject an earlier step bound, and everything
    # below it has settled that and asks only how many and on what. A floor
    # for `_described_returns`' reason exactly, tail call included:
    # `counters`' last act is to hand the sentence down, so one
    # printed-specificity order still reads top to bottom across two files,
    # and nothing reads back.
    "_plus_one_counters",
    # `_named_counters` split out of `lowering/counters.py` at Nemesis' Phase 0,
    # with that module 22 lines under the guard and nothing in flight: fading
    # and Mana Cache's charge counter were due to land in it from several
    # groups at once with none of them able to cross it alone, which is the
    # shared module the playbook says is pre-split rather than briefed. The
    # line is the gate `_lower_put_counter` had written five times over:
    # `not is_pt_counter(node.counter)`. A CR 122.1a pair carries its power and
    # toughness in its name and is written through `Game.place_pt_counters`; a
    # wind, charge or fade counter carries nothing and sits in
    # `engine/named_counters.py`'s open store — "two different writes", in the
    # words of the P/T block-pair branch that stayed behind — so it is
    # `_counter_stores`' boundary (what the *payload* asks for) read a third
    # time, and the name is the store's own rather than a new word. Every
    # `add_named_counter_to_self` and `add_named_counter_to_target` the
    # package builds is built there and nothing else is. The Dread Wight
    # placement stayed although its kind carries the word, because its gate
    # stopped asking: it takes either kind of counter as payload.
    # **Two entry points**, for `_bound_exiles`' reason exactly: four of the
    # five branches are read ahead of every P/T branch and the fifth after
    # three that never ask the counter's kind, so one function would have
    # moved a branch — a behaviour change dressed as a split. A floor for
    # `_counter_stores`' reason: `counters` is its only reader and it reads
    # nothing back.
    #
    # `PREVENTION_SHIELD_RECORD` left `counters` at the same Phase 0 for
    # `_prevented_riders`, where the predicate that reads it already lived —
    # that floor had been importing it *upward*, from inside a function body,
    # which no guard in this file looks at because a shared module is skipped.
    "_named_counters",
    # `records` split out of `ast/conditions.py` at Mirage, when three
    # intervening-if productions took that module past the guard. The line is
    # the one `lowering/conditions.py` had been drawing in prose card by card:
    # a condition answered by looking at the game **now** — a board count, a
    # zone's height, a life total, whose turn it is — against one answered by
    # looking at a record of something already done ("if you do", "died this
    # way", "if you've gained 3 or more life this turn"). It reuses the name
    # `grammar/records.py` and `lowering/_records.py` already carry, so the
    # mirror re-forms across all three layers instead of forking a fourth
    # vocabulary. A floor rather than a family for `conditions`' own reason:
    # `conditions` reads it — the `Condition` union is the roof over both
    # halves and has to name all of them — and it reads nothing back.
    "records",
    # `_filters` split out of `lowering/_common.py` at Visions' Phase 0, the
    # first time that module reached the guard below — taken while nothing was
    # in flight, because `_common` is the one floor every wave branch adds to
    # and a cap crossed at integration is a seam found with none of the work in
    # hand. The line is the one `_common`'s own docstring had already drawn: a
    # **filter** payload (which `ObjectFilter` fields survive to a handler,
    # which narrowings a payload drops, and the two cost gates over the same
    # question) against a **target description** and the small values several
    # families share. A floor for `_primitives`' reason exactly — `_common`
    # reads it, re-exports every name, and it reads nothing back, so no family
    # imports it directly.
    "_filters",
    # `_blankets` split out of `lowering/prevention.py` at Visions' first wave,
    # when Remedy's divided pool and Honorable Passage's reflecting rider took
    # that module past the guard. The line is one `engine/prevention.py` already
    # draws in its **order bands**, and draws for a reason that decides
    # behaviour: a blanket shield has no charges, so applying it costs its
    # recipient nothing and it runs ahead of every consumable — where a pool
    # (CR 615.7) is spent by points and a CR 615.8 shield by instances, and
    # spending one on damage a blanket would have stopped anyway is the outcome
    # CR 616.1e's default must not pick. A floor for `_bound_returns`' reason
    # exactly: `prevention` reads it — `_lower_prevent_damage` dispatches here
    # the moment the printed quantity is `ast.AllOf` — and it reads nothing
    # back. Al-abara's Carpet's source-scoped blanket came with it because it is
    # a blanket too and is reached only from inside the one that moved.
    "_blankets",
    # `_counted_redirects` split out of `lowering/redirection.py` at Nemesis'
    # first wave, when Sivvi's Valor's and Oracle's Attendants' blanket
    # redirects off an announced target took that module past the guard. The
    # line is `_blankets`' own axis on the redirect side — the printed
    # *quantity* — and it is the one the parse side already draws inside its
    # single production: "All damage …" moves the whole event, "the next N
    # damage …" moves N points (CR 615.7's numeric shield with CR 614.9's
    # verb). `_lower_redirect_damage` already handed a counted node down
    # before any of its branches could read it, so the call graph was two
    # components joined by that one dispatch. A floor for `_blankets`' reason
    # exactly: `redirection` reads it and it reads nothing back. Both functions
    # moved byte-identically, so no compiled program moves.
    "_counted_redirects",
    # `_instance_redirects` split out of `lowering/redirection.py` at Prophecy's
    # first wave, when Shield Dancer's redirect onto its own dealer took that
    # module past the guard. The line is the parse side's: both shapes here are
    # read by `effects/damage_instances._finish_named_source_effect` — CR
    # 615.8's "the next time <a source the sentence names> would deal damage"
    # — where the chosen-source and blanket redirects stay behind. A floor for
    # `_counted_redirects`' reason exactly: `redirection` reads it and it reads
    # nothing back. Soltari Guerrillas' lowering moved byte-identically.
    "_instance_redirects",
    # `_prevented_riders` split out of `lowering/prevention.py` at Mercadian
    # Masques' first wave, when Charm Peddler's chosen-source shield over an
    # announced creature took that module past the guard. The line is the one
    # `prevention`'s own docstring states — "which shield records what, and for
    # how long" — read against the clause printed *beside* a shield, which is
    # neither: CR 615.5's additional effect (Reverse Damage's life gain, Bone
    # Mask's exile, Temper's counter, Shadowbane's team shield) and Elvish
    # Healer's second size. It takes the name `engine/grammar/prevented_riders.py`
    # already carries on the parse side, so the mirror re-forms instead of
    # forking. A floor for `_blankets`' reason exactly: `prevention` reads it —
    # from three refusals in front of the branches that own the clause — and it
    # reads nothing back.
    #
    # Two more readers since, each for a predicate about the same rider that had
    # been sitting on a nearer floor: `counters` (Mercadian Masques' Phase 0,
    # out of `_records`) and, at Invasion's Phase 0, `statement_dispatch` —
    # `_guard_is_the_arms_own_precondition` left the bottom of the dispatcher,
    # where it routed nothing. The dispatch layer is above every floor, so that
    # import needs no entry here; this module still reads nothing back.
    "_prevented_riders",
    # `_zone_categories` split out of `lowering/zones.py` at Tempest's Phase 0,
    # when that module sat eleven lines from the guard with three of the wave's
    # five groups reaching it and none of them owning it. The line is the one
    # the table's own header already drew, read a clause further than it was
    # written: "here rather than *there*" was an argument against `categories`
    # rather than an argument for one file, and 121 rows with no call graph is
    # the same seam `by_node` and `_records` each left a module through — the
    # table is a registry either way, and `zones.py` is dispatch. It is also
    # the half that grows, since a kind gets a row the day it is invented and a
    # lowering only when a card prints the sentence.
    #
    # A floor that reads nothing at all: `categories` composes it into one
    # `INSTRUCTION_CATEGORIES`, which is now a shared module reading a shared
    # module where it used to be `categories` reaching up into a family for its
    # rows. **Not one row's value changed** — a category names the migration
    # family a kind belongs to, never the module its lowering lives in, and
    # renaming one leaves it out of `GRAMMAR_CATEGORIES`, which has no fallback.
    # `_pump_categories` split out of `lowering/categories.py` at Urza's
    # Saga's wave-2 integration, when that table crossed the guard at 1,003 —
    # three lines over, from two groups' rows summing with neither at fault.
    # The seam is the one its three earlier splits all used: take a whole
    # *category*, and take the largest one left. `pump` was 50 of the 310 rows
    # still declared there, as `zones` was when it left at Visions.
    # The line is CLAUDE.md's own: a kind categorised `pump` is a kind whose
    # handler ends in `engine/pt.py`'s single P/T write API, and every kind left
    # in `categories` ends somewhere else — `_zone_categories`' question ("does
    # this kind name two zones?") one layer of the CR down. A floor, not a
    # family: 50 rows of data with no call graph, folded back in with
    # `update()` so `INSTRUCTION_CATEGORIES`' address never moved.
    "_pump_categories",
    "_zone_categories",
    # `_combat_categories` split out of `lowering/categories.py` at the Phase 0
    # before Invasion, 71 lines under the guard with eight groups about to give
    # every kind they invent a row there. The same seam a third time — a whole
    # category — and chosen by growth rather than by size: `combat_restrictions`
    # went from 21 rows to 34 between Tempest and Invasion where `damage`, the
    # one category larger, went from 30 to 36. The line is the one its rows'
    # comments had drawn singly: every kind in it is answered by the combat
    # phase, either through `engine/handlers/combat.py` or (ten of the 34) by a
    # declaration reading the compiled program with no handler at all. Five
    # lowering modules build those kinds and the one that names the subject,
    # `combat`, had 130 lines of room for 108 lines of rows, so there was no
    # family to send them home to; `zones` held its own rows once and gave them
    # up for that reason. A floor that imports nothing, folded back in with
    # `update()`, and not one row's value changed.
    "_combat_categories",
    # `_record_keys` split out of `_events` at Tempest's Phase 0, when that
    # module sat twelve lines from the guard as a floor eight lowering families
    # read. The line is one both neighbouring docstrings had already written
    # about each other: `_events` is "what a back-reference in a *triggered*
    # ability names … keyed by **trigger-condition kind**", and `_records` says
    # the other half outright — "what a step **records** is keyed by
    # *instruction kind* … three tables, three keys, three questions". Nothing
    # in `_record_keys` is keyed by a trigger-condition kind and nothing in it
    # is about a firing event: every name is the spelling of a scratchpad key
    # one step writes and a later sentence reads back (CR 608.2), which is what
    # `_records._PRODUCES` writes. It is the half that grows — a key is minted
    # whenever a step learns to leave something behind, where an event table
    # gains a row only when a set prints an event the engine already fires.
    #
    # A floor **under** a floor, as `_filters` is to `_common`: `_events`
    # imports every name and re-exports it, so no family import moved and
    # nothing reads this module directly. It reads `oracle_types`, `tokens` and
    # `_deaths` and no family at all — and deliberately not `_records`, so the
    # module that writes these keys and the module that names them cannot cycle.
    "_record_keys",
    # `_record_conditions` split out of `lowering/conditions.py` at Exodus'
    # second wave, when that module sat five lines under the guard. It is the
    # lowering-side mirror of the cut `ast/conditions.py` took when *it*
    # crossed: a clause answered by looking at the game now — a board count, a
    # zone's height, a life total, whose turn it is — against one answered by
    # reading a record of something already done. `ast/records.py` says that
    # line was written here first, "card by card, in prose".
    # The mirror was measured rather than assumed, which is what the seam rule
    # asks: every one of `_lower_condition`'s forty-nine branches is a bare
    # `isinstance` on a distinct node class, and each was read against which
    # half of `ast` defines its node. No branch spans the two, and the halves
    # share no helper and no import beyond `ast` and `LoweringError` — four
    # module-level helpers stayed and seven imports left, with none read on both
    # sides. Order cannot be part of the division either, since forty-nine
    # mutually exclusive `isinstance` tests with no `elif` among them answer the
    # same however they are ordered.
    # The name keeps the mirror's word and disambiguates by what it holds,
    # because `lowering/_records.py` is taken by a sibling of the same subject
    # (the `_PRODUCES` table) — the move `_record_keys` above made when the
    # spellings of those keys left `_events`. Three modules, one word, three
    # questions: what a step records, what the key is called, and what a
    # sentence may ask of it.
    # A floor for `conditions`' own reason: three callers in three different
    # places read a condition, and one living in a family would couple the rest
    # to that family. `conditions` hands the sentence down as its last act, the
    # arrangement `_bound_returns` has with `_described_returns`, and nothing
    # reads back.
    "_record_conditions",
    # `_collapses` split out of `lowering/control_flow.py` at Urza's Legacy's
    # Phase 0, eleven lines under the guard with three of the wave's five
    # groups due to compose a `may` or a `sequence` and none of them able to
    # cross it alone — the shared module the playbook says is pre-split rather
    # than briefed. The line is the one all five functions had already written
    # into their own docstrings: an offer whose action carries its **own**
    # ceiling ("up to three", "any number", "any amount of mana") is one
    # decision and not two, and the prompt behind it is the half that suspends
    # the resolution (CR 608.2) where an offer does not. They are recognisers —
    # one `ast.May` in, a collapsed instruction or None out — and not one of
    # them takes `lower_statement`, which is the inversion the rest of
    # `control_flow` is built on and the clearest evidence this is a floor
    # rather than the family's second half. A floor for `_bound_returns`'
    # reason exactly: `control_flow` is its only reader and a family may not
    # import a sibling.
    "_collapses",
}


@pytest.mark.parametrize(
    "package, families",
    [
        ("effects", EFFECT_FAMILIES),
        ("lowering", LOWERING_FAMILIES),
        ("ast", AST_FAMILIES),
    ],
)
def test_every_family_module_is_listed_or_shared(package, families):
    """A family nobody listed is a family `test_families_do_not_import_each_other`
    never looks at.

    The same hole as `test_every_grammar_module_is_placed_or_exempt`, one level
    down: that test iterates the *list*, so a new family module escapes it by
    being forgotten — silently, with the suite green. `lowering/exile.py` was
    written the day this assertion was added and would have been the first to
    slip through.
    """
    present = {p.stem for p in (GRAMMAR / package).glob("*.py")}
    present.discard("__init__")
    missing = sorted(present - set(families) - FAMILY_SHARED)
    assert not missing, (
        f"{package}/ modules that are neither a listed family nor a shared "
        f"floor: {missing}. Add each to the family list, or to FAMILY_SHARED "
        "with the reason every family may read it."
    )


def test_no_module_defines_the_same_name_twice():
    """A module may not bind one top-level name twice.

    Python takes the later definition silently, so a duplicate is not an error,
    it is a *shadow*: the first definition still reads correctly, is still
    imported by name, and never runs. The Dark's five-way parallel round landed
    four of them in one merge, because git resolves "both branches added a
    function" as two functions rather than as a conflict — a clean textual merge
    that is not a clean merge (SET_PLAYBOOK, "two merge hazards where taking
    either side passes the suite").

    Each of the four failed differently, which is why this asks the shape rather
    than any one symptom: two were harmless twins, one shadowed a *guard*
    (`_lower_reveal_hand`'s refusal of an unhandled player kind, so "each player
    reveals their hand" would have lowered to one player revealing), and one
    shadowed a production that returned ``Statement | None`` with one that
    raised instead, which the caller had just been taught to expect None from.
    """
    offenders = []
    for root in ("engine", "tests", "web", "scripts"):
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            try:
                tree = source_tree(path)
            except SyntaxError:  # not ours to police here
                continue
            names = [
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            for name, count in collections.Counter(names).items():
                if count > 1:
                    offenders.append(f"{path}: {name} defined {count}x")
    assert not offenders, (
        "a top-level name is bound twice in one module — the later definition "
        "silently wins and the earlier one never runs:\n  " + "\n  ".join(offenders)
    )


def test_the_lowering_and_the_handler_agree_which_actors_name_a_set_of_seats():
    """`may`'s two halves have to name the same actors.

    The lowering decides what a back-reference to a player *compiles to* inside
    an offer (``lowering/control_flow._SEAT_SET_ACTORS``) and the handler
    decides which seat it *resolves against*
    (``handlers/control_flow._EACH_ACTORS``, the rebind). An actor in one set
    and not the other is an offer that burns, or sacrifices for, whoever the
    other half happened to pick — silent, because both halves resolve to a real
    seat.
    """
    from engine.grammar.lowering.control_flow import _SEAT_SET_ACTORS
    from engine.handlers.control_flow import _EACH_ACTORS

    assert _SEAT_SET_ACTORS == _EACH_ACTORS
