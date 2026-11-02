"""A trigger fired inside a resolution chooses its target after that
resolution's state-based check (CR 603.3d with CR 117.5 / 704.3).

CR 603.3: a triggered ability is put on the stack the next time a player would
receive priority, and CR 117.5 makes the game perform state-based actions
before that; CR 603.3d chooses the ability's targets as it is put there. The
engine pushes the object at its fire site and lets its choices wait for the
unit of play that set it off (``putting_triggers_on_stack``,
``_trigger_choice_waits``) — but a resolution's window closed as its last
instruction returned, *before* the check that follows it. So a trigger fired
inside a resolving spell was offered creatures the same spell had just dealt
lethal damage to: Chandra's Incinerator, triggered by Earthquake's damage to an
opponent, could name a creature Earthquake was about to kill.

The census is every road by which a trigger fires inside a resolution and then
chooses, each over a resolving sweep that also leaves a creature with lethal
damage: the **damage event** (Chandra's Incinerator, Earthquake), the
**destruction ledger** — the abilities a destroy sets off, held until the
resolution is over (Karmic Justice, Devastate) — and the **discard event**
inside a resolution that stops to ask (Guerrilla Tactics, Tainted Specter: the
discard is a prompt, so the resolution is held for its answer and the trigger
must wait through the hold as well). Each board asks, for an interactive seat,
whether the doomed creature is among the targets offered, and for a seat the
engine plays, whether the ability named a creature that was no longer there.

Validated backwards: with the resolution's window closed before its check (the
loops' check switched off, which is the tree before), every board offers the
doomed creature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CARDS = {card.name: card for card in load_catalog()}


def card(name: str):
    return _CARDS[name]


def names(cards) -> list[str]:
    return [c.name for c in cards]


def perm(name: str) -> Permanent:
    permanent = Permanent(card=card(name))
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def table(*, hands, boards, active: int, interactive) -> Game:
    players = [
        PlayerState(
            name=f"P{seat}",
            hand=[card(n) for n in hands[seat]],
            library=[card("Island")] * 8,
            battlefield=[perm(n) for n in boards[seat]],
        )
        for seat in range(2)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    game.start_priority_window(active)
    return game


def on_board(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


@dataclass(frozen=True)
class Road:
    """One way a trigger fires inside a resolution, on a board where the same
    resolution leaves *doomed* (a creature of *victim_seat*) with lethal
    damage. *play* runs the sweep, answering anything the resolution asks of
    the sweep's other seat with its default, and returns the game with the
    watcher's ability announced or waiting to be."""

    road: str
    watcher: str
    sweep: str
    chooser: int
    doomed: str
    victim_seat: int
    play: Callable[[set], Game]
    held: bool = False


ROADS: dict[str, Road] = {}


def road(name: str, **kwargs):
    def register(play):
        ROADS[name] = Road(road=name, play=play, **kwargs)
        return play
    return register


@road(
    "damage event", watcher="Chandra's Incinerator", sweep="Earthquake",
    chooser=0, doomed="Llanowar Elves", victim_seat=1,
)
def _incinerator(interactive):
    game = table(
        hands=(("Earthquake",), ()),
        boards=(("Chandra's Incinerator",), ("Llanowar Elves", "Grizzly Bears")),
        active=0, interactive=interactive,
    )
    game.cast_from_hand(0, "Earthquake", x_value=1)
    return game


@road(
    "destruction ledger", watcher="Karmic Justice", sweep="Devastate",
    chooser=0, doomed="Llanowar Elves", victim_seat=1,
)
def _karmic_justice(interactive):
    game = table(
        hands=((), ("Devastate",)),
        boards=(("Karmic Justice", "Forest"), ("Llanowar Elves", "Grizzly Bears", "Plains")),
        active=1, interactive=interactive,
    )
    game.cast_from_hand(1, "Devastate", target_permanent_ids=[
        on_board(game, 0, "Forest").permanent_id
    ])
    return game


@road(
    "discard event, the resolution held", watcher="Guerrilla Tactics",
    sweep="Tainted Specter", chooser=0, doomed="Llanowar Elves", victim_seat=1,
    held=True,
)
def _guerrilla_tactics(interactive):
    game = table(
        hands=(("Guerrilla Tactics",), ()),
        boards=((), ("Tainted Specter", "Llanowar Elves", "Grizzly Bears")),
        active=1, interactive=interactive | {0},
    )
    specter = on_board(game, 1, "Tainted Specter")
    game.activate_permanent_ability(
        1, "Tainted Specter", permanent_index=game.battlefield_index_of(specter),
        target_player_index=0,
    )
    game._settle()
    # "…discards a card unless they put a card from their hand on top of their
    # library": the Tactics' owner declines the library and discards it —
    # asked, because the seat is interactive; the Specter's ability waits on
    # the stack for each answer (CR 608.2).
    assert game.pending_choice_of("optional_pay", 0) is not None, game.log[-5:]
    assert game.confirm_optional_pay(0, accept=False)
    assert game.pending_choice_of("discard", 0) is not None, game.log[-5:]
    assert game.resolve_pending_choice("discard", 0, hand_indices=[0], to_library=False)
    return game


def _offered(game: Game, chooser: int) -> list[str] | None:
    for _spec, choice in game.iter_pending_prompts():
        if choice.kind == "trigger_target" and choice.player_index == chooser:
            return [entry.get("name") for entry in choice.data.get("targets") or ()]
    return None


def offered_the_doomed(r: Road) -> list[str]:
    """What is wrong with the watcher's announcement for an interactive
    chooser: the doomed creature offered, or no announcement at all."""
    game = r.play({r.chooser})
    offered = _offered(game, r.chooser)
    if offered is None:
        return [f"{r.watcher} was never asked for a target: {game.log[-6:]}"]
    problems = []
    if r.doomed in offered:
        problems.append(f"{r.watcher} was offered {r.doomed}: {offered}")
    if any(p.card.name == r.doomed for p in game.controlled_by(r.victim_seat)):
        problems.append(f"{r.doomed} is still on the battlefield as {r.watcher} chooses")
    return problems


#: Three roads, each a different fire site; a table that lost its rows would
#: pass by examining nothing.
_ROADS_FLOOR = 3


@pytest.mark.cr("603.3d")
def test_every_road_is_driven():
    assert len(ROADS) >= _ROADS_FLOOR


@pytest.mark.cr("603.3d", "117.5", "704.3")
@pytest.mark.parametrize("name", sorted(ROADS))
def test_a_trigger_fired_inside_a_resolution_chooses_after_its_state_check(name):
    assert offered_the_doomed(ROADS[name]) == [], name


@pytest.mark.cr("603.3d", "117.5")
@pytest.mark.parametrize("name", sorted(n for n, r in ROADS.items() if not r.held))
def test_a_seat_the_engine_plays_never_names_the_doomed_creature(name, monkeypatch):
    """The default a seat nobody asks takes is chosen at the same moment
    (``default_at_arm``), so it is chosen from the same board: whatever the
    watcher names as its ability is announced is on the battlefield. (The
    held road needs its seat asked for the discard, so it is the interactive
    test's alone.)"""
    r = ROADS[name]
    announced = []
    original = Game._finish_announcement

    def finish(self, item, **kwargs):
        original(self, item, **kwargs)
        source = item.source_permanent
        if item.card.name == r.watcher or (source is not None and source.card.name == r.watcher):
            announced.append((
                list(item.target_permanent_id or ()),
                {p.permanent_id: p.card.name for p in self.all_permanents()},
            ))

    monkeypatch.setattr(Game, "_finish_announcement", finish)
    r.play(set())
    assert announced, f"{r.watcher}'s ability was never announced"
    for named, board in announced:
        assert named, f"{r.watcher} named nothing"
        assert all(pid in board for pid in named), (named, board)
        assert r.doomed not in [board[pid] for pid in named]


@pytest.mark.cr("603.3d", "704.3")
def test_backwards_with_the_window_closed_before_the_check_every_road_offers_it(monkeypatch):
    """The tree before: the resolution is not the unit of play — its window
    closes as its last instruction returns and the loops check state after.
    Every road then offers the creature the sweep has just doomed."""
    import contextlib

    from engine.mixins.stack.choices.queue import PendingChoicesMixin
    from engine.mixins.stack.resolution import StackResolutionMixin

    monkeypatch.setattr(
        StackResolutionMixin, "_check_inside_the_resolution_window", lambda self: None,
    )
    # …and the answer to a held resolution's prompt is no unit of play either:
    # what it sets off chooses as it is pushed.
    monkeypatch.setattr(
        PendingChoicesMixin, "_answer_window", lambda self: contextlib.nullcontext(),
    )
    named = {name for name, r in ROADS.items() if offered_the_doomed(r)}
    assert named == set(ROADS), sorted(set(ROADS) - named)
