"""Lowering tests: AST → OracleInstruction payloads.

Payload keys are a compatibility surface — 121 registered effect handlers read
them by name. These goldens pin the exact payloads so a grammar change cannot
quietly alter what a handler receives.

They compare the *behavioural* payload: the keys a handler actually reads. The
grammar additionally records what a line targets (``targets``), which no
handler consumes — it exists so the engine can answer targeting from the
compiled program instead of re-parsing oracle text. Folding that into every
golden would bury the compatibility contract these tests exist to state, so it
has its own section at the bottom.
"""

from __future__ import annotations

import pytest

from engine.grammar import GRAMMAR_CATEGORIES, behavioural_payload, compile_line
from engine.grammar.lower import INSTRUCTION_CATEGORIES
from engine.oracle_types import OracleInstruction


_SCAVENGING_GHOUL = (
    "At the beginning of each end step, put a corpse counter on this creature "
    "for each creature that died this turn."
)

_KHABAL_GHOUL = (
    "At the beginning of each end step, put a +1/+1 counter on this creature "
    "for each creature that died this turn."
)



def _instructions(line: str, card_name: str | None = None):
    result = compile_line(line, card_name=card_name)
    assert result.lowered, f"expected a lowering, got {result.failure_reason}"
    return [(i.kind, behavioural_payload(i.payload)) for i in result.instructions]


def _full_payloads(line: str, card_name: str | None = None):
    """Payloads including the grammar-only description keys."""
    result = compile_line(line, card_name=card_name)
    assert result.lowered, f"expected a lowering, got {result.failure_reason}"
    return [(i.kind, i.payload) for i in result.instructions]


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def test_fixed_damage():
    assert _instructions("Lightning Bolt deals 3 damage to any target.", "Lightning Bolt") == [
        ("deal_damage", {"amount": 3})
    ]


def test_variable_damage_lowers_x_as_a_string_like_the_legacy_rules():
    assert _instructions("Disintegrate deals X damage to any target.", "Disintegrate") == [
        ("deal_damage", {"amount": "x"})
    ]


def test_disintegrate_riders_reach_the_payload():
    assert _instructions(
        "Disintegrate deals X damage to any target. If it's a creature, it can't be "
        "regenerated this turn, and if it would die this turn, exile it instead.",
        "Disintegrate",
    ) == [("deal_damage", {"amount": "x", "no_regen": True, "exile_if_dies": True})]


def test_earthquake_and_hurricane_keep_their_dedicated_sweep_handlers():
    assert _instructions(
        "Earthquake deals X damage to each creature without flying and each player.",
        "Earthquake",
    ) == [("earthquake_damage", {"amount": "x"})]
    assert _instructions(
        "Hurricane deals X damage to each creature with flying and each player.",
        "Hurricane",
    ) == [("hurricane_damage", {"amount": "x"})]


def test_self_damage_conjunction_decomposes_into_two_instructions():
    """The legacy compiler minted `deal_damage_and_self_damage` for this shape.
    Composition removes the need for a fused kind."""
    assert _instructions(
        "Psionic Blast deals 4 damage to any target and 2 damage to you.", "Psionic Blast"
    ) == [
        ("deal_damage", {"amount": 4}),
        ("deal_damage", {"amount": 2, "recipient": "caster"}),
    ]


def test_opponent_choice_keeps_its_prompt_handler():
    # The second target is chosen by a *different* player, which needs the
    # pending-prompt machinery rather than a second plain instruction.
    assert _instructions(
        "{T}: This creature deals 1 damage to any target and 1 damage to any target "
        "of an opponent's choice."
    ) == [("deal_damage_and_opponent_choice", {"amount": 1, "opponent_amount": 1})]


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------


def test_pump_target():
    assert _instructions("Target creature gets +3/+3 until end of turn.") == [
        ("pump_target_creature_until_eot", {"power": 3, "toughness": 3, "blocking_only": False})
    ]


def test_pump_blocking_only():
    assert _instructions("Target blocking creature gets +7/+7 until end of turn.") == [
        ("pump_target_creature_until_eot", {"power": 7, "toughness": 7, "blocking_only": True})
    ]


def test_pump_self_from_activated_ability():
    assert _instructions("{R}: This creature gets +1/+0 until end of turn.") == [
        ("pump_self", {"power": 1, "toughness": 0})
    ]


def test_pump_enchanted_creature():
    assert _instructions("{W}: Enchanted creature gets +1/+1 until end of turn.") == [
        ("pump_enchanted_creature", {"power": 1, "toughness": 1})
    ]


def test_a_durationless_anthem_lowers_to_the_continuous_consumer():
    """Crusade's "White creatures get +1/+1" is a continuous effect with no
    duration, so it is a static ability re-derived on every recompute
    (CR 611.3a) — not the one-shot spell buff that shares its wording."""
    result = compile_line("White creatures get +1/+1.")
    assert result.lowered
    assert [i.kind for i in result.instructions] == ["lord_buff"]
    assert result.instructions[0].payload == {"power": 1, "toughness": 1, "colors": ["W"]}


def test_an_anthem_qualifier_is_carried_rather_than_dropped():
    """The trap this lowering was held back by for a phase: the continuous
    consumer read the colour and the controller and nothing else, so Orcish
    Oriflamme lowered alongside Crusade would have buffed every creature its
    controller has, permanently, and Castle would have buffed tapped ones.

    ``engine/lord_buffs.py`` derives the qualifier and the consumer honours it,
    so the answer is no longer a refusal — but it is still the *filter* that
    decides, which is what the next test pins."""
    for line, card, qualifier in [
        ("Attacking creatures you control get +1/+0.", "Orcish Oriflamme", "attacking"),
        ("Untapped creatures you control get +0/+2.", "Castle", "untapped"),
    ]:
        result = compile_line(line, card_name=card)
        assert result.lowered, result.failure_reason
        payload = result.instructions[0].payload
        assert payload["while"] == [qualifier], line
        assert payload["controller"] == "you", line


def test_a_restriction_the_table_cannot_carry_is_refused_not_widened():
    """The safety property survives the lowering. The filter is rebuilt from
    what ``LordBuffFilter`` holds and compared for **equality** against the one
    the parser produced, so a restriction the table has no field for refuses
    instead of being silently dropped — and a field added to ``ObjectFilter``
    later is refused by default rather than ignored by a check that predates
    it."""
    result = compile_line("Creatures with flying get +1/+1.", card_name="Invented Anthem")

    assert result.parsed, result.failure_reason
    assert not result.lowered
    assert "engine/lord_buffs.py" in result.failure_reason


def test_a_subtype_union_refuses_rather_than_taking_the_first():
    """The round trip cannot catch this one — a union survives it intact — so it
    is refused on its own terms. The table's text parser reads one subtype, so a
    grammar-only union would be a payload no printed card produces and no test
    covers."""
    result = compile_line("Other Djinn or Efreet get +1/+1.", card_name="Invented Lord")

    assert result.parsed, result.failure_reason
    assert not result.lowered
    assert "union" in result.failure_reason


def test_attacking_creatures_buff_keeps_the_qualifier():
    # Army of Allah: the parse-coverage deletion probe originally caught this
    # qualifier being dropped by the legacy rule.
    assert _instructions("Attacking creatures get +2/+0 until end of turn.") == [
        ("buff_creatures_global", {"power": 2, "toughness": 0, "all": True, "attacking_only": True})
    ]


def test_set_base_pt_both():
    assert _instructions(
        "{T}: Target creature other than this creature has base power and toughness "
        "0/2 until end of turn."
    ) == [
        ("set_base_pt_target_until_eot", {"power": 0, "toughness": 2, "exclude_self": True})
    ]


def test_set_base_power_only_records_the_restriction():
    assert _instructions("{T}: Target creature with flying has base power 0 until end of turn.") == [
        (
            "set_base_pt_target_until_eot",
            {
                "power": 0, "toughness": None, "exclude_self": False,
                "attacking_only": False, "flying_only": True,
            },
        )
    ]


def test_keyword_grants():
    assert _instructions("Target creature gains flying until end of turn.") == [
        ("grant_target_flying_until_eot", {"duration": "end_of_turn"})
    ]
    assert _instructions("{R}: This creature gains flying until end of turn.") == [
        ("grant_self_flying_until_eot", {"duration": "end_of_turn"})
    ]


def test_a_keyword_grant_carries_the_duration_it_printed():
    """Every grant kind names end of turn, and for most of the pool that is
    what the card says — but the duration is what the sweep reads, so it has to
    be payload. It was a boolean at the channel, which made every other printed
    duration *become* end of turn."""
    assert _instructions(
        "{R}: This creature gains trample until end of combat."
    ) == [
        (
            "grant_self_keyword_until_eot",
            {"keywords": ("trample",), "duration": "end_of_combat"},
        )
    ]
    assert _instructions(
        "{R}: This creature gains trample until your next upkeep."
    ) == [
        (
            "grant_self_keyword_until_eot",
            {"keywords": ("trample",), "duration": "your_next_upkeep"},
        )
    ]


def test_a_keyword_grant_refuses_a_duration_no_sweep_ends():
    """"Until your next turn" has no sweep, so the line refuses rather than
    being granted until end of turn — which is what it silently did."""
    result = compile_line("{R}: This creature gains trample until your next turn.")
    assert not result.lowered
    assert "until_your_next_turn" in (result.lowering_error or "")


def test_counter_on_self():
    assert _instructions("Whenever this creature is dealt damage, put a +1/+1 counter on it.") == [
        ("add_counter_to_self", {"power": 1, "toughness": 1})
    ]


# ---------------------------------------------------------------------------
# Back-references
# ---------------------------------------------------------------------------


def test_gain_life_from_damage_dealt_in_the_same_effect():
    assert _instructions(
        "Drain Life deals X damage to any target. You gain life equal to the damage dealt.",
        "Drain Life",
    ) == [
        ("deal_damage", {"amount": "x"}),
        ("target_gains_life", {"amount_from": "damage_dealt", "recipient": "caster"}),
    ]


# ---------------------------------------------------------------------------
# Optional actions
# ---------------------------------------------------------------------------


def test_you_may_pay_carries_its_consequence_as_instructions():
    """The old ``optional_pay`` hook could only express a fixed vocabulary —
    gain N life, draw N cards, take N damage — so any card outside it needed a
    name-keyed entry. Here the consequence is an ordinary instruction
    sequence.

    Read as a trigger remainder, which is the only place a ``may`` is executable:
    the prompt outlives the resolution that armed it, and only a triggered
    ability's resolution path holds the queue open. A spell's whole effect
    reaches the same shape since round 32
    (``test_a_spell_whose_whole_effect_is_optional_lowers``)."""
    assert _instructions(
        "When this creature enters, you may pay {1}. If you do, you gain 1 life."
    ) == [
        (
            "may",
            {
                "actor": "you",
                "cost": {"generic": 1},
                "then": (
                    OracleInstruction(
                        "target_gains_life", "", {"amount": 1, "recipient": "caster"}
                    ),
                ),
            },
        )
    ]


def test_the_if_you_do_branch_is_not_a_separate_step():
    """Parsing "If you do, …" as its own sentence would make the consequence
    unconditional — the same class of mistake as dropping "you may"."""
    result = compile_line("You may pay {1}. If you do, you gain 1 life.")
    statement = result.node.statement
    assert statement.__class__.__name__ == "May"
    assert statement.cost is not None
    assert statement.then is not None


def test_colour_narrowed_cast_trigger_carries_the_colour():
    result = compile_line(
        "Whenever a player casts a blue spell, you may pay {1}. If you do, you gain 1 life.",
        card_name="Crystal Rod",
    )
    assert result.node.event.kind == "spell_cast"
    assert result.node.event.subject.colors == ("U",)


def test_optional_actions_are_switched_on():
    """Optional actions are authoritative: the six cards that used to be
    name-keyed for "you may pay {N}" now run off this lowering."""
    result = compile_line(
        "When this creature enters, you may pay {1}. If you do, you gain 1 life."
    )
    assert result.usable
    assert result.categories == frozenset({"optional"})


def test_a_free_optional_action_lowers_to_its_own_handler():
    """"You may draw a card" — no cost, so the offer is unconditional but the
    draw still is not."""
    assert _instructions("Whenever this creature attacks, you may draw a card.") == [
        ("may", {"actor": "you", "action": (
            OracleInstruction("draw_controller_cards", "", {"amount": 1}),
        )})
    ]


def test_a_spell_whose_whole_effect_is_optional_lowers():
    """This refused until round 32, and the refusal was right when it was
    written: the prompt rode ``pending_optional_pays``, which only a triggered
    ability's resolution path held open, so a spell — which leaves the stack the
    instant it resolves — queued its effect and never performed it.

    ``arm_pending_choice`` now stamps the resolving stack object and
    ``ChoiceSpec.holds_priority`` keeps it there until the last of its prompts
    is answered (CR 608.2, CR 117.3b), so a spell's ``may`` outlives its own
    resolution. Twiddle is the shipped card that changed, and it changed from
    acting to *asking*.
    """
    result = compile_line("You may tap or untap target creature.", card_name="Test")

    assert result.lowered
    assert result.instructions[0].kind == "may"
    assert [step.kind for step in result.instructions[0].payload["action"]] == [
        "tap_or_untap_target"
    ]


def test_an_offer_to_each_player_keeps_the_actor_it_was_printed_with():
    """"Each player may …" (Rebirth) is one decision *per player*, so the actor
    is carried as payload and ``handlers/control_flow.may`` arms one prompt for
    each named seat. Lowering it as "you may" would let the caster answer for
    everybody."""
    result = compile_line(
        "Each player may ante the top card of their library. "
        "If a player does, that player's life total becomes 20.",
        card_name="Rebirth",
    )
    assert result.lowered
    offer = result.instructions[0]
    assert offer.kind == "may"
    assert offer.payload["actor"] == "each_player"
    assert [step.kind for step in offer.payload["action"]] == ["ante_top_card"]
    assert offer.payload["action"][0].payload["players"] == "that_player"
    assert [step.kind for step in offer.payload["then"]] == ["set_life_total"]
    assert offer.payload["then"][0].payload == {
        "recipient": "that_player", "amount": 20,
    }


def test_if_a_player_does_needs_an_offer_made_to_more_than_one_seat():
    """The third-person rider is a spelling of "if you do" under a multi-seat
    offer. Over a "you may" there is nothing for "a player" to refer back to,
    and reading it as "you" would put the branch on the caster whoever actually
    took the action — so the line refuses instead."""
    result = compile_line(
        "You may ante the top card of your library. "
        "If a player does, that player's life total becomes 20.",
        card_name="Test",
    )
    assert not result.parsed


def test_you_draw_and_target_player_draws_use_different_handlers():
    """They are separate handlers with different drawers, not one handler with
    a flag — lowering "you may draw a card" to the targeted one drew for the
    wrong player."""
    assert _instructions("Draw a card.")[0][0] == "draw_controller_cards"
    assert _instructions("Target player draws 2 cards.")[0][0] == "draw_target_cards"


def test_a_damage_triggers_that_much_reads_the_events_own_number():
    """El-Hajjâj's "you gain that much life" reads the *trigger's* captured
    event, not this resolution's scratchpad — reading either for the other
    yields a silent zero.

    This was a refusal for as long as "deals damage" had no seam: the amount
    was recorded by whichever fire site the card happened to be announced from,
    under whichever key that site chose, so claiming the line would have
    retired a hook onto a handler reading the wrong name. One announcement, one
    key, and the words resolve.
    """
    result = compile_line(
        "Whenever this creature deals damage, you gain that much life."
    )
    assert result.lowered
    assert result.instructions[0].payload["amount_from_trigger"] == "amount"


def test_a_back_reference_still_refuses_under_a_trigger_that_records_no_number():
    """The rule the case above is an instance of, not an exception to: an event
    with no quantity leaves "that much" naming nothing, and a silent zero is
    what the refusal exists to prevent."""
    result = compile_line("Whenever this creature attacks, you gain that much life.")
    assert result.parsed
    assert not result.lowered
    assert "no producer" in result.failure_reason


def test_a_bare_that_much_names_nothing_until_lowering_resolves_it():
    """A bare "that much" is not evidence of damage. It used to parse as
    ``ThatMuch("damage_dealt")`` whatever the sentence said, so under a life-gain
    trigger the AST asserted a producer that is nowhere on the card; the words
    "equal to the damage dealt" are what actually name one."""
    from engine.grammar import parse_line
    from engine.grammar.ast import ThatMuch

    bare = parse_line("Target opponent loses that much life.")
    assert bare.statement.amount == ThatMuch(None)

    named = parse_line("This creature deals 2 damage to you. You gain that much life.")
    gain = named.statement.steps[1]
    assert gain.amount == ThatMuch(None), "still bare — the producer is a step, not a word"

    spelled = parse_line("You gain life equal to the damage dealt.")
    assert spelled.statement.amount == ThatMuch("damage_dealt")


def test_a_back_reference_reads_the_trigger_when_the_event_carries_a_number():
    """Vito. The two channels are different payload keys, because they are
    different places: ``amount_from`` is this resolution's scratchpad and
    ``amount_from_trigger`` is the firing event's captured context. Reading one
    for the other yields a silent zero."""
    from_trigger = _instructions(
        "Whenever you gain life, target opponent loses that much life."
    )
    assert from_trigger == [("target_loses_life", {"amount_from_trigger": "life_gained"})]

    within = _instructions(
        "This spell deals 3 damage to target creature. You gain that much life."
    )
    assert within[1] == ("target_gains_life", {"amount_from": "damage_dealt", "recipient": "caster"})


def test_the_team_keyword_grant_carries_how_wide_it_reaches():
    """"Creatures you control" and "permanents you control" are one grant of
    differing width, so the width is a payload key and not a second kind. It is
    emitted only for the wider reading, which keeps every payload written before
    it byte-identical."""
    assert _instructions("Creatures you control gain trample until end of turn.") == [
        (
            "grant_team_keyword_until_eot",
            {"keywords": ("trample",), "duration": "end_of_turn"},
        )
    ]
    assert _instructions(
        "Permanents you control gain hexproof and indestructible until end of turn."
    ) == [
        (
            "grant_team_keyword_until_eot",
            {
                "keywords": ("hexproof", "indestructible"),
                "every_permanent": True, "duration": "end_of_turn",
            },
        )
    ]


def test_the_team_keyword_grant_refuses_a_narrowing_it_cannot_honour():
    """The handler loops over the controller's board and tests nothing else, so
    a printed restriction it cannot apply has to refuse rather than be dropped
    into a wider grant."""
    result = compile_line(
        "Artifact creatures you control gain flying until end of turn."
    )
    assert result.parsed
    assert not result.lowered


def test_a_bare_back_reference_under_a_quantityless_trigger_is_refused():
    """The table is the gate: a trigger kind that carries no number refuses the
    back-reference rather than reading a zero out of an empty context."""
    result = compile_line(
        "Whenever this creature attacks, target opponent loses that much life."
    )
    assert result.parsed
    assert not result.lowered
    assert "no producer" in result.failure_reason


# ---------------------------------------------------------------------------
# Static effects wait on the layers engine
# ---------------------------------------------------------------------------


def test_an_auras_static_pt_is_claimed_by_the_code_that_derives_it():
    """This used to be refused as "needs the CR 613 layers engine". It isn't:
    since phase 6 the grant is derived from the attached Aura's own text at
    layer 7c on every recompute. There is nothing to lower — an instruction
    here would apply the bonus a second time — so the line is accounted for by
    ``auras.py`` and lowers to no instructions at all."""
    result = compile_line("Enchanted creature gets +0/+2.")
    assert result.parsed
    assert result.lowered
    assert result.instructions == ()
    assert result.node.registry == "auras"


# ---------------------------------------------------------------------------
# Gate bookkeeping
# ---------------------------------------------------------------------------


def test_every_lowered_kind_declares_a_category():
    """A kind missing from INSTRUCTION_CATEGORIES can never be gated on, so it
    would silently stay on the legacy path forever."""
    for kind, category in INSTRUCTION_CATEGORIES.items():
        assert category, f"{kind} has an empty category"


def test_enabled_categories_are_all_declared_somewhere():
    declared = set(INSTRUCTION_CATEGORIES.values())
    assert GRAMMAR_CATEGORIES <= declared, (
        f"gated categories with no instructions: {GRAMMAR_CATEGORIES - declared}"
    )


@pytest.mark.parametrize("line,card_name", [
    ("Lightning Bolt deals 3 damage to any target.", "Lightning Bolt"),
    ("Target creature gets +3/+3 until end of turn.", None),
])
def test_gated_lines_are_marked_usable(line, card_name):
    assert compile_line(line, card_name=card_name).usable


# ---------------------------------------------------------------------------
# Target descriptions (grammar-only; consumed by engine/targeting.py)
# ---------------------------------------------------------------------------


def test_any_target_is_recorded_as_such():
    """"Any target" is CR 115.4's shorthand for a creature, player or
    planeswalker — the engine cannot narrow it, and must not pretend to."""
    (_kind, payload), = _full_payloads(
        "Lightning Bolt deals 3 damage to any target.", "Lightning Bolt"
    )

    assert payload["targets"] == {"quantifier": "any_target", "kind": "any"}


def test_a_targeted_object_records_its_filter():
    """The filter is what makes "target attacking creature" different from
    "target creature" — dropping it is how a targeting layer ends up offering
    illegal choices."""
    (_kind, payload), = _full_payloads(
        "This land deals 1 damage to target attacking creature.", "Desert"
    )

    assert payload["targets"] == {
        "quantifier": "target",
        "kind": "object",
        "filter": {"type_filter": "creature", "attacking_only": True},
    }


def test_untargeted_recipients_get_no_description():
    """"You" is never a target (CR 115.10b), so recording one would be a
    claim the card does not make."""
    (_kind, payload), = _full_payloads(
        "Sorrow's Path deals 2 damage to you.", "Sorrow's Path"
    )

    assert "targets" not in payload


# ---------------------------------------------------------------------------
# Sacrifice
# ---------------------------------------------------------------------------


def test_sacrifice_this_permanent_lowers_to_the_self_handler():
    """"When you control no Islands, sacrifice this creature." — Dandân,
    Sea Serpent, Pirate Ship and Island Fish Jasconius share this line."""
    assert _instructions("Sacrifice this creature.", "Dandân") == [("sacrifice_self", {})]


def test_sacrifice_is_not_tied_to_a_card_type():
    """The same production covers any permanent type — "sacrifice this
    artifact" and "sacrifice this enchantment" are the same effect."""
    assert _instructions("Sacrifice this artifact.", "Test") == [("sacrifice_self", {})]


def test_sacrificing_a_chosen_permanent_arms_the_choice():
    """"Sacrifice a creature" makes a *player* choose which one. It used to
    refuse for want of the pending-choice machinery; it now lowers onto it
    (Dire Fleet Warmonger's optional cost), with "another" carried as the
    exclusion the prompt enforces rather than as part of the filter it tests."""
    result = compile_line("Sacrifice a creature.", card_name="Test")
    assert result.lowered, result.failure_reason
    assert [(i.kind, i.payload) for i in result.instructions] == [
        ("sacrifice_matching_permanent", {"filter": {"type_filter": "creature"}})
    ]

    another = compile_line("Sacrifice another creature.", card_name="Test")
    assert another.lowered, another.failure_reason
    assert another.instructions[0].payload == {
        "filter": {"type_filter": "creature"}, "exclude_self": True
    }


def test_a_sacrifice_narrowing_the_prompt_can_test_rides_the_filter():
    """The prompt lists whatever the printed noun phrase names, so a narrowing
    it can test is carried rather than refused — "a creature with defender"
    (Portcullis Vine's cost) and "a creature ... with flying" (Run Afoul)."""
    narrowed = compile_line("Sacrifice a black creature.", card_name="Test")
    assert narrowed.lowered, narrowed.failure_reason
    assert narrowed.instructions[0].payload == {
        "filter": {"type_filter": "creature", "color_filter": "B"}
    }

    keyworded = compile_line("Sacrifice a creature with defender.", card_name="Test")
    assert keyworded.lowered, keyworded.failure_reason
    assert keyworded.instructions[0].payload == {
        "filter": {"type_filter": "creature", "with_keywords": ["defender"]}
    }


def test_a_sacrifice_narrowing_the_prompt_cannot_test_still_refuses():
    """A narrowing whose payload key is outside the **promised** set refuses the
    whole line rather than sacrificing any creature at all. That is the reason
    the payload is gated on a key set instead of being handed over whole: the
    gate reads the promise (``TESTABLE_SUBJECT_FILTER_KEYS`` /
    ``OBJECT_ONLY_FILTER_KEYS``), never a hope that some matcher downstream
    happens to answer.

    The example has moved twice, and both moves are the guard working rather
    than rotting: it was "an attacking creature" until ``attacking_only`` joined
    the set for Disharmony's untap, and "a blocking creature" until
    ``blocking_only`` joined it for Righteousness' picker and Sorrow's Path's
    two blockers. What is left outside the promise is the *union* spelling —
    ``any_states``, "attacking **or** blocking" — so that is what the guard
    names now.
    """
    result = compile_line("Sacrifice an attacking or blocking creature.", card_name="Test")
    assert result.parsed and not result.lowered


# ---------------------------------------------------------------------------
# Damage prevention (CR 615)
# ---------------------------------------------------------------------------


def test_prevention_recipient_selects_the_shield_shape():
    """One handler, three recipients, and they are not interchangeable:
    `to_self` shields the ability's controller, `to_source` the permanent the
    ability is on, and neither shields a chosen target. Getting this wrong puts
    the shield on the wrong thing while the card still looks supported."""
    to_target = _instructions(
        "Prevent the next 1 damage that would be dealt to any target this turn.", "Samite Healer"
    )
    to_you = _instructions(
        "Prevent the next 2 damage that would be dealt to you this turn.", "Conservator"
    )
    to_source = _instructions(
        "Prevent the next 1 damage that would be dealt to this creature this turn.", "Rock Hydra"
    )

    assert to_target == [("grant_prevention_shield", {"amount": 1, "to_self": False, "to_source": False})]
    assert to_you == [("grant_prevention_shield", {"amount": 2, "to_self": True, "to_source": False})]
    assert to_source == [("grant_prevention_shield", {"amount": 1, "to_self": False, "to_source": True})]


def test_colour_scoped_shield_carries_its_colour():
    """A Circle of Protection shields against one colour. The colour is the
    whole point of the card — dropping it would shield against everything."""
    assert _instructions(
        "The next time a red source of your choice would deal damage to you this turn, "
        "prevent that damage.",
        "Circle of Protection: Red",
    ) == [("grant_prevention_shield", {"amount": 1, "protection_kind": "color", "prevention_color": "R"})]


def test_an_uncoloured_source_shield_is_refused():
    """Reverse Damage's "a source of your choice" with no colour is a different
    handler (it also gains life). Lowering it as a colourless Circle of
    Protection would silently drop the life gain."""
    result = compile_line(
        "The next time a source of your choice would deal damage to you this turn, "
        "prevent that damage. You gain life equal to the damage prevented this way.",
        card_name="Reverse Damage",
    )

    assert not result.usable


def test_a_narrowed_prevention_target_keeps_its_filter_in_the_description():
    """Oasis shields "target creature"; the handler takes no filter, so the
    restriction survives in the grammar-only `targets` description that
    engine/targeting.py reads, rather than being dropped."""
    (_kind, payload), = _full_payloads(
        "Prevent the next 1 damage that would be dealt to target creature this turn.", "Oasis"
    )

    assert payload["targets"]["filter"] == {"type_filter": "creature"}


# ---------------------------------------------------------------------------
# Colour replacement (the Lace cycle)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card,colour,symbol",
    [("Chaoslace", "red", "R"), ("Deathlace", "black", "B"), ("Lifelace", "green", "G"),
     ("Purelace", "white", "W"), ("Thoughtlace", "blue", "U")],
)
def test_lace_recolours_to_the_printed_colour(card, colour, symbol):
    assert _instructions(f"Target spell or permanent becomes {colour}.", card) == [
        ("recolor_target_from_text", {"target_color": symbol})
    ]


def test_lace_does_not_describe_its_target():
    """"Spell or permanent" unions a stack object with a battlefield object,
    which the `targets` vocabulary cannot express. Describing it as a plain
    object derives "permanent" and drops spells on the stack from the picker —
    so it must describe nothing and let legality.py answer."""
    (_kind, payload), = _full_payloads("Target spell or permanent becomes red.", "Chaoslace")

    assert "targets" not in payload


def test_becomes_requires_a_real_colour():
    """The colour is the entire effect. An unrecognized word after "becomes"
    must fail the line rather than be skipped over."""
    result = compile_line("Target spell or permanent becomes enormous.", card_name="Test")

    assert not result.parsed


# ---------------------------------------------------------------------------
# Pay-or-else upkeep triggers
# ---------------------------------------------------------------------------


def test_sacrifice_unless_pay_stays_fused():
    """The upkeep dispatcher is keyed on (trigger condition, instruction kind)
    and its handlers implement the whole pay-or-else prompt. Decomposing this
    into `May(pay) else Sacrifice` would produce a pair no handler is keyed to,
    so the card would compile cleanly and do nothing — the Mana Vault failure."""
    assert _instructions(
        "Sacrifice this creature unless you pay {B}{B}.", "Junún Efreet"
    ) == [("upkeep_pay_or_sacrifice_self", {
        "mana": {"W": 0, "U": 0, "B": 2, "R": 0, "G": 0, "C": 0, "generic": 0}
    })]


def test_the_sacrificed_type_selects_the_handler():
    """An enchantment's pay-or-else prompt is a different registry entry from
    any other permanent's, so the noun is not decoration."""
    enchantment = _instructions(
        "Sacrifice this enchantment unless you pay {W}{W}.", "Conversion"
    )
    creature = _instructions(
        "Sacrifice this creature unless you pay {U}.", "Phantasmal Forces"
    )

    assert enchantment[0][0] == "upkeep_pay_or_sacrifice_enchantment"
    assert creature[0][0] == "upkeep_pay_or_sacrifice_self"


def test_the_mana_payload_names_every_colour():
    """The handlers index the mana dict directly, so a sparse dict would raise
    rather than read as zero."""
    (_kind, payload), = _instructions(
        "Sacrifice this enchantment unless you pay {W}{W}.", "Conversion"
    )

    assert set(payload["mana"]) == {"W", "U", "B", "R", "G", "C", "generic"}


# ---------------------------------------------------------------------------
# Zone changes ("return <object> to <zone>")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("card,line,expected", [
    (
        "Raise Dead",
        "Return target creature card from your graveyard to your hand.",
        ("return_creature_from_graveyard_to_hand", {"any_card": False, "card_type": "creature"}),
    ),
    (
        "Regrowth",
        "Return target card from your graveyard to your hand.",
        ("return_creature_from_graveyard_to_hand", {"any_card": True, "card_type": None}),
    ),
    (
        "Resurrection",
        "Return target creature card from your graveyard to the battlefield.",
        ("reanimate_creature", {}),
    ),
    (
        "Unsummon",
        "Return target creature to its owner's hand.",
        ("bounce_target_creature", {}),
    ),
])
def test_the_pair_of_zones_picks_the_return_handler(card, line, expected):
    """One verb, three unrelated handlers. They are not variations on a theme:
    each reads its target index against a different zone — two against a
    graveyard position and one against a battlefield position — so a lowering
    that guessed from the verb alone would move the wrong object."""
    assert _instructions(line, card) == [expected]


def test_the_type_word_is_what_separates_regrowth_from_raise_dead():
    """The handler's whole filter is one boolean, and it is the only thing
    keeping Raise Dead from returning a Mox. The legacy rule derived it by
    probing the sentence for the substring "creature card"; here it comes from
    the parsed noun phrase, so a card that says "artifact card" cannot silently
    borrow Raise Dead's answer."""
    creature_only = _instructions(
        "Return target creature card from your graveyard to your hand.", "Raise Dead"
    )
    any_type = _instructions(
        "Return target card from your graveyard to your hand.", "Regrowth"
    )

    assert creature_only[0][1] == {"any_card": False, "card_type": "creature"}
    assert any_type[0][1] == {"any_card": True, "card_type": None}


def test_an_unreadable_narrowing_is_refused_rather_than_dropped():
    """None of the three handlers reads a filter, so an adjective is invisible
    to them. Emitting Raise Dead's instruction for "target black creature card"
    would let it return a white one while the card still reported as
    supported — the bug class the full-consumption invariant exists to stop."""
    result = compile_line(
        "Return target black creature card from your graveyard to your hand.", card_name="Test"
    )

    assert result.parsed
    assert not result.lowered
    assert "restriction" in result.failure_reason


def test_the_named_card_type_is_carried_not_collapsed():
    """The handler used to express only "creature card or any card", so an
    artifact-only version was refused. It carries the named type now —
    collapsing "artifact card" to "any card" would let Reconstruction return a
    creature, which is the dropped-filter bug rather than a missing feature."""
    result = compile_line(
        "Return target artifact card from your graveyard to your hand.", card_name="Test"
    )

    assert result.parsed and result.lowered
    assert [(i.kind, i.payload) for i in result.instructions] == [
        (
            "return_creature_from_graveyard_to_hand",
            {"any_card": False, "card_type": "artifact"},
        )
    ]


def test_whose_graveyard_is_load_bearing():
    """Both graveyard handlers search the caster's own graveyard and nowhere
    else. Accepting "from a graveyard" would let a card that reads any
    graveyard quietly search only one of them."""
    result = compile_line(
        "Return target creature card from a graveyard to your hand.", card_name="Test"
    )

    assert result.parsed
    assert not result.lowered
    assert "your own" in result.failure_reason


def test_a_graveyard_return_requires_the_card_noun():
    """A graveyard holds cards, not permanents (CR 400.1), and Magic never
    templates it otherwise. Accepting the permanent wording would make "card"
    a word whose deletion changes nothing — which is precisely what the
    parse-coverage deletion probe hunts for."""
    result = compile_line(
        "Return target creature from your graveyard to your hand.", card_name="Test"
    )

    assert result.parsed
    assert not result.lowered


def test_reanimation_refuses_an_untyped_card():
    """`reanimate_creature` only ever puts a creature onto the battlefield.
    Claiming Regrowth's untyped noun phrase for it would narrow the player's
    choice without saying so."""
    result = compile_line(
        "Return target card from your graveyard to the battlefield.", card_name="Test"
    )

    assert result.parsed
    assert not result.lowered
    assert "creature cards" in result.failure_reason


def test_bounce_returns_a_creature_to_its_owner_not_to_you():
    """`bounce_target_creature` puts the creature in its owner's hand by
    construction. "To your hand" is a different effect the moment you have
    stolen the creature, so it refuses instead of approximating."""
    to_owner = compile_line("Return target creature to its owner's hand.", card_name="Unsummon")
    to_caster = compile_line("Return target creature to your hand.", card_name="Test")

    assert to_owner.lowered
    assert to_caster.parsed and not to_caster.lowered


def test_a_graveyard_card_is_never_described_to_the_battlefield_picker():
    """`targets` names battlefield permanents (engine/targeting.py). Describing
    a reanimation target with it would offer creatures already in play for a
    spell whose target index means a graveyard position — the Animate Dead
    mis-derivation, reintroduced."""
    payloads = _full_payloads(
        "Return target creature card from your graveyard to the battlefield.", "Resurrection"
    )

    assert payloads == [("reanimate_creature", {})]


def test_a_zone_scoped_filter_cannot_reach_a_battlefield_handler():
    """`ObjectFilter.to_payload` has no way to say "in a graveyard", so every
    handler reached through it searches the battlefield. A filter that names
    another zone has to fail the line rather than arrive stripped of the one
    word that mattered."""
    result = compile_line("Destroy target creature card in a graveyard.", card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert "graveyard" in result.failure_reason


# ---------------------------------------------------------------------------
# Looking at a hand (CR 701.16)
# ---------------------------------------------------------------------------


def test_look_at_target_hand_matches_the_legacy_payload():
    """Glasses of Urza's printed line. The handler takes an empty payload, so
    the whole compatibility contract is "emit nothing else" — a stray key here
    would reach a handler that never expected one."""
    assert _instructions("{T}: Look at target player's hand.", "Glasses of Urza") == [
        ("look_at_target_hand", {})
    ]


def test_looking_at_a_non_targeted_hand_is_refused():
    """`look_at_target_hand` reads one chosen player off the resolution context
    and builds a single reveal. "Each opponent's hand" needs a loop it does not
    have, so lowering it there would reveal exactly one hand and report success
    for a card that asked for several."""
    result = compile_line("Look at each opponent's hand.", card_name="Test")

    assert not result.lowered
    assert "each_opponent" in result.failure_reason


def test_look_at_requires_the_object_it_looks_at():
    """"Look at" heads a family of information effects distinguished only by
    their object — a hand, the top cards of a library, a face-down creature. A
    production that skipped the noun would claim every one of them and read the
    wrong zone.

    The probe used to be Natural Selection's own line, which was a name-keyed
    hook then and is a production now (Portent prints the identical sentence).
    A parseable line makes a poor test of what happens to an unparseable one, so
    the probe is a "look at" with no object at all — which is what the assertion
    was always about."""
    result = compile_line("Look at the top three cards.", card_name="Test")

    assert not result.parsed


def test_looking_at_another_library_reorders_only_when_the_card_says_so():
    """"…then put them back in any order" is a different handler from the bare
    look, not a flag on it: Visions looks at five cards and never rearranges
    them, and reading the two as one sentence would hand its controller a
    rearrangement the card does not give."""
    looked = compile_line(
        "Look at the top five cards of target player's library. You may then "
        "have that player shuffle that library.",
        card_name="Visions",
    )
    reordered = compile_line(
        "Look at the top three cards of target player's library, then put them "
        "back in any order.",
        card_name="Natural Selection",
    )

    assert [i.kind for i in looked.instructions] == ["look_at_target_library_top"]
    assert [i.kind for i in reordered.instructions] == ["reorder_target_library_top"]


# ---------------------------------------------------------------------------
# Extra turns (CR 505.6b)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line,card_name", [
    ("Take an extra turn after this one.", "Time Walk"),
    ("{T}: Take an extra turn after this one.", "Time Vault"),
])
def test_extra_turn_lowers_the_same_from_a_spell_and_an_ability(line, card_name):
    """The same clause appears as a sorcery's whole text and as an activated
    ability's effect. Both must reach the same instruction — a production that
    only worked in one grammatical position would leave the other card silently
    on the legacy path."""
    assert _instructions(line, card_name) == [("grant_extra_turn", {})]


def test_counted_extra_turns_carry_their_count():
    """"Take two extra turns after this one." (Teferi, Master of Time.)
    ``grant_extra_turn`` loops the payload's count, so the parse must carry it —
    a count consumed and dropped would compile cleanly and hand back a single
    turn, wrong by one turn every cast."""
    result = compile_line("Take two extra turns after this one.", card_name="Test")

    assert result.usable
    assert result.instructions[0].kind == "grant_extra_turn"
    assert result.instructions[0].payload["count"] == 2


def test_the_extra_turn_must_say_when_it_is_taken():
    """"after this one" is what places the turn immediately. Treating it as
    optional decoration would make a card that schedules the turn elsewhere
    lower onto a handler that always queues it next."""
    result = compile_line("Take an extra turn.", card_name="Test")

    assert not result.parsed


# ---------------------------------------------------------------------------
# "Can't be …" restrictions
# ---------------------------------------------------------------------------


def test_deny_regeneration_matches_the_legacy_payload():
    """Hurr Jackal's printed line."""
    assert _instructions(
        "{T}: Target creature can't be regenerated this turn.", "Hurr Jackal"
    ) == [("deny_regeneration_to_target", {})]


def test_unblockable_carries_its_printed_power_bound():
    """Dwarven Warriors' printed line.

    The bound is payload. It used to be a literal in the handler's own source
    and again in legality.py's enumerator, with a kind of its own
    (``grant_unblockable_to_low_power_target``) and a lowering that compared
    the parsed comparison against the literal — so every other threshold, and
    every other narrowing, refused."""
    assert _instructions(
        "{T}: Target creature with power 2 or less can't be blocked this turn.",
        "Dwarven Warriors",
    ) == [(
        "grant_unblockable_to_target",
        {"type_filter": "creature", "power": {"op": "le", "value": 2}},
    )]


def test_a_different_power_threshold_now_rides_the_payload():
    """The trap the old production existed to survive, gone rather than
    guarded: a card reading "power 3 or less" carries 3."""
    assert _instructions(
        "{T}: Target creature with power 3 or less can't be blocked this turn.",
        "Test",
    ) == [(
        "grant_unblockable_to_target",
        {"type_filter": "creature", "power": {"op": "le", "value": 3}},
    )]


def test_a_narrowed_restriction_target_is_refused():
    """Both handlers set a flag on whatever ``resolve_target_permanent``
    returns; neither reads a filter from the payload. So a restriction the noun
    phrase carries has nowhere to go — honouring it is impossible and dropping
    it would deny regeneration to a creature the card could not target."""
    result = compile_line(
        "{T}: Target black creature can't be regenerated this turn.", card_name="Test"
    )

    assert result.parsed
    assert not result.lowered


def test_a_restriction_with_no_duration_is_a_static_ability():
    """"Enchanted creature can't be regenerated" is continuous, not a one-shot
    effect. The handlers set an end-of-turn flag, so lowering a durationless
    restriction onto them would quietly expire an effect that should last as
    long as the Aura does."""
    result = compile_line("Target creature can't be regenerated.", card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert "static" in result.failure_reason


def test_a_blocking_exception_clause_fails_full_consumption():
    """This says *who* the restriction does not apply to. Consuming the
    exception without modelling it would turn a conditional restriction into an
    absolute one — Juggernaut would become unblockable by anything. Leaving the
    tokens makes the line fail loudly and fall back instead.

    Invisibility prints the same shape and is deliberately *not* here: its
    exception is modelled, by ``auras.aura_restriction_active``, so the line is
    claimed rather than refused (see the test below)."""
    result = compile_line("This creature can't be blocked by Walls.", card_name="Juggernaut")

    assert not result.parsed


def test_an_auras_block_restriction_is_claimed_because_it_is_modelled():
    result = compile_line(
        "Enchanted creature can't be blocked except by Walls.", card_name="Invisibility"
    )

    assert result.lowered
    assert result.instructions == ()
    assert result.node.registry == "auras"


def test_an_unmodelled_restriction_participle_is_refused():
    """The participle is read from a closed list. If it were skipped, every
    "can't be …" line would collapse onto whichever handler the production
    happened to prefer."""
    result = compile_line("Target creature can't be targeted this turn.", card_name="Test")

    assert not result.parsed


def test_damage_riders_still_lower_as_riders_not_as_restrictions():
    """Disintegrate's trailing sentence is a rider on the damage it just dealt,
    and ``_parse_damage_rider_sentence`` claims it before this production sees
    it. If the new "can't be regenerated" production took the sentence instead,
    the rider would become a second instruction targeting nothing and the
    ``no_regen`` flag would never reach the damage payload."""
    assert _instructions(
        "Disintegrate deals X damage to any target. If it's a creature, it can't be "
        "regenerated this turn, and if it would die this turn, exile it instead.",
        "Disintegrate",
    ) == [("deal_damage", {"amount": "x", "no_regen": True, "exile_if_dies": True})]


@pytest.mark.parametrize("line,card_name,kind", [
    ("Destroy target nonartifact, nonblack creature. It can't be regenerated.",
     "Terror", "destroy_target_permanent"),
    ("Destroy all creatures. They can't be regenerated.",
     "Wrath of God", "destroy_all_creatures"),
])
def test_destroy_keeps_its_inline_no_regeneration_clause(line, card_name, kind):
    """"It can't be regenerated" after a destroy is part of the destruction, not
    a separate restriction on a separate target. ``_parse_destroy`` consumes it
    inline; this pins that the new production did not steal the sentence and
    strand ``bypass_regeneration``."""
    (lowered_kind, payload), = _instructions(line, card_name)

    assert lowered_kind == kind
    assert payload["bypass_regeneration"] is True


def test_the_unblockable_target_describes_its_power_bound():
    """This used to emit no description at all, on the grounds that
    ``ObjectFilter.to_payload`` had no vocabulary for a power comparison — so a
    `targets` description would have read "target creature" and the picker
    would have offered creatures the ability could not affect. The vocabulary
    exists now, and the bound reaches both the picker and the handler through
    one description rather than through a literal written into each."""
    (_kind, payload), = _full_payloads(
        "{T}: Target creature with power 2 or less can't be blocked this turn.",
        "Dwarven Warriors",
    )

    assert payload["targets"]["filter"]["power"] == {"op": "le", "value": 2}


# ---------------------------------------------------------------------------
# Counterspells and their riders
# ---------------------------------------------------------------------------


def test_counter_with_mana_value_x_becomes_the_handlers_gate():
    """Spell Blast. ``counter_top_stack_spell`` compares the X chosen on the
    cast against the target's mana value only when told to; without the flag it
    counters whatever it is aimed at, so the restriction would evaporate and
    Spell Blast would read as a strictly better Counterspell."""
    assert _instructions(
        "Counter target spell with mana value X. (For example, if that spell's "
        "mana cost is {3}{U}{U}, X is 5.)",
        "Spell Blast",
    ) == [("counter_top_stack_spell", {"mv_equals_x": True})]


@pytest.mark.parametrize(
    "line",
    [
        "Counter target spell with mana value 3.",
        "Counter target spell with mana value 3 or less.",
    ],
)
def test_a_mana_value_gate_the_handler_cannot_ask_is_refused(line):
    """"Equals the X I chose" is the only mana-value question the handler can
    ask. A fixed number or an inequality lowered to the same flag would counter
    a spell of the wrong cost — worse than the card being unsupported."""
    result = compile_line(line, card_name="Test")

    assert result.parsed and not result.lowered


def test_a_literal_mana_value_restriction_reaches_the_payload():
    """A fixed bound ("mana value 3 or less", Eliminate) is carried on the
    payload and tested by ``permanent_matches_filter`` — never dropped."""
    result = compile_line(
        "Destroy target creature with mana value 3 or less.", card_name="Test"
    )

    assert result.parsed and result.lowered, result.failure_reason
    assert result.instructions[0].payload["mana_value"] == {"op": "le", "value": 3}


def test_a_variable_mana_value_restriction_still_refuses():
    """"mana value X" has no payload form, and dropping the bound would widen
    the effect to every mana value — the dropped-rider bug class."""
    result = compile_line("Tap target creature with mana value X.", card_name="Test")

    assert result.parsed and not result.lowered


def test_counter_unless_the_controller_pays_x():
    """Power Sink. The flag is what arms the pending "{X} or be countered"
    payment; without it the spell is countered outright and its controller
    never gets the choice the card gives them."""
    assert _instructions(
        "Counter target spell unless its controller pays {X}. If that player "
        "doesn't, they tap all lands with mana abilities they control and lose "
        "all unspent mana.",
        "Power Sink",
    ) == [("counter_top_stack_spell", {"unless_pays_x": True})]


def test_the_unpaid_penalty_is_a_rider_not_a_second_step():
    """The penalty happens *inside* countering (ON_SPELL_COUNTERED, run from
    _resolve_mana_payment), so it must not become an instruction of its own —
    a second step would tap the lands even when the controller paid."""
    result = compile_line(
        "Counter target spell unless its controller pays {X}. If that player "
        "doesn't, they tap all lands with mana abilities they control and lose "
        "all unspent mana.",
        card_name="Power Sink",
    )

    assert len(result.instructions) == 1


def test_a_fixed_unless_pays_cost_carries_its_printed_amount():
    """The fixed form (Miscast's {3}) arms the same pending payment Power Sink
    does, sized from the printed cost rather than a chosen X — so the amount
    must ride the payload, and the two flags never appear together."""
    result = compile_line(
        "Counter target spell unless its controller pays {2}.", card_name="Test"
    )

    assert result.lowered
    payload = result.instructions[0].payload
    assert payload.get("unless_pays_amount") == 2
    assert "unless_pays_x" not in payload


def test_a_coloured_unless_pays_cost_is_refused():
    """No flow charges a coloured pip: the pending payment is generic mana
    only, so "pays {W}" must refuse rather than prompt for the wrong cost."""
    result = compile_line(
        "Counter target spell unless its controller pays {1}{W}.", card_name="Test"
    )

    assert result.parsed and not result.lowered


def test_only_the_countered_spells_controller_can_pay():
    """"Unless you pay" puts the decision on the caster, which is a different
    effect from the one the counter flow implements. Accepting it would offer
    the choice to the wrong player."""
    result = compile_line(
        "Counter target spell unless you pay {X}.", card_name="Test"
    )

    assert not result.parsed


def test_an_unperformed_penalty_fails_the_whole_line():
    """A penalty the engine does not perform must not be consumed. Swallowing
    the sentence would leave the card compiling cleanly while half of what it
    says never happens — the dropped-rider bug the full-consumption invariant
    exists to prevent."""
    result = compile_line(
        "Counter target spell unless its controller pays {X}. If that player "
        "doesn't, they lose 5 life.",
        card_name="Test",
    )

    assert not result.parsed


def test_a_decline_penalty_needs_a_cost_to_decline():
    """"If that player doesn't" with no "unless … pays" in front of it has
    nothing to attach to; the grammar has no place to put it and says so."""
    result = compile_line(
        "Counter target spell. If that player doesn't, they tap all lands with "
        "mana abilities they control and lose all unspent mana.",
        card_name="Test",
    )

    assert not result.parsed


def test_a_counterspell_targets_a_spell_on_the_stack():
    """The riders must not disturb the target description: a counterspell picks
    from the stack, and describing it as an object would make the UI offer
    battlefield permanents instead."""
    for line, name in (
        ("Counter target spell with mana value X.", "Spell Blast"),
        ("Counter target spell unless its controller pays {X}.", "Power Sink"),
    ):
        (_kind, payload), = _full_payloads(line, name)
        assert payload["targets"] == {"quantifier": "target", "kind": "spell"}


# ---------------------------------------------------------------------------
# Tap-or-untap (Twiddle's disjunction)
# ---------------------------------------------------------------------------


def test_tap_or_untap_is_one_effect_with_one_target():
    """Both directions act on the same chosen permanent and only one happens.
    Reading "or" as a conjunction of two statements would tap the permanent and
    then untap it, leaving the board unchanged."""
    assert _instructions("Tap or untap target permanent.", "Twiddle") == [
        ("tap_or_untap_target", {})
    ]


@pytest.mark.parametrize(
    "line",
    [
        "Tap or untap target creature.",
        "Tap or untap target artifact, creature, or land.",
    ],
)
def test_tap_or_untap_carries_the_noun_phrase_it_is_printed_with(line):
    """The toggle used to honour no restriction at all, so a narrowed form had to
    refuse: lowered onto it, "target **creature**" could have untapped a land.
    It reads the filter now (Tolarian Kraken), and an explicitly chosen
    non-matching permanent fizzles rather than sliding onto a legal one."""
    result = compile_line(line, card_name="Test")

    assert result.lowered, result.failure_reason
    (instruction,) = result.instructions
    assert instruction.kind == "tap_or_untap_target"
    assert instruction.payload["type_filter"] == (
        "creature" if "creature." in line else ["artifact", "creature", "land"]
    )


def test_tap_or_untap_carries_a_controller_narrowing():
    """"…an opponent controls" (Hyperion Blacksmith) / "…you control".

    A seat comparison, so the pure permanent matcher cannot answer it — which
    used to refuse the line. The handler asks ``subject_matches`` with the
    resolving seat as its observer and the picker carries the same restriction,
    so the narrowing is carried rather than refused, and it reaches the payload
    where both of them read it."""
    for text, controller in (
        ("Tap or untap target creature you control.", "you"),
        ("Tap or untap target artifact an opponent controls.", "opponent"),
    ):
        result = compile_line(text, card_name="Test")

        assert result.lowered, result.lowering_error
        (instruction,) = result.instructions
        assert instruction.kind == "tap_or_untap_target"
        assert instruction.payload["controller"] == controller


def test_tap_or_untap_still_refuses_a_restriction_the_matcher_cannot_test():
    """The gate moved out to ``TESTABLE_SUBJECT_FILTER_KEYS``; it did not go
    away. A phrase naming something no filter payload can carry is still
    refused, because it would be dropped where the narrowing is applied."""
    result = compile_line(
        "Tap or untap target creature blocking this creature.", card_name="Test"
    )

    assert result.parsed and not result.lowered


def test_untap_or_tap_is_not_invented():
    """No card prints the reversed wording. Accepting it would mean the grammar
    claims text the pool never contains, which is untestable surface area."""
    result = compile_line("Untap or tap target permanent.", card_name="Test")

    assert not result.parsed


def test_tap_or_untap_records_its_target():
    """The handler takes no filter, but the *card* still targets — the
    description is what lets engine/targeting.py answer the picker from the
    compiled program instead of re-reading oracle text."""
    (_kind, payload), = _full_payloads("Tap or untap target permanent.", "Twiddle")

    assert payload["targets"] == {
        "quantifier": "target", "kind": "object", "filter": {},
    }


# ---------------------------------------------------------------------------
# Blanket combat-damage prevention (Fog)
# ---------------------------------------------------------------------------


def test_fog_lowers_to_the_turn_wide_combat_flag():
    """Byte-identical to the legacy rule this replaces.

    ``prevent_all_combat_damage`` takes an empty payload and sets one turn-wide
    flag that ``engine/prevention.py`` reads on every event carrying
    ``combat=True``. A payload key the handler does not read would leave the
    card reporting as supported while the flag never got set.
    """
    assert _instructions(
        "Prevent all combat damage that would be dealt this turn.", "Fog"
    ) == [("prevent_all_combat_damage", {})]


def test_blanket_prevention_refuses_damage_of_every_kind():
    """"Prevent all damage that would be dealt this turn" is a strictly larger
    effect than Fog. The flag is consulted only for combat damage, so lowering
    this onto it would let every burn spell through while the card reported as
    supported."""
    result = compile_line(
        "Prevent all damage that would be dealt this turn.", card_name="Test"
    )

    assert result.parsed and not result.lowered
    assert "every kind" in result.failure_reason


def test_blanket_prevention_refuses_a_recipient():
    """The flag is global. A shield written for one player or one creature
    lowered onto it would silently protect the whole table — including the
    opponent's attackers."""
    result = compile_line(
        "Prevent all combat damage that would be dealt to you this turn.",
        card_name="Test",
    )

    assert result.parsed and not result.lowered
    assert "one recipient" in result.failure_reason


def test_blanket_prevention_refuses_a_duration_the_flag_cannot_hold():
    """``combat_damage_prevented_until_eot`` is cleared in the cleanup step, so
    "this turn" is the only duration it can express. A permanent blanket
    prevention is a static ability and needs the CR 613 layers engine."""
    result = compile_line(
        "Prevent all combat damage that would be dealt.", card_name="Test"
    )

    assert result.parsed and not result.lowered
    assert "this turn" in result.failure_reason


def test_counted_prevention_is_never_scoped_to_combat():
    """``grant_prevention_shield`` counts down against damage of any kind. A
    "prevent the next N combat damage" lowered onto it would also absorb N
    damage from a burn spell, spending a shield the card never offered."""
    from engine.grammar import ast
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_statement

    node = ast.PreventDamage(
        ast.Fixed(3),
        to=ast.PlayerRef("you"),
        duration=ast.Duration("this_turn"),
        combat_only=True,
    )
    with pytest.raises(LoweringError):
        lower_statement(node)


# ---------------------------------------------------------------------------
# "has <keyword>" — the third person of "gains"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,card",
    [
        ("Enchanted creature has flying.", "Flight"),
        ("Enchanted creature has first strike.", "Lance"),
        ("Enchanted creature has islandwalk.", "Fishliver Oil"),
    ],
)
def test_an_auras_keyword_grant_is_claimed_by_the_code_that_derives_it(line, card):
    """The hazard these lines pose is unchanged and is why they must never be
    *lowered*: with no duration the keyword lasts as long as the Aura does,
    while every keyword-grant handler sets an until-end-of-turn flag the
    cleanup step wipes — so lowering onto one would grant flying for a single
    turn and then silently stop.

    The answer is not a phase-6 lowering, though; it is that layer 6 already
    carries them, derived from the attached Aura. Zero instructions is the
    correct output, and the claim names the derivation."""
    result = compile_line(line, card_name=card)

    assert result.parsed, result.failure_reason
    assert result.lowered
    assert result.instructions == ()
    assert result.node.registry == "auras"


def test_a_lords_keyword_grant_lowers_to_its_own_table():
    """The sibling case, and the boundary is still visible: a lord's grant to
    *other* creatures is not an Aura grant, so auras.py may not account for it —
    it lowers to ``lord_buff``, whose consumer contributes the keyword to the
    derived layer-6 channel for as long as the lord is there."""
    result = compile_line("Other Zombie creatures have swampwalk.", card_name="Zombie Master")

    assert result.parsed, result.failure_reason
    assert result.lowered
    assert [i.kind for i in result.instructions] == ["lord_buff"]
    assert result.instructions[0].payload == {
        "power": 0, "toughness": 0, "subtypes": ["zombie"], "other": True,
        "keywords": ["swampwalk"],
    }
    assert not hasattr(result.node, "registry"), "an Aura registry must not claim a lord line"


def test_a_keyword_layer_6_does_not_carry_refuses_by_name():
    """An unimplemented keyword must take the line down rather than lower the
    P/T half and drop the grant — the dropped-rider bug class, in the sentence
    that first produced it."""
    result = compile_line("Other Goblins get +1/+1 and have shadow.", card_name="Invented Lord")

    assert not result.lowered
    assert "shadow" in result.failure_reason and "lord_buffs" in result.failure_reason


def test_has_base_power_still_reaches_its_own_production():
    """"Base" is the one reading of "has" that is not a keyword grant. If the
    keyword list claimed it first, "base" would fail the keyword lookup and take
    the whole line down, turning every base-P/T setter unsupported."""
    assert _instructions(
        "Target creature has base power and toughness 0/2 until end of turn.",
        "Humility Test",
    ) == [
        (
            "set_base_pt_target_until_eot",
            {"power": 0, "toughness": 2, "exclude_self": False},
        )
    ]


def test_lord_conjunction_keeps_both_halves():
    """"Other Goblins get +1/+1 and have mountainwalk" is one sentence stating
    two continuous effects. Reading only the pump would drop the landwalk
    silently — the dropped-rider bug class — so the conjunction is lowered as
    one buff carrying both halves.

    It is also a *static ability*: the whole conjunction has no duration, which
    is what ``_looks_static`` now asks. Judging one effect at a time put these
    lines on a different lowering path from the anthems that say the same kind
    of thing."""
    result = compile_line(
        "Other Goblins get +1/+1 and have mountainwalk.", card_name="Goblin King"
    )

    assert result.parsed and result.lowered
    kinds = [type(effect).__name__ for effect in result.node.effect.effects]
    assert kinds == ["Pump", "GainKeyword"]
    assert result.instructions[0].payload == {
        "power": 1, "toughness": 1, "subtypes": ["goblin"], "other": True,
        "keywords": ["mountainwalk"],
    }


def test_other_excludes_the_source_rather_than_being_dropped():
    """A lord does not pump itself. "Other" sets the same ``other_than_source``
    field the postmodifier "other than this creature" sets, so any lowering that
    already honours one honours both. Ignoring the word would make Goblin King a
    3/3, and CR 613 does not exempt a static ability's own source unless the
    card says so — which is why it is a derived field rather than an
    assumption."""
    result = compile_line(
        "Other Goblins get +1/+1 and have mountainwalk.", card_name="Goblin King"
    )
    pump = result.node.effect.effects[0]

    assert pump.subject.filter.other_than_source is True
    assert pump.subject.filter.subtypes == ("goblin",)
    assert result.instructions[0].payload["other"] is True


def test_other_does_not_swallow_the_postmodifier_wording():
    """"Sacrifice a creature other than this creature" must keep parsing through
    the postmodifier branch. If the leading-adjective rule ate that "other",
    "than this creature" would be left to parse as a noun phrase and the whole
    line would fail."""
    from engine.grammar.lexer import tokenize
    from engine.grammar.parser import parse_statement
    from engine.grammar.stream import TokenStream

    lexed = tokenize(
        "Sacrifice a creature other than this creature", card_name="Lord of the Pit"
    )
    statement = parse_statement(TokenStream(lexed.tokens, "x"))

    assert statement.subject.filter.other_than_source is True
    assert statement.subject.filter.card_types == ("creature",)


# ---------------------------------------------------------------------------
# Registry lines: text-keyed behaviour with no instruction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,card",
    [
        ("Enchant creature", "Aspect of Wolf"),
        ("Enchant land", "Consecrate Land"),
        ("Enchant artifact", "Animate Artifact"),
        ("Enchant enchantment", "Feedback"),
        ("Enchant Wall", "Animate Wall"),
        (
            "Enchant creature (Target a creature as you cast this. This card "
            "enters attached to that creature.)",
            "Fear",
        ),
    ],
)
def test_aura_enchant_lines_are_accounted_for_by_the_targeting_registry(line, card):
    """An Aura's attachment restriction is not an effect and never becomes one:
    ``mixins/stack/casting.aura_enchant_noun`` reads it to decide which
    permanents the Aura may be cast onto, and ``targeting.derive_cast_target``
    reads it to tell the UI what to offer. An instruction here would duplicate a
    restriction the engine already applies at cast time."""
    result = compile_line(line, card_name=card)

    assert result.parsed and result.lowered
    assert result.node.registry == "auras"
    assert result.instructions == ()
    # No categories means the legacy path still handles the card unchanged,
    # which is what keeps the compiler's stored text — the string those
    # consumers match on — byte-identical.
    assert not result.usable


def test_animate_dead_enchant_line_is_not_claimed():
    """"Enchant creature card in a graveyard" names a graveyard card, not a
    battlefield permanent. Both consumers deliberately refuse it — the regex in
    targeting.py carries a negative lookahead for exactly this — so claiming it
    would report a reanimation Aura's attachment rule as handled while nothing
    handles it, and the picker would offer creatures in play."""
    result = compile_line(
        "Enchant creature card in a graveyard", card_name="Animate Dead"
    )

    assert result.parsed
    assert not result.lowered


@pytest.mark.parametrize(
    "line,card",
    [
        ("This artifact doesn't untap during your untap step.", "Basalt Monolith"),
        ("This creature doesn't untap during your untap step.", "Brass Man"),
        (
            "You may choose not to untap this creature during your untap step.",
            "Old Man of the Sea",
        ),
    ],
)
def test_self_untap_restrictions_are_accounted_for_by_the_untap_step(line, card):
    """``phases/untap_step.py`` scans each battlefield permanent's oracle text
    for these two phrases and skips the permanent. There is no instruction to
    store, and the claim is built from the same phrase constants that scan
    tests, so it cannot outlive the enforcement."""
    result = compile_line(line, card_name=card)

    assert result.parsed and result.lowered
    assert result.node.registry == "untap_restrictions"
    assert result.instructions == ()


def test_paralyzes_untap_restriction_is_claimed_by_the_aura_not_the_untap_registry():
    """"Enchanted creature doesn't untap during its controller's untap step" is
    not a line the untap step's *self-referential* scan reads, and claiming it
    from ``untap_restrictions`` would call a card accounted for on the strength
    of code that never looks at it. That still holds.

    What changed is that something else does look at it: phase 6 moved the
    restriction onto the Aura, and ``phases/untap_step.py`` now asks
    ``aura_restriction_active(permanent, "doesnt_untap")``. So the line is
    claimed — by the registry that implements it, and only that one."""
    result = compile_line(
        "Enchanted creature doesn't untap during its controller's untap step.",
        card_name="Paralyze",
    )

    assert result.node.registry == "auras"


def test_registry_claims_stay_stricter_than_their_enforcement():
    """The untap step matches these phrases as *substrings* of a whole card's
    text, so a line that is the restriction plus something else is only
    partially implemented by it. The whole-line matcher is anchored at both ends
    to keep such a line visibly unaccounted for rather than silently absorbed."""
    from engine.untap_restrictions import self_untap_line

    assert self_untap_line("This artifact doesn't untap during your untap step.")
    assert (
        self_untap_line(
            "This artifact doesn't untap during your untap step unless you pay {3}."
        )
        is None
    )


# ---------------------------------------------------------------------------
# Trigger conditions the grammar reads (upkeep family)
#
# A trigger phrase in engine/grammar/parser.py's tables is only half the story.
# engine/oracle.py::_parse_triggered_ability still takes the *condition* from
# its own legacy tables and only the *effect* from the grammar, and the engine
# dispatches on the pair (legacy condition kind, instruction kind). So a grammar
# phrase pays off only when the legacy table matches the same line with the same
# kind AND something is keyed to the resulting pair. The two pool-wide guards at
# the end of this section check exactly that; the goldens here pin the payloads.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card, line",
    [
        (
            "Feedback",
            "At the beginning of the upkeep of enchanted enchantment's controller, "
            "this Aura deals 1 damage to that player.",
        ),
        (
            "Wanderlust",
            "At the beginning of the upkeep of enchanted creature's controller, "
            "this Aura deals 1 damage to that player.",
        ),
        (
            "Warp Artifact",
            "At the beginning of the upkeep of enchanted artifact's controller, "
            "this Aura deals 1 damage to that player.",
        ),
        (
            "Cursed Land",
            "At the beginning of the upkeep of enchanted land's controller, "
            "this Aura deals 1 damage to that player.",
        ),
    ],
)
def test_aura_upkeep_damage_lowers_to_the_dispatched_pair(card, line):
    """The three Auras that ping whoever controls what they enchant.

    All that was missing was the trigger phrase: the effect clause already
    lowered, and ``("upkeep_enchanted_controller", "deal_damage")`` is a
    registered pair in engine/phases/upkeep_effects.py.

    ``recipient`` joined the payload with Detonate (round 23): a damage clause
    that names a player now says so, instead of the handler inferring it from
    the absence of a permanent index. Inert here — this pair's dispatcher works
    out the enchanted permanent's controller itself and reads only the amount —
    but recorded in the golden rather than filtered out of it, because a golden
    that hides a key is a golden that would not notice the key changing.
    """
    assert _instructions(line, card) == [
        ("deal_damage", {"amount": 1, "recipient": "target_player"})
    ]


def test_enchanted_land_upkeep_is_dispatched_like_its_peers():
    """Cursed Land reads exactly like Feedback/Wanderlust/Warp Artifact, and is
    dispatched by the same pair.

    ``land`` used to be excluded from the trigger table because the damage was
    dealt by a bespoke enchant-land pass in engine/phases/upkeep_step.py — so
    a trigger row would have fired the damage twice. That pass is gone; the
    ``("upkeep_enchanted_controller", "deal_damage")`` handler reads
    ``attached_to`` and does not care about the enchanted type, so the land
    Aura routes through it and the line is honestly claimed. The
    ``test_cursed_land_deals_upkeep_damage_to_land_controller`` regression pins
    that the damage still lands exactly once.
    """
    result = compile_line(
        "At the beginning of the upkeep of enchanted land's controller, "
        "this Aura deals 1 damage to that player.",
        card_name="Cursed Land",
    )

    assert result.parsed
    assert [(i.kind, dict(i.payload)) for i in result.instructions] == [
        ("deal_damage", {"amount": 1, "recipient": "target_player"})
    ]


@pytest.mark.parametrize(
    "card, line",
    [
        (
            "Power Leak",
            "At the beginning of the upkeep of enchanted enchantment's controller, "
            "that player may pay any amount of mana. This Aura deals 2 damage to that "
            "player. Prevent X of that damage, where X is the amount of mana that "
            "player paid this way.",
        ),
    ],
)
def test_the_new_trigger_phrase_does_not_drag_in_effects_it_cannot_read(card, line):
    """Adding a trigger phrase widens what reaches the effect productions, and
    Power Leak is the card that reaches them and must still be refused: its
    damage is scaled by a payment the grammar has no node for, so it falls back
    to the legacy rules whole rather than compiling onto a nearby handler.

    Unstable Mutation used to be one of three. Its "put a -1/-1 counter on
    **that creature**" is now a production — the bound-object branch the removal
    side already had, mirrored onto the placement — so the line lowers to
    ``add_pt_counters_to_attached`` with the CR 122.1a pair as payload, and the
    card-name hook that spelled out "-1/-1" is gone. It was the entry that kept
    Takklemaggot's identical sentence, printed with -0/-1, out.

    Paralyze was the third, and the test below is what replaced it.
    """
    result = compile_line(line, card_name=card)

    assert not result.parsed


def test_paralyzes_upkeep_offer_lowers_to_the_kind_its_handler_is_keyed_to():
    """The refusal above used to cover Paralyze too, and its reason has expired.

    "That player may pay {N}" is a production now (Chain Lightning needs it), so
    the line no longer refuses — and a decomposed ``may(pay, untap)`` would be
    the wrong reading twice over: "the creature" lowers to the **source**, which
    on an Aura is the Aura, and the upkeep step gathers this trigger by
    instruction kind, so the card would compile clean and never offer anything.
    The fused kind is what ``engine/phases/upkeep_effects.py`` is keyed to, and
    it is the one the card-name hook used to supply.
    """
    result = compile_line(
        "At the beginning of the upkeep of enchanted creature's controller, "
        "that player may pay {4}. If the player does, untap the creature.",
        card_name="Paralyze",
    )

    assert result.parsed
    assert [(i.kind, dict(i.payload)) for i in result.instructions] == [
        (
            "upkeep_pay_to_untap_enchanted",
            {"mana": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 4}},
        )
    ]


def test_black_vise_lowers_the_whole_count_including_the_minus_four():
    """"...where X is the number of cards in their hand minus 4."

    The count is named rather than derived, so the "minus 4" cannot be dropped.
    The pair ``("upkeep_chosen", "upkeep_chosen_player_hand_overflow_damage")``
    is registered; a plain ``deal_damage`` under ``upkeep_chosen`` is not, so
    reading this as an ordinary counted damage would compile cleanly and leave
    the card doing nothing at all.
    """
    assert _instructions(
        "At the beginning of the chosen player's upkeep, this artifact deals X damage "
        "to that player, where X is the number of cards in their hand minus 4.",
        "Black Vise",
    ) == [("upkeep_chosen_player_hand_overflow_damage", {"base": 4, "direction": "overflow"})]


def test_power_surge_binds_x_to_the_turn_start_land_count():
    """"...where X is the number of untapped lands they controlled at the
    beginning of this turn."

    ``amount: "x"`` is not a cast-time X here: the upkeep handlers read that
    exact value as the turn-start untapped-land count. Because that meaning
    lives in the handler rather than the payload, only a clause that names this
    count may lower to it -- an unnamed X must not.
    """
    assert _instructions(
        "At the beginning of each player's upkeep, this enchantment deals X damage to "
        "that player, where X is the number of untapped lands they controlled at the "
        "beginning of this turn.",
        "Power Surge",
    ) == [("deal_damage", {"amount": "x"})]


def test_a_where_x_count_on_the_upkeep_player_reads_the_seat_the_event_froze():
    """"…deals X damage to that player, where X is the number of Mountains
    **they** control", under "at the beginning of each player's upkeep".

    This test used to assert the opposite, and said so: "that player" is chosen
    by nobody, both spellings lower to the same ``recipient`` key, and the
    admission was gated on the *picker's* description — which only a real target
    has — so the line refused. That refusal was right about the danger and wrong
    about the answer: a count narrowed to a controller the matcher cannot test
    would be silently ignored, but "whose zone is scanned" is an axis the
    counter *does* read, and the seat is sitting in the trigger's frozen context
    under ``event_subject_player``.

    So the same move round 20 made for Jovial Evil's targeted spelling is made
    here for the untargeted one, gated on the event rather than on a picker:
    `_EVENT_SUBJECT_PLAYERS` is the table saying which conditions freeze a seat,
    and it is the table the damage recipient beside it already reads — so the
    count and the damage cannot land on two different players. A condition
    outside it still refuses, which the sibling test below keeps.

    Psychic Allergy is the card that asked: "at the beginning of each opponent's
    upkeep, this enchantment deals X damage to that player, where X is the
    number of nontoken permanents of the chosen color they control."
    """
    result = compile_line(
        "At the beginning of each player's upkeep, this enchantment deals X damage to "
        "that player, where X is the number of Mountains they control.",
        card_name="Test",
    )

    assert result.usable
    assert result.instructions[0].payload["recipient"] == "event_subject_player"
    assert result.instructions[0].payload["x_from_count"] == {
        "zone": "battlefield",
        "owner": "event_subject_player",
        "filter": {"subtype_filter": "mountain"},
    }


def test_a_where_x_count_on_that_player_refuses_under_an_event_with_no_seat():
    """The control on the test above: a condition that freezes **no** seat.

    "Whenever this creature blocks" records the blocked creature, not a player,
    so "that player" names nobody — and a count that fell back to the caster
    would scan the wrong battlefield while the card reported supported. The
    refusal is the whole point of keeping the admission table-driven rather
    than letting any trigger through.
    """
    result = compile_line(
        "Whenever this creature blocks, this creature deals X damage to "
        "that player, where X is the number of Mountains they control.",
        card_name="Test",
    )

    assert not result.usable


def test_karma_counts_swamps_through_the_dedicated_handler():
    """"...deals damage to that player equal to the number of Swamps they control."

    ``deal_damage_equal_to_swamps`` reads an empty payload and does the counting
    itself, against the player whose upkeep is resolving. Both halves are
    therefore checked at lowering -- what is counted and who is damaged.
    """
    assert _instructions(
        "At the beginning of each player's upkeep, this enchantment deals damage to "
        "that player equal to the number of Swamps they control.",
        "Karma",
    ) == [("deal_damage_equal_to_swamps", {})]


@pytest.mark.parametrize(
    "line",
    [
        # A different land type: the handler counts Swamps and nothing else.
        "This enchantment deals damage to that player equal to the number of "
        "Mountains they control.",
        # A different controller: the handler counts the upkeep player's Swamps,
        # not the Aura controller's.
        "This enchantment deals damage to that player equal to the number of "
        "Swamps you control.",
        # A different victim: the handler damages the upkeep player.
        "This enchantment deals damage to you equal to the number of Swamps "
        "they control.",
    ],
)
def test_counted_damage_refuses_anything_the_swamp_handler_does_not_compute(line):
    """Each of these parses cleanly and is a plausible near-miss. Lowering any
    of them onto ``deal_damage_equal_to_swamps`` would count the wrong objects
    or damage the wrong seat while the card still reported as supported."""
    result = compile_line(line, card_name="Test")

    assert result.parsed and not result.lowered


# ---------------------------------------------------------------------------
# "deals N damage to you unless you pay <cost>"
# ---------------------------------------------------------------------------


def test_force_of_nature_lowers_to_the_fused_upkeep_prompt():
    """An upkeep pay-or-else must stay fused.

    engine/phases/upkeep_effects.py dispatches on (condition, instruction kind)
    and its handler runs the whole prompt: offer the mana, and on a decline deal
    the damage. A decomposed ``may(pay) else deal_damage`` is a more faithful
    reading of the sentence and has no handler at all.
    """
    assert _instructions(
        "At the beginning of your upkeep, this creature deals 8 damage to you "
        "unless you pay {G}{G}{G}{G}.",
        "Force of Nature",
    ) == [
        (
            "upkeep_pay_or_deal_damage_to_controller",
            {"damage": 8, "mana": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 4, "C": 0, "generic": 0}},
        )
    ]


def test_hasran_ogress_lowers_to_the_optional_pay_prompt():
    """The same sentence under a combat trigger is a different flow.

    ``creature_attacks`` resolves through EFFECT_HANDLERS, where
    ``self_damage_unless_pay`` arms the pending optional-pay queue. The trigger
    -- not the clause -- is what picks between the two, which is why the event
    kind is threaded into lowering.
    """
    assert _instructions(
        "Whenever this creature attacks, it deals 3 damage to you unless you pay {2}.",
        "Hasran Ogress",
    ) == [("self_damage_unless_pay", {"amount": 3, "cost": 2})]


def test_a_pay_or_else_damage_clause_outside_a_trigger_refuses():
    """Both flows are trigger-resolution machinery. A spell line with this shape
    would queue a prompt nothing drains, so it refuses rather than lowering onto
    a handler that cannot reach it."""
    result = compile_line(
        "This creature deals 3 damage to you unless you pay {2}.", card_name="Test"
    )

    assert result.parsed and not result.lowered


def test_a_pay_or_else_damage_clause_on_the_wrong_upkeep_refuses():
    """Only ``("upkeep_self", "upkeep_pay_or_deal_damage_to_controller")`` is
    registered. Under "each player's upkeep" the same clause would compile
    cleanly onto no handler."""
    result = compile_line(
        "At the beginning of each player's upkeep, this creature deals 3 damage to you "
        "unless you pay {2}.",
        card_name="Test",
    )

    assert result.parsed and not result.lowered


def test_a_coloured_cost_refuses_outside_the_upkeep_prompt():
    """``self_damage_unless_pay`` puts a single generic number on the prompt, so
    a coloured cost lowered to it would be charged as {0} -- a free out for the
    controller and a card that never deals its damage."""
    result = compile_line(
        "Whenever this creature attacks, it deals 3 damage to you unless you pay {G}{G}.",
        card_name="Test",
    )

    assert result.parsed and not result.lowered


def test_cyclone_still_refuses_rather_than_decomposing_its_upkeep_prompt():
    """Guard on the guard: "sacrifice ... unless you pay {G} for each wind counter"
    is a pay-or-else too, but its cost scales with counters and its paid branch
    sweeps the board. ``upkeep_wind_counter_pay_or_sacrifice`` implements all of
    that, and nothing the grammar could assemble is keyed to it."""
    result = compile_line(
        "At the beginning of your upkeep, put a wind counter on this enchantment, then "
        "sacrifice this enchantment unless you pay {G} for each wind counter on it. If "
        "you pay, this enchantment deals damage equal to the number of wind counters on "
        "it to each creature and each player.",
        card_name="Cyclone",
    )

    assert not result.usable


# ---------------------------------------------------------------------------
# Pool-wide guards on the trigger seam
# ---------------------------------------------------------------------------


def _executed_trigger_lines(catalog):
    """Every (card, line, node, instructions) the grammar executes as a trigger."""
    from engine.grammar import ast as grammar_ast

    for card in catalog:
        for raw in (card.oracle_text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            result = compile_line(line, card_name=card.name)
            if not result.usable:
                continue
            if not isinstance(result.node, grammar_ast.TriggeredAbilityNode):
                continue
            yield card.name, line, result.node, result.instructions


def test_every_executed_trigger_agrees_with_the_legacy_condition_table(catalog):
    """The grammar's trigger kind must equal the legacy table's for the same line.

    engine/oracle.py takes the condition from ``WHENEVER/WHEN/AT_TRIGGER_PATTERNS``
    and only the effect from the grammar, so these two tables are not independent:
    the engine dispatches on the legacy kind, while the grammar's kind is what
    ``lower_ability`` checks when it refuses decomposed upkeep effects. If they
    disagree, the grammar guards one condition and the engine runs another.

    A legacy kind of None is the sharper failure: the line would count as
    executing through the grammar in GRAMMAR_COVERAGE.md while
    ``_parse_triggered_ability`` discarded the whole ability. That is the shape
    of false coverage this guard exists to make impossible.
    """
    from engine.oracle import trigger_condition_of_line

    disagreements = []
    for name, line, node, _lowered in _executed_trigger_lines(catalog):
        # Through the compiler's own reader, not a re-spelling of it: this
        # guard used to call `_parse_trigger_condition(normalize_creature_line(
        # line))`, which is `_parse_triggered_ability`'s first half with its
        # self-reference fallback dropped. Every pre-modern card that prints its
        # own name in the condition (Axelrod Gunnarson, Nicol Bolas) then read
        # as `legacy: None` — a disagreement invented by the guard, in exactly
        # the shape the guard exists to catch.
        condition, _ = trigger_condition_of_line(line, name)
        legacy = condition.kind if condition is not None else None
        if legacy != node.event.kind:
            disagreements.append(
                f"{name}: {line}\n    legacy: {legacy}  grammar: {node.event.kind}"
            )

    assert not disagreements, (
        "the grammar names a trigger condition the legacy table does not:\n"
        + "\n".join(disagreements)
    )


# Pairs dispatched by an upkeep scan that is not the UPKEEP_EFFECTS registry.
# It reaches state the registry's UpkeepContext does not carry -- a graveyard
# position -- so it reads its triggers directly in engine/phases/upkeep_step.py.
# It is not grammar-executed today; it is listed so this guard describes the
# real dispatch surface rather than only the part that happens to be exercised.
#
# The Aura decay pair used to be here too: a loop over every enchantment on
# every battlefield, keyed on one hard-coded instruction kind, reached by a
# card-name hook whose key spelled out "-1/-1". It is an ordinary
# ``@upkeep_effect("upkeep_enchanted_controller", "add_pt_counters_to_attached")``
# now, with the CR 122.1a pair as payload, so it belongs in the registry rather
# than on this list.
_UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY = frozenset({
    ("upkeep_self", "upkeep_return_self_from_graveyard"),
})


def test_every_executed_upkeep_trigger_lands_on_a_pair_something_dispatches(catalog):
    """The bug this catches has already shipped twice in this migration.

    Upkeep-family triggers used to resolve **only** through the registry: the
    upkeep step looked up ``(trigger condition kind, instruction kind)`` and did
    nothing at all when the pair was absent. So a trigger phrase plus a perfectly
    reasonable effect lowering could produce a card that compiles clean, reports
    as supported, and silently never fires.

    Round 134 gave those triggers the ordinary route (CR 603.3: on the stack,
    through EFFECT_HANDLERS), so there are now **three** ways a pair can be
    dispatched and the question is unchanged: is there any? The registry keeps
    the interactive pay-or-consequence shapes and is asked first; a kind
    EFFECT_HANDLERS answers takes the stack; the two below are read directly by
    the upkeep step. A pair in none of the three is still a card that compiles
    cleanly and does nothing, which is what this counts.
    """
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle import _parse_trigger_condition, normalize_creature_line
    from engine.phases.upkeep_effects import UPKEEP_EFFECTS

    assert not (_UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY & set(UPKEEP_EFFECTS)), (
        "a pair listed as dispatched outside the registry is now in it -- delete it here"
    )

    upkeep_conditions = {condition for condition, _ in UPKEEP_EFFECTS}
    dispatched = set(UPKEEP_EFFECTS) | _UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY
    from engine.phases.upkeep_step import _ORDINARY_UPKEEP_SEATS

    undispatched = []
    for name, line, _node, instructions in _executed_trigger_lines(catalog):
        condition, _ = _parse_trigger_condition(normalize_creature_line(line))
        if condition is None or condition.kind not in upkeep_conditions:
            continue
        for instruction in instructions:
            if (
                condition.kind in _ORDINARY_UPKEEP_SEATS
                and instruction.kind in EFFECT_HANDLERS
            ):
                continue
            if (condition.kind, instruction.kind) not in dispatched:
                undispatched.append(
                    f"{name}: {line}\n    pair: {(condition.kind, instruction.kind)}"
                )

    assert not undispatched, (
        "the grammar executes an upkeep trigger no handler is keyed to, so the "
        "card compiles cleanly and does nothing:\n" + "\n".join(undispatched)
    )


# ---------------------------------------------------------------------------
# Trigger conditions the grammar reads (land-tapping family)
#
# The same guard as the upkeep pair above, for the other trigger family the
# engine dispatches outside EFFECT_HANDLERS. ``Game.tap_land_for_mana`` runs
# `land_tapped_for_mana` triggers by hand — it must, because a triggered mana
# ability may not use the stack (CR 605.4a) — so an instruction kind it does
# not name compiles cleanly, reports supported, and never runs.
#
# `permanent_becomes_tapped` is the opposite case and is checked the other way
# round: it goes through the event bus onto the stack, so what it needs is an
# applicability filter (or every "whenever a <thing> becomes tapped" card fires
# on every tap) and a registered handler for its effect.
# ---------------------------------------------------------------------------

_LAND_TAPPED_FIRE_SITE_KINDS = frozenset({
    "add_mana_for_tapped_land",   # Mana Flare, Gauntlet of Might
    "deal_damage",                # Manabarbs
})


def test_every_land_tapped_for_mana_trigger_lands_on_a_kind_the_fire_site_runs(catalog):
    from engine.oracle import compile_card_oracle

    undispatched = []
    for card in catalog:
        for trig in compile_card_oracle(card).triggered_abilities:
            if trig.condition.kind != "land_tapped_for_mana" or trig.instruction is None:
                continue
            if trig.instruction.kind not in _LAND_TAPPED_FIRE_SITE_KINDS:
                undispatched.append(f"{card.name}: {trig.instruction.kind}")

    assert not undispatched, (
        "tap_land_for_mana dispatches these triggers by instruction kind and "
        "silently skips any kind it does not name:\n" + "\n".join(undispatched)
    )


def test_every_becomes_tapped_trigger_has_a_filter_and_a_handler(catalog):
    from engine.events import EVENT_FILTERS
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle import compile_card_oracle

    problems = []
    for card in catalog:
        for trig in compile_card_oracle(card).triggered_abilities:
            if trig.condition.kind != "permanent_becomes_tapped" or trig.instruction is None:
                continue
            if trig.condition.kind not in EVENT_FILTERS:
                problems.append(f"{card.name}: no event filter, so it fires on every tap")
            if trig.instruction.kind not in EFFECT_HANDLERS:
                problems.append(f"{card.name}: no handler for {trig.instruction.kind}")

    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# End-to-end: the lowerings above, resolved against real game state
#
# A payload golden proves the grammar emits what the legacy rules emitted. It
# cannot prove the pair reaches a handler, or that the handler computes what the
# clause says -- and both of those are how an upkeep trigger goes silently dead.
# These resolve the trigger and read the board.
# ---------------------------------------------------------------------------


def test_karma_damage_follows_the_upkeep_players_swamps_not_the_controllers(catalog_by_name):
    """The clause damages "that player" for "the number of Swamps they control",
    and both pronouns point at the player whose upkeep is resolving. Karma's own
    controller holding Swamps must change nothing."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    swamp = catalog_by_name["Swamp"]
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=catalog_by_name["Karma"]),
            Permanent(card=swamp),
            Permanent(card=swamp),
            Permanent(card=swamp),
        ],
        life=20,
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=swamp)], life=20)
    game = Game(players=[p1, p2])

    game.resolve_upkeep(1)

    assert p2.life == 19, "P2 controls one Swamp, so takes exactly 1"
    assert p1.life == 20, "Karma's controller is not the upkeep player"


def test_black_vise_deals_hand_size_minus_four(catalog_by_name):
    """Seven cards in hand is 3 damage, not 7. The subtraction lives only in the
    handler, so this is what proves the named count reached the right one."""
    from engine import Game, PlayerState

    island = catalog_by_name["Island"]
    p1 = PlayerState(name="P1", hand=[catalog_by_name["Black Vise"]])
    p2 = PlayerState(name="P2", hand=[island] * 7, life=20)
    game = Game(players=[p1, p2])

    assert game.cast_from_hand(0, "Black Vise", target_player_index=1).supported
    game.resolve_upkeep(1)

    assert p2.life == 17


def test_power_surge_damage_is_the_turn_start_untapped_land_count(catalog_by_name):
    """``amount: "x"`` means the turn-start untapped-land count *because the
    handler says so*. A land tapped going into the turn contributes nothing, so
    the count is 1 rather than 2 -- which no payload assertion can show."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    island = catalog_by_name["Island"]
    open_land = Permanent(card=island)
    tapped_land = Permanent(card=island)
    tapped_land.tapped = True
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=catalog_by_name["Power Surge"])])
    p2 = PlayerState(name="P2", battlefield=[open_land, tapped_land], life=20)
    game = Game(players=[p1, p2])
    game.untapped_lands_at_turn_start[1] = 1

    game.resolve_upkeep(1)

    assert p2.life == 19


def test_force_of_nature_declining_the_upkeep_cost_deals_eight(catalog_by_name):
    """The fused kind is what carries the decline branch. Had the clause
    decomposed into a ``may``, the upkeep step would have found no handler for
    the pair and the controller would take no damage at all."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=catalog_by_name["Force of Nature"])], life=20
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.resolve_upkeep(0, human_choices={"Force of Nature": False})

    assert p1.life == 12


def test_hasran_ogress_attack_offers_the_cost_before_dealing_damage(catalog_by_name):
    """``self_damage_unless_pay`` arms a prompt rather than dealing damage on
    the spot. Lowering the same clause to the upkeep kind would have produced no
    prompt and no damage, since nothing dispatches that pair on an attack."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    ogress = Permanent(card=catalog_by_name["Hasran Ogress"])
    ogress.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[ogress], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    game.declare_attackers(0, [0])
    game.resolve_stack()

    assert [entry["card_name"] for entry in game.pending_optional_pays] == ["Hasran Ogress"]

    game.auto_resolve_pending_optional_pays()

    assert p1.life == 17, "with no mana to pay {2}, the 3 damage lands"


# ---------------------------------------------------------------------------
# Activation costs (parsed, never lowered)
# ---------------------------------------------------------------------------


def test_counter_removal_cost_lets_its_effect_through():
    """Scavenging Ghoul's regeneration ability was unreachable through the
    grammar because of its *cost*, not its effect: "Remove a corpse counter
    from this creature" broke full consumption, so the whole line — a
    regeneration the grammar already knew how to lower — fell back to the
    legacy rules. The instruction is the one the legacy rule produces."""
    assert _instructions(
        "Remove a corpse counter from this creature: Regenerate this creature.",
        "Scavenging Ghoul",
    ) == [("grant_regeneration_to_self", {})]


def test_discard_last_drawn_cost_lets_its_effect_through():
    """Same shape for Jandor's Ring: the effect is a plain "Draw a card", and
    only the unusual third cost kept the line off the grammar."""
    assert _instructions(
        "{2}, {T}, Discard the last card you drew this turn: Draw a card.",
        "Jandor's Ring",
    ) == [("draw_controller_cards", {"amount": 1})]


def test_costs_never_become_instructions():
    """A cost is paid by mixins/stack/activation from ``ActivatedAbilityCost``,
    which the *legacy* compiler parses off the same line. If a cost also
    lowered to an instruction the ability would charge it twice — most visibly
    for Jandor's Ring, which would discard on activation and again on
    resolution."""
    for line, name in (
        ("Remove a corpse counter from this creature: Regenerate this creature.",
         "Scavenging Ghoul"),
        ("{2}, {T}, Discard the last card you drew this turn: Draw a card.",
         "Jandor's Ring"),
    ):
        kinds = [kind for kind, _payload in _instructions(line, name)]
        assert not any(
            word in kind for kind in kinds for word in ("discard", "remove_counter")
        ), kinds


def test_counter_removal_cost_records_the_counter_kind():
    """The kind is free text here, unlike ``put ... counter`` which restricts
    itself to the P/T kinds. The difference is consequences: a *put* lowers to
    a handler that only understands +1/+1, while a cost is recorded and never
    lowered, so CR 122.1's "a counter can have any name" holds."""
    from engine.grammar import ast

    node = compile_line(
        "Remove a corpse counter from this creature: Regenerate this creature.",
        card_name="Scavenging Ghoul",
    ).node
    assert node.costs == (ast.RemoveCounterCost("corpse", ast.Fixed(1)),)


def test_counter_removal_cost_needs_a_written_kind():
    """"Remove a counter from this creature" names no kind. Reading the head
    noun as the kind would invent a counter called "counter" and pay a cost the
    permanent may not carry."""
    result = compile_line(
        "Remove a counter from this creature: Regenerate this creature.", card_name="Test"
    )

    assert not result.parsed


def test_counter_removal_cost_refuses_a_subject_it_cannot_record():
    """``RemoveCounterCost`` has no subject field, so "from target creature"
    would be consumed and then silently read as the source's own counter."""
    result = compile_line(
        "Remove a corpse counter from target creature: Draw a card.", card_name="Test"
    )

    assert not result.parsed


def test_both_discard_costs_the_engine_charges_are_accepted():
    """Two costs, not two spellings of one: "the last card you drew this turn"
    names its card by history and leaves the payer no choice, while "a card"
    is the payer's pick. Both are collected on activation, so both parse; a
    counted "discard two cards" still refuses, because nothing charges it."""
    assert compile_line(
        "{2}, {T}, Discard the last card you drew this turn: Draw a card.",
        card_name="Jandor's Ring",
    ).parsed
    assert compile_line("Discard a card: Draw a card.", card_name="Test").parsed
    assert not compile_line("Discard two cards: Draw a card.", card_name="Test").parsed


def test_sacrifice_cost_distinguishes_the_source_from_a_chosen_permanent():
    """"Sacrifice this artifact" gives up a known permanent; "Sacrifice a
    creature" makes its controller choose one. The production used to consume
    the noun without looking at it, so both produced the same empty filter —
    which reads as "sacrifice any object" to anything that later lowers
    costs."""
    from engine.grammar import ast

    lotus = compile_line(
        "{T}, Sacrifice this artifact: Add three mana of any one color.",
        card_name="Black Lotus",
    ).node

    assert ast.SacrificeCost(
        ast.ObjectFilter(card_types=("artifact",), is_source=True)
    ) in lotus.costs
    # Diamond Valley's cost names a creature its controller chooses, so its
    # filter is the *opposite* of the Lotus's: a type with no `is_source`. Its
    # effect compiles too now ("equal to the sacrificed creature's toughness"
    # is a production, shared with Life Chisel), which is what makes the two
    # halves of this comparison a live pair rather than a parse against a
    # refusal.
    valley = compile_line(
        "{T}, Sacrifice a creature: You gain life equal to the sacrificed "
        "creature's toughness.",
        card_name="Diamond Valley",
    )
    assert valley.usable
    assert ast.SacrificeCost(
        ast.ObjectFilter(card_types=("creature",))
    ) in valley.node.costs


def test_exile_cost_refuses_anything_but_the_source():
    """``ExileSelf`` names no object. Exiling something else would be consumed
    and then read as the ability's own source leaving the battlefield."""
    assert compile_line(
        "{5}, {T}, Exile this artifact: Draw a card.", card_name="Ring of Maruf"
    ).parsed
    assert not compile_line(
        "{5}, {T}, Exile target creature: Draw a card.", card_name="Test"
    ).parsed


# ---------------------------------------------------------------------------
# Player-chosen mana colour
# ---------------------------------------------------------------------------


def test_any_colour_mana_carries_its_count():
    """How many is *data*. The handler used to probe the clause text for the
    literal "one mana of any color", which is why every other number had to
    refuse — the clause still rides along, because the colour injection in
    `mixins/stack/activation` and the AI's mana valuation both read it, but the
    number is now the payload's."""
    for name in ("Birds of Paradise", "City of Brass"):
        assert _instructions("{T}: Add one mana of any color.", name) == [
            (
                "add_mana_from_text",
                {
                    "oracle_text": "add one mana of any color",
                    "any_color": True,
                    "any_color_count": 1,
                },
            )
        ]


def test_three_mana_of_any_one_color_lowers_and_retires_a_hook():
    """Black Lotus. It kept a fused ``sacrifice_self_for_mana`` hook for exactly
    as long as the number had nowhere to go; the sacrifice is an ordinary
    activation cost and the mana is an ordinary instruction, so the decomposition
    is the card as printed and the hook is gone."""
    result = compile_line(
        "{T}, Sacrifice this artifact: Add three mana of any one color.",
        card_name="Black Lotus",
    )

    assert result.lowered, result.failure_reason
    (instruction,) = result.instructions
    assert instruction.payload["any_color_count"] == 3


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def test_the_hive_token_payload_matches_the_rule_it_replaces():
    """``create_token`` builds the whole token CardDefinition from this payload
    (engine/tokens.py), so the production is pure characteristic transcription.
    The em dash, the printed type order, and the *absence* of a ``colors`` key
    for a colourless token are all part of the contract the legacy rule
    established."""
    assert _instructions(
        "{5}, {T}: Create a 1/1 colorless Insect artifact creature token with flying "
        "named Wasp. (It can't be blocked except by creatures with flying or reach.)",
        "The Hive",
    ) == [
        (
            "create_token",
            {
                "name": "Wasp",
                "power": 1,
                "toughness": 1,
                "type_line": "Artifact Creature — Insect",
                "keywords": ("Flying",),
            },
        )
    ]


def test_a_coloured_multiple_token_carries_colours_and_a_count():
    """The optional keys appear only when the card states them, which is what
    keeps a single colourless token on the minimal payload above."""
    assert _instructions(
        "Create two 1/1 white Soldier creature tokens named Foot Soldier.", "Test"
    ) == [
        (
            "create_token",
            {
                "name": "Foot Soldier",
                "power": 1,
                "toughness": 1,
                "type_line": "Creature — Soldier",
                "colors": ("W",),
                "count": 2,
            },
        )
    ]


def test_an_unnamed_token_takes_its_cr_111_4_name():
    """CR 111.4: an unnamed token's name is its subtype(s) plus "Token" —
    "Bird Token", "Dwarf Berserker Token". One rule shared with the card
    hooks (``default_token_name``), because a token's name is what every
    "creatures named ..." effect reads."""
    for line, expected in (
        ("Create a 4/4 red Bird creature token with flying.", "Bird Token"),
        (
            "Create a 5/5 colorless Djinn artifact creature token with flying.",
            "Djinn Token",
        ),
    ):
        result = compile_line(line, card_name="Test")
        assert result.parsed and result.lowered, result.failure_reason
        assert result.instructions[0].payload["name"] == expected


def test_an_unnamed_token_with_no_subtype_refuses():
    """CR 111.4 builds the name from the subtypes; with none printed there is
    nothing to build from."""
    result = compile_line("Create a 2/2 white creature token.", card_name="Test")
    assert result.parsed and not result.lowered
    assert "no CR 111.4 name" in result.failure_reason


def test_a_non_creature_token_refuses():
    """``make_token_card`` always builds a creature card, so a type line with
    no creature type would reach the loader as something it cannot classify."""
    result = compile_line(
        "Create a 1/1 colorless Insect artifact token named Wasp.", card_name="Test"
    )

    assert result.parsed and not result.lowered


@pytest.mark.parametrize(
    ("line", "why"),
    [
        (
            "Create a 1/1 Insect artifact creature token named Wasp.",
            "no colour stated: an empty colors tuple already means colourless, so "
            "letting the word be absent would also let it be deleted with no change "
            "to the payload -- the dropped-rider shape the deletion probe flags",
        ),
        (
            "Create an X/Y colorless Insect creature token named Wasp.",
            "two different variables: the where-clause that follows such a "
            "sentence defines one X, so admitting a second would give the token "
            "a toughness nothing had stated. A single repeated variable is "
            "admitted since round 118 and reads the same X every other effect "
            "does -- the cast's, or the one a where-clause defines",
        ),
        (
            "Create a 1/1 legendary colorless Insect creature token named Wasp.",
            "a supertype has nowhere to go on CreateToken, so consuming it would "
            "drop it",
        ),
        (
            "Create a 1/1 colorless Blorb creature token named Wasp.",
            "an unknown subtype: the vocabulary is data, and a word outside it is a "
            "visible gap rather than something to skip",
        ),
    ],
)
def test_token_shapes_the_payload_cannot_carry_fail_loudly(line, why):
    """Each of these would otherwise put a token onto the battlefield carrying
    characteristics the card did not print."""
    assert not compile_line(line, card_name="Test").parsed, why



# ---------------------------------------------------------------------------
# Entry state (CR 614.1c) — lines a text-keyed sidecar performs as a permanent
# arrives, so there is no instruction and never will be
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, card",
    [
        ("This artifact enters tapped.", "Nevinyrral's Disk"),
        ("This artifact enters tapped.", "Time Vault"),
        ("As this artifact enters, choose an opponent.", "Black Vise"),
        ("As this enchantment enters, choose a color and an opponent.", "Jihad"),
        ("This creature enters with seven +1/+0 counters on it.", "Clockwork Beast"),
        ("This creature enters with X +1/+1 counters on it.", "Rock Hydra"),
        (
            "You may have this creature enter as a copy of any creature on the "
            "battlefield.",
            "Clone",
        ),
        (
            "You may have this enchantment enter as a copy of any artifact on the "
            "battlefield, except it's an enchantment in addition to its other types.",
            "Copy Artifact",
        ),
        ("You have no maximum hand size.", "Library of Leng"),
        ("You may spend white mana as though it were red mana.", "Sunglasses of Urza"),
        (
            "As this enchantment enters, you lose life equal to your life total.",
            "Lich",
        ),
    ],
)
def test_entry_state_lines_are_accounted_for_by_the_permanent_state_mixin(line, card):
    """These describe what a permanent looks like the moment it arrives, or a
    standing permission stamped on its controller then.
    ``mixins/permanent_state._initialize_permanent_state`` performs all of them
    by probing the permanent's own oracle text as it enters, before anything
    could resolve an instruction — so there is nothing to lower, and an
    instruction here would apply the effect a second time.

    If this stops holding the failure is a quiet one: the lines go back to
    reporting as unparsed backlog while the mixin keeps executing them, which is
    the misleading-backlog problem engine/grammar/registries.py exists to fix.
    """
    result = compile_line(line, card_name=card)

    assert result.parsed and result.lowered
    assert result.node.registry == "enter_effects"
    assert result.instructions == ()
    # No categories, so the legacy path still compiles the card unchanged and
    # the text those probes match on stays byte-identical.
    assert not result.usable


def test_entry_state_claims_stay_stricter_than_the_mixins_substring_probes():
    """The mixin asks "does this card mention entering as a copy anywhere?"; the
    claim asks "is that the whole line?".

    Vesuvan Doppelganger is why the difference matters. Its copy clause does
    fire in the mixin, but the granted upkeep ability trailing it is a card hook
    the mixin knows nothing about. A prefix match would report the whole line as
    understood on the strength of code that implements half of it.
    """
    from engine.enter_effects import enter_effect_line

    assert enter_effect_line("This artifact enters tapped.") is not None
    assert (
        enter_effect_line(
            "You may have this creature enter as a copy of any creature on the "
            "battlefield, except it doesn't copy that creature's color and it has "
            "a granted upkeep ability."
        )
        is None
    )
    # The mixin's own probe excludes a conditional wording ("unless"); so does a
    # whole-line claim, by construction.
    assert enter_effect_line("This artifact enters tapped unless you pay {3}.") is None


def test_the_entry_phrases_have_exactly_one_spelling():
    """The mixin and the grammar must read the *same* string, not two copies of
    it.

    A copied phrase is free to be renamed on one side only, and a renamed copy
    claims a line nothing performs — precisely the drift engine/enter_effects.py
    was extracted to prevent. Guarded mechanically rather than by convention: no
    entry phrase may appear as a string literal in the mixin.
    """
    import pathlib

    from engine import enter_effects

    mixin_source = (
        pathlib.Path(enter_effects.__file__).with_name("mixins") / "permanent_state.py"
    ).read_text(encoding="utf-8")
    for name in enter_effects.__all__:
        phrase = getattr(enter_effects, name)
        if not isinstance(phrase, str):
            continue
        assert f'"{phrase}"' not in mixin_source, name
        assert f"'{phrase}'" not in mixin_source, name


# ---------------------------------------------------------------------------
# Library search
# ---------------------------------------------------------------------------


def test_search_library_lowers_to_the_engines_one_card_search():
    """Byte-identical to what the legacy rule wrote. ``count`` is pinned at 1
    because ``confirm_search_library`` moves exactly one card however many the
    payload claims; it exists only because the UI displays it."""
    assert _instructions(
        "Search your library for a card, put that card into your hand, then shuffle.",
        "Demonic Tutor",
    ) == [("search_library", {"count": 1, "card_type": "any"})]


def test_a_typed_search_carries_the_type_the_picker_tests():
    """``choose_search_library_index`` compares the payload's ``card_type``
    against each library card's ``primary_type``, so a written type is a
    restriction the flow can honour rather than one it would ignore."""
    assert _instructions(
        "Search your library for a creature card, put that card into your hand, "
        "then shuffle.",
        "Test",
    ) == [("search_library", {"count": 1, "card_type": "creature"})]


@pytest.mark.parametrize(
    ("line", "why"),
    [
        (
            "Search target player's library for a card, put that card into your "
            "hand, then shuffle.",
            "the flow opens context.caster's library and no one else's, so this "
            "would search the wrong player's deck",
        ),
        (
            "Search your library for a black card, put that card into your hand, "
            "then shuffle.",
            "the picker tests one primary_type and nothing else, so a colour "
            "restriction would leave the player choosing from their whole library",
        ),
        (
            "Search your library for a creature, put that card into your hand, "
            "then shuffle.",
            "a library holds cards, not permanents (CR 400.1); dropping the head "
            "noun would make the phrase name something the zone cannot contain",
        ),
    ],
)
def test_search_shapes_the_flow_cannot_perform_refuse(line, why):
    """Each of these would report as supported while searching the wrong zone,
    finding the wrong card, or ignoring the restriction the card prints."""
    result = compile_line(line, card_name="Test")

    assert not result.usable, why


def test_search_to_battlefield_carries_its_destination():
    """"Search your library for a creature card, put it onto the battlefield,
    then shuffle." (Garruk, Unleashed's emblem.) The destination rides the
    payload — the confirm flow reads it, so a payload without it would tutor
    the card to the hand instead."""
    result = compile_line(
        "Search your library for a creature card, put it onto the battlefield, "
        "then shuffle.",
        card_name="Test",
    )

    assert result.usable
    assert result.instructions[0].kind == "search_library"
    assert result.instructions[0].payload["destination"] == "battlefield"


def test_the_search_is_singular_by_construction():
    """``ast.SearchLibrary`` has no count field and the confirm flow moves one
    card, so a plural search must fail in the parser rather than quietly find
    one card and report success."""
    result = compile_line(
        "Search your library for two cards, put that card into your hand, "
        "then shuffle.",
        card_name="Test",
    )

    assert not result.parsed


def test_the_searchs_shuffle_is_required():
    """``confirm_search_library`` shuffles as it moves the card, so the word is
    part of this effect. Making it optional would let it be *deleted* with no
    change to the payload — the dropped-rider shape the parse-coverage deletion
    probe flags."""
    result = compile_line(
        "Search your library for a card, put that card into your hand.",
        card_name="Test",
    )

    assert not result.parsed


# ---------------------------------------------------------------------------
# Discard — who picks the cards decides the handler
# ---------------------------------------------------------------------------


def test_a_random_discard_lowers_to_the_handler_that_discards_at_random():
    """Mind Twist. ``discard_x_target_cards`` takes the cards with
    ``random.sample`` and sizes itself from the X chosen as the spell was cast,
    so it reads nothing from the payload — which is why the payload carries no
    amount, matching the legacy rule byte for byte."""
    assert _instructions("Target player discards X cards at random.", "Mind Twist") == [
        ("discard_x_target_cards", {})
    ]


def test_a_chosen_discard_still_lowers_to_the_handler_that_prompts():
    """Disrupting Scepter's counted discard raises a pending choice and lets the
    discarding player pick. Keeping the two apart is the whole point of reading
    "at random"."""
    assert _instructions("Target player discards a card.", "Disrupting Scepter") == [
        ("discard_target_cards", {"amount": 1})
    ]


def test_a_fixed_count_discarded_at_random_uses_the_random_handler():
    """Gwendlyn Di Corci discards one at random, Mind Twist discards X. Who
    picks the cards is what separates the two handlers — nobody does, in both —
    so the count is payload on the random handler rather than a third kind."""
    assert _instructions(
        "Target player discards a card at random.", "Gwendlyn Di Corci"
    ) == [("discard_x_target_cards", {"amount": 1})]
    assert _instructions(
        "Target player discards two cards at random.", "Test"
    ) == [("discard_x_target_cards", {"amount": 2})]


def test_a_random_discard_from_a_seat_nobody_targeted_refuses():
    """"That player" names the seat a firing event recorded, and only the
    damage triggers record one. Under any other event the handler's target is a
    seat nobody chose, so the wrong hand would be emptied."""
    result = compile_line(
        "Whenever this creature attacks, that player discards a card at random.",
        card_name="Test",
    )

    assert result.parsed and not result.lowered


def test_a_variable_discard_that_is_not_random_refuses():
    """The mirror image: the only variable-count handler takes the cards at
    random, so lowering a chosen "discards X cards" onto it would take the
    choice away."""
    result = compile_line("Target player discards X cards.", card_name="Test")

    assert result.parsed and not result.lowered
    assert "at random" in result.failure_reason



def test_every_executed_end_step_trigger_lands_on_a_kind_the_step_enqueues(catalog):
    """The upkeep guard's twin, for the other step that dispatches triggers.

    ``resolve_end_step`` used to scan for a fixed set of instruction kinds and
    enqueue nothing at all for anything else — the silent-death failure this
    whole family of guards exists for. Gadrak, the Crown-Scourge is the card it
    cost, and the step answered with a **catch-all**: after the four keyed
    scans, everything else with an end-step condition is enqueued too.

    So "is this kind on a list?" can no longer fail, and asking it would only
    produce false alarms. What is left to check is the half the catch-all does
    not settle — that the enqueued instruction has somewhere to *run*. A trigger
    put on the stack with a kind ``EFFECT_HANDLERS`` does not answer dies just as
    quietly as one that was never enqueued.
    """
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle import compile_card_oracle
    from engine.phases.end_step import (
        END_STEP_CONDITIONS,
        END_STEP_DISPATCHED_KINDS,
        END_STEP_INTERVENING_IF,
    )

    # Read the **fused** instruction, which is what the step is actually handed.
    # This used to walk `compile_line`'s unfused list, and that is how Sabertooth
    # Mauler got past it: its line lowers to two instructions that each carry the
    # CR 603.4 gate, so the guard saw a healthy card, while `engine/oracle.py`
    # wrapped them in a `sequence` and the step saw one gateless object it never
    # enqueued. A guard that reads a different object from its dispatcher is
    # checking a card nobody plays.
    undispatched = []
    for card in catalog:
        for trig in compile_card_oracle(card).triggered_abilities:
            if not trig.supported or trig.instruction is None:
                continue
            # Both scopes, read from the step's own set: "your end step" is a
            # separate condition kind, and hardcoding one here would silently
            # stop covering Erg Raiders — the only shipped card that has one.
            if trig.condition.kind not in END_STEP_CONDITIONS:
                continue
            instruction = trig.instruction
            # The payload-shape scan dispatches on the *gate*, whatever the kind
            # (see END_STEP_INTERVENING_IF's own comment) — so a gated trigger is
            # dispatched by construction and the kind list has nothing to say
            # about it. Without this the guard flags healthy cards, which is why
            # it could only ever be run somewhere they do not exist.
            if instruction.payload.get(END_STEP_INTERVENING_IF) is not None:
                continue
            # A kind one of the four keyed scans handles is dispatched by
            # that scan, with the trigger context or the re-checked guard it
            # needs; everything else goes through the catch-all and then
            # through EFFECT_HANDLERS like any other resolving object.
            if (
                instruction.kind not in END_STEP_DISPATCHED_KINDS
                and instruction.kind not in EFFECT_HANDLERS
            ):
                undispatched.append(
                    f"{card.name}: {trig.source_line}\n    kind: {instruction.kind}"
                )

    assert not undispatched, (
        "an end-step trigger is enqueued with a kind nothing resolves, so "
        "the card compiles cleanly and does nothing:\n" + "\n".join(undispatched)
    )


@pytest.mark.parametrize(
    ("line", "card", "expected"),
    [
        (_SCAVENGING_GHOUL, "Scavenging Ghoul",
         ("add_corpse_counters_for_each_creature_died", {})),
        (_KHABAL_GHOUL, "Khabál Ghoul",
         ("add_plus1_counters_for_each_creature_died", {"power": 1, "toughness": 1})),
    ],
)
def test_per_death_counters_match_the_rules_they_replace(line, card, expected):
    """Byte-for-byte with the two legacy substring rules.

    If a payload drifts here the handler keeps running but reads a key that is
    no longer there: ``add_plus1_counters_for_each_creature_died`` sizes its
    counters from ``power``/``toughness``, so a missing pair puts down counters
    of a different size while the card still reports as supported.
    """
    assert _instructions(line, card) == [expected]


def test_the_per_death_clause_is_what_picks_the_scaling_handler():
    """Delete "for each creature that died this turn" and the *instruction*
    must change.

    This is the race the legacy registry had to win by hand: its per-death rule
    carries a comment saying it must out-rank the plain "put a +1/+1 counter on
    this creature" rule, 96,500 order slots away. Losing that race puts down one
    counter instead of one per death -- a smaller effect, silently. Here the
    tail is a node, so if this assertion ever fails the clause has become
    droppable again.
    """
    scaled = _instructions(
        "Put a +1/+1 counter on this creature for each creature that died this turn.",
        "Khabál Ghoul",
    )
    plain = _instructions("Put a +1/+1 counter on this creature.", "Khabál Ghoul")

    assert scaled == [("add_plus1_counters_for_each_creature_died",
                       {"power": 1, "toughness": 1})]
    assert plain == [("add_counter_to_self", {"power": 1, "toughness": 1})]
    assert scaled != plain


def test_a_per_death_clause_without_this_turn_is_not_claimed():
    """The engine's death tally resets every turn, so "that died" over any other
    window is a different number. Letting the words be optional would also let
    them be deleted with no change to the payload -- the dropped-rider shape the
    parse-coverage deletion probe flags."""
    assert not compile_line(
        "Put a +1/+1 counter on this creature for each creature that died.",
        card_name="Khabál Ghoul",
    ).parsed


@pytest.mark.parametrize(
    ("line", "why"),
    [
        (
            "Put a +1/+1 counter on this creature for each Goblin that died this turn.",
            "both handlers count every creature that died and read no filter, so a "
            "narrowed set would be executed as though it were unnarrowed",
        ),
        (
            "Put a +1/+1 counter on target creature for each creature that died this turn.",
            "both handlers put counters on the ability's own source; a chosen "
            "target would be ignored and the source would grow instead",
        ),
        (
            "Put two +1/+1 counters on this creature for each creature that died this turn.",
            "neither handler multiplies, so the second counter per death would "
            "simply not appear",
        ),
        (
            "Put a wind counter on this creature for each creature that died this turn.",
            "nothing places wind counters per death; Cyclone's counters go down "
            "one per upkeep, through a handler of its own",
        ),
    ],
)
def test_per_death_counter_shapes_without_a_handler_refuse(line, why):
    """Each of these parses -- the grammar reads it in full -- and then refuses,
    because the handler it would otherwise reach takes an empty payload and so
    would ignore exactly the part that makes the clause different."""
    result = compile_line(line, card_name="Test")
    assert result.parsed, why
    assert not result.lowered, why


def test_a_named_counter_kind_still_has_to_be_written_out():
    """Reading the head noun as the kind would invent a counter called
    "counter", and defaulting to +1/+1 would invent the wrong one on every card
    that uses any other kind."""
    assert not compile_line(
        "Put a counter on this creature for each creature that died this turn.",
        card_name="Test",
    ).parsed


def test_per_death_counters_reach_the_pair_the_end_step_dispatches(catalog_by_name):
    """The payload golden cannot show that the trigger fires.

    End-step triggers do not resolve through EFFECT_HANDLERS: ``resolve_end_step``
    looks for a specific set of instruction kinds under the ``end_step``
    condition and enqueues nothing at all otherwise. So a lowering onto any
    other kind -- including a decomposed ``for_each`` -- would leave both Ghouls
    compiling cleanly, reporting as supported, and never gaining a counter.
    """
    from engine import Game, PlayerState
    from engine.models import Permanent

    ghoul = Permanent(card=catalog_by_name["Khabál Ghoul"])
    ghoul.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[ghoul], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.creatures_died_this_turn = 2
    game.active_player_index = 0

    game.resolve_end_step(0)
    game.resolve_stack()

    assert (ghoul.effective_power, ghoul.effective_toughness) == (3, 3)


def test_corpse_counters_reach_the_pair_the_end_step_dispatches(catalog_by_name):
    """Same seam, the other counter kind. Scavenging Ghoul's corpse counters are
    the fuel its regeneration ability spends, so a trigger that never fires
    leaves the card with an ability it can never pay for."""
    from engine import Game, PlayerState
    from engine.models import Permanent

    ghoul = Permanent(card=catalog_by_name["Scavenging Ghoul"])
    ghoul.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[ghoul], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.creatures_died_this_turn = 3
    game.active_player_index = 0

    game.resolve_end_step(0)
    game.resolve_stack()

    assert ghoul.metadata.get("corpse_counters") == 3


# ---------------------------------------------------------------------------
# "Draw N cards, then discard M cards"
# ---------------------------------------------------------------------------


def test_draw_then_discard_matches_the_rule_it_replaces():
    """Bazaar of Baghdad. Both counts ride on the payload, so this golden is
    what stops the pair being swapped or one of them being defaulted -- a
    ``discard`` of 1 would make the card strictly better than printed."""
    assert _instructions("Draw two cards, then discard three cards.", "Bazaar of Baghdad") == [
        ("draw_then_discard_self", {"draw": 2, "discard": 3})
    ]


def test_draw_then_discard_reads_both_counts_rather_than_hardcoding_them():
    """The production has to be parameterised, or it is the legacy substring
    rule wearing a grammar hat."""
    assert _instructions("Draw a card, then discard a card.", "Test") == [
        ("draw_then_discard_self", {"draw": 1, "discard": 1})
    ]


def test_draw_then_discard_refuses_a_random_discard():
    """``draw_then_discard_self`` raises a prompt and lets the controller pick
    which cards go. A random discard is a different effect, and claiming it
    would silently hand the choice back to the player."""
    result = compile_line("Draw two cards, then discard three cards at random.", card_name="Test")

    assert result.parsed
    assert not result.lowered


def test_the_fusion_checks_who_discards_rather_than_matching_the_shape():
    """The pair only fuses when *both* halves belong to the effect's controller.

    ``draw_then_discard_self`` empties the controller's own hand, so a
    Draw-then-Discard whose discarder is someone else must stay decomposed —
    fusing on the node shape alone would make a targeted discard empty the
    caster's hand instead of the target's.
    """
    assert _instructions(
        "Draw two cards, then target player discards three cards.", "Test"
    ) == [
        ("draw_controller_cards", {"amount": 2}),
        ("discard_target_cards", {"amount": 3}),
    ]


# ---------------------------------------------------------------------------
# "...as long as <condition>" -- continuous abilities (CR 613, roadmap phase 6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "card"),
    [
        ("This creature gets +1/+1 as long as you control a Swamp.", "Sedge Troll"),
        ("This creature gets +1/+2 as long as you control a Forest.", "Kird Ape"),
        ("This creature gets +0/+3 as long as it's untapped.", "Giant Tortoise"),
    ],
)
def test_as_long_as_lines_parse_as_conditional_statics(line, card):
    """These three used to fail as "unconsumed text", which reads as a parser
    gap when the real blocker is the CR 613 layers engine.

    The node type is the assertion that matters. An ``ast.Conditional`` would
    lower to ``if_then``: tested once on resolution, then permanent. "As long
    as" means the bonus exists exactly while the condition does, so reading one
    as the other gives a Kird Ape that keeps +1/+2 after its Forest is
    destroyed.
    """
    from engine.grammar import ast as grammar_ast

    result = compile_line(line, card_name=card)

    assert result.parsed
    assert isinstance(result.node, grammar_ast.StaticAbilityNode)
    assert result.node.condition is not None
    assert not isinstance(result.node.effect, grammar_ast.Conditional)
    # Recorded in a shape phase 6 can lower, not as raw text.
    assert not isinstance(result.node.condition, grammar_ast.RawCondition)


def test_as_long_as_lines_stay_unlowered_and_unusable():
    """Nothing may execute through the grammar here. The engine runs these cards
    off the compiler's static-line path (``conditional_land_bonus``); if this
    ever started lowering, the bonus would be applied twice or by the wrong
    mechanism."""
    result = compile_line(
        "This creature gets +1/+1 as long as you control a Swamp.", card_name="Sedge Troll"
    )

    assert not result.lowered
    assert not result.usable
    # The refusal now names what actually carries the line, rather than a phase
    # that turned out not to be blocking it — and says *which* conditional
    # bonuses the table carries, since round 27 gave the grammar the ones whose
    # condition is about an opponent's board (Beasts of Bogardan) and left every
    # condition about your own board here.
    assert result.failure_reason == (
        "a conditional static bonus about your own board is derived by "
        "engine/static_bonuses.py"
    )


def test_an_as_long_as_condition_the_grammar_cannot_model_is_not_claimed():
    """The ``as long as`` production still refuses Jihad's condition, and what
    claims the line instead carries the condition rather than dropping it.

    The *reason* for the refusal moved. It used to be the noun parser: "a
    nontoken permanent **of the chosen color**" was outside its vocabulary, so
    `_parse_condition` failed on unconsumed words. Psychic Allergy's "nontoken
    permanents of the chosen color they control" put that phrase in, and the
    production would then have claimed this line and refused it a layer later
    at `statics._lower_anthem_condition` — which is the one failure
    ``parse_line``'s derivation-table fallback cannot recover from, since it
    only fires on a *parse* refusal. So the production gates on the phrase
    directly: a colour recorded on one permanent as it entered (CR 614.1c) is
    not something a continuous buff's condition can be evaluated against.

    Both halves matter. Claiming the line *without* the condition would report a
    card as understood while its whole restriction had gone missing, which is
    what the production refusing prevents. The line is nonetheless accounted
    for, by ``engine/lord_buffs.py`` through ``engine/grammar/derived.py``: that
    table is the code ``_recalculate_lord_buffs`` dispatches on, so the
    condition in the payload is the one the board is evaluated against.
    """
    from engine.grammar import ast as grammar_ast
    from engine.grammar.parser import _parse_static_condition_line
    from engine.grammar.lexer import tokenize
    from engine.grammar.stream import TokenStream

    line = (
        "White creatures get +2/+1 as long as the chosen player controls a "
        "nontoken permanent of the chosen color."
    )
    lexed = tokenize(line, card_name="Jihad")
    assert _parse_static_condition_line(TokenStream(lexed.tokens, line)) is None

    result = compile_line(line, card_name="Jihad")
    assert isinstance(result.node, grammar_ast.DerivedLine)
    assert result.node.table == "lord_buffs"
    assert result.instructions[0].payload["condition"] == "chosen_color_permanent"


def test_an_as_long_as_condition_no_table_models_is_refused_outright():
    """The other half of the same rule: a condition neither the grammar nor
    ``engine/lord_buffs.CONDITIONS`` models takes the whole line down.

    A near miss on Jihad's own wording, so it is the *condition* being unknown
    that decides it and nothing else. This is what stops the derivation-table
    fallback becoming a way to claim any "as long as" sentence: the table
    refuses an unmodelled condition rather than deriving an unconditional anthem
    from it.
    """
    result = compile_line(
        "White creatures get +2/+1 as long as the chosen player controls a "
        "nontoken permanent of the chosen type.",
        card_name="Test",
    )

    assert not result.parsed


def test_as_long_as_never_claims_a_one_shot_effect():
    """The production is gated on the effect being continuous. A duration makes
    it a one-shot, which is a different card shape and must fall through to the
    ordinary sentence path rather than being recorded as a static ability."""
    from engine.grammar import ast as grammar_ast

    result = compile_line(
        "This creature gets +1/+1 until end of turn as long as you control a Swamp.",
        card_name="Test",
    )

    assert not isinstance(result.node, grammar_ast.StaticAbilityNode)


# ---------------------------------------------------------------------------
# Keyword lines separated by a semicolon
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "card", "expected"),
    [
        ("Trample; banding (Any creatures with banding.)", "War Elephant",
         ("trample", "banding")),
        ("Flying; banding (Any creatures with banding.)", "Mesa Pegasus",
         ("flying", "banding")),
    ],
)
def test_semicolon_separated_keyword_lines_are_keyword_lines(line, card, expected):
    """Magic switches from commas to semicolons once a keyword carries reminder
    text, and the lexer strips the reminder while leaving the semicolon. Without
    this the line is reported as missing a *subject*, which points at nothing
    that exists and hides two cards in the largest backlog bucket."""
    from engine.grammar import ast as grammar_ast

    result = compile_line(line, card_name=card)

    assert isinstance(result.node, grammar_ast.KeywordLine)
    assert tuple(keyword.name for keyword in result.node.keywords) == expected
    # A keyword line carries no instructions, so nothing here changes behaviour.
    assert result.instructions == ()
    assert not result.usable


def test_a_semicolon_does_not_join_two_effect_sentences_into_keywords():
    """The separator only holds a keyword line together. A semicolon between
    real sentences must still leave the line to the sentence loop, or an effect
    would be swallowed as an unrecognized keyword."""
    from engine.grammar import ast as grammar_ast

    result = compile_line("Destroy target creature; draw a card.", card_name="Test")

    assert not isinstance(result.node, grammar_ast.KeywordLine)


# ---------------------------------------------------------------------------
# Productions taken over from the "expected a subject" backlog
#
# Each of these replaces a legacy @parse_rule, so the golden is the payload that
# rule produced -- byte for byte, because the handlers read these keys by name.
# The refusals beside them are the point of the exercise: every one names a
# wording the handler does *not* implement, which is what stops the production
# becoming the substring match it replaced.
# ---------------------------------------------------------------------------


def test_damage_trigger_discard_matches_the_rule_it_replaces():
    """Hypnotic Specter. The handler reads the damaged player out of the
    trigger's captured context and takes no payload at all."""
    assert _instructions(
        "Whenever this creature deals damage to an opponent, "
        "that player discards a card at random.",
        "Hypnotic Specter",
    ) == [("opponent_discards_random_card_on_damage", {})]


def test_damage_trigger_discard_needs_a_trigger_that_records_a_damaged_player():
    """The same sentence on any other trigger names a player nobody recorded,
    so the handler would discard nothing while the card reported as supported."""
    result = compile_line(
        "Whenever this creature attacks, that player discards a card at random.",
        card_name="Test",
    )

    assert result.parsed
    assert not result.lowered


def test_damage_trigger_discard_still_has_to_be_at_random():
    """"At random" is what picks the handler, not a rider either could carry.

    Without it the victim chooses which card goes, which is
    ``discard_target_cards`` -- so the random reading must not claim the
    sentence merely because the trigger matches."""
    assert _instructions(
        "Whenever this creature deals damage to an opponent, that player discards a card.",
        "Test",
    ) == [("discard_target_cards", {"amount": 1})]


def test_removing_a_counter_matches_the_rule_it_replaces():
    """Armageddon Clock. The counter's name is payload -- the accumulating side
    (``upkeep_put_counter_on_self``) reads the same key, so the pair is one
    template rather than a card."""
    assert _instructions(
        "{4}: Remove a doom counter from this artifact. "
        "Any player may activate this ability but only during any upkeep step.",
        "Armageddon Clock",
    ) == [("remove_counter_from_self", {"counter": "doom"})]


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Remove two doom counters from this artifact.", "decrements by exactly one"),
        ("Remove a doom counter from target artifact.", "reads its own source"),
    ],
)
def test_counter_removal_shapes_without_a_handler_refuse(line, why):
    result = compile_line(line, card_name="Test")

    assert result.parsed, why
    assert not result.lowered, why


def test_remove_does_not_claim_the_other_sentences_that_start_with_it():
    """"Remove target creature ... from combat" and "remove all damage marked on
    it" open the same way and are entirely different effects. They have to keep
    failing on their own missing production, not on a counter kind they never
    mentioned.

    The two refuse at different *stages* now, and the stage is not what this
    guards. Once "defending player controls" became a noun-phrase narrowing the
    parser reads (Floral Spuzzem, LEG round 32), the first line parses whole
    and refuses in lowering, by the name of its own production — which is the
    same claim, made one layer later. The second still has no production at all.
    What must stay true of both is that neither is *lowered*, and that neither
    blames the counter-removal reading they merely share an opening word with.
    """
    unlowerable = (
        "Remove target creature defending player controls from combat.",
        "The next time target land would be destroyed this turn, "
        "remove all damage marked on it instead.",
    )
    for line in unlowerable:
        result = compile_line(line, card_name="Test")
        assert not result.lowered, line
        assert "counter" not in (result.failure_reason or ""), line

    combat = compile_line(unlowerable[0], card_name="Test")
    assert combat.parsed
    assert combat.failure_reason == (
        "remove-from-combat acts on the object the sentence already chose"
    )
    damage = compile_line(unlowerable[1], card_name="Test")
    assert not damage.parsed
    assert damage.failure_reason == "expected a subject"


@pytest.mark.parametrize(
    ("line", "card", "mode"),
    [
        ("Change the text of target spell or permanent by replacing all "
         "instances of one basic land type with another.", "Magical Hack", "land_type"),
        ("Change the text of target spell or permanent by replacing all "
         "instances of one color word with another.", "Sleight of Mind", "color_word"),
    ],
)
def test_text_change_reads_the_swapped_vocabulary_as_payload(line, card, mode):
    """The two printings are one sentence with one word changed, which is what
    makes the vocabulary payload rather than part of the effect's name."""
    assert _instructions(line, card) == [("mark_text_modified", {"mode": mode})]


def test_a_text_change_the_engine_cannot_perform_is_not_claimed():
    """``mark_text_modified`` substitutes land types and colour words. A card
    naming a third vocabulary would reach it as a mode it ignores."""
    result = compile_line(
        "Change the text of target spell or permanent by replacing all "
        "instances of one creature type with another.",
        card_name="Test",
    )

    assert not result.parsed


def test_text_change_describes_no_target():
    """The Lace cycle's rule: the ``targets`` vocabulary cannot say "a spell on
    the stack *or* a permanent", so describing it at all would drop one of the
    two zones from the picker. ``engine/legality.py`` keeps answering."""
    result = compile_line(
        "Change the text of target spell or permanent by replacing all "
        "instances of one color word with another.",
        card_name="Sleight of Mind",
    )

    assert result.instructions[0].payload == {"mode": "color_word"}


def test_linked_control_matches_the_rule_it_replaces():
    """Aladdin. ``steal_target_permanent_linked_to_self`` takes no payload --
    it finds the artifact itself and ends the control change from
    ``ON_LEAVE_BATTLEFIELD``."""
    assert _instructions(
        "{1}{R}{R}, {T}: Gain control of target artifact for as long as you "
        "control this creature.",
        "Aladdin",
    ) == [("steal_target_permanent_linked_to_self", {})]


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Gain control of target artifact.",
         "an untimed steal is a permanent control change, not this one"),
        ("Gain control of target creature for as long as you control this creature.",
         "the handler looks for an artifact in its own source"),
    ],
)
def test_control_changes_without_the_linked_duration_refuse(line, why):
    result = compile_line(line, card_name="Test")

    assert not result.usable, why


def test_exile_with_the_controller_life_gain_matches_the_rule_it_replaces():
    """Swords to Plowshares. Fused because the handler is: it reads the power of
    the creature it has just removed from the battlefield, which no pair of
    independent instructions can do."""
    assert _instructions(
        "Exile target creature. Its controller gains life equal to its power.",
        "Swords to Plowshares",
    ) == [("exile_creature_gain_life_equal_to_power", {})]


def test_a_bare_exile_is_the_plain_exile_and_not_the_fused_one():
    """"Exile target creature." now has a handler of its own. It must not reach
    ``exile_creature_gain_life_equal_to_power``, which performs *both* halves of
    Swords to Plowshares' sentence and would gain life the card never offered."""
    result = compile_line("Exile target creature.", card_name="Test")

    assert result.lowered, result.failure_reason
    assert [i.kind for i in result.instructions] == ["exile_target_permanent"]


@pytest.mark.parametrize(
    "line",
    [
        "Exile target artifact. Its controller gains life equal to its power.",
        "Exile target creature. You gain life equal to its power.",
    ],
)
def test_exile_shapes_the_fused_handler_does_not_implement_refuse(line):
    """The fusion checks who gains the life and what was exiled; a mismatch
    refuses rather than lowering onto a handler that does something else."""
    result = compile_line(line, card_name="Test")

    assert result.parsed
    assert not result.lowered


def test_exile_with_an_unimplemented_duration_still_refuses():
    """The dangerous fall-through: an exile carrying a duration the
    until-end-of-turn branch does not name must not land on the *permanent*
    exile, which would never give the card back."""
    result = compile_line(
        "Exile target creature until this creature leaves the battlefield.",
        card_name="Test",
    )

    assert "exile_target_permanent" not in [i.kind for i in result.instructions]


def test_delayed_destroy_matches_the_rule_it_replaces():
    """Thicket Basilisk and Cockatrice -- two cards, one sentence, so the
    production earns its place over a per-card entry."""
    assert _instructions(
        "Whenever this creature blocks or becomes blocked by a non-Wall "
        "creature, destroy that creature at end of combat.",
        "Cockatrice",
    ) == [("delayed_destroy_blocked_or_blocker", {})]


def test_delayed_destroy_needs_the_trigger_that_binds_the_blocking_pair():
    """The handler destroys the creature this one blocked or was blocked by,
    which is a fact only that trigger knows."""
    result = compile_line(
        "Whenever this creature blocks, destroy that creature at end of combat.",
        card_name="Test",
    )

    assert result.parsed
    assert not result.lowered


def test_a_destroy_delayed_to_the_end_step_is_not_claimed():
    """Stone Giant and Nettling Imp defer to the next end step, which is a
    different handler. Refusing the line is what keeps them from being
    destroyed a combat early.

    The refusal moved a layer down when Infinite Authority taught the delay
    table "at the beginning of the next end step": the opener is read now, so
    the sentence *parses* — and then refuses to lower, because "that creature"
    under a delay that binds no object names nothing at all. Which layer says
    no does not matter; that one does is the whole property.
    """
    result = compile_line(
        "Destroy that creature at the beginning of the next end step.",
        card_name="Test",
    )

    assert not result.usable
    assert result.lowering_error


# ---------------------------------------------------------------------------
# Milling (CR 701.13a)
# ---------------------------------------------------------------------------

def test_target_player_mills_a_spelled_out_count():
    assert _instructions("Target player mills two cards.", card_name="Millstone") == [
        ("mill_target_player", {"amount": 2})
    ]


def test_target_player_mills_one_card():
    """The singular noun is the same production, not a second rule with a
    hand-picked precedence — which is what the count being an ordinary amount
    buys."""
    assert _instructions("Target player mills a card.", card_name="Test") == [
        ("mill_target_player", {"amount": 1})
    ]


@pytest.mark.parametrize(
    "line,recipient",
    [
        ("You mill three cards.", "caster"),
        ("Each opponent mills two cards.", "each_opponent"),
    ],
)
def test_a_mill_names_its_miller_on_the_payload(line, recipient):
    """The miller rides the same ``recipient`` key damage and life loss use.
    Absent still means the spell's target, so Millstone's payload is
    unchanged; naming it is what lets a bare "mill four cards" mill its own
    controller instead of whoever happened to be targeted."""
    result = compile_line(line, card_name="Test")

    assert result.lowered, result.failure_reason
    assert result.instructions[0].kind == "mill_target_player"
    assert result.instructions[0].payload["recipient"] == recipient


def test_a_mill_whose_miller_no_handler_names_still_refuses():
    """"Each player mills a card" would compile cleanly onto the handler and
    mill whoever happened to be targeted, so it refuses by name rather than
    guessing — the reason this lowering refused everything to begin with."""
    result = compile_line("Each player mills a card.", card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert "cannot mill" in result.failure_reason


# ---------------------------------------------------------------------------
# The pay-to-untap upkeep trigger (Mana Vault, Brass Man, Island Fish Jasconius)
# ---------------------------------------------------------------------------

def test_upkeep_pay_to_untap_lowers_to_the_fused_kind():
    """The upkeep dispatcher is keyed on (condition, instruction kind) and this
    handler implements the whole prompt, so the decomposed `may(pay, untap)` a
    faithful reading would produce has nowhere to go."""
    assert _instructions(
        "At the beginning of your upkeep, you may pay {4}. If you do, untap this artifact.",
        card_name="Mana Vault",
    ) == [
        (
            "upkeep_pay_to_untap_self",
            {"mana": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 4}},
        )
    ]


def test_upkeep_pay_to_untap_carries_a_coloured_cost():
    """Island Fish Jasconius pays {U}{U}{U}. The generic ``may`` lowering
    refuses a coloured optional cost — rightly, since its prompt cannot charge
    one — so this shape has to be recognized before the statement is lowered,
    not after."""
    assert _instructions(
        "At the beginning of your upkeep, you may pay {U}{U}{U}. If you do, untap this creature.",
        card_name="Island Fish Jasconius",
    ) == [
        (
            "upkeep_pay_to_untap_self",
            {"mana": {"W": 0, "U": 3, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}},
        )
    ]


def test_the_pay_to_untap_shape_is_name_agnostic():
    """One production, not three cards: an invented permanent printed with the
    same sentence gets the same instruction."""
    assert _instructions(
        "At the beginning of your upkeep, you may pay {2}. If you do, untap this enchantment.",
        card_name="Invented Clock",
    ) == [
        (
            "upkeep_pay_to_untap_self",
            {"mana": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 2}},
        )
    ]


def test_upkeep_pay_to_untap_reads_a_foreign_subject_as_a_decomposed_trigger():
    """The fused ``upkeep_pay_to_untap_self`` handler untaps ``ctx.permanent``
    and takes no target, so untapping anything else must not land on it.

    This used to be a refusal — the whole line failed, because a decomposed
    upkeep trigger had nowhere to run. It now lowers to the wrapper it is and
    takes the ordinary route (CR 603.3). What the guard holds is unchanged and
    is the part that mattered: the fused kind is what would untap the wrong
    permanent, and this line does not produce it.
    """
    result = compile_line(
        "At the beginning of your upkeep, you may pay {4}. If you do, untap target creature.",
        card_name="Test",
    )

    assert result.parsed and result.lowered
    assert [i.kind for i in result.instructions] == ["may"]
    assert "upkeep_pay_to_untap_self" not in repr(result.instructions)


def test_a_pay_to_untap_on_another_trigger_is_not_the_fused_kind():
    """The registry entry is (``upkeep_self``, ``upkeep_pay_to_untap_self``).
    The same sentence under a different trigger reaches no handler keyed to that
    pair, so it must not borrow this one's kind — it takes the ordinary
    decomposed reading, which the triggered-ability resolution path executes."""
    result = compile_line(
        "At the beginning of your end step, you may pay {4}. If you do, untap this artifact.",
        card_name="Test",
    )

    assert [instruction.kind for instruction in result.instructions] == ["may"]


def test_a_narrowed_trigger_reads_the_same_subject_on_both_sides():
    """The two front ends turn one printed phrase into one filter.

    ``engine/oracle.py`` takes a trigger's *condition* from its regex table and
    ``engine/grammar/`` takes the *effect*, so a narrowed condition is read
    twice — once by a regex that only delimits the noun phrase, once by the noun
    parser itself. Both go through ``parse_subject_filter``, and this is what
    holds them to it: a regex that approximated the subject would let the
    dispatcher test one set while the grammar claimed another, and the card
    would compile with its two halves disagreeing about which creatures it
    watches.

    The comparison is over the trigger *head* rather than the whole line on
    purpose. A card whose effect the grammar refuses (Terror of the Peaks) is
    honestly unsupported for that reason, and it is still worth knowing that
    the head it does read means the same thing on both sides.
    """
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.grammar.lexer import tokenize
    from engine.grammar.lowering._common import _filter_payload
    from engine.grammar.triggers import _parse_trigger_event
    from engine.grammar.stream import TokenStream
    from engine.oracle import _parse_trigger_condition, normalize_creature_line

    checked = 0
    disagreements = []
    # Measured sets included, as the coverage instruments include them: this
    # asks whether the two readers agree about text the engine can see, and
    # every printing of this family today is in M21.
    for card in load_cards(manifest_set_paths(include_measured=True)):
        for line in (card.oracle_text or "").splitlines():
            condition, _ = _parse_trigger_condition(normalize_creature_line(line))
            if condition is None:
                continue
            described = {
                key[: -len("_filter")]: value
                for key, value in condition.payload.items()
                if key.endswith("_filter")
            }
            if not described:
                continue
            lexed = tokenize(line, card_name=card.name)
            event = _parse_trigger_event(TokenStream(lexed.tokens, line))
            subject = getattr(event, "subject", None)
            if subject is None:
                disagreements.append(
                    f"{card.name}: {line}\n    the table read a subject, the grammar did not"
                )
                continue
            checked += 1
            # A condition may delimit more than one noun phrase: "a creature
            # spell that doesn't share a color with **a creature you control**"
            # (Invoke Prejudice) names the set the trigger fires on *and* the
            # set it is compared against. Those are paired by the stem the
            # table's `_subject` group gave them; whatever `_filter` key is left
            # over is the subject, and that is what `TriggerEvent.subject` has
            # to match. Pairing by name is the point — a grammar that consumed
            # the extra phrase and recorded nothing would leave the dispatcher
            # testing a narrowing the parse claimed it had read.
            named = dict(getattr(event, "narrowings", ()) or ())
            for stem, filt in named.items():
                if stem not in described:
                    disagreements.append(
                        f"{card.name}: {line}\n    the grammar read a {stem!r} "
                        "narrowing the table did not"
                    )
                elif _filter_payload(filt) != described[stem]:
                    disagreements.append(
                        f"{card.name}: {line}\n    table {stem}:   {described[stem]}"
                        f"\n    grammar {stem}: {_filter_payload(filt)}"
                    )
            # Deduplicated by value: a `_pair_subject` group fans one printed
            # phrase out to two keys on purpose ("blocks or becomes blocked by
            # a non-Wall creature" describes both halves of one relation), and
            # two keys holding the same filter are still one subject.
            remaining = []
            for stem, value in described.items():
                if stem not in named and value not in remaining:
                    remaining.append(value)
            if len(remaining) > 1:
                disagreements.append(
                    f"{card.name}: {line}\n    the table read {len(remaining)} "
                    "unnamed subjects; the grammar has one"
                )
            elif remaining and _filter_payload(subject) != remaining[0]:
                disagreements.append(
                    f"{card.name}: {line}\n    table:   {remaining[0]}"
                    f"\n    grammar: {_filter_payload(subject)}"
                )
    assert not disagreements, (
        "the two front ends read one printed subject differently:\n"
        + "\n".join(disagreements)
    )
    assert checked, "no card in the pool exercises a subject-filtered trigger"


def test_several_cards_from_a_graveyard_carry_the_same_narrowing_as_one():
    """"Up to two target artifact cards" is the one-card payload plus a count.
    The two arities build their payload through one function on purpose: a
    second copy is how the several-card branch ends up returning a creature for
    a line that says artifact."""
    one = compile_line(
        "Return target artifact card from your graveyard to your hand.", card_name="Test"
    )
    several = compile_line(
        "Return up to two target artifact cards from your graveyard to your hand.",
        card_name="Test",
    )

    assert one.lowered and several.lowered
    assert one.instructions[0].payload == {"any_card": False, "card_type": "artifact"}
    assert several.instructions[0].payload == {
        "any_card": False,
        "card_type": "artifact",
        "targets": {"quantifier": "up_to", "kind": "card", "count": 2},
    }


def test_a_several_card_return_refuses_a_narrowing_the_handler_cannot_test():
    """The several path reads the same two payload keys as the one-card path, so
    an adjective invisible to both refuses the line rather than returning any two
    creature cards — and the refusal names the restriction, not the arity."""
    result = compile_line(
        "Return up to two target black creature cards from your graveyard to your hand.",
        card_name="Test",
    )

    assert result.parsed
    assert not result.lowered
    assert "restriction" in result.failure_reason


def test_several_cards_to_the_battlefield_still_has_no_handler():
    """Only the graveyard→hand handler reads a list. The reanimator resolves one
    chosen index, so the arity is refused there rather than silently reanimating
    the first of two."""
    result = compile_line(
        "Return up to two target creature cards from your graveyard to the battlefield.",
        card_name="Test",
    )

    assert result.parsed
    assert not result.lowered


def test_several_cards_from_any_graveyard_still_has_no_handler():
    """"From a graveyard" is a different search, at either arity."""
    result = compile_line(
        "Return up to two target creature cards from a graveyard to your hand.",
        card_name="Test",
    )

    assert result.parsed
    assert not result.lowered

def test_a_trigger_subject_refuses_a_restriction_the_payload_cannot_carry():
    """A restriction that leaves no key behind is invisible to the
    ``TESTABLE_SUBJECT_FILTER_KEYS`` gate over the payload, so the AST is asked
    first: ``_restrictions_beyond`` names a field the payload does not carry,
    and the condition refuses rather than announcing itself on a strictly larger
    set than the card prints.

    Round 68 found the hole one layer down (a graveyard-scoped noun phrase
    compiling into a battlefield picker) and paired the two gates. Supertypes
    were the worked example until round 108 gave them a key and a matcher, so
    the example that still refuses here is ``is_enchanted``, which has neither.
    """
    from engine.grammar import subject_filter_payload

    assert subject_filter_payload("a creature you control") == {
        "type_filter": "creature", "controller": "you",
    }
    # Carried, since round 108 - read off the type line (CR 205.4a).
    assert subject_filter_payload("a legendary creature you control") == {
        "type_filter": "creature", "controller": "you",
        "supertypes": ["legendary"],
    }
    assert subject_filter_payload("a snow creature you control") == {
        "type_filter": "creature", "controller": "you", "supertypes": ["snow"],
    }
    # Still nothing behind it: "enchanted" is a relation to an Aura, not a
    # property of the object, and no payload key names one.
    assert subject_filter_payload("an enchanted creature") is None


def test_a_supertype_narrowed_trigger_carries_the_word_into_its_condition():
    """The same hole, as a card, now closed at the source.

    On the round-68 engine this compiled *supported* with
    ``attacker_filter={'type_filter': 'creature', 'controller': 'you'}`` and
    gained life off a plain 2/2 attacking; from then until round 108 it refused,
    which was correct but bought no card. It is now admitted **with** the word,
    so what the trigger fires on is what the line prints."""
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_creature_card

    program = compile_card_oracle(_mk_creature_card(
        "Legend Watcher", 2, 2,
        "Whenever a legendary creature you control attacks, you gain 1 life.",
    ))

    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    described = trigger.condition.payload.get("attacker_filter")
    assert described == {
        "type_filter": "creature", "controller": "you",
        "supertypes": ["legendary"],
    }, "admitting the line without the word is the round-68 bug returning"


def test_a_sentences_only_target_reads_another_as_the_source_exclusion():
    """"**Another** target creature you control gains indestructible until end
    of turn." (Selfless Savior.)

    CR 601.2c lets two instances of the word "target" name the same object
    unless something forbids it, and "another" is that forbidding — it points at
    whatever the sentence already chose. When the sentence chooses nothing else,
    the only object left to point at is the ability's source (CR 109.5), which
    is the restriction ``exclude_self`` already names. So the word survives into
    the payload as the *same* key the postmodifier spelling ("target creature
    other than this creature") produces, and one picker and one handler read
    both."""
    (_kind, payload), = _full_payloads(
        "Another target creature you control gains indestructible until end of turn.",
        "Selfless Savior",
    )

    assert payload["targets"] == {
        "quantifier": "target",
        "kind": "object",
        "filter": {
            "type_filter": "creature", "controller": "you", "exclude_self": True,
        },
    }


@pytest.mark.parametrize(
    "line",
    [
        # The word behind the first choice ...
        "Target creature gets +1/+1 until end of turn. Another target creature "
        "gains flying until end of turn.",
        # ... and in front of it: the order does not change what is missing.
        "Target creature gains flying until end of turn. Another target creature "
        "gets +1/+1 until end of turn.",
        # Two of them, neither with a slot to differ from.
        "Another target creature gains flying until end of turn and another "
        "target creature gains trample until end of turn.",
    ],
)
def test_another_target_refuses_when_no_lowering_has_a_slot_per_clause(line):
    """The other meaning, and why the translation above may not be applied
    blindly. Two clauses naming two chosen objects need an instruction with a
    slot each — every other handler resolves through ``_one_choice``, which
    reads the *first* entry of the target list, so both clauses would land on
    one permanent. Read as the source exclusion instead, the word would name a
    restriction the card never printed.

    The first of these compiled **supported** on the round-70 engine, with the
    word dropped entirely and both clauses on one creature."""
    result = compile_line(line, card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert "slot per clause" in (result.failure_reason or "")


def test_the_two_slot_lowerings_keep_the_distinctness_they_can_carry():
    """The refusal above is positioned *after* the fusers, so the two lowerings
    that do have a slot per clause are untouched — and neither of them turns the
    word into a source exclusion, because a spell has no source permanent and
    the restriction is between the two slots."""
    (_kind, rookie), = _full_payloads(
        "Until end of turn, target creature gets +0/+2 and another target "
        "creature gets -2/-0.",
        "Rookie Mistake",
    )
    assert rookie["targets"]["distinct"] is True
    assert all("exclude_self" not in f for f in rookie["targets"]["filters"])

    (_kind, garruk), = _full_payloads(
        "Target creature you control deals damage equal to its power to another "
        "target creature.",
        "Garruk, Savage Herald",
    )
    assert garruk["targets"]["filters"] == [
        {"type_filter": "creature", "controller": "you"},
        {"type_filter": "creature"},
    ]


# ---------------------------------------------------------------------------
# "with the same name as one another" — a relation, not a property
# ---------------------------------------------------------------------------


def test_a_shared_name_relation_without_its_threshold_is_refused():
    """"Two or more permanents with the same name as one another" bounds the
    largest same-name group. Strip the number and the payload downstream reads
    as "count > 0", which one permanent satisfies — the opposite of what the
    words say. No card prints it bare, so lowering refuses rather than inventing
    the threshold the text did not print."""
    from engine.grammar import ast
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    def gate(comparison):
        return ast.TriggeredAbilityNode(
            ast.TriggerEvent("enters_battlefield", "when"),
            ast.Draw(ast.PlayerRef("you"), ast.Fixed(1)),
            ast.Controls(
                ast.PlayerRef("you"),
                ast.ObjectFilter(),
                comparison,
                shared_name=True,
            ),
        )

    (lowered,) = lower_ability(gate(ast.Comparison("ge", ast.Fixed(2))))
    assert lowered.payload["intervening_if"]["shared_name"]

    with pytest.raises(LoweringError):
        lower_ability(gate(None))


# ---------------------------------------------------------------------------
# "A or B" — one action, two ways to take it
# ---------------------------------------------------------------------------


def test_an_alternative_that_is_not_one_instruction_has_no_mode():
    """A mode payload carries a single instruction, so an option that lowers to
    several would be silently truncated — a branch the player picks and then only
    half gets."""
    from engine.grammar import ast
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_statement

    node = ast.OneOf(
        (
            ast.Draw(ast.PlayerRef("you"), ast.Fixed(1)),
            ast.Sequence((
                ast.Draw(ast.PlayerRef("you"), ast.Fixed(1)),
                ast.Draw(ast.PlayerRef("you"), ast.Fixed(1)),
            )),
        ),
        ("draw a card", "draw two cards one at a time"),
    )
    with pytest.raises(LoweringError):
        lower_statement(node)


def test_a_narrowed_discard_carries_exactly_what_the_prompt_can_test():
    """The discard effect and the discard *cost* run through one gate, so what
    the prompt offers and what the payment accepts cannot disagree.

    "Discard a **legendary** card" was the refusal side of that gate until round
    108 gave the supertype a key and a matcher. The refusal side is now a phrase
    with no matcher at all: a card in a hand is not tapped, because CR 613.1
    applies the layers to permanents and the question does not reach it."""
    assert compile_line("Discard a creature card.").instructions[0].payload["filter"] == {
        "type_filter": "creature"
    }
    assert compile_line("Discard a legendary card.").instructions[0].payload["filter"] == {
        "supertypes": ["legendary"]
    }
    result = compile_line("Discard a tapped creature card.")
    assert result.parsed and not result.lowered


def test_up_to_one_without_target_is_not_a_cast_time_target():
    """"Up to one **target** creature" is chosen at cast (CR 601.2c); "up to
    one creature" prints no "target" and so is a resolution choice (CR 608.2d).
    The parser records the word — this holds the *lowering* to reading it,
    because a spec that treated the two spellings alike would raise a cast-time
    picker in front of a choice the card defers, and the deletion probe found
    exactly that on seven cards."""
    from engine.grammar import compile_line

    targeted = compile_line("put a +1/+1 counter on up to one target creature.")
    assert targeted.lowered
    [instruction] = targeted.instructions
    assert instruction.payload["targets"]["quantifier"] == "up_to"

    untargeted = compile_line("put a +1/+1 counter on up to one creature.")
    assert not untargeted.lowered, (
        "an 'up to one' that prints no 'target' must refuse rather than be "
        "read as targeted"
    )


# ---------------------------------------------------------------------------
# The hand-shortfall count: the threshold is data, not part of the phrase
# ---------------------------------------------------------------------------


_HAND_COUNT = (
    "this artifact deals x damage to that player, where x is {clause}"
)


@pytest.mark.parametrize(
    "clause,direction,base",
    [
        # Black Vise's printed order, and the only one the phrase table used to
        # hold — with the 4 spelled into it.
        ("the number of cards in their hand minus 4", "overflow", 4),
        ("the number of cards in their hand minus 7", "overflow", 7),
        # The Rack's, and Storm World's. This direction had a working handler
        # branch and no way for the grammar to reach it, so The Rack was a
        # name-keyed card hook purely because its number was 3.
        ("3 minus the number of cards in their hand", "deficit", 3),
        ("4 minus the number of cards in their hand", "deficit", 4),
        ("9 minus the number of cards in their hand", "deficit", 9),
    ],
)
def test_the_hand_shortfall_threshold_is_payload(clause, direction, base):
    """One arithmetic, two printed orders, any threshold.

    Written with numbers no real card prints on purpose: a test that named only
    4 and 3 would pass against the version that matched the literal token "4",
    which is the shape that made every other threshold compile *unsupported* —
    the false-negative failure `engine/land_animation.py` documents, in a second
    place.
    """
    compiled = compile_line(_HAND_COUNT.format(clause=clause))

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.kind == "upkeep_chosen_player_hand_overflow_damage"
    assert instruction.payload["direction"] == direction
    assert instruction.payload["base"] == base


def test_a_bare_hand_count_is_not_the_shortfall():
    """No threshold, no shortfall.

    The bare count is a real and different quantity — an ordinary zone count,
    which the general evaluator already answers — so the risk here is not that
    it refuses but that the *threshold* rows above swallow it and hand the
    shortfall handler no base to subtract against. It must come out the other
    door.
    """
    compiled = compile_line(
        "this artifact deals x damage to that player, where x is the number of "
        "cards in their hand"
    )

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.kind == "deal_damage"
    assert instruction.payload["x_from_count"] == {
        "zone": "hand", "owner": "owner", "filter": {},
    }
    assert "base" not in instruction.payload


# ---------------------------------------------------------------------------
# A block trigger binds "that creature" only when it names one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,binds",
    [
        # Narrowed: CR 509.3d fires once for each creature the phrase admits, so
        # the firing is about exactly one and "that creature" is that one.
        ("Whenever this creature blocks a creature, destroy that creature at "
         "end of combat.", True),
        ("Whenever this creature becomes blocked by a Wall, destroy that Wall "
         "at end of combat.", True),
        ("Whenever this creature blocks or becomes blocked by a non-Wall "
         "creature, destroy that creature at end of combat.", True),
        # Bare: CR 509.3c fires **once** however many creatures are involved,
        # so the pronoun names no one of them. The fire site would hand the
        # handler an arbitrary pick — `blockers[:1]` — which is worse than a
        # refusal because the card would look as though it resolved.
        ("Whenever this creature blocks, destroy that creature at end of "
         "combat.", False),
        ("Whenever this creature becomes blocked, destroy that creature at end "
         "of combat.", False),
    ],
)
def test_a_block_trigger_binds_that_creature_only_when_it_names_one(line, binds):
    """The narrowing, not the kind, is what decides.

    Both spellings of each pair are the *same* trigger kind, so a gate reading
    the kind alone has to pick one answer for both — and picking either is wrong
    for the other half of the table. It had picked "bind" for becomes-blocked
    (admitting the bare form) and "refuse" for blocks (costing Infernal Medusa
    its first line), which is one bug in each direction at once.
    """
    result = compile_line(line, card_name="Test")

    assert result.parsed, result.parse_error
    assert result.lowered is binds, result.lowering_error
    if binds:
        assert result.instructions[0].kind == "delayed_destroy_blocked_or_blocker"


# ---------------------------------------------------------------------------
# A printed "or" between state adjectives is a union of any of them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase,expected",
    [
        # The pair the four Legends pingers print, and the one the parser used
        # to spell out.
        ("attacking or blocking", ["attacking", "blocking"]),
        ("blocking or attacking", ["blocking", "attacking"]),
        # Tetsuo Umezawa's, which matched nothing while the pair was hardcoded.
        ("tapped or blocking", ["tapped", "blocking"]),
        # Invented, and deliberately: a test naming only the two real printings
        # passes against the version that matched those two literally, which is
        # the false-negative shape `engine/land_animation.py` documents.
        ("untapped or attacking", ["untapped", "attacking"]),
        ("tapped or attacking or blocked", ["tapped", "attacking", "blocked"]),
    ],
)
def test_a_state_union_carries_the_words_it_printed(phrase, expected):
    compiled = compile_line(f"Destroy target {phrase} creature.", card_name="Test")

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload["any_states"] == expected


def test_a_lone_state_adjective_is_not_a_union():
    """"Target tapped creature" narrows by one field, which the matcher tests
    on its own — routing it through the union would be a second answer to the
    same question."""
    compiled = compile_line("Destroy target tapped creature.", card_name="Test")

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload.get("tapped_only") is True
    assert "any_states" not in instruction.payload


# ---------------------------------------------------------------------------
# A printed "or" between a card type and a subtype is one union across two axes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase,expected",
    [
        # Avoid Fate and Ring of Immortals, the printing this exists for.
        ("instant or Aura", [["card_type", "instant"], ["subtype", "aura"]]),
        # Invented, and deliberately: a rule matching the pair above literally
        # would pass a test that only named it. What the union is made of is
        # payload, exactly as a colour list or a state pair is.
        ("sorcery or Equipment", [["card_type", "sorcery"], ["subtype", "equipment"]]),
        (
            "instant or sorcery or Aura",
            [["card_type", "instant"], ["card_type", "sorcery"], ["subtype", "aura"]],
        ),
    ],
)
def test_a_class_union_crossing_two_axes_carries_both(phrase, expected):
    compiled = compile_line(f"Counter target {phrase} spell.", card_name="Test")

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload["any_classes"] == expected
    # Never split across the two fields it straddles: every matcher ANDs them,
    # so "an instant that is also an Aura" is a set nothing is in.
    assert "card_types" not in instruction.payload
    assert "subtype_filter" not in instruction.payload


def test_a_single_axis_union_is_not_a_class_union():
    """"instant or sorcery" lives on one axis and the type key already means
    "any of these" — routing it through the cross-axis form would be a second
    answer to a question that already has one."""
    compiled = compile_line("Counter target instant or sorcery spell.", card_name="Test")

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload["card_types"] == ["instant", "sorcery"]
    assert "any_classes" not in instruction.payload


def test_a_class_union_must_name_a_spell():
    """Without the printed "spell" the phrase names a permanent, and the word
    would be droppable — the dropped-rider shape the deletion probe reports."""
    compiled = compile_line("Counter target instant or Aura.", card_name="Test")

    assert not compiled.lowered


def test_a_counter_narrowed_by_what_its_target_chose():
    """"…that targets a permanent you control" — a restriction on the chosen
    spell's own targets, carried as a nested filter the handler tests."""
    compiled = compile_line(
        "Counter target spell that targets a permanent you control.", card_name="Test"
    )

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload["targets_filter"] == {"controller": "you"}


def test_a_counter_refuses_a_target_narrowing_nothing_can_test():
    """The narrowing is the whole card, so an inner phrase the matcher cannot
    answer refuses the line rather than countering more widely than it says."""
    compiled = compile_line(
        "Counter target spell that targets a creature blocking this creature.",
        card_name="Test",
    )

    assert not compiled.lowered


# ---------------------------------------------------------------------------
# "Counter that spell" is a bound reference; "instead" is the replacement
# ---------------------------------------------------------------------------


def test_counter_that_spell_is_bound_not_a_replacement():
    """Invoke Prejudice prints the words about the spell its own *trigger*
    bound, with no earlier sentence at all. Reading "that spell" as Lofty
    Denial's replacement amount made that construction unreachable."""
    compiled = compile_line(
        "Counter that spell unless that player pays {3}.", card_name="Test"
    )

    assert compiled.lowered, compiled.failure_reason
    [instruction] = compiled.instructions
    assert instruction.payload["bound_to_trigger"] is True
    assert instruction.payload["unless_pays_amount"] == 3


def test_a_replacement_amount_with_nothing_to_replace_refuses():
    """"…pays {4} **instead**" on its own replaces an amount no sentence named.
    Lowering it as an ordinary counter would print a card that asks for one
    amount where it says two."""
    compiled = compile_line(
        "Counter that spell unless its controller pays {4} instead.", card_name="Test"
    )

    assert not compiled.lowered


def test_instead_is_refused_on_a_chosen_target():
    """A counter that picks its own spell has no earlier amount to replace."""
    compiled = compile_line(
        "Counter target spell unless its controller pays {4} instead.", card_name="Test"
    )

    assert not compiled.lowered


# ---------------------------------------------------------------------------
# Target roles (round 34): a sentence naming two targets of different kinds.
# ---------------------------------------------------------------------------

_R34_ROLES_LINE = (
    "Put X glyph counters on target creature that target Wall blocked this "
    "turn, where X is the power of that blocked creature."
)


def test_r34_a_dependent_noun_phrase_lowers_to_ordered_roles():
    """The Wall is role 0 and the creature role 1 — **dependency** order, not
    the printed order — because which creatures are legal is decided by the
    Wall, and a picker asked in printed order has no way to narrow."""
    compiled = compile_line(_R34_ROLES_LINE)
    assert compiled.usable, compiled.failure_reason
    payload = compiled.instructions[0].payload
    assert payload["subject_role"] == "subject"
    assert payload["targets"] == {
        "kind": "roles",
        "roles": [
            {
                "role": "blocker", "kind": "object", "count": 1,
                "filter": {"type_filter": "creature", "subtype_filter": "wall"},
            },
            {
                "role": "subject", "kind": "object", "count": 1,
                "filter": {"type_filter": "creature"},
                "blocked_by_role": "blocker",
            },
        ],
    }


def test_r34_the_where_clause_names_which_role_it_reads():
    """"the power of **that blocked creature**" — a sentence with two targets
    cannot be asked for "the target"."""
    payload = compile_line(_R34_ROLES_LINE).instructions[0].payload
    assert payload["x_from_count"]["object_characteristic"]["role"] == "subject"


@pytest.mark.parametrize(
    "line,reason",
    [
        # A bare "its" over two targets does not say which — refused rather
        # than resolved against whichever slot came first.
        (
            "Put X glyph counters on target creature that target Wall blocked "
            "this turn, where X is its power.",
            "does not say which",
        ),
        # A referent naming neither role.
        (
            "Put X glyph counters on target creature that target Wall blocked "
            "this turn, where X is the power of that blocked artifact.",
            "no single target role",
        ),
    ],
)
def test_r34_an_unresolvable_where_clause_referent_refuses(line, reason):
    compiled = compile_line(line)
    assert not compiled.usable
    assert reason in (compiled.failure_reason or "")


def test_r34_the_other_role_is_reachable_by_its_own_printed_words():
    """The referent is matched, not guessed: "that Wall" reads the blocker."""
    line = (
        "Put X glyph counters on target creature that target Wall blocked this "
        "turn, where X is the power of that Wall."
    )
    payload = compile_line(line).instructions[0].payload
    assert payload["x_from_count"]["object_characteristic"]["role"] == "blocker"


# ---------------------------------------------------------------------------
# The damage riders have to reach a handler that reads them
# ---------------------------------------------------------------------------


_SWEEP_WITH_RIDER = (
    "This spell deals 2 damage to each creature. If it's a creature, it can't "
    "be regenerated this turn."
)


def test_a_damage_rider_that_reaches_no_handler_refuses():
    """"…it can't be regenerated this turn" / "…if it would die this turn,
    exile it instead" (CR 701.19c, CR 614) are folded onto the damage node by
    the sentence loop, and only ``deal_damage`` reads them.

    Every other branch of the damage lowering builds its **own** payload dict —
    a board sweep, a narrowed creature sweep, a bound set, a fused two-target
    bite — and each of them dropped both keys on the floor. Nothing raised: the
    sentence parsed, the branch never looked at the riders, and the card
    compiled *supported* dealing damage that any regeneration still answers.
    Only the multi-recipient split had noticed, and it guarded itself alone.

    So the check is a post-condition on the lowered result rather than a line
    in each branch, and this is the half that matters: a branch added later is
    covered without anyone remembering it.
    """
    from engine.grammar import ast
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_statement
    from engine.grammar.parser import parse_line

    statement = parse_line(_SWEEP_WITH_RIDER, card_name="Probe").statement
    assert statement.riders.no_regen, "the rider is on the node the branch ignored"

    with pytest.raises(LoweringError, match="no_regen"):
        lower_statement(statement)


def test_the_single_target_damage_rider_still_carries():
    """The other direction of the same guard: where a handler *does* read the
    keys, they arrive. Without this the post-condition above could be satisfied
    by refusing every rider."""
    (lowered,) = compile_line(
        "This spell deals 3 damage to any target. It can't be regenerated.",
        card_name="Probe",
    ).instructions

    assert lowered.kind == "deal_damage"
    assert lowered.payload["no_regen"] is True


def test_the_noun_form_of_the_damage_rider_is_the_same_rider():
    """"**A creature dealt damage this way** can't be regenerated this turn"
    (Incinerate) is CR 701.19c written about the effect rather than about a
    pronoun — the damage twin of "A creature destroyed this way can't be
    regenerated" — so it sets the one key both spellings set rather than
    minting a second channel for the same sentence."""
    (lowered,) = compile_line(
        "This spell deals 3 damage to any target. A creature dealt damage this "
        "way can't be regenerated this turn.",
        card_name="Probe",
    ).instructions

    assert lowered.kind == "deal_damage"
    assert lowered.payload["no_regen"] is True
