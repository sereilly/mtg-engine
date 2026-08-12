# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 182/285) to the full release line - **137 sets, 33,594
printings, 26,113 unique cards** per `set_progress.json`.

A chronological engineering journal. Trimmed 2026-08-10 to the current M21
work: the founding audit, the parser migration (finished - `engine/parsing/`
is deleted and `engine/grammar/` is the only parser), and the earlier per-set
narratives live in git history at and before commit `22bd726`. The process a
set follows is `SET_PLAYBOOK.md`.

---

## M21 Phase 2–3: the census, and the keyword round

*(2026-08-10)* The first set implemented under `SET_PLAYBOOK.md`, which this
session also wrote. Phase 0 drained two known gaps: the stale tracker rows
(HOOK_RELIANCE's M21 line lagged lifelink's two cards) and the fixture seam —
`manifest_set_path` grew the `include_measured` passthrough `manifest_set`
already had, so `set_pool("M21")` resolves and a card can land with its
focused test while the set is still measured. The convention guard now proves
both directions: every manifest code reachable through the factory, a
measured code still refused by a caller that has not opted in.

**The census (Phase 2), by three read-only classifiers over the 179
unsupported cards.** Keyword-gated: 20 cards, of which only 5 fall to
keywords alone — the census names them, and Baneslayer Angel's "protection
from Demons and from Dragons" is the sixth that doesn't (non-colour
protection qualities are unmodelled, and admitting the word would drop the
shield). Blocked on subsystems: the 11 planeswalkers (CR 306 — loyalty,
`unknown card type`; scoped, not started), scry (no parse, no handler,
nothing — also gates Wall of Runes, Spined Megalodon, Stormwing Entity),
search-by-name/graveyard (5+ cards), exile-until-leaves (3), per-turn
trackers ("life gained this turn", "drawn two or more cards this turn"),
reflexive triggers, modal choose-one-or-more. The rest is round material,
and the census ranked it by cards-per-change:

1. **Token naming** — `_lower_create_token` refuses every unnamed token;
   picking the CR 111.4 convention unblocks ~12 cards across all three
   slices. The single largest blocker in the set.
2. **Counters on a non-source subject** — `put_counter_on_target` /
   `put_counter_on_each_you_control` kinds; ~12 cards census-wide.
3. **`up to N target`** — a noun-phrase production the lowering already
   honours; ~10 cards.
4. **`each opponent` as damage/life-loss/mill/discard recipient** — recipient
   widening in four lowerings; ~8 cards.
5. **The `_KEYWORD_GRANTS` table → payload-driven grant** — "gains
   deathtouch/indestructible/hexproof until end of turn"; ~7 cards.

One landmine the census wrote down before it could fire: the oracle trigger
regexes are unanchored prefixes, so `whenever you cast a spell` already
claims Quirion Dryad's colour-narrowed trigger and `at the beginning of
combat` claims "on your turn". Fixing only an *effect* under one of those
four cards would compile it supported **firing on the wrong event** —
narrow the conditions first (Quirion Dryad, Snarespinner, Gloom Sower,
Battle-Rattle Shaman / Dire Fleet Warmonger / Adherent of Hope).

**Round 1 (keywords): 106 → 110.** Six keywords, each landing as one rule at
one seam, covering everywhere the CR says it applies rather than the paths
M21 exercises. Deathtouch moved onto `_mark_damage_on_permanent` beside
lifelink — the same shape as the lifelink fix, found the same way: the
combat step stamped `received_deathtouch` and a ping did not. Indestructible
was machinery-without-a-gate (`_is_indestructible` already consulted the
keyword). Flash is a `CardDefinition` accessor read by the web layer's two
sorcery-speed gates; menace an assignment-level check in `declare_blockers`
plus an AI that declines the lone block; hexproof a seat-aware branch in
`_can_be_targeted` beside protection, with "hexproof from <colour>" kept
distinct (it is a different, narrower keyword); prowess a sweep on the
cast-trigger path through `engine/pt.py`. The keyword-line gate learned the
comma-joined parameterised forms for colour qualities only, and
`_protection_colors` learned to read protection off keyword lines — the
reclassification would otherwise have silently dropped Black Knight's
shield, which `tests/rules/test_protection.py` caught on the first run.
Fourteen rules tests cite 702.2b/.8/.11/.12/.108/.111; `SCOPE` widened to
match. The four unlocked cards are Mistral Singer, Masked Blackguard, Bone
Pit Brute, Ornery Dilophosaur; 15 more keyword-plus cards moved one line
closer. Cost: one positional-indexing ratchet near-miss (rewritten to reuse
already-resolved permanents rather than raise a baseline), zero hooks, zero
ceiling raises, suite at 18.3s.

Next round per the census ranking: token naming, then counters-on-target,
then `up to N target`.

---

## M21 rounds 2–4: the census ranking, executed

*(2026-08-10, same day.)* Three rounds off the top of the ranking,
110 → **120** supported, each landing with the suite green and every ratchet
untouched.

**Round 2 — token naming (110 → 115).** CR 111.4 settles the refusal the
lowering had recorded: an unnamed token is "<subtypes> Token" (the CR's own
Dwarf Berserker Token example), so the rule landed once in `engine/tokens.py`
as `default_token_name`, the grammar takes it, and Rukh Egg's hook fell in
line — "Bird" became "Bird Token", the CR-correct spelling, with the ARN
tests updated and the Scryfall art lookup matching the suffix-stripped name.
Bought Valorous Steed, Deathbloom Thallid, Goblin Wizardry, Sporeweb Weaver
and Speaker of the Heavens; Falconer Adept stays gated on its
tapped-and-attacking rider.

**Round 3 — counters beyond the source (115 → 116).** The put-counter
lowering learned the target and each-you-control subjects. The target form
joins `add_counter_to_target` — the kind Dwarven Weaponsmith's hook has
emitted since LEA *with no handler behind it*, the shipped pool's quietest
gap: the ability resolved to nothing, and no guard minded because
`test_no_hollow_support` only reads instants and sorceries. One card flipped
(Basri's Solidarity); the yield is the machinery, which every counter card
behind the up-to/protection/trigger gaps now lowers through. The label
lesson: the grammar claiming Dwarven Weaponsmith's clause moved its label
source, and the historical `triggered_counter` misnomer moved into
`ACTIVATED_LABELS` documented rather than corrected — the label module
carries the legacy vocabulary, it does not fix it.

**Round 4 — each-opponent recipients (116 → 120).** Damage and life loss
both accept "each opponent", on the same recipient key the caster branch
already used; the damage loop is resumable through the one player-damage
path, life loss is CR 120.3-plain. "You lose N life" came with it, which is
the half that completed Grim Tutor. Bought Storm Caller, Spirit of
Malevolence, Grim Tutor and Caged Zombie. The up-to quantifier also consumes
its "target" now — parse groundwork the lowering already honoured, banked
for Frost Breath/Barrin/Sanguine Indulgence once their second gaps close.

**Round 5 — keyword grants as payload (120 → 123).** The three-entry
`_KEYWORD_GRANTS` table keeps its pairs; everything else rides
`grant_target_keyword_until_eot` / `grant_self_keyword_until_eot`, payload
keywords looped through `grant_keyword`'s layer-6 grants, **gated on
`IMPLEMENTED_KEYWORDS`** — the grant machinery would put any word into layer
6, but a word without behaviour is a grant of nothing, so the lowering
refuses it at the same bar the printed-keyword gate holds. Multi-keyword
sentences are one instruction. Bought Sure Strike, Ranger's Guile, Fetid
Imp; Ranger's Guile's test proves the grant is real (the hexproofed creature
refuses the opposing Shock and accepts its controller's). Selfless Savior
and Seasoned Hallowblade stay gated on their sacrifice/discard costs,
Alchemist's Gift on its choose-one-of-two, Heroic Intervention on the mass
scope.

**Round 6 — mana value is payload (123 → 124).** The census's "single
precise fix" inside the search cluster: a literal bound ("mana value 3 or
less") now rides `ObjectFilter.to_payload` and `permanent_matches_filter`
tests it against the effective card's cmc (CR 202.3), so Eliminate compiles
and its cast validation refuses a four-drop. A *variable* bound ("mana value
X") still refuses — no payload form, and dropping it would widen the effect,
so the old never-dropped guard split into one test proving the bound is
carried and one proving X still refuses. The search production also learned
"reveal it," (honoured by the flow's public log) and "put it into your hand"
— banked groundwork, since Fierce Empath still waits on its you-may trigger
and MV-in-search-flow.

**Round 7 — trigger conditions carry their own narrowings (124 → 126).**
The two fixed-phrase members of the family, each landed narrowed on *both*
sides of the pipeline (oracle regex table and grammar phrase/parser),
specific-before-prefix per the tables' own ordering rule — which is the
landmine defused for these forms rather than left to discipline.
`combat_your_turn` is emitted at the beginning-of-combat step over the
active player's battlefield alone (Adherent of Hope; Battle-Rattle Shaman
and Dire Fleet Warmonger still need their effects). Quirion Dryad's
colour-list cast trigger narrows `you_cast_spell` with the list as condition
payload, checked by the cast filter as the union CR 105.4 says an or-list
is; the per-set test proves the negative (a green Titanic Growth pumps
without a counter). Snarespinner and Gloom Sower stay gated — their block
narrowings need an object filter on the event, not a fixed phrase, and
Gloom Sower's fires once per blocker besides.

**Round 8 — the causative wrapper, and the enqueue path it exposed
(126 → 128).** "You may have it deal 1 damage" is the optional form of "it
deals 1 damage", and the verb table already accepted the uninflected
spelling — so the parser's whole change is consuming "have" inside the
existing may wrapper. The real work was runtime: a dying creature's own
"When this creature dies, you may …" trigger had no enqueue path (the three
specific dies shapes are inline, each for its own recorded reason), so the
may wrapper now goes on the stack (CR 603.3) and resolves into the standard
optional prompt with the action armed on accept. Bought Goblin Arsonist and
Battle-Rattle Shaman — the second riding round 7's `combat_your_turn`
condition, which is the census's stacking pattern paying out: two rounds,
neither sufficient alone, one card each plus this one together.

**Rounds 9–11 — three groups designed in parallel, applied in series
(128 → 137).** Worktree isolation is refused in this repo, so the fan-out was
*design*: three agents each verified a group against the live compiler and
returned an applyable spec, and one applier landed them one at a time with the
suite and every `--check` between. The specs found more than they were asked
for, and in both cases the find was **silent wrongness in cards that already
reported supported**:

- **Scry (CR 701.22, not 701.18 — the spec corrected the brief).** It had no
  parse and no handler, and *seven* cards compiled supported anyway: a card is
  supported when **any** line is, so Opt, Mazemind Tome and the five Temples
  were carried by their other sentence while "Scry N" produced nothing. Scry
  now lands as a choice — keeping every card is a legal outcome of a scry but
  never a legal implementation, since the decision *is* the effect — with one
  production, one handler arming the pending-choice queue, a resolver
  validating a permutation plus a bottom count, and an AI default reusing the
  tutor scoring. Mill's miller joined the `recipient` key, and got the
  bare-imperative parse "mill four cards" needed to reach lowering at all.
  Bought Wall of Runes, Spined Megalodon, Temple of Malady.
- **Search (CR 701.19).** What a search may find was three separate guesses —
  engine, AI, web picker. `engine/search_filters.py` is now the one predicate
  all three consult, the lowering refuses any restriction it cannot test, and
  the answer is re-checked on the way back in (the picker's legal indices are
  a hint; a client offering a whole library could otherwise turn "a creature
  card with mana value 6 or greater" into Demonic Tutor). The production grew
  the two-zone fetch and "for a card named X" as branches. Bought Fierce
  Empath, Chandra's Firemaw, Garruk's Warsteed, Teferi's Wavecaster,
  Liliana's Scorn.
- **Activation costs.** The sharpest find: the grammar parsed `SacrificeCost`
  / `DiscardCost` and **discarded them**, while the charged cost came from a
  separate regex reader that knew only tap/exile-self/sacrifice-self. Atog
  therefore pumped +2/+2 for free, repeatably, *in the shipped pool* — with
  Dwarven Weaponsmith and Witch's Cauldron beside it. Costs are now checked
  for payability before anything is paid (CR 602.5c: unpayable means
  unactivatable, not free) and collected on activation (601.2h). A cost the
  charger cannot express refuses the line, so Portcullis Vine is honestly
  unsupported rather than eating any creature.
  `tests/engine/test_activation_costs.py` compares the two readers over the
  whole pool — the guard that would have caught it.

**Rounds 12–14 — a second parallel fan-out, and what it found (137 → 137).**
Three more groups designed in parallel and applied in series. The card count
is flat because two of the three rounds *withdrew* cards that were being
played wrongly, which is the direction the invariant wants:

- **Exile as a destination.** `_lower_exile` had been naming its own gap in
  its refusal string; it now has two handlers, split by the zone the subject
  names. The card that paid for it was already in the pool: **Return to
  Nature** reported supported on its first two modes while the third carried
  *no instruction at all* — a mode the UI offered and the spell then silently
  declined to play. The duration guard is the load-bearing part: an exile
  carrying a duration the until-end-of-turn branch does not name refuses
  rather than falling through to the permanent exile, which would never give
  the card back.
- **CR 603.4 finally has a reader.** The grammar has lowered a trigger's
  intervening-if onto the payload since it learned to parse one, and
  **nothing read it** — the same failure the legacy compiler was replaced for,
  one layer further along. **Adherent of Hope**, shipped by round 7 of this
  same effort, reads "if you control a Basri planeswalker" and was putting
  its counter down every combat with no Basri in play; round 7's test
  asserted that behaviour. The condition is checked on resolution now and the
  test asserts the rule. Two per-turn trackers came with it
  (`life_gained_this_turn`, written after replacements so a replaced gain
  gains nothing; `creatures_died_under_your_control_this_turn`, per seat
  because the game-wide count cannot answer "under your control"), both reset
  for *every* seat, because "this turn" is the turn and not the player's turn.
  Bought Indulging Patrician.
- **"Up to N" is not one target.** `_is_target` accepted the `up_to`
  quantifier and every consumer then discarded `TargetSpec.count`, so
  **Rewind** untapped one land of "up to four" and reported itself supported.
  What a lowering may accept is *one* target, and `_is_target` is now the one
  place that says so — "up to one" still qualifies, anything larger refuses by
  name per effect family.

## Round 15: a design round that shipped nothing, and found three bugs

*(2026-08-11.)* Three more groups designed in parallel — multi-target, reveal /
look-at-the-top, planeswalkers. **No code landed.** The planeswalker stage was
applied and then reverted (below); the other two specs are worth more than a
rushed application of them, because each names a live defect that has to be
fixed *first*. Read this section before writing any of that code.

**P0 — arming a pending choice does not suspend the steps behind it.** Verified
by execution, and it is a bug *this effort introduced* with the scry round:

```
ran scry            -> (True, 'pending_scry')  hand=[]         pending=[scry]
ran draw_controller -> (True, 'resolved')      hand=['Mountain'] pending=[scry]
```

**Opt draws the card its own scry has not yet arranged**, then the scry
rearranges the *next* card. `engine/resumption.py` stops on
`game.effect_suspended`, and that flag is set in exactly one place —
`engine/replacements.py` — never by `arm_pending_choice`. Every prompt that
decides what a *later step of the same resolution* will see has this. The fix
is a per-kind `suspends` flag on `ChoiceSpec` (opt-in: `sacrifice`, `discard`
and `mana_payment` complete inline today and flipping them all at once is a
rewrite), set in `arm_pending_choice`, cleared with a `resume_after_answer` in
`resolve_pending_choice` — the shape `_resolve_effect_order` already uses.
**Track Down cannot be implemented correctly until this lands** ("Scry 3,
*then* reveal…" is exactly the ordering that is wrong), and See the Truth's
production must stay one instruction spanning both printed sentences for the
same reason.

**P1 — the hollow-support contract excludes permanents.** `Mazemind Tome`
reports `supported=True` while *both* its activated abilities carry
`instruction=None`: it is carried by `spell_pattern` substring markers, and
`test_no_hollow_support`'s contract is restricted to instants and sorceries.
A permanent whose every ability is unsupported reports supported and does
nothing. `Nine Lives` has the same shape. The fix is to extend the contract to
permanents whose only instructions are `spell_pattern` markers **and** which
have at least one ability line that failed to parse — the second conjunct is
what keeps Howling Mine-style statics legitimate.

**P2 — enters-the-battlefield triggers drop the permanent id.**
`_apply_self_enters_battlefield_triggers` builds its context without
`target_permanent_id`, so every ETB trigger that targets resolves by index
alone and hits whatever slid into the slot when something died in response.
Oubliette is the named shipped example. One parameter, threaded through.

**The planeswalker stage was applied and reverted.** Stage 0 (the card type,
loyalty as counters, CR 306.5b entry, and an all-of support gate so a
planeswalker cannot report supported with two of its three abilities dead) is
correct as designed and flips **zero** cards — its value is that
`support_report.py` starts naming the unreadable clause instead of saying
"unknown card type". Applying it surfaced an interaction not yet understood: a
4-loyalty walker leaves the battlefield with no state-based predicate matching
it, and `all_permanents()` does not see a permanent placed directly on a
`PlayerState.battlefield` in a synthetic game. That is a control-seam question,
not a loyalty one, and shipping a half-understood state-based action is exactly
what this engine refuses. The spec stands; the seam has to be understood first.
Worth knowing when it is retried: the existing 704.5i sweep has been **dead
code** — it read a metadata key nothing ever wrote — and the 8-of-33 measurement
says no planeswalker has more than one readable ability, so the block needs
Stage 3 (25 missing effects) before any of it flips.

**Order for the next session:** P0, then P1, then P2 — all three are
correctness, and two of them make cards *stop* lying. Only then the feature
work: See the Truth (self-contained once P0 lands), the multi-target handlers
(Rewind and Basri's Acolyte, and note Rewind's lands are **not targets** — the
parser was discarding whether the word "target" was printed), then the
subsystems.

---

## Round 16: P0, P1 and P2 applied — and the fourth bug they uncovered

*(2026-08-11, same day.)* All three correctness items landed, plus a fourth
found while verifying the first, each with a guard that was watched to fail
before the fix. M21 **137 → 134** supported, and the drop is the point: the
three cards it lost were reporting support and doing nothing, while three
*others* (Opt, Revitalize, Defiant Strike) stopped playing as strictly smaller
cards without changing the count at all — which is worth noticing about the
count as a measure. Shipped pool untouched at 388/388, every `--check` green,
suite green.

**P0 — `ChoiceSpec.suspends`.** One field, set in `arm_pending_choice` on the
*queueing* path only (a `default_at_arm` seat has already taken its answer, so
nothing is waiting), and lifted at the one completion point shared by
`resolve_pending_choice` and `take_choice_default`. The ordering there is
load-bearing in a way the spec did not say: the flag is cleared **before** the
answer is applied, never after, because applying an answer can arm the next
prompt and a clear afterwards would resume straight through it. A *rejected*
answer puts it back — the prompt is still owed, so the work behind it is still
waiting. `effect_order` became the first user of the field rather than keeping
its hand-set flag in `engine/replacements.py`, which is what makes the ratchet
test (`test_the_kinds_that_suspend_are_the_ones_that_shape_a_later_step`) a
complete list rather than three quarters of one. Opted in: `scry`,
`search_library`, `reorder_library` — the three whose answer *is* the shape of
the library a later step reads.

Two things fell out that the spec did not name:

- **CR 608.2n starts being observable.** A searching spell is off the stack, out
  of hand and *not yet in the graveyard* while its prompt is open, because the
  graveyard move is the last step of a resolution that is now genuinely
  suspended. That is correct and it is a state a client can see, so it has a
  web-API test (`tests/ui/test_search_prompt_ui_api.py`) as well as a rules one.
  The alpha sweep needed the same distinction rather than a blanket "the spell is
  in the graveyard".
- **An undrained suspending prompt wedges the whole game**, not just itself: the
  flag stops the *next* resumable loop anywhere, with nothing pointing back at
  what set it. The web path drains AI-owned prompts generically and is safe; the
  headless simulator names its kinds in a fixed order for seed determinism, so
  the two new kinds were added there and a guard derives the requirement from the
  registry (`effect_order` exempt by construction — a non-interactive seat is
  answered before it is ever queued).

- The prose citation was wrong in four places, including this file's own: the
  "card into the graveyard as the last part of resolution" rule is **608.2n**;
  608.2m is "continues to resolve fully". Search is **701.23**, not 701.19
  (regenerate) — the round-11 comments took that number from a different CR
  revision.

**P1 — the hollow gate reaches permanents.** In the compiler, beside the
instant/sorcery gate it now shares a comment with, because "reports supported"
is what the complaint was about: a test-only version would leave
`support_report.py --set M21` still naming Mazemind Tome as supported. A
permanent is refused when every card-level instruction is a `spell_pattern`
marker *and* every ability line it prints failed to parse. The first conjunct is
doing more work than the spec credited it with — a permanent whose behaviour
lives in a rule table leaves a `derived_static_rule` behind, so **Howling Mine is
kept by the first conjunct, not the second**. Refused: Mazemind Tome, Sanctum of
Shattered Heights, Sanctum of Tranquil Light.

Auras are excluded by shape rather than by name, and that is the load-bearing
part: `engine/auras.py` runs first, is stricter (it names the first unclaimed
*effect* line), and knows about the Aura death trigger that
`mixins/effects.py:_trigger_aura_death_effects` carries with no instruction of
its own. **Creature Bond** has exactly the refused shape and works; without the
exclusion the shipped pool would have dropped to 387/388 on a card that is fine.

Two corrections to the spec, both by measurement:

- **`Nine Lives` does not have this shape.** Its last line compiles to a
  supported `player_loses_game` trigger, so it does do something. What is
  actually wrong with it is a *larger* class the gate deliberately does not
  touch: a card that reports supported while implementing only some of its
  lines. Its damage-prevention replacement and its exile trigger produce nothing.
- **`Fabled Passage` is hollow and stays supported.** A land with no mana ability
  and one unreadable ability, so it does literally nothing — but it has *zero*
  instructions rather than marker-only ones, and it is carried by the separate
  "a land is always at least playable" rule. Overturning that rule is a design
  decision with its own reasoning to write down, not a conjunct to widen.

**P2 — the ETB trigger keeps its target's id.** One parameter. Oubliette is the
only card in the shipped pool with a targeting enters-the-battlefield trigger,
and the regression drives the renumbering deliberately: a distractor in a lower
slot dies while the enchantment is on the stack, and the pre-fix engine phases
out the bystander that slid into the chosen slot. It joins
`tests/regressions/test_target_survives_renumbering.py` beside the spell and Aura
cases.

### The fourth bug, found in the same round and fixed with it: a multi-line spell ran only its first line

Found while confirming P0 against the real cast path, which is the only reason
it surfaced — **P0 alone did not fix Opt.** `_select_executable_instruction`
returned the first non-`spell_pattern` instruction and stopped, while
`_noncreature_line_instructions` gives an instant one instruction *per printed
line*. A card whose clauses are one line compiles to a `sequence` and was fine; a
card that prints them on two silently dropped the second. Cast for real,
headless, before:

```
Opt         -> scried 1, hand=[]        (never drew)
Revitalize  -> life 20 -> 23, hand=[]   (never drew)
```

Three M21 cards (Opt, Revitalize, Defiant Strike) and **no shipped card** — the
shipped pool has no instant or sorcery with two effect lines, which is why it
survived four sets. The fix fuses the executable instructions into one
`sequence` (CR 608.2c, "follows its instructions in the order written").

**It is fused at the resolver, not in the compiler**, and that is the whole
design question. `whole_card` already distinguishes the list's two meanings: for
an instant it is the program that resolves, for a permanent it is a *mirror* of
everything the card does, scanned by kind by the layer bridge, the upkeep pass
and the AI. Fusing in the compiler would flatten the mirror into an opaque
`sequence` and break every one of those readers. `_select_executable_instruction`
has exactly one caller and only instants and sorceries reach it, so it is the one
place where the list is unambiguously a program.

Composing through `sequence` also means the fix arrives already carrying P0: the
steps run through `run_resumable`, so Opt's draw waits for its own scry. That is
`test_opt_scries_before_it_draws` — the two halves of this round meeting on the
card that motivated both.

**Suite time is unchanged.** ~30s on this box both before and after the round
(three runs each, ±0.2s); the 23s baseline in `ci.yml` is the runner's number and
is left alone. The fourteen tests added cost nothing measurable.

Two things this round wrote down and did not act on:

- **`Nine Lives`' class — partial implementation reported as full.** It has one
  supported trigger, so it is honestly supported and honestly incomplete: its
  damage-prevention replacement and its exile trigger produce nothing. The
  hollow gate cannot see this and should not try; the class needs a census of
  its own, in the shape Phase 2 uses for a set.
- **`Fabled Passage`.** A land with no mana ability whose only ability is
  unreadable, kept supported by the "a land is always at least playable" rule in
  the compiler. That rule is right for a land that taps for mana and wrong for
  one that does not, and overturning it is a decision with its own reasoning to
  write down.

---

## Round 17: "up to N target", end to end

*(2026-08-11, same day.)* M21 **134 → 136**: Basri's Acolyte and Basri's Aegis.
Small yield for the work, and the machinery is the point — every layer between
the parser and the browser had to learn that a spell can name more than one
target, and none of them could learn it alone.

**The census reshaped the unit before any code was written.** The ROADMAP had
grouped "Rewind and Basri's Acolyte" as one job; they are not the same job.
Sorting every `up to` line in the pool by whether the word *target* is printed
splits it cleanly:

- **14 targeted lines**, of which six actually need multi-targeting (the rest say
  "up to **one**", which `_is_target` has always accepted — they are blocked on
  other things entirely).
- **5 untargeted lines**, of which Rewind is the only one blocked on the count.
  "Untap up to four lands" names no targets at all: it is a choice made on
  resolution, which is the pending-choice queue's shape, not the targeting
  system's.

So this round did the targeted family and left Rewind, which needs a different
mechanism. Six lines behind one production beats one line behind two.

**Where each layer had to change, and the one that decided the design.**

- The **carriers already existed**: `StackItem.target_permanent_index` and
  `target_permanent_id` have been "an int, a list, or None" since the permanent-id
  round, `permanent_ids_at` stamps a list positionally, and `web/actions.py`
  already resolves `target_permanent_ids` to indices and 404s on a stale one.
  Nothing on the wire needed widening — which is what a seam is for.
- `resolve_target_permanents` is **deliberately not built on** its singular
  sibling. The singular one falls back to scanning the battlefield when a chosen
  target no longer resolves, which is right for one target (hitting something
  beats fizzling) and a disaster per slot: two decayed slots would both find the
  *same* first creature and double an effect the player chose once. The plural
  one never scans, drops a slot that stopped answering (CR 608.2b) and dedupes by
  identity.
- **`_describe_several_targets` is opt-in per lowering, and that is the safety.**
  Most lowerings emit an instruction whose handler resolves exactly one
  permanent. Had the ordinary target description simply started carrying counts,
  `engine/targeting.py` would have raised a two-target picker in front of a
  one-target handler and the second choice would have been collected and
  silently dropped. A lowering says "my handler reads a list" by calling a
  different function; `_names_several_targets` keeps refusing everywhere else.
- The **count is payload, not a second instruction kind** — `add_counter_to_target`
  serves both, because the effect is identical and only the number differs.
- **`controller: "you"` became a picker narrowing** (`own_only`). It had been
  enforced only at resolution, so a picker would have offered an opponent's
  creature and then declined to affect it with nothing on screen saying why.
  That is a fix for every "target creature you control" card, not just these.
- **Two parser positions**, both found by execution rather than by reading:
  "each of" is a distributive wrapper that must be consumed *before* the
  quantifier cascade (or "each" is read as the sweep quantifier and "up to two
  target creatures" becomes every creature on the battlefield); and "other"
  prints **between the count and the word "target"**, the one position
  `parse_object_filter` cannot reach, because it reads the filter from after
  "target".
- The **AI derives its reach**, never a name list: it asks the compiled program
  for `max_targets` first (cheap, and false for every other card) and only then
  pays for the enumeration. Taking the maximum is a stated policy rather than a
  rule — "up to N" may legally take fewer, and a card that ever wants fewer needs
  a valuation, not a special case.
- The **browser picker is its own prompt**, not a flag on the single-target one:
  the player picks several, may legally stop short (CR 601.2c), and so needs a
  confirm step a one-click picker has nowhere to put. Its accumulate-and-confirm
  shape is the divided prompt's, but the two are *not* merged — a divided spell
  splits one quantity across its targets and follows up with an X prompt.

**Landed in dependency order on purpose**: the grammar production went in
**last**, so until every layer behind it worked the cards stayed honestly
unsupported rather than castable-but-half-targeted. Verified in the running app
as well as the suite — the prompt renders, the cap holds, a click on a chosen
permanent deselects it, an invalid key is refused, and confirm sends
`target_permanent_ids`.

**One finding, not acted on.** `Read the Tides` is supported on its first mode
while its second ("Return up to two target creatures to their owners' hands")
compiles to `instruction=None` — a mode the UI offers and the spell then declines
to play. That is the Return to Nature shape from round 12, one layer along, and
it is a *class*: a modal spell needs every mode implemented or the card is
lying about the ones it isn't. Worth a sweep before the next modal card lands.

**Next:** Rewind's untargeted "choose up to N on resolution" (the pending-choice
shape), the modal-mode sweep above, then See the Truth — whose remaining blocker
is a cast-zone field on the stack object, since "if this spell was cast from
anywhere other than your hand" currently has nothing to read.

---

## Round 18: the planeswalker block, retried and landed

*(2026-08-11, same day.)* M21 **136 → 147**: nine of the set's eleven
planeswalkers (Ugin, Basri Ket, Teferi ×2, Liliana ×2, Garruk ×2, Basri
Devoted Paladin) plus two cards freed by the same productions. The round-15
revert is the reason this one stuck — the control-seam question it refused to
ship past (a hand-built walker invisible to `all_permanents()`) was answered
first, and the state-based action landed with a live predicate instead of the
dead metadata read the 704.5i sweep used to be.

What the block actually took, layer by layer:

- **CR 306/606 in the compiler and activation path.** A loyalty line ("+1:",
  "−2:", "−X:") compiles as an activated ability whose whole cost is one
  loyalty symbol (CR 606.4); activation pays it by moving the counters
  immediately, so a minus that empties the walker kills it *before* the
  ability resolves (704.5i, tested). Timing is CR 606.3 — own main phase,
  empty stack, once per turn — with the one printed widening
  (`LOYALTY_ANY_TIME_STATIC`, Teferi Master of Time) read from the card's
  static lines rather than its name. The support gate is all-of: a walker with
  one unreadable ability reports unsupported naming it.
- **Combat learned its second target.** `combat_attacked_planeswalkers` maps
  attacker slot → the walker's `permanent_id` — the id, not a slot, because
  the walker renumbers on the *defender's* battlefield and a departed walker
  must resolve to nothing (CR 510.1b), not to what slid in. Unblocked damage
  goes to the walker instead of the player (702.19f), trample excess follows
  508.4.2/702.19b, and damage to a walker removes that much loyalty (306.8).
- **Emblems are CR 114 objects, not permanents**: `PlayerState.emblems`
  entries carrying a detached `Permanent` so the trigger machinery fires them,
  invisible to every board sweep by construction. Garruk Unleashed's ultimate
  is the pool's one producer.
- **Phasing (CR 702.26) is not a zone change**: `PlayerState.phased_out` holds
  the same object, id, counters and attachments intact, returned at the
  controller's next untap. Teferi Master of Time's −3 is the producer.
- **Delayed triggers (CR 603.7)** got a real list (`Game.delayed_triggers`),
  fired from declare-attackers and swept at cleanup — Basri Ket's −2.

**Left reporting unsupported on purpose:** both Chandras. Heart of Fire's
"exile the top three… you may play cards exiled this way" and Flame's
Catalyst's "you may cast target red instant or sorcery card from your
graveyard this turn" both need a cast/play-permission seam over non-hand
zones that does not exist yet, and
`test_chandras_report_the_unbuilt_permission_seam` holds them honest until it
does. It is the same missing field See the Truth is blocked on: the stack
object does not know what zone its card was cast from.

---

## Round 19: the cast/play-from-exile/graveyard seam, and both Chandras through it

*(2026-08-11, same day.)* M21 **147 → 149**: Chandra, Heart of Fire and
Chandra, Flame's Catalyst — the two cards round 18 deliberately left refusing.
The subsystem is `engine/cast_permissions.py`, and the shape is the shields
model again: one `CastPermission` collection on `Game`, granted by an effect,
asked by the cast path, swept by cleanup — never a per-card field, never a
branch in a cast cascade.

**The seam.** A grant names its seat, its zone (`graveyard`/`exile`, plus
`hand` for cost waivers), its mode (`play` covers lands and spells, `cast`
spells alone), the cards it covers *by identity*, and its duration. CR 611.2a
settled the one design question worth having: Flame's Catalyst's −2 prints no
duration, so the grant lasts — bounded by the card staying the object it was
(CR 400.7), which the identity list gives for free: a card that left the
graveyard no longer matches, and a look-alike arriving later never did. The
turn-scoped grants die at cleanup beside the delayed triggers. Consumption is
per occurrence, so a one-card grant on one of two identical copies permits
exactly one cast — the same duplicate discipline the permanent-id round bought
for the battlefield, applied to zone lists.

**The stack object learned its zone.** `StackItem.cast_from_zone` — the field
round 17 named as See the Truth's remaining blocker — plus
`exile_instead_of_graveyard`, the printed rider stamped at cast time. Every
place a spell's card leaves the stack (resolution's CR 608.2n move, both
counter paths, Word of Command's deferred finish) now routes through one
`_bin_spell_card`, because "if that spell **would be put into your graveyard**"
is a replacement (CR 614.1a) and covers being countered — tested, not assumed.
`queue_from_hand` grew `from_zone` rather than a sibling entry point, so taxes,
timing gates, target validation and payment hold for a graveyard cast without a
second copy of any of them. A land played from exile still charges the land
drop (CR 305.1/305.2b); a free cast locks {X} at 0 (CR 107.3b) — which is why
the waiver auto-applies only to X-less spells, paying for X=5 usually beating a
free X=0.

**Four new sentences in the grammar**, all in the cards family: "exile the top
N cards of your library" (a producer — the exiled cards are recorded for the
next sentence to read); "[until end of turn,] you may play/cast <cards>" in its
four printed objects (`cards exiled this way`, `them`, `target … card from your
graveyard`, `spells from your hand without paying their mana costs`); the
two-zone any-number search ("search your graveyard and library for any number
of red instant and/or sorcery cards, exile them, then shuffle" — a different
effect from the one-card tutor, not a wording of it); and "Add six {R}", a
counted single pip. The back-reference discipline from "that much" applies
unchanged: a permission over "cards exiled this way" refuses to lower unless a
step of the same effect produced `exiled_cards`. The rider sentence folds onto
the permission node the way damage riders fold onto `DealDamage`. One nouns.py
fix fell out: "and/or" now separates a card-type union.

**The search is the sixth suspending prompt.** `search_exile_cards` — multi-
select across two zones, validated pick-by-pick with nothing moved on a
rejected answer, fail-to-find as an empty confirm (CR 701.23b). It suspends
because "You may cast them this turn." and "Add six {R}." read what the picks
decide; the API test pins that the mana arrives only after the answer. AI
default: take everything that matches — "any number" of cards that come back
castable leaves nothing on the table.

**Web:** `castable_from_zones` in the state payload, `from_zone` on the cast
action (riding `sendAction` the way the modal mode index already does, so
every cast path — targeted, X, auto-tap retry — carries it), a green glow on
castable zone cards, and the two-grid search modal. **Not driven in the
browser:** M21 is measured, not shipped, so no deck can hold a Chandra and the
Debug Menu can't inject one — the client work is exercised at the API layer
(`tests/ui/test_cast_from_zone_ui_api.py`) and becomes browser-reachable the
day the set ships.

**Next:** unchanged from round 17 — Rewind's untargeted "choose up to N on
resolution", the modal-mode sweep, then See the Truth, whose blocker
(`cast_from_zone`) this round built in passing.

---

## Round 20: the round-17 backlog cleared — Rewind, See the Truth, and the modal gate

*(2026-08-11, same day.)* M21 **149 → 151** by the count, five cards by what
actually changed: Rewind and See the Truth flipped, and the three
supported-but-lying modal cards (Read the Tides, Pestilent Haze, Destructive
Tampering) stopped lying. Every item was named by round 17's "Next" list, and
each turned out to be its own mechanism:

- **The `targeted` flag closes the round-15 finding.** "Up to two target
  creatures" and "up to four lands" both read as quantifier `up_to`, and the
  parser consumed the word "target" without recording it — so the AST could
  not say which family a clause belonged to. `TargetSpec.targeted` records it;
  `_describe_several_targets` now *refuses* an untargeted spec (a cast-time
  picker in front of a resolution-time choice), and Rewind's lowering demands
  the opposite. The two "up to N" families are separated by evidence now, not
  by which lowering happened to see the clause first.
- **Rewind** — "Untap up to four lands." is a pending choice
  (`untap_up_to`), armed on resolution, answered by stable permanent id,
  whole-answer validation (five picks against "up to four" moves nothing).
  Deliberately not suspending: the untap is its effect's last step.
- **See the Truth** — one three-sentence production, and the payoff for round
  19's field: the handler reads `cast_from_zone` off the resolution context,
  asks its `look_top_pick` choice only for a hand cast, and puts all three
  cards into the hand when the spell arrived from anywhere else — tested
  through a round-19 exile grant, the two subsystems meeting on one card. The
  pick suspends (the scry discipline: CR 608.2n's graveyard move waits).
- **The modal gate is all-of now.** `_modal_options`' per-mode support policy
  — "a card with one readable mode and one unreadable one still resolves the
  readable one" — was the Read the Tides bug as design; the compiler now
  refuses a card whose mode list has a dead entry, naming the mode. The three
  cards it would have refused were fixed in the same round: multi-target
  bounce for "their owners' hands" (the plural possessive is one lexer token;
  each creature still goes to its own owner, CR 400.3), a loyalty sweep for
  "remove two loyalty counters from each planeswalker" (CR 704.5i collects
  the emptied walkers), and the one-shot blanket "creatures without flying
  can't block this turn" — Game-level state read by `_can_block_attacker`
  with keywords asked of layer 6, so a creature granted flying after the
  spell resolves may still block, and one entering later may not.

Fallout worth the note: two ratchet tests existed to pin the *refusals* while
they were the honest state (`test_rewind_is_no_longer_reported_as_supported`,
the untargeted half of `test_several_targets_are_refused_rather_than_halved`).
Their purpose was fulfilled, not violated — both now pin the implementations
instead, and the targeted-several-tap refusal keeps its test.

**Next:** the "unsupported triggered ability" block (26 M21 cards) and the
"no handler implements this spell's effect" tail (22), which the support
report now names card by card.

---

## Round 21: bounce and burn — riders, unions, and one history

*(2026-08-11, same day.)* M21 **151 → 157**: Roaming Ghostlight, Barrin
Tolarian Archmage, Shipwreck Dowser, Scorching Dragonfire, Soul Sear, Life
Goes On — the first slice of the triggered-ability block and the no-handler
tail, chosen because they share machinery in pairs:

- **Type unions reach planeswalkers.** "Target creature or planeswalker" was
  already parsed for damage; the bounce and the graveyard return learned the
  same shape. The bounce lowering admits exactly two narrowings beyond the
  bare creature ("non-Spirit", "other … creature or planeswalker") and
  carries them as payload the handler *enforces* — resolved strictly, no
  fallback scan, because "up to one" legally names nothing and a decayed
  choice must bounce nothing rather than something else. `ObjectFilter`
  learned to emit `exclude_subtypes` and the shared matcher to test it, by
  `has_type` so a granted subtype excludes too.
- **Two rider spellings.** Disintegrate's "if it would die" grew the modern
  "if **that creature or planeswalker** would die this turn, exile it
  instead" (Scorching Dragonfire — the exile-if-dies machinery existed end to
  end; only the parser refused the spelling). And the pronoun grant rider
  ("It gains …") got its negative twin: "**That permanent loses**
  indestructible until end of turn" (Soul Sear) binds to the damage
  sentence's target — `_statement_bound_target` learned to look in
  `DealDamage.recipients` — and lowers onto `remove_keyword`, layer 6's
  removal, so it beats an older grant by timestamp and expires at cleanup.
- **One new history.** Barrin's end-step intervening-if reads "a permanent
  was put into your hand from the battlefield this turn" — a per-seat counter
  the bounce paths feed, reset with the other per-turn counters. Bouncing the
  *opponent's* walker does not satisfy it (CR 400.3: the card goes to its
  owner's hand), which the test pins because it is exactly the mistake a
  reader of the card would make. His trigger is also the first card through
  the resolution-side CR 603.4 payload gate round 16 left "armed for the
  first card that needs it" — and it exposed that `resolve_end_step`'s
  closed dispatch table never fired it: a new `END_STEP_INTERVENING_IF_KINDS`
  block evaluates the gate at fire time, scoped to the end step's own player.
- **Life Goes On** is a fold, not a sequence: "If a creature died this turn,
  you gain 8 life **instead**" replaces the sentence before it, so the rider
  parser rewrites the pair into one `Conditional` — parsed apart, the two
  sentences would stack to 12.

**Next:** unchanged — the remaining triggered-ability block (20 cards now),
led by the "you may … If you do, …" trigger family (Jeskai Elder, Crypt
Lurker, Dire Fleet Warmonger), and the rest of the no-handler tail.

---

## Round 22: the controller's discard, and tokens for the other side

*(2026-08-11, same day.)* M21 **157 → 160**: Jeskai Elder, Secure the Scene,
Angelic Ascension. A deliberately small round — two mechanisms, both of them
back-references the machinery already promised:

- **Jeskai Elder** is the first of the "you may … If you do, …" trigger
  family through, and it cost exactly one lowering plus one handler: a bare
  "discard a card" with the effect's own controller as the implied subject
  (`discard_controller_cards`, arming the same pending discard the targeted
  form uses). The `may` wrapper, the if-you-do branch and the prompt were all
  already there. **Left in the family**: Crypt Lurker's either/or action cost
  and Dire Fleet Warmonger's sacrifice-then-pump, both blocked on an ordering
  question — the then-branch must wait for an *action* cost's own pending
  choice, which is the suspends discipline applied to `may`, and worth its
  own round rather than a rushed corner of this one.
- **"Its controller creates a <token>."** (Secure the Scene, Angelic
  Ascension.) The exile handler has recorded `exiled_permanent_controller`
  since round 12 with a comment promising exactly this rider; the rider now
  exists, binds to the previous sentence's chosen target, and the token
  lowering demands the producer the same way "that much" demands its damage.
  Nothing exiled — the target left in response — means no controller was
  recorded and no token is created, which the handler states rather than
  guessing a seat. `CreateToken` grew a `recipient` field (append-only, so
  every earlier token payload is byte-identical), and the token production
  reads "creates" beside "create" so the grammar exists exactly once.

**Next:** the may-with-action-cost ordering question above; then the
remaining triggered-ability block and no-handler tail, where the support
report names every card.

---

## Round 23: the may-with-action-cost, answered by never offering the unpayable

*(2026-08-11, same day.)* M21 **160 → 162**: Dire Fleet Warmonger and Aven
Gagglemaster. The round-22 question — how does a "you may <action>. If you
do, …" trigger wait for its action cost's own pending choice — dissolved on
inspection into two smaller obligations, both already idioms:

- **"Sacrifice a creature" lowers onto the forced-sacrifice prompt**
  (`sacrifice_matching_permanent` → `arm_forced_sacrifice`), with "another"
  carried as the exclusion the prompt enforces and any narrowing the
  prompt's one-type-word candidate test cannot honour still refusing. The
  refusal test this retires said exactly what was missing ("needs the
  pending-choice machinery"); it now pins the lowering instead.
- **The `may` handler learned action-cost affordability**: with nothing
  legal to sacrifice, the offer is never made — the same rule it has always
  applied to mana — so the if-you-do pump can never be taken for free. That,
  plus the standing prompt gating every other action while the pick is owed,
  is what makes the accept-then-choose ordering safe without a new
  suspension: the pump lands before the chosen creature leaves, but nothing
  can observe the board in between.
- **Aven Gagglemaster** is the gains-life mirror of Liliana, Death Mage's
  loses-life multiplier: "for each creature you control with flying" rides
  ``GainLife.per_each``, counted over the gainer's own battlefield with
  keywords asked of layer 6 — a granted flying counts, and the
  Gagglemaster's own wings count it among its flock.

**Still in the family:** Crypt Lurker's either/or action cost ("sacrifice a
creature **or** discard a creature card"), which needs an or-composed cost
prompt, not just this round's single-action one.

---

## Round 24: two spellings and two destinations

*(2026-08-11, same day.)* M21 **162 → 165**: Falconer Adept, Epitaph Golem,
Unsubstantiate — chosen from a fresh census of the 123 remaining by first
failing clause, which also sized the big blocks this round did *not* touch:
the protection-quality family ("protection from multicolored", "from Demons
and from Dragons", "from the chosen color") keeps turning up across both the
keyword gate and the rider parser, and stays deliberately refused until the
shield machinery models non-colour qualities.

- **Falconer Adept** cost exactly one spelling: Basri Ket's tokens are "that
  **are** tapped and attacking", the Adept's single Bird is "that**'s**" —
  the entry-state machinery from the walker round did the rest.
- **Epitaph Golem** is `PutOnLibraryTop`'s mirror: "put target card from
  your graveyard on the bottom of your library", scoped exactly to the
  caster's own graveyard and own library, everything else refusing.
- **Unsubstantiate** is a union across *zones* no object filter expresses —
  "target spell or creature" — so the template is read whole and the node
  carries the stack half as a flag. A chosen spell is unstacked to its
  owner's hand: not countered, so nothing is binned, no counter hooks fire,
  and the test pins that the returned Shock never resolved and can be recast.
  The creature half is the ordinary bounce. The picker is the Lace cycle's
  spell-or-permanent one, narrowed to creatures on the battlefield half by a
  new `permanent_kind` flag.

**Next:** the protection-quality family is now the single biggest named
block; otherwise the remaining triggered-ability and no-handler groups, card
by card in the support report.

---

## Round 25: protection grows past colour

*(2026-08-11, same day.)* M21 **165 → 166** by the count — Baneslayer Angel
alone — and the number undersells the round the way round 3's single counter
card did: the deliverable is the *quality subsystem* the census named as the
biggest block. `_protection_colors` is now the colour slice of
`_protection_qualities`, whose vocabulary is exactly what the shield
machinery can test: colours, "multicolored" (the effective-colour count),
"planeswalkers" (a card type), and creature subtypes ("Demons and from
Dragons"), pluralized in print and singular in the catalog. The two askers —
`_is_protected_from` for blocking and combat damage, `_can_be_targeted` for
targeting — take a quality's answer from the layer system (`has_type`,
effective colours), so a granted subtype shields exactly as a printed one.
The keyword gate widened in step: what may be admitted and what the shield
tests are one vocabulary, and hexproof deliberately stays colour-only
because its targeting branch reads colour words alone.

**Flipped by the subsystem but still gated on other lines, honestly:**
Basri's Lieutenant (a death trigger with an intervening clause), Sparkhunter
Masticore (an additional discard cost), Pack Leader (a prevention trigger).
Their protection lines stopped being the blocker; the census names what
remains. **Left named:** Feat of Resistance's "protection from the color of
your choice" (a chosen-colour grant riding the cast's colour channel plus a
layer-6 read `_protection_qualities` does not do yet), Runed Halo (player
protection from a chosen *name*), and Feline Sovereign (protection as a
lord-buff grant).

---

## Round 26: six widenings, and counters become countable

*(2026-08-11, same day.)* M21 **166 → 173**: Bad Deal, Liliana's Steward,
Kaervek the Spiteful, Azusa Lost but Seeking, Chandra's Magmutt, Miscast,
Tempered Veteran. Seven cards from six independent widenings, each a small
entry in machinery that already existed — chosen from a fresh line-by-line
probe (`compile_line` names the exact refusal, which beats reading the
aggregate report buckets):

- **Discard recipients.** The discard lowering learned `each_opponent` (one
  pending discard choice per opponent — Bad Deal) and `target_opponent`
  (Liliana's Steward, whose sacrifice cost and sorcery-speed gate already
  worked). Lose-life learned `each_player` (CR 800.4a excludes a departed
  seat). The `opponents_only` picker flag turned out to be **dropped** by
  `_from_targets_payload` for every player-kind target — the phase-out sweep
  had been writing it into payloads targeting.py then discarded — so the fix
  serves Teferi, Timeless Voyager's −8 as well as the Steward.
- **Negative lord buffs.** Kaervek's "Other creatures get -1/-1." was USABLE
  in the grammar and refused by `lord_buff_for` — the two front ends of one
  table disagreeing on a sign. `_PT_RE` reads `[+-]` now; the consumer's
  arithmetic and the 704.5f death were already correct.
- **The creature static gate asks the land-play table.** Azusa was Fastbond's
  exact template on a creature: enforced correctly by
  `_land_play_allowances` (which scans every controlled permanent), reported
  unsupported because `_is_supported_static_creature_line` never consulted
  the table `_derived_static_claims` has asked since it was written. Only the
  permission clause claims; a rider-only line still refuses.
- **"Target player or planeswalker"** (Chandra's Magmutt) — a new
  `player_or_planeswalker` target kind: player faces plus planeswalker
  permanents, the "any target" resolution shape minus the creature half.
  Parsed only in the damage-recipient position, so no other lowering can
  receive the flag and silently narrow it.
- **The counter filter grows types and a fixed price** (Miscast). "Target
  instant or sorcery **spell**" records the head noun as zone="stack" (the
  bare types would read as battlefield permanents — the dropped-rider class);
  the counter lowering, handler, and stack picker all honour the union, and
  the "unless its controller pays {3}" fixed cost arms the same pending
  payment Power Sink's X does. Coloured pips still refuse.
- **Counters became state** (Tempered Veteran). "With a +1/+1 counter on it"
  is a question about *counters*, and the engine could not answer it: every
  +1/+1 counter was a bare P/T bonus, `metadata["plus_counters"]` written by
  **nothing** — so the 704.5q plus/minus cancellation sweep was unreachable
  from real play and the web card face showed no counter for a counter the
  engine had placed. `pt.add_plus1_counters` now records both channels at
  every placing site (the three handlers, Khabál Ghoul's, Rock Hydra's
  enters-with-X), and the filter reads the record — a Giant Growth writes
  power_bonus too, which is exactly why the bonus could never be the answer.

**Found red on HEAD, fixed in passing:** three LEA counterspell tests
(`Blue/Red Elemental Blast`, `Spell Blast`) asserted the log line round 19's
`_bin_spell_card` refactor reworded, and had been failing since that commit —
the round-19 "suite green" predates its final wording. The behaviour
(countered, binned, never resolved) was intact; the assertions now read the
one bin-line verb.

**Written down, not acted on:** Rock Hydra's "for each 1 damage … remove a
+1/+1 counter from it and prevent that 1 damage" is acknowledged in
`IMPLEMENTED_ELSEWHERE` as "prevention.py (Rock Hydra's +1/+1 counter
shield)" — but that file only implements his *activated* {R} shield; nothing
reads counters in any damage path, so the automatic shield is the Nine Lives
class (supported, partially implemented) hiding behind a
verified-sounding acknowledgement. The counter record this round added is
the prerequisite for fixing it honestly.

Two ratchet tests pinned refusals this round implemented (the fixed
unless-pays cost, the negative lord buff); both now pin the implementations,
and the coloured-pip refusal keeps a test. Suite 4,796 at 18.9s, every
`--check` green, shipped pool untouched at 388/388, zero hooks, zero ceiling
raises.

**Next:** modal triggered abilities (Trufflesnout and Elder Gargaroth — every
bullet already USABLE, only the trigger-head assembly missing), then the
census's remaining named blocks: the drawn-two-cards-this-turn tracker family
(Gnarled Sage, Tome Anima, Jolrael, Mystic Skyfish), cast-trigger type
narrowings (Spellgorger Weird), and the intervening-if object filter
(Turret Ogre, Furious Rise).

---

## Round 27: a trigger learns to offer a choice

*(2026-08-11, same day.)* M21 **173 → 175**: Trufflesnout and Elder Gargaroth
— the modal triggered abilities round 26's census named first. The pieces were
already waiting, and the seam even said so: `_modal_options`' docstring noted
that a modal *trigger* "reaches here and is not claimed, because its head
parses as a `TriggeredAbilityNode`". This round claims it:

- **Grouping is the compiler's job, reading is the grammar's** — the same
  split the modal-spell path established. `_modal_trigger_ability` reads the
  head through `_modal_head(…, TriggeredAbilityNode)`, the condition through
  the ordinary trigger parser, each bullet through `_line_instruction`, and
  assembles one `choose_one` instruction carrying every mode. One
  instruction, not one trigger per bullet — a triggered ability triggers
  *once*, and the expansion trick modal activated abilities use would fire
  them all. The classifier's line loop consumes head plus bullets together,
  so a bullet never reaches the per-line steps as an orphaned fragment.
- **The choice is a pending prompt, the `may` shape.** `choose_one` arms a
  `mode_choice` carrying the mode instructions and the resolution context;
  the resolver runs the picked one. `default_at_arm`: a non-interactive seat
  takes the first printed mode the moment it is armed (a stated policy, like
  the up-to-N maximum — a card whose AI should pick otherwise needs a
  valuation, not a special case), so the headless simulator needed nothing.
  CR 700.2b would choose the mode as the ability goes on the stack; asking at
  resolution is the same standing approximation the engine already makes for
  an ETB trigger's target, and the prompt blocks the owing seat meanwhile.
- **The all-of gate from round 20 applies here too**: a recognized head with
  an unreadable condition or a dead bullet refuses the whole card naming the
  clause — a mode list with a dead entry is a card that offers a choice and
  then declines to perform it. A *targeted* mode also refuses (nothing
  collects a target after the mode is picked), and "choose one or more"
  stays refused by the head's own lowering, exactly as for spells.
- **`creature_attacks_or_blocks` had a parse and no dispatch** — both trigger
  tables knew the words; no combat step fired them. The two per-creature
  sites (`_fire_creature_attacks_triggers`, `_fire_creature_blocks_triggers`)
  take a condition-kind set, so the union condition is one entry in each, and
  the per-set test drives both halves: Gargaroth's Beast arrives on attack
  and on block.
- **Web:** one renderer, one `ActionKind` (`mode_choice_confirm`, answered by
  index), the registration's prompt riding the three generic loops — covered
  by construction, per the pending-choices design.

Suite 4,803 at 19.8s, every `--check` green, shipped pool 388/388, zero
hooks, zero ceiling raises.

**Next:** the census's remaining named blocks — the drawn-two-cards-this-turn
tracker family (Gnarled Sage, Tome Anima, Jolrael, Mystic Skyfish),
cast-trigger type narrowings (Spellgorger Weird), and the intervening-if
object filter (Turret Ogre) — plus the counters-as-state families the
round-26 record unlocked (Basri's Lieutenant, Pridemalkin, Sigiled
Contender).

---

## Round 28: three narrowings, three mechanisms

*(2026-08-11, same day.)* M21 **175 → 178**: Spellgorger Weird, Turret Ogre,
Mystic Skyfish — the three census blocks round 27 queued, each its own
mechanism:

- **Cast triggers narrow by type** (Spellgorger Weird). Round 7's shape
  exactly: the narrowed pattern lands on *both* sides of the pipeline
  (oracle regex table and grammar parser), specific-before-prefix, with the
  type word as condition payload the `you_cast_spell` event filter tests
  against the cast card's type line. The word list is closed to what the
  filter can test — a subtype ("Dog spell", Rin and Seri) keeps refusing
  rather than compiling a trigger that fires on every spell. "Enchantment"
  stays its own condition kind; the article split ("a"/"an") keeps the two
  from colliding.
- **An intervening-if can carry an object filter** (Turret Ogre). "If you
  control another creature with power 4 or greater" needed four small
  pieces, each closing a silent-drop hole: the condition parse accepts
  "another" (CR 109.5's exclusion, contracted into an article);
  `ObjectFilter.to_payload` emits **power and toughness bounds** (both,
  because emitting one and dropping the other would let a toughness
  restriction vanish — the same rule mana_value already followed);
  `permanent_matches_filter` tests them against the layer-computed stats (a
  pumped 1/3 counts while pumped, tested); and the `controls` condition
  honours `exclude_self`, without which an invented power-4 creature with
  Turret Ogre's text would count itself. The ETB trigger path also gained
  the CR 603.4 gate the stack path got in round 16 — it executes inline and
  never passed through that read, so the Ogre would have pinged with no big
  creature in play.
- **"Whenever you draw your second card each turn"** (Mystic Skyfish).
  The record already existed — `cards_drawn_this_turn`, per seat, fed by
  every draw path since Jandor's Ring needed "the last card you drew" — so
  the round added only the announcement: a sweep in
  `check_state_based_actions` with a once-per-turn flag, firing
  `draws_second_card` through the event bus with a controller-scoped
  filter. The sweep site is deliberate: there is no one draw seam (a dozen
  paths append to the record, three of them calling `player.draw` around
  `_draw_with_replacements` despite its "only way to draw" docstring), and
  a site every action already passes through cannot be forgotten by the
  next draw path — the trigger still enqueues before any player next gets
  priority, which is when a trigger is noticed anyway (CR 603.3b). Jolrael's
  trigger reads through the same condition; she stays honestly gated on her
  X/X-setting ability.

Consolidating the draw paths onto `_draw_with_replacements` is written down
as owed — the direct `player.draw` calls in the zones handlers skip any
armed draw replacement today, which is its docstring's own warning.

Suite 4,810 at 19.6s, every `--check` green, shipped pool 388/388, zero
hooks, zero ceiling raises.

**Next:** the conditional-static family ("as long as" P/T, keyword and
evasion grants: Gnarled Sage, Tome Anima, Sigiled Contender, Radha,
Predatory Wurm — five cards on one mechanism), then the counter-state
death trigger (Basri's Lieutenant) and Pridemalkin's counter-filtered
trample grant.

---

## Round 29: "as long as" becomes one table

*(2026-08-12.)* M21 **178 → 182**: Predatory Wurm, Gnarled Sage, Sigiled
Contender, Tome Anima. The conditional-static family, generalized rather than
extended: `static_bonuses.py`'s two legacy kinds baked the condition into the
instruction kind — one dispatch branch per condition per effect class, which
is multiplicative — so everything new rides one `conditional_static` kind
whose condition *and* effect are payload. Three conditions (drawn-N-this-turn
off the round-28 record, controls-a-`<subtype>`-planeswalker through
`has_type`, has-a-+1/+1-counter off the round-26 record) crossed with three
effect classes, and the crossing is free: Gnarled Sage's "+0/+2 and has
vigilance" is one entry, not a fourth kind.

**Who consumes which half is split by layer, and the split is the design:**

- The **P/T delta** joins the legacy kinds' derived 7c channel in
  `_refresh_dynamic_creatures` — recompute-written, like
  `conditional_land_bonus` always was.
- The **keyword grants** are written by `_recalculate_lord_buffs`, and only
  by it, because that pass owns the derived-grant channel's clear/rebuild —
  a grant written from any other pass would be wiped whenever the lord pass
  runs alone, which it does from six call sites.
- **"Can't be blocked"** is asked at block-legality time (and by the UI's
  `is_unblockable` tag), never materialized: the condition can change
  between recomputes, and the blocking check is the read that matters.

Keywords are gated on `IMPLEMENTED_KEYWORDS` at derivation — a conditional
grant of a word without behaviour is a grant of nothing, so the line refuses
instead (the lord-buff table's own rule). Radha stays gated honestly: her
conditional first strike would derive, but her top-of-library line and
where-clause pump do not, and her self-noun normalizes to her name rather
than "this creature" — a sixth condition wording for a card two other lines
keep unsupported anyway.

Suite 4,818 at 23.3s, every `--check` green, shipped pool 388/388, zero
hooks, zero ceiling raises.

**Next:** Basri's Lieutenant's counter-state death trigger ("if it had a
+1/+1 counter on it" — last-known information over the round-26 record),
Pridemalkin's counter-filtered trample grant (a lord-buff subject
qualifier), and the remaining no-handler tail the support report names.

---

## Standing invariants

Anything that weakens these is a regression regardless of what it enables:

1. **No silent wrongness.** A card may fail loudly as unsupported with a
   reason; it may never resolve as something other than what it says.
2. **The suite stays fast.** 4,454 tests at a steady 23s, against a CI budget of
   35s. The budget catches a step change; the *baseline* recorded beside it in
   `ci.yml` is what catches creep, and it is the number to keep honest — it
   went 9s → 17s across four phases with the gate green the whole way. Raising
   the budget is a decision, not maintenance.

   The baseline moved 17 → 23 in this session, and that is a *record* of growth
   rather than permission for it: ~130 tests were added (permanent ids, the
   grammar layering guards, two renumbering regression suites) and 17 stopped
   being true. Leaving it would have parked the warning threshold
   (`BASELINE × 1.5` = 25.5s) two and a half seconds away, so the next
   unrelated change would have been blamed for drift this one caused. The
   budget is untouched.

   **The variance recorded here earlier did not reproduce.** Two back-to-back
   local runs once measured 43.98s and 16.79s, which read as a runner-weather
   problem serious enough to question the mechanism; three consecutive runs
   later landed on 23s exactly. Treat one slow run as noise. The distinction
   still matters — "the budget is too tight" and "this box is noisy" have the
   same symptom and opposite fixes — but there is currently no evidence for
   either.
3. **Determinism.** A given seed reproduces a run exactly. Parsing and lowering
   are pure functions of card text.
4. **Ratchets only tighten.** Coverage floors, probe baselines, and accepted-diff
   lists shrink or hold — never grow without review. "Tighten" is the
   invariant, not "shrink": `hook_reliance_ratchet.json` holds *ceilings*, so
   tightening moves it down while `grammar_ratchet.json` tightens by moving up.
   The pair is deliberate — one guards the general reader keeping ground, the
   other guards the special-case readers not taking any — and a ceiling needs
   its measurement asserted, because unlike a floor it passes when it breaks.
5. **No card name decides behaviour outside `card_hooks.py`** — anywhere under
   `engine/`, heuristics and AI code included. The rule is about *dispatch*, not
   mention: a name in a log line, a prompt label or a fixture decklist is data;
   a name in an `if` is a claim, and `tests/engine/test_card_name_reads.py`
   enforces exactly that shape. "Only one card does this" is a claim about the
   *pool*, and it expires without anyone editing the comment — so before a name
   goes anywhere else, give an invented card the same printed text and check
   that it behaves. A name-keyed dispatch and a CR rule written as a card
   special case grep identically and have opposite fixes.

   Two things this covers that the earlier wording did not, both found by
   writing the guard rather than by reading the rule. **Heuristics are in
   scope.** A weight is tuning and stays tuning, but *which cards a weight
   reaches* is a claim about the pool and decays exactly like a parse rule —
   `ai_policy` named eight cards and aimed four unnamed removal spells at its own
   board. Derive the reach (`engine/ai_valuation.py`) and keep the weight.
   **Test oracles are out of scope, with their reason measured.**
   `ai_simulator._assert_expected` asserts a card did what the *printed* card
   says; deriving that from the compiled program makes it a tautology, and the
   only exemptions that stay are ones where the tautology has actually been
   demonstrated. An acknowledgement carries the measurement, not an opinion.
