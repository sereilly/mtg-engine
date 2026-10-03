"""Regressions: an Aura's ability that resolves after the Aura has left still
names the creature it enchanted (CR 113.7a, CR 608.2h).

An ability on the stack exists independently of its source (CR 113.7a), and an
effect that needs information from a source that has left its zone uses that
source's last-known information (CR 608.2h). "Enchanted creature" is such a
piece of information. So "{G}: Regenerate enchanted creature" with the Aura
destroyed in response still regenerates the creature it was on, and "At the
beginning of your upkeep, untap enchanted land" with the Aura gone before the
trigger resolves still untaps that land.

The engine clears the Aura's live ``attached_to`` record as part of its
teardown, so seven handlers that read the live record did nothing in that
window. W1G1 fixed ``destroy_attached_permanent`` by routing it through
``handlers/_common.attached_host``, which keeps the last-known host, and listed
the rest unmeasured. Measured at W2G2 (``scratch/w2g2/aura_census.py``): 41
(card, kind) pairs over both manifest roles; 30 of them were wrong on the
pre-fix tree, the 10 ``destroy_attached_permanent`` rows were already right, and
one (Nurturing Licid) needed a rig the census could not build. After the fix
all 40 are right. The tests below drive the shapes through the real entry
points: an activation, an upkeep trigger, and a combat trigger whose delayed
half reads the host later.

``sacrifice_attached_permanent`` also fell off the end of its body and returned
None. Every caller unpacks a handler's ``(supported, detail)`` pair, so Slow
Motion **crashed the game** whenever its creature's controller did not pay —
not an edge case at all, but the card's ordinary outcome.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.handlers._common import attached_host
from engine.layer_bridge import computed_colors
from engine.models import Permanent
from tests.helpers import resolve_stack

_POOL: dict = {}
for _card in load_cards(manifest_set_paths()):
    _POOL.setdefault(_card.name, _card)


def _w2g2_perm(name: str) -> Permanent:
    perm = Permanent(card=_POOL[name])
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g2_enchanted(aura_name: str, host_name: str = "Grizzly Bears"):
    """Seat 0's main phase, with *aura_name* on seat 0's *host_name*."""
    host = _w2g2_perm(host_name)
    aura = _w2g2_perm(aura_name)
    game = Game(players=[
        PlayerState(name="P0", battlefield=[host, aura]),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, host)
    game.start_turn(0)
    game._close_current_priority_step()
    return game, aura, host


def _w2g2_activate_then_lose_the_aura(game, aura, **kwargs):
    queued = game.queue_permanent_ability(
        0, aura.card.name, permanent_index=game.battlefield_index_of(aura), **kwargs
    )
    assert queued.supported, queued.details
    assert game.stack, "the ability must be waiting on the stack"
    # The Aura is destroyed in response: the ability stays on the stack.
    game.sacrifice_permanent(aura)
    assert aura.metadata.get("attached_to") is None, "the teardown cleared it"
    resolve_stack(game)


@pytest.mark.cr("113.7a", "608.2h")
def test_regeneration_destroyed_in_response_still_shields_its_creature():
    game, aura, bear = _w2g2_enchanted("Regeneration")

    _w2g2_activate_then_lose_the_aura(game, aura)

    assert bear.regeneration_shield == 1, game.log


@pytest.mark.cr("113.7a", "608.2h")
def test_dream_coat_destroyed_in_response_still_recolours_its_creature():
    game, aura, bear = _w2g2_enchanted("Dream Coat")

    _w2g2_activate_then_lose_the_aura(game, aura, mana_color="U")

    assert computed_colors(bear) == {"U"}, game.log


@pytest.mark.cr("113.7a", "608.2h")
def test_vanishing_destroyed_in_response_still_phases_its_creature_out():
    game, aura, bear = _w2g2_enchanted("Vanishing")

    _w2g2_activate_then_lose_the_aura(game, aura)

    assert not game.is_on_battlefield(bear), game.log
    assert any("phased out" in line for line in game.log), game.log


def _w2g2_upkeep(aura_name: str, host_name: str, *, host_seat: int, turn_seat: int):
    """*aura_name* (seat 0's) on *host_name* (seat *host_seat*'s), with its
    upkeep trigger waiting on the stack in *turn_seat*'s upkeep."""
    host = _w2g2_perm(host_name)
    aura = _w2g2_perm(aura_name)
    boards: list[list] = [[aura], []]
    boards[host_seat].append(host)
    game = Game(players=[
        PlayerState(name="P0", battlefield=boards[0], library=[_POOL["Island"]] * 3),
        PlayerState(name="P1", battlefield=boards[1], library=[_POOL["Island"]] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, host)
    game.active_player_index = turn_seat
    game._sync_control()
    host.tapped = True
    game.resolve_upkeep(turn_seat, defer_priority=True)
    assert [item.card.name for item in game.stack] == [aura_name], game.log
    return game, aura, host


@pytest.mark.cr("113.7a", "608.2h", "603.3")
def test_wellspring_gone_before_its_upkeep_trigger_still_untaps_and_takes_the_land():
    """"At the beginning of your upkeep, untap enchanted land. You gain control
    of that land until end of turn." Both sentences name the land the Aura
    was on, and the second reads what the first untapped — so a lost host
    lost both."""
    game, aura, forest = _w2g2_upkeep("Wellspring", "Forest", host_seat=1, turn_seat=0)

    game.sacrifice_permanent(aura)
    resolve_stack(game)

    assert not forest.tapped, game.log
    assert game.controller_index_of(forest) == 0, game.log


@pytest.mark.cr("113.7a", "608.2h", "603.3")
def test_mind_whip_gone_before_its_upkeep_trigger_still_taps_the_creature():
    game, aura, bear = _w2g2_upkeep("Mind Whip", "Grizzly Bears", host_seat=1, turn_seat=1)
    bear.tapped = False

    game.sacrifice_permanent(aura)
    resolve_stack(game)

    assert game.players[1].life == 18, game.log
    assert bear.tapped, game.log


@pytest.mark.cr("113.7a", "608.2h", "701.21a")
def test_slow_motion_gone_before_its_upkeep_trigger_still_takes_the_creature():
    """"…that player sacrifices that creature unless they pay {2}." Nobody
    pays, so the creature goes — whether or not the Aura is still around to
    watch it."""
    game, aura, bear = _w2g2_upkeep("Slow Motion", "Grizzly Bears", host_seat=1, turn_seat=1)

    game.sacrifice_permanent(aura)
    resolve_stack(game)

    assert not game.is_on_battlefield(bear), game.log
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("701.21a", "603.3")
def test_slow_motion_takes_the_creature_when_its_price_is_not_paid():
    """The ordinary case, and the crash. The handler answered None, which the
    "unless" wrapper unpacks; resolving this trigger raised ``TypeError`` on
    the pre-fix tree."""
    game, _aura, bear = _w2g2_upkeep("Slow Motion", "Grizzly Bears", host_seat=1, turn_seat=1)

    resolve_stack(game)

    assert not game.is_on_battlefield(bear), game.log
    assert any("Grizzly Bears was sacrificed" in line for line in game.log), game.log


@pytest.mark.cr("113.7a", "608.2h", "603.7c")
def test_infinite_authority_gone_before_its_block_trigger_still_rewards_the_creature():
    """"Whenever enchanted creature … becomes blocked by a creature with
    toughness 3 or less, destroy the other creature at end of combat. At the
    beginning of the next end step, if that creature was destroyed this way,
    put a +1/+1 counter on **the first creature**."

    The delayed half reads which creature "the first" is off the record the
    trigger wrote as it resolved — and with the Aura already gone that record
    named the Aura itself, so the counter had nowhere to go."""
    bears = _w2g2_perm("Grizzly Bears")
    aura = _w2g2_perm("Infinite Authority")
    wall = _w2g2_perm("Wall of Wood")
    game = Game(players=[
        PlayerState(name="P0", battlefield=[bears, aura], library=[_POOL["Island"]] * 3),
        PlayerState(name="P1", battlefield=[wall], library=[_POOL["Island"]] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    attach_aura(aura, bears)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(bears)], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(wall): game.battlefield_index_of(bears)}
    )[0]
    assert [item.card.name for item in game.stack] == ["Infinite Authority"], game.log

    game.sacrifice_permanent(aura)
    resolve_stack(game)
    while game.current_turn_phase == "combat":
        game.advance_combat_phase()
        resolve_stack(game)
    assert not game.is_on_battlefield(wall), game.log
    game.resolve_end_step(0)
    resolve_stack(game)

    assert (bears.effective_power, bears.effective_toughness) == (3, 3), game.log


def test_an_attachment_still_on_the_battlefield_names_no_host_once_unattached():
    """CR 608.2h's other half, and the reason the last-known fallback is gated
    on the source having *left*: while an object is still in the zone the
    effect expects it in, its current information is what counts. An Equipment
    unattached in response is still on the battlefield and equips nothing, so
    "equipped creature" must not quietly come back as the creature it used to
    be on. Once it leaves, the last-known host is the answer."""
    sword = _w2g2_perm("Short Sword")
    bear = _w2g2_perm("Grizzly Bears")
    game = Game(players=[PlayerState(name="P0", battlefield=[bear, sword]), PlayerState(name="P1")])
    attach_aura(sword, bear)
    assert attached_host(game, sword) is bear

    detach_aura(sword, bear)
    assert game.is_on_battlefield(sword)
    assert attached_host(game, sword) is None, "still here, attached to nothing"

    attach_aura(sword, bear)
    game.sacrifice_permanent(sword)
    assert attached_host(game, sword) is bear, "gone: last-known information"
