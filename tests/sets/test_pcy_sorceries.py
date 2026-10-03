"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_creature_card(name):
    return _w1g6_mk_card(name, "Creature — Beast")


def _w1g6_elephants(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Elephant Token"]


def test_w1g6_elephant_resurgence_sizes_each_token_by_its_controllers_graveyard(set_pool):
    """"Each player creates a green Elephant creature token. Those creatures
    have "This token's power and toughness are each equal to the number of
    creature cards in its controller's graveyard."" Each token counts its own
    controller's pile, and keeps counting it."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Elephant Resurgence"]],
            graveyard=[_w1g6_creature_card("Elk"), _w1g6_creature_card("Ox")],
        ),
        _W1G6PlayerState(
            name="P1",
            graveyard=[_w1g6_creature_card("Yak"), _w1g6_mk_card("Forest", "Basic Land — Forest")],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.cast_from_hand(0, "Elephant Resurgence").supported
    _w1g6_resolve(game)

    (mine,), (theirs,) = _w1g6_elephants(game, 0), _w1g6_elephants(game, 1)
    assert mine.metadata.get("is_token") and theirs.metadata.get("is_token")
    assert "G" in mine.effective_colors
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1)

    # A creature of P1's dies: P1's token grows, P0's does not.
    gnu = _W1G6Permanent(card=_w1g6_creature_card("Gnu"))
    game._put_permanent_onto_battlefield(1, gnu, None)
    game.sacrifice_permanent(gnu)
    game._refresh_dynamic_creatures()
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert mine.effective_power == 2


def _w1g6_denying_wind_table(set_pool):
    library = [_w1g6_mk_card(f"Card {n}", "Sorcery") for n in range(10)]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[set_pool("PCY")["Denying Wind"]]),
        _W1G6PlayerState(name="P1", library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Denying Wind", target_player_index=1).supported
    return game  # _w1g6_denying_wind_table


def test_w1g6_denying_wind_exiles_up_to_seven_from_the_targets_library(set_pool):
    """"Search target player's library for up to seven cards and exile them.
    Then that player shuffles." The caster searches the *target's* library and
    may stop short of seven: three picks are a legal answer."""
    game = _w1g6_denying_wind_table(set_pool)
    game.interactive_seats = {0}
    _w1g6_resolve(game)
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert game.pending_choices[0].data.get("count") == 7
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 4, 9)]
    )
    _w1g6_resolve(game)
    assert sorted(c.name for c in game.players[1].exile) == ["Card 0", "Card 4", "Card 9"]
    assert len(game.players[1].library) == 7
    assert not game.players[0].exile and not game.players[0].library


def test_w1g6_denying_wind_default_takes_at_most_seven(set_pool):
    game = _w1g6_denying_wind_table(set_pool)
    _w1g6_resolve(game)
    exiled = len(game.players[1].exile)
    assert 0 <= exiled <= 7
    assert exiled + len(game.players[1].library) == 10
