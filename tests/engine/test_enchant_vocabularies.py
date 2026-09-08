"""The three tables that read an "Enchant <noun>" clause must know the same
nouns.

CR 702.5's enchant ability is read by three separate registries, in three
files, for three different questions:

* ``targeting._ENCHANT_NOUNS`` — the **claim**. It builds the regex
  ``enchant_line_subject`` matches, which is what tells the support gate and
  ``parse_coverage`` that the printed line is accounted for.
* ``targeting._ENCHANT_NOUN_TO_SPEC`` — the **picker**. It turns the clause
  into the target spec ``_enumerate_targets`` offers hosts from.
* ``mixins/stack/casting._ENCHANT_TARGET_MATCHERS`` — the **gate**. It answers
  "is this permanent a legal host", for the cast check (CR 601.2c), for
  ``auras.aura_attach_refusal`` and for the CR 704.5m sweep.

A noun in the first two and not the third used to be a **supported, deckable
Aura whose printed restriction nothing tested**: the matcher's fallback
answered True for a noun it had never seen, so the Aura went on anything. That
is the Roots class this repo has already paid for once — a shipped Aura
attachable to a creature its own line excluded — and it fails open, which is
wrong in the player's favour and silent.

The fallback now refuses instead of admitting, so the drift would show as an
Aura that attaches to nothing. This test is how it shows without a game.
"""

from __future__ import annotations

import pytest

from engine.mixins.stack.casting import (
    _ENCHANT_TARGET_MATCHERS,
    permanent_matches_enchant_noun,
)
from engine.models import Permanent
from engine.targeting import _ENCHANT_NOUNS, _ENCHANT_NOUN_TO_SPEC

from tests.helpers import _mk_creature_card


def test_the_claim_the_picker_and_the_gate_know_the_same_enchant_nouns():
    """One vocabulary in three files. The land subtypes come from the same
    catalog on both sides, so a mismatch here is a hand-written row that only
    got added twice.
    """
    claim = set(_ENCHANT_NOUNS)
    picker = set(_ENCHANT_NOUN_TO_SPEC)
    gate = set(_ENCHANT_TARGET_MATCHERS)

    assert claim == picker, "the claim and the picker disagree"
    assert claim == gate, "the claim and the gate disagree"


def test_every_shipped_auras_enchant_noun_has_a_matcher(catalog):
    """The same check asked of the pool rather than of the tables — a noun the
    regex admits by some other route (a colour word, a negation, a seat clause)
    still has to reach a row here once it has been split down to its head noun.
    """
    from engine.mixins.stack.casting import aura_enchant_noun
    from engine.oracle import compile_card_oracle
    from engine.targeting import (
        enchant_subject_colours,
        enchant_subject_keyword_exclusion,
        enchant_subject_seat,
    )

    def _heads(clause: str) -> list[str]:
        """The clause stripped to its noun(s), in the gate's own order: seat,
        negated subtype, keyword exclusion, colours, then the union split."""
        noun = enchant_subject_seat(clause)[0]
        if noun.startswith("non-") and " " in noun:
            noun = noun.split(" ", 1)[1]
        noun = enchant_subject_keyword_exclusion(noun)[0]
        noun = enchant_subject_colours(noun)[0]
        return [part.strip() for part in noun.split(" or ")]

    missing = []
    for card in catalog:
        noun = aura_enchant_noun(card)
        if noun is None or not compile_card_oracle(card).supported:
            continue
        for head in _heads(noun):
            if head not in _ENCHANT_TARGET_MATCHERS:
                missing.append((card.name, noun, head))
    assert missing == []


def test_an_unread_enchant_noun_refuses_every_host_rather_than_admitting_all():
    """The fallback's direction, which is the whole of what this round changed
    about it.

    Answering True for a noun nobody has read is a printed restriction enforced
    by nothing; answering False is an Aura that attaches to nothing, which one
    game makes obvious. The cost of the strict answer is nil, because a card
    whose noun is unread is **unsupported** one step earlier — its enchant line
    fails ``enchant_line_subject``'s vocabulary, so no player can deck it.
    """
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))

    assert permanent_matches_enchant_noun(bear, "creature")
    assert not permanent_matches_enchant_noun(bear, "equipment")
    assert not permanent_matches_enchant_noun(bear, "artifact or equipment")


def test_an_aura_printing_an_unread_noun_is_unsupported_and_says_which_line():
    """…and this is that earlier step, so the strict fallback is never the only
    thing standing between a player and a broken Aura."""
    from dataclasses import replace

    from engine.oracle import compile_card_oracle

    template = _mk_creature_card("Probe", 1, 1)
    aura = replace(
        template,
        type_line="Enchantment — Aura",
        oracle_text="Enchant Equipment\nEnchanted Equipment can't be equipped.",
    )

    program = compile_card_oracle(aura)

    assert not program.supported
    assert "enchant equipment" in (program.reason or "").lower()
