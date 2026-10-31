"""Census: the pool's colour narrowings off the battlefield, driven under a Dawn.

Celestial Dawn's second sentence — "The same is true for spells you control
and nonland cards you own that aren't on the battlefield" — is the one static
in the pool that recolours objects off the battlefield (the query is in round
kg's report; Darkest Hour, Thran Lens, Shifting Sky and Dralnu's Crusade reach
the battlefield alone). So the differential is boards x cards: each card below
is cast from its controller's hand, its abilities activated from the
battlefield and the graveyard, and a turn round played, on two boards per side
of the table (the Dawn under the driver, ``D0``, and under the opponent,
``D1``):

* **A** — every card off the battlefield printed in its own colours;
* **W** — the Dawn controller's nonland cards printed *white*.

The Dawn makes every one of those cards white anyway, so a correct engine
cannot tell A from W: the zones, the life totals and the log must come out
byte-identical. And on A every card off the battlefield is a :class:`_Probe`
whose ``colors`` read is watched: a read of a recoloured card's printed colours
anywhere but ``object_colors.card_colors`` handed that card's own seat is the
defect, named by the call site.

**The population is what the pool-wide run found.** The full census (the 854
cards whose text names a colour, both manifest roles, in the round's scratch
``dawn_census.py``) found these on ``c42aec75``: 11 call sites, 13 cards —
Celestial Dawn's graveyard among them (Revive, Crypt Angel, Dreams of the Dead
and Chandra, Flame's Catalyst through ``graveyard_card_matches``) — and six of
the 1,708 A/W pairs played differently. Run against that tree this file fails
on all of them; ``test_the_census_examined_what_it_claims`` is the floor that
keeps a drive that reaches nothing from reading as clean.
"""

from __future__ import annotations

import dataclasses
import random
import sys
from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: Every card the pool-wide run found asking a Dawn-recoloured card its
#: colour without that card's seat, or playing differently on A and W.
POPULATION = (
    "Avatar of Woe", "Balduvian Dead", "Baleful Stare", "Bearscape",
    "Chandra, Flame's Catalyst", "Crypt Angel", "Dreams of the Dead",
    "Drudge Spell", "Grindstone", "Merchant Scroll", "Natural Order",
    "Night Soil", "Revive", "Surge of Strength",
)

#: The probes the full run picked (two disjoint sets, one per seat; vanilla
#: creatures of every colour, colourless artifacts, untargeted instants and
#: sorceries, enchantments). Fixed here so a run is the run that was measured.
PROBES = (
    ("Mox Emerald", "Giant Cockroach", "Metallic Sliver", "Balduvian Bears",
     "Balduvian Barbarians", "Coral Merfolk", "Eager Cadet", "Barktooth Warbeard",
     "Darkest Hour", "Crosswinds", "Bedlam", "Treasure Trove", "Crusade",
     "Dark Ritual", "Serene Heart", "Boil", "Riptide", "Revitalize", "Unnerve",
     "Tsunami", "Flashfires", "Concentrate", "Sacred Nectar"),
    ("Mox Jet", "Headless Horseman", "Obsianus Golem", "Barbary Apes",
     "Crimson Kobolds", "Giant Octopus", "Femeref Scouts", "Jasmine Boreal",
     "Bad Moon", "Root Maze", "Blood Moon", "Chill", "Glorious Anthem", "Dredge",
     "Vitalize", "Falter", "Mental Note", "Reviving Dose", "Nausea", "Tranquility",
     "Ruination", "Acid Rain", "Armageddon"),
)

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_DAWN = "Celestial Dawn"

#: The modules whose frames are the reader itself; a defect is attributed to
#: the first frame outside them.
_READER_MODULES = {
    "engine.object_colors", "engine.search_filters", "engine.handlers._filters",
    "engine.subject_filters", "engine.damage_source_colors",
}
#: Reads of the printed colours that mean the printed colours: the layer-5
#: seed and layer 1's copiable values (CR 707.2a), and dataclass plumbing.
_BLESSED_MODULES = {"engine.layer_bridge", "engine.copies"}
_PLUMBING = {"__eq__", "__repr__", "__hash__", "replace", "fields", "__init__",
             "_asdict_inner", "astuple", "asdict"}


class _Spy:
    def __init__(self):
        self.on = False
        self.dawn_seat = None
        self.true_seat: dict[int, int] = {}
        self.defects: Counter = Counter()
        self.asked = 0

    def observe(self, card, frame):
        seat = self.true_seat.get(id(card))
        if seat is None:
            return
        module = frame.f_globals.get("__name__", "")
        func = frame.f_code.co_name
        if func in _PLUMBING or module.startswith("dataclasses") or module in _BLESSED_MODULES:
            return
        if seat != self.dawn_seat:
            return
        self.asked += 1
        if module == "engine.object_colors" and func == "card_colors":
            from engine.object_colors import _seat_index

            asked = _seat_index(frame.f_locals.get("game"), frame.f_locals.get("seat"))
            if asked == seat:
                return
            verdict, reader = ("missing seat" if asked is None else "wrong seat"), frame.f_back
        else:
            verdict, reader = "printed colours", frame
        site = reader
        while site is not None and site.f_globals.get("__name__", "") in _READER_MODULES:
            site = site.f_back
        where = (
            f"{site.f_globals.get('__name__')}.{site.f_code.co_name}"
            if site is not None else "?"
        )
        self.defects[(verdict, where)] += 1


SPY = _Spy()


class _Probe(CardDefinition):
    """A card whose printed-colour reads are watched."""

    @property
    def colors(self):  # type: ignore[override]
        value = self.__dict__["_probe_colors"]
        if SPY.on:
            SPY.observe(self, sys._getframe(1))
        return value

    @colors.setter
    def colors(self, value):
        self.__dict__["_probe_colors"] = value


def _probe(card, seat, *, white):
    fields = {f.name: getattr(card, f.name) for f in dataclasses.fields(CardDefinition)}
    if white:
        fields["colors"] = ("W",)
    made = _Probe(**fields)
    SPY.true_seat[id(made)] = seat
    return made


def _board(pool, unit, dawn_seat, *, white):
    SPY.true_seat.clear()
    players = []
    for seat in (0, 1):
        own = [pool[name] for name in PROBES[seat]]
        recolour = white and seat == dawn_seat

        def mk(card, _seat=seat, _recolour=recolour):
            return _probe(card, _seat, white=_recolour)

        battlefield = [Permanent(card=pool[name]) for name in _BASICS]
        battlefield += [
            Permanent(card=mk(card)) for card in own
            if "creature" in card.type_line.lower()
        ][:3]
        if seat == dawn_seat:
            battlefield.append(Permanent(card=pool[_DAWN]))
        players.append(PlayerState(
            name=f"P{seat + 1}",
            hand=[mk(card) for card in own if "instant" not in card.type_line.lower()],
            graveyard=[mk(card) for card in own],
            library=[mk(card) for card in own] * 2,
            battlefield=battlefield, life=20,
        ))
    driven = _probe(pool[unit], 0, white=white and dawn_seat == 0)
    players[0].hand.insert(0, driven)
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    instants = [
        _probe(pool[name], dawn_seat, white=white)
        for name in PROBES[dawn_seat]
        if pool[name].type_line.lower().startswith("instant")
    ]
    return game, driven, instants


def _settle(game):
    try:
        resolve_stack(game)
    except AssertionError:
        pass
    # A prompt owed on an empty stack (a search armed as its spell resolved)
    # is answered the way a headless seat answers it — by the AI's pick.
    game.auto_resolve_pending_choices()


def _drive(game, driven, instants, dawn_seat):
    """Cast it, activate it from the battlefield and the graveyard, play a
    turn round — every road the generic drive has, each refusal tolerated (the
    two boards meet the same refusals)."""
    random.seed(7)
    program = compile_card_oracle(driven)

    def attempt(step):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - recorded, and compared A vs W
            game.log.append(f"census: {type(exc).__name__}")
        _settle(game)

    if "instant" in driven.type_line.lower() or driven.has_flash:
        for spell in instants:
            attempt(lambda s=spell: game.queue_from_hand(
                dawn_seat, s.name, target_player_index=1 - dawn_seat))
    attempt(lambda: game.cast_from_hand(0, driven.name, target_player_index=1, x_value=2))
    if program.activated_abilities:
        if any(p.card.name == driven.name for p in game.all_permanents()):
            for index in range(len(program.activated_abilities)):
                attempt(lambda i=index: game.activate_permanent_ability(
                    0, driven.name, target_player_index=1, ability_index=i))
        game.players[0].graveyard.append(driven)
        for index in range(len(program.activated_abilities)):
            attempt(lambda i=index: game.activate_from_graveyard(0, driven.name, i))
    attempt(game.start_next_turn)
    attempt(game.start_next_turn)


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
        "dawn": any(p.card.name == _DAWN for p in game.all_permanents()),
    }


def _run(pool, unit, dawn_seat):
    outcomes = {}
    for white in (False, True):
        SPY.on, SPY.dawn_seat = not white, dawn_seat
        try:
            game, driven, instants = _board(pool, unit, dawn_seat, white=white)
            _drive(game, driven, instants, dawn_seat)
        finally:
            SPY.on = False
        outcomes["W" if white else "A"] = _outcome(game)
    return outcomes


@pytest.fixture(scope="module")
def pool():
    from engine.card_loader import load_cards, manifest_set_paths

    return {card.name: card for card in load_cards(manifest_set_paths(include_measured=True))}


@pytest.fixture(scope="module")
def census(pool):
    SPY.defects.clear()
    results = {}
    asked = {}
    for unit in POPULATION:
        for dawn_seat in (0, 1):
            before = SPY.asked
            results[(unit, dawn_seat)] = _run(pool, unit, dawn_seat)
            asked[(unit, dawn_seat)] = SPY.asked - before
    return results, asked, Counter(SPY.defects)


@pytest.mark.full
def test_no_rule_reads_the_printed_colour_of_a_card_the_dawn_recoloured(census):
    _results, _asked, defects = census
    assert not defects, (
        "a card off the battlefield was asked its colour without its own seat "
        "while its owner's Celestial Dawn had made it white (CR 613.1):\n  "
        + "\n  ".join(f"{verdict} <- {site}: {n}" for (verdict, site), n in defects.items())
    )


@pytest.mark.full
def test_a_dawn_recolouring_is_indistinguishable_from_printed_white(census):
    results, _asked, _defects = census
    moved = []
    for (unit, dawn_seat), outcome in sorted(results.items()):
        a, w = outcome["A"], outcome["W"]
        if not (a["dawn"] and w["dawn"]):
            continue  # the Dawn left: printed colours are back on both boards
        if a != w:
            line = next(
                (f"{x!r} vs {y!r}" for x, y in zip(a["log"], w["log"]) if x != y),
                f"{len(a['log'])} vs {len(w['log'])} log lines",
            )
            moved.append(f"{unit} (Dawn on seat {dawn_seat}): {line}")
    assert not moved, "\n".join(moved)


@pytest.mark.full
def test_the_census_examined_what_it_claims(pool, census):
    """The floor: every card in the population exists, and its drive asked at
    least one colour question of a card the Dawn had recoloured — a drive that
    reached nothing would read as clean."""
    results, asked, _defects = census
    assert all(name in pool for name in POPULATION + PROBES[0] + PROBES[1] + (_DAWN,))
    assert len(results) == 2 * len(POPULATION) >= 28
    quiet = [unit for unit in POPULATION if not (asked[(unit, 0)] or asked[(unit, 1)])]
    assert not quiet, f"drives that asked no recoloured card its colour: {quiet}"
    kept = sum(1 for outcome in results.values() if outcome["A"]["dawn"])
    assert kept >= len(results) - 4, "the Dawn left the board in most drives"
