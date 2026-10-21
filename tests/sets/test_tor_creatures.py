"""Torment creatures (legendary ones too).

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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_duel(*, hand0=(), hand1=(), bf0=(), bf1=(), library0=None):
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library0) if library0 is not None else [filler] * 10,
            hand=list(hand0),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10, hand=list(hand1),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def test_w1g5_cephalid_vandal_mills_one_more_card_each_upkeep(set_pool):
    """A shred counter each upkeep, then a mill of one card per shred counter:
    1, then 2, then 3 — the count read off the source as the trigger resolves."""
    vandal = set_pool("TOR")["Cephalid Vandal"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(10)]
    game = _w1g5_duel(bf0=[vandal], library0=library)

    milled = []
    for _turn in range(3):
        before = len(game.players[0].graveyard)
        game.start_turn(0)
        _w1g5_resolve_stack(game)
        milled.append(len(game.players[0].graveyard) - before)

    assert milled == [1, 2, 3]
    assert "Cephalid Vandal gets a shred counter (3 total)" in game.log
    assert "A milled 3 card(s)" in game.log


def test_w1g5_pitchstone_wall_returns_the_discarded_card_if_sacrificed(set_pool):
    """Two discards, two triggers. Taking the first offer sacrifices the Wall
    and returns that card; the second finds no Wall to sacrifice ("if you do")
    and returns nothing."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    wall, sludge = tor["Pitchstone Wall"], tor["Mind Sludge"]
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g5_duel(
        hand0=[bolt, bears, forest], hand1=[sludge],
        bf0=[wall], bf1=[lea["Swamp"], lea["Swamp"]],
    )
    game.interactive_seats = {0}

    game.cast_from_hand(1, sludge.name, target_player_index=0)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1], to_library=False,
    )
    assert [item.card.name for item in game.stack] == ["Pitchstone Wall"] * 2
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g5_resolve_stack(game)

    a = game.players[0]
    assert sorted(card.name for card in a.hand) == ["Forest", "Lightning Bolt"]
    assert sorted(card.name for card in a.graveyard) == ["Grizzly Bears", "Pitchstone Wall"]
    assert not list(game.controlled_by(0))


def test_w1g5_pitchstone_wall_declined_returns_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[lea["Lightning Bolt"]], hand1=[tor["Mind Sludge"]],
        bf0=[tor["Pitchstone Wall"]], bf1=[lea["Swamp"]],
    )

    game.cast_from_hand(1, "Mind Sludge", target_player_index=0)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Pitchstone Wall"]


def test_w1g5_pitchstone_wall_ignores_an_opponents_discard(set_pool):
    """"Whenever **you** discard a card": the Wall's controller only."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[tor["Mind Sludge"]], hand1=[lea["Lightning Bolt"]],
        bf0=[tor["Pitchstone Wall"], lea["Swamp"]],
    )

    game.cast_from_hand(0, "Mind Sludge", target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]
    assert not game.stack


def test_w1g5_nantuko_cultivator_counts_and_draws_the_lands_discarded(set_pool):
    """Discard three lands: three +1/+1 counters and three cards. It placed
    none and drew none — the counters read Tetravus's ``trigger_count`` and
    the draw's handler never read ``amount_from`` — and with the counter
    step unreadable the offer could not fold its payoffs, so both ran before
    the discard was even answered."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    forest, island, bolt = lea["Forest"], lea["Island"], lea["Lightning Bolt"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Instant") for i in range(10)]
    game = _w1g5_duel(hand0=[cultivator, forest, forest, island, bolt], library0=library)
    game.interactive_seats = {0}

    game.cast_from_hand(0, cultivator.name)
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    owed = game.pending_choice_of("discard", 0)
    assert owed is not None and owed.data.get("up_to")
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1, 2], to_library=False,
    )
    _w1g5_resolve_stack(game)

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Lightning Bolt", "W1G5 Card 0", "W1G5 Card 1", "W1G5 Card 2",
    ]


def test_w1g5_nantuko_cultivator_declined_places_and_draws_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    game = _w1g5_duel(hand0=[cultivator, lea["Forest"]])

    game.cast_from_hand(0, cultivator.name)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

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
