"""Within one event putting permanents onto the battlefield, the choices and
the timestamps go in APNAP order (CR 101.4, CR 613.7m), and an each-seat
offer's "as it enters" choices wait for every seat's pick (Show and Tell's
rulings).

CR 613.7m: "If two or more objects would receive a timestamp simultaneously,
such as by entering a zone simultaneously …, their relative timestamps are
determined in APNAP order (see rule 101.4). Objects controlled by the active
player … have an earlier relative timestamp in the order of that player's
choice, followed by each other player in turn order." CR 101.4: "the active
player … makes any choices required, then the next player in turn order …
Then the actions happen simultaneously."

An event's newcomers used to have their entry states performed — and their
timestamps stamped — as each call was made, in the order the road happened to
walk them: Planar Guide's return gives the cards back in the order it exiled
them, seat 0's first whoever is active. They are handed to the event now and
performed as it closes, in APNAP order of the seat each enters under
(``entry_awaiting.apnap_order``).

Show and Tell's 2004-10-04 ruling: "If the cards being put onto the
battlefield also require choices, those choices are made after all players
choose their card. The active player makes choices for their card (if any),
then the other players (if any) in turn order." A Quirion Elves put down by
the first seat chose its colour at that seat's pick, before the second seat
had picked.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, settle

_CARDS = {card.name: card for card in load_catalog()}

#: "As this creature enters, choose a color." — an "as it enters" choice
#: (CR 614.12a) a person is asked.
CHOOSER = "Quirion Elves"


def _table(*, active: int, interactive=frozenset()) -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = active
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = set(interactive)
    game._sync_control()
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    """Put *name* on *seat*'s battlefield with nobody asked anything."""
    asked = game.interactive_seats
    game.interactive_seats = set()
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.interactive_seats = asked
    return permanent


def _entry_prompts(game: Game) -> list[int]:
    """The seats owing an "as it enters" choice, in the order they were armed."""
    return [
        choice.player_index for choice in game.pending_choices
        if choice.data.get("_entering_permanent") is not None
    ]


def _planar_guided(game: Game, active: int, names: dict[int, str]) -> None:
    """The active player's Planar Guide exiles every creature — *names*, one
    per seat — and the next end step returns them (one event)."""
    for seat, name in names.items():
        _set_down(game, seat, name)
    _set_down(game, active, "Planar Guide")
    asked = game.interactive_seats
    game.interactive_seats = set()
    assert game.activate_permanent_ability(active, "Planar Guide")
    settle(game)
    game.interactive_seats = asked
    assert not any(p.is_creature for p in game.all_permanents())
    game.resolve_end_step(active)


@pytest.mark.cr("613.7m", "101.4")
@pytest.mark.parametrize("active", [0, 1])
def test_cards_returned_together_are_stamped_active_player_first(active):
    """Planar Guide gives back both seats' creatures at once, and the active
    player's carries the earlier timestamp whichever seat that is."""
    game = _table(active=active)
    _planar_guided(game, active, {0: "Grizzly Bears", 1: "Llanowar Elves"})
    settle(game)
    stamps = {
        seat: [p.timestamp for p in game.controlled_by(seat) if p.is_creature]
        for seat in (0, 1)
    }
    assert all(len(stamped) == 1 for stamped in stamps.values()), (stamps, game.log[-10:])
    other = 1 - active
    assert stamps[active][0] < stamps[other][0], (
        f"active player on seat {active}: its creature was stamped "
        f"{stamps[active][0]}, the other seat's {stamps[other][0]}"
    )


@pytest.mark.cr("101.4", "614.12a", "603.6a")
@pytest.mark.parametrize("active", [0, 1])
def test_cards_returned_together_choose_active_player_first(active):
    """Two Quirion Elves, one each side, given back together: each colour is
    asked in APNAP order — the active player's Elves first — with neither on
    the battlefield yet (CR 614.12a), and both enter once both are chosen."""
    game = _table(active=active, interactive={0, 1})
    _planar_guided(game, active, {0: CHOOSER, 1: CHOOSER})
    _answer_until_an_entry_prompt(game)
    assert _entry_prompts(game) == [active, 1 - active], (
        [(c.kind, c.player_index) for c in game.pending_choices], game.log[-8:]
    )
    assert not any(p.is_creature for p in game.all_permanents())
    settle(game)
    assert all(
        [p.card.name for p in game.controlled_by(seat) if p.is_creature] == [CHOOSER]
        for seat in (0, 1)
    ), game.log[-10:]


def _show_and_tell(game: Game, active: int, hands: dict[int, str]) -> None:
    for seat, name in hands.items():
        game.players[seat].hand = [_CARDS[name]]
    game.players[active].hand.append(_CARDS["Show and Tell"])
    assert game.cast_from_hand(active, "Show and Tell").supported


def _answer_until_an_entry_prompt(game: Game) -> None:
    """Answer every offer and pick by default until an "as it enters" choice
    is the one owed (or nothing is)."""
    for _ in range(60):
        owed = game.waiting_prompt()
        if owed is not None and owed.data.get("_entering_permanent") is not None:
            return
        if owed is not None:
            game.take_choice_default(owed)
        elif game.stack:
            game.resolve_top_of_stack(pause_for_choices=game.holds_for_answers())
        else:
            return


@pytest.mark.cr("101.4", "101.4b", "603.6a", "614.12a")
@pytest.mark.parametrize("active", [0, 1])
def test_show_and_tells_entry_choice_waits_for_every_seats_pick(active):
    """The active player puts Quirion Elves down and the other seat a
    Grizzly Bears. The Elves' colour is asked only once the other seat has
    picked (the 2004-10-04 ruling), and both creatures enter together after
    it."""
    other = 1 - active
    game = _table(active=active, interactive={active})
    _show_and_tell(game, active, {active: CHOOSER, other: "Grizzly Bears"})
    _answer_until_an_entry_prompt(game)
    assert _entry_prompts(game) == [active], (
        [(c.kind, c.player_index) for c in game.pending_choices], game.log[-8:]
    )
    assert _CARDS["Grizzly Bears"] not in game.players[other].hand, (
        "the colour was asked before the other seat had picked"
    )
    assert not any(c.kind == "optional_pay" for c in game.pending_choices)
    assert not any(p.is_creature for p in game.all_permanents())
    settle(game)
    assert [p.card.name for p in game.controlled_by(active)] == [CHOOSER]
    assert [p.card.name for p in game.controlled_by(other)] == ["Grizzly Bears"]


@pytest.mark.cr("101.4", "603.6a", "614.12a")
@pytest.mark.parametrize("active", [0, 1])
def test_show_and_tells_entry_choices_go_active_player_first(active):
    """Both seats put a Quirion Elves down, both people: the colours are
    asked after both picks, the active player's first."""
    game = _table(active=active, interactive={0, 1})
    _show_and_tell(game, active, {0: CHOOSER, 1: CHOOSER})
    _answer_until_an_entry_prompt(game)
    assert _entry_prompts(game) == [active, 1 - active], (
        [(c.kind, c.player_index) for c in game.pending_choices], game.log[-8:]
    )
    settle(game)
    assert all(
        [p.card.name for p in game.controlled_by(seat)] == [CHOOSER]
        for seat in (0, 1)
    ), game.log[-10:]
