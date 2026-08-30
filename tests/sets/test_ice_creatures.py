"""Ice Age (ICE) creature cards.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.cumulative_upkeep import cumulative_upkeep_cost
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Round 1: cumulative upkeep (CR 702.24) ---
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
def test_musician_still_refuses_a_cost_the_engine_cannot_charge(set_pool):
    """The keyword compiles, but "That enchantment gains ..." does not, so the
    card stays unsupported naming the clause it cannot read.

    Kept from round 1 as the shape rather than the card: what the gate must not
    do is admit a permanent on the strength of a keyword it *can* read while
    dropping a line it cannot."""
    musician = set_pool("ICE")["Musician"]
    program = compile_card_oracle(musician)

    assert not program.supported
    # The refusal names the granted-ability line, not the keyword: the cost
    # reader admits "{1}" and the gate still says no.
    assert "music counter" in (program.reason or "")
    assert cumulative_upkeep_cost("cumulative upkeep {1}") is not None
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
# --- Round 12: a counted amount, and a name that is also a creature type ---
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
# --- Round 23: a combat restriction is about the declaration, not the creature ---
def test_goblin_mutant_is_grounded_by_an_untapped_defender(set_pool):
    """"This creature can't attack **if** defending player controls an untapped
    creature with power 3 or greater."

    The same question Sea Serpent's "unless defending player controls an
    Island" asks, one polarity over — so both are one kind carrying the printed
    noun phrase and the printed word. The noun used to be one of five basic
    land *words*, because the enforcing check scanned the defender's lands by
    name; it reads a filter through `subject_matches` now, which is what lets
    "an untapped creature with power 3 or greater" be the same restriction.
    """
    pool = set_pool("ICE")

    def _may_attack(defender_creature: str | None, tapped: bool = False) -> bool:
        mutant = _nosick(Permanent(card=pool["Goblin Mutant"]))
        theirs = []
        if defender_creature is not None:
            blocker = Permanent(card=pool[defender_creature])
            blocker.tapped = tapped
            theirs.append(blocker)
        game = Game(players=[
            PlayerState(name="P1", battlefield=[mutant], life=20),
            PlayerState(name="P2", battlefield=theirs, life=20),
        ])
        return game.can_attack(mutant, 1)

    assert _may_attack(None)
    assert _may_attack("Balduvian Bears")           # 2/2 — under the threshold
    assert not _may_attack("Balduvian Barbarians")  # 3/1 — at it
    assert _may_attack("Balduvian Barbarians", tapped=True), (
        "the clause says untapped, and the word is part of the filter"
    )
def test_orcish_conscripts_needs_company_to_attack(set_pool):
    """"This creature can't attack **unless at least two other creatures
    attack**."

    CR 508.1c asks a restriction of the whole declaration — "if any
    restrictions are being disobeyed, the declaration is illegal" — so this one
    is not a fact about the creature and `can_attack`, which sees one creature
    at a time, cannot answer it. It is checked where Errantry's "can only
    attack alone" already is, which is the same rule read from the other end.
    """
    pool = set_pool("ICE")
    conscripts = _nosick(Permanent(card=pool["Orcish Conscripts"]))
    friends = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[conscripts, *friends], life=20),
        PlayerState(name="P2", life=20),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers

    assert game.can_attack(conscripts, 1), "nothing about the creature forbids it"
    assert not game.declare_attackers(0, [0])[0]
    assert not game.declare_attackers(0, [0, 1])[0]
    assert game.declare_attackers(0, [0, 1, 2])[0]
def test_orcish_conscripts_needs_company_to_block(set_pool):
    """The blocking twin, CR 509.1b — the same restriction read on the other
    side of combat, so the count is payload and the word is the only
    difference."""
    pool = set_pool("ICE")
    attackers = [_nosick(Permanent(card=pool["Balduvian Bears"])) for _ in range(3)]
    conscripts = Permanent(card=pool["Orcish Conscripts"])
    friends = [Permanent(card=pool["Balduvian Bears"]) for _ in range(2)]

    def _may_block(with_friends: int) -> bool:
        game = Game(players=[
            PlayerState(name="P1", battlefield=attackers, life=20),
            PlayerState(
                name="P2", battlefield=[conscripts, *friends[:with_friends]], life=20
            ),
        ])
        _combat(game, [0, 1, 2])
        assignments = {slot: slot for slot in range(with_friends + 1)}
        return game.declare_blockers(1, assignments)[0]

    assert not _may_block(0)
    assert not _may_block(1)
    assert _may_block(2)
# --- Round 25: a borrowed permanent, and what the sentences after it name ---
def test_magus_of_the_unseen_is_ray_of_command_over_a_noun(set_pool):
    """One template, two cards: the printed type is payload on both the untap
    and the grant, and the trailing trigger names it a third time."""
    pool = set_pool("ICE")
    steps = {}
    for name in ("Ray of Command", "Magus of the Unseen"):
        program = compile_card_oracle(pool[name])
        sequence = next(
            i for i in program.instructions if i.kind == "sequence"
        )
        steps[name] = sequence.payload["steps"]

    for name, noun in (("Ray of Command", "creature"), ("Magus of the Unseen", "artifact")):
        untap, control, haste = steps[name]
        assert untap.payload["type_filter"] == noun
        assert control.payload == {
            "permanents_from": "untapped_permanents", "tap_when_lost": True,
        }
        assert haste.payload["keywords"] == ("haste",)
# --- Round 26: a printed restriction clause is a conjunction of restrictions ---
def _restricted_combat(set_pool, source_name: str, *, defender_lands=(), extra=()):
    """*source_name* on the battlefield, mid-combat, with the defender's board
    set. Combat because all three cards this round buys print "only during
    combat" or a step inside it."""
    pool = set_pool("ICE")
    source = Permanent(card=pool[source_name])
    p1 = PlayerState(name="P1", battlefield=[source, *extra], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=pool[n]) for n in defender_lands], life=20
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game._sync_control()
    for perm in (source, *extra):
        _nosick(perm)
    return game, source
def test_arcums_sleigh_needs_the_defender_to_hold_a_snow_land(set_pool):
    """"{2}, {T}: Target creature gains vigilance until end of turn. Activate
    only during combat and only if defending player controls a snow land."

    Both halves are enforced, which is what the clause being a *conjunction*
    buys: the sentence used to match no row at all, so the line refused and the
    card was unsupported.
    """
    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    game, _sleigh = _restricted_combat(
        set_pool, "Arcum's Sleigh", defender_lands=["Plains"], extra=[bear]
    )

    refused = game.activate_permanent_ability(
        0, "Arcum's Sleigh", target_player_index=0, target_permanent_index=1
    )
    assert not refused.supported
    assert not bear.has_keyword("vigilance")

    game.players[1].battlefield.append(Permanent(card=pool["Snow-Covered Plains"]))
    game._sync_control()
    allowed = game.activate_permanent_ability(
        0, "Arcum's Sleigh", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert allowed.supported, allowed.details
    assert bear.has_keyword("vigilance")
def test_kjeldoran_guard_is_the_same_clause_negated(set_pool):
    """"…only if defending player controls **no** snow lands." One row with the
    other polarity — the article is the quantifier, so this card needed no code
    of its own once Arcum's Sleigh's did."""
    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    game, _guard = _restricted_combat(
        set_pool, "Kjeldoran Guard",
        defender_lands=["Snow-Covered Plains"], extra=[bear],
    )

    refused = game.activate_permanent_ability(
        0, "Kjeldoran Guard", target_player_index=0, target_permanent_index=1
    )
    assert not refused.supported
    assert bear.effective_power == 2

    game.players[1].battlefield.clear()
    game._sync_control()
    allowed = game.activate_permanent_ability(
        0, "Kjeldoran Guard", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert allowed.supported, allowed.details
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
def test_kjeldoran_guard_dies_with_the_creature_it_pumped(set_pool):
    """"When that creature leaves the battlefield this turn, sacrifice this
    creature." CR 603.7's delayed trigger, already read by the grammar — the
    card was unsupported for its restriction clause alone, three sentences
    later."""
    pool = set_pool("ICE")
    bear = Permanent(card=pool["Balduvian Bears"])
    game, guard = _restricted_combat(set_pool, "Kjeldoran Guard", extra=[bear])

    result = game.activate_permanent_ability(
        0, "Kjeldoran Guard", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert result.supported, result.details

    game.remove_from_battlefield(bear)
    game._settle()

    assert not any(perm is guard for perm in game.all_permanents())
def test_grizzled_wolverine_prints_three_restrictions_in_one_sentence(set_pool):
    """"Activate only during the declare blockers step, only if at least one
    creature is blocking this creature, and only once each turn."

    Three conjuncts joined by commas, and the third is the per-turn cap the
    optional tails on three rows used to carry. All three are enforced.
    """
    pool = set_pool("ICE")
    wolverine = Permanent(card=pool["Grizzled Wolverine"])
    blocker = Permanent(card=pool["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[wolverine], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game._sync_control()
    _nosick(wolverine)
    _nosick(blocker)

    ok, message = game.declare_attackers(0, [0])
    assert ok, message
    game.current_step = "declare_blockers"

    unblocked = game.activate_permanent_ability(0, "Grizzled Wolverine")
    assert not unblocked.supported
    assert wolverine.effective_power == 2

    ok, message = game.declare_blockers(1, {0: 0})
    assert ok, message

    pumped = game.activate_permanent_ability(0, "Grizzled Wolverine")
    game._settle()
    assert pumped.supported, pumped.details
    assert wolverine.effective_power == 4

    again = game.activate_permanent_ability(0, "Grizzled Wolverine")
    assert not again.supported, "…and only once each turn"
    assert wolverine.effective_power == 4
def test_grizzled_wolverine_is_refused_outside_the_declare_blockers_step(set_pool):
    """The first conjunct on its own. A creature blocking it in the damage step
    is still blocking it, so the step half is the only thing refusing here —
    which is what makes the three conjuncts three rules rather than one."""
    game, wolverine = _restricted_combat(set_pool, "Grizzled Wolverine")
    game.current_step = "combat_damage"

    refused = game.activate_permanent_ability(0, "Grizzled Wolverine")

    assert not refused.supported
    assert "only during the declare blockers step" in refused.details
# --- Round 29: restricted mana is about a payment, not about a cast ---
def _mana_board(set_pool, *names, hand=()):
    """Cards on the battlefield with real mana costs enforced."""
    from engine.card_loader import load_catalog

    pool = set_pool("ICE")
    shipped = {card.name: card for card in load_catalog()}

    def card(name):
        return pool.get(name) or shipped[name]

    perms = [Permanent(card=card(n)) for n in names]
    p1 = PlayerState(
        name="P1", battlefield=perms, hand=[card(n) for n in hand],
        library=[card("Plains")] * 5, life=20,
    )
    p2 = PlayerState(
        name="P2", battlefield=[Permanent(card=card("Plains"))],
        library=[card("Plains")] * 5, life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    game._sync_control()
    for perm in perms:
        _nosick(perm)
    return game, p1, perms
def test_soldevi_machinist_mana_activates_an_artifacts_ability(set_pool):
    """"{T}: Add {C}{C}. Spend this mana only to activate abilities of
    artifacts."

    The mana lands in its own bucket (CR 106.6) and the activation path can now
    see it — it could not before, because a restriction was a claim about the
    spell being cast and only the casting path ever asked.
    """
    game, p1, (machinist, icy) = _mana_board(
        set_pool, "Soldevi Machinist", "Icy Manipulator"
    )

    game.activate_permanent_ability(0, "Soldevi Machinist")
    game._settle()
    assert p1.restricted_mana["artifact_ability"]["C"] == 2
    assert not any(p1.mana_pool.values()), "restricted mana is held apart"

    result = game.activate_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert p1.restricted_mana["artifact_ability"]["C"] == 1, "one paid the {1}"
def test_soldevi_machinist_mana_cannot_cast_an_artifact_spell(set_pool):
    """"…only to **activate abilities of** artifacts" is not "…to cast artifact
    spells" (Mishra's Workshop). Three clauses, three narrowings, and a
    cast-only predicate could not have told the second from the third."""
    game, p1, _ = _mana_board(
        set_pool, "Soldevi Machinist", hand=["Meekstone"]
    )
    game.activate_permanent_ability(0, "Soldevi Machinist")
    game._settle()

    result = game.cast_from_hand(0, "Meekstone")

    assert not result.supported
    assert p1.restricted_mana["artifact_ability"]["C"] == 2, "nothing was spent"
def test_cumulative_upkeep_can_be_paid_from_its_own_bucket(set_pool):
    """"Spend this mana only to pay cumulative upkeep costs." (Adarkar Unicorn,
    Snowfall.)

    The upkeep payment is a third path, with its own pair of functions, and it
    could not see a restricted bucket at all — so this mana existed and could
    pay for nothing in the game.
    """
    game, p1, (wall,) = _mana_board(set_pool, "Illusionary Wall")
    p1.restricted_mana.setdefault("cumulative_upkeep", {})["U"] = 3
    game.turn = 2

    game.resolve_upkeep(0)

    assert any(perm is wall for perm in game.all_permanents()), (
        "the upkeep was paid from the restricted bucket"
    )

    # And the pair itself, because by the time the step is over the bucket has
    # emptied with the pool (CR 500.4) and the count no longer reads back. The
    # purpose is what makes the bucket visible at all: without one the same
    # board cannot pay.
    from engine.restricted_mana import CUMULATIVE_UPKEEP, PaymentPurpose

    p1.restricted_mana["cumulative_upkeep"]["U"] = 3
    cost = {"U": 1, "generic": 0}
    purpose = PaymentPurpose(CUMULATIVE_UPKEEP, source=wall)
    assert game.can_pay_upkeep_mana(p1, cost, purpose=purpose) is True
    assert game.can_pay_upkeep_mana(p1, cost) is False, (
        "a payment that does not say what it is for is offered no restricted mana"
    )
    game._spend_upkeep_mana(p1, cost, purpose=purpose)
    assert p1.restricted_mana["cumulative_upkeep"]["U"] == 2
    assert not any(p1.mana_pool.values()), "and nothing came out of the pool"
def test_an_unpaid_cumulative_upkeep_still_sacrifices(set_pool):
    """Paired with the test above, so what it reads is the bucket being spent
    and not the upkeep having quietly stopped asking."""
    game, p1, (wall,) = _mana_board(set_pool, "Illusionary Wall")
    game.turn = 2

    game.resolve_upkeep(0)

    assert not any(perm is wall for perm in game.all_permanents())
def test_adarkar_unicorn_refuses_a_choice_between_multi_symbol_runs(set_pool):
    """"{T}: Add {U} or {C}{U}." The payload can express a choice only between
    single symbols, so merging this one produced a bag reading "either one {C}
    or two {U}" — neither of the two things the card prints.

    The line refuses instead, which leaves the card unsupported rather than
    supported and making mana it does not have. Its *restriction* clause is
    implemented; this is the only thing still holding it back.
    """
    from engine.grammar import compile_line
    from engine.restricted_mana import mana_restriction_for

    unicorn = set_pool("ICE")["Adarkar Unicorn"]
    assert not compile_card_oracle(unicorn).supported

    refused = compile_line("{T}: Add {U} or {C}{U}.")
    assert not refused.parsed
    assert "more than one symbol" in (refused.parse_error or "")

    # The single-symbol alternation every dual land prints is untouched.
    dual = compile_line("{T}: Add {B} or {R}.")
    assert dual.lowered
    assert dual.instructions[0].payload["pips_choice"] == (("B", 1), ("R", 1))

    assert mana_restriction_for(
        "Spend this mana only to pay cumulative upkeep costs."
    ) is not None
# --- Round 30: a card counted supported that did nothing it said ---
def test_panics_restriction_lasts_exactly_the_turn(set_pool):
    """"…this turn." Swept by the cleanup step with the rest of the turn's
    marks, so the creature blocks again next combat. Paired with the test above,
    because a restriction that never ends passes that one too."""
    pool = set_pool("ICE")
    blocker = Permanent(card=pool["Hoar Shade"])
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[], hand=[pool["Panic"]], life=20),
            PlayerState(name="P2", battlefield=[blocker], life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game._sync_control()
    _nosick(blocker)

    game.cast_from_hand(0, "Panic", target_player_index=1, target_permanent_index=0)
    game._settle()
    assert blocker.metadata.get("cant_block_until_eot")

    game.resolve_cleanup_step(0)

    assert not blocker.metadata.get("cant_block_until_eot")
# --- Round 31: a cumulative upkeep cost is a cost, not a mana cost ---
def _ice_lands(set_pool, name, count):
    return [Permanent(card=set_pool("ICE")[name]) for _ in range(count)]
def test_polar_kraken_pays_its_upkeep_by_sacrificing_a_land(set_pool):
    """"Cumulative upkeep—Sacrifice a land." The cost is a sacrifice, so the
    payment is one of the controller's own lands (CR 701.21a) and the Kraken
    stays on the battlefield."""
    kraken = Permanent(card=set_pool("ICE")["Polar Kraken"])
    forests = _ice_lands(set_pool, "Forest", 3)
    p1 = PlayerState(name="P1", battlefield=[kraken, *forests], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)

    assert compile_card_oracle(kraken.card).supported
    assert counters_on(kraken, "age") == 1
    assert kraken in p1.battlefield
    assert len([p for p in p1.battlefield if p.card.primary_type == "land"]) == 2
def test_polar_kraken_sacrifices_one_land_per_age_counter(set_pool):
    """CR 702.24a's "for each age counter on it" is about the whole cost, so
    the second upkeep asks for two lands, not one."""
    kraken = Permanent(card=set_pool("ICE")["Polar Kraken"])
    forests = _ice_lands(set_pool, "Forest", 4)
    p1 = PlayerState(name="P1", battlefield=[kraken, *forests], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    assert len([p for p in p1.battlefield if p.card.primary_type == "land"]) == 3

    game.resolve_upkeep(0)
    assert counters_on(kraken, "age") == 2
    assert len([p for p in p1.battlefield if p.card.primary_type == "land"]) == 1
    assert kraken in p1.battlefield
def test_polar_kraken_is_sacrificed_when_the_lands_run_out(set_pool):
    """Two lands, and a second upkeep that asks for two: one is left over and
    partial payment is not allowed, so the land stays and the Kraken goes."""
    kraken = Permanent(card=set_pool("ICE")["Polar Kraken"])
    forests = _ice_lands(set_pool, "Forest", 2)
    p1 = PlayerState(name="P1", battlefield=[kraken, *forests], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    game.resolve_upkeep(0)

    assert kraken not in p1.battlefield
    assert len([p for p in p1.battlefield if p.card.primary_type == "land"]) == 1
def test_polar_krakens_button_does_not_say_pay_sacrifice(set_pool):
    """A sacrifice is a thing the payer does, not a thing they hand over, so
    the imperative on the button is the cost's own — "Pay sacrifice a land" is
    not a sentence."""
    kraken = Permanent(card=set_pool("ICE")["Polar Kraken"])
    p1 = PlayerState(name="P1", battlefield=[kraken], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    entry = next(
        c for c in game.get_upkeep_pay_triggers(0)
        if c["card_name"] == "Polar Kraken"
    )

    assert entry["cost_label"] == "sacrifice a land"
    assert entry["cost_pay_label"] == "Sacrifice a land"
# --- Round 33: the rest go back on top, and that is a decision ---
def _library_of(set_pool, *names):
    pool = set_pool("ICE")
    return [pool[n] for n in names]
def test_orcish_librarian_exiles_four_at_random_and_stacks_the_other_four(set_pool):
    """"{R}, {T}: Look at the top eight cards of your library. Exile four of
    them at random, then put the rest on top of your library in any order."

    Nothing is picked and nothing reaches a hand, so it is a different
    statement from Diabolic Vision's — what the two share is the tail, and the
    tail is where they share it.
    """
    import random

    from tests.helpers import _nosick

    library = _library_of(
        set_pool, "Balduvian Bears", "Tor Giant", "Scaled Wurm", "Forest",
        "Mountain", "Island", "Swamp", "Plains", "Balduvian Barbarians",
    )
    librarian = Permanent(card=set_pool("ICE")["Orcish Librarian"])
    _nosick(librarian)
    p1 = PlayerState(
        name="P1", battlefield=[librarian], library=list(library), life=20,
        mana_pool={"R": 1},
    )
    game = Game(
        players=[p1, PlayerState(name="P2", life=20)], interactive_seats={0}
    )

    random.seed(7)
    assert game.activate_permanent_ability(0, "Orcish Librarian").supported
    while game.stack:
        game.resolve_top_of_stack()

    assert len(p1.exile) == 4
    assert len(p1.library) == 5, "four exiled, four back on top, one untouched"
    assert p1.library[4].name == "Balduvian Barbarians", "the ninth card never moved"
    assert game.pending_choice_of("reorder_library", 0) is not None
def test_orcish_librarian_is_deterministic_for_a_seed(set_pool):
    """The exile is at random and the AI regression tests rest on a seed
    replaying a run exactly, so it draws on the module RNG rather than a fresh
    one."""
    import random

    from tests.helpers import _nosick

    def _run() -> list[str]:
        librarian = Permanent(card=set_pool("ICE")["Orcish Librarian"])
        _nosick(librarian)
        p1 = PlayerState(
            name="P1", battlefield=[librarian],
            library=_library_of(
                set_pool, "Balduvian Bears", "Tor Giant", "Scaled Wurm",
                "Forest", "Mountain", "Island", "Swamp", "Plains",
            ),
            life=20, mana_pool={"R": 1},
        )
        game = Game(players=[p1, PlayerState(name="P2", life=20)])
        game.activate_permanent_ability(0, "Orcish Librarian")
        while game.stack:
            game.resolve_top_of_stack()
        return [c.name for c in p1.exile]

    random.seed(11)
    first = _run()
    random.seed(11)
    assert _run() == first


# --- Round 34: one verb over two noun phrases, and how many of them may be targeted ---


def test_snow_hound_returns_itself_and_the_creature_it_names(set_pool):
    """"{1}, {T}: Return this creature and target green or blue creature you
    control to their owner's hand."

    One verb over two noun phrases. Both halves already worked apart — the
    self-bounce and the targeted bounce are separate productions — and what was
    missing was the union: `_parse_further_subjects` took only "all" and "each",
    because a quantifier is the one signal available before the verb arrives.
    """
    hound = Permanent(card=set_pool("ICE")["Snow Hound"])
    other = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    _nosick(hound)
    p1 = PlayerState(
        name="P1", battlefield=[hound, other], life=20, mana_pool={"C": 1}
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    result = game.activate_permanent_ability(
        0, "Snow Hound", target_permanent_index=1, target_player_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert result.supported
    assert p1.battlefield == []
    assert sorted(c.name for c in p1.hand) == ["Balduvian Bears", "Snow Hound"]


def test_giant_trap_door_spider_exiles_itself_and_the_attacker(set_pool):
    """"{1}{R}{G}, {T}: Exile this creature and target creature without flying
    that's attacking you." The same union, one verb over, and each half goes to
    its own owner's exile."""
    spider = Permanent(card=set_pool("ICE")["Giant Trap Door Spider"])
    _nosick(spider)
    attacker = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    attacker.attacking = True
    attacker.defending_player_index = 0
    p1 = PlayerState(
        name="P1", battlefield=[spider], life=20,
        mana_pool={"R": 1, "G": 1, "C": 1},
    )
    p2 = PlayerState(name="P2", battlefield=[attacker], life=20)
    game = Game(players=[p1, p2])
    game.combat_attackers = {0: 0}

    result = game.activate_permanent_ability(
        0, "Giant Trap Door Spider", target_permanent_index=0, target_player_index=1
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert result.supported
    assert [c.name for c in p1.exile] == ["Giant Trap Door Spider"]
    assert [c.name for c in p2.exile] == ["Balduvian Bears"]


def test_a_union_of_two_targeted_phrases_is_refused(set_pool):
    """"Destroy target creature and target land." (Fumarole.)

    The union reads it, and the *picker* cannot: a spell is asked for one
    target (``targeting.derive_cast_spec`` answers with one kind), so admitting
    this would compile a card that is supported and uncastable, its second
    target chosen by nobody. It refuses naming that, and the two cards above are
    unaffected because their first phrase is the source rather than a target.
    """
    program = compile_card_oracle(set_pool("ICE")["Fumarole"])

    assert not program.supported


def test_and_still_joins_two_effects_rather_than_two_objects(set_pool):
    """"and" is the commonest word on a Magic card. A targeted *player* after
    it parses to ``ast.PlayerRef``, which was never a candidate for this union
    — so "…and target player draws a card" is still two statements."""
    from engine.grammar import compile_line

    joined = compile_line("Destroy target creature and target player draws a card.")

    assert [i.kind for i in joined.instructions] == [
        "destroy_target_permanent", "draw_target_cards",
    ]


# --- Round 35: the pronoun names what the sentence in front of it chose ---


def test_krovikan_elementalist_sacrifices_the_creature_it_gave_flying(set_pool):
    """"{U}{U}: Target creature you control gains flying until end of turn.
    Sacrifice it at the beginning of the next end step."

    "It" is the creature the first sentence targeted. The card was **supported**
    and armed the sacrifice on *itself*: the sentence reached the general
    delayed-trigger production, which reads the pronoun as the ability's source.
    So the Elementalist died at end of turn and the creature it had just given
    flying to walked away — a card doing something other than what it prints,
    with nothing failing.
    """
    elementalist = Permanent(card=set_pool("ICE")["Krovikan Elementalist"])
    bear = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    _nosick(elementalist)
    p1 = PlayerState(
        name="P1", battlefield=[elementalist, bear], life=20, mana_pool={"U": 2}
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.activate_permanent_ability(
        0, "Krovikan Elementalist", ability_index=1,
        target_permanent_index=1, target_player_index=0,
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert bear.has_keyword("flying")
    assert bear.metadata.get("sacrifice_at_next_end_step") is True
    assert elementalist.metadata.get("sacrifice_at_next_end_step") is None

    game.resolve_end_step(0)

    assert [p.card.name for p in p1.battlefield] == ["Krovikan Elementalist"]
    assert [c.name for c in p1.graveyard] == ["Balduvian Bears"]


# --- Round 36: a hook that had a second card, and the noun phrase it dropped ---


def test_norritt_gets_the_ability_nettling_imp_had_hooked(set_pool):
    """"{T}: Choose target non-Wall creature the active player has controlled
    continuously since the beginning of the turn. That creature attacks this
    turn if able. Destroy it at the beginning of the next end step if it didn't
    attack this turn. Activate only before attackers are declared."

    Nettling Imp prints that ability *verbatim* apart from the last sentence —
    "Activate only during an opponent's turn, before attackers are declared" —
    and was a card hook keyed on the whole line. So the identical effect on a
    second card reached nothing at all, which is exactly the arithmetic
    `HOOK_RELIANCE.md` measures.
    """
    program = compile_card_oracle(set_pool("ICE")["Norritt"])

    assert program.supported
    assert [
        a.instruction.kind for a in program.activated_abilities if a.instruction
    ] == ["untap_target_permanent", "mark_non_wall_target_to_attack"]


def test_norritt_may_point_a_creature_at_an_attack_on_its_own_turn(set_pool):
    """The two cards' restrictions are different restrictions, not one clause
    written two ways: Nettling Imp is limited to an opponent's turn and Norritt
    is not, so Norritt can force the active player's creature to attack while
    that active player is its own controller."""
    from engine.activation_restrictions import ACTIVATION_RESTRICTIONS

    def _rule(sentence):
        return next(
            r for r in ACTIVATION_RESTRICTIONS if r.pattern.match(sentence)
        )

    norritt = _rule("activate only before attackers are declared")
    imp = _rule(
        "activate only during an opponent's turn, before attackers are declared"
    )

    game = Game(
        players=[PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    )
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"

    assert norritt.is_legal(game, 0, None) is True
    assert imp.is_legal(game, 0, None) is False, "its own turn"


def test_norritt_marks_the_creature_it_names(set_pool):
    """The effect end to end on the card that could not reach it."""
    norritt = Permanent(card=set_pool("ICE")["Norritt"])
    bears = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    giant = Permanent(card=set_pool("ICE")["Tor Giant"])
    for perm in (norritt, bears, giant):
        perm.metadata["summoning_sickness_turn"] = -1
    p1 = PlayerState(name="P1", battlefield=[norritt], life=20)
    p2 = PlayerState(name="P2", battlefield=[bears, giant], life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 1

    game.activate_permanent_ability(
        0, "Norritt", ability_index=1,
        target_player_index=1, target_permanent_index=1,
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert giant.metadata.get("must_attack_until_eot") is True
    assert bears.metadata.get("must_attack_until_eot") is None


# --- Round 37: the "unless" cost of an upkeep toll is payload, not a kind ---


def test_minion_of_leshrac_gives_up_a_creature_instead_of_taking_the_damage(set_pool):
    """"At the beginning of your upkeep, this creature deals 5 damage to you
    unless you sacrifice a creature other than this creature. If this creature
    deals damage to you this way, tap it."

    Mishra's War Machine prints the same sentence with 3 for 5 and a discard for
    the sacrifice, and it was a card hook keyed on its whole printed line — so
    the second card printing the template reached nothing at all.
    """
    minion = Permanent(card=set_pool("ICE")["Minion of Leshrac"])
    bear = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[minion, bear], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)

    assert p1.life == 20
    assert [p.card.name for p in p1.battlefield] == ["Minion of Leshrac"]
    assert not minion.tapped


def test_minion_of_leshrac_will_not_pay_with_itself(set_pool):
    """"…a creature **other than this creature**." Alone on the battlefield it
    has nothing to give up, so it takes the damage — the exclusion is compared
    by identity, and dropping it would let the card pay by sacrificing the one
    permanent the sentence rules out."""
    minion = Permanent(card=set_pool("ICE")["Minion of Leshrac"])
    p1 = PlayerState(name="P1", battlefield=[minion], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    game.resolve_upkeep(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert p1.life == 15
    assert minion.tapped, "the tap rides the damage branch"
    assert minion in p1.battlefield


def test_the_toll_reads_its_number_and_its_cost_off_the_card(set_pool):
    """One template, two cards, and everything that differs is payload."""
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS

    minion = next(
        t.instruction
        for t in compile_card_oracle(set_pool("ICE")["Minion of Leshrac"]).triggered_abilities
        if t.instruction
    )
    assert minion.kind == "upkeep_damage_unless_cost"
    assert minion.payload["amount"] == 5
    assert minion.payload["sacrifice"] == {"type_filter": "creature"}
    assert minion.payload["exclude_self"] is True
    assert "Mishra's War Machine" not in CARD_LINE_INSTRUCTIONS


# --- Round 39: a landwalk's name is its printed quality, so no list holds it ---
def _r39_presence(set_pool):
    presence = Permanent(card=set_pool("ICE")["Illusionary Presence"])
    p1 = PlayerState(name="P1", battlefield=[presence], mana_pool={"U": 9}, life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.active_player_index = 0
    return game, p1, presence


def test_illusionary_presence_compiles_supported(set_pool):
    """"At the beginning of your upkeep, choose a land type. This creature gains
    landwalk of the chosen type until end of turn."

    Giant Slug's sentence over the wider domain: "a **basic** land type" is
    CR 205.3i's five, "a land type" is every land subtype printed. Reading the
    wider phrase as the narrower one would offer five options where the card
    offers eighteen.
    """
    program = compile_card_oracle(set_pool("ICE")["Illusionary Presence"])

    assert program.supported, program.reason
    choice = next(
        trig.instruction
        for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "choose_one"
    )
    labels = [mode["label"] for mode in choice.payload["modes"]]
    assert "forestwalk" in labels and "locuswalk" in labels
    assert len(labels) > len({"plainswalk", "islandwalk", "swampwalk",
                              "mountainwalk", "forestwalk"})


def test_illusionary_presence_gains_the_chosen_landwalk_at_upkeep(set_pool):
    """The grant used to be refused rather than offered: `_check_grantable`
    asked `IMPLEMENTED_KEYWORDS`, which lists six "[type]walk" words, and
    CR 702.14a builds the name out of the printed quality — so thirteen of the
    eighteen options were a lowering error."""
    game, _p1, presence = _r39_presence(set_pool)

    game.resolve_upkeep(0)
    game._settle()
    game.resolve_stack()
    game._settle()

    granted = [
        keyword for keyword in ("cavewalk", "forestwalk", "islandwalk")
        if presence.has_keyword(keyword)
    ]
    assert granted, "the trigger granted the landwalk it chose"


def test_a_landwalk_grant_is_gated_by_the_landwalk_reader_not_by_a_word_list(set_pool):
    """The gate is `engine/landwalk.py` — the same reader `engine/oracle.py`
    already asks about a printed keyword *line*. A grant asking a different
    question is how one sentence works for five land types and refuses
    thirteen."""
    from engine.grammar import ast
    from engine.grammar.lower import lower_ability
    from engine.grammar.errors import LoweringError

    def _grant(keyword: str):
        return lower_ability(ast.SpellEffectLine(ast.GainKeyword(
            ast.TargetSpec("this", ast.ObjectFilter(is_source=True)),
            (keyword,),
            ast.Duration("until_end_of_turn"),
        )))

    assert _grant("locuswalk")[0].payload["keywords"] == ("locuswalk",)
    assert _grant("snow forestwalk")[0].payload["keywords"] == ("snow forestwalk",)

    # The bare family word names no land and so restricts no block: granting it
    # would put a word into layer 6 that does nothing.
    try:
        _grant("landwalk")
    except LoweringError as error:
        assert "land type" in str(error)
    else:  # pragma: no cover - the assertion is the refusal
        raise AssertionError("granting the bare family word must refuse")

    # And a word that is neither is still refused, so the arm added here did
    # not turn the gate into a pass-through.
    try:
        _grant("suspend")
    except LoweringError as error:
        assert "keyword implemented" in str(error)
    else:  # pragma: no cover - the assertion is the refusal
        raise AssertionError("an unimplemented keyword must still refuse")


# --- Round 41: a combat restriction can be conditional, and it is payload ---
def _r41_foxes(set_pool, defender_lands):
    """Arctic Foxes attacking into a 3/3, with *defender_lands* on the far
    side."""
    foxes = _nosick(Permanent(card=set_pool("ICE")["Arctic Foxes"]))
    blocker = _nosick(Permanent(card=set_pool("ICE")["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[foxes], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker, *defender_lands], life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    return game, foxes, blocker


def test_arctic_foxes_compiles_supported(set_pool):
    """"This creature can't be blocked by creatures with power 2 or greater
    **as long as defending player controls a snow land**."

    The restriction was already readable; the trailing qualifier was not, and
    the row's capture ends in `.+` — so the whole clause went into the blocker
    union, which could not read it, and the line refused. The qualifier is
    stripped once now, the way `untap_restrictions` strips "as long as this
    artifact is untapped".
    """
    from engine.combat_restrictions import combat_restriction_for

    program = compile_card_oracle(set_pool("ICE")["Arctic Foxes"])
    assert program.supported, program.reason

    restriction = combat_restriction_for(
        "this creature can't be blocked by creatures with power 2 or greater "
        "as long as defending player controls a snow land"
    )
    assert restriction.kind == "cant_be_blocked_by"
    assert restriction.payload["condition"] == {
        "who": "defending_player",
        "subject": {"type_filter": "land", "supertypes": ["snow"]},
    }


def test_arctic_foxes_evasion_is_off_without_the_snow_land(set_pool):
    """The condition is the whole point of the card: with no snow land on the
    far side the 2/2 blocks normally."""
    game, foxes, blocker = _r41_foxes(set_pool, [])
    game.declare_attackers(0, [0])

    assert game._can_block_attacker(blocker, foxes)


def test_arctic_foxes_evasion_is_on_with_a_snow_land(set_pool):
    """And with one it is not blockable by anything that big. `subject_matches`
    answers the noun phrase, so it is a *snow* land the defender needs — not
    any land, and not one of the attacker's."""
    snow = Permanent(card=set_pool("ICE")["Snow-Covered Forest"])
    game, foxes, blocker = _r41_foxes(set_pool, [snow])
    game.declare_attackers(0, [0])

    assert not game._can_block_attacker(blocker, foxes)


def test_arctic_foxes_reads_the_defenders_board_not_its_own(set_pool):
    """"Defending player controls" is the seat being attacked. A snow land on
    the *attacker's* side leaves the restriction off."""
    snow = Permanent(card=set_pool("ICE")["Snow-Covered Forest"])
    game, foxes, blocker = _r41_foxes(set_pool, [])
    game.players[0].battlefield.append(snow)
    game.declare_attackers(0, [0])

    assert game._can_block_attacker(blocker, foxes)


def test_a_condition_on_a_kind_nothing_asks_about_refuses_the_line(set_pool):
    """The qualifier is attached only to kinds whose enforcement site asks.
    Anywhere else it would be a restriction applied unconditionally — silently,
    and in the direction of doing more than the card says — so the line refuses
    and its card is unsupported naming the clause."""
    from engine.combat_restrictions import combat_restriction_for

    assert combat_restriction_for(
        "this creature can't block as long as you control a snow land"
    ) is None
    assert combat_restriction_for("this creature can't block") is not None


# --- W1G5: statics, continuous effects, control changes ---
def _w1g5_squatters_game(set_pool, catalog_by_name):
    """Orcish Squatters attacking, with a land of its **own** controller's on
    the board beside the defender's two.

    That third land is the point: "target land **defending player controls**"
    must never offer it, and the seat is a fact about the combat rather than
    about the seat choosing.
    """
    squatters = Permanent(card=set_pool("ICE")["Orcish Squatters"])
    p1 = PlayerState(name="P1", battlefield=[
        squatters, Permanent(card=catalog_by_name["Mountain"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=catalog_by_name["Forest"]),
        Permanent(card=catalog_by_name["Island"]),
    ])
    game = Game(players=[p1, p2])
    game.interactive_seats = {0}
    return game, p1, p2, squatters


def _w1g5_attack_unblocked(game):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # declare blockers
    ok, msg = game.declare_blockers(1, {})
    assert ok, msg
    game._settle()
    game.advance_combat_phase()   # blocks lock: the trigger fires here
    return game.pending_choices_of("trigger_target")


def _w1g5_finish_combat(game):
    game._settle()
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break


def test_orcish_squatters_offers_only_the_defending_players_lands(
    set_pool, catalog_by_name
):
    """The printed noun phrase is "target land defending player controls", and
    the picker is what enforces the seat — ``subject_matches`` deliberately
    refuses that key, because the seat belongs to the combat and not to the
    permanent."""
    game, _, p2, _ = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))

    assert len(pending) == 1, game.log
    offered = pending[0].data["targets"]
    assert {t["name"] for t in offered} == {"Forest", "Island"}, game.log
    assert {t["permanent_id"] for t in offered} == {
        p.permanent_id for p in p2.battlefield
    }


def test_orcish_squatters_steals_the_land_and_then_deals_no_combat_damage(
    set_pool, catalog_by_name
):
    """The whole sentence: the land changes hands, and "if you do, this creature
    assigns no combat damage this turn" is read by the damage step — so the
    defender's life is what this asserts, not a flag."""
    game, p1, p2, _ = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))
    chosen = next(t for t in pending[0].data["targets"] if t["name"] == "Forest")
    assert game.confirm_trigger_target(0, chosen["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Orcish Squatters", accept=True)
    _w1g5_finish_combat(game)

    assert "Forest" in [p.card.name for p in p1.battlefield], game.log
    assert [p.card.name for p in p2.battlefield] == ["Island"], game.log
    assert p2.life == 20, game.log


def test_orcish_squatters_gives_the_land_back_when_it_leaves(
    set_pool, catalog_by_name
):
    """"…for as long as you control this creature" (CR 611.2b). The contribution
    is keyed on the Squatters and the state-based sweep re-checks the condition,
    so the land reverts to the seat it entered under — never to whoever happened
    to hold it last."""
    game, p1, p2, squatters = _w1g5_squatters_game(set_pool, catalog_by_name)

    pending = list(_w1g5_attack_unblocked(game))
    chosen = next(t for t in pending[0].data["targets"] if t["name"] == "Forest")
    assert game.confirm_trigger_target(0, chosen["permanent_id"])
    game._settle()
    assert game.confirm_optional_pay(0, "Orcish Squatters", accept=True)
    stolen = game.permanent_by_id(chosen["permanent_id"])
    assert game.controller_index_of(stolen) == 0, game.log

    game.remove_from_battlefield(squatters)
    game.check_state_based_actions()

    assert game.controller_index_of(stolen) == 1, game.log
    assert {p.card.name for p in p2.battlefield} == {"Forest", "Island"}, game.log


def _w1g5_merieke_board(set_pool, catalog_by_name):
    merieke = Permanent(card=set_pool("ICE")["Merieke Ri Berit"])
    _nosick(merieke)
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[merieke]),
        PlayerState(name="P2", battlefield=[victim]),
    ])
    game.enforce_mana_costs = False
    return game, merieke, victim


def _w1g5_merieke_steals(game):
    result = game.activate_permanent_ability(
        0, "Merieke Ri Berit", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()


def test_merieke_ri_berit_compiles_its_own_name_as_a_self_reference(set_pool):
    """The card's oracle text names the card — printed text, not a reason to key
    on the name. The lexer collapses it to the same SELF token "this creature"
    produces, so the ability lowers to the ordinary linked steal plus the
    delayed ability the second sentence creates."""
    program = compile_card_oracle(set_pool("ICE")["Merieke Ri Berit"])

    assert program.supported
    ability = program.activated_abilities[0]
    steps = ability.instruction.payload["steps"]
    assert [i.kind for i in steps] == [
        "steal_target_linked_to_source", "create_delayed_trigger",
    ]
    assert steps[0].payload["link_conditions"] == ["you_control_source"]
    assert steps[1].payload["event"] == "bound_permanent_leaves_or_untaps"
    assert steps[1].payload["instruction"].payload["bypass_regeneration"] is True


def test_merieke_ri_berit_takes_the_creature_and_stays_tapped(
    set_pool, catalog_by_name
):
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)

    _w1g5_merieke_steals(game)

    assert game.controller_index_of(victim) == 0, game.log
    assert merieke.tapped


def test_merieke_ri_berit_destroys_the_creature_when_she_untaps(
    set_pool, catalog_by_name
):
    """"When Merieke Ri Berit … becomes untapped, destroy that creature."
    Announced from ``become_untapped``, which is the one place a permanent
    untaps — an announcement wired into the untap step alone would miss every
    Twiddle."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    _w1g5_merieke_steals(game)

    game.become_untapped(merieke)
    game._settle()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(victim), game.log
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_merieke_ri_berit_destroys_the_creature_when_she_leaves(
    set_pool, catalog_by_name
):
    """The other half of the same delayed ability. It also proves the two ends
    do not fight: the linked steal reverts control as the sweep runs, and the
    delayed destroy still finds the creature by the id it bound."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    _w1g5_merieke_steals(game)

    game.remove_from_battlefield(merieke)
    game._settle()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(victim), game.log
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]


def test_merieke_ri_berit_leaves_an_untouched_board_alone(
    set_pool, catalog_by_name
):
    """The delayed ability is armed only by the steal, and it watches Merieke by
    id. Untapping some *other* permanent must not fire it — the guard against an
    entry that answers to the first thing to untap."""
    game, merieke, victim = _w1g5_merieke_board(set_pool, catalog_by_name)
    other = Permanent(card=catalog_by_name["Mountain"], tapped=True)
    game.players[0].battlefield.append(other)
    _w1g5_merieke_steals(game)

    game.become_untapped(other)
    game._settle()
    game.check_state_based_actions()

    assert game.is_on_battlefield(victim), game.log
    assert game.controller_index_of(victim) == 0
# --- end W1G5 ---
