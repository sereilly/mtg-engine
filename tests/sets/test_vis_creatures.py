"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle


def test_kyscu_drake_charges_both_halves_of_its_conjoined_sacrifice(set_pool):
    """"Sacrifice this creature **and a creature named Spitting Drake**".

    Two objects under one printed verb, joined by a bare "and" with no comma —
    the shape every reader in the charger declined. The Oxford-list regex needs
    a comma before its "and", the single-object delimiter is switched off once
    "sacrifice this ..." has set ``sacrifice_self``, and the "any number of"
    reader wants a set. So the Drake's own sacrifice was charged and the second
    creature was not: an ability activated for less than the card prints, which
    is the failure that neither crashes nor goes missing.
    """
    drake = set_pool("VIS")["Kyscu Drake"]
    program = compile_card_oracle(drake)

    tutor = [
        ability
        for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(tutor) == 1, "the tutor ability is the one that sacrifices itself"
    cost = tutor[0].cost

    # The source in its flag and the chosen permanent in the filter — the same
    # encoding the Oxford-list path already gives the same two facts.
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "named": "spitting drake",
    }


# --- VIS w1g3: prevention, redirection and lethal damage --------------------
#
# Imports live inside the block by the per-set convention, so a merge that
# appends another group's block cannot lose one. Every test here drives a real
# ``Game``: a shield that is armed and never consumed looks exactly like one
# that works.

from engine import Game, PlayerState
from engine.game_types import OracleExecutionContext
from engine.models import CardDefinition, Permanent
from engine.pt import add_pt_counters
from tests.helpers import _damage_dealt, _nosick


def _w1g3c_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g3c_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g3c_activate(game, permanent, ability, *, caster, target=None,
                    target_permanent_index=None):
    context = OracleExecutionContext(
        card=permanent.card, caster=caster, target=target or caster,
        source_permanent=permanent,
        target_permanent_index=target_permanent_index,
    )
    game._execute_oracle_instruction(ability.instruction, context)
    return context


def test_resistance_fighter_stops_the_creature_it_named_dealing_combat_damage(set_pool):
    """"Sacrifice this creature: Prevent all combat damage **target creature
    would deal** this turn."

    The active voice of a sentence the engine has read in the passive since Kry
    Shield - the printed subject moved in front of the verb and nothing else -
    so the test that matters is that the shield really stops that creature's
    combat damage and leaves its noncombat damage and everybody else's alone.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    fighter = _nosick(Permanent(card=set_pool("VIS")["Resistance Fighter"]))
    dangerous = _nosick(Permanent(card=_w1g3c_bear("Dangerous Bear")))
    bystander = _nosick(Permanent(card=_w1g3c_bear("Other Bear")))
    p1.battlefield.append(fighter)
    p2.battlefield.extend([dangerous, bystander])

    program = compile_card_oracle(fighter.card)
    assert len(program.activated_abilities) == 1
    _w1g3c_activate(
        game, fighter, program.activated_abilities[0], caster=p1, target=p2,
        target_permanent_index=0,
    )

    assert _damage_dealt(game, p1, 3, source=dangerous, combat=True) == 0
    # Only combat damage, and only that creature's.
    assert _damage_dealt(game, p1, 3, source=dangerous, combat=False) == 3
    assert _damage_dealt(game, p1, 3, source=bystander, combat=True) == 3


def test_zhalfirin_crusader_moves_one_point_onto_the_target_it_chose(set_pool):
    """"{1}{W}: The next 1 damage that would be dealt to this creature this turn
    is dealt to **any target** instead."

    A redirect, not a shield: the damage is still dealt in full by the same
    source, and only its recipient changes for the one point the record covers.
    So the assertion is on both ends - nothing extra marked on the Crusader, and
    the point landing on what the ability named - and on the *remainder*,
    because a record that ate the whole event would be a shield wearing a
    redirect's name.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    crusader = _nosick(Permanent(card=set_pool("VIS")["Zhalfirin Crusader"]))
    taker = _nosick(Permanent(card=_w1g3c_bear("Taker", toughness=5)))
    p1.battlefield.append(crusader)
    p2.battlefield.append(taker)

    program = compile_card_oracle(crusader.card)
    ability = next(
        a for a in program.activated_abilities
        if a.instruction.kind == "redirect_next_damage_from_source_until_eot"
    )
    _w1g3c_activate(
        game, crusader, ability, caster=p1, target=p2, target_permanent_index=0,
    )

    game._mark_damage_on_permanent(crusader, 3)

    assert taker.damage_marked == 1, "one point moved, as the card counts them"
    assert crusader.damage_marked == 2, "and the rest landed where it was aimed"


def test_lichenthrope_turns_damage_into_counters_and_takes_none(set_pool):
    """"If damage would be dealt to this creature, put that many -1/-1 counters
    on it instead."

    CR 614's substitution: the damage is **not dealt at all**, which is why the
    assertion is on ``damage_marked`` staying zero as well as on the counters
    arriving. A version that marked the damage *and* added the counters would
    kill the Plant twice as fast while looking implemented.
    """
    game = _w1g3c_duel()
    p1, _ = game.players
    plant = _nosick(Permanent(card=set_pool("VIS")["Lichenthrope"]))
    p1.battlefield.append(plant)
    printed_toughness = plant.effective_toughness

    assert _damage_dealt(game, plant, 3) == 0
    assert plant.damage_marked == 0
    assert plant.effective_toughness == printed_toughness - 3


def test_lichenthrope_sheds_one_counter_each_upkeep(set_pool):
    """The card's other line, and the reason the substitution above is
    survivable. Asserted in the same file because the two sentences are one
    card: counters that nothing removes are a Plant that dies to a single
    Shock, eventually."""
    game = _w1g3c_duel()
    p1, _ = game.players
    plant = _nosick(Permanent(card=set_pool("VIS")["Lichenthrope"]))
    p1.battlefield.append(plant)
    printed_toughness = plant.effective_toughness
    add_pt_counters(plant, "-1/-1", 2)
    assert plant.effective_toughness == printed_toughness - 2

    game.start_turn(0)
    game._close_current_priority_step()
    game._close_current_priority_step()

    assert plant.effective_toughness == printed_toughness - 1


def test_ogre_enforcer_survives_lethal_damage_spread_across_two_sources(set_pool):
    """"This creature can't be destroyed by lethal damage unless lethal damage
    dealt by a **single source** is marked on it."

    Two 3/3s hitting the Ogre mark lethal damage between them and it lives; one
    source that dealt lethal on its own kills it. CR 704.5g is a state-based
    action, so the only way to test this is to let the sweep run.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    ogre = _nosick(Permanent(card=set_pool("VIS")["Ogre Enforcer"]))
    first = _nosick(Permanent(card=_w1g3c_bear("First Biter", power=3)))
    second = _nosick(Permanent(card=_w1g3c_bear("Second Biter", power=3)))
    p1.battlefield.append(ogre)
    p2.battlefield.extend([first, second])
    half = ogre.effective_toughness - 1

    game._mark_damage_on_permanent(ogre, half, source=first)
    game._mark_damage_on_permanent(ogre, half, source=second)
    game.check_state_based_actions()

    assert ogre.damage_marked >= ogre.effective_toughness, "the damage is lethal"
    assert any(p is ogre for p in p1.battlefield), "and the Ogre is still here"


def test_ogre_enforcer_dies_to_one_source_that_dealt_lethal(set_pool):
    """The other half, which is what makes the exception an exception rather
    than indestructibility."""
    game = _w1g3c_duel()
    p1, p2 = game.players
    ogre = _nosick(Permanent(card=set_pool("VIS")["Ogre Enforcer"]))
    big = _nosick(Permanent(card=_w1g3c_bear("Big Biter", power=9, toughness=9)))
    p1.battlefield.append(ogre)
    p2.battlefield.append(big)

    game._mark_damage_on_permanent(ogre, ogre.effective_toughness, source=big)
    game.check_state_based_actions()

    assert not any(p is ogre for p in p1.battlefield)


def test_an_ordinary_creature_still_dies_to_shared_lethal_damage(set_pool):
    """The control: the narrowing is derived from the Ogre's own text, so every
    other creature keeps CR 704.5g exactly as printed. A sweep that had learned
    the exception generally would be a board nothing can kill by ganging up."""
    game = _w1g3c_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3c_bear("Ordinary Bear", toughness=4)))
    first = _nosick(Permanent(card=_w1g3c_bear("First Biter", power=3)))
    second = _nosick(Permanent(card=_w1g3c_bear("Second Biter", power=3)))
    p1.battlefield.append(victim)
    p2.battlefield.extend([first, second])

    game._mark_damage_on_permanent(victim, 3, source=first)
    game._mark_damage_on_permanent(victim, 3, source=second)
    game.check_state_based_actions()

    assert not any(p is victim for p in p1.battlefield)
# --- end VIS w1g3 ---
