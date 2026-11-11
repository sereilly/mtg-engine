"""Darksteel sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
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

from engine import Game as _w1g4_Game
from engine import PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from tests.helpers import settle as _w1g4_settle


def _w1g4_card(set_pool, name):
    """A card by name: Darksteel first, then Alpha, Odyssey and Mirrodin."""
    for code in ("DST", "LEA", "ODY", "MRD"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g4_table(set_pool, hand=(), *, mine=(), theirs=(), their_hand=(),
                graveyard=(), interactive=()):
    """Seat 0 to act in its first main phase, mana off, each named
    permanent untapped and able to act."""
    card = lambda name: _w1g4_card(set_pool, name)  # noqa: E731
    game = _w1g4_Game(players=[
        _w1g4_PlayerState("A", hand=[card(n) for n in hand],
                          graveyard=[card(n) for n in graveyard],
                          library=[card("Forest")] * 12),
        _w1g4_PlayerState("B", hand=[card(n) for n in their_hand],
                          library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g4_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def _w1g4_where(game, name):
    """Every zone holding a card called *name*, as ``"<seat>.<zone>"``."""
    return sorted(
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "graveyard", "library", "exile")
        for held in getattr(player, zone)
        if held.name == name
    )


def test_w1g4_pulse_of_the_dross_returns_while_the_target_holds_more(set_pool):
    """"Target player reveals three cards from their hand and you choose one
    of them. That player discards that card. Then if that player has more
    cards in hand than you, return Pulse of the Dross to its owner's hand."
    "That player" is the target: five cards, one discarded, four against the
    caster's none — the card comes back."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Dross"],
        their_hand=["Forest", "Island", "Swamp", "Mountain", "Plains"],
    )
    assert game.cast_from_hand(0, "Pulse of the Dross", target_player_index=1).supported
    _w1g4_settle(game)
    assert len(game.players[1].hand) == 4
    assert len(game.players[1].graveyard) == 1
    assert _w1g4_where(game, "Pulse of the Dross") == ["0.hand"]


def test_w1g4_pulse_of_the_dross_counts_the_hand_after_the_discard(set_pool):
    """Both seats answer for themselves: the target shows three of its two
    (it has only two), the caster picks the Swamp. Counted after the discard
    — one card against the caster's one — the target does not have more, so
    the card goes to the graveyard; counted before it, 2 > 1 would have
    returned it."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Dross", "Forest"], their_hand=["Island", "Swamp"],
        interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Pulse of the Dross", target_player_index=1).supported

    def _pick_the_swamp(game, choice):
        names = [game.players[1].hand[i].name for i in choice.data["legal_indices"]]
        assert sorted(names) == ["Island", "Swamp"]
        assert game.confirm_revealed_hand_pick(
            0, choice.data["legal_indices"][names.index("Swamp")]
        )

    _w1g4_settle(game, answers={"revealed_hand_pick": _pick_the_swamp})
    assert [c.name for c in game.players[1].graveyard] == ["Swamp"]
    assert [c.name for c in game.players[1].hand] == ["Island"]
    assert _w1g4_where(game, "Pulse of the Dross") == ["0.graveyard"]


def test_w1g4_pulse_of_the_tangle_returns_while_the_opponent_has_more_creatures(set_pool):
    """Drive list (supported on arrival, and it never returned). The Beast
    makes one creature against the opponent's two: the card comes back; with
    the opponent at one it is a tie and it does not."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Tangle"], theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Pulse of the Tangle").supported
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Beast Token"]
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.hand"]

    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Pulse of the Tangle"], theirs=["Grizzly Bears"],
    )
    game.cast_from_hand(0, "Pulse of the Tangle")
    _w1g4_settle(game)
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.graveyard"]


def test_w1g4_a_flashed_back_pulse_is_exiled_rather_than_returned(set_pool):
    """CR 702.34a: a spell whose flashback cost was paid is exiled "instead of
    putting it anywhere else any time it would leave the stack" — the Pulse's
    own return included. Recoup grants Pulse of the Tangle flashback; cast
    from the graveyard with the opponent ahead, it makes its Beast and goes to
    exile, not to the hand."""
    game, _mine, _theirs = _w1g4_table(
        set_pool, ["Recoup"], graveyard=["Pulse of the Tangle"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g4_settle(game)
    assert game.cast_from_hand(0, "Pulse of the Tangle", from_zone="graveyard").supported
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Beast Token"]
    assert _w1g4_where(game, "Pulse of the Tangle") == ["0.exile"]

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
