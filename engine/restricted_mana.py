"""Mana that may be spent only on certain things (CR 106.6).

"Spend this mana only to cast creature spells." (Metamorphosis.) "Spend this
mana only to cast an instant or sorcery spell." (Vodalian Arcanist.) One
template with the *restriction* as its parameter, in exactly the sense
``engine/combat_restrictions.py`` means it — and the reason it is a module
rather than a flag is the reason that one is too: the engine held the first of
these as a field named ``creature_only_mana`` and a ``creature_spell: bool``
threaded to the payer, so the second wording had nowhere to go but a second
field, a second bool and a second branch in the payment.

**The restriction is on a payment, not on a cast.** Every clause the pool
printed until Ice Age narrowed *which spell* the mana could pay for, so the
predicate took the card being cast and the only payment site that asked was
``mixins/stack/casting.py``. Two Ice Age cards narrow a different payment —
"only to pay cumulative upkeep costs" (Adarkar Unicorn, Snowfall) and "only to
activate abilities of artifacts" (Soldevi Machinist) — and neither is a cast at
all. The predicate takes a :class:`PaymentPurpose` now, and all three payment
paths (casting, activating, an upkeep cost) ask it. That is the widening
``become_tapped`` and ``remove_from_battlefield`` needed: one question, asked
wherever it arises, rather than at the one site the pool happened to exercise.

Each entry is a printed phrase, the key it produces, and a predicate over that
purpose. The predicate is what the payment asks; the phrase is what the parser
claims and what the support gate reads, so the words admitted and the rule
enforced cannot drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

#: The purposes a payment can have, one per payment path in the engine. Named
#: constants rather than bare strings, so a typo in a predicate is a name error
#: instead of a restriction that silently admits nothing.
CAST = "cast"
ACTIVATE = "activate"
CUMULATIVE_UPKEEP = "cumulative_upkeep"


@dataclass(frozen=True)
class PaymentPurpose:
    """What a mana payment is *for* — which is what these clauses narrow.

    ``card`` is the spell being cast; ``source`` is the permanent whose ability
    is being activated, or whose upkeep is being paid. Both are optional,
    because a purpose names only what its own kind needs.

    A payment with **no** purpose admits no restricted mana. That is the
    failing-safe direction and what every caller written before this existed
    already got: unrestricted mana is unaffected either way, and restricted mana
    nobody can classify must not be spendable.
    """

    kind: str
    card: object = None
    source: object = None


#: What separates a restriction's name from the parameter its bucket carries.
#: "Spend this mana only to cast **the last card exiled with this artifact**"
#: (Ice Cauldron) is the first clause in the pool whose subject is one *object*
#: rather than a class of them, and a bucket is keyed by a string — so the
#: object is named in the key, after this. One spelling, because the writer
#: (``handlers/mana``) and the reader (:func:`restriction_admits`) have to agree.
PARAMETER = ":"


@dataclass(frozen=True)
class ManaRestriction:
    """One "spend this mana only to…" clause."""

    key: str
    #: Whether *purpose* is something this mana may pay for. A restriction that
    #: reads a parameter takes it as a second argument.
    admits: Callable[..., bool]
    #: Whether this clause's bucket key carries a parameter after
    #: :data:`PARAMETER`, and ``admits`` therefore takes it. Declared rather
    #: than sniffed, the way ``ActivationRestriction.reads_payload`` is: a
    #: signature guessed by introspection is a signature that silently stops
    #: being guessed right.
    reads_parameter: bool = False


def _type_line(obj) -> str:
    return (getattr(obj, "type_line", "") or "").lower()


def _casting_a_creature(purpose: "PaymentPurpose") -> bool:
    return purpose.kind == CAST and "creature" in _type_line(purpose.card)


def _casting_an_instant_or_sorcery(purpose: "PaymentPurpose") -> bool:
    lowered = _type_line(purpose.card)
    return purpose.kind == CAST and ("instant" in lowered or "sorcery" in lowered)


def _casting_an_artifact(purpose: "PaymentPurpose") -> bool:
    return purpose.kind == CAST and "artifact" in _type_line(purpose.card)


def _paying_cumulative_upkeep(purpose: "PaymentPurpose") -> bool:
    """"Spend this mana only to pay cumulative upkeep costs." (Adarkar Unicorn,
    Snowfall.)

    Any permanent's, not only the producer's: the printed phrase says
    "cumulative upkeep costs" with no possessive.
    """
    return purpose.kind == CUMULATIVE_UPKEEP


def _casting_the_named_card(purpose: "PaymentPurpose", card_name: str) -> bool:
    """"Spend this mana only to cast **the last card exiled with this
    artifact**." (Ice Cauldron.)

    The permitted object is not a class this predicate could test — it is one
    card, chosen when the mana was made — so the bucket's key carries its name
    and this compares against that. A name rather than an identity because the
    two are the same question here and only one of them survives a string key:
    a deck repeats one immutable ``CardDefinition`` per copy
    (``web/deck_builder``), so every copy of a card in a hand *is* the same
    object, and no comparison can tell two of them apart.

    An empty parameter admits nothing, which is the direction every refusal in
    this file goes: mana whose restriction cannot be tested must not be
    spendable.
    """
    return bool(
        card_name
        and purpose.kind == CAST
        and str(getattr(purpose.card, "name", "")) == card_name
    )


def _activating_an_artifact_ability(purpose: "PaymentPurpose") -> bool:
    """"Spend this mana only to activate abilities of artifacts." (Soldevi
    Machinist.)

    Read off the permanent whose ability it is, through what that permanent
    *effectively* is: an artifact animated into a creature is still an artifact
    (CR 205.1b), and a permanent a type change made one counts for the same
    reason.
    """
    source = purpose.source
    effective = getattr(source, "effective_card", None) or source
    return purpose.kind == ACTIVATE and "artifact" in _type_line(effective)


# The printed line, anchored at both ends. Anchored because a sentence saying
# more than one of these is a restriction this file does not implement, and a
# prefix match would claim it and then enforce the narrower rule — mana more
# freely spendable than the card allows.
_PATTERNS: tuple[tuple[re.Pattern[str], ManaRestriction], ...] = (
    (
        re.compile(r"^spend this mana only to cast creature spells\.?$"),
        ManaRestriction("creature", _casting_a_creature),
    ),
    (
        re.compile(r"^spend this mana only to cast an instant or sorcery spell\.?$"),
        ManaRestriction("instant_or_sorcery", _casting_an_instant_or_sorcery),
    ),
    (
        # Mishra's Workshop. Its {C}{C}{C} parsed here long before this row
        # existed; what refused the line was this clause, and the refusal took
        # the whole ability with it — so the land fell through to the blanket
        # land pass and tapped for the single {C} `produced_mana` records. An
        # artifact-restricted three mana became one unrestricted mana, which is
        # the direction the anchoring note above is about.
        re.compile(r"^spend this mana only to cast artifact spells\.?$"),
        ManaRestriction("artifact", _casting_an_artifact),
    ),
    (
        # Adarkar Unicorn, Snowfall. The first clause in the pool that names a
        # payment which is not a cast — and the reason the predicate takes a
        # purpose rather than a card.
        re.compile(r"^spend this mana only to pay cumulative upkeep costs\.?$"),
        ManaRestriction("cumulative_upkeep", _paying_cumulative_upkeep),
    ),
    (
        # Soldevi Machinist. The other non-cast payment, and the one that needs
        # to know *whose* ability: "abilities of artifacts" is a narrowing on the
        # ability's source, which only the activation path holds.
        re.compile(r"^spend this mana only to activate abilities of artifacts\.?$"),
        ManaRestriction("artifact_ability", _activating_an_artifact_ability),
    ),
    (
        # Ice Cauldron. The first clause whose subject is one *object* rather
        # than a class of them: which card it is was decided when the mana was
        # made, so the bucket's key carries it and the predicate reads it back.
        # The noun is captured and not required to be "artifact" for the reason
        # every other parameter here is data — a card printing the same sentence
        # about an enchantment needs no row.
        re.compile(
            r"^spend this mana only to cast the last card exiled with this "
            r"[a-z]+\.?$"
        ),
        ManaRestriction(
            "last_card_exiled_with_source",
            _casting_the_named_card,
            reads_parameter=True,
        ),
    ),
)

#: The keys above, for a reader that needs the set rather than a lookup.
RESTRICTION_KEYS = frozenset(r.key for _pattern, r in _PATTERNS)


def mana_restriction_for(sentence: str) -> ManaRestriction | None:
    """The restriction *sentence* imposes, or None when it is not one."""
    text = sentence.strip().lower()
    for pattern, restriction in _PATTERNS:
        if pattern.match(text):
            return restriction
    return None


def restriction_admits(key: str, purpose: "PaymentPurpose | None") -> bool:
    """Whether mana held under *key* may pay for *purpose*.

    An unknown key admits **nothing**. That is the safe direction: a key with no
    predicate behind it is mana whose restriction the engine cannot test, and
    treating it as unrestricted would spend it on anything. A payment with no
    purpose admits nothing for the same reason.
    """
    if purpose is None:
        return False
    name, _, parameter = key.partition(PARAMETER)
    for _pattern, restriction in _PATTERNS:
        if restriction.key != name:
            continue
        if restriction.reads_parameter:
            return bool(restriction.admits(purpose, parameter))
        # A parameter on a restriction that reads none is a key nobody wrote and
        # nothing can test, so it admits nothing — the same direction the
        # unknown key below goes.
        return not parameter and bool(restriction.admits(purpose))
    return False


def spendable_restricted_mana(player, purpose: "PaymentPurpose | None") -> dict[str, int]:
    """Every restricted bucket *purpose* may be paid from, merged by symbol.

    Merged rather than tried one at a time because a payment is one operation:
    two buckets that both admit it are, to CR 601.2g, simply mana in the pool.
    Which of them a spent unit came out of is settled afterwards by
    :func:`debit_restricted_mana`, in the same order this merge walked.

    Lives here rather than beside one payment path, because there are three of
    those now and a second copy of the merge would be a second opinion about
    what a bucket may pay for.
    """
    merged: dict[str, int] = {}
    if purpose is None:
        return merged
    for key, bucket in (getattr(player, "restricted_mana", None) or {}).items():
        if not any(bucket.values()) or not restriction_admits(key, purpose):
            continue
        for symbol, amount in bucket.items():
            merged[symbol] = merged.get(symbol, 0) + amount
    return merged


def debit_restricted_mana(
    player, purpose: "PaymentPurpose | None", symbol: str, amount: int
) -> None:
    """Take *amount* of *symbol* out of the buckets that paid for *purpose*.

    In the merge's own order, so the attribution matches what was offered. The
    order between two admitting buckets is arbitrary and does not matter: both
    are spendable on this payment and both empty at the same step boundary, so
    no observable differs.
    """
    remaining = amount
    for key, bucket in (getattr(player, "restricted_mana", None) or {}).items():
        if remaining <= 0:
            break
        if not restriction_admits(key, purpose):
            continue
        taken = min(remaining, bucket.get(symbol, 0))
        if taken:
            bucket[symbol] = bucket.get(symbol, 0) - taken
            remaining -= taken


__all__ = [
    "ACTIVATE",
    "CAST",
    "CUMULATIVE_UPKEEP",
    "PARAMETER",
    "ManaRestriction",
    "PaymentPurpose",
    "RESTRICTION_KEYS",
    "debit_restricted_mana",
    "mana_restriction_for",
    "restriction_admits",
    "spendable_restricted_mana",
]
