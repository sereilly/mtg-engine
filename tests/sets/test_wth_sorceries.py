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


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.cast_costs import cast_announces_x
from engine.models import CardDefinition


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_misery(set_pool, graveyard):
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Haunting Misery"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_haunting_misery_announces_an_x_its_mana_cost_never_prints(set_pool):
    """CR 107.3a names four places an X can live, and Haunting Misery's is the
    *additional cost*: its printed mana cost is {1}{B}{B} with no {X} in it. A
    reader that probed only the mana cost would offer no X box and the cast
    would take CR 107.3b's default of 0 — legal, and useless."""
    misery = set_pool("WTH")["Haunting Misery"]
    assert "{X}" not in (misery.mana_cost or "")
    assert cast_announces_x(misery)


def test_haunting_misery_exiles_x_creature_cards_and_deals_x(set_pool):
    """"As an additional cost to cast this spell, exile X creature cards from
    your graveyard." The price and the damage read the *same* announced X, and
    the land in the pile is not a creature card and does not pay."""
    game = _w1g1_misery(set_pool, [
        _w1g1_card("Land", "Land"),
        _w1g1_card("Bear One", "Creature — Bear"),
        _w1g1_card("Bear Two", "Creature — Bear"),
        _w1g1_card("Bear Three", "Creature — Bear"),
    ])
    me, them = game.players
    result = game.cast_from_hand(
        0, "Haunting Misery", target_player_index=1, x_value=2
    )
    assert result.supported, result.details
    assert len(me.exile) == 2
    assert all("Bear" in card.name for card in me.exile)
    assert [
        card.name for card in me.graveyard if card.name != "Haunting Misery"
    ] == ["Land", "Bear One"]
    if game.stack:
        game.resolve_top_of_stack()
    assert them.life == 18


def test_haunting_misery_refuses_an_x_the_graveyard_cannot_pay(set_pool):
    """CR 601.2h: an unpayable cost is an uncastable spell. A graveyard holding
    one creature card cannot pay an announced X of three, and a gate that asked
    only whether *one* existed would charge one and deal three."""
    game = _w1g1_misery(set_pool, [_w1g1_card("Bear One", "Creature — Bear")])
    me, them = game.players
    result = game.cast_from_hand(
        0, "Haunting Misery", target_player_index=1, x_value=3
    )
    assert not result.supported
    assert [card.name for card in me.graveyard] == ["Bear One"]
    assert them.life == 20


def test_haunting_miserys_x_is_bounded_by_the_creature_cards_in_the_pile(set_pool):
    """CR 601.2h gives the announcement a ceiling, and it is not the mana pool:
    this X is paid in graveyard cards. The picker reads the same enumeration
    ``_unpayable_additional_cost`` refuses by, so it can neither offer an X the
    cast would reject nor hide one it would accept."""
    game = _w1g1_misery(set_pool, [_w1g1_card("Land", "Land")])
    misery = set_pool("WTH")["Haunting Misery"]
    assert game.cast_target_spec(0, misery)["max_x"] == 0, (
        "a graveyard of lands is an X of zero, not an unbounded offer"
    )
    game.players[0].graveyard.extend(
        _w1g1_card(f"Bear {n}", "Creature — Bear") for n in range(3)
    )
    assert game.cast_target_spec(0, misery)["max_x"] == 3


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


# --- W2G2: damage divided, doubled and prevented ---
from engine import Game, PlayerState
from engine.models import CardDefinition as _w2g2_card
from engine.models import Permanent as _w2g2_permanent
from engine.oracle import compile_card_oracle as _w2g2_compile


def _w2g2_bear(name: str, toughness: int = 4):
    return _w2g2_permanent(card=_w2g2_card(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": "2", "toughness": str(toughness)},
    ))


def _w2g2_cone_game(set_pool, board):
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Cone of Flame"]]),
        PlayerState(name="P2", battlefield=list(board)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_cone_of_flame_is_one_announcement_of_three_targets(set_pool):
    """"Cone of Flame deals 1 damage to any target, 2 damage to another target,
    and 3 damage to a third target."

    Three printed clauses, one instruction. Three would raise three pickers for
    one announcement (CR 601.2c settles every target at once) and only the first
    would reach the stack item — so the compiled program is the thing to pin,
    not just the outcome.
    """
    program = _w2g2_compile(set_pool("WTH")["Cone of Flame"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "deal_damage"
    assert instruction.payload["amount"] == 6, "the total it deals"
    assert instruction.payload["targets"]["shares"] == [1, 2, 3]
    assert instruction.payload["targets"]["target_count"] == 3


def test_cone_of_flame_gives_each_target_its_printed_share(set_pool):
    """The share belongs to the target it was announced against, in printed
    order — 1 to the first, 2 to the second, 3 to the third. An engine that
    divided its total evenly would deal 2 to each and be invisible to any census.
    """
    first, second = _w2g2_bear("First"), _w2g2_bear("Second")
    game = _w2g2_cone_game(set_pool, [first, second])

    result = game.queue_from_hand(
        0, "Cone of Flame", divided_targets=[(1, 0), (1, 1), (1, None)],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert first.damage_marked == 1
    assert second.damage_marked == 2
    assert game.players[1].life == 17


def test_cone_of_flame_keeps_a_survivors_own_share_when_a_target_leaves(set_pool):
    """CR 608.2b drops an illegal target and the rest of the effect happens —
    and the share that was announced against the *survivor* has to travel with
    it. Read positionally instead, the 3 would slide onto the creature the card
    assigned 2, which is why the shares are stamped onto the announcement.
    """
    first, second = _w2g2_bear("First"), _w2g2_bear("Second")
    game = _w2g2_cone_game(set_pool, [first, second])

    result = game.queue_from_hand(
        0, "Cone of Flame", divided_targets=[(1, 0), (1, 1), (1, None)],
    )
    assert result.supported, result.details
    game.remove_from_battlefield(first)
    game._settle()
    game.resolve_stack()

    assert second.damage_marked == 2, "still its own share, not the first's"
    assert game.players[1].life == 17


def test_cone_of_flame_is_proposable_by_the_ai(set_pool):
    """A card the policy skips every turn is a card no simulation ever tests.

    Cone of Flame's total is printed, so nothing asks for it — and
    `_divided_announcement_total` read the total off a key only "as you choose"
    set, answered 0, and `choose_divided_targets` returned "no lawful
    announcement". The card compiled, resolved correctly when driven by hand,
    and was never once cast.
    """
    from engine.ai_policy import choose_cast_action

    board = [_w2g2_bear(f"Bear {i}") for i in range(3)]
    lands = [_w2g2_permanent(card=set_pool("LEA")["Mountain"]) for _ in range(6)]
    for land in lands:
        land.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Cone of Flame"]],
                    battlefield=lands),
        PlayerState(name="P2", battlefield=board),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Cone of Flame"
    assert len(action.divided_targets) == 3, "the count the card prints"


# --- W2G4: libraries and graveyards as piles ---

import pytest

from engine import Game, PlayerState
from engine.oracle import compile_card_oracle as _w2g4_compile
from engine.targeting import derive_cast_spec as _w2g4_cast_spec


def _w2g4_game(set_pool, hand, *, library=(), graveyard=(), opponent_graveyard=(),
               life=20, interactive=(0,)):
    """A two-seat board with the piles this group's cards read."""
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(
            name="P1", hand=list(hand), library=list(library),
            graveyard=list(graveyard), life=life,
        ),
        PlayerState(
            name="P2", library=[lea["Island"]] * 10,
            graveyard=list(opponent_graveyard),
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def test_buried_alive_searches_a_library_into_a_graveyard(set_pool):
    """"Search your library for up to three creature cards, put them into your
    graveyard, then shuffle."

    The search flow already carried its destination as a parameter; a graveyard
    simply was not in the closed set of destinations it implements, so the card
    refused with "the search flow puts the found card into the searcher's own
    hand". The three finds land in the graveyard and nothing else moves.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Buried Alive"])
    assert program.supported, program.reason
    (search,) = program.instructions
    assert search.kind == "search_library"
    assert search.payload["destinations"] == ["graveyard"] * 3

    game = _w2g4_game(
        set_pool, [wth["Buried Alive"]],
        library=[lea[n] for n in
                 ("Grizzly Bears", "Craw Wurm", "Shivan Dragon", "Forest", "Island")],
        interactive=(),
    )
    game.cast_from_hand(0, "Buried Alive")
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert sorted(c.name for c in game.players[0].graveyard) == [
        "Buried Alive", "Craw Wurm", "Grizzly Bears", "Shivan Dragon",
    ], game.log
    assert sorted(c.name for c in game.players[0].library) == ["Forest", "Island"]
    assert game.players[0].hand == []


def test_argivian_restoration_finds_an_artifact_creature(set_pool):
    """"Return target artifact card from your graveyard to the battlefield."

    Clay Statue's printed line is "Artifact Creature", and CR 205.2b makes it an
    artifact card **and** a creature card. ``primary_type`` picks one of them by
    the order of a list and answers "creature", so a reanimation reading it
    would have offered the player nothing at all.
    """
    wth, lea, atq = set_pool("WTH"), set_pool("LEA"), set_pool("ATQ")
    statue = atq["Clay Statue"]
    assert statue.primary_type == "creature"

    program = _w2g4_compile(wth["Argivian Restoration"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "reanimate_creature"
    assert instruction.payload == {"card_type": "artifact"}

    game = _w2g4_game(
        set_pool, [wth["Argivian Restoration"]],
        graveyard=[lea["Grizzly Bears"], statue, lea["Black Lotus"]],
    )
    spec = _w2g4_cast_spec(wth["Argivian Restoration"], program)
    offered = game._enumerate_targets(
        0, wth["Argivian Restoration"], spec, for_cast=True
    )
    assert [entry["name"] for entry in offered] == ["Clay Statue", "Black Lotus"]

    game.cast_from_hand(0, "Argivian Restoration", target_permanent_index=1)
    game.resolve_stack()

    assert [p.card.name for p in game.players[0].battlefield] == ["Clay Statue"]
    assert [c.name for c in game.players[0].graveyard] == [
        "Grizzly Bears", "Black Lotus", "Argivian Restoration",
    ]


def test_argivian_restoration_declines_a_graveyard_of_creatures(set_pool):
    """The other half of the same narrowing: a pile with no artifact card in it
    offers nothing, where a reanimation that ignored the printed type would
    have returned the Bears."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Argivian Restoration"])
    game = _w2g4_game(
        set_pool, [wth["Argivian Restoration"]], graveyard=[lea["Grizzly Bears"]],
    )
    spec = _w2g4_cast_spec(wth["Argivian Restoration"], program)

    assert game._enumerate_targets(
        0, wth["Argivian Restoration"], spec, for_cast=True
    ) == []


def test_agonizing_memories_stacks_two_cards_in_the_order_chosen(set_pool):
    """"Look at target player's hand and choose two cards from it. Put them on
    top of that player's library in any order."

    The order is the pick order: the chooser is asked one card at a time and
    each goes on top of the last, so the **second** card named ends up on top.
    That is what "in any order" buys, and it is why the clause is consumed
    rather than recorded.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Agonizing Memories"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.kind == "reveal_hand_and_choose"
    assert instruction.payload["count"] == 2
    assert instruction.payload["fate"] == "library_top"

    game = _w2g4_game(set_pool, [wth["Agonizing Memories"]], library=[lea["Island"]] * 5)
    game.players[1].hand = [
        lea["Grizzly Bears"], lea["Shivan Dragon"], lea["Forest"],
    ]
    game.cast_from_hand(0, "Agonizing Memories", target_player_index=1)
    game.resolve_stack()

    assert [c.kind for c in game.pending_choices] == ["revealed_hand_pick"]
    assert game.confirm_revealed_hand_pick(0, 1)   # Shivan Dragon
    assert game.confirm_revealed_hand_pick(0, 0)   # Grizzly Bears

    assert [c.name for c in game.players[1].hand] == ["Forest"]
    assert [c.name for c in game.players[1].library[:2]] == [
        "Grizzly Bears", "Shivan Dragon",
    ], game.log


def test_agonizing_memories_refuses_a_pronoun_that_disagrees_with_the_count():
    """"Put **that card** on top" after "choose **two** cards" is not a sentence
    any card prints, and admitting it would let a two-card choice claim the
    one-card reading."""
    from engine.grammar.errors import GrammarError
    from engine.grammar.parser import parse_line

    parse_line(
        "Look at target player's hand and choose a card from it. "
        "Put that card on top of that player's library."
    )
    with pytest.raises(GrammarError):
        parse_line(
            "Look at target player's hand and choose two cards from it. "
            "Put that card on top of that player's library in any order."
        )


def test_gaeas_blessing_shuffles_the_cards_its_target_chose(set_pool):
    """"Target player shuffles up to three target cards from their graveyard
    into their library. Draw a card."

    The card was already "supported" on its cantrip alone: this sentence
    compiled to nothing and the picker offered nothing, which is the Roots
    class. The cards are chosen out of the *target's* graveyard and the
    remainder stays where it was.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Gaea's Blessing"])
    shuffle, draw = program.instructions
    assert shuffle.kind == "shuffle_graveyard_into_library"
    assert shuffle.payload["graveyard_owner"] == "target_player"
    assert shuffle.payload["targets"] == {
        "quantifier": "up_to", "kind": "card", "count": 3,
    }
    assert draw.kind == "draw_controller_cards"

    game = _w2g4_game(
        set_pool, [wth["Gaea's Blessing"]], library=[lea["Island"]] * 5,
        opponent_graveyard=[lea[n] for n in
                            ("Grizzly Bears", "Black Lotus", "Forest", "Mountain")],
    )
    before = len(game.players[1].library)
    game.cast_from_hand(
        0, "Gaea's Blessing", target_player_index=1, target_permanent_index=[0, 2],
    )
    game.resolve_stack()
    game.auto_resolve_pending_choices()

    assert [c.name for c in game.players[1].graveyard] == ["Black Lotus", "Mountain"]
    assert len(game.players[1].library) == before + 2
    assert [c.name for c in game.players[0].hand] == ["Island"]


def test_gaeas_blessing_returns_the_graveyard_when_it_is_milled(set_pool):
    """"When this card is put into your graveyard from your library, shuffle
    your graveyard into your library."

    A trigger no permanent can ever fire (CR 113.6k), announced from the seam
    the card actually moves through. The Blessing itself is in the graveyard
    when the ability resolves, so it goes back too.
    """
    from engine.replacements import _mill_cards

    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Gaea's Blessing"])
    (trigger,) = [
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "self_put_into_graveyard_from_library"
    ]
    assert trigger.instruction.kind == "shuffle_graveyard_into_library"

    game = _w2g4_game(
        set_pool, [],
        library=[wth["Gaea's Blessing"], lea["Island"], lea["Island"]],
        graveyard=[lea["Grizzly Bears"], lea["Forest"]],
    )
    _mill_cards(game, game.players[0], 1)

    assert [item.card.name for item in game.stack] == ["Gaea's Blessing"]
    game.resolve_stack()

    assert game.players[0].graveyard == []
    assert len(game.players[0].library) == 5, game.log


def test_a_second_copy_in_the_graveyard_does_not_trigger(set_pool):
    """The fire site is scoped to **the card that moved**. A graveyard scan
    would find a copy already lying in the pile and fire for a card that never
    went anywhere."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w2g4_game(
        set_pool, [],
        library=[lea["Island"], lea["Island"]],
        graveyard=[wth["Gaea's Blessing"]],
    )
    from engine.replacements import _mill_cards

    _mill_cards(game, game.players[0], 1)

    assert game.stack == [], game.log


def test_paradigm_shift_exiles_a_library_and_refills_it(set_pool):
    """"Exile all cards from your library. Then shuffle your graveyard into
    your library."

    The whole-library exile existed for Thought Lash's third-person spelling
    ("that player exiles all cards from their library") and was simply
    unreachable from the imperative.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Paradigm Shift"])
    assert program.supported, program.reason
    (sequence,) = program.instructions
    exile, shuffle = sequence.payload["steps"]
    assert exile.kind == "exile_entire_library"
    assert shuffle.kind == "shuffle_graveyard_into_library"

    game = _w2g4_game(
        set_pool, [wth["Paradigm Shift"]], library=[lea["Island"]] * 7,
        graveyard=[lea[n] for n in ("Grizzly Bears", "Forest", "Black Lotus")],
    )
    game.cast_from_hand(0, "Paradigm Shift")
    game.resolve_stack()

    assert len(game.players[0].exile) == 7
    assert sorted(c.name for c in game.players[0].library) == [
        "Black Lotus", "Forest", "Grizzly Bears",
    ]
    # The spell itself finishes resolving *after* the shuffle (CR 608.2), so it
    # is not one of the cards that went back.
    assert [c.name for c in game.players[0].graveyard] == ["Paradigm Shift"]


def test_doomsday_keeps_five_cards_and_exiles_both_zones(set_pool):
    """"Search your library and graveyard for five cards and exile the rest.
    Put the chosen cards on top of your library in any order. You lose half
    your life, rounded up."

    Two zones searched at once, the *piles* exiled rather than the finds, and
    the pick order is the stack order — the first card named ends up on top.
    """
    wth, lea = set_pool("WTH"), set_pool("LEA")
    program = _w2g4_compile(wth["Doomsday"])
    assert program.supported, program.reason
    (sequence,) = program.instructions
    search, life = sequence.payload["steps"]
    assert search.payload["zones"] == ("library", "graveyard")
    assert search.payload["exile_rest"] is True
    assert search.payload["destinations"] == ["library_top"] * 5
    assert life.kind == "target_loses_life"

    game = _w2g4_game(
        set_pool, [wth["Doomsday"]],
        library=[lea[n] for n in
                 ("Grizzly Bears", "Shivan Dragon", "Forest", "Island",
                  "Mountain", "Plains", "Swamp", "Black Lotus")],
        graveyard=[lea["Healing Salve"], lea["Ancestral Recall"]],
    )
    game.cast_from_hand(0, "Doomsday")
    game.resolve_stack()
    assert game.confirm_search_library_picks(0, [
        {"zone": "library", "index": 0},
        {"zone": "library", "index": 1},
        {"zone": "graveyard", "index": 1},
        {"zone": "library", "index": 7},
        {"zone": "library", "index": 2},
    ]), game.log

    assert [c.name for c in game.players[0].library] == [
        "Grizzly Bears", "Shivan Dragon", "Ancestral Recall", "Black Lotus",
        "Forest",
    ], game.log
    assert sorted(c.name for c in game.players[0].exile) == [
        "Healing Salve", "Island", "Mountain", "Plains", "Swamp",
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Doomsday"]
    assert game.players[0].life == 10


def test_doomsday_empties_both_zones_even_when_nothing_is_found(set_pool):
    """A search that finds nothing still searched, so "exile the rest" still
    empties both piles — and the life loss still happens."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    game = _w2g4_game(
        set_pool, [wth["Doomsday"]], library=[lea["Island"]] * 3,
        graveyard=[lea["Forest"]], life=7,
    )
    game.cast_from_hand(0, "Doomsday")
    game.resolve_stack()
    assert game.decline_search_library(0)

    assert game.players[0].library == []
    assert sorted(c.name for c in game.players[0].exile) == [
        "Forest", "Island", "Island", "Island",
    ]
    assert game.players[0].life == 3
