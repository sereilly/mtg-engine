"""The AI splices onto Arcane (CR 702.47a) — `engine/ai_splice.py`.

Until CHK's wave 2 no AI seat ever spliced: every splice card was cast alone,
spent, and never once added to the Arcane spell its seat was casting anyway.
A splice is weighed after the host's own candidate is built: each card
``splice.splice_candidates`` offers is added to the host's announcement, its
gained text aimed out of the engine's own list for that text, and the combined
cast rehearsed; it is kept only when it scores above the cast without it, with
mana no other spell in hand needs.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_casts import _priced_candidate
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import settle


@pytest.fixture
def _w2g2_cards(set_pool):
    return {**set_pool("LEA"), **set_pool("CHK")}


def _w2g2_table(cards, hand, lands, *, theirs=()) -> Game:
    me = PlayerState(
        name="Me",
        hand=[cards[name] for name in hand],
        battlefield=[Permanent(card=cards[name]) for name in lands],
        library=[cards["Island"]] * 10,
    )
    you = PlayerState(
        name="You",
        battlefield=[Permanent(card=cards[name]) for name in theirs],
        library=[cards["Island"]] * 10,
    )
    game = Game(players=[me, you], enforce_mana_costs=True)
    game._sync_control()
    game.turn = 5
    game.begin_turn_bookkeeping(0)
    game._enter_main_phase(precombat=True)
    return game


def _w2g2_carry_out(game: Game, action) -> None:
    """Every executor's two lines: tap the plan, announce everything."""
    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    settle(game)


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def test_the_ai_splices_glacial_ray_onto_an_arcane_spell_and_keeps_the_card(_w2g2_cards):
    """Reach Through Mists with Glacial Ray spliced on draws a card and kills
    the Bears — and Glacial Ray stays in hand for the next Arcane spell
    (CR 702.47a), where cast alone it would have been spent."""
    game = _w2g2_table(
        _w2g2_cards, ["Reach Through Mists", "Glacial Ray"],
        ["Island", "Mountain", "Mountain", "Mountain"], theirs=["Grizzly Bears"],
    )
    bears = game.players[1].battlefield[0]

    action = choose_cast_action(game, 0)

    assert action.card_name == "Reach Through Mists"
    assert action.splice_cards == [{
        "hand_index": 1, "target_player_index": 1,
        "target_permanent_ids": [bears.permanent_id],
    }]
    assert len(action.land_tap_indices) == 3  # {U} and the splice's {1}{R}
    _w2g2_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert "Glacial Ray" in _names(game.players[0].hand)
    assert len(game.players[0].hand) == 2  # Glacial Ray and the card drawn
    assert any("spliced Glacial Ray onto Reach Through Mists" in line for line in game.log)


def test_a_second_copy_is_spliced_at_the_other_creature(_w2g2_cards):
    """Two copies of one card may both be spliced (CR 702.47b), and the second
    is offered the creature the first does not hit — two Grizzly Bears are not
    one question once one of them is already named."""
    game = _w2g2_table(
        _w2g2_cards, ["Reach Through Mists", "Glacial Ray", "Glacial Ray"],
        ["Island", "Mountain", "Mountain", "Mountain", "Mountain"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    action = choose_cast_action(game, 0)

    assert action.card_name == "Reach Through Mists"
    assert [entry["hand_index"] for entry in action.splice_cards] == [1, 2]
    aimed = [entry["target_permanent_ids"][0] for entry in action.splice_cards]
    assert sorted(aimed) == sorted(p.permanent_id for p in game.players[1].battlefield)
    _w2g2_carry_out(game, action)
    assert _names(game.players[1].graveyard) == ["Grizzly Bears", "Grizzly Bears"]
    assert _names(game.players[0].hand).count("Glacial Ray") == 2


def test_no_splice_with_mana_another_spell_in_hand_needs(_w2g2_cards):
    """The splice's {1}{R} would leave Gray Ogre uncast this turn: Reach plus
    the Ogre fit four lands, Reach spliced plus the Ogre do not. The buyback
    rule, the spliced card set aside."""
    game = _w2g2_table(
        _w2g2_cards, ["Reach Through Mists", "Glacial Ray", "Gray Ogre"],
        ["Island", "Mountain", "Mountain", "Mountain"], theirs=["Grizzly Bears"],
    )
    reach = game.players[0].hand[0]

    candidate = _priced_candidate(game, 0, reach, 0)

    assert candidate is not None and candidate.splice_cards is None


def test_an_unaffordable_splice_is_not_announced(_w2g2_cards):
    """Two lands pay Glacial Ray or Reach, never Reach with the splice on top:
    the seat casts Glacial Ray itself."""
    game = _w2g2_table(
        _w2g2_cards, ["Reach Through Mists", "Glacial Ray"],
        ["Island", "Mountain"], theirs=["Grizzly Bears"],
    )
    reach = game.players[0].hand[0]

    assert _priced_candidate(game, 0, reach, 0).splice_cards is None
    action = choose_cast_action(game, 0)
    assert action.card_name == "Glacial Ray" and not action.splice_cards


def test_a_splice_whose_text_moves_nothing_lasting_is_not_taken(_w2g2_cards):
    """Desperate Ritual spliced adds {R}{R}{R} that empties at the end of the
    step: a text that leaves the board as it was is a splice cost paid for
    nothing, and the rehearsal says so."""
    game = _w2g2_table(
        _w2g2_cards, ["Reach Through Mists", "Desperate Ritual"],
        ["Island", "Mountain", "Mountain", "Mountain"],
    )
    reach = game.players[0].hand[0]

    assert _priced_candidate(game, 0, reach, 0).splice_cards is None


@pytest.mark.full
def test_the_ai_splices_in_a_seeded_game():
    """A seeded batch with splice cards and Arcane spells pinned into both
    decks: some card is spliced (a floor of one — the seed decides how often),
    no splice cast is refused and no rehearsal raises."""
    report = run_ai_simulation(
        manifest_set_path("CHK", include_measured=True),
        games=4, seed=11, max_turns=14,
        required_cards=(
            "Glacial Ray", "Lava Spike", "Unnatural Speed", "Crushing Pain",
            "Unearthly Blizzard", "Kodama's Might",
        ),
    )
    assert report.games_completed == report.games_requested
    assert sum(report.spliced_casts.values()) >= 1, report.spliced_casts
    spliced = [line for line in report.log_lines if "spliced]" in line]
    assert spliced, "the report counted a splice its log does not show"
    assert all(
        "-> resolved" in line or "-> queued" in line for line in spliced
    ), spliced
    assert not report.rehearsals_raised
