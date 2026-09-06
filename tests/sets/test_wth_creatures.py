"""Weatherlight creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G5: each player, in parallel ---
from engine import Game, PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5c_compile


def _w1g5c_game(interactive=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g5c_kill(game, perm, lea):
    """Bolt *perm* and let its dies-trigger resolve, draining every prompt."""
    game.players[0].hand = [lea["Lightning Bolt"]]
    game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(perm),
    )
    game.resolve_stack()
    game._settle()
    game.resolve_stack()


def test_veteran_explorer_gives_every_seat_two_basics_off_its_own_library(set_pool):
    """"When this creature dies, each player may search their library for up to
    two basic land cards, put them onto the battlefield, then shuffle."

    The whole per-seat machinery was already here — `may` loops the seats
    through `run_resumable` and `_offer_to_seat` rebinds ``caster``, so the
    search inside opens the *offered* seat's library. What refused the card was
    one word: the search production expected "your" and the card prints
    "their", which is the pronoun agreeing with the subject the offer above it
    already named.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5c_compile(wth["Veteran Explorer"])
    assert program.supported, program.reason
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may" and offer.payload["actor"] == "each_player"
    (search,) = offer.payload["action"]
    assert search.kind == "search_library"
    assert search.payload["destinations"] == ["battlefield", "battlefield"]
    assert search.payload["restrictions"] == {"supertypes": ["basic"]}

    game = _w1g5c_game()
    explorer = _W1G5Permanent(card=wth["Veteran Explorer"])
    game.players[0].battlefield.append(explorer)
    game._sync_control()
    game.players[0].library = [lea["Forest"], lea["Grizzly Bears"], lea["Plains"]] * 4
    game.players[1].library = [lea["Mountain"], lea["Lightning Bolt"], lea["Island"]] * 4

    _w1g5c_kill(game, explorer, lea)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    # Each seat's own basics, off its own library — and the nonland cards in
    # both libraries are untouched.
    assert sorted(p.card.name for p in game.players[0].battlefield) == [
        "Forest", "Plains",
    ], game.log
    assert sorted(p.card.name for p in game.players[1].battlefield) == [
        "Island", "Mountain",
    ], game.log


def test_noble_benefactor_shuffles_only_the_seats_that_searched(set_pool):
    """"…each player may search their library for a card and put that card into
    their hand. Then each player who searched their library this way shuffles."

    The second sentence is CR 701.23c's shuffle, printed as a following
    sentence because the search it ends was offered to a *set* of seats and the
    words have to say which of them shuffle. This engine performs the shuffle
    inside the search prompt, so the set the sentence names is exactly the set
    the offer armed a prompt for — a seat that declines the "may" never
    searched, is never prompted, and its library is left alone.

    Natural Balance prints the same sentence word for word, which is why it is
    a production rather than a hook.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5c_compile(wth["Noble Benefactor"])
    assert program.supported, program.reason
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may" and offer.payload["actor"] == "each_player"
    (search,) = offer.payload["action"]
    assert search.kind == "search_library"
    assert search.payload == {"count": 1, "card_type": "any"}

    game = _w1g5c_game(interactive={1})
    benefactor = _W1G5Permanent(card=wth["Noble Benefactor"])
    game.players[0].battlefield.append(benefactor)
    game._sync_control()
    game.players[0].library = [lea["Forest"], lea["Grizzly Bears"]] * 4
    ordered = [lea["Mountain"], lea["Island"], lea["Plains"]] * 3
    game.players[1].library = list(ordered)

    _w1g5c_kill(game, benefactor, lea)
    # P1 takes the default offer and searches; P2 is asked and declines.
    game.auto_resolve_pending_choices(only_player_index=0)
    owed = game.pending_choice_of("optional_pay")
    assert owed is not None and owed.player_index == 1, game.pending_choices
    assert game.confirm_optional_pay(1, accept=False), game.log
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 1, game.log
    assert game.players[1].hand == [], game.log
    # The declining seat never searched, so nothing shuffled its library.
    assert [c.name for c in game.players[1].library] == [
        c.name for c in ordered
    ], game.log
