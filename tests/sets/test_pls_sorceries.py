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


# --- W1G3: revealed cards ---
# Noxious Vapors: "Each player reveals their hand, chooses one card of each
# color from it, then discards all other nonland cards." Amnesia for every
# seat with a choice in the middle of it — and the choice is an *assignment*
# (one card per colour, a gold card filling one of its colours), which is
# Global Ruin's keep-then-sacrifice one zone over.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_vapors_table(set_pool, *hands, interactive=()):
    """One seat per hand, seat 0 also holding Noxious Vapors; names are read
    from PLS, then LEA. It is seat 0's main phase. Returns the game and a
    name -> card lookup."""
    pools = [set_pool(code) for code in ("PLS", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_players = [
        _W1G3PlayerState(
            name="ABC"[seat], hand=[w1g3_card(name) for name in held],
            library=[w1g3_card("Forest")] * 6,
        )
        for seat, held in enumerate(hands)
    ]
    w1g3_players[0].hand.insert(0, w1g3_card("Noxious Vapors"))
    w1g3_game = _W1G3Game(players=w1g3_players)
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set(interactive)
    w1g3_game.start_turn(0)
    return w1g3_game, w1g3_card  # _w1g3_vapors_table


def _w1g3_zone(cards):
    return sorted(card.name for card in cards)  # _w1g3_zone


def test_w1g3_noxious_vapors_keeps_one_card_of_each_colour_and_every_land(set_pool):
    """The whole sentence, with nobody asked (the stated default: a maximum
    keep, in hand order). A keeps one red card of three and the one blue card,
    and the Forest, which is no colour and is not a nonland card; the second
    Lightning Bolt, the Shivan Dragon and the colourless Sol Ring go. B keeps
    the green Bears and the Swamp and loses the Black Lotus."""
    game, _card = _w1g3_vapors_table(
        set_pool,
        ["Lightning Bolt", "Lightning Bolt", "Counterspell", "Forest", "Sol Ring",
         "Shivan Dragon"],
        ["Grizzly Bears", "Swamp", "Black Lotus"],
    )
    mine, theirs = game.players

    result = game.cast_from_hand(0, "Noxious Vapors")
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g3_zone(mine.hand) == ["Counterspell", "Forest", "Lightning Bolt"]
    assert _w1g3_zone(mine.graveyard) == [
        "Lightning Bolt", "Noxious Vapors", "Shivan Dragon", "Sol Ring",
    ]
    assert _w1g3_zone(theirs.hand) == ["Grizzly Bears", "Swamp"]
    assert _w1g3_zone(theirs.graveyard) == ["Black Lotus"]
    # CR 701.20a: both hands were made public, card by card.
    assert any(
        line == "B reveals their hand: Grizzly Bears, Swamp, Black Lotus"
        for line in game.log
    ), game.log


def test_w1g3_noxious_vapors_holds_each_players_answer_to_one_card_per_colour(set_pool):
    """Each player owes a pick of their own, and the engine checks it: two red
    cards are the right number and the wrong answer, one card is too few (the
    hand can fill red *and* blue), and a land is no colour. The discard waits
    for the last seat's answer and spares exactly the slot named — the *other*
    Lightning Bolt goes, though it is the same card."""
    game, _card = _w1g3_vapors_table(
        set_pool,
        ["Lightning Bolt", "Lightning Bolt", "Counterspell", "Forest"],
        ["Grizzly Bears", "Shivan Dragon"],
        interactive=(0, 1),
    )
    mine, theirs = game.players
    game.queue_from_hand(0, "Noxious Vapors")
    game.resolve_top_of_stack()

    owed = [c for c in game.pending_choices if c.kind == "choose_cards_in_hand"]
    assert sorted(c.player_index for c in owed) == [0, 1]
    assert game.live_choose_cards_in_hand(owed[0]) == [0, 1, 2], "never the Forest"
    assert game._how_many_cards_to_choose(owed[0]) == 2
    assert not game.confirm_choose_cards_in_hand(0, [0, 1]), "two red cards"
    assert not game.confirm_choose_cards_in_hand(0, [2]), "a red card could be kept"
    assert not game.confirm_choose_cards_in_hand(0, [2, 3]), "a land is no colour"
    assert game.confirm_choose_cards_in_hand(0, [1, 2])

    assert len(mine.hand) == 4 and not mine.graveyard, "B has not answered yet"
    assert game.confirm_choose_cards_in_hand(1, [1, 0])
    _w1g3_resolve_stack(game)

    assert _w1g3_zone(mine.hand) == ["Counterspell", "Forest", "Lightning Bolt"]
    assert _w1g3_zone(mine.graveyard) == ["Lightning Bolt", "Noxious Vapors"]
    assert _w1g3_zone(theirs.hand) == ["Grizzly Bears", "Shivan Dragon"]
    assert not theirs.graveyard


def test_w1g3_noxious_vapors_counts_a_gold_card_for_one_of_its_colours(set_pool):
    """A multicoloured card fills one slot. Doomsday Specter is blue and black:
    beside a Counterspell it is the black card and both are kept; two Specters
    and a Counterspell are three cards for two colours, so one is discarded —
    and the answer naming all three is refused."""
    game, _card = _w1g3_vapors_table(
        set_pool, ["Doomsday Specter", "Counterspell"], [],
    )
    game.cast_from_hand(0, "Noxious Vapors")
    _w1g3_resolve_stack(game)
    assert _w1g3_zone(game.players[0].hand) == ["Counterspell", "Doomsday Specter"]

    game, _card = _w1g3_vapors_table(
        set_pool, ["Doomsday Specter", "Doomsday Specter", "Counterspell"], [],
        interactive=(0,),
    )
    mine = game.players[0]
    game.queue_from_hand(0, "Noxious Vapors")
    game.resolve_top_of_stack()
    owed = next(c for c in game.pending_choices if c.kind == "choose_cards_in_hand")

    assert game._how_many_cards_to_choose(owed) == 2
    assert not game.confirm_choose_cards_in_hand(0, [0, 1, 2])
    assert game.confirm_choose_cards_in_hand(0, [0, 1]), "one as blue, one as black"
    _w1g3_resolve_stack(game)

    assert _w1g3_zone(mine.hand) == ["Doomsday Specter", "Doomsday Specter"]
    assert _w1g3_zone(mine.graveyard) == ["Counterspell", "Noxious Vapors"]


def test_w1g3_noxious_vapors_asks_nothing_of_a_hand_with_no_colour_in_it(set_pool):
    """A hand of lands and artifacts has no card of any colour: nothing is
    chosen, no prompt is armed for that seat, the lands stay and every nonland
    card is discarded. An empty hand is asked nothing either."""
    game, _card = _w1g3_vapors_table(
        set_pool, ["Forest", "Sol Ring", "Black Lotus"], [], interactive=(0, 1),
    )
    mine, theirs = game.players

    game.queue_from_hand(0, "Noxious Vapors")
    _w1g3_resolve_stack(game)

    assert not game.pending_choices
    assert _w1g3_zone(mine.hand) == ["Forest"]
    assert _w1g3_zone(mine.graveyard) == ["Black Lotus", "Noxious Vapors", "Sol Ring"]
    assert not theirs.hand and not theirs.graveyard
