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


@pytest.mark.cr("700.4")
def test_700_4_dies_is_the_short_spelling_of_the_same_event():
    """"The term **dies** means 'is put into a graveyard from the
    battlefield.'"

    So a printed noun phrase means the same thing in front of either wording,
    and the two must produce the *same condition kind with the same payload* —
    otherwise a card printing the rule's own shorthand would reach a different
    dispatcher (or, as it did, none at all). Asserted as an equality between the
    two spellings rather than as "the short one works", because the failure this
    guards is the two drifting.
    """
    from engine.oracle import trigger_condition_of_line

    long_form, _ = trigger_condition_of_line(
        "Whenever a creature with shadow is put into a graveyard from the "
        "battlefield, put a +1/+1 counter on this creature."
    )
    short_form, _ = trigger_condition_of_line(
        "Whenever a creature with shadow dies, put a +1/+1 counter on this "
        "creature."
    )

    assert long_form is not None and short_form is not None
    assert short_form.kind == long_form.kind == "permanent_dies"
    assert short_form.payload == long_form.payload == {
        "dying_filter": {"type_filter": "creature", "with_keywords": ["shadow"]}
    }


@pytest.mark.cr("615.8", "615.9", "702.28a")
def test_615_9_a_keyword_narrowed_shield_rechecks_the_source():
    """Circle of Protection: Shadow, as a rule rather than as a card.

    CR 615.8 gives the shield its one instance and CR 615.9 makes the recorded
    property a **recheck** at damage time. A shield that snapshotted "these are
    the shadow creatures" when it was armed would pass every positive test and
    fail the third assertion here — and the pool has no other card that can
    change a source's recorded property between the arming and the damage,
    which is why shadow is where this rule finally gets exercised.
    """
    from engine.keywords import grant_keyword, remove_keyword
    from engine.shields import add_shield, make_source_subject_shield
    from tests.helpers import _damage_dealt

    shadowy = _bear("Shade Bear", "Shadow", keywords=("Shadow",))
    ground = _bear("Ground Bear")
    game, p0, p1 = _duel([], [shadowy, ground])
    shadow_source, ordinary_source = p1.battlefield

    described = {"type_filter": "creature", "with_keywords": ["shadow"]}
    add_shield(p0, make_source_subject_shield(described, 0, "Test Circle"))

    # An ordinary creature is not the described source.
    assert _damage_dealt(game, p0, 3, source=ordinary_source, combat=True) == 3

    # The described one is, and one instance is all the shield holds.
    assert _damage_dealt(game, p0, 2, source=shadow_source, combat=True) == 0
    assert _damage_dealt(game, p0, 2, source=shadow_source, combat=True) == 2

    # And the recheck, both ways: a source that gains the keyword after the
    # shield was armed matches, and one that loses it stops matching.
    add_shield(p0, make_source_subject_shield(described, 0, "Test Circle"))
    grant_keyword(ordinary_source, "shadow", duration="end_of_turn")
    assert _damage_dealt(game, p0, 3, source=ordinary_source, combat=True) == 0

    add_shield(p0, make_source_subject_shield(described, 0, "Test Circle"))
    remove_keyword(shadow_source, "shadow", duration="end_of_turn")
    assert _damage_dealt(game, p0, 2, source=shadow_source, combat=True) == 2


@pytest.mark.cr("509.1b")
def test_509_1b_a_block_narrowing_refuses_a_word_that_is_not_a_keyword():
    """The row next door to the one this group added, and the same hole.

    "This creature can block only creatures with **flying**" (Shacklegeist,
    Cloud Elemental, Cloud Djinn) captured its keyword as `[a-z]+` and checked
    it against nothing. The enforcement asks ``Game._has_keyword``, which
    answers False for a word no card carries — so an invented creature printed
    "can block only creatures with blorb" compiled **supported** and could then
    block nothing at all.

    That is the narrowing direction rather than the widening one, which is why
    no card in the pool exposed it: all four printings say "flying". It is the
    same shape SET_PLAYBOOK's round 7 found on a whitelist that accepted
    "creatures with three heads", and it is caught the same way — by writing
    the refusing gate's refusal test rather than only its positive cases.

    The gate is the printed keyword **catalog**, not `IMPLEMENTED_KEYWORDS`: the
    question is what the enforcement can answer, and `_has_keyword` reads a
    keyword off layer 6 whether or not this engine implements the behaviour
    behind it. Shadowstorm hit exactly the shadow creatures for a whole set
    before shadow was implemented, for exactly that reason.
    """
    from engine.combat_restrictions import combat_restriction_for
    from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS

    for keyword in ("flying", "shadow"):
        restriction = combat_restriction_for(
            f"this creature can block only creatures with {keyword}"
        )
        assert restriction is not None, keyword
        assert restriction.payload == {"required_keyword": keyword}

    # A real keyword the engine does not implement still reads: `_has_keyword`
    # can answer it, so the restriction is enforceable as printed.
    assert "ward" not in IMPLEMENTED_KEYWORDS
    assert combat_restriction_for(
        "this creature can block only creatures with ward"
    ) is not None

    # A word that is not a keyword ability at all refuses the whole line.
    assert combat_restriction_for(
        "this creature can block only creatures with blorb"
    ) is None
    assert not compile_card_oracle(_bear(
        "Test Blorb Blocker",
        "This creature can block only creatures with blorb.",
    )).supported


@pytest.mark.cr("608.2b", "115.1c")
def test_w1g1_the_removal_still_reaches_a_printed_planeswalker(catalog_by_name):
    """The reason the predicate was unconditional in the first place, kept.

    Soul Sear prints "target creature **or planeswalker**", which lowers
    `type_filter` as a *list* — so the fix reads the printed type off the
    payload rather than asking "is it a creature?", and both halves of that
    card's target line still resolve. A hardcoded creature floor would have
    declined the planeswalker, which is the direction this whole family of
    fixes exists to avoid.
    """
    sear = catalog_by_name["Soul Sear"]
    ugin = _nosick(Permanent(card=catalog_by_name["Ugin, the Spirit Dragon"]))
    p0 = PlayerState(name="P0", battlefield=[ugin], life=20, hand=[sear],
                     library=[catalog_by_name["Mox Pearl"]] * 4)
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game._sync_control()

    game.cast_from_hand(0, "Soul Sear", target_permanent_index=0,
                        target_player_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    assert any(
        "Ugin, the Spirit Dragon loses indestructible" in line
        for line in game.log
    )
