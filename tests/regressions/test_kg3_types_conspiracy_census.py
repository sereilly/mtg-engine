"""Census: the pool's creature-type narrowings off the battlefield, driven under
a Conspiracy.

"Creatures you control are the chosen type. The same is true for creature
spells you control and creature cards you own that aren't on the
battlefield." (Conspiracy.) The one static in the pool that changes a *type*
off the battlefield — round kg3's query over both manifest roles found it
and Mistform Ultimus, whose "is every creature type" is a CDA folded into the
printed parse every zone shares (``printed_characteristics._printed_shape``).
The type twin of ``test_kg_colour_dawn_census.py``: boards x cards, each card
cast from its controller's hand, its abilities activated from the battlefield
and the graveyard, a creature spell cast by the active seat, and a turn round
played, on two boards per side of the table (the Conspiracy under the driver,
``C0``, and under the opponent, ``C1``):

* **A** — every card printed with its own type line;
* **T** — the Conspiracy controller's creature cards printed "— <chosen>".

The Conspiracy makes every one of those cards the chosen type and nothing else
anyway (CR 205.1a; the card's ruling, 2013-09-20), so a correct engine cannot
tell A from T: the zones, the life totals and the log come out byte-identical.

**The population is what the pool-wide run found.** The full census (603
cards whose text names a creature type or "creature type", both manifest
roles; scratch ``kg3/types/conspiracy_census.py``) found five of the 1,206 A/T
pairs playing differently on ``e7a41c0e`` — Aphetto Dredging's default type,
Lin Sivvi's and Strongarm Thug's graveyard targets, Rin and Seri's cast
trigger and Urza's Incubator's discount — and none after the round. The rest
of the population are cards whose drive asks a Conspiracy-retyped card its
types and which played the same either way; the floor holds each to having
asked (``creature_type_override_for_seat`` answering the chosen type), so a
drive that reaches nothing cannot read as clean.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter

import pytest

import engine.object_creature_types as object_creature_types
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: card -> the type its Conspiracy names (the first the card's text names).
POPULATION = {
    "Aphetto Dredging": "goblin",
    "Lin Sivvi, Defiant Hero": "rebel",
    "Rin and Seri, Inseparable": "dog",
    "Strongarm Thug": "mercenary",
    "Urza's Incubator": "goblin",
    "Mtenda Griffin": "griffin",
    "Lord of the Undead": "zombie",
    "Unholy Grotto": "zombie",
    "Goblin Matron": "goblin",
    "Patriarch's Bidding": "goblin",
    "Tsabo's Decree": "goblin",
}

#: The probes the full run picked (two disjoint sets, one per seat; vanilla
#: creatures of several subtypes, an artifact creature, untargeted instants and
#: sorceries, enchantments). Fixed here so a run is the run that was measured.
PROBES = (
    ("Mox Emerald", "Giant Cockroach", "Metallic Sliver", "Balduvian Bears",
     "Balduvian Barbarians", "Coral Merfolk", "Eager Cadet", "Darkest Hour",
     "Crosswinds", "Bedlam", "Treasure Trove", "Crusade", "Dark Ritual",
     "Serene Heart", "Boil", "Riptide", "Revitalize", "Unnerve", "Tsunami",
     "Flashfires", "Concentrate", "Sacred Nectar"),
    ("Mox Jet", "Headless Horseman", "Obsianus Golem", "Barbary Apes",
     "Crimson Kobolds", "Fugitive Wizard", "Femeref Scouts", "Bad Moon",
     "Root Maze", "Blood Moon", "Chill", "Glorious Anthem", "Dredge", "Vitalize",
     "Brightstone Ritual", "Mental Note", "Reviving Dose", "Infest",
     "Tranquility", "Ruination", "Acid Rain", "Armageddon"),
)

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_CONSPIRACY = "Conspiracy"


def _retyped(card, chosen):
    line = card.type_line or ""
    if "creature" not in line.lower():
        return card
    head = line.split("—")[0].strip()
    fields = {f.name: getattr(card, f.name) for f in dataclasses.fields(CardDefinition)}
    fields["type_line"] = f"{head} — {chosen.title()}"
    return CardDefinition(**fields)


def _board(pool, unit, seat_of_conspiracy, chosen, *, typed):
    def mk(card, seat):
        return _retyped(card, chosen) if typed and seat == seat_of_conspiracy else card

    players = []
    for seat in (0, 1):
        own = [pool[name] for name in PROBES[seat]]
        battlefield = [Permanent(card=pool[name]) for name in _BASICS]
        battlefield += [
            Permanent(card=mk(card, seat)) for card in own
            if "creature" in card.type_line.lower()
        ][:3]
        if seat == seat_of_conspiracy:
            source = Permanent(card=pool[_CONSPIRACY])
            source.metadata["chosen_creature_type"] = chosen.title()
            battlefield.append(source)
        players.append(PlayerState(
            name=f"P{seat + 1}",
            hand=[mk(card, seat) for card in own if "instant" not in card.type_line.lower()],
            graveyard=[mk(card, seat) for card in own],
            library=[mk(card, seat) for card in own] * 2,
            battlefield=battlefield, life=20,
        ))
    driven = mk(pool[unit], 0)
    players[0].hand.insert(0, driven)
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    return game, driven


def _settle(game):
    try:
        resolve_stack(game)
    except AssertionError:
        pass
    game.auto_resolve_pending_choices()


def _drive(game, driven):
    """Cast it, activate it from the battlefield and the graveyard, cast a
    creature spell for the active seat, play a turn round — every refusal
    tolerated (the two boards meet the same refusals)."""
    random.seed(7)
    program = compile_card_oracle(driven)

    def attempt(step):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - recorded, and compared A vs T
            game.log.append(f"census: {type(exc).__name__}")
        _settle(game)

    def cast_a_creature(seat):
        for card in list(game.players[seat].hand):
            if "creature" in card.type_line.lower():
                attempt(lambda c=card: game.cast_from_hand(
                    seat, c.name, target_player_index=1 - seat))
                return

    attempt(lambda: game.cast_from_hand(0, driven.name, target_player_index=1, x_value=2))
    if program.activated_abilities:
        if any(p.card.name == driven.name for p in game.all_permanents()):
            for index in range(len(program.activated_abilities)):
                attempt(lambda i=index: game.activate_permanent_ability(
                    0, driven.name, target_player_index=1, ability_index=i))
    cast_a_creature(0)
    if program.activated_abilities:
        game.players[0].graveyard.append(driven)
        for index in range(len(program.activated_abilities)):
            attempt(lambda i=index: game.activate_from_graveyard(0, driven.name, i))
    attempt(game.start_next_turn)
    cast_a_creature(game.active_player_index)
    attempt(game.start_next_turn)
    cast_a_creature(game.active_player_index)


def _outcome(game):
    return {
        "zones": [
            {zone: [card.name for card in getattr(player, zone)]
             for zone in ("hand", "graveyard", "library", "exile")}
            | {"life": player.life}
            for player in game.players
        ],
        "battlefield": sorted(
            (p.card.name, game.controller_index_of(p), bool(p.tapped))
            for p in game.all_permanents()
        ),
        "log": list(game.log),
        "kept": any(p.card.name == _CONSPIRACY for p in game.all_permanents()),
    }


@pytest.fixture(scope="module")
def pool():
    from engine.card_loader import load_cards, manifest_set_paths

    return {card.name: card for card in load_cards(manifest_set_paths(include_measured=True))}


@pytest.fixture(scope="module")
def census(pool):
    asked: Counter = Counter()
    current = {"key": None}
    real = object_creature_types.creature_type_override_for_seat

    def counting(game, seat):
        answer = real(game, seat)
        if answer is not None and current["key"] is not None:
            asked[current["key"]] += 1
        return answer

    results = {}
    object_creature_types.creature_type_override_for_seat = counting
    try:
        for unit, chosen in POPULATION.items():
            for seat in (0, 1):
                outcome = {}
                for typed in (False, True):
                    current["key"] = None if typed else (unit, seat)
                    game, driven = _board(pool, unit, seat, chosen, typed=typed)
                    _drive(game, driven)
                    outcome["T" if typed else "A"] = _outcome(game)
                results[(unit, seat)] = outcome
    finally:
        object_creature_types.creature_type_override_for_seat = real
        current["key"] = None
    return results, asked


@pytest.mark.full
def test_a_conspiracy_retyping_is_indistinguishable_from_the_printed_type(census):
    results, _asked = census
    moved = []
    for (unit, seat), outcome in sorted(results.items()):
        a, t = outcome["A"], outcome["T"]
        if not (a["kept"] and t["kept"]):
            continue  # the Conspiracy left: printed types are back on both boards
        if a != t:
            line = next(
                (f"{x!r} vs {y!r}" for x, y in zip(a["log"], t["log"]) if x != y),
                f"{len(a['log'])} vs {len(t['log'])} log lines",
            )
            moved.append(f"{unit} (Conspiracy on seat {seat}): {line}")
    assert not moved, (
        "a card off the battlefield was read as its printed creature type while "
        "its owner's Conspiracy had retyped it (CR 205.1a, 613.1):\n  "
        + "\n  ".join(moved)
    )


@pytest.mark.full
def test_the_census_examined_what_it_claims(pool, census):
    """The floor: every card exists, every drive kept its Conspiracy on most
    boards, and every card's drive asked a retyped card its creature types at
    least once — a drive that reached nothing would read as clean."""
    results, asked = census
    assert all(
        name in pool
        for name in (*POPULATION, *PROBES[0], *PROBES[1], _CONSPIRACY)
    )
    assert len(results) == 2 * len(POPULATION) >= 22
    quiet = [
        unit for unit in POPULATION
        if not (asked[(unit, 0)] or asked[(unit, 1)])
    ]
    assert not quiet, f"drives that asked no retyped card its creature types: {quiet}"
    kept = sum(1 for outcome in results.values() if outcome["A"]["kept"])
    assert kept >= len(results) - 4, "the Conspiracy left the board in most drives"
