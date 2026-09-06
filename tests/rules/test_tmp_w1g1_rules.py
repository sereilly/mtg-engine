"""CR 702.28 — Shadow, and the block restriction it is.

Tempest wave 1, group 1. Shadow is the first evasion ability in this engine
whose restriction runs in **both** directions, and that is the whole reason
these tests exist as rules tests rather than as per-card ones:

    702.28b A creature with shadow can't be blocked by creatures without
    shadow, **and a creature without shadow can't be blocked by creatures with
    shadow**.

Flying, fear and landwalk are each one prohibition, so each is enforced as
``attacker_has_x and not blocker_can_answer_x``. A reading of that shape
applied to shadow keeps the evasion and drops the drawback — the Soltari
creatures become strictly better than the card says, silently and in the
player's favour, which is the failure mode this repo names as the one worth
building guards for. The second half is therefore tested first-class, and
against a creature that *has* shadow being unable to block, not merely against
a creature without it being unable to block one that has it.

CR 702.28c ("multiple instances are redundant") is exercised through the grant:
a creature that already has shadow and is granted it again is still exactly one
creature with shadow, and the restriction is not doubled or cancelled.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _bear(name: str, text: str = "", keywords=()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
        oracle_text=text, colors=("G",), color_identity=("G",),
        keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": "2", "toughness": "2", "keywords": list(keywords)},
    )


def _duel(p0_cards, p1_cards):
    p0 = PlayerState(name="P0"); p1 = PlayerState(name="P1")
    for card in p0_cards:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_cards:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1


@pytest.mark.cr("702.28a", "702.28b", "509.1b")
def test_702_28b_shadow_restricts_both_creatures_not_only_the_attacker():
    """The whole sentence, all four pairings, on invented cards.

    Invented rather than Soltari, deliberately: shadow is a **template**, and a
    test naming only Tempest's creatures would pass against an implementation
    that keyed on their names or their tribes. What the rule is about is the
    keyword, so the keyword is what the fixture carries.
    """
    shadowy = _bear("Shade Bear", "Shadow", keywords=("Shadow",))
    ground = _bear("Ground Bear")
    game, p0, p1 = _duel([shadowy, ground], [shadowy, ground])
    shadow_attacker, ground_attacker = p0.battlefield
    shadow_blocker, ground_blocker = p1.battlefield

    # Half one: a creature with shadow can't be blocked by creatures without it.
    assert not game._can_block_attacker(ground_blocker, shadow_attacker)
    assert game._can_block_attacker(shadow_blocker, shadow_attacker)

    # Half two, the one a flying-shaped reading loses: a creature **with**
    # shadow can't block a creature without it. The Soltari creatures are meant
    # to be unable to hold the ground, and an engine that only implemented the
    # evasion would let them.
    assert not game._can_block_attacker(shadow_blocker, ground_attacker), (
        "CR 702.28b's second prohibition is missing: a shadow creature blocked "
        "a creature without shadow"
    )
    assert game._can_block_attacker(ground_blocker, ground_attacker)


@pytest.mark.cr("702.28b", "613.1f")
def test_702_28b_reads_shadow_off_layer_6_not_off_the_printed_card():
    """A granted shadow restricts blocks and a removed one stops restricting.

    Dauthi Embrace and Shadow Rift grant it; Reality Anchor takes it away. All
    three go through the ordinary layer-6 channels, so the question this asserts
    is that the block gate asks the *layer system* rather than the printed
    keywords field — the bug class ``tests/engine/test_layer_reads.py`` guards,
    and the one the fear check beside it was written into and never noticed for
    want of a card.
    """
    from engine.keywords import grant_keyword, remove_keyword

    ground = _bear("Ground Bear")
    shadowy = _bear("Shade Bear", "Shadow", keywords=("Shadow",))
    game, p0, p1 = _duel([ground], [ground, shadowy])
    attacker = p0.battlefield[0]
    blocker, shadow_blocker = p1.battlefield

    assert game._can_block_attacker(blocker, attacker)

    grant_keyword(attacker, "shadow", duration="end_of_turn")
    assert game._has_keyword(attacker, "shadow")
    assert not game._can_block_attacker(blocker, attacker)
    assert game._can_block_attacker(shadow_blocker, attacker)

    # And the removal, off the printed creature: Reality Anchor's sentence.
    remove_keyword(shadow_blocker, "shadow", duration="end_of_turn")
    assert not game._has_keyword(shadow_blocker, "shadow")
    assert game._can_block_attacker(shadow_blocker, attacker) is False, (
        "the attacker still has shadow, so a blocker that just lost it may not "
        "block"
    )
    remove_keyword(attacker, "shadow", duration="end_of_turn")
    assert game._can_block_attacker(shadow_blocker, attacker), (
        "with shadow gone from both, the pairing is an ordinary block"
    )


@pytest.mark.cr("702.28c")
def test_702_28c_a_second_instance_of_shadow_is_redundant():
    """"Multiple instances of shadow on the same creature are redundant."

    Soltari Emissary can activate its own grant twice, and Dauthi Embrace can
    target a Dauthi creature that already has shadow. Neither doubles anything
    and neither cancels: the creature has shadow, once.
    """
    from engine.keywords import grant_keyword

    shadowy = _bear("Shade Bear", "Shadow", keywords=("Shadow",))
    ground = _bear("Ground Bear")
    game, p0, p1 = _duel([shadowy], [ground, shadowy])
    attacker = p0.battlefield[0]
    ground_blocker, shadow_blocker = p1.battlefield

    grant_keyword(attacker, "shadow", duration="end_of_turn")
    grant_keyword(attacker, "shadow", duration="end_of_turn")

    assert game._has_keyword(attacker, "shadow")
    assert not game._can_block_attacker(ground_blocker, attacker)
    assert game._can_block_attacker(shadow_blocker, attacker)


@pytest.mark.cr("609.4", "702.28b", "509.1b")
def test_609_4_can_block_as_though_it_had_shadow_lifts_exactly_one_half():
    """"This creature can block creatures with shadow as though it had shadow."

    CR 609.4: an "as though" effect applies **only** to the stated effect. So
    Heartwood Dryad does not gain shadow — it gains permission to block one kind
    of creature it otherwise could not, and keeps every ordinary block it
    already had. Modelling the line as a shadow *grant* would be a shorter
    implementation of a different card: the Dryad would stop being able to block
    the ground creatures it is printed to stop, by CR 702.28b's other half.

    Invented cards, because the sentence is a template — the keyword is payload
    in `engine/combat_restrictions.py`, not part of the instruction kind.
    """
    watcher = _bear(
        "Test Watcher",
        "This creature can block creatures with shadow as though it had shadow.",
    )
    shadowy = _bear("Shade Bear", "Shadow", keywords=("Shadow",))
    ground = _bear("Ground Bear")

    program = compile_card_oracle(watcher)
    assert program.supported
    assert [i.kind for i in program.instructions] == ["can_block_as_though_it_had"]
    assert program.instructions[0].payload == {"keyword": "shadow"}

    game, p0, p1 = _duel([shadowy, ground], [watcher])
    shadow_attacker, ground_attacker = p0.battlefield
    blocker = p1.battlefield[0]

    assert game._can_block_attacker(blocker, shadow_attacker)
    assert game._can_block_attacker(blocker, ground_attacker), (
        "the permission is 'as though', not a grant: the blocker must keep the "
        "ordinary blocks it already had"
    )
    assert not game._has_keyword(blocker, "shadow"), (
        "CR 609.4 — nothing about the creature's abilities changed"
    )


@pytest.mark.cr("609.4")
def test_609_4_the_as_though_line_refuses_a_keyword_nothing_enforces():
    """The refusing half of the gate above, written before trusting it.

    The row captures the keyword twice and both halves must name the same
    ability, and the word has to be one the blockers step actually consults.
    A line admitted for an ability nothing enforces is a card reported
    supported for a permission that never applies — the widening direction
    `engine/combat_restrictions.py` exists to refuse in.
    """
    from engine.combat_restrictions import combat_restriction_for

    assert combat_restriction_for(
        "this creature can block creatures with shadow as though it had shadow"
    ) is not None
    # Halves that disagree: not a card this table has ever seen.
    assert combat_restriction_for(
        "this creature can block creatures with shadow as though it had flying"
    ) is None
    # A word the shadow check does not read.
    assert combat_restriction_for(
        "this creature can block creatures with ward as though it had ward"
    ) is None
    assert compile_card_oracle(_bear(
        "Test Refusal",
        "This creature can block creatures with ward as though it had ward.",
    )).supported is False
