"""Test: hovering a floating stack card grows it 50% (and shrinks on unhover).

Casts two spells so the cascade has overlap, hovers the bottom card, and
checks scale growth, draw-order stickiness, and shrink-back.
"""
import json
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok))
        print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until="networkidle")

        session_id = page.evaluate(
            """
            async () => {
              const data = await postJson("/api/sessions", {
                mode: "human_vs_human", host_name: "P1", guest_name: "P2",
                host_colors: 1, guest_colors: 1, host_deck_id: null, guest_deck_id: null,
                use_custom_seed: true, custom_seed: 42, enable_pregame: false,
              });
              sessionId = data.session_id;
              seat = data.seat;
              openStateSyncStream();
              setVisible(true);
              initBattlefieldCanvas();
              renderState(data.state);
              return data.session_id;
            }
            """
        )
        urllib.request.urlopen(
            urllib.request.Request(
                f"{BASE}/api/sessions/{session_id}/join",
                data=json.dumps({"guest_name": "P2"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        ).read()

        def api_action(body):
            req = urllib.request.Request(
                f"{BASE}/api/sessions/{session_id}/action",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return {"error": e.read().decode()}

        deadline = time.time() + 30
        while time.time() < deadline:
            if page.evaluate(
                "() => !!(currentState && currentState.priority_player === 0 && "
                "currentState.current_turn === 0 && "
                "currentState.current_turn_phase === 'precombat_main')"
            ):
                break
            if page.evaluate("() => currentState?.priority_player") == 1:
                api_action({"seat": 1, "action": "pass_priority"})
            time.sleep(0.4)

        # Cast spell 1, hover-hold it through the dwell, then cast spell 2 in
        # response while holding (click to lock so we can move the mouse).
        page.evaluate(
            """
            async () => {
              q("debugCardSearch").value = "Wrath of God";
              await castDebugCardForFree();
            }
            """
        )
        page.wait_for_function(
            "() => battlefieldCanvas && battlefieldCanvas.stackVisuals.length > 0", timeout=10000
        )
        pt = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[0];
              const c = battlefieldCanvas.worldToCanvas(v.tcx, v.tcy);
              return battlefieldCanvas._canvasToPage(c.x, c.y);
            }
            """
        )
        page.mouse.move(pt["x"], pt["y"], steps=5)
        time.sleep(2.0)
        page.mouse.click(pt["x"], pt["y"])  # lock hold
        time.sleep(0.3)
        page.evaluate(
            """
            async () => {
              q("debugCardSearch").value = "Dark Ritual";
              await castDebugCardForFree();
            }
            """
        )
        page.wait_for_function(
            "() => battlefieldCanvas.stackVisuals.length === 2", timeout=10000
        )
        time.sleep(2.0)

        base_scale = page.evaluate("() => 1.7 / battlefieldCanvas.zoom")

        # Hover the bottom card (index 1) on its uncovered upper-left corner.
        pt = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[1];
              const c = battlefieldCanvas.worldToCanvas(v.cx - 45, v.cy - 65);
              return battlefieldCanvas._canvasToPage(c.x, c.y);
            }
            """
        )
        page.mouse.move(pt["x"], pt["y"], steps=5)
        time.sleep(1.0)  # let the grow animation ease in

        st = page.evaluate(
            """
            () => ({
              hovered: battlefieldCanvas.hoveredStackIndex,
              scales: battlefieldCanvas.stackVisuals.map((v) => v.scale),
              tScales: battlefieldCanvas.stackVisuals.map((v) => v.tScale),
            })
            """
        )
        page.screenshot(path="scripts/stack_hover_zoom.png")
        grown = abs(st["tScales"][1] - base_scale * 1.5) < 0.01 and st["scales"][1] > base_scale * 1.4
        normal = abs(st["tScales"][0] - base_scale) < 0.01
        check("hovered card targets 1.5x and grows", st["hovered"] == 1 and grown, json.dumps(st))
        check("other card stays at base scale", normal, json.dumps(st["tScales"]))

        # Hover stays on the enlarged card even where it now overlaps card 0.
        still = page.evaluate("() => battlefieldCanvas.hoveredStackIndex")
        check("hover is stable while enlarged", still == 1)

        # Unhover: shrinks back to base scale.
        page.mouse.move(400, 800, steps=5)
        time.sleep(1.0)
        st = page.evaluate(
            """
            () => ({
              hovered: battlefieldCanvas.hoveredStackIndex,
              tScales: battlefieldCanvas.stackVisuals.map((v) => v.tScale),
              scales: battlefieldCanvas.stackVisuals.map((v) => v.scale),
            })
            """
        )
        back = st["hovered"] is None and abs(st["tScales"][1] - base_scale) < 0.01 and st["scales"][1] < base_scale * 1.1
        check("unhover shrinks back to base scale", back, json.dumps(st))

        if errors:
            print("PAGE ERRORS:", errors)
        browser.close()

    print()
    print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAILED")


if __name__ == "__main__":
    main()
