let sessionId = null;
let seat = null;
let currentState = null;
let stateSyncSource = null;
let pendingActivation = null;
let pendingCastTarget = null;
let pendingCastX = null;
let pendingCastHandCard = null;
let pendingManaColor = null;
let pendingAutoTap = null;
// "Choose one —" modal spell awaiting the caster's mode selection.
let pendingModalChoice = null;
// A printed "as an additional cost to cast this spell, discard a card"
// (Thrill of Possibility, Sparkhunter Masticore). The payment is a card in
// hand, not a permanent, so it gets its own prompt rather than riding the
// battlefield picker the sacrifice cost uses — and it rides `cost_hand_index`,
// because a cost is not a target (CR 601.2b vs 601.2c).
let pendingDiscardCost = null;
// A permanent with more than one activated ability (Rock Hydra, Basalt Monolith)
// awaiting the player's choice of which ability to activate.
let pendingAbilityChoice = null;
// Channel emblem awaiting the player's choice of how much life to pay for {C}.
let pendingChannel = null;
// Free-For-All declare-attackers: the parked attack declaration while the
// attacking player picks which opponent to swing at from the prompt panel
// (one button per living opponent — never window.prompt).
let pendingAttackTarget = null;
// Disrupting Scepter discard destination toggle (Library of Leng): false =
// graveyard, true = top of library. Reset whenever a new discard prompt opens.
let discardToLibrarySelected = false;
// Effect-driven discards (Bazaar of Baghdad's three, Disrupting Scepter's one):
// the hand indices picked so far, by clicking cards in hand. Held client-side
// and submitted as one discard_confirm once the required count is reached.
let discardSelection = [];
// Balance: the indices the player has currently picked to sacrifice/discard.
let balanceSelection = { lands: [], creatures: [], hand: [] };
// Forced sacrifice (Lich): the battlefield indices the player has currently
// picked to sacrifice.
let sacrificeSelection = [];
// Raging River: in-progress left/right labels, keyed by creature index, for
// whichever role (defender division / attacker labeling) the viewer is resolving.
// Each creature starts unset; once every creature has a side the choice submits.
let ragingRiverSelection = null;
// Camouflage: in-progress pile choices for the defending player, keyed by
// creature index. Values are a 0-based pile number or "none" (kept out of every
// pile). Once every untapped creature has a choice, the piles submit.
let camouflageSelection = null;
// Identity of the Camouflage prompt the selection belongs to; reset on change.
let camouflagePromptSig = null;
// Identity of the prompt the in-progress selection belongs to ("seat:idx,idx").
// When it changes (new role / new creatures), the tentative selection is reset.
let ragingRiverPromptSig = null;
// Chosen mode index for the cast in progress, injected into the cast action.
let pendingCastModeIndex = null;
// "Choose one or more —" (Sublime Epiphany, CR 700.2d). The modes the caster
// picked, walked one at a time through the ordinary per-mode targeting prompts:
// each prompt ends by calling sendAction with that mode's target, and sendAction
// captures it here instead of sending until every chosen mode has one. Null
// whenever a cast is not collecting mode targets, which is every other spell.
let pendingModeCollection = null;
// Casting from the graveyard or exile (a cast permission, e.g. Chandra's
// "you may cast them this turn"): which zone the pending cast's card leaves.
// Rides sendAction the same way pendingCastModeIndex does, so every cast path
// (targeted, X, auto-tap retry) carries it without threading it manually.
let pendingCastFromZone = null;
let debugSearchTimer = null;
let debugAddManaMode = false;
let symbolMap = {};
let combatDragSource = null;
let combatDamageDraft = {};
let combatDamageDialogKey = "";
let combatAttackerDraft = [];
// Whether the active player is grouping the currently-selected attackers into a
// single attacking band (CR 702.22c). Sent as `bands` on declare_attackers.
let combatBandDraft = false;
// Which assignment the combat-damage dialog is currently editing: the active
// player's normal split ("attacker") or the defender's banding split ("banding").
let combatDamageDialogMode = "attacker";
let combatBlockerDraft = {};
// CR 702.22k: the active player's choice of which band member each creature
// blocking their band damages. Maps blocker_idx -> chosen attacker (band member).
let combatBandBlockerDraft = {};
// CR 510.1d: the defending player's division of a multi-blocking creature's
// damage (Two-Headed Giant of Foriys). Maps blocker_idx -> {attacker_idx: damage}.
let combatMultiblockDraft = {};
let combatDraftStepKey = "";
let combatPromptKey = "";
let previousLifeBySeat = {};
let aiAutoStepInFlight = false;
let aiAutoStepRequestedStateKey = "";
let autoPassTurnEndEnabled = false;
let autoPassTurnEndInFlight = false;
let autoPassTurnEndRequestedStateKey = "";
let autoPassMode = null;
let holdPriorityActive = false;
// Click-held stack item, or null. Tracked as {bottomOffset, sig} rather than
// an array index: the serialized stack is top-first, so responses cast while
// holding shift indices, while distance-from-bottom stays stable.
let stackClickHold = null;
let stackCanvasHoverActive = false;
let searchLibrarySelectedIndex = null;
let searchLibraryFilter = "";
let reorderLibraryCurrentOrder = null;
let autoPassPriorityInFlight = false;
let autoPassPriorityRequestedStateKey = "";
let autoPassDisabledPhaseInFlight = false;
let autoPassDisabledPhaseRequestedStateKey = "";
let autoCombatDeclareInFlight = false;
let autoCombatDeclareRequestedStateKey = "";
// Phases toggled OFF will be auto-passed. Default: only M1, M2 are ON.
const disabledPhases = new Set([
  "untap", "upkeep", "draw",
  "beginning_of_combat", "declare_attackers", "declare_blockers", "combat_damage", "end_of_combat",
  "end", "cleanup",
]);
const opponentDisabledPhases = new Set([
  "untap", "upkeep", "draw",
  "precombat_main", "beginning_of_combat", "declare_attackers",
  "declare_blockers", "combat_damage", "end_of_combat",
  "postcombat_main", "end", "cleanup",
]);
// Steps that never receive priority — can't be held regardless of toggle state.
const NO_PRIORITY_STEPS = new Set(["untap", "cleanup"]);

// Engine step names the human wants to stop at on the opponent's turn (the phases
// NOT toggled to auto-pass). Sent with `ai_step` so the AI hands us priority there.
function opponentStopSteps() {
  return PHASE_RAIL
    .map((p) => p.key)
    .filter((key) => !NO_PRIORITY_STEPS.has(key) && !opponentDisabledPhases.has(key));
}
// Engine step names the human wants to stop at on their OWN turn (the phases NOT
// toggled to auto-pass). Sent so the server opens a priority window at steps it
// would otherwise resolve itself (upkeep, draw) instead of skipping into the main phase.
function selfStopSteps() {
  return PHASE_RAIL
    .map((p) => p.key)
    .filter((key) => !NO_PRIORITY_STEPS.has(key) && !disabledPhases.has(key));
}
/** @type {BattlefieldCanvas|null} */
let battlefieldCanvas = null;
let lastAnnouncedTurn = null;
let lastAnnouncedTurnNumber = null;

const setupEl = document.getElementById("setup");
const boardEl = document.getElementById("boardPanel");
const aiControlsEl = document.getElementById("aiControls");
// Join URLs for the current hosted session. Surfaced in the "Waiting for
// Opponent" prompt rather than at the top of the page.
let currentJoinUrl = "";
let currentLanJoinUrl = "";
let currentPublicJoinUrl = "";
const menuPages = {
  home: document.getElementById("homePage"),
  host: document.getElementById("hostGamePage"),
  join: document.getElementById("joinGamePage"),
};

const MANA_ORDER = ["W", "U", "B", "R", "G", "C"];
const MANA_COLOR_OPTIONS = [
  { symbol: "W", label: "White" },
  { symbol: "U", label: "Blue" },
  { symbol: "B", label: "Black" },
  { symbol: "R", label: "Red" },
  { symbol: "G", label: "Green" },
];
const PHASE_LABELS = {
  untap: "Untap",
  upkeep: "Upkeep",
  draw: "Draw",
  precombat_main: "Precombat Main",
  main: "Main",
  combat: "Combat",
  beginning_of_combat: "Beginning of Combat",
  declare_attackers: "Declare Attackers",
  declare_blockers: "Declare Blockers",
  combat_damage: "Combat Damage",
  end_of_combat: "End of Combat",
  postcombat_main: "Postcombat Main",
  end: "End",
  cleanup: "Cleanup",
};
const PHASE_RAIL = [
  { key: "untap", label: "UN", title: "Untap" },
  { key: "upkeep", label: "UP", title: "Upkeep" },
  { key: "draw", label: "DR", title: "Draw" },
  { key: "precombat_main", label: "M1", title: "Precombat Main" },
  { key: "beginning_of_combat", label: "BC", title: "Beginning of Combat" },
  { key: "declare_attackers", label: "AT", title: "Declare Attackers" },
  { key: "declare_blockers", label: "BL", title: "Declare Blockers" },
  { key: "combat_damage", label: "DM", title: "Combat Damage" },
  { key: "end_of_combat", label: "EC", title: "End of Combat" },
  { key: "postcombat_main", label: "M2", title: "Postcombat Main" },
  { key: "end", label: "EN", title: "End" },
  { key: "cleanup", label: "CL", title: "Cleanup" },
];

function getActiveStepKey(state) {
  if (!state) return "";
  if (state.current_step) return state.current_step;
  if (state.current_turn_phase === "precombat_main") return "precombat_main";
  if (state.current_turn_phase === "postcombat_main") return "postcombat_main";
  return state.current_phase || "";
}

function getPhaseDisplayLabel(state) {
  const key = getActiveStepKey(state);
  return PHASE_LABELS[key] || PHASE_LABELS[state?.current_phase] || state?.current_phase || "-";
}

// The priority prompt is titled with the current phase/step name (e.g. "Main
// Phase") rather than a generic "Priority" label. Keys not listed here fall
// back to their PHASE_LABELS name.
const PRIORITY_PROMPT_TITLES = {
  upkeep: "Upkeep Step",
  draw: "Draw Step",
  precombat_main: "Main Phase",
  postcombat_main: "Second Main Phase",
  end: "End Step",
};

function getPriorityPromptTitle(state) {
  const key = getActiveStepKey(state);
  return PRIORITY_PROMPT_TITLES[key] || getPhaseDisplayLabel(state);
}

function q(id) {
  return document.getElementById(id);
}

function triggerLifeFlash(element, changeType) {
  if (!element || !changeType) return;
  element.classList.remove("life-flash-gain", "life-flash-loss");
  // Force a reflow so repeated changes retrigger animation reliably.
  void element.offsetWidth;
  element.classList.add(changeType === "gain" ? "life-flash-gain" : "life-flash-loss");
}

function renderLifePill(elementId, seatIndex, nextLife) {
  const lifeEl = q(elementId);
  if (!lifeEl) return;

  const numericSeat = Number(seatIndex);
  const numericLife = Number(nextLife);
  const previousLife = previousLifeBySeat[numericSeat];

  lifeEl.textContent = String(nextLife);

  if (Number.isFinite(previousLife) && Number.isFinite(numericLife) && numericLife !== previousLife) {
    triggerLifeFlash(lifeEl, numericLife > previousLife ? "gain" : "loss");
    if (window.FX) FX.lifePunch(lifeEl, numericLife - previousLife);
    SFX.onLifeChange(numericSeat, previousLife, numericLife, seat ?? 0);
  }

  if (Number.isFinite(numericSeat) && Number.isFinite(numericLife)) {
    previousLifeBySeat[numericSeat] = numericLife;
  }
}

// Show/hide a player's damage-prevention shield badge next to their life pill.
// Hovering it previews the card that granted the shield, like the card-shield
// badge on the canvas.
function renderPlayerShield(elementId, player) {
  const el = q(elementId);
  if (!el) return;
  const amount = Number(player?.damage_prevention_pool || 0);
  const source = player?.shield_source || null;
  if (amount > 0) {
    el.textContent = String(amount);
    el.classList.remove("hidden");
    el.title = source?.name ? `Prevent ${amount} damage — ${source.name}` : `Prevent ${amount} damage`;
    el.onmouseenter = source ? () => showCardPreview(source) : null;
  } else {
    el.classList.add("hidden");
    el.onmouseenter = null;
  }
}

function getCombatState(state = currentState) {
  return state?.combat || null;
}

function isCombatStep(state = currentState, step = "") {
  if (!state) return false;
  return state.current_turn_phase === "combat" && state.current_step === step;
}

function isCombatAttackerDrag(payload, state = currentState) {
  if (!payload || payload.kind !== "permanent" || !Number.isInteger(payload.permanentIndex)) return false;
  return isCombatStep(state, "declare_attackers") && seat === state?.current_turn;
}

function isCombatBlockerDrag(payload, state = currentState) {
  if (!payload || payload.kind !== "permanent" || !Number.isInteger(payload.permanentIndex)) return false;
  const combat = getCombatState(state);
  if (!combat) return false;
  return isCombatStep(state, "declare_blockers") && seat === combat.defending_player_index;
}

function getCombatDraftStepKey(state = currentState) {
  if (!state) return "";
  return `${state.turn_number || 0}:${state.current_turn}:${state.current_turn_phase}:${state.current_step}`;
}

function syncCombatDrafts(state = currentState) {
  if (!state) return;
  const nextKey = getCombatDraftStepKey(state);
  if (nextKey === combatDraftStepKey) return;
  combatDraftStepKey = nextKey;

  const combat = getCombatState(state);
  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn) {
    combatAttackerDraft = (combat?.attackers || []).map((item) => Number(item.attacker_index)).sort((a, b) => a - b);
  } else {
    combatAttackerDraft = [];
    combatBandDraft = false;
  }

  if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index) {
    combatBlockerDraft = {};
    for (const pair of combat?.blockers || []) {
      const b = Number(pair.blocker_index);
      (combatBlockerDraft[b] = combatBlockerDraft[b] || []).push(Number(pair.attacker_index));
    }
  } else {
    combatBlockerDraft = {};
  }
}

// Assign a blocker to an attacker in the draft. A creature that can block more than
// one attacker (Two-Headed Giant of Foriys, or a Blaze of Glory grant) toggles the
// attacker in its list; an ordinary blocker holds a single attacker (reassigning
// replaces it). Values are always arrays of attacker indices.
function assignBlockerDraft(blockerIdx, attackerIdx) {
  const b = Number(blockerIdx);
  const a = Number(attackerIdx);
  const defender = getCombatState(currentState)?.defending_player_index;
  const blockerCard = currentState?.players?.[defender]?.battlefield?.[b];
  const canMultiple = !!(blockerCard && typeof blockerCard !== "string" && blockerCard.can_block_multiple);
  const current = Array.isArray(combatBlockerDraft[b]) ? combatBlockerDraft[b] : [];
  if (canMultiple) {
    combatBlockerDraft[b] = current.includes(a) ? current.filter((x) => x !== a) : [...current, a];
    if (combatBlockerDraft[b].length === 0) delete combatBlockerDraft[b];
  } else {
    combatBlockerDraft[b] = [a];
  }
}

function toggleCombatAttackerDraft(permanentIndex) {
  const idx = Number(permanentIndex);
  if (!Number.isInteger(idx) || idx < 0) return;
  if (combatAttackerDraft.includes(idx)) {
    combatAttackerDraft = combatAttackerDraft.filter((value) => value !== idx);
    SFX.onMenuToggle(false);
  } else {
    combatAttackerDraft = [...combatAttackerDraft, idx].sort((a, b) => a - b);
    SFX.onMenuToggle(true);
  }
}

// Combat legality is computed authoritatively by the backend (engine/legality.py)
// and shipped on the serialized combat state. The frontend only reads those lists
// — it no longer re-derives attack/block legality from oracle text.
function getValidAttackerIndices(state = currentState) {
  if (!state || !isCombatStep(state, "declare_attackers") || seat !== state.current_turn) return [];
  const combat = getCombatState(state);
  const indices = Array.isArray(combat?.legal_attacker_indices) ? combat.legal_attacker_indices : [];
  return indices.map(Number).filter((idx) => Number.isInteger(idx) && idx >= 0);
}

function getValidBlockerAssignments(state = currentState) {
  if (!state || !isCombatStep(state, "declare_blockers")) return [];
  const combat = getCombatState(state);
  if (!combat || seat !== combat.defending_player_index) return [];
  const pairs = Array.isArray(combat.legal_blocker_assignments) ? combat.legal_blocker_assignments : [];
  return pairs
    .map((p) => ({ blocker_index: Number(p.blocker_index), attacker_index: Number(p.attacker_index) }))
    .filter((p) => Number.isInteger(p.blocker_index) && Number.isInteger(p.attacker_index));
}

// Why a proposed (blocker → attacker) assignment is illegal, or "" if it's legal.
// The legality itself comes from the engine's legal_blocker_assignments list; the
// extra checks below only produce a friendlier message for the common cases.
function blockAssignmentRejectionReason(state = currentState, blockerIdx, attackerIdx) {
  const combat = getCombatState(state);
  if (!combat || seat !== combat.defending_player_index) return "You aren't the defending player.";
  if (combat.camouflage_active) {
    return "Camouflage: use the pile buttons above your creatures — piles block random attackers.";
  }

  const isAttacker = Array.isArray(combat.attackers)
    && combat.attackers.some((a) => Number(a.attacker_index) === Number(attackerIdx));
  if (!isAttacker) return "That creature isn't attacking.";

  const defenderBattlefield = state.players?.[combat.defending_player_index]?.battlefield;
  const blockerCard = Array.isArray(defenderBattlefield) ? defenderBattlefield[blockerIdx] : null;
  if (!blockerCard || typeof blockerCard === "string") return "Invalid blocker.";
  // is_creature is the engine's effective view — an animated land (Kormus Bell /
  // Living Lands) is a creature even though its printed type line has no "creature".
  const blockerIsCreature = blockerCard.is_creature
    || String(blockerCard.type || "").toLowerCase().includes("creature");
  if (!blockerIsCreature) return "Only creatures can block.";
  if (blockerCard.tapped) return `${blockerCard.name} is tapped and can't block.`;

  const legal = getValidBlockerAssignments(state).some(
    (p) => p.blocker_index === Number(blockerIdx) && p.attacker_index === Number(attackerIdx)
  );
  if (!legal) {
    const attackerBattlefield = state.players?.[state.current_turn]?.battlefield;
    const attackerCard = Array.isArray(attackerBattlefield) ? attackerBattlefield[attackerIdx] : null;
    return `${blockerCard.name} can't block ${attackerCard?.name || "that attacker"}.`;
  }
  return "";
}

function getDisplayedAttackerLinks(state = currentState) {
  const combat = getCombatState(state);
  if (!combat) return [];
  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat.attackers_locked) {
    const defendingPlayerIndex = Number.isInteger(combat.defending_player_index)
      ? combat.defending_player_index
      : 1 - state.current_turn;
    return combatAttackerDraft.map((attackerIndex) => ({
      attacker_index: attackerIndex,
      defending_player_index: defendingPlayerIndex,
    }));
  }
  return combat.attackers || [];
}

function getDisplayedBlockerLinks(state = currentState) {
  const combat = getCombatState(state);
  if (!combat) return [];
  if (isCombatStep(state, "declare_blockers") && seat === combat.defending_player_index && !combat.blockers_locked) {
    return Object.entries(combatBlockerDraft).flatMap(([blockerIndex, attackerIndices]) =>
      (Array.isArray(attackerIndices) ? attackerIndices : [attackerIndices]).map((attackerIndex) => ({
        blocker_index: Number(blockerIndex),
        attacker_index: Number(attackerIndex),
      })),
    );
  }
  return combat.blockers || [];
}

function isOpponentMidAction(state, viewerSeat) {
  if (!state || !Number.isInteger(viewerSeat)) return false;
  if (state.current_turn !== viewerSeat) return false;

  const combat = getCombatState(state);
  const defenderSeat = combat?.defending_player_index;

  // During declare blockers, the defending player must confirm blockers before turn owner can continue.
  if (
    isCombatStep(state, "declare_blockers") &&
    Number.isInteger(defenderSeat) &&
    defenderSeat !== viewerSeat &&
    !combat?.blockers_locked
  ) {
    return true;
  }

  // If the stack contains an opponent action, treat that as opponent action in progress.
  if (Array.isArray(state.stack) && state.stack.some((item) => item?.caster_index !== viewerSeat)) {
    return true;
  }

  return false;
}

function renderCombatOverlay(state = currentState) {
  if (!battlefieldCanvas || !state) return;
  const combat = getCombatState(state);
  const arrows = [];
  const attackingKeys = new Set();

  if (combat) {
    const activeSeat = state.current_turn;
    const defenderSeat = combat.defending_player_index;

    for (const link of getDisplayedAttackerLinks(state)) {
      attackingKeys.add(`${activeSeat}-${link.attacker_index}`);
    }

    if (Number.isInteger(defenderSeat)) {
      for (const link of getDisplayedBlockerLinks(state)) {
        arrows.push({
          fromSeat: defenderSeat,
          fromIdx: link.blocker_index,
          toSeat: activeSeat,
          toIdx: link.attacker_index,
          kind: "blocker",
        });
      }
    }
  }

  // Attacking bands (Benalish Hero / Mesa Pegasus / Timber Wolves, …): connect the
  // declared band members with a purple link so the grouping is visible.
  const bands = [];
  if (combat && Array.isArray(combat.bands)) {
    const activeSeat = state.current_turn;
    for (const band of combat.bands) {
      if (Array.isArray(band) && band.length >= 2) {
        bands.push(band.map((idx) => ({ seat: activeSeat, idx: Number(idx) })));
      }
    }
  }
  battlefieldCanvas.setCombatBands(bands);

  battlefieldCanvas.setCombatArrows(arrows);
  battlefieldCanvas.setAttackingKeys(attackingKeys);

  // Raging River (CR 702): left/right piles + the viewer's Left/Right buttons.
  battlefieldCanvas.setRagingRiver(buildRagingRiverCanvasData(state));
  const riverInfo = getRagingRiverInfo(state);
  if (riverInfo) {
    const isDefender = Array.isArray(riverInfo.divide_creatures);
    updateActionHint(
      isDefender
        ? "Raging River: tap Left or Right above each of your creatures to divide them."
        : "Raging River: tap Left or Right above each attacker to choose its pile."
    );
  }

  // Camouflage: numbered pile buttons above the defender's untapped creatures.
  battlefieldCanvas.setCamouflage(buildCamouflageCanvasData(state));
  const camoInfo = getCamouflageInfo(state);
  if (camoInfo) {
    updateActionHint(
      `Camouflage: assign each of your creatures a pile (1–${camoInfo.pile_count}) or ✕ for none. ` +
        "Each pile blocks a random attacker."
    );
  }
}

function cardHasKeyword(card, keyword) {
  return String(card?.oracle_text || "").toLowerCase().includes(keyword);
}

// Banding (printed or granted). Prefer the serialized effective-keyword strip so
// a creature granted banding (Helm of Chatzuk) reads correctly; fall back to the
// printed reminder text on the card itself.
function cardHasBanding(card) {
  if (!card || typeof card !== "object") return false;
  const kws = Array.isArray(card.keywords) ? card.keywords : [];
  if (kws.some((k) => String(k).toLowerCase() === "banding")) return true;
  return String(card.oracle_text || "").toLowerCase().startsWith("banding");
}

// CR 702.22c: whether the currently-selected attackers can be declared as one
// legal band — at least two creatures, at least one with banding, and at most one
// without banding.
function selectedAttackersCanBand(state) {
  const battlefield = state?.players?.[state.current_turn]?.battlefield || [];
  const selected = combatAttackerDraft.filter((i) => i >= 0 && i < battlefield.length);
  if (selected.length < 2) return false;
  let banders = 0;
  let nonbanders = 0;
  for (const idx of selected) {
    if (cardHasBanding(battlefield[idx])) banders += 1;
    else nonbanders += 1;
  }
  return banders >= 1 && nonbanders <= 1;
}

// CR 702.22j: an attacker is "banding-blocked" when at least one of the creatures
// blocking it has banding — the defending player, not the attacker's controller,
// then assigns that attacker's combat damage among its blockers.
function attackerBlockedByBandingClient(state, attackerIdx) {
  const combat = getCombatState(state);
  if (!combat) return false;
  const defenderSeat = Number.isInteger(combat.defending_player_index)
    ? combat.defending_player_index
    : 1 - state.current_turn;
  const defenderBattlefield = state.players?.[defenderSeat]?.battlefield || [];
  return (combat.blockers || []).some(
    (pair) =>
      Number(pair.attacker_index) === attackerIdx &&
      cardHasBanding(defenderBattlefield[Number(pair.blocker_index)]),
  );
}

// Rebuild the damage events of a combat damage resolution from the state that
// preceded it, mirroring the engine's default assignment (lethal to each
// blocker in declared order, deathtouch needs 1, trample excess to the player).
function buildCombatDamageStrikes(prev, firstStrikePass, regularPass) {
  const combat = getCombatState(prev);
  const attackerSeat = prev.current_turn;
  const defenderSeat = Number.isInteger(combat.defending_player_index)
    ? combat.defending_player_index
    : 1 - attackerSeat;
  const attackerBattlefield = prev.players?.[attackerSeat]?.battlefield || [];
  const defenderBattlefield = prev.players?.[defenderSeat]?.battlefield || [];

  const hasFirst = (card) => cardHasKeyword(card, "first strike") || cardHasKeyword(card, "double strike");
  // Which creatures deal damage in the pass(es) covered by this update.
  const strikesNow = (card) => {
    if (firstStrikePass && regularPass) return true; // both passes bundled in one update
    if (firstStrikePass) return hasFirst(card);
    if (combat.first_strike_done) return cardHasKeyword(card, "double strike") || !hasFirst(card);
    return true;
  };

  const blockersByAttacker = new Map();
  for (const pair of combat.blockers || []) {
    const attackerIndex = Number(pair.attacker_index);
    if (!blockersByAttacker.has(attackerIndex)) blockersByAttacker.set(attackerIndex, []);
    blockersByAttacker.get(attackerIndex).push(Number(pair.blocker_index));
  }

  const strikes = [];
  for (const link of combat.attackers || []) {
    const attackerIdx = Number(link.attacker_index);
    const attackerCard = attackerBattlefield[attackerIdx];
    if (!attackerCard) continue;
    const power = Math.max(0, Number(attackerCard.power) || 0);
    const attackerStrikes = power > 0 && strikesNow(attackerCard);
    const blockerIndices = (blockersByAttacker.get(attackerIdx) || []).sort((a, b) => a - b);
    const deathtouch = cardHasKeyword(attackerCard, "deathtouch");
    const trample = cardHasKeyword(attackerCard, "trample");

    let powerLeft = attackerStrikes ? power : 0;
    const blockers = [];
    blockerIndices.forEach((blockerIdx, i) => {
      const blockerCard = defenderBattlefield[blockerIdx];
      if (!blockerCard) return;
      let damage = 0;
      if (powerLeft > 0) {
        let lethal = Math.max(0, (Number(blockerCard.toughness) || 0) - (Number(blockerCard.damage_marked) || 0));
        if (deathtouch && lethal > 0) lethal = 1;
        damage = i === blockerIndices.length - 1 && !trample ? powerLeft : Math.min(powerLeft, lethal);
        powerLeft -= damage;
      }
      blockers.push({
        seat: defenderSeat,
        idx: blockerIdx,
        damage,
        returnDamage: strikesNow(blockerCard) ? Math.max(0, Number(blockerCard.power) || 0) : 0,
        power: Number(blockerCard.power) || 0,
        toughness: Number(blockerCard.toughness) || 0,
      });
    });

    let playerDamage = 0;
    if (attackerStrikes) {
      if (!blockerIndices.length) {
        // Blocked stays blocked even if the blocker died to first strike.
        playerDamage = attackerCard.blocked && !trample ? 0 : power;
      } else if (trample) {
        playerDamage = powerLeft;
      }
    }

    if (!attackerStrikes && blockers.every((b) => b.returnDamage <= 0)) continue;
    strikes.push({ attackerSeat, attackerIdx, defenderSeat, playerDamage, blockers });
  }
  return strikes;
}

// Detect a combat damage resolution between two consecutive states (via the
// engine's log entries) and play the battlefield animation for it. Must run
// before the new state is applied so the canvas can snapshot creatures that
// died to the damage.
function maybeTriggerCombatDamageFx(prev, next) {
  if (!battlefieldCanvas || !prev || !next) return;
  const combat = getCombatState(prev);
  if (!combat || !Array.isArray(combat.attackers) || !combat.attackers.length || combat.damage_resolved) return;
  const prevLogLen = Array.isArray(prev.log) ? prev.log.length : 0;
  const newEntries = (Array.isArray(next.log) ? next.log.slice(prevLogLen) : []).map(String);
  if (!newEntries.length) return;
  const firstStrikePass = newEntries.includes("Resolved first strike combat damage");
  const regularPass = newEntries.includes("Resolved combat damage");
  if (!firstStrikePass && !regularPass) return;
  const strikes = buildCombatDamageStrikes(prev, firstStrikePass, regularPass);
  if (strikes.length) battlefieldCanvas.playCombatDamage(strikes);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeSymbolToken(token) {
  if (!token || typeof token !== "string" || token.length < 3) {
    return token;
  }

  const open = token[0];
  const close = token[token.length - 1];
  const isCurly = open === "{" && close === "}";
  if (!isCurly) {
    return token;
  }

  const body = token.slice(1, -1).trim().toUpperCase();
  return `{${body}}`;
}

function symbolSrc(token) {
  if (!token || typeof token !== "string") return null;
  return symbolMap[token] || symbolMap[normalizeSymbolToken(token)] || null;
}

function renderSymbolsInline(text, symbolClass = "mtg-symbol-inline") {
  const input = String(text || "");
  let html = "";
  let lastIndex = 0;
  const matches = input.matchAll(/\{[^}]+\}/g);

  for (const match of matches) {
    const token = match[0];
    const index = match.index || 0;
    const isCurlyToken = token[0] === "{" && token[token.length - 1] === "}";

    if (!isCurlyToken) {
      continue;
    }

    html += escapeHtml(input.slice(lastIndex, index));
    const src = symbolSrc(token);
    if (src) {
      const normalizedToken = normalizeSymbolToken(token);
      html += `<img class="mtg-symbol ${symbolClass}" src="${escapeHtml(src)}" alt="${escapeHtml(normalizedToken)}" title="${escapeHtml(normalizedToken)}" />`;
    } else {
      html += escapeHtml(token);
    }
    lastIndex = index + token.length;
  }

  html += escapeHtml(input.slice(lastIndex));
  return html.replace(/\n/g, "<br>");
}

function setSymbolsHtml(element, text, symbolClass = "mtg-symbol-inline") {
  if (!element) return;
  element.innerHTML = renderSymbolsInline(text, symbolClass);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Copy the capitalization of `source` onto `target` for the leading letter, so
// "Black" -> "Red" (not "red") when a text-change edit is rendered mid-sentence.
function matchLeadingCase(source, target) {
  if (source && target && source[0] === source[0].toUpperCase() && source[0] !== source[0].toLowerCase()) {
    return target[0].toUpperCase() + target.slice(1);
  }
  return target;
}

// Render oracle text, but where a text-changing spell (Sleight of Mind / Magical
// Hack) edited a word, show the original struck through followed by the new word
// in gold. `changes` is a list of {from, to} word replacements.
function renderOracleTextWithChanges(text, changes, symbolClass = "mtg-symbol-inline") {
  const base = String(text || "");
  const edits = Array.isArray(changes) ? changes.filter((c) => c && c.from && c.to) : [];
  if (edits.length === 0) {
    return renderSymbolsInline(base, symbolClass);
  }
  const pattern = new RegExp(`\\b(${edits.map((c) => escapeRegExp(c.from)).join("|")})\\b`, "gi");
  let html = "";
  let lastIndex = 0;
  for (const match of base.matchAll(pattern)) {
    const index = match.index || 0;
    const matched = match[0];
    const edit = edits.find((c) => c.from.toLowerCase() === matched.toLowerCase());
    if (!edit) continue;
    html += renderSymbolsInline(base.slice(lastIndex, index), symbolClass);
    const replacement = matchLeadingCase(matched, edit.to);
    html += `<span class="text-changed-old">${escapeHtml(matched)}</span> `;
    html += `<span class="text-changed-new">${escapeHtml(replacement)}</span>`;
    lastIndex = index + matched.length;
  }
  html += renderSymbolsInline(base.slice(lastIndex), symbolClass);
  return html;
}

function formatManaSymbolsHtml(counts) {
  const parts = [];
  for (const symbol of ["W", "U", "B", "R", "G", "C"]) {
    const count = Number(counts?.[symbol] || 0);
    if (count > 0) {
      const src = symbolSrc(`{${symbol}}`);
      const icon = src
        ? `<img class="mtg-symbol mtg-symbol-inline" src="${escapeHtml(src)}" alt="{${symbol}}" title="{${symbol}}" />`
        : symbol;
      parts.push(`${icon} x${count}`);
    }
  }
  const generic = Number(counts?.generic || 0);
  if (generic > 0) {
    const src = symbolSrc(`{${generic}}`);
    const icon = src
      ? `<img class="mtg-symbol mtg-symbol-inline" src="${escapeHtml(src)}" alt="{${generic}}" title="{${generic}}" />`
      : `Generic ${generic}`;
    parts.push(src ? icon : `${icon} x1`);
  }
  return parts.length > 0 ? parts.join(", ") : "No mana cost";
}

async function loadSymbolMap() {
  try {
    const resp = await fetch("/symbols/symbol-map.json", { cache: "no-store" });
    if (!resp.ok) return;
    symbolMap = await resp.json();
    if (currentState) {
      renderState(currentState);
    }
    if (typeof window.refreshDeckEditorSymbols === "function") {
      window.refreshDeckEditorSymbols();
    }
  } catch {
    symbolMap = {};
  }
}

function hideSetupPanel() {
  setupEl.classList.add("hidden");
  setupEl.hidden = true;
  setupEl.style.display = "none";
}

function showSetupPanel() {
  setupEl.classList.remove("hidden");
  setupEl.hidden = false;
  setupEl.style.display = "";
}

function syncSeedControls() {
  const useCustomSeed = q("useCustomSeed").checked;
  q("customSeedLabel").classList.toggle("hidden", !useCustomSeed);
  q("customSeed").disabled = !useCustomSeed;
}

// CR 407.1: is the host setting up a game played for ante? Read by
// deck-editor.js, which greys out decks holding ante cards while this is off
// (CR 407.3). Defaults to false — the checkbox starts unticked.
window.isPlayingForAnte = () => Boolean(q("playingForAnte")?.checked);

function showMenuPage(name) {
  const applyVisibility = () => {
    for (const [key, element] of Object.entries(menuPages)) {
      if (!element) continue;
      element.classList.toggle("hidden", key !== name);
      element.hidden = key !== name;
    }
  };
  const current = Object.values(menuPages).find(
    (el) => el && !el.classList.contains("hidden")
  );
  const next = menuPages[name];
  if (window.FX && current !== next) {
    FX.menuSwap(current, next, applyVisibility);
  } else {
    applyVisibility();
  }
}

function setVisible(active) {
  const wasActive = document.body.classList.contains("in-game");
  if (active) {
    hideSetupPanel();
  } else {
    showSetupPanel();
  }
  boardEl.classList.toggle("hidden", !active);
  document.body.classList.toggle("in-game", active);
  if (active && !wasActive && window.FX) FX.enterBoard(boardEl);
}

function closeStateSyncStream() {
  if (!stateSyncSource) return;
  stateSyncSource.close();
  stateSyncSource = null;
}

function openStateSyncStream() {
  closeStateSyncStream();
  if (!sessionId) return;

  const source = new EventSource(`/api/sessions/${sessionId}/events`);
  source.addEventListener("state", (event) => {
    let skipStale = false;
    // A rematch rebuilds the game with a fresh (shorter) log, so the monotonic-log
    // stale guard would wrongly discard it — bypass the guard for those resets too.
    try {
      const reason = JSON.parse(event.data)?.reason;
      if (reason === "undo" || reason === "rematch_start" || reason === "match_restart") skipStale = true;
      // A restart rebuilds the board for everyone — announce it to all seats
      // (including the initiator, whose own stream also delivers this event).
      if (reason === "match_restart") showMatchRestartAnnouncement();
    } catch {}
    getState(skipStale).catch(() => {
      // Ignore transient refresh failures; the stream will keep delivering future updates.
    });
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED && stateSyncSource === source) {
      stateSyncSource = null;
    }
  };
  stateSyncSource = source;
}

function resetToSetup(message = "Session not found. Start a new game.") {
  closeStateSyncStream();
  sessionId = null;
  seat = null;
  currentState = null;
  previousLifeBySeat = {};
  aiAutoStepInFlight = false;
  aiAutoStepRequestedStateKey = "";
  if (battlefieldCanvas) {
    battlefieldCanvas.destroy();
    battlefieldCanvas = null;
  }
  showSetupPanel();
  showMenuPage("home");
  boardEl.classList.add("hidden");
  aiControlsEl?.classList.add("hidden");
  // Clear any game-over overlay (e.g. the Defeat shown by conceding on Leave
  // Game) so it doesn't linger into the menu or a freshly hosted game.
  q("gameOverOverlay")?.classList.add("hidden");
  setJoinUrls("", "");
  updateActionHint(message, true);
}

function shouldShowAiControls(state) {
  const seatTypes = state?.seat_types || {};
  const values = Object.values(seatTypes);
  return values.length > 0 && values.every((t) => t === "ai");
}

function getAiStepStateKey(state) {
  if (!state) return "";
  const stackSize = Array.isArray(state.stack) ? state.stack.length : 0;
  const logSize = Array.isArray(state.log) ? state.log.length : 0;
  return `${state.turn_number || 0}:${state.current_turn}:${state.current_turn_phase}:${state.current_step}:${stackSize}:${logSize}`;
}

function getAutoPassStateKey(state) {
  if (!state) return "";
  const stackSize = Array.isArray(state.stack) ? state.stack.length : 0;
  const logSize = Array.isArray(state.log) ? state.log.length : 0;
  const combat = getCombatState(state);
  return `${state.turn_number || 0}:${state.current_turn}:${state.current_turn_phase}:${state.current_step}:${state.priority_player}:${stackSize}:${logSize}:${combat?.attackers_locked ? 1 : 0}:${combat?.blockers_locked ? 1 : 0}`;
}

// True when the current seat still owes a combat-damage assignment this step —
// a multi-blocked attacker's damage split (CR 510.1c) or the defending player's
// banding split (CR 702.22j). Combat damage can't resolve until it's submitted,
// so the server holds priority on that seat; the auto-pass helpers must treat it
// as a blocking prompt or they loop forever passing priority into a step that
// won't advance. (Band-blocker assignment, CR 702.22k, is covered separately by
// getBandBlockerInfo below.)
function combatDamageAssignmentPending(state = currentState) {
  if (!state || seat === null) return false;
  const combat = getCombatState(state);
  if (!combat || !isCombatStep(state, "combat_damage") || combat.damage_resolved) return false;
  if (state.banding_assignment && seat === state.banding_assignment.defender_seat
      && getDefenderBandingGroups(state).length > 0) return true;
  if (seat === state.current_turn && getAttackerAssignGroups(state).length > 0) return true;
  if (getMultiblockInfo(state)) return true;
  return false;
}

function hasBlockingPromptForAutoPass(state = currentState) {
  if (getCleanupDiscardInfo(state) || getUntapLandSelectionInfo(state) || getOptionalUntapInfo(state) || getUpkeepPayInfo(state) || getOptionalTriggerInfo(state) || getUpkeepPreventionInfo(state) || getDiscardSelectInfo(state) || getLengDiscardInfo(state) || getCommanderZoneChangeInfo(state) || getBalanceSelectInfo(state) || getSacrificeSelectInfo(state) || getOptionalPayInfo(state) || getOpponentDamageInfo(state) || getLampDrawInfo(state) || getOutsideGameDrawInfo(state) || getLandTypeChoiceInfo(state) || getEffectOrderInfo(state) || getBodyChoiceInfo(state) || getManaPaymentInfo(state) || getBandBlockerInfo(state) || getMultiblockInfo(state) || getKudzuReattachInfo(state) || getFaceDownCastInfo(state) || getTimeVaultInfo(state) || getWordOfCommandInfo(state) || getRagingRiverInfo(state) || getCamouflageInfo(state) || getIslandSanctuaryInfo(state) || combatDamageAssignmentPending(state)) return true;
  return !!(pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingModalChoice || pendingDiscardCost || pendingAbilityChoice || pendingChannel || pendingAttackTarget);
}

function shouldAutoPassUntilTurnEnd(state = currentState) {
  if (!state || seat === null) return false;
  if (!autoPassTurnEndEnabled) return false;
  if (autoPassMode === "self") {
    return state.current_turn === seat;
  }
  if (autoPassMode === "opponent") {
    return state.current_turn !== seat;
  }
  return false;
}

async function maybeAutoPassUntilTurnEnd(state = currentState) {
  if (!shouldAutoPassUntilTurnEnd(state) || autoPassTurnEndInFlight) {
    return;
  }

  if (hasBlockingPromptForAutoPass(state)) {
    autoPassTurnEndEnabled = false;
    autoPassMode = null;
    updateActionHint("Auto-pass paused: turn requires a manual selection.", true);
    return;
  }

  if (state.priority_player !== seat) {
    return;
  }

  const stateKey = getAutoPassStateKey(state);
  if (!stateKey || stateKey === autoPassTurnEndRequestedStateKey) {
    return;
  }

  autoPassTurnEndRequestedStateKey = stateKey;
  autoPassTurnEndInFlight = true;
  try {
    const combat = getCombatState(state);
    if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat?.attackers_locked) {
      await sendAction({
        seat,
        action: "declare_attackers",
        attacker_indices: [],
        target_seat: Number.isInteger(combat?.defending_player_index)
          ? combat.defending_player_index
          : firstLivingOpponentSeat(state, seat, "auto-pass empty declare_attackers"),
      });
      return;
    }

    if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && !combat?.blockers_locked) {
      // Camouflage replaces blocker declaration with pile assignment; an empty
      // division (every creature out of the piles) is the "no blocks" equivalent.
      if (combat?.camouflage_active) {
        await sendAction({ seat, action: "assign_camouflage_piles", camouflage_piles: {} });
      } else {
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: {} });
      }
      return;
    }

    await sendAction({ seat, action: "pass_priority" });
  } catch (error) {
    autoPassTurnEndEnabled = false;
    autoPassMode = null;
    const message = error instanceof Error ? error.message : "Auto-pass failed";
    updateActionHint(`Auto-pass paused: ${message}`, true);
  } finally {
    autoPassTurnEndInFlight = false;
  }
}

function isStackHoverHolding() {
  return stackCanvasHoverActive;
}

function isPriorityHeld() {
  return holdPriorityActive || stackClickHold !== null || isStackHoverHolding();
}

function _stackItemSig(item) {
  return `${item?.type || "spell"}|${item?.card?.name || item?.label || "?"}|${item?.caster_index}`;
}

// Array index of the click-held item in the current serialized stack, or null
// if nothing is held or the held item has left the stack (resolved/countered).
function getHeldStackArrayIndex() {
  if (!stackClickHold) return null;
  const idx = _currentStack.length - 1 - stackClickHold.bottomOffset;
  if (idx < 0 || idx >= _currentStack.length) return null;
  if (_stackItemSig(_currentStack[idx]) !== stackClickHold.sig) return null;
  return idx;
}

function resumeAutoPassAfterHold() {
  autoPassPriorityRequestedStateKey = "";
  autoPassDisabledPhaseRequestedStateKey = "";
  maybeAutoPassPriority(currentState);
  maybeAutoPassDisabledPhase(currentState);
}

function releaseStackClickHold(message) {
  if (!stackClickHold) return;
  stackClickHold = null;
  _refreshStackHoldVisuals();
  if (message) updateActionHint(message);
  if (!isPriorityHeld()) {
    resumeAutoPassAfterHold();
  }
}

async function maybeAutoPassPriority(state = currentState) {
  if (isPriorityHeld()) return;
  if (autoPassTurnEndEnabled) return;
  if (!state || seat === null) return;
  if (autoPassPriorityInFlight) return;
  if (state.priority_player !== seat) return;
  if (hasBlockingPromptForAutoPass(state)) return;
  if (combatPromptNeedsConfirmation(state)) return;

  // Only auto-pass after a spell or ability was cast — not during empty-stack priority windows.
  const stackSize = Array.isArray(state.stack) ? state.stack.length : 0;
  if (stackSize === 0) return;

  const stateKey = getAutoPassStateKey(state);
  if (!stateKey || stateKey === autoPassPriorityRequestedStateKey) return;

  autoPassPriorityRequestedStateKey = stateKey;
  autoPassPriorityInFlight = true;
  try {
    // Let the cast animation and stack dwell play out before resolving the
    // spell, so the game state never runs ahead of what's on screen.
    await waitForBattlefieldAnimations();
    const latest = currentState;
    if (
      isPriorityHeld() ||
      !latest ||
      latest.priority_player !== seat ||
      hasBlockingPromptForAutoPass(latest) ||
      combatPromptNeedsConfirmation(latest) ||
      !(Array.isArray(latest.stack) && latest.stack.length > 0)
    ) {
      return;
    }
    await sendAction({ seat, action: "pass_priority" });
  } catch {
    // Silently absorb; next state update will retry if needed.
  } finally {
    autoPassPriorityInFlight = false;
  }
}

async function maybeAutoPassDisabledPhase(state = currentState) {
  if (isPriorityHeld()) return;
  if (autoPassTurnEndEnabled) return;
  if (!state || seat === null) return;
  if (autoPassDisabledPhaseInFlight) return;
  if (state.priority_player !== seat) return;
  if (hasBlockingPromptForAutoPass(state)) return;

  const activeKey = getActiveStepKey(state);
  const isMyTurn = state.current_turn === seat;
  const shouldAutoPass = isMyTurn ? disabledPhases.has(activeKey) : opponentDisabledPhases.has(activeKey);
  if (!shouldAutoPass) return;

  const stackSize = Array.isArray(state.stack) ? state.stack.length : 0;
  if (stackSize > 0) return;

  const stateKey = getAutoPassStateKey(state);
  if (!stateKey || stateKey === autoPassDisabledPhaseRequestedStateKey) return;

  autoPassDisabledPhaseRequestedStateKey = stateKey;
  autoPassDisabledPhaseInFlight = true;
  try {
    // Don't advance the phase while a resolve/entrance animation is mid-flight.
    await waitForBattlefieldAnimations();
    const latest = currentState;
    if (
      isPriorityHeld() ||
      !latest ||
      latest.priority_player !== seat ||
      hasBlockingPromptForAutoPass(latest)
    ) {
      return;
    }
    const combat = getCombatState(state);
    if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat?.attackers_locked) {
      await sendAction({
        seat,
        action: "declare_attackers",
        attacker_indices: [],
        target_seat: Number.isInteger(combat?.defending_player_index)
          ? combat.defending_player_index
          : firstLivingOpponentSeat(state, seat, "auto-pass empty declare_attackers"),
      });
      return;
    }
    if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && !combat?.blockers_locked) {
      // Camouflage replaces blocker declaration with pile assignment; an empty
      // division (every creature out of the piles) is the "no blocks" equivalent.
      if (combat?.camouflage_active) {
        await sendAction({ seat, action: "assign_camouflage_piles", camouflage_piles: {} });
      } else {
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: {} });
      }
      return;
    }
    await sendAction({ seat, action: "pass_priority" });
  } catch {
    // Silently absorb
  } finally {
    autoPassDisabledPhaseInFlight = false;
  }
}

// Declaring attackers/blockers is a turn-based action with no priority window,
// so when the active/defending player has NO legal declaration to make (e.g. no
// untapped non-summoning-sick creatures), there is no UI affordance to advance:
// "Next Phase" needs priority (none here), and the combat OK button only appears
// when there's a real choice to confirm. Auto-submit the empty declaration so
// combat never deadlocks. Only fires when there are zero legal choices — when a
// real choice exists, the player declares it themselves via the combat UI.
async function maybeAutoAdvanceCombatDeclaration(state = currentState) {
  if (isPriorityHeld()) return;
  if (!state || seat === null) return;
  if (autoCombatDeclareInFlight) return;
  if (state.current_turn_phase !== "combat") return;
  if (hasBlockingPromptForAutoPass(state)) return;

  const combat = getCombatState(state);
  if (!combat) return;

  let actionBody = null;
  if (
    isCombatStep(state, "declare_attackers") &&
    seat === state.current_turn &&
    !combat.attackers_locked &&
    getValidAttackerIndices(state).length === 0
  ) {
    const defendingSeat = Number.isInteger(combat.defending_player_index)
      ? combat.defending_player_index
      : firstLivingOpponentSeat(state, seat, "auto-advance empty declare_attackers");
    actionBody = { seat, action: "declare_attackers", attacker_indices: [], target_seat: defendingSeat };
  } else if (
    isCombatStep(state, "declare_blockers") &&
    seat === combat.defending_player_index &&
    !combat.blockers_locked &&
    combat.camouflage_active
  ) {
    // Camouflage: the numbered pile buttons are the affordance; auto-submit an
    // empty division only when there is nothing left to divide.
    if (!getCamouflageInfo(state)) {
      actionBody = { seat, action: "assign_camouflage_piles", camouflage_piles: {} };
    }
  } else if (
    isCombatStep(state, "declare_blockers") &&
    seat === combat.defending_player_index &&
    !combat.blockers_locked &&
    getValidBlockerAssignments(state).length === 0
  ) {
    actionBody = { seat, action: "declare_blockers", blocker_pairs: {} };
  } else if (
    // I'm the attacker stalled on the declare-blockers turn-based step (no priority
    // window), and the defender is the AI (or there are no attackers to block).
    // Nudge the server to run the AI's blocks (or skip the empty step) — nothing
    // else triggers it. This holds whether or not blocks are already locked.
    isCombatStep(state, "declare_blockers") &&
    seat === state.current_turn &&
    !Number.isInteger(state.priority_player)
  ) {
    const seatTypes = state.seat_types || {};
    const defender = combat.defending_player_index;
    const noAttackers = !Array.isArray(combat.attackers) || combat.attackers.length === 0;
    const defenderIsAi = Number.isInteger(defender) ? seatTypes[defender] === "ai" : true;
    if (noAttackers || defenderIsAi) {
      actionBody = { seat, action: "next_phase" };
    }
  }
  if (!actionBody) return;

  const stateKey = getAutoPassStateKey(state);
  if (!stateKey || stateKey === autoCombatDeclareRequestedStateKey) return;

  autoCombatDeclareRequestedStateKey = stateKey;
  autoCombatDeclareInFlight = true;
  try {
    await waitForBattlefieldAnimations();
    const latest = currentState;
    // Re-validate against the freshest state before committing.
    if (
      isPriorityHeld() ||
      !latest ||
      latest.current_turn_phase !== "combat" ||
      latest.current_step !== state.current_step ||
      hasBlockingPromptForAutoPass(latest)
    ) {
      return;
    }
    await sendAction(actionBody);
  } catch {
    // Silently absorb; the next state update will retry if still stuck.
  } finally {
    autoCombatDeclareInFlight = false;
  }
}

// ---- Pacing: animation-aware delays for automatic actions ----
const AI_ACTION_DELAY_MS = 700; // breather between automatic AI actions
const ANIMATION_WAIT_TIMEOUT_MS = 8000; // never stall the game on a stuck animation
const ANIMATION_POLL_MS = 100;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Resolves once the battlefield canvas reports no in-flight card animations
// (cast flights, stack dwell, resolve/land effects), or after a safety timeout.
async function waitForBattlefieldAnimations() {
  const deadline = Date.now() + ANIMATION_WAIT_TIMEOUT_MS;
  while (battlefieldCanvas?.hasPendingAnimations() && Date.now() < deadline) {
    await sleep(ANIMATION_POLL_MS);
  }
}

function shouldAutoStepAi(state = currentState) {
  if (!state || !sessionId) return false;
  const seatTypes = state?.seat_types || {};
  if (seatTypes?.[state?.current_turn] !== "ai") return false;
  // In AI vs AI, respect the manual toggle; in human vs AI always auto-step.
  if (shouldShowAiControls(state)) {
    const toggle = q("aiAutoStepToggle");
    return toggle ? toggle.checked : false;
  }
  return true;
}

async function maybeAutoStepAi(state = currentState) {
  if (!shouldAutoStepAi(state) || aiAutoStepInFlight) {
    return;
  }

  // Don't auto-step while another player holds priority (AI must wait its turn).
  const priorityPlayer = state.priority_player;
  if (Number.isInteger(priorityPlayer) && priorityPlayer !== state.current_turn) {
    return;
  }

  const stateKey = getAiStepStateKey(state);
  if (!stateKey || stateKey === aiAutoStepRequestedStateKey) {
    return;
  }

  aiAutoStepRequestedStateKey = stateKey;
  aiAutoStepInFlight = true;
  try {
    // Pace the AI: let card animations finish playing, then take a short
    // breather so each action is watchable before the next one fires.
    await waitForBattlefieldAnimations();
    await sleep(AI_ACTION_DELAY_MS);
    if (!shouldAutoStepAi(currentState)) return;
    await sendAction({ seat: seat ?? 0, action: "ai_step" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "AI step failed";
    updateActionHint(`Auto AI step paused: ${message}`, true);
  } finally {
    aiAutoStepInFlight = false;
    // Re-check after the flag clears: if renderState was called while in-flight (e.g. due
    // to an SSE event arriving before the HTTP response), maybeAutoStepAi was blocked.
    // This ensures the AI continues acting on the most recent currentState.
    maybeAutoStepAi();
  }
}

// Oracle text plus any abilities granted by another permanent's static effect
// (Zombie Master's '{B}: Regenerate this permanent.') — the activation flow
// treats granted lines exactly like printed ones.
function activatedAbilityText(card) {
  if (!card || typeof card === "string") return "";
  const granted = Array.isArray(card.granted_abilities) ? card.granted_abilities : [];
  return [(card.oracle_text || "").trim(), ...granted].filter(Boolean).join("\n");
}

function hasActivatedAbility(card) {
  if (!card || typeof card === "string") return false;
  const text = activatedAbilityText(card);
  if (!text) return false;
  return /\{t\}|:\s*/i.test(text);
}

function getActivatedAbilityCost(card) {
  if (!card || typeof card === "string") return "";
  const text = activatedAbilityText(card);
  if (!text) return "";

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || !line.includes(":")) continue;
    const [cost] = line.split(":", 1);
    if (!cost || !cost.trim()) continue;
    return cost.trim();
  }

  return "";
}

function abilityCostRequiresTap(card) {
  return /\{t\}/i.test(getActivatedAbilityCost(card));
}

// The mana the insufficient-mana auto-tap flow must actually pay. For casting
// this is the card's mana cost; for an activated ability it is the ability's
// activation cost (e.g. Circle of Protection's {1}, not its {1}{W} card cost),
// carried on `pending.cost`. parseManaCostSymbols ignores {T}/commas, so a full
// cost string like Rod of Ruin's "{3}, {T}" is safe to pass through.
function pendingAutoTapCost(pending) {
  if (!pending) return "";
  if (typeof pending.cost === "string" && pending.cost) return pending.cost;
  return (pending.card && pending.card.mana_cost) || "";
}

function shouldPromptForActivationCost(costText) {
  const cleaned = (costText || "").replace(/[()\s]/g, "").toUpperCase();
  if (!cleaned) return false;
  return cleaned !== "{T}";
}

function parseManaCostSymbols(costText) {
  const required = { W: 0, U: 0, B: 0, R: 0, G: 0, C: 0, generic: 0 };
  const tokens = (costText || "").toUpperCase().match(/\{([^}]+)\}/g) || [];

  for (const token of tokens) {
    const symbol = token.slice(1, -1).trim();
    if (!symbol || symbol === "T") continue;
    if (/^\d+$/.test(symbol)) {
      required.generic += Number(symbol);
      continue;
    }
    if (symbol in required) {
      required[symbol] += 1;
    }
  }

  return required;
}

function manaPoolCanPayCost(manaPool, required) {
  const pool = manaPool || {};
  if ((pool.W || 0) < required.W) return false;
  if ((pool.U || 0) < required.U) return false;
  if ((pool.B || 0) < required.B) return false;
  if ((pool.R || 0) < required.R) return false;
  if ((pool.G || 0) < required.G) return false;
  if ((pool.C || 0) < required.C) return false;

  const remaining =
    (pool.W || 0) +
    (pool.U || 0) +
    (pool.B || 0) +
    (pool.R || 0) +
    (pool.G || 0) +
    (pool.C || 0) -
    required.W -
    required.U -
    required.B -
    required.R -
    required.G -
    required.C;

  return remaining >= required.generic;
}

function hasXCost(card) {
  return !!card && typeof card !== "string" && (card.mana_cost || "").toUpperCase().includes("{X}");
}

// ---------------------------------------------------------------------------
// Targeting: the backend (engine/legality.py) classifies what each spell/ability
// targets and enumerates every legal target, shipping a `target_spec` on each
// hand card (its cast target) and each of the viewer's own permanents (its
// activated-ability target). The frontend no longer parses oracle text for any
// of this — these predicates and helpers just read the supplied spec.
// ---------------------------------------------------------------------------

const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };

// The backend target spec for a hand card (cast) or a permanent (activation).
function targetSpecOf(card) {
  if (!card || typeof card !== "object") return EMPTY_TARGET_SPEC;
  return card.target_spec || EMPTY_TARGET_SPEC;
}

function specKind(card) {
  return targetSpecOf(card).kind;
}

function specHasTargets(card) {
  return (targetSpecOf(card).valid_targets || []).length > 0;
}

// Index a backend `valid_targets` list into the lookup structures the UI uses to
// validate clicks and highlight targets: permanent canvas keys ("seat-index"),
// targetable player seats, top-first stack indices, and graveyard descriptors.
function indexValidTargets(validTargets) {
  const validKeys = new Set();
  const validPlayerSeats = new Set();
  const validStackIndices = new Set();
  const validGraveyard = [];
  for (const t of (validTargets || [])) {
    if (!t) continue;
    if (t.kind === "permanent" && t.key) validKeys.add(t.key);
    else if (t.kind === "player" && Number.isInteger(t.seat)) validPlayerSeats.add(t.seat);
    else if (t.kind === "stack" && Number.isInteger(t.stack_index)) validStackIndices.add(t.stack_index);
    else if (t.kind === "graveyard") validGraveyard.push(t);
  }
  return { validTargets: validTargets || [], validKeys, validPlayerSeats, validStackIndices, validGraveyard };
}

// Base fields (target kind + indexed legal-target sets) shared by every pending
// target prompt. `validTargetsOverride` is used for a chosen modal mode, whose
// legal targets live on the mode rather than the card's cast spec.
function pendingTargetFields(card, validTargetsOverride = null) {
  const vt = validTargetsOverride ?? (targetSpecOf(card).valid_targets || []);
  return indexValidTargets(vt);
}

// --- Cast-time target predicates (read the hand card's cast spec) ---
function cardRequiresTargetPlayer(card) { return specKind(card) === "player"; }
function cardRequiresTargetLand(card) { return specKind(card) === "land"; }
function cardRequiresTargetGraveyardCreature(card) { return specKind(card) === "graveyard_creature"; }
function cardReanimatesOwnGraveyardOnly(card) { return !!targetSpecOf(card).own_graveyard_only; }
function cardRequiresTargetCreature(card) {
  const s = targetSpecOf(card);
  return s.kind === "creature" && !s.optional;
}
// Clone / Copy Artifact: an *optional* copy choice, offered only when something is
// available to copy (the backend leaves valid_targets empty otherwise).
function cardOffersCopyCreatureChoice(card) {
  const s = targetSpecOf(card);
  return s.kind === "creature" && !!s.optional && (s.valid_targets || []).length > 0;
}
function cardOffersCopyArtifactChoice(card) {
  const s = targetSpecOf(card);
  return s.kind === "artifact" && !!s.optional && (s.valid_targets || []).length > 0;
}
function cardRequiresTargetPermanent(card) {
  const k = specKind(card);
  return k === "permanent" || k === "spell_or_permanent";
}
// Lace recolor spells target a permanent OR a spell on the stack.
function cardRequiresTargetSpellOrPermanent(card) { return specKind(card) === "spell_or_permanent"; }
function cardRequiresTargetArtifact(card) {
  const s = targetSpecOf(card);
  return s.kind === "artifact" && !s.optional;
}
function cardRequiresTargetAny(card) { return specKind(card) === "any"; }
function cardRequiresDividedDamage(card) { return specKind(card) === "divided"; }
// "Up to N target creatures" (Basri's Acolyte). `max_targets` is the maximum the
// card names, derived by the backend from the compiled program — its absence is
// the ordinary one-target case, so this reads false for every other card without
// anything having to list them.
function severalTargetMaximum(card) {
  const max = targetSpecOf(card).max_targets;
  return Number.isInteger(max) && max > 1 ? max : null;
}
function cardRequiresSeveralTargets(card) { return severalTargetMaximum(card) !== null; }
function cardRequiresTargetStackSpell(card) { return specKind(card) === "stack"; }

// What a graveyard-return prompt is asking the player to click. Regrowth takes
// any card (any_card), Reconstruction an artifact card (card_type), Raise Dead
// and the reanimation spells a creature card.
function graveyardCardNoun(spec) {
  if (spec?.any_card) return "card";
  return `${spec?.card_type || "creature"} card`;
}

function startCastGraveyardCreatureTargetPrompt(card, castAction = "cast", extra = {}) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  const spec = targetSpecOf(card);
  const ownGraveyardOnly = !!spec.own_graveyard_only;
  const noun = graveyardCardNoun(spec);
  const verb = spec.any_card ? "return" : "reanimate";
  // "Return up to two target creature cards from your graveyard to your hand."
  // (Sanguine Indulgence): several slots and a maximum the caster may legally
  // stop short of. It stays *this* prompt rather than the several-permanents
  // one because the click surface is the zone-reveal panel, not the canvas —
  // and because `targetKind` is what keeps that panel auto-opened.
  const max = severalTargetMaximum(card);
  // An empty graveyard is not a reason to refuse the cast when the maximum may
  // be zero (CR 601.2c). The prompt opens with nothing clickable and a reachable
  // confirm, which is what announcing no targets looks like.
  if (!max && (spec.valid_targets || []).length === 0) {
    clearPendingHandCast();
    updateActionHint(`No ${noun}s in ${ownGraveyardOnly ? "your" : "any"} graveyard for ${cardName}.`, true);
    return;
  }
  pendingCastTarget = {
    card, cardName, targetKind: "graveyard_creature", castAction,
    ...(max ? { maxTargets: max, severalGraveyard: [] } : {}),
    ...pendingTargetFields(card),
    // Which permanent, and which of its abilities, when this prompt was opened
    // by an activation rather than a cast. The picker is identical — the card
    // clicked is in a graveyard either way — so only the action differs.
    ...extra,
  };
  renderActivationPrompt();
  renderBoard(currentState);
  // Auto-open the zone reveal panel on the graveyard(s) holding legal targets —
  // renderBoard just re-ran renderZoneCards, so the valid cards are already
  // marked .targeting-valid and clickable inside it.
  const targetSeats = [...new Set((pendingCastTarget.validGraveyard || []).map((t) => t.seat))];
  const sections = targetSeats.map((s) => zoneRevealSectionFor(s, "graveyard"));
  if (sections.length) openZoneReveal(sections, { auto: true });
}

function severalGraveyardHint() {
  const p = pendingCastTarget;
  if (!p || !p.severalGraveyard) return "";
  const n = p.severalGraveyard.length;
  return n === 0
    ? `Choose up to ${p.maxTargets} cards in your graveyard for ${p.cardName} (click each), then confirm. Choosing none is legal.`
    : `${n} of up to ${p.maxTargets} chosen.`;
}

function toggleSeveralGraveyardTarget(zoneSeat, index) {
  const p = pendingCastTarget;
  if (!p || !p.severalGraveyard) return;
  const legal = (p.validGraveyard || []).some((t) => t.seat === zoneSeat && t.index === index);
  if (!legal) {
    updateActionHint("That card isn't a valid target for the pending spell.", true);
    return;
  }
  const at = p.severalGraveyard.findIndex((t) => t.seat === zoneSeat && t.idx === index);
  if (at >= 0) {
    p.severalGraveyard.splice(at, 1);
  } else {
    if (p.severalGraveyard.length >= p.maxTargets) {
      updateActionHint(`${p.cardName} names at most ${p.maxTargets} targets — click one to deselect it.`, true);
      return;
    }
    p.severalGraveyard.push({ seat: zoneSeat, idx: index });
  }
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(severalGraveyardHint());
}

function confirmSeveralGraveyardTargets() {
  const p = pendingCastTarget;
  if (!p || !p.severalGraveyard) return;
  const { cardName, castAction, severalGraveyard } = p;
  // Indices, not ids: a card in a graveyard has no `permanent_id` to send. The
  // engine re-checks every slot against the graveyard as it stands at cast time
  // and refuses one that is no longer a legal choice, which is the protection an
  // id gives on the battlefield.
  const targetSeat = severalGraveyard.length ? severalGraveyard[0].seat : seat;
  if (!severalGraveyard.every((t) => t.seat === targetSeat)) {
    // The indices are positional on one `target_seat`; a spread across two
    // graveyards cannot be sent at all. No printed card names one, so this is a
    // refusal rather than a wire format.
    updateActionHint("Choose cards from one graveyard.", true);
    return;
  }
  const body = { seat, action: castAction || "cast", card_name: cardName, target_seat: targetSeat };
  if (severalGraveyard.length) {
    body.target_permanent_indices = severalGraveyard.map((t) => t.idx);
  }
  clearPendingCastTargeting();
  closeZoneRevealIfAutoOpened();
  updateActionHint(`Casting ${cardName}...`);
  sendAction(body)
    .then(() => updateActionHint(`Cast ${cardName}.`))
    .catch((e) => updateActionHint(e.message, true))
    .finally(() => clearPendingHandCast());
}

// Whether a serialized stack item (at top-first array index `arrayIndex`) is a
// legal target for the in-progress spell-target prompt — membership in the
// backend-supplied set of legal stack indices.
function isStackItemValidCastTarget(item, arrayIndex) {
  if (!pendingCastTarget) return false;
  // "stack" prompts target spells only; "spell_or_permanent" (lace) prompts allow
  // either a permanent or a stack spell, flagged via alsoStack.
  if (pendingCastTarget.targetKind !== "stack" && !pendingCastTarget.alsoStack) return false;
  return !!pendingCastTarget.validStackIndices && pendingCastTarget.validStackIndices.has(Number(arrayIndex));
}

// Battlefield permanents that are legal targets for the in-progress prompt, as
// "seat-index" canvas keys — straight from the backend's enumerated target list.
function getTargetablePermanentKeysForPrompt() {
  if (!pendingCastTarget || !pendingCastTarget.validKeys) return [];
  return [...pendingCastTarget.validKeys];
}

function activatedAbilityTargetsSelf(card) {
  if (!card || typeof card === "string") return false;
  // Abilities that grant keywords/buffs to "target creature" refer to the controller's
  // own creatures (e.g. Helm of Chatzuk: "Target creature gains banding until end of turn").
  const activatedLines = (card.oracle_text || "").split("\n")
    .filter((line) => /^\s*(\{[^}]+\}[,\s]*)+:/.test(line))
    .map((line) => line.toLowerCase());
  return activatedLines.some((line) =>
    line.includes("target creature gains banding") ||
    line.includes("target creature gains flying") ||
    line.includes("target creature gains") ||
    line.includes("untap target") ||
    line.includes("regenerate target") ||
    line.includes("target creature gets +")
  );
}

// --- Activated-ability target predicates (read the permanent's activation spec) ---
function activatedAbilityRequiresTargetLand(card) { return specKind(card) === "land"; }
function activatedAbilityTargetLandExcludesSwamp(card) { return !!targetSpecOf(card).exclude_swamp; }
function activatedAbilityRequiresTargetCreature(card) { return specKind(card) === "creature"; }
// Colour a "destroy target [colour] permanent" ability is restricted to, null for
// an uncoloured "destroy target permanent", or undefined when there's no such
// ability — preserving the original tri-state the callers depend on.
function activatedAbilityDestroyPermanentColor(card) {
  const s = targetSpecOf(card);
  if (s.kind !== "permanent") return undefined;
  return s.color_filter ?? null;
}
function activatedAbilityRequiresTargetPermanent(card) { return specKind(card) === "permanent"; }
// Aladdin: "Gain control of target artifact for as long as you control this creature."
function activatedAbilityRequiresTargetArtifact(card) { return specKind(card) === "artifact"; }
function activatedAbilityRequiresTargetAny(card) { return specKind(card) === "any"; }
function activatedAbilityRequiresTargetPlayer(card) { return specKind(card) === "player"; }
function activatedAbilityRequiresTargetCreatureGrant(card) { return specKind(card) === "creature"; }
function activatedAbilityRequiresTargetStackSpell(card) { return specKind(card) === "stack"; }

function cardRequiresManaColorChoice(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  // "…protection from the color of your choice" (Feat of Resistance) rides the
  // same one-shot colour prompt: CR 609.3 makes the choice part of resolving
  // the spell, and it reaches the engine as mana_color exactly as the
  // any-one-color mana clauses do.
  return (
    text.includes("any one color")
    || text.includes("one mana of any color")
    || text.includes("the color of your choice")
  );
}

function cardRequiresCastColorChoice(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  // Sleight of Mind: "replacing all instances of one color word with another."
  if (text.includes("replacing all instances of one color word with another")) return true;
  // Magical Hack: "replacing all instances of one basic land type with another."
  // Each chosen color maps to a basic land type (W=Plains, U=Island, B=Swamp,
  // R=Mountain, G=Forest), passed to the engine as the new_color.
  if (text.includes("replacing all instances of one basic land type with another")) return true;
  return false;
}

const LAND_TYPE_BY_SYMBOL = { W: "plains", U: "island", B: "swamp", R: "mountain", G: "forest" };

// Magical Hack replaces an existing basic land type word — the "from" choices
// are limited to land words actually present on the target (its land type,
// override, oracle text or granted/printed landwalk keywords).
function landWordOptionsForTarget(perm) {
  if (!perm || typeof perm === "string") return [];
  const haystack = [
    perm.land_type_override || "",
    perm.type || "",
    perm.oracle_text || "",
    ...(Array.isArray(perm.keywords) ? perm.keywords : []),
  ]
    .join(" ")
    .toLowerCase();
  return MANA_COLOR_OPTIONS.filter((o) => haystack.includes(LAND_TYPE_BY_SYMBOL[o.symbol]));
}

function getDualLandColors(card) {
  if (!card || typeof card === "string") return null;
  const produced = Array.isArray(card.produced_mana) ? card.produced_mana.map((s) => s.toUpperCase()) : [];
  return produced.length >= 2 ? produced : null;
}

function xSpendColorForCard(card) {
  // "Spend only black mana on X." (Drain Life) — X may only be paid in one color.
  if (!card || typeof card === "string") return null;
  const m = (card.oracle_text || "").toLowerCase().match(/spend only (white|blue|black|red|green) mana on x/);
  if (!m) return null;
  return { white: "W", blue: "U", black: "B", red: "R", green: "G" }[m[1]] || null;
}

function getMaxAffordableX(manaPool, manaCost, card = null) {
  const pool = manaPool || {};
  const cost = parseManaCostSymbols(manaCost || "");
  const xColor = xSpendColorForCard(card);
  const totalMana = MANA_ORDER.reduce((sum, symbol) => sum + Number(pool[symbol] || 0), 0);
  const fixedCost = cost.W + cost.U + cost.B + cost.R + cost.G + cost.C + cost.generic;
  const maxPossible = Math.max(0, totalMana - fixedCost);

  for (let candidate = maxPossible; candidate >= 0; candidate -= 1) {
    const trial = xColor
      ? { ...cost, [xColor]: (cost[xColor] || 0) + candidate }
      : { ...cost, generic: cost.generic + candidate };
    if (manaPoolCanPayCost(pool, trial)) {
      return candidate;
    }
  }

  return 0;
}

function inferLandProducedMana(perm) {
  if (Array.isArray(perm.produced_mana) && perm.produced_mana.length > 0) {
    return perm.produced_mana.map((s) => s.toUpperCase());
  }
  const type = (perm.type || "").toLowerCase();
  const symbols = [];
  if (type.includes("plains")) symbols.push("W");
  if (type.includes("island")) symbols.push("U");
  if (type.includes("swamp")) symbols.push("B");
  if (type.includes("mountain")) symbols.push("R");
  if (type.includes("forest")) symbols.push("G");
  return symbols;
}

function computeAutoTapLands(manaCost, currentManaPool, battlefield) {
  const required = parseManaCostSymbols(manaCost || "");
  const pool = { W: 0, U: 0, B: 0, R: 0, G: 0, C: 0, ...currentManaPool };
  const toTap = [];

  const untapped = [];
  for (let i = 0; i < (battlefield || []).length; i++) {
    const perm = battlefield[i];
    if (!(perm.type || "").toLowerCase().includes("land")) continue;
    if (perm.tapped) continue;
    const produces = inferLandProducedMana(perm);
    if (produces.length > 0) untapped.push({ index: i, produces, used: false });
  }

  // Satisfy specific color requirements first
  for (const color of ["W", "U", "B", "R", "G", "C"]) {
    let deficit = Math.max(0, (required[color] || 0) - (pool[color] || 0));
    for (const land of untapped) {
      if (deficit <= 0) break;
      if (land.used || !land.produces.includes(color)) continue;
      land.used = true;
      toTap.push(land.index);
      pool[color] = (pool[color] || 0) + 1;
      deficit--;
    }
  }

  // Satisfy generic mana with remaining untapped lands
  const totalPool = MANA_ORDER.reduce((sum, c) => sum + (pool[c] || 0), 0);
  const totalRequired = MANA_ORDER.reduce((sum, c) => sum + (required[c] || 0), 0) + (required.generic || 0);
  let genericDeficit = Math.max(0, totalRequired - totalPool);
  for (const land of untapped) {
    if (genericDeficit <= 0) break;
    if (land.used) continue;
    land.used = true;
    toTap.push(land.index);
    genericDeficit--;
  }

  return toTap;
}

function canAutoTapSatisfyCost(manaCost, currentManaPool, battlefield) {
  const required = parseManaCostSymbols(manaCost || "");
  const pool = { W: 0, U: 0, B: 0, R: 0, G: 0, C: 0, ...currentManaPool };

  const untapped = [];
  for (const perm of (battlefield || [])) {
    if (!(perm.type || "").toLowerCase().includes("land")) continue;
    if (perm.tapped) continue;
    const produces = inferLandProducedMana(perm);
    if (produces.length > 0) untapped.push({ produces, used: false });
  }

  for (const color of ["W", "U", "B", "R", "G", "C"]) {
    let deficit = Math.max(0, (required[color] || 0) - (pool[color] || 0));
    for (const land of untapped) {
      if (deficit <= 0) break;
      if (land.used || !land.produces.includes(color)) continue;
      land.used = true;
      pool[color] = (pool[color] || 0) + 1;
      deficit--;
    }
    if (deficit > 0) return false;
  }

  const totalPool = MANA_ORDER.reduce((sum, c) => sum + (pool[c] || 0), 0);
  const totalRequired = MANA_ORDER.reduce((sum, c) => sum + (required[c] || 0), 0) + (required.generic || 0);
  const genericDeficit = Math.max(0, totalRequired - totalPool);
  const unusedLands = untapped.filter(l => !l.used).length;
  return genericDeficit <= unusedLands;
}

async function performAutoTap() {
  if (!pendingAutoTap) return;
  const pending = pendingAutoTap;
  pendingAutoTap = null;
  renderActivationPrompt();

  try {
    const me = getCurrentPlayerState();
    if (!me) throw new Error("Cannot read player state.");

    const landIndices = computeAutoTapLands(pendingAutoTapCost(pending), me.mana_pool, me.battlefield);
    if (landIndices.length > 0) {
      updateActionHint(`Auto-tapping ${landIndices.length} land(s)...`);
      for (const permanentIndex of landIndices) {
        await sendAction(withPermanentId(
          { seat, action: "tap", permanent_index: permanentIndex },
          "permanent_id", seat, permanentIndex,
        ));
      }
    }

    await sendAction(pending.actionBody);
    updateActionHint(`Cast ${pending.cardName}.`);
  } catch (e) {
    updateActionHint(e.message, true);
  } finally {
    clearPendingHandCast();
  }
}

function formatManaSymbols(counts) {
  const parts = [];
  for (const symbol of ["W", "U", "B", "R", "G", "C"]) {
    const count = Number(counts?.[symbol] || 0);
    if (count > 0) {
      parts.push(`${symbol}${count > 1 ? ` x${count}` : ""}`);
    }
  }
  if (Number(counts?.generic || 0) > 0) {
    parts.push(`Generic x${counts.generic}`);
  }
  return parts.length > 0 ? parts.join(", ") : "No mana cost";
}

function getCurrentPlayerState(state = currentState) {
  if (state === null || seat === null) return null;
  return state.players?.[seat] || null;
}

// --- stable permanent identity ------------------------------------------
// Every battlefield card in the state payload carries an `id`: the server's
// stable handle on that permanent, unique across all seats and unchanged for as
// long as it is on the battlefield (a card that leaves and comes back gets a
// new one — CR 400.7).
//
// A battlefield *index* is not a handle. It is a slot in an array, and this
// client acts on a board it last polled some hundreds of milliseconds ago: if
// anything left the battlefield in between, every later slot shifted and the
// index this click carries now names a different permanent. Actions therefore
// send the id **beside** the index. The server prefers the id, and refuses a
// stale one rather than quietly falling back to the slot — which is the bug the
// id exists to prevent.

function permanentIdAt(seatIndex, permanentIndex, state = currentState) {
  if (!Number.isInteger(seatIndex) || !Number.isInteger(permanentIndex)) return null;
  const card = state?.players?.[seatIndex]?.battlefield?.[permanentIndex];
  const pid = card && typeof card === "object" ? card.id : null;
  return Number.isInteger(pid) ? pid : null;
}

/** Add `field` to `body` when the permanent at (seatIndex, permanentIndex) has
 *  a stable id. Returns `body`, so it reads inline at the call site. */
function withPermanentId(body, field, seatIndex, permanentIndex, state = currentState) {
  const pid = permanentIdAt(seatIndex, permanentIndex, state);
  if (pid !== null) body[field] = pid;
  return body;
}

function getCleanupDiscardInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_phase !== "cleanup") return null;
  const info = state.cleanup_discard;
  if (info && Number(info.required_count || 0) > 0) {
    return info;
  }

  // Fallback for stale/partial state payloads: infer cleanup requirement locally.
  const me = state.players?.[seat];
  const hand = Array.isArray(me?.hand) ? me.hand : [];
  const requiredCount = Math.max(0, hand.length - 7);
  if (requiredCount <= 0) return null;

  return {
    required_count: requiredCount,
    selected_indices: [],
    selected_count: 0,
    inferred: true,
  };
}

function getUntapLandSelectionInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_step !== "untap") return null;
  if (state.current_turn !== seat) return null;

  const info = state.untap_land_selection;
  if (info && Number(info.max_count || 0) > 0) {
    return info;
  }

  return null;
}

function getUpkeepPayInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_step !== "upkeep") return null;
  if (state.current_turn !== seat) return null;

  const info = state.upkeep_pay;
  if (!info || !Array.isArray(info.pending) || info.pending.length === 0) return null;
  return info;
}

function getOptionalTriggerInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_step !== "upkeep") return null;
  if (state.current_turn !== seat) return null;

  const info = state.optional_trigger;
  if (!info || !Array.isArray(info.pending) || info.pending.length === 0) return null;
  return info;
}

function getUpkeepPreventionInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_step !== "upkeep") return null;
  if (state.current_turn !== seat) return null;

  const info = state.upkeep_mana_prevention;
  if (!info || !Array.isArray(info.pending) || info.pending.length === 0) return null;
  return info;
}

function getIslandSanctuaryInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_turn !== seat) return null;
  return state.island_sanctuary_pending ? true : null;
}

function getPregameInfo(state = currentState) {
  const info = state?.pregame;
  if (!info || !info.phase) return null;
  return info;
}

function getSearchLibraryInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.search_library;
  if (!info) return null;
  if (info.caster_seat !== seat) return null;
  return info;
}

function getSearchExileInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.search_exile;
  if (!info) return null;
  if (info.caster_seat !== seat) return null;
  return info;
}

function getDiscardSelectInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.discard_select;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  return info;
}

function getLengDiscardInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.leng_discard;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  return info;
}

function getCommanderZoneChangeInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.commander_zone_change;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  return info;
}

function getBalanceSelectInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.balance_select;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  return info;
}

function getSacrificeSelectInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.sacrifice_select;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  if (!Array.isArray(info.permanents) || info.permanents.length === 0) return null;
  return info;
}

function getOptionalPayInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.optional_pay;
  if (!info || !Array.isArray(info.pending) || info.pending.length === 0) return null;
  return info;
}

// CR 616.1e: two or more replacement/prevention effects are attempting to modify
// one event, and the affected player picks which applies first. The event has
// not happened yet — nothing is applied until this is answered.
function getEffectOrderInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.effect_order;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  if (!Array.isArray(info.options) || info.options.length < 2) return null;
  return info;
}

function getLandTypeChoiceInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.land_type_choice;
  if (!info || !Array.isArray(info.options) || info.options.length === 0) return null;
  return info;
}

// Black Vise / Jihad: the "as this enters, choose an opponent [and a color]" prompt.
function getEnterChoiceInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.enter_choice;
  if (!info || !Array.isArray(info.opponents) || info.opponents.length === 0) {
    enterChoiceSelectedColor = null;
    return null;
  }
  return info;
}

// Primal Clay: "As this creature enters, it becomes your choice of <body>."
function getBodyChoiceInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.body_choice;
  if (!info || !Array.isArray(info.options) || info.options.length === 0) return null;
  return info;
}

// Drop of Honey: the tie-break choice among creatures tied for least power.
function getLeastPowerChoiceInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.least_power_choice;
  if (!info || !Array.isArray(info.candidates) || info.candidates.length === 0) return null;
  return info;
}

// Liliana's Scrounger: which planeswalker receives the loyalty counter.
function getLoyaltyRecipientInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.loyalty_recipient;
  if (!info || !Array.isArray(info.candidates) || info.candidates.length === 0) return null;
  return info;
}

function getManaPaymentInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.mana_payment;
  if (!info) return null;
  return info;
}

function getKudzuReattachInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.kudzu_reattach;
  if (!info || !Array.isArray(info.lands) || info.lands.length === 0) return null;
  return info;
}

function getFaceDownCastInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.face_down_cast;
  if (!info || !Array.isArray(info.choices) || info.choices.length === 0) return null;
  return info;
}

function getTimeVaultInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.time_vault;
  if (!info || !Array.isArray(info.permanents) || info.permanents.length === 0) return null;
  return info;
}

function getWordOfCommandInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.word_of_command;
  if (!info || !Array.isArray(info.choices) || info.choices.length === 0) return null;
  return info;
}

// Old Man of the Sea: the start-of-turn "may choose not to untap" choice.
function getOptionalUntapInfo(state = currentState) {
  if (!state || seat === null) return null;
  if (state.current_turn !== seat) return null;
  const info = state.optional_untap;
  if (!info || !Array.isArray(info.permanents) || info.permanents.length === 0) return null;
  return info;
}

// Cuombajj Witches: the opposing chooser picks any target for the second damage.
function getOpponentDamageInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.opponent_damage_choice;
  if (!info || !Array.isArray(info.valid_targets)) return null;
  return info;
}

// Aladdin's Lamp: pick which of the revealed top cards to draw.
function getLampDrawInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.lamp_draw;
  if (!info || !Array.isArray(info.card_names) || info.card_names.length === 0) return null;
  return info;
}

// Ring of Ma'rûf: pick a card you own from outside the game (your sideboard) to
// put into your hand instead of drawing.
function getOutsideGameDrawInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.outside_game_draw;
  if (!info || !Array.isArray(info.card_names) || info.card_names.length === 0) return null;
  return info;
}

function getRagingRiverInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.raging_river;
  if (!info) return null;
  if (!Array.isArray(info.divide_creatures) && !Array.isArray(info.label_attackers)) return null;
  return info;
}

// Camouflage: the defending player's pending pile division. Server-built, only
// present for the human defender while blocks are unlocked and creatures remain.
function getCamouflageInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.camouflage;
  if (!info || info.defender_seat !== seat) return null;
  if (!Array.isArray(info.divide_creatures) || info.divide_creatures.length === 0) return null;
  return info;
}

function getReorderLibraryInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.reorder_library;
  if (!info) return null;
  if (info.caster_seat !== seat) return null;
  return info;
}

function getHandRevealInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.hand_reveal;
  if (!info) return null;
  if (info.viewer_seat !== seat) return null;
  return info;
}

// ---------------------------------------------------------------------------
// Prompt board targeting
// ---------------------------------------------------------------------------
// Prompts that choose permanents and/or players are answered on the board — the
// legal permanents glow like spell targets, the legal player pills glow gold —
// instead of listing card names as buttons in the prompt panel. One descriptor
// per prompt says what may be clicked and what a click submits, and the click
// handlers (canvas cards, player pills) plus the render loop all read it, so a
// prompt joins the flow by adding a branch to getPromptBoardTargeting below.

// Fields:
//   permanentKeys  "<seat>-<index>" battlefield keys that may be clicked
//   playerSeats    seats whose name/life pill may be clicked
//   selectedKeys   permanents already picked (multi-pick prompts), for the
//                  canvas' "selected" highlight
//   onPermanent / onPlayer  what a legal click submits
//   fallThroughOnInvalid    true when clicking anything else keeps its normal
//                  meaning (the backend still allows other actions meanwhile)
//   invalidHint    message shown for an illegal click that doesn't fall through
function promptTargeting(spec) {
  return {
    permanentKeys: new Set(spec.permanentKeys || []),
    playerSeats: new Set(spec.playerSeats || []),
    selectedKeys: spec.selectedKeys || [],
    onPermanent: spec.onPermanent || (() => {}),
    onPlayer: spec.onPlayer || (() => {}),
    fallThroughOnInvalid: !!spec.fallThroughOnInvalid,
    invalidHint: spec.invalidHint || "That isn't a legal choice for this prompt.",
  };
}

// Submit a prompt answer, surfacing a rejection as an action hint rather than an
// unhandled rejection (board clicks have no button to disable on failure).
function submitPromptAction(body) {
  sendAction(body).catch((e) => updateActionHint(e.message, true));
}

// Re-render the prompt panel and the board after a board click changed an
// in-progress multi-pick selection (the counts live in the panel, the
// highlights on the canvas).
function refreshPromptSelection(state = currentState) {
  renderActivationPrompt();
  renderBoard(state);
}

// The board-targeting descriptor for the prompt currently on screen, or null.
// The order below mirrors renderActivationPrompt's dispatch so the highlights
// always belong to the prompt the player is actually looking at: every prompt
// that outranks a board-targeted one bails out with null.
function getPromptBoardTargeting(state = currentState) {
  if (!state || seat === null) return null;
  if (getPregameInfo(state)) return null;
  if (getTimeVaultInfo(state)) return null;
  if (getCleanupDiscardInfo(state)) return null;
  // Constrained untap (Winter Orb / Smoke) is already board-driven through its
  // own untap_select action — see the canvas click handler.
  if (getUntapLandSelectionInfo(state)) return null;

  // Old Man of the Sea: toggle which permanents stay tapped, then confirm.
  const optionalUntapInfo = getOptionalUntapInfo(state);
  if (optionalUntapInfo) {
    const permanents = optionalUntapInfo.permanents || [];
    return promptTargeting({
      permanentKeys: permanents.map((p) => `${seat}-${Number(p.index)}`),
      selectedKeys: optionalUntapKeepSelection.map((idx) => `${seat}-${idx}`),
      onPermanent: (_targetSeat, idx) => {
        const at = optionalUntapKeepSelection.indexOf(idx);
        if (at >= 0) optionalUntapKeepSelection.splice(at, 1);
        else optionalUntapKeepSelection.push(idx);
        refreshPromptSelection(state);
      },
      invalidHint: "That permanent untaps normally — pick one of the highlighted ones.",
    });
  }

  // Cuombajj Witches: the opposing chooser picks any target (player or creature).
  const opponentDamageInfo = getOpponentDamageInfo(state);
  if (opponentDamageInfo) {
    const permanentKeys = [];
    const playerSeats = [];
    for (const t of opponentDamageInfo.valid_targets || []) {
      if (t.kind === "player") playerSeats.push(Number(t.seat));
      else if (t.kind === "permanent") permanentKeys.push(`${t.seat}-${t.index}`);
    }
    return promptTargeting({
      permanentKeys,
      playerSeats,
      onPermanent: (targetSeat, idx) =>
        submitPromptAction({
          seat,
          action: "opponent_damage_choose",
          target_seat: targetSeat,
          target_permanent_index: idx,
        }),
      onPlayer: (targetSeat) =>
        submitPromptAction({ seat, action: "opponent_damage_choose", target_seat: targetSeat }),
      invalidHint: `That isn't a legal target for ${opponentDamageInfo.card_name}'s damage.`,
    });
  }

  if (getLampDrawInfo(state) || getOutsideGameDrawInfo(state)) return null;
  if (getUpkeepPayInfo(state)) return null;

  // A target-bearing upkeep trigger (Vesuvan Doppelganger's re-copy, Erhnam
  // Djinn's forestwalk grant, Serendib Djinn's land sacrifice) picks its
  // permanent off the board — `needs_target` names the kind to highlight.
  const optionalTriggerInfo = getOptionalTriggerInfo(state);
  if (optionalTriggerInfo) {
    const current = (optionalTriggerInfo.pending || [])[0];
    const targets = Array.isArray(current?.valid_targets) ? current.valid_targets : [];
    if (!current?.needs_target || targets.length === 0) return null;
    return promptTargeting({
      permanentKeys: targets.map((t) => `${t.seat}-${t.index}`),
      onPermanent: (targetSeat, idx) =>
        submitPromptAction({
          seat,
          action: "resolve_optional_trigger",
          card_name: current.card_name,
          accept: true,
          target_seat: targetSeat,
          target_permanent_index: idx,
        }),
      // Upkeep still allows tapping lands and activating abilities while the
      // trigger waits, so a click elsewhere keeps its normal meaning.
      fallThroughOnInvalid: true,
    });
  }

  if (getUpkeepPreventionInfo(state)) return null;
  if (getDiscardSelectInfo(state)) return null;
  if (getLengDiscardInfo(state) || getCommanderZoneChangeInfo(state)) return null;

  // Balance: the lands/creatures to sacrifice are picked on the board (the cards
  // to discard are picked in hand — see the balanceHandSelectable hand option).
  const balanceSelectInfo = getBalanceSelectInfo(state);
  if (balanceSelectInfo) {
    const owner = Number(balanceSelectInfo.player_seat);
    const need = {
      lands: balanceSelectInfo.lands_to_sacrifice || 0,
      creatures: balanceSelectInfo.creatures_to_sacrifice || 0,
    };
    // Lands and creatures index into the same battlefield array, so one map
    // resolves a clicked index to the section it belongs to.
    const kindByIndex = new Map();
    if (need.lands) {
      for (const land of balanceSelectInfo.lands || []) kindByIndex.set(Number(land.index), "lands");
    }
    if (need.creatures) {
      for (const c of balanceSelectInfo.creatures || []) kindByIndex.set(Number(c.index), "creatures");
    }
    return promptTargeting({
      permanentKeys: [...kindByIndex.keys()].map((idx) => `${owner}-${idx}`),
      selectedKeys: [...balanceSelection.lands, ...balanceSelection.creatures].map((idx) => `${owner}-${idx}`),
      onPermanent: (_targetSeat, idx) => {
        const kind = kindByIndex.get(idx);
        if (!kind) return;
        const picked = balanceSelection[kind];
        const at = picked.indexOf(idx);
        if (at >= 0) picked.splice(at, 1);
        else if (picked.length < need[kind]) picked.push(idx);
        refreshPromptSelection(state);
      },
      invalidHint: "Balance only takes the highlighted lands and creatures.",
    });
  }

  // Forced sacrifice (Lich, Lord of the Pit): pick `count` of your permanents.
  const sacrificeSelectInfo = getSacrificeSelectInfo(state);
  if (sacrificeSelectInfo) {
    const owner = Number(sacrificeSelectInfo.player_seat);
    const permanents = sacrificeSelectInfo.permanents || [];
    const need = Math.min(sacrificeSelectInfo.count || 0, permanents.length);
    return promptTargeting({
      permanentKeys: permanents.map((p) => `${owner}-${p.index}`),
      selectedKeys: sacrificeSelection.map((idx) => `${owner}-${idx}`),
      onPermanent: (_targetSeat, idx) => {
        const at = sacrificeSelection.indexOf(idx);
        if (at >= 0) sacrificeSelection.splice(at, 1);
        else if (sacrificeSelection.length < need) sacrificeSelection.push(idx);
        refreshPromptSelection(state);
      },
      invalidHint: "That permanent can't be sacrificed.",
    });
  }

  if (getOptionalPayInfo(state)) return null;
  if (getLandTypeChoiceInfo(state)) return null;

  // Black Vise / Jihad: "as this enters, choose an opponent [and a color]" — the
  // opponent is chosen by clicking their pill (the color keeps its buttons).
  const enterChoiceInfo = getEnterChoiceInfo(state);
  if (enterChoiceInfo) {
    return promptTargeting({
      playerSeats: (enterChoiceInfo.opponents || []).map((opp) => Number(opp.seat)),
      onPlayer: (targetSeat) => {
        const payload = { seat, action: "enter_choice_confirm", target_seat: targetSeat };
        if (enterChoiceInfo.needs_color) {
          payload.mana_color = enterChoiceSelectedColor || enterChoiceInfo.default_color || "W";
        }
        enterChoiceSelectedColor = null;
        submitPromptAction(payload);
      },
      invalidHint: "Choose one of the highlighted opponents.",
    });
  }

  // Drop of Honey: which of the creatures tied for least power is destroyed.
  const leastPowerChoiceInfo = getLeastPowerChoiceInfo(state);
  if (leastPowerChoiceInfo) {
    return promptTargeting({
      permanentKeys: (leastPowerChoiceInfo.candidates || []).map((c) => `${c.seat}-${c.index}`),
      onPermanent: (targetSeat, idx) =>
        submitPromptAction({
          seat,
          action: "least_power_choice_confirm",
          target_seat: targetSeat,
          target_permanent_index: idx,
        }),
      invalidHint: "Only the creatures tied for least power can be chosen.",
    });
  }

  // Liliana's Scrounger: which planeswalker the loyalty counter lands on.
  // Answered by *id*, not by seat+index: the ability names permanents that may
  // sit on either battlefield, and an index is positional on one seat.
  const loyaltyRecipientInfo = getLoyaltyRecipientInfo(state);
  if (loyaltyRecipientInfo) {
    const byKey = new Map(
      (loyaltyRecipientInfo.candidates || []).map((c) => [`${c.seat}-${c.index}`, c.id]),
    );
    return promptTargeting({
      permanentKeys: [...byKey.keys()],
      onPermanent: (targetSeat, idx) =>
        submitPromptAction({
          seat,
          action: "loyalty_recipient_confirm",
          target_permanent_id: byKey.get(`${targetSeat}-${idx}`),
        }),
      invalidHint: "Only a planeswalker the ability names can take the counter.",
    });
  }

  if (getManaPaymentInfo(state)) return null;

  // Kudzu: pick the land the Aura moves to.
  const kudzuReattachInfo = getKudzuReattachInfo(state);
  if (kudzuReattachInfo) {
    return promptTargeting({
      permanentKeys: (kudzuReattachInfo.lands || []).map((land) => `${seat}-${land.index}`),
      onPermanent: (_targetSeat, idx) =>
        submitPromptAction({ seat, action: "kudzu_reattach_confirm", target_permanent_index: idx }),
      invalidHint: "Kudzu must be attached to one of your lands.",
    });
  }

  return null;
}

// A cast or activation already choosing targets outranks a parked prompt (only
// the upkeep-trigger prompt lets a spell get started while it waits), so its
// targets stay the highlighted ones.
function activePromptBoardTargeting(state = currentState) {
  if (pendingCastTarget) return null;
  return getPromptBoardTargeting(state);
}

// Seats whose name/life pill is a legal click right now — a board-targeting
// prompt's players if one is open, otherwise the pending spell's.
function validPlayerTargetSeats(state = currentState) {
  const boardTargeting = activePromptBoardTargeting(state);
  if (boardTargeting?.playerSeats.size) return boardTargeting.playerSeats;
  return pendingCastTarget?.validPlayerSeats || null;
}

// ---------------------------------------------------------------------------
// Free-For-All (3-4 player) target-seat helpers.
//
// Every 2-player call site keeps its original `1 - seat` shortcut untouched.
// These helpers are only ever consulted when `state.players.length > 2`, so
// they add zero risk to the well-tested 2-player paths.
function livingOpponentSeats(state, viewerSeat) {
  if (!state || !Array.isArray(state.players) || !Number.isInteger(viewerSeat)) return [];
  return state.players
    .map((_, idx) => idx)
    .filter((idx) => idx !== viewerSeat && !state.players[idx]?.lost);
}

function isFfaState(state = currentState) {
  return !!(state && Array.isArray(state.players) && state.players.length > 2);
}

// Seat shown by the classic single-opponent header (#oppName / #oppLife /
// #oppHand): the only opponent in 2-player games, otherwise the seat whose
// battlefield quadrant is top-LEFT. Must stay in lockstep with
// _classicOppSeat() in battlefield-canvas.js (3 players: viewer's field spans
// the whole bottom, opponents sit top-left/top-right; 4 players: quadrants
// rotate viewer -> bottom-right -> top-left -> top-right).
function classicOppSeat(state, viewerSeat) {
  const n = Array.isArray(state?.players) ? state.players.length : 2;
  if (n <= 2) return viewerSeat === 0 ? 1 : 0;
  return (viewerSeat + (n === 3 ? 1 : 2)) % n;
}

// DOM id of the hand fan showing a seat's cards (every seat has one: the
// viewer's #selfHand, the classic opponent's #oppHand, and per-seat FFA
// corner fans built by renderFfaOpponentPanels).
function handContainerIdForSeat(state, viewerSeat, seatIdx) {
  if (seatIdx === viewerSeat) return "selfHand";
  if (seatIdx === classicOppSeat(state, viewerSeat)) return "oppHand";
  return `ffaHand_${seatIdx}`;
}

// Default opponent seat for flows where target_seat is a formality rather
// than a real choice: first living opponent seat, no prompt. Anything that
// genuinely targets a player runs through the prompt-panel targeting flows
// (startCastTargetPrompt / startCastAnyTargetPrompt / pendingAttackTarget)
// BEFORE these defaults are consulted — never window.prompt. Logs so any FFA
// gap here is discoverable.
function firstLivingOpponentSeat(state = currentState, viewerSeat = seat, context = "") {
  const candidates = livingOpponentSeats(state, viewerSeat);
  if (candidates.length > 0) return candidates[0];
  if (context) console.log(`FFA: no living opponent found for ${context}; falling back to 1 - seat`);
  return 1 - viewerSeat;
}

function getDefaultTargetSeat(cardName) {
  if (seat === null) return 1;
  if (["Ancestral Recall", "Healing Salve", "Stream of Life"].includes(cardName)) {
    return seat;
  }
  // Cards that really target a player never reach this default — the cast
  // paths intercept them with startCastTargetPrompt/startCastAnyTargetPrompt
  // first — so in FFA any living opponent works as the formal target_seat.
  if (isFfaState()) return firstLivingOpponentSeat(currentState, seat, `default target for ${cardName}`);
  return 1 - seat;
}

function getOpponentDefaultTargetSeat(cardName) {
  // Default target when the spell is being cast on the opponent's behalf
  // (debug-only "cast for free as opponent" flow).
  if (seat === null) return 0;
  const opponentSeat = isFfaState()
    ? firstLivingOpponentSeat(currentState, seat, "debug cast-as-opponent default target")
    : 1 - seat;
  if (["Ancestral Recall", "Healing Salve", "Stream of Life"].includes(cardName)) {
    return opponentSeat;
  }
  return seat;
}

// Whether a clicked target (battlefield permanent or player) is legal for the
// in-progress prompt. Legality is the backend's: membership in the enumerated
// valid-target sets attached to pendingCastTarget — no type/colour/text checks.
function isPendingCastTargetValidForCard(card, { targetSeat = null, zoneKind = "", permanentIndex = null } = {}) {
  if (!pendingCastTarget) return false;
  if (!Number.isInteger(targetSeat)) return false;
  if (!zoneKind) return false;

  // Player targets ("target player", "any target", divided face) are validated by
  // seat against the backend's targetable-player set, regardless of which zone
  // element (life pill / name) was clicked.
  if (pendingCastTarget.targetKind === "player") {
    return !!pendingCastTarget.validPlayerSeats && pendingCastTarget.validPlayerSeats.has(targetSeat);
  }

  if (zoneKind !== "battlefield" || !Number.isInteger(permanentIndex)) return false;
  return !!pendingCastTarget.validKeys && pendingCastTarget.validKeys.has(`${targetSeat}-${permanentIndex}`);
}

function findCardInCurrentHand(cardName) {
  const me = getCurrentPlayerState();
  if (!me || !Array.isArray(me.hand)) return null;
  return me.hand.find((card) => normalizeCardName(card) === cardName) || null;
}

function beginPendingHandCast(card, handIndex = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  // A fresh cast starts with no chosen mode; a modal prompt sets it later.
  pendingCastModeIndex = null;
  // A fresh cast is from the hand; a zone cast sets the zone right after.
  pendingCastFromZone = null;
  pendingCastHandCard = {
    cardName,
    handIndex: Number.isInteger(handIndex) && handIndex >= 0 ? handIndex : null,
  };
}

function clearPendingHandCast() {
  // While a multi-mode cast is collecting targets, each per-mode prompt ends by
  // calling sendAction — which captures instead of sending and opens the *next*
  // prompt. The caller's own .finally() then lands here, after that prompt is
  // already open, and clearing would take its card away. The collection's own
  // finish clears itself first, so this only ever holds mid-walk.
  if (pendingModeCollection) return;
  pendingCastHandCard = null;
  pendingModalChoice = null;
  pendingCastModeIndex = null;
  pendingCastFromZone = null;
  document.querySelectorAll(".casting-card").forEach((el) => el.classList.remove("casting-card"));
}

function isPendingHandCastCard(card, handIndex = null) {
  if (!pendingCastHandCard) return false;
  const cardName = normalizeCardName(card);
  if (!cardName || cardName !== pendingCastHandCard.cardName) {
    return false;
  }
  if (Number.isInteger(pendingCastHandCard.handIndex)) {
    return pendingCastHandCard.handIndex === handIndex;
  }
  return true;
}

function isAnyPromptActive(state = currentState) {
  if (getCleanupDiscardInfo(state)) return true;
  if (getUntapLandSelectionInfo(state)) return true;
  if (getUpkeepPayInfo(state)) return true;
  if (getOptionalTriggerInfo(state)) return true;
  if (getUpkeepPreventionInfo(state)) return true;
  if (getDiscardSelectInfo(state)) return true;
  if (getLengDiscardInfo(state) || getCommanderZoneChangeInfo(state)) return true;
  if (getBalanceSelectInfo(state)) return true;
  if (getOptionalPayInfo(state)) return true;
  if (getOptionalUntapInfo(state)) return true;
  if (getOpponentDamageInfo(state)) return true;
  if (getLampDrawInfo(state) || getOutsideGameDrawInfo(state)) return true;
  if (getEffectOrderInfo(state)) return true;
  if (getLandTypeChoiceInfo(state)) return true;
  if (getBodyChoiceInfo(state)) return true;
  if (getManaPaymentInfo(state)) return true;
  if (getBandBlockerInfo(state)) return true;
  if (getMultiblockInfo(state)) return true;
  if (getKudzuReattachInfo(state)) return true;
  if (getFaceDownCastInfo(state)) return true;
  if (getTimeVaultInfo(state)) return true;
  if (getWordOfCommandInfo(state)) return true;
  if (getRagingRiverInfo(state)) return true;
  if (getCamouflageInfo(state)) return true;
  if (shouldShowPriorityPrompt(state)) return true;
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingAutoTap || pendingModalChoice || pendingDiscardCost || pendingAbilityChoice || pendingChannel || pendingAttackTarget) return true;

  const hasValidAttackers = getValidAttackerIndices(state).length > 0;
  const hasValidBlockers = getValidBlockerAssignments(state).length > 0;
  const isDeclareAttackersPrompt = isCombatStep(state, "declare_attackers") && hasValidAttackers;
  const isDeclareBlockersPrompt = isCombatStep(state, "declare_blockers") && hasValidBlockers;
  return isDeclareAttackersPrompt || isDeclareBlockersPrompt;
}

function shouldShowPriorityPrompt(state = currentState) {
  if (!state || seat === null) return false;
  if (state.priority_player !== seat) return false;
  if (getCleanupDiscardInfo(state) || getUntapLandSelectionInfo(state) || getOptionalUntapInfo(state) || getUpkeepPayInfo(state) || getOptionalTriggerInfo(state) || getUpkeepPreventionInfo(state) || getDiscardSelectInfo(state) || getLengDiscardInfo(state) || getCommanderZoneChangeInfo(state) || getBalanceSelectInfo(state) || getSacrificeSelectInfo(state) || getOptionalPayInfo(state) || getOpponentDamageInfo(state) || getLampDrawInfo(state) || getOutsideGameDrawInfo(state) || getLandTypeChoiceInfo(state) || getEffectOrderInfo(state) || getBodyChoiceInfo(state) || getManaPaymentInfo(state) || getBandBlockerInfo(state) || getMultiblockInfo(state) || getKudzuReattachInfo(state) || getFaceDownCastInfo(state) || getTimeVaultInfo(state) || getWordOfCommandInfo(state) || getRagingRiverInfo(state) || getCamouflageInfo(state)) return false;

  // Combat declaration prompts own the prompt panel while declarations are pending.
  if (combatPromptNeedsConfirmation(state)) return false;

  const phase = state.current_turn_phase;
  if (phase === "precombat_main" || phase === "combat" || phase === "postcombat_main" || state.current_step === "end") {
    return true;
  }
  // Holding priority during another player's turn (e.g. a phase-rail hold at their
  // upkeep or draw step): the server only hands us priority at a step that grants
  // it, so priority_player === seat here means we have a genuine window to act or
  // pass. Surface the prompt at those steps too, otherwise the game silently
  // stalls with no visible reason.
  if (Number.isInteger(state.current_turn) && state.current_turn !== seat) {
    return true;
  }
  return false;
}

function combatNeedsManualDamageAssignment(state = currentState) {
  const blockers = getDisplayedBlockerLinks(state);
  const byAttacker = {};
  for (const pair of blockers) {
    const attackerIndex = Number(pair.attacker_index);
    if (!byAttacker[attackerIndex]) {
      byAttacker[attackerIndex] = [];
    }
    byAttacker[attackerIndex].push(Number(pair.blocker_index));
  }
  return Object.values(byAttacker).some((blockerIndices) => blockerIndices.length >= 2);
}

function combatPromptNeedsConfirmation(state = currentState) {
  if (!state || seat === null) return false;
  const combat = getCombatState(state);
  if (!combat || state.current_turn_phase !== "combat") return false;

  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn) {
    if (getValidAttackerIndices(state).length === 0) {
      return false;
    }
    return !combat.attackers_locked;
  }
  if (isCombatStep(state, "declare_blockers") && seat === combat.defending_player_index) {
    if (getValidBlockerAssignments(state).length === 0) {
      return false;
    }
    return !combat.blockers_locked;
  }
  return false;
}

async function handleUntapPromptOk() {
  if (!currentState || seat === null) return false;
  const untapInfo = getUntapLandSelectionInfo(currentState);
  if (!untapInfo) return false;
  await sendAction({ seat, action: "untap_confirm" });
  updateActionHint("Untap choices confirmed.");
  return true;
}

async function handleCombatPromptOk() {
  if (!currentState || seat === null) return false;
  const state = currentState;
  const combat = getCombatState(state);
  if (!combat || state.current_turn_phase !== "combat") return false;

  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat.attackers_locked) {
    if (getValidAttackerIndices(state).length === 0) {
      return false;
    }
    const declared = [...combatAttackerDraft];
    let defendingSeat = Number.isInteger(combat.defending_player_index) ? combat.defending_player_index : null;
    if (defendingSeat === null) {
      // 3+ player game with no single defender established yet: the attacking
      // player must choose which one opponent every declared attacker goes at
      // (MVP scope — no true per-attacker-defender picker). With more than one
      // living opponent, park the declaration and let the prompt panel offer a
      // button per candidate (see renderActivationPrompt's pendingAttackTarget
      // branch); the declaration is sent by confirmPendingAttackTarget.
      const candidates = isFfaState(state) ? livingOpponentSeats(state, seat) : [1 - seat];
      if (candidates.length > 1) {
        pendingAttackTarget = {
          attackerIndices: declared,
          band: !!(combatBandDraft && selectedAttackersCanBand(state)),
        };
        renderCombatControls(state); // hide the declare summary/Alpha Strike while picking
        renderActivationPrompt();
        return true;
      }
      defendingSeat = candidates.length === 1 ? candidates[0] : 1 - seat;
    }
    const declareBody = {
      seat,
      action: "declare_attackers",
      attacker_indices: declared,
      target_seat: defendingSeat,
    };
    // CR 702.22c: declare the selected attackers as a single band when requested.
    if (combatBandDraft && selectedAttackersCanBand(state)) {
      declareBody.bands = [declared];
    }
    await sendAction(declareBody);
    combatBandDraft = false;
    updateActionHint(
      `Attackers declared (${declared.length})${declareBody.bands ? " as a band" : ""}.` +
        " Players may now cast spells/activate abilities before blockers.",
    );
    return true;
  }

  if (isCombatStep(state, "declare_blockers") && seat === combat.defending_player_index && !combat.blockers_locked) {
    if (getValidBlockerAssignments(state).length === 0) {
      return false;
    }
    const blockerPairs = { ...combatBlockerDraft };
    await sendAction({ seat, action: "declare_blockers", blocker_pairs: blockerPairs });
    updateActionHint(
      `Blockers declared (${Object.keys(blockerPairs).length}). Players may now cast spells/activate abilities before damage.`,
    );
    return true;
  }

  return false;
}

// Send the attack declaration parked by handleCombatPromptOk once the player
// picks an opponent from the prompt-panel buttons.
async function confirmPendingAttackTarget(targetSeat) {
  const pending = pendingAttackTarget;
  pendingAttackTarget = null;
  if (!pending || !Number.isInteger(targetSeat)) {
    renderActivationPrompt();
    return;
  }
  const declareBody = {
    seat,
    action: "declare_attackers",
    attacker_indices: pending.attackerIndices,
    target_seat: targetSeat,
  };
  if (pending.band) declareBody.bands = [pending.attackerIndices];
  try {
    await sendAction(declareBody);
    combatBandDraft = false;
    updateActionHint(
      `Attackers declared (${pending.attackerIndices.length})${declareBody.bands ? " as a band" : ""}.` +
        " Players may now cast spells/activate abilities before blockers.",
    );
  } catch (e) {
    updateActionHint(e.message, true);
  }
  if (currentState) renderCombatControls(currentState);
  renderActivationPrompt();
}

async function handlePriorityPromptOk() {
  if (!currentState || seat === null) return false;
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingModalChoice || pendingDiscardCost || pendingAbilityChoice || pendingChannel || pendingAttackTarget) return false;
  if (!shouldShowPriorityPrompt(currentState)) return false;
  await sendAction({ seat, action: "pass_priority" });
  updateActionHint("Passed priority.");
  return true;
}

function applyCleanupPrompt(cleanupDiscard) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");
  const requiredCount = Number(cleanupDiscard.required_count || 0);
  const selectedCount = Number(cleanupDiscard.selected_count || 0);
  const remaining = Math.max(0, requiredCount - selectedCount);

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  title.textContent = "Cleanup discard required";
  body.textContent = "Select cards from your hand to discard. The turn will continue automatically once all required cards are selected.";
  steps.innerHTML = [
    `<div><strong>Selected ${selectedCount} of ${requiredCount}</strong> (${remaining} more to discard)</div>`,
    "<div>Action: click cards in your hand to select; click a highlighted card again to unselect it.</div>",
  ].join("");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;
}

function applyUntapPrompt(untapInfo) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");
  const maxCount = Number(untapInfo.max_count || 0);
  const selectedCount = Number(untapInfo.selected_count || 0);

  // Name the constrained type(s): Winter Orb restricts lands, Smoke restricts
  // creatures, and both can be active at once.
  const landConstrained = untapInfo.land_max != null;
  const creatureConstrained = untapInfo.creature_max != null;
  const noun = landConstrained && creatureConstrained
    ? "lands and creatures"
    : creatureConstrained
    ? "creatures"
    : "lands";
  const nounTitle = landConstrained && creatureConstrained
    ? "Permanents"
    : creatureConstrained
    ? "Creatures"
    : "Lands";

  panel.classList.remove("hidden");
  okBtn.classList.remove("hidden");
  customRow.classList.add("hidden");
  title.textContent = `Choose ${nounTitle} to Untap`;
  body.textContent = `Select tapped ${noun} (highlighted) to untap, then press OK.`;
  steps.innerHTML = [
    `<div>Maximum ${noun}: ${maxCount}</div>`,
    `<div>Selected: ${selectedCount}</div>`,
    `<div>Action: click your highlighted tapped ${noun} to toggle selection.</div>`,
  ].join("");
  cancelBtn.disabled = true;
  okBtn.disabled = false;
  customOkBtn.disabled = true;
}

function manaObjectToSymbolString(mana) {
  if (!mana || typeof mana !== "object") return "?";
  const parts = [];
  // Generic mana renders as a single numeric symbol ({4}), not four {generic}
  // tokens — the symbol map only has numeric icons, so {generic} would fall back
  // to literal text in the prompt.
  const generic = Number(mana.generic || 0);
  if (generic > 0) parts.push(`{${generic}}`);
  for (const [sym, count] of Object.entries(mana)) {
    if (sym === "generic") continue;
    const n = Number(count) || 0;
    for (let i = 0; i < n; i += 1) parts.push(`{${sym}}`);
  }
  return parts.join("") || "{0}";
}

function applyUpkeepPayPrompt(upkeepInfo) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const pending = upkeepInfo.pending || [];
  const current = pending[0];
  const cardName = current?.card_name || "Unknown";
  const manaStr = manaObjectToSymbolString(current?.mana);

  // The consequence of declining depends on the trigger: most cards are
  // sacrificed, but some (Force of Nature) deal damage to you instead.
  const kind = current?.kind || "";
  let declineLabel;
  if (kind === "upkeep_pay_or_deal_damage_to_controller") {
    const dmg = current?.damage || 0;
    declineLabel = `Take ${dmg} damage`;
  } else if (kind === "upkeep_pay_or_tap_and_sacrifice_opponent_land") {
    declineLabel = "Don't pay (tap & sacrifice a land)";
  } else if (kind === "upkeep_pay_to_untap_self" || kind === "upkeep_pay_to_untap_enchanted") {
    // No consequence — declining just leaves the permanent tapped.
    declineLabel = "Don't pay";
  } else if (kind === "upkeep_pay_to_gain_life") {
    // No consequence — declining just forgoes the life gain (Farmstead).
    declineLabel = "Don't pay";
  } else if (kind === "draw_step_life_loss_unless_pay") {
    // Nafs Asp: nothing is sacrificed — declining costs life at the draw step.
    declineLabel = `Lose ${current?.life_loss || 1} life`;
  } else {
    declineLabel = `Sacrifice ${escapeHtml(cardName)}`;
  }

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  title.textContent = "Upkeep Payment Required";
  body.textContent = kind === "draw_step_life_loss_unless_pay"
    ? `${cardName} damaged you — pay before your draw step or lose ${current?.life_loss || 1} life. Tap lands to generate mana, then pay or decline.`
    : `${cardName} requires a payment at the beginning of your upkeep. Tap lands to generate mana, then pay or decline.`;

  // Server-computed affordability (pool + untapped mana lands): a payment the
  // engine would reject is greyed out instead of offered.
  const canPay = upkeepInfo.can_pay?.[cardName] !== false;
  const payBtn = `<button type="button" class="prompt-choice-btn" id="upkeepPayBtn"${canPay ? "" : " disabled"}>Pay ${renderSymbolsInline(manaStr)}</button>`;
  const sacBtn = `<button type="button" class="prompt-choice-btn" id="upkeepSacBtn">${declineLabel}</button>`;
  const remaining = pending.length;
  steps.innerHTML = [
    `<div>Card: ${escapeHtml(cardName)}</div>`,
    `<div>Cost: ${renderSymbolsInline(manaStr)}</div>`,
    canPay ? "" : `<div class="prompt-warning">Not enough mana to pay.</div>`,
    `<div>Remaining decisions: ${remaining}</div>`,
    `<div class="prompt-choice-row">${payBtn}${sacBtn}</div>`,
  ].join("");

  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const payBtnEl = document.getElementById("upkeepPayBtn");
  const sacBtnEl = document.getElementById("upkeepSacBtn");
  if (payBtnEl) {
    payBtnEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "pay_upkeep", card_name: cardName });
    });
  }
  if (sacBtnEl) {
    sacBtnEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "sacrifice_upkeep", card_name: cardName });
    });
  }
}

function applyOptionalTriggerPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const pending = info.pending || [];
  const current = pending[0];
  const cardName = current?.card_name || "Unknown";
  const promptText = current?.prompt || `Resolve ${cardName}'s triggered ability?`;

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const mandatory = !!current?.mandatory;
  title.textContent = mandatory ? "Triggered Ability" : "Optional Trigger";
  body.textContent = promptText;

  // A target-bearing trigger (Vesuvan Doppelganger's upkeep re-copy, Erhnam
  // Djinn's forestwalk grant, Serendib Djinn's land sacrifice) takes its target
  // off the board: the legal permanents are highlighted and clicking one accepts
  // the trigger with that target (see getPromptBoardTargeting). Plain triggers
  // keep the simple Yes button. A mandatory trigger offers no decline — only the
  // board click.
  const needsTarget = !!current?.needs_target;
  const validTargets = Array.isArray(current?.valid_targets) ? current.valid_targets : [];
  const hasBoardTargets = needsTarget && validTargets.length > 0;
  // `needs_target` is the noun to highlight ("creature", "land", …).
  const targetNoun = typeof current?.needs_target === "string" ? current.needs_target : "permanent";
  const yesBtn = `<button type="button" class="prompt-choice-btn" id="optionalTriggerYesBtn">Yes</button>`;
  const noBtn = `<button type="button" class="prompt-choice-btn" id="optionalTriggerNoBtn">No</button>`;
  steps.innerHTML = [
    `<div>Card: ${escapeHtml(cardName)}</div>`,
    `<div>Remaining decisions: ${pending.length}</div>`,
    hasBoardTargets && mandatory
      ? `<div>Action: click a highlighted ${escapeHtml(targetNoun)} on the battlefield to choose it.</div>`
      : hasBoardTargets
      ? `<div>Action: click a highlighted ${escapeHtml(targetNoun)} on the battlefield to copy it, or decline.</div>` +
        `<div class="prompt-choice-row">${noBtn}</div>`
      : `<div class="prompt-choice-row">${yesBtn}${noBtn}</div>`,
  ].join("");

  const yesEl = document.getElementById("optionalTriggerYesBtn");
  const noEl = document.getElementById("optionalTriggerNoBtn");
  if (yesEl) {
    yesEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "resolve_optional_trigger", card_name: cardName, accept: true });
    });
  }
  if (noEl) {
    noEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "resolve_optional_trigger", card_name: cardName, accept: false });
    });
  }
}

// Power Leak: "you may pay any amount of mana ... prevent X of that damage." The
// player picks how much mana to pay (0..min(damage, available)); paying that much
// prevents that much of the Aura's damage.
function applyUpkeepPreventionPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const pending = info.pending || [];
  const current = pending[0];
  const cardName = current?.card_name || "Unknown";
  const damage = Math.max(0, Number(current?.damage) || 0);
  const available = Math.max(0, Number(info.available_mana) || 0);
  const maxPay = Math.min(damage, available);

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Pay to Prevent Damage";
  body.textContent = `${cardName} deals ${damage} damage to you. Pay mana to prevent that much.`;

  const buttons = [];
  for (let value = 0; value <= maxPay; value += 1) {
    buttons.push(
      `<button type="button" class="prompt-choice-btn" data-prevent-amount="${value}">Pay ${value}</button>`,
    );
  }
  steps.innerHTML = [
    `<div>Card: ${escapeHtml(cardName)}</div>`,
    `<div>Damage: ${damage} &nbsp; Available mana: ${available}</div>`,
    `<div class="prompt-choice-row">${buttons.join("")}</div>`,
  ].join("");

  steps.querySelectorAll("[data-prevent-amount]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const amount = Number(btn.dataset.preventAmount) || 0;
      await sendAction({
        seat,
        action: "pay_upkeep_prevention",
        card_name: cardName,
        amount,
      });
    });
  });
}

// Disrupting Scepter: the discarding player picks which card to discard. With
// Library of Leng a destination toggle lets them send it to the top of their
// library instead of the graveyard.
function applyDiscardSelectPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const allowTop = !!info.allow_top_of_library;
  const requiredCount = Math.max(1, Number(info.count || 1));
  const handSize = (info.cards || []).length;
  // Never quote a target the hand can't meet (Bazaar with fewer than three
  // cards left); the engine caps the requirement the same way.
  const target = Math.min(requiredCount, handSize);
  const selectedCount = discardSelection.length;
  const remaining = Math.max(0, target - selectedCount);

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = target === 1 ? "Discard a Card" : `Discard ${target} Cards`;
  const destLabel = allowTop
    ? discardToLibrarySelected
      ? "top of your library (Library of Leng)"
      : "your graveyard"
    : "your graveyard";
  body.textContent = `Select ${target} card(s) from your hand to discard to ${destLabel}.`;

  const toggleRow = allowTop
    ? `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="discardDestToggle">` +
      `Destination: ${discardToLibrarySelected ? "Top of Library" : "Graveyard"} (click to switch)</button></div>`
    : "";
  // Only the count, never the card list — the hand itself is the picker.
  steps.innerHTML = [
    `<div><strong>Selected ${selectedCount} of ${target}</strong> (${remaining} more to discard)</div>`,
    "<div>Action: click cards in your hand to select; click a highlighted card again to unselect it.</div>",
    toggleRow,
  ].join("");

  const toggleEl = document.getElementById("discardDestToggle");
  if (toggleEl) {
    toggleEl.addEventListener("click", () => {
      discardToLibrarySelected = !discardToLibrarySelected;
      applyDiscardSelectPrompt(info);
    });
  }
}

// A card in hand was clicked while a discard prompt is open: toggle it, and
// submit the whole batch once the required count is reached (confirm_discard
// requires all indices at once).
async function toggleDiscardSelection(handIndex) {
  const info = getDiscardSelectInfo();
  if (!info) return;
  const target = Math.min(Math.max(1, Number(info.count || 1)), (info.cards || []).length);
  const at = discardSelection.indexOf(handIndex);
  if (at >= 0) discardSelection.splice(at, 1);
  else if (discardSelection.length < target) discardSelection.push(handIndex);

  if (discardSelection.length < target) {
    const remaining = target - discardSelection.length;
    // renderBoard redraws the hand's highlights; the prompt panel is a separate
    // render pass, so the "N of M" line needs its own refresh.
    renderBoard(currentState);
    renderActivationPrompt();
    updateActionHint(`Select ${remaining} more card(s) to discard.`);
    return;
  }
  const indices = [...discardSelection];
  const toLibrary = !!info.allow_top_of_library && discardToLibrarySelected;
  discardSelection = [];
  discardToLibrarySelected = false;
  await sendAction({ seat, action: "discard_confirm", discard_indices: indices, to_library: toLibrary });
}

// Library of Leng: a card was discarded (random/forced/cleanup) and the optional
// replacement lets its controller put it on top of their library instead of the
// graveyard. One card at a time; two destination buttons.
function applyLengDiscardPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = (info.card && info.card.name) || "the card";
  const remaining = Number(info.remaining || 1);
  title.textContent = "Library of Leng";
  body.textContent =
    `You discarded ${cardName}. Put it on top of your library instead of your graveyard?` +
    (remaining > 1 ? ` (${remaining} cards to route)` : "");

  steps.innerHTML =
    `<div class="prompt-choice-row">` +
    `<button type="button" class="prompt-choice-btn" data-leng-dest="library">Top of Library</button>` +
    `<button type="button" class="prompt-choice-btn" data-leng-dest="graveyard">Graveyard</button>` +
    `</div>`;

  steps.querySelectorAll("[data-leng-dest]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const toLibrary = btn.dataset.lengDest === "library";
      await sendAction({ seat, action: "leng_discard_confirm", to_library: toLibrary });
      updateActionHint(
        toLibrary
          ? `${cardName} was put on top of your library (Library of Leng).`
          : `${cardName} was put into your graveyard.`,
      );
    });
  });
}

// CR 903.9: a commander was about to go somewhere else and its owner may put it
// into the command zone instead. One commander at a time; two destination
// buttons, like Library of Leng's above. The rule half is named because 903.9a
// (it died or was exiled) and 903.9b (it was about to be bounced or tucked)
// read very differently to a player.
function applyCommanderZoneChangePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = (info.card && info.card.name) || "your commander";
  const destination = String(info.destination || "graveyard");
  const remaining = Number(info.remaining || 1);
  const rule = info.rule === "903.9b" ? "903.9b" : "903.9a";
  const wording = rule === "903.9b"
    ? `${cardName} would be put into your ${destination}.`
    : `${cardName} is in your ${destination}.`;
  title.textContent = "Commander";
  body.textContent =
    `${wording} Put it into the command zone instead? (CR ${rule})` +
    (remaining > 1 ? ` (${remaining} to decide)` : "");

  const keepLabel = destination.charAt(0).toUpperCase() + destination.slice(1);
  steps.innerHTML =
    `<div class="prompt-choice-row">` +
    `<button type="button" class="prompt-choice-btn" data-commander-dest="command">Command Zone</button>` +
    `<button type="button" class="prompt-choice-btn" data-commander-dest="keep">Leave in ${keepLabel}</button>` +
    `</div>`;

  steps.querySelectorAll("[data-commander-dest]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const toCommandZone = btn.dataset.commanderDest === "command";
      await sendAction({
        seat, action: "commander_zone_change_confirm", to_command_zone: toCommandZone,
      });
      updateActionHint(
        toCommandZone
          ? `${cardName} was put into the command zone (CR ${rule}).`
          : `${cardName} stayed in your ${destination}.`,
      );
    });
  });
}

// Balance: the player picks exactly which lands/creatures to sacrifice and which
// cards to discard down to the lowest counts, with a selected/total readout.
function applyBalanceSelectPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const need = {
    lands: info.lands_to_sacrifice || 0,
    creatures: info.creatures_to_sacrifice || 0,
    hand: info.cards_to_discard || 0,
  };

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Balance — Choose Sacrifices";
  // Permanents are picked on the board (highlighted lands/creatures), cards to
  // discard by clicking them in hand — never from a list of names here.
  body.textContent = "Click your highlighted lands and creatures to sacrifice them, and cards in your hand to discard.";

  // Only the counts, never the card lists — the board and hand are the pickers.
  function section(label, kind, where) {
    if (!need[kind]) return "";
    return (
      `<div>${escapeHtml(label)} — selected ${balanceSelection[kind].length}/${need[kind]} ` +
      `(click ${escapeHtml(where)})</div>`
    );
  }

  const ready =
    balanceSelection.lands.length === need.lands &&
    balanceSelection.creatures.length === need.creatures &&
    balanceSelection.hand.length === need.hand;

  steps.innerHTML = [
    section(`Sacrifice ${need.lands} land(s)`, "lands", "highlighted lands on the battlefield"),
    section(`Sacrifice ${need.creatures} creature(s)`, "creatures", "highlighted creatures on the battlefield"),
    section(`Discard ${need.hand} card(s)`, "hand", "cards in your hand"),
    `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="balanceConfirmBtn"${ready ? "" : " disabled"}>Confirm</button></div>`,
  ].join("");

  const confirmBtn = document.getElementById("balanceConfirmBtn");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      const payload = {
        seat,
        action: "balance_confirm",
        land_indices: balanceSelection.lands.slice(),
        creature_indices: balanceSelection.creatures.slice(),
        discard_indices: balanceSelection.hand.slice(),
      };
      balanceSelection = { lands: [], creatures: [], hand: [] };
      await sendAction(payload);
    });
  }
}

// A card in hand was clicked while Balance's prompt is open: toggle it in the
// discard half of the plan (the sacrifice halves are toggled on the board).
function toggleBalanceHandSelection(handIndex) {
  const info = getBalanceSelectInfo();
  if (!info) return;
  const need = Number(info.cards_to_discard || 0);
  const at = balanceSelection.hand.indexOf(handIndex);
  if (at >= 0) balanceSelection.hand.splice(at, 1);
  else if (balanceSelection.hand.length < need) balanceSelection.hand.push(handIndex);
  refreshPromptSelection();
}

// Forced sacrifice (Lich: "sacrifice that many nontoken permanents"): the player
// picks exactly `count` of their own permanents. The valid permanents are also
// highlighted on the battlefield canvas (see setTargetingKeys in the render loop).
function applySacrificeSelectPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const permanents = info.permanents || [];
  const validIndices = new Set(permanents.map((p) => p.index));
  // Drop any stale picks that are no longer valid permanents.
  sacrificeSelection = sacrificeSelection.filter((i) => validIndices.has(i));
  const need = Math.min(info.count || 0, permanents.length);

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = `${info.reason || "Sacrifice"} — Choose Sacrifices`;
  body.textContent = `Choose ${need} permanent(s) to sacrifice.`;

  // Only the count, never the card list — the battlefield is the picker.
  const ready = sacrificeSelection.length === need;
  steps.innerHTML = [
    `<div>Selected ${sacrificeSelection.length}/${need}</div>`,
    "<div>Action: click your highlighted permanents to select; click a selected one again to unselect it.</div>",
    `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="sacrificeConfirmBtn"${ready ? "" : " disabled"}>Confirm</button></div>`,
  ].join("");

  const confirmBtn = document.getElementById("sacrificeConfirmBtn");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      const payload = {
        seat,
        action: "sacrifice_confirm",
        sacrifice_indices: sacrificeSelection.slice(),
      };
      sacrificeSelection = [];
      await sendAction(payload);
    });
  }
}

// Color rods (Wooden Sphere, …): "Whenever a player casts a [color] spell, you
// may pay {1}. If you do, gain 1 life." A yes/no decision per pending trigger.
function applyOptionalPayPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  const pending = info.pending || [];
  const current = pending[0];
  const cardName = current?.card_name || "Unknown";
  const cost = current?.cost ?? 1;
  const life = current?.life ?? 1;
  // A free "you may draw a card" rider (Verduran Enchantress) has no mana cost.
  const isDraw = !!current?.draw;

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  // Hasran Ogress: "unless you pay {2}" — declining deals damage instead.
  const damage = Number(current?.damage || 0);

  // Render the generic cost as a mana icon ({1}) rather than literal "{1}" text.
  const costSymbols = renderSymbolsInline(`{${cost}}`);
  const acceptLabel = isDraw
    ? escapeHtml(`Draw ${current.draw} card${current.draw > 1 ? "s" : ""}`)
    : `Pay ${costSymbols}`;
  const declineLabel = damage > 0 ? escapeHtml(`Take ${damage} damage`) : "Decline";
  title.textContent = isDraw ? "Optional Draw" : damage > 0 ? "Pay or Take Damage" : "Pay for Life?";
  if (isDraw) {
    body.textContent = `${cardName}: ${current.prompt || "Draw a card?"}`;
  } else if (damage > 0) {
    setSymbolsHtml(body, `${cardName}: pay {${cost}}, or it deals ${damage} damage to you.`);
  } else {
    setSymbolsHtml(body, `${cardName}: pay {${cost}} to gain ${life} life?`);
  }
  steps.innerHTML = [
    `<div>Card: ${escapeHtml(cardName)}</div>`,
    `<div>Remaining decisions: ${pending.length}</div>`,
    `<div class="prompt-choice-row">` +
      `<button type="button" class="prompt-choice-btn" data-optional-pay="yes">${acceptLabel}</button>` +
      `<button type="button" class="prompt-choice-btn" data-optional-pay="no">${declineLabel}</button>` +
      `</div>`,
  ].join("");

  steps.querySelectorAll("[data-optional-pay]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({
        seat,
        action: "resolve_optional_pay",
        card_name: cardName,
        accept: btn.dataset.optionalPay === "yes",
      });
    });
  });
}

// Old Man of the Sea: at the start of the turn, toggle which "may choose not
// to untap" permanents stay tapped, then confirm.
let optionalUntapKeepSelection = [];
function applyOptionalUntapPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const validIndices = new Set((info.permanents || []).map((p) => Number(p.index)));
  optionalUntapKeepSelection = optionalUntapKeepSelection.filter((i) => validIndices.has(i));

  title.textContent = "Choose not to untap?";
  body.textContent = "These permanents may stay tapped this turn (e.g. Old Man of the Sea keeps control of its stolen creature while tapped).";
  // Toggled on the board: the eligible permanents are highlighted and the ones
  // picked to stay tapped read back here, so no card list is needed.
  const keeping = (info.permanents || []).filter((p) =>
    optionalUntapKeepSelection.includes(Number(p.index)),
  );
  const keepLine = keeping.length
    ? `Staying tapped: ${keeping.map((p) => p.name).join(", ")}`
    : "Staying tapped: none — all of them will untap.";
  steps.innerHTML = [
    "<div>Action: click a highlighted permanent to keep it tapped; click it again to let it untap.</div>",
    `<div><strong>${escapeHtml(keepLine)}</strong></div>`,
    `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" data-optional-untap-confirm="1">Continue</button></div>`,
  ].join("");

  steps.querySelector("[data-optional-untap-confirm]")?.addEventListener("click", async () => {
    const keep = [...optionalUntapKeepSelection];
    optionalUntapKeepSelection = [];
    await sendAction({ seat, action: "optional_untap_confirm", creature_indices: keep });
  });
}

// Cuombajj Witches: the opposing chooser picks any target ("any target of an
// opponent's choice") for the second point of damage.
function applyOpponentDamagePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = `Choose a target for ${info.card_name}`;
  body.textContent = `You choose any target for ${info.card_name}'s ${info.amount} damage.`;
  // Picked on the board: creatures glow as targets, players' name/life pills
  // glow gold (see getPromptBoardTargeting).
  steps.innerHTML =
    "<div>Action: click a highlighted creature on the battlefield, or a player's name/life pill.</div>";
}

// A replaced draw where the player picks one card from a revealed set: Aladdin's
// Lamp (the top X of the library) and Ring of Ma'rûf (the cards they own from
// outside the game). Shown as a card grid with art and hover preview (the
// hand-reveal modal's presentation) — picking a card is a visual decision, not a
// choice between names. `info.card_names` is authoritative for the count and for
// the index sent back; `info.cards` carries the art alongside it.
function renderDrawChoiceModal(info, { title, subtitle, action }) {
  const modal = document.getElementById("lampDrawModal");
  if (!modal) return;

  if (!info) {
    modal.classList.add("hidden");
    return;
  }

  const names = info.card_names || [];
  const cards = info.cards || [];
  modal.classList.remove("hidden");

  const titleEl = document.getElementById("lampDrawTitle");
  if (titleEl) titleEl.textContent = title;
  const subtitleEl = document.getElementById("lampDrawSubtitle");
  if (subtitleEl) subtitleEl.textContent = subtitle(names.length);

  const grid = document.getElementById("lampDrawGrid");
  if (!grid) return;
  grid.innerHTML = names
    .map((name, i) => {
      const card = cards[i];
      const inner = card?.image_uri
        ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(name)}" loading="lazy" />`
        : `<div class="library-card-text-placeholder">${escapeHtml(name)}</div>`;
      return `<div class="library-card-choice lamp-draw-choice" role="button" tabindex="0" data-draw-choice="${i}">` +
        `${inner}<div class="library-card-choice-name">${escapeHtml(name)}</div></div>`;
    })
    .join("");

  grid.querySelectorAll("[data-draw-choice]").forEach((el) => {
    const index = Number(el.dataset.drawChoice);
    const card = cards[index];
    if (card) {
      el.addEventListener("mouseenter", () => showCardPreview(card));
      el.addEventListener("mouseleave", () => clearCardPreview());
    }
    const choose = async () => {
      clearCardPreview();
      modal.classList.add("hidden");
      await sendAction({ seat, action, hand_index: index });
    };
    el.addEventListener("click", choose);
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        choose();
      }
    });
  });
}

// Only one replaced draw can be pending at a time (each is consumed by the draw
// that triggered it), so both share the one modal.
function renderDrawChoiceModals(state) {
  const lamp = getLampDrawInfo(state);
  if (lamp) {
    renderDrawChoiceModal(lamp, {
      title: "Aladdin's Lamp",
      action: "lamp_draw_confirm",
      subtitle: (n) =>
        `Choose which of these ${n} card${n === 1 ? "" : "s"} to draw. ` +
        "The rest go to the bottom of your library in a random order.",
    });
    return;
  }
  const outside = getOutsideGameDrawInfo(state);
  renderDrawChoiceModal(outside, {
    title: "Ring of Ma'rûf",
    action: "outside_game_draw_confirm",
    subtitle: (n) =>
      `Choose a card you own from outside the game to put into your hand ` +
      `(${n} available).`,
  });
}

// Phantasmal Terrain: "As this Aura enters, choose a basic land type." The
// controller picks one of the five basic land types for the enchanted land.
function applyLandTypeChoicePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = info.card_name || "Phantasmal Terrain";
  title.textContent = "Choose a basic land type";
  body.textContent = `${cardName}: the enchanted land becomes the chosen type.`;
  const buttons = info.options
    .map(
      (type) =>
        `<button type="button" class="prompt-choice-btn" data-land-type="${escapeHtml(type)}">` +
        `${escapeHtml(type.charAt(0).toUpperCase() + type.slice(1))}</button>`
    )
    .join("");
  steps.innerHTML = `<div class="prompt-choice-column">${buttons}</div>`;

  steps.querySelectorAll("[data-land-type]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({
        seat,
        action: "land_type_confirm",
        land_type: btn.dataset.landType,
      });
    });
  });
}

function applyEffectOrderPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Choose which effect applies first";
  body.textContent =
    "Several effects are trying to change the same event. Pick the one to apply " +
    "first; the rest are reconsidered afterwards.";
  const buttons = info.options
    .map(
      (label, index) =>
        `<button type="button" class="prompt-choice-btn" data-effect-order="${index}">` +
        `${escapeHtml(label)}</button>`
    )
    .join("");
  steps.innerHTML = `<div class="prompt-choice-column">${buttons}</div>`;

  steps.querySelectorAll("[data-effect-order]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({
        seat,
        action: "effect_order_confirm",
        option_index: Number(btn.dataset.effectOrder),
      });
    });
  });
}

// Primal Clay: "As this creature enters, it becomes your choice of a 3/3, a 2/2
// with flying, or a 1/6 Wall with defender." The first printed body is already
// applied, so this offers to replace it.
function applyBodyChoicePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = info.card_name || "Primal Clay";
  title.textContent = "Choose what it enters as";
  body.textContent = `${cardName}: pick the body it becomes.`;
  const buttons = info.options
    .map((option) => {
      const label = option.keyword
        ? `${option.power}/${option.toughness} with ${option.keyword}`
        : `${option.power}/${option.toughness}`;
      return (
        `<button type="button" class="prompt-choice-btn" data-body-index="${option.index}">` +
        `${escapeHtml(label)}</button>`
      );
    })
    .join("");
  steps.innerHTML = `<div class="prompt-choice-column">${buttons}</div>`;

  steps.querySelectorAll("[data-body-index]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({
        seat,
        action: "body_choice_confirm",
        hand_index: Number(btn.dataset.bodyIndex),
      });
    });
  });
}

// Black Vise / Jihad: "As this enters, choose an opponent [and a color]."
// Selected color for the current enter-choice prompt (Jihad); reset whenever
// the prompt is (re)rendered without a prior selection.
let enterChoiceSelectedColor = null;

function applyEnterChoicePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = info.card_name || "Permanent";
  const needsColor = !!info.needs_color;
  if (needsColor && !enterChoiceSelectedColor) {
    enterChoiceSelectedColor = info.default_color || "W";
  }
  title.textContent = needsColor ? "Choose a color and an opponent" : "Choose an opponent";
  body.textContent = `${cardName}: as it enters, choose ${needsColor ? "a color and " : ""}an opponent.`;

  const colorNames = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };
  const colorRow = needsColor
    ? `<div class="prompt-choice-row">` +
      (info.colors || [])
        .map(
          (c) =>
            `<button type="button" class="prompt-choice-btn${c === enterChoiceSelectedColor ? " selected" : ""}" data-enter-color="${escapeHtml(c)}">` +
            `${escapeHtml(colorNames[c] || c)}</button>`
        )
        .join("") +
      `</div>`
    : "";
  // The opponent is chosen by clicking their (highlighted) name/life pill; only
  // the color, which has no board representation, keeps its buttons.
  steps.innerHTML =
    `${colorRow}<div>Action: click a highlighted opponent's name or life pill` +
    `${needsColor ? " (after picking a color above)" : ""}.</div>`;

  steps.querySelectorAll("[data-enter-color]").forEach((btn) => {
    btn.addEventListener("click", () => {
      enterChoiceSelectedColor = btn.dataset.enterColor;
      steps.querySelectorAll("[data-enter-color]").forEach((b) => {
        b.classList.toggle("selected", b.dataset.enterColor === enterChoiceSelectedColor);
      });
    });
  });
}

// Drop of Honey: pick which of the creatures tied for least power is destroyed.
function applyLeastPowerChoicePrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = info.card_name || "Drop of Honey";
  title.textContent = "Choose a creature to destroy";
  body.textContent = `${cardName}: these creatures are tied for least power — choose which one is destroyed.`;
  // The tied creatures are highlighted on the battlefield; clicking one picks it.
  steps.innerHTML = "<div>Action: click one of the highlighted creatures on the battlefield.</div>";
}


function applyLoyaltyRecipientPrompt(info) {
  const panel = q("activationPanel");
  panel.classList.remove("hidden");
  q("promptOkBtn").classList.add("hidden");
  q("promptCustomRow").classList.add("hidden");
  q("promptCancelBtn").classList.add("hidden");
  q("promptCancelBtn").disabled = true;
  q("promptCustomOkBtn").disabled = true;
  q("promptTitle").textContent = "Choose a planeswalker";
  q("promptBody").textContent =
    `${info.card_name}: put ${info.count} loyalty counter(s) on one of these.`;
  q("promptSteps").innerHTML =
    "<div>Action: click one of the highlighted planeswalkers on the battlefield.</div>";
}

// Power Sink: "Counter target spell unless its controller pays {X}." The targeted
// spell's controller taps lands to fill their pool, then pays {X} to keep their
// spell or declines (and it is countered, tapping their lands and draining mana).
function applyManaPaymentPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const cardName = info.card_name || "Power Sink";
  const spellName = info.spell_name || "your spell";
  const costSymbols = renderSymbolsInline(`{${Number(info.amount) || 0}}`);
  title.textContent = "Pay or be countered";
  setSymbolsHtml(
    body,
    `${cardName} counters ${spellName} unless you pay {${Number(info.amount) || 0}}. ` +
      `Tap lands to generate mana, then pay or decline.`,
  );
  const payBtn = `<button type="button" class="prompt-choice-btn" id="manaPayBtn">Pay ${costSymbols}</button>`;
  const declineBtn = `<button type="button" class="prompt-choice-btn" id="manaDeclineBtn">Don't pay (${escapeHtml(spellName)} is countered)</button>`;
  steps.innerHTML = [
    `<div>Spell: ${escapeHtml(spellName)}</div>`,
    `<div>Cost to keep it: ${costSymbols}</div>`,
    `<div class="prompt-choice-row">${payBtn}${declineBtn}</div>`,
  ].join("");

  const payEl = document.getElementById("manaPayBtn");
  const declineEl = document.getElementById("manaDeclineBtn");
  if (payEl) {
    payEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "confirm_mana_payment", accept: true });
    });
  }
  if (declineEl) {
    declineEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "confirm_mana_payment", accept: false });
    });
  }
}

// Kudzu: "That land's controller may attach this Aura to a land of their choice."
// After the enchanted land is destroyed, the controller picks a new land.
function applyKudzuReattachPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Kudzu — choose a land";
  body.textContent = "Attach Kudzu to a land of your choice.";
  // Your lands are highlighted on the battlefield; clicking one re-attaches Kudzu.
  steps.innerHTML = "<div>Action: click one of your highlighted lands on the battlefield.</div>";
}

// Word of Command: "Look at target opponent's hand and choose a card; that player
// plays it." The caster picks which of the revealed cards to force (or declines).
function applyWordOfCommandPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Word of Command";
  body.textContent = `Choose a card from ${info.target_name}'s hand for them to play.`;
  const buttons = info.choices
    .map(
      (c) =>
        `<button type="button" class="prompt-choice-btn" data-woc-hand="${c.hand_index}">` +
        `${escapeHtml(c.name)}</button>`
    )
    .join("");
  steps.innerHTML =
    `<div class="prompt-choice-column">${buttons}` +
    `<button type="button" class="prompt-choice-btn" data-woc-decline="1">Decline</button></div>`;

  steps.querySelectorAll("[data-woc-hand]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({ seat, action: "word_of_command_confirm", hand_index: Number(btn.dataset.wocHand) });
    });
  });
  const declineBtn = steps.querySelector("[data-woc-decline]");
  if (declineBtn) {
    declineBtn.addEventListener("click", async () => {
      await sendAction({ seat, action: "word_of_command_confirm", accept: false });
    });
  }
}

// Time Vault: "If you would begin your turn while this is tapped, you may skip
// that turn instead. If you do, untap it." A begin-of-turn yes/no decision.
function applyTimeVaultPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const name = info.permanents[0] || "Time Vault";
  title.textContent = "Skip your turn?";
  body.textContent = `Skip this turn to untap ${name}?`;
  steps.innerHTML =
    `<div class="prompt-choice-row">` +
    `<button type="button" class="prompt-choice-btn" data-tv="skip">Skip turn &amp; untap ${escapeHtml(name)}</button>` +
    `<button type="button" class="prompt-choice-btn" data-tv="decline">Take my turn</button>` +
    `</div>`;

  steps.querySelectorAll("[data-tv]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.dataset.tv === "skip") {
        await sendAction({ seat, action: "time_vault_skip", card_name: name });
      } else {
        await sendAction({ seat, action: "time_vault_decline" });
      }
    });
  });
}

// Illusionary Mask: "{X}: cast a creature card whose cost X could pay, face down
// as a 2/2." The controller picks an eligible hand creature, or declines.
function applyFaceDownCastPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Illusionary Mask — cast face down";
  body.textContent = `Choose a creature (mana value ≤ ${info.max_cmc}) to cast face down as a 2/2.`;
  const buttons = info.choices
    .map(
      (c) =>
        `<button type="button" class="prompt-choice-btn" data-fd-hand="${c.hand_index}">` +
        `${escapeHtml(c.name)} (${c.cmc})</button>`
    )
    .join("");
  steps.innerHTML =
    `<div class="prompt-choice-column">${buttons}` +
    `<button type="button" class="prompt-choice-btn" data-fd-decline="1">Decline</button></div>`;

  steps.querySelectorAll("[data-fd-hand]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await sendAction({
        seat,
        action: "face_down_cast_confirm",
        hand_index: Number(btn.dataset.fdHand),
      });
    });
  });
  const declineBtn = steps.querySelector("[data-fd-decline]");
  if (declineBtn) {
    declineBtn.addEventListener("click", async () => {
      await sendAction({ seat, action: "face_down_cast_confirm", accept: false });
    });
  }
}

// Raging River: the defending player divides their non-flying creatures into a
// "left" and "right" pile; the attacking player then labels each attacker with the
// pile it can be blocked from. Both are resolved with Left/Right buttons drawn over
// each creature on the board (not a modal). This builds the state the canvas needs:
// committed piles for both players (for the divider + side badges) and the viewer's
// own pending choice (the buttons). Returns null when no division is active.
function buildRagingRiverCanvasData(state) {
  const combat = getCombatState(state);
  if (!combat || !combat.left_right_active) return null;
  const defenderSeat = combat.left_right_defender_index;
  const attackerSeat = state.current_turn;
  const data = {
    active: true,
    defenderSeat,
    attackerSeat,
    defenderPiles: combat.defender_piles || {},
    attackerPiles: combat.attacker_piles || {},
    defenderLocked: !!combat.defender_piles_locked,
    attackerLocked: !!combat.attacker_piles_locked,
    prompt: null,
  };

  const info = getRagingRiverInfo(state);
  if (info) {
    const isDefender = Array.isArray(info.divide_creatures);
    const items = isDefender ? info.divide_creatures : info.label_attackers;
    const promptSeat = isDefender ? defenderSeat : attackerSeat;
    const sig = `${promptSeat}:${items.map((it) => it.index).join(",")}`;
    // Start fresh (every creature unset) whenever the prompt changes, so the
    // player explicitly assigns each creature rather than accepting a default.
    if (ragingRiverPromptSig !== sig) {
      ragingRiverPromptSig = sig;
      ragingRiverSelection = {};
    }
    data.prompt = {
      seat: promptSeat,
      role: isDefender ? "defender" : "attacker",
      items: items.map((it) => ({ idx: it.index, name: it.name })),
      selection: ragingRiverSelection || {},
    };
  } else {
    ragingRiverPromptSig = null;
    ragingRiverSelection = null;
  }
  return data;
}

// Apply one Left/Right button click (from the canvas) to the viewer's pending
// Raging River choice. Once every prompted creature has a side, submit the pile
// assignment; otherwise re-render so the new selection shows immediately.
function handleRagingRiverPileClick({ idx, side }) {
  if (!currentState || seat === null) return;
  const info = getRagingRiverInfo(currentState);
  if (!info) return;
  const isDefender = Array.isArray(info.divide_creatures);
  const items = isDefender ? info.divide_creatures : info.label_attackers;
  if (!items.some((it) => it.index === idx)) return;
  if (!ragingRiverSelection) ragingRiverSelection = {};
  ragingRiverSelection[idx] = side;

  const allChosen = items.every(
    (it) => ragingRiverSelection[it.index] === "left" || ragingRiverSelection[it.index] === "right"
  );
  if (allChosen) {
    const piles = {};
    for (const it of items) piles[it.index] = ragingRiverSelection[it.index];
    ragingRiverSelection = null;
    ragingRiverPromptSig = null;
    sendAction({
      seat,
      action: isDefender ? "assign_defender_piles" : "assign_attacker_piles",
      piles,
    }).catch((e) => updateActionHint(e.message, true));
  } else {
    renderBoard(currentState);
    updateActionHint(
      `Raging River: assign each creature to Left or Right (${Object.keys(ragingRiverSelection).length}/${items.length} chosen).`
    );
  }
}

// Camouflage: the defending player divides their untapped creatures into
// numbered piles (one per attacker); each pile is then matched to a random
// attacker by the engine. Resolved with numbered buttons drawn over each
// creature on the board (mirroring the Raging River flow). Returns the state
// the canvas needs, or null when no Camouflage division is pending.
function buildCamouflageCanvasData(state) {
  const info = getCamouflageInfo(state);
  if (!info) {
    camouflagePromptSig = null;
    camouflageSelection = null;
    return null;
  }
  const items = info.divide_creatures;
  const sig = `${info.defender_seat}:${info.pile_count}:${items.map((it) => it.index).join(",")}`;
  // Start fresh (every creature unset) whenever the prompt changes, so the
  // player explicitly assigns each creature rather than accepting a default.
  if (camouflagePromptSig !== sig) {
    camouflagePromptSig = sig;
    camouflageSelection = {};
  }
  return {
    active: true,
    seat: info.defender_seat,
    pileCount: Number(info.pile_count) || 1,
    items: items.map((it) => ({ idx: it.index, name: it.name })),
    selection: camouflageSelection || {},
  };
}

// Apply one Camouflage pile-button click (from the canvas). `pile` is a 0-based
// pile number or "none". Once every prompted creature has a choice, submit the
// division; otherwise re-render so the new selection shows immediately.
function handleCamouflagePileClick({ idx, pile }) {
  if (!currentState || seat === null) return;
  const info = getCamouflageInfo(currentState);
  if (!info) return;
  const items = info.divide_creatures;
  if (!items.some((it) => it.index === idx)) return;
  if (!camouflageSelection) camouflageSelection = {};
  camouflageSelection[idx] = pile;

  const allChosen = items.every((it) => camouflageSelection[it.index] !== undefined);
  if (allChosen) {
    const piles = {};
    for (const it of items) {
      const chosen = camouflageSelection[it.index];
      if (chosen !== "none") piles[it.index] = chosen;
    }
    camouflageSelection = null;
    camouflagePromptSig = null;
    sendAction({ seat, action: "assign_camouflage_piles", camouflage_piles: piles }).catch((e) =>
      updateActionHint(e.message, true)
    );
  } else {
    renderBoard(currentState);
    updateActionHint(
      `Camouflage: assign each creature a pile number or ✕ for none ` +
        `(${Object.keys(camouflageSelection).length}/${items.length} chosen). ` +
        "Each pile blocks a random attacker."
    );
  }
}

function applyIslandSanctuaryPrompt() {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  title.textContent = "Island Sanctuary";
  body.textContent = "Skip your draw to gain protection from non-flying, non-islandwalk creatures this turn, or draw normally.";

  const skipBtn = `<button type="button" class="prompt-choice-btn" id="sanctuarySkipBtn">Skip Draw (gain protection)</button>`;
  const drawBtn = `<button type="button" class="prompt-choice-btn" id="sanctuaryDrawBtn">Draw a card</button>`;
  steps.innerHTML = `<div class="prompt-choice-row">${skipBtn}${drawBtn}</div>`;

  const skipEl = document.getElementById("sanctuarySkipBtn");
  const drawEl = document.getElementById("sanctuaryDrawBtn");
  if (skipEl) {
    skipEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "island_sanctuary_skip" });
    });
  }
  if (drawEl) {
    drawEl.addEventListener("click", async () => {
      await sendAction({ seat, action: "island_sanctuary_draw" });
    });
  }
}

function applyCoinFlipPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  cancelBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  okBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  const loserChoice = !!info.is_loser_choice;
  if (info.is_my_turn) {
    title.textContent = loserChoice ? "You lost — your call" : "You won the coin flip!";
    body.textContent = loserChoice
      ? `You lost the last game, so ${escapeHtml(info.winner_name || "you")} choose who plays first. Do you want to go first or second?`
      : `${escapeHtml(info.winner_name || "You")} won the coin flip. Do you want to go first or second?`;
    steps.innerHTML = `
      <div class="prompt-choice-row">
        <button type="button" class="prompt-choice-btn" id="coinFlipFirstBtn">Go First</button>
        <button type="button" class="prompt-choice-btn" id="coinFlipSecondBtn">Go Second</button>
      </div>`;
    document.getElementById("coinFlipFirstBtn").addEventListener("click", () =>
      sendAction({ seat, action: "coin_flip_choose", hand_index: 0 })
    );
    document.getElementById("coinFlipSecondBtn").addEventListener("click", () =>
      sendAction({ seat, action: "coin_flip_choose", hand_index: 1 })
    );
  } else {
    title.textContent = loserChoice ? "Choosing who plays first" : "Coin Flip";
    body.textContent = loserChoice
      ? `${escapeHtml(info.winner_name || "Opponent")} lost the last game and is choosing who plays first.`
      : `${escapeHtml(info.winner_name || "Opponent")} won the coin flip and is choosing who goes first.`;
    steps.innerHTML = `<div>Waiting for ${escapeHtml(info.waiting_for || "opponent")} to choose...</div>`;
  }
}

function applyMulliganPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  cancelBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  okBtn.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  if (info.is_my_turn) {
    const taken = Number(info.mulligans_taken || 0);
    const keepSize = 7 - taken;
    title.textContent = taken > 0 ? `Mulligan (×${taken})` : "Keep or Mulligan?";
    body.textContent = taken > 0
      ? `You have taken ${taken} mulligan${taken > 1 ? "s" : ""}. Keep this hand (you'll put ${taken} card${taken > 1 ? "s" : ""} on the bottom), or take another mulligan?`
      : "Do you want to keep your opening hand or take a mulligan?";
    steps.innerHTML = `
      <div>Your hand has 7 cards. If you keep, you will put ${taken} card${taken !== 1 ? "s" : ""} on the bottom.</div>
      <div class="prompt-choice-row" style="margin-top:6px">
        <button type="button" class="prompt-choice-btn" id="mulliganKeepBtn">Keep Hand</button>
        ${taken < 7 ? '<button type="button" class="prompt-choice-btn" id="mulliganTakeBtn">Take Mulligan</button>' : ""}
      </div>`;
    document.getElementById("mulliganKeepBtn").addEventListener("click", () =>
      sendAction({ seat, action: "mulligan_keep" })
    );
    const takeBtn = document.getElementById("mulliganTakeBtn");
    if (takeBtn) {
      takeBtn.addEventListener("click", () =>
        sendAction({ seat, action: "mulligan_take" })
      );
    }
  } else {
    // Simultaneous mode: waiting_for may name several still-deciding players.
    const waitingFor = info.waiting_for || "Opponent";
    const plural = info.simultaneous && waitingFor.includes(",");
    title.textContent = plural ? "Waiting for Mulligan Decisions" : "Waiting for Mulligan Decision";
    body.textContent = plural
      ? `${escapeHtml(waitingFor)} are still deciding whether to mulligan.`
      : `${escapeHtml(waitingFor)} is deciding whether to mulligan.`;
    steps.innerHTML = `<div>Waiting for ${escapeHtml(waitingFor)}...</div>`;
  }
}

function applyMulliganBottomPrompt(info) {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customOkBtn = q("promptCustomOkBtn");

  panel.classList.remove("hidden");
  cancelBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  cancelBtn.disabled = true;
  customOkBtn.disabled = true;

  if (info.is_my_turn) {
    const required = Number(info.required_count || 0);
    const selectedCount = Number(info.selected_count || 0);

    title.textContent = `Put ${required} Card${required !== 1 ? "s" : ""} on the Bottom`;
    body.textContent = `You took ${required} mulligan${required !== 1 ? "s" : ""}. Click ${required} card${required !== 1 ? "s" : ""} in your hand to put on the bottom of your library, then click Confirm.`;

    steps.innerHTML = `<div>Selected: ${selectedCount} / ${required}</div>`;

    const ready = selectedCount === required;
    okBtn.classList.remove("hidden");
    okBtn.textContent = `Confirm (${selectedCount}/${required})`;
    okBtn.disabled = !ready;
    if (ready) {
      okBtn.onclick = () => sendAction({ seat, action: "mulligan_bottom_confirm" });
    } else {
      okBtn.onclick = null;
    }
  } else {
    title.textContent = "Opponent Selecting Bottom Cards";
    body.textContent = `${escapeHtml(info.waiting_for || "Opponent")} is choosing ${info.required_count} card${info.required_count !== 1 ? "s" : ""} to put on the bottom.`;
    steps.innerHTML = `<div>Waiting for ${escapeHtml(info.waiting_for || "opponent")}...</div>`;
    okBtn.classList.add("hidden");
  }
}

function renderSearchLibraryModal(info) {
  const modal = document.getElementById("searchLibraryModal");
  if (!modal) return;

  if (!info) {
    modal.classList.add("hidden");
    return;
  }

  const cards = info.cards || [];
  const count = info.count || 1;
  const subtitle = document.getElementById("searchLibrarySubtitle");
  if (subtitle) {
    subtitle.textContent = `Choose ${count === 1 ? "a card" : `${count} cards`} to put into your hand.`;
  }

  modal.classList.remove("hidden");

  const grid = document.getElementById("searchLibraryGrid");
  const filterInput = document.getElementById("searchLibraryFilter");
  const confirmBtn = document.getElementById("searchLibraryConfirmBtn");

  function buildGrid() {
    if (!grid) return;
    const term = searchLibraryFilter.toLowerCase();
    const items = cards
      .map((card, idx) => {
        if (term && !card.name.toLowerCase().includes(term) && !(card.type || "").toLowerCase().includes(term)) {
          return "";
        }
        const selectedClass = searchLibrarySelectedIndex === idx ? " selected" : "";
        const inner = card.image_uri
          ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name)}" loading="lazy" />`
          : `<div class="library-card-text-placeholder">${escapeHtml(card.name)}</div>`;
        return `<div class="library-card-choice${selectedClass}" data-idx="${idx}">${inner}<div class="library-card-choice-name">${escapeHtml(card.name)}</div></div>`;
      })
      .join("");
    grid.innerHTML = items;

    grid.querySelectorAll(".library-card-choice").forEach((el) => {
      el.addEventListener("click", () => {
        searchLibrarySelectedIndex = Number(el.dataset.idx);
        if (confirmBtn) confirmBtn.disabled = false;
        buildGrid();
      });
    });
  }

  if (filterInput && !filterInput.dataset.bound) {
    filterInput.dataset.bound = "1";
    filterInput.value = searchLibraryFilter;
    filterInput.addEventListener("input", () => {
      searchLibraryFilter = filterInput.value;
      buildGrid();
    });
  }

  if (confirmBtn && !confirmBtn.dataset.bound) {
    confirmBtn.dataset.bound = "1";
    confirmBtn.addEventListener("click", async () => {
      if (searchLibrarySelectedIndex === null) return;
      const idx = searchLibrarySelectedIndex;
      searchLibrarySelectedIndex = null;
      searchLibraryFilter = "";
      if (filterInput) { filterInput.value = ""; delete filterInput.dataset.bound; }
      delete confirmBtn.dataset.bound;
      modal.classList.add("hidden");
      await sendAction({ seat, action: "search_library_confirm", hand_index: idx });
    });
  }

  buildGrid();
  if (confirmBtn) confirmBtn.disabled = searchLibrarySelectedIndex === null;
}

// See the Truth's pick: the looked-at top cards; clicking one keeps it and
// bottoms the rest, so there is no separate confirm step.
function getLookTopPickInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.look_top_pick;
  if (!info) return null;
  if (info.caster_seat !== seat) return null;
  return info;
}

function renderLookTopPickModal(info) {
  const modal = document.getElementById("lookTopPickModal");
  if (!modal) return;
  if (!info) {
    modal.classList.add("hidden");
    return;
  }
  modal.classList.remove("hidden");
  const subtitle = document.getElementById("lookTopPickSubtitle");
  if (subtitle) {
    subtitle.textContent = `${info.card_name}: click a card to put it into your hand; the rest go to the bottom of your library.`;
  }
  const grid = document.getElementById("lookTopPickGrid");
  if (grid) {
    grid.innerHTML = (info.cards || [])
      .map((card, idx) => {
        const inner = card.image_uri
          ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name)}" loading="lazy" />`
          : `<div class="library-card-text-placeholder">${escapeHtml(card.name)}</div>`;
        return `<div class="library-card-choice" data-idx="${idx}">${inner}<div class="library-card-choice-name">${escapeHtml(card.name)}</div></div>`;
      })
      .join("");
    grid.querySelectorAll(".library-card-choice").forEach((el) => {
      el.addEventListener("click", async () => {
        modal.classList.add("hidden");
        await sendAction({ seat, action: "look_top_pick_confirm", hand_index: Number(el.dataset.idx) });
      });
    });
  }
}

// Rewind's "Untap up to four lands": a resolution-time multi-select over
// matching permanents, capped at the printed amount. Confirming with nothing
// selected is legal ("up to" includes zero).
let untapUpToSelected = new Set();

function getUntapUpToInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.untap_up_to;
  if (!info) return null;
  if (info.player_seat !== seat) return null;
  return info;
}

function renderUntapUpToModal(info) {
  const modal = document.getElementById("untapUpToModal");
  if (!modal) return;
  if (!info) {
    modal.classList.add("hidden");
    untapUpToSelected = new Set();
    return;
  }
  modal.classList.remove("hidden");
  const subtitle = document.getElementById("untapUpToSubtitle");
  if (subtitle) {
    subtitle.textContent = `${info.card_name}: choose up to ${info.amount} to untap (tapped ones shown first).`;
  }
  const list = document.getElementById("untapUpToList");
  const confirmBtn = document.getElementById("untapUpToConfirmBtn");
  const candidates = [...(info.candidates || [])].sort((a, b) => Number(b.tapped) - Number(a.tapped));
  if (list) {
    list.innerHTML = candidates
      .map((entry) => {
        const selectedClass = untapUpToSelected.has(entry.id) ? " selected" : "";
        const state = entry.tapped ? "tapped" : "untapped";
        return `<div class="library-card-choice${selectedClass}" data-id="${entry.id}"><div class="library-card-text-placeholder">${escapeHtml(entry.name)}</div><div class="library-card-choice-name">${escapeHtml(state)}${entry.seat !== seat ? " (opponent's)" : ""}</div></div>`;
      })
      .join("") || `<div class="modal-empty-note">Nothing to untap.</div>`;
    list.querySelectorAll(".library-card-choice").forEach((el) => {
      el.addEventListener("click", () => {
        const id = Number(el.dataset.id);
        if (untapUpToSelected.has(id)) untapUpToSelected.delete(id);
        else if (untapUpToSelected.size < Number(info.amount || 0)) untapUpToSelected.add(id);
        else return;
        el.classList.toggle("selected");
      });
    });
  }
  if (confirmBtn && !confirmBtn.dataset.bound) {
    confirmBtn.dataset.bound = "1";
    confirmBtn.addEventListener("click", async () => {
      const ids = [...untapUpToSelected];
      untapUpToSelected = new Set();
      delete confirmBtn.dataset.bound;
      modal.classList.add("hidden");
      await sendAction({ seat, action: "untap_up_to_confirm", target_permanent_ids: ids });
    });
  }
}

// Chandra, Heart of Fire's −9: a two-zone multi-select search. Any number of
// the highlighted (matching) cards may be picked across both grids; confirm
// exiles them, and confirming with nothing picked is the fail-to-find.
let searchExileSelected = new Set();

function renderSearchExileModal(info) {
  const modal = document.getElementById("searchExileModal");
  if (!modal) return;

  if (!info) {
    modal.classList.add("hidden");
    searchExileSelected = new Set();
    return;
  }

  modal.classList.remove("hidden");
  const subtitle = document.getElementById("searchExileSubtitle");
  if (subtitle) {
    const what = [
      (info.colors || []).join("/"),
      (info.card_types || []).join(" or "),
    ].filter(Boolean).join(" ");
    subtitle.textContent = `Choose any number of ${what || "matching"} cards to exile. You may cast them this turn.`;
  }

  const confirmBtn = document.getElementById("searchExileConfirmBtn");

  function buildGrid(gridId, zone, cards, legalIndices) {
    const grid = document.getElementById(gridId);
    if (!grid) return;
    const legal = new Set(legalIndices || []);
    grid.innerHTML = (cards || [])
      .map((card, idx) => {
        if (!legal.has(idx)) return "";
        const key = `${zone}:${idx}`;
        const selectedClass = searchExileSelected.has(key) ? " selected" : "";
        const inner = card.image_uri
          ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name)}" loading="lazy" />`
          : `<div class="library-card-text-placeholder">${escapeHtml(card.name)}</div>`;
        return `<div class="library-card-choice${selectedClass}" data-zone="${zone}" data-idx="${idx}">${inner}<div class="library-card-choice-name">${escapeHtml(card.name)}</div></div>`;
      })
      .join("") || `<div class="modal-empty-note">No matching cards.</div>`;

    grid.querySelectorAll(".library-card-choice").forEach((el) => {
      el.addEventListener("click", () => {
        const key = `${el.dataset.zone}:${el.dataset.idx}`;
        if (searchExileSelected.has(key)) searchExileSelected.delete(key);
        else searchExileSelected.add(key);
        el.classList.toggle("selected");
        if (confirmBtn) {
          confirmBtn.textContent = searchExileSelected.size
            ? `Exile ${searchExileSelected.size} Card${searchExileSelected.size === 1 ? "" : "s"}`
            : "Take Nothing";
        }
      });
    });
  }

  buildGrid("searchExileGraveyardGrid", "graveyard", info.graveyard_cards, info.legal_graveyard_indices);
  buildGrid("searchExileLibraryGrid", "library", info.cards, info.legal_indices);

  if (confirmBtn && !confirmBtn.dataset.bound) {
    confirmBtn.dataset.bound = "1";
    confirmBtn.addEventListener("click", async () => {
      const picks = [...searchExileSelected].map((key) => {
        const [zone, idx] = key.split(":");
        return { zone, index: Number(idx) };
      });
      searchExileSelected = new Set();
      delete confirmBtn.dataset.bound;
      modal.classList.add("hidden");
      await sendAction({ seat, action: "search_exile_confirm", search_picks: picks });
    });
  }
  if (confirmBtn) {
    confirmBtn.textContent = searchExileSelected.size
      ? `Exile ${searchExileSelected.size} Card${searchExileSelected.size === 1 ? "" : "s"}`
      : "Take Nothing";
  }
}

// Glasses of Urza: show the viewer the actual cards in the looked-at player's
// hand (card art), with a Continue button that dismisses the reveal.
function renderHandRevealModal(info) {
  const modal = document.getElementById("handRevealModal");
  if (!modal) return;

  if (!info) {
    modal.classList.add("hidden");
    return;
  }

  const cards = info.cards || [];
  const subtitle = document.getElementById("handRevealSubtitle");
  if (subtitle) {
    const n = cards.length;
    subtitle.textContent = n === 0
      ? `${info.target_name}'s hand is empty.`
      : `${info.target_name}'s hand (${n} card${n === 1 ? "" : "s"}). Click Continue when done.`;
  }

  modal.classList.remove("hidden");

  const grid = document.getElementById("handRevealGrid");
  if (grid) {
    grid.innerHTML = cards
      .map((card, i) => {
        const inner = card.image_uri
          ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name)}" loading="lazy" />`
          : `<div class="library-card-text-placeholder">${escapeHtml(card.name)}</div>`;
        return `<div class="library-card-choice" data-reveal-index="${i}">${inner}<div class="library-card-choice-name">${escapeHtml(card.name)}</div></div>`;
      })
      .join("");
    // Hover preview, mirroring the board/stack card-preview behavior.
    grid.querySelectorAll("[data-reveal-index]").forEach((el) => {
      const card = cards[Number(el.dataset.revealIndex)];
      el.addEventListener("mouseenter", () => showCardPreview(card));
      el.addEventListener("mouseleave", () => clearCardPreview());
    });
  }

  const continueBtn = document.getElementById("handRevealContinueBtn");
  if (continueBtn && !continueBtn.dataset.bound) {
    continueBtn.dataset.bound = "1";
    continueBtn.addEventListener("click", async () => {
      modal.classList.add("hidden");
      await sendAction({ seat, action: "dismiss_hand_reveal" });
    });
  }
}

function renderReorderLibraryModal(info) {
  const modal = document.getElementById("reorderLibraryModal");
  if (!modal) return;

  if (!info) {
    modal.classList.add("hidden");
    return;
  }

  modal.classList.remove("hidden");

  const cards = info.cards || [];
  if (reorderLibraryCurrentOrder === null || reorderLibraryCurrentOrder.length !== cards.length) {
    reorderLibraryCurrentOrder = cards.map((_, i) => i);
  }

  const container = document.getElementById("reorderLibraryCards");
  const confirmBtn = document.getElementById("reorderLibraryConfirmBtn");
  const shuffleBtn = document.getElementById("reorderLibraryShuffleBtn");

  let dragSrcSlot = null;

  function buildCards() {
    if (!container) return;
    container.innerHTML = "";
    reorderLibraryCurrentOrder.forEach((cardIdx, slotPos) => {
      const card = cards[cardIdx];
      const slot = document.createElement("div");
      slot.className = "reorder-card-slot";
      slot.dataset.slotPos = slotPos;

      const item = document.createElement("div");
      item.className = "reorder-card-item";
      item.draggable = true;
      item.dataset.slotPos = slotPos;

      if (card.image_uri) {
        const img = document.createElement("img");
        img.src = card.image_uri;
        img.alt = card.name;
        img.loading = "lazy";
        item.appendChild(img);
      } else {
        const ph = document.createElement("div");
        ph.className = "reorder-card-text-placeholder";
        ph.textContent = card.name;
        item.appendChild(ph);
      }

      const nameEl = document.createElement("div");
      nameEl.className = "reorder-card-item-name";
      nameEl.textContent = card.name;
      item.appendChild(nameEl);

      item.addEventListener("dragstart", (e) => {
        dragSrcSlot = slotPos;
        item.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
      });

      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        container.querySelectorAll(".reorder-card-slot").forEach((s) => s.classList.remove("drag-over"));
      });

      slot.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        slot.classList.add("drag-over");
      });

      slot.addEventListener("dragleave", () => {
        slot.classList.remove("drag-over");
      });

      slot.addEventListener("drop", (e) => {
        e.preventDefault();
        slot.classList.remove("drag-over");
        const destSlot = Number(slot.dataset.slotPos);
        if (dragSrcSlot === null || dragSrcSlot === destSlot) return;
        const newOrder = [...reorderLibraryCurrentOrder];
        const tmp = newOrder[dragSrcSlot];
        newOrder[dragSrcSlot] = newOrder[destSlot];
        newOrder[destSlot] = tmp;
        reorderLibraryCurrentOrder = newOrder;
        dragSrcSlot = null;
        buildCards();
      });

      slot.appendChild(item);
      container.appendChild(slot);
    });
  }

  if (confirmBtn && !confirmBtn.dataset.bound) {
    confirmBtn.dataset.bound = "1";
    confirmBtn.addEventListener("click", async () => {
      const order = [...reorderLibraryCurrentOrder];
      reorderLibraryCurrentOrder = null;
      delete confirmBtn.dataset.bound;
      if (shuffleBtn) delete shuffleBtn.dataset.bound;
      modal.classList.add("hidden");
      await sendAction({ seat, action: "reorder_library_confirm", card_order: order });
    });
  }

  // "You may have that player shuffle" (Natural Selection): offer a shuffle option.
  if (shuffleBtn) {
    if (info.may_shuffle) {
      shuffleBtn.classList.remove("hidden");
      const who = info.target_name ? ` (${info.target_name})` : "";
      shuffleBtn.textContent = `Have Them Shuffle${who}`;
      if (!shuffleBtn.dataset.bound) {
        shuffleBtn.dataset.bound = "1";
        shuffleBtn.addEventListener("click", async () => {
          const order = [...reorderLibraryCurrentOrder];
          reorderLibraryCurrentOrder = null;
          delete shuffleBtn.dataset.bound;
          if (confirmBtn) delete confirmBtn.dataset.bound;
          modal.classList.add("hidden");
          await sendAction({ seat, action: "reorder_library_confirm", card_order: order, shuffle: true });
        });
      }
    } else {
      shuffleBtn.classList.add("hidden");
    }
  }

  buildCards();
}

function getOpponentName(state = currentState) {
  if (!state || !Array.isArray(state.players) || state.players.length < 2) {
    return "Opponent";
  }
  const viewerSeat = Number.isInteger(seat) ? seat : 0;
  const oppSeat = classicOppSeat(state, viewerSeat);
  return state.players?.[oppSeat]?.name || "Opponent";
}

function applyPriorityPromptStyle(panel, state = currentState) {
  if (!panel) return;
  panel.classList.remove("priority-self", "priority-opponent");
  if (!state || seat === null || !Number.isInteger(state.priority_player)) return;

  if (state.priority_player === seat) {
    panel.classList.add("priority-self");
  } else {
    panel.classList.add("priority-opponent");
  }
}

function renderActivationPrompt() {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const autoTapBtn = q("promptAutoTapBtn");
  const customRow = q("promptCustomRow");
  const customValue = q("promptCustomValue");
  const customOkBtn = q("promptCustomOkBtn");
  if (autoTapBtn) autoTapBtn.classList.add("hidden");
  // The OK button is shared by every prompt; restore its default label/handler
  // before dispatching so one prompt's customization (mulligan-bottom's
  // "Confirm (n/n)" text+onclick, the priority prompt's "Next Phase") can't
  // leak into the next prompt.
  okBtn.textContent = "OK";
  okBtn.onclick = null;
  const me = getCurrentPlayerState();

  // Eliminated in a still-running Free-For-All: the seat is a spectator until
  // the game ends, so no prompt applies — the spectator banner (renderBoard)
  // owns the messaging.
  if (isFfaState(currentState) && me?.lost && currentState?.winner == null) {
    panel.classList.add("hidden");
    return;
  }
  const cleanupDiscard = getCleanupDiscardInfo();
  const untapInfo = getUntapLandSelectionInfo();
  const upkeepPayInfo = getUpkeepPayInfo();
  const inCombat = currentState?.current_turn_phase === "combat";
  const combatForPrompt = getCombatState(currentState);
  const hasValidAttackers = getValidAttackerIndices(currentState).length > 0;
  const hasValidBlockers = getValidBlockerAssignments(currentState).length > 0;
  // The declaration prompt only owns the panel while the declaration is still
  // pending. Once attackers/blockers are locked the step becomes a priority
  // window, so the Priority prompt takes over (CR 508.4 / 509.4).
  const isDeclareAttackersStep =
    isCombatStep(currentState, "declare_attackers") && hasValidAttackers && !combatForPrompt?.attackers_locked;
  const isDeclareBlockersStep =
    isCombatStep(currentState, "declare_blockers") && hasValidBlockers && !combatForPrompt?.blockers_locked;
  const isCombatDeclarePromptStep = isDeclareAttackersStep || isDeclareBlockersStep;

  applyPriorityPromptStyle(panel, currentState);

  if (currentState?.lobby && !currentState.lobby.game_started) {
    // The lobby overlay owns the screen while waiting for players to join
    // and start — see updateLobbyOverlay(), driven from renderState().
    return;
  }

  const pregameInfo = getPregameInfo();
  if (pregameInfo) {
    if (pregameInfo.phase === "coin_flip") {
      applyCoinFlipPrompt(pregameInfo);
      return;
    }
    if (pregameInfo.phase === "mulligan") {
      applyMulliganPrompt(pregameInfo);
      return;
    }
    if (pregameInfo.phase === "bottom_select") {
      applyMulliganBottomPrompt(pregameInfo);
      return;
    }
  }

  const timeVaultInfo = getTimeVaultInfo();
  if (timeVaultInfo) {
    applyTimeVaultPrompt(timeVaultInfo);
    return;
  }

  if (cleanupDiscard) {
    applyCleanupPrompt(cleanupDiscard);
    return;
  }

  if (untapInfo) {
    applyUntapPrompt(untapInfo);
    return;
  }

  const optionalUntapInfo = getOptionalUntapInfo();
  if (optionalUntapInfo) {
    applyOptionalUntapPrompt(optionalUntapInfo);
    return;
  }

  const opponentDamageInfo = getOpponentDamageInfo();
  if (opponentDamageInfo) {
    applyOpponentDamagePrompt(opponentDamageInfo);
    return;
  }

  // Aladdin's Lamp and Ring of Ma'rûf have their own card-grid modal
  // (renderDrawChoiceModals), so they claim the prompt slot without rendering
  // into the text prompt panel.
  if (getLampDrawInfo() || getOutsideGameDrawInfo()) {
    panel.classList.add("hidden");
    return;
  }

  if (upkeepPayInfo) {
    applyUpkeepPayPrompt(upkeepPayInfo);
    return;
  }

  const optionalTriggerInfo = getOptionalTriggerInfo();
  if (optionalTriggerInfo) {
    applyOptionalTriggerPrompt(optionalTriggerInfo);
    return;
  }

  const upkeepPreventionInfo = getUpkeepPreventionInfo();
  if (upkeepPreventionInfo) {
    applyUpkeepPreventionPrompt(upkeepPreventionInfo);
    return;
  }

  const discardSelectInfo = getDiscardSelectInfo();
  if (discardSelectInfo) {
    applyDiscardSelectPrompt(discardSelectInfo);
    return;
  }

  const lengDiscardInfo = getLengDiscardInfo();
  if (lengDiscardInfo) {
    applyLengDiscardPrompt(lengDiscardInfo);
    return;
  }

  const commanderZoneInfo = getCommanderZoneChangeInfo();
  if (commanderZoneInfo) {
    applyCommanderZoneChangePrompt(commanderZoneInfo);
    return;
  }

  const balanceSelectInfo = getBalanceSelectInfo();
  if (balanceSelectInfo) {
    applyBalanceSelectPrompt(balanceSelectInfo);
    return;
  }

  const sacrificeSelectInfo = getSacrificeSelectInfo();
  if (sacrificeSelectInfo) {
    applySacrificeSelectPrompt(sacrificeSelectInfo);
    return;
  }

  const optionalPayInfo = getOptionalPayInfo();
  if (optionalPayInfo) {
    applyOptionalPayPrompt(optionalPayInfo);
    return;
  }

  const effectOrderInfo = getEffectOrderInfo();
  if (effectOrderInfo) {
    applyEffectOrderPrompt(effectOrderInfo);
    return;
  }

  const landTypeChoiceInfo = getLandTypeChoiceInfo();
  if (landTypeChoiceInfo) {
    applyLandTypeChoicePrompt(landTypeChoiceInfo);
    return;
  }

  const enterChoiceInfo = getEnterChoiceInfo();
  if (enterChoiceInfo) {
    applyEnterChoicePrompt(enterChoiceInfo);
    return;
  }

  const bodyChoiceInfo = getBodyChoiceInfo();
  if (bodyChoiceInfo) {
    applyBodyChoicePrompt(bodyChoiceInfo);
    return;
  }

  const leastPowerChoiceInfo = getLeastPowerChoiceInfo();
  if (leastPowerChoiceInfo) {
    applyLeastPowerChoicePrompt(leastPowerChoiceInfo);
    return;
  }

  const loyaltyRecipientInfo = getLoyaltyRecipientInfo();
  if (loyaltyRecipientInfo) {
    applyLoyaltyRecipientPrompt(loyaltyRecipientInfo);
    return;
  }

  const manaPaymentInfo = getManaPaymentInfo();
  if (manaPaymentInfo) {
    applyManaPaymentPrompt(manaPaymentInfo);
    return;
  }

  const kudzuReattachInfo = getKudzuReattachInfo();
  if (kudzuReattachInfo) {
    applyKudzuReattachPrompt(kudzuReattachInfo);
    return;
  }

  const faceDownCastInfo = getFaceDownCastInfo();
  if (faceDownCastInfo) {
    applyFaceDownCastPrompt(faceDownCastInfo);
    return;
  }

  const wordOfCommandInfo = getWordOfCommandInfo();
  if (wordOfCommandInfo) {
    applyWordOfCommandPrompt(wordOfCommandInfo);
    return;
  }

  // Raging River is resolved with Left/Right buttons drawn directly on the board
  // (see renderRagingRiver / onRiverPileClick), not through the modal panel — so
  // it deliberately has no dispatch branch here.

  const islandSanctuaryInfo = getIslandSanctuaryInfo();
  if (islandSanctuaryInfo) {
    applyIslandSanctuaryPrompt();
    return;
  }

  // Free-For-All: the attack declaration is parked while the attacking player
  // picks which opponent to swing at (see handleCombatPromptOk). One button
  // per living opponent; Cancel returns to the declare-attackers prompt.
  if (pendingAttackTarget) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    title.textContent = "Attack which player?";
    body.textContent = "Every declared attacker attacks the same opponent this combat.";
    const seatButtons = livingOpponentSeats(currentState, seat)
      .map((idx) => {
        const p = currentState?.players?.[idx] || {};
        const label = `${p.name || `Seat ${idx}`} — ${Number(p.life)} life`;
        return `<button type="button" class="prompt-choice-btn" data-attack-seat="${idx}">${escapeHtml(label)}</button>`;
      })
      .join("");
    steps.innerHTML = `<div class="prompt-choice-column">${seatButtons}</div>`;
    okBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingAutoTap) {
    panel.classList.remove("hidden");
    if (autoTapBtn) {
      autoTapBtn.classList.remove("hidden");
      const canSatisfy = !!me && canAutoTapSatisfyCost(
        pendingAutoTapCost(pendingAutoTap),
        me.mana_pool,
        me.battlefield
      );
      autoTapBtn.disabled = !canSatisfy;
    }
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    title.textContent = `Insufficient mana`;
    body.textContent = `You don't have enough mana to cast ${pendingAutoTap.cardName}. Auto-tap lands to pay the cost, or cancel.`;
    steps.innerHTML = [
      `<div>Card: ${escapeHtml(pendingAutoTap.cardName)}</div>`,
      `<div>Cost: ${renderSymbolsInline(pendingAutoTapCost(pendingAutoTap) || "none")}</div>`,
      `<div>Current mana: ${me ? formatManaSymbolsHtml(me.mana_pool) : "Unknown"}</div>`,
    ].join("");
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    okBtn.disabled = true;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingModalChoice) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    const several = pendingModalChoice.atLeast === true;
    const picked = pendingModalChoice.picked || [];
    title.textContent = several
      ? `Choose one or more — ${pendingModalChoice.cardName}`
      : `Choose one — ${pendingModalChoice.cardName}`;
    body.textContent = several
      ? "Select every mode to cast, then confirm. Each one picks its own target."
      : "Select which mode to cast.";
    const modeButtons = pendingModalChoice.modes
      .map((mode, index) => {
        const disabled = mode.supported === false ? " disabled" : "";
        const suffix = mode.supported === false ? " (unsupported)" : "";
        const on = several && picked.includes(index) ? " prompt-choice-btn-on" : "";
        const tick = several && picked.includes(index) ? "✓ " : "";
        return `<button type="button" class="prompt-choice-btn${on}" data-mode-choice="${index}"${disabled}>${tick}${escapeHtml(mode.label)}${suffix}</button>`;
      })
      .join("");
    steps.innerHTML = `<div class="prompt-choice-column">${modeButtons}</div>`;
    // A multi-select needs a confirm, because "I am done choosing" is not
    // something a click on a mode can say — the next click might be another
    // mode. A single-mode prompt is finished by the click itself and keeps its
    // disabled OK button.
    if (several) {
      okBtn.classList.remove("hidden");
      okBtn.textContent = picked.length > 1 ? `Cast ${picked.length} modes` : "Cast";
    }
    okBtn.disabled = !several || picked.length === 0;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingDiscardCost) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    title.textContent = `Additional cost — ${pendingDiscardCost.cardName}`;
    body.textContent = pendingDiscardCost.activation
      ? "Discard a card to activate this ability. Choose which."
      : "Discard a card to cast it. Choose which.";
    const cardButtons = pendingDiscardCost.options
      .map(
        (option) =>
          `<button type="button" class="prompt-choice-btn" data-discard-cost="${option.hand_index}">` +
          `${escapeHtml(option.name)}</button>`,
      )
      .join("");
    steps.innerHTML = `<div class="prompt-choice-column">${cardButtons}</div>`;
    okBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (!pendingActivation && !pendingCastTarget && !pendingCastX && !pendingManaColor && !pendingAbilityChoice && !pendingChannel) {
    const shouldShowPriority = shouldShowPriorityPrompt(currentState);
    const opponentHasPriority =
      !!currentState &&
      seat !== null &&
      Number.isInteger(currentState.priority_player) &&
      currentState.priority_player !== seat;
    const shouldShowWaitingPriority = !isCombatDeclarePromptStep && !shouldShowPriority && opponentHasPriority;

    panel.classList.toggle("hidden", !isCombatDeclarePromptStep && !shouldShowPriority && !shouldShowWaitingPriority);
    if (isCombatDeclarePromptStep) {
      if (isDeclareAttackersStep) {
        title.textContent = "Declare Attackers";
        body.textContent = "Choose your attackers and press OK to declare them.";
      } else {
        title.textContent = "Declare Blockers";
        body.textContent = "Assign your blockers and press OK to declare them.";
      }
    } else if (shouldShowPriority) {
      // Holding priority during someone else's turn: name the holder so it's clear
      // to everyone the game is paused on them (not the active player), and don't
      // mislabel the pass button as "Next Phase" — passing here just returns
      // priority to the active player, it doesn't advance to the holder's turn.
      const holdingOnOpponentTurn =
        Number.isInteger(currentState?.current_turn) && currentState.current_turn !== seat;
      const holderName = currentState?.players?.[seat]?.name || "You";
      const holdNote = holdingOnOpponentTurn
        ? `⏸ Priority is being held by ${holderName}. `
        : "";
      title.textContent = getPriorityPromptTitle(currentState);
      if (inCombat) {
        const lockedCombat = getCombatState(currentState);
        const stage = lockedCombat?.attackers_locked && !lockedCombat?.blockers_locked
          && isCombatStep(currentState, "declare_attackers")
          ? "Attackers are declared. "
          : lockedCombat?.blockers_locked && isCombatStep(currentState, "declare_blockers")
            ? "Blockers are declared. "
            : "";
        const stackEmpty = !(currentState?.stack || []).length;
        okBtn.textContent = holdingOnOpponentTurn ? "Pass Priority" : (stackEmpty ? "Next Phase" : "OK");
        const passLabel = holdingOnOpponentTurn ? "Pass Priority" : (stackEmpty ? "Next Phase" : "OK");
        body.textContent = `${holdNote}${stage}Cast an instant or activate an ability, or press ${passLabel} to ${holdingOnOpponentTurn ? "pass back" : (stackEmpty ? "move on" : "pass priority")}.`;
      } else {
        const stackEmpty = !(currentState?.stack || []).length;
        okBtn.textContent = holdingOnOpponentTurn ? "Pass Priority" : (stackEmpty ? "Next Phase" : "OK");
        const passLabel = holdingOnOpponentTurn ? "Pass Priority" : (stackEmpty ? "Next Phase" : "OK");
        body.textContent = `${holdNote}Take an action (cast a spell, activate an ability, or play a land for turn), or press ${passLabel} to ${holdingOnOpponentTurn ? "pass back" : (stackEmpty ? "move on" : "pass priority")}.`;
      }
    } else if (shouldShowWaitingPriority) {
      // Name the seat that actually holds priority — in FFA any opponent can,
      // so the classic top-left opponent's name (getOpponentName) is often wrong.
      const holderName =
        currentState.players?.[currentState.priority_player]?.name || getOpponentName(currentState);
      title.textContent = `Waiting for ${holderName}...`;
      body.textContent = `${holderName} has priority.`;
    } else {
      title.textContent = "No pending activation.";
      body.textContent = "Select an activated ability to begin paying its cost.";
    }
    steps.innerHTML = "";
    customRow.classList.add("hidden");
    okBtn.classList.toggle("hidden", shouldShowWaitingPriority);
    okBtn.disabled = shouldShowWaitingPriority || (!combatPromptNeedsConfirmation(currentState) && !shouldShowPriority);
    cancelBtn.classList.add("hidden");
    cancelBtn.disabled = true;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingCastTarget) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    // A "sacrifice a <type>" cost (Diamond Valley, Atog, Metamorphosis) picks a
    // permanent the same way, but it is a cost being paid, not a target.
    // **The type comes from the spec**, never the word "creature": Atog eats an
    // artifact and Dwarven Weaponsmith's second prompt does too, so a fixed noun
    // told the player to look for something the picker was not offering.
    const pendingCostStage = !!(pendingCastTarget.__costOnly || pendingCastTarget.__costStage);
    const pendingSpec = targetSpecOf(pendingCastTarget.card);
    const costSpec = pendingCostStage
      ? (pendingSpec?.cost_spec || pendingSpec)
      : null;
    const isSacrificeCost = !!(costSpec?.sacrifice_cost || pendingSpec?.sacrifice_cost);
    const sacrificeNoun = costSpec?.kind || pendingSpec?.kind || "permanent";
    title.textContent = isSacrificeCost
      ? `Choose ${/^[aeiou]/.test(sacrificeNoun) ? "an" : "a"} ${sacrificeNoun} to sacrifice for ${pendingCastTarget.cardName}`
      : `Choose target for ${pendingCastTarget.cardName}`;
    if (pendingCastTarget.targetKind === "land") {
      body.textContent = "Click a valid land on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "creature") {
      body.textContent = isSacrificeCost
        ? `Click ${/^[aeiou]/.test(sacrificeNoun) ? "an" : "a"} ${sacrificeNoun} you control on the battlefield to sacrifice it.`
        : "Click a valid creature on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "artifact") {
      body.textContent = "Click a valid artifact on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "permanent") {
      const isEnchantEnchantment = String(pendingCastTarget.card?.oracle_text || "")
        .toLowerCase()
        .includes("enchant enchantment");
      body.textContent = isSacrificeCost
        ? `Click ${/^[aeiou]/.test(sacrificeNoun) ? "an" : "a"} ${sacrificeNoun} you control on the battlefield to sacrifice it.`
        : pendingCastTarget.alsoStack
        ? "Click a permanent on the battlefield, or a glowing spell on the stack, to choose the target."
        : isEnchantEnchantment
        ? "Click a glowing enchantment on the battlefield to choose the target."
        : "Click any permanent on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "any") {
      body.textContent = "Click a creature on the battlefield, or click a player's life pill (glowing yellow) to target them.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "divided") {
      body.textContent =
        "Click creatures to split the damage among them, or click a player's life pill to hit their face. Then confirm to choose X.";
      const n = dividedTargetCount();
      steps.innerHTML = [
        `<div>Card: ${escapeHtml(pendingCastTarget.cardName)}</div>`,
        `<div>${escapeHtml(dividedTargetsHint())}</div>`,
        `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="dividedConfirmBtn"${n === 0 ? " disabled" : ""}>Confirm targets</button></div>`,
      ].join("");
      const confirmBtn = document.getElementById("dividedConfirmBtn");
      if (confirmBtn) confirmBtn.addEventListener("click", confirmDividedTargets);
      cancelBtn.classList.remove("hidden");
      cancelBtn.disabled = false;
      customOkBtn.disabled = true;
      return;
    } else if (pendingCastTarget.targetKind === "several") {
      body.textContent =
        `Click up to ${pendingCastTarget.maxTargets} valid permanents to choose them, then confirm. ` +
        "Click a chosen one again to deselect it.";
      steps.innerHTML = [
        `<div>Card: ${escapeHtml(pendingCastTarget.cardName)}</div>`,
        `<div>${escapeHtml(severalTargetsHint())}</div>`,
        `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="severalConfirmBtn">Confirm targets</button></div>`,
      ].join("");
      // Never disabled: "up to N" may legally choose none (CR 601.2c), so
      // confirming with nothing selected has to be reachable.
      const severalBtn = document.getElementById("severalConfirmBtn");
      if (severalBtn) severalBtn.addEventListener("click", confirmSeveralTargets);
      cancelBtn.classList.remove("hidden");
      cancelBtn.disabled = false;
      customOkBtn.disabled = true;
      return;
    } else if (pendingCastTarget.targetKind === "stack") {
      body.textContent = "Click a glowing spell on the stack to choose which one to target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "graveyard_creature") {
      // Regrowth targets any card; Animate Dead / Resurrection a creature card;
      // Reconstruction an artifact card. Never fall through to the
      // player-select fallback — the target is always a card in a graveyard,
      // not a player.
      const spec = targetSpecOf(pendingCastTarget.card);
      const noun = graveyardCardNoun(spec);
      const where = spec?.own_graveyard_only ? "your graveyard" : "a graveyard";
      if (pendingCastTarget.severalGraveyard) {
        // "Up to N": an accumulate-and-confirm prompt, for the same reason the
        // several-permanents one is — the caster may legally stop short of the
        // maximum, and a one-click picker has nowhere to put that decision.
        body.textContent =
          `Click up to ${pendingCastTarget.maxTargets} glowing ${noun}s in ${where} to choose them, then confirm. ` +
          "Click a chosen one again to deselect it.";
        steps.innerHTML = [
          `<div>Card: ${escapeHtml(pendingCastTarget.cardName)}</div>`,
          `<div>${escapeHtml(severalGraveyardHint())}</div>`,
          `<div class="prompt-choice-row"><button type="button" class="prompt-choice-btn" id="severalGraveyardConfirmBtn">Confirm targets</button></div>`,
        ].join("");
        // Never disabled: "up to N" may legally choose none (CR 601.2c).
        const graveyardBtn = document.getElementById("severalGraveyardConfirmBtn");
        if (graveyardBtn) graveyardBtn.addEventListener("click", confirmSeveralGraveyardTargets);
        cancelBtn.classList.remove("hidden");
        cancelBtn.disabled = false;
        customOkBtn.disabled = true;
        return;
      }
      body.textContent = `Click a glowing ${noun} in ${where} to choose the target.`;
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else {
      const players = Array.isArray(currentState?.players) ? currentState.players : [];
      // Only seats the backend listed as legal — "target opponent" (Word of
      // Command) excludes the caster's own seat, and a dead seat is nobody's
      // legal target. An empty/absent list means every seat is fair game.
      const legalSeats = pendingCastTarget.validPlayerSeats;
      const targetButtons = players
        .map((player, index) => {
          if (legalSeats && legalSeats.size > 0 && !legalSeats.has(index)) return "";
          const label = player?.name || `Seat ${index}`;
          return `<button type="button" class="prompt-choice-btn" data-target-choice="${index}">${escapeHtml(label)}</button>`;
        })
        .join("");
      body.textContent = "Select a player to target.";
      steps.innerHTML = [
        `<div>Card: ${pendingCastTarget.cardName}</div>`,
        `<div class="prompt-choice-row">${targetButtons}</div>`,
      ].join("");
    }
    okBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingChannel) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    title.textContent = "Channel";
    setSymbolsHtml(body, "Pay 1 life per {C}. Choose how much life to pay.");
    const maxBtn = Math.min(Number(pendingChannel.maxLife || 1), 10);
    const choiceButtons = [];
    for (let value = 1; value <= maxBtn; value += 1) {
      choiceButtons.push(`<button type="button" class="prompt-choice-btn" data-channel-life="${value}">${value}</button>`);
    }
    choiceButtons.push('<button type="button" class="prompt-choice-btn" data-channel-life="custom">Custom...</button>');
    steps.innerHTML = [
      `<div>Max life payable: ${pendingChannel.maxLife}</div>`,
      `<div>Each life adds ${renderSymbolsInline("{C}")}.</div>`,
      `<div class="prompt-choice-row">${choiceButtons.join("")}</div>`,
    ].join("");
    customRow.classList.toggle("hidden", !pendingChannel.awaitingCustomValue);
    customValue.max = String(pendingChannel.maxLife);
    customValue.min = "1";
    customValue.value = String(Math.min(Math.max(Number(customValue.value || 1), 1), pendingChannel.maxLife));
    okBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = !pendingChannel.awaitingCustomValue;
    return;
  }

  if (pendingCastX) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    title.textContent = `Choose X for ${pendingCastX.cardName}`;
    // A loyalty "−X" is paid in counters, so its ceiling is the loyalty on the
    // permanent (CR 606.6) and no amount of tapping raises it. Everything else
    // recomputes the ceiling from the live mana pool: tapping more lands while
    // the prompt is open grows the range of X choices on the next render.
    if (pendingCastX.loyalty) {
      pendingCastX.maxX = currentLoyaltyOf(pendingCastX.card);
      body.textContent =
        `${pendingCastX.cardName} has ${pendingCastX.maxX} loyalty, and X counters are removed to pay for this ability.`;
    } else {
      if (pendingCastX.costString !== undefined) {
        const liveMax = getMaxAffordableX(me?.mana_pool, pendingCastX.costString, pendingCastX.costCard);
        pendingCastX.maxX = Math.max(0, liveMax - Math.max(0, pendingCastX.extraTargetTax || 0));
      }
      const xColor = xSpendColorForCard(pendingCastX.card);
      const xColorName = xColor ? { W: "white", U: "blue", B: "black", R: "red", G: "green" }[xColor] : null;
      body.textContent = xColorName
        ? `You have ${pendingCastX.maxX} ${xColorName} mana available for X (only ${xColorName} mana may be spent on X). Tap more mana sources to raise the limit.`
        : `You have ${pendingCastX.maxX} mana available for X after paying the colored cost. Tap more mana sources to raise the limit.`;
    }
    const choiceButtons = [];
    for (let value = 0; value <= pendingCastX.maxX; value += 1) {
      choiceButtons.push(`<button type="button" class="prompt-choice-btn" data-x-choice="${value}">${value}</button>`);
    }
    choiceButtons.push('<button type="button" class="prompt-choice-btn" data-x-choice="custom">Custom...</button>');
    steps.innerHTML = (
      pendingCastX.loyalty
        ? [
          `<div>Cost: ${escapeHtml(loyaltySymbolText(loyaltyCostOfChosenAbility(pendingCastX.card)))}</div>`,
          `<div>Loyalty: ${currentLoyaltyOf(pendingCastX.card)}</div>`,
          `<div class="prompt-choice-row">${choiceButtons.join("")}</div>`,
        ]
        : [
          `<div>Cost: ${renderSymbolsInline(pendingCastX.card.mana_cost || "none")}</div>`,
          `<div>Needed: ${formatManaSymbolsHtml(pendingCastX.manaRequirement || {})}</div>`,
          `<div>Current mana: ${me ? formatManaSymbolsHtml(me.mana_pool) : "Unknown"}</div>`,
          `<div class="prompt-choice-row">${choiceButtons.join("")}</div>`,
        ]
    ).join("");
    customRow.classList.toggle("hidden", !pendingCastX.awaitingCustomValue);
    customValue.max = String(pendingCastX.maxX);
    customValue.value = String(Math.min(Number(customValue.value || 0), pendingCastX.maxX));
    okBtn.disabled = true;
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = !pendingCastX.awaitingCustomValue;
    return;
  }

  if (pendingAbilityChoice) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    const choiceCard = pendingAbilityChoice.card;
    if (pendingAbilityChoice.loyalty) {
      // A loyalty menu reads like the card does: the cost symbol on the left as
      // the button, the ability it buys spelled out beside it.
      title.textContent = `Activate a loyalty ability of ${pendingAbilityChoice.cardName}`;
      body.textContent = `Loyalty: ${currentLoyaltyOf(choiceCard)}`;
      steps.innerHTML = [
        `<div class="loyalty-ability-list">${pendingAbilityChoice.options
          .map((opt) => {
            const disabledReason = abilityOptionDisabledReason(opt, choiceCard);
            const disabledAttrs = disabledReason
              ? ` disabled title="${escapeHtml(disabledReason)}"`
              : "";
            const sign = opt.loyalty && opt.loyalty.delta !== null && opt.loyalty.delta > 0 ? "up" : "down";
            // The reason stays on the button's title so a hover still explains
            // the greying, but it is not spelled out under the ability: a card
            // that reads "−6" beside a loyalty of 4 has already said it.
            return `<div class="loyalty-ability-row${disabledReason ? " is-disabled" : ""}">`
              + `<button type="button" class="loyalty-cost-btn loyalty-${sign}" `
              + `data-ability-choice="${opt.index}"${disabledAttrs}>${escapeHtml(opt.cost)}</button>`
              + `<div class="loyalty-ability-text">${escapeHtml(opt.text)}</div></div>`;
          })
          .join("")}</div>`,
      ].join("");
    } else {
      title.textContent = `Choose an ability for ${pendingAbilityChoice.cardName}`;
      body.textContent = "This permanent has more than one activated ability. Pick which one to activate.";
      steps.innerHTML = [
        `<div>Card: ${escapeHtml(pendingAbilityChoice.cardName)}</div>`,
        `<div class="prompt-choice-row">${pendingAbilityChoice.options
          .map(
            (opt) => {
              const disabledReason = abilityOptionDisabledReason(opt, choiceCard);
              const disabledAttrs = disabledReason
                ? ` disabled title="${escapeHtml(disabledReason)}"`
                : "";
              return `<button type="button" class="prompt-choice-btn" data-ability-choice="${opt.index}"${disabledAttrs}>` +
                `${renderSymbolsInline(opt.cost)}: ${escapeHtml(opt.text)}</button>`;
            },
          )
          .join("")}</div>`,
      ].join("");
    }
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingManaColor) {
    // The dual-land choice is presented as an on-board mana fan, not a modal;
    // keep the prompt panel out of the way while the fan is up.
    if (pendingManaColor.fan) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    if (pendingManaColor.kind === "cast") {
      const noun = pendingManaColor.isLandType ? "land type" : "color word";
      if (pendingManaColor.step === "from") {
        title.textContent = `Choose the ${noun} to replace in ${pendingManaColor.cardName}'s target`;
        body.textContent = `Select the current ${noun} named in the target's text.`;
      } else {
        title.textContent = `Choose the new ${noun} for ${pendingManaColor.cardName}`;
        body.textContent = `Select the ${noun} to replace it with.`;
      }
    } else {
      title.textContent = `Choose mana color for ${pendingManaColor.cardName}`;
      body.textContent = "Select the mana color this ability should generate.";
    }
    steps.innerHTML = [
      `<div>Ability: ${renderSymbolsInline(pendingManaColor.oracleText || "Activated mana ability")}</div>`,
      `<div class="prompt-choice-row">${(pendingManaColor.colorOptions || MANA_COLOR_OPTIONS).map(
        ({ symbol, label }) => {
          const token = `{${symbol}}`;
          const src = symbolSrc(token);
          const symbolHtml = src
            ? `<img class="mtg-symbol mtg-symbol-inline" src="${escapeHtml(src)}" alt="${escapeHtml(token)}" title="${escapeHtml(token)}" />`
            : escapeHtml(`{${symbol}}`);
          return `<button type="button" class="prompt-choice-btn" data-mana-color="${symbol}">${escapeHtml(label)} ${symbolHtml}</button>`;
        },
      ).join("")}</div>`,
    ].join("");
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  panel.classList.remove("hidden");
  okBtn.classList.remove("hidden");
  const manaRequirement = pendingActivation.manaRequirement || {};
  const canPay = me ? manaPoolCanPayCost(me.mana_pool, manaRequirement) : false;

  title.textContent = `Pay activation cost for ${pendingActivation.cardName}`;
  body.textContent = pendingActivation.awaitingApproval
    ? "Press OK to start paying this activation cost."
    : canPay
      ? "Cost is covered. The activation will be submitted automatically."
      : "Use board actions to generate the missing mana, then this prompt will complete the activation automatically.";
  steps.innerHTML = [
    `<div>Cost: ${renderSymbolsInline(pendingActivation.activationCost || "none")}</div>`,
    `<div>Needed: ${formatManaSymbolsHtml(manaRequirement)}</div>`,
    `<div>Current mana: ${me ? formatManaSymbolsHtml(me.mana_pool) : "Unknown"}</div>`,
    `<div>Action: ${pendingActivation.awaitingApproval ? "press OK to start paying, then click lands or other mana sources." : "click lands or other mana sources, then wait for the activation to resolve."}</div>`,
  ].join("");
  customRow.classList.add("hidden");
  okBtn.disabled = !pendingActivation.awaitingApproval;
  cancelBtn.classList.remove("hidden");
  cancelBtn.disabled = false;
  customOkBtn.disabled = true;
}

async function attemptPendingActivation() {
  if (!pendingActivation || seat === null) return;
  if (pendingActivation.awaitingApproval) {
    renderActivationPrompt();
    return;
  }
  const me = getCurrentPlayerState();
  if (!me) return;

  if (!manaPoolCanPayCost(me.mana_pool, pendingActivation.manaRequirement)) {
    renderActivationPrompt();
    return;
  }

  const pending = pendingActivation;
  pendingActivation = null;
  renderActivationPrompt();
  updateActionHint(`Submitting activation for ${pending.cardName}...`);

  try {
    const activateBody = withPermanentId(
      {
        seat,
        action: "activate",
        permanent_name: pending.cardName,
        permanent_index: pending.permanentIndex,
        target_seat: pending.targetSeat,
      },
      "permanent_id", seat, pending.permanentIndex,
    );
    if (Number.isInteger(pending.abilityIndex)) activateBody.ability_index = pending.abilityIndex;
    await sendAction(activateBody);
    updateActionHint(`Activated ${pending.cardName}.`);
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

// Activate a Guardian Angel emblem ("pay {1}: prevent next 1 damage"). The
// ability is locked to the original spell's target ("that permanent or player"),
// so there is no target prompt: clicking just pays {1} (auto-tapping lands if
// needed) and the engine applies the shield to the stored target.
function startEmblemActivation(emblemIndex) {
  if (!currentState || seat === null) return;
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingAutoTap || pendingModalChoice || pendingAbilityChoice || pendingChannel) {
    updateActionHint("Finish the current action first.", true);
    return;
  }
  if (currentState.priority_player !== seat) {
    SFX.onError();
    updateActionHint("You can only use the emblem when you have priority (instant speed).", true);
    return;
  }
  const actionBody = { seat, action: "activate_emblem", emblem_index: emblemIndex };
  updateActionHint("Activating Guardian Angel emblem...");
  sendAction(actionBody)
    .then(() => updateActionHint("Activated Guardian Angel emblem."))
    .catch((e) => {
      if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
        // Reuse the cast auto-tap flow to pay {1}.
        const pseudoCard = { name: "Guardian Angel emblem", mana_cost: "{1}" };
        pendingAutoTap = { card: pseudoCard, cardName: "Guardian Angel emblem", actionBody };
        renderActivationPrompt();
        return;
      }
      updateActionHint(e.message, true);
    });
}

// Channel emblem: "any time you could activate a mana ability, you may pay 1 life.
// If you do, add {C}." Prompt for how many life to pay (default 1) and add that
// many {C}. Needs priority, like any mana ability used at instant speed here.
function startChannelMana() {
  if (!currentState || seat === null) return;
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingAutoTap || pendingModalChoice || pendingAbilityChoice || pendingChannel) {
    updateActionHint("Finish the current action first.", true);
    return;
  }
  if (currentState.priority_player !== seat) {
    SFX.onError();
    updateActionHint("You can only use Channel when you have priority.", true);
    return;
  }
  const me = currentState.players?.[seat];
  // You may pay your entire life total (CR 118.4); dying to it is legal.
  const maxLife = Math.max(1, me?.life ?? 1);
  // Use the in-game prompt dialog (not window.prompt): pick how much life to pay.
  pendingChannel = { maxLife, awaitingCustomValue: false };
  renderActivationPrompt();
}

function resolveChannel(amount) {
  if (!pendingChannel) return;
  const maxLife = Number(pendingChannel.maxLife || 1);
  const value = Math.floor(Number(amount));
  if (!Number.isFinite(value) || value < 1 || value > maxLife) {
    updateActionHint(`Choose between 1 and ${maxLife} life to pay.`, true);
    return;
  }
  pendingChannel = null;
  renderActivationPrompt();
  updateActionHint(`Channeling ${value} life for {C}...`);
  sendAction({ seat, action: "channel_mana", x_value: value })
    .then(() => updateActionHint(`Added ${value} {C} via Channel.`))
    .catch((e) => updateActionHint(e.message, true));
}

// A loyalty-ability cost line: "+1: …", "−2: …", "0: …", "−X: …" (CR 606.2).
// Mirrors the engine's _LOYALTY_LINE_RE, and like it reads only a planeswalker's
// lines: everything left of the colon must be the one loyalty symbol, so an
// ordinary "{2}, {T}:" cost is never mistaken for one. Both minus signs are
// accepted — printed oracle text uses U+2212, hand-typed text a hyphen.
const LOYALTY_COST_RE = /^([+\-−]?\s*(?:\d+|[xX]))\s*:\s*(.+)$/;

function isPlaneswalkerCard(card) {
  if (!card || typeof card === "string") return false;
  if (card.is_planeswalker === true) return true;
  return /planeswalker/i.test(String(card.type || card.type_line || ""));
}

// The signed cost a loyalty symbol names (CR 606.4): how many counters
// activating puts on (positive) or removes (negative). `xSign` is set instead of
// `delta` when the amount is X, whose value the player chooses on activation.
function loyaltyCostOf(costText) {
  const m = String(costText || "").trim().match(/^([+\-−]?)\s*(\d+|[xX])$/);
  if (!m) return null;
  const sign = (m[1] === "-" || m[1] === "−") ? -1 : 1;
  if (/^[xX]$/.test(m[2])) return { delta: null, xSign: sign };
  return { delta: sign * Number(m[2]), xSign: null };
}

// Loyalty counters currently on a planeswalker, off the generic counters map.
function currentLoyaltyOf(card) {
  if (!card || typeof card === "string") return 0;
  return Number(card.counters?.loyalty ?? 0);
}

// A loyalty cost back as the symbol the card prints it as ("+1", "−2", "0",
// "−X"), for hints and log lines.
function loyaltySymbolText(cost) {
  if (!cost) return "";
  if (cost.xSign !== null) return `${cost.xSign < 0 ? "−" : "+"}X`;
  if (cost.delta > 0) return `+${cost.delta}`;
  if (cost.delta < 0) return `−${-cost.delta}`;
  return "0";
}

// The loyalty symbol on the ability being activated, for the flows below that
// must not treat it as a mana cost. `__abilityIndex` is set on the synthetic
// single-ability card resolveAbilityChoice builds, so this reads that one line.
function loyaltyCostOfChosenAbility(card) {
  if (!isPlaneswalkerCard(card)) return null;
  if (card?.__loyaltyCost) return card.__loyaltyCost;
  const options = getActivatedAbilityOptions(card);
  return options.length === 1 ? (options[0].loyalty || null) : null;
}

// Parse the activated-ability lines ("{cost}: effect") of a card's oracle text,
// plus a planeswalker's loyalty lines ("+1: effect").
// Index matches the engine's order of supported activated abilities, so it can be
// sent back as `ability_index` (Rock Hydra: 0 = {R} prevention, 1 = {R}{R}{R} +1/+1).
function getActivatedAbilityOptions(card) {
  if (!card || typeof card === "string") return [];
  const options = [];
  const planeswalker = isPlaneswalkerCard(card);
  let index = 0;
  const lines = activatedAbilityText(card).split("\n");
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    const m = line.match(/^\s*((?:\{[^}]+\}[,\s]*)+):\s*(.+)$/);
    if (!m) {
      // A loyalty cost is counters rather than mana, so its half of the line
      // carries no symbols and the brace pattern above never matches it.
      const lm = planeswalker ? line.trim().match(LOYALTY_COST_RE) : null;
      if (!lm) continue;
      const cost = lm[1].replace(/\s+/g, "");
      options.push({
        index, cost, text: lm[2].trim(), line: line.trim(), loyalty: loyaltyCostOf(cost),
      });
      index += 1;
      continue;
    }
    // Modal activated ability (Pyramids: "{2}: Choose one —" + bullets):
    // one option per bullet, sharing the cost — matching the engine, which
    // compiles each bullet as its own activated ability.
    if (/^choose one\b/i.test(m[2].trim())) {
      let consumedBullets = false;
      let j = li + 1;
      while (j < lines.length && lines[j].trim().startsWith("•")) {
        const text = lines[j].trim().replace(/^•\s*/, "");
        options.push({ index, cost: m[1].trim(), text, line: `${m[1].trim()}: ${text}` });
        index += 1;
        consumedBullets = true;
        j += 1;
      }
      if (consumedBullets) {
        li = j - 1;
        continue;
      }
    }
    options.push({ index, cost: m[1].trim(), text: m[2].trim(), line: line.trim() });
    index += 1;
  }
  return options;
}

// Mirror of the engine's per-ability activation gates (queue_permanent_ability):
// given one ability's text, the reason it can't be activated RIGHT NOW, or null.
// Used to grey menu buttons and to fail fast before a doomed request.
function activationTimingDisabledReason(lineText) {
  const line = (lineText || "").toLowerCase();
  if (!currentState || seat === null) return null;
  const myTurn = currentState.current_turn === seat;
  const phase = currentState.current_turn_phase;
  const step = currentState.current_step;

  if (line.includes("activate only during your upkeep") && !(myTurn && step === "upkeep")) {
    return "Can only be activated during your upkeep.";
  }
  if (line.includes("only during your turn") && !myTurn) {
    return "Can only be activated during your turn.";
  }
  if (line.includes("activate only as a sorcery")) {
    const stackEmpty = !(currentState.stack || []).length;
    if (!(myTurn && currentState.current_phase === "main" && stackEmpty)) {
      return "Can only be activated as a sorcery (your main phase, empty stack).";
    }
  }
  if (line.includes("activate only during the end of combat step") && step !== "end_of_combat") {
    return "Can only be activated during the end of combat step.";
  }
  if (
    line.includes("activate only during combat")
    && !line.includes("end of combat")
    && phase !== "combat"
  ) {
    return "Can only be activated during combat.";
  }
  if (line.includes("activate only during an opponent's turn, before attackers are declared")) {
    const combat = getCombatState(currentState);
    const beforeAttackers =
      phase === "beginning"
      || phase === "precombat_main"
      || (
        phase === "combat"
        && (step === "beginning_of_combat" || step === "declare_attackers")
        && !combat?.attackers_locked
      );
    if (myTurn || !beforeAttackers) {
      return "Can only be activated during an opponent's turn, before attackers are declared.";
    }
  }
  return null;
}

// Every reason one ability line can't be activated right now: the engine's
// activation-timing gates plus the non-timing cost restrictions (Library of
// Alexandria's exact hand size, Jandor's Ring's "discard the last card you drew
// this turn" additional cost). Null when it is activatable.
function abilityLineDisabledReason(line) {
  if (/activate only if you have exactly seven cards in hand/i.test(line || "")) {
    const handCount = Number(getCurrentPlayerState()?.hand_count ?? getCurrentPlayerState()?.hand?.length ?? 0);
    if (handCount !== 7) {
      return `Requires exactly seven cards in hand (you have ${handCount}).`;
    }
  }
  if (/discard the last card you drew this turn/i.test(line || "")) {
    if (!getCurrentPlayerState()?.has_last_drawn_card) {
      return "No card you drew this turn is still in hand to discard.";
    }
  }
  return activationTimingDisabledReason(line);
}

// Why one loyalty ability of `card` can't be activated right now, or null.
// Mirrors the engine's gate in mixins/stack/activation.py, so a button this
// greys out and a request the engine would refuse are the same set: the
// sorcery-speed window and the once-per-turn limit (CR 606.3) rule out every
// ability on the permanent, and a minus cost bigger than the loyalty on it
// rules out that one (CR 606.6). The two pieces of state a client can't derive
// — whether a loyalty ability was already used this turn, and whether the card
// widens its own timing window — ride along on the permanent payload.
//
// The whole-permanent halves are also refused up front, before the menu opens,
// so in practice this answers the per-ability half. Both stay here because
// resolveAbilityChoice checks this one function before sending anything, and a
// mirror missing a rule the engine has is how a button starts promising more
// than the engine will do.
function loyaltyAbilityDisabledReason(card, opt) {
  const cost = opt?.loyalty;
  if (!cost || !currentState || seat === null) return null;

  if (!card?.loyalty_any_time) {
    const myTurn = currentState.current_turn === seat;
    const stackEmpty = !(currentState.stack || []).length;
    if (!(myTurn && currentState.current_phase === "main" && stackEmpty)) {
      return "Loyalty abilities can only be activated during a main phase of your turn with the stack empty (CR 606.3).";
    }
  }
  if (card?.loyalty_ability_used_this_turn) {
    return "This planeswalker has already activated a loyalty ability this turn (CR 606.3).";
  }
  // "−X" is affordable at X = 0 whatever the loyalty is; the X prompt caps the
  // value at the counters actually on the permanent.
  if (cost.delta !== null && cost.delta < 0) {
    const loyalty = currentLoyaltyOf(card);
    if (loyalty < -cost.delta) {
      return `Not enough loyalty: this ability costs ${-cost.delta} and ${normalizeCardName(card)} has ${loyalty} (CR 606.6).`;
    }
  }
  return null;
}

// Per-option gate for the multi-ability menu.
function abilityOptionDisabledReason(opt, card) {
  if (opt?.loyalty) return loyaltyAbilityDisabledReason(card, opt);
  return abilityLineDisabledReason(opt.line);
}

function resolveAbilityChoice(optionIndex) {
  if (!pendingAbilityChoice) return;
  const pending = pendingAbilityChoice;
  const opt = pending.options.find((o) => o.index === optionIndex);
  if (!opt) return;
  // The button was greyed out, so this is a keyboard or stale-render route into
  // an option the engine would refuse. Say why instead of sending it.
  const disabledReason = abilityOptionDisabledReason(opt, pending.card);
  if (disabledReason) {
    SFX.onError();
    updateActionHint(`${pending.cardName}: ${disabledReason}`, true);
    return;
  }
  pendingAbilityChoice = null;
  // Recurse with a single-ability synthetic card so the normal target/cost flow
  // handles just the chosen ability; __abilityIndex is threaded into the action.
  // __loyaltyCost carries the chosen line's loyalty symbol, which the synthetic
  // card's own text can no longer be indexed for — it holds one line, so
  // re-parsing it would number that line 0 whichever ability was picked.
  const singleAbilityCard = {
    ...pending.card,
    oracle_text: opt.line,
    __abilityIndex: opt.index,
    __loyaltyCost: opt.loyalty || null,
  };
  // Multi-ability cards whose abilities target differently (Pyramids) carry a
  // per-ability spec; swap it in so the target flow prompts for THIS ability.
  const perAbilitySpecs = pending.card?.ability_target_specs;
  if (Array.isArray(perAbilitySpecs) && perAbilitySpecs[opt.index]) {
    singleAbilityCard.target_spec = perAbilitySpecs[opt.index];
  }
  startActivationPrompt(singleAbilityCard, pending.targetSeat, pending.permanentIndex);
}

function startActivationPrompt(card, targetSeat, permanentIndex = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  // Cards with more than one activated ability (Rock Hydra, Basalt Monolith) must
  // let the player choose which ability to use before paying any cost. A
  // planeswalker asks even when it has only one loyalty ability: the cost is
  // spent out of the walker's own loyalty and the once-per-turn limit means
  // there is no second chance, so it is never a choice to make on the player's
  // behalf.
  if (!Number.isInteger(card?.__abilityIndex)) {
    const abilityOptions = getActivatedAbilityOptions(card);
    const loyaltyMenu = abilityOptions.some((opt) => opt.loyalty);
    // The once-per-turn half of CR 606.3 rules out every ability at once, so it
    // is a refusal rather than a menu — a walker that has already gone this
    // turn says so on selection instead of opening a list of dead buttons.
    if (loyaltyMenu && card?.loyalty_ability_used_this_turn) {
      SFX.onError();
      updateActionHint(
        `${cardName} has already activated a loyalty ability this turn (CR 606.3).`, true,
      );
      return;
    }
    if (abilityOptions.length >= (loyaltyMenu ? 1 : 2)) {
      pendingAbilityChoice = {
        card, cardName, targetSeat, permanentIndex, options: abilityOptions, loyalty: loyaltyMenu,
      };
      renderActivationPrompt();
      return;
    }
  }
  const abilityIndex = Number.isInteger(card?.__abilityIndex) ? card.__abilityIndex : null;

  // A {T} ability can't be activated while the creature is summoning sick
  // (CR 302.6). When the only way to use the card is a tap ability, don't open a
  // prompt that's doomed to fail — play the error sound and say why.
  if (card && card.summoning_sick && abilityCostRequiresTap(card)) {
    SFX.onError();
    updateActionHint(`${cardName} has summoning sickness and can't use its tap ability yet.`, true);
    return;
  }

  // Activation gates (Jade Statue's combat-only, Illusionary Mask's
  // sorcery-speed, Jandor's Ring's discard cost, ...): fail fast with the reason
  // instead of a doomed request.
  {
    const gateReason = abilityLineDisabledReason(card?.oracle_text);
    if (gateReason) {
      SFX.onError();
      updateActionHint(`${cardName}: ${gateReason}`, true);
      return;
    }
  }

  // A "Discard a card:" activation cost (Seasoned Hallowblade) is paid from
  // hand, so it takes the same prompt the cast-side additional cost does. It
  // comes before the target cascades because CR 602.2b announces the cost
  // first, and because the ability whose spec reports it has no target of its
  // own — a card needing both prompts runs them in sequence instead (below).
  if (cardRequiresDiscardCost(card) &&
      startActivationDiscardCostPrompt(card, cardName, permanentIndex, abilityIndex)) {
    return;
  }

  // A "Sacrifice a/an <type>" activation cost whose ability targets nothing
  // else (Atog, Hobblefiend, Witch's Cauldron, Diamond Valley): the whole
  // choice is which permanent pays, so it takes the ordinary permanent picker
  // with the answer on the cost field. Without this the player was never asked
  // and the deterministic default paid — with Atog on a board holding a Black
  // Lotus and a Mox, it took the Lotus.
  {
    const spec = targetSpecOf(card);
    if (spec.sacrifice_cost) {
      const fields = pendingTargetFields(card);
      if (fields.validKeys.size === 0) {
        SFX.onError();
        updateActionHint(`${cardName} has nothing it can sacrifice for its cost.`, true);
        return;
      }
      pendingCastTarget = {
        card, cardName, targetKind: "permanent", castAction: "activate",
        sourcePermanentIndex: permanentIndex, abilityIndex,
        __costOnly: true, ...fields,
      };
      renderActivationPrompt();
      renderBoard(currentState);
      return;
    }
  }

  // "{G}: Exile target card from a graveyard." (Scavenging Ooze; also Epitaph
  // Golem, Obsessive Stitcher, Liliana Death Mage, Chandra Flame's Catalyst.)
  // The clickable surface is the zone-reveal panel rather than the canvas, so
  // this reuses the cast-side prompt and every branch below it stays a
  // battlefield picker. Without it the ability was sent with no target at all
  // and the engine's stale-choice fallback took the first legal card.
  if (cardRequiresTargetGraveyardCreature(card)) {
    startCastGraveyardCreatureTargetPrompt(card, "activate", {
      sourcePermanentIndex: permanentIndex, abilityIndex,
    });
    return;
  }

  // Activated abilities that destroy a target creature (e.g. Royal Assassin)
  // must let the player choose which creature before the ability is activated.
  // The permanent's activation target_spec supplies the kind and legal targets.
  if (activatedAbilityRequiresTargetCreature(card)) {
    const fields = pendingTargetFields(card);
    if (fields.validKeys.size === 0) {
      updateActionHint(`No valid creature targets in play for ${cardName}.`, true);
      return;
    }
    pendingCastTarget = {
      card, cardName, targetKind: "creature", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...fields,
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that destroy a target permanent of a given color (Northern Paladin:
  // "Destroy target black permanent."): the backend already restricts the legal
  // targets to the required colour.
  if (activatedAbilityRequiresTargetPermanent(card)) {
    const fields = pendingTargetFields(card);
    // Circle of Protection's "source of your choice" may be a permanent or a spell
    // on the stack (also_stack), so it stays activatable when only a stack source exists.
    const alsoStack = !!targetSpecOf(card).also_stack;
    if (fields.validKeys.size === 0 && !(alsoStack && fields.validStackIndices.size > 0)) {
      updateActionHint(`No valid source for ${cardName} — nothing of that color to prevent.`, true);
      return;
    }
    pendingCastTarget = {
      card, cardName, targetKind: "permanent", castAction: "activate", alsoStack,
      sourcePermanentIndex: permanentIndex, abilityIndex, ...fields,
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that target an artifact (Aladdin's "Gain control of target
  // artifact"): the backend restricts the list to artifacts it could legally take.
  if (activatedAbilityRequiresTargetArtifact(card)) {
    const fields = pendingTargetFields(card);
    if (fields.validKeys.size === 0) {
      updateActionHint(`No valid artifact targets in play for ${cardName}.`, true);
      return;
    }
    pendingCastTarget = {
      card, cardName, targetKind: "artifact", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...fields,
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that untap/affect a target land (Ley Druid, Gaea's Liege, Cyclopean
  // Tomb's non-Swamp land): the backend already excludes illegal lands.
  if (activatedAbilityRequiresTargetLand(card)) {
    const fields = pendingTargetFields(card);
    if (fields.validKeys.size === 0) {
      const noun = activatedAbilityTargetLandExcludesSwamp(card) ? "non-Swamp land" : "land";
      updateActionHint(`No valid ${noun} targets in play for ${cardName}.`, true);
      return;
    }
    pendingCastTarget = {
      card, cardName, targetKind: "land", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...fields,
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that grant a keyword/pump to a target creature (Stone Giant,
  // Helm of Chatzuk): the player chooses which creature.
  if (activatedAbilityRequiresTargetCreatureGrant(card)) {
    const fields = pendingTargetFields(card);
    if (fields.validKeys.size === 0) {
      updateActionHint(`No valid creature targets in play for ${cardName}.`, true);
      return;
    }
    pendingCastTarget = {
      card, cardName, targetKind: "creature", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...fields,
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that counter a target spell on the stack (Deathgrip): the player
  // chooses which spell.
  if (activatedAbilityRequiresTargetStackSpell(card)) {
    pendingCastTarget = {
      card, cardName, targetKind: "stack", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...pendingTargetFields(card),
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that deal damage to "any target" (Orcish Artillery): the player must
  // choose a creature or a player's face before the ability is activated.
  if (activatedAbilityRequiresTargetAny(card)) {
    pendingCastTarget = {
      card, cardName, targetKind: "any", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...pendingTargetFields(card),
    };
    renderActivationPrompt();
    renderBoard(currentState);
    return;
  }

  // Abilities that look at a target player's hand (Glasses of Urza): choose whose
  // hand to look at.
  if (activatedAbilityRequiresTargetPlayer(card)) {
    pendingCastTarget = {
      card, cardName, targetKind: "player", castAction: "activate",
      sourcePermanentIndex: permanentIndex, abilityIndex, ...pendingTargetFields(card),
    };
    renderActivationPrompt();
    return;
  }

  // A loyalty cost is paid in counters, not mana (CR 606.4), so it skips both
  // the {X} mana prompt and the pay-the-cost prompt below — those read the text
  // left of the colon as mana symbols, and "+1" or "−X" is neither payable nor
  // refusable that way. The engine moves the counters itself as the ability is
  // activated, so all this has to send is which ability.
  const loyaltyCost = loyaltyCostOfChosenAbility(card);
  if (loyaltyCost) {
    // "−X" (Ugin): X is chosen on activation and CR 606.6 caps it at the
    // counters actually on the permanent, so the loyalty is the ceiling here —
    // not the mana available, which is what the {X} prompt below computes.
    if (loyaltyCost.xSign !== null) {
      // A "+X" cost has no such ceiling — 606.6 bounds only removal — and no
      // printed card carries one, so there is nothing to derive a range from.
      // Refuse by name rather than offer a range of X = 0 that looks like an
      // answer; a card that prints it can bring its own bound.
      if (loyaltyCost.xSign > 0) {
        SFX.onError();
        updateActionHint(`${cardName}: a "+X" loyalty cost has no supported range of X.`, true);
        return;
      }
      pendingCastX = {
        kind: "cast_x",
        card,
        cardName,
        targetSeat,
        targetPermanentIndex: null,
        targetStackIndex: null,
        castAction: "activate",
        activatePermanentIndex: permanentIndex,
        activateAbilityIndex: abilityIndex,
        manaRequirement: {},
        costString: "",
        costCard: null,
        loyalty: true,
        maxX: currentLoyaltyOf(card),
        awaitingCustomValue: false,
      };
      renderActivationPrompt();
      return;
    }
    const loyaltyBody = withPermanentId(
      {
        seat,
        action: "activate",
        permanent_name: cardName,
        permanent_index: permanentIndex,
        target_seat: targetSeat,
      },
      "permanent_id", seat, permanentIndex,
    );
    if (Number.isInteger(abilityIndex)) loyaltyBody.ability_index = abilityIndex;
    sendAction(loyaltyBody)
      .then(() => updateActionHint(`Activated ${cardName}'s ${loyaltySymbolText(loyaltyCost)} ability.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

  if (cardRequiresManaColorChoice(card)) {
    pendingManaColor = {
      cardName,
      permanentIndex,
      targetSeat,
      oracleText: card.oracle_text || "",
    };
    renderActivationPrompt();
    return;
  }

  const dualColors = getDualLandColors(card);
  if (dualColors) {
    const colorOptions = MANA_COLOR_OPTIONS.filter((o) => dualColors.includes(o.symbol));
    pendingManaColor = {
      cardName,
      permanentIndex,
      targetSeat,
      oracleText: card.oracle_text || "",
      colorOptions,
      // `fan` routes the choice to the on-board mana fan rather than the modal;
      // renderActivationPrompt keeps the prompt panel hidden while it's set.
      fan: true,
    };
    // Pop the mana symbols out of the land itself (the viewer controls it, so
    // its canvas key is `${seat}-${permanentIndex}`) and let the player click one.
    if (battlefieldCanvas && seat !== null) {
      battlefieldCanvas.showManaFan(`${seat}-${permanentIndex}`, colorOptions);
    }
    renderActivationPrompt();
    updateActionHint(`Choose a mana color for ${cardName}.`);
    return;
  }

  const activationCost = getActivatedAbilityCost(card);

  // "{X}" activation costs (Illusionary Mask, Clockwork Beast) need an X chosen
  // before the ability is sent — without it the engine receives X = 0 and e.g.
  // Illusionary Mask finds no castable creature regardless of the hand.
  if (/\{x\}/i.test(activationCost)) {
    pendingCastX = {
      kind: "cast_x",
      card,
      cardName,
      targetSeat,
      targetPermanentIndex: null,
      targetStackIndex: null,
      castAction: "activate",
      activatePermanentIndex: permanentIndex,
      activateAbilityIndex: abilityIndex,
      manaRequirement: parseManaCostSymbols(activationCost),
      costString: activationCost,
      costCard: null,
      maxX: getMaxAffordableX(getCurrentPlayerState()?.mana_pool, activationCost, null),
      awaitingCustomValue: false,
    };
    renderActivationPrompt();
    return;
  }

  if (!shouldPromptForActivationCost(activationCost)) {
    const directBody = withPermanentId(
      {
        seat,
        action: "activate",
        permanent_name: cardName,
        permanent_index: permanentIndex,
        target_seat: targetSeat,
      },
      "permanent_id", seat, permanentIndex,
    );
    if (Number.isInteger(abilityIndex)) directBody.ability_index = abilityIndex;
    sendAction(directBody)
      .then(() => updateActionHint(`Activated ${cardName}.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

  pendingActivation = {
    cardName,
    permanentIndex,
    targetSeat,
    activationCost,
    manaRequirement: parseManaCostSymbols(activationCost),
    awaitingApproval: true,
    abilityIndex,
  };
  renderActivationPrompt();
}

function resolvePendingManaColor(manaColor) {
  if (!pendingManaColor || seat === null) return;
  const validOptions = pendingManaColor.colorOptions || MANA_COLOR_OPTIONS;
  if (!validOptions.some((option) => option.symbol === manaColor)) {
    updateActionHint("Invalid mana color choice.", true);
    return;
  }

  const pending = pendingManaColor;
  pendingManaColor = null;
  renderActivationPrompt();

  if (pending.kind === "cast_fixed") {
    // One-shot color choice attached to an already-built cast body (Metamorphosis).
    const actionBody = { ...pending.castActionBody, mana_color: manaColor };
    updateActionHint(`Casting ${pending.cardName} (${manaColor})...`);
    sendAction(actionBody)
      .then(() => {
        updateActionHint(`Cast ${pending.cardName} for ${manaColor} mana.`);
        clearPendingHandCast();
      })
      .catch((e) => {
        clearPendingHandCast();
        updateActionHint(e.message, true);
      });
    return;
  }

  if (pending.kind === "cast") {
    // First pick is the "from" word; re-prompt for the "to" word before casting.
    // The "from" list may be limited to words present on the target; the "to"
    // replacement can be any land type/color again.
    if (pending.step === "from") {
      pendingManaColor = { ...pending, step: "to", fromColor: manaColor, colorOptions: undefined };
      renderActivationPrompt();
      return;
    }
    const actionBody = {
      ...pending.castActionBody,
      old_color: pending.fromColor,
      mana_color: manaColor,
    };
    updateActionHint(`Casting ${pending.cardName} (${pending.fromColor} → ${manaColor})...`);
    sendAction(actionBody)
      .then(() => {
        updateActionHint(`Cast ${pending.cardName}: replaced ${pending.fromColor} with ${manaColor}.`);
        clearPendingHandCast();
      })
      .catch((e) => {
        clearPendingHandCast();
        updateActionHint(e.message, true);
      });
    return;
  }

  updateActionHint(`Activating ${pending.cardName} for ${manaColor} mana...`);

  sendAction(withPermanentId(
    {
      seat,
      action: "activate",
      permanent_name: pending.cardName,
      permanent_index: pending.permanentIndex,
      target_seat: pending.targetSeat,
      mana_color: manaColor,
    },
    "permanent_id", seat, pending.permanentIndex,
  ))
    .then(() => updateActionHint(`Activated ${pending.cardName} and chose ${manaColor}.`))
    .catch((e) => updateActionHint(e.message, true));
}

// Selectable modes of a "Choose one —" modal spell, as serialized by the server
// on each hand card. A card is modal (worth prompting) only with 2+ modes.
function cardModeOptions(card) {
  if (!card || typeof card === "string") return [];
  return Array.isArray(card.modes) ? card.modes : [];
}

function cardIsModal(card) {
  return cardModeOptions(card).length >= 2;
}

// A printed "discard a card" additional cost, and the cards that may pay it.
// The engine enumerates them (it withholds the copy about to be cast, which
// CR 601.2a has already put on the stack) and re-checks the answer, so this is
// a hint rather than the authority.
function cardRequiresDiscardCost(card) {
  return !!targetSpecOf(card)?.discard_cost;
}

function discardCostOptions(card) {
  const spec = targetSpecOf(card);
  return (spec?.valid_targets || []).filter((option) => Number.isInteger(option?.hand_index));
}

// Open the discard-cost prompt. With nothing legal to discard the cast is left
// to the engine, which refuses it under CR 601.2h and says why — a client-side
// refusal here would be a second opinion about payability.
function startCastDiscardCostPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return false;
  const options = discardCostOptions(card);
  if (!options.length) return false;
  pendingDiscardCost = { card, cardName, castAction, options };
  renderActivationPrompt();
  return true;
}

// Send the cast with the chosen payment on the cost field. `cost_hand_index`
// indexes the hand as it stands now — the one that still holds the spell —
// which is the hand the engine resolves it against before the card leaves it.
function payDiscardCost(handIndex) {
  if (!pendingDiscardCost) return;
  const choice = pendingDiscardCost;
  pendingDiscardCost = null;
  renderActivationPrompt();
  const activation = choice.activation;
  if (activation) {
    const body = withPermanentId(
      {
        seat,
        action: "activate",
        permanent_name: choice.cardName,
        permanent_index: activation.permanentIndex,
        cost_hand_index: handIndex,
      },
      "permanent_id", seat, activation.permanentIndex,
    );
    if (Number.isInteger(activation.abilityIndex)) body.ability_index = activation.abilityIndex;
    updateActionHint(`Activating ${choice.cardName}...`);
    sendAction(body)
      .then(() => updateActionHint(`Activated ${choice.cardName}.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

  updateActionHint(`Casting ${choice.cardName}...`);
  sendAction({
    seat,
    action: choice.castAction || "cast",
    card_name: choice.cardName,
    cost_hand_index: handIndex,
  })
    .then(() => {
      updateActionHint(`Cast ${choice.cardName}.`);
      clearPendingHandCast();
    })
    .catch((e) => {
      clearPendingHandCast();
      updateActionHint(e.message, true);
    });
}

// The activation twin of startCastDiscardCostPrompt. Nothing is withheld from
// the hand here — the source is a permanent, so a copy of it in hand is an
// ordinary card — and the answer rides the same `cost_hand_index` field.
function startActivationDiscardCostPrompt(card, cardName, permanentIndex, abilityIndex) {
  const options = discardCostOptions(card);
  if (!options.length) return false;
  pendingDiscardCost = {
    card,
    cardName,
    castAction: "activate",
    options,
    activation: { permanentIndex, abilityIndex },
  };
  renderActivationPrompt();
  return true;
}

// Show the generic mode-choice prompt for a modal spell. Returns true when the
// prompt was opened, false when the card isn't actually modal.
function startModalChoicePrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return false;
  const modes = cardModeOptions(card);
  if (modes.length < 2) return false;

  // "Choose one **or more** —" (CR 700.2d). The bound comes from the server
  // beside the mode list, because a client reading five modes has no way to
  // know whether it may offer two of them — and reading it off the label text
  // would be the substring match the compiler stopped making.
  const atLeast = card && card.modes_at_least === true;
  pendingModalChoice = { card, cardName, castAction, modes, atLeast, picked: [] };
  renderActivationPrompt();
  return true;
}

// Confirm a multi-select mode prompt: begin walking the chosen modes through
// their own targeting prompts, in the order the caster clicked them. The engine
// sorts them into printed order (CR 608.2c), so this order only decides which
// target is asked for first.
function confirmModalModes() {
  const choice = pendingModalChoice;
  if (!choice || !choice.atLeast || !choice.picked.length) return;
  pendingModalChoice = null;
  pendingCastModeIndex = null;
  pendingModeCollection = {
    card: choice.card,
    cardName: choice.cardName,
    castAction: choice.castAction,
    modes: choice.modes,
    order: choice.picked.slice(),
    collected: [],
    cursor: 0,
  };
  promptNextModeTarget();
}

// Open the targeting prompt for the mode the collection is currently on. A mode
// that targets nothing records an entry with no target and moves straight on,
// which is what makes "Target player draws a card" and "Counter target spell"
// compose in one cast.
function promptNextModeTarget() {
  const run = pendingModeCollection;
  if (!run) return;
  if (run.cursor >= run.order.length) {
    finishModeCollection();
    return;
  }
  const index = run.order[run.cursor];
  const mode = run.modes[index];
  updateActionHint(`${run.cardName} — ${mode.label}.`);
  dispatchModalCast(run.card, run.castAction, mode.target_kind, mode.valid_targets);
}

// Send the accumulated modes as one cast. Cleared first, so the sendAction below
// is an ordinary cast rather than the last mode's capture.
function finishModeCollection() {
  const run = pendingModeCollection;
  if (!run) return;
  pendingModeCollection = null;
  updateActionHint(`Casting ${run.cardName}...`);
  sendAction({
    seat,
    action: run.castAction || "cast",
    card_name: run.cardName,
    mode_choices: run.collected,
  })
    .then(() => updateActionHint(`Cast ${run.cardName}.`))
    .catch((e) => updateActionHint(e.message, true))
    .finally(() => clearPendingHandCast());
}

// Apply the caster's mode pick: record the index, then continue into the normal
// targeting flow using that mode's target kind.
function chooseModalMode(index) {
  if (!pendingModalChoice) return;
  const choice = pendingModalChoice;
  const mode = choice.modes[index];
  if (!mode) return;
  if (mode.supported === false) {
    updateActionHint("That mode isn't supported yet — pick another.", true);
    return;
  }

  // A multi-select prompt toggles and waits for the confirm; a single-mode one
  // is finished by this click, which is the difference between "which mode" and
  // "which modes".
  if (choice.atLeast) {
    const at = choice.picked.indexOf(index);
    if (at >= 0) choice.picked.splice(at, 1);
    else choice.picked.push(index);
    renderActivationPrompt();
    return;
  }

  pendingModalChoice = null;
  pendingCastModeIndex = index;
  renderActivationPrompt();
  updateActionHint(`${choice.cardName} — ${mode.label}.`);
  dispatchModalCast(choice.card, choice.castAction, mode.target_kind, mode.valid_targets);
}

// Route a chosen mode to the targeting prompt its effect needs, or cast directly
// when the mode targets nothing.
function dispatchModalCast(card, castAction, targetKind, validTargets = null) {
  // A mode naming several targets takes the several-target prompt whatever its
  // kind says, for the same reason the cast cascades check it first.
  if (cardRequiresSeveralTargets(card)) {
    startCastSeveralTargetsPrompt(card, castAction, validTargets);
    return;
  }
  switch (targetKind) {
    case "creature":
      startCastCreatureTargetPrompt(card, castAction, validTargets);
      return;
    case "artifact":
      startCastArtifactTargetPrompt(card, castAction, validTargets);
      return;
    case "permanent":
      startCastPermanentTargetPrompt(card, castAction, validTargets);
      return;
    case "stack":
      startCastStackSpellPrompt(card, castAction, validTargets);
      return;
    case "any":
      startCastAnyTargetPrompt(card, castAction, validTargets);
      return;
    case "player":
      startCastTargetPrompt(card, castAction, validTargets);
      return;
    default:
      break; // "none" — no target to choose.
  }

  const cardName = normalizeCardName(card);
  const targetSeat = getDefaultTargetSeat(cardName);
  const actionBody = { seat, action: castAction, card_name: cardName, target_seat: targetSeat };
  sendAction(actionBody)
    .then(() => {
      updateActionHint(`Cast ${cardName}.`);
      clearPendingHandCast();
    })
    .catch((e) => {
      clearPendingHandCast();
      updateActionHint(e.message, true);
    });
}

// Each start function takes the card and (for a chosen modal mode) the mode's
// own legal-target list; otherwise it reads the card's cast target_spec. The
// backend-supplied valid targets are indexed onto pendingCastTarget so clicks and
// highlights validate against them — no client-side legality remains here.
function startCastTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "player",
    castAction,
    ...pendingTargetFields(card, validTargets),
  };
  renderActivationPrompt();
}

function startCastLandTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const fields = pendingTargetFields(card, validTargets);
  if (fields.validKeys.size === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid land targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = { card, cardName, targetKind: "land", castAction, ...fields };
  renderActivationPrompt();
  renderBoard(currentState);
}

function startCastCreatureTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const fields = pendingTargetFields(card, validTargets);
  if (fields.validKeys.size === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid creature targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = { card, cardName, targetKind: "creature", castAction, ...fields };
  renderActivationPrompt();
  renderBoard(currentState);
}

function startCastPermanentTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const fields = pendingTargetFields(card, validTargets);
  // Lace recolor ("target spell or permanent") and "source of your choice" prevention
  // (Reverse Damage, marked with also_stack) may pick a permanent OR a spell on the
  // stack, so they stay castable when there are no permanents but there is a stack target.
  const alsoStack = cardRequiresTargetSpellOrPermanent(card) || !!targetSpecOf(card).also_stack;
  if (fields.validKeys.size === 0 && !(alsoStack && fields.validStackIndices.size > 0)) {
    clearPendingHandCast();
    updateActionHint(`No valid permanent targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = { card, cardName, targetKind: "permanent", alsoStack, castAction, ...fields };
  renderActivationPrompt();
  renderBoard(currentState);
}

function startCastArtifactTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const fields = pendingTargetFields(card, validTargets);
  if (fields.validKeys.size === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid artifact targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = { card, cardName, targetKind: "artifact", castAction, ...fields };
  renderActivationPrompt();
  renderBoard(currentState);
}

function startCastAnyTargetPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "any",
    castAction,
    ...pendingTargetFields(card, validTargets),
  };
  renderActivationPrompt();
  renderBoard(currentState);
}

// Fireball-style "divided among any number of targets" cast flow. The player
// accumulates targets (creatures on one side, or a single player's face),
// confirms, then chooses X — the extra targets are taxed {1} each.
function startCastDividedPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  pendingCastTarget = {
    card,
    cardName,
    castAction,
    targetKind: "divided",
    dividedTargets: [], // [{ seat, idx }] creatures — any mix across both seats
    dividedFaces: [], // [seat, ...] player faces — combinable with creatures
    ...pendingTargetFields(card, validTargets),
  };
  renderActivationPrompt();
  renderBoard(currentState);
  const landFilter = targetSpecOf(card)?.land_filter;
  updateActionHint(
    landFilter
      ? `Choose the ${landFilter}s for ${cardName} to destroy (click each), then confirm.`
      : `Choose targets for ${cardName}: click any mix of creatures (either side) and/or player life pills to split the damage among them. Then confirm.`,
  );
}

function dividedTargetCount() {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "divided") return 0;
  return p.dividedTargets.length + (p.dividedFaces?.length || 0);
}

// --- "Up to N target ..." ----------------------------------------------------
//
// Its own prompt rather than a flag on the single-target one: the player picks
// several, may legally stop short of the maximum (CR 601.2c), and so needs a
// confirm step that a one-click picker has nowhere to put. The accumulate-and-
// confirm shape is the divided prompt's, but the two must not be merged — a
// divided spell splits *one* quantity across its targets and follows up with an
// X prompt, while these are N independent targets of one effect.

function startCastSeveralTargetsPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  const max = severalTargetMaximum(card);
  pendingCastTarget = {
    card,
    cardName,
    castAction,
    targetKind: "several",
    maxTargets: max,
    severalTargets: [], // [{ seat, idx }] — all on one seat; see confirm below
    ...pendingTargetFields(card, validTargets),
  };
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(severalTargetsHint());
}

function severalTargetsHint() {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "several") return "";
  const n = p.severalTargets.length;
  return n === 0
    ? `Choose up to ${p.maxTargets} targets for ${p.cardName} (click each), then confirm. Choosing none is legal.`
    : `${n} of up to ${p.maxTargets} chosen.`;
}

function toggleSeveralTarget(targetSeat, permanentIndex) {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "several") return;
  if (p.validKeys && !p.validKeys.has(`${targetSeat}-${permanentIndex}`)) {
    updateActionHint("That permanent isn't a valid target for the pending spell.", true);
    return;
  }
  const at = p.severalTargets.findIndex((t) => t.seat === targetSeat && t.idx === permanentIndex);
  if (at >= 0) {
    p.severalTargets.splice(at, 1);
  } else {
    if (p.severalTargets.length >= p.maxTargets) {
      updateActionHint(`${p.cardName} names at most ${p.maxTargets} targets — click one to deselect it.`, true);
      return;
    }
    // A cross-seat selection is legal and the wire carries it: `confirm` sends
    // `target_permanent_ids`, and web/actions.py keeps those ids rather than
    // collapsing them onto one `target_seat`. Rookie Mistake's two slots are
    // both a bare "target creature", so pumping one of yours and shrinking one
    // of theirs is the ordinary play — the old reset-on-other-seat made it
    // unreachable. A pick with no resolvable id is refused at confirm rather
    // than silently sent as an index on the wrong board.
    p.severalTargets.push({ seat: targetSeat, idx: permanentIndex });
  }
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(severalTargetsHint());
}

function confirmSeveralTargets() {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "several") return;
  const { card, cardName, castAction, severalTargets } = p;
  const targetSeat = severalTargets.length ? severalTargets[0].seat : seat;
  // Ids, not indices: a permanent that left the battlefield between the click
  // and the send must be a refusal rather than whichever permanent slid into
  // its slot. A pick with no id falls back to its index, which is what the
  // server does with the pair anyway.
  const ids = severalTargets
    .map((t) => permanentIdAt(t.seat, t.idx))
    .filter((pid) => Number.isInteger(pid));
  const oneSeat = severalTargets.every((t) => t.seat === targetSeat);
  const body = { seat, action: castAction || "cast", card_name: cardName, target_seat: targetSeat };
  if (ids.length === severalTargets.length && ids.length > 0) {
    body.target_permanent_ids = ids;
  } else if (severalTargets.length && oneSeat) {
    body.target_permanent_indices = severalTargets.map((t) => t.idx);
  } else if (severalTargets.length) {
    // Indices are positional on one `target_seat`, so a cross-seat selection
    // whose ids did not resolve cannot be sent at all. Refusing beats sending
    // the second pick as a slot on the first pick's board.
    updateActionHint("One of the chosen permanents has left the battlefield — pick again.", true);
    return;
  }
  clearPendingCastTargeting();
  updateActionHint(`Casting ${cardName}...`);
  sendAction(body)
    .then(() => updateActionHint(`Cast ${cardName}.`))
    .catch((e) => updateActionHint(e.message, true))
    .finally(() => clearPendingHandCast());
}

/** Drop the in-progress target prompt and every highlight it painted. */
function clearPendingCastTargeting() {
  pendingCastTarget = null;
  battlefieldCanvas?.setTargetingKeys([]);
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
  clearFfaTargetingHighlights();
}

function dividedTargetsHint() {
  const n = dividedTargetCount();
  if (n === 0) return "No targets chosen yet.";
  // The per-target mana tax only applies to Fireball-style splits, not to a
  // count-based selection (Volcanic Eruption, where X = the number chosen).
  const xEqualsTargets = !!targetSpecOf(pendingCastTarget?.card)?.x_equals_targets;
  const extra = !xEqualsTargets && n > 1 ? ` (+${n - 1} mana for the extra target${n - 1 === 1 ? "" : "s"})` : "";
  return `${n} target${n === 1 ? "" : "s"} chosen${extra}.`;
}

function toggleDividedCreatureTarget(targetSeat, permanentIndex) {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "divided") return;
  // Only server-enumerated targets are selectable: Fireball offers creatures on
  // both sides, Volcanic Eruption offers Mountains only — clicking anything
  // else is rejected instead of silently added.
  if (p.validKeys && !p.validKeys.has(`${targetSeat}-${permanentIndex}`)) {
    const landFilter = targetSpecOf(p.card)?.land_filter;
    updateActionHint(
      landFilter
        ? `${p.cardName} targets ${landFilter}s — click a ${landFilter}.`
        : "That permanent isn't a valid target for the pending spell.",
      true,
    );
    return;
  }
  // Any mix of valid targets on both sides (and player faces) is legal — the
  // damage is divided evenly among everything chosen.
  const existing = p.dividedTargets.findIndex((t) => t.seat === targetSeat && t.idx === permanentIndex);
  if (existing >= 0) p.dividedTargets.splice(existing, 1);
  else p.dividedTargets.push({ seat: targetSeat, idx: permanentIndex });
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(dividedTargetsHint());
}

function setDividedFaceTarget(targetSeat) {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "divided") return;
  if (!Array.isArray(p.dividedFaces)) p.dividedFaces = [];
  // Clicking a face toggles it; faces combine freely with creature targets.
  const existing = p.dividedFaces.indexOf(targetSeat);
  if (existing >= 0) p.dividedFaces.splice(existing, 1);
  else p.dividedFaces.push(targetSeat);
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(dividedTargetsHint());
}

function confirmDividedTargets() {
  const p = pendingCastTarget;
  if (!p || p.targetKind !== "divided") return;
  const n = dividedTargetCount();
  if (n === 0) {
    updateActionHint("Choose at least one target first.", true);
    return;
  }
  // The full cross-seat target list: creatures as {seat, index}, faces as {seat}.
  const dividedPayload = [
    ...p.dividedTargets.map((t) => ({ seat: t.seat, index: t.idx })),
    ...(p.dividedFaces || []).map((faceSeat) => ({ seat: faceSeat })),
  ];
  const { card, cardName, castAction } = p;
  // Volcanic Eruption: X equals the number of chosen targets (Mountains), so there
  // is no separate X prompt — cast straight away with x_value = the count.
  const xEqualsTargets = !!targetSpecOf(card)?.x_equals_targets;
  pendingCastTarget = null;
  battlefieldCanvas?.setTargetingKeys([]);
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
  clearFfaTargetingHighlights();
  if (xEqualsTargets) {
    const body = {
      seat,
      action: castAction || "cast",
      card_name: cardName,
      divided_targets: dividedPayload,
      x_value: dividedPayload.length,
    };
    updateActionHint(`Casting ${cardName} (X = ${dividedPayload.length})...`);
    sendAction(body)
      .then(() => updateActionHint(`Cast ${cardName}.`))
      .catch((e) => updateActionHint(e.message, true))
      .finally(() => clearPendingHandCast());
    return;
  }
  startCastDividedXPrompt(card, cardName, dividedPayload, n - 1, castAction || "cast");
}

function startCastDividedXPrompt(card, cardName, dividedPayload, extraTargetTax, castAction = "cast") {
  const baseMax = getMaxAffordableX(getCurrentPlayerState()?.mana_pool, card.mana_cost || "", card);
  pendingCastX = {
    kind: "cast_x",
    card,
    cardName,
    targetSeat: null,
    targetPermanentIndex: null,
    dividedPayload, // [{seat, index}] creatures + [{seat}] faces, both sides
    extraTargetTax,
    castAction,
    manaRequirement: parseManaCostSymbols(card.mana_cost || ""),
    // renderActivationPrompt recomputes maxX from these each render, so the
    // prompt tracks mana added while it is open.
    costString: card.mana_cost || "",
    costCard: card,
    // Each target beyond the first eats {1} of generic mana that could go to X.
    maxX: Math.max(0, baseMax - Math.max(0, extraTargetTax)),
    awaitingCustomValue: false,
  };
  renderActivationPrompt();
  const count = dividedPayload.length;
  updateActionHint(`Choose X for ${cardName} — damage split among ${count} target${count === 1 ? "" : "s"}.`);
}

function startCastStackSpellPrompt(card, castAction = "cast", validTargets = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const fields = pendingTargetFields(card, validTargets);
  if (fields.validStackIndices.size === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid spell on the stack for ${cardName} to target.`, true);
    return;
  }
  pendingCastTarget = {
    card, cardName, targetKind: "stack", castAction,
    // Fork copies the chosen spell and lets the caster pick new targets for the
    // copy, so selecting the spell starts a second target prompt rather than
    // casting immediately.
    copiesSpell: !!targetSpecOf(card).copies_spell,
    ...fields,
  };
  renderActivationPrompt();
  renderStack(currentState ? currentState.stack : _currentStack);
}

// Fork second step: after the spell to copy is chosen, offer the caster a new
// target for the copy (when the copied spell targets a permanent), then send the
// cast carrying both the copied-spell index and the chosen target. A copied spell
// that targets a player or nothing simply keeps its original targets.
const _FORK_RETARGET_KINDS = new Set(["creature", "permanent", "artifact", "land"]);

async function startForkCopyRetarget(forkPending, stackArrayIndex, copiedItem) {
  const copiedName = copiedItem?.card?.name || "the spell";
  const copiedCard = await attachCardTargetSpec(await fetchCardByName(copiedName), seat);
  const spec = copiedCard ? targetSpecOf(copiedCard) : EMPTY_TARGET_SPEC;
  const fields = indexValidTargets(spec.valid_targets || []);
  if (!_FORK_RETARGET_KINDS.has(spec.kind) || fields.validKeys.size === 0) {
    // Nothing to retarget — copy keeps the original spell's targets.
    sendForkCopyCast(forkPending, stackArrayIndex, null, null, copiedName);
    return;
  }
  pendingCastTarget = {
    card: forkPending.card,
    cardName: forkPending.cardName,
    targetKind: spec.kind === "creature" ? "creature" : "permanent",
    castAction: forkPending.castAction,
    forkStackIndex: stackArrayIndex,
    copyTargetName: copiedName,
    ...fields,
  };
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(`Choose a new target for the copy of ${copiedName} (click the original to keep it).`);
}

function sendForkCopyCast(forkPending, stackArrayIndex, targetSeat, permanentIndex, copiedName) {
  const body = {
    seat,
    action: forkPending.castAction || "cast",
    card_name: forkPending.cardName,
    target_stack_index: stackArrayIndex,
  };
  if (Number.isInteger(targetSeat)) body.target_seat = targetSeat;
  if (Number.isInteger(permanentIndex)) {
    body.permanent_index = permanentIndex;
    withPermanentId(body, "target_permanent_id", targetSeat, permanentIndex);
  }
  updateActionHint(`Casting ${forkPending.cardName} (copying ${copiedName})...`);
  sendAction(body)
    .then(() => {
      updateActionHint(`Cast ${forkPending.cardName}.`);
      clearPendingHandCast();
    })
    .catch((e) => {
      if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
        pendingAutoTap = { card: forkPending.card, cardName: forkPending.cardName, actionBody: body };
        renderActivationPrompt();
        return;
      }
      clearPendingHandCast();
      updateActionHint(e.message, true);
    });
}

function startCastXPrompt(card, targetSeat, targetPermanentIndex = null, castAction = "cast", targetStackIndex = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastX = {
    kind: "cast_x",
    card,
    cardName,
    targetSeat,
    targetPermanentIndex,
    targetStackIndex,
    castAction,
    manaRequirement: parseManaCostSymbols(card.mana_cost || ""),
    costString: card.mana_cost || "",
    costCard: card,
    maxX: getMaxAffordableX(getCurrentPlayerState()?.mana_pool, card.mana_cost || "", card),
    awaitingCustomValue: false,
  };
  renderActivationPrompt();
}

function resolvePendingCastTarget(targetSeat, targetPermanentIndex = null) {
  if (!pendingCastTarget) return;
  const pending = pendingCastTarget;
  const selectedTarget = Number.isInteger(targetSeat) ? targetSeat : seat;
  const selectedPermanentIndex = Number.isInteger(targetPermanentIndex) ? targetPermanentIndex : null;

  if (pending.targetKind === "land" && selectedPermanentIndex === null) {
    updateActionHint("Choose a land in play to target.", true);
    return;
  }
  if (pending.targetKind === "artifact" && selectedPermanentIndex === null) {
    updateActionHint("Choose an artifact in play to target.", true);
    return;
  }
  if (pending.targetKind === "creature" && selectedPermanentIndex === null) {
    updateActionHint("Choose a creature in play to target.", true);
    return;
  }
  if (pending.targetKind === "permanent" && selectedPermanentIndex === null) {
    updateActionHint("Choose a permanent in play to target.", true);
    return;
  }
  if (pending.targetKind === "graveyard_creature" && selectedPermanentIndex === null) {
    updateActionHint("Choose a creature card in a graveyard to target.", true);
    return;
  }

  pendingCastTarget = null;
  battlefieldCanvas?.setTargetingKeys([]);
  if (battlefieldCanvas) battlefieldCanvas.zonePileTargeting = null;
  closeZoneRevealIfAutoOpened();
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
  clearFfaTargetingHighlights();
  renderActivationPrompt();

  // Fork copy retarget: the chosen permanent becomes the copy's new target. Send
  // the Fork cast carrying both the copied-spell index and the new target.
  if (Number.isInteger(pending.forkStackIndex)) {
    sendForkCopyCast(pending, pending.forkStackIndex, selectedTarget, selectedPermanentIndex, pending.copyTargetName);
    return;
  }

  // Activated ability targeting a permanent (e.g. Gaea's Liege targeting a land):
  // send an "activate" action with the chosen target permanent rather than a cast.
  if (pending.castAction === "activate") {
    // Jade Monolith: after the creature is chosen, a second prompt picks the
    // damage source ("a source of your choice") before the ability is sent.
    const spec = targetSpecOf(pending.card);
    if (spec?.requires_source && !pending.__sourceStage) {
      // The source may be any permanent on either battlefield OR a spell on
      // the stack — both come enumerated in source_targets.
      const sourceTargets = spec.source_targets || [];
      if (!sourceTargets.length) {
        updateActionHint(`No damage source available for ${pending.cardName}.`, true);
        return;
      }
      pendingCastTarget = {
        card: pending.card,
        cardName: pending.cardName,
        targetKind: "permanent",
        castAction: "activate",
        alsoStack: true,
        sourcePermanentIndex: pending.sourcePermanentIndex,
        __sourceStage: true,
        chosenTargetSeat: selectedTarget,
        chosenTargetIndex: selectedPermanentIndex,
        ...pendingTargetFields(pending.card, sourceTargets),
      };
      renderActivationPrompt();
      renderBoard(currentState);
      renderStack(_currentStack);
      updateActionHint(
        `Now choose the damage source for ${pending.cardName}: click a permanent or a spell on the stack.`,
      );
      return;
    }
    // Dwarven Weaponsmith: the target is chosen, now the cost. Two prompts
    // because CR 601.2c and CR 601.2b are two announcements on two fields —
    // one picker collecting both would have to send one of them as the other.
    const costSpec = spec?.cost_spec;
    if (costSpec && !pending.__costStage && !pending.__costOnly) {
      const costTargets = costSpec.valid_targets || [];
      if (!costTargets.length) {
        updateActionHint(
          `${pending.cardName} has nothing it can sacrifice for its cost.`, true,
        );
        return;
      }
      pendingCastTarget = {
        card: pending.card,
        cardName: pending.cardName,
        targetKind: "permanent",
        castAction: "activate",
        sourcePermanentIndex: pending.sourcePermanentIndex,
        abilityIndex: pending.abilityIndex,
        __costStage: true,
        chosenTargetSeat: selectedTarget,
        chosenTargetIndex: selectedPermanentIndex,
        ...pendingTargetFields(pending.card, costTargets),
      };
      renderActivationPrompt();
      renderBoard(currentState);
      updateActionHint(
        `Now choose what ${pending.cardName} sacrifices to pay for it.`,
      );
      return;
    }

    // The cost pick — either the whole choice (__costOnly) or the second half
    // of it (__costStage) — rides the cost field, never the target one.
    if (pending.__costOnly || pending.__costStage) {
      const costBody = withPermanentId(
        {
          seat,
          action: "activate",
          permanent_name: pending.cardName,
          permanent_index: pending.sourcePermanentIndex,
          cost_permanent_index: selectedPermanentIndex,
          ...(pending.__costStage
            ? {
                target_seat: pending.chosenTargetSeat,
                target_permanent_index: pending.chosenTargetIndex,
              }
            : {}),
        },
        "cost_permanent_id", selectedTarget, selectedPermanentIndex,
      );
      if (Number.isInteger(pending.abilityIndex)) costBody.ability_index = pending.abilityIndex;
      updateActionHint(`Activating ${pending.cardName}...`);
      sendAction(costBody)
        .then(() => updateActionHint(`Activated ${pending.cardName}.`))
        .catch((e) => {
          if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
            pendingAutoTap = {
              card: pending.card,
              cardName: pending.cardName,
              cost: getActivatedAbilityCost(pending.card),
              actionBody: costBody,
            };
            renderActivationPrompt();
            return;
          }
          updateActionHint(e.message, true);
        });
      return;
    }

    const activateBody = pending.__sourceStage
      ? {
          seat,
          action: "activate",
          permanent_name: pending.cardName,
          permanent_index: pending.sourcePermanentIndex,
          target_seat: pending.chosenTargetSeat,
          target_permanent_index: pending.chosenTargetIndex,
          source_seat: selectedTarget,
          source_permanent_index: selectedPermanentIndex,
        }
      : {
          seat,
          action: "activate",
          permanent_name: pending.cardName,
          permanent_index: pending.sourcePermanentIndex,
          target_seat: selectedTarget,
          target_permanent_index: selectedPermanentIndex,
        };
    if (Number.isInteger(pending.abilityIndex)) activateBody.ability_index = pending.abilityIndex;
    updateActionHint(`Activating ${pending.cardName}...`);
    sendAction(activateBody)
      .then(() => updateActionHint(`Activated ${pending.cardName}.`))
      .catch((e) => {
        // Abilities with a mana cost (e.g. Rod of Ruin's "{3}, {T}") prompt the
        // auto-tap/auto-pay flow when the pool can't cover the cost, just like
        // casting a spell.
        if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
          // Ability activation: pay the ability's activation cost (e.g. Circle
          // of Protection's {1}), not the card's casting cost ({1}{W}).
          pendingAutoTap = {
            card: pending.card,
            cardName: pending.cardName,
            cost: getActivatedAbilityCost(pending.card),
            actionBody: activateBody,
          };
          renderActivationPrompt();
          return;
        }
        updateActionHint(e.message, true);
      });
    return;
  }

  if (hasXCost(pending.card)) {
    startCastXPrompt(pending.card, selectedTarget, selectedPermanentIndex, pending.castAction || "cast");
    return;
  }

  // A "sacrifice a creature" additional cost (Sacrifice, Village Rites) picks a
  // creature through this same prompt, but what was picked is a *cost payment*,
  // not a target — so it rides the cost field. Sending it as the target made
  // the engine treat it as one, which is how the cost came to be paid twice
  // once the cost itself became general.
  const paysCostWithPermanent = !!targetSpecOf(pending.card)?.sacrifice_cost;
  const actionBody = withPermanentId(
    {
      seat,
      action: pending.castAction || "cast",
      card_name: pending.cardName,
      ...(paysCostWithPermanent
        ? { cost_permanent_index: selectedPermanentIndex }
        : { target_seat: selectedTarget, permanent_index: selectedPermanentIndex }),
    },
    // The chosen target, captured now: this body can sit in `pendingManaColor`
    // through several polls before it is sent.
    paysCostWithPermanent ? "cost_permanent_id" : "target_permanent_id",
    selectedTarget, selectedPermanentIndex,
  );

  // Metamorphosis: "Add X mana of any one color..." — the caster picks the
  // color after choosing the sacrificed creature; it rides mana_color.
  if (cardRequiresManaColorChoice(pending.card) && (pending.castAction || "cast") === "cast") {
    pendingManaColor = {
      kind: "cast_fixed",
      cardName: pending.cardName,
      oracleText: pending.card.oracle_text || "",
      castActionBody: actionBody,
    };
    renderActivationPrompt();
    return;
  }

  if (cardRequiresCastColorChoice(pending.card)) {
    // Text-change spells (Sleight of Mind / Magical Hack) replace one word with
    // another, so two colors are chosen: the "from" word to replace, then the
    // "to" word. Both are sent (old_color + mana_color); collecting only one
    // leaves old_color unset and the engine stores no remap.
    const isLandType = /basic land type/.test((pending.card.oracle_text || "").toLowerCase());
    let fromOptions = null;
    if (isLandType && Number.isInteger(selectedTarget) && Number.isInteger(selectedPermanentIndex)) {
      const targetPerm = currentState?.players?.[selectedTarget]?.battlefield?.[selectedPermanentIndex];
      if (targetPerm && typeof targetPerm !== "string") {
        fromOptions = landWordOptionsForTarget(targetPerm);
        if (!fromOptions.length) {
          clearPendingHandCast();
          updateActionHint(
            `${targetPerm.name} has no basic land type in its text for ${pending.cardName} to replace.`,
            true,
          );
          return;
        }
      }
    }
    pendingManaColor = {
      kind: "cast",
      step: "from",
      fromColor: null,
      isLandType,
      cardName: pending.cardName,
      castActionBody: actionBody,
      oracleText: pending.card.oracle_text || "",
      colorOptions: fromOptions || undefined,
    };
    renderActivationPrompt();
    updateActionHint(
      `Choose the ${isLandType ? "land type" : "color word"} to replace in ${pending.cardName}'s target.`,
    );
    return;
  }

  updateActionHint(`Casting ${pending.cardName}...`);
  sendAction(actionBody)
    .then(() => {
      updateActionHint(`Cast ${pending.cardName}.`);
      clearPendingHandCast();
    })
    .catch((e) => {
      if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
        pendingAutoTap = { card: pending.card, cardName: pending.cardName, actionBody };
        renderActivationPrompt();
        return;
      }
      clearPendingHandCast();
      updateActionHint(e.message, true);
    });
}

function handlePlayerTargetClick(targetSeat) {
  if (!pendingCastTarget) return;
  if (!Number.isInteger(targetSeat)) return;
  // The backend enumerates which players are legal targets; reject a face the
  // server didn't mark targetable.
  if (pendingCastTarget.validPlayerSeats && !pendingCastTarget.validPlayerSeats.has(targetSeat)) {
    updateActionHint("That player isn't a valid target for the pending spell.", true);
    return;
  }
  if (pendingCastTarget.targetKind === "divided") {
    setDividedFaceTarget(targetSeat);
    return;
  }
  if (pendingCastTarget.targetKind !== "player" && pendingCastTarget.targetKind !== "any") return;
  resolvePendingCastTarget(targetSeat);
}

function confirmPendingActivation() {
  if (!pendingActivation || !pendingActivation.awaitingApproval) return;
  pendingActivation.awaitingApproval = false;
  renderActivationPrompt();
  updateActionHint(`Paying activation cost for ${pendingActivation.cardName}.`);
  attemptPendingActivation();
}

function resolvePendingCastX(xValue) {
  if (!pendingCastX) return;
  const maxX = Number(pendingCastX.maxX || 0);
  const selectedX = Number.isInteger(xValue) ? xValue : Number(q("promptCustomValue").value);
  if (!Number.isInteger(selectedX) || selectedX < 0 || selectedX > maxX) {
    updateActionHint(`Choose an X value between 0 and ${maxX}.`, true);
    return;
  }

  const pending = pendingCastX;
  pendingCastX = null;
  renderActivationPrompt();
  const verb = pending.castAction === "activate" ? "Activating" : "Casting";
  updateActionHint(`${verb} ${pending.cardName} with X = ${selectedX}...`);

  const body = {
    seat,
    action: pending.castAction || "cast",
    card_name: pending.cardName,
    x_value: selectedX,
  };
  // Fireball-style casts carry the cross-seat divided target list; Power Sink
  // carries the index of the spell on the stack it counters; everything else
  // carries a single permanent index (or none, for a face/player target). An
  // "{X}" activated ability (Illusionary Mask) routes to the activate action
  // with the source permanent instead of a hand card.
  if (pending.castAction === "activate") {
    delete body.card_name;
    body.permanent_name = pending.cardName;
    body.permanent_index = pending.activatePermanentIndex;
    if (Number.isInteger(pending.activateAbilityIndex)) body.ability_index = pending.activateAbilityIndex;
    body.target_seat = pending.targetSeat;
  } else if (Number.isInteger(pending.targetStackIndex)) {
    body.target_seat = pending.targetSeat;
    body.target_stack_index = pending.targetStackIndex;
  } else if (Array.isArray(pending.dividedPayload)) {
    body.divided_targets = pending.dividedPayload;
  } else {
    body.target_seat = pending.targetSeat;
    body.permanent_index = pending.targetPermanentIndex;
  }

  sendAction(body)
    .then(() => updateActionHint(
      `${pending.castAction === "activate" ? "Activated" : "Cast"} ${pending.cardName} with X = ${selectedX}.`,
    ))
    .catch((e) => updateActionHint(e.message, true))
    .finally(() => clearPendingHandCast());
}

function normalizeCardName(card) {
  if (!card) return "";
  if (typeof card === "string") return card;
  return card.name || "";
}

function normalizeImageUri(card) {
  if (!card || typeof card === "string") return null;
  return card.image_uri || null;
}

function normalizeLargeImageUri(card) {
  if (!card || typeof card === "string") return null;
  return card.large_image_uri || card.image_uri || null;
}

function cardStatsLabel(card) {
  if (!card || typeof card === "string") return "";
  const typeLine = String(card.type || "").toLowerCase();
  if (!typeLine.includes("creature")) {
    return "";
  }
  if (typeof card.power !== "number" || typeof card.toughness !== "number") {
    return "";
  }
  return `${card.power}/${card.toughness}`;
}

function updateActionHint(message, isError = false) {
  const el = q("actionHint");
  el.textContent = message;
  el.style.color = isError ? "#e16d70" : "#cfd7e4";
  if (isError) {
    const middleLane = document.querySelector(".middle-lane");
    if (middleLane) {
      middleLane.classList.remove("error-flash");
      void middleLane.offsetWidth;
      middleLane.classList.add("error-flash");
    }
  }
}

function setJoinUrls(url = "", lanUrl = "", publicUrl = "") {
  currentJoinUrl = String(url || "").trim();
  currentLanJoinUrl = String(lanUrl || "").trim();
  currentPublicJoinUrl = String(publicUrl || "").trim();
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();

  const copied = document.execCommand("copy");
  document.body.removeChild(helper);
  if (!copied) {
    throw new Error("Clipboard copy failed");
  }
}

function updateDebugStatus(message, status = "") {
  const el = q("debugStatus");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("error", "success");
  if (status === "error") {
    el.classList.add("error");
  }
  if (status === "success") {
    el.classList.add("success");
  }
}

function renderDebugOptions(cards) {
  const list = q("debugCardOptions");
  if (!list) return;
  list.innerHTML = "";
  for (const card of cards || []) {
    const option = document.createElement("option");
    option.value = card.name;
    option.label = `${card.name} - ${card.type || "Unknown"}`;
    list.appendChild(option);
  }
}

function setDebugMenuEnabled(enabled, canCastFree = false) {
  q("debugCardSearch").disabled = !enabled;
  q("debugAddToHandBtn").disabled = !enabled;
  q("debugAddToSideboardBtn").disabled = !enabled;
  q("debugCastFreeBtn").disabled = !enabled || !canCastFree;
  q("debugCastFreeOpponentBtn").disabled = !enabled;
  q("debugForceAttackAllToggle").disabled = !enabled;
  if (!enabled) {
    renderDebugOptions([]);
  }
}

async function fetchDebugSuggestions(query = "") {
  const term = (query || "").trim();
  const url = `/api/cards/search?query=${encodeURIComponent(term)}&limit=20`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error("failed to fetch card suggestions");
  }
  const payload = await resp.json();
  renderDebugOptions(payload.cards || []);
}

function renderVerifyOptions(cards) {
  const list = q("verifyCardOptions");
  if (!list) return;
  list.innerHTML = "";
  for (const card of cards || []) {
    const option = document.createElement("option");
    option.value = card.name;
    option.label = `${card.name} - ${card.type || "Unknown"}`;
    list.appendChild(option);
  }
}

async function fetchVerifySuggestions(query = "") {
  const term = (query || "").trim();
  const url = `/api/cards/search?query=${encodeURIComponent(term)}&limit=20&untested_only=true`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error("failed to fetch untested card suggestions");
  }
  const payload = await resp.json();
  renderVerifyOptions(payload.cards || []);
}

async function fetchCardByName(cardName) {
  const term = (cardName || "").trim();
  if (!term) return null;
  const url = `/api/cards/search?query=${encodeURIComponent(term)}&limit=20`;
  const resp = await fetch(url);
  if (!resp.ok) return null;
  const payload = await resp.json();
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  const lowered = term.toLowerCase();
  return cards.find((card) => String(card.name || "").toLowerCase() === lowered) || null;
}

// Catalog-search cards (the debug "cast for free" flow) carry no target spec —
// it's session/caster-dependent. Fetch the backend-computed cast spec for the
// given caster so the same targeting cascade hand cards use applies here too.
async function attachCardTargetSpec(card, casterSeat) {
  if (!card || !sessionId || !Number.isInteger(casterSeat)) return card;
  try {
    const url = `/api/sessions/${sessionId}/card_target_spec?card_name=${encodeURIComponent(card.name)}&seat=${casterSeat}`;
    const resp = await fetch(url);
    if (!resp.ok) return card;
    const payload = await resp.json();
    card.target_spec = payload.target_spec;
    if (Array.isArray(payload.modes)) card.modes = payload.modes;
  } catch {
    /* leave the card without a spec — the cascade falls through to a no-target cast */
  }
  return card;
}

async function addDebugCardToHand() {
  if (!sessionId || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }

  const input = q("debugCardSearch");
  const cardName = input.value.trim();
  if (!cardName) {
    updateDebugStatus("Type a card name before adding.", "error");
    return;
  }

  await sendAction({ seat, action: "debug_add_to_hand", card_name: cardName });
  updateDebugStatus(`Added ${cardName} to your hand.`, "success");
  updateActionHint(`Debug: added ${cardName} to your hand.`);
}

// Cards you own from outside the game (CR 100.4) — a random deck starts with
// none, so this is how Ring of Ma'rûf's replaced draw gets something to offer.
async function addDebugCardToSideboard() {
  if (!sessionId || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }

  const cardName = q("debugCardSearch").value.trim();
  if (!cardName) {
    updateDebugStatus("Type a card name before adding.", "error");
    return;
  }

  await sendAction({ seat, action: "debug_add_to_sideboard", card_name: cardName });
  updateDebugStatus(`Added ${cardName} to your cards outside the game.`, "success");
  updateActionHint(`Debug: added ${cardName} outside the game.`);
}

async function castDebugCardForFree() {
  if (!sessionId || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }
  if (!currentState || currentState.priority_player !== seat) {
    updateDebugStatus("You can only cast for free when you have priority.", "error");
    return;
  }

  const input = q("debugCardSearch");
  const cardName = input.value.trim();
  if (!cardName) {
    updateDebugStatus("Type a card name before casting.", "error");
    return;
  }

  const card = await attachCardTargetSpec(await fetchCardByName(cardName), seat);
  const resolvedCardName = normalizeCardName(card) || cardName;
  pendingCastModeIndex = null;

  if (card && cardIsModal(card) && startModalChoicePrompt(card, "debug_cast_free")) {
    updateDebugStatus(`Choose a mode for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetGraveyardCreature(card)) {
    startCastGraveyardCreatureTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a creature card in a graveyard for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetLand(card)) {
    startCastLandTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a land target for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetArtifact(card)) {
    startCastArtifactTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose an artifact target for ${resolvedCardName}.`, "success");
    return;
  }

  // Before every single-target check: a spell naming "up to N targets" has an
  // ordinary kind ("creature") and would otherwise take the one-click picker,
  // which can collect only the first of them.
  if (card && cardRequiresSeveralTargets(card)) {
    startCastSeveralTargetsPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose targets for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardOffersCopyCreatureChoice(card)) {
    startCastCreatureTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a creature for ${resolvedCardName} to copy.`, "success");
    return;
  }

  if (card && cardOffersCopyArtifactChoice(card)) {
    startCastArtifactTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose an artifact for ${resolvedCardName} to copy.`, "success");
    return;
  }

  if (card && cardRequiresTargetCreature(card)) {
    startCastCreatureTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a creature target for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetPermanent(card)) {
    startCastPermanentTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a permanent target for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetStackSpell(card)) {
    startCastStackSpellPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a spell on the stack for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresDividedDamage(card)) {
    startCastDividedPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose targets for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetAny(card)) {
    startCastAnyTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a target for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetPlayer(card)) {
    startCastTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a target for ${resolvedCardName}.`, "success");
    return;
  }

  const targetSeat = getDefaultTargetSeat(resolvedCardName);
  if (card && hasXCost(card)) {
    startCastXPrompt(card, targetSeat, null, "debug_cast_free");
    updateDebugStatus(`Choose X for ${resolvedCardName}.`, "success");
    return;
  }

  await sendAction({ seat, action: "debug_cast_free", card_name: resolvedCardName, target_seat: targetSeat });
  updateDebugStatus(`Cast ${resolvedCardName} for free.`, "success");
  updateActionHint(`Debug: cast ${resolvedCardName} for free.`);
}

async function castDebugCardForFreeAsOpponent() {
  if (!sessionId || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }

  const input = q("debugCardSearch");
  const cardName = input.value.trim();
  if (!cardName) {
    updateDebugStatus("Type a card name before casting.", "error");
    return;
  }

  // The opponent variant casts as the other seat, so enumerate targets from that
  // caster's perspective.
  const card = await attachCardTargetSpec(await fetchCardByName(cardName), 1 - seat);
  const resolvedCardName = normalizeCardName(card) || cardName;
  pendingCastModeIndex = null;

  if (card && cardIsModal(card) && startModalChoicePrompt(card, "debug_cast_free_opponent")) {
    updateDebugStatus(`Choose a mode for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetGraveyardCreature(card)) {
    startCastGraveyardCreatureTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a creature card in a graveyard for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetLand(card)) {
    startCastLandTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a land target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetArtifact(card)) {
    startCastArtifactTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose an artifact target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  // Before every single-target check: a spell naming "up to N targets" has an
  // ordinary kind ("creature") and would otherwise take the one-click picker,
  // which can collect only the first of them.
  if (card && cardRequiresSeveralTargets(card)) {
    startCastSeveralTargetsPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose targets for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardOffersCopyCreatureChoice(card)) {
    startCastCreatureTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a creature for ${resolvedCardName} to copy (as opponent).`, "success");
    return;
  }

  if (card && cardOffersCopyArtifactChoice(card)) {
    startCastArtifactTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose an artifact for ${resolvedCardName} to copy (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetCreature(card)) {
    startCastCreatureTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a creature target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetPermanent(card)) {
    startCastPermanentTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a permanent target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetStackSpell(card)) {
    startCastStackSpellPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a spell on the stack for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresDividedDamage(card)) {
    startCastDividedPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose targets for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetAny(card)) {
    startCastAnyTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  if (card && cardRequiresTargetPlayer(card)) {
    startCastTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a target for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  const targetSeat = getOpponentDefaultTargetSeat(resolvedCardName);
  if (card && hasXCost(card)) {
    startCastXPrompt(card, targetSeat, null, "debug_cast_free_opponent");
    updateDebugStatus(`Choose X for ${resolvedCardName} (as opponent).`, "success");
    return;
  }

  await sendAction({
    seat,
    action: "debug_cast_free_opponent",
    card_name: resolvedCardName,
    target_seat: targetSeat,
  });
  updateDebugStatus(`Cast ${resolvedCardName} for free as opponent.`, "success");
  updateActionHint(`Debug: cast ${resolvedCardName} for free as opponent.`);
}

// ---------------------------------------------------------------------------
// Card verification tracker
// ---------------------------------------------------------------------------

async function refreshVerifyProgress() {
  const el = q("debugVerifyProgress");
  if (!el) return;
  try {
    const resp = await fetch("/api/verification");
    if (!resp.ok) throw new Error("failed");
    const payload = await resp.json();
    const c = payload.counts || {};
    el.textContent = `Verified ${c.pass || 0} passed, ${c.fail || 0} failed, ${c.equivalent || 0} equivalent, ${c.untested || 0} untested (of ${payload.total || 0}).`;
    el.classList.remove("error");
  } catch (e) {
    el.textContent = "Could not load verification progress.";
    el.classList.add("error");
  }
}

async function addUntestedCardToHand() {
  if (!sessionId || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }
  const resp = await fetch("/api/verification/next-untested");
  if (resp.status === 404) {
    updateDebugStatus("All cards have already been tested. 🎉", "success");
    return;
  }
  if (!resp.ok) {
    updateDebugStatus("Could not pick an untested card.", "error");
    return;
  }
  const payload = await resp.json();
  const cardName = payload.card_name;
  await sendAction({ seat, action: "debug_add_to_hand", card_name: cardName });
  q("debugCardSearch").value = cardName;
  updateDebugStatus(`Added untested card "${cardName}" to your hand (${payload.remaining} untested left). Test it, then Mark Test Result.`, "success");
  updateActionHint(`Debug: added untested card "${cardName}" to your hand.`);
}

function setVerifyReasonVisibility() {
  const failChecked = document.querySelector('input[name="verifyResult"]:checked')?.value === "fail";
  q("verifyReasonField").classList.toggle("hidden", !failChecked);
}

function openVerifyResultModal(prefillName = "") {
  const name = prefillName || q("debugCardSearch")?.value.trim() || "";
  q("verifyCardName").value = name;
  const passRadio = document.querySelector('input[name="verifyResult"][value="pass"]');
  if (passRadio) passRadio.checked = true;
  q("verifyReason").value = "";
  setVerifyReasonVisibility();
  updateVerifyStatus("");
  q("verifyResultModal").classList.remove("hidden");
  SFX.onNotificationAppear();
  q("verifyCardName").focus();
  fetchVerifySuggestions(name).catch(() => {
    // Keep silent on open to avoid noisy UI warnings.
  });
}

function closeVerifyResultModal() {
  if (!q("verifyResultModal").classList.contains("hidden")) SFX.onNotificationClose();
  q("verifyResultModal").classList.add("hidden");
}

function updateVerifyStatus(message, status) {
  const el = q("verifyResultStatus");
  if (!el) return;
  el.textContent = message || "";
  el.classList.remove("error", "success");
  if (status) el.classList.add(status);
}

async function submitVerifyResult() {
  const cardName = q("verifyCardName").value.trim();
  if (!cardName) {
    updateVerifyStatus("Enter a card name.", "error");
    return;
  }
  const result = document.querySelector('input[name="verifyResult"]:checked')?.value || "pass";
  const reason = q("verifyReason").value.trim();
  if (result === "fail" && !reason) {
    updateVerifyStatus("Add a reason describing the failure.", "error");
    return;
  }
  try {
    await postJson("/api/verification", {
      card_name: cardName,
      status: result,
      reason: result === "fail" ? reason : null,
    });
  } catch (e) {
    updateVerifyStatus(e.message || "Failed to save result.", "error");
    return;
  }
  closeVerifyResultModal();
  updateDebugStatus(`Recorded "${cardName}" as ${result.toUpperCase()}.`, "success");
  refreshVerifyProgress();
}

let trackerCards = [];

function renderTrackerList() {
  const listEl = q("trackerList");
  if (!listEl) return;
  const nameFilter = q("trackerFilter").value.trim().toLowerCase();
  const statusFilter = q("trackerStatusFilter").value;
  // "equivalent" is derived, not recorded: the card runs the same engine
  // paths as a passing peer, so it needs no separate manual pass.
  const badge = { pass: "✅", fail: "❌", untested: "⬜", equivalent: "≡" };
  listEl.innerHTML = "";
  const filtered = trackerCards.filter((card) => {
    if (statusFilter !== "all" && card.status !== statusFilter) return false;
    if (nameFilter && !card.card_name.toLowerCase().includes(nameFilter)) return false;
    return true;
  });
  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "tracker-empty";
    empty.textContent = "No cards match this filter.";
    listEl.appendChild(empty);
    return;
  }
  for (const card of filtered) {
    const row = document.createElement("div");
    row.className = `tracker-row tracker-row--${card.status}`;

    const name = document.createElement("span");
    name.className = "tracker-name";
    name.textContent = `${badge[card.status]} ${card.card_name}`;
    row.appendChild(name);

    if (card.status === "fail" && card.reason) {
      const reason = document.createElement("span");
      reason.className = "tracker-reason";
      reason.textContent = card.reason;
      row.appendChild(reason);
    }

    const retest = document.createElement("button");
    retest.type = "button";
    retest.className = "secondary-btn tracker-retest";
    retest.textContent = card.status === "untested" ? "Mark…" : "Re-mark…";
    retest.addEventListener("click", () => {
      closeTrackerModal();
      openVerifyResultModal(card.card_name);
    });
    row.appendChild(retest);

    listEl.appendChild(row);
  }
}

async function openTrackerModal() {
  q("trackerModal").classList.remove("hidden");
  SFX.onNotificationAppear();
  q("trackerSummary").textContent = "Loading…";
  try {
    const resp = await fetch("/api/verification");
    if (!resp.ok) throw new Error("failed");
    const payload = await resp.json();
    trackerCards = payload.cards || [];
    const c = payload.counts || {};
    q("trackerSummary").textContent = `${c.pass || 0} passed · ${c.fail || 0} failed · ${c.equivalent || 0} equivalent · ${c.untested || 0} untested · ${payload.total || 0} total`;
    renderTrackerList();
  } catch (e) {
    q("trackerSummary").textContent = "Could not load the tracker.";
  }
}

function closeTrackerModal() {
  if (!q("trackerModal").classList.contains("hidden")) SFX.onNotificationClose();
  q("trackerModal").classList.add("hidden");
}

// The preview is a hover-only overlay floating over the battlefield's left
// middle: it appears when something is hovered and hides when nothing is.
// Hides are deferred one frame because a single mousemove can end one hover
// source and start another (canvas card -> stack card, canvas -> hand fan);
// the show cancels the pending hide so the preview never flickers.
let _previewHideRaf = null;

function _cancelPendingPreviewHide() {
  if (_previewHideRaf !== null) {
    cancelAnimationFrame(_previewHideRaf);
    _previewHideRaf = null;
  }
}

function scheduleHidePreview() {
  if (_previewHideRaf !== null) return;
  _previewHideRaf = requestAnimationFrame(() => {
    _previewHideRaf = null;
    clearCardPreview();
  });
}

function clearCardPreview() {
  _cancelPendingPreviewHide();
  q("cardPreviewOverlay")?.classList.add("hidden");
}

// One "symbol: count" line per counter kind on a permanent (["≈: 3"] for a
// Cyclone holding three wind counters). Empty for a card with no counters, or a
// bare card name / hand card that has no `counters` map.
function previewCounterLines(card) {
  if (!card || typeof card !== "object") return [];
  const map = card.counters;
  const entries = [];
  if (map && typeof map === "object") {
    for (const [kind, n] of Object.entries(map)) {
      if (Number(n) > 0) entries.push([kind, Number(n)]);
    }
  } else if (Number(card.corpse_counters) > 0) {
    entries.push(["corpse", Number(card.corpse_counters)]);
  }
  return entries.map(([kind, n]) => {
    const style = counterBadgeStyle(kind);
    return `${style.previewIcon || style.icon}: ${n}`;
  });
}

function showCardPreview(card) {
  _cancelPendingPreviewHide();
  q("cardPreviewOverlay")?.classList.remove("hidden");
  const largeImageUri = normalizeLargeImageUri(card);
  q("cardPreviewName").textContent = normalizeCardName(card) || "Card";
  q("cardPreviewType").textContent = typeof card === "string" ? "" : card.type || "";
  const previewText = typeof card === "string" ? "" : card.oracle_text || "";
  const keywords = typeof card === "object" && Array.isArray(card?.keywords) ? card.keywords : [];
  // Effective keywords reflect the live board (aura grants, pumps, removals), so
  // a creature that gained Flying — or lost it to Earthbind — reads correctly.
  const keywordLabel = keywords.length ? `Keywords: ${keywords.join(", ")}` : "";
  const sicknessLabel = typeof card === "object" && card?.summoning_sick ? "Summoning Sickness" : "";
  // A text-changing spell (Sleight of Mind / Magical Hack) records per-word edits
  // so the oracle text can show the old word struck through and the new one in gold.
  const textChanges = typeof card === "object" && Array.isArray(card?.text_changes) ? card.text_changes : [];
  // Counters currently on the permanent (wind counters from Cyclone, corpse
  // counters from Scavenging Ghoul, …), one "symbol: count" line per kind.
  const counterLines = previewCounterLines(card);
  const sections = [];
  if (keywordLabel) sections.push(renderSymbolsInline(keywordLabel));
  if (previewText) sections.push(renderOracleTextWithChanges(previewText, textChanges));
  for (const line of counterLines) sections.push(renderSymbolsInline(line));
  if (sicknessLabel) sections.push(renderSymbolsInline(sicknessLabel));
  const previewEl = q("cardPreviewText");
  if (previewEl) previewEl.innerHTML = sections.join("<br>");

  if (!largeImageUri) {
    q("cardPreview").classList.add("empty-preview");
    q("cardPreviewImage").src = "/images/card_back.webp";
    q("cardPreviewImage").alt = "Card back";
    q("cardPreviewImage").classList.remove("hidden");
    q("cardPreviewEmpty").classList.add("hidden");
    return;
  }

  q("cardPreview").classList.remove("empty-preview");
  q("cardPreviewImage").src = largeImageUri;
  q("cardPreviewImage").alt = `${normalizeCardName(card)} preview`;
  q("cardPreviewImage").classList.remove("hidden");
  q("cardPreviewEmpty").classList.add("hidden");
}

function createCardElement(card, options = {}) {
  const {
    draggable = false,
    dragKind = null,
    tapped = false,
    hidden = false,
    compact = false,
    subtitle = "",
    interactive = false,
    castOnClick = false,
    permanentIndex = null,
    handIndex = null,
    cleanupSelectable = false,
    mulliganBottomSelectable = false,
    discardSelectable = false,
    balanceHandSelectable = false,
    selected = false,
    targetSeat = null,
    zoneKind = "",
    playable = false,
    showManaCost = true,
  } = options;
  const cardEl = document.createElement("div");
  cardEl.className = "card";
  if (zoneKind) {
    cardEl.dataset.zoneKind = zoneKind;
  }
  if (Number.isInteger(targetSeat)) {
    cardEl.dataset.targetSeat = String(targetSeat);
  }
  if (Number.isInteger(permanentIndex)) {
    cardEl.dataset.permanentIndex = String(permanentIndex);
  }
  if (!hidden && typeof card === "object") {
    cardEl.dataset.previewCard = JSON.stringify(card);
  }
  if (!hidden && typeof card === "object" && card.summoning_sick) {
    cardEl.classList.add("summoning-sick");
    const badge = document.createElement("img");
    badge.className = "card-overlay-badge";
    badge.src = "/symbols/summoning_sickness.png";
    badge.alt = "Summoning Sickness";
    badge.title = "Summoning Sickness";
    cardEl.appendChild(badge);
  }
  if (draggable) {
    cardEl.classList.add("draggable");
    cardEl.draggable = true;
  }
  if (tapped) cardEl.classList.add("tapped");
  if (hidden) cardEl.classList.add("card-hidden");
  if (interactive) cardEl.classList.add("clickable");
  if (cleanupSelectable || mulliganBottomSelectable || discardSelectable || balanceHandSelectable)
    cardEl.classList.add("cleanup-selectable", "clickable");
  if (selected) cardEl.classList.add("selected-card");
  if (playable && !selected) cardEl.classList.add("playable");
  if (zoneKind === "hand" && isPendingHandCastCard(card, handIndex)) cardEl.classList.add("casting-card");

  if (hidden) {
    const img = document.createElement("img");
    img.src = "/images/card_back.webp";
    img.alt = "Card back";
    cardEl.appendChild(img);
  } else {
    const imageUri = normalizeImageUri(card);
    if (imageUri) {
      const img = document.createElement("img");
      img.src = imageUri;
      img.alt = normalizeCardName(card);
      cardEl.appendChild(img);
    }

    const label = document.createElement("div");
    label.className = "card-label";
    const name = normalizeCardName(card) || "Card";
    const stats = cardStatsLabel(card);
    const suffix = [stats, subtitle].filter(Boolean).join(" ");
    label.textContent = suffix ? `${name} ${suffix}` : name;
    cardEl.appendChild(label);
  }

  if (draggable && dragKind) {
    cardEl.addEventListener("dragstart", (event) => {
      cardEl.classList.add("combat-source");
      combatDragSource = {
        sourceEl: cardEl,
        payload: { kind: dragKind, permanentIndex },
        pointer: { x: event.clientX || 0, y: event.clientY || 0 },
      };
      renderCombatOverlay();
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(
        "text/plain",
        JSON.stringify({ kind: dragKind, name: normalizeCardName(card), permanentIndex, handIndex })
      );
    });
    cardEl.addEventListener("dragend", () => {
      cardEl.classList.remove("combat-source");
      combatDragSource = null;
      renderCombatOverlay();
    });
  }

  if (compact) {
    cardEl.style.width = "54px";
    cardEl.style.minHeight = "74px";
  }

  if (Number.isInteger(targetSeat) && zoneKind) {
    cardEl.addEventListener("click", (event) => {
      if (!pendingCastTarget) return;

      const validTarget = isPendingCastTargetValidForCard(card, {
        targetSeat,
        zoneKind,
        permanentIndex,
      });
      if (!validTarget) {
        updateActionHint("That is not a valid target for the pending spell.", true);
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }

      event.preventDefault();
      event.stopImmediatePropagation();
      const targetPermanentIndex = zoneKind === "battlefield" ? permanentIndex : null;
      resolvePendingCastTarget(targetSeat, targetPermanentIndex);
    });
  }

  if (interactive && typeof card === "object") {
    cardEl.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();

      if (seat === null) {
        updateActionHint("Join or create a session before interacting.", true);
        return;
      }

      try {
        const cardName = normalizeCardName(card);
        if (!cardName) return;

        const untapInfo = getUntapLandSelectionInfo(currentState);
        if (
          untapInfo &&
          zoneKind === "battlefield" &&
          Number.isInteger(permanentIndex) &&
          targetSeat === seat
        ) {
          const candidateIndices = Array.isArray(untapInfo.candidate_indices) ? untapInfo.candidate_indices : [];
          if (!candidateIndices.includes(permanentIndex)) {
            updateActionHint(`${cardName} is not a valid untap choice.`, true);
            return;
          }
          await sendAction({ seat, action: "untap_select", permanent_index: permanentIndex });
          const nextInfo = getUntapLandSelectionInfo(currentState);
          const selectedCount = Number(nextInfo?.selected_count || 0);
          const maxCount = Number(nextInfo?.max_count || 0);
          updateActionHint(`Untap selection: ${selectedCount}/${maxCount} permanent(s) selected.`);
          return;
        }

        // Attacker selection only owns the click before attackers are declared.
        // After they're locked the step is a priority window, so clicks fall
        // through to tap/activate.
        if (
          zoneKind === "battlefield" &&
          Number.isInteger(permanentIndex) &&
          isCombatStep(currentState, "declare_attackers") &&
          seat === currentState?.current_turn &&
          targetSeat === seat &&
          !getCombatState(currentState)?.attackers_locked
        ) {
          // Only creatures that can legally attack may be selected (CR 508.1a).
          if (!getValidAttackerIndices(currentState).includes(permanentIndex)) {
            updateActionHint(`${cardName} can't attack right now.`, true);
            return;
          }
          toggleCombatAttackerDraft(permanentIndex);
          renderBoard(currentState);
          updateActionHint(
            `Attackers selected: ${combatAttackerDraft.length}. Use Alpha Strike to toggle all valid attackers, then press OK.`,
          );
          return;
        }

        // Beyond this point we're trying to use the permanent (tap/activate),
        // which only the controller may do.
        if (zoneKind === "battlefield" && targetSeat !== seat) {
          updateActionHint("You don't control this permanent.", true);
          return;
        }

        if (!hasActivatedAbility(card)) {
          updateActionHint(`${cardName} has no activated ability to use.`, true);
          return;
        }

        // Activated abilities that act on a target land (e.g. Gaea's Liege)
        // let the player pick which land in play to affect. The backend supplies
        // the legal lands (already excluding Swamps for Cyclopean Tomb, etc.).
        if (activatedAbilityRequiresTargetLand(card)) {
          const fields = pendingTargetFields(card);
          if (fields.validKeys.size === 0) {
            const noun = activatedAbilityTargetLandExcludesSwamp(card) ? "non-Swamp land" : "land";
            updateActionHint(`No valid ${noun} targets in play for ${cardName}.`, true);
            return;
          }
          pendingCastTarget = {
            card,
            cardName: normalizeCardName(card),
            targetKind: "land",
            castAction: "activate",
            sourcePermanentIndex: permanentIndex,
            ...fields,
          };
          renderActivationPrompt();
          return;
        }

        // Abilities that buff/modify the controller's own creatures target self, not
        // opponent. Abilities with a real target are intercepted by the dedicated
        // prompt flows inside startActivationPrompt, so the FFA seat here is only
        // the formal target_seat default — no picker needed.
        const activationTargetSeat = activatedAbilityTargetsSelf(card)
          ? seat
          : (isFfaState() ? firstLivingOpponentSeat(currentState, seat, `${cardName} activation default`) : 1 - seat);
        startActivationPrompt(card, activationTargetSeat, permanentIndex);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
  }

  if (
    (castOnClick || mulliganBottomSelectable || discardSelectable || balanceHandSelectable) &&
    typeof card === "object"
  ) {
    cardEl.classList.add("clickable");
    cardEl.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();

      if (seat === null) {
        updateActionHint("Join or create a session before interacting.", true);
        return;
      }

      if (pendingCastHandCard && !isPendingHandCastCard(card, handIndex)) {
        updateActionHint("Finish the current cast before starting another.", true);
        return;
      }

      // Second click on the card while the insufficient-mana prompt is open
      // performs the auto-tap, same as pressing the Auto-Tap button.
      if (pendingAutoTap && isPendingHandCastCard(card, handIndex)) {
        const me = getCurrentPlayerState();
        const canSatisfy = !!me && canAutoTapSatisfyCost(
          pendingAutoTapCost(pendingAutoTap),
          me.mana_pool,
          me.battlefield
        );
        if (!canSatisfy) {
          updateActionHint("Not enough untapped lands to auto-tap for this cost.", true);
          return;
        }
        await performAutoTap();
        return;
      }

      try {
        if (cleanupSelectable) {
          await sendAction({ seat, action: "cleanup_select", hand_index: handIndex });
          const nextInfo = getCleanupDiscardInfo(currentState);
          if (nextInfo) {
            const remaining = Math.max(0, Number(nextInfo.required_count || 0) - Number(nextInfo.selected_count || 0));
            updateActionHint(`Cleanup: select ${remaining} more card(s) to discard.`);
          } else {
            updateActionHint("Cleanup discard complete.");
          }
          return;
        }

        if (discardSelectable) {
          await toggleDiscardSelection(handIndex);
          return;
        }

        if (balanceHandSelectable) {
          toggleBalanceHandSelection(handIndex);
          return;
        }

        if (mulliganBottomSelectable) {
          await sendAction({ seat, action: "mulligan_bottom_select", hand_index: handIndex });
          const nextInfo = getPregameInfo(currentState);
          const required = Number(nextInfo?.required_count || 0);
          const selectedCount = Number(nextInfo?.selected_count || 0);
          const remaining = Math.max(0, required - selectedCount);
          updateActionHint(
            remaining > 0
              ? `Select ${remaining} more card(s) for the bottom of your library.`
              : "Selection complete — click Confirm."
          );
          return;
        }

        const cardName = normalizeCardName(card);
        if (!cardName) return;
        beginPendingHandCast(card, handIndex);
        cardEl.classList.add("casting-card");

        // Modal "Choose one —" spells prompt for the mode first; the chosen mode
        // then drives which targeting flow (if any) runs.
        if (cardIsModal(card) && startModalChoicePrompt(card)) {
          return;
        }

        // A printed additional cost is announced before any target (CR 601.2b
        // precedes 601.2c), and none of the cards printing this one also
        // targets, so it comes first among the target cascades below.
        if (cardRequiresDiscardCost(card) && startCastDiscardCostPrompt(card)) {
          return;
        }

        if (cardRequiresTargetGraveyardCreature(card)) {
          startCastGraveyardCreatureTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetLand(card)) {
          startCastLandTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetArtifact(card)) {
          startCastArtifactTargetPrompt(card);
          return;
        }

        if (cardRequiresSeveralTargets(card)) {
          startCastSeveralTargetsPrompt(card);
          return;
        }

        if (cardOffersCopyCreatureChoice(card)) {
          startCastCreatureTargetPrompt(card);
          return;
        }

        if (cardOffersCopyArtifactChoice(card)) {
          startCastArtifactTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetCreature(card)) {
          startCastCreatureTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetPermanent(card)) {
          startCastPermanentTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetStackSpell(card)) {
          startCastStackSpellPrompt(card);
          return;
        }

        if (cardRequiresDividedDamage(card)) {
          startCastDividedPrompt(card);
          return;
        }

        if (cardRequiresTargetAny(card)) {
          startCastAnyTargetPrompt(card);
          return;
        }

        if (cardRequiresTargetPlayer(card)) {
          startCastTargetPrompt(card);
          return;
        }

        const targetSeat = getDefaultTargetSeat(cardName);
        if (hasXCost(card)) {
          startCastXPrompt(card, targetSeat);
          return;
        }

        const actionBody = { seat, action: "cast", card_name: cardName, target_seat: targetSeat };
        try {
          await sendAction(actionBody);
          updateActionHint(`Cast ${cardName} targeting seat ${targetSeat}.`);
          clearPendingHandCast();
        } catch (e) {
          if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
            pendingAutoTap = { card, cardName, actionBody };
            renderActivationPrompt();
            return;
          }
          clearPendingHandCast();
          throw e;
        }
      } catch (e) {
        clearPendingHandCast();
        updateActionHint(e.message, true);
      }
    });
  }

  const wrapper = document.createElement("div");
  wrapper.className = "card-wrapper";
  wrapper.appendChild(cardEl);

  if (!hidden && showManaCost && typeof card === "object" && card.mana_cost) {
    const costEl = document.createElement("div");
    costEl.className = "card-mana-cost";
    costEl.innerHTML = renderSymbolsInline(card.mana_cost);
    wrapper.appendChild(costEl);
  }

  return wrapper;
}

function renderCardRow(containerId, cards, options = {}) {
  const container = q(containerId);
  container.innerHTML = "";
  const entries = Array.isArray(cards) ? cards.map((card, index) => ({ card, index })) : [];

  const appendEntries = (targetContainer, rowEntries) => {
    for (const { card, index } of rowEntries) {
      if (card === "<hidden>") {
        targetContainer.appendChild(createCardElement("Hidden", { ...options, hidden: true }));
        continue;
      }
      const tapped = typeof card === "object" ? !!card.tapped : false;
      const permanentIndex = options.zoneKind === "battlefield" ? index : null;
      const selected =
        (Array.isArray(options.selectedHandIndices) && options.selectedHandIndices.includes(index)) ||
        (Array.isArray(options.selectedPermanentIndices) && options.selectedPermanentIndices.includes(index));
      targetContainer.appendChild(
        createCardElement(card, { ...options, tapped, permanentIndex, handIndex: index, selected })
      );
    }
  };

  if (options.zoneKind === "battlefield") {
    const isLandPermanent = (card) => {
      if (!card || typeof card === "string") return false;
      return String(card.type || "").toLowerCase().includes("land");
    };

    const landEntries = entries.filter(({ card }) => isLandPermanent(card));
    const nonLandEntries = entries.filter(({ card }) => !isLandPermanent(card));
    const backRowIndex = containerId === "oppBattlefield" ? 0 : 1;

    const rowElements = [0, 1].map((rowIndex) => {
      const row = document.createElement("div");
      row.className = "battlefield-subrow";
      row.dataset.rowIndex = String(rowIndex);
      container.appendChild(row);
      return row;
    });

    appendEntries(rowElements[1 - backRowIndex], nonLandEntries);
    appendEntries(rowElements[backRowIndex], landEntries);
    return;
  }

  appendEntries(container, entries);
}

// When the viewer's hand overflows, it becomes a carousel: only a window of
// cards is fanned at once and left/right arrows scroll through the rest.
const HAND_CAROUSEL_WINDOW = 12;
const HAND_CAROUSEL_STEP = 4;
let handCarouselOffset = 0;

// Per-fan card keys from the previous render, so a full state-refresh rebuild
// only plays the entrance animation for cards that actually just arrived.
const _prevHandKeysByContainer = {};

function _handCardKey(card) {
  return card === "<hidden>" ? "<hidden>" : String(card?.name ?? card);
}

function renderHandFan(containerId, cards, options = {}) {
  const container = q(containerId);
  container.innerHTML = "";

  const isOpponent = container.classList.contains("hand-fan--opponent");
  // Bottom-anchored opponent fans (the 4-player FFA bottom-right seat) fan
  // like the viewer's hand — cards rising from the bottom edge — while still
  // rendering small face-down backs.
  const anchorBottom = !isOpponent || container.classList.contains("hand-fan--bottom");
  const entries = Array.isArray(cards) ? cards : [];
  const totalCount = entries.length;
  const MAX_ANGLE = 15;
  const MAX_RISE = isOpponent ? 22 : 44;
  const PUSH_X = isOpponent ? 7 : 14;
  const { playableHandIndices = [], selectedHandIndices = [], ...fanOptions } = options;

  // Carousel only applies to the viewer's own (face-up) hand when it overflows.
  const carousel = !isOpponent && totalCount > HAND_CAROUSEL_WINDOW;
  let windowEntries = entries.map((card, index) => ({ card, index }));
  let maxOffset = 0;
  if (carousel) {
    maxOffset = totalCount - HAND_CAROUSEL_WINDOW;
    handCarouselOffset = Math.max(0, Math.min(handCarouselOffset, maxOffset));
    windowEntries = windowEntries.slice(handCarouselOffset, handCarouselOffset + HAND_CAROUSEL_WINDOW);
  } else {
    handCarouselOffset = 0;
  }
  const count = windowEntries.length;

  // Multiset diff against the previous render: hand indices whose card wasn't
  // present before are "new" and get the entrance animation.
  const prevCounts = new Map();
  for (const key of _prevHandKeysByContainer[containerId] || []) {
    prevCounts.set(key, (prevCounts.get(key) || 0) + 1);
  }
  const newIndexSet = new Set();
  entries.forEach((card, index) => {
    const key = _handCardKey(card);
    const remaining = prevCounts.get(key) || 0;
    if (remaining > 0) prevCounts.set(key, remaining - 1);
    else newIndexSet.add(index);
  });
  _prevHandKeysByContainer[containerId] = entries.map(_handCardKey);

  const slots = [];
  const enteringCardEls = [];

  windowEntries.forEach(({ card, index }, pos) => {
    const normalizedPos = count <= 1 ? 0 : (pos / (count - 1)) * 2 - 1;
    const angle = normalizedPos * MAX_ANGLE * (anchorBottom ? 1 : -1);
    // Both hands: center card most prominent (1-pos² parabola).
    const rise = (1 - normalizedPos * normalizedPos) * MAX_RISE;

    const isHidden = card === "<hidden>";
    const cardEl = createCardElement(isHidden ? "Hidden" : card, {
      ...fanOptions,
      compact: false,
      hidden: isHidden,
      handIndex: index,
      playable: !isHidden && playableHandIndices.includes(index),
      selected: !isHidden && selectedHandIndices.includes(index),
    });

    const slot = document.createElement("div");
    slot.className = "hand-fan-slot";
    // The hand index, not the fan position: the viewer's carousel fans a window
    // of the hand, so a card arriving at index 9 may sit in slot 5 or in no slot
    // at all. Zone -> hand flights land on the slot addressed this way.
    slot.dataset.handIndex = String(index);
    // Top-anchored opponent fans tuck their face-down cards into the top edge
    // (mirror of the viewer's bottom tuck): only the bottom half shows until a
    // card is revealed (rendered face-up), which drops the tuck for full view.
    if (isOpponent && !anchorBottom && isHidden) {
      slot.classList.add("hand-fan-slot--tucked");
    }
    slot.style.setProperty("--fan-angle", `${angle}deg`);
    slot.style.setProperty("--fan-push-x", "0px");
    slot.style.setProperty("--fan-z", `${pos * 5}px`);
    slot.style.zIndex = String(pos + 1);
    if (anchorBottom) {
      slot.style.marginBottom = `${rise}px`;
    } else {
      slot.style.marginTop = `${rise}px`;
    }
    slot.appendChild(cardEl);

    container.appendChild(slot);
    slots.push(slot);
    // A card whose zone -> hand flight is still in the air belongs to the clone
    // until it lands. One state change renders the hand several times over, and
    // every render builds a fresh element that knows nothing about the flight —
    // so the hold is re-applied here rather than held on the element.
    if (window.FX && handSlotsInFlight.has(handFlightKey(containerId, index))) {
      FX.holdForFlight(cardEl);
    } else if (newIndexSet.has(index)) {
      enteringCardEls.push(cardEl);
    }
  });

  if (enteringCardEls.length && window.FX) FX.handEnter(enteringCardEls);

  renderHandCarouselArrows(container, {
    active: carousel,
    offset: handCarouselOffset,
    maxOffset,
    totalCount,
    rerender: () => renderHandFan(containerId, cards, options),
  });

  slots.forEach((slot, i) => {
    slot.addEventListener("mouseenter", () => {
      slots.forEach((other, j) => {
        other.style.setProperty("--fan-push-x", `${(j - i) * PUSH_X}px`);
      });
    });
    slot.addEventListener("mouseleave", () => {
      slots.forEach((other) => other.style.setProperty("--fan-push-x", "0px"));
    });
  });
}

// Manage the carousel arrows that live in the hand-fan-wrap alongside the fan.
// They scroll the viewer's hand window left/right when it overflows.
function renderHandCarouselArrows(container, { active, offset, maxOffset, totalCount, rerender }) {
  const wrap = container.parentElement;
  if (!wrap) return;
  wrap
    .querySelectorAll(".hand-carousel-arrow")
    .forEach((el) => el.remove());
  if (!active) return;

  const makeArrow = (dir) => {
    const atStart = dir < 0 && offset <= 0;
    const atEnd = dir > 0 && offset >= maxOffset;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      `hand-carousel-arrow hand-carousel-arrow--${dir < 0 ? "left" : "right"}` +
      (atStart || atEnd ? " hand-carousel-arrow--disabled" : "");
    btn.textContent = dir < 0 ? "‹" : "›";
    btn.title =
      dir < 0 ? "Scroll hand left" : "Scroll hand right";
    btn.setAttribute("aria-label", btn.title);
    if (atStart || atEnd) {
      btn.disabled = true;
    } else {
      btn.addEventListener("click", () => {
        handCarouselOffset = Math.max(0, Math.min(offset + dir * HAND_CAROUSEL_STEP, maxOffset));
        rerender();
      });
    }
    return btn;
  };

  const leftArrow = makeArrow(-1);
  const rightArrow = makeArrow(1);
  wrap.appendChild(leftArrow);
  wrap.appendChild(rightArrow);

  // Anchor the arrows beside the leftmost/rightmost fanned card rather than
  // the stage edges — the wrap spans the full board width, so the class
  // defaults (left/right: 4px) would strand them far from a narrow fan.
  const slotEls = container.querySelectorAll(".hand-fan-slot");
  const first = slotEls[0];
  const last = slotEls[slotEls.length - 1];
  if (first && last) {
    const wrapRect = wrap.getBoundingClientRect();
    const firstRect = first.getBoundingClientRect();
    const lastRect = last.getBoundingClientRect();
    const gapX = 10;
    leftArrow.style.left = `${Math.max(4, firstRect.left - wrapRect.left - 40 - gapX)}px`;
    rightArrow.style.right = `${Math.max(4, wrapRect.right - lastRect.right - 40 - gapX)}px`;
    // Level with the visible (tucked) card tops — high enough to clear the
    // name/life pill in the wrap's bottom-left corner.
    const arrowTop = `${firstRect.top - wrapRect.top - 8}px`;
    leftArrow.style.top = arrowTop;
    rightArrow.style.top = arrowTop;
  }
}

function renderZoneCards(containerId, cards, { zoneSeat = null, zoneKind = "" } = {}) {
  const container = q(containerId);
  container.innerHTML = "";
  if (!cards || cards.length === 0) return;
  const graveyardTargeting =
    pendingCastTarget &&
    pendingCastTarget.targetKind === "graveyard_creature" &&
    zoneKind === "graveyard" &&
    Number.isInteger(zoneSeat);
  // The backend enumerates the legal graveyard targets (already restricting to the
  // caster's own graveyard for "from your graveyard" cards); a card is targetable
  // only if its (seat, index) appears there.
  const validGraveyard = pendingCastTarget?.validGraveyard || [];
  const isValidGraveyardTarget = (index) =>
    validGraveyard.some((t) => t.seat === zoneSeat && t.index === index);
  // A cast permission (engine/cast_permissions.py) over the viewer's own
  // graveyard/exile: the backend says which (zone, index) entries the viewer
  // may cast or play right now, and clicking one starts an ordinary cast with
  // the zone riding along.
  // "command" joins graveyard/exile here because the backend answers all three
  // through one `castable_from_zones` list — a commander is offered by CR 903.8
  // rather than by a cast permission, but what the client does with it is
  // identical.
  const castableEntries =
    zoneSeat === seat && (zoneKind === "graveyard" || zoneKind === "exile" || zoneKind === "command")
      ? (currentState?.castable_from_zones || []).filter((entry) => entry.zone === zoneKind)
      : [];
  const isCastableFromZone = (index) => castableEntries.some((entry) => entry.index === index);
  // Render with the most recently added card (end of the array) leftmost,
  // while keeping each card's original index for targeting clicks.
  // Slots already chosen for an "up to N" graveyard prompt, so a second click
  // reads as a deselect rather than as a repeat of the same choice.
  const chosenSlots = pendingCastTarget?.severalGraveyard || null;
  const isChosenGraveyardTarget = (index) =>
    !!chosenSlots && chosenSlots.some((t) => t.seat === zoneSeat && t.idx === index);
  for (let index = cards.length - 1; index >= 0; index--) {
    const card = cards[index];
    const el = createCardElement(card, {
      compact: true, showManaCost: false,
      selected: graveyardTargeting && isChosenGraveyardTarget(index),
    });
    if (graveyardTargeting && isValidGraveyardTarget(index)) {
      el.classList.add("targeting-valid");
      el.style.cursor = "pointer";
      el.addEventListener("click", () => (
        chosenSlots
          ? toggleSeveralGraveyardTarget(zoneSeat, index)
          : resolvePendingCastTarget(zoneSeat, index)
      ));
    } else if (isCastableFromZone(index) && !pendingCastTarget && !pendingCastHandCard) {
      el.classList.add("castable-from-zone");
      el.style.cursor = "pointer";
      const zoneLabel = zoneKind === "command" ? "command zone" : zoneKind;
      const tax = castableEntries.find((entry) => entry.index === index)?.commander_tax || 0;
      // CR 903.8: the tax is part of what this cast will cost, so it is named
      // on the card rather than left to surprise the player at payment.
      el.title = tax
        ? `Cast ${card.name || ""} from your ${zoneLabel} (+{${tax}} commander tax)`
        : `Cast ${card.name || ""} from your ${zoneLabel}`;
      el.addEventListener("click", () => beginZoneCast(card, zoneKind));
    }
    container.appendChild(el);
  }
}

// Start casting a card the viewer holds a cast permission for in their
// graveyard or exile. Mirrors the hand-cast chain: the same target/X prompts
// run, and `pendingCastFromZone` rides sendAction so whichever path fires
// carries the zone.
async function beginZoneCast(card, zone) {
  if (seat === null) return;
  if (pendingCastHandCard) {
    updateActionHint("Finish the current cast before starting another.", true);
    return;
  }
  const cardName = normalizeCardName(card);
  beginPendingHandCast(card);
  pendingCastFromZone = zone;
  try {
    if (cardIsModal(card) && startModalChoicePrompt(card)) return;
    if (cardRequiresDiscardCost(card) && startCastDiscardCostPrompt(card)) return;
    if (cardRequiresTargetGraveyardCreature(card)) { startCastGraveyardCreatureTargetPrompt(card); return; }
    if (cardRequiresTargetLand(card)) { startCastLandTargetPrompt(card); return; }
    if (cardRequiresTargetArtifact(card)) { startCastArtifactTargetPrompt(card); return; }
    if (cardRequiresSeveralTargets(card)) { startCastSeveralTargetsPrompt(card); return; }
    if (cardOffersCopyCreatureChoice(card)) { startCastCreatureTargetPrompt(card); return; }
    if (cardOffersCopyArtifactChoice(card)) { startCastArtifactTargetPrompt(card); return; }
    if (cardRequiresTargetCreature(card)) { startCastCreatureTargetPrompt(card); return; }
    if (cardRequiresTargetPermanent(card)) { startCastPermanentTargetPrompt(card); return; }
    if (cardRequiresTargetStackSpell(card)) { startCastStackSpellPrompt(card); return; }
    if (cardRequiresDividedDamage(card)) { startCastDividedPrompt(card); return; }
    if (cardRequiresTargetAny(card)) { startCastAnyTargetPrompt(card); return; }
    if (cardRequiresTargetPlayer(card)) { startCastTargetPrompt(card); return; }
    const castTargetSeat = getDefaultTargetSeat(cardName);
    if (hasXCost(card)) { startCastXPrompt(card, castTargetSeat); return; }
    const actionBody = { seat, action: "cast", card_name: cardName, target_seat: castTargetSeat, from_zone: zone };
    try {
      await sendAction(actionBody);
      updateActionHint(`Cast ${cardName} from your ${zone}.`);
      clearPendingHandCast();
    } catch (e) {
      if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
        pendingAutoTap = { card, cardName, actionBody };
        renderActivationPrompt();
        return;
      }
      clearPendingHandCast();
      throw e;
    }
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

// ---- Zone reveal panel ----
// Clicking a graveyard/exile pile on the canvas opens a small scrollable
// overlay listing every card in that zone (the piles themselves show only the
// top card). It also auto-opens while a spell is choosing a graveyard target,
// closing again once the target is picked or the cast is cancelled.
let zoneRevealAutoOpened = false;

function zoneRevealSectionFor(zoneSeat, kind) {
  const side = zoneSeat === seat ? "self" : "opp";
  return `${side}-${kind}`;
}

function openZoneReveal(sections, { auto = false } = {}) {
  const overlay = q("zoneRevealOverlay");
  if (!overlay || !sections || !sections.length) return;
  const titles = {
    "self-graveyard": "Your Graveyard",
    "self-exile": "Your Exile",
    "self-ante": "Your Ante",
    "self-command": "Your Command Zone",
    "self-sideboard": "Your Cards Outside the Game",
    "opp-graveyard": "Opponent Graveyard",
    "opp-exile": "Opponent Exile",
    "opp-ante": "Opponent Ante",
    "opp-command": "Opponent Command Zone",
  };
  overlay.querySelectorAll(".zone-reveal-section").forEach((el) => {
    el.classList.toggle("hidden", !sections.includes(el.dataset.zone));
  });
  q("zoneRevealTitle").textContent =
    sections.length === 1 ? (titles[sections[0]] || "Zone") : "Graveyards";
  // Anchor near the matching pile column: opponent zones top-left, own bottom-left.
  const anchorTop = sections[0].startsWith("opp-");
  overlay.classList.toggle("zone-reveal--top", anchorTop);
  overlay.classList.toggle("zone-reveal--bottom", !anchorTop);
  overlay.classList.remove("hidden");
  zoneRevealAutoOpened = auto;
}

function closeZoneReveal() {
  q("zoneRevealOverlay")?.classList.add("hidden");
  zoneRevealAutoOpened = false;
}

// Close the auto-opened reveal panel once graveyard targeting is over.
function closeZoneRevealIfAutoOpened() {
  if (zoneRevealAutoOpened) closeZoneReveal();
}

const lastManaCounts = {};

// The label each "spend this mana only to…" bucket shows. Keyed by the same
// restriction key engine/restricted_mana.py produces, so a bucket the client has
// no label for still renders — as a restricted chip with a generic note, which
// is honest about what it is rather than silently folding it into the pool.
const RESTRICTED_MANA_LABELS = {
  creature: ["creatures only", "This mana can only be used to cast creature spells."],
  instant_or_sorcery: [
    "instants/sorceries only",
    "This mana can only be used to cast an instant or sorcery spell.",
  ],
};

function renderMana(containerId, manaPool, targetSeat = null, restrictedPools = null) {
  const container = q(containerId);
  container.innerHTML = "";
  const pool = manaPool || {};
  const clickable = debugAddManaMode && targetSeat !== null;
  container.classList.toggle("mana-row-addable", clickable);
  const prev = lastManaCounts[containerId] || {};
  const current = {};
  let total = 0;
  for (const symbol of MANA_ORDER) {
    const chip = document.createElement("div");
    const count = Number(pool[symbol] || 0);
    current[symbol] = count;
    total += count;
    chip.className =
      `mana-symbol mana-${symbol} ` + (count > 0 ? "mana-symbol-filled" : "mana-symbol-empty");
    const src = symbolSrc(`{${symbol}}`);
    const glyph = src
      ? `<img class="mtg-symbol mtg-symbol-mana" src="${escapeHtml(src)}" alt="{${symbol}}" title="{${symbol}}" />`
      : `<span class="mana-glyph-text">${symbol === "C" ? "◇" : symbol}</span>`;
    chip.innerHTML =
      `<span class="mana-orb-glyph">${glyph}</span>` +
      `<span class="mana-orb-count">${count}</span>`;
    // Pop the orb when its count changes (e.g. mana added/spent) for feedback.
    if (count !== (prev[symbol] || 0)) {
      chip.classList.add("mana-symbol-bump");
    }
    if (clickable) {
      chip.classList.add("mana-symbol-addable");
      chip.title = `Debug: click to add {${symbol}} to this mana pool`;
      chip.addEventListener("click", () => {
        addDebugMana(targetSeat, symbol).catch((error) => {
          updateDebugStatus(error.message || "Could not add mana.", "error");
        });
      });
    }
    container.appendChild(chip);
  }
  const totalChip = document.createElement("div");
  totalChip.className = "mana-total" + (total > 0 ? " mana-total-active" : "");
  totalChip.title = `${total} total mana available`;
  totalChip.innerHTML =
    `<span class="mana-total-num">${total}</span>` +
    `<span class="mana-total-label">total</span>`;
  container.appendChild(totalChip);

  // Restricted mana lives in its own bucket per restriction and can't pay for
  // anything but the spells that restriction admits, so each gets its own chips
  // rather than being added into the counts above (which would overstate what's
  // spendable). A bare object is the legacy creature-only shape.
  const buckets =
    restrictedPools && !Array.isArray(restrictedPools) && MANA_ORDER.some((s) => s in restrictedPools)
      ? { creature: restrictedPools }
      : restrictedPools || {};
  for (const [key, restricted] of Object.entries(buckets)) {
    const [badge, title] = RESTRICTED_MANA_LABELS[key] || [
      "restricted",
      "This mana can only be spent on certain spells.",
    ];
    for (const symbol of MANA_ORDER) {
      const count = Number((restricted || {})[symbol] || 0);
      if (count <= 0) continue;
      const chip = document.createElement("div");
      chip.className = `mana-symbol mana-${symbol} mana-symbol-filled mana-symbol-restricted`;
      chip.title = title;
      const src = symbolSrc(`{${symbol}}`);
      const glyph = src
        ? `<img class="mtg-symbol mtg-symbol-mana" src="${escapeHtml(src)}" alt="{${symbol}}" title="${escapeHtml(title)}" />`
        : `<span class="mana-glyph-text">${symbol === "C" ? "◇" : symbol}</span>`;
      chip.innerHTML =
        `<span class="mana-orb-glyph">${glyph}</span>` +
        `<span class="mana-orb-count">${count}</span>` +
        `<span class="mana-orb-restricted-badge" title="${escapeHtml(title)}">${badge}</span>`;
      container.appendChild(chip);
    }
  }

  lastManaCounts[containerId] = current;
}

async function addDebugMana(targetSeat, color) {
  if (sessionId === null || seat === null) {
    updateDebugStatus("Create or join a session first.", "error");
    return;
  }
  await sendAction({ seat, action: "debug_add_mana", target_seat: targetSeat, mana_color: color });
  updateActionHint(`Debug: added {${color}} mana.`);
}

let _lastPhaseRailActiveKey = null;

function renderPhaseRail(state) {
  const container = q("phaseRail");
  if (!container) return;

  container.innerHTML = "";
  const activeKey = getActiveStepKey(state);
  const activeKeyChanged = activeKey !== _lastPhaseRailActiveKey;
  _lastPhaseRailActiveKey = activeKey;
  for (const phase of PHASE_RAIL) {
    const item = document.createElement("div");
    item.className = "phase-chip-item";
    item.dataset.phase = phase.key;
    if (activeKey === phase.key) {
      item.classList.add("active");
      item.setAttribute("aria-current", "step");
    }

    // Untap and cleanup never grant priority, so holding there is impossible.
    const lockedNoPriority = NO_PRIORITY_STEPS.has(phase.key);
    const playerEnabled = !disabledPhases.has(phase.key);
    const oppEnabled = !opponentDisabledPhases.has(phase.key);

    const leftHalf = document.createElement("div");
    leftHalf.className = "phase-half phase-half-player" + (playerEnabled ? " phase-half-enabled" : "");
    if (lockedNoPriority) {
      leftHalf.classList.add("phase-half-locked");
      leftHalf.title = `${phase.title}: no priority — can't hold here`;
    } else {
      leftHalf.title = playerEnabled
        ? `${phase.title}: hold priority (your turn) — click to auto-pass`
        : `${phase.title}: auto-pass (your turn) — click to hold priority`;
      leftHalf.addEventListener("click", () => {
        if (disabledPhases.has(phase.key)) {
          disabledPhases.delete(phase.key);
        } else {
          disabledPhases.add(phase.key);
          autoPassDisabledPhaseRequestedStateKey = "";
          maybeAutoPassDisabledPhase();
        }
        renderPhaseRail(currentState);
      });
    }

    const rightHalf = document.createElement("div");
    rightHalf.className = "phase-half phase-half-opp" + (oppEnabled ? " phase-half-enabled" : "");
    if (lockedNoPriority) {
      rightHalf.classList.add("phase-half-locked");
      rightHalf.title = `${phase.title}: no priority — can't hold here`;
    } else {
      rightHalf.title = oppEnabled
        ? `${phase.title}: hold priority (opponent's turn) — click to auto-pass`
        : `${phase.title}: auto-pass (opponent's turn) — click to hold priority`;
      rightHalf.addEventListener("click", () => {
        if (opponentDisabledPhases.has(phase.key)) {
          opponentDisabledPhases.delete(phase.key);
        } else {
          opponentDisabledPhases.add(phase.key);
          autoPassDisabledPhaseRequestedStateKey = "";
          maybeAutoPassDisabledPhase();
        }
        renderPhaseRail(currentState);
      });
    }

    const label = document.createElement("span");
    label.className = "phase-chip-label";
    label.textContent = phase.label;

    item.appendChild(leftHalf);
    item.appendChild(rightHalf);
    item.appendChild(label);
    container.appendChild(item);
    if (activeKey === phase.key && activeKeyChanged && window.FX) FX.phasePulse(item);
  }
}

let _currentStack = [];

function _refreshStackHoldVisuals() {
  const heldIdx = getHeldStackArrayIndex();
  if (battlefieldCanvas) {
    battlefieldCanvas.stackHeldIndex = heldIdx;
    battlefieldCanvas.needsRedraw = true;
  }
}

function toggleStackClickHold(arrayIndex) {
  if (getHeldStackArrayIndex() === arrayIndex) {
    releaseStackClickHold("Priority hold released.");
    return;
  }
  const item = _currentStack[arrayIndex];
  if (!item) return;
  stackClickHold = {
    bottomOffset: _currentStack.length - 1 - arrayIndex,
    sig: _stackItemSig(item),
  };
  _refreshStackHoldVisuals();
  updateActionHint("Priority held: tap lands and cast responses freely. Click the card again to release.");
}

function selectStackSpellTarget(arrayIndex) {
  const pending = pendingCastTarget;
  if (!pending || (pending.targetKind !== "stack" && !pending.alsoStack)) return;
  const item = _currentStack[arrayIndex];
  if (!item || !isStackItemValidCastTarget(item, arrayIndex)) return;

  pendingCastTarget = null;
  renderActivationPrompt();

  // Fork: after choosing the spell to copy, run a second prompt to let the caster
  // choose new targets for the copy before the cast is sent.
  if (pending.copiesSpell && pending.castAction !== "activate") {
    startForkCopyRetarget(pending, arrayIndex, item);
    return;
  }

  // Activated ability that counters a target spell (Deathgrip): send an
  // "activate" action identifying the source permanent and the chosen spell.
  if (pending.castAction === "activate") {
    // Jade Monolith's second stage: the clicked stack spell is the chosen
    // damage SOURCE — send it alongside the already-chosen creature target.
    const body = pending.__sourceStage
      ? {
          seat,
          action: "activate",
          permanent_name: pending.cardName,
          permanent_index: pending.sourcePermanentIndex,
          target_seat: pending.chosenTargetSeat,
          target_permanent_index: pending.chosenTargetIndex,
          source_stack_index: arrayIndex,
        }
      : {
          seat,
          action: "activate",
          permanent_name: pending.cardName,
          permanent_index: pending.sourcePermanentIndex,
          target_stack_index: arrayIndex,
        };
    updateActionHint(`Activating ${pending.cardName} at ${item.card?.name || "spell"}...`);
    sendAction(body)
      .then(() => updateActionHint(`Activated ${pending.cardName}.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

  // Power Sink ({X}{U}): after choosing the spell to counter, prompt for X (the
  // amount its controller must pay) before sending the cast.
  if (hasXCost(pending.card)) {
    startCastXPrompt(pending.card, null, null, pending.castAction || "cast", arrayIndex);
    return;
  }

  // arrayIndex is the top-first index the server expects for target_stack_index.
  const actionBody = {
    seat,
    action: pending.castAction || "cast",
    card_name: pending.cardName,
    target_stack_index: arrayIndex,
  };

  updateActionHint(`Casting ${pending.cardName} at ${item.card?.name || "spell"}...`);
  sendAction(actionBody)
    .then(() => {
      updateActionHint(`Cast ${pending.cardName}.`);
      clearPendingHandCast();
    })
    .catch((e) => {
      if (e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
        pendingAutoTap = { card: pending.card, cardName: pending.cardName, actionBody };
        renderActivationPrompt();
        return;
      }
      clearPendingHandCast();
      updateActionHint(e.message, true);
    });
}

function renderStack(stack) {
  _currentStack = stack || [];

  // The hold lasts until the held spell leaves the stack (resolves or is
  // countered) or the player clicks it again — taking actions keeps it.
  if (stackClickHold && getHeldStackArrayIndex() === null) {
    releaseStackClickHold("Priority hold released: the spell left the stack.");
  }

  // The canvas stack cascade is the only stack UI. While targeting a spell on
  // the stack (Counterspell, Fork), legal targets get a glow on the canvas.
  const choosingStackTarget = !!pendingCastTarget
    && (pendingCastTarget.targetKind === "stack" || pendingCastTarget.alsoStack);
  if (battlefieldCanvas) {
    battlefieldCanvas.stackTargetableIndices = choosingStackTarget
      ? new Set(_currentStack.map((item, i) => i).filter((i) => isStackItemValidCastTarget(_currentStack[i], i)))
      : null;
    battlefieldCanvas.needsRedraw = true;
  }

  _refreshStackHoldVisuals();
}

function renderCombatControls(state) {
  const summary = q("combatSummary");
  const actions = q("combatActions");
  const damagePanel = q("combatDamagePanel");
  if (!summary || !actions || !damagePanel) return;

  summary.classList.add("hidden");
  actions.classList.add("hidden");
  damagePanel.classList.add("hidden");
  actions.innerHTML = "";
  damagePanel.innerHTML = "";
  const combat = getCombatState(state);
  const inCombat = state?.current_turn_phase === "combat";
  // While the FFA attack-target picker owns the prompt panel, the declare
  // summary/Alpha Strike controls would just crowd it — keep them hidden.
  if (!inCombat || pendingAttackTarget) {
    return;
  }

  summary.classList.remove("hidden");
  actions.classList.remove("hidden");
  damagePanel.classList.remove("hidden");

  const attackers = getDisplayedAttackerLinks(state);
  const blockers = getDisplayedBlockerLinks(state);
  if (isCombatStep(state, "declare_attackers")) {
    summary.textContent = `Attackers: ${attackers.length}`;
  } else if (isCombatStep(state, "declare_blockers")) {
    summary.textContent = `Blockers: ${blockers.length}`;
  } else {
    summary.textContent = `Attackers: ${attackers.length} | Blockers: ${blockers.length}`;
  }

  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn) {
    const validAttackerIndices = getValidAttackerIndices(state);
    if (validAttackerIndices.length === 0) {
      return;
    }
    const prompt = document.createElement("div");
    prompt.className = "combat-summary";
    if (combat?.attackers_locked) {
      prompt.textContent = "Attackers are declared. Both players may cast spells or activate abilities before Next Phase.";
    } else {
      prompt.textContent = "Declare attackers: click creatures, or use Alpha Strike to toggle all valid attackers, then press OK.";
    }
    damagePanel.appendChild(prompt);

    if (combat?.attackers_locked) return;
    const alphaStrikeBtn = document.createElement("button");
    alphaStrikeBtn.type = "button";
    alphaStrikeBtn.id = "alphaStrikeBtn";
    alphaStrikeBtn.textContent = "Alpha Strike";
    alphaStrikeBtn.addEventListener("click", () => {
      const validAttackerIndices = getValidAttackerIndices(currentState);
      if (!validAttackerIndices.length) {
        updateActionHint("No valid attackers available for Alpha Strike.", true);
        return;
      }

      const allValidAlreadySelected = validAttackerIndices.every((idx) => combatAttackerDraft.includes(idx));
      if (allValidAlreadySelected) {
        combatAttackerDraft = combatAttackerDraft.filter((idx) => !validAttackerIndices.includes(idx));
        updateActionHint("Alpha Strike cleared all valid attackers.");
      } else {
        combatAttackerDraft = [...new Set([...combatAttackerDraft, ...validAttackerIndices])].sort((a, b) => a - b);
        updateActionHint(`Alpha Strike selected ${validAttackerIndices.length} valid attacker(s).`);
      }

      renderBoard(currentState);
    });
    actions.appendChild(alphaStrikeBtn);

    // CR 702.22c: if the selected attackers can form a legal band (≥1 with banding,
    // ≤1 without), let the player group them so they attack — and are blocked — as
    // a single band.
    if (!selectedAttackersCanBand(state)) combatBandDraft = false;
    if (selectedAttackersCanBand(state)) {
      const bandBtn = document.createElement("button");
      bandBtn.type = "button";
      bandBtn.id = "formBandBtn";
      bandBtn.className = combatBandDraft ? "active" : "";
      bandBtn.textContent = combatBandDraft ? "Banding: ON" : "Attack as Band";
      bandBtn.title = "Group the selected attackers into one band (CR 702.22).";
      bandBtn.addEventListener("click", () => {
        combatBandDraft = !combatBandDraft;
        updateActionHint(
          combatBandDraft
            ? "Selected attackers will attack as a band."
            : "Band grouping cleared.",
        );
        renderBoard(currentState);
      });
      actions.appendChild(bandBtn);
    }
  }

  if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index) {
    const validBlockerAssignments = getValidBlockerAssignments(state);
    if (validBlockerAssignments.length === 0) {
      return;
    }
    const prompt = document.createElement("div");
    prompt.className = "combat-summary";
    if (combat?.blockers_locked) {
      prompt.textContent = "Blockers are declared. Both players may cast spells or activate abilities before combat damage.";
    } else {
      prompt.textContent = "Declare blockers: drag from each blocker to an attacking creature, then press OK.";
    }
    damagePanel.appendChild(prompt);

  }

  // CR 702.22j: the defending player splits the damage of each attacker blocked by
  // one of their banding creatures, before the active player resolves.
  if (
    isCombatStep(state, "combat_damage") &&
    state.banding_assignment &&
    seat === state.banding_assignment.defender_seat &&
    !combat?.damage_resolved
  ) {
    const groups = getDefenderBandingGroups(state);
    if (groups.length > 0) {
      const prompt = document.createElement("div");
      prompt.className = "combat-summary";
      prompt.textContent =
        "A banding creature is blocking — you choose how each banded attacker's damage is split.";
      damagePanel.appendChild(prompt);

      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.textContent = "Assign Banding Damage";
      openBtn.addEventListener("click", () => openBandingDamageDialog(state));
      actions.appendChild(openBtn);

      const key = `banding:${getCombatDraftStepKey(state)}`;
      if (combatDamageDialogKey !== key) {
        combatDamageDialogKey = key;
        openBandingDamageDialog(state);
      }
      return;
    }
  }

  // CR 510.1d: the defending player divides a multi-blocking creature's damage
  // (Two-Headed Giant of Foriys) before combat damage resolves.
  if (
    isCombatStep(state, "combat_damage") &&
    seat === combat?.defending_player_index &&
    getMultiblockInfo(state) &&
    !combat?.damage_resolved
  ) {
    const prompt = document.createElement("div");
    prompt.className = "combat-summary";
    prompt.textContent =
      "Your creature is blocking multiple attackers — choose how its damage is divided.";
    damagePanel.appendChild(prompt);

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.textContent = "Divide Blocker Damage";
    openBtn.addEventListener("click", () => openMultiblockDamageDialog(state));
    actions.appendChild(openBtn);

    const key = `multiblock:${getCombatDraftStepKey(state)}`;
    if (combatDamageDialogKey !== key) {
      combatDamageDialogKey = key;
      openMultiblockDamageDialog(state);
    }
    return;
  }

  // CR 702.22k: a creature is blocking the active player's band — they choose which
  // band member it damages, before the normal attacker assignment.
  if (
    isCombatStep(state, "combat_damage") &&
    seat === state.current_turn &&
    getBandBlockerInfo(state) &&
    !combat?.damage_resolved
  ) {
    const prompt = document.createElement("div");
    prompt.className = "combat-summary";
    prompt.textContent =
      "A creature is blocking your band — choose which creature in the band it damages.";
    damagePanel.appendChild(prompt);

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.textContent = "Assign Band Blocker Damage";
    openBtn.addEventListener("click", () => openBandBlockerDialog(state));
    actions.appendChild(openBtn);

    const key = `bandblock:${getCombatDraftStepKey(state)}`;
    if (combatDamageDialogKey !== key) {
      combatDamageDialogKey = key;
      openBandBlockerDialog(state);
    }
    return;
  }

  if (isCombatStep(state, "combat_damage") && seat === state.current_turn && !combat?.damage_resolved) {
    // Manual assignment is only needed when an attacker is blocked by 2+ creatures,
    // excluding those a banding blocker hands to the defender (CR 702.22j).
    const groups = getAttackerAssignGroups(state);
    if (groups.length === 0) return;

    const prompt = document.createElement("div");
    prompt.className = "combat-summary";
    prompt.textContent = "An attacker is blocked by multiple creatures. Open the dialog to split its damage.";
    damagePanel.appendChild(prompt);

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.textContent = "Assign Combat Damage";
    openBtn.addEventListener("click", () => openCombatDamageDialog(state));
    actions.appendChild(openBtn);

    // Auto-open the dialog the first time we reach this assignment for this step.
    const key = getCombatDraftStepKey(state);
    if (combatDamageDialogKey !== key) {
      combatDamageDialogKey = key;
      openCombatDamageDialog(state);
    }
  }
}

// Collect attackers blocked by 2+ creatures, with the card data and per-blocker
// lethal thresholds needed to drive the manual damage-assignment dialog. Mirrors
// the engine's view: attacker on the active player's battlefield, blockers on the
// defender's, blockers processed in ascending (declared) index order.
function getMultiBlockedAttackerGroups(state = currentState) {
  const combat = getCombatState(state);
  if (!combat) return [];
  const attackerSeat = state.current_turn;
  const defenderSeat = Number.isInteger(combat.defending_player_index)
    ? combat.defending_player_index
    : 1 - attackerSeat;
  const attackerBattlefield = state.players?.[attackerSeat]?.battlefield || [];
  const defenderBattlefield = state.players?.[defenderSeat]?.battlefield || [];

  const byAttacker = new Map();
  for (const pair of combat.blockers || []) {
    const a = Number(pair.attacker_index);
    if (!byAttacker.has(a)) byAttacker.set(a, []);
    byAttacker.get(a).push(Number(pair.blocker_index));
  }

  const groups = [];
  for (const [attackerIdx, blockerIndices] of byAttacker) {
    if (blockerIndices.length < 2) continue;
    const attackerCard = attackerBattlefield[attackerIdx];
    if (!attackerCard) continue;
    const deathtouch = cardHasKeyword(attackerCard, "deathtouch");
    const trample = cardHasKeyword(attackerCard, "trample");
    const blockers = blockerIndices
      .slice()
      .sort((a, b) => a - b)
      .map((blockerIdx) => {
        const card = defenderBattlefield[blockerIdx];
        let lethal = Math.max(0, (Number(card?.toughness) || 0) - (Number(card?.damage_marked) || 0));
        if (deathtouch && lethal > 0) lethal = 1;
        return { blockerIdx, card, lethal };
      })
      .filter((b) => b.card);
    if (blockers.length < 2) continue;
    groups.push({
      attackerIdx,
      attackerCard,
      power: Math.max(0, Number(attackerCard.power) || 0),
      deathtouch,
      trample,
      blockers,
    });
  }
  groups.sort((a, b) => a.attackerIdx - b.attackerIdx);
  return groups;
}

// Fill combatDamageDraft with the engine's default assignment: lethal to each
// blocker in declared order while power remains, then dump any leftover onto the
// last blocker that received lethal (trampling attackers leave the remainder for
// the player, so they don't get the leftover here).
function autoAssignCombatDamage(groups) {
  for (const group of groups) {
    const perBlocker = {};
    let powerLeft = group.power;
    let lastLethalIdx = null;
    for (const { blockerIdx, lethal } of group.blockers) {
      const give = Math.min(powerLeft, lethal);
      perBlocker[blockerIdx] = give;
      powerLeft -= give;
      if (give > 0 && give >= lethal) lastLethalIdx = blockerIdx;
    }
    if (powerLeft > 0 && !group.trample && lastLethalIdx !== null) {
      perBlocker[lastLethalIdx] += powerLeft;
    }
    combatDamageDraft[group.attackerIdx] = perBlocker;
  }
}

// Validate one attacker's assignment against the engine's rules so we can guide
// the player before they submit. CR 510.1c: the attacker assigns ALL its combat
// damage, divided among its blockers however the assigning player chooses (there
// is no lethal-in-order requirement in the current rules), so the total must
// equal its power. A trampler may assign less to the blockers — the remainder
// tramples through to the player — but only once every blocker is assigned at
// least lethal damage (CR 702.19e). The same totals apply in "banding" mode,
// where the defender divides the damage instead (CR 702.22j).
function validateCombatDamageGroup(group, mode = combatDamageDialogMode) {
  const draft = combatDamageDraft[group.attackerIdx] || {};
  let total = 0;
  let underLethal = false;
  for (const { blockerIdx, lethal } of group.blockers) {
    const value = Math.max(0, Number(draft[blockerIdx]) || 0);
    total += value;
    if (value < lethal) underLethal = true;
  }
  let violation = null;
  if (total > group.power) {
    violation = "Assigned damage exceeds the attacker's power.";
  } else if (total < group.power) {
    if (!group.trample) {
      violation = `Assign all ${group.power} damage among the blockers.`;
    } else if (underLethal) {
      violation = "Trample: assign lethal to every blocker before letting damage through.";
    }
  }
  return { total, violation, valid: !violation };
}

function closeCombatDamageDialog() {
  const modal = q("combatDamageModal");
  if (modal) modal.classList.add("hidden");
}

// CR 702.22k: the active player chooses which band member each creature blocking
// their band damages. Surfaced to the active player as state.band_blocker_assignment.
function getBandBlockerInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.band_blocker_assignment;
  if (!info || !Array.isArray(info.blockers) || info.blockers.length === 0) return null;
  if (seat !== info.attacker_seat) return null;
  return info;
}

function openBandBlockerDialog(state = currentState) {
  const info = getBandBlockerInfo(state);
  const modal = q("combatDamageModal");
  if (!info || !modal) {
    closeCombatDamageDialog();
    return;
  }
  const combat = getCombatState(state);
  const attackerBf = state.players?.[state.current_turn]?.battlefield || [];
  const defenderBf = state.players?.[combat?.defending_player_index]?.battlefield || [];

  // Default: the blocker's full power on the first band member it blocks (the
  // engine's default). Draft maps blocker_idx -> {member_idx: damage} so the
  // attacking player can divide the damage freely (CR 702.22j/k).
  for (const b of info.blockers) {
    if (!combatBandBlockerDraft[b.blocker_idx] || typeof combatBandBlockerDraft[b.blocker_idx] !== "object") {
      const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
      const split = {};
      b.member_indices.forEach((m, i) => { split[m] = i === 0 ? power : 0; });
      combatBandBlockerDraft[b.blocker_idx] = split;
    }
  }

  const titleEl = q("combatDamageTitle");
  const subtitleEl = document.querySelector("#combatDamageModal .modal-subtitle");
  if (titleEl) titleEl.textContent = "Assign Band Blocker Damage";
  if (subtitleEl) {
    subtitleEl.textContent =
      "A creature is blocking your band, so you (the attacking player) choose how " +
      "its combat damage is divided among the band (CR 702.22j).";
  }

  const cardThumb = (card, sub) => {
    const el = document.createElement("div");
    el.className = "cda-card";
    const pt = `${Number(card?.power) || 0}/${Number(card?.toughness) || 0}`;
    const art = card?.image_uri
      ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name || "")}" loading="lazy" />`
      : `<div class="cda-card-placeholder">${escapeHtml(card?.name || "")}</div>`;
    el.innerHTML =
      `${art}<div class="cda-card-name">${escapeHtml(card?.name || "")}</div>` +
      `<div class="cda-card-pt">${pt}</div>` +
      (sub ? `<div class="cda-card-sub">${escapeHtml(sub)}</div>` : "");
    return el;
  };

  const render = () => {
    const body = q("combatDamageDialogBody");
    if (!body) return;
    body.innerHTML = "";
    for (const b of info.blockers) {
      const blockerCard = defenderBf[b.blocker_idx];
      const section = document.createElement("div");
      section.className = "cda-attacker";

      const left = document.createElement("div");
      left.className = "cda-attacker-side";
      left.appendChild(cardThumb(blockerCard, `deals ${Number(blockerCard?.power) || 0}`));
      section.appendChild(left);

      const arrow = document.createElement("div");
      arrow.className = "cda-arrow";
      arrow.textContent = "→";
      section.appendChild(arrow);

      const power = Number(blockerCard?.power) || 0;
      const split = combatBandBlockerDraft[b.blocker_idx] || {};
      const assigned = b.member_indices.reduce((sum, m) => sum + (Number(split[m]) || 0), 0);

      const targets = document.createElement("div");
      targets.className = "cda-blockers";
      for (const m of b.member_indices) {
        const memberCard = attackerBf[m];
        const cell = document.createElement("div");
        cell.className = "cda-target-btn" + ((Number(split[m]) || 0) > 0 ? " selected" : "");
        cell.appendChild(cardThumb(memberCard));
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.max = String(power);
        input.value = String(Number(split[m]) || 0);
        input.className = "cda-input";
        input.addEventListener("change", () => {
          const v = Math.max(0, Math.min(power, Number(input.value) || 0));
          combatBandBlockerDraft[b.blocker_idx] = { ...split, [m]: v };
          render();
        });
        cell.appendChild(input);
        targets.appendChild(cell);
      }
      section.appendChild(targets);

      const totalNote = document.createElement("div");
      totalNote.className = "cda-card-sub";
      totalNote.textContent = `Assigned ${assigned} of ${power}`;
      // CR 510.1c: the blocker assigns ALL its combat damage — flag any total
      // that isn't exactly its power.
      if (assigned !== power) totalNote.style.color = "#e16d70";
      section.appendChild(totalNote);
      body.appendChild(section);
    }
  };

  render();
  modal.classList.remove("hidden");

  const autoBtn = q("combatDamageAutoBtn");
  if (autoBtn) {
    autoBtn.onclick = () => {
      for (const b of info.blockers) {
        const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
        const split = {};
        b.member_indices.forEach((m, i) => { split[m] = i === 0 ? power : 0; });
        combatBandBlockerDraft[b.blocker_idx] = split;
      }
      render();
    };
  }
  const confirmBtn = q("combatDamageConfirmBtn");
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      const blockerDamageSplit = {};
      for (const b of info.blockers) {
        const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
        const split = combatBandBlockerDraft[b.blocker_idx] || {};
        const total = b.member_indices.reduce((sum, m) => sum + (Number(split[m]) || 0), 0);
        if (total !== power) {
          updateActionHint(`Assign all of the blocker's damage (${total} of ${power} assigned).`, true);
          return;
        }
        blockerDamageSplit[b.blocker_idx] = {};
        for (const m of b.member_indices) blockerDamageSplit[b.blocker_idx][m] = Number(split[m]) || 0;
      }
      try {
        confirmBtn.disabled = true;
        await sendAction({ seat, action: "assign_combat_damage", blocker_damage_split: blockerDamageSplit });
        updateActionHint("Band blocker damage assigned.");
        combatBandBlockerDraft = {};
        closeCombatDamageDialog();
      } catch (e) {
        updateActionHint(e.message, true);
      } finally {
        confirmBtn.disabled = false;
      }
    };
  }
}

// CR 510.1d: the defending player divides a multi-blocking creature's combat
// damage among the attackers it blocks (Two-Headed Giant of Foriys). Surfaced to
// the defender as state.multiblock_blocker_assignment.
function getMultiblockInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.multiblock_blocker_assignment;
  if (!info || !Array.isArray(info.blockers) || info.blockers.length === 0) return null;
  if (seat !== info.defender_seat) return null;
  return info;
}

function openMultiblockDamageDialog(state = currentState) {
  const info = getMultiblockInfo(state);
  const modal = q("combatDamageModal");
  if (!info || !modal) {
    closeCombatDamageDialog();
    return;
  }
  const attackerBf = state.players?.[state.current_turn]?.battlefield || [];
  const defenderBf = state.players?.[info.defender_seat]?.battlefield || [];

  // Default: the blocker's full power on the first attacker it blocks (the
  // engine's default). Draft maps blocker_idx -> {attacker_idx: damage}.
  for (const b of info.blockers) {
    if (!combatMultiblockDraft[b.blocker_idx] || typeof combatMultiblockDraft[b.blocker_idx] !== "object") {
      const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
      const split = {};
      b.attacker_indices.forEach((a, i) => { split[a] = i === 0 ? power : 0; });
      combatMultiblockDraft[b.blocker_idx] = split;
    }
  }

  const titleEl = q("combatDamageTitle");
  const subtitleEl = document.querySelector("#combatDamageModal .modal-subtitle");
  if (titleEl) titleEl.textContent = "Divide Blocker Damage";
  if (subtitleEl) {
    subtitleEl.textContent =
      "Your creature is blocking more than one attacker, so you choose how " +
      "its combat damage is divided among them (CR 510.1d).";
  }

  const cardThumb = (card, sub) => {
    const el = document.createElement("div");
    el.className = "cda-card";
    const pt = `${Number(card?.power) || 0}/${Number(card?.toughness) || 0}`;
    const art = card?.image_uri
      ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name || "")}" loading="lazy" />`
      : `<div class="cda-card-placeholder">${escapeHtml(card?.name || "")}</div>`;
    el.innerHTML =
      `${art}<div class="cda-card-name">${escapeHtml(card?.name || "")}</div>` +
      `<div class="cda-card-pt">${pt}</div>` +
      (sub ? `<div class="cda-card-sub">${escapeHtml(sub)}</div>` : "");
    return el;
  };

  const render = () => {
    const body = q("combatDamageDialogBody");
    if (!body) return;
    body.innerHTML = "";
    for (const b of info.blockers) {
      const blockerCard = defenderBf[b.blocker_idx];
      const section = document.createElement("div");
      section.className = "cda-attacker";

      const left = document.createElement("div");
      left.className = "cda-attacker-side";
      left.appendChild(cardThumb(blockerCard, `deals ${Number(blockerCard?.power) || 0}`));
      section.appendChild(left);

      const arrow = document.createElement("div");
      arrow.className = "cda-arrow";
      arrow.textContent = "→";
      section.appendChild(arrow);

      const power = Number(blockerCard?.power) || 0;
      const split = combatMultiblockDraft[b.blocker_idx] || {};
      const assigned = b.attacker_indices.reduce((sum, a) => sum + (Number(split[a]) || 0), 0);

      const targets = document.createElement("div");
      targets.className = "cda-blockers";
      for (const a of b.attacker_indices) {
        const attackerCard = attackerBf[a];
        const cell = document.createElement("div");
        cell.className = "cda-target-btn" + ((Number(split[a]) || 0) > 0 ? " selected" : "");
        cell.appendChild(cardThumb(attackerCard));
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.max = String(power);
        input.value = String(Number(split[a]) || 0);
        input.className = "cda-input";
        input.addEventListener("change", () => {
          const v = Math.max(0, Math.min(power, Number(input.value) || 0));
          combatMultiblockDraft[b.blocker_idx] = { ...split, [a]: v };
          render();
        });
        cell.appendChild(input);
        targets.appendChild(cell);
      }
      section.appendChild(targets);

      const totalNote = document.createElement("div");
      totalNote.className = "cda-card-sub";
      totalNote.textContent = `Assigned ${assigned} of ${power}`;
      // CR 510.1d: the blocker assigns ALL its combat damage — flag any total
      // that isn't exactly its power.
      if (assigned !== power) totalNote.style.color = "#e16d70";
      section.appendChild(totalNote);
      body.appendChild(section);
    }
  };

  render();
  modal.classList.remove("hidden");

  const autoBtn = q("combatDamageAutoBtn");
  if (autoBtn) {
    autoBtn.onclick = () => {
      for (const b of info.blockers) {
        const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
        const split = {};
        b.attacker_indices.forEach((a, i) => { split[a] = i === 0 ? power : 0; });
        combatMultiblockDraft[b.blocker_idx] = split;
      }
      render();
    };
  }
  const confirmBtn = q("combatDamageConfirmBtn");
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      const blockerDamageSplit = {};
      for (const b of info.blockers) {
        const power = Number(defenderBf[b.blocker_idx]?.power) || 0;
        const split = combatMultiblockDraft[b.blocker_idx] || {};
        const total = b.attacker_indices.reduce((sum, a) => sum + (Number(split[a]) || 0), 0);
        if (total !== power) {
          updateActionHint(`Assign all of the blocker's damage (${total} of ${power} assigned).`, true);
          return;
        }
        blockerDamageSplit[b.blocker_idx] = {};
        for (const a of b.attacker_indices) blockerDamageSplit[b.blocker_idx][a] = Number(split[a]) || 0;
      }
      try {
        confirmBtn.disabled = true;
        await sendAction({ seat, action: "assign_multiblock_damage", blocker_damage_split: blockerDamageSplit });
        updateActionHint("Blocker damage divided.");
        combatMultiblockDraft = {};
        closeCombatDamageDialog();
      } catch (e) {
        updateActionHint(e.message, true);
      } finally {
        confirmBtn.disabled = false;
      }
    };
  }
}

// Multi-blocked attackers the *active player* assigns (everything except those a
// banding blocker hands to the defender per CR 702.22j).
function getAttackerAssignGroups(state = currentState) {
  return getMultiBlockedAttackerGroups(state).filter(
    (g) => !attackerBlockedByBandingClient(state, g.attackerIdx),
  );
}

// Multi-blocked attackers the *defending player* assigns because at least one of
// their banding creatures is among the blockers (CR 702.22j).
function getDefenderBandingGroups(state = currentState) {
  return getMultiBlockedAttackerGroups(state).filter((g) =>
    attackerBlockedByBandingClient(state, g.attackerIdx),
  );
}

function openCombatDamageDialog(state = currentState) {
  openDamageDialog(state, "attacker");
}

function openBandingDamageDialog(state = currentState) {
  openDamageDialog(state, "banding");
}

// Shared assignment dialog. `mode` selects whose split this is — the active
// player's normal combat damage ("attacker") or the defending player's banding
// split ("banding") — which only changes the action that submits it.
function openDamageDialog(state = currentState, mode = "attacker") {
  const modal = q("combatDamageModal");
  if (!modal) return;
  combatDamageDialogMode = mode;
  const groups = mode === "banding" ? getDefenderBandingGroups(state) : getAttackerAssignGroups(state);
  if (groups.length === 0) {
    closeCombatDamageDialog();
    return;
  }

  // Seed any unassigned attacker with the sensible default distribution.
  const needsSeed = groups.filter((g) => !combatDamageDraft[g.attackerIdx]);
  if (needsSeed.length) autoAssignCombatDamage(needsSeed);

  renderCombatDamageDialogBody(groups, mode);
  modal.classList.remove("hidden");

  const autoBtn = q("combatDamageAutoBtn");
  if (autoBtn) {
    autoBtn.onclick = () => {
      autoAssignCombatDamage(groups);
      renderCombatDamageDialogBody(groups, mode);
    };
  }
  const confirmBtn = q("combatDamageConfirmBtn");
  if (confirmBtn) {
    confirmBtn.onclick = async () => {
      if (groups.some((g) => !validateCombatDamageGroup(g, mode).valid)) return;
      const assignment = {};
      for (const g of groups) assignment[g.attackerIdx] = combatDamageDraft[g.attackerIdx] || {};
      try {
        confirmBtn.disabled = true;
        if (mode === "banding") {
          await sendAction({ seat, action: "assign_banding_damage", banding_damage: assignment });
          updateActionHint("Banding combat damage assigned.");
        } else {
          await sendAction({ seat, action: "assign_combat_damage", attacker_damage: assignment });
          updateActionHint("Combat damage resolved.");
        }
        closeCombatDamageDialog();
      } catch (e) {
        updateActionHint(e.message, true);
      } finally {
        confirmBtn.disabled = false;
      }
    };
  }
}

// Build the per-attacker assignment UI. Rebuilt on every change so totals and
// validity stay in sync with combatDamageDraft.
function renderCombatDamageDialogBody(groups, mode = combatDamageDialogMode) {
  const body = q("combatDamageDialogBody");
  if (!body) return;
  body.innerHTML = "";

  // Banding (CR 702.22j): the defending player is the one splitting the damage,
  // so retitle the dialog to make that clear.
  const titleEl = q("combatDamageTitle");
  const subtitleEl = document.querySelector("#combatDamageModal .modal-subtitle");
  if (titleEl) {
    titleEl.textContent = mode === "banding" ? "Assign Banding Damage" : "Assign Combat Damage";
  }
  if (subtitleEl) {
    subtitleEl.textContent =
      mode === "banding"
        ? "A creature with banding is blocking, so you (the defender) choose how each attacker's damage is split among its blockers (CR 702.22j)."
        : "Distribute each attacker's power among the creatures blocking it. The total assigned to a blocker's row cannot exceed the attacker's damage.";
  }

  const cardThumb = (card, sub) => {
    const el = document.createElement("div");
    el.className = "cda-card";
    const pt = `${Number(card?.power) || 0}/${Number(card?.toughness) || 0}`;
    const art = card?.image_uri
      ? `<img src="${escapeHtml(card.image_uri)}" alt="${escapeHtml(card.name || "")}" loading="lazy" />`
      : `<div class="cda-card-placeholder">${escapeHtml(card?.name || "")}</div>`;
    el.innerHTML =
      `${art}` +
      `<div class="cda-card-name">${escapeHtml(card?.name || "")}</div>` +
      `<div class="cda-card-pt">${pt}</div>` +
      (sub ? `<div class="cda-card-sub">${escapeHtml(sub)}</div>` : "");
    return el;
  };

  let allValid = true;
  for (const group of groups) {
    const result = validateCombatDamageGroup(group, mode);
    if (!result.valid) allValid = false;

    const section = document.createElement("div");
    section.className = "cda-attacker";

    // Attacker side.
    const attackerSide = document.createElement("div");
    attackerSide.className = "cda-attacker-side";
    const tags = [];
    if (group.deathtouch) tags.push("deathtouch");
    if (group.trample) tags.push("trample");
    attackerSide.appendChild(cardThumb(group.attackerCard, tags.join(", ")));
    const dealing = document.createElement("div");
    dealing.className = "cda-dealing";
    dealing.textContent = `${group.power} damage to assign`;
    attackerSide.appendChild(dealing);
    section.appendChild(attackerSide);

    const arrow = document.createElement("div");
    arrow.className = "cda-arrow";
    arrow.textContent = "→";
    section.appendChild(arrow);

    // Blockers side.
    const blockersSide = document.createElement("div");
    blockersSide.className = "cda-blockers";
    for (const { blockerIdx, card, lethal } of group.blockers) {
      const col = document.createElement("div");
      col.className = "cda-blocker";
      col.appendChild(cardThumb(card, `lethal: ${lethal}`));

      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.max = String(group.power);
      input.className = "cda-input";
      input.value = String(Math.max(0, Number(combatDamageDraft?.[group.attackerIdx]?.[blockerIdx]) || 0));
      input.addEventListener("input", () => {
        if (!combatDamageDraft[group.attackerIdx]) combatDamageDraft[group.attackerIdx] = {};
        combatDamageDraft[group.attackerIdx][blockerIdx] = Math.max(0, Math.floor(Number(input.value) || 0));
        renderCombatDamageDialogBody(groups, mode);
      });
      col.appendChild(input);
      blockersSide.appendChild(col);
    }
    section.appendChild(blockersSide);

    // Running total + validation message.
    const footer = document.createElement("div");
    footer.className = "cda-attacker-footer";
    const totalEl = document.createElement("span");
    totalEl.className = "cda-total" + (result.valid ? "" : " cda-total-over");
    totalEl.textContent = `Assigned ${result.total} / ${group.power}`;
    footer.appendChild(totalEl);
    if (result.violation) {
      const warn = document.createElement("span");
      warn.className = "cda-warning";
      warn.textContent = result.violation;
      footer.appendChild(warn);
    }
    section.appendChild(footer);

    body.appendChild(section);
  }

  const confirmBtn = q("combatDamageConfirmBtn");
  if (confirmBtn) confirmBtn.disabled = !allValid;
}

function renderLog(state) {
  const logRoot = q("logText");
  logRoot.innerHTML = "";
  const entries = state.log || [];
  if (entries.length === 0) {
    logRoot.textContent = "No events yet.";
    return;
  }

  const header = document.createElement("div");
  header.className = "log-item";
  header.innerHTML = renderSymbolsInline(`Turn ${state.turn_number || "-"} | Phase ${getPhaseDisplayLabel(state)}`);
  logRoot.appendChild(header);

  entries.forEach((entry, idx) => {
    const item = document.createElement("div");
    item.className = "log-item";
    item.innerHTML = renderSymbolsInline(`${idx + 1}. ${entry}`);
    logRoot.appendChild(item);
  });

  const logTab = q("logTab");
  if (logTab) logTab.scrollTop = logTab.scrollHeight;
}

function showTurnAnnouncement(isSelfTurn, isExtraTurn = false, playerName = null) {
  const el = document.getElementById("turnAnnouncement");
  if (!el) return;
  el.classList.remove("announcing");
  // Force reflow so removing+adding the class restarts the animation
  void el.offsetWidth;
  const possessive = playerName ? `${escapeHtml(playerName)}'s` : "Opponent's";
  const label = isSelfTurn
    ? (isExtraTurn ? "Your Extra Turn" : "Your Turn")
    : (isExtraTurn ? `${possessive} Extra Turn` : `${possessive} Turn`);
  const color = isSelfTurn ? "#5dde6a" : "#e16d70";
  el.innerHTML = `<span style="color:${color};">${label}</span>`;
  el.classList.add("announcing");
  el.addEventListener("animationend", () => el.classList.remove("announcing"), { once: true });
}

function showMatchRestartAnnouncement() {
  // Reuse the center turn-announcement banner/animation to flash "Match
  // Restarting" to every seat when someone restarts the match.
  const el = document.getElementById("turnAnnouncement");
  if (!el) return;
  el.classList.remove("announcing");
  void el.offsetWidth; // force reflow so the animation restarts
  el.innerHTML = `<span style="color:#7ec4ff;">Match Restarting</span>`;
  el.classList.add("announcing");
  el.addEventListener("animationend", () => el.classList.remove("announcing"), { once: true });
  updateActionHint("Match is restarting — resetting the board for a new game.");
}

function renderGameOverOverlay(state) {
  const overlay = q("gameOverOverlay");
  const textEl = q("gameOverText");
  if (!overlay || !textEl) return;

  const w = state.winner;
  if (w === null || w === undefined) {
    overlay.classList.add("hidden");
    return;
  }

  overlay.classList.remove("hidden");
  textEl.className = "game-over-text";
  if (w === -1) {
    textEl.textContent = "Draw";
    textEl.classList.add("draw");
  } else if (seat !== null && w === seat) {
    textEl.textContent = "Victory";
    textEl.classList.add("victory");
  } else if (isFfaState(state)) {
    // FFA: the viewer may have been eliminated (and spectating) long before
    // this — name the last player standing rather than a bare "Defeat".
    textEl.textContent = `${state.players?.[w]?.name || `Seat ${w}`} Wins`;
    textEl.classList.add("defeat");
  } else {
    textEl.textContent = "Defeat";
    textEl.classList.add("defeat");
  }

  updateRematchButtons(state);
}

function updateRematchButtons(state) {
  const playBtn = q("playAgainBtn");
  if (!playBtn) return;

  const rematch = state.mode === "human_vs_human" ? state.rematch : null;
  if (rematch && rematch.you_requested) {
    // We've asked; waiting on the opponent to agree.
    playBtn.disabled = true;
    playBtn.textContent = "Waiting for opponent…";
  } else if (rematch && rematch.opponent_requested) {
    // The opponent already asked — one click accepts and starts the rematch.
    playBtn.disabled = false;
    playBtn.textContent = "Accept Rematch";
  } else {
    playBtn.disabled = false;
    playBtn.textContent = "Play Again";
  }
}

function manaPipsHtml(colors) {
  if (!colors || !colors.length) {
    return `<span class="mana-pip mana-pip--C" title="Colorless"></span>`;
  }
  return colors.map((c) => `<span class="mana-pip mana-pip--${c}"></span>`).join("");
}

// Multi-human lobby (networked human_vs_human or Free-For-All with an open
// human seat): a full-board overlay listing each seat's name/deck/colors as
// players join, with a Start Game button any joined player can enable once
// the roster is full. Driven by state.lobby (see _serialize_state in app.py).
function updateLobbyOverlay(state) {
  const overlay = q("lobbyOverlay");
  if (!overlay) return;
  const lobby = state?.lobby;
  if (!lobby || lobby.game_started) {
    overlay.classList.add("hidden");
    return;
  }
  overlay.classList.remove("hidden");
  const countEl = q("lobbyCount");
  if (countEl) countEl.textContent = `${lobby.joined_count}/${lobby.total_seats} in game`;
  const roster = q("lobbyRoster");
  if (roster) {
    roster.innerHTML = lobby.seats
      .map((s) => {
        if (!s.joined) {
          return `<div class="lobby-seat-row lobby-seat-row--open">Waiting for a player…</div>`;
        }
        return `<div class="lobby-seat-row">
          <span class="lobby-seat-name">${escapeHtml(s.name)}${s.is_ai ? " (AI)" : ""}</span>
          <span class="lobby-seat-deck">${escapeHtml(s.deck_name || "")}</span>
          <span class="lobby-mana-pips">${manaPipsHtml(s.colors)}</span>
        </div>`;
      })
      .join("");
  }
  const startBtn = q("lobbyStartBtn");
  if (startBtn) startBtn.disabled = lobby.open_seats.length > 0;
}

// Drop the gold player-targeting highlight from every FFA corner panel — the
// classic header pills are cleared by their fixed-id loops, but the corner
// pills would otherwise only re-sync on the next renderBoard.
function clearFfaTargetingHighlights() {
  document
    .querySelectorAll("#ffaOpponentPanels .targeting-valid")
    .forEach((el) => el.classList.remove("targeting-valid"));
}

// Free-For-All (3-4 player) only: a corner panel for every seat other than
// the viewer and the classic single-opponent header's (top-left) seat. Each
// panel mirrors the classic header — a name + life pill styled like
// .hand-fan-info plus a face-down hand fan — anchored to the screen corner
// matching that seat's battlefield quadrant (3 players: top-right; 4 players:
// bottom-right and top-right). The pill reuses the same click-to-target flow
// as the classic header (see the click listener wired onto
// #ffaOpponentPanels below) so spells/abilities targeting "any player" can be
// aimed at these seats too. The panel skeleton persists across renders (only
// text/fans update) so the life-pill flash animation isn't cut short.
function renderFfaOpponentPanels(state, viewerSeat, oppSeat) {
  const container = q("ffaOpponentPanels");
  if (!container) return;
  const players = Array.isArray(state.players) ? state.players : [];
  const n = players.length;
  const isFfa = n > 2;
  container.classList.toggle("hidden", !isFfa);
  if (!isFfa) {
    container.innerHTML = "";
    delete container.dataset.layout;
    return;
  }
  const extraSeats = players.map((_, idx) => idx).filter((idx) => idx !== viewerSeat && idx !== oppSeat);
  const cornerFor = (idx) => {
    const r = (((idx - viewerSeat) % n) + n) % n;
    // Matches _quadrantFor in battlefield-canvas.js: with 3 players the only
    // extra seat is top-right; with 4, r=1 is bottom-right and r=3 top-right.
    return n === 4 && r === 1 ? "bottom-right" : "top-right";
  };
  const layoutKey = extraSeats.map((idx) => `${idx}:${cornerFor(idx)}`).join(",");
  if (container.dataset.layout !== layoutKey) {
    container.dataset.layout = layoutKey;
    container.innerHTML = extraSeats
      .map((idx) => {
        const corner = cornerFor(idx);
        const fanClasses =
          "hand-fan hand-fan--opponent" + (corner === "bottom-right" ? " hand-fan--bottom" : "");
        return `
      <div class="ffa-corner ffa-corner--${corner}">
        <div class="hand-fan-wrap">
          <div id="ffaHand_${idx}" class="${fanClasses}"></div>
          <div class="hand-fan-info hand-fan-info--corner ffa-opponent-panel" data-target-seat="${idx}">
            <h2 id="ffaName_${idx}"></h2>
            <div id="ffaLife_${idx}" class="life-pill" data-target-seat="${idx}">20</div>
          </div>
          <div id="ffaMana_${idx}" class="mana-row mana-row--ffa"></div>
        </div>
      </div>`;
      })
      .join("");
  }
  const validPlayerSeats = validPlayerTargetSeats(state);
  for (const idx of extraSeats) {
    const p = players[idx] || {};
    const nameEl = q(`ffaName_${idx}`);
    if (nameEl) {
      nameEl.textContent = (p.name || `Seat ${idx}`) + (p.lost ? " ☠" : "");
      nameEl.classList.toggle("opponent-turn-name", state.current_turn === idx);
    }
    renderLifePill(`ffaLife_${idx}`, idx, p.life);
    const isTargetable = !!(validPlayerSeats && validPlayerSeats.has(idx));
    const panel = container.querySelector(`.ffa-opponent-panel[data-target-seat="${idx}"]`);
    if (panel) {
      panel.classList.toggle("targeting-valid", isTargetable);
      panel.style.cursor = isTargetable ? "pointer" : "default";
    }
    q(`ffaLife_${idx}`)?.classList.toggle("targeting-valid", isTargetable);
    // Corner opponents' floating mana, mirroring the classic #oppMana column:
    // only non-zero orbs render (CSS), and the row hides entirely while empty.
    renderMana(`ffaMana_${idx}`, p.mana_pool, idx, p.restricted_mana);
    const manaTotal = Object.values(p.mana_pool || {}).reduce((sum, n) => sum + Number(n || 0), 0)
      + Object.values(p.restricted_mana || {}).reduce((sum, b) => sum + Object.values(b || {}).reduce((t, n) => t + Number(n || 0), 0), 0);
    q(`ffaMana_${idx}`)?.classList.toggle("hidden", manaTotal === 0 && !debugAddManaMode);
    const hand = Array.isArray(p.hand)
      ? p.hand
      : new Array(Number(p.hand_count || 0) || 0).fill("<hidden>");
    renderHandFan(`ffaHand_${idx}`, hand, { zoneKind: "hand", targetSeat: idx });
  }
}

function renderBoard(state) {
  renderGameOverOverlay(state);
  closePermanentMenuIfStale(state);
  // Eliminated in a still-running FFA: pin the spectator strip while the
  // remaining players finish the game (the game-over overlay replaces it).
  const spectatorBanner = q("spectatorBanner");
  if (spectatorBanner) {
    const spectating =
      isFfaState(state) && seat !== null && !!state.players?.[seat]?.lost && state.winner == null;
    spectatorBanner.classList.toggle("hidden", !spectating);
  }
  const viewerSeat = seat ?? 0;
  const oppSeat = classicOppSeat(state, viewerSeat);
  const me = state.players[viewerSeat];
  const opp = state.players[oppSeat];
  const combat = getCombatState(state);
  const playerCount = Array.isArray(state.players) ? state.players.length : 2;

  // Free-For-All layout classes: the classic opponent header only spans the
  // top-LEFT half (its seat's quadrant), and with 4 players the viewer's own
  // hand shifts into the bottom-left half to stay inside their quadrant.
  const boardShell = document.querySelector(".board-shell");
  boardShell?.classList.toggle("is-ffa", playerCount > 2);
  boardShell?.classList.toggle("is-ffa-4", playerCount >= 4);

  q("selfName").textContent = me.name;
  q("selfName").dataset.targetSeat = String(viewerSeat);
  renderLifePill("selfLife", viewerSeat, me.life);
  q("selfLife").dataset.targetSeat = String(viewerSeat);
  q("oppName").textContent = opp.name;
  q("oppName").dataset.targetSeat = String(oppSeat);
  renderLifePill("oppLife", oppSeat, opp.life);
  q("oppLife").dataset.targetSeat = String(oppSeat);
  renderPlayerShield("selfShield", me);
  renderPlayerShield("oppShield", opp);

  const isSelfTurn = state.current_turn === viewerSeat;
  const hasPriority = seat !== null && state.priority_player === seat;
  const canEndTurn = seat !== null && isSelfTurn && !isOpponentMidAction(state, viewerSeat);
  const pregameInfo = getPregameInfo(state);
  const isPregame = !!pregameInfo;
  const cleanupDiscard = getCleanupDiscardInfo(state);
  const requiresCleanupSelection = !!cleanupDiscard;
  const discardSelectInfo = getDiscardSelectInfo(state);
  const requiresDiscardSelection = !!discardSelectInfo;
  // A stale selection from a previous prompt would mis-index this one's hand.
  if (!requiresDiscardSelection && discardSelection.length) discardSelection = [];
  const mulliganBottomInfo = pregameInfo?.phase === "bottom_select" && pregameInfo.is_my_turn ? pregameInfo : null;
  const requiresMulliganBottomSelection = !!mulliganBottomInfo;
  // Balance's discard half: its permanents are picked on the board, its cards to
  // discard by clicking them in hand (the same picker as every other discard).
  const balanceSelectInfo = getBalanceSelectInfo(state);
  const requiresBalanceHandSelection = !!balanceSelectInfo && (balanceSelectInfo.cards_to_discard || 0) > 0;
  // As with discardSelection: a plan left over from a previous Balance would
  // mis-index this board and hand.
  if (!balanceSelectInfo && (balanceSelection.lands.length || balanceSelection.creatures.length || balanceSelection.hand.length)) {
    balanceSelection = { lands: [], creatures: [], hand: [] };
  }
  const hasBlockingPrompt = hasBlockingPromptForAutoPass(state);
  const hasCombatDeclarationPrompt = combatPromptNeedsConfirmation(state);
  const untapInfo = getUntapLandSelectionInfo(state);
  const selfHeader = document.querySelector(".self-header");
  const oppHeader = document.querySelector(".opponent-header");
  setDebugMenuEnabled(sessionId !== null && seat !== null, hasPriority);
  q("endTurnBtn").textContent = autoPassTurnEndEnabled ? "Cancel Auto-Pass" : (isSelfTurn ? "End Turn" : "Auto-Pass");
  q("endTurnBtn").disabled = autoPassTurnEndEnabled
    ? false
    : (isSelfTurn ? (!canEndTurn || hasBlockingPrompt) : (seat === null || hasBlockingPrompt));
  q("nextPhaseBtn").disabled = !hasPriority || hasBlockingPrompt || hasCombatDeclarationPrompt;
  q("undoBtn").disabled = sessionId === null;
  selfHeader?.classList.toggle("turn-zone-self", isSelfTurn);
  // Per-seat, not just "not my turn": in FFA the active player might be one
  // of the corner seats instead of the classic header's seat.
  oppHeader?.classList.toggle("turn-zone-opponent", state.current_turn === oppSeat);
  q("selfName").classList.toggle("active-turn-name", isSelfTurn);
  q("oppName").classList.toggle("opponent-turn-name", state.current_turn === oppSeat);

  renderHandFan("selfHand", me.hand, {
    draggable:
      !requiresCleanupSelection && !requiresDiscardSelection && !requiresBalanceHandSelection && !isPregame,
    dragKind: "hand",
    zoneKind: "hand",
    castOnClick: !isPregame,
    targetSeat: viewerSeat,
    cleanupSelectable: requiresCleanupSelection,
    mulliganBottomSelectable: requiresMulliganBottomSelection,
    discardSelectable: requiresDiscardSelection,
    balanceHandSelectable: requiresBalanceHandSelection,
    selectedHandIndices: requiresDiscardSelection
      ? discardSelection
      : requiresBalanceHandSelection
      ? balanceSelection.hand
      : cleanupDiscard?.selected_indices || mulliganBottomInfo?.selected_indices || [],
    playableHandIndices: me.playable_hand_indices || [],
  });
  renderHandFan("oppHand", opp.hand, { zoneKind: "hand", targetSeat: oppSeat });

  // Canvas battlefield update
  if (battlefieldCanvas) {
    battlefieldCanvas.updateState(state, viewerSeat);

    // "Waiting for <name>" above the top stack card while another player sits
    // on priority (e.g. holding it by hovering the stack on their client). The
    // canvas applies a short dwell before drawing so quick hand-offs stay quiet.
    const priorityHolder = Number.isInteger(state.priority_player) ? state.priority_player : null;
    const waitingOnStack =
      (state.stack || []).length > 0 &&
      priorityHolder !== null &&
      priorityHolder !== viewerSeat &&
      state.winner == null &&
      !getPregameInfo(state);
    battlefieldCanvas.setStackWaitingLabel(
      waitingOnStack ? state.players?.[priorityHolder]?.name || `Seat ${priorityHolder}` : null,
    );

    // Compute selected permanent keys for the canvas
    const selfSelectedKeys = [];
    const allSelectedKeys = [];
    if (untapInfo && seat === viewerSeat) {
      for (const idx of (untapInfo.selected_indices || [])) selfSelectedKeys.push(`${viewerSeat}-${idx}`);
    } else if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && seat === viewerSeat) {
      for (const idx of combatAttackerDraft) selfSelectedKeys.push(`${viewerSeat}-${idx}`);
    } else if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && seat === viewerSeat) {
      for (const idx of Object.keys(combatBlockerDraft)) selfSelectedKeys.push(`${viewerSeat}-${Number(idx)}`);
      // Highlight targeted attackers on opponent side (a blocker may target several).
      if (seat !== oppSeat) {
        for (const list of Object.values(combatBlockerDraft)) {
          for (const idx of (Array.isArray(list) ? list : [list])) allSelectedKeys.push(`${oppSeat}-${Number(idx)}`);
        }
      }
    }
    // A prompt that picks permanents off the board (forced sacrifice, Balance,
    // Drop of Honey, …) highlights every legal permanent as a target and marks
    // the ones picked so far as selected.
    const boardTargeting = activePromptBoardTargeting(state);
    let targetingKeys = getTargetablePermanentKeysForPrompt();
    if (boardTargeting && boardTargeting.permanentKeys.size) {
      targetingKeys = [...boardTargeting.permanentKeys];
      selfSelectedKeys.push(...boardTargeting.selectedKeys);
    }
    // Constrained untap selection (Winter Orb / Smoke): highlight every
    // candidate so the player can see exactly which permanents may be untapped.
    if (untapInfo && seat === viewerSeat) {
      targetingKeys = (untapInfo.candidate_indices || []).map((idx) => `${viewerSeat}-${idx}`);
    }
    battlefieldCanvas.setSelectedKeys([...selfSelectedKeys, ...allSelectedKeys]);

    battlefieldCanvas.setTargetingKeys(targetingKeys);

    // Pulse the canvas graveyard pile(s) holding legal targets while a spell
    // is choosing a graveyard card.
    battlefieldCanvas.zonePileTargeting =
      pendingCastTarget?.targetKind === "graveyard_creature"
        ? { kind: "graveyard", seats: [...new Set((pendingCastTarget.validGraveyard || []).map((t) => t.seat))] }
        : null;
  }

  // The reveal panel auto-opened for graveyard targeting closes itself as soon
  // as the prompt is over (target picked, cast cancelled, or state moved on).
  if (zoneRevealAutoOpened && pendingCastTarget?.targetKind !== "graveyard_creature") {
    closeZoneReveal();
  }

  // Highlight only the player faces that are legal right now — the seats the
  // backend marked as targets for the pending spell/ability, or the seats an
  // open player-choosing prompt offers.
  const validPlayerSeats = validPlayerTargetSeats(state);
  const highlightSelfFace = !!(validPlayerSeats && validPlayerSeats.has(viewerSeat));
  const highlightOppFace = !!(validPlayerSeats && validPlayerSeats.has(oppSeat));
  q("selfLife")?.classList.toggle("targeting-valid", highlightSelfFace);
  q("selfName")?.classList.toggle("targeting-valid", highlightSelfFace);
  q("oppLife")?.classList.toggle("targeting-valid", highlightOppFace);
  q("oppName")?.classList.toggle("targeting-valid", highlightOppFace);

  q("selfDeckCount").textContent = me.library_count;
  q("selfGraveCount").textContent = me.graveyard.length;
  q("selfExileCount").textContent = (me.exile || []).length;
  q("selfAnteCount").textContent = (me.ante || []).length;
  q("selfCommandCount").textContent = (me.command_zone || []).length;
  q("selfSideboardCount").textContent = (me.sideboard || []).length;
  q("oppDeckCount").textContent = opp.library_count;
  q("oppGraveCount").textContent = opp.graveyard.length;
  q("oppExileCount").textContent = (opp.exile || []).length;
  q("oppAnteCount").textContent = (opp.ante || []).length;
  q("oppCommandCount").textContent = (opp.command_zone || []).length;

  renderZoneCards("selfGraveyardCards", me.graveyard, { zoneSeat: seat, zoneKind: "graveyard" });
  renderZoneCards("selfExileCards", me.exile || [], { zoneSeat: seat, zoneKind: "exile" });
  renderZoneCards("selfAnteCards", me.ante || []);
  // The viewer's own command zone is clickable: a commander there is castable
  // by CR 903.8, and `castable_from_zones` says when.
  renderZoneCards("selfCommandCards", me.command_zone || [], { zoneSeat: seat, zoneKind: "command" });
  renderZoneCards("selfSideboardCards", me.sideboard || []);
  renderZoneCards("oppGraveyardCards", opp.graveyard, { zoneSeat: oppSeat, zoneKind: "graveyard" });
  renderZoneCards("oppExileCards", opp.exile || []);
  renderZoneCards("oppAnteCards", opp.ante || []);
  renderZoneCards("oppCommandCards", opp.command_zone || []);

  renderMana("selfMana", me.mana_pool, seat, me.restricted_mana);
  renderMana("oppMana", opp.mana_pool, oppSeat, opp.restricted_mana);
  // FFA hides the stage-right #oppMana column (CSS) — the classic opponent's
  // pool shows inline in their top-left header pill instead, like the corner
  // seats' rows, so every pool sits next to its owner.
  const oppManaHeader = q("oppManaHeader");
  if (oppManaHeader) {
    if (playerCount > 2) {
      renderMana("oppManaHeader", opp.mana_pool, oppSeat, opp.restricted_mana);
      const oppManaTotal = Object.values(opp.mana_pool || {}).reduce((sum, n) => sum + Number(n || 0), 0)
        + Object.values(opp.restricted_mana || {}).reduce((sum, b) => sum + Object.values(b || {}).reduce((t, n) => t + Number(n || 0), 0), 0);
      oppManaHeader.classList.toggle("hidden", oppManaTotal === 0 && !debugAddManaMode);
    } else {
      oppManaHeader.classList.add("hidden");
    }
  }
  renderPhaseRail(state);
  if (aiControlsEl) {
    aiControlsEl.classList.toggle("hidden", !shouldShowAiControls(state));
  }
  renderCombatControls(state);
  renderStack(state.stack);
  renderLog(state);
  renderCombatOverlay(state);
  renderFfaOpponentPanels(state, viewerSeat, oppSeat);
  q("rawState").textContent = JSON.stringify(state, null, 2);

  if (requiresCleanupSelection) {
    const remaining = Math.max(0, Number(cleanupDiscard.required_count || 0) - Number(cleanupDiscard.selected_count || 0));
    updateActionHint(`Cleanup: select ${remaining} more card(s) to discard.`);
  }
}

// Indices of cards present in prevHand that are no longer in nextHand, matched
// greedily by name so duplicates resolve correctly. Used to pick which hand
// slots should fly to the graveyard on discard.
function removedHandIndices(prevHand, nextHand) {
  const nextCounts = {};
  for (const c of nextHand || []) {
    const k = normalizeCardName(c) || "<hidden>";
    nextCounts[k] = (nextCounts[k] || 0) + 1;
  }
  const removed = [];
  (prevHand || []).forEach((c, i) => {
    const k = normalizeCardName(c) || "<hidden>";
    if (nextCounts[k] > 0) nextCounts[k] -= 1;
    else removed.push(i);
  });
  return removed;
}

// Animate a single card flying from a hand slot (source rect) to the graveyard
// pile (dest rect). Builds a throwaway fixed-position clone; removes it on finish.
function flyCardToGraveyard(source, dest, imageUri) {
  const fly = document.createElement("div");
  fly.className = "discard-fly card";
  fly.style.position = "fixed";
  fly.style.left = `${source.left}px`;
  fly.style.top = `${source.top}px`;
  fly.style.width = `${source.width}px`;
  fly.style.height = `${source.height}px`;
  fly.style.margin = "0";
  fly.style.zIndex = "9999";
  fly.style.pointerEvents = "none";

  const img = document.createElement("img");
  img.src = imageUri || "/images/card_back.webp";
  img.alt = "";
  fly.appendChild(img);
  document.body.appendChild(fly);

  const dx = dest.left + dest.width / 2 - (source.left + source.width / 2);
  const dy = dest.top + dest.height / 2 - (source.top + source.height / 2);
  const scale = dest.width > 0 ? Math.min(1, dest.width / source.width) : 0.55;

  const anim = fly.animate(
    [
      { transform: "translate(0px, 0px) scale(1) rotate(0deg)", opacity: 1 },
      { transform: `translate(${dx}px, ${dy}px) scale(${scale}) rotate(-8deg)`, opacity: 0.25 },
    ],
    { duration: 480, easing: "cubic-bezier(0.4, 0.1, 0.3, 1)", fill: "forwards" }
  );
  anim.onfinish = () => fly.remove();
  anim.oncancel = () => fly.remove();
}

// Detect cards discarded between two states and animate them flying from the
// hand into the owner's graveyard pile. Must be called BEFORE renderBoard
// re-renders the hand, so the outgoing hand slots are still in the DOM to read
// their on-screen positions from.
function animateDiscards(prev, next, viewerSeat) {
  if (!prev || !next || next.pregame) return;
  const prevLogLen = Array.isArray(prev.log) ? prev.log.length : 0;
  const newEntries = Array.isArray(next.log) ? next.log.slice(prevLogLen) : [];
  const discardEntries = newEntries
    .map((e) => String(e))
    .filter((e) => /discarded/i.test(e) && !/drew/i.test(e));
  if (discardEntries.length === 0) return;

  const seatCount = Array.isArray(next.players) ? next.players.length : 2;
  for (let s = 0; s < seatCount; s++) {
    const grew = (next.players?.[s]?.graveyard?.length ?? 0) - (prev.players?.[s]?.graveyard?.length ?? 0);
    if (grew <= 0) continue;
    const name = next.players?.[s]?.name;
    if (!name || !discardEntries.some((e) => e.includes(name))) continue;

    const isSelf = s === viewerSeat;
    const container = document.getElementById(handContainerIdForSeat(next, viewerSeat, s));
    const slotEls = container ? Array.from(container.querySelectorAll(".hand-fan-slot")) : [];
    if (slotEls.length === 0) continue;

    // Which slots fly: for our own hand we know exactly which cards left and can
    // show their art; the opponent's hand is hidden, so fly the last N backs.
    let picks;
    if (isSelf) {
      picks = removedHandIndices(prev.players?.[s]?.hand, next.players?.[s]?.hand)
        .filter((i) => i < slotEls.length)
        .slice(0, grew);
    } else {
      picks = [];
      for (let i = slotEls.length - 1; i >= 0 && picks.length < grew; i--) picks.unshift(i);
    }
    if (picks.length === 0) continue;

    const flights = picks.map((i) => {
      const el = slotEls[i].querySelector(".card") || slotEls[i];
      const card = isSelf ? prev.players?.[s]?.hand?.[i] : null;
      return { source: el.getBoundingClientRect(), imageUri: normalizeImageUri(card) };
    });
    // Destination is read after renderBoard has synced the canvas graveyard
    // pile, so the discard flies to the actual on-canvas pile position.
    requestAnimationFrame(() => {
      const pt = battlefieldCanvas?.getZonePileClientPoint(s, "graveyard");
      if (!pt) return;
      const dw = 44;
      const dh = 62;
      const dest = { left: pt.x - dw / 2, top: pt.y - dh / 2, width: dw, height: dh };
      flights.forEach((f, idx) => {
        setTimeout(() => flyCardToGraveyard(f.source, dest, f.imageUri), idx * 90);
      });
    });
  }
}

// ---------------------------------------------------------------------------
// Zone -> hand flights (the mirror of the discard flight above)
// ---------------------------------------------------------------------------

// Public zones a card can arrive in hand from, in the order an arriving card
// looks for the zone it left. The battlefield comes first because a bounce is
// both the commonest source and the only one with a per-card screen position;
// the library is not here because nothing names the card that left it — a draw
// is inferred from the deck count instead.
// The command zone is not here: nothing in the rules moves a card from it into
// a hand. CR 903.9b travels the other way, and CR 903.8's cast puts the
// commander on the stack.
const HAND_SOURCE_ZONES = ["battlefield", "graveyard", "exile", "ante", "sideboard"];
// A mass return (Evacuation-style) would otherwise fire one clone per card.
const HAND_FLIGHT_MAX = 8;
const HAND_FLIGHT_STAGGER_MS = 90;
const HAND_FLIGHT_MS = 460;

// Indices of cards present in nextHand that weren't in prevHand, matched
// greedily by name so duplicates resolve correctly — the arrival half of
// removedHandIndices, used to pick which hand slot a zone card flies into.
function addedHandIndices(prevHand, nextHand) {
  const prevCounts = {};
  for (const c of prevHand || []) {
    const k = normalizeCardName(c) || "<hidden>";
    prevCounts[k] = (prevCounts[k] || 0) + 1;
  }
  const added = [];
  (nextHand || []).forEach((c, i) => {
    const k = normalizeCardName(c) || "<hidden>";
    if (prevCounts[k] > 0) prevCounts[k] -= 1;
    else added.push(i);
  });
  return added;
}

// The same multiset diff over a public zone list: {index, card} for every entry
// of `before` that `after` no longer has. `index` is the position in `before`,
// which for a battlefield list is the permanent index the canvas keys by.
function removedZoneEntries(before, after) {
  const afterCounts = new Map();
  for (const c of after || []) {
    const k = normalizeCardName(c);
    afterCounts.set(k, (afterCounts.get(k) || 0) + 1);
  }
  const out = [];
  (before || []).forEach((card, index) => {
    const k = normalizeCardName(card);
    const n = afterCounts.get(k) || 0;
    if (n > 0) afterCounts.set(k, n - 1);
    else out.push({ index, card });
  });
  return out;
}

// Where on screen a card leaving `zone` departs from: the permanent's own slot
// for a bounce, the zone's canvas pile for everything else.
function handFlightSourcePoint(seat, zone, index) {
  if (!battlefieldCanvas) return null;
  if (zone === "battlefield") return battlefieldCanvas.getCardPageCenter(seat, index);
  return battlefieldCanvas.getZonePileClientPoint(seat, zone);
}

// Detect cards that arrived in a hand between two states and work out where
// each one flies from. Must be called BEFORE renderBoard, while the canvas
// still holds the previous state: the bounced permanent is still at its slot,
// and a graveyard the return just emptied still has a pile to leave from (a
// pile disappears the moment its zone is empty).
function collectHandArrivalFlights(prev, next, viewerSeat) {
  if (!prev || !next || next.pregame || prev.pregame) return [];
  const seatCount = Array.isArray(next.players) ? next.players.length : 0;
  if (!seatCount) return [];

  // What every seat lost from every public zone, so an arrival can be matched
  // to the card that left. Claimed entries are struck off, so two copies
  // arriving together take two different sources.
  const removals = [];
  for (let s = 0; s < seatCount; s++) {
    for (const zone of HAND_SOURCE_ZONES) {
      for (const gone of removedZoneEntries(prev.players?.[s]?.[zone], next.players?.[s]?.[zone])) {
        removals.push({ seat: s, zone, index: gone.index, card: gone.card });
      }
    }
  }
  const claimed = new Set();
  const takeRemoval = (match) => {
    const i = removals.findIndex((r, idx) => !claimed.has(idx) && match(r));
    if (i < 0) return null;
    claimed.add(i);
    return removals[i];
  };

  const flights = [];
  for (let s = 0; s < seatCount; s++) {
    const added = addedHandIndices(prev.players?.[s]?.hand, next.players?.[s]?.hand);
    if (added.length === 0) continue;
    // How many of this seat's arrivals the deck can account for. Only the count
    // is public, so this is all a draw ever leaves behind.
    let draws = Math.max(
      0,
      (prev.players?.[s]?.library_count ?? 0) - (next.players?.[s]?.library_count ?? 0)
    );

    for (const handIndex of added) {
      if (flights.length >= HAND_FLIGHT_MAX) break;
      const card = next.players?.[s]?.hand?.[handIndex];
      const name = normalizeCardName(card);
      // An opponent's hand is card backs, so a hidden arrival can only be
      // matched by seat: a draw first, then anything else that seat lost.
      const hidden = !name || name === "<hidden>";
      let source = null;
      if (hidden) {
        if (draws > 0) {
          draws -= 1;
          source = { seat: s, zone: "library", index: null, card: null };
        } else {
          source = takeRemoval((r) => r.seat === s);
        }
      } else {
        // Prefer this seat's own zones, then anyone else's: a card returns to
        // its OWNER's hand, so an opponent's board can be where it comes from.
        source =
          takeRemoval((r) => r.seat === s && normalizeCardName(r.card) === name) ||
          takeRemoval((r) => normalizeCardName(r.card) === name);
        if (!source && draws > 0) {
          draws -= 1;
          source = { seat: s, zone: "library", index: null, card: null };
        }
      }
      if (!source) continue;
      const point = handFlightSourcePoint(source.seat, source.zone, source.index);
      // Nothing on screen to leave from (a zone with no pile, a permanent the
      // canvas never placed): no flight, and the ordinary hand entrance plays.
      if (!point) continue;
      flights.push({
        seat: s,
        handIndex,
        point,
        // Face-up only where the viewer was already entitled to it: their own
        // arriving card, or a card that was public in the zone it left. A card
        // drawn into an opponent's hand flies as a back.
        imageUri: hidden ? normalizeImageUri(source.card) : normalizeImageUri(card),
      });
    }
  }
  return flights;
}

// The pose a flight has to land in: where the hand slot's card sits, how big it
// is, and how far the fan has rotated it. Size comes from the layout box and
// position from the rendered one — the slot is fanned and tilted, so its
// bounding rect is the box AROUND the card, a good third wider than the card.
// Landing on the bounding rect instead would visibly shrink the card at the
// moment the clone hands off to the real one.
function handSlotLandingPose(slot, cardEl) {
  const box = cardEl.getBoundingClientRect();
  const w = cardEl.offsetWidth || box.width;
  const h = cardEl.offsetHeight || box.height;
  return {
    cx: box.left + box.width / 2,
    cy: box.top + box.height / 2,
    w,
    h,
    angle: parseFloat(slot.style.getPropertyValue("--fan-angle")) || 0,
  };
}

// Animate one card flying from a screen point into its hand slot, then hand the
// slot back to the real card. Built in the landing pose and animated back from
// the source, so the last frame is exactly the card it replaces.
function flyCardToHand(point, pose, imageUri, onLand) {
  const fly = document.createElement("div");
  fly.className = "hand-fly card";
  fly.style.position = "fixed";
  fly.style.left = `${pose.cx - pose.w / 2}px`;
  fly.style.top = `${pose.cy - pose.h / 2}px`;
  fly.style.width = `${pose.w}px`;
  fly.style.height = `${pose.h}px`;
  fly.style.margin = "0";
  fly.style.zIndex = "9999";
  fly.style.pointerEvents = "none";

  const img = document.createElement("img");
  img.src = imageUri || "/images/card_back.webp";
  img.alt = "";
  fly.appendChild(img);
  document.body.appendChild(fly);

  const dx = point.x - pose.cx;
  const dy = point.y - pose.cy;
  // Zone piles and battlefield slots render much smaller than a hand card, so
  // the card grows over the flight instead of arriving the size it left at.
  const startScale = pose.w > 0 ? Math.min(1, 46 / pose.w) : 0.55;

  const anim = fly.animate(
    [
      {
        transform: `translate(${dx}px, ${dy}px) scale(${startScale}) rotate(${pose.angle + 14}deg)`,
        opacity: 0.35,
      },
      { transform: `translate(0px, 0px) scale(1) rotate(${pose.angle}deg)`, opacity: 1 },
    ],
    // The discard flight's easing, run the other way: the card pulls out of the
    // zone slowly enough to be read, then settles into the fan.
    { duration: HAND_FLIGHT_MS, easing: "cubic-bezier(0.4, 0.1, 0.3, 1)", fill: "forwards" }
  );
  const land = () => {
    onLand();
    fly.remove();
  };
  anim.onfinish = land;
  anim.oncancel = land;
}

// Hand slots whose card is currently mid-flight, as `fan#index`. Read by
// renderHandFan on every render, which is the point: the DOM element is not a
// place to keep this, because the renders that arrive during a flight replace
// it. Held here rather than on the flight so a slot re-rendered five times
// stays hidden all five.
const handSlotsInFlight = new Set();

function handFlightKey(containerId, handIndex) {
  return `${containerId}#${handIndex}`;
}

// The elements currently showing a seat's hand index, or null when the hand no
// longer has one (scrolled out of the viewer's carousel, or the card left again
// before its flight landed).
//
// Two of them, because createCardElement returns a WRAPPER — the card plus its
// mana-cost badge. `holdEl` is that wrapper, everything the slot shows and so
// everything a flight has to hide; hiding the `.card` alone leaves the cost
// badge hanging in an apparently empty slot. `cardEl` is the card face itself,
// which is what the landing pose is measured from.
function handSlotParts(containerId, handIndex) {
  const container = document.getElementById(containerId);
  const slot = container?.querySelector(`.hand-fan-slot[data-hand-index="${handIndex}"]`);
  if (!slot) return null;
  const holdEl = slot.firstElementChild || slot;
  return { slot, holdEl, cardEl: slot.querySelector(".card") || holdEl };
}

// Launch the collected flights. Must be called AFTER renderBoard: the slot each
// card lands on only exists once the hand has been re-rendered.
function playHandArrivalFlights(flights, state, viewerSeat) {
  if (!flights || flights.length === 0) return;
  flights.forEach((flight, i) => {
    const containerId = handContainerIdForSeat(state, viewerSeat, flight.seat);
    const found = handSlotParts(containerId, flight.handIndex);
    // Nothing on screen to land on (a hand scrolled out of its carousel window).
    if (!found) return;
    const key = handFlightKey(containerId, flight.handIndex);
    handSlotsInFlight.add(key);
    if (window.FX) FX.holdForFlight(found.holdEl);
    // Measured after the hold, which clears the entrance animation's first
    // frame — otherwise the flight would aim at a slot mid-tween.
    const pose = handSlotLandingPose(found.slot, found.cardEl);

    // Released against whatever element holds the slot when the flight lands,
    // never the one measured above: renders in between will have replaced it.
    const land = () => {
      if (!handSlotsInFlight.delete(key)) return;
      const current = handSlotParts(containerId, flight.handIndex);
      if (!current) return;
      if (window.FX) FX.releaseFlight(current.holdEl);
      else current.holdEl.style.opacity = "";
    };

    if (pose.w === 0 || pose.h === 0) {
      land();
      return;
    }
    const delay = i * HAND_FLIGHT_STAGGER_MS;
    setTimeout(() => flyCardToHand(flight.point, pose, flight.imageUri, land), delay);
    // A hold that outlived its flight would leave a card invisible in the hand,
    // which is a worse failure than a missed animation — so it always expires.
    setTimeout(land, delay + HAND_FLIGHT_MS + 500);
  });
}

function renderState(state, { skipStaleCheck = false } = {}) {
  // Discard stale responses: when a slow HTTP response arrives after a faster SSE+getState
  // has already applied newer state, log length is monotonically increasing so we can use
  // it as a version guard to avoid regressing currentState.
  // (skipStaleCheck is set for undo, which intentionally produces a shorter log.)
  const incomingLogLen = Array.isArray(state?.log) ? state.log.length : -1;
  const currentLogLen = Array.isArray(currentState?.log) ? currentState.log.length : -1;
  if (!skipStaleCheck && incomingLogLen < currentLogLen) return;
  const wasInPregame = !!currentState?.pregame;
  const prevStateForDiscard = currentState;

  if (autoPassTurnEndEnabled && seat === null) {
    autoPassTurnEndEnabled = false;
    autoPassTurnEndRequestedStateKey = "";
    autoPassMode = null;
  }

  if (autoPassTurnEndEnabled && autoPassMode === "self" && state.current_turn !== seat) {
    autoPassTurnEndEnabled = false;
    autoPassTurnEndRequestedStateKey = "";
    autoPassMode = null;
  }

  if (autoPassTurnEndEnabled && autoPassMode === "opponent" && state.current_turn === seat) {
    autoPassTurnEndEnabled = false;
    autoPassTurnEndRequestedStateKey = "";
    autoPassMode = null;
  }

  maybeTriggerCombatDamageFx(currentState, state);
  SFX.onStateChange(currentState, state, seat ?? 0);
  // Begin background music once the game is underway (idempotent per session).
  if (state && !state.pregame && !state.winner) MUSIC.start();
  currentState = state;
  syncCombatDrafts(state);
  if (!isCombatStep(state, "combat_damage") || getCombatState(state)?.damage_resolved) {
    combatDamageDraft = {};
    combatBandBlockerDraft = {};
    combatMultiblockDraft = {};
    combatDamageDialogKey = "";
    closeCombatDamageDialog();
  }
  const cleanupInfo = getCleanupDiscardInfo(state);
  const untapInfo = getUntapLandSelectionInfo(state);
  const upkeepPayInfo = getUpkeepPayInfo(state);
  const optionalTriggerInfo = getOptionalTriggerInfo(state);
  const islandSanctuaryPending = getIslandSanctuaryInfo(state);
  const searchLibraryInfo = getSearchLibraryInfo(state);
  const reorderLibraryInfo = getReorderLibraryInfo(state);
  if (cleanupInfo || untapInfo || upkeepPayInfo || optionalTriggerInfo || islandSanctuaryPending) {
    pendingActivation = null;
    pendingCastTarget = null;
    pendingCastX = null;
    clearPendingHandCast();
    pendingManaColor = null;
    pendingAbilityChoice = null;
    battlefieldCanvas?.hideManaFan();
  }
  if (sessionId !== null) {
    hideSetupPanel();
  }
  const viewerSeat = seat ?? 0;
  const isSelfTurn = state.current_turn === viewerSeat;
  const turnChanged =
    lastAnnouncedTurn !== state.current_turn || lastAnnouncedTurnNumber !== state.turn_number;
  if (turnChanged && !state.pregame && state.lobby?.game_started !== false) {
    lastAnnouncedTurn = state.current_turn;
    lastAnnouncedTurnNumber = state.turn_number;
    showTurnAnnouncement(
      isSelfTurn,
      state.current_turn_is_extra,
      state.players?.[state.current_turn]?.name || null,
    );
  }
  animateDiscards(prevStateForDiscard, state, viewerSeat);
  // Collected before the render (the source zone is still on the canvas as it
  // was) and played after it (the hand slot to land on only exists once the
  // hand has been rebuilt).
  const handArrivals = collectHandArrivalFlights(prevStateForDiscard, state, viewerSeat);
  renderBoard(state);
  playHandArrivalFlights(handArrivals, state, viewerSeat);
  updateLobbyOverlay(state);
  if (wasInPregame && !state?.pregame) {
    updateActionHint("Drag from your hand to cast. The battlefield arranges itself automatically.");
  }
  renderActivationPrompt();
  renderSearchLibraryModal(searchLibraryInfo);
  renderSearchExileModal(getSearchExileInfo(state));
  renderUntapUpToModal(getUntapUpToInfo(state));
  renderLookTopPickModal(getLookTopPickInfo(state));
  renderReorderLibraryModal(reorderLibraryInfo);
  renderHandRevealModal(getHandRevealInfo(state));
  renderDrawChoiceModals(state);
  attemptPendingActivation();

  const combat = getCombatState(state);
  const promptStateKey = `${getCombatDraftStepKey(state)}:${combat?.attackers_locked ? 1 : 0}:${combat?.blockers_locked ? 1 : 0}`;
  if (promptStateKey !== combatPromptKey) {
    combatPromptKey = promptStateKey;
    if (untapInfo) {
      updateActionHint("Choose which lands untap, then press OK.");
    } else if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat?.attackers_locked) {
      updateActionHint("Declare attackers by clicking creatures, or use Alpha Strike to toggle all valid attackers, then press OK.");
    } else if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && !combat?.blockers_locked) {
      updateActionHint("Declare blockers by dragging to attacking creatures, then press OK.");
    }
  }

  // Final-pass override so these prompts always win against other prompt updates.
  if (cleanupInfo) {
    applyCleanupPrompt(cleanupInfo);
  } else if (untapInfo) {
    applyUntapPrompt(untapInfo);
  } else if (upkeepPayInfo) {
    applyUpkeepPayPrompt(upkeepPayInfo);
  } else if (optionalTriggerInfo) {
    applyOptionalTriggerPrompt(optionalTriggerInfo);
  } else if (islandSanctuaryPending) {
    applyIslandSanctuaryPrompt();
  }

  maybeAutoStepAi(state);
  maybeAutoPassUntilTurnEnd(state);
  maybeAutoAdvanceCombatDeclaration(state);
  maybeAutoPassDisabledPhase(state);
  maybeAutoPassPriority(state);
}

// ---------------------------------------------------------------------------
// Battlefield permanent right-click menu
// ---------------------------------------------------------------------------

// The permanent the open menu acts on ({ seat, idx, name }), or null when closed.
let permanentMenuTarget = null;
// Set when a press outside the open menu dismissed it, so the click that press
// produces is swallowed too — a dismissing click must never also act on the
// board underneath (the same way a native context menu eats its dismissal).
let swallowClickAfterMenuDismiss = false;

// One entry per menu item: the server action it sends and the hint it leaves
// behind. "mark-test-result" is handled separately (it opens a modal instead).
const PERMANENT_MENU_ACTIONS = {
  tap: {
    action: "debug_tap_permanent",
    hint: (name) => `Tapped ${name}.`,
  },
  untap: {
    action: "debug_untap_permanent",
    hint: (name) => `Untapped ${name}.`,
  },
  "clear-summoning-sickness": {
    action: "debug_clear_summoning_sickness",
    hint: (name) => `${name} no longer has summoning sickness.`,
  },
  "return-to-hand": {
    action: "debug_return_to_hand",
    hint: (name) => `Returned ${name} to its owner's hand.`,
  },
  destroy: {
    action: "debug_destroy_permanent",
    hint: (name) => `Destroyed ${name}.`,
  },
  exile: {
    action: "debug_exile_permanent",
    hint: (name) => `Exiled ${name}.`,
  },
};

// The permanent the menu was opened on, re-read from *state* — null once it has
// moved zones or the battlefield reshuffled under the stored index.
function permanentMenuPermanent(state = currentState) {
  if (!permanentMenuTarget) return null;
  const permanent =
    state?.players?.[permanentMenuTarget.seat]?.battlefield?.[permanentMenuTarget.idx];
  return permanent && permanent.name === permanentMenuTarget.name ? permanent : null;
}

function closePermanentMenu({ silent = false } = {}) {
  if (!permanentMenuTarget) return;
  permanentMenuTarget = null;
  q("permanentMenu").classList.add("hidden");
  if (!silent) SFX.onMenuToggle(false);
}

// Called on every board render: the stored battlefield index only means
// something against the state the menu was opened on.
function closePermanentMenuIfStale(state) {
  if (permanentMenuTarget && !permanentMenuPermanent(state)) closePermanentMenu({ silent: true });
}

function openPermanentMenu({ seat: targetSeat, idx, event }) {
  const permanent = currentState?.players?.[targetSeat]?.battlefield?.[idx];
  if (!permanent) return;
  permanentMenuTarget = { seat: targetSeat, idx, name: permanent.name };

  const menu = q("permanentMenu");
  q("permanentMenuTitle").textContent = permanent.name;
  // One item, two meanings: it offers the opposite of the current state and
  // carries that choice in its data-action, so the click can never disagree
  // with the label the player read.
  const tapItem = menu.querySelector(".permanent-menu-item--tap");
  tapItem.dataset.action = permanent.tapped ? "untap" : "tap";
  tapItem.textContent = permanent.tapped ? "Untap" : "Tap";
  // Summoning sickness is a creature-only condition (CR 302.6). is_creature —
  // not the printed type — so an animated land (Kormus Bell) counts.
  menu.querySelector('[data-action="clear-summoning-sickness"]').disabled = !permanent.is_creature;
  menu.classList.remove("hidden");

  // Measure once visible, then clamp so the menu never spills off-screen.
  const { width, height } = menu.getBoundingClientRect();
  const margin = 8;
  menu.style.left = `${Math.max(margin, Math.min(event.clientX, window.innerWidth - width - margin))}px`;
  menu.style.top = `${Math.max(margin, Math.min(event.clientY, window.innerHeight - height - margin))}px`;
  SFX.onMenuToggle(true);
}

async function runPermanentMenuAction(itemAction) {
  const target = permanentMenuTarget;
  const stillOnBattlefield = !!permanentMenuPermanent();
  closePermanentMenu({ silent: true });
  if (!target) return;

  if (itemAction === "mark-test-result") {
    openVerifyResultModal(target.name);
    return;
  }

  const entry = PERMANENT_MENU_ACTIONS[itemAction];
  if (!entry) return;
  if (seat === null) {
    updateActionHint("Join or create a session before interacting.", true);
    return;
  }
  if (!stillOnBattlefield) {
    SFX.onError();
    updateActionHint(`${target.name} is no longer on the battlefield.`, true);
    return;
  }

  try {
    await sendAction(withPermanentId(
      {
        seat,
        action: entry.action,
        target_seat: target.seat,
        target_permanent_index: target.idx,
      },
      "target_permanent_id", target.seat, target.idx,
    ));
    updateActionHint(entry.hint(target.name));
  } catch (e) {
    SFX.onError();
    updateActionHint(e.message, true);
  }
}

function initPermanentMenu() {
  const menu = q("permanentMenu");

  menu.addEventListener("click", (event) => {
    const item = event.target.closest(".permanent-menu-item");
    if (!item || item.disabled) return;
    runPermanentMenuAction(item.dataset.action);
  });
  // A right-click on the menu itself dismisses rather than stacking a menu.
  menu.addEventListener("contextmenu", (event) => event.preventDefault());

  // Any press outside the menu dismisses it. Capture phase, so a left press
  // that only meant "close this" never reaches the canvas and taps a permanent;
  // a right press is left alone so the contextmenu that follows can open the
  // menu on whatever was clicked.
  document.addEventListener(
    "mousedown",
    (event) => {
      swallowClickAfterMenuDismiss = false;
      if (!permanentMenuTarget || menu.contains(event.target)) return;
      closePermanentMenu();
      if (event.button !== 0) return;
      swallowClickAfterMenuDismiss = true;
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );
  document.addEventListener(
    "click",
    (event) => {
      if (!swallowClickAfterMenuDismiss) return;
      swallowClickAfterMenuDismiss = false;
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePermanentMenu();
  });
  window.addEventListener("blur", () => closePermanentMenu({ silent: true }));
  window.addEventListener("resize", () => closePermanentMenu({ silent: true }));
}

function handleCanvasCardContextMenu({ seat: targetSeat, idx: permanentIndex, card, event }) {
  if (!currentState) return;
  const combat = getCombatState(currentState);

  try {
    if (
      combat &&
      isCombatStep(currentState, "declare_attackers") &&
      seat === currentState.current_turn &&
      targetSeat === seat &&
      !combat.attackers_locked &&
      combatAttackerDraft.includes(permanentIndex)
    ) {
      combatAttackerDraft = combatAttackerDraft.filter((idx) => idx !== permanentIndex);
      SFX.onMenuToggle(false);
      renderBoard(currentState);
      updateActionHint("Removed attacker from draft selection.");
      return;
    }

    if (
      combat &&
      isCombatStep(currentState, "declare_blockers") &&
      seat === combat.defending_player_index &&
      !combat.blockers_locked &&
      blockerDraftReferences(permanentIndex, targetSeat, combat)
    ) {
      if (targetSeat === combat.defending_player_index) {
        delete combatBlockerDraft[permanentIndex];
      }
      if (targetSeat === currentState.current_turn) {
        for (const [blockerIdx, attackerIndices] of Object.entries(combatBlockerDraft)) {
          const remaining = (Array.isArray(attackerIndices) ? attackerIndices : [attackerIndices])
            .filter((a) => Number(a) !== permanentIndex);
          if (remaining.length === 0) delete combatBlockerDraft[Number(blockerIdx)];
          else combatBlockerDraft[Number(blockerIdx)] = remaining;
        }
      }
      SFX.onMenuToggle(false);
      renderBoard(currentState);
      updateActionHint("Removed blocker target link from draft.");
      return;
    }

    // Nothing in a combat draft to unpick: right-click means "open the menu".
    openPermanentMenu({ seat: targetSeat, idx: permanentIndex, event });
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

// True when the blocker draft has an entry the right-clicked permanent would
// clear — either the blocker itself, or an attacker some blocker points at.
function blockerDraftReferences(permanentIndex, targetSeat, combat) {
  if (targetSeat === combat.defending_player_index && permanentIndex in combatBlockerDraft) {
    return true;
  }
  if (targetSeat !== currentState.current_turn) return false;
  return Object.values(combatBlockerDraft).some((attackerIndices) =>
    (Array.isArray(attackerIndices) ? attackerIndices : [attackerIndices])
      .some((a) => Number(a) === permanentIndex),
  );
}

function initCombatContextMenu() {
  // Context menu for non-battlefield cards (hand etc.) via DOM
  boardEl.addEventListener("contextmenu", (event) => {
    const cardEl = event.target.closest(".card");
    if (!cardEl) return;
    const zoneKind = cardEl.dataset.zoneKind;
    if (zoneKind === "battlefield") return; // handled by canvas
    event.preventDefault();
  });
}

function parseDragPayload(event) {
  try {
    const raw = event.dataTransfer.getData("text/plain");
    if (!raw) return null;
    const payload = JSON.parse(raw);
    if (!payload || !payload.kind || !payload.name) return null;
    return payload;
  } catch {
    return null;
  }
}

async function handleHandCardDropOnBattlefield({ event, targetSeat, targetItem }) {
  if (seat === null) {
    updateActionHint("Join or create a session before interacting.", true);
    return;
  }
  if (pendingCastHandCard) {
    updateActionHint("Finish the current cast before starting another.", true);
    return;
  }
  const payload = parseDragPayload(event);
  if (!payload) {
    updateActionHint("Could not read dropped card data.", true);
    return;
  }

  try {
    if (payload.kind === "hand") {
      const card = findCardInCurrentHand(payload.name);
      beginPendingHandCast(card || payload.name, Number.isInteger(payload.handIndex) ? payload.handIndex : null);
      if (card && cardIsModal(card) && startModalChoicePrompt(card)) { return; }
      if (card && cardRequiresDiscardCost(card) && startCastDiscardCostPrompt(card)) { return; }
      if (card && cardRequiresTargetGraveyardCreature(card)) { startCastGraveyardCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetLand(card)) { startCastLandTargetPrompt(card); return; }
      if (card && cardRequiresTargetArtifact(card)) { startCastArtifactTargetPrompt(card); return; }
      if (card && cardRequiresSeveralTargets(card)) { startCastSeveralTargetsPrompt(card); return; }
      if (card && cardOffersCopyCreatureChoice(card)) { startCastCreatureTargetPrompt(card); return; }
      if (card && cardOffersCopyArtifactChoice(card)) { startCastArtifactTargetPrompt(card); return; }
      if (card && cardRequiresTargetCreature(card)) { startCastCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetPermanent(card)) { startCastPermanentTargetPrompt(card); return; }
      if (card && cardRequiresTargetStackSpell(card)) { startCastStackSpellPrompt(card); return; }
      if (card && cardRequiresDividedDamage(card)) { startCastDividedPrompt(card); return; }
      if (card && cardRequiresTargetAny(card)) { startCastAnyTargetPrompt(card); return; }
      if (card && cardRequiresTargetPlayer(card)) { startCastTargetPrompt(card); return; }
      const castTargetSeat = card ? getDefaultTargetSeat(payload.name) : targetSeat;
      if (card && hasXCost(card)) { startCastXPrompt(card, castTargetSeat); return; }
      const actionBody = { seat, action: "cast", card_name: payload.name, target_seat: castTargetSeat };
      try {
        await sendAction(actionBody);
        updateActionHint(`Cast ${payload.name} targeting seat ${castTargetSeat}.`);
        clearPendingHandCast();
      } catch (e) {
        if (card && e.message && e.message.toLowerCase().startsWith("insufficient mana")) {
          pendingAutoTap = { card, cardName: payload.name, actionBody };
          renderActivationPrompt();
          return;
        }
        clearPendingHandCast();
        throw e;
      }
      return;
    }

    // Dragging a battlefield permanent onto the canvas (activate, or blocker)
    if (payload.kind === "permanent") {
      // If the drop landed on an opponent card during declare_blockers, assign block
      if (
        targetItem &&
        isCombatStep(currentState, "declare_blockers") &&
        seat === getCombatState(currentState)?.defending_player_index &&
        targetItem.seat !== seat &&
        !getCombatState(currentState)?.blockers_locked
      ) {
        // Validate the block immediately (CR 509.1b) rather than on confirm.
        const reason = blockAssignmentRejectionReason(
          currentState,
          Number(payload.permanentIndex),
          targetItem.idx,
        );
        if (reason) {
          SFX.onError();
          updateActionHint(reason, true);
          return;
        }
        assignBlockerDraft(Number(payload.permanentIndex), targetItem.idx);
        SFX.onMenuToggle(true);
        renderBoard(currentState);
        updateActionHint("Blocker link added. Press OK when done declaring blockers.");
        return;
      }

      const me = getCurrentPlayerState();
      const indexedCard = me && Number.isInteger(payload.permanentIndex) ? me.battlefield[payload.permanentIndex] : null;
      const card = indexedCard || (me ? me.battlefield.find((perm) => normalizeCardName(perm) === payload.name) : null);
      if (card) {
        const permanentIndex = me && Number.isInteger(payload.permanentIndex) && me.battlefield[payload.permanentIndex] === card
          ? payload.permanentIndex
          : me.battlefield.findIndex((perm) => perm === card);
        startActivationPrompt(card, targetSeat, permanentIndex >= 0 ? permanentIndex : null);
      }
    }
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

function initDropZones() {
  // Battlefield drop handling is managed entirely by BattlefieldCanvas.
  // This function is kept as a no-op; the canvas callbacks wire up the behavior.
}

function initBattlefieldCanvas() {
  if (battlefieldCanvas) {
    battlefieldCanvas.destroy();
    battlefieldCanvas = null;
  }

  const canvasEl = q("battlefieldCanvas");
  if (!canvasEl) return;

  battlefieldCanvas = new BattlefieldCanvas(canvasEl, {
    onCardClick({ seat: cardSeat, idx: permanentIndex, card }) {
      if (!currentState || seat === null) return;
      try {
        const untapInfo = getUntapLandSelectionInfo(currentState);
        if (untapInfo && cardSeat === seat) {
          const candidates = Array.isArray(untapInfo.candidate_indices) ? untapInfo.candidate_indices : [];
          if (!candidates.includes(permanentIndex)) {
            updateActionHint(`${card.name} is not a valid untap choice.`, true);
            return;
          }
          sendAction({ seat, action: "untap_select", permanent_index: permanentIndex })
            .then(() => {
              const nextInfo = getUntapLandSelectionInfo(currentState);
              updateActionHint(`Untap selection: ${nextInfo?.selected_count ?? "?"}/${nextInfo?.max_count ?? "?"} land(s) selected.`);
            })
            .catch((e) => updateActionHint(e.message, true));
          return;
        }

        // A prompt that picks permanents (forced sacrifice, Balance, Drop of
        // Honey, Kudzu, an upkeep trigger's target, …) answers itself here:
        // clicking a highlighted permanent submits or toggles that choice.
        const boardTargeting = activePromptBoardTargeting(currentState);
        if (boardTargeting && boardTargeting.permanentKeys.size) {
          if (boardTargeting.permanentKeys.has(`${cardSeat}-${permanentIndex}`)) {
            boardTargeting.onPermanent(cardSeat, permanentIndex);
            return;
          }
          if (!boardTargeting.fallThroughOnInvalid) {
            updateActionHint(boardTargeting.invalidHint, true);
            return;
          }
        }

        // Attacker selection only owns the click while attackers are still being
        // chosen. Once they're declared (locked) the step is a priority window, so
        // clicks fall through to tap lands / activate abilities / target spells.
        const combatStateForClick = getCombatState(currentState);
        if (
          isCombatStep(currentState, "declare_attackers") &&
          seat === currentState.current_turn &&
          cardSeat === seat &&
          !combatStateForClick?.attackers_locked
        ) {
          // Only creatures that can legally attack may be selected (CR 508.1a).
          if (!getValidAttackerIndices(currentState).includes(permanentIndex)) {
            updateActionHint(`${card.name} can't attack right now.`, true);
            return;
          }
          toggleCombatAttackerDraft(permanentIndex);
          renderBoard(currentState);
          updateActionHint(`Attackers selected: ${combatAttackerDraft.length}. Use Alpha Strike to toggle all valid attackers, then press OK.`);
          return;
        }

        if (pendingCastTarget) {
          const valid = isPendingCastTargetValidForCard(card, {
            targetSeat: cardSeat,
            zoneKind: "battlefield",
            permanentIndex,
          });
          if (!valid) { updateActionHint("That is not a valid target.", true); return; }
          if (pendingCastTarget.targetKind === "divided") {
            toggleDividedCreatureTarget(cardSeat, permanentIndex);
            return;
          }
          if (pendingCastTarget.targetKind === "several") {
            toggleSeveralTarget(cardSeat, permanentIndex);
            return;
          }
          resolvePendingCastTarget(cardSeat, permanentIndex);
          return;
        }

        // Beyond this point we're trying to use the permanent (tap/activate),
        // which only the controller may do. Targeting an opponent's permanent
        // for a pending spell/ability was already handled above. Exception:
        // "Any player may activate this ability" (Ifh-Bíff Efreet).
        const anyPlayerAbility =
          (card.oracle_text || "").toLowerCase().includes("any player may activate this ability");
        if (cardSeat !== seat && !anyPlayerAbility) {
          updateActionHint("You don't control this permanent.", true);
          return;
        }

        if (!hasActivatedAbility(card)) {
          updateActionHint(`${card.name} has no activated ability to use.`, true);
          return;
        }

        // Identical cards are auto-stacked into piles. If the clicked copy is
        // already tapped, redirect the activation to an untapped copy in the
        // same pile so clicking the pile taps cards one at a time.
        let activateCard = card;
        let activateIdx = permanentIndex;
        if (battlefieldCanvas && card.tapped) {
          const stackMembers = battlefieldCanvas.getStackMembers(cardSeat, permanentIndex);
          for (const member of stackMembers) {
            const memberCard = currentState.players?.[member.seat]?.battlefield?.[member.idx];
            if (memberCard && memberCard.name === card.name && !memberCard.tapped) {
              activateCard = memberCard;
              activateIdx = member.idx;
              break;
            }
          }
        }

        // If the ability costs {T} and the (chosen) copy is still tapped — no
        // untapped copy was found in the pile — it can't be activated. Don't
        // open a prompt; just play the error sound and say so.
        if (activateCard.tapped && abilityCostRequiresTap(activateCard)) {
          SFX.onError();
          updateActionHint("Card is already tapped.", true);
          return;
        }

        // Abilities with a real target are intercepted by the dedicated prompt
        // flows inside startActivationPrompt, so the FFA seat here is only the
        // formal target_seat default — no picker needed.
        startActivationPrompt(
          activateCard,
          isFfaState() ? firstLivingOpponentSeat(currentState, seat, `${activateCard.name} activation default`) : 1 - seat,
          activateIdx,
        );
      } catch (e) {
        updateActionHint(e.message, true);
      }
    },

    onCardContextMenu(info) {
      handleCanvasCardContextMenu(info);
    },

    onCardHover(info) {
      if (!info) {
        if (!battlefieldCanvas?.hasAnyHover()) scheduleHidePreview();
        return;
      }
      showCardPreview(info.card);
    },

    onStackCardHover(info) {
      stackCanvasHoverActive = !!info;
      if (info) {
        if (info.item?.card) showCardPreview(info.item.card);
        return;
      }
      if (!battlefieldCanvas?.hasAnyHover()) scheduleHidePreview();
      // Hover ended: resume the normal flow unless something else still holds.
      if (!isPriorityHeld()) {
        resumeAutoPassAfterHold();
      }
    },

    onStackCardClick(info) {
      if (!info) return;
      // While targeting a spell on the stack (Counterspell, Fork, lace spells…),
      // clicking a spell card in the canvas stack cascade chooses it as the
      // target. The canvas stack index matches the state.stack array index.
      if (pendingCastTarget && (pendingCastTarget.targetKind === "stack" || pendingCastTarget.alsoStack)) {
        selectStackSpellTarget(info.index);
        return;
      }
      toggleStackClickHold(info.index);
    },

    onEmblemClick({ index, emblem }) {
      if (emblem?.kind === "channel") {
        startChannelMana();
        return;
      }
      startEmblemActivation(typeof emblem?.index === "number" ? emblem.index : index);
    },

    onEmblemHover(emblem) {
      if (!emblem) {
        if (!battlefieldCanvas?.hasAnyHover()) scheduleHidePreview();
        return;
      }
      showCardPreview(emblem);
    },

    onShieldHover(source) {
      // Hovering a permanent's shield badge previews the card that granted it.
      if (source) {
        showCardPreview(source);
      } else if (!battlefieldCanvas?.hasAnyHover()) {
        scheduleHidePreview();
      }
    },

    // Deck / graveyard / exile piles drawn on the canvas along the left edge.
    onZonePileHover(info) {
      if (!info) {
        if (!battlefieldCanvas?.hasAnyHover()) scheduleHidePreview();
        return;
      }
      if (info.topCard) showCardPreview(info.topCard);
    },

    onZonePileClick(info) {
      if (!info || info.kind === "library") return;
      openZoneReveal([zoneRevealSectionFor(info.seat, info.kind)]);
    },

    // The player clicked a wedge of the land mana fan — submit the chosen color
    // through the same path the modal used.
    onManaFanPick(symbol) {
      resolvePendingManaColor(symbol);
    },

    // The player clicked away from the fan to dismiss it without choosing.
    onManaFanCancel() {
      if (pendingManaColor && pendingManaColor.fan) {
        pendingManaColor = null;
        renderActivationPrompt();
        updateActionHint("Mana color choice canceled.");
      }
    },

    onHandCardDrop(info) {
      handleHandCardDropOnBattlefield(info).catch((e) => updateActionHint(e.message, true));
    },

    // Raging River: a Left/Right button drawn above a creature was clicked.
    onRiverPileClick(choice) {
      handleRagingRiverPileClick(choice);
    },

    // Camouflage: a numbered pile button drawn above a creature was clicked.
    onCamouflagePileClick(choice) {
      handleCamouflagePileClick(choice);
    },

    onBlockerAssign({ blockerIdx, attackerIdx }) {
      const combat = getCombatState(currentState);
      if (!combat || combat.blockers_locked) {
        updateActionHint("Blockers are already confirmed.", true);
        return;
      }
      // Validate the block as it's assigned (CR 509.1b) rather than waiting for the
      // OK confirmation, so an illegal block is rejected immediately with a reason.
      const reason = blockAssignmentRejectionReason(currentState, blockerIdx, attackerIdx);
      if (reason) {
        SFX.onError();
        updateActionHint(reason, true);
        return;
      }
      assignBlockerDraft(blockerIdx, attackerIdx);
      renderBoard(currentState);
      updateActionHint("Blocker assigned. Press OK when done.");
    },
  });
}

function initTabs() {
  // Log and Debug live in floating overlays over the battlefield, toggled by
  // the 📜 / 🛠️ buttons at the bottom of the phase rail (and closable via
  // their own × buttons).
  const setOverlayOpen = (overlayId, toggleBtnId, open) => {
    const overlay = q(overlayId);
    if (!overlay) return;
    overlay.classList.toggle("hidden", !open);
    q(toggleBtnId)?.classList.toggle("toggle-btn-active", open);
    if (open) SFX.onLogOpen();
    else SFX.onLogClose();
  };
  const toggleOverlay = (overlayId, toggleBtnId, onOpen = null) => {
    const overlay = q(overlayId);
    if (!overlay) return;
    const open = overlay.classList.contains("hidden");
    setOverlayOpen(overlayId, toggleBtnId, open);
    if (open && onOpen) onOpen();
  };
  const scrollLogToBottom = () => {
    const tab = q("logTab");
    if (tab) tab.scrollTop = tab.scrollHeight;
  };
  q("logToggleBtn")?.addEventListener("click", () => toggleOverlay("logOverlay", "logToggleBtn", scrollLogToBottom));
  q("logCloseBtn")?.addEventListener("click", () => setOverlayOpen("logOverlay", "logToggleBtn", false));
  q("debugToggleBtn")?.addEventListener("click", () => toggleOverlay("debugOverlay", "debugToggleBtn"));
  q("debugCloseBtn")?.addEventListener("click", () => setOverlayOpen("debugOverlay", "debugToggleBtn", false));
  q("settingsToggleBtn")?.addEventListener("click", () => toggleOverlay("settingsOverlay", "settingsToggleBtn"));
  q("settingsCloseBtn")?.addEventListener("click", () => setOverlayOpen("settingsOverlay", "settingsToggleBtn", false));
  q("zoneRevealCloseBtn")?.addEventListener("click", () => closeZoneReveal());

  q("rawStateCopyBtn").addEventListener("click", async () => {
    try {
      await copyTextToClipboard(q("rawState").textContent || "");
      updateActionHint("Raw state copied to clipboard.");
    } catch {
      updateActionHint("Could not copy raw state to clipboard.", true);
    }
  });

  q("rawStatePasteBtn").addEventListener("click", pasteRawState);
}

// Read JSON from the clipboard, show it in the Raw State box, and push it to the
// server so the live game (for every player) is rebuilt to match.
async function pasteRawState() {
  if (!sessionId) {
    updateActionHint("No active game to paste state into.", true);
    return;
  }
  let text;
  try {
    if (!navigator.clipboard || !window.isSecureContext) {
      throw new Error("Clipboard read is unavailable in this context.");
    }
    text = await navigator.clipboard.readText();
  } catch {
    updateActionHint("Could not read the clipboard. Paste raw state manually.", true);
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    updateActionHint("Clipboard does not contain valid JSON game state.", true);
    return;
  }

  q("rawState").textContent = JSON.stringify(parsed, null, 2);
  try {
    const state = await postJson(`/api/sessions/${sessionId}/raw-state`, {
      state: parsed,
      seat: Number.isInteger(seat) ? seat : null,
    });
    renderState(state, { skipStaleCheck: true });
    updateActionHint("Game state replaced from pasted raw state.");
  } catch (e) {
    updateActionHint(`Could not apply raw state: ${e.message}`, true);
  }
}

function initCardPreviewHover() {
  boardEl.addEventListener("mouseover", (event) => {
    const cardEl = event.target.closest(".card");
    if (!cardEl || !boardEl.contains(cardEl)) {
      return;
    }

    const previewPayload = cardEl.dataset.previewCard;
    if (!previewPayload) {
      return;
    }

    try {
      showCardPreview(JSON.parse(previewPayload));
    } catch {
      clearCardPreview();
    }
  });

  // The preview is hover-only: leaving a DOM card (hand fan, reveal panel,
  // modal grids) without entering another one hides it. Canvas hover-loss is
  // handled by the canvas callbacks.
  boardEl.addEventListener("mouseout", (event) => {
    const cardEl = event.target.closest(".card");
    if (!cardEl || !boardEl.contains(cardEl)) return;
    if (event.relatedTarget && event.relatedTarget.closest?.(".card")) return;
    scheduleHidePreview();
  });
}

async function getState(skipStaleCheck = false) {
  if (!sessionId) return;
  // Capture the session this fetch is for; if we leave/replace the session while
  // the request is in flight (e.g. Leave Game concedes then resets to the menu),
  // a late response must not render the old finished state over the menu or a
  // freshly hosted game.
  const requestedSessionId = sessionId;
  const params = new URLSearchParams();
  if (Number.isInteger(seat)) {
    params.set("seat", String(seat));
  }
  const query = params.toString();
  const url = query ? `/api/sessions/${sessionId}/state?${query}` : `/api/sessions/${sessionId}/state`;
  const resp = await fetch(url);
  if (sessionId !== requestedSessionId) return;
  if (resp.status === 404) {
    resetToSetup();
    return;
  }
  if (!resp.ok) return;
  const state = await resp.json();
  if (sessionId !== requestedSessionId) return;
  renderState(state, { skipStaleCheck });
}

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await resp.json();
  if (!resp.ok) {
    throw new Error(payload.detail || "request failed");
  }
  return payload;
}

// Resolve a deck-select value into a request payload. Personal decks live only in
// this browser, so they're sent inline (deck_cards) rather than by server id.
function deckSelection(selectId) {
  const id = q(selectId)?.value || null;
  if (id && window.PersonalDecks?.isPersonalId(id)) {
    const deck = window.PersonalDecks.get(id);
    // A personal deck's sideboard travels inline with it; a shared deck's is
    // read server-side from its saved record.
    if (deck) {
      return {
        deck_id: null,
        deck_cards: deck.cards || [],
        deck_sideboard: deck.sideboard || [],
        // The command zone (CR 903.5a) travels inline with a personal deck for
        // the same reason its sideboard does — the server has no copy of it.
        deck_commander: deck.commander || [],
        deck_name: deck.name || null,
      };
    }
  }
  if (id) {
    const meta = window.getDeckMeta?.(id);
    return {
      deck_id: id, deck_cards: null, deck_sideboard: null, deck_commander: null,
      deck_name: meta?.name || null,
    };
  }
  return {
    deck_id: null, deck_cards: null, deck_sideboard: null, deck_commander: null,
    deck_name: null,
  };
}

// Segmented toggles: visible button groups backed by a hidden <input>, so the
// rest of the code (and deck-editor.js) keeps reading q(id).value and listening
// for "change" on the input exactly as it did with the old <select>s.
function initSegToggles(root = document) {
  for (const wrap of root.querySelectorAll(".seg-toggle[data-input]")) {
    if (wrap.dataset.segWired) continue;
    wrap.dataset.segWired = "1";
    const input = q(wrap.dataset.input);
    if (!input) continue;
    const sync = () => {
      for (const btn of wrap.querySelectorAll(".seg-option")) {
        btn.classList.toggle("is-active", btn.dataset.value === input.value);
      }
    };
    wrap.addEventListener("click", (event) => {
      const btn = event.target instanceof Element ? event.target.closest(".seg-option") : null;
      if (!btn || btn.dataset.value === input.value) return;
      input.value = btn.dataset.value;
      sync();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    sync();
  }
}

// Auto-assigned display names for AI seats — the host only names themself.
const FFA_AI_NAMES = ["Urza", "Mishra", "Serra", "Ashnod"];

function ffaAiName(index) {
  return `AI ${FFA_AI_NAMES[index % FFA_AI_NAMES.length]}`;
}

// Markup for one Free-For-All seat card. Seat 0 is the host ("You") and is the
// only seat with a name field; other human seats are open lobby slots and AI
// seats get an auto-assigned name.
function ffaSeatBlockHtml(index, defaults) {
  const isHost = index === 0;
  // The host seat defaults to the player's remembered name (persisted in
  // localStorage), falling back to "Player 1" for a first-time visitor.
  const name = defaults?.name || (isHost ? rememberedPlayerName() : null) || "Player 1";
  const isAi = defaults ? !!defaults.isAi : false;
  const colors = defaults?.colors || 2;
  return `
    <div class="seat-card ffa-seat-block" data-seat-index="${index}">
      <div class="seat-card-head">
        <h3 class="seat-card-title">${isHost ? "You (Host)" : `Seat ${index + 1}`}</h3>
        <input type="hidden" id="ffaSeatType_${index}" value="${isAi ? "ai" : "human"}" />
        <div class="seg-toggle seg-toggle--small" data-input="ffaSeatType_${index}">
          <button type="button" class="seg-option" data-value="human">Human</button>
          <button type="button" class="seg-option" data-value="ai">AI</button>
        </div>
      </div>
      ${isHost ? `<label id="ffaSeatNameLabel_${index}">Name <input id="ffaSeatName_${index}" value="${escapeHtml(name)}" /></label>` : ""}
      <div id="ffaSeatDeckFields_${index}" class="ffa-seat-deck-fields">
        <label>Deck
          <select id="ffaSeatDeck_${index}" class="ffa-deck-select">
            <option value="">Random deck</option>
          </select>
        </label>
        <label id="ffaSeatColorsLabel_${index}">Deck colors (1-5) <input id="ffaSeatColors_${index}" type="number" min="1" max="5" value="${colors}" /></label>
      </div>
      <div id="ffaSeatAiNote_${index}" class="seat-ai-note hidden">Plays as <strong>${escapeHtml(ffaAiName(index))}</strong></div>
      <div id="ffaSeatOpenNote_${index}" class="seat-open-note hidden">Open seat &mdash; a player joins with their own name and deck.</div>
    </div>`;
}

// (Re)build the per-seat cards for the current #ffaSeatCount, preserving
// whatever the user already entered for seats that still exist afterward.
function generateFfaSeatBlocks() {
  const container = q("ffaSeatsContainer");
  if (!container) return;
  const seatCount = Number(q("ffaSeatCount")?.value) || 4;
  const previous = [];
  for (let i = 0; i < seatCount; i++) {
    const typeEl = q(`ffaSeatType_${i}`);
    previous.push({
      name: q(`ffaSeatName_${i}`)?.value,
      isAi: typeEl ? typeEl.value === "ai" : undefined,
      colors: q(`ffaSeatColors_${i}`)?.value,
    });
  }
  let html = "";
  for (let i = 0; i < seatCount; i++) {
    const prev = previous[i];
    html += ffaSeatBlockHtml(i, {
      name: prev?.name,
      isAi: prev?.isAi !== undefined ? prev.isAi : false,
      colors: prev?.colors,
    });
  }
  container.innerHTML = html;
  initSegToggles(container);
  // Populate the freshly-created deck selects with the current deck catalog
  // (deck-editor.js owns the deck list and exposes this helper on window).
  for (let i = 0; i < seatCount; i++) {
    window.populateDeckSelectElement?.(q(`ffaSeatDeck_${i}`), "Random deck");
  }
  // Deck fields are shown for the host and for AI seats — a human non-host seat
  // is an open lobby slot filled by whoever joins, so it needs no config here.
  // The colors input only matters for random decks, so it hides when a deck is picked.
  for (let i = 0; i < seatCount; i++) {
    const isHost = i === 0;
    const typeEl = q(`ffaSeatType_${i}`);
    const deckEl = q(`ffaSeatDeck_${i}`);
    const sync = () => {
      const isAi = typeEl.value === "ai";
      const showDeckFields = isHost || isAi;
      q(`ffaSeatDeckFields_${i}`)?.classList.toggle("hidden", !showDeckFields);
      q(`ffaSeatOpenNote_${i}`)?.classList.toggle("hidden", isAi || isHost);
      q(`ffaSeatAiNote_${i}`)?.classList.toggle("hidden", !isAi);
      q(`ffaSeatNameLabel_${i}`)?.classList.toggle("hidden", isAi);
      q(`ffaSeatColorsLabel_${i}`)?.classList.toggle("hidden", Boolean(deckEl?.value));
    };
    typeEl?.addEventListener("change", sync);
    deckEl?.addEventListener("change", sync);
    sync();
  }
}

// Toggle between the Standard host form and the Free-For-All seat list, and
// (re)generate the seat blocks whenever the format or seat count changes.
function syncFormatFields() {
  const format = q("format")?.value || "standard";
  const isFfa = format === "free_for_all";
  q("standardModeFields")?.classList.toggle("hidden", isFfa);
  q("ffaModeFields")?.classList.toggle("hidden", !isFfa);
  if (isFfa) {
    generateFfaSeatBlocks();
  } else {
    window.syncStartPageColorInputs?.();
  }
}

// Build the {name, is_ai, colors, deck_id, deck_cards} entries for a
// Free-For-All session from the per-seat blocks generateFfaSeatBlocks() built.
function collectFfaSeats() {
  const seatCount = Number(q("ffaSeatCount")?.value) || 4;
  const seats = [];
  for (let i = 0; i < seatCount; i++) {
    const typeEl = q(`ffaSeatType_${i}`);
    const colorsEl = q(`ffaSeatColors_${i}`);
    const sel = deckSelection(`ffaSeatDeck_${i}`);
    const isAi = typeEl ? typeEl.value === "ai" : false;
    // Only the host names themself; AI seats get auto-assigned names and open
    // human seats are placeholders until a player joins with their own name.
    let name;
    if (isAi) {
      name = ffaAiName(i);
    } else if (i === 0) {
      name = q("ffaSeatName_0")?.value || "Player 1";
    } else {
      name = `Player ${i + 1}`;
    }
    seats.push({
      name,
      is_ai: isAi,
      colors: Number(colorsEl?.value) || 2,
      deck_id: sel.deck_id,
      deck_cards: sel.deck_cards,
      deck_sideboard: sel.deck_sideboard,
      deck_commander: sel.deck_commander,
      deck_name: sel.deck_name,
    });
  }
  return seats;
}

// The player's chosen name persists across sessions in localStorage so they
// don't have to retype it every visit. Restored into the name inputs on load
// (restorePlayerName) and re-saved whenever they start or join a game.
const PLAYER_NAME_KEY = "player_name";

function savePlayerName(name) {
  const trimmed = (name || "").trim();
  if (!trimmed) return;
  try {
    localStorage.setItem(PLAYER_NAME_KEY, trimmed);
  } catch (_) {
    /* storage unavailable (private mode / disabled) — non-fatal */
  }
}

function rememberedPlayerName() {
  try {
    return localStorage.getItem(PLAYER_NAME_KEY) || null;
  } catch (_) {
    return null;
  }
}

function restorePlayerName() {
  const saved = rememberedPlayerName();
  if (!saved) return;
  for (const id of ["hostName", "joinName", "ffaSeatName_0"]) {
    const el = q(id);
    if (el) el.value = saved;
  }
}

async function createSession() {
  hideSetupPanel();
  syncSeedControls();
  const format = q("format")?.value || "standard";
  const useCustomSeed = q("useCustomSeed").checked;
  const playingForAnte = window.isPlayingForAnte();
  // CR 903.1 / 903.12a: "" means an ordinary game, which is what the server
  // reads a missing variant as.
  const variant = q("commanderVariant")?.value || null;
  savePlayerName(format === "free_for_all" ? q("ffaSeatName_0")?.value : q("hostName")?.value);
  let req;
  if (format === "free_for_all") {
    req = {
      mode: "free_for_all",
      seats: collectFfaSeats(),
      use_custom_seed: useCustomSeed,
      custom_seed: useCustomSeed ? Number(q("customSeed").value) : null,
      enable_pregame: true,
      simultaneous_mulligan: !!q("simultaneousMulligan")?.checked,
      playing_for_ante: playingForAnte,
      variant,
    };
  } else {
    const mode = q("mode").value;
    const hostSel = deckSelection("hostDeckSelect");
    // The opponent's deck is only host-configurable when it's AI. For networked
    // human_vs_human the guest brings their own deck on join.
    const guestSel = mode === "human_vs_human"
      ? { deck_id: null, deck_cards: null, deck_sideboard: null, deck_commander: null, deck_name: null }
      : deckSelection("guestDeckSelect");
    req = {
      mode,
      host_name: q("hostName").value,
      host_colors: Number(q("hostColors").value),
      host_deck_id: hostSel.deck_id,
      host_deck_cards: hostSel.deck_cards,
      host_deck_sideboard: hostSel.deck_sideboard,
      host_deck_commander: hostSel.deck_commander,
      host_deck_name: hostSel.deck_name,
      guest_colors: Number(q("guestColors").value),
      guest_deck_id: guestSel.deck_id,
      guest_deck_cards: guestSel.deck_cards,
      guest_deck_sideboard: guestSel.deck_sideboard,
      guest_deck_commander: guestSel.deck_commander,
      guest_deck_name: guestSel.deck_name,
      use_custom_seed: useCustomSeed,
      custom_seed: useCustomSeed ? Number(q("customSeed").value) : null,
      enable_pregame: true,
      simultaneous_mulligan: !!q("simultaneousMulligan")?.checked,
      playing_for_ante: playingForAnte,
      variant,
    };
  }
  const data = await postJson("/api/sessions", req);
  sessionId = data.session_id;
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url, data.public_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  if (data.state?.lobby && !data.state.lobby.game_started) {
    updateActionHint("Waiting for players to join — share the Join URL above.");
  } else if (!data.state?.pregame) {
    updateActionHint("Session ready. Drag from your hand to cast. The battlefield arranges itself automatically.");
  }
}

async function joinSession() {
  sessionId = q("joinSessionId").value.trim();
  if (!sessionId) {
    alert("Enter a session ID");
    return;
  }
  savePlayerName(q("joinName")?.value);
  const joinSel = deckSelection("joinDeckSelect");
  const data = await postJson(`/api/sessions/${sessionId}/join`, {
    guest_name: q("joinName").value,
    guest_deck_id: joinSel.deck_id,
    guest_deck_cards: joinSel.deck_cards,
    guest_deck_sideboard: joinSel.deck_sideboard,
    guest_deck_commander: joinSel.deck_commander,
    guest_deck_name: joinSel.deck_name,
    guest_colors: Number(q("joinColors")?.value) || 2,
  });
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url, data.public_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  if (!data.state?.pregame) {
    updateActionHint("Joined. Drag from your hand to play. The battlefield arranges itself automatically.");
  }
}

const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);

async function sendAction(actionBody) {
  if (!sessionId) return;
  // Always carry the current phase-rail hold preferences so the server knows where
  // to stop on the AI's turn — including steps it resolves itself (turn start, end).
  const body = { stop_steps: opponentStopSteps(), self_stop_steps: selfStopSteps(), ...actionBody };
  // Carry the chosen mode for a "Choose one —" modal spell through whichever cast
  // path fires (direct, targeted, X, auto-tap retry) without threading it manually.
  if (_CAST_ACTIONS.has(body.action) && body.mode_index == null && pendingCastModeIndex != null) {
    body.mode_index = pendingCastModeIndex;
  }
  // "Choose one or more —": while a collection is open, a cast body is not a
  // cast — it is the target the current mode's own prompt just produced. Capture
  // it and open the next mode's prompt instead of sending. Intercepted here
  // because this is the one place every targeting prompt ends up, the same
  // reason the single mode index rides through it.
  if (pendingModeCollection && _CAST_ACTIONS.has(body.action)) {
    const run = pendingModeCollection;
    const entry = { index: run.order[run.cursor] };
    if (Number.isInteger(body.target_seat)) entry.target_seat = body.target_seat;
    if (Number.isInteger(body.permanent_index)) entry.permanent_index = body.permanent_index;
    if (Number.isInteger(body.target_permanent_index)) entry.permanent_index = body.target_permanent_index;
    // Prefer the identity over the slot, for the reason every other target
    // does: a permanent that leaves between the click and the cast must be a
    // refusal, not whichever permanent slid into its place (CR 400.7).
    if (Number.isInteger(entry.target_seat) && Number.isInteger(entry.permanent_index)) {
      const pid = permanentIdAt(entry.target_seat, entry.permanent_index);
      if (Number.isInteger(pid)) entry.permanent_id = pid;
    }
    if (Number.isInteger(body.target_stack_index)) entry.target_stack_index = body.target_stack_index;
    run.collected.push(entry);
    run.cursor += 1;
    promptNextModeTarget();
    return;
  }
  // Same trick for a cast permission's zone: whichever cast path fires, the
  // engine learns which zone the card leaves.
  if (body.action === "cast" && body.from_zone == null && pendingCastFromZone != null) {
    body.from_zone = pendingCastFromZone;
  }
  const payload = await postJson(`/api/sessions/${sessionId}/action`, body);
  renderState(payload);
}

q("homeHostBtn")?.addEventListener("click", () => {
  showMenuPage("host");
  syncFormatFields();
});

q("homeJoinBtn")?.addEventListener("click", () => {
  showMenuPage("join");
});

q("hostBackBtn")?.addEventListener("click", () => {
  showMenuPage("home");
});

q("joinBackBtn")?.addEventListener("click", () => {
  showMenuPage("home");
});

async function requestRematch() {
  // Coordinated rematch: tell the server this seat wants to play again and wait
  // for the opponent to agree. The shared session stays open; when both players
  // have voted the server rebuilds the game and pushes fresh state over SSE.
  if (!sessionId || seat === null) return;
  const btn = q("playAgainBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Waiting for opponent…";
  }
  try {
    const payload = await postJson(`/api/sessions/${sessionId}/rematch`, { seat });
    renderState(payload, { skipStaleCheck: true });
  } catch (e) {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Play Again";
    }
    alert(e.message);
  }
}

function restartLocalGame() {
  // Single-browser modes (vs AI / AI vs AI): tear down the finished session and
  // spin up a fresh one. createSession() reads the (still-populated) host inputs.
  q("gameOverOverlay")?.classList.add("hidden");
  closeStateSyncStream();
  sessionId = null;
  seat = null;
  currentState = null;
  previousLifeBySeat = {};
  return createSession().catch((e) => resetToSetup(e.message));
}

q("playAgainBtn")?.addEventListener("click", async () => {
  if (currentState?.mode === "human_vs_human") {
    await requestRematch();
  } else {
    await restartLocalGame();
  }
});

q("leaveRoomBtn")?.addEventListener("click", () => {
  resetToSetup("Left the game. Start a new one when you're ready.");
});

// ── Settings panel: match actions ─────────────────────────────────────────────
function closeSettingsPanel() {
  q("settingsOverlay")?.classList.add("hidden");
  q("settingsToggleBtn")?.classList.remove("toggle-btn-active");
}

async function restartMatch() {
  if (!sessionId || seat === null) return;
  try {
    // Server-side restart rebuilds the board in-place and broadcasts to every
    // connected seat (see the "match_restart" reason in openStateSyncStream),
    // so all players get the announcement and the fresh game.
    const data = await postJson(`/api/sessions/${sessionId}/restart`, { seat });
    closeSettingsPanel();
    renderState(data, { skipStaleCheck: true });
  } catch (e) {
    alert(e.message);
  }
}

async function concedeCurrentSeat() {
  if (!sessionId || seat === null) return;
  const data = await postJson(`/api/sessions/${sessionId}/action`, { seat, action: "concede" });
  renderState(data, { skipStaleCheck: true });
}

q("restartMatchBtn")?.addEventListener("click", () => {
  if (!confirm("Restart the match? The board will be reset for a new game.")) return;
  restartMatch();
});

q("concedeBtn")?.addEventListener("click", async () => {
  if (!confirm("Concede this match? You will lose the game.")) return;
  try {
    await concedeCurrentSeat();
    closeSettingsPanel();
  } catch (e) {
    alert(e.message);
  }
});

q("leaveGameBtn")?.addEventListener("click", async () => {
  if (!confirm("Leave the match? You will forfeit and return to the main menu.")) return;
  // Concede first so the remaining players see the forfeit, then bail to setup.
  try {
    await concedeCurrentSeat();
  } catch {
    // Even if the concede call fails (e.g. game already over), still leave.
  }
  closeSettingsPanel();
  resetToSetup("You left the match.");
});

q("lobbyStartBtn")?.addEventListener("click", async () => {
  if (!sessionId || seat === null) return;
  const data = await postJson(`/api/sessions/${sessionId}/start`, { seat });
  renderState(data);
});

q("lobbyCopyLinkBtn")?.addEventListener("click", async () => {
  // Prefer the public IPv6 URL so the link works beyond the local network.
  const linkUrl = currentPublicJoinUrl || currentLanJoinUrl || currentJoinUrl;
  if (!linkUrl) return;
  try {
    await copyTextToClipboard(linkUrl);
    updateActionHint("Join URL copied to clipboard.");
  } catch {
    updateActionHint("Could not copy the Join URL. Copy it manually.", true);
  }
});

q("startBtn").addEventListener("click", async () => {
  try {
    hideSetupPanel();
    await createSession();
  } catch (e) {
    showSetupPanel();
    alert(e.message);
  }
});

initSegToggles();

q("mode").addEventListener("change", () => {
  window.syncStartPageColorInputs?.();
});

q("format")?.addEventListener("change", () => {
  syncFormatFields();
});

q("ffaSeatCount")?.addEventListener("change", () => {
  generateFfaSeatBlocks();
});

q("useCustomSeed").addEventListener("change", () => {
  syncSeedControls();
});

// Turning ante on/off changes which decks may be chosen (CR 407.3), so the
// deck pickers are rebuilt whenever it flips.
q("playingForAnte")?.addEventListener("change", () => {
  window.refreshDeckSelectOptions?.();
});

q("joinBtn").addEventListener("click", async () => {
  try {
    await joinSession();
  } catch (e) {
    alert(e.message);
  }
});

// A player's name/life pill was clicked. A prompt that chooses players (Cuombajj
// Witches' damage, Black Vise's "choose an opponent") owns the click while it is
// open; otherwise it aims the pending spell/ability at that player.
function handlePlayerPillClick(targetSeat, event) {
  if (!Number.isInteger(targetSeat)) return;
  const boardTargeting = activePromptBoardTargeting();
  if (boardTargeting && boardTargeting.playerSeats.size) {
    event?.preventDefault();
    if (!boardTargeting.playerSeats.has(targetSeat)) {
      updateActionHint(boardTargeting.invalidHint, true);
      return;
    }
    boardTargeting.onPlayer(targetSeat);
    return;
  }
  if (
    !pendingCastTarget ||
    (pendingCastTarget.targetKind !== "player" &&
      pendingCastTarget.targetKind !== "any" &&
      pendingCastTarget.targetKind !== "divided")
  )
    return;
  event?.preventDefault();
  handlePlayerTargetClick(targetSeat);
}

// Free-For-All opponent panels are rebuilt (innerHTML) on every render, so use
// one delegated listener on the container rather than rebinding per-panel.
q("ffaOpponentPanels")?.addEventListener("click", (event) => {
  const panel = event.target instanceof Element ? event.target.closest("[data-target-seat]") : null;
  if (!panel) return;
  handlePlayerPillClick(Number(panel.dataset.targetSeat), event);
});

for (const elementId of ["selfName", "oppName", "selfLife", "oppLife"]) {
  q(elementId)?.addEventListener("click", (event) => {
    const source = event.currentTarget;
    if (!(source instanceof HTMLElement)) return;
    handlePlayerPillClick(Number(source.dataset.targetSeat), event);
  });
}


q("promptCancelBtn").addEventListener("click", () => {
  SFX.onMenuCancel();
  const wasCasting = !!(pendingCastTarget || pendingCastX || pendingAutoTap || pendingModalChoice || pendingDiscardCost);
  pendingActivation = null;
  pendingCastTarget = null;
  pendingCastX = null;
  pendingManaColor = null;
  pendingAutoTap = null;
  pendingModalChoice = null;
  pendingModeCollection = null;
  pendingDiscardCost = null;
  pendingAbilityChoice = null;
  pendingChannel = null;
  const wasPickingAttackTarget = !!pendingAttackTarget;
  pendingAttackTarget = null;
  clearPendingHandCast();
  battlefieldCanvas?.hideManaFan();
  battlefieldCanvas?.setTargetingKeys([]);
  if (battlefieldCanvas) battlefieldCanvas.zonePileTargeting = null;
  closeZoneRevealIfAutoOpened();
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
  clearFfaTargetingHighlights();
  // Canceling the FFA attack-target picker returns to the declare-attackers
  // prompt, whose summary/Alpha Strike controls were hidden while it was open.
  if (wasPickingAttackTarget && currentState) renderCombatControls(currentState);
  renderActivationPrompt();
  updateActionHint(wasCasting ? "Cast canceled. Any mana in your pool is retained." : "Prompt canceled.");
});

q("promptAutoTapBtn")?.addEventListener("click", async () => {
  try {
    await performAutoTap();
  } catch (e) {
    updateActionHint(e.message, true);
  }
});

q("promptOkBtn").addEventListener("click", async () => {
  try {
    // Pregame prompts (mulligan bottom-select's "Confirm (n/n)") drive the OK
    // button through okBtn.onclick; without this guard the fallback chain below
    // also fires and sends a stray pass_priority the server 400s on.
    if (getPregameInfo()) return;
    // A multi-select mode prompt is finished by its own confirm, before every
    // fallback below — the cascade would otherwise read the open prompt as a
    // pending activation and send a cast with no modes at all.
    if (pendingModalChoice && pendingModalChoice.atLeast) {
      confirmModalModes();
      return;
    }
    const handledUntap = await handleUntapPromptOk();
    if (handledUntap) {
      return;
    }
    const handledCombat = await handleCombatPromptOk();
    if (handledCombat) {
      return;
    }
    const handledPriority = await handlePriorityPromptOk();
    if (handledPriority) {
      return;
    }
    confirmPendingActivation();
  } catch (e) {
    updateActionHint(e.message, true);
  }
});

q("promptCustomOkBtn").addEventListener("click", () => {
  if (pendingChannel) {
    resolveChannel(Number(q("promptCustomValue")?.value));
    return;
  }
  resolvePendingCastX();
});

q("promptSteps").addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  const modeChoice = target.dataset.modeChoice;
  if (modeChoice !== undefined && pendingModalChoice) {
    chooseModalMode(Number(modeChoice));
    return;
  }

  const discardCost = target.dataset.discardCost;
  if (discardCost !== undefined && pendingDiscardCost) {
    payDiscardCost(Number(discardCost));
    return;
  }

  const attackSeat = target.dataset.attackSeat;
  if (attackSeat !== undefined && pendingAttackTarget) {
    confirmPendingAttackTarget(Number(attackSeat));
    return;
  }

  const targetChoice = target.dataset.targetChoice;
  if (targetChoice && pendingCastTarget) {
    const targetPermanentIndex = target.dataset.targetPermanentIndex;
    const parsedPermanentIndex =
      targetPermanentIndex !== undefined && targetPermanentIndex !== ""
        ? Number(targetPermanentIndex)
        : null;
    resolvePendingCastTarget(Number(targetChoice), Number.isInteger(parsedPermanentIndex) ? parsedPermanentIndex : null);
    return;
  }

  const choice = target.dataset.xChoice;
  if (choice && pendingCastX) {
    if (choice === "custom") {
      pendingCastX.awaitingCustomValue = true;
      renderActivationPrompt();
      return;
    }
    resolvePendingCastX(Number(choice));
    return;
  }

  const channelLife = target.dataset.channelLife;
  if (channelLife !== undefined && pendingChannel) {
    if (channelLife === "custom") {
      pendingChannel.awaitingCustomValue = true;
      renderActivationPrompt();
      return;
    }
    resolveChannel(Number(channelLife));
    return;
  }

  const manaColorChoice = target.dataset.manaColor;
  if (manaColorChoice && pendingManaColor) {
    resolvePendingManaColor(manaColorChoice);
    return;
  }

  const abilityChoice = target.dataset.abilityChoice;
  if (abilityChoice !== undefined && pendingAbilityChoice) {
    resolveAbilityChoice(Number(abilityChoice));
  }
});

q("endTurnBtn").addEventListener("click", async () => {
  try {
    if (autoPassTurnEndEnabled) {
      autoPassTurnEndEnabled = false;
      autoPassTurnEndRequestedStateKey = "";
      autoPassMode = null;
      renderBoard(currentState);
      updateActionHint("Auto-pass canceled.");
      return;
    }

    pendingActivation = null;
    pendingCastTarget = null;
    pendingCastX = null;
    pendingManaColor = null;
    battlefieldCanvas?.hideManaFan();
    const isSelfTurn = !!currentState && seat !== null && currentState.current_turn === seat;
    autoPassTurnEndEnabled = true;
    autoPassMode = isSelfTurn ? "self" : "opponent";
    autoPassTurnEndRequestedStateKey = "";
    renderBoard(currentState);
    renderActivationPrompt();
    await maybeAutoPassUntilTurnEnd(currentState);
    updateActionHint(
      autoPassMode === "self"
        ? "Auto-passing priority until your turn ends."
        : "Auto-pass enabled for opponent turn priority."
    );
  } catch (e) {
    alert(e.message);
  }
});

q("undoBtn").addEventListener("click", async () => {
  SFX.onMenuCancel();
  if (!sessionId) return;
  try {
    const url = seat !== null
      ? `/api/sessions/${sessionId}/undo?seat=${seat}`
      : `/api/sessions/${sessionId}/undo`;
    const resp = await fetch(url, { method: "POST" });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "undo failed");
    renderState(payload, { skipStaleCheck: true });
    updateActionHint("Undone.");
  } catch (e) {
    alert(e.message);
  }
});

q("nextPhaseBtn").addEventListener("click", async () => {
  try {
    await sendAction({ seat, action: "pass_priority" });
    updateActionHint("Passed priority.");
  } catch (e) {
    alert(e.message);
  }
});

q("aiStepBtn").addEventListener("click", async () => {
  try {
    await sendAction({ seat: seat ?? 0, action: "ai_step" });
    updateActionHint("Ran one AI step.");
  } catch (e) {
    alert(e.message);
  }
});

q("aiLoopBtn").addEventListener("click", async () => {
  if (!sessionId) return;
  try {
    const resp = await fetch(`/api/sessions/${sessionId}/run-ai?steps=10`, { method: "POST" });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "run-ai failed");
    renderState(payload);
    updateActionHint("Ran AI for 10 steps.");
  } catch (e) {
    alert(e.message);
  }
});

q("aiAutoStepToggle")?.addEventListener("change", () => {
  if (!q("aiAutoStepToggle")?.checked) {
    return;
  }
  aiAutoStepRequestedStateKey = "";
  maybeAutoStepAi(currentState);
});

q("debugCardSearch").addEventListener("input", (event) => {
  const value = event.target.value;
  if (debugSearchTimer !== null) {
    clearTimeout(debugSearchTimer);
  }
  debugSearchTimer = setTimeout(() => {
    fetchDebugSuggestions(value).catch((error) => {
      updateDebugStatus(error.message || "Could not load card suggestions.", "error");
    });
  }, 120);
});

q("debugCardSearch").addEventListener("focus", () => {
  fetchDebugSuggestions(q("debugCardSearch").value).catch(() => {
    // Keep this silent on focus to avoid noisy UI warnings.
  });
});

q("debugCardSearch").addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  try {
    await addDebugCardToHand();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugAddToHandBtn").addEventListener("click", async () => {
  try {
    await addDebugCardToHand();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugAddToSideboardBtn").addEventListener("click", async () => {
  try {
    await addDebugCardToSideboard();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugCastFreeBtn").addEventListener("click", async () => {
  try {
    await castDebugCardForFree();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugCastFreeOpponentBtn").addEventListener("click", async () => {
  try {
    await castDebugCardForFreeAsOpponent();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugAddUntestedBtn").addEventListener("click", async () => {
  try {
    await addUntestedCardToHand();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

q("debugAddManaToggle").addEventListener("change", (event) => {
  debugAddManaMode = event.target.checked;
  if (currentState) {
    renderState(currentState);
  }
});

q("debugForceAttackAllToggle").addEventListener("change", async (event) => {
  const enabled = event.target.checked;
  try {
    await sendAction({ seat, action: "debug_force_ai_attack_all", force_attack_all: enabled });
    updateDebugStatus(
      enabled
        ? "AI will now attack with every legal attacker."
        : "AI attacker selection restored to normal.",
      "success"
    );
  } catch (e) {
    // Roll the checkbox back to match the server's unchanged state on failure.
    event.target.checked = !enabled;
    updateDebugStatus(e.message || "Could not toggle force-attack.", "error");
  }
});

q("debugMarkResultBtn").addEventListener("click", () => {
  openVerifyResultModal();
});

q("debugViewTrackerBtn").addEventListener("click", () => {
  openTrackerModal();
});

let verifySearchTimer = null;
q("verifyCardName").addEventListener("input", (event) => {
  const value = event.target.value;
  if (verifySearchTimer !== null) {
    clearTimeout(verifySearchTimer);
  }
  verifySearchTimer = setTimeout(() => {
    fetchVerifySuggestions(value).catch(() => {
      // Keep silent to avoid noisy UI warnings while typing.
    });
  }, 120);
});

q("verifyResultRow").addEventListener("change", setVerifyReasonVisibility);
q("verifyResultCancelBtn").addEventListener("click", closeVerifyResultModal);
q("verifyResultSubmitBtn").addEventListener("click", async () => {
  await submitVerifyResult();
});
q("verifyResultModal").addEventListener("click", (event) => {
  if (event.target === q("verifyResultModal")) closeVerifyResultModal();
});

q("trackerFilter").addEventListener("input", renderTrackerList);
q("trackerStatusFilter").addEventListener("change", renderTrackerList);
q("trackerCloseBtn").addEventListener("click", closeTrackerModal);
q("trackerModal").addEventListener("click", (event) => {
  if (event.target === q("trackerModal")) closeTrackerModal();
});

refreshVerifyProgress();

const params = new URLSearchParams(window.location.search);
const sessionFromUrl = params.get("session");
if (sessionFromUrl) {
  q("joinSessionId").value = sessionFromUrl;
  showMenuPage("join");
}

window.syncStartPageColorInputs?.();
syncSeedControls();
setDebugMenuEnabled(false);
q("undoBtn").disabled = true;
q("endTurnBtn").disabled = true;
q("endTurnBtn").textContent = "End Turn";
q("nextPhaseBtn").disabled = true;
fetchDebugSuggestions().catch(() => {
  // Intentionally ignored during startup.
});

loadSymbolMap();

initDropZones(); // no-op; canvas handles battlefield drop
initTabs();
initCardPreviewHover();
initCombatContextMenu();
initPermanentMenu();
clearCardPreview();

// ── Audio controls ────────────────────────────────────────────────────────────
// Restore the player's remembered name into the setup name inputs on load.
(function initPlayerName() {
  restorePlayerName();
})();

(function initAudioControls() {
  const muteBtn = q("muteBtn");
  const volSlider = q("volumeSlider");
  if (!muteBtn || !volSlider) return;

  // Restore persisted state
  volSlider.value = String(Math.round(SFX.getVolume() * 100));
  muteBtn.textContent = SFX.isMuted() ? "🔇" : "🔊";

  muteBtn.addEventListener("click", () => {
    const next = !SFX.isMuted();
    SFX.setMuted(next);
    muteBtn.textContent = next ? "🔇" : "🔊";
    SFX.onMenuToggle(!next);
  });

  volSlider.addEventListener("input", () => {
    const v = parseInt(volSlider.value) / 100;
    SFX.setVolume(v);
    if (SFX.isMuted() && v > 0) {
      SFX.setMuted(false);
      muteBtn.textContent = "🔊";
    }
  });

  // ── Music controls ──────────────────────────────────────────────────────────
  const musicMuteBtn = q("musicMuteBtn");
  const musicSlider = q("musicVolumeSlider");
  if (musicMuteBtn && musicSlider) {
    musicSlider.value = String(Math.round(MUSIC.getVolume() * 100));
    musicMuteBtn.textContent = MUSIC.isMuted() ? "🔇" : "🎵";

    musicMuteBtn.addEventListener("click", () => {
      const next = !MUSIC.isMuted();
      MUSIC.setMuted(next);
      musicMuteBtn.textContent = next ? "🔇" : "🎵";
      SFX.onMenuToggle(!next);
    });

    musicSlider.addEventListener("input", () => {
      const v = parseInt(musicSlider.value) / 100;
      MUSIC.setVolume(v);
      if (MUSIC.isMuted() && v > 0) {
        MUSIC.setMuted(false);
        musicMuteBtn.textContent = "🎵";
      }
    });
  }
})();
