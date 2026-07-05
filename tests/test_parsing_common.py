"""Unit tests for the shared parsing helpers in engine/parsing/common.py."""

from __future__ import annotations

from engine.oracle_types import _parse_number_token, parse_number_token
from engine.parsing.common import (
    TargetFilter,
    cant_be_regenerated,
    find_color_word,
    find_excluded_colors,
    find_excluded_types,
    find_padded_color_word,
    parse_duration,
    parse_target_filter,
)


# --- number words -----------------------------------------------------------

def test_parse_number_token_digits_and_words():
    assert parse_number_token("3") == 3
    assert parse_number_token("seven") == 7
    assert parse_number_token("ten") == 10


def test_parse_number_token_unknown_is_none():
    assert parse_number_token("umpteen") is None


def test_legacy_parse_number_token_extended_past_seven():
    # Previously "eight"/"nine"/"ten" silently parsed to 0.
    assert _parse_number_token("eight") == 8
    assert _parse_number_token("umpteen") == 0


# --- color helpers ----------------------------------------------------------

def test_find_color_word_with_template():
    assert find_color_word("counter target blue spell", "counter target {} spell") == "U"
    assert find_color_word("counter target spell", "counter target {} spell") is None


def test_find_padded_color_word_ignores_non_prefix():
    assert find_padded_color_word("destroy target black creature") == "B"
    # "nonblack" must not match "black".
    assert find_padded_color_word("destroy target nonblack creature") is None


def test_find_excluded_colors_and_types():
    assert find_excluded_colors("destroy target nonblack creature") == ["B"]
    assert find_excluded_types("destroy target nonartifact, nonblack creature") == ["artifact"]


# --- misc helpers -----------------------------------------------------------

def test_cant_be_regenerated_both_wordings():
    assert cant_be_regenerated("destroy all creatures. they can't be regenerated")
    assert cant_be_regenerated("it cannot be regenerated")
    assert not cant_be_regenerated("destroy all creatures")


def test_parse_duration():
    assert parse_duration("target creature gets +3/+3 until end of turn") == "until_end_of_turn"
    assert parse_duration("prevent the next 2 damage this turn") == "until_end_of_turn"
    assert parse_duration("target creature gains flying") is None


# --- target noun-phrase parsing ---------------------------------------------

def _payload(text: str) -> dict:
    clause = text.split("destroy target", 1)[1].split(".")[0]
    return parse_target_filter(clause, text).to_payload()


def test_target_filter_plain_creature():
    assert _payload("destroy target creature") == {"type_filter": "creature"}


def test_target_filter_tapped_creature():
    assert _payload("destroy target tapped creature") == {
        "type_filter": "creature",
        "tapped_only": True,
    }


def test_target_filter_wall_subtype():
    assert _payload("destroy target wall") == {
        "type_filter": "creature",
        "subtype_filter": "wall",
    }


def test_target_filter_artifact_or_enchantment():
    assert _payload("destroy target artifact or enchantment") == {
        "type_filter": "artifact_or_enchantment",
    }


def test_target_filter_color_and_exclusions():
    assert _payload("destroy target black creature") == {
        "type_filter": "creature",
        "color_filter": "B",
    }
    assert _payload("destroy target nonartifact, nonblack creature") == {
        "type_filter": "creature",
        "exclude_colors": ["B"],
        "exclude_types": ["artifact"],
    }


def test_target_filter_land():
    assert _payload("destroy target land") == {"type_filter": "land"}


def test_target_filter_no_noun_is_unfiltered():
    assert _payload("destroy target permanent") == {}


def test_target_filter_dataclass_defaults():
    assert TargetFilter().to_payload() == {}


# --- parse-rule registry invariants ------------------------------------------

def test_parse_rules_strictly_ordered_and_unique():
    from engine.parsing.base import iter_rules

    orders = [r.order for r in iter_rules()]
    assert orders == sorted(orders)
    assert len(orders) == len(set(orders)), "duplicate parse-rule orders"
