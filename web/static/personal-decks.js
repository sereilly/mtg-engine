// Personal deck store. Unlike the shared decks served from the server's `decks/`
// folder (read-only to clients), personal decks live entirely in this browser's
// localStorage. They are played by sending their cards inline at game start, so
// the server never persists them. Exposed as `window.PersonalDecks`.
(() => {
  const STORAGE_KEY = "magic.personalDecks.v1";
  const ID_PREFIX = "local-";

  function isPersonalId(id) {
    return typeof id === "string" && id.startsWith(ID_PREFIX);
  }

  function newId() {
    const rand =
      window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    return ID_PREFIX + rand;
  }

  function readAll() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed.filter((d) => d && d.id && d.name != null) : [];
    } catch {
      return [];
    }
  }

  function writeAll(decks) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(decks));
      return true;
    } catch {
      return false;
    }
  }

  function normalizeCards(cards) {
    const merged = new Map();
    for (const entry of cards || []) {
      const name = String(entry && entry.name ? entry.name : "").trim();
      const count = Number(entry && entry.count ? entry.count : 0);
      if (!name || count <= 0) continue;
      merged.set(name, (merged.get(name) || 0) + count);
    }
    return [...merged.entries()].map(([name, count]) => ({ name, count }));
  }

  // Returns raw decks {id, name, cards, created_at, updated_at}, sorted by name.
  function all() {
    return readAll().sort((a, b) =>
      String(a.name).localeCompare(String(b.name), undefined, { sensitivity: "base" }),
    );
  }

  function get(id) {
    return readAll().find((d) => d.id === id) || null;
  }

  // Create (no id / unknown id) or update (existing id). Returns the saved deck.
  function save({ id, name, description, cards }) {
    const decks = readAll();
    const now = Date.now() / 1000;
    const cleanName = String(name || "Untitled Deck").trim() || "Untitled Deck";
    const cleanDescription = String(description || "").trim();
    const cleanCards = normalizeCards(cards);
    const idx = id ? decks.findIndex((d) => d.id === id) : -1;
    let deck;
    if (idx >= 0) {
      deck = { ...decks[idx], name: cleanName, description: cleanDescription, cards: cleanCards, updated_at: now };
      decks[idx] = deck;
    } else {
      deck = {
        id: newId(),
        name: cleanName,
        description: cleanDescription,
        cards: cleanCards,
        created_at: now,
        updated_at: now,
      };
      decks.push(deck);
    }
    if (!writeAll(decks)) throw new Error("Could not save to local storage (it may be full or disabled).");
    return deck;
  }

  function remove(id) {
    const decks = readAll();
    const next = decks.filter((d) => d.id !== id);
    if (next.length === decks.length) return false;
    return writeAll(next);
  }

  window.PersonalDecks = { all, get, save, remove, isPersonalId };
})();
