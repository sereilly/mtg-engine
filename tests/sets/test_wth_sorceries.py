"""Weatherlight sorceries.

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
from engine.oracle import compile_card_oracle as _w1g5_compile


def _w1g5_game(interactive=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def test_gerrards_wisdom_counts_the_caster_s_hand_and_not_their_board(set_pool):
    """"You gain 2 life for each card in your hand."

    The refusal named the bug exactly — "the per-each life gain counts the
    gainer's own battlefield" — and the branch behind it read *graveyard*, for
    Spoils of Evil's sentence, and refused every other zone. The count spec is
    the one `count_spec` builds for any zone, so a hand is not a widening of
    what a count may read; it was a second spelling of that function refusing
    to read it.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5_compile(wth["Gerrard's Wisdom"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.payload["per_each"] == {
        "zone": "hand", "owner": "you", "filter": {},
    }

    game = _w1g5_game()
    game.players[0].hand = [
        wth["Gerrard's Wisdom"], lea["Forest"], lea["Grizzly Bears"],
    ]
    # A board full of permanents the old branch would have counted instead.
    game.players[0].battlefield = []
    game.cast_from_hand(0, "Gerrard's Wisdom")
    game.resolve_stack()

    # Two cards left in hand after the spell was cast: 2 life each.
    assert game.players[0].life == 24, game.log


def test_natures_resurgence_counts_each_players_own_graveyard(set_pool):
    """"Each player draws a card for each creature card in their graveyard."

    "Their" is one number per seat. `draw_target_cards`' looping branch
    resolves ``amount`` once, so a shared count would have handed everybody the
    same number — and `amount: "x"` with no announced X is zero, which is a
    card that compiles supported and draws nothing.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5_compile(wth["Nature's Resurgence"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.payload["recipient"] == "each_player"
    assert "amount" not in instruction.payload, instruction.payload
    assert instruction.payload["x_from_count_per_recipient"] == {
        "zone": "graveyard", "owner": "owner", "filter": {"type_filter": "creature"},
    }

    game = _w1g5_game()
    game.players[0].hand = [wth["Nature's Resurgence"]]
    game.players[0].graveyard = [
        lea["Grizzly Bears"], lea["Grizzly Bears"], lea["Lightning Bolt"],
    ]
    game.players[1].graveyard = [lea["Grizzly Bears"]]
    game.players[0].library = [lea["Forest"]] * 10
    game.players[1].library = [lea["Forest"]] * 10

    game.cast_from_hand(0, "Nature's Resurgence")
    game.resolve_stack()

    # Two creature cards in one graveyard, one in the other — and the Bolt is
    # not counted.
    assert len(game.players[0].hand) == 2, game.log
    assert len(game.players[1].hand) == 1, game.log


def test_flux_lets_every_seat_choose_and_draws_each_of_them_their_own_number(set_pool):
    """"Each player discards any number of cards, then draws that many cards."

    Both halves are per seat, and the second reads the first. The card reported
    *supported* before this round because its other line is a cantrip — only
    `parse_coverage.py` could see the sentence at all.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5_compile(wth["Flux"])
    assert program.supported, program.reason
    sequence = program.instructions[0]
    discard, draw = sequence.payload["steps"]
    assert discard.kind == "each_player_discards_up_to_cards"
    assert discard.payload["any_number"] is True
    assert draw.payload["x_from_count_per_recipient"] == {
        "seat_record": "discarded_by_seat",
    }

    # P2 answers for itself and keeps a card; P1 takes the default.
    game = _w1g5_game(interactive={1})
    game.players[0].hand = [wth["Flux"], lea["Grizzly Bears"], lea["Forest"]]
    game.players[1].hand = [lea["Mountain"], lea["Mountain"], lea["Plains"]]
    game.players[0].library = [lea["Island"]] * 20
    game.players[1].library = [lea["Island"]] * 20

    game.cast_from_hand(0, "Flux")
    game.resolve_stack()
    # Every seat is asked, and the game waits: the whole point of the prompt is
    # that a later step of the same resolution reads its answer (CR 608.2).
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("discard", 0), ("discard", 1),
    ]
    assert game.waiting_prompt() is not None

    game.auto_resolve_pending_choices(only_player_index=0)
    assert game.confirm_discard(1, [0, 1]), game.log

    # Two pitched, two drawn, plus the printed cantrip for the caster.
    assert [c.name for c in game.players[0].hand] == ["Island"] * 3, game.log
    assert [c.name for c in game.players[1].hand] == ["Plains", "Island", "Island"]
    assert game.stack == [] and game.resume_stack == []


def test_flux_draws_a_seat_nothing_when_it_discarded_nothing(set_pool):
    """An empty hand discards none and draws none — the record is a zero rather
    than a missing key, which is what stops the seat reading somebody else's
    answer."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w1g5_game()
    game.players[0].hand = [wth["Flux"], lea["Grizzly Bears"]]
    game.players[1].hand = []
    game.players[0].library = [lea["Island"]] * 20
    game.players[1].library = [lea["Island"]] * 20

    game.cast_from_hand(0, "Flux")
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert [c.name for c in game.players[0].hand] == ["Island", "Island"], game.log
    assert game.players[1].hand == [], game.log
