"""Seeded games that use the declare-attackers window (kg3 `aidefend`).

Floors, never counts: each run asserts its subject was exercised at least
once — an ambush blocker cast before the blocks, an ability activated there,
Swooping Talon shedding its flying for the creature it provoked — that the
report's honesty count is what the engine's own cast seam saw, and that no
rehearsal raised.
"""
from __future__ import annotations

import pytest

from engine.ai_rehearsal import rehearsing
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.game import Game

pytestmark = pytest.mark.full


def test_a_seeded_urzas_legacy_run_casts_an_ambush_blocker():
    """Urza's Legacy's three flash creatures pinned into both decks: a
    defending seat casts one in the declare-attackers step at least once,
    and ``casts_before_blocks`` is exactly what a spy on
    ``Game.queue_from_hand`` saw cast there by a seat that was not active."""
    seen = []
    original = Game.queue_from_hand

    def queue_from_hand(self, caster_index, card_name, *args, **kwargs):
        before_blocks = (
            not rehearsing()
            and self.current_step == "declare_attackers"
            and not self.stack
            and caster_index != self.active_player_index
        )
        result = original(self, caster_index, card_name, *args, **kwargs)
        if before_blocks and result.supported:
            seen.append(card_name)
        return result

    Game.queue_from_hand = queue_from_hand
    try:
        report = run_ai_simulation(
            manifest_set_path("ULG"), games=3, seed=1337,
            required_cards=["Simian Grunts", "Defender of Law", "Defender of Chaos"],
        )
    finally:
        Game.queue_from_hand = original

    assert report.games_completed == 3
    assert report.casts_before_blocks >= 1, report.casts_before_blocks
    assert report.casts_before_blocks == len(seen), seen
    assert report.activations_at_instant_speed["declare_attackers"] >= 1
    assert not report.rehearsals_raised, dict(report.rehearsals_raised)
    assert not report.steps_left_owing, dict(report.steps_left_owing)
    assert not report.refused_instant_casts, dict(report.refused_instant_casts)


def test_a_seeded_legions_run_sheds_talons_flying_for_its_provoke():
    """The provoke cards pinned as in ``test_ai_lgn_w1g2_provoke``: at least
    once a provoke is taken against a creature that could not block a flier,
    and Swooping Talon then pays {1} in the declare-attackers step to let it.
    The defending AI obeys every requirement (no block refused).

    Seed 11 since SCG Phase 5. Seed 1337's second game had Beacon of Destiny
    tap itself in its own precombat main phase on turns 3 to 5, to redirect
    damage nothing could deal it on its own turn — a CR 614.9 redirect the
    main-phase chooser scored flat. Rehearsed now
    (``ai_valuation.DAMAGE_REPLACEMENT_KINDS``), the Beacon attacks instead,
    and that game no longer reaches the provoke this test is about."""
    report = run_ai_simulation(
        manifest_set_path("LGN", include_measured=True), games=3, seed=11,
        required_cards=[
            "Goblin Grappler", "Lowland Tracker", "Krosan Vorine", "Hunter Sliver",
            "Brontotherium", "Deftblade Elite", "Swooping Talon", "Crested Craghorn",
        ],
    )
    assert report.games_completed == 3
    assert any(
        "activate Swooping Talon" in line and "[in the declare attackers step]" in line
        for line in report.log_lines
    )
    assert any("blocks Swooping Talon this combat if able" in line for line in report.log_lines)
    assert any("Swooping Talon loses flying until end of turn" in line for line in report.log_lines)
    assert not report.rehearsals_raised, dict(report.rehearsals_raised)
    assert not report.refused_blocks
