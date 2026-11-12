"""Sunburst (CR 702.44), the keyword and the entry replacement it *is*.

CR 702.44a does not describe sunburst, it **defines** it: "Sunburst" means "If
this object is entering as a creature, ignoring any type-changing effects that
would affect it, it enters with a +1/+1 counter on it for each color of mana
spent to cast it. Otherwise, it enters with a charge counter on it for each
color of mana spent to cast it." So this is the rewrite ``engine/modular.py``
made for modular and ``engine/fading.py`` for fading: the printed keyword line
becomes the sentence the rules say it already is, applied by
``line_rewrites.expand_ability_lines`` before any line is classified, and from
there nothing downstream knows the word. No card asks about a permanent "with
sunburst", so the word needs no layer-6 presence (modular's
``has_printed_modular`` exists for Arcbound Overseer; nothing like it prints
here).

**One line, two sentences.** CR 702.44a's text is one static ability (CR
113.3) whose second sentence is the first one's "otherwise" — split across two
lines, the second would be a sentence about nothing. So the rewrite writes the
rule's text on one line, and ``enter_effects.enters_with_counters_per_color_spent``
reads that whole line as one entry replacement, beside the one-sentence form
the CR 702.44c example gives Modular—Sunburst ("This permanent enters with a
+1/+1 counter on it for each color of mana spent to cast it") and later
sets print as converge. One reader, three spellings; the support gate, the
grammar's registry claim, ``parse_coverage`` and the entry state all ask it, so
what is claimed and what is placed cannot drift.

**Which kind of counter is decided as the object enters**, not by the printed
type line: "entering as a creature, ignoring any type-changing effects" is the
object's copiable values (CR 707.2 — a Copy Artifact copying an artifact
creature with sunburst enters as a creature) and never layer 4's answer (a
noncreature sunburst artifact under March of the Machines still enters with
charge counters). The entry state reads ``printed_characteristics.printed_shape``
of the permanent's ``effective_card`` — layers 1 and 3, no layer 4 — for that
reason.

**What was spent is measured, not predicted** (CR 702.44b, the Pentad Prism
ruling of 2020-08-07: "Sunburst checks what mana was actually spent to cast
the spell"). ``PoolPaymentMixin._pay_cast_mana`` — the one payment every
cast's mana goes through, the mana cost or an alternative cost in its place
and every additional cost and tax beside it (CR 702.44b's "including
additional or alternative costs") — reports the difference it made to the pool
and its restricted buckets (:func:`pool_units`, :func:`mana_spent_between`);
the cast records it on the stack item (``choices[MANA_SPENT_TO_CAST]``) and
the resolving permanent spell stamps it on the permanent before it enters
(``_resolve_permanent_spell``). A permanent put onto the battlefield any other
way — reanimated, blinked, a token, a Bringer's free arrival — passes no cast
and carries no stamp, which is CR 702.44b's "only if the object … is entering
the battlefield from the stack as a resolving spell" by construction. A
CR 609.4b permission ("spend mana as though it were mana of any color")
changes which pips a unit may pay, never which unit was spent, so the delta
counts the mana's own colours.

**The payment that spends the most colours** is the payer's choice (CR
601.2h), and it is the half of sunburst the cast cannot make for the payer:
:func:`color_spreading_costs` is the one list of ways to pay a cost with more
colours in it, asked by the pool payment for floating mana
(``_pay_cast_cost``) and by the payment planner every auto-tap shares
(``ai_payment._PaymentPlanner.plan``) for the sources it taps.

CR 702.44d (several instances each work) needs nothing here: two printed lines
are two rewritten lines, and the entry state places for each.
"""

from __future__ import annotations

from itertools import combinations
import re

#: The rules text CR 702.44a gives the keyword, quoted word for word, on one
#: line (see the module's note).
SUNBURST_RULES_TEXT = (
    "If this object is entering as a creature, ignoring any type-changing "
    "effects that would affect it, it enters with a +1/+1 counter on it for "
    "each color of mana spent to cast it. Otherwise, it enters with a charge "
    "counter on it for each color of mana spent to cast it."
)

#: The ``StackItem.choices`` key a cast records what its mana payment spent
#: under (``{symbol: count}``, colourless as "C"), and the permanent-metadata
#: key the resolving permanent spell copies it to. One spelling for both ends,
#: for ``enter_effects.CAST_X_VALUE``'s reason.
MANA_SPENT_TO_CAST = "mana_spent_to_cast"

#: The five colours (CR 105.1), in WUBRG order. Colourless is not one (the
#: Engineered Explosives ruling of 2020-08-07: "Colorless is not a color").
COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")

#: The pool's symbols, colourless included — what a payment can take out.
_POOL_SYMBOLS: tuple[str, ...] = ("W", "U", "B", "R", "G", "C")

#: "Sunburst", as the printed line survives reminder-text removal.
_SUNBURST_LINE = re.compile(r"^sunburst\.?$", re.IGNORECASE)

#: Any line that *is* a sunburst keyword line, readable or not — the word and
#: whatever a later printing might put after it. The wider shape is what the
#: support gate asks (:func:`unread_sunburst_line`), so a variant the rewrite
#: does not read stays refused *as sunburst* rather than reaching a classifier
#: that has never heard of the word: an artifact whose other line compiles
#: would otherwise report supported entering with no counters at all, which is
#: what all six of Fifth Dawn's noncreature sunburst cards did on arrival.
_SUNBURST_SHAPE = re.compile(r"^sunburst\b.*$", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip()


def is_sunburst_line(line: str) -> bool:
    """Whether *line* is a printed sunburst keyword line, whether or not
    :func:`expand_sunburst_line` can read it."""
    return _SUNBURST_SHAPE.match(_stripped(line)) is not None


def expand_sunburst_line(line: str) -> str | None:
    """The CR 702.44a rules text for one printed sunburst line, or None."""
    if _SUNBURST_LINE.match(_stripped(line)) is None:
        return None
    return SUNBURST_RULES_TEXT


def expand_sunburst_lines(oracle_text: str) -> str:
    """*oracle_text* with every sunburst keyword line rewritten to its rules
    text. Text without one is returned unchanged."""
    if not oracle_text or "unburst" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_sunburst_line(line) or line for line in oracle_text.split("\n")
    )


def unread_sunburst_line(oracle_text: str) -> str | None:
    """A printed sunburst-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run, as ``modular.unread_modular_line`` is.
    """
    for line in (oracle_text or "").split("\n"):
        if is_sunburst_line(line):
            return _stripped(line)
    return None


# --- what a cast spent -----------------------------------------------------


def pool_units(player) -> dict[str, int]:
    """Every unit of mana *player* holds, per symbol: the pool and every
    restricted bucket (CR 106.6) together, because a payment may draw on both
    and what it spent is the mana, whichever store it sat in."""
    held = {symbol: int(player.mana_pool.get(symbol, 0) or 0) for symbol in _POOL_SYMBOLS}
    for bucket in (getattr(player, "restricted_mana", None) or {}).values():
        for symbol, amount in bucket.items():
            if symbol in held:
                held[symbol] += int(amount or 0)
    return held


def mana_spent_between(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """The units a payment took, per symbol: *before* less *after*
    (:func:`pool_units` both), the symbols it took none of left out."""
    return {
        symbol: spent
        for symbol in _POOL_SYMBOLS
        if (spent := int(before.get(symbol, 0)) - int(after.get(symbol, 0))) > 0
    }


def colors_spent(spent) -> int:
    """How many colours of mana *spent* (a :data:`MANA_SPENT_TO_CAST` record)
    holds — CR 702.44a's number. Colourless is not a colour; a missing record
    is a permanent that was not cast, and counts nothing."""
    if not spent:
        return 0
    return sum(1 for color in COLORS if int(spent.get(color, 0) or 0) > 0)


# --- paying with more colours ----------------------------------------------


def counts_colors_spent(card) -> bool:
    """Whether a cast of *card* is worth more for every colour spent on it:
    one of its lines, after every rewrite, is an entry replacement sized by the
    colours of mana spent to cast it (sunburst, Modular—Sunburst)."""
    if card is None:
        return False
    text = getattr(card, "oracle_text", "") or ""
    if "unburst" not in text and "spent to cast" not in text:
        return False
    from .enter_effects import enters_with_counters_per_color_spent
    from .line_rewrites import expand_card_lines

    return any(
        enters_with_counters_per_color_spent(line, card.name) is not None
        for line in expand_card_lines(card)
    )


def color_spreading_costs(required: dict[str, int]):
    """*required* again with some of its generic mana named as colours it does
    not already name, most new colours first, ending with *required* itself.

    The ways CR 601.2h lets a payer pay one cost, as far as the colours spent
    on it go: a generic {1} paid with a unit of a colour no pip names is one
    more colour spent, so ``{"generic": 3}`` is first asked as each set of
    three colours, then each pair, then each single colour, and last as
    printed. A payer takes the first its mana can pay — every caller tries
    candidates whose payment leaves nothing behind when it fails
    (``_pay_mana_cost``, the planner's matching) — so the cost paid is the
    cost owed, with as many colours in it as the mana in reach allows. The
    colours a pip already names count already and are never asked twice.
    """
    generic = max(0, int(required.get("generic", 0) or 0))
    named = {color for color in COLORS if int(required.get(color, 0) or 0) > 0}
    spare = [color for color in COLORS if color not in named]
    for size in range(min(generic, len(spare)), 0, -1):
        for chosen in combinations(spare, size):
            candidate = dict(required)
            candidate["generic"] = generic - size
            for color in chosen:
                candidate[color] = int(candidate.get(color, 0) or 0) + 1
            yield candidate
    yield dict(required)


__all__ = [
    "COLORS",
    "MANA_SPENT_TO_CAST",
    "SUNBURST_RULES_TEXT",
    "color_spreading_costs",
    "colors_spent",
    "counts_colors_spent",
    "expand_sunburst_line",
    "expand_sunburst_lines",
    "is_sunburst_line",
    "mana_spent_between",
    "pool_units",
    "unread_sunburst_line",
]
