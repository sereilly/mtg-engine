"""Nemesis creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: alternative costs and redirects ---
# Skyshroud Cutter (an alternative cost that hands every other player life) and
# Oracle's Attendants (a blanket redirect off an announced creature, answering
# to one chosen source).
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec
from tests.helpers import _nosick


def _w1g2c_table(set_pool, hand=(), mine=(), theirs=()):
    """Two seats, mana costs **enforced**. Basics and bystanders come from
    the base set."""
    pools = (set_pool("NEM"), set_pool("LEA"))

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [card(name) for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    caster.battlefield.extend(_nosick(Permanent(card=card(name))) for name in mine)
    other.battlefield.extend(_nosick(Permanent(card=card(name))) for name in theirs)
    game._sync_control()
    return game, caster, other


def test_w1g2_skyshroud_cutter_costs_the_opponent_five_life(set_pool):
    """"If you control a Forest, rather than pay this spell's mana cost, you may
    have each other player gain 5 life." The Cutter lands, the opponent gains,
    and the pool is untouched; with no Forest there is no offer."""
    game, caster, other = _w1g2c_table(set_pool, ["Skyshroud Cutter"], mine=("Island",))
    assert not game.cast_from_hand(0, "Skyshroud Cutter", alternative_cost=True).supported

    game, caster, other = _w1g2c_table(set_pool, ["Skyshroud Cutter"], mine=("Forest",))
    result = game.cast_from_hand(0, "Skyshroud Cutter", alternative_cost=True)

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Forest", "Skyshroud Cutter"]
    assert (caster.life, other.life) == (20, 25)
    assert not any(caster.mana_pool.values())


def _w1g2c_attendants_ability_index(set_pool):
    program = compile_card_oracle(set_pool("NEM")["Oracle's Attendants"])
    return next(
        i for i, ability in enumerate(program.activated_abilities)
        if ability.instruction.kind
        == "redirect_chosen_source_damage_off_target_until_eot"
    )


def test_w1g2_oracles_attendants_picker_asks_for_a_creature_and_a_source(set_pool):
    """Two announcements: the protected creature is a target (CR 601.2c) and
    the source is CR 609.7a's choice, which is not one. A picker asking only
    for the creature would send an activation that moves nothing."""
    program = compile_card_oracle(set_pool("NEM")["Oracle's Attendants"])
    ability = program.activated_abilities[_w1g2c_attendants_ability_index(set_pool)]
    assert derive_activation_spec(ability) == {
        "kind": "creature", "requires_source": True,
    }


def test_w1g2_oracles_attendants_takes_the_chosen_sources_damage_all_turn(set_pool):
    """"{T}: **All** damage that would be dealt to target creature this turn by
    a source of your choice is dealt to this creature instead."

    Blanket, not "the next time": both hits from the chosen source move, and
    the first does not use the effect up. Only that source's damage moves — a
    second creature's hit lands on the protected one as printed.
    """
    game, caster, other = _w1g2c_table(
        set_pool, mine=("Oracle's Attendants", "Grizzly Bears"),
        theirs=("Hill Giant", "Llanowar Elves"),
    )
    attendants, bears = caster.battlefield
    giant, elves = other.battlefield

    result = game.activate_permanent_ability(
        0, "Oracle's Attendants", permanent_index=0,
        ability_index=_w1g2c_attendants_ability_index(set_pool),
        target_player_index=0, target_permanent_index=1,
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported, result.details
    assert attendants.tapped

    game._mark_damage_on_permanent(bears, 1, source=giant)
    game._mark_damage_on_permanent(bears, 2, source=giant)
    assert (bears.damage_marked, attendants.damage_marked) == (0, 3)

    game._mark_damage_on_permanent(bears, 1, source=elves)
    assert (bears.damage_marked, attendants.damage_marked) == (1, 3)


def test_w1g2_oracles_attendants_with_no_source_named_moves_nothing(set_pool):
    """CR 609.7a requires the source be chosen. A blanket record answering to
    any source would make the Attendants take every point dealt to the creature
    all turn, so an activation that named none arms nothing — the reading that
    cannot be wrong in its controller's favour."""
    game, caster, other = _w1g2c_table(
        set_pool, mine=("Oracle's Attendants", "Grizzly Bears"),
        theirs=("Hill Giant",),
    )
    attendants, bears = caster.battlefield

    result = game.activate_permanent_ability(
        0, "Oracle's Attendants", permanent_index=0,
        ability_index=_w1g2c_attendants_ability_index(set_pool),
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details

    game._mark_damage_on_permanent(bears, 1, source=other.battlefield[0])
    assert (bears.damage_marked, attendants.damage_marked) == (1, 0)
