"""CR 603.3 / CR 603.6a — a permanent's own "when this enters" trigger is an
object on the stack, and every player gets priority with it there.

"Once an ability has triggered, its controller puts it on the stack as an
object that's not a card the next time a player would receive priority."
(CR 603.3.) This engine carried an entry trigger out inline instead, inside the
event that put the permanent onto the battlefield, so nothing could respond to
one. What that cost is the play every Planeshift player knows: Cavern Harpy
("When this creature enters, return a blue or black creature you control to its
owner's hand. / Pay 1 life: Return this creature to its owner's hand.") returned
to its owner's hand **in response to its own trigger**.

The cards here are built in the test, so each sentence is the one under test and
no pool card's other text is in the way. ``tests/engine/
test_entry_trigger_stack_census.py`` asks the same question of every entry
trigger the pool prints; the real Cavern Harpy is in
``tests/sets/test_pls_creatures_later_groups.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack

_W2G6_HARPY = _mk_card(
    name="W2G6 Harpy", mana_cost="{U}{B}", type_line="Creature — Harpy Beast",
    oracle_text=(
        "When this creature enters, return a blue or black creature you control "
        "to its owner's hand.\n"
        "Pay 1 life: Return this creature to its owner's hand."
    ),
    colors=("U", "B"),
)
_W2G6_KNIGHT = _mk_card(
    name="W2G6 Knight", mana_cost="{B}{B}", type_line="Creature — Knight",
    oracle_text="", colors=("B",),
)
_W2G6_HEALER = _mk_card(
    name="W2G6 Healer", mana_cost="{1}{W}", type_line="Creature — Cleric",
    oracle_text="When this creature enters, you gain 3 life.", colors=("W",),
)
_W2G6_TWIN = _mk_card(
    name="W2G6 Twin", mana_cost="{2}{W}", type_line="Creature — Cleric",
    oracle_text=(
        "When this creature enters, you gain 3 life.\n"
        "When this creature enters, draw a card."
    ),
    colors=("W",),
)
_W2G6_UPRISING = _mk_card(
    name="W2G6 Uprising", mana_cost="{2}{G}", type_line="Enchantment",
    oracle_text=(
        "When this enchantment enters, if you control a creature with power 4 "
        "or greater, draw a card."
    ),
    colors=("G",),
)
_W2G6_WURM = _mk_card(
    name="W2G6 Wurm", mana_cost="{4}{G}{G}", type_line="Creature — Wurm",
    oracle_text="", colors=("G",), power=6, toughness=4,
)
_W2G6_CAVES = _mk_card(
    name="W2G6 Caves", type_line="Land",
    oracle_text="When this land enters, you gain 1 life.",
)
_W2G6_JELLY = _mk_card(
    name="W2G6 Jelly", mana_cost="{2}{U}", type_line="Creature — Jellyfish",
    oracle_text="When this creature enters, return target creature to its owner's hand.",
    colors=("U",),
)
_W2G6_SLAY = _mk_card(
    name="W2G6 Slay", mana_cost="{B}", type_line="Instant",
    oracle_text="Destroy target creature.", colors=("B",),
)
_W2G6_RAISE = _mk_card(
    name="W2G6 Raise", mana_cost="{W}", type_line="Sorcery",
    oracle_text="Return target creature card from your graveyard to the battlefield.",
    colors=("W",),
)
_W2G6_FILLER = _mk_card(name="W2G6 Filler", type_line="Land")


def _w2g6_table(hand=(), their_hand=(), mine=(), theirs=(), graveyard=()) -> Game:
    """Two human seats in seat 0's main phase, seat 0 holding priority.

    Humans, so nothing is defaulted on the spot and the stack is resolved the
    way a table resolves it: by every player passing in succession."""
    game = Game(players=[
        PlayerState("A", library=[_W2G6_FILLER] * 10, hand=list(hand),
                    graveyard=list(graveyard)),
        PlayerState("B", library=[_W2G6_FILLER] * 10, hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game.active_player_index = 0
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    game.start_priority_window(0)
    return game


def _w2g6_cast(game, seat, card, **announced) -> None:
    result = game.queue_from_hand(seat, card.name, **announced)
    assert result.supported, result
    game.note_priority_action_taken(seat)


def _w2g6_all_pass(game) -> str:
    """Every player passes in succession (CR 117.4): the top object resolves."""
    result = "passed"
    for _ in range(len(game.players)):
        result = game.pass_priority(game.priority_player_index)
        if result != "passed":
            return result
    return result


def _w2g6_named(game, seat) -> list[str]:
    return [permanent.card.name for permanent in game.controlled_by(seat)]


def _w2g6_abilities(game) -> list[str]:
    return [item.ability_text for item in game.stack if item.is_ability]


@pytest.mark.cr("603.3", "603.6a", "117.3b")
def test_w2g6_603_3_an_entry_trigger_waits_on_the_stack_with_priority_given():
    """The creature spell resolves and its trigger is put on the stack; the
    active player then has priority (CR 117.3b) and nothing has happened."""
    game = _w2g6_table(hand=[_W2G6_HEALER])
    _w2g6_cast(game, 0, _W2G6_HEALER)

    assert _w2g6_all_pass(game) == "resolved_top"

    assert _w2g6_named(game, 0) == ["W2G6 Healer"]
    assert _w2g6_abilities(game) == ["When this creature enters, you gain 3 life."]
    assert game.stack[-1].source_permanent is next(iter(game.controlled_by(0)))
    assert game.players[0].life == 20, "triggered, not resolved"
    assert game.priority_player_index == 0 and game.pending_choices == []

    assert _w2g6_all_pass(game) == "resolved_top"
    assert game.players[0].life == 23 and game.stack == []


@pytest.mark.cr("603.3", "608.2b")
def test_w2g6_603_3_the_harpy_goes_home_in_response_to_its_own_gate():
    """The play. With the gate on the stack its controller pays 1 life and the
    Harpy is in hand; the gate then resolves anyway — it targets nothing, so
    CR 608.2b has nothing to find illegal — and still returns a blue or black
    creature, of which the Knight is now the only one."""
    game = _w2g6_table(hand=[_W2G6_HARPY], mine=[_W2G6_KNIGHT])
    _w2g6_cast(game, 0, _W2G6_HARPY)
    assert _w2g6_all_pass(game) == "resolved_top"
    assert _w2g6_named(game, 0) == ["W2G6 Knight", "W2G6 Harpy"]
    assert len(game.stack) == 1 and game.priority_player_index == 0

    activated = game.queue_permanent_ability(0, "W2G6 Harpy")
    assert activated.supported, activated
    game.note_priority_action_taken(0)
    assert game.players[0].life == 19
    assert len(game.stack) == 2, "the ability is above the gate"

    assert _w2g6_all_pass(game) == "resolved_top"
    assert [card.name for card in game.players[0].hand] == ["W2G6 Harpy"]
    assert _w2g6_named(game, 0) == ["W2G6 Knight"]
    assert len(game.stack) == 1, "the gate is still there"

    assert _w2g6_all_pass(game) == "awaiting_choice"
    (asked,) = game.pending_choices
    assert asked.kind == "permanent_set_choice" and asked.player_index == 0
    (knight,) = game.live_permanent_set_choices(asked)
    assert knight.card is _W2G6_KNIGHT
    assert not game.confirm_permanent_set_choice(0, []), "the return is not optional"
    assert game.confirm_permanent_set_choice(0, [knight.permanent_id])

    assert sorted(card.name for card in game.players[0].hand) == [
        "W2G6 Harpy", "W2G6 Knight",
    ]
    assert _w2g6_named(game, 0) == [] and game.stack == []
    assert game.players[0].life == 19


@pytest.mark.cr("603.3", "608.2b")
def test_w2g6_603_3_a_gate_with_nothing_left_to_return_returns_nothing():
    """The same play with no other blue or black creature: the gate resolves
    and finds nothing, and the Harpy has cost its controller one life."""
    game = _w2g6_table(hand=[_W2G6_HARPY])
    _w2g6_cast(game, 0, _W2G6_HARPY)
    assert _w2g6_all_pass(game) == "resolved_top"

    assert game.queue_permanent_ability(0, "W2G6 Harpy").supported
    game.note_priority_action_taken(0)
    assert _w2g6_all_pass(game) == "resolved_top"
    assert _w2g6_all_pass(game) == "resolved_top"

    assert [card.name for card in game.players[0].hand] == ["W2G6 Harpy"]
    assert game.stack == [] and game.pending_choices == []
    assert _w2g6_named(game, 0) == [] and game.players[0].life == 19


@pytest.mark.cr("603.3", "113.7a")
def test_w2g6_113_7a_the_trigger_outlives_a_source_destroyed_in_response():
    """An opponent can now answer the creature before its trigger resolves —
    and the ability "exists on the stack independently of its source", so the
    life is still gained."""
    game = _w2g6_table(hand=[_W2G6_HEALER], their_hand=[_W2G6_SLAY])
    _w2g6_cast(game, 0, _W2G6_HEALER)
    assert _w2g6_all_pass(game) == "resolved_top"
    (healer,) = game.controlled_by(0)

    assert game.pass_priority(0) == "passed"
    _w2g6_cast(game, 1, _W2G6_SLAY, target_permanent_ids=[healer.permanent_id])
    assert _w2g6_all_pass(game) == "resolved_top"
    assert not game.is_on_battlefield(healer)
    assert game.players[0].life == 20 and len(game.stack) == 1

    assert _w2g6_all_pass(game) == "resolved_top"
    assert game.players[0].life == 23


@pytest.mark.cr("603.4")
def test_w2g6_603_4_an_intervening_if_is_asked_again_as_the_trigger_resolves():
    """"If the ability triggers, it checks the stated condition again as it
    resolves." Inline, the two checks were one moment; on the stack there is a
    window between them, and an opponent who kills the 6/4 in it turns the
    draw off."""
    game = _w2g6_table(
        hand=[_W2G6_UPRISING], their_hand=[_W2G6_SLAY], mine=[_W2G6_WURM],
    )
    (wurm,) = game.controlled_by(0)
    _w2g6_cast(game, 0, _W2G6_UPRISING)
    assert _w2g6_all_pass(game) == "resolved_top"
    assert len(_w2g6_abilities(game)) == 1, "the condition held as it entered"

    assert game.pass_priority(0) == "passed"
    _w2g6_cast(game, 1, _W2G6_SLAY, target_permanent_ids=[wurm.permanent_id])
    assert _w2g6_all_pass(game) == "resolved_top"
    assert not game.is_on_battlefield(wurm)

    assert _w2g6_all_pass(game) == "resolved_top"
    assert game.players[0].hand == [], "the condition is no longer true"
    assert game.stack == []


@pytest.mark.cr("603.4")
def test_w2g6_603_4_a_false_condition_never_reaches_the_stack():
    """The rule's first check, unchanged: with no creature of power 4 or
    greater the ability does not trigger, so there is nothing to respond to."""
    game = _w2g6_table(hand=[_W2G6_UPRISING])
    _w2g6_cast(game, 0, _W2G6_UPRISING)
    assert _w2g6_all_pass(game) == "resolved_top"

    assert game.stack == [] and game.players[0].hand == []
    assert _w2g6_named(game, 0) == ["W2G6 Uprising"]


@pytest.mark.cr("603.3b", "603.3")
def test_w2g6_603_3b_two_entry_triggers_are_two_objects_the_first_printed_on_top():
    """Two triggers of one permanent trigger together and are two stack
    objects. This engine asks nobody the order CR 603.3b lets their controller
    choose, so the stated order is the printed one: the first printed is on
    top and resolves first, alone."""
    game = _w2g6_table(hand=[_W2G6_TWIN])
    game.players[0].library = [_W2G6_FILLER] * 3
    _w2g6_cast(game, 0, _W2G6_TWIN)
    assert _w2g6_all_pass(game) == "resolved_top"

    assert _w2g6_abilities(game) == [
        "When this creature enters, draw a card.",
        "When this creature enters, you gain 3 life.",
    ], "bottom first: the last printed was put on the stack first"
    assert (game.players[0].life, len(game.players[0].hand)) == (20, 0)

    assert _w2g6_all_pass(game) == "resolved_top"
    assert (game.players[0].life, len(game.players[0].hand)) == (23, 0)
    assert _w2g6_all_pass(game) == "resolved_top"
    assert (game.players[0].life, len(game.players[0].hand)) == (23, 1)
    assert game.stack == []


@pytest.mark.cr("603.3", "116.2a")
def test_w2g6_116_2a_a_played_lands_entry_trigger_is_on_the_stack_with_no_spell():
    """Playing a land is a special action and puts no spell on the stack — and
    the land's entry trigger still goes there, by itself, to be passed on."""
    game = _w2g6_table(hand=[_W2G6_CAVES])
    played = game.queue_from_hand(0, "W2G6 Caves")
    assert played.supported, played
    game.note_priority_action_taken(0)

    assert _w2g6_named(game, 0) == ["W2G6 Caves"]
    assert _w2g6_abilities(game) == ["When this land enters, you gain 1 life."]
    assert len(game.stack) == 1 and game.players[0].life == 20
    assert game.priority_player_index == 0

    assert _w2g6_all_pass(game) == "resolved_top"
    assert game.players[0].life == 21 and game.stack == []


@pytest.mark.cr("603.3", "603.6a")
def test_w2g6_603_6a_an_entry_nothing_cast_puts_its_trigger_on_the_stack_too():
    """A creature returned from a graveyard enters during another spell's
    resolution. Its trigger is put on the stack — it does not happen inside
    that resolution — and resolves after the spell has finished."""
    game = _w2g6_table(hand=[_W2G6_RAISE], graveyard=[_W2G6_HEALER])
    _w2g6_cast(game, 0, _W2G6_RAISE, target_player_index=0, target_permanent_index=0)
    assert _w2g6_all_pass(game) == "resolved_top"

    assert _w2g6_named(game, 0) == ["W2G6 Healer"]
    assert _w2g6_abilities(game) == ["When this creature enters, you gain 3 life."]
    assert all(item.is_ability for item in game.stack), "the sorcery has left"
    assert game.players[0].life == 20

    resolve_stack(game)
    assert game.players[0].life == 23


@pytest.mark.cr("603.3d", "603.3")
def test_w2g6_603_3d_the_casts_announcement_rides_the_trigger_and_is_not_asked_again():
    """This engine names an entry trigger's target as the permanent is cast.
    The trigger is a stack object carrying that choice: nobody is asked a
    second time, the target is whatever was named — by identity, across the
    priority round the trigger now waits through — and nothing is returned
    until it resolves."""
    game = _w2g6_table(
        hand=[_W2G6_JELLY], their_hand=[_W2G6_SLAY],
        theirs=[_W2G6_KNIGHT, _W2G6_WURM],
    )
    knight, wurm = game.controlled_by(1)
    _w2g6_cast(game, 0, _W2G6_JELLY, target_permanent_ids=[wurm.permanent_id])
    assert _w2g6_all_pass(game) == "resolved_top"

    (trigger,) = game.stack
    assert trigger.is_ability and trigger.target_permanent_id == [wurm.permanent_id]
    assert game.pending_choices == [], "the cast already chose"
    assert game.is_on_battlefield(wurm)

    # The opponent kills its own Knight in response: every later slot on that
    # battlefield renumbers, and the trigger still finds the Wurm.
    assert game.pass_priority(0) == "passed"
    _w2g6_cast(game, 1, _W2G6_SLAY, target_permanent_ids=[knight.permanent_id])
    assert _w2g6_all_pass(game) == "resolved_top"
    assert not game.is_on_battlefield(knight) and game.is_on_battlefield(wurm)

    assert _w2g6_all_pass(game) == "resolved_top"
    assert [card.name for card in game.players[1].hand] == ["W2G6 Wurm"]
    assert _w2g6_named(game, 1) == []
