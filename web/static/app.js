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
let debugSearchTimer = null;
let symbolMap = {};
let combatDragSource = null;
let combatDamageDraft = {};
let combatAttackerDraft = [];
let combatBlockerDraft = {};
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
let searchLibrarySelectedIndex = null;
let searchLibraryFilter = "";
let autoPassPriorityInFlight = false;
let autoPassPriorityRequestedStateKey = "";
let autoPassDisabledPhaseInFlight = false;
let autoPassDisabledPhaseRequestedStateKey = "";
// Phases toggled OFF will be auto-passed. Default: only M1, AT, M2 are ON.
const disabledPhases = new Set([
  "untap", "upkeep", "draw",
  "beginning_of_combat", "declare_blockers", "combat_damage", "end_of_combat",
  "end", "cleanup",
]);
/** @type {BattlefieldCanvas|null} */
let battlefieldCanvas = null;

const setupEl = document.getElementById("setup");
const boardEl = document.getElementById("boardPanel");
const aiControlsEl = document.getElementById("aiControls");
const joinUrlEl = document.getElementById("joinUrl");
const lanJoinUrlEl = document.getElementById("lanJoinUrl");
const startGameSectionEl = document.getElementById("startGameSection");
const joinExistingSectionEl = document.getElementById("joinExistingSection");

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
  }

  if (Number.isFinite(numericSeat) && Number.isFinite(numericLife)) {
    previousLifeBySeat[numericSeat] = numericLife;
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
  }

  if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index) {
    combatBlockerDraft = {};
    for (const pair of combat?.blockers || []) {
      combatBlockerDraft[Number(pair.blocker_index)] = Number(pair.attacker_index);
    }
  } else {
    combatBlockerDraft = {};
  }
}

function toggleCombatAttackerDraft(permanentIndex) {
  const idx = Number(permanentIndex);
  if (!Number.isInteger(idx) || idx < 0) return;
  if (combatAttackerDraft.includes(idx)) {
    combatAttackerDraft = combatAttackerDraft.filter((value) => value !== idx);
  } else {
    combatAttackerDraft = [...combatAttackerDraft, idx].sort((a, b) => a - b);
  }
}

function isCardLikelyAttacker(card) {
  if (!card || typeof card === "string") return false;
  return String(card.type || "").toLowerCase().includes("creature") && !card.tapped;
}

function canCardAttackDefenderFromPublicState(card, defenderBattlefield) {
  if (!isCardLikelyAttacker(card)) return false;

  const text = String(card.oracle_text || "").toLowerCase();
  const hasDefender = text.includes("defender");
  const canIgnoreDefender = text.includes("can attack as though it didn't have defender");
  if (hasDefender && !canIgnoreDefender) return false;

  if (text.includes("can't attack unless defending player controls an island")) {
    const defenderControlsIsland = Array.isArray(defenderBattlefield)
      ? defenderBattlefield.some((perm) => String(perm?.type || "").toLowerCase().includes("island"))
      : false;
    if (!defenderControlsIsland) return false;
  }

  return true;
}

function getValidAttackerIndices(state = currentState) {
  if (!state || !isCombatStep(state, "declare_attackers") || seat !== state.current_turn) return [];

  const combat = getCombatState(state);
  const attackerSeat = state.current_turn;
  const defenderSeat = Number.isInteger(combat?.defending_player_index)
    ? combat.defending_player_index
    : 1 - attackerSeat;

  const attackerPlayer = state.players?.[attackerSeat];
  const defenderPlayer = state.players?.[defenderSeat];
  const attackerBattlefield = Array.isArray(attackerPlayer?.battlefield) ? attackerPlayer.battlefield : [];
  const defenderBattlefield = Array.isArray(defenderPlayer?.battlefield) ? defenderPlayer.battlefield : [];

  return attackerBattlefield
    .map((card, index) => ({ card, index }))
    .filter(({ card }) => canCardAttackDefenderFromPublicState(card, defenderBattlefield))
    .map(({ index }) => index);
}

function isCardLikelyBlocker(card) {
  if (!card || typeof card === "string") return false;
  return String(card.type || "").toLowerCase().includes("creature") && !card.tapped;
}

function canCardBlockAttackerFromPublicState(blockerCard, attackerCard) {
  if (!isCardLikelyBlocker(blockerCard)) return false;
  if (!attackerCard || typeof attackerCard === "string") return false;

  const attackerText = String(attackerCard.oracle_text || "").toLowerCase();
  const blockerText = String(blockerCard.oracle_text || "").toLowerCase();
  const blockerType = String(blockerCard.type || "").toLowerCase();

  if (attackerText.includes("can't be blocked") && !attackerText.includes("except")) {
    return false;
  }

  const attackerHasFlying = attackerText.includes("flying");
  const blockerHasFlying = blockerText.includes("flying");
  const blockerHasReach = blockerText.includes("reach");
  if (attackerHasFlying && !(blockerHasFlying || blockerHasReach)) {
    return false;
  }

  if (attackerText.includes("can't be blocked by walls") && blockerType.includes("wall")) {
    return false;
  }

  return true;
}

function getValidBlockerAssignments(state = currentState) {
  if (!state || !isCombatStep(state, "declare_blockers")) return [];
  const combat = getCombatState(state);
  if (!combat || seat !== combat.defending_player_index) return [];

  const attackerSeat = state.current_turn;
  const defenderSeat = combat.defending_player_index;
  const attackerPlayer = state.players?.[attackerSeat];
  const defenderPlayer = state.players?.[defenderSeat];
  const attackerBattlefield = Array.isArray(attackerPlayer?.battlefield) ? attackerPlayer.battlefield : [];
  const defenderBattlefield = Array.isArray(defenderPlayer?.battlefield) ? defenderPlayer.battlefield : [];
  const attackerIndices = Array.isArray(combat.attackers)
    ? combat.attackers.map((item) => Number(item.attacker_index)).filter((idx) => Number.isInteger(idx) && idx >= 0)
    : [];

  const assignments = [];
  for (let blockerIndex = 0; blockerIndex < defenderBattlefield.length; blockerIndex += 1) {
    const blockerCard = defenderBattlefield[blockerIndex];
    if (!isCardLikelyBlocker(blockerCard)) continue;
    for (const attackerIndex of attackerIndices) {
      const attackerCard = attackerBattlefield[attackerIndex];
      if (!attackerCard) continue;
      if (!canCardBlockAttackerFromPublicState(blockerCard, attackerCard)) continue;
      assignments.push({ blocker_index: blockerIndex, attacker_index: attackerIndex });
    }
  }

  return assignments;
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
    return Object.entries(combatBlockerDraft).map(([blockerIndex, attackerIndex]) => ({
      blocker_index: Number(blockerIndex),
      attacker_index: Number(attackerIndex),
    }));
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

  battlefieldCanvas.setCombatArrows(arrows);
  battlefieldCanvas.setAttackingKeys(attackingKeys);
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

function setSetupModeForUrlSession(hasSessionInUrl) {
  if (!startGameSectionEl || !joinExistingSectionEl) return;

  startGameSectionEl.classList.toggle("hidden", hasSessionInUrl);
  startGameSectionEl.hidden = hasSessionInUrl;

  joinExistingSectionEl.classList.remove("hidden");
  joinExistingSectionEl.hidden = false;
}

function setVisible(active) {
  if (active) {
    hideSetupPanel();
  } else {
    showSetupPanel();
  }
  boardEl.classList.toggle("hidden", !active);
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
  source.addEventListener("state", () => {
    getState().catch(() => {
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
  boardEl.classList.add("hidden");
  aiControlsEl?.classList.add("hidden");
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

function hasBlockingPromptForAutoPass(state = currentState) {
  if (getCleanupDiscardInfo(state) || getUntapLandSelectionInfo(state) || getUpkeepPayInfo(state)) return true;
  return !!(pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor);
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
        target_seat: Number.isInteger(combat?.defending_player_index) ? combat.defending_player_index : 1 - seat,
      });
      return;
    }

    if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && !combat?.blockers_locked) {
      await sendAction({ seat, action: "declare_blockers", blocker_pairs: {} });
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

async function maybeAutoPassPriority(state = currentState) {
  if (holdPriorityActive) return;
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
    await sendAction({ seat, action: "pass_priority" });
  } catch {
    // Silently absorb; next state update will retry if needed.
  } finally {
    autoPassPriorityInFlight = false;
  }
}

async function maybeAutoPassDisabledPhase(state = currentState) {
  if (holdPriorityActive) return;
  if (autoPassTurnEndEnabled) return;
  if (!state || seat === null) return;
  if (autoPassDisabledPhaseInFlight) return;
  if (state.priority_player !== seat) return;
  if (hasBlockingPromptForAutoPass(state)) return;

  const activeKey = getActiveStepKey(state);
  if (!disabledPhases.has(activeKey)) return;

  const stackSize = Array.isArray(state.stack) ? state.stack.length : 0;
  if (stackSize > 0) return;

  const stateKey = getAutoPassStateKey(state);
  if (!stateKey || stateKey === autoPassDisabledPhaseRequestedStateKey) return;

  autoPassDisabledPhaseRequestedStateKey = stateKey;
  autoPassDisabledPhaseInFlight = true;
  try {
    const combat = getCombatState(state);
    if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && !combat?.attackers_locked) {
      await sendAction({
        seat,
        action: "declare_attackers",
        attacker_indices: [],
        target_seat: Number.isInteger(combat?.defending_player_index) ? combat.defending_player_index : 1 - seat,
      });
      return;
    }
    if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && !combat?.blockers_locked) {
      await sendAction({ seat, action: "declare_blockers", blocker_pairs: {} });
      return;
    }
    await sendAction({ seat, action: "pass_priority" });
  } catch {
    // Silently absorb
  } finally {
    autoPassDisabledPhaseInFlight = false;
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
    await sendAction({ seat: seat ?? 0, action: "ai_step" });
  } catch (error) {
    const message = error instanceof Error ? error.message : "AI step failed";
    updateActionHint(`Auto AI step paused: ${message}`, true);
  } finally {
    aiAutoStepInFlight = false;
  }
}

function hasOpenHumanSlot(state) {
  if (!state) return false;

  const joinedSeats = new Set((state.joined_seats || []).map((value) => Number(value)));
  const seatTypes = state.seat_types || {};
  for (const seat of [0, 1]) {
    const seatType = seatTypes[seat] ?? seatTypes[String(seat)] ?? "human";
    if (seatType === "human" && !joinedSeats.has(seat)) {
      return true;
    }
  }

  return false;
}

function hasActivatedAbility(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").trim();
  if (!text) return false;
  return /\{t\}|:\s*/i.test(text);
}

function getActivatedAbilityCost(card) {
  if (!card || typeof card === "string") return "";
  const text = (card.oracle_text || "").trim();
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

function cardRequiresTargetPlayer(card) {
  if (!card || typeof card === "string") return false;
  return (card.oracle_text || "").toLowerCase().includes("target player");
}

function cardRequiresTargetLand(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  return text.includes("target land") || text.includes("enchant land");
}

function cardRequiresTargetCreature(card) {
  if (!card || typeof card === "string") return false;
  return (card.oracle_text || "").toLowerCase().includes("enchant creature");
}

function cardRequiresTargetPermanent(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  return text.includes("target spell or permanent") || (text.includes("target permanent") && !text.includes("target land") && !text.includes("target creature"));
}

function cardRequiresManaColorChoice(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  return text.includes("any one color") || text.includes("one mana of any color");
}

function getMaxAffordableX(manaPool, manaCost) {
  const pool = manaPool || {};
  const cost = parseManaCostSymbols(manaCost || "");
  const totalMana = MANA_ORDER.reduce((sum, symbol) => sum + Number(pool[symbol] || 0), 0);
  const fixedCost = cost.W + cost.U + cost.B + cost.R + cost.G + cost.C + cost.generic;
  const maxPossible = Math.max(0, totalMana - fixedCost);

  for (let candidate = maxPossible; candidate >= 0; candidate -= 1) {
    if (manaPoolCanPayCost(pool, { ...cost, generic: cost.generic + candidate })) {
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

    const landIndices = computeAutoTapLands(pending.card.mana_cost || "", me.mana_pool, me.battlefield);
    if (landIndices.length > 0) {
      updateActionHint(`Auto-tapping ${landIndices.length} land(s)...`);
      for (const permanentIndex of landIndices) {
        await sendAction({ seat, action: "tap", permanent_index: permanentIndex });
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

function getSearchLibraryInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.search_library;
  if (!info) return null;
  if (info.caster_seat !== seat) return null;
  return info;
}

function getDefaultTargetSeat(cardName) {
  if (seat === null) return 1;
  if (["Ancestral Recall", "Healing Salve", "Stream of Life"].includes(cardName)) {
    return seat;
  }
  return 1 - seat;
}

function getTargetableLandsForPrompt(state = currentState) {
  if (!state) return [];

  const result = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.battlefield)) continue;
    for (const [permanentIndex, permanent] of player.battlefield.entries()) {
      if (!permanent || !String(permanent.type || "").toLowerCase().includes("land")) continue;
      result.push({
        targetSeat,
        permanentIndex,
        cardName: permanent.name || "Land",
        ownerName: player.name || `Seat ${targetSeat}`,
      });
    }
  }
  return result;
}

function getTargetableCreaturesForPrompt(state = currentState) {
  if (!state) return [];
  const result = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.battlefield)) continue;
    for (const [permanentIndex, permanent] of player.battlefield.entries()) {
      if (!permanent || !String(permanent.type || "").toLowerCase().includes("creature")) continue;
      result.push({ targetSeat, permanentIndex, cardName: permanent.name || "Creature", ownerName: player.name || `Seat ${targetSeat}` });
    }
  }
  return result;
}

function getTargetablePermanentsForPrompt(state = currentState) {
  if (!state) return [];
  const result = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.battlefield)) continue;
    for (const [permanentIndex, permanent] of player.battlefield.entries()) {
      if (!permanent) continue;
      result.push({ targetSeat, permanentIndex, cardName: permanent.name || "Permanent", ownerName: player.name || `Seat ${targetSeat}` });
    }
  }
  return result;
}

function isPendingCastTargetValidForCard(card, { targetSeat = null, zoneKind = "", permanentIndex = null } = {}) {
  if (!pendingCastTarget) return false;
  if (!Number.isInteger(targetSeat)) return false;
  if (!zoneKind) return false;

  if (pendingCastTarget.targetKind === "player") {
    return zoneKind === "hand" || zoneKind === "battlefield";
  }

  if (pendingCastTarget.targetKind === "land") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    if (!card || typeof card === "string") return false;
    return String(card.type || "").toLowerCase().includes("land");
  }

  if (pendingCastTarget.targetKind === "creature") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    if (!card || typeof card === "string") return false;
    return String(card.type || "").toLowerCase().includes("creature");
  }

  if (pendingCastTarget.targetKind === "permanent") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    return true;
  }

  return false;
}

function findCardInCurrentHand(cardName) {
  const me = getCurrentPlayerState();
  if (!me || !Array.isArray(me.hand)) return null;
  return me.hand.find((card) => normalizeCardName(card) === cardName) || null;
}

function beginPendingHandCast(card, handIndex = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  pendingCastHandCard = {
    cardName,
    handIndex: Number.isInteger(handIndex) && handIndex >= 0 ? handIndex : null,
  };
}

function clearPendingHandCast() {
  pendingCastHandCard = null;
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
  if (shouldShowPriorityPrompt(state)) return true;
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor || pendingAutoTap) return true;

  const hasValidAttackers = getValidAttackerIndices(state).length > 0;
  const hasValidBlockers = getValidBlockerAssignments(state).length > 0;
  const isDeclareAttackersPrompt = isCombatStep(state, "declare_attackers") && hasValidAttackers;
  const isDeclareBlockersPrompt = isCombatStep(state, "declare_blockers") && hasValidBlockers;
  return isDeclareAttackersPrompt || isDeclareBlockersPrompt;
}

function shouldShowPriorityPrompt(state = currentState) {
  if (!state || seat === null) return false;
  if (state.priority_player !== seat) return false;
  if (getCleanupDiscardInfo(state) || getUntapLandSelectionInfo(state) || getUpkeepPayInfo(state)) return false;

  // Combat declaration prompts own the prompt panel while declarations are pending.
  if (combatPromptNeedsConfirmation(state)) return false;

  const phase = state.current_turn_phase;
  return phase === "precombat_main" || phase === "combat" || phase === "postcombat_main" || state.current_step === "end";
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
    const defendingSeat = Number.isInteger(combat.defending_player_index) ? combat.defending_player_index : 1 - seat;
    await sendAction({
      seat,
      action: "declare_attackers",
      attacker_indices: declared,
      target_seat: defendingSeat,
    });
    updateActionHint(
      `Attackers declared (${declared.length}). Players may now cast spells/activate abilities before blockers.`,
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

async function handlePriorityPromptOk() {
  if (!currentState || seat === null) return false;
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
    `<div>Chosen: ${selectedCount}</div>`,
    `<div>Total needed: ${requiredCount}</div>`,
    `<div>Remaining: ${remaining}</div>`,
    "<div>Action: click cards in your hand to select or unselect them.</div>",
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

  panel.classList.remove("hidden");
  okBtn.classList.remove("hidden");
  customRow.classList.add("hidden");
  title.textContent = "Choose Lands to Untap";
  body.textContent = "Select tapped lands to untap, then press OK.";
  steps.innerHTML = [
    `<div>Maximum lands: ${maxCount}</div>`,
    `<div>Selected: ${selectedCount}</div>`,
    "<div>Action: click your tapped lands to toggle selection.</div>",
  ].join("");
  cancelBtn.disabled = true;
  okBtn.disabled = false;
  customOkBtn.disabled = true;
}

function manaObjectToSymbolString(mana) {
  if (!mana || typeof mana !== "object") return "?";
  return Object.entries(mana)
    .flatMap(([sym, count]) => Array(Number(count)).fill(`{${sym}}`))
    .join("");
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

  panel.classList.remove("hidden");
  okBtn.classList.add("hidden");
  customRow.classList.add("hidden");
  title.textContent = "Upkeep Payment Required";
  body.textContent = `${cardName} requires a payment at the beginning of your upkeep. Tap lands to generate mana, then pay or sacrifice.`;

  const payBtn = `<button type="button" class="prompt-choice-btn" id="upkeepPayBtn">Pay ${renderSymbolsInline(manaStr)}</button>`;
  const sacBtn = `<button type="button" class="prompt-choice-btn" id="upkeepSacBtn">Sacrifice ${escapeHtml(cardName)}</button>`;
  const remaining = pending.length;
  steps.innerHTML = [
    `<div>Card: ${escapeHtml(cardName)}</div>`,
    `<div>Cost: ${renderSymbolsInline(manaStr)}</div>`,
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

function getOpponentName(state = currentState) {
  if (!state || !Array.isArray(state.players) || state.players.length < 2) {
    return "Opponent";
  }
  const viewerSeat = Number.isInteger(seat) ? seat : 0;
  const oppSeat = viewerSeat === 0 ? 1 : 0;
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
  const me = getCurrentPlayerState();
  const cleanupDiscard = getCleanupDiscardInfo();
  const untapInfo = getUntapLandSelectionInfo();
  const upkeepPayInfo = getUpkeepPayInfo();
  const inCombat = currentState?.current_turn_phase === "combat";
  const hasValidAttackers = getValidAttackerIndices(currentState).length > 0;
  const hasValidBlockers = getValidBlockerAssignments(currentState).length > 0;
  const isDeclareAttackersStep = isCombatStep(currentState, "declare_attackers") && hasValidAttackers;
  const isDeclareBlockersStep = isCombatStep(currentState, "declare_blockers") && hasValidBlockers;
  const isCombatDeclarePromptStep = isDeclareAttackersStep || isDeclareBlockersStep;

  applyPriorityPromptStyle(panel, currentState);

  if (cleanupDiscard) {
    applyCleanupPrompt(cleanupDiscard);
    return;
  }

  if (untapInfo) {
    applyUntapPrompt(untapInfo);
    return;
  }

  if (upkeepPayInfo) {
    applyUpkeepPayPrompt(upkeepPayInfo);
    return;
  }

  if (pendingAutoTap) {
    panel.classList.remove("hidden");
    if (autoTapBtn) {
      autoTapBtn.classList.remove("hidden");
      const canSatisfy = !!me && canAutoTapSatisfyCost(
        pendingAutoTap.card.mana_cost || "",
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
      `<div>Cost: ${renderSymbolsInline(pendingAutoTap.card.mana_cost || "none")}</div>`,
      `<div>Current mana: ${me ? formatManaSymbolsHtml(me.mana_pool) : "Unknown"}</div>`,
    ].join("");
    cancelBtn.disabled = false;
    okBtn.disabled = true;
    customOkBtn.disabled = true;
    return;
  }

  if (!pendingActivation && !pendingCastTarget && !pendingCastX && !pendingManaColor) {
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
      title.textContent = "Priority";
      body.textContent = "Take an action (cast a spell, activate an ability, or play a land for turn), or press OK to pass priority.";
    } else if (shouldShowWaitingPriority) {
      title.textContent = `Waiting for ${getOpponentName(currentState)}...`;
      body.textContent = "Opponent has priority.";
    } else {
      title.textContent = "No pending activation.";
      body.textContent = "Select an activated ability to begin paying its cost.";
    }
    steps.innerHTML = "";
    customRow.classList.add("hidden");
    okBtn.classList.toggle("hidden", shouldShowWaitingPriority);
    okBtn.disabled = shouldShowWaitingPriority || (!combatPromptNeedsConfirmation(currentState) && !shouldShowPriority);
    cancelBtn.disabled = true;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingCastTarget) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    title.textContent = `Choose target for ${pendingCastTarget.cardName}`;
    if (pendingCastTarget.targetKind === "land") {
      body.textContent = "Click a valid land on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "creature") {
      body.textContent = "Click a valid creature on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "permanent") {
      body.textContent = "Click any permanent on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else {
      const players = Array.isArray(currentState?.players) ? currentState.players : [];
      const targetButtons = players
        .map((player, index) => {
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
    cancelBtn.disabled = false;
    customOkBtn.disabled = true;
    return;
  }

  if (pendingCastX) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    title.textContent = `Choose X for ${pendingCastX.cardName}`;
    body.textContent = `You have ${pendingCastX.maxX} mana available for X after paying the colored cost.`;
    const choiceButtons = [];
    for (let value = 0; value <= pendingCastX.maxX; value += 1) {
      choiceButtons.push(`<button type="button" class="prompt-choice-btn" data-x-choice="${value}">${value}</button>`);
    }
    choiceButtons.push('<button type="button" class="prompt-choice-btn" data-x-choice="custom">Custom...</button>');
    steps.innerHTML = [
      `<div>Cost: ${renderSymbolsInline(pendingCastX.card.mana_cost || "none")}</div>`,
      `<div>Needed: ${formatManaSymbolsHtml(pendingCastX.manaRequirement || {})}</div>`,
      `<div>Current mana: ${me ? formatManaSymbolsHtml(me.mana_pool) : "Unknown"}</div>`,
      `<div class="prompt-choice-row">${choiceButtons.join("")}</div>`,
    ].join("");
    customRow.classList.toggle("hidden", !pendingCastX.awaitingCustomValue);
    customValue.max = String(pendingCastX.maxX);
    customValue.value = String(Math.min(Number(customValue.value || 0), pendingCastX.maxX));
    okBtn.disabled = true;
    cancelBtn.disabled = false;
    customOkBtn.disabled = !pendingCastX.awaitingCustomValue;
    return;
  }

  if (pendingManaColor) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    title.textContent = `Choose mana color for ${pendingManaColor.cardName}`;
    body.textContent = "Select the mana color this ability should generate.";
    steps.innerHTML = [
      `<div>Ability: ${renderSymbolsInline(pendingManaColor.oracleText || "Activated mana ability")}</div>`,
      `<div class="prompt-choice-row">${MANA_COLOR_OPTIONS.map(
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
    await sendAction({
      seat,
      action: "activate",
      permanent_name: pending.cardName,
      permanent_index: pending.permanentIndex,
      target_seat: pending.targetSeat,
    });
    updateActionHint(`Activated ${pending.cardName}.`);
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

function startActivationPrompt(card, targetSeat, permanentIndex = null) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  if (cardRequiresManaColorChoice(card)) {
    pendingManaColor = {
      cardName,
      permanentIndex,
      targetSeat,
      oracleText: card.oracle_text || "",
    };
    renderActivationPrompt();
    updateActionHint(`Choose a mana color for ${cardName}.`);
    return;
  }

  const activationCost = getActivatedAbilityCost(card);
  if (!shouldPromptForActivationCost(activationCost)) {
    sendAction({
      seat,
      action: "activate",
      permanent_name: cardName,
      permanent_index: permanentIndex,
      target_seat: targetSeat,
    })
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
  };
  renderActivationPrompt();
  updateActionHint(
    `Activation pending for ${cardName}. Press OK to begin paying the cost or cancel to undo it.`,
  );
}

function resolvePendingManaColor(manaColor) {
  if (!pendingManaColor || seat === null) return;
  if (!MANA_COLOR_OPTIONS.some((option) => option.symbol === manaColor)) {
    updateActionHint("Choose one of W, U, B, R, or G.", true);
    return;
  }

  const pending = pendingManaColor;
  pendingManaColor = null;
  renderActivationPrompt();
  updateActionHint(`Activating ${pending.cardName} for ${manaColor} mana...`);

  sendAction({
    seat,
    action: "activate",
    permanent_name: pending.cardName,
    permanent_index: pending.permanentIndex,
    target_seat: pending.targetSeat,
    mana_color: manaColor,
  })
    .then(() => updateActionHint(`Activated ${pending.cardName} and chose ${manaColor}.`))
    .catch((e) => updateActionHint(e.message, true));
}

function startCastTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "player",
    castAction,
  };
  renderActivationPrompt();
  updateActionHint(`Choose a target for ${cardName}.`);
}

function startCastLandTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  if (getTargetableLandsForPrompt().length === 0) {
    updateActionHint(`No valid land targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "land",
    castAction,
  };
  renderActivationPrompt();
  updateActionHint(`Choose a land target for ${cardName}.`);
}

function startCastCreatureTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  if (getTargetableCreaturesForPrompt().length === 0) {
    updateActionHint(`No valid creature targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "creature",
    castAction,
  };
  renderActivationPrompt();
  updateActionHint(`Choose a creature target for ${cardName}.`);
}

function startCastPermanentTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  if (getTargetablePermanentsForPrompt().length === 0) {
    updateActionHint(`No valid permanent targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "permanent",
    castAction,
  };
  renderActivationPrompt();
  updateActionHint(`Choose a target permanent for ${cardName}.`);
}

function startCastXPrompt(card, targetSeat, targetPermanentIndex = null, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastX = {
    kind: "cast_x",
    card,
    cardName,
    targetSeat,
    targetPermanentIndex,
    castAction,
    manaRequirement: parseManaCostSymbols(card.mana_cost || ""),
    maxX: getMaxAffordableX(getCurrentPlayerState()?.mana_pool, card.mana_cost || ""),
    awaitingCustomValue: false,
  };
  renderActivationPrompt();
  updateActionHint(`Choose X for ${cardName}.`);
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
  if (pending.targetKind === "creature" && selectedPermanentIndex === null) {
    updateActionHint("Choose a creature in play to target.", true);
    return;
  }
  if (pending.targetKind === "permanent" && selectedPermanentIndex === null) {
    updateActionHint("Choose a permanent in play to target.", true);
    return;
  }

  pendingCastTarget = null;
  renderActivationPrompt();

  if (hasXCost(pending.card)) {
    startCastXPrompt(pending.card, selectedTarget, selectedPermanentIndex, pending.castAction || "cast");
    return;
  }

  const actionBody = {
    seat,
    action: pending.castAction || "cast",
    card_name: pending.cardName,
    target_seat: selectedTarget,
    permanent_index: selectedPermanentIndex,
  };
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
  if (pendingCastTarget.targetKind !== "player") return;
  if (!Number.isInteger(targetSeat)) return;
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
  updateActionHint(`Casting ${pending.cardName} with X = ${selectedX}...`);

  sendAction({
    seat,
    action: pending.castAction || "cast",
    card_name: pending.cardName,
    target_seat: pending.targetSeat,
    permanent_index: pending.targetPermanentIndex,
    x_value: selectedX,
  })
    .then(() => updateActionHint(`Cast ${pending.cardName} with X = ${selectedX}.`))
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

function setSingleJoinUrl(element, label, url = "") {
  if (!element) return;
  const trimmed = String(url || "").trim();
  if (!trimmed) {
    element.dataset.url = "";
    element.textContent = "";
    element.classList.add("hidden");
    return;
  }

  element.dataset.url = trimmed;
  element.textContent = `${label}: ${trimmed}`;
  element.classList.remove("hidden");
}

function setJoinUrls(url = "", lanUrl = "") {
  setSingleJoinUrl(joinUrlEl, "Join URL", url);
  setSingleJoinUrl(lanJoinUrlEl, "LAN Join URL", lanUrl);
}

function syncJoinUrlVisibility(state) {
  const visible = hasOpenHumanSlot(state);
  for (const element of [joinUrlEl, lanJoinUrlEl]) {
    if (!element) continue;
    if (!element.dataset.url) {
      element.classList.add("hidden");
      continue;
    }
    element.classList.toggle("hidden", !visible);
  }
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
  q("debugCastFreeBtn").disabled = !enabled || !canCastFree;
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

  const card = await fetchCardByName(cardName);
  const resolvedCardName = normalizeCardName(card) || cardName;

  if (card && cardRequiresTargetLand(card)) {
    startCastLandTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a land target for ${resolvedCardName}.`, "success");
    return;
  }

  if (card && cardRequiresTargetPermanent(card)) {
    startCastPermanentTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a permanent target for ${resolvedCardName}.`, "success");
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

function clearCardPreview() {
  q("cardPreview").classList.add("empty-preview");
  q("cardPreviewImage").src = "/images/card_back.webp";
  q("cardPreviewImage").alt = "Card back";
  q("cardPreviewImage").classList.remove("hidden");
  q("cardPreviewEmpty").classList.add("hidden");
  q("cardPreviewName").textContent = "No card selected";
  q("cardPreviewType").textContent = "";
  q("cardPreviewText").textContent = "";
}

function showCardPreview(card) {
  const largeImageUri = normalizeLargeImageUri(card);
  q("cardPreviewName").textContent = normalizeCardName(card) || "Card";
  q("cardPreviewType").textContent = typeof card === "string" ? "" : card.type || "";
  const previewText = typeof card === "string" ? "" : card.oracle_text || "";
  const sicknessLabel = typeof card === "object" && card?.summoning_sick ? "Summoning Sickness" : "";
  setSymbolsHtml(q("cardPreviewText"), [previewText, sicknessLabel].filter(Boolean).join("\n"));

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
    selected = false,
    targetSeat = null,
    zoneKind = "",
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
  if (cleanupSelectable) cardEl.classList.add("cleanup-selectable", "clickable");
  if (selected) cardEl.classList.add("selected-card");
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
          updateActionHint(`Untap selection: ${selectedCount}/${maxCount} land(s) selected.`);
          return;
        }

        if (
          zoneKind === "battlefield" &&
          Number.isInteger(permanentIndex) &&
          isCombatStep(currentState, "declare_attackers") &&
          seat === currentState?.current_turn &&
          targetSeat === seat
        ) {
          if (!isCardLikelyAttacker(card)) {
            updateActionHint(`${cardName} is not able to attack right now.`, true);
            return;
          }
          toggleCombatAttackerDraft(permanentIndex);
          renderBoard(currentState);
          updateActionHint(
            `Attackers selected: ${combatAttackerDraft.length}. Use Alpha Strike to toggle all valid attackers, then press OK.`,
          );
          return;
        }

        if (!hasActivatedAbility(card)) {
          updateActionHint(`${cardName} has no activated ability to use.`, true);
          return;
        }

        startActivationPrompt(card, 1 - seat, permanentIndex);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
  }

  if (castOnClick && typeof card === "object") {
    cardEl.classList.add("clickable");
    cardEl.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();

      if (seat === null) {
        updateActionHint("Join or create a session before interacting.", true);
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

        const cardName = normalizeCardName(card);
        if (!cardName) return;
        beginPendingHandCast(card, handIndex);
        cardEl.classList.add("casting-card");

        if (cardRequiresTargetLand(card)) {
          startCastLandTargetPrompt(card);
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

  return cardEl;
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

function renderZoneCards(containerId, cards) {
  const container = q(containerId);
  container.innerHTML = "";
  if (!cards || cards.length === 0) return;
  for (const card of cards) {
    container.appendChild(createCardElement(card, { compact: true }));
  }
}

function renderMana(containerId, manaPool) {
  const container = q(containerId);
  container.innerHTML = "";
  const pool = manaPool || {};
  for (const symbol of MANA_ORDER) {
    const chip = document.createElement("div");
    chip.className = `mana-symbol mana-${symbol}`;
    const count = Number(pool[symbol] || 0);
    const src = symbolSrc(`{${symbol}}`);
    if (src) {
      chip.innerHTML = `<span><img class="mtg-symbol mtg-symbol-mana" src="${escapeHtml(src)}" alt="{${symbol}}" title="{${symbol}}" /> ${count}</span>`;
    } else {
      chip.innerHTML = `<span>${symbol === "C" ? "GEN" : symbol} ${count}</span>`;
    }
    container.appendChild(chip);
  }
}

function renderPhaseRail(state) {
  const container = q("phaseRail");
  if (!container) return;

  container.innerHTML = "";
  const activeKey = getActiveStepKey(state);
  for (const phase of PHASE_RAIL) {
    const item = document.createElement("div");
    item.className = "phase-chip-item";
    item.textContent = phase.label;
    item.dataset.phase = phase.key;
    const isDisabled = disabledPhases.has(phase.key);
    item.title = isDisabled ? `${phase.title} (auto-pass — click to enable)` : `${phase.title} (click to disable)`;
    item.classList.toggle("phase-disabled", isDisabled);
    if (activeKey === phase.key) {
      item.classList.add("active");
      item.setAttribute("aria-current", "step");
    }
    item.addEventListener("click", () => {
      if (disabledPhases.has(phase.key)) {
        disabledPhases.delete(phase.key);
      } else {
        disabledPhases.add(phase.key);
        autoPassDisabledPhaseRequestedStateKey = "";
        maybeAutoPassDisabledPhase();
      }
      renderPhaseRail(currentState);
    });
    container.appendChild(item);
  }
}

function renderStack(stack) {
  if (!stack || stack.length === 0) {
    q("stackZone").textContent = "Stack: empty";
    return;
  }
  const lines = stack.map((item) => {
    const cardName = item.label || item.card?.name || "Unknown";
    const caster = item.caster_name || `Seat ${item.caster_index}`;
    if (item.target_player_name) {
      return `${cardName} by ${caster} targeting ${item.target_player_name}`;
    }
    return `${cardName} by ${caster}`;
  });
  q("stackZone").innerHTML = `Stack:<br>${lines.map((line) => renderSymbolsInline(line)).join("<br>")}`;
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
  if (!inCombat) {
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

  if (isCombatStep(state, "combat_damage") && seat === state.current_turn && !combat?.damage_resolved) {
    const byAttacker = {};
    for (const pair of blockers) {
      const attackerIndex = Number(pair.attacker_index);
      if (!byAttacker[attackerIndex]) {
        byAttacker[attackerIndex] = [];
      }
      byAttacker[attackerIndex].push(Number(pair.blocker_index));
    }

    // Only show manual assignment UI when an attacker is blocked by 2+ creatures.
    const multiBlockedEntries = Object.entries(byAttacker).filter(([, bl]) => bl.length >= 2);
    if (multiBlockedEntries.length === 0) return;

    for (const [attackerIndexRaw, blockerIndices] of multiBlockedEntries) {
      const attackerIndex = Number(attackerIndexRaw);
      const row = document.createElement("div");
      row.className = "combat-damage-row";
      const label = document.createElement("div");
      label.textContent = `Attacker ${attackerIndex} assigns damage`;
      const inputs = document.createElement("div");
      inputs.className = "combat-damage-inputs";
      for (const blockerIndex of blockerIndices) {
        const wrapper = document.createElement("label");
        wrapper.textContent = `B${blockerIndex}`;
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.value = String(
          Number(combatDamageDraft?.[attackerIndex]?.[blockerIndex] ?? 0),
        );
        input.dataset.attackerIndex = String(attackerIndex);
        input.dataset.blockerIndex = String(blockerIndex);
        input.addEventListener("change", () => {
          const a = Number(input.dataset.attackerIndex);
          const b = Number(input.dataset.blockerIndex);
          if (!combatDamageDraft[a]) {
            combatDamageDraft[a] = {};
          }
          combatDamageDraft[a][b] = Math.max(0, Number(input.value || 0));
        });
        wrapper.appendChild(input);
        inputs.appendChild(wrapper);
      }
      row.appendChild(label);
      row.appendChild(inputs);
      damagePanel.appendChild(row);
    }

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.textContent = "Assign Combat Damage";
    submitBtn.addEventListener("click", async () => {
      try {
        await sendAction({ seat, action: "assign_combat_damage", attacker_damage: combatDamageDraft });
        updateActionHint("Combat damage resolved.");
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
    actions.appendChild(submitBtn);

  }
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
}

function renderBoard(state) {
  const viewerSeat = seat ?? 0;
  const oppSeat = viewerSeat === 0 ? 1 : 0;
  const me = state.players[viewerSeat];
  const opp = state.players[oppSeat];
  const combat = getCombatState(state);

  q("selfName").textContent = me.name;
  q("selfName").dataset.targetSeat = String(viewerSeat);
  renderLifePill("selfLife", viewerSeat, me.life);
  q("selfLife").dataset.targetSeat = String(viewerSeat);
  q("oppName").textContent = opp.name;
  q("oppName").dataset.targetSeat = String(oppSeat);
  renderLifePill("oppLife", oppSeat, opp.life);
  q("oppLife").dataset.targetSeat = String(oppSeat);

  const isSelfTurn = state.current_turn === viewerSeat;
  const hasPriority = seat !== null && state.priority_player === seat;
  const canEndTurn = seat !== null && isSelfTurn && !isOpponentMidAction(state, viewerSeat);
  const cleanupDiscard = getCleanupDiscardInfo(state);
  const requiresCleanupSelection = !!cleanupDiscard;
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
  q("holdPriorityBtn").classList.toggle("toggle-btn-active", holdPriorityActive);
  selfHeader?.classList.toggle("turn-zone-self", isSelfTurn);
  oppHeader?.classList.toggle("turn-zone-opponent", !isSelfTurn);
  q("selfName").classList.toggle("active-turn-name", isSelfTurn);
  q("oppName").classList.toggle("opponent-turn-name", !isSelfTurn);

  renderCardRow("selfHand", me.hand, {
    draggable: !requiresCleanupSelection,
    dragKind: "hand",
    zoneKind: "hand",
    targetSeat: viewerSeat,
    castOnClick: true,
    cleanupSelectable: requiresCleanupSelection,
    selectedHandIndices: cleanupDiscard?.selected_indices || [],
  });
  renderCardRow("oppHand", opp.hand, { compact: true, zoneKind: "hand", targetSeat: oppSeat });

  // Canvas battlefield update
  if (battlefieldCanvas) {
    battlefieldCanvas.updateState(state, viewerSeat);

    // Compute selected permanent keys for the canvas
    const selfSelectedKeys = [];
    const allSelectedKeys = [];
    if (untapInfo && seat === viewerSeat) {
      for (const idx of (untapInfo.selected_indices || [])) selfSelectedKeys.push(`${viewerSeat}-${idx}`);
    } else if (isCombatStep(state, "declare_attackers") && seat === state.current_turn && seat === viewerSeat) {
      for (const idx of combatAttackerDraft) selfSelectedKeys.push(`${viewerSeat}-${idx}`);
    } else if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index && seat === viewerSeat) {
      for (const idx of Object.keys(combatBlockerDraft)) selfSelectedKeys.push(`${viewerSeat}-${Number(idx)}`);
      // Highlight targeted attackers on opponent side
      if (seat !== oppSeat) {
        for (const idx of Object.values(combatBlockerDraft)) allSelectedKeys.push(`${oppSeat}-${Number(idx)}`);
      }
    }
    battlefieldCanvas.setSelectedKeys([...selfSelectedKeys, ...allSelectedKeys]);
  }

  q("selfDeckCount").textContent = `Deck: ${me.library_count}`;
  q("selfGraveCount").textContent = `Graveyard: ${me.graveyard.length}`;
  q("selfExileCount").textContent = `Exile: ${(me.exile || []).length}`;
  q("oppDeckCount").textContent = `Deck: ${opp.library_count}`;
  q("oppGraveCount").textContent = `Graveyard: ${opp.graveyard.length}`;
  q("oppExileCount").textContent = `Exile: ${(opp.exile || []).length}`;

  renderZoneCards("selfGraveyardCards", me.graveyard);
  renderZoneCards("selfExileCards", me.exile || []);
  renderZoneCards("oppGraveyardCards", opp.graveyard);
  renderZoneCards("oppExileCards", opp.exile || []);

  renderMana("selfMana", me.mana_pool);
  renderMana("oppMana", opp.mana_pool);
  renderPhaseRail(state);
  if (aiControlsEl) {
    aiControlsEl.classList.toggle("hidden", !shouldShowAiControls(state));
  }
  renderCombatControls(state);
  renderStack(state.stack);
  renderLog(state);
  renderCombatOverlay(state);
  q("rawState").textContent = JSON.stringify(state, null, 2);

  if (requiresCleanupSelection) {
    const remaining = Math.max(0, Number(cleanupDiscard.required_count || 0) - Number(cleanupDiscard.selected_count || 0));
    updateActionHint(`Cleanup: select ${remaining} more card(s) to discard.`);
  }
}

function renderState(state) {
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

  currentState = state;
  syncJoinUrlVisibility(state);
  syncCombatDrafts(state);
  if (!isCombatStep(state, "combat_damage")) {
    combatDamageDraft = {};
  }
  const cleanupInfo = getCleanupDiscardInfo(state);
  const untapInfo = getUntapLandSelectionInfo(state);
  const upkeepPayInfo = getUpkeepPayInfo(state);
  const searchLibraryInfo = getSearchLibraryInfo(state);
  if (cleanupInfo || untapInfo || upkeepPayInfo) {
    pendingActivation = null;
    pendingCastTarget = null;
    pendingCastX = null;
    clearPendingHandCast();
    pendingManaColor = null;
  }
  if (sessionId !== null) {
    hideSetupPanel();
  }
  renderBoard(state);
  renderActivationPrompt();
  renderSearchLibraryModal(searchLibraryInfo);
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
  }

  maybeAutoStepAi(state);
  maybeAutoPassUntilTurnEnd(state);
  maybeAutoPassDisabledPhase(state);
  maybeAutoPassPriority(state);
}

function handleCanvasCardContextMenu({ seat: targetSeat, idx: permanentIndex, card, event }) {
  if (!currentState) return;
  const combat = getCombatState(currentState);
  if (!combat) return;

  try {
    if (
      isCombatStep(currentState, "declare_attackers") &&
      seat === currentState.current_turn &&
      targetSeat === seat &&
      !combat?.attackers_locked
    ) {
      combatAttackerDraft = combatAttackerDraft.filter((idx) => idx !== permanentIndex);
      renderBoard(currentState);
      updateActionHint("Removed attacker from draft selection.");
      return;
    }

    if (
      isCombatStep(currentState, "declare_blockers") &&
      seat === combat.defending_player_index &&
      !combat?.blockers_locked
    ) {
      if (targetSeat === combat.defending_player_index) {
        delete combatBlockerDraft[permanentIndex];
      }
      if (targetSeat === currentState.current_turn) {
        for (const [blockerIdx, attackerIdx] of Object.entries(combatBlockerDraft)) {
          if (Number(attackerIdx) === permanentIndex) {
            delete combatBlockerDraft[Number(blockerIdx)];
          }
        }
      }
      renderBoard(currentState);
      updateActionHint("Removed blocker target link from draft.");
    }
  } catch (e) {
    updateActionHint(e.message, true);
  }
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
  const payload = parseDragPayload(event);
  if (!payload) {
    updateActionHint("Could not read dropped card data.", true);
    return;
  }

  try {
    if (payload.kind === "hand") {
      const card = findCardInCurrentHand(payload.name);
      beginPendingHandCast(card || payload.name, Number.isInteger(payload.handIndex) ? payload.handIndex : null);
      if (card && cardRequiresTargetLand(card)) { startCastLandTargetPrompt(card); return; }
      if (card && cardRequiresTargetCreature(card)) { startCastCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetPermanent(card)) { startCastPermanentTargetPrompt(card); return; }
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
        combatBlockerDraft[Number(payload.permanentIndex)] = targetItem.idx;
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

        if (
          isCombatStep(currentState, "declare_attackers") &&
          seat === currentState.current_turn &&
          cardSeat === seat
        ) {
          if (!isCardLikelyAttacker(card)) {
            updateActionHint(`${card.name} is not able to attack right now.`, true);
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
          resolvePendingCastTarget(cardSeat, permanentIndex);
          return;
        }

        if (!hasActivatedAbility(card)) {
          updateActionHint(`${card.name} has no activated ability to use.`, true);
          return;
        }

        // Tap entire stack: if card is in a multi-card stack and has a simple
        // auto-activating ability (no interactive cost prompt), also activate all
        // other stack members with tap abilities.
        if (
          battlefieldCanvas &&
          !cardRequiresManaColorChoice(card) &&
          !shouldPromptForActivationCost(getActivatedAbilityCost(card))
        ) {
          const stackMembers = battlefieldCanvas.getStackMembers(cardSeat, permanentIndex);
          if (stackMembers.length > 1) {
            for (const member of stackMembers) {
              const memberCard = currentState.players?.[member.seat]?.battlefield?.[member.idx];
              if (!memberCard) continue;
              startActivationPrompt(memberCard, 1 - seat, member.idx);
            }
            return;
          }
        }

        startActivationPrompt(card, 1 - seat, permanentIndex);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    },

    onCardContextMenu(info) {
      handleCanvasCardContextMenu(info);
    },

    onCardHover(info) {
      if (!info) return;
      showCardPreview(info.card);
    },

    onHandCardDrop(info) {
      handleHandCardDropOnBattlefield(info).catch((e) => updateActionHint(e.message, true));
    },

    onBlockerAssign({ blockerIdx, attackerIdx }) {
      const combat = getCombatState(currentState);
      if (!combat || combat.blockers_locked) {
        updateActionHint("Blockers are already confirmed.", true);
        return;
      }
      combatBlockerDraft[blockerIdx] = attackerIdx;
      renderBoard(currentState);
      updateActionHint("Blocker assigned. Press OK when done.");
    },

    onPermanentDrop() {
      if (!battlefieldCanvas || !Number.isInteger(seat)) return;
      const positions = {};
      for (const item of battlefieldCanvas.cardItems) {
        if (item.seat === seat) {
          positions[item.key] = { x: item.x, y: item.y };
        }
      }
      postJson(`/api/sessions/${sessionId}/card-positions`, { seat, positions }).catch(() => {});
    },
  });
}

function initTabs() {
  q("logTabBtn").addEventListener("click", () => {
    q("logTabBtn").classList.add("active");
    q("rawTabBtn").classList.remove("active");
    q("logTab").classList.remove("hidden");
    q("rawTab").classList.add("hidden");
  });

  q("rawTabBtn").addEventListener("click", () => {
    q("rawTabBtn").classList.add("active");
    q("logTabBtn").classList.remove("active");
    q("rawTab").classList.remove("hidden");
    q("logTab").classList.add("hidden");
  });
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
}

async function getState() {
  if (!sessionId) return;
  const params = new URLSearchParams();
  if (Number.isInteger(seat)) {
    params.set("seat", String(seat));
  }
  const query = params.toString();
  const url = query ? `/api/sessions/${sessionId}/state?${query}` : `/api/sessions/${sessionId}/state`;
  const resp = await fetch(url);
  if (resp.status === 404) {
    resetToSetup();
    return;
  }
  if (!resp.ok) return;
  const state = await resp.json();
  renderState(state);
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

async function createSession() {
  hideSetupPanel();
  syncGuestNameForMode();
  syncSeedControls();
  const useCustomSeed = q("useCustomSeed").checked;
  const req = {
    mode: q("mode").value,
    host_name: q("hostName").value,
    guest_name: q("guestName").value,
    host_colors: Number(q("hostColors").value),
    guest_colors: Number(q("guestColors").value),
    use_custom_seed: useCustomSeed,
    custom_seed: useCustomSeed ? Number(q("customSeed").value) : null,
  };
  const data = await postJson("/api/sessions", req);
  sessionId = data.session_id;
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  updateActionHint("Session ready. Drag from your hand to cast, or drag cards on the battlefield to reposition.");
}

function syncGuestNameForMode() {
  const mode = q("mode").value;
  const guestNameInput = q("guestName");
  const guestName = guestNameInput.value.trim();

  if (mode === "human_vs_ai" || mode === "ai_vs_ai") {
    if (guestName === "" || guestName === "Player 2") {
      guestNameInput.value = "AI";
    }
    return;
  }

  if (mode === "human_vs_human" && (guestName === "" || guestName === "AI")) {
    guestNameInput.value = "Player 2";
  }
}

async function joinSession() {
  sessionId = q("joinSessionId").value.trim();
  if (!sessionId) {
    alert("Enter a session ID");
    return;
  }
  const data = await postJson(`/api/sessions/${sessionId}/join`, { guest_name: q("joinName").value });
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  updateActionHint("Joined. Drag from your hand to play, or drag cards on the battlefield to reposition.");
}

async function sendAction(actionBody) {
  if (!sessionId) return;
  const payload = await postJson(`/api/sessions/${sessionId}/action`, actionBody);
  renderState(payload);
}

q("startBtn").addEventListener("click", async () => {
  try {
    hideSetupPanel();
    await createSession();
  } catch (e) {
    showSetupPanel();
    alert(e.message);
  }
});

q("mode").addEventListener("change", () => {
  syncGuestNameForMode();
});

q("useCustomSeed").addEventListener("change", () => {
  syncSeedControls();
});

q("joinBtn").addEventListener("click", async () => {
  try {
    await joinSession();
  } catch (e) {
    alert(e.message);
  }
});

for (const elementId of ["selfName", "oppName", "selfLife", "oppLife"]) {
  q(elementId)?.addEventListener("click", (event) => {
    if (!pendingCastTarget || pendingCastTarget.targetKind !== "player") return;
    const source = event.currentTarget;
    if (!(source instanceof HTMLElement)) return;
    const targetSeat = Number(source.dataset.targetSeat);
    if (!Number.isInteger(targetSeat)) return;
    event.preventDefault();
    handlePlayerTargetClick(targetSeat);
  });
}

for (const [element, label] of [[joinUrlEl, "Join URL"], [lanJoinUrlEl, "LAN join URL"]]) {
  element?.addEventListener("click", async () => {
    const targetUrl = element.dataset.url;
    if (!targetUrl) return;
    try {
      await copyTextToClipboard(targetUrl);
      updateActionHint(`${label} copied to clipboard.`);
    } catch {
      updateActionHint(`Could not copy ${label.toLowerCase()}. Copy it manually.`, true);
    }
  });
}

q("promptCancelBtn").addEventListener("click", () => {
  pendingActivation = null;
  pendingCastTarget = null;
  pendingCastX = null;
  pendingManaColor = null;
  pendingAutoTap = null;
  clearPendingHandCast();
  renderActivationPrompt();
  updateActionHint("Prompt canceled.");
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
  resolvePendingCastX();
});

q("promptSteps").addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

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

  const manaColorChoice = target.dataset.manaColor;
  if (manaColorChoice && pendingManaColor) {
    resolvePendingManaColor(manaColorChoice);
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
  if (!sessionId) return;
  try {
    const url = seat !== null
      ? `/api/sessions/${sessionId}/undo?seat=${seat}`
      : `/api/sessions/${sessionId}/undo`;
    const resp = await fetch(url, { method: "POST" });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "undo failed");
    renderState(payload);
    updateActionHint("Undone.");
  } catch (e) {
    alert(e.message);
  }
});

q("holdPriorityBtn").addEventListener("click", () => {
  holdPriorityActive = !holdPriorityActive;
  q("holdPriorityBtn").classList.toggle("toggle-btn-active", holdPriorityActive);
  if (!holdPriorityActive) {
    autoPassPriorityRequestedStateKey = "";
    autoPassDisabledPhaseRequestedStateKey = "";
    maybeAutoPassPriority(currentState);
    maybeAutoPassDisabledPhase(currentState);
  }
  updateActionHint(holdPriorityActive ? "Hold Priority on: priority will not auto-pass." : "Hold Priority off: priority will pass automatically.");
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

q("debugCastFreeBtn").addEventListener("click", async () => {
  try {
    await castDebugCardForFree();
  } catch (e) {
    updateDebugStatus(e.message, "error");
  }
});

const params = new URLSearchParams(window.location.search);
const sessionFromUrl = params.get("session");
setSetupModeForUrlSession(Boolean(sessionFromUrl));
if (sessionFromUrl) {
  q("joinSessionId").value = sessionFromUrl;
}

syncGuestNameForMode();
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
clearCardPreview();
