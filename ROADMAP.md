# Scaling Roadmap

Target: grow the card pool from 388 unique cards (LEA/LEB/2ED/ARN/3ED shipped,
M21 measured at 110/285) to the full release line - **137 sets, 33,594
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
