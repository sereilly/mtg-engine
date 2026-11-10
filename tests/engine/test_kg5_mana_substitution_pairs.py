"""Census: every pair of the pool's mana substitutions on one land, each
symbol on offer asked for and made.

CR 106.12b makes "if a land is tapped for mana, it produces X instead" a
replacement over the production event, and CR 616.1e lets the land's
controller order two of them — the one applied last is what the land makes
(616.1f). The producers are found structurally, never by name:

* the battlefield statics — every printed line ``land_mana_swaps.
  substitution_line`` reads (Infernal Darkness, Ritual of Subdual,
  Contamination, Naked Singularity, Reality Twist, Pulse of Llanowar);
* the per-seat records — every compiled step of a kind that arms one
  (Deep Water, Pale Moon, Chaos Moon, Harvest Mage, Hall of Gemstone, False
  Dawn), armed by running that step through the engine's dispatcher.

Each pair is put on the first land of a short list both of them cover. A
producer that replaces every type ("instead of any other type") can be the one
applied last, and then the land makes what that producer alone would — so what
it alone offers must be offered beside the other (``payment_colors``: what the
planner counts and the client's colour fan shows), and a tap asking for it
must make it; so must every symbol offered. And what CR 106.7 says the land
could produce (``lands_could_produce``) is exactly that offer, so a Reflecting
Pool or a Fellwar Stone reading it reads the same set.

Backwards on the base (59f133e63): of the 65 pairs examined (15 of two
statics, 35 of a static and a record, 15 of two records), 47 offer one symbol
where the other producer's is reachable too — the newest record or the first
static won every tap.

**The third shape: a record on one land** — every compiled step of a kind that
writes one (Quarum Trench Gnomes' "If target Plains is tapped for mana, it
produces colorless mana instead of white mana"), armed on the land by running
it through the dispatcher. It replaces only the white mana ("The ability only
replaces white mana produced by the Plains", its ruling, 2008-08-01), so it is
never the one that decides by being applied last; what each order makes is
stated outright instead (:func:`test_a_land_s_own_record_is_ordered_against_every_substitution`).
Backwards on ``e245e624c``, where the record was read inside
``Permanent.effective_produced_mana`` ahead of every substitution: of the 12
pairs, Hall of Gemstone's {R} (colours only), Pulse of Llanowar's and Harvest
Mage's choice offer one order's symbols alone, and a tap asking for {C} beside
either choice makes a colour.
"""
from __future__ import annotations

from itertools import combinations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.land_mana_swaps import payment_colors, substitution_line, swapped_production
from engine.mana_could_produce import lands_could_produce
from engine.mana_payment import _every_nested_step
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

#: The instruction kinds that arm a per-seat substitution record
#: (``handlers/mana``).
_RECORD_KINDS = frozenset({
    "swap_controller_land_mana_until_eot", "swap_controller_added_mana_until_eot",
})

#: Lands to put a pair on, the first both producers cover winning: basics of
#: two types, a nonbasic of two types (Pale Moon's "nonbasic", Naked
#: Singularity's two clauses) and a nonbasic of one.
_LANDS = ("Forest", "Mountain", "Plains", "Taiga", "Tundra")


def _program_steps(program):
    roots = [*program.instructions]
    roots += [ability.instruction for ability in program.activated_abilities]
    roots += [ability.instruction for ability in program.triggered_abilities]
    for root in roots:
        if root is None:
            continue
        yield root
        yield from _every_nested_step(root)


def _producers():
    statics, records = [], []
    for unit in compilation_units(_CATALOG):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if any(substitution_line(line.lower()) for line in (unit.oracle_text or "").split("\n")):
            statics.append(unit)
            continue
        steps = [step for step in _program_steps(program) if step.kind in _RECORD_KINDS]
        if steps:
            records.append((unit, steps[0]))
    return statics, records


def _board(land_name, producers):
    game = Game(players=[
        PlayerState("A", library=[_CARDS["Forest"]] * 5),
        PlayerState("B", library=[_CARDS["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    land = Permanent(card=_CARDS[land_name])
    game._put_permanent_onto_battlefield(0, land, None)
    land.metadata["summoning_sickness_turn"] = -99
    for card, step in producers:
        source = None
        if card.primary_type not in ("instant", "sorcery"):
            source = Permanent(card=card)
            game._put_permanent_onto_battlefield(0, source, None)
            # "…mana of the chosen color" (Hall of Gemstone) follows its
            # source's recorded colour.
            source.metadata.setdefault("chosen_color", "R")
        if step is not None:
            player = game.players[0]
            game._execute_oracle_instruction(step, OracleExecutionContext(
                caster=player, target=player, card=card, source_permanent=source,
            ))
    game.stack.clear()
    game.pending_choices.clear()
    return game, land


def _tap(game, land, asked):
    land.tapped = False
    player = game.players[0]
    for symbol in player.mana_pool:
        player.mana_pool[symbol] = 0
    for bucket in (getattr(player, "restricted_mana", None) or {}).values():
        for symbol in bucket:
            bucket[symbol] = 0
    assert game.tap_land_for_mana(0, land.card.name, chosen_color=asked, permanent_id=land.permanent_id)
    made = {symbol for symbol, n in player.mana_pool.items() if n}
    for bucket in (getattr(player, "restricted_mana", None) or {}).values():
        made |= {symbol for symbol, n in bucket.items() if n}
    return made


def _alone(land_name, producer):
    """What *producer* alone makes *land_name*'s tap into — ``(offered,
    colors_only)`` — or None where it does not cover that land."""
    game, land = _board(land_name, (producer,))
    offered = payment_colors(game, land)
    if offered is None:
        return None
    return set(offered), swapped_production(game, land).colors_only


def test_every_pair_of_substitutions_makes_each_symbol_it_offers():
    """Each producer of a pair that replaces every type ("instead of any other
    type") can be the one applied last (CR 616.1e), and then the land makes
    what it alone would: so what it alone offers is offered beside the other,
    and a tap asking for it makes it. Every symbol offered is made, and CR
    106.7's set is the offer."""
    statics, records = _producers()
    assert len(statics) >= 6, [card.name for card in statics]
    assert len(records) >= 6, [card.name for card, _ in records]
    producers = [(card, None) for card in statics] + records
    examined: dict[str, int] = {"static+static": 0, "static+record": 0, "record+record": 0}
    unoffered, wrong, mismatched = [], [], []
    for first, second in combinations(producers, 2):
        for land_name in _LANDS:
            alone = [_alone(land_name, producer) for producer in (first, second)]
            if all(found is not None for found in alone):
                break
        else:
            continue
        records_in_pair = sum(step is not None for _card, step in (first, second))
        examined[("static+static", "static+record", "record+record")[records_in_pair]] += 1
        game, land = _board(land_name, (first, second))
        names = (first[0].name, second[0].name, land_name)
        offered = payment_colors(game, land) or ()
        reachable = set().union(*(found for found, colors_only in alone if not colors_only))
        if not reachable <= set(offered):
            unoffered.append((names, sorted(reachable), offered))
        could = set(lands_could_produce(game)[land.permanent_id])
        if could != set(offered):
            mismatched.append((names, offered, sorted(could)))
        for symbol in sorted(reachable | set(offered)):
            made = _tap(game, land, symbol)
            if symbol not in made:
                wrong.append((names, symbol, sorted(made)))
    # A floor on what was examined, per shape of pair: a census that met no
    # contention has measured nothing.
    assert sum(examined.values()) >= 50, examined
    assert all(count >= 10 for count in examined.values()), examined
    assert unoffered == [], unoffered
    assert wrong == [], wrong
    assert mismatched == [], mismatched


#: The instruction kinds that write a substitution onto one land
#: (``handlers/mana.produce_mana_instead``).
_LAND_RECORD_KINDS = frozenset({"produce_mana_instead"})

#: Where a land's own record is put beside another producer, the first both
#: cover winning: the record names a Plains, so the census's lands that are
#: one, and Plateau for the Mountain-only producers (Chaos Moon).
_PLAINS = ("Plains", "Tundra", "Plateau")


def _land_record_producers():
    found = []
    for unit in compilation_units(_CATALOG):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        steps = [step for step in _program_steps(program) if step.kind in _LAND_RECORD_KINDS]
        if steps:
            found.append((unit, steps[0]))
    return found


def _record_on(game, land, card, step):
    """Run *card*'s record-writing *step* aimed at *land*, as its resolution
    would; whether a record was written is the land's own answer."""
    player = game.players[0]
    game._execute_oracle_instruction(step, OracleExecutionContext(
        caster=player, target=player, card=card,
        target_permanent_id=[land.permanent_id],
    ))
    game.stack.clear()
    game.pending_choices.clear()
    return bool(land.metadata.get("produced_mana_swaps"))


def test_a_land_s_own_record_is_ordered_against_every_substitution():
    """CR 616.1e for a record that replaces one symbol: on a Plains its white
    mana is made {C} either **before** the other producer applies — which then
    acts on {C} — or **after** it, when only the white it left is replaced. So
    the land makes what the other producer alone makes of {C} (itself, for one
    that replaces only colours or only named symbols), and what it alone makes
    of the Plains with the white turned to {C}: exactly that is offered, every
    symbol of it is made by a tap asking for it, and CR 106.7's set is the
    offer."""
    records = _land_record_producers()
    assert records, "no step writes a record onto one land"
    statics, seat_records = _producers()
    others = [(card, None) for card in statics] + seat_records
    examined = {"record+static": 0, "record+seat record": 0}
    wrong_offer, unmade, mismatched = [], [], []
    for record_card, record_step in records:
        for other in others:
            for land_name in _PLAINS:
                game, land = _board(land_name, ())
                if not _record_on(game, land, record_card, record_step):
                    continue
                alone = _alone(land_name, other)
                if alone is not None:
                    break
            else:
                continue
            examined["record+static" if other[1] is None else "record+seat record"] += 1
            other_offer, other_colors_only = alone
            game, land = _board(land_name, (other,))
            assert _record_on(game, land, record_card, record_step)
            # "…instead of any other **color**" leaves {C} alone; "any other
            # type" makes it what it makes of anything.
            of_colorless = {"C"} if other_colors_only else set(other_offer)
            expected = of_colorless | {"C" if symbol == "W" else symbol for symbol in other_offer}
            names = (record_card.name, other[0].name, land_name)
            offered = payment_colors(game, land) or ()
            if set(offered) != expected:
                wrong_offer.append((names, sorted(expected), offered))
            could = set(lands_could_produce(game)[land.permanent_id])
            if could != set(offered):
                mismatched.append((names, offered, sorted(could)))
            for symbol in sorted(expected | set(offered)):
                made = _tap(game, land, symbol)
                if symbol not in made:
                    unmade.append((names, symbol, sorted(made)))
    # A floor per shape: a census that met no other producer measured nothing.
    assert all(count >= 5 for count in examined.values()), examined
    assert wrong_offer == [], wrong_offer
    assert unmade == [], unmade
    assert mismatched == [], mismatched
