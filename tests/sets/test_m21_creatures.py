"""Core Set 2021 (M21) creature cards.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine import Game
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick


# --- Round 23: the may-with-action-cost, and a counted gain ------------------


@pytest.mark.parametrize("name", ["Aven Gagglemaster", "Dire Fleet Warmonger"])
def test_round_23_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_aven_gagglemaster_counts_its_own_wings(set_pool):
    pool = set_pool("M21")
    flyers = [Permanent(card=pool["Concordia Pegasus"]) for _ in range(2)]
    grounded = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(
        name="P1", hand=[pool["Aven Gagglemaster"]],
        battlefield=[*flyers, grounded],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "Aven Gagglemaster")
    assert result.supported, result.details
    # Two Pegasi plus the Gagglemaster itself fly; the cat does not.
    assert p1.life == 26


def test_dire_fleet_warmonger_eats_a_creature_for_the_turn(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    snack = Permanent(card=pool["Pridemalkin"])
    p1 = PlayerState(name="P1", battlefield=[warmonger, snack])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat fires the trigger
    game._settle()
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the 'you may sacrifice' offer should be queued"
    assert game.confirm_optional_pay(0, accept=True)
    # Accepting arms the sacrifice prompt; Warmonger itself is excluded
    # ("another"), so only the cat is a legal pick.
    sac = game.pending_sacrifice_state()
    assert sac is not None and sac["valid_indices"] == [1]
    assert game.confirm_sacrifice(0, [1])
    assert not game.is_on_battlefield(snack)
    assert warmonger.effective_power == 5  # 3/3 printed, +2/+2
    assert game._has_keyword(warmonger, "trample")
    # CR 514.2: the meal wears off.
    game.resolve_cleanup_step(0)
    assert warmonger.effective_power == 3
    assert not game._has_keyword(warmonger, "trample")


def test_dire_fleet_warmonger_with_nothing_to_eat_is_never_asked(set_pool):
    pool = set_pool("M21")
    warmonger = Permanent(card=pool["Dire Fleet Warmonger"])
    p1 = PlayerState(name="P1", battlefield=[warmonger])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game._settle()
    assert not game.pending_choices_of("optional_pay", 0), (
        "with no other creature the cost is unpayable, so the offer is never "
        "made and the pump cannot be taken for free"
    )
    assert warmonger.effective_power == 3


def test_falconer_adept_token_arrives_tapped_and_attacking(set_pool):
    pool = set_pool("M21")
    adept = Permanent(card=pool["Falconer Adept"])
    p1 = PlayerState(name="P1", battlefield=[adept])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    birds = [p for p in p1.battlefield if p.card.name == "Bird Token"]
    assert len(birds) == 1
    assert birds[0].tapped
    bird_index = p1.battlefield.index(birds[0])
    assert bird_index in game.combat_attackers, "the Bird joined the attack"


# --- Round 25: protection grows past colour ----------------------------------


def test_baneslayer_angel_compiles_and_shields_against_its_named_tribes(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Baneslayer Angel"])
    assert program.supported, program.reason
    angel = Permanent(card=pool["Baneslayer Angel"])
    dragon = Permanent(card=pool["Gadrak, the Crown-Scourge"])  # a Dragon
    game = Game(players=[
        PlayerState(name="P1", battlefield=[angel]),
        PlayerState(name="P2", battlefield=[dragon]),
    ])
    assert game._is_protected_from(angel, dragon)
    assert not game._can_block_attacker(dragon, angel)
    # And the colour half of her line still reads: nothing here is a Demon or
    # Dragon spell, so an ordinary removal spell may still target her.
    assert game._can_be_targeted(angel, pool["Shock"])


# --- Round 32: the opponent-scoped board, in both readings --------------------


def test_massacre_wurm_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Massacre Wurm"])
    assert program.supported, program.reason


def test_massacre_wurm_shrinks_only_the_other_side(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])        # 2/2, the caster's
    theirs = Permanent(card=pool["Alpine Watchdog"])      # 2/2, dies to -2/-2
    sturdy = Permanent(card=pool["Concordia Pegasus"])    # 1/3, survives at -1/1
    p1 = PlayerState(name="P1", hand=[pool["Massacre Wurm"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, sturdy])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Massacre Wurm")
    assert result.supported, result.details
    game._settle()

    assert game.is_on_battlefield(mine), "the caster's own board is untouched"
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert not game.is_on_battlefield(theirs), "a 2/2 dies to -2/-2"
    assert (sturdy.effective_power, sturdy.effective_toughness) == (-1, 1)
    # And the death trigger it just caused drains that creature's controller.
    assert p2.life == 18
    assert p1.life == 20


def test_massacre_wurm_drains_the_dead_creatures_controller(set_pool):
    pool = set_pool("M21")
    wurm = Permanent(card=pool["Massacre Wurm"])
    mine = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[wurm, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    # The Wurm's controller losing a creature triggers nothing.
    game._permanent_to_graveyard(p1, mine)
    game.remove_from_battlefield(mine)
    game._settle()
    assert (p1.life, p2.life) == (20, 20)

    game._permanent_to_graveyard(p2, theirs)
    game.remove_from_battlefield(theirs)
    game._settle()
    assert p2.life == 18, "that player is the dead creature's controller"
    assert p1.life == 20


def test_waker_of_waves_static_line_reads_even_though_the_card_does_not(set_pool):
    """Its anthem line derives; the card stays unsupported on its other
    ability ("Discard this card:" — activating from hand, a mechanic the
    engine has no seam for), so it compiles to no instructions at all. The
    behaviour of the scope is pinned with an invented card in
    tests/rules/test_lord_buffs.py, where the table's properties live."""
    from engine.lord_buffs import lord_buff_for
    from engine.oracle import normalize_creature_line

    buff = lord_buff_for(
        normalize_creature_line("Creatures your opponents control get -1/-0.")
    )
    assert buff is not None and buff.filter.controller == "opponent"
    assert (buff.power, buff.toughness) == (-1, 0)
    assert not compile_card_oracle(set_pool("M21")["Waker of Waves"]).supported


# --- Round 31: a counter placement becomes an event ---------------------------


@pytest.mark.parametrize("name", ["Conclave Mentor", "Wildwood Scourge"])
def test_round_31_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_conclave_mentor_raises_a_counter_placed_by_another_card(set_pool):
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])
    veteran = Permanent(card=pool["Tempered Veteran"])
    cat = Permanent(card=pool["Pridemalkin"])  # 2/1 printed
    p1 = PlayerState(name="P1", battlefield=[mentor, veteran, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)

    # Tempered Veteran's expensive ability places one counter; the Mentor
    # makes it two, without either card knowing about the other.
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=1,
        target_player_index=0, target_permanent_index=2,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 2
    assert (cat.effective_power, cat.effective_toughness) == (4, 3)


def test_conclave_mentor_pays_out_its_power_as_it_dies(set_pool):
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])  # 2/2 printed
    p1 = PlayerState(name="P1", battlefield=[mentor])
    game = Game(players=[p1, PlayerState(name="P2")])

    # A counter of its own first: the life gained is the power it had when it
    # died, not the printed number.
    game.place_plus1_counters(mentor, 1)
    assert mentor.effective_power == 4, "its own replacement raised the placement"

    game._permanent_to_graveyard(p1, mentor)
    game.remove_from_battlefield(mentor)
    game._settle()
    assert p1.life == 24


def _living_scourge(game, player, card):
    """A Wildwood Scourge with entry counters on it.

    It is printed 0/0 — an X-cost Hydra — so one placed bare dies to CR 704.5f
    before anything can trigger. Its own placement feeds nothing ("another"),
    which is exactly what the next assertions rely on.
    """
    scourge = Permanent(card=card)
    player.battlefield.append(scourge)
    game.place_plus1_counters(scourge, 2)
    game._settle()
    return scourge


def test_wildwood_scourge_grows_with_its_flock(set_pool):
    pool = set_pool("M21")
    other = Permanent(card=pool["Concordia Pegasus"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[other])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    scourge = _living_scourge(game, p1, pool["Wildwood Scourge"])
    assert scourge.metadata["plus_counters"] == 2, "its own counters feed nothing"

    game.place_plus1_counters(other, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == 3, "a counted ally feeds the Hydra"

    game.place_plus1_counters(theirs, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == 3, "'you control' scopes it"


def test_wildwood_scourge_ignores_another_hydra(set_pool):
    """The excluded subtype is condition payload read off the printed line."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])
    scourge = _living_scourge(game, p1, pool["Wildwood Scourge"])
    hydra = _living_scourge(game, p1, pool["Wildwood Scourge"])

    before = scourge.metadata["plus_counters"]
    game.place_plus1_counters(hydra, 1)
    game._settle()
    assert scourge.metadata["plus_counters"] == before


# --- Round 30: counters as a filter, and as last-known information ------------


@pytest.mark.parametrize("name", ["Pridemalkin", "Basri's Lieutenant"])
def test_round_30_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_pridemalkin_tramples_only_the_counted(set_pool):
    pool = set_pool("M21")
    cat = Permanent(card=pool["Pridemalkin"])
    counted = Permanent(card=pool["Concordia Pegasus"])
    plain = Permanent(card=pool["Alpine Watchdog"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[cat, counted, plain])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    from engine.pt import add_plus1_counters, add_pt_modifier

    add_plus1_counters(counted)
    add_plus1_counters(theirs)
    # A pump is not a counter: the record is what the filter reads.
    add_pt_modifier(plain, 1, 1)
    game._recompute_continuous_effects()

    assert game._has_keyword(counted, "trample")
    assert not game._has_keyword(plain, "trample"), "a pump places no counter"
    assert not game._has_keyword(theirs, "trample"), "'you control' scopes it"
    assert not game._has_keyword(cat, "trample"), "the Cat has no counter itself"


def test_basris_lieutenant_knights_a_counted_death(set_pool):
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    counted = Permanent(card=pool["Concordia Pegasus"])
    plain = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant, counted, plain])
    game = Game(players=[p1, PlayerState(name="P2")])

    from engine.pt import add_plus1_counters

    add_plus1_counters(counted)

    # An uncounted death makes nothing.
    game._permanent_to_graveyard(p1, plain)
    game.remove_from_battlefield(plain)
    game._settle()
    assert not [p for p in p1.battlefield if p.card.name == "Knight Token"]

    # A counted one does — the counter is read as last-known information,
    # after the creature is already in the graveyard.
    game._permanent_to_graveyard(p1, counted)
    game.remove_from_battlefield(counted)
    game._settle()
    knights = [p for p in p1.battlefield if p.card.name == "Knight Token"]
    assert len(knights) == 1
    assert (knights[0].effective_power, knights[0].effective_toughness) == (2, 2)
    assert game._has_keyword(knights[0], "vigilance")


def test_basris_lieutenant_triggers_on_its_own_counted_death(set_pool):
    """"This creature or another creature you control" includes itself, so the
    self-exclusion every other dies-trigger applies must not reach it."""
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant])
    game = Game(players=[p1, PlayerState(name="P2")])

    from engine.pt import add_plus1_counters

    add_plus1_counters(lieutenant)
    game._permanent_to_graveyard(p1, lieutenant)
    game.remove_from_battlefield(lieutenant)
    game._settle()

    assert len([p for p in p1.battlefield if p.card.name == "Knight Token"]) == 1


def test_basris_lieutenant_ignores_an_opponents_counted_death(set_pool):
    pool = set_pool("M21")
    lieutenant = Permanent(card=pool["Basri's Lieutenant"])
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[lieutenant])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    from engine.pt import add_plus1_counters

    add_plus1_counters(theirs)
    game._permanent_to_graveyard(p2, theirs)
    game.remove_from_battlefield(theirs)
    game._settle()

    assert not [p for p in p1.battlefield if p.card.name == "Knight Token"]


# --- Round 29: the conditional-static family ----------------------------------


@pytest.mark.parametrize(
    "name",
    ["Predatory Wurm", "Gnarled Sage", "Sigiled Contender", "Tome Anima"],
)
def test_round_29_conditional_static_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_predatory_wurm_grows_under_its_own_garruk_only(set_pool):
    pool = set_pool("M21")
    wurm = Permanent(card=pool["Predatory Wurm"])  # 4/4 printed
    garruk = Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[wurm])
    p2 = PlayerState(name="P2", battlefield=[garruk])
    game = Game(players=[p1, p2])

    game._recompute_continuous_effects()
    assert wurm.effective_power == 4, "an opponent's Garruk is not 'you control'"

    p1.battlefield.append(
        Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 4})
    )
    game._recompute_continuous_effects()
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 6)


def test_gnarled_sage_stands_taller_after_the_second_draw(set_pool):
    pool = set_pool("M21")
    sage = Permanent(card=pool["Gnarled Sage"])  # 4/4 printed
    p1 = PlayerState(name="P1", battlefield=[sage], library=[pool["Island"]] * 3)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.begin_turn_bookkeeping(0)

    game._recompute_continuous_effects()
    assert sage.effective_toughness == 4
    assert not game._has_keyword(sage, "vigilance")

    game._draw_with_replacements(p1, 2)
    game._settle()
    assert sage.effective_toughness == 6
    assert game._has_keyword(sage, "vigilance")


def test_sigiled_contender_lifelinks_only_while_counted(set_pool):
    pool = set_pool("M21")
    contender = Permanent(card=pool["Sigiled Contender"])  # 3/3 printed
    game = Game(players=[
        PlayerState(name="P1", battlefield=[contender]), PlayerState(name="P2"),
    ])
    game._recompute_continuous_effects()
    assert not game._has_keyword(contender, "lifelink")

    from engine.pt import add_plus1_counters

    add_plus1_counters(contender)
    game._recompute_continuous_effects()
    assert game._has_keyword(contender, "lifelink")


def test_tome_anima_slips_past_blockers_after_two_draws(set_pool):
    pool = set_pool("M21")
    anima = Permanent(card=pool["Tome Anima"])
    blocker = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[anima], library=[pool["Island"]] * 3)
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    assert game._can_block_attacker(blocker, anima), "no draws yet: blockable"
    game._draw_with_replacements(p1, 2)
    game._settle()
    assert not game._can_block_attacker(blocker, anima)
    assert game.is_unblockable(anima), "the UI tag tracks the same condition"


# --- Round 28: cast-type narrowing, filtered intervening-if, second draw ------


@pytest.mark.parametrize(
    "name", ["Spellgorger Weird", "Turret Ogre", "Mystic Skyfish"],
)
def test_round_28_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_spellgorger_weird_counts_only_noncreature_spells(set_pool):
    pool = set_pool("M21")
    weird = Permanent(card=pool["Spellgorger Weird"])
    p1 = PlayerState(
        name="P1", battlefield=[weird],
        hand=[pool["Shock"], pool["Concordia Pegasus"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert result.supported, result.details
    game._settle()
    assert weird.metadata.get("plus_counters", 0) == 1, "an instant counts"

    result = game.cast_from_hand(0, "Concordia Pegasus")
    assert result.supported, result.details
    game._settle()
    assert weird.metadata.get("plus_counters", 0) == 1, "a creature spell does not"


def test_turret_ogre_needs_another_big_creature(set_pool):
    pool = set_pool("M21")
    # Alone, his own power 4 does not satisfy "another creature" (CR 109.5).
    p1 = PlayerState(name="P1", hand=[pool["Turret Ogre"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game._settle()
    assert p2.life == 20, "no other big creature, no damage"

    # With a 6/6 already out, the trigger's condition holds.
    big = Permanent(card=pool["Elder Gargaroth"])
    q1 = PlayerState(name="Q1", hand=[pool["Turret Ogre"]], battlefield=[big])
    q2 = PlayerState(name="Q2")
    game2 = Game(players=[q1, q2])
    result = game2.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game2._settle()
    assert q2.life == 18


def test_turret_ogre_counts_a_pumped_small_creature(set_pool):
    """The bound reads the layer-computed power, not the printed one."""
    pool = set_pool("M21")
    small = Permanent(card=pool["Concordia Pegasus"])  # 1/3 printed
    from engine.pt import add_pt_modifier

    add_pt_modifier(small, 3, 0)  # 4/3 while modified
    p1 = PlayerState(name="P1", hand=[pool["Turret Ogre"]], battlefield=[small])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Turret Ogre")
    assert result.supported, result.details
    game._settle()
    assert p2.life == 18


def test_mystic_skyfish_lifts_off_on_the_second_draw(set_pool):
    pool = set_pool("M21")
    skyfish = Permanent(card=pool["Mystic Skyfish"])
    p1 = PlayerState(
        name="P1", battlefield=[skyfish], library=[pool["Island"]] * 4,
    )
    p2 = PlayerState(name="P2", library=[pool["Island"]] * 4)
    game = Game(players=[p1, p2])
    game.begin_turn_bookkeeping(0)

    game._draw_with_replacements(p1, 1)
    game._settle()
    assert not game._has_keyword(skyfish, "flying"), "one draw is not two"

    game._draw_with_replacements(p1, 1)
    game._settle()
    assert game._has_keyword(skyfish, "flying"), "the second draw lifts it"

    # Once per turn: a third draw does not queue a second trigger.
    fired = len(game.second_draw_fired_this_turn)
    game._draw_with_replacements(p1, 1)
    game._settle()
    assert len(game.second_draw_fired_this_turn) == fired

    # CR 514.2: the grant wears off at cleanup, and the next turn's second
    # draw fires afresh.
    game.resolve_cleanup_step(0)
    assert not game._has_keyword(skyfish, "flying")
    game.begin_turn_bookkeeping(1)
    game._draw_with_replacements(p2, 2)
    game._settle()
    assert not game._has_keyword(skyfish, "flying"), (
        "an opponent's second draw is not 'you draw'"
    )


# --- Round 27: modal triggered abilities --------------------------------------


@pytest.mark.parametrize("name", ["Trufflesnout", "Elder Gargaroth"])
def test_round_27_modal_trigger_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason
    trig = next(t for t in program.triggered_abilities if t.supported)
    assert trig.instruction is not None and trig.instruction.kind == "choose_one"
    assert program.modes == (), "a trigger's modes are not cast-time modes"


def test_trufflesnout_default_takes_the_first_printed_mode(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 1, "mode 0: the counter"
    assert (snout.effective_power, snout.effective_toughness) == (3, 3)
    assert p1.life == 20, "the life mode was not also taken"


def test_trufflesnout_interactive_controller_may_take_the_life_instead(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Trufflesnout"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    pending = game.pending_choices_of("mode_choice", 0)
    assert pending and pending[0].data["labels"] == [
        "Put a +1/+1 counter on this creature", "You gain 4 life",
    ]
    assert not game.resolve_pending_choice("mode_choice", 0, mode_index=5), (
        "an index outside the printed list is refused and the prompt stays owed"
    )
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    assert p1.life == 24
    snout = next(p for p in p1.battlefield if p.card.name == "Trufflesnout")
    assert snout.metadata.get("plus_counters", 0) == 0, "the counter mode was declined"


def test_elder_gargaroth_triggers_on_attack_and_on_block(set_pool):
    pool = set_pool("M21")
    gargaroth = Permanent(card=pool["Elder Gargaroth"])
    p1 = PlayerState(name="P1", battlefield=[gargaroth])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game._settle()
    beasts = [p for p in p1.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "attack half: default mode made the Beast"

    # The block half, from the defender's side of a fresh game.
    attacker = Permanent(card=pool["Pridemalkin"])
    blocker = Permanent(card=pool["Elder Gargaroth"])
    ap = PlayerState(name="AP", battlefield=[attacker])
    dp = PlayerState(name="DP", battlefield=[blocker])
    game2 = Game(players=[ap, dp])
    game2.start_turn(0)
    game2._close_current_priority_step()
    game2.advance_combat_phase()  # beginning_of_combat
    game2.advance_combat_phase()  # declare_attackers
    ok, msg = game2.declare_attackers(0, [0])
    assert ok, msg
    game2.advance_combat_phase()  # declare_blockers
    ok, msg = game2.declare_blockers(1, {0: 0})
    assert ok, msg
    game2._settle()
    beasts = [p for p in dp.battlefield if p.card.name == "Beast Token"]
    assert len(beasts) == 1, "block half: the union condition fires here too"


def test_lilianas_steward_feeds_herself_to_empty_an_opposing_hand(set_pool):
    pool = set_pool("M21")
    steward = Permanent(card=pool["Liliana's Steward"])
    p1 = PlayerState(name="P1", battlefield=[steward])
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, p2])
    game.start_turn(0)  # "Activate only as a sorcery" needs the main phase

    result = game.activate_permanent_ability(
        0, "Liliana's Steward", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(steward), "the sacrifice was a cost"
    game.auto_resolve_pending_choices()
    assert len(p2.hand) == 1, "the targeted opponent discarded one card"


def test_lilianas_steward_cannot_point_at_her_own_controller(set_pool):
    pool = set_pool("M21")
    program = compile_card_oracle(pool["Liliana's Steward"])
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player", "opponents_only": True}


def test_chandras_magmutt_pings_a_face_or_a_walker(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    assert compile_card_oracle(magmutt.card).supported
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    p1 = PlayerState(name="P1", battlefield=[magmutt])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0, target_player_index=1,
    )
    assert result.supported, result.details
    assert p2.life == 19, "the player face is a legal target"

    magmutt.tapped = False
    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert walker.metadata["loyalty_counters"] == 2, "damage strips loyalty (CR 306.8)"
    assert p2.life == 19, "the walker soaked it, not the player"


def test_chandras_magmutt_never_offers_a_creature(set_pool):
    pool = set_pool("M21")
    magmutt = Permanent(card=pool["Chandra's Magmutt"])
    bear = Permanent(card=pool["Pridemalkin"])
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    game = Game(players=[
        PlayerState(name="P1", battlefield=[magmutt]),
        PlayerState(name="P2", battlefield=[bear, walker]),
    ])
    program = compile_card_oracle(magmutt.card)
    from engine.targeting import derive_activation_spec

    ability = next(a for a in program.activated_abilities if a.supported)
    spec = derive_activation_spec(ability)
    assert spec == {"kind": "player_or_planeswalker"}
    offered = game._enumerate_targets(
        0, magmutt.card, spec, for_cast=False,
        ability_instruction=ability.instruction, source_permanent=magmutt,
    )
    names = {t.get("name") for t in offered if t["kind"] == "permanent"}
    assert names == {"Basri Ket"}, "planeswalkers yes, creatures no"
    assert {t["seat"] for t in offered if t["kind"] == "player"} == {0, 1}


def test_tempered_veteran_tends_only_an_already_counted_creature(set_pool):
    pool = set_pool("M21")
    veteran = Permanent(card=pool["Tempered Veteran"])
    cat = Permanent(card=pool["Pridemalkin"])  # 2/1, no counter yet
    p1 = PlayerState(name="P1", battlefield=[veteran, cat])
    game = Game(players=[p1, PlayerState(name="P2")])
    program = compile_card_oracle(veteran.card)
    assert program.supported, program.reason

    from engine.targeting import derive_activation_spec

    cheap = program.activated_abilities[0]  # {W}, {T}: counter on a counted creature
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert offered == [], "with no counter anywhere, the cheap ability has no target"

    # The expensive ability seeds the counter; the cheap one can then grow it.
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 1, "the counter is recorded, not just P/T"
    assert (cat.effective_power, cat.effective_toughness) == (3, 2)

    veteran.tapped = False
    offered = game._enumerate_targets(
        0, veteran.card, derive_activation_spec(cheap), for_cast=False,
        ability_instruction=cheap.instruction, source_permanent=veteran,
    )
    assert [t.get("name") for t in offered] == ["Pridemalkin"]
    result = game.activate_permanent_ability(
        0, "Tempered Veteran", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert cat.metadata["plus_counters"] == 2
    assert (cat.effective_power, cat.effective_toughness) == (4, 3)


# --- The subject-filtered trigger: "a creature you control with deathtouch" --


@pytest.mark.parametrize(
    "name", ["Hooded Blightfang", "Snarespinner", "Gloom Sower"],
)
def test_round_34_subject_filter_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _attack(game, seat, attacker_indices, blocks=None):
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(seat, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    if blocks is not None:
        ok, msg = game.declare_blockers(1 - seat, blocks)
        assert ok, msg
    game._settle()


def test_hooded_blightfang_drains_once_for_each_deathtouch_attacker(set_pool):
    """Its own deathtouch counts it among the creatures it watches; the
    Watchdog attacking beside it does not."""
    pool = set_pool("M21")
    fang = _nosick(Permanent(card=pool["Hooded Blightfang"]))
    plain = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[fang, plain])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    _attack(game, 0, [0, 1])

    assert (p1.life, p2.life) == (21, 19), "one drain, not two and not none"


def test_hooded_blightfang_ignores_an_opponents_deathtouch_attacker(set_pool):
    """"A creature **you control**" is the ability's controller (CR 109.5), and
    the scope lives in the trigger's own noun phrase rather than in the event."""
    pool = set_pool("M21")
    fang = Permanent(card=pool["Hooded Blightfang"])
    theirs = _nosick(Permanent(card=pool["Ornery Dilophosaur"]))  # deathtouch
    p1 = PlayerState(name="P1", battlefield=[fang])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    _attack(game, 1, [0])

    assert (p1.life, p2.life) == (20, 20)


def test_hooded_blightfang_destroys_a_walker_its_deathtouch_creature_damaged(set_pool):
    """Any damage, not only combat damage — the emit sits on the one path every
    damage-to-a-permanent caller runs through, like lifelink and deathtouch."""
    pool = set_pool("M21")
    fang = _nosick(Permanent(card=pool["Hooded Blightfang"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[fang])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(walker, 1, source=fang)
    game._settle()

    assert not game.is_on_battlefield(walker), "1 damage, then destroyed"


def test_hooded_blightfang_leaves_a_walker_alone_without_deathtouch(set_pool):
    pool = set_pool("M21")
    fang = Permanent(card=pool["Hooded Blightfang"])
    plain = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[fang, plain])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])

    game._mark_damage_on_permanent(walker, 1, source=plain)
    game._settle()

    assert game.is_on_battlefield(walker)
    assert walker.metadata["loyalty_counters"] == 3, "damage still removed loyalty"


def test_snarespinner_grows_only_against_a_flier(set_pool):
    """The rider used to be dropped: the condition matched "whenever this
    creature blocks" and "a creature with flying" went unread, so the Spider
    would have pumped against anything it blocked."""
    pool = set_pool("M21")
    base = Permanent(card=pool["Snarespinner"]).effective_power

    spider = Permanent(card=pool["Snarespinner"])
    ground = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    attackers = PlayerState(name="AP", battlefield=[ground])
    game = Game(players=[attackers, PlayerState(name="DP", battlefield=[spider])])
    _attack(game, 0, [0], blocks={0: 0})
    assert spider.effective_power == base, "a ground attacker gives it nothing"

    spider2 = Permanent(card=pool["Snarespinner"])
    flier = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    game2 = Game(players=[
        PlayerState(name="AP", battlefield=[flier]),
        PlayerState(name="DP", battlefield=[spider2]),
    ])
    _attack(game2, 0, [0], blocks={0: 0})
    assert spider2.effective_power == base + 2


def test_gloom_sower_drains_once_per_blocker(set_pool):
    """CR 509.3d: "becomes blocked **by a creature**" triggers once for each
    creature that blocks it, where the bare wording would fire once."""
    pool = set_pool("M21")
    sower = _nosick(Permanent(card=pool["Gloom Sower"]))
    first = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    second = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(name="P1", battlefield=[sower])
    p2 = PlayerState(name="P2", battlefield=[first, second])
    game = Game(players=[p1, p2])

    _attack(game, 0, [0], blocks={0: 0, 1: 0})

    assert (p1.life, p2.life) == (24, 16), "two blockers, 2 life each way apiece"


# --- Costs go down as well as up (CR 601.2f / 118.7) ------------------------


@pytest.mark.parametrize(
    "name", ["Vryn Wingmare", "Watcher of the Spheres", "Stormwing Entity"],
)
def test_round_35_cost_modifier_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _casting_game(set_pool, battlefield, hand, **mana):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=pool[n]) for n in battlefield],
        hand=[pool[n] for n in hand],
        library=[pool["Island"]] * 6,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    p1.mana_pool = {sym: mana.get(sym, 0) for sym in ("W", "U", "B", "R", "G", "C")}
    return game, p1


def test_watcher_of_the_spheres_discounts_only_flying_creature_spells(set_pool):
    """"Creature spells with flying **you cast**": three narrowings, and each
    one has to hold or the discount is a different card's."""
    # Concordia Pegasus is {1}{W} with flying — one white mana is enough.
    game, _ = _casting_game(set_pool, ["Watcher of the Spheres"], ["Concordia Pegasus"], W=1)
    assert game.queue_from_hand(0, "Concordia Pegasus").supported

    # Without the Watcher, the same mana is not.
    bare, _ = _casting_game(set_pool, [], ["Concordia Pegasus"], W=1)
    assert not bare.queue_from_hand(0, "Concordia Pegasus").supported

    # Alpine Watchdog is {1}{W} without flying, so the keyword narrowing bites.
    grounded, _ = _casting_game(set_pool, ["Watcher of the Spheres"], ["Alpine Watchdog"], W=1)
    assert not grounded.queue_from_hand(0, "Alpine Watchdog").supported


def test_watcher_of_the_spheres_does_not_discount_an_opponents_spell(set_pool):
    """"You cast" is the Watcher's controller (CR 109.5) — the discount does not
    cross the table, which is the one narrowing a board-wide scan would lose."""
    pool = set_pool("M21")
    watcher = Permanent(card=pool["Watcher of the Spheres"])
    p1 = PlayerState(name="P1", battlefield=[watcher])
    p2 = PlayerState(
        name="P2", hand=[pool["Concordia Pegasus"]], library=[pool["Island"]] * 4
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    p2.mana_pool = {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    assert not game.queue_from_hand(1, "Concordia Pegasus").supported


def test_vryn_wingmare_taxes_noncreature_spells_only(set_pool):
    """"Non" is the printed negation of the same word: Shock pays {1} more and
    a creature spell pays nothing more."""
    game, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Shock"], R=1)
    assert not game.queue_from_hand(0, "Shock", target_player_index=1).supported

    paid, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Shock"], R=1, C=1)
    assert paid.queue_from_hand(0, "Shock", target_player_index=1).supported

    creature, _ = _casting_game(set_pool, ["Vryn Wingmare"], ["Alpine Watchdog"], W=1, C=1)
    assert creature.queue_from_hand(0, "Alpine Watchdog").supported


def test_stormwing_entity_discounts_itself_after_an_instant(set_pool):
    """{3}{U}{U} less {2}{U} is {1}{U} — the coloured half of the reduction
    takes a blue pip and the generic half takes two generic (CR 118.7a/c)."""
    # {1}{U} is not enough on its own.
    game, _ = _casting_game(set_pool, [], ["Stormwing Entity"], U=1, C=1)
    assert not game.queue_from_hand(0, "Stormwing Entity").supported

    # After an instant, it is.
    discounted, player = _casting_game(
        set_pool, [], ["Shock", "Stormwing Entity"], U=1, C=1, R=1
    )
    assert discounted.queue_from_hand(0, "Shock", target_player_index=1).supported
    discounted._settle()
    assert [c.name for c in player.spells_cast_this_turn] == ["Shock"]
    assert discounted.queue_from_hand(0, "Stormwing Entity").supported


# --- Fight (CR 701.14), and the damage a creature reflects -------------------


def test_brash_taunter_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Brash Taunter"])
    assert program.supported, program.reason


def test_brash_taunter_fights_and_reflects_what_it_takes(set_pool):
    """Its two lines meet. The fight deals both halves (CR 701.14a), the
    Taunter survives its six because it is indestructible, and the "whenever
    this creature is dealt damage" trigger sends that six at the opponent."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])       # 1/1 indestructible
    gargaroth = Permanent(card=pool["Elder Gargaroth"])   # 6/6
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2", battlefield=[gargaroth])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(
        0, "Brash Taunter", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert gargaroth.damage_marked == 1, "the Taunter's own power"
    assert taunter.damage_marked == 6
    assert game.is_on_battlefield(taunter), "indestructible"
    assert p2.life == 14, "the six it took, reflected"


def test_a_dealt_damage_trigger_is_not_gated_on_surviving(set_pool):
    """"Whenever this creature is dealt damage" triggers on the damage
    (CR 603.2); whether the creature dies is a state-based action that has not
    run yet. The guard that stood here read a rule that does not exist — it was
    harmless for a card whose trigger puts a counter on a dying creature, and
    wrong for one that is indestructible."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    from engine.handlers._common import apply_damage_to_creature

    # Nine damage to a 1/1: lethal by the numbers, and it still reflects.
    apply_damage_to_creature(game, taunter, 9, source=None)
    game._settle()

    assert p2.life == 11


def test_the_fight_needs_two_creatures_or_neither_deals(set_pool):
    """CR 701.14b, and the reason this is one instruction rather than two
    damage steps: written as two, the first would resolve and the second would
    not."""
    pool = set_pool("M21")
    taunter = Permanent(card=pool["Brash Taunter"])
    p1 = PlayerState(name="P1", battlefield=[taunter])
    p2 = PlayerState(name="P2")                     # nothing to fight
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Brash Taunter", target_player_index=1)
    game._settle()

    assert taunter.damage_marked == 0
    assert p2.life == 20
    assert any("neither deals damage" in line for line in game.log)


# --- What a sacrificed source is still worth ---------------------------------


def test_heartfire_immolator_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Heartfire Immolator"])
    assert program.supported, program.reason


def test_heartfire_immolator_deals_the_power_it_had_when_it_was_sacrificed(set_pool):
    """The source pays for its own ability by being sacrificed, so by
    resolution it is in a graveyard and its power is last-known information
    (CR 608.2). Prowess is what makes the distinction observable: a 2/1 that
    saw a noncreature spell this turn deals **three**, not two."""
    pool = set_pool("M21")
    immolator = Permanent(card=pool["Heartfire Immolator"])   # 2/1, prowess
    victim = Permanent(card=pool["Elder Gargaroth"])          # 6/6
    p1 = PlayerState(
        name="P1", battlefield=[immolator], hand=[pool["Shock"]],
        library=[pool["Mountain"]] * 4,
    )
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()
    assert immolator.effective_power == 3, "prowess"

    result = game.activate_permanent_ability(
        0, "Heartfire Immolator", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(immolator), "sacrificed to pay the cost"
    assert victim.damage_marked == 3, "the power it had, not the power it was printed with"


def test_heartfire_immolator_can_aim_at_a_planeswalker(set_pool):
    """"Target creature **or planeswalker**" — the union is the filter, and it
    is enforced at resolution as well as offered by the picker."""
    pool = set_pool("M21")
    immolator = Permanent(card=pool["Heartfire Immolator"])
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[immolator])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(
        0, "Heartfire Immolator", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert walker.metadata["loyalty_counters"] == 2, "damage to a walker is loyalty (CR 120.3c)"


# --- The sacrifice-seam round ------------------------------------------------


def test_havoc_jester_compiles_supported(set_pool):
    """"Whenever you sacrifice a permanent, this creature deals 1 damage to any
    target." The condition is the pool's first trigger on a *keyword action*
    rather than on a zone change or a step, and it is announced from
    ``Game.sacrifice_permanent`` — which is why it needed no fire site of its
    own: there are thirteen sacrifices in this engine and one transition."""
    assert compile_card_oracle(set_pool("M21")["Havoc Jester"]).supported


def test_havoc_jester_fires_when_a_cost_is_paid_by_sacrificing(set_pool):
    """The sacrifice that trips it is a *cost*, not an effect — Witch's Cauldron
    eats a creature to pay for its own ability. The Jester's ping is a separate
    ability on the stack, so both happen."""
    pool = set_pool("M21")
    jester = _nosick(Permanent(card=pool["Havoc Jester"]))
    cauldron = _nosick(Permanent(card=pool["Witch's Cauldron"]))
    food = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[jester, cauldron, food],
                     library=[pool["Swamp"]] * 4)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    result = game.activate_permanent_ability(0, "Witch's Cauldron")
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(food), "eaten to pay the cost"
    assert p2.life == 19, "the Jester pinged for the sacrifice"


def test_havoc_jester_stays_silent_when_an_opponent_sacrifices(set_pool):
    """"Whenever **you** sacrifice" is the Jester's controller (CR 109.5). The
    event is announced once, game-wide, carrying the seat that sacrificed — the
    narrowing is the trigger's own word, not a second announcement."""
    pool = set_pool("M21")
    jester = _nosick(Permanent(card=pool["Havoc Jester"]))
    cauldron = _nosick(Permanent(card=pool["Witch's Cauldron"]))
    food = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    p1 = PlayerState(name="P1", battlefield=[jester])
    p2 = PlayerState(name="P2", battlefield=[cauldron, food],
                     library=[pool["Swamp"]] * 4)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    game.activate_permanent_ability(1, "Witch's Cauldron")
    game._settle()

    assert not game.is_on_battlefield(food), "the opponent's own creature went"
    assert (p1.life, p2.life) == (20, 21), (
        "no ping: the opponent sacrificed, and they gained the Cauldron's life"
    )


# --- The additional-cost round ----------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Goremand",              # sacrifice cost // ETB: each opponent sacrifices
        "Sparkhunter Masticore", # discard cost // protection from planeswalkers
    ],
)
def test_additional_cost_creatures_compile_supported(set_pool, name):
    """Both were reported "creature text too complex" naming the *cost* line,
    which is the first line each prints — so nothing below it was ever read.
    A cost is not an effect, and the compiler now hands the line to
    engine/cast_costs.py instead of looking for an instruction in it."""
    assert compile_card_oracle(set_pool("M21")[name]).supported


def test_goremand_makes_each_opponent_sacrifice_when_it_enters(set_pool):
    """"When this creature enters, each opponent sacrifices a creature."

    The same prompt the controller-scoped form arms, owed by a different set of
    seats — one instruction with the payer named, never a second kind, because
    CR 701.21a already says the sacrificing player chooses.
    """
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Alpine Watchdog"])],
                     hand=[pool["Goremand"]])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool["Concordia Pegasus"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Goremand")
    game._settle()

    assert [p.card.name for p in p2.battlefield] == [], "the opponent's creature went"
    assert [p.card.name for p in p1.battlefield] == ["Goremand"], (
        "and the Demon is not its own opponent (CR 102.3) — only the cost took one of ours"
    )


# --- The trigger-timing round -----------------------------------------------


def test_deathbloom_thallid_leaves_a_saproling_behind(set_pool):
    """"When this creature dies, create a 1/1 green Saproling creature token."

    One of four M21 cards whose dies-trigger had no fire site: the loop that put
    them on the stack was keyed by instruction kind, one branch per card that
    had needed one, so ``create_token`` fell through.
    """
    pool = set_pool("M21")
    thallid = Permanent(card=pool["Deathbloom Thallid"])
    p1 = PlayerState(name="P1", battlefield=[thallid])
    p2 = PlayerState(name="P2", hand=[pool["Shock"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    while game.is_on_battlefield(thallid) and p2.hand:
        game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)
        game._settle()

    assert [p.card.name for p in p1.battlefield] == ["Saproling Token"]


def test_conclave_mentor_gains_the_life_it_had(set_pool):
    """"When this creature dies, you gain life equal to its power." The power is
    read as the permanent leaves (CR 603.10), which this fire site was already
    doing — it is the only dies-shape it *did* get right, and the reason the
    general case looked covered."""
    pool = set_pool("M21")
    mentor = Permanent(card=pool["Conclave Mentor"])   # 2/2
    p1 = PlayerState(name="P1", battlefield=[mentor], life=20)
    p2 = PlayerState(name="P2", hand=[pool["Shock"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1

    while game.is_on_battlefield(mentor) and p2.hand:
        game.cast_from_hand(1, "Shock", target_player_index=0, target_permanent_index=0)
        game._settle()

    assert p1.life == 22


# --- Round 55: a where-clause that counts a history --------------------------


def _death_board(set_pool):
    pool = set_pool("M21")
    p1, p2 = PlayerState(name="P1"), PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    p1.library = [pool["Swamp"]] * 12
    return game, p1, p2, pool


def test_lilianas_standard_bearer_draws_for_each_creature_that_died(set_pool):
    """"…where X is the number of creatures that **died under your control**
    this turn." The count is a history, so it is read off the per-seat tracker
    rather than by scanning a zone — the creatures it counts are exactly the
    ones no longer on the battlefield, and the bare filter "creature" would
    count the survivors instead."""
    game, p1, p2, pool = _death_board(set_pool)
    for owner in (p1, p1, p1):
        perm = Permanent(card=pool["Alpine Watchdog"])
        owner.battlefield.append(perm)
        game._permanent_to_graveyard(owner, perm)
    p1.hand = [pool["Liliana's Standard Bearer"]]

    game.queue_from_hand(0, "Liliana's Standard Bearer")
    game._settle()

    assert len([c for c in p1.hand if c.name == "Swamp"]) == 3


def test_the_death_count_is_the_controllers_own(set_pool):
    """The control, and what the tracker exists for: a creature that died under
    the *opponent's* control is not counted, which a game-wide tally could not
    tell apart."""
    game, p1, p2, pool = _death_board(set_pool)
    for owner in (p1, p2, p2):
        perm = Permanent(card=pool["Alpine Watchdog"])
        owner.battlefield.append(perm)
        game._permanent_to_graveyard(owner, perm)
    p1.hand = [pool["Liliana's Standard Bearer"]]

    game.queue_from_hand(0, "Liliana's Standard Bearer")
    game._settle()

    assert len([c for c in p1.hand if c.name == "Swamp"]) == 1


# --- Round 57: a damage event that knows who dealt it -----------------------


def _pyreling_board(set_pool):
    pool = set_pool("M21")
    pyreling = Permanent(card=pool["Chandra's Pyreling"])
    p1 = PlayerState(name="P1", battlefield=[pyreling], hand=[pool["Shock"]])
    p2 = PlayerState(name="P2", hand=[pool["Shock"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2, pyreling


def test_chandras_pyreling_grows_when_your_spell_burns_an_opponent(set_pool):
    """"Whenever a source you control deals noncombat damage to an opponent…"
    The trigger reads the *source's* controller (CR 109.5), which is what a
    damage event could not answer until it carried a seat: a Shock arrives at
    the damage paths as its printed card."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()

    assert pyreling.effective_power == 2  # 1/3 printed, +1/+0
    assert game._has_keyword(pyreling, "double strike")


def test_chandras_pyreling_is_silent_when_the_opponent_burns_you(set_pool):
    """The control the seat exists for. Reading the *damaged* player's seat
    instead of the source's would fire on exactly this."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)
    game.active_player_index = 1

    game.cast_from_hand(1, "Shock", target_player_index=0)
    game._settle()

    assert pyreling.effective_power == 1
    assert not game._has_keyword(pyreling, "double strike")


def test_chandras_pyreling_is_silent_on_combat_damage(set_pool):
    """"Noncombat" is a property of the fire site rather than a flag: the combat
    damage step reaches players by its own path, because it applies prevention
    where the event is recorded. Attacking with the Pyreling must not pump it."""
    game, p1, p2, pyreling = _pyreling_board(set_pool)
    game.start_turn(0)
    _nosick(pyreling)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    game.advance_combat_phase()  # combat_damage
    game._settle()

    assert p2.life == 19, "the 1/3 connected"
    assert pyreling.effective_power == 1
    assert not game._has_keyword(pyreling, "double strike")


# --- Round 58: the condition that parsed on both sides and fired nowhere ----


def _draw_trigger_board(set_pool):
    pool = set_pool("M21")
    oak = Permanent(card=pool["Burlfist Oak"])
    coatl = Permanent(card=pool["Lorescale Coatl"])
    p1 = PlayerState(
        name="P1", battlefield=[oak, coatl], library=[pool["Island"]] * 8
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1, oak, coatl, pool


def test_a_draw_trigger_fires_at_all(set_pool):
    """Two cards that compiled supported, entered play and did nothing.

    "Whenever you draw a card" parsed in the oracle table *and* in the grammar's
    phrase table and had no dispatcher anywhere, so both cards produced a real
    instruction under a condition the game never announced. The support report
    counted them as working the whole time — the compiler can see that a
    condition parsed and cannot see whether anything says it happened."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)

    game._draw_with_replacements(p1, 1)
    game._settle()

    assert (oak.effective_power, oak.effective_toughness) == (4, 5)
    assert coatl.metadata["plus_counters"] == 1


def test_a_draw_trigger_fires_once_per_card(set_pool):
    """CR 121.2: drawing N cards is N individual draws, so the sweep counts
    rather than flags — which is the whole difference between this and the
    "your second card each turn" trigger it sits beside."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)

    game._draw_with_replacements(p1, 3)
    game._settle()

    assert coatl.metadata["plus_counters"] == 3
    assert oak.effective_power == 2 + 2 * 3


def test_an_opponents_draw_does_not_fire_your_trigger(set_pool):
    """"Whenever **you** draw a card" — the seat is the drawing player's, and
    the sweep is game-wide, so this is the narrowing that has to hold."""
    game, p1, oak, coatl, pool = _draw_trigger_board(set_pool)
    p2 = game.players[1]
    p2.library = [pool["Island"]] * 4

    game._draw_with_replacements(p2, 2)
    game._settle()

    assert coatl.metadata.get("plus_counters", 0) == 0
    assert oak.effective_power == 2


# --- Round 59: how many creatures attacked ----------------------------------


def _attack_board(set_pool, names):
    pool = set_pool("M21")
    perms = [_nosick(Permanent(card=pool[name])) for name in names]
    p1 = PlayerState(name="P1", battlefield=perms, library=[pool["Island"]] * 5)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    return game, p1, perms


def test_tide_skimmer_counts_the_fliers_in_the_declaration(set_pool):
    """"Whenever you attack with two or more creatures with flying, draw a
    card." The count and the noun phrase are both payload the compiler read off
    the printed line, so the filter here is about the *declaration* — which is
    the only announcement that can answer how many creatures attacked."""
    game, p1, perms = _attack_board(set_pool, ["Tide Skimmer", "Gale Swooper"])

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game._settle()

    assert len(p1.hand) == 1


def test_tide_skimmer_does_not_count_a_grounded_attacker(set_pool):
    """The narrowing. Dropping "with flying" would make the Skimmer a strictly
    better card, which is the one direction a trigger must never go."""
    game, p1, perms = _attack_board(set_pool, ["Tide Skimmer", "Alpine Watchdog"])

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game._settle()

    assert p1.hand == []


def test_makeshift_battalion_needs_itself_and_two_others(set_pool):
    """"Battalion — Whenever this creature and at least two other creatures
    attack…" The ability word is CR 207.2c flavour and is dropped before either
    front end reads the line; what is left counts the *others*, so three
    attackers are needed and the Battalion must be one of them."""
    game, p1, perms = _attack_board(
        set_pool, ["Makeshift Battalion", "Alpine Watchdog", "Gale Swooper"]
    )

    ok, msg = game.declare_attackers(0, [0, 1, 2])
    assert ok, msg
    game._settle()

    assert perms[0].metadata["plus_counters"] == 1


def test_makeshift_battalion_is_silent_with_only_one_other(set_pool):
    game, p1, perms = _attack_board(
        set_pool, ["Makeshift Battalion", "Alpine Watchdog"]
    )

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game._settle()

    assert perms[0].metadata.get("plus_counters", 0) == 0


def test_makeshift_battalion_must_be_attacking_itself(set_pool):
    """"**This creature** and at least two other creatures" — three attackers
    are not enough if the Battalion stayed home. Membership is by identity, so
    a second Battalion in the same declaration would not stand in for it."""
    game, p1, perms = _attack_board(
        set_pool,
        ["Makeshift Battalion", "Alpine Watchdog", "Gale Swooper", "Tide Skimmer"],
    )

    ok, msg = game.declare_attackers(0, [1, 2, 3])
    assert ok, msg
    game._settle()

    assert perms[0].metadata.get("plus_counters", 0) == 0


# --- Round 60: an optional cost that is not generic -------------------------


def _devotee_board(set_pool, lands):
    pool = set_pool("M21")
    devotee = Permanent(card=pool["Liliana's Devotee"])
    p1 = PlayerState(
        name="P1",
        battlefield=[devotee] + [Permanent(card=pool[name]) for name in lands],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)
    victim = Permanent(card=pool["Alpine Watchdog"])
    p1.battlefield.append(victim)
    game._permanent_to_graveyard(p1, victim)
    return game, p1, devotee


def test_lilianas_devotee_offers_a_coloured_cost(set_pool):
    """"At the beginning of your end step, if a creature died this turn, you may
    pay {1}{B}. If you do, create a 2/2 black Zombie creature token."

    The refusal it lifts was not a parser gap: the prompt collected its cost by
    counting to a number, so a {B} had nothing to collect it with, and the
    lowering refused rather than describe a payment that could not happen."""
    game, p1, devotee = _devotee_board(set_pool, ["Swamp", "Forest"])

    game.resolve_end_step(0)
    game._settle()
    pending = game.pending_choices_of("optional_pay", 0)
    assert pending, "the offer should be made"
    assert pending[0].data["prompt"] == "Pay {1}{B}?"

    assert game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert [p.card.name for p in p1.battlefield if "Zombie" in p.card.name] == [
        "Zombie Token"
    ]
    assert all(p.tapped for p in p1.battlefield if p.card.primary_type == "land")


def test_lilianas_devotee_is_not_offered_a_cost_it_cannot_pay(set_pool):
    """CR 601.2h: an offer the player could not take is never made. Two Forests
    are two mana and still not {1}{B} — which is exactly the distinction a
    payment that counted to a number could not draw."""
    game, p1, devotee = _devotee_board(set_pool, ["Forest", "Forest"])

    game.resolve_end_step(0)
    game._settle()

    assert not game.pending_choices_of("optional_pay", 0)


def test_lilianas_devotee_is_silent_with_no_death(set_pool):
    """The intervening-if (CR 603.4). It is also what the trigger was found by:
    the end step enqueued gated triggers from a list of *instruction kinds*
    holding one entry, and this card lowers onto ``may`` — so it would have
    compiled clean and never fired."""
    pool = set_pool("M21")
    devotee = Permanent(card=pool["Liliana's Devotee"])
    p1 = PlayerState(
        name="P1",
        battlefield=[devotee, Permanent(card=pool["Swamp"]), Permanent(card=pool["Forest"])],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.interactive_seats = {0}
    game.start_turn(0)

    game.resolve_end_step(0)
    game._settle()

    assert not game.pending_choices_of("optional_pay", 0)


# --- Round 64: a static bonus whose size is computed ------------------------


def _grub_board(set_pool, graveyard):
    pool = set_pool("M21")
    grub = Permanent(card=pool["Carrion Grub"])
    p1 = PlayerState(
        name="P1", battlefield=[grub], graveyard=[pool[name] for name in graveyard]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, p1, grub


def test_carrion_grub_takes_the_greatest_power_in_its_graveyard(set_pool):
    """"This creature gets +X/+0, where X is the greatest power among creature
    cards in your graveyard."

    Two things the engine had no shape for: an aggregate that is a **maximum**
    rather than a count, and a CR 613 layer-7c contribution whose *size* is
    computed — which no text-keyed static table can express, because the size is
    the whole variable part."""
    game, p1, grub = _grub_board(set_pool, ["Alpine Watchdog", "Selfless Savior"])

    # The Watchdog is the bigger of the two (2/2 against the Savior's 1/1).
    assert (grub.effective_power, grub.effective_toughness) == (2, 5)


def test_carrion_grub_is_recomputed_as_the_graveyard_changes(set_pool):
    """A static ability is continuous (CR 611.3a), not locked in — so this is
    the same question the where-clause asks at resolution, asked again on every
    recompute. One evaluator answers both."""
    game, p1, grub = _grub_board(set_pool, ["Alpine Watchdog"])
    assert grub.effective_power == 2

    p1.graveyard.append(set_pool("M21")["Gale Swooper"])  # 3/2
    game.check_state_based_actions()

    assert grub.effective_power == 3


def test_carrion_grub_counts_no_noncreature_card(set_pool):
    """The narrowing, and the empty case: a maximum over nothing is 0, which is
    what the printed 0/5 body then is."""
    game, p1, grub = _grub_board(set_pool, ["Island", "Shock"])

    assert (grub.effective_power, grub.effective_toughness) == (0, 5)


def test_selfless_savior_names_a_creature_that_is_not_itself(set_pool):
    """"Sacrifice this creature: **Another** target creature you control gains
    indestructible until end of turn."

    Round 65 withdrew this card rather than keep dropping the word: the emitted
    filter excluded nothing, so the picker offered the Savior itself — an illegal
    target the player could announce, whose cost then sacrificed it and whose
    ability then fizzled. CR 601.2c is why the word has to be said at all, since
    two instances of "target" may otherwise name the same object.

    It is back because the word now has somewhere to go. This sentence names one
    chosen object, so the only referent "another" can exclude is the ability's
    source (CR 109.5) — which is what ``other_than_source``/``exclude_self``
    already says, and what the picker and the handlers already read. The
    genuinely-two-slot meaning is claimed above this by the fusers and refused
    everywhere else, so the two readings cannot be confused.
    """
    program = compile_card_oracle(set_pool("M21")["Selfless Savior"])

    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature",
        "controller": "you",
        "exclude_self": True,
    }


# --- Round 66: a life payment as a cost, and a coin flip ---------------------


def _swindler_board(set_pool, life=20):
    pool = set_pool("M21")
    swindler = _nosick(Permanent(card=pool["Tavern Swindler"]))
    p1 = PlayerState(name="P1", battlefield=[swindler], life=life)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game, p1, swindler


def _activate_swindler(game, *, win: bool):
    """Activate the ability with the flip forced.

    ``engine.handlers._common`` is where ``flip_coin`` draws from, and patching
    ``random.random`` on it is patching the one module object every other reader
    of the RNG shares. Patching ``flip_coin`` itself would skip the draw, and a
    test that skips the draw cannot say what the draw count is.
    """
    with patch("engine.handlers._common.random.random", return_value=0.0 if win else 0.99):
        result = game.queue_permanent_ability(0, "Tavern Swindler", permanent_index=0)
        game._settle()
    return result


def test_tavern_swindler_pays_three_life_and_gains_six_on_a_win(set_pool):
    """"{T}, Pay 3 life: Flip a coin. If you win the flip, you gain 6 life."

    Both halves in one activation: the life is a cost paid on activation
    (CR 118.3b), and the gain is what the won flip's branch does at resolution.
    20 - 3 + 6."""
    game, p1, swindler = _swindler_board(set_pool)

    result = _activate_swindler(game, win=True)

    assert result.supported, result.details
    assert p1.life == 23
    assert swindler.tapped is True


def test_tavern_swindler_still_pays_the_three_life_on_a_loss(set_pool):
    """A cost is paid whether or not the effect does anything (CR 601.2h) â€” the
    losing branch is the whole point of the card, and a cost the engine only
    charged on success would make it strictly better than it prints."""
    game, p1, swindler = _swindler_board(set_pool)

    result = _activate_swindler(game, win=False)

    assert result.supported, result.details
    assert p1.life == 17
    assert swindler.tapped is True


def test_tavern_swindler_flips_exactly_one_coin(set_pool):
    """One printed flip is one draw from the RNG. Two would be a different card
    and, in a seeded simulation, a different game from that point on."""
    game, _p1, _swindler = _swindler_board(set_pool)

    with patch("engine.handlers._common.random.random", return_value=0.0) as flip:
        game.queue_permanent_ability(0, "Tavern Swindler", permanent_index=0)
        game._settle()

    assert flip.call_count == 1


def test_tavern_swindler_cannot_be_activated_below_its_life_cost(set_pool):
    """CR 119.4 through CR 602.5c: an unpayable cost makes the ability
    unactivatable, not free. Nothing is spent and the creature stays untapped."""
    game, p1, swindler = _swindler_board(set_pool, life=2)

    result = _activate_swindler(game, win=True)

    assert not result.supported
    # The refusal has to be *this* refusal. Before the round the whole ability
    # was unsupported, so "not supported" was already true for a reason that
    # says nothing about life â€” which is exactly how a control passes while the
    # rule it names is unimplemented.
    assert "life" in result.details
    assert p1.life == 2
    assert swindler.tapped is False

# --- Round 69: a trigger on the activation, not on what it resolves into ----
#
# "Whenever you activate a loyalty ability of a Chandra planeswalker, this
# creature deals 1 damage to each opponent." One condition with two narrowings,
# and they fail in different directions: the *actor* is CR 109.5's "you" (drop
# it and an opponent's own tick-up pings them on your behalf) and the *object*
# is a printed noun phrase (drop it and every planeswalker in the format is a
# Chandra). "Chandra" is a planeswalker subtype â€” see
# data/vocabulary/planeswalker_types.json â€” and never a card name.


def _disciples_board(set_pool, walker_name, *, loyalty=None,
                     walker_seat=0, disciple_seat=0):
    """A planeswalker and the Disciples, on the seats named.

    The seats are parameters because the trigger says "you": which seat
    activates and which seat watches are the two halves the condition tests.
    """
    pool = set_pool("M21")
    card = pool[walker_name]
    walker = Permanent(
        card=card, metadata={"loyalty_counters": int(loyalty or card.loyalty)}
    )
    seats = [PlayerState(name="P1"), PlayerState(name="P2")]
    seats[walker_seat].battlefield.append(walker)
    disciples = Permanent(card=pool["Keral Keep Disciples"])
    seats[disciple_seat].battlefield.append(disciples)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.active_player_index = walker_seat
    return game, walker, disciples


def test_keral_keep_disciples_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Keral Keep Disciples"])
    assert program.supported, program.reason
    condition = program.triggered_abilities[0].condition
    assert condition.kind == "you_activate_loyalty_ability"
    # The subtype, and no `named` key: four cards in this pool alone are called
    # Chandra-something, and a name match here would be dispatch on a card name
    # outside card_hooks.py.
    assert condition.payload["walker_filter"] == {
        "type_filter": "planeswalker",
        "subtype_filter": "chandra",
    }


def test_keral_keep_disciples_pings_each_opponent_when_a_chandra_ticks_up(set_pool):
    """+1 on Chandra, Flame's Catalyst: her own 3 to each opponent, and the
    Disciples' 1 on top of it."""
    game, walker, _ = _disciples_board(set_pool, "Chandra, Flame's Catalyst")

    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)

    assert result.supported, result.details
    assert [p.life for p in game.players] == [20, 16]
    assert walker.metadata["loyalty_counters"] == 6


def test_the_disciples_trigger_goes_on_the_stack_above_the_loyalty_ability(set_pool):
    """CR 603.3: an ability that triggers while a loyalty ability is being
    activated is put on the stack once that activation finishes, so it is the
    topmost object and resolves first.

    This engine pays costs *before* it pushes â€” a payment that cannot be made
    has to leave nothing behind â€” so the announcement at the CR 606.4 payment
    is held by ``deferring_triggers`` until the push has happened. Read off the
    stack rather than off the log, because the order is the assertion.
    """
    pool = set_pool("M21")
    game, walker, _ = _disciples_board(set_pool, "Chandra, Heart of Fire")
    game.players[0].library = [pool["Shock"]] * 5

    queued = game.queue_permanent_ability(0, walker.card.name, ability_index=1)

    assert queued.details == "queued", queued.details
    assert [item.card.name for item in game.stack] == [
        "Chandra, Heart of Fire",
        "Keral Keep Disciples",
    ], "the trigger is above the ability that fired it"


def test_a_planeswalker_of_another_subtype_leaves_the_disciples_silent(set_pool):
    """The control for the object half. Liliana's +1 is not damage, so any life
    lost here would be the Disciples firing on a phrase they do not match."""
    game, walker, _ = _disciples_board(set_pool, "Liliana, Death Mage")

    assert game.activate_permanent_ability(
        0, walker.card.name, ability_index=0
    ).supported
    assert [p.life for p in game.players] == [20, 20]


def test_an_opponents_chandra_leaves_your_disciples_silent(set_pool):
    """The control for the actor half, and the one the printed phrase does not
    carry: there is no "you control" on the planeswalker, so the filter alone
    matches an opponent's Chandra. "You" is the *trigger's* controller
    (CR 109.5), which is the seat the announcement carries.
    """
    game, walker, _ = _disciples_board(
        set_pool, "Chandra, Flame's Catalyst", walker_seat=1, disciple_seat=0,
    )

    assert game.activate_permanent_ability(
        1, walker.card.name, ability_index=0
    ).supported
    # Chandra's own 3 at her opponent, and nothing from the Disciples.
    assert [p.life for p in game.players] == [17, 20]


def test_the_disciples_fire_off_a_minus_that_bins_its_own_walker(set_pool):
    """CR 606.4's payment *is* the activation, and CR 704.5i bins a
    planeswalker the moment its last loyalty counter goes â€” so by the time the
    trigger resolves the Chandra is in the graveyard. What the condition asked
    about happened while she was still there."""
    pool = set_pool("M21")
    game, walker, _ = _disciples_board(
        set_pool, "Chandra, Flame's Catalyst", loyalty=8,
    )
    game.players[0].library = [pool["Shock"]] * 8

    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)

    assert result.supported, result.details
    assert not game.is_on_battlefield(walker), "0 loyalty (CR 704.5i)"
    assert game.players[1].life == 19


def test_a_loyalty_cost_the_walker_cannot_pay_fires_nothing(set_pool):
    """CR 606.6: a minus larger than the loyalty on the permanent cannot be
    activated at all, so there is no activation for the trigger to have seen.
    The announcement sits *after* the sufficiency check for that reason."""
    game, walker, _ = _disciples_board(
        set_pool, "Chandra, Flame's Catalyst", loyalty=1,
    )

    refused = game.activate_permanent_ability(0, walker.card.name, ability_index=2)

    assert not refused.supported
    assert "606.6" in refused.details
    assert [p.life for p in game.players] == [20, 20]
    assert not game.stack, (
        "a refused activation leaves nothing behind â€” including a trigger "
        "announced before the check that refused it"
    )


def test_a_second_loyalty_activation_the_same_turn_fires_nothing(set_pool):
    """CR 606.3's other half: one loyalty ability per permanent per turn. The
    second attempt is refused, so it pings nobody â€” one tick, one ping."""
    game, walker, _ = _disciples_board(set_pool, "Chandra, Flame's Catalyst")

    assert game.activate_permanent_ability(
        0, walker.card.name, ability_index=0
    ).supported
    again = game.activate_permanent_ability(0, walker.card.name, ability_index=0)

    assert not again.supported
    assert [p.life for p in game.players] == [20, 16]
    assert not game.stack


def test_a_non_loyalty_activation_leaves_the_disciples_silent(set_pool):
    """"A **loyalty** ability" (CR 606.2) â€” which is why the announcement sits
    at the loyalty-counter payment rather than at the bottom of every
    activation.

    Belt and braces: the subject filter refuses a creature anyway, and no card
    in this pool prints a *non*-loyalty ability on a planeswalker (the compiler
    refuses one outright), so this is the closest a real card gets to the
    distinction.
    """
    pool = set_pool("M21")
    game, _, _ = _disciples_board(set_pool, "Chandra, Flame's Catalyst")
    game.players[0].battlefield.append(
        _nosick(Permanent(card=pool["Chandra's Magmutt"]))
    )

    result = game.activate_permanent_ability(
        0, "Chandra's Magmutt", target_player_index=1,
    )

    assert result.supported, result.details
    # The Magmutt's own ping, and nothing behind it.
    assert [p.life for p in game.players] == [20, 19]

# --- Round 72: a conditional permission that lifts defender ------------------


def _tyrannodon_board(set_pool, *, with_big: bool):
    """The Tyrannodon, optionally beside a plainly 4-power friend, at declare
    attackers."""
    pool = set_pool("M21")
    tyrannodon = _nosick(Permanent(card=pool["Drowsing Tyrannodon"]))  # 3/3
    battlefield = [tyrannodon]
    if with_big:
        battlefield.append(_nosick(Permanent(card=pool["Colossal Dreadmaw"])))  # 6/6
    game = Game(players=[PlayerState(name="P1", battlefield=battlefield),
                         PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    return game, tyrannodon


def test_drowsing_tyrannodon_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Drowsing Tyrannodon"])

    assert program.supported, program.reason
    permission = [
        i for i in program.instructions
        if i.kind == "conditional_static" and i.payload.get("ignores_defender")
    ]
    assert len(permission) == 1, program.instructions
    # The condition is the payload the grammar already produces for a
    # "you control a creature with power 4 or greater" intervening-if, so the
    # phrase has one meaning in the engine rather than two that agree today.
    assert permission[0].payload["condition"] == {
        "kind": "controls", "who": "you",
        "filter": {"type_filter": "creature", "power": {"op": "ge", "value": 4}},
    }


def test_drowsing_tyrannodon_attacks_only_beside_a_four_power_creature(set_pool):
    """The card has to *attack*, not merely compile. Fixing the parser alone
    leaves a supported creature that still can't be declared."""
    game, tyrannodon = _tyrannodon_board(set_pool, with_big=True)
    assert game.declare_attackers(0, [0]) == (True, "declared attackers")

    alone, tyrannodon_alone = _tyrannodon_board(set_pool, with_big=False)
    ok, message = alone.declare_attackers(0, [0])
    assert not ok
    assert "cannot attack" in message
    # Its own 3 power is under the threshold, so nothing on the board answers.
    assert tyrannodon_alone.effective_power == 3


def test_drowsing_tyrannodon_still_has_defender_while_it_attacks(set_pool):
    """CR 609.4: "as though" applies to the stated effect and nothing else.

    Granting the permission by *removing* defender would pass an attack test and
    then quietly change what a defender-narrowed noun phrase matches â€” which is
    how Portcullis Vine's "sacrifice a creature with defender" would stop
    seeing it.
    """
    from engine.subject_filters import subject_matches

    game, tyrannodon = _tyrannodon_board(set_pool, with_big=True)
    assert game.can_attack(tyrannodon, 1)

    assert game._has_keyword(tyrannodon, "defender")
    assert subject_matches(
        game, tyrannodon, {"type_filter": "creature", "with_keywords": ["defender"]},
        observer=0,
    )


def test_drowsing_tyrannodon_can_answer_its_own_condition(set_pool):
    """The card prints "a creature", not "another creature" (contrast Turret
    Ogre), so a Tyrannodon pumped to 4 power satisfies itself â€” and the power it
    is asked for is the layer-computed one, not the printed 3.
    """
    from engine.pt import add_pt_modifier

    game, tyrannodon = _tyrannodon_board(set_pool, with_big=False)
    assert not game.can_attack(tyrannodon, 1)

    add_pt_modifier(tyrannodon, 1, 1)
    game._recompute_continuous_effects()

    assert tyrannodon.effective_power == 4
    assert game.can_attack(tyrannodon, 1)


def test_drowsing_tyrannodons_permission_ends_when_the_big_creature_does(set_pool):
    """"As long as" is asked of the board at every read, never latched at a
    recompute â€” the same reason the block-legality check asks Tome Anima's twin
    at block time."""
    game, tyrannodon = _tyrannodon_board(set_pool, with_big=True)
    assert game.can_attack(tyrannodon, 1)

    dreadmaw = game.players[0].battlefield[1]
    game.remove_from_battlefield(dreadmaw)
    game._settle()

    assert not game.can_attack(tyrannodon, 1)

# --- Round 71: the word "another" with nothing else to point at -------------


def _savior_board(set_pool):
    """The Savior, one other creature of its controller's, one of the opponent's."""
    pool = set_pool("M21")
    savior = _nosick(Permanent(card=pool["Selfless Savior"]))
    mine = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    theirs = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(name="P1", battlefield=[savior, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game, p1, p2, savior, mine, theirs


def test_selfless_savior_compiles_supported(set_pool):
    """"Sacrifice this creature: **Another** target creature you control gains
    indestructible until end of turn."

    Withdrawn in round 65 because the word was being dropped: a one-recipient
    description had nowhere to say which other choice this one differs from
    (CR 601.2c), and dropped, the picker offered the Savior itself. It is back
    because the sentence chooses nothing else, so the only object "another" can
    exclude is the source (CR 109.5) — and that restriction the payload can
    carry."""
    program = compile_card_oracle(set_pool("M21")["Selfless Savior"])

    assert program.supported
    ability, = program.activated_abilities
    assert ability.cost.sacrifice_self
    assert ability.instruction.kind == "grant_target_keyword_until_eot"
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature", "controller": "you", "exclude_self": True,
    }


def test_the_savior_is_never_offered_as_its_own_target(set_pool):
    """The half that made round 65 withdraw the card. An illegal target a player
    can announce is worse than an unsupported card: the cost sacrifices the
    Savior and the ability then fizzles, with nothing on screen saying why."""
    game, _p1, _p2, savior, mine, theirs = _savior_board(set_pool)
    ability, = compile_card_oracle(savior.card).activated_abilities

    spec = derive_activation_spec(ability)
    assert spec == {"kind": "creature", "own_only": True, "exclude_source": True}

    offered = game._enumerate_targets(
        0, savior.card, spec, for_cast=False,
        ability_instruction=ability.instruction, source_permanent=savior,
    )
    assert [t.get("name") for t in offered] == [mine.card.name]


def test_the_savior_saves_another_creature_and_dies_doing_it(set_pool):
    """End to end: the sacrifice is a cost (CR 601.2h — paid on activation, so
    the Savior is in the graveyard before the ability resolves), and what the
    ability grants is real indestructibility."""
    game, p1, _p2, savior, mine, _theirs = _savior_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Selfless Savior", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(savior)
    assert [c.name for c in p1.graveyard] == ["Selfless Savior"]
    assert mine.has_keyword("indestructible")

    game._mark_damage_on_permanent(mine, 9, source=None)
    game.check_state_based_actions()
    assert game.is_on_battlefield(mine), "lethal damage does not destroy it (CR 702.12b)"


def test_the_grant_refuses_a_creature_its_activator_does_not_control(set_pool):
    """The resolution half of the printed noun phrase. ``derive_activation_spec``
    narrows what is *offered*, but nothing validates an announcement that did
    not come through the picker — so the handler has to ask the same question,
    which it did not: it resolved with the default "is it a creature?" predicate
    and read no filter at all."""
    game, _p1, _p2, _savior, mine, theirs = _savior_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Selfless Savior", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game._settle()

    assert not theirs.has_keyword("indestructible")
    assert not mine.has_keyword("indestructible"), (
        "a refused target is not a licence to pick a different one"
    )

# --- Round 71, also: a global buff that was dropping its "other" ------------


def test_bolt_hound_does_not_pump_itself(set_pool):
    """"Whenever this creature attacks, **other** creatures you control get
    +1/+0 until end of turn."

    The global-buff lowering read four fields off the printed noun phrase and
    dropped the rest, so the Hound buffed itself as well and played as a
    strictly better card than the one printed. The same word, the same failure,
    one layer away from the Savior's."""
    pool = set_pool("M21")
    hound = _nosick(Permanent(card=pool["Bolt Hound"]))
    mate = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    theirs = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(name="P1", battlefield=[hound, mate], library=[pool["Island"]] * 3)
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg
    game._settle()

    assert hound.effective_power == 2, "the Hound is not one of the *other* creatures"
    assert mate.effective_power == 3
    assert theirs.effective_power == 1, '"you control" still holds'


# --- Round 76: a trigger that fires from a graveyard ------------------------


def _ghoul_graveyard(set_pool, life_gained=3, copies=1):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", graveyard=[pool["Silversmote Ghoul"] for _ in range(copies)]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    p1.life_gained_this_turn = life_gained
    return game, p1


def _ghouls_on(player):
    return [p for p in player.battlefield if p.card.name == "Silversmote Ghoul"]


def test_silversmote_ghoul_compiles_with_the_zone_it_functions_from(set_pool):
    """CR 113.6: an object's abilities function only on the battlefield unless
    the ability says otherwise, and CR 113.6m is the clause that says so for an
    ability whose effect moves its own source out of a zone.

    So the key is *derived* from the sentence rather than declared per card: the
    zone the sentence names as the source is the zone the ability works from, and
    the scan reads that key rather than a list of instruction kinds."""
    program = compile_card_oracle(set_pool("M21")["Silversmote Ghoul"])

    assert program.supported, program.reason
    trigger = next(
        t for t in program.triggered_abilities
        if t.instruction is not None
        and t.instruction.kind == "return_self_from_graveyard"
    )
    assert trigger.condition.kind == "end_step_self"
    payload = trigger.instruction.payload
    assert payload["tapped"] is True
    assert payload["functions_from"] == "graveyard"
    # And the CR 603.4 gate rides the same instruction, which is what the
    # graveyard scan re-checks before enqueueing anything.
    assert payload["intervening_if"] == {
        "kind": "life_gained_this_turn", "who": "you", "amount": 3,
    }


def test_silversmote_ghoul_returns_tapped_after_three_life(set_pool):
    """"â€¦return this card from your graveyard to the battlefield **tapped**" â€”
    CR 110.5b, a permanent enters untapped unless an ability says otherwise."""
    game, p1 = _ghoul_graveyard(set_pool, life_gained=3)

    game.resolve_end_step(0)
    game._settle()

    (ghoul,) = _ghouls_on(p1)
    assert ghoul.tapped, "CR 110.5b â€” the ability said otherwise"
    assert p1.graveyard == []


def test_silversmote_ghoul_stays_down_below_three_life(set_pool):
    """The intervening-if (CR 603.4), checked when the trigger would fire."""
    game, p1 = _ghoul_graveyard(set_pool, life_gained=2)

    game.resolve_end_step(0)
    game._settle()

    assert _ghouls_on(p1) == []
    assert len(p1.graveyard) == 1


def test_silversmote_ghoul_ignores_an_opponents_end_step(set_pool):
    """"**Your** end step". A card in a graveyard has no controller, so "your"
    is its owner's (CR 108.4a) â€” which is the seat the scan enqueues it under,
    not whichever seat the step happens to be running for."""
    game, p1 = _ghoul_graveyard(set_pool, life_gained=3)

    game.resolve_end_step(1)
    game._settle()

    assert _ghouls_on(p1) == []
    assert len(p1.graveyard) == 1


def test_two_copies_in_one_graveyard_both_return(set_pool):
    """The look-alike trap, in the zone where it is worst. A graveyard holds
    ``CardDefinition`` objects and two copies of one card are *the same
    immutable object*, so removing "one" with a filter-by-identity rebuild
    removes **both** and a name match finds the wrong entry. The handler pops at
    an identity-found index, which removes exactly one â€” and each copy is
    enqueued separately, so both come back as distinct permanents."""
    game, p1 = _ghoul_graveyard(set_pool, life_gained=3, copies=2)

    game.resolve_end_step(0)
    game._settle()

    returned = _ghouls_on(p1)
    assert len(returned) == 2
    assert len({p.permanent_id for p in returned}) == 2, "two objects, two ids"
    assert p1.graveyard == []


def test_the_self_return_refuses_a_destination_no_handler_moves_to():
    """The rider is only a sentence for the battlefield. "To your hand tapped"
    is not one, and silently dropping the word is the bug class this grammar
    refuses by construction."""
    result = compile_line(
        "Return this card from your graveyard to your hand.", card_name="Test"
    )

    assert result.parsed and not result.lowered
    assert "graveyard to the hand" in result.failure_reason


# --- Round 78: what a card *was*, read after it stopped being there ---------


def _ooze_board(set_pool, graveyard_card, *, opponent=True):
    pool = set_pool("M21")
    ooze = _nosick(Permanent(card=pool["Scavenging Ooze"]))
    p1 = PlayerState(name="P1", battlefield=[ooze], life=20)
    p2 = PlayerState(name="P2")
    holder = p2 if opponent else p1
    holder.graveyard.append(pool[graveyard_card])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, ooze, holder


def _activate(game, holder_seat):
    return game.activate_permanent_ability(
        0, "Scavenging Ooze", permanent_index=0,
        target_player_index=holder_seat, target_permanent_index=0,
    )


def test_scavenging_ooze_compiles_supported(set_pool):
    """"{G}: Exile target card from **a** graveyard." â€” any graveyard, not the
    controller's, and the rider reads what the exiled card *was*."""
    program = compile_card_oracle(set_pool("M21")["Scavenging Ooze"])

    assert program.supported, program.reason


def test_exiling_a_creature_card_grows_the_ooze_and_gains_the_life(set_pool):
    """The whole sentence: the exile happens either way, and the counter and the
    life ride on what the card was."""
    game, ooze, holder = _ooze_board(set_pool, "Alpine Watchdog")

    result = _activate(game, 1)
    assert result.supported, result.details
    game._settle()

    assert int(ooze.metadata.get("plus_counters", 0)) == 1
    assert game.players[0].life == 21
    assert holder.graveyard == []


def test_exiling_a_noncreature_card_exiles_it_and_nothing_else(set_pool):
    """"**If it was a creature card**" is a condition on the rider, not on the
    exile. The instant still goes, and the Ooze gets nothing."""
    game, ooze, holder = _ooze_board(set_pool, "Shock")

    _activate(game, 1)
    game._settle()

    assert int(ooze.metadata.get("plus_counters", 0)) == 0
    assert game.players[0].life == 20
    assert holder.graveyard == [], "the exile is unconditional"


def test_the_ooze_can_eat_its_own_controllers_graveyard(set_pool):
    """"a graveyard" is any graveyard (CR 109.5 does not narrow it), so the
    controller's own pile is a legal choice."""
    game, ooze, holder = _ooze_board(set_pool, "Alpine Watchdog", opponent=False)

    _activate(game, 0)
    game._settle()

    assert int(ooze.metadata.get("plus_counters", 0)) == 1
    assert holder.graveyard == []


def test_the_rider_refuses_with_no_exile_before_it():
    """A back-reference names its producer or refuses (idiom #7). "It was" reads
    what an earlier step of the same effect recorded, so with nothing recorded
    the condition would answer False forever and the card would compile clean
    while its rider never fired."""
    result = compile_line(
        "If it was a creature card, you gain 1 life.", card_name="Test"
    )

    assert result.parsed and not result.lowered
    assert result.failure_reason
