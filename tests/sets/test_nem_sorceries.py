"""Nemesis sorceries.

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


# --- W1G5: library, hand and graveyard ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent


def _w1g5_pack_hunt(set_pool, library, *, targets=("Mogg Toady",)):
    """Pack Hunt in seat 0's hand, *targets* on seat 1's battlefield in order.
    W1G5's own."""
    nem = set_pool("NEM")
    me = _W1G5PlayerState(name="W1G5-A", hand=[nem["Pack Hunt"]], library=list(library))
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    pool = {**set_pool("LEA"), **nem}
    for name in targets:
        game._put_permanent_onto_battlefield(1, _W1G5Permanent(card=pool[name]), None)
    game.auto_resolve_pending_choices()
    return game, me


def test_w1g5_pack_hunt_finds_up_to_three_of_the_targets_name(set_pool):
    """"Search your library for up to three cards with the same name as target
    creature, reveal them, put them into your hand, then shuffle."

    Four Mogg Toadies in the library and three are taken; the Forest is refused
    as an answer, because the name is the target's and the search asks it.
    """
    nem, lea = set_pool("NEM"), set_pool("LEA")
    toady = nem["Mogg Toady"]
    game, me = _w1g5_pack_hunt(
        set_pool, [toady, lea["Forest"], toady, nem["Wild Mammoth"], toady, toady],
    )
    assert game.cast_target_spec(0, nem["Pack Hunt"])["kind"] == "creature"
    assert game.cast_from_hand(
        0, "Pack Hunt", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_top_of_stack()

    search = game.pending_choice_of("search_library", 0)
    assert search.data["restrictions"]["named"] == "Mogg Toady"
    assert search.data["count"] == 3 and search.data["up_to"]
    assert not game.confirm_search_library_picks(0, [{"zone": "library", "index": 1}])
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 2, 4)]
    )
    game._settle()

    assert [c.name for c in me.hand] == ["Mogg Toady"] * 3
    assert sorted(c.name for c in me.library) == ["Forest", "Mogg Toady", "Wild Mammoth"]
    assert [c.name for c in me.graveyard] == ["Pack Hunt"]


def test_w1g5_pack_hunt_may_find_fewer(set_pool):
    """"Up to three" is a ceiling (CR 701.23b): one copy in the library is a
    legal whole answer, and so is none."""
    nem = set_pool("NEM")
    game, me = _w1g5_pack_hunt(set_pool, [nem["Mogg Toady"], nem["Wild Mammoth"]])
    game.cast_from_hand(0, "Pack Hunt", target_player_index=1, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(0, [{"zone": "library", "index": 0}])
    game._settle()
    assert [c.name for c in me.hand] == ["Mogg Toady"]


def test_w1g5_pack_hunt_reads_a_copys_name(set_pool):
    """The name is the target's *current* one (CR 707.2 copies the name): a
    Clone copying Mogg Toady is named Mogg Toady, so that is what the search
    looks for — not "Clone", which is only the printed face."""
    nem = set_pool("NEM")
    game, me = _w1g5_pack_hunt(
        set_pool, [nem["Mogg Toady"], set_pool("LEA")["Clone"]],
        targets=("Mogg Toady", "Clone"),
    )
    (clone,) = [p for p in game.controlled_by(1) if p.card.name == "Clone"]
    assert clone.effective_card.name == "Mogg Toady"
    index = game.battlefield_index_of(clone)
    game.cast_from_hand(
        0, "Pack Hunt", target_player_index=1, target_permanent_index=index
    )
    game.resolve_top_of_stack()
    assert game.pending_choice_of("search_library", 0).data["restrictions"]["named"] == (
        "Mogg Toady"
    )
