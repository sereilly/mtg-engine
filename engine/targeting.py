"""Cast-time targeting derived from the compiled program (CR 115).

`engine/legality.py` answers "what does this spell target?" by re-reading the
oracle text with ~40 substring predicates — a second parser of the same text,
which must agree with the compiler forever or the UI offers targets the engine
rejects. This module is its replacement: it reads the *compiled program* the
engine already built, so there is one parse and nothing to keep in sync.

The replacement is partial by design. A target kind is derivable when the
program carries the evidence:

- an Aura's ``Enchant <subject>`` line names what it attaches to, and
- an instruction's ``type_filter`` payload names what it acts on.

Where the program carries no such evidence — Lightning Bolt and Fireball are
both a bare ``deal_damage``, differing only in text the instruction does not
record — :func:`derive_cast_target` returns None and the caller falls back to
``legality.py``. That set is the concrete backlog for the grammar: it shrinks as
lowering starts emitting target specs, and `tests/engine/test_targeting.py`
measures it rather than leaving it to assertion.

Every derivation is differentially tested against `legality.py` across the whole
pool, so the two can only agree.
"""

from __future__ import annotations

import re

# "Enchant creature", "Enchant land", ... — but NOT "Enchant creature card in a
# graveyard" (Animate Dead), which targets a graveyard card rather than a
# permanent on the battlefield. The negative lookahead is load-bearing: without
# it Animate Dead derives "creature" and the UI would offer battlefield
# creatures for a reanimation spell.
_ENCHANT_SUBJECTS = ("creature", "land", "artifact", "enchantment", "wall")
_ENCHANT_LINE = re.compile(
    rf"^enchant ({'|'.join(_ENCHANT_SUBJECTS)})\b(?! card)",
    re.MULTILINE,
)

# The whole-line form of the same scan, anchored at both ends so it claims a
# line that is *only* the attachment restriction.
_WHOLE_ENCHANT_LINE = re.compile(rf"^enchant ({'|'.join(_ENCHANT_SUBJECTS)})$")

# Reminder text, stripped exactly as mixins/stack_casting.aura_enchant_noun
# strips it — "Enchant creature (Target a creature as you cast this. …)" is the
# same restriction as a bare "Enchant creature", and two consumers of one line
# must not read it differently.
_REMINDER_TEXT = re.compile(r"\([^)]*\)")


def enchant_line_subject(line: str) -> str | None:
    """What *line* attaches to, if the whole line is an ``Enchant <subject>``
    restriction (CR 702.5) — otherwise ``None``.

    The single-line form of the :data:`_ENCHANT_LINE` scan
    :func:`derive_cast_target` runs over a card's whole normalized text, sharing
    its subject vocabulary so the two cannot drift. It exists so
    ``engine/grammar/registries.py`` can ask *this* module whether an Aura's
    attachment line is already accounted for, rather than copying the phrasing
    into the grammar where nothing would keep the copy honest.

    The trailing ``$`` is load-bearing: it keeps "Enchant creature card in a
    graveyard" (Animate Dead) out. Neither derivation here nor
    ``mixins/stack_casting.aura_enchant_noun`` implements that line — both
    deliberately refuse it, because it names a graveyard card rather than a
    battlefield permanent — so claiming it would report a reanimation Aura's
    attachment rule as handled while nothing handles it.
    """
    normalized = _REMINDER_TEXT.sub("", line).strip().lower().rstrip(".").strip()
    match = _WHOLE_ENCHANT_LINE.match(normalized)
    return match.group(1) if match is not None else None


# What an "Enchant <subject>" line means as a cast-time target kind. A Wall is a
# creature to the targeting layer; an Aura that enchants an enchantment is
# offered the general permanent picker.
_ENCHANT_SUBJECT_TO_KIND = {
    "creature": "creature",
    "wall": "creature",
    "land": "land",
    "artifact": "artifact",
    "enchantment": "permanent",
}

# An instruction's type_filter, as a target kind. Filters naming more than one
# type fall back to the general permanent picker, which then applies the filter.
_TYPE_FILTER_TO_KIND = {
    "artifact": "artifact",
    "creature": "creature",
    "land": "land",
    "enchantment": "permanent",
    "permanent": "permanent",
    "artifact_or_enchantment": "permanent",
}


def derive_cast_target(card, program) -> str | None:
    """The cast-time target kind of *card*, or None when the compiled program
    does not carry enough to say.

    None means "ask the fallback", never "this spell has no target" — those are
    different answers and conflating them would silently drop a target prompt.
    """
    enchant = _ENCHANT_LINE.search(program.normalized_text or "")
    if enchant is not None:
        return _ENCHANT_SUBJECT_TO_KIND.get(enchant.group(1))

    # Only a spell picks a target as it is cast. A permanent's instructions
    # belong to its abilities, which choose their own targets on activation —
    # reading a filter off those would make the UI demand a target for casting
    # Royal Assassin because its tap ability destroys a tapped creature.
    type_line = card.type_line.lower()
    if "instant" not in type_line and "sorcery" not in type_line:
        return None

    for instruction in program.instructions:
        described = _from_targets_payload(instruction.payload.get("targets"))
        if described is not None:
            return described
        type_filter = instruction.payload.get("type_filter")
        if type_filter:
            return _TYPE_FILTER_TO_KIND.get(type_filter)

    return None


def _from_targets_payload(targets) -> str | None:
    """The target kind from a grammar-lowered ``targets`` description.

    This is the evidence the legacy rules never recorded: it is what tells
    Lightning Bolt ("any target") apart from Earthbind ("target creature with
    flying") when both compile to a bare ``deal_damage``.
    """
    if not isinstance(targets, dict):
        return None
    if targets.get("kind") == "any":
        return "any"
    if targets.get("kind") == "player":
        return "player"
    if targets.get("kind") == "spell":
        # A spell on the stack, which the UI picks from a different zone than
        # any permanent — "stack" is legality.py's name for that picker.
        return "stack"
    if targets.get("kind") != "object":
        return None
    filt = targets.get("filter") or {}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # A targeted object with no type restriction is any permanent.
        return "permanent"
    return _TYPE_FILTER_TO_KIND.get(type_filter)
