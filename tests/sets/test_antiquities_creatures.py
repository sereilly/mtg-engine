"""Per-card tests for Antiquities' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.damage_events import deal_damage
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Citanul Druid (round 3) — "whenever an opponent casts an artifact spell"
# ---------------------------------------------------------------------------


def test_citanul_druid_grows_on_an_opponents_artifact_spell(set_pool):
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid])
    p2 = PlayerState(name="P2", hand=[pool["Ornithopter"]])
    game = Game(players=[p1, p2])

    base = druid.effective_power
    game.cast_from_hand(1, "Ornithopter")

    assert druid.effective_power == base + 1


def test_citanul_druid_ignores_your_own_artifact_spell(set_pool):
    """"an **opponent** casts" — the scope half of the narrowing."""
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid], hand=[pool["Ornithopter"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    base = druid.effective_power
    game.cast_from_hand(0, "Ornithopter")

    assert druid.effective_power == base


def test_citanul_druid_ignores_a_nonartifact_spell(set_pool):
    """And the type half."""
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid])
    p2 = PlayerState(name="P2", hand=[pool["Detonate"]])
    game = Game(players=[p1, p2])

    base = druid.effective_power
    game.cast_from_hand(1, "Detonate")

    assert druid.effective_power == base


def test_citanul_druid_compiles_the_narrowed_condition(set_pool):
    program = compile_card_oracle(set_pool("ATQ")["Citanul Druid"])
    (trigger,) = program.triggered_abilities

    assert trigger.supported
    assert trigger.condition.kind == "opponent_casts_spell"
    assert trigger.condition.payload["cast_type"] == "artifact"


# ---------------------------------------------------------------------------
# Argothian Treefolk / Argothian Pixies (round 4) — artifact-source shields
# ---------------------------------------------------------------------------


def test_argothian_treefolk_is_unharmed_by_an_artifact_source(set_pool):
    pool = set_pool("ATQ")
    treefolk = Permanent(card=pool["Argothian Treefolk"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[treefolk])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    outcome = deal_damage(
        game, {"recipient": treefolk, "amount": 3, "source": thopter, "combat": False}
    )

    assert outcome.dealt == 0


def test_argothian_treefolk_still_takes_damage_from_a_creature(set_pool):
    """The narrowing under load: the shield names artifact sources, so an
    ordinary creature gets through."""
    pool = set_pool("ATQ")
    treefolk = Permanent(card=pool["Argothian Treefolk"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[treefolk])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    outcome = deal_damage(
        game, {"recipient": treefolk, "amount": 3, "source": druid, "combat": False}
    )

    assert outcome.dealt == 3


def test_argothian_pixies_cannot_be_blocked_by_an_artifact_creature(set_pool):
    pool = set_pool("ATQ")
    pixies = Permanent(card=pool["Argothian Pixies"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[pixies])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(thopter, pixies) is False


def test_argothian_pixies_can_still_be_blocked_by_an_ordinary_creature(set_pool):
    """The restriction names artifact creatures; a flesh-and-blood blocker is
    unaffected. Without this the test above would pass against a rule that
    stopped every block."""
    pool = set_pool("ATQ")
    pixies = Permanent(card=pool["Argothian Pixies"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[pixies])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(druid, pixies) is True


# ---------------------------------------------------------------------------
# Gaea's Avenger / Urza's Avenger (round 9)
# ---------------------------------------------------------------------------


def test_gaeas_avenger_counts_one_plus_the_opponents_artifacts(set_pool):
    pool = set_pool("ATQ")
    avenger = Permanent(card=pool["Gaea's Avenger"])
    p1 = PlayerState(name="P1", battlefield=[avenger])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=pool["Ornithopter"]), Permanent(card=pool["Jalum Tome"])],
    )
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()

    assert (avenger.effective_power, avenger.effective_toughness) == (3, 3)


def test_gaeas_avenger_ignores_your_own_artifacts(set_pool):
    """"artifacts **your opponents** control" — the constant survives alone."""
    pool = set_pool("ATQ")
    avenger = Permanent(card=pool["Gaea's Avenger"])
    p1 = PlayerState(
        name="P1", battlefield=[avenger, Permanent(card=pool["Ornithopter"])]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game._refresh_dynamic_creatures()

    assert (avenger.effective_power, avenger.effective_toughness) == (1, 1)


def test_urzas_avenger_offers_all_four_printed_keywords(set_pool):
    """"…gains your choice of banding, flying, first strike, or trample." The
    keyword-list parser read "or" but not the comma-separated form, so a list
    of four collapsed to one item and the card was refused for offering a
    choice of one."""
    program = compile_card_oracle(set_pool("ATQ")["Urza's Avenger"])
    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    choice = next(step for step in steps if step.kind == "choose_one")
    labels = {mode["label"] for mode in choice.payload["modes"]}

    assert ability.supported
    assert labels == {"banding", "flying", "first strike", "trample"}
    # The drawback is the other half of the sentence and rides in the same
    # sequence — a card that granted the keyword without the -1/-1 would be
    # strictly better than the one printed.
    assert any(
        step.kind == "pump_self" and step.payload == {"power": -1, "toughness": -1}
        for step in steps
    )


# ---------------------------------------------------------------------------
# Clockwork Avian (round 12) — the cap is a number, not a card name
# ---------------------------------------------------------------------------


def _avian_in_upkeep(set_pool):
    """Clockwork Avian **entered** rather than constructed, so its "enters with
    four +1/+0 counters" actually ran — and in an upkeep, because "Activate
    only during your upkeep" is a real restriction and is enforced."""
    pool = set_pool("ATQ")
    avian = Permanent(card=pool["Clockwork Avian"])
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, avian, None)
    game._set_phase_and_step("beginning", "upkeep")
    # The ability costs {T}, so summoning sickness is a real gate on it
    # (CR 302.6) and the fixture has to be past it — a creature that just
    # arrived genuinely cannot use this.
    avian.metadata.pop("summoning_sickness_turn", None)
    return game, avian


def test_clockwork_avian_enters_at_its_cap_and_cannot_exceed_it(set_pool):
    game, avian = _avian_in_upkeep(set_pool)
    assert avian.effective_power == 4, "0/4 base plus four +1/+0 counters"

    game.activate_permanent_ability(0, "Clockwork Avian", x_value=3)

    assert avian.effective_power == 4, "already at the printed cap"


def test_clockwork_avian_refills_only_up_to_the_cap(set_pool):
    game, avian = _avian_in_upkeep(set_pool)
    # Spend three, as combat would.
    avian.metadata["plus_1_0_counters"] = 1
    avian.power_bonus = 1
    assert avian.effective_power == 1

    game.activate_permanent_ability(0, "Clockwork Avian", x_value=10)

    assert avian.effective_power == 4, "1 -> 4, not 1 -> 11"


def test_the_two_clockwork_cards_share_one_rule_with_different_numbers(set_pool, catalog_by_name):
    """Clockwork Beast prints seven and the Avian prints four. That difference
    used to be a card-name-keyed hook whose dictionary key spelled out "seven"
    and a constant 7 in the handler — two copies of one number, which is why
    the Avian would have needed a second entry to say four."""
    beast = compile_card_oracle(catalog_by_name["Clockwork Beast"])
    avian = compile_card_oracle(set_pool("ATQ")["Clockwork Avian"])

    (beast_ability,) = [a for a in beast.activated_abilities if a.instruction]
    (avian_ability,) = [a for a in avian.activated_abilities if a.instruction]

    assert beast_ability.instruction.kind == avian_ability.instruction.kind
    assert beast_ability.instruction.payload["cap"] == 7
    assert avian_ability.instruction.payload["cap"] == 4


# ---------------------------------------------------------------------------
# Priest of Yawgmoth (round 15) — an effect reading back what its cost ate
# ---------------------------------------------------------------------------


def _priest_and(set_pool, artifact_name):
    pool = set_pool("ATQ")
    priest = Permanent(card=pool["Priest of Yawgmoth"])
    fodder = Permanent(card=pool[artifact_name])
    p1 = PlayerState(name="P1", battlefield=[priest, fodder])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    priest.metadata.pop("summoning_sickness_turn", None)
    return game, p1


def test_priest_of_yawgmoth_pays_the_sacrificed_artifacts_mana_value(set_pool):
    game, p1 = _priest_and(set_pool, "Jalum Tome")  # {3}

    game.activate_permanent_ability(0, "Priest of Yawgmoth", cost_permanent_index=1)

    assert p1.mana_pool["B"] == 3
    assert "Jalum Tome" not in {perm.card.name for perm in game.all_permanents()}


def test_a_zero_cost_artifact_pays_nothing(set_pool):
    """Ornithopter's mana value is 0, and 0 is the honest answer — the amount
    is the sacrificed artifact's mana value, not "at least one"."""
    game, p1 = _priest_and(set_pool, "Ornithopter")  # {0}

    game.activate_permanent_ability(0, "Priest of Yawgmoth", cost_permanent_index=1)

    assert p1.mana_pool.get("B", 0) == 0


def test_the_ability_pays_its_own_sacrifice_cost(set_pool):
    """`sacrifice_creature_for_mana` was listed as a kind whose handler performs
    the sacrifice itself, so the activation path skipped paying it. That was
    harmless while only two *sorceries* produced the kind — the casting path
    pays their cost — and silently stopped paying it the moment an activated
    ability produced the same kind."""
    game, p1 = _priest_and(set_pool, "Jalum Tome")
    before = len(list(game.all_permanents()))

    game.activate_permanent_ability(0, "Priest of Yawgmoth", cost_permanent_index=1)

    assert len(list(game.all_permanents())) == before - 1, "exactly one artifact left"


# ---------------------------------------------------------------------------
# Phyrexian Gremlins (round 18) — a linked untap lock
# ---------------------------------------------------------------------------


def _gremlins_holding(set_pool):
    pool = set_pool("ATQ")
    gremlins = Permanent(card=pool["Phyrexian Gremlins"])
    tome = Permanent(card=pool["Jalum Tome"])
    p1 = PlayerState(name="P1", battlefield=[gremlins])
    p2 = PlayerState(name="P2", battlefield=[tome])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    gremlins.metadata.pop("summoning_sickness_turn", None)
    game.activate_permanent_ability(
        0, "Phyrexian Gremlins", target_player_index=1, target_permanent_index=0
    )
    return game, gremlins, tome


def test_phyrexian_gremlins_taps_the_artifact_and_holds_it(set_pool):
    game, gremlins, tome = _gremlins_holding(set_pool)

    assert gremlins.tapped, "the ability costs {T}"
    assert tome.tapped

    game.resolve_untap_step(1)
    assert tome.tapped, "held while the Gremlins remains tapped"


def test_the_lock_ends_the_moment_the_gremlins_untaps(set_pool):
    """The restriction is read off the *source's* record, so it ends when the
    source untaps — there is no flag on the held artifact to clear, which is
    what makes a duration that ends on a condition expressible at all."""
    game, gremlins, tome = _gremlins_holding(set_pool)

    gremlins.tapped = False
    game.resolve_untap_step(1)

    assert not tome.tapped


def test_the_lock_leaves_other_artifacts_alone(set_pool):
    game, gremlins, tome = _gremlins_holding(set_pool)
    pool = set_pool("ATQ")
    other = Permanent(card=pool["Jalum Tome"])
    other.tapped = True
    game.players[1].battlefield.append(other)

    game.resolve_untap_step(1)

    assert tome.tapped, "the named one is held"
    assert not other.tapped, "its look-alike is not — the record is by id"


# ---------------------------------------------------------------------------
# Martyrs of Korlis (round 20) — Veteran Bodyguard's redirect, other class
# ---------------------------------------------------------------------------


def _martyrs_hit_by(set_pool, source_name, tapped=False):
    from engine.damage_events import deal_damage

    pool = set_pool("ATQ")
    martyrs = Permanent(card=pool["Martyrs of Korlis"])
    martyrs.tapped = tapped
    source = Permanent(card=pool[source_name])
    p1 = PlayerState(name="P1", battlefield=[martyrs])
    p2 = PlayerState(name="P2", battlefield=[source])
    game = Game(players=[p1, p2])
    deal_damage(game, {"recipient": p1, "amount": 3, "source": source, "combat": False})
    return p1, martyrs


def test_martyrs_of_korlis_takes_artifact_damage_for_you(set_pool):
    p1, martyrs = _martyrs_hit_by(set_pool, "Ornithopter")

    assert p1.life == 20
    assert martyrs.damage_marked == 3


def test_a_tapped_martyrs_protects_nobody(set_pool):
    """"**As long as this creature is untapped**" — the condition is half the
    card, and a redirect that fired while tapped would be strictly better than
    the one printed."""
    p1, martyrs = _martyrs_hit_by(set_pool, "Ornithopter", tapped=True)

    assert martyrs.damage_marked == 0


def test_martyrs_of_korlis_ignores_a_nonartifact_source(set_pool):
    """The class is the only thing separating this card from Veteran
    Bodyguard, which redirects unblocked creatures and not artifacts."""
    p1, martyrs = _martyrs_hit_by(set_pool, "Citanul Druid")

    assert martyrs.damage_marked == 0


# ---------------------------------------------------------------------------
# Shapeshifter (round 24) — a number a player picks, read back as P/T
# ---------------------------------------------------------------------------


def _shapeshifter(set_pool, *, chosen=None):
    pool = set_pool("ATQ")
    metadata = {} if chosen is None else {"chosen_number": chosen}
    perm = Permanent(card=pool["Shapeshifter"], metadata=metadata)
    p1 = PlayerState(name="P1", battlefield=[perm])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    return game, p1, perm


def test_shapeshifter_splits_seven_between_power_and_toughness(set_pool):
    game, p1, perm = _shapeshifter(set_pool, chosen=2)

    assert (perm.effective_power, perm.effective_toughness) == (2, 5)


def test_the_total_is_the_printed_one_not_a_fixed_body(set_pool):
    """The control on the test above: nothing about the card is 2/5. The
    toughness is derived from the same number the power is, which is why the
    printed 7 is payload rather than a second template."""
    game, p1, perm = _shapeshifter(set_pool, chosen=6)

    assert (perm.effective_power, perm.effective_toughness) == (6, 1)


def test_it_chooses_a_number_as_it_enters(set_pool):
    """CR 614.1c: the choice is part of entering, not a trigger. A trigger
    would leave a 0/0 on the battlefield long enough for the state-based check
    to bin it."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Shapeshifter"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Shapeshifter")

    perm = p1.battlefield[0]
    assert perm.metadata["chosen_number"] == 3, "the middle of the printed range"
    assert (perm.effective_power, perm.effective_toughness) == (3, 4)
    assert [choice.kind for choice in game.pending_choices] == ["number_choice"]


def test_the_controller_can_answer_the_prompt(set_pool):
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Shapeshifter"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Shapeshifter")
    perm = p1.battlefield[0]

    assert game.confirm_number_choice(0, 7)
    assert (perm.effective_power, perm.effective_toughness) == (7, 0)


def test_a_number_outside_the_printed_range_is_refused(set_pool):
    """Rejected, not clamped. The prompt names the range the card prints, and
    an answer quietly repaired into a legal one is a caller told its illegal
    request worked."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Shapeshifter"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Shapeshifter")
    perm = p1.battlefield[0]

    assert not game.confirm_number_choice(0, 8)
    assert perm.metadata["chosen_number"] == 3
    assert [choice.kind for choice in game.pending_choices] == ["number_choice"]


def test_the_upkeep_trigger_offers_a_new_number(set_pool):
    """"You **may** choose a number" — an optional upkeep trigger, so the offer
    comes first and the number choice only after it is taken."""
    game, p1, perm = _shapeshifter(set_pool, chosen=2)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game._settle()
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]

    game.confirm_optional_pay(0, card_name="Shapeshifter", accept=True)
    assert game.confirm_number_choice(0, 5)

    assert (perm.effective_power, perm.effective_toughness) == (5, 2)


def test_declining_the_upkeep_offer_keeps_the_last_number(set_pool):
    """"The **last** chosen number" is what the P/T reads, so declining is a
    real answer rather than a missing one."""
    game, p1, perm = _shapeshifter(set_pool, chosen=2)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    game._settle()
    game.confirm_optional_pay(0, card_name="Shapeshifter", accept=False)

    assert (perm.effective_power, perm.effective_toughness) == (2, 5)
