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


def test_the_whitelist_holds_no_bare_word():
    """The three bare substrings are gone, and nothing may put one back.

    ``"loses"``, ``"deals"`` and ``"gain"`` matched any sentence containing the
    word, and six of Mirage's thirteen unimplemented sentences were admitted
    into the support gate on exactly those three. The old guard here asserted
    they were *present* and merely carried nobody alone — a containment fence
    around a hazard rather than the removal of it, and it could not see a card
    admitted by one alongside a real instruction.

    They were deleted at Mirage's cleanup, with a deletion probe proving no card
    depended on them. What is left is five Aura enchant lines, each a phrase
    that names a whole printed line rather than a word inside one. A single word
    here would be a card admitted because its text happened to contain it.
    """
    from engine.oracle import SUPPORTED_SPELL_PATTERNS

    bare = sorted(p for p in SUPPORTED_SPELL_PATTERNS if " " not in p.strip())
    assert not bare, (
        f"bare single-word entries are back in the whitelist: {bare}. A word "
        "matches every sentence containing it; write the printed phrase."
    )


def test_no_spell_is_supported_by_a_whitelist_marker_alone():
    """The property the three per-word guards were reaching for, asked once and
    of every entry rather than of three named ones."""
    carried = [
        name
        for name, instrs in _hollow_spells()
        if instrs and all(i.startswith("spell_pattern:") for i in instrs)
    ]

    assert not carried, (
        f"spells supported only by a whitelist substring: {carried}"
    )


# ---------------------------------------------------------------------------
# The permanent half
# ---------------------------------------------------------------------------


def _hollow_permanents() -> list[tuple[str, list[str], list[str]]]:
    hollow: list[tuple[str, list[str], list[str]]] = []
    for card in _whole_pool():
        if card.primary_type not in ("artifact", "enchantment"):
            continue
        # Auras answer to engine/auras.py, which runs first and is stricter —
        # see test_an_aura_is_left_to_its_own_gate below. Equipment used to be
        # skipped beside them; it is not any more, because an Equipment now
        # carries a real equip ability (CR 702.6a) and so never has the hollow
        # shape — see test_equipment_is_supported_on_its_equip_ability.
        if "Aura" in card.type_line:
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
        # Mazemind Tome's shape as it *was*: "draw a card" is a whitelist
        # substring, so the card-level marker matched while the ability that
        # would have done the drawing did not parse. Its real cost is read since
        # round 127, so the probe now spells a counter kind the cost table
        # cannot charge — the property under test is the shape, not the card.
        "{T}, Put a page counter on target artifact: Draw a card.",
        # Same with a trigger rather than an activated ability: the condition is
        # read and the effect clause is not. "gain" matched the whitelist when
        # this was written, which is why the shape needed a test at all.
        "When this artifact enters the battlefield, you gain 4 life for each "
        "Shrine you control.",
    ],
)
def test_a_permanent_whose_only_ability_is_unreadable_is_unsupported(text):
    """Verified by injection rather than by the pool alone: the shipped pool is
    clean, so the property test above passes against a compiler that never
    learned this. These are the shapes it must refuse.

    **The reason must name the shape, and which name is right depends on the
    ability.** Both of these used to answer "no ability of this permanent is
    implemented", because a whitelist substring manufactured a card-level
    instruction and that branch needed one. With the whitelist down to five
    Aura entries the trigger case reaches an earlier and *better* branch —
    "unsupported triggered ability" says which half of the card failed. So this
    asserts the property that matters (the card is refused, and the refusal
    names something) rather than one exact string, which was only ever a
    description of the route.
    """
    program = _probe(text)
    assert not program.supported
    assert program.reason and program.reason != "effect not in basic pattern set", (
        f"the refusal must name what could not be read, not fall back to the "
        f"generic message: {program.reason!r}"
    )
    assert (
        "no ability of this permanent is implemented" in program.reason
        or "unsupported triggered ability" in program.reason
    ), program.reason


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


# Round 53 found the blind spot with three cards and this test named all three.
# All three are implemented now — Sanctum of Stone Fangs in round 54, Fiery
# Emancipation and Teferi's Ageless Insight in 57 and 58 — so a card list here
# would be empty, and an empty list is a guard that passes because it asks
# nothing. The *property* is what survives, probed with text no card prints:
# a permanent whose one line the parser refuses outright leaves no ability
# object behind, and "no ability failed" is not the same as "nothing failed".
def test_a_permanent_whose_line_never_became_an_ability_is_unsupported():
    """The shape of the blind spot. The gate asked for an unreadable *ability*,
    which is an ability that failed late enough to become an object; a line the
    parser refuses outright leaves the list empty, so the more completely a line
    failed the more likely the card was to pass. All three cards entered play,
    reported supported and did nothing."""
    pool = {c.name: c for c in _whole_pool()}
    program = compile_card_oracle(
        dataclasses.replace(
            pool["Fiery Emancipation"],
            name="Probe Enchantment",
            oracle_text="Whenever the sky is green, you win the game.",
        )
    )

    assert not program.supported
    assert "no ability of this permanent is implemented" in program.reason
    assert "sky is green" in program.reason


def test_equipment_is_supported_on_its_equip_ability():
    """An Equipment is no longer exempt from the hollow-permanent gate, because
    it no longer needs to be. Short Sword used to be supported on the substring
    "gets +" alone — its equip line compiled to nothing, so it entered play and
    could never be attached — and the gate had to exempt "equip" by shape or
    refuse it. CR 702.6a defines equip as an activated ability; the compiler
    now rewrites the keyword into that ability, which is the "something
    supported" the gate already looks for.

    The exemption's *absence* is the point of this test: an Equipment whose
    equip ability fails to compile is refused, with the line named, rather than
    slipping past the gate on the strength of the word.
    """
    pool = {c.name: c for c in _whole_pool()}
    for name in ("Short Sword", "Malefic Scythe"):
        program = compile_card_oracle(pool[name])
        assert program.supported, program.reason
        equips = [
            a for a in program.activated_abilities
            if a.instruction is not None and a.instruction.kind == "attach_source_to_target"
        ]
        assert len(equips) == 1, f"{name} should carry exactly one compiled equip ability"
        assert equips[0].supported

    # The control: the same card with its equip line replaced by one the
    # expansion refuses (CR 702.6e's planeswalker variant) has no supported
    # ability left and is refused naming the equip line — not admitted on the
    # "gets +" substring, and not exempted by the word.
    probe = compile_card_oracle(
        dataclasses.replace(
            pool["Short Sword"],
            name="Probe Sword",
            oracle_text="Equipped creature gets +1/+1.\nEquip planeswalker {1}",
        )
    )
    assert not probe.supported
    assert "equip ability not implemented" in probe.reason
    assert "Equip planeswalker {1}" in probe.reason


def test_the_pool_scan_reaches_every_manifest_role():
    """The other half of why this was never found: the scan read the shipped
    pool alone, which is the half held at 100% support and looked at constantly.
    All three cards lived in M21, which was measured at the time.

    M21 ships now, so "wider than the catalog" has nothing left to be wider
    *than* — and asserting a strict superset would make this guard fail every
    time a set is promoted, which is the moment it matters least. What is
    actually being held is that the scan reads the manifest's **roles** rather
    than one of them, so it is asked that way: every shipped card is scanned,
    and every measured card would be too.
    """
    names = {c.name for c in _whole_pool()}
    assert "Sanctum of Stone Fangs" in names
    assert names >= {c.name for c in load_catalog()}
    measured = {
        card.name
        for path in manifest_set_paths(include_measured=True)
        for card in load_cards(path)
    }
    assert names >= measured


def test_an_equipment_with_an_unimplemented_effect_line_is_unsupported():
    """The other half of the Equipment gate: an Equipment whose *effect* line
    nothing reads is refused naming the line, instead of shipping with an equip
    that attaches a do-nothing. Before the gate existed, the equip line and the
    effect line were both unread and the card was supported on "gets +"."""
    pool = {c.name: c for c in _whole_pool()}
    probe = compile_card_oracle(
        dataclasses.replace(
            pool["Short Sword"],
            name="Probe Equipment",
            oracle_text="Equipped creature has hexproof from everything.\nEquip {1}",
        )
    )
    assert not probe.supported
    assert "unimplemented equipment effect" in probe.reason
    assert "hexproof from everything" in probe.reason


# ---------------------------------------------------------------------------
# The land half
# ---------------------------------------------------------------------------


def _hollow_lands() -> list[tuple[str, list[str]]]:
    """Lands that print ability lines and compiled none of them.

    A land's mana comes from ``CardDefinition.produced_mana``, never from
    parsing, so ``engine/oracle.py``'s land gate passes every land: "an
    unparsed *bonus* ability degrades just that ability, never the land's own
    castability". That is the right rule for Desert's damage ping — and the
    code never implemented the distinction the comment draws, so a land whose
    unreadable line **is** its mana ability was passed by the same blanket
    clause.

    Antiquities is what made the difference visible. Urza's Mine, Power Plant
    and Tower each print one line, that line is the whole card, and none of
    them parsed: all three reported supported, tapped for the flat ``{C}`` that
    ``produced_mana`` records and could never assemble. Mishra's Workshop is the
    sharper one, because nothing about it looks broken — it taps for one ``{C}``
    where the card prints three, and spends it on anything.

    The property is the same one the artifact half asks, so it is written the
    same way: a permanent that prints abilities and can read none of them does
    not do what it says. A land with *some* readable ability is degraded, not
    hollow, and stays supported — that is the documented rule working.
    """
    return [
        (card.name, [a.source_line for a in _land_abilities(card)])
        for card in _whole_pool()
        if _is_hollow_land(card)
    ]


def _land_abilities(card) -> tuple:
    program = compile_card_oracle(card)
    return (*program.activated_abilities, *program.triggered_abilities)


def _is_hollow_land(card) -> bool:
    """The predicate itself, so the guard and its control ask one question.

    It used to be written out inside the sweep, and the control below asserted
    the same property a second time against a card that happened to have it —
    which stopped being true the moment that card's last unread line was
    implemented. A predicate has one home.
    """
    if card.primary_type != "land":
        return False
    program = compile_card_oracle(card)
    if not program.supported:
        return False
    abilities = _land_abilities(card)
    if not abilities:
        # No printed ability at all: a basic or a dual, whose whole text is
        # CR 305.6 reminder text. `produced_mana` is the whole card and it is
        # right.
        return False
    return not any(a.supported and a.instruction is not None for a in abilities)


def test_no_supported_land_prints_only_unreadable_abilities():
    hollow = _hollow_lands()

    assert not hollow, (
        "supported land(s) whose every printed ability failed to parse — they "
        "tap for whatever produced_mana records and do nothing else:\n"
        + "\n".join(f"  {name}: {lines}" for name, lines in sorted(hollow))
    )


def _invented_land(text: str) -> CardDefinition:
    """A land that exists only for this test, with *text* as its whole rules box.

    Invented rather than borrowed. The control was Mishra's Factory for as long
    as one of its three abilities was unread, and the day the animation was
    implemented the control silently stopped testing anything — it asserted the
    card *had* an unreadable line, which is a fact about the pool and not about
    the guard. No land in the pool has one now, and none should: a card is the
    wrong place to keep a fixture.
    """
    return CardDefinition(
        name="Invented Land",
        mana_cost="",
        cmc=0.0,
        type_line="Land",
        oracle_text=text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=("C",),
        raw={},
    )


def test_a_land_with_one_readable_ability_is_not_hollow():
    """The other direction, and the reason the guard asks *all* rather than
    *any*: a land doing *less* than it prints is degradation, which the
    coverage instruments report and this guard deliberately does not fail on —
    as against one that does nothing it prints at all."""
    mixed = _invented_land(
        "{T}: Add {C}.\n"
        "{2}: This land glimmers uncontrollably until end of turn."
    )
    abilities = _land_abilities(mixed)

    assert any(a.supported and a.instruction is not None for a in abilities), (
        "the control needs a readable ability, or it is testing the wrong thing"
    )
    assert any(not a.supported or a.instruction is None for a in abilities), (
        "the control needs an unreadable ability too — otherwise it would pass "
        "against a guard that failed every land with any unread line"
    )
    assert not _is_hollow_land(mixed)


def test_a_land_with_no_readable_ability_never_reaches_the_sweep():
    """The other end of the same rule, and where round 1 left it: a land whose
    only ability is unread is refused by the *support gate* before this guard
    could see it. So the sweep above is a ratchet on that gate rather than the
    thing doing the work, and this says which — a land that started reporting
    supported again would show up there, loudly."""
    unreadable = _invented_land("{2}: This land glimmers uncontrollably until end of turn.")

    assert not compile_card_oracle(unreadable).supported
    assert not _is_hollow_land(unreadable)


# ---------------------------------------------------------------------------
# The Aura half: a claim that asks, rather than a wildcard that assumes
# ---------------------------------------------------------------------------


def test_an_aura_trigger_nothing_implements_leaves_the_card_unsupported():
    """`engine/auras.py` is the Aura gate and the guard above defers to it as
    "the stricter of the two". It was stricter about everything except its own
    catch-all: one template matched ``when(ever) enchanted|equipped <anything>``
    and claimed the line for "trigger_utils / upkeep_effects" without asking
    either of them.

    That is a guard satisfied by its own declaration — the round-140 shape.
    Antiquities' Artifact Possession is the card that proves it: its whole
    effect is one trigger nothing in the engine reads, the wildcard claimed the
    line, the gate found no unclaimed effect and the card reported supported
    while enchanting an artifact and doing nothing.

    Verified by injection, because the pool cannot show it: whichever cards
    currently rest on the wildcard are implemented, so a property test over the
    pool passes against the wildcard too. The property is that an *invented*
    attached trigger the engine has never heard of must not be claimed.
    """
    program = _probe(
        "Enchant creature\n"
        "Whenever enchanted creature is dealt damage by a Wall, "
        "flip three coins and untap every Forest.",
        type_line="Enchantment — Aura",
    )

    assert not program.supported
    assert "unimplemented aura effect" in program.reason


def test_an_attached_trigger_the_engine_does_read_is_still_claimed():
    """The other direction, and the reason the fix is an *asked* claim rather
    than deleting the wildcard. Three shipped cards rest on it and all three
    work — Psychic Venom and Malefic Scythe compile a trigger; Creature Bond
    compiles a condition whose dispatcher lives in mixins/effects.py and leaves
    no instruction behind. Deleting the template would have withdrawn all
    three."""
    pool = {c.name: c for c in _whole_pool()}
    for name in ("Psychic Venom", "Malefic Scythe", "Creature Bond"):
        assert compile_card_oracle(pool[name]).supported, name
