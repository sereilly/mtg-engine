"""Permanents that enter at the same time (CR 603.6a, 614.12, 610.3d).

CR 603.6a: "Each time an event puts one or more permanents onto the
battlefield, all permanents on the battlefield (including the newcomers) are
checked for any enters-the-battlefield triggers that match the event." CR
614.12: an entering permanent's replacement effects are judged with "continuous
effects that already exist" — so a newcomer is not yet there to be seen by
another newcomer's "as it enters". The engine opens one event around the
permanents a road puts down together (``Game.entering_together``):
each newcomer's entry state is performed in no zone as its call is made, and
the rest of every entry once the event closes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(*, interactive: bool = False) -> Game:
    players = [
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 20)
        for i in range(2)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0} if interactive else set()
    game._sync_control()
    return game


def _place(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    return permanent


@pytest.mark.cr("603.6a")
@pytest.mark.parametrize("interactive", [False, True], ids=["nobody_asked", "a_person"])
@pytest.mark.parametrize(
    "order",
    [["Goblin Assassin", "Goblin Clearcutter"], ["Goblin Clearcutter", "Goblin Assassin"]],
    ids=["assassin_first", "assassin_last"],
)
def test_goblin_assassin_returned_beside_another_goblin_triggers_twice(order, interactive):
    """The playbook's observation: "Goblin Assassin triggered once, not twice,
    when Planar Guide returned it beside Goblin Clearcutter." "Whenever this
    creature or another Goblin enters": two Goblins entering at once are two
    occurrences, whichever of them came back first (Planar Guide's ruling,
    2004-10-04: "All 'enters' abilities trigger as normal")."""
    game = _table(interactive=interactive)
    # Set down rather than entered: the Assassin's own trigger would flip
    # coins (and sacrifice) before the board this test is about exists.
    for name in [*order, "Planar Guide"]:
        permanent = Permanent(card=_CARDS[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        game.players[0].battlefield.append(permanent)
    game._sync_control()
    assert game.activate_permanent_ability(0, "Planar Guide")
    settle(game)
    mark = len(game.log)
    game.resolve_end_step(0)
    settle(game)
    rounds = sum(
        1 for line in game.log[mark:]
        if line.startswith("Goblin Assassin: P0 flipped")
    )
    assert rounds == 2, game.log[mark:]


@pytest.mark.cr("614.12", "707.5", "603.6a")
@pytest.mark.parametrize("clone_first", [True, False], ids=["clone_first", "clone_last"])
def test_a_clone_cannot_copy_a_creature_entering_beside_it(clone_first):
    """Clone's ruling (2025-10-02): "If Clone somehow enters at the same time
    as another creature, Clone can't become a copy of that creature. You may
    choose only a creature that's already on the battlefield." Twilight's
    Call's (2004-10-04): "All the creature cards enter simultaneously." So the
    Clone returned beside a Shivan Dragon copies the Grizzly Bears already
    there, whichever order the graveyard held them in — it used to copy the
    Dragon when the Dragon happened to come back first."""
    game = _table()
    _place(game, 1, "Grizzly Bears")
    pile = ["Clone", "Shivan Dragon"] if clone_first else ["Shivan Dragon", "Clone"]
    game.players[0].graveyard = [_CARDS[name] for name in pile]
    game.players[0].hand = [_CARDS["Twilight's Call"]]
    assert game.cast_from_hand(0, "Twilight's Call").supported
    settle(game)
    mine = sorted(p.effective_card.name for p in game.controlled_by(0))
    assert mine == ["Grizzly Bears", "Shivan Dragon"], (mine, game.log[-10:])


@pytest.mark.cr("614.12a", "603.6a")
def test_an_event_whose_newcomers_ask_waits_as_one():
    """Two Primal Clays and a Soul Warden put back together by Living Death,
    at a person's table: each Clay's "as this creature enters, it becomes
    your choice of …" is made before it enters (CR 614.12a), and the three
    enter together (CR 603.6a) — so none of them is on the battlefield while
    either choice is owed, the first answer moves nothing, and the last puts
    all three there at once, the Soul Warden seeing both Clays."""
    game = _table(interactive=True)
    game.players[0].graveyard = [
        _CARDS["Primal Clay"], _CARDS["Soul Warden"], _CARDS["Primal Clay"],
    ]
    game.players[0].hand = [_CARDS["Living Death"]]
    assert game.cast_from_hand(0, "Living Death").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    def mine() -> list[str]:
        return sorted(p.card.name for p in game.controlled_by(0))

    owed = [c for c in game.pending_choices if c.player_index == 0]
    assert len(owed) == 2, [c.kind for c in game.pending_choices]
    assert mine() == [], "nothing of the event is on the battlefield yet"
    assert len(game.entries_in_progress) == 3
    assert game.stack and game.stack[-1].card.name == "Living Death"

    game.take_choice_default(owed[0])
    assert mine() == [], "one answer of two moves nothing"
    life = game.players[0].life

    game.take_choice_default(owed[1])
    assert mine() == ["Primal Clay", "Primal Clay", "Soul Warden"]
    assert not game.entries_in_progress
    settle(game)
    assert game.players[0].life == life + 2


@pytest.mark.cr("610.3d")
def test_two_exiles_ended_by_one_sweep_return_together():
    """CR 610.3d: "If multiple one-shot effects are created this way
    immediately after one or more simultaneous events, those one-shot effects
    are also simultaneous" — its example two Banisher Priests destroyed by one
    Day of Judgment. Two Tawnos's Coffins destroyed by one Shatterstorm give
    their creatures back in one event: the Soul Warden the first Coffin held
    sees the Grizzly Bears the second gave back."""
    game = _table()
    warden = _place(game, 0, "Soul Warden")
    bears = _place(game, 0, "Grizzly Bears")
    coffins = [_place(game, 0, "Tawnos's Coffin") for _ in range(2)]
    for coffin, victim in zip(coffins, (bears, warden)):
        slot = next(
            i for i, held in enumerate(game.players[0].battlefield) if held is coffin
        )
        assert game.activate_permanent_ability(
            0, "Tawnos's Coffin", permanent_index=slot,
            target_permanent_ids=[victim.permanent_id],
        ).supported
        settle(game)
    life = game.players[0].life
    game.players[1].hand = [_CARDS["Shatterstorm"]]
    game.active_player_index = 1
    assert game.cast_from_hand(1, "Shatterstorm").supported
    settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Soul Warden",
    ]
    assert game.players[0].life == life + 1
