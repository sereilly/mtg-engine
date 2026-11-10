"""Under Worms of the Earth a land an effect would put onto the battlefield
stays where it is (CR 614.17; the card's ruling, 2004-10-04: "an effect that
'puts a land onto the battlefield' won't do anything, and the land will stay
where it is" — "You'll still do everything else the spell or ability tells
you to do, such as shuffle the library").

On round kg5's chain (e245e624c) the "can't" was asked at the battlefield
funnel, after each road had taken the card out of its zone: the land went to
no zone, and the road still logged it put onto the battlefield. One board per
road — the hand (Show and Tell's one event, Elvish Pioneer's pick), the
library (a search; Transmute Artifact's held find), the graveyard (Planar
Birth's sweep), a land played in a game with costs off — each driven with
Worms out and, as the reference that the road was exercised, without it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}


def _game(*, hand=(), opponent_hand=(), mine=(), theirs=(), graveyard=(),
          library=None, worms=True, interactive=False, mana=False) -> Game:
    game = Game(players=[
        PlayerState("P0", hand=[_POOL[n] for n in hand],
                    library=[_POOL[n] for n in (library or ["Island"] * 10)],
                    graveyard=[_POOL[n] for n in graveyard]),
        PlayerState("P1", hand=[_POOL[n] for n in opponent_hand],
                    library=[_POOL["Island"]] * 10),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = {0} if interactive else set()
    theirs = (*theirs, *(("Worms of the Earth",) if worms else ()))
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.pending_choices.clear()
    game.start_turn(0)
    settle(game)
    return game


def _where(game: Game, name: str) -> list[str]:
    found = []
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile", "library"):
            found += [f"P{seat}.{zone}"] * sum(
                1 for held in getattr(player, zone) if held.name == name
            )
    found += ["battlefield"] * sum(
        1 for permanent in game.all_permanents() if permanent.card.name == name
    )
    return sorted(found)


def _stays(game: Game, name: str, zone: str) -> bool:
    return any(
        line.startswith(f"{name} can't enter the battlefield and stays in P0's {zone}")
        and line.endswith("(Worms of the Earth)")
        for line in game.log
    )


def _claims_entry(game: Game, name: str) -> bool:
    return any(
        name in line and ("onto the battlefield" in line or "returned" in line)
        and "can't enter" not in line
        for line in game.log
    )


@pytest.mark.parametrize("worms", [True, False])
@pytest.mark.parametrize("interactive", [False, True])
def test_show_and_tell_leaves_the_land_in_the_hand(worms, interactive):
    game = _game(hand=["Show and Tell", "Lake of the Dead"], mine=["Swamp", "Swamp"],
                 opponent_hand=["Grizzly Bears"], worms=worms, interactive=interactive)
    assert game.queue_from_hand(0, "Show and Tell").supported
    picked = []

    def pick_the_lake(game, choice):
        picked.append(choice.kind)
        lake = next(
            i for i, c in enumerate(game.players[0].hand) if c.name == "Lake of the Dead"
        )
        assert game.confirm_put_from_hand_choice(0, lake)

    settle(game, answers={
        "optional_pay": lambda game, c: game.confirm_optional_pay(c.player_index, accept=True),
        "put_from_hand_choice": pick_the_lake,
    } if interactive else None)
    # The interactive seat was asked, and its answer is the one that stayed.
    assert picked == (["put_from_hand_choice"] if interactive else [])
    # The rest of the event happens either way: the opponent's Bears enter.
    assert _where(game, "Grizzly Bears") == ["battlefield"]
    if worms:
        assert _where(game, "Lake of the Dead") == ["P0.hand"]
        assert _stays(game, "Lake of the Dead", "hand")
        assert not _claims_entry(game, "Lake of the Dead")
        assert _where(game, "Swamp") == ["battlefield", "battlefield"]
    else:
        assert _where(game, "Lake of the Dead") == ["battlefield"]
        assert "P0 put Lake of the Dead onto the battlefield (Show and Tell)" in game.log


@pytest.mark.parametrize("worms", [True, False])
def test_elvish_pioneer_leaves_the_basic_land_in_the_hand(worms):
    game = _game(hand=["Elvish Pioneer", "Forest"], worms=worms)
    assert game.queue_from_hand(0, "Elvish Pioneer").supported
    settle(game)
    assert _where(game, "Elvish Pioneer") == ["battlefield"]
    if worms:
        assert _where(game, "Forest") == ["P0.hand"]
        assert _stays(game, "Forest", "hand")
        assert not _claims_entry(game, "Forest")
    else:
        assert _where(game, "Forest") == ["battlefield"]


@pytest.mark.parametrize("worms", [True, False])
def test_a_search_leaves_the_land_in_the_library(worms):
    game = _game(hand=["Untamed Wilds"], library=["Forest"] * 3 + ["Island"] * 3,
                 worms=worms)
    assert game.queue_from_hand(0, "Untamed Wilds").supported
    settle(game)
    forests = sum(1 for c in game.players[0].library if c.name == "Forest")
    if worms:
        assert forests == 3 and len(game.players[0].library) == 6
        # A library search finds a card nobody else sees: counted, not named.
        assert any(
            line == "a card can't enter the battlefield and stays in P0's library "
            "(Worms of the Earth)" for line in game.log
        )
        assert not any("put Forest onto the battlefield" in line for line in game.log)
    else:
        assert forests == 2 and _where(game, "Forest").count("battlefield") == 1


@pytest.mark.parametrize("worms", [True, False])
def test_planar_birth_leaves_the_lands_in_the_graveyard(worms):
    game = _game(hand=["Planar Birth"], graveyard=["Forest", "Island"], worms=worms)
    assert game.queue_from_hand(0, "Planar Birth").supported
    settle(game)
    for name in ("Forest", "Island"):
        zones = [z for z in _where(game, name) if not z.endswith("library")]
        if worms:
            assert zones == ["P0.graveyard"], (name, zones)
            assert _stays(game, name, "graveyard")
        else:
            assert zones == ["battlefield"], (name, zones)


@pytest.mark.parametrize("worms", [True, False])
def test_transmute_artifacts_held_artifact_land_goes_back_to_the_library(worms):
    game = _game(hand=["Transmute Artifact"], mine=["Ornithopter"],
                 library=["Seat of the Synod"] + ["Island"] * 5, worms=worms)
    assert game.queue_from_hand(0, "Transmute Artifact").supported
    settle(game)
    assert _where(game, "Ornithopter") == ["P0.graveyard"]
    if worms:
        assert _where(game, "Seat of the Synod") == ["P0.library"]
        assert len(game.players[0].library) == 6
        assert not any("Seat of the Synod enters the battlefield" in line for line in game.log)
    else:
        assert _where(game, "Seat of the Synod") == ["battlefield"]


@pytest.mark.parametrize("mana", [False, True])
def test_a_land_played_under_worms_stays_in_the_hand(mana):
    game = _game(hand=["Forest"], mana=mana)
    result = game.queue_from_hand(0, "Forest")
    assert not result.supported
    assert result.details == (
        "no player can play lands (Worms of the Earth)" if mana
        else "Forest can't enter the battlefield (Worms of the Earth)"
    )
    assert _where(game, "Forest").count("P0.hand") == 1
    assert not game.lands_played_this_turn.get(0)
