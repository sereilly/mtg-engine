"""Permanents one event puts onto the battlefield enter together (CR 603.6a).

CR 603.6a: "Each time an event puts one or more permanents onto the
battlefield, all permanents on the battlefield (including the newcomers) are
checked for any enters-the-battlefield triggers that match the event." And
Soul Warden's ruling (2025-01-24): "If this creature enters at the same time
as one or more other creatures, its ability will trigger for each of those
other creatures."

Every road that puts several permanents onto the battlefield used to enter
them one at a time, so an observer among the newcomers saw only those that
entered after it: Goblin Assassin returned by Planar Guide after a Goblin
Clearcutter triggered once instead of twice (the playbook's observation,
diagnosed at kg3/entry). The roads now open one event around their newcomers
(``Game.entering_together``) and announce each one with all of them present.

The census: each road, driven through its real card from the pool, with a Soul
Warden **among the newcomers** — first of them and last of them, which is the
pair that differed — and, where the road leaves the board standing, a Soul
Warden **already there**, which counts every newcomer either way. A seat
nobody asks, and the same with a person at the table where the road takes the
interactive path. Backwards: on the base, every "last" row gains less than
the "first" row beside it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

WARDEN = "Soul Warden"


def _table(*, seats: int = 2, interactive: bool = False) -> Game:
    players = [
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 20)
        for i in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0} if interactive else set()
    game._sync_control()
    return game


def _place(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    return permanent


def _settle(game: Game) -> None:
    """Resolve and answer everything, each prompt by its seat's default."""
    for _ in range(200):
        owed = game.waiting_prompt()
        if owed is not None:
            game.take_choice_default(owed)
            continue
        if game.stack:
            game.resolve_top_of_stack(pause_for_choices=game.holds_for_answers())
            continue
        if game.pending_choices or game.pending_replacement_choices:
            game.auto_resolve_pending_choices()
            game.auto_resolve_pending_replacement_choices()
            continue
        return
    raise AssertionError(f"the table did not settle: {game.log[-5:]}")


def _ordered(first: bool, *others: str) -> list[str]:
    return [WARDEN, *others] if first else [*others, WARDEN]


def _life(game: Game) -> list[int]:
    return [player.life for player in game.players]


# -- the roads ----------------------------------------------------------------
#
# Each returns ``(newcomer_gain, present_gain)``: what the Soul Warden among
# the newcomers should have gained its controller (one per *other* creature
# entering), and what a Soul Warden already on the battlefield should have
# gained its own (one per creature entering) — None where the road clears the
# board before anything returns.


def _living_death(game: Game, first: bool):
    """Living Death: "…then puts all cards they exiled this way onto the
    battlefield" — "all players put all creatures they exiled onto the
    battlefield at the same time" (its ruling, 2018-03-16). Across seats."""
    game.players[0].graveyard = [_CARDS[n] for n in _ordered(first, "Grizzly Bears")]
    game.players[1].graveyard = [_CARDS["Llanowar Elves"]]
    game.players[0].hand = [_CARDS["Living Death"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Living Death").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 2, None, None


def _planar_guide(game: Game, first: bool):
    """Planar Guide: "At the beginning of the next end step, return those
    cards to the battlefield" — its ruling (2004-10-04): "All 'enters'
    abilities trigger as normal"."""
    for name in _ordered(first, "Grizzly Bears", "Llanowar Elves"):
        _place(game, 0, name)
    _place(game, 0, "Planar Guide")
    before = _life(game)
    assert game.activate_permanent_ability(0, "Planar Guide")
    _settle(game)
    game.resolve_end_step(0)
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 2, None, None


def _victimize(game: Game, first: bool):
    """Victimize: "…return the chosen cards to the battlefield tapped"."""
    _place(game, 1, WARDEN)
    _place(game, 0, "Llanowar Elves")
    game.players[0].graveyard = [_CARDS[n] for n in _ordered(first, "Grizzly Bears")]
    game.players[0].hand = [_CARDS["Victimize"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Victimize", target_permanent_index=[0, 1]).supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 1, gained[1], 2


def _twilights_call(game: Game, first: bool):
    """Twilight's Call: "Each player returns all creature cards from their
    graveyard to the battlefield"."""
    _place(game, 1, WARDEN)
    game.players[0].graveyard = [_CARDS[n] for n in _ordered(first, "Grizzly Bears")]
    game.players[1].graveyard = [_CARDS["Llanowar Elves"]]
    game.players[0].hand = [_CARDS["Twilight's Call"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Twilight's Call").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 2, gained[1], 3


def _tempting_wurm(game: Game, first: bool):
    """Tempting Wurm: "each opponent may put any number of … cards from their
    hand onto the battlefield" — the cards a seat puts down enter together."""
    _place(game, 0, WARDEN)
    game.players[1].hand = [_CARDS[n] for n in _ordered(first, "Grizzly Bears")]
    game.players[0].hand = [_CARDS["Tempting Wurm"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Tempting Wurm").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    # The Warden already there sees the Wurm too.
    return gained[1], 1, gained[0], 3


def _death_or_glory(game: Game, first: bool):
    """Death or Glory: "…return the other to the battlefield" — the pile the
    opponent leaves is one event. The caster splits as a person (the default
    split puts one creature in each pile): the Warden and the Bears in one
    pile, a Shivan Dragon alone in the other, which the opponent exiles."""
    _place(game, 1, WARDEN)
    game.interactive_seats = {0}
    game.players[0].graveyard = [
        _CARDS[n] for n in _ordered(first, "Grizzly Bears")
    ] + [_CARDS["Shivan Dragon"]]
    game.players[0].hand = [_CARDS["Death or Glory"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Death or Glory").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.resolve_pending_choice("pile_split", 0, first_pile=[0, 1])
    _settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(
        [WARDEN, "Grizzly Bears"]
    ), game.log[-8:]
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 1, gained[1], 2


def _coffins_exiling(game: Game, first: bool) -> list:
    """Two Tawnos's Coffins, each holding one creature ("Exile target creature
    … until this artifact leaves the battlefield or becomes untapped")."""
    victims = [_place(game, 0, name) for name in _ordered(first, "Grizzly Bears")]
    coffins = [_place(game, 0, "Tawnos's Coffin") for _ in victims]
    for coffin, victim in zip(coffins, victims):
        slot = next(
            i for i, held in enumerate(game.players[0].battlefield) if held is coffin
        )
        assert game.activate_permanent_ability(
            0, "Tawnos's Coffin", permanent_index=slot,
            target_permanent_ids=[victim.permanent_id],
        ).supported
        _settle(game)
        assert not game.is_on_battlefield(victim)
    return coffins


def _coffins_swept(game: Game, first: bool):
    """CR 610.3d: "If multiple one-shot effects are created this way
    immediately after one or more simultaneous events, those one-shot effects
    are also simultaneous" — its example two Banisher Priests a Day of
    Judgment destroys. Here two Coffins a Shatterstorm destroys."""
    _place(game, 1, WARDEN)
    _coffins_exiling(game, first)
    before = _life(game)
    game.players[1].hand = [_CARDS["Shatterstorm"]]
    game.active_player_index = 1
    assert game.cast_from_hand(1, "Shatterstorm").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 1, gained[1], 2


def _coffins_untapped(game: Game, first: bool):
    """…and the other ending: both Coffins untapping in their controller's
    untap step, which untaps them "all simultaneously" (CR 502.3)."""
    _place(game, 1, WARDEN)
    _coffins_exiling(game, first)
    before = _life(game)
    game.start_turn(0)
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 1, gained[1], 2


def _twin_tokens(game: Game, first: bool):
    """A token maker whose tokens observe ("…tokens with 'Whenever another
    creature enters, you gain 1 life'") — an invented card, since no token in
    the pool carries an entry observer: each token sees the other (CR
    603.6a). Identical tokens, so *first* names nothing here."""
    from engine.models import CardDefinition

    maker = CardDefinition(
        name="Twin Wardens", mana_cost="{1}{W}", cmc=2.0, type_line="Sorcery",
        oracle_text=(
            "Create two 1/1 white Spirit creature tokens with \"Whenever "
            "another creature enters, you gain 1 life.\""
        ),
        colors=("W",), color_identity=("W",), keywords=(), produced_mana=(),
        raw={"name": "Twin Wardens", "type_line": "Sorcery"},
    )
    _place(game, 1, WARDEN)
    game.players[0].hand = [maker]
    before = _life(game)
    assert game.cast_from_hand(0, "Twin Wardens").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[0], 2, gained[1], 2


def _parallel_evolution(game: Game, first: bool):
    """Parallel Evolution: "For each creature token on the battlefield, its
    controller creates a token that's a copy of that creature" — every copy in
    one event, so a copy of a Soul Warden sees the copies made beside it."""
    _place(game, 1, WARDEN)
    order = _ordered(first, "Grizzly Bears")
    for name in order:
        source = _place(game, 0, name)
        game.create_token_copy(0, source)
        resolve_stack(game)
        game.remove_from_battlefield(source)
    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(order)
    game.players[0].hand = [_CARDS["Parallel Evolution"]]
    before = _life(game)
    assert game.cast_from_hand(0, "Parallel Evolution").supported
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    # The Warden token already there sees both copies; the new one sees one.
    return gained[0] - 2, 1, gained[1], 2


def _game_preserve(game: Game, first: bool):
    """Game Preserve: "…put those cards onto the battlefield under their
    owners' control" — each player's top card, in one event."""
    _place(game, 0, "Game Preserve")
    top = _ordered(first, "Grizzly Bears")
    # The active player's card is stamped first (CR 613.7m), so "first" is
    # the Warden on top of the active player's library.
    game.players[0].library = [_CARDS[top[0]]] + [_CARDS["Plains"]] * 5
    game.players[1].library = [_CARDS[top[1]]] + [_CARDS["Plains"]] * 5
    warden_seat = 0 if first else 1
    before = _life(game)
    game.start_turn(0)
    _settle(game)
    gained = [now - then for now, then in zip(_life(game), before)]
    return gained[warden_seat], 1, None, None


ROADS = {
    "living_death": _living_death,
    "planar_guide": _planar_guide,
    "victimize": _victimize,
    "twilights_call": _twilights_call,
    "tempting_wurm": _tempting_wurm,
    "death_or_glory": _death_or_glory,
    "coffins_swept": _coffins_swept,
    "coffins_untapped": _coffins_untapped,
    "twin_tokens": _twin_tokens,
    "parallel_evolution": _parallel_evolution,
    "game_preserve": _game_preserve,
}


@pytest.mark.parametrize("interactive", [False, True], ids=["nobody_asked", "a_person"])
@pytest.mark.parametrize("first", [True, False], ids=["warden_first", "warden_last"])
@pytest.mark.parametrize("road", sorted(ROADS))
def test_every_newcomer_sees_every_other_enter(road, first, interactive):
    game = _table(interactive=interactive)
    newcomer_gain, newcomer_expected, present_gain, present_expected = ROADS[road](game, first)
    assert newcomer_gain == newcomer_expected, (
        f"{road}: the Soul Warden among the newcomers gained {newcomer_gain}, "
        f"one per other creature entering beside it is {newcomer_expected}\n"
        + "\n".join(game.log[-25:])
    )
    if present_expected is not None:
        assert present_gain == present_expected, (
            f"{road}: the Soul Warden already there gained {present_gain}, "
            f"one per creature entering is {present_expected}"
        )
