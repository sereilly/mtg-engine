"""A quoted grant that hampers its holder is aimed at an opponent's object.

"{1}{W}: Until end of turn, target creature gains "This creature can't attack
or block unless its controller pays {1} for each Cleric on the battlefield.""
(Whipgrass Entangler.) The instruction kind is a grant, whose category reads
every grant as a gift, so a simulated seat paid {1}{W} every turn to tax its
own creature. ``ai_target_sides._grants_a_burden`` reads the quoted line
through the readers that enforce it: a restriction on the holder's own
attacking or blocking, or on its own untapping.
"""

from engine.ai_target_sides import ability_denies_its_target, ability_target_side
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card


def _granting_instruction(text):
    card = _mk_card("Grant Probe", "Creature — Human Cleric", text, power=1, toughness=1)
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    return ability.instruction


def test_whipgrass_entangler_aims_its_toll_at_an_opponents_creature(set_pool):
    (ability,) = compile_card_oracle(
        set_pool("LGN")["Whipgrass Entangler"]
    ).activated_abilities
    assert ability_target_side(ability.instruction) == "opponent"
    assert ability_denies_its_target(ability.instruction)


def test_a_granted_restriction_on_the_holder_is_a_burden():
    for text in (
        '{1}: Target creature gains "This creature can\'t block." until end of turn.',
        '{1}: Until end of turn, target creature gains "This creature can\'t attack unless its controller pays {2}."',
        '{1}: Target creature gains "This creature doesn\'t untap during your untap step." until end of turn.',
    ):
        instruction = _granting_instruction(text)
        assert ability_target_side(instruction) == "opponent", text
        assert ability_denies_its_target(instruction), text


def test_a_granted_gift_keeps_its_own_side():
    """Evasion ("can't be blocked except by …") restricts the *other* side,
    and a regeneration shield is a gift: both stay the grant's reading."""
    for text in (
        '{1}: Target creature gains "This creature can\'t be blocked except by Walls." until end of turn.',
        '{1}: Target creature gains "{G}: Regenerate this creature." until end of turn.',
    ):
        instruction = _granting_instruction(text)
        assert ability_target_side(instruction) != "opponent", text
        assert not ability_denies_its_target(instruction), text
