"""Core Set 2021 (M21) planeswalkers — loyalty, emblems, phasing, delayed triggers.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- The planeswalker round: loyalty, emblems, delayed triggers, phasing ----


@pytest.mark.parametrize(
    "name",
    [
        "Ugin, the Spirit Dragon",
        "Basri Ket",
        "Teferi, Master of Time",
        "Liliana, Waker of the Dead",
        "Garruk, Unleashed",
        "Basri, Devoted Paladin",
        "Teferi, Timeless Voyager",
        "Liliana, Death Mage",
        "Garruk, Savage Herald",
    ],
)
def test_planeswalker_round_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


@pytest.mark.parametrize(
    "name",
    [
        # Formerly the two walkers held honest by
        # test_chandras_report_the_unbuilt_permission_seam: both needed the
        # cast/play-from-exile-or-graveyard permission seam, which now exists
        # (engine/cast_permissions.py).
        "Chandra, Heart of Fire",
        "Chandra, Flame's Catalyst",
    ],
)
def test_chandras_compile_through_the_permission_seam(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def test_chandra_heart_of_fire_plus_one_permits_playing_the_exiled_cards(set_pool):
    """+1: the hand goes, the top three go to exile, and exactly those three
    are castable/playable from exile until end of turn."""
    pool = set_pool("M21")
    shock, pegasus = pool["Shock"], pool["Concordia Pegasus"]
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire",
        hand=[pegasus], library=[shock, pegasus, pegasus, pegasus],
    )
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details
    me = game.players[0]
    assert me.hand == []
    # The discarded Pegasus went to the graveyard, not exile; the top three
    # library cards (Shock + two Pegasi) were exiled; the fourth stayed.
    assert len(me.exile) == 3
    assert [card.name for card in me.graveyard] == ["Concordia Pegasus"]
    assert len(me.library) == 1
    exiled_names = [card.name for card in me.exile]
    assert exiled_names.count("Shock") == 1
    # Shock was among the exiled three and is castable from exile at the
    # opponent's face; the fourth library card stayed put and is not.
    cast = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18


def test_chandra_heart_of_fire_permission_ends_at_cleanup(set_pool):
    pool = set_pool("M21")
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire",
        library=[pool["Shock"], pool["Shock"], pool["Shock"], pool["Shock"]],
    )
    assert game.activate_permanent_ability(0, walker.card.name, ability_index=0).supported
    game.resolve_cleanup_step(0)
    refused = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert not refused.supported
    assert "601.3" in refused.details


def test_chandra_heart_of_fire_ultimate_adds_no_mana_until_the_search_is_answered(set_pool):
    """−9: the search suspends the rest of the resolution — "You may cast them
    this turn." and "Add six {R}." run only once the picks are in (the Opt
    lesson, CR 608.2n's cousin for loyalty abilities)."""
    pool = set_pool("M21")
    shock, pegasus = pool["Shock"], pool["Concordia Pegasus"]
    game, walker = _walker_game(
        set_pool, "Chandra, Heart of Fire", loyalty=9,
        library=[pegasus, shock], graveyard=[shock],
    )
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    me = game.players[0]
    pending = game.pending_choices_of("search_exile_cards", 0)
    assert pending, "the two-zone search should be waiting on its picks"
    assert me.mana_pool.get("R", 0) == 0
    # Take the Shock from each zone; the Pegasus is not red and not legal.
    ok = game.confirm_search_exile(0, [
        {"zone": "graveyard", "index": 0},
        {"zone": "library", "index": 1},
    ])
    assert ok
    assert me.mana_pool.get("R", 0) == 6
    assert [card.name for card in me.exile].count("Shock") == 2
    cast = game.cast_from_hand(0, "Shock", from_zone="exile", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18


def test_chandra_flames_catalyst_minus_two_casts_it_then_exiles_it(set_pool):
    """−2: the targeted graveyard card becomes castable, and the printed rider
    routes it to exile instead of back to the graveyard when it leaves the
    stack (CR 614.1a)."""
    pool = set_pool("M21")
    shock = pool["Shock"]
    game, walker = _walker_game(
        set_pool, "Chandra, Flame's Catalyst", graveyard=[shock],
    )
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result.details
    cast = game.cast_from_hand(0, "Shock", from_zone="graveyard", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18
    me = game.players[0]
    assert [card.name for card in me.exile] == ["Shock"]
    assert all(card.name != "Shock" for card in me.graveyard)


def test_chandra_flames_catalyst_minus_eight_waives_mana_costs_until_end_of_turn(set_pool):
    pool = set_pool("M21")
    shock = pool["Shock"]
    game, walker = _walker_game(
        set_pool, "Chandra, Flame's Catalyst", loyalty=9,
        hand=[pool["Concordia Pegasus"]], library=[shock] * 8,
    )
    game.enforce_mana_costs = True
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    me = game.players[0]
    assert len(me.hand) == 7  # hand discarded, seven drawn
    # An empty pool casts Shock anyway: the waiver covers it.
    cast = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert cast.supported, cast.details
    assert game.players[1].life == 18
    # CR 514.2: the waiver ends at cleanup; the next Shock needs real mana.
    game.resolve_cleanup_step(0)
    refused = game.cast_from_hand(0, "Shock", target_player_index=1)
    assert not refused.supported
    assert "insufficient mana" in refused.details


def _walker_game(set_pool, name, loyalty=None, opp_battlefield=None, hand=None, library=None, graveyard=None):
    card = set_pool("M21")[name]
    walker = Permanent(card=card, metadata={"loyalty_counters": int(loyalty or card.loyalty)})
    p1 = PlayerState(
        name="P1", battlefield=[walker], hand=list(hand or []),
        library=list(library or []), graveyard=list(graveyard or []),
    )
    p2 = PlayerState(name="P2", battlefield=list(opp_battlefield or []))
    return Game(players=[p1, p2]), walker


def test_teferi_master_of_time_takes_two_extra_turns(set_pool):
    game, walker = _walker_game(set_pool, "Teferi, Master of Time", loyalty=12)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    assert game.extra_turn_queue.count(0) == 2


def test_teferi_master_of_time_activates_on_an_opponents_turn(set_pool):
    game, walker = _walker_game(set_pool, "Teferi, Master of Time")
    game.active_player_index = 1
    game.players[0].library = [set_pool("M21")["Concordia Pegasus"]] * 2
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details


def test_teferi_master_of_time_phases_out_an_opposing_creature(set_pool):
    bear = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game, walker = _walker_game(set_pool, "Teferi, Master of Time", opp_battlefield=[bear])
    original_id = bear.permanent_id
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bear)
    assert any(p is bear for p in game.players[1].phased_out)
    # CR 702.26e: it phases in at its controller's untap step, the same object.
    game.resolve_untap_step(1)
    assert game.is_on_battlefield(bear)
    assert bear.permanent_id == original_id


def test_liliana_waker_of_the_dead_plus_one_punishes_empty_hands(set_pool):
    game, walker = _walker_game(set_pool, "Liliana, Waker of the Dead",
                                hand=[set_pool("M21")["Concordia Pegasus"]])
    # Opponent has no hand: they cannot discard and lose 3 life.
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=0)
    assert result.supported, result.details
    assert game.players[1].life == 17
    assert len(game.players[0].hand) == 0


def test_liliana_death_mage_destroy_drains_the_controller(set_pool):
    bear = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game, walker = _walker_game(set_pool, "Liliana, Death Mage", opp_battlefield=[bear])
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(bear)
    assert game.players[1].life == 18
    assert walker.metadata["loyalty_counters"] == 1


def test_basri_ket_minus_two_makes_attacking_soldiers(set_pool):
    game, walker = _walker_game(set_pool, "Basri Ket")
    attacker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game.players[0].battlefield.append(attacker)
    game.start_turn(0)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=1)
    assert result.supported, result.details
    assert len(game.delayed_triggers) == 1
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    attacker.metadata.pop("summoning_sickness_turn", None)
    slot = game.battlefield_index_of(attacker)
    ok, msg = game.declare_attackers(0, [slot])
    assert ok, msg
    while game.stack:
        game.resolve_top_of_stack()
    soldiers = [p for p in game.controlled_by(0) if "Soldier" in p.card.name]
    assert len(soldiers) == 1
    assert soldiers[0].tapped and soldiers[0].attacking


def test_basri_devoted_paladin_counters_each_attacker(set_pool):
    game, walker = _walker_game(set_pool, "Basri, Devoted Paladin")
    attacker = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    game.players[0].battlefield.append(attacker)
    game.start_turn(0)
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=1)
    assert result.supported, result.details
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    attacker.metadata.pop("summoning_sickness_turn", None)
    slot = game.battlefield_index_of(attacker)
    ok, msg = game.declare_attackers(0, [slot])
    assert ok, msg
    while game.stack:
        game.resolve_top_of_stack()
    # 1/3 Pegasus with a +1/+1 counter attacks as a 2/4.
    assert attacker.effective_power == 2


def test_garruk_unleashed_emblem_tutors_at_end_step(set_pool):
    pegasus = set_pool("M21")["Concordia Pegasus"]
    game, walker = _walker_game(set_pool, "Garruk, Unleashed", loyalty=8,
                                library=[pegasus])
    result = game.activate_permanent_ability(0, walker.card.name, ability_index=2)
    assert result.supported, result.details
    assert len(game.players[0].emblems) == 1
    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_choices()
    # Non-interactive search default: the creature is on the battlefield.
    assert any(p.card.name == "Concordia Pegasus" for p in game.controlled_by(0))


def test_ugin_minus_x_exiles_colored_permanents_by_mana_value(set_pool):
    cheap = Permanent(card=set_pool("M21")["Concordia Pegasus"])   # mv 2, white
    game, walker = _walker_game(set_pool, "Ugin, the Spirit Dragon",
                                opp_battlefield=[cheap])
    result = game.activate_permanent_ability(
        0, walker.card.name, ability_index=1, x_value=3,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(cheap)
    assert any(c.name == "Concordia Pegasus" for c in game.players[1].exile)
    # Ugin itself is colorless: the sweep spared it.
    assert game.is_on_battlefield(walker)
    assert walker.metadata["loyalty_counters"] == 4


def test_garruk_savage_herald_bite_compiles_to_the_two_target_kind(set_pool):
    walker_card = set_pool("M21")["Garruk, Savage Herald"]
    program = compile_card_oracle(walker_card)
    assert program.activated_abilities[1].instruction.kind == "target_bites_target"


def test_garruk_savage_herald_can_bite_an_opponents_creature(set_pool):
    """"Target creature you control deals damage … to **another target
    creature**" names the caster's creature and then *anyone's*. Two things
    hid the second half.

    The picker carried one filter for both slots, so "you control" narrowed
    them both and only the caster's creatures were ever offered — the ability
    could bite nothing but its own board, while its handler was written to
    allow either. And the stack re-derived both targets' identities from the
    single `target_player_index`, so a second slot on the other battlefield
    resolved to whatever sat at that index on the wrong board.
    """
    from engine.targeting import derive_activation_spec

    pool = set_pool("M21")
    walker_card = pool["Garruk, Savage Herald"]
    program = compile_card_oracle(walker_card)
    bite = program.activated_abilities[1]

    spec = derive_activation_spec(bite)
    assert spec["max_targets"] == 2
    assert "own_only" not in spec, "the second slot admits any creature"

    walker = Permanent(card=walker_card, metadata={"loyalty_counters": 5})
    mine = Permanent(card=pool["Elder Gargaroth"])       # 6/6, the biter
    theirs = Permanent(card=pool["Concordia Pegasus"])   # 1/3, the bitten
    p1 = PlayerState(name="P1", battlefield=[walker, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    offered = game._enumerate_targets(
        0, walker_card, spec, for_cast=False,
        ability_instruction=bite.instruction, source_permanent=walker,
    )
    assert {t.get("name") for t in offered} == {"Elder Gargaroth", "Concordia Pegasus"}

    result = game.activate_permanent_ability(
        0, "Garruk, Savage Herald", ability_index=1,
        target_player_index=0, target_permanent_index=[1, 0],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    assert result.supported, result.details
    game._settle()

    assert theirs.damage_marked == 6
    assert not game.is_on_battlefield(theirs)
    assert mine.damage_marked == 0, "a bite is one-way"

# --- Round 68: a counter on a permanent the controller chooses --------------
#
# Liliana's Scrounger is a creature, but every assertion below reads a
# *planeswalker's* loyalty — the Scrounger is only the source of the counter.
# They live here so loyalty behaviour is in one place, and because the creature
# file is at the size guard's edge (tests/engine/test_set_test_convention.py):
# M21 has 149 creatures and the printed-type axis has no further split left in
# it, which is the signal idiom #13 says to act on rather than raise.

# --- Round 68: a counter on a permanent the controller chooses --------------


def _scrounger_walker(set_pool, name, loyalty=None):
    card = set_pool("M21")[name]
    return Permanent(card=card, metadata={"loyalty_counters": int(loyalty or card.loyalty)})


def _scrounger_board(set_pool, walkers, *, scrounger_seat=0, interactive=(), died=True):
    """A Scrounger, some planeswalkers beside it, and a creature that died.

    ``scrounger_seat`` is a parameter because the trigger reads "each end step":
    the seat that controls it is not necessarily the seat whose end step runs.
    """
    pool = set_pool("M21")
    seats = [PlayerState(name="P1"), PlayerState(name="P2")]
    seats[scrounger_seat].battlefield.append(Permanent(card=pool["Liliana's Scrounger"]))
    seats[scrounger_seat].battlefield.extend(walkers)
    game = Game(players=seats)
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    if died:
        victim = Permanent(card=pool["Alpine Watchdog"])
        seats[0].battlefield.append(victim)
        game._permanent_to_graveyard(seats[0], victim)
    return game


def _end_step(game, seat=0):
    game.resolve_end_step(seat)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()


def _loyalty(permanent):
    return int(permanent.metadata.get("loyalty_counters", 0))


def test_lilianas_scrounger_puts_the_counter_on_the_only_liliana(set_pool):
    """"At the beginning of each end step, if a creature died this turn, you may
    put a loyalty counter on a Liliana planeswalker you control."

    One candidate is not a choice, so nothing is asked."""
    liliana = _scrounger_walker(set_pool, "Liliana, Waker of the Dead")   # printed 4
    _end_step(_scrounger_board(set_pool, [liliana]))

    assert _loyalty(liliana) == 5


def test_lilianas_scrounger_fires_on_an_opponents_end_step(set_pool):
    """**Each** end step, not "your" â€” the word both condition tables read and
    the dispatch did not.

    The test that fails on a half-landed change: with the lowering in and the
    condition still one kind, the gated end-step scan is scoped to the active
    player's own permanents, so a Scrounger on the other seat compiles clean and
    never fires."""
    liliana = _scrounger_walker(set_pool, "Liliana, Death Mage")          # printed 4
    _end_step(_scrounger_board(set_pool, [liliana], scrounger_seat=1))

    assert _loyalty(liliana) == 5


def test_lilianas_scrounger_is_silent_with_no_death(set_pool):
    """The intervening-if, checked when the trigger would fire (CR 603.4)."""
    liliana = _scrounger_walker(set_pool, "Liliana, Death Mage")
    _end_step(_scrounger_board(set_pool, [liliana], died=False))

    assert _loyalty(liliana) == 4


def test_a_non_liliana_planeswalker_is_not_a_recipient(set_pool):
    """The control. "Liliana" is a planeswalker *subtype*
    (data/vocabulary/planeswalker_types.json), never a card name, so Garruk is
    outside the phrase â€” and the narrowing is tested rather than dropped, which
    is why the picker refuses a filter it cannot test."""
    garruk = _scrounger_walker(set_pool, "Garruk, Unleashed")             # printed 4
    _end_step(_scrounger_board(set_pool, [garruk]))

    assert _loyalty(garruk) == 4


def test_an_opponents_liliana_is_not_a_recipient(set_pool):
    """"â€¦you control" is CR 109.5's seat: the ability's controller."""
    theirs = _scrounger_walker(set_pool, "Liliana, Death Mage")
    game = _scrounger_board(set_pool, [])
    game.players[1].battlefield.append(theirs)
    _end_step(game)

    assert _loyalty(theirs) == 4


def test_lilianas_scrounger_asks_which_liliana(set_pool):
    """Two candidates is a real choice, so an interactive seat is asked â€” and
    answers by ``permanent_id``, never by battlefield slot."""
    waker = _scrounger_walker(set_pool, "Liliana, Waker of the Dead", loyalty=4)
    mage = _scrounger_walker(set_pool, "Liliana, Death Mage", loyalty=2)
    game = _scrounger_board(set_pool, [waker, mage], interactive=(0,))

    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert game.pending_choices_of("loyalty_recipient", 0)
    assert game.confirm_loyalty_recipient(0, game.permanent_id_of(waker))
    assert (_loyalty(waker), _loyalty(mage)) == (5, 2)


def test_the_loyalty_recipient_answer_is_rechecked(set_pool):
    """The offered list is a hint and the engine is the check: a seat naming a
    planeswalker outside the phrase is refused and still owes the prompt."""
    waker = _scrounger_walker(set_pool, "Liliana, Waker of the Dead")
    mage = _scrounger_walker(set_pool, "Liliana, Death Mage")
    garruk = _scrounger_walker(set_pool, "Garruk, Unleashed")
    game = _scrounger_board(set_pool, [waker, mage, garruk], interactive=(0,))

    game.resolve_end_step(0)
    game._settle()
    game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert not game.confirm_loyalty_recipient(0, game.permanent_id_of(garruk))
    assert _loyalty(garruk) == 4
    assert game.pending_choices_of("loyalty_recipient", 0)


def test_a_non_interactive_seat_feeds_the_liliana_closest_to_dying(set_pool):
    """The stated policy, not a valuation: fewest loyalty counters, ties by
    battlefield scan order. Loyalty is a planeswalker's life total (CR 306.5c)
    and CR 704.5i bins one at zero."""
    waker = _scrounger_walker(set_pool, "Liliana, Waker of the Dead", loyalty=4)
    mage = _scrounger_walker(set_pool, "Liliana, Death Mage", loyalty=2)
    _end_step(_scrounger_board(set_pool, [waker, mage]))

    assert (_loyalty(waker), _loyalty(mage)) == (4, 3)
