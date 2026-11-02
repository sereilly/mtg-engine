"""The upkeep registry's "an opponent" picks are asked of somebody.

Three pay-or-consequence upkeep handlers (``phases/upkeep_effects.py``) named
an opponent and asked nobody:

* Demonic Hordes — "…tap this creature and sacrifice a land **of an
  opponent's choice**": the first land on the board went, in every seat count;
* Rohgahh of Kher Keep — "…then **an opponent** gains control of them": the
  first living opponent in seat order after the controller took them, though
  the ruling (2009-10-01) has the controller choose as the ability resolves;
* Rogue Skycaptain — "…and **an opponent** gains control of it": the same,
  against the same ruling (2008-10-01).

Each now asks through the choosers' seam (``handlers/player_choices.
ask_which_opponent``: the controller names the opponent where several could),
and the Hordes' named opponent picks the land (``permanent_choice``); the
consequence is the last step of a resumable loop, so an interactive chooser's
answer is waited for. Driven at three seats with each chooser interactive,
and with every seat a default one.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters

_CARDS = {card.name: card for card in load_catalog()}


def _perm(name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(mine, *, interactive=()) -> Game:
    """Seat 0's upkeep at a three-seat table; seat 0 holds *mine* and no
    black or red mana, so no upkeep price here can be paid."""
    game = Game(players=[
        PlayerState(name="P0", battlefield=[_perm(name) for name in mine],
                    library=[_CARDS["Island"]] * 5),
        PlayerState(name="P1", battlefield=[_perm("Island")],
                    library=[_CARDS["Island"]] * 5),
        PlayerState(name="P2", battlefield=[_perm("Island")],
                    library=[_CARDS["Island"]] * 5),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._recompute_continuous_effects()
    return game


def _owed(game: Game, kind: str):
    return [(c.player_index, c) for c in game.pending_choices if c.kind == kind]


def _names(game: Game, seat: int) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(seat))


# -- Demonic Hordes -----------------------------------------------------------

_HORDES = ["Demonic Hordes", "Forest", "Plains", "Mountain"]


def test_demonic_hordes_the_controller_names_the_opponent_who_picks_the_land():
    game = _table(_HORDES, interactive=(0, 2))
    hordes = game.players[0].battlefield[0]
    game.resolve_upkeep(0)
    assert hordes.tapped
    # Nothing is sacrificed until the land is chosen.
    assert _names(game, 0) == sorted(_HORDES), game.log
    (seat, choice), = _owed(game, "player_choice")
    assert seat == 0 and sorted(choice.data["seats"]) == [1, 2]
    assert game.confirm_player_choice(0, 2)
    (seat, choice), = _owed(game, "permanent_choice")
    assert seat == 2
    offered = sorted(p.card.name for p in choice.data["_candidates"])
    assert offered == ["Forest", "Mountain", "Plains"]
    plains = next(p for p in game.controlled_by(0) if p.card.name == "Plains")
    assert game.confirm_permanent_choice(2, plains.permanent_id)
    assert _names(game, 0) == ["Demonic Hordes", "Forest", "Mountain"], game.log
    assert "Plains" in [c.name for c in game.players[0].graveyard]


def test_demonic_hordes_a_default_table_still_sacrifices_one_land():
    game = _table(_HORDES)
    game.resolve_upkeep(0)
    assert not game.pending_choices
    # The first opponent offered chooses, and takes the first live land.
    assert _names(game, 0) == ["Demonic Hordes", "Mountain", "Plains"], game.log


def test_demonic_hordes_with_no_land_sacrifices_nothing_and_asks_nobody():
    game = _table(["Demonic Hordes"], interactive=(0, 1, 2))
    game.resolve_upkeep(0)
    assert not game.pending_choices
    assert game.players[0].battlefield[0].tapped


# -- Rohgahh of Kher Keep -----------------------------------------------------

_ROHGAHH = ["Rohgahh of Kher Keep", "Kobolds of Kher Keep", "Forest"]


def test_rohgahh_the_controller_names_the_opponent_who_gains_them():
    game = _table(_ROHGAHH, interactive=(0,))
    game.resolve_upkeep(0)
    (seat, choice), = _owed(game, "player_choice")
    assert seat == 0 and sorted(choice.data["seats"]) == [1, 2]
    # Tapped as printed, and still seat 0's until the opponent is named.
    assert all(p.tapped for p in game.controlled_by(0) if p.is_creature)
    assert "Rohgahh of Kher Keep" in _names(game, 0)
    assert game.confirm_player_choice(0, 2)
    assert _names(game, 0) == ["Forest"], game.log
    assert sorted(_names(game, 2)) == ["Island", "Kobolds of Kher Keep", "Rohgahh of Kher Keep"]


def test_rohgahh_a_default_controller_names_the_first_opponent_offered():
    game = _table(_ROHGAHH)
    game.resolve_upkeep(0)
    assert not game.pending_choices
    assert sorted(_names(game, 1)) == ["Island", "Kobolds of Kher Keep", "Rohgahh of Kher Keep"]


# -- Rogue Skycaptain ---------------------------------------------------------


def test_rogue_skycaptain_the_controller_names_the_opponent_who_gains_it():
    game = _table(["Rogue Skycaptain", "Forest"], interactive=(0,))
    captain = game.players[0].battlefield[0]
    add_counters(captain, "wage", 1)
    game.resolve_upkeep(0)
    (seat, choice), = _owed(game, "player_choice")
    assert seat == 0 and sorted(choice.data["seats"]) == [1, 2]
    assert game.confirm_player_choice(0, 2)
    assert game.controller_index_of(captain) == 2, game.log


def test_rogue_skycaptain_a_default_controller_names_the_first_opponent_offered():
    game = _table(["Rogue Skycaptain", "Forest"])
    captain = game.players[0].battlefield[0]
    game.resolve_upkeep(0)
    assert game.controller_index_of(captain) == 1, game.log
