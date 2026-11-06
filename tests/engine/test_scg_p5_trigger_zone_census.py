"""Census: a triggered ability fires only from the zone it functions in
(CR 113.6, 113.6m).

    113.6m An ability whose cost or effect specifies that it moves the object
    it's on out of a particular zone functions only in that zone, unless its
    trigger condition or a previous part of its cost or effect specifies that
    the object is put into that zone …

The lowering stamps that zone on the instruction (``functions_from``), and the
exile register has its own reading (``exiled_records.functions_in_exile``:
"if this card is exiled", All Hallow's Eve). The graveyard scan
(``events.graveyard_trigger_events``) asked the stamp; the battlefield scans
never did. So in Scourge's post-promotion browser session Dragon Wings,
attached to a Shivan Dragon, offered "return this card from your graveyard"
each time a big creature entered, and the Yes resolved as "Dragon Wings was no
longer in the graveyard" — and Squee, Goblin Nabob on the battlefield fired
its own upkeep trigger.

The population is derived, never listed: every triggered ability in the pool
(both manifest roles, every face) whose instruction states a zone other than
the battlefield, on a card that can be a permanent. For each, both directions:

* **from the battlefield** — the card on the battlefield (an Aura attached to
  a creature), its trigger event made to happen: nothing of that ability is
  collected, and nothing of it is put on the stack;
* **from its own zone** — the same card in its owner's graveyard, the same
  event: the ability is collected.

"Collected" is ``Game._enqueue_triggered_ability`` being handed the ability,
which is before CR 603.4's intervening-if (Krovikan Horror needs a creature
card above it, Silversmote Ghoul a life gain): the question is which zone the
engine fired the ability from, not whether its own condition then held. The
battlefield half also watches ``Game._stack_push`` itself, because the attack,
block and entry fire sites build their own stack objects.

How a trigger event is made to happen is a table keyed by the condition kind,
and a stamped trigger whose kind is not in it fails the census — a new kind is
a new event somebody has to say how to drive.

The exile half is the other reader's: a card held in the exile register for a
reason of its own (Three Wishes' face-down exile) with an ordinary upkeep
trigger (Juzám Djinn) fires nothing from there, and All Hallow's Eve, whose
trigger says "if this card is exiled", does.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.exiled_records import record_exiled_card
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.trigger_utils import trigger_functions_from

BATTLEFIELD = "battlefield"


def _pool():
    return load_cards(manifest_set_paths(include_measured=True))


def _by_name():
    return {card.name: card for card in _pool()}


def _is_permanent_card(card) -> bool:
    line = (card.type_line or "").lower()
    return not ("instant" in line or "sorcery" in line)


def _stamped_population():
    """``(card, trigger)`` for every trigger stating a zone other than the
    battlefield, on a card that can be a permanent."""
    rows = []
    seen = set()
    for card in compilation_units(_pool()):
        if card.name in seen:
            continue
        seen.add(card.name)
        for trig in compile_card_oracle(card).triggered_abilities:
            if trig.instruction is None:
                continue
            zone = trigger_functions_from(trig)
            if zone == BATTLEFIELD:
                continue
            rows.append((card, trig, zone))
    return rows


def _game(by_name):
    forests = [by_name["Forest"]] * 10
    me = PlayerState(name="Me", library=list(forests))
    opp = PlayerState(name="Opp", library=list(forests))
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    return game


class _Watch:
    """What reached the two seams for one ability of one card."""

    def __init__(self, game, card, trig):
        self.card = card
        self.text = trig.source_line
        self.collected = 0
        self.pushed = 0
        enqueue = game._enqueue_triggered_ability
        push = game._stack_push

        def watched_enqueue(**event):
            if self._ours(event.get("card"), event.get("source_permanent"),
                          event.get("ability_text")):
                self.collected += 1
            return enqueue(**event)

        def watched_push(item=None, **kwargs):
            if item is not None and item.is_ability and self._ours(
                item.card, item.source_permanent, item.ability_text,
            ):
                self.pushed += 1
            return push(item, **kwargs)

        game._enqueue_triggered_ability = watched_enqueue
        game._stack_push = watched_push

    def _ours(self, card, source, text) -> bool:
        named = getattr(card, "name", None) or getattr(
            getattr(source, "card", None), "name", None
        )
        return named == self.card.name and (text or "") == (self.text or "")


def _drive(game, by_name, kind: str) -> None:
    """Make the trigger event of *kind* happen with seat 0 active."""
    if kind == "upkeep_self":
        game.start_turn(0)
    elif kind in ("end_step", "end_step_self"):
        game.start_turn(0)
        game.resolve_end_step(0)
    elif kind == "matching_permanent_enters":
        # A creature with mana value 6 that is a Dragon: what each stamped
        # entry condition in the pool names (the Dragon Auras' "a creature
        # with mana value 6 or greater", Bladewing's Thrall's "a Dragon").
        game.start_turn(0)
        game._put_permanent_onto_battlefield(
            0, Permanent(card=by_name["Shivan Dragon"]), None
        )
    else:  # pragma: no cover - the census's own completeness
        raise AssertionError(f"no way to drive {kind!r}: add it to _drive")


DRIVEN = ("upkeep_self", "end_step", "end_step_self", "matching_permanent_enters")


def test_the_population_is_the_one_the_census_drives():
    """Floor and completeness: the census examined something, and every
    stamped trigger's event is one it knows how to make happen."""
    rows = _stamped_population()
    permanents = [row for row in rows if _is_permanent_card(row[0])]
    assert len(permanents) >= 14, [row[0].name for row in permanents]
    undriven = sorted(
        {row[1].condition.kind for row in permanents} - set(DRIVEN)
    )
    assert not undriven, undriven


def test_no_trigger_that_functions_elsewhere_fires_from_the_battlefield():
    by_name = _by_name()
    fired = []
    examined = 0
    for card, trig, zone in _stamped_population():
        if not _is_permanent_card(card) or zone != "graveyard":
            continue
        game = _game(by_name)
        if "aura" in (card.type_line or "").lower():
            host = Permanent(card=by_name["Grizzly Bears"])
            game._put_permanent_onto_battlefield(0, host, None)
            aura = Permanent(card=card)
            game._put_permanent_onto_battlefield(0, aura, None)
            attach_aura(aura, host)
            game._recompute_continuous_effects()
        else:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(0, permanent, None)
            # A */* or 0/0 creature (Ghastly Remains' amplify) would die to
            # CR 704.5f and fire from the graveyard for real.
            game.place_plus1_counters(permanent, 3)
        game.stack.clear()
        watch = _Watch(game, card, trig)
        _drive(game, by_name, trig.condition.kind)
        assert any(
            held.card is card for held in game.all_permanents()
        ), f"{card.name} left the battlefield: the census asked nothing of it"
        examined += 1
        if watch.collected or watch.pushed:
            fired.append((card.name, trig.condition.kind, watch.collected, watch.pushed))
    assert examined >= 14
    assert not fired, (
        f"{len(fired)} of {examined} triggers that function from a graveyard "
        f"fired from the battlefield (CR 113.6m): {fired}"
    )


def test_every_trigger_that_functions_from_a_graveyard_still_fires_there():
    by_name = _by_name()
    silent = []
    examined = 0
    for card, trig, zone in _stamped_population():
        if not _is_permanent_card(card) or zone != "graveyard":
            continue
        game = _game(by_name)
        game.players[0].graveyard.append(card)
        if trig.condition.kind in ("end_step", "end_step_self"):
            # The end-step graveyard scan asks CR 603.4's intervening-if
            # before it collects (``EndStepMixin._begin_end_step``), so the
            # two the pool prints are made true: a creature card directly
            # above it (Krovikan Horror) and 3 life gained this turn
            # (Silversmote Ghoul).
            game.players[0].graveyard.append(by_name["Grizzly Bears"])
            game.start_turn(0)
            game._gain_life(game.players[0], 3)
            watch = _Watch(game, card, trig)
            game.resolve_end_step(0)
        else:
            watch = _Watch(game, card, trig)
            _drive(game, by_name, trig.condition.kind)
        examined += 1
        if not watch.collected:
            silent.append((card.name, trig.condition.kind))
    assert examined >= 14
    assert not silent, silent


@pytest.mark.parametrize("name,fires", [("Juzám Djinn", False), ("All Hallow's Eve", True)])
def test_an_exiled_card_fires_only_what_functions_in_exile(name, fires):
    """Juzám Djinn held in the exile register face down (Three Wishes' road)
    deals no damage from there; All Hallow's Eve, "if this card is exiled with
    a scream counter on it", is the one upkeep trigger that works from
    exile."""
    by_name = _by_name()
    card = by_name[name]
    game = _game(by_name)
    game.players[0].exile.append(card)
    record_exiled_card(
        game, card, 0, face_down=(name == "Juzám Djinn"),
        counters={"scream": 2} if name == "All Hallow's Eve" else None,
    )
    (trig,) = [
        t for t in compile_card_oracle(card).triggered_abilities
        if t.condition.kind == "upkeep_self"
    ]
    watch = _Watch(game, card, trig)
    game.start_turn(0)
    assert bool(watch.collected) is fires
