"""Visions artifacts.

Each group appends its own block with its own imports at the top of that block,
so a per-set merge is an append rather than a conflict (SET_PLAYBOOK.md).
"""


# --- W1G4: upkeep, end-step and per-player step triggers ---
import pytest

from engine import Game, PlayerState
from engine.grammar import parse_line
from engine.grammar.errors import GrammarError
from engine.hand_size import maximum_hand_size
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.untap_restrictions import untap_restriction_for


def _w1g4_forest(name: str) -> CardDefinition:
    """A basic land under a made-up name, so a hand or library is countable."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",), raw={"name": name},
    )


def _w1g4_bear(name: str, tapped: bool = False) -> Permanent:
    return Permanent(
        card=CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": name}, power="2", toughness="2",
        ),
        tapped=tapped,
    )


def _w1g4_game(*, hands=(0, 0), libraries=(0, 0)) -> Game:
    game = Game(players=[
        PlayerState(
            name=f"P{seat}",
            hand=[_w1g4_forest(f"H{seat}_{i}") for i in range(hands[seat])],
            library=[_w1g4_forest(f"L{seat}_{i}") for i in range(libraries[seat])],
        )
        for seat in (0, 1)
    ])
    game.enforce_mana_costs = False
    return game


def _w1g4_drain(game: Game) -> None:
    """Resolve everything the step just put on the stack."""
    for _ in range(20):
        if not game.stack:
            return
        game.resolve_top_of_stack()
    raise AssertionError("the stack never drained")


def test_anvil_of_bogardan_removes_every_players_maximum_hand_size(set_pool):
    """"Players have no maximum hand size." - CR 402.2, for everyone at the
    table, and derived from the board so it ends with the artifact (CR 611.3a).

    Asserted at the cleanup step rather than off the reader alone: a restriction
    line parsed and enforced by nobody is the failure that never crashes and is
    always in the player's favour.
    """
    game = _w1g4_game(hands=(10, 10))
    anvil = Permanent(card=set_pool("VIS")["Anvil of Bogardan"])
    game.players[0].battlefield.append(anvil)
    game.begin_turn_bookkeeping(0)

    assert maximum_hand_size(game, 0) is None
    # Its controller's opponent too - the line says "players", not "you".
    assert maximum_hand_size(game, 1) is None
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 10
    assert game.players[0].graveyard == []

    game.remove_from_battlefield(anvil)
    assert maximum_hand_size(game, 0) == 7
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 7


def test_sands_of_time_makes_every_player_skip_their_untap_step(set_pool):
    """"Each player skips their untap step." - the distributive spelling of
    Stasis's "Players skip their untap steps", and the same CR 502 restriction,
    so it is one row in the table rather than a second."""
    sands = set_pool("VIS")["Sands of Time"]
    restriction = untap_restriction_for(sands.oracle_text)

    assert restriction is not None
    assert (restriction.scope, restriction.limit) == ("all", 0)

    game = _w1g4_game()
    game.players[0].battlefield.append(Permanent(card=sands))
    bear = _w1g4_bear("Bear", tapped=True)
    game.players[0].battlefield.append(bear)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game.resolve_untap_step(0)

    assert bear.tapped is True


def test_sands_of_time_inverts_only_the_upkeeps_own_players_permanents(set_pool):
    """"At the beginning of each player's upkeep, that player **simultaneously**
    untaps each tapped artifact, creature, and land they control and taps each
    untapped artifact, creature, and land they control."

    Two assertions, and the second is the adverb. The seat is the one whose
    upkeep it is (CR 603.10), so an opponent's board is untouched; and the two
    sweeps are simultaneous (CR 611.2c), so a permanent that was tapped comes up
    and *stays* up rather than being caught by the tap half.
    """
    pool = set_pool("VIS")
    game = _w1g4_game()

    sands = Permanent(card=pool["Sands of Time"])
    game.players[0].battlefield.append(sands)
    mine_tapped = _w1g4_bear("Mine tapped", tapped=True)
    mine_untapped = _w1g4_bear("Mine untapped")
    game.players[0].battlefield.extend([mine_tapped, mine_untapped])
    theirs_tapped = _w1g4_bear("Theirs tapped", tapped=True)
    game.players[1].battlefield.append(theirs_tapped)

    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    _w1g4_drain(game)

    assert mine_tapped.tapped is False
    assert mine_untapped.tapped is True
    # The artifact is one of the permanents its own sentence names.
    assert sands.tapped is True
    # Somebody else's upkeep, somebody else's board.
    assert theirs_tapped.tapped is True


def test_teferis_puzzle_box_bottoms_a_hand_and_redraws_it(set_pool):
    """"At the beginning of each player's draw step, that player puts the cards
    in their hand on the **bottom** of their library in any order, then draws
    that many cards."

    Three facts, and each is a place this card could go wrong quietly: the seat
    is the one whose draw step it is, the cards go to the *bottom* (a prompt
    that could not tell the ends apart would put them on top), and the redraw
    counts what the put actually moved rather than a printed number.
    """
    game = _w1g4_game(hands=(3, 3), libraries=(20, 20))
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Teferi's Puzzle Box"])
    )
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.active_player_index = 1
    old_hand = [card.name for card in game.players[1].hand]
    top_before = [card.name for card in game.players[1].library[:3]]

    game.resolve_upkeep(1, defer_priority=True)
    game.resolve_draw_step(1, defer_priority=True)
    game.resolve_top_of_stack()

    # The prompt is owed before anything moves, and it is owed by the seat whose
    # draw step this is (CR 608.2, CR 117.3b).
    assert [choice.kind for choice in game.pending_choices] == ["hand_to_library"]
    choice = game.pending_choices[0]
    assert choice.player_index == 1
    assert choice.data["destination"] == "bottom"
    # The turn-based draw happens inside the step and before this trigger
    # resolves, so what goes back is the hand as it stands then - which is
    # exactly why the count is read off the board rather than printed.
    held = len(game.players[1].hand)
    assert held == len(old_hand) + 1
    assert choice.data["count"] == held
    assert game.confirm_hand_to_library(1, list(range(held)))

    assert [card.name for card in game.players[1].library[-held:]][:3] == old_hand
    assert [card.name for card in game.players[1].hand][:2] == top_before[1:]
    # The Puzzle Box's controller is not the seat whose draw step it was.
    assert len(game.players[0].hand) == 3


def test_teferis_puzzle_box_compiles_the_bottoming_and_the_redraw_as_one_step(set_pool):
    """The two halves are one ``sequence``, and the draw reads the record the
    put wrote - "that many" has no other producer, and a back-reference with
    none reads as zero."""
    program = compile_card_oracle(set_pool("VIS")["Teferi's Puzzle Box"])
    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "draw_step_each"
    assert trigger.instruction.kind == "sequence"
    put, draw = trigger.instruction.payload["steps"]
    assert put.kind == "put_hand_cards_on_library"
    assert put.payload["destination"] == "bottom"
    assert put.payload["whole_hand"] is True
    assert put.payload["recipient"] == "event_subject_player"
    assert draw.kind == "draw_target_cards"
    assert draw.payload["amount_from"] == "hand_cards_to_library"
    assert draw.payload["drawer_seat_record"] == "event_subject_player"


@pytest.mark.parametrize("line", [
    # The ordering rider is the whole of what the player still decides once the
    # card has named the end, so a bottoming sentence without it must refuse
    # rather than parse with the choice dropped.
    "That player puts the cards in their hand on the bottom of their library.",
    # A destination this production does not read.
    "That player puts the cards in their hand beside their library in any order.",
])
def test_the_bottoming_production_refuses_what_it_cannot_read(line):
    """A production consumes every token of its line or raises (CLAUDE.md)."""
    with pytest.raises(GrammarError):
        parse_line(line)


@pytest.mark.parametrize("line", [
    # Half a sentence: the tap sweep is what makes it an inversion.
    "That player simultaneously untaps each tapped creature they control.",
])
def test_the_inversion_production_refuses_what_it_cannot_read(line):
    """The refusal test for the other production this block added."""
    with pytest.raises(GrammarError):
        parse_line(line)
