"""Per-card tests for Antiquities' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from unittest.mock import patch

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


# ---------------------------------------------------------------------------
# Goblin Artisans (round 25) — a spell nobody else is already aiming at
# ---------------------------------------------------------------------------


def _artisans_board(set_pool, *, copies=1):
    pool = set_pool("ATQ")
    artisans = [Permanent(card=pool["Goblin Artisans"]) for _ in range(copies)]
    p1 = PlayerState(
        name="P1",
        battlefield=list(artisans),
        hand=[pool["Ornithopter"]],
        library=[pool["Ornithopter"]] * 5,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game, p1, pool


def _flip(win: bool):
    """The flip forced through the module object every RNG reader shares —
    the idiom test_m21_creatures.py's Tavern Swindler tests record."""
    return patch(
        "engine.handlers._common.random.random", return_value=0.0 if win else 0.99
    )


def test_goblin_artisans_draws_on_a_won_flip(set_pool):
    game, p1, pool = _artisans_board(set_pool)
    before = len(p1.hand)

    with _flip(True):
        game.queue_permanent_ability(0, "Goblin Artisans", permanent_index=0)
        game._settle()

    assert len(p1.hand) == before + 1, game.log


def test_a_lost_flip_counters_your_own_artifact_spell(set_pool):
    game, p1, pool = _artisans_board(set_pool)
    game.queue_from_hand(0, "Ornithopter")

    with _flip(False):
        game.queue_permanent_ability(
            0, "Goblin Artisans", permanent_index=0, target_stack_index=0
        )
        game._settle()

    assert game.stack == []
    assert [card.name for card in p1.graveyard] == ["Ornithopter"]


def test_an_artifact_creature_spell_is_an_artifact_spell(set_pool):
    """CR 205.2: a card has every type its line names. Ornithopter is the only
    thing in the set this ability can legally be pointed at, and asking the
    card's *primary* type picked "creature" — so the whole card refused every
    spell it exists to counter. The test above is that check; this names it."""
    pool = set_pool("ATQ")
    assert "artifact" in pool["Ornithopter"].type_line.lower()
    assert pool["Ornithopter"].primary_type != "artifact"


def test_it_cannot_counter_an_opponents_artifact_spell(set_pool):
    """"…target artifact spell **you control**"."""
    game, p1, pool = _artisans_board(set_pool)
    p2 = game.players[1]
    p2.hand.append(pool["Ornithopter"])
    game.queue_from_hand(1, "Ornithopter")

    with _flip(False):
        game.queue_permanent_ability(
            0, "Goblin Artisans", permanent_index=0, target_stack_index=0
        )
        game._settle()

    assert [perm.card.name for perm in p2.battlefield] == ["Ornithopter"]


def test_a_second_artisans_already_aiming_at_the_spell_locks_it_out(set_pool):
    """"…that isn't the target of an ability from **another** creature named
    Goblin Artisans." The guard against two copies pointing at one spell. Both
    abilities are put on the stack aimed at the same Ornithopter; the one that
    resolves first sees the other still waiting and does nothing."""
    game, p1, pool = _artisans_board(set_pool, copies=2)
    game.queue_from_hand(0, "Ornithopter")

    with _flip(False):
        game.queue_permanent_ability(
            0, "Goblin Artisans", permanent_index=1, target_stack_index=0
        )
        game.queue_permanent_ability(
            0, "Goblin Artisans", permanent_index=0, target_stack_index=0
        )
        game._settle()

    assert any(
        "already the target of another" in entry for entry in game.log
    ), game.log


def test_one_artisans_is_not_blocked_by_its_own_ability(set_pool):
    """"**Another**" is by identity: the ability now resolving is this
    permanent's own, and a rule that counted it would make a lone Goblin
    Artisans unable to counter anything at all."""
    game, p1, pool = _artisans_board(set_pool)
    game.queue_from_hand(0, "Ornithopter")

    with _flip(False):
        game.queue_permanent_ability(
            0, "Goblin Artisans", permanent_index=0, target_stack_index=0
        )
        game._settle()

    assert [card.name for card in p1.graveyard] == ["Ornithopter"], game.log


# ---------------------------------------------------------------------------
# Tetravus (round 26) — counters into tokens and back
# ---------------------------------------------------------------------------


def _tetravus(set_pool):
    """Tetravus cast and on the battlefield, with its three counters."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Tetravus"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Tetravus")
    game.active_player_index = 0
    return game, p1, p1.battlefield[0]


def _tetravites(player):
    return [perm for perm in player.battlefield if perm.card.name.startswith("Tetravite")]


def _take_upkeep(game, *, remove=0, exile=0, accept=True):
    """Run Tetravus's upkeep and answer both of its offers.

    Both triggers fire (CR 603.3) and both print the same card name, so the
    prompts are told apart by what they are for rather than by who they are
    from — which is what the queue records.
    """
    game.resolve_upkeep(0)
    game._settle()
    while game.pending_choices:
        choice = game.pending_choices[0]
        if choice.kind == "optional_pay":
            game.confirm_optional_pay(0, card_name="Tetravus", accept=accept)
            continue
        if choice.kind != "number_choice":
            break
        wanted = exile if choice.data.get("exile_own_tokens") else remove
        game.confirm_number_choice(0, min(wanted, int(choice.data["maximum"])))


def test_tetravus_enters_with_three_counters(set_pool):
    game, p1, tetravus = _tetravus(set_pool)

    assert tetravus.metadata["plus_counters"] == 3
    assert (tetravus.effective_power, tetravus.effective_toughness) == (4, 4)


def test_counters_come_off_as_tetravites(set_pool):
    """"…remove any number of +1/+1 counters. If you do, create **that many**
    … tokens." The count is the player's, and the second sentence is about the
    answer to the first."""
    game, p1, tetravus = _tetravus(set_pool)

    _take_upkeep(game, remove=2)

    assert tetravus.metadata["plus_counters"] == 1
    assert (tetravus.effective_power, tetravus.effective_toughness) == (2, 2)
    assert len(_tetravites(p1)) == 2


def test_the_tetravites_carry_both_printed_abilities(set_pool):
    """"They each have flying and "This token can't be enchanted."" — a whole
    sentence after the token clause, which the quoted-line entry point used to
    read up to the first full stop and drop."""
    game, p1, tetravus = _tetravus(set_pool)

    _take_upkeep(game, remove=1)

    token = _tetravites(p1)[0]
    assert game._has_keyword(token, "flying")
    assert game._cant_be_enchanted(token)


def test_an_ordinary_creature_can_still_be_enchanted(set_pool):
    """The control on the check above: the restriction is the token's printed
    line, not something true of every creature."""
    game, p1, tetravus = _tetravus(set_pool)

    assert not game._cant_be_enchanted(tetravus)


def test_declining_removes_no_counters(set_pool):
    game, p1, tetravus = _tetravus(set_pool)

    _take_upkeep(game, remove=3, accept=False)

    assert tetravus.metadata["plus_counters"] == 3
    assert _tetravites(p1) == []


def test_exiling_the_tetravites_puts_the_counters_back(set_pool):
    """The second upkeep trigger, which is the first one run backwards."""
    game, p1, tetravus = _tetravus(set_pool)
    _take_upkeep(game, remove=3)
    assert len(_tetravites(p1)) == 3

    _take_upkeep(game, remove=0, exile=3)

    assert _tetravites(p1) == []
    assert tetravus.metadata["plus_counters"] == 3


def test_both_upkeep_triggers_fire(set_pool):
    """CR 603.3 puts **every** ability that triggered on the stack. The upkeep
    loop stopped at a permanent's first one, which was invisible until the only
    card in the pool that prints two."""
    game, p1, tetravus = _tetravus(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert len(game.pending_choices_of("optional_pay", 0)) == 2


def test_a_tetravite_belongs_to_the_tetravus_that_made_it(set_pool):
    """"…tokens **created with this creature**." A second Tetravus's tokens are
    not this one's, so its exile trigger must not reach them."""
    game, p1, tetravus = _tetravus(set_pool)
    _take_upkeep(game, remove=2)

    made = _tetravites(p1)
    assert {perm.metadata["created_with_permanent_id"] for perm in made} == {
        tetravus.permanent_id
    }


# ---------------------------------------------------------------------------
# Battering Ram (round 30) — a trigger that compiled and fired nothing
# ---------------------------------------------------------------------------


def _ram_blocked_by(set_pool, blocker_name):
    pool = set_pool("ATQ")
    ram = Permanent(card=pool["Battering Ram"])
    blocker = Permanent(card=pool[blocker_name])
    p1 = PlayerState(name="P1", battlefield=[ram])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.declare_attackers(0, [0])
    game.current_step = "declare_blockers"
    accepted, why = game.declare_blockers(1, {0: 0})
    assert accepted, why
    game._settle()
    game._resolve_end_of_combat_destruction()
    return game, p2


def test_a_wall_that_blocks_the_ram_dies_at_end_of_combat(set_pool):
    game, p2 = _ram_blocked_by(set_pool, "Wall of Spears")

    assert [perm.card.name for perm in p2.battlefield] == []
    assert [card.name for card in p2.graveyard] == ["Wall of Spears"]


def test_a_creature_that_is_not_a_wall_survives(set_pool):
    """"…becomes blocked by **a Wall**, destroy that Wall." The noun is what
    separates this from Thicket Basilisk, which destroys everything *but* a
    Wall — so a rule that ignored it would be the other card."""
    game, p2 = _ram_blocked_by(set_pool, "Citanul Druid")

    assert [perm.card.name for perm in p2.battlefield] == ["Citanul Druid"]


def test_the_trigger_names_the_blocker_and_not_the_ram(set_pool):
    """The dispatcher pushed the *attacker* as the trigger's target, which for
    a "destroy that Wall" rider would have destroyed the Ram. The blocker is
    what the event bound, so the blocker is what the stack item carries."""
    game, p2 = _ram_blocked_by(set_pool, "Wall of Spears")

    assert any(
        "will destroy Wall of Spears" in entry for entry in game.log
    ), game.log
