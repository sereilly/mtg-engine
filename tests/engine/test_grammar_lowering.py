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
        assert payload["while"] == qualifier, line
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
        ("grant_target_flying_until_eot", {})
    ]
    assert _instructions("{R}: This creature gains flying until end of turn.") == [
        ("grant_self_flying_until_eot", {})
    ]


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
    sequence."""
    assert _instructions("You may pay {1}. If you do, you gain 1 life.") == [
        (
            "may",
            {
                "actor": "you",
                "cost": 1,
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
    result = compile_line("You may pay {1}. If you do, you gain 1 life.")
    assert result.usable
    assert result.categories == frozenset({"optional"})


def test_a_free_optional_action_lowers_to_its_own_handler():
    """"You may draw a card" — no cost, so the offer is unconditional but the
    draw still is not."""
    assert _instructions("You may draw a card.") == [
        ("may", {"actor": "you", "action": (
            OracleInstruction("draw_controller_cards", "", {"amount": 1}),
        )})
    ]


def test_you_draw_and_target_player_draws_use_different_handlers():
    """They are separate handlers with different drawers, not one handler with
    a flag — lowering "you may draw a card" to the targeted one drew for the
    wrong player."""
    assert _instructions("Draw a card.")[0][0] == "draw_controller_cards"
    assert _instructions("Target player draws 2 cards.")[0][0] == "draw_target_cards"


def test_back_reference_without_a_producer_is_refused():
    """El-Hajjâj's "you gain that much life" reads the *trigger's* captured
    event, not this resolution's scratchpad. Lowering it as a scratchpad read
    would silently gain zero life, so the grammar refuses and the legacy
    trigger handler keeps the card."""
    result = compile_line(
        "Whenever this creature deals damage, you gain that much life."
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


def test_sacrificing_a_chosen_permanent_is_refused():
    """"Sacrifice a creature" makes a *player* choose which one, which needs
    the pending-choice machinery. Lowering it to sacrifice_self would sacrifice
    the source instead — the wrong permanent, silently."""
    result = compile_line("Sacrifice a creature.", card_name="Test")

    assert result.parsed, "the line should parse; only the lowering refuses"
    assert not result.lowered
    assert "chosen permanent" in result.failure_reason


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
    their object — a hand, the top cards of a library, a face-down creature.
    Natural Selection looks at a *library*; if the production skipped the noun
    it would claim that card and reveal the wrong zone."""
    result = compile_line(
        "Look at the top three cards of target player's library, then put them "
        "back in any order.",
        card_name="Natural Selection",
    )

    assert not result.parsed


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


def test_more_than_one_extra_turn_fails_to_parse():
    """`grant_extra_turn` queues exactly one turn and takes no count. Parsing a
    general quantity here would let "two extra turns" compile cleanly and hand
    back a single turn — the card would look supported and be wrong by one turn
    every cast."""
    result = compile_line("Take two extra turns after this one.", card_name="Test")

    assert not result.parsed


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


def test_unblockable_matches_the_legacy_payload():
    """Dwarven Warriors' printed line."""
    assert _instructions(
        "{T}: Target creature with power 2 or less can't be blocked this turn.",
        "Dwarven Warriors",
    ) == [("grant_unblockable_to_low_power_target", {})]


def test_a_different_power_threshold_is_refused():
    """The trap this production exists to survive.
    ``grant_unblockable_to_low_power_target`` hardcodes "power 2 or less" as a
    literal in engine/handlers/combat.py, and again in legality.py's target
    enumerator — the payload carries no threshold at all. A card reading
    "power 3 or less" would therefore compile cleanly and silently get the ≤2
    behaviour, so lowering compares the parsed comparison against the literal
    and refuses anything else."""
    result = compile_line(
        "{T}: Target creature with power 3 or less can't be blocked this turn.",
        card_name="Test",
    )

    assert result.parsed, "the line is grammatical; the refusal belongs at lowering"
    assert not result.lowered
    assert "power 2 or less" in result.failure_reason


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


def test_the_unblockable_target_is_deliberately_not_described():
    """``ObjectFilter.to_payload`` has no vocabulary for a power comparison, so
    a `targets` description here would read "target creature" and the picker
    would offer creatures the ability cannot legally affect. Emitting nothing
    keeps legality.py answering — the same call the Lace cycle makes."""
    (_kind, payload), = _full_payloads(
        "{T}: Target creature with power 2 or less can't be blocked this turn.",
        "Dwarven Warriors",
    )

    assert "targets" not in payload


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


@pytest.mark.parametrize(
    "line",
    [
        "Destroy target creature with mana value 3.",
        "Tap target creature with mana value X.",
    ],
)
def test_a_mana_value_restriction_is_never_dropped_by_another_effect(line):
    """``ObjectFilter.mana_value`` has no payload key and
    ``permanent_matches_filter`` cannot test one, so every handler but the
    counterspell would ignore it. Refusing keeps a new noun-phrase restriction
    from silently widening effects that were written before it existed."""
    result = compile_line(line, card_name="Test")

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


def test_a_fixed_unless_pays_cost_is_refused():
    """Only {X} has a payment flow: the pending prompt is sized from the
    caster's chosen X. Lowering "pays {2}" to the same flag would prompt for the
    wrong amount."""
    result = compile_line(
        "Counter target spell unless its controller pays {2}.", card_name="Test"
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
def test_tap_or_untap_refuses_a_restriction_it_cannot_honour(line):
    """``tap_or_untap_target`` toggles whatever it is handed
    (``predicate=lambda p: True``) and falls back to the first permanent when no
    choice was made, so a restricted form lowered to it could untap a land for
    "target creature". The filtered handler is ``tap_target_permanent``; there
    is no filtered toggle, so the restricted shapes refuse."""
    result = compile_line(line, card_name="Test")

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
    ],
)
def test_aura_upkeep_damage_lowers_to_the_dispatched_pair(card, line):
    """The three Auras that ping whoever controls what they enchant.

    All that was missing was the trigger phrase: the effect clause already
    lowered, and ``("upkeep_enchanted_controller", "deal_damage")`` is a
    registered pair in engine/phases/upkeep_effects.py. The payload is the
    legacy one byte for byte, which is what makes adding the phrase a no-op for
    behaviour and a gain for the migration.
    """
    assert _instructions(line, card) == [("deal_damage", {"amount": 1})]


def test_enchanted_land_upkeep_is_deliberately_not_a_trigger_phrase():
    """Cursed Land reads the same way but must NOT be claimed.

    Its upkeep damage is already dealt by the enchant-land pass in
    engine/phases/upkeep_step.py, and the legacy condition table excludes
    ``land`` for exactly that reason. Adding a fourth table row would give the
    grammar a trigger the engine never dispatches -- the line would count as
    "executing through the grammar" in GRAMMAR_COVERAGE.md while nothing about
    the card changed. False coverage is worse than none.
    """
    result = compile_line(
        "At the beginning of the upkeep of enchanted land's controller, "
        "this Aura deals 1 damage to that player.",
        card_name="Cursed Land",
    )

    assert not result.parsed


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
        (
            "Paralyze",
            "At the beginning of the upkeep of enchanted creature's controller, "
            "that player may pay {4}. If the player does, untap the creature.",
        ),
        (
            "Unstable Mutation",
            "At the beginning of the upkeep of enchanted creature's controller, "
            "put a -1/-1 counter on that creature.",
        ),
    ],
)
def test_the_new_trigger_phrase_does_not_drag_in_effects_it_cannot_read(card, line):
    """Adding a trigger phrase widens what reaches the effect productions, and
    these three are the cards that reach them and must still be refused.

    Power Leak's damage is scaled by a payment the grammar has no node for;
    Paralyze's optional untap decomposes into a ``may`` that no upkeep handler
    is keyed to; Unstable Mutation's "that creature" is a referent bound by the
    trigger, which the statement grammar cannot see. Each falls back to the
    legacy rules whole rather than compiling onto a nearby handler.
    """
    result = compile_line(line, card_name=card)

    assert not result.parsed


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


def test_an_unknown_where_x_is_count_refuses_the_whole_line():
    """The failure mode this production exists to prevent: consuming "where X
    is ..." generically would let any count reach whichever handler the caller
    assumed. An unlisted count leaves its tokens unconsumed instead, so the line
    fails full-token consumption and the card falls back visibly."""
    result = compile_line(
        "At the beginning of each player's upkeep, this enchantment deals X damage to "
        "that player, where X is the number of Mountains they control.",
        card_name="Test",
    )

    assert not result.parsed


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
    from engine.oracle import _parse_trigger_condition, normalize_creature_line

    disagreements = []
    for name, line, node, _lowered in _executed_trigger_lines(catalog):
        condition, _ = _parse_trigger_condition(normalize_creature_line(line))
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
# Both reach state the registry's UpkeepContext does not carry -- a graveyard
# position, and a P/T change applied to the enchanted permanent -- so they read
# their triggers directly in engine/phases/upkeep_step.py. Neither is grammar-
# executed today; they are listed so this guard describes the real dispatch
# surface rather than only the part that happens to be exercised.
_UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY = frozenset({
    ("upkeep_self", "upkeep_return_self_from_graveyard"),
    ("upkeep_enchanted_controller", "add_minus1_counter_to_enchanted"),
})


def test_every_executed_upkeep_trigger_lands_on_a_pair_something_dispatches(catalog):
    """The bug this catches has already shipped twice in this migration.

    Upkeep-family triggers do not resolve through EFFECT_HANDLERS: the upkeep
    step looks up ``(trigger condition kind, instruction kind)`` and does
    nothing at all when the pair is absent. So a trigger phrase plus a perfectly
    reasonable effect lowering can produce a card that compiles clean, reports as
    supported, and silently never fires. Checking the pair against the registry
    over the whole pool is the mechanical form of that review.
    """
    from engine.oracle import _parse_trigger_condition, normalize_creature_line
    from engine.phases.upkeep_effects import UPKEEP_EFFECTS

    assert not (_UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY & set(UPKEEP_EFFECTS)), (
        "a pair listed as dispatched outside the registry is now in it -- delete it here"
    )

    upkeep_conditions = {condition for condition, _ in UPKEEP_EFFECTS}
    dispatched = set(UPKEEP_EFFECTS) | _UPKEEP_PAIRS_DISPATCHED_OUTSIDE_THE_REGISTRY

    undispatched = []
    for name, line, _node, instructions in _executed_trigger_lines(catalog):
        condition, _ = _parse_trigger_condition(normalize_creature_line(line))
        if condition is None or condition.kind not in upkeep_conditions:
            continue
        for instruction in instructions:
            if (condition.kind, instruction.kind) not in dispatched:
                undispatched.append(
                    f"{name}: {line}\n    pair: {(condition.kind, instruction.kind)}"
                )

    assert not undispatched, (
        "the grammar executes an upkeep trigger no handler is keyed to, so the "
        "card compiles cleanly and does nothing:\n" + "\n".join(undispatched)
    )


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


def test_only_the_discard_cost_the_engine_can_charge_is_accepted():
    """``ActivatedAbilityCost`` has a flag for "the last card you drew this
    turn" and no field for a generic discard, so accepting "Discard a card"
    would describe a payment nothing collects — a free ability that still reads
    as supported."""
    assert compile_line(
        "{2}, {T}, Discard the last card you drew this turn: Draw a card.",
        card_name="Jandor's Ring",
    ).parsed
    assert not compile_line("Discard a card: Draw a card.", card_name="Test").parsed


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
    # Diamond Valley's cost now parses; its *effect* is what still refuses, so
    # the card stays on the legacy path for a reason the backlog can name.
    valley = compile_line(
        "{T}, Sacrifice a creature: You gain life equal to the sacrificed "
        "creature's toughness.",
        card_name="Diamond Valley",
    )
    assert not valley.parsed and "cost" not in (valley.failure_reason or "")


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


def test_one_mana_of_any_color_keeps_the_clause_text():
    """The one place the grammar still hands a handler its own clause back.

    ``add_mana_from_text``'s any-colour path is ``_add_mana_from_text`` probing
    for the literal phrase, with the chosen symbol arriving separately as
    ``color`` (injected by mixins/stack/activation when ``any_color`` is set).
    Structured pips would say nothing that path can read, so the payload stays
    byte-identical to the legacy rule's — which is what keeps Birds of
    Paradise, City of Brass and Celestial Prism producing mana at all."""
    for name in ("Birds of Paradise", "City of Brass"):
        assert _instructions("{T}: Add one mana of any color.", name) == [
            (
                "add_mana_from_text",
                {"oracle_text": "add one mana of any color", "any_color": True},
            )
        ]


def test_three_mana_of_any_one_color_refuses():
    """Black Lotus. That text probe recognizes *one* mana and no other number,
    so lowering three here would add nothing while reporting success. The card
    keeps its own fused ``sacrifice_self_for_mana`` handler on the legacy
    path."""
    result = compile_line(
        "{T}, Sacrifice this artifact: Add three mana of any one color.",
        card_name="Black Lotus",
    )

    assert result.parsed and not result.lowered
    assert "one mana of any colour" in result.failure_reason


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


def test_an_unnamed_token_refuses_rather_than_picking_a_convention():
    """Rukh Egg's and Bottle of Suleiman's token phrases parse in full but do
    not lower. CR 111.4 names an unnamed token "<subtypes> Token"; the engine's
    other token maker (``arm_end_step_token``) names it after the subtype
    alone. A token's name is what every "creatures named ..." effect reads, so
    picking one convention here would print the wrong name for one of the two
    families."""
    for line in (
        "Create a 4/4 red Bird creature token with flying.",
        "Create a 5/5 colorless Djinn artifact creature token with flying.",
    ):
        result = compile_line(line, card_name="Test")
        assert result.parsed and not result.lowered
        assert "no printed name" in result.failure_reason


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
            "Create an X/X colorless Insect creature token named Wasp.",
            "variable P/T: CreateToken stores printed integers and create_token "
            "reads them with int(), so there is no representation on either side",
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
            "Search your library for a card, put that card onto the battlefield, "
            "then shuffle.",
            "confirm_search_library appends to the hand; a battlefield destination "
            "is a different effect entirely",
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


def test_a_fixed_count_discarded_at_random_refuses():
    """There is no handler for it. ``discard_target_cards`` is the only handler
    that reads a counted amount, and it hands the victim the choice this card
    denies them."""
    result = compile_line("Target player discards two cards at random.", card_name="Test")

    assert result.parsed and not result.lowered
    assert "at random" in result.failure_reason


def test_a_variable_discard_that_is_not_random_refuses():
    """The mirror image: the only variable-count handler takes the cards at
    random, so lowering a chosen "discards X cards" onto it would take the
    choice away."""
    result = compile_line("Target player discards X cards.", card_name="Test")

    assert result.parsed and not result.lowered
    assert "at random" in result.failure_reason



def test_every_executed_end_step_trigger_lands_on_a_kind_the_step_enqueues(catalog):
    """The upkeep guard's twin, for the other step that dispatches by kind.

    ``resolve_end_step`` scans for a fixed set of instruction kinds under the
    ``end_step`` condition and enqueues nothing at all for anything else — so
    the same silent-death failure is available here: a trigger phrase the
    grammar already knows, plus a perfectly reasonable effect lowering, gives a
    card that compiles cleanly, reports as supported, and never fires. The
    dispatched set lives in ``engine/phases/end_step.py`` as data precisely so
    this check can read it rather than restate it.
    """
    from engine.oracle import _parse_trigger_condition, normalize_creature_line
    from engine.phases.end_step import END_STEP_DISPATCHED_KINDS

    undispatched = []
    for name, line, _node, instructions in _executed_trigger_lines(catalog):
        condition, _ = _parse_trigger_condition(normalize_creature_line(line))
        if condition is None or condition.kind != "end_step":
            continue
        for instruction in instructions:
            if instruction.kind not in END_STEP_DISPATCHED_KINDS:
                undispatched.append(f"{name}: {line}\n    kind: {instruction.kind}")

    assert not undispatched, (
        "the grammar executes an end-step trigger the step never enqueues, so "
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
    # that turned out not to be blocking it.
    assert result.failure_reason == (
        "a conditional static bonus is derived by engine/static_bonuses.py"
    )


def test_an_as_long_as_condition_the_grammar_cannot_model_is_not_claimed():
    """Jihad's condition ("the chosen player controls a nontoken permanent of
    the chosen color") is outside the condition vocabulary. Claiming the line
    anyway would report a card as understood while its whole restriction had
    been dropped."""
    assert not compile_line(
        "White creatures get +2/+1 as long as the chosen player controls a "
        "nontoken permanent of the chosen color.",
        card_name="Jihad",
    ).parsed


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
