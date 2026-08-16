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

import io
import pathlib
import re
import tokenize

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


def _code_only(source: str) -> list[str]:
    """*source*'s lines with comments and string literals blanked out.

    These guards are about what the engine *does*, and this repo explains
    itself in prose: a docstring naming ``permanent.card.oracle_text`` to say
    why a node is not normalized is a description of the rule, not a breach of
    it. Matching it would leave the only fix available being to stop writing
    the sentence down. Line numbers are preserved so a real hit still points at
    its line.
    """
    lines = source.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines  # unparseable: report everything rather than nothing
    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            head = line[:start_col] if row == start_row else ""
            tail = line[end_col:] if row == end_row else ""
            lines[row - 1] = head + " " * (len(line) - len(head) - len(tail)) + tail
    return lines


def _hits(pattern: re.Pattern, skip: set[str]) -> list[tuple[str, int, str]]:
    found = []
    for path in _engine_files():
        if path.name in skip:
            continue
        source = path.read_text(encoding="utf-8")
        raw = source.splitlines()
        for number, line in enumerate(_code_only(source), 1):
            if pattern.search(line):
                found.append((str(path.relative_to(ENGINE)), number, raw[number - 1].strip()))
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


# ---------------------------------------------------------------------------
# The printed characteristics of a permanent's card
# ---------------------------------------------------------------------------
#
# The guards above pin the *storage* of a layer's contributions. This one pins
# the other end: reading ``perm.card.type_line`` or ``perm.card.colors`` to
# decide what a permanent currently is. Those are the card as printed, which no
# effect can change, and the accessors beside them (``has_type``,
# ``effective_colors``) are the same question asked of CR 613.
#
# Round 47 found the shape at its sharpest: ``_can_block_attacker`` tested
# Juggernaut's "can't be blocked by Walls" against the printed line and
# Invisibility's "can only be blocked by Walls" against ``has_type``, three
# lines apart — so a creature that *became* a Wall failed both restrictions at
# once. Round 48 found five more, including a picker that offered no target for
# Northern Paladin against a Deathlaced creature while the resolution behind it
# happily destroyed one.
#
# A ratchet with an exempt list rather than a ban, because some readers really
# do mean the card:
#
#   * the layer machinery itself has to start from the printed shape;
#   * an effect that asks "is this *not* already a creature?" before animating
#     it must not see the type it is about to add (engine/auras.py);
#   * the state-based sweep matches Aura / Equipment / Saga / Role shapes, and
#     supertypes (Legendary, World), which this engine does not model at
#     layer 4 at all — ``has_type`` would answer False for every one of them.
#
# The list may only shrink. A new entry means either a real exemption with a
# reason written here, or a read that should have been an accessor.

# The pattern is deliberately ``<something>.card.<field>`` and not a bare
# ``card.type_line``: a local named ``card`` already *is* a CardDefinition, so
# reading its printed line is the only thing it could mean. It is the possessive
# — a permanent reaching past itself into its card — that is the smell.
_PRINTED_READS = re.compile(r"\.card\.(type_line|colors)\b")

# file -> why its printed reads are the right question.
PRINTED_READ_EXEMPTIONS: dict[str, str] = {
    # The layer system's own input: the computed answer is built out of the
    # printed shape, so somewhere has to read it first.
    "models.py": "Permanent's accessors start from the printed basic land types",
    # Asking the computed type here would include the type this very effect is
    # about to add, so the answer would depend on whether it had already been
    # asked — a self-reference, not a shortcut. Both sites say so in place.
    "auras.py": "animating_auras must not see the creature type it grants",
    "mixins/permanent_state.py": "the same self-reference, for global statics",
    # Card shapes and supertypes this engine models on the printed line alone:
    # `has_type` covers card types and subtypes, so it answers False for
    # "Legendary" and "World" whatever the permanent is.
    "mixins/game_ending.py": "Aura/Equipment/Saga/Role shapes and supertypes",
    "mixins/helpers.py": "the Aura shape, plus a stack item's card colours",
    # An object on the stack is not a permanent and has no layers applied to it
    # here; its colour comes from the card (and a Lace's recolour, which
    # `_stack_item_colors` folds in).
    "mixins/stack/casting.py": "a spell on the stack, matched by its card",
}


def test_printed_type_and_colour_reads_stay_where_they_belong():
    """"What type/colour is this permanent?" has one answer, and it is the
    computed one."""
    offenders = [
        hit for hit in _hits(_PRINTED_READS, skip=set())
        if hit[0].replace("\\", "/") not in PRINTED_READ_EXEMPTIONS
    ]
    assert not offenders, (
        "printed type_line/colors read outside the exempt list — ask "
        "permanent.has_type / permanent.effective_colors, or add the file to "
        "PRINTED_READ_EXEMPTIONS with the reason it really means the card:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


def test_no_printed_read_exemption_has_gone_stale():
    """An exemption for a file that no longer has such a read is how the next
    one gets in free. The list may only shrink."""
    live = {hit[0].replace("\\", "/") for hit in _hits(_PRINTED_READS, skip=set())}
    stale = sorted(set(PRINTED_READ_EXEMPTIONS) - live)
    assert not stale, (
        f"exemptions with no printed read left: {stale} — drop them from "
        "PRINTED_READ_EXEMPTIONS"
    )


# ---------------------------------------------------------------------------
# What a permanent says, and the keywords parsed off it
# ---------------------------------------------------------------------------
#
# The same ratchet one layer over. ``perm.card.oracle_text`` and
# ``perm.card.keywords`` are the card as it left the printer, and three separate
# effects change what a permanent actually says before anything should read it:
# layer 1 (a copy takes the copied object's rules text, CR 707.2), layer 3 (a
# text change rewrites words, CR 612.1), and the ability a board-wide static
# grants, which ``Permanent.effective_card`` appends after both.
#
# Round 48 gave the *type and colour* accessors this guard and wrote down that
# the text had none. The census that followed found reads in seventeen files,
# and they were not theoretical:
#
#   * a Clone of Wall of Stone could attack, because the defender gate scanned
#     the printed keyword list — and so could a Primal Clay on its 1/6 Wall
#     body, whose defender is a layer-6 grant that is in *neither* card;
#   * a Clone of Veteran Bodyguard let its controller take the damage, a Copy
#     Artifact of Time Vault untapped every turn, a Clone of Old Man of the Sea
#     was never offered its keep-tapped choice;
#   * Sleight of Mind on a Ward and Magical Hack on Burrowing rewrote the word
#     and changed nothing, which is a text-changing effect doing the one thing
#     it exists to do.
#
# So the accessor is ``permanent.effective_card`` — or, for a keyword, the
# ``_has_keyword`` that asks layer 6 as well.

_PRINTED_TEXT_READS = re.compile(r"\.card\.(oracle_text|keywords)\b")

# file -> why its printed text reads are the right question.
PRINTED_TEXT_EXEMPTIONS: dict[str, str] = {
    # A cycle, not a preference: ``effective_card`` appends the abilities these
    # statics grant, so asking the effective text which permanents grant them
    # would make the answer depend on itself. Both readers live here for that
    # reason — ``_refresh_global_statics`` calls in rather than keeping its own.
    "global_statics.py": "the text that defines a static cannot be read through it",
    # The resolving spell's own card, reached through the execution context.
    # A spell is not a permanent and has no layers applied to it here.
    "handlers/zones.py": "the resolving spell's card, not a permanent",
}


def test_printed_text_and_keyword_reads_stay_where_they_belong():
    """"What does this permanent say?" has one answer, and it is the computed
    one."""
    offenders = [
        hit for hit in _hits(_PRINTED_TEXT_READS, skip=set())
        if hit[0].replace("\\", "/") not in PRINTED_TEXT_EXEMPTIONS
    ]
    assert not offenders, (
        "printed oracle_text/keywords read outside the exempt list — ask "
        "permanent.effective_card (or _has_keyword, which also asks layer 6), "
        "or add the file to PRINTED_TEXT_EXEMPTIONS with the reason it really "
        "means the card:\n"
        + "\n".join(f"  {f}:{n}: {t}" for f, n, t in offenders)
    )


def test_no_printed_text_exemption_has_gone_stale():
    """The list may only shrink, for the same reason as the one above."""
    live = {hit[0].replace("\\", "/") for hit in _hits(_PRINTED_TEXT_READS, skip=set())}
    stale = sorted(set(PRINTED_TEXT_EXEMPTIONS) - live)
    assert not stale, (
        f"exemptions with no printed text read left: {stale} — drop them from "
        "PRINTED_TEXT_EXEMPTIONS"
    )
