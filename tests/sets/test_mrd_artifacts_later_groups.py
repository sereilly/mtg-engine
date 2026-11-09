"""Mirrodin artifacts, the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Activated abilities on artifacts: Tel-Jilad Stylus's "target permanent you
# own", Scrabbling Claws' target player picking out of their own graveyard,
# and the mana rocks, Talismans and Towers this family drives.
from engine import Game as _W1G8Game
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_activation_spec as _w1g8_activation_spec

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_board(set_pool, mine, theirs=(), *, hand=()):
    """A duel at seat 0's first main phase, *mine* and *theirs* on the
    battlefield and ready to tap; mana costs off unless a test turns them on."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name="A", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G8PlayerState(name="B", library=[lea["Plains"]] * 8),
    ])
    game.enforce_mana_costs = False
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            perm = _W1G8Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            placed.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.current_step == "precombat_main"
    return game, placed


def test_w1g8_tel_jilad_stylus_offers_what_you_own_not_what_you_control(set_pool):
    """2004-12-01: it "may target a permanent you own but do not control". The
    picker offers the activator's own permanents and the one an opponent
    controls but the activator owns; an opponent's own permanent is refused
    before the {T} is paid; the target goes under its owner's library."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (stylus, bears, ring, giant, angel) = _w1g8_board(
        set_pool,
        [mrd["Tel-Jilad Stylus"], lea["Grizzly Bears"], lea["Sol Ring"]],
        [lea["Hill Giant"], lea["Serra Angel"]],
    )
    # The Angel is seat 0's card on seat 1's battlefield.
    angel.metadata["owner_player_index"] = 0
    ability = _w1g8_compile(stylus.card).activated_abilities[0]
    offered = {
        entry.get("name")
        for entry in game.activation_offer(0, stylus, ability)["valid_targets"]
    }
    assert offered == {"Tel-Jilad Stylus", "Grizzly Bears", "Sol Ring", "Serra Angel"}
    refused = game.activate_permanent_ability(
        0, "Tel-Jilad Stylus", target_permanent_ids=[giant.permanent_id]
    )
    assert not refused.supported and not stylus.tapped
    assert game.activate_permanent_ability(
        0, "Tel-Jilad Stylus", target_permanent_ids=[angel.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert not game.is_on_battlefield(angel)
    assert game.players[0].library[-1].name == "Serra Angel"
    assert [p.card.name for p in game.players[1].battlefield] == ["Hill Giant"]
    assert "Tel-Jilad Stylus: Serra Angel put on the bottom of A's library" in game.log


def test_w1g8_scrabbling_claws_target_player_picks_from_their_own_graveyard(set_pool):
    """"{T}: Target player exiles a card from their graveyard." The activation
    announces a player (the picker is a player picker, CR 601.2c); the card is
    that player's choice as the ability resolves — driven both as a default
    seat and as an interactive one answering the pick."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    ability = _w1g8_compile(claws.card).activated_abilities[0]
    assert _w1g8_activation_spec(ability) == {"kind": "player"}
    pile = [lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Island"]]
    game.players[1].graveyard = list(pile)
    game.players[0].graveyard = [lea["Plains"]]
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert len(game.players[1].graveyard) == 2
    assert len(game.players[1].exile) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Plains"]

    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    game.players[1].graveyard = list(pile)
    game.interactive_seats = {0, 1}
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    owed = [(c.kind, c.player_index) for c in game.pending_choices]
    assert owed == [("graveyard_exile_pick", 1)], owed
    assert game.resolve_pending_choice(
        "graveyard_exile_pick", 1, graveyard_indices=[1]
    )
    _w1g8_resolve_stack(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt", "Island"]
    assert "B exiled Grizzly Bears from B's graveyard (Scrabbling Claws)" in game.log


def test_w1g8_scrabbling_claws_on_an_empty_graveyard_exiles_nothing(set_pool):
    mrd = set_pool("MRD")
    game, (claws,) = _w1g8_board(set_pool, [mrd["Scrabbling Claws"]])
    assert game.activate_permanent_ability(
        0, "Scrabbling Claws", target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert claws.tapped and not game.players[1].exile
    assert not game.pending_choices

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
