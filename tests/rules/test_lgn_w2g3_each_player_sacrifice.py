""""Each player sacrifices …" is one round: chosen in turn order, done together.

CR 101.4's own example is this sentence: "A card reads 'Each player
sacrifices a creature.' First, the active player chooses a creature they
control. Then each of the nonactive players, in turn order, chooses a creature
they control. Then all creatures chosen this way are sacrificed
simultaneously." And CR 101.4b: a player knows the choices made by the
previous players.

``sacrifice_matching_permanent`` with ``who`` each_player / each_opponent
armed every seat's prompt at once, in *seat* order, and each answer
sacrificed on the spot — so the nonactive player was asked first whenever the
active player was not seat 0, and an interactive later seat chose blind. The
round is now ``resumption.ask_in_turn_order`` over a batch the round's last
step performs (``SacrificeChoicesMixin.finish_sacrifice_batch``). The
measurement is ``scratch/lgn/w1g7/sac_census.py`` (18 cards).
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import _mk_creature_card, resolve_stack


def _table(seats: int, *, active: int, interactive=()) -> Game:
    game = Game(players=[PlayerState(name=f"P{i}") for i in range(seats)])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = active
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _owed(game: Game) -> list:
    return [(c.kind, c.player_index) for c in game.pending_choices]


def _cast_and_pass(game: Game, seat: int, name: str) -> str:
    """Cast *name* from *seat*'s hand and let every player pass over it —
    the priority path a person's table takes (``pause_for_choices``)."""
    game.start_priority_window(seat)
    assert game.queue_from_hand(seat, name).supported
    result = ""
    for _ in range(len(game.players)):
        result = game.pass_priority(game.priority_player_index)
    return result


@pytest.mark.cr("101.4", "101.4b")
def test_the_active_player_chooses_first_and_nothing_goes_until_the_last_choice(set_pool):
    """Seat 1's turn, both seats people: seat 1 is asked first, seat 0 only
    once seat 1 has answered — and seat 1's creature is still on the
    battlefield (chosen, publicly, not yet sacrificed) while seat 0 decides.
    Then both go, and only then does Innocent Blood leave the stack."""
    game = _table(2, active=1, interactive={0, 1})
    elves = _put(game, 0, _mk_creature_card("Elves", 1, 1))
    giant = _put(game, 0, _mk_creature_card("Giant", 3, 3))
    bear = _put(game, 1, _mk_creature_card("Bear", 2, 2))
    _put(game, 1, _mk_creature_card("Wurm", 6, 4))
    resolve_stack(game)
    game.players[1].hand.append(set_pool("ODY")["Innocent Blood"])

    assert _cast_and_pass(game, 1, "Innocent Blood") == "awaiting_choice"
    assert _owed(game) == [("sacrifice", 1)], "the active player chooses first"

    # By stable id — the prompt's id form.
    assert game.confirm_sacrifice(1, permanent_ids=[bear.permanent_id])
    assert _owed(game) == [("sacrifice", 0)], "then the next player in turn order"
    assert game.is_on_battlefield(bear), "chosen, not yet sacrificed (CR 101.4)"
    assert "P1 chose Bear to sacrifice (Innocent Blood)" in game.log, (
        "CR 101.4b: the next chooser knows the choice"
    )
    assert [item.card.name for item in game.stack] == ["Innocent Blood"]

    assert game.confirm_sacrifice(0, [game.battlefield_index_of(elves)])
    assert not game.is_on_battlefield(bear) and not game.is_on_battlefield(elves)
    assert game.is_on_battlefield(giant)
    assert not game.stack, "the round's last answer finishes the resolution"
    assert [c.name for c in game.players[1].graveyard] == ["Bear", "Innocent Blood"]


@pytest.mark.cr("101.4")
def test_seats_nobody_asks_choose_in_turn_order_too(set_pool):
    """Headless and AI play run straight through, in the same order: the
    active player's choice is said first, and both sacrifices follow it."""
    game = _table(2, active=1)
    _put(game, 0, _mk_creature_card("Elves", 1, 1))
    _put(game, 1, _mk_creature_card("Bear", 2, 2))
    resolve_stack(game)
    game.players[1].hand.append(set_pool("ODY")["Innocent Blood"])

    assert game.cast_from_hand(1, "Innocent Blood").supported
    resolve_stack(game)

    said = [line for line in game.log if "(Innocent Blood)" in line]
    assert said == [
        "P1 chose Bear to sacrifice (Innocent Blood)",
        "P0 chose Elves to sacrifice (Innocent Blood)",
        "P1 sacrificed Bear (Innocent Blood)",
        "P0 sacrificed Elves (Innocent Blood)",
    ]
    assert not list(game.controlled_by(0)) and not list(game.controlled_by(1))


@pytest.mark.cr("101.4")
def test_three_seats_are_asked_from_the_active_player_round_the_table(set_pool):
    """Seat 2's turn at a three-seat table: 2, then 0, then 1 — turn order
    from the active player, never seat order."""
    game = _table(3, active=2, interactive={0, 1, 2})
    for seat in range(3):
        _put(game, seat, _mk_creature_card(f"Bear{seat}", 2, 2))
    resolve_stack(game)
    game.players[2].hand.append(set_pool("ODY")["Innocent Blood"])

    assert _cast_and_pass(game, 2, "Innocent Blood") == "awaiting_choice"
    asked = []
    while game.pending_choices:
        (choice,) = game.pending_choices
        asked.append(choice.player_index)
        assert game.confirm_sacrifice(choice.player_index, [0])
    assert asked == [2, 0, 1]
    assert all(not list(game.controlled_by(seat)) for seat in range(3))


@pytest.mark.cr("609.3", "101.4")
def test_a_player_short_of_the_count_sacrifices_what_they_have(set_pool):
    """"Each player sacrifices four lands" (Wildfire) over a seat holding
    three: that seat sacrifices the three (CR 609.3, as much as possible). It
    used to sacrifice none — the count was read as indivisible, which is
    Infernal Denizen's "sacrifice two Swamps. If you can't" and not this
    sentence's — while the other seat gave up four."""
    game = _table(2, active=0)
    mountain = set_pool("USG")["Mountain"]
    for seat, held in ((0, 3), (1, 5)):
        for _ in range(held):
            _put(game, seat, mountain)
    resolve_stack(game)
    game.players[0].hand.append(set_pool("USG")["Wildfire"])

    assert game.cast_from_hand(0, "Wildfire").supported
    resolve_stack(game)

    lands = [
        sum(1 for perm in game.controlled_by(seat) if perm.has_type("land"))
        for seat in (0, 1)
    ]
    assert lands == [0, 1]


@pytest.mark.cr("101.4")
def test_a_stale_or_foreign_id_is_refused_and_the_prompt_stays(set_pool):
    """The id form answers by object (CR 400.7): an id naming another seat's
    permanent, or nothing at all, is refused and the seat still owes it."""
    game = _table(2, active=0, interactive={0, 1})
    mine = _put(game, 0, _mk_creature_card("Elves", 1, 1))
    theirs = _put(game, 1, _mk_creature_card("Bear", 2, 2))
    resolve_stack(game)
    game.players[0].hand.append(set_pool("ODY")["Innocent Blood"])

    assert _cast_and_pass(game, 0, "Innocent Blood") == "awaiting_choice"
    assert not game.confirm_sacrifice(0, permanent_ids=[theirs.permanent_id])
    assert not game.confirm_sacrifice(0, permanent_ids=[987654])
    assert not game.confirm_sacrifice(0, permanent_ids=[mine.permanent_id, mine.permanent_id])
    assert _owed(game) == [("sacrifice", 0)]
    assert game.confirm_sacrifice(0, permanent_ids=[mine.permanent_id])
    assert _owed(game) == [("sacrifice", 1)]


@pytest.mark.cr("101.4", "101.4b")
def test_cataclysm_asks_the_current_player_first_and_the_other_after(set_pool):
    """Known gap "A keep batch asks every seat at once": Cataclysm's ruling
    (2004-10-04) — "The current player makes their choices before the other
    player" — on a table where the current player is seat 1. Seat 0 is asked
    only once seat 1 has chosen, and nothing moves until seat 0 has."""
    game = _table(2, active=1, interactive={0, 1})
    lea = set_pool("LEA")
    mine = [_put(game, 0, lea[n]) for n in ("Grizzly Bears", "Forest", "Forest")]
    theirs = [_put(game, 1, lea[n]) for n in ("Hill Giant", "Savannah Lions", "Mountain")]
    resolve_stack(game)
    game.players[1].hand.append(set_pool("EXO")["Cataclysm"])

    assert _cast_and_pass(game, 1, "Cataclysm") == "awaiting_choice"
    assert _owed(game) == [("keep_permanents", 1)]
    assert game.confirm_keep_permanents(
        1, [theirs[0].permanent_id, theirs[2].permanent_id]
    )
    assert _owed(game) == [("keep_permanents", 0)]
    assert game.is_on_battlefield(theirs[1]), "held until the last choice"
    assert game.confirm_keep_permanents(0, [mine[0].permanent_id, mine[1].permanent_id])
    assert not game.is_on_battlefield(theirs[1]) and not game.is_on_battlefield(mine[2])
    assert not game.stack
