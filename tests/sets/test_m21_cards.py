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


# --- The causative round: "you may have <subject> <verb> ..." ---------------


@pytest.mark.parametrize("name", ["Goblin Arsonist", "Battle-Rattle Shaman"])
def test_causative_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_goblin_arsonist_may_ping_when_it_dies(set_pool):
    """"You may have it deal 1 damage to any target" — the may wrapper arms
    the standard optional prompt, and accepting deals the damage."""
    arsonist = Permanent(card=set_pool("M21")["Goblin Arsonist"])
    p1 = PlayerState(name="P1", battlefield=[arsonist])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(arsonist)
    game._permanent_to_graveyard(p1, arsonist)
    game.resolve_top_of_stack()

    assert any(e["card_name"] == "Goblin Arsonist" for e in game.pending_optional_pays)
    game.confirm_optional_pay(0, "Goblin Arsonist", accept=True)
    assert p2.life == 19


# --- The trigger-narrowing round: conditions carry their own restrictions ---


def test_quirion_dryad_counters_only_the_listed_colours(set_pool):
    """"Whenever you cast a spell that's white, blue, black, or red" — a green
    spell is not in the list, so it must not fire the trigger."""
    dryad = Permanent(card=set_pool("M21")["Quirion Dryad"])
    red = set_pool("M21")["Shock"]
    green = set_pool("M21")["Titanic Growth"]
    p1 = PlayerState(name="P1", battlefield=[dryad], hand=[red, green])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    base = dryad.effective_power

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1

    game.cast_from_hand(0, "Titanic Growth", target_player_index=0, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert dryad.effective_power == base + 1 + 4  # the +4/+4 pump lands, the counter does not


def test_adherent_of_hope_counters_on_its_controllers_combat_only(set_pool):
    adherent = Permanent(card=set_pool("M21")["Adherent of Hope"])
    p1 = PlayerState(name="P1", battlefield=[adherent])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    base = adherent.effective_power

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat, controller's turn
    game.resolve_top_of_stack()
    assert adherent.effective_power == base + 1

    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()  # opponent's combat: no trigger
    assert adherent.effective_power == base + 1


# --- The mana-value round: a literal bound rides the payload ----------------


def test_eliminate_compiles_with_its_mana_value_bound(set_pool):
    program = compile_card_oracle(set_pool("M21")["Eliminate"])
    assert program.supported
    destroy = next(i for i in program.instructions if i.kind == "destroy_target_permanent")
    assert destroy.payload["mana_value"] == {"op": "le", "value": 3}


def test_eliminate_refuses_a_four_drop(set_pool):
    """The bound is enforced at cast validation, not just carried."""
    eliminate = set_pool("M21")["Eliminate"]
    cheap = Permanent(card=set_pool("M21")["Concordia Pegasus"])   # MV 2
    big = Permanent(card=set_pool("M21")["Warden of the Woods"])   # MV 5
    p1 = PlayerState(name="P1", hand=[eliminate])
    p2 = PlayerState(name="P2", battlefield=[cheap, big])
    game = Game(players=[p1, p2])

    ok, _ = game._validate_cast_targets(
        eliminate, 0, target_player_index=1, target_permanent_index=1
    )
    assert not ok
    ok, msg = game._validate_cast_targets(
        eliminate, 0, target_player_index=1, target_permanent_index=0
    )
    assert ok, msg


# --- The keyword-grant round: "gains <keyword> until end of turn" -----------


@pytest.mark.parametrize(
    "name",
    [
        "Sure Strike",     # +3/+0 and gains first strike
        "Ranger's Guile",  # your creature gains hexproof
        "Fetid Imp",       # {B}: this creature gains deathtouch
    ],
)
def test_keyword_grant_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_rangers_guile_grants_hexproof_for_the_turn(set_pool):
    guile = set_pool("M21")["Ranger's Guile"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[guile])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Ranger's Guile", target_player_index=0, target_permanent_index=0)

    assert mine.has_keyword("hexproof")
    bolt = set_pool("M21")["Shock"]
    assert game._can_be_targeted(mine, bolt, caster_index=1) is False
    assert game._can_be_targeted(mine, bolt, caster_index=0) is True


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
