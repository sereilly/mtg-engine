"""AST tests for the oracle grammar.

Two kinds of test here:

* **goldens** — real card lines produce the exact AST expected, so a refactor
  that changes meaning shows up as a diff rather than as a mystery bug;
* **the full-consumption invariant** — the grammar must account for every token
  of a line or refuse it. This is the structural fix for the bug class the
  parse-coverage deletion probe finds empirically: the legacy rules matched a
  substring and silently discarded the rest of the sentence, so a card could be
  "supported" while half its text did nothing.
"""

from __future__ import annotations

import pytest

from engine.grammar import ast, compile_line
from engine.grammar.errors import GrammarError
from engine.grammar.lexer import tokenize
from engine.grammar.parser import parse_line


def _statement(line: str, card_name: str | None = None) -> ast.Statement:
    node = parse_line(line, card_name=card_name)
    if isinstance(node, ast.SpellEffectLine):
        return node.statement
    if isinstance(node, (ast.TriggeredAbilityNode, ast.ActivatedAbilityNode)):
        return node.statement
    if isinstance(node, ast.StaticAbilityNode):
        return node.effect
    raise AssertionError(f"unexpected node {type(node).__name__}")


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def test_simple_damage_to_any_target():
    statement = _statement("Lightning Bolt deals 3 damage to any target.", "Lightning Bolt")
    assert statement == ast.DealDamage(
        source=ast.TargetSpec("this", ast.ObjectFilter(is_source=True)),
        amount=ast.Fixed(3),
        recipients=(ast.TargetSpec("any_target"),),
    )


def test_variable_damage():
    statement = _statement("Fireball deals X damage to any target.", "Fireball")
    assert statement.amount == ast.Var("x")


def test_sweep_keeps_the_creature_restriction():
    # The legacy parse_target_filter knew four creature subtypes and discarded
    # every other restriction word, so "without flying" would have vanished.
    statement = _statement(
        "Earthquake deals X damage to each creature without flying and each player.",
        "Earthquake",
    )
    creature, player = statement.recipients
    assert creature.quantifier == "each"
    assert creature.filter.card_types == ("creature",)
    assert creature.filter.without_keywords == ("flying",)
    assert player == ast.PlayerRef("each_player")


def test_two_damage_clauses_become_a_conjunction_not_a_new_kind():
    statement = _statement(
        "Psionic Blast deals 4 damage to any target and 2 damage to you.", "Psionic Blast"
    )
    assert isinstance(statement, ast.Conjunction)
    first, second = statement.effects
    assert first.amount == ast.Fixed(4)
    assert second.amount == ast.Fixed(2)
    assert second.recipients == (ast.PlayerRef("you"),)


def test_opponent_choice_clause_records_the_chooser():
    statement = _statement(
        "{T}: This creature deals 1 damage to any target and 1 damage to any target "
        "of an opponent's choice."
    )
    _, second = statement.effects
    assert second.chooser == ast.PlayerRef("target_opponent")


def test_disintegrate_riders_attach_to_the_damage():
    statement = _statement(
        "Disintegrate deals X damage to any target. If it's a creature, it can't be "
        "regenerated this turn, and if it would die this turn, exile it instead.",
        "Disintegrate",
    )
    assert statement.riders == ast.DamageRiders(no_regen=True, exile_if_dies=True)


def test_divided_damage_is_recorded_as_a_rider():
    statement = _statement(
        "Fireball deals X damage divided evenly, rounded down, among any number of targets.",
        "Fireball",
    )
    assert statement.riders.divided and statement.riders.divided_evenly


# ---------------------------------------------------------------------------
# Pump / P&T
# ---------------------------------------------------------------------------


def test_pump_with_duration():
    statement = _statement("Target creature gets +3/+3 until end of turn.")
    assert statement == ast.Pump(
        subject=ast.TargetSpec("target", ast.ObjectFilter(card_types=("creature",))),
        power=ast.Fixed(3),
        toughness=ast.Fixed(3),
        duration=ast.Duration("until_end_of_turn"),
    )


def test_negative_pump_records_the_sign():
    statement = _statement("Target creature gets -2/-2 until end of turn.")
    assert statement.power_negative and statement.toughness_negative


def test_blocking_restriction_is_kept():
    statement = _statement("Target blocking creature gets +7/+7 until end of turn.")
    assert statement.subject.filter.blocking is True


def test_bare_plural_subject_is_an_implicit_all():
    statement = _statement("White creatures get +1/+1.")
    assert statement.subject.quantifier == "all"
    assert statement.subject.filter.colors == ("W",)


def test_keyword_grant_with_duration():
    statement = _statement("Target creature gains flying until end of turn.")
    assert statement == ast.GainKeyword(
        subject=ast.TargetSpec("target", ast.ObjectFilter(card_types=("creature",))),
        keywords=("flying",),
        duration=ast.Duration("until_end_of_turn"),
    )


def test_set_base_power_only_keeps_the_flying_restriction():
    statement = _statement("{T}: Target creature with flying has base power 0 until end of turn.")
    assert statement.toughness is None
    assert statement.subject.filter.with_keywords == ("flying",)


def test_other_than_this_creature_is_recorded():
    statement = _statement(
        "{T}: Target creature other than this creature has base power and toughness "
        "0/2 until end of turn."
    )
    assert statement.subject.filter.other_than_source is True


# ---------------------------------------------------------------------------
# Line classification
# ---------------------------------------------------------------------------


def test_keyword_line():
    assert parse_line("Flying") == ast.KeywordLine((ast.KeywordInstance("flying"),))


def test_multi_keyword_line():
    node = parse_line("Flying, trample")
    assert [k.name for k in node.keywords] == ["flying", "trample"]


def test_protection_keeps_its_argument():
    node = parse_line("Protection from red")
    assert node.keywords[0] == ast.KeywordInstance("protection", "red")


def test_activated_ability_costs():
    node = parse_line("{3}, {T}: This artifact deals 1 damage to any target.")
    assert isinstance(node, ast.ActivatedAbilityNode)
    assert ast.TapSelf() in node.costs
    assert ast.ManaCost((("generic", 3),)) in node.costs


def test_triggered_ability_event_kind_matches_the_legacy_vocabulary():
    node = parse_line("At the beginning of your upkeep, this creature deals 1 damage to you.")
    assert isinstance(node, ast.TriggeredAbilityNode)
    # Kind strings deliberately match engine/oracle.py's tables so the existing
    # condition_kinds= dispatch sites keep working during migration.
    assert node.event.kind == "upkeep_self"


def test_static_line_is_classified_as_static_not_a_spell_effect():
    node = parse_line("Enchanted creature gets +0/+2.")
    assert isinstance(node, ast.StaticAbilityNode)


# ---------------------------------------------------------------------------
# The full-consumption invariant
# ---------------------------------------------------------------------------


def test_trailing_text_is_refused_not_ignored():
    with pytest.raises(GrammarError):
        parse_line("Target creature gets +3/+3 until end of turn and wins the game.")


def test_unknown_restriction_word_is_refused():
    # "with shadow" is a real restriction the engine has no vocabulary for;
    # dropping it would target the wrong creatures, so the line must fail.
    with pytest.raises(GrammarError):
        parse_line("Target creature with wumpus gets +1/+1 until end of turn.")


@pytest.mark.parametrize(
    "line,card_name",
    [
        ("Lightning Bolt deals 3 damage to any target.", "Lightning Bolt"),
        ("Target creature gets +3/+3 until end of turn.", None),
        ("Target blocking creature gets +7/+7 until end of turn.", None),
        ("Earthquake deals X damage to each creature without flying and each player.", "Earthquake"),
        ("Target creature gains flying until end of turn.", None),
        ("{T}: Target creature with flying has base power 0 until end of turn.", None),
    ],
)
def test_deleting_any_word_changes_the_ast(line: str, card_name: str | None):
    """Delete one word at a time and re-parse: the AST must change or the parse
    must fail. An identical AST would mean the deleted word was ignored, which
    is exactly the dropped-rider bug the parse-coverage probe hunts for."""
    baseline = parse_line(line, card_name=card_name)
    words = line.split()
    for index in range(len(words)):
        probe = " ".join(words[:index] + words[index + 1:])
        try:
            candidate = parse_line(probe, card_name=card_name)
        except GrammarError:
            continue
        assert candidate != baseline, (
            f"deleting {words[index]!r} left the AST unchanged — the word is being ignored"
        )


def test_every_token_is_consumed_for_accepted_lines():
    line = "Disintegrate deals X damage to any target."
    tokens = tokenize(line, card_name="Disintegrate").tokens
    # A successful parse means the stream reached the end; assert the line has
    # tokens at all so an empty-token false positive cannot pass this test.
    assert tokens
    assert compile_line(line, card_name="Disintegrate").parsed


# ---------------------------------------------------------------------------
# Activation restrictions
# ---------------------------------------------------------------------------


def test_trailing_activation_restriction_is_consumed_not_dropped():
    """"Activate only during your upkeep." belongs to the ability, not its
    effect. The grammar must account for the tokens — a line it cannot fully
    consume is refused outright — while enforcement stays where it already is,
    on the raw ability text in mixins/stack_casting.py."""
    from engine.grammar import compile_line

    result = compile_line(
        "{R}{R}{R}: Put a +1/+1 counter on this creature. Activate only during your upkeep.",
        card_name="Rock Hydra",
    )

    assert result.usable
    assert [(i.kind, i.payload) for i in result.instructions] == [
        ("add_counter_to_self", {"power": 1, "toughness": 1})
    ]


def test_activation_restriction_does_not_leak_into_the_effect():
    """The restriction must not become a step of the effect — an ability that
    ran its restriction as an instruction would do something extra on
    resolution."""
    from engine.grammar import compile_line

    with_restriction = compile_line(
        "{T}: Draw a card. Activate only if you have five or fewer cards in hand.",
        card_name="Library of Alexandria",
    )
    without = compile_line("{T}: Draw a card.", card_name="Test")

    assert with_restriction.instructions == without.instructions


# ---------------------------------------------------------------------------
# Registry lines — behaviour that lives outside the instruction IR
# ---------------------------------------------------------------------------


REGISTRY_LINES = [
    # engine/cast_restrictions.py, looped by check_cast_timing().
    ("Cast this spell only during your declare attackers step.", "cast_restrictions"),
    ("Cast this spell only before the combat damage step.", "cast_restrictions"),
    # engine/untap_restrictions.py, read by phases/untap_step.py.
    ("Players skip their untap steps.", "untap_restrictions"),
    (
        "As long as this artifact is untapped, players can't untap more than one "
        "land during their untap steps.",
        "untap_restrictions",
    ),
    ("Blue creatures don't untap during their controllers' untap steps.", "untap_restrictions"),
    # engine/draw_step_modifiers.py, read by phases/draw_step.py.
    (
        "At the beginning of each player's draw step, if this artifact is untapped, "
        "that player draws an additional card.",
        "draw_step_modifiers",
    ),
    # engine/cost_modifiers.py, applied by spell_cost_tax / ability_cost_tax.
    ("White spells cost {3} more to cast.", "cost_modifiers"),
    ("Activated abilities of white enchantments cost {3} more to activate.", "cost_modifiers"),
    # engine/replacements.py CR 614 interceptors.
    ("If you would gain life, draw that many cards instead.", "replacements"),
    (
        "Damage that would reduce your life total to less than 1 reduces it to 1 instead.",
        "replacements",
    ),
    (
        "If an effect causes you to discard a card, discard it, but you may put it "
        "on top of your library instead of into your graveyard.",
        "replacements",
    ),
]


@pytest.mark.parametrize("line,registry", REGISTRY_LINES)
def test_registry_line_is_claimed_by_the_module_that_implements_it(line: str, registry: str):
    assert parse_line(line) == ast.RegistryLine(registry, line)


@pytest.mark.parametrize("line,registry", REGISTRY_LINES)
def test_registry_line_keeps_its_text_verbatim(line: str, registry: str):
    """The replacement interceptors self-select by looking for their phrase in
    ``permanent.card.oracle_text``. Normalizing the text on the node would be a
    way to quietly unhook Lich, Library of Leng and Ali from Cairo, so the node
    is pinned to the line exactly as printed."""
    node = parse_line(line)
    assert node.text == line


@pytest.mark.parametrize("line,registry", REGISTRY_LINES)
def test_registry_line_produces_no_instructions_and_never_executes(line: str, registry: str):
    """Parse credit only, by design. A registry line has no instructions, so it
    has no categories, so ``usable`` is False and the legacy compiler path is
    left to handle the card exactly as before."""
    result = compile_line(line)
    assert result.parsed
    assert result.instructions == ()
    assert not result.categories
    assert not result.usable


@pytest.mark.parametrize(
    "line",
    [
        # Not a template cost_modifiers.py knows — Fireball's surcharge lives in
        # mixins/stack_casting.py, and claiming it here would be a lie about
        # which code runs it.
        "This spell costs {1} more to cast for each target beyond the first.",
        # A timing restriction no CAST_RESTRICTIONS entry carries.
        "Cast this spell only during your untap step.",
        # An untap wording UNTAP_RESTRICTION_PATTERNS does not match.
        "Green creatures don't untap during their upkeeps.",
        # A restriction plus a real effect: the effect half is unaccounted for,
        # so the line must stay a loud failure rather than be half-claimed.
        "Destroy target creature. Cast this spell only before the combat damage step.",
    ],
)
def test_unimplemented_lookalikes_are_still_refused(line: str):
    """The production must not generalize from the shapes it admits. Each line
    here resembles a claimed one but has no registry behind it, so parsing it
    would report understanding the engine does not have."""
    with pytest.raises(GrammarError):
        parse_line(line)


def test_registry_claim_matches_the_registry_phrase_exactly():
    """The claim is delegated, not copied: a phrase table inside the grammar
    could drift from the interceptor that reads it, and a drifted copy would
    claim a line nothing implements."""
    from engine.grammar.registries import registry_for_line
    from engine.replacements import DAMAGE_LIFE_FLOOR_TEXT, LIFE_GAIN_TO_DRAW_TEXT

    assert registry_for_line(LIFE_GAIN_TO_DRAW_TEXT + ".") == "replacements"
    assert registry_for_line(DAMAGE_LIFE_FLOOR_TEXT + ".") == "replacements"
    # Truncate the phrase and the claim disappears with it.
    assert registry_for_line(LIFE_GAIN_TO_DRAW_TEXT[:-8] + ".") is None
