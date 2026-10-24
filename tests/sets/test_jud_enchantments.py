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

# ==== end W1G10 ======================================================
