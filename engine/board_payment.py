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

**What a seat could tap.** Lands through the tap seam, always. With
``nonland_sources=True`` — which the castable highlight passes — also every
other permanent's mana ability whose whole cost is {T} and which the
activation path would accept now (a Sol Ring, a Mox, a Llanowar Elves that is
not summoning sick, none of them under a Null Rod or a Cursed Totem):
:func:`source_tap_yields`.

That was "lands only, by decision", and the decision is reversed here on
purpose. Its reason was that no automatic payment taps a non-land source, so
"a glow that needed one would light a card the click then cannot pay for".
Two things have changed under it. The AI *has* tapped these sources since
Planeshift (``ai_policy._nonland_mana_source``), so an AI seat cast spells the
same board showed a human as uncastable. And the question the highlight
answers is CR 601.2g's — "the player then has a chance to activate mana
abilities" — which is about what the player is *able* to do, not about which
of it this app does for them: the client's own auto-tap is the proof that the
glow already meant "castable with what you could tap" rather than "castable
from the pool". A card that is dark over a Sol Ring that pays for it is the
display saying something false; a card that glows and whose auto-tap button
is disabled (the client plans lands alone) says something true and asks for
one click on the Ring. The default stays lands-only so that a caller planning
an *automatic* payment gets the sources an automatic payment taps.

Still not counted, in either mode: a mana ability that costs more than the tap
— a storage land's counters, a filter land's mana, a Black Lotus's sacrifice.
Each is a payment in its own right, which the matching below has no way to
charge.

**And what a tap sets off.** "Whenever a player taps a land for mana, that
player adds one additional mana of any type that land produced" (Mana Flare)
is a triggered mana ability (CR 605.1b): it resolves inside the tap, and the
mana it adds is mana that tap makes. Read off ``Game.land_tap_mana_adders`` —
the seam's own walk of them, performed by nothing.

Held to the seam by ``tests/engine/test_castable_highlight_asks_the_planner.py``:
every land in the pool, alone and in a pair, with the truth found by tapping
every combination through ``tap_land_for_mana`` and casting.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mana_payment import (MANA_PRODUCING_KINDS, PIP_SYMBOLS, _every_nested_step,
                           pips_payable_by, plan_payment)

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
    three mana of any one color") rather than each chosen freely. ``extra`` is
    mana the same tap adds that is no part of that one choice — an Aura's
    "adds an additional {G}", a Gauntlet of Might's {R} — which the shared
    colour must not be narrowed by: two mana of any one colour and a Wild
    Growth's {G} is {U}{U}{G} as readily as {G}{G}{G}.
    """

    units: "tuple[frozenset[str], ...]"
    one_color: bool = False
    extra: "tuple[frozenset[str], ...]" = ()


def _seam_abilities(game: "Game", land: "Permanent") -> list:
    """The instructions the tap seam would run for *land*, one per mana
    ability a tap alone pays for — ``None`` standing for the printed-summary
    path a basic or a dual takes."""
    from .mixins.turn_management import is_tap_alone_mana_ability

    found: list = []
    if game.land_mana_tap_refusal(land) is None:
        free, _priced = game._land_mana_abilities(land)
        found.append(free)
    usable = game.usable_abilities_of(land)
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


def _instruction_yields(
    game: "Game", land: "Permanent", instruction, purpose, *, summary: bool = True
) -> list[TapYield]:
    """What running *instruction* — one tap-alone mana ability — adds.

    Read off the add-mana step's payload, the shapes ``handlers/mana`` carries
    out (:func:`_read_yields`). A shape that does not read exactly falls back
    to **one** mana of what the engine says the land offers, which is the
    amount every reader assumed before any of them counted — unless *summary*
    is off (a non-land source, which has no tap seam and so no summary path),
    where it counts nothing.
    """
    found = _read_yields(game, land, instruction, purpose)
    if found is not None:
        return found
    fallback = _summary_yield(game, land) if summary else None
    return [fallback] if fallback is not None else []


def _read_yields(
    game: "Game", land: "Permanent", instruction, purpose
) -> "list[TapYield] | None":
    """What running *instruction* adds, where its payload is a shape this
    module reads exactly — and **None where it is not**, which is a different
    answer from "nothing": the caller decides what an unread ability counts
    as, and the planner's hook (:func:`tap_alone_symbols`) must not mistake
    one for an ability that makes no mana.
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
        # More than one producing step (or none this reads).
        return None
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
    if payload.get("from_chosen_color"):
        # "{T}: Add one mana of the chosen color." (the Diamonds' cousins that
        # choose as they enter): the colour is on the permanent.
        chosen = (land.metadata or {}).get("chosen_color")
        return [TapYield((frozenset({str(chosen)}),))] if chosen in PIP_SYMBOLS else []
    return None


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


def _with_triggered_mana(
    game: "Game", land: "Permanent", found: TapYield, purpose
) -> TapYield:
    """*found* with what the tap's triggered mana abilities add to it —
    "an additional {R}" (Gauntlet of Might), "one additional mana of any type
    that land produced" (Mana Flare).

    The second is mana of the **same** symbol as what the land made, so it
    joins the yield as more units of the one shared choice: a Tropical Island
    under a Mana Flare is {G}{G} or {U}{U}, never {G}{U}.
    """
    from .restricted_mana import restriction_admits

    seat = game.controller_index_of(land)
    if seat is None:
        return found
    extra: list[frozenset[str]] = []
    same = 0
    for instruction in game.land_tap_mana_adders(seat, land):
        payload = instruction.payload or {}
        spend_only = payload.get("spend_only")
        if spend_only and not restriction_admits(str(spend_only), purpose):
            # "Spend this mana only to pay cumulative upkeep costs" (Snowfall).
            continue
        pips = tuple(payload.get("pips") or ())
        alt = payload.get("alt_supertype")
        if alt and land.has_supertype(str(alt)):
            pips = tuple(payload.get("alt_pips") or ())
        extra.extend(
            frozenset({str(symbol)}) for symbol, count in pips for _ in range(int(count))
        )
        same += int(payload.get("of_type_produced", 0) or 0)
    if not extra and not same:
        return found
    units = found.units
    one_color = found.one_color
    if same:
        produced = frozenset.intersection(*units) or units[0]
        if len(units) == 1 or found.one_color:
            # One choice of symbol, shared by the land's own mana and the
            # extra: more units of the same.
            units = units + (produced,) * same
            one_color = len(units) > 1 and len(produced) > 1
            if one_color:
                units = (produced,) * len(units)
        else:
            units = units + (produced,) * same
    return TapYield(units, one_color, found.extra + tuple(extra))


def source_tap_yields(
    game: "Game", permanent: "Permanent", purpose=None
) -> list[TapYield]:
    """Every way one activation of a **non-land** permanent's mana ability can
    come out, toward a payment for *purpose* — a Sol Ring's {C}{C}, a Llanowar
    Elves' {G}, a Birds of Paradise's one mana of any colour. Empty for a land
    (:func:`land_tap_yields` is the seam's) and for a source the activation
    path would refuse now.

    **Only an ability whose whole cost is {T}** — ``is_tap_alone_mana_
    ability``, the tap seam's own predicate and the one the AI's plan asks.
    And only one the door will open: the permanent's own list
    (``Game.usable_abilities_of``: nothing under Titania's Song), untapped,
    not summoning sick where it is a creature (CR 602.5a), and not prohibited
    (``activation_prohibitions.activation_prohibition`` — a Null Rod, a Cursed
    Totem, an Interdict, a City of Solitude on another player's turn).

    A shape this cannot read exactly counts for nothing, where a land falls
    back to one mana of its summary: a land's summary is the seam's own
    fallback, and a non-land source has no seam.
    """
    from .activation_prohibitions import activation_prohibition
    from .mixins.turn_management import is_tap_alone_mana_ability

    if permanent.tapped or permanent.has_type("land"):
        return []
    seat = game.controller_index_of(permanent)
    if seat is None or game._is_summoning_sick(permanent):
        return []
    yields: list[TapYield] = []
    for ability in game.usable_abilities_of(permanent):
        if not is_tap_alone_mana_ability(ability):
            continue
        if activation_prohibition(game, seat, permanent, ability) is not None:
            continue
        yields.extend(
            item for item in _instruction_yields(
                game, permanent, ability.instruction, purpose, summary=False
            )
            if item.units
        )
    return yields


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
            item = _with_triggered_mana(game, land, item, purpose)
            yields.append(
                TapYield(item.units, item.one_color, item.extra + _aura_units(land))
            )
    # …and the mana ability of a basic land type the land **gained** (Blanket
    # of Night: "…a Swamp in addition to its other land types"), which is no
    # compiled ability at all (CR 305.6). The summary path above already
    # carries it; a land with a compiled tap-alone ability of its own did not,
    # and the seam makes the gained symbol when it is asked for one the land
    # does not print.
    if game.land_mana_tap_refusal(land) is None:
        free, _priced = game._land_mana_abilities(land)
        # What the tap-alone abilities counted above already make. This asked
        # the printed summary, which also lists what a *priced* ability makes:
        # a School of the Unseen ("{2}, {T}: Add one mana of any color.")
        # under the Blanket was "already a {B} land", so the gained Swamp's
        # free {B} was never counted and a {B} spell stayed dark over it.
        counted = {
            symbol for item in yields for unit in item.units for symbol in unit
        }
        if free is not None:
            for symbol in game._gained_type_mana(land):
                if str(symbol).upper() in counted:
                    continue
                item = _under_a_swap(
                    game, land, TapYield((frozenset({str(symbol).upper()}),))
                )
                if item.units:
                    item = _with_triggered_mana(game, land, item, purpose)
                    yields.append(TapYield(
                        item.units, item.one_color, item.extra + _aura_units(land)
                    ))
    return yields


#: The order a land's symbols are listed in where nothing else orders them:
#: CR 105.1's WUBRG, then colourless.
_SYMBOL_ORDER: tuple[str, ...] = ("W", "U", "B", "R", "G", "C")


def _makes(game: "Game", land: "Permanent", instruction) -> "frozenset[str] | None":
    """Every symbol one run of *instruction* can put in the pool toward a
    payment with no purpose named — None where the shape is not read."""
    found = _read_yields(game, land, instruction, None)
    if found is None:
        return None
    return frozenset(symbol for item in found for unit in item.units for symbol in unit)


def tap_alone_symbols(game: "Game", land: "Permanent") -> "tuple[str, ...] | None":
    """Every symbol **a tap alone** can make from *land*, read ability by
    ability — or None for a land this cannot answer for (no compiled
    tap-alone ability, or one whose shape is not read), whose caller keeps the
    printed summary.

    CR 605: each mana ability is its own ability, and what a land "taps for"
    is what the abilities whose whole cost is {T} make. The printed
    ``produced_mana`` summary is a different list — every symbol *any*
    ability of the land makes, whatever it costs — and the planner's hook
    (``Game._land_payment_colors``) answered with it. So a School of the
    Unseen ("{T}: Add {C}." and "{2}, {T}: Add one mana of any color.") was
    five colours to a payment that taps and pays nothing more, and a Tinder
    Farm paid {R}{W} without being sacrificed.

    The default ability's symbols come first — what the land makes unasked —
    then the rest in WUBRG-then-colourless order, then the mana of a basic
    land type the land *gained* (CR 305.7).
    """
    from .mixins.turn_management import is_tap_alone_mana_ability

    free, _priced = game._land_mana_abilities(land)
    if free is None:
        return None
    first = _makes(game, land, free)
    if first is None:
        return None
    rest: set[str] = set()
    for index, ability in enumerate(game.usable_abilities_of(land)):
        if ability.instruction is free or not is_tap_alone_mana_ability(ability):
            continue
        if game.land_mana_tap_refusal(land, index) is not None:
            continue
        made = _makes(game, land, ability.instruction)
        if made is None:
            return None
        rest |= made
    rest |= {str(symbol).upper() for symbol in game._gained_type_mana(land)}
    ordered = [symbol for symbol in _SYMBOL_ORDER if symbol in first]
    ordered += [symbol for symbol in _SYMBOL_ORDER if symbol in rest - first]
    return tuple(ordered)


def tap_alone_ability_for(
    game: "Game", land: "Permanent", symbol: str
) -> "int | None":
    """Which of *land*'s mana abilities a tap **asked for** *symbol* runs: an
    index into ``Game.usable_abilities_of`` — or None for the default.

    CR 605.1a / CR 106.12: tapping a land for mana is activating one of its
    mana abilities, and the player chooses which. The seam ran the first one
    whatever was asked, so a Karplusan Forest asked for {R} made {C} — while
    every reader that counts the land (the planner's hook, the wire's colour
    list, the castable highlight) said it pays {R}.

    **The game's one answer** (``Game.land_mana_ability_for``), which the
    AI's executor and an effect's payer already asked: two readers choosing
    an ability two ways is a land that pays for one player and not for the
    other.
    """
    return game.land_mana_ability_for(land, symbol)


def _expanded(
    yields: list[TapYield], wanted: "frozenset[str] | None" = None,
    *, free: bool = False,
) -> "list[tuple[frozenset[str], ...]]":
    """*yields* as plain unit tuples the matching can take.

    Alternatives that are each **one** mana fold into one unit with the union
    of their symbols — tapping for {C} or for {W}/{U} is one mana of one of
    three symbols. A shared colour is written out once per colour it could be
    — **per colour the cost asks for**, when *wanted* says which those are:
    "two mana of any one color" toward {2}{G} is {G}{G} or two mana that pay
    only the generic part, and the other four colours are that second answer
    four more times. Written out five ways each, six such lands were 15,625
    assignments and past the cap below.

    *free* drops the sharing altogether (each unit chosen on its own), which
    can only over-offer: the reading for a board past the cap even so.
    """
    plain: list[tuple[frozenset[str], ...]] = []
    for item in yields:
        if item.one_color and not free:
            shared = set.intersection(*(set(unit) for unit in item.units))
            named = sorted(shared if wanted is None else shared & wanted)
            other = sorted(shared - set(named))
            plain.extend(
                tuple(frozenset({symbol}) for _ in item.units) + item.extra
                for symbol in named + other[:1]
            )
        else:
            plain.append(item.units + item.extra)
    singles = [units[0] for units in plain if len(units) == 1]
    rest = [units for units in plain if len(units) != 1]
    if singles:
        rest.insert(0, (frozenset().union(*singles),))
    # A yield another one covers unit for unit adds no way to pay.
    return list(dict.fromkeys(rest))


def _pays(player, symbols: frozenset[str], *, as_any_type: bool = False,
          as_any_color: bool = False) -> frozenset[str]:
    """The pips one unit that may be any of *symbols* can pay for *player*,
    with the mark that counts it toward a generic cost.

    ``mana_payment.pips_payable_by`` is the reading — the payment's own
    cascade, asked per unit — and it is shared with ``plan_payment``, which is
    how an effect-priced cost and the castable highlight come to agree about a
    seat's CR 106.6 permissions.
    """
    return pips_payable_by(
        player, symbols, as_any_type=as_any_type, as_any_color=as_any_color,
    ) | {_ANY}


def board_can_pay(
    game: "Game", seat: int, required: dict, *, purpose=None,
    nonland_sources: bool = False,
) -> bool:
    """Whether *seat* could pay *required* from its pool plus what tapping its
    untapped lands would add — for a payment of *purpose*
    (``restricted_mana.PaymentPurpose``), which decides what restricted mana
    and which CR 609.4 grants count.

    *nonland_sources* also counts what activating every other permanent's
    tap-alone mana ability would add (:func:`source_tap_yields`): the question
    a **player** is asked, who may activate them (CR 601.2g), where the
    default is the question an automatic payment asks, which taps lands.

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

    # Which symbols the cost names: a shared colour is worth telling apart
    # only where it is one of these.
    wanted = frozenset(
        str(symbol) for symbol, amount in required.items()
        if symbol != "generic" and int(amount or 0) > 0
    )
    found: list[list[TapYield]] = []
    for permanent in game.controlled_by(seat):
        if permanent.tapped:
            continue
        if permanent.has_type("land"):
            yields = land_tap_yields(game, permanent, purpose)
        elif nonland_sources:
            yields = source_tap_yields(game, permanent, purpose)
        else:
            continue
        if yields:
            found.append(yields)

    def assignments(free: bool):
        expanded = [_expanded(yields, wanted, free=free) for yields in found]
        expanded = [options for options in expanded if options]
        total = 1
        for options in expanded:
            total *= len(options)
        return expanded, total

    choices, combinations = assignments(free=False)
    if combinations > _MAX_COLOR_ASSIGNMENTS:
        # More shared-colour sources than are worth enumerating even so: each
        # unit read as free to differ. Over-offers; never refuses a real
        # payment. (This read each land as its *first* longest option — all
        # white — which refused every payment that wanted another colour.)
        choices, _combinations = assignments(free=True)
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


__all__ = [
    "TapYield", "board_can_pay", "land_tap_yields", "source_tap_yields",
    "tap_alone_ability_for", "tap_alone_symbols",
]
