"""Invasion sorceries.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: kicker ---
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_sorcery_duel(set_pool, name, pool):
    """Seat 0 holds the INV sorcery *name* with *pool* floating; costs are
    charged, because a kicker is a price."""
    lea = set_pool("LEA")
    mine = _W1G1PlayerState(
        "Caster", library=[lea["Forest"]] * 10, hand=[set_pool("INV")[name]],
    )
    theirs = _W1G1PlayerState("Victim", library=[lea["Forest"]] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    return game  # _w1g1_sorcery_duel


def _w1g1_board(game, set_pool):
    """A walker and a flier for the other seat, a walker for the caster."""
    lea = set_pool("LEA")
    placed = {}
    for seat, name in ((1, "Hill Giant"), (1, "Serra Angel"), (0, "Grizzly Bears")):
        permanent = _W1G1Permanent(card=lea[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        placed[name] = permanent
    return placed  # _w1g1_board


def _w1g1_settle(game):
    """Resolve the stack and answer what the resolution asked (Probe's own
    discard is a prompt owed after the spell has left the stack)."""
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)  # _w1g1_settle


def test_w1g1_probe_kicked_makes_the_target_player_discard_two(set_pool):
    """"Draw three cards, then discard two cards. If this spell was kicked,
    target player discards two cards." Both halves, in the order written."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    game.players[1].hand.extend([lea["Mountain"], lea["Island"], lea["Swamp"]])
    result = game.cast_from_hand(
        0, "Probe", optional_cost_payments={"{1}{B}": 1}, target_player_index=1,
    )
    assert result.supported, result
    _w1g1_settle(game)

    assert len(game.players[0].hand) == 1          # drew 3, discarded 2
    assert len(game.players[0].graveyard) == 3     # two discards and Probe
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2


def test_w1g1_probe_unkicked_touches_nobody_else(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    game.players[1].hand.extend([lea["Mountain"], lea["Island"], lea["Swamp"]])
    result = game.cast_from_hand(0, "Probe")
    assert result.supported, result
    _w1g1_settle(game)

    assert len(game.players[0].hand) == 1
    assert len(game.players[1].hand) == 3
    assert game.players[1].graveyard == []
    assert sum(game.players[0].mana_pool.values()) == 2


def test_w1g1_probe_names_a_player_only_when_kicked(set_pool):
    """CR 702.33g: the kicked-only part's target is chosen only if the spell
    was kicked. The spec a player is shown asks for nobody until the kicker is
    taken, and then for a player."""
    card = set_pool("INV")["Probe"]
    game = _w1g1_sorcery_duel(set_pool, "Probe", {"U": 3, "B": 2})
    plain = game.cast_target_spec(0, card)
    assert (plain["kind"], plain["requires_target"]) == ("none", False)
    assert [offer["label"] for offer in plain["cost_offers"]] == ["kicker"]

    kicked = game.cast_target_spec(0, card, optional_cost_payments={"{1}{B}": 1})
    assert (kicked["kind"], kicked["requires_target"]) == ("player", True)
    assert len(kicked["valid_targets"]) == 2


@_w1g1_pytest.mark.parametrize(
    "name,colour,kicked_dies,spared",
    [
        # "…to each creature **without** flying and each player."
        ("Breath of Darigaaz", "R", ("Hill Giant", "Grizzly Bears"), ("Serra Angel",)),
        # "…to each creature **with** flying and each player."
        ("Canopy Surge", "G", ("Serra Angel",), ("Hill Giant", "Grizzly Bears")),
    ],
)
def test_w1g1_the_instead_sweepers_deal_one_or_four(
    set_pool, name, colour, kicked_dies, spared
):
    """"<This> deals 1 damage to each creature … and each player. If this spell
    was kicked, it deals 4 damage … **instead**." One or the other, never both:
    unkicked nothing dies and each player loses 1; kicked the named half of the
    board dies and each player loses 4."""
    plain = _w1g1_sorcery_duel(set_pool, name, {colour: 4})
    board = _w1g1_board(plain, set_pool)
    assert plain.cast_from_hand(0, name).supported
    _w1g1_settle(plain)
    assert all(plain.is_on_battlefield(p) for p in board.values())
    assert [player.life for player in plain.players] == [19, 19]
    assert sum(plain.players[0].mana_pool.values()) == 2

    kicked = _w1g1_sorcery_duel(set_pool, name, {colour: 4})
    board = _w1g1_board(kicked, set_pool)
    assert kicked.cast_from_hand(
        0, name, optional_cost_payments={"{2}": 1}
    ).supported
    _w1g1_settle(kicked)
    assert [player.life for player in kicked.players] == [16, 16]
    for creature in kicked_dies:
        assert not kicked.is_on_battlefield(board[creature])
    for creature in spared:
        assert kicked.is_on_battlefield(board[creature])


def test_w1g1_hypnotic_cloud_is_one_card_or_three_never_four(set_pool):
    """"Target player discards a card. If this spell was kicked, **that
    player** discards three cards **instead**." One discard of one size from
    the one player the spell names."""
    lea = set_pool("LEA")
    for kick, left in ((None, 3), ("{4}", 1)):
        game = _w1g1_sorcery_duel(set_pool, "Hypnotic Cloud", {"B": 6})
        game.players[1].hand.extend(
            [lea["Mountain"], lea["Island"], lea["Swamp"], lea["Plains"]]
        )
        spec = game.cast_target_spec(
            0, set_pool("INV")["Hypnotic Cloud"],
            optional_cost_payments={kick: 1} if kick else None,
        )
        assert spec["kind"] == "player" and "max_targets" not in spec
        result = game.cast_from_hand(
            0, "Hypnotic Cloud",
            optional_cost_payments={kick: 1} if kick else None,
            target_player_index=1,
        )
        assert result.supported, result
        _w1g1_settle(game)
        assert len(game.players[1].hand) == left
        assert len(game.players[1].graveyard) == 4 - left
        assert game.players[0].hand == []
# end of the W1G1 sorceries block
