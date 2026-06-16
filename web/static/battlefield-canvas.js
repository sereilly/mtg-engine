// battlefield-canvas.js — canvas-based battlefield renderer, projected onto a
// 3D-tilted table plane (bird's-eye Arena-style view).
//
// Layout is fully automatic: identical cards collapse into piles, piles are
// arranged into per-player bands (creatures in front near the split line,
// support permanents in the middle, lands in the back), and the camera pans
// and zooms on its own to keep every card in view. There is no manual panning
// or card dragging; the only drag interaction left is assigning blockers.

const BF_CARD_W = 80;
const BF_CARD_H = 112;

// ---- 3D table perspective ----
// The canvas is tilted away from the camera with a CSS rotateX inside a
// perspective container, so the opponent's side recedes into the distance.
// All mouse coordinates are mapped back onto the plane analytically.
const BF_TILT_DEG = 26; // tilt of the table away from the camera
const BF_PERSPECTIVE = 1500; // CSS perspective distance (px)
const BF_OVERSCAN_X = 1.22; // oversize the plane so it fills the stage when tilted
const BF_OVERSCAN_Y = 1.34;
const BF_OVERSAMPLE = 1.3; // extra backing resolution so the projection stays crisp
// World Y value of the dividing line between the two player halves
const BF_WORLD_SPLIT_Y = 310;

// ---- Automatic layout ----
// Each player's permanents are split into bands, ordered front (nearest the
// split line) to back (nearest that player's table edge):
//   band 0: creatures, planeswalkers, battles (combat-relevant, easiest to see)
//   band 1: artifacts, enchantments and other support permanents
//   band 2: lands
const BF_SLOT_PITCH_X = BF_CARD_W + 18; // horizontal distance between slots
const BF_ROW_GAP = 18; // vertical gap between rows inside a band
const BF_BAND_GAP = 26; // vertical gap between bands
const BF_SPLIT_GAP = 26; // gap between the split line and each front band
const BF_MAX_COLS = 9; // slots per row before wrapping
// Piles of identical cards fan downward; the fan compresses for tall piles.
const BF_PILE_OFFSET_Y = 20;
const BF_PILE_MAX_FAN = 60;
// Attached auras fan downward below their target.
const BF_AURA_OFFSET_Y = 22;

// ---- Automatic camera ----
const BF_MIN_ZOOM = 0.3;
const BF_MAX_ZOOM = 1.15;
const BF_FIT_PADDING = 44; // world-space padding around the fitted bounding box
const BF_CAM_EASE = 0.16; // per-frame easing toward the camera target
const BF_CARD_EASE = 0.22; // per-frame easing of cards toward their slots

// ---- Stack zone & spell animations ----
// Spells on the stack render as enlarged cards in a cascade on the right side
// of the battlefield. Casting flies the card in from the caster's hand;
// resolution either slams a permanent onto its battlefield slot or shrinks a
// non-permanent away toward the caster's graveyard.
const BF_STACK_SCALE = 1.7; // stack cards render larger than battlefield cards
const BF_STACK_HOVER_SCALE = 1.5; // extra growth of the hovered stack card
const BF_STACK_OFFSET_X = 30; // cascade offset between overlapping stack cards
const BF_STACK_OFFSET_Y = 38;
const BF_STACK_DWELL_MS = 1200; // minimum time a spell stays on the stack before resolving
const BF_STACK_GAP_X = 64; // gap between battlefield content and the stack zone
const BF_STACK_EASE = 0.18; // per-frame easing of stack cards (position + scale)
const BF_RESOLVE_FLY_MS = 340; // stack -> hover point above the battlefield slot
const BF_RESOLVE_HOVER_MS = 200; // pause hovering above the slot
const BF_RESOLVE_SLAM_MS = 110; // quick slam down into place
const BF_RESOLVE_HOVER_LIFT = 30; // world px the card hovers above its slot
const BF_FIZZLE_MS = 480; // non-permanent: stack -> graveyard shrink/fade
const BF_ABILITY_FADE_MS = 260; // resolved ability: shrink/fade in place
const BF_IMPACT_RING_MS = 240; // expanding ring when a permanent slams down

// ---- Flying creatures ----
// Creatures with Flying hover off the table and rock gently side to side, with
// a soft contact shadow left behind on the board to sell the height.
const BF_FLY_LIFT = 11; // base world px a flyer floats above its slot
const BF_FLY_BOB = 8; // extra px of vertical bob added to the lift
const BF_FLY_BOB_MS = 1200; // period of the vertical bob
const BF_FLY_TILT = 0.3; // peak swivel angle in radians (~29°) about the vertical axis
const BF_FLY_TILT_MS = 1000; // period of the left/right swivel
const BF_FLY_SKEW = 0.2; // perspective shear strength accompanying the swivel

// ---- Combat damage animations ----
// On damage resolution each attacker lunges toward its target under a glowing
// red chevron, fires a particle beam at whatever takes its damage, blockers
// recoil from the hit while their toughness visibly ticks down, and any
// creature that died stays visible as a "ghost" until its fx finish.
const BF_COMBAT_STAGGER_MS = 240; // delay between successive attackers
const BF_PUNCH_MS = 380; // attacker lunge out + settle back
const BF_PUNCH_DIST = 30; // world px the attacker lunges forward
const BF_PUNCH_IMPACT_MS = 130; // moment within the punch the hit lands
const BF_CHEVRON_MS = 1100; // glowing chevron above the attacker
const BF_BEAM_MS = 340; // particle beam head travel time
const BF_BEAM_LINGER_MS = 180; // beam tail fade after the head arrives
const BF_RECOIL_MS = 320; // knock-back on a card taking damage
const BF_RECOIL_DIST = 16;
const BF_TOUGHNESS_MS = 800; // blocker toughness count-down ticker
const BF_HIT_RING_MS = 280; // red impact flash on the target
const BF_GHOST_FADE_MS = 240; // dead participants fade out at the end

class BattlefieldCanvas {
  constructor(canvasEl, callbacks = {}) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d");
    this.dpr = window.devicePixelRatio || 1;
    this.tiltRad = (BF_TILT_DEG * Math.PI) / 180;

    // Tilt the canvas plane in 3D. The wrapper provides the perspective camera.
    const wrap = canvasEl.parentElement;
    if (wrap) {
      wrap.style.perspective = `${BF_PERSPECTIVE}px`;
      wrap.style.perspectiveOrigin = "50% 50%";
    }
    canvasEl.style.position = "absolute";
    canvasEl.style.transformOrigin = "50% 50%";
    canvasEl.style.transform = `rotateX(${BF_TILT_DEG}deg)`;

    // Camera state (in CSS-pixel space). The camera is fully automatic: it
    // eases toward camTarget, which is recomputed to frame all cards in play.
    this.camX = 0;
    this.camY = 0;
    this.zoom = 1.0;
    this.camTarget = null;
    this._cameraInit = false;

    // cardItems: [{key, seat, idx, card, x, y, tx, ty}]
    // x/y are the current (animated) world-space anchor coordinates;
    // tx/ty are the layout targets the card eases toward.
    // For stacked items, only the bottom card's position is used as the stack
    // anchor; other members' positions are computed by _renderPos().
    this.cardItems = [];

    // stacks: [{id, keys[], offsetY, kind: "pile"|"aura"}]
    // keys is ordered bottom-to-top; the bottom key renders first (behind).
    this.stacks = [];

    // Visuals for the engine's spell stack, drawn in the stack zone to the
    // right of the battlefield. Center-based coordinates so scaling is easy:
    // [{sig, item, cx, cy, scale, tcx, tcy, tScale}]
    this.stackVisuals = [];
    this._stackSynced = false;
    this._stackBaseX = 6 * BF_SLOT_PITCH_X + BF_STACK_GAP_X;

    // Time-based resolve animations (card flights + impact rings) and the
    // battlefield keys hidden while their entrance animation plays.
    this.fxAnims = [];
    this.suppressedKeys = new Set();

    // Combat damage fx timeline (punches, chevrons, beams, recoils, tickers)
    // and the per-key world-space render offsets the punches/recoils produce.
    this.combatFx = [];
    this.combatOffsets = new Map();

    // Per seat+band ordered list of layout group ids, persisted across updates
    // so existing cards keep their slots when new ones arrive.
    this.bandOrder = new Map();

    // Image cache: url -> HTMLImageElement | null
    this.imageCache = new Map();
    this.imageLoading = new Set();

    // Callbacks
    this.onCardClick = callbacks.onCardClick || null;
    this.onCardContextMenu = callbacks.onCardContextMenu || null;
    this.onCardHover = callbacks.onCardHover || null;
    this.onHandCardDrop = callbacks.onHandCardDrop || null;
    this.onBlockerAssign = callbacks.onBlockerAssign || null;
    this.onStackCardHover = callbacks.onStackCardHover || null;
    this.onStackCardClick = callbacks.onStackCardClick || null;

    // Runtime state
    this.viewerSeat = 0;
    this.selectedKeys = new Set();
    this.attackingKeys = new Set();
    this.targetingKeys = new Set();
    this.combatArrows = [];
    this.hoveredKey = null;
    // Floating stack-card interaction: index into stackVisuals (= serialized
    // stack index) currently hovered, and the index click-locked for priority
    // (set externally by app.js so the DOM stack list stays in sync).
    this.hoveredStackIndex = null;
    this.stackHeldIndex = null;

    // Mouse-press state (left mouse): click detection + blocker-assignment drag.
    this.pressState = null;

    // Last known mouse position (client coords). Stack cards animate into
    // place, so hover is re-evaluated every tick against this — a card
    // sliding under a stationary cursor still registers as hovered.
    this._lastMouseClient = null;

    // External context passed on updates (current game state for callback decisions)
    this.currentState = null;

    // RAF loop
    this.rafId = null;
    this.needsRedraw = true;

    this._resize();
    this._updateCameraTarget();
    if (this.camTarget) {
      this.camX = this.camTarget.x;
      this.camY = this.camTarget.y;
      this.zoom = this.camTarget.zoom;
    }
    this._bindEvents();
    this._startLoop();
  }

  destroy() {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this._unbindEvents();
  }

  // ---------------------------------------------------------------------------
  // Coordinate transforms
  // ---------------------------------------------------------------------------

  canvasToWorld(cx, cy) {
    return { x: (cx - this.camX) / this.zoom, y: (cy - this.camY) / this.zoom };
  }

  worldToCanvas(wx, wy) {
    return { x: wx * this.zoom + this.camX, y: wy * this.zoom + this.camY };
  }

  // Center of the (untransformed) stage wrapper in client coordinates.
  // The canvas is centered on it, and both the transform-origin and the
  // perspective-origin coincide with it, which keeps the math closed-form.
  _stageCenter() {
    const el = this.canvas.parentElement || this.canvas;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  // Inverse perspective projection: client (page) coords -> flat canvas-local coords.
  // Derivation: a plane point (x, y) under rotateX(t) + perspective P projects to
  //   X = x * s,  Y = y * cos(t) * s,  with s = P / (P - y * sin(t))
  // which solves to y = Y*P / (P*cos(t) + Y*sin(t)).
  _pageToCanvas(pageX, pageY) {
    const c = this._stageCenter();
    const X = pageX - c.x;
    const Y = pageY - c.y;
    const sin = Math.sin(this.tiltRad);
    const cos = Math.cos(this.tiltRad);
    const y = (Y * BF_PERSPECTIVE) / (BF_PERSPECTIVE * cos + Y * sin);
    const s = BF_PERSPECTIVE / (BF_PERSPECTIVE - y * sin);
    const x = X / s;
    return { x: x + (this.cssW || 0) / 2, y: y + (this.cssH || 0) / 2 };
  }

  // Forward perspective projection: flat canvas-local coords -> client (page) coords.
  _canvasToPage(u, v) {
    const c = this._stageCenter();
    const x = u - (this.cssW || 0) / 2;
    const y = v - (this.cssH || 0) / 2;
    const sin = Math.sin(this.tiltRad);
    const cos = Math.cos(this.tiltRad);
    const s = BF_PERSPECTIVE / (BF_PERSPECTIVE - y * sin);
    return { x: c.x + x * s, y: c.y + y * cos * s };
  }

  // ---------------------------------------------------------------------------
  // Stack helpers
  // ---------------------------------------------------------------------------

  // Return the world-space render position of a card, accounting for stack offset.
  _renderPos(key) {
    const item = this.cardItems.find((c) => c.key === key);
    if (!item) return null;
    const stack = this.stacks.find((s) => s.keys.includes(key));
    if (!stack) return { x: item.x, y: item.y };
    const stackPos = stack.keys.indexOf(key);
    const baseItem = this.cardItems.find((c) => c.key === stack.keys[0]);
    if (!baseItem) return { x: item.x, y: item.y };
    return { x: baseItem.x, y: baseItem.y + stackPos * (stack.offsetY ?? BF_AURA_OFFSET_Y) };
  }

  // Same as _renderPos but using layout targets instead of animated positions.
  _targetRenderPos(key) {
    const item = this.cardItems.find((c) => c.key === key);
    if (!item) return null;
    const stack = this.stacks.find((s) => s.keys.includes(key));
    if (!stack) return { x: item.tx, y: item.ty };
    const stackPos = stack.keys.indexOf(key);
    const baseItem = this.cardItems.find((c) => c.key === stack.keys[0]);
    if (!baseItem) return { x: item.tx, y: item.ty };
    return { x: baseItem.tx, y: baseItem.ty + stackPos * (stack.offsetY ?? BF_AURA_OFFSET_Y) };
  }

  // Get the world-space bounding box of a card for hit testing.
  _cardBounds(key) {
    const pos = this._renderPos(key);
    if (!pos) return null;
    return this._boundsAt(key, pos);
  }

  // Bounding box of a card at its layout target (for camera fitting).
  _targetBounds(key) {
    const pos = this._targetRenderPos(key);
    if (!pos) return null;
    return this._boundsAt(key, pos);
  }

  _boundsAt(key, pos) {
    const item = this.cardItems.find((c) => c.key === key);
    const tapped = item?.card?.tapped;
    if (tapped) {
      const cx = pos.x + BF_CARD_W / 2;
      const cy = pos.y + BF_CARD_H / 2;
      return { x: cx - BF_CARD_H / 2, y: cy - BF_CARD_W / 2, w: BF_CARD_H, h: BF_CARD_W };
    }
    return { x: pos.x, y: pos.y, w: BF_CARD_W, h: BF_CARD_H };
  }

  _hitTest(wx, wy) {
    // Test from top of render order (last item = topmost visually).
    for (let i = this.cardItems.length - 1; i >= 0; i--) {
      const item = this.cardItems[i];
      const b = this._cardBounds(item.key);
      if (!b) continue;
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) {
        return item;
      }
    }
    return null;
  }

  // Hit-test the floating stack cascade. Index 0 (top of the engine stack)
  // draws last and therefore sits on top, so test in ascending order — but
  // test the currently hovered card first: it's enlarged and drawn above
  // everything, and giving it precedence keeps hover stable in overlaps.
  _hitTestStack(wx, wy) {
    const hitAt = (i) => {
      const v = this.stackVisuals[i];
      const w = BF_CARD_W * v.scale;
      const h = BF_CARD_H * v.scale;
      return wx >= v.cx - w / 2 && wx <= v.cx + w / 2 && wy >= v.cy - h / 2 && wy <= v.cy + h / 2
        ? { index: i, item: v.item }
        : null;
    };
    const hovered = this.hoveredStackIndex;
    if (hovered != null && hovered < this.stackVisuals.length) {
      const hit = hitAt(hovered);
      if (hit) return hit;
    }
    for (let i = 0; i < this.stackVisuals.length; i++) {
      if (i === hovered) continue;
      const hit = hitAt(i);
      if (hit) return hit;
    }
    return null;
  }

  // Recompute which stack card (if any) is under the given world point and
  // fire the hover callback on changes. Returns the hit, or null.
  _updateStackHover(wx, wy) {
    const stackHit = this._hitTestStack(wx, wy);
    const newStackIndex = stackHit ? stackHit.index : null;
    if (newStackIndex !== this.hoveredStackIndex) {
      this.hoveredStackIndex = newStackIndex;
      this.needsRedraw = true;
      if (this.onStackCardHover) {
        this.onStackCardHover(stackHit ? { index: stackHit.index, item: stackHit.item } : null);
      }
    }
    return stackHit;
  }

  // Stack cards ease into their cascade slots, so a card can arrive under a
  // cursor that isn't moving. Re-evaluate hover from the last known mouse
  // position each tick; without this, hover only updates on mousemove and
  // the auto-pass fires even though the player is pointing at the card.
  _updateStackHoverFromLastMouse() {
    if (!this._lastMouseClient || this.pressState) return;
    if (!this.stackVisuals.length && this.hoveredStackIndex === null) return;
    const { x: cx, y: cy } = this._pageToCanvas(this._lastMouseClient.x, this._lastMouseClient.y);
    const world = this.canvasToWorld(cx, cy);
    this._updateStackHover(world.x, world.y);
  }

  _sortRenderOrder() {
    const stackedKeys = new Set(this.stacks.flatMap((s) => s.keys));
    const free = this.cardItems.filter((c) => !stackedKeys.has(c.key));
    const stacked = [];
    for (const stack of this.stacks) {
      // Aura stacks keep the enchanted permanent at keys[0]; draw its auras
      // first so they sit BEHIND the creature and never occlude it. Regular
      // piles keep their natural bottom-to-top order.
      const drawKeys =
        stack.kind === "aura" && stack.keys.length > 1
          ? [...stack.keys.slice(1), stack.keys[0]]
          : stack.keys;
      for (const k of drawKeys) {
        const item = this.cardItems.find((c) => c.key === k);
        if (item) stacked.push(item);
      }
    }
    this.cardItems = [...free, ...stacked];
  }

  // ---------------------------------------------------------------------------
  // State update from renderBoard
  // ---------------------------------------------------------------------------

  updateState(state, viewerSeat) {
    this.viewerSeat = viewerSeat ?? 0;
    this.currentState = state;

    const newKeys = new Set();
    const incoming = new Map(); // key -> {seat, idx, card}

    const players = Array.isArray(state.players) ? state.players : [];
    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const bf = Array.isArray(players[seatIdx]?.battlefield) ? players[seatIdx].battlefield : [];
      for (let idx = 0; idx < bf.length; idx++) {
        const key = `${seatIdx}-${idx}`;
        newKeys.add(key);
        incoming.set(key, { seat: seatIdx, idx, card: bf[idx] });
      }
    }

    // Prune cards that left the battlefield
    this.cardItems = this.cardItems.filter((c) => newKeys.has(c.key));

    // Drop stale entrance suppressions when the board changed under them
    // (index shifted or the permanent is already gone).
    for (const fx of this.fxAnims) {
      if (!fx.suppressKey) continue;
      const data = incoming.get(fx.suppressKey);
      if (!data || data.card?.name !== fx.card?.name) {
        this.suppressedKeys.delete(fx.suppressKey);
        fx.suppressKey = null;
      }
    }

    // Update existing cards / add new ones
    const brandNew = [];
    for (const [key, data] of incoming) {
      const existing = this.cardItems.find((c) => c.key === key);
      if (existing) {
        existing.card = data.card;
      } else {
        const item = { key, seat: data.seat, idx: data.idx, card: data.card, x: 0, y: 0, tx: 0, ty: 0 };
        this.cardItems.push(item);
        brandNew.push(item);
      }
    }

    this._layoutBoard(state);
    this._syncAuraStacks(state, newKeys);

    // New arrivals appear directly at their assigned slot; existing cards
    // animate toward theirs only when the layout had to move them.
    for (const item of brandNew) {
      item.x = item.tx;
      item.y = item.ty;
    }

    const firstSync = !this._stackSynced;
    this._syncStackZone(state, brandNew);
    if (!firstSync) this._spawnLandEntranceFx(brandNew);

    this._sortRenderOrder();
    this._updateCameraTarget();
    if (!this._cameraInit) {
      this._cameraInit = true;
      if (this.camTarget) {
        this.camX = this.camTarget.x;
        this.camY = this.camTarget.y;
        this.zoom = this.camTarget.zoom;
      }
    }
    this.needsRedraw = true;
  }

  // Which band a permanent belongs to (0 front, 1 middle, 2 back).
  _bandFor(card) {
    const t = String(card?.type || "").toLowerCase();
    // Creature check first so animated lands fight from the front line.
    if (t.includes("creature") || t.includes("planeswalker") || t.includes("battle")) return 0;
    if (t.includes("land")) return 2;
    return 1;
  }

  // Cards involved in combat (or carrying damage) are pulled out of piles so
  // they stay individually visible until combat wraps up.
  _isCombatActive(card) {
    if (!card) return false;
    return Boolean(card.attacking) || Number(card.damage_marked) > 0 || card.blocking_attacker_index != null;
  }

  // Recompute every card's layout target and rebuild identity piles.
  _layoutBoard(state) {
    const players = Array.isArray(state.players) ? state.players : [];
    const itemByKey = new Map(this.cardItems.map((c) => [c.key, c]));

    // Attached auras ride their target; their targets keep a dedicated slot.
    const attachedKeys = new Set();
    const auraCounts = new Map(); // targetKey -> number of attachments
    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const bf = Array.isArray(players[seatIdx]?.battlefield) ? players[seatIdx].battlefield : [];
      for (let idx = 0; idx < bf.length; idx++) {
        const card = bf[idx];
        if (!card || card.attached_to_index == null) continue;
        const targetKey = `${card.attached_to_seat ?? seatIdx}-${card.attached_to_index}`;
        attachedKeys.add(`${seatIdx}-${idx}`);
        auraCounts.set(targetKey, (auraCounts.get(targetKey) || 0) + 1);
      }
    }

    const piles = [];

    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const bf = Array.isArray(players[seatIdx]?.battlefield) ? players[seatIdx].battlefield : [];

      // ---- Group cards into layout groups (identity piles / solo slots) ----
      const groups = new Map(); // id -> {id, band, keys[]}
      const occ = new Map(); // occurrence counters for unique-slot ids
      const order = []; // encounter order of group ids
      for (let idx = 0; idx < bf.length; idx++) {
        const card = bf[idx];
        const key = `${seatIdx}-${idx}`;
        if (!card || attachedKeys.has(key)) continue;
        const band = this._bandFor(card);
        let id;
        if (auraCounts.has(key)) {
          // Cards with attachments get their own slot for the aura fan.
          const n = (occ.get(`base:${card.name}`) || 0) + 1;
          occ.set(`base:${card.name}`, n);
          id = `base:${card.name}#${n}`;
        } else {
          id = `pile:${card.name}${card.is_token ? "|token" : ""}`;
        }
        let g = groups.get(id);
        if (!g) {
          g = { id, band, keys: [] };
          groups.set(id, g);
          order.push(id);
        }
        g.keys.push(key);
      }

      // ---- Pull combat-active cards out of piles, next to their pile ----
      const finalGroups = [];
      for (const id of order) {
        const g = groups.get(id);
        const active = g.keys.filter((k) => this._isCombatActive(itemByKey.get(k)?.card));
        if (g.keys.length >= 2 && active.length > 0 && active.length < g.keys.length) {
          finalGroups.push({ ...g, keys: g.keys.filter((k) => !active.includes(k)) });
          active.forEach((k, j) => {
            finalGroups.push({ id: `combat:${id}#${j + 1}`, band: g.band, keys: [k], parentId: id });
          });
        } else {
          finalGroups.push(g);
        }
      }

      // ---- Stable slot order per band: keep prior slots, add new groups ----
      const bandGroups = [[], [], []];
      for (const g of finalGroups) bandGroups[g.band].push(g);
      for (let band = 0; band < 3; band++) {
        const byId = new Map(bandGroups[band].map((g) => [g.id, g]));
        const orderKey = `${seatIdx}|${band}`;
        const ordered = (this.bandOrder.get(orderKey) || []).filter((id) => byId.has(id));
        for (const g of bandGroups[band]) {
          if (ordered.includes(g.id)) continue;
          let at = g.parentId ? ordered.indexOf(g.parentId) : -1;
          if (at >= 0) {
            at++;
            while (at < ordered.length && ordered[at].startsWith(`combat:${g.parentId}#`)) at++;
            ordered.splice(at, 0, g.id);
          } else {
            ordered.push(g.id);
          }
        }
        this.bandOrder.set(orderKey, ordered);
        bandGroups[band] = ordered.map((id) => byId.get(id));
      }

      // ---- Band geometry: wrap into rows, size rows by their tallest fan ----
      const fanExtra = (g) => {
        const auraFan = (g.keys.length === 1 ? auraCounts.get(g.keys[0]) || 0 : 0) * BF_AURA_OFFSET_Y;
        const pileFan = g.keys.length >= 2 ? Math.min(BF_PILE_MAX_FAN, (g.keys.length - 1) * BF_PILE_OFFSET_Y) : 0;
        return Math.max(auraFan, pileFan);
      };
      const bands = bandGroups.map((groupsHere) => {
        const rows = [];
        for (let i = 0; i < groupsHere.length; i += BF_MAX_COLS) {
          const row = groupsHere.slice(i, i + BF_MAX_COLS);
          const h = BF_CARD_H + Math.max(0, ...row.map(fanExtra));
          rows.push({ row, h });
        }
        const height = rows.reduce((sum, r) => sum + r.h, 0) + Math.max(0, rows.length - 1) * BF_ROW_GAP;
        return { rows, height };
      });

      // ---- Place groups. Viewer bands grow downward from the split line,
      //      opponent bands grow upward, front band nearest the split. ----
      const isViewer = seatIdx === this.viewerSeat;
      let cursor = isViewer ? BF_WORLD_SPLIT_Y + BF_SPLIT_GAP : BF_WORLD_SPLIT_Y - BF_SPLIT_GAP;
      for (const band of bands) {
        if (!band.rows.length) continue;
        let rowTop = isViewer ? cursor : cursor - band.height;
        for (const { row, h } of band.rows) {
          row.forEach((g, col) => {
            const gx = col * BF_SLOT_PITCH_X;
            for (const k of g.keys) {
              const item = itemByKey.get(k);
              if (item) {
                item.tx = gx;
                item.ty = rowTop;
              }
            }
            if (g.keys.length >= 2) {
              piles.push({
                id: `pile-${seatIdx}-${g.id}`,
                keys: [...g.keys],
                offsetY: Math.min(BF_PILE_OFFSET_Y, BF_PILE_MAX_FAN / (g.keys.length - 1)),
                kind: "pile",
              });
            }
          });
          rowTop += h + BF_ROW_GAP;
        }
        cursor = isViewer ? cursor + band.height + BF_BAND_GAP : cursor - band.height - BF_BAND_GAP;
      }
    }

    this.stacks = piles;
  }

  _syncAuraStacks(state, newKeys) {
    const players = Array.isArray(state.players) ? state.players : [];
    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const bf = Array.isArray(players[seatIdx]?.battlefield) ? players[seatIdx].battlefield : [];
      for (let idx = 0; idx < bf.length; idx++) {
        const card = bf[idx];
        if (!card || card.attached_to_index === null || card.attached_to_index === undefined) continue;

        const targetSeat = card.attached_to_seat ?? seatIdx;
        const targetKey = `${targetSeat}-${card.attached_to_index}`;
        const auraKey = `${seatIdx}-${idx}`;

        if (!newKeys.has(targetKey) || !newKeys.has(auraKey)) continue;

        let stack = this.stacks.find((s) => s.kind === "aura" && s.keys[0] === targetKey);
        if (!stack) {
          // Negative offset: auras fan UPWARD so they stick out the top of the
          // enchanted permanent rather than below it.
          stack = { id: `aura-${targetKey}`, keys: [targetKey], offsetY: -BF_AURA_OFFSET_Y, kind: "aura" };
          this.stacks.push(stack);
        }
        if (!stack.keys.includes(auraKey)) stack.keys.push(auraKey);

        // Auras share their target's slot.
        const targetItem = this.cardItems.find((c) => c.key === targetKey);
        const auraItem = this.cardItems.find((c) => c.key === auraKey);
        if (targetItem && auraItem) {
          auraItem.tx = targetItem.tx;
          auraItem.ty = targetItem.ty;
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Spell stack zone & cast/resolve animations
  // ---------------------------------------------------------------------------

  // Diff the engine's spell stack against our visuals. New items fly in from
  // the caster's hand (spells) or source permanent (abilities) and grow into
  // the stack zone; removed items play a resolve animation.
  _syncStackZone(state, brandNew) {
    const stackData = Array.isArray(state.stack) ? state.stack : [];

    // Rightmost battlefield content; only used as a directional fallback for
    // the hand/graveyard anchors (the cascade itself is pinned to the view).
    let maxX = 6 * BF_SLOT_PITCH_X;
    for (const item of this.cardItems) maxX = Math.max(maxX, item.tx + BF_CARD_W);
    this._stackBaseX = maxX + BF_STACK_GAP_X;

    // In-order signature matching keeps visuals stable across pushes/pops and
    // tolerates a counterspell plucking an item out of the middle. The
    // serialized stack is top-first and only the top changes, so match from
    // the BOTTOM (the stable end): with identical names on the stack, the
    // existing visuals keep their slots and the unmatched newcomer lands on
    // top, and on resolution it is the top visual that animates away.
    const sigs = stackData.map((it) => `${it.type}|${it.card?.name || it.label || "?"}|${it.caster_index}`);
    const old = this.stackVisuals;
    const matched = new Array(old.length).fill(false);
    const next = new Array(stackData.length);
    let scanFrom = old.length - 1;
    for (let i = stackData.length - 1; i >= 0; i--) {
      let found = -1;
      for (let j = scanFrom; j >= 0; j--) {
        if (!matched[j] && old[j].sig === sigs[i]) { found = j; break; }
      }
      if (found >= 0) {
        matched[found] = true;
        scanFrom = found - 1;
        old[found].item = stackData[i];
        next[i] = old[found];
      } else {
        const from = this._castOrigin(stackData[i]);
        next[i] = { sig: sigs[i], item: stackData[i], cx: from.x, cy: from.y, scale: from.scale, tcx: from.x, tcy: from.y, tScale: BF_STACK_SCALE };
      }
    }
    const removed = old.filter((v, j) => !matched[j]);
    this.stackVisuals = next;
    if (this.hoveredStackIndex != null && this.hoveredStackIndex >= next.length) {
      this.hoveredStackIndex = null;
      if (this.onStackCardHover) this.onStackCardHover(null);
    }
    if (this.stackHeldIndex != null && this.stackHeldIndex >= next.length) {
      this.stackHeldIndex = null;
    }
    this._retargetStackVisuals();

    if (!this._stackSynced) {
      // First sync after (re)joining: place without animating.
      this._stackSynced = true;
      for (const v of next) {
        v.cx = v.tcx;
        v.cy = v.tcy;
        v.scale = v.tScale;
      }
      return;
    }
    for (const v of removed) this._spawnResolveFx(v, brandNew);
  }

  // Pin the stack cascade to the right side of the currently visible
  // battlefield. The camera never moves to accommodate the stack, so this is
  // re-run every frame instead — camera motion can't strand the stack off
  // screen. Sizes divide by zoom so stack cards keep a constant on-screen
  // size however far the camera is zoomed out. The serialized stack is
  // top-first: index 0 (next to resolve) takes the deepest down-right offset
  // and is drawn on top.
  _retargetStackVisuals() {
    const n = this.stackVisuals.length;
    if (!n) return;
    const rect = this._visibleWorldRect();
    const sc = BF_STACK_SCALE / this.zoom;
    const w = BF_CARD_W * sc;
    const offX = BF_STACK_OFFSET_X / this.zoom;
    const offY = BF_STACK_OFFSET_Y / this.zoom;
    const margin = 30 / this.zoom;
    const baseX = rect.maxX - margin - w / 2 - (n - 1) * offX;
    const centerY = (rect.minY + rect.maxY) / 2;
    this.stackVisuals.forEach((v, i) => {
      const pos = n - 1 - i;
      // The hovered card grows; shifting it left by the extra half-width
      // keeps its right edge anchored (and on screen), and the enlarged
      // bounds still fully contain the resting bounds so hover stays stable.
      const hovered = i === this.hoveredStackIndex;
      v.tcx = baseX + pos * offX - (hovered ? ((BF_STACK_HOVER_SCALE - 1) * w) / 2 : 0);
      v.tcy = centerY + (pos - (n - 1) / 2) * offY;
      v.tScale = hovered ? sc * BF_STACK_HOVER_SCALE : sc;
    });
  }

  // World-space rectangle currently visible on the battlefield stage (the
  // non-overscan part of the canvas, mapped through the camera).
  _visibleWorldRect() {
    const vx = ((this.cssW || 0) * (1 - 1 / BF_OVERSCAN_X)) / 2;
    const vy = ((this.cssH || 0) * (1 - 1 / BF_OVERSCAN_Y)) / 2;
    const vw = (this.cssW || 0) / BF_OVERSCAN_X;
    const vh = (this.cssH || 0) / BF_OVERSCAN_Y;
    const tl = this.canvasToWorld(vx, vy);
    const br = this.canvasToWorld(vx + vw, vy + vh);
    return { minX: tl.x, minY: tl.y, maxX: br.x, maxY: br.y };
  }

  // Clamp a world point so a card anchored there stays on the battlefield.
  _clampToBattlefield(x, y) {
    const rect = this._visibleWorldRect();
    const pad = BF_CARD_W * 0.75;
    return {
      x: Math.min(rect.maxX - pad, Math.max(rect.minX + pad, x)),
      y: Math.min(rect.maxY - pad, Math.max(rect.minY + pad, y)),
    };
  }

  // World-space point a newly cast stack item flies in from. Hand/graveyard
  // anchors live outside the canvas, so the projected point is clamped to the
  // visible battlefield — the card enters from the matching table edge
  // instead of teleporting in from off screen.
  _castOrigin(item) {
    if (item?.type === "ability" && item.source_permanent_seat != null && item.source_permanent_index != null) {
      const pos = this._renderPos(`${item.source_permanent_seat}-${item.source_permanent_index}`);
      if (pos) return { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2, scale: 1.0 };
    }
    const fromViewer = item?.caster_index === this.viewerSeat;
    const el = document.getElementById(fromViewer ? "selfHand" : "oppHand");
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 || r.height > 0) {
        const c = this._pageToCanvas(r.left + r.width / 2, r.top + r.height / 2);
        const w = this.canvasToWorld(c.x, c.y);
        const p = this._clampToBattlefield(w.x, w.y);
        return { x: p.x, y: p.y, scale: 0.55 / this.zoom };
      }
    }
    const fallback = this._clampToBattlefield(this._stackBaseX, BF_WORLD_SPLIT_Y + (fromViewer ? 520 : -520));
    return { x: fallback.x, y: fallback.y, scale: 0.55 / this.zoom };
  }

  // World-space point a resolved non-permanent shrinks away toward, clamped
  // so the fizzle heads in the graveyard's direction without leaving the
  // battlefield.
  _graveAnchor(casterSeat) {
    const isViewer = casterSeat === this.viewerSeat;
    const el = document.getElementById(isViewer ? "selfGraveCount" : "oppGraveCount");
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 || r.height > 0) {
        const c = this._pageToCanvas(r.left + r.width / 2, r.top + r.height / 2);
        const w = this.canvasToWorld(c.x, c.y);
        return this._clampToBattlefield(w.x, w.y);
      }
    }
    return this._clampToBattlefield(this._stackBaseX + 260, BF_WORLD_SPLIT_Y + (isViewer ? 420 : -420));
  }

  // A stack item disappeared: animate its resolution. Permanents fly to their
  // new battlefield slot, hover briefly, then slam down; other spells shrink
  // toward the caster's graveyard; abilities just fade out.
  _spawnResolveFx(v, brandNew) {
    const item = v.item || {};
    const card = item.card || null;
    const typeStr = String(card?.type || "").toLowerCase();
    const isSpell = item.type !== "ability";
    const isPermanentSpell = isSpell && !/instant|sorcery/.test(typeStr) &&
      /creature|artifact|enchantment|planeswalker|battle|land/.test(typeStr);

    // Spells stay on the stack for a minimum dwell even when priority passes
    // immediately, measured from when the card visually arrived there (or
    // from now if it is still mid-flight). The dwell stage also finishes the
    // cast flight, so the resolve movement always departs from the stack slot.
    const now = performance.now();
    const dwell = Math.max(0, BF_STACK_DWELL_MS - (now - (v.settledAt ?? now)));
    const hold = dwell > 16
      ? [{ x0: v.cx, y0: v.cy, s0: v.scale, a0: 1, x1: v.tcx, y1: v.tcy, s1: v.tScale, a1: 1, dur: dwell, ease: _easeOutCubic }]
      : [];
    const sx = hold.length ? v.tcx : v.cx;
    const sy = hold.length ? v.tcy : v.cy;
    const ss = hold.length ? v.tScale : v.scale;

    if (isPermanentSpell) {
      const landed = (brandNew || []).find(
        (bi) => !bi._fxClaimed && bi.seat === item.caster_index && bi.card?.name === card?.name
      );
      if (landed) {
        landed._fxClaimed = true;
        const pos = this._targetRenderPos(landed.key) || { x: landed.tx, y: landed.ty };
        const slot = { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2 };
        const hover = { x: slot.x, y: slot.y - BF_RESOLVE_HOVER_LIFT };
        this.suppressedKeys.add(landed.key);
        this.fxAnims.push({
          type: "card", card, suppressKey: landed.key, impactAt: slot,
          stageIdx: 0, stageStart: null, x: v.cx, y: v.cy, scale: v.scale, alpha: 1,
          stages: [
            ...hold,
            { x0: sx, y0: sy, s0: ss, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_FLY_MS, ease: _easeOutCubic, lifted: true },
            { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_HOVER_MS, ease: null, lifted: true },
            { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: slot.x, y1: slot.y, s1: 1, a1: 1, dur: BF_RESOLVE_SLAM_MS, ease: _easeInQuad },
          ],
        });
        return;
      }
    }

    if (isSpell) {
      const g = this._graveAnchor(item.caster_index ?? 0);
      this.fxAnims.push({
        type: "card", card, stageIdx: 0, stageStart: null, x: v.cx, y: v.cy, scale: v.scale, alpha: 1,
        stages: [
          ...hold,
          { x0: sx, y0: sy, s0: ss, a0: 1, x1: g.x, y1: g.y, s1: 0.2, a1: 0, dur: BF_FIZZLE_MS, ease: _easeInCubic },
        ],
      });
      return;
    }

    this.fxAnims.push({
      type: "card", card, stageIdx: 0, stageStart: null, x: v.cx, y: v.cy, scale: v.scale, alpha: 1,
      stages: [
        ...hold,
        { x0: sx, y0: sy, s0: ss, a0: 1, x1: sx, y1: sy, s1: ss * 0.6, a1: 0, dur: BF_ABILITY_FADE_MS, ease: null },
      ],
    });
  }

  // Lands never go on the stack: new land permanents play the same
  // hover-and-slam entrance as resolved permanents, flying straight in from
  // the controller's hand. Cards already claimed by a stack-resolve
  // animation are skipped.
  _spawnLandEntranceFx(brandNew) {
    for (const item of brandNew) {
      if (item._fxClaimed) continue;
      const typeStr = String(item.card?.type || "").toLowerCase();
      if (!typeStr.includes("land")) continue;
      const pos = this._targetRenderPos(item.key) || { x: item.tx, y: item.ty };
      const slot = { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2 };
      const hover = { x: slot.x, y: slot.y - BF_RESOLVE_HOVER_LIFT };
      const from = this._castOrigin({ caster_index: item.seat });
      this.suppressedKeys.add(item.key);
      this.fxAnims.push({
        type: "card", card: item.card, suppressKey: item.key, impactAt: slot,
        stageIdx: 0, stageStart: null, x: from.x, y: from.y, scale: from.scale, alpha: 1,
        stages: [
          { x0: from.x, y0: from.y, s0: from.scale, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_FLY_MS, ease: _easeOutCubic, lifted: true },
          { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_HOVER_MS, ease: null, lifted: true },
          { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: slot.x, y1: slot.y, s1: 1, a1: 1, dur: BF_RESOLVE_SLAM_MS, ease: _easeInQuad },
        ],
      });
    }
  }

  // Advance time-based resolve animations. Returns true while any are active.
  _tickFx(now) {
    if (!this.fxAnims.length) return false;
    const done = [];
    for (const fx of this.fxAnims) {
      if (fx.type === "ring") {
        if (fx.start == null) fx.start = now;
        fx.t = (now - fx.start) / fx.dur;
        if (fx.t >= 1) done.push(fx);
        continue;
      }
      if (fx.stageStart == null) fx.stageStart = now;
      let stage = fx.stages[fx.stageIdx];
      let t = stage.dur > 0 ? (now - fx.stageStart) / stage.dur : 1;
      while (t >= 1 && fx.stageIdx < fx.stages.length - 1) {
        fx.stageStart += stage.dur;
        fx.stageIdx++;
        stage = fx.stages[fx.stageIdx];
        t = stage.dur > 0 ? (now - fx.stageStart) / stage.dur : 1;
      }
      const k = Math.min(1, Math.max(0, t));
      const e = stage.ease ? stage.ease(k) : k;
      // Re-clamp against the live view every tick: the camera may pan/zoom
      // for battlefield changes mid-animation, and the card must ride the
      // view edge rather than be left out of frame.
      const p = this._clampToBattlefield(_lerp(stage.x0, stage.x1, e), _lerp(stage.y0, stage.y1, e));
      fx.x = p.x;
      fx.y = p.y;
      fx.scale = _lerp(stage.s0, stage.s1, e);
      fx.alpha = _lerp(stage.a0, stage.a1, e);
      fx.lifted = !!stage.lifted;
      if (t >= 1 && fx.stageIdx === fx.stages.length - 1) done.push(fx);
    }
    for (const fx of done) {
      this.fxAnims.splice(this.fxAnims.indexOf(fx), 1);
      if (fx.suppressKey) this.suppressedKeys.delete(fx.suppressKey);
      if (fx.impactAt) {
        this.fxAnims.push({ type: "ring", x: fx.impactAt.x, y: fx.impactAt.y, dur: BF_IMPACT_RING_MS, start: null, t: 0 });
      }
    }
    return true;
  }

  // True while a cast/resolve animation is visually in progress: a stack card
  // still flying in or sitting out its minimum dwell, or any time-based fx
  // (resolve flights, fizzles, land entrances, impact rings). Lets the app
  // pace automatic actions to what the player has actually seen.
  hasPendingAnimations() {
    if (this.fxAnims.length > 0 || this.combatFx.length > 0) return true;
    const now = performance.now();
    for (const v of this.stackVisuals) {
      if (!v.settledAt || now - v.settledAt < BF_STACK_DWELL_MS) return true;
    }
    return false;
  }

  // ---------------------------------------------------------------------------
  // Combat damage fx
  // ---------------------------------------------------------------------------

  // Play the combat damage step animation. Must be called BEFORE the state
  // update that applies the damage, while the canvas still holds every
  // participant (positions and card data are snapshotted here so creatures
  // that die can keep animating as ghosts).
  //
  // strikes: [{
  //   attackerSeat, attackerIdx, defenderSeat,
  //   playerDamage,                       // damage dealt to the defending player
  //   blockers: [{seat, idx, damage, returnDamage, power, toughness}],
  // }]
  playCombatDamage(strikes) {
    if (!Array.isArray(strikes) || !strikes.length) return;
    const now = performance.now();

    // Snapshot each participant once; refs are shared across fx so per-frame
    // resolution (live card vs ghost) stays consistent.
    const refs = new Map();
    const getRef = (seatIdx, idx) => {
      const key = `${seatIdx}-${idx}`;
      let ref = refs.get(key);
      if (ref) return ref;
      const item = this.cardItems.find((c) => c.key === key);
      if (!item) return null;
      const center = this._cardCenter(key) || { x: item.x + BF_CARD_W / 2, y: item.y + BF_CARD_H / 2 };
      ref = { seat: seatIdx, idx, key, name: item.card?.name || "", card: item.card, snapX: center.x, snapY: center.y, tapped: !!item.card?.tapped };
      refs.set(key, ref);
      return ref;
    };
    // Track how long each participant stays involved so its ghost (used only
    // if the creature died) survives until its last fx finishes.
    const ghostEnd = new Map();
    const noteUse = (ref, end) => {
      if (ref) ghostEnd.set(ref, Math.max(ghostEnd.get(ref) || 0, end));
    };

    let lane = 0;
    for (const strike of strikes) {
      const atk = getRef(strike.attackerSeat, strike.attackerIdx);
      if (!atk) continue;
      const t0 = now + lane * BF_COMBAT_STAGGER_MS;
      lane++;
      const forwardY = strike.attackerSeat === this.viewerSeat ? -1 : 1;

      // Punch toward the first blocker when there is one, straight ahead otherwise.
      const blockers = Array.isArray(strike.blockers) ? strike.blockers : [];
      const firstBlocker = blockers.length ? getRef(blockers[0].seat, blockers[0].idx) : null;
      let dirX = 0;
      let dirY = forwardY;
      if (firstBlocker) {
        const dx = firstBlocker.snapX - atk.snapX;
        const dy = firstBlocker.snapY - atk.snapY;
        const len = Math.hypot(dx, dy) || 1;
        dirX = dx / len;
        dirY = dy / len;
      }

      this.combatFx.push({ kind: "chevron", ref: atk, dirY: forwardY, start: t0, dur: BF_CHEVRON_MS });
      this.combatFx.push({ kind: "punch", ref: atk, dirX, dirY, amp: BF_PUNCH_DIST, start: t0, dur: BF_PUNCH_MS });
      noteUse(atk, t0 + Math.max(BF_CHEVRON_MS, BF_PUNCH_MS));

      const impact = t0 + BF_PUNCH_IMPACT_MS;
      const beamDur = BF_BEAM_MS + BF_BEAM_LINGER_MS;

      for (const b of blockers) {
        const bRef = getRef(b.seat, b.idx);
        if (!bRef) continue;
        const arrive = impact + BF_BEAM_MS;
        const damage = Math.max(0, Number(b.damage) || 0);
        if (damage > 0) {
          this.combatFx.push({ kind: "beam", fromRef: atk, toRef: bRef, start: impact, travel: BF_BEAM_MS, dur: beamDur, particles: _beamParticles() });
          this.combatFx.push({ kind: "hit", ref: bRef, start: arrive, dur: BF_HIT_RING_MS });
          const fromT = Number(b.toughness) || 0;
          this.combatFx.push({ kind: "toughness", ref: bRef, power: Number(b.power) || 0, fromT, toT: Math.max(0, fromT - damage), start: arrive, dur: BF_TOUGHNESS_MS });
        }
        // The blocker recoils from the clash either when the beam lands or,
        // for a damage-less clash, right at the punch impact.
        const recoilAt = damage > 0 ? arrive : impact;
        this.combatFx.push({ kind: "recoil", ref: bRef, dirX, dirY, amp: BF_RECOIL_DIST, start: recoilAt, dur: BF_RECOIL_MS });
        noteUse(bRef, Math.max(recoilAt + BF_RECOIL_MS, damage > 0 ? arrive + BF_TOUGHNESS_MS : 0));

        // Blockers deal their damage back to the attacker.
        const returnDamage = Math.max(0, Number(b.returnDamage) || 0);
        if (returnDamage > 0) {
          const returnArrive = arrive + BF_BEAM_MS;
          this.combatFx.push({ kind: "beam", fromRef: bRef, toRef: atk, start: arrive, travel: BF_BEAM_MS, dur: beamDur, particles: _beamParticles() });
          this.combatFx.push({ kind: "hit", ref: atk, start: returnArrive, dur: BF_HIT_RING_MS });
          this.combatFx.push({ kind: "recoil", ref: atk, dirX: -dirX, dirY: -dirY, amp: BF_RECOIL_DIST * 0.8, start: returnArrive, dur: BF_RECOIL_MS });
          noteUse(bRef, arrive + beamDur);
          noteUse(atk, returnArrive + BF_RECOIL_MS);
        }
      }

      if (Number(strike.playerDamage) > 0) {
        this.combatFx.push({ kind: "beam", fromRef: atk, toPlayerSeat: strike.defenderSeat, start: impact, travel: BF_BEAM_MS, dur: beamDur, particles: _beamParticles() });
        noteUse(atk, impact + beamDur);
      }
    }

    // Ghost cards keep dead participants visible while their fx play out.
    for (const [ref, end] of ghostEnd) {
      this.combatFx.push({ kind: "ghost", ref, start: now, dur: end - now + BF_GHOST_FADE_MS });
    }
    this.needsRedraw = true;
  }

  // Per-frame resolution of a combat participant: the live card (tracking
  // layout motion) when it still exists, its snapshot position otherwise.
  _combatRefState(ref) {
    const item = this.cardItems.find((c) => c.key === ref.key);
    if (item && item.card?.name === ref.name && !this.suppressedKeys.has(ref.key)) {
      const c = this._cardCenter(ref.key);
      if (c) return { alive: true, x: c.x, y: c.y };
    }
    return { alive: false, x: ref.snapX, y: ref.snapY };
  }

  _combatOffsetFor(ref) {
    const off = this.combatOffsets.get(ref.key);
    return off && off.name === ref.name ? off : { x: 0, y: 0 };
  }

  // Beam / fx anchor point of a participant, including its punch/recoil offset.
  _combatAnchor(ref) {
    const st = this._combatRefState(ref);
    const off = this._combatOffsetFor(ref);
    return { x: st.x + off.x, y: st.y + off.y };
  }

  // World-space point standing in for a player: the matching table edge.
  _combatPlayerPoint(seatIdx, anchorX) {
    const rect = this._visibleWorldRect();
    const y = seatIdx === this.viewerSeat ? rect.maxY - 26 : rect.minY + 26;
    const x = Math.min(rect.maxX - 40, Math.max(rect.minX + 40, anchorX));
    return { x, y };
  }

  // Advance combat fx: prune finished entries and rebuild the punch/recoil
  // offsets applied to cards this frame. Returns true while any are active.
  _tickCombatFx(now) {
    this.combatOffsets.clear();
    if (!this.combatFx.length) return false;
    this.combatFx = this.combatFx.filter((fx) => now - fx.start < fx.dur);
    for (const fx of this.combatFx) {
      if (fx.kind !== "punch" && fx.kind !== "recoil") continue;
      const t = now - fx.start;
      if (t < 0) continue;
      const env = _strikeEnv(t / fx.dur, fx.kind === "punch" ? 0.32 : 0.22);
      if (env <= 0) continue;
      const off = this.combatOffsets.get(fx.ref.key) || { x: 0, y: 0, name: fx.ref.name };
      off.x += fx.dirX * fx.amp * env;
      off.y += fx.dirY * fx.amp * env;
      this.combatOffsets.set(fx.ref.key, off);
    }
    return this.combatFx.length > 0;
  }

  // ---------------------------------------------------------------------------
  // Automatic camera
  // ---------------------------------------------------------------------------

  // Fit the camera target around every card's layout position (plus the split
  // line, so the table center stays visible even on a sparse board).
  _updateCameraTarget() {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const item of this.cardItems) {
      const b = this._targetBounds(item.key);
      if (!b) continue;
      minX = Math.min(minX, b.x);
      minY = Math.min(minY, b.y);
      maxX = Math.max(maxX, b.x + b.w);
      maxY = Math.max(maxY, b.y + b.h);
    }
    if (!Number.isFinite(minX)) {
      // Empty board: frame a sensible area around the split line.
      minX = 0;
      maxX = 6 * BF_SLOT_PITCH_X;
      minY = BF_WORLD_SPLIT_Y - 220;
      maxY = BF_WORLD_SPLIT_Y + 220;
    }
    // Always keep the split line (and its labels) in frame.
    minY = Math.min(minY, BF_WORLD_SPLIT_Y - 80);
    maxY = Math.max(maxY, BF_WORLD_SPLIT_Y + 80);

    const bx = minX - BF_FIT_PADDING;
    const by = minY - BF_FIT_PADDING;
    const bw = maxX - minX + 2 * BF_FIT_PADDING;
    const bh = maxY - minY + 2 * BF_FIT_PADDING;

    // Visible (non-overscan) part of the tilted canvas, in canvas coordinates.
    const vx = ((this.cssW || 0) * (1 - 1 / BF_OVERSCAN_X)) / 2;
    const vy = ((this.cssH || 0) * (1 - 1 / BF_OVERSCAN_Y)) / 2;
    const vw = (this.cssW || 0) / BF_OVERSCAN_X;
    const vh = (this.cssH || 0) / BF_OVERSCAN_Y;
    if (vw <= 0 || vh <= 0) return;

    const zoom = Math.max(BF_MIN_ZOOM, Math.min(BF_MAX_ZOOM, vw / bw, vh / bh));
    this.camTarget = {
      x: vx + (vw - bw * zoom) / 2 - bx * zoom,
      y: vy + (vh - bh * zoom) / 2 - by * zoom,
      zoom,
    };
  }

  // Ease cards and camera toward their targets (runs every frame).
  _tick() {
    let moving = false;
    for (const item of this.cardItems) {
      const dx = item.tx - item.x;
      const dy = item.ty - item.y;
      if (dx === 0 && dy === 0) continue;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) {
        item.x = item.tx;
        item.y = item.ty;
      } else {
        item.x += dx * BF_CARD_EASE;
        item.y += dy * BF_CARD_EASE;
      }
      moving = true;
    }
    // Stack-zone cards ease toward their cascade slot, growing on the way.
    // Targets are re-pinned to the visible battlefield every frame so camera
    // motion never carries the stack out of view.
    this._retargetStackVisuals();
    for (const v of this.stackVisuals) {
      const dx = v.tcx - v.cx;
      const dy = v.tcy - v.cy;
      const ds = v.tScale - v.scale;
      if (dx !== 0 || dy !== 0 || ds !== 0) {
        if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(ds) < 0.004) {
          v.cx = v.tcx;
          v.cy = v.tcy;
          v.scale = v.tScale;
        } else {
          v.cx += dx * BF_STACK_EASE;
          v.cy += dy * BF_STACK_EASE;
          v.scale += ds * BF_STACK_EASE;
        }
        moving = true;
      }
      // Stamp when the card visually reaches the stack; the resolve dwell
      // is measured from here so the flight doesn't eat into it.
      if (!v.settledAt && Math.abs(v.tcx - v.cx) < 12 && Math.abs(v.tcy - v.cy) < 12) {
        v.settledAt = performance.now();
      }
    }
    this._updateStackHoverFromLastMouse();
    if (this._tickFx(performance.now())) moving = true;
    if (this._tickCombatFx(performance.now())) moving = true;
    const t = this.camTarget;
    if (t && (t.x !== this.camX || t.y !== this.camY || t.zoom !== this.zoom)) {
      const dx = t.x - this.camX;
      const dy = t.y - this.camY;
      const dz = t.zoom - this.zoom;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(dz) < 0.002) {
        this.camX = t.x;
        this.camY = t.y;
        this.zoom = t.zoom;
      } else {
        this.camX += dx * BF_CAM_EASE;
        this.camY += dy * BF_CAM_EASE;
        this.zoom += dz * BF_CAM_EASE;
      }
      moving = true;
    }
    // The priority pulse animates continuously, so keep redrawing while a side
    // holds priority and the game is still going.
    if (this._priorityPulseSide()) moving = true;
    // Flyers bob and tilt continuously, so keep the frame loop alive for them.
    if (!moving && this.cardItems.some((it) => _isFlyer(it.card))) moving = true;
    if (moving) this.needsRedraw = true;
  }

  // ---------------------------------------------------------------------------
  // Selection / highlights
  // ---------------------------------------------------------------------------

  setSelectedKeys(keys) { this.selectedKeys = new Set(keys); this.needsRedraw = true; }
  setAttackingKeys(keys) { this.attackingKeys = new Set(keys); this.needsRedraw = true; }
  setTargetingKeys(keys) { this.targetingKeys = new Set(keys); this.needsRedraw = true; }

  setCombatArrows(arrows) {
    // arrows: [{fromSeat, fromIdx, toSeat, toIdx, kind}]
    this.combatArrows = arrows;
    this.needsRedraw = true;
  }

  // Returns all {seat, idx} pairs in the same stack as the given card, or just the card if not stacked.
  getStackMembers(seat, idx) {
    const key = `${seat}-${idx}`;
    const stack = this.stacks.find((s) => s.keys.includes(key));
    const keys = stack ? stack.keys : [key];
    return keys.map((k) => {
      const item = this.cardItems.find((c) => c.key === k);
      return item ? { seat: item.seat, idx: item.idx } : null;
    }).filter(Boolean);
  }

  // Returns {x, y} in page (client) coordinates for the center of a card.
  getCardPageCenter(seat, idx) {
    const key = `${seat}-${idx}`;
    const pos = this._renderPos(key);
    if (!pos) return null;
    const item = this.cardItems.find((c) => c.key === key);
    const tapped = item?.card?.tapped;
    const wx = tapped ? pos.x + BF_CARD_H / 2 : pos.x + BF_CARD_W / 2;
    const wy = tapped ? pos.y + BF_CARD_W / 2 : pos.y + BF_CARD_H / 2;
    const canvasPos = this.worldToCanvas(wx, wy);
    return this._canvasToPage(canvasPos.x, canvasPos.y);
  }

  // ---------------------------------------------------------------------------
  // Image loading
  // ---------------------------------------------------------------------------

  _loadImage(url) {
    if (!url) return null;
    if (this.imageCache.has(url)) return this.imageCache.get(url);
    if (this.imageLoading.has(url)) return null;
    this.imageLoading.add(url);
    const img = new Image();
    img.onload = () => { this.imageLoading.delete(url); this.imageCache.set(url, img); this.needsRedraw = true; };
    img.onerror = () => { this.imageLoading.delete(url); this.imageCache.set(url, null); };
    img.src = url;
    return null;
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  _drawCardFace(ctx, x, y, w, h, card, flags, creatureCard) {
    const { selected, attacking, hovered, targeting, pileCount } = flags || {};
    const img = card?.image_uri ? this._loadImage(card.image_uri) : null;
    const R = 4;

    ctx.save();

    // ---- Drop shadow onto the table ----
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.55)";
    ctx.shadowBlur = (hovered ? 24 : 12) / this.zoom;
    ctx.shadowOffsetY = (hovered ? 10 : 5) / this.zoom;
    ctx.fillStyle = "rgba(0,0,0,0.4)";
    this._roundRect(ctx, x, y, w, h, R);
    ctx.fill();
    ctx.restore();

    // ---- Clipped card art ----
    ctx.save();
    this._roundRect(ctx, x, y, w, h, R);
    ctx.clip();
    if (img) {
      ctx.drawImage(img, x, y, w, h);
    } else {
      ctx.fillStyle = "#1a2438";
      ctx.fillRect(x, y, w, h);
      if (card?.name) {
        ctx.fillStyle = "#8ab";
        ctx.font = `bold ${Math.max(7, w * 0.11)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        _wrapCanvasText(ctx, card.name, x + w / 2, y + 6, w - 8, Math.max(9, w * 0.12));
      }
    }
    // Summoning sickness tint
    if (card?.summoning_sick) {
      ctx.fillStyle = "rgba(90,20,220,0.22)";
      ctx.fillRect(x, y, w, h);
    }
    ctx.restore();

    // ---- Glow / border ----
    ctx.save();
    if (attacking) { ctx.shadowColor = "#ff5555"; ctx.shadowBlur = 18 / this.zoom; }
    else if (selected) { ctx.shadowColor = "#ffe040"; ctx.shadowBlur = 14 / this.zoom; }
    else if (targeting) { ctx.shadowColor = "#50ffb0"; ctx.shadowBlur = 16 / this.zoom; }
    else if (hovered) { ctx.shadowColor = "#7ec4ff"; ctx.shadowBlur = 10 / this.zoom; }

    ctx.strokeStyle = attacking ? "#ff5555" : selected ? "#ffe040" : targeting ? "#50ffb0" : hovered ? "#7ec4ff" : "rgba(255,255,255,0.22)";
    ctx.lineWidth = (attacking || selected || targeting ? 2.5 : 1) / this.zoom;
    this._roundRect(ctx, x, y, w, h, R);
    ctx.stroke();
    ctx.restore();

    // ---- Keyword strip ----
    // Render the creature's current keywords (Flying, Trample, First Strike, …)
    // in a translucent band just above the badge row. For an enchanted creature
    // hidden under an aura, creatureCard carries the keywords (incl. any the
    // aura grants); otherwise the card's own keywords are used.
    const kwCard = creatureCard || card;
    const keywords = Array.isArray(kwCard?.keywords) ? kwCard.keywords : [];
    if (keywords.length && String(kwCard?.type || "").toLowerCase().includes("creature")) {
      const font = Math.max(6, w * 0.085);
      ctx.font = `bold ${font}px sans-serif`;
      const lineH = font + 2;
      const lines = _wrapKeywordLines(ctx, keywords, w - 6);
      const bandH = lines.length * lineH + 3;
      const reserveBottom = 16; // leave the bottom corners for P/T and damage badges
      const bandBottom = y + h - reserveBottom;
      const bandTop = bandBottom - bandH;
      ctx.fillStyle = "rgba(0,0,0,0.62)";
      ctx.fillRect(x, bandTop, w, bandH);
      ctx.fillStyle = "#ffe9a8";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      let ty = bandTop + 2;
      for (const line of lines) {
        ctx.fillText(line, x + w / 2, ty);
        ty += lineH;
      }
    }

    // ---- P/T badge ----
    // If creatureCard is provided, show its P/T on this card (enchantment on top of creature).
    const ptCard = creatureCard || card;
    if (ptCard && typeof ptCard.power === "number" && typeof ptCard.toughness === "number" && String(ptCard.type || "").toLowerCase().includes("creature")) {
      const bw = 26, bh = 13;
      const bx = x + w - bw - 2, by = y + h - bh - 2;
      ctx.fillStyle = "rgba(0,0,0,0.78)";
      ctx.fillRect(bx, by, bw, bh);
      ctx.font = `bold ${Math.max(8, bh * 0.75)}px sans-serif`;
      ctx.textBaseline = "middle";
      // Green when buffed above the printed base, red when reduced below it,
      // white when unchanged or the base is variable (`*`).
      const ptColor = (value, base) => {
        if (typeof base !== "number") return "#fff";
        if (value > base) return "#5dd55d";
        if (value < base) return "#ff6b6b";
        return "#fff";
      };
      const pStr = String(ptCard.power), tStr = String(ptCard.toughness);
      const wP = ctx.measureText(pStr).width;
      const wSlash = ctx.measureText("/").width;
      const wT = ctx.measureText(tStr).width;
      const cy = by + bh / 2;
      let tx = bx + bw / 2 - (wP + wSlash + wT) / 2;
      ctx.textAlign = "left";
      ctx.fillStyle = ptColor(ptCard.power, ptCard.base_power);
      ctx.fillText(pStr, tx, cy); tx += wP;
      ctx.fillStyle = "#fff";
      ctx.fillText("/", tx, cy); tx += wSlash;
      ctx.fillStyle = ptColor(ptCard.toughness, ptCard.base_toughness);
      ctx.fillText(tStr, tx, cy);
    }

    // ---- Damage badge ----
    const dmgCard = creatureCard || card;
    if (dmgCard && Number(dmgCard.damage_marked) > 0) {
      const bw = 20, bh = 13;
      ctx.fillStyle = "rgba(200,30,30,0.88)";
      ctx.fillRect(x + 2, y + h - bh - 2, bw, bh);
      ctx.fillStyle = "#fff";
      ctx.font = `bold ${Math.max(8, bh * 0.75)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(dmgCard.damage_marked), x + 2 + bw / 2, y + h - bh / 2 - 2);
    }

    // ---- Pile count badge ----
    if (pileCount >= 2) {
      const label = `×${pileCount}`;
      ctx.font = "bold 10px sans-serif";
      const bw = Math.ceil(ctx.measureText(label).width) + 8;
      const bh = 14;
      ctx.fillStyle = "rgba(0,0,0,0.78)";
      this._roundRect(ctx, x + w - bw - 2, y + 2, bw, bh, 3);
      ctx.fill();
      ctx.fillStyle = "#ffd76a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, x + w - 2 - bw / 2, y + 2 + bh / 2);
    }

    ctx.restore();
  }

  _drawCard(ctx, item) {
    // Hidden while its entrance (slam) animation is still playing.
    if (this.suppressedKeys.has(item.key)) return;
    const pos = this._renderPos(item.key);
    if (!pos) return;
    const card = item.card;
    const tapped = card?.tapped;
    const flags = {
      selected: this.selectedKeys.has(item.key),
      attacking: this.attackingKeys.has(item.key),
      targeting: this.targetingKeys.has(item.key),
      hovered: this.hoveredKey === item.key,
    };

    // Topmost (fully visible) card of a pile shows the pile size.
    const pile = this.stacks.find((s) => s.kind === "pile" && s.keys.length >= 2 && s.keys[s.keys.length - 1] === item.key);
    if (pile) flags.pileCount = pile.keys.length;

    // If this is the topmost card in an aura stack, show the bottom creature's P/T and damage on it.
    let creatureCard = null;
    const stack = this.stacks.find((s) => s.kind === "aura" && s.keys.length >= 2 && s.keys[s.keys.length - 1] === item.key);
    if (stack) {
      const bottomItem = this.cardItems.find((c) => c.key === stack.keys[0]);
      if (bottomItem?.card && typeof bottomItem.card.power === "number" && String(bottomItem.card.type || "").toLowerCase().includes("creature")) {
        creatureCard = bottomItem.card;
      }
    }

    ctx.save();
    // Combat punch / recoil knock-back offset.
    const combatOff = this.combatOffsets.get(item.key);
    if (combatOff && combatOff.name === card?.name) {
      ctx.translate(combatOff.x, combatOff.y);
    }
    // Flying creatures float off the board and rock gently side to side, with a
    // soft contact shadow left behind on the table beneath them.
    if (_isFlyer(card)) {
      const center = this._cardCenter(item.key);
      if (center) {
        const now = performance.now();
        // Per-card phase so a board full of flyers doesn't bob in lockstep.
        const phase = _keyPhase(item.key);
        const lift = BF_FLY_LIFT + (0.5 + 0.5 * Math.sin(now / BF_FLY_BOB_MS + phase)) * BF_FLY_BOB;
        // Swivel about the card's vertical (Y) axis, faked on the 2D canvas:
        // compress the width by cos(angle) and add a vertical shear for the
        // perspective so one edge reads as nearer than the other.
        const swing = BF_FLY_TILT * Math.sin(now / BF_FLY_TILT_MS + phase);
        this._drawGroundShadow(ctx, center.x, center.y, lift, tapped);
        ctx.translate(center.x, center.y);
        ctx.translate(0, -lift);
        ctx.transform(Math.cos(swing), Math.sin(swing) * BF_FLY_SKEW, 0, 1, 0, 0);
        ctx.translate(-center.x, -center.y);
      }
    }
    // Hovered cards lift slightly off the table.
    if (flags.hovered) {
      const center = this._cardCenter(item.key);
      if (center) {
        const liftScale = 1.07;
        ctx.translate(center.x, center.y);
        ctx.scale(liftScale, liftScale);
        ctx.translate(-center.x, -center.y);
      }
    }
    if (tapped) {
      const cx = pos.x + BF_CARD_W / 2;
      const cy = pos.y + BF_CARD_H / 2;
      ctx.translate(cx, cy);
      ctx.rotate(Math.PI / 2);
      ctx.translate(-BF_CARD_W / 2, -BF_CARD_H / 2);
      this._drawCardFace(ctx, 0, 0, BF_CARD_W, BF_CARD_H, card, flags, creatureCard);
    } else {
      this._drawCardFace(ctx, pos.x, pos.y, BF_CARD_W, BF_CARD_H, card, flags, creatureCard);
    }
    ctx.restore();
  }

  _drawArrow(ctx, fx, fy, tx, ty, color) {
    const HEAD = 10 / this.zoom;
    const ANGLE = Math.PI / 6;
    const angle = Math.atan2(ty - fy, tx - fx);

    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2.5 / this.zoom;
    ctx.globalAlpha = 0.88;
    ctx.beginPath();
    ctx.moveTo(fx, fy);
    ctx.lineTo(tx, ty);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - HEAD * Math.cos(angle - ANGLE), ty - HEAD * Math.sin(angle - ANGLE));
    ctx.lineTo(tx - HEAD * Math.cos(angle + ANGLE), ty - HEAD * Math.sin(angle + ANGLE));
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  _cardCenter(key) {
    const pos = this._renderPos(key);
    if (!pos) return null;
    const item = this.cardItems.find((c) => c.key === key);
    const tapped = item?.card?.tapped;
    return tapped
      ? { x: pos.x + BF_CARD_H / 2, y: pos.y + BF_CARD_W / 2 }
      : { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2 };
  }

  // Soft contact shadow cast on the table beneath a floating (flying) card. A
  // rounded rectangle that echoes the card's own footprint; the higher it
  // floats, the larger, softer and fainter the shadow gets.
  _drawGroundShadow(ctx, cx, cy, lift, tapped) {
    const t = Math.max(0, Math.min(1, lift / (BF_FLY_LIFT + BF_FLY_BOB)));
    const w = (tapped ? BF_CARD_H : BF_CARD_W) * (0.8 + 0.12 * t);
    const h = (tapped ? BF_CARD_W : BF_CARD_H) * (0.8 + 0.12 * t);
    ctx.save();
    ctx.globalAlpha = 0.4 - 0.14 * t;
    ctx.fillStyle = "#000";
    ctx.shadowColor = "rgba(0,0,0,0.5)";
    ctx.shadowBlur = (12 + 14 * t) / this.zoom;
    this._roundRect(ctx, cx - w / 2, cy - h / 2 + 6, w, h, 6);
    ctx.fill();
    ctx.restore();
  }

  // Which board half should pulse, or null if neither. Returns "you" when the
  // viewer holds priority, "opponent" when the other player does. Suppressed
  // once the game is over.
  _priorityPulseSide() {
    const st = this.currentState;
    if (!st || st.winner !== null && st.winner !== undefined) return null;
    const pp = st.priority_player;
    if (pp !== 0 && pp !== 1) return null;
    return pp === this.viewerSeat ? "you" : "opponent";
  }

  _drawPriorityPulse(ctx, cw, ch, grid) {
    const side = this._priorityPulseSide();
    if (!side) return;
    const splitY = this.worldToCanvas(0, BF_WORLD_SPLIT_Y).y;
    const yTop = side === "you" ? splitY : 0;
    const yBot = side === "you" ? ch : splitY;
    if (yBot - yTop <= 1) return;
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 350);
    const alpha = 0.08 + pulse * 0.24;
    const color = side === "you" ? `rgba(74,222,128,${alpha})` : `rgba(248,82,82,${alpha})`;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, yTop, cw, yBot - yTop);
    ctx.clip();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let gx = ((cw / 2) % grid); gx < cw; gx += grid) {
      ctx.moveTo(gx, yTop);
      ctx.lineTo(gx, yBot);
    }
    for (let gy = ((ch / 2) % grid); gy < ch; gy += grid) {
      ctx.moveTo(0, gy);
      ctx.lineTo(cw, gy);
    }
    ctx.stroke();
    ctx.restore();
  }

  _render() {
    if (!this.needsRedraw) return;
    this.needsRedraw = false;

    const canvas = this.canvas;
    const ctx = this.ctx;
    const scale = this.renderScale || this.dpr;
    const cw = canvas.width / scale;
    const ch = canvas.height / scale;

    ctx.setTransform(scale, 0, 0, scale, 0, 0);

    // ---- Table surface ----
    // Vertical gradient: darker toward the far (opponent) edge, lighter up close.
    const bgGrad = ctx.createLinearGradient(0, 0, 0, ch);
    bgGrad.addColorStop(0, "#0b1320");
    bgGrad.addColorStop(0.45, "#152434");
    bgGrad.addColorStop(1, "#21344b");
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, cw, ch);

    // Soft center sheen
    const sheen = ctx.createRadialGradient(cw / 2, ch / 2, 0, cw / 2, ch / 2, Math.max(cw, ch) * 0.62);
    sheen.addColorStop(0, "rgba(126,196,255,0.09)");
    sheen.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = sheen;
    ctx.fillRect(0, 0, cw, ch);

    // Subtle grid: straight lines on the plane converge on screen under the
    // real 3D tilt, which is what visually sells the perspective.
    ctx.save();
    ctx.strokeStyle = "rgba(126,196,255,0.055)";
    ctx.lineWidth = 1;
    const GRID = 92;
    ctx.beginPath();
    for (let gx = ((cw / 2) % GRID); gx < cw; gx += GRID) {
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, ch);
    }
    for (let gy = ((ch / 2) % GRID); gy < ch; gy += GRID) {
      ctx.moveTo(0, gy);
      ctx.lineTo(cw, gy);
    }
    ctx.stroke();
    ctx.restore();

    // ---- Priority pulse: tint the grid on the half of the player who holds
    // priority — green on your side, red on the opponent's side — so it's
    // obvious at a glance whose turn it is to act.
    this._drawPriorityPulse(ctx, cw, ch, GRID);

    // Edge vignette so the table fades out toward the stage borders
    const vig = ctx.createRadialGradient(cw / 2, ch / 2, Math.min(cw, ch) * 0.38, cw / 2, ch / 2, Math.max(cw, ch) * 0.78);
    vig.addColorStop(0, "rgba(0,0,0,0)");
    vig.addColorStop(1, "rgba(0,0,0,0.42)");
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, cw, ch);

    // ---- Glowing separator between the two player halves ----
    const splitCanvas = this.worldToCanvas(0, BF_WORLD_SPLIT_Y);
    ctx.save();
    const lineGrad = ctx.createLinearGradient(0, 0, cw, 0);
    lineGrad.addColorStop(0, "rgba(126,196,255,0)");
    lineGrad.addColorStop(0.5, "rgba(126,196,255,0.45)");
    lineGrad.addColorStop(1, "rgba(126,196,255,0)");
    // Soft glow band
    ctx.fillStyle = lineGrad;
    ctx.globalAlpha = 0.16;
    ctx.fillRect(0, splitCanvas.y - 9, cw, 18);
    ctx.globalAlpha = 1;
    // Crisp core line
    ctx.strokeStyle = lineGrad;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, splitCanvas.y);
    ctx.lineTo(cw, splitCanvas.y);
    ctx.stroke();
    ctx.fillStyle = "rgba(190,215,240,0.22)";
    ctx.font = "600 13px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("OPPONENT", cw / 2, splitCanvas.y - 7);
    ctx.textBaseline = "top";
    ctx.fillText("YOU", cw / 2, splitCanvas.y + 7);
    ctx.restore();

    // Apply camera transform for world-space drawing
    ctx.save();
    ctx.translate(this.camX, this.camY);
    ctx.scale(this.zoom, this.zoom);

    // ---- Draw all cards (stacked items render on top due to sort order) ----
    for (const item of this.cardItems) {
      this._drawCard(ctx, item);
    }

    // ---- Combat arrows ----
    for (const arrow of this.combatArrows) {
      const fc = this._cardCenter(`${arrow.fromSeat}-${arrow.fromIdx}`);
      const tc = this._cardCenter(`${arrow.toSeat}-${arrow.toIdx}`);
      if (fc && tc) {
        this._drawArrow(ctx, fc.x, fc.y, tc.x, tc.y, arrow.kind === "blocker" ? "#48b0ff" : "#ff6060");
      }
    }

    // ---- Live blocker-assignment drag arrow ----
    if (this.pressState?.combatDrag) {
      const fc = this._cardCenter(this.pressState.key);
      const tw = this.canvasToWorld(this.pressState.currentCX, this.pressState.currentCY);
      if (fc) {
        this._drawArrow(ctx, fc.x, fc.y, tw.x, tw.y, "#ff8888");
      }
    }

    // ---- Combat damage fx (ghosts, beams, chevrons, hit flashes, tickers) ----
    this._drawCombatFx(ctx, performance.now());

    // ---- Spell stack zone and cast/resolve animations (drawn on top) ----
    this._drawStackAndFx(ctx);

    ctx.restore(); // camera
  }

  _drawCombatFx(ctx, now) {
    if (!this.combatFx.length) return;
    const ordered = [...this.combatFx].sort(
      (a, b) => (_COMBAT_FX_DRAW_ORDER[a.kind] || 0) - (_COMBAT_FX_DRAW_ORDER[b.kind] || 0)
    );
    for (const fx of ordered) {
      const t = now - fx.start;
      if (t < 0 || t >= fx.dur) continue;
      const p = t / fx.dur;
      switch (fx.kind) {
        case "ghost": this._drawCombatGhost(ctx, fx, p); break;
        case "beam": this._drawCombatBeam(ctx, fx, t, now); break;
        case "hit": this._drawCombatHit(ctx, fx, p); break;
        case "chevron": this._drawCombatChevron(ctx, fx, now, p); break;
        case "toughness": this._drawCombatToughness(ctx, fx, p); break;
      }
    }
  }

  // A participant that left the battlefield mid-animation keeps rendering at
  // its snapshot position (with its knock-back offset) until its fx finish.
  _drawCombatGhost(ctx, fx, p) {
    const st = this._combatRefState(fx.ref);
    if (st.alive) return;
    const fadeStart = Math.max(0, 1 - BF_GHOST_FADE_MS / fx.dur);
    const alpha = p > fadeStart ? (1 - p) / (1 - fadeStart) : 1;
    const off = this._combatOffsetFor(fx.ref);
    this._drawFloatingCard(ctx, fx.ref.card, st.x + off.x, st.y + off.y, 1, alpha * 0.95, false, fx.ref.tapped ? Math.PI / 2 : 0);
  }

  _drawCombatBeam(ctx, fx, t, now) {
    const a = this._combatAnchor(fx.fromRef);
    const b = fx.toPlayerSeat != null ? this._combatPlayerPoint(fx.toPlayerSeat, a.x) : this._combatAnchor(fx.toRef);
    const h = Math.min(1, t / fx.travel);
    const fade = t <= fx.travel ? 1 : Math.max(0, 1 - (t - fx.travel) / (fx.dur - fx.travel));
    const hx = _lerp(a.x, b.x, h);
    const hy = _lerp(a.y, b.y, h);
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const px = -dy / len;
    const py = dx / len;

    ctx.save();
    ctx.shadowColor = "#ff3322";
    ctx.shadowBlur = 12 / this.zoom;

    // Core ray up to the beam head
    ctx.strokeStyle = `rgba(255,64,48,${0.5 * fade})`;
    ctx.lineWidth = 3 / this.zoom;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(hx, hy);
    ctx.stroke();

    // Bright head while traveling
    if (t <= fx.travel) {
      ctx.fillStyle = `rgba(255,170,130,${0.95 * fade})`;
      ctx.beginPath();
      ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Particles streaming from the source toward the target
    for (const part of fx.particles) {
      const u = (part.u0 + t / 520) % 1;
      if (u > h) continue;
      const wobble = Math.sin(now / 120 + part.ph) * part.j;
      const x = _lerp(a.x, b.x, u) + px * wobble;
      const y = _lerp(a.y, b.y, u) + py * wobble;
      const twinkle = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(now / 90 + part.ph * 3));
      ctx.fillStyle = `rgba(255,110,80,${fade * twinkle})`;
      ctx.beginPath();
      ctx.arc(x, y, part.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  // Red flash + expanding ring where damage lands.
  _drawCombatHit(ctx, fx, p) {
    const c = this._combatAnchor(fx.ref);
    const k = _easeOutCubic(p);
    ctx.save();
    ctx.fillStyle = `rgba(255,80,56,${0.28 * (1 - p)})`;
    ctx.beginPath();
    ctx.arc(c.x, c.y, 14 + 26 * k, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = `rgba(255,90,60,${0.85 * (1 - p)})`;
    ctx.lineWidth = 3 / this.zoom;
    ctx.beginPath();
    ctx.arc(c.x, c.y, 12 + 40 * k, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  // Glowing red chevron hovering off the attacker's leading edge, pointing at
  // the opponent. A fainter trailing chevron sells the direction.
  _drawCombatChevron(ctx, fx, now, p) {
    const st = this._combatRefState(fx.ref);
    const off = this._combatOffsetFor(fx.ref);
    const item = this.cardItems.find((c) => c.key === fx.ref.key);
    const tapped = st.alive ? !!item?.card?.tapped : fx.ref.tapped;
    const half = tapped ? BF_CARD_W / 2 : BF_CARD_H / 2;
    const dir = fx.dirY; // -1 when the opponent is up-screen, +1 when down
    const alpha = Math.min(1, p / 0.12) * Math.min(1, (1 - p) / 0.25);
    const pulse = 0.7 + 0.3 * Math.sin(now / 110);
    const bob = Math.sin(now / 150) * 3;
    const cx = st.x + off.x;
    const baseY = st.y + off.y + dir * (half + 22 + bob);

    ctx.save();
    ctx.lineWidth = 4.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.shadowColor = "#ff2a1a";
    ctx.shadowBlur = 16 / this.zoom;
    for (let i = 0; i < 2; i++) {
      const yOff = baseY - dir * i * 11;
      ctx.strokeStyle = `rgba(255,70,50,${alpha * pulse * (i === 0 ? 1 : 0.45)})`;
      ctx.beginPath();
      ctx.moveTo(cx - 13, yOff - dir * 7);
      ctx.lineTo(cx, yOff + dir * 7);
      ctx.lineTo(cx + 13, yOff - dir * 7);
      ctx.stroke();
    }
    ctx.restore();
  }

  // Floating P/T readout over a blocker whose toughness counts down by the
  // damage it just took, drifting up and fading out.
  _drawCombatToughness(ctx, fx, p) {
    const st = this._combatRefState(fx.ref);
    const off = this._combatOffsetFor(fx.ref);
    const tickP = Math.min(1, p / 0.65); // count down, then hold the result
    const value = Math.round(_lerp(fx.fromT, fx.toT, _easeOutCubic(tickP)));
    const alpha = p > 0.8 ? (1 - p) / 0.2 : 1;
    const half = fx.ref.tapped ? BF_CARD_W / 2 : BF_CARD_H / 2;
    const x = st.x + off.x;
    const y = st.y + off.y - half - 10 - 10 * p;
    const label = `${fx.power}/${value}`;
    ctx.save();
    ctx.font = "bold 16px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.shadowColor = "#ff2a1a";
    ctx.shadowBlur = 10 / this.zoom;
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = `rgba(20,8,8,${0.85 * alpha})`;
    ctx.strokeText(label, x, y);
    ctx.fillStyle = value <= 0 ? `rgba(255,60,60,${alpha})` : `rgba(255,120,100,${alpha})`;
    ctx.fillText(label, x, y);
    ctx.restore();
  }

  _drawStackAndFx(ctx) {
    if (this.stackVisuals.length) {
      // Faint zone label below the cascade.
      const n = this.stackVisuals.length;
      const h = BF_CARD_H * (BF_STACK_SCALE / this.zoom);
      const labelX = this.stackVisuals.reduce((sum, v) => sum + v.tcx, 0) / n;
      const labelY = Math.max(...this.stackVisuals.map((v) => v.tcy)) + h / 2 + 12 / this.zoom;
      ctx.save();
      ctx.fillStyle = "rgba(190,215,240,0.3)";
      ctx.font = `600 ${13 / this.zoom}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText("STACK", labelX, labelY);
      ctx.restore();
    }

    // Bottom of the stack first; the top spell (next to resolve) draws on
    // top. The hovered card grows, so it draws above everything else.
    for (let i = this.stackVisuals.length - 1; i >= 0; i--) {
      if (i === this.hoveredStackIndex) continue;
      const v = this.stackVisuals[i];
      this._drawFloatingCard(ctx, v.item?.card, v.cx, v.cy, v.scale, 1, i === this.stackHeldIndex);
    }
    const hoveredVisual = this.hoveredStackIndex != null ? this.stackVisuals[this.hoveredStackIndex] : null;
    if (hoveredVisual) {
      this._drawFloatingCard(ctx, hoveredVisual.item?.card, hoveredVisual.cx, hoveredVisual.cy, hoveredVisual.scale, 1, true);
    }

    this._drawStackHoldUi(ctx);

    for (const fx of this.fxAnims) {
      if (fx.type === "ring") {
        const k = Math.min(1, Math.max(0, fx.t));
        ctx.save();
        ctx.strokeStyle = `rgba(255,225,140,${0.7 * (1 - k)})`;
        ctx.lineWidth = 3 / this.zoom;
        ctx.beginPath();
        ctx.arc(fx.x, fx.y, 18 + 52 * k, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      } else {
        this._drawFloatingCard(ctx, fx.card, fx.x, fx.y, fx.scale, fx.alpha, fx.lifted);
      }
    }
  }

  // Hover/click-hold affordances for the floating stack cascade: a glowing
  // border on the click-held card, and a hint label beside the hovered card
  // ("Click to hold priority" / "Priority held — click to release"). The
  // stack hugs the right edge, so the label goes to the card's left.
  _drawStackHoldUi(ctx) {
    const heldVisual = this.stackHeldIndex != null ? this.stackVisuals[this.stackHeldIndex] : null;
    if (heldVisual) {
      const w = BF_CARD_W * heldVisual.scale;
      const h = BF_CARD_H * heldVisual.scale;
      ctx.save();
      ctx.strokeStyle = "rgba(126, 196, 255, 0.95)";
      ctx.lineWidth = 3 / this.zoom;
      ctx.shadowColor = "#7ec4ff";
      ctx.shadowBlur = 14 / this.zoom;
      ctx.strokeRect(heldVisual.cx - w / 2, heldVisual.cy - h / 2, w, h);
      ctx.restore();
    }

    const labelIndex = this.hoveredStackIndex != null ? this.hoveredStackIndex : this.stackHeldIndex;
    const labelVisual = labelIndex != null ? this.stackVisuals[labelIndex] : null;
    if (!labelVisual) return;
    const text = labelIndex === this.stackHeldIndex
      ? "Priority held — click to release"
      : "Click to hold priority";
    const w = BF_CARD_W * labelVisual.scale;
    const tx = labelVisual.cx - w / 2 - 10 / this.zoom;
    const ty = labelVisual.cy;
    ctx.save();
    ctx.font = `600 ${13 / this.zoom}px sans-serif`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const pad = 6 / this.zoom;
    const tw = ctx.measureText(text).width;
    const th = 18 / this.zoom;
    ctx.fillStyle = "rgba(12, 20, 32, 0.82)";
    ctx.fillRect(tx - tw - pad, ty - th / 2 - pad / 2, tw + pad * 2, th + pad);
    ctx.fillStyle = "rgba(126, 196, 255, 0.95)";
    ctx.fillText(text, tx, ty);
    ctx.restore();
  }

  // Draw a card centered at (cx, cy) at an arbitrary scale/alpha; `lifted`
  // borrows the hover treatment (bigger drop shadow) to sell height.
  _drawFloatingCard(ctx, card, cx, cy, scale, alpha, lifted, rot = 0) {
    if (!(scale > 0) || !(alpha > 0)) return;
    const w = BF_CARD_W * scale;
    const h = BF_CARD_H * scale;
    ctx.save();
    ctx.globalAlpha = Math.min(1, alpha);
    if (rot) {
      ctx.translate(cx, cy);
      ctx.rotate(rot);
      this._drawCardFace(ctx, -w / 2, -h / 2, w, h, card, { hovered: !!lifted });
    } else {
      this._drawCardFace(ctx, cx - w / 2, cy - h / 2, w, h, card, { hovered: !!lifted });
    }
    ctx.restore();
  }

  _startLoop() {
    const loop = () => {
      this._tick();
      this._render();
      this.rafId = requestAnimationFrame(loop);
    };
    this.rafId = requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------------------
  // Events
  // ---------------------------------------------------------------------------

  _resize() {
    const container = this.canvas.parentElement;
    if (!container) return;
    const r = container.getBoundingClientRect();
    const baseW = Math.max(r.width || 600, 300);
    const baseH = Math.max(r.height || 400, 200);
    // Oversize the plane so the tilted projection still covers the stage,
    // and keep it centered on the wrapper (origin of the projection math).
    const w = baseW * BF_OVERSCAN_X;
    const h = baseH * BF_OVERSCAN_Y;
    this.cssW = w;
    this.cssH = h;
    this.renderScale = this.dpr * BF_OVERSAMPLE;
    this.canvas.width = Math.round(w * this.renderScale);
    this.canvas.height = Math.round(h * this.renderScale);
    this.canvas.style.width = w + "px";
    this.canvas.style.height = h + "px";
    this.canvas.style.left = (baseW - w) / 2 + "px";
    this.canvas.style.top = (baseH - h) / 2 + "px";
    this._updateCameraTarget();
    this.needsRedraw = true;
  }

  _bindEvents() {
    this._mdown = (e) => this._handleMouseDown(e);
    this._mmove = (e) => this._handleMouseMove(e);
    this._mup = (e) => this._handleMouseUp(e);
    this._mwheel = (e) => e.preventDefault(); // camera is automatic; just stop page scroll
    this._mctx = (e) => this._handleContextMenu(e);
    this._dragover = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; this.canvas.classList.add("active-drop"); };
    this._dragleave = () => this.canvas.classList.remove("active-drop");
    this._drop = (e) => this._handleDrop(e);

    this.canvas.addEventListener("mousedown", this._mdown);
    window.addEventListener("mousemove", this._mmove);
    window.addEventListener("mouseup", this._mup);
    this.canvas.addEventListener("wheel", this._mwheel, { passive: false });
    this.canvas.addEventListener("contextmenu", this._mctx);
    this.canvas.addEventListener("dragover", this._dragover);
    this.canvas.addEventListener("dragleave", this._dragleave);
    this.canvas.addEventListener("drop", this._drop);

    this._resizeObs = new ResizeObserver(() => { this._resize(); });
    if (this.canvas.parentElement) this._resizeObs.observe(this.canvas.parentElement);
  }

  _unbindEvents() {
    this.canvas.removeEventListener("mousedown", this._mdown);
    window.removeEventListener("mousemove", this._mmove);
    window.removeEventListener("mouseup", this._mup);
    this.canvas.removeEventListener("wheel", this._mwheel);
    this.canvas.removeEventListener("contextmenu", this._mctx);
    this.canvas.removeEventListener("dragover", this._dragover);
    this.canvas.removeEventListener("dragleave", this._dragleave);
    this.canvas.removeEventListener("drop", this._drop);
    this._resizeObs?.disconnect();
  }

  _isCombatBlockerPhase() {
    const s = this.currentState;
    if (!s) return false;
    return s.current_turn_phase === "combat" && s.current_step === "declare_blockers";
  }

  _handleMouseDown(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);

    // Floating stack cards draw above the battlefield, so they win the press.
    const stackHit = this._hitTestStack(world.x, world.y);
    if (stackHit) {
      this.pressState = {
        stackIndex: stackHit.index,
        key: null,
        seat: null,
        idx: null,
        card: stackHit.item?.card || null,
        startCX: cx,
        startCY: cy,
        currentCX: cx,
        currentCY: cy,
        combatDrag: false,
        cancelled: false,
      };
      return;
    }

    const item = this._hitTest(world.x, world.y);
    if (!item) return;

    this.pressState = {
      key: item.key,
      seat: item.seat,
      idx: item.idx,
      card: item.card,
      startCX: cx,
      startCY: cy,
      currentCX: cx,
      currentCY: cy,
      combatDrag: false,
      cancelled: false,
    };
  }

  _handleMouseMove(event) {
    this._lastMouseClient = { x: event.clientX, y: event.clientY };
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);

    const ps = this.pressState;
    if (ps) {
      ps.currentCX = cx;
      ps.currentCY = cy;
      const dx = Math.abs(cx - ps.startCX);
      const dy = Math.abs(cy - ps.startCY);

      if (!ps.combatDrag && !ps.cancelled && (dx > 4 || dy > 4)) {
        // The only drag interaction: in declare_blockers, dragging one of my
        // creatures onto an attacker assigns it as a blocker.
        const canCombatDrag =
          this._isCombatBlockerPhase() &&
          this.currentState?.combat?.defending_player_index === this.viewerSeat &&
          ps.seat === this.viewerSeat &&
          ps.card?.attached_to_index == null;
        if (canCombatDrag) {
          ps.combatDrag = true;
        } else if (dx > 10 || dy > 10) {
          // Moved too far to be a click; cards can't be repositioned manually.
          ps.cancelled = true;
        }
      }

      if (ps.combatDrag) this.needsRedraw = true;
      return;
    }

    // Hover — the floating stack cascade sits above battlefield cards.
    const stackHit = this._updateStackHover(world.x, world.y);

    const item = stackHit ? null : this._hitTest(world.x, world.y);
    const newKey = item?.key || null;
    this.canvas.style.cursor = (item || stackHit) ? "pointer" : "default";
    if (newKey !== this.hoveredKey) {
      this.hoveredKey = newKey;
      this.needsRedraw = true;
      if (this.onCardHover) {
        this.onCardHover(item ? { seat: item.seat, idx: item.idx, card: item.card } : null);
      }
    }
  }

  _handleMouseUp(event) {
    if (event.button !== 0 || !this.pressState) return;

    const ps = this.pressState;
    this.pressState = null;
    this.needsRedraw = true;

    if (ps.combatDrag) {
      // Blocker assignment: find attacker under cursor
      const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
      const world = this.canvasToWorld(cx, cy);
      const target = this._hitTest(world.x, world.y);
      if (
        target &&
        target.seat !== this.viewerSeat &&
        target.key !== ps.key &&
        this.onBlockerAssign
      ) {
        this.onBlockerAssign({ blockerIdx: ps.idx, attackerIdx: target.idx });
      }
      return;
    }

    if (!ps.cancelled && ps.stackIndex != null) {
      if (this.onStackCardClick) {
        this.onStackCardClick({ index: ps.stackIndex, item: this.stackVisuals[ps.stackIndex]?.item || null });
      }
      return;
    }

    if (!ps.cancelled && this.onCardClick) {
      this.onCardClick({ seat: ps.seat, idx: ps.idx, card: ps.card });
    }
  }

  _handleContextMenu(event) {
    event.preventDefault();
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);
    const item = this._hitTest(world.x, world.y);
    if (item && this.onCardContextMenu) {
      this.onCardContextMenu({ seat: item.seat, idx: item.idx, card: item.card, event });
    }
  }

  _handleDrop(event) {
    event.preventDefault();
    this.canvas.classList.remove("active-drop");

    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);

    // Determine seat from vertical position relative to split
    const dropSeat = world.y < BF_WORLD_SPLIT_Y ? (1 - this.viewerSeat) : this.viewerSeat;

    // Check for card under cursor (for blocker assignment or aura targeting)
    const item = this._hitTest(world.x, world.y);

    if (this.onHandCardDrop) {
      this.onHandCardDrop({
        event,
        targetSeat: dropSeat,
        targetItem: item ? { seat: item.seat, idx: item.idx, card: item.card } : null,
        dropWorldX: world.x,
        dropWorldY: world.y,
      });
    }
  }
}

// ---- Easing helpers for the spell animations ----
function _lerp(a, b, t) {
  return a + (b - a) * t;
}

function _easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

function _easeInCubic(t) {
  return t * t * t;
}

function _easeInQuad(t) {
  return t * t;
}

// ---- Combat fx helpers ----

// Draw order within a frame: ghosts under everything, text on top.
const _COMBAT_FX_DRAW_ORDER = { ghost: 0, beam: 1, hit: 2, chevron: 3, toughness: 4 };

// Out-and-back envelope for punches/recoils: fast strike out (the first
// `out` fraction of the duration), then a smooth settle back to rest.
function _strikeEnv(p, out) {
  if (p <= 0 || p >= 1) return 0;
  if (p < out) return _easeOutCubic(p / out);
  const r = (p - out) / (1 - out);
  return 1 - r * r * (3 - 2 * r);
}

// Random particle set for one damage beam.
function _beamParticles() {
  const particles = [];
  for (let i = 0; i < 22; i++) {
    particles.push({
      u0: Math.random(),
      j: (Math.random() - 0.5) * 10,
      r: 1.2 + Math.random() * 2,
      ph: Math.random() * Math.PI * 2,
    });
  }
  return particles;
}

// True for a battlefield creature that has the Flying keyword (case-insensitive).
function _isFlyer(card) {
  if (!card || !String(card.type || "").toLowerCase().includes("creature")) return false;
  const kws = Array.isArray(card.keywords) ? card.keywords : [];
  return kws.some((k) => String(k).toLowerCase() === "flying");
}

// Stable per-card phase offset (radians) derived from its key, so multiple
// flyers bob and tilt out of sync rather than in lockstep.
function _keyPhase(key) {
  let h = 0;
  const s = String(key);
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return ((h % 1000) / 1000) * Math.PI * 2;
}

// Wrap a list of keywords into lines that fit maxWidth, keeping each keyword
// whole (never splitting "First Strike" across two lines). The active ctx font
// must already be set so measurement matches what gets drawn.
function _wrapKeywordLines(ctx, keywords, maxWidth) {
  const lines = [];
  let line = "";
  for (const kw of keywords) {
    const test = line ? `${line}  ${kw}` : kw;
    if (line && ctx.measureText(test).width > maxWidth) {
      lines.push(line);
      line = kw;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines;
}

// Utility: word-wrap text on canvas
function _wrapCanvasText(ctx, text, centerX, y, maxWidth, lineHeight) {
  const words = String(text || "").split(" ");
  let line = "";
  for (const word of words) {
    const test = line ? line + " " + word : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, centerX, y);
      line = word;
      y += lineHeight;
    } else {
      line = test;
    }
  }
  if (line) ctx.fillText(line, centerX, y);
}
