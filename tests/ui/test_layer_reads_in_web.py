"""The scan half of "what type is this?", over ``web/``.

``tests/engine/test_layer_reads.py`` guards this class inside the engine and it
**scans ``engine/`` only**. So every reader in ``web/`` has been outside it since
the day it was written, and the cost was collected one promotion at a time:
Tempest found ``_effective_keywords`` asking ``perm.card.type_line`` (an
animated land lost every keyword), Stronghold found ``is_aura`` (a Licid reached
the client as a non-Aura), Exodus found ``web/combat_prompts.py``'s blocker
check and ``web/prompts.py``'s Balance lists, Urza's Legacy found three more
asking ``card.primary_type``. Four consecutive sets, one site each, every one
found by a person reading a payload rather than by anything that fails.

This is that scan. Its companion ``test_layer_reads_on_the_wire.py`` drives the
serializer and reads the fields a player sees; this file reads the source and
says where the question is asked of the wrong object.

**``primary_type`` is in the pattern and it is not in the engine guard's.**
Every one of the seven historical ``web/`` sites used it and the engine's regex
covers ``type_line`` and ``colors`` alone — which is why widening the engine
guard was not the move here: ``engine/`` carries 70 such reads and draining them
is a round of its own (SET_PLAYBOOK.md, Known gaps).

A **ratchet per module**, not a ban, for the reason ``test_control_reads.py``'s
positional ratchet is one. The printed-read table is empty since round kg (the
last reads were Balance's lists, which are the engine's own candidates now);
two printed-card arguments survive in ``web/serialization.py``, each the
printed half asked for on purpose. The numbers may only go down.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.source_index import code_only_lines, python_files, source_text

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"

# The printed characteristics of a card. ``name`` is deliberately absent: on
# this side of the wire a name is an *address* — ``web/actions.py`` resolves a
# permanent by ``permanent_name`` and the engine's own ``tap_land_for_mana`` /
# ``queue_permanent_ability`` take one — so ``perm.card.name`` is the physical
# card being pointed at, not a claim about what it currently is.
_PRINTED_FIELDS = ("type_line", "primary_type", "colors", "oracle_text",
                   "keywords", "mana_cost")

# The possessive is the smell, exactly as in the engine guard: a local named
# ``card`` already *is* a CardDefinition, so reading its printed line is the
# only thing it could mean. It is an object reaching past itself into its card
# that has to justify itself.
_PRINTED_READ = re.compile(r"\.card\.(" + "|".join(_PRINTED_FIELDS) + r")\b")

# The receiver, read *backwards* from the match rather than as a prefix of the
# pattern above. Written the other way round first, it required a bare name in
# front of ``.card`` — and so slid straight past
# ``battlefield[idx].card.primary_type``, which is ``web/state_view.py``'s
# untap-candidate read and one of the seven sites this file exists for. A
# subscript, a call and a chain of attributes are all the same possessive.
_RECEIVER = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\[\]]*\]|\([^()]*\))*\s*$"
)

#: Receivers that are **not** permanents, so no layer has been applied to them
#: and the card is the only answer there is. An object on the stack is a spell
#: or an ability (CR 111 / CR 113), not a permanent — the same exemption
#: ``engine/mixins/stack/cast_target_validation.py`` carries one package over. Named receivers
#: rather than an exempt file, so ``web/serialization.py`` — where three of the
#: seven historical sites lived — stays fully guarded around them.
STACK_RECEIVERS = frozenset({"item", "stack_item", "target_item"})

#: module -> how many printed reads survive in it, and why. A ratchet: it may
#: only go down.
PRINTED_READ_BASELINE: dict[str, int] = {
    # Empty since round kg. The last two were Balance's land and creature
    # lists, asking ``card.primary_type`` while the engine counted through the
    # layers — so an animated Mishra's Factory was offered only as a land and
    # an Opalescence enchantment not at all. The lists are the engine's own
    # ``Game.balance_candidates`` now, one round at a time (lands, then cards
    # in hand, then creatures, each counted as it starts — the card's ruling),
    # which is also what settled "a permanent that is both".
    #
    # It was 3 until Odyssey: the third was Kudzu's own land list, which went
    # with that card's hook — its reattachment is the general permanent choice
    # now, whose candidates are the engine's and read the layers.
}

# A permanent's printed card handed whole to a card renderer. The same class
# one call deep: what the payload then describes is the card as printed rather
# than the permanent on the board.
_CARD_RENDERERS = ("_card_image_uris", "_card_preview", "_printed_stat",
                   "serialize_card", "_serialize_card_summary")
_PRINTED_CARD_ARGUMENT = re.compile(
    r"\b(" + "|".join(_CARD_RENDERERS) + r")\(\s*[^()]*?\.card\s*[,)]"
)

#: module -> how many of those survive, and why. Also a ratchet.
PRINTED_CARD_ARGUMENT_BASELINE: dict[str, int] = {
    # Two, and both are the printed half being asked for on purpose:
    # ``_card_image_uris(perm.card)`` (a Clone keeps its own art, because the
    # physical card is a Clone) and ``_serialize_card_summary(perm.card)``
    # inside ``_serialize_permanent_summary``, which is the function that then
    # overrides every characteristic CR 613 can move.
    "serialization.py": 2,
    # (``prompt_board.py`` held three until round kg — Balance's two lists and
    # the forced-sacrifice list, each drawing a permanent as its printed card.
    # ``PromptContext.serialize_permanent`` is the second injected callable,
    # ``_serialize_permanent_summary`` behind it, read through
    # ``PromptContext.describe_permanent``.)
}


def _web_files() -> tuple[pathlib.Path, ...]:
    return python_files("web")


def _receiver(line: str, at: int) -> str:
    """The name the ``.card`` at *at* hangs off, or "" when it is an expression
    this pattern cannot name."""
    match = _RECEIVER.search(line[:at])
    return match.group(1) if match else ""


def _hits(pattern: re.Pattern, *, skip_stack_receivers: bool) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _web_files():
        raw = source_text(path).splitlines()
        for number, line in enumerate(code_only_lines(path), 1):
            for match in pattern.finditer(line):
                if skip_stack_receivers and _receiver(line, match.start()) in STACK_RECEIVERS:
                    continue
                found.append(
                    (path.relative_to(WEB).as_posix(), number, raw[number - 1].strip())
                )
    return found


def _counts(hits: list[tuple[str, int, str]]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for module, _number, _text in hits:
        counted[module] = counted.get(module, 0) + 1
    return counted


def _report(hits: list[tuple[str, int, str]], modules: set[str]) -> str:
    return "\n".join(
        f"  web/{module}:{number}: {text}"
        for module, number, text in hits
        if module in modules
    )


def test_no_new_printed_type_or_colour_read_in_web():
    """"What type/colour is this permanent?" has one answer on this side of the
    wire too, and it is the computed one."""
    hits = _hits(_PRINTED_READ, skip_stack_receivers=True)
    counted = _counts(hits)
    over = {
        module for module, count in counted.items()
        if count > PRINTED_READ_BASELINE.get(module, 0)
    }
    assert not over, (
        "printed characteristic read off a permanent's card in web/ — ask "
        "permanent.has_type / permanent.is_creature / game._effective_colors / "
        "permanent.effective_card, or lower the module's entry in "
        "PRINTED_READ_BASELINE with the reason it really means the card:\n"
        + _report(hits, over)
        + "\n(baselines: "
        + ", ".join(f"{m}={PRINTED_READ_BASELINE.get(m, 0)} now {counted[m]}" for m in sorted(over))
        + ")"
    )


def test_no_new_printed_card_handed_to_a_renderer_in_web():
    """The same question one call deep: a permanent's ``.card`` passed whole to
    something that describes it."""
    hits = _hits(_PRINTED_CARD_ARGUMENT, skip_stack_receivers=False)
    counted = _counts(hits)
    over = {
        module for module, count in counted.items()
        if count > PRINTED_CARD_ARGUMENT_BASELINE.get(module, 0)
    }
    assert not over, (
        "a permanent's printed card handed to a card renderer in web/ — the "
        "payload will describe the card rather than the permanent (a Clone's "
        "own type line, an animated land's non-creature line). Pass the "
        "effective card, or lower the module's entry in "
        "PRINTED_CARD_ARGUMENT_BASELINE with the reason:\n"
        + _report(hits, over)
    )


@pytest.mark.parametrize(
    "baseline,pattern,skip",
    [
        (PRINTED_READ_BASELINE, _PRINTED_READ, True),
        (PRINTED_CARD_ARGUMENT_BASELINE, _PRINTED_CARD_ARGUMENT, False),
    ],
    ids=["printed-reads", "printed-card-arguments"],
)
def test_no_baseline_sits_above_its_real_count(baseline, pattern, skip):
    """A baseline higher than the truth is room for the next one to appear
    free, which is what makes the ratchet ratchet."""
    counted = _counts(_hits(pattern, skip_stack_receivers=skip))
    slack = {
        module: (expected, counted.get(module, 0))
        for module, expected in baseline.items()
        if counted.get(module, 0) < expected
    }
    assert not slack, (
        "baseline above the real count — lower these entries: "
        + ", ".join(f"{m}: {was} -> {now}" for m, (was, now) in sorted(slack.items()))
    )


def test_the_stack_receiver_exemption_is_still_used():
    """The named receivers are an exemption, and an exemption for something
    that no longer exists is how the next real read gets a free pass."""
    with_stack = len(_hits(_PRINTED_READ, skip_stack_receivers=False))
    without_stack = len(_hits(_PRINTED_READ, skip_stack_receivers=True))
    assert with_stack > without_stack, (
        "STACK_RECEIVERS excuses nothing any more — drop the names from it"
    )
