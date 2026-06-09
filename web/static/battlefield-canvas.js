// battlefield-canvas.js — canvas-based battlefield renderer, projected onto a
// 3D-tilted table plane (bird's-eye Arena-style view).

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
// Stack: each successive card is offset down (positive Y) so cards fan downward.
// Target (bottom of stack) is at base Y; auras layer below it.
const BF_STACK_OFFSET_X = 0;
const BF_STACK_OFFSET_Y = 22;
// World Y value of the dividing line between the two player halves
const BF_WORLD_SPLIT_Y = 310;
// How close (in world px) the center of a dragged card must be to snap-stack
const BF_SNAP_DIST = BF_CARD_W * 0.7;

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

    // Camera state (in CSS-pixel space)
    this.camX = 30;
    this.camY = 20;
    this.zoom = 1.0;

    // cardItems: [{key, seat, idx, card, x, y}]
    // x/y are world-space anchor coordinates for the item.
    // For stacked items, only the bottom card's x/y is used as the stack anchor;
    // other members' positions are computed by _renderPos().
    this.cardItems = [];

    // stacks: [{id, keys[]}]
    // keys is ordered bottom-to-top (game stack order).
    // Visual: bottom key rendered first (behind), top key rendered last (on top).
    this.stacks = [];

    // Image cache: url -> HTMLImageElement | null
    this.imageCache = new Map();
    this.imageLoading = new Set();

    // Callbacks
    this.onCardClick = callbacks.onCardClick || null;
    this.onCardContextMenu = callbacks.onCardContextMenu || null;
    this.onCardHover = callbacks.onCardHover || null;
    this.onHandCardDrop = callbacks.onHandCardDrop || null;
    this.onBlockerAssign = callbacks.onBlockerAssign || null;
    this.onPermanentDrop = callbacks.onPermanentDrop || null;

    // Runtime state
    this.viewerSeat = 0;
    this.selectedKeys = new Set();
    this.attackingKeys = new Set();
    this.targetingKeys = new Set();
    this.combatArrows = [];
    this.hoveredKey = null;

    // Drag state (left mouse)
    this.dragState = null;
    // Pan state (middle mouse)
    this.panState = null;

    // External context passed on updates (current game state for callback decisions)
    this.currentState = null;

    // RAF loop
    this.rafId = null;
    this.needsRedraw = true;

    this._resize();
    // Shift the default camera so world-origin content sits inside the visible
    // (non-overscan) part of the tilted plane.
    this.camX = 30 + ((this.cssW || 0) * (1 - 1 / BF_OVERSCAN_X)) / 2;
    this.camY = 20 + ((this.cssH || 0) * (1 - 1 / BF_OVERSCAN_Y)) / 2;
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
    return {
      x: baseItem.x + stackPos * BF_STACK_OFFSET_X,
      y: baseItem.y + stackPos * BF_STACK_OFFSET_Y,
    };
  }

  // Get the world-space bounding box of a card for hit testing.
  _cardBounds(key) {
    const pos = this._renderPos(key);
    if (!pos) return null;
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

  // All keys that move together when `key` is grabbed:
  // the grabbed card and every card above it in its stack.
  _movedKeys(key) {
    const stack = this.stacks.find((s) => s.keys.includes(key));
    if (!stack) return [key];
    const pos = stack.keys.indexOf(key);
    return stack.keys.slice(pos);
  }

  // Detach movedKeys from their stacks, fixing each item's x/y to its current render position.
  _detachFromStacks(keys) {
    // First fix positions
    for (const k of keys) {
      const pos = this._renderPos(k);
      const item = this.cardItems.find((c) => c.key === k);
      if (item && pos) { item.x = pos.x; item.y = pos.y; }
    }
    // Remove from stacks
    for (const stack of this.stacks) {
      for (const k of keys) {
        const idx = stack.keys.indexOf(k);
        if (idx >= 0) stack.keys.splice(idx, 1);
      }
    }
    this.stacks = this.stacks.filter((s) => s.keys.length >= 2);
  }

  // Merge movedKeys on top of targetKey's stack (or create a new stack).
  _stackOnto(movedKeys, targetKey) {
    let targetStack = this.stacks.find((s) => s.keys.includes(targetKey));
    if (!targetStack) {
      targetStack = { id: `stack-${targetKey}-${Date.now()}`, keys: [targetKey] };
      this.stacks.push(targetStack);
    }
    for (const k of movedKeys) {
      if (!targetStack.keys.includes(k)) targetStack.keys.push(k);
    }
    // Snap movedItems' stored x/y to stack base
    const baseItem = this.cardItems.find((c) => c.key === targetStack.keys[0]);
    if (baseItem) {
      for (const k of movedKeys) {
        const item = this.cardItems.find((c) => c.key === k);
        if (item) { item.x = baseItem.x; item.y = baseItem.y; }
      }
    }
    this._sortRenderOrder();
    this.needsRedraw = true;
  }

  _sortRenderOrder() {
    const stackedKeys = new Set(this.stacks.flatMap((s) => s.keys));
    const free = this.cardItems.filter((c) => !stackedKeys.has(c.key));
    const stacked = [];
    for (const stack of this.stacks) {
      for (const k of stack.keys) {
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

    const canvasH = this.cssH || 500;
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

    // Prune cards and stacks that left the battlefield
    this.cardItems = this.cardItems.filter((c) => newKeys.has(c.key));
    this.stacks = this.stacks
      .map((s) => ({ ...s, keys: s.keys.filter((k) => newKeys.has(k)) }))
      .filter((s) => s.keys.length >= 2);

    const serverPositions = state.card_positions || {};
    const draggingKeys = new Set(this.dragState?.movedKeys || []);

    // Update existing cards / add new ones
    for (const [key, data] of incoming) {
      const existing = this.cardItems.find((c) => c.key === key);
      if (existing) {
        existing.card = data.card;
        const serverPos = serverPositions[key];
        if (serverPos && !draggingKeys.has(key)) {
          existing.x = serverPos.x;
          existing.y = serverPos.y;
        }
      } else {
        let pos;
        const serverPos = serverPositions[key];
        if (serverPos) {
          pos = serverPos;
        } else if (data.seat === this.viewerSeat && this._pendingDropX !== undefined) {
          pos = { x: this._pendingDropX - BF_CARD_W / 2, y: this._pendingDropY - BF_CARD_H / 2 };
          this._pendingDropX = undefined;
          this._pendingDropY = undefined;
        } else {
          pos = this._defaultPosition(data.seat, data.idx, canvasH);
        }
        this.cardItems.push({ key, seat: data.seat, idx: data.idx, card: data.card, x: pos.x, y: pos.y });
      }
    }

    this._syncAuraStacks(state, newKeys);
    this._sortRenderOrder();
    this.needsRedraw = true;
  }

  _defaultPosition(seat, idx, canvasH) {
    const COLS = 8;
    const col = idx % COLS;
    const row = Math.floor(idx / COLS);
    const x = 20 + col * (BF_CARD_W + 18);
    const rowH = BF_CARD_H + 18;
    let y;
    if (seat === this.viewerSeat) {
      y = BF_WORLD_SPLIT_Y + 20 + row * rowH;
    } else {
      y = 20 + row * rowH;
    }
    return { x, y };
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

        // Ensure there's a stack with targetKey as bottom and auraKey in it.
        let stack = this.stacks.find((s) => s.keys[0] === targetKey);
        if (!stack) {
          // targetKey might be in another stack somewhere — remove it first
          this.stacks = this.stacks.map((s) => ({ ...s, keys: s.keys.filter((k) => k !== targetKey) })).filter((s) => s.keys.length >= 2);
          stack = { id: `aura-${targetKey}`, keys: [targetKey] };
          this.stacks.push(stack);
        }
        if (!stack.keys.includes(auraKey)) {
          // Push first so the stack has >= 2 keys and survives the filter below.
          stack.keys.push(auraKey);
          // Remove auraKey from any other stack.
          this.stacks = this.stacks.map((s) => {
            if (s === stack) return s;
            return { ...s, keys: s.keys.filter((k) => k !== auraKey) };
          }).filter((s) => s.keys.length >= 2);
        }

        // Snap aura position to target's position
        const targetItem = this.cardItems.find((c) => c.key === targetKey);
        const auraItem = this.cardItems.find((c) => c.key === auraKey);
        if (targetItem && auraItem) {
          auraItem.x = targetItem.x;
          auraItem.y = targetItem.y;
        }
      }
    }
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
    const { selected, attacking, hovered, isDragGhost, targeting } = flags || {};
    const img = card?.image_uri ? this._loadImage(card.image_uri) : null;
    const R = 4;
    const alpha = isDragGhost ? 0.45 : 1;

    ctx.save();
    ctx.globalAlpha = alpha;

    // ---- Drop shadow onto the table ----
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.55)";
    ctx.shadowBlur = (hovered || isDragGhost ? 24 : 12) / this.zoom;
    ctx.shadowOffsetY = (hovered || isDragGhost ? 10 : 5) / this.zoom;
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
    else if (hovered && !isDragGhost) { ctx.shadowColor = "#7ec4ff"; ctx.shadowBlur = 10 / this.zoom; }

    ctx.strokeStyle = attacking ? "#ff5555" : selected ? "#ffe040" : targeting ? "#50ffb0" : hovered ? "#7ec4ff" : "rgba(255,255,255,0.22)";
    ctx.lineWidth = (attacking || selected || targeting ? 2.5 : 1) / this.zoom;
    this._roundRect(ctx, x, y, w, h, R);
    ctx.stroke();
    ctx.restore();

    // ---- P/T badge ----
    // If creatureCard is provided, show its P/T on this card (enchantment on top of creature).
    const ptCard = creatureCard || card;
    if (ptCard && typeof ptCard.power === "number" && typeof ptCard.toughness === "number" && String(ptCard.type || "").toLowerCase().includes("creature")) {
      const label = `${ptCard.power}/${ptCard.toughness}`;
      const bw = 26, bh = 13;
      ctx.fillStyle = "rgba(0,0,0,0.78)";
      ctx.fillRect(x + w - bw - 2, y + h - bh - 2, bw, bh);
      ctx.fillStyle = "#fff";
      ctx.font = `bold ${Math.max(8, bh * 0.75)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, x + w - bw / 2 - 2, y + h - bh / 2 - 2);
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

    ctx.globalAlpha = 1;
    ctx.restore();
  }

  _drawCard(ctx, item, overrideFlags) {
    const pos = this._renderPos(item.key);
    if (!pos) return;
    const card = item.card;
    const tapped = card?.tapped;
    const flags = {
      selected: this.selectedKeys.has(item.key),
      attacking: this.attackingKeys.has(item.key),
      targeting: this.targetingKeys.has(item.key),
      hovered: this.hoveredKey === item.key,
      ...overrideFlags,
    };

    // If this is the topmost card in a stack, show the bottom creature's P/T and damage on it.
    let creatureCard = null;
    const stack = this.stacks.find((s) => s.keys.length >= 2 && s.keys[s.keys.length - 1] === item.key);
    if (stack) {
      const bottomItem = this.cardItems.find((c) => c.key === stack.keys[0]);
      if (bottomItem?.card && typeof bottomItem.card.power === "number" && String(bottomItem.card.type || "").toLowerCase().includes("creature")) {
        creatureCard = bottomItem.card;
      }
    }

    ctx.save();
    // Hovered / dragged cards lift slightly off the table.
    const lifted = (flags.hovered && !flags.isDragGhost) || flags.isDragGhost;
    if (lifted) {
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
    const draggedKeys = this.dragState?.dragging ? new Set(this.dragState.movedKeys) : new Set();

    for (const item of this.cardItems) {
      if (draggedKeys.has(item.key)) continue; // draw dragged cards last
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

    // ---- Live combat drag arrow ----
    if (this.dragState?.combatDrag) {
      const fc = this._cardCenter(this.dragState.key);
      const tw = this.canvasToWorld(this.dragState.currentCX, this.dragState.currentCY);
      if (fc) {
        this._drawArrow(ctx, fc.x, fc.y, tw.x, tw.y, "#ff8888");
      }
    }

    // ---- Dragged cards (ghost at new position) ----
    if (this.dragState?.dragging && !this.dragState.combatDrag) {
      // Drop-target highlight
      if (this.dragState.dropTarget) {
        const targetPos = this._renderPos(this.dragState.dropTarget);
        if (targetPos) {
          ctx.save();
          ctx.strokeStyle = "#ffe040";
          ctx.lineWidth = 2.5 / this.zoom;
          ctx.setLineDash([5, 3]);
          this._roundRect(ctx, targetPos.x - 3, targetPos.y - 3, BF_CARD_W + 6, BF_CARD_H + 6, 6);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.restore();
        }
      }

      for (const item of this.cardItems) {
        if (!draggedKeys.has(item.key)) continue;
        this._drawCard(ctx, item);
      }
    }

    ctx.restore(); // camera
  }

  _startLoop() {
    const loop = () => {
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
    this.needsRedraw = true;
  }

  _bindEvents() {
    this._mdown = (e) => this._handleMouseDown(e);
    this._mmove = (e) => this._handleMouseMove(e);
    this._mup = (e) => this._handleMouseUp(e);
    this._mwheel = (e) => this._handleWheel(e);
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

  _isCombatAttackerPhase() {
    const s = this.currentState;
    if (!s) return false;
    return s.current_turn_phase === "combat" && s.current_step === "declare_attackers";
  }

  _handleMouseDown(event) {
    event.preventDefault();
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);

    if (event.button === 1) {
      // Middle mouse: pan
      this.panState = { startCamX: this.camX, startCamY: this.camY, startX: cx, startY: cy };
      this.canvas.style.cursor = "grabbing";
      return;
    }

    if (event.button !== 0) return;

    const item = this._hitTest(world.x, world.y);
    if (!item) {
      // Left-click on empty space: pan
      this.panState = { startCamX: this.camX, startCamY: this.camY, startX: cx, startY: cy };
      this.canvas.style.cursor = "grabbing";
      return;
    }

    const movedKeys = this._movedKeys(item.key);
    const origPositions = {};
    for (const k of movedKeys) {
      const pos = this._renderPos(k);
      if (pos) origPositions[k] = { x: pos.x, y: pos.y };
    }

    this.dragState = {
      key: item.key,
      seat: item.seat,
      idx: item.idx,
      card: item.card,
      movedKeys,
      origPositions,
      startWorldX: world.x,
      startWorldY: world.y,
      startCX: cx,
      startCY: cy,
      currentCX: cx,
      currentCY: cy,
      dragging: false,
      combatDrag: false,
      dropTarget: null,
    };
  }

  _handleMouseMove(event) {
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const world = this.canvasToWorld(cx, cy);

    if (this.panState) {
      this.camX = this.panState.startCamX + (cx - this.panState.startX);
      this.camY = this.panState.startCamY + (cy - this.panState.startY);
      this.needsRedraw = true;
      return;
    }

    if (this.dragState) {
      const dx = world.x - this.dragState.startWorldX;
      const dy = world.y - this.dragState.startWorldY;
      const pixDx = cx - this.dragState.startCX;
      const pixDy = cy - this.dragState.startCY;

      if (!this.dragState.dragging && (Math.abs(pixDx) > 4 || Math.abs(pixDy) > 4)) {
        if (this.dragState.seat !== this.viewerSeat) return;
        // Auras attached to permanents cannot be manually detached
        if (this.dragState.card?.attached_to_index != null) return;
        // Start dragging
        this.dragState.dragging = true;

        // In declare_blockers phase: if dragging my own creature, treat as combat drag
        if (
          this._isCombatBlockerPhase() &&
          this.currentState?.combat?.defending_player_index === this.viewerSeat &&
          this.dragState.seat === this.viewerSeat &&
          this.dragState.movedKeys.length === 1
        ) {
          this.dragState.combatDrag = true;
        } else {
          // Regular card move: detach from stacks
          this._detachFromStacks(this.dragState.movedKeys);
          // Re-save positions after detach
          for (const k of this.dragState.movedKeys) {
            const item = this.cardItems.find((c) => c.key === k);
            if (item) this.dragState.origPositions[k] = { x: item.x, y: item.y };
          }
        }
      }

      if (this.dragState.dragging) {
        this.dragState.currentCX = cx;
        this.dragState.currentCY = cy;

        if (!this.dragState.combatDrag) {
          // Move all dragged items
          for (const k of this.dragState.movedKeys) {
            const item = this.cardItems.find((c) => c.key === k);
            const orig = this.dragState.origPositions[k];
            if (item && orig) { item.x = orig.x + dx; item.y = orig.y + dy; }
          }

          // Find drop target (snap candidate)
          this.dragState.dropTarget = null;
          const draggedCenter = {
            x: (this.dragState.origPositions[this.dragState.key]?.x || 0) + dx + BF_CARD_W / 2,
            y: (this.dragState.origPositions[this.dragState.key]?.y || 0) + dy + BF_CARD_H / 2,
          };
          for (let i = this.cardItems.length - 1; i >= 0; i--) {
            const candidate = this.cardItems[i];
            if (this.dragState.movedKeys.includes(candidate.key)) continue;
            const cpos = this._renderPos(candidate.key);
            if (!cpos) continue;
            const ccx = cpos.x + BF_CARD_W / 2;
            const ccy = cpos.y + BF_CARD_H / 2;
            const dist = Math.hypot(draggedCenter.x - ccx, draggedCenter.y - ccy);
            if (dist < BF_SNAP_DIST) {
              this.dragState.dropTarget = candidate.key;
              break;
            }
          }
        }

        this.needsRedraw = true;
      }
      return;
    }

    // Hover
    const item = this._hitTest(world.x, world.y);
    const newKey = item?.key || null;
    this.canvas.style.cursor = item ? "pointer" : "grab";
    if (newKey !== this.hoveredKey) {
      this.hoveredKey = newKey;
      this.needsRedraw = true;
      if (this.onCardHover) {
        this.onCardHover(item ? { seat: item.seat, idx: item.idx, card: item.card } : null);
      }
    }
  }

  _handleMouseUp(event) {
    if (this.panState && (event.button === 1 || event.button === 0)) {
      this.panState = null;
      this.canvas.style.cursor = "grab";
      return;
    }

    if (event.button !== 0 || !this.dragState) return;

    const ds = this.dragState;
    this.dragState = null;

    if (!ds.dragging) {
      // Click
      if (this.onCardClick) {
        this.onCardClick({ seat: ds.seat, idx: ds.idx, card: ds.card });
      }
      return;
    }

    if (ds.combatDrag) {
      // Blocker assignment: find attacker under cursor
      const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
      const world = this.canvasToWorld(cx, cy);
      const target = this._hitTest(world.x, world.y);
      if (
        target &&
        target.seat !== this.viewerSeat &&
        target.key !== ds.key &&
        this.onBlockerAssign
      ) {
        this.onBlockerAssign({ blockerIdx: ds.idx, attackerIdx: target.idx });
      }
      // Snap card back to original position
      const item = this.cardItems.find((c) => c.key === ds.key);
      const orig = ds.origPositions[ds.key];
      if (item && orig) { item.x = orig.x; item.y = orig.y; }
    } else if (ds.dropTarget) {
      // Stack the dragged cards onto the drop target
      this._stackOnto(ds.movedKeys, ds.dropTarget);
    }

    // In declare_blockers, also allow dropping own permanent onto opponent's attacker via regular drag
    if (
      !ds.combatDrag &&
      ds.dropTarget &&
      this._isCombatBlockerPhase() &&
      this.currentState?.combat?.defending_player_index === this.viewerSeat &&
      ds.seat === this.viewerSeat
    ) {
      const targetItem = this.cardItems.find((c) => c.key === ds.dropTarget);
      if (targetItem && targetItem.seat !== this.viewerSeat && this.onBlockerAssign) {
        this.onBlockerAssign({ blockerIdx: ds.idx, attackerIdx: targetItem.idx });
        // Undo the stack, return card to original position
        this._detachFromStacks([ds.key]);
        const item = this.cardItems.find((c) => c.key === ds.key);
        const orig = ds.origPositions[ds.key];
        if (item && orig) { item.x = orig.x; item.y = orig.y; }
      }
    }

    if (this.onPermanentDrop) this.onPermanentDrop();
    this.needsRedraw = true;
  }

  _handleWheel(event) {
    event.preventDefault();
    const { x: cx, y: cy } = this._pageToCanvas(event.clientX, event.clientY);
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.max(0.15, Math.min(5, this.zoom * factor));
    const wx = (cx - this.camX) / this.zoom;
    const wy = (cy - this.camY) / this.zoom;
    this.zoom = newZoom;
    this.camX = cx - wx * this.zoom;
    this.camY = cy - wy * this.zoom;
    this.needsRedraw = true;
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
      this._pendingDropX = world.x;
      this._pendingDropY = world.y;
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
