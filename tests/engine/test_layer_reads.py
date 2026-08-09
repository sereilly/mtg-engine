"""Guard: "what type is this?" has exactly one answer.

``land_type_override`` is how a land-type change is *recorded*. CR 613 layer 4
turns it into a subtype replacement (CR 305.7), and ``Permanent.has_type`` is
the only thing that applies that rule. Every other reader that went to the raw
metadata — or to ``card.type_line`` — was a second opinion, and they did not
agree:

  * legality matched *printed type OR override*, so a Mountain turned into an
    Island was a legal "target Mountain" and a legal "target Island" at once.
  * mass destruction matched by substring, which hid that the handler stripped
    a trailing "s" from the named type and turned "Plains" into "plain".
  * landwalk, animation and Magical Hack each had their own version.

Writers are fine — recording the effect is the point. This pins the reads.
"""

import pathlib
import re

import pytest

ENGINE = pathlib.Path(__file__).resolve().parents[2] / "engine"

# The one place that may consume the raw key: the layer-4 builder that turns it
# into a continuous effect. Everything else must ask has_type.
ALLOWED_READERS = {
    "layer_bridge.py",
}

# Reading the key to undo an effect you yourself recorded is bookkeeping, not a
# type question. Each entry names why.
ACKNOWLEDGED = {
    "card_hooks.py": "Gaea's Liege reverts only the override it set itself",
}

_READ = re.compile(r'metadata\.get\(\s*"land_type_override"')


def _raw_reads() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(ENGINE.rglob("*.py")):
        if path.name in ALLOWED_READERS or path.name in ACKNOWLEDGED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _READ.search(line):
                found.append((str(path.relative_to(ENGINE)), number, line.strip()))
    return found


def test_land_type_is_read_through_the_layer_system():
    offenders = _raw_reads()
    assert not offenders, (
        "raw land_type_override read(s) outside the layer-4 builder — ask "
        "permanent.has_type(...) so CR 305.7's replacement is applied in one "
        "place:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


@pytest.mark.parametrize("name,reason", sorted(ACKNOWLEDGED.items()))
def test_acknowledged_readers_still_exist(name, reason):
    """An acknowledgement for a file that no longer reads the key is a stale
    exemption, and a stale exemption is how the next raw read gets a free pass."""
    path = next((p for p in ENGINE.rglob(name)), None)
    assert path is not None, f"{name} no longer exists; drop its acknowledgement"
    assert _READ.search(path.read_text(encoding="utf-8")), (
        f"{name} no longer reads land_type_override ({reason}); drop its acknowledgement"
    )
