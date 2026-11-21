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

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

from engine import Game as _W1G10Game
from engine.cast_permissions import playable_from_zones as _w1g10_playable
from engine.models import Permanent as _W1G10Permanent
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_kanzashi_table(set_pool, opponent_library):
    """Alice controls an untapped Ornate Kanzashi; Bob's library is as given."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    kanzashi = _W1G10Permanent(card=bok["Ornate Kanzashi"])
    game = _W1G10Game(players=[
        _W1G10PlayerState(name="Alice", battlefield=[kanzashi],
                          library=[lea["Island"]] * 10),
        _W1G10PlayerState(name="Bob", library=[lea[name] for name in opponent_library]),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def test_w1g10_ornate_kanzashi_exiles_the_opponents_top_card_to_play(set_pool):
    """Ornate Kanzashi: "{2}, {T}: Target opponent exiles the top card of their
    library. You may play that card this turn." Bob's Grizzly Bears goes to
    Bob's exile (CR 406.3, its owner's) face up (2005-02-01 ruling); Alice may
    cast it and it enters under her control; Bob may not."""
    game = _w1g10_kanzashi_table(set_pool, ["Grizzly Bears", "Island"])
    alice, bob = game.players
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    assert [card.name for card in bob.exile] == ["Grizzly Bears"]
    assert any("Bob exiled Grizzly Bears from the top of their library" in line
               for line in game.log)
    assert [(e["zone"], e["name"]) for e in _w1g10_playable(game, 0)] == [
        ("exile", "Grizzly Bears"),
    ]
    assert _w1g10_playable(game, 1) == []
    cast = game.cast_from_hand(0, "Grizzly Bears", from_zone="exile")
    assert cast.supported, cast.details
    _w1g10_settle(game)
    assert "Grizzly Bears" in [perm.card.name for perm in game.controlled_by(0)]
    assert bob.exile == []


def test_w1g10_ornate_kanzashi_plays_a_land_and_the_grant_ends_this_turn(set_pool):
    """"Play" includes a land (CR 305.1, with the land drop); and "You can't play
    cards you exiled with Ornate Kanzashi on previous turns" (2005-02-01): a
    card not played stays exiled and is closed once the turn ends."""
    game = _w1g10_kanzashi_table(set_pool, ["Forest", "Lightning Bolt", "Island"])
    alice, bob = game.players
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    played = game.cast_from_hand(0, "Forest", from_zone="exile")
    assert played.supported, played.details
    assert "Forest" in [perm.card.name for perm in game.controlled_by(0)]
    game.players[0].battlefield[0].tapped = False
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    assert [card.name for card in bob.exile] == ["Lightning Bolt"]
    assert [e["name"] for e in _w1g10_playable(game, 0)] == ["Lightning Bolt"]
    game.resolve_cleanup_step(0)
    game.start_next_turn()
    _w1g10_settle(game)
    game.resolve_cleanup_step(1)
    game.start_next_turn()
    _w1g10_settle(game)
    assert _w1g10_playable(game, 0) == []
    assert [card.name for card in bob.exile] == ["Lightning Bolt"]

# ==== end w1g10 ======================================================
