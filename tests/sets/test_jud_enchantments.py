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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

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
