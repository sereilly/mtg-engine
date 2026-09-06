"""Tempest sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W2G3: Time Warp, the extra turn somebody else takes ---

from engine import Game, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w2g3s_game(hands):
    seats = [
        PlayerState(name=f"P{index + 1}", hand=list(cards))
        for index, cards in enumerate(hands)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def test_time_warp_gives_the_extra_turn_to_its_target(set_pool):
    """"**Target player** takes an extra turn after this one." (CR 500.7.)

    The whole difference from Time Walk, which the engine has read since Alpha,
    is which seat gets the turn — and the lowering used to refuse every subject
    but "you" rather than hand a handler the wrong player. It is one payload key
    now, and the handler reads it exactly where it already read the caster.
    """
    game = _w2g3s_game([[set_pool("TMP")["Time Warp"]], []])
    game.start_turn(0)

    result = game.cast_from_hand(0, "Time Warp", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert game.extra_turn_queue == [1]
    assert game._compute_next_active_player() == 1
    assert game.current_turn_is_extra


def test_time_walk_still_chooses_nobody(catalog_by_name):
    """The regression the payload key exists to avoid. "Take an extra turn
    after this one" names no seat, so no picker is derived and the payload
    stays byte-equal with what the pool has always compiled to — a flat
    "this kind targets a player" row would have put a prompt in front of a
    spell whose handler ignores the answer."""
    walk = catalog_by_name["Time Walk"]

    assert derive_cast_spec(walk, compile_card_oracle(walk)) is None

    game = _w2g3s_game([[walk], []])
    game.start_turn(0)
    game.cast_from_hand(0, "Time Walk")
    game._settle()

    assert game.extra_turn_queue == [0]


def test_time_warp_asks_the_caster_to_pick_a_player(set_pool):
    """And the other half: the picker the browser is offered."""
    warp = set_pool("TMP")["Time Warp"]

    assert derive_cast_spec(warp, compile_card_oracle(warp)) == {"kind": "player"}
    assert compile_card_oracle(warp).instructions[0].payload == {"recipient": "target"}
