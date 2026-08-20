// Deck editor page. Relies on globals from app.js: q(), escapeHtml(),
// renderSymbolsInline(), postJson(), and the shared stylesheet.
(() => {
  const state = {
    catalog: [],
    catalogByName: new Map(),
    decks: [],
    // entries/sideboard/commander: [{name, count, status}]
    current: { id: null, name: "Untitled Deck", entries: [], sideboard: [], commander: [], format: "casual" },
    // Which board the browser's +/- buttons and the deck pane act on: "main",
    // "sideboard" (the "outside the game" pool, CR 100.4, that Ring of Ma'rûf
    // fetches from), or "commander" (the command zone, CR 903.5a — only shown
    // for the Commander format).
    activeBoard: "main",
    dirty: false,
    selectedCardName: null,
    colorFilters: new Set(),
  };

  const BOARD_PROPERTY = { main: "entries", sideboard: "sideboard", commander: "commander" };

  const TYPE_GROUPS = [
    ["creature", "Creatures"],
    ["instant", "Instants"],
    ["sorcery", "Sorceries"],
    ["enchantment", "Enchantments"],
    ["artifact", "Artifacts"],
    ["land", "Lands"],
  ];
  const COLOR_SORT_ORDER = { W: 0, U: 1, B: 2, R: 3, G: 4 };

  function lookupCard(name) {
    return state.catalogByName.get(String(name).toLowerCase()) || null;
  }

  // Swap the W/U/B/R/G/C filter buttons' letter labels for the real mana icons,
  // matching the in-game mana pool orbs. symbolMap (in app.js) loads
  // asynchronously, so this may run before icons are available; app.js calls
  // window.refreshDeckEditorSymbols once symbolMap is ready to retry.
  function renderColorFilterIcons() {
    for (const btn of document.querySelectorAll("#browserColorFilters .color-filter-btn[data-color]")) {
      const color = btn.dataset.color;
      if (color === "M") continue;
      const src = typeof symbolSrc === "function" ? symbolSrc(`{${color}}`) : null;
      if (src) {
        btn.innerHTML = `<span class="mana-orb-glyph"><img class="mtg-symbol mtg-symbol-mana" src="${escapeHtml(src)}" alt="{${color}}" /></span>`;
      }
    }
  }

  function cardStatus(name) {
    const card = lookupCard(name);
    if (!card) return "unknown";
    return card.supported ? "ok" : "unsupported";
  }

  function currentFormat() {
    return state.current.format || "casual";
  }

  // Legality reason for a card in the current format, "" if ok. The copy limit
  // counts deck + sideboard + commander together (CR 100.4a), so all boards
  // are consulted regardless of which one the card is being shown in.
  function cardLegalityProblem(name) {
    const card = lookupCard(name);
    if (!card || !window.Legality) return "";
    const main = entryFor(name, "entries");
    const side = entryFor(name, "sideboard");
    const cmd = entryFor(name, "commander");
    return window.Legality.cardProblem(
      card, currentFormat(), main ? main.count : 0, side ? side.count : 0, cmd ? cmd.count : 0,
    );
  }

  // Copies of a card held across all boards — the number the four-of limit
  // actually applies to (CR 100.4a).
  function combinedCount(name) {
    const main = entryFor(name, "entries");
    const side = entryFor(name, "sideboard");
    const cmd = entryFor(name, "commander");
    return (main ? main.count : 0) + (side ? side.count : 0) + (cmd ? cmd.count : 0);
  }

  function overCopyLimit(name) {
    const card = lookupCard(name);
    const limit = card && window.Legality ? window.Legality.copyLimit(card, currentFormat()) : null;
    return limit != null && combinedCount(name) > limit;
  }

  function primaryType(card) {
    const lowered = card.type_line.toLowerCase();
    for (const [key] of TYPE_GROUPS) {
      if (lowered.includes(key)) return key;
    }
    return "other";
  }

  function deckTotal() {
    return state.current.entries.reduce((sum, e) => sum + e.count, 0);
  }

  function sideboardTotal() {
    return activeEntries("sideboard").reduce((sum, e) => sum + e.count, 0);
  }

  function commanderTotal() {
    return activeEntries("commander").reduce((sum, e) => sum + e.count, 0);
  }

  // The list currently being edited (mainboard unless the Sideboard/Commander
  // tab is on), or a named one. state.current.sideboard/commander are absent
  // on decks saved before those boards existed, so they are created on demand.
  function activeEntries(which = null) {
    const key = which || BOARD_PROPERTY[state.activeBoard];
    if (!Array.isArray(state.current[key])) state.current[key] = [];
    return state.current[key];
  }

  function entryFor(name, which = null) {
    return activeEntries(which).find((e) => e.name.toLowerCase() === String(name).toLowerCase()) || null;
  }

  function setStatus(message, isError = false) {
    const el = q("deckEditorStatus");
    el.textContent = message || "";
    el.classList.toggle("status-error", Boolean(isError));
  }

  function markDirty() {
    state.dirty = true;
    renderTopbar();
  }

  function confirmDiscardChanges() {
    if (!state.dirty || deckTotal() === 0) return true;
    return window.confirm("Discard unsaved changes to the current deck?");
  }

  // ── Data loading ──────────────────────────────────────────────────────────

  async function loadCatalog() {
    const resp = await fetch("/api/cards/catalog");
    if (!resp.ok) throw new Error("could not load card catalog");
    const payload = await resp.json();
    state.catalog = payload.cards || [];
    state.catalogByName = new Map(state.catalog.map((c) => [c.name.toLowerCase(), c]));
    if (window.Legality) window.Legality.setFormats(payload.formats);
    populateSetFilter();
    populateFormatSelect();
  }

  // Fill the deck-editor format picker from the format table shipped with the
  // catalog, so it stays in sync with the server's banlist rules.
  function populateFormatSelect() {
    const select = q("deckFormatSelect");
    if (!select || !window.Legality) return;
    select.innerHTML = "";
    for (const fmt of window.Legality.formats()) {
      const option = document.createElement("option");
      option.value = fmt.key;
      option.textContent = fmt.label;
      select.appendChild(option);
    }
    select.value = currentFormat();
  }

  // Every set a card was printed in: the backend's `sets` membership list
  // (reprints included), falling back to the first printing's `set` code.
  function cardSetCodes(card) {
    if (Array.isArray(card.sets) && card.sets.length > 0) {
      return card.sets.map((s) => s.code).filter(Boolean);
    }
    return card.set ? [card.set] : [];
  }

  // The printing to display for a card: the one matching the active set filter
  // (so a Beta-filtered browser shows Beta art and a LEB badge), else the first
  // printing. Fields default to the catalog entry's own first-printing values.
  function displayPrinting(card) {
    const setFilter = q("browserSetFilter")?.value || "";
    const printings = Array.isArray(card.sets) ? card.sets : [];
    const match = setFilter ? printings.find((s) => s.code === setFilter) : null;
    return {
      code: match ? match.code : card.set,
      name: match ? match.name : card.set_name,
      image_uri: (match && match.image_uri) || card.image_uri,
      large_image_uri: (match && match.large_image_uri) || card.large_image_uri,
      scryfall_uri: (match && match.scryfall_uri) || card.scryfall_uri,
    };
  }

  // Build the set filter's options from the distinct sets present in the loaded
  // catalog, so it stays correct automatically as sets are added to the pool.
  function populateSetFilter() {
    const select = q("browserSetFilter");
    if (!select) return;
    const byCode = new Map();
    for (const card of state.catalog) {
      for (const printing of Array.isArray(card.sets) ? card.sets : []) {
        if (printing.code && !byCode.has(printing.code)) {
          byCode.set(printing.code, printing.name || printing.code.toUpperCase());
        }
      }
      if (card.set && !byCode.has(card.set)) {
        byCode.set(card.set, card.set_name || card.set.toUpperCase());
      }
    }
    const sets = [...byCode.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    select.innerHTML = '<option value="">All sets</option>';
    for (const [code, name] of sets) {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = name;
      select.appendChild(option);
    }
  }

  // Build a deck-list summary for a personal (localStorage) deck, mirroring the
  // shape the server returns for shared decks so both render the same way.
  function summarizePersonalDeck(deck) {
    const cards = (deck.cards || []).map((c) => ({ name: c.name, count: c.count }));
    const colors = new Set();
    let cardCount = 0;
    let unknown = 0;
    let unsupported = 0;
    for (const c of cards) {
      cardCount += c.count;
      const card = lookupCard(c.name);
      if (!card) {
        unknown += c.count;
      } else {
        if (!card.supported) unsupported += c.count;
        for (const col of card.color_identity || []) colors.add(col);
      }
    }
    const fmt = window.Legality ? window.Legality.normalizeFormat(deck.format) : "casual";
    const sideboard = (deck.sideboard || []).map((c) => ({ name: c.name, count: c.count }));
    const commander = (deck.commander || []).map((c) => ({ name: c.name, count: c.count }));
    const legality = window.Legality
      ? window.Legality.validateDeck(cards, fmt, (n) => lookupCard(n), sideboard, commander)
      : { legal: true, problems: [] };
    return {
      id: deck.id,
      name: deck.name,
      description: deck.description || "",
      format: fmt,
      legality: { legal: legality.legal, problems: legality.problems },
      // CR 407.3: ante cards anywhere in this deck, mirroring the server's deck
      // summary so the setup pickers gate personal and shared decks alike.
      ante_names: legality.anteNames || [],
      card_count: cardCount,
      colors: ["W", "U", "B", "R", "G"].filter((c) => colors.has(c)),
      unsupported_count: unsupported,
      unknown_count: unknown,
      sideboard_count: sideboard.reduce((s, c) => s + c.count, 0),
      commander_count: commander.reduce((s, c) => s + c.count, 0),
      updated_at: deck.updated_at,
      scope: "personal",
      cards,
      sideboard,
      commander,
    };
  }

  async function refreshDeckLists() {
    let shared = [];
    try {
      const resp = await fetch("/api/decks");
      if (resp.ok) {
        const payload = await resp.json();
        shared = (payload.decks || []).map((d) => ({ ...d, scope: d.scope || "shared" }));
      }
    } catch {
      shared = [];
    }
    const personal = (window.PersonalDecks?.all() || []).map(summarizePersonalDeck);
    state.decks = [...shared, ...personal];
    renderDeckSelectOptions();
  }

  // CR 407.3: a deck holding ante cards can only be brought to a game played
  // for ante, so those decks are unselectable in the game-setup pickers until
  // the host ticks "Playing for ante". The deck editor's own load picker never
  // blocks — you must still be able to open such a deck to edit it.
  function deckAnteNames(deck) {
    const names = deck.ante_names || deck.legality?.ante_names || [];
    return Array.isArray(names) ? names : [];
  }

  function anteBlocks(deck) {
    return deckAnteNames(deck).length > 0 && !window.isPlayingForAnte?.();
  }

  // Which format a picker judges a deck against. A picker for the game the host
  // is configuring judges every deck against *that game's* format; the deck
  // editor's own load list judges each deck against the one it was saved under.
  // The two are different questions — a Casual-saved 60-card deck is legal as
  // saved and still cannot be brought to a Commander game — and the deck
  // summary the server ships answers only the second, which is why the first is
  // recomputed here from the deck's own card lists.
  function deckLegalityProblems(deck, format) {
    if (!window.Legality || format === deck.format || !Array.isArray(deck.cards)) {
      return orderedProblems(deck.legality?.problems || [], deck.legality?.illegal_names || []);
    }
    // Validated as if the game were not played for ante, matching the server's
    // summaries — deckProblems() below is what forgives those when it applies.
    const result = window.Legality.validateDeck(
      deck.cards, format, lookupCard, deck.sideboard || [], deck.commander || [],
    );
    return orderedProblems(result.problems, [...result.illegalNames]);
  }

  // The problems about the deck as a whole (its size, its sideboard, its
  // command zone) ahead of the ones about a single card, which is not the order
  // they are found in. A tooltip shows the first few, and a Commander picker
  // opening with six near-identical "4 copies exceed the 1-of limit" lines
  // buries the headline: a 60-card deck with nothing in the command zone could
  // not be played however its copies were counted. Told apart by name, the way
  // deckProblems() below tells the ante ones apart.
  function orderedProblems(problems, illegalNames) {
    const aboutOneCard = (p) => (illegalNames || []).some((n) => p.startsWith(n));
    return [...problems.filter((p) => !aboutOneCard(p)), ...problems.filter(aboutOneCard)];
  }

  // Deck summaries are always validated as if the game were not played for
  // ante, so each ante card contributes exactly one problem. In an ante-aware
  // picker with ante turned on those problems no longer apply — drop them so a
  // deck whose only flaw was "needs an ante game" reads as fine. Elsewhere (the
  // deck editor's load list) they stand: the deck really is illegal for normal
  // play.
  function deckProblems(deck, { blockAnte = false, format = null } = {}) {
    const problems = deckLegalityProblems(deck, format || deck.format);
    if (!blockAnte || anteBlocks(deck)) return problems;
    const anteNames = deckAnteNames(deck);
    return problems.filter(
      (p) => !anteNames.some((n) => p.startsWith(`${n} must be removed`)),
    );
  }

  function makeDeckOption(deck, { blockAnte = false, format = null } = {}) {
    const judged = format || deck.format;
    const option = document.createElement("option");
    option.value = deck.id;
    let label = `${deck.name} (${deck.card_count})`;
    const problems = deckProblems(deck, { blockAnte, format });
    const illegal = problems.length > 0;
    const blocked = blockAnte && anteBlocks(deck);
    if (deck.unknown_count > 0 || illegal) label += " ⚠";
    if (blocked) label += " 🚫 ante only";
    option.textContent = label;
    option.disabled = blocked;
    // Read by populateDeckSelectElement, which leaves these out unless the
    // host asks to see them — the tooltip below is then the answer to why.
    if (illegal || blocked) option.dataset.illegal = "1";
    // Native title tooltip explains why the deck is flagged for its format.
    const tips = [];
    if (blocked) {
      tips.push(
        `Contains ante card(s): ${deckAnteNames(deck).join(", ")}.\n` +
        'Tick "Playing for ante" to use this deck (CR 407.3).',
      );
    }
    if (illegal) {
      const shown = problems.slice(0, 6).join("\n");
      const more = problems.length > 6 ? `\n…and ${problems.length - 6} more` : "";
      tips.push(`Not legal in ${window.Legality ? window.Legality.formatLabel(judged) : judged}:\n${shown}${more}`);
    }
    if (deck.unknown_count > 0) tips.push(`${deck.unknown_count} card(s) not in the catalog`);
    if (tips.length) option.title = tips.join("\n\n");
    return option;
  }

  // Populate a single <select> with the current deck list. Exposed on window so
  // app.js can call it for dynamically-created selects (e.g. Free-For-All seat
  // deck pickers) that aren't part of the fixed `configs` list below.
  //
  // Three separate questions decide what a picker offers, and each caller
  // answers them for itself:
  //   `format`     which format's rules a deck is judged against — null judges
  //                each deck by the format it was *saved* under, which is all
  //                the editor's own load picker (and a session id that names no
  //                format) can honestly say.
  //   `hideIllegal` whether the ones that fail leave the list entirely.
  //   `blockAnte`  whether a deck holding ante cards is unselectable (CR 407.3).
  // The defaults are the host page's answers, because every picker on it — the
  // fixed ones and the Free-For-All seats app.js builds — wants them.
  function populateDeckSelectElement(select, placeholder, {
    format = window.selectedGameFormat?.() || "casual",
    hideIllegal = !window.showsIllegalDecks?.(),
    blockAnte = true,
  } = {}) {
    if (!select) return;
    const previous = select.value;
    select.innerHTML = "";
    // CR 903.3: a Commander/Brawl game is led by a designated commander, which
    // a generated random deck doesn't have — so those two formats list saved
    // decks only. Read as a rule off the format key rather than the shipped
    // table's `variant`, for the reason createSession gives: the table arrives
    // with the catalog, and this can run before it.
    const offersRandom = format !== "commander" && format !== "brawl";
    if (offersRandom) {
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = placeholder;
      select.appendChild(blank);
    }
    // A format nobody has named cannot rule a deck out, so it never hides one:
    // the list would be filtered by a rule the player was never shown.
    const hidesIllegal = Boolean(format) && hideIllegal;
    // Group decks by scope so the source of each is unambiguous.
    for (const [scope, groupLabel] of [["personal", "Personal"], ["shared", "Shared"]]) {
      const options = state.decks
        .filter((d) => (d.scope || "shared") === scope)
        .map((deck) => makeDeckOption(deck, { blockAnte, format }))
        .filter((option) => !(hidesIllegal && option.dataset.illegal));
      if (options.length === 0) continue;
      const group = document.createElement("optgroup");
      group.label = groupLabel;
      for (const option of options) group.appendChild(option);
      select.appendChild(group);
    }
    // A previously chosen deck that ante or the format has just ruled out falls
    // back to the first selectable option — the placeholder where the format
    // offers one, otherwise the first listed deck — rather than staying picked
    // but unplayable.
    const kept = [...select.options].find((o) => o.value === previous && !o.disabled);
    if (kept) {
      select.value = previous;
    } else {
      const first = [...select.options].find((o) => !o.disabled);
      select.value = first ? first.value : "";
    }
  }
  window.populateDeckSelectElement = populateDeckSelectElement;

  // Resolve a deck id (shared or personal) to its full summary, so app.js can
  // read a saved deck's display name for the multiplayer lobby roster.
  window.getDeckMeta = (id) => state.decks.find((d) => d.id === id) || null;

  // Re-render every game-setup deck picker (app.js calls this when the host
  // toggles "Playing for ante", which changes which decks are selectable).
  window.refreshDeckSelectOptions = () => renderDeckSelectOptions();

  function renderDeckSelectOptions() {
    const configs = [
      // The editor's load picker must reach every deck, including ante ones and
      // ones no format would seat.
      ["deckLoadSelect", "— Load a deck —", { format: null, hideIllegal: false, blockAnte: false }],
      ["hostDeckSelect", "Random deck"],
      ["guestDeckSelect", "Random deck"],
      // The joining player is judged against the format the *session id* names
      // (null while it names none — a legacy id, or nothing pasted yet), with
      // its own "show the illegal ones" checkbox beside it. Ante is still not
      // knowable from here, so an ante deck stays selectable and the server
      // rejects it with an explanatory error (CR 407.3).
      ["joinDeckSelect", "Random deck", {
        format: window.joinGameFormat?.() ?? null,
        hideIllegal: !window.joinShowsIllegalDecks?.(),
        blockAnte: false,
      }],
    ];
    for (const [id, placeholder, options] of configs) {
      populateDeckSelectElement(q(id), placeholder, options);
    }
    // Free-For-All seat deck selects are created dynamically by app.js; refresh
    // whichever of them currently exist in the DOM too.
    for (const select of document.querySelectorAll(".ffa-deck-select")) {
      populateDeckSelectElement(select, "Random deck");
    }
    syncStartPageColorInputs();
  }

  function setHidden(id, hidden) {
    const el = q(id);
    if (el) el.classList.toggle("hidden", Boolean(hidden));
  }

  function setText(id, text) {
    const el = q(id);
    if (el) el.textContent = text;
  }

  // Lays out the Host form for the selected mode and shows the per-seat colors
  // inputs only when that seat is on a random deck. The host never sets the
  // opponent's name; the opponent's deck is host-configurable only when it's AI.
  function syncStartPageColorInputs() {
    // Free-For-All uses its own per-seat colors inputs (built by app.js); the
    // singular host/guest colors fields this function manages are hidden for
    // that game type, so there's nothing here for it to do.
    const gameTypeEl = q("gameType");
    if (gameTypeEl && gameTypeEl.value === "free_for_all") return;

    const modeEl = q("mode");
    const mode = modeEl ? modeEl.value : "human_vs_ai";
    const isAiVsAi = mode === "ai_vs_ai";
    const isHvh = mode === "human_vs_human";

    // Seat-card titles reflect who sits where in the chosen mode.
    setText("hostSeatTitle", isAiVsAi ? "Player 1 (AI)" : "You");
    setText("guestSeatTitle", isAiVsAi ? "Player 2 (AI)" : isHvh ? "Opponent" : "Opponent (AI)");

    // Host's own name is irrelevant for AI vs AI.
    setHidden("hostNameLabel", isAiVsAi);

    // The opponent's deck is only host-configurable when the opponent is AI —
    // a networked human opponent brings their own deck (and name) on join.
    setHidden("guestDeckLabel", isHvh);
    setHidden("guestOpenNote", !isHvh);

    const hostSel = q("hostDeckSelect");
    const guestSel = q("guestDeckSelect");
    const joinSel = q("joinDeckSelect");
    setHidden("hostColorsLabel", Boolean(hostSel && hostSel.value));
    setHidden("guestColorsLabel", isHvh || Boolean(guestSel && guestSel.value));
    setHidden("joinColorsLabel", Boolean(joinSel && joinSel.value));
  }

  // Let app.js re-run the layout when the mode changes.
  window.syncStartPageColorInputs = syncStartPageColorInputs;

  // ── Navigation ────────────────────────────────────────────────────────────

  function showDeckEditor() {
    hideSetupPanel();
    q("deckEditorPanel").classList.remove("hidden");
    renderAll();
  }

  function hideDeckEditor() {
    q("deckEditorPanel").classList.add("hidden");
    showSetupPanel();
    refreshDeckLists();
  }

  // ── Deck mutations ────────────────────────────────────────────────────────

  function changeCount(name, delta) {
    const key = BOARD_PROPERTY[state.activeBoard];
    const existing = entryFor(name);
    if (existing) {
      existing.count = Math.max(0, Math.min(99, existing.count + delta));
      if (existing.count === 0) {
        state.current[key] = activeEntries().filter((e) => e !== existing);
      }
    } else if (delta > 0) {
      const card = lookupCard(name);
      activeEntries().push({
        name: card ? card.name : name,
        count: Math.min(99, delta),
        status: cardStatus(name),
      });
    } else {
      return;
    }
    markDirty();
    updateBrowserTile(lookupCard(name)?.name || name);
    renderDeckPane();
    renderPreview();
  }

  // Redden a tile's count badge once the card breaks the format's copy limit,
  // so the 5th copy is visible the instant it's added.
  function decorateCountBadge(badge, name) {
    const over = overCopyLimit(name);
    badge.classList.toggle("browser-card-count-over", over);
    badge.title = over ? cardLegalityProblem(name) : "";
  }

  function updateBrowserTile(name) {
    const tile = document.querySelector(
      `#browserGrid .browser-card[data-card-name="${CSS.escape(name)}"]`,
    );
    if (!tile) return;
    const entry = entryFor(name);
    let badge = tile.querySelector(".browser-card-count");
    if (entry) {
      if (!badge) {
        badge = document.createElement("div");
        badge.className = "browser-card-count";
        tile.insertBefore(badge, tile.querySelector(".browser-card-controls"));
      }
      badge.textContent = `×${entry.count}`;
      decorateCountBadge(badge, name);
    } else if (badge) {
      badge.remove();
    }
    const minus = tile.querySelector(".browser-card-controls button");
    if (minus) minus.disabled = !entry;
  }

  function resetDeck(name = "Untitled Deck", entries = [], id = null, scope = "personal", description = "", format = "casual", sideboard = [], commander = []) {
    const fmt = window.Legality ? window.Legality.normalizeFormat(format) : format || "casual";
    state.current = { id, name, description, entries, sideboard, commander, scope, format: fmt };
    state.activeBoard = "main";
    state.dirty = false;
    state.selectedCardName = null;
    q("deckNameInput").value = name;
    q("deckDescriptionInput").value = description;
    const formatSelect = q("deckFormatSelect");
    if (formatSelect) formatSelect.value = fmt;
    renderAll();
  }

  async function loadDeck(deckId) {
    // Personal decks live in localStorage; shared decks are fetched from the server.
    if (window.PersonalDecks?.isPersonalId(deckId)) {
      const deck = window.PersonalDecks.get(deckId);
      if (!deck) throw new Error("could not load deck");
      resetDeck(
        deck.name, (deck.cards || []).map((c) => ({ ...c })), deck.id, "personal",
        deck.description || "", deck.format, (deck.sideboard || []).map((c) => ({ ...c })),
        (deck.commander || []).map((c) => ({ ...c })),
      );
      setStatus(`Loaded "${deck.name}".`);
      return;
    }
    const resp = await fetch(`/api/decks/${encodeURIComponent(deckId)}`);
    if (!resp.ok) throw new Error("could not load deck");
    const deck = await resp.json();
    resetDeck(
      deck.name, deck.cards.map((c) => ({ ...c })), deck.id, "shared",
      deck.description || "", deck.format, (deck.sideboard || []).map((c) => ({ ...c })),
      (deck.commander || []).map((c) => ({ ...c })),
    );
    // Shared decks are read-only here; editing this and saving makes a personal copy.
    setStatus(`Loaded shared deck "${deck.name}" — saving will create a personal copy.`);
  }

  // Clients can only save to their personal (localStorage) decks. Saving while a
  // shared deck is open (or via "Save As Copy") always produces a new personal deck.
  async function saveDeck(asCopy = false) {
    if (!window.PersonalDecks) {
      setStatus("Local storage is unavailable, so decks can't be saved.", true);
      return;
    }
    let name = q("deckNameInput").value.trim() || "Untitled Deck";
    const description = q("deckDescriptionInput").value.trim();
    const cards = state.current.entries.map((e) => ({ name: e.name, count: e.count }));
    const sideboard = activeEntries("sideboard").map((e) => ({ name: e.name, count: e.count }));
    const commander = activeEntries("commander").map((e) => ({ name: e.name, count: e.count }));
    if (cards.length === 0) {
      setStatus("Cannot save an empty deck.", true);
      return;
    }
    const format = currentFormat();
    const isPersonal = state.current.scope === "personal" && state.current.id;
    const makeCopy = asCopy || !isPersonal;
    if (makeCopy && state.current.id) name = `${name} (copy)`;
    let deck;
    try {
      deck = window.PersonalDecks.save({ id: makeCopy ? null : state.current.id, name, description, format, cards, sideboard, commander });
    } catch (e) {
      setStatus(e.message || "Could not save deck.", true);
      return;
    }
    q("deckNameInput").value = deck.name;
    resetDeck(
      deck.name, deck.cards.map((c) => ({ ...c })), deck.id, "personal",
      deck.description || "", deck.format, (deck.sideboard || []).map((c) => ({ ...c })),
      (deck.commander || []).map((c) => ({ ...c })),
    );
    await refreshDeckLists();
    q("deckLoadSelect").value = deck.id;
    renderTopbar();
    const cardCount = deck.cards.reduce((s, c) => s + c.count, 0);
    // Saving never blocks, but surface any format-legality issues as a warning.
    const legality = window.Legality
      ? window.Legality.validateDeck(cards, format, (n) => lookupCard(n), sideboard, commander)
      : { legal: true, problems: [] };
    if (!legality.legal) {
      const first = legality.problems[0] || "";
      const extra = legality.problems.length > 1 ? ` (+${legality.problems.length - 1} more issue${legality.problems.length > 2 ? "s" : ""})` : "";
      setStatus(`Saved "${deck.name}" (${cardCount} cards) — not legal in ${window.Legality.formatLabel(format)}: ${first}${extra}`, true);
    } else {
      setStatus(`Saved personal deck "${deck.name}" (${cardCount} cards).`);
    }
  }

  async function deleteDeck() {
    if (!state.current.id) {
      setStatus("This deck has not been saved yet.", true);
      return;
    }
    if (state.current.scope !== "personal") {
      setStatus("Shared decks are read-only and can't be deleted here.", true);
      return;
    }
    if (!window.confirm(`Delete deck "${state.current.name}"? This cannot be undone.`)) return;
    if (!window.PersonalDecks?.remove(state.current.id)) {
      setStatus("Could not delete deck.", true);
      return;
    }
    await refreshDeckLists();
    resetDeck();
    setStatus("Deck deleted.");
  }

  async function postJsonMethod(url, method, body) {
    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await resp.json();
    if (!resp.ok) throw new Error(payload.detail || "request failed");
    return payload;
  }

  // ── Import ────────────────────────────────────────────────────────────────

  function openImportModal() {
    q("importMoxfieldUrl").value = "";
    q("importDeckText").value = "";
    q("importDeckStatus").textContent = "";
    q("importDeckModal").classList.remove("hidden");
    q("importMoxfieldUrl").focus();
  }

  function closeImportModal() {
    q("importDeckModal").classList.add("hidden");
  }

  async function confirmImport() {
    const url = q("importMoxfieldUrl").value.trim();
    const text = q("importDeckText").value;
    const statusEl = q("importDeckStatus");
    if (!url && !text.trim()) {
      statusEl.textContent = "Enter a Moxfield URL or paste a deck list.";
      return;
    }
    if (!confirmDiscardChanges()) return;
    statusEl.textContent = "Importing…";
    const confirmBtn = q("importDeckConfirmBtn");
    confirmBtn.disabled = true;
    try {
      const result = await postJson("/api/decks/import", url ? { url } : { text });
      const name = url ? result.name : (q("deckNameInput").value.trim() || result.name);
      resetDeck(
        name, result.cards.map((c) => ({ ...c })), null, "personal", "", "casual",
        (result.sideboard || []).map((c) => ({ ...c })),
        (result.commander || []).map((c) => ({ ...c })),
      );
      markDirty();
      closeImportModal();
      const problems = [];
      if (result.unknown_count > 0) problems.push(`${result.unknown_count} card(s) not in the catalog`);
      if (result.unsupported_count > 0) problems.push(`${result.unsupported_count} unsupported card(s)`);
      const suffix = problems.length ? ` — ${problems.join(", ")} highlighted in red.` : ".";
      const sideCount = (result.sideboard || []).reduce((s, c) => s + c.count, 0);
      const sidePart = sideCount ? ` and ${sideCount} sideboard card(s)` : "";
      const cmdCount = (result.commander || []).reduce((s, c) => s + c.count, 0);
      const cmdPart = cmdCount ? ` and ${cmdCount} commander card(s)` : "";
      setStatus(
        `Imported ${result.cards.reduce((s, c) => s + c.count, 0)} cards${sidePart}${cmdPart}${suffix}`,
        problems.length > 0,
      );
    } catch (e) {
      statusEl.textContent = e.message || "Import failed.";
    } finally {
      confirmBtn.disabled = false;
    }
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function renderAll() {
    renderTopbar();
    renderBrowser();
    renderDeckPane();
    renderPreview();
  }

  function renderBoardTabs() {
    const mainBtn = q("deckBoardMainBtn");
    const sideBtn = q("deckBoardSideBtn");
    const cmdBtn = q("deckBoardCommanderBtn");
    if (!mainBtn || !sideBtn) return;
    // Live counts against the format's limits, e.g. "Deck (58/60)" reddened
    // until the minimum is met, "Sideboard (16/15)" once it's overfull.
    const fmt = window.Legality && window.Legality.isChecked(currentFormat())
      ? window.Legality.getFormat(currentFormat())
      : null;
    const main = deckTotal();
    const side = sideboardTotal();
    const mainLimit = fmt && fmt.min_deck ? `/${fmt.min_deck}` : "";
    const sideLimit = fmt && fmt.max_sideboard ? `/${fmt.max_sideboard}` : "";
    mainBtn.textContent = `Deck (${main}${mainLimit})`;
    sideBtn.textContent = `Sideboard (${side}${sideLimit})`;
    mainBtn.classList.toggle(
      "deck-board-tab-problem",
      Boolean(fmt) && (main < fmt.min_deck || (fmt.max_deck != null && main > fmt.max_deck)),
    );
    sideBtn.classList.toggle(
      "deck-board-tab-problem",
      Boolean(fmt) && fmt.max_sideboard != null && side > fmt.max_sideboard,
    );
    mainBtn.classList.toggle("active", state.activeBoard === "main");
    sideBtn.classList.toggle("active", state.activeBoard === "sideboard");
    mainBtn.setAttribute("aria-selected", String(state.activeBoard === "main"));
    sideBtn.setAttribute("aria-selected", String(state.activeBoard === "sideboard"));

    // The Commander tab only exists for formats with a command zone (CR 903.5a).
    const usesCommander = Boolean(fmt && fmt.max_commander);
    if (cmdBtn) {
      cmdBtn.classList.toggle("hidden", !usesCommander);
      if (usesCommander) {
        const cmd = commanderTotal();
        cmdBtn.textContent = `Commander (${cmd}/${fmt.max_commander})`;
        cmdBtn.classList.toggle(
          "deck-board-tab-problem", cmd < fmt.min_commander || cmd > fmt.max_commander,
        );
        cmdBtn.classList.toggle("active", state.activeBoard === "commander");
        cmdBtn.setAttribute("aria-selected", String(state.activeBoard === "commander"));
      }
    }
  }

  function setActiveBoard(board) {
    if (state.activeBoard === board) return;
    state.activeBoard = board;
    state.selectedCardName = null;
    // The browser tiles' count badges track the active board, so redraw them too.
    renderAll();
  }

  function renderTopbar() {
    const total = deckTotal();
    const editingPersonal = Boolean(state.current.id) && state.current.scope === "personal";
    // A shared deck is read-only: saving it writes a new personal copy instead.
    q("deckSaveBtn").textContent = editingPersonal
      ? state.dirty
        ? "Save*"
        : "Save"
      : "Save to Personal";
    q("deckDeleteBtn").disabled = !editingPersonal;
    q("deckSaveAsBtn").disabled = total === 0;
  }

  // CR 903.3: only a legendary creature (or a card that says it can be your
  // commander) can go in the command zone. This card pool has no
  // planeswalkers/"can be your commander" text, so legendary creature is the
  // whole check.
  function isLegendaryCreature(card) {
    const tl = card.type_line.toLowerCase();
    return tl.includes("legendary") && tl.includes("creature");
  }

  function getFilteredCards() {
    const term = q("browserSearch").value.trim().toLowerCase();
    const typeFilter = q("browserTypeFilter").value;
    const rarityFilter = q("browserRarityFilter").value;
    const setFilter = q("browserSetFilter").value;
    const cmcMinRaw = q("browserCmcMin").value;
    const cmcMaxRaw = q("browserCmcMax").value;
    const cmcMin = cmcMinRaw === "" ? null : Number(cmcMinRaw);
    const cmcMax = cmcMaxRaw === "" ? null : Number(cmcMaxRaw);
    const colors = state.colorFilters;
    const legalOnly = q("browserLegalOnlyFilter").checked;

    const matches = state.catalog.filter((card) => {
      if (state.activeBoard === "commander" && !isLegendaryCreature(card)) return false;
      if (term) {
        const haystack = `${card.name}\n${card.type_line}\n${card.oracle_text}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      if (typeFilter && primaryType(card) !== typeFilter) return false;
      if (rarityFilter && card.rarity !== rarityFilter) return false;
      if (setFilter && !cardSetCodes(card).includes(setFilter)) return false;
      if (cmcMin !== null && card.cmc < cmcMin) return false;
      if (cmcMax !== null && card.cmc > cmcMax) return false;
      if (legalOnly && window.Legality && window.Legality.isChecked(currentFormat())) {
        const status = window.Legality.cardStatus(card, currentFormat());
        if (status === "banned" || status === "not_legal") return false;
      }
      if (colors.size > 0) {
        const cardColors = card.colors || [];
        let matched = false;
        if (colors.has("C") && cardColors.length === 0) matched = true;
        if (colors.has("M") && cardColors.length > 1) matched = true;
        for (const c of cardColors) {
          if (colors.has(c)) matched = true;
        }
        if (!matched) return false;
      }
      return true;
    });

    const sortMode = q("browserSortSelect").value;
    const colorKey = (card) => {
      const cardColors = card.colors || [];
      if (cardColors.length === 0) return 6;
      if (cardColors.length > 1) return 5;
      return COLOR_SORT_ORDER[cardColors[0]] ?? 6;
    };
    matches.sort((a, b) => {
      if (sortMode === "cmc" && a.cmc !== b.cmc) return a.cmc - b.cmc;
      if (sortMode === "color" && colorKey(a) !== colorKey(b)) return colorKey(a) - colorKey(b);
      if (sortMode === "type" && primaryType(a) !== primaryType(b)) {
        return primaryType(a).localeCompare(primaryType(b));
      }
      return a.name.localeCompare(b.name);
    });
    return matches;
  }

  function renderBrowser() {
    const grid = q("browserGrid");
    const cards = getFilteredCards();
    q("browserResultCount").textContent = `${cards.length} card${cards.length === 1 ? "" : "s"}`;
    grid.innerHTML = "";

    for (const card of cards) {
      const tile = document.createElement("div");
      tile.className = "browser-card";
      if (!card.supported) tile.classList.add("card-unsupported");
      // Format legality: flag cards banned or not legal in the chosen format.
      const legalStatus =
        window.Legality && window.Legality.isChecked(currentFormat())
          ? window.Legality.cardStatus(card, currentFormat())
          : "legal";
      const isIllegal = legalStatus === "banned" || legalStatus === "not_legal";
      if (isIllegal) {
        tile.classList.add("card-illegal");
        tile.title = window.Legality.cardProblem(card, currentFormat());
      }
      if (state.selectedCardName === card.name) tile.classList.add("selected");
      tile.dataset.cardName = card.name;

      const printing = displayPrinting(card);
      if (printing.image_uri) {
        const img = document.createElement("img");
        img.src = printing.image_uri;
        img.alt = card.name;
        img.loading = "lazy";
        img.draggable = false;
        tile.appendChild(img);
      } else {
        const fallback = document.createElement("div");
        fallback.className = "browser-card-fallback";
        fallback.textContent = card.name;
        tile.appendChild(fallback);
      }

      if (printing.code) {
        const setBadge = document.createElement("div");
        setBadge.className = "browser-card-set";
        setBadge.textContent = printing.code.toUpperCase();
        setBadge.title = printing.name || printing.code;
        tile.appendChild(setBadge);
      }

      const inDeck = entryFor(card.name);
      if (inDeck) {
        const badge = document.createElement("div");
        badge.className = "browser-card-count";
        badge.textContent = `×${inDeck.count}`;
        decorateCountBadge(badge, card.name);
        tile.appendChild(badge);
      }
      if (!card.supported) {
        const flag = document.createElement("div");
        flag.className = "card-unsupported-flag";
        flag.textContent = "Unsupported";
        tile.appendChild(flag);
      }
      if (isIllegal) {
        const flag = document.createElement("div");
        flag.className = "card-illegal-flag";
        flag.textContent = legalStatus === "banned" ? "Banned" : "Not Legal";
        tile.appendChild(flag);
      }

      const controls = document.createElement("div");
      controls.className = "browser-card-controls";
      const minus = document.createElement("button");
      minus.type = "button";
      minus.textContent = "−";
      minus.title = "Remove one";
      minus.disabled = !inDeck;
      minus.addEventListener("click", (event) => {
        event.stopPropagation();
        changeCount(card.name, -1);
      });
      const plus = document.createElement("button");
      plus.type = "button";
      plus.textContent = "+";
      plus.title = "Add one";
      plus.addEventListener("click", (event) => {
        event.stopPropagation();
        changeCount(card.name, 1);
      });
      controls.appendChild(minus);
      controls.appendChild(plus);
      tile.appendChild(controls);

      tile.addEventListener("click", () => selectCard(card.name));
      grid.appendChild(tile);
    }

    if (cards.length === 0) {
      const empty = document.createElement("div");
      empty.className = "browser-empty";
      empty.textContent =
        state.activeBoard === "commander"
          ? state.catalog.some(isLegendaryCreature)
            ? "No legendary creatures match the current filters."
            : "No legendary creatures in the current card pool (LEA/LEB/2ED/ARN predate the Legendary supertype, introduced in Legends)."
          : "No cards match the current filters.";
      grid.appendChild(empty);
    }
  }

  function renderDeckPane() {
    renderBoardTabs();
    // Stats describe whichever board is being edited, so the numbers match the
    // list below them.
    const entries = activeEntries();
    const total = entries.reduce((sum, e) => sum + e.count, 0);
    const landCount = entries
      .filter((e) => {
        const card = lookupCard(e.name);
        return card && primaryType(card) === "land";
      })
      .reduce((sum, e) => sum + e.count, 0);
    const problemCount = entries
      .filter((e) => e.status !== "ok")
      .reduce((sum, e) => sum + e.count, 0);

    const stats = q("deckStats");
    let statsHtml = `<span class="deck-stat-total">${total} cards</span> · ${landCount} lands`;
    if (problemCount > 0) {
      statsHtml += ` · <span class="deck-stat-problem">${problemCount} unsupported</span>`;
    }
    stats.innerHTML = statsHtml;

    renderLegalitySummary();
    renderCurve();
    renderDeckList();
    renderTopbar();
  }

  // Deck-level legality banner: OK badge when the deck is legal for its format,
  // or a red list of the specific rule violations. Always covers both boards
  // (deck size, sideboard cap, and the combined copy limit), whichever tab is
  // open, so a sideboard problem can't hide behind the mainboard view.
  function renderLegalitySummary() {
    const el = q("deckLegality");
    if (!el) return;
    const format = currentFormat();
    if (!window.Legality || !window.Legality.isChecked(format)) {
      el.className = "deck-legality";
      el.innerHTML = "";
      return;
    }
    const cards = state.current.entries.map((e) => ({ name: e.name, count: e.count }));
    const side = activeEntries("sideboard").map((e) => ({ name: e.name, count: e.count }));
    const cmd = activeEntries("commander").map((e) => ({ name: e.name, count: e.count }));
    const legality = window.Legality.validateDeck(cards, format, (n) => lookupCard(n), side, cmd);
    const label = window.Legality.formatLabel(format);
    if (legality.legal) {
      el.className = "deck-legality deck-legality-ok";
      el.innerHTML = `<span class="deck-legality-icon">✓</span> Legal in ${escapeHtml(label)}`;
      return;
    }
    el.className = "deck-legality deck-legality-bad";
    const items = legality.problems.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
    el.innerHTML =
      `<div class="deck-legality-head"><span class="deck-legality-icon">⚠</span> ` +
      `${legality.problems.length} issue${legality.problems.length === 1 ? "" : "s"} for ${escapeHtml(label)}</div>` +
      `<ul class="deck-legality-list">${items}</ul>`;
  }

  function renderCurve() {
    const curveEl = q("deckCurve");
    const buckets = new Array(8).fill(0); // 0..6, 7+
    let any = false;
    for (const entry of state.current.entries) {
      const card = lookupCard(entry.name);
      if (!card || primaryType(card) === "land") continue;
      const bucket = Math.min(7, Math.max(0, Math.floor(card.cmc)));
      buckets[bucket] += entry.count;
      any = true;
    }
    curveEl.innerHTML = "";
    if (!any) return;
    const max = Math.max(...buckets, 1);
    for (let i = 0; i < buckets.length; i += 1) {
      const col = document.createElement("div");
      col.className = "deck-curve-col";
      const bar = document.createElement("div");
      bar.className = "deck-curve-bar";
      bar.style.height = `${Math.round((buckets[i] / max) * 100)}%`;
      bar.title = `${buckets[i]} card(s) with mana value ${i === 7 ? "7+" : i}`;
      const count = document.createElement("div");
      count.className = "deck-curve-count";
      count.textContent = buckets[i] || "";
      const label = document.createElement("div");
      label.className = "deck-curve-label";
      label.textContent = i === 7 ? "7+" : String(i);
      col.appendChild(count);
      col.appendChild(bar);
      col.appendChild(label);
      curveEl.appendChild(col);
    }
  }

  function renderDeckList() {
    const listEl = q("deckList");
    const entries = activeEntries();
    listEl.innerHTML = "";

    const groups = new Map(TYPE_GROUPS.map(([key, label]) => [key, { label, entries: [] }]));
    groups.set("other", { label: "Other", entries: [] });
    groups.set("unknown", { label: "Not in Catalog", entries: [] });

    for (const entry of entries) {
      const card = lookupCard(entry.name);
      const key = card ? primaryType(card) : "unknown";
      (groups.get(key) || groups.get("other")).entries.push(entry);
    }

    for (const [, group] of groups) {
      if (group.entries.length === 0) continue;
      const groupCount = group.entries.reduce((sum, e) => sum + e.count, 0);

      const header = document.createElement("div");
      header.className = "deck-group-header";
      header.textContent = `${group.label} (${groupCount})`;
      listEl.appendChild(header);

      group.entries
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .forEach((entry) => {
          const card = lookupCard(entry.name);
          const legalProblem = cardLegalityProblem(entry.name);
          const row = document.createElement("div");
          row.className = "deck-row";
          if (entry.status !== "ok" || legalProblem) row.classList.add("deck-row-problem");
          if (state.selectedCardName === entry.name) row.classList.add("selected");

          const count = document.createElement("span");
          count.className = "deck-row-count";
          count.textContent = `${entry.count}×`;

          const name = document.createElement("span");
          name.className = "deck-row-name";
          name.textContent = entry.name;
          const engineTip = entry.status === "unknown"
            ? "This card is not in the supported catalog"
            : entry.status === "unsupported"
              ? "The game engine does not support this card yet"
              : "";
          name.title = [engineTip, legalProblem].filter(Boolean).join("\n");

          const mana = document.createElement("span");
          mana.className = "deck-row-mana";
          if (card && card.mana_cost) {
            mana.innerHTML = renderSymbolsInline(card.mana_cost, "mtg-symbol-inline");
          }

          const controls = document.createElement("span");
          controls.className = "deck-row-controls";
          const minus = document.createElement("button");
          minus.type = "button";
          minus.textContent = "−";
          minus.addEventListener("click", (event) => {
            event.stopPropagation();
            changeCount(entry.name, -1);
          });
          const plus = document.createElement("button");
          plus.type = "button";
          plus.textContent = "+";
          plus.addEventListener("click", (event) => {
            event.stopPropagation();
            changeCount(entry.name, 1);
          });
          const removeAll = document.createElement("button");
          removeAll.type = "button";
          removeAll.textContent = "✕";
          removeAll.title = "Remove all copies";
          removeAll.addEventListener("click", (event) => {
            event.stopPropagation();
            changeCount(entry.name, -entry.count);
          });
          controls.appendChild(minus);
          controls.appendChild(plus);
          controls.appendChild(removeAll);

          row.appendChild(count);
          row.appendChild(name);
          row.appendChild(mana);
          row.appendChild(controls);
          row.addEventListener("click", () => selectCard(entry.name));
          listEl.appendChild(row);
        });
    }

    if (entries.length === 0) {
      const empty = document.createElement("div");
      empty.className = "deck-list-empty";
      empty.textContent =
        state.activeBoard === "sideboard"
          ? "Sideboard is empty. Add cards from the browser on the left — Ring of Ma'rûf fetches from here."
          : state.activeBoard === "commander"
            ? "No commander designated yet. Add it from the browser on the left."
            : "Deck is empty. Add new cards from the browser on the left.";
      listEl.appendChild(empty);
    }
  }

  function selectCard(name) {
    state.selectedCardName = name;
    renderPreview();
    // Refresh selection highlight without rebuilding everything.
    for (const tile of document.querySelectorAll("#browserGrid .browser-card")) {
      tile.classList.toggle("selected", tile.dataset.cardName === name);
    }
    for (const row of document.querySelectorAll("#deckList .deck-row")) {
      const rowName = row.querySelector(".deck-row-name")?.textContent;
      row.classList.toggle("selected", rowName === name);
    }
  }

  function renderPreview() {
    const name = state.selectedCardName;
    const frame = q("editorPreviewFrame");
    const image = q("editorPreviewImage");
    const cardBack = q("editorPreviewCardBack");
    const emptyEl = q("editorPreviewEmpty");
    const warning = q("editorPreviewWarning");
    const setEl = q("editorPreviewSet");
    const addBtn = q("editorPreviewAddBtn");
    const removeBtn = q("editorPreviewRemoveBtn");

    if (!name) {
      // Nothing selected: show a card back so the pane always reads as a card.
      frame.classList.add("empty-preview");
      image.classList.add("hidden");
      image.removeAttribute("src");
      cardBack.classList.remove("hidden");
      emptyEl.classList.add("hidden");
      q("editorPreviewName").textContent = "No card selected";
      q("editorPreviewType").textContent = "";
      setEl.textContent = "";
      q("editorPreviewText").textContent = "";
      q("editorPreviewScryfallLink").classList.add("hidden");
      warning.classList.add("hidden");
      addBtn.disabled = true;
      removeBtn.disabled = true;
      return;
    }

    // A real card is selected, so the card back stays hidden behind it.
    cardBack.classList.add("hidden");

    const card = lookupCard(name);
    const entry = entryFor(name);
    const printing = card ? displayPrinting(card) : null;
    setEl.textContent = printing && printing.name ? printing.name : "";

    const scryfallLink = q("editorPreviewScryfallLink");
    if (printing && printing.scryfall_uri) {
      scryfallLink.href = printing.scryfall_uri;
      scryfallLink.classList.remove("hidden");
    } else {
      scryfallLink.classList.add("hidden");
    }

    let nameHtml = escapeHtml(name);
    if (card && card.mana_cost) {
      nameHtml += ` <span class="card-preview-cost">${renderSymbolsInline(card.mana_cost, "mtg-symbol-inline")}</span>`;
    }
    q("editorPreviewName").innerHTML = nameHtml;
    q("editorPreviewType").textContent = card ? card.type_line : "";
    if (card) {
      let text = card.oracle_text || "";
      if (card.power != null && card.toughness != null) {
        text = text ? `${text}\n${card.power}/${card.toughness}` : `${card.power}/${card.toughness}`;
      }
      q("editorPreviewText").innerHTML = renderSymbolsInline(text, "mtg-symbol-inline").replace(/\n/g, "<br>");
    } else {
      q("editorPreviewText").textContent = "";
    }

    const imageUri = printing ? (printing.large_image_uri || printing.image_uri) : null;
    if (imageUri) {
      image.src = imageUri;
      image.classList.remove("hidden");
      emptyEl.classList.add("hidden");
      frame.classList.remove("empty-preview");
    } else {
      image.classList.add("hidden");
      image.removeAttribute("src");
      emptyEl.classList.remove("hidden");
      emptyEl.textContent = card ? "No image available." : "Card not found in the catalog.";
      frame.classList.add("empty-preview");
    }

    const legalProblem = card ? cardLegalityProblem(name, entry ? entry.count : 0) : "";
    if (!card) {
      warning.textContent = "⚠ This card is not in the supported catalog and cannot be played.";
      warning.classList.remove("hidden");
    } else if (!card.supported) {
      let text = `⚠ Unsupported by the game engine${card.unsupported_reason ? `: ${card.unsupported_reason}` : "."}`;
      if (legalProblem) text += `\n⚠ ${legalProblem}`;
      warning.textContent = text;
      warning.classList.remove("hidden");
    } else if (legalProblem) {
      warning.textContent = `⚠ ${legalProblem}`;
      warning.classList.remove("hidden");
    } else {
      warning.classList.add("hidden");
    }

    addBtn.disabled = !card;
    addBtn.textContent = entry ? `Add (have ${entry.count})` : "Add to Deck";
    removeBtn.disabled = !entry;
  }

  // ── Event wiring ──────────────────────────────────────────────────────────

  function bindEvents() {
    q("deckEditorBtn")?.addEventListener("click", () => {
      showDeckEditor();
    });
    q("deckEditorBackBtn").addEventListener("click", () => {
      hideDeckEditor();
    });

    q("deckLoadSelect").addEventListener("change", async (event) => {
      const deckId = event.target.value;
      if (!deckId) return;
      if (!confirmDiscardChanges()) {
        event.target.value = state.current.id || "";
        return;
      }
      try {
        await loadDeck(deckId);
      } catch (e) {
        setStatus(e.message || "Could not load deck.", true);
      }
    });

    q("deckNewBtn").addEventListener("click", () => {
      if (!confirmDiscardChanges()) return;
      q("deckLoadSelect").value = "";
      resetDeck();
      setStatus("Started a new deck.");
    });

    q("deckSaveBtn").addEventListener("click", async () => {
      try {
        await saveDeck(false);
      } catch (e) {
        setStatus(e.message || "Could not save deck.", true);
      }
    });

    q("deckSaveAsBtn").addEventListener("click", async () => {
      try {
        await saveDeck(true);
      } catch (e) {
        setStatus(e.message || "Could not save deck.", true);
      }
    });

    q("deckDeleteBtn").addEventListener("click", async () => {
      try {
        await deleteDeck();
      } catch (e) {
        setStatus(e.message || "Could not delete deck.", true);
      }
    });

    q("deckNameInput").addEventListener("input", () => {
      state.current.name = q("deckNameInput").value;
      markDirty();
    });

    q("deckDescriptionInput").addEventListener("input", () => {
      state.current.description = q("deckDescriptionInput").value;
      markDirty();
    });

    q("deckFormatSelect")?.addEventListener("change", (event) => {
      state.current.format = window.Legality
        ? window.Legality.normalizeFormat(event.target.value)
        : event.target.value;
      // Switching away from a format with a command zone while the Commander
      // tab is open would leave it open on a now-hidden tab.
      const fmt = window.Legality ? window.Legality.getFormat(state.current.format) : null;
      if (state.activeBoard === "commander" && !(fmt && fmt.max_commander)) {
        state.activeBoard = "main";
      }
      markDirty();
      // Legality flags are format-dependent, so re-render everything.
      renderAll();
    });

    q("deckBoardMainBtn")?.addEventListener("click", () => setActiveBoard("main"));
    q("deckBoardSideBtn")?.addEventListener("click", () => setActiveBoard("sideboard"));
    q("deckBoardCommanderBtn")?.addEventListener("click", () => setActiveBoard("commander"));

    q("deckImportBtn").addEventListener("click", openImportModal);
    q("importDeckCancelBtn").addEventListener("click", closeImportModal);
    q("importDeckConfirmBtn").addEventListener("click", confirmImport);
    q("importDeckModal").addEventListener("click", (event) => {
      if (event.target === q("importDeckModal")) closeImportModal();
    });

    q("browserSearch").addEventListener("input", renderBrowser);
    q("browserTypeFilter").addEventListener("change", renderBrowser);
    q("browserRarityFilter").addEventListener("change", renderBrowser);
    q("browserSetFilter").addEventListener("change", () => {
      renderBrowser();
      renderPreview(); // the preview's art/set follow the filtered printing
    });
    q("browserCmcMin").addEventListener("input", renderBrowser);
    q("browserCmcMax").addEventListener("input", renderBrowser);
    q("browserSortSelect").addEventListener("change", renderBrowser);
    q("browserLegalOnlyFilter").addEventListener("change", renderBrowser);

    for (const btn of document.querySelectorAll("#browserColorFilters .color-filter-btn")) {
      btn.addEventListener("click", () => {
        const color = btn.dataset.color;
        if (state.colorFilters.has(color)) {
          state.colorFilters.delete(color);
          btn.classList.remove("active");
        } else {
          state.colorFilters.add(color);
          btn.classList.add("active");
        }
        renderBrowser();
      });
    }

    q("browserClearFiltersBtn").addEventListener("click", () => {
      q("browserSearch").value = "";
      q("browserTypeFilter").value = "";
      q("browserRarityFilter").value = "";
      q("browserSetFilter").value = "";
      q("browserCmcMin").value = "";
      q("browserCmcMax").value = "";
      q("browserLegalOnlyFilter").checked = true;
      state.colorFilters.clear();
      for (const btn of document.querySelectorAll("#browserColorFilters .color-filter-btn")) {
        btn.classList.remove("active");
      }
      renderBrowser();
      renderPreview(); // clearing the set filter reverts the preview's printing
    });

    q("editorPreviewAddBtn").addEventListener("click", () => {
      if (state.selectedCardName) changeCount(state.selectedCardName, 1);
    });
    q("editorPreviewRemoveBtn").addEventListener("click", () => {
      if (state.selectedCardName) changeCount(state.selectedCardName, -1);
    });

    q("hostDeckSelect")?.addEventListener("change", syncStartPageColorInputs);
    q("guestDeckSelect")?.addEventListener("change", syncStartPageColorInputs);
    q("joinDeckSelect")?.addEventListener("change", syncStartPageColorInputs);
  }

  async function init() {
    bindEvents();
    renderColorFilterIcons();
    window.refreshDeckEditorSymbols = renderColorFilterIcons;
    try {
      await loadCatalog();
    } catch {
      setStatus("Could not load the card catalog.", true);
    }
    await refreshDeckLists();
    resetDeck();
  }

  init();
})();
