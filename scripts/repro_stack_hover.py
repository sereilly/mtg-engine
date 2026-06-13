"""Repro: hover the floating stack card on the battlefield canvas.

Starts a human-vs-human session (no pregame), debug-casts a no-target spell so
it sits on the stack, then moves the mouse over the floating stack card and
reports the canvas hover/hold state.
"""
import json
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
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

        # If the other (uncontrolled) seat has the turn, drive it via the API
        # until seat 0 has priority in its own main phase.
        import urllib.request

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

        join_req = urllib.request.Request(
            f"{BASE}/api/sessions/{session_id}/join",
            data=json.dumps({"guest_name": "P2"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(join_req).read()

        deadline = time.time() + 30
        while time.time() < deadline:
            ready = page.evaluate(
                "() => !!(currentState && currentState.priority_player === 0 && "
                "currentState.current_turn === 0 && "
                "currentState.current_turn_phase === 'precombat_main')"
            )
            if ready:
                break
            st = page.evaluate(
                "() => ({turn: currentState?.current_turn, prio: currentState?.priority_player, "
                "phase: currentState?.current_turn_phase})"
            )
            if st["prio"] == 1:
                resp = api_action({"seat": 1, "action": "pass_priority"})
                if "error" in resp:
                    print("seat1 pass error:", resp["error"], "state:", st)
            time.sleep(0.4)
        else:
            st = page.evaluate(
                "() => ({turn: currentState?.current_turn, prio: currentState?.priority_player, "
                "phase: currentState?.current_turn_phase, step: currentState?.current_step, "
                "logTail: (currentState?.log || []).slice(-8)})"
            )
            print("FINAL STATE:", json.dumps(st, indent=2))
            raise RuntimeError("never reached seat 0 main phase")

        # Cast a spell with no targets for free so it sits on the stack.
        page.evaluate(
            """
            async () => {
              q("debugCardSearch").value = "Wrath of God";
              await castDebugCardForFree();
            }
            """
        )
        try:
            page.wait_for_function(
                "() => currentState && Array.isArray(currentState.stack) && currentState.stack.length > 0",
                timeout=10000,
            )
        except Exception:
            diag = page.evaluate(
                """
                () => ({
                  debugStatus: q("debugStatus")?.textContent,
                  stack: currentState?.stack,
                  phase: currentState?.current_turn_phase,
                  priority: currentState?.priority_player,
                  logTail: (currentState?.log || []).slice(-6),
                })
                """
            )
            print("CAST DIAG:", json.dumps(diag, indent=2))
            print("PAGE ERRORS:", errors)
            browser.close()
            return
        # Let the cast animation fly the card into the stack slot.
        time.sleep(1.5)

        info = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[0];
              if (!v) return { error: "no stack visual" };
              const c = battlefieldCanvas.worldToCanvas(v.cx, v.cy);
              const pt = battlefieldCanvas._canvasToPage(c.x, c.y);
              return {
                world: { cx: v.cx, cy: v.cy, scale: v.scale },
                canvas: c,
                page: pt,
                cssW: battlefieldCanvas.cssW,
                cssH: battlefieldCanvas.cssH,
                zoom: battlefieldCanvas.zoom,
              };
            }
            """
        )
        print("stack visual:", json.dumps(info, indent=2))
        if "error" in info:
            print("PAGE ERRORS:", errors)
            browser.close()
            return

        x, y = info["page"]["x"], info["page"]["y"]
        page.mouse.move(x, y)
        time.sleep(0.3)

        hover_state = page.evaluate(
            """
            () => ({
              hoveredStackIndex: battlefieldCanvas.hoveredStackIndex,
              stackCanvasHoverActive: stackCanvasHoverActive,
              previewName: q("cardPreviewName").textContent,
              elementAtPoint: (() => {
                const el = document.elementFromPoint(%f, %f);
                return el ? el.tagName + "." + el.className : null;
              })(),
            })
            """
            % (x, y)
        )
        print("after hover:", json.dumps(hover_state, indent=2))

        # Click to lock the hold.
        page.mouse.click(x, y)
        time.sleep(0.3)
        click_state = page.evaluate(
            """
            () => ({
              stackClickHoldActive: stackClickHold !== null,
              stackClickHoldIndex: getHeldStackArrayIndex(),
              canvasHeldIndex: battlefieldCanvas.stackHeldIndex,
            })
            """
        )
        print("after click:", json.dumps(click_state, indent=2))

        # Move away: hover should end, click-hold should remain.
        page.mouse.move(100, 100)
        time.sleep(0.3)
        away_state = page.evaluate(
            """
            () => ({
              hoveredStackIndex: battlefieldCanvas.hoveredStackIndex,
              stackCanvasHoverActive: stackCanvasHoverActive,
              stackClickHoldActive: stackClickHold !== null,
            })
            """
        )
        print("after move away:", json.dumps(away_state, indent=2))
        print("PAGE ERRORS:", errors if errors else "none")
        browser.close()


if __name__ == "__main__":
    main()
