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

The browser is driven with **`playwright-cli`** (Microsoft's Playwright CLI) — see
the [playwright-cli skill](../playwright-cli/SKILL.md) for the full command
reference. It manages its own headless Chromium and runs as a persistent daemon:
every `playwright-cli` invocation talks to the **same default browser session**
until you `close` it, so you drive the app one command at a time across separate
shell calls. This skill documents only the LEA-specific launch + flow on top of it.

## Prerequisites (verified on Windows 11 / PowerShell)

- Python venv at `.venv\` with the web deps. Confirm:
  ```powershell
  .\.venv\Scripts\python.exe -m pip list | Select-String "fastapi|uvicorn|starlette|pydantic"
  ```
  Expected: fastapi 0.136.x, uvicorn 0.47.x, starlette 1.1.x, pydantic 2.13.x.
- `playwright-cli` installed globally (one-time):
  ```powershell
  npm install -g @playwright/cli@latest
  playwright-cli --version    # -> 0.1.x
  ```
  If the command is not found, the npm global bin (`%APPDATA%\npm`) isn't on
  PATH — add it, or call the shim directly: `& "$env:APPDATA\npm\playwright-cli.cmd" ...`.
  `playwright-cli` downloads its own Chromium on first use, so no system
  Chrome/Edge is required.

## Run (agent path) — START HERE

### 1. Launch the server (detached, survives across shell calls)

Each PowerShell tool call is its own process, so a `Start-Job` server dies when
that call returns. Launch it **detached** with `Start-Process` so it keeps
running while you drive the browser in later calls:

```powershell
$root = "c:\Users\qwv48_66yef5i\Desktop\Magic"
if (-not (Test-Path "$root\logs")) { New-Item -ItemType Directory -Force "$root\logs" | Out-Null }
$p = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","web.app:app","--host","127.0.0.1","--port","8010" `
  -WorkingDirectory $root `
  -RedirectStandardOutput "$root\logs\skill_server.log" `
  -RedirectStandardError  "$root\logs\skill_server.err.log" `
  -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 5
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/ -TimeoutSec 5).StatusCode   # -> 200
"server PID $($p.Id)"   # note this to stop it later
```

### 2. Drive the browser with playwright-cli

`playwright-cli` commands accept CSS selectors directly. Use `--raw eval` to read
a value out of the live page (prints just the result). The full menu→game flow:

```powershell
$pw = "playwright-cli"   # or "$env:APPDATA\npm\playwright-cli.cmd" if not on PATH
$shots = "c:\Users\qwv48_66yef5i\Desktop\Magic\.claude\skills\run-magic\shots"

& $pw open "http://127.0.0.1:8010/"
& $pw --raw eval "document.title"                         # -> "Magic LEA Web App"

# Home -> Host Game page (selectors are stable element ids from index.html).
& $pw click "#homeHostBtn"
& $pw --raw eval "!document.querySelector('#hostGamePage').classList.contains('hidden')"   # -> true

# Mode <select> defaults to human_vs_ai; create the session.
& $pw click "#startBtn"
Start-Sleep -Seconds 4    # session creation hits the API and deals opening hands

# Prove the game is live (the board is canvas-rendered, so check panels/canvas, not .card).
& $pw --raw eval "!document.querySelector('#boardPanel').classList.contains('hidden')"     # -> true
& $pw --raw eval "!!document.querySelector('#battlefieldCanvasWrap canvas')"               # -> true
& $pw --raw eval "document.querySelector('#promptTitle')?.textContent"                     # e.g. "You won the coin flip!"

& $pw screenshot --filename="$shots\flow.png"
& $pw close
```

**Open the PNG and look at it** — `flow.png` should show the game board (life
totals, mana pool, Stack panel, Current Prompt, phase rail), not the menu. The
exact prompt text varies with the pregame state (coin flip or mulligan); what
matters is the board panel and canvas being present.

### 3. Stop the server

```powershell
Stop-Process -Id <PID>        # the PID printed in step 1
# or, if you lost it:
Get-Process python | Where-Object { $_.Path -like "*Magic*venv*" } | Stop-Process -Force
```

### Common driving commands

Invoke as `& $pw <command> ...` (with `$pw` set as above). See the
[playwright-cli skill](../playwright-cli/SKILL.md) for the complete list.

| Goal | Command |
|---|---|
| Navigate / settle | `playwright-cli open <url>` (or `goto <url>` if already open) |
| Read a page value | `playwright-cli --raw eval "<jsExpr>"` |
| Read an element attr | `playwright-cli eval "el => el.textContent" "<selector>"` |
| Click | `playwright-cli click "<selector>"` |
| Screenshot to file | `playwright-cli screenshot --filename="<out.png>"` |
| Accessibility snapshot | `playwright-cli snapshot` (menu only — see canvas gotcha) |
| Inspect console / network | `playwright-cli console` / `playwright-cli requests` |
| Close the browser | `playwright-cli close` |

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
browser — for agents use the detached-server + playwright-cli path above.

## Gotchas

- **The battlefield is canvas-rendered.** `web/static/battlefield-canvas.js`
  paints cards/permanents onto a `<canvas>`. DOM selectors like `.card` find
  **nothing** on the board — `document.querySelectorAll(".card").length` is 0
  even mid-game, and `playwright-cli snapshot` won't list cards. To assert the
  game is live, check `#battlefieldCanvasWrap canvas` exists, or read panel text
  like `#promptTitle` / life totals, or query the JSON API
  (`/api/sessions/{id}/state`).
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
- **playwright-cli is a persistent daemon.** Commands share one default browser
  session across invocations until `close`/`close-all`. Start each fresh run
  with `playwright-cli close-all` if a stale session may be lingering. Session
  artifacts (snapshots, console logs) land in `.playwright-cli/` — gitignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `playwright-cli: command not found` | npm global bin not on PATH. Add `%APPDATA%\npm`, or call `& "$env:APPDATA\npm\playwright-cli.cmd" ...`. |
| `eval` / page shows title `127.0.0.1` or `ERR_CONNECTION_REFUSED` | The server isn't running (a `Start-Job` server dies with its shell). Relaunch detached via step 1; confirm `200`. |
| `playwright-cli` reports a missing/undownloaded browser | First run downloads Chromium automatically; re-run, or `npx playwright install chromium`. |
| `board visible: false` after Create Session | Increase the post-`#startBtn` settle (3–5 s); session creation deals opening hands and can be slow on first run. |
| API returns 422 on session create | Use a valid `mode` literal (see Gotchas), not `"ai"`. |
| screenshot PNG shows the menu, not the board | The flow didn't reach the board — confirm `#startBtn` was clicked and the settle elapsed before `screenshot`. |
