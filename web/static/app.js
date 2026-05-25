let sessionId = null;
let seat = null;
let currentState = null;
let pendingActivation = null;
let pendingCastTarget = null;
let pendingCastX = null;
let pendingManaColor = null;
let debugSearchTimer = null;
let symbolMap = {};
let combatDragSource = null;
let combatDamageDraft = {};

const setupEl = document.getElementById("setup");
const boardEl = document.getElementById("boardPanel");
const aiControlsEl = document.getElementById("aiControls");
const joinUrlEl = document.getElementById("joinUrl");
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

function getCardCenter(cardEl) {
  if (!cardEl) return null;
  const rect = cardEl.getBoundingClientRect();
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  };
}

function getZoneCenter(zoneEl) {
  if (!zoneEl) return null;
  const rect = zoneEl.getBoundingClientRect();
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  };
}

function clearCombatOverlay() {
  const overlay = q("combatOverlay");
  if (!overlay) return;
  const lines = overlay.querySelectorAll("line");
  lines.forEach((line) => line.remove());
}

function drawCombatArrow(fromPoint, toPoint, kind = "attacker") {
  const overlay = q("combatOverlay");
  if (!overlay || !fromPoint || !toPoint) return;
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", String(fromPoint.x));
  line.setAttribute("y1", String(fromPoint.y));
  line.setAttribute("x2", String(toPoint.x));
  line.setAttribute("y2", String(toPoint.y));
  line.setAttribute("class", kind === "blocker" ? "combat-link-line blocker" : "combat-link-line");
  overlay.appendChild(line);
}

function renderCombatOverlay(state = currentState) {
  clearCombatOverlay();
  if (!state) return;
  const combat = getCombatState(state);
  if (!combat) return;

  const activeSeat = state.current_turn;
  const defenderSeat = combat.defending_player_index;
  if (!Number.isInteger(activeSeat) || !Number.isInteger(defenderSeat)) return;

  for (const link of combat.attackers || []) {
    const attackerEl = document.querySelector(
      `.card[data-zone-kind="battlefield"][data-target-seat="${activeSeat}"][data-permanent-index="${link.attacker_index}"]`,
    );
    const from = getCardCenter(attackerEl);
    const to = getZoneCenter(defenderSeat === 0 ? q("selfBattlefield") : q("oppBattlefield"));
    if (from && to) {
      drawCombatArrow(from, to, "attacker");
    }
  }

  for (const link of combat.blockers || []) {
    const blockerEl = document.querySelector(
      `.card[data-zone-kind="battlefield"][data-target-seat="${defenderSeat}"][data-permanent-index="${link.blocker_index}"]`,
    );
    const attackerEl = document.querySelector(
      `.card[data-zone-kind="battlefield"][data-target-seat="${activeSeat}"][data-permanent-index="${link.attacker_index}"]`,
    );
    const from = getCardCenter(blockerEl);
    const to = getCardCenter(attackerEl);
    if (from && to) {
      drawCombatArrow(from, to, "blocker");
    }
  }

  if (combatDragSource && combatDragSource.sourceEl) {
    const from = getCardCenter(combatDragSource.sourceEl);
    const to = combatDragSource.pointer;
    if (from && to) {
      drawCombatArrow(from, to, "attacker");
    }
  }
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
  const isParen = open === "(" && close === ")";
  if (!isCurly && !isParen) {
    return token;
  }

  const body = token.slice(1, -1).trim().toUpperCase();
  return `{${body}}`;
}

function isLikelyParenManaToken(token) {
  if (!token || typeof token !== "string" || token.length < 3) return false;
  if (token[0] !== "(" || token[token.length - 1] !== ")") return false;
  const body = token.slice(1, -1).trim().toUpperCase();
  // Restrict parenthesis parsing to mana-like symbols so normal prose is untouched.
  return /^[0-9WUBRGCXPQST/]+$/.test(body);
}

function symbolSrc(token) {
  if (!token || typeof token !== "string") return null;
  return symbolMap[token] || symbolMap[normalizeSymbolToken(token)] || null;
}

function renderSymbolsInline(text, symbolClass = "mtg-symbol-inline") {
  const input = String(text || "");
  let html = "";
  let lastIndex = 0;
  const matches = input.matchAll(/\{[^}]+\}|\([^)]*\)/g);

  for (const match of matches) {
    const token = match[0];
    const index = match.index || 0;
    const isCurlyToken = token[0] === "{" && token[token.length - 1] === "}";
    const isManaParenToken = isLikelyParenManaToken(token);

    if (!isCurlyToken && !isManaParenToken) {
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

function resetToSetup(message = "Session not found. Start a new game.") {
  sessionId = null;
  seat = null;
  currentState = null;
  showSetupPanel();
  boardEl.classList.add("hidden");
  aiControlsEl?.classList.add("hidden");
  setJoinUrl("");
  updateActionHint(message, true);
}

function shouldShowAiControls(state) {
  const seatTypes = state?.seat_types || {};
  const values = Object.values(seatTypes);
  const hasAiPlayer = values.includes("ai");
  const currentTurnIsAi = seatTypes?.[state?.current_turn] === "ai";
  return hasAiPlayer && currentTurnIsAi;
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
  return (card.oracle_text || "").toLowerCase().includes("target land");
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

  return false;
}

function findCardInCurrentHand(cardName) {
  const me = getCurrentPlayerState();
  if (!me || !Array.isArray(me.hand)) return null;
  return me.hand.find((card) => normalizeCardName(card) === cardName) || null;
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

function renderActivationPrompt() {
  const panel = q("activationPanel");
  const title = q("promptTitle");
  const body = q("promptBody");
  const steps = q("promptSteps");
  const cancelBtn = q("promptCancelBtn");
  const okBtn = q("promptOkBtn");
  const customRow = q("promptCustomRow");
  const customValue = q("promptCustomValue");
  const customOkBtn = q("promptCustomOkBtn");
  const me = getCurrentPlayerState();
  const cleanupDiscard = getCleanupDiscardInfo();

  if (cleanupDiscard) {
    applyCleanupPrompt(cleanupDiscard);
    return;
  }

  if (!pendingActivation && !pendingCastTarget && !pendingCastX && !pendingManaColor) {
    panel.classList.add("hidden");
    title.textContent = "No pending activation.";
    body.textContent = "Select an activated ability to begin paying its cost.";
    steps.innerHTML = "";
    customRow.classList.add("hidden");
    okBtn.classList.remove("hidden");
    okBtn.disabled = true;
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
    } else {
      body.textContent = "Click a card in hand or on the battlefield of the player you want to target.";
      steps.innerHTML = `<div>Card: ${pendingCastTarget.cardName}</div>`;
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
            : escapeHtml(`(${symbol})`);
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

  pendingCastTarget = null;
  renderActivationPrompt();

  if (hasXCost(pending.card)) {
    startCastXPrompt(pending.card, selectedTarget, selectedPermanentIndex, pending.castAction || "cast");
    return;
  }

  updateActionHint(`Casting ${pending.cardName}...`);
  sendAction({
    seat,
    action: pending.castAction || "cast",
    card_name: pending.cardName,
    target_seat: selectedTarget,
    permanent_index: selectedPermanentIndex,
  })
    .then(() => updateActionHint(`Cast ${pending.cardName}.`))
    .catch((e) => updateActionHint(e.message, true));
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
    .catch((e) => updateActionHint(e.message, true));
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
  if (typeof card.power !== "number" || typeof card.toughness !== "number") {
    return "";
  }
  return `${card.power}/${card.toughness}`;
}

function updateActionHint(message, isError = false) {
  const el = q("actionHint");
  el.textContent = message;
  el.style.color = isError ? "#e16d70" : "#cfd7e4";
}

function setJoinUrl(url = "") {
  if (!joinUrlEl) return;

  const trimmed = String(url || "").trim();
  if (!trimmed) {
    joinUrlEl.dataset.url = "";
    joinUrlEl.textContent = "";
    joinUrlEl.classList.add("hidden");
    return;
  }

  joinUrlEl.dataset.url = trimmed;
  joinUrlEl.textContent = `Join URL: ${trimmed}`;
  joinUrlEl.classList.remove("hidden");
}

function syncJoinUrlVisibility(state) {
  if (!joinUrlEl) return;
  if (!joinUrlEl.dataset.url) {
    joinUrlEl.classList.add("hidden");
    return;
  }
  joinUrlEl.classList.toggle("hidden", !hasOpenHumanSlot(state));
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

function setDebugMenuEnabled(enabled) {
  q("debugCardSearch").disabled = !enabled;
  q("debugAddToHandBtn").disabled = !enabled;
  q("debugCastFreeBtn").disabled = !enabled;
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
  q("cardPreviewImage").classList.add("hidden");
  q("cardPreviewImage").removeAttribute("src");
  q("cardPreviewEmpty").classList.remove("hidden");
  q("cardPreviewName").textContent = "No card selected";
  q("cardPreviewType").textContent = "";
  q("cardPreviewText").textContent = "";
}

function showCardPreview(card) {
  const largeImageUri = normalizeLargeImageUri(card);
  q("cardPreviewName").textContent = normalizeCardName(card) || "Card";
  q("cardPreviewType").textContent = typeof card === "string" ? "" : card.type || "";
  setSymbolsHtml(q("cardPreviewText"), typeof card === "string" ? "" : card.oracle_text || "");

  if (!largeImageUri) {
    q("cardPreview").classList.add("empty-preview");
    q("cardPreviewImage").classList.add("hidden");
    q("cardPreviewImage").removeAttribute("src");
    q("cardPreviewEmpty").classList.remove("hidden");
    q("cardPreviewEmpty").textContent = "No large art available for this card.";
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
  if (draggable) {
    cardEl.classList.add("draggable");
    cardEl.draggable = true;
  }
  if (tapped) cardEl.classList.add("tapped");
  if (hidden) cardEl.classList.add("card-hidden");
  if (interactive) cardEl.classList.add("clickable");
  if (cleanupSelectable) cardEl.classList.add("cleanup-selectable", "clickable");
  if (selected) cardEl.classList.add("selected-card");

  const imageUri = normalizeImageUri(card);
  if (!hidden && imageUri) {
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
        JSON.stringify({ kind: dragKind, name: normalizeCardName(card), permanentIndex })
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

        if (cardRequiresTargetLand(card)) {
          startCastLandTargetPrompt(card);
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

        await sendAction({ seat, action: "cast", card_name: cardName, target_seat: targetSeat });
        updateActionHint(`Cast ${cardName} targeting seat ${targetSeat}.`);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
  }

  return cardEl;
}

function renderCardRow(containerId, cards, options = {}) {
  const container = q(containerId);
  container.innerHTML = "";
  if (!cards || cards.length === 0) return;

  for (const [index, card] of cards.entries()) {
    if (card === "<hidden>") {
      container.appendChild(createCardElement("Hidden", { ...options, hidden: true }));
      continue;
    }
    const tapped = typeof card === "object" ? !!card.tapped : false;
    const permanentIndex = options.zoneKind === "battlefield" ? index : null;
    const selected = Array.isArray(options.selectedHandIndices) && options.selectedHandIndices.includes(index);
    container.appendChild(
      createCardElement(card, { ...options, tapped, permanentIndex, handIndex: index, selected })
    );
  }
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
    item.title = phase.title;
    item.dataset.phase = phase.key;
    if (activeKey === phase.key) {
      item.classList.add("active");
      item.setAttribute("aria-current", "step");
    }
    container.appendChild(item);
  }
}

function renderStack(stack) {
  if (!stack || stack.length === 0) {
    q("stackZone").textContent = "Stack: empty";
    return;
  }
  const lines = stack.map((item) => {
    const cardName = item.card?.name || "Unknown";
    const caster = item.caster_name || `Seat ${item.caster_index}`;
    if (item.target_player_name) {
      return `${cardName} by ${caster} targeting ${item.target_player_name}`;
    }
    return `${cardName} by ${caster}`;
  });
  q("stackZone").innerHTML = `Stack:<br>${lines.map((line) => renderSymbolsInline(line)).join("<br>")}`;
}

function renderCombatControls(state) {
  const controls = q("combatControls");
  const summary = q("combatSummary");
  const actions = q("combatActions");
  const damagePanel = q("combatDamagePanel");
  if (!controls || !summary || !actions || !damagePanel) return;

  actions.innerHTML = "";
  damagePanel.innerHTML = "";
  const combat = getCombatState(state);
  const inCombat = state?.current_turn_phase === "combat";
  controls.classList.toggle("hidden", !inCombat);
  if (!inCombat) {
    return;
  }

  const attackers = combat?.attackers || [];
  const blockers = combat?.blockers || [];
  summary.textContent = `Attackers: ${attackers.length} | Blockers: ${blockers.length}`;

  if (isCombatStep(state, "declare_attackers") && seat === state.current_turn) {
    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.id = "confirmAttackersBtn";
    submitBtn.textContent = "Confirm Attackers";
    submitBtn.addEventListener("click", async () => {
      try {
        const declared = (getCombatState(currentState)?.attackers || []).map((item) => Number(item.attacker_index));
        await sendAction({ seat, action: "declare_attackers", attacker_indices: declared });
        updateActionHint(`Attackers confirmed (${declared.length}).`);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
    actions.appendChild(submitBtn);
  }

  if (isCombatStep(state, "declare_blockers") && seat === combat?.defending_player_index) {
    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.id = "confirmBlockersBtn";
    submitBtn.textContent = "Confirm Blockers";
    submitBtn.addEventListener("click", async () => {
      try {
        const blockerPairs = {};
        for (const pair of getCombatState(currentState)?.blockers || []) {
          blockerPairs[Number(pair.blocker_index)] = Number(pair.attacker_index);
        }
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: blockerPairs });
        updateActionHint(`Blockers confirmed (${Object.keys(blockerPairs).length}).`);
      } catch (e) {
        updateActionHint(e.message, true);
      }
    });
    actions.appendChild(submitBtn);
  }

  if (isCombatStep(state, "combat_damage") && seat === state.current_turn) {
    const byAttacker = {};
    for (const pair of blockers) {
      const attackerIndex = Number(pair.attacker_index);
      if (!byAttacker[attackerIndex]) {
        byAttacker[attackerIndex] = [];
      }
      byAttacker[attackerIndex].push(Number(pair.blocker_index));
    }

    for (const [attackerIndexRaw, blockerIndices] of Object.entries(byAttacker)) {
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

  q("selfBattlefield").dataset.targetSeat = String(viewerSeat);
  q("oppBattlefield").dataset.targetSeat = String(oppSeat);

  q("statusHeadline").textContent = `Status: ${state.status}`;
  q("turnBadge").textContent = `Turn: Seat ${state.current_turn} (No. ${state.turn_number || "-"})`;
  q("phaseBadge").textContent = `Phase: ${getPhaseDisplayLabel(state)}`;
  q("winnerBadge").textContent = `Winner: ${state.winner === null ? "-" : state.winner}`;

  q("selfName").textContent = me.name;
  q("selfLife").textContent = String(me.life);
  q("oppName").textContent = opp.name;
  q("oppLife").textContent = String(opp.life);

  const isSelfTurn = state.current_turn === viewerSeat;
  const canEndTurn = seat !== null && isSelfTurn;
  const cleanupDiscard = getCleanupDiscardInfo(state);
  const requiresCleanupSelection = !!cleanupDiscard;
  const selfLane = document.querySelector(".self-lane");
  const oppLane = document.querySelector(".opponent-lane");
  setDebugMenuEnabled(sessionId !== null && seat !== null);
  q("endTurnBtn").disabled = !canEndTurn;
  selfLane?.classList.toggle("turn-zone-self", isSelfTurn);
  oppLane?.classList.toggle("turn-zone-opponent", !isSelfTurn);
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
  renderCardRow("selfBattlefield", me.battlefield, {
    draggable: true,
    dragKind: "permanent",
    zoneKind: "battlefield",
    targetSeat: viewerSeat,
    interactive: true,
  });
  renderCardRow("oppBattlefield", opp.battlefield, { zoneKind: "battlefield", targetSeat: oppSeat });

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
  currentState = state;
  syncJoinUrlVisibility(state);
  if (!isCombatStep(state, "combat_damage")) {
    combatDamageDraft = {};
  }
  const cleanupInfo = getCleanupDiscardInfo(state);
  if (cleanupInfo) {
    pendingActivation = null;
    pendingCastTarget = null;
    pendingCastX = null;
    pendingManaColor = null;
  }
  if (sessionId !== null) {
    hideSetupPanel();
  }
  renderBoard(state);
  renderActivationPrompt();
  attemptPendingActivation();

  // Final-pass override so cleanup prompt always wins against other prompt updates.
  if (cleanupInfo) {
    applyCleanupPrompt(cleanupInfo);
  }
}

function initCombatContextMenu() {
  boardEl.addEventListener("contextmenu", async (event) => {
    const cardEl = event.target.closest(".card");
    if (!cardEl || !currentState) return;
    const zoneKind = cardEl.dataset.zoneKind;
    const targetSeat = Number(cardEl.dataset.targetSeat || -1);
    const permanentIndex = Number(cardEl.dataset.permanentIndex || -1);
    if (zoneKind !== "battlefield" || !Number.isInteger(permanentIndex) || permanentIndex < 0) {
      return;
    }

    const combat = getCombatState(currentState);
    if (!combat) return;

    try {
      if (isCombatStep(currentState, "declare_attackers") && seat === currentState.current_turn && targetSeat === seat) {
        event.preventDefault();
        const updated = (combat.attackers || [])
          .map((item) => Number(item.attacker_index))
          .filter((idx) => idx !== permanentIndex)
          .sort((a, b) => a - b);
        await sendAction({ seat, action: "declare_attackers", attacker_indices: updated, target_seat: combat.defending_player_index });
        updateActionHint("Removed attacker target link.");
        return;
      }

      if (isCombatStep(currentState, "declare_blockers") && seat === combat.defending_player_index) {
        event.preventDefault();
        const blockerPairs = {};
        for (const pair of combat.blockers || []) {
          const blockerIdx = Number(pair.blocker_index);
          const attackerIdx = Number(pair.attacker_index);
          if (targetSeat === combat.defending_player_index && blockerIdx === permanentIndex) {
            continue;
          }
          if (targetSeat === currentState.current_turn && attackerIdx === permanentIndex) {
            continue;
          }
          blockerPairs[blockerIdx] = attackerIdx;
        }
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: blockerPairs });
        updateActionHint("Removed blocker target link.");
      }
    } catch (e) {
      updateActionHint(e.message, true);
    }
  });

  window.addEventListener("resize", () => renderCombatOverlay());
  window.addEventListener("scroll", () => renderCombatOverlay(), true);
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

function bindDropBehavior(element, onDropAction) {
  element.addEventListener("dragover", (event) => {
    event.preventDefault();
    element.classList.add("active-drop");
    if (combatDragSource) {
      combatDragSource.pointer = { x: event.clientX, y: event.clientY };
      renderCombatOverlay();
    }
  });
  element.addEventListener("dragleave", () => {
    element.classList.remove("active-drop");
    renderCombatOverlay();
  });
  element.addEventListener("drop", async (event) => {
    event.preventDefault();
    element.classList.remove("active-drop");
    if (seat === null) {
      updateActionHint("Join or create a session before interacting.", true);
      return;
    }
    const payload = parseDragPayload(event);
    if (!payload) {
      updateActionHint("Could not read dropped card data.", true);
      return;
    }
    await onDropAction(payload, element, event);
    combatDragSource = null;
    renderCombatOverlay();
  });
}

function initDropZones() {
  bindDropBehavior(q("selfBattlefield"), async (payload, element, event) => {
    const targetSeat = Number(element.dataset.targetSeat || String(seat));
    try {
      if (isCombatAttackerDrag(payload) && targetSeat !== seat) {
        const combat = getCombatState();
        const existing = (combat?.attackers || []).map((item) => Number(item.attacker_index));
        const updated = Array.from(new Set([...existing, Number(payload.permanentIndex)])).sort((a, b) => a - b);
        await sendAction({ seat, action: "declare_attackers", attacker_indices: updated, target_seat: targetSeat });
        updateActionHint("Declared attacker link.");
        return;
      }

      if (isCombatBlockerDrag(payload)) {
        const combat = getCombatState();
        const activeSeat = currentState?.current_turn;
        const targetCardEl = event.target.closest(".card");
        const targetIndexRaw = targetCardEl?.dataset?.permanentIndex;
        const targetCardSeat = Number(targetCardEl?.dataset?.targetSeat || -1);
        const attackerIndex = Number(targetIndexRaw);
        if (!Number.isInteger(attackerIndex) || targetCardSeat !== activeSeat) {
          updateActionHint("Drop blocker onto an attacking creature.", true);
          return;
        }
        const blockerPairs = {};
        for (const pair of combat?.blockers || []) {
          blockerPairs[Number(pair.blocker_index)] = Number(pair.attacker_index);
        }
        blockerPairs[Number(payload.permanentIndex)] = attackerIndex;
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: blockerPairs });
        updateActionHint("Declared blocker link.");
        return;
      }

      if (payload.kind === "hand") {
        const card = findCardInCurrentHand(payload.name);
        if (card && cardRequiresTargetPlayer(card)) {
          startCastTargetPrompt(card);
          return;
        }
        const castTargetSeat = card ? getDefaultTargetSeat(payload.name) : targetSeat;
        if (card && hasXCost(card)) {
          startCastXPrompt(card, castTargetSeat);
          return;
        }
        await sendAction({ seat, action: "cast", card_name: payload.name, target_seat: castTargetSeat });
        updateActionHint(`Cast ${payload.name} targeting seat ${castTargetSeat}.`);
        return;
      }
      if (payload.kind === "permanent") {
        const me = getCurrentPlayerState();
        const indexedCard =
          me && Number.isInteger(payload.permanentIndex) ? me.battlefield[payload.permanentIndex] : null;
        const card = indexedCard || (me ? me.battlefield.find((perm) => normalizeCardName(perm) === payload.name) : null);
        if (card) {
          const permanentIndex =
            me && Number.isInteger(payload.permanentIndex) && me.battlefield[payload.permanentIndex] === card
              ? payload.permanentIndex
              : me.battlefield.findIndex((perm) => perm === card);
          startActivationPrompt(card, targetSeat, permanentIndex >= 0 ? permanentIndex : null);
        }
      }
    } catch (e) {
      updateActionHint(e.message, true);
    }
  });

  bindDropBehavior(q("oppBattlefield"), async (payload, element, event) => {
    const targetSeat = Number(element.dataset.targetSeat || "1");
    try {
      if (isCombatAttackerDrag(payload) && targetSeat !== seat) {
        const combat = getCombatState();
        const existing = (combat?.attackers || []).map((item) => Number(item.attacker_index));
        const updated = Array.from(new Set([...existing, Number(payload.permanentIndex)])).sort((a, b) => a - b);
        await sendAction({ seat, action: "declare_attackers", attacker_indices: updated, target_seat: targetSeat });
        updateActionHint("Declared attacker link.");
        return;
      }

      if (isCombatBlockerDrag(payload)) {
        const combat = getCombatState();
        const activeSeat = currentState?.current_turn;
        const targetCardEl = event.target.closest(".card");
        const targetIndexRaw = targetCardEl?.dataset?.permanentIndex;
        const targetCardSeat = Number(targetCardEl?.dataset?.targetSeat || -1);
        const attackerIndex = Number(targetIndexRaw);
        if (!Number.isInteger(attackerIndex) || targetCardSeat !== activeSeat) {
          updateActionHint("Drop blocker onto an attacking creature.", true);
          return;
        }
        const blockerPairs = {};
        for (const pair of combat?.blockers || []) {
          blockerPairs[Number(pair.blocker_index)] = Number(pair.attacker_index);
        }
        blockerPairs[Number(payload.permanentIndex)] = attackerIndex;
        await sendAction({ seat, action: "declare_blockers", blocker_pairs: blockerPairs });
        updateActionHint("Declared blocker link.");
        return;
      }

      if (payload.kind === "hand") {
        const card = findCardInCurrentHand(payload.name);
        if (card && cardRequiresTargetPlayer(card)) {
          startCastTargetPrompt(card);
          return;
        }
        const castTargetSeat = card ? getDefaultTargetSeat(payload.name) : targetSeat;
        if (card && hasXCost(card)) {
          startCastXPrompt(card, castTargetSeat);
          return;
        }
        await sendAction({ seat, action: "cast", card_name: payload.name, target_seat: castTargetSeat });
        updateActionHint(`Cast ${payload.name} targeting seat ${castTargetSeat}.`);
        return;
      }
      if (payload.kind === "permanent") {
        const me = getCurrentPlayerState();
        const indexedCard =
          me && Number.isInteger(payload.permanentIndex) ? me.battlefield[payload.permanentIndex] : null;
        const card = indexedCard || (me ? me.battlefield.find((perm) => normalizeCardName(perm) === payload.name) : null);
        if (card) {
          const permanentIndex =
            me && Number.isInteger(payload.permanentIndex) && me.battlefield[payload.permanentIndex] === card
              ? payload.permanentIndex
              : me.battlefield.findIndex((perm) => perm === card);
          startActivationPrompt(card, targetSeat, permanentIndex >= 0 ? permanentIndex : null);
        }
      }
    } catch (e) {
      updateActionHint(e.message, true);
    }
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
  const resp = await fetch(`/api/sessions/${sessionId}/state?seat=${seat ?? ""}`);
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
  setJoinUrl(data.join_url);
  renderState(data.state);
  setVisible(true);
  updateActionHint("Session ready. Drag from your hand to cast.");
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
  setJoinUrl(data.join_url);
  renderState(data.state);
  setVisible(true);
  updateActionHint("Joined. Drag from your hand or battlefield to play.");
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

joinUrlEl?.addEventListener("click", async () => {
  const targetUrl = joinUrlEl.dataset.url;
  if (!targetUrl) return;
  try {
    await copyTextToClipboard(targetUrl);
    updateActionHint("Join URL copied to clipboard.");
  } catch {
    updateActionHint("Could not copy join URL. Copy it manually.", true);
  }
});

q("promptCancelBtn").addEventListener("click", () => {
  pendingActivation = null;
  pendingCastTarget = null;
  pendingCastX = null;
  pendingManaColor = null;
  renderActivationPrompt();
  updateActionHint("Prompt canceled.");
});

q("promptOkBtn").addEventListener("click", () => {
  confirmPendingActivation();
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
    await sendAction({ seat, action: "end_turn" });
    updateActionHint("Ended turn.");
  } catch (e) {
    alert(e.message);
  }
});

q("nextPhaseBtn").addEventListener("click", async () => {
  try {
    await sendAction({ seat, action: "next_phase" });
    updateActionHint("Advanced to the next phase.");
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

setInterval(() => {
  getState();
}, 1500);

const params = new URLSearchParams(window.location.search);
const sessionFromUrl = params.get("session");
setSetupModeForUrlSession(Boolean(sessionFromUrl));
if (sessionFromUrl) {
  q("joinSessionId").value = sessionFromUrl;
}

syncGuestNameForMode();
syncSeedControls();
setDebugMenuEnabled(false);
q("endTurnBtn").disabled = true;
fetchDebugSuggestions().catch(() => {
  // Intentionally ignored during startup.
});

loadSymbolMap();

initDropZones();
initTabs();
initCardPreviewHover();
initCombatContextMenu();
clearCardPreview();
