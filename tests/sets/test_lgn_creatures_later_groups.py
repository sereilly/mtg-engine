"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


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

# --- W1G7: players and odd ends ----------------------------------------------
from engine import Game as _w1g7_Game
from engine.models import Permanent as _w1g7_Permanent
from engine.models import PlayerState as _w1g7_PlayerState

from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(set_pool, name):
    """A Legions card, else one from Alpha (the lands and the old regulars)."""
    lgn = set_pool("LGN")
    return lgn[name] if name in lgn else set_pool("LEA")[name]


def _w1g7_table(set_pool, hands=None, *, libraries=None, seats=2, interactive=()):
    """A *seats*-player table, Alice active, costs unenforced."""
    hands = hands or {}
    libraries = libraries or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g7_PlayerState(
            name=name,
            hand=[_w1g7_card(set_pool, c) for c in hands.get(seat, ())],
            library=[
                _w1g7_card(set_pool, c)
                for c in libraries.get(seat, ["Plains"] * 8)
            ],
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g7_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g7_put(game, set_pool, seat, name, *, tapped=False):
    """Put *name* onto *seat*'s battlefield by an effect (never cast)."""
    permanent = _w1g7_Permanent(card=_w1g7_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve_stack(game)
    permanent.tapped = tapped
    return permanent


def _w1g7_finish_combat(game):
    """Step from declare-blockers through the damage, draining each trigger."""
    for _ in range(12):
        _w1g7_resolve_stack(game)
        if game.current_phase != "combat" or game.pending_choices:
            return
        game.advance_combat_phase()


def _w1g7_names(cards):
    return [card.name for card in cards]


# --- Phage the Untouchable ----------------------------------------------------


def test_w1g7_phage_cast_from_a_hand_keeps_its_controller_in_the_game(set_pool):
    """"When Phage enters, if you didn't cast it from your hand, you lose the
    game." Cast from Alice's hand, the intervening-if (CR 603.4) is false when
    the permanent enters, so nothing triggers and nobody loses."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    assert _w1g7_names(p.card for p in game.controlled_by(0)) == ["Phage the Untouchable"]
    assert not game.players[0].lost
    assert any("didn't trigger" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_put_onto_the_battlefield_loses_the_game(set_pool):
    """The ruling (2004-10-04): "Putting it onto the battlefield from your
    hand using a spell or ability will cause you to lose the game." A Phage
    that was never cast has no cast stamp, so its controller loses."""
    game = _w1g7_table(set_pool)
    _w1g7_put(game, set_pool, 0, "Phage the Untouchable")
    assert game.players[0].lost
    assert not game.players[1].lost
    assert any("Alice lost the game" in line for line in game.log), game.log[-4:]


def test_w1g7_phage_destroys_what_it_damages_past_regeneration(set_pool):
    """"Whenever Phage deals combat damage to a creature, destroy that
    creature. It can't be regenerated." Drudge Skeletons with two shields
    spends one on the lethal combat damage and the second cannot save it from
    the trigger; a Wall of Stone that survives the damage is destroyed too."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    skeletons = _w1g7_put(game, set_pool, 1, "Drudge Skeletons")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    for _ in range(2):
        assert game.activate_permanent_ability(
            1, "Drudge Skeletons",
            permanent_index=game.battlefield_index_of(skeletons),
        ).supported
        _w1g7_resolve_stack(game)
    _w1g7_finish_combat(game)
    assert "Drudge Skeletons regenerated" in game.log
    assert "Phage the Untouchable destroyed Drudge Skeletons" in game.log
    assert _w1g7_names(game.players[1].graveyard) == ["Drudge Skeletons"]

    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_put(game, set_pool, 1, "Wall of Stone")
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_finish_combat(game)
    assert _w1g7_names(game.players[1].graveyard) == ["Wall of Stone"]
    assert not game.players[1].lost


def test_w1g7_phage_unblocked_makes_the_damaged_player_lose(set_pool):
    """"Whenever Phage deals combat damage to a player, that player loses the
    game." Bob takes four and loses; Alice, who cast Phage, does not."""
    game = _w1g7_table(set_pool, hands={0: ["Phage the Untouchable"]})
    assert game.cast_from_hand(0, "Phage the Untouchable").supported
    _w1g7_resolve_stack(game)
    _w1g7_declare_attack(game, 0)
    _w1g7_finish_combat(game)
    assert game.players[1].life == 16
    assert game.players[1].lost
    assert not game.players[0].lost

# ==== end W1G7 ======================================================
