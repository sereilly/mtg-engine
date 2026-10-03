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
from tests.source_index import code_only_lines, source_text

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
        raw = source_text(path).splitlines()
        for number, line in enumerate(code_only_lines(path), 1):
            if pattern.search(line):
                found.append((str(path.relative_to(ENGINE)), number, raw[number - 1].strip()))
    return found


def _module(hit: tuple[str, int, str]) -> str:
    return hit[0].replace("\\", "/")


def _counts(pattern: re.Pattern) -> dict[str, int]:
    """How many times *pattern* matches, per engine module."""
    counted: dict[str, int] = {}
    for hit in _hits(pattern, skip=set()):
        counted[_module(hit)] = counted.get(_module(hit), 0) + 1
    return counted


def _assert_within_baseline(
    pattern: re.Pattern, baseline: dict[str, int], message: str
) -> None:
    """No module may carry more matches of *pattern* than its recorded count.

    A count rather than a file on an exempt list, so a *new* read in a module
    that already has one fails. The companion check below refuses a baseline
    that sits above the truth, which is what keeps the two directions honest.
    """
    hits = _hits(pattern, skip=set())
    counted = _counts(pattern)
    over = {
        module for module, count in counted.items()
        if count > baseline.get(module, 0)
    }
    assert not over, (
        message
        + ":\n"
        + "\n".join(
            f"  {hit[0]}:{hit[1]}: {hit[2]}" for hit in hits if _module(hit) in over
        )
        + "\n(baselines: "
        + ", ".join(f"{m}={baseline.get(m, 0)} now {counted[m]}" for m in sorted(over))
        + ")"
    )


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
        text = source_text(path)
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
#   * the state-based sweep matches Aura / Equipment / Saga / Role shapes.
#     Supertypes used to be listed here too and no longer are: "Legendary" and
#     "World" are copiable values (CR 707.2), so the legend and world rules
#     read ``printed_supertypes(perm.effective_card.type_line)`` and a Clone of
#     a legend is a second legend. ``has_type`` is still not the accessor for
#     them — it computes layer 4's card types and subtypes, which do not
#     include supertypes at all.
#
# The numbers below may only go **down**. A rise is either a real exemption
# with a reason written here, or a read that should have been an accessor.
#
# A **count per module**, not a file on an exempt list, and the difference is
# what this guard was missing for four sets. An exempt file is exempt for ever:
# `mixins/helpers.py` was on the old list for "the Aura shape, plus a stack
# item's card colours" and by the time anyone looked again it held two live
# Licid-class reads and no colour read at all — the stated reason had gone stale
# in one half while the other half hid the offences. A count cannot do that,
# because a *new* read in an already-listed module fails. Same mechanism as
# `test_control_reads.py`'s positional ratchet and the `web/` twin in
# `tests/ui/test_layer_reads_in_web.py`.

# The pattern is deliberately ``<something>.card.<field>`` and not a bare
# ``card.type_line``: a local named ``card`` already *is* a CardDefinition, so
# reading its printed line is the only thing it could mean. It is the possessive
# — a permanent reaching past itself into its card — that is the smell.
_PRINTED_READS = re.compile(r"\.card\.(type_line|colors)\b")

#: module -> how many printed type/colour reads survive in it, and why.
PRINTED_READ_BASELINE: dict[str, int] = {
    # The layer system's own input: the computed answer is built out of the
    # printed shape, so somewhere has to read it first.
    "models.py": 2,
    # Asking the computed type here would include the type this very effect is
    # about to add, so the answer would depend on whether it had already been
    # asked — a self-reference, not a shortcut. Both sites say so in place.
    "auras.py": 1,
    "mixins/permanent_state.py": 1,  # the same self-reference, for global statics
    # Card shapes this engine models on the printed line alone. The supertype
    # sweeps that used to be covered by this entry read the effective card now.
    #
    # **Not all of these are blessed.** The Aura reads are the Licid class: a
    # Gliding Licid "becomes an Aura enchantment" by a CR 613 layer-4 type
    # change, which moves neither the printed line nor `effective_card` (layer 1
    # folds a copy, layer 3 a text change, and this is neither), so only
    # `has_type("aura")` answers. They are counted rather than fixed because
    # `_unattach_illegal_auras` and its callers are the CR 704.5m/n sweep and
    # changing what it matches is a rules round, not a guard one.
    "mixins/game_ending.py": 5,   # 3 Aura (Licid-class debt), Saga, Role
    "mixins/helpers.py": 2,       # both Aura — Licid-class debt, see above
    # `mixins/stack/casting.py` used to be exempt here, on the reason "an object
    # on the stack is not a permanent and has no layers applied to it". The
    # first half is true and the second was the mistake this list is meant to
    # catch: CR 613.1 applies the layers to an *object*. Its one read — the
    # spell "counter target <colour> spell" falls back to — goes through
    # `object_colors` now, so the entry is gone rather than reworded.
}


def test_printed_type_and_colour_reads_stay_where_they_belong():
    """"What type/colour is this permanent?" has one answer, and it is the
    computed one."""
    _assert_within_baseline(
        _PRINTED_READS,
        PRINTED_READ_BASELINE,
        "printed type_line/colors read above its module's baseline — ask "
        "permanent.has_type / permanent.effective_colors, or raise the "
        "module's entry in PRINTED_READ_BASELINE with the reason it really "
        "means the card",
    )


# ---------------------------------------------------------------------------
# The printed colour of an object that is *not* a permanent
# ---------------------------------------------------------------------------
#
# The guard above deliberately skips a **bare** ``card.colors``: "a local named
# ``card`` already *is* a CardDefinition, so reading its printed line is the
# only thing it could mean." That is still true of a type line and it stopped
# being true of a colour the day Celestial Dawn was ingested — "the same is
# true for spells you control and nonland cards you own that aren't on the
# battlefield" is a CR 613 layer-5 effect over objects with no permanent to
# ask, so a card in a hand, a graveyard or on the stack has an effective colour
# and ``engine/object_colors.py`` is where it is answered.
#
# The 6ED round found thirteen of these and left five. Every one it fixed was a
# rule reading a characteristic the board had already changed, in silence: a
# Gloom charged nothing for a Dark Ritual the Dawn had made white, a White
# Knight refused to be targeted by a Terror that was no longer black, and
# "whenever a player casts a white spell" never fired.
#
# Same shape as the list above and the same rule: it may only shrink. A new
# entry is either a caller that genuinely has no game and no seat — which gets
# the printed answer, the safe direction — or a read that should have gone
# through ``object_colors``.

# Both spellings, unlike the guard above: ``perm.card.colors`` and a bare
# ``card.colors`` are the same wrong answer here, so the possessive half
# overlaps that list on purpose and is the stricter of the two.
_PRINTED_COLOR_READS = re.compile(r"\b\w*card\.colors\b")

#: module -> how many printed colour reads survive in it, and why.
PRINTED_COLOR_BASELINE: dict[str, int] = {
    # The layer system's own input, both of them: layer 5 is seeded from the
    # printed colours and layer 1 copies them as a copiable value (CR 707.2a).
    "layer_bridge.py": 1,       # the layer-5 seed
    "copies.py": 1,             # the copiable values a copy starts from
    # A weight over a card with no board in hand. AI tuning, not a rule.
    "ai_valuation.py": 1,       # a valuation predicate with no game to ask
    # Known gaps, both named in the 6ED w1g3 report rather than left silent:
    # `graveyard_card_matches` has nineteen call sites and takes neither a game
    # nor the pile's owner, and `_exile_search_matches` is a staticmethod. Both
    # want the seat threaded to them, which is its own round.
    "handlers/_common.py": 1,   # graveyard_card_matches takes no game or owner yet
    "mixins/stack/choices.py": 1,  # _exile_search_matches is a staticmethod
}


def test_printed_colour_reads_of_a_non_permanent_stay_where_they_belong():
    """"What colour is this card?" is CR 613.1e's question wherever the card
    is, and ``object_colors`` is the one place it is answered."""
    _assert_within_baseline(
        _PRINTED_COLOR_READS,
        PRINTED_COLOR_BASELINE,
        "printed card.colors read above its module's baseline — ask "
        "engine.object_colors.object_colors / card_colors with the object's "
        "seat, or raise the module's entry in PRINTED_COLOR_BASELINE with the "
        "reason it really means the printed mana cost",
    )


# ---------------------------------------------------------------------------
# The collapsed printed type — ``card.primary_type``
# ---------------------------------------------------------------------------
#
# The pattern above covers ``type_line`` and ``colors`` and has never covered
# ``primary_type``, which is the **same wrong answer twice over**:
#
#   * it is the card as printed, so every layer-4 type change is missing from
#     it — an animated Mishra's Factory is not a creature, a Kormus Bell Swamp
#     is not a creature, a Licid is not an Aura;
#   * and it *collapses* a multi-type line to one word (``models.py``: the
#     first of land/creature/artifact/… that appears), so an Artifact Creature
#     answers "creature" and is invisible to any count of artifacts. That is
#     the half a `type_line` substring test gets right and this one cannot.
#
# The second half is what five consecutive promotions have each paid for, most
# recently at MMQ, where `engine/ai_simulator.py` reported Disenchant destroying
# nothing on a game whose log said `Destroyed Toymaker` one line above —
# Toymaker being an Artifact Creature, counted as neither. The engine was right
# and the honesty check was lying, which is the expensive direction.
#
# So the field is in the scan at last, as a **ratchet rather than a ban**:
# draining the 64 sites is a round of its own (SET_PLAYBOOK.md, Known gaps —
# each one needs a judgement about whether it means the card or the permanent,
# and some of them, like Balance's land/creature counts, cannot be fixed on this
# side alone). What the ratchet buys is that there cannot be a 65th.

_PRINTED_PRIMARY_TYPE = re.compile(r"\.card\.primary_type\b")

#: module -> how many ``.card.primary_type`` reads survive in it. **Untriaged
#: debt, not blessings**: unlike every other baseline in this file, no entry
#: here carries a reason, because no one has yet asked of these sites whether
#: they mean the card or the permanent. Lower an entry when you drain one; the
#: only rule the guard enforces is that no entry may rise.
PRIMARY_TYPE_BASELINE: dict[str, int] = {
    "ai_policy.py": 11,
    "card_hooks.py": 1,
    "handlers/board_misc.py": 5,
    "handlers/destruction.py": 2,
    "handlers/mana.py": 1,
    "handlers/prevention.py": 1,
    "handlers/stack.py": 2,
    "handlers/tapping.py": 2,
    "mana_payment.py": 1,
    "mixins/effects.py": 1,
    "mixins/game_ending.py": 1,
    "mixins/helpers.py": 1,
    "mixins/oracle_instructions.py": 6,
    "mixins/permanent_state.py": 10,
    "mixins/stack/casting.py": 3,
    "mixins/stack/choices.py": 7,
    "mixins/stack/resolution.py": 1,
    "mixins/turn_management.py": 1,
    "phases/untap_step.py": 2,
    "phases/upkeep_step.py": 3,
}


def test_no_new_collapsed_printed_type_read():
    """``card.primary_type`` is the printed line *and* collapsed to one word.
    The population may only shrink."""
    _assert_within_baseline(
        _PRINTED_PRIMARY_TYPE,
        PRIMARY_TYPE_BASELINE,
        "new card.primary_type read — it is the printed type line (so no "
        "layer-4 change is in it) collapsed to a single word (so an Artifact "
        "Creature answers only \"creature\"). Ask permanent.has_type / "
        "permanent.is_creature",
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

#: module -> how many printed text/keyword reads survive in it, and why.
PRINTED_TEXT_BASELINE: dict[str, int] = {
    # A cycle, not a preference: ``effective_card`` appends the abilities these
    # statics grant, so asking the effective text which permanents grant them
    # would make the answer depend on itself. Both readers live here for that
    # reason — ``_refresh_global_statics`` calls in rather than keeping its own.
    "global_statics.py": 1,
}


def test_printed_text_and_keyword_reads_stay_where_they_belong():
    """"What does this permanent say?" has one answer, and it is the computed
    one."""
    _assert_within_baseline(
        _PRINTED_TEXT_READS,
        PRINTED_TEXT_BASELINE,
        "printed oracle_text/keywords read above its module's baseline — ask "
        "permanent.effective_card (or _has_keyword, which also asks layer 6), "
        "or raise the module's entry in PRINTED_TEXT_BASELINE with the reason "
        "it really means the card",
    )


@pytest.mark.parametrize(
    "baseline,pattern",
    [
        (PRINTED_READ_BASELINE, _PRINTED_READS),
        (PRINTED_COLOR_BASELINE, _PRINTED_COLOR_READS),
        (PRINTED_TEXT_BASELINE, _PRINTED_TEXT_READS),
        (PRIMARY_TYPE_BASELINE, _PRINTED_PRIMARY_TYPE),
    ],
    ids=["type-and-colour", "colour-of-a-non-permanent", "text", "primary-type"],
)
def test_no_baseline_sits_above_its_real_count(baseline, pattern):
    """The half that makes a ratchet ratchet.

    A baseline above the truth is room for the next read to appear for free —
    and a module that has dropped to zero is the old stale-exemption check,
    which this subsumes: an entry for a module with no such read left is slack
    of exactly its own size.
    """
    counted = _counts(pattern)
    slack = {
        module: (recorded, counted.get(module, 0))
        for module, recorded in baseline.items()
        if recorded > counted.get(module, 0)
    }
    assert not slack, (
        "baseline above the real count — lower (or drop) these entries so the "
        "ratchet keeps its teeth:\n"
        + "\n".join(
            f"  {module}: recorded {recorded}, really {real}"
            for module, (recorded, real) in sorted(slack.items())
        )
    )
