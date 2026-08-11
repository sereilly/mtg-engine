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


# --- The token-naming round: CR 111.4 names unnamed tokens ------------------


@pytest.mark.parametrize(
    "name",
    [
        "Valorous Steed",         # ETB: 2/2 white Knight token with vigilance
        "Deathbloom Thallid",     # dies: 1/1 green Saproling token
        "Falconer Adept",         # attacks: 1/1 white Bird token — still gated
        "Goblin Wizardry",        # two 1/1 red Wizard tokens with prowess
        "Sporeweb Weaver",        # dealt damage: gain 1 life + Saproling token
        "Speaker of the Heavens", # {T}: 4/4 white Angel token, conditional
    ],
)
def test_token_round_cards_compile_supported(set_pool, name):
    if name == "Falconer Adept":
        pytest.skip("still gated on the tapped-and-attacking rider")
    assert compile_card_oracle(set_pool("M21")[name]).supported


# --- The each-opponent round: damage and life loss sweep the table ----------


@pytest.mark.parametrize(
    "name",
    [
        "Storm Caller",           # ETB: deals 2 damage to each opponent
        "Spirit of Malevolence",  # dies: each opponent loses 1 life
        "Grim Tutor",             # tutor + "You lose 3 life"
        "Caged Zombie",           # activated: each opponent loses 2 life
    ],
)
def test_each_opponent_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_storm_caller_damages_each_opponent_on_entry(set_pool):
    caller = set_pool("M21")["Storm Caller"]
    p1 = PlayerState(name="P1", hand=[caller])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Storm Caller")

    assert p2.life == 18
    assert p1.life == 20


# --- The counter round: +1/+1 counters on non-source subjects ---------------


def test_basris_solidarity_counters_each_of_your_creatures(set_pool):
    """"Put a +1/+1 counter on each creature you control." — the sweep counts
    the caster's side only, through the control seam."""
    solidarity = set_pool("M21")["Basri's Solidarity"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    theirs = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[solidarity])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    base_mine = mine.effective_power
    base_theirs = theirs.effective_power
    game.cast_from_hand(0, "Basri's Solidarity")

    assert mine.effective_power == base_mine + 1
    assert theirs.effective_power == base_theirs


def test_valorous_steed_token_takes_its_cr_111_4_name(set_pool):
    program = compile_card_oracle(set_pool("M21")["Valorous Steed"])
    create = next(
        trig.instruction
        for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "create_token"
    )
    assert create.payload["name"] == "Knight Token"
    assert create.payload["keywords"] == ("Vigilance",)
