"""Fifth Dawn creatures (legendary ones too).

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


def _w1g3_table(set_pool, *, graveyard=(), hand=(), interactive=()):
    """Two seats on seat 0's first main phase, *graveyard* and *hand* seat
    0's, libraries to draw from."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_small_artifact_pile(set_pool):
    """A graveyard where "artifact card with mana value 1 or less" names two
    cards out of five: a four-drop artifact, a creature, the 1-drop, an
    artifact creature at 0, and an {X} artifact (X is 0 off the stack,
    CR 202.3e — Auriok Salvagers' 2020-08-07 ruling)."""
    lea, atq, fdn = set_pool("LEA"), set_pool("ATQ"), set_pool("5DN")
    return [
        lea["Rod of Ruin"], lea["Grizzly Bears"], lea["Sol Ring"],
        atq["Ornithopter"], fdn["Engineered Explosives"],
    ]


def _w1g3_names(cards):
    return [card.name for card in cards]


def test_w1g3_leonin_squire_returns_only_a_small_artifact_card(set_pool):
    """"When this creature enters, return target artifact card with mana value
    1 or less from your graveyard to your hand." A seat nobody asks takes a
    legal card — never the Rod of Ruin first in the pile, which is what the
    unnarrowed artifact return would take."""
    pile = _w1g3_small_artifact_pile(set_pool)
    pile = [pile[0], pile[1], pile[2]]  # Rod of Ruin, Grizzly Bears, Sol Ring
    game = _w1g3_table(
        set_pool, graveyard=pile, hand=[set_pool("5DN")["Leonin Squire"]],
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Sol Ring"], game.log[-8:]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Grizzly Bears"]


def test_w1g3_leonin_squire_offers_the_small_artifacts_and_takes_the_named_one(set_pool):
    """Asked as it goes on the stack (CR 603.3d), the picker lists the three
    artifact cards at mana value 1 or less — the 1-drop, the artifact creature
    at 0 and the {X} artifact — and not the Rod of Ruin or the creature card.
    The one named is the one returned."""
    game = _w1g3_table(
        set_pool, graveyard=_w1g3_small_artifact_pile(set_pool),
        hand=[set_pool("5DN")["Leonin Squire"]], interactive={0},
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    choice = _w1g3_settle(game, defaults=False)
    assert choice is not None and choice.kind == "trigger_target", game.log[-6:]
    assert sorted(entry["name"] for entry in choice.data["targets"]) == [
        "Engineered Explosives", "Ornithopter", "Sol Ring",
    ]
    assert game.confirm_trigger_target(0, seat=0, graveyard_index=3)
    _w1g3_settle(game)

    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Ornithopter"]
    assert "Rod of Ruin" in _w1g3_names(alice.graveyard)


def test_w1g3_leonin_squire_with_no_small_artifact_returns_nothing(set_pool):
    lea = set_pool("LEA")
    game = _w1g3_table(
        set_pool, graveyard=[lea["Rod of Ruin"], lea["Jayemdae Tome"]],
        hand=[set_pool("5DN")["Leonin Squire"]],
    )
    assert game.cast_from_hand(0, "Leonin Squire").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert alice.hand == []
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Jayemdae Tome"]
    assert any(p.card.name == "Leonin Squire" for p in alice.battlefield)


def test_w1g3_auriok_salvagers_picker_and_gate_read_the_mana_value(set_pool):
    """"{1}{W}: Return target artifact card with mana value 1 or less from your
    graveyard to your hand." The activation spec carries the bound, a named
    Rod of Ruin is refused at announcement (CR 602.2b), and a named Sol Ring
    comes back — repeatably, the ability having no tap in its cost."""
    game = _w1g3_table(set_pool, graveyard=_w1g3_small_artifact_pile(set_pool))
    salvagers = set_pool("5DN")["Auriok Salvagers"]
    game._put_permanent_onto_battlefield(0, _W1G3Permanent(card=salvagers), None)
    ability = _w1g3_compile(salvagers).activated_abilities[0]
    spec = _w1g3_activation_spec(ability)
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]
    assert spec["graveyard_mana_value"] == {"op": "le", "value": 1}

    refused = game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[0],
    )
    assert not refused.supported, "a Rod of Ruin is not a legal target"
    assert game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[2],
    ).supported
    _w1g3_settle(game)
    assert game.activate_permanent_ability(
        0, "Auriok Salvagers", target_player_index=0, target_graveyard_indices=[3],
    ).supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert sorted(_w1g3_names(alice.hand)) == ["Engineered Explosives", "Sol Ring"]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin", "Grizzly Bears", "Ornithopter"]


def test_w1g3_auriok_salvagers_unannounced_takes_a_legal_card(set_pool):
    """A bare activation (an AI seat, a caller that named no slot) still takes
    only a card the line allows."""
    lea = set_pool("LEA")
    game = _w1g3_table(
        set_pool, graveyard=[lea["Rod of Ruin"], lea["Black Lotus"]],
    )
    salvagers = set_pool("5DN")["Auriok Salvagers"]
    game._put_permanent_onto_battlefield(0, _W1G3Permanent(card=salvagers), None)
    assert game.activate_permanent_ability(0, "Auriok Salvagers").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert _w1g3_names(alice.hand) == ["Black Lotus"]
    assert _w1g3_names(alice.graveyard) == ["Rod of Ruin"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================
