"""Planeshift sorceries.

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


# --- W1G4: domain ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve

_W1G4_FIVE = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _w1g4_sorcery_table(set_pool, spell, mine=(), theirs=(), interactive=()):
    """*spell* in seat 0's hand over two boards of Alpha permanents, each seat
    with a library to draw from (a draw off an empty one loses the game and
    would hide what the spell did)."""
    w1g4_pls, w1g4_lea = set_pool("PLS"), set_pool("LEA")
    w1g4_game = _W1G4Game(players=[
        _W1G4PlayerState(name="W1G4-A", hand=[w1g4_pls[spell]]),
        _W1G4PlayerState(name="W1G4-B"),
    ])
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_game.interactive_seats = set(interactive)
    for w1g4_player in w1g4_game.players:
        w1g4_player.library = [w1g4_lea["Grizzly Bears"]] * 20
    w1g4_rows = []
    for w1g4_seat, w1g4_names in enumerate((mine, theirs)):
        w1g4_row = []
        for w1g4_name in w1g4_names:
            w1g4_perm = _W1G4Permanent(card=w1g4_lea[w1g4_name])
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_row.append(w1g4_perm)
        w1g4_rows.append(w1g4_row)
    return w1g4_game, w1g4_rows[0], w1g4_rows[1]  # _w1g4_sorcery_table


def _w1g4_land_names(game, seat):
    return sorted(
        w1g4_perm.card.name for w1g4_perm in game.controlled_by(seat)
    )  # _w1g4_land_names


def test_w1g4_allied_strategies_offers_a_player(set_pool):
    card = set_pool("PLS")["Allied Strategies"]
    program = _w1g4_compile(card)
    assert program.supported, program.reason
    assert _w1g4_cast_spec(card, program) == {"kind": "player"}


def test_w1g4_allied_strategies_counts_the_targets_lands_not_the_casters(set_pool):
    """"Target player draws a card for each basic land type among lands
    **they** control." Aimed at an opponent holding three types on four lands
    it draws them three, whatever the caster's five types are."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
        theirs=["Forest", "Forest", "Tropical Island", "Mountain"],
    )
    cast = game.cast_from_hand(0, "Allied Strategies", target_player_index=1)
    assert cast.supported, cast.details
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 3]
    assert "W1G4-B drew 3 cards" in game.log


def test_w1g4_allied_strategies_aimed_at_its_caster_draws_their_domain(set_pool):
    """The same sentence with the caster as the target: five types, five
    cards — and the opponent's single Forest is nobody's draw."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE, theirs=["Forest"],
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=0).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [5, 0]


def test_w1g4_allied_strategies_counts_at_resolution_and_types_not_lands(set_pool):
    """CR 608.2h: counted once, as the spell resolves — a dual land that
    arrives while it is on the stack adds its two types, and four Forests
    beside it are still one."""
    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", theirs=["Forest"] * 4,
    )
    assert game.queue_from_hand(0, "Allied Strategies", target_player_index=1).supported
    game._put_permanent_onto_battlefield(
        1, _W1G4Permanent(card=set_pool("LEA")["Badlands"]), None
    )
    _w1g4_resolve(game)
    assert len(game.players[1].hand) == 3

    game, _mine, _theirs = _w1g4_sorcery_table(
        set_pool, "Allied Strategies", mine=_W1G4_FIVE,
    )
    assert game.cast_from_hand(0, "Allied Strategies", target_player_index=1).supported
    _w1g4_resolve(game)
    assert [len(player.hand) for player in game.players] == [0, 0], (
        "a target with no lands draws nothing"
    )


def test_w1g4_they_control_binds_only_to_a_chosen_player():
    """The rewrite is for the player the sentence *targeted*. "Each player …
    they control" and "you … they control" name no chosen seat, and the count
    refuses rather than falling back to whichever board the resolution held."""
    from engine.grammar import compile_line

    bound = compile_line("Target opponent draws a card for each creature they control.")
    assert bound.usable
    assert bound.instructions[0].payload["x_from_count"]["owner"] == "target_player"
    for line in (
        "Each player draws a card for each land they control.",
        "You draw a card for each land they control.",
    ):
        assert not compile_line(line).usable, line
