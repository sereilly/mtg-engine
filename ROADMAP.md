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

**Next per the census:** the rest of the search-library template family
(graveyard and by-name variants, the search-flow filter widening); the
trigger-condition narrowings — respecting the unanchored-regex landmine
recorded above — and the sacrifice/discard activation costs (Selfless
Savior, Seasoned Hallowblade); then the subsystem blocks (planeswalkers,
scry, exile-until-leaves, per-turn trackers).

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
