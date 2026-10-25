"""Onslaught creatures (legendary ones too) — wave 1's groups W1G3 to W1G13.

The set prints 174 creatures; W1G1 (morph) and W1G2 (face-down) write in
`test_ons_creatures.py`, every later group here, so neither file reaches the
2,600-line cap mid-wave.

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


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: cycling triggers on creatures, and the cycling creatures --------
#
# Krosan Tusker's "When you cycle this card" is the cycled card's own trigger
# (CR 702.29c), asked of the card in the graveyard; Fleeting Aven's "Whenever
# a player cycles a card" is a permanent watching the table. Both announced
# where the cycling ability's discard is paid
# (`CardActivationMixin._announce_cycle`).
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=()):
    """Alice (seat 0, active) holding *hand* over *library* (top first) and
    five Plains; Bob holding *opponent_hand*."""
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand],
        library=[ons[name] for name in library] + [filler] * 5,
    )
    bob = PlayerState(
        name="Bob", hand=[ons[name] for name in opponent_hand],
        library=[filler] * 5,
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


def test_w1g3_krosan_tusker_cycled_searches_before_it_draws(set_pool):
    """"When you cycle this card, you may search your library for a basic land
    card, reveal that card, put it into your hand, then shuffle. (Do this
    before you draw.)" The library's top card is Wellwisher, a creature; the
    search takes the Forest from under it, and only then is a card drawn."""
    game, alice, _bob = _w1g3_table(
        set_pool, "Krosan Tusker", library=("Wellwisher", "Forest"),
    )
    game.enforce_mana_costs = True
    alice.mana_pool.update({"C": 2, "G": 1})

    assert game.activate_from_hand(0, "Krosan Tusker").supported
    assert not any(alice.mana_pool.values())
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == ["Forest"], "searched, not yet drawn"
    assert len(alice.library) == 6
    assert any("revealed Forest" in line for line in game.log)
    resolve_stack(game)
    assert len(alice.hand) == 2 and len(alice.library) == 5
    assert [c.name for c in alice.graveyard] == ["Krosan Tusker"]


def test_w1g3_krosan_tusker_is_supported_and_cycles_only_from_hand(set_pool):
    """The creature compiles now that its cycle trigger does; on the
    battlefield it is a 6/5 with no cycling to reach (CR 702.29b / 113.6j),
    and another card's cycle is not its own."""
    tusker = set_pool("ONS")["Krosan Tusker"]
    program = compile_card_oracle(tusker)
    assert program.supported, program.reason
    assert usable_activated_abilities(program) == []

    game, alice, _bob = _w1g3_table(set_pool, "Lay Waste")
    beast = _w1g3_put(game, 0, tusker)
    assert (beast.effective_power, beast.effective_toughness) == (6, 5)
    assert not game.activate_permanent_ability(0, "Krosan Tusker").supported
    assert game.activate_from_hand(0, "Lay Waste").supported
    assert [item.card.name for item in game.stack] == ["Lay Waste"]
    resolve_stack(game)


@pytest.mark.parametrize("cycler", [0, 1])
def test_w1g3_fleeting_aven_returns_to_hand_when_anyone_cycles(set_pool, cycler):
    """"Whenever a player cycles a card, return this creature to its owner's
    hand." — its controller's cycle or its opponent's, before the draw."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste", opponent_hand=["Swat"])
    aven = _w1g3_put(game, 0, set_pool("ONS")["Fleeting Aven"])
    name = "Lay Waste" if cycler == 0 else "Swat"
    cycling_player = game.players[cycler]

    assert game.activate_from_hand(cycler, name).supported
    assert game.stack[-1].card.name == "Fleeting Aven"
    assert game.resolve_top_of_stack()
    assert not game.is_on_battlefield(aven)
    assert "Fleeting Aven" in [c.name for c in alice.hand]
    assert "Plains" not in [c.name for c in cycling_player.hand], "not drawn yet"
    resolve_stack(game)
    assert "Plains" in [c.name for c in cycling_player.hand]


#: The Onslaught creatures that print cycling and nothing triggering on it,
#: with the mana their cycling cost takes from the pool.
_W1G3_PLAIN_CYCLING_CREATURES = {
    "Barkhide Mauler": {"C": 2},
    "Disciple of Grace": {"C": 2},
    "Disciple of Malice": {"C": 2},
    "Slipstream Eel": {"C": 1, "U": 1},
    "Undead Gladiator": {"C": 1, "B": 1},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_CREATURES))
def test_w1g3_a_cycling_creature_cycles_from_hand_and_never_from_play(set_pool, name):
    """From a hand: the printed cycling cost, the card to the graveyard, one
    card drawn. On the battlefield (CR 702.29b): the ability still exists, and
    nothing can activate it (CR 113.6j)."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    cycling = [
        a for a in usable_activated_abilities(program, zone=HAND)
        if a.source_line.endswith("Discard this card: Draw a card.")
    ]
    assert len(cycling) == 1
    assert cycling[0] not in usable_activated_abilities(program)

    game, alice, _bob = _w1g3_table(set_pool, name)
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_CREATURES[name])
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]

    game, alice, _bob = _w1g3_table(set_pool)
    _w1g3_put(game, 0, card)
    library = len(alice.library)
    game.activate_permanent_ability(0, name)
    resolve_stack(game)
    assert len(alice.library) == library and alice.hand == []
    assert alice.graveyard == []

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


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
