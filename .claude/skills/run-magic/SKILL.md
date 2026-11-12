---
name: run-magic
description: Build, launch, screenshot, and drive the MTG Simulacrum web app (FastAPI + browser game UI). Use to run/start the server, take a screenshot of the board, start a human-vs-AI game in a browser, or verify a UI/engine change works in the real running app.
---

# Run the MTG Simulacrum web app

This repo is a single deployable unit: a text-based Magic: The Gathering rules
engine (`engine/`) served behind a FastAPI web app (`web/app.py`) with a
browser game UI (`web/static/`). The board is drawn on an HTML canvas
(`web/static/battlefield-canvas.js`), so it is driven through a real browser.

**Paths below are relative to the repo root**, which is where the PowerShell
tool starts — the snippets read it with `(Get-Location).Path` rather than
spelling out one machine's clone. `.\setup.cmd` installs everything listed under
Prerequisites.

The browser is driven with **`playwright-cli`** (Microsoft's Playwright CLI) — see
the [playwright-cli skill](../playwright-cli/SKILL.md) for the full command
reference. It manages its own headless Chromium and runs as a persistent daemon:
every `playwright-cli` invocation talks to the **same default browser session**
until you `close` it, so you drive the app one command at a time across separate
shell calls. This skill documents only the MTG Simulacrum-specific launch + flow on top of it.

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
$root = (Get-Location).Path   # the repo root
if (-not (Test-Path "$root\logs")) { New-Item -ItemType Directory -Force "$root\logs" | Out-Null }
$p = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","web.app:app","--host","127.0.0.1","--port","8010" `
  -WorkingDirectory $root `
  -RedirectStandardOutput "$root\logs\skill_server.log" `
  -RedirectStandardError  "$root\logs\skill_server.err.log" `
  -WindowStyle Hidden -PassThru
# Up in ~2 s when the compiled-program store for this engine is there; the first
# start after an engine edit compiles the pool and writes it (~20 s).
$deadline = (Get-Date).AddSeconds(60)
do {
  Start-Sleep -Milliseconds 500
  try { $code = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/ -TimeoutSec 2).StatusCode } catch { $code = $null }
} until ($code -eq 200 -or (Get-Date) -gt $deadline)
$code   # -> 200
"server PID $($p.Id)"   # note this to stop it later
```

### 2. Drive the browser with playwright-cli

`playwright-cli` commands accept CSS selectors directly. Use `--raw eval` to read
a value out of the live page (prints just the result). The full menu→game flow:

```powershell
$pw = "playwright-cli"   # or "$env:APPDATA\npm\playwright-cli.cmd" if not on PATH
$shots = "$((Get-Location).Path)\.claude\skills\run-magic\shots"

& $pw open "http://127.0.0.1:8010/"
& $pw --raw eval "document.title"                         # -> "MTG Simulacrum"

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
.\.venv\Scripts\python.exe scripts/support_report.py     # whole manifest pool -> all categories supported, none unsupported
.\.venv\Scripts\python.exe scripts/support_report.py --set ARN   # one set, by its code in cards/manifest.json
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest                     # full suite
.\.venv\Scripts\python.exe -m pytest tests/ui/test_web_api.py -q   # fast HTTP-layer subset
```

## Run (human path)

`README.md` documents `uvicorn ... --host 0.0.0.0 --port 8010`, then open
`http://127.0.0.1:8010/` in a real browser and click through the menu. That
foreground form blocks the shell and is only useful with a human at a real
browser — for agents use the detached-server + playwright-cli path above.

## Verifying one card in-game

The full loop for "does this card actually work in the app", which is what
`CARD_VERIFICATION.md` records. Fixing a card in the engine does **not** clear a
failing row — only a recorded in-game check does.

```powershell
& $pw resize 1920 1080     # do this FIRST — see the prompt-panel gotcha below
& $pw click "#homeHostBtn"; & $pw click "#startBtn"; Start-Sleep 5
# Pregame: "Go First"/"Go Second", then "Keep Hand" — find their refs with `snapshot`.

# Put the card and its supporting board in play, from the Debug Menu.
& $pw click "#debugToggleBtn"
& $pw fill "#debugCardSearch" "Candelabra of Tawnos"; Start-Sleep 2
& $pw click "#debugCastFreeBtn"            # onto YOUR battlefield
& $pw click "#debugCastFreeOpponentBtn"    # onto the opponent's (for a target)
& $pw click "#debugAddManaToggle"          # adds a clickable mana rail down the right edge
& $pw click "#debugCloseBtn"
```

Then **click the permanent on the canvas** by its id (next section), drive
whatever prompts appear, and check the result against the state API rather
than the picture:

```powershell
$sid = (& $pw requests) -match 'api/sessions/(\w+)' | Out-Null; $matches[1]
.\.venv\Scripts\python.exe -c "import json,urllib.request; s=json.load(urllib.request.urlopen('http://127.0.0.1:8010/api/sessions/$sid/state?seat=0')); print([(c['name'],c.get('tapped')) for c in s['players'][0]['battlefield']]); print(s['log'][-5:])"
```

Record the result the way the tracker expects — the Debug Menu, not the JSON:

```powershell
& $pw click "#debugToggleBtn"; & $pw click "#debugMarkResultBtn"
& $pw fill "#verifyCardName" "Candelabra of Tawnos"; Start-Sleep 2
& $pw click "#verifyResultRow input[value='pass']"    # or value='fail' + a reason
& $pw click "#verifyResultSubmitBtn"
& $pw --raw eval "document.querySelector('#debugVerifyProgress').textContent"
```

That rewrites `CARD_VERIFICATION.md` and `card_verification.json` on disk.

## Clicking a card by its id

The board is a canvas, so no selector reaches a permanent. The page carries a
read-only debug accessor instead (`web/static/app.js`,
`BattlefieldCanvas.debugPositions`): **`window.__boardPositions()`** returns,
as the page stands now, every drawn object's page rectangle and a point a
real click lands on, and **`window.__boardPoint(ref)`** is that point as
`"x y"` (`""` when there is none). The point is found by sending candidate
points back through the canvas's own press path (`_pressTarget`, what a
mouse-down asks), so an Equipment or Aura tucked under its creature, or a
lower card of a pile, gets a point on its **visible strip**, and a point a
DOM panel covers (the prompt dock at narrow widths) is never reported.

`ref` is a permanent id (the payload's `id`, stable while the permanent
stays — CR 400.7), `"hand:N"`, `"stack:N"`, `"emblem:N"`, `"<zone>:<seat>"`
(`library`, `graveyard`, `exile`, `command`, `ante`, `sideboard`), or a name
(the first permanent, else hand card, so named).

```sh
# Git Bash, your own playwright-cli session (-s=<name>)
XY=$(playwright-cli -s=me --raw eval "__boardPoint(12)" | tr -d '"')
[ -n "$XY" ] && { playwright-cli -s=me mousemove $XY; playwright-cli -s=me mousedown; playwright-cli -s=me mouseup; }
```
```powershell
$xy = (& $pw --raw eval "__boardPoint(12)").Trim('"')
if ($xy) { $x, $y = $xy.Split(' '); & $pw mousemove $x $y; & $pw mousedown; & $pw mouseup }
```

`mousedown`/`mouseup` take `right` for the context menu. What
`__boardPositions()` holds:

| Field | What |
|---|---|
| `settled` | false while a card, the stack or a camera is still easing — a point read then can move; read again |
| `mana_fan_open` | the land mana fan is modal and takes every press |
| `permanents[]` | `id`, `seat`, `index` (battlefield slot), `name`, `printed_name`, `tapped`, `attached_to_id`, `group` (`{kind: "aura"\|"pile", position, size}` — position 0 is the host / bottom), `rect` `{x,y,w,h}`, `click` `{x,y}` or null, `share` (how much of the card a click can reach: ~0.18 for a tucked attachment) |
| `stack[]`, `zones[]`, `emblems[]` | the floating stack cascade by index, the zone piles by seat and kind, the viewer's emblems — each with `rect`, `click`, `share` |
| `hand[]` | the viewer's hand: `index`, `name`, `selector` (`#selfHand .hand-fan-slot[data-hand-index="N"]`), `rect`, `click`, `share` — fanned cards overlap, so click the point, not the selector's centre |

```sh
playwright-cli -s=me --raw eval "JSON.stringify(__boardPositions().permanents.map(p => [p.id, p.name, p.click, p.share]))"
```

## Keeping a board across a code change

Every server-side edit used to mean restarting the server and rebuilding the
game. `scripts/integration/serve_board.py --reload` supervises the app
process: on a change to a `.py` under `engine/` or `web/` (or a card file) it
saves every session, starts the app on the new code and loads them back
before it serves — same session id, same permanent ids, the stack and any
prompt still open (a resolution suspended for an answer included), the log
and the undo history. **The page does not reload**: its event stream
reconnects and re-fetches. A `web/` edit is serving again in ~5 s, an engine
edit in ~25 s (the pool's compile).

```powershell
$scr = "<your scratch>"   # holds cmd/ (the command folder), and the logs
$p = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "-u","scripts/integration/serve_board.py","--port","<port>","--cmd","$scr\cmd","--reload" `
  -WorkingDirectory $root -RedirectStandardOutput "$scr\server.log" -RedirectStandardError "$scr\server.err.log" `
  -WindowStyle Hidden -PassThru
# Stop-Process -Id $p.Id stops the supervisor and the app with it.
```

After an edit, wait for `<cmd>/serve_board.state` to read `state=up` with
the next `generation`; `server.log` says what changed, what was saved and
restored. A session that cannot be saved keeps the old process serving on
the old code (`state=up-old-code`, the reason in the log), retried every ten
seconds. `--restore <cmd>/board.pickle` without `--reload` starts a server on
the last saved board. What a session keeps and does not is
`scripts/integration/board_pickle.py`'s docstring.

**A client edit** (`web/static/`) restarts nothing: bump `index.html`'s `?v=`,
then reload the page **into the same game** — open
`http://127.0.0.1:<port>/?session=<sessionId>`, wait out the 5 s presence
grace (`web/presence.py`), and click the seat's **Rejoin** button
(`.rejoin-seat-btn[data-seat='0']`). `sessionId` is a page global
(`playwright-cli --raw eval "sessionId"`).

## Gotchas

- **`fill` on the Debug Menu's card box does not select the card.**
  `#debugCardSearch` is an `<input>` backed by a `<datalist>`, and the app arms
  "Cast Selected Card For Free" from an `input`/`change` handler that
  `playwright-cli fill` does not trigger — so the button stays enabled, the click
  returns 200, and **nothing reaches the battlefield**. Set the value and
  dispatch both events:
  ```powershell
  & $pw --raw eval "(()=>{const i=document.querySelector('#debugCardSearch'); i.value='Yavimaya Scion'; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); return i.value;})()"
  ```
  The same applies to `#verifyCardName` on the Mark Test Result form. Always
  confirm against the state API that the permanent actually arrived, rather than
  trusting the click.
- **Driving an activated ability over HTTP beats clicking the canvas.** The
  action body is `{"seat":0,"action":"activate","permanent_index":N,"id":M}` —
  note `action`, not `kind` (the schema rejects `kind` with a 422 naming the
  missing field). `"tap"` with the same shape taps a land for mana, which is how
  you pay for the ability without hunting for the debug mana rail.
- **Clicking a permanent means clicking a coordinate.** There is no selector for
  one: take its point from `__boardPoint(<id>)` ("Clicking a card by its id"
  above) and use real mouse events — `mousemove <x> <y>`, then `mousedown`,
  then `mouseup` (three separate commands). `click` needs a selector and
  cannot reach the board.
- **Resize to 1920x1080 before touching the board.** At the default width the
  Current Prompt panel sits on top of the right-hand half of your own
  battlefield row, so a permanent that exists is unclickable — and the board
  **re-lays out** whenever a permanent enters either side, which silently moves
  whatever you were about to click. Ask `__boardPoint` again after every state
  change, once `__boardPositions().settled` is true.
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
  session across invocations until `close`. When agents drive browsers in
  parallel, each uses its own session (`playwright-cli -s=<name> …`) and its
  own server port, and closes only that session — `close-all` closes every
  agent's browser. Session artifacts (snapshots, console logs) land in
  `.playwright-cli/` — gitignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `playwright-cli: command not found` | npm global bin not on PATH. Add `%APPDATA%\npm`, or call `& "$env:APPDATA\npm\playwright-cli.cmd" ...`. |
| `eval` / page shows title `127.0.0.1` or `ERR_CONNECTION_REFUSED` | The server isn't running (a `Start-Job` server dies with its shell). Relaunch detached via step 1; confirm `200`. |
| `playwright-cli` reports a missing/undownloaded browser | First run downloads Chromium automatically; re-run, or `npx playwright install chromium`. |
| `board visible: false` after Create Session | Increase the post-`#startBtn` settle (3–5 s); session creation deals opening hands and can be slow on first run. |
| API returns 422 on session create | Use a valid `mode` literal (see Gotchas), not `"ai"`. |
| screenshot PNG shows the menu, not the board | The flow didn't reach the board — confirm `#startBtn` was clicked and the settle elapsed before `screenshot`. |
