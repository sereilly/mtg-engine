"""Visions instants.

Opened at Visions' first wave. Every test here drives a real ``Game`` and
reads what happened to it — a shield that is armed and never consumed looks
exactly like one that works, which is why none of these assert on a compiled
program.
"""

# --- VIS w1g3: prevention, redirection and divided damage -------------------
#
# Imports live inside the block by the per-set convention, so a merge that
# appends another group's block cannot lose one.

from engine import Game, PlayerState
from engine.divided_damage import DIVIDED_TARGETS
from engine.game_types import OracleExecutionContext
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.shields import shields_on
from tests.helpers import _damage_dealt, _nosick


def _w1g3_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g3_bear(name="Bear", power=2, toughness=2, colors=()):
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Bear",
        oracle_text="",
        colors=tuple(colors),
        color_identity=tuple(colors),
        keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature — Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g3_flyer(name):
    card = _w1g3_bear(name)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Bird",
        oracle_text="Flying", colors=(), color_identity=(),
        keywords=("flying",), produced_mana=(),
        raw={
            "name": name, "type_line": "Creature — Bird",
            "power": "2", "toughness": "2",
        },
    )


def _w1g3_resolve(game, card, *, caster, target=None, choices=None,
                  source_permanent=None, target_permanent_index=None):
    """Run every instruction of *card*'s compiled program, once."""
    program = compile_card_oracle(card)
    context = OracleExecutionContext(
        card=card, caster=caster, target=target or caster,
        source_permanent=source_permanent,
        target_permanent_index=target_permanent_index,
        choices=choices or {},
    )
    for instruction in program.instructions:
        game._execute_oracle_instruction(instruction, context)
    return context


def test_remedy_splits_its_five_points_the_way_its_caster_announced(set_pool):
    """"Prevent the next 5 damage that would be dealt this turn to any number
    of targets, **divided as you choose**."

    CR 615.7's point pool split across CR 601.2d's announced targets. The test
    is the whole point of the round: the division has to reach the *shields*,
    and a shield armed at the wrong size looks identical to one armed right
    until damage arrives. So each recipient is dealt more than its share and
    what survives is read back.
    """
    game = _w1g3_duel()
    p1, p2 = game.players
    bear = _nosick(Permanent(card=_w1g3_bear()))
    p1.battlefield.append(bear)

    _w1g3_resolve(
        game, set_pool("VIS")["Remedy"], caster=p1,
        choices={DIVIDED_TARGETS: [(0, 0, 3), (1, None, 2)]},
    )

    # 3 points on the bear: a 5-damage hit leaves 2.
    assert _damage_dealt(game, bear, 5) == 2
    # 2 points on the opponent's face: a 5-damage hit leaves 3.
    assert _damage_dealt(game, p2, 5) == 3


def test_remedy_falls_back_to_an_even_split_when_nobody_announced_one(set_pool):
    """A seat with no way to be asked — the AI, a scripted duel — announces no
    division, and ``engine/divided_damage.py`` gives it the even one. Read here
    rather than trusted, because the fallback lives in the module the burn
    spells share and this is the first shield to use it.
    """
    game = _w1g3_duel()
    p1, p2 = game.players

    _w1g3_resolve(
        game, set_pool("VIS")["Remedy"], caster=p1,
        choices={DIVIDED_TARGETS: [(0, None), (1, None)]},
    )

    assert _damage_dealt(game, p1, 5) == 3
    assert _damage_dealt(game, p2, 5) == 3


def test_honorable_passage_sends_a_red_source_s_damage_back_at_its_controller(set_pool):
    """"…prevent that damage. **If damage from a red source is prevented this
    way, this spell deals that much damage to the source's controller.**"

    Two halves and the second is the card: the shield absorbing is not evidence
    that the rider fired, and the rider firing on a *green* source would be a
    card doing more than it prints. Both are asserted, in one game.
    """
    game = _w1g3_duel()
    p1, p2 = game.players
    red_source = _nosick(Permanent(card=_w1g3_bear("Fire Bear", colors=("R",))))
    p2.battlefield.append(red_source)

    _w1g3_resolve(
        game, set_pool("VIS")["Honorable Passage"], caster=p1, target=p1,
    )
    assert shields_on(p1), "the shield goes around what the spell targeted"

    before = p2.life
    assert _damage_dealt(game, p1, 4, source=red_source) == 0
    assert p2.life == before - 4, "the red source's controller takes it back"


def test_honorable_passage_prevents_a_green_source_and_pays_nobody(set_pool):
    """The condition is rechecked against the source when the damage would be
    dealt (CR 615.9's reading applied to the rider): a source of the wrong
    colour is still *prevented* — the sentence before the condition is
    unconditional — and nobody is dealt anything for it."""
    game = _w1g3_duel()
    p1, p2 = game.players
    green_source = _nosick(Permanent(card=_w1g3_bear("Leaf Bear", colors=("G",))))
    p2.battlefield.append(green_source)

    _w1g3_resolve(
        game, set_pool("VIS")["Honorable Passage"], caster=p1, target=p1,
    )

    before = p2.life
    assert _damage_dealt(game, p1, 4, source=green_source) == 0
    assert p2.life == before


def test_rock_slide_offers_only_creatures_in_combat_and_without_flying(set_pool):
    """"…among any number of target **attacking or blocking creatures without
    flying**."

    The union is the narrowing this round bought, and what it is worth is the
    *picker*: an idle creature and a flying attacker are not legal targets, and
    before ``any_states`` was promised the whole card was refused rather than
    narrowed. Asked of ``legality``, which is the list the engine and the web
    picker both read.
    """
    from engine.targeting import derive_cast_spec

    game = _w1g3_duel()
    p1, p2 = game.players
    attacker = _nosick(Permanent(card=_w1g3_bear("Ground Attacker")))
    idle = _nosick(Permanent(card=_w1g3_bear("Idle Bear")))
    flyer = _nosick(Permanent(card=_w1g3_flyer("Flying Attacker")))
    p2.battlefield.extend([attacker, idle, flyer])
    attacker.attacking = True
    flyer.attacking = True

    rock_slide = set_pool("VIS")["Rock Slide"]
    spec = derive_cast_spec(rock_slide, compile_card_oracle(rock_slide))
    assert spec["kind"] == "divided", "the caster divides X among its targets"

    offered = {
        entry.get("name")
        for entry in game._enumerate_targets(0, rock_slide, spec, for_cast=True)
        if entry.get("name")
    }
    assert "Ground Attacker" in offered
    assert "Idle Bear" not in offered, "not in combat"
    assert "Flying Attacker" not in offered, "in combat, and excluded by name"


def test_rock_slide_divides_x_among_the_creatures_its_caster_named(set_pool):
    """The Rock Hydra step for the other half: the targets are offered, and the
    damage announced for each one is the damage each one takes."""
    game = _w1g3_duel()
    p1, p2 = game.players
    big = _nosick(Permanent(card=_w1g3_bear("Big Attacker", power=1, toughness=5)))
    small = _nosick(Permanent(card=_w1g3_bear("Small Blocker", power=1, toughness=5)))
    p2.battlefield.extend([big, small])
    big.attacking = True
    small.blocking_attacker_index = 0

    _w1g3_resolve(
        game, set_pool("VIS")["Rock Slide"], caster=p1, target=p2,
        choices={DIVIDED_TARGETS: [(1, 0, 3), (1, 1, 1)]},
    )

    assert big.damage_marked == 3
    assert small.damage_marked == 1


def test_simoon_burns_only_the_opponent_it_named(set_pool):
    """"Simoon deals 1 damage to **each creature target opponent controls**."

    A supported card no player could cast — the picker offered nothing, so the
    client sent a bare cast and the engine refused it (the Roots class). And
    behind that, a second failure the picker finding could not see: the matcher
    read "target opponent" as *any* opponent, so with three seats at the table
    the spell burned two boards where the card names one.

    Three seats, therefore, because two cannot tell the two readings apart.
    """
    game = Game(players=[
        PlayerState(name="P1"), PlayerState(name="P2"), PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    p1, p2, p3 = game.players
    named = _nosick(Permanent(card=_w1g3_bear("Named Opponent's Bear")))
    other = _nosick(Permanent(card=_w1g3_bear("Other Opponent's Bear")))
    mine = _nosick(Permanent(card=_w1g3_bear("My Own Bear")))
    p2.battlefield.append(named)
    p3.battlefield.append(other)
    p1.battlefield.append(mine)

    _w1g3_resolve(game, set_pool("VIS")["Simoon"], caster=p1, target=p2)

    assert named.damage_marked == 1
    assert other.damage_marked == 0, "the opponent the spell did not name"
    assert mine.damage_marked == 0, "and never the caster's own creatures"


def test_simoon_asks_for_the_opponent_it_names(set_pool):
    """The picker half of the same finding, asserted separately: the cast spec
    is a player prompt that excludes the caster (CR 115.4), which is what makes
    the resolution above reachable from a client at all."""
    from engine.targeting import derive_cast_spec

    simoon = set_pool("VIS")["Simoon"]
    spec = derive_cast_spec(simoon, compile_card_oracle(simoon))

    assert spec == {"kind": "player", "opponents_only": True}
# --- end VIS w1g3 ---
