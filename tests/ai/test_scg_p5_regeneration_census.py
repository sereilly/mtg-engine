"""Pool-wide: every regeneration ability an AI seat could pay for is used on a
creature about to die in combat, in every window before the damage (SCG
Phase 5, AI-3).

Krosan Warchief ("{1}{G}: Regenerate target Beast") attacked, a person
blocked it with a creature that killed it, and the AI had {1}{G} open. The
engine's priority answer (``ai_priority.act_at_priority``) was right; the web
AI's step asks the main-phase chooser (``ai_abilities.choose_activation_action``)
in each step of the AI's turn, and that chooser passed over a tapped attacker.

The population is every usable activated ability, both manifest roles, whose
every step is a regeneration shield (CR 701.19a): "Regenerate this creature",
"Regenerate target <creature>", "Regenerate enchanted creature". Each is put on
the AI's board with the creature it protects — the source itself, a creature
the target picker offers, or the Aura's host — and that creature is about to
die to an opposing Craw Wurm (6/4). The census asks, in each window:

* **the AI attacking**, the Wurm blocking, the declare-blockers step after
  the blocks (CR 509.2: the active player gets priority) — both the engine's
  answer and the chooser the web asks;
* **the AI blocking** the attacking Wurm, the same step — the engine's answer;
* **in response** to a Lightning Bolt at the creature, for one Bolt kills.

A proposal must be that ability, aimed at the creature. An ability is left
out of a window, counted, where the policy declines its cost by rule (a
sacrifice, a discard, life, a counter: ``_activation_candidate``'s floors),
where its {T} cannot be paid by a tapped attacker, and where the creature
would not die there.
"""
from __future__ import annotations

import collections
import copy

import pytest

from engine.ai_abilities import choose_activation_action
from engine.activation_restrictions import activation_denial
from engine.ai_priority import act_at_priority
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from engine.ai_weighed_cast import _effect_steps
from tests.helpers import _nosick, declare_attack, resolve_stack

_REGENERATION = frozenset({
    "grant_regeneration_to_self",
    "grant_regeneration_to_target_creature",
    "grant_regeneration_to_enchanted_creature",
})


def _pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _priced(cost) -> bool:
    """Whether the own-board chooser prices *cost* at all (its floors)."""
    return not (
        cost.sacrifice_filter is not None or cost.discard_cards or cost.pay_life
        or cost.put_counter_filter is not None or cost.remove_counter_filter is not None
        or cost.exile_top_of_library or cost.exile_graveyard_position is not None
        or cost.remove_counter is not None or cost.mana_from_attached
        or cost.sacrifice_self or cost.exile_self or cost.return_self_to_hand
        or cost.tap_count or cost.return_to_hand_count
    )


def _population(pool) -> list:
    rows = []
    for name, card in sorted(pool.items()):
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            steps = _effect_steps(ability.instruction) if ability.instruction is not None else ()
            if steps and all(step.kind in _REGENERATION for step in steps):
                rows.append((card, index, ability, steps[0].kind))
    return rows


def _seat_the_protected(pool, card, kind):
    """``(the AI's battlefield, the protected creature's slot)`` or None."""
    source = _nosick(Permanent(card=card))
    if kind == "grant_regeneration_to_enchanted_creature":
        if "Aura" not in (card.type_line or ""):
            return None
        host = _nosick(Permanent(card=pool["Grizzly Bears"]))
        attach_aura(source, host)
        return [host, source], 0
    if not source.is_creature:
        return None
    return [source], 0


def _game(pool, battlefield, *, ai_attacks: bool) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].battlefield = list(battlefield)
    game.players[1].battlefield = [_nosick(Permanent(card=pool["Craw Wurm"]))]
    for player in game.players:
        player.library = [pool["Forest"]] * 10
    game._recompute_continuous_effects()
    return game


def _aimed_at(game, action, protected) -> bool:
    if action is None:
        return False
    source = game.permanent_at(0, action.permanent_index)
    if source is None:
        return False
    target = action.target_permanent_index
    if target is None:
        return source is protected or source.metadata.get("attached_to") is protected
    return game.permanent_at(action.target_player_index, target) is protected


def _dies_without_it(game, protected) -> bool:
    """Whether *protected* is gone once what is coming has happened — the
    stack resolved and the combat's damage dealt — on a copy of the table
    with nothing activated. Protection from the attacker's colour, a
    first-striking blocker, a flanking shrink: the engine's answer, not a
    reading of the numbers."""
    table = copy.deepcopy(game)
    if table.stack:
        resolve_stack(table)
        table.check_state_based_actions()
    for _ in range(3):
        if table.current_turn_phase != "combat" or table.current_step not in (
            "declare_attackers", "declare_blockers",
        ):
            break
        table.advance_combat_phase()
    return table.permanent_by_id(protected.permanent_id) is None


def _set_up(pool, game, window, slot) -> "str | None":
    """Put *game* in *window*; a reason it cannot be, or None."""
    if window.startswith("attacking"):
        try:
            declare_attack(game, 0, blocks={0: 0})
        except (AssertionError, IndexError):
            return "cannot attack"
        resolve_stack(game)  # its own triggers ("whenever this becomes blocked")
        return None
    if window == "blocking":
        try:
            declare_attack(game, 1, blocks={slot: 0})
        except (AssertionError, IndexError):
            return "cannot block"
        resolve_stack(game)
        return None
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    game.players[1].hand = [pool["Lightning Bolt"]]
    cast = game.queue_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=slot)
    return None if cast.supported else "the Bolt is refused"


def _census(pool) -> dict:
    found = {"examined": [], "missed": [], "taken": collections.Counter(),
             "left_out": collections.Counter()}
    for card, index, ability, kind in _population(pool):
        if index != 0:
            found["left_out"]["not the first ability"] += 1
            continue
        if not _priced(ability.cost):
            found["left_out"]["a cost the policy declines"] += 1
            continue
        if _seat_the_protected(pool, card, kind) is None:
            found["left_out"]["no creature of its own to protect"] += 1
            continue
        found["examined"].append(card.name)
        for window in ("attacking", "attacking (web door)", "blocking", "response"):
            battlefield, slot = _seat_the_protected(pool, card, kind)
            protected = battlefield[slot]
            game = _game(pool, battlefield, ai_attacks=window.startswith("attacking"))
            source = game.players[0].battlefield[-1] if len(battlefield) > 1 else protected
            if window.startswith("attacking") and ability.cost.requires_tap and source is protected:
                found["left_out"][f"{window}: its {{T}} on a tapped attacker"] += 1
                continue
            reason = _set_up(pool, game, window, slot)
            if reason is None and not _dies_without_it(game, protected):
                reason = "would not die"
            if reason is None and activation_denial(game, 0, source, ability.source_line or ""):
                reason = "an activation restriction stands"  # Threshold, "only if dealt damage"
            if reason is None and kind == "grant_regeneration_to_target_creature" and not any(
                game.permanent_at(entry.get("seat"), entry.get("index")) is protected
                for entry in game.activation_target_spec(
                    0, game.players[0].battlefield.index(source),
                ).get("valid_targets") or ()
            ):
                reason = "its target picker does not offer it"
            if reason is not None:
                found["left_out"][f"{window}: {reason}"] += 1
                continue
            if window == "attacking (web door)":
                action = choose_activation_action(game, 0)
            else:
                act = act_at_priority(game, 0)
                action = act.action if act is not None and act.kind == "activate" else None
            if _aimed_at(game, action, protected):
                found["taken"][window] += 1
            else:
                found["missed"].append((card.name, window))
    return found


@pytest.mark.full
def test_every_regeneration_the_ai_can_pay_for_saves_a_creature_about_to_die():
    found = _census(_pool())
    assert found["missed"] == [], found["missed"]
    assert len(found["examined"]) >= 60, found["examined"]
    for window in ("attacking", "attacking (web door)", "blocking", "response"):
        assert found["taken"][window] >= 30, (window, found["taken"])
    assert "Krosan Warchief" in found["examined"]


@pytest.mark.full
def test_with_the_chooser_answering_as_a_main_phase_the_web_door_misses_them():
    """Backwards: ``choose_activation_action`` answering every moment as its
    main phase, as on 43a45e81. The engine's own windows were right there
    too; the web's door was not — 45 of the 51 attackers (the six it took
    stay untapped as they attack)."""
    from unittest import mock

    from engine import ai_abilities

    with mock.patch.object(ai_abilities, "_at_sorcery_speed", lambda game, seat: True):
        found = _census(_pool())
    missed = [name for name, window in found["missed"] if window == "attacking (web door)"]
    assert len(missed) >= 40, found["missed"]
    assert "Krosan Warchief" in missed
    assert {window for _name, window in found["missed"]} == {"attacking (web door)"}
