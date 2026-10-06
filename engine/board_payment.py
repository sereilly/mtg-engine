"""Could this seat pay this cost with what it has and what its lands would make?

CR 601.2h asks what a player is *able* to pay. For a cast, producing the mana
is the player's own separate action — they tap, then the cast spends the pool
(``mixins/stack/casting._pay_mana_cost``) — so the question a *preview* of a
cast has to answer is "is there a way to tap these lands that leaves a pool the
payment accepts". This module answers it, for the one reader that shows a
player the answer before they act: the castable highlight
(``web/state_view._card_castable_now``).

**What it replaced.** The highlight summed every untapped land's every listed
symbol into a "potential pool" — one mana *per colour* per land — and asked
whether that pool could pay. So a land that offers two colours counted as two
mana whenever the cost wanted both: Craw Wurm ({4}{G}{G}) over three Tropical
Islands glowed and the cast was refused, and so did a {G}{U} spell over one.
Measured over every land in both manifest roles, alone and in a pair, against
every cost of one to three symbols it could be asked for: **3,543 of 14,626**
(board, cost) pairs glowed over a cost no tapping could pay, on 99 of 199
lands — the duals, the painlands, every "any colour" land, and every land
whose summary lists a colour only a *priced* ability makes.

**How it answers.** The exact matching already existed:
``mana_payment.plan_payment`` is an augmenting-path assignment of pips to
sources, written because "a greedy pick under-reports a board that could pay".
It takes a pool, a list of sources and what each source can make; this module
supplies the list. A source is one **unit of mana** — a mana floating in the
pool, or one of the mana a land's tap would add — carrying the set of pips it
may pay:

* what a land's tap makes is read off the **tap seam's** own facts
  (``Game.land_mana_tap_refusal``, ``_land_mana_abilities``, the tap-alone
  abilities ``is_tap_alone_mana_ability`` admits) rather than off the printed
  ``produced_mana`` summary, which lists every symbol any ability of the land
  can make and says nothing of what it costs or how many;
* what a unit may pay is the seat's CR 609.4 spending permissions, asked of
  ``mana_payment.may_pay_pip`` — the arithmetic the payment itself runs.

A land whose tap makes several mana is several units; a land whose tap offers a
choice is one unit with alternatives; "N mana of any **one** color" is N units
that share their colour, which the matching cannot express, so the colour is
enumerated around it.

**Lands only, by decision.** A mana ability of a creature or an artifact (a
Llanowar Elves, a Mox) is not counted, nor is a land's mana ability that costs
more than the tap (a storage land's counters, a filter land's mana). Those are
activations the player makes — after which the mana is in the pool and is
counted — and no automatic payment in this app taps them: the client's
auto-tap plans from tap-seam lands alone, the AI's planner likewise, and
``mana_payment.untapped_mana_lands`` states the same limit. A glow that needed
one would light a card the click then cannot pay for.

Held to the seam by ``tests/engine/test_castable_highlight_asks_the_planner.py``:
every land in the pool, alone and in a pair, with the truth found by tapping
every combination through ``tap_land_for_mana`` and casting.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mana_payment import (MANA_PRODUCING_KINDS, PIP_SYMBOLS, _every_nested_step,
                           may_pay_pip, plan_payment)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent

#: A mark every unit carries so the matching counts it toward a generic cost
#: (``plan_payment`` spends on generic only a source that makes *something*).
#: No pip is spelled this way, so it pays for nothing else.
_ANY = "*"

#: The most colour assignments tried for the lands whose mana shares one chosen
#: colour. Five to the fifth: more such lands than that on one battlefield and
#: the rest are read as free to differ, which can only over-offer.
_MAX_COLOR_ASSIGNMENTS = 3125


@dataclass(frozen=True)
class TapYield:
    """One way one tap of a land can come out.

    ``units`` is one entry per mana, each the symbols that mana may be.
    ``one_color`` says the units are **the same** symbol, chosen once ("add
    three mana of any one color") rather than each chosen freely.
    """

    units: "tuple[frozenset[str], ...]"
    one_color: bool = False


def _seam_abilities(game: "Game", land: "Permanent") -> list:
    """The instructions the tap seam would run for *land*, one per mana
    ability a tap alone pays for — ``None`` standing for the printed-summary
    path a basic or a dual takes."""
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .oracle import compile_card_oracle
    from .targeting import usable_activated_abilities

    found: list = []
    if game.land_mana_tap_refusal(land) is None:
        free, _priced = game._land_mana_abilities(land)
        found.append(free)
    usable = usable_activated_abilities(
        compile_card_oracle(game.playable_card_of(land))
    )
    for index, ability in enumerate(usable):
        if not is_tap_alone_mana_ability(ability):
            continue
        if any(ability.instruction is seen for seen in found):
            continue
        if game.land_mana_tap_refusal(land, index) is None:
            found.append(ability.instruction)
    return found


def _summary_yield(game: "Game", land: "Permanent") -> TapYield | None:
    """What the seam's fallback adds for a land with no compiled mana ability:
    one mana of a symbol the land offers (``Game._land_payment_colors``), or of
    its basic land type where the summary is silent."""
    symbols = tuple(game._land_payment_colors(land)) or tuple(land.basic_land_mana)[:1]
    if not symbols:
        return None
    return TapYield((frozenset(str(s).upper() for s in symbols),))


def _instruction_yields(game: "Game", land: "Permanent", instruction, purpose) -> list[TapYield]:
    """What running *instruction* — one tap-alone mana ability — adds.

    Read off the add-mana step's payload, the shapes ``handlers/mana`` carries
    out. A shape this does not read exactly falls back to **one** mana of what
    the engine says the land offers, which is the amount every reader assumed
    before any of them counted.
    """
    from .handlers._common import count_from_payload
    from .handlers.control_flow import evaluate_condition
    from .mana_could_produce import ability_colors_on_offer
    from .named_counters import counters_on
    from .game_types import OracleExecutionContext
    from .restricted_mana import restriction_admits

    seat = game.controller_index_of(land)
    player = game.players[seat]
    context = OracleExecutionContext(
        caster=player, target=player, card=land.card, source_permanent=land,
    )
    roots = (instruction,)
    if instruction.kind == "if_then":
        # "{T}: Add {C}. If you control an Urza's Power-Plant and an Urza's
        # Tower, add {C}{C} instead." Which branch runs is a fact about the
        # board now, asked of the evaluator the resolution asks.
        holds = evaluate_condition(game, context, instruction.payload.get("condition") or {})
        roots = tuple(instruction.payload.get("then" if holds else "else") or ())
    steps = [
        step for root in roots for step in (root, *_every_nested_step(root))
        if step.kind in MANA_PRODUCING_KINDS
    ]
    if len(steps) != 1:
        # More than one producing step (or none this reads): one mana, of what
        # the land offers.
        fallback = _summary_yield(game, land)
        return [fallback] if fallback is not None else []
    payload = steps[0].payload or {}
    spend_only = payload.get("spend_only")
    if spend_only and not restriction_admits(str(spend_only), purpose):
        # "Spend this mana only to cast artifact spells" (Mishra's Workshop):
        # mana this payment may not use is not mana toward it (CR 106.6).
        return []

    alternatives = payload.get("pips_alternatives")
    if alternatives:
        return [
            TapYield(tuple(
                frozenset({str(symbol)})
                for symbol, count in alternative for _ in range(int(count))
            ))
            for alternative in alternatives
        ]
    combination = payload.get("combination")
    if combination:
        count = payload.get("combination_count", 0)
        if isinstance(count, int) and not isinstance(count, bool):
            each = frozenset(str(symbol) for symbol in combination)
            return [TapYield((each,) * max(0, count))]
    choice = payload.get("pips_choice")
    if choice:
        return [TapYield((frozenset(str(symbol) for symbol, _count in choice),))]
    pips = payload.get("pips")
    if pips:
        multiplier = 1
        if payload.get("per_each") is not None:
            multiplier = max(0, int(count_from_payload(game, context, payload["per_each"])))
        if payload.get("per_each_counter_on_source") is not None:
            multiplier = counters_on(land, str(payload["per_each_counter_on_source"]))
        if any(payload.get(key) is not None for key in (
            "pips_amount", "per_each_counter_removed", "per_each_counter_removed_this_way",
        )):
            # A count the ability's own cost or announcement supplies: not a
            # tap-alone shape. One mana, as before.
            multiplier = 1
        return [TapYield(tuple(
            frozenset({str(symbol)})
            for symbol, count in pips for _ in range(int(count) * multiplier)
        ))]
    any_count = payload.get("any_color_count")
    if any_count is not None and isinstance(any_count, int) and not isinstance(any_count, bool):
        # The whole ability, not the one step: the colour may be narrowed by a
        # step beside it ("Choose a color of a permanent you control. …").
        offered = ability_colors_on_offer(game, land, instruction)
        symbols = frozenset(PIP_SYMBOLS if offered is None else offered)
        if not symbols or any_count <= 0:
            return []
        return [TapYield((symbols,) * any_count, one_color=any_count > 1)]
    fallback = _summary_yield(game, land)
    return [fallback] if fallback is not None else []


def _under_a_swap(game: "Game", land: "Permanent", found: TapYield) -> TapYield:
    """*found* as CR 106.12b's "produces … instead" leaves it (Deep Water,
    Contamination, Harvest Mage) — the substitution the seam applies to
    whatever the land's ability put in the pool."""
    from . import land_mana_swaps

    swap = land_mana_swaps.swapped_production(game, land)
    offered = land_mana_swaps.payment_colors(game, land)
    if swap is None or offered is None or not found.units:
        return found
    colours = frozenset(offered) - {"C"} if swap.colors_only else frozenset(offered)

    def swapped(unit: frozenset[str]) -> frozenset[str]:
        if not swap.colors_only:
            return colours
        return (unit & {"C"}) | (colours if unit - {"C"} else frozenset())

    units = tuple(swapped(unit) for unit in found.units)
    if swap.replaces_amount:
        units = units[:1]
    return TapYield(units, one_color=found.one_color and len(units) > 1)


def _aura_units(land: "Permanent") -> "tuple[frozenset[str], ...]":
    """"Whenever enchanted land is tapped for mana, its controller adds an
    additional {G}." (Wild Growth, Fertile Ground.) Added by the seam on every
    tap, whatever the land's own ability made."""
    from .auras import AURA_ANY_COLOR_MANA, aura_additional_mana_on_tap

    aura = land.metadata.get("attached_aura")
    if aura is None:
        return ()
    return tuple(
        frozenset(PIP_SYMBOLS) if extra == AURA_ANY_COLOR_MANA else frozenset({str(extra)})
        for extra in aura_additional_mana_on_tap(aura.effective_card.oracle_text)
    )


def land_tap_yields(game: "Game", land: "Permanent", purpose=None) -> list[TapYield]:
    """Every way one tap of *land* through the tap seam can come out, toward a
    payment for *purpose*. Empty when the seam makes no mana from it now: a
    tapped land, a storage land with nothing to remove, a Bazaar of Baghdad, a
    summoning-sick land creature, a land whose mana this payment may not spend.
    """
    yields: list[TapYield] = []
    for instruction in _seam_abilities(game, land):
        if instruction is None:
            summary = _summary_yield(game, land)
            found = [summary] if summary is not None else []
        else:
            found = _instruction_yields(game, land, instruction, purpose)
        for item in found:
            item = _under_a_swap(game, land, item)
            if not item.units:
                continue
            yields.append(TapYield(item.units + _aura_units(land), item.one_color))
    return yields


def _expanded(yields: list[TapYield]) -> "list[tuple[frozenset[str], ...]]":
    """*yields* as plain unit tuples the matching can take.

    Alternatives that are each **one** mana fold into one unit with the union
    of their symbols — tapping for {C} or for {W}/{U} is one mana of one of
    three symbols. A shared colour is written out once per colour it could be.
    """
    plain: list[tuple[frozenset[str], ...]] = []
    for item in yields:
        if item.one_color:
            shared = set.intersection(*(set(unit) for unit in item.units))
            plain.extend(
                tuple(frozenset({symbol}) for _ in item.units) for symbol in sorted(shared)
            )
        else:
            plain.append(item.units)
    singles = [units[0] for units in plain if len(units) == 1]
    rest = [units for units in plain if len(units) != 1]
    if singles:
        rest.insert(0, (frozenset().union(*singles),))
    # A yield another one covers unit for unit adds no way to pay.
    return list(dict.fromkeys(rest))


def _pays(player, symbols: frozenset[str], *, as_any_type: bool = False,
          as_any_color: bool = False) -> frozenset[str]:
    """The pips one unit that may be any of *symbols* can pay for *player*.

    The payment's own cascade (``_pay_mana_cost_directly``), asked per unit:
    CR 106.6 permissions through ``may_pay_pip``, Chromatic Orrery's "as though
    it were mana of any color" (every unit pays a coloured pip, and {C} still
    wants colourless), Sunglasses of Urza's white-as-red.
    """
    if as_any_type:
        return frozenset(PIP_SYMBOLS) | {"C", _ANY}
    pays: set[str] = {_ANY}
    if "C" in symbols:
        pays.add("C")
    if as_any_color or player.spends_mana_as_any_color:
        return frozenset(pays | set(PIP_SYMBOLS))
    if player.mana_spending_is_general:
        permissions = player.mana_spending_permissions
        pays.update(
            pip for pip in PIP_SYMBOLS
            if any(may_pay_pip(permissions, symbol, pip) for symbol in symbols)
        )
        return frozenset(pays)
    pays.update(symbol for symbol in symbols if symbol in PIP_SYMBOLS)
    if player.can_spend_white_as_red and "W" in symbols:
        pays.add("R")
    return frozenset(pays)


def board_can_pay(game: "Game", seat: int, required: dict, *, purpose=None) -> bool:
    """Whether *seat* could pay *required* from its pool plus what tapping its
    untapped lands would add — for a payment of *purpose*
    (``restricted_mana.PaymentPurpose``), which decides what restricted mana
    and which CR 609.4 grants count.

    Pure: nothing is tapped, spent, logged or prompted for.
    """
    from .restricted_mana import CAST, spendable_restricted_mana

    player = game.players[seat]
    floating: list[frozenset[str]] = []
    held = dict(player.mana_pool)
    for symbol, amount in spendable_restricted_mana(player, purpose).items():
        held[symbol] = held.get(symbol, 0) + amount
    for symbol, amount in held.items():
        floating.extend([frozenset({str(symbol)})] * max(0, int(amount)))

    choices: list[list[tuple[frozenset[str], ...]]] = []
    for land in game.controlled_by(seat):
        if land.tapped or not land.has_type("land"):
            continue
        options = _expanded(land_tap_yields(game, land, purpose))
        if options:
            choices.append(options)

    combinations = 1
    for options in choices:
        combinations *= len(options)
    if combinations > _MAX_COLOR_ASSIGNMENTS:
        # More shared-colour lands than are worth enumerating: read each as
        # its most generous option. Over-offers; never refuses a real payment.
        choices = [[max(options, key=len)] for options in choices]

    # CR 609.4's one-spell grants (North Star), tried only where the ordinary
    # reading cannot pay — the order the payment itself spends them in.
    readings = [{}]
    if purpose is not None and purpose.kind == CAST:
        for grant in player.spend_mana_as_though_grants:
            if int(grant.get("spells", 0)) > 0:
                readings.append(
                    {"as_any_type": True} if grant.get("any_type") else {"as_any_color": True}
                )
                break

    for reading in readings:
        for picked in itertools.product(*choices):
            sources = floating + [unit for units in picked for unit in units]
            pays = [_pays(player, symbols, **reading) for symbols in sources]
            if plan_payment(
                {}, range(len(sources)), required, produces=pays.__getitem__,
            ) is not None:
                return True
    return False


__all__ = ["TapYield", "board_can_pay", "land_tap_yields"]
