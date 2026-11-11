"""Darksteel artifacts — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Mycosynth Lattice: a board-wide layer-4 card-type addition, a layer-5
# colour set reaching every zone and every player's objects, and every
# player's spend-as-any-colour permission (CR 609.4b). Boards are built
# through the entry seam and read after `settle`.

from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.object_colors import card_colors as _w1g8_card_colors
from engine.targeting import derive_cast_spec as _w1g8_cast_spec
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import settle as _w1g8_settle


def _w1g8_table(set_pool, *, library=None):
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", library=list(library or [island] * 20))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g8_put(game, card, seat=0):
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def _w1g8_lattice(set_pool):
    return set_pool("DST")["Mycosynth Lattice"]


def test_w1g8_lattice_makes_every_permanent_an_artifact(set_pool):
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    forest = _w1g8_put(game, lea["Forest"])
    bears = _w1g8_put(game, lea["Grizzly Bears"])
    crusade = _w1g8_put(game, lea["Crusade"], seat=1)
    angel = _w1g8_put(game, lea["Serra Angel"], seat=1)
    assert not any(p.has_type("artifact") for p in (forest, bears, crusade, angel))

    lattice = _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    for permanent in (forest, bears, crusade, angel, lattice):
        assert permanent.has_type("artifact"), permanent.card.name
    # CR 205.1b: every other type is kept.
    assert forest.has_type("land") and forest.has_type("forest")
    assert bears.is_creature and bears.has_type("bear")
    assert crusade.has_type("enchantment")

    # A static ability: the Lattice leaving ends it (CR 611.3a).
    game.remove_from_battlefield(lattice)
    _w1g8_settle(game)
    assert not any(p.has_type("artifact") for p in (forest, bears, crusade, angel))


def test_w1g8_lattice_makes_every_object_in_every_zone_colorless(set_pool):
    lea = set_pool("LEA")
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g8_table(set_pool, library=[lea["Giant Growth"]] * 10)
    game.players[0].hand.append(bolt)
    game.players[1].graveyard.append(lea["Dark Ritual"])
    angel = _w1g8_put(game, lea["Serra Angel"], seat=1)
    _w1g8_put(game, bears)
    assert _w1g8_card_colors(game, bolt, 0) == ("R",)
    assert game._effective_colors(angel) == {"W"}

    lattice = _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    # Permanents, through the layers.
    assert game._effective_colors(angel) == set()
    # Cards in a hand, a library and a graveyard, both players', and whether
    # or not the caller can say whose (the sentence names no seat).
    assert _w1g8_card_colors(game, bolt, 0) == ()
    assert _w1g8_card_colors(game, bolt) == ()
    assert _w1g8_card_colors(game, game.players[1].library[0], 1) == ()
    assert _w1g8_card_colors(game, game.players[1].graveyard[0], 1) == ()
    assert _w1g8_card_colors(game, forest, 0) == ()
    # A spell on the stack.
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game._stack_item_colors(game.stack[-1]) == ()
    _w1g8_settle(game)
    assert game.players[1].life == 17

    game.remove_from_battlefield(lattice)
    _w1g8_settle(game)
    assert game._effective_colors(angel) == {"W"}
    assert _w1g8_card_colors(game, game.players[1].library[0], 1) == ("G",)


def test_w1g8_lattice_lets_every_player_spend_mana_as_any_color(set_pool):
    """CR 609.4b: each player pays a {G} with {C}. Only how the cost may be
    paid changes, never the cost — and with no Lattice the {C} pays
    nothing coloured."""
    lea = set_pool("LEA")
    for with_lattice in (True, False):
        for seat in (0, 1):
            game = _w1g8_table(set_pool)
            game.enforce_mana_costs = True
            game.players[seat].hand.append(lea["Giant Growth"])
            bears = _w1g8_put(game, lea["Grizzly Bears"], seat=seat)
            if with_lattice:
                _w1g8_put(game, _w1g8_lattice(set_pool), seat=0)
            if seat == 1:
                game.start_turn(1)
            _w1g8_settle(game)
            game.players[seat].mana_pool = {
                "W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1,
            }
            result = game.cast_from_hand(
                seat, "Giant Growth", target_permanent_ids=[bears.permanent_id],
            )
            assert result.supported is with_lattice, (with_lattice, seat, result)
            _w1g8_settle(game)
            assert bears.effective_power == (5 if with_lattice else 2)


def test_w1g8_lattice_lets_shatter_destroy_a_land_and_stops_terror(set_pool):
    """Every reader of "artifact" follows layer 4: Shatter ("target
    artifact") reaches a land, and Terror ("nonartifact, nonblack creature")
    reaches no creature at all."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.players[0].hand.extend([lea["Shatter"], lea["Terror"]])
    island = _w1g8_put(game, lea["Island"], seat=1)
    bears = _w1g8_put(game, lea["Grizzly Bears"], seat=1)
    shatter, terror = game.players[0].hand
    shatter_spec = _w1g8_cast_spec(shatter, _w1g8_compile(shatter))
    terror_spec = _w1g8_cast_spec(terror, _w1g8_compile(terror))

    def offered(card, spec):
        return {
            entry["name"]
            for entry in game._enumerate_targets(0, card, spec, for_cast=True)
        }

    assert "Island" not in offered(shatter, shatter_spec)
    assert "Grizzly Bears" in offered(terror, terror_spec)

    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    assert "Island" in offered(shatter, shatter_spec)
    assert offered(terror, terror_spec) == set()
    assert not game.cast_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[island.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(island)
    assert island.card in game.players[1].graveyard


def test_w1g8_lattice_lets_a_colorless_white_spell_target_through_protection(set_pool):
    """CR 702.16b: protection from white stops only white objects. Under the
    Lattice Swords to Plowshares is colourless, so Black Knight can be its
    target; without it, it cannot."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.players[0].hand.append(lea["Swords to Plowshares"])
    knight = _w1g8_put(game, lea["Black Knight"], seat=1)
    assert not game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[knight.permanent_id],
    ).supported

    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_settle(game)
    assert game.cast_from_hand(
        0, "Swords to Plowshares", target_permanent_ids=[knight.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(knight)
    assert game.players[1].life == 22


def test_w1g8_lattice_counts_every_permanent_for_affinity(set_pool):
    """Affinity for artifacts counts what *is* an artifact (CR 702.41a): a
    Lattice, two Forests and a Bears are four, so Myr Enforcer costs {3} —
    and the three Forests' mana pays exactly that."""
    lea = set_pool("LEA")
    game = _w1g8_table(set_pool)
    game.enforce_mana_costs = True
    game.players[0].hand.append(set_pool("MRD")["Myr Enforcer"])
    _w1g8_put(game, _w1g8_lattice(set_pool))
    _w1g8_put(game, lea["Grizzly Bears"])
    _w1g8_put(game, lea["Forest"])
    _w1g8_put(game, lea["Forest"])
    _w1g8_settle(game)
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 0}
    assert not game.cast_from_hand(0, "Myr Enforcer").supported
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 3, "C": 0}
    assert game.cast_from_hand(0, "Myr Enforcer").supported
    _w1g8_settle(game)
    assert "Myr Enforcer" in [p.card.name for p in game.all_permanents()]

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
