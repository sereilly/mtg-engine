"""CR 701.19a-b's third sentence: "If it's an attacking or blocking creature,
remove it from combat."

``engine/regeneration._apply`` tapped the creature and removed its damage and
said, in its own docstring, that the removal from combat "is not carried out
here". So every regenerating card in the pool (133 supported programs, W1G2's
census at Mirrodin) went on fighting after it regenerated: a Drudge Skeletons
regenerated from a Black Knight's first-strike damage dealt its regular damage
to the Knight, and a regenerated attacker stayed an "attacking creature" for
every filter that asked. The printed reminder on Drudge Skeletons says it in
four words: "tap it, remove it from combat".

CR 506.4 lists regenerating among the roads out of combat, and the removal is
one transition (``Game.remove_from_combat``) whichever road is taken. A
creature it was blocking **stays blocked** (CR 509.1h): it deals no damage to
the defending player for want of a blocker.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.regeneration import regeneration_replaces_destruction
from tests.helpers import _game, _nosick, declare_attack, resolve_stack

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_ARN = {c.name: c for c in load_cards(manifest_set_path("ARN"))}
_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG"))}


def _table(attacker_card, blocker_card, *extra_for_defender):
    """Seat 0 attacks with *attacker_card*; seat 1 blocks with *blocker_card*
    (and holds *extra_for_defender*). The declare blockers step, blocks made."""
    game = _game(PlayerState(name="A"), PlayerState(name="D"))
    attacker = Permanent(card=attacker_card)
    blocker = Permanent(card=blocker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    game._put_permanent_onto_battlefield(1, blocker, None)
    extras = []
    for card in extra_for_defender:
        extra = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, extra, None)
        extras.append(extra)
    for permanent in (attacker, blocker, *extras):
        _nosick(permanent)
    game._settle()
    declare_attack(game, 0, blocks={0: 0})
    return game, attacker, blocker, extras


def _shield(game, seat: int, name: str) -> None:
    """Activate "{B}: Regenerate this creature" through the real entry point."""
    queued = game.queue_permanent_ability(seat, name, permanent_index=0)
    assert queued.supported and queued.details == "queued", queued
    resolve_stack(game)


def _deal_combat_damage(game) -> None:
    """Both damage passes (first strike, then regular), into end of combat."""
    game.advance_combat_phase()
    resolve_stack(game)
    assert game.current_step == "end_of_combat", game.current_step


@pytest.mark.cr("701.19a", "506.4", "509.1h")
def test_a_blocker_regenerated_by_first_strike_damage_deals_no_regular_damage():
    """Black Knight (2/2 first strike) attacks; Drudge Skeletons (1/1) blocks
    with a shield. The first-strike step kills it, it regenerates, and it is
    out of combat before the regular step — so the Knight takes nothing. The
    Knight stays blocked and deals nothing to the defending player."""
    game, knight, skeletons, _ = _table(_LEA["Black Knight"], _LEA["Drudge Skeletons"])
    _shield(game, 1, "Drudge Skeletons")

    _deal_combat_damage(game)

    assert game.is_on_battlefield(skeletons) and skeletons.tapped
    assert "Drudge Skeletons was removed from combat" in game.log
    assert skeletons.blocking_attacker_index is None
    assert knight.damage_marked == 0
    assert knight.blocked and knight.attacking
    assert game.players[1].life == 20


@pytest.mark.cr("701.19a", "506.4")
def test_a_regenerated_attacker_is_no_longer_attacking():
    """Drudge Skeletons attacks with a shield into a Black Knight. Regenerated
    by the first-strike damage, it deals no regular damage to the Knight, and
    it is no longer an attacking creature: Singing Tree's "target attacking
    creature" has nothing to point at."""
    game, skeletons, knight, (tree,) = _table(
        _LEA["Drudge Skeletons"], _LEA["Black Knight"], _ARN["Singing Tree"],
    )
    _shield(game, 0, "Drudge Skeletons")

    _deal_combat_damage(game)

    assert game.is_on_battlefield(skeletons) and skeletons.tapped
    assert not skeletons.attacking
    assert knight.damage_marked == 0
    aimed = game.queue_permanent_ability(
        1, "Singing Tree", permanent_index=1,
        target_permanent_ids=[skeletons.permanent_id],
    )
    assert not aimed.supported, aimed
    assert not game.stack


@pytest.mark.cr("701.19b", "506.4")
def test_a_static_regeneration_removes_its_blocker_from_combat_too():
    """Clergy of the Holy Nimbus regenerates itself each time (CR 701.19b) —
    the same alternate effect, so the same third sentence. White Knight's
    first-strike damage kills it; it deals White Knight nothing in the regular
    step."""
    game, knight, clergy, _ = _table(
        _LEA["White Knight"], _LEG["Clergy of the Holy Nimbus"],
    )

    _deal_combat_damage(game)

    assert game.is_on_battlefield(clergy) and clergy.tapped
    assert "Clergy of the Holy Nimbus regenerates itself (701.19b)" in game.log
    assert "Clergy of the Holy Nimbus was removed from combat" in game.log
    assert knight.damage_marked == 0
    assert game.players[1].life == 20


@pytest.mark.cr("701.19a")
def test_a_regeneration_outside_combat_removes_nothing():
    """Not attacking, not blocking: the removal is no part of the event and
    says nothing."""
    game = _game(PlayerState(name="A"), PlayerState(name="D"))
    skeletons = Permanent(card=_LEA["Drudge Skeletons"], regeneration_shield=1)
    game._put_permanent_onto_battlefield(0, skeletons, None)
    game._settle()

    assert regeneration_replaces_destruction(game, skeletons)

    assert skeletons.tapped
    assert not any("removed from combat" in line for line in game.log)
