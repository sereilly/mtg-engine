"""Hover the floating stack card under different devicePixelRatio values,
moving the real mouse to the card's ground-truth drawn position (magenta
marker located via screenshot).
"""
import io
import json
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def run_case(p, dsf):
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=dsf)
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
        if page.evaluate("() => currentState?.priority_player") == 1:
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
    time.sleep(2.0)

    # Stamp a magenta marker at the card center via the draw pipeline.
    page.evaluate(
        """
        () => {
          const bc = battlefieldCanvas;
          const v = bc.stackVisuals[0];
          const wx = v.cx, wy = v.cy;
          const orig = bc._drawStackAndFx.bind(bc);
          bc._drawStackAndFx = (ctx) => {
            orig(ctx);
            ctx.save();
            ctx.fillStyle = "#ff00ff";
            ctx.beginPath();
            ctx.arc(wx, wy, 6 / bc.zoom, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
          };
          bc.needsRedraw = true;
        }
        """
    )
    time.sleep(0.5)

    shot = page.screenshot()
    img = Image.open(io.BytesIO(shot)).convert("RGB")
    w, h = img.size
    px = img.load()
    xs, ys, count = 0, 0, 0
    for yy in range(0, h):
        for xx in range(0, w):
            r, g, b = px[xx, yy]
            if r > 200 and b > 200 and g < 90:
                xs += xx
                ys += yy
                count += 1
    if count == 0:
        print(f"dsf={dsf}: marker not found")
        browser.close()
        return
    # Screenshot pixels are device px; mouse wants CSS px.
    mx, my = xs / count / dsf, ys / count / dsf
    page.mouse.move(mx, my, steps=5)
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
    print(f"dsf={dsf}: marker at CSS ({mx:.0f}, {my:.0f}) -> hover:", json.dumps(state))
    if errors:
        print(f"dsf={dsf} PAGE ERRORS:", errors)
    browser.close()


def main():
    with sync_playwright() as p:
        for dsf in (1, 1.25, 1.5):
            run_case(p, dsf)


if __name__ == "__main__":
    main()
