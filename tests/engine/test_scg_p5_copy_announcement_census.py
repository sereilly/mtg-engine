"""Census: a copy is announced once, after its targets are decided, for the
targets it has (CR 707.10, 707.10c).

    707.10c Some effects copy a spell or ability and state that its
    controller may choose new targets for the copy. … Once the player has
    decided what the copy's targets will be, the copy is put onto the stack
    with those targets.

A copy was pushed (``_stack_push``), the push announced "becomes the target"
for the original's targets and "is put onto the stack" (Grip of Chaos), and
only then was it offered a new target — whose answer announced "becomes the
target" again, for the new one. Scattershot with storm count 7 aimed at Daru
Spiritualist ("whenever a Cleric creature you control becomes the target of a
spell or ability, it gets +0/+2") fired Daru seven times before the re-aim
prompt, and the two copies re-aimed at Zealous Inquisitor fired again for it
(Scourge's post-promotion session; Daru ended 1/17).

**Every road that makes a copy and lets someone choose its targets**, each
under an interactive seat (every pairing of kept and re-aimed) and a headless
one (its measured default):

* storm (``copy_triggering_spell`` with a count) — Scattershot, two copies;
* the trigger copies (``copy_triggering_spell``) — Double Vision;
* Fork with no target named on the cast, and with one named
  (``copy_top_stack_spell``) — headless, its measured default, as the
  trigger copies' (kg4: it kept the original's);
* Chain Lightning's copy (``copy_this_spell``);
* Radiate (``copy_spell_for_each_other_target``), whose copies' targets the
  effect assigns (CR 707.10d).

Counted per copy, at the three seams every announcement goes through:
``_announce_targeting`` ("becomes the target") exactly once, for the targets
the copy has when the road is done; ``announce_put_onto_stack`` exactly once,
after it; and "a player chooses targets" (Psychic Battle) once where the
copy's controller moved a target and never where the original's were kept
or the effect assigned them.
"""

from __future__ import annotations

import itertools

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.game_types import target_ids
from engine.models import Permanent
from tests.helpers import resolve_stack


def _pool():
    return {card.name: card for card in load_cards(manifest_set_paths(include_measured=True))}


class _Watch:
    """Every announcement made for a copy, with the targets it had then."""

    def __init__(self, game):
        self.game = game
        self.targeting: list = []
        self.put: list = []
        self.chose: list = []
        targeting = game._announce_targeting
        put = game.announce_put_onto_stack
        chose = game.announce_targets_chosen

        def watched_targeting(item):
            if getattr(item, "is_copy", False):
                self.targeting.append((item, _aim(item)))
            return targeting(item)

        def watched_put(item):
            if getattr(item, "is_copy", False):
                self.put.append((item, _aim(item)))
            return put(item)

        def watched_chose(item, **kwargs):
            if getattr(item, "is_copy", False) and not kwargs.get("at_random"):
                from engine.stack_targets import has_targets

                if has_targets(game, item):
                    self.chose.append(item)
            return chose(item, **kwargs)

        game._announce_targeting = watched_targeting
        game.announce_put_onto_stack = watched_put
        game.announce_targets_chosen = watched_chose

    def of(self, rows, copy):
        return [aim for item, aim in rows if item is copy]


def _aim(item):
    return (item.target_player_index if not target_ids(item.target_permanent_id) else None,
            tuple(target_ids(item.target_permanent_id)))


def _table(pool, *, mine=(), theirs=(), hand=(), interactive=()):
    game = Game(players=[
        PlayerState(name="P1", hand=[pool[name] for name in hand],
                    library=[pool["Mountain"]] * 10),
        PlayerState(name="P2", library=[pool["Mountain"]] * 10),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    game.start_turn(0)
    game._close_current_priority_step()
    game.interactive_seats = set(interactive)
    return game


def _bears(game):
    return [perm for perm in game.players[1].battlefield if perm.card.name == "Grizzly Bears"]


def _answer_copy_prompts(game, seat, plan, other_id):
    """Answer each ``copy_spell_target`` offer of *seat* in queue order: keep,
    or re-aim at *other_id*, as *plan* says. Returns how many were asked."""
    asked = 0
    for reaim in plan:
        offer = next(
            (choice for choice in game.pending_choices
             if choice.kind == "copy_spell_target" and choice.player_index == seat),
            None,
        )
        if offer is None:
            break
        asked += 1
        if reaim:
            assert game.confirm_copy_spell_target(seat, permanent_id=other_id)
        else:
            assert game.confirm_copy_spell_target(seat, keep=True)
    return asked


def _check(watch, copies, *, moved):
    """The per-copy counts. *moved* maps each copy to whether its controller
    moved its target, or None when that is the road's to say (headless)."""
    assert copies, "the road made no copy"
    for copy in copies:
        final = _aim(copy)
        targeted = watch.of(watch.targeting, copy)
        put = watch.of(watch.put, copy)
        assert targeted == [final], (copy.card.name, targeted, final)
        assert put == [final], (copy.card.name, put, final)
        chose = sum(1 for item in watch.chose if item is copy)
        expected = moved.get(id(copy))
        if expected is not None:
            assert chose == (1 if expected else 0), (copy.card.name, chose, expected)
        else:
            assert chose <= 1


def _storm(pool, plan, interactive):
    game = _table(
        pool, theirs=["Grizzly Bears", "Grizzly Bears"],
        hand=["Dark Ritual", "Dark Ritual", "Scattershot"],
        interactive={0} if interactive else (),
    )
    for _ in range(2):
        assert game.queue_from_hand(0, "Dark Ritual").supported
        resolve_stack(game)
    first, other = _bears(game)
    watch = _Watch(game)
    assert game.queue_from_hand(
        0, "Scattershot", target_permanent_ids=[first.permanent_id],
    ).supported
    game.resolve_top_of_stack()  # the storm trigger
    return game, watch, first, other


def _copies(game):
    return [item for item in game.stack if item.is_copy]


PLANS = list(itertools.product((False, True), repeat=2))


@pytest.mark.parametrize("plan", PLANS)
def test_storm_copies_announce_once_after_the_choice(plan):
    pool = _pool()
    game, watch, first, other = _storm(pool, plan, interactive=True)
    copies = _copies(game)
    assert len(copies) == 2
    # Nothing announced for a copy before its controller answers.
    assert not watch.targeting and not watch.put
    assert _answer_copy_prompts(game, 0, plan, other.permanent_id) == 2
    _check(watch, copies, moved={id(copy): reaim for copy, reaim in zip(copies, plan)})


def test_storm_copies_headless():
    pool = _pool()
    game, watch, _first, _other = _storm(pool, None, interactive=False)
    game.auto_resolve_pending_choices()
    _check(watch, _copies(game), moved={})


def _double_vision(pool, interactive):
    game = _table(
        pool, mine=["Double Vision"], theirs=["Grizzly Bears", "Grizzly Bears"],
        hand=["Lightning Bolt"], interactive={0} if interactive else (),
    )
    first, other = _bears(game)
    watch = _Watch(game)
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[first.permanent_id],
    ).supported
    game.resolve_top_of_stack()  # Double Vision's trigger
    return game, watch, first, other


@pytest.mark.parametrize("reaim", (False, True))
def test_a_trigger_copy_announces_once_after_the_choice(reaim):
    pool = _pool()
    game, watch, _first, other = _double_vision(pool, True)
    copies = _copies(game)
    assert len(copies) == 1 and not watch.targeting and not watch.put
    assert _answer_copy_prompts(game, 0, [reaim], other.permanent_id) == 1
    _check(watch, copies, moved={id(copies[0]): reaim})


def test_a_trigger_copy_headless():
    pool = _pool()
    game, watch, _first, _other = _double_vision(pool, False)
    game.auto_resolve_pending_choices()
    _check(watch, _copies(game), moved={})


def _fork(pool, interactive, *, named=False):
    game = _table(
        pool, theirs=["Grizzly Bears", "Grizzly Bears"],
        hand=["Lightning Bolt", "Fork"], interactive={0} if interactive else (),
    )
    first, other = _bears(game)
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[first.permanent_id],
    ).supported
    watch = _Watch(game)
    kwargs = {"target_stack_index": 0}
    if named:
        kwargs.update(target_permanent_ids=[other.permanent_id])
    assert game.queue_from_hand(0, "Fork", **kwargs).supported, kwargs
    game.resolve_top_of_stack()  # Fork
    return game, watch, first, other


@pytest.mark.parametrize("reaim", (False, True))
def test_fork_with_no_target_named_announces_its_copy_once(reaim):
    pool = _pool()
    game, watch, _first, other = _fork(pool, True)
    copies = _copies(game)
    assert len(copies) == 1 and not watch.of(watch.targeting, copies[0])
    assert _answer_copy_prompts(game, 0, [reaim], other.permanent_id) == 1
    _check(watch, copies, moved={id(copies[0]): reaim})


def test_fork_headless_takes_the_measured_answer_and_announces_once():
    """A seat nobody asks takes the measured answer (kg4): the copy of a Bolt
    already aimed at one Bears is re-aimed at the other, and announced once,
    for that target."""
    pool = _pool()
    game, watch, _first, other = _fork(pool, False)
    copies = _copies(game)
    assert [_aim(copy)[1] for copy in copies] == [(other.permanent_id,)]
    _check(watch, copies, moved={id(copies[0]): True})


@pytest.mark.parametrize("interactive", (False, True))
def test_fork_with_a_target_named_on_the_cast_announces_it_once(interactive):
    pool = _pool()
    game, watch, _first, other = _fork(pool, interactive, named=True)
    copies = _copies(game)
    assert [_aim(copy)[1] for copy in copies] == [(other.permanent_id,)]
    _check(watch, copies, moved={id(copies[0]): True})


@pytest.mark.parametrize("reaim", (False, True))
def test_chain_lightnings_copy_announces_once_after_the_choice(reaim):
    pool = _pool()
    game = _table(pool, theirs=["Mountain", "Mountain"], hand=["Chain Lightning"])
    game.interactive_seats = {1}
    watch = _Watch(game)
    game.cast_from_hand(0, "Chain Lightning", target_player_index=1)
    game.confirm_optional_pay(1, accept=True)   # the {R}{R}
    game.confirm_optional_pay(1, accept=True)   # "they may copy this spell"
    copies = _copies(game)
    assert len(copies) == 1 and not watch.of(watch.targeting, copies[0])
    offer = next(c for c in game.pending_choices if c.kind == "copy_spell_target")
    if reaim:
        assert game.confirm_copy_spell_target(1, target_seat=0)
    else:
        assert game.confirm_copy_spell_target(1, keep=True)
    assert offer not in game.pending_choices
    _check(watch, copies, moved={id(copies[0]): reaim})


def test_radiate_copies_announce_once_with_the_targets_the_effect_assigns():
    pool = _pool()
    game = _table(
        pool, theirs=["Grizzly Bears", "Grizzly Bears", "Hill Giant"],
        hand=["Lightning Bolt", "Radiate"],
    )
    first, _other = _bears(game)
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[first.permanent_id],
    ).supported
    watch = _Watch(game)
    assert game.queue_from_hand(0, "Radiate", target_stack_index=0).supported
    game.resolve_top_of_stack()
    copies = _copies(game)
    assert len(copies) >= 3
    _check(watch, copies, moved={id(copy): False for copy in copies})
