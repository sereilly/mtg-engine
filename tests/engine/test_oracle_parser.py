from engine.models import CardDefinition
from engine.oracle import compile_card_oracle, lex_oracle_text, parse_activated_ability_cost


def _mk_card(name: str, type_line: str, oracle_text: str = "", keywords: tuple[str, ...] = ()) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def test_lexer_preserves_mana_symbols_and_colon():
    tokens = lex_oracle_text("{1}, {T}: Target creature gains banding until end of turn.")

    assert [token.value for token in tokens[:5]] == ["{1}", ",", "{T}", ":", "target"]




def test_compile_spell_program_emits_executable_instruction():
    card = _mk_card("Bolt Test", "Instant", "Bolt Test deals 3 damage to any target.")

    program = compile_card_oracle(card)

    assert program.supported is True
    assert program.instructions[0].kind == "deal_damage"
    assert program.instructions[0].payload["amount"] == 3


def test_compile_activated_ability_emits_banding_instruction():
    card = _mk_card(
        "Helm Test",
        "Artifact",
        "{1}, {T}: Target creature gains banding until end of turn.",
    )

    program = compile_card_oracle(card)

    assert program.supported is True
    assert program.activated_abilities[0].instruction is not None
    assert program.activated_abilities[0].instruction.kind == "grant_banding_to_target"




# ---------------------------------------------------------------------------
# "Choose one —" modal spells
# ---------------------------------------------------------------------------
#
# Splitting the bullets is line classification, which this module owns; each
# bullet's *effect* then goes to the same front ends an ordinary line does. That
# split is what stops a modal spell being read off its whole collapsed text,
# where "counter target red spell. destroy target red permanent" is one sentence
# describing a spell that does both.

def test_a_modal_spell_compiles_one_mode_per_bullet():
    card = _mk_card(
        "Blast Test",
        "Instant",
        "Choose one —\n• Counter target red spell.\n• Destroy target red permanent.",
    )

    program = compile_card_oracle(card)

    assert program.supported is True
    assert [mode.instruction.kind for mode in program.modes] == [
        "counter_top_stack_spell", "destroy_target_permanent"
    ]
    assert all(mode.supported for mode in program.modes)
    assert [mode.label for mode in program.modes] == [
        "Counter target red spell", "Destroy target red permanent"
    ]


def test_a_modal_spells_card_level_instruction_is_its_first_mode():
    """The stack executes this list when no mode was chosen, and the bullets are
    alternatives — so the first one is the only honest candidate. Reading the
    whole text instead would produce an instruction for a sentence the card
    never performs on its own."""
    card = _mk_card(
        "Blast Test",
        "Instant",
        "Choose one —\n• Counter target red spell.\n• Destroy target red permanent.",
    )

    program = compile_card_oracle(card)

    assert [i.kind for i in program.instructions if i.kind != "spell_pattern"] == [
        "counter_top_stack_spell"
    ]


def test_a_mode_nothing_reads_refuses_the_whole_card():
    """The reversal of the policy this test used to pin. Per-mode support let a
    card with one dead mode report supported — the UI then offered the whole
    mode list and the dead choice resolved to nothing (the Read the Tides
    finding, round 17). The gate is all-of, like the planeswalker one: every
    printed mode or the card refuses, naming the mode nothing reads."""
    card = _mk_card(
        "Half Test",
        "Instant",
        "Choose one —\n• Target player gains 3 life.\n• Ponder the infinite.",
    )

    program = compile_card_oracle(card)

    assert not program.supported
    assert "modal mode not implemented" in program.reason
    assert "Ponder the infinite" in program.reason


def test_a_head_asking_for_a_count_the_engine_cannot_carry_is_not_read_as_choose_one():
    """"choose one" is a substring of "choose one or more", and the test this
    replaced matched it, so a spell whose controller picks several modes
    compiled as one that picks the first. The grammar reads the *count*, and a
    count it refuses reaches here as a head with no modes at all rather than as
    a wrong number of them.

    "One or more" is carried now (Sublime Epiphany); an exact count above one is
    still refused, so that is what this asks about. The point is unchanged: the
    number the head printed is either understood or the card is unsupported.
    """
    card = _mk_card(
        "Epiphany Test",
        "Instant",
        "Choose two —\n• Counter target spell.\n• Target player draws a card.",
    )

    program = compile_card_oracle(card)

    assert program.modes == ()
    assert program.supported is False


def test_a_head_choosing_one_or_more_carries_its_modes_and_says_so():
    """The counterpart, on the same card shape: the modes are read *and* the
    program records that more than one may be chosen. Recording the bound is the
    half that matters — a mode list without it is a spell the cast path would
    still hold to one mode."""
    card = _mk_card(
        "Epiphany Test",
        "Instant",
        "Choose one or more —\n• Counter target spell.\n• Target player draws a card.",
    )

    program = compile_card_oracle(card)

    assert [m.label for m in program.modes] == [
        "Counter target spell", "Target player draws a card",
    ]
    assert program.modes_at_least is True
    assert program.supported is True


def test_a_lone_bullet_under_a_head_is_not_a_mode_list():
    """CR 700.2: a modal spell has "two or more options in a bulleted list".
    One option is text this does not understand, and returning it as a one-mode
    spell would be a guess wearing the shape of a reading."""
    card = _mk_card("Single Test", "Instant", "Choose one —\n• Counter target red spell.")

    program = compile_card_oracle(card)

    assert program.modes == ()


def test_bullets_belong_to_the_head_above_them_not_to_the_card():
    """The mode list is grouped with its own head. The version this replaced
    partitioned the card's whole text at the first "•", so a bullet list
    anywhere on the card became the modes of a "choose one" anywhere else."""
    card = _mk_card(
        "Detached Test",
        "Instant",
        "Choose one —\n"
        "• Counter target red spell.\n"
        "• Destroy target red permanent.\n"
        "Target player gains 3 life.\n"
        "• Draw a card.",
    )

    program = compile_card_oracle(card)

    assert [mode.label for mode in program.modes] == [
        "Counter target red spell", "Destroy target red permanent"
    ]


def test_a_modal_triggered_ability_never_becomes_a_cast_time_mode():
    """CR 700.2b: a triggered ability's modes are chosen when the ability goes
    on the stack, not when the card is cast. The head parses as a triggered
    ability, so nothing here claims it — where the whole-text substring test
    saw "choose one" plus bullets and offered them at cast time."""
    card = _mk_card(
        "Trigger Modal Test",
        "Enchantment",
        "When this enchantment enters, choose one —\n"
        "• You gain 4 life.\n"
        "• Draw a card.",
    )

    assert compile_card_oracle(card).modes == ()


def test_a_modal_activated_ability_never_becomes_a_cast_time_mode():
    """Pyramids' bullets are alternatives of an *ability*, expanded into one
    ability line each before any of this runs. Letting one into `modes` would
    offer it as a mode when the artifact was cast."""
    card = _mk_card(
        "Pyramid Test",
        "Artifact",
        "{2}: Choose one —\n• Destroy target artifact.\n• Destroy target enchantment.",
    )

    program = compile_card_oracle(card)

    assert program.modes == ()
    assert len(program.activated_abilities) == 2


def test_a_modal_activated_head_is_recognised_by_shape_not_by_its_cost():
    """The regex this replaced admitted a run of mana symbols and nothing else,
    so a modal ability with any other cost would have been left unexpanded — a
    head line nothing reads plus two orphan bullets. The grammar reads the whole
    cost clause, so the shape decides."""
    card = _mk_card(
        "Sac Modal Test",
        "Artifact",
        "Sacrifice this artifact: Choose one —\n"
        "• Destroy target artifact.\n"
        "• Destroy target enchantment.",
    )

    program = compile_card_oracle(card)

    assert [a.instruction.kind for a in program.activated_abilities] == [
        "destroy_target_permanent", "destroy_target_permanent"
    ]


def test_an_activated_head_the_engine_cannot_carry_out_is_not_expanded():
    """Expanding "{2}: Choose two —" into one ability per bullet would let the
    player activate each mode separately — a strictly more permissive card than
    the one printed. The lowering's refusal has to reach the expansion, and it
    does because the expansion asks the grammar rather than a second regex."""
    card = _mk_card(
        "Two Modes Test",
        "Artifact",
        "{2}: Choose two —\n• Destroy target artifact.\n• Destroy target enchantment.",
    )

    program = compile_card_oracle(card)

    # The head stays one line, so it stays one ability — an unsupported one,
    # which is the loud failure. The refusal names that whole unexpanded head:
    # two bullets' worth of abilities here would be the permissive card, and a
    # reason naming a single bullet would mean the head *had* been split.
    assert not program.supported
    assert program.reason.endswith("{2}: Choose two —"), program.reason
    assert not program.activated_abilities
