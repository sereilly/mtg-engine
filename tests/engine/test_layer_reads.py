"""Guard: "what type is this?" and "what does this say?" have one answer each.

A land-type change is a CR 613 layer-4 effect (CR 305.7: setting a basic land
subtype *replaces* the old ones); a word swap is a layer-3 text change. Both are
now **recorded contributions** — ``engine/land_types.py`` and
``engine/text_changes.py`` — collected by exactly one reader each, and asked
through ``Permanent.has_type`` / ``Permanent.basic_land_types`` and
``Permanent.effective_card``.

Every other reader that went to the storage directly was a second opinion, and
they did not agree:

  * legality matched *printed type OR override*, so a Mountain turned into an
    Island was a legal "target Mountain" and a legal "target Island" at once.
  * mass destruction matched by substring, which hid that the handler stripped
    a trailing "s" from the named type and turned "Plains" into "plain".
  * landwalk, animation and Magical Hack each had their own version.
  * three consumers patched a Sleight of Mind colour remap onto an already
    remapped value, applying layer 3 twice.

Writers go through the write API, which is why the raw keys are pinned too: a
stamped value has to be un-stamped by whoever wrote it, and only ever
*wholesale* — which is how one effect ending took another effect's type change
with it.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"

# The write APIs. Only these may touch the storage keys.
STORAGE_OWNERS = {
    "land_types.py": ("land_type_effects", "derived_land_type_changes"),
    "text_changes.py": ("text_change_effects",),
}

# Who may consume the recorded contributions: one reader per channel, the one
# that applies the layer. Everything else asks the accessor on Permanent.
ACCESSOR_READERS = {
    # layer 4 — engine/layer_bridge.py builds the CR 305.7 subtype replacement.
    "land_type_changes": {"land_types.py", "layer_bridge.py"},
    # layer 3 — Permanent.effective_card folds the text changes, once.
    "apply_text_changes": {"text_changes.py", "models.py"},
}

# Reading a channel to undo an effect you yourself recorded used to need an
# acknowledgement here (Gaea's Liege reverting its own Forest). It does not any
# more: ``end_land_type_change(land, source=self)`` drops one contribution
# without asking what the land currently is. Kept as a mechanism, with the
# staleness check below, so the next one that appears has to justify itself.
ACKNOWLEDGED: dict[str, str] = {}

# The metadata key the whole family used to be stamped under. It is gone; this
# is the ratchet that keeps it gone.
_RETIRED_KEY = "land_type_override"


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
def test_the_storage_keys_are_touched_only_by_their_write_api(owner, keys):
    """A raw ``metadata["land_type_effects"]`` poke outside the write API is a
    contribution nothing else can end, or an ending nothing else recorded."""
    pattern = re.compile("|".join(re.escape(f'"{key}"') for key in keys))
    offenders = _hits(pattern, skip=set(STORAGE_OWNERS) | set(ACKNOWLEDGED))
    assert not offenders, (
        f"raw {'/'.join(keys)} access outside engine/{owner} — record the effect "
        "through its write API so removal is dropping a contribution:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


@pytest.mark.parametrize("accessor,allowed", sorted(ACCESSOR_READERS.items()))
def test_each_channel_has_exactly_one_consumer(accessor, allowed):
    """The contributions are applied by the layer, in one place. A second
    consumer is a second opinion about what the effects add up to — which is
    what layer 4's audit found seven of, and layer 3's three."""
    pattern = re.compile(rf"\b{re.escape(accessor)}\s*\(")
    offenders = _hits(pattern, skip=allowed | set(ACKNOWLEDGED))
    assert not offenders, (
        f"{accessor}() called outside {sorted(allowed)} — ask permanent.has_type / "
        "permanent.basic_land_types / permanent.effective_card so the layer is "
        "applied in one place:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


def test_the_stamped_land_type_override_is_gone():
    """The single-string channel every land-type effect used to share. Two
    effects on one land could not both be recorded in it, and neither could be
    ended without ending the other."""
    offenders = _hits(re.compile(re.escape(_RETIRED_KEY)), skip=set())
    assert not offenders, (
        f"{_RETIRED_KEY} is back — a land-type change is a contribution with a "
        "source and a timestamp (engine/land_types.py), not a stamped value:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
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
