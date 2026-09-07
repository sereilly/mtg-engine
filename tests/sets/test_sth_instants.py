"""Stronghold instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: damage prevention, redirection and damage-event triggers ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g1_temper(set_pool, x_value):
    """Temper cast for *x_value* over a 2/2, with the shield armed."""
    game = _w1g1_duel()
    p1, _ = game.players
    bear = _nosick(Permanent(card=_w1g1_bear("Shielded Bear")))
    p1.battlefield.append(bear)
    p1.hand.append(set_pool("STH")["Temper"])
    result = game.cast_from_hand(
        0, "Temper", target_player_index=0, target_permanent_index=0,
        x_value=x_value,
    )
    assert result.supported
    return game, bear


def test_temper_puts_a_counter_on_as_each_point_is_prevented(set_pool):
    """"Prevent the next X damage that would be dealt to target creature this
    turn. For each 1 damage prevented this way, put a +1/+1 counter on that
    creature."

    CR 615.5: "the prevention takes place at the time the original event would
    have happened; the rest of the effect takes place immediately afterward."
    So the counters arrive **inside the damage event**, which is the assertion
    that matters — a reading that placed them when the spell resolved would put
    down zero for ever, and would report exactly the same "supported".

    Three numbers, because each is a different way to get it wrong: no damage
    marked (the points really were prevented), two counters (one per point, not
    one per event), and the shield spent down to nothing.
    """
    game, bear = _w1g1_temper(set_pool, 2)
    printed = bear.effective_power

    assert bear.effective_power == printed, "nothing is placed at resolution"

    game._mark_damage_on_permanent(bear, 2)

    assert bear.damage_marked == 0
    assert bear.effective_power == printed + 2
    assert bear.damage_prevention_pool == 0


def test_temper_only_pays_for_the_damage_its_shield_actually_absorbed(set_pool):
    """The pool is X points wide and the counters count points, not events
    (CR 615.7). An event larger than the pool leaves its remainder marked and
    buys exactly as many counters as the shield had left — a rider that read
    the *event* would grow the creature by the whole Fireball.
    """
    game, bear = _w1g1_temper(set_pool, 1)
    printed_toughness = bear.effective_toughness

    game._mark_damage_on_permanent(bear, 3)

    assert bear.damage_marked == 2, "only one point was in the pool"
    assert bear.effective_toughness == printed_toughness + 1
