"""An ability that moves nothing is not proposed — every ability, not the shapes
named; and one whose worth is a fight it does not change waits for the blocks
(kg4 `aiact`, parts 4 and 3).

**The defects.** The main-phase chooser (``ai_abilities.choose_activation_action``)
rehearsed seven shapes it had been caught spending mana on — a land's
ability, a hamper, a rewrite of its source, an armed draw, a shield, a source
given up, an effect reaching both sides — and proposed every other ability at
its flat score whatever it did. On a neutral board in a postcombat main phase
(the census below) 432 of its 698 proposals on the base moved nothing that
lasted or left the seat worse off: Shivan Dragon's firebreathing with no fight
left, Wyluli Wolf's +1/+1 at nobody, Tracker fighting a creature that kills it,
Orcish Artillery's 2 damage for 3 of its controller's life.

And a precombat ability whose good is the fight was bought before the attack
wherever the fight went better with it, even when the attack and the blocks
were the same without it — the firebreathing an unblocked flier could buy in
the declare-blockers step, with the blocks known (SCG Phase 5's Zealous
Inquisitor note).

**The fix.** Every main-phase proposal is held to the cast rule
(``ai_abilities._moves_something``: ``ai_scoring._worth_proposing``, read
through the fight where its good is gone by the end of the turn); and before
the seat's own combat a fight-priced ability is made only for a declaration
it changes (``Rehearsal.declarations_changed``) — otherwise, where it could be
activated in the declare-blockers step, it waits for it
(``ai_abilities._read_through_the_fight``).
"""
from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.ai_abilities import (_exists_to_be_given_up, _gives_up_its_source,
                                 _rehearse_activation, choose_activation_action)
from engine.ai_actions import activation_announcement
from engine.ai_combat import run_ai_combat_phase
from engine.ai_payment import tap_planned_lands
from engine.ai_rehearsal import deliberating, rehearse
from engine.ai_scoring import _leaves_nothing, _worth_proposing
from engine.ai_valuation import source_becomes_an_aura
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, stable_sample

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}
_LANDS = ("Plains", "Island", "Swamp", "Mountain", "Forest") * 3

#: The census floors: units examined, and proposals the chooser still makes
#: on its board (275 of 1,920 at kg4, every one worth making; 698 on the
#: base, 432 of them not).
_EXAMINED_FLOOR = 1500
_PROPOSED_FLOOR = 150
#: The quick pass's one-in-N sample.
_SAMPLE = 8


def _table(own, other=("Grizzly Bears", "Mountain"), *, step="postcombat_main", active=0):
    players = [
        PlayerState(name=name, library=[_CARDS["Forest"]] * 8)
        for name in ("AI-A", "AI-B")
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate((own, other)):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step(step, step)
    return game, report


def _units() -> list:
    return [
        unit for unit in compilation_units(_CATALOG)
        if "Land" not in (unit.type_line or "")
        and unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and usable_activated_abilities(compile_card_oracle(unit))
    ]


@pytest.mark.full
def test_every_main_phase_proposal_moves_something_that_lasts():
    """The census, whole: every shipped permanent with an activated ability,
    under seat 0 with every colour of mana, in its postcombat main phase
    against a Grizzly Bears. Whatever the chooser proposes, carried out on a
    copy, is one the cast rule would propose of the effect alone (the {T} it
    costs on both copies; a Licid asked only whether its change lasts) —
    on the base, 698 proposals and most of them not."""
    _census(every=1)


def test_every_main_phase_proposal_moves_something_that_lasts_sampled():
    """The census's quick-pass sample (``stable_sample``)."""
    _census(every=_SAMPLE)


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def _effect_rehearsal(game, seat, action, ability):
    """*action* carried out on a copy (``ai_rehearsal.rehearse``) against a
    copy with the same lands tapped and — for a {T} ability — its source
    tapped too: what the **effect** did, the reading the cast rule is asked
    of here. Built from the rehearsal itself rather than the chooser's own
    gate, so the census asks the question independently of the answer."""
    def perform(table):
        planned = tap_planned_lands(table, seat, action)
        return table.queue_permanent_ability(
            seat, planned.permanent_name, **activation_announcement(planned),
        )

    def without(table, _carried):
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, action)
        pool.clear()
        pool.update(floating)
        if ability.cost.requires_tap:
            table.permanent_at(seat, action.permanent_index).tapped = True

    with deliberating():
        return rehearse(
            game, seat, perform, spell_name=None, leaves_hand=False,
            without=without, without_key=("census", action.land_tap_indices),
        )


def _census(*, every: int) -> None:
    examined, proposed, wrong = 0, 0, []
    for unit in _units():
        if not stable_sample(unit.name, every):
            continue
        examined += 1
        game, _report = _table((unit.name, *_LANDS))
        action = choose_activation_action(game, 0)
        if action is None or action.permanent_name != unit.name:
            continue
        proposed += 1
        source = _on(game, 0, unit.name)
        ability = game.usable_abilities_of(source)[action.ability_index or 0]
        if _gives_up_its_source(ability.cost) and _exists_to_be_given_up(source):
            # A one-shot keeps its flat score (`ai_abilities._exists_to_be_given_up`:
            # the standing prices the permanent at least a card, so no
            # rehearsal would ever crack the Egg) — the gate's one exception.
            continue
        rehearsal = _effect_rehearsal(game, 0, action, ability)
        if rehearsal is None:
            continue
        if source_becomes_an_aura(ability.instruction):
            ok = rehearsal.accepted and rehearsal.changed and not _leaves_nothing(rehearsal)
        else:
            ok = _worth_proposing(rehearsal)
        if not ok:
            wrong.append((unit.name, action.ability_index, round(rehearsal.swing, 2)))
    assert wrong == [], wrong
    assert examined >= _EXAMINED_FLOOR // every, examined
    assert proposed >= _PROPOSED_FLOOR // every, proposed


def test_firebreathing_with_no_fight_left_is_not_bought():
    """Shivan Dragon's "{R}: +1/+0 until end of turn" in the postcombat main
    phase: gone by the end of the turn, and nothing to fight. The base paid
    {R} for it every second main phase."""
    game, _report = _table(("Shivan Dragon", "Mountain", "Mountain"))
    assert choose_activation_action(game, 0) is None


def test_a_fight_the_pump_does_not_change_waits_for_the_blocks():
    """Before its combat, against a board with nothing that flies: the Dragon
    attacks with or without the pump and nothing can block it, so
    firebreathing is not bought in the main phase — and in the
    declare-blockers step, unblocked, the seat pumps it there."""
    game, report = _table(
        ("Shivan Dragon", "Mountain", "Mountain"), step="precombat_main",
    )
    assert choose_activation_action(game, 0) is None
    run_ai_combat_phase(game, 0)
    assert game.current_turn_phase != "combat"
    pumped = [
        line for line in report.log_lines
        if "activate Shivan Dragon" in line and "declare blockers" in line
    ]
    assert pumped, report.log_lines
    assert game.players[1].life < 20 - 5, game.players[1].life


def test_a_shield_that_makes_the_attack_is_still_bought_before_it():
    """Zealous Inquisitor's redirect against a Grizzly Bears: without it the
    2/2 stays home (a trade), with it the Bears does not block — an attack the
    redirect adds (``Rehearsal.declarations_changed``), so it is bought
    before the attack as before (the board SCG Phase 5 saw)."""
    game, _report = _table(
        ("Zealous Inquisitor", "Plains", "Plains"), step="precombat_main",
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Zealous Inquisitor", action
    with deliberating():
        fought = _rehearse_activation(game, 0, action, through_combat=True)
    assert fought is not None and fought.declarations_changed
