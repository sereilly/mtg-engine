"""Move a measured manifest entry into `sets` as a *textual* edit.

    promote.py CODE            release-ordered position (the real promotion)
    promote.py CODE --wrong    appended after the last shipped set (the rehearsal)

Run from the root of the tree to edit. The same move either way, so the order
guard is the only thing the wrong insert can turn red (SET_PLAYBOOK Phase 4).
No json round-trip: json.dumps re-escapes the em dashes in the role
descriptions. The file is the one `engine.card_loader` names — never a second
spelling of its path.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

from engine.card_loader import MANIFEST_PATH  # noqa: E402

code = sys.argv[1]
wrong = "--wrong" in sys.argv[2:]
path = MANIFEST_PATH
raw = io.open(path, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in raw else "\n"

data = json.loads(raw)
entry = next(e for e in data["measured"] if e["code"] == code)
released = entry["released"]

block_re = re.compile(
    r"    \{" + re.escape(nl) + r'      "code": "' + re.escape(code) + r'",.*?' + re.escape(nl) + r"    \}",
    re.S,
)
m_start = raw.index('"measured": [')
match = block_re.search(raw, m_start)
assert match, "measured block not found"
block = match.group(0)

# Cut it out of `measured`, with the comma that separated it from a neighbour.
before, after = raw[:match.start()], raw[match.end():]
if after.startswith("," + nl):
    after = after[len("," + nl):]                    # first of several
    measured_cut = before + after
elif before.endswith("," + nl):
    measured_cut = before[:-len("," + nl)] + after      # last of several
else:                                                # the only entry
    assert before.endswith("[" + nl) and after.startswith(nl + "  ]"), "unexpected measured shape"
    measured_cut = before[:-len(nl)] + after[len(nl) + 2:]   # "measured": []
raw2 = measured_cut

# Paste into `sets`.
shipped = data["sets"]
if wrong:
    anchor = shipped[-1]["code"]
    place_after = True
else:
    later = [e for e in shipped if e["released"] > released]
    if later:
        anchor, place_after = later[0]["code"], False
    else:
        anchor, place_after = shipped[-1]["code"], True

anchor_re = re.compile(
    r"    \{" + re.escape(nl) + r'      "code": "' + re.escape(anchor) + r'",.*?' + re.escape(nl) + r"    \}",
    re.S,
)
a = anchor_re.search(raw2)
assert a and a.start() < raw2.index('"measured": ['), "anchor not in sets"
if place_after:
    raw3 = raw2[:a.end()] + "," + nl + block + raw2[a.end():]
else:
    raw3 = raw2[:a.start()] + block + "," + nl + raw2[a.start():]

check = json.loads(raw3)
codes = [e["code"] for e in check["sets"]]
assert code in codes and all(e["code"] != code for e in check["measured"])
assert len(check["sets"]) == len(shipped) + 1
io.open(path, "w", encoding="utf-8", newline="").write(raw3)
print(f"{code} -> sets at index {codes.index(code)} ({'WRONG END' if wrong else 'release order'}); "
      f"measured now {[e['code'] for e in check['measured']]}")
