"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# --- G2: auras and land statics (The Dark) ---


def _attack_with(game: Game, seat: int, index: int) -> None:
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(seat, [index])
    assert ok, msg


def test_goblin_rock_sled_rests_for_exactly_one_of_its_controllers_untap_steps(set_pool):
    """"…doesn't untap during your untap step if it attacked during your last
    turn." The condition is re-asked every untap step off the permanent's own
    attack record — the loose substring reading of the phrase would have frozen
    the Sled for the rest of the game."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    # "…can't attack unless defending player controls a Mountain" is the Sled's
    # other printed restriction, so the defender needs one for this test to be
    # about the untap step at all.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]),
        PlayerState(name="P2", battlefield=[Permanent(card=set_pool("LEA")["Mountain"])]),
    ])
    game.start_turn(0)
    _attack_with(game, 0, 0)
    assert sled.tapped, "attacking taps it (CR 508.1f)"

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: it attacked during P1's last turn
    assert sled.tapped, game.log

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: last turn it sat out, so it untaps
    assert not sled.tapped, game.log


def test_a_goblin_rock_sled_that_never_attacked_untaps_normally(set_pool):
    """The other direction of the same condition. Without it the phrase alone
    would keep any tapped Sled tapped forever."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]), PlayerState(name="P2"),
    ])
    game.become_tapped(sled)
    game.start_turn(0)

    assert not sled.tapped, game.log


def test_goblin_rock_sled_cannot_attack_without_a_defending_mountain(set_pool):
    """The card's other printed restriction, on the same compiled program."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    p1 = PlayerState(name="P1", battlefield=[sled])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert not game.can_attack(sled, 1)
    p2.battlefield.append(mountain)
    game._sync_control()
    assert game.can_attack(sled, 1)


def test_goblins_of_the_flarg_is_sacrificed_the_moment_a_dwarf_arrives(set_pool):
    """"When you control a Dwarf, sacrifice this creature." A state trigger
    (CR 603.8), so it fires alongside the state-based actions rather than
    waiting for the next upkeep — the Goblin never gets to attack beside the
    Dwarf it is printed to lose to."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.check_state_based_actions()
    assert goblin in p1.battlefield, "no Dwarf, no sacrifice"

    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1.battlefield.append(dwarf)
    game._sync_control()
    game.check_state_based_actions()

    assert goblin not in p1.battlefield, game.log
    assert [c.name for c in p1.graveyard] == ["Goblins of the Flarg"]


def test_an_opponents_dwarf_does_not_sacrifice_goblins_of_the_flarg(set_pool):
    """"**You** control a Dwarf" is a seat, and the seat is the Goblin's
    controller — an ignored controller narrowing would sacrifice the card off
    somebody else's board."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    p2 = PlayerState(name="P2", battlefield=[dwarf])
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert goblin in p1.battlefield, game.log

# --- G1: damage family (The Dark) ---


def _board(set_pool, name: str, *, seats: int = 2) -> tuple[Game, list[PlayerState], Permanent]:
    """*name* on seat 0's battlefield, summoning sickness already worked off."""
    perm = Permanent(card=set_pool("DRK")[name])
    perm.summoning_sick = False
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].battlefield = [perm]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players, perm


def test_banshee_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("DRK")["Banshee"])
    assert program.supported, program.unsupported_reason


def test_banshee_rounds_the_two_halves_in_opposite_directions(set_pool):
    """"half X damage, rounded down, to any target, and half X damage, rounded
    up, to you" — one sentence, two roundings. With X = 5 that is 2 and 3, and
    a reader that honoured one rounding for both would deal 2/2 or 3/3."""
    game, players, banshee = _board(set_pool, "Banshee")

    result = game.activate_permanent_ability(
        0, "Banshee", target_player_index=1, x_value=5
    )

    assert result.supported, result.details
    assert players[1].life == 18, game.log
    assert players[0].life == 17, game.log


def test_banshee_with_an_odd_x_of_one_hits_only_its_controller(set_pool):
    """X = 1: half rounded down is 0, and CR 120.8 makes a source that would
    deal 0 damage deal none at all. Half rounded up is still 1."""
    game, players, banshee = _board(set_pool, "Banshee")

    game.activate_permanent_ability(0, "Banshee", target_player_index=1, x_value=1)

    assert players[1].life == 20, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_pumps_and_bites_its_controller_in_one_ability(set_pool):
    """"gets +2/+0 until end of turn **and deals 1 damage to you**" is one
    printed ability. Read as a pump alone the card is strictly better than it
    prints, and the whole line refused to parse before the conjunct existed."""
    game, players, eel = _board(set_pool, "Electric Eel")

    result = game.activate_permanent_ability(0, "Electric Eel")

    assert result.supported, result.details
    assert eel.effective_power == 3, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_bites_its_controller_when_it_enters(set_pool):
    """The other half of the card, and the one that already worked — kept here
    so a change to the activated line cannot quietly take the trigger with it."""
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].hand = [set_pool("DRK")["Electric Eel"]]
    game = Game(players=players)
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Electric Eel")
    game._settle()

    assert players[0].life == 19, game.log


def test_the_fallen_damages_nobody_before_it_has_damaged_anybody(set_pool):
    """"each opponent … **it has dealt damage to this game**" is a history, not
    a board. With an empty record the upkeep trigger hits nothing; a reading
    that dropped the clause would be a Pestilence."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game.start_turn(0)
    game._settle()

    assert players[1].life == 20, game.log


def test_the_fallen_remembers_the_opponent_it_damaged(set_pool):
    """One point of damage from this creature puts that seat in its record, and
    every later upkeep collects on it."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 3, source=fallen)
    assert players[1].life == 17

    game.start_turn(0)
    game._settle()

    assert players[1].life == 16, game.log


def test_the_fallen_forgets_what_a_previous_object_damaged(set_pool):
    """CR 400.7: a creature that leaves and returns is a new object. The record
    lives on the permanent, so the new one remembers nothing — which is what
    keeps "this game" from meaning "this game, plus a previous incarnation"."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 1, source=fallen)
    game.remove_from_battlefield(fallen)

    returned = Permanent(card=set_pool("DRK")["The Fallen"])
    returned.summoning_sick = False
    players[0].battlefield = [returned]
    game._sync_control()
    life_before = players[1].life

    game.start_turn(0)
    game._settle()

    assert players[1].life == life_before, game.log


def test_the_fallen_never_damages_its_own_controller(set_pool):
    """"each **opponent**": a seat recorded because this creature damaged its
    own controller is not one, and the record holds seats rather than
    opponents so the question is asked when the trigger resolves."""
    game, players, fallen = _board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[0], 1, source=fallen)
    life_before = players[0].life

    game.start_turn(0)
    game._settle()

    assert players[0].life == life_before, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _leviathan_board(set_pool, island_count: int = 2):
    """Leviathan untapped on the battlefield with *island_count* Islands."""
    lea = set_pool("LEA")
    leviathan = Permanent(card=set_pool("DRK")["Leviathan"])
    islands = [Permanent(card=lea["Island"]) for _ in range(island_count)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[leviathan, *islands]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    return game, leviathan


def test_leviathan_enters_tapped_and_stays_tapped(set_pool):
    """"This creature enters tapped and doesn't untap during your untap step."

    One printed line making two claims. The entry half was already applied
    (`enter_effects.ENTERS_TAPPED` is a substring probe); the untap half was
    **not** — `self_untap_line` is anchored on the whole line and had no row
    for this spelling, so Leviathan entered tapped and then untapped every
    turn with nothing failing.
    """
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("DRK")["Leviathan"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Leviathan").supported
    leviathan = next(p for p in game.all_permanents() if p.card.name == "Leviathan")
    assert leviathan.tapped

    game.resolve_untap_step(0)
    assert leviathan.tapped


def test_leviathan_untaps_when_two_islands_are_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice two Islands. If you
    do, untap this creature." This line produced no instruction at all."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)
    game.become_tapped(leviathan)
    game.current_turn_phase = "beginning"

    game.resolve_upkeep(0)
    while game.stack:
        game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, card_name="Leviathan", accept=True)

    assert not leviathan.tapped
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_cannot_attack_without_two_islands_to_sacrifice(set_pool):
    """"This creature can't attack unless you sacrifice two Islands. (This cost
    is paid as attackers are declared.)" CR 508.1g — a cost, not a target.

    With one Island the cost is unpayable, so the declaration is illegal. The
    Island stays: a refused declaration charges nothing.
    """
    game, _leviathan = _leviathan_board(set_pool, island_count=1)

    ok, _message = game.declare_attackers(0, [0])

    assert not ok
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_pays_two_islands_as_attackers_are_declared(set_pool):
    """The other half: with the cost payable the attack happens **and** the
    Islands are gone. A restriction nothing charges is a card that attacks for
    free, which is the direction a missing enforcement always fails in."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)

    ok, _message = game.declare_attackers(0, [0])

    assert ok
    assert leviathan.attacking
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Island", "Island"]
