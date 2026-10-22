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

import re
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
    probe = _probe_card(text, self_name)
    if probe is None:
        return False
    from .oracle import compile_card_oracle

    return bool(compile_card_oracle(probe).supported)


def _probe_card(text: str, self_name: str | None):
    """A card that says *text* and nothing else, or None for no text.

    The one probe both questions in this module are asked of, so "does it
    compile?" and "what did it compile to?" cannot be about two cards. It
    builds the card and stops: each caller names the compiler itself, because
    ``tests/engine/test_front_end_safety.py`` decides which caches hold a
    compiled answer by reading their own bodies for one.
    """
    line = " ".join((text or "").split())
    if not line:
        return None
    from .models import CardDefinition

    return CardDefinition(
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


#: The **static** sentences a derived grant may hand a permanent, by the
#: instruction kind the sentence compiles to — "This creature can't block.",
#: "This creature attacks each combat if able.", "All creatures able to block
#: this creature do so."
#:
#: A triggered or an activated ability handed over as a line needs no list: the
#: trigger scans and the activation enumerator read every ability off
#: ``Permanent.effective_card``, which is the whole reason the channel exists.
#: A *static* sentence is only as good as its one reader, and "the card
#: compiles" does not say that reader asks the effective card at the moment
#: the question arises — an entry-state phrase ("enters tapped") is read once,
#: as the permanent arrives, and handed over later it would be a line that
#: compiles, reports supported and does nothing. So each kind here names a
#: reader that was checked: ``block_legality`` reads ``cant_block`` and
#: ``declare_blockers_step`` ``must_be_blocked_by_all_able`` off the blocker's
#: and the attacker's effective card at the declaration, and
#: ``attack_legality._must_attack_if_able`` reads
#: ``must_attack_each_combat`` the same way. Adding a kind is a claim about its
#: reader; ``tests/regressions/test_ody_w1g1_conditional_grants.py`` drives
#: each one through a declaration.
DERIVABLE_STATIC_KINDS: frozenset[str] = frozenset(
    {"cant_block", "must_attack_each_combat", "must_be_blocked_by_all_able"}
)


@compilation_cache
@lru_cache(maxsize=None)
def derived_line_supported(text: str, self_name: str | None = None) -> bool:
    """Whether a permanent handed *text* on the **derived** channel
    (``keywords.DERIVED_ABILITY_LINES``) behaves as the sentence prints.

    The gate for a grant that comes and goes with a condition — "As long as
    there are seven or more cards in your graveyard, this creature gets +2/+2
    **and can't block**" (Childhood Horror), "…has **"At the beginning of your
    upkeep, sacrifice a creature."**" (Wayward Angel). Stricter than
    :func:`granted_ability_supported`, which it asks first: the line must
    compile, and every part of what it compiles to must be either an ability
    the board scans find (triggered, activated) or a static sentence in
    :data:`DERIVABLE_STATIC_KINDS`. A keyword line, an entry-state phrase and
    a line some text-keyed registry claims without an instruction are all
    refused — each has its own channel or its own moment, and this is neither.
    """
    if not granted_ability_supported(text, self_name):
        return False
    from .oracle import compile_card_oracle

    program = compile_card_oracle(_probe_card(text, self_name))
    carried = {
        id(part.instruction)
        for part in (*program.triggered_abilities, *program.activated_abilities)
        if part.instruction is not None
    }
    sentences = [
        instruction for instruction in program.instructions
        if id(instruction) not in carried
    ]
    if not sentences:
        return bool(carried)
    return all(
        instruction.kind in DERIVABLE_STATIC_KINDS for instruction in sentences
    )


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


#: How a granted ability names **the permanent that granted it**, once that
#: ability is the host's own text. 'Enchanted creature has "{T}: This creature
#: deals X damage …, where X is the number of arrow counters on **Archery
#: Training**."' Printed on the Aura the name is the Aura naming itself; folded
#: onto the creature it enchants it is a proper noun the creature's compiler
#: has never heard of. CR 201.5a says what it means there: "the name refers
#: only to the specific object which is that first ability's source" — one
#: object, not any object so named — so the name is written as the relation it
#: stood for, *with the object's id*, which is the only spelling that keeps two
#: Archery Trainings on one creature counting their own arrows.
#:
#: The same move ``grammar/effects/tokens.TOKEN_CREATOR_PHRASE`` makes for a
#: token whose text names its maker, and ``bind_chosen_player`` above makes for
#: a pronoun: rewrite the sentence once into words a reader knows, rather than
#: teach every reader of every ability what a foreign name might mean.
GRANTER_PHRASE_HEAD = ("the", "permanent", "with", "id")
GRANTER_PHRASE_TAIL = ("that", "granted", "this", "ability")

#: The id a quote is bound with when **no permanent is in hand** — the support
#: gate and the coverage scripts ask whether the sentence can be read, which
#: does not depend on which object it names. No permanent has it:
#: ``models.next_permanent_id`` counts from 1.
GRANTER_PROBE_ID = 0


def granter_phrase(permanent_id: int) -> str:
    """The words a granted ability names its granter by (see above)."""
    return " ".join(
        (*GRANTER_PHRASE_HEAD, str(int(permanent_id)), *GRANTER_PHRASE_TAIL)
    )


def bind_granter(
    text: str, granter_name: str | None, permanent_id: int = GRANTER_PROBE_ID
) -> str:
    """*text* with *granter_name* read as the one permanent granting it.

    Whole-name matches only, case-insensitively (the Aura readers lower-case
    what they hand out and a spell's quote keeps its capitals). A quote that
    never names its granter comes back unchanged, which is nineteen of the
    twenty quoted Aura grants in the pool.

    This binds the *name*; it does not promise a reader. A quote that names its
    granter somewhere no production reads the relation ("Sacrifice <the Aura>:
    …") still refuses to compile, and the caller asking
    :func:`granted_ability_supported` then reports the grant unreadable — which
    is the answer, not a gap in this function.
    """
    line = text or ""
    name = (granter_name or "").strip()
    if not line or not name:
        return line
    pattern = re.compile(rf"(?<![\w']){re.escape(name)}(?![\w])", re.IGNORECASE)
    return pattern.sub(granter_phrase(permanent_id), line)


__all__ = [
    "DERIVABLE_STATIC_KINDS",
    "GRANTER_PHRASE_HEAD",
    "GRANTER_PHRASE_TAIL",
    "GRANTER_PROBE_ID",
    "bind_chosen_player",
    "bind_granter",
    "derived_line_supported",
    "granted_ability_supported",
    "granter_phrase",
]
