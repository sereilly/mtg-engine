"""An ability granted as **quoted text** (CR 113.3, CR 611.2c).

"…that creature gains "Remove a matrix counter from this creature: Regenerate
this creature."" (Life Matrix.) What such a card grants is not a keyword and not
a described effect — it is a *whole printed ability*, and the engine already has
exactly one thing that turns a printed ability into behaviour: the compiler.

So the grant is carried as the text, `engine/keywords.py`'s
``GRANTED_ABILITY_LINES`` channel records it, ``Permanent.effective_card`` folds
it into the rules text, and `compile_card_oracle` reads it from there like any
printed line. Nothing downstream — the activation enumerator, the upkeep step,
the trigger scans, the web payload, the coverage scripts — has to learn that a
spell granted it.

This module owns the one question that is *not* the compiler's: whether the
engine can read the quoted text at all. A grant it cannot read is a card that
compiles supported and does nothing, which is the failure this codebase is
built to refuse, so the lowering asks here and refuses the line when the answer
is no.
"""

from __future__ import annotations

from functools import lru_cache

#: The probe card's type line. A granted ability is nearly always granted to a
#: creature, and the printed *type* is what makes "this creature" resolvable
#: while the line is being classified. It is deliberately not derived from the
#: granting card: the question asked here is whether the engine reads the
#: sentence, and a type line that varied per caller would make the answer vary
#: with something the sentence does not say.
_PROBE_TYPE_LINE = "Creature"


@lru_cache(maxsize=None)
def granted_ability_supported(text: str) -> bool:
    """Whether the engine compiles *text* into the ability it prints.

    Asked the way the game will ask it — the line is compiled **on a card that
    says nothing else**, which is precisely what ``effective_card`` will hand
    the compiler once the grant is recorded. A second, cheaper reading (a
    pattern list, a substring) would be a different reader of the same text, and
    the two would eventually disagree about what the card said.

    Imports are deferred because ``engine.oracle`` imports the grammar and the
    grammar's lowering asks this: at import time that is a cycle, at call time
    it is not.
    """
    line = " ".join((text or "").split())
    if not line:
        return False
    from .models import CardDefinition
    from .oracle import compile_card_oracle

    probe = CardDefinition(
        name="Granted Ability",
        mana_cost="",
        cmc=0.0,
        type_line=_PROBE_TYPE_LINE,
        oracle_text=line,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={},
    )
    return bool(compile_card_oracle(probe).supported)


__all__ = ["granted_ability_supported"]
