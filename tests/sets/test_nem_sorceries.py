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


def _w1g5_gambit(set_pool, a_hand, b_hand, *, interactive=()):
    """Stronghold Gambit cast by seat 0 and resolved as far as it goes.
    Headless seats take the stated default — the first card in hand order.
    W1G5's own."""
    me = _W1G5PlayerState(
        name="W1G5-A", hand=[set_pool("NEM")["Stronghold Gambit"], *a_hand]
    )
    them = _W1G5PlayerState(name="W1G5-B", hand=list(b_hand))
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    assert game.cast_from_hand(0, "Stronghold Gambit").supported
    game.resolve_top_of_stack()
    return game, me, them


def _w1g5_names_on(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g5_stronghold_gambit_lowest_revealed_creature_enters(set_pool):
    """"Each player chooses a card in their hand. Then each player reveals
    their chosen card. The owner of each creature card revealed this way with
    the lowest mana value puts it onto the battlefield."

    Seat 0 shows a two-drop and seat 1 a three-drop: only the two-drop enters,
    under its owner, and the three-drop goes back to being a card in a hand —
    revealed, not spent. Both reveals reach the web layer's feed.
    """
    nem = set_pool("NEM")
    game, me, them = _w1g5_gambit(
        set_pool, [nem["Mogg Toady"], nem["Wild Mammoth"]], [nem["Wild Mammoth"]],
    )
    game._settle()

    assert _w1g5_names_on(game, 0) == ["Mogg Toady"]
    assert _w1g5_names_on(game, 1) == []
    assert [c.name for c in them.hand] == ["Wild Mammoth"]
    assert [c.name for c in me.graveyard] == ["Stronghold Gambit"]
    assert [(e["seat"], e["cards"]) for e in game.reveal_events] == [
        (0, ["Mogg Toady"]), (1, ["Wild Mammoth"]),
    ]


def test_w1g5_stronghold_gambit_ties_all_enter_and_lands_do_not_compete(set_pool):
    """"**Each** creature card … with the lowest mana value": two two-drops
    tie and both enter, each on its owner's side. And a revealed land is not a
    creature card, so its mana value of 0 is not "the lowest" — the Mammoth
    across from it enters alone."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, _, _ = _w1g5_gambit(set_pool, [nem["Mogg Toady"]], [nem["Shrieking Mogg"]])
    game._settle()
    assert _w1g5_names_on(game, 0) == ["Mogg Toady"]
    assert _w1g5_names_on(game, 1) == ["Shrieking Mogg"]

    game, me, _ = _w1g5_gambit(set_pool, [lea["Forest"]], [nem["Wild Mammoth"]])
    game._settle()
    assert _w1g5_names_on(game, 0) == []
    assert [c.name for c in me.hand] == ["Forest"]
    assert _w1g5_names_on(game, 1) == ["Wild Mammoth"]


def test_w1g5_stronghold_gambit_keeps_a_pick_hidden_until_the_reveal(set_pool):
    """CR 101.4a: a card chosen out of a hand may stay face down as it is
    chosen. Seat 1 (headless) has chosen by the time seat 0 is asked, and the
    public log says only *that* it chose — the card is named by the reveal,
    after seat 0 answers. The spell stays on the stack until then (CR 608.2)."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, me, _ = _w1g5_gambit(
        set_pool, [lea["Forest"], nem["Wild Mammoth"]], [nem["Rhox"]], interactive=(0,),
    )
    pick = game.pending_choice_of("choose_cards_in_hand", 0)
    assert pick is not None and game.live_choose_cards_in_hand(pick) == [0, 1]
    assert game.stack, "the sorcery is still resolving"
    assert not any("Rhox" in line for line in game.log), "seat 1's pick is face down"
    assert any("W1G5-B chose 1 card(s)" in line for line in game.log)

    assert game.confirm_choose_cards_in_hand(0, [1])
    game._settle()

    assert any("W1G5-B reveals Rhox" in line for line in game.log)
    assert _w1g5_names_on(game, 0) == ["Wild Mammoth"]
    assert [c.name for c in me.hand] == ["Forest"]


def test_w1g5_stronghold_gambit_waits_for_every_seat_in_any_order(set_pool):
    """Two interactive seats owe a pick at once. The first answer (seat 1's,
    out of turn order) reveals nothing and moves nothing: the sorcery resolves
    only when the last seat has chosen, and then compares both cards."""
    nem, lea = set_pool("NEM"), set_pool("LEA")
    game, me, them = _w1g5_gambit(
        set_pool, [nem["Rhox"], nem["Mogg Toady"]], [nem["Wild Mammoth"], lea["Forest"]],
        interactive=(0, 1),
    )
    owed = sorted(c.player_index for c in game.pending_choices if c.kind == "choose_cards_in_hand")
    assert owed == [0, 1]

    assert game.confirm_choose_cards_in_hand(1, [0])
    assert game.stack and game.reveal_events == [], "nothing is revealed yet"
    assert game.confirm_choose_cards_in_hand(0, [0])
    game._settle()

    assert not game.stack
    assert _w1g5_names_on(game, 1) == ["Wild Mammoth"], "3 beats 6"
    assert sorted(c.name for c in me.hand) == ["Mogg Toady", "Rhox"]


def test_w1g5_stronghold_gambit_an_empty_hand_chooses_nothing(set_pool):
    """A player with no cards in hand makes no choice and reveals nothing; the
    other player's card still competes alone."""
    game, _, _ = _w1g5_gambit(set_pool, [set_pool("NEM")["Wild Mammoth"]], [])
    game._settle()
    assert _w1g5_names_on(game, 0) == ["Wild Mammoth"]
    assert [e["seat"] for e in game.reveal_events] == [0]
