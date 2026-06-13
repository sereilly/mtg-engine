"""Test: a click-held priority lock survives taking actions.

Flow (human vs human, we drive seat 1 via the API):
1. Play a land, debug-cast Wrath of God (sits on the stack).
2. Click the floating stack card -> hold locked.
3. Tap the land for mana -> hold and priority must persist.
4. Debug-cast Dark Ritual in response -> hold must persist, marker follows
   the original card (now index 1; the response is on top at index 0).
5. Click the held card again -> released; auto-pass resumes and, with seat 1
   passing, the stack drains.
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

        # 1. Play a land from hand.
        land = page.evaluate(
            """
            () => {
              const hand = currentState.players[0].hand;
              const i = hand.findIndex((c) => (c.type || "").toLowerCase().includes("land"));
              return i >= 0 ? hand[i].name : null;
            }
            """
        )
        if not land:
            print("no land in hand; aborting")
            browser.close()
            return
        page.evaluate(f'async () => sendAction({{seat: 0, action: "cast", card_name: "{land}"}})')
        time.sleep(0.6)

        # Cast the spell to respond to.
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
            timeout=10000,
        )

        # 2. Hover the card's slot immediately (hover-hold beats the auto-pass
        #    during the dwell), let it settle, then click to lock.
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
        time.sleep(2.0)  # settle into the cascade while hover-holding
        page.mouse.click(pt["x"], pt["y"])
        time.sleep(0.3)
        held = page.evaluate("() => stackClickHold !== null && getHeldStackArrayIndex() === 0")
        check("click locks hold", held)

        # Move the mouse away so only the click-hold is in effect.
        page.mouse.move(400, 800, steps=3)
        time.sleep(0.3)

        # 3. Tap the land for mana.
        land_idx = page.evaluate(
            """
            () => currentState.players[0].battlefield.findIndex(
              (c) => (c.type || "").toLowerCase().includes("land"))
            """
        )
        page.evaluate(f'async () => sendAction({{seat: 0, action: "tap", permanent_index: {land_idx}}})')
        time.sleep(2.5)  # long enough for a broken auto-pass to fire

        st = page.evaluate(
            """
            () => ({
              held: stackClickHold !== null,
              heldIdx: getHeldStackArrayIndex(),
              priority: currentState.priority_player,
              stackLen: (currentState.stack || []).length,
              tapped: currentState.players[0].battlefield.some((c) => c.tapped),
            })
            """
        )
        check(
            "hold + priority survive tapping a land",
            st["held"] and st["priority"] == 0 and st["stackLen"] == 1 and st["tapped"],
            json.dumps(st),
        )

        # 4. Cast a response while holding.
        page.evaluate(
            """
            async () => {
              q("debugCardSearch").value = "Dark Ritual";
              await castDebugCardForFree();
            }
            """
        )
        page.wait_for_function("() => (currentState?.stack || []).length === 2", timeout=10000)
        time.sleep(2.5)

        st = page.evaluate(
            """
            () => ({
              held: stackClickHold !== null,
              heldIdx: getHeldStackArrayIndex(),
              canvasHeldIdx: battlefieldCanvas.stackHeldIndex,
              priority: currentState.priority_player,
              stackLen: (currentState.stack || []).length,
              topName: currentState.stack[0]?.card?.name,
            })
            """
        )
        check(
            "hold survives casting a response; marker follows original card",
            st["held"] and st["heldIdx"] == 1 and st["canvasHeldIdx"] == 1
            and st["priority"] == 0 and st["stackLen"] == 2 and st["topName"] == "Dark Ritual",
            json.dumps(st),
        )

        # 5. Click the held (bottom) card on its uncovered corner to release.
        pt = page.evaluate(
            """
            () => {
              const v = battlefieldCanvas.stackVisuals[1];
              const c = battlefieldCanvas.worldToCanvas(v.cx - 45, v.cy - 65);
              return battlefieldCanvas._canvasToPage(c.x, c.y);
            }
            """
        )
        page.mouse.click(pt["x"], pt["y"])
        time.sleep(0.3)
        released = page.evaluate("() => stackClickHold === null")
        check("second click releases hold", released)

        # Move clear of the cascade so no hover-hold remains, then let it drain.
        page.mouse.move(400, 800, steps=3)
        drained = False
        deadline = time.time() + 20
        while time.time() < deadline:
            if page.evaluate("() => (currentState?.stack || []).length === 0"):
                drained = True
                break
            if page.evaluate("() => currentState?.priority_player") == 1:
                api_action({"seat": 1, "action": "pass_priority"})
            time.sleep(0.4)
        check("stack drains after release", drained)

        if errors:
            print("PAGE ERRORS:", errors)
        browser.close()

    print()
    print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAILED")


if __name__ == "__main__":
    main()
