""""Sacrifice it at the beginning of the next end step" is a sacrifice
(CR 701.21a), through the one transition, each its own event (CR 603.7).

The end step performed these delayed sacrifices with its destruction sweep,
protections switched off and ``NOT_A_DESTRUCTION`` as the cause: nothing called
the move a destruction, and nothing called it a sacrifice either. So "whenever
you sacrifice a permanent" (Havoc Jester; CR 603.10a makes it look back at the
permanent that went) never heard it, Urza's Miter's "if it wasn't sacrificed"
offered its draw for an artifact that was, and the log said "was destroyed at
end step". Driven through the printed activations that arm the mark
(Krovikan Elementalist, Celestial Sword), then the end step.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _table() -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _settle(game: Game) -> None:
    for _ in range(100):
        if game.stack:
            resolve_stack(game)
            continue
        if game.pending_choices:
            game.auto_resolve_pending_choices()
            continue
        return
    raise AssertionError(game.log[-8:])


def _resolved(game: Game, name: str) -> int:
    return sum(1 for line in game.log if line == f"{name} ability resolved")


def _activate(game: Game, name: str, target: Permanent, ability_index: int) -> None:
    result = game.activate_permanent_ability(
        0, name, target_player_index=0, ability_index=ability_index,
        target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result
    _settle(game)


@pytest.mark.cr("701.21a", "603.10a")
def test_the_delayed_sacrifice_is_heard_by_whenever_you_sacrifice():
    """Krovikan Elementalist's "{U}{U}: Target creature you control gains
    flying until end of turn. Sacrifice it at the beginning of the next end
    step." — Havoc Jester hears its controller sacrifice the Bears."""
    game = _table()
    _set_down(game, 0, "Havoc Jester")
    _set_down(game, 0, "Krovikan Elementalist")
    bears = _set_down(game, 0, "Grizzly Bears")
    _activate(game, "Krovikan Elementalist", bears, ability_index=1)
    assert game.is_on_battlefield(bears)

    game.resolve_end_step(0)
    _settle(game)

    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]
    assert "P0 sacrificed Grizzly Bears at end step" in game.log
    assert not any("destroyed at end step" in line for line in game.log)
    assert _resolved(game, "Havoc Jester") == 1, game.log[-8:]
    assert game.players[1].life == 19


@pytest.mark.cr("701.21a")
def test_urzas_miter_reads_the_delayed_sacrifice_as_one():
    """Celestial Sword: "Its controller sacrifices it at the beginning of the
    next end step." The Ornithopter it pumped was sacrificed, so Urza's
    Miter's "if it wasn't sacrificed, you may pay {3}" does not trigger."""
    game = _table()
    _set_down(game, 0, "Urza's Miter")
    _set_down(game, 0, "Celestial Sword")
    thopter = _set_down(game, 0, "Ornithopter")
    _activate(game, "Celestial Sword", thopter, ability_index=0)

    game.resolve_end_step(0)
    _settle(game)

    assert not game.is_on_battlefield(thopter)
    assert [card.name for card in game.players[0].graveyard] == ["Ornithopter"]
    assert _resolved(game, "Urza's Miter") == 0, game.log[-8:]


@pytest.mark.cr("701.21a", "603.7")
def test_each_delayed_sacrifice_is_its_own_event():
    """Two activations, two delayed abilities: each sacrifice is its own
    event, so Havoc Jester — marked by the first — hears its own sacrifice,
    and sees the Bears go only if it is still there when the Bears' turn
    comes."""
    game = _table()
    jester = _set_down(game, 0, "Havoc Jester")
    _set_down(game, 0, "Krovikan Elementalist")
    bears = _set_down(game, 0, "Grizzly Bears")
    _activate(game, "Krovikan Elementalist", jester, ability_index=1)
    _activate(game, "Krovikan Elementalist", bears, ability_index=1)

    game.resolve_end_step(0)
    _settle(game)

    assert not game.is_on_battlefield(jester)
    assert not game.is_on_battlefield(bears)
    assert sum(
        1 for line in game.log if line.endswith("at end step") and "sacrificed" in line
    ) == 2
    # The Jester went first (seat order), in an event of its own: it heard
    # itself go and not the Bears, which left after it in another.
    assert _resolved(game, "Havoc Jester") == 1, game.log[-10:]
