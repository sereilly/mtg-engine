"""Torment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand0=(), gy0=(), gy1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), ((), gy1)))
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g2_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g2_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def _w1g2_gy(game, seat):
    return sorted(card.name for card in game.players[seat].graveyard)


#: Six cards and seven: threshold is "seven or more cards in your graveyard"
#: (CR 207.2c makes the word itself mean nothing), asked as the spell resolves,
#: when the spell is on the stack and not yet in that graveyard.
_W1G2_SHORT = ["Forest"] * 6
_W1G2_THRESHOLD = ["Forest"] * 7


# --- Kamahl's Sledge: the replaced sentence, and then its target's controller --

def test_kamahls_sledge_deals_four_to_the_creature_alone_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_SHORT,
        bf1=["Craw Wurm", "Grizzly Bears"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert [t["name"] for t in game.cast_target_spec(
        0, game.players[0].hand[0])["valid_targets"]
    ] == ["Craw Wurm", "Grizzly Bears"]
    assert game.cast_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert [p.life for p in game.players] == [20, 20]


def test_kamahls_sledge_with_threshold_also_hits_that_creatures_controller(set_pool):
    """"…instead Kamahl's Sledge deals 4 damage to that creature and 4 damage
    to that creature's controller." One announcement (CR 601.2c) — the
    creature — and the seat is whoever controls it, the caster included."""
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf1=["Craw Wurm"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert game.cast_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == []
    assert [p.life for p in game.players] == [20, 16]

    own = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf0=["Craw Wurm"],
    )
    assert own.cast_from_hand(
        0, "Kamahl's Sledge",
        target_permanent_ids=[_w1g2_on_board(own, 0, "Craw Wurm").permanent_id],
    ).supported
    _w1g2_resolve_stack(own)
    assert [p.life for p in own.players] == [16, 20]


def test_kamahls_sledge_does_nothing_once_its_one_target_is_gone(set_pool):
    """CR 608.2b: every target illegal, so neither arm runs — no damage to a
    controller the creature no longer has."""
    game = _w1g2_table(
        set_pool, hand0=["Kamahl's Sledge"], gy0=_W1G2_THRESHOLD,
        bf1=["Craw Wurm"],
    )
    wurm = _w1g2_on_board(game, 1, "Craw Wurm")
    assert game.queue_from_hand(
        0, "Kamahl's Sledge", target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [20, 20]


# --- Rancid Earth: the replaced sentence, and then a sweep -----------------

def test_rancid_earth_destroys_the_land_alone_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_SHORT,
        bf0=["Grizzly Bears"], bf1=["Mountain", "Grizzly Bears"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.cast_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert [p.life for p in game.players] == [20, 20]
    assert all(p.damage_marked == 0 for p in game.all_permanents())


def test_rancid_earth_with_threshold_also_deals_one_to_each_creature_and_player(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_THRESHOLD,
        bf0=["Grizzly Bears"], bf1=["Mountain", "Mons's Goblin Raiders"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.cast_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [19, 19]
    assert _w1g2_names(game, 1) == [], "the land destroyed, the 1/1 dead of 1 damage"
    assert _w1g2_on_board(game, 0, "Grizzly Bears").damage_marked == 1


def test_rancid_earth_does_nothing_once_its_land_is_gone(set_pool):
    """The damage is part of the arm that destroys "that land", and with the
    one target illegal the spell does not resolve at all (CR 608.2b)."""
    game = _w1g2_table(
        set_pool, hand0=["Rancid Earth"], gy0=_W1G2_THRESHOLD,
        bf1=["Mountain", "Grizzly Bears"],
    )
    mountain = _w1g2_on_board(game, 1, "Mountain")
    assert game.queue_from_hand(
        0, "Rancid Earth", target_permanent_ids=[mountain.permanent_id],
    ).supported
    game.remove_from_battlefield(mountain)
    _w1g2_resolve_stack(game)
    assert [p.life for p in game.players] == [20, 20]
    assert _w1g2_on_board(game, 1, "Grizzly Bears").damage_marked == 0


# --- Cleansing Meditation: what the sweep destroyed, returned ----------------

def test_cleansing_meditation_destroys_every_enchantment_without_threshold(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Cleansing Meditation"], gy0=_W1G2_SHORT[:5],
        bf0=["Castle"], bf1=["Crusade"],
    )
    assert game.cast_from_hand(0, "Cleansing Meditation").supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == [] and _w1g2_names(game, 1) == []
    assert "Castle" in _w1g2_gy(game, 0) and _w1g2_gy(game, 1) == ["Crusade"]


def test_cleansing_meditation_with_threshold_returns_only_your_own_destroyed_cards(set_pool):
    """"…instead destroy all enchantments, then return all cards in **your
    graveyard destroyed this way** to the battlefield." The opponent's
    enchantment went to their graveyard and stays; a copy that was already in
    yours before the sweep is not a card destroyed this way and stays too."""
    game = _w1g2_table(
        set_pool, hand0=["Cleansing Meditation"],
        gy0=_W1G2_SHORT + ["Castle"],
        bf0=["Castle", "Crusade"], bf1=["Crusade"],
    )
    assert game.cast_from_hand(0, "Cleansing Meditation").supported
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == ["Castle", "Crusade"]
    assert _w1g2_names(game, 1) == [] and _w1g2_gy(game, 1) == ["Crusade"]
    assert _w1g2_gy(game, 0).count("Castle") == 1, "the older copy stays put"
    assert any(
        "P0 returned Castle to the battlefield" in line for line in game.log
    )


def test_a_destroyed_this_way_return_with_no_destroy_in_front_is_refused():
    """The record is the producer discipline every "this way" keeps: with no
    step of the effect destroying anything the words name an empty set, and
    read as the plain sweep they would return the whole pile."""
    from engine.grammar import compile_line

    assert not compile_line(
        "Return all cards in your graveyard destroyed this way to the battlefield."
    ).usable
    assert compile_line(
        "Destroy all artifacts, then return all cards in your graveyard "
        "destroyed this way to the battlefield."
    ).usable

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

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
