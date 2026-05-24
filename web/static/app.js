let sessionId = null;
let seat = null;
let currentState = null;
let pendingActivation = null;
let pendingCastTarget = null;
let pendingCastX = null;

const setupEl = document.getElementById("setup");
const sessionEl = document.getElementById("session");
const boardEl = document.getElementById("boardPanel");
const controlsEl = document.getElementById("controls");

const MANA_ORDER = ["W", "U", "B", "R", "G", "C"];
const PHASE_LABELS = {
  untap: "Untap",
  upkeep: "Upkeep",
  draw: "Draw",
  main: "Main",
};

function q(id) {
  return document.getElementById(id);
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

function setVisible(active) {
  if (active) {
    hideSetupPanel();
  } else {
    showSetupPanel();
  }
  for (const el of [sessionEl, boardEl, controlsEl]) {
    el.classList.toggle("hidden", !active);
  }
}

function resetToSetup(message = "Session not found. Start a new game.") {
  sessionId = null;
  seat = null;
  currentState = null;
  showSetupPanel();
  sessionEl.classList.add("hidden");
  boardEl.classList.add("hidden");
  controlsEl.classList.add("hidden");
  updateActionHint(message, true);
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

function getDefaultTargetSeat(cardName) {
  if (seat === null) return 1;
  if (["Ancestral Recall", "Healing Salve", "Stream of Life"].includes(cardName)) {
    return seat;
  }
  return 1 - seat;
}

function findCardInCurrentHand(cardName) {
  const me = getCurrentPlayerState();
  if (!me || !Array.isArray(me.hand)) return null;
  return me.hand.find((card) => normalizeCardName(card) === cardName) || null;
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

  if (!pendingActivation && !pendingCastTarget && !pendingCastX) {
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
    body.textContent = "This spell targets a player. Choose who should receive it.";
    steps.innerHTML = [
      `<div>Card: ${pendingCastTarget.cardName}</div>`,
      `<div class="prompt-choice-row">${[
        `<button type="button" class="prompt-choice-btn" data-target-choice="${seat}">You</button>`,
        `<button type="button" class="prompt-choice-btn" data-target-choice="${1 - seat}">Opponent</button>`,
      ].join("")}</div>`,
    ].join("");
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
      `<div>Cost: ${pendingCastX.card.mana_cost || "none"}</div>`,
      `<div>Needed: ${formatManaSymbols(pendingCastX.manaRequirement || {})}</div>`,
      `<div>Current mana: ${me ? formatManaSymbols(me.mana_pool) : "Unknown"}</div>`,
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
    `<div>Cost: ${pendingActivation.activationCost || "none"}</div>`,
    `<div>Needed: ${formatManaSymbols(manaRequirement)}</div>`,
    `<div>Current mana: ${me ? formatManaSymbols(me.mana_pool) : "Unknown"}</div>`,
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
      target_seat: pending.targetSeat,
    });
    updateActionHint(`Activated ${pending.cardName}.`);
  } catch (e) {
    updateActionHint(e.message, true);
  }
}

function startActivationPrompt(card, targetSeat) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  const activationCost = getActivatedAbilityCost(card);
  if (!shouldPromptForActivationCost(activationCost)) {
    sendAction({ seat, action: "activate", permanent_name: cardName, target_seat: targetSeat })
      .then(() => updateActionHint(`Activated ${cardName}.`))
      .catch((e) => updateActionHint(e.message, true));
    return;
  }

  pendingActivation = {
    cardName,
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

function startCastTargetPrompt(card) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastTarget = {
    card,
    cardName,
  };
  renderActivationPrompt();
  updateActionHint(`Choose a target for ${cardName}.`);
}

function startCastXPrompt(card, targetSeat) {
  const cardName = normalizeCardName(card);
  if (!cardName) return;

  pendingCastX = {
    kind: "cast_x",
    card,
    cardName,
    targetSeat,
    manaRequirement: parseManaCostSymbols(card.mana_cost || ""),
    maxX: getMaxAffordableX(getCurrentPlayerState()?.mana_pool, card.mana_cost || ""),
    awaitingCustomValue: false,
  };
  renderActivationPrompt();
  updateActionHint(`Choose X for ${cardName}.`);
}

function resolvePendingCastTarget(targetSeat) {
  if (!pendingCastTarget) return;
  const pending = pendingCastTarget;
  const selectedTarget = Number.isInteger(targetSeat) ? targetSeat : seat;
  pendingCastTarget = null;
  renderActivationPrompt();

  if (hasXCost(pending.card)) {
    startCastXPrompt(pending.card, selectedTarget);
    return;
  }

  updateActionHint(`Casting ${pending.cardName} targeting seat ${selectedTarget}...`);
  sendAction({
    seat,
    action: "cast",
    card_name: pending.cardName,
    target_seat: selectedTarget,
  })
    .then(() => updateActionHint(`Cast ${pending.cardName} targeting seat ${selectedTarget}.`))
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
    action: "cast",
    card_name: pending.cardName,
    target_seat: pending.targetSeat,
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
  q("cardPreviewText").textContent = typeof card === "string" ? "" : card.oracle_text || "";

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
  } = options;
  const cardEl = document.createElement("div");
  cardEl.className = "card";
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
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(
        "text/plain",
        JSON.stringify({ kind: dragKind, name: normalizeCardName(card) })
      );
    });
  }

  if (compact) {
    cardEl.style.width = "54px";
    cardEl.style.minHeight = "74px";
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

        startActivationPrompt(card, 1 - seat);
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
        const cardName = normalizeCardName(card);
        if (!cardName) return;

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

  for (const card of cards) {
    if (card === "<hidden>") {
      container.appendChild(createCardElement("Hidden", { ...options, hidden: true }));
      continue;
    }
    const tapped = typeof card === "object" ? !!card.tapped : false;
    container.appendChild(createCardElement(card, { ...options, tapped }));
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
    chip.innerHTML = `<span>${symbol === "C" ? "GEN" : symbol} ${count}</span>`;
    container.appendChild(chip);
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
  q("stackZone").textContent = `Stack: ${lines.join(" | ")}`;
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
  header.textContent = `Turn ${state.turn_number || "-"} | Phase ${PHASE_LABELS[state.current_phase] || state.current_phase}`;
  logRoot.appendChild(header);

  entries.forEach((entry, idx) => {
    const item = document.createElement("div");
    item.className = "log-item";
    item.textContent = `${idx + 1}. ${entry}`;
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
  q("phaseBadge").textContent = `Phase: ${PHASE_LABELS[state.current_phase] || state.current_phase}`;
  q("winnerBadge").textContent = `Winner: ${state.winner === null ? "-" : state.winner}`;

  q("selfName").textContent = me.name;
  q("selfLife").textContent = String(me.life);
  q("oppName").textContent = opp.name;
  q("oppLife").textContent = String(opp.life);

  renderCardRow("selfHand", me.hand, { draggable: true, dragKind: "hand", castOnClick: true });
  renderCardRow("oppHand", opp.hand, { compact: true });
  renderCardRow("selfBattlefield", me.battlefield, { draggable: true, dragKind: "permanent", interactive: true });
  renderCardRow("oppBattlefield", opp.battlefield);

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
  renderStack(state.stack);
  renderLog(state);
  q("rawState").textContent = JSON.stringify(state, null, 2);
}

function renderState(state) {
  currentState = state;
  if (sessionId !== null) {
    hideSetupPanel();
  }
  renderBoard(state);
  renderActivationPrompt();
  attemptPendingActivation();
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
  });
  element.addEventListener("dragleave", () => {
    element.classList.remove("active-drop");
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
    await onDropAction(payload, element);
  });
}

function initDropZones() {
  bindDropBehavior(q("selfBattlefield"), async (payload, element) => {
    const targetSeat = Number(element.dataset.targetSeat || String(seat));
    try {
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
        const card = me ? me.battlefield.find((perm) => normalizeCardName(perm) === payload.name) : null;
        if (card) {
          startActivationPrompt(card, targetSeat);
        }
      }
    } catch (e) {
      updateActionHint(e.message, true);
    }
  });

  bindDropBehavior(q("oppBattlefield"), async (payload, element) => {
    const targetSeat = Number(element.dataset.targetSeat || "1");
    try {
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
        const card = me ? me.battlefield.find((perm) => normalizeCardName(perm) === payload.name) : null;
        if (card) {
          startActivationPrompt(card, targetSeat);
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
  const req = {
    mode: q("mode").value,
    host_name: q("hostName").value,
    guest_name: q("guestName").value,
    host_colors: Number(q("hostColors").value),
    guest_colors: Number(q("guestColors").value),
    seed: Number(q("seed").value),
  };
  const data = await postJson("/api/sessions", req);
  sessionId = data.session_id;
  seat = data.seat;
  q("sessionMeta").textContent = `Session: ${sessionId} | You are seat ${seat}`;
  const joinAbsolute = `${window.location.origin}/index.html?session=${sessionId}`;
  q("joinUrl").textContent = `Join URL: ${joinAbsolute}`;
  renderState(data.state);
  setVisible(true);
  updateActionHint("Session ready. Drag from your hand to cast.");
}

async function joinSession() {
  sessionId = q("joinSessionId").value.trim();
  if (!sessionId) {
    alert("Enter a session ID");
    return;
  }
  const data = await postJson(`/api/sessions/${sessionId}/join`, { guest_name: q("joinName").value });
  seat = data.seat;
  q("sessionMeta").textContent = `Session: ${sessionId} | You are seat ${seat}`;
  q("joinUrl").textContent = "Joined existing session";
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

q("joinBtn").addEventListener("click", async () => {
  try {
    await joinSession();
  } catch (e) {
    alert(e.message);
  }
});

q("promptCancelBtn").addEventListener("click", () => {
  pendingActivation = null;
  pendingCastTarget = null;
  pendingCastX = null;
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
    resolvePendingCastTarget(Number(targetChoice));
    return;
  }

  const choice = target.dataset.xChoice;
  if (!choice || !pendingCastX) return;
  if (choice === "custom") {
    pendingCastX.awaitingCustomValue = true;
    renderActivationPrompt();
    return;
  }
  resolvePendingCastX(Number(choice));
});

q("endTurnBtn").addEventListener("click", async () => {
  try {
    await sendAction({ seat, action: "end_turn" });
    updateActionHint("Ended turn.");
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

setInterval(() => {
  getState();
}, 1500);

const params = new URLSearchParams(window.location.search);
const sessionFromUrl = params.get("session");
if (sessionFromUrl) {
  q("joinSessionId").value = sessionFromUrl;
}

initDropZones();
initTabs();
initCardPreviewHover();
clearCardPreview();
