"""Per-card tests for Homelands' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G5: upkeep, counters and forced sacrifice ---

from engine import Game, PlayerState, load_cards
from engine.auras import attach_aura
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.named_counters import counters_on


def _w1g5_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


# -- Koskun Falls -----------------------------------------------------------


def _w1g5_falls(set_pool, *, creatures: int = 1):
    falls = Permanent(card=set_pool("HML")["Koskun Falls"])
    board = [falls]
    for _ in range(creatures):
        bear = Permanent(card=_w1g5_lea()["Grizzly Bears"])
        bear.metadata["summoning_sickness_turn"] = -99
        board.append(bear)
    p1 = PlayerState(name="P1", battlefield=board)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, falls, p1


def test_koskun_falls_taps_a_creature_to_stay_on_the_battlefield(set_pool):
    """"At the beginning of your upkeep, sacrifice this enchantment unless you
    tap an untapped creature you control."

    The alternative is a *deed*, not a payment, so it is decomposed into the
    offer machinery rather than fused: the tap is chosen and performed, and the
    enchantment stays.
    """
    game, falls, p1 = _w1g5_falls(set_pool, creatures=1)
    bear = p1.battlefield[1]
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert any(perm is falls for perm in p1.battlefield)
    assert bear.tapped


def test_koskun_falls_is_sacrificed_with_nothing_to_tap(set_pool):
    """No untapped creature is an offer that cannot be taken, so the printed
    consequence applies -- which is the half a "free offer" reading would drop.
    """
    game, falls, p1 = _w1g5_falls(set_pool, creatures=0)
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert not any(perm is falls for perm in p1.battlefield)


def _w1g5_attack_rig(set_pool, *, lands: int, attackers: int, falls: bool = True):
    lea = _w1g5_lea()
    board = []
    for _ in range(attackers):
        bear = Permanent(card=lea["Grizzly Bears"])
        bear.metadata["summoning_sickness_turn"] = -99
        board.append(bear)
    board += [Permanent(card=lea["Forest"]) for _ in range(lands)]
    p1 = PlayerState(name="P1", battlefield=board)
    defender_board = (
        [Permanent(card=set_pool("HML")["Koskun Falls"])] if falls else []
    )
    p2 = PlayerState(name="P2", battlefield=defender_board)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    return game, p1


def test_koskun_falls_charges_two_generic_for_each_attacker(set_pool):
    """"Creatures can't attack you unless their controller pays {2} for each
    creature they control that's attacking you." (CR 508.1g.)

    The multiplication is the declaration's own sum, not a number in the
    payload: two attackers owe {4} together, and three lands cannot pay it.
    """
    game, p1 = _w1g5_attack_rig(set_pool, lands=4, attackers=2)
    ok, _ = game.declare_attackers(0, [0, 1])
    assert ok
    assert sum(1 for p in p1.battlefield if p.card.name == "Forest" and p.tapped) == 4

    game, p1 = _w1g5_attack_rig(set_pool, lands=3, attackers=2)
    ok, message = game.declare_attackers(0, [0, 1])
    assert not ok
    assert "{4}" in message
    # Refused with nothing spent: the plan is made before anything is tapped.
    assert not any(p.tapped for p in p1.battlefield if p.card.name == "Forest")


def test_koskun_falls_leaves_an_unwatched_attack_alone(set_pool):
    """The toll is the *defending* player's permanent, so a seat with no Koskun
    Falls charges nothing -- the control the enchantment's own row exists for.
    """
    game, p1 = _w1g5_attack_rig(set_pool, lands=0, attackers=1, falls=False)
    ok, message = game.declare_attackers(0, [0])
    assert ok, message


# -- Orcish Mine ------------------------------------------------------------


def _w1g5_mine(set_pool):
    land = Permanent(card=_w1g5_lea()["Mountain"])
    mine = Permanent(card=set_pool("HML")["Orcish Mine"])
    p1 = PlayerState(name="P1", battlefield=[])
    p2 = PlayerState(name="P2", battlefield=[land])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._put_permanent_onto_battlefield(0, mine, None)
    attach_aura(mine, land)
    game._settle()
    return game, mine, land, p1, p2


def test_orcish_mine_enters_with_three_ore_counters(set_pool):
    game, mine, land, p1, p2 = _w1g5_mine(set_pool)
    assert counters_on(mine, "ore") == 3


def test_orcish_mine_loses_a_counter_when_the_enchanted_land_is_tapped(set_pool):
    """"At the beginning of your upkeep **and** whenever enchanted land becomes
    tapped, remove an ore counter from this Aura."

    One printed ability with two trigger events (CR 603.1), and the second is
    the half a table holding only the upkeep condition would have dropped
    silently -- the card would have compiled supported and ticked once a turn.
    """
    game, mine, land, p1, p2 = _w1g5_mine(set_pool)
    game.become_tapped(land)
    game._settle()
    assert counters_on(mine, "ore") == 2


def test_orcish_mine_loses_a_counter_on_its_controllers_upkeep(set_pool):
    """The other half of the same ability."""
    game, mine, land, p1, p2 = _w1g5_mine(set_pool)
    game.start_turn(1)
    game._settle()
    game.start_turn(0)
    game._settle()
    assert counters_on(mine, "ore") == 2


def test_orcish_mine_destroys_the_land_and_burns_its_controller(set_pool):
    """"When the last ore counter is removed from this Aura, destroy enchanted
    land and this Aura deals 2 damage to that land's controller."

    The damage goes to the **land's** controller, not the Aura's -- they are
    different seats on every printing of this card that matters, and by the
    time the damage step runs the land is a card in a graveyard with no
    controller left to ask (CR 608.2h).
    """
    game, mine, land, p1, p2 = _w1g5_mine(set_pool)
    for _ in range(3):
        game.become_untapped(land)
        game.become_tapped(land)
        game._settle()

    assert counters_on(mine, "ore") == 0
    assert not any(perm is land for perm in p2.battlefield)
    assert p2.life == 18
    assert p1.life == 20


# -- Funeral March ----------------------------------------------------------


def test_funeral_march_makes_the_hosts_controller_sacrifice(set_pool):
    """"When enchanted creature leaves the battlefield, its controller
    sacrifices a creature of their choice."

    CR 603.6c's event about the permanent the Aura is attached to, and the seat
    is frozen at the fire site: by resolution the host is in a graveyard, which
    CR 400.7 makes a different object with no controller.
    """
    lea = _w1g5_lea()
    host = Permanent(card=lea["Grizzly Bears"])
    spare = Permanent(card=lea["Hurloon Minotaur"])
    march = Permanent(card=set_pool("HML")["Funeral March"])
    p1 = PlayerState(name="P1", battlefield=[march])
    p2 = PlayerState(name="P2", battlefield=[host, spare])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    attach_aura(march, host)
    game._settle()

    game.remove_from_battlefield(host)
    p2.graveyard.append(host.card)
    game._settle()

    # The host's controller gave up their other creature -- not the Aura's.
    assert not any(perm is spare for perm in p2.battlefield)
    assert p1.battlefield == []
