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


# --- W2G1: costs, alternative and additional ---

from engine import Game as _W2G1sGame, PlayerState as _W2G1sPlayerState
from engine.models import Permanent as _W2G1sPermanent
from engine.card_loader import load_cards as _w2g1s_load, manifest_set_path as _w2g1s_path
from engine.cast_costs import additional_cost_for_line as _w2g1s_add_line

_W2G1S_LEA = {c.name: c for c in _w2g1s_load(_w2g1s_path("LEA"))}


def _w2g1s_scene(hand, swamps, opposing=()):
    p1 = _W2G1sPlayerState(name="A", hand=list(hand))
    p2 = _W2G1sPlayerState(name="B")
    game = _W2G1sGame(players=[p1, p2])
    game.enforce_mana_costs = False
    for _ in range(swamps):
        p1.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA["Swamp"]))
    for name in opposing:
        p2.battlefield.append(_W2G1sPermanent(card=_W2G1S_LEA[name]))
    return game, p1, p2


def test_infernal_harvest_returns_x_swamps_and_deals_that_much(set_pool):
    """CR 107.3a: an X in an **additional** cost is announced as the spell is
    cast, and Infernal Harvest's printed mana cost has no {X} in it at all —
    this clause is the only place its X lives.

    Before the cost was read the card dealt its damage for {1}{B} with no
    Swamp returned, which is the defect this whole block exists for.
    """
    game, caster, victim = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=3,
        opposing=("Mons's Goblin Raiders", "Hurloon Minotaur"),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=2, divided_targets=[(1, 0), (1, 1)],
    )

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Swamp"]
    assert [c.name for c in caster.hand] == ["Swamp", "Swamp"]
    # 1 damage each: the Goblin dies, the Minotaur survives.
    assert [p.card.name for p in victim.battlefield] == ["Hurloon Minotaur"]


def test_infernal_harvest_refuses_an_x_the_board_cannot_pay(set_pool):
    """CR 601.2h: three Swamps is no payment for an X of four, and the refusal
    costs the caster nothing."""
    game, caster, _ = _w2g1s_scene(
        [set_pool("VIS")["Infernal Harvest"]], swamps=2,
        opposing=("Hurloon Minotaur",),
    )

    result = game.cast_from_hand(
        0, "Infernal Harvest", x_value=3, divided_targets=[(1, 0)],
    )

    assert not result.supported
    assert "CR 601.2h" in result.details
    assert len(caster.battlefield) == 2
    assert [c.name for c in caster.hand] == ["Infernal Harvest"]


def test_the_return_cost_reads_the_printed_destination():
    """The zone is part of the clause: the payment reaches one hand, and a
    sentence naming another destination refuses rather than being charged
    against it."""
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X Swamps you "
        "control to the graveyard."
    ) is None
    # …and an un-narrowed noun phrase is refused for the reason every other
    # counted cost's is: it would let the payment eat anything the caster has.
    assert _w2g1s_add_line(
        "As an additional cost to cast this spell, return X permanents you "
        "control to their owner's hand."
    ) is None
