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
