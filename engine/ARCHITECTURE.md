# Engine Architecture

The engine is built so that card support grows by **adding registry entries**,
never by editing core control flow. Every extension point is a small function
in a category module; dispatch is data-driven.

## Pipeline

```
cards/manifest.json → the set JSONs it registers (card_loader.manifest_set_paths)
   │  card_loader.load_cards
   ▼
CardDefinition (immutable)
   │  oracle.compile_card_oracle        ← cached: each card compiles once per process
   │    ├─ engine/grammar/   per line: tokenize → AST → lower   (used when gated on)
   │    └─ engine/parsing/   legacy @parse_rule registry        (fallback)
   ▼
OracleProgram
   ├─ instructions          (primary effects, e.g. deal_damage)
   ├─ activated_abilities   (cost + instruction)
   ├─ triggered_abilities   (TriggerCondition + instruction)
   └─ static_lines          (keywords, static buffs)
   │  Game mixins (stack/casting → oracle_instructions)
   ▼
EFFECT_HANDLERS[instruction.kind](game, instruction, context)   ← O(1) dict dispatch
```

**Two front ends, one IR.** `engine/grammar/` is progressively replacing
`engine/parsing/`; both lower to the same `OracleInstruction`, so they are
directly comparable and can coexist per line. See "Grammar front end" below and
`ROADMAP.md` for the migration plan.

## Packages

| Package / module | Role |
| --- | --- |
| `engine/oracle_types.py` | Shared dataclasses (`OracleInstruction`, `OracleProgram`, …) and text helpers. No engine imports — safe to import from anywhere. |
| `engine/events.py` | Trigger event bus: `emit(game, kind, **payload)` announces something that happened and enqueues every matching triggered ability in APNAP order. `@event_filter(kind)` registers per-kind applicability predicates ("…casts a *blue* spell"). Prefer this over adding another hand-placed `iter_triggered_abilities` scan. |
| `engine/continuous.py` | The CR 613 layer system: layers, sublayers, timestamps, and dependency. Pure — it computes characteristics from effects and never touches game state, so it is tested directly against the rule text. |
| `engine/layer_bridge.py` | Adapter from the engine's stored channels to `ContinuousEffect`s (layers 6 and 7 today). The seam that lets storage change without touching the rules logic. |
| `engine/keywords.py` | Single write API for keyword abilities (layer 6): `grant_keyword` / `remove_keyword`, recorded in order with timestamps. Never set a `gains_<keyword>` flag by hand — grants and removals share a layer, so only the recorded order can decide which wins. |
| `engine/grammar/` | Grammar front end: tokenizer → recursive-descent parser → typed AST → lowering to `OracleInstruction`. Progressively replacing `engine/parsing/`; see "Grammar front end" below. Imports only `oracle_types`. |
| `engine/parsing/` | Declarative parse rules. Each `@parse_rule(order)` function maps a normalized oracle-text clause to `(OracleInstruction, effect_kind)`. First match in ascending order wins. `engine/parsing/common.py` hosts helpers shared across rules (number words, color-word scans, duration parsing, `parse_target_filter` for "target <noun phrase>" restrictions) — check there before adding a new one-off regex. |
| `engine/oracle.py` | The compiler: tokenizes oracle text, classifies lines (keyword / triggered / activated / static), delegates effect clauses to `engine.parsing`, and caches one `OracleProgram` per card. |
| `engine/handlers/` | Effect executors. Each `@effect_handler(kind)` function mutates game state for one instruction kind. Registered into `EFFECT_HANDLERS` and dispatched with a single dict lookup. `engine/handlers/_common.py` hosts shared helpers (`resolve_target_permanent`/`pick_target_permanent`, `permanent_matches_filter`, damage application). |
| `engine/pt.py` | The single write API for power/toughness channels (`set_base_pt`, `add_pt_modifier`, `switch_pt`, `clear_base_pt`) — see "P/T channels" below. All P/T mutation should go through here, never direct metadata pokes. |
| `engine/replacements.py` | CR 614 replacement-effect registry (`life_gain`, `damage_to_creature`, `would_die`, …). An interceptor may consume an event or adjust its amount before the default action runs; see "Replacement effects" below. |
| `engine/prevention.py` | CR 615 damage-shield registry. Each `@prevention_effect(order, applies=…)` function reports how many points it removes from one damage event, over players and permanents alike. See "Prevention effects" below. |
| `engine/effect_ordering.py` | CR 616.1: gather every applicable replacement and prevention effect, choose one, apply it, re-ask the rest. Both registries run through it, which is why each registration carries a pure `applies` predicate. See "Effect ordering" below. |
| `engine/damage_events.py` | A damage event start to finish: CR 120.4's two halves (damage dealt, then its result), with CR 616.1's contention set — shields *and* replacements together — inside each. `deal_damage(game, event)` is what every damage path calls, and there is no half-event alternative. |
| `engine/tokens.py` | `make_token_card(...)` — the one place that builds a token's `CardDefinition`. A token-creating card is a parse rule emitting a generic `create_token` instruction, never a bespoke handler. |
| `engine/cast_restrictions.py` | Text-keyed "Cast this spell only during..." timing gates — an ordered predicate table, since the restriction is the same for any card printed with that phrase (not name-specific). |
| `engine/targeting.py` | Cast-time target kind derived from the compiled program — an Aura's `Enchant <subject>` line or an instruction's `type_filter`. The strangler seam replacing `legality.py`'s text cascade: it answers where the program carries evidence, `legality.py` answers otherwise, and a differential guard keeps them equal. |
| `Game.become_tapped(permanent)` | The single untapped→tapped transition (CR 701.26a). It announces `permanent_becomes_tapped` on the event bus, so a "whenever a `<type>` [an opponent controls] becomes tapped" card is dispatched by its own compiled condition and goes on the stack (CR 605.5a — it is not a mana ability). Never set `perm.tapped = True` directly — a trigger registered on one tapping path silently misses every other, which is exactly how Lifetap came to ignore Icy Manipulator. Entering the battlefield tapped is *not* becoming tapped and deliberately bypasses it. |
| `engine/cost_modifiers.py` | Text-keyed cost increases (CR 601.2f) — "<colour> spells cost {N} more to cast" and the activated-ability form. Applied once per taxing permanent on any battlefield. Increases only; reduction is deliberately absent until a card needs it. |
| `engine/untap_restrictions.py` | Text-keyed untap-step restrictions (CR 502): skip the step, per-type untap limits, power- and color-gated blocks, and the "as long as this is untapped" qualifier that composes with any of them. Derived from oracle text, so a card printed with a known template needs no registration. |
| `engine/auras.py` | What an Aura's effect lines say and whether the engine implements them. Two jobs: the **support gate** requires every effect line of an Aura to be claimed here, so an Aura whose effect is unimplemented is reported unsupported instead of entering play and doing nothing; and the **derivations** an Aura's continuous effects are read from while it is attached (static P/T, keyword grants, combat/untap restrictions, protection colours, artifact animation). Removal is the Aura ceasing to be attached — there is no remembered delta to subtract. `attach_aura`/`detach_aura` keep `attached_to` and `attached_auras` in step; `attached_aura` is a single slot a second Aura overwrites, so the list is the authority. |
| `engine/characteristic_defining.py` | Characteristic-defining power/toughness (CR 604.3) — "<name>'s power and toughness are each equal to the number of X". The possessive subject is the card's own name, which normalization does not replace, so these were four literals containing four card names. One `dynamic_pt_count` instruction now carries what to count (`land`/`creature`/`same_name`) and whose battlefield to count it on. |
| `engine/static_bonuses.py` | Conditional static P/T bonuses (CR 613 layer 7c) — "gets +N/+N as long as you control a <land>", "as long as it's untapped". Both printed word orders, because only the trailing one was ever dispatched while the leading one sat in the support gate as a literal naming Swamp. Also `singular_land_type`, since Plains is spelled the same singular and plural. |
| `engine/lord_buffs.py` | The lord/anthem template (CR 611.3a, layers 6 and 7c) — "Other Goblins get +1/+1 and have mountainwalk", "Black creatures get +1/+1", "Attacking creatures you control get +1/+0". Derives **who** (colour, creature subtype, "other", controller scope, and a state qualifier: attacking/blocking/tapped/untapped) and **what** (P/T delta, keyword abilities, a granted activated ability). The support gate, both parser front ends and `_recalculate_lord_buffs` all read this one table. A clause carrying a **duration** is deliberately not claimed: that is the spell reading of the same sentence, which locks its set in at resolution (CR 611.2c) and stays on `buff_creatures_global`. |
| `engine/combat_restrictions.py` | Text-keyed combat restrictions (CR 506, 509): "can't attack unless defending player controls a <land type>", "attacks each combat if able", "can't be blocked by Walls", "can't block creatures with power N or greater". The land type and the threshold are payload data, not part of the instruction kind. The support gate consults this table rather than listing the same sentences, so a rider the table does not recognize fails loudly instead of compiling to a bare static line. |
| `engine/enter_effects.py` | Entry-state phrases `_initialize_permanent_state` carries out (enters tapped, enters with counters, enter-as-a-copy, choose-on-enter, no maximum hand size, spend white as red). `enter_effect_line` is the whole-line matcher; the compiler's support gate and `engine/grammar/registries.py` both read it, so the phrases cannot drift between what is implemented and what is claimed. |
| `engine/draw_step_modifiers.py` | Text-keyed symmetric bonus draws (CR 504): "at the beginning of each player's draw step, that player draws an additional card", with the optional untapped-source clause. |
| `engine/land_animation.py` | Text-keyed land animation (CR 613 layers 4/5/7): "All &lt;land type&gt;s are P/T \[colour] creatures that are still lands". The land type, the P/T and the colour are all payload on one `animate_all_lands` instruction, so a third animator needs no code. Replaced two parse rules that baked the land type into the instruction *kind* and a refresh that matched `card.name == "Kormus Bell"` — the two halves failing in opposite directions at once. |
| `engine/land_play_allowance.py` | Text-keyed extra land plays (CR 305.2): "You may play any number of lands on each of your turns", the "\[N] additional land(s)" forms, and the self-damage rider that may accompany them. Every land-drop gate — cast validation, the AI's land policy, the web layer's playable list — and the support gate all ask this one table, so they cannot disagree about what a card grants. |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior: spell-resolved triggers, counterspell riders, leave-battlefield effects, draw-step modifiers, the Aura on a land tapped for mana. The only sanctioned place in the engine to reference a card by name; there are no `# TODO(card-hooks)` exceptions left outside it. |
| `engine/phases/` | One mixin per turn phase and per step within a phase (CR 500–514): `beginning_phase` + `untap_step`/`upkeep_step`/`draw_step`, `precombat_main_phase`, `combat_phase` + its five step modules, `postcombat_main_phase`, `ending_phase` + `end_step`/`cleanup_step`. Each is composed onto `Game`. See `engine/phases/__init__.py` for the full taxonomy. |
| `engine/mixins/` | Cross-cutting game flow not tied to a single phase: turn-structure navigation and priority (`phase_steps`), per-turn/pregame management (`turn_management`), state-based actions, effects, helpers. Consumes compiled programs; should never parse oracle text itself. |
| `engine/mixins/stack/` | The stack (CR 405), one mixin per stage of an object's life on it: `casting` (CR 601), `activation` (CR 602), `resolution` (CR 603/608), and `choices` — the `pending_choices` queue every part-way-through decision uses, plus the table registering them. |

## Adding support for a new card

Work top-down; stop at the first step that covers the card.

1. **Already covered?** If the card's oracle text matches existing parse rules
   (run `compile_card_oracle(card)` and check `supported`), nothing to do.
   `python scripts/support_report.py` reports coverage for the whole manifest
   pool and `--set <CODE>` for one set, and the "creature text too complex"
   reason now names the specific unrecognized line.
2. **New text pattern, existing effect.** Add one `@parse_rule` to the matching
   category module in `engine/parsing/` that returns an existing instruction
   kind. Reuse `engine/parsing/common.py` helpers (number words, color words,
   durations, target-noun-phrase filters) instead of re-deriving them. Pick an
   `order` using the `BAND_*` constants in `engine/parsing/base.py` — more
   specific patterns must use lower orders than generic ones (e.g. `"destroy
   all creatures"` runs before `"destroy target"`).
3. **New effect.** Invent a new instruction kind (verb_object naming, e.g.
   `exile_target_creature_until_eot`), add the parse rule, then add one
   `@effect_handler` function in the matching `engine/handlers/` module.
   Creating tokens: emit `create_token` (payload: name/power/toughness/
   type_line/colors/keywords/count) — never write a bespoke token handler.
   Setting/modifying power or toughness: go through `engine/pt.py`, never
   metadata directly. "If X would happen, Y instead": register an interceptor
   in `engine/replacements.py` instead of an inline metadata check.
4. **Card-specific behavior.** If the behavior can't be expressed generically,
   register a hook in `engine/card_hooks.py` keyed by card name (or, for a
   genuinely textual timing restriction, an entry in
   `engine/cast_restrictions.py`). Don't put card names anywhere else in the
   engine.
5. **Tests.** Add a focused test per new rule/handler (see
   `tests/sets/test_lea_cards.py` for per-card patterns). The comprehensive-cast
   sweep (`test_every_catalog_card_resolves_without_exception`) is driven by
   `pytest_generate_tests` over the whole `cards/manifest.json` catalog, so a
   new set is swept the moment it is ingested. Only add to that file's
   `SWEEP_EXCLUSIONS` if a card needs setup the generic body can't provide.

## Grammar front end

`engine/grammar/` parses an oracle line into a typed AST and lowers it to the
same `OracleInstruction` IR the parse rules emit. Modules:

| Module | Role |
| --- | --- |
| `lexer.py` | Tokenizer. Keeps P/T as one token, preserves source spans for error offsets, strips reminder text (recording it), and collapses a card's self-references to a single `SELF` token so productions never need card names. |
| `vocabulary.py` | Creature/land/artifact types, supertypes, and keywords loaded from `data/vocabulary/` (fetched by `scripts/fetch_vocabulary.py`). Never touches the network at import. |
| `ast.py` | Frozen dataclass node inventory. Imports nothing from the engine. **Append-only** — repurposing a field invalidates every golden and ratchet entry at once. |
| `amounts.py` / `nouns.py` | Quantity and object-phrase sub-parsers (`Fixed`/`Var`/`CountOf`/`ThatMuch`, `ObjectFilter`/`TargetSpec`/`PlayerRef`). |
| `parser.py` | Line classification (keyword / activated / triggered / static / spell) and the recursive-descent statement grammar. |
| `lower.py` | AST → instructions, emitting the payload keys the existing handlers already read. |

Two properties define how it behaves:

- **Full token consumption.** A production must account for every token of its
  line; leftovers raise `GrammarError`. So "parsed" means "understood in full",
  and a gap fails loudly (unsupported, with the clause named) rather than
  resolving as something the card doesn't say. This is the structural fix for
  the dropped-rider class that `scripts/parse_coverage.py`'s deletion probe
  detects empirically.
- **Category gating.** The grammar runs on every line, but its output is only
  *used* when every category it lowered to is in
  `engine.grammar.GRAMMAR_CATEGORIES`; otherwise the legacy rules handle the
  line unchanged. Enabling a category is a one-line change made after
  `tests/engine/test_grammar_differential.py` is green for it.

Composition lives in the IR: `sequence`, `if_then`, `may`, and `for_each`
(`engine/handlers/control_flow.py`) nest instruction tuples in their payloads,
and `OracleExecutionContext.results` carries values between steps of one
resolution ("deals X damage… you gain that much life"). That is what removes the
need for fused kinds like `deal_damage_and_gain_life` — 28 of the legacy
compiler's 120 kinds were conjunctions of this sort.

Coverage is tracked in `GRAMMAR_COVERAGE.md` with floors in
`scripts/grammar_ratchet.json`, guarded by `tests/engine/test_grammar_ratchet.py`.

## Destruction is a state-based action

Lethal damage (CR 704.5g) and deathtouch damage (704.5h) destroy creatures in
`check_state_based_actions` and nowhere else. Effect handlers mark damage and
stop — they do not sweep for deaths, and nothing else should either.

This used to be the opposite: destruction happened only when an effect called
`_destroy_marked_creatures()` by hand, at nine separate sites. Any new damage
effect that forgot left a lethally damaged creature alive, and composed effects
made that easy to hit, since a damage step no longer necessarily sits inside a
handler that knows to run the sweep. If a new code path needs deaths applied
before it continues, call `check_state_based_actions()` — that is CR 704.3, and
it is what the phase steps do before handing out priority.

## Continuous effects — the CR 613 layer system

`engine/continuous.py` implements the layer system: effects are placed in
layers 1–7, layer 7 is split into sublayers 7a–7d, and within a layer or
sublayer effects apply in **timestamp** order — except where **dependency**
(CR 613.8) overrides it. Dependency is detected generally, by asking what an
effect *would* do before and after applying another, rather than by enumerating
known card interactions; dependency loops fall back to timestamp order as
613.8b requires, and the order is re-evaluated after every application (613.8c).

Two consequences for anyone adding an effect:

- **`modify` and `applies_to` must be pure.** Both are applied speculatively to
  throwaway state while probing dependency, so they may run many times per
  recompute. A side effect outside the `Characteristics` passed in will fire
  spuriously.
- **Ordering is a rule, not a coding convention.** Put an effect in its layer
  and give it a timestamp; do not try to sequence it by where the code runs.

`engine/layer_bridge.py` adapts the engine's stored channels into effects and is
what `Permanent.effective_power`/`effective_toughness` and
`Permanent.has_keyword` call. Keeping the adapter separate keeps the layer
engine pure and testable directly against the rule text
(`tests/rules/test_layers.py`), while the storage it reads from can move without
the rules logic changing.

**Layers 4–7 are live.** The accessors that read them:

| Accessor | Layer |
| --- | --- |
| `Permanent.is_creature`, `Permanent.has_type` | 4 (type-changing) |
| `Permanent.effective_colors` | 5 (colour-changing) |
| `Permanent.has_keyword` | 6 (ability add/remove) |
| `Permanent.effective_power` / `effective_toughness` | 7a–7d |

A printed keyword is part of an object's copiable values, so it is *seeded*
before layer 1; grants and removals are continuous effects recorded in order by
`engine/keywords.py`. A removal can therefore take a printed ability away, and
a later grant can put it back — CR 613.9's worked example, and neither was
expressible when the engine stored one `gains_<keyword>` / `loses_<keyword>`
flag per keyword and checked removals first.

Layer 4 distinguishes *adding* a type (animation: a Kormus Bell Swamp is a
creature **and** still a land) from *replacing* subtypes (Evil Presence: the
land is a Swamp **instead of** a Forest). Ask `perm.has_type("swamp")` rather
than comparing `metadata["land_type_override"]`, which only sees one of those.

**Layer 7c splits by lifetime, and the split is load-bearing.** `power_bonus` is
persistent (counters, one-shot boosts); `static_buff_*`, `derived_buff_*` and
`lord_buff_while` are derived — cleared and rebuilt from the board on every
recompute. A continuous
effect that writes to the persistent channel has to subtract itself again later,
and a subtraction that doesn't exactly match its addition compounds on every
refresh, which CR 611.3a guarantees is constant. Each derived channel is cleared
by the same function that rebuilds it; splitting those apart reintroduces the
bug.

`lord_buff_while` splits again, by *when the contribution is evaluated*. It maps
a state qualifier ("attacking", "blocking", "tapped", "untapped") to its P/T
delta, and `layer_bridge.qualifier_holds` checks the qualifier when power and
toughness are **read** — not when the board was last recomputed. Nothing
recomputes when a creature taps, so a bonus contributed at recompute time
outlives its own condition: Castle's "Untapped creatures you control get +0/+2"
stayed on a creature for the whole declare-attackers step after it had attacked.
The qualifier vocabulary is `lord_buffs.QUALIFIER_FIELDS`, and a qualifier with
no predicate to evaluate it raises at import rather than applying
unconditionally.

All writes go through `engine/pt.py`;
characteristic-defining P/T (layer 7a) is registry-driven via
`engine.mixins.permanent_state.DYNAMIC_PT` (instruction kind → count
function) — a new CDA card is one table entry, not a new branch.

## Replacement effects

"If X would happen, Y instead" effects (Lich, Disintegrate's exile-instead,
Jade Monolith's redirect, …) are interceptors registered in
`engine/replacements.py` by event kind (`life_gain`, `damage_to_creature`,
`life_loss`, `would_die`, …). Each registration is a pure `applies` predicate
plus the effect itself; `apply_replacements(game, kind, payload)` runs them
through CR 616.1 (see "Effect ordering" below). An interceptor may consume the
event (skip the default action) or adjust `payload["amount"]` and let the process
continue. Interceptors self-select from game/permanent state, so the registry
stays name-free — Veteran Bodyguard's redirect reads the damage source's own
combat state rather than trusting which loop of the combat step it arrived in,
which is what makes it correctly decline a blocked trampler's excess.

### Replacements that need a decision

Some replacement effects are optional ("you *may* put it on top of your library
instead") or let the player choose among outcomes ("look at the top X cards,
draw one of them"). Those can't be applied inline — `apply_replacements` returns
synchronously while a human's answer arrives on a later request.

Such an interceptor *offers* a `ReplacementChoice` (`engine/replacement_choices.py`)
carrying the seat, the option labels, a default, and whatever its resolver will
need. An interactive seat gets it queued on `game.pending_replacement_choices`
and the event is suspended — the affected card sits in no zone until
`Game.resolve_replacement_choice` answers. Any other seat takes the default
immediately. Both paths finish through the same `@replacement_choice(kind)`
resolver, so there is one completion path rather than an inline AI branch and a
`confirm_` method that must agree.

Adding an interactive replacement is an interceptor plus a resolver — no new
`Game` field, confirm method, or prompt plumbing. `pending_lamp_draw`,
`pending_outside_game_draw` and `pending_leng_discards` remain as read-only
views over the queue in the shapes the web layer reads.

## Pending choices

Every other decision a seat owes part-way through a spell, an ability or a turn
step — a library search, a discard, Balance's removals, Power Sink's payment,
Word of Command's borrowed card — is a `PendingChoice` on
`Game.pending_choices`, with a `ChoiceSpec` registered in
`engine/pending_choices.py` (the table itself lives at the bottom of
`engine/mixins/stack/choices.py`).

A prompt has five parts: something arms it, a **resolver**, a **default** for
non-interactive seats, a **renderer**, and an **action** that answers it. The
spec carries the last four plus the gating metadata — the 400 message that
refuses other actions, whether the whole game waits or only the choosing seat,
whether a spectator sees it, and whether a non-interactive seat takes the
default the moment it is armed (`default_at_arm`) or stays queued for the
auto-resolver.

```
handler / upkeep effect / entry replacement
  → game.arm_pending_choice(kind, seat, **data)
      interactive seat  → queued on game.pending_choices
      other seat        → spec.default(...) now, or on the next auto-resolve pass
  → web/prompts.py renders it, refuses other actions, and answers AI-owned ones
  → confirm_*  → game.resolve_pending_choice(kind, seat, **response) → spec.resolve
```

The web layer loops over `game.iter_pending_prompts()` rather than naming each
kind, and that iterator spans **both** queues — a suspended `ReplacementChoice`
carries the same `kind`/`player_index`/`data` attributes, so no adapter is
needed. `pending_<name>` properties remain as read-only views derived from the
queue, each taking its seat from `choice.player_index` so the two cannot drift.

Adding an interactive choice is one `register_choice(...)`, one renderer, and
the code that arms it; `tests/engine/test_pending_choices.py` fails if a kind is
armed with no spec, registered with no renderer, or given an action `web/app.py`
never dispatches. That last check exists because the failure is silent and
asymmetric: a missing default *hangs an AI seat forever*, a missing gate lets a
player act around their own prompt, and a missing renderer means the prompt is
armed and never shown — which is exactly what Primal Clay shipped with.

## Prevention effects

Damage shields (CR 615) are a separate registry with the same shape,
`engine/prevention.py`. A `@prevention_effect(order, applies=…)` function
inspects one event — `{recipient, amount, source, combat}`, where `recipient` is
a `PlayerState` *or* a `Permanent` — and returns how many points it removes, or
`None` to pass. Both models carry `damage_prevention_pool`, so the numeric
shield of CR 615.7 is a single interceptor covering creatures and players;
shields that only make sense for a player (Circle of Protection, Reverse Damage,
Forcefield) check the recipient type themselves. `combat` marks the event as
combat damage and is what scopes the blanket shields (Fog, Ebony Horse) — every
other shield ignores it.

## Effect ordering (CR 616.1)

Replacement and prevention effects are not two pipelines that happen to run one
after the other. CR 616.1 gathers everything applicable to an event, lets the
affected player choose one, applies it, then repeats over what is *still*
applicable (616.1f). `engine/effect_ordering.py` is that process and the only
place either registry decides what runs next.

Which is why every registration is split in two: a pure `applies` predicate and
the effect. An effect that answers "do I apply?" by applying itself makes the
rule unimplementable — counting the contenders would mean running one, which is
exactly what 616.1 forbids before the choice is made. The predicate must not
consume a charge, because an effect that is asked about may then not be chosen.

### Asking the choice (616.1e)

The choice belongs to the affected player, and `apply_in_order` puts it to them
through its `ask` hook — an `effect_order` pending choice, registered like every
other prompt.

Purity is what makes suspending cheap. When a contended round is reached,
*nothing has been applied yet*, so the process can be abandoned and the **whole
event re-run** later: it arrives at the same round with the same contenders and
the recorded answer waiting. No continuation, no snapshot, no rollback — there
is nothing yet to undo. (Snapshotting would in fact be wrong here: the engine
compares damage sources and band members by identity, which a deep copy breaks.)

The re-run is supplied by the caller as a `restart` thunk, because an event is
more than its replacements — a draw nothing replaces still has to draw. Passing
one is a caller declaring "this event can suspend"; a suspended event reports
`consumed` so the caller skips the default action and the re-run does it
properly. Non-interactive seats are never asked anywhere.

Two things have to be true before a caller can offer a re-run. Its own
consequences must be *inside* the event — damage callers pass them as `then`,
so a suspended event does not get logged as 0 damage or gain life equal to
nothing (`tests/engine/test_damage_continuations.py` holds engine code to
that). And the work *behind* the event must be recorded, which is
`engine/resumption.py`: a loop registers the rest of itself before each step, so
answering resumes the divided damage, the sequence, and the spell's graveyard
move in that order. A loop using it must be the last thing its function does.

**Every damage path satisfies both and asks**, combat included. The combat
damage step was the last to convert and the only one where it was a restructure
rather than a two-line change: its dealing half is now nested resumable loops
(blockers by defender, by blocker, by band member; then the two attacker loops),
its tail — the lifelink gain, the state-based actions and the
`combat_first_strike_done` / `combat_damage_resolved` flags — is the last *step*
of the outermost loop rather than code after it, and both strike passes (CR
510.4) run through one `resolve_all_combat_damage` so a first-strike pass that
suspends records the second behind it instead of being re-run by a caller that
saw "not resolved yet".

`engine/damage_events.py` is where a *damage* event's members of both registries
become the one candidate list the rule describes. `deal_damage(game, event)` is
the entry point every damage path uses — there is deliberately no shields-only
or replacements-only alternative, because a caller holding half a contention set
is the shape this pipeline exists to remove.

Unlike parse rules, order here is semantic rather than a precedence tiebreak: it
is the *default choice* a non-interactive seat makes, so the two registries share
one order space for damage and a collision between them raises at import — as
does a duplicate within either one.

### A damage event has two halves (CR 120.4)

616.1 is not the only sequencing a damage event has. CR 120.4 runs it in parts:

- **120.4b** — the damage is *dealt*, as modified by the effects that interact
  with damage: shields absorb points, redirects send the event elsewhere.
  Triggers on damage being dealt trigger on what comes out of this half.
- **120.4c** — what was dealt is *processed into its results*, as modified by the
  effects that interact with those results: life lost for a player, damage
  marked for a creature.

616.1 chooses within each half, so they are four registry kinds:
`damage_to_player` / `damage_to_creature` for the first, `life_loss` /
`damage_marked` for the second. `deal_damage` returns a `DamageOutcome` carrying
both numbers — `dealt` and `result`.

Two numbers, not one, because they genuinely differ. Ali from Cairo ("damage
that would reduce your life total to less than 1 reduces it to 1 instead") is a
120.4c effect: the damage is dealt in full, so lifelink gains the full amount
(CR 120.3f) and a "deals damage to a player" trigger sees the full amount, and
only the life loss is capped. Collapsing them is what forced the combat damage
step to apply its shields where the event was recorded and its replacements
where life was applied — one moment short of a second number, not two moments by
necessity.

## Ordering conventions for parse rules

All orders share one global space (cross-category precedence is intentional:
"destroy all creatures" must beat "destroy target" regardless of which file
each lives in). Historic orders were multiplied by 100, opening ~99 free slots
between former neighbors; new rules should be written as `BAND_X + offset`
using the named band constants in `engine/parsing/base.py`. Current bands
(ascending):

- 1,000–6,500: upkeep pay-or-else effects (`BAND_UPKEEP`)
- 7,000–13,000: named triggered-ability effects (`BAND_NAMED_TRIGGERS`)
- 14,000–50,000: spells — zone changes, combat tricks, damage, library effects (`BAND_SPELLS`)
- 51,000–63,000: recolor, mass/targeted destruction, pumps, discard (`BAND_DESTRUCTION`)
- 64,000–80,000: game-ending, life totals, tap/untap, prevention, regeneration (`BAND_LIFE_TAP_PREVENT`)
- 81,000–100,000: activated abilities (pump, counters, tokens, misc) (`BAND_ACTIVATED`)
- 101,000–105,000: mana production, counterspells (`BAND_MANA_COUNTER`)
- 106,000–112,000: triggered-effect shorthands ("draw a card", "you lose the game") (`BAND_TRIGGER_SHORTHANDS`)
- 113,000–117,000: global/static buffs (lowest precedence — most generic patterns) (`BAND_GLOBAL_STATIC`)

A duplicate order raises at import time, so collisions surface immediately;
`tests/engine/test_parsing_common.py` additionally asserts the registry is strictly
ordered.

## Scale properties

- **Compile once:** `compile_card_oracle` is cached unbounded; parsing cost is
  paid once per distinct card per process, regardless of how many games run.
- **O(1) execution:** instruction dispatch is a dict lookup. Adding the
  1000th effect kind does not slow down the 1st.
- **Parsing is not O(1), and it is the real growth term.** The legacy
  `parse_primary_instruction` is a linear scan over the whole `@parse_rule`
  registry for every clause, so compile cost is O(cards × clauses × rules) with
  the rule count itself growing per card. The grammar front end replaces that
  with O(tokens) recursive descent plus hash lookups, which is the main reason
  it exists. See `ROADMAP.md`.
- **Precompiled regexes:** trigger tables and parse rules compile their
  patterns at import. Python's internal regex cache (512 entries) is never
  relied on.
- **Deterministic simulations:** `run_ai_simulation` seeds the module-level
  RNG, so a given seed reproduces a run exactly — required for regression
  tests over AI behavior.
