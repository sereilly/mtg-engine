"""Tempest enchantments (Auras included — the printed type is the axis).

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: Legacy's Allure's counter bound and Recycle's hand size ---

from engine import Game, PlayerState
from engine.hand_size import maximum_hand_size
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _w1g5e_card(name, type_line, power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text="",
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w1g5e_game(mine, theirs):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game._settle()
    return game


def _w1g5e_allure(set_pool, counters, victim_power):
    allure = Permanent(card=set_pool("TMP")["Legacy's Allure"])
    victim = Permanent(card=_w1g5e_card(
        "Beast", "Creature — Beast", power=victim_power, toughness=victim_power,
    ))
    game = _w1g5e_game([allure], [victim])
    add_counters(allure, "treasure", counters)
    return game, allure, victim


def test_w1g5_legacys_allure_takes_a_creature_within_its_counter_bound(set_pool):
    """"Sacrifice this enchantment: Gain control of target creature with power
    less than or equal to the number of treasure counters on this enchantment."

    The bound is a count on the ability's own **source**, which the pure filter
    matcher cannot reach — so it is answered where the source is in hand, and a
    caller without one narrows to nothing rather than to every creature.
    """
    game, _allure, victim = _w1g5e_allure(set_pool, counters=3, victim_power=2)

    result = game.activate_permanent_ability(
        0, "Legacy's Allure", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert game.controller_index_of(victim) == 0, game.log


def test_w1g5_legacys_allure_refuses_a_creature_over_its_counter_bound(set_pool):
    """The half a dropped narrowing loses. With one counter, a 2-power creature
    is not a legal target (CR 601.2c/602.2b), and the refusal comes *before*
    the cost — so the enchantment is still on the battlefield afterwards."""
    game, allure, victim = _w1g5e_allure(set_pool, counters=1, victim_power=2)

    result = game.activate_permanent_ability(
        0, "Legacy's Allure", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert allure in game.controlled_by(0), "nothing was sacrificed"
    assert game.controller_index_of(victim) == 1


def test_w1g5_legacys_allure_offers_a_picker(set_pool):
    """The other half of the same defect: `picker_sweep` reported "says
    'target', derivation offers no picker" because the ability compiled to no
    instruction at all, leaving `derive_activation_spec` nothing to read."""
    program = compile_card_oracle(set_pool("TMP")["Legacy's Allure"])
    ability = program.activated_abilities[0]
    assert ability.instruction is not None, "the line is no longer hollow"
    assert derive_activation_spec(ability) == {"kind": "creature"}


def test_w1g5_recycle_sets_its_controllers_maximum_hand_size(set_pool):
    """"Your maximum hand size is two." (CR 402.2.)

    Three assertions because the sentence names one seat: the controller is
    limited, the opponent is not, and CR 611.3a ends the limit with the
    enchantment. That last one is what separates a derived static from the
    stamped field that left Library of Leng's permission on a destroyed
    permanent's controller for the rest of the game.
    """
    recycle = Permanent(card=set_pool("TMP")["Recycle"])
    game = _w1g5e_game([recycle], [])

    assert maximum_hand_size(game, 0) == 2
    assert maximum_hand_size(game, 1) == 7, "the sentence names one seat"

    game.players[0].hand.extend(
        _w1g5e_card(f"Card {index}", "Instant") for index in range(5)
    )
    game.active_player_index = 0
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 2, game.log

    game.remove_from_battlefield(recycle)
    assert maximum_hand_size(game, 0) == 7, "CR 611.3a: the static ends with it"
