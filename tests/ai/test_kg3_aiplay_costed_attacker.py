"""A costed attacker the AI chose survives CR 508.1d's search (kg3 `aiplay`,
part 3).

When the AI's attack has to go through the maximisation
(``ai_declarations._obeying_declaration`` → ``Game.obeying_attack_declaration``),
the search walks only the attacks that cost nothing — CR 508.1d does not make
a player pay to obey a requirement — so a creature the seat had chosen to
attack with, and planned the toll for, fell out of the declaration the search
handed back. The maximum is over requirements; among the declarations that
reach it the seat's preference decides, so what the search leaves out of the
preference is offered back where the requirements and restrictions allow
(``AttackRequirementsMixin._with_the_preference_kept``).

The board: a Craw Wurm under Brainwash ("Enchanted creature can't attack
unless its controller pays {3}") beside an Ekundu Cyclops ("If a creature you
control attacks, this creature also attacks if able"), three Mountains. The
seat sends the Wurm and pays its toll; the Wurm attacking compels the
Cyclops, so the declaration "the Wurm alone" obeys fewer requirements than
the board allows and the search is asked. Its answer — the Cyclops, which
attacks for free — dropped the Wurm.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import CombatOutcome, declare_ai_attackers
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_card, _nosick

_CARDS = {card.name: card for card in load_catalog()}


def _declaring(mine, theirs, *, brainwashed=None):
    game = Game(players=[
        PlayerState(name="AI", battlefield=[Permanent(card=_CARDS[n]) for n in mine],
                    library=[_mk_card("Top", "Land")] * 3),
        PlayerState(name="Opp", battlefield=[Permanent(card=_CARDS[n]) for n in theirs],
                    library=[_mk_card("Top", "Land")] * 3),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game._sync_control()
    if brainwashed is not None:
        host = next(p for p in game.controlled_by(0) if p.card.name == brainwashed)
        aura = next(p for p in game.controlled_by(1) if p.card.name == "Brainwash")
        attach_aura(aura, host)
    game.start_turn(0)
    for perm in game.players[0].battlefield:
        _nosick(perm)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game


def _slot(game, name):
    return next(
        game.battlefield_index_of(p) for p in game.controlled_by(0) if p.card.name == name
    )


def _board():
    return _declaring(
        ["Craw Wurm", "Ekundu Cyclops", "Mountain", "Mountain", "Mountain"],
        ["Brainwash"], brainwashed="Craw Wurm",
    )


@pytest.mark.cr("508.1d")
def test_the_searched_declaration_keeps_the_attacker_the_seat_pays_for():
    game = _board()
    wurm, cyclops = _slot(game, "Craw Wurm"), _slot(game, "Ekundu Cyclops")
    declaration = game.obeying_attack_declaration(0, [wurm], against=1)
    assert sorted(declaration.attackers) == sorted([wurm, cyclops])
    assert declaration.seats == {wurm: 1, cyclops: 1}


@pytest.mark.cr("508.1d", "508.1h")
def test_the_ai_declares_it_and_pays_the_toll():
    """The seat's preference declared through the AI's own road: both
    creatures attack, the Wurm's {3} is paid, nothing is refused."""
    game = _board()
    wurm, cyclops = _slot(game, "Craw Wurm"), _slot(game, "Ekundu Cyclops")
    outcome = CombatOutcome()
    ok, why = declare_ai_attackers(game, 0, attacker_indices=[wurm], outcome=outcome)
    assert ok, why
    assert not outcome.refused_attacks
    assert sorted(game.combat_attackers) == sorted([wurm, cyclops])
    assert sum(1 for p in game.controlled_by(0) if p.has_type("land") and p.tapped) == 3


@pytest.mark.cr("508.1d")
def test_nothing_is_added_back_that_the_maximum_cannot_carry():
    """Dueling Grounds ("no more than one creature can attack each combat")
    beside a Juggernaut: the requirement takes the one place, and the Wurm
    the seat would rather send is not added back over the cap."""
    game = _declaring(["Juggernaut", "Craw Wurm", "Dueling Grounds"], [])
    juggernaut = _slot(game, "Juggernaut")
    declaration = game.obeying_attack_declaration(
        0, [_slot(game, "Craw Wurm")], against=1,
    )
    assert declaration.attackers == [juggernaut]


@pytest.mark.cr("508.1d", "508.1h")
def test_a_preference_the_lands_cannot_pay_for_is_not_handed_back_unchanged():
    """Juggernaut and Craw Wurm facing Propaganda ("{2} for each creature …
    attacking you") and a planeswalker, two Mountains: attacking the player
    with both costs {4}. The preference obeys the requirement and breaks no
    restriction, and was handed back as it stood — declared, it was refused
    whole. The searched answer attacks the planeswalker with both, free, and
    the AI's declaration is taken first time."""
    game = _declaring(
        ["Juggernaut", "Craw Wurm", "Mountain", "Mountain"], ["Propaganda", "Basri Ket"],
    )
    juggernaut, wurm = _slot(game, "Juggernaut"), _slot(game, "Craw Wurm")
    outcome = CombatOutcome()
    ok, why = declare_ai_attackers(game, 0, outcome=outcome)
    assert ok, why
    assert not outcome.refused_attacks, outcome.refused_attacks
    assert juggernaut in game.combat_attackers
