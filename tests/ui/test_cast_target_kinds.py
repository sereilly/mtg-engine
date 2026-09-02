"""Every target kind the backend can name is a kind the browser can collect.

Two functions on the server decide what a cast asks the player for, and they
are *different* functions: ``engine.targeting.derive_cast_spec`` answers for a
card, and ``web.serialization._mode_target_kind`` answers for one mode of a
modal spell. The browser has one table for both
(``startCastPromptForKind`` in ``web/static/app.js``), and a kind missing from
it is not a missing feature — it is a cast sent with **no target at all**,
which the engine then aims at whatever its fallback points to. That is how
"Exile two target artifacts" came to exile one and how "target player or
planeswalker" came to be aimed at a default seat.

So the kinds are compared rather than trusted. The JS side is read as source
text: ``app.js`` is a DOM-coupled script that bare ``node`` cannot load (unlike
``legality.js``, which the parity suite next door does run), and the switch
labels are the thing being checked, so reading them is reading the real answer
rather than a paraphrase of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.legality import targeting_instruction
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from web.serialization import _mode_target_kind

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)

# Shipped *and* measured: a kind the browser cannot collect is just as
# uncollectable on a card nobody can deck yet, and the ingest of the set that
# first prints one is exactly when this should fail.
_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

#: Kinds that name no choice, so no prompt collects them.
_NO_PROMPT = frozenset({"none", "modal"})

#: A cost payment is not a target (CR 601.2b vs CR 601.2c) and has its own
#: prompt — ``startCastCostPrompt`` — reached before the target cascade runs.
_COST_KINDS = frozenset({"hand_card"})


def _routed_kinds() -> frozenset[str]:
    """The kinds ``startCastPromptForKind`` routes, read off its switch."""
    body = re.search(
        r"function startCastPromptForKind\([^)]*\)\s*\{(.*?)\n\}\n", APP_JS, re.S
    )
    assert body is not None, "startCastPromptForKind is gone or was renamed"
    return frozenset(re.findall(r'case "([a-z_]+)":', body.group(1)))


def _cast_spec_kinds() -> frozenset[str]:
    """Every kind a card's own cast spec reports, over every castable zone."""
    found = set()
    for card in _POOL.values():
        program = compile_card_oracle(card)
        for zone in ("hand", "graveyard", "exile", "command"):
            spec = derive_cast_spec(card, program, from_zone=zone)
            if spec is not None:
                found.add(spec["kind"])
    return frozenset(found)


def _mode_kinds() -> frozenset[str]:
    """Every kind one mode of a modal spell reports."""
    found = set()
    for card in _POOL.values():
        program = compile_card_oracle(card)
        if len(program.modes) < 2:
            continue
        for mode in program.modes:
            if not mode.supported:
                continue
            instruction = targeting_instruction(mode.instruction) or mode.instruction
            found.add(_mode_target_kind(instruction))
    return frozenset(found)


def test_the_pool_produces_kinds_to_check():
    """Both enumerations read the pool rather than a list, so an ingest that
    renamed a kind would quietly empty them and the comparisons below would
    pass over nothing."""
    assert len(_cast_spec_kinds()) > 5
    assert len(_mode_kinds()) > 2


def test_every_cast_spec_kind_has_a_prompt():
    missing = _cast_spec_kinds() - _routed_kinds() - _NO_PROMPT - _COST_KINDS
    assert not missing, (
        f"derive_cast_spec reports {sorted(missing)} for a card in the pool and "
        "startCastPromptForKind routes none of them — those casts are sent with "
        "no target"
    )


def test_every_modal_mode_kind_has_a_prompt():
    """The half that has no other guard: a mode's kind comes from
    ``_mode_target_kind``, whose own fall-through answers "player" for an
    instruction it does not recognize, so a kind it *does* recognize and the
    client does not is the only way this goes wrong — and it goes wrong
    silently."""
    missing = _mode_kinds() - _routed_kinds() - _NO_PROMPT
    assert not missing, (
        f"a modal mode in the pool reports {sorted(missing)} and the client "
        "routes none of them"
    )


def test_the_client_refuses_a_kind_it_cannot_collect():
    """And when one does slip through, the cast must not happen.

    ``dispatchModalCast`` used to fall through its switch into an untargeted
    ``sendAction``, which is the silent partial match ``engine/grammar/`` refuses
    in the same words. The refusal is what makes the two tests above a tripwire
    rather than the only thing standing between a new kind and a wrong cast.
    """
    body = re.search(
        r"function dispatchModalCast\([^)]*\)\s*\{(.*?)\n\}\n", APP_JS, re.S
    )
    assert body is not None
    assert "startCastPromptForKind" in body.group(1)
    assert "can't be chosen here yet" in body.group(1)


@pytest.mark.parametrize(
    "card_name,kind",
    [
        # The four cards the ordering bug hit, pinned by kind so a spec change
        # that moves one of them off its picker is a failure here too.
        ("Dust to Dust", "artifact"),
        ("Avalanche", "land"),
        ("Volcanic Eruption", "land"),
        ("Sanguine Indulgence", "graveyard_creature"),
    ],
)
def test_a_several_target_spell_still_reports_its_kind(card_name, kind):
    """A card naming several targets keeps the kind of the things it names — the
    several-target picker is chosen by ``max_targets``/``x_targets``, not by a
    kind of its own, and the cascade has to ask about those *before* the
    per-kind prompts. It did not, so all three of the battlefield ones took the
    single-target picker and named one permanent for a spell that prints two or
    X."""
    card = _POOL[card_name]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec["kind"] == kind
    assert spec.get("max_targets") or spec.get("x_targets")


def test_several_targets_is_asked_before_the_per_kind_prompts():
    """The order itself, which is the whole fix: in ``startCastTargetCascade``
    the several-target question comes before ``land`` and ``artifact``.

    The graveyard question stays ahead of it deliberately — Sanguine
    Indulgence's several targets are clicked in the zone-reveal panel rather
    than on the canvas, so that prompt carries its own multi-select.
    """
    cascade = re.search(
        r"function startCastTargetCascade\([^)]*\)\s*\{(.*?)\n\}\n", APP_JS, re.S
    )
    assert cascade is not None
    body = cascade.group(1)
    several = body.index("cardRequiresSeveralTargets")
    assert several < body.index("cardRequiresTargetLand")
    assert several < body.index("cardRequiresTargetArtifact")
    assert body.index("cardRequiresTargetGraveyardCreature") < several


# ---------------------------------------------------------------------------
# "two target artifacts" is not "up to two" — CR 601.2c
# ---------------------------------------------------------------------------
#
# The grammar has told the two quantifiers apart since it parsed them
# ("exactly" / "up_to"), and the spec folded both into `max_targets`. Nobody
# noticed while the only cards reaching the several-target picker were the "up
# to" ones; moving the picker ahead of the per-kind prompts is what brought a
# printed number to it.


def _several_target_cards() -> dict[str, dict]:
    found = {}
    for name, card in _POOL.items():
        spec = derive_cast_spec(card, compile_card_oracle(card))
        if spec and spec.get("max_targets"):
            found[name] = spec
    return found


def test_a_printed_number_is_reported_exact():
    """The whole pool, so the two halves stay named by their quantifier rather
    than by a list here."""
    specs = _several_target_cards()
    exact = {name for name, spec in specs.items() if spec.get("exact_targets")}

    # "Destroy two target nonartifact creatures" / "Exile two target artifacts".
    assert exact == {"Ashes to Ashes", "Dust to Dust"}, sorted(exact)
    # And the "up to" ones must not claim it, or the picker would refuse an
    # announcement the card allows — CR 601.2c lets those choose fewer, none
    # included.
    assert not specs["Sanguine Indulgence"].get("exact_targets")
    assert not specs["Basri's Acolyte"].get("exact_targets")


def test_the_prompt_requires_the_printed_number():
    """The client half: the confirm is unreachable while an exact count is
    short, and reachable at once for an "up to" one."""
    assert "function severalTargetsAreExact(" in APP_JS
    assert "exact_targets" in APP_JS
    assert "severalExact && severalChosen < pendingCastTarget.maxTargets" in APP_JS
