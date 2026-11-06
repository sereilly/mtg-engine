"""Census: an ability that triggers while a triggered ability is being put on
the stack goes on in the next round of CR 603.3b, above it, and sees that
ability's target already chosen.

    603.3b … Then the game once again checks for and performs state-based
    actions until none are performed, then abilities that triggered during
    this process go on the stack. This process repeats until no new
    state-based actions are performed and no abilities trigger.

When Bladewing the Risen entered with Grip of Chaos out ("Whenever a spell or
ability is put onto the stack, if it has a single target, reselect its target
at random"), Grip's trigger was offered in the same "order your triggered
abilities" prompt as Bladewing's entry trigger, so its controller could put
Grip underneath — where it resolves after the ability it was meant to re-aim
(Scourge's post-promotion session).

**The population is every watcher in the pool whose event an announcement
makes while a triggered ability is put on the stack**: every triggered ability
whose condition is "becomes the target" (``self_becomes_target``), "a player
chooses one or more targets" (``player_chooses_targets``) or "a spell or
ability is put onto the stack" (``spell_or_ability_put_onto_stack``) — the
three events ``_announce_targeting``, ``announce_targets_chosen`` and
``announce_put_onto_stack`` emit. Each watcher is put on its controller's
battlefield (an Aura on a creature it enchants) and a Flametongue Kavu's entry
trigger ("deals 4 damage to target creature") is aimed at the watcher's
creature — by the watcher's own controller, so the two could be ordered
together, and by the opponent, for "an opponent controls". Two roads for the
target: named as the Kavu is cast (the entry trigger carries it), and chosen
at the entry trigger's own prompt by an asked seat.

Of every watcher that fired: its trigger is of a later round than the entry
trigger, sits above it on the stack, shares no ordering prompt with it, and
saw the entry trigger's target already chosen when it was put on the stack.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import target_ids
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.trigger_order import is_triggered_object

WATCHED = frozenset({
    "self_becomes_target", "player_chooses_targets", "spell_or_ability_put_onto_stack",
})
KAVU = "Flametongue Kavu"


def _pool():
    return load_cards(manifest_set_paths())


def _watchers():
    seen = set()
    rows = []
    for card in compilation_units(_pool()):
        if card.name in seen:
            continue
        seen.add(card.name)
        if any(
            trig.condition.kind in WATCHED
            for trig in compile_card_oracle(card).triggered_abilities
        ):
            rows.append(card)
    return rows


def _table(by_name, watcher, watcher_seat):
    game = Game(players=[
        PlayerState(name="P1", library=[by_name["Mountain"]] * 10,
                    graveyard=[by_name["Shivan Dragon"]]),
        PlayerState(name="P2", library=[by_name["Mountain"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    line = (watcher.type_line or "").lower()
    if "creature" in line:
        target = Permanent(card=watcher)
        game._put_permanent_onto_battlefield(watcher_seat, target, None)
    else:
        target = Permanent(card=by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(watcher_seat, target, None)
        source = Permanent(card=watcher)
        game._put_permanent_onto_battlefield(watcher_seat, source, None)
        if "aura" in line:
            attach_aura(source, target)
            game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    return game, target


class _Watch:
    """Each triggered ability of the watcher's card put on the stack, with
    what the Kavu's entry trigger had chosen at that moment."""

    def __init__(self, game, watcher):
        self.pushed: list = []
        push = game._stack_push

        def watched(item=None, **kwargs):
            if item is not None and is_triggered_object(item) and (
                item.card.name == watcher.name
            ):
                kavu = next(
                    (entry for entry in game.stack if _is_kavu_trigger(entry)), None,
                )
                self.pushed.append((item, None if kavu is None else tuple(
                    target_ids(kavu.target_permanent_id)
                )))
            return push(item, **kwargs)

        game._stack_push = watched


def _round(item) -> int:
    return int(getattr(item, "trigger_round", 0) or 0)


def _is_kavu_trigger(item) -> bool:
    return is_triggered_object(item) and item.card.name == KAVU


def _drive(game, by_name, target, kavu_seat, *, asked: bool):
    if asked:
        game.interactive_seats = {0, 1}
        game._put_permanent_onto_battlefield(kavu_seat, Permanent(card=by_name[KAVU]), None)
        choice = game.pending_choice_of("trigger_target", kavu_seat)
        if choice is None:
            return False
        if not game.confirm_trigger_target(kavu_seat, permanent_id=target.permanent_id):
            return False
        return True
    game.interactive_seats = {0, 1}
    game.players[kavu_seat].hand.append(by_name[KAVU])
    cast = game.queue_from_hand(
        kavu_seat, KAVU, target_permanent_ids=[target.permanent_id],
    )
    if not cast.supported:
        return False
    # The Kavu spell alone: its entry trigger goes on the stack carrying the
    # target the cast named, and what that sets off goes on with it.
    game.resolve_top_of_stack()
    return True


def _problems(game, watch):
    kavu = next((item for item in game.stack if _is_kavu_trigger(item)), None)
    if kavu is None:
        return None, []
    problems = []
    fired = [item for item, _seen in watch.pushed if any(e is item for e in game.stack)]
    for item, seen in watch.pushed:
        if not any(entry is item for entry in game.stack):
            continue
        if _round(item) <= _round(kavu):
            problems.append(f"round {_round(item)} beside the entry trigger's {_round(kavu)}")
        if game.stack.index(item) < game.stack.index(kavu):
            problems.append("below the entry trigger it triggered off")
        if not seen:
            problems.append("put on the stack before the entry trigger's target was chosen")
    for choice in game.pending_choices:
        if choice.kind != "order_triggers":
            continue
        held = choice.data.get("_trigger_items") or ()
        if any(entry is kavu for entry in held) and any(
            any(entry is item for entry in held) for item in fired
        ):
            problems.append("offered in the entry trigger's ordering prompt")
    return bool(fired), problems


@pytest.mark.parametrize("asked", (False, True), ids=("named_on_cast", "asked"))
def test_a_trigger_set_off_by_putting_a_trigger_on_the_stack_is_the_next_round(asked):
    pool = _pool()
    by_name = {card.name: card for card in pool}
    watchers = _watchers()
    assert len(watchers) >= 20, len(watchers)
    failures = []
    fired = 0
    for watcher in watchers:
        for kavu_seat in (0, 1):
            game, target = _table(by_name, watcher, 0)
            watch = _Watch(game, watcher)
            if not _drive(game, by_name, target, kavu_seat, asked=asked):
                continue
            did, problems = _problems(game, watch)
            if did:
                fired += 1
            if problems:
                failures.append((watcher.name, kavu_seat, problems))
    assert fired >= 12, fired
    assert not failures, (
        f"{len(failures)} watcher drives went on in the round that set them off:\n"
        + "\n".join(f"  {name} (Kavu at seat {seat}): {p}" for name, seat, p in failures)
    )
