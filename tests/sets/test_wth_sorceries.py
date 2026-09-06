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


def _w1g5_put(game, seat, card):
    from engine.models import Permanent

    perm = Permanent(card=card)
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_tariff_takes_each_seat_s_own_biggest_creature(set_pool):
    """"Each player sacrifices the creature they control with the greatest mana
    value unless they pay that creature's mana cost."

    One instruction whose handler is the loop, because "each player" is a
    number of *pairs* of steps only the resolution knows. Every step it builds
    is one the engine already dispatches: Juxtapose's `choose_permanent` with
    `greatest_mana_value` and `only_on_tie`, and Flash's `may` whose cost is
    read off what that step recorded, with Retribution's
    `sacrifice_recorded_permanent` on the decline.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w1g5_compile(wth["Tariff"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "each_player_pays_or_sacrifices_greatest"
    assert instruction.payload == {"card_type": "creature"}

    game = _w1g5_game()
    game.active_player_index = 0
    _w1g5_put(game, 0, lea["Grizzly Bears"])
    _w1g5_put(game, 0, lea["Shivan Dragon"])
    _w1g5_put(game, 1, lea["Craw Wurm"])
    _w1g5_put(game, 1, lea["Mons's Goblin Raiders"])
    game.players[0].hand = [wth["Tariff"]]

    game.cast_from_hand(0, "Tariff")
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    # Each seat lost its own greatest-mana-value creature and kept the rest.
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [p.card.name for p in game.players[1].battlefield] == [
        "Mons's Goblin Raiders"
    ], game.log


def test_tariff_offers_the_creature_s_own_mana_cost_to_its_own_controller(set_pool):
    """The toll is "**that** creature's mana cost" — unprinted, and different
    for every seat. Paying it keeps the creature."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w1g5_game(interactive={1})
    game.active_player_index = 0
    _w1g5_put(game, 0, lea["Shivan Dragon"])
    _w1g5_put(game, 1, lea["Craw Wurm"])
    game.players[1].mana_pool = {
        "W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 4,
    }
    game.players[0].hand = [wth["Tariff"]]

    game.cast_from_hand(0, "Tariff")
    game.resolve_stack()

    owed = game.pending_choice_of("optional_pay")
    assert owed is not None and owed.player_index == 1, game.pending_choices
    assert owed.data["prompt"] == "Pay {4}{G}{G}?", owed.data
    assert game.confirm_optional_pay(1, accept=True), game.log

    # The payer kept the Wurm and spent the mana; the seat that could not pay
    # lost its Dragon.
    assert [p.card.name for p in game.players[1].battlefield] == ["Craw Wurm"]
    assert not any(v for v in game.players[1].mana_pool.values()), game.players[1].mana_pool
    assert game.players[0].battlefield == [], game.log


def test_tariff_asks_the_tied_seat_which_of_its_creatures(set_pool):
    """"If two or more creatures a player controls are tied for greatest, that
    player chooses one." The prompt is asked of the seat whose creatures they
    are — and asked *only* on a tie, because with one candidate the card names
    it outright.

    Seat 0 is a seat: `controlled_by` used to be read for truthiness, so a loop
    naming the active player dropped the narrowing entirely and let that seat
    choose out of somebody else's board.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w1g5_game(interactive={1})
    game.active_player_index = 0
    _w1g5_put(game, 1, lea["Craw Wurm"])
    _w1g5_put(game, 1, lea["Force of Nature"])
    game.players[0].hand = [wth["Tariff"]]

    game.cast_from_hand(0, "Tariff")
    game.resolve_stack()

    owed = game.pending_choice_of("permanent_choice")
    assert owed is not None and owed.player_index == 1, game.pending_choices
    assert owed.data["result_key"] == "greatest_creature_seat_1"
    # Both are mana value 6, and the caster controls nothing, so it is asked
    # once and only of the seat that owns them.
    assert len(owed.data["_candidates"]) == 2, owed.data


def test_tariff_skips_a_seat_with_no_creature_rather_than_offering_it_nothing(set_pool):
    """CR 608.2b: with nothing to sacrifice there is no toll. Asked anyway it
    would be an offer to pay nothing for nothing, shown to a live player — and
    the caster here is an interactive seat with an empty board."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w1g5_game(interactive={0, 1})
    game.active_player_index = 0
    _w1g5_put(game, 1, lea["Craw Wurm"])
    game.players[1].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 2, "C": 4}
    game.players[0].hand = [wth["Tariff"]]

    game.cast_from_hand(0, "Tariff")
    game.resolve_stack()

    # Only the seat that owns a creature is asked anything at all.
    assert [c.player_index for c in game.pending_choices] == [1], game.pending_choices
