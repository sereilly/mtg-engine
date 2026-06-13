"""Ground-truth test: hover where the stack card is VISUALLY drawn.

Takes a screenshot, locates the bright card pixels on the right side of the
battlefield, moves the real mouse to that centroid, and checks whether hover
registers. Also prints where the canvas math thinks the card is, to expose
any projection mismatch between drawing and hit-testing.
"""
import io
import json
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def main():
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
        join_req = urllib.request.Request(
            f"{BASE}/api/sessions/{session_id}/join",
            data=json.dumps({"guest_name": "P2"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(join_req).read()

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
            ready = page.evaluate(
                "() => !!(currentState && currentState.priority_player === 0 && "
                "currentState.current_turn === 0 && "
                "currentState.current_turn_phase === 'precombat_main')"
            )
            if ready:
                break
            st = page.evaluate("() => currentState?.priority_player")
            if st == 1:
                api_action({"seat": 1, "action": "pass_priority"})
            time.sleep(0.4)

        page.evaluate(
            """
            async () => {
              q("debugCardSearch").value = "Wrath of God";
              await castDebugCardForFree();
            }
            """
        )
        page.wait_for_function(
            "() => currentState && (currentState.stack || []).length > 0",
            timeout=10000,
        )
        time.sleep(2.0)  # settle

        predicted = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[0];
              const c = battlefieldCanvas.worldToCanvas(v.cx, v.cy);
              const pt = battlefieldCanvas._canvasToPage(c.x, c.y);
              return { x: pt.x, y: pt.y };
            }
            """
        )

        shot = page.screenshot()
        img = Image.open(io.BytesIO(shot)).convert("RGB")
        w, h = img.size
        px = img.load()

        # Find bright card pixels in the right portion of the board area.
        xs, ys, count = 0, 0, 0
        for yy in range(int(h * 0.25), int(h * 0.75), 2):
            for xx in range(int(w * 0.55), w, 2):
                r, g, b = px[xx, yy]
                if r > 150 and g > 140 and b > 110:  # bright card face on dark table
                    xs += xx
                    ys += yy
                    count += 1
        if count < 50:
            print(f"could not find card pixels (count={count})")
            img.save("scripts/stack_hover_debug.png")
            browser.close()
            return

        cx_detected, cy_detected = xs / count, ys / count
        print(f"predicted by canvas math: ({predicted['x']:.0f}, {predicted['y']:.0f})")
        print(f"detected from pixels:     ({cx_detected:.0f}, {cy_detected:.0f})  ({count} px)")
        dx = cx_detected - predicted["x"]
        dy = cy_detected - predicted["y"]
        print(f"delta: ({dx:.0f}, {dy:.0f})")

        page.mouse.move(cx_detected, cy_detected, steps=5)
        time.sleep(0.5)
        state = page.evaluate(
            """
            () => ({
              hoveredStackIndex: battlefieldCanvas.hoveredStackIndex,
              stackCanvasHoverActive: stackCanvasHoverActive,
              previewName: q("cardPreviewName").textContent,
            })
            """
        )
        print("hover at drawn position:", json.dumps(state, indent=2))
        img.save("scripts/stack_hover_debug.png")
        print("PAGE ERRORS:", errors if errors else "none")
        browser.close()


if __name__ == "__main__":
    main()
