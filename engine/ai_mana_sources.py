"""What one tap of a mana source makes, as the AI's payment plan counts it.

The planner (``ai_payment``) matches a cost against units of mana; this is
where each permanent's units come from, and which permanents it may count
at all.

* **A land** is read through the engine's own answer to what its tap makes
  (:func:`_land_tap_options`, over ``board_payment.land_tap_yields`` — the
  reading the castable highlight takes, so the card that glows and the card
  the AI casts are judged on one account), with the run of different symbols
  one tap makes (:func:`_land_mixed_run`), every symbol a tap-alone ability
  makes (:func:`_land_symbols`), and the mana no plan can count — restricted
  or board-dependent (:func:`_land_mana_is_unplannable`).
* **A non-land** permanent is counted for an ability whose whole cost is {T}
  and whose output its payload states, or one that pays by sacrificing only
  itself (:func:`_nonland_mana_source`: the Moxen, Sol Ring, Llanowar Elves,
  Black Lotus).
* **A source whose mana costs mana** (the Odyssey filter lands, Mana Cylix)
  is :func:`_priced_mana_source`'s, for the plan to put the taps that pay
  its price in front of it.

Each answers None where the payload cannot say, and the plan leaves that
source out: mana counted that a tap will not make is a cast refused for
insufficient mana.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .ai_valuation import mana_ability_symbols, planned_mana_yield
from .activation_permissions import activation_permission_denial
from .activation_restrictions import activation_denial, global_activation_ban
from .game import Game
from .auras import aura_restriction_active
from .models import Permanent
from .oracle import compile_card_oracle
from .targeting import usable_activated_abilities


_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")


@dataclass(frozen=True)
class _PricedManaSource:
    """A mana ability that costs mana, as the payment plan counts it — see
    `_priced_mana_source`."""

    #: Which of the permanent's usable abilities.
    ability_index: int
    #: The generic mana one activation costs, beside the tap.
    price: int
    #: Every symbol one activation may be asked for, the unasked one first.
    symbols: tuple[str, ...]
    #: How many mana of the asked symbol.
    amount: int
    #: A fixed run of different symbols ("{U}{B}"), or None.
    run: "dict[str, int] | None" = None

    def outputs(self) -> "list[tuple[str, dict[str, int]]]":
        """``(symbol to ask for, what that activation adds)``, one per answer."""
        if self.run is not None:
            return [(self.symbols[0], dict(self.run))]
        return [(symbol, {symbol: self.amount}) for symbol in self.symbols]


def _priced_mana_source(
    game: Game, seat: int, permanent: "Permanent | None"
) -> "_PricedManaSource | None":
    """The mana ability of a permanent *seat* controls whose cost is **generic
    mana and {T}** and which is the only mana that permanent makes — or None.

    "{1}, {T}: Add {U}{B}." (Darkwater Catacombs and the other four Odyssey
    filter lands), "{1}, {T}: Add one mana of any color." (Mana Cylix,
    Helionaut), "{2}, {T}: …" (Celestial Prism). **A land of this kind was a
    land that made nothing for an AI seat**: the tap seam runs only an ability
    whose whole cost is {T} (`land_mana_tap_refusal` answers
    ``priced_mana_ability``), so the planner left it out and the seat counted
    one land fewer than it controlled — ten filter lands were played in a
    ten-game seeded Odyssey run and not one was ever activated (W1G2 saw the
    same in six).

    The cheap half of ROADMAP's "costed and sacrifice mana sources": a price
    paid in mana renumbers nothing, where a sacrifice during payment moves the
    battlefield under an announcement made by index. What it needs instead is
    an *input* — a unit of mana from another source, in the pool before this
    one is activated — which is `ai_payment._plan_through_a_priced_source`'s to arrange.

    Narrow on purpose, each clause a shape this cannot plan:

    * **only generic mana in the price** — "{G}, {T}: Add {R}." (Fire Sprites)
      needs a coloured input, a second matching problem;
    * **only with {T}** — "{1}: Add {B}." (Bog Initiate) may be activated any
      number of times, and how many is a search, not a tap;
    * **no other mana ability on the permanent** — a land that also taps for
      mana on its own (the Homelands tri-lands, Crystal Quarry) is already the
      free planner's, and one slot in a plan cannot say which ability it means;
    * **a yield the payload states** (`ai_valuation.planned_mana_yield`), with
      no rider.

    And only one the activation path will accept, by the gates
    `_nonland_mana_source` asks: untapped, not a summoning-sick creature, not
    under a ban or a permission that closes it to this seat.
    """
    import dataclasses

    from .activation_restrictions import prints_activation_restriction
    from .mana_payment import carries_an_offer
    from .mana_payment import is_mana_ability as is_cr_mana_ability
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .spell_prohibitions import permanent_activations_forbidden

    if permanent is None or permanent.tapped:
        return None
    if game.land_mana_tap_refusal(permanent) not in (
        "priced_mana_ability", "not_an_untapped_land",
    ):
        # A land the seam taps (None), or one it refuses for a reason that is
        # not about the price: summoning sick, forbidden, stripped.
        return None
    if game._is_summoning_sick(permanent):
        return None
    usable = game.usable_abilities_of(permanent)
    found: "_PricedManaSource | None" = None
    for index, ability in enumerate(usable):
        if is_tap_alone_mana_ability(ability):
            return None
        if not is_cr_mana_ability(ability):
            continue
        if found is not None:
            # Two priced mana abilities: which one a plan's slot means is not
            # something a slot can say.
            return None
        cost = ability.cost
        mana = {symbol: int(amount or 0) for symbol, amount in cost.mana.items()}
        generic = mana.get("generic", 0)
        if generic < 1 or any(amount for symbol, amount in mana.items() if symbol != "generic"):
            return None
        if cost != dataclasses.replace(
            type(cost)(mana={symbol: 0 for symbol in cost.mana}),
            requires_tap=True, mana=cost.mana,
        ):
            return None
        line = ability.source_line or ""
        if prints_activation_restriction(line) or carries_an_offer(ability.instruction):
            return None
        produced = planned_mana_yield(ability.instruction)
        if produced is None or produced.board_narrowed or produced.from_chosen_color:
            return None
        if not produced.symbols:
            return None
        if (
            permanent_activations_forbidden(game, permanent)
            or global_activation_ban(game, permanent) is not None
            or activation_denial(game, seat, permanent, line)
            or activation_permission_denial(game, seat, permanent, line)
            or aura_restriction_active(permanent, "all_activated_abilities_shut_off")
        ):
            return None
        found = _PricedManaSource(
            ability_index=index,
            price=generic,
            symbols=produced.symbols,
            amount=produced.amount,
            run=dict(produced.run) if produced.run else None,
        )
    return found


@dataclass(frozen=True)
class _NonlandManaSource:
    """One non-land permanent's mana ability as the payment plan counts it."""

    #: Which of the permanent's usable abilities — the index the activation
    #: path addresses one by.
    ability_index: int
    #: Every symbol one activation may be asked for, the unasked one first.
    symbols: tuple[str, ...]
    #: How many mana of the asked symbol.
    amount: int
    #: A fixed run of different symbols, or None (`_land_mixed_run`'s shape).
    run: "dict[str, int] | None" = None
    #: Whether the activation **sacrifices the source** ("{T}, Sacrifice this
    #: artifact: Add three mana of any one color"). Mana a plan may count only
    #: under `ai_payment._may_sacrifice_for` — see `_nonland_mana_source`.
    sacrifices: bool = False


def _sacrifices_only_itself(cost) -> bool:
    """Whether *cost* is "Sacrifice this permanent", with or without {T}, and
    **nothing else** — no mana, no card, no counter, no life, no other
    permanent.

    Compared against a default cost rather than by listing what must be empty,
    for `turn_management._is_free_beyond_tapping`'s reason: a list would start
    ignoring any cost component added later, and ignoring one here is the AI
    paying a price it never weighed.
    """
    empty = type(cost)(mana={symbol: 0 for symbol in cost.mana})
    return bool(cost.sacrifice_self) and replace(cost, requires_tap=False) == replace(
        empty, sacrifice_self=True
    )


def _nonland_mana_source(
    game: Game, seat: int, permanent: "Permanent | None", *, may_sacrifice: bool = False,
) -> "_NonlandManaSource | None":
    """The mana ability of a **non-land** permanent *seat* controls that its
    payment plan may count right now, or None.

    **The AI never tapped anything but a land for mana.** `ai_payment._plan_land_taps`
    asked the tap seam's gate of every permanent, and that gate's first line
    refuses a non-land — so the Moxen, Sol Ring, Llanowar Elves, Birds of
    Paradise and the rest were cast (`ai_valuation.mana_ability_amount` scores them) and
    then sat untapped for the whole game: 64 "{T}: Add …" abilities on 63
    permanents across both manifest roles, 62 of them shipped, and in ten
    seeded Alpha games nineteen such permanents entered the battlefield and
    none made a mana.

    **An ability whose whole cost is {T}** (`is_tap_alone_mana_ability`, the
    tap seam's own predicate — which also excludes a printed "Activate only …"
    and an ability that asks another player something) is the free mana, and
    the only kind this answers with unless asked for more.

    ***may_sacrifice* asks for the other kind the plan can price: a source
    that pays by sacrificing itself** — "{T}, Sacrifice this artifact: Add
    three mana of any one color" (Black Lotus, Lotus Petal), "Sacrifice this
    creature: Add {B}" (Blood Pet, Basal Thrull, Tinder Wall, Morgue Toad).
    Returned with ``sacrifices`` set, and never for a permanent that also has a
    free mana ability: Eye of Ramos' "Sacrifice this artifact: Add {U}" beside
    its "{T}: Add {U}" would trade a mana every turn for one mana now. Whether
    a plan may *count* one is `ai_payment._may_sacrifice_for`'s question, not this
    function's — this says what the ability is. An untapped permanent is asked
    for only where the ability taps ({T} in the cost is CR 302.6's as well),
    so a tapped or summoning-sick Blood Pet is still a mana.

    Everything else stays out, and that is the stated limit of what the AI
    will give up for mana: **never another permanent** ("Sacrifice a
    creature", Ashnod's Altar, Phyrexian Altar; "Sacrifice a land", Squandered
    Resources), **never a card** (Bog Witch, Skirge Familiar, Lion's Eye
    Diamond's whole hand, Cadaverous Bloom), **never a counter or life** (the
    Mana Batteries, Iceberg, Phyrexian Lens) — each is a choice of *which* or
    *how many* that this plan has no valuation for. A source that costs mana
    to make mana ("{1}, {T}: Add one mana of any color", Mana Cylix; the
    Odyssey filter lands) is not this function's either: it is counted apart,
    as a last resort and behind the tap that pays for it
    (`_priced_mana_source`), and one that also sacrifices itself ("{1},
    Sacrifice this creature: Add {U}{B}{R}", the Attendants) stays out.

    **And only one the activation path will accept**, the non-land twin of
    `land_mana_tap_refusal`: untapped; not a summoning-sick creature (CR 302.6
    — a {T} ability is a {T} ability); not under a ban on its activated
    abilities (Interdict, Null Rod, Cursed Totem, Volrath's Curse) or a
    permission that closes it to this seat. Those are the gates
    `ai_abilities.choose_activation_action` asks of the tables the engine enforces; asked
    here for the same reason — a source counted and then refused is a cast
    refused for insufficient mana, the same spell every turn.

    What the activation makes is `ai_valuation.planned_mana_yield`, with the
    two answers only the game has: which colours a "could produce" clause
    offers on this board (none is no source at all), and the colour a source
    chose as it entered.
    """
    from .activation_restrictions import prints_activation_restriction
    from .mana_could_produce import ability_colors_on_offer
    from .mana_payment import carries_an_offer
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .spell_prohibitions import permanent_activations_forbidden

    if permanent is None:
        return None
    if permanent.has_type("land") or (
        not permanent.tapped
        and game.land_mana_tap_refusal(permanent) != "not_an_untapped_land"
    ):
        # A land (the seam's own reading of which permanents are its) — the
        # land half of the plan answers for it, whatever it answers.
        return None
    # The permanent's own list: a Sol Ring under Titania's Song has lost its
    # mana ability, and planning its mana planned a cast the pool cannot pay.
    usable = game.usable_abilities_of(permanent)
    taps_alone = any(is_tap_alone_mana_ability(ability) for ability in usable)
    if not taps_alone and not may_sacrifice:
        return None
    ready = not permanent.tapped and not game._is_summoning_sick(permanent)
    for index, ability in enumerate(usable):
        if taps_alone:
            if not ready:
                return None
            if not is_tap_alone_mana_ability(ability):
                continue
        else:
            # A source that pays by leaving. Asked only of a permanent with no
            # free mana ability, and held to the two things the tap seam's
            # predicate holds a free one to.
            if ability.instruction is None or not _sacrifices_only_itself(ability.cost):
                continue
            if ability.cost.requires_tap and not ready:
                continue
            if prints_activation_restriction(
                ability.source_line or ""
            ) or carries_an_offer(ability.instruction):
                continue
        produced = planned_mana_yield(ability.instruction)
        if produced is None:
            continue
        symbols = produced.symbols
        if produced.board_narrowed:
            symbols = tuple(ability_colors_on_offer(game, permanent, ability.instruction) or ())
        elif produced.from_chosen_color:
            chosen = (permanent.metadata or {}).get("chosen_color")
            symbols = (chosen,) if chosen in _MANA_SYMBOLS else ()
        if not symbols:
            continue
        line = ability.source_line or ""
        if (
            permanent_activations_forbidden(game, permanent)
            or global_activation_ban(game, permanent) is not None
            or activation_denial(game, seat, permanent, line)
            or activation_permission_denial(game, seat, permanent, line)
            or aura_restriction_active(permanent, "all_activated_abilities_shut_off")
        ):
            return None
        return _NonlandManaSource(
            ability_index=index,
            symbols=symbols,
            amount=produced.amount,
            run=dict(produced.run) if produced.run else None,
            sacrifices=not taps_alone,
        )
    return None


@dataclass(frozen=True)
class _TapOption:
    """One way one tap of a mana source can come out, as the plan counts it.

    ``units`` is one entry per mana, each the symbols that mana may be — the
    shape `board_payment.TapYield` has and `mana_payment.plan_payment` matches
    over. ``ask`` is the colour an executor asks the source for to get this
    outcome, where the outcome fixes one ("three mana of any one color", as
    {R}); None where the pip the plan assigns decides (`ai_payment._asked_color`).
    """

    units: "tuple[frozenset[str], ...]"
    ask: "str | None" = None


def _land_tap_options(game: Game, land: Permanent, purpose) -> "tuple[_TapOption, ...]":
    """Every way one tap of *land* comes out, read off
    `board_payment.land_tap_yields` — **the reading the castable highlight
    takes**, so the card that glows and the card the AI casts are judged on
    one account of what a land makes.

    This planner kept its own (`_land_symbols`, `_land_mana_amount`,
    `_land_mixed_run`), and the two had come apart: Ancient Tomb's "{T}: Add
    {C}{C}. This land deals 2 damage to you." is a two-step effect whose pips
    the amount reader did not open, so the AI counted one mana where the
    highlight counted two (8 of 14,626 land-and-cost pairs), and a land whose
    amount the board decides — Gaea's Cradle — was left out of every plan.

    The outcomes that are **one** mana fold into a single unit offering every
    symbol any of them makes (a painland's {C} and its two colours), which is
    the choice the executor makes with the colour it asks for; a shared colour
    ("two mana of any one color") is one option per colour.
    """
    from .board_payment import land_tap_yields

    singles: set[str] = set()
    options: list[_TapOption] = []
    for found in land_tap_yields(game, land, purpose):
        units = tuple(found.units)
        if found.one_color and len(units) > 1:
            shared = set.intersection(*(set(unit) for unit in units))
            options.extend(
                _TapOption(tuple(frozenset({symbol}) for _ in units), ask=symbol)
                for symbol in _MANA_SYMBOLS if symbol in shared
            )
        elif len(units) == 1:
            singles |= set(units[0])
        elif units:
            options.append(_TapOption(units))
    if singles:
        options.insert(0, _TapOption((frozenset(singles),)))
    return tuple(dict.fromkeys(options))


def _nonland_tap_options(source: _NonlandManaSource) -> "tuple[_TapOption, ...]":
    """`_land_tap_options` for a non-land source: a fixed run of symbols, one
    mana of a choice of symbols, or several of one chosen symbol."""
    if source.run:
        return (_TapOption(tuple(
            frozenset({symbol}) for symbol, count in source.run.items() for _ in range(count)
        )),)
    if source.amount <= 1:
        return (_TapOption((frozenset(source.symbols),)),)
    return tuple(
        _TapOption(tuple(frozenset({symbol}) for _ in range(source.amount)), ask=symbol)
        for symbol in source.symbols
    )


def _land_mixed_run(game: Game, permanent: Permanent) -> "dict[str, int] | None":
    """The fixed run one tap of *permanent* makes when it is **two or more
    different symbols** ("{C}{U}", Coral Atoll), as ``{symbol: count}`` — or
    None for every other land, whose tap is a number of one symbol.

    Not read by `ai_payment._plan_land_taps` any more, which counts a land through
    `board_payment.land_tap_yields`; kept as the statement of what a mixed
    land's tap makes that `tests/ai/test_ai_land_mana_plans.py` holds the tap
    seam to.

    Read off the free ability the tap seam will run and only where nothing
    else decides the output: a seat-wide swap replaces the type (and perhaps
    the amount), and a multiplier or a restriction makes the run something
    this cannot state.
    """
    from . import land_mana_swaps

    if land_mana_swaps.swapped_production(game, permanent) is not None:
        return None
    free, _priced = game._land_mana_abilities(permanent)
    payload = (getattr(free, "payload", None) or {}) if free is not None else {}
    pips = payload.get("pips")
    if not pips or len(payload) != 1:
        return None
    run = {str(symbol): int(count) for symbol, count in pips}
    return run if len(run) >= 2 else None


#: Payload keys on a land's add-mana step that make **how much** one tap
#: produces a fact about the rest of the board rather than about the land:
#: "{G} for each creature you control" (Gaea's Cradle), "{C} for each storage
#: counter on this land" (City of Shadows). The planner counts a tap as its
#: printed pips, so these read as one mana each — on an empty board, zero.
#:
#: ``any_type_from_lands`` ("one mana of any type that a land you control could
#: produce", Reflecting Pool) was a third entry here and is not one: its amount
#: is the printed one, and *which* type is `Game.narrowed_land_mana_colors`'
#: exact answer since PLS wave 1 — the same reader that makes Meteor Crater
#: plannable below. Listed here it stayed out of every plan, so a seat with a
#: Swamp and a Reflecting Pool could not cast a two-mana spell.
_BOARD_DEPENDENT_MANA_KEYS = ("per_each", "per_each_counter_on_source")


def _land_mana_is_unplannable(game: Game, land: Permanent) -> bool:
    """Whether the mana *land*'s default tap makes is **restricted** ("Spend
    this mana only …", CR 106.6 — the ``spend_only`` the add-mana handler
    files it under) or **board-dependent** (`_BOARD_DEPENDENT_MANA_KEYS`).

    This was the planner's exclusion list: such a land was left out of every
    plan rather than guessed at. `ai_payment._plan_land_taps` no longer asks it — it
    counts a land through `board_payment.land_tap_yields`, which reads a
    restriction against what the payment is for and a board-counted amount
    off the board — so a Gaea's Cradle beside three creatures is three mana
    and Mishra's Workshop pays for an artifact spell. Kept because three test
    files read it as the description of which lands those are.
    """
    free, _priced = game._land_mana_abilities(land)
    if free is None:
        return False
    payload = free.payload or {}
    if payload.get("spend_only"):
        return True
    if any(
        (step.payload or {}).get(key)
        for step in (free, *((payload.get("steps") or ())))
        for key in _BOARD_DEPENDENT_MANA_KEYS
        if hasattr(step, "payload")
    ):
        return True
    # A land whose *colours* the board decides and whose amount it does not
    # ("Choose a color of a permanent you control. Add one mana of that
    # color.", Meteor Crater) is plannable for exactly what that board offers
    # now — `Game._land_payment_colors` answers with it — and unplannable only
    # where it offers nothing: `_land_symbols` would fall back to "C" for a
    # land with no symbol, the tap would make no mana, and the cast would be
    # refused for the same spell every turn.
    narrowed = game.narrowed_land_mana_colors(land)
    return narrowed is not None and not narrowed


def _tap_alone_land_symbols(game: Game, land: Permanent) -> set[str]:
    """Every symbol one of *land*'s tap-alone mana abilities makes — the
    abilities the tap seam runs (`ai_payment.planned_tap_ability` picks among them), and
    none it refuses (`land_mana_tap_refusal`)."""
    from .mixins.turn_management import is_tap_alone_mana_ability

    found: set[str] = set()
    usable = usable_activated_abilities(compile_card_oracle(game.playable_card_of(land)))
    for index, ability in enumerate(usable):
        if is_tap_alone_mana_ability(ability) and game.land_mana_tap_refusal(land, index) is None:
            found |= mana_ability_symbols(ability.instruction)
    return found


def _land_symbols(game: Game, permanent: Permanent) -> tuple[str, ...]:
    """Every symbol tapping *permanent* for mana could put in the pool, the one
    it would make unasked first.

    ``Game._land_payment_colors`` — the engine's own answer, swaps and granted
    abilities included — and the basic land types layer 4 gives it where that
    is silent. "C" for a land that names neither, which is what this planner
    has always assumed of one.
    """
    from . import land_mana_swaps

    symbols = tuple(game._land_payment_colors(permanent))
    free, _priced = game._land_mana_abilities(permanent)
    if symbols and game.narrowed_land_mana_colors(permanent) is not None:
        # A land whose colours the board defines (Reflecting Pool, Meteor
        # Crater): `_land_payment_colors` has already answered with exactly
        # what that board offers. The reordering below would widen it back to
        # every colour the compiled ability *could* name — "any color" reads
        # as all five there — which is the summary's mistake made a second
        # time.
        return symbols
    if symbols and free is not None and not land_mana_swaps.payment_colors(game, permanent):
        # **Only what the tap can make.** ``_land_payment_colors`` is the
        # printed summary for an unswapped land, and the summary lists every
        # symbol any of the land's abilities makes — including one behind a
        # mana price the tap seam will not pay: Henge of Ramos and Castle
        # Sengir summarise to five colours and tap for {C}. Counted as
        # coloured, the plan tapped them "for" a red pip, made {C} and the
        # spell was refused. So the symbols are the tap-alone abilities' own,
        # read off the compiled program (`mana_ability_symbols`).
        #
        # And what the **default** ability makes goes first, because the
        # planner pays generic mana with a land's first symbol and the tap
        # executor runs the default ability for it (`ai_payment.planned_tap_ability`):
        # the summary is alphabetical, so an Underground River ("B", "C", "U")
        # paid a generic {1} with its painful {B} rather than its {C}.
        default = mana_ability_symbols(free)
        reachable = set(default) | _tap_alone_land_symbols(game, permanent)
        ordered = [symbol for symbol in symbols if symbol in default]
        ordered += [symbol for symbol in symbols if symbol in reachable and symbol not in ordered]
        ordered += [symbol for symbol in sorted(reachable) if symbol not in ordered]
        if ordered:
            return tuple(ordered)
    if symbols:
        return symbols
    # Layer 4 already knows which basic land types this permanent currently
    # has, printed or granted by a type-changing effect.
    basic = tuple(permanent.basic_land_mana)
    return basic if basic else ("C",)
