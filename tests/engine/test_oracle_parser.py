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


def test_a_mode_nothing_reads_is_reported_unsupported_on_its_own():
    """A card with one readable mode and one unreadable one still resolves the
    readable one — support is per mode, not per card."""
    card = _mk_card(
        "Half Test",
        "Instant",
        "Choose one —\n• Target player gains 3 life.\n• Ponder the infinite.",
    )

    program = compile_card_oracle(card)

    assert [mode.supported for mode in program.modes] == [True, False]
    assert program.modes[1].instruction is None


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
