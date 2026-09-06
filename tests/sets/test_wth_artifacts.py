"""Weatherlight artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: each player, in parallel ---
from engine import Game, PlayerState
from engine.models import Permanent as _W1G5aPermanent
from engine.oracle import compile_card_oracle as _w1g5a_compile


def _w1g5a_well(set_pool):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[], library=[set_pool("LEA")["Island"]] * 10),
        PlayerState(name="P2", battlefield=[], library=[set_pool("LEA")["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    well = _W1G5aPermanent(card=set_pool("WTH")["Well of Knowledge"])
    game.players[0].battlefield.append(well)
    game._sync_control()
    return game


def _w1g5a_try(game, seat, step, active):
    """Activate the Well from *seat* in *step* of *active*'s turn."""
    game.current_step = step
    game.active_player_index = active
    before = len(game.players[seat].hand)
    result = game._activate_onto_stack(
        seat, "Well of Knowledge", source_controller_index=0,
    )
    game.resolve_stack()
    return result, len(game.players[seat].hand) - before


def test_well_of_knowledge_is_open_to_everyone_on_their_own_draw_step(set_pool):
    """"{2}: Draw a card. Any player may activate this ability but only during
    their draw step."

    Two claims in one sentence and `engine/activation_permissions.py` already
    carried the first: "any player may activate this ability" is a row there,
    read by the reachability check, the API and the client, and
    `permission_clause_readable` already split the "but only …" tail off to
    `activation_restrictions.py`. What was missing was the tail's row — so the
    card was unsupported, which is the safe direction: an unenforced timing
    clause is an ability that works more often than the card allows.

    "Their" is the *activating* seat. `_activate_onto_stack` takes its
    ``controller_index`` as the activator (CR 602.1a's controller of the
    ability) and names whose battlefield holds the permanent separately, so the
    seat comparison in the predicate is already the right one.
    """
    program = _w1g5a_compile(set_pool("WTH")["Well of Knowledge"])
    assert program.supported, program.reason

    game = _w1g5a_well(set_pool)
    # Its own controller, outside a draw step.
    refused, drew = _w1g5a_try(game, 0, "main1", 0)
    assert not refused.supported and drew == 0, refused.details
    # Its own controller, in their draw step.
    allowed, drew = _w1g5a_try(game, 0, "draw", 0)
    assert allowed.supported and drew == 1, allowed.details
    # An opponent, in *somebody else's* draw step: reachable, but not now.
    refused, drew = _w1g5a_try(game, 1, "draw", 0)
    assert not refused.supported and drew == 0, refused.details
    # The same opponent, in their own draw step.
    allowed, drew = _w1g5a_try(game, 1, "draw", 1)
    assert allowed.supported and drew == 1, allowed.details
    # And the controller is shut out of the opponent's draw step in turn — the
    # permission widens who may reach the ability, it does not widen when.
    refused, drew = _w1g5a_try(game, 0, "draw", 1)
    assert not refused.supported and drew == 0, refused.details
