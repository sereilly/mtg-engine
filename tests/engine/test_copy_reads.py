"""Guard: "what is this a copy of?" has one answer, and layer 1 owns it.

CR 613.2a puts copy effects in layer 1, and CR 613.2c says what comes out of it
is the object's **copiable values** — the thing every other layer starts from.
So a copy is not a set of results to stamp onto the copy; it is a recorded
contribution (``engine/copies.py``) that :func:`engine.copies.copiable_card`
folds, and ``Permanent.effective_card`` applies exactly once.

The stamped model this replaced kept the answer in five places, and CR 707.2's
boundary — printed values as modified by *copy* effects, and nothing else — was
violated by four of them:

  * ``absolute_power``/``absolute_toughness`` is **layer 7b's** channel, so a
    copy took whatever a non-copy effect had set on the source.
  * ``copied_card`` held the source permanent's own ``card``, which is not its
    copiable values when the source is itself a copy (CR 707.3).
  * Copy Artifact read the source's ``effective_card``, which already has
    layer 3 folded in — and CR 707.2 does not copy text changes.
  * ``copied_colors`` was written only when there were colours to write, so
    "this effect declines colour" (CR 707.9c) and "the copied object was
    colourless" were the same absent record. Copy Artifact copying a Sol Ring
    came out blue.

Every one of those is a stamp recording an *answer* where the rule asks where
the answer came from. This guard pins the storage and its single consumer, and
ratchets the retired keys so they cannot come back.
"""

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"

# The write API. Only this module may touch the storage key.
STORAGE_OWNERS = {
    "copies.py": ("copy_effects",),
}

# Who may consume the recorded contributions. Layer 1 has *one* reader, because
# what it produces is the seed every other layer reads: a second fold would be a
# second opinion about what the object's copiable values are.
ACCESSOR_READERS = {
    # the fold itself — applied once, by Permanent.effective_card
    "copiable_card": {"copies.py", "models.py"},
    # the raw contribution list
    "copy_effects": {"copies.py"},
    # the write API: one entry point for all three copiers in the pool, because
    # CR 707.2 is one rule and their differences are CR 707.9 exceptions read
    # off each card's own text.
    "become_copy": {"copies.py", "permanent_state.py"},
}

# Genuine exceptions, by file name with the reason each cannot ask the
# accessor. Empty, and worth keeping that way: every entry would be a place
# where a copy is described by something other than its contribution.
ACKNOWLEDGED: dict[str, str] = {}

# The metadata keys the stamped model used. They are gone; this is the ratchet
# that keeps them gone. Written as quoted literals so the prose that explains
# why they were retired does not trip the guard.
RETIRED_KEYS = (
    "copied_card",
    "copied_colors",
    "copied_keywords",
    "copied_from",
    "may_recopy_each_upkeep",
)

# Layer 7's channels. Layer 1 must not write them: a copy expressed as a P/T
# stamp is a copy that cannot tell a printed 2/2 from a 2/2 something else set,
# which is CR 707.2's boundary collapsing.
PT_CHANNELS = ("absolute_power", "absolute_toughness", "power_bonus", "toughness_bonus")


def _engine_files() -> list[pathlib.Path]:
    return sorted(ENGINE.rglob("*.py"))


def _hits(pattern: re.Pattern, skip: set[str]) -> list[tuple[str, int, str]]:
    found = []
    for path in _engine_files():
        if path.name in skip:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                found.append((str(path.relative_to(ENGINE)), number, line.strip()))
    return found


@pytest.mark.parametrize("owner,keys", sorted(STORAGE_OWNERS.items()))
def test_the_storage_key_is_touched_only_by_its_write_api(owner, keys):
    """A raw ``metadata["copy_effects"]`` poke outside the write API is a copy
    nothing can end, or an ending nothing recorded."""
    pattern = re.compile("|".join(re.escape(f'"{key}"') for key in keys))
    offenders = _hits(pattern, skip=set(STORAGE_OWNERS) | set(ACKNOWLEDGED))
    assert not offenders, (
        f"raw {'/'.join(keys)} access outside engine/{owner} — record the copy "
        "through become_copy() so removal is dropping a contribution:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


@pytest.mark.parametrize("accessor,allowed", sorted(ACCESSOR_READERS.items()))
def test_each_channel_has_exactly_one_consumer(accessor, allowed):
    """Layer 1 is folded in one place and recorded from one place. A second
    fold is a second answer to "what are this object's copiable values", which
    is the question every other layer is seeded from."""
    pattern = re.compile(rf"\b{re.escape(accessor)}\s*\(")
    offenders = _hits(pattern, skip=allowed | set(ACKNOWLEDGED))
    assert not offenders, (
        f"{accessor}() called outside {sorted(allowed)} — ask "
        "permanent.effective_card / permanent.copied_from so layer 1 is applied "
        "in one place:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


@pytest.mark.parametrize("key", RETIRED_KEYS)
def test_the_stamped_copy_channels_are_gone(key):
    """Each of these recorded a *result* of copying. A result cannot say where
    it came from, which is the entire content of CR 707.2's last sentence."""
    offenders = _hits(re.compile(re.escape(f'"{key}"')), skip=set())
    assert not offenders, (
        f"{key} is back — a copy is a contribution carrying the copied object's "
        "copiable values, a source and a timestamp (engine/copies.py), not a "
        "stamped answer:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


def _named_in_code(path: pathlib.Path) -> set[str]:
    """Every identifier and string literal the module's *code* uses.

    Prose is excluded — a bare string expression is a docstring — because this
    module's whole documentation is about the channels it must not touch, and a
    plain substring scan would forbid explaining why.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prose = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in prose:
                names.add(node.value)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


@pytest.mark.parametrize("channel", PT_CHANNELS)
def test_layer_one_does_not_write_layer_seven(channel):
    """``engine/copies.py`` must not name a P/T channel in its code. The stamped
    model stored a copy's power in ``absolute_power`` — layer 7b — so a "base
    power 0" effect on the source was indistinguishable from the source's
    printed power, and got copied."""
    assert channel not in _named_in_code(ENGINE / "copies.py"), (
        f"engine/copies.py names {channel}: layer 1 produces copiable values, "
        "and layer 7 applies over them (engine/pt.py). A copy that writes a P/T "
        "channel cannot tell a printed value from a set one."
    )


def test_no_acknowledgement_has_gone_stale():
    """An acknowledgement for a file that no longer needs it is a stale
    exemption, and a stale exemption is how the next raw read gets a free pass.
    Vacuously true while there are none — which is the state to keep."""
    stale = []
    for name, reason in sorted(ACKNOWLEDGED.items()):
        path = next((p for p in ENGINE.rglob(name)), None)
        if path is None:
            stale.append(f"{name} no longer exists")
            continue
        text = path.read_text(encoding="utf-8")
        keys = [key for keys in STORAGE_OWNERS.values() for key in keys]
        wanted = [*(f'"{key}"' for key in keys), *ACCESSOR_READERS]
        if not any(token in text for token in wanted):
            stale.append(f"{name} no longer reads the storage ({reason})")
    assert not stale, "drop the stale acknowledgement(s): " + "; ".join(stale)
