"""The deletion criterion for ``engine/parsing/``, as a ratchet.

``engine/parsing/`` is the legacy ``@parse_rule`` registry, being deleted. The
question that decides when it *can* be deleted is not "how much does the grammar
parse" but "what would change if the rules were gone tomorrow" — so this
compiles the whole pool with them stubbed out and compares, card by card,
against the program the compiler produces today.

Two lists, and both only ever shrink:

* :data:`LOSES_SUPPORT` — cards the legacy rules are still the only reader of.
  Each entry names the code that is missing, because a card here is a card the
  deletion would break.
* :data:`CHANGES_SHAPE` — cards that stay supported but compile to a different
  instruction list. Every one of these is the *whole-text fallback* (the branch
  in ``_compile_card_oracle`` that collapses a card to one string and keeps the
  first rule matching it) inventing an instruction for a sentence the engine
  implements elsewhere. Each entry names the code that really carries the line,
  so "nothing dispatches this" is a claim on the record rather than a shrug.

An entry that stops diverging fails the test, which is what keeps the lists
honest as the migration finishes.
"""

from __future__ import annotations

import pytest

import engine.oracle as oracle
from engine.card_loader import load_catalog


# card -> the code that would have to exist for the deletion not to lose it.
LOSES_SUPPORT: dict[str, str] = {
    "Metamorphosis": (
        "engine/handlers/mana.py has no handler that adds X mana of a "
        "player-chosen colour sized by a sacrificed creature's mana value. The "
        "legacy rule hands this card *Sacrifice*'s instruction "
        "(`sacrifice_creature_for_black_mana`, which adds {B} per mana value), "
        "so hooking that reading would enshrine the wrong effect rather than "
        "preserve the right one — the same refusal Black Lotus's three-mana "
        "any-colour line got, for the same reason."
    ),
}

# card -> the instruction the whole-text fallback invents, and what really runs
# the line it was invented from.
CHANGES_SHAPE: dict[str, str] = {
    "Fastbond": (
        "`deal_damage`: the land-drop damage is derived from the card's own text "
        "by engine/land_play_allowance.py and applied by the land-drop path. "
        "Nothing reads a `deal_damage` on a non-Aura enchantment's mirror."
    ),
    "Island Sanctuary": (
        "`draw_controller_cards`: the card skips a draw, it does not take one. "
        "Its behaviour is card_hooks.DRAW_STEP_MODIFIERS, read by "
        "engine/phases/draw_step.py."
    ),
    "Jihad": (
        "`sacrifice_self`: read only through `matching_triggers` with a "
        "`no_islands`/`no_lands` condition (engine/mixins/game_ending.py), and "
        "Jihad's condition is in no trigger table. The anthem it shares the card "
        "with is now derived by engine/lord_buffs.py instead of by the fallback."
    ),
    "Lich": (
        "`player_loses_game`: an instruction on an enchantment's mirror, which "
        "nothing resolves. Lich's three real behaviours are the CR 614 "
        "interceptor in engine/replacements.py, the 704.5a exemption in "
        "engine/mixins/game_ending.py and the damage-sacrifice in "
        "engine/mixins/effects.py, all keyed on its oracle text."
    ),
}


@pytest.fixture(scope="module")
def compiled_pool():
    """Every card's program with, and without, the ``@parse_rule`` registry."""
    cards = list(load_catalog())

    def compile_all():
        oracle._compile_card_oracle.cache_clear()
        return {card.name: oracle.compile_card_oracle(card) for card in cards}

    with_legacy = compile_all()

    saved = (oracle.parse_primary_instruction, oracle.parse_static_coeffects)
    oracle.parse_primary_instruction = lambda text, activated=False: (None, "")
    oracle.parse_static_coeffects = lambda *args, **kwargs: ()
    try:
        without_legacy = compile_all()
    finally:
        (oracle.parse_primary_instruction, oracle.parse_static_coeffects) = saved
        oracle._compile_card_oracle.cache_clear()

    return with_legacy, without_legacy


def _shape(program):
    return (
        program.supported,
        tuple(i.kind for i in program.instructions),
        tuple(
            (a.supported, a.instruction.kind if a.instruction else None)
            for a in program.activated_abilities
        ),
        tuple(
            (t.condition.kind, t.instruction.kind if t.instruction else None)
            for t in program.triggered_abilities
        ),
        tuple(program.static_lines),
    )


def test_no_card_outside_the_list_loses_support(compiled_pool):
    with_legacy, without_legacy = compiled_pool
    lost = sorted(
        name
        for name, program in with_legacy.items()
        if program.supported and not without_legacy[name].supported
    )

    assert lost == sorted(LOSES_SUPPORT), (
        "deleting engine/parsing/ would change which cards are supported. Add a "
        "production, a card_hooks entry, or an entry to LOSES_SUPPORT naming the "
        f"code that is missing: {lost}"
    )


def test_no_card_outside_the_list_changes_shape(compiled_pool):
    with_legacy, without_legacy = compiled_pool
    changed = sorted(
        name
        for name, program in with_legacy.items()
        if _shape(program) != _shape(without_legacy[name])
    )
    expected = sorted(set(LOSES_SUPPORT) | set(CHANGES_SHAPE))

    assert changed == expected, (
        "deleting engine/parsing/ would change these cards' compiled programs; "
        f"the lists in this module say it would change these: {changed} vs {expected}"
    )


def test_every_listed_card_still_diverges(compiled_pool):
    """A stale entry is a claim nobody is checking any more — the ratchet only
    tightens."""
    with_legacy, without_legacy = compiled_pool
    stale = sorted(
        name
        for name in (*LOSES_SUPPORT, *CHANGES_SHAPE)
        if _shape(with_legacy[name]) == _shape(without_legacy[name])
    )

    assert not stale, f"these no longer change without the legacy rules; delete them: {stale}"


def test_every_listed_card_explains_itself():
    for name, reason in (*LOSES_SUPPORT.items(), *CHANGES_SHAPE.items()):
        assert len(reason) > 60, f"{name} needs a real explanation"
        assert "engine/" in reason, f"{name} must name the code involved"
