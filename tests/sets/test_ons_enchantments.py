"""Onslaught enchantments, Auras included.

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

# A face-down creature leaving the battlefield and coming back (CR 708.9,
# CR 400.7) through Astral Slide's exile-and-return, with the creature cast
# face down by morph rather than put face down by Illusionary Mask (W1G3's
# section drives the Mask's).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.face_down import is_face_down as _w1g2_is_face_down
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def test_w1g2_astral_slide_exiles_a_morph_creature_face_up_and_it_returns_face_up(set_pool):
    """Astral Slide (2008-08-01): "If a face-down card is exiled, it turns
    face-up and remains face-up when it returns to the battlefield." A Krosan
    Colossus cast face down for {3} is exiled by the Slide's trigger — exile
    holds the Colossus, revealed (CR 708.9), and the log names it only then —
    and the next end step returns it a new, face-up 9/9 (CR 400.7)."""
    ons = set_pool("ONS")
    alice = _W1G2PlayerState(
        name="Alice", hand=[ons["Krosan Colossus"]], library=[ons["Plains"]] * 5,
    )
    bob = _W1G2PlayerState(name="Bob", hand=[ons["Lay Waste"]], library=[ons["Plains"]] * 5)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    slide = _W1G2Permanent(card=ons["Astral Slide"])
    game._put_permanent_onto_battlefield(1, slide, None)
    game._sync_control()

    assert game.queue_from_hand(0, "Krosan Colossus", alternative_cost=True).supported
    _w1g2_resolve_stack(game)
    (hidden,) = game.controlled_by(0)
    assert _w1g2_is_face_down(hidden)
    assert not any("Krosan Colossus" in line for line in game.log)

    # Bob cycles Lay Waste; the Slide's "you may exile target creature" aims
    # at the face-down Colossus (its only creature on the table).
    assert game.activate_from_hand(1, "Lay Waste").supported
    assert game.stack[-1].card.name == "Astral Slide"
    assert game.resolve_top_of_stack()
    for seat in (0, 1):
        offer = game.pending_choice_of("optional_pay", seat)
        if offer is not None:
            assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()
    assert not game.is_on_battlefield(hidden)
    assert [c.name for c in alice.exile] == ["Krosan Colossus"]
    assert any("it is Krosan Colossus" in line for line in game.log)
    _w1g2_resolve_stack(game)

    game.resolve_end_step(0)
    _w1g2_resolve_stack(game)
    (back,) = game.controlled_by(0)
    assert back.permanent_id != hidden.permanent_id
    assert not _w1g2_is_face_down(back) and back.card is ons["Krosan Colossus"]
    assert (back.effective_power, back.effective_toughness) == (9, 9)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: "whenever a player cycles a card" (CR 702.29a) -------------------
#
# A permanent watching every seat's cycling, announced where a cycling
# ability's discard cost is paid (`CardActivationMixin._announce_cycle`) and
# collected off the battlefield by the event bus. Each test cycles a plain
# cycling card (Lay Waste) with the watcher in play, resolves the watcher's
# trigger alone — the cycling ability is under it, so nothing is drawn yet —
# reads the board, then lets the draw resolve.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=5):
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
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cycle_and_resolve_watcher(game, seat, name, watcher, *, accept=True):
    """*seat* cycles *name*; *watcher*'s trigger is on top of the cycling
    ability; resolve it (answering its "you may") and leave the draw."""
    assert game.activate_from_hand(seat, name).supported
    assert game.stack[-1].card.name == watcher
    assert game.stack[-1].ability_text.startswith("Whenever a player cycles a card")
    assert game.stack[-2].ability_text.endswith("Discard this card: Draw a card.")
    assert game.resolve_top_of_stack()
    for seat_index in range(len(game.players)):
        offer = game.pending_choice_of("optional_pay", seat_index)
        if offer is not None:
            assert game._resolve_optional_pay(offer, accept, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1, "the cycling ability is still waiting to draw"


def test_w1g3_astral_slide_exiles_a_creature_until_the_next_end_step(set_pool):
    """"…you may exile target creature. If you do, return that card to the
    battlefield under its owner's control at the beginning of the next end
    step." It comes back a new object (CR 400.7)."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste")
    _w1g3_put(game, 0, set_pool("ONS")["Astral Slide"])
    target = _w1g3_put(game, 1, _mk_creature_card("Blocker", 2, 4))

    _w1g3_cycle_and_resolve_watcher(game, 0, "Lay Waste", "Astral Slide")
    assert not game.is_on_battlefield(target)
    assert [c.name for c in bob.exile] == ["Blocker"]
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]

    game.resolve_end_step(0)
    resolve_stack(game)
    assert bob.exile == []
    (back,) = [p for p in game.controlled_by(1) if p.card.name == "Blocker"]
    assert back.permanent_id != target.permanent_id


def test_w1g3_astral_slide_on_a_cycle_in_the_end_step_waits_a_turn(set_pool):
    """2004-10-04: "If a player cycles a card during the end step, the
    creature that is exiled won't come back until the end of the next turn."
    The end step's beginning has passed, so the next one is next turn's."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste")
    _w1g3_put(game, 0, set_pool("ONS")["Astral Slide"])
    _w1g3_put(game, 1, _mk_creature_card("Blocker", 2, 4))
    game.resolve_end_step(0)
    resolve_stack(game)

    _w1g3_cycle_and_resolve_watcher(game, 0, "Lay Waste", "Astral Slide")
    resolve_stack(game)
    game.resolve_cleanup_step(0)
    assert [c.name for c in bob.exile] == ["Blocker"], "still gone this turn"

    game.active_player_index = 1
    game.resolve_end_step(1)
    resolve_stack(game)
    assert bob.exile == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Blocker"]


def test_w1g3_astral_slide_sees_an_opponents_cycle_too(set_pool):
    game, alice, bob = _w1g3_table(set_pool, opponent_hand=["Lay Waste"])
    _w1g3_put(game, 0, set_pool("ONS")["Astral Slide"])
    theirs = _w1g3_put(game, 1, _mk_creature_card("Attacker", 3, 3))

    _w1g3_cycle_and_resolve_watcher(game, 1, "Lay Waste", "Astral Slide")
    assert not game.is_on_battlefield(theirs)
    resolve_stack(game)
    assert [c.name for c in bob.hand] == ["Plains"]


def _w1g3_shipped(name):
    found = getattr(_w1g3_shipped, "_cache", None)
    if found is None:
        found = {card.name: card for card in load_catalog()}
        _w1g3_shipped._cache = found
    return found[name]


# Astral Slide 2008-08-01: "If a face-down card is exiled, it turns face-up
# and remains face-up when it returns to the battlefield" (CR 708.9). Was a
# strict xfail until W1G1's face-down model sent the real card wherever a
# face-down permanent goes; W1G2 drove it and removed the marker.
def test_w1g3_astral_slide_exiles_a_face_down_creature_face_up(set_pool):
    grizzly = _w1g3_shipped("Grizzly Bears")
    mask = _w1g3_shipped("Illusionary Mask")
    game, alice, bob = _w1g3_table(set_pool, opponent_hand=["Lay Waste"])
    alice.hand.append(grizzly)
    _w1g3_put(game, 0, mask)
    _w1g3_put(game, 1, set_pool("ONS")["Astral Slide"])
    assert game.activate_permanent_ability(
        0, "Illusionary Mask", target_player_index=1, x_value=2
    ).supported
    if game.pending_face_down_cast is not None:
        assert game.confirm_face_down_cast(0, 0)
    resolve_stack(game)
    (face_down,) = [p for p in game.controlled_by(0) if p.metadata.get("face_down")]

    _w1g3_cycle_and_resolve_watcher(game, 1, "Lay Waste", "Astral Slide")
    assert not game.is_on_battlefield(face_down)
    assert alice.exile == [grizzly], [(c.name, c.oracle_text) for c in alice.exile]
    resolve_stack(game)
    game.resolve_end_step(0)
    resolve_stack(game)
    (back,) = [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]
    assert back.card is grizzly and not back.metadata.get("face_down")


def test_w1g3_withering_hex_counts_every_cycle_on_its_creature(set_pool):
    """"Whenever a player cycles a card, put a plague counter on this Aura." /
    "Enchanted creature gets -1/-1 for each plague counter on this Aura." Two
    cycles, either player's, kill a 2/2."""
    game, alice, bob = _w1g3_table(
        set_pool, "Withering Hex", "Lay Waste", opponent_hand=["Swat"],
    )
    bear = _w1g3_put(game, 1, _mk_creature_card("Bear", 2, 2))
    assert game.cast_from_hand(
        0, "Withering Hex", target_permanent_ids=[bear.permanent_id]
    ).supported
    resolve_stack(game)
    (hex_,) = [p for p in game.controlled_by(0) if p.card.name == "Withering Hex"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    _w1g3_cycle_and_resolve_watcher(game, 0, "Lay Waste", "Withering Hex")
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)
    resolve_stack(game)

    _w1g3_cycle_and_resolve_watcher(game, 1, "Swat", "Withering Hex")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(bear)
    assert not game.is_on_battlefield(hex_), "CR 704.5m: its creature is gone"
    resolve_stack(game)


def test_w1g3_lightning_rift_pays_1_for_2_damage(set_pool):
    """"…you may pay {1}. If you do, this enchantment deals 2 damage to any
    target." 2022-12-08: the target is chosen as the trigger goes on the stack,
    the {1} as it resolves — here off an untapped Mountain."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste")
    _w1g3_put(game, 0, set_pool("ONS")["Lightning Rift"])
    mountain = _w1g3_put(game, 0, set_pool("ONS")["Mountain"])

    assert game.activate_from_hand(0, "Lay Waste").supported
    rift = game.stack[-1]
    assert rift.card.name == "Lightning Rift" and rift.target_player_index == 1
    assert not mountain.tapped, "nothing is paid as it goes on the stack"
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer.data["cost"] == {"generic": 1}
    assert game._resolve_optional_pay(offer, True, None)
    assert mountain.tapped
    assert bob.life == 18
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_lightning_rift_with_no_mana_deals_nothing(set_pool):
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste")
    game.enforce_mana_costs = True
    _w1g3_put(game, 0, set_pool("ONS")["Lightning Rift"])
    alice.mana_pool["C"] = 2

    assert game.activate_from_hand(0, "Lay Waste").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert bob.life == 20
    assert [c.name for c in alice.hand] == ["Plains"]


def test_w1g3_invigorating_boon_puts_a_counter_on_a_cycle(set_pool):
    game, alice, _bob = _w1g3_table(set_pool, "Lay Waste")
    _w1g3_put(game, 0, set_pool("ONS")["Invigorating Boon"])
    bear = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))

    _w1g3_cycle_and_resolve_watcher(game, 0, "Lay Waste", "Invigorating Boon")
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    resolve_stack(game)
    game.resolve_cleanup_step(0)
    assert (bear.effective_power, bear.effective_toughness) == (3, 3), "a counter stays"


def test_w1g3_improvised_armor_cycles_from_hand(set_pool):
    """The Aura prints cycling and nothing triggering on it: from a hand it is
    "{3}, Discard this card: Draw a card", and attached it has no way to
    reach that ability."""
    card = set_pool("ONS")["Improvised Armor"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1
    assert usable_activated_abilities(program) == []

    game, alice, _bob = _w1g3_table(set_pool, "Improvised Armor")
    game.enforce_mana_costs = True
    alice.mana_pool["C"] = 3
    assert game.activate_from_hand(0, "Improvised Armor").supported
    resolve_stack(game)
    assert not any(alice.mana_pool.values())
    assert [c.name for c in alice.graveyard] == ["Improvised Armor"]
    assert [c.name for c in alice.hand] == ["Plains"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import _damage_dealt as _w1g4_damage_dealt
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_creature(name, subtype):
    return _W1G4Permanent(card=_w1g4_mk_card(name, "{2}", f"Creature - {subtype}", ""))


def _w1g4_enter(set_pool, name, *, mine=(), theirs=(), interactive=()):
    """*name* cast by P1 and resolved, P1 holding *mine* and P2 *theirs*."""
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[set_pool("ONS")[name]], battlefield=list(mine)),
        _W1G4PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    assert game.cast_from_hand(0, name).supported
    _w1g4_resolve_stack(game)
    source = next(perm for perm in game.controlled_by(0) if perm.card.name == name)
    return game, source


def _w1g4_two_tribes():
    """P1's two Elves against P2's three Goblins — whose type a default names
    is then visible from which side it is."""
    return (
        [_w1g4_creature("My Elf A", "Elf"), _w1g4_creature("My Elf B", "Elf")],
        [_w1g4_creature(f"Their Goblin {n}", "Goblin") for n in range(3)],
    )


# --- Circle of Solace --------------------------------------------------------------


def test_w1g4_circle_of_solace_prevents_the_next_damage_from_the_chosen_type(set_pool):
    """"{1}{W}: The next time a creature of the chosen type would deal damage to
    you this turn, prevent that damage." The line compiled to no instruction
    (hollow) at ingest. Now: a Goblin's damage is prevented whole (CR 615.8),
    an Elf's is not, and the shield is spent by the first Goblin — the second
    one's damage goes through."""
    goblin_a = _w1g4_creature("Goblin A", "Goblin")
    goblin_b = _w1g4_creature("Goblin B", "Goblin")
    elf = _w1g4_creature("Elf", "Elf")
    game, circle = _w1g4_enter(
        set_pool, "Circle of Solace", theirs=[goblin_a, goblin_b, elf],
    )
    assert circle.metadata["chosen_creature_type"] == "goblin"
    assert game.activate_permanent_ability(0, "Circle of Solace").supported
    _w1g4_resolve_stack(game)

    me = game.players[0]
    assert _w1g4_damage_dealt(game, me, 3, source=elf) == 3
    assert _w1g4_damage_dealt(game, me, 3, source=goblin_a) == 0
    assert _w1g4_damage_dealt(game, me, 3, source=goblin_b) == 3


def test_w1g4_circle_of_solace_chooses_nothing_at_activation(set_pool):
    """The source is a class, not "a source of your choice": the activation
    derives no picker, so the client sends a bare activation the engine
    accepts."""
    ability = _w1g4_compile(set_pool("ONS")["Circle of Solace"]).activated_abilities[0]
    assert ability.supported
    assert _w1g4_activation_spec(ability) is None


def test_w1g4_circle_of_solace_reads_the_type_its_controller_named(set_pool):
    """An interactive controller names the type as the Circle enters
    (CR 614.1c); the shield answers to *that* type, read when the ability
    resolves."""
    elf = _w1g4_creature("Elf", "Elf")
    goblin = _w1g4_creature("Goblin", "Goblin")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[set_pool("ONS")["Circle of Solace"]]),
        _W1G4PlayerState(name="P2", battlefield=[elf, goblin]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Circle of Solace")
    assert game.confirm_enter_choice(0, creature_type="elf")
    _w1g4_resolve_stack(game)
    game.activate_permanent_ability(0, "Circle of Solace")
    _w1g4_resolve_stack(game)

    me = game.players[0]
    assert _w1g4_damage_dealt(game, me, 2, source=goblin) == 2
    assert _w1g4_damage_dealt(game, me, 2, source=elf) == 0


# --- the entry choosers' defaults: whose type a gift names ---------------------


def test_w1g4_cover_of_darkness_gives_fear_to_its_controllers_type(set_pool):
    """"Creatures of the chosen type have fear." A gift, so the default names
    the controller's own type. It named the opponents' commonest type at
    ingest and so gave *their* creatures fear."""
    mine, theirs = _w1g4_two_tribes()
    game, cover = _w1g4_enter(set_pool, "Cover of Darkness", mine=mine, theirs=theirs)
    assert cover.metadata["chosen_creature_type"] == "elf"
    assert game._has_keyword(mine[0], "fear")
    assert not game._has_keyword(theirs[0], "fear")


def test_w1g4_steely_resolve_gives_shroud_to_its_controllers_type(set_pool):
    """"Creatures of the chosen type have shroud." The same gift, the same
    default — and the Goblins stay targetable."""
    mine, theirs = _w1g4_two_tribes()
    game, resolve = _w1g4_enter(set_pool, "Steely Resolve", mine=mine, theirs=theirs)
    assert resolve.metadata["chosen_creature_type"] == "elf"
    assert game._has_keyword(mine[1], "shroud")
    assert not game._has_keyword(theirs[0], "shroud")


def test_w1g4_shared_triumph_pumps_every_creature_of_the_chosen_type(set_pool):
    """"Creatures of the chosen type get +1/+1." Every creature of the type,
    whoever controls it — an opponent's Elf too — and no other."""
    mine, theirs = _w1g4_two_tribes()
    their_elf = _w1g4_creature("Their Elf", "Elf")
    game, triumph = _w1g4_enter(
        set_pool, "Shared Triumph", mine=mine, theirs=[*theirs, their_elf],
    )
    assert triumph.metadata["chosen_creature_type"] == "elf"
    assert (mine[0].effective_power, mine[0].effective_toughness) == (3, 3)
    assert (their_elf.effective_power, their_elf.effective_toughness) == (3, 3)
    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (2, 2)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: Mistform Mask (CR 303.4, CR 205.1a) ------------------------------
from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.aura_attachment import attach_aura as _w1g5_attach_aura
from engine.layer_bridge import computed_types as _w1g5_computed_types
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_masked(set_pool, catalog_by_name, *, host_seat=0, interactive=(0,)):
    """Mistform Mask (seat 0's) on a Grizzly Bears controlled by *host_seat*,
    with an Elvish Champion on seat 1's side."""
    game = _W1G5Game(players=[_W1G5PlayerState(name="A"), _W1G5PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    bears = _W1G5Permanent(card=catalog_by_name["Grizzly Bears"])
    mask = _W1G5Permanent(card=set_pool("ONS")["Mistform Mask"])
    champion = _W1G5Permanent(card=catalog_by_name["Elvish Champion"])
    game.players[host_seat].battlefield.append(bears)
    game.players[0].battlefield.append(mask)
    game.players[1].battlefield.append(champion)
    _w1g5_attach_aura(mask, bears)
    game._recompute_continuous_effects()
    return game, mask, bears


def test_w1g5_mistform_mask_sets_the_enchanted_creatures_type(set_pool, catalog_by_name):
    """"{1}: Enchanted creature becomes the creature type of your choice until
    end of turn." The Aura's host, which nobody targets (no picker): the Bears
    made an Elf are no longer a Bear and take Elvish Champion's +1/+1 and
    forestwalk; cleanup ends it."""
    game, mask, bears = _w1g5_masked(set_pool, catalog_by_name)
    ability = _w1g5_compile(mask.card).activated_abilities[0]
    assert _w1g5_activation_spec(ability) is None

    assert game.activate_permanent_ability(0, "Mistform Mask").supported
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g5_resolve_stack(game)
    assert set(_w1g5_computed_types(bears)[1]) == {"elf"}
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert game._has_keyword(bears, "forestwalk")
    assert "Grizzly Bears became an Elf until end of turn (Mistform Mask)" in game.log

    game.resolve_cleanup_step(0)
    assert set(_w1g5_computed_types(bears)[1]) == {"bear"}
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g5_mistform_mask_on_an_opponents_creature_is_its_controllers_choice(
    set_pool, catalog_by_name,
):
    """"Your choice" is the ability's controller's (CR 109.5) — the Mask's, not
    the creature's: the prompt is armed for seat 0 though the Bears are seat
    1's."""
    game, _mask, bears = _w1g5_masked(set_pool, catalog_by_name, host_seat=1)
    assert game.activate_permanent_ability(0, "Mistform Mask").supported
    (owed,) = game.pending_choices
    assert (owed.kind, owed.player_index) == ("creature_type_choice", 0)
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(game)
    assert set(_w1g5_computed_types(bears)[1]) == {"goblin"}


def test_w1g5_mistform_mask_destroyed_in_response_still_changes_its_host(
    set_pool, catalog_by_name,
):
    """The ability exists apart from its source (CR 113.7a): the Mask gone in
    response, the creature it was on — last known — still becomes the type."""
    game, mask, bears = _w1g5_masked(set_pool, catalog_by_name, interactive=())
    assert game.queue_permanent_ability(0, "Mistform Mask").supported
    game.remove_from_battlefield(mask)
    _w1g5_resolve_stack(game)
    # Nobody asked: the default joins seat 0's other creatures — it has none
    # but the Bears, so nothing is chosen and nothing changes…
    assert set(_w1g5_computed_types(bears)[1]) == {"bear"}

    game, mask, bears = _w1g5_masked(set_pool, catalog_by_name)
    assert game.queue_permanent_ability(0, "Mistform Mask").supported
    game.remove_from_battlefield(mask)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_creature_type_choice(0, "zombie")
    _w1g5_resolve_stack(game)
    # …and asked, the answer lands on the host the Mask was last attached to.
    assert set(_w1g5_computed_types(bears)[1]) == {"zombie"}

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# "Share a creature type" (CR 205.3m) — the Crowns' sacrifice ability.
# "Sacrifice this Aura: Enchanted creature and other creatures that share a
# creature type with it …": the enchanted creature as it was when the cost took
# the Aura (CR 608.2h), and "other" measured from it, not from the Aura.

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.face_down import is_face_down as _w1g6_is_face_down
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("ONS", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g6_table(set_pool, *, hand=()):
    me = _W1G6PlayerState(
        name="Me", hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Plains")] * 6,
    )
    opp = _W1G6PlayerState(name="Opp", library=[_w1g6_card(set_pool, "Forest")] * 6)
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _w1g6_put(game, set_pool, seat, name):
    perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_enchant(game, crown, host):
    """Cast *crown* from seat 0's hand onto *host* and resolve it."""
    game._recompute_continuous_effects()
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.queue_from_hand(0, crown, target_permanent_ids=[host.permanent_id]).supported
    _w1g6_resolve_stack(game)
    aura = next(p for p in game.all_permanents() if p.card.name == crown)
    assert aura.metadata.get("attached_to") is host
    return aura


def _w1g6_sacrifice(game, crown, aura):
    assert game.activate_permanent_ability(0, crown).supported
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(aura), game.log
    assert crown in [card.name for card in game.players[0].graveyard]


def _w1g6_tribal_board(game, set_pool):
    """An Elf Warrior to enchant; an Elf Druid (shares Elf) and a Human Soldier
    (shares nothing) beside it; a Goblin Warrior (shares Warrior) and a Bear
    (shares nothing) across the table."""
    return {
        "host": _w1g6_put(game, set_pool, 0, "Elvish Warrior"),
        "elf": _w1g6_put(game, set_pool, 0, "Wirewood Elf"),
        "human": _w1g6_put(game, set_pool, 0, "Glory Seeker"),
        "goblin": _w1g6_put(game, set_pool, 1, "Goblin Sky Raider"),
        "bear": _w1g6_put(game, set_pool, 1, "Grizzly Bears"),
    }


def _w1g6_pt(perm):
    return perm.effective_power, perm.effective_toughness


def test_w1g6_crown_of_vigor_pumps_the_host_once_and_every_creature_sharing_a_type(set_pool):
    """Crown of Vigor's sacrifice: the Elf Warrior gets +1/+1 **once** — the
    "other" is other than it, so it is not counted again among the creatures
    sharing its types — and so do the Elf Druid (Elf) and the opponent's
    Goblin Warrior (Warrior). The Human Soldier and the Bear share nothing."""
    game = _w1g6_table(set_pool, hand=["Crown of Vigor"])
    board = _w1g6_tribal_board(game, set_pool)
    before = {key: _w1g6_pt(perm) for key, perm in board.items()}
    aura = _w1g6_enchant(game, "Crown of Vigor", board["host"])
    assert _w1g6_pt(board["host"]) == (before["host"][0] + 1, before["host"][1] + 1)

    _w1g6_sacrifice(game, "Crown of Vigor", aura)

    for key in ("host", "elf", "goblin"):
        power, toughness = before[key]
        assert _w1g6_pt(board[key]) == (power + 1, toughness + 1), (key, game.log)
    for key in ("human", "bear"):
        assert _w1g6_pt(board[key]) == before[key], (key, game.log)

    game.resolve_cleanup_step(0)
    assert {key: _w1g6_pt(perm) for key, perm in board.items()} == before


def test_w1g6_crown_of_ascension_gives_flying_to_the_host_and_its_kin(set_pool):
    """"…gain flying until end of turn." The host (no longer flying by the
    Aura's static, which left with it) and the Elf Druid gain it; the Human
    Soldier and the Bear do not."""
    game = _w1g6_table(set_pool, hand=["Crown of Ascension"])
    board = _w1g6_tribal_board(game, set_pool)
    aura = _w1g6_enchant(game, "Crown of Ascension", board["host"])
    assert game._has_keyword(board["host"], "flying")
    assert not game._has_keyword(board["elf"], "flying")

    _w1g6_sacrifice(game, "Crown of Ascension", aura)

    for key in ("host", "elf"):
        assert game._has_keyword(board[key], "flying"), (key, game.log)
    for key in ("human", "bear"):
        assert not game._has_keyword(board[key], "flying"), (key, game.log)

    game.resolve_cleanup_step(0)
    assert not game._has_keyword(board["host"], "flying")
    assert not game._has_keyword(board["elf"], "flying")


def test_w1g6_crown_of_awe_gives_both_protections_to_the_host_and_its_kin(set_pool):
    """"…gain protection from black and from red until end of turn." Two
    qualities, on the host, the Elf Druid and the Goblin Warrior alike."""
    game = _w1g6_table(set_pool, hand=["Crown of Awe"])
    board = _w1g6_tribal_board(game, set_pool)
    aura = _w1g6_enchant(game, "Crown of Awe", board["host"])

    _w1g6_sacrifice(game, "Crown of Awe", aura)

    expected = {("color", "B"), ("color", "R")}
    for key in ("host", "elf", "goblin"):
        assert expected <= set(game._protection_qualities(board[key])), (key, game.log)
    for key in ("human", "bear"):
        assert not set(game._protection_qualities(board[key])) & expected, key


def test_w1g6_crown_of_fury_pumps_and_grants_first_strike_to_one_set(set_pool):
    """"…get +1/+0 and gain first strike until end of turn." Both halves of
    the sentence reach the same set: each sharer is +1/+0 **and** has first
    strike, and nobody else has either."""
    game = _w1g6_table(set_pool, hand=["Crown of Fury"])
    board = _w1g6_tribal_board(game, set_pool)
    before = {key: _w1g6_pt(perm) for key, perm in board.items()}
    aura = _w1g6_enchant(game, "Crown of Fury", board["host"])

    _w1g6_sacrifice(game, "Crown of Fury", aura)

    for key in ("host", "elf", "goblin"):
        power, toughness = before[key]
        assert _w1g6_pt(board[key]) == (power + 1, toughness), (key, game.log)
        assert game._has_keyword(board[key], "first strike"), key
    for key in ("human", "bear"):
        assert _w1g6_pt(board[key]) == before[key], key
        assert not game._has_keyword(board[key], "first strike"), key


def test_w1g6_crown_of_suspicion_on_an_opponents_goblin_kills_its_one_toughness_kin(set_pool):
    """Crown of Suspicion on the opponent's Goblin Warrior: its +2/-1 reaches
    every creature sharing Goblin or Warrior, whoever controls it. The Skirk
    Prospector (a 1/1 Goblin) is put into its owner's graveyard by the
    state-based check; the caster's own Elf Warrior shares Warrior and becomes
    a 4/2; the Human Soldier is untouched."""
    game = _w1g6_table(set_pool, hand=["Crown of Suspicion"])
    host = _w1g6_put(game, set_pool, 1, "Goblin Sky Raider")
    prospector = _w1g6_put(game, set_pool, 1, "Skirk Prospector")
    warrior = _w1g6_put(game, set_pool, 0, "Elvish Warrior")
    human = _w1g6_put(game, set_pool, 0, "Glory Seeker")
    aura = _w1g6_enchant(game, "Crown of Suspicion", host)
    assert _w1g6_pt(host) == (3, 1)

    _w1g6_sacrifice(game, "Crown of Suspicion", aura)
    game._settle()

    assert _w1g6_pt(host) == (3, 1), game.log
    assert not game.is_on_battlefield(prospector), game.log
    assert "Skirk Prospector" in [card.name for card in game.players[1].graveyard]
    assert _w1g6_pt(warrior) == (4, 2)
    assert _w1g6_pt(human) == (2, 2)


def test_w1g6_a_crown_on_a_face_down_creature_reaches_only_that_creature(set_pool):
    """A face-down creature has no creature types (CR 708.2), so it shares one
    with nothing — not with the creatures on the board and not with another
    face-down creature. The sacrifice pumps the host alone."""
    game = _w1g6_table(set_pool, hand=["Crown of Vigor", "Krosan Colossus", "Krosan Colossus"])
    game.start_turn(0)
    game._close_current_priority_step()
    for _ in range(2):
        assert game.queue_from_hand(0, "Krosan Colossus", alternative_cost=True).supported
        _w1g6_resolve_stack(game)
    face_down = [perm for perm in game.all_permanents() if _w1g6_is_face_down(perm)]
    assert len(face_down) == 2
    host, other = face_down
    elf = _w1g6_put(game, set_pool, 0, "Wirewood Elf")
    aura = _w1g6_enchant(game, "Crown of Vigor", host)

    _w1g6_sacrifice(game, "Crown of Vigor", aura)

    assert _w1g6_pt(host) == (3, 3), game.log
    assert _w1g6_pt(other) == (2, 2), game.log
    assert _w1g6_pt(elf) == (1, 2), game.log


# -- Mana Echoes ---------------------------------------------------------------
# "Whenever a creature enters, you may add an amount of {C} equal to the number
# of creatures you control that share a creature type with it."


def _w1g6_settle(game):
    """Resolve the stack and take every owed default — what a headless seat's
    loop does between actions."""
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)


def _w1g6_echoes_table(set_pool, *, hand=(), opp_hand=(), mine=(), theirs=()):
    game = _w1g6_table(set_pool, hand=hand)
    game.players[1].hand.extend(_w1g6_card(set_pool, n) for n in opp_hand)
    _w1g6_put(game, set_pool, 0, "Mana Echoes")
    board = {name: _w1g6_put(game, set_pool, 0, name) for name in mine}
    board.update({name: _w1g6_put(game, set_pool, 1, name) for name in theirs})
    # The puts above are entries too; their triggers are not this test's.
    game.stack.clear()
    game.pending_choices.clear()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board


def _w1g6_colorless(game, seat=0):
    return game.players[seat].mana_pool.get("C", 0)


def test_w1g6_mana_echoes_counts_the_creatures_that_share_a_type_with_the_one_that_entered(set_pool):
    """An Elf Warrior enters under Mana Echoes. It shares a type with itself
    (the ruling of 2020-08-07: "…so Mana Echoes usually adds at least {C}"),
    with the Goblin Warrior and with the Elf Druid — and the other Elf Warrior
    counts **once**, though it shares both types ("Mana Echoes counts the
    number of creatures that share a type, not how many types they share").
    The Human Soldier shares nothing: {C}{C}{C}{C}."""
    game, _board = _w1g6_echoes_table(
        set_pool, hand=["Elvish Warrior"],
        mine=["Goblin Sky Raider", "Wirewood Elf", "Elvish Vanguard", "Glory Seeker"],
    )
    assert game.queue_from_hand(0, "Elvish Warrior").supported
    _w1g6_settle(game)

    assert _w1g6_colorless(game) == 4, game.log
    assert "Mana Echoes produced {C}{C}{C}{C}" in game.log


def test_w1g6_mana_echoes_counts_only_your_creatures_when_an_opponents_enters(set_pool):
    """"…the number of creatures **you** control." The opponent's Goblin
    Warrior enters: it is not one of Mana Echoes' controller's creatures, so it
    does not count itself, and neither do the opponent's other Goblins — only
    the controller's Elf Warrior (Warrior) and Goblin (Goblin): {C}{C}. The
    opponent's pool is untouched."""
    game, _board = _w1g6_echoes_table(
        set_pool, opp_hand=["Goblin Piledriver"],
        mine=["Elvish Warrior", "Skirk Prospector", "Glory Seeker"],
        theirs=["Goblin Sky Raider"],
    )
    assert game.queue_from_hand(1, "Goblin Piledriver").supported
    _w1g6_settle(game)

    assert _w1g6_colorless(game, 0) == 2, game.log
    assert _w1g6_colorless(game, 1) == 0


def test_w1g6_mana_echoes_counts_as_it_resolves_after_a_response(set_pool):
    """Mana Echoes (2020-08-07): "The amount of mana to add is determined only
    as the triggered ability of Mana Echoes resolves. The ability isn't a mana
    ability; players may respond to it." The trigger for an entering Elf
    Warrior is on the stack; in response the opponent Shocks the Elf Druid, and
    by resolution only the Elf Warrior itself and the Goblin Warrior are left
    to count: {C}{C}."""
    game, board = _w1g6_echoes_table(
        set_pool, hand=["Elvish Warrior"], opp_hand=["Shock"],
        mine=["Goblin Sky Raider", "Wirewood Elf"],
    )
    assert game.queue_from_hand(0, "Elvish Warrior").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Mana Echoes"], game.stack
    elf = board["Wirewood Elf"]
    assert game.queue_from_hand(
        1, "Shock", target_permanent_ids=[elf.permanent_id],
    ).supported
    assert game.resolve_top_of_stack()
    # CR 704.3: the state-based check a player's priority makes between the
    # two resolutions puts the Elf Druid into its owner's graveyard.
    game._check_between_resolutions()
    assert not game.is_on_battlefield(elf), game.log
    assert [item.card.name for item in game.stack] == ["Mana Echoes"]
    _w1g6_settle(game)

    assert _w1g6_colorless(game) == 2, game.log
    assert "Mana Echoes produced {C}{C}" in game.log


def test_w1g6_mana_echoes_adds_nothing_for_a_face_down_creature(set_pool):
    """A face-down creature has no creature types (CR 708.2), so nothing —
    not even itself — shares one with it, and Mana Echoes adds no mana; the
    Krosan Colossus it really is would have shared Beast with the Ravenous
    Baloth."""
    game, _board = _w1g6_echoes_table(
        set_pool, hand=["Krosan Colossus"], mine=["Ravenous Baloth", "Glory Seeker"],
    )
    assert game.queue_from_hand(0, "Krosan Colossus", alternative_cost=True).supported
    _w1g6_settle(game)

    assert any(_w1g6_is_face_down(p) for p in game.all_permanents())
    assert _w1g6_colorless(game) == 0, game.log


def test_w1g6_a_crown_s_kin_are_still_pumped_after_the_host_dies_in_response(set_pool):
    """Crown of Vigor's sacrifice on the stack; in response the opponent
    destroys the enchanted Elf Warrior. The ability still resolves: "it" is
    the Elf Warrior as it last existed (CR 608.2h), so the Elf Druid and the
    Goblin Warrior that shared its types get +1/+1, and the Human Soldier does
    not."""
    game = _w1g6_table(set_pool, hand=["Crown of Vigor"])
    board = _w1g6_tribal_board(game, set_pool)
    game.players[1].hand.append(_w1g6_card(set_pool, "Swat"))
    before = {key: _w1g6_pt(perm) for key, perm in board.items()}
    aura = _w1g6_enchant(game, "Crown of Vigor", board["host"])
    assert game.queue_permanent_ability(0, "Crown of Vigor").supported
    assert not game.is_on_battlefield(aura)
    assert game.queue_from_hand(
        1, "Swat", target_permanent_ids=[board["host"].permanent_id],
    ).supported
    assert game.resolve_top_of_stack()
    game._check_between_resolutions()
    assert not game.is_on_battlefield(board["host"]), game.log
    _w1g6_resolve_stack(game)

    for key in ("elf", "goblin"):
        power, toughness = before[key]
        assert _w1g6_pt(board[key]) == (power + 1, toughness + 1), (key, game.log)
    assert _w1g6_pt(board["human"]) == before["human"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.type_changes import gain_types as _w1g7_gain_types
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_perm(pool, name):
    return _w1g7_nosick(_w1g7_Permanent(card=pool[name]))


def _w1g7_game(mine=(), theirs=(), *, p1=None, p2=None):
    one = _w1g7_PlayerState(name="P1", battlefield=list(mine), **(p1 or {}))
    two = _w1g7_PlayerState(name="P2", battlefield=list(theirs), **(p2 or {}))
    game = _w1g7_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two

from engine.aura_attachment import attach_aura as _w1g7_attach_aura


def test_w1g7_elvish_guidance_adds_a_green_per_elf(set_pool):
    """"Whenever enchanted land is tapped for mana, its controller adds an
    additional {G} for each Elf on the battlefield." Counted as the land is
    tapped: both sides' Elves, not a Goblin, and a Goblin that became an Elf."""
    pool = set_pool("ONS")
    forest = _w1g7_perm(pool, "Forest")
    guidance = _w1g7_perm(pool, "Elvish Guidance")
    goblin = _w1g7_perm(pool, "Skirk Prospector")
    game, p1, _p2 = _w1g7_game(
        [forest, guidance, _w1g7_perm(pool, "Wirewood Elf"), goblin],
        [_w1g7_perm(pool, "Wellwisher")],
    )
    _w1g7_attach_aura(guidance, forest)
    game._settle()
    assert game.tap_land_for_mana(0, "Forest")
    assert p1.mana_pool.get("G") == 3

    forest.tapped = False
    p1.mana_pool.clear()
    _w1g7_gain_types(goblin, subtypes=("elf",))
    game._recompute_continuous_effects()
    assert game.tap_land_for_mana(0, "Forest")
    assert p1.mana_pool.get("G") == 4


def test_w1g7_elvish_guidance_with_no_elf_adds_nothing_extra(set_pool):
    pool = set_pool("ONS")
    forest = _w1g7_perm(pool, "Forest")
    guidance = _w1g7_perm(pool, "Elvish Guidance")
    game, p1, _p2 = _w1g7_game([forest, guidance])
    _w1g7_attach_aura(guidance, forest)
    game._settle()
    assert game.tap_land_for_mana(0, "Forest")
    assert p1.mana_pool.get("G") == 1


def test_w1g7_elvish_guidance_counts_toward_the_planned_payment(set_pool):
    """The payment planner reads the same count the tap seam adds: a Forest
    under the Guidance beside two Elves is three green toward a cost."""
    from engine.board_payment import land_tap_yields

    pool = set_pool("ONS")
    forest = _w1g7_perm(pool, "Forest")
    guidance = _w1g7_perm(pool, "Elvish Guidance")
    game, _p1, _p2 = _w1g7_game(
        [forest, guidance, _w1g7_perm(pool, "Wirewood Elf"),
         _w1g7_perm(pool, "Wellwisher")],
    )
    _w1g7_attach_aura(guidance, forest)
    game._settle()
    (tap,) = land_tap_yields(game, forest)
    assert len(tap.units) + len(tap.extra) == 3

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Lavamancer's Skill: an Aura's quoted grant, and a second one behind "as long
# as enchanted creature is a Wizard". Both are derived from the Aura on every
# read (``aura_grants``), so they leave with it and the second follows the
# host's type through layer 4.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import (
    usable_activated_abilities as _w1g8_usable_abilities,
)
from engine.type_changes import (
    end_type_changes as _w1g8_end_type_changes, gain_types as _w1g8_gain_types,
)
from tests.helpers import _nosick as _w1g8_nosick, resolve_stack as _w1g8_resolve


def _w1g8_pinger_lines(game, host):
    """The host's activated lines that deal damage, as it says them now."""
    game._recompute_continuous_effects()
    return [
        ability.source_line.lower()
        for ability in _w1g8_usable_abilities(_w1g8_compile(host.effective_card))
        if "damage" in ability.source_line.lower()
    ]


def _w1g8_ping(game, host, victim, amount):
    """Activate the host's "deals *amount* damage" line at *victim*."""
    abilities = _w1g8_usable_abilities(_w1g8_compile(host.effective_card))
    (index,) = [
        i for i, ability in enumerate(abilities)
        if f"deals {amount} damage" in ability.source_line.lower()
    ]
    result = game.activate_permanent_ability(
        game.controller_index_of(host), host.card.name, ability_index=index,
        target_player_index=game.controller_index_of(victim),
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve(game)


def test_w1g8_lavamancers_skill_grants_a_one_damage_pinger(set_pool):
    """'Enchanted creature has "{T}: This creature deals 1 damage to target
    creature."' Cast on a creature through the real cast path: its
    controller can activate the line, the damage is the host's, and the
    ability leaves with the Aura."""
    pool = set_pool("ONS")
    seeker = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    victim = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    one = _w1g8_PlayerState(
        name="P1", battlefield=[seeker], hand=[pool["Lavamancer's Skill"]],
    )
    two = _w1g8_PlayerState(name="P2", battlefield=[victim])
    game = _w1g8_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    assert _w1g8_pinger_lines(game, seeker) == []

    result = game.cast_from_hand(
        0, "Lavamancer's Skill", target_permanent_ids=[seeker.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve(game)
    (skill,) = [p for p in game.controlled_by(0) if p.card.name == "Lavamancer's Skill"]
    assert _w1g8_pinger_lines(game, seeker) == [
        "{t}: this creature deals 1 damage to target creature."
    ], "a Glory Seeker is no Wizard: one ability, not two"

    _w1g8_ping(game, seeker, victim, 1)
    assert victim.damage_marked == 1 and seeker.tapped
    assert any("Glory Seeker" in line and "1 damage" in line for line in game.log)

    game.remove_from_battlefield(skill)
    game._settle()
    assert _w1g8_pinger_lines(game, seeker) == []


def test_w1g8_lavamancers_skill_is_claimed_by_the_aura_module(set_pool):
    """Both quoted grants are ``engine/auras.py``'s, each by the reader that
    folds it onto the host — ``aura_granted_ability_lines`` for the plain one,
    ``conditional_ability_lines_for`` for the Wizard one — so the Aura is
    supported by the module that implements it, which is what
    ``test_no_hollow_support``'s pool-wide guard asks once Onslaught ships
    (it reads shipped sets only, so it cannot see this card while measured)."""
    from engine.auras import aura_claim, aura_effect_claim
    from engine.oracle import expand_ability_lines, normalize_creature_line

    card = set_pool("ONS")["Lavamancer's Skill"]
    lines = [
        normalize_creature_line(line)
        for line in expand_ability_lines(card.oracle_text).splitlines()
    ]
    assert aura_claim(lines, card.name) == "auras"
    plain, conditional = lines[1], lines[2]
    assert "aura_granted_ability_lines" in (aura_effect_claim(plain, card.name) or "")
    assert "conditional_ability_lines_for" in (
        aura_effect_claim(conditional, card.name) or ""
    )


def test_w1g8_lavamancers_skill_on_a_wizard_has_both_abilities(set_pool):
    """'As long as enchanted creature is a Wizard, it has "{T}: This creature
    deals 2 damage to target creature."' The ruling (2004-10-04): "If this
    card enchants a Wizard, the Wizard has both abilities and its controller
    can use either one." The criterion is read through layer 4, so a creature
    that *became* a Wizard has the second line — and loses it when the type
    change ends."""
    pool = set_pool("ONS")
    seeker = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    victim = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    one = _w1g8_PlayerState(
        name="P1", battlefield=[seeker], hand=[pool["Lavamancer's Skill"]],
    )
    two = _w1g8_PlayerState(name="P2", battlefield=[victim])
    game = _w1g8_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    _w1g8_gain_types(
        seeker, subtypes=["wizard"], source="test", duration="until_end_of_turn",
        replaces_creature_types=True,
    )
    assert game.cast_from_hand(
        0, "Lavamancer's Skill", target_permanent_ids=[seeker.permanent_id],
    ).supported
    _w1g8_resolve(game)
    assert sorted(_w1g8_pinger_lines(game, seeker)) == [
        "{t}: this creature deals 1 damage to target creature.",
        "{t}: this creature deals 2 damage to target creature.",
    ]

    _w1g8_ping(game, seeker, victim, 2)
    assert not game.is_on_battlefield(victim), "2 damage kills the 2/2"

    # The type change ends (the cleanup step's sweep, by its duration): no
    # longer a Wizard, one line left.
    _w1g8_end_type_changes(
        seeker, lambda record: record.get("duration") == "until_end_of_turn"
    )
    assert not seeker.has_type("wizard")
    assert _w1g8_pinger_lines(game, seeker) == [
        "{t}: this creature deals 1 damage to target creature."
    ]


# --- The family's Auras that compiled on arrival and had never been run.


def _w1g8_aura_game(pool, mine=(), theirs=(), *, hand=()):
    one = _w1g8_PlayerState(
        name="P1", battlefield=list(mine), hand=[pool[name] for name in hand],
        library=[pool["Island"]] * 5,
    )
    two = _w1g8_PlayerState(
        name="P2", battlefield=list(theirs), library=[pool["Island"]] * 5,
    )
    game = _w1g8_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def _w1g8_enchant(game, name, host):
    result = game.cast_from_hand(
        0, name, target_player_index=game.controller_index_of(host),
        target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve(game)
    game._recompute_continuous_effects()


@_w1g8_pytest.mark.parametrize("sacrifice", [True, False])
def test_w1g8_custody_battle_takes_the_creature_unless_a_land_goes(set_pool, sacrifice):
    """'Enchanted creature has "At the beginning of your upkeep, target
    opponent gains control of this creature unless you sacrifice a land."'
    Cast on the opponent's creature: at *its controller's* upkeep the quoted
    trigger names the Aura's caster, and that controller either sacrifices a
    land and keeps it, or does not and loses it."""
    pool = set_pool("ONS")
    seeker = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    island = _w1g8_nosick(_w1g8_Permanent(card=pool["Island"]))
    game, _one, two = _w1g8_aura_game(
        pool, theirs=[seeker, island], hand=["Custody Battle"],
    )
    _w1g8_enchant(game, "Custody Battle", seeker)
    assert "target opponent gains control of this creature" in (
        seeker.effective_card.oracle_text.lower()
    )
    game.start_turn(1)
    _w1g8_resolve(game)
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(1, accept=sacrifice)
    _w1g8_resolve(game)
    game._recompute_continuous_effects()
    if sacrifice:
        assert game.controller_index_of(seeker) == 1
        assert [card.name for card in two.graveyard] == ["Island"]
    else:
        assert game.controller_index_of(seeker) == 0
        assert game.is_on_battlefield(island)


def test_w1g8_mythic_proportions_and_pacifism(set_pool):
    """'+8/+8 and has trample', then 'can't attack or block' on the same
    creature — and both leave with their Auras."""
    pool = set_pool("ONS")
    seeker = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    attacker = _w1g8_nosick(_w1g8_Permanent(card=pool["Glory Seeker"]))
    game, one, _two = _w1g8_aura_game(
        pool, [seeker], [attacker], hand=["Mythic Proportions", "Pacifism"],
    )
    _w1g8_enchant(game, "Mythic Proportions", seeker)
    assert (seeker.effective_power, seeker.effective_toughness) == (10, 10)
    assert game._has_keyword(seeker, "trample")
    assert game.can_attack(seeker, 1)
    _w1g8_enchant(game, "Pacifism", seeker)
    assert not game.can_attack(seeker, 1)
    assert not game._can_block_attacker(seeker, attacker)
    for aura in [p for p in one.battlefield if p.card.name in ("Pacifism", "Mythic Proportions")]:
        game.remove_from_battlefield(aura)
    game._settle()
    game._recompute_continuous_effects()
    assert (seeker.effective_power, seeker.effective_toughness) == (2, 2)
    assert game.can_attack(seeker, 1) and game._can_block_attacker(seeker, attacker)


def test_w1g8_seas_claim_makes_a_land_an_island(set_pool):
    """'Enchanted land is an Island.' CR 305.7: it loses the Mountain's mana
    ability and taps for {U}."""
    pool = set_pool("ONS")
    mountain = _w1g8_nosick(_w1g8_Permanent(card=pool["Mountain"]))
    game, one, _two = _w1g8_aura_game(pool, [mountain], hand=["Sea's Claim"])
    _w1g8_enchant(game, "Sea's Claim", mountain)
    assert mountain.has_type("island") and not mountain.has_type("mountain")
    # Asked for {R}, which it can no longer make, it makes its default.
    assert game.tap_land_for_mana(0, "Mountain", chosen_color="R")
    assert one.mana_pool.get("U") == 1 and one.mana_pool.get("R", 0) == 0

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.named_counters import counters_on as _w1g9_counters_on
from tests.helpers import resolve_stack as _w1g9_resolve


def _w1g9_table(seats=2):
    """*seats* players, seat 0 active, mana costs off."""
    w1g9_game = _w1g9_Game(
        players=[_w1g9_PlayerState(name=f"W1G9-{index}") for index in range(seats)]
    )
    w1g9_game.enforce_mana_costs = False
    w1g9_game.active_player_index = 0
    return w1g9_game


def _w1g9_enter(game, seat, card):
    """*card* onto *seat*'s battlefield through the entry seam, unsick."""
    w1g9_entered = _w1g9_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g9_entered, None)
    w1g9_entered.metadata["summoning_sickness_turn"] = -99
    game.check_state_based_actions()
    _w1g9_resolve(game)
    return w1g9_entered


def _w1g9_settle(game):
    _w1g9_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g9_resolve(game)
    game._recompute_continuous_effects()


def _w1g9_hit_unblocked(game, attacker, *, seat=0, defender=1):
    """*attacker* attacks *defender*, nobody blocks, combat damage is dealt
    and what it set off resolves."""
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        seat, [game.battlefield_index_of(attacker)], defending_player_index=defender
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(defender, {})[0]
    game._set_phase_and_step("combat", "combat_damage")
    assert game.resolve_combat_damage(seat)[0]
    _w1g9_settle(game)


def test_w1g9_aurification_makes_the_creature_that_hit_you_a_wall_with_defender(set_pool):
    """The trigger puts the gold counter on; the static reads it. CR 205.1b
    (layer 4) adds Wall to the creature's other types, CR 702.3b (layer 6)
    gives it defender, so the next attack is refused."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    _w1g9_enter(game, 1, ons["Aurification"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    assert not seeker.has_type("wall")
    _w1g9_hit_unblocked(game, seeker)
    assert game.players[1].life == 18
    assert _w1g9_counters_on(seeker, "gold") == 1
    assert seeker.has_type("wall") and seeker.has_type("soldier")
    assert game._has_keyword(seeker, "defender")

    game.end_combat()
    game.become_untapped(seeker)
    game._set_phase_and_step("combat", "declare_attackers")
    refused = game.declare_attackers(
        0, [game.battlefield_index_of(seeker)], defending_player_index=1
    )
    assert not refused[0]
    assert not seeker.attacking


def test_w1g9_aurification_reaches_only_creatures_bearing_the_counter(set_pool):
    """A creature that dealt no damage to the enchantment's controller has no
    counter and is untouched — and a Wall is a Wall to every reader, so Elven
    Riders' "except by Walls" admits the newly golden blocker."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Aurification"])
    attacker = _w1g9_enter(game, 1, ons["Glory Seeker"])
    bystander = _w1g9_enter(game, 1, ons["Elvish Warrior"])
    riders = _w1g9_enter(game, 0, ons["Elven Riders"])
    game.active_player_index = 1
    _w1g9_hit_unblocked(game, attacker, seat=1, defender=0)
    assert attacker.has_type("wall")
    assert not bystander.has_type("wall")
    assert not game._has_keyword(bystander, "defender")
    game.end_combat()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(riders)], defending_player_index=1
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert not game._can_block_attacker(bystander, riders)
    assert game._can_block_attacker(attacker, riders), "a Wall may block Elven Riders"


def test_w1g9_aurification_leaving_takes_the_counters_and_the_wall_away(set_pool):
    """"When this enchantment leaves the battlefield, remove all gold counters
    from all creatures." The static ends with its source and the counters go
    with the trigger: the creature is a Soldier again and may attack."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    aurification = _w1g9_enter(game, 1, ons["Aurification"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    _w1g9_hit_unblocked(game, seeker)
    assert seeker.has_type("wall")
    game.end_combat()
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.remove_from_battlefield(aurification)
    _w1g9_settle(game)
    assert _w1g9_counters_on(seeker, "gold") == 0
    assert not seeker.has_type("wall")
    assert not game._has_keyword(seeker, "defender")


def test_w1g9_gratuitous_violence_doubles_its_controllers_creatures_in_combat(set_pool):
    """"If a creature you control would deal damage to a permanent or player,
    it deals double that damage instead." Combat damage to a player and to a
    blocker is doubled (CR 614.1a); the opponent's creature's is not."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    _w1g9_hit_unblocked(game, seeker)
    assert game.players[1].life == 16
    assert "2 damage becomes 4" in game.log

    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    wall = _w1g9_enter(game, 1, lea["Wall of Stone"])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(seeker)],
                                  defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {
        game.battlefield_index_of(wall): [game.battlefield_index_of(seeker)]
    })[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    assert wall.damage_marked == 4

    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    giant = _w1g9_enter(game, 1, lea["Hill Giant"])
    game.active_player_index = 1
    _w1g9_hit_unblocked(game, giant, seat=1, defender=0)
    assert game.players[0].life == 17, "the opponent's creature is not 'yours'"


def test_w1g9_gratuitous_violence_doubles_a_creatures_ability_not_a_spell(set_pool):
    """A creature's ability is the creature dealing damage, so Prodigal
    Sorcerer's ping is doubled; Shock (a spell) and Rod of Ruin (an artifact)
    are not creatures and deal what they print."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    _w1g9_enter(game, 0, lea["Prodigal Sorcerer"])
    _w1g9_enter(game, 0, lea["Rod of Ruin"])
    game.players[0].hand.append(ons["Shock"])
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.cast_from_hand(0, "Shock", target_player_index=1)
    _w1g9_settle(game)
    assert game.players[1].life == 18
    game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    _w1g9_settle(game)
    assert game.players[1].life == 16
    game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)
    _w1g9_settle(game)
    assert game.players[1].life == 15


def test_w1g9_doublers_stack_and_keep_their_own_scopes(set_pool):
    """Two Gratuitous Violences and an opponent's Furnace of Rath: a creature's
    damage is doubled three times (CR 616.1 applies each; the order does not
    matter to a product), a spell's only by the Furnace."""
    ons, lea, tmp = set_pool("ONS"), set_pool("LEA"), set_pool("TMP")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    _w1g9_enter(game, 0, ons["Gratuitous Violence"])
    _w1g9_enter(game, 1, tmp["Furnace of Rath"])
    _w1g9_enter(game, 0, lea["Prodigal Sorcerer"])
    game.players[0].hand.append(ons["Shock"])
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    _w1g9_settle(game)
    assert game.players[1].life == 20 - 8
    game.cast_from_hand(0, "Shock", target_player_index=1)
    _w1g9_settle(game)
    assert game.players[1].life == 12 - 4


def test_w1g9_the_multiplier_reader_takes_the_creature_printing():
    """The third printing of the one sentence, through the one reader the
    support gate and the interceptor share."""
    from engine.replacements.damage import damage_multiplier_line

    assert damage_multiplier_line(
        "If a creature you control would deal damage to a permanent or player, "
        "it deals double that damage instead."
    ) == (2, True)
    assert damage_multiplier_line(
        "If a creature you control would deal damage to a permanent, it deals "
        "double that damage instead."
    ) is None
# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# --- W1G10: Risky Move ---------------------------------------------------------
#
# "At the beginning of each player's upkeep, that player gains control of this
# enchantment. When you gain control of this enchantment from another player,
# choose a creature you control and an opponent. Flip a coin. If you lose the
# flip, that opponent gains control of that creature." The gain trigger fires
# from the one seam a permanent changes hands at (`_sync_control`).
from unittest.mock import patch as _w1g10_patch

from engine import Game as _w1g10_Game
from engine.models import Permanent as _w1g10_Permanent
from engine.models import PlayerState as _w1g10_PlayerState
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_risky_table(set_pool):
    """Three seats: Risky Move and a Hill Giant on seat 0, Grizzly Bears on
    seat 1, nothing on seat 2."""
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 10,
        )
        for seat in range(3)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    placed = {}
    for seat, code, name in (
        (0, "ONS", "Risky Move"), (0, "LEA", "Hill Giant"), (1, "LEA", "Grizzly Bears"),
    ):
        perm = _w1g10_Permanent(card=set_pool(code)[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        placed[name] = perm
    _w1g10_resolve_stack(game)
    return game, placed


def _w1g10_next_upkeep(game, *, won: bool):
    with _w1g10_patch("engine.handlers.control_flow.flip_coin", return_value=won):
        game.start_next_turn()
        _w1g10_resolve_stack(game)
        for _ in range(10):
            if not game.pending_choices:
                break
            game.auto_resolve_pending_choices()
            _w1g10_resolve_stack(game)


def test_w1g10_risky_move_hands_itself_over_and_a_lost_flip_gives_a_creature(set_pool):
    """On seat 1's upkeep seat 1 takes the enchantment; gaining it from another
    player triggers for seat 1, which chooses its own creature and an
    opponent, loses the flip, and the opponent takes the creature — for good
    (the ruling: not at end of turn, nor when this card leaves)."""
    game, placed = _w1g10_risky_table(set_pool)
    risky, bears, giant = placed["Risky Move"], placed["Grizzly Bears"], placed["Hill Giant"]
    assert game.controller_index_of(risky) == 0
    _w1g10_next_upkeep(game, won=False)

    assert game.controller_index_of(risky) == 1, game.log
    assert "Risky Move: chose Grizzly Bears" in game.log
    new_owner = game.controller_index_of(bears)
    assert new_owner in (0, 2), game.log
    assert game.controller_index_of(giant) == 0, "seat 0's creature was never seat 1's to give"

    game.remove_from_battlefield(risky)
    game.resolve_cleanup_step(game.active_player_index)
    assert game.controller_index_of(bears) == new_owner, game.log


def test_w1g10_risky_move_a_won_flip_keeps_the_creature(set_pool):
    game, placed = _w1g10_risky_table(set_pool)
    _w1g10_next_upkeep(game, won=True)
    assert game.controller_index_of(placed["Risky Move"]) == 1
    assert game.controller_index_of(placed["Grizzly Bears"]) == 1, game.log
    assert any("won the coin flip" in line for line in game.log), game.log


def test_w1g10_risky_move_its_own_controllers_upkeep_triggers_nothing(set_pool):
    """The upkeep hand-over to the seat that already controls it is no change
    of control, so the "from another player" trigger does not fire."""
    game, placed = _w1g10_risky_table(set_pool)
    game.start_turn(0)
    _w1g10_resolve_stack(game)
    assert game.controller_index_of(placed["Risky Move"]) == 0
    assert not any("Risky Move: chose" in line for line in game.log), game.log

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# --- W1G13: each player, and graveyards --------------------------------------
from engine import Game as _w1g13_Game
from engine.models import Permanent as _w1g13_Permanent
from engine.models import PlayerState as _w1g13_PlayerState

from tests.helpers import _mk_creature_card as _w1g13_creature
from tests.helpers import resolve_stack as _w1g13_resolve_stack


def _w1g13_table(set_pool, hands=None, *, interactive=(), seats=3):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g13_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[ons["Plains"]] * 5,
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g13_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g13_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g13_buried(count):
    return [_w1g13_creature(f"Buried {n}", 2, 2) for n in range(count)]


def test_w1g13_oversold_cemetery_returns_a_creature_card_at_four(set_pool):
    """"…if you have four or more creature cards in your graveyard, you may
    return target creature card from your graveyard to your hand." The target
    is named as the trigger goes on the stack (CR 603.3d) — asked of an
    interactive seat — and the land in the pile counts for nothing."""
    game = _w1g13_table(set_pool, interactive={0})
    alice = game.players[0]
    _w1g13_put(game, 0, set_pool("ONS")["Oversold Cemetery"])
    buried = _w1g13_buried(4)
    alice.graveyard.extend([buried[0], set_pool("ONS")["Plains"], *buried[1:]])
    game.resolve_upkeep(0)
    target = game.pending_choice_of("trigger_target", 0)
    assert target is not None
    assert [entry["name"] for entry in target.data["targets"]] == [c.name for c in buried]
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in alice.hand] == ["Buried 0"]
    assert "Buried 0" not in [c.name for c in alice.graveyard]


def test_w1g13_oversold_cemetery_intervening_if_both_times(set_pool):
    """CR 603.4, and the 2022-12-08 ruling: three creature cards and a land is
    no trigger at all; four that drop to three before it resolves is a trigger
    that does nothing."""
    game = _w1g13_table(set_pool)
    alice = game.players[0]
    _w1g13_put(game, 0, set_pool("ONS")["Oversold Cemetery"])
    alice.graveyard.extend([*_w1g13_buried(3), set_pool("ONS")["Plains"]])
    game.resolve_upkeep(0)
    assert not game.stack and not game.pending_choices
    assert not any("Oversold Cemetery" in line for line in game.log)

    alice.graveyard.append(_w1g13_creature("Fourth", 2, 2))
    game.interactive_seats = {0}
    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices(kinds=("trigger_target",))
    assert [item.card.name for item in game.stack] == ["Oversold Cemetery"]
    alice.graveyard.pop()
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert alice.hand == []
    assert any("condition is no longer true" in line for line in game.log)


def _w1g13_quiet_put(game, seat, card):
    """Onto the battlefield without an entry event, so a watcher already in
    play does not trigger on the table being set."""
    permanent = _w1g13_Permanent(card=card)
    game.players[seat].battlefield.append(permanent)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_death_match_the_entering_creatures_controller_aims_it(set_pool):
    """"Whenever a creature enters, that creature's controller may have target
    creature of their choice get -3/-3 until end of turn." Alice controls the
    enchantment, Bob's creature enters: Bob is asked for the target (CR 603.3d,
    "unless the effect states otherwise" — it does) and Bob is the one asked
    "may?", and the -3/-3 lands on the creature Bob named."""
    game = _w1g13_table(set_pool, {1: [_w1g13_creature("Bob's Giant", 3, 3)]},
                        interactive={0, 1})
    _w1g13_quiet_put(game, 0, set_pool("ONS")["Death Match"])
    alices = _w1g13_quiet_put(game, 0, _w1g13_creature("Alice's Bear", 3, 3))
    caras = _w1g13_quiet_put(game, 2, _w1g13_creature("Cara's Bear", 2, 2))
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Bob's Giant").supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("trigger_target", 0) is None
    asked = game.pending_choice_of("trigger_target", 1)
    assert asked is not None
    assert {entry["name"] for entry in asked.data["targets"]} == {
        "Alice's Bear", "Bob's Giant", "Cara's Bear",
    }
    assert game.confirm_trigger_target(1, permanent_id=caras.permanent_id)
    game.resolve_top_of_stack()
    assert game.pending_choice_of("optional_pay", 0) is None
    assert game.pending_choice_of("optional_pay", 1) is not None
    assert game.confirm_optional_pay(1, "Death Match", accept=True)
    _w1g13_resolve_stack(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(caras)
    assert game.is_on_battlefield(alices) and alices.effective_toughness == 3


def test_w1g13_death_match_declined_does_nothing(set_pool):
    """The "may" is the entering creature's controller's to decline."""
    game = _w1g13_table(set_pool, {1: [_w1g13_creature("Bob's Giant", 3, 3)]},
                        interactive={1})
    _w1g13_quiet_put(game, 0, set_pool("ONS")["Death Match"])
    alices = _w1g13_quiet_put(game, 0, _w1g13_creature("Alice's Bear", 3, 3))
    game.active_player_index = 1
    assert game.queue_from_hand(1, "Bob's Giant").supported
    game.resolve_top_of_stack()
    assert game.confirm_trigger_target(1, permanent_id=alices.permanent_id)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(1, "Death Match", accept=False)
    _w1g13_resolve_stack(game)
    assert alices.effective_toughness == 3

# ==== end W1G13 ======================================================
