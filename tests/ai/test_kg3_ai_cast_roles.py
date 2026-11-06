"""A cast announcement carries one answer per role (CR 601.2c).

`ActivationAction` has carried ``target_role_refs`` since Goblin Welder;
`CastAction` had no such field, so an AI seat's roles announcement was its
positional fields alone — one seat and battlefield ids. That cannot say two
players or a card in a graveyard, and the AI's role chain stopped where they
began (`ai_targets._choose_role_targets`): Wheel and Deal's weighing stopped
at the second opponent, Kaboom! named one player, Cruel Revival never named
its "up to one target Zombie card from your graveyard", and Cultural
Exchange's two players were no chain at all. The field is now on the action,
forwarded by `cast_announcement` (the one place a `CastAction` becomes a
cast), and the chain answers every role in it (`ai_targets._role_answer`).

The census holds every spell in the pool whose announcement needs a seat per
role or a graveyard card to a board here.
"""

from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action, choose_combat_instant_cast_action
from engine.ai_targets import _choose_role_targets
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.target_roles import role_seat_positions
from engine.targeting import derive_cast_spec, spec_roles
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

#: Spells whose announcement no `CastAction` could carry before the field —
#: each driven by a board below, or (Cultural Exchange) named with what is
#: still missing. Scourge's two "any number of target players each …" spells
#: are driven in ``tests/ai/test_scg_w1g4_any_number_of_players.py`` and join
#: this census when the set ships.
_DRIVEN = {
    "Cruel Revival", "Kaboom!", "Wheel and Deal",
    "Reward the Faithful", "Cabal Conditioning",
}
#: "Choose any number of creatures target player controls. Choose the same
#: number of creatures another target player controls." Both players are
#: announced now (`test_cultural_exchange_names_both_players`), but the
#: resolution's "choose any number of creatures" is answered with none by a
#: seat nobody asks, so the rehearsal reads a cast that changes nothing and
#: it is not proposed. What is left is that default, not the announcement.
_ANNOUNCED_NOT_YET_WORTH_CASTING = {"Cultural Exchange"}


def _table(*seats_and_lands, active=0):
    """A table with costs enforced in seat *active*'s precombat main phase:
    one ``(PlayerState, [land or permanent names])`` per seat."""
    game = Game(players=[seat for seat, _names in seats_and_lands])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 4
    game.active_player_index = active
    for index, (_seat, names) in enumerate(seats_and_lands):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(index, permanent, None)
            _nosick(permanent)
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _seat(name, *, hand=(), graveyard=(), library="Island", cards=20):
    return PlayerState(
        name=name, hand=[_CARDS[card] for card in hand],
        graveyard=[_CARDS[card] for card in graveyard],
        library=[_CARDS[library]] * cards,
    )


def _cast(game, seat, action):
    action = tap_planned_lands(game, seat, action)
    result = game.cast_from_hand(seat, action.card_name, **cast_announcement(action))
    resolve_stack(game)
    return result


def test_every_spell_needing_a_role_per_seat_or_a_graveyard_card_is_driven():
    """The census, with its floor (four spells at the kg3 round)."""
    found = set()
    for card in compilation_units(load_catalog()):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for mode in (range(len(program.modes)) if program.modes else (None,)):
            roles = spec_roles(derive_cast_spec(card, program, mode_index=mode))
            if len(role_seat_positions(roles)) > 1 or any(
                "graveyard" in str(role.get("kind")) for role in roles
            ):
                found.add(card.name)
    assert len(found) >= 4, found
    assert found <= _DRIVEN | _ANNOUNCED_NOT_YET_WORTH_CASTING, sorted(
        found - _DRIVEN - _ANNOUNCED_NOT_YET_WORTH_CASTING
    )


def test_cruel_revival_names_the_zombie_card_and_returns_it():
    """"Destroy target non-Zombie creature. … Return up to one target Zombie
    card from your graveyard to your hand." The card is named in its own role
    (a graveyard slot, ``graveyard_seat``/``graveyard_index``), the dearest
    first, and it is the card that comes back."""
    game = _table(
        (_seat("A", hand=["Cruel Revival"],
               graveyard=["Hill Giant", "Gangrenous Goliath", "Aphetto Vulture"],
               library="Swamp"), ["Swamp"] * 5),
        (_seat("B", library="Swamp"), ["Grizzly Bears"]),
    )
    bears = next(iter(game.controlled_by(1)))

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Cruel Revival"
    vulture = [card.name for card in game.players[0].graveyard].index("Aphetto Vulture")
    assert action.target_role_refs == [
        {"permanent_id": bears.permanent_id},
        {"graveyard_seat": 0, "graveyard_index": vulture},
    ]
    assert _cast(game, 0, action).supported
    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[0].hand] == ["Aphetto Vulture"]


def test_cruel_revival_at_instant_speed_names_the_card_too():
    """The instant-speed chooser builds the same announcement
    (`ai_policy._combat_instant_candidate`): in the opponent's end step, with
    the creature to destroy and the card to return."""
    game = _table(
        (_seat("A", library="Swamp"), ["Grizzly Bears"]),
        (_seat("B", hand=["Cruel Revival"], graveyard=["Gangrenous Goliath"],
               library="Swamp"), ["Swamp"] * 5),
        active=0,
    )
    game.current_turn_phase, game.current_step = "ending", "end"

    action = choose_combat_instant_cast_action(game, 1)

    assert action is not None and action.card_name == "Cruel Revival"
    assert action.target_role_refs[1] == {"graveyard_seat": 1, "graveyard_index": 0}


def _wheel_table(*, hands):
    return _table(
        (_seat("A", hand=["Wheel and Deal", "Island"]), ["Island"] * 4),
        *((_seat(name, hand=["Island"] * held, cards=30), []) for name, held in zip("BC", hands)),
    )


def test_wheel_and_deal_names_both_opponents_worth_naming():
    """"Any number of target opponents each discard their hands, then draw
    seven cards." Two opponents each holding nine: naming both is the best
    prefix, and both are named — one seat per role — where the weighing used
    to stop at the second seat."""
    game = _wheel_table(hands=(9, 9))

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Wheel and Deal"
    assert action.target_role_refs == [{"seat": 1}, {"seat": 2}]
    assert _cast(game, 0, action).supported
    assert [len(player.hand) for player in game.players] == [2, 7, 7]


def test_wheel_and_deal_still_stops_where_the_next_opponent_is_not_worth_it():
    """The prefix is weighed, not taken whole: an opponent with nine cards is
    worth naming, the one after with two is handed five, and is not named."""
    game = _wheel_table(hands=(9, 2))

    action = choose_cast_action(game, 0)

    assert action is not None and action.target_role_refs == [{"seat": 1}]
    assert _cast(game, 0, action).supported
    assert [len(player.hand) for player in game.players] == [2, 7, 2]


def test_kaboom_names_every_opponent_at_a_three_seat_table():
    """"Choose any number of target players or planeswalkers. For each of
    them, reveal …, Kaboom! deals damage equal to that card's mana value to
    that player or planeswalker." Two opponents, two seat roles: the chain
    was refused for naming two players (one field), so Kaboom! was never cast
    at a table of three."""
    game = _table(
        (_seat("A", hand=["Kaboom!"], library="Hill Giant"), ["Mountain"] * 5),
        (_seat("B", cards=30), []),
        (_seat("C", cards=30), []),
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Kaboom!"
    assert action.target_role_refs == [{"seat": 1}, {"seat": 2}]
    assert _cast(game, 0, action).supported
    # Hill Giant's mana value is 4.
    assert [player.life for player in game.players] == [20, 16, 16]


def test_cultural_exchange_names_both_players():
    """The chain is announced — both players, one role each — which it was
    not before; what keeps it uncast is named in
    ``_ANNOUNCED_NOT_YET_WORTH_CASTING``."""
    game = _table(
        (_seat("A", hand=["Cultural Exchange"]), ["Island"] * 6 + ["Grizzly Bears"]),
        (_seat("B"), ["Serra Angel"]),
    )

    chain = _choose_role_targets(game, 0, _CARDS["Cultural Exchange"])

    assert chain not in (None, ())
    assert chain[4] == [{"seat": 0}, {"seat": 1}]


@pytest.mark.parametrize("name", ["Cruel Revival", "Kaboom!"])
def test_the_simulator_casts_it_with_the_whole_announcement(name):
    """The simulator's executor makes the announcement the chooser built
    (`ai_simulator._play_one_cast` through `cast_announcement`): the cast is
    accepted, and the log names it."""
    seats = {
        "Cruel Revival": (
            (_seat("AI-A", hand=["Cruel Revival"], graveyard=["Gangrenous Goliath"],
                   library="Swamp"), ["Swamp"] * 5),
            (_seat("AI-B", library="Swamp"), ["Grizzly Bears"]),
        ),
        "Kaboom!": (
            (_seat("AI-A", hand=["Kaboom!"], library="Hill Giant"), ["Mountain"] * 5),
            (_seat("AI-B", cards=30), []),
        ),
    }[name]
    game = _table(*seats)
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )

    assert ai_simulator._play_one_cast(game, 0, report, 1, 1) is True

    assert report.log_lines[0] == f"G1 T1 AI-A cast {name} -> resolved"
    assert not report.refused_casts
    if name == "Cruel Revival":
        assert [card.name for card in game.players[0].hand] == ["Gangrenous Goliath"]
    else:
        assert game.players[1].life == 16
