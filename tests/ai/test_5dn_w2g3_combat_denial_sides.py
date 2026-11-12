"""Maze of Ith, Maze of Shadows and Dwarven Sea Clan are aimed at the attacker across the table.

"{T}: Untap target attacking creature. Prevent all combat damage that would be
dealt to and dealt by that creature this turn." (Maze of Ith; Maze of
Shadows' second ability, "…with shadow".) ``ai_target_sides.ability_target_side``
read the untap alone and called it "you", so a seat defending against an
attacker never activated a Maze. "{T}: Choose target attacking or blocking
creature whose controller controls an Island. This creature deals 2 damage to
that creature at end of combat." (Dwarven Sea Clan.) The targeted step is a
choice with no side, and the damage was never read: no side, never activated.
W1G2 measured all three (5DN). A two-way prevention spent on the target, and
— where the targeted step has no side — the step spent on it, now decide;
"target attacking creature **you control**" (Ebony Horse, Elvish Scout) and a
grant's delayed drawback (War Barge, Sandals of Abdallah) keep "you".
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import choose_instant_speed_activation
from engine.ai_target_sides import ability_target_side
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import declare_attack, drive_combat, settle


def _pool(set_pool) -> dict:
    return {
        **set_pool("LEA"), **set_pool("ARN"), **set_pool("ATQ"), **set_pool("3ED"),
        **set_pool("DRK"), **set_pool("FEM"), **set_pool("HML"), **set_pool("TMP"),
    }


def test_the_three_read_opponent_and_their_rescue_twins_keep_you(set_pool):
    pool = _pool(set_pool)
    sides = {
        name: [ability_target_side(a.instruction) for a in compile_card_oracle(pool[name]).activated_abilities]
        for name in (
            "Maze of Ith", "Maze of Shadows", "Dwarven Sea Clan",
            "Ebony Horse", "Elvish Scout", "War Barge", "Sandals of Abdallah",
        )
    }
    assert sides["Maze of Ith"] == ["opponent"]
    assert sides["Maze of Shadows"][-1] == "opponent"
    assert sides["Dwarven Sea Clan"] == ["opponent"]
    for rescue in ("Ebony Horse", "Elvish Scout", "War Barge", "Sandals of Abdallah"):
        assert sides[rescue] == ["you"], (rescue, sides[rescue])


def _table(set_pool, *, mine, theirs) -> tuple[Game, dict]:
    pool = _pool(set_pool)
    game = Game(players=[
        PlayerState(name="AI", library=[pool["Forest"]] * 8),
        PlayerState(name="Opp", library=[pool["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    placed: dict = {}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.setdefault((seat, name), permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed


def _activate(game, action) -> None:
    from engine.ai_actions import activation_announcement

    result = game.activate_permanent_ability(0, action.permanent_name, **activation_announcement(action))
    assert result.supported, result
    settle(game)


def test_a_defending_seat_mazes_the_attacker(set_pool):
    """The opponent's Hill Giant attacks; the seat's Maze of Ith untaps it and
    prevents its combat damage — the seat takes none."""
    game, placed = _table(set_pool, mine=["Maze of Ith"], theirs=["Hill Giant"])
    declare_attack(game, 1)
    action = choose_instant_speed_activation(game, 0)
    assert action is not None and action.permanent_name == "Maze of Ith"
    assert action.target_permanent_ids == [placed[(1, "Hill Giant")].permanent_id]
    _activate(game, action)
    drive_combat(game)
    assert game.players[0].life == 20
    assert not placed[(1, "Hill Giant")].tapped


def test_an_attacking_seat_does_not_maze_its_own_attacker(set_pool):
    """The seat's own Grizzly Bears attack into an empty board: a Maze on
    them would prevent the seat's own damage. Not activated."""
    game, _placed = _table(set_pool, mine=["Maze of Ith", "Grizzly Bears"], theirs=[])
    declare_attack(game, 0)
    action = choose_instant_speed_activation(game, 0)
    assert action is None or action.permanent_name != "Maze of Ith"


def test_dwarven_sea_clan_kills_an_attacker_whose_controller_has_an_island(set_pool):
    """The opponent's Grizzly Bears attack beside their Island: the Sea Clan
    names them, and at end of combat its 2 damage kills them."""
    game, placed = _table(set_pool, mine=["Dwarven Sea Clan"], theirs=["Grizzly Bears", "Island"])
    declare_attack(game, 1)
    action = choose_instant_speed_activation(game, 0)
    assert action is not None and action.permanent_name == "Dwarven Sea Clan"
    assert action.target_permanent_ids == [placed[(1, "Grizzly Bears")].permanent_id]
    _activate(game, action)
    drive_combat(game)
    assert any(card.name == "Grizzly Bears" for card in game.players[1].graveyard)
