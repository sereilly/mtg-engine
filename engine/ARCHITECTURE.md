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
   │                                      (a large test run, a whole-pool script and
   │                                       the web server read it: program_store.py)
   │    ├─ engine/grammar/                    per line: tokenize → AST → lower
   │    └─ card_hooks.CARD_LINE_INSTRUCTIONS  one printed line of one card
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

**One parser.** `engine/grammar/` reads a line; where it refuses,
`card_hooks.CARD_LINE_INSTRUCTIONS` supplies the reading of one printed line of
one named card. There is nothing after that — a line neither claims produces no
instruction, and the card is reported unsupported naming the clause. The flat
`@parse_rule` registry in `engine/parsing/` (2,303 lines of substring
predicates hand-ordered against one another, which claimed a clause on a prefix
and dropped whatever followed) is deleted. See "Grammar front end" below.

## Packages

| Package / module | Role |
| --- | --- |
| `engine/oracle_types.py` | Shared dataclasses (`OracleInstruction`, `OracleProgram`, …) and text helpers. No engine imports at run time — safe to import from anywhere. `ActivatedAbilityCost`, which its annotations name under `TYPE_CHECKING`, is `engine/activated_ability_cost.py` (what an activated ability costs, one field per kind of payment), which imports nothing from the engine either. |
| `engine/events.py` | Trigger event bus: `emit(game, kind, **payload)` announces something that happened and enqueues every matching triggered ability in APNAP order. `@event_filter(kind)` registers per-kind applicability predicates ("…casts a *blue* spell"); they live in `engine/cast_event_filters.py` (the cast events) and `engine/event_filters.py` (every other kind), which `events.py` imports last so that importing it fills the registry. Prefer this over adding another hand-placed `iter_triggered_abilities` scan. **A graveyard card's trigger is collected beside the permanents'** (`graveyard_trigger_events`, CR 113.6m: its top instruction carries `functions_from: "graveyard"`, which `lowering/control_flow._lower_may` lifts off an offer's own move) and is asked the event's narrowing through the graveyard twin of the registry, `@graveyard_event_filter(kind)` (`GRAVEYARD_EVENT_FILTERS`: observer the owner, no source) — **fail-closed**, so a kind narrowed for permanents and with no graveyard reading fires nothing from a graveyard. The event's payload rides as the trigger's context, which is where "attached to that creature" (the Scourge Dragon Auras) finds its host. **The converse holds too**: a trigger that states another zone (`trigger_utils.trigger_functions_from`: the `functions_from` stamp, or `exiled_records.functions_in_exile`) is never yielded to a battlefield scan — `matching_triggers` takes the zone being scanned (default the battlefield), and the fire sites that read a program's triggers themselves filter through `trigger_utils.battlefield_triggers` (`tests/engine/test_scg_p5_trigger_zone_census.py`). |
| `engine/continuous.py` | The CR 613 layer system: layers, sublayers, timestamps, and dependency. Pure — it computes characteristics from effects and never touches game state, so it is tested directly against the rule text. |
| `engine/layer_bridge.py` | Adapter from the engine's stored channels to `ContinuousEffect`s (layers 2, 5, 6 and 7, and the computed accessors that apply them; layer 4 is `type_layer.py`, the printed seed `printed_characteristics.py`). The seam that lets storage change without touching the rules logic. |
| `engine/type_layer.py` | Layer 4: the type-changing effects on a permanent as CR 613 effects. `collect_type_effects` gathers what is recorded on the permanent or contributed by something attached to it, and what a board-wide static says of it (decided once for the whole board, with dependency, by `engine/type_statics.py`). `TYPE_EFFECT_CHANNELS` is every key the two collectors read, which `layer_bridge`'s accessors check before paying for the layer. The write API is `engine/type_changes.py`. |
| `engine/printed_characteristics.py` | What a card is printed with: off the battlefield the answer itself (`printed_shape`, CR 613 does not apply there), on it the seed every layer starts from (`seed_characteristics`, CR 613.2c) — types, supertypes, colours, P/T and the printed abilities, with the every-creature-type CDA (CR 604.3) folded in. |
| `engine/keywords.py` | Single write API for keyword abilities (layer 6): `grant_keyword` / `remove_keyword`, recorded in order with timestamps. Never set a `gains_<keyword>` flag by hand — grants and removals share a layer, so only the recorded order can decide which wins. |
| `engine/copies.py` | Single write API for copy effects (layer 1, CR 707): `become_copy` records the copied object's *copiable* values, the characteristics this effect takes (`copies=EXCEPT_COLOR` for Vesuvan Doppelganger), CR 707.9's modifications, a source and a timestamp; `copiable_card` folds them. Nothing about a copy is stamped onto the copy — a stamp records an answer, and CR 707.2 is a question about where the answer came from. |
| `engine/grammar/` | **The parser**: tokenizer → recursive-descent productions → typed AST → lowering to `OracleInstruction`. A production must consume every token of its line or raise `GrammarError`; see "Grammar front end" below. Imports only `oracle_types`. |
| `engine/effect_labels.py` | The `effect_kind` reporting label an ability's instruction carries, by instruction kind and by the position it occupies. Not dispatch: it feeds `SimulationResult` and `StackItem.ability_effect_kind` (the support report buckets by card type and refusal, never by label); whether a stack object is activated or triggered is `StackItem.ability_kind`, which `web/serialization.py` serializes as `is_triggered`. It is the vocabulary `engine/parsing/` used to produce, carried across that deletion so 57 cards were not silently re-bucketed, and held to the pool in both directions by `tests/engine/test_effect_labels.py`. The rows live in two family modules it imports: `engine/activated_labels.py` (the activated position) and `engine/triggered_labels.py` (the triggered position and its by-condition rows); a new row goes in its position's module. |
| `engine/oracle.py` | The compiler: caches one `OracleProgram` per card and runs the gates every card passes on its way to one. The readers it calls each have a module of their own (split out at the 2,000-line cap): `line_rewrites` (every rewrite applied before a line is classified — equip, cycling, buyback, kicker, entwine, echo, fading, flashback, affinity (CR 702.41a, `engine/affinity.py`: "This spell costs {1} less to cast for each artifact you control."), modal heads, and a distributive list of conditional grants written out one sentence per pair, Tribal Golem's), `line_classification` (the line loops, one per card type, the planeswalker program included), `ability_lines` (one line read as a triggered, activated or modal ability, and the delayed trigger a line creates), `front_ends` (an effect clause through `engine.grammar` and then the card hooks), `trigger_conditions` + `whenever_triggers` (the trigger-condition tables), `activation_costs` + `chargeable_costs` (an ability's cost, and the charger's reading of a prose cost), `keyword_lines`, `static_line_support` + `derived_static_claims` (support derived from the text-keyed rule tables) and `line_normalization`. |
| `engine/handlers/` | Effect executors. Each `@effect_handler(kind)` function mutates game state for one instruction kind. Registered into `EFFECT_HANDLERS` and dispatched with a single dict lookup. The shared helpers are four floors and one module above them: `_chosen.py` (a chosen word turned into filter keys), `_filters.py` (`permanent_matches_filter`, `_card_matches_filter`), `_targets.py` (`resolve_target_permanent`/`pick_target_permanent`, roles, back-references), `_amounts.py` (`evaluate_count`, `count_from_payload`), and `_common.py` (shared actions: the bounce, coin flips, damage application). A condition payload is answered by `control_flow.evaluate_condition`, which hands each kind to one of three registration-free families, the handler twins of the lowering's: `_conditions.py` (the game now), `_record_conditions.py` (a record of something already done) and `_color_conditions.py` (a colour). The order `control_flow.for_each` handles an announcement's roles in is `_role_order.py`'s: turn order between seats' groups, and within one seat's group the order its controller chooses (the `target_group_order` prompt, Kaboom!'s ruling). |
| `engine/pt.py` | The single write API for power/toughness channels (`set_base_pt`, `add_pt_modifier`, `switch_pt`, `clear_base_pt`) — see "P/T channels" below. All P/T mutation should go through here, never direct metadata pokes. |
| `engine/exiled_records.py` | The exile register: one `ExiledRecord` per exiled **object** a later effect still reads (a card's counters in exile, a face-down card, a spell's frozen announcement, the cards a Dimensional Breach will hand back), because a `CardDefinition` has nowhere to keep such facts. **The object is the key because no exile holds one object twice**: every arrival goes through `Game.put_card_into_exile` (`tests/engine/test_exile_arrival_seam.py`), which returns the object the pile holds — a new, equal one (`distinct_exile_object`, CR 400.7/406.7) when some seat's exile already holds that object, since a deck repeats one definition per copy — and the caller writes that object into every record. A record written before its card lands (a spell exiling itself, CR 608.2n) is `awaiting_arrival` until the funnel binds it. A record speaks for its card only while it is **registered and** its card is in its owner's exile (`is_live`, CR 400.7): the one departure seam, `Game.take_card_from_exile`, retires it, so a held record (a trigger's context, a delayed ability's `captured`) never comes back to life when the same card is exiled again. Being in the register says nothing about abilities: the upkeep step's exile scan announces only a trigger that functions from exile (`functions_in_exile`, CR 113.6k — an intervening "if this card is exiled"). "For as long as any of those cards remain exiled" is `delayed_triggers.WHILE_EXILED_THIS_WAY` over the records the arming handler registers (`handlers/exiled_returns.exiled_this_way_records`), ended at the departure seam (`end_exhausted_exile_delays`). |
| `engine/graveyard_order.py` | Where a card sits in a graveyard and how it got there. CR 404.1's order ("above" is later in the list; every reader answers with positions), CR 613.7d's arrival stamps for the cards whose static functions there (`record_graveyard_arrival`, `graveyard_arrival_stamps`), and **one object, one position**: the graveyard's one arrival, `Game.put_card_into_graveyard`, makes a copy arriving as an object some graveyard already holds a new, equal one (`distinct_graveyard_object`, exile's object, CR 400.7) and returns the object the pile holds, which a caller that writes the card down afterwards writes down — the dies-trigger fire sites (`dead_card`, the self-dies card), the discard seams, the mill records. So every record keyed by identity names one card: "put there from the battlefield this turn" (`record_arrival_history`, retired at an object's next arrival — No Rest for the Wicked, Second Sunrise), a `GraveyardTarget`, the stamps, a granted flashback. A pile written whole (the Debug Menu's paste) is held apart after the write (`keep_graveyards_apart`). Guarded by `tests/engine/test_graveyard_arrival_identity.py`, which also enumerates every add through a computed attribute name — two put cards into a graveyard around the seam until Mirrodin (Gravegouger's return, Vexing Arcanix's miss). |
| `engine/source_tapped_effects.py` | Effects a resolving ability creates "for as long as this <permanent> remains tapped" (CR 611.2b): Ashnod's Battle Gear, Thran Weaponry, the ONS Couriers. Each is an entry on the **source** (`record_while_tapped`) naming the one permanent it is on (a sweep records one per creature, CR 611.2c) and what it gives — a P/T delta, contributed by `_refresh_linked_tapped_pumps` (layer 7c), and/or keywords, granted by `_recalculate_lord_buffs` (layer 6, the pass that owns the derived-grant channel). The record is **ended, not skipped**: `Game.become_untapped` drops it (`end_effects_while_tapped`) and marks the source's abilities still on the stack (`StackItem.choices["source_untapped"]`, `break_pending_durations`), so an effect never comes back when the source taps again and one whose source untapped before resolution never starts (Old Man of the Sea, 2009-10-01). Phasing out ends it too (CR 702.26f). With no human to ask, the untap step keeps a "you may choose not to untap" source tapped while its effect still reaches a creature. |
| `engine/replacements/` | CR 614 replacement-effect registry (`life_gain`, `damage_to_creature`, `would_die`, …). An interceptor may consume an event or adjust its amount before the default action runs; see "Replacement effects" below. |
| `engine/prevention/` | CR 615 damage-shield registry. Each `@prevention_effect(order, applies=…)` function reports how many points it removes from one damage event, over players and permanents alike. See "Prevention effects" below. |
| `engine/effect_ordering.py` | CR 616.1: gather every applicable replacement and prevention effect, choose one, apply it, re-ask the rest. Both registries run through it, which is why each registration carries a pure `applies` predicate. See "Effect ordering" below. |
| `engine/damage_events.py` | A damage event start to finish: CR 120.4's two halves (damage dealt, then its result), with CR 616.1's contention set — shields *and* replacements together — inside each. `deal_damage(game, event)` is what every damage path calls, and there is no half-event alternative. |
| `engine/simultaneous_damage.py` | Damage several sources deal at once is **one** event (CR 603.2c, 510.2, 608.2f). `deal_damage` runs one event per chunk (one source, one recipient); this is the record of the dealing the chunks were dealt *with*, opened by the combat damage step once per strike pass and by every spell or ability dealing damage to several recipients (`deal_at_once`, the one loop they share, in APNAP order of the seat each chunk asks; a split damage sentence's `sequence` carries `oracle_types.ONE_DEALING` and is dealt by `begin_sentence` / `collect` / `deal_sentence`: its chunks collected at the damage seams as its steps run, then dealt as one loop in APNAP order), and finished when the last chunk is dealt. A trigger naming both ends answers each chunk; one naming the recipient alone, or the source alone, is announced once as the dealing finishes, for that end's total — delayed ones included (`delayed_triggers.fire_delayed_totals`) — and lifelink is gained there once per source (CR 702.15e). |
| `engine/tokens.py` | `make_token_card(...)` — the one place that builds a token's `CardDefinition`. A token-creating card is a production lowering to a generic `create_token` instruction, never a bespoke handler. |
| `engine/cast_restrictions.py` | Text-keyed "Cast this spell only during..." timing gates — an ordered predicate table, since the restriction is the same for any card printed with that phrase (not name-specific). Also the reader of the negative spelling a card prints about its own cast ("You can't cast Rock Jockey if you've played a land this turn", `self_cast_ban_line` with the card's name for CR 201.5's self-reference, its condition payload in `_SELF_CAST_BAN_CONDITIONS`), which is enforced as the `self_cast_ban` row of `engine/cast_prohibitions.py` so all three readers ask it. |
| `engine/cast_bans.py` | The board half of CR 601.3: a sentence printed on a *permanent* forbidding other spells or land plays ("Creature spells can't be cast", Steel Golem, Meddling Mage, Arcane Laboratory, Damping Engine and its CR 116.2d special action). A scan of the battlefields, one reader per sentence for the claim and the enforcement; `engine/cast_prohibitions.py`'s one table asks every ban here. |
| `engine/targeting.py` | Cast-time target kind derived from the compiled program — an Aura's `Enchant <subject>` line or an instruction's `type_filter`. The strangler seam replacing `legality.py`'s text cascade: it answers where the program carries evidence, `legality.py` answers otherwise, and a differential guard keeps them equal. The entry points (`derive_cast_spec`, `derive_activation_spec`, `derive_instruction_spec`) stay here; the evidence was split out at the 2,000-line cap into `enchant_targets`, `cast_targets`, `instruction_targets`, `payload_target_specs`, `target_descriptions`, `target_roles` and `cost_pickers`, with the ratchets' text probes in `picker_probes`. |
| `engine/legality.py` + `engine/legality_*.py` | The legality queries the web layer ships and the engine's gates ask, as mixins composed onto `Game` directly after `LegalityMixin`: combat legality and the module-level spec helpers (`legality.py`), what a spell may be announced with (`legality_cast_spec`), several-role announcements (`legality_roles`), an ability's picker and the activation gate (`legality_abilities`), the CR 601.2c cast gates (`legality_cast_gates`), stack targets (`legality_stack`), the CR 608.2b re-check (`legality_resolution`) and the enumeration every one of them compares against (`legality_enumeration`). |
| `Game.become_tapped(permanent)` | The single untapped→tapped transition (CR 701.26a). It announces `permanent_becomes_tapped` on the event bus, so a "whenever a `<type>` [an opponent controls] becomes tapped" card is dispatched by its own compiled condition and goes on the stack (CR 605.5a — it is not a mana ability). Never set `perm.tapped = True` directly — a trigger registered on one tapping path silently misses every other, which is exactly how Lifetap came to ignore Icy Manipulator. Entering the battlefield tapped is *not* becoming tapped and deliberately bypasses it. Its twin `Game.become_untapped` (CR 701.26b) announces `permanent_becomes_untapped` with the subject's controller and id frozen (Ghostly Pilferer's "this creature", Mesmeric Orb's "a permanent … that permanent's controller"). |
| `engine/cost_modifiers.py` | Text-keyed cost increases and reductions (CR 601.2f) — "<colour> <type> spells cost {N} more/less to cast" and the activated-ability form. Applied once per taxing permanent on any battlefield. The subject may also carry a creature type ("Goblin spells", the Warchiefs, read through `object_creature_types.creature_types` with the caster's seat), a mana-value bound counted on the stack ("with mana value 6 or greater", Krosan Drover — `spell_mana_value`, X as announced, CR 202.3e; the cast path asks the reduction again once X is settled) a relation to the taxing permanent ("that share a creature type with this creature", Mistform Warchief) and a per-object multiplier ("…for each artifact its controller controls", Hum of the Radix — `CostModifier.per_each`, counted at CR 601.2f off the seat `per_each_seat` names); every narrowing is asked in `_matches`, so every loop over the table asks the same ones. `reduce_cost` is CR 118.7's arithmetic, and `CostReduction.colored_only` is the one coloured reduction it does not spill (Edgewalker's "This effect reduces only the amount of colored mana you pay"). A permanent's modifier is read off its line in `engine/cost_modifier_lines.py` and a spell's own in `engine/self_cost_modifiers.py`; this module applies both and claims their lines. |
| `engine/untap_restrictions.py` | Text-keyed untap-step restrictions (CR 502): skip the step, per-type untap limits, power- and color-gated blocks, a type the untapping player names, and the "as long as this is untapped" qualifier that composes with any of them — plus one permission, "untap all <noun phrase> you control during each other player's untap step" (Seedborn Muse, scope `other_players_steps`), which the untap step carries out for the source's controller after the active player's untap, bound by none of the active player's restrictions (each is printed about a player's own step) — except a lock on the step itself (`engine/untap_step_locks.py`). Derived from oracle text, so a card printed with a known template needs no registration. |
| `engine/untap_step_locks.py` | A resolving spell's untap restriction that belongs to a **player's step** rather than to permanents: "Creatures don't untap during target player's next untap step" (Blinding Beam). CR 611.2c lets a rules-modifying effect reach objects that arrive after it began, so it is a record on `Game.untap_step_locks` (seat, noun phrase, steps left), read by `_untap_constraints` as one more `blocked` entry for that seat's step (and by the Seedborn path, which untaps in that step too) and spent when the step runs — not by a skipped one. The per-permanent marker (`handlers/tapping.skip_next_untap`) stays the reading of every sentence naming its permanents. |
| `engine/entwine.py` | Entwine (CR 702.42): the keyword line rewritten into CR 601.2b's optional additional cost (kicker's shape, mana and non-mana alike), and the link to the mode choice — a paid entwine **is** every mode (`entwine_mode_refusal`, asked by `_resolve_chosen_modes`; a headless paid cast with no mode named is given every mode, `entwined_mode_choices`). The modes are the "choose one or more" announcement (`ChosenMode`, each with its own targets, a graveyard stamp included), resolved in printed order through a resumable loop. The cast picker carries the offer on the card's own "modal" spec (`entwine` key, label "entwine"), never on a mode's. The AI weighs it once every mode is built (`ai_entwine.entwined_cast`). |
| `Game.shuffle_library_of(player, *, below=0)` | The one seam for a library a spell or ability shuffles (CR 701.24): shuffles through the module RNG at the call site's moment and announces `library_shuffled` with the seat as `event_subject_player` (Psychogenic Probe). The pregame shuffles (CR 103.3, mulligans) stay raw in `mixins/turn_management.py`; `tests/engine/test_w1g11_shuffle_seam.py` holds every other library shuffle to the seam. |
| `handlers/_common.flip_coin_for` / `flip_face_for` | The two coin-flip seams (CR 705.2): a flip won or lost (announcing `you_win_coin_flip`) and a heads-or-tails flip. Each asks the `coin_flip` CR 614 event (`replacements/coin_flips.py`, Krark's Thumb) how many coins one flip becomes and keeps a win / heads. A run its flipper may stop (Fiery Gambit) is `handlers/coin_runs.py`, one flip per `flip_again` answer. |
| `engine/auras.py` | What an Aura's effect lines say and whether the engine implements them. Two jobs: the **support gate** requires every effect line of an Aura to be claimed here, so an Aura whose effect is unimplemented is reported unsupported instead of entering play and doing nothing; and the **derivations** an Aura's continuous effects are read from while it is attached (static P/T, keyword grants, combat/untap restrictions, protection colours, artifact animation). Removal is the Aura ceasing to be attached — there is no remembered delta to subtract. `attach_aura`/`detach_aura` keep `attached_to` and `attached_auras` in step; `attached_aura` is a single slot a second Aura overwrites, so the list is the authority. Split by subject: the derivations are `engine/aura_grants.py` (what an attached Aura gives its host) and `engine/aura_restrictions.py` (what it forbids), the attachment record, `attach_aura`/`detach_aura` and the attach-legality predicate are `engine/aura_attachment.py`, the shared vocabulary is `engine/aura_vocabulary.py`, and `engine/auras.py` keeps the gate. |
| `engine/equipment.py` | Equipment (CR 301.5), the equip keyword (CR 702.6) and the attach action (CR 701.3). Equip is compiled as the activated ability CR 702.6a defines it to be — `expand_equip_lines` rewrites "Equip {1}" into "{1}: Attach this permanent to target creature you control. Activate only as a sorcery." before the compiler classifies a line, applied through `line_rewrites.expand_ability_lines` beside the modal-head rewrite — so the grammar's `Attach` production, the `attach_source_to_target` handler, the activation-restriction table and the target picker carry it with no equip-specific path. `equip_refusal` is the one legality predicate (CR 301.5, 301.5c, 702.16d), read by `attach_equipment`, the picker and `unattach_illegal_equipment`, the CR 704.5n sweep that also drops a departed Equipment from its host (CR 701.3d); the picker and the handler's target check ask it through `equip_target_refusal` (`attachment_target_refusal` for any attachment), which drops only the Equipment-side refusal — an Equipment that is a creature may still activate equip at a creature you control, and the attach does nothing (CR 301.5c, 701.3b; March of the Machines' 2004-12-01 ruling). Attachment state is the Aura record (`attach_aura`/`detach_aura`), and `engine/auras.py`'s templates read "equipped" beside "enchanted" (CR 301.5f). A non-mana equip cost printed behind a dash ("Equip—Pay 3 life", Nightmare Lash) is the same rewrite with the cost handed to the activated-ability cost parser. The grammar reads "equipped creature" as the referent "enchanted creature" names (`nouns.parse_object_filter`, one `is_enchanted` draft field, CR 301.5f / 303.4b), so every lowering written for the Aura spelling — counted pumps, damage and block triggers — reads the Equipment one; under any quantifier but the referent's own ("target equipped creature") the phrase refuses. A card that asks *about* equip abilities gets the word back through `is_equip_ability` (the rewrite run backwards, as `cycling.is_cycling_ability` is): "Equip costs you pay cost {1} less" (Auriok Steelshaper) is the activation reduction `cost_modifier_lines` narrows by `ability_keyword`. "Equipped" is a state word (`handlers/_filters._STATE_TESTS`, CR 301.5a). Two sweeps move Equipment beside the equip ability: `attach_all_to_source` ("attach all Equipment on the battlefield to it", Vulshok Battlemaster) and `unattach_all_from_target` (CR 701.3d, Disarm), each move through `attach_equipment` / `unattach_equipment`. |
| `engine/cycling.py` | Cycling (CR 702.29), the second keyword the rules define as a rewrite. CR 702.29a: "Cycling [cost]" *means* "[Cost], Discard this card: Draw a card.", so `expand_cycling_lines` rewrites the printed line before the compiler classifies anything (applied through `line_rewrites.expand_ability_lines` beside the equip and buyback rewrites) and from there it is an ordinary activated ability to the grammar, the cost parser, the stack and the web layer — none of which know the word. Typecycling (CR 702.29e) is the same rewrite with a search for its effect: "Plainscycling {2}" becomes "{2}, Discard this card: Search your library for a Plains card, reveal it, put it into your hand, then shuffle." (`typecycling_parts`, `TYPECYCLING_RULES_TEXT`), the type read word by word against `data/vocabulary/` (any card type, subtype or supertype, "basic landcycling" included) — a word no catalog knows leaves the line unrewritten, and `unread_cycling_line` reports the card unsupported naming it: the wide-shape gate `equipment.is_equip_line` keeps, for the same reason. CR 702.29f makes the result a cycling ability for every purpose, and every purpose asks `is_cycling_ability` (the rewrite run backwards): the cycle triggers, the cycling-cost modifiers and "Players can't cycle cards" (Stabilizer: `cycling_ban_line` / `cycling_ban`, read by the `cycling_ban` row of `activation_prohibitions.ACTIVATION_PROHIBITIONS`, which binds a card in a hand). The *other* half of the keyword — CR 702.29b's ability that exists in every zone and functions in one — is not a rewrite and is not here; it is CR 113.6j, in `engine/activation_zones.py`. **Cycling a card is one event** (ONS): the one seam that pays a cycling ability's discard cost (`CardActivationMixin._activate_from_hand`, asking `is_cycling_ability`) announces it, `_announce_cycle` → `emit("cycles_card")`, inside the activation's `deferring_triggers` window, so every trigger it fires goes on the stack above the cycling ability and resolves before its draw. Two conditions ride it: a permanent's "whenever a player / you / an opponent cycles a card" (`cycles_card`, seat axis `cycler`, `event_filters._cycles_card_filter`), and the cycled card's own "when you cycle this card" (`self_cycled`, CR 702.29c), asked of the card wherever it landed through `events._MOVED_CARD_CONDITIONS` — never a zone scan, so a second copy already in the graveyard does not fire. A discard by any other means is not a cycle; the discard itself is still announced by `_discard_card`, so a discard watcher answers a cycled card too. It is a **cost**, and every cost discard tells the seam so (`_discard_card(..., as_cost=True)`, held by `tests/engine/test_discard_cost_seam.py`): Library of Leng's "if an effect causes you to discard" refuses it ("costs aren't effects", 2004-10-04), where it used to put the cycled card back on top of the library for the draw to bring back. |
| `engine/activation_zones.py` | Which zone an activated ability functions in (CR 113.6), and the one reader every activation path asks. CR 113.6b's *stated* zone (the `functions_from` payload key `activation_restrictions.py` and `lowering/_bound_returns.py` stamp) outranks CR 113.6j's *derived* one — an ability whose cost discards the card it is printed on is payable in a hand and nowhere else (CR 701.9a), so cycling and Waker of Waves get the same answer off the compiled cost with no card and no keyword named. It is the **negative** half that was missing: `activate_from_hand` asked `cost.discard_self` and nothing asked the converse, so `usable_activated_abilities`, `queue_permanent_ability` and the AI's activation loop all offered a hand-only ability on the battlefield and ran it — a free repeatable draw that discarded nothing. The zone read now lives in `usable_activated_abilities(program, zone=…)`, which is the list all three index an ability by, so the web picker, the AI and the engine cannot disagree about what a permanent's abilities are. |
| `engine/characteristic_defining.py` | Characteristic-defining power/toughness (CR 604.3) — "<name>'s power and toughness are each equal to the number of X". The possessive subject is the card's own name, which normalization does not replace, so these were four literals containing four card names. One `dynamic_pt_count` instruction now carries what to count (`land`/`creature`/`same_name`) and whose battlefield to count it on. The general row reads the counted noun phrase through the noun parser into the shared `count_spec`, and a sum of two counts ("…the number of Zombies on the battlefield plus the number of Zombie cards in all graveyards", Soulless One) rides the first as `plus_count`, which `handlers/_amounts.evaluate_count` adds for the recompute and a resolution alike. A sum over the set rather than a count of it ("…the total mana value of other creatures you control", Ancient Ooze) is the same spec with the aggregate `total_mana_value`, beside `greatest_mana_value` ("the greatest mana value among permanents you control", `ast.GreatestManaValueAmong`, read behind "equal to" and a where-clause by one reader, `grammar/where_x.accept_greatest_among`). |
| `engine/static_bonuses.py` | Conditional static P/T bonuses (CR 613 layer 7c) — "gets +N/+N as long as you control a <land>", "as long as it's untapped". Both printed word orders, because only the trailing one was ever dispatched while the leading one sat in the support gate as a literal naming Swamp. Also `singular_land_type`, since Plains is spelled the same singular and plural. It also reads a quoted grant (`has "<ability>"`, ONS: Tribal Golem's fifth clause), carried on the `ability_lines` key the grammar's conditional statics already hand the layer-6 pass, and admitted only when the quote compiles (`granted_abilities.granted_ability_supported`). |
| `engine/lord_buffs.py` | The lord/anthem template (CR 611.3a, layers 6 and 7c) — "Other Goblins get +1/+1 and have mountainwalk", "Black creatures get +1/+1", "Attacking creatures you control get +1/+0". Derives **who** (colour, creature subtype, "other", controller scope, and a state qualifier: attacking/blocking/tapped/untapped) and **what** (P/T delta, keyword abilities, a granted activated ability). The support gate, both parser front ends and `_recalculate_lord_buffs` all read this one table. A clause carrying a **duration** is deliberately not claimed: that is the spell reading of the same sentence, which locks its set in at resolution (CR 611.2c) and stays on `buff_creatures_global`. A keyword the CR defines *as* a triggered ability (`keywords.LINE_DERIVED_KEYWORDS`: rampage, flanking, provoke) is granted as its printed **line** as well as its word — `_recalculate_lord_buffs` writes it on the derived-ability channel, once per lord (`cumulative=True`), so the compiler builds the trigger and two Hunter Slivers give a Sliver two provokes (CR 702.39b). |
| `engine/combat_restrictions.py` | Text-keyed combat restrictions (CR 506, 509): "can't attack unless defending player controls a <land type>", "attacks each combat if able", "can't be blocked by Walls", "can't block creatures with power N or greater". The land type and the threshold are payload data, not part of the instruction kind. The support gate consults this table rather than listing the same sentences, so a rider the table does not recognize fails loudly instead of compiling to a bare static line. The rows themselves are `_PATTERNS` in `engine/combat_restriction_table.py`. |
| `engine/amplify.py` | Amplify (CR 702.38), a keyword line admitted by the reader that implements it (`amplify_amount`, asked by `keyword_lines._qualified_keyword_part` beside rampage's and morph's) and performed as an entry replacement: `_perform_entry_state` calls `arm_amplify_reveals` for every road onto the battlefield, one `entry_reveal` prompt per instance (CR 702.38b) over the hand cards that share a creature type with the permanent as it enters (`object_creature_types.creature_types`, the card half that knows Conspiracy). A seat nobody asks reveals every eligible card; the reveal is public (`record_reveal`) and the counters go through `place_plus1_counters`. Cards entering together leave the hand together first (`handlers/hand._put_entrants`), so none can be revealed for another. |
| `engine/copy_casts.py` | Casting a copy of an exiled card during a resolution (CR 707.12; Isochron Scepter, Spellweaver Helix). `cast_copy_of_exiled_card` reads the source's linked exile (`linked_exile.cards_still_exiled_with`, the one reader of imprint's "the exiled card" — a card still in its owner's exile, read off the source even once it has left) and arms one `copy_cast` prompt per card (CR 607.3, 707.12a); the answer makes the copy in the caster's exile and casts it under a `CastPermission` that waives the mana cost (`free`) and marks the spell a copy (`cast_as_copy` → `StackItem.is_copy`, CR 707.10a), madness's offer arrangement; a copy not cast is taken out of exile at the same answer. A seat nobody asks weighs the copy with `ai_policy.choose_copy_cast` — inside a rehearsal one level down (`ai_prompt_picks._one_level_deeper`), so a rehearsed Isochron Scepter activation casts its copy — and takes a hand imprint whose source prints a linked ability (`ai_prompt_readers.offers_a_hand_imprint`, CR 607.2a's two phrases). Beside it, imprint's other readers: `mana_could_produce.exiled_card_colors` (Chrome Mox, Mourner's Shield), `mixins/protection.exiled_card_types` (Mirror Golem), `engine/exiled_card_bodies.py` (Duplicant, layers 4 and 7b), `subject_filters` key `shares_name_with_exiled_card` (Extraplanar Lens), `handlers/tokens._copy_exiled_cards` (Soul Foundry). |
| `engine/storm.py` | Storm (CR 702.40), the keyword the CR defines as a triggered ability: the keyword line compiles to a `self_cast` trigger (`keyword_lines.keyword_line_triggers`, one per instance, CR 702.40b) resolving `copy_triggering_spell` with `for_each: other_spell_cast_before_it_this_turn`, which `copies_for_each` reads as the storm spell's own position in the turn's cast record (`damage_ledger` casts, by stack object — every player's, any zone, countered or not, never a copy). Admitted by its reader (`is_storm`), not listed in `IMPLEMENTED_KEYWORDS`: a permanent printing storm is refused by `unread_storm_line`, because a copy of a permanent spell becomes a token (CR 707.10f) and the stack does not build one. Each copy's CR 707.10c new target is offered as it is made (`spell_copies._offer_copy_new_target`): a permanent or player through `copy_spell_target`, a graveyard card or a spell through CR 115.7's `change_slots` and `retarget_choice`; for a seat nobody asks, each offered target is rehearsed against keeping the original's (`ai_prompts.choose_copy_target`, `choose_copy_retarget`). Each offer is numbered (`copy_number` of `copy_count`, stamped only above one copy) so a person asked about each in turn is told which copy, and `copy_spell_target` has a keep answer (`confirm_copy_spell_target(keep=True)`, the wire's `accept: false`) that leaves a copy on the original's target whether or not it is still offered. The AI's main-phase chooser casts a storm spell after the turn's other proposed casts where it can still pay for it (`ai_policy._storm_spell_last`). |
| `engine/enter_effects.py` | Entry-state phrases `_initialize_permanent_state` carries out (enters tapped, enters with counters, enter-as-a-copy, choose-on-enter, no maximum hand size, spend white as red), performed with the permanent in no zone (CR 614.12a). `enter_effect_line` is the whole-line matcher; the compiler's support gate and `engine/grammar/registries.py` both read it, so the phrases cannot drift between what is implemented and what is claimed. The choose-on-enter readers and `ENTRY_CHOICES`, the table of what each choice records, are `engine/entry_choices.py`. |
| `engine/entry_awaiting.py` | A permanent on its way onto the battlefield while its "as it enters" choice is made (CR 614.12a): one `EntryInProgress` record per permanent on `Game.entries_in_progress`, from the moment its entry state starts until it is on the battlefield. It answers who controls the permanent meanwhile (`Game.controller_index_of` reads it), that a resolution's loop is waiting on it (an owed suspension), and that no copy of the table may be made; at a table that holds for answers the rest of the entry (the append, the recompute, the "enters" announcement, the caller's `then`) is the record's finish, run at the last answer (`ZoneFunnelsMixin._finish_answered_entries`). And the event one event's newcomers are handed to (`EntryEvent`, `DeferredEntry`), performed in APNAP order when it closes (CR 101.4, 613.7m, `apnap_order`) and finished together (CR 603.6a, `ZoneFunnelsMixin.entering_together`; a prompt armed inside it carries it, `ENTRY_EVENT`, so its answer re-joins it): appended at once, recomputed once, announced with every newcomer present, and waiting as one for the last answer any of them owes. The Game-side work is in `engine/mixins/zone_funnels.py`. |
| `engine/draw_step_modifiers.py` | Text-keyed symmetric bonus draws (CR 504): "at the beginning of each player's draw step, that player draws an additional card", with the optional untapped-source clause. |
| `engine/land_animation.py` | Text-keyed land animation (CR 613 layers 4/5/7): "All &lt;land type&gt;s are P/T \[colour] \[creature types] creatures that are still lands" (or "&lt;land type&gt;s you control are …"). The land type, the P/T, the colour, whose lands, keywords and creature types (Ambush Commander's "green Elf", added in layer 4 at the animator's own place in the order, `type_changes.land_animation_types_key`) are all payload on one `animate_all_lands` instruction, so a third animator needs no code — printed on a creature too (`static_line_support._GRAMMAR_STATIC_CREATURE_KINDS`). Replaced two parse rules that baked the land type into the instruction *kind* and a refresh that matched `card.name == "Kormus Bell"` — the two halves failing in opposite directions at once. |
| `engine/land_play_allowance.py` | Text-keyed extra land plays (CR 305.2): "You may play any number of lands on each of your turns", the "\[N] additional land(s)" forms, and the self-damage rider that may accompany them — and the prohibitions (CR 305.1): "Players can't play lands" with its board condition, and "You can't play lands if this creature was cast this turn" (Rock Jockey: the controller alone, while the permanent's own cast-this-turn stamp holds — `prohibition_holds` takes the permanent and the seat). Every land-drop gate — cast validation, the AI's land policy, the web layer's playable list — and the support gate all ask this one table, so they cannot disagree about what a card grants. |
| `engine/ai_valuation.py` | What a card does in the terms `ai_policy`'s heuristics ask about — how many cards it makes its target draw, whether it bounces a creature, what it destroys, whether it counters a spell, how much mana its ability adds — derived from the compiled program. Replaced eight `card.name == "…"` comparisons that had already decayed: Shatter, Terror, Stone Rain and Desert Twister print Disenchant's template, were not on the list, and the AI aimed all four at its own permanents. A heuristic's *weight* stays tuning in `ai_policy`; **which cards it reaches** is a claim about the pool and lives here. A family, one subject a module: `ai_weighed_cast` (the floor: the cast being weighed — its mode, the permission it is cast under — and the casts a seat may weigh beyond its hand), `ai_target_sides` (which side of the table one target or a seat belongs on), `ai_slot_sides` (each slot or role of an announcement that names several, and what a divided spell divides), `ai_standing` (the one measure: what a seat's position is worth), `ai_rehearsal` (what one cast does to it, found by rehearsing the cast), `ai_scratch_copy` (the copy it is rehearsed on: made, cut loose, concealed, seeded), `ai_combat_triggers` (what a creature's own attack or block trigger gambles), `ai_prompt_readers` (what a choice the rules leave to a player does — an offer's price, a toll's branches, a chosen colour, name, number or pile), and `ai_valuation` itself, the front door. |
| `engine/ai_sacrifice_victims.py` | Which permanent a seat sacrifices when the effect reads what it ate ("X is the sacrificed artifact's mana value", Forge Armor; `x_from_count.cost_sacrifice_characteristic`): one candidate per distinct reading, the cheapest to lose among equals. The cast chooser rehearses each and names the best (`ai_casts._cast_naming_its_sacrifice` → `CastAction.cost_permanent_ids`); a seat naming nothing pays with `Game.default_sacrifice_pick`. |
| `engine/ai_policy.py` | The AI's choosers — what a seat nobody is prompting does with priority (its main-phase cast, its land drop, a madness cast, the spell — an instant, or anything else it may cast at instant speed — or ability it uses at instant speed) — and the front door to the rest of the policy, one subject a module: `ai_actions` (the proposals and the one place each becomes an announcement, `cast_announcement`, and `activation_announcement` for an ability), `ai_casts` (one cast built as a candidate, mode by mode and offer by offer), `ai_cast_gates` (whether it can be made as announced), `ai_targets` / `ai_divisions` (what it names, and how a divided spell divides), `ai_scoring` (what a proposal is worth, by rehearsal), `ai_abilities` (which ability of its own permanents to activate), `ai_foreign_activations` (which of another seat's, CR 602.1b), `ai_hand_activations` (which ability of a card in its hand, CR 113.6j), `ai_graveyard_activations` (which ability of a card in its graveyard, CR 113.6b), `ai_text_changes` (which object a "target spell or permanent" cast names, and a text change's two words), `ai_declarations` (attackers and blockers), `ai_prompts` (the answers it gives part-way through a resolution) and `ai_prompt_picks` (what a seat nobody asks picks for each prompt kind's default, by worth), `ai_payment` / `ai_mana_sources` (the taps that pay), and `ai_priority` (what a seat nobody asks does with priority at instant speed — `instant_speed_window`, `act_at_priority` — one answer for the simulator's priority driver and the web AI seat). Nothing below imports `ai_policy`; the engine's resolution paths import the prompt answers from `ai_prompts` at call time. |
| `engine/card_hooks.py` | Name-keyed registries for truly bespoke card behavior: spell-resolved triggers, counterspell riders, leave-battlefield effects, draw-step modifiers, and `CARD_LINE_INSTRUCTIONS` — the instruction one printed *line* of one card compiles to, for texts that are a single card's sentence rather than a template. `engine/front_ends.py` reads it after the grammar refuses, and it is the last front end there is, so a line that grows a production leaves its entry dead rather than wrong; `tests/engine/test_card_lines.py` fails on a dead entry and on a key matching no printed line, and `tests/engine/test_front_end_safety.py` fails if the production that took a hooked line over produces less than the hook did. The only sanctioned place in the engine to key behavior on a card name — enforced by `tests/engine/test_card_name_reads.py`, which scans `engine/` for a name in a comparison (dispatch) rather than in a log line (data), with one acknowledgement: `simulation_checks._assert_expected`, a test oracle whose expectations must stay independent of the parse they check. |
| `engine/control.py` | CR 613 layer 2: a control change is a recorded *contribution* with a source and a timestamp (`change_control` / `end_control_change`), never a move; `base_controller_index` is the seat the permanent entered under and is never rewritten. `Game._sync_control` projects the derived controller onto the battlefield lists. |
| `engine/commander.py` | CR 903, the Commander variant and its Brawl option — inert unless `Game.commander_variant` is set. Colour identity is derived here (not read off the ingested field), the designation is per seat by card-object identity, and CR 903.9b's return-to-command-zone is why every "put into a hand / a library" goes through `Game.put_card_into_hand` / `put_card_into_library`. |
| `engine/subject_filters.py` | What a printed noun phrase means, tested against one permanent: `subject_matches` is the one answer, `TESTABLE_SUBJECT_FILTER_KEYS` names exactly the payload keys it can test, and a compiler admits a narrowed line only when every key is in that set. |
| `engine/object_creature_types.py` | What creature types an object has (CR 205.3) — a card in a zone, a spell, a permanent — and the **"share a creature type" relation** (CR 205.3m), the twin of `object_colors.share_a_color`: `creature_types` (only the creature-type vocabulary, through the layers), `share_a_creature_type`, the "each" form `shares_a_creature_type_with_each` (Cryptic Gateway) and the grouping `shared_creature_type_count` (Graxiplon). A printed far end rides `ObjectFilter.shares_creature_type_with`; `lowering/_cost_records.shared_creature_type_referent` reads it per position and `handlers/_chosen.resolve_shared_creature_type` turns it into the creature types of each object it names (`shares_creature_type_with_each`), which both pure matchers answer. And the **"every creature type" CDA** (CR 604.3, changeling's CR 702.73a; Mistform Ultimus): `every_creature_type_line` is the one reader of the sentence (support gate, grammar registry claim), `every_creature_type_subtypes` adds the vocabulary inside `printed_characteristics._printed_shape` — the parse both the off-battlefield answer and the layer seed read, so every zone sees it and a layer-4 type-setting effect replaces it — and `restore_struck_every_creature_type` keeps it through a layer-6 removal (the card's ruling). `search_filters.card_has_type` asks it for a creature-type word the printed line lacks, and asks `card_creature_types` (the owner's Conspiracy) when told `game=`/`owner=`. |
| `engine/search_filters.py` | What a library/graveyard search may *find* — one predicate over a `ObjectFilter` payload, asked by the search prompt, its default and the AI — and which pile a searched zone names (`search_zone_cards`, over `SEARCHABLE_ZONES`: library, graveyard and, since Dark Supplicant, hand). |
| `engine/target_restrictions.py` | Printed restrictions on what a spell may *choose* (CR 601.2c — "you can't choose an untapped creature as this spell's target"), read by the cast path and the AI's Aura chooser. |
| `engine/named_protection.py` | Protection a *player* has from a card name (CR 702.16i, Runed Halo): the cast-target check and the player-damage path both ask it. |
| `engine/activation_cost_alternatives.py` | An ability with a choice of printed activation costs — "{3}, {T} or {U}, {T}" (the Mirrodin Shards; one ability, either cost, never both). The compiler carries the first cost as `ActivatedAbilityCost.mana` and the rest as `mana_alternatives` (the halves share every non-mana cost); this is the one reader of the choice: `printed_mana_costs`, `alternative_cost_refusal` and the default for a seat that names none (the cheapest cost the pool covers, else the cheapest the board could pay). The announcement is `alternative_cost_index` — the cast path's name for CR 118.9a's choice — on `activate_permanent_ability`, `Game.activation_mana_charge`, `ActivationAction` and the web's activate route; the controller's view carries the prices as `ability_cost_alternatives`. |
| `engine/activation_restrictions.py` | Text-keyed "Activate only …" clauses (CR 602.5) — an ordered predicate table the activation path *and* the support gate read, so a printed restriction nobody listed cannot be admitted unenforced. The table and its moment-of-turn predicates live here; the predicates about the state of things are `activation_conditions.py`, the per-turn and once-only caps with the ledgers they count against are `activation_tallies.py`, and the sentence reader all of them share is `activation_clauses.py`. |
| `engine/cast_costs.py` / `engine/cast_permissions.py` | The CR 601.2b additional costs a spell prints in its own text, and permission to cast from somewhere other than the hand (a graveyard, the top of the library, the cards a seat exiled with a permanent whose static lets that seat look at and play them — `engine/exiler_grants.py`, Shared Fate) — both tables, not per-card. The cost objects and the clause table are `engine/cast_cost_clauses.py`. |
| `engine/mana_payment.py` | Whether a cost can be paid from the board and how: `plan_payment` is an exact matching of coloured pips to lands, because "you may pay {1}{B}" inside a resolution gives its player no priority window to produce the mana themselves. Which sources pay is chosen to leave the payer's other wants payable, then to cost least beyond the tap (`_sparing_choice`; the wants are `engine/mana_wants.py`, the prices `engine/mana_drawbacks.py`), at the one seam the AI planner, the web's auto-tap and every effect-collected cost share (an effect-collected cost asks `Game.effect_payment_plan`, each land planned as the units one tap of it adds, `board_payment.plan_over_land_units`) — and which *floating* mana pays generic likewise (`floating_units_for_generic`, colourless first where nothing is wanted), asked by `plan_payment`, the permission paths and the cast path's pool spend (`pool_payment._pay_mana_cost_directly`). |
| `engine/mana_drawbacks.py` | What tapping a mana source costs its controller beyond the tap (`tap_prices`), read off what the engine will run: the mana ability run for the symbol, every trigger the tap fires, its own untap text, and a counter a tap trigger puts on it that the board keeps tapped. One point per point of life, missed untap or harmful counter, `SOURCE_LOST` for a source given away or destroyed. Read by the AI planner and the effect payer (`mana_payment.payment_prices_in_force`), after the wants. |
| `engine/restricted_mana.py` | Mana that may be spent only on certain spells (CR 106.6) — the spend restriction travels with the mana in the pool. |
| `engine/hand_size.py` | CR 402.2's seven and the printed lines that change it, read by the cleanup step, the support gate and the parse-coverage report. |
| `engine/named_counters.py` / `engine/text_changes.py` / `engine/land_types.py` | Single write APIs: counters with no rules meaning of their own (CR 122) — plus the any-kind readers a "remove a counter" cost asks (`counter_kinds_on`, `counters_held`, `counter_kind_to_remove`, `ANY_COUNTER_KIND`) — text-changing effects (layer 3), basic-land-type changes (layer 4). |
| `engine/phases/` | One mixin per turn phase and per step within a phase (CR 500–514): `beginning_phase` + `untap_step`/`upkeep_step`/`draw_step`, `precombat_main_phase`, `combat_phase` + its five step modules (the two declaration steps with `attack_legality` / `attack_requirements` / `block_legality` / `block_requirements` beside them, and `block_triggers`; the combat damage step with `combat_damage_assignment` beside it, CR 510.1), `postcombat_main_phase`, `ending_phase` + `end_step`/`cleanup_step`. Each is composed onto `Game`. See `engine/phases/__init__.py` for the full taxonomy. **Once the game is over (CR 104.1) the stepping goes no further**: every stepping entry point a driver calls — `start_turn`, `start_next_turn`, `begin_turn_bookkeeping`, `resolve_untap_step`, `resolve_upkeep`, `resolve_draw_step`, `close_beginning_step`, `enter_turn_phase`, `enter_next_turn_phase`, `_close_current_priority_step`, `advance_combat_phase`, `end_combat`, `resolve_end_step`, `close_end_step`, `resolve_cleanup_step`, `_resolve_priority_window`, `pass_priority` and the one unit of play `resolve_next_object` — is decorated `@goes_no_further(...)` (`engine/game_over_guard.py`) and does nothing on an ended game; `tests/engine/test_scg_p5_game_over_stepping.py` holds every method those names match to it. |
| `engine/mixins/` | Cross-cutting game flow not tied to a single phase: turn-structure navigation and priority (`phase_steps`), per-turn/pregame management (`turn_management`), tapping a land for mana (`land_mana_taps`) and the CR 106.12 event the tap raises (`land_tapped_for_mana`), state-based actions (`game_ending`); a permanent's entry state (`permanent_state`, `entry_choices`) and its recompute (`board_statics`, `dynamic_creatures`, `lords`, `protection`); effects (`effects`, `draws_and_discards`); the control seam (`control_seam`), the zone funnels (`zone_funnels`), deaths (`deaths`), the stack push and its target announcements (`target_announcements`), and the general helpers (`helpers`). Consumes compiled programs; should never parse oracle text itself. |
| **The turn's phase plan** (`phase_steps`) | `Game.turn_phases_remaining` is the phases this turn still has to take, in order — CR 500.1's five at the start of every turn (`begin_turn_bookkeeping`), CR 500.8's extras *inserted* into it (`add_extra_phase`), each entry spent as its phase is entered (`_set_phase_and_step`, the line every entry point already passes through). **No driver names its own successor**: `next_unskipped_phase_after` peeks and `enter_next_turn_phase` / `enter_turn_phase` enter, and the headless flow, the combat phase and `web/game_flow._advance_phase` all go through them. A *list* rather than a dict keyed by phase name, because a repeated phase is two entries — an extra combat phase and the turn's own one have the same name, and a name-keyed record cannot tell them apart. Adding a phase means adding an entry point in `enter_turn_phase`; `tests/rules/test_turn_phases.py` fails if a phase the plan can hold has none. |
| `engine/mixins/stack/` | The stack (CR 405), one mixin per stage of an object's life on it: `casting` (CR 601), `activation` (CR 602), `resolution` (CR 603/608), and `choices` — a package: the `pending_choices` queue every part-way-through decision uses (`queue.py`), one mixin per family of prompt beside it, and the table registering them (`table.py`). The first three each have the parts split out of them at the 2,000-line cap beside them, composed onto `Game` directly after them: `cast_announcement` (where a spell is cast from, its modes and each mode's targets, CR 601.2a–c), `cast_additional_costs` (CR 601.2b/f–h), `cast_alternative_costs` (CR 118.9), `cast_target_validation` (CR 601.2c–d, and the Aura enchant gate) and `pool_payment` (X, CR 107.3, and the mana payment, CR 601.2g–h); `activation_checks` (everything an activation refuses before a cost, CR 602.2a–b and 602.5), `activation_payment` (can the cost be paid, and by what), `activation_charges` (the payers chosen and the payment, CR 601.2h) and `card_activation` (an ability of a card in a hand or a graveyard); `trigger_targets` (a trigger's mode and targets, CR 603.3c–d — made once the unit of play that set it off is over: a trigger pushed inside a `putting_triggers_on_stack` window waits on `Game.unannounced_triggers` and chooses as the outermost window closes, after the event and a step's state-based check, and a resolution's (`resolve_next_object`), CR 117.5; `TargetAnnouncementsMixin._trigger_choice_waits`) and `triggered_abilities` (triggers onto the stack, CR 603.3). `_cast_onto_stack` and `_activate_onto_stack` are CR 601.2/602.2 in order and call those steps; the mana payment, the hinge between refusing and paying, stays in each. |
| `engine/refusals.py` | A refused cast or activation (CR 733.1: the illegal action is reversed, CR 733.2: the actor keeps priority) is answered to the actor and to nobody else. `refuse(card_name, effect_kind, details)` is the only constructor of a refused result — a `Refusal`, a `SimulationResult` subclass — and writes nothing; the reason reaches the actor unchanged as the HTTP 400 `detail` and `SimulationResult.details`. The four attempt wrappers (`queue_from_hand`, `queue_permanent_ability`, `activate_from_hand`, `activate_from_graveyard`) take back every line a refused attempt wrote (`take_back_refused_attempt`) — its announcement, never a payment, because nothing is refused below the mana payment. The tap seam is the other door to a mana ability (CR 106.12): `tap_land_for_mana_or_refusal` returns its refusal's reason and logs nothing (`tap_land_for_mana` is that answer as a bool). `game.log` is served whole to every seat, so a refusal that wrote it named a hidden card. Held by `tests/engine/test_kg2_refusal_seam.py`: an AST walk of `engine/` and `web/` (no refused `SimulationResult` outside the seam, no log write in a refusal's tail, nothing refused below the hinge) and refusals driven over the pool, each a `Refusal` that leaves the log as it found it. |

## Adding support for a new card

Work top-down; stop at the first step that covers the card.

1. **Already covered?** If the parser reads the card's oracle text
   (run `compile_card_oracle(card)` and check `supported`), nothing to do.
   `python scripts/support_report.py` reports coverage for the whole manifest
   pool and `--set <CODE>` for one set, and the "creature text too complex"
   reason now names the specific unrecognized line.
2. **New text pattern, existing effect.** Add a *production* to
   `engine/grammar/`. Noun phrases, amounts, durations and player references
   are already parsed, so most patterns are a branch in an existing production
   plus a lowering — and there is no precedence number to pick, because a
   production either consumes its line or refuses it. If the lowering cannot
   honour part of the clause, raise `LoweringError` naming what is missing
   rather than emitting an instruction that means something narrower.
3. **New effect.** Invent a new instruction kind (verb_object naming, e.g.
   `exile_target_creature_until_eot`), lower to it, give it an entry in
   `INSTRUCTION_CATEGORIES` *and* in `GRAMMAR_CATEGORIES` (they are held equal),
   then add one `@effect_handler` function in the matching `engine/handlers/`
   module.
   Creating tokens: emit `create_token` (payload: name/power/toughness/
   type_line/colors/keywords/count) — never write a bespoke token handler.
   Setting/modifying power or toughness: go through `engine/pt.py`, never
   metadata directly. "If X would happen, Y instead": register an interceptor
   in `engine/replacements/` instead of an inline metadata check.
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
`OracleInstruction` IR. Both halves are layered bottom to top, and the seven
effect *families* carry the same names on each side — so one template has one
home per side. The order is asserted by `tests/engine/test_grammar_layering.py`
(`PARSE_LAYERS` / `LOWER_LAYERS`), along with family independence, the flat
re-export from each `__init__`. The module cap (2,000 lines, over every module
in `engine/`, `web/` and `scripts/`, `tests/engine/test_module_size.py`) is a
scheduling signal, not style: a family that crosses it has stopped absorbing
new work and splits along a CR boundary (`nouns.py` → `references.py`,
`statements.py` → `paragraphs.py`, `lowering/characteristics.py` →
`lowering/counters.py` are the precedents).

| Layer | Parse side | Lowering side |
| --- | --- | --- |
| vocabulary | `lexer.py` (tokenizer; P/T as one token, reminder text stripped and recorded, self-references collapsed to `SELF`), `stream.py`, `errors.py`, `vocabulary.py` (creature/land/artifact types, supertypes, keywords from `data/vocabulary/` — never the network at import), `amounts.py` | — |
| nodes | `ast/_core.py` (the vocabulary nodes everything is built from), `ast/{damage,characteristics,board,cards,stack,combat,game}.py`, `ast/statements.py` (the `Effect` / `Statement` unions and the composable statement nodes), `ast/lines.py` (the ability-line nodes and the `AbilityNode` union — the type of the *line* row below, as `statements` is of the *sentence* row). Frozen dataclasses, **append-only** — repurposing a field invalidates every golden and ratchet entry at once. | — |
| noun phrases | `nouns.py` (what an object phrase *describes*: `ObjectFilter`, `TargetSpec`, `PlayerRef`), `references.py` (what it *points at*: "that creature", "it", the enchanted permanent), `paragraphs.py` (a whole paragraph: the self-reference and linked-duration shapes) | `lowering/_common.py` (shared payload builders) |
| phrases | `phrases.py` (word tables and fragment productions shared by every family), `triggers.py` (trigger heads), `conditions.py`, `riders.py` | — |
| effects | `effects/{damage,characteristics,board,cards,stack,combat,game}.py` — one family per module | `lowering/` — the same seven, plus `zones`, `library`, `mana`, `counters`, whose lowering halves outgrew the cap while their parse halves stayed small |
| sentence | `statements.py` (one whole sentence), `costs.py` (activation and additional costs), `statics.py` | `lowering/categories.py` (the instruction → category table the support report and `GRAMMAR_CATEGORIES` read) |
| line | `parser.py` (`parse_line`: classification as keyword / activated / triggered / static / spell, then the statement grammar) | `lower.py` (dispatch: AST → instructions emitting the payload keys the existing handlers already read) |
| sidecars | `registries.py` — which text-keyed registry, if any, implements a whole line (the untap table, the cast-timing gate, the cost taxes, the CR 614 interceptors, the entry-state phrases); those lines carry no instruction because the registry runs them off the card's text. `derived.py` — derivation tables consulted **after** every production has refused (the lord/anthem table, the land animations, the land type changes), each handing over the table's own instruction. | — |

Two properties define how it behaves:

- **Full token consumption.** A production must account for every token of its
  line; leftovers raise `GrammarError`. So "parsed" means "understood in full",
  and a gap fails loudly (unsupported, with the clause named) rather than
  resolving as something the card doesn't say. This is the structural fix for
  the dropped-rider class that `scripts/parse_coverage.py`'s deletion probe
  detects empirically.
- **Category gating, which now means completeness.** A line's output is used
  when every category it lowered to is in `engine.grammar.GRAMMAR_CATEGORIES`.
  While `engine/parsing/` existed this was the migration's valve — a category
  left off fell back to the legacy rules, so work could land and be measured
  before it was switched on. With nothing underneath, leaving one off does not
  route its lines anywhere; it makes those cards **unsupported**. So the set is
  held equal to every category `lower.py` can emit
  (`tests/engine/test_grammar_categories.py`), and a category that genuinely
  should not execute belongs as a `LoweringError` in `lower_statement` — which
  carries a reason the coverage report can group — rather than as an
  unexplained absence from a frozenset.

Composition lives in the IR: `sequence`, `if_then`, `may`, and `for_each`
(`engine/handlers/control_flow.py`) nest instruction tuples in their payloads,
and `OracleExecutionContext.results` carries values between steps of one
resolution ("deals X damage… you gain that much life"). That is what removes the
need for fused kinds like `deal_damage_and_gain_life` — 28 of the legacy
compiler's 120 kinds were conjunctions of this sort.

Coverage is tracked in `GRAMMAR_COVERAGE.md` with floors in
`scripts/grammar_ratchet.json`, guarded by `tests/engine/test_grammar_ratchet.py`.
Those floors were the migration ratchet and are now a division-of-labour one:
every line the grammar does not read has to be read by something narrower, so a
**fall** means the pool became more special-cased than it was.

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

**Layers 1–7 are live.** The accessors that read them:

| Accessor | Layer |
| --- | --- |
| `Permanent.effective_card` | 1 (copy, then 1b face-down), then 3 (text-changing) |
| `Permanent.copied_from` | 1 (copy) |
| `Game.controller_index_of` / `controls` / `controlled_by` | 2 (control-changing; `engine/control.py`, contributions with timestamps over `base_controller_index`) |
| `Permanent.is_creature`, `Permanent.has_type`, `Permanent.basic_land_types` | 4 (type-changing) |
| `Permanent.effective_colors` | 5 (colour-changing) |
| `Permanent.has_keyword` | 6 (ability add/remove) |
| `Permanent.effective_power` / `effective_toughness` | 7a–7d |

**Layer 1 produces the seed rather than applying over it.** CR 613.2c: once
layer 1 has been applied, the object's characteristics *are* its copiable
values. So `engine/copies.py` answers with a `CardDefinition` — the copied
object's copiable values, folded by `copiable_card` and read by
`effective_card` — and `apply_layers` refuses a layer-1 `ContinuousEffect`
rather than silently dropping it. A copy effect records what it *takes*
(`copies=EXCEPT_COLOR` is Vesuvan Doppelganger) plus CR 707.9's modifications,
so an exception is a named value and not an unwritten stamp. Nothing about a
copy is stamped onto the copy: P/T, colours, types and abilities are all read
back through the layers from the recorded contribution, which is what keeps
CR 707.2's boundary — printed values as modified by *copy* effects, and nothing
else. `tests/engine/test_copy_reads.py` enforces it.

**A face-down object's card is the blank 2/2** (CR 708.2a, layer 1b;
`engine/face_down.py`). A face-down spell's `StackItem.card` and a face-down
permanent's `Permanent.card` *are* `face_down.face_down_card(real)` — no
name, text, subtypes, mana cost or colour, 2/2 — with the hidden card riding
on it as `CardDefinition.face_down_of`. So every reader of a characteristic,
every log line and every serializer is fail-closed by construction (a
face-down object never names its card to the table, CR 708.5). What the shape
owes in return is that the hidden card goes wherever the object goes when it
stops being hidden (CR 708.9), and that is two seams, both asked already:
`faces.whole_card` (every zone funnel and the stack's bin) follows
`face_down_of` exactly as it follows a split half's `face_of`, and
`Game.remove_all_from_battlefield` reveals a departing face-down permanent
(`face_down.reveal_departing`): its card becomes the real one, and
`copies.FACE_DOWN_AS_IT_LEFT` keeps what the departed object *was* the
face-down 2/2 for every last-known-information reader (CR 603.10). Layer 1b
follows 1a (CR 613.2b, 708.10): `copiable_card` returns a face-down
permanent's blank whatever copy effect it carries, and `become_copy` copies a
face-down source's values without the hidden card. Turning face up
(`face_down.turn_face_up`, CR 708.8) changes `Permanent.card` and nothing
else — the permanent is the same object, so counters, damage, Auras, control
changes, P/T effects and tapped state all stay. Morph (CR 702.37) is an
`AlternativeCost` the keyword line produces (`keyword="morph"`, {3}), turned
face down by the cast path at the announcement, and a CR 116.2b special
action (`turn_face_up`) on `engine/special_actions.py`'s permanent seam,
offered for the morph cost the permanent *would* have face up
(`face_down.face_up_morph_cost`, over `copies.face_up_copiable_card` — a
face-down Clone of a morph creature has one, CR 708.10). A morph cost
printing `{X}` (Legions: Bane of the Living, Warbreak Trumpeter) is offered
at its fixed part with `SpecialActionOffer.x_symbols`; the taker announces X
just before paying (CR 107.3d) as the seam's `x_value`, the listing reports
`x_symbols` and `max_x`, and `turn_face_up(x_value=)` hands X to the face-up
triggers (CR 702.37f) — an effect that turns it up chose no X, so theirs is
0. A morph cost that is not mana (Scourge: "Morph—Pay 5 life", "—Sacrifice
two Mountains", "—Return a Bird you control to its owner's hand", "—Discard a
Zombie card") is read by `face_down.morph_price` — mana first, the rest through
`alternative_costs._read_cost_clauses`, flashback's arrangement — and offered
as `SpecialActionOffer.clauses`, an `AlternativeCost`: the seam gates it with
`Game._unpayable_alternative_cost(refused_as=)` and pays it with
`Game._pay_alternative_cost(paying_for=)`, the payers named on
`cost_permanent_ids` / `cost_hand_index` and listed as `cost_permanents` /
`cost_hand_choices`. The cost is read with the permanent's text changes
applied (Putrid Raptor's ruling). "All morph costs cost {2} more" (Exiled
Doomsayer) is a `CostModifier` with `applies_to="turn_face_up"`, asked by
`_morph_offer` through `cost_modifiers.keyword_cost_modifiers` — never
under `"morph"`, the {3} face-down cast's keyword. Turning face up also
announces `permanent_turned_face_up` on the event bus ("Whenever a permanent
is turned face up", and an Aura's "When enchanted creature is turned face
up", narrowed by `event_filters._turned_face_up_filter`), in the same CR
603.3b window as the permanent's own `turned_face_up` triggers. Effects act on the
same two seams (`engine/handlers/face_down.py`): "turn … face down / face
up" is the `TurnFace` node (`turn_target_face_down`, `turn_target_face_up`,
`turn_self_face_down`; "any number of target …", Weaver of Lies, is the
several-target description on the same two handlers); "face-down" and
"with a morph ability" (a card in a zone answers it too — Dermoplasm's
hand pick) are the
`face_down_only` / `with_morph_ability` subject-filter keys, carried onto the
picker spec so CR 608.2b re-asks them; "Face-down creatures get +1/+1" is a
`lord_buffs` qualifier asked as P/T is read; and a look at a face-down
permanent (CR 708.5's exception) is the `face_down_look` notification prompt,
owed by the looker alone and never a log line — and, like `hand_reveal`, its
dismissal is never refused by a blocking prompt beside it
(`web/prompts.blocking_prompt`: Spy Network owes two library reorders as it
shows both). The client draws what each seat was sent and nothing else: the
controller's `hidden_card` as the real card marked face down, anyone else a
card back (`faceDownDisplayCard` in `web/static/battlefield-canvas.js`).

**`game.log` is every seat's, so a line names only what the table may see.**
A card in a hand or library nothing revealed, a card exiled face down (CR
406.3, its look permission included — a look is one seat's view), and the card
behind a face-down object are counted, never named: "may look at 3 face-down
card(s)", "a face-down card goes to their owner's hand"
(`linked_exile.exiled_cards_for_the_log` / `entry_name_for_the_log`). A card
exiled face down stays so after its exiler leaves or phases out —
`linked_exile.keep_face_down_after_departure` hands the permanent's face-down
entries to the game's register (`engine/exiled_records.py`) at the one
transition out — and an exiled card's own upkeep trigger fires from exile only
when it says it works there (`exiled_records.functions_in_exile`, CR 113.6k).
Held by `tests/engine/test_hidden_cards_stay_out_of_the_log.py` (beside
`test_private_finds_stay_out_of_the_log.py` for looks and searches): a new log
line that names a card goes through the census's watcher, which flags any name
hidden as it is written and still hidden at the next line.

A printed keyword is part of an object's copiable values, so it is *seeded*
by layer 1 rather than granted afterwards; grants and removals are continuous
effects recorded in order by
`engine/keywords.py`. A removal can therefore take a printed ability away, and
a later grant can put it back — CR 613.9's worked example, and neither was
expressible when the engine stored one `gains_<keyword>` / `loses_<keyword>`
flag per keyword and checked removals first.

Layer 4 distinguishes *adding* a type (animation: a Kormus Bell Swamp is a
creature **and** still a land) from *replacing* subtypes (Evil Presence: the
land is a Swamp **instead of** a Forest, CR 305.7). Ask `perm.has_type("swamp")`
or `perm.basic_land_types`; nothing else may read the storage, which
`tests/engine/test_layer_reads.py` enforces.

**Layers 3 and 4 record contributions, not values.** `engine/text_changes.py`
holds each text change (a colour word, a basic land type, a creature type —
Artificial Evolution — and every written form of it, a creature type's plural
included, never inside a card name, CR 612.2) with a timestamp;
`engine/land_types.py` holds each land-type
change with a timestamp *and a source*. Removal is dropping one contribution,
so an effect ending restores what the others still say rather than the printed
characteristic — a Gaea's Liege Forest ending on an Evil Presence Swamp leaves
a Swamp. **Neither layer commutes**, which is what the timestamps are for: two
land-type changes each *replace*, and two text changes each rewrite what the
previous one produced. Both were previously a single stamped value that only
one effect could occupy at a time.

Layer 3 is applied by `Permanent.effective_card`, which rewrites the rules
text, the type line and the parsed keywords — so a Magical Hack land swap and a
Sleight of Mind colour swap are one effect each, and every text-keyed table
downstream (untap restrictions, cost taxes, protection colours, lord grants)
reads the changed text without knowing text can change. The no-change path
returns the card object itself, unallocated. A spell's is applied by
`text_changes.spell_text_card` over `StackItem.text_change_effects` — the
stack object's `card` stays the printed card that moves — and carried onto
the permanent it becomes by `carry_spell_text_changes` (CR 400.7a).

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
one `dynamic_pt_count` instruction whose payload says what to count
(`engine/characteristic_defining.py`), tallied by
`engine/mixins/dynamic_creatures.py` — a new CDA card is a payload, not a
new branch.

## Replacement effects

"If X would happen, Y instead" effects (Lich, Disintegrate's exile-instead,
Jade Monolith's redirect, …) are interceptors registered in
`engine/replacements/` by event kind (`life_gain`, `damage_to_creature`,
`life_loss`, `would_die`, …). Each registration is a pure `applies` predicate
plus the effect itself; `apply_replacements(game, kind, payload)` runs them
through CR 616.1 (see "Effect ordering" below). An interceptor may consume the
event (skip the default action) or adjust `payload["amount"]` and let the process
continue. Interceptors self-select from game/permanent state, so the registry
stays name-free — Veteran Bodyguard's redirect reads the damage source's own
combat state rather than trusting which loop of the combat step it arrived in,
which is what makes it correctly decline a blocked trampler's excess.

A replacement and a prohibition over the same event are different rules. "If a
player would gain life, that player gains no life instead" (Sulfuric Vortex,
`replacements/life_gain.py`) is a `life_gain` interceptor, so beside Lich's
"draw that many cards instead" the gaining player chooses which applies
(CR 616.1e; `Game._gain_life` passes a restart, so an interactive seat is
asked). "Players can't gain life" (Forsaken Wastes) is CR 119.7's ban, asked by
`engine/life_prohibitions.py` *before* any replacement is gathered, and it
stops Lich as well.

The same shape one rule over: "You can't lose the game and your opponents
can't win the game" (Platinum Angel) is a ban on an *outcome*,
`engine/game_result_bans.py`, read off the board on every ask so it lifts the
moment the Angel leaves (CR 611.3b). **Every loss the engine performs goes
through `Game.lose_the_game`**, which asks it — CR 704.5a/b/c, commander damage,
and every effect that says a player loses (`tests/engine/test_mrd_w1g10_loss_funnel.py`
fails a `.lost = True` written anywhere but the funnel, a concession and a
draw); a "wins the game" effect asks `player_cant_win` before anyone loses to
it. A concession (CR 104.3a), a draw (CR 104.4) and CR 104.2a's last player
standing are outside it, per the Angel's rulings.

### Replacements that need a decision

Some replacement effects are optional ("you *may* put it on top of your library
instead") or let the player choose among outcomes ("look at the top X cards,
draw one of them"). Those can't be applied inline — `apply_replacements` returns
synchronously while a human's answer arrives on a later request.

Such an interceptor *offers* a `ReplacementChoice` (`engine/replacement_choices.py`)
carrying the seat, the option labels, a default, and whatever its resolver will
need. An interactive seat gets it queued on `game.pending_replacement_choices`
and the event is suspended — the affected card sits in no zone until
`Game.resolve_replacement_choice` answers. A queued offer is a prompt like any
other: stamped with the object resolving (`_stack_item`), it holds that object
on the stack (CR 608.2) and suspends the loop its event was a step of, and its
answer runs inside `_answer_pending_choice`, which resumes that loop. Any
other seat takes the default immediately. Both paths finish through the same
`@replacement_choice(kind)` resolver, so there is one completion path rather
than an inline AI branch and a `confirm_` method that must agree.

Adding an interactive replacement is an interceptor plus a resolver, and —
because a queued offer is a prompt like any other — the prompt's row: its
`ChoiceSpec` in `mixins/stack/choices/replacements.py` (named last in
`table.py`), a `pending_*` view and `confirm_*` answer there, a renderer in
`web/prompt_values.py` and its `@action_handler` (Obstinate Familiar's
`skip_draw` and Parallel Thoughts' `pile_top_draw` are the shape). No new
`Game` field. `pending_lamp_draw`, `pending_outside_game_draw` and
`pending_leng_discards` remain as read-only views over the queue in the shapes
the web layer reads.

## Pending choices

Every other decision a seat owes part-way through a spell, an ability or a turn
step — a library search, a discard, Balance's removals, Power Sink's payment,
Word of Command's borrowed card — is a `PendingChoice` on
`Game.pending_choices`, with a `ChoiceSpec` registered in
`engine/pending_choices.py`. Each family of prompt is a mixin of its own in
`engine/mixins/stack/choices/` (and `engine/mixins/entry_choices.py` for an
entering permanent's), holding its kinds' arm / confirm / resolve / default
methods and, at its foot, each kind's `ChoiceSpec` row (`SCRY_SPEC`); the
table itself is `engine/mixins/stack/choices/table.py`, one
`register_choices` list naming every row in the order the queue is read.

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
  → web/prompts.py renders it (one renderer per kind, in web/prompt_cards.py,
    web/prompt_board.py or web/prompt_values.py), refuses other actions, and
    answers AI-owned ones
  → the answering action's handler (in web/action_prompt_cards.py,
    web/action_prompt_board.py or web/action_prompt_values.py, as its renderer)
  → confirm_*  → game.resolve_pending_choice(kind, seat, **response) → spec.resolve
```

"Interactive" is asked of the seat that **decides** for the one that owes the
choice: `game.asks_a_person(seat)` — `game.decider_of(seat)` (its controller
during a turn another player controls, CR 723 / Mindslaver,
`engine/player_control.py`) is in `interactive_seats`, which keeps meaning
"a person sits here". The membership spelling `seat in game.interactive_seats`
is held to that one function (`tests/engine/test_player_control_seam.py`); the
web asks the same question through `web/seats._seat_type` (the decider's
kind) and `_sitter_type` (who sits there). An AI deciding for another seat
plays nothing optional for it and weighs its rehearsed picks by its own
standing (`engine/ai_player_control.py`).

The web layer loops over `game.iter_pending_prompts()` rather than naming each
kind, and that iterator spans **both** queues — a suspended `ReplacementChoice`
carries the same `kind`/`player_index`/`data` attributes, so no adapter is
needed. `pending_<name>` properties remain as read-only views derived from the
queue, each taking its seat from `choice.player_index` so the two cannot drift.

Adding an interactive choice is one `ChoiceSpec` row beside its resolver and
its name appended to `table.py`'s list, one renderer, the
code that arms it, and a scenario in the answered-choice census
(`tests/regressions/test_kg_prompts_answered_choice_leaves_queue.py`, which
fails on a kind with none); `tests/engine/test_pending_choices.py` fails if a kind is
armed with no spec, registered with no renderer, or given an action `web/app.py`
never dispatches. That last check exists because the failure is silent and
asymmetric: a missing default *hangs an AI seat forever*, a missing gate lets a
player act around their own prompt, and a missing renderer means the prompt is
armed and never shown — which is exactly what Primal Clay shipped with.

## Prevention effects

Damage shields (CR 615) are a separate registry with the same shape,
`engine/prevention/`. A `@prevention_effect(order, applies=…)` function
inspects one event — `{recipient, amount, source, combat}`, where `recipient` is
a `PlayerState` *or* a `Permanent` — and returns how many points it removes, or
`None` to pass. `combat` marks the event as combat damage and is what scopes the
blanket shields (Fog, Ebony Horse) — every other shield ignores it.

The *state* is generic too. A shield is a `Shield` in one collection on its
recipient (`engine/shields.py`): what it answers to (`source`, `color`), how
much it absorbs (`amount` points, `leave` points let through), how many `uses`
remain, and its `lifetime`. Both models carry the collection, so CR 615.7's
numeric shield is one interceptor covering creatures and players; shields whose
additional effect needs a player (Reverse Damage's life gain) check the
recipient type themselves. `kind` names the interceptor that consumes the
shield, so state and behaviour cannot drift.

`Shield.would_prevent` computes and `Shield.spend` mutates — the split CR 616.1
needs, since a predicate that consumed a charge would spend shields the player
was only asked about.

**Adding a shield is one `@prevention_effect` plus a `Shield`.** No
`PlayerState` field, no clearing line in the cleanup or end-of-combat step (the
sweeps read `lifetime`), and no change to the web payload. The old per-card
field names (`damage_prevention_pool`, `color_prevention_shields`,
`forcefield_capped_sources`, `reverse_damage_charges`/`_sources`,
`combat_damage_cap_one_charges`) survive as views over the collection, derived
on every read, so the web layer and the AI simulator keep reading what they
always did. `damage_prevention_color` is the one read-only view: the colour is
what its shield matches the source against (CR 615.9), so there is nothing to
set that isn't a shield.

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

A registration is one candidate — **unless it stands for several effects**.
"The next time you would draw a card this turn, … instead" is one registration
(`replacements/draws.py`'s armed one-shot) and one effect per activation: two
Words of Worship and a Words of War are three effects, and the drawing player
chooses which each draw spends (the Words' ruling, CR 616.1e). Such a
registration passes `instances=` to `@replacement_effect` — a pure reader of
`(instance key, source)` pairs — each instance's option the registration's label with its own source — equal effects collapsed to one — and
`replacement_candidates(kind, game, event)` makes a candidate of each, keyed
`<registration>:<instance>`, whose `apply` receives the instance. The keys need
only be stable while the event waits on the `effect_order` answer; nothing is
armed or spent in between. Without the event (a caller contending damage) the
registration is the one candidate it always was.

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

Two things have to be true before a caller can offer a re-run — unless every effect that can contend sends the object somewhere else (a death, a move into a graveyard, a discard's destination): a suspended move then reports "did not arrive", which is what it will be whatever is answered, and asks without either (`answered_restart`). Otherwise: its own
consequences must be *inside* the event — damage callers pass them as `then`,
so a suspended event does not get logged as 0 damage or gain life equal to
nothing (`tests/engine/test_damage_continuations.py` holds engine code to
that). And the work *behind* the event must be recorded, which is
`engine/resumption.py`: a loop registers the rest of itself before each step, so
answering resumes the divided damage, the sequence, and the spell's graveyard
move in that order. A loop using it must be the last thing its function does.
A sentence that asks **each player** something (CR 101.4, each knowing the
earlier answers, 101.4b) is the same loop over `game.apnap_seats()`:
`resumption.ask_in_turn_order(game, ask, then=…)` arms one seat's prompt per
step, so the next seat is asked only once the one before has answered, and runs
`then` once after the last answer — each player choosing a creature type
(`handlers/value_choices.each_player_chooses_creature_type`), the each-seat
discards (`handlers/discards`), the each-seat hand picks and reveals
(`handlers/hand._ask_each_seat_to_pick_from_hand`), and each player choosing
permanents ("each player returns a permanent they control", Curfew and Words
of Wind — `handlers/permanent_choices.choose_permanents`), and each player
sacrificing ("each player sacrifices a creature", CR 101.4's own example —
`handlers/sacrifices.sacrifice_matching_permanent` with `who` each_player /
each_opponent) or keeping and sacrificing the rest (Cataclysm —
`keep_chosen_sacrifice_rest`): there the answers are **held** in a batch
(`new_sacrifice_batch` / `new_keep_batch`) and the round's `then` performs
every seat's choice in one event, because CR 101.4 has the actions happen
simultaneously after the last choice. A loop whose repetitions sacrifice at
their answers (Fade Away, Read the Runes, Tariff, "each opponent sacrifices …
unless they pay") holds them the same way, on the loop's own context
(`sacrificing_together_through`, `OracleExecutionContext.sacrifice_batch`), for
its last step — and a held permanent is no candidate for another repetition
(Fade Away's ruling: one creature cannot pay for another). **A secret number is
not asked in turn**: "each player **secretly** chooses a number" (Goblin Game,
Menacing Ogre) is the card setting 101.4b aside, so `secretly_choose_numbers`
arms every seat's `secret_number` at once and the answer that completes the map
logs the reveal. Two decisions by two different players in one sentence are the
same loop over one seat with the second as its `then` — Blackmail's revealer
picks the three cards to show, then the caster picks among them
(`handlers/reveal._reveal_shown_cards_and_choose`).

**Every damage call in the engine satisfies both and asks**: the handlers and
the combat damage step (`tests/engine/test_kg_damage_handler_asks.py`), and
everything else (`tests/engine/test_kg3_damage_asks_outside_handlers.py`). An
inline upkeep effect, a prompt's answer, a land's rider, an Aura's entry and
Eye for an Eye's mirror each make the event the last thing their own step
does. A CR 614.9 redirect hands its moved damage to
`replacements/redirects.deal_redirected_damage`: the modified event's own
616.1 process, asked of its new affected player (CR 616.2; 616.1g holds
because the redirect is chosen first). A loop dealing to several recipients at
once walks `effect_ordering.in_apnap_order`, so their seats are asked in APNAP
order (616.1's last sentence). The combat
damage step was the last to convert and the only one where it was a restructure
rather than a two-line change: its dealing half is one resumable loop over the
pass's chunks in APNAP order of the affected seat (CR 616.1), inside one
simultaneous dealing (`engine/simultaneous_damage.py`); its tail — finishing
the dealing (the once-per-recipient and once-per-source triggers, lifelink once
per source), the state-based actions and the `combat_first_strike_done` /
`combat_damage_resolved` flags — is that loop's `then` rather than code after
it, and both strike passes (CR 510.4) run through one
`resolve_all_combat_damage` so a first-strike pass that suspends records the
second behind it instead of being re-run by a caller that saw "not resolved
yet".

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

## Precedence: there isn't any

A section here documented the `@parse_rule` order bands — one global integer
space, nine named `BAND_*` constants, and the rule that a specific pattern had
to be given a lower number than a generic one so `"destroy all creatures"` beat
`"destroy target"`. **It went with `engine/parsing/`, and its absence is the
point.** Precedence was a property of the registry, needed because every rule
was a substring predicate that could match any clause: the ordering was how a
rule was told which other rules it was allowed to be wrong about, and a new
card meant choosing a number relative to rules its author had not read.

A grammar has no such knob. `"destroy all creatures"` and `"destroy target
creature"` are one production whose difference falls out of the noun phrase's
quantifier, so there is nothing to order and nothing to get wrong. Two
orderings remain, both structural rather than numeric, and each is asserted
rather than assumed:

- **the front ends, most general first** — the grammar, then the name-keyed
  card hooks. A line the grammar learns to read stops reaching its hook, which
  makes a superseded hook *dead* rather than wrong;
  `tests/engine/test_card_lines.py` fails on a dead one, and
  `tests/engine/test_front_end_safety.py` fails if the production that took the
  line over says less than the hook did.
- **productions before derivation tables**, inside the grammar. `parse_line`
  runs every production and consults `engine/grammar/derived.py` only after a
  `GrammarError`; reversing that would let `engine/lord_buffs.py` claim every
  anthem in the pool. Asserted by
  `tests/engine/test_grammar_derived_lines.py`.

## Scale properties

- **Compile once:** `compile_card_oracle` is cached unbounded, and each card
  keeps its program on the card object once read; parsing cost is paid once
  per distinct (line, card name) per process, regardless of how many games run
  (`grammar.parser.each_line_parsed_once`, while a card compiles).
- **O(1) execution:** instruction dispatch is a dict lookup. Adding the
  1000th effect kind does not slow down the 1st.
- **Parsing was the real growth term, and no longer is.**
  `parse_primary_instruction` was a linear scan over the whole `@parse_rule`
  registry for every clause, so compile cost was O(cards × clauses × rules)
  with the rule count itself growing per card — the reason the grammar exists.
  Parsing is now O(tokens) recursive descent plus hash lookups, and the card
  hooks behind it are a two-level dict lookup keyed by (name, line).
- **Precompiled regexes:** trigger tables and parse rules compile their
  patterns at import. Python's internal regex cache (512 entries) is never
  relied on.
- **Deterministic simulations:** `run_ai_simulation` seeds the module-level
  RNG, so a given seed reproduces a run exactly — required for regression
  tests over AI behavior.
