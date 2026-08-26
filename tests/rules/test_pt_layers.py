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
    add_pt_modifier(perm, 3, 3, until="end_of_turn")
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
    add_pt_modifier(perm, 3, 3, until="end_of_turn")
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    game.resolve_cleanup_step(0)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)


@pytest.mark.cr("613.4b", "613.4c")
def test_a_permanent_base_rewrite_composes_with_counters():
    """A resolved "change base power and toughness to 0/2" (Brine Hag's shape,
    layer 7b, no duration) still takes 7c modifications on top — the rewrite
    replaces the base, not the creature's whole P/T computation."""
    from engine.pt import add_pt_counters

    perm = _perm(5, 5)
    set_base_pt(perm, 0, 2)
    add_pt_counters(perm, "+1/+1")
    assert (perm.effective_power, perm.effective_toughness) == (1, 3)


@pytest.mark.cr("613.4b", "611.2a")
def test_a_scheduled_base_pt_revert_ends_when_the_named_upkeep_ends():
    """"…until the end of your next upkeep" (Halfdane): the revert stamp names
    a seat and the turn it was written; the seat's draw step — the moment its
    upkeep has just ended — clears a base override stamped on an *earlier*
    turn, and leaves one stamped this very upkeep alone."""
    from engine.pt import BASE_PT_REVERT_KEY

    expired = _perm(3, 3, name="Expired")
    fresh = _perm(3, 3, name="Fresh")
    p1 = PlayerState(name="P1", battlefield=[expired, fresh],
                     library=[_mk_creature_card("Card A", 1, 1)])
    p2 = PlayerState(name="P2")
    game = _game(p1, p2)
    game.turn = 3

    set_base_pt(expired, 5, 5)
    expired.metadata[BASE_PT_REVERT_KEY] = {"seat": 0, "turn": 1}
    set_base_pt(fresh, 5, 5)
    fresh.metadata[BASE_PT_REVERT_KEY] = {"seat": 0, "turn": 3}

    game.resolve_draw_step(0)

    assert (expired.effective_power, expired.effective_toughness) == (3, 3)
    assert (fresh.effective_power, fresh.effective_toughness) == (5, 5)
    assert BASE_PT_REVERT_KEY not in expired.metadata
    assert BASE_PT_REVERT_KEY in fresh.metadata


@pytest.mark.cr("613.4b", "611.2a")
def test_the_revert_waits_for_the_stamped_seat():
    """Another seat's upkeep ending is not the stamped one's — "your next
    upkeep" belongs to the seat that resolved the ability."""
    from engine.pt import BASE_PT_REVERT_KEY

    perm = _perm(3, 3)
    p1 = PlayerState(name="P1", library=[_mk_creature_card("Card A", 1, 1)])
    p2 = PlayerState(name="P2", battlefield=[perm],
                     library=[_mk_creature_card("Card B", 1, 1)])
    game = _game(p1, p2)
    game.turn = 4

    set_base_pt(perm, 7, 7)
    perm.metadata[BASE_PT_REVERT_KEY] = {"seat": 1, "turn": 2}

    game.resolve_draw_step(0)
    assert (perm.effective_power, perm.effective_toughness) == (7, 7), \
        "seat 0's upkeep ending is not seat 1's"

    game.resolve_draw_step(1)
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)


@pytest.mark.cr("613.4b", "613.7")
def test_a_newer_permanent_rewrite_supersedes_a_scheduled_revert():
    """Layer 7b is last-write-wins here: a later indefinite rewrite (Brine
    Hag's) over a scheduled one (Halfdane's) removes the schedule, because
    reverting to the printed base would erase the newer effect too."""
    from engine.pt import BASE_PT_REVERT_KEY

    perm = _perm(3, 3)
    set_base_pt(perm, 5, 5)
    perm.metadata[BASE_PT_REVERT_KEY] = {"seat": 0, "turn": 1}

    set_base_pt(perm, 0, 2)
    assert BASE_PT_REVERT_KEY not in perm.metadata
    assert (perm.effective_power, perm.effective_toughness) == (0, 2)
