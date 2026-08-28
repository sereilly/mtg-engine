"""Per-card tests for The Dark's instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.targeting import derive_cast_spec
from engine.oracle import compile_card_oracle


# --- G2: auras and land statics (The Dark) ---


def _cast(game: Game, seat: int, name: str) -> None:
    game.enforce_mana_costs = False
    game.cast_from_hand(seat, name)
    game.resolve_top_of_stack()


def test_riptide_taps_only_the_blue_creatures(set_pool):
    """"Tap all blue creatures." The sweep's colour is payload the matcher
    tests through CR 613 layer 5, so it reaches every battlefield and stops at
    the colour boundary rather than at a controller one."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    mine = Permanent(card=lea["Phantom Monster"])       # blue
    theirs = Permanent(card=lea["Air Elemental"])       # blue
    red = Permanent(card=lea["Hill Giant"])             # red
    p1 = PlayerState(name="P1", hand=[pool["Riptide"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, red])
    game = Game(players=[p1, p2])

    _cast(game, 0, "Riptide")

    assert mine.tapped and theirs.tapped, game.log
    assert not red.tapped, "a red creature is not a blue creature"


def test_holy_light_shrinks_everything_that_is_not_white(set_pool):
    """"Nonwhite creatures get -1/-1 until end of turn." The exclusion is
    carried, not dropped: dropped, Holy Light would shrink the white team it is
    printed to spare. A colourless creature is nonwhite (CR 105.2c)."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    atq = set_pool("ATQ")
    white = Permanent(card=lea["Savannah Lions"])       # 2/1 white
    red = Permanent(card=lea["Hill Giant"])             # 3/3 red
    artifact = Permanent(card=atq["Ornithopter"])      # colourless artifact creature
    p1 = PlayerState(name="P1", hand=[pool["Holy Light"]], battlefield=[white])
    p2 = PlayerState(name="P2", battlefield=[red, artifact])
    game = Game(players=[p1, p2])
    colourless_before = (artifact.effective_power, artifact.effective_toughness)

    _cast(game, 0, "Holy Light")

    assert (white.effective_power, white.effective_toughness) == (2, 1)
    assert (red.effective_power, red.effective_toughness) == (2, 2), game.log
    assert (artifact.effective_power, artifact.effective_toughness) == (
        colourless_before[0] - 1, colourless_before[1] - 1
    ), "a colourless creature is nonwhite (CR 105.2c)"

# --- G1: damage family (The Dark) ---


def _brimstone(set_pool, seats: int = 2):
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [set_pool("DRK")["Fire and Brimstone"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def _offered_seats(game, card):
    spec = derive_cast_spec(card, compile_card_oracle(card))
    return sorted(
        entry["seat"] for entry in game._enumerate_targets(0, card, spec, for_cast=True)
    )


def test_fire_and_brimstone_offers_nobody_when_nobody_attacked(set_pool):
    """"target player **who attacked this turn**". A restriction nothing
    enforces is not a narrower card, it is a card that hits any seat at all —
    and the picker is what enforces it."""
    game, players = _brimstone(set_pool)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == []


def test_fire_and_brimstone_offers_the_seat_that_declared_an_attacker(set_pool):
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [1]


def test_fire_and_brimstone_may_be_aimed_at_its_own_caster(set_pool):
    """"target **player**", not "target opponent": the caster is a legal answer
    when they are the one who attacked."""
    game, players = _brimstone(set_pool)
    players[0].attacked_this_turn = True

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [0]


def test_fire_and_brimstone_burns_its_caster_too(set_pool):
    """"4 damage to target player who attacked this turn **and 4 damage to
    you**" — one sentence, two clauses, and the second is not optional."""
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    result = game.cast_from_hand(0, "Fire and Brimstone", target_player_index=1)

    assert result.supported, result.details
    assert players[1].life == 16, game.log
    assert players[0].life == 16, game.log


def test_the_attacked_record_is_on_the_seat_not_on_its_creatures(set_pool):
    """A player who attacked and then lost the attacker still attacked this
    turn. Read off the board — the record every creature carries — the seat
    would stop being a legal target the moment its attacker died."""
    game, players = _brimstone(set_pool)
    attacker = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    attacker.summoning_sick = False
    players[1].battlefield = [attacker]
    game._sync_control()
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(1, [0])
    assert ok, msg
    game.remove_from_battlefield(attacker)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [1]


def test_the_attacked_record_is_cleared_when_the_next_turn_begins(set_pool):
    """"this turn" is the turn, and the record resets with every other per-turn
    history — otherwise the card reads "who has ever attacked"."""
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    game.begin_turn_bookkeeping(1)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == []

# --- G3: upkeep and land denial (The Dark) ---


def _festival_board(set_pool):
    """Festival in seat 1's hand, with a creature of seat 0's ready to attack."""
    bears = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears]),
        PlayerState(name="P2", hand=[set_pool("DRK")["Festival"]]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, bears


def test_festival_can_only_be_cast_during_an_opponents_upkeep(set_pool):
    """"Cast this spell only during an opponent's upkeep." Both halves of the
    window are asked — the seat *and* the step — because either alone is a
    window the card does not print."""
    game, _bears = _festival_board(set_pool)

    game.current_turn_phase = "precombat_main"
    game.current_step = None
    assert not game.cast_from_hand(1, "Festival").supported

    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    assert game.cast_from_hand(1, "Festival").supported


def test_festival_grounds_every_creature_for_the_turn(set_pool):
    """"Creatures can't attack this turn."

    A blanket restriction the attack gate tests for the rest of the turn, not a
    flag stamped on the creatures that happened to be there — so a creature
    that entered afterwards cannot attack either.
    """
    game, _bears = _festival_board(set_pool)
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"

    assert game.cast_from_hand(1, "Festival").supported
    while game.stack:
        game.resolve_top_of_stack()

    latecomer = Permanent(card=set_pool("LEA")["Hill Giant"])
    game.players[0].battlefield.append(latecomer)

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    ok, _message = game.declare_attackers(0, [0])
    assert not ok
    ok, _message = game.declare_attackers(0, [1])
    assert not ok


def test_festival_stops_at_the_end_of_the_turn(set_pool):
    """"…this turn" (CR 514.2): the cleanup step ends it, beside its blocking
    twin so the two cannot disagree about when the turn is over."""
    game, _bears = _festival_board(set_pool)
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    assert game.cast_from_hand(1, "Festival").supported
    while game.stack:
        game.resolve_top_of_stack()

    game.resolve_cleanup_step(0)

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    ok, _message = game.declare_attackers(0, [0])
    assert ok


# --- H4: per-seat damage state (The Dark) ---


def test_blood_of_the_martyr_offers_its_controller_a_creature_the_damage_would_kill(
    set_pool,
):
    """"Until end of turn, if damage would be dealt to any creature, you may
    have that damage dealt to you instead."

    The record watches a *class*, so it covers a creature that entered after
    the spell resolved — and it is optional, so a non-interactive seat takes
    the stated policy: take the damage when it would otherwise be lethal and
    the taker survives it.
    """
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Blood of the Martyr"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _cast(game, 0, "Blood of the Martyr")

    # Entered *after* the spell resolved: a record hung on the creatures that
    # happened to be there would miss it.
    latecomer = Permanent(card=lea["Grizzly Bears"])  # 2/2
    p1.battlefield.append(latecomer)
    life_before = p1.life

    game._mark_damage_on_permanent(latecomer, 2, source=None)

    assert latecomer.damage_marked == 0, game.log
    assert p1.life == life_before - 2


def test_blood_of_the_martyr_leaves_damage_a_creature_survives(set_pool):
    """The other half of the same stated policy: below lethal the creature keeps
    the damage, because it heals at cleanup and the life would not come back."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])  # 2/2
    p1 = PlayerState(
        name="P1", hand=[pool["Blood of the Martyr"]], battlefield=[bears]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _cast(game, 0, "Blood of the Martyr")
    life_before = p1.life

    game._mark_damage_on_permanent(bears, 1, source=None)

    assert bears.damage_marked == 1, game.log
    assert p1.life == life_before


def test_blood_of_the_martyr_ends_with_the_turn(set_pool):
    """"Until end of turn" — the record expires through the cleanup step's one
    sweep over a player's redirects, with no lifetime of its own."""
    pool = set_pool("DRK")
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])
    p1 = PlayerState(
        name="P1", hand=[pool["Blood of the Martyr"]], battlefield=[bears]
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _cast(game, 0, "Blood of the Martyr")
    game.resolve_cleanup_step(0)
    life_before = p1.life

    game._mark_damage_on_permanent(bears, 2, source=None)

    assert bears.damage_marked == 2, game.log
    assert p1.life == life_before
