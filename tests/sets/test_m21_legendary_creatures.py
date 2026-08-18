"""Core Set 2021 (M21) legendary creatures.

Split out of ``test_m21_creatures.py`` when that file reached the size guard in
``tests/engine/test_set_test_convention.py``. The axis is the one the convention
names — the **printed type** of the card each test is about — taken one step
further into the type line: "Legendary Creature — Vampire Cleric" is a supertype
plus a card type (CR 205.4a), and M21 prints eleven of them, so this is a
division the set keeps filling rather than a bucket invented to make a number go
down. Only four are supported today; the other seven land here as they arrive,
and so will the "legend rule reads the printed name" work (ROADMAP round 49),
since every legendary creature in the pool is M21's.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Barrin, Tolarian Archmage: a bounce, and the history it feeds ----------


def test_barrin_bounces_a_planeswalker_to_its_owners_hand(set_pool):
    """The union half: "up to one other target creature **or planeswalker**".
    And the CR 400.3 nuance the end-step test below leans on: the walker goes
    to its *owner's* hand, so bouncing the opponent's does not feed Barrin's
    own put-into-your-hand history."""
    pool = set_pool("M21")
    walker = Permanent(
        card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4},
    )
    p1 = PlayerState(name="P1", hand=[pool["Barrin, Tolarian Archmage"]])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(walker)
    assert any(c.name == "Garruk, Unleashed" for c in p2.hand)
    assert game.permanents_to_hand_this_turn.get(0, 0) == 0
    assert game.permanents_to_hand_this_turn.get(1, 0) == 1


def test_barrin_draws_at_end_step_after_bouncing_his_controllers_own(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(
        name="P1", hand=[pool["Barrin, Tolarian Archmage"]],
        battlefield=[mine], library=[pool["Island"]] * 3,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(
        0, "Barrin, Tolarian Archmage", target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Concordia Pegasus" for c in p1.hand)
    # The bounce landed in *your* hand, which is what the end-step
    # intervening-if reads (CR 603.4). The trigger goes on the stack and
    # resolves through the ordinary settle.
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert len(p1.hand) == hand_before + 1


def test_barrin_end_step_trigger_stays_quiet_without_a_bounce(set_pool):
    pool = set_pool("M21")
    barrin = Permanent(card=pool["Barrin, Tolarian Archmage"])
    p1 = PlayerState(name="P1", battlefield=[barrin], library=[pool["Island"]] * 3)
    game = Game(players=[p1, PlayerState(name="P2")])
    hand_before = len(p1.hand)
    game.resolve_end_step(0)
    game._settle()
    assert not game.stack
    assert len(p1.hand) == hand_before, (
        "nothing was put into Barrin's controller's hand from the battlefield "
        "this turn, so CR 603.4 keeps the trigger off the stack"
    )


# --- Azusa, Kaervek, Vito ---------------------------------------------------


def test_azusa_grants_two_additional_land_plays(set_pool):
    pool = set_pool("M21")
    azusa = Permanent(card=pool["Azusa, Lost but Seeking"])
    assert compile_card_oracle(azusa.card).supported
    p1 = PlayerState(name="P1", battlefield=[azusa], hand=[pool["Forest"]] * 4)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True  # CR 305.2's count is enforced in this mode

    plays = [game.cast_from_hand(0, "Forest").supported for _ in range(4)]
    assert plays == [True, True, True, False], "one land plus Azusa's two"


def test_kaervek_shrinks_every_other_creature_and_not_himself(set_pool):
    pool = set_pool("M21")
    kaervek = Permanent(card=pool["Kaervek, the Spiteful"])
    own_bird = Permanent(card=pool["Concordia Pegasus"])    # 1/3, his own side
    frail = Permanent(card=pool["Speaker of the Heavens"])  # 1/1, opposing
    p1 = PlayerState(name="P1", battlefield=[kaervek, own_bird])
    p2 = PlayerState(name="P2", battlefield=[frail])
    game = Game(players=[p1, p2])

    program = compile_card_oracle(kaervek.card)
    assert program.supported, program.reason
    game._recalculate_lord_buffs()

    assert kaervek.effective_power == 3, "'Other creatures' excludes the source"
    assert own_bird.effective_power == 0, "his own side shrinks too"
    assert frail.effective_toughness == 0
    game.check_state_based_actions()
    assert not game.is_on_battlefield(frail), "a 1/1 dies under him (CR 704.5f)"
    assert game.is_on_battlefield(own_bird)


def test_vito_drains_for_exactly_the_life_that_arrived(set_pool):
    """The trigger's number is the event's, not a printed amount: Revitalize
    gains 3, so the opponent loses 3."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    p1 = PlayerState(
        name="P1", battlefield=[vito], hand=[pool["Revitalize"]],
        library=[pool["Swamp"]] * 3,
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Revitalize")
    assert result.supported, result.details
    game._settle()

    assert p1.life == 23
    assert p2.life == 17, "target opponent loses that much life"


def test_vito_drains_off_his_own_lifelink_grant(set_pool):
    """His two lines meet: the {3}{B}{B} grant makes the team lifelink, combat
    damage gains life through the one seam, and the seam announces it."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    beater = _nosick(Permanent(card=pool["Alpine Watchdog"]))  # 2/2 vigilance
    p1 = PlayerState(name="P1", battlefield=[vito, beater])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(0, "Vito, Thorn of the Dusk Rose")
    assert result.supported, result.details
    game._settle()
    assert game._has_keyword(beater, "lifelink")

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [1])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert p1.life == 22, "lifelink gained 2"
    assert p2.life == 16, "2 combat damage, then Vito's 2"


def test_vito_stays_silent_when_the_opponent_gains_the_life(set_pool):
    """"Whenever **you** gain life" is the ability's controller (CR 109.5). The
    event is announced game-wide and the narrowing is the trigger's own word,
    so this is what the event filter is for."""
    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    p1 = PlayerState(name="P1", battlefield=[vito])
    p2 = PlayerState(
        name="P2", hand=[pool["Revitalize"]], library=[pool["Swamp"]] * 3
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(1, "Revitalize")
    assert result.supported, result.details
    game._settle()

    assert p2.life == 23
    assert p1.life == 20, "Vito's controller gained nothing, so nothing drained"


def test_vito_reads_the_life_a_replacement_left_and_not_the_life_intended(set_pool):
    """CR 614: a replaced life gain never happened. Lich replaces the whole
    gain with draws, so the event is not announced at all — which is why the
    emit is after the replacements rather than beside the intent."""
    from tests.helpers import CARDS_BY_NAME

    pool = set_pool("M21")
    vito = Permanent(card=pool["Vito, Thorn of the Dusk Rose"])
    lich = Permanent(card=CARDS_BY_NAME["Lich"])
    p1 = PlayerState(
        name="P1", battlefield=[vito, lich], library=[pool["Swamp"]] * 5
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    before = p1.life

    game._gain_life(p1, 3, "a test")
    game._settle()

    assert len(p1.hand) == 3, "Lich drew that many cards instead"
    assert p1.life == before, "the gain was replaced, so no life arrived"
    assert p2.life == 20, "no life was gained, so nothing triggered"


# --- Round 100: a base P/T set over a whole team ----------------------------


def _jolrael_board(set_pool, hand=("Shock", "Island", "Forest")):
    pool = set_pool("M21")
    jolrael = _nosick(Permanent(card=pool["Jolrael, Mwonvuli Recluse"]))
    friend = _nosick(Permanent(card=pool["Gale Swooper"]))
    p1 = PlayerState(
        name="P1", battlefield=[jolrael, friend],
        hand=[pool[name] for name in hand],
    )
    theirs = Permanent(card=pool["Alpine Watchdog"])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, jolrael, friend, theirs


def test_jolrael_compiles_supported(set_pool):
    """A sweep rather than a target, so it is its own instruction kind: the
    targeted base-P/T handler asks a picker *which* permanent, and this one asks
    the board *which permanents*."""
    program = compile_card_oracle(set_pool("M21")["Jolrael, Mwonvuli Recluse"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    assert ability.instruction.kind == "set_team_base_pt_until_eot"


def test_every_creature_you_control_takes_the_new_base(set_pool):
    game, _p1, jolrael, friend, theirs = _jolrael_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Jolrael, Mwonvuli Recluse", permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert (jolrael.effective_power, jolrael.effective_toughness) == (3, 3)
    assert (friend.effective_power, friend.effective_toughness) == (3, 3)


def test_the_opponents_creatures_are_untouched(set_pool):
    game, _p1, _jolrael, _friend, theirs = _jolrael_board(set_pool)

    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)


def test_x_is_fixed_as_the_ability_resolves(set_pool):
    """CR 608.2: the value is calculated on resolution and does not track the
    hand afterwards. Drawing later in the turn does not grow the team — which is
    exactly what a continuous recompute of the count would have said."""
    game, p1, jolrael, _friend, _theirs = _jolrael_board(set_pool)
    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    p1.hand.append(set_pool("M21")["Mountain"])
    game._recompute_continuous_effects()

    assert (jolrael.effective_power, jolrael.effective_toughness) == (3, 3)


def test_the_base_reverts_at_cleanup(set_pool):
    game, _p1, jolrael, friend, _theirs = _jolrael_board(set_pool)
    game.activate_permanent_ability(0, "Jolrael, Mwonvuli Recluse", permanent_index=0)
    game._settle()

    game.resolve_cleanup_step(0)

    assert (jolrael.effective_power, jolrael.effective_toughness) == (1, 2)
    assert (friend.effective_power, friend.effective_toughness) == (3, 2)


def test_a_team_set_that_names_only_one_characteristic_refuses(set_pool):
    """The handler writes both. "Creatures you control have base power 0" would
    leave toughness tracking whatever else applies, which is a different effect
    and one nothing here performs."""
    from engine.grammar import compile_line

    result = compile_line(
        "Until end of turn, creatures you control have base power 0."
    )

    assert not result.lowered
