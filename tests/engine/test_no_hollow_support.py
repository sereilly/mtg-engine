"""Guard: a supported card must actually do something.

``supported`` is set by the oracle compiler as soon as *any* instruction was
produced — including a ``spell_pattern`` marker, which carries no behavior and
exists only to record that a whitelist substring matched. A card can therefore
report support, pass the parse-coverage guard (its text is "claimed"), be marked
verified in CARD_VERIFICATION.md, and still resolve as a complete no-op.

That is exactly what Shahrazad did: its text contains the word "loses", the
whitelist has a bare ``"loses"`` entry, and casting it logged "Resolved
supported pattern ... without state mutation" while nothing changed. The
acknowledgement in parse_coverage.py even described life-halving behavior that
did not exist.

This checks the property directly, in two shapes:

* **A spell** must compile at least one instruction with a registered handler,
  because that is the only way an instant or sorcery can do anything.
* **A permanent** may work through statics, auras, layers or the text-keyed step
  tables instead — but every one of those leaves a real instruction behind
  (``static_line``, ``derived_static_rule``, an effect kind). What it may not do
  is carry a whitelist marker and *nothing else* while every ability line it
  prints failed to parse. Mazemind Tome shipped in M21 that way: two activated
  abilities, both with ``instruction=None``, and an artifact that entered play,
  offered both and performed neither.

The permanent half used to be excluded here wholesale, on the grounds that a
permanent's work happens elsewhere. That is true of *where* the work is and not
of *whether* there is any, which is what this asks.
"""

import dataclasses

import pytest

from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.handlers import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle


def _whole_pool():
    """Every card the engine can read, **measured sets included**.

    A permanent that does nothing does nothing whether or not a deck may hold
    it, and the shipped pool is the half least likely to be wrong — it is held
    at 100% support and looked at constantly. Scanning `load_catalog()` alone
    left the measured set unwatched, which is where all three of the cards the
    blind spot below was hiding turned out to live.
    """
    seen = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            seen.setdefault(card.name, card)
    return list(seen.values())


def _hollow_spells() -> list[tuple[str, list[str]]]:
    hollow: list[tuple[str, list[str]]] = []
    for card in load_catalog():
        type_line = card.type_line.lower()
        if "instant" not in type_line and "sorcery" not in type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        if program.modes:
            # A modal spell selects its instruction at resolution from the
            # chosen mode, so the top-level instruction list is not the whole
            # story.
            continue
        if any(instr.kind in EFFECT_HANDLERS for instr in program.instructions):
            continue
        hollow.append((card.name, [f"{i.kind}:{i.value}" for i in program.instructions]))
    return hollow


def test_no_supported_spell_resolves_without_an_effect():
    """A supported instant or sorcery whose every instruction lacks a handler
    resolves to nothing at all. Either give it an effect or classify it
    unsupported with a reason — silent no-op support is the failure mode the
    whole parse-coverage apparatus exists to prevent."""
    hollow = _hollow_spells()

    assert not hollow, (
        "supported spells that resolve with no registered handler (they do "
        f"nothing when cast): {hollow}"
    )


@pytest.mark.parametrize("bare_pattern", ["loses", "deals", "gain"])
def test_broad_whitelist_patterns_never_carry_a_card_alone(bare_pattern):
    """The spell-pattern whitelist holds bare substrings like "loses" that
    match far more text than they describe. None of them may be the only thing
    making a spell supported — that is how a card ends up claiming support for
    text nothing implements."""
    from engine.oracle import SUPPORTED_SPELL_PATTERNS

    assert bare_pattern in SUPPORTED_SPELL_PATTERNS, (
        f"{bare_pattern!r} left the whitelist; drop it from this test too"
    )
    carried = [
        name
        for name, instrs in _hollow_spells()
        if instrs == [f"spell_pattern:{bare_pattern}"]
    ]

    assert not carried, f"spells supported only by the bare {bare_pattern!r} pattern: {carried}"


# ---------------------------------------------------------------------------
# The permanent half
# ---------------------------------------------------------------------------


def _hollow_permanents() -> list[tuple[str, list[str], list[str]]]:
    hollow: list[tuple[str, list[str], list[str]]] = []
    for card in _whole_pool():
        if card.primary_type not in ("artifact", "enchantment"):
            continue
        # Auras and Equipment answer to engine/auras.py, which runs first and is
        # stricter — see test_an_aura_is_left_to_its_own_gate below. Equipment
        # is here for the same reason and by the same shape: Short Sword's
        # "+1/+1" is an `aura_static_pt_grant` that leaves no instruction for
        # this scan to find.
        if "Aura" in card.type_line or "Equipment" in card.type_line:
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        if not program.instructions:
            continue
        if any(i.kind != "spell_pattern" for i in program.instructions):
            continue
        abilities = (*program.activated_abilities, *program.triggered_abilities)
        if any(a.supported and a.instruction is not None for a in abilities):
            continue
        # **No `if not unreadable: continue` here.** The guard used to skip a
        # card with no unreadable ability, which sounds like "nothing failed"
        # and means "nothing failed *late enough to become an object*" — a line
        # the parser refuses outright leaves no ability behind at all. The
        # compiler's gate had the identical blind spot, written from the same
        # thought at the same time, so this guard could not have found it: it
        # hid Sanctum of Stone Fangs, Fiery Emancipation and Teferi's Ageless
        # Insight, three permanents that entered play and did nothing.
        unreadable = [a.source_line for a in abilities if not a.supported or a.instruction is None]
        hollow.append((
            card.name,
            [f"{i.kind}:{i.value}" for i in program.instructions],
            unreadable or [ln for ln in card.oracle_text.splitlines() if ln.strip()],
        ))
    return hollow


def test_no_supported_permanent_carries_only_a_whitelist_marker():
    """A permanent whose every card-level instruction is a whitelist marker and
    whose every printed ability failed to parse does nothing at all. It must be
    classified unsupported naming the clause, not reported as playable."""
    hollow = _hollow_permanents()

    assert not hollow, (
        "supported permanent(s) with no behaviour behind them — a whitelist "
        "substring matched and every ability line failed to parse:\n"
        + "\n".join(f"  {name}: {kinds} / {lines}" for name, kinds, lines in sorted(hollow))
    )


def _probe(text: str, type_line: str = "Artifact"):
    catalog = {c.name: c for c in load_catalog()}
    return compile_card_oracle(
        dataclasses.replace(
            catalog["Jayemdae Tome"], name="Probe", type_line=type_line, oracle_text=text
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        # Mazemind Tome's shape: "draw a card" is a whitelist substring, so the
        # card-level marker matched, while the ability that would have done the
        # drawing did not parse and carries no instruction.
        "{T}, Put a page counter on this artifact: Draw a card.",
        # Same with a trigger rather than an activated ability: the condition is
        # read, the effect clause is not, and "gain" matched the whitelist.
        "When this artifact enters the battlefield, you gain 4 life for each "
        "Shrine you control.",
    ],
)
def test_a_permanent_whose_only_ability_is_unreadable_is_unsupported(text):
    """Verified by injection rather than by the pool alone: the shipped pool is
    clean, so the property test above passes against a compiler that never
    learned this. These are the shapes it must refuse."""
    program = _probe(text)
    assert not program.supported
    assert "no ability of this permanent is implemented" in program.reason


def test_a_permanent_whose_work_is_done_by_a_rule_table_keeps_its_support():
    """The other direction, and the reason the gate needs both conjuncts.
    Howling Mine's trigger does not parse either — its behaviour lives in
    engine/draw_step_modifiers.py, which leaves a ``derived_static_rule``
    instruction. That is not a whitelist marker, so the card is not hollow."""
    program = compile_card_oracle({c.name: c for c in load_catalog()}["Howling Mine"])
    assert program.supported
    assert any(i.kind == "derived_static_rule" for i in program.instructions)


def test_an_aura_is_left_to_its_own_gate():
    """Auras are excluded by shape, not by name. engine/auras.py runs first and
    is stricter — it names the first unclaimed *effect line* — and it knows about
    the Aura death trigger that mixins/effects.py carries with no instruction of
    its own. Creature Bond has exactly that shape and works."""
    program = compile_card_oracle({c.name: c for c in load_catalog()}["Creature Bond"])
    assert program.supported
    assert all(
        a.instruction is None for a in program.triggered_abilities
    ), "the trigger still has no instruction — its behaviour is elsewhere"


# ---------------------------------------------------------------------------
# The blind spot both halves shared
# ---------------------------------------------------------------------------


# Sanctum of Stone Fangs was the third of these and is gone from the list
# because round 54 implemented it — which is the only way an entry may leave.
# The two that remain are replacement effects nobody has built.
@pytest.mark.parametrize(
    "name,clause",
    [
        ("Fiery Emancipation", "would deal damage"),
        ("Teferi's Ageless Insight", "would draw a card"),
    ],
)
def test_a_permanent_whose_line_never_became_an_ability_is_unsupported(name, clause):
    """The three cards the blind spot hid, and the shape of it: each prints one
    line, the parser refuses that line outright, and so **no ability object was
    ever built**. The gate asked for an unreadable ability and found none, which
    reads as "nothing failed" and means "nothing failed late enough to leave a
    record". All three entered play, reported supported and did nothing."""
    pool = {c.name: c for c in _whole_pool()}
    program = compile_card_oracle(pool[name])

    assert not program.supported
    assert "no ability of this permanent is implemented" in program.reason
    assert clause in program.reason.lower(), program.reason


def test_equipment_is_left_to_its_own_gate_like_an_aura():
    """The control for the widening, and the reason the exclusion is by shape
    rather than by name. Short Sword's "+1/+1" is an ``aura_static_pt_grant``
    read off the card's text by engine/auras.py, which leaves no instruction
    here — so dropping the unreadable-ability requirement would have refused two
    Equipment that work perfectly well."""
    pool = {c.name: c for c in _whole_pool()}
    for name in ("Short Sword", "Malefic Scythe"):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        assert all(i.kind == "spell_pattern" for i in program.instructions), (
            f"{name} is exactly the shape the gate refuses, minus the exclusion"
        )


def test_the_pool_scan_reaches_the_measured_set():
    """The other half of why this was never found: the scan read the shipped
    pool alone, which is the half held at 100% support and looked at constantly.
    All three cards live in M21."""
    names = {c.name for c in _whole_pool()}
    assert "Sanctum of Stone Fangs" in names
    assert names > {c.name for c in load_catalog()}
