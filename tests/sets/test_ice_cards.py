"""Per-card tests for Ice Age (ICE).

Conventions: `tests/sets/README.md`. The set starts as one file and splits by
the printed type of the card each test names when it outgrows one.

CR-level tests for the mechanics this set introduced live in `tests/rules/` —
cumulative upkeep is `tests/rules/test_cumulative_upkeep.py`. What belongs here
is the *card*: that this printing compiles, and that its own numbers and text
do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _cu_trigger(card):
    """The cumulative upkeep ability *card* compiles to, or None."""
    return next(
        (
            trig
            for trig in compile_card_oracle(card).triggered_abilities
            if trig.instruction is not None
            and trig.instruction.kind == "cumulative_upkeep"
        ),
        None,
    )


# --- Round 1: cumulative upkeep (CR 702.24) ---


def test_illusionary_wall_carries_its_cumulative_upkeep(set_pool):
    """A creature printing "Cumulative upkeep {U}" alongside defender: the
    keyword line is one line and both halves survive it."""
    wall = set_pool("ICE")["Illusionary Wall"]
    program = compile_card_oracle(wall)

    assert program.supported
    trigger = _cu_trigger(wall)
    assert trigger is not None
    assert trigger.instruction.payload["mana"] == {"U": 1}
    assert Permanent(card=wall).has_keyword("defender")


def test_illusionary_wall_ages_and_is_sacrificed_when_unpaid(set_pool):
    wall = Permanent(card=set_pool("ICE")["Illusionary Wall"])
    p1 = PlayerState(name="P1", battlefield=[wall], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)

    assert counters_on(wall, "age") == 1
    assert wall not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Illusionary Wall"]


def test_mystic_remora_cumulative_upkeep_reaches_an_enchantment(set_pool):
    """The rewrite has to run on the **non-creature** front end too.

    Mystic Remora prints cumulative upkeep beside a trigger the engine cannot
    yet read. The creature loop and the permanent loop are different code, and
    with the rewrite in only the first one this card compiled *supported* with
    its upkeep silently dropped — a strictly better card than the one printed.
    """
    remora = set_pool("ICE")["Mystic Remora"]
    trigger = _cu_trigger(remora)

    assert trigger is not None
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.payload["mana"] == {"generic": 1}


def test_soldevi_simulacrum_escalates_across_two_upkeeps(set_pool):
    """"Cumulative upkeep {1}" on the board: {1} the first upkeep, {2} the
    second, paid by tapping lands during the step."""
    sim = Permanent(card=set_pool("ICE")["Soldevi Simulacrum"])
    forests = [Permanent(card=set_pool("ICE")["Forest"]) for _ in range(4)]
    p1 = PlayerState(name="P1", battlefield=[sim, *forests], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    assert sum(1 for f in forests if f.tapped) == 1
    for forest in forests:
        forest.tapped = False

    game.resolve_upkeep(0)
    assert counters_on(sim, "age") == 2
    assert sum(1 for f in forests if f.tapped) == 2
    assert sim in p1.battlefield


def test_polar_kraken_refuses_a_cost_the_engine_cannot_charge(set_pool):
    """"Cumulative upkeep—Sacrifice a land." CR 702.24a admits any cost and
    this engine charges mana, so the card stays unsupported **naming the
    clause** rather than shipping with a free upkeep."""
    kraken = set_pool("ICE")["Polar Kraken"]
    program = compile_card_oracle(kraken)

    assert not program.supported
    assert "cumulative upkeep" in (program.reason or "").lower()
    assert _cu_trigger(kraken) is None


def test_halls_of_mist_still_reports_its_unread_static_line(set_pool):
    """A land whose cumulative upkeep now compiles, and whose *other* line the
    engine does not implement.

    The land support gate used to skip the static check for any land carrying
    an ability, so implementing the keyword would have turned this card
    supported with "Creatures that attacked … can't attack" doing nothing. The
    gate reads every land now and names the line it cannot claim.
    """
    program = compile_card_oracle(set_pool("ICE")["Halls of Mist"])

    assert not program.supported
    assert "can't attack" in (program.reason or "")


# --- Round 2: the Scarab cycle — a conditional static on an Aura's host ---


def _scarab_board(set_pool, scarab_name: str, opponent_permanent: str | None):
    """A 2/2 bear wearing *scarab_name*, with the opponent's board as named.

    The Aura is attached with ``attach_aura`` rather than cast, because what is
    under test is the continuous effect while attached (CR 611.3a) — recomputed
    on every read, never applied once at attachment.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])  # a vanilla 2/2, no text at all
    scarab = Permanent(card=pool[scarab_name])
    p1 = PlayerState(name="P1", battlefield=[bear, scarab], life=20)
    theirs = [Permanent(card=pool[opponent_permanent])] if opponent_permanent else []
    p2 = PlayerState(name="P2", battlefield=theirs, life=20)
    game = Game(players=[p1, p2])
    attach_aura(scarab, bear)
    game._settle()
    return game, bear, scarab


def test_black_scarab_grants_nothing_while_no_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", None)

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_black_scarab_grants_plus_two_while_an_opponent_has_a_black_permanent(set_pool):
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")  # a black creature

    assert (bear.effective_power, bear.effective_toughness) == (4, 4)


def test_black_scarab_reads_the_condition_on_every_recompute(set_pool):
    """CR 611.3a — the condition is asked continuously, not locked in when the
    Aura attached. Removing the opponent's black permanent removes the bonus
    with nothing to undo."""
    game, bear, _ = _scarab_board(set_pool, "Black Scarab", "Moor Fiend")
    assert bear.effective_power == 4

    game.remove_from_battlefield(game.players[1].battlefield[0])
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_scarab_condition_is_measured_from_the_auras_controller(set_pool):
    """CR 109.5: the ability is the Aura's, so "an opponent" is an opponent of
    whoever controls the Aura — not of whoever controls the creature.

    The cycle exists to be put on an opponent's creature, so this is the case
    the card is printed for rather than a corner: P1's Scarab on P1's own black
    creature must see P1's board as "you", find no *opponent* with a black
    permanent, and grant nothing.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    black_bear = Permanent(card=pool["Moor Fiend"])
    scarab = Permanent(card=pool["Black Scarab"])
    p1 = PlayerState(name="P1", battlefield=[black_bear, scarab], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(scarab, black_bear)
    game._settle()

    assert (black_bear.effective_power, black_bear.effective_toughness) == (3, 3)


def test_every_scarab_in_the_cycle_compiles_to_the_same_shape(set_pool):
    """Five cards, one sentence with the colour word changed — the reason this
    is a production rather than five entries."""
    pool = set_pool("ICE")
    colors = {
        "Black Scarab": "B", "Blue Scarab": "U", "Green Scarab": "G",
        "Red Scarab": "R", "White Scarab": "W",
    }
    for name, symbol in colors.items():
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        static = next(
            i for i in program.instructions if i.kind == "conditional_static"
        )
        assert static.payload["subject"] == "attached", name
        assert static.payload["power"] == 2 and static.payload["toughness"] == 2
        assert static.payload["condition"]["who"] == "opponent", name
        assert static.payload["condition"]["filter"]["color_filter"] == symbol, name


# --- Round 3: the cantrip cycle — "at the beginning of the next turn's upkeep" ---


def test_pyknite_draws_at_the_next_turns_upkeep(set_pool):
    """The cantrip run end to end: the creature enters, arms the delayed
    ability, and the card arrives at the *next* upkeep — not this one, and not
    at resolution."""
    pool = set_pool("ICE")
    pyknite = Permanent(card=pool["Pyknite"])
    p1 = PlayerState(
        name="P1",
        battlefield=[pyknite],
        library=[pool["Balduvian Bears"], pool["Balduvian Bears"]],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game._apply_self_enters_battlefield_triggers(0, pyknite, None, None)
    game._settle()
    assert p1.hand == [], "the draw is delayed, not part of the enters trigger"

    game.resolve_upkeep(0)
    game._settle()
    assert len(p1.hand) == 1


def test_the_cantrip_cycle_arms_the_unseated_upkeep_event(set_pool):
    """Seven cards, one sentence. What makes it one round rather than seven is
    that they all compile to the same delayed event — and it is the *unseated*
    one, because "the next turn's upkeep" is whichever comes next."""
    pool = set_pool("ICE")
    for name in (
        "Portent", "Krovikan Fetish", "Panic", "Pyknite",
        "Touch of Vitae", "Barbed Sextant",
    ):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        events = {
            instruction.payload.get("event")
            for instruction in _all_instructions(program)
            if instruction.kind == "create_delayed_trigger"
        }
        assert events == {"next_turns_upkeep"}, (name, events)


def _all_instructions(program):
    """Every instruction the program carries, card-level and per-ability.

    The cycle prints its cantrip in three places — a spell's second sentence, an
    Aura's enters trigger, an artifact's activated ability — so a reader that
    looked only at ``program.instructions`` would find the clause on some of
    them and quietly miss it on the rest.
    """
    def walk(instruction):
        yield instruction
        # A `sequence` is how two sentences on one line compose (Barbed
        # Sextant's "Add one mana of any color. Draw a card at …"), so a reader
        # that stopped at the top level would find the clause on five of the
        # seven and report the other two clean.
        for step in instruction.payload.get("steps", ()):
            yield from walk(step)

    for instruction in program.instructions:
        yield from walk(instruction)
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        if ability.instruction is not None:
            yield from walk(ability.instruction)


# --- Round 4: combat-relation target descriptions ---


def _combat(game: Game, attacker_indices: list[int]) -> None:
    """Advance seat 0's turn to the declare-blockers step with those attackers."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"


def test_goblin_snowman_can_only_ping_the_creature_it_blocks(set_pool):
    """"{T}: This creature deals 1 damage to target creature it's blocking."

    The picker is what is under test, not the handler: an ability that offered
    every creature on the board would let a player point this at a creature the
    card cannot hit.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])
    bystander = Permanent(card=pool["Balduvian Barbarians"])
    snowman = Permanent(card=pool["Goblin Snowman"])
    p1 = PlayerState(name="P1", battlefield=[attacker, bystander], life=20)
    p2 = PlayerState(name="P2", battlefield=[snowman], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    program = compile_card_oracle(snowman.card)
    ability = program.activated_abilities[0]
    from engine.targeting import derive_activation_spec

    spec = derive_activation_spec(ability)
    offered = game._enumerate_targets(
        1, snowman.card, spec, for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=snowman, ability_source=snowman,
    )
    named = {
        game.players[t["seat"]].battlefield[t["index"]].card.name
        for t in offered if t["kind"] == "permanent"
    }
    assert named == {"Balduvian Bears"}, named


def test_goblin_snowman_offers_nothing_while_it_blocks_nothing(set_pool):
    """Out of combat the relation names no creature, so the ability has no legal
    target — refused, rather than offered the board."""
    pool = set_pool("ICE")
    snowman = Permanent(card=pool["Goblin Snowman"])
    other = Permanent(card=pool["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[snowman, other], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    from engine.targeting import derive_activation_spec

    ability = compile_card_oracle(snowman.card).activated_abilities[0]
    offered = game._enumerate_targets(
        0, snowman.card, derive_activation_spec(ability), for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=snowman, ability_source=snowman,
    )
    assert offered == []


def test_snow_fortress_only_reaches_creatures_attacking_its_controller(set_pool):
    """"…target creature without flying that's attacking you."

    Two narrowings at once, and the second is a *seat* question: a creature
    attacking somebody else is attacking, and is not a legal target.
    """
    pool = set_pool("ICE")
    ground = Permanent(card=pool["Balduvian Bears"])       # 2/2, no flying
    flier = Permanent(card=pool["Silver Erne"])          # flying
    fortress = Permanent(card=pool["Snow Fortress"])
    p1 = PlayerState(name="P1", battlefield=[ground, flier], life=20)
    p2 = PlayerState(name="P2", battlefield=[fortress], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0, 1])

    from engine.targeting import derive_activation_spec

    ability = next(
        a for a in compile_card_oracle(fortress.card).activated_abilities
        if a.instruction is not None and "damage" in a.instruction.kind
    )
    offered = game._enumerate_targets(
        1, fortress.card, derive_activation_spec(ability), for_cast=False,
        ability_instruction=ability.instruction,
        source_permanent=fortress, ability_source=fortress,
    )
    named = {
        game.players[t["seat"]].battlefield[t["index"]].card.name
        for t in offered if t["kind"] == "permanent"
    }
    assert named == {"Balduvian Bears"}, named


# --- Round 5: Aura keyword grants, from the engine's one keyword registry ---


def test_wings_of_aesthir_grants_both_keywords_and_the_bonus(set_pool):
    """"Enchanted creature gets +1/+0 and has flying **and first strike**."

    Two keywords on one line. The grant used to read one, so a card printing
    two would have shipped giving half of what it prints — and matched, so
    nothing would have said so.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    wings = Permanent(card=pool["Wings of Aesthir"])
    p1 = PlayerState(name="P1", battlefield=[bear, wings], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(wings, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (3, 2)
    assert bear.has_keyword("flying")
    assert bear.has_keyword("first strike")


def test_imposing_visage_grants_menace(set_pool):
    """A keyword the engine has implemented all along and the Aura reader did
    not list. `auras` kept a hand-written copy of the keyword registry; it is
    derived now, so what an Aura may grant and what the engine implements are
    one fact."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    visage = Permanent(card=pool["Imposing Visage"])
    p1 = PlayerState(name="P1", battlefield=[bear, visage], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(visage, bear)
    game._settle()

    assert compile_card_oracle(visage.card).supported
    assert bear.has_keyword("menace")


# --- Round 6: snow as a supertype the rules already knew how to read ---


def test_rime_dryad_is_blockable_without_a_snow_forest(set_pool):
    """Snow forestwalk, run in real combat rather than asserted off the
    compiled program: CR 702.14c asks the *defending player's* board."""
    pool = set_pool("ICE")
    dryad = Permanent(card=pool["Rime Dryad"])
    blocker = Permanent(card=pool["Balduvian Bears"])
    forest = Permanent(card=pool["Forest"])
    p1 = PlayerState(name="P1", battlefield=[dryad], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker, forest], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    assert game.declare_blockers(1, {0: 0})[0]


def test_rime_dryad_is_unblockable_against_a_snow_covered_forest(set_pool):
    pool = set_pool("ICE")
    dryad = Permanent(card=pool["Rime Dryad"])
    blocker = Permanent(card=pool["Balduvian Bears"])
    snow = Permanent(card=pool["Snow-Covered Forest"])
    p1 = PlayerState(name="P1", battlefield=[dryad], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker, snow], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


def test_woolly_mammoths_tramples_only_while_you_control_a_snow_land(set_pool):
    """"…has trample as long as you control a snow land" — the general
    "you control <noun phrase>" condition, asked on every recompute."""
    pool = set_pool("ICE")
    mammoths = Permanent(card=pool["Woolly Mammoths"])
    p1 = PlayerState(name="P1", battlefield=[mammoths], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game._settle()
    assert not mammoths.has_keyword("trample")

    snow = Permanent(card=pool["Snow-Covered Plains"])
    p1.battlefield.append(snow)
    game._settle()
    assert mammoths.has_keyword("trample")

    game.remove_from_battlefield(snow)
    game._settle()
    assert not mammoths.has_keyword("trample")


# --- Round 7: "can't be blocked by <noun phrase>", one vocabulary ---


def test_stone_spirit_cannot_be_blocked_by_a_flier(set_pool):
    """"This creature can't be blocked by creatures with flying."

    A keyword in the blocker noun, which the restriction table had no capture
    for — the four it had (subtype, card type, colour, power) were each
    translated back into a subject filter by a matching branch at the
    enforcement site, so a fifth noun needed both halves and was unenforced
    without the second. One filter vocabulary now, read by `_blocker_union`.
    """
    pool = set_pool("ICE")
    spirit = Permanent(card=pool["Stone Spirit"])
    flier = Permanent(card=pool["Silver Erne"])
    ground = Permanent(card=pool["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[spirit], life=20)
    p2 = PlayerState(name="P2", battlefield=[flier, ground], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    assert not game.declare_blockers(1, {0: 0})[0], "the flier may not block"
    assert game.declare_blockers(1, {1: 0})[0], "the ground creature may"


def test_flow_of_maggots_can_only_be_blocked_by_walls(set_pool):
    """"…can't be blocked by **non-Wall** creatures" — the negation of a
    subtype, which is a different set from any of the positive forms."""
    pool = set_pool("ICE")
    maggots = Permanent(card=pool["Flow of Maggots"])
    wall = Permanent(card=pool["Glacial Wall"])
    bear = Permanent(card=pool["Balduvian Bears"])
    # A land to pay the cumulative upkeep with: `start_turn` runs the upkeep,
    # and an unpaid Flow of Maggots is sacrificed before it can attack.
    p1 = PlayerState(
        name="P1", battlefield=[maggots, Permanent(card=pool["Swamp"])], life=20
    )
    p2 = PlayerState(name="P2", battlefield=[wall, bear], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    assert not game.declare_blockers(1, {1: 0})[0], "a non-Wall may not block"
    assert game.declare_blockers(1, {0: 0})[0], "a Wall may"


# --- Round 8: a self-reference's noun is not a filter ---


def test_the_self_bouncers_return_their_own_source(set_pool):
    """"{cost}: Return this <noun> to its owner's hand" on four cards and three
    different nouns.

    The lowering refused the printed noun as an unhonoured restriction. On a
    self-reference there is nothing to restrict: "this creature", "this
    enchantment" and "this permanent" all name the object the ability is
    printed on (CR 109.5), which is why the engine's own collapser reads the
    three as one phrase.
    """
    pool = set_pool("ICE")
    for name in ("Blinking Spirit", "Foul Familiar", "Leshrac's Sigil",
                 "Freyalise's Charm"):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        kinds = {
            ability.instruction.kind
            for ability in program.activated_abilities
            if ability.instruction is not None
        }
        assert "return_source_card_to_owners_hand" in kinds, name


def test_blinking_spirit_bounces_itself(set_pool):
    """Run rather than asserted off the program: the ability is free, so what
    it does is the whole card."""
    pool = set_pool("ICE")
    spirit = Permanent(card=pool["Blinking Spirit"])
    p1 = PlayerState(name="P1", battlefield=[spirit], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    result = game.activate_permanent_ability(0, "Blinking Spirit", permanent_index=0)
    assert result.supported, result.details
    game._settle()

    assert spirit not in p1.battlefield
    assert [c.name for c in p1.hand] == ["Blinking Spirit"]


# --- Round 9: characteristic-defining P/T (CR 604.3) ---


def test_drift_of_the_dead_counts_snow_lands_only(set_pool):
    """"…power and toughness are each equal to the number of **snow** lands you
    control." A supertype narrowing the land count (CR 205.4), which no layer
    computes — the effective type line is the whole answer."""
    pool = set_pool("ICE")

    def _drift_on(*land_names: str) -> Permanent:
        drift = Permanent(card=pool["Drift of the Dead"])
        lands = [Permanent(card=pool[name]) for name in land_names]
        p1 = PlayerState(name="P1", battlefield=[drift, *lands], life=20)
        Game(players=[p1, PlayerState(name="P2", life=20)])._refresh_dynamic_creatures()
        return drift

    bare = _drift_on()
    assert (bare.effective_power, bare.effective_toughness) == (0, 0)

    # The plain Forest must not count, which is the whole of the supertype.
    snowy = _drift_on("Snow-Covered Swamp", "Snow-Covered Forest", "Forest")
    assert (snowy.effective_power, snowy.effective_toughness) == (2, 2)


def test_lhurgoyf_counts_every_graveyard_and_its_toughness_is_that_plus_one(set_pool):
    """Lhurgoyf is printed */1+*, so the toughness clause is half the card — and
    "in **all** graveyards" is every player's, not the controller's."""
    pool = set_pool("ICE")
    lhurgoyf = Permanent(card=pool["Lhurgoyf"])
    p1 = PlayerState(
        name="P1", battlefield=[lhurgoyf],
        graveyard=[pool["Balduvian Bears"], pool["Moor Fiend"]], life=20,
    )
    p2 = PlayerState(
        name="P2", graveyard=[pool["Balduvian Bears"], pool["Icequake"]], life=20,
    )
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()

    # Three creature cards across both graveyards; Icequake is a sorcery.
    assert (lhurgoyf.effective_power, lhurgoyf.effective_toughness) == (3, 4)


def test_pestilence_rats_counts_the_other_rats(set_pool):
    """"…the number of **other** Rats on the battlefield" — the source excluded
    by identity (CR 109.5), and the printed toughness (3) left standing."""
    pool = set_pool("ICE")
    first = Permanent(card=pool["Pestilence Rats"])
    second = Permanent(card=pool["Pestilence Rats"])
    p1 = PlayerState(name="P1", battlefield=[first], life=20)
    p2 = PlayerState(name="P2", battlefield=[second], life=20)
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()

    assert (first.effective_power, first.effective_toughness) == (1, 3)
    assert (second.effective_power, second.effective_toughness) == (1, 3)


# --- Round 10: sweeps and grants over a set the sentence names ---


def test_jokulhaups_destroys_three_types_and_beats_regeneration(set_pool):
    """"Destroy all artifacts, creatures, and lands. They can't be regenerated."

    A type union no per-scope sweep kind names. The filtered sweep already
    answers it — `type_filter` takes a list and the matcher reads one as a
    union — so this routes rather than needing a fourth hand-written scope.
    """
    pool = set_pool("ICE")
    creature = Permanent(card=pool["Balduvian Bears"])
    land = Permanent(card=pool["Forest"])
    enchantment = Permanent(card=pool["Snowfall"])
    p1 = PlayerState(name="P1", battlefield=[creature, land, enchantment], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    program = compile_card_oracle(pool["Jokulhaups"])
    assert program.supported
    instruction = program.instructions[0]
    assert instruction.kind == "destroy_all_matching"
    assert set(instruction.payload["type_filter"]) == {"artifact", "creature", "land"}
    assert instruction.payload["bypass_regeneration"] is True


def test_stampede_reaches_attacking_creatures_the_caster_does_not_control(set_pool):
    """"Attacking creatures get +1/+0 and gain trample until end of turn."

    Both halves of the sentence name the same set, and only the P/T half read
    it: the keyword half refused the narrowing, so supporting the card without
    this would have pumped every attacker and given trample to none of them.
    The set is also not the caster's board — Stampede is castable by the
    defending player, which is what `every_seat` carries.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])
    home = Permanent(card=pool["Balduvian Barbarians"])
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[home], hand=[pool["Stampede"]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    _combat(game, [0])
    game.cast_from_hand(1, "Stampede")
    game._settle()

    assert attacker.has_keyword("trample"), "the opponent's attacker is in the set"
    assert not home.has_keyword("trample"), "a creature that is not attacking is not"


# --- Round 11: "If that land was a snow land, …" (CR 608.2h) ---


def _cast_land_destroyer(set_pool, spell: str, land: str):
    """Cast *spell* at a *land* the opponent controls; return the board."""
    pool = set_pool("ICE")
    victim = Permanent(card=pool[land])
    p1 = PlayerState(name="P1", hand=[pool[spell]], life=20)
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(
        0, spell, target_player_index=1, target_permanent_index=0
    )
    game._settle()
    return game, p1, p2, victim


def test_thermokarst_gains_life_only_for_a_snow_land(set_pool):
    """"Destroy target land. If that land was a snow land, you gain 1 life."

    The condition is asked **after** the land is a card in a graveyard, so it
    reads the object as it was (CR 608.2h) — nothing on the board can answer it.
    """
    _game, p1, p2, snow = _cast_land_destroyer(
        set_pool, "Thermokarst", "Snow-Covered Forest"
    )
    assert snow not in p2.battlefield
    assert p1.life == 21

    _game, p1, p2, plain = _cast_land_destroyer(set_pool, "Thermokarst", "Forest")
    assert plain not in p2.battlefield
    assert p1.life == 20, "an ordinary Forest is not a snow land"


def test_icequake_damages_the_controller_only_for_a_snow_land(set_pool):
    """The other half of the cycle, whose rider names the land's controller —
    a seat the destruction has to have recorded for the same reason."""
    _game, p1, p2, snow = _cast_land_destroyer(
        set_pool, "Icequake", "Snow-Covered Swamp"
    )
    assert snow not in p2.battlefield
    assert p2.life == 19

    _game, p1, p2, plain = _cast_land_destroyer(set_pool, "Icequake", "Swamp")
    assert plain not in p2.battlefield
    assert p2.life == 20


# --- Round 12: a counted amount, and a name that is also a creature type ---


def test_songs_of_the_damned_counts_a_graveyard(set_pool):
    """"Add {B} for each creature card **in your graveyard**."

    The mana multiplier was hardwired to the battlefield. The evaluator behind
    it already reads a zone off its spec; what was missing was carrying the one
    the phrase named — and a card in a zone has no computed characteristics
    (CR 613.1), so the narrowing is held to what a *card* can answer.
    """
    pool = set_pool("ICE")
    p1 = PlayerState(
        name="P1", hand=[pool["Songs of the Damned"]],
        graveyard=[pool["Balduvian Bears"], pool["Moor Fiend"], pool["Icequake"]],
        life=20,
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Songs of the Damned")
    game._settle()

    # Two creature cards; Icequake is a sorcery and does not count.
    assert p1.mana_pool["B"] == 2


def test_aurochs_counts_the_creature_type_not_itself(set_pool):
    """"Whenever this creature attacks, it gets +1/+0 until end of turn for each
    other attacking **Aurochs**."

    The word is the creature type, and the card is named after it. Both
    self-reference readers — the lexer's SELF collapsing and the static-line
    path's — turned it into "each other attacking **this creature**": a set of
    one permanent that excludes itself, so always empty, so a pump that always
    resolves for +0/+0 while the card reports supported.
    """
    pool = set_pool("ICE")
    program = compile_card_oracle(pool["Aurochs"])
    assert program.supported

    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "creature_attacks"
    counted = trigger.instruction.payload["x_from_count"]["filter"]
    assert counted["subtype_filter"] == "aurochs"
    assert counted["exclude_self"] is True


def test_a_name_that_is_a_creature_type_still_collapses_in_self_position(set_pool):
    """The other half, and the half that must not break: Lhurgoyf's name is a
    creature type too, and "Lhurgoyf's power is equal to…" is the card naming
    itself (CR 201.4). Only a *type position* is left alone."""
    from engine.oracle import _restriction_line

    assert _restriction_line(
        "Lhurgoyf's power is equal to the number of creature cards in all "
        "graveyards.", "Lhurgoyf",
    ).startswith("this creature's power")
    assert compile_card_oracle(set_pool("ICE")["Lhurgoyf"]).supported


# --- Round 13: "when you control no <noun>" — the noun is payload ---


def test_gorilla_pack_is_sacrificed_without_a_forest(set_pool):
    """"When you control no Forests, sacrifice this creature."

    The identical sentence Sea Serpent prints about Islands, which the engine
    read through a `no_islands` condition kind with the land type welded into
    the name — so this card, and every other type, was unreadable. The noun is
    payload now, tested by the same `subject_matches` the positive twin uses.
    """
    pool = set_pool("ICE")
    program = compile_card_oracle(pool["Gorilla Pack"])
    assert program.supported
    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "controls_no_matching"
    assert trigger.condition.payload["controlled_filter"] == {"subtype_filter": "forest"}

    kept = Permanent(card=pool["Gorilla Pack"])
    p1 = PlayerState(
        name="P1", battlefield=[kept, Permanent(card=pool["Forest"])], life=20
    )
    Game(players=[p1, PlayerState(name="P2", life=20)]).check_state_based_actions()
    assert kept in p1.battlefield

    lost = Permanent(card=pool["Gorilla Pack"])
    p2 = PlayerState(name="P2", battlefield=[lost], life=20)
    Game(players=[p2, PlayerState(name="P3", life=20)]).check_state_based_actions()
    assert lost not in p2.battlefield


# --- Round 14: a hook that had a second card ---


def test_portent_and_elemental_augury_reorder_a_library(set_pool):
    """"Look at the top three cards of target player's library, then put them
    back in any order."

    The sentence Natural Selection prints, verbatim — and `card_hooks`' entry
    bar is that no second card, real or plausibly printable, shares the shape.
    Two did. Portent compiled *supported* on the strength of its cantrip line
    while its main effect was a bare whitelist marker; Elemental Augury has no
    second line and was unsupported outright.
    """
    pool = set_pool("ICE")
    for name in ("Portent", "Elemental Augury"):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        assert "reorder_target_library_top" in {
            instruction.kind for instruction in program.instructions
        }, name


def test_portent_offers_the_shuffle_and_elemental_augury_does_not(set_pool):
    """The optional shuffle is a printed sentence, so it rides the payload —
    Portent prints it and Elemental Augury does not."""
    pool = set_pool("ICE")

    def _reorder(name):
        return next(
            instruction for instruction in compile_card_oracle(pool[name]).instructions
            if instruction.kind == "reorder_target_library_top"
        )

    assert _reorder("Portent").payload["may_shuffle"] is True
    assert _reorder("Elemental Augury").payload["may_shuffle"] is False


# --- Round 15: two Aura effect lines with a P/T half in front ---


def test_spectral_shield_grants_toughness_and_target_immunity(set_pool):
    """"Enchanted creature gets +0/+2 **and** can't be the target of spells."

    Two effects on one line, owned by two readers: the P/T grant is
    `aura_static_pt_grant`'s and the immunity is `target_immunity`'s. The
    immunity reader could not see past the P/T half, so the whole line went
    unclaimed — the same split `_KEYWORD_GRANT` already makes with its optional
    "gets ±N/±N and" prefix, and made in the one place both the support gate and
    the runtime reader go through.
    """
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    shield = Permanent(card=pool["Spectral Shield"])
    p1 = PlayerState(name="P1", battlefield=[bear, shield], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(shield, bear)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 4)
    assert not game._can_be_targeted(bear, 1)


def test_errantry_lets_its_creature_attack_only_alone(set_pool):
    """"Enchanted creature gets +3/+0 and **can only attack alone**." CR 506.5,
    read as a restriction on the *declaration* — a per-creature predicate has no
    way to say "and nobody else", which is why the attack cap beside it is
    checked over the declared set too."""
    from engine.auras import attach_aura

    pool = set_pool("ICE")
    lone = Permanent(card=pool["Balduvian Bears"])
    friend = Permanent(card=pool["Balduvian Barbarians"])
    errantry = Permanent(card=pool["Errantry"])
    p1 = PlayerState(name="P1", battlefield=[lone, friend, errantry], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    attach_aura(errantry, lone)
    game._settle()

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert (lone.effective_power, lone.effective_toughness) == (5, 2)
    ok, message = game.declare_attackers(0, [0, 1])
    assert not ok and "alone" in message
    assert game.declare_attackers(0, [0])[0], "alone is legal"


# --- Round 16: a pay-or-else prompt aimed at the event's player ---


def test_soul_barrier_offers_the_pay_to_the_caster_not_its_controller(set_pool):
    """"Whenever an opponent casts a creature spell, this enchantment deals 2
    damage to **that player** unless **they** pay {2}."

    Both pay-or-else flows offered the cost to the ability's *controller*, so
    this card and Seizures were unsupported outright. The seat is the one the
    fire site froze into the trigger's context (CR 603.10) — the trigger has no
    target, so `context.caster` is the enchantment's controller and prompting
    them would charge and damage the wrong player.
    """
    pool = set_pool("ICE")
    barrier = Permanent(card=pool["Soul Barrier"])
    p1 = PlayerState(name="P1", battlefield=[barrier], life=20)
    p2 = PlayerState(name="P2", hand=[pool["Balduvian Bears"]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(1, "Balduvian Bears")
    game._settle()

    offers = [choice for choice in game.pending_choices if choice.kind == "optional_pay"]
    assert len(offers) == 1
    assert offers[0].player_index == 1, "the spell's caster is offered the cost"
    assert offers[0].data["cost"] == {"generic": 2}
    assert offers[0].data["damage"] == 2


# --- Round 17: a keyword family named whole, and a negated supertype ---


def test_staff_of_the_ages_switches_off_every_landwalk(set_pool):
    """"Creatures with **landwalk abilities** can be blocked as though they
    didn't have **those abilities**."

    The evasion-negation table read one keyword per sentence. CR 702.14a makes
    landwalk a *family* whose members are **open** — the ability's name is built
    from a printed quality, so "snow forestwalk" is one — which is why the
    negation carries the family word rather than a list of members. Enumerating
    the five basics was the first attempt, and it left Rime Dryad's snow
    forestwalk enforced against a Staff that says it is not.
    """
    from engine.evasion_negation import evasion_negation_for
    from engine.landwalk import LANDWALK

    assert evasion_negation_for(
        "creatures with landwalk abilities can be blocked as though they "
        "didn't have those abilities"
    ) == frozenset({LANDWALK})
    assert compile_card_oracle(set_pool("ICE")["Staff of the Ages"]).supported


def test_staff_of_the_ages_lets_a_forestwalker_be_blocked(set_pool):
    """Run in real combat: with a Forest out, forestwalk normally forbids the
    block, and the Staff lifts the restriction (CR 509.1b) without removing the
    keyword."""
    pool = set_pool("ICE")

    def _blocks(with_staff: bool) -> bool:
        walker = Permanent(card=pool["Rime Dryad"])  # snow forestwalk
        blocker = Permanent(card=pool["Balduvian Bears"])
        snow = Permanent(card=pool["Snow-Covered Forest"])
        theirs = [blocker, snow]
        if with_staff:
            theirs.append(Permanent(card=pool["Staff of the Ages"]))
        p1 = PlayerState(name="P1", battlefield=[walker], life=20)
        p2 = PlayerState(name="P2", battlefield=theirs, life=20)
        game = Game(players=[p1, p2])
        _combat(game, [0])
        return game.declare_blockers(1, {0: 0})[0]

    assert not _blocks(with_staff=False)
    assert _blocks(with_staff=True)


def test_hallowed_ground_returns_only_a_nonsnow_land(set_pool):
    """"Return target **nonsnow** land you control to its owner's hand." A
    negated supertype (CR 205.4), which no layer computes — the matcher reads
    it off the effective type line, exactly as it reads the positive key."""
    pool = set_pool("ICE")
    program = compile_card_oracle(pool["Hallowed Ground"])
    assert program.supported

    ability = program.activated_abilities[0]
    described = ability.instruction.payload["filter"]
    assert described["exclude_supertypes"] == ["snow"]

    from engine.subject_filters import subject_matches

    plain = Permanent(card=pool["Forest"])
    snowy = Permanent(card=pool["Snow-Covered Forest"])
    p1 = PlayerState(name="P1", battlefield=[plain, snowy], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    assert subject_matches(game, plain, described, observer=0)
    assert not subject_matches(game, snowy, described, observer=0)


# --- Round 18: "enters with X <kind> counters", with the kind as data ---


def test_balduvian_hydra_enters_with_x_plus_one_zero_counters(set_pool):
    """"This creature enters with X **+1/+0** counters on it."

    The printed-count form reads its counter kind off the line; the X form was
    a literal sentence naming +1/+1, so Rock Hydra worked and this card —
    printing the identical template one counter kind over — did not. The count
    is still what separates them: it is the announced X (CR 601.2b), not a
    printed number.
    """
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Balduvian Hydra"]], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Balduvian Hydra", x_value=3)
    game._settle()

    hydra = p1.battlefield[0]
    assert (hydra.effective_power, hydra.effective_toughness) == (3, 1)
    assert hydra.metadata["plus_1_0_counters"] == 3


# --- Round 19: an offer whose action shares the printed subject ---


def test_thoughtleech_offers_the_life_when_an_opponents_island_taps(set_pool):
    """"Whenever an Island an opponent controls becomes tapped, **you may gain
    1 life**."

    The offer prints its subject once, in front of "may", and the action behind
    it is a bare verb — the same shared-subject shape a conjunction already
    handles ("Target player draws a card **and loses 1 life**"), one clause
    earlier. Without it "you may gain 1 life" refused while "you may draw a
    card" parsed, because "draw" is a bare imperative and "gain" is not.
    """
    pool = set_pool("ICE")
    leech = Permanent(card=pool["Thoughtleech"])
    island = Permanent(card=pool["Island"])
    p1 = PlayerState(name="P1", battlefield=[leech], life=20)
    p2 = PlayerState(name="P2", battlefield=[island], life=20)
    game = Game(players=[p1, p2])

    game.become_tapped(island)
    game._settle()

    offers = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert len(offers) == 1 and offers[0].player_index == 0
    assert offers[0].data["cost"] == {}, "the offer costs nothing; it is a may"

    game.auto_resolve_pending_optional_pays()
    game._settle()
    assert p1.life == 21


# --- Round 20: a possessive back-reference written with its noun ---


def test_word_of_blasting_burns_for_the_walls_mana_value(set_pool):
    """"Destroy target Wall. It can't be regenerated. This spell deals damage
    equal to **that Wall's** mana value to **the Wall's** controller."

    Three readers had to widen for one card, and each was narrowed by a word
    rather than by a meaning: the amount read only "its mana value" (a pronoun),
    the recipient read only "that/this <card type>'s controller" (a Wall is a
    *subtype*), and the damage handler had no branch for the scratchpad channel
    at all — so the lowering was already emitting `amount_from` and nothing read
    it, which would have dealt 0 on a card reporting supported.
    """
    pool = set_pool("ICE")
    wall = Permanent(card=pool["Glacial Wall"])  # mana value 3
    p1 = PlayerState(name="P1", hand=[pool["Word of Blasting"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[wall], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Word of Blasting", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert wall not in p2.battlefield
    assert p2.life == 17


# --- Round 21: a regeneration rider on a subject nothing targets ---


def test_incinerate_kills_through_a_regeneration_shield(set_pool):
    """"Incinerate deals 3 damage to any target. **A creature dealt damage this
    way** can't be regenerated this turn."

    CR 701.19c printed as a sentence about the *effect* rather than about a
    pronoun — the damage twin of War Barge's "A creature destroyed this way
    can't be regenerated", and it exists for the same reason: by the time the
    rider is read there is no "it" left to point at, so the noun restates what
    the damage already named. The rider parser required the sentence to open
    with "it" or "if", so Incinerate refused its only line.
    """
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])  # 2/2
    bears.regeneration_shield = 1
    p1 = PlayerState(name="P1", hand=[pool["Incinerate"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[bears], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(
        0, "Incinerate", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert bears.metadata["cant_be_regenerated_this_turn"]
    assert bears not in p2.battlefield, "the shield cannot answer this damage"
    assert bears.regeneration_shield == 1, "and it was not spent"


def test_lim_duls_cohort_denies_regeneration_to_what_it_blocks(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature, **that
    creature** can't be regenerated this turn."

    The third subject the rider can have, beside a chosen target (Hurr Jackal)
    and the ability's own source (Clergy of the Holy Nimbus): the other half of
    the blocking pair, which nothing on the board records and only the trigger
    knows. `_lower_cant_be` saw no event at all and refused every subject that
    was neither, so the card compiled with its only line lowering to nothing.

    Run in real combat rather than asserted on the payload, because the thing
    that could go wrong is *which* creature is marked: on the blocks half the
    stack item's target is the blocking creature itself, so a handler reading
    the target would deny regeneration to the Cohort and still look resolved.
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])  # 2/2
    attacker.regeneration_shield = 1
    cohort = Permanent(card=pool["Lim-Dûl's Cohort"])  # 2/2
    p1 = PlayerState(name="P1", battlefield=[attacker], life=20)
    p2 = PlayerState(name="P2", battlefield=[cohort], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()

    assert attacker.metadata.get("cant_be_regenerated_this_turn")
    assert not cohort.metadata.get("cant_be_regenerated_this_turn"), (
        "the rider names the creature it blocked, not itself"
    )

    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert attacker not in p1.battlefield, "2 damage is lethal and unregenerable"


# --- Round 22: "if it's <colour>" — the colour is payload, the pronoun is not ---


def _blast_board(set_pool, blast: str, spell: str, **cast):
    """Seat 0 holding *blast*, with seat 1's *spell* already on the stack."""
    pool = set_pool("ICE")
    library = [pool["Balduvian Bears"] for _ in range(5)]
    p1 = PlayerState(name="P1", hand=[pool[blast]], library=library, life=20)
    p2 = PlayerState(name="P2", hand=[pool[spell]], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, spell, **cast)
    assert [item.card.name for item in game.stack] == [spell]
    return game


def test_hydroblast_counters_a_red_spell(set_pool):
    """"Counter target spell **if it's red**." CR 608.2c: the colour is read
    while the instruction is followed, so the clause lowers to an `if_then`
    over the ordinary counter rather than to a colour narrowing on it."""
    game = _blast_board(set_pool, "Hydroblast", "Incinerate", target_player_index=0)

    game.cast_from_hand(0, "Hydroblast", mode_index=0, target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert game.players[0].life == 20, "the burn never resolved"
    assert "Incinerate" in [c.name for c in game.players[1].graveyard]


def test_hydroblast_may_target_a_spell_it_cannot_counter(set_pool):
    """The half that separates this from "counter target **red** spell".

    "Target spell" is the whole of the printed restriction (CR 608.2b), so a
    blue spell is a legal target and Hydroblast simply does nothing to it —
    where a colour narrowing on the counter would have refused the cast and
    narrowed the picker. Lowering it as `counter_top_stack_spell` with a
    `color_filter` would have been the smaller diff and the wrong card.
    """
    game = _blast_board(
        set_pool, "Hydroblast", "Ray of Erasure", target_player_index=0
    )

    game.cast_from_hand(0, "Hydroblast", mode_index=0, target_stack_index=0)
    game.resolve_stack()
    game._settle()

    assert not game.stack
    # The blue spell resolved: its mill took a card off the library it named.
    assert len(game.players[0].library) == 4
    assert "Balduvian Bears" in [c.name for c in game.players[0].graveyard]
    assert "Ray of Erasure" in [c.name for c in game.players[1].graveyard]


def test_pyroblast_destroys_a_blue_permanent_and_spares_the_rest(set_pool):
    """The second mode, and the colour read off a *permanent* rather than a
    spell. Same printed condition, different half of the resolution context —
    which is why the referent is bound at lowering, from the effect beside it,
    rather than guessed at resolution."""
    pool = set_pool("ICE")

    def _destroys(victim: str) -> bool:
        target = Permanent(card=pool[victim])
        p1 = PlayerState(name="P1", hand=[pool["Pyroblast"]], life=20)
        p2 = PlayerState(name="P2", battlefield=[target], life=20)
        game = Game(players=[p1, p2])
        game.enforce_mana_costs = False
        game.cast_from_hand(
            0, "Pyroblast", mode_index=1,
            target_player_index=1, target_permanent_index=0,
        )
        game._settle()
        return target not in p2.battlefield

    assert _destroys("Illusionary Wall")      # blue
    assert not _destroys("Balduvian Bears")   # red


def test_the_two_blasts_differ_only_by_the_colour_in_the_payload(set_pool):
    """One production, two cards. The colour is a payload symbol — the spelling
    every filter and colour accessor in the engine already uses — so a third
    card printing "if it's white" needs no parser change at all."""
    pool = set_pool("ICE")
    conditions = {}
    for name in ("Hydroblast", "Pyroblast"):
        program = compile_card_oracle(pool[name])
        conditions[name] = [
            mode.instruction.payload["condition"] for mode in program.modes
        ]

    assert conditions["Hydroblast"] == [
        {"kind": "target_is_color", "color": "R", "negated": False, "target": "spell"},
        {"kind": "target_is_color", "color": "R", "negated": False, "target": "permanent"},
    ]
    assert conditions["Pyroblast"] == [
        {"kind": "target_is_color", "color": "U", "negated": False, "target": "spell"},
        {"kind": "target_is_color", "color": "U", "negated": False, "target": "permanent"},
    ]
