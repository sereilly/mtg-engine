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

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.type_changes import gain_types as _w1g4_gain_types
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_creature(name, subtype):
    return _W1G4Permanent(card=_w1g4_mk_card(name, "{2}", f"Creature - {subtype}", ""))


def _w1g4_pump_game(set_pool, spell, mine, theirs, interactive=()):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[spell]], battlefield=list(mine),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_pt(perm):
    return (perm.effective_power, perm.effective_toughness)


def test_w1g4_defensive_maneuvers_asks_on_resolution_and_toughens_only_that_type(set_pool):
    """"Creatures of the creature type of your choice get +0/+4 until end of
    turn." CR 608.2d: the type is chosen as the spell resolves, so the prompt
    holds the spell on the stack and nothing is pumped until the answer — then
    every creature of the type, the opponent's included, and nothing else."""
    elf = _w1g4_creature("Elf", "Elf")
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    their_goblin = _w1g4_creature("Their Goblin", "Goblin")
    zombie = _w1g4_creature("Zombie", "Zombie")
    game = _w1g4_pump_game(
        set_pool, "Defensive Maneuvers", [elf, my_goblin], [their_goblin, zombie],
        interactive=[0],
    )
    result = game.cast_from_hand(0, "Defensive Maneuvers")
    assert result.supported, result.details

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("creature_type_choice", 0)
    ]
    assert _w1g4_pt(my_goblin) == (2, 2), "nothing is pumped before the answer"

    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)
    assert _w1g4_pt(my_goblin) == (2, 6)
    assert _w1g4_pt(their_goblin) == (2, 6)
    assert _w1g4_pt(elf) == (2, 2)
    assert _w1g4_pt(zombie) == (2, 2)
    assert any("Defensive Maneuvers: chose goblin" in line for line in game.log)


def test_w1g4_defensive_maneuvers_default_names_the_casters_own_type(set_pool):
    """A seat nobody asks names the type its own creatures have most of, net
    of the opponents' — a pump aimed at the opponents' type is not a choice a
    player makes. Elves 2 − 0 beat Goblins 1 − 3."""
    elves = [_w1g4_creature("Elf A", "Elf"), _w1g4_creature("Elf B", "Elf")]
    my_goblin = _w1g4_creature("My Goblin", "Goblin")
    theirs = [_w1g4_creature(f"Goblin {n}", "Goblin") for n in range(3)]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [*elves, my_goblin], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert game.pending_choices == []
    assert [_w1g4_pt(perm) for perm in elves] == [(2, 6), (2, 6)]
    assert _w1g4_pt(my_goblin) == (2, 2)
    assert all(_w1g4_pt(perm) == (2, 2) for perm in theirs)
    assert any("Defensive Maneuvers: chose elf" in line for line in game.log)


def test_w1g4_tribal_unity_pumps_the_named_type_by_x_through_the_layers(set_pool):
    """"Creatures of the creature type of your choice get +X/+X until end of
    turn." X is the announced one (CR 107.3a), and the type is read through
    layer 4: a creature that *became* a Goblin is one (CR 613.1d), and the
    Elf beside it that did not is left alone."""
    became_goblin = _w1g4_creature("Shifted Elf", "Elf")
    _w1g4_gain_types(became_goblin, subtypes=("goblin",), source="test")
    elf = _w1g4_creature("Elf", "Elf")
    goblin = _w1g4_creature("Goblin", "Goblin")
    game = _w1g4_pump_game(
        set_pool, "Tribal Unity", [became_goblin, elf], [goblin], interactive=[0],
    )
    result = game.cast_from_hand(0, "Tribal Unity", x_value=3)
    assert result.supported, result.details
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(became_goblin) == (5, 5)
    assert _w1g4_pt(goblin) == (5, 5)
    assert _w1g4_pt(elf) == (2, 2)


def test_w1g4_a_pump_with_no_type_to_name_pumps_nothing(set_pool):
    """No creature of the caster's means no type worth naming: the default is
    no choice, and the buff reads that as pumping nothing — never as a buff
    with no narrowing, which would pump the opponent's whole board."""
    theirs = [_w1g4_creature("Goblin", "Goblin")]
    game = _w1g4_pump_game(set_pool, "Defensive Maneuvers", [], theirs)
    game.cast_from_hand(0, "Defensive Maneuvers")
    _w1g4_resolve_stack(game)

    assert _w1g4_pt(theirs[0]) == (2, 2)
    assert any("no creature type was chosen" in line for line in game.log)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: Trickery Charm, Standardize (CR 205.1a, CR 611.2c) and
# Artificial Evolution (CR 612, CR 613.1c) ---------------------------------
from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.layer_bridge import computed_types as _w1g5_computed_types
from engine.models import Permanent as _W1G5Permanent
from engine.text_changes import changed_words as _w1g5_changed_words
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, hand, *, interactive=(0,)):
    """Seat 0 holding *hand* (ONS names), costs off, in its main phase."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="A", hand=[set_pool("ONS")[name] for name in hand]),
        _W1G5PlayerState(name="B"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._recompute_continuous_effects()
    return permanent


def _w1g5_types(permanent):
    return set(_w1g5_computed_types(permanent)[1])


def test_w1g5_trickery_charm_sets_its_targets_type(set_pool, catalog_by_name):
    """"• Target creature becomes the creature type of your choice until end of
    turn." The mode's picker offers creatures and only creatures; the type is
    chosen as the Charm resolves, with no exclusion — an opponent's Bears can
    be made a Wall — and it is a Wall alone until cleanup."""
    game = _w1g5_table(set_pool, ["Trickery Charm"])
    bears = _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    forest = _w1g5_put(game, 1, catalog_by_name["Forest"])
    charm = set_pool("ONS")["Trickery Charm"]
    spec = game.cast_target_spec(0, charm, mode_index=1)
    assert spec["kind"] == "creature" and spec["requires_target"]
    assert not game.queue_from_hand(
        0, "Trickery Charm", mode_index=1, target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.queue_from_hand(
        0, "Trickery Charm", mode_index=1, target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "wall")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(bears) == {"wall"}
    assert "Grizzly Bears became a Wall until end of turn (Trickery Charm)" in game.log
    game.resolve_cleanup_step(0)
    assert _w1g5_types(bears) == {"bear"}


def test_w1g5_trickery_charm_flying_mode_is_untouched(set_pool, catalog_by_name):
    """The first mode is still flying alone: no type prompt is armed."""
    game = _w1g5_table(set_pool, ["Trickery Charm"])
    bears = _w1g5_put(game, 0, catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Trickery Charm", mode_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game._has_keyword(bears, "flying") and _w1g5_types(bears) == {"bear"}
    assert not game.pending_choices


def test_w1g5_standardize_sets_every_creature_on_the_battlefield(
    set_pool, catalog_by_name,
):
    """"Choose a creature type other than Wall. Each creature becomes that type
    until end of turn." Wall is refused with the question still standing; the
    answer sets every creature on either side — so Goblin King, itself made a
    Goblin, pumps all the others — and a creature that enters afterwards is
    untouched (CR 611.2c; the card's ruling: "This spell only affects creatures
    on the battlefield when it resolves"). Cleanup ends every one."""
    game = _w1g5_table(set_pool, ["Standardize"])
    game.players[0].hand.append(catalog_by_name["Grizzly Bears"])
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    king = _w1g5_put(game, 0, catalog_by_name["Goblin King"])
    their_bears = _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    assert game.queue_from_hand(0, "Standardize").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "wall") is False
    assert _w1g5_types(their_bears) == {"bear"}
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(game)

    assert [_w1g5_types(p) for p in (dreamer, king, their_bears)] == [{"goblin"}] * 3
    assert (their_bears.effective_power, their_bears.effective_toughness) == (3, 3)
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)

    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g5_resolve_stack(game)
    (late,) = [
        perm for perm in game.controlled_by(0) if perm.card.name == "Grizzly Bears"
    ]
    assert _w1g5_types(late) == {"bear"}
    assert (late.effective_power, late.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert _w1g5_types(dreamer) == {"illusion"}
    assert _w1g5_types(king) == {"goblin"}
    assert _w1g5_types(their_bears) == {"bear"}



def _w1g5_evolve(game, target, old, new):
    """Seat 0 casts Artificial Evolution at *target* and names *old*, then
    *new* — each asked as the spell resolves, one after the other."""
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[target.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, old)
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, new)
    _w1g5_resolve_stack(game)


def test_w1g5_artificial_evolution_rewrites_a_lords_text_and_type_line(
    set_pool, catalog_by_name,
):
    """"Change the text of target spell or permanent by replacing all instances
    of one creature type with another." Elf to Goblin on Elvish Champion: its
    "Other Elf creatures" now reads Goblin, so the opponent's Llanowar Elves
    lose the +1/+1 and seat 0's Raging Goblin gets it with forestwalk; its type
    line reads Goblin too (CR 612.1 — the ruling: "the text box and the type
    line"); its name does not change (CR 612.2). Indefinite: cleanup leaves
    it."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    elves = _w1g5_put(game, 1, catalog_by_name["Llanowar Elves"])
    goblin = _w1g5_put(game, 0, catalog_by_name["Raging Goblin"])
    assert (elves.effective_power, goblin.effective_power) == (2, 1)

    _w1g5_evolve(game, champion, "elf", "goblin")

    assert champion.effective_card.oracle_text.startswith(
        "Other Goblin creatures get +1/+1 and have forestwalk."
    )
    assert _w1g5_types(champion) == {"goblin"}
    assert (elves.effective_power, elves.effective_toughness) == (1, 1)
    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2)
    assert game._has_keyword(goblin, "forestwalk")
    assert champion.effective_card.name == "Elvish Champion"
    assert {"from": "elf", "to": "goblin"} in _w1g5_changed_words(champion)
    assert (
        "Artificial Evolution changed elf to goblin in Elvish Champion's text"
        in game.log
    )
    game.resolve_cleanup_step(0)
    assert goblin.effective_power == 2


def test_w1g5_artificial_evolution_refuses_wall_and_the_same_word(
    set_pool, catalog_by_name,
):
    """"The new creature type can't be Wall." and the ruling "It can't change
    a word to the same word": the second question refuses both with the
    question still standing, and its own list offers neither."""
    from web.prompts import PromptContext, render_prompts

    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[champion.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    (first,) = game.pending_choices
    assert first.data["word_role"] == "replaced"
    assert first.data["default_creature_type"] == "elf", "written on the target"
    assert game.confirm_creature_type_choice(0, "elf")
    assert game.confirm_creature_type_choice(0, "wall") is False
    assert game.confirm_creature_type_choice(0, "elf") is False
    offered = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["creature_type_choice"]
    assert "wall" not in offered["creature_types"]
    assert "elf" not in offered["creature_types"]
    # The second of the two questions says it is the replacement.
    assert offered["word_role"] == "replacement"
    assert _w1g5_types(champion) == {"elf"}
    assert game.confirm_creature_type_choice(0, "zombie")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(champion) == {"zombie"}


def test_w1g5_a_creature_type_set_by_an_effect_beats_the_text_change(set_pool):
    """The ruling: "If a creature's creature type has been changed by a spell
    or ability, changing the card's text won't affect or alter the new
    creature type." The Mistform's set is layer 4 and the text change layer 3
    (CR 613.1c–d), so the set wins whichever came first: an Elf by its own
    ability stays an Elf after its "Illusion" is rewritten Goblin, and once
    cleanup ends the set it is the Goblin its text now says. A set made after
    the text change wins the same way."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"])
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    assert game.activate_permanent_ability(0, "Mistform Dreamer").supported
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g5_resolve_stack(game)

    _w1g5_evolve(game, dreamer, "illusion", "goblin")
    assert dreamer.effective_card.type_line == "Creature — Goblin"
    assert _w1g5_types(dreamer) == {"elf"}
    game.resolve_cleanup_step(0)
    assert _w1g5_types(dreamer) == {"goblin"}

    assert game.activate_permanent_ability(0, "Mistform Dreamer").supported
    assert game.confirm_creature_type_choice(0, "wizard")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(dreamer) == {"wizard"}


def test_w1g5_artificial_evolution_for_a_seat_nobody_asks(set_pool, catalog_by_name):
    """The defaults: the word replaced is the first creature type written on
    the target (its type line), and its replacement the caster's own
    commonest type that is neither Wall nor that word — so the opponent's
    Elvish Champion becomes a lord of seat 0's Goblins."""
    game = _w1g5_table(set_pool, ["Artificial Evolution"], interactive=())
    champion = _w1g5_put(game, 1, catalog_by_name["Elvish Champion"])
    kings = [_w1g5_put(game, 0, catalog_by_name["Goblin King"]) for _ in range(2)]
    assert game.queue_from_hand(
        0, "Artificial Evolution", target_permanent_ids=[champion.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert _w1g5_types(champion) == {"goblin"}
    assert (
        "Artificial Evolution changed elf to goblin in Elvish Champion's text"
        in game.log
    )
    # Each King: 2/2, +1/+1 from the other King, +1/+1 from the Champion.
    assert kings[0].effective_power == 4

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
