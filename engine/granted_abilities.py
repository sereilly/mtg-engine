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

from .oracle_types import compilation_cache

#: The probe card's type line. A granted ability is nearly always granted to a
#: creature, and the printed *type* is what makes "this creature" resolvable
#: while the line is being classified. It is deliberately not derived from the
#: granting card: the question asked here is whether the engine reads the
#: sentence, and a type line that varied per caller would make the answer vary
#: with something the sentence does not say.
_PROBE_TYPE_LINE = "Creature"


@compilation_cache
@lru_cache(maxsize=None)
def granted_ability_supported(text: str, self_name: str | None = None) -> bool:
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
        # The name the *quoted sentence* calls itself by, when it names itself
        # at all. "Johan can't attack" is only an ability on a card called
        # Johan: compiled under any other name the self-reference is a proper
        # noun the grammar has never heard of, and the probe would report the
        # grant unreadable when the game will read it perfectly. Everything
        # else is granted to "this creature" and compiles under the placeholder.
        name=self_name or "Granted Ability",
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


#: The possessive pronoun a granted ability opens with when the granting
#: sentence, not the quote, is what named the player.
_THAT_PLAYERS = "that player's"
_CHOSEN_PLAYERS = "the chosen player's"


def bind_chosen_player(text: str) -> str:
    """*text* with an unbound "that player's" read as the player this effect
    chose.

    "…gains "At the beginning of **that player's** upkeep, this enchantment
    deals 1 damage to that player."" (Takklemaggot.) CR 611.2c fixes what a
    granted ability means when it is granted, and here the pronoun points at a
    player the *granting* sentence named — the seat it asked to choose. The
    quote is compiled on its own (see :func:`granted_ability_supported`) and
    read again off the permanent's text, so inside it the words have no
    antecedent at all; left as printed they name nobody.

    The engine already has one spelling for "a player this permanent's effect
    bound", and it is "the chosen player" — the seat
    ``chosen_player_index`` holds. So the pronoun is translated into that
    vocabulary at grant time, which is the same move
    ``oracle.expand_ability_lines`` makes for equip: rewrite the sentence once,
    into words every reader downstream already knows, rather than teaching every
    reader a second pronoun.

    Only the **possessive** is rewritten. A bare "that player" later in the same
    quote does have an antecedent — the trigger this quote prints — and reading
    it as the chosen player too would be right by accident here and wrong on the
    first card whose granted trigger names somebody else.
    """
    line = text or ""
    lowered = line.lower()
    index = lowered.find(_THAT_PLAYERS)
    if index < 0:
        return line
    return line[:index] + _CHOSEN_PLAYERS + line[index + len(_THAT_PLAYERS):]


__all__ = ["bind_chosen_player", "granted_ability_supported"]
