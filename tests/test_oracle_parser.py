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


