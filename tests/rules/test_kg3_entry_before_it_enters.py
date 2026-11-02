"""CR 614.12a: an "as it enters" choice is made before the permanent enters.

"If a replacement effect that modifies how a permanent enters the battlefield
requires a choice, that choice is made before the permanent enters the
battlefield." The engine performed the entry state with the permanent already
on the battlefield: a person's Ward Sliver sat there with a provisional colour
while its prompt was open, every Sliver had protection from it, and Soul Warden
("whenever another creature enters") had already gained its life.

Now the entry state is performed with the permanent in no zone, and at a table
that holds for answers an entry that asks a question waits on its way until the
last answer (``engine/entry_awaiting.py``); the answer completes it, then the
held spell is released. These drive the roads one at a time, as an interactive
seat and as a seat nobody asks.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_C = {card.name: card for card in load_catalog()}


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_C[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(hand=(), mine=(), theirs=(), *, graveyard=(), interactive=True, seats=2):
    lands = [_permanent(n) for n in ("Plains", "Island", "Swamp", "Mountain", "Forest")]
    players = [
        PlayerState(
            name="Human", hand=[_C[n] for n in hand], graveyard=[_C[n] for n in graveyard],
            library=[_C["Forest"]] * 10, battlefield=[*lands, *(_permanent(n) for n in mine)],
        ),
        PlayerState(
            name="AI", library=[_C["Forest"]] * 10,
            battlefield=[_permanent(n) for n in theirs],
        ),
    ]
    for extra in range(2, seats):
        players.append(PlayerState(name=f"P{extra + 1}", library=[_C["Forest"]] * 10))
    game = Game(players=players)
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game._sync_control()
    return game


def _cast(game: Game, name: str, **kwargs) -> None:
    assert game.queue_from_hand(0, name, **kwargs).supported, name
    for _ in range(5):
        if not game.stack or game.waiting_prompt() is not None:
            return
        game.resolve_top_of_stack(pause_for_choices=game.holds_for_answers())


def _named(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _warden_triggered(game: Game, life_before: int) -> bool:
    return (
        any(item.card.name == "Soul Warden" for item in game.stack)
        or game.players[1].life > life_before
    )


@pytest.mark.cr("614.12a", "603.6a")
def test_a_persons_colour_is_chosen_before_the_sliver_enters_and_soul_warden_sees_it_after():
    game = _table(hand=["Ward Sliver"], mine=["Plated Sliver"], theirs=["Soul Warden"])
    _cast(game, "Ward Sliver")

    prompt = game.waiting_prompt()
    assert prompt is not None and prompt.kind == "enter_choice"
    ward = prompt.data["permanent"]
    plated = _named(game, 0, "Plated Sliver")
    # On its way: on no battlefield, its spell still on the stack, nothing
    # recorded, nothing protected, and no "enters" trigger yet.
    assert not game.is_on_battlefield(ward) and game.entry_is_awaited(ward)
    assert [item.card.name for item in game.stack] == ["Ward Sliver"]
    assert "chosen_color" not in ward.metadata
    assert not game._protection_colors(plated)
    assert not _warden_triggered(game, 20)
    assert not any("put Ward Sliver onto battlefield" in line for line in game.log)

    assert game.confirm_enter_choice(0, mana_color="U")

    assert game.is_on_battlefield(ward) and ward.metadata["chosen_color"] == "U"
    assert {"U", "blue"} & game._protection_colors(plated)
    assert {"U", "blue"} & game._protection_colors(ward)
    assert not game.entries_in_progress
    # Soul Warden saw it enter — after the choice, never before.
    assert any(item.card.name == "Soul Warden" for item in game.stack)
    chose = game.log.index("Ward Sliver: chose U")
    entered = game.log.index("Human put Ward Sliver onto battlefield")
    finished = game.log.index("Ward Sliver finished resolving")
    assert chose < entered < finished


@pytest.mark.cr("614.12a")
def test_a_seat_nobody_asks_enters_at_once_with_its_choice_made():
    """No change for a seat nobody asks: its default is its answer, taken as
    the prompt is armed, and the permanent enters within the resolution."""
    game = _table(hand=["Ward Sliver"], mine=["Plated Sliver"], theirs=["Soul Warden"],
                  interactive=False)
    _cast(game, "Ward Sliver")
    ward = _named(game, 0, "Ward Sliver")
    assert game.waiting_prompt() is None and not game.entries_in_progress
    assert ward.metadata.get("chosen_color")
    assert _warden_triggered(game, 20)


@pytest.mark.cr("614.12a", "608.2n")
def test_a_reanimated_shapeshifter_enters_at_the_answer_and_the_spell_finishes_after_it():
    """A non-cast road: Resurrection returns Shapeshifter, whose number is a
    person's choice. The creature waits on its way and the spell waits on the
    stack — its trip to the graveyard is its last step (CR 608.2n), behind an
    entry that has not finished."""
    game = _table(hand=["Resurrection"], graveyard=["Shapeshifter"], theirs=["Soul Warden"])
    _cast(game, "Resurrection", target_player_index=0, target_permanent_index=0)

    prompt = game.waiting_prompt()
    assert prompt is not None and prompt.kind == "number_choice"
    shifter = prompt.data["permanent"]
    assert not game.is_on_battlefield(shifter)
    assert "chosen_number" not in shifter.metadata
    assert [item.card.name for item in game.stack] == ["Resurrection"]
    assert [card.name for card in game.players[0].graveyard] == []
    assert not _warden_triggered(game, 20)

    assert game.confirm_number_choice(0, 6)

    assert game.is_on_battlefield(shifter) and shifter.metadata["chosen_number"] == 6
    assert (shifter.effective_power, shifter.effective_toughness) == (6, 1)
    assert [card.name for card in game.players[0].graveyard] == ["Resurrection"]
    assert not any(item.card.name == "Resurrection" for item in game.stack)
    assert _warden_triggered(game, 20)


@pytest.mark.cr("614.12a", "702.38a")
def test_amplifys_counters_are_placed_on_the_way_under_its_controllers_replacements():
    """Part 5: the counters a revealed card buys go on while the creature is on
    its way, through ``place_plus1_counters`` — and the controller's CR 614
    replacement on them applies (Conclave Mentor: that many plus one), which
    needs the seat it enters under while it is on no battlefield."""
    game = _table(hand=["Canopy Crawler", "Krosan Tusker"], mine=["Conclave Mentor"],
                  theirs=["Soul Warden"])
    _cast(game, "Canopy Crawler")

    prompt = game.waiting_prompt()
    assert prompt is not None and prompt.kind == "entry_reveal"
    crawler = prompt.data["permanent"]
    assert not game.is_on_battlefield(crawler)
    assert game.controller_index_of(crawler) == 0
    assert not _warden_triggered(game, 20)

    tusker = next(i for i, card in enumerate(game.players[0].hand) if card.name == "Krosan Tusker")
    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[tusker])

    assert game.is_on_battlefield(crawler)
    # Amplify 1, one card revealed: one counter, plus Conclave Mentor's one —
    # a 2/2 entering as a 4/4.
    assert (crawler.effective_power, crawler.effective_toughness) == (4, 4)
    assert _warden_triggered(game, 20)


@pytest.mark.cr("614.12a", "614.13a")
def test_a_played_lands_toll_is_paid_before_it_enters():
    """A land play (CR 305.1) down the same road: Balduvian Trading Post's
    toll is a person's sacrifice, so the land waits on its way, offering only
    the Mountain already there, and the play's bookkeeping follows the entry."""
    game = _table(hand=["Balduvian Trading Post"])
    mountain = _named(game, 0, "Mountain")
    game.queue_from_hand(0, "Balduvian Trading Post")

    offered = game.pending_sacrifice_state()
    assert offered is not None
    post = next(record.permanent for record in game.entries_in_progress)
    assert post.card.name == "Balduvian Trading Post" and not game.is_on_battlefield(post)
    assert [game.permanent_at(0, i).card.name for i in offered["valid_indices"]] == ["Mountain"]

    assert game.confirm_sacrifice(0, permanent_ids=[mountain.permanent_id])
    assert game.is_on_battlefield(post) and not game.is_on_battlefield(mountain)
    assert any("put Balduvian Trading Post onto battlefield" in line for line in game.log)


@pytest.mark.cr("614.12a")
def test_a_persons_prompt_answered_by_default_writes_the_default_it_carries():
    """Nothing is stamped for a person, so a person's prompt answered by
    default (a drain, a seat the table stopped waiting for) writes the default
    the prompt carries — through the resolver an answer goes through."""
    game = _table(hand=["Psychic Allergy"], theirs=["Grizzly Bears"])
    _cast(game, "Psychic Allergy")
    prompt = game.waiting_prompt()
    allergy = prompt.data["permanent"]
    default = prompt.data["default_color"]
    assert "chosen_color" not in allergy.metadata
    game.take_choice_default(prompt)
    assert game.is_on_battlefield(allergy) and allergy.metadata["chosen_color"] == default

    game = _table(hand=["Primal Clay"])
    _cast(game, "Primal Clay")
    prompt = game.waiting_prompt()
    clay = prompt.data["permanent"]
    assert prompt.kind == "body_choice" and "chosen_body" not in clay.metadata
    game.take_choice_default(prompt)
    assert game.is_on_battlefield(clay)
    assert (clay.effective_power, clay.effective_toughness) == (3, 3)


@pytest.mark.cr("614.12a", "700.2e")
def test_an_entry_waits_for_both_answers_when_the_controller_names_who_chooses():
    """Callous Oppressor at three seats: the controller names which opponent
    chooses, and that opponent then chooses the type. The creature enters only
    after the second answer — the first answer arms the second prompt, which
    keeps it on its way."""
    game = _table(hand=["Callous Oppressor"], theirs=["Grizzly Bears"], seats=3)
    game.interactive_seats = {0, 2}
    _cast(game, "Callous Oppressor")
    first = game.waiting_prompt()
    oppressor = first.data["permanent"]
    assert first.player_index == 0 and first.data.get("then_opponent_chooses_creature_type")
    assert game.confirm_enter_choice(0, opponent_index=2)
    second = game.waiting_prompt()
    assert second is not None and second.player_index == 2
    assert not game.is_on_battlefield(oppressor) and game.entry_is_awaited(oppressor)
    assert "chosen_creature_type" not in oppressor.metadata
    assert game.confirm_enter_choice(2, creature_type="goblin")
    assert game.is_on_battlefield(oppressor)
    assert oppressor.metadata["chosen_creature_type"] == "goblin"
