"""Per-card tests for Visions' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. A branch that added an import to a shared header loses it in the
mechanical "take ours, append the branch's block" merge — a ``NameError`` at
collection, found only after the merge is committed. A self-contained block
cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations


# --- W1G2: the land-play allowance ---

from engine import Game, PlayerState


def _w1g2_game():
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    return game


def test_summer_bloom_grants_three_more_land_drops_this_turn(set_pool):
    """"You may play up to three additional lands this turn." (CR 305.2.)

    Not a ``may`` wrapper: the word is the permission, not an offer taken at
    resolution, and wrapping it would put a yes/no prompt in front of a card
    that prints no decision.
    """
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]

    result = game.cast_from_hand(0, "Summer Bloom")
    assert result.supported, result.details
    game.resolve_stack()

    for played in range(4):
        assert game._may_play_another_land(0), f"land drop {played + 1} of 4"
        game.lands_played_this_turn[0] = played + 1
    assert not game._may_play_another_land(0), "one plus three, and no more"


def test_summer_bloom_grants_nothing_to_the_other_seat(set_pool):
    """"**You** may play…" — CR 109.5's controller, and nobody else."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.lands_played_this_turn[1] = 1
    assert not game._may_play_another_land(1)


def test_summer_bloom_s_grant_ends_with_the_turn(set_pool):
    """"…**this turn**." The record is cleared at the turn boundary beside the
    per-turn count it adds to."""
    game = _w1g2_game()
    game.players[0].hand = [set_pool("VIS")["Summer Bloom"]]
    game.cast_from_hand(0, "Summer Bloom")
    game.resolve_stack()

    game.start_turn(0)

    game.lands_played_this_turn[0] = 1
    assert not game._may_play_another_land(0)


def test_two_summer_blooms_add_up(set_pool):
    """Two resolutions of one effect grant six, not three: a ceiling the second
    copy merely re-asserted would make it free."""
    game = _w1g2_game()
    bloom = set_pool("VIS")["Summer Bloom"]
    game.players[0].hand = [bloom, bloom]
    for _ in range(2):
        game.cast_from_hand(0, "Summer Bloom")
        game.resolve_stack()

    game.lands_played_this_turn[0] = 6
    assert game._may_play_another_land(0)
    game.lands_played_this_turn[0] = 7
    assert not game._may_play_another_land(0)


# --- W2G2: continuous statics and printed restrictions ---
#
# Imports at the top of this block, so a merge that appends another group's
# block below cannot lose them (SET_PLAYBOOK.md).

from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.card_loader import load_cards as _w2g2_load
from engine.card_loader import manifest_set_paths as _w2g2_paths
from engine.models import Permanent as _W2G2Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile


def _w2g2_catalog():
    return {card.name: card for card in _w2g2_load(_w2g2_paths(include_measured=True))}


def _w2g2_slot(player, permanent):
    return next(i for i, perm in enumerate(player.battlefield) if perm is permanent)


def _w2g2_peace_talks_board(set_pool):
    """Two seats, a creature each, and Peace Talks in the first one's hand."""
    catalog = _w2g2_catalog()
    bear = _W2G2Permanent(card=catalog["Grizzly Bears"])
    hill = _W2G2Permanent(card=catalog["Hill Giant"])
    p1 = _W2G2PlayerState(
        name="P1",
        battlefield=[bear],
        hand=[set_pool("VIS")["Peace Talks"], catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    p2 = _W2G2PlayerState(
        name="P2",
        battlefield=[hill],
        hand=[catalog["Lightning Bolt"]],
        library=[catalog["Mountain"]] * 30,
    )
    game = _W2G2Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for player in (p1, p2):
        for perm in player.battlefield:
            perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    return game, bear, hill


def _w2g2_end_turn(game):
    seat = game.active_player_index
    game.resolve_end_step(seat)
    game.resolve_cleanup_step(seat)


def _w2g2_to_declare_attackers(game):
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()


def test_peace_talks_compiles_both_clauses_over_one_window(set_pool):
    """"This turn and next turn, creatures can't attack, and players and
    permanents can't be the targets of spells or activated abilities."

    One leading duration over two effects, so the window is distributed to
    both. Two instructions rather than one fused kind, because they are
    enforced in two different places (CR 508.1c's declaration and CR 115.1's
    choice) -- and both carry the same two-turn count.
    """
    program = _w2g2_compile(set_pool("VIS")["Peace Talks"])
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == ["cant_attack_until_eot", "ban_targeting"]
    assert [step.payload["remaining_turns"] for step in steps] == [2, 2]


def test_peace_talks_stops_attacks_and_targeting_on_the_turn_it_resolves(set_pool):
    """Both clauses, watched as refusals.

    A restriction nothing enforces looks exactly like one that works, so each
    half is checked by an action being declined: a Lightning Bolt that never
    reaches its face, and a declaration the attack gate refuses.
    """
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)

    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported, game.log
    assert game.players[1].life == 20

    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]


def test_peace_talks_still_binds_the_opponent_on_the_next_turn(set_pool):
    """"And next turn" is the half a one-turn sweep would silently drop -- and
    it is the half the caster paid for, because the turn it resolves in is
    their own."""
    game, _bear, hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    _w2g2_end_turn(game)
    game.start_next_turn()

    assert game.active_player_index == 1
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 20
    _w2g2_to_declare_attackers(game)
    assert not game.declare_attackers(1, [_w2g2_slot(game.players[1], hill)])[0]


def test_peace_talks_ends_after_the_second_cleanup(set_pool):
    """Two cleanups and no more: a window that outlived them would be a
    permanent effect the card never printed, which is the other direction and
    just as silent."""
    game, bear, _hill = _w2g2_peace_talks_board(set_pool)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log
    for _ in range(2):
        _w2g2_end_turn(game)
        game.start_next_turn()

    assert game.targeting_bans == []
    assert game.attack_restrictions_until_eot == []
    assert game.active_player_index == 0
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17
    _w2g2_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w2g2_slot(game.players[0], bear)])[0]
