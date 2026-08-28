"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G1: damage family (The Dark) ---


def test_sorrows_path_burns_its_controller_and_their_creatures_when_tapped(set_pool):
    """"it deals 2 damage to **you and each creature you control**" — one
    printed clause, two kinds of recipient, and no sweep handler that batches
    exactly that set. Lowered as one instruction per recipient; refused
    outright before that, so the whole trigger did nothing."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    mine = Permanent(card=lea["Grizzly Bears"])
    theirs = Permanent(card=lea["Grizzly Bears"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path, mine]
    players[1].battlefield = [theirs]
    game = Game(players=players)
    game._sync_control()

    game.become_tapped(path)
    game._settle()

    assert players[0].life == 18, game.log
    assert mine.damage_marked == 2, game.log
    assert theirs.damage_marked == 0, game.log


def test_sorrows_paths_sweep_reaches_creatures_that_arrived_since(set_pool):
    """The recipients are the printed noun phrase asked at resolution, not a
    list built when the land entered — so a creature that arrived in between is
    damaged and one that left is not."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path]
    game = Game(players=players)
    game._sync_control()

    latecomer = Permanent(card=lea["Hill Giant"])
    players[0].battlefield.append(latecomer)
    game._sync_control()
    game.become_tapped(path)
    game._settle()

    assert latecomer.damage_marked == 2, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _run_upkeep(game: Game, seat: int) -> None:
    """One upkeep step for *seat*, with its triggers resolved off the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


def _safe_haven_holding_a_creature(set_pool):
    """Safe Haven on the battlefield with one creature exiled under it."""
    lea = set_pool("LEA")
    haven = Permanent(card=set_pool("DRK")["Safe Haven"])
    bears = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[haven, bears]),
        PlayerState(name="P2"),
    ])
    game.players[0].mana_pool["C"] = 2
    result = game.activate_permanent_ability(
        0, "Safe Haven", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.reason
    while game.stack:
        game.resolve_top_of_stack()
    return game, haven


def test_safe_haven_exiles_a_creature_with_its_activated_ability(set_pool):
    """"{2}, {T}: Exile target creature you control." The pile the upkeep
    trigger below returns from has to exist before it can be returned."""
    game, _haven = _safe_haven_holding_a_creature(set_pool)

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    assert not [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]


def test_safe_haven_returns_its_exiled_cards_when_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice this land. If you do,
    return each card exiled with this land to the battlefield under its owner's
    control."

    This line compiled to **no instruction** — Safe Haven reported supported and
    exiled creatures forever. Knowledge Vault prints the same linked-pile
    sentence with the other verb ("put all cards exiled with…into"), so both
    spellings are one production now.
    """
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=True)

    assert not game.is_on_battlefield(haven)
    assert not game.players[0].exile
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]


def test_safe_haven_declined_keeps_the_cards_in_exile(set_pool):
    """The offer is a "may": declining leaves the land and the pile alone."""
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=False)

    assert game.is_on_battlefield(haven)
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
