"""Judgment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Lost in Thought: "Enchanted creature can't attack or block, and its
# activated abilities can't be activated. Its controller may exile three cards
# from their graveyard for that player to ignore this effect until end of
# turn." CR 116.2d's special action — Volrath's Curse's offer at a graveyard
# price ("You can take the 'exile three cards' action any time you have
# priority without using the stack", ruling 2004-10-04).

import pytest as _w1g5_pytest  # noqa: E402

from engine.special_actions import (  # noqa: E402
    available_permanent_special_actions as _w1g5_offers,
    permanent_special_action_refusal as _w1g5_refusal,
    take_permanent_special_action as _w1g5_take,
)
from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402

_W1G5_IGNORE = "ignore_attached_static_until_eot"


def _w1g5_lost(set_pool, graveyard=4, host="Prodigal Sorcerer"):
    """Seat 0's Lost in Thought on seat 1's *host*; seat 1 holds *graveyard*
    cards, the first of them a Grizzly Bears and the rest Forests."""
    game = _w1g5.table(set_pool, hands=(["Lost in Thought"], []))
    game.start_turn(0)
    creature = _w1g5.put(game, set_pool, 1, host)
    pile = [_w1g5.card(set_pool, "Grizzly Bears")] + [
        _w1g5.card(set_pool, "Forest")
    ] * (graveyard - 1)
    game.players[1].graveyard.extend(pile[:graveyard])
    cast = game.cast_from_hand(0, "Lost in Thought", target_permanent_ids=[creature.permanent_id])
    assert cast.supported, cast.details
    _w1g5.settle(game)
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Lost in Thought")
    return game, aura, creature


def test_w1g5_lost_in_thought_shuts_its_creature_down(set_pool):
    game, _aura, sorcerer = _w1g5_lost(set_pool)

    assert not game.can_attack(sorcerer, 0)
    pinged = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    assert not pinged.supported
    assert game.players[0].life == 20


def test_w1g5_lost_in_thought_offers_its_hosts_controller_the_three_card_exile(set_pool):
    game, aura, sorcerer = _w1g5_lost(set_pool)
    game.priority_player_index = 1

    assert _w1g5_offers(game, 1) == [{
        "permanent_id": aura.permanent_id, "name": "Lost in Thought",
        "kind": _W1G5_IGNORE, "exile_from_graveyard": 3,
    }]
    game.priority_player_index = 0
    assert _w1g5_offers(game, 0) == [], "the Aura's controller is offered nothing"


def test_w1g5_lost_in_thought_ignored_for_the_turn_exiles_the_three_named(set_pool):
    """The taker names the three; the creature is free until the cleanup step
    (CR 514.2), and then it is held again."""
    game, aura, sorcerer = _w1g5_lost(set_pool)
    game.priority_player_index = 1

    assert _w1g5_take(game, 1, aura, _W1G5_IGNORE, exiled_slots=[1, 2, 3]) is None

    assert _w1g5.pile(game, 1) == ["Grizzly Bears"], "the unnamed card stays"
    assert _w1g5.pile(game, 1, "exile") == ["Forest"] * 3
    assert game.can_attack(sorcerer, 0)
    pinged = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    assert pinged.supported, pinged.details
    _w1g5.settle(game)
    assert game.players[0].life == 19
    assert _w1g5_offers(game, 1) == [], "one turn's relief, bought once"

    game.resolve_cleanup_step(1)
    assert not game.can_attack(sorcerer, 0)


def test_w1g5_lost_in_thought_cannot_be_ignored_with_two_cards(set_pool):
    game, aura, sorcerer = _w1g5_lost(set_pool, graveyard=2)
    game.priority_player_index = 1

    assert _w1g5_offers(game, 1) == []
    assert "fewer than 3" in _w1g5_refusal(game, 1, aura, _W1G5_IGNORE)
    assert _w1g5_take(game, 1, aura, _W1G5_IGNORE) is not None
    assert len(game.players[1].graveyard) == 2 and not game.can_attack(sorcerer, 0)


def test_w1g5_lost_in_thought_holds_the_taker_to_three_cards_of_their_naming(set_pool):
    game, aura, sorcerer = _w1g5_lost(set_pool)
    game.priority_player_index = 1

    for named in ([0, 1], [0, 1, 1], [0, 1, 9]):
        assert _w1g5_take(game, 1, aura, _W1G5_IGNORE, exiled_slots=named) is not None
    assert len(game.players[1].graveyard) == 4 and game.players[1].exile == []
    assert not game.can_attack(sorcerer, 0)


def test_w1g5_lost_in_thought_named_by_nobody_pays_the_least_valuable_three(set_pool):
    """A seat that names no cards gives up the stated order's three
    (``graveyard_price_order``): the Forests, cheapest first, before the
    Bears."""
    game, aura, _sorcerer = _w1g5_lost(set_pool)
    game.priority_player_index = 1

    assert _w1g5_take(game, 1, aura, _W1G5_IGNORE) is None
    assert _w1g5.pile(game, 1) == ["Grizzly Bears"]


def test_w1g5_lost_in_thought_needs_priority(set_pool):
    game, aura, _sorcerer = _w1g5_lost(set_pool)
    game.priority_player_index = 0

    assert "does not have priority" in _w1g5_refusal(game, 1, aura, _W1G5_IGNORE)


# --- Web of Inertia ----------------------------------------------------------
# "At the beginning of combat on each opponent's turn, that player may exile a
# card from their graveyard. If the player doesn't, creatures they control
# can't attack you this turn." An offer to the seat whose combat it is
# (``event_subject_player``), performed out of their own graveyard, and a
# turn-scoped can't-attack entry scoped to that seat's creatures and to attacks
# on the Web's controller alone.

def _w1g5_web(set_pool, *, graveyard=2, seats=2, interactive=(0, 1)):
    """Seat 0's Web of Inertia at the beginning of seat 1's combat, the
    trigger on the stack; seat 1 holds a Hill Giant and *graveyard* Forests."""
    game = _w1g5.table(set_pool, hands=[[] for _ in range(seats)], interactive=interactive)
    game.players[1].graveyard.extend([_w1g5.card(set_pool, "Forest")] * graveyard)
    _w1g5.put(game, set_pool, 0, "Web of Inertia")
    _w1g5.put(game, set_pool, 0, "Grizzly Bears")
    giant = _w1g5.put(game, set_pool, 1, "Hill Giant")
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_step == "beginning_of_combat"
    assert [item.card.name for item in game.stack] == ["Web of Inertia"]
    return game, giant


def _w1g5_attackers(game, seat):
    return sorted(
        list(game.controlled_by(seat))[index].card.name
        for index in game.legal_attacker_indices(seat)
    )


def test_w1g5_web_of_inertia_declined_keeps_that_players_creatures_home(set_pool):
    game, giant = _w1g5_web(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == [1], "the seat whose combat it is is asked"
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5.settle(game)
    game.advance_combat_phase()

    assert game.current_step == "declare_attackers"
    assert _w1g5_attackers(game, 1) == []
    assert len(game.players[1].graveyard) == 2

    # CR 514.2: "this turn" ends at cleanup.
    game.resolve_cleanup_step(1)
    assert game.can_attack(giant, 0)


def test_w1g5_web_of_inertia_taken_exiles_one_of_their_own_cards(set_pool):
    """The pick is out of the *offered* seat's graveyard, made by that seat;
    the Web's controller's graveyard is not touched."""
    game, giant = _w1g5_web(set_pool)
    game.players[0].graveyard.append(_w1g5.card(set_pool, "Island"))
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.confirm_optional_pay(1, accept=True)
    assert _w1g5.owed(game, "graveyard_exile_pick") == [1]
    _w1g5.settle(game)
    game.advance_combat_phase()

    assert _w1g5.pile(game, 1, "exile") == ["Forest"] and len(game.players[1].graveyard) == 1
    assert _w1g5.pile(game, 0) == ["Island"]
    assert _w1g5_attackers(game, 1) == ["Hill Giant"]


def test_w1g5_web_of_inertia_with_an_empty_graveyard_cannot_be_bought_off(set_pool):
    """CR 608.2d: an option that is impossible is not offered — with nothing
    to exile, the restriction simply applies."""
    game, giant = _w1g5_web(set_pool, graveyard=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g5.owed(game) == []
    _w1g5.settle(game)
    assert not game.can_attack(giant, 0)


def test_w1g5_web_of_inertia_is_silent_on_its_controllers_own_turn(set_pool):
    game = _w1g5.table(set_pool, hands=([], []))
    _w1g5.put(game, set_pool, 0, "Web of Inertia")
    _w1g5.put(game, set_pool, 0, "Grizzly Bears")
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()

    assert game.stack == [] and game.attack_restrictions_until_eot == []


def test_w1g5_web_of_inertia_forbids_attacking_you_and_nobody_else(set_pool):
    """"Can't attack **you**": at a three-seat table the held-back creatures
    may still attack the other opponent, and a planeswalker the Web's
    controller controls (ruling 2014-02-01: "a creature that can't attack you
    can still attack a planeswalker you control")."""
    game, giant = _w1g5_web(set_pool, seats=3)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5.settle(game)

    assert not game.can_attack(giant, 0)
    assert game.can_attack(giant, 2)
    assert game.can_attack(giant, 0, attacking_planeswalker=True)


@_w1g5_pytest.mark.parametrize("could_attack", [True, False])
def test_w1g5_a_seat_nobody_asks_keeps_its_graveyard_when_nothing_could_attack(
    set_pool, could_attack
):
    """The standing policy paid this toll every combat — a card out of the
    graveyard (threshold's pile, in this block) to lift a restriction on an
    attack the seat could not have made. With nothing able to attack, the
    restriction takes nothing and the offer is refused; with an attacker,
    the price is still paid."""
    game, giant = _w1g5_web(set_pool, interactive=())
    if not could_attack:
        giant.tapped = True
    _w1g5.settle(game)

    assert len(game.players[1].graveyard) == (1 if could_attack else 2)
    assert bool(game.attack_restrictions_until_eot) is (not could_attack)


def test_w1g5_web_of_inertia_restricts_that_players_creatures_only(set_pool):
    """The entry is scoped to the seat the event froze: the Web's own
    controller's creatures are not "creatures they control"."""
    game, giant = _w1g5_web(set_pool, seats=3)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g5.settle(game)
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")

    assert game.can_attack(bears, 1)
    assert [entry.get("controller_seat") for entry in game.attack_restrictions_until_eot] == [1]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
#
# Drive-list cards (supported on arrival), each given a game: what they count
# is counted on the right board and at the right moment.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_table(set_pool, catalog_by_name):
    jud = set_pool("JUD")
    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P0", library=[island] * 10),
        _W1G7PlayerState(name="P1", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g7_card = lambda name: jud[name] if name in jud else catalog_by_name[name]
    return game


def _w1g7_put(game, seat, name):
    permanent = _W1G7Permanent(card=game._w1g7_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve(game)
    _w1g7_nosick(permanent)
    return permanent


def _w1g7_bolt(game, seat, victim):
    game.players[seat].hand.append(game._w1g7_card("Lightning Bolt"))
    assert game.cast_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    ).supported
    _w1g7_resolve(game)


def test_w1g7_soulcatchers_aerie_counts_only_its_controllers_birds(
    set_pool, catalog_by_name,
):
    """"Whenever a Bird is put into **your** graveyard from the battlefield":
    the controller's Suntail Hawk dying adds a feather counter, and every Bird
    on the table — the opponent's too, "Bird creatures get" names no
    controller — grows by one. The opponent's Hawk dying adds nothing."""
    game = _w1g7_table(set_pool, catalog_by_name)
    aerie = _w1g7_put(game, 0, "Soulcatchers' Aerie")
    doomed, mine = _w1g7_put(game, 0, "Suntail Hawk"), _w1g7_put(game, 0, "Suntail Hawk")
    theirs = _w1g7_put(game, 1, "Suntail Hawk")
    _w1g7_bolt(game, 1, doomed)

    assert aerie.metadata.get("feather_counters") == 1
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    _w1g7_bolt(game, 0, theirs)
    assert aerie.metadata.get("feather_counters") == 1
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


def test_w1g7_epic_struggle_wins_at_its_controllers_upkeep_with_twenty_creatures(
    set_pool, catalog_by_name,
):
    """Nineteen creatures at the upkeep win nothing; the twentieth does, at the
    next upkeep of the enchantment's controller."""
    game = _w1g7_table(set_pool, catalog_by_name)
    _w1g7_put(game, 0, "Epic Struggle")
    for _ in range(19):
        _w1g7_put(game, 0, "Grizzly Bears")
    game.start_turn(0)
    _w1g7_resolve(game)
    assert not any(player.lost for player in game.players)
    _w1g7_put(game, 0, "Grizzly Bears")
    game.start_turn(0)
    _w1g7_resolve(game)
    assert game.players[1].lost and not game.players[0].lost


def test_w1g7_test_of_endurance_wins_at_fifty_life(set_pool, catalog_by_name):
    game = _w1g7_table(set_pool, catalog_by_name)
    _w1g7_put(game, 0, "Test of Endurance")
    game.players[0].life = 49
    game.start_turn(0)
    _w1g7_resolve(game)
    assert not game.players[1].lost
    game.players[0].life = 50
    game.start_turn(0)
    _w1g7_resolve(game)
    assert game.players[1].lost

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_chaos_board(set_pool) -> "_w1g8_Game":
    """Seat 0 controls Planar Chaos; seat 0's turn, mana costs waived."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._put_permanent_onto_battlefield(
        0, _w1g8_Permanent(card=set_pool("JUD")["Planar Chaos"]), None,
    )
    return game


def test_w1g8_planar_chaos_counters_a_spell_whose_caster_loses_the_flip(set_pool, monkeypatch):
    """"Whenever a player casts a spell, that player flips a coin. If they lose
    the flip, counter that spell." The trigger is a stack object above the
    spell (CR 603.3); the opponent who cast the Bolt flips and loses, and the
    Bolt is countered — seat 0 keeps its life."""
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game = _w1g8_chaos_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Planar Chaos"]
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 20
    assert "Planar Chaos: P2 lost the coin flip" in game.log
    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]


def test_w1g8_planar_chaos_lets_a_spell_through_when_its_caster_wins(set_pool, monkeypatch):
    """The winner is the player who flipped (CR 705.2) — the Bolt's caster,
    not Planar Chaos's controller — and the spell resolves. Planar Chaos's
    controller is held to it too: their own spell is flipped for."""
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: True)
    game = _w1g8_chaos_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 17
    assert "Planar Chaos: P2 won the coin flip" in game.log

    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert "Planar Chaos: P1 lost the coin flip" in game.log


def test_w1g8_planar_chaos_is_sacrificed_when_its_upkeep_flip_is_lost(set_pool, monkeypatch):
    """"At the beginning of your upkeep, flip a coin. If you lose the flip,
    sacrifice this enchantment." Driven through the real turn: seat 0's next
    upkeep puts the trigger on the stack, and the lost flip sacrifices it."""
    game = _w1g8_chaos_board(set_pool)
    monkeypatch.setattr("engine.handlers.control_flow.flip_coin", lambda: False)
    game.start_turn(1)
    game.start_turn(0)
    _w1g8_resolve_stack(game)
    assert not any(p.card.name == "Planar Chaos" for p in game.controlled_by(0))
    assert [card.name for card in game.players[0].graveyard] == ["Planar Chaos"]

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Auras: a pump with a rider on one line (Cagemail), a pump sized by a live
# count (Exoskeletal Armor), and an Aura that moves on to a host picked at
# random when its creature dies (Infectious Rage). Each Aura is cast through
# the real cast path onto its host and then played: the attack declaration,
# the P/T as graveyards change, the death and the return.

import random as _w1g9_random

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_table(set_pool):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G9Game(players=[
        _W1G9PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g9_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam, not sick."""
    permanent = _W1G9Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_cast_aura(game, seat, card, host):
    """Cast *card* from *seat*'s hand onto *host* and resolve it."""
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand(seat, card.name, target_permanent_ids=[host.permanent_id])
    assert cast.supported, (cast.details, game.log[-4:])
    _w1g9_resolve_stack(game)
    game._settle()
    return next(p for p in game.all_permanents() if p.card is card)


def _w1g9_bolt(game, set_pool, seat, permanent):
    """Lightning Bolt *permanent* through the real path, the stack drained."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    cast = game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id]
    )
    assert cast.supported, game.log[-3:]
    for _ in range(3):
        _w1g9_resolve_stack(game)
        game._settle()


def _w1g9_attack_with(game, seat, permanent):
    """Declare *permanent* as *seat*'s only attacker; the (ok, why) pair."""
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    slot = next(
        i for i, perm in enumerate(game.players[seat].battlefield) if perm is permanent
    )
    return game.declare_attackers(seat, [slot], defending_player_index=1 - seat)


def test_w1g9_cagemail_pumps_its_host_and_forbids_the_attack(set_pool):
    """"Enchanted creature gets +2/+2 and can't attack." Both halves of the one
    line: a 4/4 Grizzly Bears whose attack the declaration refuses, beside an
    unenchanted Bears that may attack — and once the Aura is gone the host is a
    2/2 that may attack again (CR 611.3a: nothing to undo)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    caged = _w1g9_put(game, lea["Grizzly Bears"], 0)
    free = _w1g9_put(game, lea["Grizzly Bears"], 0)
    cagemail = _w1g9_cast_aura(game, 0, jud["Cagemail"], caged)

    assert cagemail.metadata.get("attached_to") is caged
    assert (caged.effective_power, caged.effective_toughness) == (4, 4)
    assert (free.effective_power, free.effective_toughness) == (2, 2)
    assert not game.can_attack(caged, 1)
    assert game.can_attack(free, 1)
    ok, _why = _w1g9_attack_with(game, 0, caged)
    assert not ok, "CR 508.1c: the restriction refuses the declaration itself"

    game._set_phase_and_step("precombat_main", "main")
    game.players[1].hand.append(lea["Disenchant"])
    cast = game.queue_from_hand(1, "Disenchant", target_permanent_ids=[cagemail.permanent_id])
    assert cast.supported, game.log[-3:]
    _w1g9_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(cagemail)
    assert (caged.effective_power, caged.effective_toughness) == (2, 2)
    assert game.can_attack(caged, 1)


def test_w1g9_exoskeletal_armor_recounts_creature_cards_in_every_graveyard(set_pool):
    """"+X/+X, where X is the number of creature cards in all graveyards." The
    ruling (2004-10-04): "The value of X changes as the number of creatures
    cards in graveyards changes." Both graveyards count, a land does not, and a
    creature card leaving a graveyard takes its +1/+1 with it."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    bears = _w1g9_put(game, lea["Grizzly Bears"], 0)
    _w1g9_cast_aura(game, 0, jud["Exoskeletal Armor"], bears)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    assert game.put_card_into_graveyard(0, lea["Hill Giant"])
    assert game.put_card_into_graveyard(1, lea["Craw Wurm"])
    assert game.put_card_into_graveyard(1, lea["Island"])
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)

    # A creature dying adds its card to the count the moment it lands.
    giant = _w1g9_put(game, lea["Hill Giant"], 1)
    _w1g9_bolt(game, set_pool, 0, giant)
    assert "Hill Giant" in [card.name for card in game.players[1].graveyard]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    # …and a card leaving a graveyard takes it away again.
    wurm = game.players[1].graveyard.index(lea["Craw Wurm"])
    game.players[1].graveyard.pop(wurm)
    game._settle()
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def _w1g9_rage_board(set_pool, *others):
    """Seat 0's Grizzly Bears under Infectious Rage, *others* on seat 1."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g9_table(set_pool)
    bears = _w1g9_put(game, lea["Grizzly Bears"], 0)
    placed = [_w1g9_put(game, card, 1) for card in others]
    rage = _w1g9_cast_aura(game, 0, jud["Infectious Rage"], bears)
    return game, bears, rage, placed


def _w1g9_rage_on_board(game):
    return [p for p in game.all_permanents() if p.card.name == "Infectious Rage"]


def test_w1g9_infectious_rage_returns_onto_a_creature_it_can_legally_enchant(set_pool):
    """The host dies and the Aura comes back attached to the one creature it
    can enchant. The rulings (2004-10-04): it is put there "without targeting
    it, so it can be placed on a creature with Shroud", and "you can't place
    this card on a permanent with protection from red" — so with a shroud
    creature and a protection-from-red creature on the board, every seed lands
    it on the shroud one. It comes back under its controller's control
    (CR 110.2a) and pumps its new host."""
    for seed in range(6):
        _w1g9_random.seed(seed)
        game, bears, _rage, (centaur, beasts) = _w1g9_rage_board(
            set_pool,
            set_pool("MIR")["Jolrael's Centaur"],   # 2/2 shroud
            set_pool("LEG")["Beasts of Bogardan"],  # protection from red
        )
        assert (bears.effective_power, bears.effective_toughness) == (4, 1)
        _w1g9_bolt(game, set_pool, 1, bears)

        assert not game.is_on_battlefield(bears)
        (rage,) = _w1g9_rage_on_board(game)
        assert rage.metadata.get("attached_to") is centaur
        assert game.controller_index_of(rage) == 0
        assert (centaur.effective_power, centaur.effective_toughness) == (4, 1)
        assert (beasts.effective_power, beasts.effective_toughness) == (3, 3)
        assert any("at random" in line for line in game.log)


def test_w1g9_infectious_rage_picks_at_random_and_a_seed_reproduces_it(set_pool):
    """"Choose a creature **at random**": nobody picks. With two legal hosts
    the pick moves with the seed — both are reached across a run of seeds,
    which a controller's choice would not do — and the same seed always makes
    the same pick (the module RNG the simulator seeds)."""
    lea = set_pool("LEA")

    def landing(seed):
        _w1g9_random.seed(seed)
        game, bears, _rage, (giant, wurm) = _w1g9_rage_board(
            set_pool, lea["Hill Giant"], lea["Craw Wurm"]
        )
        _w1g9_bolt(game, set_pool, 1, bears)
        (rage,) = _w1g9_rage_on_board(game)
        host = rage.metadata.get("attached_to")
        assert host in (giant, wurm)
        return host.card.name

    picks = [landing(seed) for seed in range(12)]
    assert set(picks) == {"Hill Giant", "Craw Wurm"}, picks
    assert [landing(seed) for seed in range(12)] == picks


def test_w1g9_infectious_rage_with_no_legal_host_stays_in_the_graveyard(set_pool):
    """CR 303.4g: "If an Aura is entering the battlefield and there is no legal
    object or player for it to enchant, the Aura remains in its current zone."
    The only other creature has protection from red, so the Aura stays in its
    owner's graveyard rather than entering attached to nothing."""
    game, bears, _rage, (beasts,) = _w1g9_rage_board(
        set_pool, set_pool("LEG")["Beasts of Bogardan"]
    )
    _w1g9_bolt(game, set_pool, 1, bears)

    assert _w1g9_rage_on_board(game) == []
    assert "Infectious Rage" in [card.name for card in game.players[0].graveyard]
    assert (beasts.effective_power, beasts.effective_toughness) == (3, 3)
    assert not any("returned to the battlefield" in line for line in game.log)

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _W1G10Game, PlayerState as _W1G10PlayerState
from engine.board_payment import board_can_pay as _w1g10_board_can_pay
from engine.models import Permanent as _W1G10Permanent


def _w1g10_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = _W1G10Game(players=[
        _W1G10PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _w1g10_put(game, card, seat):
    permanent = _W1G10Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _w1g10_pool(game, seat):
    return {s: n for s, n in game.players[seat].mana_pool.items() if n}


def test_w1g10_mirari_s_wake_doubles_its_controller_s_land_mana(set_pool):
    """"Whenever you tap a land for mana, add one mana of any type that land
    produced." A triggered mana ability (CR 605.1b) resolved inside the tap
    (CR 605.4a): a Forest tapped by the Wake's controller makes {G}{G}, and a
    Badlands asked for {R} makes {R}{R} — the type it produced, not one of the
    controller's choosing (ruling 2021-06-18)."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g10_table(set_pool)
    _w1g10_put(game, jud["Mirari's Wake"], 0)
    forest = _w1g10_put(game, lea["Forest"], 0)
    badlands = _w1g10_put(game, lea["Badlands"], 0)
    game._settle()

    assert game.tap_land_for_mana(0, "Forest", permanent_id=forest.permanent_id)
    assert _w1g10_pool(game, 0) == {"G": 2}
    assert game.tap_land_for_mana(
        0, "Badlands", "R", permanent_id=badlands.permanent_id
    )
    assert _w1g10_pool(game, 0) == {"G": 2, "R": 2}
    assert any("Mirari's Wake: P0 added {R}" in line for line in game.log)


def test_w1g10_mirari_s_wake_ignores_an_opponent_s_tap(set_pool):
    """"Whenever **you** tap" — the opponent's Forest makes its one {G}."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g10_table(set_pool)
    _w1g10_put(game, jud["Mirari's Wake"], 0)
    theirs = _w1g10_put(game, lea["Forest"], 1)
    game._settle()

    assert game.tap_land_for_mana(1, "Forest", permanent_id=theirs.permanent_id)
    assert _w1g10_pool(game, 1) == {"G": 1}
    assert _w1g10_pool(game, 0) == {}


def test_w1g10_mirari_s_wake_counts_in_what_the_board_can_pay(set_pool):
    """What the castable highlight and the auto-payment ask beforehand
    (``board_payment``) is what the tap will make: two Mountains pay {3}{R}
    under the Wake and not without it. And creatures its controller controls
    get +1/+1 — the opponent's do not."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g10_table(set_pool)
    _w1g10_put(game, lea["Mountain"], 0)
    _w1g10_put(game, lea["Mountain"], 0)
    game._settle()
    cost = {"R": 1, "generic": 3}
    assert not _w1g10_board_can_pay(game, 0, cost)

    _w1g10_put(game, jud["Mirari's Wake"], 0)
    mine = _w1g10_put(game, lea["Grizzly Bears"], 0)
    theirs = _w1g10_put(game, lea["Grizzly Bears"], 1)
    game._settle()
    assert _w1g10_board_can_pay(game, 0, cost)
    assert (mine.effective_power, mine.effective_toughness) == (3, 3)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)


def _w1g10_mist_game(set_pool, seat0, seat1, *, graveyards=((), ())):
    """Two seats with permanents (card names) and graveyards (card names),
    Mist of Stagnation on seat 0's side, every other permanent tapped."""
    from tests.helpers import resolve_stack

    pool = {**set_pool("LEA"), **set_pool("JUD")}
    island = pool["Island"]
    game = _W1G10Game(players=[
        _W1G10PlayerState(
            name=f"P{seat}", life=20, library=[island] * 8,
            graveyard=[pool[name] for name in graveyards[seat]],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    mist = _w1g10_put(game, pool["Mist of Stagnation"], 0)
    sides = []
    for seat, names in ((0, seat0), (1, seat1)):
        placed = [_w1g10_put(game, pool[name], seat) for name in names]
        for permanent in placed:
            permanent.tapped = True
        sides.append(placed)
    game._settle()

    def take_turn(seat):
        game.start_turn(seat)
        for _ in range(4):
            game.auto_resolve_pending_choices()
            if not resolve_stack(game):
                break

    return game, mist, sides, take_turn


def test_w1g10_mist_of_stagnation_untaps_one_per_graveyard_card(set_pool):
    """"Permanents don't untap during their controllers' untap steps. At the
    beginning of each player's upkeep, that player chooses a permanent for each
    card in their graveyard, then untaps those permanents."

    The untap step untaps nothing of anyone's (CR 502.3); the upkeep player
    with two cards in their graveyard untaps two permanents, and a seat
    nobody asks picks its own tapped ones. The other seat, with an empty
    graveyard, gets nothing back on its own upkeep."""
    game, _, (mine, theirs), take_turn = _w1g10_mist_game(
        set_pool,
        ["Forest", "Forest", "Forest", "Grizzly Bears"],
        ["Mountain", "Mountain"],
        graveyards=(("Lightning Bolt", "Giant Growth"), ()),
    )

    take_turn(1)
    assert all(permanent.tapped for permanent in theirs), (
        "an empty graveyard untaps nothing, and the untap step untapped nothing"
    )
    assert all(permanent.tapped for permanent in mine)

    take_turn(0)
    assert [permanent.tapped for permanent in mine] == [False, False, True, True]
    assert all(permanent.tapped for permanent in theirs)


def test_w1g10_mist_of_stagnation_counts_the_upkeep_players_graveyard(set_pool):
    """"…for each card in **their** graveyard" is the upkeep player's pile, not
    the Mist controller's: on seat 1's upkeep seat 1's three cards count, and
    seat 0's own graveyard of one does not."""
    game, _, (mine, theirs), take_turn = _w1g10_mist_game(
        set_pool,
        ["Forest", "Forest"],
        ["Mountain", "Mountain", "Mountain", "Mountain"],
        graveyards=(("Lightning Bolt",), ("Hill Giant", "Hill Giant", "Dark Ritual")),
    )
    take_turn(1)
    assert [permanent.tapped for permanent in theirs] == [False, False, False, True]
    assert all(permanent.tapped for permanent in mine)


def test_w1g10_mist_of_stagnation_asks_the_upkeep_player_and_any_permanent_counts(set_pool):
    """An interactive upkeep player is asked for exactly as many as their
    graveyard holds, out of **every** permanent — "a permanent", not one they
    control — and the ones named are untapped, an opponent's included."""
    game, _, (mine, theirs), _ = _w1g10_mist_game(
        set_pool,
        ["Forest", "Forest"],
        ["Mountain", "Mountain"],
        graveyards=((), ("Lightning Bolt", "Dark Ritual")),
    )
    game.interactive_seats = {0, 1}
    game.start_turn(1)
    for _ in range(4):
        if not game.stack or not game.resolve_top_of_stack():
            break

    prompts = [c for c in game.pending_choices if c.kind == "permanent_set_choice"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    prompt = prompts[0]
    assert prompt.player_index == 1
    assert (prompt.data["up_to"], prompt.data["at_least"]) == (2, 2)
    offered = {perm.permanent_id for perm in game.live_permanent_set_choices(prompt)}
    assert {perm.permanent_id for perm in mine + theirs} <= offered
    assert not game.confirm_permanent_set_choice(1, [theirs[0].permanent_id]), (
        "one permanent is not one for each card"
    )
    assert game.confirm_permanent_set_choice(
        1, [theirs[1].permanent_id, mine[0].permanent_id]
    )
    from tests.helpers import resolve_stack

    resolve_stack(game)
    assert [permanent.tapped for permanent in theirs] == [True, False]
    assert [permanent.tapped for permanent in mine] == [False, True]

# ==== end W1G10 ======================================================
