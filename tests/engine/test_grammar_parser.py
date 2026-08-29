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
        recipients=(ast.TargetSpec("any_target", targeted=True),),
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
        subject=ast.TargetSpec("target", ast.ObjectFilter(card_types=("creature",)), targeted=True),
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
        subject=ast.TargetSpec("target", ast.ObjectFilter(card_types=("creature",)), targeted=True),
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
    """A lord's anthem is a continuous effect, not a one-shot pump. (An Aura's
    "Enchanted creature gets +0/+2" used to be the example here; it is now
    claimed as a RegistryLine, because layer 7c already derives it from the
    attached Aura — see test_grammar_lowering.)"""
    node = parse_line("Other Merfolk get +1/+1.")
    assert isinstance(node, ast.StaticAbilityNode)


# ---------------------------------------------------------------------------
# Modal heads (CR 700.2)
# ---------------------------------------------------------------------------
#
# The head is a *statement*, so the three places it is printed all read it
# through line shapes that already existed. These assert the node reached each
# of them with the prefix intact — a head parsed with its cost or its trigger
# dropped would be the silent-rider bug, wearing a passing test.


def test_a_bare_modal_head_is_a_statement_carrying_the_count():
    assert _statement("Choose one —") == ast.ModalNode(1)


def test_a_modal_head_keeps_the_activation_cost_it_sits_behind():
    node = parse_line("{2}: Choose one —")
    assert isinstance(node, ast.ActivatedAbilityNode)
    assert node.costs == (ast.ManaCost((("generic", 2),)),)
    assert node.statement == ast.ModalNode(1)


def test_a_modal_head_keeps_the_trigger_it_sits_behind():
    node = parse_line("When this creature enters, choose one —")
    assert isinstance(node, ast.TriggeredAbilityNode)
    assert node.event.kind == "enters_battlefield"
    assert node.statement == ast.ModalNode(1)


def test_the_mode_count_is_read_rather_than_assumed():
    """"Choose one or more" contains "choose one". The substring test this
    production replaced matched it and built a one-mode spell out of Sublime
    Epiphany; the count and the floor are separate fields here so that lowering
    has to look at both."""
    assert _statement("Choose one or more —") == ast.ModalNode(1, at_least=True)
    assert _statement("Choose two —") == ast.ModalNode(2)


def test_a_head_the_engine_cannot_carry_out_is_read_then_refused():
    """Parsed in full and refused at *lowering*, which is where "the engine has
    no way to do this" belongs — the alternative is a card that compiles
    cleanly and picks one mode where the text says several.

    "Choose one **or more**" was the example until the stack learned to carry a
    list of chosen modes; it is read now. An exact count above one still is not,
    and for the reason the refusal was always about: nothing in the pool prints
    it, so the bound would ship unexercised, and a wrong bound is a spell
    performing a mode its controller never chose.
    """
    result = compile_line("Choose two —")
    assert result.parsed
    assert not result.lowered
    assert "has no representation" in result.lowering_error


def test_a_head_choosing_one_or_more_is_carried():
    """The counterpart: parsed, lowered, and marked as the multi-mode head it
    is. Paired with the refusal above so the difference between the two counts
    is what the pair reads, not the presence of a head."""
    result = compile_line("Choose one or more —")
    assert result.parsed and result.lowered
    assert result.node.statement.at_least is True


@pytest.mark.parametrize(
    "line",
    [
        # Necromentia. Opens with the same two tokens as a modal head, and is a
        # different effect entirely — so the head production must decline
        # quietly and leave this line's own failure reason alone.
        "Choose a card name other than a basic land card name.",
        # A head is the whole clause; the modes are the lines below it. Anything
        # trailing means this is not that sentence.
        "Choose one — and draw a card.",
    ],
)
def test_other_choose_sentences_are_not_claimed_as_modal_heads(line: str):
    with pytest.raises(GrammarError):
        parse_line(line)


@pytest.mark.parametrize(
    "line",
    ["Draw a card, then choose one —", "Draw a card. Choose one —"],
)
def test_a_modal_head_buried_in_a_sequence_refuses(line: str):
    """A head lowers to no instructions because the *compiler* picks the modes
    up from the bullet lines beneath the head **line**. Inside a sequence it is
    not that line, so lowering it to nothing would be a spell that performs
    everything except its modes — the dropped-rider bug with the modes as the
    rider."""
    result = compile_line(line)
    assert result.parsed
    assert result.lowering_error == "a modal head is a whole clause, not a step inside one"


def test_an_ability_word_is_dropped_before_anything_reads_the_line():
    """CR 207.2c: an ability word is italic flavour with **no rules meaning**,
    so dropping it is the rule rather than a guess about the card.

    Rejecting every em dash on sight once put "Battalion — Whenever …" in the
    modal backlog, which pointed the work at the wrong production entirely; then
    it failed honestly on the trigger it could not read. Now it reads both."""
    result = compile_line(
        "Battalion — Whenever this creature and at least two other creatures "
        "attack, put a +1/+1 counter on this creature."
    )
    assert result.lowered, result.parse_error or result.lowering_error
    assert [i.kind for i in result.instructions] == ["add_counter_to_self"]


def test_a_dash_that_is_not_an_ability_word_is_left_alone():
    """The control. The strip is keyed on the printed vocabulary (CR 207.2c),
    not on the punctuation — a line that merely contains an em dash keeps
    whatever it says in front of one."""
    result = compile_line("Wumpus — Whenever this creature attacks, draw a card.")

    assert not result.parsed


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
    on the raw ability text in mixins/stack/activation.py."""
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

    # The card's own clause, because the restriction production now asks
    # `engine/activation_restrictions.py` whether the sentence is one the engine
    # enforces. The invented "five or fewer" clause this test used to carry is
    # not, and the line refuses with it — which is the point of the second half
    # below rather than a failure of the first.
    with_restriction = compile_line(
        "{T}: Draw a card. Activate only if you have exactly seven cards in hand.",
        card_name="Library of Alexandria",
    )
    without = compile_line("{T}: Draw a card.", card_name="Test")

    assert with_restriction.instructions == without.instructions

    # …and a restriction nothing enforces refuses the whole line rather than
    # being consumed verbatim. Vampire Bats' "Activate no more than twice each
    # turn" was consumed that way, against a table with no row for it, so the
    # card compiled supported with an uncapped ability.
    unreadable = compile_line(
        "{T}: Draw a card. Activate only if you have five or fewer cards in hand.",
        card_name="Test",
    )
    assert not unreadable.usable


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
        # mixins/stack/activation.py, and claiming it here would be a lie about
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


# ---------------------------------------------------------------------------
# The bare pronoun names the object the trigger's condition was about
# ---------------------------------------------------------------------------


def test_a_pronoun_under_a_self_subject_trigger_still_means_the_source():
    """"Whenever this creature is dealt damage, put a +1/+1 counter on it."

    The reading every line in the pool had before the rebinding existed, and
    the one it must keep: with nothing else named, "it" is the source."""
    statement = _statement(
        "Whenever this creature is dealt damage, put a +1/+1 counter on it.",
        card_name="Fungusaur",
    )
    assert statement.subject.filter.is_source
    assert not statement.subject.filter.is_enchanted


def test_a_pronoun_under_an_attached_subject_trigger_means_that_permanent():
    """"When enchanted land becomes tapped, destroy it." (Blight.) Read as the
    source, this destroys the Aura instead of the land."""
    statement = _statement(
        "When enchanted land becomes tapped, destroy it.", card_name="Blight",
    )
    assert statement.subject.filter.is_enchanted
    assert not statement.subject.filter.is_source


def test_the_card_naming_itself_is_not_rebound():
    """"Whenever enchanted land becomes tapped, Psychic Venom deals 2 damage to
    that land's controller."

    The same filter as a pronoun's default and a different reference: rewriting
    it would make the Aura's own effect come from the permanent it enchants.
    Pinned on the *node*, because the instruction this line lowers to carries
    no subject at all and so could not tell the two apart."""
    node = parse_line(
        "Whenever enchanted creature becomes tapped, Probe Aura deals 2 damage "
        "to any target.",
        card_name="Probe Aura",
    )
    assert isinstance(node, ast.TriggeredAbilityNode)
    assert node.statement.source.filter.is_source
    assert not node.statement.source.filter.is_enchanted


def test_the_rebinding_reaches_a_pronoun_inside_a_wrapper():
    """Structural, not a table of the productions that admit a pronoun: the
    walk has to reach one nested inside a `may`, a `sequence` or anything else
    the AST grows."""
    node = parse_line(
        "When enchanted creature becomes tapped, you may destroy it.",
        card_name="Probe Aura",
    )
    assert isinstance(node, ast.TriggeredAbilityNode)
    assert isinstance(node.statement, ast.May)
    assert node.statement.action.subject.filter.is_enchanted


# ---------------------------------------------------------------------------
# The filter draft mirrors the filter it becomes
# ---------------------------------------------------------------------------


def test_every_filter_draft_field_is_carried_into_the_object_filter():
    """``nouns._FilterDraft`` is a hand-written mirror of ``ast.ObjectFilter``,
    and the postmodifier parsers write onto the draft.

    A draft is an ordinary dataclass, so a field the parser sets that the draft
    does not declare is created on the instance and then **silently dropped** —
    the phrase parses, the restriction vanishes, and the effect reaches a
    strictly larger set than the card prints. That is this codebase's worst bug
    class and it is invisible: nothing raises, nothing fails, the card compiles.
    It happened while adding "target creature it's blocking" and was found only
    because the payload was printed by hand.

    Two halves, and both are needed. The draft may declare nothing the filter
    cannot hold, and — the half that actually bites — every field the parsers
    write must reach ``ObjectFilter``, which is checked by setting a marker on a
    fresh draft and reading it back off the built filter.
    """
    import dataclasses

    from engine.grammar import ast
    from engine.grammar.nouns import _FilterDraft, _build_object_filter

    draft_fields = {f.name for f in dataclasses.fields(_FilterDraft)}
    filter_fields = {f.name for f in dataclasses.fields(ast.ObjectFilter)}
    # `saw_head` and the two `*_by` spellings are the draft's own bookkeeping —
    # named here so a new one is a deliberate decision rather than an omission.
    draft_only = draft_fields - filter_fields - {"saw_head", "owned_by"}
    assert not draft_only, (
        f"draft fields with nowhere to go in ObjectFilter: {sorted(draft_only)}"
    )

    carried = {
        name
        for name in draft_fields
        if getattr(_build_object_filter(_FilterDraft()), name, "?") != "?"
    }
    missing = sorted(
        name for name in draft_fields - {"saw_head", "owned_by"} if name not in carried
    )
    assert not missing, (
        "these draft fields are never copied into ObjectFilter, so a parser "
        f"setting one drops the restriction silently: {missing}"
    )
