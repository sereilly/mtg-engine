"""Fifth Dawn artifacts.

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

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_station_table(set_pool, *, graveyard, interactive=()):
    """Salvaging Station on seat 0's board, a Grizzly Bears on each side to
    die, and *graveyard* seat 0's."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    station = _W1G3Permanent(card=set_pool("5DN")["Salvaging Station"])
    game._put_permanent_onto_battlefield(0, station, None)
    bears = []
    for seat in (0, 1):
        bear = _W1G3Permanent(card=lea["Grizzly Bears"])
        game._put_permanent_onto_battlefield(seat, bear, None)
        bears.append(bear)
    _w1g3_settle(game)
    return game, station, bears


def _w1g3_bolt(game, set_pool, victim):
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, (result, game.log[-4:])


def test_w1g3_salvaging_station_returns_a_small_noncreature_artifact(set_pool):
    """"{T}: Return target noncreature artifact card with mana value 1 or less
    from your graveyard to the battlefield." The spec carries both narrowings;
    the Ornithopter (an artifact *creature* at 0) and the Rod of Ruin (at 4)
    are refused at announcement (CR 602.2b); the Sol Ring enters, the Station
    taps."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, _bears = _w1g3_station_table(
        set_pool, graveyard=[atq["Ornithopter"], lea["Rod of Ruin"], lea["Sol Ring"]],
    )
    spec = _w1g3_activation_spec(_w1g3_compile(station.card).activated_abilities[0])
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]
    assert spec["graveyard_mana_value"] == {"op": "le", "value": 1}
    assert spec["graveyard_excluded_types"] == ["creature"]

    for slot in (0, 1):
        refused = game.activate_permanent_ability(
            0, "Salvaging Station", target_player_index=0,
            target_graveyard_indices=[slot],
        )
        assert not refused.supported, slot
    assert not station.tapped
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[2],
    ).supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert station.tapped
    assert any(p.card.name == "Sol Ring" for p in alice.battlefield)
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Rod of Ruin"]


def test_w1g3_salvaging_station_untaps_when_a_creature_dies_and_goes_again(set_pool):
    """"Whenever a creature dies, you may untap this artifact." Any creature,
    the opponent's too. Untapped by the death, a bare activation (no slot
    named, as an AI seat makes it) takes the legal Black Lotus — never the
    Ornithopter first in the pile."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, bears = _w1g3_station_table(
        set_pool,
        graveyard=[atq["Ornithopter"], lea["Sol Ring"], lea["Black Lotus"]],
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[1],
    ).supported
    _w1g3_settle(game)
    assert station.tapped

    _w1g3_bolt(game, set_pool, bears[1])
    _w1g3_settle(game)
    assert not station.tapped, game.log[-6:]

    assert game.activate_permanent_ability(0, "Salvaging Station").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert {p.card.name for p in alice.battlefield} >= {"Sol Ring", "Black Lotus"}
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Lightning Bolt"]


def test_w1g3_salvaging_station_untap_is_a_choice_an_asked_seat_may_decline(set_pool):
    """The "may" is asked of an interactive seat, and declined leaves the
    Station tapped."""
    lea = set_pool("LEA")
    game, station, bears = _w1g3_station_table(
        set_pool, graveyard=[lea["Sol Ring"]], interactive={0},
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert station.tapped
    _w1g3_bolt(game, set_pool, bears[0])
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay", game.log[-6:]
    assert asked.data["card_name"] == "Salvaging Station"
    assert game.confirm_optional_pay(0, "Salvaging Station", accept=False)
    _w1g3_settle(game)
    assert station.tapped

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================
