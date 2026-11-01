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
  makes, for the wire (``web/serialization``'s ``ability_mana``).
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


def split_refusal(instruction, split) -> str | None:
    """Why *split* is not a split *instruction* offers, or None when it is.

    Whole or not at all: only the printed symbols, no negative unit, and —
    where the count is printed — exactly that many. A count the resolution
    sizes ("X mana … where X is the sacrificed creature's mana value") is
    checked there, where it is known (``_split_mana_combination``)."""
    if split is None:
        return None
    shape = combination_of(instruction)
    if shape is None:
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
