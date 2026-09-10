"""CR 608.2: a resolution is over when its last step is done, on every path.

The engine has held a resolution open for its prompts since the Sanctum of All
round, but only behind ``resolve_top_of_stack(pause_for_choices=True)`` — a flag
set by the priority path and the step drain and by nothing else. ``Game._settle``
is the third way a stack object resolves in this engine: it is the loop behind
``cast_from_hand`` and ``activate_permanent_ability``, the "announce it and
finish it" entry points, and it resolved without pausing whoever was playing.

So the whole rule below was unenforced there. What the seat owed was queued
against an empty stack, the object never came back, and every consequence the
rule has of a resolution *not* being over — CR 608.2n's bin, CR 704.3's sweep,
CR 117.3b's hand-off — was applied to one that had not finished.

The condition is derived, not declared: ``bool(interactive_seats)``, exactly as
``_resolve_priority_window`` derives it. With nobody to wait for the loop is
what it always was, which is what keeps a seeded simulation reproducible — and
is asserted here rather than assumed.

Its own file per SET_PLAYBOOK's block convention: a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState


def _w2g5_duel(pool, hand=(), graveyard=(), *, interactive=(0,)):
    p1 = PlayerState(
        name="P1",
        hand=[pool[n] for n in hand],
        graveyard=[pool[n] for n in graveyard],
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, p1, p2


def _w2g5_recall(pool, **kwargs):
    return _w2g5_duel(
        pool,
        hand=["Recall", "Grizzly Bears", "Grizzly Bears"],
        graveyard=["Healing Salve"],
        **kwargs,
    )


@pytest.mark.cr("608.2", "608.2m")
def test_a_spell_resolved_in_one_call_stays_on_the_stack_while_it_asks(
    catalog_by_name,
):
    """"…its resolution may involve several steps." Recall's first step asks
    the caster to discard; until that is answered the spell has not finished
    resolving, so the object is still on the stack."""
    game, _, _ = _w2g5_recall(catalog_by_name)

    game.cast_from_hand(0, "Recall", x_value=1)

    assert [item.card.name for item in game.stack] == ["Recall"]
    assert game.stack[-1].resolution_held


@pytest.mark.cr("117.3b")
def test_nobody_receives_priority_while_the_resolution_is_unfinished(
    catalog_by_name,
):
    """"The active player receives priority after a spell or ability … resolves."
    One that stopped to ask has not, so the seat that owes the answer is the
    only one the game is waiting on."""
    game, _, _ = _w2g5_recall(catalog_by_name)

    game.cast_from_hand(0, "Recall", x_value=1)

    owed = game.waiting_prompt()
    assert owed is not None and owed.player_index == 0
    assert game.priority_player_index is None


@pytest.mark.cr("608.2n")
def test_the_card_reaches_the_graveyard_only_as_the_final_part(catalog_by_name):
    """"As the final part of an instant or sorcery spell's resolution, the spell
    is put into its owner's graveyard."

    Balance's prompt does not suspend the resumable loop, so its bin step is the
    one that used to run early — the card in the graveyard with the sacrifice
    still owed.
    """
    game, p1, p2 = _w2g5_duel(catalog_by_name, hand=["Balance"])
    for _ in range(3):
        p1.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))
    p2.battlefield.append(Permanent(card=catalog_by_name["Grizzly Bears"]))

    game.cast_from_hand(0, "Balance")
    assert game.waiting_prompt() is not None
    assert "Balance" not in [c.name for c in p1.graveyard]

    game.auto_resolve_pending_choices()
    assert "Balance" in [c.name for c in p1.graveyard]


@pytest.mark.cr("704.3")
def test_the_state_based_check_waits_for_the_last_answer(catalog_by_name):
    """"Whenever a player would get priority … the game checks for any of the
    listed conditions for state-based actions."

    Nobody would get priority while the resolution is open, so the sweep belongs
    with the release. Answering the last prompt runs both, in that order.
    """
    game, p1, _ = _w2g5_recall(catalog_by_name)
    game.cast_from_hand(0, "Recall", x_value=1)
    assert game.stack, "still resolving"

    game.auto_resolve_pending_choices()

    assert game.stack == []
    assert game.waiting_prompt() is None
    assert "Recall finished resolving" in game.log


@pytest.mark.cr("602.2b", "608.2")
def test_an_ability_resolved_in_one_call_waits_for_the_seat_it_asked(
    catalog_by_name,
):
    """The same rule for an activated ability, and the shape the browser
    reaches: an AI seat activates through ``activate_permanent_ability`` and the
    prompt lands on the human seat opposite it."""
    game, p1, p2 = _w2g5_duel(catalog_by_name, interactive=(1,))
    scepter = Permanent(card=catalog_by_name["Disrupting Scepter"])
    scepter.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(scepter)
    p2.hand = [catalog_by_name["Grizzly Bears"]]

    game.activate_permanent_ability(0, "Disrupting Scepter", target_player_index=1)

    owed = game.waiting_prompt()
    assert owed is not None and owed.player_index == 1
    assert len(game.stack) == 1


@pytest.mark.cr("605.3a")
def test_a_mana_ability_holds_nothing_because_it_uses_no_stack(catalog_by_name):
    """The 29 armings the census leaves unheld, and why they are right.

    "A player may activate an activated mana ability … even if it's in the
    middle of casting or resolving a spell" — a mana ability never uses the
    stack (CR 605.1a), so the colour prompt Birds of Paradise arms has no object
    to record and must not grow one. A derivation that "fixed" this would be
    inventing a stack object for an ability the rules keep off it.
    """
    game, p1, _ = _w2g5_duel(catalog_by_name)
    birds = Permanent(card=catalog_by_name["Birds of Paradise"])
    birds.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(birds)

    game.activate_permanent_ability(0, "Birds of Paradise")

    owed = game.waiting_prompt()
    assert owed is not None and owed.kind == "mana_color_choice"
    assert game.stack == []
    assert "_stack_item" not in owed.data


@pytest.mark.cr("608.2")
def test_a_game_with_no_interactive_seat_resolves_exactly_as_before(
    catalog_by_name,
):
    """The determinism half. There is nobody to wait for, so the resolution runs
    to its end and the caller drains the queue — which is what a seeded
    simulation reproduces."""
    game, p1, _ = _w2g5_recall(catalog_by_name, interactive=())

    game.cast_from_hand(0, "Recall", x_value=1)

    assert game.stack == []
    assert [c.kind for c in game.pending_choices] == ["discard"]

    game.auto_resolve_pending_choices()
    assert "Recall" in [c.name for c in p1.exile]
