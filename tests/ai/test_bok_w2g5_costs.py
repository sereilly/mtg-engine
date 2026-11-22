"""The AI pays Betrayers of Kamigawa's prices that are not the mana cost
(BOK wave 2, W2G5): an offering (CR 702.48, `engine/ai_offering.py`), a Shoal's
pitch naming X (CR 118.9 / 107.3a, `engine/ai_pitch.py`), Kentaro's granted
{X}, a splice cost that is not mana (CR 702.47a, `engine/ai_splice_prices.py`)
and "a source of your choice" (CR 609.7a, `engine/ai_chosen_source.py`).

Wave 1 measured every one of these as cast and resolved with no refusal — and
never with the price: each Patron and Shoal was hard-cast or held, and each
splice card whose cost is not mana was cast alone.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, ai_simulator
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import (choose_cast_action, choose_combat_instant_cast_action,
                              holds_an_instant_it_could_pay_for)
from engine.ai_prompt_picks import held_worth
from engine.ai_splice_prices import splice_price_answer
from engine.ai_valuation import OFFER_REDUCES, cast_offers
from engine.models import Permanent
from engine.splice import splice_offer
from tests.helpers import _nosick, settle


@pytest.fixture
def _w2g5_cards(set_pool):
    return {**set_pool("LEA"), **set_pool("CHK"), **set_pool("BOK")}


def _w2g5_table(cards, hand, mine, *, theirs=(), graveyard=(), sick=()) -> Game:
    """Seat 0's precombat main phase, mana enforced; *sick* names the
    permanents of seat 0 that arrived this turn."""
    me = PlayerState(
        name="Me", hand=[cards[name] for name in hand],
        graveyard=[cards[name] for name in graveyard],
        library=[cards["Plains"]] * 10,
    )
    you = PlayerState(name="You", library=[cards["Plains"]] * 10)
    game = Game(players=[me, you], enforce_mana_costs=True)
    game.turn = 5
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=cards[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            if not (seat == 0 and name in sick):
                _nosick(permanent)
    game._sync_control()
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def _w2g5_carry_out(game: Game, action, seat: int = 0):
    """Every executor's two lines: tap the plan, announce everything."""
    tap_planned_lands(game, seat, action)
    result = game.cast_from_hand(seat, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    settle(game)
    return result


def _names(cards) -> list[str]:
    return sorted(card.name for card in cards)


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


# --- Offering (CR 702.48) ---------------------------------------------------


def test_each_patrons_offering_is_its_own_class(_w2g5_cards):
    """The five Patrons' offerings buy the same spell for less and at instant
    speed — not a different spell (Undergrowth's class), which the policy
    declines."""
    patrons = [name for name in _w2g5_cards if name.startswith("Patron of the ")]
    assert len(patrons) == 5
    for name in patrons:
        assert [offer.buys for offer in cast_offers(_w2g5_cards[name])] == [OFFER_REDUCES], name


def test_an_offering_pays_for_a_patron_the_lands_cannot(_w2g5_cards):
    """Patron of the Kitsune costs {4}{W}{W}; three Plains pay {2}{W} once a
    Kitsune Blademaster ({2}{W}) is offered (CR 702.48c), so the seat offers
    it rather than holding the Patron."""
    game = _w2g5_table(
        _w2g5_cards, ["Patron of the Kitsune"], ["Plains"] * 3 + ["Kitsune Blademaster"],
    )
    fox = _on(game, 0, "Kitsune Blademaster")

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Patron of the Kitsune"
    assert action.optional_cost_payments == {"sacrifice a fox": 1}
    assert action.cost_permanent_ids == [fox.permanent_id]
    _w2g5_carry_out(game, action)
    assert _on(game, 0, "Patron of the Kitsune") is not None
    assert _names(game.players[0].graveyard) == ["Kitsune Blademaster"]
    assert sum(1 for p in game.controlled_by(0) if p.card.name == "Plains" and not p.tapped) == 0
    assert any("costs {2}{W} less to cast (offering Kitsune Blademaster)" in line for line in game.log)


def test_no_offering_where_the_mana_cost_is_paid(_w2g5_cards):
    """Six Plains pay the Patron as printed in the seat's own main phase:
    the Fox is kept — what the offering would save is mana the seat has."""
    game = _w2g5_table(
        _w2g5_cards, ["Patron of the Kitsune"], ["Plains"] * 6 + ["Kitsune Blademaster"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Patron of the Kitsune"
    assert not action.optional_cost_payments
    _w2g5_carry_out(game, action)
    assert _on(game, 0, "Kitsune Blademaster") is not None


def test_the_fox_offered_is_one_whose_reduction_pays(_w2g5_cards):
    """Three Plains, a Kitsune Diviner ({W}) and a Kitsune Blademaster
    ({2}{W}): the Diviner is cheaper to lose, but {3}{W}{W} is still more than
    three lands — so the Blademaster is the one offered."""
    game = _w2g5_table(
        _w2g5_cards, ["Patron of the Kitsune"],
        ["Plains"] * 3 + ["Kitsune Diviner", "Kitsune Blademaster"],
    )
    blademaster = _on(game, 0, "Kitsune Blademaster")

    action = choose_cast_action(game, 0)

    assert action is not None and action.cost_permanent_ids == [blademaster.permanent_id]
    _w2g5_carry_out(game, action)
    assert _on(game, 0, "Kitsune Diviner") is not None
    assert _names(game.players[0].graveyard) == ["Kitsune Blademaster"]


def _w2g5_window_table(cards, *, hands, boards, active):
    """A two-seat table as `run_ai_simulation` builds one, its priority
    answered by the simulator's own driver, *active*'s turn."""
    players = [
        PlayerState(name=name, hand=[cards[card] for card in hand],
                    library=[cards["Plains"]] * 8)
        for name, hand in zip(("AI-A", "AI-B"), hands)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate(boards):
        for name in board:
            permanent = Permanent(card=cards[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    return game, report


def test_a_patron_is_flashed_in_at_the_opponents_end_step(_w2g5_cards):
    """CR 601.3c: the offering lets the Patron be cast any time an instant
    could — and only with it paid (CR 601.2e). At the other seat's end step,
    with six untapped Plains (the printed cost payable), the seat casts the
    Patron offering its Fox: the window exists only with the offering."""
    game, report = _w2g5_window_table(
        _w2g5_cards, hands=((), ("Patron of the Kitsune",)),
        boards=(("Mountain",), ["Plains"] * 6 + ["Kitsune Blademaster"]), active=0,
    )
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()
    settle(game)

    assert _on(game, 1, "Patron of the Kitsune") is not None
    assert _names(game.players[1].graveyard) == ["Kitsune Blademaster"]
    assert report.casts_on_opponents_turn == 1
    assert report.prices_paid["offering"] == 1
    assert report.refused_instant_casts == {}


def test_a_patron_is_flashed_in_to_block(_w2g5_cards):
    """The offering's other window: AI-A attacks with an Earth Elemental
    (4/5), and AI-B — three Plains and a Kitsune Blademaster, whose 3/3 first
    strike block would not kill it, the Patron of the Kitsune in hand — casts
    the Patron in the declare-attackers step, offering the Fox (the cast exists
    only with it: the moment, and the {2}{W} it takes off), and blocks with
    the 5/6: the Elemental dies and no damage reaches AI-B."""
    from engine.ai_combat import run_ai_combat_phase

    game, report = _w2g5_window_table(
        _w2g5_cards, hands=((), ("Patron of the Kitsune",)),
        boards=(("Earth Elemental",), ["Plains"] * 3 + ["Kitsune Blademaster"]), active=0,
    )
    game._set_phase_and_step("precombat_main", "precombat_main")
    while game.current_step != "declare_attackers":
        game.advance_combat_phase()
    elemental = _on(game, 0, "Earth Elemental")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(elemental)], defending_player_index=1,
    )
    assert ok, why

    run_ai_combat_phase(game, 0)

    assert _on(game, 1, "Patron of the Kitsune") is not None
    assert _on(game, 0, "Earth Elemental") is None
    assert game.players[1].life == 20
    assert report.casts_before_blocks == 1
    assert report.prices_paid["offering"] == 1


def test_three_plains_and_a_fox_are_a_cast_the_instant_chooser_is_asked(_w2g5_cards):
    """The cheap gate in front of the instant-speed chooser
    (`holds_an_instant_it_could_pay_for`) counts the reduced price: three
    Plains do not pay {4}{W}{W}, the Fox's offering does."""
    game, _report = _w2g5_window_table(
        _w2g5_cards, hands=((), ("Patron of the Kitsune",)),
        boards=(("Mountain",), ["Plains"] * 3 + ["Kitsune Blademaster"]), active=0,
    )
    game._set_phase_and_step("ending", "end")
    assert holds_an_instant_it_could_pay_for(game, 1)
    action = choose_combat_instant_cast_action(game, 1)
    assert action is not None and action.optional_cost_payments == {"sacrifice a fox": 1}


# --- The Shoals' pitch (CR 118.9, 107.3a) -----------------------------------


def test_a_shoal_is_pitched_with_no_land_to_pay_for_it(_w2g5_cards):
    """No lands at all, and Sickening Shoal kills the Grizzly Bears by
    exiling a black card of mana value 2: the card names X (CR 107.3a)."""
    game = _w2g5_table(
        _w2g5_cards, ["Sickening Shoal", "Drudge Skeletons"], [], theirs=["Grizzly Bears"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sickening Shoal"
    assert action.alternative_cost and action.alternative_cost_hand_index == 1
    assert action.x_value == 2
    _w2g5_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert _names(game.players[0].exile) == ["Drudge Skeletons"]


def test_the_x_pitched_is_the_one_that_does_the_job(_w2g5_cards):
    """Against a 3/3, a black two-drop pitched is −2/−2 and leaves nothing
    lasting; the three-drop is −3/−3 and kills. Each X the hand can name is a
    candidate of its own, and the rehearsal picks the one that kills."""
    game = _w2g5_table(
        _w2g5_cards, ["Sickening Shoal", "Drudge Skeletons", "Hypnotic Specter"], [],
        theirs=["Hill Giant"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sickening Shoal"
    assert action.alternative_cost_hand_index == 2 and action.x_value == 3
    _w2g5_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Hill Giant"]
    assert "Drudge Skeletons" in _names(game.players[0].hand)


def test_a_pitch_is_weighed_beside_a_mana_cost_the_lands_pay(_w2g5_cards):
    """Three Swamps pay {X}{B}{B} for X = 1 — −1/−1, nothing against a 3/3.
    The pitch is a different spell, not a cheaper one: X = 3 off the pitched
    Specter kills, and the seat pitches although its lands could pay."""
    game = _w2g5_table(
        _w2g5_cards, ["Sickening Shoal", "Hypnotic Specter"], ["Swamp"] * 3,
        theirs=["Hill Giant"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sickening Shoal"
    assert action.alternative_cost and action.x_value == 3
    _w2g5_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Hill Giant"]


def test_of_two_cards_of_one_x_the_one_least_worth_holding_is_pitched(_w2g5_cards):
    """Two black cards of mana value 2 name the same X; the one the seat
    holds for less (``ai_prompt_picks.held_worth``) is the one exiled."""
    game = _w2g5_table(
        _w2g5_cards, ["Sickening Shoal", "Drudge Skeletons", "Black Knight"], [],
        theirs=["Grizzly Bears"],
    )
    worth = {slot: held_worth(game, 0, game.players[0].hand[slot]) for slot in (1, 2)}
    assert worth[1] != worth[2]

    action = choose_cast_action(game, 0)

    assert action is not None and action.alternative_cost_hand_index == min(worth, key=worth.get)


def test_shining_shoal_names_the_bolt_and_sends_its_damage_back(_w2g5_cards):
    """CR 609.7a: the source is the caster's choice, announced with the cast.
    With an opposing Lightning Bolt aimed at its Grizzly Bears and no land,
    the seat pitches a white three-drop, names the Bolt as the source and the
    Hill Giant as the new recipient — and the Bears live while the Giant
    dies. Named nothing, the pool answered to any source."""
    game = _w2g5_table(
        _w2g5_cards, ["Shining Shoal", "Kitsune Blademaster"], ["Grizzly Bears"],
        theirs=["Mountain", "Hill Giant"],
    )
    game.start_turn(1)
    game._close_current_priority_step()
    game.players[1].hand.append(_w2g5_cards["Lightning Bolt"])
    bears = _on(game, 0, "Grizzly Bears")
    game.tap_land_for_mana(1, "Mountain", chosen_color="R")
    queued = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert queued.supported, queued.details

    action = choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.card_name == "Shining Shoal"
    assert action.chosen_source_stack_index == 0
    assert action.alternative_cost_hand_index == 1 and action.x_value == 3
    tap_planned_lands(game, 0, action)
    result = game.queue_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    settle(game)
    assert _on(game, 0, "Grizzly Bears") is not None
    assert _on(game, 1, "Hill Giant") is None
    assert any("the next 3 damage Lightning Bolt would deal" in line for line in game.log)


def test_kor_chant_names_the_bolt_as_its_source(set_pool):
    """The chosen-source chooser reads the cast spec, not the card: Kor Chant
    (Exodus) asks for "a source of your choice" too, and with an opposing
    Lightning Bolt aimed at the seat's Grizzly Bears it names the Bolt, so
    the Bears live and the other creature named takes the damage."""
    cards = {**set_pool("LEA"), **set_pool("EXO")}
    game = _w2g5_table(
        cards, ["Kor Chant"], ["Plains"] * 3 + ["Grizzly Bears"],
        theirs=["Mountain", "Hill Giant", "Grizzly Bears"],
    )
    game.start_turn(1)
    game._close_current_priority_step()
    game.players[1].hand.append(cards["Lightning Bolt"])
    bears = _on(game, 0, "Grizzly Bears")
    game.tap_land_for_mana(1, "Mountain", chosen_color="R")
    queued = game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_ids=[bears.permanent_id],
    )
    assert queued.supported, queued.details

    action = choose_combat_instant_cast_action(game, 0)

    assert action is not None and action.card_name == "Kor Chant"
    assert action.chosen_source_stack_index == 0
    tap_planned_lands(game, 0, action)
    result = game.queue_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    settle(game)
    assert bears in game.controlled_by(0)
    assert len(game.players[1].graveyard) == 2  # the Bolt, and the creature it hit


# --- Kentaro, the Smiling Cat ----------------------------------------------


def test_kentaros_x_pays_for_a_samurai_the_colours_cannot(_w2g5_cards):
    """"You may pay {X} rather than pay the mana cost for Samurai spells you
    cast" (X the spell's mana value, CR 107.3c): three Mountains cannot pay
    Kitsune Blademaster's {2}{W}, and pay its {3}."""
    game = _w2g5_table(
        _w2g5_cards, ["Kitsune Blademaster"], ["Mountain"] * 3 + ["Kentaro, the Smiling Cat"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Kitsune Blademaster"
    assert action.alternative_cost and len(action.land_tap_indices) == 3
    _w2g5_carry_out(game, action)
    assert _on(game, 0, "Kitsune Blademaster") is not None
    assert any("cast for its alternative cost (pay {3})" in line for line in game.log)


# --- Splice costs that are not mana (CR 702.47a) ----------------------------


def test_torrent_of_stone_is_spliced_for_two_spare_mountains(_w2g5_cards):
    """Eight Mountains, a Glacial Ray and a Torrent of Stone, against a Hill
    Giant and Grizzly Bears: Torrent cast with Glacial Ray spliced on would
    leave the Ray; here the seat holds two Torrents and splices the second onto
    the first, paying two Mountains it does not need — the lands the cast
    tapped first (their mana is spent either way)."""
    game = _w2g5_table(
        _w2g5_cards, ["Torrent of Stone", "Torrent of Stone"], ["Mountain"] * 8,
        theirs=["Hill Giant", "Grizzly Bears"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.splice_cards
    entry = action.splice_cards[0]
    tapped = {game.permanent_at(0, slot).permanent_id for slot in action.land_tap_indices}
    assert set(entry["cost_permanent_ids"]) <= tapped
    _w2g5_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears", "Hill Giant"]
    assert sum(1 for p in game.controlled_by(0) if p.card.name == "Mountain") == 6
    assert "Torrent of Stone" in _names(game.players[0].hand)


def test_horobis_whisper_exiles_the_graveyard_cards_least_worth_keeping(_w2g5_cards):
    """"Splice onto Arcane—Exile four cards from your graveyard": the four
    are named by ``graveyard_price_order``, so the Lightning Bolt (the dearest)
    stays, and the spliced text destroys the Hill Giant beside the Ray's two
    damage to the Bears."""
    game = _w2g5_table(
        _w2g5_cards, ["Glacial Ray", "Horobi's Whisper"], ["Mountain"] * 3 + ["Swamp"],
        theirs=["Grizzly Bears", "Hill Giant"],
        graveyard=["Lightning Bolt", "Mountain", "Forest", "Island", "Swamp"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Glacial Ray"
    assert action.splice_cards and sorted(action.splice_cards[0]["cost_graveyard_indices"]) == [1, 2, 3, 4]
    _w2g5_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears", "Hill Giant"]
    assert _names(game.players[0].graveyard) == ["Glacial Ray", "Lightning Bolt"]
    assert "Horobi's Whisper" in _names(game.players[0].hand)


def test_a_tap_price_takes_the_creature_that_could_not_attack(_w2g5_cards):
    """Hundred-Talon Strike's "Tap an untapped white creature you control":
    of two Savannah Lions, the one that arrived this turn (summoning sick, CR
    302.6) is the body the seat misses least."""
    game = _w2g5_table(
        _w2g5_cards, ["Glacial Ray", "Hundred-Talon Strike"],
        ["Mountain"] * 2 + ["Savannah Lions", "Savannah Lions"],
        theirs=["Grizzly Bears"], sick=("Savannah Lions",),
    )
    lions = [p for p in game.controlled_by(0) if p.card.name == "Savannah Lions"]
    # `sick` marked both; the second is made ready again.
    _nosick(lions[1])
    ray = game.players[0].hand[0]
    strike = game.players[0].hand[1]
    current = choose_cast_action(game, 0)
    assert current is not None

    answer = splice_price_answer(
        game, 0, ray, current, [], strike, splice_offer(strike.oracle_text), named=set(),
    )

    assert answer == {"cost_permanent_ids": [lions[0].permanent_id]}


def test_a_return_price_never_takes_the_creature_the_text_aims_at(_w2g5_cards):
    """Veil of Secrecy's text aims at the seat's own creature and its splice
    cost returns a blue creature it controls: with one blue creature, the
    only payer is the target, and that splice is not weighed (its target would
    leave as the cost is paid)."""
    game = _w2g5_table(
        _w2g5_cards, ["Glacial Ray", "Veil of Secrecy"],
        ["Mountain"] * 3 + ["Island", "Merfolk of the Pearl Trident"],
        theirs=["Grizzly Bears"],
    )

    action = choose_cast_action(game, 0)

    assert action is not None and not action.splice_cards
    _w2g5_carry_out(game, action)
    assert _on(game, 0, "Merfolk of the Pearl Trident") is not None


# --- In a game --------------------------------------------------------------


@pytest.mark.full
def test_seeded_bok_games_take_offerings_and_pitch_shoals():
    """Seeded AI games over Betrayers of Kamigawa with two Patrons, the
    Shoals of their colours and Fox and Goblin payers pinned: at least one
    offering is taken and at least one Shoal is pitched (a floor of one each,
    never how often), and nothing is refused or raises."""
    from engine.card_loader import manifest_set_path

    report = ai_simulator.run_ai_simulation(
        manifest_set_path("BOK", include_measured=True), games=2, seed=7, max_turns=9,
        required_cards=[
            "Patron of the Kitsune", "Patron of the Akki",
            "Kitsune Palliator", "Split-Tail Miko", "Akki Raider", "Goblin Cohort",
            "Blazing Shoal", "Shining Shoal",
        ],
    )

    assert report.prices_paid["offering"] >= 1, report.prices_paid
    assert report.prices_paid["pitch"] >= 1, report.prices_paid
    assert not report.refused_casts, report.refused_casts
    assert not report.refused_instant_casts, report.refused_instant_casts
    assert not report.rehearsals_raised, report.rehearsals_raised
