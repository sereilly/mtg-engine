"""Layer-composition tests for the P/T write API (engine/pt.py).

Pre-Arabian-Nights proof: a "base power and toughness 0/2" set effect
(Sorceress Queen, layer 7b) must compose with +X/+Y modifications (layer 7c)
and wear off at cleanup.
"""

from __future__ import annotations

import pytest

from engine.models import Permanent
from engine.pt import add_pt_modifier, clear_base_pt, set_base_pt, switch_pt
from tests.helpers import _game, _mk_creature_card

from engine import PlayerState


def _perm(power: int, toughness: int, name: str = "Test Beast") -> Permanent:
    return Permanent(card=_mk_creature_card(name, power, toughness))


@pytest.mark.cr("613.4b", "613.4c")
def test_set_base_pt_until_eot_composes_with_boost():
    # Sorceress Queen shape: target becomes 0/2 until EOT, then Giant Growth.
    perm = _perm(5, 5)
    set_base_pt(perm, 0, 2, until_eot=True)
    add_pt_modifier(perm, 3, 3, until_eot=True)
    assert (perm.effective_power, perm.effective_toughness) == (3, 5)


@pytest.mark.cr("613.4b", "613.7")
def test_temporary_set_beats_permanent_set():
    # A resolved 7b set effect is newer than a CDA/permanent set (last write wins).
    perm = _perm(5, 5)
    set_base_pt(perm, 7, 7)                    # e.g. CDA / animation
    set_base_pt(perm, 0, 2, until_eot=True)    # newer until-EOT set effect
    assert (perm.effective_power, perm.effective_toughness) == (0, 2)
    clear_base_pt(perm, until_eot=True)
    assert (perm.effective_power, perm.effective_toughness) == (7, 7)


@pytest.mark.cr("613.4d")
def test_switch_pt_switches_and_cancels():
    perm = _perm(1, 4)
    switch_pt(perm)
    assert (perm.effective_power, perm.effective_toughness) == (4, 1)
    switch_pt(perm)
    assert (perm.effective_power, perm.effective_toughness) == (1, 4)


@pytest.mark.cr("613.4b", "613.4c")
def test_set_effect_on_lord_buffed_creature():
    # Static lord buffs live in the static_buff_* channel (7c); a 7b set effect
    # replaces the base but keeps the lord bonus on top.
    perm = _perm(2, 2)
    perm.metadata["static_buff_power"] = 1
    perm.metadata["static_buff_toughness"] = 1
    set_base_pt(perm, 0, 2, until_eot=True)
    assert (perm.effective_power, perm.effective_toughness) == (1, 3)


@pytest.mark.cr("613.4b", "611.2a")
def test_until_eot_set_wears_off_at_cleanup():
    p1 = PlayerState(name="A", library=[], hand=[])
    p2 = PlayerState(name="B", library=[], hand=[])
    game = _game(p1, p2)
    perm = _perm(3, 3)
    p1.battlefield.append(perm)
    set_base_pt(perm, 0, 2, until_eot=True)
    assert (perm.effective_power, perm.effective_toughness) == (0, 2)
    game.resolve_cleanup_step(0)
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)


@pytest.mark.cr("613.4c", "611.2a")
def test_until_eot_boost_wears_off_at_cleanup():
    p1 = PlayerState(name="A", library=[], hand=[])
    p2 = PlayerState(name="B", library=[], hand=[])
    game = _game(p1, p2)
    perm = _perm(2, 2)
    p1.battlefield.append(perm)
    add_pt_modifier(perm, 3, 3, until_eot=True)
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    game.resolve_cleanup_step(0)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
