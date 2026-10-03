"""The printed word "another" reaches the payload, pool-wide.

CR 113.7 makes the source of a triggered ability the object whose ability
triggered, and a sentence that says "**another** target ..." is a sentence that
excludes it. The word is read by the noun parser
(``references.parse_target_spec`` records it as
``TargetSpec.distinct_from_prior``, ``nouns.parse_object_filter`` as
``ObjectFilter.other_than_source``) and it was being *dropped* on one route: the
graveyard-to-hand return, whose gate for narrowings it cannot honour
(``_reads_no_return_restriction``) asks the **filter** and so never saw a word
the parser had put on the **spec**.

Junk Diver -- "when this creature dies, return another target artifact card from
your graveyard to your hand" -- therefore returned itself out of an otherwise
empty graveyard. The behaviour regression is in
``tests/regressions/test_printed_another_is_not_dropped.py``; this file is the
census that says no other card in either manifest role is in the same state.
"""

from __future__ import annotations

import re

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import compile_line
from engine.grammar.ast import ObjectFilter, TargetSpec
from engine.grammar.lowering.returns import subject_names_another
from engine.handlers._common import excluded_graveyard_slot
from engine.models import CardDefinition
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card

#: The payload keys that *are* an exclusion, one printed shape each.
#:
#: There are two rules behind the one word and both are represented, because a
#: card may print it for either. "Another target creature" with no earlier
#: choice in the sentence excludes the ability's own source (CR 113.7) and
#: lowers to an identity key; the same words after a first "target" forbid the
#: repeat CR 115.3 would otherwise allow and lower to ``distinct``. Which of the
#: two a sentence means is ``lowering/_targets.py``'s decision, not this test's
#: -- what this asserts is that *some* reader took the word.
_EXCLUSION_KEYS = frozenset({
    # CR 113.7's source, by identity, against a permanent
    # (``subject_filters.subject_matches``).
    "exclude_self",
    # ...and against a **card in a graveyard**, where the exclusion is a slot
    # rather than a characteristic
    # (``handlers/_common.excluded_graveyard_slot``).
    "exclude_source_card",
    # CR 115.3/601.2c's distinctness over a several-slot announcement.
    "distinct",
    # The Aura spellings: the host the Aura is already on (Crown of the Ages,
    # Enchantment Alteration) and the creature the Aura's own trigger makes the
    # biter (Farrel's Mantle). Different objects from the ability's source,
    # which is the Aura itself and never a legal answer to "another creature".
    "exclude_relative_host", "exclude_attached", "exclude_biter",
})


def _payload_keys(node) -> set[str]:
    """Every exclusion key set truthily anywhere in a compiled instruction tree,
    plus the one *quantifier* that carries a distinctness instead of a key."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _EXCLUSION_KEYS and value:
                found.add(key)
            # "1 damage to any target, 2 damage to **another** target, and 3 to
            # a third target" (Cone of Flame). CR 601.2d's divided announcement
            # is distinct by construction -- every target must receive at least
            # one of what is divided -- so the restriction lives in the picker
            # rather than as a payload key, and this is the honest way to count
            # it.
            if key == "quantifier" and value == "divided":
                found.add("divided")
            found |= _payload_keys(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            found |= _payload_keys(item)
    elif hasattr(node, "payload"):
        found |= _payload_keys(node.payload)
    return found


def _program_exclusions(card: CardDefinition) -> set[str]:
    program = compile_card_oracle(card)
    found: set[str] = set()
    for entry in (
        *program.instructions,
        *program.activated_abilities,
        *program.triggered_abilities,
    ):
        instruction = entry if hasattr(entry, "payload") else entry.instruction
        found |= _payload_keys(instruction)
    return found


def _cards_printing_another_target() -> list[CardDefinition]:
    """Both manifest roles, because a measured set is exactly where this was
    found -- Junk Diver is Urza's Destiny's, read at its promotion gate.

    Scoped to "another **target**" rather than to the bare word, and that is the
    whole of what makes this census unambiguous. "As long as you control another
    creature" (Bronze Horse) is a condition, "when you play another land" (City
    of Traitors) a trigger condition, "sacrifice another creature" (Hobblefiend)
    a cost, and "replacing all instances of one color word with another"
    (Magical Hack) is not about an object at all -- each of those has its own
    reader and none of them writes a target payload. Where the word stands in
    front of "target" it narrows the object an effect acts on, and nothing else
    can be meant.
    """
    return sorted(
        (
            card
            for card in load_cards(manifest_set_paths(include_measured=True))
            if re.search(r"\banother target\b", card.oracle_text or "", re.I)
        ),
        key=lambda card: card.name,
    )


def test_every_card_printing_another_target_carries_the_exclusion():
    """The word is never merely consumed.

    A dropped narrowing is the one direction this engine must never fail in: the
    effect reaches a strictly larger set than the card prints, and nothing
    anywhere says so -- the card compiles supported, every guard is green, and
    the only witness is the board.

    Scoped to **supported** cards, because a refused line has not consumed the
    word -- it has declined the whole sentence, which is the outcome this file
    wants for a word no reader can honour yet. Prophecy's Withdraw is the case
    that drew the line: "Then return another target creature ... unless its
    controller pays {1}" refuses in the lowering with "a printed 'another
    target' in a multi-clause sentence needs a lowering with a slot per
    clause", so it reached this census as a card carrying *no* program for
    that line and read as a drop. The census names it unsupported with that
    reason; once it compiles, it is in scope here like every other card.
    """
    dropped = [
        card.name
        for card in _cards_printing_another_target()
        if compile_card_oracle(card).supported and not _program_exclusions(card)
    ]
    assert dropped == [], (
        'these cards print "another target" and their compiled program carries '
        f"no exclusion at all: {dropped}"
    )


def test_the_census_is_not_empty():
    """A census that found nothing would pass the test above for ever.

    The count is not asserted -- a new set may print the word -- but its being
    non-zero is what says the search still matches something.
    """
    assert len(_cards_printing_another_target()) >= 18


# ---------------------------------------------------------------------------
# The graveyard exclusion, one key at a time
# ---------------------------------------------------------------------------


def _card(name: str) -> CardDefinition:
    return _mk_card(name, "{1}", "Artifact", "")


def test_the_graveyard_exclusion_takes_the_slot_the_source_sits_in():
    source = _card("Junk Diver")
    graveyard = [_card("Ornithopter"), source]

    assert excluded_graveyard_slot(
        {"exclude_source_card": True}, graveyard, source
    ) == 1


def test_it_takes_one_slot_and_not_every_copy_of_the_card():
    """``load_cards`` dedupes by ``oracle_id``, so two copies of one card in one
    graveyard are literally one ``CardDefinition`` object -- the residual
    :class:`engine.game_types.GraveyardTarget` documents. A *per-card* exclusion
    would take both away, which is the card doing less than it says: "another
    target artifact card" with a second Junk Diver in the pile really can return
    that second one."""
    source = _card("Junk Diver")

    assert excluded_graveyard_slot(
        {"exclude_source_card": True}, [source, source], source
    ) == 0


def test_it_excludes_nothing_when_the_sentence_printed_no_such_word():
    source = _card("Raise Dead")
    assert excluded_graveyard_slot({}, [source], source) is None


def test_it_excludes_nothing_without_a_source_to_compare_against():
    """For an *exclusion* the safe answer with no source is "exclude nothing":
    the alternative would be to withhold from the caster a card the printed
    sentence lets them name."""
    assert excluded_graveyard_slot(
        {"exclude_source_card": True}, [_card("Ornithopter")], None
    ) is None


def test_it_excludes_nothing_when_no_copy_of_the_source_is_in_the_pile():
    """The source may have left the graveyard between the announcement and the
    resolution -- Sylvan Hierophant exiles itself first -- and then there is no
    slot to exclude."""
    assert excluded_graveyard_slot(
        {"exclude_source_card": True}, [_card("Ornithopter")], _card("Junk Diver")
    ) is None


# ---------------------------------------------------------------------------
# What refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    # A reanimation: the handler puts the card onto the battlefield off a fixed
    # payload and has nowhere to read a slot exclusion.
    "Return another target creature card from your graveyard to the battlefield.",
    # The several-card branch: its handler resolves a list of slots through
    # ``_resolve_graveyard_slots``, which reads a per-card predicate.
    "Return up to two other target creature cards from your graveyard to your hand.",
])
def test_a_graveyard_return_that_cannot_read_the_word_refuses_the_line(line):
    """Loud rather than silent, which is this engine's first standing invariant.

    No card in either manifest role prints either shape; what the refusal buys
    is that the *next* one is reported unsupported naming its clause instead of
    quietly resolving without the restriction.
    """
    compiled = compile_line(line)
    assert not compiled.usable, f"{line!r} lowered with the word unread"


def test_both_spellings_of_the_word_reach_the_same_answer():
    """"Another target creature" puts the word on the ``TargetSpec``; "other
    target creature" and "target creature other than this creature" put it on
    the ``ObjectFilter``. One printed restriction, so one reader."""
    assert not subject_names_another(
        TargetSpec("target", ObjectFilter(), targeted=True)
    )
    assert subject_names_another(
        TargetSpec("target", ObjectFilter(), targeted=True, distinct_from_prior=True)
    )
    assert subject_names_another(
        TargetSpec("target", ObjectFilter(other_than_source=True), targeted=True)
    )
