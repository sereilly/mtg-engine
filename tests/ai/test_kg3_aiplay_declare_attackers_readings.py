"""Two readings in the declare-attackers window (kg3 `aiplay`, part 4).

* **Provoke's shed reading saw one blocker.** ``ai_compelled_blocks.
  compelled_block_worth`` priced Swooping Talon's provoke at a Bears by the
  fight the Talon wins once it sheds its flying — and a grounded Talon is
  open to every blocker, not only the one it compelled. Against three
  Grizzly Bears the provoke was taken (untapping a Bears), and the window
  then rightly declined to shed: the untap given away. The defender's other
  creatures that could block the grounded attacker are weighed now
  (``_ganged_on``), with no rehearsal — the question is asked part-way
  through the provoke's resolution.
* **A response before the blocks was read without the fight.** With an
  attack trigger on the stack the window is a response, and a copy made
  there owes the blocks once its stack resolves — so the rehearsal, which
  fought no combat, read an attack that dealt no damage on either copy. Such
  a response is read through the rest of the combat now
  (``ai_rehearsal.blocks_owed``).
"""
from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.ai_combat import run_ai_combat_phase
from engine.ai_compelled_blocks import compelled_block_worth
from engine.ai_policy import choose_combat_instant_cast_action
from engine.ai_rehearsal import blocks_still_to_come
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

_CARDS = {card.name: card for card in load_catalog()}


def _table(*, boards=((), ()), hands=((), ()), life=(20, 20), driven=True):
    """A two-seat table as `run_ai_simulation` builds one, in AI-A's
    precombat main phase (`test_kg3_aidefend_windows`' shape)."""
    players = [
        PlayerState(
            name=name, hand=[_CARDS[card] for card in hand],
            library=[_CARDS["Forest"]] * 8, life=total,
        )
        for name, hand, total in zip(("AI-A", "AI-B"), hands, life)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    if driven:
        game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = 0
    for seat, board in enumerate(boards):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, report


def _declare(game, *names):
    while game.current_step != "declare_attackers":
        game.advance_combat_phase()
    slots = [
        game.battlefield_index_of(permanent)
        for permanent in game.controlled_by(0)
        if permanent.is_creature and (not names or permanent.card.name in names)
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


# --- provoke's shed reading ---------------------------------------------------


@pytest.mark.parametrize("bears, taken", [(1, True), (3, False)])
def test_a_shed_is_weighed_against_every_blocker_the_grounded_attacker_meets(bears, taken):
    """Talon (2/6) grounded in front of one Bears wins the fight; in front of
    three it is blocked by all of them and dies, so provoking one is worth
    nothing to it."""
    game, _report = _table(
        boards=(("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",) * bears),
    )
    talon, bear = _on(game, 0, "Swooping Talon"), _on(game, 1, "Grizzly Bears")
    worth = compelled_block_worth(game, talon, bear)
    assert (worth > 0) is taken, worth


def test_the_provoke_is_declined_where_the_shed_would_lose_the_fight():
    """The whole combat, as the simulator plays it: against three Bears the
    provoke is not taken (no Bears is untapped and told to block), Talon
    keeps its flying, and deals its 2."""
    game, _report = _table(
        boards=(("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",) * 3),
    )
    _declare(game, "Swooping Talon")
    run_ai_combat_phase(game, 0)

    assert not any("blocks Swooping Talon this combat if able" in line for line in game.log)
    assert "Swooping Talon loses flying until end of turn" not in game.log
    assert game.players[1].life == 18


# --- a response before the blocks ---------------------------------------------


def test_a_response_to_an_attack_trigger_is_read_through_the_fight():
    """Hollow Dogs ("Whenever this creature attacks, it gets +2/+0 until end
    of turn") and a Hill Giant attack a seat at 5 life with a Grizzly Bears
    to block with, holding Fog and a Forest. In response to the trigger,
    read without the fight, Fog stopped nothing: the copy owed the Bears'
    block once the trigger resolved, the walk stopped there, and no combat
    damage was dealt on either copy. Read through the fight, Fog saves the
    Bears or three life."""
    game, _report = _table(
        boards=(("Hollow Dogs", "Hill Giant"), ("Forest", "Grizzly Bears")),
        hands=((), ("Fog",)), life=(20, 5), driven=False,
    )
    _declare(game)
    # The response window before the blocks: the trigger on the stack, the
    # attack locked in, the blocks owed.
    assert game.stack and game.current_step == "declare_attackers"
    assert game.combat_attackers_locked and not game.combat_blockers_locked
    assert not blocks_still_to_come(game)
    action = choose_combat_instant_cast_action(game, 1)
    assert action is not None and action.card_name == "Fog", action
