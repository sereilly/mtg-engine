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

Not in the census: Quarum Trench Gnomes' per-permanent record, which
``Permanent.effective_produced_mana`` applies ahead of every substitution here
(its order against Hall of Gemstone's colours-only record or Pulse of
Llanowar's choice is not offered — kg5 ``mana``'s report names it).

Backwards on the base (59f133e63): of the 65 pairs examined (15 of two
statics, 35 of a static and a record, 15 of two records), 47 offer one symbol
where the other producer's is reachable too — the newest record or the first
static won every tap.
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
