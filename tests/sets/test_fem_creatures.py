"""Per-card tests for Fallen Empires' creatures.

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


# --- G5: prices offered to a player, prevention and control ---
from engine import Game, PlayerState
from engine.models import Permanent


def _g5_game(*rows) -> Game:
    game = Game(players=[PlayerState(name=f"P{i + 1}", battlefield=list(row))
                         for i, row in enumerate(rows)])
    game.enforce_mana_costs = False
    return game


def _g5_ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _seasinger_board(set_pool, *, their_island: bool):
    singer = _g5_ready(Permanent(card=set_pool("FEM")["Seasinger"]))
    mine = Permanent(card=set_pool("LEA")["Island"])
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    theirs = [bear] + ([Permanent(card=set_pool("LEA")["Island"])] if their_island else [])
    game = _g5_game([singer, mine], theirs)
    game.start_turn(0)
    return game, singer, bear


def test_seasinger_steals_a_creature_whose_controller_controls_an_island(set_pool):
    """"{T}: Gain control of target creature whose controller controls an
    Island for as long as you control this creature and this creature remains
    tapped."

    The narrowing is a question about the *candidate's own controller's* board,
    which is why it needs the game and cannot be answered off the creature.
    """
    game, singer, bear = _seasinger_board(set_pool, their_island=True)

    assert game.activate_permanent_ability(
        0, "Seasinger", target_player_index=1, target_permanent_index=0
    ).supported
    assert singer.tapped, "the {T} cost was paid"
    assert game.controller_index_of(bear) == 0, game.log


def test_seasinger_refuses_a_creature_whose_controller_has_no_island(set_pool):
    """The half a matcher that dropped the phrase would get wrong: with the
    restriction ignored, every creature on the table is a legal steal."""
    game, singer, bear = _seasinger_board(set_pool, their_island=False)

    game.activate_permanent_ability(
        0, "Seasinger", target_player_index=1, target_permanent_index=0
    )

    assert game.controller_index_of(bear) == 1, game.log


def test_seasinger_gives_the_creature_back_when_it_untaps(set_pool):
    """CR 611.2b: the contribution ends when the linked condition stops
    holding, and the state-based sweep is what re-checks it."""
    game, singer, bear = _seasinger_board(set_pool, their_island=True)
    game.activate_permanent_ability(
        0, "Seasinger", target_player_index=1, target_permanent_index=0
    )
    assert game.controller_index_of(bear) == 0

    singer.tapped = False
    game.check_state_based_actions()

    assert game.controller_index_of(bear) == 1, game.log


def _thrull_board(set_pool, their_lands):
    wizard = _g5_ready(Permanent(card=set_pool("FEM")["Thrull Wizard"]))
    lands = [Permanent(card=set_pool("LEA")[name]) for name in their_lands]
    game = _g5_game([wizard], lands)
    game.players[1].hand = [set_pool("LEA")["Dark Ritual"]]
    game.start_turn(0)
    game.queue_from_hand(1, "Dark Ritual")
    assert len(game.stack) == 1
    return game


def test_thrull_wizard_counters_a_black_spell_nobody_can_pay_for(set_pool):
    """"{1}{B}: Counter target black spell unless that spell's controller pays
    {B} or {3}." One Mountain covers neither price."""
    game = _thrull_board(set_pool, ["Mountain"])

    assert game.activate_permanent_ability(
        0, "Thrull Wizard", target_stack_index=0
    ).supported
    game.auto_resolve_pending_choices()

    assert game.stack == []
    assert [c.name for c in game.players[1].graveyard] == ["Dark Ritual"], game.log


def test_thrull_wizard_takes_the_coloured_price_when_the_board_can_pay_it(set_pool):
    """The half a generic-only payment flow could not express: {B} is a
    coloured pip, and one Swamp pays it."""
    game = _thrull_board(set_pool, ["Swamp"])
    swamp = game.players[1].battlefield[0]

    game.activate_permanent_ability(0, "Thrull Wizard", target_stack_index=0)
    game.auto_resolve_pending_choices()

    assert swamp.tapped, "the Swamp paid the {B}"
    assert any("is not countered" in line for line in game.log), game.log


def test_thrull_wizard_takes_the_printed_alternative_when_only_it_is_payable(set_pool):
    """CR 118.8: "{B} **or {3}**" is one offer with two ways to cover it, so
    three Mountains keep the spell exactly as one Swamp would."""
    game = _thrull_board(set_pool, ["Mountain"] * 3)

    game.activate_permanent_ability(0, "Thrull Wizard", target_stack_index=0)
    game.auto_resolve_pending_choices()

    assert all(land.tapped for land in game.players[1].battlefield)
    assert any("paid {3}" in line for line in game.log), game.log
# --- end G5 ---
