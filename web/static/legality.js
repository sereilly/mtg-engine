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
    { key: "casual", label: "Casual (no restrictions)", session_code: "qf", scryfall_key: null, min_deck: 0, max_deck: null, max_copies: 99, max_sideboard: null, singleton: false },
  ];
  let byKey = new Map(FORMATS.map((f) => [f.key, f]));
  let byCode = new Map(FORMATS.map((f) => [f.session_code, f]));
  const DEFAULT_FORMAT = "casual";

  function setFormats(list) {
    if (Array.isArray(list) && list.length > 0) {
      FORMATS = list;
      byKey = new Map(FORMATS.map((f) => [f.key, f]));
      byCode = new Map(FORMATS.map((f) => [f.session_code, f]));
      // Anything read off the table before it arrived — the Join screen's
      // format, decoded from a session id below — was answered against the
      // one-row fallback and is stale now. An optional callback rather than a
      // DOM event because this file is DOM-free by design (the parity test
      // evaluates it in bare node, with `window` an empty object).
      if (typeof window.onLegalityFormatsLoaded === "function") {
        window.onLegalityFormatsLoaded();
      }
    }
  }

  function formats() {
    return FORMATS;
  }

  function normalizeFormat(key) {
    return key && byKey.has(key) ? key : DEFAULT_FORMAT;
  }

  // A session id leads with two characters naming the format it is played
  // under, with nothing between them and the random half — mirrors
  // web/deck_legality.py, where the codes are arbitrary rather than
  // abbreviations so an id does not announce its format on sight. This is what
  // lets the Join screen name the format, and filter the deck list by it, from
  // the pasted id alone — before any request is made.
  const SESSION_CODE_LENGTH = 2;

  function sessionIdPrefix(key) {
    const fmt = byKey.get(normalizeFormat(key));
    return fmt ? fmt.session_code : "";
  }

  // The format a session id names, or null when it names none — an id minted
  // before this encoding existed, or a half-typed one. Null is not "casual":
  // see the docstring on the Python half for why the join screen must be able
  // to tell "played unrestricted" from "not stated".
  function formatFromSessionId(sessionId) {
    const id = String(sessionId == null ? "" : sessionId);
    if (id.length <= SESSION_CODE_LENGTH) return null;
    const fmt = byCode.get(id.slice(0, SESSION_CODE_LENGTH));
    return fmt ? fmt.key : null;
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

  // CR 407.3: the cards that carry "Remove this card from your deck before
  // playing if you're not playing for ante" may only be in a deck or sideboard
  // when the game is actually played for ante. Mirrors engine/ante.py.
  const ANTE_DECK_TEXT = "remove this card from your deck before playing if you're not playing for ante";

  function isAnteCard(card) {
    return String((card && card.oracle_text) || "")
      .toLowerCase()
      .replace(/’/g, "'")
      .includes(ANTE_DECK_TEXT);
  }

  // ---------------------------------------------------------------------
  // CR 903 — Commander / Brawl. Mirrors engine/commander.py; a format opts in
  // with a `variant` key ("commander" / "brawl") in the shipped FORMATS table.
  // ---------------------------------------------------------------------

  const COLORS = "WUBRG";
  // Basic land type -> the mana symbol it taps for (CR 305.6). A land with a
  // basic land type has that intrinsic mana ability, and its symbol counts
  // toward colour identity — which is why Badlands is black-red even though
  // CR 903.4c throws away the reminder text that says so.
  const LAND_TYPE_MANA = { plains: "W", island: "U", swamp: "B", mountain: "R", forest: "G" };
  // CR 903.3a — "This card can be your commander."
  const CAN_BE_COMMANDER_TEXT = "can be your commander";
  // CR 903.3 / 903.12c — the card types a commander may have, per variant.
  const COMMANDER_TYPES = { commander: ["creature"], brawl: ["creature", "planeswalker"] };

  // CR 903.4: mana symbols in the mana cost or rules text (reminder text
  // ignored, 903.4c), every face included (903.4d/e), plus the card's own
  // colours (a colour indicator, 204, or a characteristic-defining ability,
  // 604.3) and the intrinsic mana of any basic land type.
  function colorIdentity(card) {
    const identity = new Set();
    for (const c of (card && card.colors) || []) {
      const up = String(c).toUpperCase();
      if (COLORS.includes(up)) identity.add(up);
    }
    const typeLine = String((card && card.type_line) || "").toLowerCase();
    for (const [landType, symbol] of Object.entries(LAND_TYPE_MANA)) {
      if (typeLine.includes(landType)) identity.add(symbol);
    }
    const faces = [[(card && card.mana_cost) || "", (card && card.oracle_text) || ""]];
    for (const face of (card && card.faces) || []) {
      faces.push([(face && face.mana_cost) || "", (face && face.oracle_text) || ""]);
    }
    for (const [cost, text] of faces) {
      for (const source of [String(cost), String(text).replace(/\([^)]*\)/g, " ")]) {
        for (const match of source.matchAll(/\{([^}]*)\}/g)) {
          for (const ch of match[1].toUpperCase()) {
            if (COLORS.includes(ch)) identity.add(ch);
          }
        }
      }
    }
    return identity;
  }

  // "WUB", or "colorless" for the empty identity.
  function formatIdentity(identity) {
    const ordered = [...COLORS].filter((c) => identity.has(c)).join("");
    return ordered || "colorless";
  }

  function deckIdentity(cards) {
    const identity = new Set();
    for (const card of cards || []) for (const c of colorIdentity(card)) identity.add(c);
    return identity;
  }

  function hasBasicLandType(card) {
    const tl = String((card && card.type_line) || "").toLowerCase();
    return Object.keys(LAND_TYPE_MANA).some((t) => tl.includes(t));
  }

  // The colours of mana a land could produce (CR 903.5d).
  function producedManaColors(card) {
    const colors = new Set();
    for (const c of (card && card.produced_mana) || []) {
      const up = String(c).toUpperCase();
      if (COLORS.includes(up)) colors.add(up);
    }
    const tl = String((card && card.type_line) || "").toLowerCase();
    for (const [landType, symbol] of Object.entries(LAND_TYPE_MANA)) {
      if (tl.includes(landType)) colors.add(symbol);
    }
    return colors;
  }

  // CR 903.3 / 903.12c / 903.3a — why this card may not be a commander, or "".
  function commanderTypeProblem(card, variant) {
    const name = String((card && card.name) || "card");
    if (String((card && card.oracle_text) || "").toLowerCase().includes(CAN_BE_COMMANDER_TEXT)) return "";
    const tl = String((card && card.type_line) || "").toLowerCase();
    if (!tl.includes("legendary")) return `${name} is not legendary and cannot be a commander (CR 903.3).`;
    const allowed = COMMANDER_TYPES[variant] || COMMANDER_TYPES.commander;
    if (allowed.some((t) => tl.includes(t))) return "";
    if (tl.includes("vehicle")) return "";
    if (tl.includes("spacecraft") && card.power) return "";
    return `${name} is not a legendary ${allowed.join(" or ")} and cannot be a commander (CR 903.3).`;
  }

  // CR 903.5c/d (and 903.12e) — why this card may not be in the deck, or "".
  function deckCardProblem(card, identity, variant, brawlBasicType) {
    const name = String((card && card.name) || "card");
    const outsideOf = (set) => new Set([...set].filter((c) => !identity.has(c)));
    if (hasBasicLandType(card)) {
      const produced = producedManaColors(card);
      if (variant === "brawl" && identity.size === 0 && brawlBasicType) {
        const allowed = LAND_TYPE_MANA[String(brawlBasicType).toLowerCase()];
        if ([...produced].every((c) => c === allowed)) return "";
      }
      const outside = outsideOf(produced);
      if (outside.size) {
        return `${name} could produce ${formatIdentity(outside)} mana, which is outside the commander's colour identity (${formatIdentity(identity)}) (CR 903.5d).`;
      }
      return "";
    }
    const own = colorIdentity(card);
    const outside = outsideOf(own);
    if (outside.size) {
      return `${name}'s colour identity (${formatIdentity(own)}) is outside the commander's (${formatIdentity(identity)}) (CR 903.5c).`;
    }
    return "";
  }

  // CR 903.12e's "one basic land type of their choice", read off the deck: the
  // one basic land type its basics have, or null for none or more than one.
  function singleBasicType(counts, lookupCard) {
    const types = new Set();
    for (const name of counts.keys()) {
      const card = lookupCard(name);
      if (!card || !isBasicLand(card)) continue;
      const tl = String(card.type_line || "").toLowerCase();
      for (const t of Object.keys(LAND_TYPE_MANA)) if (tl.includes(t)) types.add(t);
    }
    return types.size === 1 ? [...types][0] : null;
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
  // {format, legal, problems:[str], illegalNames:Set, anteNames:[str]}. Cards
  // not in the catalog are skipped — they're surfaced separately as "not in
  // catalog". `playingForAnte` reflects the game the deck is headed for; when
  // false (the default) its ante cards are illegal in every format (CR 407.3).
  function validateDeck(entries, key, lookupCard, sideboard = null, commander = null, playingForAnte = false) {
    const fmt = getFormat(key);
    const result = {
      format: fmt ? fmt.key : DEFAULT_FORMAT,
      legal: true,
      problems: [],
      illegalNames: new Set(),
      anteNames: [],
    };

    const main = tally(entries);
    const side = tally(sideboard);
    const cmd = tally(commander);
    // Main-deck order first, then sideboard/commander-only cards.
    const names = [
      ...main.counts.keys(),
      ...[...side.counts.keys()].filter((n) => !main.counts.has(n)),
      ...[...cmd.counts.keys()].filter((n) => !main.counts.has(n) && !side.counts.has(n)),
    ];
    // CR 407.3 is not a format rule — it holds in Casual (which has no banlist)
    // exactly as it does in Vintage, so it is checked before the format bailout.
    for (const name of names) {
      const card = lookupCard(name);
      if (!card || !isAnteCard(card)) continue;
      if (!result.anteNames.includes(card.name)) result.anteNames.push(card.name);
      if (!playingForAnte) {
        result.problems.push(`${card.name} must be removed from the deck unless the game is played for ante.`);
        result.illegalNames.add(card.name);
      }
    }
    if (!fmt || !fmt.scryfall_key) {
      result.legal = result.problems.length === 0;
      return result;
    }
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
    // CR 903.3 / 903.12c and CR 903.5c/d, for the formats that have a command
    // zone. Mirrors the same block in web/deck_legality.py.
    if (fmt.variant) {
      const commanderCards = [...cmd.counts.keys()].map(lookupCard).filter(Boolean);
      for (const card of commanderCards) {
        const problem = commanderTypeProblem(card, fmt.variant);
        if (problem) {
          result.problems.push(problem);
          result.illegalNames.add(card.name);
        }
      }
      const identity = deckIdentity(commanderCards);
      result.commanderIdentity = [...COLORS].filter((c) => identity.has(c)).join("");
      const brawlBasicType = singleBasicType(main.counts, lookupCard);
      for (const name of names) {
        const card = lookupCard(name);
        if (!card) continue;
        const problem = deckCardProblem(card, identity, fmt.variant, brawlBasicType);
        if (problem) {
          result.problems.push(problem);
          result.illegalNames.add(card.name);
        }
      }
    }
    result.legal = result.problems.length === 0;
    return result;
  }

  window.Legality = {
    setFormats,
    formats,
    normalizeFormat,
    sessionIdPrefix,
    formatFromSessionId,
    getFormat,
    formatLabel,
    isChecked,
    cardStatus,
    cardProblem,
    copyLimit,
    isAnteCard,
    colorIdentity,
    formatIdentity,
    commanderTypeProblem,
    deckCardProblem,
    validateDeck,
    DEFAULT_FORMAT,
  };
})();
