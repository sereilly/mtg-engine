"""Urza's Legacy sorceries.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: zones — hands, graveyards, libraries ---
from engine import Game, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

from tests.helpers import resolve_stack


def _g5_game(p1: PlayerState, p2: PlayerState) -> Game:
    """Two seats, no mana enforcement, nobody interactive.

    Headless seats are what let a pending choice take its registered default
    rather than sitting owed — every card in this block asks somebody
    something.
    """
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_w1g5_ostracize_offers_only_the_creature_cards_in_the_revealed_hand(set_pool):
    """"You choose a **creature card** from it." The picker's whole restriction,
    and the reason it is a picker restriction rather than a handler one: what is
    offered and what an answer is checked against are one predicate, so a type
    only the handler knew about would be a client offering the whole hand.

    The refusal that stood before this said so outright — "the revealed-hand
    picker cannot narrow by: card_types" — which is the lowering refusing rather
    than dropping the adjective, the direction this repo asks for.
    """
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    victim = PlayerState(
        name="P2",
        hand=[lea["Mountain"], lea["Shivan Dragon"], lea["Lightning Bolt"]],
    )
    game = _g5_game(PlayerState(name="P1", hand=[pool["Ostracize"]]), victim)

    result = game.cast_from_hand(0, "Ostracize", target_player_index=1)
    resolve_stack(game)

    assert result.supported is True
    owed = [c for c in game.pending_choices if c.kind == "revealed_hand_pick"]
    assert len(owed) == 1
    # Slot 1 is the Shivan Dragon; the Mountain and the Bolt are not offered.
    assert list(owed[0].data["legal_indices"]) == [1]

    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].graveyard] == ["Shivan Dragon"]
    assert [c.name for c in game.players[1].hand] == ["Mountain", "Lightning Bolt"]


def test_w1g5_ostracize_with_no_creature_in_hand_asks_nothing(set_pool):
    """A choice with no legal answer is not a choice — the handler queues
    nothing rather than blocking the caster on a prompt they cannot satisfy."""
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    victim = PlayerState(name="P2", hand=[lea["Mountain"], lea["Lightning Bolt"]])
    game = _g5_game(PlayerState(name="P1", hand=[pool["Ostracize"]]), victim)

    game.cast_from_hand(0, "Ostracize", target_player_index=1)
    resolve_stack(game)

    assert [c.kind for c in game.pending_choices] == []
    assert game.players[1].graveyard == []
    assert len(game.players[1].hand) == 2


def test_w1g5_unearth_derives_a_picker_that_reads_its_printed_mana_bound(set_pool):
    """The Roots class, on a card that reported **supported** the whole time —
    its cycling line carried it while the return sentence lowered to nothing.

    A cast spec of None is what the client tests to decide whether to ask for a
    target, so the browser sent a bare cast and the engine refused it: a
    supported card no player could put on the battlefield.
    """
    card = set_pool("ULG")["Unearth"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {
        "kind": "graveyard_creature",
        "own_graveyard_only": True,
        "graveyard_mana_value": {"op": "le", "value": 3},
    }


def test_w1g5_unearth_reanimates_a_cheap_creature(set_pool):
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    caster = PlayerState(
        name="P1", hand=[pool["Unearth"]],
        graveyard=[lea["Grizzly Bears"], lea["Shivan Dragon"]],
    )
    game = _g5_game(caster, PlayerState(name="P2"))

    result = game.cast_from_hand(
        0, "Unearth", target_player_index=0, target_permanent_index=0,
    )
    resolve_stack(game)

    assert result.supported is True
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [c.name for c in caster.graveyard] == ["Shivan Dragon", "Unearth"]


def test_w1g5_unearth_refuses_a_creature_over_the_printed_bound(set_pool):
    """A printed restriction is only done when something enforces it, and the
    enforcement is CR 601.2c at announcement: the target is refused with the
    spell still in hand, not admitted and then declined at resolution."""
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    caster = PlayerState(
        name="P1", hand=[pool["Unearth"]], graveyard=[lea["Shivan Dragon"]],
    )
    game = _g5_game(caster, PlayerState(name="P2"))

    result = game.cast_from_hand(
        0, "Unearth", target_player_index=0, target_permanent_index=0,
    )

    assert result.supported is False
    assert game.players[0].battlefield == []
    assert [c.name for c in caster.graveyard] == ["Shivan Dragon"]
    assert [c.name for c in caster.hand] == ["Unearth"]
