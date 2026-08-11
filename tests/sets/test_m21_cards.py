"""Per-card tests for Core Set 2021 (M21) — a *measured* set, mid-implementation.

Cards land here with the round that buys them (tests/sets/README.md,
SET_PLAYBOOK.md Phase 3). The pool resolves through ``set_pool("M21")`` even
though the set is not shipped: reading a card file is not shipping it, and a
card's focused test is written while its set is still under ``measured``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.grammar import compile_line
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


# --- The search round: the filter the flow honours, and the two-zone fetch ---


@pytest.mark.parametrize(
    "name",
    [
        "Fierce Empath",        # search for a creature with mana value 6+
        "Chandra's Firemaw",    # library and/or graveyard, for a named card
        "Garruk's Warsteed",
        "Teferi's Wavecaster",
        "Liliana's Scorn",
    ],
)
def test_search_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_a_search_refuses_a_card_its_restriction_excludes(set_pool):
    """The engine is the authority on what may be found, not the client that
    offered the cards: an index outside the restriction is simply refused."""
    pool = set_pool("M21")
    big = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc >= 6)
    small = next(c for c in pool.values() if c.primary_type == "creature" and c.cmc < 6)
    p1 = PlayerState(name="P1", library=[small, big])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="creature",
        zones=("library",), restrictions={"mana_value": {"op": "ge", "value": 6}},
    )

    assert not game.confirm_search_library(0, 0)
    assert p1.hand == []
    assert game.pending_search_library is not None

    assert game.confirm_search_library(0, 1)
    assert [c.name for c in p1.hand] == [big.name]
    assert game.pending_search_library is None


def test_a_search_that_can_find_nothing_can_still_be_left(set_pool):
    """Failing to find is legal (CR 701.19b) and is the only answer available
    when nothing in the searched zones matches."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", library=[pool["Island"], pool["Island"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={"named": "Fierce Empath"},
    )

    assert game.decline_search_library(0)
    assert p1.hand == []
    assert len(p1.library) == 2
    assert game.pending_search_library is None


def test_a_search_cannot_be_answered_with_a_zone_it_was_not_armed_with(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", library=[pool["Island"]], graveyard=[pool["Alpine Watchdog"]]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library",), restrictions={},
    )

    assert not game.confirm_search_library(0, 0, "graveyard")
    assert p1.hand == []
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog"]


def test_a_graveyard_find_does_not_shuffle_the_library(set_pool):
    """CR 701.19d and the printed "If you search your library this way,
    shuffle": a graveyard is an open zone, so randomising a library the player
    did not search would destroy information they were entitled to keep."""
    pool = set_pool("M21")
    wanted = pool["Alpine Watchdog"]
    library = [pool["Island"], pool["Forest"], pool["Mountain"]]
    p1 = PlayerState(name="P1", library=list(library), graveyard=[wanted])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.arm_pending_choice(
        "search_library", 0, count=1, card_type="any",
        zones=("library", "graveyard"), restrictions={"named": "alpine watchdog"},
    )

    assert game.confirm_search_library(0, 0, "graveyard")
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert p1.graveyard == []
    assert [c.name for c in p1.library] == [c.name for c in library]


# --- The scry round (CR 701.22), and mill's recipient -----------------------


@pytest.mark.parametrize("name", ["Wall of Runes", "Spined Megalodon"])
def test_scry_round_cards_compile_supported(set_pool, name):
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_opt_no_longer_drops_its_scry(set_pool):
    """Regression for a *silent* wrong: Opt compiled supported on the strength
    of "Draw a card." alone while "Scry 1." produced no instruction at all, so
    the card played as a strictly worse Opt. Both sentences must be claimed."""
    kinds = [i.kind for i in compile_card_oracle(set_pool("M21")["Opt"]).instructions]
    assert "scry" in kinds
    assert "draw_controller_cards" in kinds


def test_temple_of_mystery_etb_scry_is_claimed(set_pool):
    program = compile_card_oracle(set_pool("M21")["Temple of Mystery"])
    assert any(
        t.instruction is not None and t.instruction.kind == "scry"
        for t in program.triggered_abilities
    )


def test_carrion_grub_etb_mills_its_own_controller(set_pool):
    """"Mill four cards." — a bare imperative, so the miller is the effect's
    controller and travels on the same `recipient` key life loss uses, rather
    than as a target the handler would read off `context.target`.

    Asserted on the line rather than the card: Carrion Grub's *other* line
    ("gets +X/+0, where X is the greatest power among creature cards in your
    graveyard") still refuses, and a refused line stops the creature compiling
    at all — so the card stays unsupported while this line is done.
    """
    grub = set_pool("M21")["Carrion Grub"]
    line = next(l for l in grub.oracle_text.split("\n") if "mill" in l)
    result = compile_line(line, card_name="Carrion Grub")

    assert result.lowered, result.failure_reason
    mill = result.instructions[0]
    assert mill.kind == "mill_target_player"
    assert mill.payload["recipient"] == "caster"
    assert mill.payload["amount"] == 4
    assert "targets" not in mill.payload  # a bare mill targets nobody
    assert not compile_card_oracle(grub).supported


def test_track_down_still_refuses_its_reveal_clause(set_pool):
    """Scry 3 parses now, but "then reveal the top card of your library" has no
    production — the sentence refuses whole rather than scrying and dropping
    the rest."""
    assert not compile_card_oracle(set_pool("M21")["Track Down"]).supported


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
