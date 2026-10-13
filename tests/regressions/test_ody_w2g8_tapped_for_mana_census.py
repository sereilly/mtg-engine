"""Census: a land tapped for mana, by every road, under every card that watches.

CR 106.12 makes "tapped for mana" one event — the activation of a mana ability
with {T} in its cost — and three roads reach it: the player's own tap
(``Game.tap_land_for_mana``), a cost an effect collects
(``Game._pay_planned_cost``; CR 605.3a), and the activation path's inline
branch for a land whose mana ability costs more than the tap (CR 605.3b). Only
the first announced anything.

**What is counted.** For each land × each watcher × four seatings (who taps,
whose turn it is), the watcher's *reaction* on each road — everything about
the game that differs from the same road with no watcher: life, the tapped
land's fate, the other lands, the watcher's own counters, the seat's
"tapped a land for mana this turn" record, and how much mana there is —
compared with its reaction to the explicit tap. A priced land has no explicit
tap, so it is compared with a twin of itself whose ability costs the tap
alone. With no watcher at all the roads are compared directly: what the
land's own ability does (a painland's damage, an Ancient Tomb's second mana)
must happen whichever road tapped it.

**The watchers are derived**, over both manifest roles: every card with a
``land_tapped_for_mana`` trigger, every Aura the tap seam reads an extra mana
off, every "if a land is tapped for mana, it produces … instead".

**Validated backwards.** On the tree before the fix, over a third of the
pool's land classes (55 of them, 23 watchers):

* the plan road — 1,261 of 3,380 cases differ, and *every* watcher that reacts
  to an explicit tap is silent on every one of them: Manabarbs 148 of 148,
  Mana Flare 148 of 148, Storm Cauldron 148 of 148, Price of Glory 75 of 75,
  Savage Firecat 74 of 74, Wild Growth 148 of 148, and fifteen more;
* the priced road — 494 of 1,460 (Darkwater Catacombs under Mana Flare adds
  nothing, under Manabarbs deals nothing);
* a tap-alone ability reached through the activation path — 1,188 of 3,380;
* with no watcher, 148 of 148 planned taps differ from the explicit one (the
  per-turn record never written), and for the lands whose ability does more
  than add one mana the difference is the card: an Ancient Tomb dealt no
  damage and made one mana, a Barbarian Ring dealt none, a Tolarian Academy
  beside no artifact paid a {1};
* and 180 driven cases raised ``ValueError: Invalid mana color: C`` — any land
  that offers a colour choice, asked for the {C} every land pays under Ritual
  of Subdual.

The suite runs the lands below — one per kind of mana ability — and the whole
pool's classes when run as a module:

    python -m tests.regressions.test_ody_w2g8_tapped_for_mana_census            # the suite's lands
    python -m tests.regressions.test_ody_w2g8_tapped_for_mana_census --pool     # every land class
"""

from __future__ import annotations

import dataclasses
import re
from collections import Counter

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_additional_mana_on_tap
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.mana_payment import is_mana_ability
from engine.mixins.turn_management import (TAP_TRIGGER_KINDS,
                                           _tap_trigger_steps,
                                           is_tap_alone_mana_ability)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import resolve_stack

#: One land per kind of mana ability the roads have to agree about.
SUITE_LANDS = (
    "Forest",                                  # CR 305.6's intrinsic ability
    "Snow-Covered Island",                     # a supertype a watcher narrows by
    "Badlands",                                # two intrinsic abilities (a Mountain)
    "Elfhame Palace",                          # a compiled colour choice
    "Adarkar Wastes",                          # a free {C} and a coloured one that hurts
    "Ancient Tomb",                            # two mana and damage
    "Barbarian Ring",                          # Odyssey: damage on the tap
    "Darkwater Catacombs",                     # priced: "{1}, {T}: Add {U}{B}."
    "Ebon Stronghold",                         # priced: "{T}, Sacrifice this land"
)

#: (who taps, whose turn): the watcher's controller on their own turn and on
#: the other player's, and the other player on the watcher's turn. "You tap"
#: (Savage Firecat), "an opponent taps" (Sanctimony, Mana Web) and "if it's
#: not that player's turn" (Price of Glory) each need two of the three.
SEATINGS = ((0, 0), (0, 1), (1, 0))
_SWAP_TEXT = re.compile(r"tap(?:s|ped)? [^.]*for mana, it produces", re.I)

PLAN_FLOOR = 500
ACTIVATION_FLOOR = 400
OWN_EFFECT_FLOOR = 20
WATCHER_FLOOR = 20


def _pool():
    cards = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def watchers(pool) -> list[tuple[str, object, str]]:
    """``(name, card, how)`` for every card that watches a land tapped for
    mana, derived from the compiled pool: ``trigger`` (a
    ``land_tapped_for_mana`` ability), ``aura`` (an extra mana the seam reads
    off the enchanted land's Aura) or ``swap`` (a replacement over the
    production, which some of these cards arm only when activated)."""
    found = []
    for unit in compilation_units(list(pool.values())):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if any(
            trigger.condition.kind == "land_tapped_for_mana"
            for trigger in program.triggered_abilities
        ):
            found.append((unit.name, unit, "trigger"))
        elif aura_additional_mana_on_tap(unit.oracle_text or ""):
            found.append((unit.name, unit, "aura"))
        elif _SWAP_TEXT.search(unit.oracle_text or "") and unit.primary_type in (
            "enchantment", "artifact", "creature",
        ):
            found.append((unit.name, unit, "swap"))
    return found


def land_classes(pool) -> list:
    """One land per mana-ability signature, over the whole pool."""
    classes: dict = {}
    for unit in compilation_units(list(pool.values())):
        if unit.primary_type != "land":
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        mana = tuple(
            (repr(ability.cost), repr(ability.instruction))
            for ability in program.activated_abilities
            if ability.instruction is not None and (
                is_mana_ability(ability) or ability.instruction.kind == "if_then"
            )
        )
        types = tuple(sorted(str(unit.type_line).lower().replace("—", " ").split()))
        key = (
            types, mana, tuple(unit.produced_mana or ()),
            tuple(sorted(t.condition.kind for t in program.triggered_abilities)),
            len(program.static_lines),
        )
        classes.setdefault(key, unit)
    return list(classes.values())


def _place(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    if permanent.tapped:
        game.become_untapped(permanent)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _total_mana(player) -> int:
    units = sum(int(amount) for amount in player.mana_pool.values())
    for bucket in (getattr(player, "restricted_mana", None) or {}).values():
        units += sum(int(amount) for amount in bucket.values())
    return units


def _watcher_state(game, watcher):
    if watcher is None:
        return None
    return (
        game.is_on_battlefield(watcher),
        repr(sorted(
            (key, value) for key, value in watcher.metadata.items()
            if "counter" in str(key)
        )),
        (watcher.effective_power, watcher.effective_toughness)
        if watcher.is_creature else None,
    )


def _where(game, permanent):
    if game.is_on_battlefield(permanent):
        marks = tuple(sorted(
            str(key) for key, value in permanent.metadata.items()
            if "untap" in str(key) and value
        ))
        return ("battlefield", permanent.tapped, marks)
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile"):
            if any(card is permanent.card for card in getattr(player, zone)):
                return (zone, seat)
    return ("gone",)


def _first_color(game, land) -> str:
    colors = (
        game._land_payment_colors(land)
        or tuple(land.effective_produced_mana or ())
        or tuple(land.basic_land_mana or ())
    )
    return str(colors[0]).upper() if colors else "C"


def drive(pool, road, land_card, tapper, active, watcher=None, how=None,
          ability_index=None):
    """One road on one board: what the game looks like afterwards, or None
    when the road refused."""
    filler = [pool["Forest"]] * 20
    game = Game(players=[
        PlayerState("P1", library=list(filler), hand=[]),
        PlayerState("P2", library=list(filler), hand=[]),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn += 1
    game.active_player_index = active
    seen = None
    if watcher is not None and how != "aura":
        seen = _place(game, 0, watcher)
    land = _place(game, tapper, land_card)
    # A second copy of the same land, behind it: something for a sweep over
    # "lands that could produce any type that land could produce" (Mana Web)
    # to find, and a land no plan for a cost of {1} reaches unless the first
    # one's tap made nothing.
    others = [_place(game, tapper, land_card)]
    if watcher is not None and how == "aura":
        seen = Permanent(card=watcher)
        game._put_permanent_onto_battlefield(0, seen, None)
        attach_aura(seen, land)
    for player in game.players:
        player.mana_pool = {symbol: 0 for symbol in player.mana_pool}
        player.tapped_land_for_mana_this_turn = False
    player = game.players[tapper]
    color = _first_color(game, land)
    before = _watcher_state(game, seen)
    if road == "explicit":
        if not game.tap_land_for_mana(
            tapper, land.card.name, color, permanent_id=land.permanent_id,
        ):
            return None
    elif road == "plan":
        if game._optional_pay_plan(player, {"cost": {"generic": 1}}) is None:
            return None
        game._pay_optional(tapper, {"cost": {"generic": 1}, "card_name": "a price"})
        # the payment's own unit, put back so the roads compare on what was made
        player.mana_pool["C"] = player.mana_pool.get("C", 0) + 1
    else:
        player.mana_pool["C"] = 6          # whatever the ability's own price is
        result = game.activate_permanent_ability(
            tapper, land.card.name, permanent_index=game.battlefield_index_of(land),
            ability_index=ability_index, mana_color=color,
        )
        if not result.supported:
            return None
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    after = _watcher_state(game, seen)
    return {
        "life": tuple(seat.life for seat in game.players),
        "land": _where(game, land),
        "others": tuple(
            (other.card.name, other.tapped, game.is_on_battlefield(other))
            for other in others
        ),
        "watcher_change": None if after == before else (before, after),
        "deed": player.tapped_land_for_mana_this_turn,
        "mana": _total_mana(player),
    }


def reaction(with_watcher, without):
    """What the watcher changed: each observed field that differs from the
    same road with no watcher."""
    if with_watcher is None or without is None:
        return None
    changed = {}
    for key, value in with_watcher.items():
        if value == without[key]:
            continue
        if key == "mana":
            changed[key] = value - without[key]
        elif key == "life":
            changed[key] = tuple(a - b for a, b in zip(value, without[key]))
        else:
            changed[key] = value
    return changed


def tap_abilities(card) -> list[tuple[int, object, bool]]:
    """``(usable index, ability, is tap-alone)`` for *card*'s mana abilities
    that include {T} in their cost — CR 106.12's own test."""
    program = compile_card_oracle(card)
    return [
        (index, ability, is_tap_alone_mana_ability(ability))
        for index, ability in enumerate(usable_activated_abilities(program))
        if ability.instruction is not None and is_mana_ability(ability)
        and ability.cost.requires_tap
    ]


def twin_of(card, ability):
    """*card* with *ability* alone, its cost reduced to the tap."""
    line = ability.source_line or ""
    if ":" not in line:
        return None
    return dataclasses.replace(card, oracle_text="{T}: " + line.split(":", 1)[1].strip())


def census(pool, lands):
    watch = watchers(pool)
    tally: Counter = Counter()
    differing: list[str] = []
    for land_card in lands:
        abilities = tap_abilities(land_card)
        for tapper, active in SEATINGS:
            seating = f"tapper {tapper}, turn {active}"
            base_explicit = drive(pool, "explicit", land_card, tapper, active)
            base_plan = drive(pool, "plan", land_card, tapper, active)
            if base_explicit is not None and base_plan is not None:
                tally["own effect"] += 1
                if base_explicit != base_plan:
                    keys = [k for k in base_explicit if base_explicit[k] != base_plan[k]]
                    differing.append(
                        f"{land_card.name} with no watcher ({seating}): by hand and "
                        f"by plan differ in "
                        f"{ {k: (base_explicit[k], base_plan[k]) for k in keys} }"
                    )
            elif base_explicit is None and base_plan is not None:
                differing.append(
                    f"{land_card.name} ({seating}): a plan taps a land the seam refuses"
                )
            activation_base = {}
            for index, ability, tap_alone in abilities:
                reference_card = land_card if tap_alone else twin_of(land_card, ability)
                reference = (
                    base_explicit if tap_alone
                    else None if reference_card is None
                    else drive(pool, "explicit", reference_card, tapper, active)
                )
                own = drive(pool, "activation", land_card, tapper, active, ability_index=index)
                if reference is not None and own is not None:
                    activation_base[index] = (reference_card, reference, own)
            for name, card, how in watch:
                expected = reaction(
                    drive(pool, "explicit", land_card, tapper, active, card, how),
                    base_explicit,
                ) if base_explicit is not None else None
                if expected is not None and base_plan is not None:
                    tally["plan"] += 1
                    tally[("watched", name)] += bool(expected)
                    found = reaction(
                        drive(pool, "plan", land_card, tapper, active, card, how),
                        base_plan,
                    )
                    if found != expected:
                        differing.append(
                            f"{land_card.name} under {name}, by plan ({seating}): "
                            f"the explicit tap gave {expected}, the plan {found}"
                        )
                for index, (reference_card, reference, own) in activation_base.items():
                    wanted = reaction(
                        drive(pool, "explicit", reference_card, tapper, active, card, how),
                        reference,
                    )
                    got = reaction(
                        drive(pool, "activation", land_card, tapper, active, card, how,
                              ability_index=index),
                        own,
                    )
                    if wanted is None or got is None:
                        continue
                    if own["land"][0] != "battlefield" or reference["land"][0] != "battlefield":
                        # A land its own cost removed: what a watcher does *to
                        # the land* is not comparable, and an Aura on it left
                        # with it — that is the cost, not a reaction.
                        for side in (wanted, got):
                            side.pop("land", None)
                            if how == "aura":
                                side.pop("watcher_change", None)
                    tally["activation"] += 1
                    tally[("watched", name)] += bool(wanted)
                    if got != wanted:
                        differing.append(
                            f"{land_card.name} ability {index} under {name}, "
                            f"activated ({seating}): its tap-alone twin gave "
                            f"{wanted}, the activation {got}"
                        )
    return tally, differing, watch


def test_every_road_that_taps_a_land_for_mana_is_the_same_event():
    pool = _pool()
    tally, differing, watch = census(pool, [pool[name] for name in SUITE_LANDS])
    assert len(watch) >= WATCHER_FLOOR, f"only {len(watch)} watchers derived"
    assert tally["plan"] >= PLAN_FLOOR, f"only {tally['plan']} plan cases"
    assert tally["activation"] >= ACTIVATION_FLOOR, (
        f"only {tally['activation']} activation cases"
    )
    assert tally["own effect"] >= OWN_EFFECT_FLOOR, (
        f"only {tally['own effect']} own-effect cases"
    )
    # every watcher was seen reacting to *something*: a census in which a
    # watcher never reacts has compared nothing about it
    asleep = [
        name for name, _card, how in watch
        if how != "swap" and not tally[("watched", name)]
    ]
    assert asleep == [], f"watchers that never reacted on any road: {asleep}"
    assert differing == [], "\n".join(differing[:20])


# --- what is still not the stack: the measured decline ---------------------------

#: The tap-for-mana triggers that are **not** mana abilities and still resolve
#: inline at the tap seam, where CR 603.3 would put them on the stack.
#:
#: CR 605.1b makes a triggered ability a mana ability only if it "could add
#: mana to a player's mana pool when it resolves", and CR 605.4a is what lets
#: such an ability skip the stack. Seven cards in the pool trigger on a land
#: tapped for mana and add none, and each has a ruling or a rule saying it
#: uses the stack — Manabarbs' of 2009-10-01 in so many words ("This ability
#: is not a mana ability. It goes on the stack and can be responded to"),
#: Mana Web's of 2008-04-01 ("The opponent can tap their lands for mana in
#: response").
#:
#: Moving them is a change to where every tap sits relative to the spell it
#: pays for, in a browser where a player taps and *then* casts; it was
#: measured and declined in Odyssey's wave 2 (ROADMAP). Pinned so that an
#: eighth card joins the inventory on purpose, and so that the day they move
#: this test is the one that says so.
NON_MANA_TAP_TRIGGERS_RESOLVED_INLINE = frozenset({
    "Manabarbs", "Scald", "Storm Cauldron", "Mana Web", "Sanctimony",
    "Price of Glory", "Savage Firecat",
})

#: …and the ones CR 605.1b does make mana abilities, the whole ability
#: included: Overabundance's damage and Winter's Night's untap lock are part
#: of an ability that adds mana, so they resolve with it and cannot be
#: responded to (Overabundance's ruling of 2004-10-04 says so of the damage).
TRIGGERED_MANA_ABILITIES = frozenset({
    "Gauntlet of Might", "Mana Flare", "Snowfall", "Vernal Bloom",
    "Overabundance", "Winter's Night",
})


def tap_triggers(pool) -> dict[str, bool]:
    """Every card with a ``land_tapped_for_mana`` trigger → whether that
    trigger is a mana ability (CR 605.1b: it could add mana)."""
    found: dict[str, bool] = {}
    for unit in compilation_units(list(pool.values())):
        for trigger in compile_card_oracle(unit).triggered_abilities:
            if trigger.condition.kind != "land_tapped_for_mana":
                continue
            if trigger.instruction is None:
                continue
            kinds = [step.kind for step in _tap_trigger_steps(trigger.instruction)]
            assert set(kinds) <= TAP_TRIGGER_KINDS, (unit.name, kinds)
            found[unit.name] = "add_mana_for_tapped_land" in kinds
    return found


def test_the_tap_triggers_that_are_not_mana_abilities_are_the_known_seven():
    found = tap_triggers(_pool())
    assert {name for name, adds in found.items() if adds} == TRIGGERED_MANA_ABILITIES
    assert {
        name for name, adds in found.items() if not adds
    } == NON_MANA_TAP_TRIGGERS_RESOLVED_INLINE


def test_a_non_mana_tap_trigger_still_resolves_before_anything_can_respond():
    """The decline, stated as behaviour: Manabarbs' damage has happened by the
    time ``tap_land_for_mana`` returns, and nothing is on the stack. When the
    triggers move to the stack this assertion is the one that changes."""
    pool = _pool()
    seen = drive(pool, "explicit", pool["Island"], 0, 0, pool["Manabarbs"], "permanent")
    assert seen["life"] == (19, 20)


if __name__ == "__main__":
    import sys

    pool = _pool()
    lands = (
        land_classes(pool) if "--pool" in sys.argv
        else [pool[name] for name in SUITE_LANDS]
    )
    tally, differing, watch = census(pool, lands)
    print(f"lands: {len(lands)}; watchers: {len(watch)}")
    for key in ("plan", "activation", "own effect"):
        print(f"   {key} cases: {tally[key]}")
    asleep = [
        name for name, _card, how in watch
        if how != "swap" and not tally[("watched", name)]
    ]
    print(f"watchers that never reacted: {asleep}")
    print(f"differing cases: {len(differing)}")
    for line in differing[:60]:
        print("  ", line)
    triggers = tap_triggers(pool)
    print("tap triggers that are mana abilities:", sorted(n for n, a in triggers.items() if a))
    print("tap triggers resolved inline that are not:", sorted(n for n, a in triggers.items() if not a))
