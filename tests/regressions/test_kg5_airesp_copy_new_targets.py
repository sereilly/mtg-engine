"""A copy of a spell with several targets or a mode is re-aimed, slot by
slot, by whoever controls it (CR 707.10c, 115.7d, 115.8) — the person asked
once per target with "keep" beside each, the seat nobody asks measured.

    115.7d If an effect allows a player to "choose new targets" for a spell
    or ability, the player may leave any number of the targets unchanged,
    even if those targets would be illegal. If the player chooses to change
    some or all of the targets, the new targets must be legal and must not
    cause any unchanged targets to become illegal.

Before kg5 every one of these copies kept its original's targets: a Forked
Reckless Spite aimed at the forker's creatures destroyed them twice, a Forked
Funeral Charm (a modal spell, which ``change_slots`` refused) shrank the
forker's creature again, and a Forked Fireball "re-aimed" by a seat nobody
asks logged its new target and dealt its damage to the old one (its one
target rides the division, which the one-slot offer's write never reached).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.stack_targets import chosen_targets
from tests.helpers import settle


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _forked(spell, announce, *, mine, theirs, interactive=False):
    """Seat 1 casts *spell* (``announce(mine, theirs)`` its announcement);
    seat 0 Forks it and the Fork resolves — the copy is on the stack, its
    offer made or waiting."""
    ours = [_permanent(name) for name in mine]
    others = [_permanent(name) for name in theirs]
    us = PlayerState(name="A", battlefield=list(ours), library=[_POOL["Island"]] * 10)
    them = PlayerState(name="B", battlefield=list(others), library=[_POOL["Island"]] * 10)
    game = Game(players=[us, them])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    game.start_priority_window(1)
    them.hand = [_POOL[spell]]
    us.hand = [_POOL["Fork"]]
    cast = game.queue_from_hand(1, spell, **announce(ours, others))
    assert cast.supported, cast.details
    original = game.stack[-1]
    game.priority_player_index = 0
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    game.resolve_top_of_stack()
    return game, original, ours, others


def _labels(game, item) -> list:
    from engine.stack_targets import target_label

    return [target_label(game, target) for target in chosen_targets(game, item) or ()]


def _copy(game):
    return next(item for item in game.stack if item.is_copy)


def _spite(ours, _others):
    return {"target_player_index": 0, "target_permanent_ids": [ours[0].permanent_id, ours[1].permanent_id]}


def test_a_person_re_aims_a_two_target_copy_slot_by_slot():
    """Reckless Spite ("Destroy two target nonblack creatures") at A's two
    creatures, Forked by A: asked twice, "keep" first each time. The first
    target moves to B's Hill Giant; the second is kept. The second prompt
    does not offer the creature the first now names (CR 115.3: one instance
    names each object once)."""
    game, _original, ours, others = _forked(
        "Reckless Spite", _spite,
        mine=("Grizzly Bears", "Gray Ogre"), theirs=("Hill Giant", "Craw Wurm"),
        interactive=True,
    )
    first = game.pending_choice_of("retarget_choice", 0)
    assert first is not None
    assert first.data["prompt"] == (
        "Choose a new target for the copy of Reckless Spite: target 1 of 2 "
        "(now A's Grizzly Bears), or keep it."
    )
    names = first.data["names"]
    assert names[0] == "Keep the original's target"
    giant = names.index("B's Hill Giant")
    assert game.confirm_retarget_choice(0, giant)
    second = game.pending_choice_of("retarget_choice", 0)
    assert second is not None and "target 2 of 2" in second.data["prompt"]
    assert "B's Hill Giant" not in second.data["names"]
    assert game.confirm_retarget_choice(0, 0)  # keep the Gray Ogre
    assert game.pending_choice_of("retarget_choice", 0) is None
    copy = _copy(game)
    assert _labels(game, copy) == ["B's Hill Giant", "A's Gray Ogre"]
    assert "Reckless Spite (copy) targets B's Hill Giant" in game.log
    game.resolve_top_of_stack()  # the copy
    assert not any(p is others[0] for p in game.controlled_by(1))
    assert not any(p is ours[1] for p in game.controlled_by(0))
    assert any(p is ours[0] for p in game.controlled_by(0))
    assert game.players[0].life == 15  # the copy's "You lose 5 life" is A's


def test_two_targets_of_one_instance_may_be_exchanged():
    """CR 115.7e: "only the final set of targets is evaluated". The first
    target moved onto what the second names leaves the second no "keep" —
    the two would name one creature — and it is offered the first's."""
    game, _original, ours, _others = _forked(
        "Reckless Spite", _spite,
        mine=("Grizzly Bears", "Gray Ogre"), theirs=("Hill Giant",),
        interactive=True,
    )
    first = game.pending_choice_of("retarget_choice", 0)
    assert game.confirm_retarget_choice(0, first.data["names"].index("A's Gray Ogre"))
    second = game.pending_choice_of("retarget_choice", 0)
    assert second is not None
    assert "Keep the original's target" not in second.data["names"]
    assert "another target of it now names that" in second.data["prompt"]
    assert game.confirm_retarget_choice(0, second.data["names"].index("A's Grizzly Bears"))
    assert _labels(game, _copy(game)) == ["A's Gray Ogre", "A's Grizzly Bears"]


def test_a_seat_nobody_asks_moves_both_targets_onto_the_other_side():
    game, _original, ours, others = _forked(
        "Reckless Spite", _spite,
        mine=("Grizzly Bears", "Gray Ogre"), theirs=("Hill Giant", "Craw Wurm"),
    )
    assert not game.pending_choices
    copy = _copy(game)
    assert sorted(_labels(game, copy)) == ["B's Craw Wurm", "B's Hill Giant"]
    settle(game)
    assert [p.card.name for p in game.controlled_by(1) if p.is_creature] == []


def test_a_modal_copy_keeps_its_mode_and_moves_its_target():
    """Funeral Charm's second mode ("Target creature gets +2/-1 until end of
    turn") at A's Llanowar Elves, Forked by A: the copy is still that mode
    (CR 115.8, 700.2g) and is aimed at B's Llanowar Elves, which dies."""
    def announce(ours, _others):
        return {"mode_index": 1, "target_player_index": 0,
                "target_permanent_ids": [ours[0].permanent_id]}

    game, original, ours, others = _forked(
        "Funeral Charm", announce,
        mine=("Llanowar Elves", "Hill Giant"), theirs=("Llanowar Elves", "Hill Giant"),
    )
    copy = _copy(game)
    assert copy.chosen_mode_index == original.chosen_mode_index == 1
    assert _labels(game, copy) != _labels(game, original)
    settle(game)
    assert not any(p is others[0] for p in game.controlled_by(1)), game.log[-8:]


def test_a_person_is_asked_for_a_modal_copys_target():
    def announce(ours, _others):
        return {"mode_index": 1, "target_player_index": 0,
                "target_permanent_ids": [ours[0].permanent_id]}

    game, _original, ours, others = _forked(
        "Funeral Charm", announce,
        mine=("Llanowar Elves",), theirs=("Llanowar Elves",), interactive=True,
    )
    prompt = game.pending_choice_of("retarget_choice", 0)
    assert prompt is not None
    assert prompt.data["prompt"] == (
        "Choose a new target for the copy of Funeral Charm "
        "(now A's Llanowar Elves), or keep it."
    )
    assert game.confirm_retarget_choice(0, prompt.data["names"].index("B's Llanowar Elves"))
    settle(game)
    assert not any(p is others[0] for p in game.controlled_by(1))


def test_a_divided_copys_one_target_is_moved_with_its_share():
    """Fireball (X=2) at A's Gray Ogre: its one target is an entry of its
    division (CR 115.7f keeps the share with the slot). The seat nobody asks
    moves it to B's Gray Ogre — and the 2 damage goes there."""
    def announce(_ours, _others):
        return {"x_value": 2, "divided_targets": [(0, 0)]}

    game, _original, ours, others = _forked(
        "Fireball", announce, mine=("Gray Ogre",), theirs=("Gray Ogre",),
    )
    copy = _copy(game)
    assert _labels(game, copy) == ["B's Gray Ogre"]
    game.resolve_top_of_stack()  # the copy
    assert others[0].damage_marked == 2 or not any(
        p is others[0] for p in game.controlled_by(1)
    )
    assert ours[0].damage_marked == 0


def test_a_slot_list_of_one_description_is_re_aimed():
    """Consume Strength ("Target creature gets +2/+2 … Another target
    creature gets -2/-2"): two printed instances of one description, which
    ``change_slots`` refused as "target" printed twice. B pumps its Bears and
    shrinks A's Gray Ogre; A's copy pumps A's creature and shrinks B's."""
    def announce(ours, others):
        return {"target_player_index": 1,
                "target_permanent_ids": [others[0].permanent_id, ours[0].permanent_id]}

    game, _original, ours, others = _forked(
        "Consume Strength", announce,
        mine=("Gray Ogre",), theirs=("Grizzly Bears",),
    )
    copy = _copy(game)
    assert _labels(game, copy) == ["A's Gray Ogre", "B's Grizzly Bears"]
