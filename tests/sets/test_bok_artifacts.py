"""Betrayers of Kamigawa artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (settle as _w1g8_settle,
                           stock_libraries as _w1g8_stock_libraries)


def _w1g8_artifact_table(*mine):
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0"), _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game.enforce_mana_costs = True
    placed = []
    for each in mine:
        permanent = _w1g8_Permanent(card=each)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, placed


def test_w1g8_baku_altar_trades_a_ki_counter_for_a_spirit_token(set_pool):
    """"Whenever you cast a Spirit or Arcane spell, you may put a ki counter on
    this artifact. / {2}, {T}, Remove a ki counter from this artifact: Create a
    1/1 colorless Spirit creature token." A Spirit cast, the counter taken;
    {2} paid, the counter gone, a 1/1 colourless Spirit; with no counter the
    ability is refused with nothing paid."""
    from engine.named_counters import counters_on

    bok = set_pool("BOK")
    game, (altar,) = _w1g8_artifact_table(bok["Baku Altar"])
    game.players[0].hand.append(bok["Petalmane Baku"])
    game.players[0].mana_pool["G"] = 2
    assert game.cast_from_hand(0, "Petalmane Baku").supported
    _w1g8_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
    })
    assert counters_on(altar, "ki") == 1
    game.players[0].mana_pool["C"] = 2
    made = game.activate_permanent_ability(0, "Baku Altar")
    _w1g8_settle(game)
    assert made.supported, made.details
    assert counters_on(altar, "ki") == 0 and altar.tapped
    (token,) = [p for p in game.controlled_by(0) if p.card.name == "Spirit Token"]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.has_type("creature") and not token.card.colors
    altar.tapped = False
    game.players[0].mana_pool["C"] = 2
    assert not game.activate_permanent_ability(0, "Baku Altar").supported
    assert game.players[0].mana_pool["C"] == 2


def test_w1g8_slumbering_tora_becomes_a_cat_the_size_of_the_discard(set_pool):
    """"{2}, Discard a Spirit or Arcane card: This artifact becomes an X/X Cat
    artifact creature until end of turn, where X is the discarded card's mana
    value." Skullmane Baku (mana value 5) discarded — never the Grizzly Bears
    beside it — makes a 5/5 Cat artifact creature, an artifact again at
    cleanup."""
    from engine.object_creature_types import creature_types

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (tora,) = _w1g8_artifact_table(bok["Slumbering Tora"])
    game.players[0].hand.extend([bok["Skullmane Baku"], lea["Grizzly Bears"]])
    game.players[0].mana_pool["C"] = 2
    woke = game.activate_permanent_ability(0, "Slumbering Tora")
    _w1g8_settle(game)
    assert woke.supported, woke.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Skullmane Baku"]
    assert tora.is_creature and tora.has_type("artifact")
    assert (tora.effective_power, tora.effective_toughness) == (5, 5)
    assert creature_types(game, tora) == frozenset({"cat"})
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert not tora.is_creature and tora.has_type("artifact")

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
