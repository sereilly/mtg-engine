"""Planeshift instants.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: two kickers ---
# Ertai's Trickery — "Counter target spell if it was kicked." Supported on
# arrival and countering nothing: the pronoun was read as the spell asking, and
# Ertai's Trickery prints no kicker.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.cast_costs import kicked as _w1g2_kicked
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_counter_table(set_pool, spell_name, spell_set):
    """Seat 0 holds *spell_name*, seat 1 holds Ertai's Trickery; both have mana
    floating and costs are charged."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Kicker", library=[forest] * 10, hand=[set_pool(spell_set)[spell_name]],
        ),
        _W1G2PlayerState(
            "Ertai", library=[forest] * 10,
            hand=[set_pool("PLS")["Ertai's Trickery"]],
        ),
    ])
    game.enforce_mana_costs = True
    for seat in (0, 1):
        game.players[seat].mana_pool.update(
            {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}
        )
    return game  # _w1g2_counter_table


def _w1g2_trick(game, spell_name, kick=None, **announced):
    """Seat 0 casts *spell_name* (paying the costs in *kick*), seat 1 answers
    with Ertai's Trickery aimed at it, and everything resolves. Returns whether
    the spell on the stack was a kicked one."""
    assert game.queue_from_hand(
        0, spell_name, optional_cost_payments=kick, **announced
    ).supported
    item = game.stack[-1]
    was_kicked = _w1g2_kicked(item.card, item.choices)
    answer = game.queue_from_hand(
        1, "Ertai's Trickery", target_stack_index=len(game.stack) - 1
    )
    assert answer.supported, answer
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].graveyard] == ["Ertai's Trickery"]
    return was_kicked  # _w1g2_trick


def test_w1g2_ertais_trickery_counters_a_kicked_spell_and_only_a_kicked_one(set_pool):
    """The pronoun is the *targeted* spell (CR 608.2c). A kicked Kavu Titan is
    countered; the same Titan cast for {1}{G} resolves, and the Trickery is
    spent either way."""
    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert _w1g2_trick(game, "Kavu Titan", {"{2}{G}": 1}) is True
    assert [c.name for c in game.players[0].graveyard] == ["Kavu Titan"]
    assert list(game.controlled_by(0)) == []

    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert _w1g2_trick(game, "Kavu Titan") is False
    assert [p.card.name for p in game.controlled_by(0)] == ["Kavu Titan"]
    assert game.players[0].graveyard == []


@_w1g2_pytest.mark.parametrize("kick,countered", [
    (None, False),
    ({"{1}{G}": 1}, True),
    ({"{2}{U}": 1}, True),
    ({"{1}{G}": 1, "{2}{U}": 1}, True),
])
def test_w1g2_ertais_trickery_reads_either_of_two_kickers(set_pool, kick, countered):
    """CR 702.33d: a spell is kicked if its controller paid **any** of its
    kicker costs. A Sunscape Battlemage that paid only its second is as kicked
    as one that paid both — and one that paid neither is not."""
    game = _w1g2_counter_table(set_pool, "Sunscape Battlemage", "PLS")
    assert _w1g2_trick(game, "Sunscape Battlemage", kick) is countered
    on_board = [p.card.name for p in game.controlled_by(0)]
    in_yard = [c.name for c in game.players[0].graveyard]
    if countered:
        assert (on_board, in_yard) == ([], ["Sunscape Battlemage"])
        # …and a countered Battlemage never entered, so nothing was drawn.
        assert game.players[0].hand == []
    else:
        assert (on_board, in_yard) == (["Sunscape Battlemage"], [])


def test_w1g2_ertais_trickery_does_not_take_another_optional_cost_for_a_kicker(set_pool):
    """Buyback is an optional additional cost too (CR 702.27a), and it is not a
    kicker: a bought-back Capsize is not countered, returns its target, and
    comes back to its owner's hand."""
    game = _w1g2_counter_table(set_pool, "Capsize", "TMP")
    forest = _W1G2Permanent(card=set_pool("LEA")["Forest"])
    game._put_permanent_onto_battlefield(1, forest, None)
    assert _w1g2_trick(
        game, "Capsize", {"{3}": 1}, target_permanent_ids=[forest.permanent_id]
    ) is False
    assert not game.is_on_battlefield(forest)
    assert [c.name for c in game.players[0].hand] == ["Capsize"]


def test_w1g2_ertais_trickery_may_be_aimed_at_any_spell(set_pool):
    """"Target spell" is the whole of the printed restriction (CR 608.2b), so
    the picker offers an unkicked spell too — the "if" is read as the Trickery
    resolves, not as it is announced."""
    game = _w1g2_counter_table(set_pool, "Kavu Titan", "INV")
    assert game.queue_from_hand(0, "Kavu Titan").supported
    spec = game.cast_target_spec(1, set_pool("PLS")["Ertai's Trickery"])
    assert spec["kind"] == "stack" and spec["requires_target"]
    assert len(spec["valid_targets"]) == 1
# end of the W1G2 instants block
