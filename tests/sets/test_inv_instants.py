"""Invasion instants.

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


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_cast_spec as _w1g8_cast_spec
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_instant_duel(set_pool, *, active: int = 0, library: int = 10):
    """Two seats, costs off, each with *library* Islands to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g8_instant_put(game, set_pool, seat: int, name: str, code: str = "LEA"):
    """*name* on *seat*'s battlefield, free of summoning sickness."""
    permanent = _W1G8Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.summoning_sick = False
    return permanent


def _w1g8_instant_names(game, seat: int) -> list[str]:
    """The names on *seat*'s battlefield, through the control seam."""
    return sorted(
        permanent.effective_card.name
        for permanent in game.controlled_by(game.players[seat])
    )


def test_winnow_destroys_a_permanent_with_a_namesake_and_draws(set_pool):
    """"Destroy target nonland permanent if another permanent with the same
    name is on the battlefield. / Draw a card." Two Grizzly Bears: the targeted
    one dies, the other stays, and the caster draws."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    twin = _w1g8_instant_put(game, set_pool, 0, "Grizzly Bears")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert not game.is_on_battlefield(target)
    assert game.is_on_battlefield(twin)
    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_winnow_spares_a_permanent_with_no_namesake_and_still_draws(set_pool):
    """The condition is checked on resolution (CR 608.2c) and guards the
    destroy alone: a lone Grizzly Bears survives, the card is still drawn."""
    game = _w1g8_instant_duel(set_pool)
    target = _w1g8_instant_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_instant_put(game, set_pool, 1, "Hill Giant")
    game.players[0].hand.append(set_pool("INV")["Winnow"])

    assert game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert game.is_on_battlefield(target)
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert not any("Destroyed" in line for line in game.log)


def test_winnow_offers_nonland_permanents_and_refuses_a_land(set_pool):
    """"target **nonland** permanent" reaches the picker and the announcement
    gate: two Forests share a name and neither can be named."""
    winnow = set_pool("INV")["Winnow"]
    assert _w1g8_cast_spec(winnow, _w1g8_compile(winnow)) == {
        "kind": "permanent", "filter": {"exclude_types": ["land"]},
    }
    game = _w1g8_instant_duel(set_pool)
    forest = _w1g8_instant_put(game, set_pool, 1, "Forest")
    _w1g8_instant_put(game, set_pool, 1, "Forest")
    game.players[0].hand.append(winnow)

    assert not game.cast_from_hand(
        0, "Winnow", target_permanent_ids=[forest.permanent_id],
    ).supported
    assert game.is_on_battlefield(forest)
    assert game.players[0].hand == [winnow]
