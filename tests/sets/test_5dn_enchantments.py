"""Fifth Dawn enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, hand=()):
    plains = set_pool("LEA")["Plains"]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name=f"P{seat}", hand=list(hand) if seat == 0 else [],
                         library=[plains] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def _w1g6_counters(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def test_w1g6_rite_of_passage_grows_a_creature_that_survives_the_damage(set_pool):
    """'Whenever a creature you control is dealt damage, put a +1/+1 counter
    on it. (It must survive the damage to get the counter.)' The counter goes
    on the damaged creature — the object the event froze, not the
    enchantment — as the trigger resolves, so one the damage killed gets
    nothing, and an opponent's damaged creature triggers nothing."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]])
    _w1g6_put(game, 0, fdn["Rite of Passage"])
    sorcerer = _w1g6_put(game, 0, lea["Prodigal Sorcerer"])
    giant = _w1g6_put(game, 0, lea["Hill Giant"])
    bears = _w1g6_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g6_put(game, 1, lea["Grizzly Bears"])

    # Survives the ping: one counter, on the Giant.
    result = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", permanent_index=game.battlefield_index_of(sorcerer),
        target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result
    _w1g6_settle(game)
    assert _w1g6_counters(giant) == (4, 4)
    assert _w1g6_counters(sorcerer) == (1, 1)

    # Lethal: no counter, and no other creature takes it.
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g6_counters(giant) == (4, 4)
    assert "Rite of Passage: the permanent it names is gone" in game.log

    # An opponent's creature: no trigger at all.
    resolved = game.log.count("Rite of Passage ability resolved")
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[theirs.permanent_id])
    assert result.supported, result
    _w1g6_settle(game)
    assert not game.is_on_battlefield(theirs)
    assert game.log.count("Rite of Passage ability resolved") == resolved


def test_w1g6_rite_of_passage_one_counter_for_one_simultaneous_dealing(set_pool):
    """Two sources at once is one trigger and one counter (ruling
    2004-12-01): a Force of Nature (8/8) blocked by two Grizzly Bears takes 4 at
    once and survives as a 9/9, not a 10/10."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, fdn["Rite of Passage"])
    wurm = _w1g6_put(game, 0, lea["Force of Nature"])
    blockers = [_w1g6_put(game, 1, lea["Grizzly Bears"]) for _ in range(2)]
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(wurm)], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    blocks = {game.battlefield_index_of(b): game.battlefield_index_of(wurm) for b in blockers}
    ok, why = game.declare_blockers(1, blocks)
    assert ok, why
    _w1g6_drive_combat(game)
    assert game.is_on_battlefield(wurm)
    assert _w1g6_counters(wurm) == (9, 9)

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.
#
# Dawn's Reflection's triggered mana split; Ion Storm's either-kind
# counter cost.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _W1G7Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    _w1g7_settle(game)
    return game, placed[0], placed[1]


def _w1g7_pool(player):
    return {symbol: n for symbol, n in player.mana_pool.items() if n}


def test_w1g7_dawns_reflection_adds_two_mana_split_as_the_tap_says(set_pool):
    """"…its controller adds an additional two mana in any combination of
    colors." Cast on a Forest through the real cast; each tap adds the
    Forest's {G} and two more — the split the tap names ({U}{B}: ruling
    2004-12-01, "The two mana can be of two different colors"), and a split
    that does not add up to two is not honoured part-way: the default takes
    its place whole."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest,), _ = _w1g7_table(
        set_pool, hand=[pool["Dawn's Reflection"]], mine=[lea["Forest"]],
    )
    result = game.cast_from_hand(
        0, "Dawn's Reflection", target_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result
    _w1g7_settle(game)
    assert forest.metadata.get("attached_aura") is not None
    player = game.players[0]

    assert game.tap_land_for_mana(
        0, "Forest", chosen_color="G", permanent_id=forest.permanent_id,
        mana_combination={"U": 1, "B": 1},
    )
    assert _w1g7_pool(player) == {"G": 1, "U": 1, "B": 1}
    assert game.log[-2:] == [
        "Dawn's Reflection: P0 added an additional {U}",
        "Dawn's Reflection: P0 added an additional {B}",
    ]

    forest.tapped = False
    game.clear_mana_pools()
    game.tap_land_for_mana(
        0, "Forest", chosen_color="G", permanent_id=forest.permanent_id,
        mana_combination={"U": 3},
    )
    # Nothing in hand asks for a colour, so the default is the colour the
    # tap asked the land for.
    assert _w1g7_pool(player) == {"G": 3}


def test_w1g7_dawns_reflection_defaults_toward_what_the_hand_asks_for(set_pool):
    """A seat that names no split takes the colours its held cards want
    (`mana_combination.default_split`): a {U}{B} spell in hand makes the
    two extra mana {U}{B} rather than two more of the land's own colour."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest, aura), _ = _w1g7_table(
        set_pool, mine=[lea["Forest"], pool["Dawn's Reflection"]],
    )
    from engine.aura_attachment import attach_aura

    attach_aura(aura, forest)
    game.players[0].hand.append(set_pool("ICE")["Diabolic Vision"])

    game.tap_land_for_mana(0, "Forest", chosen_color="G", permanent_id=forest.permanent_id)

    assert _w1g7_pool(game.players[0]) == {"G": 1, "U": 1, "B": 1}


def test_w1g7_dawns_reflection_gives_the_mana_to_the_lands_controller(set_pool):
    """Its ruling (2004-12-01): "The controller of the land gets the
    additional mana, not the controller of the enchantment." Cast on an
    opponent's Island, the opponent's tap makes three mana for them and
    none for the Aura's controller."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, _, (island,) = _w1g7_table(
        set_pool, hand=[pool["Dawn's Reflection"]], theirs=[lea["Island"]],
    )
    game.cast_from_hand(
        0, "Dawn's Reflection", target_permanent_ids=[island.permanent_id],
    )
    _w1g7_settle(game)

    game.tap_land_for_mana(1, "Island", chosen_color="U", permanent_id=island.permanent_id)

    assert _w1g7_pool(game.players[1]) == {"U": 3}
    assert _w1g7_pool(game.players[0]) == {}


def test_w1g7_dawns_reflection_counts_in_the_payment_planner(set_pool):
    """The planner's units for the enchanted land (`board_payment`) are the
    land's own mana and two of any colour, so one Forest pays {1}{U}{B} and
    not {1}{U}{U}{B}."""
    from engine.board_payment import board_can_pay

    pool = set_pool("5DN")
    lea = set_pool("LEA")
    game, (forest, aura), _ = _w1g7_table(
        set_pool, mine=[lea["Forest"], pool["Dawn's Reflection"]],
    )
    from engine.aura_attachment import attach_aura

    attach_aura(aura, forest)
    cost = {"U": 1, "B": 1, "generic": 1}
    assert board_can_pay(game, 0, cost)
    assert not board_can_pay(game, 0, {"U": 2, "B": 1, "generic": 1})


def test_w1g7_ion_storm_pays_with_either_kind_off_a_permanent_you_choose(set_pool):
    """"{1}{R}, Remove a +1/+1 counter or a charge counter from a permanent
    you control: This enchantment deals 2 damage to any target." The payer
    picks the permanent (``cost_permanent_ids``); unnamed, the one with the
    most to spare pays, and a permanent holding both gives up the inert
    charge counter first. Each payment is one counter, and with none left the
    activation is refused before anything is paid (CR 601.2h)."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    from engine.named_counters import add_counters, counters_on

    game, (storm, bears, bauble), (enemy,) = _w1g7_table(
        set_pool,
        mine=[pool["Ion Storm"], lea["Grizzly Bears"], pool["Wayfarer's Bauble"]],
        theirs=[lea["Grizzly Bears"]],
    )
    game.place_plus1_counters(bears, 1)
    add_counters(bauble, "charge", 2)

    result = game.activate_permanent_ability(0, "Ion Storm", target_player_index=1)
    assert result.supported, result
    _w1g7_settle(game)
    assert game.players[1].life == 18
    assert counters_on(bauble, "charge") == 1
    assert "Wayfarer's Bauble gave up 1 charge counter(s) (Ion Storm's cost)" in game.log

    game.activate_permanent_ability(
        0, "Ion Storm", target_permanent_ids=[enemy.permanent_id],
        cost_permanent_ids=[bears.permanent_id],
    )
    _w1g7_settle(game)
    assert counters_on(bears, "+1/+1") == 0
    assert enemy not in game.players[1].battlefield

    game.activate_permanent_ability(0, "Ion Storm", target_player_index=1)
    _w1g7_settle(game)
    assert counters_on(bauble, "charge") == 0
    assert game.players[1].life == 16

    refused = game.activate_permanent_ability(0, "Ion Storm", target_player_index=1)
    assert not refused.supported
    assert refused.details == (
        "Ion Storm: no permanent with a +1/+1 or charge counter to remove"
    )
    assert game.players[1].life == 16


def test_w1g7_ion_storm_takes_only_the_kinds_it_lists(set_pool):
    """A counter of another kind pays nothing — a Bauble holding only fade
    counters is no candidate — and a kind named outside the two
    (``cost_counter_kind``) is refused with nothing spent."""
    pool = set_pool("5DN")
    from engine.named_counters import add_counters, counters_on

    game, (storm, bauble), _ = _w1g7_table(
        set_pool, mine=[pool["Ion Storm"], pool["Wayfarer's Bauble"]],
    )
    add_counters(bauble, "fade", 2)
    refused = game.activate_permanent_ability(0, "Ion Storm", target_player_index=1)
    assert not refused.supported
    assert counters_on(bauble, "fade") == 2

    add_counters(bauble, "charge", 1)
    refused = game.activate_permanent_ability(
        0, "Ion Storm", target_player_index=1,
        cost_permanent_ids=[bauble.permanent_id], cost_counter_kind="fade",
    )
    assert not refused.supported
    assert counters_on(bauble, "fade") == 2 and counters_on(bauble, "charge") == 1
    assert game.players[1].life == 20

# ==== end w1g7 ======================================================

