"""Mercadian Masques artifacts.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: upkeep and end-step triggers ---
#
# Two artifacts, both of which parsed cleanly on `main` and were refused one
# layer down: the mill on a phrase the *draw* one family over already read, and
# the Atlas on a CR 603.4 condition nothing had a node for.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4a_card(name, type_line="Basic Land - Forest"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name},
    )


def _g4a_duel(set_pool):
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4a_run(game):
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()


def test_worry_beads_mills_the_seat_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** mills a
    card." The seat is the one the upkeep announcement froze - the same record
    the damage recipient and the draw's own reader already take of the same two
    words, and the reading the mill's comment claimed it took and did not."""
    game, p1, p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Worry Beads"]))
    p1.library = [_g4a_card("a0"), _g4a_card("a1")]
    p2.library = [_g4a_card("b0"), _g4a_card("b1")]
    game._sync_control()

    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert p2.graveyard == []

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert [card.name for card in p2.graveyard] == ["b0"]


def test_mercadian_atlas_draws_only_on_a_landless_turn(set_pool):
    """"At the beginning of your end step, **if you didn't play a land this
    turn**, you may draw a card." CR 603.4 checks the condition when the
    trigger would fire, so a turn with a land drop puts nothing on the stack at
    all."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 0
    game.resolve_end_step(0)
    _g4a_run(game)

    assert [card.name for card in p1.hand] == ["top"]


def test_a_land_drop_silences_mercadian_atlas(set_pool):
    """The other half of the same gate, read off the per-seat per-turn tally
    the land-play path writes - never off the board, because by the end step a
    land played this turn is an ordinary permanent."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 1
    game.resolve_end_step(0)
    _g4a_run(game)

    assert p1.hand == []
    assert [card.name for card in p1.library] == ["top", "next"]
