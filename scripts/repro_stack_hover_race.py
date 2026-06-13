"""Repro: hover the floating stack card DURING the cast dwell, racing auto-pass.

Scenario mirrors real play vs AI: the player casts on their own turn, the
client auto-pass is in flight (waiting on the stack dwell), and the player
moves the mouse onto the floating card. Expected: the hover holds priority and
the spell does not resolve. Control run: without hovering, it resolves.
"""
import json
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def run_case(p, hover: bool):
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")

    page.evaluate(
        """
        async () => {
          const data = await postJson("/api/sessions", {
            mode: "human_vs_ai", host_name: "P1", guest_name: "AI",
            host_colors: 1, guest_colors: 1, host_deck_id: null, guest_deck_id: null,
            use_custom_seed: true, custom_seed: 7, enable_pregame: false,
          });
          sessionId = data.session_id;
          seat = data.seat;
          openStateSyncStream();
          setVisible(true);
          initBattlefieldCanvas();
          renderState(data.state);
        }
        """
    )

    # Wait until it's the player's main phase with priority (AI turns auto-run).
    page.wait_for_function(
        "() => currentState && currentState.priority_player === 0 && "
        "currentState.current_turn === 0 && "
        "currentState.current_turn_phase === 'precombat_main'",
        timeout=60000,
    )

    # Cast and immediately aim the mouse at the cascade's target slot.
    page.evaluate(
        """
        async () => {
          q("debugCardSearch").value = "Wrath of God";
          await castDebugCardForFree();
        }
        """
    )
    page.wait_for_function(
        "() => battlefieldCanvas && battlefieldCanvas.stackVisuals.length > 0",
        timeout=5000,
    )
    if hover:
        target = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[0];
              const c = battlefieldCanvas.worldToCanvas(v.tcx, v.tcy);
              return battlefieldCanvas._canvasToPage(c.x, c.y);
            }
            """
        )
        page.mouse.move(target["x"], target["y"], steps=8)

    time.sleep(3.5)

    result = page.evaluate(
        """
        () => ({
          stackLen: (currentState?.stack || []).length,
          priority: currentState?.priority_player,
          hoveredStackIndex: battlefieldCanvas.hoveredStackIndex,
          stackCanvasHoverActive: typeof stackCanvasHoverActive !== 'undefined' ? stackCanvasHoverActive : null,
          logTail: (currentState?.log || []).slice(-4),
        })
        """
    )
    print(f"hover={hover}:", json.dumps(result, indent=2))

    if hover and result["stackLen"] > 0:
        # Unhover: auto-pass should resume and the spell should resolve.
        page.mouse.move(100, 100, steps=4)
        time.sleep(3.5)
        after = page.evaluate("() => (currentState?.stack || []).length")
        print(f"after unhover, stackLen={after} ({'resolved' if after == 0 else 'STUCK'})")
        result["resolvedAfterUnhover"] = after == 0

    if errors:
        print("PAGE ERRORS:", errors)
    browser.close()
    return result


def main():
    with sync_playwright() as p:
        with_hover = run_case(p, hover=True)
        without_hover = run_case(p, hover=False)

    held = with_hover["stackLen"] > 0
    resolved = without_hover["stackLen"] == 0
    print(f"\nhover holds spell on stack: {'PASS' if held else 'FAIL'}")
    print(f"no hover lets spell resolve: {'PASS' if resolved else 'FAIL'}")


if __name__ == "__main__":
    main()
