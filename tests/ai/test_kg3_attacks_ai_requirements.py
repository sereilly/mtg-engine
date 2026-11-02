"""The AI's attack declarations under CR 508.1d's maximisation.

The declaration gate now refuses a declaration that obeys fewer requirements
than the most the board allows — so an AI whose prune drops the compelled
creature for a cap, or which aims every creature at the player when the only
free attack is at a planeswalker, would be refused, and a refused declaration
is silent: the seat attacks with nobody. The AI asks the engine's own
maximisation last (``Game.obeying_attack_declaration``), and declares its
answer with each creature's aim.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine import ai_rehearsal
from engine.ai_combat import CombatOutcome, declare_ai_attackers
from engine.ai_declarations import choose_attackers
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_catalog, manifest_set_path
from engine.combat_restrictions import participation_cap
from engine.models import Permanent

from tests.helpers import _mk_card, _mk_creature_card, _nosick

_CARDS = {card.name: card for card in load_catalog()}


def _declaring(mine, theirs):
    game = Game(players=[
        PlayerState(name="AI", battlefield=list(mine),
                    library=[_mk_card("Top", "Land")] * 3),
        PlayerState(name="Opp", battlefield=list(theirs),
                    library=[_mk_card("Top", "Land")] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    for perm in game.players[0].battlefield:
        _nosick(perm)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game


def _named(name):
    return Permanent(card=_CARDS[name])


@pytest.mark.cr("508.1d")
def test_under_dueling_grounds_the_ai_sends_the_compelled_creature():
    """A Craw Wurm is worth more than a Juggernaut, so the cap's prune keeps
    the Wurm — and the Wurm attacking alone obeys no requirement while the
    Juggernaut alone obeys one. The AI sends the Juggernaut, and the gate
    takes it first time."""
    game = _declaring(
        [_named("Juggernaut"), _named("Craw Wurm"), _named("Dueling Grounds")], [],
    )
    assert choose_attackers(game, 0) == [0]
    outcome = CombatOutcome()
    ok, why = declare_ai_attackers(game, 0, outcome=outcome)
    assert ok, why
    assert not outcome.refused_attacks
    assert sorted(game.combat_attackers) == [0]


@pytest.mark.cr("508.1b", "508.1d")
def test_the_ai_attacks_the_planeswalker_the_requirement_can_reach_for_free():
    """Juggernaut beside the opponent's Propaganda and Basri Ket, with no land
    to pay the toll: attacking the player is out of reach, attacking the
    planeswalker is free, so the requirement compels that — and the AI, which
    aims at players, is handed the planeswalker by the engine."""
    game = _declaring(
        [_named("Juggernaut")], [_named("Propaganda"), _named("Basri Ket")],
    )
    walker = next(p for p in game.players[1].battlefield if p.has_type("planeswalker"))
    outcome = CombatOutcome()
    ok, why = declare_ai_attackers(game, 0, outcome=outcome)
    assert ok, why
    assert not outcome.refused_attacks and not outcome.silent_attacks
    assert game.combat_attacked_planeswalkers == {0: walker.permanent_id}


@pytest.mark.cr("508.1d")
def test_the_last_rung_is_the_fewest_the_requirements_allow():
    """"Nobody" was the fallback's last rung, and under Dueling Grounds beside
    a compelled creature it is illegal. An override the gate refuses whole (the
    Debug Menu's "attack with everything") is turned into the nearest legal
    declaration rather than into no attack."""
    game = _declaring(
        [_named("Juggernaut"), _mk_bear(), _named("Dueling Grounds")], [],
    )
    ok, why = declare_ai_attackers(game, 0, attacker_indices=[0, 1])
    assert ok, why
    assert sorted(game.combat_attackers) == [0]


def _mk_bear():
    return Permanent(card=_mk_creature_card("Bear", 2, 2))


@pytest.mark.full
@pytest.mark.cr("508.1d")
def test_a_seeded_game_with_a_cap_and_compelled_creatures_declares_legally(monkeypatch):
    """Dueling Grounds and Juggernaut pinned into both decks: the run
    completes, no attack declaration is refused, and at least one declaration
    was judged on a board carrying both a cap and a requirement (a floor —
    never how often)."""
    original = Game.attack_requirement_refusal
    judged: list[int] = []

    def spy(self, controller_index, declared):
        if not ai_rehearsal.rehearsing() and self.attack_requirements(
            controller_index
        ) and participation_cap(self.all_permanents(), "attack") is not None:
            judged.append(controller_index)
        return original(self, controller_index, declared)

    monkeypatch.setattr(Game, "attack_requirement_refusal", spy)
    report = run_ai_simulation(
        [manifest_set_path("LEA"), manifest_set_path("INV")], games=3, seed=1337,
        max_turns=14, required_cards=["Dueling Grounds", "Juggernaut", "Juggernaut"],
    )
    assert report.games_completed == 3
    assert not report.refused_attacks, report.refused_attacks
    assert not report.rehearsals_raised
    assert not [issue for issue in report.issues if "attacked with nobody" in str(issue)]
    assert judged, "no declaration met a cap and a requirement together"
