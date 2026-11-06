"""An AI seat Forks an opponent's burn spell aimed at its own creature, and
aims the copy at the opponent (CR 707.10c).

The copy's target is measured when the copy is made
(``ai_prompts.choose_copy_target``) — but the decision to cast the Fork is a
rehearsal, and no rehearsal runs inside one, so on the rehearsal's table the
copy kept the original's target: a Fork of a Bolt at the seat's own Bears
read as a second Bolt on those Bears, worth nothing, and no AI seat ever
cast a Fork in response to an opponent's spell (kg4: none in four seeded LEA
games with Fork pinned). Inside a rehearsal the copy is now moved off the
wrong side of the table (``ai_prompts._copy_target_by_side``) — a floor the
real, measured answer is taken over.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_priority import act_at_priority
from engine.ai_prompts import _copy_target_by_side
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_catalog, manifest_set_path
from engine.game_types import StackItem
from engine.models import Permanent
from engine.pending_choices import PendingChoice
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _permanent(name):
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _board(*, aimed_at_bears: bool):
    """The AI (seat 0) holds Fork and two Mountains, and a Grizzly Bears; the
    opponent, whose turn it is, a Hill Giant — and casts Lightning Bolt at
    the AI's Bears (or face)."""
    ai = PlayerState(name="AI", library=[_CARDS["Mountain"]] * 10)
    them = PlayerState(name="Them", library=[_CARDS["Mountain"]] * 10)
    game = Game(players=[ai, them])
    game.enforce_mana_costs = True
    bears, giant = _permanent("Grizzly Bears"), _permanent("Hill Giant")
    for permanent in (bears, _permanent("Mountain"), _permanent("Mountain")):
        game._put_permanent_onto_battlefield(0, permanent, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    game.start_turn(1)
    game._close_current_priority_step()
    ai.hand = [_CARDS["Fork"]]
    them.hand = [_CARDS["Lightning Bolt"]] + list(them.hand)
    them.mana_pool.update({"R": 1})
    announced = (
        {"target_permanent_ids": [bears.permanent_id]} if aimed_at_bears else {}
    )
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, **announced,
    ).supported
    game.priority_player_index = 0
    return game, bears, giant


@pytest.mark.parametrize("aimed_at_bears", (True, False))
def test_the_ai_forks_an_opponents_bolt_aimed_at_it_and_turns_the_copy(aimed_at_bears):
    game, _bears, giant = _board(aimed_at_bears=aimed_at_bears)
    log = len(game.log)

    act = act_at_priority(game, 0)

    assert act is not None and act.kind == "cast" and act.card.name == "Fork"
    resolve_stack(game)
    game.check_state_based_actions()
    # The copy, measured as it is made, killed the opponent's Hill Giant; the
    # Bolt itself went where it was aimed.
    assert not game.is_on_battlefield(giant)
    assert any("Lightning Bolt (copy) targets Hill Giant" in line for line in game.log[log:])
    assert game.players[1].life == 20


def _offer(game, copy, seat):
    targets = [
        {"kind": "player", "seat": index, "name": player.name}
        for index, player in enumerate(game.players)
    ] + [
        {"kind": "permanent", "seat": game.controller_index_of(perm), "index": 0,
         "permanent_id": perm.permanent_id, "name": perm.card.name}
        for perm in game.all_permanents() if perm.is_creature
    ]
    return PendingChoice(kind="copy_spell_target", player_index=seat,
                         data={"_copy": copy, "targets": targets})


def test_inside_a_rehearsal_a_copy_on_the_right_side_is_never_moved():
    """The floor moves a copy only off the wrong side: the copier's own
    Bolt at the opponent's Hill Giant stays there; at the copier's own Bears
    it goes to the opponent's face (the seat it attacks)."""
    game, bears, giant = _board(aimed_at_bears=True)
    bolt = game.stack[-1]
    copy = StackItem(card=bolt.card, caster_index=0, target_player_index=1,
                     target_permanent_index=None, x_value=None,
                     target_permanent_id=[giant.permanent_id], is_copy=True)
    offer = _offer(game, copy, 0)
    answers = [{"seat": 0}, {"seat": 1}, {"permanent_id": bears.permanent_id}]
    kept = {"permanent_id": giant.permanent_id}
    assert _copy_target_by_side(game, offer, kept, answers) == kept

    kept = {"permanent_id": bears.permanent_id}
    answers = [{"seat": 0}, {"seat": 1}, {"permanent_id": giant.permanent_id}]
    assert _copy_target_by_side(game, offer, kept, answers) == {"seat": 1}


@pytest.mark.full
def test_a_seeded_lea_game_forks_an_opponents_spell_back_at_them():
    """A whole game reaches it: Fork and Lightning Bolt pinned into every
    deck, and at least one Fork cast in response to an opponent's spell whose
    copy is aimed at that opponent — a floor, never a count."""
    report = run_ai_simulation(
        manifest_set_path("LEA"), games=4, seed=1337,
        required_cards=["Fork", "Lightning Bolt", "Lightning Bolt", "Mountain"],
    )
    assert report.games_completed == 4
    lines = report.log_lines
    turned = 0
    for index, line in enumerate(lines):
        if " cast Fork -> queued [in response to " not in line:
            continue
        caster = line.split(" cast Fork")[0].split()[-1]
        aimed = next(
            (later for later in lines[index + 1:index + 30] if "(copy) targets " in later),
            None,
        )
        if aimed is None:
            continue
        target = aimed.split("(copy) targets ")[1].strip()
        if target != caster and target.startswith("AI-"):
            turned += 1
    assert turned >= 1
