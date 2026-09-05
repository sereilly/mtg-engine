"""Visions enchantments and Auras.

Split by the printed type of the card each test names
(``tests/sets/README.md``).
"""

# --- G1: the return-to-hand family ---
#
# Imports at the top of this block, so a merge that appends another group's
# block below cannot lose them (SET_PLAYBOOK.md).
from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _rig():
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, alice, bob


def _enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def test_flooded_shoreline_charges_both_islands_before_it_bounces(set_pool, catalog_by_name):
    """"{U}{U}, Return two Islands you control to their owner's hand: Return
    target creature to its owner's hand."

    The cost is the half nothing charged: the effect ("return target creature")
    has been readable since Unsummon, so an activation with the cost dropped
    would be a free Boomerang every turn. Two Islands leave, and the third is
    what proves the count rather than the whole board is what was taken.
    """
    game, alice, bob = _rig()
    for _ in range(3):
        _enters(game, 0, catalog_by_name["Island"])
    _enters(game, 0, set_pool("VIS")["Flooded Shoreline"])
    _enters(game, 1, catalog_by_name["Grizzly Bears"])

    result = game.activate_permanent_ability(
        0, "Flooded Shoreline", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is True
    assert [p.card.name for p in alice.battlefield] == ["Island", "Flooded Shoreline"]
    assert [card.name for card in alice.hand] == ["Island", "Island"]
    assert bob.battlefield == []
    assert [card.name for card in bob.hand] == ["Grizzly Bears"]


def test_flooded_shoreline_is_refused_with_one_island(set_pool, catalog_by_name):
    """CR 601.2h: partial payments are not allowed.

    One Island is not half a cost — the activation is refused with nothing
    spent, rather than eating the one Island and bouncing anyway.
    """
    game, alice, bob = _rig()
    _enters(game, 0, catalog_by_name["Island"])
    _enters(game, 0, set_pool("VIS")["Flooded Shoreline"])
    bear = _enters(game, 1, catalog_by_name["Grizzly Bears"])

    result = game.activate_permanent_ability(
        0, "Flooded Shoreline", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is False
    assert [p.card.name for p in alice.battlefield] == ["Island", "Flooded Shoreline"]
    assert alice.hand == []
    assert game.is_on_battlefield(bear)


def test_sun_clasp_buffs_and_then_bounces_the_creature_it_enchants(set_pool, catalog_by_name):
    """"Enchanted creature gets +1/+3." / "{W}: Return enchanted creature to
    its owner's hand."

    The Aura's own attachment, named rather than chosen (CR 303.4b), so the
    bounce reaches an opponent's creature without targeting it. And the Aura
    goes with it: CR 704.5m bins an Aura attached to nothing.
    """
    game, alice, bob = _rig()
    bear = _enters(game, 1, catalog_by_name["Grizzly Bears"])
    clasp = _enters(game, 0, set_pool("VIS")["Sun Clasp"])
    attach_aura(clasp, bear)

    assert (bear.effective_power, bear.effective_toughness) == (3, 5)

    result = game.activate_permanent_ability(0, "Sun Clasp")

    assert result.supported is True
    assert bob.battlefield == []
    assert [card.name for card in bob.hand] == ["Grizzly Bears"]
    assert alice.battlefield == [], "the Aura followed it (704.5m)"
    assert [card.name for card in alice.graveyard] == ["Sun Clasp"]


def test_sun_clasp_claims_every_printed_line(set_pool):
    """Both effect lines compile, not just the +1/+3.

    An Aura is supported when the gate can read its effects, and the P/T grant
    alone used to be enough to make the card look done while the activated
    ability had nothing behind it.
    """
    program = compile_card_oracle(set_pool("VIS")["Sun Clasp"])

    assert program.supported is True
    assert len(program.activated_abilities) == 1
    ability = program.activated_abilities[0]
    assert ability.supported is True
    assert ability.instruction.kind == "return_attached_permanent_to_hand"
