"""The real web app, plus a command folder that sets up boards with engine calls.

    python scripts/integration/serve_board.py --port 8022 --cmd .worktrees/scratch/$ROUND/<group>/cmd

Run from a tree's root (it serves that tree's engine and client). Start a game
in the browser as usual, then drop a ``.py`` file into the command folder: it
is executed under the session's lock and the session is notified, so the board
redraws and the *gesture* is what gets clicked — setting a board up by hand
in the browser took most of a client round (W2G6 at Mirrodin wrote this).

A command file whose first line is ``# sid=<session id>`` (the id is in the
browser's URL and in the server's session store) runs with ``session``,
``game`` and ``sid`` in scope; every file has ``store``, ``card(name)``,
``place(game, seat, name)``, ``notify(sid)`` and ``latest()`` (the newest
session). Its output lands in ``<name>.out`` and the file is renamed
``<name>.done``. For driving the page itself, see the ``run-magic`` skill.
"""

from __future__ import annotations

import argparse
import io
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from board import card, place  # noqa: E402


def run_command(path: Path, scope: dict, session_lock, notify) -> None:
    out = io.StringIO()
    source = path.read_text(encoding="utf-8")
    first = source.splitlines()[0] if source else ""
    sid = first.split("=", 1)[1].strip() if first.startswith("# sid=") else None
    scope = dict(scope, sid=sid)
    try:
        if sid:
            scope["session"] = scope["store"].get(sid)
            scope["game"] = scope["session"].game
            with session_lock(sid), redirect_stdout(out):
                exec(compile(source, str(path), "exec"), scope)
            notify(sid)
        else:
            with redirect_stdout(out):
                exec(compile(source, str(path), "exec"), scope)
    except Exception:
        out.write(traceback.format_exc())
    path.with_suffix(".out").write_text(out.getvalue(), encoding="utf-8")
    path.replace(path.with_suffix(".done"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8022)
    parser.add_argument("--cmd", type=Path, required=True, help="the command folder to watch")
    args = parser.parse_args()

    import uvicorn

    from web.app import app, store
    from web.events import _notify_session_change
    from web.runtime import session_lock

    def notify(sid):
        _notify_session_change(sid, "raw_state")

    def latest():
        sessions = getattr(store, "_sessions", {})
        return list(sessions.values())[-1] if sessions else None

    scope = {"store": store, "card": card, "place": place, "notify": notify, "latest": latest}
    args.cmd.mkdir(parents=True, exist_ok=True)

    def watch():
        while True:
            for path in sorted(args.cmd.glob("*.py")):
                run_command(path, scope, session_lock, notify)
            time.sleep(0.3)

    threading.Thread(target=watch, daemon=True).start()
    print(f"serving http://127.0.0.1:{args.port}/ ; commands from {args.cmd}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
