"""A steal spent on the object an earlier step named is aimed across the table.

"Untap target creature and gain control of it until end of turn. That
creature gains haste until end of turn." The target rides the untap alone,
and ``ai_target_sides.ability_target_side`` read only the steps that carry a
target — so the untap made the ability "you", and an AI seat (or any seat
nobody asks, ``_default_trigger_target_side``) borrowed its **own** creature:
Bringer of the Red Dawn's upkeep trigger took the Bringer itself in a seeded
5DN game, and Overtaker's activation (Mercadian Masques) was aimed the same
way. The spell reading (``_spell_object_target_steps``) already read the
steal; the ability reading now does too, for a control change alone.

Measured over both manifest roles before the change: fifteen abilities would
have changed side had every step spent on the earlier target been read, and
two of the flips would have been wrong (Sandals of Abdallah's and War Barge's
islandwalk, a gift whose delayed destroy is the price) — so only the steal is
read. Validated backwards: on the tree before the change the first test
reads "you" for both abilities.
"""

from engine.ai_target_sides import ability_target_side
from engine.oracle import compile_card_oracle


def _abilities(card):
    program = compile_card_oracle(card)
    return [
        ability.instruction
        for ability in (*program.activated_abilities, *program.triggered_abilities)
        if ability.instruction is not None
    ]


def test_an_untap_and_steal_is_aimed_at_the_opponents_creature(set_pool):
    red = set_pool("5DN")["Bringer of the Red Dawn"]
    overtaker = set_pool("MMQ")["Overtaker"]

    assert [ability_target_side(step) for step in _abilities(red)
            if "gain_control_until_eot" in repr(step)] == ["opponent"]
    assert [ability_target_side(step) for step in _abilities(overtaker)] == ["opponent"]


def test_a_gift_with_a_delayed_price_stays_on_its_own_board(set_pool):
    """The steps the reading still leaves out: islandwalk granted now and the
    creature (or the artifact) destroyed later is a gift with a price, aimed
    at the activator's own creature."""
    sandals = set_pool("ARN")["Sandals of Abdallah"]
    barge = set_pool("DRK")["War Barge"]

    assert [ability_target_side(step) for step in _abilities(sandals)] == ["you"]
    assert [ability_target_side(step) for step in _abilities(barge)] == ["you"]
