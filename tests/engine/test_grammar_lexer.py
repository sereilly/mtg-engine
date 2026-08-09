"""Tokenizer tests for the oracle grammar.

The lexer's job is to *not lose information*. The older ``OracleLexer`` in
engine/oracle.py shreds "+1/+1" into five symbol tokens and keeps no source
offsets, which is why parse failures there could not say where they failed.
These tests pin the properties the grammar depends on.
"""

from __future__ import annotations

from engine.grammar.lexer import (
    MANA,
    NUMBER,
    PT,
    PUNCT,
    SELF,
    WORD,
    strip_reminder_text,
    tokenize,
)


def _kinds(line: str, **kwargs) -> list[tuple[str, str]]:
    return [(token.kind, token.text) for token in tokenize(line, **kwargs).tokens]


def test_power_toughness_is_one_token():
    assert ("pt", "+1/+1") in _kinds("Put a +1/+1 counter on it.")
    assert ("pt", "+3/+3") in _kinds("Target creature gets +3/+3 until end of turn.")


def test_negative_and_variable_power_toughness():
    assert ("pt", "-2/-2") in _kinds("Target creature gets -2/-2 until end of turn.")
    assert ("pt", "+x/+0") in _kinds("Target creature gets +X/+0 until end of turn.")


def test_base_pt_without_signs_is_one_token():
    assert ("pt", "0/2") in _kinds("has base power and toughness 0/2 until end of turn")


def test_mana_symbols_are_upper_cased_single_tokens():
    kinds = _kinds("{2}, {T}: Draw a card.")
    assert (MANA, "{2}") in kinds
    assert (MANA, "{T}") in kinds


def test_numbers_and_words_separate():
    kinds = _kinds("deals 3 damage")
    assert kinds == [(WORD, "deals"), (NUMBER, "3"), (WORD, "damage")]


def test_possessive_splits_so_every_token_is_accounted_for():
    # "land's controller" must not become an opaque word — the noun parser
    # matches the possessive explicitly, and full-token consumption means it
    # cannot be silently skipped.
    kinds = _kinds("that land's controller")
    assert kinds == [(WORD, "that"), (WORD, "land"), (WORD, "'s"), (WORD, "controller")]


def test_contraction_stays_one_word():
    assert (WORD, "can't") in _kinds("it can't be regenerated this turn")


def test_reminder_text_is_stripped_but_recorded():
    text = "Flying (This creature can't be blocked except by creatures with flying.)"
    stripped, reminders = strip_reminder_text(text)
    assert "blocked except" not in stripped
    assert len(reminders) == 1
    result = tokenize(text)
    assert [t.text for t in result.tokens] == ["flying"]
    assert result.reminder_text == reminders


def test_card_name_becomes_a_self_token():
    kinds = _kinds("Lightning Bolt deals 3 damage to any target.", card_name="Lightning Bolt")
    assert kinds[0] == (SELF, "lightning bolt")
    assert kinds[1] == (WORD, "deals")


def test_card_name_without_match_leaves_words_alone():
    kinds = _kinds("Lightning Bolt deals 3 damage.", card_name="Shivan Dragon")
    assert kinds[0] == (WORD, "lightning")


def test_card_name_only_matches_whole_words():
    # A card named "Fire" must not swallow the first four letters of
    # "Firebreathing" — that would emit a SELF token and silently drop the rest
    # of the word.
    kinds = _kinds("Firebreathing costs {R}.", card_name="Fire")
    assert kinds[0] == (WORD, "firebreathing")
    assert not any(kind == SELF for kind, _ in kinds)


def test_repeated_self_reference_is_tokenized_each_time():
    kinds = _kinds(
        "Fireball deals X damage. Fireball is exiled.", card_name="Fireball"
    )
    assert [k for k, _ in kinds].count(SELF) == 2


def test_tokens_carry_source_spans():
    tokens = tokenize("deals 3 damage").tokens
    assert [(t.start, t.end) for t in tokens] == [(0, 5), (6, 7), (8, 14)]


def test_punctuation_is_preserved():
    kinds = _kinds("Draw a card. Each player discards a card.")
    assert kinds.count((PUNCT, ".")) == 2
