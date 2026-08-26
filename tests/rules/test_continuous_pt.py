"""CR 611.3a — continuous effects apply dynamically, so recomputing must be idempotent.

Static and conditional P/T effects are *derived*: every recompute clears the
channel they contribute to and rebuilds it from the current board. The
alternative — adding to a persistent bonus and subtracting it again next time —
requires every effect to record exactly what it contributed, and any mismatch
compounds, because CR 611.3a means the recompute runs constantly.

That is not hypothetical. Aspect of Wolf shipped with under-recorded stacking
(tests/regressions/test_batch17.py). These tests pin the general property
rather than the individual cards: refreshing repeatedly must not drift, and a
condition becoming false must remove its bonus without anything having to undo
it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _board(cards, arn, *, forests: int = 0):
    """A board with Kird Ape (+1/+2 while you control a Forest), a Giant
    Tortoise (+0/+2 while untapped), and *forests* Forests."""
    ape = Permanent(card=arn["Kird Ape"])
    tortoise = Permanent(card=arn["Giant Tortoise"])
    lands = [Permanent(card=cards["Forest"]) for _ in range(forests)]
    p1 = PlayerState(name="P1", battlefield=[ape, tortoise, *lands], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    return game, p1, ape, tortoise


@pytest.mark.cr("611.3a")
def test_repeated_recomputes_do_not_drift(cards, arn_by_name):
    """The property that matters: recomputing N times equals recomputing once."""
    game, _, ape, tortoise = _board(cards, arn_by_name, forests=1)

    game._recompute_continuous_effects()
    first = (ape.effective_power, ape.effective_toughness,
             tortoise.effective_power, tortoise.effective_toughness)

    for _ in range(25):
        game._recompute_continuous_effects()

    assert (ape.effective_power, ape.effective_toughness,
            tortoise.effective_power, tortoise.effective_toughness) == first


@pytest.mark.cr("611.3a")
def test_a_conditional_bonus_appears_and_disappears_with_its_condition(cards, arn_by_name):
    game, p1, ape, _ = _board(cards, arn_by_name, forests=0)

    game._recompute_continuous_effects()
    without_forest = (ape.effective_power, ape.effective_toughness)

    p1.battlefield.append(Permanent(card=cards["Forest"]))
    game._recompute_continuous_effects()
    with_forest = (ape.effective_power, ape.effective_toughness)
    assert with_forest[0] == without_forest[0] + 1
    assert with_forest[1] == without_forest[1] + 2

    # Removing the Forest must restore the original values exactly — nothing
    # has to remember what was added in order to take it back.
    p1.battlefield = [perm for perm in p1.battlefield if perm.card.name != "Forest"]
    game._recompute_continuous_effects()
    assert (ape.effective_power, ape.effective_toughness) == without_forest


@pytest.mark.cr("611.3a")
def test_a_state_dependent_bonus_tracks_the_state(cards, arn_by_name):
    """Giant Tortoise is bigger only while untapped, so tapping and untapping it
    must move the bonus with no bookkeeping.

    The sizes come from the card rather than being written in here: the point
    is that the bonus tracks the state and that untapping restores exactly what
    tapping removed, however large it is.
    """
    game, _, _, tortoise = _board(cards, arn_by_name)
    printed = tortoise.card.base_toughness

    game._recompute_continuous_effects()
    untapped = tortoise.effective_toughness
    assert untapped > printed, "the untapped bonus should apply"

    tortoise.tapped = True
    game._recompute_continuous_effects()
    assert tortoise.effective_toughness == printed

    tortoise.tapped = False
    game._recompute_continuous_effects()
    assert tortoise.effective_toughness == untapped


@pytest.mark.cr("611.3a")
def test_derived_bonuses_do_not_leak_into_the_counter_channel(cards, arn_by_name):
    """``power_bonus`` means counters and other permanent modifications. A
    continuous effect writing there is what created the compounding bug, so it
    must stay clean however many times the board is recomputed."""
    game, _, ape, tortoise = _board(cards, arn_by_name, forests=2)

    for _ in range(10):
        game._recompute_continuous_effects()

    for perm in (ape, tortoise):
        assert perm.power_bonus == 0, f"{perm.card.name} leaked into power_bonus"
        assert perm.toughness_bonus == 0, f"{perm.card.name} leaked into toughness_bonus"


@pytest.mark.cr("611.3a")
def test_counters_and_derived_bonuses_add_together(cards, arn_by_name):
    """A +1/+1 counter is not a continuous effect — it lives on the permanent.
    Both channels must apply."""
    game, _, ape, _ = _board(cards, arn_by_name, forests=1)

    game._recompute_continuous_effects()
    before = ape.effective_power

    ape.power_bonus += 3  # a counter, not an effect
    game._recompute_continuous_effects()
    assert ape.effective_power == before + 3


# ---------------------------------------------------------------------------
# The lord-buff channels. Two more derived channels answer to the same
# property, and one of them (the state-qualified buff) is read *outside* the
# recompute, so drift there would be invisible to the tests above.
# ---------------------------------------------------------------------------


def _lord_board(cards):
    """Crusade (unqualified anthem) and Castle (untapped-only) over one bear."""
    bear = Permanent(card=cards["Savannah Lions"])  # white, so Crusade reaches it
    p1 = PlayerState(
        name="P1",
        battlefield=[bear, Permanent(card=cards["Crusade"]), Permanent(card=cards["Castle"])],
        life=20,
    )
    p2 = PlayerState(name="P2", life=20)
    return Game(players=[p1, p2]), bear


@pytest.mark.cr("611.3a", "613.4c")
def test_repeated_recomputes_do_not_drift_for_lord_buffs(cards):
    game, bear = _lord_board(cards)

    game._recompute_continuous_effects()
    once = (bear.effective_power, bear.effective_toughness)
    assert once == (3, 4), "Crusade's +1/+1 and Castle's +0/+2 on a 2/1"

    for _ in range(25):
        game._recompute_continuous_effects()

    assert (bear.effective_power, bear.effective_toughness) == once


@pytest.mark.cr("611.3a")
def test_lord_buffs_do_not_leak_into_the_counter_channel(cards):
    game, bear = _lord_board(cards)

    for _ in range(10):
        game._recompute_continuous_effects()

    assert bear.power_bonus == 0 and bear.toughness_bonus == 0


@pytest.mark.cr("611.3a")
def test_a_qualified_lord_buff_does_not_accumulate_across_recomputes(cards):
    """The qualified channel is a dict keyed by qualifier, and its contributions
    are summed. Rebuilding it without clearing it first would add Castle's
    +0/+2 again on every pass — invisible while the creature is tapped, which is
    exactly when nobody is looking."""
    from engine.layer_bridge import QUALIFIED_BUFFS

    game, bear = _lord_board(cards)
    for _ in range(10):
        game._recompute_continuous_effects()

    assert bear.metadata[QUALIFIED_BUFFS] == {("untapped",): (0, 2)}


@pytest.mark.cr("611.3a", "611.3b", "613.1f")
def test_a_lord_granted_keyword_does_not_outlive_its_source(cards):
    """Layer 6's derived channel answers to the same invariant, but its symptom
    is different: the grant is a set, so re-adding it is idempotent and a
    missing clear shows up only when the source *leaves*. That is the assertion
    that makes clearing load-bearing, and repeating the recompute first is what
    makes sure the answer is not an artifact of the first pass."""
    from engine.keywords import DERIVED_GRANTS

    king = Permanent(card=cards["Goblin King"])
    goblin = Permanent(card=cards["Mons's Goblin Raiders"])
    p1 = PlayerState(name="P1", battlefield=[king, goblin], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    for _ in range(10):
        game._recompute_continuous_effects()

    assert goblin.metadata[DERIVED_GRANTS] == ["mountainwalk"]
    assert goblin.has_keyword("mountainwalk")

    p1.battlefield.remove(king)
    game._recompute_continuous_effects()

    assert not goblin.metadata.get(DERIVED_GRANTS)
    assert not goblin.has_keyword("mountainwalk")


# ---------------------------------------------------------------------------
# CR 613.4c — a bonus whose size is a repetition count (round 21)
# ---------------------------------------------------------------------------


def _plain_aura(name: str):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Enchantment - Aura",
        oracle_text="Enchant creature", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment - Aura"},
    )


def _per_each_creature(name: str, text: str):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{3}{G}", cmc=4.0, type_line="Creature - Beast",
        oracle_text=text, colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Beast",
             "power": "1", "toughness": "1"},
    )


@pytest.mark.cr("613.4c", "611.3a")
def test_a_per_each_bonus_is_the_printed_number_times_the_count():
    """"…gets +2/+2 for each Aura attached to it." (Rabid Wombat.)

    Written with an invented card printed +1/+3 rather than +2/+2, because the
    two halves are scaled independently — a version folding the multiplier into
    the shared count spec passes for Rabid Wombat's symmetrical numbers and
    gets this one wrong in both directions.
    """
    from engine.auras import attach_aura, detach_aura

    beast = Permanent(card=_per_each_creature(
        "Invented Beast", "This creature gets +1/+3 for each Aura attached to it."
    ))
    auras = [Permanent(card=_plain_aura(f"Aura {n}")) for n in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[beast, *auras], life=20),
        PlayerState(name="P2", life=20),
    ])
    game._refresh_dynamic_creatures()
    assert (beast.effective_power, beast.effective_toughness) == (1, 1)

    attach_aura(auras[0], beast)
    game._refresh_dynamic_creatures()
    assert (beast.effective_power, beast.effective_toughness) == (2, 4)

    attach_aura(auras[1], beast)
    game._refresh_dynamic_creatures()
    assert (beast.effective_power, beast.effective_toughness) == (3, 7)

    detach_aura(auras[1], beast)
    game._refresh_dynamic_creatures()
    assert (beast.effective_power, beast.effective_toughness) == (2, 4)


@pytest.mark.cr("613.4c")
def test_a_per_each_bonus_counts_attachments_whoever_controls_them():
    """"Each Aura attached to it" names no controller. What is attached to a
    permanent is recorded on that permanent, which is why the count is not a
    battlefield scan scoped to one seat — an opponent's Pacifism on your
    creature is attached to your creature."""
    from engine.auras import attach_aura

    beast = Permanent(card=_per_each_creature(
        "Invented Beast", "This creature gets +1/+3 for each Aura attached to it."
    ))
    theirs = Permanent(card=_plain_aura("Their Aura"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[beast], life=20),
        PlayerState(name="P2", battlefield=[theirs], life=20),
    ])
    attach_aura(theirs, beast)
    game._refresh_dynamic_creatures()

    assert (beast.effective_power, beast.effective_toughness) == (2, 4)


@pytest.mark.cr("613.4c")
def test_a_per_each_bonus_counts_only_what_the_noun_phrase_names():
    """A non-Aura enchantment on the board is not attached to anything, and an
    Aura attached to something else is not attached to *it*."""
    from engine.auras import attach_aura

    beast = Permanent(card=_per_each_creature(
        "Invented Beast", "This creature gets +1/+3 for each Aura attached to it."
    ))
    other = Permanent(card=_per_each_creature("Invented Other", ""))
    elsewhere = Permanent(card=_plain_aura("Elsewhere"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[beast, other, elsewhere], life=20),
        PlayerState(name="P2", life=20),
    ])
    attach_aura(elsewhere, other)
    game._refresh_dynamic_creatures()

    assert (beast.effective_power, beast.effective_toughness) == (1, 1)
