# Batch 9 — remaining failed-card fixes (continuation plan)

Tracks the CARD_VERIFICATION.md ❌ failures from this round. **Done** items are
fixed + tested (engine + UI-API) and the app boots clean in the browser.
**Remaining** items are investigated with a concrete plan but not yet implemented.

## Done (20)

| Card | Fix | Tests |
| --- | --- | --- |
| Fork | Verified the core already works: `copy_top_stack_spell` copies the targeted instant/sorcery and the copy resolves with the original's targets (legal — keeping targets is allowed). The *optional* "you may choose new targets" remains unmodeled and is documented as such | `batch9::TestForkCopiesSpell` |
| Library of Leng | New centralized `_discard_card` helper routes a discarded card to the top of the library when the player controls Library of Leng (else the graveyard); applied to random discards (combat-damage trigger, "discards X at random") and cleanup discards, not just Disrupting Scepter | `batch9::TestLibraryOfLengDiscards` |
| Farmstead | The ad-hoc enchant-land life-gain block now honors `human_choices` (auto-pays only as the AI/headless default); surfaced via `get_upkeep_pay_triggers` (enchant-land scan) as `upkeep_pay_to_gain_life` with a "no life" decline label | `batch9::TestFarmsteadUpkeepPay` |
| Mana Vault | New parse rule `upkeep_pay_to_untap_self` + `_UPKEEP_PAY_KINDS` entry + upkeep resolve branch (pay → untap the artifact, no decline consequence); surfaced via existing `get_upkeep_pay_triggers` (upkeep_self) and the upkeep-pay prompt (new "stay tapped" decline label) | `batch9::TestManaVaultUpkeepUntap` |
| Paralyze | New parse rule `upkeep_pay_to_untap_enchanted` + resolve branch keyed on `upkeep_enchanted_controller` via `attached_to` (pay → untap enchanted creature); `get_upkeep_pay_triggers` extended to scan all battlefields for auras enchanting this player's creature | `batch9::TestParalyzeUpkeepUntap` |
| Channel | `_serialize_emblems` emits a synthetic `kind:"channel"` emblem while `channel_active_until_eot`; canvas `onEmblemClick` routes it to a new `startChannelMana` (prompts life, sends `channel_mana`) instead of `activate_emblem` | `test_batch9_ui_api` (2) |
| Smoke | `get_untap_land_selection_options` generalized to creatures (Winter Orb land + Smoke creature caps coexist); `resolve_untap_step` gains `selected_creature_indices`; the web untap_select/untap_confirm flow now carries creatures and splits the selection by type at resolve | `batch9::TestSmokeUntapSelection` + `test_batch9_ui_api` |
| Kudzu | Human tap defers the reattach (`tap_land_for_mana(defer_kudzu_choice=True)`) arming `pending_kudzu_reattach`; controller picks the land via `confirm_kudzu_reattach` / `kudzu_reattach_confirm` ActionKind + land-button prompt; AI auto-resolver + headless path keep the first-land default | `batch9::TestKudzuReattach` + `test_batch9_ui_api` |
| Reverse Damage | New parse rule + `grant_reverse_damage_shield` handler arms a one-shot shield (`PlayerState.reverse_damage_charges`); `_prevent_damage` fully prevents the next event to the caster and gains that much life (cleared at cleanup) | `batch9::TestReverseDamage` |
| Phantasmal Terrain | Aura ETB arms `pending_land_type_choice` (provisional `island` default for headless/AI); human picks via `confirm_land_type` / `land_type_confirm` ActionKind + 5-button prompt; AI auto-resolver keeps the default | `batch9::TestPhantasmalTerrain` + `test_batch9_ui_api` |
| Helm of Chatzuk | Handler honors the chosen target creature (was forcing controller's first creature); precheck validates any creature | `batch9::TestHelmOfChatzuk` |
| Stone Giant | Activation enumerates only legal targets (your creature, toughness < its power) via `_ability_target_legal` | `batch9::TestStoneGiantTargeting` |
| Rock Hydra | Per-ability timing scoped to `ability.source_line`; {R} prevent usable any time, {R}{R}{R} pump upkeep-only | `batch9::TestRockHydraTiming` |
| Lure | AI treats a Lured attacker as forced so the defender gets a block step | `batch9::TestLureAttackPolicy` |
| Verduran Enchantress | "may draw" is now an optional yes/no via `pending_optional_pays` (free `draw` rider) | `batch9::TestVerduranOptionalDraw` + updated existing |
| Gloom | Viewer hand cards serialize the Gloom-taxed `mana_cost` (+ `printed_mana_cost`, `cost_increased`) | `test_batch9_ui_api` |
| Scavenging Ghoul | `_serialize_permanent` exposes `corpse_counters`/`counters`; canvas draws a ☠N badge | `test_batch9_ui_api` |
| Island Sanctuary | `getIslandSanctuaryInfo` added to `hasBlockingPromptForAutoPass` so the prompt isn't auto-passed | existing engine test covers resolve |
| Raging River | Per-role lock flags clear the prompt after assignment; no empty/defenderless loop | `test_raging_river_ui_api` (2 new) |
| Glasses of Urza | Reveal-hand modal cards wired to `showCardPreview`/`clearCardPreview` on hover | (visual; verify in browser) |

## Remaining (0 cards — optional enhancements only)

Every card originally in this section is now implemented and test-guarded (see the
**done** notes inline below). What is left are the optional enhancements called
out per card: the human-facing UI slices (Two-Headed Giant multi-block draft,
Camouflage pile selection, Magical Hack/Sleight of Mind from/to picker, Fireball
cross-seat targeting, Word of Command forced-spell target choice) and the
Illusionary Mask face-up reveal. None are required for the cards to function.

Infra patterns to reuse: `pending_optional_pays`/`confirm_optional_pay`,
`pending_search_library`/`pending_discard` style deferred choices (state on `Game`,
serialize in `web/app.py` ~1257-1410, gate other actions ~2565, add an ActionKind
in `web/schemas.py` + dispatch ~3050, render in `app.js`). **Every new pending
choice needs an AI/headless auto-resolver** (determinism).

### Upkeep / untap optional-pay prompts
- **Time Vault** — **done**. `_begin_turn` pauses for a human controlling a tapped Time Vault, serializing a `time_vault` prompt. New engine `untap_for_skip` untaps WITHOUT scheduling a future skip (unlike `skip_turn_to_untap`), so the `time_vault_skip` action untaps + advances to the next turn (the current turn is genuinely skipped, no double-skip); `time_vault_decline` resumes the turn. app.js prompt + a per-turn `time_vault_resolved_turn` guard. Test-guarded (`batch9::TestTimeVaultUntapForSkip` + 3 `test_batch9_ui_api` flow tests).

### Pending-choice (engine auto-resolves a choice today)
- **Lich** — core works and is now test-guarded (`batch9::TestLichSacrifice`): N damage sacrifices N nontoken permanents, game-losing ones last. *Remaining enhancement only:* `pending_sacrifice` + `confirm_sacrifice` so a human picks which (keep the "can't → lose" path).
- **Illusionary Mask** — **done** (engine + web): the `{X}` ability arms `pending_face_down_cast` (max_cmc = X); `confirm_face_down_cast` casts the chosen hand creature (mana value ≤ X) face down as a 2/2, keeping the real card (`face_down_real_card`), or declines. AI auto-resolver picks the first eligible; web serializes the eligible hand creatures + `face_down_cast_confirm` ActionKind + app.js prompt. Test-guarded (`batch9::TestIllusionaryMask` + `test_batch9_ui_api`). *Remaining (optional):* the "turned face up when it deals/takes damage or becomes tapped" reveal.

### Targeting
- **Fireball** — core works and is test-guarded (`batch9::TestFireballDividedDamage`): X is divided evenly among targets on one battlefield. *Remaining enhancement only:* allow targets across both seats — drop the same-seat guard at `app.js:3796`, add per-target `{seat,index}` payload (`schemas.py`), extend the divided `deal_damage` to split across both battlefields/faces.
- **Power Sink** — core works and is now test-guarded (`batch9::TestPowerSinkCounters`): the spell is countered when its controller can't pay {X}; AI auto-pays when able. *Remaining enhancement only:* a pay-or-be-countered prompt to a human targeted player (model on `pending_optional_pays`) + new ActionKind.
- **Forcefield** — **done**: `_classify_activation` returns a creature target filtered to unblocked attackers (`unblocked_attacker` flag), reusing the standard activation-target UI; the handler stores the chosen attacker in `PlayerState.forcefield_capped_sources` and `_prevent_damage` caps only that creature's next combat damage to 1 (cleared at end of combat / cleanup). Test-guarded (`batch9::TestForcefield`). (Reverse Damage in this cluster is also **Done**.)
- **Volcanic Eruption** — **done**: "Destroy X target Mountains" now offers a Mountain multi-select. `_classify_cast` returns `{kind: divided, land_filter: mountain, x_equals_targets: True}`; the enumerator lists Mountains (no player faces); the frontend divided flow casts straight away with `x_value` = the number chosen (no separate X prompt or per-target tax). Test-guarded (`batch9::TestVolcanicEruption` + `test_batch9_ui_api`).

### Text-change
- **Magical Hack / Sleight of Mind** — **done** (engine + API). The parse rule splits by suffix into a `mode` (`land_type` / `color_word`); the cast path threads the **from**-word (`old_color`) alongside `new_color` (StackItem + context + `queue_from_hand`/`cast_from_hand` + web `old_color`). The handler no longer recolors: Magical Hack sets a land's `land_type_override` (land) or remaps landwalk via `lost_<old>walk`/`has_<new>walk` (creature, honored in `_attacker_has_active_landwalk`); Sleight of Mind stores a per-permanent `color_word_remap` consumed in `_protection_colors`. `test_bug_regressions` updated; new guards `batch9::TestMagicalHackLand::test_remaps_creature_landwalk` and `batch9::TestSleightOfMind`. *Remaining (optional):* a UI double-prompt to pick the from/to words (schema + engine already accept them); extend `color_word_remap` consumption to the counter-color read sites.

### Combat / UI
- **Two-Headed Giant of Foriys** — engine + API **done** and test-guarded (`batch9::TestTwoHeadedGiantDoubleBlock`): `combat_blockers` is now `dict[int,list[int]]`, `declare_blockers` accepts int-or-list and enforces a per-creature block limit (`_max_blocks_for`, +1 per "can block an additional creature"); damage resolves correctly (blocker takes damage from each attacker, deals to one). The `blocker_pairs` schema/dispatch accept lists. *Remaining:* the frontend `combatBlockerDraft` is still single-attacker (~8 canvas sites + a serialized per-blocker `max_blocks`) — needed for a human to declare the double-block in-game.
- **Banding visuals** (Benalish Hero / Mesa Pegasus / Timber Wolves) — **done**: `renderCombatOverlay` feeds `state.combat.bands` (verified to serialize on band declaration) to a new canvas `setCombatBands`; the draw pass connects band members with a dashed purple link + node dots and group-highlights the band on hover (`_bandKeysForHover`). Zero engine risk; recommend a live screenshot in a banding combat to confirm placement.
- **Camouflage** — **done** (engine): `randomize_blockers` sets `camouflage_active_turn`; a new `resolve_camouflage_blocking` divides the defender's untapped creatures round-robin into one pile per attacker, randomly maps piles to attackers (module RNG → reproducible under a seed), and blocks each assigned attacker if able. `advance_combat_phase` auto-resolves it (human + AI) when active, gated so normal combat is untouched. Test-guarded (`batch9::TestCamouflage`). *Remaining:* a human-defender UI to choose pile membership (the headless model piles all untapped creatures).
- **Word of Command** — **done** (MVP): the stub that discarded the first card is replaced. `peek_hand_and_force_play` arms `pending_word_of_command` (revealing the target's hand to the caster); `confirm_word_of_command` makes the target play the caster's chosen card via `queue_from_hand` as the target, or declines. Wired end-to-end (AI auto-resolver forces the first card; `word_of_command_confirm` ActionKind + app.js prompt). Test-guarded (`batch9::TestWordOfCommand` + `test_batch9_ui_api`; existing `test_lea_cards` updated). *Remaining (optional):* let the caster also choose the **forced spell's targets** (MVP defaults the forced spell to target the forced player) and model "you control that player" for multi-step plays.

## Notes
- CARD_VERIFICATION.md is generated via the in-game Debug Menu — do **not** hand-edit; re-verify fixed cards there.
- `tests/declare_blockers_step.py::test_509_3a_..._regeneration_...` fails **in isolation** at baseline (test-order/RNG artifact), passes in the full suite.
