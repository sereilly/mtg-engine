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

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

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

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# The Words: "{1}: The next time you would draw a card this turn, <effect>
# instead." — Mangara's Tome's armed one-shot with "instead" printed behind
# the effect (`grammar/statements.py`), each activation its own CR 616.1
# candidate at the draw (`replacements/draws._armed_draw_instances`), so the
# drawing player chooses which Word each draw spends (the Words' ruling,
# 2004-10-04). Every test arms through `activate_permanent_ability` and draws
# through the one draw seam, `Game._draw_with_replacements`. And Future
# Sight: the top card revealed (CR 400.2) and played from (CR 601.3, CR
# 305.1) — `engine/library_top.py`.

from engine import Game as _W1G11Game, PlayerState as _W1G11PlayerState
from engine.cast_permissions import playable_from_zones as _w1g11_playable_from_zones
from engine.library_top import top_is_public as _w1g11_top_is_public
from engine.models import Permanent as _W1G11Permanent
from engine.oracle import compile_card_oracle as _w1g11_compile
from engine.targeting import derive_activation_spec as _w1g11_activation_spec
from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_table(set_pool, *, hand=(), library=None, interactive=(), enforce=False):
    """Alice (seat 0, active) and Bob, each with a library of basics."""
    ons = set_pool("ONS")
    alice = _W1G11PlayerState(
        name="Alice",
        library=list(library) if library is not None else [ons["Island"]] * 6,
        hand=[ons[name] for name in hand],
    )
    bob = _W1G11PlayerState(
        name="Bob", library=[ons["Mountain"]] * 6,
        hand=[ons["Swamp"], ons["Forest"], ons["Island"]],
    )
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g11_put(game, seat, card):
    permanent = _W1G11Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g11_arm(game, name, **announcement):
    """Activate the Word *name* for seat 0 and resolve the activation."""
    result = game.activate_permanent_ability(0, name, **announcement)
    assert result.supported, result.details
    _w1g11_resolve_stack(game)


def test_w1g11_two_words_replace_two_draws_and_the_third_is_drawn(set_pool):
    """Words of Worship twice, then a three-card draw: CR 121.2 makes it three
    draws, the first two are each replaced by 5 life (each activation is its
    own effect, CR 614.1 — and nothing is drawn for them, CR 121.6), and the
    third is an ordinary draw."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, ons["Words of Worship"])
    _w1g11_arm(game, "Words of Worship")
    _w1g11_arm(game, "Words of Worship")
    alice = game.players[0]

    drawn = game._draw_with_replacements(alice, 3)

    assert alice.life == 30
    assert drawn == 1 and len(alice.hand) == 1
    assert game.armed_draw_replacements == []
    assert sum("gained 5 life from Words of Worship" in line for line in game.log) == 2


def test_w1g11_the_drawing_player_chooses_which_word_each_draw_spends(set_pool):
    """"If multiple Words have been used prior to drawing a card, then you can
    choose which one to apply (and use up) each time you draw a card." (Each
    Word, 2004-10-04.) Worship then War armed; Alice draws two and is asked
    (CR 616.1e's ``effect_order``) — she spends War first, oldest-first
    notwithstanding, so Bob takes 2 before Alice gains her 5 on the second
    draw, which is no longer contested and is not asked."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, interactive={0, 1})
    _w1g11_put(game, 0, ons["Words of Worship"])
    _w1g11_put(game, 0, ons["Words of War"])
    _w1g11_arm(game, "Words of Worship")
    _w1g11_arm(game, "Words of War", target_player_index=1)
    alice, bob = game.players

    assert game._draw_with_replacements(alice, 2) == 0
    offer = game.pending_choice_of("effect_order", 0)
    assert offer is not None
    options = offer.data["options"]
    assert options == ["Words of Worship", "Words of War (at Bob)"]
    assert (alice.life, bob.life, len(alice.hand)) == (20, 20, 0), "nothing yet"

    assert game.resolve_pending_choice(
        "effect_order", 0, option_index=options.index("Words of War (at Bob)")
    )

    assert game.pending_choice_of("effect_order", 0) is None
    assert (alice.life, bob.life) == (25, 18)
    assert len(alice.hand) == 0, "both draws were replaced"
    war_at = next(i for i, line in enumerate(game.log) if "Words of War dealt 2" in line)
    worship_at = next(
        i for i, line in enumerate(game.log)
        if "gained 5 life from Words of Worship" in line
    )
    assert war_at < worship_at


def test_w1g11_two_equal_words_are_one_choice_and_a_headless_seat_spends_oldest(set_pool):
    """Two Words of Worship are the same option twice, so the drawing player is
    not asked between them; a seat nobody asks spends Worship (armed first)
    before War, CR 616.1e's default."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, interactive={0})
    _w1g11_put(game, 0, ons["Words of Worship"])
    _w1g11_arm(game, "Words of Worship")
    _w1g11_arm(game, "Words of Worship")
    game._draw_with_replacements(game.players[0], 1)
    assert game.pending_choice_of("effect_order", 0) is None
    assert game.players[0].life == 25 and len(game.armed_draw_replacements) == 1

    headless = _w1g11_table(set_pool)
    _w1g11_put(headless, 0, ons["Words of Worship"])
    _w1g11_put(headless, 0, ons["Words of War"])
    _w1g11_arm(headless, "Words of Worship")
    _w1g11_arm(headless, "Words of War", target_player_index=1)
    headless._draw_with_replacements(headless.players[0], 1)
    assert (headless.players[0].life, headless.players[1].life) == (25, 20)


def test_w1g11_a_word_armed_on_an_opponents_turn_replaces_none_of_their_draws(set_pool):
    """"The next time **you** would draw": the effect is its controller's
    (CR 109.5). Armed during Bob's turn, Bob's draw is a draw; Alice's next
    draw that turn is the one replaced."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, ons["Words of Worship"])
    game.active_player_index = 1
    _w1g11_arm(game, "Words of Worship")
    alice, bob = game.players

    game._draw_with_replacements(bob, 1)
    assert len(bob.hand) == 4 and alice.life == 20
    game._draw_with_replacements(alice, 1)
    assert alice.life == 25 and len(alice.hand) == 0


def test_w1g11_an_armed_word_ends_with_the_turn(set_pool):
    """"…this turn": an unspent Word is gone at the next turn's start, and the
    next draw Alice makes is a draw."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, ons["Words of Worship"])
    _w1g11_arm(game, "Words of Worship")
    assert len(game.armed_draw_replacements) == 1

    game.begin_turn_bookkeeping(1)

    assert game.armed_draw_replacements == []
    game._draw_with_replacements(game.players[0], 1)
    assert game.players[0].life == 20 and len(game.players[0].hand) == 1


def test_w1g11_words_of_war_damages_the_target_announced_with_the_activation(set_pool):
    """CR 115.1c: the ability prints "any target", so its target is chosen as
    it is activated — the picker offers one — and the damage at the draw is
    dealt to that target, by the enchantment (CR 120.7): Bob's 1/1 dies, and
    the drawing player is not hit."""
    ons = set_pool("ONS")
    war = ons["Words of War"]
    (ability,) = _w1g11_compile(war).activated_abilities
    assert _w1g11_activation_spec(ability) == {"kind": "any"}

    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, war)
    pioneer = _w1g11_put(game, 1, ons["Elvish Pioneer"])
    _w1g11_arm(game, "Words of War", target_permanent_ids=[pioneer.permanent_id])
    assert game.is_on_battlefield(pioneer), "nothing is dealt until the draw"

    game._draw_with_replacements(game.players[0], 1)
    assert "Words of War dealt 2 damage to Elvish Pioneer" in game.log
    game.check_state_based_actions()  # CR 704.3: the draw was made outside a step

    assert not game.is_on_battlefield(pioneer)
    assert "Elvish Pioneer" in [card.name for card in game.players[1].graveyard]
    assert game.players[0].life == 20 and len(game.players[0].hand) == 0


def test_w1g11_words_of_war_whose_target_left_still_replaces_the_draw(set_pool):
    """CR 614.6: the modified event's damage cannot be dealt to a creature
    that has gone, and is ignored — the draw is still replaced, and nobody
    else takes the 2."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, ons["Words of War"])
    pioneer = _w1g11_put(game, 1, ons["Elvish Pioneer"])
    _w1g11_arm(game, "Words of War", target_permanent_ids=[pioneer.permanent_id])
    game.remove_from_battlefield(pioneer)

    assert game._draw_with_replacements(game.players[0], 1) == 0

    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert len(game.players[0].hand) == 0
    assert game.armed_draw_replacements == []


def test_w1g11_words_of_wind_asks_each_player_in_turn_and_the_next_draw_waits(set_pool):
    """"…each player returns a permanent they control to its owner's hand
    instead." Each player chooses, one at a time in APNAP order (CR 101.4b: a
    player knows the choices made before theirs) — Bob's prompt is armed only
    once Alice has answered — and the second card of Alice's two-card draw
    waits for the last answer (CR 614.11a)."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, interactive={0, 1})
    _w1g11_put(game, 0, ons["Words of Wind"])
    plains = _w1g11_put(game, 0, ons["Plains"])
    _w1g11_put(game, 1, ons["Mountain"])
    island = _w1g11_put(game, 1, ons["Island"])
    _w1g11_arm(game, "Words of Wind")
    alice, bob = game.players

    assert game._draw_with_replacements(alice, 2) == 0
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_set_choice", 0)
    ]
    assert game.resolve_pending_choice(
        "permanent_set_choice", 0, permanent_ids=[plains.permanent_id]
    )
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_set_choice", 1)
    ]
    assert len(alice.hand) == 0, "the second draw waits on Bob"
    assert game.resolve_pending_choice(
        "permanent_set_choice", 1, permanent_ids=[island.permanent_id]
    )

    assert [p.card.name for p in game.controlled_by(0)] == ["Words of Wind"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Mountain"]
    assert [card.name for card in alice.hand] == ["Plains", "Island"]
    assert "Island" in [card.name for card in bob.hand]


def test_w1g11_words_of_waste_makes_each_opponent_discard_before_the_next_draw(set_pool):
    """"…each opponent discards a card instead." W1G13's each-seat discard,
    asked of Bob inside Alice's draw: her second card is drawn only once Bob
    has discarded."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, interactive={0, 1})
    _w1g11_put(game, 0, ons["Words of Waste"])
    _w1g11_arm(game, "Words of Waste")
    alice, bob = game.players

    game._draw_with_replacements(alice, 2)
    assert game.pending_choice_of("discard", 1) is not None
    assert len(alice.hand) == 0

    game.auto_resolve_pending_choices()

    assert len(bob.hand) == 2 and len(bob.graveyard) == 1
    assert len(alice.hand) == 1
    assert game.pending_choices == []


def test_w1g11_words_of_wilding_makes_a_bear_instead_of_the_draw(set_pool):
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    _w1g11_put(game, 0, ons["Words of Wilding"])
    _w1g11_arm(game, "Words of Wilding")

    game._draw_with_replacements(game.players[0], 1)

    (bear,) = [p for p in game.controlled_by(0) if p.is_creature]
    assert bear.card.name == "Bear Token" and bear.card.colors == ("G",)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert bear.has_type("bear")
    assert len(game.players[0].hand) == 0


def test_w1g11_a_cycled_cards_draw_meets_a_word(set_pool):
    """W1G3's cycle event and a Word: Renewed Faith is cycled (its discard is
    the cost, CR 702.29a), its "when you cycle" trigger still fires — the
    cycling happened — and the draw the cycling ability makes is the one
    Words of Worship replaces (CR 121.6)."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, hand=["Renewed Faith"])
    _w1g11_put(game, 0, ons["Words of Worship"])
    _w1g11_arm(game, "Words of Worship")
    alice = game.players[0]

    assert game.activate_from_hand(0, "Renewed Faith").supported
    assert any("cycled Renewed Faith" in line for line in game.log)
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    _w1g11_resolve_stack(game)

    assert alice.hand == [] and [c.name for c in alice.graveyard] == ["Renewed Faith"]
    assert any("gained 5 life from Words of Worship" in line for line in game.log)
    assert any("Renewed Faith drew 0 card" in line for line in game.log)
    assert game.armed_draw_replacements == []


def test_w1g11_future_sight_reveals_the_top_card_to_everyone(set_pool):
    """"Play with the top card of your library revealed." Public (CR 400.2):
    for its controller's library, and only while it stands."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool)
    sight = _w1g11_put(game, 0, ons["Future Sight"])
    assert _w1g11_top_is_public(game, 0) and not _w1g11_top_is_public(game, 1)
    game.remove_from_battlefield(sight)
    assert not _w1g11_top_is_public(game, 0)


def test_w1g11_future_sight_casts_and_plays_from_the_top_at_the_normal_price(set_pool):
    """"You may play lands and cast spells from the top of your library."
    Shock is cast off the top for its mana cost (2019-06-14: "pay its costs"),
    the Mountain under it is played as the turn's land drop, and the Plains
    under that cannot be — "you may play that land only if you have any
    available land plays" (2019-06-14)."""
    ons = set_pool("ONS")
    game = _w1g11_table(
        set_pool, enforce=True,
        library=[ons["Shock"], ons["Mountain"], ons["Plains"], ons["Island"]],
    )
    _w1g11_put(game, 0, ons["Future Sight"])
    assert _w1g11_playable_from_zones(game, 0)[0]["name"] == "Shock"

    unpaid = game.cast_from_hand(0, "Shock", from_zone="library", target_player_index=1)
    assert not unpaid.supported, "the top card is cast at its own price"
    game.players[0].mana_pool["R"] = 1
    shock = game.cast_from_hand(0, "Shock", from_zone="library", target_player_index=1)
    assert shock.supported, shock.details
    _w1g11_resolve_stack(game)
    assert game.players[1].life == 18
    assert game.players[0].library[0].name == "Mountain"

    assert game.cast_from_hand(0, "Mountain", from_zone="library").supported
    refused = game.cast_from_hand(0, "Plains", from_zone="library")
    assert not refused.supported and "already played a land" in refused.details
    assert [p.card.name for p in game.controlled_by(0)] == ["Future Sight", "Mountain"]
    assert game.players[0].library[0].name == "Plains"


def test_w1g11_future_sights_top_card_is_not_in_a_hand(set_pool):
    """"The top card of your library isn't in your hand, so you can't … cycle
    it" (2019-06-14). A cycler on top is castable as a spell and is not
    cyclable."""
    ons = set_pool("ONS")
    game = _w1g11_table(set_pool, library=[ons["Renewed Faith"], ons["Island"]])
    _w1g11_put(game, 0, ons["Future Sight"])

    assert not game.activate_from_hand(0, "Renewed Faith").supported
    assert game.players[0].library[0].name == "Renewed Faith"
    assert _w1g11_playable_from_zones(game, 0)[0]["name"] == "Renewed Faith"

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
