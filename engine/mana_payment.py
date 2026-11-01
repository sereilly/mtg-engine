"""Whether a player can pay a mana cost from what is *on the board*, and how.

There are two different questions about paying, and the engine only ever
answered one of them well. ``PoolPaymentMixin._pay_mana_cost`` spends the
**pool** — the right question while casting or activating, where producing the
mana is the player's own separate action. The other question is asked by an
effect that must collect a cost with no priority window in between: "you may pay
{1}{B}. If you do, …" (Liliana's Devotee), an upkeep's "unless you pay", a
draw-step obligation. There the player never gets a chance to tap for mana, so
the payment has to look at the untapped lands as well as at the pool.

That question had one answer and it counted to a number: floating mana plus
untapped mana-producing lands, against a **generic** cost. Every printed
"you may pay" with a coloured pip in it therefore refused at compile time, which
is honest and also permanent — the lowering could not admit a cost the payer
could not collect.

**Why an exact matching rather than a greedy pick.** Assigning lands to coloured
pips one at a time gets a board wrong that can genuinely pay: a Swamp and a
Dimir dual against {U}{B} is fine, but a greedy pass that spends the dual on the
{B} strands the {U}. Guessing wrong here does not overpay — it *under*-reports,
so a cost the player could pay is never offered — and CR 601.2h's "unpayable
costs can't be paid" is about what the player is *able* to do, not about what an
approximation could find. The numbers are tiny (a handful of pips against a
handful of lands), so the exact answer is a dozen lines of augmenting-path
matching and no reason to accept a heuristic.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

if TYPE_CHECKING:
    from .models import Permanent

#: The coloured symbols a cost can name, in the order a payer should try them.
#: Colourless {C} is here too: it is not a colour, but it is paid the same way —
#: by a source that produces exactly it.
COLOR_SYMBOLS: tuple[str, ...] = ("W", "U", "B", "R", "G", "C")


@dataclass(frozen=True)
class ManaPayment:
    """How a cost is to be paid: what comes out of the pool, and what is tapped.

    ``from_pool`` is per symbol and includes the pool's share of the generic
    part; ``tapped`` is the lands, in the order they should be tapped. Both are
    needed by the caller and neither can be derived from the other, which is why
    the plan is a value rather than the payment itself — a caller can ask
    "could this be paid?" without paying it, which is what CR 601.2h needs.

    ``tapped_for`` is positional beside ``tapped``: the pip each land was
    matched to, or None for a land the generic part takes. It is what the
    payer **asks the land for** — a plan's tap is the player activating that
    land's mana ability (CR 605.3a), and a land that offers a choice has to be
    told which colour the plan counted on it for
    (``Game._pay_planned_cost``).
    """

    from_pool: dict[str, int] = field(default_factory=dict)
    tapped: tuple["Permanent", ...] = ()
    tapped_for: tuple["str | None", ...] = ()


def fungible_colors_headroom(
    pool: dict[str, int], required: dict[str, int]
) -> int | None:
    """Units left over after *pool* pays *required* with every unit fungible for
    a **colour** (CR 609.4, "you may spend mana as though it were mana of any
    color"), or None when it cannot pay at all.

    Chromatic Orrery's permission, as the one arithmetic three readers ask.
    They ask different questions of it -- can this be paid, how much X is
    affordable, may the client offer the card -- and the answers have to agree,
    which is exactly what three copies of a payment rule do not do: the
    permission was honoured by the payment alone, so an {X} spell with a
    coloured pip inferred X = 0 off a colourless pool and resolved for nothing,
    and the client greyed out a card the engine would have cast.

    Colourless is a **source** and not a destination. Every unit pays a coloured
    pip, the Orrery's own {C} included, because that is what the card is for --
    but a {C} the cost names still wants colourless, since colourless is not a
    colour (CR 105.1) and the printed permission grants colours. So the
    colourless the cost names has to survive whatever the pips took, which is
    the second test below and the only subtle line here.

    The leftover is what an {X} can grow into: X is generic, and under this
    permission every remaining unit pays generic.
    """
    held = {sym: max(0, int(pool.get(sym, 0))) for sym in COLOR_SYMBOLS}
    total = sum(held.values())
    colored_pips = sum(int(required.get(sym, 0)) for sym in ("W", "U", "B", "R", "G"))
    colorless = int(required.get("C", 0))
    generic = int(required.get("generic", 0))
    if total < colored_pips + colorless + generic:
        return None
    if held["C"] < colorless + max(0, colored_pips - (total - held["C"])):
        return None
    return total - colored_pips - colorless - generic


def fungible_types_headroom(
    pool: dict[str, int], required: dict[str, int]
) -> int | None:
    """:func:`fungible_colors_headroom` with **colourless in the set** too --
    CR 106.1b's five colours and colorless, which is what "as though it were
    mana of any *type*" means (North Star).

    Short where that one is careful, and the difference is the whole of why
    they are two functions rather than one with a flag: with colorless
    reachable, a {C} the cost names is payable by a coloured unit, so nothing
    has to be reserved and no pip can starve one. The payment collapses to a
    single question about the total.
    """
    total = sum(max(0, int(pool.get(sym, 0))) for sym in COLOR_SYMBOLS)
    owed = sum(int(required.get(sym, 0)) for sym in COLOR_SYMBOLS)
    owed += int(required.get("generic", 0))
    return None if total < owed else total - owed


#: The five colours a *pip* can be. Colourless is a pool symbol and never a
#: coloured pip, which is why this is not ``COLOR_SYMBOLS`` above.
PIP_SYMBOLS: tuple[str, ...] = ("W", "U", "B", "R", "G")


def may_pay_pip(permissions: Sequence, symbol: str, pip: str) -> bool:
    """Whether one unit of *symbol* mana may pay a coloured *pip* for a seat
    holding *permissions* (``engine/mana_spending.ManaSpending``).

    With no permission the answer is the rule: a unit pays its own colour and
    nothing else. With permissions it is **any** of them — CR 106.6 grants are
    additive, so a restriction one source prints cannot reach the mana another
    source freed. That is the whole reason this is an ``any`` and not a fold:
    Celestial Dawn beside Sunglasses of Urza is a seat whose Swamp pays ``{B}``
    again, because Sunglasses says nothing about black mana and the Dawn's
    "only" clause is a property of the Dawn's own permission.
    """
    if not permissions:
        return symbol == pip
    return any(permission.may_pay(symbol, pip) for permission in permissions)


def _assign_pips(
    pool: dict[str, int], required: dict[str, int], permissions: Sequence
) -> dict[str, int] | None:
    """*pool* with the coloured pips of *required* paid, or None.

    Augmenting-path matching (Kuhn's), the same shape :func:`_match_colored`
    uses over lands and for the same reason: exact is the requirement rather
    than a nicety. A greedy assignment under-reports a pool that could pay --
    spend the white on the red pip and the white pip starves -- and CR 601.2h
    asks what a player is *able* to do, not what one pass of a loop managed.

    The units are expanded one per unit, which is what keeps this obviously
    correct rather than a capacity argument that has to be re-derived: a mana
    pool is a handful of units and the matching is over a handful of pips.
    Colourless units are offered **last**, so a cost that also names ``{C}`` is
    not starved by a pip a coloured unit could have paid -- a preference inside
    the matching, which still backtracks past it when it cannot be honoured.
    """
    left = {symbol: max(0, int(pool.get(symbol, 0))) for symbol in COLOR_SYMBOLS}
    units: list[str] = []
    for symbol in tuple(PIP_SYMBOLS) + ("C",):
        units.extend([symbol] * left[symbol])
    pips: list[str] = []
    for pip in PIP_SYMBOLS:
        pips.extend([pip] * int(required.get(pip, 0)))
    if not pips:
        return left

    holder: dict[int, int] = {}  # unit index -> pip index

    def place(pip_index: int, seen: set[int]) -> bool:
        pip = pips[pip_index]
        for unit_index, symbol in enumerate(units):
            if unit_index in seen or not may_pay_pip(permissions, symbol, pip):
                continue
            seen.add(unit_index)
            if unit_index not in holder or place(holder[unit_index], seen):
                holder[unit_index] = pip_index
                return True
        return False

    for index in range(len(pips)):
        if not place(index, set()):
            return None
    for unit_index in holder:
        left[units[unit_index]] -= 1
    return left


def spend_under_permissions(
    pool: dict[str, int], required: dict[str, int], permissions: Sequence = (),
    *, wants=None, others=(),
) -> dict[str, int] | None:
    """*pool* after paying *required* under CR 106.6 *permissions*, or None.

    The one arithmetic every payment site asks, generalised from
    :func:`fungible_colors_headroom` when Celestial Dawn arrived with a
    permission the two booleans on ``PlayerState`` could not express: white mana
    pays any colour and every other unit pays none, not even its own. Three
    buckets in the order that makes the payment maximal -- the coloured pips
    (pickiest), then ``{C}``, which nothing else can pay, then the generic
    remainder from whatever is left: which of it, against the payer's *wants*
    with *others* (its untapped lands) beside it, is
    :func:`pool_spent_on_generic`'s — colourless first where nothing is wanted.
    """
    after = _assign_pips(pool, required, permissions)
    if after is None:
        return None
    colorless = int(required.get("C", 0))
    if after["C"] < colorless:
        return None
    after["C"] -= colorless
    generic = int(required.get("generic", 0))
    if sum(max(0, amount) for amount in after.values()) < generic:
        return None

    def pays_of(symbol: str) -> frozenset:
        return frozenset(
            pip for pip in COLOR_SYMBOLS
            if (pip == "C" and symbol == "C")
            or (pip != "C" and may_pay_pip(permissions, symbol, pip))
        )

    for symbol, spent in pool_spent_on_generic(
        after, generic, wants, others=others, pays_of=pays_of,
    ).items():
        after[symbol] -= spent
    return after


def pips_payable_by(
    player, symbols: "frozenset[str]", *, as_any_type: bool = False,
    as_any_color: bool = False,
) -> "frozenset[str]":
    """The pips one unit of mana that may be any of *symbols* can pay for
    *player* — coloured pips and ``{C}``; every unit also pays generic.

    The payment's own cascade (``_pay_mana_cost_directly``), asked per unit:
    CR 106.6 permissions through :func:`may_pay_pip`, Chromatic Orrery's "as
    though it were mana of any color" (every unit pays a coloured pip, and
    ``{C}`` still wants colourless), Sunglasses of Urza's white-as-red.

    One reading for the two functions that plan a payment a unit at a time —
    the castable highlight's (``board_payment``, where this was written) and
    :func:`plan_payment`'s, which matched a pip to a land that *produces* its
    colour and so never asked what the seat may spend that mana as.
    """
    if as_any_type:
        return frozenset(PIP_SYMBOLS) | {"C"}
    pays: set[str] = set()
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


def _normalized(required: dict[str, int]) -> dict[str, int]:
    return {
        **{symbol: int(required.get(symbol, 0)) for symbol in COLOR_SYMBOLS},
        "generic": int(required.get("generic", 0)),
    }


def _match_colored(
    pips: Sequence[str], producers: Sequence[tuple[int, frozenset[str]]]
) -> dict[int, str] | None:
    """Assign each coloured pip a distinct land that can produce it.

    Augmenting-path bipartite matching (Kuhn's): for each pip, walk the lands
    that could pay it and either take a free one or ask whoever holds it to move.
    Exact, and it stops at the first pip it cannot place — which is the answer
    "this board cannot pay that cost", not "this search gave up".
    """
    holder: dict[int, int] = {}  # land index -> pip index

    def place(pip_index: int, seen: set[int]) -> bool:
        symbol = pips[pip_index]
        for land_index, produced in producers:
            if symbol not in produced or land_index in seen:
                continue
            seen.add(land_index)
            if land_index not in holder or place(holder[land_index], seen):
                holder[land_index] = pip_index
                return True
        return False

    for index in range(len(pips)):
        if not place(index, set()):
            return None
    return {land: pips[pip] for land, pip in holder.items()}


def _plan_under_permissions(
    pool: dict[str, int],
    lands: Sequence["Permanent"],
    want: dict[str, int],
    produced: "Sequence[frozenset[str]]",
    payer,
    wants=None,
) -> ManaPayment | None:
    """:func:`plan_payment` for a seat holding a CR 106.6 spending permission.

    With a permission in force "which land produces this pip's colour" is the
    wrong question twice over: a unit may pay a pip it is not the colour of
    (white as any colour, Celestial Dawn), and may **not** pay the pip it is
    the colour of ("other mana only as though it were colorless mana" — a
    floating {B} is no payment for a {B} pip there). So the pool is not spent
    ahead of the matching the way the ordinary path spends it; every floating
    unit and every land is one source carrying what :func:`pips_payable_by`
    says it pays, and one matching places the pips over all of them.

    Floating mana is listed first, which is the ordinary path's preference
    ("a land kept untapped is worth more than one that is not") expressed as
    the order the matching tries sources in.
    """
    units: list[str] = [
        str(symbol) for symbol, amount in pool.items()
        for _ in range(max(0, int(amount)))
    ]
    floating = len(units)
    sources: list[tuple[int, frozenset[str]]] = [
        (index, pips_payable_by(payer, frozenset({symbol})))
        for index, symbol in enumerate(units)
    ]
    sources += [
        (floating + index, pips_payable_by(payer, made) if made else frozenset())
        for index, made in enumerate(produced)
    ]
    pips = [symbol for symbol in COLOR_SYMBOLS for _ in range(want[symbol])]
    assignment = _match_colored(pips, sources) if pips else {}
    if assignment is None:
        return None

    from_pool: dict[str, int] = {}
    for index in assignment:
        if index < floating:
            from_pool[units[index]] = from_pool.get(units[index], 0) + 1
    generic = want["generic"]
    spent_floating = set(assignment)
    spare = [
        index for index, made in enumerate(produced)
        if floating + index not in assignment and made
    ]
    # Which floating units pay generic: `floating_units_for_generic`, over what
    # each may pay *as*.
    unspent = [(index, sources[index][1]) for index in range(floating) if index not in assignment]
    for index in floating_units_for_generic(
        unspent, min(generic, len(unspent)), _wants_in_force(wants),
        others=lambda: [sources[floating + index][1] for index in spare],
    ):
        from_pool[units[index]] = from_pool.get(units[index], 0) + 1
        spent_floating.add(index)
        generic -= 1
    if generic > len(spare):
        return None
    matched = {
        index - floating: pip
        for index, pip in assignment.items() if index >= floating
    }
    tapped = sorted([*matched, *spare[:max(0, generic)]])
    # Which lands pay what the floating mana did not is the sparing choice's
    # (`_sparing_choice`), over what each land's mana may pay *as*; what the
    # floating mana pays was settled above, and what it leaves is still there
    # for the payer's next want.
    chosen = _sparing_choice(
        [(index, sources[floating + index][1]) for index, made in enumerate(produced) if made],
        list(matched.values()), max(0, generic), tapped,
        [sources[index][1] for index in range(floating) if index not in spent_floating],
        _wants_in_force(wants),
    )
    if chosen is not None:
        tapped, matched = chosen
    return ManaPayment(
        from_pool=from_pool, tapped=tuple(lands[i] for i in tapped),
        # The pip is what the land's mana pays *as*; whether the land can be
        # asked for that symbol is the payer's to decide from what it makes.
        tapped_for=tuple(matched.get(i) for i in tapped),
    )


def plan_payment(
    pool: dict[str, int],
    lands: Sequence["Permanent"],
    required: dict[str, int],
    produces: "Callable[[Permanent], Sequence[str]] | None" = None,
    *,
    payer=None,
    wants=None,
    spent_first: int = 0,
    owners=None,
) -> ManaPayment | None:
    """How *required* can be paid from *pool* plus tapping *lands*, or None.

    The pool goes first for the coloured pips, because floating mana is already
    spent-in-advance and a land kept untapped is worth more than one that is
    not. Whatever colours the pool cannot cover are matched against the lands;
    the generic part is then paid by anything left over, pool before lands.

    **Which lands pay is chosen with the payer's other wants in view**
    (*wants*, `_sparing_choice`): of the sets of lands that pay this cost, the
    one leaving the most of the payer's other costs payable (together, then
    one at a time: `_wants_left`) — so a {3} on four Plains and three
    Mountains leaves two Plains when a face-down Exalted Angel wants
    {2}{W}{W}, where the lands' order alone took three Plains and stranded
    it. Whether the cost can be paid never depends on this, only which lands
    pay it; with nothing wanted, or nothing to choose between, the lands are
    the ones their order gives, as they always were. *wants* is a sequence of
    symbol dicts or a function returning one (asked only when there is a
    choice to make); left out, it is whatever ``payment_wants_in_force``
    names — the one writer of an effect-collected cost
    (``Game._pay_planned_cost``) names the payer's there. *spent_first* is how
    many of the first *lands* are mana already floating, there to be spent
    before any permanent is chosen (``ai_payment._PaymentPlanner`` hands its
    floating units in as lands); *owners*, beside *lands*, is the source each
    is a unit of where one source makes several (Sol Ring's {C}{C}).

    *produces* overrides what a land makes, for the effects that change it and
    that the permanent cannot answer alone: "Until end of turn, if you tap a
    land you control for mana, it produces {U} instead of any other type" (Deep
    Water) is a record on the *seat*, so only a caller with the game can resolve
    it (``engine/land_mana_swaps.py``). Passed in rather than looked up here for
    the reason this module takes a pool and a list instead of a game: what a
    cost can be paid from is arithmetic, and the caller owns the board. A caller
    that omits it gets the permanent's own answer, which is what every caller
    got before the override existed.

    *payer* is the seat paying (a ``PlayerState``), for what it may spend its
    mana **as** (CR 609.4b, CR 106.6): "you may spend white mana as though it
    were mana of any color" (Celestial Dawn, False Dawn), "…as though it were
    red mana" (Sunglasses of Urza), "…mana as though it were mana of any
    color" (Chromatic Orrery). The permissions are the seat's derived list, so
    this stays arithmetic — and a seat holding none takes the path below
    exactly as it always has, which is every board but the ones those cards
    are on. Without it an effect-priced coloured cost could not be paid under
    Celestial Dawn at all, where every land is a Plains and no land "produces"
    the pip.
    """
    want = _normalized(required)
    if payer is not None and getattr(payer, "mana_spending_permissions", ()):
        return _plan_under_permissions(
            pool, lands, want,
            [
                frozenset(produces(land) if produces else (land.effective_produced_mana or ()))
                for land in lands
            ],
            payer,
            wants,
        )
    from_pool: dict[str, int] = {}
    left = dict(pool)

    pips: list[str] = []
    for symbol in COLOR_SYMBOLS:
        paid = min(want[symbol], int(left.get(symbol, 0)))
        if paid:
            from_pool[symbol] = paid
            left[symbol] = int(left[symbol]) - paid
        pips.extend([symbol] * (want[symbol] - paid))

    producers = [
        (index, frozenset(produces(land) if produces else (land.effective_produced_mana or ())))
        for index, land in enumerate(lands)
    ]
    assignment = _match_colored(pips, producers) if pips else {}
    if assignment is None:
        return None

    generic = want["generic"]
    spare = [
        index
        for index, produced in producers
        if index not in assignment and produced
    ]
    # The floating mana pays generic first, as much of it as there is; which
    # of it is `floating_units_for_generic`'s, against the payer's wants and
    # with the lands no pip needs still there beside what it leaves.
    from_floating = min(generic, sum(max(0, int(amount or 0)) for amount in left.values()))
    if from_floating:
        spent = pool_spent_on_generic(
            left, from_floating, _wants_in_force(wants),
            others=lambda: [producers[index][1] for index in spare],
        )
        for symbol, paid in spent.items():
            from_pool[symbol] = from_pool.get(symbol, 0) + paid
            left[symbol] = int(left[symbol]) - paid
        generic -= from_floating
    if generic > len(spare):
        return None
    # The floating units a caller handed in as lands (*spent_first*, the AI
    # planner's) pay generic before any permanent does — which of them, the
    # same answer as the pool's.
    floating_spare = [index for index in spare if index < spent_first]
    land_spare = [index for index in spare if index >= spent_first]
    from_spent_first = min(generic, len(floating_spare))
    paying = floating_units_for_generic(
        [(index, producers[index][1]) for index in floating_spare],
        from_spent_first, _wants_in_force(wants),
        others=lambda: [
            *(frozenset({symbol}) for symbol, amount in left.items()
              for _ in range(max(0, int(amount)))),
            *(producers[index][1] for index in land_spare),
        ],
    )
    tapped = sorted([*assignment, *paying, *land_spare[:generic - from_spent_first]])
    # The floating units a caller handed in as lands (*spent_first*) pay what
    # the order gave them; which permanents pay the rest is the sparing
    # choice's, and what the pool and the unspent floating units hold is still
    # there for the payer's next want.
    fixed = [index for index in tapped if index < spent_first]
    chosen = _sparing_choice(
        [(index, produced) for index, produced in producers if produced and index >= spent_first],
        [pip for index, pip in assignment.items() if index >= spent_first],
        sum(1 for index in tapped if index >= spent_first and index not in assignment),
        [index for index in tapped if index >= spent_first],
        [
            *(frozenset({symbol}) for symbol, amount in left.items()
              for _ in range(max(0, int(amount)))),
            *(producers[index][1] for index in range(min(spent_first, len(producers)))
              if index not in tapped and producers[index][1]),
        ],
        _wants_in_force(wants),
        owners,
    )
    if chosen is not None:
        chosen_tapped, chosen_matched = chosen
        assignment = {
            **{index: pip for index, pip in assignment.items() if index < spent_first},
            **chosen_matched,
        }
        tapped = sorted([*fixed, *chosen_tapped])
    return ManaPayment(
        from_pool=from_pool, tapped=tuple(lands[i] for i in tapped),
        tapped_for=tuple(assignment.get(i) for i in tapped),
    )


# -- Which sources pay: the payer's other wants -------------------------------

#: The wants an effect-collected cost is planned against when its caller names
#: none (``Game._pay_planned_cost``, the one writer of such costs, sets it for
#: the length of a payment): a sequence of symbol dicts, or a function
#: returning one.
_WANTS_IN_FORCE: ContextVar = ContextVar("payment_wants_in_force", default=None)


@contextmanager
def payment_wants_in_force(wants):
    """Run a block in which every :func:`plan_payment` that names no *wants*
    plans against these.

    A context rather than a parameter for ``ai_payment._PAYING_FOR``'s reason:
    the plans an effect-collected cost is paid by are drawn up by eight
    callers' own thunks (an upkeep price, a toll, a counterspell's "unless",
    an optional offer, a special action …), each also asked "can this be
    paid?" where the answer cannot depend on it, and handed to one writer
    (``Game._pay_planned_cost``) — which is the one place that knows a payment
    is being made, and so the one place that names what the payer still
    wants.
    """
    token = _WANTS_IN_FORCE.set(wants)
    try:
        yield
    finally:
        _WANTS_IN_FORCE.reset(token)


def _wants_in_force(wants):
    return _WANTS_IN_FORCE.get() if wants is None else wants


#: The most ways of choosing which sources pay that are weighed one by one.
#: Past it the order the sources were handed in decides, as it always did.
_MAX_SPARING_CHOICES = 512


def _sparing_choice(candidates, pips, generic, base, left, wants, owners=None):
    """``(tapped, matched)`` — the sources to tap instead of *base* and the pip
    each pays — or None to tap *base*.

    **The one preference every payment planner shares**: of the sets of
    sources that pay a cost, the one that leaves the payer the most of what
    else it wants to pay for. Paying in the order the sources are listed is
    blind to that: a {3} on four Plains and three Mountains took three Plains
    and stranded Exalted Angel's {2}{W}{W} turn-up; Astral Slide's {2}{W} on
    Plains, Mountain, Plains, Mountain, Plains, Plains took a Mountain and
    stranded Solar Blast's cycling {1}{R}{R} (Onslaught's Phase 5). Asked by
    :func:`plan_payment` — the matching the AI's payment plan, the web's
    auto-tap and every effect-collected cost go through — after it has found
    *a* payment, so whether a cost can be paid never depends on it.

    *candidates* is ``(index, pays)`` for every unit of mana the choice may
    spend, in the caller's order: *pays* is the set of pips it may pay (every
    candidate also pays generic). The chosen units must pay *pips* and
    *generic*. *left* is mana that stays available whatever is chosen
    (floating mana the payment does not spend), one pays-set per unit.
    *wants* is the payer's other costs — a `PaymentWants`, a sequence of
    symbol dicts, or a function returning either. *owners*, where a source makes more than one unit (Sol Ring's
    {C}{C}), maps an index to the source it is a unit of: a source part-spent
    is tapped all the same, so its other units are not counted as left for a
    want (they float only until the step ends, CR 106.4), and of two equally
    good choices the one tapping fewer sources is taken.

    Exact over **kinds** of unit: two Mountains are interchangeable, so a
    choice is how many of each kind it spends — the first that many of the
    kind, in the caller's order. Each choice is scored by what the rest still
    pays (`_wants_left`: the most wants together, the most of them cards, then
    the most one at a time; a want repeated in hand counts each time); *base*
    — the caller's own choice — is kept unless another scores higher, so a board
    with no competing want pays exactly as it did, and ties go to the choice
    tapping the fewest sources, then to the one whose units come first in the
    caller's order. Nothing is asked of the wants where there is nothing to
    choose: one kind of unit, or every candidate needed.
    """
    owed = len(pips) + generic
    if not owed or owed >= len(candidates) or not wants:
        return None
    kinds: dict[frozenset, list[int]] = {}
    for index, pays in candidates:
        kinds.setdefault(frozenset(pays), []).append(index)
    if len(kinds) < 2:
        return None
    named: dict = {}
    owner_of = tuple(
        named.setdefault(
            owners[index] if owners is not None and owners[index] is not None
            else ("unit", index),
            len(named),
        )
        for index, _pays in candidates
    )
    if callable(wants):
        wants = wants()
    counted = _counted_wants(wants, generic_too=len(named) < len(candidates))
    if not counted:
        return None
    order = tuple(kinds)
    position_of = {index: position for position, (index, _pays) in enumerate(candidates)}
    # The candidates by kind, as positions in the caller's order, and whose
    # unit each is: the board as the scoring sees it, with no index in it.
    of_kind = tuple(tuple(position_of[index] for index in kinds[kind]) for kind in order)
    scores = _choice_scores(
        order, of_kind, owner_of, tuple(sorted(pips)), generic,
        tuple(sorted(left, key=sorted)), counted,
    )
    if not scores:
        return None
    kind_of = {index: position for position, kind in enumerate(order) for index in kinds[kind]}
    taken = [0] * len(order)
    for index in base:
        if index in kind_of:
            taken[kind_of[index]] += 1
    best = max(score for score, _sources in scores.values())
    if tuple(taken) in scores and scores[tuple(taken)][0] >= best:
        return None
    _sources, positions = min(
        (sources, _realized(of_kind, choice))
        for choice, (score, sources) in scores.items() if score == best
    )
    chosen = [candidates[position][0] for position in positions]
    pays_of = dict(candidates)
    matched = _match_colored(list(pips), [(index, pays_of[index]) for index in chosen]) if pips else {}
    if matched is None:
        return None
    return chosen, matched


# -- Which floating mana pays generic -----------------------------------------

#: The order floating mana is offered in to pay generic where nothing else
#: decides: colourless first, the unit that pays no coloured pip, then the
#: colours in WUBRG order.
FLOATING_GENERIC_ORDER: tuple[str, ...] = ("C", *PIP_SYMBOLS)


def floating_units_for_generic(candidates, amount: int, wants, *, others=()) -> list:
    """Which *amount* of the floating units *candidates* pay generic mana:
    their indices.

    **The pool's half of the preference every planner shares**
    (`_sparing_choice`). The lands a payment taps have been chosen to spare
    the payer's other wants since round kg2, and the mana already floating
    was spent in a fixed order, a different one in each of three places: the
    cast path's spend took C, W, U, B, R, G, so a floating {C} paid a {1}
    beside a {C} still wanted; :func:`plan_payment` took the pool dict's own
    order, colourless last, so turning Liege of the Axe face up for {1}{W}
    from {W:3, G:4, C:7} spent {W}{W} and left Defender of the Order's
    {W}{W} unpayable with seven colourless floating (LGN Phase 5); and the
    AI planner's floating units paid "what the order gave them". One answer
    now, asked by all three.

    *candidates* is ``(index, pays)`` per floating unit — *pays* the pips it
    may pay (`pips_payable_by`) — in the order preferred where the wants do
    not decide: a unit paying no coloured pip first (:data:`FLOATING_GENERIC_ORDER`).
    *wants* is the payer's other costs (a `PaymentWants`, a sequence of symbol
    dicts, a function returning either, or None); *others* is what stays
    available whatever is chosen — the untapped lands, one pays-set each — or
    a function returning it, asked only when there is a choice to make.
    """
    ordered = sorted(
        candidates,
        key=lambda candidate: bool(set(candidate[1]) & set(PIP_SYMBOLS)),
    )
    amount = max(0, min(int(amount), len(ordered)))
    base = [index for index, _pays in ordered[:amount]]
    if not amount or amount >= len(ordered) or not wants:
        return base
    if len({frozenset(pays) for _index, pays in ordered}) < 2:
        return base
    chosen = _sparing_choice(
        ordered, [], amount, base, list(others() if callable(others) else others), wants,
    )
    return base if chosen is None else list(chosen[0])


def pool_spent_on_generic(pool, amount: int, wants, *, others=(), pays_of=None) -> dict:
    """``{symbol: units}`` — which of the mana in *pool* (a symbol dict) pays
    *amount* generic, by :func:`floating_units_for_generic`. *pays_of* is a
    unit's pips by its symbol (a payer's CR 106.6 permissions,
    `pips_payable_by`); left out, a unit pays its own symbol."""
    units = [
        symbol for symbol in FLOATING_GENERIC_ORDER
        for _ in range(max(0, int(pool.get(symbol, 0) or 0)))
    ]
    chosen = floating_units_for_generic(
        [
            (index, frozenset({symbol}) if pays_of is None else pays_of(symbol))
            for index, symbol in enumerate(units)
        ],
        amount, wants, others=others,
    )
    spent: dict[str, int] = {}
    for index in chosen:
        spent[units[index]] = spent.get(units[index], 0) + 1
    return spent


@dataclass(frozen=True)
class PaymentWants:
    """What a payer may still want to pay for, as symbol dicts, in two tiers
    (``mana_wants.mana_wants`` builds it).

    ``cards`` is what a card the payer holds back costs — a spell in hand, an
    ability that works from the hand, a face-down permanent's turn-up: a card
    that does nothing until it is paid for. ``abilities`` is the activated
    abilities of permanents already in play, which can wait. Where two
    choices keep as many wants payable together, the one keeping more of the
    first tier wins (`_wants_left`). A plain sequence of symbol dicts is all
    ``cards``.
    """

    cards: tuple = ()
    abilities: tuple = ()


def _realized(of_kind, choice) -> "tuple[int, ...]":
    """The candidate positions a *choice* (a count per kind) spends: the first
    that many of each kind, in the caller's order."""
    return tuple(sorted(
        position for kind, count in enumerate(choice) for position in of_kind[kind][:count]
    ))


def _counted_wants(wants, *, generic_too: bool) -> "tuple[tuple[tuple[tuple[str, int], ...], int, int], ...]":
    """*wants* (a `PaymentWants` or a sequence of symbol dicts) as ``((cost
    items, times, tier), …)`` — the cards' tier (0) before the abilities'
    (1), each in the order listed (first appearance), each cost a sorted
    tuple of its non-zero symbols. A want of generic mana alone is dropped
    unless
    *generic_too* (some source makes more than one unit): with one unit a
    source every choice taps as many sources, so such a want is payable after
    all of them or none — but a choice that part-spends a Sol Ring taps one
    more source than the choice that spends both its units.
    """
    if isinstance(wants, PaymentWants):
        tiers = (wants.cards, wants.abilities)
    else:
        tiers = (tuple(wants or ()), ())
    times: dict[tuple, int] = {}
    for tier, listed in enumerate(tiers):
        for want in listed:
            items = tuple(sorted(
                (str(symbol), int(amount)) for symbol, amount in (want or {}).items()
                if int(amount or 0) > 0
            ))
            if not items or not generic_too and not any(
                symbol != "generic" for symbol, _amount in items
            ):
                continue
            times[(items, tier)] = times.get((items, tier), 0) + 1
    return tuple((items, count, tier) for (items, tier), count in times.items())


@lru_cache(maxsize=8192)
def _choice_scores(order, of_kind, owner_of, pips, generic, left, wants):
    """``{choice: (score, sources tapped)}`` for every way of spending
    ``len(pips) + generic`` units of the kinds *order* that pays *pips* — a
    choice is a count per kind (``of_kind[k]`` lists kind *k*'s candidate
    positions, ``owner_of[p]`` the source position *p* is a unit of), its
    score what the untouched sources and *left* still pay of *wants*
    (`_wants_left`).
    Empty past ``_MAX_SPARING_CHOICES``.

    A pure function of what a board holds and what is asked of it, so a board
    planned again (every rehearsal of every candidate cast plans the same
    lands) is answered from the cache.
    """
    owed = len(pips) + generic
    caps = tuple(len(positions) for positions in of_kind)
    kind_at = {position: kind for kind, positions in enumerate(of_kind) for position in positions}
    choices: list[tuple[int, ...]] = []

    def extend(kind: int, remaining: int, prefix: tuple[int, ...]) -> bool:
        if kind == len(order) - 1:
            if remaining <= caps[kind]:
                choices.append((*prefix, remaining))
            return len(choices) <= _MAX_SPARING_CHOICES
        for count in range(min(remaining, caps[kind]), -1, -1):
            if not extend(kind + 1, remaining - count, (*prefix, count)):
                return False
        return True

    if not extend(0, owed, ()):
        return {}
    asked = [(dict(items), times, tier) for items, times, tier in wants]
    scores: dict[tuple[int, ...], tuple] = {}
    for choice in choices:
        spending = [order[kind] for kind, count in enumerate(choice) for _ in range(count)]
        if pips and _match_colored(list(pips), list(enumerate(spending))) is None:
            continue
        spent = _realized(of_kind, choice)
        touched = {owner_of[position] for position in spent}
        rest = [
            *left,
            *(order[kind_at[position]] for position in range(len(owner_of))
              if owner_of[position] not in touched),
        ]
        scores[choice] = (_wants_left(rest, asked), len(touched))
    return scores


def _wants_left(rest: "list[frozenset[str]]", wants) -> tuple:
    """How well *rest* serves *wants* (``(want, times, tier)``, cards before
    abilities), as a key that sorts better-is-larger: how many it pays
    **together** — taken in the order listed, each kept if it still fits
    beside those before it — then how many of those are the cards' tier
    (`PaymentWants`), then how many it pays one at a time.

    Together first, because a turn is several payments. Scored one at a
    time, the seeded M21 game paid Walking Corpse with both Swamps off
    Mountain, Swamp, Swamp and a Dismal Backwater: Mountain and the dual
    leave Archfiend's Vessel ({B}), Liliana's Steward ({B}) and Heartfire
    Immolator's "{R}, Sacrifice" each payable alone, where a Swamp and the
    dual leave only the two one-drops — and the AI cast one spell fewer. The
    cards' tier second, for the same game: either way two wants fit
    together, and two one-drops in hand beat a one-drop and an ability that
    can wait. Nothing finer: two cards in hand are not ranked against each
    other, so where they tie the caller's own choice stands.
    """
    together: dict[str, int] = {}
    packed = cards = 0
    for want, times, tier in wants:
        for _ in range(times):
            trial = dict(together)
            for symbol, amount in want.items():
                trial[symbol] = trial.get(symbol, 0) + amount
            if _units_pay(rest, trial):
                together = trial
                packed += 1
                cards += 1 if tier == 0 else 0
    alone = sum(times for want, times, _tier in wants if _units_pay(rest, want))
    return (packed, cards, alone)


def _units_pay(units: "list[frozenset[str]]", want: dict[str, int]) -> bool:
    """Whether *units* — one pays-set per mana, each also good for generic —
    pay *want*: its pips matched exactly (:func:`_match_colored`), its generic
    from what the pips leave."""
    pips = [symbol for symbol in COLOR_SYMBOLS for _ in range(int(want.get(symbol, 0)))]
    if len(units) < len(pips) + int(want.get("generic", 0)):
        return False
    return not pips or _match_colored(pips, list(enumerate(units))) is not None


#: Instruction kinds that put mana into a pool. CR 605.1a's "could add mana to
#: a player's mana pool" is a question about what the ability *does*, so it is
#: asked of the compiled program rather than of the printed words — a land that
#: says "add {G}" and one that says "add one mana of any color" are the same
#: kind of ability and neither spells the test out.
MANA_PRODUCING_KINDS: frozenset[str] = frozenset({
    "add_mana_from_text",
    "sacrifice_creature_for_mana",
    "sacrifice_self_for_mana",
    "channel_life_for_mana",
})

#: Costs that move a card to or from a library, as fields of
#: ``ActivatedAbilityCost`` - each a count, zero for "no such cost". CR 605.1a's
#: fourth criterion (in the rules since the September 2026 edition): an
#: activated ability is a mana ability only if "its cost and effect don't move
#: any card to or from a library". Milling (Millikin, Charmed Pendant) and
#: exiling the top of a library move one *from* it; a card put from a hand on
#: top moves one *to* it, and so do cards put from a graveyard on the bottom
#: (Battlefield Scrounger).
LIBRARY_MOVING_COSTS: tuple[str, ...] = (
    "mill_cards", "exile_top_of_library", "hand_to_library_top",
    "graveyard_to_library_bottom",
)

#: The effect half of the same criterion, asked **the other way round**. Every
#: effect that moves a card between zones lowers into one grammar category
#: (:data:`_ZONE_MOVING_CATEGORY`, 166 kinds), and a step of that category
#: beside an add-mana step is *presumed* to move a card to or from a library
#: unless it is one of these - the zone-moving steps the pool's mana abilities
#: carry that have been read and do not:
#:
#: * ``sacrifice_self`` - battlefield to graveyard (Gemstone Mine and the five
#:   storage lands sacrifice themselves when the last counter is gone);
#: * ``return_self_instead_of_untapping`` - battlefield to hand, later
#:   (Undiscovered Paradise);
#: * ``reveal_cards_from_hand`` - nothing moves (Metalworker).
#:
#: Presumed, because the two ways of being wrong are not alike. A mana ability
#: read as an ordinary one still works, through the stack; an ordinary ability
#: read as a mana ability can be activated in the middle of a payment and
#: cannot be responded to, which is the card doing more than it prints with
#: nothing to show for it. A draw is the step the pool actually carries ("Add
#: one mana of any color. **Draw a card.**" - Chromatic Sphere, Odyssey's five
#: Eggs), and a set collected off the pool would have held that one kind and
#: called "{T}: Add {G}. Mill a card." a mana ability the day it was printed.
#: ``tests/engine/test_mana_ability_library_criterion.py`` holds every such
#: step in either manifest role to a reviewed verdict, so an entry is added
#: here by reading a card, never by default.
LIBRARY_SAFE_ZONE_KINDS: frozenset[str] = frozenset({
    "sacrifice_self",
    "return_self_instead_of_untapping",
    "reveal_cards_from_hand",
})

#: The grammar category of an effect that moves a card between zones
#: (``lowering/categories.INSTRUCTION_CATEGORIES``).
_ZONE_MOVING_CATEGORY = "zones"

#: A step that sets up a **later** ability rather than doing its work now. CR
#: 603.7: "An effect may create a delayed triggered ability that can do
#: something at a later time" - the delayed ability is another ability, with its
#: own resolution, and what *it* moves is not moved by the cost or the effect of
#: the ability that created it. So "Add one mana of any color. Draw a card at
#: the beginning of the next turn's upkeep." (Barbed Sextant, Astrolabe) is a
#: mana ability and "Add one mana of any color. Draw a card." (Chromatic Sphere)
#: is not. No ruling says so of the Sextant by name; the Sphere's, Millikin's
#: and Selvala's (all 2026-08-05) are each about a card moved as the ability is
#: activated or resolves, and the mischief the criterion answers - a card drawn
#: or revealed in the middle of paying for something - is one a draw at the next
#: upkeep cannot do.
_LATER_ABILITY_KINDS: frozenset[str] = frozenset({"create_delayed_trigger"})


def has_nonmana_activated_ability(card) -> bool:
    """Whether *card* has an activated ability that isn't a mana ability
    (CR 602.1, CR 605.1a) — "each land with an activated ability that isn't a
    mana ability" (Tsabo's Web).

    Asked of the **compiled program**, which is where a keyword that is an
    activated ability has already been written out as one: cycling is
    CR 702.29a's "[cost], Discard this card: Draw a card", so a cycling land
    answers yes although the ability never functions on the battlefield — the
    rule asks what the object *has*, not what it could activate right now.
    A basic land's intrinsic mana ability (CR 305.6) is no activated ability
    the program carries and would be a mana ability if it were, so a Forest
    answers no either way.

    Pass a permanent's ``effective_card``, never its printed one: an ability
    gained or lost since it entered counts as it is now.
    """
    from .oracle import compile_card_oracle

    return any(
        not is_mana_ability(ability)
        for ability in compile_card_oracle(card).activated_abilities
    )


def _intrinsic_land_mana_ability():
    from .oracle_types import (ActivatedAbilityCost, OracleInstruction,
                               ParsedActivatedAbility)

    return ParsedActivatedAbility(
        source_line="",
        normalized_effect="",
        supported=True,
        cost=ActivatedAbilityCost(mana={}, requires_tap=True),
        effect_kind="activated_mana",
        instruction=OracleInstruction("add_mana_from_text", "", {}),
    )


#: CR 305.6's "{T}: Add [mana symbol]" — the mana ability a basic land type
#: gives a land, which no text carries and so no compiled program holds. A
#: question asked *of an ability* (CR 602.5's prohibitions: "can't be
#: activated", "unless they're mana abilities", "with {T} in their costs") has
#: to be handed one, and a Forest has nothing else to hand: this is that
#: ability as the rules define it — a {T} cost, no other, an effect that adds
#: mana and targets nothing, and no printed line for a clause to sit on. What
#: it adds is not here (the land's summary and its types say that); it is the
#: answer to what kind of ability tapping the land activates.
INTRINSIC_LAND_MANA_ABILITY = _intrinsic_land_mana_ability()


def is_mana_ability(ability) -> bool:
    """Whether *ability* is a mana ability (CR 605.1a).

    Three clauses, and only two of them can be answered here. It must be able to
    add mana, which the instruction kind says; it must not target, which the
    payload says. The third — "not a loyalty ability" — is a property of the
    cost, and a loyalty ability never produces mana in this pool, so asking the
    kind answers it too.

    Its own function because two callers need the same answer and the harder one
    is a *restriction*: "activated abilities can't be activated unless they're
    mana abilities" (Faith's Fetters) is a rule about this predicate, and a
    second reading of it would shut off an ability the rules leave open — or,
    worse, leave one open that should be shut.

    **It takes an ability or a bare instruction, and it used to take only one.**
    ``getattr(ability, "instruction", None)`` is None for an ``OracleInstruction``,
    so the four call sites in ``ai_policy``/``ai_valuation`` that pass one — every
    caller on the AI side — got False for every mana ability there is. Nothing
    raised and nothing was missing; the AI simply never recognised a mana ability
    through those paths.

    **And "could add mana when it resolves" is asked of the whole effect, not of
    its first step.** "{T}: Add {W} or {U}. This land deals 1 damage to you"
    (Adarkar Wastes and the four other Ice Age painlands) and "{T}: Add {U} or
    {B}. Put a depletion counter on this land" (the five depletion lands) lower
    to a ``sequence``, whose kind is not in :data:`MANA_PRODUCING_KINDS` — so
    twelve shipped cards answered False here. That is CR 605.1a read backwards:
    the rule asks whether the ability *could* add mana, and a two-step effect
    whose first step does is a mana ability with a drawback, which is the whole
    design of both cycles. The consequence was silent in the direction that does
    more work — they used the stack (CR 605.3a says they must not), Imprison's
    "a {T} ability that isn't a mana ability" would have fired on them, and an
    effect shutting off everything but mana abilities shut them off too.

    The no-target clause is asked of every step for the same reason: a sentence
    that adds mana and then targets something is not a mana ability, and asking
    only the outer instruction would have admitted it.

    **And "doesn't require a target" is not the same question as "carries a
    ``targets`` payload"** (CR 605.5a). That key is how a lowering spells a
    targeted *object*; a targeted **player** is spelled as a payload value out
    of the lowering's own reference vocabulary — ``"target"``,
    ``"target_player"``, ``"target_opponent"`` — on whatever key the effect
    happens to use. Witch Engine's "Target opponent gains control of this
    creature" arrives as ``{"who": "target_opponent"}`` and so read as a mana
    ability, which is the one card in the pool that is famously *not* one for
    exactly this reason. Asked by value at any depth rather than by naming the
    keys, because the key is the effect's business and the word is the rule's.

    **The loyalty clause is real, and it is the third one this function used to
    say it could skip.** The docstring above claimed "a loyalty ability never
    produces mana in this pool, so asking the kind answers it too" — measurably
    false: Chandra, Heart of Fire's "−9: … Add six {R}" is shipped, and it read
    as a mana ability. A loyalty cost is a property of the **cost**, so it can
    only be answered when this is handed an ability; given a bare
    ``OracleInstruction`` there is no cost to read and the caller gets the
    other two clauses alone. That is the honest answer rather than a silent
    one — the four AI call sites pass a bare instruction and no planeswalker
    reaches them.

    **And an ability that moves a card to or from a library is not a mana
    ability** — the fourth criterion, which CR 605.1a has carried since the
    September 2026 edition: "…and its cost and effect don't move any card to
    or from a library." It first reached this function as a *ruling* (Millikin,
    2026-08-05: "not a mana ability. Players can respond to it, and it can't be
    activated in the middle of paying for a cost"), while the rules file this
    repo shipped was the April edition, and was held to the one cost that
    ruling was written about. Both halves are asked now:

    * the **cost** (:data:`LIBRARY_MOVING_COSTS`) — a mill, the top of a
      library exiled, a card put on top of one. A property of the cost, like
      the loyalty clause, so a caller holding a bare instruction is not told;
    * the **effect** (:func:`moves_a_library_card`) — "Add one mana of any
      color. Draw a card." (Chromatic Sphere, the five Eggs). Asked of the
      steps the ability carries out *as it resolves*: a delayed ability it
      sets up is another ability (:data:`_LATER_ABILITY_KINDS`, with the
      reasoning), so Barbed Sextant's draw at the next upkeep leaves its mana
      ability one. And asked fail-closed: a zone-moving step that nobody has
      read is presumed to reach a library (:data:`LIBRARY_SAFE_ZONE_KINDS`).

    It is those cards' printed reminder text made true: an ability that uses
    the stack is activated whenever its controller has priority, which is
    "only as an instant". The rule's last sentence — "Do not take into account
    replacement effects that may apply, other than self-replacement effects" —
    is why this reads the compiled ability and never the board: a mana ability
    whose draw something would replace is still not a mana ability, and one
    that a replacement would *make* draw still is.
    """
    instruction = getattr(ability, "instruction", ability)
    if instruction is None or not hasattr(instruction, "kind"):
        return False
    cost = getattr(ability, "cost", None)
    if getattr(cost, "loyalty", None) is not None:
        return False
    if any(getattr(cost, field, 0) for field in LIBRARY_MOVING_COSTS):
        return False
    steps = (instruction, *_every_nested_step(instruction))
    if not any(step.kind in MANA_PRODUCING_KINDS for step in steps):
        return False
    if moves_a_library_card(instruction):
        return False
    return not any(
        (step.payload or {}).get("targets") or _names_a_target(step.payload)
        for step in steps
    )


def moves_a_library_card(instruction) -> bool:
    """Whether resolving *instruction* moves a card to or from a library, as
    far as CR 605.1a's fourth criterion is concerned: any step it carries out
    now (:func:`steps_carried_out_now`) that moves a card between zones and is
    not one of :data:`LIBRARY_SAFE_ZONE_KINDS`."""
    from .grammar.lowering.categories import INSTRUCTION_CATEGORIES

    return any(
        INSTRUCTION_CATEGORIES.get(step.kind) == _ZONE_MOVING_CATEGORY
        and step.kind not in LIBRARY_SAFE_ZONE_KINDS
        for step in steps_carried_out_now(instruction)
    )


def steps_carried_out_now(instruction) -> tuple:
    """*instruction* and every step inside it that happens as it resolves —
    :func:`_every_nested_step` that does not open a step which only sets up a
    later ability (:data:`_LATER_ABILITY_KINDS`).

    The walk CR 605.1a's fourth criterion needs and the first three do not:
    "could add mana" and "doesn't require a target" are true of an ability
    whatever part of it says so, while "its … effect [doesn't] move any card to
    or from a library" is about what this ability's own resolution does.
    """
    if instruction is None or not hasattr(instruction, "kind"):
        return ()
    found = [instruction]
    if instruction.kind in _LATER_ABILITY_KINDS:
        return tuple(found)
    from .grammar.lower import nested_instructions, offer_branches

    inner = nested_instructions(instruction)
    if inner is None:
        inner = offer_branches(instruction)
    for step in inner or ():
        found.extend(steps_carried_out_now(step))
    return tuple(found)


def carries_an_offer(instruction) -> bool:
    """Whether any step of *instruction* asks a player something — an offer
    (``may``) or a toll (``unless_player_pays``).

    A mana ability may (CR 605.1a is silent on it): "Add one mana of that color
    **unless any player pays {1}**" (Rhystic Cave). What such an ability cannot
    be is run by a path that has to finish before it returns — the tap seam,
    part-way through a payment — because the mana does not exist until every
    seat it asks has answered.
    """
    from .grammar.lower import OFFER_BRANCH_KEYS

    if instruction is None or not hasattr(instruction, "kind"):
        return False
    return any(
        step.kind in OFFER_BRANCH_KEYS
        for step in (instruction, *_every_nested_step(instruction))
    )


#: How a lowering spells "this names a target" as a payload **value**, at any
#: depth. Collected off the pool rather than invented: these three are the only
#: ``target``-prefixed strings any compiled payload in either manifest role
#: holds as a value, and every one of them is CR 115's word.
_TARGET_REFERENCE_WORDS: frozenset[str] = frozenset({
    "target", "target_player", "target_opponent",
})


def _names_a_target(value) -> bool:
    """Whether *value* holds one of :data:`_TARGET_REFERENCE_WORDS` anywhere.

    Values only — a payload **key** named ``targets_filter`` or ``target_color``
    describes a target the sentence has already announced elsewhere or a colour
    the effect asks about, and reading keys would make every "change the colour
    of target permanent" rider answer this question twice.
    """
    if isinstance(value, str):
        return value in _TARGET_REFERENCE_WORDS
    if isinstance(value, dict):
        return any(_names_a_target(inner) for inner in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_names_a_target(inner) for inner in value)
    return False


def _every_nested_step(instruction) -> tuple:
    """Every instruction inside *instruction*, at any depth.

    Through the grammar's own reader of what a control-flow instruction
    contains, so "which keys hold steps" has one answer here: a branch key
    added there and not here would be an effect this predicate cannot see into.

    Named apart from ``instruction_targets._nested_steps`` on purpose. That one walks a
    single level off a *third* copy of the step-key table
    (``instruction_targets._WRAPPER_STEP_KEYS``), and this one walks all of them off the
    grammar's; sharing the name would be one word for two facts, which is the
    shape ``_per_recipient_count`` was recorded under in SET_PLAYBOOK's Known
    gaps until VIS wave 4 split it into ``_amounts._recipient_seat_count`` and
    ``_sweeps._per_recipient_multiplier``. That the two tables exist at all is
    the real debt, and it belongs to whoever next needs a third reader.
    """
    # `grammar.lower` rather than `lowering.categories` or
    # `lowering.control_flow`: the walk has lived in both, and each move took
    # the old address with it. The name has one home and this is it.
    from .grammar.lower import nested_instructions, offer_branches

    inner = nested_instructions(instruction)
    # **And an offer's branches**, which the category walk must not open and
    # this one must. "Add one mana of that color **unless any player pays
    # {1}**" (Rhystic Cave) puts the whole of its mana behind a toll, and CR
    # 605.1a asks whether the ability *could* add mana — it could, and
    # "regardless of … timing restrictions (such as 'Activate only as an
    # instant')" (CR 605.1) it is a mana ability. Opening the two offer kinds
    # moved no compiled ability's answer in either manifest role but the Cave's.
    if inner is None:
        inner = offer_branches(instruction)
    if not inner:
        return ()
    found: list = []
    for step in inner:
        found.append(step)
        found.extend(_every_nested_step(step))
    return tuple(found)


def generic_cost(amount: int) -> dict[str, int]:
    """A cost of ``{N}`` in the one shape a payment reads.

    Named rather than written out at each call site because that is where the
    two shapes met: the optional-pay prompt used to carry its cost as a bare
    number, so every effect that arms one had a number to hand over. A number is
    still what those effects have — a hook event's ``{2}``, an instruction's
    ``cost`` payload — and this is the one line that says which cost it is.
    """
    return {"generic": max(0, int(amount))}


def mana_cost_from_symbols(printed: str) -> dict[str, int] | None:
    """``{1}{B}`` as the symbol dict a payment reads — the inverse of
    :func:`mana_cost_label` — or None when a symbol is one this cannot spend.

    Here rather than beside the reader that wants it, for the reason
    :func:`generic_cost` is here: a cost is a symbol dict *everywhere*, and a
    second place that turns printed symbols into one is a second answer to the
    question of what "{1}" costs. The grammar has its own reader because it
    works from a token stream; this is for the derivation tables, which hold the
    printed run as a captured string.

    A hybrid, Phyrexian or ``{X}`` symbol returns None rather than an
    approximation. A restriction whose cost this cannot express must refuse its
    line — a cost read as smaller than it is charges a player less than the card
    says, and one read as zero charges nothing at all.
    """
    counts: dict[str, int] = {}
    for symbol in _PRINTED_SYMBOL.findall(printed or ""):
        upper = symbol.upper()
        if upper.isdigit():
            counts["generic"] = counts.get("generic", 0) + int(upper)
        elif upper in COLOR_SYMBOLS:
            counts[upper] = counts.get(upper, 0) + 1
        else:
            return None
    return counts or None


#: One printed mana symbol. Deliberately permissive about *what* is inside the
#: braces so an unspendable one reaches the check above and refuses, rather than
#: failing to match and being silently dropped from the cost.
_PRINTED_SYMBOL = re.compile(r"\{([^}]+)\}")


def permanent_mana_cost(permanent) -> dict[str, int] | None:
    """The mana cost of *permanent* as a payable symbol dict, or None when it
    has none.

    "…unless you pay **its mana cost**." Read off ``effective_card``, so a
    Clone costs what it copied (CR 707.2) and a token that is not a copy has no
    mana cost at all (CR 202.1b). **None is "unpayable", not "free"** —
    CR 118.6 — and the two must not be confused: ``{0}`` (Ornithopter) is a
    mana cost and comes back as an empty requirement any player can meet, while
    a land's missing cost comes back None and may not be paid.

    ``{X}`` is 0 anywhere but the stack (CR 107.3g, CR 107.3h), so it is
    dropped rather than refused. A symbol this engine cannot spend — hybrid,
    Phyrexian — is None for :func:`mana_cost_from_symbols`' reason: a cost read
    as smaller than it is charges less than the card says, and refusing the
    payment is the conservative answer.
    """
    return mana_cost_x_as_zero(permanent.effective_card.mana_cost or "")


def mana_cost_x_as_zero(printed: str) -> dict[str, int] | None:
    """A printed mana cost off the stack (CR 107.3g): :func:`permanent_mana_cost`'s
    reading of a card's cost string — None for no symbols or one this cannot
    spend, ``{}`` for a cost of {0} or {X} alone, each ``{X}`` dropped."""
    symbols = _PRINTED_SYMBOL.findall(printed or "")
    if not symbols:
        return None
    spendable = "".join(
        "{" + symbol + "}" for symbol in symbols if symbol.upper() != "X"
    )
    if not spendable:
        return {}
    cost = mana_cost_from_symbols(spendable)
    if cost is None:
        return None
    return {symbol: amount for symbol, amount in cost.items() if amount}


def spell_mana_cost(item) -> dict[str, int] | None:
    """The mana cost of the spell *item* (a stack object) as a payable symbol
    dict, or None when it has none.

    "…may pay **that spell's mana cost**." (Ice Cave.) :func:`permanent_mana_cost`
    one zone over, and the zone is the whole difference: CR 107.3h — "if an
    effect instructs a player to pay an object's mana cost that includes {X},
    the value of X is treated as 0 unless the object is a spell on the stack.
    In that case, the value of X is the value chosen or determined for it as
    the spell was cast." So each ``{X}`` is that many generic mana here, where
    the permanent reader drops it.

    The **printed** cost, coloured symbols and all (CR 202.1a — "mana cost
    includes color", as the card's own reminder says): never what was actually
    paid, so a cost increase, a reduction or an alternative cost changes
    nothing (the card's ruling: "the mana cost does not include cost increases
    or reductions").

    **None is "unpayable", not "free"** (CR 118.6, CR 202.1b), for
    :func:`permanent_mana_cost`'s reason: ``{0}`` is a mana cost and comes back
    as an empty requirement any player can meet, while a spell with no mana
    cost comes back None and may not be paid for at all. A symbol this engine
    cannot spend — hybrid, Phyrexian — is None too: refusing the payment is the
    conservative answer to a cost it would otherwise under-charge.

    The card is the stack item's own, so a split card's cost is the cast
    half's (CR 709.3b) with no branch here.
    """
    card = getattr(item, "card", None)
    symbols = _PRINTED_SYMBOL.findall(getattr(card, "mana_cost", "") or "")
    if not symbols:
        return None
    announced = max(0, int(getattr(item, "x_value", 0) or 0))
    spendable = "".join(
        "{" + symbol + "}" for symbol in symbols if symbol.upper() != "X"
    )
    cost: dict[str, int] = {}
    if spendable:
        printed = mana_cost_from_symbols(spendable)
        if printed is None:
            return None
        cost = dict(printed)
    variable = sum(1 for symbol in symbols if symbol.upper() == "X")
    if variable:
        cost["generic"] = int(cost.get("generic", 0)) + variable * announced
    return {symbol: amount for symbol, amount in cost.items() if amount}


def total_pips(required: dict[str, int]) -> int:
    """How many mana the cost is, all told — for a log line or a prompt label,
    never for deciding whether it can be paid."""
    want = _normalized(required)
    return sum(want.values())


def mana_cost_label(required: dict[str, int]) -> str:
    """The cost written the way a card prints it: ``{1}{B}``.

    The generic part first and then the coloured pips in WUBRGC order, which is
    Magic's own convention — the prompt a player reads should look like the line
    they read it on.
    """
    want = _normalized(required)
    parts = [f"{{{want['generic']}}}"] if want["generic"] else []
    parts += [f"{{{symbol}}}" * want[symbol] for symbol in COLOR_SYMBOLS if want[symbol]]
    return "".join(parts) or "{0}"


def untapped_mana_lands(permanents: Iterable["Permanent"]) -> list["Permanent"]:
    """The permanents a payment may tap: untapped lands that make mana.

    Lands only, and that is a real limitation rather than a simplification of
    one — a mana artifact's ability is an activated ability the player would
    have to activate, and this payment happens with no priority window in which
    to do it. It matches what the generic-only payer this replaces did.
    """
    return [
        perm
        for perm in permanents
        if perm.has_type("land")
        and not perm.tapped
        and perm.effective_produced_mana
        and taps_for_payment(perm)
    ]


def taps_for_payment(land) -> bool:
    """Whether tapping *land* for mana part-way through a payment makes mana.

    The tap seam's own answer (``Game.tap_land_for_mana``), asked by every
    reader that counts a land as mana it can spend — the payment planner's land
    list above and the AI's tap plan — so a land the seam refuses is never
    counted as one it would tap. The seam runs a land's tap-alone mana ability
    (``_land_mana_abilities``' first answer), refuses one whose only mana
    ability costs more than the tap or cannot be run inside a payment (its
    second), and otherwise falls back to the printed summary.

    **Rhystic Cave is why the question has to be the seam's.** "{T}: Choose a
    color. Add one mana of that color unless any player pays {1}. Activate only
    as an instant." is a mana ability (CR 605.1a), but "only as an instant"
    means its controller must have priority (CR 304.5), which nobody has while
    a cost is being paid — and any player may deny the mana. Read off its
    summary, the planner counted it as a free WUBRG land.

    The same question was answered wrong for sixteen more, measured over both
    manifest roles: every land whose mana ability costs more than {T} — the
    storage lands' "{T}, Remove any number of storage counters", the depletion
    lands' "{T}, Remove a depletion counter", Gemstone Mine, Fountain of Cho and
    the rest. The seam refused them (CR 602.2b) while the planner tapped them
    for one free mana of their summary's colour and spent no counter at all.
    """
    from .mixins.land_mana_taps import LandManaTapsMixin

    free, priced = LandManaTapsMixin._land_mana_abilities(land)
    if free is not None:
        return True
    if priced:
        # …unless a land type it *gained* gives it a second mana ability the
        # tap does pay for (CR 305.7's last sentence, CR 305.6): a depletion
        # land under Blanket of Night taps for {B} at the seam, and this
        # answered for the whole land by the ability it prints.
        return bool(LandManaTapsMixin._gained_type_mana(land))
    # A land that has lost all abilities (an animated one under Humility) has
    # lost the mana ability its type gives it with the rest — the seam's own
    # refusal, asked here so the planner does not count what it will not tap.
    from .keywords import abilities_lost_at

    if abilities_lost_at(land) is not None:
        return False
    return bool(land.effective_produced_mana or land.basic_land_types)


def answer_color_choices(instruction, color: str | None):
    """*instruction* with every "Choose a color" its controller makes answered
    by *color* — the colour named with a **mana ability's** activation.

    CR 605.3b: a mana ability does not use the stack and resolves the moment it
    is activated, so the colour its activator names with the activation is the
    answer to the choice it makes as it resolves (CR 608.2d). "{T}: Choose a
    color. Add one mana of that color unless any player pays {1}" (Rhystic
    Cave). Called only by the two sites that run a mana ability inline — the
    activation path's CR 605.3b branch and the tap seam — so an ability that
    goes on the stack keeps asking at resolution.

    A choice somebody *else* makes (a ``chooser`` on the payload) is left to
    ask, and so is any step this walk cannot see into: unanswered is the
    prompt, which is the safe direction. Rebuilt rather than mutated, because a
    compiled instruction is shared by every copy of the card.
    """
    from .grammar.lower import OFFER_BRANCH_KEYS, WRAPPER_KINDS
    from .oracle_types import OracleInstruction

    if not color or instruction is None:
        return instruction
    if instruction.kind == "choose_color":
        if (instruction.payload or {}).get("chooser"):
            return instruction
        return OracleInstruction(
            instruction.kind, instruction.value,
            {**instruction.payload, "color": color},
        )
    keys = WRAPPER_KINDS.get(instruction.kind) or OFFER_BRANCH_KEYS.get(instruction.kind)
    if not keys:
        return instruction
    changed = {
        key: tuple(
            answer_color_choices(step, color)
            for step in instruction.payload.get(key) or ()
        )
        for key in keys
        if instruction.payload.get(key)
    }
    if all(
        new is old
        for key, steps in changed.items()
        for new, old in zip(steps, instruction.payload.get(key) or ())
    ):
        return instruction
    return OracleInstruction(
        instruction.kind, instruction.value, {**instruction.payload, **changed}
    )


def land_text_is_run(land) -> bool:
    """Whether the engine runs any of *land*'s printed text at all.

    ``effective_produced_mana`` is Scryfall's summary of which symbols a land
    can make, and for a basic or a dual (whose only text is CR 305.6 reminder
    text) it is exactly the land. For a land whose printed mana ability the
    engine cannot compile it is a guess at the land with every cost and every
    condition taken out. Rhystic Cave was the case until PCY W3G1: "{T}: Choose
    a color. Add one mana of that color unless any player pays {1}. Activate
    only as an instant" summarised to WUBRG, so both mana seams read the
    unsupported card as a free five-colour land no player could deny and no
    timing restricted. It compiles now, and :func:`taps_for_payment` is what
    keeps it out of a payment; this stays the guard for the next land whose
    text nothing runs.

    A land whose types an effect has replaced is answered by its new types
    (CR 305.7: it loses its printed abilities and gains the basic one), so it
    counts as run whatever its printed text was — and that needs no arm of its
    own: the effective card *is* the land with its own text struck
    (``Permanent.effective_card``), which compiles as a land with nothing to
    run, plus whatever another effect granted it, which is text the engine
    does run.
    """
    from .oracle import compile_card_oracle

    return compile_card_oracle(land.effective_card).supported


__all__ = [
    "COLOR_SYMBOLS", "ManaPayment", "answer_color_choices",
    "fungible_colors_headroom",
    "fungible_types_headroom", "generic_cost", "land_text_is_run",
    "mana_cost_from_symbols",
    "mana_cost_label", "plan_payment",
    "taps_for_payment", "total_pips",
    "untapped_mana_lands",
]
