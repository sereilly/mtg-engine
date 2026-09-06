"""CR 116 — special actions: what a player may do with priority, off the stack.

CR 116.1 defines them as "actions a player may take when they have priority
that don't use the stack", and CR 116.2 lists twelve. This engine implements
two: the land drop (CR 116.2a), which predates the seam and still lives on the
play path, and CR 116.2e, the only rule in the whole CR that names a card.

The reason the second one needed a seam at all is the first clause of CR 116.1.
No stack means no instruction to compile and no handler to dispatch, so a card
whose remaining text is a keyword line and an upkeep trigger reported
*unsupported* however well the action worked — the compiler had nowhere to put
it. `engine/special_actions.py` is the table, and the support gate reads that
same table, which is what closes the gap.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.oracle import compile_card_oracle
from engine.special_actions import (available_special_actions,
                                    special_action_line,
                                    special_action_refusal,
                                    special_actions_for, take_special_action)

_WTH = {
    c.name: c
    for c in load_cards(manifest_set_path("WTH", include_measured=True))
}
_CATALOG = {c.name: c for c in load_catalog()}


def _duel(hand=()):
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


@pytest.mark.cr("116.1", "116.2e", "116.3")
def test_116_2e_discarding_circling_vultures_is_a_special_action():
    """"One card (Circling Vultures) has the ability 'You may discard Circling
    Vultures any time you could cast an instant.' Doing so is a special action.
    A player can take such an action any time they have priority."

    Three properties, one per clause, and each is a way this could be built
    wrong:

    * it does not use the stack (CR 116.1), so nothing is put on it and nothing
      resolves;
    * it needs priority and nothing else (CR 116.2e) — *not* CR 601.3d's
      sorcery window, and not `cast_timing.casts_at_instant_speed`, which
      answers about a card being **cast** and nothing here is cast;
    * the player has priority again afterwards (CR 116.3), so the action must
      not pass or advance a step.
    """
    assert special_action_line(
        "You may discard this card any time you could cast an instant."
    ) == "discard_from_hand"
    assert special_actions_for(_WTH["Circling Vultures"]) == ("discard_from_hand",)

    game, p1, _p2 = _duel([_WTH["Circling Vultures"], _CATALOG["Grizzly Bears"]])
    game.priority_player_index = 0
    assert available_special_actions(game, 0) == [
        {"hand_index": 0, "name": "Circling Vultures", "kind": "discard_from_hand"}
    ]

    assert take_special_action(
        game, 0, _WTH["Circling Vultures"], "discard_from_hand"
    ) is None

    assert [c.name for c in p1.hand] == ["Grizzly Bears"]
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]
    assert game.stack == [], "CR 116.1: a special action does not use the stack"
    assert game.has_priority(0), "CR 116.3: and the player keeps priority"


@pytest.mark.cr("116.1", "116.2e")
def test_116_1_a_special_action_needs_priority_and_the_card_in_hand():
    """The two halves of "when they have priority", asked of the one gate the
    engine and the web layer both read — an action the client offers and the
    engine refuses is a button that does nothing.

    The opponent's answer is the one that matters: the card is in somebody's
    hand and the ability is real, and the seat that may take it is the seat
    holding it.
    """
    game, _p1, _p2 = _duel([_WTH["Circling Vultures"]])
    vultures = _WTH["Circling Vultures"]

    game.priority_player_index = 1
    assert special_action_refusal(game, 0, vultures, "discard_from_hand") == (
        "A does not have priority"
    )
    assert available_special_actions(game, 0) == []

    game.priority_player_index = 0
    assert special_action_refusal(game, 0, vultures, "discard_from_hand") is None
    assert special_action_refusal(game, 1, vultures, "discard_from_hand") == (
        "Circling Vultures is not in B's hand"
    )
    assert available_special_actions(game, 1) == []


@pytest.mark.cr("116.2e", "400.3")
def test_116_2e_a_discard_takes_exactly_one_copy_of_a_shared_definition():
    """A deck repeats one immutable ``CardDefinition`` per copy, so an identity
    *filter* over the hand removes every copy where the caller then files one.
    That class has deleted cards from this game before
    (`tests/engine/test_hand_removal_seam.py`), and the graveyard side is
    CR 614's event rather than a list append — a bare append skips every
    replacement over "if a card would be put into your graveyard".
    """
    vultures = _WTH["Circling Vultures"]
    game, p1, _p2 = _duel([vultures, vultures])
    game.priority_player_index = 0

    take_special_action(game, 0, vultures, "discard_from_hand")

    assert [c.name for c in p1.hand] == ["Circling Vultures"]
    assert [c.name for c in p1.graveyard] == ["Circling Vultures"]


@pytest.mark.cr("116.1")
def test_116_1_a_special_action_makes_its_card_supported():
    """The gap the seam closes, asserted rather than described.

    Circling Vultures' other two lines both worked — flying, and an upkeep
    trigger that compiles to a real ``may``/``otherwise`` pair — and the card
    reported unsupported for the one sentence that produces no instruction
    *by rule*. A support gate that only counts instructions cannot admit a
    CR 116 action at all, which is why it reads this table.
    """
    program = compile_card_oracle(_WTH["Circling Vultures"])

    assert program.supported, program.reason
    assert [t.supported for t in program.triggered_abilities] == [True]
