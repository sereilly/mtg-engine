"""Oubliette's phase-out is phasing (CR 702.26), not a departure.

"When this enchantment enters, target creature phases out until this
enchantment leaves the battlefield. Tap that creature as it phases in this
way." The handler took the creature off the battlefield as a removal — every
consequence of leaving with it — and tore what was attached off beside it; a
name-keyed leave hook (``card_hooks._oubliette_leaves``, on the graveyard path
alone) put the same objects back. Measured on 614442be against Oubliette's
2020-08-07 rulings:

* "Phasing out doesn't cause any 'leaves the battlefield' abilities to
  trigger" — Dual Nature's "whenever a nontoken creature leaves the
  battlefield" triggered as the creature phased out.
* "Each Aura and Equipment attached to a permanent that's phasing out also
  phases out. They will phase in with that permanent and still be attached to
  it" — Control Magic on the creature was torn down, so the creature phased
  back in under its owner; a Holy Strength came back unattached.
* "It phases in immediately after Oubliette leaves the battlefield" — on any
  road: a bounced Oubliette kept its creature for ever (the hook was on the
  graveyard path).

Now the creature phases out through ``Game.phase_out_permanent`` (what is
attached goes with it, CR 702.26g, and it keeps its id, CR 702.26d), its
phase-in waits for the source (``phasing_locks.PHASED_OUT_UNTIL_SOURCE_LEAVES``:
"A creature phased out by Oubliette doesn't phase in during its controller's
untap step as normal"), and the one transition off the battlefield phases it
in, tapped, when the source leaves (``Game.phase_in_what_waited_for``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import settle

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


def _cast(game: Game, seat: int, name: str, target: Permanent) -> None:
    game.players[seat].hand.append(_CARDS[name])
    result = game.cast_from_hand(
        seat, name, target_player_index=game.controller_index_of(target),
        target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result
    settle(game)


def _oubliette(game: Game) -> Permanent:
    return next(p for p in game.all_permanents() if p.card.name == "Oubliette")


def _phased(game: Game, seat: int) -> list[str]:
    return [perm.card.name for perm in game.players[seat].phased_out]


@pytest.mark.cr("702.26d")
def test_the_phase_out_triggers_no_leaves_the_battlefield_ability():
    game = _table()
    _set_down(game, 0, "Dual Nature")
    giant = _set_down(game, 1, "Hill Giant")
    before = giant.permanent_id
    _cast(game, 0, "Oubliette", giant)

    assert _phased(game, 1) == ["Hill Giant"]
    assert giant.permanent_id == before
    assert not any("Dual Nature" in line for line in game.log), game.log[-8:]


@pytest.mark.cr("702.26g", "702.26d")
def test_control_magic_phases_out_with_its_creature_and_keeps_it():
    """The Aura goes with the creature and comes back still attached, so the
    creature phases back in under Control Magic's controller."""
    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    aura = _set_down(game, 0, "Control Magic")
    attach_aura(aura, giant)
    change_control(giant, 0, source=aura)
    game._sync_control()
    assert game.controller_index_of(giant) == 0

    _cast(game, 1, "Oubliette", giant)
    assert sorted(_phased(game, 0)) == ["Control Magic", "Hill Giant"]
    assert not game.is_on_battlefield(aura)

    _cast(game, 1, "Disenchant", _oubliette(game))
    assert game.is_on_battlefield(giant) and game.is_on_battlefield(aura)
    assert aura.metadata.get("attached_to") is giant
    assert game.controller_index_of(giant) == 0
    assert giant.tapped and not aura.tapped
    assert _phased(game, 0) == [] and _phased(game, 1) == []


@pytest.mark.cr("702.26a", "702.26g")
def test_the_untap_step_leaves_it_out_and_the_aura_comes_back_attached():
    """"A creature phased out by Oubliette doesn't phase in during its
    controller's untap step as normal." The Holy Strength on it waits with
    it, and phases in attached."""
    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    strength = _set_down(game, 1, "Holy Strength")
    attach_aura(strength, giant)
    game._sync_control()
    _cast(game, 0, "Oubliette", giant)

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert sorted(_phased(game, 1)) == ["Hill Giant", "Holy Strength"]

    _cast(game, 1, "Disenchant", _oubliette(game))
    assert game.is_on_battlefield(giant) and giant.tapped
    assert strength.metadata.get("attached_to") is giant
    assert (giant.effective_power, giant.effective_toughness) == (4, 5)  # +1/+2


@pytest.mark.cr("610.3")
def test_a_bounced_oubliette_gives_the_creature_back():
    """Any road off the battlefield ends the phase-out, not the graveyard's
    alone."""
    game = _table()
    giant = _set_down(game, 1, "Hill Giant")
    _cast(game, 0, "Oubliette", giant)
    assert not game.is_on_battlefield(giant)

    _cast(game, 1, "Boomerang", _oubliette(game))
    assert [card.name for card in game.players[0].hand] == ["Oubliette"]
    assert game.is_on_battlefield(giant) and giant.tapped
    assert game.controller_index_of(giant) == 1
