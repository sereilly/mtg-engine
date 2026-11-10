#!/usr/bin/env bash
# run_and_wait.sh <log> <command...>   start <command> detached, then wait on it (bounded)
# run_and_wait.sh --wait <log>         wait again on a run already started
#
# A tool call that runs in the foreground is cut off at about three minutes, so
# every long run (a gate, a folder of tests, a census) became a hand-written
# background job and a poll loop — and a loop that greps the log for "passed"
# never ends here (pytest's summary line is suppressed), while an agent that
# ends its turn "waiting on its own background work" never wakes. This is that
# boilerplate once:
#
#   - the command runs detached, its output in <log>; when it ends, its exit
#     code is the log's last line (`exit=N`) and the whole of <log>.exit, so a
#     result is readable from the log alone, after a session break too;
#   - the wait is bounded: RUN_WAIT seconds (default 170). Done: prints the
#     exit and any FAILED/ERROR lines, and exits with the command's code.
#     Not done: says so, with the command to resume, and exits 75 — "still
#     running", never a red. Re-run `--wait <log>` (or anything else) and come
#     back; leave no loop of your own running.
#
# Starting a second run on a log whose run is still going refuses (exit 2).
set -u
RUN_WAIT="${RUN_WAIT:-170}"
if [ "${1:-}" = "--wait" ]; then
  log="${2:?usage: run_and_wait.sh --wait <log>}"
  [ -f "$log.started" ] || { echo "no run was started on $log"; exit 2; }
else
  log="${1:?usage: run_and_wait.sh <log> <command...>}"; shift
  [ $# -gt 0 ] || { echo "usage: run_and_wait.sh <log> <command...>"; exit 2; }
  if [ -f "$log.started" ] && [ ! -f "$log.exit" ]; then
    echo "a run on $log is still going (started $(cat "$log.started")); wait on it: run_and_wait.sh --wait $log"
    exit 2
  fi
  mkdir -p "$(dirname "$log")"
  rm -f "$log.exit"
  date +%s > "$log.started"
  # printf %q keeps each argument one word through the inner shell.
  quoted=$(printf '%q ' "$@")
  nohup bash -c "$quoted > $(printf %q "$log") 2>&1; code=\$?; echo exit=\$code >> $(printf %q "$log"); echo \$code > $(printf %q "$log.exit")" > /dev/null 2>&1 &
  disown
fi
start=$(cat "$log.started")
deadline=$(( $(date +%s) + RUN_WAIT ))
while [ ! -f "$log.exit" ] && [ "$(date +%s)" -lt "$deadline" ]; do
  sleep 2
done
elapsed=$(( $(date +%s) - start ))
if [ ! -f "$log.exit" ]; then
  echo "still running after ${elapsed}s (log $log); resume with: $0 --wait $log"
  exit 75
fi
code=$(cat "$log.exit")
echo "exit=$code after ${elapsed}s (log $log)  FAILED=$(grep -c '^FAILED' "$log")"
grep '^FAILED\|^ERROR' "$log" | sed 's/ - .*//' | sort | head -40
exit "$code"
