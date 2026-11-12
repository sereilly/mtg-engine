"""The real web app, plus a command folder that sets up boards with engine calls.

    python scripts/integration/serve_board.py --port 8022 --cmd .worktrees/scratch/$ROUND/<group>/cmd [--reload]

Run from a tree's root (it serves that tree's engine and client). Start a game
in the browser as usual, then drop a ``.py`` file into the command folder: it
is executed under the session's lock and the session is notified, so the board
redraws and the *gesture* is what gets clicked — setting a board up by hand
in the browser took most of a client round (W2G6 at Mirrodin wrote this).

A command file whose first line is ``# sid=<session id>`` (the id is the
page's ``sessionId``, and in the server's session store) runs with
``session``, ``game`` and ``sid`` in scope; every file has ``store``,
``card(name)``, ``place(game, seat, name)``, ``notify(sid)`` and ``latest()``
(the newest session). Its output lands in ``<name>.out`` and the file is
renamed ``<name>.done``. For driving the page itself — and clicking a card by
its permanent id — see the ``run-magic`` skill.

**``--reload`` keeps the board across a code change** (Darksteel's client
group restarted the server and rebuilt its game by hand for every
server-side edit). The process becomes a supervisor of the app process: when
a ``.py`` under ``engine/`` or ``web/``, a card file under ``cards/``, or
this toolkit's ``board.py``/``board_pickle.py``/``serve_board.py`` changes,
it asks the app to save every session, stops it, and starts one on the new
code that loads them back before it serves a request — same session ids,
same revisions. The page does not reload: its event stream reconnects and
re-fetches the state. An engine edit's restart pays the pool's compile
(~20 s), a ``web/`` edit's ~5 s; ``<cmd>/serve_board.state`` reads
``state=up`` again when it is serving. What a session keeps, and what it
does not, is ``board_pickle.py``'s docstring. A session that cannot be saved
keeps the old process serving on the old code, retried on the next change
and every ten seconds — a board is never dropped. A client edit under
``web/static/`` restarts nothing: reload the page and rejoin (the skill).
Stopping the supervisor stops the app with it.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from board import card, place  # noqa: E402
from board_pickle import restore_board, save_board  # noqa: E402

#: What ``--reload`` watches, relative to the tree's root: (path, suffix) —
#: a folder walked for files ending in the suffix, or one file.
WATCHED = (
    ("engine", ".py"),
    ("web", ".py"),
    ("cards", ".json"),
    ("scripts/integration/board.py", ""),
    ("scripts/integration/board_pickle.py", ""),
    ("scripts/integration/serve_board.py", ""),
)


def say(message: str) -> None:
    print(f"[serve_board] {message}", flush=True)


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


# ---------------------------------------------------------------------------
# The app process
# ---------------------------------------------------------------------------


def serve(args) -> None:
    import uvicorn

    from web.app import app, store
    from web.events import _notify_session_change, _session_revisions
    from web.runtime import session_lock

    if args.restore and args.restore.exists():
        say(restore_board(store, _session_revisions, args.restore))

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

    if args.child:
        # The supervisor talks on stdin: "save" asks for the board (this
        # process exits once it is written, holding every session's lock),
        # and the pipe closing — the supervisor stopped — ends it too.
        refused = args.board.with_suffix(".refused")

        def listen():
            for line in sys.stdin.buffer:
                if line.strip() != b"save":
                    continue
                saved, message = save_board(store, session_lock, _session_revisions, args.board)
                say(message)
                if saved:
                    os._exit(0)
                refused.write_text(message, encoding="utf-8")
            os._exit(0)

        threading.Thread(target=listen, daemon=True).start()

    say(f"serving http://127.0.0.1:{args.port}/ ; commands from {args.cmd}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


# ---------------------------------------------------------------------------
# The supervisor (--reload)
# ---------------------------------------------------------------------------


def snapshot(root: Path) -> dict[str, int]:
    """Modification time of every watched file, by path."""
    stamps: dict[str, int] = {}
    for relative, suffix in WATCHED:
        base = root / relative
        if base.is_file():
            stamps[str(base)] = base.stat().st_mtime_ns
            continue
        for folder, subfolders, files in os.walk(base):
            subfolders[:] = [name for name in subfolders if name != "__pycache__"]
            for name in files:
                if name.endswith(suffix):
                    path = os.path.join(folder, name)
                    try:
                        stamps[path] = os.stat(path).st_mtime_ns
                    except OSError:
                        pass
    return stamps


def changed(before: dict, after: dict) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def write_state(args, **fields) -> None:
    """``<cmd>/serve_board.state``, one line: what a harness polls to know the
    app is serving again (``state=up``) and on which generation."""
    line = " ".join(f"{key}={value}" for key, value in fields.items())
    (args.cmd / "serve_board.state").write_text(line + "\n", encoding="utf-8")


def wait_until_up(port: int, child: subprocess.Popen, seconds: float = 180) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if child.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as reply:
                if reply.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def supervise(args) -> None:
    root = Path.cwd()
    args.cmd.mkdir(parents=True, exist_ok=True)
    refused = args.board.with_suffix(".refused")
    generation = 0

    def start(restore: bool) -> subprocess.Popen:
        nonlocal generation
        generation += 1
        command = [sys.executable, str(Path(__file__).resolve()), "--child",
                   "--port", str(args.port), "--cmd", str(args.cmd), "--board", str(args.board)]
        if restore:
            command += ["--restore", str(args.board)]
        write_state(args, state="starting", generation=generation)
        began = time.time()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, cwd=root)
        if wait_until_up(args.port, process):
            say(f"app up (generation {generation}, pid {process.pid}) in {time.time() - began:.1f} s")
            write_state(args, state="up", generation=generation, pid=process.pid)
        else:
            say(f"the app did not come up (generation {generation}); the board stays in "
                f"{args.board} for the next change")
            write_state(args, state="down", generation=generation)
        return process

    if args.restore and args.restore.exists() and args.restore != args.board:
        args.board.write_bytes(args.restore.read_bytes())
    child = start(restore=bool(args.restore and args.board.exists()))
    say(f"supervising (pid {os.getpid()}); a change under engine/, web/ or cards/ reloads the app")
    stamps = snapshot(root)
    retry_at = None
    last_refusal = ""
    exit_reported = False
    while True:
        time.sleep(1.0)
        now = snapshot(root)
        moved = changed(stamps, now)
        if moved:
            # Let an editor finish writing a group of files.
            while True:
                time.sleep(0.6)
                later = snapshot(root)
                if not changed(now, later):
                    break
                moved = sorted(set(moved) | set(changed(now, later)))
                now = later
            stamps = now
            shown = ", ".join(os.path.relpath(path, root) for path in moved[:4])
            say(f"changed: {shown}{' …' if len(moved) > 4 else ''}")
        elif retry_at is None or time.time() < retry_at:
            if child.poll() is not None and not exit_reported:
                say(f"the app exited (code {child.returncode}); the next change starts it again")
                write_state(args, state="down", generation=generation)
                exit_reported = True
            continue
        retry_at = None
        if child.poll() is None:
            refused.unlink(missing_ok=True)
            write_state(args, state="saving", generation=generation, pid=child.pid)
            try:
                child.stdin.write(b"save\n")
                child.stdin.flush()
            except OSError:
                pass
            deadline = time.time() + 90
            while child.poll() is None and not refused.exists() and time.time() < deadline:
                time.sleep(0.2)
            if child.poll() is None:
                reason = refused.read_text(encoding="utf-8") if refused.exists() else "no answer in 90 s"
                if reason != last_refusal:
                    say(f"kept the old process on the old code: {reason}; retrying every 10 s")
                last_refusal = reason
                retry_at = time.time() + 10
                write_state(args, state="up-old-code", generation=generation, pid=child.pid)
                continue
            last_refusal = ""
            if child.returncode != 0:
                say(f"the app exited with code {child.returncode} while saving; the last saved board is kept")
        exit_reported = False
        child = start(restore=args.board.exists())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8022)
    parser.add_argument("--cmd", type=Path, required=True, help="the command folder to watch")
    parser.add_argument("--reload", action="store_true",
                        help="restart the app on an engine/ web/ cards/ change, keeping every session")
    parser.add_argument("--board", type=Path, default=None,
                        help="where --reload keeps the sessions between processes (default <cmd>/board.pickle)")
    parser.add_argument("--restore", type=Path, default=None,
                        help="load the sessions saved in this board file before serving")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.cmd = args.cmd.resolve()
    args.board = (args.board or args.cmd / "board.pickle").resolve()
    if args.restore:
        args.restore = args.restore.resolve()
    if args.reload and not args.child:
        supervise(args)
    else:
        serve(args)


if __name__ == "__main__":
    main()
