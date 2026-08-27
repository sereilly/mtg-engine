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
from engine.targeting import derive_cast_spec


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
    assert game._enumerate_stack_targets(1, pool["Miscast"], spec) == [], (
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


# --- Round 56: the sacrifice's noun phrase, read by the noun parser ---------


def _run_afoul_board(set_pool):
    pool = set_pool("M21")
    hound = Permanent(card=pool["Alpine Watchdog"])
    singer = Permanent(card=pool["Mistral Singer"])  # flying
    p1 = PlayerState(name="P1", hand=[pool["Run Afoul"]])
    p2 = PlayerState(name="P2", battlefield=[hound, singer])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2, hound, singer


def test_run_afoul_takes_a_flier_and_leaves_the_ground_creature(set_pool):
    """"Target opponent sacrifices a creature of their choice with flying."

    Three words the engine could not read until this round, in one sentence: the
    payer is a *targeted* player rather than the caster, "of their choice" says
    who picks, and "with flying" narrows what may be picked. The narrowing is the
    load-bearing one — dropped, the Watchdog is a legal answer and the spell
    reads as a strictly better card."""
    game, p1, p2, hound, singer = _run_afoul_board(set_pool)

    game.cast_from_hand(0, "Run Afoul", target_player_index=1)

    assert game.is_on_battlefield(hound), "no flying, so not a legal sacrifice"
    assert not game.is_on_battlefield(singer)


def test_run_afoul_with_no_flier_takes_nothing(set_pool):
    """The control. CR 701.21b: a player asked to sacrifice something they do
    not control sacrifices nothing — the spell still resolves, and the ground
    creature is not a consolation prize."""
    game, p1, p2, hound, singer = _run_afoul_board(set_pool)
    game.remove_from_battlefield(singer)

    game.cast_from_hand(0, "Run Afoul", target_player_index=1)

    assert game.is_on_battlefield(hound)


def test_run_afoul_may_not_choose_its_own_caster(set_pool):
    """"Target **opponent**" (CR 115.4). The payload keeps the two targeted
    forms apart for exactly this: the handler resolves both to the seat the
    spell chose, so only the picker can tell "target opponent" from "target
    player", and collapsing them would offer the caster their own seat."""
    game, p1, p2, hound, singer = _run_afoul_board(set_pool)
    card = p1.hand[0]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {"kind": "player", "opponents_only": True}
    offered = game._enumerate_targets(0, card, spec, for_cast=True)
    assert [t["seat"] for t in offered] == [1]


# --- Round 62: a count as an amount -----------------------------------------


def test_frantic_inventory_counts_its_own_copies(set_pool):
    """"Draw a card, then draw cards equal to the number of cards named Frantic
    Inventory in your graveyard."

    Three things met here, and none of them was the draw: the noun before the
    count ("draw **cards** equal to…", where every other draw puts it behind),
    a card *name* as a restriction on a noun phrase, and a count that **is** an
    amount rather than one that defines an X for the sentence around it."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        library=[pool["Island"]] * 10,
        hand=[pool["Frantic Inventory"]],
        graveyard=[pool["Frantic Inventory"], pool["Frantic Inventory"], pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Frantic Inventory")
    game._settle()

    assert len(p1.hand) == 3, "one, then one per copy already in the graveyard"


def test_frantic_inventory_ignores_a_graveyard_of_other_cards(set_pool):
    """The narrowing. Dropping the name would count the whole graveyard, which
    is the direction that makes the card better than it is — and the count is
    taken at *resolution* (CR 608.2), so it is the graveyard as it stands."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        library=[pool["Island"]] * 10,
        hand=[pool["Frantic Inventory"]],
        graveyard=[pool["Island"], pool["Shock"], pool["Alpine Watchdog"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Frantic Inventory")
    game._settle()

    assert len(p1.hand) == 1


def test_two_counts_cannot_share_one_x():
    """The constraint the round had to design around. One resolution has one
    ``context.x_value``, so a sentence with a where-clause *and* a counted
    amount would have the two overwrite each other silently. Neither reading is
    the card."""
    result = compile_line(
        "Draw cards equal to the number of Islands you control, "
        "where x is the number of Swamps you control."
    )

    assert result.parsed and not result.lowered
    assert result.failure_reason == "two counts cannot share one X"


# --- Round 63: a choice made as the effect resolves -------------------------


def _gift_board(set_pool, *, interactive: bool):
    pool = set_pool("M21")
    watchdog = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(
        name="P1", battlefield=[watchdog], hand=[pool["Alchemist's Gift"]]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = {0}
    return game, p1, watchdog


def test_alchemists_gift_offers_the_two_keywords(set_pool):
    """"Target creature gets +1/+1 and gains **your choice of** deathtouch or
    lifelink until end of turn."

    A choice between two effects is what ``choose_one`` already is — the
    composition seam a modal ability uses — so this needed no prompt of its own.
    The labels are the keywords, and the seat that was asked picks."""
    game, p1, watchdog = _gift_board(set_pool, interactive=True)

    game.cast_from_hand(
        0, "Alchemist's Gift", target_player_index=0, target_permanent_index=0
    )
    game._settle()
    pending = game.pending_choices_of("mode_choice", 0)
    assert pending, "the choice should be offered"
    assert pending[0].data["labels"] == ["deathtouch", "lifelink"]

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)

    assert (watchdog.effective_power, watchdog.effective_toughness) == (3, 3)
    assert game._has_keyword(watchdog, "lifelink")
    assert not game._has_keyword(watchdog, "deathtouch"), "one keyword, not both"


def test_a_seat_that_is_not_asked_takes_the_first_printed(set_pool):
    """The stated policy `choose_one` already carries, inherited rather than
    invented: the first printed option, which is a policy and not a valuation.
    A card whose AI should pick otherwise needs one."""
    game, p1, watchdog = _gift_board(set_pool, interactive=False)

    game.cast_from_hand(
        0, "Alchemist's Gift", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert game._has_keyword(watchdog, "deathtouch")
    assert not game._has_keyword(watchdog, "lifelink")


def test_a_choice_of_keywords_is_not_a_list_of_them():
    """The distinction the AST has to carry. "gains deathtouch **and** lifelink"
    and "gains your choice of deathtouch **or** lifelink" reach the keyword
    reader as the same tuple, so the alternatives are marked where the words
    are still there — otherwise the card grants both."""
    both = compile_line("Target creature gains deathtouch and lifelink until end of turn.")
    assert [i.kind for i in both.instructions] == ["grant_target_keyword_until_eot"]
    assert both.instructions[0].payload["keywords"] == ("deathtouch", "lifelink")

    either = compile_line(
        "Target creature gains your choice of deathtouch or lifelink until end of turn."
    )
    assert [i.kind for i in either.instructions] == ["choose_one"]
    assert [m["label"] for m in either.instructions[0].payload["modes"]] == [
        "deathtouch", "lifelink"
    ]


def test_a_choice_of_one_keyword_refuses():
    """"Your choice of" with nothing to choose between is a misread sentence,
    not a grant."""
    result = compile_line("Target creature gains your choice of flying until end of turn.")

    assert not result.parsed


# --- The two-target round: a leading duration and a second chosen creature ---


def test_rookie_mistake_compiles_to_one_two_slot_pump(set_pool):
    """Two things were missing and only one of them was the second target.

    The printed duration is in the *leading* position, which no production read
    â€” "Until end of turn, target creature gets +0/+2." refused on its own â€” and
    the two clauses name two different creatures, which two ``sequence`` steps
    cannot express because every single-target handler resolves through
    ``_one_choice`` and reads the first entry of the target list."""
    program = compile_card_oracle(set_pool("M21")["Rookie Mistake"])

    assert program.supported, program.reason
    instruction = program.instructions[0]
    assert instruction.kind == "pump_targets_until_eot"
    assert instruction.payload["slots"] == (
        {"power": 0, "toughness": 2},
        {"power": -2, "toughness": 0},
    )
    targets = instruction.payload["targets"]
    assert targets["count"] == 2
    assert targets["distinct"] is True, "the printed 'another' (CR 601.2c)"
    assert targets["filters"] == [
        {"type_filter": "creature"},
        {"type_filter": "creature"},
    ]


def test_rookie_mistake_names_two_targets_to_the_picker(set_pool):
    """Both slots are a bare "target creature", so neither narrows the prompt
    and both battlefields are offered."""
    pool = set_pool("M21")
    card = pool["Rookie Mistake"]
    pegasus = pool["Concordia Pegasus"]
    p1 = PlayerState(name="P1", hand=[card], battlefield=[Permanent(card=pegasus)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pegasus)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    spec = game.cast_target_spec(0, card)

    assert spec["max_targets"] == 2
    assert "own_only" not in spec
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}


def test_rookie_mistake_pumps_one_creature_and_shrinks_another(set_pool):
    """The two slots are resolved positionally and may sit on two battlefields
    â€” the ids are what address them, because an index is positional on one
    seat."""
    pool = set_pool("M21")
    pegasus = pool["Concordia Pegasus"]          # 1/3
    mine = Permanent(card=pegasus)
    theirs = Permanent(card=pegasus)
    p1 = PlayerState(name="P1", hand=[pool["Rookie Mistake"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(
        0, "Rookie Mistake",
        target_player_index=0,
        target_permanent_index=[0, 0],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    assert result.supported, result.details
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (1, 5)
    assert (theirs.effective_power, theirs.effective_toughness) == (-1, 3)


def test_rookie_mistake_drops_a_slot_that_stopped_answering(set_pool):
    """Why the handler resolves its slots positionally rather than through
    ``resolve_target_permanents``.

    That resolver *compacts* â€” it drops a decayed slot without padding â€” so a
    positional reader would hand the surviving second creature the first slot's
    +0/+2. Here the first target leaves while the spell is on the stack: the
    second must still shrink, and must not grow (CR 608.2b)."""
    pool = set_pool("M21")
    pegasus = pool["Concordia Pegasus"]
    mine = Permanent(card=pegasus)
    theirs = Permanent(card=pegasus)
    p1 = PlayerState(name="P1", hand=[pool["Rookie Mistake"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.queue_from_hand(
        0, "Rookie Mistake",
        target_player_index=0,
        target_permanent_index=[0, 0],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    game.remove_from_battlefield(mine)
    game._settle()

    assert (theirs.effective_power, theirs.effective_toughness) == (-1, 3)


def test_rookie_mistake_never_boosts_and_shrinks_the_same_creature(set_pool):
    """The printed "another" at resolution (CR 601.2c/608.2b).

    The picker cannot select one permanent twice, but the enumeration is a hint
    and the engine re-checks the answer: a client sending the same id in both
    slots gets the first slot only, never both effects on one creature."""
    pool = set_pool("M21")
    only = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Rookie Mistake"]], battlefield=[only])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Rookie Mistake",
        target_player_index=0,
        target_permanent_index=[0, 0],
        target_permanent_ids=[only.permanent_id, only.permanent_id],
    )
    game._settle()

    assert (only.effective_power, only.effective_toughness) == (1, 5), \
        "the +0/+2 alone; the second slot named a creature the first already took"


def test_two_targeted_pumps_without_another_refuse():
    """The near miss, which must keep failing loudly.

    CR 601.2c lets two instances of the word "target" name the same object, so
    without the printed "another" the sentence needs a picker told about two
    slots. The ordinary step lowering would emit two single-target pumps that
    both read the first chosen id, so a card printed that way is refused by name
    rather than silently double-pumping one creature."""
    compiled = compile_line(
        "Until end of turn, target creature gets +0/+2 and target creature gets -2/-0.",
        card_name="Not A Real Card",
    )

    assert compiled.instructions == ()
    assert compiled.lowering_error is not None
    assert "another" in compiled.lowering_error


def test_a_leading_duration_reaches_both_clauses():
    """A leading "Until end of turn," in front of a conjunction has to reach
    both halves. The trailing spelling attaches to the clause it follows, which
    is why that spelling of the same sentence keeps refusing: its first pump has
    no duration at all, and a durationless pump is a continuous effect."""
    leading = compile_line(
        "Until end of turn, target creature gets +0/+2 and another target creature gets -2/-0.",
        card_name="Not A Real Card",
    )
    trailing = compile_line(
        "Target creature gets +0/+2 and another target creature gets -2/-0 until end of turn.",
        card_name="Not A Real Card",
    )

    assert leading.instructions and leading.instructions[0].kind == "pump_targets_until_eot"
    assert trailing.instructions == ()
    assert trailing.lowering_error is not None


def test_a_leading_duration_does_not_take_the_cast_permissions(set_pool):
    """The production that nearly cost two cards.

    Placed before ``_parse_cast_permission``, the leading-duration branch
    consumes "Until end of turn," and then fails on "you may play cards exiled
    this way", which has no duration field to attach to. The branch belongs
    after it."""
    pool = set_pool("M21")
    for name in ("Chandra, Heart of Fire", "Chandra, Flame's Catalyst"):
        assert compile_card_oracle(pool[name]).supported, name


def test_the_ai_shrinks_the_opponents_creature_not_its_own(set_pool):
    """``_choose_several_targets`` takes the maximum from one battlefield,
    preferring the caster's. That is right for every card printed with the
    template before this one, because each gives a benefit per target; Rookie
    Mistake's second slot is a penalty, so the one-seat policy made the AI
    shrink its own creature. Which slot wants which board is *derived* from the
    compiled program (the sign of the slot's P/T delta), never from the name."""
    from engine.ai_policy import choose_cast_action

    pool = set_pool("M21")
    pegasus = pool["Concordia Pegasus"]
    mine = Permanent(card=pegasus)
    theirs = Permanent(card=pegasus)
    p1 = PlayerState(name="P1", hand=[pool["Rookie Mistake"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Rookie Mistake"
    assert action.target_permanent_ids == [mine.permanent_id, theirs.permanent_id]


def test_the_several_target_policy_is_unchanged_where_every_slot_agrees(set_pool):
    """The AI change must be invisible to every card that existed before it.
    Basri's Acolyte's two slots are both "you control", so the single-seat path
    still answers and the ids stay absent."""
    from engine.ai_policy import choose_cast_action

    pool = set_pool("M21")
    pegasus = pool["Concordia Pegasus"]
    p1 = PlayerState(
        name="P1", hand=[pool["Basri's Acolyte"]],
        battlefield=[Permanent(card=pegasus) for _ in range(3)],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.target_permanent_ids is None


# --- Round 71: the keyword grant reads the noun phrase it was given ---------


def test_rangers_guile_grants_hexproof_only_to_a_creature_you_control(set_pool):
    """"Target creature **you control** gets +1/+1 and gains hexproof until end
    of turn."

    ``grant_target_keyword_until_eot`` read no filter at all, so the second half
    of this sentence handed hexproof to an opponent's creature whenever the
    announcement did not come through the picker. Selfless Savior is why the
    handler now asks; Ranger's Guile is the card that was already wrong.

    The pump half is a separate handler with the same omission, so this pins
    only what round 71 changed."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Ranger's Guile"], pool["Ranger's Guile"]],
                     battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    # Naming the opponent's creature is refused as the spell is cast now
    # (CR 601.2c, `legality.cast_target_refusal`) rather than resolving into a
    # grant the handler then declines to make. Both halves are asserted: the
    # announcement is refused, and nothing was granted by way of it.
    refused = game.cast_from_hand(
        0, "Ranger's Guile", target_player_index=1, target_permanent_index=0,
    )
    assert not refused.supported
    game._settle()
    assert not theirs.has_keyword("hexproof")
    assert not mine.has_keyword("hexproof")

    # …and the legal announcement still grants it, so the filter is pinned in
    # both directions rather than only by an effect that did nothing.
    granted = game.cast_from_hand(
        0, "Ranger's Guile", target_player_index=0, target_permanent_index=0,
    )
    assert granted.supported, granted.details
    game._settle()

    assert mine.has_keyword("hexproof")
    assert not theirs.has_keyword("hexproof")


# --- Round 75: two targets tapped, and a marker that waits per controller ----


def _frost_board(set_pool):
    """The caster's creature and an opponent's, both untapped."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Frost Breath"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, mine, theirs


def _cast_frost_breath(game, *targets):
    return game.cast_from_hand(
        0, "Frost Breath",
        target_player_index=0,
        target_permanent_index=[0] * len(targets),
        target_permanent_ids=[t.permanent_id for t in targets],
    )


def test_frost_breath_compiles_to_a_tap_and_a_marker(set_pool):
    """Two sentences, two instructions, composed rather than fused: the second
    acts on whatever the first chose, which is what the scratchpad record is
    for."""
    program = compile_card_oracle(set_pool("M21")["Frost Breath"])

    assert program.supported, program.reason
    (sequence,) = program.instructions
    tap, marker = sequence.payload["steps"]
    assert tap.kind == "tap_target_permanent"
    assert tap.payload["targets"]["count"] == 2
    assert marker.kind == "skip_next_untap"
    assert marker.payload["permanents_from"] == "tapped_permanents"


def test_frost_breath_taps_both_and_holds_each_through_its_own_untap_step(set_pool):
    """"â€¦during **their controller's** next untap step" is per creature, not per
    caster (CR 502.3). Two creatures under two controllers each wait for their
    own controller's step, and the marker expires there whether or not it kept
    anything tapped (CR 611.2a; CR 701.43b says the same of exert)."""
    game, mine, theirs = _frost_board(set_pool)

    result = _cast_frost_breath(game, mine, theirs)
    assert result.supported, result.details
    game._settle()
    assert (mine.tapped, theirs.tapped) == (True, True)

    game.resolve_untap_step(0)
    assert mine.tapped, "held through its controller's next untap step"
    game.resolve_untap_step(1)
    assert theirs.tapped, "and so is the one on the other board"

    game.resolve_untap_step(0)
    assert not mine.tapped, "the marker lasted exactly one untap step"
    game.resolve_untap_step(1)
    assert not theirs.tapped


def test_frost_breath_may_name_one_creature(set_pool):
    """"Up to two" may legally name fewer (CR 601.2c), and the marker follows
    the tap rather than the printed maximum."""
    game, mine, theirs = _frost_board(set_pool)

    _cast_frost_breath(game, theirs)
    game._settle()

    assert (mine.tapped, theirs.tapped) == (False, True)
    game.resolve_untap_step(1)
    assert theirs.tapped
    assert not mine.metadata.get("skip_next_untap")


def test_frost_breath_refuses_more_targets_than_it_prints(set_pool):
    """CR 601.2c: the number of targets is what the card printed. The picker and
    the AI both cap themselves, so this is the re-check of a number they were
    told â€” and before it, a cast naming three was accepted and the handler
    silently capped at two."""
    pool = set_pool("M21")
    game, mine, theirs = _frost_board(set_pool)
    third = Permanent(card=pool["Alpine Watchdog"])
    game.players[1].battlefield.append(third)

    result = _cast_frost_breath(game, mine, theirs, third)

    assert not result.supported
    assert "too many targets" in result.details
    assert (mine.tapped, theirs.tapped, third.tapped) == (False, False, False)


def test_the_marker_sentence_refuses_with_no_tap_before_it():
    """A back-reference names its producer or refuses (idiom #7). The handler
    reads the affected permanents out of the resolution scratchpad, so with
    nothing recorded it would mark nothing while the card compiled clean."""
    result = compile_line(
        "Those creatures don't untap during their controller's next untap step.",
        card_name="Test",
    )

    assert result.parsed and not result.lowered
    assert "no producer in this effect" in result.failure_reason


def test_the_permanent_wording_is_not_the_same_effect():
    """Dropping "next" turns the sentence into the *permanent* restriction
    ``engine/auras.py`` derives for Paralyze â€” a strictly larger effect â€” so the
    word is required rather than decorative."""
    result = compile_line(
        "Tap up to two target creatures. Those creatures don't untap during "
        "their controller's untap step.",
        card_name="Test",
    )

    assert not result.usable


def test_the_ai_taps_the_opponents_creatures_not_its_own(set_pool):
    """A several-target tap is a denial, so every slot wants an opponent's
    permanent. The single-seat fallback prefers the caster's own board, which is
    round 65's bug arriving through a different effect family â€” and the reach is
    derived from the instruction kind, never from the card's name."""
    from engine.ai_policy import choose_cast_action

    game, _mine, _theirs = _frost_board(set_pool)

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Frost Breath"
    assert action.target_player_index == 1


# --- Round 81: one counter, two amounts -------------------------------------


def _denial_game(set_pool, *, with_flier):
    pool = set_pool("M21")
    battlefield = [Permanent(card=pool["Concordia Pegasus"])] if with_flier else []
    p1 = PlayerState(name="P1", hand=[pool["Lofty Denial"]], battlefield=battlefield)
    p2 = PlayerState(name="P2", hand=[pool["Shock"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Shock", target_player_index=0)
    game.queue_from_hand(0, "Lofty Denial", target_stack_index=0)
    return game, p1


def _demanded(game):
    return next((line for line in game.log if "must pay" in line), "")


def test_lofty_denial_compiles_to_one_counter_with_a_replacement_amount(set_pool):
    """Two sentences, **one** instruction.

    Lowered as two steps the card counters twice and asks its victim to pay
    twice, which is a different and much worse card. The second sentence adds no
    effect â€” it replaces a number in the first â€” so the two fuse, and the
    replacement rides beside the printed amount rather than becoming a branch.
    """
    program = compile_card_oracle(set_pool("M21")["Lofty Denial"])

    assert program.supported, program.reason
    (counter,) = [i for i in program.instructions if i.kind == "counter_top_stack_spell"]
    assert counter.payload["unless_pays_amount"] == 1
    assert counter.payload["unless_pays_if"] == {
        "condition": {
            "kind": "controls",
            "who": "you",
            "filter": {"type_filter": "creature", "with_keywords": ["flying"]},
        },
        "amount": 4,
    }


def test_lofty_denial_demands_one_without_a_flier(set_pool):
    game, _p1 = _denial_game(set_pool, with_flier=False)
    game._settle()

    assert "must pay {1}" in _demanded(game)


def test_lofty_denial_demands_four_with_a_flier(set_pool):
    game, _p1 = _denial_game(set_pool, with_flier=True)
    game._settle()

    assert "must pay {4}" in _demanded(game)


def test_the_amount_is_read_at_resolution_not_at_cast(set_pool):
    """CR 608.2: the condition is checked as the spell resolves, so a flier that
    dies in response changes what its victim owes. A lowering that branched at
    cast time would have fixed the number when Lofty Denial went on the stack."""
    game, p1 = _denial_game(set_pool, with_flier=True)
    game.remove_from_battlefield(p1.battlefield[0])
    game._settle()

    assert "must pay {1}" in _demanded(game)


def test_a_second_counter_without_instead_refuses():
    """The near miss, and why the word is recorded rather than consumed. Two
    counters in one line that are genuinely two effects would ask the spell's
    controller to pay twice; no card prints it, and fusing them silently would
    drop one."""
    result = compile_line(
        "Counter target spell unless its controller pays {1}. If you control a "
        "creature with flying, counter that spell unless its controller pays {4}.",
        card_name="Test",
    )

    assert not result.usable


def test_instead_refuses_on_a_freshly_chosen_spell():
    """"Instead" replaces an amount an earlier sentence named. On a new target
    there is nothing to replace, so the sentence refuses rather than reading the
    word as decoration."""
    result = compile_line(
        "Counter target spell unless its controller pays {4} instead.",
        card_name="Test",
    )

    assert not result.usable


# --- Round 97: protection from a colour chosen as it resolves ---------------


def _feat_board(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Gale Swooper"])
    p1 = PlayerState(
        name="P1", battlefield=[mine], hand=[pool["Feat of Resistance"]]
    )
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=pool["Chandra's Magmutt"])]
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, mine


def test_feat_of_resistance_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Feat of Resistance"])
    assert program.supported, program.reason


def test_a_granted_protection_was_refused_for_its_argument(set_pool):
    """The defect this round found. "Protection from black" is the keyword
    *protection* carrying a quality (CR 702.16a); the grant gate compared the
    whole compound string against a registry that lists the ability — so **every**
    granted protection was refused as an unimplemented keyword, while a printed
    one had worked since the keyword gate was written."""
    from engine.grammar import compile_line

    result = compile_line("It gains protection from black until end of turn.")

    assert result.lowered, result.failure_reason
    assert result.instructions[0].payload["keywords"] == ("protection from black",)


def test_the_counter_and_the_protection_both_land(set_pool):
    game, _p1, mine = _feat_board(set_pool)

    result = game.cast_from_hand(
        0, "Feat of Resistance",
        target_player_index=0, target_permanent_index=0, new_color="R",
    )
    assert result.supported, result.details
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (4, 3)
    assert ("color", "R") in game._protection_qualities(mine)


def test_the_colour_is_the_one_chosen_and_not_a_default(set_pool):
    """CR 609.3: the choice is made as the effect resolves, so the keyword
    cannot name it — it names the *choice*, and the grant resolves it."""
    game, _p1, mine = _feat_board(set_pool)

    game.cast_from_hand(
        0, "Feat of Resistance",
        target_player_index=0, target_permanent_index=0, new_color="U",
    )
    game._settle()

    assert ("color", "U") in game._protection_qualities(mine)
    assert ("color", "R") not in game._protection_qualities(mine)


def test_no_colour_chosen_protects_from_nothing(set_pool):
    """A protection the player did not pick is a protection from the wrong
    things, so nothing is granted rather than a default colour being invented.
    The +1/+1 counter still happens — CR 608.2's "as much as it can"."""
    game, _p1, mine = _feat_board(set_pool)

    game.cast_from_hand(
        0, "Feat of Resistance", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (4, 3)
    assert game._protection_qualities(mine) == set()


def test_the_protection_expires_with_the_turn(set_pool):
    """"Until end of turn" — swept by prefix at cleanup, because the key is one
    per colour rather than a fixed name."""
    game, _p1, mine = _feat_board(set_pool)
    game.cast_from_hand(
        0, "Feat of Resistance",
        target_player_index=0, target_permanent_index=0, new_color="R",
    )
    game._settle()
    assert game._protection_qualities(mine)

    game.resolve_cleanup_step(0)

    assert game._protection_qualities(mine) == set()


# --- Discontinuity: the turn ends (round 110) -------------------------------


def test_discontinuity_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Discontinuity"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions][0] == "end_the_turn"


def test_discontinuity_costs_less_during_your_turn(set_pool):
    """The other line, which was already implemented and is checked here so the
    card is covered rather than half-covered: "During your turn, this spell
    costs {2}{U}{U} less to cast." reduces {3}{U}{U}{U} to {1}{U}."""
    from engine.cost_modifiers import CostReduction, cost_reduction_for_cast

    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Discontinuity"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.active_player_index = 0
    reduction, names = cost_reduction_for_cast(game, 0, pool["Discontinuity"])
    assert reduction == CostReduction(2, (("U", 2),))
    assert names == ["Discontinuity"]

    # "During **your** turn" is a fact about whose turn it is, not about who is
    # casting: on the opponent's turn the same caster gets nothing off.
    game.active_player_index = 1
    assert cost_reduction_for_cast(game, 0, pool["Discontinuity"]) == (
        CostReduction(0, ()), [],
    )


# --- Round 135: a spell that takes several of its modes ---------------------


def test_sublime_epiphany_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Sublime Epiphany"])
    assert program.supported, program.reason


def test_sublime_epiphany_reads_five_modes_and_says_several_may_be_taken(set_pool):
    """All five, and the bound beside them. The mode list alone cannot say the
    card takes more than one, and the cast path refuses a second mode without
    it — so a program with the modes and not the bound is a spell that reads
    right and plays as "Choose one"."""
    program = compile_card_oracle(set_pool("M21")["Sublime Epiphany"])

    assert [m.instruction.kind for m in program.modes] == [
        "counter_top_stack_spell",
        "counter_stack_ability",
        "bounce_target_creature",
        "create_copy_token",
        "draw_target_cards",
    ]
    assert program.modes_at_least is True


def _epiphany_board(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])          # 2/2 vigilance
    theirs = Permanent(card=pool["Garruk's Gorehorn"])      # 5 mana value
    p1 = PlayerState(name="P1", hand=[pool["Sublime Epiphany"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs], library=[pool["Shock"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    return game, p1, p2, mine, theirs


def test_sublime_epiphany_performs_every_mode_it_was_given(set_pool):
    """Three modes in one cast, each with its own target (CR 601.2c): the bounce
    names the opponent's permanent, the copy names the caster's, and the draw
    names a seat. One target field could not have said all three."""
    game, p1, p2, mine, theirs = _epiphany_board(set_pool)

    result = game.cast_from_hand(
        0, "Sublime Epiphany",
        mode_choices=[
            {"index": 2, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 3, "target_player_index": 0, "target_permanent_index": 0},
            {"index": 4, "target_player_index": 1},
        ],
    )
    assert result.supported, result.details

    assert [c.name for c in p2.hand] == ["Garruk's Gorehorn", "Shock"]
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Alpine Watchdog", "Alpine Watchdog",
    ]
    assert list(game.controlled_by(1)) == []


def test_sublime_epiphanys_token_is_a_copy_and_a_token(set_pool):
    """CR 707.2 and CR 111.1 are both true of it: the copied creature's power,
    toughness and keywords, and ``is_token`` so it ceases to exist rather than
    going to a graveyard."""
    game, p1, p2, mine, theirs = _epiphany_board(set_pool)

    game.cast_from_hand(
        0, "Sublime Epiphany",
        mode_choices=[{"index": 3, "target_player_index": 0, "target_permanent_index": 0}],
    )

    token = next(p for p in game.controlled_by(0) if p.metadata.get("is_token"))
    assert token.effective_card.name == "Alpine Watchdog"
    assert (token.effective_power, token.effective_toughness) == (2, 2)
    assert token.has_keyword("vigilance")


def test_sublime_epiphany_copies_only_a_creature_you_control(set_pool):
    """"target creature **you control**" is half the mode: a copy of an
    opponent's creature is a different and much better spell. The same board
    copies the caster's own, so what is being read is the seat."""
    game, p1, p2, mine, theirs = _epiphany_board(set_pool)

    game.cast_from_hand(
        0, "Sublime Epiphany",
        mode_choices=[{"index": 3, "target_player_index": 1, "target_permanent_index": 0}],
    )
    assert not any(p.metadata.get("is_token") for p in game.controlled_by(0))

    p1.hand.append(set_pool("M21")["Sublime Epiphany"])
    game.cast_from_hand(
        0, "Sublime Epiphany",
        mode_choices=[{"index": 3, "target_player_index": 0, "target_permanent_index": 0}],
    )
    assert any(p.metadata.get("is_token") for p in game.controlled_by(0))


def test_sublime_epiphany_counters_an_ability_on_the_stack(set_pool):
    """CR 701.5a: the ability is removed from the stack and does nothing. Not a
    spell — an ability has no card, so there is nothing to put in a graveyard."""
    from engine.oracle_types import OracleInstruction

    game, p1, p2, mine, theirs = _epiphany_board(set_pool)
    game._enqueue_triggered_ability(
        controller_index=1, source_permanent=theirs,
        instruction=OracleInstruction("gain_life", "", {"amount": 5}),
        effect_kind="triggered_life",
    )
    assert len(game.stack) == 1

    game.cast_from_hand(
        0, "Sublime Epiphany", mode_choices=[{"index": 1, "target_stack_index": 0}],
    )

    assert game.stack == []
    assert p2.life == 20, "countered, so it never resolved"
    assert p2.graveyard == [], "an ability has no card to bin"


def test_sublime_epiphanys_ability_counter_refuses_a_spell(set_pool):
    """The two counter modes are different cards' worth of effect, and the
    difference is what the phrase names. Mode 1 aimed at a spell counters
    nothing; mode 0 on the same board counters it."""
    pool = set_pool("M21")
    for mode, expect_countered in ((1, False), (0, True)):
        p1 = PlayerState(name="P1", hand=[pool["Sublime Epiphany"]])
        p2 = PlayerState(name="P2", hand=[pool["Shock"]], life=20)
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = False
        game.active_player_index = 1
        game.queue_from_hand(1, "Shock", target_player_index=0)

        game.cast_from_hand(
            0, "Sublime Epiphany",
            mode_choices=[{"index": mode, "target_stack_index": 0}],
        )
        game._settle()

        assert (p1.life == 20) is expect_countered, (
            f"mode {mode} should {'' if expect_countered else 'not '}counter a spell"
        )
