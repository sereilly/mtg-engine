"""CR 608.2b relaxed by the object's own printed sentence.

CR 608.2b is the fizzle: as a spell or ability begins to resolve, its targets
are checked, and if **every** one of them is illegal the object leaves the stack
without resolving. `legality.illegal_targets_refusal` is where this engine asks
that question.

Some objects print the exception:

    When this creature enters, exchange control of this creature and up to one
    target creature an opponent controls. If you don't or can't make an
    exchange, sacrifice this creature. **This ability still resolves if its
    target becomes illegal.** (Gilded Drake.)

The sentence is not an effect. Nothing about it is dispatched, nothing about it
is put on the stack, and there is no instruction for a production to lower —
it changes what the *rules* do with the object, which is exactly the shape
`engine/special_actions.py` and `engine/cost_modifiers.py` already have and the
reason all three are read as **whole printed sentences** rather than compiled.
`grammar/parser._parse_registry_claimed_sentence` consumes it and asks this
module whether the words can be read, so a wording nothing here implements
leaves the line refused rather than being silently dropped — the rule
`engine/activation_restrictions.py` states for its own clause.

**Why the card prints it, and why the sentence is load-bearing on this one.**
Gilded Drake's second sentence is a consequence of the first *not* having
happened. Under a plain CR 608.2b, a Drake whose only target had left would
fizzle: the exchange would not happen and the sacrifice would not happen
either, so the Drake's controller would keep a 3/3 flier for {1}{U} and the
opponent would keep their creature. The sentence is what makes the failure
land on the Drake.

**What it is worth today, stated plainly.** This engine's CR 608.2b check
already declines two whole classes of object — a triggered ability, because a
fire site stamps targets a rules-correct announcement would never have offered,
and any card that is not an instant or a sorcery — and Gilded Drake's ability is
both of those. So the override changes no outcome *at present*; it is asserted
here so that the day either exclusion lifts (both are in ROADMAP.md) this card
keeps the behaviour it prints, instead of quietly acquiring a fizzle nobody
went looking for. The row is cheap, the alternative is a printed sentence read
by nothing, and `tests/rules/test_illegal_target_resolution.py` pins the branch
against a card that *is* an instant so it is exercised rather than merely
present.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CardDefinition


#: The override a printed sentence states, keyed by the sentence. One row
#: today; a second goes here beside it rather than in a branch, for the reason
#: every derivation table in this engine is a table.
#:
#: Anchored whole, never as a substring, for `special_actions.special_action_line`'s
#: reason: a substring match is how a whitelist comes to claim text it does not
#: implement. "Ability" and "spell" are both admitted because the printed
#: sentence names whichever object it is on and the rule (CR 608.2b) is the same
#: for both; the plural is admitted because a card with two instances of the
#: word "target" would print "its targets become illegal", and CR 608.2b's
#: all-or-nothing test is what the sentence overrides either way.
RESOLVES_WITH_ILLEGAL_TARGETS = "resolves_with_illegal_targets"

_OVERRIDE_SENTENCES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^this (?:ability|spell) still resolves if "
            r"(?:its target becomes illegal|its targets become illegal)$"
        ),
        RESOLVES_WITH_ILLEGAL_TARGETS,
    ),
)


def _normalize(text: str) -> str:
    return " ".join((text or "").replace("’", "'").split()).lower().rstrip(".")


def resolution_override_sentence(text: str) -> str | None:
    """The override *text* states, as its kind, or None.

    The grammar's claim and the enforcement below both go through here, so what
    the engine implements and what it claims to have read cannot drift — the
    same seam `enter_effects.enter_effect_line` is.
    """
    normalized = _normalize(text)
    for pattern, kind in _OVERRIDE_SENTENCES:
        if pattern.match(normalized):
            return kind
    return None


def _states_override(text: str, kind: str) -> bool:
    """Whether any sentence of *text* states *kind*.

    Sentence by sentence rather than line by line: this is a *rider* on an
    ability, printed after the effect on the same line, so a line-level match
    would never fire. Split on the full stop the same way the printed sentence
    ends, and each piece asked whole.
    """
    return any(
        resolution_override_sentence(sentence) == kind
        for sentence in (text or "").replace("\n", ". ").split(".")
    )


def resolves_with_illegal_targets(
    card: "CardDefinition | None", ability_text: str | None = None
) -> bool:
    """Whether this object prints CR 608.2b's exception on itself.

    *ability_text* is the printed line of the ability on the stack when the
    caller has one (`StackItem.ability_text`), and it is preferred: the sentence
    is a rider on **one** ability, and a card whose second ability targets
    without printing the override must not inherit it. The card's whole text is
    the fallback for a spell, which has no ability line and whose every targeting
    instruction comes from the same printed text.
    """
    if ability_text:
        return _states_override(ability_text, RESOLVES_WITH_ILLEGAL_TARGETS)
    text = getattr(card, "oracle_text", "") or "" if card is not None else ""
    return _states_override(text, RESOLVES_WITH_ILLEGAL_TARGETS)
