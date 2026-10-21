"""Census: one event, one controller, two or more triggered abilities — and
the controller is asked their order (CR 603.3b).

Every scenario is a sample of real pool cards on one interactive seat's
battlefield, set off through the engine's own event:

* ``upkeep``  — the seat's upkeep (``resolve_upkeep``, priority deferred):
  each card printing two upkeep triggers alone (Tangle Wire, Smokestack,
  Tetravus), and sampled pairs of upkeep-trigger permanents;
* ``end``     — the end step, sampled pairs;
* ``entry``   — a permanent printing two entry triggers entering alone
  (Marsh Crocodile, the Battlemages), and sampled pairs of an observer of
  entries with an entrant that has its own;
* ``dies``    — sampled pairs of creatures with death triggers, one sweeper;
* ``attacks`` — sampled pairs of creatures with attack triggers, declared
  together.

A **moment** is everything pushed between two resolutions — CR 603.3b's "since
the last time a player received priority", as far as a headless table shows it.
A scenario counts when seat 0 had two or more *distinguishable* triggers
(:func:`engine.trigger_order.interchangeable` says which are not) pushed in one
moment; for each, an ``order_triggers`` prompt must have been armed for seat 0
in that moment, and answering it in reverse must reverse those objects on the
stack. On the tree before round 4 every family counted and none was asked —
45 of the 79 scenarios here, 0 asked (119 of 219 at forty a family, 0 asked)
— which is the defect this names; round 4 asks all 45. The floors are on what
was counted, because a census that reaches nothing passes.

The second half of the rule (abilities whose trigger condition is another
ability triggering go on in a second round) has no card behind it: the last
test here holds that at zero, so the card that would need the round is named
by a failure rather than by nobody.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict

import pytest

from engine import Game
from engine.faces import compilation_units
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

#: Pairs sampled per family. Small on purpose: the families are the census,
#: the sample is what keeps it a few seconds rather than a few minutes.
SAMPLE = 12

#: What each family must count (scenarios with a choice to make). Measured
#: at SAMPLE = 12, the same before and after round 4: upkeep 9, end 5,
#: entry 10, dies 10, attacks 11 — on an unscreened draw.
#:
#: Since Torment's promotion rehearsal the pairs are drawn from cards that
#: fire alone (``_scenarios``' *fires*), so a pair family reaches nearly its
#: whole sample: measured upkeep 15 / 16, end 12 / 12, dies 12 / 12, attacks
#: 10 / 10 (two pairs each hold an "attacks alone" trigger, which fires alone
#: and rightly not beside a second attacker), entry 10 / 11 (unscreened: an
#: observer fires only for the entrant it describes) — without and with
#: Torment shipped. Two under the lower of each, and never below the floor
#: the family had before.
FLOORS = {"upkeep": 13, "end": 10, "entry": 8, "dies": 10, "attacks": 9}


def _kinds(card):
    program = compile_card_oracle(card)
    if not program.supported:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for trig in program.triggered_abilities:
        if trig.supported and trig.instruction is not None:
            counts[trig.condition.kind] += 1
    return counts


def _is_creature(card) -> bool:
    return "Creature" in (card.type_line or "")


def _scenarios(cards: dict, family: str, fires=None) -> list[dict]:
    """The family's scenarios. *fires* (a card name -> bool) screens the
    cards a **pair** is drawn from: only cards that put a trigger on the
    stack for seat 0 at this family's event when alone on the census board.

    Without it a pair was two cards that *print* a trigger of the kind, and
    most such triggers are conditional on a board this census does not set
    up ("if you control no untapped lands", "if a creature died this turn",
    "at the beginning of each opponent's upkeep") — so how many pairs owed an
    order was a fact about which cards the seeded draw happened to pick, and
    every ingest redrew it. Torment's promotion rehearsal is where that
    showed: no card's behaviour changed, the pool gained 143 names, and the
    draw that had reached 5 of 12 end-step pairs reached 3 (upkeep: 9 of 22
    scenarios, then 6 of 23), under floors of 4 and 7. Each pair it lost was
    read: a conditional trigger beside a card that makes the condition false
    (Thran Quarry's "if you control no creatures" beside Asmira, Osai
    Vultures' "if a creature died this turn"). Screened, every pair drawn is
    two triggers at once by construction, and a pair that then owes nothing
    is a finding rather than the noise — the ones that do are an "attacks
    alone" trigger beside a second attacker, and two fading upkeeps
    ``trigger_order.interchangeable`` rightly does not ask about.
    """
    rng = random.Random(6033)
    by_kind: dict[str, list[str]] = defaultdict(list)
    for name in sorted(cards):
        for kind in _kinds(cards[name]):
            by_kind[kind].append(name)

    def pairs(pool, k):
        pool = sorted(set(pool))
        if fires is not None:
            # Screened in a seeded order, and only as far as the draw needs:
            # twice the pairs' worth of cards that fire is enough to draw *k*
            # distinct pairs from, and screening the whole family would cost a
            # game per card printing the kind.
            order = list(pool)
            rng.shuffle(order)
            firing: list[str] = []
            for name in order:
                if len(firing) >= 2 * k:
                    break
                if fires(name):
                    firing.append(name)
            pool = sorted(firing)
        out: set = set()
        while len(out) < min(k, len(pool) * (len(pool) - 1) // 2):
            a, b = rng.sample(pool, 2)
            out.add(tuple(sorted((a, b))))
        return [list(pair) for pair in sorted(out)]

    if family == "upkeep":
        upkeep = by_kind["upkeep_self"] + by_kind["upkeep_each"]
        alone = [
            [name] for name in sorted(set(upkeep))
            if _kinds(cards[name]).get("upkeep_self", 0)
            + _kinds(cards[name]).get("upkeep_each", 0) >= 2
        ]
        return [{"board": board} for board in alone + pairs(upkeep, SAMPLE)]
    if family == "end":
        end = by_kind["end_step"] + by_kind["end_step_self"]
        return [{"board": board} for board in pairs(end, SAMPLE)]
    if family == "entry":
        alone = [
            {"board": [], "enters": name}
            for name in sorted(set(by_kind["enters_battlefield"]))
            if _kinds(cards[name]).get("enters_battlefield", 0) >= 2
        ]
        observers = sorted(set(by_kind["matching_permanent_enters"]))
        entrants = sorted(
            name for name in set(by_kind["enters_battlefield"])
            if _is_creature(cards[name])
        )
        return alone + [
            {"board": [rng.choice(observers)], "enters": rng.choice(entrants)}
            for _ in range(SAMPLE)
        ]
    if family == "dies":
        dies = [name for name in by_kind["dies"] if _is_creature(cards[name])]
        return [{"board": board} for board in pairs(dies, SAMPLE)]
    if family == "attacks":
        attacks = [
            name for name in by_kind["creature_attacks"] if _is_creature(cards[name])
        ]
        return [{"board": board} for board in pairs(attacks, SAMPLE)]
    raise AssertionError(family)


class _Recorder:
    """Every triggered object pushed, with the moment it was pushed in, and
    every ``order_triggers`` prompt armed — by wrapping the push, the
    resolution and the arming, which every tree has."""

    def __init__(self, monkeypatch):
        self.moment = 0
        self.on = False
        self.pushes: list[tuple[int, object]] = []
        self.asked: list[tuple[int, int, object]] = []
        push, resolve, arm = (
            Game._stack_push, Game.resolve_top_of_stack, Game.arm_pending_choice,
        )

        def _push(game, item=None, **kwargs):
            result = push(game, item, **kwargs)
            # Recorded as it goes on — not asked again at the end, because a
            # table that never stops resolves them in the same call (the
            # sweeper's own cast), and "on the stack afterwards" would count
            # only the trees that hold them.
            if (
                self.on and item is not None and item.is_ability
                and not item.activated and not item.is_copy
                and any(entry is item for entry in game.stack)
            ):
                self.pushes.append((self.moment, item))
            return result

        def _resolve(game, *args, **kwargs):
            self.moment += 1
            return resolve(game, *args, **kwargs)

        def _arm(game, kind, player_index, **data):
            choice = arm(game, kind, player_index, **data)
            if self.on and kind == "order_triggers":
                self.asked.append((self.moment, player_index, choice))
            return choice

        monkeypatch.setattr(Game, "_stack_push", _push)
        monkeypatch.setattr(Game, "resolve_top_of_stack", _resolve)
        monkeypatch.setattr(Game, "arm_pending_choice", _arm)


def _game(cards) -> Game:
    game = Game(players=[PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    for player in game.players:
        player.library = [cards["Island"]] * 20
    game.begin_turn_bookkeeping(0)
    return game


def _put(game, cards, seat, name) -> Permanent:
    permanent = Permanent(card=cards[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _clear(game) -> None:
    game.stack.clear()
    game.pending_choices.clear()
    game.pending_replacement_choices.clear()


def _fire(game, cards, family, scenario, permanents, recorder) -> None:
    if family == "upkeep":
        game.turn += 1
        game.begin_turn_bookkeeping(0)
        game.resolve_upkeep(0, defer_priority=True)
    elif family == "end":
        game._set_phase_and_step("precombat_main", "main")
        game.resolve_end_step(0)
    elif family == "entry":
        _put(game, cards, 0, scenario["enters"])
    elif family == "dies":
        game.players[0].hand = [cards["Wrath of God"]]
        game._set_phase_and_step("precombat_main", "main")
        game.cast_from_hand(0, "Wrath of God")
    elif family == "attacks":
        recorder.on = False
        game.turn += 2
        game.begin_turn_bookkeeping(1)
        game.begin_turn_bookkeeping(0)
        _clear(game)
        recorder.on = True
        game._set_phase_and_step("combat", "declare_attackers")
        game.declare_attackers(
            0, [game.battlefield_index_of(p) for p in permanents], 1,
        )


def _distinguishable(items) -> bool:
    first = items[0]
    return any(
        (item.card.name, item.ability_text, item.source_permanent)
        != (first.card.name, first.ability_text, first.source_permanent)
        for item in items[1:]
    ) and not _interchangeable(items)


def _interchangeable(items) -> bool:
    try:
        from engine.trigger_order import interchangeable
    except ImportError:  # the tree before round 4 has no such reading
        return False
    return interchangeable(items)


def _run(cards, family, scenario, monkeypatch) -> dict:
    recorder = _Recorder(monkeypatch)
    game = _game(cards)
    permanents = [_put(game, cards, 0, name) for name in scenario["board"]]
    _clear(game)
    game.interactive_seats = {0}
    recorder.on = True
    recorder.moment += 1
    try:
        _fire(game, cards, family, scenario, permanents, recorder)
    finally:
        recorder.on = False
    moments: dict[int, list] = defaultdict(list)
    for moment, item in recorder.pushes:
        if item.caster_index == 0 and not any(kept is item for kept in moments[moment]):
            moments[moment].append(item)
    owed = [
        items for items in moments.values()
        if len(items) >= 2 and _distinguishable(items)
    ]
    asked = [
        (moment, choice) for moment, seat, choice in recorder.asked if seat == 0
    ]
    reversed_ok = True
    for _moment, choice in asked:
        if choice is None or not any(c is choice for c in game.pending_choices):
            continue
        offered = list(choice.data["_trigger_items"])
        assert game.confirm_order_triggers(0, list(reversed(range(len(offered)))))
        now = [entry for entry in reversed(game.stack) if any(entry is o for o in offered)]
        reversed_ok = reversed_ok and all(
            a is b for a, b in zip(now, list(reversed(offered)))
        )
    return {
        "owed": len(owed), "asked": len(asked), "reversed": reversed_ok,
        "pushed": sum(len(items) for items in moments.values()),
        "label": f"{scenario['board']}{' + ' + scenario['enters'] if 'enters' in scenario else ''}",
    }


def _fires_alone(cards, family, monkeypatch):
    """Whether one card alone on seat 0's board puts a triggered ability of
    seat 0's on the stack at *family*'s event — the screen ``_scenarios``
    draws its pairs through, asked through the same ``_run`` the census is."""
    memo: dict[str, bool] = {}

    def fires(name: str) -> bool:
        if name not in memo:
            with monkeypatch.context() as patch:
                memo[name] = _run(cards, family, {"board": [name]}, patch)["pushed"] >= 1
        return memo[name]

    return fires


@pytest.mark.parametrize("family", sorted(FLOORS))
def test_one_controllers_simultaneous_triggers_are_hers_to_order(
    family, catalog_by_name, monkeypatch,
):
    cards = catalog_by_name
    results = []
    for scenario in _scenarios(cards, family, _fires_alone(cards, family, monkeypatch)):
        with monkeypatch.context() as patch:
            results.append(_run(cards, family, scenario, patch))
    counted = [r for r in results if r["owed"]]
    assert len(counted) >= FLOORS[family], (
        f"{family}: only {len(counted)} of {len(results)} scenarios gave seat 0 "
        "two triggers at once — the census has stopped reaching its subject"
    )
    never_asked = [r["label"] for r in counted if r["asked"] < r["owed"]]
    assert not never_asked, (
        f"{family}: {len(never_asked)} of {len(counted)} never asked their order: "
        f"{never_asked}"
    )
    assert all(r["reversed"] for r in counted), family


#: "Whenever/When … an ability … triggers" as a triggered ability's own
#: condition: CR 603.3b's second round.
_TRIGGERS_ON_TRIGGERING = re.compile(
    r"^(?:when|whenever)\b[^,]*\b(?:ability|abilities)\b[^,]*\btrigger", re.I,
)


def test_no_card_triggers_on_another_ability_triggering(catalog):
    """CR 603.3b's second part orders "all remaining triggered abilities" — the
    ones whose trigger condition is another ability triggering — after every
    other. No supported card in the pool prints one (Psychic Battle triggers
    on a player choosing targets; Sanctum of All's sentence is CR 603.2d's
    "triggers an additional time", counted in ``additional_triggers``), so the
    engine has one round. A card that prints one fails here by name."""
    scanned = 0
    found = []
    for card in compilation_units(catalog):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            scanned += 1
            if _TRIGGERS_ON_TRIGGERING.search(trig.source_line or ""):
                found.append((card.name, trig.source_line))
    assert scanned >= 1500, scanned  # 1,635 on the tree this was written on
    assert found == []
