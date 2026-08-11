"""Per-card tests for Core Set 2021 (M21) — a *measured* set, mid-implementation.

Cards land here with the round that buys them (tests/sets/README.md,
SET_PLAYBOOK.md Phase 3). The pool resolves through ``set_pool("M21")`` even
though the set is not shipped: reading a card file is not shipping it, and a
card's focused test is written while its set is still under ``measured``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- The keyword round: flash, menace, hexproof(+from), prowess, ------------
# --- deathtouch, indestructible ---------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Mistral Singer",       # Flying // Prowess
        "Masked Blackguard",    # Flash // pump ability
        "Bone Pit Brute",       # Menace // ETB pump
        "Ornery Dilophosaur",   # Deathtouch // conditional attack trigger
    ],
)
def test_keyword_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_bone_pit_brute_cannot_be_blocked_by_one_creature(set_pool):
    brute = Permanent(card=set_pool("M21")["Bone Pit Brute"])
    blocker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[brute])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers

    ok, msg = game.declare_blockers(1, {0: 0})
    assert not ok
    assert "menace" in msg.lower()


def test_mistral_singer_pumps_on_a_noncreature_cast(set_pool):
    singer = Permanent(card=set_pool("M21")["Mistral Singer"])
    opt = set_pool("M21")["Opt"]
    p1 = PlayerState(
        name="P1", battlefield=[singer], hand=[opt],
        library=[set_pool("M21")["Island"], set_pool("M21")["Island"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Opt")

    assert singer.effective_power == 3  # 2/2 printed, +1/+1 from prowess
    assert singer.effective_toughness == 3


def test_masked_blackguard_casts_at_instant_speed(set_pool):
    assert set_pool("M21")["Masked Blackguard"].has_flash
