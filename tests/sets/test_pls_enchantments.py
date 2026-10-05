"""Planeshift enchantments.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G7: triggers and cast rules ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import CardDefinition as _W1G7Card
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(name, type_line, text="", *, cost="{1}", colors=(), pt=None):
    """A fixture card with exactly the printed text a test needs."""
    raw = {"name": name, "type_line": type_line}
    if pt is not None:
        raw["power"], raw["toughness"] = str(pt[0]), str(pt[1])
    made = _W1G7Card(
        name=name, mana_cost=cost, cmc=float(cost.count("{")),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    return made


def _w1g7_lands(set_pool, count, name="Swamp"):
    """*count* untapped basics — real ones, so they tap for real mana."""
    land = set_pool("LEA")[name]
    return [_W1G7Permanent(card=land) for _ in range(count)]


def _w1g7_board(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Two seats, a library each, costs off — the enchantment under test on
    seat 0 unless the test says otherwise."""
    filler = _w1g7_card("W1G7 Filler", "Creature - Test", pt=(1, 1))
    table = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", battlefield=list(mine), hand=list(hands[0]),
            library=[filler] * 8,
        ),
        _W1G7PlayerState(
            name="P2", battlefield=list(theirs), hand=list(hands[1]),
            library=[filler] * 8,
        ),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set(interactive)
    return table


# Phyrexian Tyranny — "Whenever a player draws a card, that player loses 2 life
# unless they pay {2}." CR 121.2 makes a draw a per-card event, so a draw-two is
# two triggers and two tolls; "a player" is the third value of the seat axis
# `draws_card` already carried for "you" and "an opponent".


def test_w1g7_phyrexian_tyranny_compiles_as_a_toll_on_any_seats_draw(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Phyrexian Tyranny"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "draws_card"
    assert trigger.condition.payload == {"drawer": "a player"}
    assert trigger.instruction.kind == "may"
    assert trigger.instruction.payload["actor"] == "event_subject_player"
    assert trigger.instruction.payload["cost"] == {"generic": 2}


def test_w1g7_phyrexian_tyranny_costs_the_drawing_opponent_two_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    # No land to pay with, so the offer is never made and the toll applies.
    assert [seat.life for seat in table.players] == [20, 18]


def test_w1g7_phyrexian_tyranny_binds_its_own_controller_too(set_pool):
    """"A player" is not "an opponent": the enchantment's controller drawing is
    the event happening to a seat the card names."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[0], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    assert [seat.life for seat in table.players] == [18, 20]


def test_w1g7_phyrexian_tyranny_is_one_toll_per_card_drawn(set_pool):
    """CR 121.2: drawing two cards is two draws, so two triggers and two
    separate offers — three lands pay for exactly one of them."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 2)
    table.check_state_based_actions()
    assert [item.card.name for item in table.stack] == ["Phyrexian Tyranny"] * 2

    table.resolve_top_of_stack(pause_for_choices=True)
    (offer,) = table.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 1), (
        "the drawing player is the payer, not the enchantment's controller"
    )
    assert table.confirm_optional_pay(1, accept=True)
    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2

    # The second toll: one untapped land cannot cover {2}, so it is not offered.
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.pending_choices == []
    assert table.players[1].life == 18
    assert not table.stack


def test_w1g7_phyrexian_tyranny_a_declined_toll_loses_the_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 2)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.confirm_optional_pay(1, accept=False)

    assert table.players[1].life == 18
    assert not any(land.tapped for land in lands)


def test_w1g7_phyrexian_tyranny_fires_in_the_draw_step_that_drew(set_pool):
    """CR 504.2 with CR 603.3: the turn-based draw's trigger goes on the stack
    before the active player's draw-step priority, not a phase later. The
    headless turn resolves it inside the step, so the toll is already settled
    when the main phase begins."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    table.resolve_draw_step(1)
    table.auto_resolve_pending_choices()

    assert table.current_step == "draw"
    assert table.players[1].life == 18
