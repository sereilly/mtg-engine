---
name: run-magic
description: Build, launch, screenshot, and drive the MTG LEA web app (FastAPI + browser game UI). Use to run/start the server, take a screenshot of the board, start a human-vs-AI game in a browser, or verify a UI/engine change works in the real running app.
---

# Run the MTG LEA web app

This repo is a single deployable unit: a text-based Magic: The Gathering rules
engine (`engine/`) served behind a FastAPI web app (`web/app.py`) with a
browser game UI (`web/static/`). The board is drawn on an HTML canvas
(`web/static/battlefield-canvas.js`), so it is driven through a real browser.

**Paths below are relative to the repo root** (`c:\Users\qwv48_66yef5i\Desktop\Magic`).

The agent harness for the browser is
[.claude/skills/run-magic/driver.py](.claude/skills/run-magic/driver.py) — a
small Python script built on [Playwright](https://playwright.dev/python/), which
is installed in the workspace venv (`playwright` + its bundled Chromium). It runs
headless and manages its own browser, so no system Chrome/Edge is required.

## Prerequisites (verified on Windows 11 / PowerShell)

- Python venv already present at `.venv\` with the web deps. Confirm:
  ```powershell
  .\.venv\Scripts\python.exe -m pip list | Select-String "fastapi|uvicorn|starlette|pydantic|playwright"
  ```
  Expected: fastapi 0.136.x, uvicorn 0.47.x, starlette 1.1.x, pydantic 2.13.x,
  playwright 1.60.x.
- Playwright's Chromium browser installed (one-time, already done in this
  environment). If `driver.py` reports a missing browser, install it with:
  ```powershell
  .\.venv\Scripts\python.exe -m playwright install chromium
  ```

## Run (agent path) — START HERE

### 1. Launch the server in the background

```powershell
Start-Job -Name mtg -ScriptBlock { Set-Location "c:\Users\qwv48_66yef5i\Desktop\Magic"; & ".\.venv\Scripts\python.exe" -m uvicorn web.app:app --host 127.0.0.1 --port 8010 *>&1 | Out-File "c:\Users\qwv48_66yef5i\Desktop\Magic\logs\skill_server.log" }
Start-Sleep -Seconds 4
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/ -TimeoutSec 5).StatusCode   # -> 200
```

### 2. Drive the browser with the driver

Run the driver with the venv python. Paths below are relative to the repo root.

```powershell
Set-Location "c:\Users\qwv48_66yef5i\Desktop\Magic"
$py = ".\.venv\Scripts\python.exe"
$drv = ".claude\skills\run-magic\driver.py"

# Screenshot the home menu.
& $py $drv shot http://127.0.0.1:8010/ .claude/skills/run-magic/shots/home.png

# Read any value out of the live page (prints JSON).
& $py $drv eval http://127.0.0.1:8010/ "document.title"        # -> "Magic LEA Web App"

# Full scripted flow: Home -> Host Game -> Create Session (human vs AI),
# then screenshot the live board. Prints progress + the in-game prompt.
& $py $drv flow .claude/skills/run-magic/shots/flow.png
```

`flow` output on success (exit 0):
```
home shown: True
host page: True
board visible: True
prompt: Keep or Mulligan?
canvas: True
saved .claude/skills/run-magic/shots/flow.png
```
(The exact `prompt` text varies with the pregame state — e.g. a coin-flip or
mulligan prompt. What matters is `board visible: True` and `canvas: True`.)

Screenshots land in `.claude/skills/run-magic/shots/`. **Open the PNG and look
at it** — `flow.png` should show the game board (life totals, mana pool, stack
panel, phase rail), not the menu.

### 3. Stop the server

```powershell
Stop-Job -Name mtg; Remove-Job -Name mtg
```

### Driver subcommands

Invoke as `& $py $drv <command> ...` (with `$py`/`$drv` set as above).

| Command | What it does |
|---|---|
| `driver.py shot <url> <out.png>` | Navigate, settle, screenshot |
| `driver.py eval <url> "<jsExpr>"` | Navigate, print JSON of `jsExpr` evaluated in the page |
| `driver.py evalshot <url> "<jsExpr>" <out.png>` | Navigate, run `jsExpr`, then screenshot |
| `driver.py click <url> <selector> <out.png>` | Navigate, click a selector, screenshot |
| `driver.py flow <out.png>` | Full menu→game flow, screenshot the live board |

Env: `APP_URL` (default `http://127.0.0.1:8010`), `HEADED=1` (visible window
instead of headless).

## Direct invocation (no browser) — drive the engine / API

Most engine PRs don't need the browser. Hit the engine or HTTP API directly:

```powershell
# REST: create a human-vs-AI session (note the literal mode strings).
$body = '{"mode":"human_vs_ai","host_name":"Tester","host_colors":2,"guest_colors":2}'
Invoke-WebRequest -UseBasicParsing -Method Post "http://127.0.0.1:8010/api/sessions" -ContentType "application/json" -Body $body

# Scripted duel against the engine (no server, deterministic):
.\.venv\Scripts\python.exe scripts/run_duel.py

# Card-support coverage report:
.\.venv\Scripts\python.exe scripts/support_report.py     # -> all categories supported, none unsupported
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest                     # full suite
.\.venv\Scripts\python.exe -m pytest tests/test_web_api.py -q   # fast HTTP-layer subset (39 tests)
```

## Run (human path)

`README.md` documents `uvicorn ... --host 0.0.0.0 --port 8010`, then open
`http://127.0.0.1:8010/` in a real browser and click through the menu. That
foreground form blocks the shell and is only useful with a human at a real
browser — for agents use the background-job + driver path above.

## Gotchas

- **The battlefield is canvas-rendered.** `web/static/battlefield-canvas.js`
  paints cards/permanents onto a `<canvas>`. DOM selectors like `.card` find
  **nothing** on the board — `document.querySelectorAll(".card").length` is 0
  even mid-game. To assert the game is live, check
  `#battlefieldCanvasWrap canvas` exists, or read panel text like `#promptTitle`
  / life totals, or query the JSON API (`/api/sessions/{id}/state`).
- **Session `mode` must be a literal.** The API rejects `"ai"` with HTTP 422 —
  valid values are exactly `human_vs_ai`, `ai_vs_ai`, `human_vs_human`.
- **The menu flow auto-runs the coin flip.** Clicking "Create Session"
  (`#startBtn`) from the Host Game page lands you on a coin-flip pregame prompt
  (`#promptTitle` = "You won the coin flip!"), even though the REST
  `enable_pregame` field defaults to false — the UI enables it. The board is
  already visible behind the prompt.
- **Real menu selectors** (from `web/static/index.html`): `#homeHostBtn` →
  `#hostGamePage`, the `#mode` `<select>`, `#startBtn` ("Create Session"),
  board container `#boardPanel` (loses its `hidden` class when the game starts).
- **Each driver run launches its own Playwright Chromium** in a fresh context
  and closes it on exit, so multiple `driver.py` runs don't collide; nothing to
  clean up.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `driver.py` prints `ERROR ...Executable doesn't exist...` | Playwright's Chromium isn't installed. Run `.\.venv\Scripts\python.exe -m playwright install chromium`. |
| `flow` shows `board visible: False` (exit 1) | Server not running or wrong port. Confirm step 1 returned `200` and `APP_URL` matches. |
| API returns 422 on session create | Use a valid `mode` literal (see Gotchas), not `"ai"`. |
| `shot`/`flow` PNG shows the menu, not the board | Increase the post-`Create Session` settle in `driver.py` (`flow` waits 3500 ms); session creation deals opening hands and can be slow on first run. |
