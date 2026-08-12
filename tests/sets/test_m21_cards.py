"""Per-card tests for Core Set 2021 (M21) — a *measured* set, mid-implementation.

Cards land here with the round that buys them (tests/sets/README.md,
SET_PLAYBOOK.md Phase 3). The pool resolves through ``set_pool("M21")`` even
though the set is not shipped: reading a card file is not shipping it, and a
card's focused test is written while its set is still under ``measured``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- The keyword round: flash, menace, hexproof(+from), prowess, ------------
# --- deathtouch, indestructible ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Mistral Singer",       # Flying // Prowess
        "Masked Blackguard",    # Flash // pump ability
        "Bone Pit Brute",       # Menace // ETB pump
        "Ornery Dilophosaur",   # Deathtouch // conditional attack trigger
    ],
)
def test_keyword_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_bone_pit_brute_cannot_be_blocked_by_one_creature(set_pool):
    brute = Permanent(card=set_pool("M21")["Bone Pit Brute"])
    blocker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[brute])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers

    ok, msg = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "menace" in msg.lower()


def test_mistral_singer_pumps_on_a_noncreature_cast(set_pool):
    singer = Permanent(card=set_pool("M21")["Mistral Singer"])
    opt = set_pool("M21")["Opt"]
    p1 = PlayerState(
        name="P1", battlefield=[singer], hand=[opt],
        library=[set_pool("M21")["Island"], set_pool("M21")["Island"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Opt")

    assert singer.effective_power == 3  # 2/2 printed, +1/+1 from prowess
    assert singer.effective_toughness == 3


def test_masked_blackguard_casts_at_instant_speed(set_pool):
    assert set_pool("M21")["Masked Blackguard"].has_flash


# --- The token-naming round: CR 111.4 names unnamed tokens ------------------


@pytest.mark.parametrize(
    "name",
    [
        "Valorous Steed",         # ETB: 2/2 white Knight token with vigilance
        "Deathbloom Thallid",     # dies: 1/1 green Saproling token
        "Falconer Adept",         # attacks: 1/1 white Bird token — still gated
        "Goblin Wizardry",        # two 1/1 red Wizard tokens with prowess
        "Sporeweb Weaver",        # dealt damage: gain 1 life + Saproling token
        "Speaker of the Heavens", # {T}: 4/4 white Angel token, conditional
    ],
)
def test_token_round_cards_compile_supported(set_pool, name):
    if name == "Falconer Adept":
        pytest.skip("still gated on the tapped-and-attacking rider")
    assert compile_card_oracle(set_pool("M21")[name]).supported


# --- The each-opponent round: damage and life loss sweep the table ----------


@pytest.mark.parametrize(
    "name",
    [
        "Storm Caller",           # ETB: deals 2 damage to each opponent
        "Spirit of Malevolence",  # dies: each opponent loses 1 life
        "Grim Tutor",             # tutor + "You lose 3 life"
        "Caged Zombie",           # activated: each opponent loses 2 life
    ],
)
def test_each_opponent_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_storm_caller_damages_each_opponent_on_entry(set_pool):
    caller = set_pool("M21")["Storm Caller"]
    p1 = PlayerState(name="P1", hand=[caller])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Storm Caller")

    assert p2.life == 18
    assert p1.life == 20


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


def test_targeted_several_taps_are_still_refused_rather_than_halved():
    """The *targeted* family stays refused: "tap up to two target creatures"
    names cast-time targets no tap handler resolves as a list. Rewind's
    untargeted spelling is the one that got a lowering, and the ``targeted``
    flag on the spec is what keeps the two apart."""
    result = compile_line("Tap up to two target creatures.", card_name="Test")

    assert result.parsed
    assert not result.lowered
    assert result.failure_reason == "no handler taps or untaps several targets"


# --- The multi-target round: "each of up to N target ..." -------------------


@pytest.mark.parametrize(
    "line",
    [
        "Put a +1/+1 counter on each of up to two target creatures.",
        "Put a +1/+1 counter on up to two target creatures.",
        "Put a +1/+1 counter on each of up to two other target creatures you control.",
    ],
)
def test_counters_on_several_targets_carry_their_maximum(line):
    """All three spellings are one instruction with the count on the payload.

    "each of" is a distributive wrapper over the noun phrase, not a quantifier,
    and "other" prints *before* the word "target" in the middle spelling — the
    one position the object-filter parser cannot reach. The count is what a
    picker reads to collect more than one; it used to be dropped, which is why
    the lowering refused rather than countering one creature and calling the
    card done."""
    result = compile_line(line, card_name="Test")

    assert result.lowered, result.failure_reason
    instruction = result.instructions[0]
    assert instruction.kind == "add_counter_to_target"
    assert instruction.payload["targets"]["count"] == 2


def test_basris_acolyte_counters_the_two_creatures_it_targeted(set_pool):
    """The card the round bought. Three creatures, two named: exactly those two
    get counters, and the Acolyte's own "other" keeps it off its own list."""
    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    mine = [Permanent(card=pegasus) for _ in range(3)]
    theirs = Permanent(card=pegasus)
    p1 = PlayerState(name="P1", hand=[acolyte], battlefield=list(mine))
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    base = pegasus and mine[0].effective_power

    game.cast_from_hand(
        0, "Basri's Acolyte", target_player_index=0, target_permanent_index=[0, 2]
    )

    assert [p.effective_power for p in mine] == [base + 1, base, base + 1]
    assert theirs.effective_power == base, "the opponent's creature was not touched"


def test_basris_acolyte_offers_only_its_controllers_creatures(set_pool):
    """The picker's half. "you control" is a seat test, so it narrows the
    enumeration rather than being left to the handler to decline silently after
    the player has already clicked."""
    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    p1 = PlayerState(name="P1", hand=[acolyte], battlefield=[Permanent(card=pegasus)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pegasus)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    spec = game.cast_target_spec(0, acolyte)

    assert spec["max_targets"] == 2
    assert spec["own_only"] is True
    assert {t["seat"] for t in spec["valid_targets"]} == {0}


def test_the_ai_names_as_many_targets_as_the_card_allows(set_pool):
    """Which cards this reaches is derived from the compiled program, never a
    list of names — so a card printed with the same template is covered the day
    it is ingested."""
    from engine.ai_policy import choose_cast_action

    acolyte = set_pool("M21")["Basri's Acolyte"]
    pegasus = set_pool("M21")["Concordia Pegasus"]
    p1 = PlayerState(
        name="P1", hand=[acolyte],
        battlefield=[Permanent(card=pegasus), Permanent(card=pegasus), Permanent(card=pegasus)],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Basri's Acolyte"
    assert action.target_permanent_index == [0, 1], "two of the three, the maximum"
    assert action.target_player_index == 0


def test_up_to_one_target_is_still_a_single_target():
    """"Up to one target creature" chooses one target or none — exactly what a
    handler reading one id does. Narrowing "several" must not take it away."""
    result = compile_line(
        "Put a +1/+1 counter on up to one target creature.", card_name="Test"
    )

    assert result.lowered, result.failure_reason
    described = result.instructions[0].payload["targets"]
    assert described["quantifier"] == "up_to"
    assert described["filter"]["type_filter"] == "creature"


# --- The tracker round: a turn's history, and CR 603.4 -----------------------


def test_indulging_patrician_compiles_supported(set_pool):
    assert compile_card_oracle(set_pool("M21")["Indulging Patrician"]).supported


def test_life_gained_this_turn_counts_and_resets(set_pool):
    """"This turn" is *the turn*, not the player's turn: lifelink on an
    opponent's turn is life you gained this turn. A counter that never resets
    is a bug that first appears on turn two, firing off last turn's gains."""
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])

    game._gain_life(p1, 2)
    game._gain_life(p1, 1)
    assert p1.life_gained_this_turn == 3

    game.begin_turn_bookkeeping(1)
    assert p1.life_gained_this_turn == 0, "every seat resets, not just the active one"


def test_creature_deaths_are_counted_under_the_seat_that_controlled_them(set_pool):
    """The game-wide counter cannot answer "under your control" — it is one
    number for the whole table."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Concordia Pegasus"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    game._permanent_to_graveyard(p1, mine)
    game._permanent_to_graveyard(p2, theirs)

    assert p1.creatures_died_under_your_control_this_turn == 1
    assert p2.creatures_died_under_your_control_this_turn == 1
    assert game.creatures_died_this_turn == 2

    game.begin_turn_bookkeeping(1)
    assert p1.creatures_died_under_your_control_this_turn == 0


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


# --- The cost round: non-mana activation costs ------------------------------


@pytest.mark.parametrize("name", ["Hobblefiend", "Seasoned Hallowblade"])
def test_cost_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_hobblefiend_sacrifices_the_named_creature_and_keeps_itself(set_pool):
    pool = set_pool("M21")
    fiend = Permanent(card=pool["Hobblefiend"])
    keep = Permanent(card=pool["Concordia Pegasus"])
    food = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[fiend, keep, food])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    before = fiend.effective_power

    result = game.activate_permanent_ability(
        0, "Hobblefiend", permanent_index=0, cost_permanent_index=2,
    )

    assert result.supported, result.details
    # The *named* creature paid, not the first look-alike on the battlefield.
    assert not any(perm is food for perm in game.controlled_by(0))
    assert any(perm is keep for perm in game.controlled_by(0))
    assert any(perm is fiend for perm in game.controlled_by(0))
    assert fiend.effective_power == before + 1


def test_hobblefiend_alone_cannot_activate_and_does_not_eat_itself(set_pool):
    """CR 602.5c: an unpayable cost makes the ability unactivatable — not free,
    and not payable with the source the word "another" excludes."""
    fiend = Permanent(card=set_pool("M21")["Hobblefiend"])
    p1 = PlayerState(name="P1", battlefield=[fiend])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    before = fiend.effective_power

    result = game.activate_permanent_ability(0, "Hobblefiend", permanent_index=0)

    assert not result.supported
    assert "sacrifice" in result.details.lower()
    assert any(perm is fiend for perm in game.controlled_by(0))
    assert fiend.effective_power == before


def test_seasoned_hallowblade_discards_the_named_card_and_taps(set_pool):
    pool = set_pool("M21")
    blade = Permanent(card=pool["Seasoned Hallowblade"])
    keep, pitch = pool["Opt"], pool["Island"]
    p1 = PlayerState(name="P1", battlefield=[blade], hand=[keep, pitch])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Seasoned Hallowblade", permanent_index=0, cost_hand_index=1,
    )

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == [keep.name]
    assert p1.graveyard[-1].name == pitch.name
    assert blade.tapped
    assert blade.has_keyword("indestructible")


def test_seasoned_hallowblade_cannot_activate_with_an_empty_hand(set_pool):
    blade = Permanent(card=set_pool("M21")["Seasoned Hallowblade"])
    p1 = PlayerState(name="P1", battlefield=[blade])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Seasoned Hallowblade", permanent_index=0)

    assert not result.supported
    assert not blade.tapped


def test_portcullis_vine_is_refused_rather_than_sacrificing_any_creature(set_pool):
    """"Sacrifice a creature with defender" is a cost the charger cannot
    express, so the card is unsupported with the clause named — dropping the
    rider would let the Vine eat any creature and still read as supported."""
    program = compile_card_oracle(set_pool("M21")["Portcullis Vine"])
    assert not program.supported
    assert "defender" in program.reason


# --- The search round: the filter the flow honours, and the two-zone fetch ---


@pytest.mark.parametrize(
    "name",
    [
        "Fierce Empath",        # search for a creature with mana value 6+
        "Chandra's Firemaw",    # library and/or graveyard, for a named card
        "Garruk's Warsteed",
        "Teferi's Wavecaster",
        "Liliana's Scorn",
    ],
)
def test_search_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_a_search_refuses_a_card_its_restriction_excludes(set_pool):
    """The engine is the authority on what may be found, not the client that
    offered the cards: an index outside the restriction is simply refused."""
    pool = set_pool("M21")
    big = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc >= 6)
    small = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc < 6)
    p1 = PlayerState(name="P1", library=[small, big])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="creature",
        zones=("library",), restrictions={"mana_value": {"op": "ge", "value": 6}},
    )

    assert not game.confirm_search_library(0, 0)
    assert p1.hand == []
    assert game.pending_search_library is not None

    assert game.confirm_search_library(0, 1)
    assert [c.name for c in p1.hand] == [big.name]
    assert game.pending_search_library is None


def test_a_search_that_can_find_nothing_can_still_be_left(set_pool):
    """Failing to find is legal (CR 701.19b) and is the only answer available
    when nothing in the searched zones matches."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", library=[pool["Island"], pool["Island"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={"named": "Fierce Empath"},
    )

    assert game.decline_search_library(0)
    assert p1.hand == []
    assert len(p1.library) == 2
    assert game.pending_search_library is None


def test_a_search_cannot_be_answered_with_a_zone_it_was_not_armed_with(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", library=[pool["Island"]], graveyard=[pool["Alpine Watchdog"]]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={},
    )

    assert not game.confirm_search_library(0, 0, "graveyard")
    assert p1.hand == []
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog"]


def test_a_graveyard_find_does_not_shuffle_the_library(set_pool):
    """CR 701.19d and the printed "If you search your library this way,
    shuffle": a graveyard is an open zone, so randomising a library the player
    did not search would destroy information they were entitled to keep."""
    pool = set_pool("M21")
    wanted = pool["Alpine Watchdog"]
    library = [pool["Island"], pool["Forest"], pool["Mountain"]]
    p1 = PlayerState(name="P1", library=list(library), graveyard=[wanted])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library", "graveyard"), restrictions={"named": "alpine watchdog"},
    )

    assert game.confirm_search_library(0, 0, "graveyard")
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert p1.graveyard == []
    assert [c.name for c in p1.library] == [c.name for c in library]


# --- The scry round (CR 701.22), and mill's recipient -----------------------


@pytest.mark.parametrize("name", ["Wall of Runes", "Spined Megalodon"])
def test_scry_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


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


def test_temple_of_mystery_etb_scry_is_claimed(set_pool):
    program = compile_card_oracle(set_pool("M21")["Temple of Mystery"])
    assert any(
        t.instruction is not None and t.instruction.kind == "scry"
        for t in program.triggered_abilities
    )


def test_carrion_grub_etb_mills_its_own_controller(set_pool):
    """"Mill four cards." — a bare imperative, so the miller is the effect's
    controller and travels on the same `recipient` key life loss uses, rather
    than as a target the handler would read off `context.target`.

    Asserted on the line rather than the card: Carrion Grub's *other* line
    ("gets +X/+0, where X is the greatest power among creature cards in your
    graveyard") still refuses, and a refused line stops the creature compiling
    at all — so the card stays unsupported while this line is done.
    """
    grub = set_pool("M21")["Carrion Grub"]
    line = next(l for l in grub.oracle_text.split("\n") if "mill" in l)
    result = compile_line(line, card_name="Carrion Grub")

    assert result.lowered, result.failure_reason
    mill = result.instructions[0]
    assert mill.kind == "mill_target_player"
    assert mill.payload["recipient"] == "caster"
    assert mill.payload["amount"] == 4
    assert "targets" not in mill.payload  # a bare mill targets nobody
    assert not compile_card_oracle(grub).supported


def test_track_down_still_refuses_its_reveal_clause(set_pool):
    """Scry 3 parses now, but "then reveal the top card of your library" has no
    production — the sentence refuses whole rather than scrying and dropping
    the rest."""
    assert not compile_card_oracle(set_pool("M21")["Track Down"]).supported


# --- The causative round: "you may have <subject> <verb> ..." ---------------


@pytest.mark.parametrize("name", ["Goblin Arsonist", "Battle-Rattle Shaman"])
def test_causative_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_goblin_arsonist_may_ping_when_it_dies(set_pool):
    """"You may have it deal 1 damage to any target" — the may wrapper arms
    the standard optional prompt, and accepting deals the damage."""
    arsonist = Permanent(card=set_pool("M21")["Goblin Arsonist"])
    p1 = PlayerState(name="P1", battlefield=[arsonist])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(arsonist)
    game._permanent_to_graveyard(p1, arsonist)
    game.resolve_top_of_stack()

    assert any(e["card_name"] == "Goblin Arsonist" for e in game.pending_optional_pays)
    game.confirm_optional_pay(0, "Goblin Arsonist", accept=True)
    assert p2.life == 19


# --- The trigger-narrowing round: conditions carry their own restrictions ---


def test_quirion_dryad_counters_only_the_listed_colours(set_pool):
    """"Whenever you cast a spell that's white, blue, black, or red" — a green
    spell is not in the list, so it must not fire the trigger."""
    dryad = Permanent(card=set_pool("M21")["Quirion Dryad"])
    red = set_pool("M21")["Shock"]
    green = set_pool("M21")["Titanic Growth"]
    p1 = PlayerState(name="P1", battlefield=[dryad], hand=[red, green])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    base = dryad.effective_power

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1

    game.cast_from_hand(0, "Titanic Growth", target_player_index=0, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1 + 4  # the +4/+4 pump lands, the counter does not


def test_adherent_of_hope_triggers_only_on_its_controllers_combat(set_pool):
    """The trigger *condition* is the controller's combat — a separate question
    from the intervening-if below, which decides whether the resolution does
    anything."""
    adherent = Permanent(card=set_pool("M21")["Adherent of Hope"])
    p1 = PlayerState(name="P1", battlefield=[adherent])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat, controller's turn
    assert game.stack, "the trigger fires on its controller's combat"
    game.resolve_top_of_stack()

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # opponent's combat
    assert not game.stack, "and not on anyone else's"


def test_adherent_of_hope_does_nothing_without_its_basri_planeswalker(set_pool):
    """CR 603.4. The printed line is "…**if you control a Basri planeswalker**,
    put a +1/+1 counter on this creature", and the condition was lowered onto
    the payload and read by nothing — so the counter landed every combat. It is
    checked on resolution now, and with no Basri in play the ability does
    nothing at all."""
    adherent = Permanent(card=set_pool("M21")["Adherent of Hope"])
    p1 = PlayerState(name="P1", battlefield=[adherent])
    game = Game(players=[p1, PlayerState(name="P2")])
    base = adherent.effective_power

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.resolve_top_of_stack()

    assert adherent.effective_power == base


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


# --- The keyword-grant round: "gains <keyword> until end of turn" -----------


@pytest.mark.parametrize(
    "name",
    [
        "Sure Strike",     # +3/+0 and gains first strike
        "Ranger's Guile",  # your creature gains hexproof
        "Fetid Imp",       # {B}: this creature gains deathtouch
    ],
)
def test_keyword_grant_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


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


# --- The counter round: +1/+1 counters on non-source subjects ---------------


def test_basris_solidarity_counters_each_of_your_creatures(set_pool):
    """"Put a +1/+1 counter on each creature you control." — the sweep counts
    the caster's side only, through the control seam."""
    solidarity = set_pool("M21")["Basri's Solidarity"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    theirs = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[solidarity])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    base_mine = mine.effective_power
    base_theirs = theirs.effective_power
    game.cast_from_hand(0, "Basri's Solidarity")

    assert mine.effective_power == base_mine + 1
    assert theirs.effective_power == base_theirs


def test_valorous_steed_token_takes_its_cr_111_4_name(set_pool):
    program = compile_card_oracle(set_pool("M21")["Valorous Steed"])
    create = next(
        trig.instruction
        for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "create_token"
    )
    assert create.payload["name"] == "Knight Token"
    assert create.payload["keywords"] == ("Vigilance",)


# --- The planeswalker round: loyalty, emblems, delayed triggers, phasing ----


@pytest.mark.parametrize(
    "name",
    [
        "Ugin, the Spirit Dragon",
        "Basri Ket",
        "Teferi, Master of Time",
        "Liliana, Waker of the Dead",
        "Garruk, Unleashed",
        "Basri, Devoted Paladin",
        "Teferi, Timeless Voyager",
        "Liliana, Death Mage",
        "Garruk, Savage Herald",
    ],
)
def test_planeswalker_round_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


@pytest.mark.parametrize(
    "name",
    [
        # Formerly the two walkers held honest by
        # test_chandras_report_the_unbuilt_permission_seam: both needed the
        # cast/play-from-exile-or-graveyard permission seam, which now exists
        # (engine/cast_permissions.py).
        "Chandra, Heart of Fire",
        "Chandra, Flame's Catalyst",
    ],
)
def test_chandras_compile_through_the_permission_seam(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_chandra_heart_of_fire_plus_one_permits_playing_the_exiled_cards(set_pool):
    """+1: the hand goes, the top three go to exile, and exactly those three
    are castable/playable from exile until end of turn."""
    pool = set_pool("M21")
    shock, pegasus = pool["Shock"], pool["Concordia Pegasus"]
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire",
        hand=[pegasus], library=[shock, pegasus, pegasus, pegasus],
    )
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details
    me = game.players[0]
    assert me.hand == []
    # The discarded Pegasus went to the graveyard, not exile; the top three
    # library cards (Shock + two Pegasi) were exiled; the fourth stayed.
    assert len(me.exile) == 3
    assert [card.name for card in me.graveyard] == ["Concordia Pegasus"]
    assert len(me.library) == 1
    exiled_names = [card.name for card in me.exile]
    assert exiled_names.count("Shock") == 1
    # Shock was among the exiled three and is castable from exile at the
    # opponent's face; the fourth library card stayed put and is not.
    cast = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18


def test_chandra_heart_of_fire_permission_ends_at_cleanup(set_pool):
    pool = set_pool("M21")
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire",
        library=[pool["Shock"], pool["Shock"], pool["Shock"], pool["Shock"]],
    )
    assert game.activate_permanent_ability(0, walker.card.name, ability_index=0).supported
    game.resolve_cleanup_step(0)
    refused = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert not refused.supported
    assert "601.3" in refused.details


def test_chandra_heart_of_fire_ultimate_adds_no_mana_until_the_search_is_answered(set_pool):
    """−9: the search suspends the rest of the resolution — "You may cast them
    this turn." and "Add six {R}." run only once the picks are in (the Opt
    lesson, CR 608.2n's cousin for loyalty abilities)."""
    pool = set_pool("M21")
    shock, pegasus = pool["Shock"], pool["Concordia Pegasus"]
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire", loyalty=9,
        library=[pegasus, shock], graveyard=[shock],
    )
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    me = game.players[0]
    pending = game.pending_choices_of("search_exile_cards", 0)
    assert pending, "the two-zone search should be waiting on its picks"
    assert me.mana_pool.get("R", 0) == 0
    # Take the Shock from each zone; the Pegasus is not red and not legal.
    ok = game.confirm_search_exile(0, [
        {"zone": "graveyard", "index": 0},
        {"zone": "library", "index": 1},
    ])
    assert ok
    assert me.mana_pool.get("R", 0) == 6
    assert [card.name for card in me.exile].count("Shock") == 2
    cast = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18


def test_chandra_flames_catalyst_minus_two_casts_it_then_exiles_it(set_pool):
    """−2: the targeted graveyard card becomes castable, and the printed rider
    routes it to exile instead of back to the graveyard when it leaves the
    stack (CR 614.1a)."""
    pool = set_pool("M21")
    shock = pool["Shock"]
    game, walker = _walker_game(
        set_pool, "Chandra, Flame's Catalyst", graveyard=[shock],
    )
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    cast = game.cast_from_hand(0, "Shock", from_zone="graveyard", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18
    me = game.players[0]
    assert [card.name for card in me.exile] == ["Shock"]
    assert all(card.name != "Shock" for card in me.graveyard)


def test_chandra_flames_catalyst_minus_eight_waives_mana_costs_until_end_of_turn(set_pool):
    pool = set_pool("M21")
    shock = pool["Shock"]
    game, walker = _walker_game(
        set_pool, "Chandra, Flame's Catalyst", loyalty=9,
        hand=[pool["Concordia Pegasus"]], library=[shock] * 8,
    )
    game.enforce_mana_costs = True
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    me = game.players[0]
    assert len(me.hand) == 7  # hand discarded, seven drawn
    # An empty pool casts Shock anyway: the waiver covers it.
    cast = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18
    # CR 514.2: the waiver ends at cleanup; the next Shock needs real mana.
    game.resolve_cleanup_step(0)
    refused = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert not refused.supported
    assert "insufficient mana" in refused.details


def _walker_game(set_pool, name, loyalty=None, opp_battlefield=None, hand=None, library=None, graveyard=None):
    card = set_pool("M21")[name]
    walker = Permanent(card=card, metadata={"loyalty_counters": int(loyalty or card.loyalty)})
    p1 = PlayerState(
        name="P1", battlefield=[walker], hand=list(hand or []),
        library=list(library or []), graveyard=list(graveyard or []),
    )
    p2 = PlayerState(name="P2", battlefield=list(opp_battlefield or []))
    return Game(players=[p1, p2]), walker


def test_teferi_master_of_time_takes_two_extra_turns(set_pool):
    game, walker = _walker_game(set_pool, "Teferi, Master of Time", loyalty=12)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    assert game.extra_turn_queue.count(0) == 2


def test_teferi_master_of_time_activates_on_an_opponents_turn(set_pool):
    game, walker = _walker_game(set_pool, "Teferi, Master of Time")
    game.active_player_index = 1
    game.players[0].library = [set_pool("M21")["Concordia Pegasus"]] * 2
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details


def test_teferi_master_of_time_phases_out_an_opposing_creature(set_pool):
    bear = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game, walker = _walker_game(set_pool, "Teferi, Master of Time", opp_battlefield=[bear])
    original_id = bear.permanent_id
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bear)
    assert any(p is bear for p in game.players[1].phased_out)
    # CR 702.26e: it phases in at its controller's untap step, the same object.
    game.resolve_untap_step(1)
    assert game.is_on_battlefield(bear)
    assert bear.permanent_id == original_id


def test_liliana_waker_of_the_dead_plus_one_punishes_empty_hands(set_pool):
    game, walker = _walker_game(set_pool, "Liliana, Waker of the Dead",
                                hand=[set_pool("M21")["Concordia Pegasus"]])
    # Opponent has no hand: they cannot discard and lose 3 life.
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details
    assert game.players[1].life == 17
    assert len(game.players[0].hand) == 0


def test_liliana_death_mage_destroy_drains_the_controller(set_pool):
    bear = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game, walker = _walker_game(set_pool, "Liliana, Death Mage", opp_battlefield=[bear])
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bear)
    assert game.players[1].life == 18
    assert walker.metadata["loyalty_counters"] == 1


def test_basri_ket_minus_two_makes_attacking_soldiers(set_pool):
    game, walker = _walker_game(set_pool, "Basri Ket")
    attacker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game.players[0].battlefield.append(attacker)
    game.start_turn(0)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=1)
    assert result.supported, result.details
    assert len(game.delayed_triggers) == 1
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    attacker.metadata.pop("summoning_sickness_turn", None)
    slot = game.battlefield_index_of(attacker)
    ok, msg = game.declare_attackers(0, [slot])
    assert ok, msg
    while game.stack:
        game.resolve_top_of_stack()
    soldiers = [p for p in game.controlled_by(0) if "Soldier" in p.card.name]
    assert len(soldiers) == 1
    assert soldiers[0].tapped and soldiers[0].attacking


def test_basri_devoted_paladin_counters_each_attacker(set_pool):
    game, walker = _walker_game(set_pool, "Basri, Devoted Paladin")
    attacker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game.players[0].battlefield.append(attacker)
    game.start_turn(0)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=1)
    assert result.supported, result.details
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    attacker.metadata.pop("summoning_sickness_turn", None)
    slot = game.battlefield_index_of(attacker)
    ok, msg = game.declare_attackers(0, [slot])
    assert ok, msg
    while game.stack:
        game.resolve_top_of_stack()
    # 1/3 Pegasus with a +1/+1 counter attacks as a 2/4.
    assert attacker.effective_power == 2


def test_garruk_unleashed_emblem_tutors_at_end_step(set_pool):
    pegasus = set_pool("M21")["Concordia Pegasus"]
    game, walker = _walker_game(set_pool, "Garruk, Unleashed", loyalty=8,
                                library=[pegasus])
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    assert len(game.players[0].emblems) == 1
    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_choices()
    # Non-interactive search default: the creature is on the battlefield.
    assert any(p.card.name == "Concordia Pegasus" for p in game.controlled_by(0))


def test_ugin_minus_x_exiles_colored_permanents_by_mana_value(set_pool):
    cheap = Permanent(card=set_pool("M21")["Concordia Pegasus"])   # mv 2, white
    game, walker = _walker_game(set_pool, "Ugin, the Spirit Dragon",
                                opp_battlefield=[cheap])
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1, x_value=3,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(cheap)
    assert any(c.name == "Concordia Pegasus" for c in game.players[1].exile)
    # Ugin itself is colorless: the sweep spared it.
    assert game.is_on_battlefield(walker)
    assert walker.metadata["loyalty_counters"] == 4


def test_garruk_savage_herald_bite_compiles_to_the_two_target_kind(set_pool):
    walker_card = set_pool("M21")["Garruk, Savage Herald"]
    program = compile_card_oracle(walker_card)
    assert program.activated_abilities[1].instruction.kind == "target_bites_target"


# --- Round 20: Rewind, See the Truth, and the modal-honesty sweep -----------


@pytest.mark.parametrize(
    "name",
    ["Rewind", "See the Truth", "Read the Tides", "Pestilent Haze", "Destructive Tampering"],
)
def test_round_20_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


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


def test_see_the_truth_from_hand_keeps_one_and_bottoms_the_rest(set_pool):
    pool = set_pool("M21")
    library = [pool["Shock"], pool["Rewind"], pool["Island"], pool["Concordia Pegasus"]]
    p1 = PlayerState(name="P1", hand=[pool["See the Truth"]], library=list(library))
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "See the Truth")
    assert result.supported, result.details
    # The pick suspends the resolution: the spell is not yet in the graveyard
    # (CR 608.2n) while its controller is looking.
    assert not any(c.name == "See the Truth" for c in p1.graveyard)
    assert game.confirm_look_top_pick(0, 1)
    assert [c.name for c in p1.hand] == ["Rewind"]
    # The other two looked-at cards went under the Pegasus.
    assert [c.name for c in p1.library] == ["Concordia Pegasus", "Shock", "Island"]
    assert any(c.name == "See the Truth" for c in p1.graveyard)


def test_see_the_truth_cast_from_exile_takes_all_three(set_pool):
    """The cast-zone conditional, fed by the permission seam: cast from
    anywhere but the hand, every looked-at card goes to the hand and there is
    no choice at all."""
    from engine.cast_permissions import grant_permission

    pool = set_pool("M21")
    truth = pool["See the Truth"]
    p1 = PlayerState(
        name="P1", exile=[truth],
        library=[pool["Shock"], pool["Rewind"], pool["Island"], pool["Concordia Pegasus"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    grant_permission(
        game, player_index=0, zone="exile", mode="cast",
        cards=[truth], duration="end_of_turn", source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "See the Truth", from_zone="exile")
    assert result.supported, result.details
    assert not game.pending_choices_of("look_top_pick")
    assert sorted(c.name for c in p1.hand) == ["Island", "Rewind", "Shock"]
    assert [c.name for c in p1.library] == ["Concordia Pegasus"]


def test_read_the_tides_second_mode_bounces_both_chosen_creatures(set_pool):
    pool = set_pool("M21")
    bears = [Permanent(card=pool["Concordia Pegasus"]) for _ in range(3)]
    p1 = PlayerState(name="P1", hand=[pool["Read the Tides"]])
    p2 = PlayerState(name="P2", battlefield=list(bears))
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Read the Tides", target_player_index=1,
        target_permanent_index=[0, 2], mode_index=1,
    )
    assert result.supported, result.details
    assert len(p2.battlefield) == 1
    assert len(p2.hand) == 2


def test_pestilent_haze_second_mode_strips_loyalty_from_every_walker(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    theirs = Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 2})
    p1 = PlayerState(name="P1", hand=[pool["Pestilent Haze"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Pestilent Haze", mode_index=1)
    assert result.supported, result.details
    assert mine.metadata["loyalty_counters"] == 1
    # Garruk hit zero and the state-based sweep collected him (CR 704.5i).
    assert not game.is_on_battlefield(theirs)
    assert any(c.name == "Garruk, Unleashed" for c in p2.graveyard)


def test_destructive_tampering_second_mode_grounds_blockers_for_the_turn(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Destructive Tampering"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "Destructive Tampering", mode_index=1)
    assert result.supported, result.details
    assert game.blocking_restrictions_until_eot
    # A ground attacker, so blocking legality turns on the restriction alone:
    # the grounded cat may not block, the flyer still may ("without flying"
    # spares it, asked of layer 6).
    attacker = Permanent(card=pool["Pridemalkin"])
    grounded = Permanent(card=pool["Pridemalkin"])
    flyer = Permanent(card=pool["Concordia Pegasus"])
    assert game._can_block_attacker(flyer, attacker) is True
    assert game._can_block_attacker(grounded, attacker) is False
    # CR 514.2: the restriction ends with the turn.
    game.resolve_cleanup_step(0)
    assert not game.blocking_restrictions_until_eot
    assert game._can_block_attacker(grounded, attacker) is True


# --- Round 21: bounce and burn — riders, unions, and one history ------------


@pytest.mark.parametrize(
    "name",
    [
        "Roaming Ghostlight", "Barrin, Tolarian Archmage", "Shipwreck Dowser",
        "Scorching Dragonfire", "Soul Sear", "Life Goes On",
    ],
)
def test_round_21_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


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


def test_roaming_ghostlight_cannot_bounce_a_spirit(set_pool):
    pool = set_pool("M21")
    spirit = Permanent(card=pool["Roaming Ghostlight"])   # a Spirit itself
    pegasus = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Roaming Ghostlight"]])
    p2 = PlayerState(name="P2", battlefield=[spirit, pegasus])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Roaming Ghostlight", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    # The chosen Spirit is not a legal object for the trigger, and "up to one"
    # may legally affect nothing — so nothing was bounced.
    assert game.is_on_battlefield(spirit)
    assert game.is_on_battlefield(pegasus)
    assert len(p2.hand) == 0


def test_roaming_ghostlight_bounces_a_non_spirit(set_pool):
    pool = set_pool("M21")
    pegasus = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Roaming Ghostlight"]])
    p2 = PlayerState(name="P2", battlefield=[pegasus])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Roaming Ghostlight", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(pegasus)
    assert [c.name for c in p2.hand] == ["Concordia Pegasus"]


def test_barrin_bounces_a_planeswalker_to_its_owners_hand(set_pool):
    """The union half: "up to one other target creature **or planeswalker**".
    And the CR 400.3 nuance the end-step test below leans on: the walker goes
    to its *owner's* hand, so bouncing the opponent's does not feed Barrin's
    own put-into-your-hand history."""
    pool = set_pool("M21")
    walker = Permanent(
        card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4},
    )
    p1 = PlayerState(name="P1", hand=[pool["Barrin, Tolarian Archmage"]])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(walker)
    assert any(c.name == "Garruk, Unleashed" for c in p2.hand)
    assert game.permanents_to_hand_this_turn.get(0, 0) == 0
    assert game.permanents_to_hand_this_turn.get(1, 0) == 1


def test_barrin_draws_at_end_step_after_bouncing_his_controllers_own(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(
        name="P1", hand=[pool["Barrin, Tolarian Archmage"]],
        battlefield=[mine], library=[pool["Island"]] * 3,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Concordia Pegasus" for c in p1.hand)
    # The bounce landed in *your* hand, which is what the end-step
    # intervening-if reads (CR 603.4). The trigger goes on the stack and
    # resolves through the ordinary settle.
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert len(p1.hand) == hand_before + 1


def test_barrin_end_step_trigger_stays_quiet_without_a_bounce(set_pool):
    pool = set_pool("M21")
    barrin = Permanent(card=pool["Barrin, Tolarian Archmage"])
    p1 = PlayerState(name="P1", battlefield=[barrin], library=[pool["Island"]] * 3)
    game = Game(players=[p1, PlayerState(name="P2")])
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert not game.stack
    assert len(p1.hand) == hand_before, (
        "nothing was put into Barrin's controller's hand from the battlefield "
        "this turn, so CR 603.4 keeps the trigger off the stack"
    )


def test_shipwreck_dowser_returns_an_instant_but_not_a_creature(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Shipwreck Dowser"]],
        graveyard=[pool["Concordia Pegasus"], pool["Shock"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Shipwreck Dowser", target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert any(c.name == "Shock" for c in p1.hand)
    assert any(c.name == "Concordia Pegasus" for c in p1.graveyard)


def test_life_goes_on_gains_eight_only_over_a_body(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Life Goes On"], pool["Life Goes On"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    assert game.cast_from_hand(0, "Life Goes On").supported
    assert p1.life == 24
    game.creatures_died_this_turn = 1
    assert game.cast_from_hand(0, "Life Goes On").supported
    assert p1.life == 32, "a creature died this turn, so the 8-life arm applies"


# --- Round 22: the controller discard, and tokens for the other side --------


@pytest.mark.parametrize(
    "name", ["Jeskai Elder", "Secure the Scene", "Angelic Ascension"],
)
def test_round_22_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_secure_the_scene_exiles_and_compensates_the_owner(set_pool):
    pool = set_pool("M21")
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Secure the Scene"]])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Secure the Scene", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Concordia Pegasus" for c in p2.exile)
    # The Soldier goes to the exiled permanent's controller — the opponent,
    # not the caster.
    assert [p.card.name for p in p2.battlefield] == ["Soldier Token"]
    assert p1.battlefield == []


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


def test_jeskai_elder_draws_then_asks_for_the_discard(set_pool):
    pool = set_pool("M21")
    elder = Permanent(card=pool["Jeskai Elder"])
    p1 = PlayerState(
        name="P1", battlefield=[elder],
        hand=[pool["Island"]], library=[pool["Shock"]] * 2,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    program = compile_card_oracle(elder.card)
    trig = next(t for t in program.triggered_abilities if t.supported and t.instruction is not None)
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=elder, instruction=trig.instruction,
        effect_kind=trig.effect_kind,
    )
    game._settle()
    # The optional draw is a pending "may"; accept it.
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the 'you may draw' offer should be queued"
    assert game.confirm_optional_pay(0, accept=True)
    assert len(p1.hand) == 2, "drew the card"
    discard = game.pending_choices_of("discard", 0)
    assert discard and discard[0].data["count"] == 1
    assert game.confirm_discard(0, [0])
    assert len(p1.hand) == 1, "and discarded one of their choice"


# --- Round 23: the may-with-action-cost, and a counted gain ------------------


@pytest.mark.parametrize("name", ["Aven Gagglemaster", "Dire Fleet Warmonger"])
def test_round_23_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_aven_gagglemaster_counts_its_own_wings(set_pool):
    pool = set_pool("M21")
    flyers = [Permanent(card=pool["Concordia Pegasus"]) for _ in range(2)]
    grounded = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(
        name="P1", hand=[pool["Aven Gagglemaster"]],
        battlefield=[*flyers, grounded],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "Aven Gagglemaster")
    assert result.supported, result.details
    # Two Pegasi plus the Gagglemaster itself fly; the cat does not.
    assert p1.life == 26


def test_dire_fleet_warmonger_eats_a_creature_for_the_turn(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    snack = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", battlefield=[warmonger, snack])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat fires the trigger
    game._settle()
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the 'you may sacrifice' offer should be queued"
    assert game.confirm_optional_pay(0, accept=True)
    # Accepting arms the sacrifice prompt; Warmonger itself is excluded
    # ("another"), so only the cat is a legal pick.
    sac = game.pending_sacrifice_state()
    assert sac is not None and sac["valid_indices"] == [1]
    assert game.confirm_sacrifice(0, [1])
    assert not game.is_on_battlefield(snack)
    assert warmonger.effective_power == 5  # 3/3 printed, +2/+2
    assert game._has_keyword(warmonger, "trample")
    # CR 514.2: the meal wears off.
    game.resolve_cleanup_step(0)
    assert warmonger.effective_power == 3
    assert not game._has_keyword(warmonger, "trample")


def test_dire_fleet_warmonger_with_nothing_to_eat_is_never_asked(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    p1 = PlayerState(name="P1", battlefield=[warmonger])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game._settle()
    assert not game.pending_choices_of("optional_pay", 0), (
        "with no other creature the cost is unpayable, so the offer is never "
        "made and the pump cannot be taken for free"
    )
    assert warmonger.effective_power == 3


# --- Round 24: two spellings and two destinations ----------------------------


@pytest.mark.parametrize(
    "name", ["Falconer Adept", "Epitaph Golem", "Unsubstantiate"],
)
def test_round_24_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_falconer_adept_token_arrives_tapped_and_attacking(set_pool):
    pool = set_pool("M21")
    adept = Permanent(card=pool["Falconer Adept"])
    p1 = PlayerState(name="P1", battlefield=[adept])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    birds = [p for p in p1.battlefield if p.card.name == "Bird Token"]
    assert len(birds) == 1
    assert birds[0].tapped
    bird_index = p1.battlefield.index(birds[0])
    assert bird_index in game.combat_attackers, "the Bird joined the attack"


def test_epitaph_golem_bottoms_a_chosen_graveyard_card(set_pool):
    pool = set_pool("M21")
    golem = Permanent(card=pool["Epitaph Golem"])
    p1 = PlayerState(
        name="P1", battlefield=[golem],
        graveyard=[pool["Shock"], pool["Concordia Pegasus"]],
        library=[pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.activate_permanent_ability(
        0, "Epitaph Golem", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert [c.name for c in p1.library] == ["Island", "Concordia Pegasus"]


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


# --- Round 25: protection grows past colour ----------------------------------


def test_baneslayer_angel_compiles_and_shields_against_its_named_tribes(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Baneslayer Angel"])
    assert program.supported, program.reason
    angel = Permanent(card=pool["Baneslayer Angel"])
    dragon = Permanent(card=pool["Gadrak, the Crown-Scourge"])  # a Dragon
    game = Game(players=[
        PlayerState(name="P1", battlefield=[angel]),
        PlayerState(name="P2", battlefield=[dragon]),
    ])
    assert game._is_protected_from(angel, dragon)
    assert not game._can_block_attacker(dragon, angel)
    # And the colour half of her line still reads: nothing here is a Demon or
    # Dragon spell, so an ordinary removal spell may still target her.
    assert game._can_be_targeted(angel, pool["Shock"])


# --- Round 27: modal triggered abilities --------------------------------------


@pytest.mark.parametrize("name", ["Trufflesnout", "Elder Gargaroth"])
def test_round_27_modal_trigger_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason
    trig = next(t for t in program.triggered_abilities if t.supported)
    assert trig.instruction is not None and trig.instruction.kind == "choose_one"
    assert program.modes == (), "a trigger's modes are not cast-time modes"


def test_trufflesnout_default_takes_the_first_printed_mode(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 1, "mode 0: the counter"
    assert (snout.effective_power, snout.effective_toughness) == (3, 3)
    assert p1.life == 20, "the life mode was not also taken"


def test_trufflesnout_interactive_controller_may_take_the_life_instead(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    pending = game.pending_choices_of("mode_choice", 0)
    assert pending and pending[0].data["labels"] == [
        "Put a +1/+1 counter on this creature", "You gain 4 life",
    ]
    assert not game.resolve_pending_choice("mode_choice", 0, mode_index=5), (
        "an index outside the printed list is refused and the prompt stays owed"
    )
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    assert p1.life == 24
    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 0, "the counter mode was declined"


def test_elder_gargaroth_triggers_on_attack_and_on_block(set_pool):
    pool = set_pool("M21")
    gargaroth = Permanent(card=pool["Elder Gargaroth"])
    p1 = PlayerState(name="P1", battlefield=[gargaroth])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    beasts = [p for p in p1.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "attack half: default mode made the Beast"

    # The block half, from the defender's side of a fresh game.
    attacker = Permanent(card=pool["Pridemalkin"])
    blocker = Permanent(card=pool["Elder Gargaroth"])
    ap = PlayerState(name="AP", battlefield=[attacker])
    dp = PlayerState(name="DP", battlefield=[blocker])
    game2 = Game(players=[ap, dp])
    game2.start_turn(0)
    game2._close_current_priority_step()
    game2.advance_combat_phase()  # beginning_of_combat
    game2.advance_combat_phase()  # declare_attackers
    ok, msg = game2.declare_attackers(0, [0])
    assert ok, msg
    game2.advance_combat_phase()  # declare_blockers
    ok, msg = game2.declare_blockers(1, {0: 0})
    assert ok, msg
    game2._settle()
    beasts = [p for p in dp.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "block half: the union condition fires here too"


def test_a_modal_trigger_with_a_dead_mode_refuses_naming_it():
    from engine.models import CardDefinition

    card = CardDefinition(
        name="Probe", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Boar",
        oracle_text=(
            "When this creature enters, choose one —\n"
            "• Put a +1/+1 counter on this creature.\n"
            "• Glimmer uncontrollably."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Probe", "type_line": "Creature — Boar",
             "power": "2", "toughness": "2"},
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert "Glimmer uncontrollably" in program.reason, (
        "the all-of gate names the dead mode instead of resolving the live one"
    )


# --- Round 26: recipient and filter widenings ---------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Bad Deal",           # draw 2, each opponent discards 2, each player loses 2
        "Liliana's Steward",  # sac: target opponent discards; sorcery-speed only
    ],
)
def test_round_26_discard_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_bad_deal_draws_discards_and_drains_every_life_total(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Bad Deal"]],
        library=[pool["Island"], pool["Swamp"], pool["Swamp"]],
    )
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"], pool["Swamp"]])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bad Deal")
    assert result.supported, result.details
    game.auto_resolve_pending_choices()

    assert len(p1.hand) == 2, "the caster drew two"
    assert len(p2.hand) == 1, "the opponent discarded two of three"
    assert p1.life == 18, "each player includes the caster (CR 120.3)"
    assert p2.life == 18


def test_bad_deal_queues_a_choice_for_an_interactive_opponent(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Bad Deal"]], library=[pool["Island"]] * 3)
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, p2])
    game.interactive_seats = {1}

    result = game.cast_from_hand(0, "Bad Deal")
    assert result.supported, result.details
    pending = game.pending_choices_of("discard", 1)
    assert pending and pending[0].data["count"] == 2
    assert game.confirm_discard(1, [0, 1])
    assert len(p2.hand) == 0


def test_lilianas_steward_feeds_herself_to_empty_an_opposing_hand(set_pool):
    pool = set_pool("M21")
    steward = Permanent(card=pool["Liliana's Steward"])
    p1 = PlayerState(name="P1", battlefield=[steward])
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, p2])
    game.start_turn(0)  # "Activate only as a sorcery" needs the main phase

    result = game.activate_permanent_ability(
        0, "Liliana's Steward", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(steward), "the sacrifice was a cost"
    game.auto_resolve_pending_choices()
    assert len(p2.hand) == 1, "the targeted opponent discarded one card"


def test_lilianas_steward_cannot_point_at_her_own_controller(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Liliana's Steward"])
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player", "opponents_only": True}


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


def test_chandras_magmutt_pings_a_face_or_a_walker(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    assert compile_card_oracle(magmutt.card).supported
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    p1 = PlayerState(name="P1", battlefield=[magmutt])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert p2.life == 19, "the player face is a legal target"

    magmutt.tapped = False
    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert walker.metadata["loyalty_counters"] == 2, "damage strips loyalty (CR 306.8)"
    assert p2.life == 19, "the walker soaked it, not the player"


def test_chandras_magmutt_never_offers_a_creature(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    bear = Permanent(card=pool["Pridemalkin"])
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    game = Game(players=[
        PlayerState(name="P1", battlefield=[magmutt]),
        PlayerState(name="P2", battlefield=[bear, walker]),
    ])
    program = compile_card_oracle(magmutt.card)
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player_or_planeswalker"}
    offered = game._enumerate_targets(
        0, magmutt.card, spec, for_cast=False,
        ability_instruction=ability.instruction, source_permanent=magmutt,
    )
    names = {t.get("name") for t in offered if t["kind"] == "permanent"}
    assert names == {"Basri Ket"}, "planeswalkers yes, creatures no"
    assert {t["seat"] for t in offered if t["kind"] == "player"} == {0, 1}


def test_tempered_veteran_tends_only_an_already_counted_creature(set_pool):
    pool = set_pool("M21")
    veteran = Permanent(card=pool["Tempered Veteran"])
    cat = Permanent(card=pool["Pridemalkin"])  # 2/1, no counter yet
    p1 = PlayerState(name="P1", battlefield=[veteran, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    program = compile_card_oracle(veteran.card)
    assert program.supported, program.reason

    from engine.targeting import derive_activation_spec

    cheap = program.activated_abilities[0]  # {W}, {T}: counter on a counted creature
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert offered == [], "with no counter anywhere, the cheap ability has no target"

    # The expensive ability seeds the counter; the cheap one can then grow it.
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 1, "the counter is recorded, not just P/T"
    assert (cat.effective_power, cat.effective_toughness) == (3, 2)

    veteran.tapped = False
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert [t.get("name") for t in offered] == ["Pridemalkin"]
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 2
    assert (cat.effective_power, cat.effective_toughness) == (4, 3)


def test_azusa_grants_two_additional_land_plays(set_pool):
    pool = set_pool("M21")
    azusa = Permanent(card=pool["Azusa, Lost but Seeking"])
    assert compile_card_oracle(azusa.card).supported
    p1 = PlayerState(name="P1", battlefield=[azusa], hand=[pool["Forest"]] * 4)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True  # CR 305.2's count is enforced in this mode

    plays = [game.cast_from_hand(0, "Forest").supported for _ in range(4)]
    assert plays == [True, True, True, False], "one land plus Azusa's two"


def test_kaervek_shrinks_every_other_creature_and_not_himself(set_pool):
    pool = set_pool("M21")
    kaervek = Permanent(card=pool["Kaervek, the Spiteful"])
    own_bird = Permanent(card=pool["Concordia Pegasus"])    # 1/3, his own side
    frail = Permanent(card=pool["Speaker of the Heavens"])  # 1/1, opposing
    p1 = PlayerState(name="P1", battlefield=[kaervek, own_bird])
    p2 = PlayerState(name="P2", battlefield=[frail])
    game = Game(players=[p1, p2])

    program = compile_card_oracle(kaervek.card)
    assert program.supported, program.reason
    game._recalculate_lord_buffs()

    assert kaervek.effective_power == 3, "'Other creatures' excludes the source"
    assert own_bird.effective_power == 0, "his own side shrinks too"
    assert frail.effective_toughness == 0
    game.check_state_based_actions()
    assert not game.is_on_battlefield(frail), "a 1/1 dies under him (CR 704.5f)"
    assert game.is_on_battlefield(own_bird)
