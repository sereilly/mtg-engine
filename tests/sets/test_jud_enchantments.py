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
#
# Two drive-list cards, supported on arrival, given a game: Telekinetic Bonds
# and Spirit Cairn, both "Whenever a player discards a card, you may pay …".
# Driving Bonds found its "tap or untap target permanent" writing the tapped
# state directly — past the CR 701.26 seams every "becomes tapped" and
# "becomes untapped" trigger hangs off — on all thirteen cards that print the
# verb (``handlers/tapping.tap_or_untap_target``).

from engine import Game as _W1G6EGame, PlayerState as _W1G6EPlayerState  # noqa: E402
from engine.models import Permanent as _W1G6EPermanent  # noqa: E402
from tests.helpers import _nosick as _w1g6e_nosick  # noqa: E402
from tests.helpers import resolve_stack as _w1g6e_resolve_stack  # noqa: E402


def _w1g6e_table(set_pool, enchantment, *, interactive):
    """Alice: *enchantment*, two Islands and a Plains, Mind Twist in hand;
    Bob: one card to discard. Alice's turn."""
    lea = set_pool("LEA")
    game = _W1G6EGame(players=[
        _W1G6EPlayerState(name="Alice", hand=[lea["Mind Twist"]], library=[lea["Island"]] * 5),
        _W1G6EPlayerState(name="Bob", hand=[lea["Lightning Bolt"]], library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.start_turn(0)
    for card in (set_pool("JUD")[enchantment], lea["Island"], lea["Island"], lea["Plains"]):
        _w1g6e_put(game, 0, card)
    return game


def _w1g6e_put(game, seat, card):
    permanent = _w1g6e_nosick(_W1G6EPermanent(card=card))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g6e_resolve_stack(game)
    return permanent


def _w1g6e_bob_discards(game):
    """Mind Twist for one: Bob discards his only card, which is the event both
    enchantments watch ("a player" — the opponent here)."""
    result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=1)
    assert result.supported, result.details
    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]


def _w1g6e_answer_bonds(game, target):
    """Alice aims Telekinetic Bonds' trigger at *target* (CR 603.3d), pays its
    {1}{U} and takes the tap-or-untap — each as the prompt that asks it."""
    answered = []
    for _ in range(12):
        if game.pending_choices:
            choice = game.pending_choices[0]
            if choice.kind == "trigger_target":
                assert game.resolve_pending_choice(
                    "trigger_target", 0, permanent_id=target.permanent_id,
                    seat=game.controller_index_of(target),
                )
            else:
                assert choice.kind == "optional_pay", choice.kind
                assert game.resolve_pending_choice("optional_pay", 0, accept=True, option=None)
            answered.append(choice.kind)
        elif game.stack:
            game.resolve_top_of_stack(pause_for_choices=True)
        else:
            return answered
    raise AssertionError(f"the prompts did not settle: {answered}")


def test_w1g6_telekinetic_bonds_tapping_a_forest_is_a_forest_becoming_tapped(set_pool):
    """Bob discards; Alice pays {1}{U} and taps his Forest. Lifetap ("Whenever
    a Forest an opponent controls becomes tapped, you gain 1 life") sees it —
    it did not while the toggle wrote ``tapped`` past ``become_tapped``."""
    game = _w1g6e_table(set_pool, "Telekinetic Bonds", interactive=True)
    _w1g6e_put(game, 0, set_pool("LEA")["Lifetap"])
    forest = _w1g6e_put(game, 1, set_pool("LEA")["Forest"])
    _w1g6e_bob_discards(game)

    assert _w1g6e_answer_bonds(game, forest) == [
        "trigger_target", "optional_pay", "optional_pay",
    ]
    _w1g6e_resolve_stack(game)
    assert forest.tapped
    assert game.players[0].life == 21
    assert sum(1 for p in game.controlled_by(0) if p.has_type("land") and p.tapped) == 2


def test_w1g6_telekinetic_bonds_untapping_a_creature_is_it_becoming_untapped(set_pool):
    """The untap half: a tapped Ghostly Pilferer untapped by Bonds is a
    creature that became untapped (CR 701.26b), and its own trigger fires."""
    game = _w1g6e_table(set_pool, "Telekinetic Bonds", interactive=True)
    pilferer = _w1g6e_put(game, 1, set_pool("M21")["Ghostly Pilferer"])
    pilferer.tapped = True
    _w1g6e_bob_discards(game)
    _w1g6e_answer_bonds(game, pilferer)

    _w1g6e_resolve_stack(game)
    assert not pilferer.tapped
    untapped = game.log.index("Untapped Ghostly Pilferer")
    assert "Ghostly Pilferer ability resolved" in game.log[untapped:], game.log[-8:]


def test_w1g6_spirit_cairn_buys_a_flying_spirit_when_an_opponent_discards(set_pool):
    """Headless: the offer's {W} is paid off the Plains and a 1/1 white Spirit
    with flying is created — the discard is Bob's, and "a player" counts it."""
    game = _w1g6e_table(set_pool, "Spirit Cairn", interactive=False)
    _w1g6e_bob_discards(game)
    _w1g6e_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6e_resolve_stack(game)

    (spirit,) = [p for p in game.controlled_by(0) if p.card.name == "Spirit Token"]
    assert (spirit.effective_power, spirit.effective_toughness) == (1, 1)
    assert game._has_keyword(spirit, "flying")
    assert spirit.card.colors == ("W",)
    plains = next(p for p in game.controlled_by(0) if p.card.name == "Plains")
    assert plains.tapped

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

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

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
