"""The AI takes ninjutsu (CR 702.49a): "{cost}, Return an unblocked attacker
you control to hand: Put this card onto the battlefield from your hand tapped
and attacking."

Before BOK's wave 2 every Ninja an AI seat held was hard-cast: the hand
chooser (``ai_hand_activations``) had a floor for a cost that returns a
creature, because nothing priced the trade, and without it the ability scored
its flat 2.5 and would have been proposed blind (BOK W1G1: four Ninjas pinned
into four games, never one ninjutsu). Now:

* **when** — the attacking seat's priority in the declare-blockers step,
  after the blocks (CR 509.1h: nothing is unblocked before then;
  ``ai_priority.instant_speed_window``'s ``"combat"``), asked of the hand
  door's own cost question (``card_activation.hand_cost_refusal``);
* **which attacker** — every unblocked attacker the cost could return is a
  candidate of its own (``ai_hand_activations._return_choices``);
* **whether** — each candidate is carried out on a copy of the game in that
  same step and the combat run out through its damage
  (``ai_rehearsal.rehearse``), against the copy with nothing activated: the
  returned attacker's damage and body against the Ninja's and its payoff.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_hand_activations import choose_hand_activation_action, holds_a_hand_ability
from engine.ai_priority import act_at_priority
from engine.models import Permanent
from tests.helpers import _nosick, declare_attack, drive_combat, settle


def _table(set_pool, ninja: str, attackers, *, theirs=(), blocks=None, attack=True,
           lands=("Island", "Island", "Swamp", "Swamp", "Swamp")):
    """*ninja* in P1's hand, *attackers* (LEA cards) attacking P2 with *blocks*
    declared (none by default) — the declare-blockers step, blocks locked —
    and *lands* untapped to pay for it; costs enforced, so what is proposed
    is a payment the seat can make. With *attack* False the table is P1's
    first main phase."""
    lea, bok = set_pool("LEA"), set_pool("BOK")
    mine = [_nosick(Permanent(card=lea[name])) for name in attackers]
    defenders = [_nosick(Permanent(card=lea[name])) for name in theirs]
    game = Game(players=[
        PlayerState(
            name="P1", hand=[bok[ninja]],
            battlefield=[_nosick(Permanent(card=lea[name])) for name in lands] + mine,
            library=[lea["Island"]] * 5,
        ),
        PlayerState(name="P2", battlefield=defenders, library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = True
    game._settle()
    if attack:
        declare_attack(game, 0, blocks=blocks)
    return game, mine, defenders


def _names(cards) -> list[str]:
    return sorted(card.name for card in cards)


def test_the_attacker_takes_ninjutsu_after_the_blocks_and_the_ninja_connects(set_pool):
    """The unblocked Bears go home, Ninja of the Deep Hours comes in tapped and
    attacking, deals its 2 and draws — the seat's answer to its priority in
    the declare-blockers step, through the executor the simulator and the web
    AI seat share."""
    game, (bears,), _ = _table(set_pool, "Ninja of the Deep Hours", ["Grizzly Bears"])
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "hand" and act.window == "combat"
    assert act.supported, act.result
    assert act.action.cost_permanent_ids == (bears.permanent_id,)
    settle(game)
    ninja = next(p for p in game.controlled_by(0) if p.card.name == "Ninja of the Deep Hours")
    assert ninja.tapped and ninja.attacking
    drive_combat(game)
    assert game.players[1].life == 18
    # The Bears back in hand, and the card the Ninja's trigger drew.
    assert _names(game.players[0].hand) == ["Grizzly Bears", "Island"]


def test_the_attacker_returned_is_the_one_whose_return_gains_most(set_pool):
    """Two unblocked attackers: a Craw Wurm and a Llanowar Elves. The Elves go
    home — the Wurm's six damage stays in the fight — though the Wurm is first
    in board order, the engine's own pick were nothing named."""
    game, (wurm, elves), _ = _table(
        set_pool, "Ninja of the Deep Hours", ["Craw Wurm", "Llanowar Elves"],
    )
    action = choose_hand_activation_action(game, 0, at_instant_speed=True)
    assert action is not None and action.cost_permanent_ids == (elves.permanent_id,)
    act = act_at_priority(game, 0)
    assert act is not None and act.supported
    settle(game)
    drive_combat(game)
    assert game.players[1].life == 20 - 6 - 2
    assert any(p is wurm for p in game.controlled_by(0))
    assert "Llanowar Elves" in _names(game.players[0].hand)


def test_a_payoff_that_outvalues_the_damage_is_taken(set_pool):
    """Throat Slitter ("…destroy target nonblack creature that player
    controls") for a Hill Giant: a point of damage and a bigger body given up
    for the defender's Craw Wurm, which stayed home."""
    game, (giant,), (wurm,) = _table(
        set_pool, "Throat Slitter", ["Hill Giant"], theirs=["Craw Wurm"],
    )
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "hand" and act.supported
    assert act.action.cost_permanent_ids == (giant.permanent_id,)
    settle(game)
    drive_combat(game)
    assert game.players[1].life == 18
    assert not any(p is wurm for p in game.controlled_by(1))
    assert "Craw Wurm" in _names(game.players[1].graveyard)


def test_a_swap_that_loses_is_not_made(set_pool):
    """Mistblade Shinobi, a 1/1 whose payoff bounces a creature of the damaged
    player's, for an unblocked Craw Wurm with nothing on the other side to
    bounce: five damage and a 6/4 given up for nothing. Not proposed — and the
    Wurm connects."""
    game, (wurm,), _ = _table(set_pool, "Mistblade Shinobi", ["Craw Wurm"])
    assert choose_hand_activation_action(game, 0, at_instant_speed=True) is None
    act = act_at_priority(game, 0)
    assert act is None or act.kind != "hand"
    drive_combat(game)
    assert game.players[1].life == 14
    assert _names(game.players[0].hand) == ["Mistblade Shinobi"]


def test_only_a_blocked_attacker_pays_nothing(set_pool):
    """A blocked attacker is not "an unblocked attacker you control": with the
    only one blocked there is nothing to return, and nothing is proposed — a
    refused activation would be the seat's priority spent on nothing."""
    game, _mine, _theirs = _table(
        set_pool, "Ninja of the Deep Hours", ["Grizzly Bears"],
        theirs=["Hill Giant"], blocks={0: 5},
    )
    assert not holds_a_hand_ability(game, 0)
    assert choose_hand_activation_action(game, 0, at_instant_speed=True) is None


@pytest.mark.parametrize("moment", ["main_phase", "declare_attackers"])
def test_nothing_is_proposed_before_the_blocks(set_pool, moment):
    """CR 509.1h: an attacker is unblocked only once blockers are declared, so
    before then — the main phase, or the declare-attackers step with the
    blocks owed — ninjutsu's return has no payer and the engine refuses it.
    The chooser asks the engine's question and proposes nothing."""
    game, mine, _ = _table(
        set_pool, "Ninja of the Deep Hours", ["Grizzly Bears"], attack=False,
    )
    if moment == "declare_attackers":
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        slot = game.battlefield_index_of(mine[0])
        ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
        assert ok, why
    for speed in (False, True):
        assert choose_hand_activation_action(game, 0, at_instant_speed=speed) is None


def test_the_defending_seat_holds_its_ninja(set_pool):
    """The defender's Ninja has no attacker of its own to return: nothing is
    proposed for the defending seat in the same step."""
    bok = set_pool("BOK")
    game, _mine, _ = _table(set_pool, "Ninja of the Deep Hours", ["Grizzly Bears"])
    game.players[1].hand.append(bok["Ninja of the Deep Hours"])
    assert choose_hand_activation_action(game, 1, at_instant_speed=True) is None


#: Betrayers of Kamigawa's four cheapest ninjutsu costs, pinned into both
#: decks of a short seeded game (seed 4: one ninjutsu in 8 turns, measured).
_W2G4_CHEAP_NINJAS = (
    "Ninja of the Deep Hours", "Mistblade Shinobi", "Walker of Secret Ways", "Skullsnatcher",
)


@pytest.mark.full
def test_a_seeded_game_takes_ninjutsu_and_the_engine_never_refuses_it():
    """The simulator plays the engine's turn: a ninjutsu taken in it goes
    through ``ai_priority.act_at_priority``'s combat window and is counted
    with the other hand activations at instant speed. A floor of one — the
    subject was exercised — and none refused, none rehearsal-raised."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        manifest_set_path("BOK", include_measured=True), games=1, seed=4,
        max_turns=8, required_cards=list(_W2G4_CHEAP_NINJAS),
    )
    taken = {
        name: count for name, count in report.activations_from_hand_at_instant_speed.items()
        if name in _W2G4_CHEAP_NINJAS
    }
    assert sum(taken.values()) >= 1, report.activations_from_hand_at_instant_speed
    assert any("to activate" in line and "returned" in line for line in report.log_lines)
    assert not report.refused_instant_activations, report.refused_instant_activations
    assert not report.rehearsals_raised, report.rehearsals_raised
