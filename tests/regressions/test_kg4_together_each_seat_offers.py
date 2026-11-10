"""What each seat puts onto the battlefield in answer to one offer enters
together (CR 603.6a, 101.4).

Show and Tell: "Each player may put an artifact, creature, enchantment, or
land card from their hand onto the battlefield." Its rulings: "The current
player chooses first, then each other player chooses in turn order … After
all choices are made, the cards are put onto the battlefield simultaneously"
(2008-04-01), and "If the cards being put onto the battlefield also require
choices, those choices are made after all players choose their card. The
active player makes choices for their card (if any), then the other players
(if any) in turn order" (2004-10-04). CR 101.4: the players choose in APNAP
order, "then the actions happen simultaneously"; CR 603.6a: "Each time an
event puts one or more permanents onto the battlefield, all permanents on the
battlefield (including the newcomers) are checked for any enters-the-
battlefield triggers that match the event."

The offer is one prompt per seat (``handlers/control_flow.may``), each
answered after the call that made it has returned, so a ``with`` block could
not hold the event across them: every seat's card entered at its own answer,
and an observer among the later seat's cards never saw the earlier seat's
arrive — a Soul Warden on the non-active seat gained 0 off Show and Tell, at
both kinds of table (kg3's probe).

The census is every pool line whose one offer to several seats can put a
permanent onto the battlefield, derived from the compiled programs; each is
driven through its real card, with an observer among the newcomers on the
**later** seat in turn order (the row that was 0 on the base) and on the
earlier one, at a table nobody asks, with a person at the table answering
first, and with a person answering last. Lands have no observer in the pool
that can be among the newcomers, so the three land searches put down an
invented basic land that is one ("Whenever another land enters, you gain 1
life").
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compiled_units
from tests.helpers import resolve_stack, settle

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

WARDEN = "Soul Warden"

#: A basic land that observes lands entering — invented, because no land in
#: the pool does (the land searches' observer).
FIELD = CardDefinition(
    name="Warden's Field", mana_cost="", cmc=0.0,
    type_line="Basic Land — Plains",
    oracle_text="Whenever another land enters, you gain 1 life.",
    colors=(), color_identity=(), keywords=(), produced_mana=("W",),
    raw={"name": "Warden's Field", "type_line": "Basic Land — Plains"},
)


def _table(seats: int, interactive=frozenset()) -> Game:
    players = [
        PlayerState(name=f"P{i}", library=[_CARDS["Grizzly Bears"]] * 10)
        for i in range(seats)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = set(interactive)
    game._sync_control()
    return game


def _place(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    return permanent


def _life(game: Game) -> list[int]:
    return [player.life for player in game.players]


def _two_newcomers(seats: list[int], observer_later: bool, observer, other):
    """``{seat: card name}`` for the two seats putting a card down: the
    observer on the later seat in turn order, or on the earlier one."""
    first, second = seats
    return (
        {first: other, second: observer} if observer_later
        else {first: observer, second: other}
    )


# -- the rows -----------------------------------------------------------------
#
# Each takes the table and *observer_later*, and returns ``(seat, change,
# expected)``: the observer's seat, how much that seat's life changed, and
# what one event makes it (one per other permanent of its kind entering).


def _show_and_tell(game: Game, observer_later: bool):
    puts = _two_newcomers([0, 1], observer_later, WARDEN, "Grizzly Bears")
    for seat, name in puts.items():
        game.players[seat].hand = [_CARDS[name]]
    game.players[0].hand.append(_CARDS["Show and Tell"])
    seat = next(s for s, name in puts.items() if name == WARDEN)
    before = _life(game)
    assert game.cast_from_hand(0, "Show and Tell").supported
    settle(game)
    return seat, _life(game)[seat] - before[seat], 1


def _from_hand_to_each_opponent(source: str, observer: str, other: str):
    def row(game: Game, observer_later: bool):
        puts = _two_newcomers([1, 2], observer_later, observer, other)
        for seat, name in puts.items():
            game.players[seat].hand = [_CARDS[name]]
        seat = next(s for s, name in puts.items() if name == observer)
        before = _life(game)
        _place(game, 0, source)
        settle(game)
        return seat, _life(game)[seat] - before[seat], -1 if observer == "Carnival of Souls" else 1
    return row


def _enslaved_horror(game: Game, observer_later: bool):
    """"…each other player may return a creature card from their graveyard
    to the battlefield.\""""
    puts = _two_newcomers([1, 2], observer_later, WARDEN, "Grizzly Bears")
    for seat, name in puts.items():
        game.players[seat].graveyard = [_CARDS[name]]
    seat = next(s for s, name in puts.items() if name == WARDEN)
    before = _life(game)
    _place(game, 0, "Enslaved Horror")
    settle(game)
    return seat, _life(game)[seat] - before[seat], 1


def _land_libraries(game: Game, seats: list[int], observer_later: bool) -> int:
    puts = _two_newcomers(seats, observer_later, "field", "Plains")
    for seat, name in puts.items():
        land = FIELD if name == "field" else _CARDS["Plains"]
        game.players[seat].library = [land] + [_CARDS["Grizzly Bears"]] * 8
    return next(s for s, name in puts.items() if name == "field")


def _veteran_explorer(game: Game, observer_later: bool):
    """"When this creature dies, each player may search their library for up
    to two basic land cards, put them onto the battlefield, then shuffle.\""""
    seat = _land_libraries(game, [0, 1], observer_later)
    explorer = _place(game, 0, "Veteran Explorer")
    before = _life(game)
    game.sacrifice_permanent(explorer)
    settle(game)
    return seat, _life(game)[seat] - before[seat], 1


def _new_frontiers(game: Game, observer_later: bool):
    """"Each player may search their library for up to X basic land cards
    and put them onto the battlefield tapped.\""""
    seat = _land_libraries(game, [0, 1], observer_later)
    game.players[0].hand = [_CARDS["New Frontiers"]]
    before = _life(game)
    assert game.cast_from_hand(0, "New Frontiers", x_value=1).supported
    settle(game)
    return seat, _life(game)[seat] - before[seat], 1


def _hired_giant(game: Game, observer_later: bool):
    """"When this creature enters, each other player may search their library
    for a land card and put that card onto the battlefield.\""""
    seat = _land_libraries(game, [1, 2], observer_later)
    before = _life(game)
    _place(game, 0, "Hired Giant")
    settle(game)
    return seat, _life(game)[seat] - before[seat], 1


#: ``card -> (seats at the table, the row)``.
ROWS = {
    "Show and Tell": (2, _show_and_tell),
    "Hunted Wumpus": (3, _from_hand_to_each_opponent("Hunted Wumpus", WARDEN, "Grizzly Bears")),
    # "…an artifact or enchantment card": an enchantment that sees creatures
    # enter (Carnival of Souls: "Whenever a creature enters, you lose 1 life
    # and add {B}") beside an artifact creature.
    "Charmed Griffin": (3, _from_hand_to_each_opponent("Charmed Griffin", "Carnival of Souls", "Ornithopter")),
    "Enslaved Horror": (3, _enslaved_horror),
    "Veteran Explorer": (2, _veteran_explorer),
    "New Frontiers": (2, _new_frontiers),
    "Hired Giant": (3, _hired_giant),
}


# -- the census ---------------------------------------------------------------

_MULTI_SEAT = frozenset({"each_player", "each_opponent"})


def _enters(step) -> bool:
    """Whether *step* puts a permanent onto the battlefield."""
    if step.kind == "put_chosen_card_from_hand_onto_battlefield":
        return True
    if step.kind == "search_library":
        places = [step.payload.get("destination")] + list(
            step.payload.get("destinations") or ()
        )
        return "battlefield" in places
    return False


def _walk(instruction):
    yield instruction
    for value in (instruction.payload or {}).values():
        if hasattr(value, "kind"):
            yield from _walk(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if hasattr(item, "kind"):
                    yield from _walk(item)


def _each_seat_offers_that_enter() -> tuple[int, set[str]]:
    found: set[str] = set()
    examined = 0
    for card, program in compiled_units(_CATALOG):
        if not program.supported:
            continue
        examined += 1
        roots = list(program.instructions) + [
            ability.instruction for ability in program.triggered_abilities
            if ability.instruction is not None
        ]
        for root in roots:
            for step in _walk(root):
                if step.kind != "may" or step.payload.get("actor") not in _MULTI_SEAT:
                    continue
                if any(
                    _enters(inner)
                    for key in ("action", "then")
                    for top in (step.payload.get(key) or ())
                    for inner in _walk(top)
                ):
                    found.add(card.name)
    return examined, found


def test_the_census_is_every_driven_row():
    """Every offer to several seats that can put a permanent onto the
    battlefield is a row below; a new one has to be driven."""
    examined, found = _each_seat_offers_that_enter()
    assert examined >= 4000, examined
    assert len(found) >= 7, sorted(found)
    assert found == set(ROWS), sorted(found ^ set(ROWS))


#: Which seats are interactive, by the table's size: nobody; the first seat
#: to answer; the last seat to answer (whose answer closes the event).
_TABLES = {
    "nobody_asked": lambda seats: frozenset(),
    "a_person_first": lambda seats: frozenset({0 if seats == 2 else 1}),
    "a_person_last": lambda seats: frozenset({seats - 1}),
}


@pytest.mark.parametrize("table", sorted(_TABLES))
@pytest.mark.parametrize("observer_later", [True, False], ids=["observer_later", "observer_earlier"])
@pytest.mark.parametrize("card", sorted(ROWS))
def test_each_seats_card_sees_the_others_enter(card, observer_later, table):
    seats, row = ROWS[card]
    game = _table(seats, _TABLES[table](seats))
    seat, change, expected = row(game, observer_later)
    assert change == expected, (
        f"{card}: the observer on seat {seat} among the newcomers changed its "
        f"life by {change}; entering with the other seat's card it is "
        f"{expected}\n" + "\n".join(game.log[-25:])
    )
    # Nothing left open: every event that was handed a card has closed.
    assert not getattr(game, "open_entry_events", []), game.open_entry_events
    assert game.entry_batch is None
