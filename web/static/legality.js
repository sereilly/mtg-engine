// Shared MTG format-legality / banlist checks for the browser. Mirrors the
// server-side rules in web/deck_legality.py (the format table is shipped to the
// client in the /api/cards/catalog payload, so both share one source of truth
// for the rule parameters). Used by the deck editor for live feedback and to
// validate personal (localStorage) decks that never touch the server.
//
// Exposed as `window.Legality`.
(() => {
  // Fallback format table, used only if the catalog payload hasn't loaded yet.
  // Kept minimal — the authoritative list arrives via setFormats() from the
  // /api/cards/catalog response.
  let FORMATS = [
    { key: "casual", label: "Casual (no restrictions)", scryfall_key: null, min_deck: 0, max_deck: null, max_copies: 99, singleton: false },
  ];
  let byKey = new Map(FORMATS.map((f) => [f.key, f]));
  const DEFAULT_FORMAT = "casual";

  function setFormats(list) {
    if (Array.isArray(list) && list.length > 0) {
      FORMATS = list;
      byKey = new Map(FORMATS.map((f) => [f.key, f]));
    }
  }

  function formats() {
    return FORMATS;
  }

  function normalizeFormat(key) {
    return key && byKey.has(key) ? key : DEFAULT_FORMAT;
  }

  function getFormat(key) {
    return byKey.get(normalizeFormat(key)) || null;
  }

  function formatLabel(key) {
    const fmt = byKey.get(key);
    return fmt ? fmt.label : key || "";
  }

  // Does this format actually enforce a banlist? Casual (no scryfall_key) doesn't.
  function isChecked(key) {
    const fmt = byKey.get(normalizeFormat(key));
    return Boolean(fmt && fmt.scryfall_key);
  }

  // Legality of a single card in a format: "legal" | "restricted" | "banned" |
  // "not_legal". Reads straight from the card's Scryfall `legalities` map.
  function cardStatus(card, key) {
    const fmt = getFormat(key);
    if (!fmt || !fmt.scryfall_key) return "legal";
    const value = card && card.legalities ? card.legalities[fmt.scryfall_key] : undefined;
    if (value === "legal" || value === "restricted" || value === "banned") return value;
    return "not_legal";
  }

  function isBasicLand(card) {
    const tl = String((card && card.type_line) || "").toLowerCase();
    return tl.includes("basic") && tl.includes("land");
  }

  function anyNumberAllowed(card) {
    return String((card && card.oracle_text) || "")
      .toLowerCase()
      .includes("a deck can have any number of cards named");
  }

  // Copy limit for a legal/restricted card, or null for unlimited.
  function effectiveMaxCopies(card, fmt, status) {
    if (isBasicLand(card) || anyNumberAllowed(card)) return null;
    let limit = fmt.max_copies;
    if (status === "restricted") limit = Math.min(limit, 1);
    if (fmt.singleton) limit = Math.min(limit, 1);
    return limit;
  }

  // Human-readable reason a card is illegal in a format, or "" if it's fine.
  // `count` lets it report copy-limit violations; pass 0/omitted to only check
  // the card's own ban/legality status (used for browser tiles).
  function cardProblem(card, key, count = 0) {
    const fmt = getFormat(key);
    if (!card || !fmt || !fmt.scryfall_key) return "";
    const status = cardStatus(card, key);
    if (status === "banned") return `${card.name} is banned in ${fmt.label}.`;
    if (status === "not_legal") return `${card.name} is not legal in ${fmt.label}.`;
    const limit = effectiveMaxCopies(card, fmt, status);
    if (count && limit != null && count > limit) {
      if (status === "restricted") return `${card.name} is restricted to 1 copy in ${fmt.label} (deck has ${count}).`;
      if (limit === 1) return `${card.name}: ${count} copies exceed the 1-of limit in ${fmt.label}.`;
      return `${card.name}: ${count} copies exceed the ${limit}-copy limit in ${fmt.label}.`;
    }
    return "";
  }

  // Validate a whole deck. `entries` is [{name, count}]; `lookupCard(name)`
  // resolves a name to a catalog card (or null). Returns
  // {format, legal, problems:[str], illegalNames:Set}. Cards not in the catalog
  // are skipped — they're surfaced separately as "not in catalog".
  function validateDeck(entries, key, lookupCard) {
    const fmt = getFormat(key);
    const result = { format: fmt ? fmt.key : DEFAULT_FORMAT, legal: true, problems: [], illegalNames: new Set() };
    if (!fmt || !fmt.scryfall_key) return result;

    let total = 0;
    for (const entry of entries || []) {
      const name = String((entry && entry.name) || "").trim();
      const count = Number((entry && entry.count) || 0);
      if (!name || count <= 0) continue;
      total += count;
      const card = lookupCard(name);
      if (!card) continue;
      const problem = cardProblem(card, key, count);
      if (problem) {
        result.problems.push(problem);
        result.illegalNames.add(card.name);
      }
    }
    if (total < fmt.min_deck) {
      result.problems.push(`Deck has ${total} card(s); ${fmt.label} requires at least ${fmt.min_deck}.`);
    }
    if (fmt.max_deck != null && total > fmt.max_deck) {
      result.problems.push(`Deck has ${total} card(s); ${fmt.label} allows at most ${fmt.max_deck}.`);
    }
    result.legal = result.problems.length === 0;
    return result;
  }

  window.Legality = {
    setFormats,
    formats,
    normalizeFormat,
    getFormat,
    formatLabel,
    isChecked,
    cardStatus,
    cardProblem,
    validateDeck,
    DEFAULT_FORMAT,
  };
})();
