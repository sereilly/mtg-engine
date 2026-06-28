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

## Remaining (15) — plans

Infra patterns to reuse: `pending_optional_pays`/`confirm_optional_pay`,
`pending_search_library`/`pending_discard` style deferred choices (state on `Game`,
serialize in `web/app.py` ~1257-1410, gate other actions ~2565, add an ActionKind
in `web/schemas.py` + dispatch ~3050, render in `app.js`). **Every new pending
choice needs an AI/headless auto-resolver** (determinism).

### Upkeep / untap optional-pay prompts
- **Time Vault** — web surfacing of the already-implemented `get_begin_turn_untap_options`/`skip_turn_to_untap` (no web call today): pause `_begin_turn`, serialize, add skip/decline actions + app.js prompt.

### Pending-choice (engine auto-resolves a choice today)
- **Lich** — core works and is now test-guarded (`batch9::TestLichSacrifice`): N damage sacrifices N nontoken permanents, game-losing ones last. *Remaining enhancement only:* `pending_sacrifice` + `confirm_sacrifice` so a human picks which (keep the "can't → lose" path).
- **Illusionary Mask** — handler auto-picks first creature; add a hand-card selection prompt filtered by `cmc ≤ X`. Highest effort.

### Targeting
- **Fireball** — core works and is test-guarded (`batch9::TestFireballDividedDamage`): X is divided evenly among targets on one battlefield. *Remaining enhancement only:* allow targets across both seats — drop the same-seat guard at `app.js:3796`, add per-target `{seat,index}` payload (`schemas.py`), extend the divided `deal_damage` to split across both battlefields/faces.
- **Power Sink** — core works and is now test-guarded (`batch9::TestPowerSinkCounters`): the spell is countered when its controller can't pay {X}; AI auto-pays when able. *Remaining enhancement only:* a pay-or-be-countered prompt to a human targeted player (model on `pending_optional_pays`) + new ActionKind.
- **Forcefield** — already functional: activatable, caps the next combat damage instance >1 to 1 (`combat_damage_cap_one_charges`). *Remaining enhancement only:* an activation spec enumerating unblocked attackers + storing the chosen source so `effects.py` caps only that source. (Reverse Damage in this cluster is now **Done**.)

### Text-change (need from→to plumbing)
- **Magical Hack / Sleight of Mind** — Magical Hack's land case works and is test-guarded (`batch9::TestMagicalHackLand`): a changed land's type override and mana update. *Remaining:* split the parse rule by suffix ("one basic land type" vs "one color word") into a `mode`; thread the **from**-word through the cast path (schema + context). Magical Hack: land-type mode must NOT recolor and should remap `has_<old>walk`→`has_<new>walk` on creatures. Sleight of Mind: color-word mode stores a per-permanent `color_word_remap` consumed at the counter-color read sites (`stack_casting.py:423`, `handlers/stack.py:55`) — do not recolor. Update `test_bug_regressions.py:318` (asserts the old color_override behavior).

### Combat / UI
- **Two-Headed Giant of Foriys** — blocker model is `blocker→single attacker` end-to-end; change to `dict[int,list[int]]` (schema, `declare_blockers`, `combatBlockerDraft`) + a per-creature block limit from "can block an additional creature".
- **Banding visuals** (Benalish Hero / Mesa Pegasus / Timber Wolves) — `state.combat.bands` already serialized; pass to the canvas and draw purple connecting lines + hover group-highlight.
- **Camouflage** — handler is a stub; implement random pile partition/assignment using the left/right pile infra (seeded RNG for determinism).
- **Word of Command** — stub discards first card; needs reveal + hand-selection + opponent-controlled cast. Large; recommend a phased MVP.

## Notes
- CARD_VERIFICATION.md is generated via the in-game Debug Menu — do **not** hand-edit; re-verify fixed cards there.
- `tests/declare_blockers_step.py::test_509_3a_..._regeneration_...` fails **in isolation** at baseline (test-order/RNG artifact), passes in the full suite.
