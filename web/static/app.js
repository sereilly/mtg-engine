let sessionId = null;
let seat = null;
let currentState = null;

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
          await sendAction({ seat, action: "tap", permanent_name: cardName });
          updateActionHint(`Tapped ${cardName}.`);
          return;
        }

        // `window.prompt` is unsupported in some webview hosts; use click semantics instead.
        // Normal click taps. Shift+click activates the permanent's ability.
        if (!event.shiftKey) {
          await sendAction({ seat, action: "tap", permanent_name: cardName });
          updateActionHint(`Tapped ${cardName}.`);
          return;
        }

        const targetSeat = Number(q("activateTarget")?.value ?? String(1 - seat));
        await sendAction({ seat, action: "activate", permanent_name: cardName, target_seat: targetSeat });
        updateActionHint(`Activated ${cardName}. (Tip: normal click taps, Shift+click activates)`);
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

        const targetSeat = Number(q("castTarget")?.value ?? String(1 - seat));
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

function populateManualControls(state) {
  const me = seat !== null ? state.players[seat] : null;
  const castSelect = q("castCard");
  const activateSelect = q("activatePermanent");
  castSelect.innerHTML = "";
  activateSelect.innerHTML = "";

  if (!me) return;

  for (const card of me.hand) {
    if (card === "<hidden>") continue;
    const name = normalizeCardName(card);
    if (!name) continue;
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    castSelect.appendChild(opt);
  }

  for (const perm of me.battlefield) {
    const name = normalizeCardName(perm);
    if (!name) continue;
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    activateSelect.appendChild(opt);
  }
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
  populateManualControls(state);
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
        await sendAction({ seat, action: "cast", card_name: payload.name, target_seat: targetSeat });
        updateActionHint(`Cast ${payload.name} targeting seat ${targetSeat}.`);
        return;
      }
      if (payload.kind === "permanent") {
        await sendAction({ seat, action: "activate", permanent_name: payload.name, target_seat: targetSeat });
        updateActionHint(`Activated ${payload.name} targeting seat ${targetSeat}.`);
      }
    } catch (e) {
      updateActionHint(e.message, true);
    }
  });

  bindDropBehavior(q("oppBattlefield"), async (payload, element) => {
    const targetSeat = Number(element.dataset.targetSeat || "1");
    try {
      if (payload.kind === "hand") {
        await sendAction({ seat, action: "cast", card_name: payload.name, target_seat: targetSeat });
        updateActionHint(`Cast ${payload.name} targeting seat ${targetSeat}.`);
        return;
      }
      if (payload.kind === "permanent") {
        await sendAction({ seat, action: "activate", permanent_name: payload.name, target_seat: targetSeat });
        updateActionHint(`Activated ${payload.name} targeting seat ${targetSeat}.`);
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

q("castBtn").addEventListener("click", async () => {
  try {
    await sendAction({
      seat,
      action: "cast",
      card_name: q("castCard").value,
      target_seat: Number(q("castTarget").value),
    });
    updateActionHint(`Cast ${q("castCard").value}.`);
  } catch (e) {
    alert(e.message);
  }
});

q("activateBtn").addEventListener("click", async () => {
  try {
    await sendAction({
      seat,
      action: "activate",
      permanent_name: q("activatePermanent").value,
      target_seat: Number(q("activateTarget").value),
    });
    updateActionHint(`Activated ${q("activatePermanent").value}.`);
  } catch (e) {
    alert(e.message);
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
