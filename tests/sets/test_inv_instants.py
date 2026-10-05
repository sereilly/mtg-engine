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


# --- W1G7: piles ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack

_W1G7_FOF_LIBRARY = (
    "Shivan Dragon", "Forest", "Lightning Bolt", "Forest", "Serra Angel", "Island",
)


def _w1g7_fof_table(set_pool, library=_W1G7_FOF_LIBRARY, interactive=()):
    """Seat 0 holding Fact or Fiction over a stacked library."""
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", hand=[inv["Fact or Fiction"]],
            library=[lea[name] for name in library],
        ),
        _W1G7PlayerState(name="P2"),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    w1g7_table_ready = game
    return w1g7_table_ready


def _w1g7_zone_names(cards):
    w1g7_names = [card.name for card in cards]
    return w1g7_names


def test_w1g7_fact_or_fiction_an_opponent_separates_and_the_caster_takes_a_pile(set_pool):
    """"Reveal the top five cards of your library. An opponent separates those
    cards into two piles. Put one pile into your hand and the other into your
    graveyard."

    CR 700.3 with two seats and two decisions, in that order: the **opponent**
    separates, then the **caster** chooses, and the game waits on each (CR
    608.2) — the spell is still on the stack while either is owed. Nothing
    moves at the split (CR 700.3c); the sixth card never leaves the library.
    """
    program = _w1g7_compile(set_pool("INV")["Fact or Fiction"])
    assert program.supported, program.reason

    game = _w1g7_fof_table(set_pool, interactive=[0, 1])
    assert game.cast_from_hand(0, "Fact or Fiction").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    split = game.pending_choice_of("pile_split", 1)
    assert split is not None, "the separation is owed by the opponent"
    assert [c.kind for c in game.pending_choices] == ["pile_split"]
    assert game.stack and game.waiting_prompt() is not None
    assert len(game.players[0].library) == 6, "a pile is not a zone: nothing moved"
    # Not the caster's to answer, no position twice, no position off the end.
    assert not game.confirm_pile_split(0, [0])
    assert not game.confirm_pile_split(1, [0, 0])
    assert not game.confirm_pile_split(1, [5])
    # The two Forests are one ``CardDefinition`` object, as two copies in a
    # deck always are — and they go into *different* piles, which only a
    # position can say.
    assert game.confirm_pile_split(1, [0, 1])

    choice = game.pending_choice_of("pile_choice", 0)
    assert choice is not None, "the choice is owed by the caster"
    assert game.stack, "still resolving"
    assert not game.confirm_pile_choice(1, 0)
    assert not game.confirm_pile_choice(0, 2)
    assert game.confirm_pile_choice(0, 1)

    caster = game.players[0]
    assert _w1g7_zone_names(caster.hand) == ["Lightning Bolt", "Forest", "Serra Angel"]
    assert _w1g7_zone_names(caster.graveyard) == [
        "Shivan Dragon", "Forest", "Fact or Fiction",
    ]
    assert _w1g7_zone_names(caster.library) == ["Island"]
    assert not game.stack and not game.pending_choices


def test_w1g7_fact_or_fiction_an_empty_pile_is_a_legal_separation(set_pool):
    """CR 700.3d: a pile can contain zero objects. Five-and-none is a real
    separation, and it makes the caster choose between everything and nothing —
    here they take nothing, and all five revealed cards are binned."""
    game = _w1g7_fof_table(set_pool, interactive=[0, 1])
    game.cast_from_hand(0, "Fact or Fiction")
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_pile_split(1, [])
    assert game.confirm_pile_choice(0, 0)

    caster = game.players[0]
    assert caster.hand == []
    assert _w1g7_zone_names(caster.graveyard) == [
        "Shivan Dragon", "Forest", "Lightning Bolt", "Forest", "Serra Angel",
        "Fact or Fiction",
    ]


def test_w1g7_fact_or_fiction_reveals_what_a_short_library_has(set_pool):
    """Three cards in the library: three are revealed and separated, and a
    headless table answers both decisions where they stand — the opponent's
    default is the most even split it can make, and the caster's reads the
    piles and takes the better one."""
    game = _w1g7_fof_table(
        set_pool, library=("Shivan Dragon", "Forest", "Lightning Bolt"),
    )
    assert game.cast_from_hand(0, "Fact or Fiction").supported
    _w1g7_resolve_stack(game)

    caster = game.players[0]
    assert caster.library == []
    # The Dragon alone outweighs a land and a one-mana spell, so the even
    # split is the Dragon against the other two and the caster takes it.
    assert _w1g7_zone_names(caster.hand) == ["Shivan Dragon"]
    assert _w1g7_zone_names(caster.graveyard) == [
        "Forest", "Lightning Bolt", "Fact or Fiction",
    ]
    assert any("reveals Shivan Dragon, Forest, Lightning Bolt" in line for line in game.log)
    assert not game.pending_choices
