// animations.js — centralized anime.js-powered UI motion helpers.
//
// Exposes a single global `FX`. Every helper is safe to call even if anime.js
// failed to load or the user prefers reduced motion: the fallback is always
// the instant, animation-free behavior the app had before this file existed.
(function () {
  "use strict";

  const hasAnime = typeof anime !== "undefined";
  const reducedQuery = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };

  const FX = {
    get reduced() {
      return reducedQuery.matches;
    },
    get enabled() {
      return hasAnime && !reducedQuery.matches;
    },
  };

  // Clear only the inline properties an animation touched. Many animated
  // elements carry load-bearing inline styles (fan angles, z-index, custom
  // properties), so removeAttribute("style") is never safe here.
  function clearAnimStyles(el) {
    el.style.opacity = "";
    el.style.transform = "";
  }

  // -------------------------------------------------------------------------
  // Menu page transitions
  // -------------------------------------------------------------------------

  let menuBusy = false;

  // Swap between menu pages: quick fade-out of the current page, apply the
  // real visibility change (caller-provided), then stagger the new page's
  // children in. Falls back to a synchronous swap when animation is off or a
  // swap is already in flight (double-click).
  FX.menuSwap = function (outEl, inEl, applyVisibility) {
    if (!FX.enabled || menuBusy || !inEl) {
      applyVisibility();
      return;
    }
    menuBusy = true;
    const finish = () => {
      applyVisibility();
      const children = inEl.querySelectorAll(":scope > *");
      anime({
        targets: children,
        opacity: [0, 1],
        translateY: [18, 0],
        scale: [0.98, 1],
        duration: 350,
        delay: anime.stagger(45),
        easing: "easeOutCubic",
        complete: () => {
          menuBusy = false;
          // Clear inline styles so CSS hover transforms work afterwards.
          children.forEach(clearAnimStyles);
        },
      });
    };
    if (outEl && !outEl.classList.contains("hidden")) {
      anime({
        targets: outEl.querySelectorAll(":scope > *"),
        opacity: [1, 0],
        translateY: [0, -12],
        duration: 120,
        easing: "easeInQuad",
        complete: () => {
          // Reset the outgoing page's inline styles so it is intact next time.
          outEl.querySelectorAll(":scope > *").forEach(clearAnimStyles);
          finish();
        },
      });
    } else {
      finish();
    }
  };

  // Menu -> game transition: stagger the board HUD clusters in.
  FX.enterBoard = function (boardEl) {
    if (!FX.enabled || !boardEl) return;
    const clusters = boardEl.querySelectorAll(
      ".board-header, .phase-rail, .floating-dock, .hand-fan-wrap, .mana-row"
    );
    if (!clusters.length) return;
    anime({
      targets: clusters,
      opacity: [0, 1],
      translateY: [16, 0],
      duration: 420,
      delay: anime.stagger(60),
      easing: "easeOutCubic",
      complete: () => clusters.forEach(clearAnimStyles),
    });
  };

  // -------------------------------------------------------------------------
  // Modals — observe .modal-overlay class flips; pop the box on open.
  // Never mutates the hidden class itself (game logic reads it).
  // -------------------------------------------------------------------------

  FX.observeModals = function () {
    if (!window.MutationObserver) return;
    document.querySelectorAll(".modal-overlay").forEach((overlay) => {
      let wasHidden = overlay.classList.contains("hidden");
      const observer = new MutationObserver(() => {
        const hidden = overlay.classList.contains("hidden");
        if (wasHidden && !hidden && FX.enabled) {
          const box = overlay.querySelector(".modal-box");
          if (box) {
            anime({
              targets: box,
              scale: [0.92, 1],
              translateY: [14, 0],
              opacity: [0, 1],
              duration: 320,
              easing: "easeOutBack",
              complete: () => clearAnimStyles(box),
            });
          }
        }
        wasHidden = hidden;
      });
      observer.observe(overlay, { attributes: true, attributeFilter: ["class"] });
    });
  };

  // -------------------------------------------------------------------------
  // Micro-interactions
  // -------------------------------------------------------------------------

  // Life total punch: elastic scale pop, bigger for bigger swings.
  FX.lifePunch = function (el, delta) {
    if (!FX.enabled || !el) return;
    const magnitude = Math.min(1.5, 1.2 + Math.abs(delta || 1) * 0.05);
    anime.remove(el);
    anime({
      targets: el,
      scale: [magnitude, 1],
      duration: 650,
      easing: "easeOutElastic(1, .45)",
      complete: () => clearAnimStyles(el),
    });
  };

  // Phase rail pill pulse when the active phase changes.
  FX.phasePulse = function (el) {
    if (!FX.enabled || !el) return;
    anime.remove(el);
    anime({
      targets: el,
      scale: [1.18, 1],
      duration: 450,
      easing: "easeOutBack",
      complete: () => clearAnimStyles(el),
    });
  };

  // Turn announcement: blur-in headline.
  FX.turnAnnounce = function (el) {
    if (!FX.enabled || !el) return;
    anime.remove(el);
    anime({
      targets: el,
      opacity: [0, 1],
      scale: [1.15, 1],
      duration: 500,
      easing: "easeOutCubic",
      complete: () => clearAnimStyles(el),
    });
  };

  // Stagger newly drawn hand cards in. Caller passes only the NEW slots.
  FX.handEnter = function (els) {
    if (!FX.enabled || !els || !els.length) return;
    anime({
      targets: els,
      opacity: [0, 1],
      translateY: [26, 0],
      scale: [0.9, 1],
      duration: 380,
      delay: anime.stagger(55),
      easing: "easeOutCubic",
      // Inline transform/opacity must be cleared or the CSS fan hover breaks.
      complete: () => els.forEach(clearAnimStyles),
    });
  };

  // Delegated tactile press feedback for all buttons (one listener).
  FX.pressFeedback = function () {
    if (!hasAnime) return;
    document.addEventListener(
      "pointerdown",
      (ev) => {
        if (!FX.enabled) return;
        const btn = ev.target.closest("button");
        if (!btn || btn.disabled) return;
        anime.remove(btn);
        anime({
          targets: btn,
          scale: [0.94, 1],
          duration: 320,
          easing: "easeOutBack",
          complete: () => (btn.style.transform = ""),
        });
      },
      { passive: true }
    );
  };

  // Boot the passive observers once the DOM is ready.
  const boot = () => {
    FX.observeModals();
    FX.pressFeedback();
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.FX = FX;
})();
