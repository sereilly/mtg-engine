---
paths:
  - "web/**"
  - "tests/ui/**"
---

# Web layer

Part of `CLAUDE.md`, kept here so it loads when you open a file it
describes (the `paths` above). The root file's rule for editing applies,
and you can open this file directly whenever its subject is yours.

`web/app.py` is the FastAPI app (`/api/...` routes + static UI in `web/static/`)
and **nothing else** — the one place a route is declared. Everything else is a
module beside it, **layered**: `web/__init__.py` declares the order in `LAYERS`
and a module may import only from an earlier one
(`tests/ui/test_web_layering.py`, which also catches function-level imports).

| Module | Job |
| --- | --- |
| `runtime.py` | the card pool, the three store instances, session lookup, the per-session request lock |
| `events.py` | server-sent events — the one thing the API *pushes* |
| `seats.py` | seat kind, who has lost, whether to hold priority |
| `offers.py` | what a viewer's object offers right now as the engine answers it: a tap's mana, each ability's mana and refusal, a cast's mana colour, text-change words, payable X |
| `serialization.py` | engine object → client JSON, one function per kind |
| `catalog.py` | the pool and decks as the client browses them |
| `verification_report.py` | the verification tracker's read side |
| `pregame.py` | coin flip and mulligans |
| `turn_steps.py` | the beginning phase (turn 1's included, `_settle_pregame`) and the turn's boundaries |
| `combat_prompts.py` | banding / multiblock / pile-division assignments |
| `game_flow.py` | priority, phase advancement, AI stepping |
| `state_view.py` | the whole-state payload a client polls |
| `debug_actions.py` | Debug-Menu board manipulation, raw-state injection |
| `payment_plan.py` | the auto-tap: which permanents pay for an action, planned and tapped by the server |
| `action_helpers.py`, `action_*.py` | the shared cast plumbing, then one module of registered handlers per group of `ActionKind`s; a prompt's answer in `action_prompt_cards.py`, `action_prompt_board.py` or `action_prompt_values.py`, split as the renderers are |
| `actions.py` | the one dispatch over `ActionKind` |
| `prompt_registry.py` | `PromptContext` and the renderer table |
| `prompt_cards.py`, `prompt_board.py`, `prompt_values.py` | one renderer per prompt kind, by what the prompt is answered with (cards; permanents, players or spells; a value) |
| `prompts.py` | the three loops over every prompt (below) |

The card pool is `CARD_PATHS` from `engine.card_loader.manifest_set_paths()`,
loaded once at startup into `CARD_CATALOG` (`runtime.py`). **Adding a set means
ingesting it and moving one manifest entry** — the web app, the fixtures and the
scripts all read that registry. State lives in in-memory stores
(`session_store.py`, which takes the loaded catalog; `deck_store.py`, including
Moxfield import; `verification_store.py`). Game actions funnel through one
endpoint, `POST /api/sessions/{id}/action`, dispatched by the `ActionKind`
literal in `web/schemas.py`. A session's routes run one at a time and a payload
is encoded as one moment (`web.runtime.one_request_at_a_time`). Session `mode` is
one of `human_vs_ai`, `ai_vs_ai`, `human_vs_human`, `free_for_all` (3–4 seats,
configured per seat via `seats`).

`web/prompts.py` and the renderer modules beside it own every prompt's
presentation: one renderer per kind plus the three loops that render the prompts a viewer may see, refuse the actions a
pending prompt blocks, and answer AI-owned prompts with their defaults — all
reading the registry, so a new prompt is covered by construction. **The client
keeps no copy of that registry**: the payload carries `waiting_on_prompt`, which
the auto-pass reads. AI-owned prompts are answered before **and after** an
action's handler (a human's answer can arm one), and **an AI step never advances
a human's turn** (`_advance_ai_turn` returns unless the active seat's
*decider* is an AI — `web/seats._seat_type` answers who decides for a seat,
`_sitter_type` who sits there, which differ for a turn Mindslaver controls
(CR 723; the wire's `act_as`, `controller_seat`, `player_controls`) — nor in a
step a person holds priority in).

**What a card can do right now is sent, not re-derived by the client**: `ways`
(each way a card may be cast from a permission-opened zone, its price, whether
payable now), `ability_denials` (the activation path's pre-choice refusals
per ability, {T} included — `web/offers._ability_denial`), `ability_mana`
(each mana ability's symbols on this board — what the board, a record or the
cost decides included, `web/offers._decided_ability_mana`; whether a colour
is chosen; a mixed split's `combination` and an "or" of quantities'
`alternatives`, both answered on `mana_combination` —
`engine/mana_combination.py`; `symbols_by_cost` where the cost's permanent
decides; null for an ability that adds no mana), `ability_text_change` and a
cast's `text_change` (the words a text change announces), `x_payable` /
`ability_x_payable` (`{pool, board, colors}`: the payable X as the cast or
activation path prices it), `cast_mana`, a card's `cost_before_modifiers`
beside its charged price, `ability_prices` (an ability's charged price where
a modifier moved it, by ability index) and `ability_cost_alternatives` (a
Shard's two printed costs; the activate action sends `alternative_cost_index`),
a modal spec's `entwine` / `entwine_cost_spec`, `combat.blocker_ceilings`, a
cast's `decline_copy` (a copy-as-it-enters "may" declined), `prompt_owed_by`
(which seat owes the decision holding the game — the pending-choice queue's,
else a session-held one, `state_view._SESSION_DECISIONS`),
`abilities_lost`, `taps_for_mana`, `produced_mana`, a payment prompt's `payable`
(a "pay" that cannot be collected is refused with the prompt kept, never read as
a decline), a search's `min_picks`, a graveyard ability's `target_spec`,
`target_spec.cost_offers` (every applicable alternative cost by
`alternative_index`, which the cast answers with `alternative_cost_index`, CR
118.9a), a castable spell's `mana_combination` when it makes mana in any
combination (`count`, or `count_by_cost` per permanent that could pay its
cost — `mana_combination.cast_split_offer`), the active seat's
`combat.attack_requirements` and a defending seat's `combat.block_requirements`
(each with `most_obeyable`); and while a permanent's "as it enters" choice is
owed, that permanent listed in its controller's `battlefield` as arriving
(`serialization._serialize_arriving`, `entering: true`; the engine has it in
no zone until the answer, CR 614.12a), as are an open entry event's puts —
to their controller alone (CR 101.4a). A permanent's `name` is its name (CR
707.2: a copy's is what it copies) and `printed_name` the physical card's (a
face-down one's blank), which the client matches a card across zones and
groups a pile by; a test reading the payload looks a copy up by
`printed_name`. Every request body the client builds
is held to its route: presence (`tests/ui/test_kg_client_request_schemas.py`),
each value's type (`test_kg3_wire_request_shapes.py`), and what an armed
prompt's handler takes (`test_kg3_wire_prompt_state_bodies.py`). **Every
automatic sender in the client re-asks by fetching the state when its
in-flight flag clears** — one scheduled re-ask (`retryAutoAdvanceAfterFlight`)
serves every sender, delayed only while the state key stays unchanged — and
forgets the state key it last sent from when a game ends (a rematch can open
on the same turn, step and log length). A state is newer by the payload's
`revision` (one more per announced change, `web/events`), never by the log's
length, and each event stream is handed its events thread-safely,
coalesced with their reasons. The client does not plan taps: a
click on a castable card is answered by `web/payment_plan.py`
(`POST …/payment_plan` previews; `auto_tap` on the action taps), and every
paying action is previewed before it is sent (`previewPayingAction`), so a
pool that cannot pay opens the auto-tap dialog without a refused request.

The board UI is **canvas-rendered** (`web/static/battlefield-canvas.js`). **A
client change is not done until it has been clicked in a browser** — a
text-level test has passed over a change that made every Blood Moon land
unclickable.
