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


# --- W1G4: amounts and bounded targets ---
# Two legends: Ascendant Evincar's colour-*negated* anthem, carried as a filter
# field the layer-7c refresh tests through the layer-5 colour accessor, and
# Volrath the Fallen's pump sized by what its own discard cost paid.
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_creature_card(name, power, toughness, colors=(), cmc=0):
    """A vanilla test creature of *colors* and mana value *cmc*."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="{%d}" % cmc if cmc else "", cmc=float(cmc),
        type_line=line, oracle_text="", colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_creature_table(seat0=(), seat1=(), hand=()):
    """Two seats, costs unenforced, P0's main phase with *hand* in it."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), hand=list(hand)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_ascendant_evincar_lifts_black_and_shrinks_nonblack_everywhere(
    set_pool,
):
    """"Other black creatures get +1/+1. Nonblack creatures get -1/-1."

    Both lines reach every player's creatures. The Evincar is black, so the
    first line's "other" keeps it a 3/3 and the second line misses it; a
    colourless creature is nonblack (CR 105.2c) and shrinks; a nonblack 1/1
    dies to the state-based check. The exclusion was the refused half — the
    lord-buff table carried no colour exclusion, so the sentence could only be
    dropped or refused.
    """
    black_ally = _W1g4Permanent(card=_w1g4_creature_card("Black Ally", 2, 2, ("B",)))
    green_ally = _W1g4Permanent(card=_w1g4_creature_card("Green Ally", 2, 2, ("G",)))
    colourless = _W1g4Permanent(card=_w1g4_creature_card("Grey Foe", 2, 2))
    black_foe = _W1g4Permanent(card=_w1g4_creature_card("Black Foe", 2, 2, ("B",)))
    weenie = _W1g4Permanent(card=_w1g4_creature_card("Weenie", 1, 1, ("W",)))
    game = _w1g4_creature_table(
        (black_ally, green_ally), (colourless, black_foe, weenie),
        hand=(set_pool("NEM")["Ascendant Evincar"],),
    )

    game.cast_from_hand(0, "Ascendant Evincar")
    _w1g4_resolve(game)

    evincar = next(
        perm for perm in game.all_permanents() if perm.card.name == "Ascendant Evincar"
    )
    sizes = {
        perm.card.name: (perm.effective_power, perm.effective_toughness)
        for perm in (evincar, black_ally, green_ally, colourless, black_foe)
    }
    assert sizes == {
        "Ascendant Evincar": (3, 3),
        "Black Ally": (3, 3), "Black Foe": (3, 3),
        "Green Ally": (1, 1), "Grey Foe": (1, 1),
    }
    assert not game.is_on_battlefield(weenie)


def test_w1g4_ascendant_evincar_reads_colour_through_the_layers(set_pool):
    """A creature *made* black escapes the debuff and joins the anthem, because
    both lines ask the layer-5 colour accessor on every recompute rather than
    the printed colour (CR 613.5's own worked example, one colour over)."""
    evincar = _W1g4Permanent(card=set_pool("NEM")["Ascendant Evincar"])
    bear = _W1g4Permanent(card=_w1g4_creature_card("Green Bear", 2, 2, ("G",)))
    game = _w1g4_creature_table((evincar,), (bear,))
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert (bear.effective_power, bear.effective_toughness) == (1, 1)

    bear.metadata["color_override"] = ("B",)
    game._recalculate_lord_buffs()
    game._refresh_dynamic_creatures()
    assert "B" in bear.effective_colors
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)


def test_w1g4_volrath_grows_by_the_discarded_creature_cards_mana_value(set_pool):
    """"{1}{B}, Discard a creature card: Volrath the Fallen gets +X/+X until
    end of turn, where X is the discarded card's mana value."

    X is read off the payment path's record of the card the cost discarded
    (CR 601.2h then 608.2h) — the same channel Pyromancy's damage reads. The
    cost is narrowed to a *creature* card and the player names which: naming a
    noncreature card is refused with nothing paid.
    """
    volrath = _W1g4Permanent(card=set_pool("NEM")["Volrath the Fallen"])
    volrath.metadata["summoning_sickness_turn"] = -99
    instant = set_pool("NEM")["Rupture"]
    five_drop = _w1g4_creature_card("Five Drop", 5, 5, cmc=5)
    game = _w1g4_creature_table((volrath,), hand=(instant, five_drop))
    ability = _w1g4_compile(volrath.card).activated_abilities[0]
    assert _w1g4_activation_spec(ability)["filters"] == [{"type_filter": "creature"}]

    refused = game.activate_permanent_ability(0, "Volrath the Fallen", cost_hand_index=0)
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Rupture", "Five Drop"]

    result = game.activate_permanent_ability(0, "Volrath the Fallen", cost_hand_index=1)
    assert result.supported, result
    _w1g4_resolve(game)

    assert [card.name for card in game.players[0].graveyard] == ["Five Drop"]
    assert (volrath.effective_power, volrath.effective_toughness) == (11, 9)
