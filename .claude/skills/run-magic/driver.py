#!/usr/bin/env python
"""Playwright browser driver for the Magic LEA web app.

Drives the canvas-rendered board through a real Chromium that Playwright
manages, so no system Chrome/Edge path detection is needed. Run it with the
workspace venv python (it has `playwright` installed):

    .\\.venv\\Scripts\\python.exe .claude/skills/run-magic/driver.py <cmd> ...

Subcommands (see SKILL.md for the canonical invocations):
  shot   <url> <outfile>              navigate, settle, PNG screenshot
  eval   <url> <jsExpr>               navigate, print JSON result of jsExpr
  evalshot <url> <jsExpr> <outfile>   navigate, run jsExpr, then screenshot
  click  <url> <selector> <outfile>   navigate, click selector, screenshot
  flow   <outfile>                    full scripted flow: start a human-vs-AI
                                       game from the menu, screenshot the board

Env:
  APP_URL    base app url (default http://127.0.0.1:8010)
  HEADED=1   launch a visible window instead of headless
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8010")
HEADED = bool(os.environ.get("HEADED"))


def navigate(page, url):
    page.goto(url or APP_URL, wait_until="load")
    # The app boots its menu synchronously; a short settle plus a readyState
    # poll is reliable enough for screenshots/eval.
    page.wait_for_function("() => document.readyState === 'complete'", timeout=10000)
    page.wait_for_timeout(400)


def js_eval(page, expr):
    """Evaluate a page-side JS expression and return its (JSON) value.

    Mirrors the old CDP driver: wraps the expression so a thrown error comes
    back as {"__err": ...} instead of crashing the call. Playwright auto-awaits
    a returned promise.
    """
    wrapped = (
        "(async () => { try { return (%s); } catch (e) { return { __err: String(e) }; } })()"
        % expr
    )
    return page.evaluate(wrapped)


def main():
    args = sys.argv[1:]
    if not args:
        print("usage: driver.py <shot|eval|evalshot|click|flow> ...", file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    exit_code = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED, args=["--window-size=1400,900"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            if cmd == "shot":
                url = rest[0] if rest else APP_URL
                out = rest[1] if len(rest) > 1 else "shots/app.png"
                navigate(page, url)
                page.screenshot(path=out)
                print("saved", out)
            elif cmd == "eval":
                url = rest[0] if rest else APP_URL
                expr = rest[1] if len(rest) > 1 else "document.title"
                navigate(page, url)
                print(json.dumps(js_eval(page, expr), indent=2))
            elif cmd == "evalshot":
                url, expr = rest[0], rest[1]
                out = rest[2] if len(rest) > 2 else "shots/evalshot.png"
                navigate(page, url)
                print("eval", json.dumps(js_eval(page, expr)))
                page.wait_for_timeout(500)
                page.screenshot(path=out)
                print("saved", out)
            elif cmd == "click":
                url, sel = rest[0], rest[1]
                out = rest[2] if len(rest) > 2 else "shots/click.png"
                navigate(page, url)
                clicked = js_eval(
                    page,
                    "(() => { const el = document.querySelector(%s);"
                    " if (!el) return { clicked: false }; el.click();"
                    " return { clicked: true }; })()" % json.dumps(sel),
                )
                print("click", json.dumps(clicked))
                page.wait_for_timeout(600)
                page.screenshot(path=out)
                print("saved", out)
            elif cmd == "flow":
                out = rest[0] if rest else "shots/flow.png"
                navigate(page, APP_URL)
                print("home shown:", js_eval(page, '!!document.querySelector("#homeHostBtn")'))
                # Home -> Host Game page. Selectors are stable element ids from index.html.
                page.click("#homeHostBtn")
                page.wait_for_timeout(500)
                print(
                    "host page:",
                    js_eval(page, '!document.querySelector("#hostGamePage").classList.contains("hidden")'),
                )
                # Mode select defaults to "human_vs_ai"; set it explicitly to be safe,
                # then click "Create Session" (#startBtn).
                js_eval(
                    page,
                    "(() => { const s = document.querySelector('#mode');"
                    " s.value = 'human_vs_ai';"
                    " s.dispatchEvent(new Event('change', { bubbles: true }));"
                    " return s.value; })()",
                )
                page.click("#startBtn")
                # Session creation hits the API and deals opening hands; give it time.
                page.wait_for_timeout(3500)
                board = js_eval(
                    page, '!document.querySelector("#boardPanel").classList.contains("hidden")'
                )
                print("board visible:", board)
                # The battlefield is canvas-rendered (battlefield-canvas.js), so cards are
                # NOT DOM nodes. Prove the game is live via the prompt/canvas instead.
                print(
                    "prompt:",
                    js_eval(page, '(document.querySelector("#promptTitle")||{}).textContent || null'),
                )
                print("canvas:", js_eval(page, '!!document.querySelector("#battlefieldCanvasWrap canvas")'))
                page.screenshot(path=out)
                print("saved", out)
                if not board:
                    exit_code = 1
            else:
                print("usage: driver.py <shot|eval|evalshot|click|flow> ...", file=sys.stderr)
                exit_code = 2
        except Exception as e:  # noqa: BLE001 - report and exit non-zero
            print("ERROR", e, file=sys.stderr)
            exit_code = 1
        finally:
            browser.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
