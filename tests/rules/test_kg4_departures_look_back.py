"""What one event takes off the battlefield looks back at itself — every road,
every look-back ability (CR 603.10a).

CR 603.10a: "Some zone-change triggers look back in time. These are
leaves-the-battlefield abilities, abilities that trigger when a player
sacrifices a permanent, abilities that trigger when a card leaves a
graveyard, and abilities that trigger when an object that all players can see
is put into a hand or library." Such an ability triggers if it existed
"immediately prior to the event" — so an observer the event takes off the
battlefield sees everything else the event takes with it.

The engine performs one event as several removals one after another: Upheaval
returns one permanent at a time (``returns.return_all_matching``), a cost of
"sacrifice all permanents you control" sacrifices them one by one, and each
"whenever you sacrifice a permanent" is announced after its permanent has gone.
So an observer taken first saw nothing taken after it, and one sacrificed saw
not even itself. Each board below seats the observer first and last; on the
base (4c3d6e34) every "first" row misses what the "last" row sees — the
asymmetry is the defect:

* Warped Devotion ("Whenever a permanent is returned to a player's hand, that
  player discards a card"; its ruling: "This card can trigger on itself being
  returned") returned by Upheaval ahead of two creatures triggered once.
* Dual Nature ("Whenever a nontoken creature leaves the battlefield, …")
  returned by Upheaval ahead of a creature did not trigger for it.
* Funeral March ("When enchanted creature leaves the battlefield, its
  controller sacrifices a creature") returned ahead of its creature, or exiled
  with it by Apocalypse, never triggered.
* Havoc Jester ("Whenever you sacrifice a permanent, this creature deals 1
  damage to any target"; its ruling: "triggers when you sacrifice it. If you
  sacrifice other permanents at the same time, it triggers for them as well")
  never triggered on its own sacrifice, nor for what went with it.
* Vengeful Dead ("Whenever this creature or another Zombie dies, each opponent
  loses 1 life") sacrificed ahead of a Zombie to Kaervek's Spite's cost missed
  the Zombie.

Now one action's removals are one departure event (``Game.leaving_together``
around each such loop) and every look-back announcement asks what the event has
already taken off the battlefield: the bus (``events.LOOKS_BACK_IN_TIME``), the
attachment and token-maker scans of the one transition out
(``remove_all_from_battlefield``), and the sacrifice transitions open the event
they announce in.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}

FIRST, LAST = "observer_first", "observer_last"


def _table() -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    """On the battlefield without entering (an entry trigger would move the
    board this test is about)."""
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _cast(game: Game, seat: int, name: str, **kwargs) -> None:
    game.players[seat].hand.append(_CARDS[name])
    assert game.cast_from_hand(seat, name, **kwargs).supported


def _resolved(game: Game, name: str) -> int:
    return sum(1 for line in game.log if line == f"{name} ability resolved")


@pytest.mark.cr("603.10a")
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_warped_devotion_returned_with_the_others_triggers_for_each(order):
    """Upheaval returns Warped Devotion and two creatures: three permanents
    returned, three triggers — whichever the sweep took first."""
    game = _table()
    if order == FIRST:
        _set_down(game, 0, "Warped Devotion")
    _set_down(game, 1, "Hill Giant")
    _set_down(game, 1, "Grizzly Bears")
    if order == LAST:
        _set_down(game, 1, "Warped Devotion")
    _cast(game, 0, "Upheaval")
    settle(game)
    assert not list(game.all_permanents())
    assert _resolved(game, "Warped Devotion") == 3, game.log[-12:]


@pytest.mark.cr("603.10a")
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_dual_nature_returned_with_a_creature_sees_it_leave(order):
    """Dual Nature's two leave abilities: its own departure, and the Hill
    Giant's — both trigger whichever Upheaval returned first."""
    game = _table()
    if order == FIRST:
        _set_down(game, 0, "Dual Nature")
    _set_down(game, 1, "Hill Giant")
    if order == LAST:
        _set_down(game, 1, "Dual Nature")
    _cast(game, 0, "Upheaval")
    settle(game)
    assert _resolved(game, "Dual Nature") == 2, game.log[-10:]


@pytest.mark.cr("603.10a", "603.6e")
@pytest.mark.parametrize("spell", ["Upheaval", "Apocalypse"])
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_funeral_march_leaving_with_its_creature_triggers(order, spell):
    """The Aura and its creature leave in one event; the Aura's "when
    enchanted creature leaves the battlefield" triggers (CR 603.6e)."""
    game = _table()
    # The Aura on the seat the sweep reaches first, or last.
    aura_seat = 0 if order == FIRST else 1
    host = _set_down(game, 1, "Hill Giant")
    aura = _set_down(game, aura_seat, "Funeral March")
    attach_aura(aura, host)
    _cast(game, 0, spell)
    settle(game)
    assert _resolved(game, "Funeral March") == 1, game.log[-10:]


@pytest.mark.cr("603.10a", "701.21a")
def test_havoc_jester_sees_its_own_sacrifice():
    """Innocent Blood: Havoc Jester is its controller's only creature. It
    triggers on its own sacrifice (its ruling) and deals 1 to the opponent."""
    game = _table()
    _set_down(game, 0, "Havoc Jester")
    _set_down(game, 1, "Hill Giant")
    _cast(game, 0, "Innocent Blood")
    settle(game)
    assert _resolved(game, "Havoc Jester") == 1, game.log[-10:]
    assert game.players[1].life == 19


@pytest.mark.cr("603.10a", "701.21a")
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_havoc_jester_sacrificed_with_others_triggers_for_each(order):
    """Death Pit Offering: "sacrifice all creatures you control" takes the
    Jester and two creatures at once — three triggers."""
    game = _table()
    if order == FIRST:
        _set_down(game, 0, "Havoc Jester")
    _set_down(game, 0, "Grizzly Bears")
    _set_down(game, 0, "Hill Giant")
    if order == LAST:
        _set_down(game, 0, "Havoc Jester")
    _cast(game, 0, "Death Pit Offering")
    settle(game)
    assert _resolved(game, "Havoc Jester") == 3, game.log[-12:]
    assert game.players[1].life == 17


@pytest.mark.cr("603.10a", "601.2h")
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_a_cost_of_several_sacrifices_is_one_event(order):
    """Kaervek's Spite's additional cost sacrifices Vengeful Dead and a Zombie
    together: the Dead sees both die (2), then the spell's 5."""
    game = _table()
    first, second = (
        ("Vengeful Dead", "Gravedigger") if order == FIRST
        else ("Gravedigger", "Vengeful Dead")
    )
    _set_down(game, 0, first)
    _set_down(game, 0, second)
    _cast(game, 0, "Kaervek's Spite", target_player_index=1)
    settle(game)
    assert game.players[1].life == 20 - 2 - 5, game.log[-10:]


@pytest.mark.cr("603.10a")
def test_no_departure_event_is_left_open():
    """Every board closes the event it opened (``Game.departure_batch`` and
    its aftermath read None at rest, which every ``vars()`` walker sees)."""
    game = _table()
    _set_down(game, 0, "Warped Devotion")
    _set_down(game, 1, "Hill Giant")
    _cast(game, 0, "Upheaval")
    settle(game)
    assert game.departure_batch is None
    assert game.departure_aftermath is None


@pytest.mark.cr("603.10a", "603.6e")
@pytest.mark.parametrize("aura", ["Creature Bond", "Funeral March"])
@pytest.mark.parametrize("order", [FIRST, LAST])
def test_an_aura_destroyed_with_its_creature_sees_it_go(order, aura):
    """Nevinyrral's Disk destroys an Aura and its creature on one seat — one
    removal, the Aura put into its graveyard (and torn down) as the sweep
    reaches it. Its "when enchanted creature dies" (Creature Bond) or
    "…leaves the battlefield" (Funeral March) triggers whichever of the two
    the sweep reached first."""
    game = _table()
    if order == FIRST:
        enchantment = _set_down(game, 1, aura)
        host = _set_down(game, 1, "Hill Giant")
    else:
        host = _set_down(game, 1, "Hill Giant")
        enchantment = _set_down(game, 1, aura)
    attach_aura(enchantment, host)
    _set_down(game, 0, "Nevinyrral's Disk")
    assert game.activate_permanent_ability(0, "Nevinyrral's Disk").supported
    settle(game)
    assert not list(game.all_permanents())
    assert _resolved(game, aura) == 1, game.log[-10:]
    if aura == "Creature Bond":
        # "…deals damage equal to that creature's toughness to the
        # creature's controller": the Hill Giant's 3.
        assert game.players[1].life == 17


@pytest.mark.cr("603.10a", "701.21a")
def test_a_sylex_sweep_is_a_sacrifice_of_each():
    """Golgothian Sylex: "Each nontoken permanent with a name originally
    printed in the Antiquities expansion is sacrificed by its controller" —
    one event, and a sacrifice of each: Havoc Jester (not an Antiquities card)
    hears its controller sacrifice the Sylex, the Miter and the Ornithopter,
    and Urza's Miter's "if it wasn't sacrificed" reads that they were."""
    game = _table()
    for name in ("Golgothian Sylex", "Havoc Jester", "Urza's Miter", "Ornithopter"):
        _set_down(game, 0, name)
    assert game.activate_permanent_ability(0, "Golgothian Sylex").supported
    settle(game)
    assert [p.card.name for p in game.all_permanents()] == ["Havoc Jester"]
    assert _resolved(game, "Havoc Jester") == 3, game.log[-12:]
    assert game.players[1].life == 17
    assert _resolved(game, "Urza's Miter") == 0, game.log[-12:]
