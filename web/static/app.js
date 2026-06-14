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
let debugAddManaMode = false;
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
// Phases toggled OFF will be auto-passed. Default: only M1, AT, M2 are ON.
const disabledPhases = new Set([
  "untap", "upkeep", "draw",
  "beginning_of_combat", "declare_blockers", "combat_damage", "end_of_combat",
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
/** @type {BattlefieldCanvas|null} */
let battlefieldCanvas = null;
let lastAnnouncedTurn = null;

const setupEl = document.getElementById("setup");
const boardEl = document.getElementById("boardPanel");
const aiControlsEl = document.getElementById("aiControls");
// Join URLs for the current hosted session. Surfaced in the "Waiting for
// Opponent" prompt rather than at the top of the page.
let currentJoinUrl = "";
let currentLanJoinUrl = "";
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
    SFX.onLifeChange(numericSeat, previousLife, numericLife, seat ?? 0);
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
  if (card.summoning_sick) return false;
  return String(card.type || "").toLowerCase().includes("creature") && !card.tapped;
}

function canCardAttackDefenderFromPublicState(card, defenderBattlefield) {
  if (!isCardLikelyAttacker(card)) return false;

  const text = String(card.oracle_text || "").toLowerCase();
  const hasDefender = text.includes("defender");
  const canIgnoreDefender = text.includes("can attack as though it didn't have defender");
  if (hasDefender && !canIgnoreDefender) return false;

  // Filter activated-ability lines before checking static restrictions
  const nonActivatedLines = (card.oracle_text || "").split("\n")
    .filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line))
    .map((line) => line.toLowerCase());
  if (nonActivatedLines.some((line) => line.includes("can't attack"))) return false;

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

function cardHasKeyword(card, keyword) {
  return String(card?.oracle_text || "").toLowerCase().includes(keyword);
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

function showMenuPage(name) {
  for (const [key, element] of Object.entries(menuPages)) {
    if (!element) continue;
    element.classList.toggle("hidden", key !== name);
    element.hidden = key !== name;
  }
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
  source.addEventListener("state", (event) => {
    let skipStale = false;
    // A rematch rebuilds the game with a fresh (shorter) log, so the monotonic-log
    // stale guard would wrongly discard it — bypass the guard for those resets too.
    try {
      const reason = JSON.parse(event.data)?.reason;
      if (reason === "undo" || reason === "rematch_start") skipStale = true;
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

function isStackHoverHolding() {
  return stackCanvasHoverActive || !!document.querySelector("#stackZone .stack-item:hover");
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
  const lines = (card.oracle_text || "").split("\n");
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => line.toLowerCase().includes("target player"));
}

function cardRequiresTargetLand(card) {
  if (!card || typeof card === "string") return false;
  const lines = (card.oracle_text || "").split("\n");
  // Exclude activated ability lines (format: "{cost}: effect") — those trigger on activation, not cast
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => {
    const t = line.toLowerCase();
    return t.includes("target land") || t.includes("enchant land");
  });
}

function cardRequiresTargetGraveyardCreature(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  // Animate Dead and similar reanimation Auras enchant a creature card in a
  // graveyard, chosen as the spell's target when it is cast (Rule 601.2c).
  return text.includes("enchant creature card in a graveyard");
}

function getTargetableGraveyardCreatures(state = currentState) {
  if (!state) return [];
  const result = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.graveyard)) continue;
    player.graveyard.forEach((card, index) => {
      if (String(card.type || "").toLowerCase().includes("creature")) {
        result.push({ targetSeat, index, cardName: card.name || "Creature" });
      }
    });
  }
  return result;
}

function startCastGraveyardCreatureTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;
  if (getTargetableGraveyardCreatures().length === 0) {
    clearPendingHandCast();
    updateActionHint(`No creature cards in any graveyard for ${cardName}.`, true);
    return;
  }
  pendingCastTarget = { card, cardName, targetKind: "graveyard_creature", castAction };
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(`Choose a creature card in a graveyard to reanimate with ${cardName}.`);
}

function cardRequiresTargetCreature(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  if (text.includes("enchant creature card in a graveyard")) return false;
  const lines = (card.oracle_text || "").split("\n");
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => {
    const t = line.toLowerCase();
    // "target creature card" refers to a graveyard card (Raise Dead, Resurrection),
    // not a battlefield creature — not a battlefield target prompt.
    if (t.includes("target creature card")) return false;
    if (t.includes("enchant creature") || t.includes("enchant wall")) return true;
    // Spells that destroy a target creature (incl. Walls): Terror, Tunnel, etc.
    if (t.includes("destroy target") && (/\bcreature\b/.test(t) || /\bwall\b/.test(t))) return true;
    // Pumps/keyword grants (Berserk, Giant Growth, Jump, Howl from Beyond).
    if (t.includes("target creature gets") || t.includes("target creature gains")) return true;
    // Direct damage to a target creature (Simulacrum).
    if (t.includes("damage to target creature")) return true;
    return false;
  });
}

// Clone-style permanents that may "enter as a copy of any creature on the
// battlefield". The copy is optional, so it's only a prompt when a creature
// exists to copy; otherwise the spell is cast as-is.
function cardOffersCopyCreatureChoice(card) {
  if (!card || typeof card === "string") return false;
  return (card.oracle_text || "")
    .toLowerCase()
    .includes("enter as a copy of any creature on the battlefield");
}

function cardRequiresTargetPermanent(card) {
  if (!card || typeof card === "string") return false;
  const lines = (card.oracle_text || "").split("\n");
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => {
    const t = line.toLowerCase();
    if (t.includes("target spell or permanent")) return true;
    if (t.includes("target permanent") && !t.includes("target land") && !t.includes("target creature")) return true;
    // Disenchant: "Destroy target artifact or enchantment" — either type, either side.
    if (t.includes("destroy target artifact or enchantment")) return true;
    // Power Leak: an Aura that enchants an enchantment (chosen on cast).
    if (t.includes("enchant enchantment")) return true;
    return false;
  });
}

function cardRequiresTargetArtifact(card) {
  if (!card || typeof card === "string") return false;
  const lines = (card.oracle_text || "").split("\n");
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => line.toLowerCase().includes("enchant artifact"));
}

function cardRequiresTargetAny(card) {
  if (!card || typeof card === "string") return false;
  const lines = (card.oracle_text || "").split("\n");
  // Exclude activated ability lines (format: "{cost}: effect") — those trigger on activation, not cast
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => line.toLowerCase().includes("any target"));
}

// Spells that target another spell on the stack (Counterspell, Fork, the colored
// Blasts, Spell Blast). The player chooses which spell on the stack to target.
function cardRequiresTargetStackSpell(card) {
  if (!card || typeof card === "string") return false;
  const lines = (card.oracle_text || "").split("\n");
  const nonActivatedLines = lines.filter((line) => !/^\s*(\{[^}]+\})+\s*:/.test(line));
  return nonActivatedLines.some((line) => {
    const t = line.toLowerCase();
    return t.includes("counter target") || (t.includes("copy target") && t.includes("spell"));
  });
}

// Color word the spell-target prompt is restricted to (Blue/Red Elemental Blast),
// or null when any spell is a legal target.
function stackSpellTargetColorFilter(card) {
  const text = (card.oracle_text || "").toLowerCase();
  const m = text.match(/counter target (\w+) spell/);
  if (!m) return null;
  return { blue: "U", red: "R", black: "B", green: "G", white: "W" }[m[1]] || null;
}

// True when the spell can only copy instants/sorceries (Fork).
function stackSpellTargetInstantSorceryOnly(card) {
  return (card.oracle_text || "").toLowerCase().includes("copy target instant or sorcery spell");
}

// Whether a serialized stack item is a legal target for the in-progress
// spell-target cast prompt.
function isStackItemValidCastTarget(item) {
  if (!item || !pendingCastTarget || pendingCastTarget.targetKind !== "stack") return false;
  if (item.type !== "spell") return false;  // only spells, not activated/triggered abilities
  const card = pendingCastTarget.card;
  const cardType = String(item.card?.type || "").toLowerCase();
  if (stackSpellTargetInstantSorceryOnly(card) &&
      !(cardType.includes("instant") || cardType.includes("sorcery"))) {
    return false;
  }
  const colorFilter = stackSpellTargetColorFilter(card);
  if (colorFilter) {
    const colors = (item.card?.colors || []).map((c) => String(c).toUpperCase());
    // Fall back to a color-identity check if explicit colors aren't serialized.
    if (!colors.includes(colorFilter)) return false;
  }
  return true;
}

// Battlefield permanents that are legal targets for the in-progress cast prompt,
// returned as "seat-permanentIndex" canvas keys. Covers every battlefield target
// kind (creature/land/artifact/permanent/any) so the canvas can highlight them —
// e.g. Control Magic ("Enchant creature") highlights every creature. Player-only
// targets are highlighted on the life/name elements instead, not here.
function getTargetablePermanentKeysForPrompt(state = currentState) {
  if (!state || !pendingCastTarget) return [];
  if (pendingCastTarget.targetKind === "player") return [];
  const keys = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.battlefield)) continue;
    for (const [permanentIndex, permanent] of player.battlefield.entries()) {
      if (!permanent) continue;
      if (isPendingCastTargetValidForCard(permanent, { targetSeat, zoneKind: "battlefield", permanentIndex })) {
        keys.push(`${targetSeat}-${permanentIndex}`);
      }
    }
  }
  return keys;
}

function activatedAbilityTargetsSelf(card) {
  if (!card || typeof card === "string") return false;
  // Abilities that grant keywords/buffs to "target creature" refer to the controller's
  // own creatures (e.g. Helm of Chatzuk: "Target creature gains banding until end of turn").
  const activatedLines = (card.oracle_text || "").split("\n")
    .filter((line) => /^\s*(\{[^}]+\})+\s*:/.test(line))
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

function activatedAbilityRequiresTargetLand(card) {
  if (!card || typeof card === "string") return false;
  // Activated-ability lines (format: "{cost}: effect") that act on a target land,
  // e.g. Gaea's Liege: "{T}: Target land becomes a Forest...".
  const activatedLines = (card.oracle_text || "").split("\n")
    .filter((line) => /^\s*(\{[^}]+\})+\s*:/.test(line))
    .map((line) => line.toLowerCase());
  return activatedLines.some((line) => line.includes("target land"));
}

function activatedAbilityRequiresTargetCreature(card) {
  if (!card || typeof card === "string") return false;
  // Activated-ability lines that destroy a target creature, e.g. Royal Assassin:
  // "{T}: Destroy target tapped creature." The player must pick which creature.
  const activatedLines = (card.oracle_text || "").split("\n")
    .filter((line) => /^\s*(\{[^}]+\})+\s*:/.test(line))
    .map((line) => line.toLowerCase());
  return activatedLines.some(
    (line) => line.includes("destroy target") && (/\bcreature\b/.test(line) || /\bwall\b/.test(line)),
  );
}

function cardRequiresManaColorChoice(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  return text.includes("any one color") || text.includes("one mana of any color");
}

function cardRequiresCastColorChoice(card) {
  if (!card || typeof card === "string") return false;
  const text = (card.oracle_text || "").toLowerCase();
  return text.includes("replacing all instances of one color word with another");
}

function getDualLandColors(card) {
  if (!card || typeof card === "string") return null;
  const produced = Array.isArray(card.produced_mana) ? card.produced_mana.map((s) => s.toUpperCase()) : [];
  return produced.length >= 2 ? produced : null;
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

function getReorderLibraryInfo(state = currentState) {
  if (!state || seat === null) return null;
  const info = state.reorder_library;
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

function getOpponentDefaultTargetSeat(cardName) {
  // Default target when the spell is being cast on the opponent's behalf.
  if (seat === null) return 0;
  const opponentSeat = 1 - seat;
  if (["Ancestral Recall", "Healing Salve", "Stream of Life"].includes(cardName)) {
    return opponentSeat;
  }
  return seat;
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

function getTargetableArtifactsForPrompt(state = currentState) {
  if (!state) return [];
  const result = [];
  for (const targetSeat of [0, 1]) {
    const player = state.players?.[targetSeat];
    if (!player || !Array.isArray(player.battlefield)) continue;
    for (const [permanentIndex, permanent] of player.battlefield.entries()) {
      if (!permanent || !String(permanent.type || "").toLowerCase().includes("artifact")) continue;
      result.push({ targetSeat, permanentIndex, cardName: permanent.name || "Artifact", ownerName: player.name || `Seat ${targetSeat}` });
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

  if (pendingCastTarget.targetKind === "artifact") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    if (!card || typeof card === "string") return false;
    return String(card.type || "").toLowerCase().includes("artifact");
  }

  if (pendingCastTarget.targetKind === "permanent") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    return true;
  }

  if (pendingCastTarget.targetKind === "any") {
    if (zoneKind !== "battlefield") return false;
    if (!Number.isInteger(permanentIndex)) return false;
    if (!card || typeof card === "string") return false;
    const type = String(card.type || "").toLowerCase();
    return type.includes("creature") || type.includes("planeswalker");
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
  if (pendingActivation || pendingCastTarget || pendingCastX || pendingManaColor) return false;
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

function applyAwaitingOpponentPrompt() {
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

  title.textContent = "Waiting for Opponent";
  const linkUrl = currentLanJoinUrl || currentJoinUrl;
  const joinLink = linkUrl
    ? `<a href="${escapeHtml(linkUrl)}" id="awaitingJoinLink" class="join-url-link" title="Click to copy">Join URL</a>`
    : "Join URL";
  body.innerHTML = `Send the ${joinLink} to a friend. The game will begin once they join.`;
  steps.innerHTML = `<div>Waiting for an opponent to join…</div>`;

  const linkEl = document.getElementById("awaitingJoinLink");
  if (linkEl) {
    linkEl.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        await copyTextToClipboard(linkUrl);
        updateActionHint("Join URL copied to clipboard.");
      } catch {
        updateActionHint("Could not copy the Join URL. Copy it manually.", true);
      }
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

  if (info.is_my_turn) {
    title.textContent = "You won the coin flip!";
    body.textContent = `${escapeHtml(info.winner_name || "You")} won the coin flip. Do you want to go first or second?`;
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
    title.textContent = "Coin Flip";
    body.textContent = `${escapeHtml(info.winner_name || "Opponent")} won the coin flip and is choosing who goes first.`;
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
    title.textContent = "Waiting for Mulligan Decision";
    body.textContent = `${escapeHtml(info.waiting_for || "Opponent")} is deciding whether to mulligan.`;
    steps.innerHTML = `<div>Waiting for ${escapeHtml(info.waiting_for || "opponent")}...</div>`;
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
    const selectedSet = new Set(info.selected_indices || []);
    const hand = getCurrentPlayerState()?.hand || [];

    title.textContent = `Put ${required} Card${required !== 1 ? "s" : ""} on the Bottom`;
    body.textContent = `You took ${required} mulligan${required !== 1 ? "s" : ""}. Select ${required} card${required !== 1 ? "s" : ""} to put on the bottom of your library, then click Confirm.`;

    const cardRows = hand.map((card, idx) => {
      const name = typeof card === "string" ? card : (card?.name || "Unknown");
      const isSelected = selectedSet.has(idx);
      return `<div>
        <button type="button" class="prompt-choice-btn${isSelected ? " active" : ""}"
          onclick="sendAction({ seat, action: 'mulligan_bottom_select', hand_index: ${idx} })">
          ${escapeHtml(name)}${isSelected ? " ✓" : ""}
        </button>
      </div>`;
    }).join("");
    steps.innerHTML = `<div style="margin-bottom:4px">Selected: ${selectedCount} / ${required}</div>${cardRows}`;

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

  if (currentState?.awaiting_opponent) {
    applyAwaitingOpponentPrompt();
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

  const islandSanctuaryInfo = getIslandSanctuaryInfo();
  if (islandSanctuaryInfo) {
    applyIslandSanctuaryPrompt();
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
    cancelBtn.classList.remove("hidden");
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
    cancelBtn.classList.add("hidden");
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
    } else if (pendingCastTarget.targetKind === "artifact") {
      body.textContent = "Click a valid artifact on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "permanent") {
      body.textContent = "Click any permanent on the battlefield to choose the target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "any") {
      body.textContent = "Click a creature on the battlefield, or click a player's life pill (glowing yellow) to target them.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
    } else if (pendingCastTarget.targetKind === "stack") {
      body.textContent = "Click a glowing spell on the stack to choose which one to target.";
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
    cancelBtn.classList.remove("hidden");
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
    cancelBtn.classList.remove("hidden");
    cancelBtn.disabled = false;
    customOkBtn.disabled = !pendingCastX.awaitingCustomValue;
    return;
  }

  if (pendingManaColor) {
    panel.classList.remove("hidden");
    okBtn.classList.add("hidden");
    customRow.classList.add("hidden");
    if (pendingManaColor.kind === "cast") {
      title.textContent = `Choose replacement color for ${pendingManaColor.cardName}`;
      body.textContent = "Select the new color to replace the color word in the target.";
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

  // Activated abilities that destroy a target creature (e.g. Royal Assassin)
  // must let the player choose which creature before the ability is activated.
  if (activatedAbilityRequiresTargetCreature(card)) {
    if (getTargetableCreaturesForPrompt().length === 0) {
      updateActionHint(`No valid creature targets in play for ${cardName}.`, true);
      return;
    }
    pendingCastTarget = {
      card,
      cardName,
      targetKind: "creature",
      castAction: "activate",
      sourcePermanentIndex: permanentIndex,
    };
    renderActivationPrompt();
    updateActionHint(`Choose a creature target for ${cardName}'s ability.`);
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
    updateActionHint(`Choose a mana color for ${cardName}.`);
    return;
  }

  const dualColors = getDualLandColors(card);
  if (dualColors) {
    pendingManaColor = {
      cardName,
      permanentIndex,
      targetSeat,
      oracleText: card.oracle_text || "",
      colorOptions: MANA_COLOR_OPTIONS.filter((o) => dualColors.includes(o.symbol)),
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
  const validOptions = pendingManaColor.colorOptions || MANA_COLOR_OPTIONS;
  if (!validOptions.some((option) => option.symbol === manaColor)) {
    updateActionHint("Invalid mana color choice.", true);
    return;
  }

  const pending = pendingManaColor;
  pendingManaColor = null;
  renderActivationPrompt();

  if (pending.kind === "cast") {
    const actionBody = { ...pending.castActionBody, mana_color: manaColor };
    updateActionHint(`Casting ${pending.cardName} with color ${manaColor}...`);
    sendAction(actionBody)
      .then(() => {
        updateActionHint(`Cast ${pending.cardName} replacing color with ${manaColor}.`);
        clearPendingHandCast();
      })
      .catch((e) => {
        clearPendingHandCast();
        updateActionHint(e.message, true);
      });
    return;
  }

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
    clearPendingHandCast();
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
    clearPendingHandCast();
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
    clearPendingHandCast();
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

function startCastArtifactTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  if (getTargetableArtifactsForPrompt().length === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid artifact targets in play for ${cardName}.`, true);
    return;
  }

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "artifact",
    castAction,
  };
  renderActivationPrompt();
  updateActionHint(`Choose an artifact target for ${cardName}.`);
}

function startCastAnyTargetPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "any",
    castAction,
  };
  renderActivationPrompt();
  renderBoard(currentState);
  updateActionHint(`Choose any target for ${cardName}: click a creature on the battlefield, or click a player's glowing life pill.`);
}

function startCastStackSpellPrompt(card, castAction = "cast") {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
    targetKind: "stack",
    castAction,
  };
  const validCount = (_currentStack || []).filter(isStackItemValidCastTarget).length;
  if (validCount === 0) {
    clearPendingHandCast();
    updateActionHint(`No valid spell on the stack for ${cardName} to target.`, true);
    return;
  }
  renderActivationPrompt();
  renderStack(currentState ? currentState.stack : _currentStack);
  updateActionHint(`Choose a spell on the stack for ${cardName} to target (glowing).`);
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
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
  renderActivationPrompt();

  // Activated ability targeting a permanent (e.g. Gaea's Liege targeting a land):
  // send an "activate" action with the chosen target permanent rather than a cast.
  if (pending.castAction === "activate") {
    updateActionHint(`Activating ${pending.cardName}...`);
    sendAction({
      seat,
      action: "activate",
      permanent_name: pending.cardName,
      permanent_index: pending.sourcePermanentIndex,
      target_seat: selectedTarget,
      target_permanent_index: selectedPermanentIndex,
    })
      .then(() => updateActionHint(`Activated ${pending.cardName}.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

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

  if (cardRequiresCastColorChoice(pending.card)) {
    pendingManaColor = {
      kind: "cast",
      cardName: pending.cardName,
      castActionBody: actionBody,
      oracleText: pending.card.oracle_text || "",
    };
    renderActivationPrompt();
    updateActionHint(`Choose a replacement color for ${pending.cardName}.`);
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
  if (pendingCastTarget.targetKind !== "player" && pendingCastTarget.targetKind !== "any") return;
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

function setJoinUrls(url = "", lanUrl = "") {
  currentJoinUrl = String(url || "").trim();
  currentLanJoinUrl = String(lanUrl || "").trim();
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
  q("debugCastFreeOpponentBtn").disabled = !enabled;
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

  if (card && cardOffersCopyCreatureChoice(card) && getTargetableCreaturesForPrompt().length > 0) {
    startCastCreatureTargetPrompt(card, "debug_cast_free");
    updateDebugStatus(`Choose a creature for ${resolvedCardName} to copy.`, "success");
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

  const card = await fetchCardByName(cardName);
  const resolvedCardName = normalizeCardName(card) || cardName;

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

  if (card && cardOffersCopyCreatureChoice(card) && getTargetableCreaturesForPrompt().length > 0) {
    startCastCreatureTargetPrompt(card, "debug_cast_free_opponent");
    updateDebugStatus(`Choose a creature for ${resolvedCardName} to copy (as opponent).`, "success");
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
    el.textContent = `Verified ${c.pass || 0} passed, ${c.fail || 0} failed, ${c.untested || 0} untested (of ${payload.total || 0}).`;
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
  q("verifyCardName").focus();
  fetchVerifySuggestions(name).catch(() => {
    // Keep silent on open to avoid noisy UI warnings.
  });
}

function closeVerifyResultModal() {
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
  const badge = { pass: "✅", fail: "❌", untested: "⬜" };
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
  q("trackerSummary").textContent = "Loading…";
  try {
    const resp = await fetch("/api/verification");
    if (!resp.ok) throw new Error("failed");
    const payload = await resp.json();
    trackerCards = payload.cards || [];
    const c = payload.counts || {};
    q("trackerSummary").textContent = `${c.pass || 0} passed · ${c.fail || 0} failed · ${c.untested || 0} untested · ${payload.total || 0} total`;
    renderTrackerList();
  } catch (e) {
    q("trackerSummary").textContent = "Could not load the tracker.";
  }
}

function closeTrackerModal() {
  q("trackerModal").classList.add("hidden");
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
  const keywords = typeof card === "object" && Array.isArray(card?.keywords) ? card.keywords : [];
  // Effective keywords reflect the live board (aura grants, pumps, removals), so
  // a creature that gained Flying — or lost it to Earthbind — reads correctly.
  const keywordLabel = keywords.length ? `Keywords: ${keywords.join(", ")}` : "";
  const sicknessLabel = typeof card === "object" && card?.summoning_sick ? "Summoning Sickness" : "";
  setSymbolsHtml(q("cardPreviewText"), [keywordLabel, previewText, sicknessLabel].filter(Boolean).join("\n"));

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
    playable = false,
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

        // Activated abilities that act on a target land (e.g. Gaea's Liege)
        // let the player pick which land in play to affect.
        if (activatedAbilityRequiresTargetLand(card)) {
          if (getTargetableLandsForPrompt().length === 0) {
            updateActionHint(`No valid land targets in play for ${cardName}.`, true);
            return;
          }
          pendingCastTarget = {
            card,
            cardName: normalizeCardName(card),
            targetKind: "land",
            castAction: "activate",
            sourcePermanentIndex: permanentIndex,
          };
          renderActivationPrompt();
          updateActionHint(`Choose a target land for ${cardName}'s ability.`);
          return;
        }

        // Abilities that buff/modify the controller's own creatures target self, not opponent.
        const activationTargetSeat = activatedAbilityTargetsSelf(card) ? seat : 1 - seat;
        startActivationPrompt(card, activationTargetSeat, permanentIndex);
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

      if (pendingCastHandCard && !isPendingHandCastCard(card, handIndex)) {
        updateActionHint("Finish the current cast before starting another.", true);
        return;
      }

      // Second click on the card while the insufficient-mana prompt is open
      // performs the auto-tap, same as pressing the Auto-Tap button.
      if (pendingAutoTap && isPendingHandCastCard(card, handIndex)) {
        const me = getCurrentPlayerState();
        const canSatisfy = !!me && canAutoTapSatisfyCost(
          pendingAutoTap.card.mana_cost || "",
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

        const cardName = normalizeCardName(card);
        if (!cardName) return;
        beginPendingHandCast(card, handIndex);
        cardEl.classList.add("casting-card");

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

        if (cardOffersCopyCreatureChoice(card) && getTargetableCreaturesForPrompt().length > 0) {
          startCastCreatureTargetPrompt(card);
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

  if (!hidden && typeof card === "object" && card.mana_cost) {
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

function renderHandFan(containerId, cards, options = {}) {
  const container = q(containerId);
  container.innerHTML = "";

  const isOpponent = container.classList.contains("hand-fan--opponent");
  const entries = Array.isArray(cards) ? cards : [];
  const count = entries.length;
  const MAX_ANGLE = 15;
  const MAX_RISE = isOpponent ? 22 : 44;
  const PUSH_X = isOpponent ? 7 : 14;
  const { playableHandIndices = [], ...fanOptions } = options;

  const slots = [];

  entries.forEach((card, index) => {
    const normalizedPos = count <= 1 ? 0 : (index / (count - 1)) * 2 - 1;
    const angle = normalizedPos * MAX_ANGLE * (isOpponent ? -1 : 1);
    // Both hands: center card most prominent (1-pos² parabola).
    const rise = (1 - normalizedPos * normalizedPos) * MAX_RISE;

    const isHidden = card === "<hidden>";
    const cardEl = createCardElement(isHidden ? "Hidden" : card, {
      ...fanOptions,
      compact: false,
      hidden: isHidden,
      handIndex: index,
      playable: !isHidden && playableHandIndices.includes(index),
    });

    const slot = document.createElement("div");
    slot.className = "hand-fan-slot";
    slot.style.setProperty("--fan-angle", `${angle}deg`);
    slot.style.setProperty("--fan-push-x", "0px");
    slot.style.setProperty("--fan-z", `${index * 5}px`);
    slot.style.zIndex = String(index + 1);
    if (isOpponent) {
      slot.style.marginTop = `${rise}px`;
    } else {
      slot.style.marginBottom = `${rise}px`;
    }
    slot.appendChild(cardEl);

    container.appendChild(slot);
    slots.push(slot);
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

function renderZoneCards(containerId, cards, { zoneSeat = null, zoneKind = "" } = {}) {
  const container = q(containerId);
  container.innerHTML = "";
  if (!cards || cards.length === 0) return;
  const graveyardTargeting =
    pendingCastTarget &&
    pendingCastTarget.targetKind === "graveyard_creature" &&
    zoneKind === "graveyard" &&
    Number.isInteger(zoneSeat);
  for (const [index, card] of cards.entries()) {
    const el = createCardElement(card, { compact: true });
    if (graveyardTargeting && String(card.type || "").toLowerCase().includes("creature")) {
      el.classList.add("targeting-valid");
      el.style.cursor = "pointer";
      el.addEventListener("click", () => resolvePendingCastTarget(zoneSeat, index));
    }
    container.appendChild(el);
  }
}

const lastManaCounts = {};

function renderMana(containerId, manaPool, targetSeat = null) {
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

function renderPhaseRail(state) {
  const container = q("phaseRail");
  if (!container) return;

  container.innerHTML = "";
  const activeKey = getActiveStepKey(state);
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
  }
}

function _stackCardLinkHtml(displayName, cardData, highlightKind, highlightSeat, highlightIdx) {
  const preview = cardData ? ` data-stack-preview='${JSON.stringify(cardData).replace(/'/g, "&#39;")}'` : "";
  const hl = highlightKind ? ` data-hl-kind="${highlightKind}" data-hl-seat="${highlightSeat ?? ""}" data-hl-idx="${highlightIdx ?? ""}"` : "";
  return `<span class="stack-card-link"${preview}${hl}>${escapeHtml(displayName)}</span>`;
}

function _buildStackItemHtml(item, position) {
  const caster = item.caster_name || `Seat ${item.caster_index}`;
  const cardName = item.card?.name || item.label || "Unknown";
  const isAbility = item.type === "ability";
  const isTriggered = item.is_triggered;
  const pos = `<span class="stack-pos">${position})</span> `;

  if (isAbility && isTriggered) {
    const srcLink = _stackCardLinkHtml(cardName, item.card, "permanent", item.source_permanent_seat, item.source_permanent_index);
    const abilityPart = item.ability_text ? `&ldquo;${renderSymbolsInline(item.ability_text)}&rdquo;` : "";
    return `${pos}${srcLink} triggered ability ${abilityPart}`;
  }

  if (isAbility) {
    const srcLink = _stackCardLinkHtml(cardName, item.card, "permanent", item.source_permanent_seat, item.source_permanent_index);
    const abilityPart = item.ability_text ? `&ldquo;${renderSymbolsInline(item.ability_text)}&rdquo;` : "";
    return `${pos}${caster} activates ${srcLink} ability ${abilityPart}`;
  }

  // Spell
  const spellLink = _stackCardLinkHtml(cardName, item.card, null, null, null);
  let targetHtml = "";
  if (item.target_stack_name) {
    const stackIdx = _findStackItemIndexByName(item.target_stack_name);
    targetHtml = `, targeting ${_stackCardLinkHtml(item.target_stack_name, null, "stack", null, stackIdx)}`;
  } else if (item.target_permanent_name) {
    targetHtml = `, targeting ${_stackCardLinkHtml(item.target_permanent_name, null, "permanent", item.target_permanent_seat, item.target_permanent_index)}`;
  } else if (item.target_player_name) {
    targetHtml = `, targeting <span class="stack-card-link">${escapeHtml(item.target_player_name)}</span>`;
  }
  return `${pos}${caster} casts ${spellLink}${targetHtml}.`;
}

let _currentStack = [];

function _findStackItemIndexByName(name) {
  return _currentStack.findIndex((item) => (item.card?.name || item.label) === name);
}

function _clearStackHighlights() {
  document.querySelectorAll(".stack-item.stack-hl").forEach((el) => el.classList.remove("stack-hl"));
  document.querySelectorAll(".card.stack-target-hl").forEach((el) => el.classList.remove("stack-target-hl"));
}

function _applyStackHoverHighlight(linkEl) {
  _clearStackHighlights();
  const kind = linkEl.dataset.hlKind;
  const seat = linkEl.dataset.hlSeat;
  const idx = linkEl.dataset.hlIdx;
  if (kind === "stack" && idx !== "" && idx !== "undefined") {
    const stackIdx = parseInt(idx, 10);
    const itemEl = document.querySelector(`.stack-item[data-stack-index="${stackIdx}"]`);
    if (itemEl) itemEl.classList.add("stack-hl");
  } else if (kind === "permanent" && seat !== "" && idx !== "" && seat !== "undefined" && idx !== "undefined") {
    const cardEl = document.querySelector(`.card[data-zone-kind="battlefield"][data-target-seat="${seat}"][data-permanent-index="${idx}"]`);
    if (cardEl) cardEl.classList.add("stack-target-hl");
  }
}

function _refreshStackHoldVisuals() {
  const heldIdx = getHeldStackArrayIndex();
  document.querySelectorAll("#stackZone .stack-item").forEach((el) => {
    const held = heldIdx !== null && Number(el.dataset.stackIndex) === heldIdx;
    el.classList.toggle("stack-held", held);
    const hint = el.querySelector(".stack-hold-hint");
    if (hint) hint.textContent = held ? "Priority held — click to release" : "Click to hold priority";
  });
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
  if (!pending || pending.targetKind !== "stack") return;
  const item = _currentStack[arrayIndex];
  if (!item || !isStackItemValidCastTarget(item)) return;

  pendingCastTarget = null;
  renderActivationPrompt();

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
  const zone = q("stackZone");

  // The hold lasts until the held spell leaves the stack (resolves or is
  // countered) or the player clicks it again — taking actions keeps it.
  if (stackClickHold && getHeldStackArrayIndex() === null) {
    releaseStackClickHold("Priority hold released: the spell left the stack.");
  }

  if (!stack || stack.length === 0) {
    zone.innerHTML = '<span class="stack-empty-label">Stack: empty</span>';
    return;
  }

  const choosingStackTarget = !!pendingCastTarget && pendingCastTarget.targetKind === "stack";

  zone.innerHTML = "";
  stack.forEach((item, arrayIndex) => {
    const position = stack.length - arrayIndex;
    const box = document.createElement("div");
    box.className = "stack-item";
    box.dataset.stackIndex = String(arrayIndex);
    box.innerHTML = _buildStackItemHtml(item, position);

    const hint = document.createElement("span");
    hint.className = "stack-hold-hint";
    box.appendChild(hint);

    // Hovering a stack item previews the card and implicitly holds priority
    // (isStackHoverHolding checks :hover, so no flag needs tracking here).
    box.addEventListener("mouseenter", () => {
      if (item.card) {
        showCardPreview(item.card);
      }
    });
    box.addEventListener("mouseleave", () => {
      if (!isPriorityHeld()) {
        resumeAutoPassAfterHold();
      }
    });

    if (choosingStackTarget) {
      // While targeting a spell on the stack (Counterspell, Fork), clicking a
      // legal spell chooses it as the target instead of toggling a hold.
      const valid = isStackItemValidCastTarget(item);
      box.classList.toggle("stack-targetable", valid);
      if (valid) {
        box.addEventListener("click", () => selectStackSpellTarget(arrayIndex));
      }
    } else {
      box.addEventListener("click", () => toggleStackClickHold(arrayIndex));
    }

    zone.appendChild(box);
  });

  _refreshStackHoldVisuals();

  zone.querySelectorAll(".stack-card-link").forEach((link) => {
    link.addEventListener("mouseenter", () => {
      const previewRaw = link.dataset.stackPreview;
      if (previewRaw) {
        try { showCardPreview(JSON.parse(previewRaw)); } catch { /* ignore */ }
      }
      _applyStackHoverHighlight(link);
    });
    link.addEventListener("mouseleave", _clearStackHighlights);
  });
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

  const logTab = q("logTab");
  if (logTab) logTab.scrollTop = logTab.scrollHeight;
}

function showTurnAnnouncement(isSelfTurn) {
  const el = document.getElementById("turnAnnouncement");
  if (!el) return;
  el.classList.remove("announcing");
  // Force reflow so removing+adding the class restarts the animation
  void el.offsetWidth;
  el.innerHTML = isSelfTurn
    ? '<span style="color:#5dde6a;">Your Turn</span>'
    : '<span style="color:#e16d70;">Opponent\'s Turn</span>';
  el.classList.add("announcing");
  el.addEventListener("animationend", () => el.classList.remove("announcing"), { once: true });
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

function renderBoard(state) {
  renderGameOverOverlay(state);
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
  const pregameInfo = getPregameInfo(state);
  const isPregame = !!pregameInfo;
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

  renderHandFan("selfHand", me.hand, {
    draggable: !requiresCleanupSelection && !isPregame,
    dragKind: "hand",
    zoneKind: "hand",
    targetSeat: viewerSeat,
    castOnClick: !isPregame,
    cleanupSelectable: requiresCleanupSelection,
    selectedHandIndices: cleanupDiscard?.selected_indices || [],
    playableHandIndices: me.playable_hand_indices || [],
  });
  renderHandFan("oppHand", opp.hand, { zoneKind: "hand", targetSeat: oppSeat });

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

    battlefieldCanvas.setTargetingKeys(getTargetablePermanentKeysForPrompt(state));
  }

  const highlightPlayerFaces = !!(
    pendingCastTarget &&
    (pendingCastTarget.targetKind === "any" || pendingCastTarget.targetKind === "player")
  );
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.toggle("targeting-valid", highlightPlayerFaces);
  }

  q("selfDeckCount").textContent = me.library_count;
  q("selfGraveCount").textContent = me.graveyard.length;
  q("selfExileCount").textContent = (me.exile || []).length;
  q("oppDeckCount").textContent = opp.library_count;
  q("oppGraveCount").textContent = opp.graveyard.length;
  q("oppExileCount").textContent = (opp.exile || []).length;

  renderZoneCards("selfGraveyardCards", me.graveyard, { zoneSeat: seat, zoneKind: "graveyard" });
  renderZoneCards("selfExileCards", me.exile || []);
  renderZoneCards("oppGraveyardCards", opp.graveyard, { zoneSeat: 1 - seat, zoneKind: "graveyard" });
  renderZoneCards("oppExileCards", opp.exile || []);

  renderMana("selfMana", me.mana_pool, seat);
  renderMana("oppMana", opp.mana_pool, 1 - seat);
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

function renderState(state, { skipStaleCheck = false } = {}) {
  // Discard stale responses: when a slow HTTP response arrives after a faster SSE+getState
  // has already applied newer state, log length is monotonically increasing so we can use
  // it as a version guard to avoid regressing currentState.
  // (skipStaleCheck is set for undo, which intentionally produces a shorter log.)
  const incomingLogLen = Array.isArray(state?.log) ? state.log.length : -1;
  const currentLogLen = Array.isArray(currentState?.log) ? currentState.log.length : -1;
  if (!skipStaleCheck && incomingLogLen < currentLogLen) return;
  const wasInPregame = !!currentState?.pregame;

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
  currentState = state;
  syncCombatDrafts(state);
  if (!isCombatStep(state, "combat_damage")) {
    combatDamageDraft = {};
  }
  const cleanupInfo = getCleanupDiscardInfo(state);
  const untapInfo = getUntapLandSelectionInfo(state);
  const upkeepPayInfo = getUpkeepPayInfo(state);
  const islandSanctuaryPending = getIslandSanctuaryInfo(state);
  const searchLibraryInfo = getSearchLibraryInfo(state);
  const reorderLibraryInfo = getReorderLibraryInfo(state);
  if (cleanupInfo || untapInfo || upkeepPayInfo || islandSanctuaryPending) {
    pendingActivation = null;
    pendingCastTarget = null;
    pendingCastX = null;
    clearPendingHandCast();
    pendingManaColor = null;
  }
  if (sessionId !== null) {
    hideSetupPanel();
  }
  const viewerSeat = seat ?? 0;
  const isSelfTurn = state.current_turn === viewerSeat;
  if (lastAnnouncedTurn !== state.current_turn && !state.pregame && !state.awaiting_opponent) {
    lastAnnouncedTurn = state.current_turn;
    showTurnAnnouncement(isSelfTurn);
  }
  renderBoard(state);
  if (wasInPregame && !state?.pregame) {
    updateActionHint("Drag from your hand to cast. The battlefield arranges itself automatically.");
  }
  renderActivationPrompt();
  renderSearchLibraryModal(searchLibraryInfo);
  renderReorderLibraryModal(reorderLibraryInfo);
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
  } else if (islandSanctuaryPending) {
    applyIslandSanctuaryPrompt();
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
      if (card && cardRequiresTargetGraveyardCreature(card)) { startCastGraveyardCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetLand(card)) { startCastLandTargetPrompt(card); return; }
      if (card && cardRequiresTargetArtifact(card)) { startCastArtifactTargetPrompt(card); return; }
      if (card && cardOffersCopyCreatureChoice(card) && getTargetableCreaturesForPrompt().length > 0) { startCastCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetCreature(card)) { startCastCreatureTargetPrompt(card); return; }
      if (card && cardRequiresTargetPermanent(card)) { startCastPermanentTargetPrompt(card); return; }
      if (card && cardRequiresTargetStackSpell(card)) { startCastStackSpellPrompt(card); return; }
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

        startActivationPrompt(activateCard, 1 - seat, activateIdx);
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

    onStackCardHover(info) {
      stackCanvasHoverActive = !!info;
      if (info) {
        if (info.item?.card) showCardPreview(info.item.card);
        return;
      }
      // Hover ended: resume the normal flow unless something else still holds.
      if (!isPriorityHeld()) {
        resumeAutoPassAfterHold();
      }
    },

    onStackCardClick(info) {
      if (info) toggleStackClickHold(info.index);
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
  });
}

function initTabs() {
  q("logTabBtn").addEventListener("click", () => {
    q("logTabBtn").classList.add("active");
    q("rawTabBtn").classList.remove("active");
    q("logTab").classList.remove("hidden");
    q("rawTab").classList.add("hidden");
    SFX.onLogOpen();
  });

  q("rawTabBtn").addEventListener("click", () => {
    q("rawTabBtn").classList.add("active");
    q("logTabBtn").classList.remove("active");
    q("rawTab").classList.remove("hidden");
    q("logTab").classList.add("hidden");
    SFX.onLogClose();
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

async function getState(skipStaleCheck = false) {
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

async function createSession() {
  hideSetupPanel();
  syncSeedControls();
  const mode = q("mode").value;
  const useCustomSeed = q("useCustomSeed").checked;
  const req = {
    mode,
    host_name: q("hostName").value,
    host_colors: Number(q("hostColors").value),
    host_deck_id: q("hostDeckSelect")?.value || null,
    // The opponent's deck is only host-configurable when it's AI. For networked
    // human_vs_human the guest brings their own deck on join.
    guest_colors: Number(q("guestColors").value),
    guest_deck_id: mode === "human_vs_human" ? null : (q("guestDeckSelect")?.value || null),
    use_custom_seed: useCustomSeed,
    custom_seed: useCustomSeed ? Number(q("customSeed").value) : null,
    enable_pregame: true,
  };
  const data = await postJson("/api/sessions", req);
  sessionId = data.session_id;
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  if (data.state?.awaiting_opponent) {
    updateActionHint("Waiting for an opponent to join — share the Join URL above.");
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
  const data = await postJson(`/api/sessions/${sessionId}/join`, {
    guest_name: q("joinName").value,
    guest_deck_id: q("joinDeckSelect")?.value || null,
    guest_colors: Number(q("joinColors")?.value) || 2,
  });
  seat = data.seat;
  openStateSyncStream();
  setJoinUrls(data.join_url, data.lan_join_url);
  setVisible(true);
  initBattlefieldCanvas();
  renderState(data.state);
  if (!data.state?.pregame) {
    updateActionHint("Joined. Drag from your hand to play. The battlefield arranges itself automatically.");
  }
}

async function sendAction(actionBody) {
  if (!sessionId) return;
  // Always carry the current phase-rail hold preferences so the server knows where
  // to stop on the AI's turn — including steps it resolves itself (turn start, end).
  const body = { stop_steps: opponentStopSteps(), ...actionBody };
  const payload = await postJson(`/api/sessions/${sessionId}/action`, body);
  renderState(payload);
}

q("homeHostBtn")?.addEventListener("click", () => {
  showMenuPage("host");
  window.syncStartPageColorInputs?.();
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
  window.syncStartPageColorInputs?.();
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
    if (!pendingCastTarget || (pendingCastTarget.targetKind !== "player" && pendingCastTarget.targetKind !== "any")) return;
    const source = event.currentTarget;
    if (!(source instanceof HTMLElement)) return;
    const targetSeat = Number(source.dataset.targetSeat);
    if (!Number.isInteger(targetSeat)) return;
    event.preventDefault();
    handlePlayerTargetClick(targetSeat);
  });
}


q("promptCancelBtn").addEventListener("click", () => {
  SFX.onMenuCancel();
  const wasCasting = !!(pendingCastTarget || pendingCastX || pendingAutoTap);
  pendingActivation = null;
  pendingCastTarget = null;
  pendingCastX = null;
  pendingManaColor = null;
  pendingAutoTap = null;
  clearPendingHandCast();
  battlefieldCanvas?.setTargetingKeys([]);
  for (const elementId of ["selfLife", "oppLife", "selfName", "oppName"]) {
    q(elementId)?.classList.remove("targeting-valid");
  }
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
clearCardPreview();

// ── Audio controls ────────────────────────────────────────────────────────────
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
})();
