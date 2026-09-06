"""Tempest creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G4: triggered abilities the engine had never fired ---

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent


def _w1g4_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _w1g4_perm(card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g4_upkeep(board, opposing=()):
    p1 = PlayerState(name="P1", battlefield=list(board))
    p2 = PlayerState(name="P2", battlefield=list(opposing))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return game, p1, p2


# -- Kezzerdrix -------------------------------------------------------------


def test_kezzerdrix_burns_you_while_your_opponents_have_no_creatures(set_pool):
    """"At the beginning of your upkeep, if your opponents control no
    creatures, this creature deals 4 damage to you."

    CR 603.4 over a per-seat board count. "Your opponents" is CR 102.2/102.3's
    set — every player who is not you — which is the same set "each opponent"
    already names, so it is a spelling rather than a fourth referent.
    """
    game, p1, _ = _w1g4_upkeep([_w1g4_perm(set_pool("TMP")["Kezzerdrix"])])

    assert p1.life == 16


def test_kezzerdrix_is_silent_while_an_opponent_has_a_creature(set_pool):
    game, p1, _ = _w1g4_upkeep(
        [_w1g4_perm(set_pool("TMP")["Kezzerdrix"])],
        [_w1g4_perm(_w1g4_lea()["Grizzly Bears"])],
    )

    assert p1.life == 20


def test_kezzerdrix_ignores_creatures_you_control(set_pool):
    """The clause names *your opponents*' boards, so your own creature does not
    switch it off — the narrowing a seat-blind board count would drop.
    """
    game, p1, _ = _w1g4_upkeep([
        _w1g4_perm(set_pool("TMP")["Kezzerdrix"]),
        _w1g4_perm(_w1g4_lea()["Grizzly Bears"]),
    ])

    assert p1.life == 16
