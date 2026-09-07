"""Exodus artifacts.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: a cost nobody chooses, and a cost that reduces another ---
#
# Null Brooch's noncreature counter behind a whole-hand discard (CR 602.2b,
# CR 601.2c) and Memory Crystal's reduction of CR 702.27a's offer (CR 601.2f).
# Imports are in this block, per the header's convention.

from engine import Game as _G5aGame
from engine.card_loader import (load_catalog as _g5a_catalog,
                                load_cards as _g5a_load,
                                manifest_set_path as _g5a_path)
from engine.cost_modifiers import (buyback_cost_reduction as _g5a_reduction,
                                   cost_modifiers_for as _g5a_modifiers)
from engine.models import PlayerState as _G5aPlayer, Permanent as _G5aPermanent
from engine.oracle import compile_card_oracle as _g5a_compile
from tests.helpers import resolve_stack as _g5a_drain

_G5A_POOL = {card.name: card for card in _g5a_catalog()}
_G5A_TMP = {card.name: card for card in _g5a_load(_g5a_path("TMP"))}


def _g5a_brooch_board(set_pool, opponent_hand):
    caster = _G5aPlayer(
        name="A", hand=[_G5A_POOL["Grizzly Bears"], _G5A_POOL["Hill Giant"]]
    )
    opponent = _G5aPlayer(name="B", hand=list(opponent_hand))
    game = _G5aGame(players=[caster, opponent])
    game.enforce_mana_costs = False
    brooch = _G5aPermanent(card=set_pool("EXO")["Null Brooch"])
    brooch.metadata["summoning_sickness_turn"] = -99
    caster.battlefield.append(brooch)
    game._settle()
    return game, caster, opponent


def test_null_brooch_counters_a_noncreature_spell_for_its_whole_hand(set_pool):
    """"{2}, {T}, Discard your hand: Counter target noncreature spell."

    ``excluded_types`` is the complement of the ``card_types`` union three
    counterspells already carry, and it reaches the same three readers — the
    handler's test, the picker's spec and the stack enumeration — because a
    narrowing only one of them knows is a counter that offers what it will not
    counter, or counters what it was not offered.
    """
    program = _g5a_compile(set_pool("EXO")["Null Brooch"])
    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.cost.discard_whole_hand
    assert ability.instruction.payload["excluded_types"] == ["creature"]

    game, caster, opponent = _g5a_brooch_board(
        set_pool, [_G5A_POOL["Lightning Bolt"]]
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.activate_permanent_ability(
        0, "Null Brooch", target_stack_index=0, ability_index=0
    )
    _g5a_drain(game)

    assert result.supported, result.details
    assert [c.name for c in opponent.graveyard] == ["Lightning Bolt"]
    assert caster.hand == [] and len(caster.graveyard) == 2


def test_null_brooch_refuses_a_creature_spell_with_nothing_paid(set_pool):
    """CR 602.2b: the target is chosen before any cost is paid, so an ability
    with no legal target is refused rather than activated to no effect.

    The direction that matters is the cost: a narrowing the picker did not know
    would have discarded the whole hand and tapped the Brooch for a counter the
    handler then declined.
    """
    game, caster, _opponent = _g5a_brooch_board(
        set_pool, [_G5A_POOL["Grizzly Bears"]]
    )
    game.queue_from_hand(1, "Grizzly Bears")
    (brooch,) = [p for p in caster.battlefield if p.card.name == "Null Brooch"]

    result = game.activate_permanent_ability(
        0, "Null Brooch", target_stack_index=0, ability_index=0
    )

    assert not result.supported
    assert len(caster.hand) == 2 and not brooch.tapped
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]


def test_null_brooch_refuses_an_artifact_creature_spell(set_pool):
    """CR 205.2: a card has **every** type its line names, so an artifact
    creature spell is not a noncreature spell.

    Asked through the handler's own reader rather than through ``primary_type``,
    which is the reading the union beside it still makes — an artifact creature
    whose primary type is "artifact" would be offered and then declined.
    """
    beast = next(
        card for card in _G5A_POOL.values()
        if "Artifact Creature" in card.type_line
    )
    game, caster, _opponent = _g5a_brooch_board(set_pool, [beast])
    game.queue_from_hand(1, beast.name)

    result = game.activate_permanent_ability(
        0, "Null Brooch", target_stack_index=0, ability_index=0
    )

    assert not result.supported
    assert len(caster.hand) == 2, "nothing is paid on the way to a refusal"


def _g5a_crystal_game(crystal, crystals, pool):
    """Whispers of the Muse ({U}, Buyback {5}) cast under *crystals* copies of
    *crystal* with *pool* floating, mana costs enforced."""
    caster = _G5aPlayer(
        name="A",
        hand=[_G5A_TMP["Whispers of the Muse"]],
        library=[_G5A_POOL["Mountain"]] * 6,
    )
    game = _G5aGame(players=[caster, _G5aPlayer(name="B")])
    game.enforce_mana_costs = True
    for _ in range(crystals):
        caster.battlefield.append(_G5aPermanent(card=crystal))
    game._settle()
    caster.mana_pool.update(pool)
    return game, caster


def test_memory_crystal_reads_as_a_reduction_of_the_keyword_and_not_of_a_spell(
    set_pool,
):
    """"Buyback costs cost {2} less."

    A third value of ``applies_to`` rather than a "cast" modifier with an empty
    filter, and the assertion says why: an unnarrowed cast modifier would reduce
    every spell's **mana cost**, which is the one thing this card must not do.
    """
    (modifier,) = _g5a_modifiers(set_pool("EXO")["Memory Crystal"].oracle_text)
    assert modifier.applies_to == "buyback" and modifier.reduces
    assert modifier.amount == 2
    assert modifier.card_types == () and modifier.colour is None


def test_memory_crystal_takes_two_off_every_buyback_and_stacks(set_pool):
    """One application per permanent printing it, the arithmetic every other
    modifier in that file uses — and CR 118.7a's clamp at zero, which is what
    lets three Crystals make a {5} buyback free rather than negative.

    The **key** is deliberately untouched: it is the printed cost, and it is
    what CR 702.27a's hand-return is read back by at resolution. A reduction
    that moved it would make a Memory Crystal the difference between a spell
    that comes back and one that does not.
    """
    crystal = set_pool("EXO")["Memory Crystal"]

    game, caster = _g5a_crystal_game(crystal, 0, {"U": 1, "C": 3})
    assert not game.queue_from_hand(
        0, "Whispers of the Muse", optional_cost_payments={"{5}": 1}
    ).supported, "{U} plus three generic cannot pay a {5} buyback unaided"
    assert _g5a_reduction(game) == (0, [])

    for crystals, pool in ((1, {"U": 1, "C": 3}), (2, {"U": 1, "C": 1}), (3, {"U": 1})):
        game, caster = _g5a_crystal_game(crystal, crystals, pool)
        assert _g5a_reduction(game)[0] == 2 * crystals
        result = game.queue_from_hand(
            0, "Whispers of the Muse", optional_cost_payments={"{5}": 1}
        )
        _g5a_drain(game)
        assert result.supported, (crystals, result.details)
        assert "Whispers of the Muse" in [c.name for c in caster.hand], (
            "the announcement's key is the printed {5}, so the card still "
            "comes back however much the charge was reduced"
        )
# end of the W1G5 artifacts block
