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
    { key: "casual", label: "Casual (no restrictions)", scryfall_key: null, min_deck: 0, max_deck: null, max_copies: 99, max_sideboard: null, singleton: false },
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

  // English-join zone names for an overage message ("deck and sideboard",
  // "deck, sideboard, and commander"). Empty/single-item lists join to "".
  function joinZones(zones) {
    if (zones.length < 2) return "";
    if (zones.length === 2) return `${zones[0]} and ${zones[1]}`;
    return `${zones.slice(0, -1).join(", ")}, and ${zones[zones.length - 1]}`;
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
  // `count` is the main-deck count, `sideCount` the sideboard count, and
  // `cmdCount` the commander (command zone) count; the copy limit applies to
  // their sum (CR 100.4a). Pass 0/omit all three to only check the card's own
  // ban/legality status (used for browser tiles).
  function cardProblem(card, key, count = 0, sideCount = 0, cmdCount = 0) {
    const fmt = getFormat(key);
    if (!card || !fmt || !fmt.scryfall_key) return "";
    const status = cardStatus(card, key);
    if (status === "banned") return `${card.name} is banned in ${fmt.label}.`;
    if (status === "not_legal") return `${card.name} is not legal in ${fmt.label}.`;
    const limit = effectiveMaxCopies(card, fmt, status);
    const total = Number(count || 0) + Number(sideCount || 0) + Number(cmdCount || 0);
    if (total && limit != null && total > limit) {
      // Name the zones that actually contribute to the overage.
      const zones = [];
      if (count) zones.push("deck");
      if (sideCount) zones.push("sideboard");
      if (cmdCount) zones.push("commander");
      const where = zones.length > 1 ? ` across ${joinZones(zones)}` : "";
      if (status === "restricted") return `${card.name} is restricted to 1 copy in ${fmt.label} (deck has ${total}${where}).`;
      if (limit === 1) return `${card.name}: ${total} copies${where} exceed the 1-of limit in ${fmt.label}.`;
      return `${card.name}: ${total} copies${where} exceed the ${limit}-copy limit in ${fmt.label}.`;
    }
    return "";
  }

  // How many copies of `card` a deck may hold in this format, or null for
  // unlimited (basic lands, "any number" cards, and unchecked formats).
  function copyLimit(card, key) {
    const fmt = getFormat(key);
    if (!card || !fmt || !fmt.scryfall_key) return null;
    return effectiveMaxCopies(card, fmt, cardStatus(card, key));
  }

  // Sum an entry list into a Map of lowercased name -> count, plus a total.
  function tally(entries) {
    const counts = new Map();
    let total = 0;
    for (const entry of entries || []) {
      const name = String((entry && entry.name) || "").trim();
      const count = Number((entry && entry.count) || 0);
      if (!name || count <= 0) continue;
      const key = name.toLowerCase();
      counts.set(key, (counts.get(key) || 0) + count);
      total += count;
    }
    return { counts, total };
  }

  // Validate a whole deck. `entries`/`sideboard`/`commander` are [{name, count}];
  // `lookupCard(name)` resolves a name to a catalog card (or null). Returns
  // {format, legal, problems:[str], illegalNames:Set}. Cards not in the catalog
  // are skipped — they're surfaced separately as "not in catalog".
  function validateDeck(entries, key, lookupCard, sideboard = null, commander = null) {
    const fmt = getFormat(key);
    const result = { format: fmt ? fmt.key : DEFAULT_FORMAT, legal: true, problems: [], illegalNames: new Set() };
    if (!fmt || !fmt.scryfall_key) return result;

    const main = tally(entries);
    const side = tally(sideboard);
    const cmd = tally(commander);
    // Main-deck order first, then sideboard/commander-only cards.
    const names = [
      ...main.counts.keys(),
      ...[...side.counts.keys()].filter((n) => !main.counts.has(n)),
      ...[...cmd.counts.keys()].filter((n) => !main.counts.has(n) && !side.counts.has(n)),
    ];
    for (const name of names) {
      const card = lookupCard(name);
      if (!card) continue;
      const problem = cardProblem(
        card, key, main.counts.get(name) || 0, side.counts.get(name) || 0, cmd.counts.get(name) || 0,
      );
      if (problem) {
        result.problems.push(problem);
        result.illegalNames.add(card.name);
      }
    }
    if (main.total < fmt.min_deck) {
      result.problems.push(`Deck has ${main.total} card(s); ${fmt.label} requires at least ${fmt.min_deck}.`);
    }
    if (fmt.max_deck != null && main.total > fmt.max_deck) {
      result.problems.push(`Deck has ${main.total} card(s); ${fmt.label} allows at most ${fmt.max_deck}.`);
    }
    if (fmt.max_sideboard != null && side.total > fmt.max_sideboard) {
      if (fmt.max_sideboard === 0) {
        result.problems.push(`${fmt.label} does not use a sideboard (sideboard has ${side.total} card(s)).`);
      } else {
        result.problems.push(`Sideboard has ${side.total} card(s); ${fmt.label} allows at most ${fmt.max_sideboard}.`);
      }
    }
    const minCmd = fmt.min_commander || 0;
    const maxCmd = fmt.max_commander || 0;
    if (maxCmd === 0 && cmd.total > 0) {
      result.problems.push(`${fmt.label} does not use a commander (commander zone has ${cmd.total} card(s)).`);
    } else if (cmd.total > maxCmd) {
      result.problems.push(`Commander zone has ${cmd.total} card(s); ${fmt.label} allows at most ${maxCmd}.`);
    } else if (cmd.total < minCmd) {
      result.problems.push(`${fmt.label} requires ${minCmd} designated commander card(s) (found ${cmd.total}).`);
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
    copyLimit,
    validateDeck,
    DEFAULT_FORMAT,
  };
})();
