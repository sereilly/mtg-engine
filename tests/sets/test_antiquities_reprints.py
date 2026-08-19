"""Antiquities cards reprinted in Revised.

The set is not in the manifest yet, so these build the cards from their printed
text. Each was blocked on a *rider or a timing window*, never on the effect
itself — damage, discard, destroy and counters were all implemented already.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _artifact(name, text, type_line="Artifact", **kw):
    return CardDefinition(
        name=name, mana_cost="{6}", cmc=6.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=kw.pop("keywords", ()),
        produced_mana=(), raw={"name": name, "type_line": type_line, **kw},
    )


# ---------------------------------------------------------------------------
# Mishra's War Machine
# ---------------------------------------------------------------------------

MWM_TEXT = (
    "Banding\nAt the beginning of your upkeep, this creature deals 3 damage to "
    "you unless you discard a card. If it deals damage to you this way, tap it."
)


def _mwm():
    return _artifact(
        "Mishra's War Machine", MWM_TEXT,
        type_line="Artifact Creature — Juggernaut",
        keywords=("Banding",), power="12", toughness="12",
    )


def test_mishras_war_machine_damage_is_not_unconditional():
    """It compiled to `deal_damage {amount: 3}` and reported supported, having
    dropped both riders: it dealt 3 every upkeep with no choice and no tap."""
    program = compile_card_oracle(_mwm())
    trigger = program.triggered_abilities[0]
    assert trigger.instruction.kind == "upkeep_damage_unless_discard"
    assert trigger.instruction.payload["amount"] == 3
    assert trigger.instruction.payload["taps_source"] is True


def test_mishras_war_machine_discards_instead_of_taking_damage(catalog):
    machine = Permanent(card=_mwm())
    player = PlayerState(name="P1", battlefield=[machine], hand=[catalog["Forest"]])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.resolve_upkeep(0)

    assert player.life == 20
    assert machine.tapped is False
    assert len(player.graveyard) == 1


def test_mishras_war_machine_taps_only_on_the_damage_branch():
    """The tap is conditional on which branch was taken, which is why it rides
    on the payload rather than being a second instruction — a sequence would
    tap either way."""
    machine = Permanent(card=_mwm())
    player = PlayerState(name="P1", battlefield=[machine], hand=[])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.resolve_upkeep(0)

    assert player.life == 17
    assert machine.tapped is True


# ---------------------------------------------------------------------------
# Rocket Launcher
# ---------------------------------------------------------------------------

RL_TEXT = (
    "{2}: This artifact deals 1 damage to any target. Destroy this artifact at "
    "the beginning of the next end step. Activate only if you've controlled "
    "this artifact continuously since the beginning of your most recent turn."
)


@pytest.mark.cr("302.6")
def test_rocket_launcher_cannot_be_activated_the_turn_it_arrives():
    """CR 302.6's clause named directly by an artifact. Asking
    `_is_summoning_sick` would answer "no" purely because an artifact is not a
    creature, so the condition is separated from the creature rule."""
    launcher = Permanent(card=_artifact("Rocket Launcher", RL_TEXT))
    p1 = PlayerState(name="P1", battlefield=[launcher])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    launcher.metadata["summoning_sickness_turn"] = game.turn

    result = game.activate_permanent_ability(0, "Rocket Launcher", target_player_index=1)

    assert result.supported is False
    assert p2.life == 20


def test_rocket_launcher_destroys_itself_at_the_next_end_step():
    launcher = Permanent(card=_artifact("Rocket Launcher", RL_TEXT))
    p1 = PlayerState(name="P1", battlefield=[launcher])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    launcher.metadata["summoning_sickness_turn"] = -99

    assert game.activate_permanent_ability(0, "Rocket Launcher", target_player_index=1).supported
    assert p2.life == 19
    assert launcher.metadata["destroy_at_next_end_step"] is True

    game.resolve_end_step(0)

    assert not any(p.card.name == "Rocket Launcher" for p in p1.battlefield)


# ---------------------------------------------------------------------------
# Armageddon Clock
# ---------------------------------------------------------------------------

CLOCK_TEXT = (
    "At the beginning of your upkeep, put a doom counter on this artifact.\n"
    "At the beginning of your draw step, this artifact deals damage equal to "
    "the number of doom counters on it to each player.\n"
    "{4}: Remove a doom counter from this artifact. Any player may activate "
    "this ability but only during any upkeep step."
)


def test_armageddon_clock_accumulates_counters_and_scales_its_damage():
    """The counter's name is payload, so the accumulation is one handler for
    every card that counts something up on its own upkeep."""
    clock = Permanent(card=_artifact("Armageddon Clock", CLOCK_TEXT))
    p1 = PlayerState(name="P1", battlefield=[clock], library=[])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.resolve_upkeep(0)
    assert clock.metadata["doom_counters"] == 1
    game.resolve_draw_step(0)
    assert (p1.life, p2.life) == (19, 19)      # 1 counter -> 1 damage each

    game.resolve_upkeep(0)
    assert clock.metadata["doom_counters"] == 2
    game.resolve_draw_step(0)
    assert (p1.life, p2.life) == (17, 17)      # 2 counters -> 2 more each


def test_armageddon_clock_draw_step_damage_is_a_compiled_trigger():
    """Round 140: the damage used to be a regex over the permanent's oracle
    text living in phases/draw_step.py, dealt inline before the turn-based
    draw. It is an ordinary trigger now — the counter kind and the recipient
    are payload, so the next card printed this way needs no code, and the
    amount is read off the source when the ability *resolves* rather than when
    the step began."""
    program = compile_card_oracle(_artifact("Armageddon Clock", CLOCK_TEXT))
    trigger = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "draw_step_self"
    )

    assert trigger.supported
    assert trigger.instruction.kind == "deal_damage"
    assert trigger.instruction.payload == {
        "amount_from_named_counters": "doom",
        "recipient": "each_player",
    }


def test_armageddon_clock_deals_no_damage_before_a_counter_exists():
    clock = Permanent(card=_artifact("Armageddon Clock", CLOCK_TEXT))
    p1 = PlayerState(name="P1", battlefield=[clock], library=[])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.resolve_draw_step(0)

    assert (p1.life, p2.life) == (20, 20)


@pytest.mark.cr("602.5")
def test_armageddon_clock_counter_removal_is_gated_to_an_upkeep_step():
    """"Only during any upkeep step" — a window scoped to a *step* rather than
    to a player's own step, which is what lets an opponent use it."""
    clock = Permanent(card=_artifact("Armageddon Clock", CLOCK_TEXT))
    p1 = PlayerState(name="P1", battlefield=[clock], library=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.resolve_upkeep(0)
    game.resolve_upkeep(0)
    assert clock.metadata["doom_counters"] == 2

    game._set_phase_and_step("precombat_main", "main")
    assert game.activate_permanent_ability(0, "Armageddon Clock").supported is False
    assert clock.metadata["doom_counters"] == 2

    game._set_phase_and_step("beginning", "upkeep")
    assert game.activate_permanent_ability(0, "Armageddon Clock").supported is True
    assert clock.metadata["doom_counters"] == 1


@pytest.mark.cr("602.5")
def test_armageddon_clock_can_be_wound_down_by_the_opponent():
    """"Any player may activate this ability." The permission and the step
    window are separate checks, and both have to pass — together they are the
    whole point of the card: the Clock threatens everyone, so everyone may
    slow it."""
    clock = Permanent(card=_artifact("Armageddon Clock", CLOCK_TEXT))
    p1 = PlayerState(name="P1", battlefield=[clock], library=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.resolve_upkeep(0)
    game.resolve_upkeep(0)
    game._set_phase_and_step("beginning", "upkeep")

    result = game.activate_permanent_ability(1, "Armageddon Clock", source_controller_index=0)

    assert result.supported is True
    assert clock.metadata["doom_counters"] == 1


def test_removing_a_counter_that_is_not_there_is_a_no_op():
    clock = Permanent(card=_artifact("Armageddon Clock", CLOCK_TEXT))
    p1 = PlayerState(name="P1", battlefield=[clock], library=[])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._set_phase_and_step("beginning", "upkeep")

    assert game.activate_permanent_ability(0, "Armageddon Clock").supported is True
    assert clock.metadata.get("doom_counters", 0) == 0


# ---------------------------------------------------------------------------
# Reconstruction / Ivory Tower / Reverse Polarity
# ---------------------------------------------------------------------------

def test_reconstruction_returns_an_artifact_not_just_any_card(catalog):
    """"Target artifact card" is a filter. The rule read anything that was not
    "creature card" as "any card", so Reconstruction could have returned a
    creature — a dropped filter, not a missing feature."""
    card = _artifact(
        "Reconstruction", "Return target artifact card from your graveyard to your hand.",
        type_line="Sorcery",
    )
    player = PlayerState(
        name="P1", hand=[card],
        graveyard=[catalog["Grizzly Bears"], catalog["Sol Ring"]],
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Reconstruction")

    assert [c.name for c in player.hand] == ["Sol Ring"]
    # Reconstruction itself is in the graveyard now, having resolved.
    assert "Grizzly Bears" in [c.name for c in player.graveyard]
    assert "Sol Ring" not in [c.name for c in player.graveyard]


@pytest.mark.parametrize("cards_in_hand,expected", [(7, 23), (5, 21), (4, 20), (2, 20)])
def test_ivory_tower_never_drains(catalog, cards_in_hand, expected):
    """"Minus 4" with three cards in hand gains nothing; it does not drain."""
    tower = _artifact(
        "Ivory Tower",
        "At the beginning of your upkeep, you gain X life, where X is the "
        "number of cards in your hand minus 4.",
    )
    player = PlayerState(
        name="P1", battlefield=[Permanent(card=tower)],
        hand=[catalog["Forest"]] * cards_in_hand,
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.resolve_upkeep(0)

    assert player.life == expected


def test_reverse_polarity_counts_only_artifact_damage(catalog):
    """The artifact share is tracked as the damage happens, because the source
    may be gone by the time the spell resolves."""
    card = _artifact(
        "Reverse Polarity",
        "You gain X life, where X is twice the damage dealt to you so far this "
        "turn by artifacts.",
        type_line="Instant",
    )
    p1 = PlayerState(name="P1", hand=[card])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game._deal_damage_to_player(p1, 3, source=Permanent(card=catalog["Sol Ring"]))
    game._deal_damage_to_player(p1, 2, source=Permanent(card=catalog["Grizzly Bears"]))
    assert p1.artifact_damage_taken_this_turn == 3
    assert p1.damage_taken_this_turn == 5

    before = p1.life
    game.cast_from_hand(0, "Reverse Polarity")

    assert p1.life == before + 6          # twice the artifact damage only


@pytest.mark.parametrize("hand,expected_damage", [(0, 3), (1, 2), (3, 0), (5, 0)])
def test_the_rack_damages_the_shortfall_not_the_excess(catalog, hand, expected_damage):
    """The Rack is Black Vise's mirror: damage for the cards a player is
    *missing*, not the ones they are holding. Both floor at zero — neither
    card heals."""
    rack = _artifact(
        "The Rack",
        "As this artifact enters, choose an opponent.\n"
        "At the beginning of the chosen player's upkeep, this artifact deals X "
        "damage to that player, where X is 3 minus the number of cards in their hand.",
    )
    permanent = Permanent(card=rack)
    permanent.metadata["chosen_player_index"] = 1
    p1 = PlayerState(name="P1", battlefield=[permanent])
    p2 = PlayerState(name="P2", hand=[catalog["Forest"]] * hand)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.resolve_upkeep(1)

    assert p2.life == 20 - expected_damage


@pytest.mark.parametrize("hand,expected_damage", [(7, 3), (5, 1), (4, 0), (2, 0)])
def test_black_vise_still_damages_the_excess(catalog, hand, expected_damage):
    """The mirror card must not have changed the original. Generalising Black
    Vise's rule into one regex covering both directions changed which rule the
    coverage script attributed its sentence to and left an existing card's text
    unclaimed — so the two are separate rules lowering to one kind."""
    vise = catalog["Black Vise"]
    permanent = Permanent(card=vise)
    permanent.metadata["chosen_player_index"] = 1
    p1 = PlayerState(name="P1", battlefield=[permanent])
    p2 = PlayerState(name="P2", hand=[catalog["Forest"]] * hand)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.resolve_upkeep(1)

    assert p2.life == 20 - expected_damage
