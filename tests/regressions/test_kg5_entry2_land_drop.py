"""A land play spends the land drop whatever its entry does (CR 305.2a,
116.2a), and "whenever a land enters" sees a land by any road (CR 603.6a).

    305.2a To determine whether a player can play a land, compare the number
    of lands the player can play this turn with the number of lands they have
    already played this turn (including lands played as special actions ...).

    116.2a Playing a land is a special action. ... By default, a player can
    take this action only once during each of their turns.

On round kg5's chain (e245e624c) the count was bumped by the land play's
``then`` (``mixins/stack/resolution._resolve_card``'s ``arrived``), which
returns for a permanent no longer on the battlefield — so a Lake of the Dead
whose Swamp nobody could sacrifice (CR 614.6: put into its owner's graveyard
instead) spent no land drop and a Forest followed it, and a Lake that Land
Equilibrium's "then sacrifices a land" took straight back out (a seat nobody
asks sacrifices before the ``then`` runs) entered, was never counted, never
logged as put onto the battlefield and never announced as played. And
"whenever a land enters" (Ankh of Mishra, Tectonic Instability) was announced
from the same ``then``, so a land an effect put onto the battlefield — Untamed
Wilds, Planar Birth — fired nothing.

What watches the *play* stays with an entry that happened: CR 603.2g ("an
event that's prevented or replaced won't trigger anything") — Horn of Greed
draws nothing for the Lake that went to the graveyard, and Fastbond's "if it
wasn't the first land you played this turn" reads the count it spent.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}


def _game(*, hand=(), mine=(), theirs=(), graveyard=(), library=None,
          interactive=False) -> Game:
    game = Game(players=[
        PlayerState("P0", hand=[_POOL[n] for n in hand],
                    library=[_POOL[n] for n in (library or ["Island"] * 10)],
                    graveyard=[_POOL[n] for n in graveyard]),
        PlayerState("P1", library=[_POOL["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.pending_choices.clear()
    game.start_turn(0)
    settle(game)
    return game


def _play(game: Game, name: str):
    return game.queue_from_hand(0, name)


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


def test_a_land_play_whose_entry_is_replaced_spends_the_land_drop():
    game = _game(hand=["Lake of the Dead", "Forest"], mine=["Island"])
    lake = _play(game, "Lake of the Dead")
    settle(game)
    assert lake.supported, lake.details
    assert _where(game, "Lake of the Dead") == ["P0.graveyard"]
    assert any("instead of entering the battlefield" in line for line in game.log)
    assert game.lands_played_this_turn.get(0) == 1
    assert not game._may_play_another_land(0)
    forest = _play(game, "Forest")
    assert not forest.supported
    assert forest.details == "already played a land this turn"
    assert _where(game, "Forest") == ["P0.hand"]


def test_a_played_land_land_equilibrium_sacrifices_was_played_and_entered():
    """The seat nobody asks applies Land Equilibrium, pays the Lake's toll and
    sacrifices the Lake itself before the play's ``then`` runs: the land
    entered (its log line), was played (Horn of Greed draws) and spent the
    drop."""
    game = _game(
        hand=["Lake of the Dead", "Forest"], mine=["Swamp", "Horn of Greed"],
        theirs=["Land Equilibrium", "Forest"],
    )
    hand_before = len(game.players[0].hand)
    lake = _play(game, "Lake of the Dead")
    settle(game)
    assert lake.supported, lake.details
    assert _where(game, "Lake of the Dead") == ["P0.graveyard"]
    assert _where(game, "Swamp") == ["P0.graveyard"]
    assert "P0 put Lake of the Dead onto battlefield" in game.log
    assert any("Horn of Greed" in line for line in game.log)
    # The Lake left the hand; Horn of Greed drew one back.
    assert len(game.players[0].hand) == hand_before
    assert game.lands_played_this_turn.get(0) == 1
    assert not _play(game, "Forest").supported


def test_the_play_triggers_follow_the_entry_and_fastbond_reads_the_count():
    game = _game(hand=["Lake of the Dead", "Forest"], mine=["Fastbond", "Horn of Greed"])
    life, hand = game.players[0].life, len(game.players[0].hand)
    _play(game, "Lake of the Dead")
    settle(game)
    # No entry, no play announced (CR 603.2g): no card drawn, no damage.
    assert (game.players[0].life, len(game.players[0].hand)) == (life, hand - 1)
    assert game.lands_played_this_turn.get(0) == 1
    forest = _play(game, "Forest")
    settle(game)
    assert forest.supported, forest.details
    # The Forest is the second land played this turn: Fastbond deals 1, and
    # Horn of Greed draws for it.
    assert game.players[0].life == life - 1
    assert len(game.players[0].hand) == hand - 1
    assert any(line == "Fastbond dealt 1 damage to P0" for line in game.log)


def test_an_answered_contention_counts_the_play_once():
    """An interactive seat's land play stops on CR 616.1e's question (Land
    Equilibrium against the Lake's unpaid toll); the drop is spent as the play
    is made, and the answer's re-run of the entry does not spend it again."""
    game = _game(
        hand=["Lake of the Dead", "Forest"], mine=["Forest", "Forest"],
        theirs=["Land Equilibrium", "Forest"], interactive=True,
    )
    _play(game, "Lake of the Dead")
    owed = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert len(owed) == 1
    assert game.lands_played_this_turn.get(0) == 1
    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    settle(game)
    assert game.lands_played_this_turn.get(0) == 1
    assert _where(game, "Lake of the Dead") == ["P0.graveyard"]
    assert not _play(game, "Forest").supported


@pytest.mark.parametrize("road, hand, graveyard, library, lands, damage", [
    ("Untamed Wilds", ["Untamed Wilds"], [], ["Forest"] * 4, 1, 2),
    ("Planar Birth", ["Planar Birth"], ["Forest", "Island"], None, 2, 4),
])
def test_whenever_a_land_enters_sees_a_land_an_effect_puts_there(
    road, hand, graveyard, library, lands, damage,
):
    game = _game(hand=hand, theirs=["Ankh of Mishra"], graveyard=graveyard,
                 library=library)
    game.enforce_mana_costs = False
    life = game.players[0].life
    before = sum(1 for p in game.controlled_by(0) if p.has_type("land"))
    assert _play(game, road).supported
    settle(game)
    assert sum(1 for p in game.controlled_by(0) if p.has_type("land")) - before == lands
    assert life - game.players[0].life == damage
    assert sum(1 for line in game.log if line == "Ankh of Mishra dealt 2 damage to P0") == lands


def test_whenever_a_land_enters_fires_once_for_a_land_play():
    game = _game(hand=["Forest"], theirs=["Ankh of Mishra", "Tectonic Instability"],
                 mine=["Island"])
    life = game.players[0].life
    assert _play(game, "Forest").supported
    settle(game)
    assert life - game.players[0].life == 2
    assert sum(1 for line in game.log if line == "Ankh of Mishra dealt 2 damage to P0") == 1
    # Tectonic Instability tapped every land the Forest's controller controls.
    assert all(p.tapped for p in game.controlled_by(0) if p.has_type("land"))
