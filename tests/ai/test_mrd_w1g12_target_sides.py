"""Whose creature an AI seat names for W1G12's two targeted Mirrodin spells.

Awe Strike ("The next time target creature would deal damage this turn,
prevent that damage. You gain life …") stops what its target deals, so the
target is an opposing creature: in seeded games before
``ai_target_sides._silences_its_object`` read ``source_from: "target"``, an AI
seat cast it on its own attacker and prevented its own damage to the opponent.
Bloodscent ("All creatures able to block target creature this turn do so") is
a Lure for the turn on the caster's attacker.
"""
from engine.ai_target_sides import spell_target_side


def test_awe_strike_names_an_opposing_creature(set_pool):
    assert spell_target_side(set_pool("MRD")["Awe Strike"]) == "opponent"


def test_bloodscent_names_the_casters_own_creature(set_pool):
    assert spell_target_side(set_pool("MRD")["Bloodscent"]) == "you"
