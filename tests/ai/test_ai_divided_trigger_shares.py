"""A divided trigger's announcement by a seat nobody asks, where the counters
it divides lower toughness: split by what the shares kill.

"When this creature dies, distribute three -1/-1 counters among one, two, or
three target creatures. For each -1/-1 counter you put on a creature this
way, remove a -1/-1 counter from that creature at the beginning of the next
end step." (Shambling Swarm, Torment — the pool's only divided trigger.)

Reviewed into the AI's divided-card inventory at Torment's promotion
rehearsal, by running it. Its side was right (the opponent's creatures) and
its split was not: one counter apiece over the first three creatures the
offer listed, so over a Hill Giant, a Craw Wurm, a Grizzly Bears and a
Llanowar Elves — in that order — it killed nothing, and on its controller's
own board it killed the Savannah Lions it was offered first beside a Hill
Giant that would have lived. The counters come back off, so a share is worth
what it kills. Validated backwards: on the tree before, the first two tests
below fail with every creature alive, and the third with the Lions dead.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import divided_shrink_shares, least_harmed_permanent
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, own=(), opponents=()):
    """Seat 0's Shambling Swarm beside *own*, seat 1's *opponents*, and a
    Lightning Bolt in seat 1's hand; nobody is asked anything."""
    lea, tor = set_pool("LEA"), set_pool("TOR")
    pool = {**lea, **tor}
    game = Game(players=[
        PlayerState("A", library=[lea["Forest"]] * 10),
        PlayerState("B", library=[lea["Forest"]] * 10, hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = {}
    for seat, names in ((0, ("Shambling Swarm", *own)), (1, opponents)):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            placed[name] = permanent
    return game, placed


def _kill_the_swarm(game, placed):
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["Shambling Swarm"].permanent_id],
    )
    assert bolt.supported, bolt.details
    resolve_stack(game)
    game.check_state_based_actions()


def _alive(game, placed, *names):
    return {name: game.is_on_battlefield(placed[name]) for name in names}


def test_the_swarm_kills_what_its_counters_can_kill(set_pool):
    """Four creatures, offered Giant, Wurm, Bears, Elves: 1 + 2 kills the
    Elves and the Bears, and neither of the two it cannot kill is named."""
    game, placed = _table(set_pool, opponents=(
        "Hill Giant", "Craw Wurm", "Grizzly Bears", "Llanowar Elves",
    ))
    _kill_the_swarm(game, placed)
    assert _alive(game, placed, "Hill Giant", "Craw Wurm", "Grizzly Bears",
                  "Llanowar Elves") == {
        "Hill Giant": True, "Craw Wurm": True,
        "Grizzly Bears": False, "Llanowar Elves": False,
    }
    assert placed["Hill Giant"].metadata.get("minus_counters", 0) == 0
    assert placed["Craw Wurm"].metadata.get("minus_counters", 0) == 0


def test_two_killed_where_a_spread_killed_one(set_pool):
    """Elves, Bears and Giant: one apiece killed the Elves alone."""
    game, placed = _table(set_pool, opponents=(
        "Llanowar Elves", "Grizzly Bears", "Hill Giant",
    ))
    _kill_the_swarm(game, placed)
    assert _alive(game, placed, "Llanowar Elves", "Grizzly Bears", "Hill Giant") == {
        "Llanowar Elves": False, "Grizzly Bears": False, "Hill Giant": True,
    }


def test_on_its_own_board_the_total_goes_where_it_harms_least(set_pool):
    """No opponent creature: the target is still owed (CR 603.3d), and the
    whole total goes on one of its controller's own — a Serra Angel lives
    through three counters, so it takes them and the Lions is spared; where
    both would die, the one worth less does."""
    game, placed = _table(set_pool, own=("Savannah Lions", "Serra Angel"))
    _kill_the_swarm(game, placed)
    assert _alive(game, placed, "Savannah Lions", "Serra Angel") == {
        "Savannah Lions": True, "Serra Angel": True,
    }
    assert placed["Serra Angel"].metadata.get("minus_counters", 0) == 3

    game, placed = _table(set_pool, own=("Hill Giant", "Savannah Lions"))
    _kill_the_swarm(game, placed)
    assert _alive(game, placed, "Hill Giant", "Savannah Lions") == {
        "Hill Giant": True, "Savannah Lions": False,
    }


def test_the_shares_are_a_lawful_division(set_pool):
    """Every share at least one, the shares totalling the printed number, no
    more targets than the ceiling (CR 601.2d) — and nothing to say for a
    counter that lowers no toughness, or a board where no share kills."""
    game, placed = _table(set_pool, opponents=(
        "Craw Wurm", "Llanowar Elves", "Grizzly Bears", "Hill Giant",
    ))
    ids = [placed[name].permanent_id for name in (
        "Craw Wurm", "Llanowar Elves", "Grizzly Bears", "Hill Giant",
    )]
    for total in range(1, 7):
        for ceiling in range(1, 4):
            shares = divided_shrink_shares(game, ids, total, ceiling, "-1/-1")
            assert shares, (total, ceiling)
            assert sum(share for _, share in shares) == total
            assert all(share >= 1 for _, share in shares)
            assert len(shares) <= ceiling
            assert len({permanent_id for permanent_id, _ in shares}) == len(shares)
    assert divided_shrink_shares(game, ids, 3, 3, "+1/+1") is None
    assert divided_shrink_shares(game, ids[:1], 3, 3, "-1/-1") is None
    assert least_harmed_permanent(game, ids, 3, "+1/+1") is None
