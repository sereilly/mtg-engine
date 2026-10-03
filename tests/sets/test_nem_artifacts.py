"""Nemesis artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: fading ---
# Fading (CR 702.32) is the rewrite in `engine/fading.py`; its rules tests are
# tests/rules/test_fading.py. These drive the Nemesis artifacts that print it.
from engine import Game as _W1G1AGame
from engine.models import Permanent as _W1G1APermanent
from engine.models import PlayerState as _W1G1APlayerState
from engine.named_counters import counters_on as _w1g1a_counters_on

from tests.helpers import resolve_stack as _w1g1a_resolve_stack


def _w1g1a_duel() -> "_W1G1AGame":
    game = _W1G1AGame(players=[
        _W1G1APlayerState(name="P1", life=20), _W1G1APlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game


def _w1g1a_upkeep(game, seat: int) -> None:
    game.turn += 1
    game.begin_turn_bookkeeping(seat)
    game.resolve_upkeep(seat)
    _w1g1a_resolve_stack(game)
    for perm in game.all_permanents():
        perm.tapped = False


def test_w1g1_rejuvenation_chamber_gains_life_until_it_fades_out(set_pool):
    """"Fading 2" and "{T}: You gain 2 life." It reported supported before the
    rewrite with its fading line unread — a life-gain rock that never left.
    Now it taps for 2 life on each of three turns and is sacrificed at its
    controller's third upkeep."""
    game = _w1g1a_duel()
    p1 = game.players[0]
    p1.hand = [set_pool("NEM")["Rejuvenation Chamber"]]
    assert game.cast_from_hand(0, "Rejuvenation Chamber").supported
    _w1g1a_resolve_stack(game)
    [chamber] = [p for p in p1.battlefield if p.card.name == "Rejuvenation Chamber"]
    assert _w1g1a_counters_on(chamber, "fade") == 2

    for expected_life in (22, 24, 26):
        assert game.activate_permanent_ability(0, "Rejuvenation Chamber").supported
        _w1g1a_resolve_stack(game)
        assert p1.life == expected_life
        _w1g1a_upkeep(game, 1)
        _w1g1a_upkeep(game, 0)

    assert not game.is_on_battlefield(chamber)
    assert [c.name for c in p1.graveyard] == ["Rejuvenation Chamber"]
    assert "Rejuvenation Chamber was sacrificed" in game.log


def _w1g1a_wire_game(set_pool, *, interactive=()):
    """Tangle Wire on P1's side, entered through the seam with its four
    counters, and P2's turn begun — so the next call is P2's upkeep."""
    game = _w1g1a_duel()
    game.interactive_seats = set(interactive)
    wire = _W1G1APermanent(card=set_pool("NEM")["Tangle Wire"])
    game._put_permanent_onto_battlefield(0, wire, None)
    return game, wire


def _w1g1a_board(game, seat: int, set_pool, names) -> list:
    """Permanents with no upkeep triggers of their own (Alpha's Forest and
    Sol Ring), so the only thing on the stack at an upkeep is the Wire."""
    lea = set_pool("LEA")
    out = []
    for name in names:
        perm = _W1G1APermanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        out.append(perm)
    return out


def test_w1g1_tangle_wire_taps_one_of_the_upkeep_players_permanents_per_counter(set_pool):
    """"At the beginning of each player's upkeep, **that player** taps an
    untapped artifact, creature, or land they control for each fade counter on
    this artifact." On the opponent's upkeep it is the opponent who taps — four
    of their five permanents, none of the Wire controller's."""
    game, wire = _w1g1a_wire_game(set_pool)
    theirs = _w1g1a_board(game, 1, set_pool, ["Sol Ring"] * 2 + ["Forest"] * 3)

    _w1g1a_upkeep(game, 1)

    # `_w1g1a_upkeep` untaps after resolving, so read the log's record.
    assert "Tangle Wire tapped Sol Ring, Sol Ring, Forest, Forest" in game.log
    assert _w1g1a_counters_on(wire, "fade") == 4, "not its controller's upkeep"
    assert all(game.is_on_battlefield(p) for p in theirs)


def test_w1g1_tangle_wire_taps_everything_when_the_player_has_too_little(set_pool):
    """Four counters and two permanents: they tap both (CR 609.3) rather than
    the prompt asking for four and getting nothing."""
    game, _wire = _w1g1a_wire_game(set_pool)
    theirs = _w1g1a_board(game, 1, set_pool, ["Forest", "Sol Ring"])
    game.turn += 1
    game.begin_turn_bookkeeping(1)

    game.resolve_upkeep(1)
    _w1g1a_resolve_stack(game)

    assert [p.tapped for p in theirs] == [True, True]


def test_w1g1_tangle_wire_never_offers_an_already_tapped_permanent(set_pool):
    """"An **untapped** artifact, creature, or land": a permanent that is
    already tapped is not a choice, so it cannot be used to soak a counter.
    With two of five already tapped, the other three are the whole offer."""
    game, _wire = _w1g1a_wire_game(set_pool, interactive=(1,))
    theirs = _w1g1a_board(game, 1, set_pool, ["Forest"] * 5)
    game.turn += 1
    game.begin_turn_bookkeeping(1)
    theirs[0].tapped = theirs[1].tapped = True

    game.resolve_upkeep(1)

    [owed] = game.pending_choices
    offered = {p.permanent_id for p in game.live_permanent_set_choices(owed)}
    assert offered == {p.permanent_id for p in theirs[2:]}
    assert (owed.data["up_to"], owed.data["at_least"]) == (4, 3)


def test_w1g1_tangle_wire_asks_an_interactive_player_which_to_tap(set_pool):
    """The upkeep player chooses — a prompt the stack waits on — and a short
    answer is refused, since "for each" says how many are tapped, not how many
    may be."""
    game, _wire = _w1g1a_wire_game(set_pool, interactive=(1,))
    theirs = _w1g1a_board(game, 1, set_pool, ["Forest"] * 5)
    game.turn += 1
    game.begin_turn_bookkeeping(1)

    game.resolve_upkeep(1)

    assert [item.card.name for item in game.stack] == ["Tangle Wire"]
    [owed] = game.pending_choices
    assert owed.player_index == 1
    assert not game.confirm_permanent_set_choice(
        1, [p.permanent_id for p in theirs[:3]]
    )
    assert game.confirm_permanent_set_choice(
        1, [p.permanent_id for p in theirs[1:]]
    )
    _w1g1a_resolve_stack(game)

    assert [p.tapped for p in theirs] == [False, True, True, True, True]
    assert game.stack == []


def test_w1g1_tangle_wire_counts_the_counters_left_when_it_resolves(set_pool):
    """The number is read at resolution off the pile on the Wire, so on its
    controller's upkeep — two triggers — the count depends on which resolves
    first. The engine keeps one controller's simultaneous triggers in printed
    order (it does not yet offer CR 603.3b's choice), so the Wire's tap
    resolves on top of the fade removal and counts four; and on the next of
    the controller's upkeeps, three."""
    game, wire = _w1g1a_wire_game(set_pool)
    mine = _w1g1a_board(game, 0, set_pool, ["Forest"] * 5)

    game.turn += 1
    game.begin_turn_bookkeeping(1)
    game.resolve_upkeep(1)
    _w1g1a_resolve_stack(game)
    game.turn += 1
    game.begin_turn_bookkeeping(0)
    for perm in game.all_permanents():
        perm.tapped = False
    game.resolve_upkeep(0)
    _w1g1a_resolve_stack(game)

    tapped_now = sum(p.tapped for p in (*mine, wire))
    assert tapped_now == 4
    assert _w1g1a_counters_on(wire, "fade") == 3

# --- end W1G1 ---
