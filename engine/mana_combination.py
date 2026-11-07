"""Mana made "in any combination of" listed symbols: the split, and who
chooses it.

"{T}, Sacrifice a Forest: Add three mana in any combination of {R} and/or
{G}." (Goblin Clearcutter, Orcish Lumberjack.) "Add X mana in any combination
of {B} and/or {R}, where X is the sacrificed creature's mana value." (Burnt
Offering.) A fixed number of mana, each unit's symbol the producer's choice —
so RRG, RGG and every other mix are as legal as RRR. The split rides the
resolution's choices under :data:`MANA_COMBINATION` (a ``{symbol: count}``
dict), announced with the activation or the cast the way ``mana_color`` is
(CR 605.3a: a mana ability resolves as it is activated, so its choices are
made then). Nothing wrote that key until W2G3, so a mix was unreachable.

Three readers:

* :func:`split_refusal` — the gate the activation and cast paths ask before
  anything is paid, so a malformed split is refused rather than silently
  replaced by the default (``handlers/mana._split_mana_combination`` still
  discards one, as the last line of defence).
* :func:`default_split` — what a seat that named no split gets: units toward
  the coloured mana the seat's own held cards and abilities ask for and its
  pool lacks (``mana_wants.mana_wants``, the demand side every payment
  planner already shares), the rest the seat's chosen colour when listed, else
  the first printed symbol. With nothing wanted it is the old default exactly.
* :func:`combination_of` — which symbols and how many one ability or spell
  makes, for the wire (``web/serialization``'s ``ability_mana``), and
  :func:`cast_split_offer` the same for a **spell** a seat may cast, with the
  count its cost decides.

"Add {U} or {C}{U}" (Adarkar Unicorn) is a choice between written-out
quantities rather than a split, and is answered on the same key — the mana the
seat takes, which must be one of them exactly (:func:`alternatives_of`,
:func:`chosen_alternative`, read by ``handlers/mana._pick_mana_alternative``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game import Game

#: The resolution-choices key a split rides under (the cast's and the
#: activation's ``choices``), read by ``handlers/mana._split_mana_combination``.
MANA_COMBINATION = "mana_combination"


def _combination_steps(instruction) -> list:
    """Every add-mana step under *instruction* that makes mana "in any
    combination of", wrappers opened."""
    found: list = []
    stack = [instruction]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        kind = getattr(current, "kind", None)
        payload = getattr(current, "payload", None)
        if kind is None or not isinstance(payload, dict):
            if isinstance(current, (list, tuple)):
                stack.extend(current)
            continue
        if kind == "add_mana_from_text" and payload.get("combination"):
            found.append(current)
        for value in payload.values():
            if isinstance(value, (list, tuple)) or hasattr(value, "kind"):
                stack.append(value)
    return found


def combination_of(instruction) -> "tuple[tuple[str, ...], int | str] | None":
    """``(symbols, count)`` of the one "any combination" step *instruction*
    carries — *count* an int, or ``"x"`` where the resolution sizes it — or
    None when it carries none (or more than one, which no card prints)."""
    steps = _combination_steps(instruction)
    if len(steps) != 1:
        return None
    payload = steps[0].payload
    count = payload.get("combination_count", 0)
    if not isinstance(count, int) or isinstance(count, bool):
        count = "x"
    return tuple(str(symbol) for symbol in payload["combination"]), count


def cast_split_offer(game: "Game", seat: int, card) -> "dict | None":
    """The split a **spell** makes "in any combination of", for the cast's
    chooser (Burnt Offering: "Add X mana in any combination of {B} and/or
    {R}, where X is the sacrificed creature's mana value") — the shape of an
    activation's ``ability_mana`` ``combination`` entry, so the client asks it
    with the chooser Goblin Clearcutter's ability uses, and the cast takes the
    answer as ``mana_combination``. None for every other card.

    A printed count is ``count``. A count the cast's own cost decides is
    ``count_by_cost``: each permanent *seat* controls, by id, with the X that
    permanent would make paying the cost — through the evaluator the
    resolution counts with (``count_from_payload`` over
    ``sacrificed_for_cost``), so the chooser offers exactly the splits the
    resolution accepts.
    """
    from .game_types import OracleExecutionContext
    from .handlers._amounts import count_from_payload
    from .oracle import compile_card_oracle

    instructions = compile_card_oracle(card).instructions
    shape = combination_of(instructions)
    if shape is None:
        return None
    symbols, count = shape
    offer: dict = {"symbols": [str(symbol) for symbol in symbols]}
    if count != "x":
        offer["count"] = int(count)
        return offer
    spec = (_combination_steps(instructions)[0].payload or {}).get("x_from_count")
    if not isinstance(spec, dict) or "cost_sacrifice_characteristic" not in spec:
        return None
    caster = game.players[seat]
    offer["count_by_cost"] = {
        str(permanent.permanent_id): count_from_payload(
            game,
            OracleExecutionContext(
                caster=caster, target=caster, card=card,
                choices={"sacrificed_for_cost": permanent},
            ),
            spec,
        )
        for permanent in game.controlled_by(seat)
    }
    return offer


def alternatives_of(instruction) -> "tuple[tuple[tuple[str, int], ...], ...] | None":
    """The written-out quantities of the one "Add A or B" step *instruction*
    carries ("Add {U} or {C}{U}", Adarkar Unicorn; "Add {B}{B} or {G}{G}",
    Cadaverous Bloom) — each a ``((symbol, count), …)`` — or None."""
    found: list = []
    stack = [instruction]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        kind = getattr(current, "kind", None)
        payload = getattr(current, "payload", None)
        if kind is None or not isinstance(payload, dict):
            if isinstance(current, (list, tuple)):
                stack.extend(current)
            continue
        if kind == "add_mana_from_text" and payload.get("pips_alternatives"):
            found.append(payload["pips_alternatives"])
        for value in payload.values():
            if isinstance(value, (list, tuple)) or hasattr(value, "kind"):
                stack.append(value)
    if len(found) != 1:
        return None
    return tuple(
        tuple((str(symbol).upper(), int(count)) for symbol, count in alternative)
        for alternative in found[0]
    )


def chosen_alternative(alternatives, split) -> "int | None":
    """The index of the alternative *split* names — the mana it makes, as
    ``{symbol: count}``, the shape a split rides in — or None when it names
    none of them (or nothing)."""
    wanted = normalized_split(split)
    if not wanted:
        return None
    wanted = {symbol: amount for symbol, amount in wanted.items() if amount}
    for index, alternative in enumerate(alternatives):
        made: dict[str, int] = {}
        for symbol, count in alternative:
            made[str(symbol).upper()] = made.get(str(symbol).upper(), 0) + int(count)
        if made == wanted:
            return index
    return None


def split_refusal(instruction, split) -> str | None:
    """Why *split* is not a split *instruction* offers, or None when it is.

    Whole or not at all: only the printed symbols, no negative unit, and —
    where the count is printed — exactly that many. A count the resolution
    sizes ("X mana … where X is the sacrificed creature's mana value") is
    checked there, where it is known (``_split_mana_combination``).

    An "Add A or B" of written-out quantities (:func:`alternatives_of`) is
    answered on the same channel — the mana the seat takes, which must be one
    of the alternatives exactly."""
    if split is None:
        return None
    shape = combination_of(instruction)
    if shape is None:
        alternatives = alternatives_of(instruction)
        if alternatives:
            if chosen_alternative(alternatives, split) is not None:
                return None
            said = " or ".join(
                "".join(("{" + symbol + "}") * count for symbol, count in alternative)
                for alternative in alternatives
            )
            return f"the mana may be only {said}"
        return "this makes no mana in any combination of symbols to split"
    symbols, count = shape
    if not isinstance(split, dict):
        return "a mana split names a count for each symbol"
    try:
        wanted = {str(symbol).upper(): int(amount) for symbol, amount in split.items()}
    except (TypeError, ValueError):
        return "a mana split names a count for each symbol"
    if any(symbol not in symbols for symbol in wanted):
        return f"the mana may be only {' and/or '.join('{' + s + '}' for s in symbols)}"
    if any(amount < 0 for amount in wanted.values()):
        return "a mana split cannot name a negative amount"
    if count != "x" and sum(wanted.values()) != count:
        return f"the split must add up to {count} mana"
    return None


def normalized_split(split) -> "dict[str, int] | None":
    """*split* with its symbols upper-cased, or None for no split."""
    if not isinstance(split, dict):
        return None
    try:
        return {str(symbol).upper(): int(amount) for symbol, amount in split.items()}
    except (TypeError, ValueError):
        return None


def default_split(
    game: "Game", seat: int, symbols: tuple, total: int, chosen: "str | None",
) -> dict:
    """The split a seat that named none takes: what its held cards ask for.

    Units go, in the order the seat's wants list them (its hand's spells and
    hand abilities, then its permanents' abilities — ``mana_wants``), to each
    listed symbol a want asks for beyond what the pool already holds and the
    split has given; whatever is left is the seat's chosen colour when the
    clause lists it, otherwise the first printed symbol. A seat with nothing
    to cast that needs a listed colour gets every unit the same, which is what
    this default was before it read the wants. Deterministic: seat-visible
    information only (CR 400.2), nothing random.
    """
    if total <= 0:
        return {}
    split = {symbol: 0 for symbol in symbols}
    remaining = total
    from .mana_wants import mana_wants

    wants = mana_wants(game, seat)
    pool = game.players[seat].mana_pool
    for want in tuple(wants.cards) + tuple(wants.abilities):
        for symbol in symbols:
            if remaining <= 0:
                break
            missing = int(want.get(symbol, 0)) - int(pool.get(symbol, 0)) - split[symbol]
            if missing > 0:
                take = min(missing, remaining)
                split[symbol] += take
                remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        split[chosen if chosen in symbols else symbols[0]] += remaining
    return {symbol: amount for symbol, amount in split.items() if amount}
