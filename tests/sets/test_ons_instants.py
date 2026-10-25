"""Onslaught instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
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

# --- W1G3: cycling triggers (CR 702.29c) and the cycling instants -----------
#
# "When you cycle this card, …" is the cycled card's own triggered ability,
# announced where the cycling ability's discard cost is paid
# (`CardActivationMixin._announce_cycle`) and asked of the card in the
# graveyard. Each test cycles the card, resolves the trigger **alone** — the
# cycling ability is still under it, so nothing has been drawn yet (the
# 2022-12-08 rulings) — reads the board, then lets the draw resolve.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=5, interactive=()):
    """Alice (seat 0, active) holding *hand*; Bob holding *opponent_hand*."""
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[filler] * library,
    )
    bob = PlayerState(
        name="Bob", hand=[ons[name] for name in opponent_hand],
        library=[filler] * library,
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cycle_and_resolve_trigger(game, name, *, accept=True):
    """Cycle *name* from seat 0 and resolve its trigger — only its trigger.

    Asserts the trigger is above the cycling ability, answers the "you may"
    (*accept*), and returns with the cycling ability still on the stack.
    """
    assert game.activate_from_hand(0, name).supported
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.stack[-2].ability_text.endswith("Discard this card: Draw a card.")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, accept, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1, "the cycling ability is still waiting to draw"


def _w1g3_resolve_cycle_trigger_alone(game):
    """Resolve the trigger on top of the cycling ability and take its "you
    may", leaving the draw on the stack."""
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1


def test_w1g3_renewed_faith_cycled_gains_2_life_before_the_draw(set_pool):
    """"When you cycle this card, you may gain 2 life." — not the spell's 6."""
    game, alice, _bob = _w1g3_table(set_pool, "Renewed Faith")

    _w1g3_cycle_and_resolve_trigger(game, "Renewed Faith")
    assert alice.life == 22
    assert alice.hand == [] and len(alice.library) == 5

    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    assert [c.name for c in alice.graveyard] == ["Renewed Faith"]
    assert alice.life == 22


def test_w1g3_renewed_faith_declined_still_draws(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Renewed Faith")

    _w1g3_cycle_and_resolve_trigger(game, "Renewed Faith", accept=False)
    resolve_stack(game)
    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_sunfire_balm_cycled_shields_the_creature_its_controller_names(set_pool):
    """"…you may prevent the next 1 damage that would be dealt to any target
    this turn." Alice is asked for the target as the trigger goes on the stack
    (CR 603.3d) and names her own Bear; a Shock then marks only 1 of its 2."""
    game, alice, bob = _w1g3_table(
        set_pool, "Sunfire Balm", opponent_hand=["Shock"], interactive={0},
    )
    bear = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))

    assert game.activate_from_hand(0, "Sunfire Balm").supported
    asked = game.pending_choice_of("trigger_target", 0)
    offered = {(entry["kind"], entry.get("seat"), entry.get("permanent_id"))
               for entry in asked.data["targets"]}
    assert offered == {
        ("player", 0, None), ("player", 1, None),
        ("permanent", 0, bear.permanent_id),
    }
    assert game.resolve_pending_choice("trigger_target", 0, permanent_id=bear.permanent_id)
    assert game.stack[-1].target_permanent_id == [bear.permanent_id]

    # The trigger resolves and stops to ask; it stays on the stack (CR 608.2)
    # until the "you may" is answered, and only then does the draw come.
    assert game.resolve_top_of_stack(pause_for_choices=True)
    assert len(game.stack) == 2 and alice.hand == []
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    assert len(game.stack) == 1
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]

    game.interactive_seats = set()
    assert game.queue_from_hand(1, "Shock", target_permanent_ids=[bear.permanent_id]).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bear)
    assert bear.damage_marked == 1
    assert "Prevented 1 damage to Bear" in game.log


def test_w1g3_sunfire_balm_cycled_by_a_seat_nobody_asks_shields_itself(set_pool):
    """The default a non-interactive seat takes for "any target" is the
    standing opposing seat — except for a gift, which this is: the AI and a
    headless seat shield their own face, not the opponent's
    (`TriggerChoicesMixin._default_trigger_target`)."""
    game, alice, bob = _w1g3_table(set_pool, "Sunfire Balm", opponent_hand=["Shock"])

    assert game.activate_from_hand(0, "Sunfire Balm").supported
    assert game.stack[-1].target_player_index == 0
    _w1g3_resolve_cycle_trigger_alone(game)
    resolve_stack(game)

    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    resolve_stack(game)
    assert alice.life == 19, "1 of the Shock's 2 was prevented"


def test_w1g3_choking_tethers_cycled_taps_a_creature_before_the_draw(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Choking Tethers")
    theirs = _w1g3_put(game, 1, _mk_creature_card("Attacker", 3, 3))

    _w1g3_cycle_and_resolve_trigger(game, "Choking Tethers")
    assert theirs.tapped
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_counters_a_spell_its_controller_cannot_pay_for(set_pool):
    """Bob's Shock is on the stack; Alice cycles Complicate in response. The
    trigger targets the Shock (the cycling ability under it is no spell), Bob
    has no mana for the {1}, and the Shock is countered before Alice draws."""
    game, alice, bob = _w1g3_table(set_pool, "Complicate", opponent_hand=["Shock"])
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported

    assert game.activate_from_hand(0, "Complicate").supported
    trigger = game.stack[-1]
    assert trigger.target_stack_item is game.stack[0]
    assert game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    assert [c.name for c in bob.graveyard] == ["Shock"]
    assert [item.card.name for item in game.stack] == ["Complicate"]

    resolve_stack(game)
    assert alice.life == 20
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_is_paid_off_by_a_controller_with_the_mana(set_pool):
    """The same, with an untapped Mountain beside Bob: he pays {1} and the
    Shock resolves."""
    game, alice, bob = _w1g3_table(set_pool, "Complicate", opponent_hand=["Shock"])
    game.enforce_mana_costs = True
    mountain = _w1g3_put(game, 1, set_pool("ONS")["Mountain"])
    bob.mana_pool["R"] = 1
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    alice.mana_pool.update({"C": 2, "U": 1})

    assert game.activate_from_hand(0, "Complicate").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert mountain.tapped, "Bob tapped it to pay"
    assert alice.life == 18, game.log
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_complicate_cycled_with_no_spell_on_the_stack_just_draws(set_pool):
    """"You can cycle this card even if there are no legal targets for the
    triggered ability." (2022-12-08.) CR 603.3d takes the trigger off."""
    game, alice, _bob = _w1g3_table(set_pool, "Complicate")
    assert game.activate_from_hand(0, "Complicate").supported
    assert [item.ability_text for item in game.stack] == [
        "{2}{U}, Discard this card: Draw a card."
    ]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_death_pulse_cycled_kills_a_one_toughness_creature(set_pool):
    game, alice, bob = _w1g3_table(set_pool, "Death Pulse")
    weenie = _w1g3_put(game, 1, _mk_creature_card("Weenie", 1, 1))

    _w1g3_cycle_and_resolve_trigger(game, "Death Pulse")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(weenie)
    assert [c.name for c in bob.graveyard] == ["Weenie"]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_solar_blast_cycled_deals_1_damage_from_the_graveyard(set_pool):
    """"…you may have it deal 1 damage to any target." "It" is the card, in
    the graveyard by now; the seat nobody asks aims at the opponent."""
    game, alice, bob = _w1g3_table(set_pool, "Solar Blast")

    _w1g3_cycle_and_resolve_trigger(game, "Solar Blast")
    assert bob.life == 19
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_primal_boost_cycled_pumps_until_end_of_turn(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Primal Boost")
    bear = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))

    _w1g3_cycle_and_resolve_trigger(game, "Primal Boost")
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    resolve_stack(game)
    game.resolve_cleanup_step(0)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


#: The Onslaught instants that print cycling and nothing that triggers on it,
#: with the mana their cycling cost takes from the pool. Supported on arrival;
#: driven here for the first time.
_W1G3_PLAIN_CYCLING_INSTANTS = {
    "Akroma's Blessing": {"W": 1},
    "Aura Extraction": {"C": 2},
    "Fade from Memory": {"B": 1},
    "Mage's Guile": {"U": 1},
    "Starstorm": {"C": 3},
    "Swat": {"C": 2},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_INSTANTS))
def test_w1g3_a_plain_cycling_instant_pays_its_cost_and_draws(set_pool, name):
    """Cycling from the hand with mana costs enforced: exactly the printed
    cycling cost leaves the pool, the card goes to the graveyard, one card is
    drawn and the spell's own effect never happens."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1
    assert usable_activated_abilities(program) == []

    game, alice, bob = _w1g3_table(set_pool, name)
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_INSTANTS[name])
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]
    assert (alice.life, bob.life) == (20, 20)


def test_w1g3_a_cycling_instant_cannot_be_cycled_without_its_cost(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Starstorm")
    game.enforce_mana_costs = True
    alice.mana_pool.update({"C": 2})
    assert not game.activate_from_hand(0, "Starstorm").supported
    assert [c.name for c in alice.hand] == ["Starstorm"]


# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

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


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
