"""Nemesis artifacts.

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
# Two artifacts whose number is read off something else: Belbe's Armor's
# announced X, signed both ways on one creature, and Eye of Yawgmoth's count
# taken off the creature its own cost sacrificed (CR 601.2h, read back as
# CR 608.2h's last-known information).
from engine import Game as _W1g4Game
from engine import PlayerState as _W1g4PlayerState
from engine.models import CardDefinition as _W1g4Card
from engine.models import Permanent as _W1g4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_artifact_creature(name, power, toughness):
    """A vanilla test creature; the name says its size."""
    line = "Creature - Test"
    return _W1g4Card(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_artifact_table(seat0=(), seat1=(), library=()):
    """Two seats, costs unenforced, P0's main phase with priority open."""
    table = _W1g4Game(players=[
        _W1g4PlayerState(name="P0", battlefield=list(seat0), library=list(library)),
        _W1g4PlayerState(name="P1", battlefield=list(seat1)),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set()
    table.start_turn(0)
    table._close_current_priority_step()
    return table


def test_w1g4_belbes_armor_shrinks_power_and_grows_toughness_by_the_announced_x(
    set_pool,
):
    """"{X}, {T}: Target creature gets -X/+X until end of turn."

    The negated X is the half that used to refuse ("negative variable pump is
    not supported"): it travels as ``{"times_x": -1}``, the shape a "-1/-1 for
    each" repetition already lowers to, so the one amount reader applies the
    sign. A sign carried beside a bare "x" would be honoured only by handlers
    taught to read it — every other one would *grow* the creature.
    """
    armor = _W1g4Permanent(card=set_pool("NEM")["Belbe's Armor"])
    bear = _W1g4Permanent(card=_w1g4_artifact_creature("Bear 2/2", 2, 2))
    game = _w1g4_artifact_table((armor,), (bear,))
    ability = _w1g4_compile(armor.card).activated_abilities[0]
    assert _w1g4_activation_spec(ability) == {"kind": "creature"}

    result = game.activate_permanent_ability(
        0, "Belbe's Armor", target_player_index=1,
        target_permanent_ids=[bear.permanent_id], x_value=3,
    )
    assert result.supported, result
    _w1g4_resolve(game)

    assert (bear.effective_power, bear.effective_toughness) == (-1, 5)
    assert armor.tapped
    assert "Belbe's Armor gives Bear 2/2 -3/+3 until end of turn" in game.log


def test_w1g4_eye_of_yawgmoth_reveals_as_many_as_the_sacrificed_power(set_pool):
    """"{3}, {T}, Sacrifice a creature: Reveal a number of cards from the top of
    your library equal to the sacrificed creature's power. Put one into your
    hand and exile the rest."

    The count is the sacrificed creature's power *as it last existed* (CR
    608.2h) — the payment path's record, not a board read, since by resolution
    the creature is a card in a graveyard. The reveal is CR 701.20a's public
    one, recorded for every player; the pick and the exile are the look-and-
    pick procedure the family already runs (Browse's destinations).
    """
    eye = _W1g4Permanent(card=set_pool("NEM")["Eye of Yawgmoth"])
    fodder = _W1g4Permanent(card=_w1g4_artifact_creature("Fodder 3/1", 3, 1))
    library = [_w1g4_artifact_creature(f"Card {i}", 1, 1) for i in range(5)]
    game = _w1g4_artifact_table((eye, fodder), library=library)

    result = game.activate_permanent_ability(
        0, "Eye of Yawgmoth", cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result
    _w1g4_resolve(game)

    assert not game.is_on_battlefield(fodder)
    assert game.reveal_events[-1]["cards"] == ["Card 0", "Card 1", "Card 2"]
    assert game.pending_choice_of("look_top_pick", 0) is not None
    assert game.confirm_look_top_pick(0, 1)

    me = game.players[0]
    assert [card.name for card in me.hand] == ["Card 1"]
    assert sorted(card.name for card in me.exile) == ["Card 0", "Card 2"]
    assert [card.name for card in me.library] == ["Card 3", "Card 4"]


def test_w1g4_eye_of_yawgmoth_reads_last_known_power_not_the_printed_one(set_pool):
    """A pumped creature sacrificed for the cost reveals its *pumped* power: the
    record carries the permanent, whose computed power is what it had on the
    battlefield (CR 608.2h). The printed 1 would reveal one card."""
    from engine.pt import add_pt_modifier

    eye = _W1g4Permanent(card=set_pool("NEM")["Eye of Yawgmoth"])
    fodder = _W1g4Permanent(card=_w1g4_artifact_creature("Fodder 1/1", 1, 1))
    library = [_w1g4_artifact_creature(f"Card {i}", 1, 1) for i in range(5)]
    game = _w1g4_artifact_table((eye, fodder), library=library)
    add_pt_modifier(fodder, 3, 0)

    game.activate_permanent_ability(
        0, "Eye of Yawgmoth", cost_permanent_ids=[fodder.permanent_id],
    )
    _w1g4_resolve(game)

    assert len(game.reveal_events[-1]["cards"]) == 4
