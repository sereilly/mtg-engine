"""Pool-wide: no shield and no damage redirect is bought with nothing coming,
in any window an AI seat is asked (SCG Phase 5, AI-2).

Zealous Inquisitor ("{1}{W}: The next 1 damage that would be dealt to this
creature this turn is dealt to target creature instead") was activated in its
controller's main phase, and that controller then attacked with nothing. A
shield was already rehearsed before the main-phase chooser proposed it
(``ai_valuation.shields_only``, LGN Phase 5); a CR 614.9 redirect, categorised
``damage``, was not, and scored a flat 2.5.

The population is every usable activated ability, both manifest roles, whose
every step is a CR 615 shield, a CR 701.19 regeneration shield or a CR 614
damage replacement (``SHIELD_KINDS`` | ``DAMAGE_REPLACEMENT_KINDS``, the
choice of a creature beside one aside). Each is put on the AI's board with a
creature on each side and asked, ability by ability
(``ai_abilities._activation_candidate``, the gate every chooser runs), in the
windows where nothing can be coming:

* **the AI's postcombat main phase**, the stack empty — the main-phase
  chooser's own moment;
* **its own end step** — where the web's AI step asks that chooser too;
* **the opponent's end step**, the stack empty — the engine's priority
  answer (``ai_policy.choose_instant_speed_activation``).

Validated backwards: with the redirects read as on 43a45e81 (no shields), the
main-phase window proposes them — Zealous Inquisitor and the en-Kor among
them.
"""
from __future__ import annotations

from unittest import mock

import pytest

from engine import ai_valuation
from engine.ai_abilities import _activation_candidate, choose_activation_action
from engine.ai_policy import choose_instant_speed_activation
from engine.ai_valuation import DAMAGE_REPLACEMENT_KINDS, SHIELD_KINDS
from engine.ai_weighed_cast import _effect_steps
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES
from engine.mixins._constants import phases_after
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick


def _pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _is_shield_or_redirect(instruction) -> bool:
    steps = [s for s in _effect_steps(instruction) if s.kind != "choose_permanent"]
    return bool(steps) and all(
        s.kind in SHIELD_KINDS or s.kind in DAMAGE_REPLACEMENT_KINDS for s in steps
    )


def _population(pool) -> list:
    rows = []
    for name, card in sorted(pool.items()):
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is not None and _is_shield_or_redirect(ability.instruction):
                redirect = any(
                    s.kind in DAMAGE_REPLACEMENT_KINDS for s in _effect_steps(ability.instruction)
                )
                rows.append((card, index, redirect))
    return rows


def _board(pool, card, step: str, active: int) -> Game:
    bears = pool["Grizzly Bears"]
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    source = _nosick(Permanent(card=card))
    game.players[0].battlefield = [source, _nosick(Permanent(card=bears))]
    game.players[1].battlefield = [_nosick(Permanent(card=bears))]
    for player in game.players:
        player.library = [pool["Plains"]] * 10
    if "Aura" in (card.type_line or ""):
        attach_aura(source, game.players[0].battlefield[1])
    game._recompute_continuous_effects()
    game.active_player_index = active
    game.current_turn_phase = "ending" if step == "end" else step
    game.current_step = step
    game.turn_phases_remaining = phases_after("postcombat_main")
    if step == "end":
        game.turn_phases_remaining = []
    return game


def _census(pool) -> dict:
    found = {"examined": 0, "redirects": 0, "idle": []}
    for card, index, redirect in _population(pool):
        found["examined"] += 1
        found["redirects"] += bool(redirect)
        for window, step, active in (
            ("main phase 2", "postcombat_main", 0),
            ("own end step", "end", 0),
            ("opponent's end step", "end", 1),
        ):
            game = _board(pool, card, step, active)
            source = game.players[0].battlefield[0]
            usable = game.usable_abilities_of(source)
            if index >= len(usable):
                continue
            if window == "main phase 2":
                proposed = _activation_candidate(
                    game, 0, 0, source, usable[index], None if index == 0 else index,
                ) is not None
            else:
                chooser = choose_activation_action if active == 0 else choose_instant_speed_activation
                action = chooser(game, 0)
                proposed = action is not None and action.permanent_index == 0
            if proposed:
                found["idle"].append((card.name, index, window))
    return found


def test_no_shield_or_redirect_is_bought_with_nothing_coming():
    found = _census(_pool())
    assert found["idle"] == [], found["idle"]
    assert found["examined"] >= 150, found["examined"]
    assert found["redirects"] >= 20, found["redirects"]


@pytest.mark.full
def test_with_the_redirects_scored_flat_the_census_finds_zealous_inquisitor():
    """Backwards: ``shields_only`` reading the shields alone, as on 43a45e81."""
    def shields_alone(instruction):
        steps = _effect_steps(instruction) if instruction is not None else ()
        return bool(steps) and all(step.kind in SHIELD_KINDS for step in steps)

    with mock.patch("engine.ai_abilities.shields_only", shields_alone):
        found = _census(_pool())
    idle = {name for name, _index, window in found["idle"] if window == "main phase 2"}
    # (Shield Dancer is not among them: "target attacking creature" has no
    # target in a main phase 2, so it was never proposed there.)
    assert {"Zealous Inquisitor", "Zhalfirin Crusader", "Kjeldoran Royal Guard"} <= idle, sorted(idle)
    assert len(idle) >= 15, sorted(idle)


def test_every_damage_replacement_kind_is_read_as_a_shield():
    """Every kind of the ``damage`` category that redirects a damage event
    (CR 614.9) is in ``DAMAGE_REPLACEMENT_KINDS``, and every kind there is a
    ``damage`` kind — so a new redirect is rehearsed from the day it lands."""
    redirects = {
        kind for kind, family in INSTRUCTION_CATEGORIES.items()
        if family == "damage" and "redirect" in kind
    }
    assert redirects <= DAMAGE_REPLACEMENT_KINDS, sorted(redirects - DAMAGE_REPLACEMENT_KINDS)
    assert {INSTRUCTION_CATEGORIES.get(kind) for kind in DAMAGE_REPLACEMENT_KINDS} == {"damage"}
    assert not DAMAGE_REPLACEMENT_KINDS & SHIELD_KINDS
    assert ai_valuation.shields_only(
        next(iter(usable_activated_abilities(compile_card_oracle(_pool()["Zealous Inquisitor"])))).instruction
    )
