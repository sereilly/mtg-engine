"""Whether a player can pay a mana cost from what is *on the board*, and how.

There are two different questions about paying, and the engine only ever
answered one of them well. ``SpellCastingMixin._pay_mana_cost`` spends the
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
from dataclasses import dataclass, field
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
    """

    from_pool: dict[str, int] = field(default_factory=dict)
    tapped: tuple["Permanent", ...] = ()


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
    pool: dict[str, int], required: dict[str, int], permissions: Sequence = ()
) -> dict[str, int] | None:
    """*pool* after paying *required* under CR 106.6 *permissions*, or None.

    The one arithmetic every payment site asks, generalised from
    :func:`fungible_colors_headroom` when Celestial Dawn arrived with a
    permission the two booleans on ``PlayerState`` could not express: white mana
    pays any colour and every other unit pays none, not even its own. Three
    buckets in the order that makes the payment maximal -- the coloured pips
    (pickiest), then ``{C}``, which nothing else can pay, then the generic
    remainder from whatever is left.
    """
    after = _assign_pips(pool, required, permissions)
    if after is None:
        return None
    colorless = int(required.get("C", 0))
    if after["C"] < colorless:
        return None
    after["C"] -= colorless
    generic = int(required.get("generic", 0))
    for symbol in ("C",) + tuple(PIP_SYMBOLS):
        if generic <= 0:
            break
        spend = min(after[symbol], generic)
        after[symbol] -= spend
        generic -= spend
    if generic > 0:
        return None
    return after


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


def plan_payment(
    pool: dict[str, int],
    lands: Sequence["Permanent"],
    required: dict[str, int],
    produces: "Callable[[Permanent], Sequence[str]] | None" = None,
) -> ManaPayment | None:
    """How *required* can be paid from *pool* plus tapping *lands*, or None.

    The pool goes first for the coloured pips, because floating mana is already
    spent-in-advance and a land kept untapped is worth more than one that is
    not. Whatever colours the pool cannot cover are matched against the lands;
    the generic part is then paid by anything left over, pool before lands.

    *produces* overrides what a land makes, for the effects that change it and
    that the permanent cannot answer alone: "Until end of turn, if you tap a
    land you control for mana, it produces {U} instead of any other type" (Deep
    Water) is a record on the *seat*, so only a caller with the game can resolve
    it (``engine/land_mana_swaps.py``). Passed in rather than looked up here for
    the reason this module takes a pool and a list instead of a game: what a
    cost can be paid from is arithmetic, and the caller owns the board. A caller
    that omits it gets the permanent's own answer, which is what every caller
    got before the override existed.
    """
    want = _normalized(required)
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
    for symbol, amount in list(left.items()):
        if generic <= 0:
            break
        paid = min(generic, int(amount))
        if paid:
            from_pool[symbol] = from_pool.get(symbol, 0) + paid
            left[symbol] = int(amount) - paid
            generic -= paid
    spare = [
        index
        for index, produced in producers
        if index not in assignment and produced
    ]
    if generic > len(spare):
        return None
    tapped = sorted([*assignment, *spare[:generic]])
    return ManaPayment(from_pool=from_pool, tapped=tuple(lands[i] for i in tapped))


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
    """
    instruction = getattr(ability, "instruction", ability)
    if instruction is None or not hasattr(instruction, "kind"):
        return False
    steps = (instruction, *_every_nested_step(instruction))
    if not any(step.kind in MANA_PRODUCING_KINDS for step in steps):
        return False
    return not any((step.payload or {}).get("targets") for step in steps)


def _every_nested_step(instruction) -> tuple:
    """Every instruction inside *instruction*, at any depth.

    Through the grammar's own reader of what a control-flow instruction
    contains, so "which keys hold steps" has one answer here: a branch key
    added there and not here would be an effect this predicate cannot see into.

    Named apart from ``targeting._nested_steps`` on purpose. That one walks a
    single level off a *third* copy of the step-key table
    (``targeting._WRAPPER_STEP_KEYS``), and this one walks all of them off the
    grammar's; sharing the name would be one word for two facts, which is the
    shape ``_per_recipient_count`` is already recorded under in SET_PLAYBOOK's
    Known gaps. That the two tables exist at all is the real debt, and it
    belongs to whoever next needs a third reader.
    """
    # `control_flow` rather than `categories`: this predicate was written
    # against the latter's re-export, and the wave-1 split that moved
    # `categories_of` out took the re-export with it. The name has one home
    # and this is it.
    from .grammar.lowering.control_flow import nested_instructions

    inner = nested_instructions(instruction)
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
        if perm.card.primary_type == "land"
        and not perm.tapped
        and perm.effective_produced_mana
    ]


__all__ = [
    "COLOR_SYMBOLS", "ManaPayment", "fungible_colors_headroom",
    "fungible_types_headroom", "generic_cost", "mana_cost_from_symbols",
    "mana_cost_label", "plan_payment",
    "total_pips",
    "untapped_mana_lands",
]
