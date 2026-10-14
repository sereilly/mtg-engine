# Set history

The pool, set by set: what each set brought, where it sits in the manifest and
why, what its promotion found, and how the verification tracker moved.

**Nothing here is an instruction.** It is the evidence behind rules stated
elsewhere - CLAUDE.md's two about the manifest (rehearse the wrong insert at
every promotion; count a reprint against the sets that actually print it) and
`SET_PLAYBOOK.md`'s gates - kept in a file of its own so that neither has to
be read past it. The process is `SET_PLAYBOOK.md`, whose retrospectives are
about how a set was *worked*; the numbers a census is planned from are
`ROADMAP.md`'s "Where the sets landed".

Both sections were moved here verbatim from CLAUDE.md on 2026-10-13, when that
file became its own short form (`engine/ARCHITECTURE.md`, "The long form of
CLAUDE.md", has the engine's half). "This file" in them means CLAUDE.md as it
was.

**A promotion adds its set's paragraph to the first section; Phase 5 adds what
its in-game pass found to the second.** Not to CLAUDE.md, which is loaded into
every session and whose size `tests/engine/test_claude_md_size.py` holds.

## The pool and its manifest, set by set

**MTG Simulacrum** — a text-based **Magic: The Gathering rules engine** plus a
FastAPI web app with a browser game UI. The card pool lives in `cards/` as one
JSON per set, registered in `cards/manifest.json` (the single source of truth
for which sets ship): Limited Edition Alpha (290 cards), Limited Edition Beta
(292), Unlimited Edition (292 — same list as Beta), Arabian Nights (78),
Antiquities (85), Revised Edition (296), Legends (310), The Dark (119),
Fallen Empires (102), Fourth Edition (368), Ice Age (373), Homelands (115),
Alliances (144), Mirage (335), Visions (167), Fifth Edition (434),
Weatherlight (167), Tempest (335), Stronghold (143), Exodus (143),
Urza's Saga (335), Urza's Legacy (143), Classic Sixth Edition (335),
Urza's Destiny (143), Mercadian Masques (335), Nemesis (143), Prophecy (143),
Invasion (335), Planeshift (143), Seventh Edition (335), Apocalypse (143),
Odyssey (335) and Core Set 2021 (285), 5,246 unique cards, all classified as
supported.
**Thirty-three sets, and their sizes are the whole spread**: 4ED and 5ED are pure
reprint sets, every one of their cards already in the pool, so they are the two
sets that ship without implementing a card, and **6ED is the third of that shape
and the first where it is only *almost* true** — 333 of its 335 were already
here and **two were not**, Blaze and Regal Unicorn, whose earlier printings were
in Portal, a set this manifest does not carry. A reprint set is a set that
reprints from *this pool*, not from Magic, and the difference is two cards.
**7ED is the fourth, and the one that priced "almost"**: 318 of its 335 were
here and **seventeen were not** — Portal, Portal Second Age and Starter again
— of which five are vanilla creatures, ten arrived supported, and two needed a
production (Sleight of Hand, Baleful Stare). `set_progress.json` records it
with 0 new cards, as it did 6ED, and ROADMAP said in advance to read that
number the way 6ED turned out. A reprint-shaped set is still an ingest and a
rehearsal rather than a set of rounds, but it is not nothing: the fifteen
that "arrived supported" were each driven in a game, and driving them found
three pool-wide defects no census could see; Ice Age is the largest ever ingested and brought
**346 new cards**, more than any set since Alpha; and Fallen Empires is the
smallest work set yet, 102 cards of which every single one was new. Homelands
is the second set after FEM to bring nothing but new cards — 115 of 115, with
zero overlap with the 1,610 already here, Alliances is the **third**: 144
of 144 new, sharing not one oracle_id with 5ED or M21, and Visions is the
fourth — 167 of 167 new, sharing not one oracle_id with *any* set in the pool.
**Weatherlight is the fifth, Exodus the sixth, Urza's Destiny the
seventh, Nemesis the eighth and Prophecy the ninth**, and all five are clean the same way: 167 of
167, 143 of 143, 143 of 143, 143 of 143 and 143 of 143 new, each sharing with every set before it not one oracle_id **and
not one card name**. **Planeshift is one card short of a tenth**: 142 of its 143 are new, and the one that is not is
the whole of its promotion story (below). **Apocalypse is the tenth**: 143 of 143 new, sharing
not one oracle_id and not one card name with the thirty-one sets before it. `set_progress.json` records UDS with 142 new cards and it
brought 143, for 6ED's reason one column over — that number counts against the
whole release line and this manifest is a subset of it. **Mirage breaks that run** — 313 of its 335 are new and 22 were
already here, which makes it the
first set since 4ED whose insert position can move a card's origin. **Tempest
sits between the two shapes and is the one to reason from**: 309 of its 335 are
new and the 26 that were not are almost all furniture — twenty basic lands plus
Counterspell, Dark Ritual, Pacifism and a few more — so its insert position
moves **no card's origin at all**, and the printing-order guard is the only
thing that can catch a wrong one.

**Mercadian Masques is Tempest's shape again and the most emphatic instance of
it**: 311 of its 335 are new, and every one of its 24 reprints already had a
printing earlier than 1999 in this pool — so, uniquely among the sets that
carry reprints, *no* card's origin turns on its insert position, checked
rather than assumed. The rehearsal was run anyway and is what makes that a
statement instead of a hope: appended after M21 it fails
`test_the_shipped_sets_are_in_printing_order` at index 24 while the prefix
guard stays green, which is the division of labour those two guards are
documented to have.

**Stronghold is the shape that looks like Tempest's and is not, and the
difference is one card.** 142 of its 143 are new, so it reads as an all-new set
and the prefix guard is blind to its position for the seventh consecutive set.
But its single reprint is **Shock**, whose only other printing is **M21** — not
Tempest — so STH's insert position decides Shock's *origin*: at index 18 it
reads `sth`, and appended after M21 it reads `m21`, with every guard green
either way. That is Mirage's Volcanic Geyser exactly, in a set whose one shared
card makes it look impossible. **Count the reprints against the sets that
actually print them, not against the set you expect.**

**Exodus is what that rule looks like when the answer comes back clean**, and
it is worth keeping beside Stronghold rather than instead of it. EXO shares
**zero oracle_ids and zero card names** with the twenty sets before it, so its
position really cannot move any card's origin — but that was *measured at the
promotion*, in both directions, rather than inferred from the block the way
Stronghold's was. The rehearsal costs a minute and is the difference between
"it looks immune" and "it is".

**Invasion is that lesson a third time, down to one card again, and the first
set to bring machinery rather than only cards.** 310 of its 335 are new and 25
were already here, and of those 25 exactly **one** — **Opt** — has its only
other printing in M21. Rehearsed at the wrong end with the same move script as
the real promotion, Opt's origin read `m21` while the prefix guard stayed green
and `test_the_shipped_sets_are_in_printing_order` failed; at index 27 it reads
`inv`. What the set brought that no set before it had is three things the
engine did not have at all: **kicker** (CR 702.33, 35 cards — a rewrite onto
buyback's optional-additional-cost machinery, so no keyword flag exists),
the pool's **first multi-face layout** (five split cards, CR 709 —
`engine/faces.py`), and **separating into piles** (CR 700.3, six cards —
`engine/piles.py`).

**Planeshift is Stronghold exactly, one block later, and the proof that the
shape recurs rather than surprises.** 142 of its 143 are new, so it reads as an
all-new set; its single reprint is **Quirion Dryad**, whose only other printing
is M21. At index 28 the Dryad's origin reads `pls`; appended after M21 it reads
`m21`, with the prefix guard green and
`test_the_shipped_sets_are_in_printing_order` the only thing that fails. It was
rehearsed twice with the same move script — on the day of the ingest and again
at the promotion — and named in the ingest's commit message before any card was
implemented, which is what the lesson looks like once it has stopped being one.
**Seventh Edition is the same card-sized trap inside a reprint set, where the
prefix guard is silent for two reasons at once.** Of its 318 reprints exactly
one — **Mind Rot** — has its only other printing later than 2001, in M21. At
index 29 Mind Rot's origin reads `7ed`; appended after M21 it reads `m21`,
the prefix guard green, the printing-order guard failing at index 29 and
nothing else. Rehearsed at the ingest and again at the promotion with the
promotion's own script; `test_7ed_cards.py` asserts the eighteen cards that
originate in the set, seventeen new ones and that one.

**Apocalypse is Exodus's shape again - clean, and measured rather than
inferred.** It is the third set of Invasion's block and shares nothing with
the pool at all, so its index (30) can move no card's origin; that was
computed at the ingest and rehearsed at both ends at the promotion, where
the wrong-end insert turned red the printing-order guard and nothing else.
It arrived at 65.7% supported, Planeshift's number to the decimal, for
Planeshift's reason: a block-mate inherits mechanics and not templates. It
brought no machinery. What it brought is three questions about an
*announcement* that the engine could not ask: a target an opponent **must**
choose (the Flagbearers, `engine/target_requirements.py`), a spell named
*beside* a permanent in one cast (Suffocating Blast, a roles announcement
with a stack slot) or *instead of* one (Illusion's "target spell or
permanent"), and which of two kickers a permanent was kicked **with** as it
enters (the five Volvers).
What Planeshift brought is the *second half* of what Invasion built: a kicker
whose cost is not mana, two kickers on one card (CR 702.33b) and the question
"which one was paid" (CR 702.33f), domain sizing a *cost*, and no machinery
the engine lacked.

**Odyssey is Mercadian Masques' shape, and the first set since Invasion to
bring machinery.** 322 of its 335 are new and every one of its 13 reprints -
five basic lands, four cards from Tempest, three from Exodus and Buried Alive
from Weatherlight - already had an earlier printing here, so its index (31)
moves no card's origin: computed at the ingest and rehearsed at both ends at
the promotion, where the wrong-end insert turned red the printing-order guard
and nothing else. It arrived at 65.4% supported with its headline keyword
**dropped** on 27 of those cards: a flashback line beside a line that
compiled left the card "supported" and uncastable from a graveyard, which
`parse_coverage --set` saw and the support count could not. What it brought
is **flashback** (CR 702.34 - a rewrite onto a cast permission that requires
an alternative cost, so no keyword flag exists; `engine/flashback.py`) and
**threshold** (CR 207.2c: an ability word, so nothing to implement but one
condition, asked of a static, an activation and a spell) - and around them
the graveyard as a place things are *chosen from*: targets out of a single
graveyard, a cost that exiles named cards from one, and an AI that had never
cast a card from any zone but a hand. `set_progress.json` records it with 321
new cards and it brought 322, for 6ED's reason: Angelic Wall has an earlier
printing in a set this manifest does not carry.

**Urza's Saga is Stronghold's lesson with three cards instead of one, and it is
the set to point at when somebody asks whether the rehearsal is worth a
minute.** 325 of its 335 are new and it shares 17 oracle_ids (32 card *names*)
with the pool — so it reads as an ordinary reprint-carrying set. But of those
17, exactly **three** — Duress, Glorious Anthem and Rewind — have their only
other printing in **M21**, and nothing else. So USG's index decides their
origin: at index 20 they read `usg`, and appended after M21 they read `m21`.
Rehearsed at the wrong end before the real promotion, the prefix guard passed
and `test_the_shipped_sets_are_in_printing_order` failed at index 20 — which is
exactly the division of labour those two guards are documented to have, observed
rather than assumed. Which is why
the per-set totals sum to far more than 5,246 — they are printings (7,741 of
them). Alliances was the
first set to reach 100% with **zero name-keyed hooks**, across all 144, Visions
is the second across all 167, **Weatherlight is the third** across all 167
again, **Tempest is the fourth and by far the largest** — 335 cards over
eighteen parallel groups in four waves, every one told a hook was the last
resort, and the set ships carrying exactly **one** hooked card, which is
Alpha's Power Sink arriving as a reprint — **Stronghold is the fifth**,
143 of 143 across ten parallel groups in two waves, adding no hook and
*retiring* one (Mana Short's, as a side effect of a noun phrase) — and
**Exodus is the sixth**, 143 of 143 across eleven parallel groups in two
waves plus a closing round, adding none — and **Urza's Saga is the seventh and
the first to move the count downward on purpose**: 335 cards across fifteen
parallel groups in three waves, adding no hook and **retiring five** — and
**Urza's Legacy is the eighth**, 143 of 143 across ten parallel groups in two
waves, adding none — and **Nemesis is the ninth**, 143 of 143 across six
parallel groups in one wave plus a closing round, adding none — and
**Prophecy is the tenth**, 143 of 143 across sixteen parallel groups in three
waves, adding none. **Four of its third wave's five groups took no card at
all**: one took the last card (Rhystic Cave, a mana ability that needs priority
and can be denied) and four went to the pile the first two waves had measured
and declined — a colour chosen at announcement instead of at
resolution (CR 608.2d), a copy that entered as the printed card (CR 707.5), an
AI simulator in which nothing had ever cost mana, and cost choices the engine
made for a human seat — and
**Invasion is the eleventh**, 335 of 335 across sixteen parallel groups in
two waves and a closing round, adding none. **Four of its second wave's seven groups took no card**,
and what they fixed was the larger half of the set's work: 182 spells castable
with no legal target to name (CR 601.2c), 17 counterspells castable onto an
empty stack with their second sentence resolving for free, ten shipped cards
with a keyword they do not print (a Licid that itself flew), and about 55
pool-wide guards that were *blind* to a split card's halves rather than red — and
**Planeshift is the twelfth**, 143 of 143 across fourteen parallel groups in
two waves, adding none. **Five of its second wave's six groups took no card**,
one card being all that was left, and what they fixed was again the larger
half: a modal spell that accepted an illegal target for the mode it announced
(1,066 of 1,516 cases; the browser was sent the wrong picker for 33 of 47
object modes), 268 of 278 entry triggers resolved inline where CR 603.3 puts
them on the stack, colour effects ordered by what kind they were rather than by
timestamp (CR 613.7), a castable highlight that glowed over 3,543 unpayable
land-and-cost pairs, and 28 shipped "as this enters, choose…" cards whose
prompt a human player could not answer in the browser at all — and
**Apocalypse is the thirteenth**, 143 of 143 across nine parallel groups in
one wave and four in a second, adding none. Wave 1 landed 48 of its 49
cards and drove every one of the 94 that arrived compiling, nine of which
mis-played; wave 2 took the one card left with its neighbour and spent
three groups on what wave 1 had measured: CR 608.2b never asked of an
ability (479 of 622 single-target activations acted wrongly once their
target was illegal, 185 of them on a bystander), five prompts the set's own
cards armed and a person could not answer in the browser, and seven
shipped defects each with a card of the set standing on it (a named cost
permanent silently replaced on 43 of 43 spells; a cast trigger finding its
spell by card rather than by stack object) — and
**Odyssey is the fourteenth**, 335 of 335 across nine parallel groups in one
wave and eight in a second, never more than five at once, adding none and
**retiring three** (Gaea's Liege, Erg Raiders, Kudzu - each onto a sentence a
card of the set also prints). Wave 1 landed 330 and declined five cards with
parts; wave 2 took those five in four groups and spent the other four on
what wave 1 had measured: CR 118.9d never applied to an alternative cost or
a waiver (43 of 43 such casts were free under Sphere of Resistance), an AI
that had never cast from a graveyard, a land tapped for mana by two of its
three roads without telling anyone (a cost an effect collected ran no mana
ability at all - 1,261 of 3,380 cases), and the set in a browser, where a
person could not see a flashback price, stop an "up to" discard early, or
answer the draw-skip prompt at all.
Reliance is **0.9% of supported cards**, 49 of 5,246, down from 52 of 4,924 and
from 53 of 3,715 before that —
and Mercadian Masques is the first set in four to move the numerator, *down*:
Food Chain is the second card to print Metamorphosis' cost-record-plus-spend-
restriction pair, which that hook's own comment said no second card printed.

USG's five are worth naming because four of them were hooks that were *wrong*,
and wrong in one way: **a hook writes the end state directly, so it is a place a
general rule can be skipped in silence.** Timetwister never shuffled. Wheel of
Fortune never announced its discards, so nothing watching a discard ever saw the
largest discard in the format. Jade Statue animated into a 3/6 that was not a
Golem. And retiring Drop of Honey's exposed a second line — "when there are no
creatures on the battlefield, sacrifice this enchantment" — that nothing had
ever implemented, which `parse_coverage` had been reporting as claimed **because
the card had a hook at all, and a hooked card's every sentence is blanket-
claimed**. That is a hole in the one instrument built to find unimplemented
lines, and only a retirement could surface it. `scripts/support_report.py` reports on the whole manifest pool, not one set. Card files hold only the fields
the engine and web layer read; `scripts/ingest_set.py` produces them. The
engine is **registry-based**: card support grows by adding small isolated
entries, never by editing core control flow.

**The manifest has two roles.** `sets` is the shipped pool above, held at 100%
supported — the web app offers those cards to players, and two guards
(`tests/engine/test_front_end_safety.py`, `tests/engine/test_card_format.py`)
fail if one of them is unsupported. `measured` is a set ingested so its numbers
can be read *before* the work of supporting it is done: the coverage instruments
load it (`manifest_set_paths(include_measured=True)`), `load_catalog` does not,
and no player can put one of its cards in a deck. **It is empty today** — M21
went in under it at 58% supported, Antiquities at 56.5%, Legends at 32.9%, The
Dark at 47.9%, Fourth Edition at 100%, Ice Age at 49.3%, Fallen Empires at
67.6%, Homelands at 66.1%, Fifth Edition at 100%, Alliances at 43.1%, Mirage
at 54.9%, Visions at 59.3%, Weatherlight at 59.9%, Tempest at 67.8%,
Stronghold at 67.8% again, Exodus at 63.6%, Classic Sixth Edition at 100%,
Urza's Destiny at 69.9%, Nemesis at 66.4%, Prophecy at 58.0%, Invasion at 66.0%, Planeshift at 65.7%, Seventh Edition at 99.4%, Apocalypse at 65.7% and Odyssey at 65.4%, and all twenty-five were promoted to `sets` once every card was, which is the role working as designed rather than a role nobody uses. 4ED is the degenerate case that shows what the role is
*for* rather than an exception to it: it entered `measured` fully supported and
left the same day, and the ingest still paid — a guard proved itself unable to
tell the roles apart for an all-reprint set, which is a finding only the
measured step could surface. 5ED repeated the shape and its ingest paid the
same way: a manifest-write guard that had baked in "measured starts empty"
fired on the first real entry. **Alliances paid it a third time, from inside a
test's docstring**: a guard listing the pool's divided-target cards asserted
equality against a list whose comment said "Alliances is still `measured`" —
a fact about today's roles written as an invariant, so it failed at the
promotion for the one reason that is not a finding. **Mirage paid it a fourth
time, and most expensively**: its promotion rehearsal found 13 printed sentences
on 11 cards that nothing implemented, six of them admitted into the support gate
by a *single whitelist word*. Every one of those cards read 335/335 supported
with zero hollow lines, because a card is supported when **any** of its lines
is. `parse_coverage.py` is the only instrument that can see it and it gates on
the shipped half alone — so the debt was invisible until the entry moved, which
is precisely what the rehearsal is for. It took a fourth wave to clear.
**6ED's ingest is the one that paid nothing, and that is a result rather than a
miss**: its rehearsal turned three guards red and all three were ratchets, where
accepting is the review — which is what four sets of guard fixes look like from
the far side, and is why the reprint-shaped ingest keeps happening rather than
being skipped. **7ED's paid nothing the same way** — a green suite at the
ingest, and an early rehearsal whose only red guards were three ratchets and
the three that name an unsupported card. The next ingested set goes there
first.

**The manifest is printing-ordered, and the order is load-bearing.** Antiquities
went in at index 4, Legends at index 6, The Dark at index 7, Fallen Empires at
index 8, Fourth Edition at index 9, Fifth Edition at index 12, Mirage at
index 13, Visions at index 14 and Weatherlight at index 16 — the first two of
those three each pushing 5ED along, to 14 and then 15, and Weatherlight landing
just past it — each *between*
the sets it was printed between rather than being appended — `CardDefinition.original_printing` is the first entry in
`printings`, so appending would have left the 19 cards Antiquities shares with
Revised reading `3ed`, and Golgothian Sylex ("each nontoken permanent with a
name originally printed in the Antiquities expansion") would have missed every
one of them. `test_appending_a_set_never_changes_an_existing_original_printing`
compares prefixes of the ordering, so inserting is legal and reordering what is
already there is not.

**That prefix guard is silent for a reprint set — and for an all-new one — so
the order is also asserted directly.** It checks the *consequence* — no card's origin moves — and a set
whose every card already has an earlier printing cannot become anyone's origin
from any position. Verified at the 4ED promotion by appending it after M21: the
whole suite stayed green with the set four places out of order.
`test_manifest_roles.test_the_shipped_sets_are_in_printing_order` compares the
`released` dates the entries already carry, which is the invariant itself
rather than a second list to maintain.

**Mirage is where that silence acquired a named card.** Rehearsed at the wrong
end, the prefix guard stayed green while **Volcanic Geyser** — in MIR and M21
and nowhere earlier — would have had its origin read `m21`. Appending a set
moves no *existing* card's origin, which is exactly what the prefix comparison
tests, so the failure is invisible to it by construction: what moves is the
**new** set's own card. Rehearsing the wrong insert costs a minute and converts
that from an assumption into an observation; do it at every promotion.

**A measured set is nameable by the reporting scripts** — `--set <CODE>` works,
and the label says "measured, not shipped" so its numbers can't be read as
shipped-pool ones. That is the point of ingesting it: `support_report.py` naming
the unsupported cards and their reasons is the tool you implement a set *with*,
and it used to exit "no set in the manifest", leaving `--cards
cards/<CODE>_cards.json` — the spelled-out filename the convention forbids — as
the only way through. Reading a card file is not shipping it; `load_catalog` is
the seam that decides what a player can deck. `--all` still means the shipped
pool alone, in the paths *and* in the label. A measured set is reported by
`GRAMMAR_COVERAGE.md` / `HOOK_RELIANCE.md` / `PARSE_COVERAGE.md` and
deliberately left out of their floors, ceilings and gate — a ratchet over a set
nobody has implemented fires on its composition rather than on anything anyone
did. It moves up to `sets` when it is
fully supported. Guarded by `tests/engine/test_manifest_roles.py`. The
end-to-end process — ingest → measure → rounds → promotion → retrospective —
is `SET_PLAYBOOK.md`.

`ROADMAP.md` tracks the work to scale from this pool to the full ~26,000-card
release line — read it before parser or card-data work.

## The verification tracker, set by set

`CARD_VERIFICATION.md` / `card_verification.json` track which cards have been
manually validated in-game (754 of the 5,246 catalog cards passing — 497
checked in-game and 257 auto-passed — with 59 more reported `equivalent`; the
rest — almost all of M21, Antiquities, Legends, The Dark, Ice Age, Fallen
Empires, Homelands, Alliances, Mirage, Visions, Weatherlight, Tempest,
Stronghold, Exodus, Urza's Saga and every set since, Invasion, Planeshift,
Apocalypse and Odyssey included, all promoted before their in-game pass —
have no
recorded result yet, which SET_PLAYBOOK.md Phase 5 owns and deliberately does
not gate promotion on; the summary at the top of the markdown is the current
number).

**Exodus is the first set in five whose Phase 5 moved the checked-in-game
number**, from 392 to 398 — not because a coverage target was set, but because
six of its cards had to be driven in the app to find the defect below, and a
card you have just watched work is a result worth recording. Fourth and Fifth
Edition are the two promotions that did not add to that backlog, because they
added no card to
verify — the tracker is keyed to the deduped catalog, so a reprint set inherits
every result its cards already have. **Classic Sixth Edition added exactly
one**, Blaze, because Regal Unicorn is a vanilla creature and auto-passes: the
smallest non-zero Phase 5 in the project, and the number that says what "almost
a reprint set" costs. **Ice Age is the opposite pole**: 346 new
cards, the largest single addition to the untested count since the tracker
existed, which took it from 708 to 1,020; Fallen Empires added 99 more of its
102 (two auto-pass and one is `equivalent`), to 1,119; Alliances added 144 new
cards of which 4 auto-pass; Mirage, Visions and Weatherlight then added 313,
167 and 167 more, and Tempest, Stronghold and Exodus 309, 143 and 143 after
them, taking the untested count to its high-water mark of 2,495.
**The checked-in-game number moved at Exodus for the first time since
Alliances**, 392 to 398, and the *reason* is the one that matters: nobody set a
coverage target. Six cards were driven in the app because Phase 5 needed them
driven, and a card you have just watched work is a result worth recording. The
decision SET_PLAYBOOK.md's Known gaps records still stands — an in-game pass is
not a required validation step, the tracker is read as a log and never as a
coverage target, and what gates a promotion is Phase 4 — and this is what that
decision looks like working rather than being abandoned: the number rises as a
by-product of finding bugs, not as a quota.
**Planeshift moved it the same way, 404 to 407**: Meddling Mage, Voice of All
and Shifting Sky were driven in a browser as a human seat to check that an
entry choice could be answered and reached the wire, and the driving found
the wire reporting a colour *before* it was chosen — the engine's provisional
default, sent as a choice while the prompt was still on the screen.
`enter_effects.chosen_as_entered` reports nothing for a permanent that is
still entering.
**Seventh Edition moved it 407 to 409** — Sleight of Hand and Baleful Stare,
driven as a human seat — and the same session's one click on a land under a
Blood Moon found that the round's activation-gate merge had made every such
land unclickable for mana: a client change held by a text-level test, first
clicked at Phase 5.
**Apocalypse moved it 409 to 433 — more than the twelve promotions before it
added between them — and recorded a failure on the day a set shipped.** Phase 5 was one
agent with a brief: twenty-two of the set's cards were watched working in the
app and recorded, and two were recorded **failing** — Fire could not be aimed
at a player (every divided spell with a ceiling of targets was handed the
several-permanents picker), and Tahngarth's Glare ended its caster's phase
(an AI-owned prompt armed by a human's answer was not answered in the same
request). The smoke game beside them found a human's precombat main phase
being skipped whenever the AI acted in its second main phase. A closing round
fixed all three, and each failing row was re-recorded only after the card was
watched working — which is the rule in the next paragraph, kept on the first
occasion it could have been skipped.
**Odyssey moved it 433 to 497 — more than twice Apocalypse's move — and its
Phase 5 is the first to need two closers.** One agent played a whole game
and four lists and recorded 71 cards, six of them **failing**: Abundance and
Pursuit of Knowledge (two draw replacements locking a multi-card draw),
Lodestone Bauble (the wrong player drew), Fork (no new target for a copied
"any target" spell), and two filter lands asked which colour they add. By
playing rather than by card it found End Turn stalling its own turn in
declare blockers and "Pay" on a toll being read as a decline. The defects
were split by where they live: the agent with the browser took the client,
a second took the engine with a census per item, and the first then drove
the second's fixes in the app. Fork was recorded failing a **second** time
on the way — its one-target copies worked and a copy of a several-target
spell lost its targets, through an arm of the resolution neither closer
had read — and passing only after a third fix was watched. Every row was
re-recorded by the agent that had watched it fail, which is the rule in the
next paragraph kept six times in a day.
A card can also be recorded **failing**: that
is an in-game bug report with a card name on it, and it stays in the tracker
until the card is fixed **and re-checked in the app** — fixing the code does not
clear the row, which is how Candelabra of Tawnos and Silent Dart went on
reporting ❌ for three days after their fixes landed. The failure count is 0.
**Generated automatically** — results are edited via the in-game Debug Menu, not
by hand.

A *simple* card — no abilities at all, or nothing but keyword lines the engine
implements (`engine.oracle.simple_card_keywords`: a vanilla creature, a
keyword-only creature, a basic land whose only text is CR 305.6's reminder
text) — is **auto-passed**: its behaviour is the generic combat and keyword
code plus its printed numbers, so a manual check would exercise no
card-specific path. It counts as a pass, the note names why ("auto-pass: no
abilities" / "keywords only (flying, prowess)"), the summary keeps the
auto-passed share beside the checked one, and the Debug Menu's "add an untested
card" never offers one. Derived on read from `web/runtime.py`'s `AUTO_PASSES`,
never written to the JSON; a result recorded in-game always wins over it, and
it does not seed `equivalent` (an auto-pass is weaker than a check).

A card is also reported `equivalent` when it is untested but a *passing* card
shares its behaviour class: the engine resolves both through the same code
paths, so a separate manual pass would exercise nothing new. That status is
derived on read, never stored, so it can't be mistaken for a human check and it
withdraws automatically if its peer is later marked failing.
`engine/behaviour_signature.py` computes the classes and
`scripts/behaviour_classes.py` regenerates `BEHAVIOUR_CLASSES.md`; `--check`
fails when classes drift, because a signature that stops distinguishing two
behaviours silently *raises* apparent coverage.
`tests/regressions/test_card_verification_regressions.py` guards against regressions in
verified cards.
