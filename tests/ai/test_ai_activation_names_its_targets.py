"""The AI's activation chooser names every target its ability owes.

``ai_abilities.choose_activation_action`` named a battlefield target and nothing
else. Two announcements went out short and were answered by the engine instead
of by the seat:

* a **card in a graveyard** (CR 115.1c). Scavenging Ooze's "{G}: Exile target
  card from a graveyard" was activated naming none — 4 of 391 activations in
  sixty simulated games — and resolved on whatever the handler found. The
  engine now answers a bare announcement with a stated default (the picker's
  first entry), which is a default for a script and not a seat's choice;
* a **printed count**. "{T}: Untap two target lands" (Argothian Elder) was
  proposed naming one land, which the engine accepted and which it now
  refuses (CR 601.2c: two means two).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.models import Permanent
from tests.helpers import resolve_stack


def _board(catalog_by_name, mine, theirs=(), *, seat=0):
    boards = [
        [Permanent(card=catalog_by_name[name]) for name in mine],
        [Permanent(card=catalog_by_name[name]) for name in theirs],
    ]
    if seat == 1:
        boards.reverse()
    game = Game(players=[
        PlayerState(name="A", battlefield=boards[0], library=[catalog_by_name["Island"]] * 8),
        PlayerState(name="B", battlefield=boards[1], library=[catalog_by_name["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.start_turn(seat)
    game._sync_control()
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _activate(game, seat, action):
    return game.activate_permanent_ability(
        seat, action.permanent_name,
        target_player_index=action.target_player_index,
        permanent_index=action.permanent_index,
        target_permanent_index=action.target_permanent_index,
        target_role_refs=action.target_role_refs,
    )


def test_scavenging_ooze_names_the_card_it_exiles(catalog_by_name):
    """An exile is aimed at the opposing pile, and within it at the card with
    the greatest mana value — here the creature card, which is also what the
    Ooze is paid for."""
    game = _board(catalog_by_name, ["Scavenging Ooze"])
    game.players[0].graveyard.extend(
        catalog_by_name[name] for name in ("Shivan Dragon", "Island")
    )
    game.players[1].graveyard.extend(
        catalog_by_name[name] for name in ("Island", "Hill Giant", "Lightning Bolt")
    )

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Scavenging Ooze"
    assert (action.target_player_index, action.target_permanent_index) == (1, 1)

    ooze = list(game.controlled_by(0))[0]
    assert _activate(game, 0, action).supported
    resolve_stack(game)

    assert [card.name for card in game.players[1].exile] == ["Hill Giant"]
    assert [card.name for card in game.players[1].graveyard] == ["Island", "Lightning Bolt"]
    assert [card.name for card in game.players[0].graveyard] == ["Shivan Dragon", "Island"]
    assert ooze.effective_power == 3 and game.players[0].life == 21


def test_scavenging_ooze_names_a_card_from_either_seat(catalog_by_name):
    """…and the same from the other chair: the choice is "the opposing pile",
    not "seat 1's"."""
    game = _board(catalog_by_name, ["Scavenging Ooze"], seat=1)
    game.players[0].graveyard.append(catalog_by_name["Hill Giant"])
    game.players[1].graveyard.append(catalog_by_name["Shivan Dragon"])

    action = choose_activation_action(game, 1)

    assert action is not None
    assert (action.target_player_index, action.target_permanent_index) == (0, 0)


def test_scavenging_ooze_is_not_proposed_at_empty_graveyards(catalog_by_name):
    game = _board(catalog_by_name, ["Scavenging Ooze"])

    assert choose_activation_action(game, 0) is None


def test_argothian_elder_names_both_lands(catalog_by_name):
    game = _board(catalog_by_name, ["Argothian Elder", "Forest", "Forest", "Forest"])
    elder, *forests = list(game.controlled_by(0))
    for forest in forests:
        forest.tapped = True

    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Argothian Elder"
    assert isinstance(action.target_permanent_index, list)
    assert len(set(action.target_permanent_index)) == 2

    assert _activate(game, 0, action).supported
    resolve_stack(game)

    assert elder.tapped
    assert sorted(forest.tapped for forest in forests) == [False, False, True]


def test_argothian_elder_is_not_proposed_with_one_land_to_name(catalog_by_name):
    """Fewer legal targets than the count is no announcement at all, and
    proposing it would be a refused activation every turn."""
    game = _board(catalog_by_name, ["Argothian Elder", "Forest"])

    assert choose_activation_action(game, 0) is None
