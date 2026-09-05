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
from engine.models import CardDefinition
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




def test_every_aura_in_the_pool_is_claimed_by_the_module_that_implements_it():
    """An Aura is supported because ``engine/auras.py`` implements it.

    That sentence was not true until Mirage's cleanup. An Aura's ``Enchant
    <subject>`` line is a keyword ability (CR 702.5) producing no instruction,
    and its effects are continuous rather than instructions — so a fully
    implemented Aura had **no evidence of support**, and the gate took it from
    the substring ``"enchant creature"`` in ``SUPPORTED_SPELL_PATTERNS``.

    Armor of Thorns is what that cost: its clause reads "Enchant **nonblack**
    creature", which the literal never matched, so it was carried by ``"gets +"``
    on a different line entirely. Support had come loose from working.
    """
    from engine.auras import aura_claim
    from engine.oracle import expand_ability_lines, normalize_creature_line

    unclaimed = []
    for card in load_catalog():
        if "Aura" not in card.type_line:
            continue
        # **Through ``expand_ability_lines``**, the rule this repo states and
        # the one the first draft of this test broke. Splitting raw
        # ``oracle_text`` reported Orcish Mine unclaimed: its conjoined "at the
        # beginning of your upkeep **and** whenever enchanted land becomes
        # tapped" is one printed line the rewrite splits into the two triggers
        # the claim table implements. The card was fine; the reader was reading
        # a different card. The gate never had this bug -- by the time it asks,
        # ``oracle_text`` is already expanded.
        lines = [
            normalize_creature_line(line)
            for line in expand_ability_lines(card.oracle_text or "").splitlines()
        ]
        if aura_claim(lines, card.name) is None:
            unclaimed.append(card.name)

    assert not unclaimed, (
        "Auras the pool ships that engine/auras.py does not claim: "
        f"{unclaimed}. They are supported by something else, which is the "
        "arrangement the substring whitelist used to provide."
    )


def test_the_aura_claim_is_what_holds_those_cards_up():
    """The claim must be load-bearing, not decorative.

    A claim that changes nothing when withdrawn is a claim nobody needs — and
    since this one replaced a substring that *was* doing the work, "the suite is
    still green" proves nothing on its own. So it is withdrawn here and the
    cards it names must fall over.
    """
    import engine.oracle as oracle

    sample = ["Pacifism", "Armor of Thorns", "Animate Wall", "Wild Growth"]
    catalog = {c.name: c for c in load_catalog()}

    # Patched on ``oracle``, not on ``auras``: the gate binds the name at import
    # (``from .auras import aura_claim``), so patching the defining module
    # leaves the bound reference untouched and nothing falls over — which is
    # how the first draft of this test passed while proving nothing.
    original = oracle.aura_claim
    try:
        oracle.aura_claim = lambda *a, **k: None
        oracle._compile_card_oracle.cache_clear()
        fell_over = [
            name for name in sample
            if not compile_card_oracle(catalog[name]).supported
        ]
    finally:
        oracle.aura_claim = original
        oracle._compile_card_oracle.cache_clear()

    assert sorted(fell_over) == sorted(sample), (
        "withdrawing the Aura claim left these still supported, so something "
        f"else is holding them up: {sorted(set(sample) - set(fell_over))}"
    )


def test_the_substring_whitelist_stays_empty():
    """The table is empty and nothing may put a card back into it.

    73 entries became 0 across two steps: a deletion probe showed 68 carried
    nobody, and the last five were Aura lines replaced by the claim above. An
    entry here is a card admitted because its text *contains* something, which
    is support that has come loose from working — the failure this whole file
    exists to catch.
    """
    from engine.oracle import SUPPORTED_SPELL_PATTERNS

    assert SUPPORTED_SPELL_PATTERNS == (), (
        f"the substring whitelist is back: {SUPPORTED_SPELL_PATTERNS}. A card "
        "the engine implements has an instruction, a claim or an ability to "
        "show for it."
    )


# --- VIS W3G5: timing evidence is not support ---
# `oracle._TIMING_ONLY_CLAIMS`, and the card that made the second entry
# necessary.
from engine.card_loader import (load_cards as _w3g5_load,
                                manifest_set_paths as _w3g5_paths)
from engine.oracle import compile_card_oracle as _w3g5_compile


def test_a_casting_permission_alone_does_not_make_a_card_supported():
    """The ``cast_timing`` claim is evidence about *when* a spell may be cast
    and never about what it does, so a card whose text is nothing else stays
    unsupported.

    W3G5 wrote this against Necromancy, whose second line was unimplemented at
    the time; W4G1 implemented that line, so the card is supported and can no
    longer demonstrate the rule. Asserting the *mechanism* instead is the
    stronger form and does not expire: an invented card printing the permission
    and nothing else is exactly the population the claim would wrongly hold up,
    and a printed card is not needed to ask the question.

    Read as behaviour, the gate credited Necromancy as **supported** while it
    reanimated nothing, with zero hollow lines and full parse coverage: the debt
    Mirage's promotion rehearsal found on eleven cards, arriving from the gate
    instead of from a whitelist word.
    """
    from engine.models import CardDefinition
    from engine.oracle import _compile_card_oracle

    permission = (
        "You may cast this spell as though it had flash. If you cast it any "
        "time a sorcery couldn't have been cast, the controller of the "
        "permanent it becomes sacrifices it at the beginning of the next "
        "cleanup step."
    )
    program = _compile_card_oracle(
        "Timing Only", "enchantment", permission, (), "normal", False,
    )

    assert all(
        i.kind == "derived_static_rule" and i.value == "cast_timing"
        for i in program.instructions
    ), program.instructions
    assert not program.supported, program.reason


def test_the_timing_claims_are_the_only_derived_rules_that_carry_no_behaviour():
    """The exception list is small on purpose, and each entry earned its place
    by a card that was reported supported on it alone.

    A claim added here is a claim that stops holding a card up, so the set is
    asserted rather than left to grow by habit.
    """
    from engine.oracle import _TIMING_ONLY_CLAIMS

    assert _TIMING_ONLY_CLAIMS == frozenset({
        "activation_restrictions", "cast_timing",
    })


def test_the_flash_cycle_is_still_supported_by_what_it_actually_does():
    """The other direction: withdrawing behaviour credit from the permission
    must not unsupport the cards that print it beside a real ability. Nine
    cards in the pool print the sentence and every one of them is held up by
    its own effect lines."""
    by_name = {c.name: c for c in _w3g5_load(_w3g5_paths(include_measured=True))}
    printers = [
        card for card in by_name.values()
        if "as though it had flash" in (card.oracle_text or "")
    ]

    assert len(printers) >= 9, printers
    unsupported = [
        card.name for card in printers if not _w3g5_compile(card).supported
    ]
    assert unsupported == [], unsupported
    # …and Necromancy, the one card that used to be on that list, is held up by
    # its effects rather than by the permission: W4G1 implemented the second
    # line, so the claim it once stood on alone is now the smaller half of what
    # supports it.
    necromancy = _w3g5_compile(by_name["Necromancy"])
    assert any(
        instruction.kind != "derived_static_rule"
        for instruction in necromancy.instructions
    ), necromancy.instructions
# --- end VIS W3G5 ---
