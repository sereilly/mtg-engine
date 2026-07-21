// battlefield-canvas.js — canvas-based battlefield renderer, projected onto a
// 3D-tilted table plane (bird's-eye Arena-style view).
//
// Layout is fully automatic: identical cards collapse into piles, piles are
// arranged into per-player bands (creatures in front near the split line,
// support permanents in the middle, lands in the back), and the camera pans
// and zooms on its own to keep every card in view. There is no manual panning
// or card dragging; the only drag interaction left is assigning blockers.
//
// 3-4 player (Free-For-All) games split the stage into one clipped screen
// viewport per seat (separated by glowing divider lines), each rendered
// through its OWN automatic camera so every quadrant independently fits its
// permanents and zone piles regardless of how crowded the other seats are.

const BF_CARD_W = 80;
const BF_CARD_H = 112;
// Glow tint for each mana symbol's wedge in the land mana-choice fan.
const BF_MANA_GLOW = { W: "#f4eec6", U: "#4a90d9", B: "#9a6bbf", R: "#e0483b", G: "#46b95f", C: "#c2c6cf" };
// Mana fan layout (world units / ms).
const BF_MANA_FAN_RADIUS = 84;   // distance the symbols travel out from the card center
const BF_MANA_FAN_SYM_R = 18;    // radius of each circular mana token
const BF_MANA_FAN_POP_MS = 300;  // per-symbol pop-out duration
const BF_MANA_FAN_STAGGER = 50;  // delay between successive symbols popping
// Hover hit-box (world units) for the shield badge at a card's top-left corner.
const SHIELD_BADGE_HIT = 24;

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
// Free-For-All (3-4 player) quadrant layout. 2-player games never use these:
// _quadrantFor()/_seatForWorldPoint() reproduce the original single-split
// behavior exactly whenever there are 2 or fewer players. For 3-4 players the
// board is additionally split left/right at this world X, giving four
// quadrants (BF_WORLD_SPLIT_Y still divides top/bottom). The shift is wide
// enough to clear a full BF_MAX_COLS-wide row (including per-slot side-aura
// overhang) so the two X columns never collide.
const BF_QUADRANT_SHIFT_X = 1400;
const BF_QUADRANT_BOUNDARY_X = BF_QUADRANT_SHIFT_X / 2;

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
// An aura enchanting another enchantment is drawn beside its target (shifted
// right by this much) with a curved connector arrow, rather than stacked over
// it — stacking would hide the enchantment underneath, which (unlike a
// creature) has no separate P/T to peek out. Offset is a full card width plus a
// gap so the two cards sit clearly apart rather than touching.
const BF_AURA_SIDE_X = BF_CARD_W + 26;

// ---- Automatic camera ----
const BF_MIN_ZOOM = 0.3;
const BF_MAX_ZOOM = 1.15;
const BF_FIT_PADDING = 44; // world-space padding around the fitted bounding box
const BF_CAM_EASE = 0.16; // per-frame easing toward the camera target
const BF_CARD_EASE = 0.22; // per-frame easing of cards toward their slots
// The DOM hand fans overlay the top/bottom of the stage, so the camera must
// not park cards under them (a full board would otherwise hide the viewer's
// land row behind their hand). Screen-space bands, measured from the stage
// edges, that the fit treats as unusable while the matching hand has cards.
const BF_HAND_RESERVE_BOTTOM = 130; // viewer hand fan (tucked: only the top half of each card shows)
const BF_HAND_RESERVE_TOP = 120; // opponent hand fan (75px card backs)
// With no hand to dodge, still keep a small strip clear for the player
// info pills that sit over the stage edges.
const BF_EDGE_RESERVE_BOTTOM = 40;
const BF_EDGE_RESERVE_TOP = 64;

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

// ---- Zone piles (library / graveyard / exile) ----
// Each player's deck, graveyard, and exile render as card piles pinned to the
// left edge of the visible battlefield (opponent top-left, viewer bottom-left),
// mirroring how the stack cascade pins to the right edge. Sizes divide by zoom
// so the piles keep a constant on-screen size.
const BF_ZONE_PILE_SCALE = 0.8;
const BF_ZONE_LEFT_INSET_PX = 165; // pile left edge, in PAGE px from the stage's left edge (clears the DOM phase rail)
const BF_ZONE_PILE_GAP_PX = 26; // vertical gap between piles (leaves room for labels)
const BF_ZONE_TOP_INSET_PX = 64; // clears the opponent name/life pill
const BF_ZONE_BOTTOM_INSET_PX = 116; // clears the viewer name/life pill
const BF_ZONE_RIGHT_INSET_PX = 56; // stack cascade reserve for the DOM mana column
// Free-For-All: each seat's piles pin inside that seat's own screen viewport
// instead of the stage edge. A viewport whose left edge is the vertical
// separator (right-half seats) uses this small inset; a viewport at the
// stage's left edge keeps BF_ZONE_LEFT_INSET_PX to clear the DOM phase rail.
const BF_ZONE_INNER_LEFT_INSET_PX = 30;
// FFA corner-hand clearances: every top-half seat fans card backs over the
// top edge of its viewport, so top pile columns start below that band; the
// 4-player bottom-right opponent fans over the bottom edge the same way; and
// with 4 players the viewer's hand shifts into the bottom-left half, over
// the classic bottom pile spot, so that column rises above the tucked fan.
const BF_ZONE_TOP_INSET_FFA_PX = 140;
const BF_ZONE_BOTTOM_INSET_FFA4_PX = 155;
const BF_CARD_BACK_URL = "/images/card_back.webp";

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

    // Palette bridge: state colors shared with the DOM glass theme. Resolved
    // from CSS custom properties once so canvas drawing and CSS stay in sync;
    // the hard-coded fallbacks match the stylesheet's values.
    this.theme = this._resolveTheme();
    // Respect reduced-motion: continuous decorative effects (arrow pulses)
    // render as static art instead.
    this.reducedMotion = !!(window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

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

    // Free-For-All (3-4 players): one automatic camera per seat viewport,
    // seat -> {x, y, zoom, target, fresh}. camX/camY/zoom then act as the
    // ACTIVE camera registers: world-space drawing and hit-testing run with a
    // seat's camera loaded via _withCam. 2-player games never touch this and
    // keep using the single global camera directly.
    this.seatCams = new Map();

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

    // Library / graveyard / exile piles pinned to the left edge of the view:
    // [{seat, kind: "library"|"graveyard"|"exile", count, topCard, cx, cy, w, h}]
    // Positions are recomputed every tick from the visible rect, like the
    // stack cascade — the piles never participate in the camera fit.
    this.zonePiles = [];
    this.hoveredZonePile = null; // {seat, kind} | null
    // Gold targeting pulse pushed from app.js while a spell targets a
    // graveyard card: {kind: "graveyard", seats: [..]} | null.
    this.zonePileTargeting = null;
    // Stack-cascade indices that are legal targets for the in-progress cast
    // (Counterspell, Fork) — Set<int> | null, pushed from app.js.
    this.stackTargetableIndices = null;

    // Time-based resolve animations (card flights + impact rings) and the
    // battlefield keys hidden while their entrance animation plays.
    this.fxAnims = [];
    this.suppressedKeys = new Set();

    // Active mana-color chooser: when a land that taps for more than one color
    // is activated, its mana symbols pop out of the card in a fan and the
    // player clicks one. null when no choice is pending.
    // { key, colors: [{symbol,label}], start, hovered }
    this.manaFan = null;

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
    this.onEmblemClick = callbacks.onEmblemClick || null;
    this.onEmblemHover = callbacks.onEmblemHover || null;
    // Fires with the granting card's preview payload when the damage-prevention
    // shield badge on a permanent is hovered (null when the hover ends).
    this.onShieldHover = callbacks.onShieldHover || null;
    this.hoveredShieldKey = null;
    // Fires with the chosen mana symbol ("G") when the player clicks a wedge of
    // the mana fan, or with no args when they click away to dismiss it.
    this.onManaFanPick = callbacks.onManaFanPick || null;
    this.onManaFanCancel = callbacks.onManaFanCancel || null;
    // Fires with {seat, idx, side} when a Raging River Left/Right button drawn
    // above a creature is clicked.
    this.onRiverPileClick = callbacks.onRiverPileClick || null;

    // Raging River left/right division state pushed from the app each render:
    // { active, defenderSeat, attackerSeat, defenderPiles, attackerPiles,
    //   defenderLocked, attackerLocked, prompt }. `prompt` (when set) is the
    //   viewer's own pending choice: { seat, role, items:[{idx,name}], selection }.
    this.river = null;
    // World-space rects of the currently drawn Left/Right buttons, for hit-testing.
    this._riverButtonRects = [];

    // Zone pile interaction: hover fires with {seat, kind, topCard, count} (or
    // null when the hover ends); click fires with {seat, kind}.
    this.onZonePileHover = callbacks.onZonePileHover || null;
    this.onZonePileClick = callbacks.onZonePileClick || null;

    // Fires with {seat, idx, pile} when a Camouflage pile button drawn above a
    // creature is clicked (`pile` is a 0-based pile number or "none").
    this.onCamouflagePileClick = callbacks.onCamouflagePileClick || null;
    // Camouflage division state pushed from the app each render:
    // { active, seat, pileCount, items:[{idx,name}], selection }.
    this.camouflage = null;
    // World-space rects of the currently drawn pile buttons, for hit-testing.
    this._camoButtonRects = [];

    // emblemItems: [{index, emblem, x, y, w, h}] — the viewer's own non-card
    // activated abilities granted until end of turn (Guardian Angel). Drawn as
    // card-like tokens with a glowing orange border to mark them as abilities.
    this.emblemItems = [];
    this.hoveredEmblemIndex = null;

    // Runtime state
    this.viewerSeat = 0;
    this.selectedKeys = new Set();
    this.attackingKeys = new Set();
    this.targetingKeys = new Set();
    this.combatArrows = [];
    // Attacking bands (CR 702.22): each entry is a list of {seat, idx} members
    // drawn connected by a purple link so the player can see the band grouping.
    this.combatBands = [];
    this.hoveredKey = null;
    // Floating stack-card interaction: index into stackVisuals (= serialized
    // stack index) currently hovered, and the index click-locked for priority
    // (set externally by app.js so the DOM stack list stays in sync).
    this.hoveredStackIndex = null;
    this.stackHeldIndex = null;
    // "Waiting for <name>" badge above the top stack card while another player
    // sits on priority (e.g. holding it by hovering the stack on their client).
    // {name, since} — drawn only after a short delay so the normal quick
    // priority hand-offs don't flicker the label.
    this.stackWaitingLabel = null;

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

  // Free-For-All: 3-4 player games render each seat's quadrant through its
  // own automatic camera, inside a clipped screen viewport.
  _isFfa() {
    return (this.currentState?.players?.length || 0) > 2;
  }

  // The camera for a seat: its per-seat FFA camera (a live object, eased by
  // _tick), or a snapshot of the single global camera in 2-player games.
  _camFor(seat) {
    if (!this._isFfa()) return { x: this.camX, y: this.camY, zoom: this.zoom };
    let cam = this.seatCams.get(seat);
    if (!cam) {
      cam = { x: 0, y: 0, zoom: 1, target: null, fresh: true };
      this.seatCams.set(seat, cam);
    }
    return cam;
  }

  // Run fn with the given camera loaded into the active registers
  // (camX/camY/zoom) — so all world<->canvas math and /zoom screen-constant
  // sizing inside sees that camera — then restore the previous registers.
  _withCam(cam, fn) {
    const px = this.camX;
    const py = this.camY;
    const pz = this.zoom;
    this.camX = cam.x;
    this.camY = cam.y;
    this.zoom = cam.zoom;
    try {
      return fn();
    } finally {
      this.camX = px;
      this.camY = py;
      this.zoom = pz;
    }
  }

  // Re-express a world point seen through fromCam as the world point that
  // renders at the same canvas position through toCam.
  _convertWorldPoint(x, y, fromCam, toCam) {
    return {
      x: (x * fromCam.zoom + fromCam.x - toCam.x) / toCam.zoom,
      y: (y * fromCam.zoom + fromCam.y - toCam.y) / toCam.zoom,
    };
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

  // Return the world-space render position of a card, accounting for stack
  // offset. A card is positioned relative to a stack only when it is a NON-base
  // member (index > 0); a card that is merely a stack base uses its own anchor.
  // The base position is resolved recursively so an aura attached to another
  // aura rides wherever that aura actually renders (e.g. fanned up behind the
  // creature it in turn enchants), not its bare layout slot.
  _renderPos(key) {
    const item = this.cardItems.find((c) => c.key === key);
    if (!item) return null;
    const stack = this.stacks.find((s) => s.keys.indexOf(key) > 0);
    if (!stack) return { x: item.x, y: item.y };
    const stackPos = stack.keys.indexOf(key);
    const basePos = this._renderPos(stack.keys[0]);
    if (!basePos) return { x: item.x, y: item.y };
    return { x: basePos.x + (stack.sideX || 0), y: basePos.y + stackPos * (stack.offsetY ?? BF_AURA_OFFSET_Y) };
  }

  // Same as _renderPos but using layout targets instead of animated positions.
  _targetRenderPos(key) {
    const item = this.cardItems.find((c) => c.key === key);
    if (!item) return null;
    const stack = this.stacks.find((s) => s.keys.indexOf(key) > 0);
    if (!stack) return { x: item.tx, y: item.ty };
    const stackPos = stack.keys.indexOf(key);
    const basePos = this._targetRenderPos(stack.keys[0]);
    if (!basePos) return { x: item.tx, y: item.ty };
    return { x: basePos.x + (stack.sideX || 0), y: basePos.y + stackPos * (stack.offsetY ?? BF_AURA_OFFSET_Y) };
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

  // regionSeat (FFA): only cards rendering in that seat's viewport are
  // candidates — the world point came through that viewport's camera, and a
  // zoomed-out neighbor camera could otherwise phantom-hit off-screen cards.
  _hitTest(wx, wy, regionSeat = null) {
    // Test from top of render order (last item = topmost visually).
    for (let i = this.cardItems.length - 1; i >= 0; i--) {
      const item = this.cardItems[i];
      if (regionSeat !== null && this._itemRegionSeat(item) !== regionSeat) continue;
      const b = this._cardBounds(item.key);
      if (!b) continue;
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) {
        return item;
      }
    }
    return null;
  }

  // Everything a mouse handler needs about a pointer position: canvas coords,
  // the FFA viewport under the pointer (null in 2-player games), the world
  // point through that viewport's camera, and the world point through the
  // stack overlay's camera (the viewer camera in FFA — stack visuals live
  // there).
  _pointerContext(clientX, clientY) {
    const { x: cx, y: cy } = this._pageToCanvas(clientX, clientY);
    if (!this._isFfa()) {
      const world = this.canvasToWorld(cx, cy);
      return { cx, cy, region: null, world, overlayWorld: world };
    }
    const region = this._regionForCanvasPoint(cx, cy);
    const world = this._withCam(this._camFor(region.seat), () => this.canvasToWorld(cx, cy));
    const overlayWorld = this._withCam(this._camFor(this.viewerSeat), () => this.canvasToWorld(cx, cy));
    return { cx, cy, region, world, overlayWorld };
  }

  // The pointer mapped into the open mana fan's camera space (the fan is
  // modal, so this must work even when the pointer is over another viewport).
  _manaFanWorldPoint(cx, cy) {
    if (!this._isFfa()) return this.canvasToWorld(cx, cy);
    const seat = this._manaFanRegionSeat() ?? this.viewerSeat;
    return this._withCam(this._camFor(seat), () => this.canvasToWorld(cx, cy));
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
    // Stack visuals live in the overlay camera's space (the viewer camera in
    // FFA), so the pointer is mapped through that camera.
    const world = this._isFfa()
      ? this._withCam(this._camFor(this.viewerSeat), () => this.canvasToWorld(cx, cy))
      : this.canvasToWorld(cx, cy);
    this._updateStackHover(world.x, world.y);
  }

  _sortRenderOrder() {
    const stackedKeys = new Set(this.stacks.flatMap((s) => s.keys));
    const free = this.cardItems.filter((c) => !stackedKeys.has(c.key));
    const stacked = [];
    // A card can belong to two stacks at once — an aura enchanting another aura
    // is both a member of its target's stack and the base of its own — so guard
    // against pushing it (and thus rendering it) twice. First push wins, which
    // keeps it behind whatever was drawn before it.
    const seen = new Set();
    for (const stack of this.stacks) {
      // Aura stacks keep the enchanted permanent at keys[0] and fan the auras
      // UPWARD (keys[last] sits highest on screen). Draw them top-down — the
      // topmost (highest) aura first so it sits BEHIND, then progressively
      // lower auras painted on top — so each lower card's top edge shows. The
      // enchanted permanent (keys[0], lowest) is drawn last, on top of all,
      // and never occluded. Regular piles keep their natural order.
      const drawKeys =
        stack.kind === "aura" && stack.keys.length > 1
          ? [...stack.keys].reverse()
          : stack.keys;
      for (const k of drawKeys) {
        if (seen.has(k)) continue;
        seen.add(k);
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
    this._layoutEmblems(state);
    this._syncAuraStacks(state, newKeys);

    // New arrivals appear directly at their assigned slot; existing cards
    // animate toward theirs only when the layout had to move them.
    for (const item of brandNew) {
      item.x = item.tx;
      item.y = item.ty;
    }

    // Zone piles sync BEFORE the stack zone so resolve/fizzle animations
    // spawned there can aim at the freshly positioned graveyard pile.
    this._syncZonePiles(state);

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

  // ---------------------------------------------------------------------------
  // Free-For-All quadrant layout
  // ---------------------------------------------------------------------------

  // Where a seat's permanents live: which way its bands grow (down from the
  // split line, or up), and which half of the X axis they're offset into.
  // For 2-or-fewer players this MUST reproduce the original behavior exactly
  // (full-width bottom half for the viewer growing down, full-width top half
  // for the other seat growing up) — every call site below is written so the
  // n<=2 branch is a byte-for-byte no-op versus the pre-FFA code.
  _quadrantFor(seatIdx) {
    const n = this.currentState?.players?.length || 0;
    if (n <= 2) {
      const isViewer = seatIdx === this.viewerSeat;
      return {
        xMin: -Infinity,
        xMax: Infinity,
        yMin: isViewer ? BF_WORLD_SPLIT_Y : -Infinity,
        yMax: isViewer ? Infinity : BF_WORLD_SPLIT_Y,
        growDirection: isViewer ? "down" : "up",
        xOffset: 0,
      };
    }
    // Rotation order relative to the viewer. 3 players: the viewer's field
    // spans the ENTIRE bottom half while the two opponents split the top half
    // into left (r=1) and right (r=2) quadrants. 4 players: 0 = viewer
    // (bottom-left), 1 = bottom-right, 2 = top-left, 3 = top-right.
    const r = (((seatIdx - this.viewerSeat) % n) + n) % n;
    if (n === 3) {
      if (r === 0) {
        return {
          xMin: -Infinity,
          xMax: Infinity,
          yMin: BF_WORLD_SPLIT_Y,
          yMax: Infinity,
          growDirection: "down",
          xOffset: 0,
        };
      }
      const isLeft3 = r === 1;
      return {
        xMin: isLeft3 ? -Infinity : BF_QUADRANT_BOUNDARY_X,
        xMax: isLeft3 ? BF_QUADRANT_BOUNDARY_X : Infinity,
        yMin: -Infinity,
        yMax: BF_WORLD_SPLIT_Y,
        growDirection: "up",
        xOffset: isLeft3 ? 0 : BF_QUADRANT_SHIFT_X,
      };
    }
    const isLeft = r === 0 || r === 2;
    const isBottom = r === 0 || r === 1;
    return {
      xMin: isLeft ? -Infinity : BF_QUADRANT_BOUNDARY_X,
      xMax: isLeft ? BF_QUADRANT_BOUNDARY_X : Infinity,
      yMin: isBottom ? BF_WORLD_SPLIT_Y : -Infinity,
      yMax: isBottom ? Infinity : BF_WORLD_SPLIT_Y,
      growDirection: isBottom ? "down" : "up",
      xOffset: isLeft ? 0 : BF_QUADRANT_SHIFT_X,
    };
  }

  // Reverse lookup: which seat owns the quadrant containing a given world
  // point. Used to resolve blocker/attacker/cast drag-drops onto a seat.
  // Mirrors _quadrantFor's n<=2 no-op guarantee exactly.
  _seatForWorldPoint(x, y) {
    const n = this.currentState?.players?.length || 0;
    if (n <= 2) {
      return y < BF_WORLD_SPLIT_Y ? (1 - this.viewerSeat) : this.viewerSeat;
    }
    const isBottom = y >= BF_WORLD_SPLIT_Y;
    const isLeft = x < BF_QUADRANT_BOUNDARY_X;
    if (n === 3) {
      // Bottom half is all the viewer's; the top half splits left/right.
      if (isBottom) return this.viewerSeat;
      return (this.viewerSeat + (isLeft ? 1 : 2)) % n;
    }
    const r = (isBottom ? 0 : 2) + (isLeft ? 0 : 1);
    if (r >= n) return null;
    return (this.viewerSeat + r) % n;
  }

  // The seat shown by the classic single-opponent DOM header (#oppName /
  // #oppLife / #oppHand): the only opponent in 2-player games, otherwise the
  // seat whose quadrant is top-LEFT (r=1 with 3 players, r=2 with 4). Must
  // stay in lockstep with app.js's classicOppSeat().
  _classicOppSeat() {
    const n = this.currentState?.players?.length || 0;
    if (n <= 2) return 1 - this.viewerSeat;
    return (this.viewerSeat + (n === 3 ? 1 : 2)) % n;
  }

  // A representative point inside a seat's quadrant, used as a fallback aim
  // target for animations when no more specific anchor (hand fan DOM rect,
  // zone pile, etc.) is available.
  _quadrantAnchor(seatIdx) {
    const q = this._quadrantFor(seatIdx);
    return {
      x: q.xOffset + BF_SLOT_PITCH_X * 2,
      y: BF_WORLD_SPLIT_Y + (q.growDirection === "down" ? 520 : -520),
    };
  }

  // ---------------------------------------------------------------------------
  // Free-For-All screen viewports (one clipped region + camera per seat)
  // ---------------------------------------------------------------------------

  // The visible (non-overscan) part of the canvas, in canvas coordinates.
  _stageCanvasRect() {
    return {
      x: ((this.cssW || 0) * (1 - 1 / BF_OVERSCAN_X)) / 2,
      y: ((this.cssH || 0) * (1 - 1 / BF_OVERSCAN_Y)) / 2,
      w: (this.cssW || 0) / BF_OVERSCAN_X,
      h: (this.cssH || 0) / BF_OVERSCAN_Y,
    };
  }

  // Screen viewports for a 3-4 player game, in canvas coordinates. Outer
  // edges extend into the overscan so clipping never shows a seam at the
  // stage border; the inner edges are the shared separator lines (recorded in
  // _sepSplitY/_sepBoundX for the divider drawing). 3 players: the viewer
  // spans the whole bottom half and the two opponents split the top half.
  _regions() {
    const n = this.currentState?.players?.length || 0;
    const stage = this._stageCanvasRect();
    const splitY = stage.y + stage.h / 2;
    const boundX = stage.x + stage.w / 2;
    const W = this.cssW || 0;
    const H = this.cssH || 0;
    this._sepSplitY = splitY;
    this._sepBoundX = boundX;
    const v = this.viewerSeat;
    if (n === 3) {
      return [
        { seat: v, x: 0, y: splitY, w: W, h: H - splitY },
        { seat: (v + 1) % n, x: 0, y: 0, w: boundX, h: splitY },
        { seat: (v + 2) % n, x: boundX, y: 0, w: W - boundX, h: splitY },
      ];
    }
    return [
      { seat: v, x: 0, y: splitY, w: boundX, h: H - splitY },
      { seat: (v + 1) % n, x: boundX, y: splitY, w: W - boundX, h: H - splitY },
      { seat: (v + 2) % n, x: 0, y: 0, w: boundX, h: splitY },
      { seat: (v + 3) % n, x: boundX, y: 0, w: W - boundX, h: splitY },
    ];
  }

  _regionForSeat(seat) {
    return this._regions().find((r) => r.seat === seat) || null;
  }

  _regionForCanvasPoint(cx, cy) {
    const regions = this._regions();
    for (const r of regions) {
      if (cx >= r.x && cx < r.x + r.w && cy >= r.y && cy < r.y + r.h) return r;
    }
    return regions[0];
  }

  // A seat's viewport, trimmed to the visible stage, expressed in that seat's
  // camera world space — the FFA counterpart of _visibleWorldRect for
  // screen-pinned content (zone piles, player beam endpoints).
  _regionWorldRect(seat) {
    const region = this._regionForSeat(seat);
    if (!region) return this._visibleWorldRect();
    const stage = this._stageCanvasRect();
    const x0 = Math.max(region.x, stage.x);
    const y0 = Math.max(region.y, stage.y);
    const x1 = Math.min(region.x + region.w, stage.x + stage.w);
    const y1 = Math.min(region.y + region.h, stage.y + stage.h);
    return this._withCam(this._camFor(seat), () => {
      const tl = this.canvasToWorld(x0, y0);
      const br = this.canvasToWorld(x1, y1);
      return { minX: tl.x, minY: tl.y, maxX: br.x, maxY: br.y };
    });
  }

  // Which seat's viewport a card renders in: the quadrant owning its render
  // position. Usually the card's controller, but e.g. an aura enchanting
  // another seat's permanent rides into that seat's quadrant. useTarget picks
  // the layout target instead of the animated position (for camera fitting).
  _itemRegionSeat(item, useTarget = false) {
    const pos =
      (useTarget ? this._targetRenderPos(item.key) : this._renderPos(item.key)) ||
      { x: item.tx, y: item.ty };
    return this._seatForWorldPoint(pos.x + BF_CARD_W / 2, pos.y + BF_CARD_H / 2);
  }

  // Recompute every card's layout target and rebuild identity piles.
  _layoutBoard(state) {
    const players = Array.isArray(state.players) ? state.players : [];
    const itemByKey = new Map(this.cardItems.map((c) => [c.key, c]));

    // Attached auras ride their target; their targets keep a dedicated slot.
    const attachedKeys = new Set();
    const auraCounts = new Map(); // targetKey -> number of attachments
    const attachedTo = new Map(); // childKey -> targetKey
    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const bf = Array.isArray(players[seatIdx]?.battlefield) ? players[seatIdx].battlefield : [];
      for (let idx = 0; idx < bf.length; idx++) {
        const card = bf[idx];
        if (!card || card.attached_to_index == null) continue;
        const targetKey = `${card.attached_to_seat ?? seatIdx}-${card.attached_to_index}`;
        attachedKeys.add(`${seatIdx}-${idx}`);
        attachedTo.set(`${seatIdx}-${idx}`, targetKey);
        auraCounts.set(targetKey, (auraCounts.get(targetKey) || 0) + 1);
      }
    }

    // An aura attached to another enchantment is drawn off to the right (see
    // _syncAuraStacks). That overhang belongs to whatever permanent actually
    // occupies a slot — walk each side-attach target up its attachment chain to
    // the root permanent so the root's slot can reserve the extra width.
    const needsSideWidth = new Set();
    for (const targetKey of auraCounts.keys()) {
      if (!this._isAuraSideTarget(itemByKey.get(targetKey)?.card)) continue;
      let root = targetKey;
      while (attachedTo.has(root)) root = attachedTo.get(root);
      needsSideWidth.add(root);
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
      // Horizontal footprint of a slot: one pitch, plus the side-aura overhang
      // for any slot that carries a right-set aura so neighbours don't collide.
      const slotWidth = (g) =>
        g.keys.length === 1 && needsSideWidth.has(g.keys[0])
          ? BF_AURA_SIDE_X + BF_SLOT_PITCH_X
          : BF_SLOT_PITCH_X;
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
      //      opponent bands grow upward, front band nearest the split. In a
      //      3-4 player (Free-For-All) game, each seat additionally gets its
      //      own X quadrant (_quadrantFor) so seats don't pile on top of each
      //      other; for 2-or-fewer players growDirection/xOffset reproduce
      //      the original isViewer-based placement exactly. ----
      const quadrant = this._quadrantFor(seatIdx);
      const growsDown = quadrant.growDirection === "down";
      let cursor = growsDown ? BF_WORLD_SPLIT_Y + BF_SPLIT_GAP : BF_WORLD_SPLIT_Y - BF_SPLIT_GAP;
      for (const band of bands) {
        if (!band.rows.length) continue;
        let rowTop = growsDown ? cursor : cursor - band.height;
        for (const { row, h } of band.rows) {
          let gx = quadrant.xOffset;
          for (const g of row) {
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
            gx += slotWidth(g);
          }
          rowTop += h + BF_ROW_GAP;
        }
        cursor = growsDown ? cursor + band.height + BF_BAND_GAP : cursor - band.height - BF_BAND_GAP;
      }
    }

    // (3-4 players: no cross-seat alignment is needed here — each seat's
    // viewport camera frames its own quadrant independently.)

    this.stacks = piles;
  }

  // Lay out the viewer's emblem tokens just to the LEFT of their battlefield,
  // along the front band row, so they sit near (but never collide with) the
  // viewer's permanents. Only the viewer's own emblems are shown/clickable.
  _layoutEmblems(state) {
    const players = Array.isArray(state.players) ? state.players : [];
    const me = players[this.viewerSeat];
    const emblems = Array.isArray(me?.emblems) ? me.emblems : [];
    const rowTop = BF_WORLD_SPLIT_Y + BF_SPLIT_GAP;
    this.emblemItems = emblems.map((emblem, i) => ({
      index: i,
      emblem,
      x: -(i + 1) * BF_SLOT_PITCH_X,
      y: rowTop,
      w: BF_CARD_W,
      h: BF_CARD_H,
    }));
  }

  _emblemBounds(item) {
    return { x: item.x, y: item.y, w: item.w, h: item.h };
  }

  _hitTestEmblem(wx, wy) {
    for (let i = this.emblemItems.length - 1; i >= 0; i--) {
      const item = this.emblemItems[i];
      const b = this._emblemBounds(item);
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) return item;
    }
    return null;
  }

  // Hover hit-test for the damage-prevention shield badge drawn at a permanent's
  // top-left corner. Returns the granting card's preview payload so app.js can
  // show it, mirroring the source-card hover on emblems. Only cards that recorded
  // a `shield_source` participate, so cardless shields don't swallow card hover.
  _hitTestShield(wx, wy, regionSeat = null) {
    for (let i = this.cardItems.length - 1; i >= 0; i--) {
      const item = this.cardItems[i];
      const card = item.card;
      if (!card || !(Number(card.damage_prevention_pool) > 0) || !card.shield_source) continue;
      if (regionSeat !== null && this._itemRegionSeat(item) !== regionSeat) continue;
      const b = this._cardBounds(item.key);
      if (!b) continue;
      // The badge hugs the card's top-left corner (see _drawShieldBadge).
      if (wx >= b.x && wx <= b.x + SHIELD_BADGE_HIT && wy >= b.y && wy <= b.y + SHIELD_BADGE_HIT) {
        return { key: item.key, source: card.shield_source };
      }
    }
    return null;
  }

  // A small heater-shield glyph with the prevention value centered inside.
  _drawShieldBadge(ctx, sx, sy, value) {
    const sw = 18, sh = 20;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + sw, sy);
    ctx.lineTo(sx + sw, sy + sh * 0.5);
    ctx.quadraticCurveTo(sx + sw, sy + sh * 0.92, sx + sw / 2, sy + sh);
    ctx.quadraticCurveTo(sx, sy + sh * 0.92, sx, sy + sh * 0.5);
    ctx.closePath();
    ctx.fillStyle = "rgba(56,118,224,0.94)";
    ctx.fill();
    ctx.strokeStyle = "rgba(214,232,255,0.96)";
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.fillStyle = "#ffffff";
    ctx.font = `bold ${Math.max(9, sh * 0.5)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(value), sx + sw / 2, sy + sh * 0.46);
    ctx.restore();
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
          // An aura on another enchantment is set directly to the right of its
          // target (level with it, no vertical drop) and joined by a curved
          // arrow; an aura on anything else gets the usual upward fan (negative
          // offset) so it sticks out the top of the enchanted permanent.
          const targetItem = this.cardItems.find((c) => c.key === targetKey);
          const side = this._isAuraSideTarget(targetItem?.card);
          stack = {
            id: `aura-${targetKey}`,
            keys: [targetKey],
            offsetY: side ? 0 : -BF_AURA_OFFSET_Y,
            sideX: side ? BF_AURA_SIDE_X : 0,
            kind: "aura",
          };
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

  // An aura is drawn beside (rather than over) its target when that target is
  // itself an enchantment with no body to peek out from under a covering card.
  // An enchantment *creature* keeps the normal upward fan — its P/T still shows
  // through, exactly like any other enchanted creature.
  _isAuraSideTarget(card) {
    const t = String(card?.type || "").toLowerCase();
    return t.includes("enchantment") && !t.includes("creature");
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
        const from = this._castOriginOverlay(stackData[i]);
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
  // and is drawn on top. In FFA the cascade lives in the viewer camera's
  // "overlay" space and is drawn unclipped above every viewport.
  _retargetStackVisuals() {
    if (this._isFfa()) {
      this._withCam(this._camFor(this.viewerSeat), () => this._retargetStackVisualsActive());
      return;
    }
    this._retargetStackVisualsActive();
  }

  _retargetStackVisualsActive() {
    const n = this.stackVisuals.length;
    if (!n) return;
    const rect = this._visibleWorldRect();
    const sc = BF_STACK_SCALE / this.zoom;
    const w = BF_CARD_W * sc;
    const offX = BF_STACK_OFFSET_X / this.zoom;
    const offY = BF_STACK_OFFSET_Y / this.zoom;
    // Extra right margin keeps the cascade clear of the DOM mana column
    // overlaying the right edge of the stage.
    const margin = (30 + BF_ZONE_RIGHT_INSET_PX) / this.zoom;
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

  // ---------------------------------------------------------------------------
  // Zone piles (library / graveyard / exile)
  // ---------------------------------------------------------------------------

  // Rebuild the pile list from the serialized state. Library always shows
  // while cards remain; graveyard/exile only once they hold a card. Only the
  // top card of graveyard/exile is shown.
  _syncZonePiles(state) {
    const players = Array.isArray(state?.players) ? state.players : [];
    const piles = [];
    for (let seatIdx = 0; seatIdx < players.length; seatIdx++) {
      const p = players[seatIdx] || {};
      const grave = Array.isArray(p.graveyard) ? p.graveyard : [];
      const exile = Array.isArray(p.exile) ? p.exile : [];
      const libraryCount = p.library_count ?? 0;
      if (libraryCount > 0) {
        piles.push({ seat: seatIdx, kind: "library", count: libraryCount, topCard: null, cx: 0, cy: 0, w: 0, h: 0 });
      }
      if (grave.length > 0) {
        piles.push({ seat: seatIdx, kind: "graveyard", count: grave.length, topCard: grave[grave.length - 1], cx: 0, cy: 0, w: 0, h: 0 });
      }
      if (exile.length > 0) {
        piles.push({ seat: seatIdx, kind: "exile", count: exile.length, topCard: exile[exile.length - 1], cx: 0, cy: 0, w: 0, h: 0 });
      }
    }
    this.zonePiles = piles;
    if (this.hoveredZonePile && !piles.some((p) => p.seat === this.hoveredZonePile.seat && p.kind === this.hoveredZonePile.kind)) {
      this.hoveredZonePile = null;
      if (this.onZonePileHover) this.onZonePileHover(null);
    }
    this._retargetZonePiles();
  }

  // Pin each seat's piles inside its own viewport: bottom-half seats grow
  // their column up from the viewport's bottom edge, top-half seats down from
  // its top, and every column hugs the viewport's LEFT edge (the stage edge,
  // or the vertical separator for right-half seats). For 2-player games this
  // reproduces the classic viewer-bottom-left / opponent-top-left columns
  // exactly. Re-run every tick (like the stack cascade) so camera motion
  // never strands them. In FFA each pile is positioned through its seat's own
  // camera, so the piles ride that quadrant's independent pan/zoom. The
  // horizontal anchor is computed in PAGE space and projected onto the tilted
  // plane per pile: the perspective tilt spreads the bottom of the plane
  // outward, so a flat-canvas inset would drift near the viewer's edge and
  // slide under the DOM phase rail.
  _retargetZonePiles() {
    if (!this.zonePiles.length) return;
    const n = this.currentState?.players?.length || 0;
    const stage = this.canvas.parentElement?.getBoundingClientRect();
    const order = { library: 0, graveyard: 1, exile: 2 };
    const slots = new Map(); // seat -> next slot index
    for (const pile of this.zonePiles.slice().sort((a, b) => order[a.kind] - order[b.kind])) {
      const slot = slots.get(pile.seat) || 0;
      slots.set(pile.seat, slot + 1);
      this._withCam(this._camFor(pile.seat), () => {
        const isBottom = this._quadrantFor(pile.seat).growDirection === "down";
        const rect = n > 2 ? this._regionWorldRect(pile.seat) : this._visibleWorldRect();
        const region = n > 2 ? this._regionForSeat(pile.seat) : null;
        const w = (BF_CARD_W * BF_ZONE_PILE_SCALE) / this.zoom;
        const h = (BF_CARD_H * BF_ZONE_PILE_SCALE) / this.zoom;
        const gap = BF_ZONE_PILE_GAP_PX / this.zoom;
        pile.w = w;
        pile.h = h;
        let topInsetPx = BF_ZONE_TOP_INSET_PX;
        let bottomInsetPx = BF_ZONE_BOTTOM_INSET_PX;
        if (n > 2) {
          if (!isBottom) topInsetPx = BF_ZONE_TOP_INSET_FFA_PX;
          else if (pile.seat !== this.viewerSeat) bottomInsetPx = BF_ZONE_TOP_INSET_FFA_PX;
          else if (n >= 4) bottomInsetPx = BF_ZONE_BOTTOM_INSET_FFA4_PX;
        }
        pile.cy = isBottom
          ? rect.maxY - bottomInsetPx / this.zoom - h / 2 - slot * (h + gap)
          : rect.minY + topInsetPx / this.zoom + h / 2 + slot * (h + gap);
        const stageCanvas = this._stageCanvasRect();
        const atStageLeft = !region || region.x <= stageCanvas.x;
        const insetPx = atStageLeft ? BF_ZONE_LEFT_INSET_PX : BF_ZONE_INNER_LEFT_INSET_PX;
        if (stage && stage.width > 0) {
          // Project the pile's row back to page space, then find the world x
          // whose page x sits exactly at the inset from the viewport's edge.
          const rowCanvasY = this.worldToCanvas(0, pile.cy).y;
          const rowPageY = this._canvasToPage(0, rowCanvasY).y;
          const leftPageX = atStageLeft
            ? stage.left
            : this._canvasToPage(Math.max(region.x, stageCanvas.x), rowCanvasY).x;
          const edge = this._pageToCanvas(leftPageX + insetPx, rowPageY);
          pile.cx = this.canvasToWorld(edge.x, edge.y).x + w / 2;
        } else {
          pile.cx = rect.minX + insetPx / this.zoom + w / 2;
        }
      });
    }
  }

  // seatFilter (FFA): only piles of the viewport under the pointer are
  // candidates — pile coordinates only mean anything through their own
  // seat's camera.
  _hitTestZonePile(wx, wy, seatFilter = null) {
    for (const pile of this.zonePiles) {
      if (seatFilter !== null && pile.seat !== seatFilter) continue;
      if (
        wx >= pile.cx - pile.w / 2 && wx <= pile.cx + pile.w / 2 &&
        wy >= pile.cy - pile.h / 2 && wy <= pile.cy + pile.h / 2
      ) {
        return pile;
      }
    }
    return null;
  }

  // Client (page) coordinates of a zone pile's center — lets app.js aim DOM
  // fly-to-graveyard animations at the actual canvas pile.
  getZonePileClientPoint(seat, kind) {
    const pile = this.zonePiles.find((p) => p.seat === seat && p.kind === kind);
    if (!pile) return null;
    const c = this._withCam(this._camFor(seat), () => this.worldToCanvas(pile.cx, pile.cy));
    return this._canvasToPage(c.x, c.y);
  }

  // True while any canvas hover source (card, stack card, emblem, shield
  // badge, zone pile) is active — app.js gates preview-hide on this so a
  // hover handoff between sources never flickers the preview away.
  hasAnyHover() {
    return !!(
      this.hoveredKey ||
      this.hoveredStackIndex != null ||
      this.hoveredEmblemIndex != null ||
      this.hoveredShieldKey ||
      this.hoveredZonePile
    );
  }

  _drawZonePiles(ctx, seatFilter = null) {
    if (!this.zonePiles.length) return;
    const now = performance.now();
    const labels = { library: "DECK", graveyard: "GRAVE", exile: "EXILE" };
    for (const pile of this.zonePiles) {
      if (seatFilter !== null && pile.seat !== seatFilter) continue;
      const x = pile.cx - pile.w / 2;
      const y = pile.cy - pile.h / 2;
      const hovered =
        this.hoveredZonePile &&
        this.hoveredZonePile.seat === pile.seat &&
        this.hoveredZonePile.kind === pile.kind;

      ctx.save();

      // Pile illusion: a couple of offset sheets behind the top card.
      const layers = Math.min(2, Math.max(0, pile.count - 1));
      for (let i = layers; i >= 1; i--) {
        const off = (i * 3) / this.zoom;
        ctx.fillStyle = "rgba(10, 16, 26, 0.9)";
        this._roundRect(ctx, x + off, y + off, pile.w, pile.h, 6 / this.zoom);
        ctx.fill();
        ctx.strokeStyle = "rgba(126, 196, 255, 0.25)";
        ctx.lineWidth = 1 / this.zoom;
        ctx.stroke();
      }

      if (pile.kind === "library") {
        // Face-down: the card back fills a rounded frame.
        const img = this._loadImage(BF_CARD_BACK_URL) || this.imageCache.get(BF_CARD_BACK_URL);
        this._roundRect(ctx, x, y, pile.w, pile.h, 6 / this.zoom);
        ctx.fillStyle = "#1a1a2e";
        ctx.fill();
        if (img) {
          ctx.save();
          this._roundRect(ctx, x, y, pile.w, pile.h, 6 / this.zoom);
          ctx.clip();
          ctx.drawImage(img, x, y, pile.w, pile.h);
          ctx.restore();
        }
        ctx.strokeStyle = hovered ? "rgba(126, 196, 255, 0.9)" : "rgba(126, 196, 255, 0.35)";
        ctx.lineWidth = (hovered ? 2 : 1) / this.zoom;
        this._roundRect(ctx, x, y, pile.w, pile.h, 6 / this.zoom);
        ctx.stroke();
      } else {
        this._drawCardFace(ctx, x, y, pile.w, pile.h, pile.topCard, { hovered: !!hovered });
      }

      // Gold pulse while a spell is choosing a target in this zone.
      const targeting =
        this.zonePileTargeting &&
        this.zonePileTargeting.kind === pile.kind &&
        (this.zonePileTargeting.seats || []).includes(pile.seat);
      if (targeting) {
        const pulse = 0.55 + 0.45 * Math.sin(now / 300);
        ctx.strokeStyle = `rgba(255, 215, 106, ${0.5 + 0.5 * pulse})`;
        ctx.lineWidth = 3 / this.zoom;
        ctx.shadowColor = "#ffd76a";
        ctx.shadowBlur = (10 + 8 * pulse) / this.zoom;
        this._roundRect(ctx, x - 2 / this.zoom, y - 2 / this.zoom, pile.w + 4 / this.zoom, pile.h + 4 / this.zoom, 7 / this.zoom);
        ctx.stroke();
        ctx.shadowBlur = 0;
      }

      // Count badge, top-right of the pile.
      const label = `×${pile.count}`;
      ctx.font = `bold ${11 / this.zoom}px sans-serif`;
      const bw = ctx.measureText(label).width + 8 / this.zoom;
      const bh = 15 / this.zoom;
      ctx.fillStyle = "rgba(0,0,0,0.78)";
      this._roundRect(ctx, x + pile.w - bw - 2 / this.zoom, y + 2 / this.zoom, bw, bh, 3 / this.zoom);
      ctx.fill();
      ctx.fillStyle = "#ffd76a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, x + pile.w - 2 / this.zoom - bw / 2, y + 2 / this.zoom + bh / 2);

      // Zone label under the pile.
      ctx.fillStyle = hovered ? "rgba(190,215,240,0.75)" : "rgba(190,215,240,0.35)";
      ctx.font = `600 ${11 / this.zoom}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(labels[pile.kind] || "", pile.cx, y + pile.h + 4 / this.zoom);

      ctx.restore();
    }
  }

  // World-space point a newly cast stack item flies in from. Hand/graveyard
  // anchors live outside the canvas, so the projected point is clamped to the
  // visible battlefield — the card enters from the matching table edge
  // instead of teleporting in from off screen.
  _castOrigin(item) {
    if (item?.type === "ability" && item.source_permanent_seat != null && item.source_permanent_index != null) {
      const pos = this._renderPos(`${item.source_permanent_seat}-${item.source_permanent_index}`);
      if (pos) {
        let p = { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2 };
        if (this._isFfa()) {
          // The permanent renders through its own quadrant's camera;
          // re-express its position in the ACTIVE camera's space so the
          // ability card visually pops out of the permanent.
          const srcSeat = this._seatForWorldPoint(p.x, p.y);
          p = this._convertWorldPoint(p.x, p.y, this._camFor(srcSeat), {
            x: this.camX, y: this.camY, zoom: this.zoom,
          });
        }
        return { x: p.x, y: p.y, scale: 1.0 };
      }
    }
    const casterSeat = item?.caster_index;
    const fromViewer = casterSeat === this.viewerSeat;
    const n = this.currentState?.players?.length || 0;
    // Every seat has a DOM hand fan: #selfHand for the viewer, #oppHand for
    // the classic (top-left) opponent, and per-seat #ffaHand_<seat> fans for
    // the remaining Free-For-All opponents (see app.js's
    // renderFfaOpponentPanels). Missing elements fall through to the
    // quadrant-based fallback.
    let el = null;
    if (fromViewer) {
      el = document.getElementById("selfHand");
    } else if (n <= 2 || casterSeat === this._classicOppSeat()) {
      el = document.getElementById("oppHand");
    } else if (Number.isInteger(casterSeat)) {
      el = document.getElementById(`ffaHand_${casterSeat}`);
    }
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 || r.height > 0) {
        const c = this._pageToCanvas(r.left + r.width / 2, r.top + r.height / 2);
        const w = this.canvasToWorld(c.x, c.y);
        const p = this._clampToBattlefield(w.x, w.y);
        return { x: p.x, y: p.y, scale: 0.55 / this.zoom };
      }
    }
    const fallbackPoint = n <= 2
      ? { x: this._stackBaseX, y: BF_WORLD_SPLIT_Y + (fromViewer ? 520 : -520) }
      : this._quadrantAnchor(Number.isInteger(casterSeat) ? casterSeat : this.viewerSeat);
    const fallback = this._clampToBattlefield(fallbackPoint.x, fallbackPoint.y);
    return { x: fallback.x, y: fallback.y, scale: 0.55 / this.zoom };
  }

  // Cast origin expressed in the stack overlay's camera space: the viewer's
  // viewport camera in FFA, the (already-active) global camera otherwise.
  _castOriginOverlay(item) {
    if (!this._isFfa()) return this._castOrigin(item);
    return this._withCam(this._camFor(this.viewerSeat), () => this._castOrigin(item));
  }

  // World-space point a resolved non-permanent shrinks away toward, clamped
  // so the fizzle heads in the graveyard's direction without leaving the
  // battlefield. Coordinates are in the ACTIVE camera's space — in FFA call
  // this under the caster seat's camera, whose space the piles live in.
  _graveAnchor(casterSeat) {
    // Aim at the caster's on-canvas graveyard pile (or their library pile
    // while the graveyard is still empty — same column, one slot over).
    const pile =
      this.zonePiles.find((p) => p.seat === casterSeat && p.kind === "graveyard") ||
      this.zonePiles.find((p) => p.seat === casterSeat && p.kind === "library");
    if (pile) return this._clampToBattlefield(pile.cx, pile.cy);
    // No piles yet: head toward the left edge of the caster's half.
    const growsDown = this._quadrantFor(casterSeat).growDirection === "down";
    const rect = this._visibleWorldRect();
    return this._clampToBattlefield(rect.minX, BF_WORLD_SPLIT_Y + (growsDown ? 420 : -420));
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

    // In FFA the stack cascade lives in the viewer camera's overlay space
    // while battlefield slots and graveyard piles live in some seat camera's
    // space. Each fx plays entirely in ONE space (fx.camSeat tags which; null
    // means overlay/global), so the departing stack coordinates are
    // re-expressed in the destination space up front. endStages receives the
    // converted stack-slot position/scale and produces the remaining stages.
    const spawn = (camSeat, endStages, extra = {}) => {
      const overlayCam = this._isFfa() ? this._camFor(this.viewerSeat) : null;
      const cam = overlayCam && camSeat !== null ? this._camFor(camSeat) : overlayCam;
      const cv = (x, y, s) => {
        if (!overlayCam || cam === overlayCam) return { x, y, s };
        const p = this._convertWorldPoint(x, y, overlayCam, cam);
        return { x: p.x, y: p.y, s: (s * overlayCam.zoom) / cam.zoom };
      };
      const start = cv(v.cx, v.cy, v.scale);
      const slot = cv(v.tcx, v.tcy, v.tScale);
      const hold = dwell > 16
        ? [{ x0: start.x, y0: start.y, s0: start.s, a0: 1, x1: slot.x, y1: slot.y, s1: slot.s, a1: 1, dur: dwell, ease: _easeOutCubic }]
        : [];
      const sx = hold.length ? slot.x : start.x;
      const sy = hold.length ? slot.y : start.y;
      const ss = hold.length ? slot.s : start.s;
      this.fxAnims.push({
        type: "card", card, camSeat, stageIdx: 0, stageStart: null,
        x: start.x, y: start.y, scale: start.s, alpha: 1,
        stages: [...hold, ...endStages(sx, sy, ss)],
        ...extra,
      });
    };

    if (isPermanentSpell) {
      const landed = (brandNew || []).find(
        (bi) => !bi._fxClaimed && bi.seat === item.caster_index && bi.card?.name === card?.name
      );
      if (landed) {
        landed._fxClaimed = true;
        const pos = this._targetRenderPos(landed.key) || { x: landed.tx, y: landed.ty };
        const slot = { x: pos.x + BF_CARD_W / 2, y: pos.y + BF_CARD_H / 2 };
        const hover = { x: slot.x, y: slot.y - BF_RESOLVE_HOVER_LIFT };
        const camSeat = this._isFfa() ? this._seatForWorldPoint(slot.x, slot.y) : null;
        this.suppressedKeys.add(landed.key);
        spawn(camSeat, (sx, sy, ss) => [
          { x0: sx, y0: sy, s0: ss, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_FLY_MS, ease: _easeOutCubic, lifted: true },
          { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: hover.x, y1: hover.y, s1: 1.12, a1: 1, dur: BF_RESOLVE_HOVER_MS, ease: null, lifted: true },
          { x0: hover.x, y0: hover.y, s0: 1.12, a0: 1, x1: slot.x, y1: slot.y, s1: 1, a1: 1, dur: BF_RESOLVE_SLAM_MS, ease: _easeInQuad },
        ], { suppressKey: landed.key, impactAt: slot });
        return;
      }
    }

    if (isSpell) {
      const casterSeat = item.caster_index ?? 0;
      const camSeat = this._isFfa() ? casterSeat : null;
      const g = camSeat !== null
        ? this._withCam(this._camFor(camSeat), () => this._graveAnchor(casterSeat))
        : this._graveAnchor(casterSeat);
      spawn(camSeat, (sx, sy, ss) => [
        { x0: sx, y0: sy, s0: ss, a0: 1, x1: g.x, y1: g.y, s1: 0.2, a1: 0, dur: BF_FIZZLE_MS, ease: _easeInCubic },
      ]);
      return;
    }

    spawn(null, (sx, sy, ss) => [
      { x0: sx, y0: sy, s0: ss, a0: 1, x1: sx, y1: sy, s1: ss * 0.6, a1: 0, dur: BF_ABILITY_FADE_MS, ease: null },
    ]);
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
      // In FFA the whole entrance plays in the destination quadrant's camera
      // space, so the hand origin is computed through that camera too.
      const camSeat = this._isFfa() ? this._seatForWorldPoint(slot.x, slot.y) : null;
      const from = camSeat !== null
        ? this._withCam(this._camFor(camSeat), () => this._castOrigin({ caster_index: item.seat }))
        : this._castOrigin({ caster_index: item.seat });
      this.suppressedKeys.add(item.key);
      this.fxAnims.push({
        type: "card", card: item.card, camSeat, suppressKey: item.key, impactAt: slot,
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
      // view edge rather than be left out of frame. The clamp runs through
      // the fx's own camera space.
      const p = this._fxClampPoint(fx, _lerp(stage.x0, stage.x1, e), _lerp(stage.y0, stage.y1, e));
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
        this.fxAnims.push({ type: "ring", camSeat: fx.camSeat ?? null, x: fx.impactAt.x, y: fx.impactAt.y, dur: BF_IMPACT_RING_MS, start: null, t: 0 });
      }
    }
    return true;
  }

  // Clamp an fx position to the battlefield through the fx's own camera: its
  // camSeat viewport camera in FFA (the viewer overlay camera for stack-space
  // fx), the single global camera otherwise.
  _fxClampPoint(fx, x, y) {
    if (!this._isFfa()) return this._clampToBattlefield(x, y);
    const cam = this._camFor(fx.camSeat ?? this.viewerSeat);
    return this._withCam(cam, () => this._clampToBattlefield(x, y));
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

  // World-space point standing in for a player: the matching edge of their
  // own viewport (FFA) or of the table (2-player).
  _combatPlayerPoint(seatIdx, anchorX) {
    const rect = this._isFfa() ? this._regionWorldRect(seatIdx) : this._visibleWorldRect();
    const atBottom = this._quadrantFor(seatIdx).growDirection === "down";
    const y = atBottom ? rect.maxY - 26 : rect.minY + 26;
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
  // line, so the table center stays visible even on a sparse board). 3-4
  // player games instead fit one camera per seat viewport.
  _updateCameraTarget() {
    if (this._isFfa()) {
      this.camTarget = null; // the global camera is unused in FFA
      this._updateFfaCameraTargets();
      return;
    }
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
    // Keep the viewer's emblem tokens (left of the board) in frame.
    for (const item of this.emblemItems) {
      const b = this._emblemBounds(item);
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
    const vw = (this.cssW || 0) / BF_OVERSCAN_X;
    // Vertically, project the stage edges onto the table plane exactly, after
    // trimming the screen bands covered by the DOM hand fans — otherwise a
    // 3-row board parks the viewer's land row underneath their hand.
    let vy = ((this.cssH || 0) * (1 - 1 / BF_OVERSCAN_Y)) / 2;
    let vh = (this.cssH || 0) / BF_OVERSCAN_Y;
    const stage = this.canvas.parentElement?.getBoundingClientRect();
    if (stage && stage.width > 0 && stage.height > 0) {
      const players = this.currentState?.players || [];
      const handCount = (seat) => {
        const p = players[seat];
        return p?.hand_count ?? (Array.isArray(p?.hand) ? p.hand.length : 0);
      };
      // Any opponent whose quadrant sits in the top half fans their card
      // backs over the top edge; a bottom-half opponent (4-player FFA's
      // bottom-right seat) fans over the bottom edge next to the viewer.
      let topHandShown = false;
      let bottomOppHandShown = false;
      for (let s = 0; s < players.length; s++) {
        if (s === this.viewerSeat || handCount(s) <= 0) continue;
        if (this._quadrantFor(s).growDirection === "down") bottomOppHandShown = true;
        else topHandShown = true;
      }
      const topReserve = topHandShown ? BF_HAND_RESERVE_TOP : BF_EDGE_RESERVE_TOP;
      const bottomReserve = handCount(this.viewerSeat) > 0
        ? BF_HAND_RESERVE_BOTTOM
        : bottomOppHandShown
          ? BF_HAND_RESERVE_TOP
          : BF_EDGE_RESERVE_BOTTOM;
      const cx = stage.left + stage.width / 2;
      const topY = this._pageToCanvas(cx, stage.top + topReserve).y;
      const bottomY = this._pageToCanvas(cx, stage.bottom - bottomReserve).y;
      if (bottomY > topY) {
        vy = topY;
        vh = bottomY - topY;
      }
    }
    if (vw <= 0 || vh <= 0) return;

    const zoom = Math.max(BF_MIN_ZOOM, Math.min(BF_MAX_ZOOM, vw / bw, vh / bh));
    this.camTarget = {
      x: vx + (vw - bw * zoom) / 2 - bx * zoom,
      y: vy + (vh - bh * zoom) / 2 - by * zoom,
      zoom,
    };
  }

  // Free-For-All: fit one camera per seat, framing that seat's quadrant
  // content (cards rendering in its quadrant, plus the viewer's emblems)
  // inside its own screen viewport — each quadrant pans/zooms independently
  // of how crowded the other seats' boards are.
  _updateFfaCameraTargets() {
    const players = this.currentState?.players || [];
    const stage = this.canvas.parentElement?.getBoundingClientRect();
    const stageC = this._stageCanvasRect();
    const handCount = (seat) => {
      const p = players[seat];
      return p?.hand_count ?? (Array.isArray(p?.hand) ? p.hand.length : 0);
    };
    for (const region of this._regions()) {
      const seat = region.seat;
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const item of this.cardItems) {
        if (this._itemRegionSeat(item, true) !== seat) continue;
        const b = this._targetBounds(item.key);
        if (!b) continue;
        minX = Math.min(minX, b.x);
        minY = Math.min(minY, b.y);
        maxX = Math.max(maxX, b.x + b.w);
        maxY = Math.max(maxY, b.y + b.h);
      }
      if (seat === this.viewerSeat) {
        for (const item of this.emblemItems) {
          const b = this._emblemBounds(item);
          minX = Math.min(minX, b.x);
          minY = Math.min(minY, b.y);
          maxX = Math.max(maxX, b.x + b.w);
          maxY = Math.max(maxY, b.y + b.h);
        }
      }
      const q = this._quadrantFor(seat);
      const growsDown = q.growDirection === "down";
      if (!Number.isFinite(minX)) {
        // Empty quadrant: frame a sensible area against the split line.
        minX = q.xOffset;
        maxX = q.xOffset + 4 * BF_SLOT_PITCH_X;
        minY = growsDown ? BF_WORLD_SPLIT_Y : BF_WORLD_SPLIT_Y - 320;
        maxY = growsDown ? BF_WORLD_SPLIT_Y + 320 : BF_WORLD_SPLIT_Y;
      }
      // Anchor the fit to the split line so the front band hugs the divider.
      if (growsDown) minY = Math.min(minY, BF_WORLD_SPLIT_Y + 4);
      else maxY = Math.max(maxY, BF_WORLD_SPLIT_Y - 4);

      const bx = minX - BF_FIT_PADDING;
      const by = minY - BF_FIT_PADDING;
      const bw = maxX - minX + 2 * BF_FIT_PADDING;
      const bh = maxY - minY + 2 * BF_FIT_PADDING;

      // Usable part of the viewport: trimmed to the visible stage, inset off
      // the separator lines, minus the screen bands the DOM hand fans cover.
      let ux = Math.max(region.x, stageC.x);
      let uy = Math.max(region.y, stageC.y);
      let ux1 = Math.min(region.x + region.w, stageC.x + stageC.w);
      let uy1 = Math.min(region.y + region.h, stageC.y + stageC.h);
      const SEP_INSET = 14;
      if (region.x > stageC.x) ux += SEP_INSET;
      if (region.x + region.w < stageC.x + stageC.w) ux1 -= SEP_INSET;
      if (region.y > stageC.y) uy += SEP_INSET;
      if (region.y + region.h < stageC.y + stageC.h) uy1 -= SEP_INSET;
      if (stage && stage.width > 0 && stage.height > 0) {
        const cxPage = stage.left + stage.width / 2;
        if (region.y <= stageC.y) {
          // Viewport touches the stage top: this opponent fans card backs there.
          const reserve = handCount(seat) > 0 ? BF_HAND_RESERVE_TOP : BF_EDGE_RESERVE_TOP;
          uy = Math.max(uy, this._pageToCanvas(cxPage, stage.top + reserve).y);
        }
        if (region.y + region.h >= stageC.y + stageC.h) {
          // Viewport touches the stage bottom: the viewer's tucked fan (or,
          // with 4 players, the bottom-right opponent's card backs) covers it.
          const reserve = handCount(seat) > 0
            ? (seat === this.viewerSeat ? BF_HAND_RESERVE_BOTTOM : BF_HAND_RESERVE_TOP)
            : BF_EDGE_RESERVE_BOTTOM;
          uy1 = Math.min(uy1, this._pageToCanvas(cxPage, stage.bottom - reserve).y);
        }
      }
      const vw = ux1 - ux;
      const vh = uy1 - uy;
      if (vw <= 0 || vh <= 0) continue;

      const zoom = Math.max(BF_MIN_ZOOM, Math.min(BF_MAX_ZOOM, vw / bw, vh / bh));
      const cam = this._camFor(seat);
      cam.target = {
        x: ux + (vw - bw * zoom) / 2 - bx * zoom,
        y: uy + (vh - bh * zoom) / 2 - by * zoom,
        zoom,
      };
      if (cam.fresh) {
        // First fit for this seat: snap instead of easing in from nowhere.
        cam.fresh = false;
        cam.x = cam.target.x;
        cam.y = cam.target.y;
        cam.zoom = cam.target.zoom;
      }
    }
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
    // motion never carries the stack out of view. Zone piles are pinned the
    // same way to the left edge.
    this._retargetStackVisuals();
    this._retargetZonePiles();
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
    // FFA per-seat viewport cameras ease toward their own targets.
    for (const cam of this.seatCams.values()) {
      const ct = cam.target;
      if (!ct || (ct.x === cam.x && ct.y === cam.y && ct.zoom === cam.zoom)) continue;
      const dx = ct.x - cam.x;
      const dy = ct.y - cam.y;
      const dz = ct.zoom - cam.zoom;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5 && Math.abs(dz) < 0.002) {
        cam.x = ct.x;
        cam.y = ct.y;
        cam.zoom = ct.zoom;
      } else {
        cam.x += dx * BF_CAM_EASE;
        cam.y += dy * BF_CAM_EASE;
        cam.zoom += dz * BF_CAM_EASE;
      }
      moving = true;
    }
    // The priority pulse animates continuously, so keep redrawing while a side
    // holds priority and the game is still going.
    if (this._priorityPulseSide()) moving = true;
    // Flyers bob and tilt continuously, so keep the frame loop alive for them.
    if (!moving && this.cardItems.some((it) => _isFlyer(it.card))) moving = true;
    // The indestructible gleam sweeps continuously — same deal.
    if (
      !moving &&
      !this.reducedMotion &&
      this.cardItems.some((it) => it.card?.is_indestructible)
    ) moving = true;
    // The mana fan pops, pulses and bobs — keep redrawing while it's open.
    if (this.manaFan) moving = true;
    // Zone-pile targeting pulses continuously while a graveyard target is
    // being chosen.
    if (this.zonePileTargeting) moving = true;
    // Combat/targeting arrows carry traveling pulses — keep redrawing while any
    // are on screen (or a blocker drag is live). Tied strictly to arrow
    // presence so the dirty-flag idles again once combat ends.
    if (!this.reducedMotion && (this.combatArrows.length || this.pressState?.combatDrag)) moving = true;
    // Aura connectors pulse only while their stack is hovered.
    if (
      !this.reducedMotion &&
      !moving &&
      this.hoveredKey != null &&
      this.stacks.some((s) => s.sideX && s.keys.includes(this.hoveredKey))
    ) moving = true;
    if (moving) this.needsRedraw = true;
  }

  // ---------------------------------------------------------------------------
  // Selection / highlights
  // ---------------------------------------------------------------------------

  setSelectedKeys(keys) { this.selectedKeys = new Set(keys); this.needsRedraw = true; }
  setAttackingKeys(keys) { this.attackingKeys = new Set(keys); this.needsRedraw = true; }
  setTargetingKeys(keys) { this.targetingKeys = new Set(keys); this.needsRedraw = true; }

  // "Waiting for <name>" above the top stack card while another player holds
  // priority. Pass null to clear. The timestamp survives repeated calls with
  // the same name so the show-after-delay check has a stable anchor.
  setStackWaitingLabel(name) {
    if (!name) {
      if (this.stackWaitingLabel) this.needsRedraw = true;
      this.stackWaitingLabel = null;
      return;
    }
    if (this.stackWaitingLabel?.name !== name) {
      this.stackWaitingLabel = { name, since: performance.now() };
    }
    this.needsRedraw = true;
  }

  setCombatArrows(arrows) {
    // arrows: [{fromSeat, fromIdx, toSeat, toIdx, kind}]
    this.combatArrows = arrows;
    this.needsRedraw = true;
  }

  setCombatBands(bands) {
    // bands: [[{seat, idx}, ...], ...] — attacking bands to draw as a connected group.
    this.combatBands = Array.isArray(bands) ? bands : [];
    this.needsRedraw = true;
  }

  // Push Raging River's left/right division state. Re-applies the pile-split
  // layout (once a side's piles are locked, its creatures cluster left/right).
  setRagingRiver(river) {
    this.river = river && river.active ? river : null;
    this._applyRiverLayout();
    // Cards may have moved into left/right clusters — refit so none clip offscreen.
    this._updateCameraTarget();
    this.needsRedraw = true;
  }

  // Push Camouflage's pending pile division (numbered buttons above the
  // defending player's untapped creatures), or null when none is pending.
  setCamouflage(camouflage) {
    this.camouflage = camouflage && camouflage.active ? camouflage : null;
    this.needsRedraw = true;
  }

  // The locked pile side ("left"/"right") for a creature, or null when its
  // controller hasn't committed yet (so it isn't badged/rearranged early).
  _riverSideForKey(seat, idx) {
    const r = this.river;
    if (!r) return null;
    if (seat === r.defenderSeat && r.defenderLocked) {
      const s = r.defenderPiles?.[idx];
      if (s) return s;
    }
    if (seat === r.attackerSeat && r.attackerLocked) {
      const s = r.attackerPiles?.[idx];
      if (s) return s;
    }
    return null;
  }

  // Rearrange each player's committed creatures into a left cluster and a right
  // cluster (CR 702 Raging River). Runs after _layoutBoard, overriding the
  // horizontal slot of every piled creature; vertical band position is kept.
  _applyRiverLayout() {
    this._riverClusters = [];
    const r = this.river;
    if (!r || !r.active) return;
    const sides = [
      { seat: r.defenderSeat, piles: r.defenderPiles, locked: r.defenderLocked },
      { seat: r.attackerSeat, piles: r.attackerPiles, locked: r.attackerLocked },
    ];
    for (const { seat, piles, locked } of sides) {
      if (!locked || !piles || !Number.isInteger(seat)) continue;
      const entries = Object.entries(piles)
        .map(([idx, side]) => ({ key: `${seat}-${Number(idx)}`, side }))
        .filter((e) => this.cardItems.some((c) => c.key === e.key));
      if (!entries.length) continue;
      // Anchor the split around where these creatures already sit so the camera
      // barely moves: average their current layout target.
      let sumX = 0;
      let sumY = 0;
      for (const e of entries) {
        const it = this.cardItems.find((c) => c.key === e.key);
        sumX += it.tx;
        sumY += it.ty;
      }
      const center = sumX / entries.length + BF_CARD_W / 2;
      const rowY = sumY / entries.length;
      const lefts = entries.filter((e) => e.side === "left");
      const rights = entries.filter((e) => e.side === "right");
      const gap = BF_SLOT_PITCH_X; // clear divider channel between the two piles
      lefts.forEach((e, i) => {
        const it = this.cardItems.find((c) => c.key === e.key);
        // Last "left" creature hugs the divider; earlier ones extend further left.
        it.tx = center - gap / 2 - (lefts.length - i) * BF_SLOT_PITCH_X;
        it.ty = rowY;
      });
      rights.forEach((e, i) => {
        const it = this.cardItems.find((c) => c.key === e.key);
        it.tx = center + gap / 2 + i * BF_SLOT_PITCH_X;
        it.ty = rowY;
      });
      this._riverClusters.push({
        seat,
        center,
        rowY,
        leftKeys: lefts.map((e) => e.key),
        rightKeys: rights.map((e) => e.key),
      });
      // Break apart identity piles that now straddle the divider so each member
      // renders at its own spot rather than fanning from a single anchor.
      const movedKeys = new Set(entries.map((e) => e.key));
      this.stacks = this.stacks.filter(
        (s) => s.kind !== "pile" || !s.keys.some((k) => movedKeys.has(k))
      );
    }
  }

  // Is the given card key part of the band the hovered card belongs to? Used to
  // group-highlight a band when any of its members is hovered.
  _bandKeysForHover() {
    if (!this.hoveredKey || !this.combatBands.length) return null;
    for (const band of this.combatBands) {
      const keys = band.map((m) => `${m.seat}-${m.idx}`);
      if (keys.includes(this.hoveredKey)) return new Set(keys);
    }
    return null;
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

  // Draw `img` into the (dx,dy,dw,dh) box "cover"-fit: scaled to fill the box,
  // overflow cropped, centered. Used to fit a wide art_crop into the portrait
  // art window without distortion. Caller is expected to have clipped the box.
  _drawImageCover(ctx, img, dx, dy, dw, dh) {
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    const scale = Math.max(dw / iw, dh / ih);
    const sw = dw / scale;
    const sh = dh / scale;
    const sx = (iw - sw) / 2;
    // Bias the crop slightly above center — card art usually has its subject in
    // the upper portion, and this keeps faces in frame in the portrait window.
    const sy = (ih - sh) * 0.4;
    ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
  }

  // The colored, beveled title plate across the top of a card, with the card's
  // name auto-fit (shrunk, then ellipsized) to one line. Serif face to echo the
  // Beleren title font MTG uses.
  _drawNamePlate(ctx, name, px, py, pw, ph, fc, r) {
    const rr = Math.min(r, ph / 2);
    const g = ctx.createLinearGradient(0, py, 0, py + ph);
    g.addColorStop(0, fc.hi);
    g.addColorStop(1, fc.base);
    ctx.fillStyle = g;
    this._roundRect(ctx, px, py, pw, ph, rr);
    ctx.fill();
    // Top highlight + full outline for a raised, engraved look.
    ctx.strokeStyle = "rgba(0,0,0,0.5)";
    ctx.lineWidth = 1 / this.zoom;
    this._roundRect(ctx, px, py, pw, ph, rr);
    ctx.stroke();
    ctx.strokeStyle = "rgba(255,255,255,0.4)";
    ctx.lineWidth = 1 / this.zoom;
    ctx.beginPath();
    ctx.moveTo(px + rr, py + 0.8 / this.zoom);
    ctx.lineTo(px + pw - rr, py + 0.8 / this.zoom);
    ctx.stroke();

    const pad = 3;
    const maxW = pw - pad * 2;
    let font = Math.max(7, ph * 0.62);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `bold ${font}px Georgia, "Times New Roman", serif`;
    let text = String(name || "");
    while (font > 6 && ctx.measureText(text).width > maxW) {
      font -= 0.5;
      ctx.font = `bold ${font}px Georgia, "Times New Roman", serif`;
    }
    text = _ellipsizeText(ctx, text, maxW);
    // Legibility shadow under the engraved title.
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillText(text, px + pw / 2, py + ph / 2 + 1);
    ctx.fillStyle = fc.ink;
    ctx.fillText(text, px + pw / 2, py + ph / 2 + 0.5);
  }

  // A mana source's produced-mana symbols, drawn as a centered row of discs
  // pinned to the bottom of the card. Covers lands and mana rocks (artifacts
  // like Sol Ring / the Moxen) — anything with produced mana that isn't a
  // creature, since creatures reserve that bottom-center strip for their
  // power/toughness box. Each symbol SVG already carries its color; a shadow
  // disc behind it lifts it off the art.
  _drawLandMana(ctx, card, x, y, w, h, m) {
    const type = String(card?.type || "").toLowerCase();
    if (type.includes("creature")) return;
    const produced = Array.isArray(card?.produced_mana) ? card.produced_mana : [];
    if (!produced.length) return;
    const sz = Math.max(12, w * 0.2);
    const gap = Math.max(2, w * 0.03);
    const n = produced.length;
    const totalW = n * sz + (n - 1) * gap;
    let sx = x + w / 2 - totalW / 2;
    const cy = y + h - m - sz / 2;
    for (const sym of produced) {
      const cxp = sx + sz / 2;
      // Shadow disc behind the symbol.
      ctx.save();
      ctx.shadowColor = "rgba(0,0,0,0.65)";
      ctx.shadowBlur = 3 / this.zoom;
      ctx.shadowOffsetY = 1 / this.zoom;
      ctx.fillStyle = "rgba(0,0,0,0.3)";
      ctx.beginPath();
      ctx.arc(cxp, cy, sz / 2 + 0.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      const src = this._symbolSrc(`{${sym}}`);
      const symImg = src ? this._loadImage(src) : null;
      if (symImg && symImg.complete && symImg.naturalWidth) {
        ctx.drawImage(symImg, cxp - sz / 2, cy - sz / 2, sz, sz);
      } else {
        // Fallback: a colored disc with the mana letter until the SVG loads.
        ctx.fillStyle = BF_MANA_GLOW[sym] || "#c2c6cf";
        ctx.beginPath();
        ctx.arc(cxp, cy, sz / 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "rgba(0,0,0,0.8)";
        ctx.font = `bold ${sz * 0.7}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(sym), cxp, cy + 0.5);
      }
      sx += sz + gap;
    }
  }

  // Draw a single emblem token: the source card's art in a card-like frame with
  // a glowing orange border (marking it as an ability, not a real card) and a
  // short cost/effect label so the player knows what clicking it does.
  _drawEmblem(ctx, item) {
    const { x, y, w, h } = item;
    const emblem = item.emblem || {};
    const cardLike = { name: emblem.source || "Emblem", image_uri: emblem.image_uri || null, type: "" };
    const hovered = this.hoveredEmblemIndex === item.index;
    this._drawCardFace(ctx, x, y, w, h, cardLike, { emblem: true, hovered }, null);

    // Cost/effect caption across the bottom of the token, rendering {N}/{W}…
    // mana tokens as their actual symbol art rather than literal "{1}" text.
    if (emblem.label) this._drawEmblemCaption(ctx, emblem.label, x, y, w, h);
  }

  // Map a mana token like "{1}" or "{W}" to its symbol SVG (served from
  // /symbols/<body>.svg, matching web/static/symbols/).
  _symbolSrc(token) {
    const m = /^\{([^}]+)\}$/.exec(token);
    if (!m) return null;
    return `/symbols/${m[1].toLowerCase()}.svg`;
  }

  // Split a whitespace-free word into text runs and {symbol} tokens so a word
  // like "{1}:" draws as the mana symbol immediately followed by the colon.
  _segmentSymbolWord(word) {
    const segs = [];
    const re = /\{[^}]+\}/g;
    let last = 0, m;
    while ((m = re.exec(word)) !== null) {
      if (m.index > last) segs.push({ t: "text", s: word.slice(last, m.index) });
      segs.push({ t: "sym", token: m[0], src: this._symbolSrc(m[0]) });
      last = m.index + m[0].length;
    }
    if (last < word.length) segs.push({ t: "text", s: word.slice(last) });
    return segs;
  }

  _drawEmblemCaption(ctx, label, x, y, w, h) {
    ctx.save();
    const font = Math.max(6, w * 0.1);
    ctx.font = `bold ${font}px sans-serif`;
    const lineH = font + 3;
    const symSize = font + 1;
    const maxWidth = w - 6;
    const spaceW = ctx.measureText(" ").width;

    // Each word is a list of text/symbol segments; symbols are square (symSize).
    const wordWidth = (segs) =>
      segs.reduce((sum, sg) => sum + (sg.t === "sym" && sg.src ? symSize : ctx.measureText(sg.t === "sym" ? sg.token : sg.s).width), 0);

    const words = String(label).split(" ").filter(Boolean).map((wd) => {
      const segs = this._segmentSymbolWord(wd);
      return { segs, width: wordWidth(segs) };
    });

    // Greedy wrap into lines, tracking each line's pixel width for centering.
    const lines = [];
    let cur = [], curW = 0;
    for (const word of words) {
      const add = (cur.length ? spaceW : 0) + word.width;
      if (cur.length && curW + add > maxWidth) {
        lines.push({ words: cur, width: curW });
        cur = [word]; curW = word.width;
      } else {
        cur.push(word); curW += add;
      }
    }
    if (cur.length) lines.push({ words: cur, width: curW });

    const bandH = lines.length * lineH + 4;
    const bandTop = y + h - bandH;
    ctx.fillStyle = "rgba(120,60,0,0.82)";
    ctx.fillRect(x, bandTop, w, bandH);

    ctx.fillStyle = "#ffd9a0";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    let ty = bandTop + 2 + lineH / 2;
    for (const line of lines) {
      let tx = x + (w - line.width) / 2;
      for (let i = 0; i < line.words.length; i++) {
        if (i > 0) tx += spaceW;
        for (const sg of line.words[i].segs) {
          if (sg.t === "sym" && sg.src) {
            const img = this._loadImage(sg.src);
            if (img) ctx.drawImage(img, tx, ty - symSize / 2, symSize, symSize);
            else { ctx.fillText(sg.token, tx, ty); }
            tx += symSize;
          } else {
            const s = sg.t === "sym" ? sg.token : sg.s;
            ctx.fillText(s, tx, ty);
            tx += ctx.measureText(s).width;
          }
        }
      }
      ty += lineH;
    }
    ctx.restore();
  }

  _resolveTheme() {
    const styles = getComputedStyle(document.documentElement);
    const token = (name, fallback) => {
      const value = styles.getPropertyValue(name).trim();
      return value || fallback;
    };
    return {
      emblem: "#ff9933",
      attacking: "#ff5555",
      selected: "#ffe040",
      targeting: "#50ffb0",
      enchant: "#c06bff",
      hovered: token("--accent-2", "#7ec4ff"),
      frameStroke: token("--glass-stroke", "rgba(255,255,255,0.22)"),
      frameHighlight: token("--glass-highlight", "rgba(255,255,255,0.22)"),
      arrowAttack: "#ff6060",
      arrowBlock: "#48b0ff",
      arrowDrag: "#ff8888",
      arrowAura: "#caa6ff",
      arrowTarget: "#ffd76a",
    };
  }

  // Render a card as its original full-card image (printed frame, art and text
  // all baked in), clipped to a rounded rect with a drop shadow and a hover/
  // state glow. Used for spells in flight and sitting on the stack — where the
  // full Magic card reads better than the Arena battlefield face.
  _drawFullCardFace(ctx, x, y, w, h, card, flags) {
    const { hovered, selected, targeting } = flags || {};
    const url = card?.large_image_uri || card?.image_uri || null;
    const img = url ? this._loadImage(url) : null;
    const R = 5;

    ctx.save();

    // ---- Drop shadow ----
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.shadowBlur = (hovered ? 26 : 13) / this.zoom;
    ctx.shadowOffsetY = (hovered ? 11 : 6) / this.zoom;
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    this._roundRect(ctx, x, y, w, h, R);
    ctx.fill();
    ctx.restore();

    // ---- Clipped full card image ----
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
    ctx.restore();

    // ---- Border / hover-state glow ----
    const T = this.theme;
    const stateColor = selected ? T.selected : targeting ? T.targeting : hovered ? T.hovered : null;
    ctx.save();
    if (stateColor) {
      ctx.shadowColor = stateColor;
      ctx.shadowBlur = 14 / this.zoom;
      ctx.strokeStyle = stateColor;
      ctx.lineWidth = 2.5 / this.zoom;
    } else {
      ctx.strokeStyle = "rgba(0,0,0,0.55)";
      ctx.lineWidth = 1.2 / this.zoom;
    }
    this._roundRect(ctx, x, y, w, h, R);
    ctx.stroke();
    ctx.restore();

    ctx.restore();
  }

  _drawCardFace(ctx, x, y, w, h, card, flags, creatureCard) {
    const { selected, attacking, hovered, targeting, pileCount, emblem, enchantTargetHover, fullImage } = flags || {};
    // Spells in flight and on the stack render as their original full card image
    // (printed frame/art/text baked in) rather than the Arena battlefield face.
    if (fullImage) {
      this._drawFullCardFace(ctx, x, y, w, h, card, flags);
      return;
    }
    // Arena-style face: the borderless art crop (falling back to the full card
    // image) sits inside a custom colored, beveled frame drawn below.
    const artUrl = card?.art_crop || card?.image_uri || null;
    const img = artUrl ? this._loadImage(artUrl) : null;
    const R = 5;
    const fc = _cardFrameColors(card);

    // A genuinely unblockable creature (Dwarven Warriors' "can't be blocked this
    // turn", or inherent unblockable text) is rendered translucent — as if it can
    // slip through blockers — with an "Unblockable" tag below.
    const unblockableCard = creatureCard || card;
    const isUnblockable = !!(unblockableCard && unblockableCard.unblockable);

    ctx.save(); // outer group — balanced by the final restore at function end

    // Face group (frame + art + title + mana): kept in its own save so the whole
    // face can fade together when the creature is unblockable (a "phasing" look),
    // while the state-glow border and status badges below stay full opacity.
    ctx.save();
    if (isUnblockable) ctx.globalAlpha = 0.5;

    // ---- Drop shadow onto the table ----
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.shadowBlur = (hovered ? 26 : 13) / this.zoom;
    ctx.shadowOffsetY = (hovered ? 11 : 6) / this.zoom;
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    this._roundRect(ctx, x, y, w, h, R);
    ctx.fill();
    ctx.restore();

    // ---- Frame panel: beveled gradient in the card's color ----
    const panel = ctx.createLinearGradient(0, y, 0, y + h);
    panel.addColorStop(0, fc.hi);
    panel.addColorStop(0.52, fc.base);
    panel.addColorStop(1, fc.lo);
    ctx.fillStyle = panel;
    this._roundRect(ctx, x, y, w, h, R);
    ctx.fill();

    // ---- Face geometry: title plate on top, art window below ----
    const m = Math.max(3, w * 0.055);        // frame thickness
    const nh = Math.max(11, h * 0.115);      // title plate height
    const artX = x + m;
    const artTop = y + m + nh + 1;
    const artW = w - 2 * m;
    const artH = y + h - m - artTop;
    const artR = Math.max(2, R * 0.5);

    // ---- Art window (art_crop, cover-fit) ----
    if (artH > 4) {
      ctx.save();
      this._roundRect(ctx, artX, artTop, artW, artH, artR);
      ctx.clip();
      ctx.fillStyle = "#0d1320";
      ctx.fillRect(artX, artTop, artW, artH);
      if (img) {
        this._drawImageCover(ctx, img, artX, artTop, artW, artH);
      } else if (card?.name) {
        ctx.fillStyle = "#8ab";
        ctx.font = `bold ${Math.max(7, w * 0.11)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        _wrapCanvasText(ctx, card.name, artX + artW / 2, artTop + 4, artW - 6, Math.max(9, w * 0.12));
      }
      // Summoning sickness tint over the art.
      if (card?.summoning_sick) {
        ctx.fillStyle = "rgba(90,20,220,0.24)";
        ctx.fillRect(artX, artTop, artW, artH);
      }
      // Soft sheen across the top of the art.
      const sheen = ctx.createLinearGradient(0, artTop, 0, artTop + artH * 0.35);
      sheen.addColorStop(0, "rgba(255,255,255,0.14)");
      sheen.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = sheen;
      ctx.fillRect(artX, artTop, artW, artH * 0.35);
      ctx.restore();
      // Inset shadow line around the art window for recessed depth.
      ctx.strokeStyle = "rgba(0,0,0,0.6)";
      ctx.lineWidth = 1 / this.zoom;
      this._roundRect(ctx, artX, artTop, artW, artH, artR);
      ctx.stroke();
    }

    // ---- Title plate ----
    this._drawNamePlate(ctx, card?.name, x + m, y + m, w - 2 * m, nh, fc, artR + 1);

    // ---- Land mana symbols (bottom center) ----
    this._drawLandMana(ctx, card, x, y, w, h, m);

    ctx.restore(); // end face group (unblockable fade)

    // ---- Frame bevel + state glow border ----
    const T = this.theme;
    const strongState = emblem || attacking || selected || targeting || enchantTargetHover;
    const stateColor = emblem ? T.emblem
      : attacking ? T.attacking
      : selected ? T.selected
      : targeting ? T.targeting
      : enchantTargetHover ? T.enchant
      : hovered ? T.hovered
      : null;
    ctx.save();
    if (stateColor) {
      // Wide, low-alpha bloom ring under the crisp border.
      ctx.save();
      ctx.globalAlpha = 0.4;
      ctx.shadowColor = stateColor;
      ctx.shadowBlur = (strongState ? 28 : 18) / this.zoom;
      ctx.strokeStyle = stateColor;
      ctx.lineWidth = 4 / this.zoom;
      this._roundRect(ctx, x, y, w, h, R);
      ctx.stroke();
      ctx.restore();

      ctx.shadowColor = stateColor;
      ctx.shadowBlur = (emblem ? (hovered ? 22 : 16) : attacking ? 18 : selected ? 14 : targeting ? 16 : enchantTargetHover ? 18 : 10) / this.zoom;
    }
    // Outer edge: the state color when active, otherwise the frame's dark bevel.
    ctx.strokeStyle = stateColor || "rgba(0,0,0,0.55)";
    ctx.lineWidth = (strongState ? 2.5 : 1.2) / this.zoom;
    this._roundRect(ctx, x, y, w, h, R);
    ctx.stroke();
    // Inner rim highlight along the top edge sells the raised bevel.
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h * 0.5);
    ctx.clip();
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.lineWidth = 1 / this.zoom;
    this._roundRect(ctx, x + 1 / this.zoom, y + 1 / this.zoom, w - 2 / this.zoom, h - 2 / this.zoom, R);
    ctx.stroke();
    ctx.restore();
    ctx.restore();

    // ---- Indestructible gleam ----
    // A shiny highlight sweeping diagonally across the card, so a granted
    // indestructible (Guardian Beast's artifacts, Consecrate Land's land) reads
    // at a glance rather than only as a badge. Skipped under reduced motion —
    // the keyword text and badge still carry the information.
    if ((creatureCard || card)?.is_indestructible && !this.reducedMotion) {
      const period = 2600;
      // Per-card phase so several protected artifacts don't gleam in lockstep.
      const t = ((performance.now() / period) + _keyPhase(card?.name || "") / (Math.PI * 2)) % 1;
      // Sweep from off one corner to off the other, so the band is absent for
      // part of the cycle rather than looping continuously.
      const travel = (w + h) * 2;
      const offset = -travel / 2 + t * travel * 2;
      ctx.save();
      this._roundRect(ctx, x, y, w, h, R);
      ctx.clip();
      const gleam = ctx.createLinearGradient(
        x + offset, y, x + offset + w * 0.55, y + h,
      );
      gleam.addColorStop(0, "rgba(255,255,255,0)");
      gleam.addColorStop(0.45, "rgba(255,255,255,0.30)");
      gleam.addColorStop(0.5, "rgba(226,240,255,0.55)");
      gleam.addColorStop(0.55, "rgba(255,255,255,0.30)");
      gleam.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = gleam;
      ctx.fillRect(x, y, w, h);
      ctx.restore();
    }

    // ---- Keyword strip ----
    // Render the permanent's current keywords (Flying, Trample, First Strike,
    // Indestructible, …) in a translucent band just above the badge row. For an
    // enchanted creature hidden under an aura, creatureCard carries the keywords
    // (incl. any the aura grants); otherwise the card's own keywords are used.
    // Noncreature permanents get the band too — Guardian Beast grants
    // indestructible to artifacts, and that has to be visible on them.
    const kwCard = creatureCard || card;
    const keywords = Array.isArray(kwCard?.keywords) ? kwCard.keywords : [];
    if (keywords.length) {
      const isCreatureCard = String(kwCard?.type || "").toLowerCase().includes("creature");
      const font = Math.max(6, w * 0.085);
      ctx.font = `bold ${font}px sans-serif`;
      const lineH = font + 2;
      const lines = _wrapKeywordLines(ctx, keywords, w - 6);
      const bandH = lines.length * lineH + 3;
      // Leave the bottom corners for P/T and damage badges; a noncreature has
      // neither, so its band sits flush with the bottom edge.
      const reserveBottom = isCreatureCard ? 16 : 3;
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
    const ptIsCreature = !!(ptCard && (ptCard.is_creature || String(ptCard.type || "").toLowerCase().includes("creature")));
    let ptBadgeDrawn = false;
    if (ptCard && typeof ptCard.power === "number" && typeof ptCard.toughness === "number" && ptIsCreature) {
      ptBadgeDrawn = true;
      const bw = 28, bh = 15;
      const bx = x + w - bw - 2, by = y + h - bh - 2;
      // Beveled dark capsule with a colored-frame rim for depth.
      const cap = ctx.createLinearGradient(0, by, 0, by + bh);
      cap.addColorStop(0, "rgba(46,46,52,0.97)");
      cap.addColorStop(1, "rgba(12,12,17,0.97)");
      ctx.fillStyle = cap;
      this._roundRect(ctx, bx, by, bw, bh, 4);
      ctx.fill();
      ctx.strokeStyle = fc.hi;
      ctx.lineWidth = 1.2 / this.zoom;
      this._roundRect(ctx, bx, by, bw, bh, 4);
      ctx.stroke();
      ctx.strokeStyle = "rgba(255,255,255,0.28)";
      ctx.lineWidth = 1 / this.zoom;
      ctx.beginPath();
      ctx.moveTo(bx + 3, by + 1 / this.zoom);
      ctx.lineTo(bx + bw - 3, by + 1 / this.zoom);
      ctx.stroke();
      ctx.font = `bold ${Math.max(8, bh * 0.7)}px sans-serif`;
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

    // ---- Counter badges (corpse, vitality, …) ----
    // Every counter type in the serialized `counters` map gets a badge so the
    // player can see the card's banked counters (Scavenging Ghoul's corpse
    // counters, Living Artifact's vitality counters). Normally bottom-right;
    // for an aura fanned behind its enchanted permanent only the top strip of
    // the card is visible, so its badges anchor top-right instead of being
    // hidden under the base card (flags.occludedAuraMember).
    const counterEntries = [];
    const counterMap = card && card.counters;
    if (counterMap && typeof counterMap === "object" && Object.keys(counterMap).length) {
      for (const [kind, n] of Object.entries(counterMap)) {
        if (Number(n) > 0) counterEntries.push([kind, Number(n)]);
      }
    } else if (card && Number(card.corpse_counters) > 0) {
      counterEntries.push(["corpse", Number(card.corpse_counters)]);
    }
    if (counterEntries.length) {
      const styles = {
        corpse: { icon: "☠", fill: "rgba(60,40,70,0.92)", stroke: "rgba(180,140,220,0.9)", text: "#f0e6ff" },
        vitality: { icon: "❤", fill: "rgba(30,70,40,0.92)", stroke: "rgba(130,220,150,0.9)", text: "#e6ffe9" },
      };
      const fallbackStyle = { icon: "●", fill: "rgba(40,50,70,0.92)", stroke: "rgba(150,180,220,0.9)", text: "#e8f0ff" };
      const bw = 22, bh = 13;
      const atTop = !!(flags && flags.occludedAuraMember);
      // When a P/T badge occupies the bottom-right corner, start the counter
      // stack one slot higher so counters never cover the power/toughness
      // (Scavenging Ghoul's corpse counters).
      const counterBaseSlot = ptBadgeDrawn && !atTop ? 1 : 0;
      counterEntries.forEach(([kind, count], i) => {
        const s = styles[kind] || fallbackStyle;
        const bx = x + w - bw - 2;
        const by = atTop
          ? y + 2 + i * (bh + 2)
          : y + h - bh - 2 - (i + counterBaseSlot) * (bh + 2);
        ctx.fillStyle = s.fill;
        this._roundRect(ctx, bx, by, bw, bh, 3);
        ctx.fill();
        ctx.strokeStyle = s.stroke;
        ctx.lineWidth = 1;
        this._roundRect(ctx, bx, by, bw, bh, 3);
        ctx.stroke();
        ctx.fillStyle = s.text;
        ctx.font = `bold ${Math.max(8, bh * 0.7)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(s.icon + count, bx + bw / 2, by + bh / 2);
      });
    }

    // ---- Damage-prevention shield badge ----
    // A shield with the remaining prevention value (Healing Salve / Samite Healer
    // on a creature, …). Sits at the top-left; hovering it previews the source.
    const shieldCard = creatureCard || card;
    if (shieldCard && Number(shieldCard.damage_prevention_pool) > 0) {
      this._drawShieldBadge(ctx, x + 3, y + 3, shieldCard.damage_prevention_pool);
    }

    // ---- Regeneration badge ----
    const regenCard = creatureCard || card;
    if (regenCard && Number(regenCard.regeneration_shield) > 0) {
      const label = "Regeneration";
      const bh = 13;
      ctx.font = `bold ${Math.max(7, bh * 0.62)}px sans-serif`;
      const bw = Math.min(w - 4, Math.ceil(ctx.measureText(label).width) + 8);
      const bx = x + (w - bw) / 2, by = y + 2;
      ctx.fillStyle = "rgba(34,139,34,0.9)";
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.fill();
      ctx.strokeStyle = "rgba(120,255,120,0.85)";
      ctx.lineWidth = 1;
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.stroke();
      ctx.fillStyle = "#eaffea";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx + bw / 2, by + bh / 2);
    }

    // ---- Color-change label (e.g. Lifelace: "Target ... becomes green.") ----
    const colorCard = creatureCard || card;
    const colorOverride = colorCard && colorCard.color_override;
    if (colorOverride) {
      const COLOR_SWATCH = { W: "#f8f6d8", U: "#3b7fd4", B: "#5a4a5a", R: "#d4452f", G: "#2f9e44", C: "#b8b8b8" };
      // Render "Color:" followed by the actual mana symbol art (not literal "{U}").
      const text = "Color:";
      const bh = 13;
      const symSize = bh - 3;
      ctx.font = `bold ${Math.max(7, bh * 0.62)}px sans-serif`;
      const textW = Math.ceil(ctx.measureText(text + " ").width);
      const bw = Math.min(w - 4, textW + symSize + 10);
      const bx = x + (w - bw) / 2;
      // Sit just below the regeneration badge if present, else at the top.
      const by = y + 2 + (regenCard && Number(regenCard.regeneration_shield) > 0 ? 15 : 0);
      ctx.fillStyle = "rgba(0,0,0,0.78)";
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.fill();
      ctx.strokeStyle = COLOR_SWATCH[colorOverride] || "rgba(255,255,255,0.85)";
      ctx.lineWidth = 1.5;
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(text, bx + 5, by + bh / 2);
      const symX = bx + 5 + textW;
      const symY = by + (bh - symSize) / 2;
      const symImg = this._loadImage(this._symbolSrc(`{${colorOverride}}`));
      if (symImg && symImg.complete && symImg.naturalWidth) {
        ctx.drawImage(symImg, symX, symY, symSize, symSize);
      } else {
        // Fallback to a colored dot until the symbol art has loaded.
        ctx.fillStyle = COLOR_SWATCH[colorOverride] || "#ffffff";
        ctx.beginPath();
        ctx.arc(symX + symSize / 2, by + bh / 2, symSize / 2, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // ---- Land-type override label ----
    // A land whose type has been changed shows its new basic type so the player
    // can see at a glance that it's now, e.g., a Swamp: a mire counter (Cyclopean
    // Tomb) or Evil Presence → Swamp, Gaea's Liege / Magical Hack → another type.
    const landOverride = card && card.land_type_override;
    if (landOverride && String(card.type || "").toLowerCase().includes("land")) {
      const TYPE_FILL = {
        plains: "rgba(150,140,60,0.92)",
        island: "rgba(40,90,170,0.92)",
        swamp: "rgba(70,55,80,0.95)",
        mountain: "rgba(180,60,40,0.92)",
        forest: "rgba(40,130,60,0.92)",
      };
      const t = String(landOverride).toLowerCase();
      const typeName = t.charAt(0).toUpperCase() + t.slice(1);
      // Note the source when a mire counter is what made it a Swamp.
      const label = card.mire_counter ? `${typeName} (mire)` : typeName;
      const bh = 13;
      ctx.font = `bold ${Math.max(7, bh * 0.62)}px sans-serif`;
      const bw = Math.min(w - 4, Math.ceil(ctx.measureText(label).width) + 8);
      // Drop below the top-right pile-count badge when this card is a pile, so
      // the two labels don't overlap on a stack of same-named lands.
      const bx = x + (w - bw) / 2, by = y + 2 + (pileCount >= 2 ? 16 : 0);
      ctx.fillStyle = TYPE_FILL[t] || "rgba(0,0,0,0.82)";
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.7)";
      ctx.lineWidth = 1;
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx + bw / 2, by + bh / 2);
    }

    // ---- Indestructible badge ----
    // A permanent granted indestructible (e.g. a land enchanted by Consecrate
    // Land) shows a steel "Indestructible" tag so the player knows it can't be
    // destroyed. Stacks below any land-type / pile badge already at the top.
    const indestructibleCard = creatureCard || card;
    if (indestructibleCard && indestructibleCard.is_indestructible) {
      const label = "Indestructible";
      const bh = 13;
      ctx.font = `bold ${Math.max(7, bh * 0.62)}px sans-serif`;
      const bw = Math.min(w - 4, Math.ceil(ctx.measureText(label).width) + 8);
      const bx = x + (w - bw) / 2;
      let by = y + 2;
      if (pileCount >= 2) by += 16;
      if (landOverride && String(card.type || "").toLowerCase().includes("land")) by += 15;
      ctx.fillStyle = "rgba(88,92,104,0.92)";
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.fill();
      ctx.strokeStyle = "rgba(206,212,224,0.9)";
      ctx.lineWidth = 1;
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.stroke();
      ctx.fillStyle = "#f2f4f8";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx + bw / 2, by + bh / 2);
    }

    // ---- Unblockable badge ----
    // An ethereal cyan "Unblockable" tag, stacked below any top badges so it
    // never overlaps them. Pairs with the translucent face applied above.
    if (isUnblockable) {
      const label = "Unblockable";
      const bh = 13;
      ctx.font = `bold ${Math.max(7, bh * 0.62)}px sans-serif`;
      const bw = Math.min(w - 4, Math.ceil(ctx.measureText(label).width) + 8);
      const bx = x + (w - bw) / 2;
      let by = y + 2;
      if (pileCount >= 2) by += 16;
      if (landOverride && String(card.type || "").toLowerCase().includes("land")) by += 15;
      if (indestructibleCard && indestructibleCard.is_indestructible) by += 15;
      if (colorOverride) by += 15;
      ctx.fillStyle = "rgba(24,86,104,0.9)";
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.fill();
      ctx.strokeStyle = "rgba(120,224,255,0.95)";
      ctx.lineWidth = 1;
      this._roundRect(ctx, bx, by, bw, bh, 3);
      ctx.stroke();
      ctx.fillStyle = "#d6f6ff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx + bw / 2, by + bh / 2);
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
      // Highlight an enchantment when a side-set aura attached to it is hovered.
      enchantTargetHover:
        this.hoveredKey != null &&
        this.stacks.some((s) => s.sideX && s.keys[0] === item.key && s.keys.indexOf(this.hoveredKey) > 0),
    };

    // Topmost (fully visible) card of a pile shows the pile size.
    const pile = this.stacks.find((s) => s.kind === "pile" && s.keys.length >= 2 && s.keys[s.keys.length - 1] === item.key);
    if (pile) flags.pileCount = pile.keys.length;

    // An aura fanned upward behind its enchanted permanent is occluded except
    // for its top strip — badges (counters) must anchor there to stay visible.
    flags.occludedAuraMember = this.stacks.some(
      (s) => s.kind === "aura" && !s.sideX && s.keys.indexOf(item.key) > 0
    );

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

  // Combat / targeting arrow: a gently bowed, tapered glowing shaft (wide at
  // the source, narrowing toward the head) with bright pulses traveling along
  // it. `opts.now` drives the pulse motion; `opts.phase` offsets it per arrow
  // so simultaneous arrows don't pulse in lockstep.
  _drawArrow(ctx, fx, fy, tx, ty, color, opts = {}) {
    const HEAD = 12 / this.zoom;
    const ANGLE = Math.PI / 6;
    const dx = tx - fx;
    const dy = ty - fy;
    const len = Math.hypot(dx, dy) || 1;
    const bow = Math.min(48, len * 0.18);
    const cpx = (fx + tx) / 2 + (-dy / len) * bow;
    const cpy = (fy + ty) / 2 + (dx / len) * bow;

    const point = (t) => {
      const mt = 1 - t;
      return {
        x: mt * mt * fx + 2 * mt * t * cpx + t * t * tx,
        y: mt * mt * fy + 2 * mt * t * cpy + t * t * ty,
      };
    };

    // The shaft stops just short of the head so the taper flows into it.
    const headT = Math.max(0.5, 1 - HEAD / len);
    const SEG = 16;
    const wideW = 5 / this.zoom;
    const narrowW = 1.6 / this.zoom;
    const left = [];
    const right = [];
    for (let i = 0; i <= SEG; i++) {
      const t = (i / SEG) * headT;
      const p = point(t);
      const ddx = 2 * (1 - t) * (cpx - fx) + 2 * t * (tx - cpx);
      const ddy = 2 * (1 - t) * (cpy - fy) + 2 * t * (ty - cpy);
      const dl = Math.hypot(ddx, ddy) || 1;
      const px = -ddy / dl;
      const py = ddx / dl;
      const halfW = (wideW + (narrowW - wideW) * t) / 2;
      left.push({ x: p.x + px * halfW, y: p.y + py * halfW });
      right.push({ x: p.x - px * halfW, y: p.y - py * halfW });
    }

    ctx.save();
    ctx.shadowColor = color;
    ctx.shadowBlur = 12 / this.zoom;
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.85;
    ctx.beginPath();
    ctx.moveTo(left[0].x, left[0].y);
    for (let i = 1; i < left.length; i++) ctx.lineTo(left[i].x, left[i].y);
    for (let i = right.length - 1; i >= 0; i--) ctx.lineTo(right[i].x, right[i].y);
    ctx.closePath();
    ctx.fill();

    // Arrowhead aligned with the curve's tangent at the target end.
    const angle = Math.atan2(ty - cpy, tx - cpx);
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - HEAD * Math.cos(angle - ANGLE), ty - HEAD * Math.sin(angle - ANGLE));
    ctx.lineTo(tx - HEAD * Math.cos(angle + ANGLE), ty - HEAD * Math.sin(angle + ANGLE));
    ctx.closePath();
    ctx.fill();

    // Traveling pulses: bright dots flowing source -> target.
    if (!this.reducedMotion) {
      const now = opts.now ?? performance.now();
      const phase = opts.phase || 0;
      const PULSES = 3;
      ctx.fillStyle = "rgba(255,255,255,0.95)";
      for (let i = 0; i < PULSES; i++) {
        const t = (now / 1200 + i / PULSES + phase) % 1;
        const p = point(t * headT);
        ctx.globalAlpha = 0.85 * (1 - 0.5 * t);
        ctx.beginPath();
        ctx.arc(p.x, p.y, (2.6 - 1.0 * t) / this.zoom, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  // A curved (bowed) connector with an arrowhead at the target end. Used to tie
  // a side-set aura back to the enchantment it is attached to. Pulses are
  // opt-in (hover only) so an idle board doesn't animate forever.
  _drawCurvedArrow(ctx, fx, fy, tx, ty, color, opts = {}) {
    const HEAD = 9 / this.zoom;
    const ANGLE = Math.PI / 6;
    const dx = tx - fx;
    const dy = ty - fy;
    const len = Math.hypot(dx, dy) || 1;
    // Bow the connector out perpendicular to its direction so it reads as a
    // curve rather than a straight combat-style line.
    const bow = Math.min(36, len * 0.4);
    const cpx = (fx + tx) / 2 + (-dy / len) * bow;
    const cpy = (fy + ty) / 2 + (dx / len) * bow;

    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2.5 / this.zoom;
    ctx.globalAlpha = 0.9;
    ctx.shadowColor = color;
    ctx.shadowBlur = 8 / this.zoom;
    ctx.beginPath();
    ctx.moveTo(fx, fy);
    ctx.quadraticCurveTo(cpx, cpy, tx, ty);
    ctx.stroke();
    // Arrowhead aligned with the curve's tangent at the target (pointing from
    // the control point toward the endpoint).
    const angle = Math.atan2(ty - cpy, tx - cpx);
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - HEAD * Math.cos(angle - ANGLE), ty - HEAD * Math.sin(angle - ANGLE));
    ctx.lineTo(tx - HEAD * Math.cos(angle + ANGLE), ty - HEAD * Math.sin(angle + ANGLE));
    ctx.closePath();
    ctx.fill();
    // Slow, faint traveling pulses along the connector (hover only).
    if (opts.pulse && !this.reducedMotion) {
      const now = opts.now ?? performance.now();
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      for (let i = 0; i < 2; i++) {
        const t = (now / 2000 + i / 2) % 1;
        const mt = 1 - t;
        const px = mt * mt * fx + 2 * mt * t * cpx + t * t * tx;
        const py = mt * mt * fy + 2 * mt * t * cpy + t * t * ty;
        ctx.globalAlpha = 0.6;
        ctx.beginPath();
        ctx.arc(px, py, 2 / this.zoom, 0, Math.PI * 2);
        ctx.fill();
      }
    }
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

  // ---------------------------------------------------------------------------
  // Mana-color fan (dual/multi land tap choice)
  // ---------------------------------------------------------------------------

  // Open the fan over the given battlefield card. `colors` is an ordered list of
  // { symbol, label } the land can produce; each becomes a clickable wedge.
  showManaFan(key, colors) {
    if (!key || !Array.isArray(colors) || colors.length === 0) return;
    this.manaFan = { key, colors: colors.slice(), start: performance.now(), hovered: -1 };
    this.needsRedraw = true;
  }

  hideManaFan() {
    if (!this.manaFan) return;
    this.manaFan = null;
    this.needsRedraw = true;
  }

  isManaFanOpen() {
    return !!this.manaFan;
  }

  // World-space layout of the fan: the card center plus, for each color, the
  // resting center of its token. Symbols fan upward in an arc above the card.
  // Returns null if the source card is no longer on the battlefield.
  _manaFanLayout() {
    if (!this.manaFan) return null;
    const center = this._cardCenter(this.manaFan.key);
    if (!center) return null;
    const colors = this.manaFan.colors;
    const n = colors.length;
    const up = -Math.PI / 2;
    const spread = Math.min(Math.PI * 0.92, Math.max(0.5, (n - 1) * 0.5));
    const items = colors.map((c, i) => {
      const a = n === 1 ? up : up - spread / 2 + (spread * i) / (n - 1);
      return {
        symbol: c.symbol,
        label: c.label,
        x: center.x + BF_MANA_FAN_RADIUS * Math.cos(a),
        y: center.y + BF_MANA_FAN_RADIUS * Math.sin(a),
      };
    });
    return { center, items };
  }

  // Index of the fan wedge under a world point, or -1.
  _manaFanHitIndex(wx, wy) {
    const layout = this._manaFanLayout();
    if (!layout) return -1;
    const r = BF_MANA_FAN_SYM_R * 1.12;
    for (let i = 0; i < layout.items.length; i++) {
      const it = layout.items[i];
      if ((wx - it.x) ** 2 + (wy - it.y) ** 2 <= r * r) return i;
    }
    return -1;
  }

  _drawManaFan(ctx, now) {
    const fan = this.manaFan;
    if (!fan) return;
    const layout = this._manaFanLayout();
    if (!layout) {
      // The source land left the battlefield mid-choice — abandon the fan.
      this.manaFan = null;
      if (this.onManaFanCancel) this.onManaFanCancel();
      return;
    }
    const elapsed = now - fan.start;

    // A soft pulsing tether ring around the source card sells the connection.
    const pulse = 0.5 + 0.5 * Math.sin(now / 320);
    ctx.save();
    ctx.strokeStyle = `rgba(126,196,255,${0.25 + 0.2 * pulse})`;
    ctx.lineWidth = 2 / this.zoom;
    ctx.beginPath();
    ctx.arc(layout.center.x, layout.center.y, BF_CARD_W * 0.46, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    layout.items.forEach((it, i) => {
      const p = Math.max(0, Math.min(1, (elapsed - i * BF_MANA_FAN_STAGGER) / BF_MANA_FAN_POP_MS));
      if (p <= 0) return;
      const e = _easeOutBack(p);
      // Travel out from the card center as it pops.
      const cx = _lerp(layout.center.x, it.x, Math.min(1, e));
      const cy = _lerp(layout.center.y, it.y, Math.min(1, e));
      const hovered = i === fan.hovered;
      const bob = hovered ? Math.sin(now / 220) * 0.8 : 0;
      const r = BF_MANA_FAN_SYM_R * (0.2 + 0.8 * Math.min(1, e)) * (hovered ? 1.16 : 1);
      const glow = BF_MANA_GLOW[it.symbol] || "#c2c6cf";

      ctx.save();
      ctx.globalAlpha = Math.min(1, p * 1.4);

      // Outer glow + dark token backing.
      ctx.shadowColor = glow;
      ctx.shadowBlur = (hovered ? 22 : 12) / this.zoom;
      ctx.fillStyle = "rgba(10,16,26,0.92)";
      ctx.beginPath();
      ctx.arc(cx, cy - bob, r, 0, Math.PI * 2);
      ctx.fill();

      // Colored rim.
      ctx.shadowBlur = 0;
      ctx.strokeStyle = glow;
      ctx.lineWidth = (hovered ? 3 : 2) / this.zoom;
      ctx.beginPath();
      ctx.arc(cx, cy - bob, r, 0, Math.PI * 2);
      ctx.stroke();

      // The mana symbol art, clipped inside the token.
      const img = this._loadImage(this._symbolSrc(`{${it.symbol}}`));
      if (img) {
        const s = r * 1.5;
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy - bob, r * 0.86, 0, Math.PI * 2);
        ctx.clip();
        ctx.drawImage(img, cx - s / 2, cy - bob - s / 2, s, s);
        ctx.restore();
      }
      ctx.restore();

      // Color name beneath the hovered wedge.
      if (hovered && it.label) {
        ctx.save();
        ctx.font = `600 ${12 / this.zoom}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        const ty = cy - bob + r + 6 / this.zoom;
        const tw = ctx.measureText(it.label).width;
        const pad = 5 / this.zoom;
        ctx.fillStyle = "rgba(12,20,32,0.85)";
        ctx.fillRect(cx - tw / 2 - pad, ty - 2 / this.zoom, tw + pad * 2, 16 / this.zoom);
        ctx.fillStyle = glow;
        ctx.fillText(it.label, cx, ty);
        ctx.restore();
      }
    });
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
  // once the game is over. (2-player only — see _priorityPulseSeat for the
  // seat-based version that also covers 3-4 player games.)
  _priorityPulseSide() {
    const seat = this._priorityPulseSeat();
    if (seat === null) return null;
    return seat === this.viewerSeat ? "you" : "opponent";
  }

  // Seat currently holding priority, or null if no seat should pulse (nobody
  // has priority, or the game is over). Valid for any player count.
  _priorityPulseSeat() {
    const st = this.currentState;
    if (!st || (st.winner !== null && st.winner !== undefined)) return null;
    const pp = st.priority_player;
    const n = Array.isArray(st.players) ? st.players.length : 0;
    if (!Number.isInteger(pp) || pp < 0 || pp >= n) return null;
    return pp;
  }

  _drawPriorityPulse(ctx, cw, ch, grid) {
    const pp = this._priorityPulseSeat();
    if (pp === null) return;
    const n = this.currentState?.players?.length || 0;
    const isYou = pp === this.viewerSeat;
    let xTop = 0;
    let xBot = cw;
    let yTop;
    let yBot;
    if (n <= 2) {
      const splitY = this.worldToCanvas(0, BF_WORLD_SPLIT_Y).y;
      yTop = isYou ? splitY : 0;
      yBot = isYou ? ch : splitY;
    } else {
      // 3-4 players: pulse just the priority-holder's own viewport rather
      // than an entire half, so the highlight points at the right seat.
      const region = this._regionForSeat(pp);
      if (!region) return;
      xTop = region.x;
      xBot = region.x + region.w;
      yTop = region.y;
      yBot = region.y + region.h;
    }
    if (yBot - yTop <= 1) return;
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 350);
    const alpha = 0.08 + pulse * 0.24;
    const color = isYou ? `rgba(74,222,128,${alpha})` : `rgba(248,82,82,${alpha})`;
    ctx.save();
    ctx.beginPath();
    ctx.rect(xTop, yTop, xBot - xTop, yBot - yTop);
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

    // ---- Table surface: a frosted glass pane ----
    // The fills below are translucent so the page's aurora glows through the
    // table (the wrap behind the canvas carries the backdrop blur); clear the
    // previous frame first or the translucency accumulates.
    ctx.clearRect(0, 0, cw, ch);
    // Vertical tint: darker toward the far (opponent) edge, lighter up close.
    const bgGrad = ctx.createLinearGradient(0, 0, 0, ch);
    bgGrad.addColorStop(0, "rgba(8, 13, 26, 0.55)");
    bgGrad.addColorStop(0.45, "rgba(16, 27, 46, 0.5)");
    bgGrad.addColorStop(1, "rgba(26, 41, 66, 0.46)");
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, cw, ch);

    // Soft center sheen
    const sheen = ctx.createRadialGradient(cw / 2, ch / 2, 0, cw / 2, ch / 2, Math.max(cw, ch) * 0.62);
    sheen.addColorStop(0, "rgba(126,196,255,0.09)");
    sheen.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = sheen;
    ctx.fillRect(0, 0, cw, ch);

    // Glass reflection: two faint diagonal streaks across the pane.
    const streak = ctx.createLinearGradient(0, 0, cw, ch);
    streak.addColorStop(0.0, "rgba(255,255,255,0)");
    streak.addColorStop(0.2, "rgba(255,255,255,0.045)");
    streak.addColorStop(0.3, "rgba(255,255,255,0)");
    streak.addColorStop(0.52, "rgba(255,255,255,0.03)");
    streak.addColorStop(0.66, "rgba(255,255,255,0)");
    ctx.fillStyle = streak;
    ctx.fillRect(0, 0, cw, ch);

    // Subtle grid: straight lines on the plane converge on screen under the
    // real 3D tilt, which is what visually sells the perspective. Etched-glass
    // white rather than a colored wireframe.
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
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

    // Edge vignette so the table fades out toward the stage borders — kept
    // light so the glass pane stays translucent at the edges.
    const vig = ctx.createRadialGradient(cw / 2, ch / 2, Math.min(cw, ch) * 0.38, cw / 2, ch / 2, Math.max(cw, ch) * 0.78);
    vig.addColorStop(0, "rgba(0,0,0,0)");
    vig.addColorStop(1, "rgba(0,0,0,0.3)");
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, cw, ch);

    // ---- Glowing separators between the player fields ----
    // 2 players: a single horizontal line at the world split, through the
    // global camera. 3-4 players: fixed screen-space viewport dividers — the
    // horizontal split plus a vertical boundary (top half only with 3
    // players, since the viewer owns the whole bottom; full height with 4).
    const ffa = this._isFfa();
    const regions = ffa ? this._regions() : null;
    const splitYc = ffa ? this._sepSplitY : this.worldToCanvas(0, BF_WORLD_SPLIT_Y).y;
    ctx.save();
    const lineGrad = ctx.createLinearGradient(0, 0, cw, 0);
    lineGrad.addColorStop(0, "rgba(126,196,255,0)");
    lineGrad.addColorStop(0.5, "rgba(126,196,255,0.45)");
    lineGrad.addColorStop(1, "rgba(126,196,255,0)");
    // Soft glow band
    ctx.fillStyle = lineGrad;
    ctx.globalAlpha = 0.16;
    ctx.fillRect(0, splitYc - 9, cw, 18);
    ctx.globalAlpha = 1;
    // Crisp core line
    ctx.strokeStyle = lineGrad;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, splitYc);
    ctx.lineTo(cw, splitYc);
    ctx.stroke();
    if (ffa) {
      const boundX = this._sepBoundX;
      const vBot = (this.currentState?.players?.length || 0) === 3 ? splitYc : ch;
      const vGrad = ctx.createLinearGradient(0, 0, 0, vBot);
      vGrad.addColorStop(0, "rgba(126,196,255,0)");
      vGrad.addColorStop(0.5, "rgba(126,196,255,0.45)");
      vGrad.addColorStop(1, "rgba(126,196,255,0)");
      ctx.fillStyle = vGrad;
      ctx.globalAlpha = 0.16;
      ctx.fillRect(boundX - 9, 0, 18, vBot);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = vGrad;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(boundX, 0);
      ctx.lineTo(boundX, vBot);
      ctx.stroke();
    }
    ctx.restore();

    // Button hit-rects are rebuilt during drawing (possibly across several
    // viewport passes in FFA), so reset them once per frame here.
    this._riverButtonRects = [];
    this._camoButtonRects = [];

    if (!ffa) {
      // Apply camera transform for world-space drawing
      ctx.save();
      ctx.translate(this.camX, this.camY);
      ctx.scale(this.zoom, this.zoom);
      this._drawWorldContent(ctx, null);

      // ---- Combat damage fx (ghosts, beams, chevrons, hit flashes, tickers) ----
      this._drawCombatFx(ctx, performance.now(), null);

      // ---- Spell stack zone and cast/resolve animations (drawn on top) ----
      this._drawStackAndFx(ctx, this.fxAnims);

      // ---- Mana-color fan, above everything so its wedges are clickable ----
      this._drawManaFan(ctx, performance.now());

      ctx.restore(); // camera
    } else {
      // ---- FFA: one clipped pass per seat viewport, each through its own
      // camera, so every quadrant frames its own content independently. ----
      const fanSeat = this._manaFanRegionSeat();
      for (const region of regions) {
        const cam = this._camFor(region.seat);
        ctx.save();
        ctx.beginPath();
        ctx.rect(region.x, region.y, region.w, region.h);
        ctx.clip();
        ctx.translate(cam.x, cam.y);
        ctx.scale(cam.zoom, cam.zoom);
        this._withCam(cam, () => {
          this._drawWorldContent(ctx, region.seat);
          this._drawCombatFx(ctx, performance.now(), region.seat);
          if (fanSeat === region.seat) this._drawManaFan(ctx, performance.now());
        });
        ctx.restore();
      }

      // Combat / drag arrows span quadrants, so they draw once in screen
      // space above every viewport (each endpoint mapped through its own
      // quadrant's camera).
      this._drawArrowsOverlay(ctx);

      // Stack cascade + overlay-space fx, unclipped above every viewport,
      // through the viewer's camera.
      const overlayCam = this._camFor(this.viewerSeat);
      ctx.save();
      ctx.translate(overlayCam.x, overlayCam.y);
      ctx.scale(overlayCam.zoom, overlayCam.zoom);
      this._withCam(overlayCam, () =>
        this._drawStackAndFx(ctx, this.fxAnims.filter((fx) => fx.camSeat == null))
      );
      ctx.restore();

      // Seat-space fx (resolve flights, land entrances, fizzles, impact
      // rings) play in their destination viewport's camera, unclipped so a
      // card flying from the stack stays visible while crossing viewports.
      const fxSeats = [...new Set(this.fxAnims.filter((fx) => fx.camSeat != null).map((fx) => fx.camSeat))];
      for (const seat of fxSeats) {
        const cam = this._camFor(seat);
        ctx.save();
        ctx.translate(cam.x, cam.y);
        ctx.scale(cam.zoom, cam.zoom);
        this._withCam(cam, () => this._drawFxAnims(ctx, this.fxAnims.filter((fx) => fx.camSeat === seat)));
        ctx.restore();
      }
    }
  }

  // The world-space battlefield scene: cards, emblems, zone piles, aura
  // connectors, combat arrows/bands, Raging River / Camouflage overlays and
  // the live blocker drag arrow. Runs inside a camera transform. regionSeat
  // (FFA) restricts drawing to content belonging to that seat's viewport;
  // null (2-player) draws everything.
  _drawWorldContent(ctx, regionSeat) {
    // ---- Draw all cards (stacked items render on top due to sort order) ----
    for (const item of this.cardItems) {
      if (regionSeat !== null && this._itemRegionSeat(item) !== regionSeat) continue;
      this._drawCard(ctx, item);
    }

    // ---- Draw the viewer's emblem tokens (orange-bordered ability markers) ----
    if (regionSeat === null || regionSeat === this.viewerSeat) {
      for (const item of this.emblemItems) {
        this._drawEmblem(ctx, item);
      }
    }

    // ---- Library / graveyard / exile piles along the left edge ----
    this._drawZonePiles(ctx, regionSeat);

    // ---- Aura→enchantment connectors (auras set beside their target) ----
    for (const stack of this.stacks) {
      if (!stack.sideX || stack.keys.length < 2) continue;
      const targetKey = stack.keys[0];
      if (regionSeat !== null) {
        const tItem0 = this.cardItems.find((c) => c.key === targetKey);
        if (!tItem0 || this._itemRegionSeat(tItem0) !== regionSeat) continue;
      }
      const tPos = this._renderPos(targetKey);
      if (!tPos) continue;
      // When the target enchantment is itself fanned up behind a creature, only
      // its top edge shows; aim the arrow there (and inset only slightly on that
      // end) so it clearly points at the enchantment rather than the creature
      // sitting on top of it. Otherwise aim at the card's center.
      const tItem = this.cardItems.find((c) => c.key === targetKey);
      const targetBehind =
        !tItem?.card?.tapped &&
        this.stacks.some((s) => s.kind === "aura" && !s.sideX && s.keys.indexOf(targetKey) > 0);
      const tc = targetBehind
        ? { x: tPos.x + BF_CARD_W / 2, y: tPos.y + BF_CARD_H * 0.11 }
        : this._cardCenter(targetKey);
      if (!tc) continue;
      // Pulse the connector only while its aura or target is hovered — hover
      // already keeps the frame loop redrawing, so an idle board stays idle.
      const auraHovered =
        this.hoveredKey != null && stack.keys.includes(this.hoveredKey);
      for (let i = 1; i < stack.keys.length; i++) {
        const fc = this._cardCenter(stack.keys[i]);
        if (!fc) continue;
        // Inset the aura end to its facing edge so the arrow spans the gap; inset
        // the target end only a little when aiming at the exposed top sliver.
        const dx = tc.x - fc.x;
        const dy = tc.y - fc.y;
        const d = Math.hypot(dx, dy) || 1;
        const fromInset = BF_CARD_W * 0.46;
        const toInset = targetBehind ? 6 : BF_CARD_W * 0.46;
        this._drawCurvedArrow(
          ctx,
          fc.x + (dx / d) * fromInset,
          fc.y + (dy / d) * fromInset,
          tc.x - (dx / d) * toInset,
          tc.y - (dy / d) * toInset,
          this.theme.arrowAura,
          { pulse: auraHovered }
        );
      }
    }

    // ---- Combat arrows (FFA draws these in a screen-space pass above every
    // quadrant instead — see _drawArrowsOverlay — because each quadrant's
    // independent camera would place the far endpoint wrongly and clip the
    // arrow away) ----
    if (regionSeat === null) {
      for (const arrow of this.combatArrows) {
        const fromKey = `${arrow.fromSeat}-${arrow.fromIdx}`;
        const fc = this._cardCenter(fromKey);
        const tc = this._cardCenter(`${arrow.toSeat}-${arrow.toIdx}`);
        if (fc && tc) {
          this._drawArrow(ctx, fc.x, fc.y, tc.x, tc.y,
            arrow.kind === "blocker" ? this.theme.arrowBlock : this.theme.arrowAttack,
            { phase: _keyPhase(fromKey) / (Math.PI * 2) });
        }
      }
    }

    // ---- Attacking bands (CR 702.22): purple links connecting band members ----
    for (const band of this.combatBands) {
      if (regionSeat !== null && band.length && band[0].seat !== regionSeat) continue;
      const centers = band
        .map((m) => this._cardCenter(`${m.seat}-${m.idx}`))
        .filter(Boolean);
      if (centers.length < 2) continue;
      const hoverKeys = this._bandKeysForHover();
      const isHoveredBand = hoverKeys && band.some((m) => hoverKeys.has(`${m.seat}-${m.idx}`));
      ctx.save();
      ctx.strokeStyle = isHoveredBand ? "#d090ff" : "#9a4fd0";
      ctx.lineWidth = (isHoveredBand ? 3.5 : 2.25) / this.zoom;
      ctx.setLineDash([8 / this.zoom, 5 / this.zoom]);
      ctx.shadowColor = "#9a4fd0";
      ctx.shadowBlur = (isHoveredBand ? 16 : 8) / this.zoom;
      ctx.beginPath();
      ctx.moveTo(centers[0].x, centers[0].y);
      for (let i = 1; i < centers.length; i++) ctx.lineTo(centers[i].x, centers[i].y);
      ctx.stroke();
      // A small filled node at each member to read as a "band".
      ctx.setLineDash([]);
      for (const c of centers) {
        ctx.beginPath();
        ctx.arc(c.x, c.y, (isHoveredBand ? 5 : 3.5) / this.zoom, 0, Math.PI * 2);
        ctx.fillStyle = isHoveredBand ? "#d090ff" : "#9a4fd0";
        ctx.fill();
      }
      ctx.restore();
    }

    // ---- Raging River: pile dividers, side badges, and Left/Right buttons ----
    this._drawRiver(ctx, regionSeat);
    this._drawCamouflage(ctx, regionSeat);

    // ---- Live blocker-assignment drag arrow (FFA: drawn by
    // _drawArrowsOverlay in screen space instead, for the same reason as the
    // combat arrows above) ----
    if (regionSeat === null && this.pressState?.combatDrag) {
      const fc = this._cardCenter(this.pressState.key);
      const tw = this.canvasToWorld(this.pressState.currentCX, this.pressState.currentCY);
      if (fc) {
        this._drawArrow(ctx, fc.x, fc.y, tw.x, tw.y, this.theme.arrowDrag);
      }
    }
  }

  // FFA: combat arrows and the live blocker drag arrow, drawn once in screen
  // space above every quadrant viewport (unclipped). Each endpoint maps
  // through the camera of the quadrant its card renders in, so an arrow
  // crossing quadrants connects the two cards' actual on-screen positions —
  // re-drawing it inside each quadrant pass would place the far endpoint via
  // the wrong camera and clip most of the arrow away.
  _drawArrowsOverlay(ctx) {
    const screenCenter = (key) => {
      const item = this.cardItems.find((c) => c.key === key);
      if (!item) return null;
      const wc = this._cardCenter(key);
      if (!wc) return null;
      const cam = this._camFor(this._itemRegionSeat(item));
      return this._withCam(cam, () => this.worldToCanvas(wc.x, wc.y));
    };
    // Identity camera registers so _drawArrow's /zoom sizing is screen-constant.
    const screenCam = { x: 0, y: 0, zoom: 1 };
    for (const arrow of this.combatArrows) {
      const fromKey = `${arrow.fromSeat}-${arrow.fromIdx}`;
      const fc = screenCenter(fromKey);
      const tc = screenCenter(`${arrow.toSeat}-${arrow.toIdx}`);
      if (fc && tc) {
        this._withCam(screenCam, () =>
          this._drawArrow(ctx, fc.x, fc.y, tc.x, tc.y,
            arrow.kind === "blocker" ? this.theme.arrowBlock : this.theme.arrowAttack,
            { phase: _keyPhase(fromKey) / (Math.PI * 2) })
        );
      }
    }
    if (this.pressState?.combatDrag) {
      const fc = screenCenter(this.pressState.key);
      if (fc) {
        this._withCam(screenCam, () =>
          this._drawArrow(ctx, fc.x, fc.y, this.pressState.currentCX, this.pressState.currentCY, this.theme.arrowDrag)
        );
      }
    }
    this._drawStackTargetArrows(ctx, true);
  }

  // Animated arrows from the hovered stack card to everything it targets
  // (CR 115): each permanent, player, graveyard card or spell-on-the-stack it
  // chose, serialized by the web layer as item.targets. Split the same way the
  // combat arrows are — 2-player draws in world space inside the stack pass,
  // FFA in screen space from _drawArrowsOverlay — because the cascade rides the
  // viewer's camera while its targets live in their own quadrants'.
  _drawStackTargetArrows(ctx, screenSpace) {
    const v = this.hoveredStackIndex != null ? this.stackVisuals[this.hoveredStackIndex] : null;
    const targets = v?.item?.targets;
    if (!v || !Array.isArray(targets) || !targets.length) return;
    const viewerCam = this._camFor(this.viewerSeat);
    const from = screenSpace
      ? this._withCam(viewerCam, () => this.worldToCanvas(v.cx, v.cy))
      : { x: v.cx, y: v.cy };
    // Half the stack card, in whichever space we're drawing in.
    const fromR = BF_CARD_W * v.scale * 0.5 * (screenSpace ? viewerCam.zoom : 1);
    // An identity camera keeps _drawArrow's /zoom sizing screen-constant.
    const screenCam = { x: 0, y: 0, zoom: 1 };
    const now = performance.now();
    let drew = false;
    targets.forEach((t, i) => {
      const to = this._stackTargetAnchor(t, screenSpace);
      if (!to) return;
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const d = Math.hypot(dx, dy);
      if (!d) return;
      // Both ends inset to their card edges so the head points at the target
      // instead of burying itself in the art — capped at a third of the span
      // each so a near target (the cascade card right below a Counterspell)
      // still gets a short arrow rather than an inside-out one.
      const cap = d / 3;
      const fi = Math.min(fromR, cap);
      const ti = Math.min(to.r, cap);
      const draw = () =>
        this._drawArrow(
          ctx,
          from.x + (dx / d) * fi,
          from.y + (dy / d) * fi,
          to.x - (dx / d) * ti,
          to.y - (dy / d) * ti,
          this.theme.arrowTarget,
          { now, phase: i / targets.length }
        );
      if (screenSpace) this._withCam(screenCam, draw);
      else draw();
      drew = true;
    });
    // The traveling pulses animate, so keep the frame loop alive while hovering.
    if (drew && !this.reducedMotion) this.needsRedraw = true;
  }

  // Endpoint for one entry of a stack item's `targets` list: {x, y, r}, where r
  // is how far short of the point the arrowhead should stop. Coordinates come
  // back in screen space (screenSpace, each endpoint mapped through the camera
  // of the viewport it renders in) or in the active camera's world space.
  _stackTargetAnchor(t, screenSpace) {
    const project = (seat, p, r) => {
      if (!p) return null;
      const cam = this._camFor(seat);
      if (!screenSpace) return { x: p.x, y: p.y, r };
      const s = this._withCam(cam, () => this.worldToCanvas(p.x, p.y));
      return { x: s.x, y: s.y, r: r * cam.zoom };
    };
    if (t.kind === "permanent") {
      const key = `${t.seat}-${t.index}`;
      const item = this.cardItems.find((c) => c.key === key);
      if (!item) return null;
      return project(this._itemRegionSeat(item), this._cardCenter(key), BF_CARD_W * 0.46);
    }
    if (t.kind === "graveyard") {
      const pile = this.zonePiles.find((p) => p.seat === t.seat && p.kind === "graveyard");
      if (!pile) return null;
      return project(t.seat, { x: pile.cx, y: pile.cy }, (pile.w || BF_CARD_W) * 0.5);
    }
    if (t.kind === "stack") {
      // Another spell in the cascade (Counterspell, Fork) — same space as the
      // hovered card, so it needs the viewer's camera like the origin does.
      const tv = this.stackVisuals[t.index];
      if (!tv) return null;
      return project(this.viewerSeat, { x: tv.cx, y: tv.cy }, BF_CARD_W * tv.scale * 0.5);
    }
    if (t.kind === "player") {
      // Players have no canvas presence: aim at their DOM life pill, projected
      // back onto the canvas plane the way _castOrigin does for hand fans.
      const el = this._playerAnchorEl(t.seat);
      const r = el?.getBoundingClientRect();
      if (!r || (!r.width && !r.height)) return null;
      const c = this._pageToCanvas(r.left + r.width / 2, r.top + r.height / 2);
      if (screenSpace) return { x: c.x, y: c.y, r: 24 };
      const w = this.canvasToWorld(c.x, c.y);
      return { x: w.x, y: w.y, r: 24 / this.zoom };
    }
    return null;
  }

  // The DOM life pill standing in for a seat on screen: #selfLife for the
  // viewer, #oppLife for the classic (top-left) opponent, per-seat #ffaLife_<n>
  // for the remaining Free-For-All seats (see app.js renderFfaOpponentPanels).
  _playerAnchorEl(seat) {
    if (seat === this.viewerSeat) return document.getElementById("selfLife");
    const n = this.currentState?.players?.length || 0;
    if (n <= 2 || seat === this._classicOppSeat()) return document.getElementById("oppLife");
    return document.getElementById(`ffaLife_${seat}`);
  }

  // Which seat's viewport the open mana fan belongs to (the quadrant of its
  // source land), or null when no fan is open.
  _manaFanRegionSeat() {
    if (!this.manaFan) return null;
    const item = this.cardItems.find((c) => c.key === this.manaFan.key);
    return item ? this._itemRegionSeat(item) : this.viewerSeat;
  }

  // Raging River (CR 702): draw the left/right divider + side badges for committed
  // piles, and the Left/Right choice buttons above the viewer's pending creatures.
  // Runs inside the camera transform so everything sits in world space; in FFA
  // regionSeat restricts drawing to the pass of the seat that owns each piece.
  // (_riverButtonRects is reset once per frame by _render, since in FFA this
  // runs once per viewport pass.)
  _drawRiver(ctx, regionSeat = null) {
    const r = this.river;
    if (!r || !r.active) return;

    // --- Divider channel + LEFT/RIGHT captions for each committed cluster ---
    for (const cl of this._riverClusters || []) {
      if (regionSeat !== null && cl.seat !== regionSeat) continue;
      const keys = [...cl.leftKeys, ...cl.rightKeys];
      let top = Infinity;
      let bot = -Infinity;
      for (const k of keys) {
        const pos = this._renderPos(k);
        if (!pos) continue;
        const b = this._boundsAt(k, pos);
        top = Math.min(top, b.y);
        bot = Math.max(bot, b.y + b.h);
      }
      if (!isFinite(top)) continue;
      top -= 16;
      bot += 10;
      ctx.save();
      ctx.strokeStyle = "rgba(120,180,255,0.5)";
      ctx.lineWidth = 2 / this.zoom;
      ctx.setLineDash([10 / this.zoom, 7 / this.zoom]);
      ctx.beginPath();
      ctx.moveTo(cl.center, top);
      ctx.lineTo(cl.center, bot);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = `700 ${13 / this.zoom}px sans-serif`;
      ctx.textBaseline = "bottom";
      if (cl.leftKeys.length) {
        ctx.textAlign = "right";
        ctx.fillStyle = "#7fb6ff";
        ctx.fillText("◄ LEFT", cl.center - 12 / this.zoom, top - 2 / this.zoom);
      }
      if (cl.rightKeys.length) {
        ctx.textAlign = "left";
        ctx.fillStyle = "#ffce6b";
        ctx.fillText("RIGHT ►", cl.center + 12 / this.zoom, top - 2 / this.zoom);
      }
      ctx.restore();
    }

    // --- Per-creature side badges for committed piles ---
    for (const item of this.cardItems) {
      if (regionSeat !== null && this._itemRegionSeat(item) !== regionSeat) continue;
      const side = this._riverSideForKey(item.seat, item.idx);
      if (!side) continue;
      const pos = this._renderPos(item.key);
      if (!pos) continue;
      const b = this._boundsAt(item.key, pos);
      this._drawRiverBadge(ctx, b.x + b.w / 2, b.y + 11 / this.zoom, side);
    }

    // --- Left/Right choice buttons above the viewer's own pending creatures ---
    const prompt = r.prompt;
    if (prompt && Array.isArray(prompt.items) && (regionSeat === null || prompt.seat === regionSeat)) {
      for (const it of prompt.items) {
        const key = `${prompt.seat}-${it.idx}`;
        const pos = this._renderPos(key);
        if (!pos) continue;
        const b = this._boundsAt(key, pos);
        const chosen = prompt.selection ? prompt.selection[it.idx] : null;
        const bh = 26 / this.zoom;
        const by = b.y - bh - 10 / this.zoom;
        const halfW = (b.w - 6 / this.zoom) / 2;
        const leftRect = { key, seat: prompt.seat, idx: it.idx, side: "left", x: b.x, y: by, w: halfW, h: bh };
        const rightRect = { key, seat: prompt.seat, idx: it.idx, side: "right", x: b.x + b.w - halfW, y: by, w: halfW, h: bh };
        this._drawRiverButton(ctx, leftRect, "◄ L", chosen === "left", "#4a90d9");
        this._drawRiverButton(ctx, rightRect, "R ►", chosen === "right", "#e0a23b");
        this._riverButtonRects.push(leftRect, rightRect);
      }
    }
  }

  _drawRiverBadge(ctx, cx, cy, side) {
    const isLeft = side === "left";
    const label = isLeft ? "LEFT" : "RIGHT";
    const color = isLeft ? "#3f7fce" : "#d2912f";
    ctx.save();
    ctx.font = `700 ${10 / this.zoom}px sans-serif`;
    const tw = ctx.measureText(label).width;
    const padX = 6 / this.zoom;
    const w = tw + padX * 2;
    const h = 15 / this.zoom;
    ctx.fillStyle = color;
    ctx.shadowColor = "rgba(0,0,0,0.55)";
    ctx.shadowBlur = 4 / this.zoom;
    this._roundRect(ctx, cx - w / 2, cy - h / 2, w, h, 4 / this.zoom);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, cx, cy + 0.5 / this.zoom);
    ctx.restore();
  }

  _drawRiverButton(ctx, rect, label, selected, color) {
    ctx.save();
    ctx.fillStyle = selected ? color : "rgba(16,24,36,0.94)";
    ctx.strokeStyle = color;
    ctx.lineWidth = 2 / this.zoom;
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.shadowBlur = 6 / this.zoom;
    this._roundRect(ctx, rect.x, rect.y, rect.w, rect.h, 5 / this.zoom);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.stroke();
    ctx.fillStyle = selected ? "#0b1118" : color;
    ctx.font = `700 ${13 / this.zoom}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, rect.x + rect.w / 2, rect.y + rect.h / 2 + 0.5 / this.zoom);
    ctx.restore();
  }

  // Hit-test the Raging River Left/Right buttons (world coords). Returns the
  // matching button rect (with seat/idx/side) or null.
  _hitTestRiverButton(wx, wy) {
    for (const b of this._riverButtonRects) {
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) return b;
    }
    return null;
  }

  // Camouflage: draw a row of pile buttons (✕ = no pile, then 1..N) above each
  // of the defending player's untapped creatures. Runs inside the camera
  // transform so everything sits in world space. (_camoButtonRects is reset
  // once per frame by _render, since in FFA this runs once per viewport pass.)
  _drawCamouflage(ctx, regionSeat = null) {
    const c = this.camouflage;
    if (!c || !c.active || !Array.isArray(c.items)) return;
    if (regionSeat !== null && c.seat !== regionSeat) return;

    const options = ["none"];
    for (let p = 0; p < c.pileCount; p++) options.push(p);
    for (const it of c.items) {
      const key = `${c.seat}-${it.idx}`;
      const pos = this._renderPos(key);
      if (!pos) continue;
      const b = this._boundsAt(key, pos);
      const chosen = c.selection ? c.selection[it.idx] : undefined;
      const bh = 26 / this.zoom;
      const by = b.y - bh - 10 / this.zoom;
      const gap = 4 / this.zoom;
      // Keep every button tappable even with many piles: let the row overflow
      // the card horizontally (centered) rather than shrink below a floor.
      const minW = 24 / this.zoom;
      const bw = Math.max(minW, (b.w - gap * (options.length - 1)) / options.length);
      const rowW = bw * options.length + gap * (options.length - 1);
      const startX = b.x + b.w / 2 - rowW / 2;
      options.forEach((opt, i) => {
        const rect = {
          key, seat: c.seat, idx: it.idx, pile: opt,
          x: startX + i * (bw + gap), y: by, w: bw, h: bh,
        };
        const isNone = opt === "none";
        const label = isNone ? "✕" : String(opt + 1);
        const color = isNone ? "#8b95a5" : _CAMO_PILE_COLORS[opt % _CAMO_PILE_COLORS.length];
        this._drawRiverButton(ctx, rect, label, chosen === opt, color);
        this._camoButtonRects.push(rect);
      });
    }
  }

  // Hit-test the Camouflage pile buttons (world coords). Returns the matching
  // button rect (with seat/idx/pile) or null.
  _hitTestCamoButton(wx, wy) {
    for (const b of this._camoButtonRects) {
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) return b;
    }
    return null;
  }

  // regionSeat (FFA): draw only fx involving that seat's creatures (or, for
  // beams, either endpoint — a cross-viewport beam draws in both passes, each
  // clipped to its own side so both endpoints anchor correctly).
  _combatFxInRegion(fx, regionSeat) {
    if (fx.kind === "beam") {
      const toSeat = fx.toRef ? fx.toRef.seat : fx.toPlayerSeat;
      return fx.fromRef.seat === regionSeat || toSeat === regionSeat;
    }
    return fx.ref.seat === regionSeat;
  }

  _drawCombatFx(ctx, now, regionSeat = null) {
    if (!this.combatFx.length) return;
    const ordered = [...this.combatFx].sort(
      (a, b) => (_COMBAT_FX_DRAW_ORDER[a.kind] || 0) - (_COMBAT_FX_DRAW_ORDER[b.kind] || 0)
    );
    for (const fx of ordered) {
      if (regionSeat !== null && !this._combatFxInRegion(fx, regionSeat)) continue;
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

  // Draws the stack cascade plus the given subset of fxAnims (all of them in
  // 2-player games; only the overlay-space ones in FFA, where seat-space fx
  // draw in their own camera pass via _drawFxAnims).
  _drawStackAndFx(ctx, fxList) {
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

    // Targeting arrows under the cascade (FFA draws them in screen space from
    // _drawArrowsOverlay instead — see _drawStackTargetArrows), so they lie
    // over the board but never across the stack cards themselves.
    if (!this._isFfa()) this._drawStackTargetArrows(ctx, false);

    // Bottom of the stack first; the top spell (next to resolve) draws on
    // top. The hovered card grows, so it draws above everything else.
    for (let i = this.stackVisuals.length - 1; i >= 0; i--) {
      if (i === this.hoveredStackIndex) continue;
      const v = this.stackVisuals[i];
      this._drawFloatingCard(ctx, v.item?.card, v.cx, v.cy, v.scale, 1, i === this.stackHeldIndex);
      this._drawStackTargetableGlow(ctx, v, i);
    }
    const hoveredVisual = this.hoveredStackIndex != null ? this.stackVisuals[this.hoveredStackIndex] : null;
    if (hoveredVisual) {
      this._drawFloatingCard(ctx, hoveredVisual.item?.card, hoveredVisual.cx, hoveredVisual.cy, hoveredVisual.scale, 1, true);
      this._drawStackTargetableGlow(ctx, hoveredVisual, this.hoveredStackIndex);
    }

    this._drawStackHoldUi(ctx);

    this._drawFxAnims(ctx, fxList);
  }

  _drawFxAnims(ctx, list) {
    for (const fx of list) {
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

  // Gold pulsing border on stack-cascade cards that are legal targets for the
  // in-progress cast (Counterspell, Fork) — the canvas replacement for the
  // old sidebar stack panel's .stack-targetable highlight.
  _drawStackTargetableGlow(ctx, v, index) {
    if (!this.stackTargetableIndices || !this.stackTargetableIndices.has(index)) return;
    const w = BF_CARD_W * v.scale;
    const h = BF_CARD_H * v.scale;
    const pulse = 0.55 + 0.45 * Math.sin(performance.now() / 300);
    ctx.save();
    ctx.strokeStyle = `rgba(255, 215, 106, ${0.5 + 0.5 * pulse})`;
    ctx.lineWidth = 3 / this.zoom;
    ctx.shadowColor = "#ffd76a";
    ctx.shadowBlur = (10 + 8 * pulse) / this.zoom;
    ctx.strokeRect(v.cx - w / 2, v.cy - h / 2, w, h);
    ctx.restore();
    this.needsRedraw = true;
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
    if (labelVisual) {
      const text = labelIndex === this.stackHeldIndex
        ? "Priority held — click to release"
        : "Click to hold priority";
      // Centered directly above the labeled card, clear of the prompt dock that
      // now sits to the stack's left.
      const h = BF_CARD_H * labelVisual.scale;
      this._drawStackBadge(ctx, labelVisual.cx, labelVisual.cy - h / 2 - 16 / this.zoom, text, "rgba(126, 196, 255, 0.95)");
    }

    // Another player is sitting on priority (e.g. holding it by hovering the
    // stack on their client): badge the top stack card with who everyone is
    // waiting on. Drawn only after a short dwell so ordinary quick priority
    // hand-offs don't flash the label.
    const waiting = this.stackWaitingLabel;
    if (waiting && this.stackVisuals.length) {
      if (performance.now() - waiting.since < 900) {
        this.needsRedraw = true; // keep the rAF loop checking until it's due
        return;
      }
      const top = this.stackVisuals[0];
      const h = BF_CARD_H * top.scale;
      // Sits one row above the hover hint when that hint occupies the top card.
      const lift = labelVisual === top ? 42 / this.zoom : 16 / this.zoom;
      this._drawStackBadge(ctx, top.cx, top.cy - h / 2 - lift, `Waiting for ${waiting.name}…`, "rgba(255, 215, 106, 0.95)");
    }
  }

  // Small dark pill with centered text, used for the stack-cascade badges.
  _drawStackBadge(ctx, tx, ty, text, color) {
    ctx.save();
    ctx.font = `600 ${13 / this.zoom}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const pad = 6 / this.zoom;
    const tw = ctx.measureText(text).width;
    const th = 18 / this.zoom;
    ctx.fillStyle = "rgba(12, 20, 32, 0.82)";
    ctx.fillRect(tx - tw / 2 - pad, ty - th / 2 - pad / 2, tw + pad * 2, th + pad);
    ctx.fillStyle = color;
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
      this._drawCardFace(ctx, -w / 2, -h / 2, w, h, card, { hovered: !!lifted, fullImage: true });
    } else {
      this._drawCardFace(ctx, cx - w / 2, cy - h / 2, w, h, card, { hovered: !!lifted, fullImage: true });
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
    const pt = this._pointerContext(event.clientX, event.clientY);
    const { cx, cy, world } = pt;
    const regionSeat = pt.region ? pt.region.seat : null;

    // The mana fan is modal while open: it captures every press, so a wedge
    // picks a color and a press anywhere else dismisses it.
    if (this.manaFan) {
      const fanWorld = this._manaFanWorldPoint(cx, cy);
      this.pressState = {
        manaFan: true,
        manaFanIndex: this._manaFanHitIndex(fanWorld.x, fanWorld.y),
        startCX: cx, startCY: cy, currentCX: cx, currentCY: cy,
        cancelled: false,
      };
      return;
    }

    // Raging River Left/Right buttons float above their creature and win the press.
    const riverHit = this._hitTestRiverButton(world.x, world.y);
    if (riverHit) {
      this.pressState = {
        riverButton: { seat: riverHit.seat, idx: riverHit.idx, side: riverHit.side },
        key: null, seat: null, idx: null, card: null,
        startCX: cx, startCY: cy, currentCX: cx, currentCY: cy,
        combatDrag: false, cancelled: false,
      };
      return;
    }

    // Camouflage pile buttons likewise float above their creature.
    const camoHit = this._hitTestCamoButton(world.x, world.y);
    if (camoHit) {
      this.pressState = {
        camoButton: { seat: camoHit.seat, idx: camoHit.idx, pile: camoHit.pile },
        key: null, seat: null, idx: null, card: null,
        startCX: cx, startCY: cy, currentCX: cx, currentCY: cy,
        combatDrag: false, cancelled: false,
      };
      return;
    }

    // Floating stack cards draw above the battlefield, so they win the press.
    const stackHit = this._hitTestStack(pt.overlayWorld.x, pt.overlayWorld.y);
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

    // Zone piles are pinned to the view above battlefield cards.
    const zoneHit = this._hitTestZonePile(world.x, world.y, regionSeat);
    if (zoneHit) {
      this.pressState = {
        zonePile: { seat: zoneHit.seat, kind: zoneHit.kind },
        key: null, seat: null, idx: null, card: null,
        startCX: cx, startCY: cy, currentCX: cx, currentCY: cy,
        combatDrag: false, cancelled: false,
      };
      return;
    }

    // Emblems only render in the viewer's viewport.
    const emblemHit = regionSeat === null || regionSeat === this.viewerSeat
      ? this._hitTestEmblem(world.x, world.y)
      : null;
    if (emblemHit) {
      this.pressState = {
        key: null,
        seat: null,
        idx: null,
        card: null,
        emblemIndex: emblemHit.index,
        emblem: emblemHit.emblem,
        startCX: cx,
        startCY: cy,
        currentCX: cx,
        currentCY: cy,
        combatDrag: false,
        cancelled: false,
      };
      return;
    }

    const item = this._hitTest(world.x, world.y, regionSeat);
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
    const pt = this._pointerContext(event.clientX, event.clientY);
    const { cx, cy, world } = pt;
    const regionSeat = pt.region ? pt.region.seat : null;

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

    // The mana fan, while open, owns hover: highlight the wedge under the
    // cursor and suppress card/stack hover beneath it.
    if (this.manaFan) {
      const fanWorld = this._manaFanWorldPoint(cx, cy);
      const idx = this._manaFanHitIndex(fanWorld.x, fanWorld.y);
      if (idx !== this.manaFan.hovered) {
        this.manaFan.hovered = idx;
        this.needsRedraw = true;
      }
      this.canvas.style.cursor = idx >= 0 ? "pointer" : "default";
      return;
    }

    // Raging River buttons sit above their creature and take pointer priority.
    if (this._hitTestRiverButton(world.x, world.y)) {
      this.canvas.style.cursor = "pointer";
      return;
    }

    // Hover — the floating stack cascade sits above battlefield cards.
    const stackHit = this._updateStackHover(pt.overlayWorld.x, pt.overlayWorld.y);

    // Zone piles are pinned to the view, above battlefield cards and emblems.
    const zoneHit = stackHit ? null : this._hitTestZonePile(world.x, world.y, regionSeat);
    const newZonePile = zoneHit ? { seat: zoneHit.seat, kind: zoneHit.kind } : null;
    const zoneChanged =
      (newZonePile?.seat !== this.hoveredZonePile?.seat) ||
      (newZonePile?.kind !== this.hoveredZonePile?.kind);
    if (zoneChanged) {
      this.hoveredZonePile = newZonePile;
      this.needsRedraw = true;
      if (this.onZonePileHover) {
        this.onZonePileHover(
          zoneHit ? { seat: zoneHit.seat, kind: zoneHit.kind, topCard: zoneHit.topCard, count: zoneHit.count } : null
        );
      }
    }

    const emblemHit =
      stackHit || zoneHit || (regionSeat !== null && regionSeat !== this.viewerSeat)
        ? null
        : this._hitTestEmblem(world.x, world.y);
    // The shield badge sits on top of its card, so it wins over the card's own
    // hover preview — but yields to the stack cascade and emblems above it.
    const shieldHit = stackHit || zoneHit || emblemHit ? null : this._hitTestShield(world.x, world.y, regionSeat);
    const item = stackHit || zoneHit || emblemHit || shieldHit ? null : this._hitTest(world.x, world.y, regionSeat);
    const newKey = item?.key || null;
    this.canvas.style.cursor = (item || stackHit || zoneHit || emblemHit || shieldHit) ? "pointer" : "default";

    const newEmblemIndex = emblemHit ? emblemHit.index : null;
    if (newEmblemIndex !== this.hoveredEmblemIndex) {
      this.hoveredEmblemIndex = newEmblemIndex;
      this.needsRedraw = true;
      if (this.onEmblemHover) this.onEmblemHover(emblemHit ? emblemHit.emblem : null);
    }

    const newShieldKey = shieldHit ? shieldHit.key : null;
    if (newShieldKey !== this.hoveredShieldKey) {
      this.hoveredShieldKey = newShieldKey;
      if (this.onShieldHover) this.onShieldHover(shieldHit ? shieldHit.source : null);
    }

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

    if (ps.manaFan) {
      if (ps.cancelled) return; // dragged off — leave the fan open
      const symbol = ps.manaFanIndex >= 0 ? this.manaFan?.colors[ps.manaFanIndex]?.symbol : null;
      this.hideManaFan();
      if (symbol && this.onManaFanPick) this.onManaFanPick(symbol);
      else if (this.onManaFanCancel) this.onManaFanCancel();
      return;
    }

    if (ps.combatDrag) {
      // Blocker assignment: find attacker under cursor
      const pt = this._pointerContext(event.clientX, event.clientY);
      const target = this._hitTest(pt.world.x, pt.world.y, pt.region ? pt.region.seat : null);
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

    if (!ps.cancelled && ps.riverButton) {
      if (this.onRiverPileClick) this.onRiverPileClick(ps.riverButton);
      return;
    }

    if (!ps.cancelled && ps.camoButton) {
      if (this.onCamouflagePileClick) this.onCamouflagePileClick(ps.camoButton);
      return;
    }

    if (!ps.cancelled && ps.stackIndex != null) {
      if (this.onStackCardClick) {
        this.onStackCardClick({ index: ps.stackIndex, item: this.stackVisuals[ps.stackIndex]?.item || null });
      }
      return;
    }

    if (!ps.cancelled && ps.zonePile) {
      if (this.onZonePileClick) this.onZonePileClick(ps.zonePile);
      return;
    }

    if (!ps.cancelled && ps.emblemIndex != null) {
      if (this.onEmblemClick) {
        this.onEmblemClick({ index: ps.emblemIndex, emblem: ps.emblem });
      }
      return;
    }

    if (!ps.cancelled && this.onCardClick) {
      this.onCardClick({ seat: ps.seat, idx: ps.idx, card: ps.card });
    }
  }

  _handleContextMenu(event) {
    event.preventDefault();
    const pt = this._pointerContext(event.clientX, event.clientY);
    const item = this._hitTest(pt.world.x, pt.world.y, pt.region ? pt.region.seat : null);
    if (item && this.onCardContextMenu) {
      this.onCardContextMenu({ seat: item.seat, idx: item.idx, card: item.card, event });
    }
  }

  _handleDrop(event) {
    event.preventDefault();
    this.canvas.classList.remove("active-drop");

    const pt = this._pointerContext(event.clientX, event.clientY);
    const world = pt.world;

    // Determine seat: the viewport under the pointer in a 3-4 player game,
    // the split-relative half otherwise.
    const resolvedDropSeat = pt.region ? pt.region.seat : this._seatForWorldPoint(world.x, world.y);
    const dropSeat = resolvedDropSeat === null ? this.viewerSeat : resolvedDropSeat;

    // Check for card under cursor (for blocker assignment or aura targeting)
    const item = this._hitTest(world.x, world.y, pt.region ? pt.region.seat : null);

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

// Overshoot ease for the mana symbols springing out of the card.
function _easeOutBack(t) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

// ---- Combat fx helpers ----

// Draw order within a frame: ghosts under everything, text on top.
const _COMBAT_FX_DRAW_ORDER = { ghost: 0, beam: 1, hit: 2, chevron: 3, toughness: 4 };

// Camouflage pile-button colors, one per pile number (cycled past six piles).
const _CAMO_PILE_COLORS = ["#4a90d9", "#e0a23b", "#5cb85c", "#c95fc9", "#d9534f", "#3ac0c0"];

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
    // A single keyword wider than the card (e.g. "Protection from white") is
    // allowed to wrap across lines on word boundaries so it doesn't overflow.
    if (ctx.measureText(kw).width > maxWidth && kw.includes(" ")) {
      if (line) { lines.push(line); line = ""; }
      let wrapped = "";
      for (const word of kw.split(" ")) {
        const test = wrapped ? `${wrapped} ${word}` : word;
        if (wrapped && ctx.measureText(test).width > maxWidth) {
          lines.push(wrapped);
          wrapped = word;
        } else {
          wrapped = test;
        }
      }
      line = wrapped;
      continue;
    }
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

// ---- Arena-style card frame palette ----
// Each entry drives the beveled frame gradient for a card's color: `hi` (top
// bevel highlight) → `base` (mid) → `lo` (bottom bevel shadow), with `ink` the
// title-plate text color chosen for contrast against that plate.
const _FRAME_PALETTE = {
  W: { hi: "#fdfbe8", base: "#e6dfbc", lo: "#a89a5c", ink: "#33301f" },
  U: { hi: "#63acec", base: "#2f6fb8", lo: "#12386c", ink: "#f0f7ff" },
  B: { hi: "#5c5764", base: "#332f3a", lo: "#100d15", ink: "#ece8f2" },
  R: { hi: "#ef8266", base: "#c23a26", lo: "#6e1a0f", ink: "#ffeee8" },
  G: { hi: "#61c078", base: "#2b8a45", lo: "#124a22", ink: "#eefff2" },
  gold: { hi: "#f2da8c", base: "#c6a445", lo: "#7f6720", ink: "#2c2210" },
  artifact: { hi: "#d0d9e3", base: "#8b95a2", lo: "#474f57", ink: "#181d24" },
  colorless: { hi: "#d0d9e3", base: "#8b95a2", lo: "#474f57", ink: "#181d24" },
  land: { hi: "#c09a70", base: "#7c5a3c", lo: "#3c2a1a", ink: "#f7ecdb" },
};

// Pick the frame palette for a card: lands are earthen, 2+ colors are gold
// (multicolor), a single color uses that color, artifacts/colorless are steel.
function _cardFrameColors(card) {
  const type = String(card?.type || "").toLowerCase();
  const colors = Array.isArray(card?.colors) ? card.colors : [];
  if (type.includes("land")) return _FRAME_PALETTE.land;
  if (colors.length >= 2) return _FRAME_PALETTE.gold;
  if (colors.length === 1 && _FRAME_PALETTE[colors[0]]) return _FRAME_PALETTE[colors[0]];
  if (type.includes("artifact")) return _FRAME_PALETTE.artifact;
  return _FRAME_PALETTE.colorless;
}

// Truncate `text` with an ellipsis so it fits within `maxW` at the current font.
function _ellipsizeText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
  return t + "…";
}
