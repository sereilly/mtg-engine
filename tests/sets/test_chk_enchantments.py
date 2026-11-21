"""Champions of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), library=None):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name=f"P{seat}",
            library=list(library) if (seat == 0 and library) else [lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, card, seat):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def test_w1g6_oni_possession_makes_a_bigger_demon_spirit_and_eats_a_creature(set_pool):
    """"Enchanted creature gets +3/+3 and has trample" and "is a Demon Spirit":
    a Grizzly Bears becomes a 5/5 trampling Demon Spirit and stops being a Bear
    (CR 205.1a — the new creature types replace the old). "At the beginning of
    your upkeep, sacrifice a creature": the next upkeep costs a creature."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Oni Possession"]])
    bears = _w1g6_put(game, lea["Grizzly Bears"], 0)
    _w1g6_put(game, lea["Llanowar Elves"], 0)
    assert game.cast_from_hand(0, "Oni Possession", target_permanent_ids=[bears.permanent_id]).supported
    _w1g6_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    assert game._has_keyword(bears, "trample")
    assert bears.has_type("Demon") and bears.has_type("Spirit")
    assert not bears.has_type("Bear")

    game.start_turn(0)
    _w1g6_settle(game)
    # The stated default gives up the cheapest creature: the Elves.
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Oni Possession"]


def test_w1g6_night_dealings_counts_damage_to_another_player(set_pool):
    """"Whenever a source you control deals damage to another player, put that
    many theft counters on this enchantment": a Bolt at the opponent (3) and a
    Hill Giant's combat damage (3) count; the opponent's Bolt at you and your
    Bolt at yourself do not. "{2}{B}{B}, Remove X theft counters: Search your
    library for a nonland card with mana value X" then fetches the Hill Giant
    for X=4."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
        library=[lea["Forest"], lea["Grizzly Bears"], lea["Hill Giant"], lea["Craw Wurm"]],
    )
    dealings = _w1g6_put(game, chk["Night Dealings"], 0)
    _w1g6_put(game, lea["Hill Giant"], 0)
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 3
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 3

    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 14
    assert _w1g6_counters_on(dealings, "theft") == 6

    assert not game.activate_permanent_ability(0, "Night Dealings", x_value=7).supported
    assert game.activate_permanent_ability(0, "Night Dealings", x_value=4).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(dealings, "theft") == 2
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
