"""Core Set 2021 (M21) instants.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- The quantifier round: "up to N" is not one target ----------------------


def test_rewind_untap_lowers_to_a_resolution_time_choice(set_pool):
    """The retreat this test used to pin is over: "Untap up to four lands."
    compiled halved (one land), then refused by name, and now lowers to
    ``untap_up_to_matching`` — a pending choice on resolution, because no
    "target" is printed and nothing is chosen at cast."""
    program = compile_card_oracle(set_pool("M21")["Rewind"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == ["counter_top_stack_spell", "untap_up_to_matching"]
    assert steps[1].payload == {"amount": 4, "filter": {"type_filter": "land"}}


# --- The exile round: exile as a destination (CR 406.1 / 400.3) -------------


def test_return_to_nature_third_mode_is_no_longer_a_dead_mode(set_pool):
    """Return to Nature reported *supported* on its first two modes while the
    third lowered to nothing — a mode the UI offered and the spell then
    silently did not play. A modal card is supported when its modes are, and
    one mode carrying no instruction is what hid it."""
    program = compile_card_oracle(set_pool("M21")["Return to Nature"])
    assert program.supported
    assert [mode.supported for mode in program.modes] == [True, True, True]
    assert program.modes[2].instruction.kind == "exile_target_graveyard_card"


def test_return_to_nature_exiles_a_card_from_a_graveyard(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Return to Nature"]])
    p2 = PlayerState(name="P2", graveyard=[pool["Concordia Pegasus"]])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(
        0, "Return to Nature", target_player_index=1,
        target_permanent_index=0, mode_index=2,
    )

    assert result.supported, result.details
    assert not p2.graveyard
    assert [c.name for c in p2.exile] == ["Concordia Pegasus"]


def test_a_plain_exile_sends_the_card_to_its_owners_exile(set_pool):
    """CR 400.3: the exiled card goes to its *owner's* exile, which is not the
    seat that was targeted once the permanent has been stolen."""
    pool = set_pool("M21")
    victim = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    from engine.oracle import OracleInstruction
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS

    EFFECT_HANDLERS["exile_target_permanent"](
        game,
        OracleInstruction("exile_target_permanent", "", {"type_filter": "creature"}),
        OracleExecutionContext(
            caster=p1, target=p2, card=pool["Angelic Ascension"],
            target_permanent_index=0,
        ),
    )

    assert [c.name for c in p2.exile] == ["Concordia Pegasus"]
    assert not p1.exile
    assert not p2.graveyard  # exiled, not destroyed
    assert not list(game.controlled_by(1))


def test_opt_no_longer_drops_its_scry(set_pool):
    """Regression for a *silent* wrong: Opt compiled supported on the strength
    of "Draw a card." alone while "Scry 1." produced no instruction at all, so
    the card played as a strictly worse Opt. Both sentences must be claimed."""
    kinds = [i.kind for i in compile_card_oracle(set_pool("M21")["Opt"]).instructions]
    assert "scry" in kinds
    assert "draw_controller_cards" in kinds


def test_opt_scries_before_it_draws(set_pool):
    """The behavioural half of the test above, and two rounds' worth of bug.

    Compiling both sentences was necessary and not sufficient: the resolver ran
    the first instruction and stopped, so cast for real Opt scried and never
    drew. With every line resolved, the scry then has to *precede* the draw —
    the draw takes whatever the scry left on top, which is only observable
    because arming the scry suspends the steps behind it.
    """
    opt = set_pool("M21")["Opt"]
    library = [set_pool("M21")[n] for n in ("Shock", "Opt", "Revitalize", "Eliminate")]
    p1 = PlayerState(name="P1", hand=[opt], library=library)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, "Opt", target_player_index=1)

    assert game.pending_choices_of("scry", 0), "the scry is owed"
    assert p1.hand == [], "the draw has not run in front of it"

    # Put the looked-at card (Shock) on the bottom; the draw must take Opt.
    assert game.confirm_scry(0, card_order=[0], bottom_count=1) is True

    assert [c.name for c in p1.hand] == ["Opt"]
    assert [c.name for c in p1.library] == ["Revitalize", "Eliminate", "Shock"]
    assert any(c.name == "Opt" for c in p1.graveyard), "and the spell finished"


def test_revitalize_gains_life_and_draws(set_pool):
    """The same fix without a prompt in the middle: two printed lines, both of
    which have to happen. It gained the life and never drew."""
    revitalize = set_pool("M21")["Revitalize"]
    p1 = PlayerState(name="P1", hand=[revitalize], library=[set_pool("M21")["Shock"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Revitalize", target_player_index=1)

    assert p1.life == 23
    assert [c.name for c in p1.hand] == ["Shock"]


def test_defiant_strike_pumps_and_draws(set_pool):
    """And the same with a target on the first line: the second line still runs
    once the first has resolved against its target."""
    strike = set_pool("M21")["Defiant Strike"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(
        name="P1", hand=[strike], battlefield=[mine], library=[set_pool("M21")["Shock"]]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    base = mine.effective_power
    game.cast_from_hand(0, "Defiant Strike", target_player_index=0, target_permanent_index=0)

    assert mine.effective_power == base + 1
    assert [c.name for c in p1.hand] == ["Shock"]


# --- The mana-value round: a literal bound rides the payload ----------------


def test_eliminate_compiles_with_its_mana_value_bound(set_pool):
    program = compile_card_oracle(set_pool("M21")["Eliminate"])
    assert program.supported
    destroy = next(i for i in program.instructions if i.kind == "destroy_target_permanent")
    assert destroy.payload["mana_value"] == {"op": "le", "value": 3}


def test_eliminate_refuses_a_four_drop(set_pool):
    """The bound is enforced at cast validation, not just carried."""
    eliminate = set_pool("M21")["Eliminate"]
    cheap = Permanent(card=set_pool("M21")["Concordia Pegasus"])   # MV 2
    big = Permanent(card=set_pool("M21")["Warden of the Woods"])   # MV 5
    p1 = PlayerState(name="P1", hand=[eliminate])
    p2 = PlayerState(name="P2", battlefield=[cheap, big])
    game = Game(players=[p1, p2])

    ok, _ = game._validate_cast_targets(
        eliminate, 0, target_player_index=1, target_permanent_index=1
    )
    assert not ok
    ok, msg = game._validate_cast_targets(
        eliminate, 0, target_player_index=1, target_permanent_index=0
    )
    assert ok, msg


def test_rangers_guile_grants_hexproof_for_the_turn(set_pool):
    guile = set_pool("M21")["Ranger's Guile"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[guile])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Ranger's Guile", target_player_index=0, target_permanent_index=0)

    assert mine.has_keyword("hexproof")
    bolt = set_pool("M21")["Shock"]
    assert game._can_be_targeted(mine, bolt, caster_index=1) is False
    assert game._can_be_targeted(mine, bolt, caster_index=0) is True


def test_rewind_counters_and_lets_its_caster_untap_up_to_four_lands(set_pool):
    """"Untap up to four lands." prints no "target": the lands are chosen on
    resolution through the pending-choice queue, not at cast."""
    pool = set_pool("M21")
    lands = [Permanent(card=pool["Island"], tapped=True) for _ in range(3)]
    p1 = PlayerState(name="P1", hand=[pool["Rewind"]], battlefield=lands)
    p2 = PlayerState(name="P2", hand=[pool["Shock"]])
    game = Game(players=[p1, p2])
    queued = game.queue_from_hand(1, "Shock", target_player_index=0)
    assert queued.supported, queued.details
    result = game.cast_from_hand(0, "Rewind")
    assert result.supported, result.details
    # The counter half already resolved; the untap half is waiting on picks.
    assert not game.stack
    assert any(c.name == "Shock" for c in p2.graveyard)
    pending = game.pending_choices_of("untap_up_to", 0)
    assert pending and pending[0].data["amount"] == 4
    ids = [game.permanent_id_of(perm) for perm in lands[:2]]
    assert game.confirm_untap_up_to(0, ids)
    assert [perm.tapped for perm in lands] == [False, False, True]


def test_rewind_rejects_more_picks_than_printed(set_pool):
    pool = set_pool("M21")
    lands = [Permanent(card=pool["Island"], tapped=True) for _ in range(5)]
    p1 = PlayerState(name="P1", battlefield=lands)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "untap_up_to", 0, amount=4, filter={"type_filter": "land"}, card_name="Rewind",
    )
    ids = [game.permanent_id_of(perm) for perm in lands]
    assert not game.confirm_untap_up_to(0, ids), "five picks against 'up to four'"
    assert all(perm.tapped for perm in lands), "nothing moved on a rejected answer"
    assert game.confirm_untap_up_to(0, ids[:4])


def test_scorching_dragonfire_exiles_what_it_kills(set_pool):
    pool = set_pool("M21")
    victim = Permanent(card=pool["Concordia Pegasus"])  # 1/3
    p1 = PlayerState(name="P1", hand=[pool["Scorching Dragonfire"]])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Scorching Dragonfire", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(victim)
    assert any(c.name == "Concordia Pegasus" for c in p2.exile)
    assert not any(c.name == "Concordia Pegasus" for c in p2.graveyard)


def test_soul_sear_strips_indestructible_before_the_damage_kills(set_pool):
    from engine.keywords import grant_keyword

    pool = set_pool("M21")
    tough = Permanent(card=pool["Concordia Pegasus"])
    grant_keyword(tough, "indestructible")
    p1 = PlayerState(name="P1", hand=[pool["Soul Sear"]])
    p2 = PlayerState(name="P2", battlefield=[tough])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Soul Sear", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(tough), (
        "5 damage kills a 1/3 whose indestructible was removed by the rider"
    )


def test_life_goes_on_gains_eight_only_over_a_body(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Life Goes On"], pool["Life Goes On"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    assert game.cast_from_hand(0, "Life Goes On").supported
    assert p1.life == 24
    game.creatures_died_this_turn = 1
    assert game.cast_from_hand(0, "Life Goes On").supported
    assert p1.life == 32, "a creature died this turn, so the 8-life arm applies"


def test_angelic_ascension_hands_the_angel_to_a_walkers_controller(set_pool):
    pool = set_pool("M21")
    walker = Permanent(
        card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4},
    )
    p1 = PlayerState(name="P1", hand=[pool["Angelic Ascension"]])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Angelic Ascension", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Garruk, Unleashed" for c in p2.exile)
    angels = [p for p in p2.battlefield if p.card.name == "Angel Token"]
    assert len(angels) == 1
    assert angels[0].effective_power == 4


def test_unsubstantiate_returns_a_spell_from_the_stack_unbinned(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Shock"]])
    p2 = PlayerState(name="P2", hand=[pool["Unsubstantiate"]])
    game = Game(players=[p1, p2])
    queued = game.queue_from_hand(0, "Shock", target_player_index=1)
    assert queued.supported, queued.details
    result = game.cast_from_hand(1, "Unsubstantiate", target_stack_index=0)
    assert result.supported, result.details
    # The spell went back to its owner's hand — not the graveyard, so it was
    # never countered and can be cast again.
    assert [c.name for c in p1.hand] == ["Shock"]
    assert not any(c.name == "Shock" for c in p1.graveyard)
    assert not game.stack
    assert p2.life == 20, "the returned Shock never resolved"


def test_unsubstantiate_bounces_a_creature_when_one_was_chosen(set_pool):
    pool = set_pool("M21")
    bear = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", hand=[pool["Unsubstantiate"]])
    p2 = PlayerState(name="P2", battlefield=[bear])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Unsubstantiate", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bear)
    assert [c.name for c in p2.hand] == ["Pridemalkin"]


def test_miscast_counters_an_instant_that_goes_unpaid(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Shock"]])
    p2 = PlayerState(name="P2", hand=[pool["Miscast"]])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Shock", target_player_index=1)
    result = game.cast_from_hand(1, "Miscast", target_stack_index=0)
    assert result.supported, result.details
    # With nothing to pay {3} from, the Shock is countered and never resolves.
    assert not game.stack
    assert any(c.name == "Shock" for c in p1.graveyard)
    assert p2.life == 20


def test_miscast_cannot_touch_a_creature_spell(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Miscast"])
    assert program.supported, program.reason
    p1 = PlayerState(name="P1", hand=[pool["Concordia Pegasus"]])
    p2 = PlayerState(name="P2", hand=[pool["Miscast"]])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Concordia Pegasus")
    from engine.targeting import derive_cast_spec

    spec = derive_cast_spec(pool["Miscast"], program)
    assert spec == {"kind": "stack", "stack_card_types": ["instant", "sorcery"]}
    assert game._enumerate_stack_targets(pool["Miscast"], spec) == [], (
        "a creature spell is not offered to an instant-or-sorcery counter"
    )


def test_heroic_intervention_shields_a_land_as_well_as_a_creature(set_pool):
    """The grant's only difference from the creature one is who is in the
    loop — hexproof is read by the targeting check and indestructible by the
    destroy check, and neither asks what type the permanent is."""
    pool = set_pool("M21")
    land = Permanent(card=pool["Forest"])
    creature = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(
        name="P1", battlefield=[land, creature], hand=[pool["Heroic Intervention"]]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Heroic Intervention")
    assert result.supported, result.details
    game._settle()

    for perm in (land, creature):
        assert game._is_indestructible(perm)
        assert not game._can_be_targeted(perm, None, caster_index=1)
        assert game._can_be_targeted(perm, None, caster_index=0), (
            "hexproof stops opponents, not the controller (CR 702.11b)"
        )


# --- "Double" reads the board at resolution ---------------------------------


@pytest.mark.parametrize("name", ["Unleash Fury", "Invigorating Surge"])
def test_round_37_doubling_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_unleash_fury_doubles_the_power_the_creature_has_now(set_pool):
    """A pump's amount is fixed when the effect is created; this one is read at
    resolution — so a creature already at 6 goes to 12, not to 4. That is the
    whole reason it is its own node rather than a Pump."""
    pool = set_pool("M21")
    beast = Permanent(card=pool["Alpine Watchdog"])   # 2/2
    p1 = PlayerState(
        name="P1", battlefield=[beast],
        hand=[pool["Titanic Growth"], pool["Unleash Fury"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Titanic Growth", target_player_index=0, target_permanent_index=0)
    game._settle()
    assert (beast.effective_power, beast.effective_toughness) == (6, 6)

    game.cast_from_hand(0, "Unleash Fury", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert beast.effective_power == 12
    assert beast.effective_toughness == 6, "power only — the noun is checked, not consumed"


def test_invigorating_surge_doubles_the_counter_it_just_placed(set_pool):
    """The rider reads *after* the placement, so the counter this spell put down
    is doubled too: 0 → 1 → 2, then 2 → 3 → 6."""
    pool = set_pool("M21")
    beast = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(
        name="P1", battlefield=[beast],
        hand=[pool["Invigorating Surge"], pool["Invigorating Surge"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Invigorating Surge", target_player_index=0, target_permanent_index=0)
    game._settle()
    assert beast.metadata["plus_counters"] == 2
    assert (beast.effective_power, beast.effective_toughness) == (4, 4)

    game.cast_from_hand(0, "Invigorating Surge", target_player_index=0, target_permanent_index=0)
    game._settle()
    assert beast.metadata["plus_counters"] == 6
    assert (beast.effective_power, beast.effective_toughness) == (8, 8)


def test_the_doubled_counters_go_through_the_replacement_seam(set_pool):
    """Round 31 made placing counters an event; the doubling is placed through
    the same seam, so Conclave Mentor raises it exactly as it raises the first
    counter (CR 614.1c). 1 counter → +1 = 2 placed; doubling 2 → +2, raised to
    3, for 5."""
    pool = set_pool("M21")
    beast = Permanent(card=pool["Alpine Watchdog"])
    mentor = Permanent(card=pool["Conclave Mentor"])
    p1 = PlayerState(
        name="P1", battlefield=[beast, mentor],
        hand=[pool["Invigorating Surge"]], library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Invigorating Surge", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert beast.metadata["plus_counters"] == 5


def test_a_durationless_doubling_and_a_doubled_toughness_both_refuse(set_pool):
    """Two refusals worth keeping. A permanent doubling is a continuous effect
    the layer system would have to own, and doubling toughness is a different
    effect — consuming the noun without checking it is how one card's
    production quietly claims another's."""
    assert not compile_line("Double the power of target creature.").lowered
    assert not compile_line("Double the toughness of target creature until end of turn.").parsed


# --- The additional-cost round ----------------------------------------------


def test_village_rites_eats_a_creature_and_draws_two(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature." /
    "Draw two cards."

    Nothing in the effect refers back to the creature, which is why the cost
    was never paid: the sentence matched a spell-pattern substring, the marker
    it produced had no handler, and the card reported supported while casting
    for its mana cost alone.
    """
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool["Alpine Watchdog"])],
        hand=[pool["Village Rites"]], library=[pool["Swamp"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Village Rites")

    assert [p.card.name for p in p1.battlefield] == []
    assert len(p1.hand) == 2


def test_thrill_of_possibility_discards_then_draws(set_pool):
    """The other cost shape. The spell is on the stack while its cost is paid
    (CR 601.2a), so with one other card in hand there is exactly one legal
    payment — the spell can never discard itself."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Thrill of Possibility"], pool["Mountain"]],
        library=[pool["Swamp"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Thrill of Possibility")

    assert [c.name for c in p1.graveyard] == ["Mountain", "Thrill of Possibility"]
    assert len(p1.hand) == 2
