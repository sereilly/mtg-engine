"""Invasion instants.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour choices ---
# Sway of Illusion: "Any number of target creatures become the color of your
# choice until end of turn. / Draw a card." It arrived supported with no
# target description at all, so the picker offered nothing and the resolution
# recoloured whatever one creature it happened on.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from engine.targeting import derive_cast_spec as _w1g6_cast_spec


def _w1g6_sway_table(set_pool, mine, theirs):
    lea = set_pool("LEA")
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.interactive_seats = {0}
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=lea[name])
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            side.append(perm)
        w1g6_sides.append(side)
    w1g6_game.players[0].hand.append(set_pool("INV")["Sway of Illusion"])
    w1g6_game.players[0].library.extend([lea["Forest"]] * 3)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_sway_table


def _w1g6_resolve_sway(game, colour):
    """Resolve the spell, answering its colour; report whether it was asked."""
    w1g6_asked = False
    for _ in range(6):
        if game.pending_choices:
            assert [(c.kind, c.player_index) for c in game.pending_choices] == [
                ("color_choice", 0)
            ]
            assert game.confirm_color_choice(0, colour)
            w1g6_asked = True
        elif game.stack:
            game.resolve_top_of_stack()
    return w1g6_asked  # _w1g6_resolve_sway


def test_w1g6_sway_of_illusion_offers_any_number_of_creature_targets(set_pool):
    """The picker is derived from the compiled program: creatures, as many as
    the caster likes, each at most once (CR 601.2c)."""
    card = set_pool("INV")["Sway of Illusion"]
    spec = _w1g6_cast_spec(card, _w1g6_compile(card))

    assert spec == {"kind": "creature", "unbounded_targets": True, "distinct_targets": True}


def test_w1g6_sway_of_illusion_recolours_exactly_the_chosen_creatures(set_pool):
    """Two of four creatures are targeted, one on each side; blue is named as
    the spell resolves — after the targets, not with them. Those two are blue
    until cleanup, the other two keep their colours, and the card is drawn."""
    game, mine, theirs = _w1g6_sway_table(
        set_pool, ["Grizzly Bears", "Hill Giant"], ["Llanowar Elves", "Black Knight"],
    )
    bears, giant = mine
    elves, knight = theirs

    assert game.queue_from_hand(
        0, "Sway of Illusion", new_color="R",
        target_permanent_ids=[bears.permanent_id, knight.permanent_id],
    ).supported
    assert _w1g6_resolve_sway(game, "U")

    colours = {
        perm.card.name: sorted(game._effective_colors(perm))
        for perm in (bears, giant, elves, knight)
    }
    assert colours == {
        "Grizzly Bears": ["U"], "Hill Giant": ["R"],
        "Llanowar Elves": ["G"], "Black Knight": ["U"],
    }
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    game.resolve_cleanup_step(0)
    assert sorted(game._effective_colors(bears)) == ["G"]
    assert sorted(game._effective_colors(knight)) == ["B"]


def test_w1g6_sway_of_illusion_with_no_targets_still_draws(set_pool):
    """"Any number" includes none (CR 601.2c): nothing is recoloured — in
    particular not the one creature on the table — and the card is drawn."""
    game, mine, _theirs = _w1g6_sway_table(set_pool, ["Grizzly Bears"], [])

    assert game.queue_from_hand(0, "Sway of Illusion").supported
    _w1g6_resolve_sway(game, "U")

    assert sorted(game._effective_colors(mine[0])) == ["G"]
    assert [card.name for card in game.players[0].hand] == ["Forest"]
