"""Per-card tests for Fallen Empires' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G2: self-clocks, delayed self-sacrifice and card-flow order ---

from unittest.mock import patch

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g2_kites_board(set_pool):
    """Goblin Kites, a 1/1 it can lift and a 3/3 it cannot."""
    lea = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    kites = Permanent(card=set_pool("FEM")["Goblin Kites"])
    small = Permanent(card=lea["Mons's Goblin Raiders"])   # 1/1
    big = Permanent(card=lea["Hill Giant"])                # 3/3
    for permanent in (kites, small, big):
        permanent.metadata["summoning_sickness_turn"] = -99
    player = PlayerState(name="P1", battlefield=[kites, small, big])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._settle()
    return game, player, kites, small, big


def _g2_fly(game, kites, rider, *, win):
    """Activate the Kites on *rider* with the end step's flip forced.

    ``engine.handlers._common`` is where ``flip_coin`` draws from, so patching
    ``random.random`` on it is patching the one module object every reader of
    the RNG shares -- and the draw still happens, which patching ``flip_coin``
    itself would skip.
    """
    with patch(
        "engine.handlers._common.random.random", return_value=0.0 if win else 0.99
    ):
        result = game.activate_permanent_ability(
            0, "Goblin Kites",
            permanent_index=game.battlefield_index_of(kites),
            target_player_index=0,
            target_permanent_index=game.battlefield_index_of(rider),
        )
        while game.stack:
            game.resolve_top_of_stack()
        game._settle()
        game.resolve_end_step(0)
        while game.stack:
            game.resolve_top_of_stack()
        game._settle()
    return result


def test_goblin_kites_lifts_a_small_creature_and_drops_it_on_a_lost_flip(set_pool):
    """"{R}: Target creature you control with toughness 2 or less gains flying
    until end of turn. Flip a coin at the beginning of the next end step. If you
    lose the flip, sacrifice that creature."

    The last two printed sentences are one delayed triggered ability (CR 603.7):
    the flip happens at the end step and so does everything hanging off it. A
    conditional performed *now* would read a flip that had not happened.
    """
    game, player, kites, small, _big = _g2_kites_board(set_pool)

    _g2_fly(game, kites, small, win=False)

    assert [c.name for c in player.graveyard] == ["Mons's Goblin Raiders"]
    assert sorted(p.card.name for p in player.battlefield) == [
        "Goblin Kites", "Hill Giant",
    ]


def test_goblin_kites_keeps_the_creature_on_a_won_flip(set_pool):
    """The other face of CR 705.2. A card that only ever lost would be a
    strictly worse one, and a delayed ability that dropped its condition would
    be exactly that."""
    game, player, kites, small, _big = _g2_kites_board(set_pool)

    _g2_fly(game, kites, small, win=True)

    assert player.graveyard == []
    assert sorted(p.card.name for p in player.battlefield) == [
        "Goblin Kites", "Hill Giant", "Mons's Goblin Raiders",
    ]


def test_goblin_kites_grants_flying_before_the_end_step_arrives(set_pool):
    """The first sentence is immediate. Checked separately from the drop,
    because a card that only sacrificed things would pass the tests above."""
    game, _player, kites, small, _big = _g2_kites_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Goblin Kites",
        permanent_index=game.battlefield_index_of(kites),
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(small),
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    assert result.supported, result.details
    assert small.has_keyword("flying")
    assert [entry.event for entry in game.delayed_triggers] == ["next_end_step"]
    assert game.delayed_triggers[0].bound_permanent_id == small.permanent_id


def test_goblin_kites_refuses_a_creature_the_phrase_excludes(set_pool):
    """"...with toughness 2 or less" is a narrowing on the *target*, so it is
    enforced where CR 602.2b puts it: at activation, with nothing paid. A
    grant whose noun phrase never reached the picker would lift a 3/3 and put
    it at risk of a coin flip the card never offered it."""
    game, _player, kites, _small, big = _g2_kites_board(set_pool)

    ability = compile_card_oracle(kites.card).activated_abilities[0]
    refusal = game.activation_target_refusal(
        0, kites, ability,
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(big),
    )
    assert refusal is not None

    result = game.activate_permanent_ability(
        0, "Goblin Kites",
        permanent_index=game.battlefield_index_of(kites),
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(big),
    )
    assert not result.supported
    assert not big.has_keyword("flying")
    assert game.delayed_triggers == []
