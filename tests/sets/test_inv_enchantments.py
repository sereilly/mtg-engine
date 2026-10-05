"""Invasion enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.control import change_control as _w1g3_change_control
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_table(set_pool, mine=(), theirs=()):
    """A duel with each seat's permanents named in board order, seat 0 active.
    Lands and bodies come from Alpha; the Invasion cards are looked up first."""
    w1g3_inv, w1g3_lea = set_pool("INV"), set_pool("LEA")
    w1g3_game = _W1G3Game(
        players=[_W1G3PlayerState(name="W1G3-A"), _W1G3PlayerState(name="W1G3-B")]
    )
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    w1g3_rows = []
    for w1g3_seat, w1g3_names in enumerate((mine, theirs)):
        w1g3_row = []
        for w1g3_name in w1g3_names:
            w1g3_source = w1g3_inv if w1g3_name in w1g3_inv else w1g3_lea
            w1g3_perm = _W1G3Permanent(card=w1g3_source[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
            w1g3_row.append(w1g3_perm)
        w1g3_rows.append(w1g3_row)
    return w1g3_game, w1g3_rows[0], w1g3_rows[1]  # _w1g3_table (enchantments)


def _w1g3_enchant(game, set_pool, aura_name, host):
    """Cast *aura_name* from seat 0's hand onto *host* through the real cast
    path, and return the Aura permanent."""
    game.players[0].hand.append(set_pool("INV")[aura_name])
    w1g3_seat = game.controller_index_of(host)
    w1g3_slot = [
        perm.permanent_id for perm in game.controlled_by(w1g3_seat)
    ].index(host.permanent_id)
    w1g3_cast = game.cast_from_hand(
        0, aura_name, target_player_index=w1g3_seat, target_permanent_index=w1g3_slot,
    )
    assert w1g3_cast.supported, w1g3_cast.details
    _w1g3_resolve(game)
    return next(  # _w1g3_enchant
        (perm for perm in game.controlled_by(0) if perm.card.name == aura_name), None
    )


def _w1g3_upkeep(game, seat):
    game.start_turn(seat)
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g3_resolve(game)  # _w1g3_upkeep


def test_w1g3_strength_of_unity_counts_the_auras_controllers_lands(set_pool):
    """"Enchanted creature gets +1/+1 for each basic land type among lands
    **you** control" — "you" is the Aura's controller (CR 109.5), so a creature
    that changes sides keeps the bonus its enchanter's lands give it."""
    game, mine, theirs = _w1g3_table(
        set_pool,
        mine=["Grizzly Bears", "Plains", "Island", "Swamp"],
        theirs=["Mountain"],
    )
    bears = mine[0]
    aura = _w1g3_enchant(game, set_pool, "Strength of Unity", bears)
    assert aura is not None
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    _w1g3_change_control(bears, 1, source="w1g3-test")
    game._settle()
    assert game.controller_index_of(bears) == 1
    assert (bears.effective_power, bears.effective_toughness) == (5, 5), (
        "the count is the Aura controller's three types, not the new "
        "controller's one"
    )


def test_w1g3_strength_of_unity_follows_the_board(set_pool):
    game, mine, _theirs = _w1g3_table(set_pool, mine=["Grizzly Bears", "Tropical Island"])
    bears = mine[0]
    _w1g3_enchant(game, set_pool, "Strength of Unity", bears)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)

    game.remove_from_battlefield(mine[1])
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g3_exotic_curse_shrinks_by_the_enchanters_domain(set_pool):
    """"Enchanted creature gets -1/-1 for each basic land type among lands you
    control." On an opponent's creature the count is still the caster's: two
    types take a 6/4 to 4/2 while the opponent's five types take nothing."""
    game, _mine, theirs = _w1g3_table(
        set_pool,
        mine=["Swamp", "Swamp", "Island"],
        theirs=["Craw Wurm", "Plains", "Island", "Swamp", "Mountain", "Forest"],
    )
    wurm = theirs[0]
    _w1g3_enchant(game, set_pool, "Exotic Curse", wurm)
    assert (wurm.effective_power, wurm.effective_toughness) == (4, 2)


def test_w1g3_exotic_curse_kills_when_the_domain_grows(set_pool):
    """The penalty is recomputed, not locked in: a new basic land type on the
    enchanter's side takes the creature's toughness to 0 and it dies as a
    state-based action (CR 704.5f)."""
    game, _mine, theirs = _w1g3_table(
        set_pool, mine=["Swamp", "Island", "Plains"], theirs=["Craw Wurm"],
    )
    wurm = theirs[0]
    _w1g3_enchant(game, set_pool, "Exotic Curse", wurm)
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)

    mountain = _W1G3Permanent(card=set_pool("LEA")["Mountain"])
    game._put_permanent_onto_battlefield(0, mountain, None)
    game._settle()
    assert not game.is_on_battlefield(wurm)
    assert [card.name for card in game.players[1].graveyard] == ["Craw Wurm"]
    assert "Exotic Curse" in [card.name for card in game.players[0].graveyard]


def test_w1g3_collapsing_borders_pays_each_player_by_their_own_lands(set_pool):
    """"At the beginning of each player's upkeep, that player gains 1 life for
    each basic land type among lands **they** control. Then this enchantment
    deals 3 damage to that player." The seat counted is the upkeep's, not the
    enchantment controller's: five types nets +2, one type nets -2."""
    game, _mine, _theirs = _w1g3_table(
        set_pool,
        mine=["Collapsing Borders", "Plains", "Island", "Swamp", "Mountain", "Forest"],
        theirs=["Mountain", "Mountain"],
    )
    _w1g3_upkeep(game, 1)
    assert [player.life for player in game.players] == [20, 18]
    assert "W1G3-B gained 1 life from Collapsing Borders (20 -> 21)" in game.log

    _w1g3_upkeep(game, 0)
    assert [player.life for player in game.players] == [22, 18]


def test_w1g3_collapsing_borders_with_no_basic_types_is_three_damage(set_pool):
    game, _mine, _theirs = _w1g3_table(set_pool, mine=["Collapsing Borders"])
    _w1g3_upkeep(game, 1)
    assert [player.life for player in game.players] == [20, 17]


def _w1g3_restrained_attack(set_pool, attacker_lands, defender_lands, attackers=2):
    """Seat 1 controls Collective Restraint; seat 0 is in its declare-attackers
    step with *attackers* Grizzly Bears and real mana to pay with."""
    game, mine, theirs = _w1g3_table(
        set_pool,
        mine=["Grizzly Bears"] * attackers + list(attacker_lands),
        theirs=["Collective Restraint", *defender_lands],
    )
    game.enforce_mana_costs = True
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    return game, mine, theirs  # _w1g3_restrained_attack


def test_w1g3_collective_restraint_charges_the_defenders_domain_per_attacker(set_pool):
    """"Creatures can't attack you unless their controller pays {X} for each
    creature they control that's attacking you, where X is the number of basic
    land types among lands you control." Three types make each attacker cost
    {3}: five Mountains cannot send two, and sending one taps three."""
    game, mine, _theirs = _w1g3_restrained_attack(
        set_pool, ["Mountain"] * 5, ["Plains", "Island", "Tropical Island"],
    )
    ok, why = game.declare_attackers(0, [0, 1])
    assert not ok and "{6}" in why
    assert not any(perm.tapped for perm in mine), "a refused declaration taps nothing"

    ok, why = game.declare_attackers(0, [0])
    assert ok, why
    assert sum(perm.tapped for perm in mine if perm.has_type("land")) == 3
    assert "W1G3-A paid {3} to declare attackers" in game.log


def test_w1g3_collective_restraint_price_follows_the_defenders_board(set_pool):
    """The X is counted when attackers are declared, off the *defending*
    controller's lands: a second type arriving raises the price, and the
    attacker's own five types never enter into it."""
    game, mine, theirs = _w1g3_restrained_attack(
        set_pool, ["Plains", "Island", "Swamp", "Mountain", "Forest"], ["Forest"],
    )
    bears = mine[0]
    assert game._attack_mana_costs_of(bears, 1) == [{"generic": 1}]

    island = _W1G3Permanent(card=set_pool("LEA")["Island"])
    game._put_permanent_onto_battlefield(1, island, None)
    assert game._attack_mana_costs_of(bears, 1) == [{"generic": 2}]

    ok, why = game.declare_attackers(0, [0, 1])
    assert ok, why
    assert sum(perm.tapped for perm in mine if perm.has_type("land")) == 4


def test_w1g3_collective_restraint_with_no_domain_stops_nothing(set_pool):
    """Zero basic land types is {0} for each attacker: no cost, no payment."""
    game, mine, _theirs = _w1g3_restrained_attack(set_pool, [], [])
    assert game._attack_mana_costs_of(mine[0], 1) == []
    ok, why = game.declare_attackers(0, [0, 1])
    assert ok, why
