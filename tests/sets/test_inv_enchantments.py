"""Invasion enchantments.

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
from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_infested_duel(set_pool, *, infestations=(1,)):
    """Both seats hold a Faerie Squadron ({U}, kicker {3}{U}) and the mana to
    kick it; Saproling Infestation sits on each seat in *infestations*."""
    inv = set_pool("INV")
    forest = set_pool("LEA")["Forest"]
    seats = [
        _W1G1PlayerState(name, library=[forest] * 10, hand=[inv["Faerie Squadron"]])
        for name in ("Caster", "Watcher")
    ]
    game = _W1G1Game(players=seats)
    game.enforce_mana_costs = True
    for seat in (0, 1):
        game.players[seat].mana_pool["U"] = 5
    for seat in infestations:
        game._put_permanent_onto_battlefield(
            seat, _W1G1Permanent(card=inv["Saproling Infestation"]), None
        )
    return game  # _w1g1_infested_duel


def _w1g1_saprolings(game, seat: int) -> int:
    return sum(
        1 for p in game.controlled_by(seat) if p.card.name == "Saproling Token"
    )  # _w1g1_saprolings


def test_w1g1_saproling_infestation_answers_a_kicked_spell(set_pool):
    """"Whenever a player kicks a spell, you create a 1/1 green Saproling
    creature token." CR 702.33d: the spell is kicked as it is cast, so the
    trigger goes on the stack above it and resolves first — and "you" is the
    enchantment's controller, whoever did the kicking."""
    game = _w1g1_infested_duel(set_pool)
    result = game.queue_from_hand(
        0, "Faerie Squadron", optional_cost_payments={"{3}{U}": 1}
    )
    assert result.supported, result
    # The spell and, above it, the trigger it caused.
    assert [item.card.name for item in game.stack] == [
        "Faerie Squadron", "Saproling Infestation",
    ]
    assert game.resolve_top_of_stack()
    assert (_w1g1_saprolings(game, 0), _w1g1_saprolings(game, 1)) == (0, 1)
    token = next(p for p in game.controlled_by(1) if p.card.name == "Saproling Token")
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.is_creature and token.has_type("saproling")
    _w1g1_resolve_stack(game)
    assert _w1g1_saprolings(game, 1) == 1


def test_w1g1_saproling_infestation_ignores_a_spell_that_was_not_kicked(set_pool):
    """The same card cast for its mana cost alone is a spell with kicker that
    was not kicked: nothing triggers, nothing goes on the stack above it."""
    game = _w1g1_infested_duel(set_pool)
    result = game.queue_from_hand(0, "Faerie Squadron")
    assert result.supported, result
    assert [item.card.name for item in game.stack] == ["Faerie Squadron"]
    _w1g1_resolve_stack(game)
    assert (_w1g1_saprolings(game, 0), _w1g1_saprolings(game, 1)) == (0, 0)


def test_w1g1_saproling_infestation_watches_its_own_controller_too(set_pool):
    """"A player" is any player. With one on each side, one kicked spell makes
    each controller a Saproling."""
    game = _w1g1_infested_duel(set_pool, infestations=(0, 1))
    result = game.cast_from_hand(
        1, "Faerie Squadron", optional_cost_payments={"{3}{U}": 1}
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    assert (_w1g1_saprolings(game, 0), _w1g1_saprolings(game, 1)) == (1, 1)
# end of the W1G1 enchantments block
