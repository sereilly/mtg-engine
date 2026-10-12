"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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
import pytest as _w1g5_pytest  # noqa: E402

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState  # noqa: E402
from engine.damage_events import deal_damage as _w1g5_deal_damage  # noqa: E402
from engine.models import Permanent as _W1G5Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w1g5_resolve_stack  # noqa: E402


def _w1g5_table(catalog_by_name, set_pool, hand0=(), hand1=(), interactive=()):
    """Two seats, mana off, a library each so a draw is a draw. Cards are
    looked up in Odyssey first and the shipped pool second."""
    ody = set_pool("ODY")

    def card(name):
        return ody[name] if name in ody else catalog_by_name[name]

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        _W1G5PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.players[0].hand = [card(name) for name in hand0]
    game.players[1].hand = [card(name) for name in hand1]
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g5_card = card
    return game  # _w1g5_table (enchantments)


def _w1g5_put(game, seat, name):
    """*name* onto *seat*'s battlefield through the one entry path, awake."""
    permanent = _W1G5Permanent(card=game._w1g5_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g5_put (enchantments)


def _w1g5_dealt(game, recipient, amount, source, source_seat=None):
    """One damage event through CR 120.4, reporting what was dealt."""
    event = {"recipient": recipient, "amount": amount, "source": source,
             "combat": False}
    if source_seat is not None:
        event["source_seat"] = source_seat
    return _w1g5_deal_damage(game, event).dealt  # _w1g5_dealt (enchantments)


# The five Spheres -------------------------------------------------------------

_W1G5_SPHERES = [
    ("Sphere of Duty", "Grizzly Bears", "Hill Giant"),      # green
    ("Sphere of Grace", "Scathe Zombies", "Hill Giant"),    # black
    ("Sphere of Law", "Hill Giant", "Grizzly Bears"),       # red
    ("Sphere of Reason", "Merfolk of the Pearl Trident", "Hill Giant"),  # blue
    ("Sphere of Truth", "Savannah Lions", "Hill Giant"),    # white
]


@_w1g5_pytest.mark.parametrize("sphere, answered, ignored", _W1G5_SPHERES)
def test_w1g5_a_sphere_shaves_two_points_off_its_colours_sources_only(
    catalog_by_name, set_pool, sphere, answered, ignored,
):
    """"If a <colour> source would deal damage to you, prevent 2 of that
    damage." Urza's Armor's sentence with two payload words changed: a static
    prevention (CR 615.1), never used up, narrowed by the source's colour and
    by "you" — the Sphere's controller. A source of another colour, and the
    opponent's face, are untouched; a 1-damage source of the colour deals
    nothing at all."""
    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, sphere)
    hit = _w1g5_put(game, 1, answered)
    miss = _w1g5_put(game, 1, ignored)
    alice, bob = game.players

    assert _w1g5_dealt(game, alice, 5, hit) == 3
    assert _w1g5_dealt(game, alice, 5, hit) == 3, "a static prevention is never used up"
    assert _w1g5_dealt(game, alice, 1, hit) == 0
    assert _w1g5_dealt(game, alice, 5, miss) == 5, "another colour's source is not this Sphere's"
    assert _w1g5_dealt(game, bob, 5, hit) == 5, "'to you' is the Sphere's controller"
    assert _w1g5_dealt(game, alice, 5, None) == 5, "no source has no colour"


def test_w1g5_sphere_of_law_reads_a_spells_colour_and_stacks_with_a_second(
    catalog_by_name, set_pool,
):
    """A Lightning Bolt cast at the Sphere's controller lands 1; a second
    Sphere takes the other point (two effects, summed — subtraction commutes,
    so CR 616.1's order cannot matter). And the colour is the source's colour
    *as a source of damage* (CR 609.7b): under Ghostly Flame a red spell is a
    colourless source, so no Sphere of Law answers to it."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"] * 3)
    _w1g5_put(game, 0, "Sphere of Law")
    game.active_player_index = 1

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 19

    _w1g5_put(game, 0, "Sphere of Law")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 19, "two Spheres prevent 4 of a 3-damage event, clamped"

    _w1g5_put(game, 1, "Ghostly Flame")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 16


def test_w1g5_a_sphere_recolours_with_its_source_and_an_invented_card_reads_the_same(
    catalog_by_name, set_pool,
):
    """The colour is read when the damage would be dealt, through the layers:
    a green creature turned red is a red source. And the sentence is a
    template, not a card — an invented permanent printing "prevent 3" against
    blue sources works with no registration."""
    from engine.color_changes import change_color
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_card

    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, "Sphere of Law")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    assert _w1g5_dealt(game, game.players[0], 4, bears) == 4
    change_color(bears, "R")
    assert _w1g5_dealt(game, game.players[0], 4, bears) == 2

    invented = _mk_card(
        "W1G5 Blue Ward", "{1}", "Enchantment",
        "If a blue source would deal damage to you, prevent 3 of that damage.",
    )
    assert compile_card_oracle(invented).supported
    game._put_permanent_onto_battlefield(0, _W1G5Permanent(card=invented), None)
    merfolk = _w1g5_put(game, 1, "Merfolk of the Pearl Trident")
    assert _w1g5_dealt(game, game.players[0], 4, merfolk) == 1

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
