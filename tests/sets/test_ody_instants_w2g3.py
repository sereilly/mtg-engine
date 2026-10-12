"""Odyssey instants — wave 2, group 3: **Tainted Pact**, the one card wave 1
declined.

    Exile the top card of your library. You may put that card into your hand
    unless it has the same name as another card exiled this way. Repeat this
    process until you put a card into your hand or you exile two cards with
    the same name, whichever comes first.

A file of its own because the per-type files hold one marked section per
wave-1 group and nobody else may write in them. Cards come from
`set_pool("ODY")`; the stack is drained with `tests.helpers.resolve_stack`;
every test asserts what a game showed.

What the card needed and no card before it had: a loop whose stopping clauses
are asked when the round is **over**, where the round ends in an offer — so
"over" is after the answer (`handlers/control_flow.repeat_process_until`,
`end_process_round`). The interactive tests go through `pass_priority`, the
path a person takes: CR 608.2 keeps the spell on the stack until its last
prompt is answered, and headless `resolve_top_of_stack()` deliberately does
not.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

PACT = (
    "Exile the top card of your library. You may put that card into your hand "
    "unless it has the same name as another card exiled this way. Repeat this "
    "process until you put a card into your hand or you exile two cards with "
    "the same name, whichever comes first."
)


def _duel(set_pool, library, *, interactive=True, spell=None):
    """Seat 0 holding the spell over *library* (LEA card names, top first)."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = Game(players=[
        PlayerState(
            "Caster", library=[lea[name] for name in library],
            hand=[spell or ody["Tainted Pact"]],
        ),
        PlayerState("Bystander", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    if interactive:
        game.interactive_seats = {0}
    return game


def _cast_and_pass(game, name="Tainted Pact"):
    """Cast it and let both seats pass — the priority path, which holds a
    resolution that stopped to ask (CR 608.2, CR 117.3b)."""
    assert game.queue_from_hand(0, name).supported
    first = game.priority_player_index
    if first is None:
        first = game.priority_player_index = 0
        game.priority_pass_count = 0
    game.pass_priority(first)
    return game.pass_priority(1 - first)


def _names(cards):
    return [card.name for card in cards]


def _offer(game):
    """The one prompt owed, as ``(kind, seat, text)``."""
    assert len(game.pending_choices) == 1, [c.kind for c in game.pending_choices]
    choice = game.pending_choices[0]
    return choice.kind, choice.player_index, choice.data.get("prompt")


# ---------------------------------------------------------------------------
# What it compiles to
# ---------------------------------------------------------------------------

def test_tainted_pact_compiles_as_a_loop_over_its_own_two_sentences(set_pool):
    program = compile_card_oracle(set_pool("ODY")["Tainted Pact"])

    assert program.supported, program.reason
    (loop,) = program.instructions
    assert loop.kind == "repeat_process_until"
    # Both printed stopping clauses, and nothing the card did not print.
    assert [part["kind"] for part in loop.payload["until"]] == [
        "it_happened", "exiled_this_way_share_a_name",
    ]
    # "This process" is the exile *and* the offer behind it.
    assert [step.kind for step in loop.payload["steps"]] == [
        "exile_top_of_library", "if_then",
    ]


# ---------------------------------------------------------------------------
# A person at the table
# ---------------------------------------------------------------------------

def test_tainted_pact_asks_about_each_card_and_waits_on_the_stack(set_pool):
    game = _duel(set_pool, ["Swamp", "Island", "Mountain", "Plains"])

    assert _cast_and_pass(game) == "awaiting_choice"

    caster = game.players[0]
    assert _names(caster.exile) == ["Swamp"]
    assert _offer(game) == ("optional_pay", 0, "Put Swamp into your hand?")
    # CR 608.2: the spell is still resolving, so it is on the stack and not in
    # a graveyard, and nobody is given priority around the offer.
    assert _names(item.card for item in game.stack) == ["Tainted Pact"]
    assert caster.graveyard == []
    assert game.waiting_prompt() is game.pending_choices[0]
    assert "Tainted Pact resolved and moved to graveyard" not in game.log

    # Declining is one round of the process, not the end of it.
    assert game.confirm_optional_pay(0, accept=False)
    assert _names(caster.exile) == ["Swamp", "Island"]
    assert _offer(game) == ("optional_pay", 0, "Put Island into your hand?")
    assert _names(item.card for item in game.stack) == ["Tainted Pact"]
    assert caster.hand == []


def test_tainted_pact_ends_when_a_card_is_taken(set_pool):
    game = _duel(set_pool, ["Swamp", "Island", "Mountain", "Plains"])
    _cast_and_pass(game)
    game.confirm_optional_pay(0, accept=False)
    game.confirm_optional_pay(0, accept=False)

    assert game.confirm_optional_pay(0, accept=True)

    caster = game.players[0]
    assert _names(caster.hand) == ["Mountain"]
    # The cards passed over stay in exile, and the library is not touched
    # past the card that was taken.
    assert _names(caster.exile) == ["Swamp", "Island"]
    assert _names(caster.library) == ["Plains"]
    assert game.pending_choices == []
    assert game.stack == []
    assert _names(caster.graveyard) == ["Tainted Pact"]
    assert "Tainted Pact finished resolving" in game.log


def test_tainted_pact_stops_on_a_second_card_of_one_name_and_offers_neither(set_pool):
    game = _duel(set_pool, ["Swamp", "Island", "Swamp", "Plains"])
    _cast_and_pass(game)
    game.confirm_optional_pay(0, accept=False)

    # Declining the Island exiles the second Swamp: "unless it has the same
    # name as another card exiled this way" withdraws the offer, and "you
    # exile two cards with the same name" ends the process.
    assert game.confirm_optional_pay(0, accept=False)

    caster = game.players[0]
    assert _names(caster.exile) == ["Swamp", "Island", "Swamp"]
    assert caster.hand == []
    assert _names(caster.library) == ["Plains"]
    assert game.pending_choices == []
    assert game.stack == []


def test_tainted_pact_tells_two_copies_apart_from_one_card(set_pool):
    """A deck repeats one card object per copy, so "another card" cannot be
    asked by identity: the first Swamp is offered, and only the second is the
    card that shares its name with another."""
    game = _duel(set_pool, ["Swamp", "Swamp", "Island"])

    _cast_and_pass(game)
    assert _offer(game)[2] == "Put Swamp into your hand?"
    game.confirm_optional_pay(0, accept=False)

    caster = game.players[0]
    assert _names(caster.exile) == ["Swamp", "Swamp"]
    assert game.pending_choices == []
    assert _names(caster.library) == ["Island"]


def test_tainted_pact_declined_to_the_bottom_ends_on_the_empty_library(set_pool):
    game = _duel(set_pool, ["Swamp", "Island", "Mountain"])
    _cast_and_pass(game)

    for _ in range(3):
        assert game.confirm_optional_pay(0, accept=False)

    caster = game.players[0]
    assert _names(caster.exile) == ["Swamp", "Island", "Mountain"]
    assert caster.library == [] and caster.hand == []
    # CR 101.3: a process that can no longer be performed is not repeated.
    # Nothing was drawn, so nobody loses (CR 704.5b is about a draw).
    assert game.pending_choices == []
    assert game.stack == []
    assert not caster.lost
    assert "Tainted Pact: the process cannot continue" in game.log


def test_tainted_pact_over_an_empty_library_offers_nothing(set_pool):
    game = _duel(set_pool, [])

    assert _cast_and_pass(game) == "resolved_top"

    caster = game.players[0]
    assert game.pending_choices == []
    assert caster.exile == [] and caster.hand == []
    assert _names(caster.graveyard) == ["Tainted Pact"]
    assert not caster.lost


# ---------------------------------------------------------------------------
# A seat nobody is driving
# ---------------------------------------------------------------------------

def test_tainted_pact_for_a_non_interactive_seat_takes_the_first_card(set_pool):
    """The default answers the offer the way it answers every free one, and
    taking the first card always terminates."""
    game = _duel(set_pool, ["Swamp", "Island", "Mountain"], interactive=False)
    assert game.queue_from_hand(0, "Tainted Pact").supported

    resolve_stack(game)
    game.auto_resolve_pending_choices()

    caster = game.players[0]
    assert _names(caster.hand) == ["Swamp"]
    assert caster.exile == []
    assert _names(caster.library) == ["Island", "Mountain"]
    assert game.pending_choices == []


# ---------------------------------------------------------------------------
# No hook: the loop belongs to the sentence, not to the card
# ---------------------------------------------------------------------------

def test_an_invented_card_printing_tainted_pacts_text_plays_the_same(set_pool):
    twin = _mk_card("Borrowed Bargain", "{1}{B}", "Instant", PACT)
    game = _duel(set_pool, ["Swamp", "Island", "Swamp"], spell=twin)

    assert _cast_and_pass(game, "Borrowed Bargain") == "awaiting_choice"
    assert _offer(game)[2] == "Put Swamp into your hand?"
    game.confirm_optional_pay(0, accept=False)
    game.confirm_optional_pay(0, accept=False)

    caster = game.players[0]
    assert _names(caster.exile) == ["Swamp", "Island", "Swamp"]
    assert caster.hand == [] and game.pending_choices == []


def test_a_loop_with_no_offer_in_it_runs_to_its_stopping_clause(set_pool):
    """A second card with a "repeat this process until …" needs no code. This
    one's round asks nobody anything, so sixty rounds are sixty turns of one
    loop — it must not recurse once per round."""
    digger = _mk_card(
        "Deep Excavation", "{B}", "Sorcery",
        "Exile the top card of your library. Repeat this process until you "
        "exile two cards with the same name.",
    )
    lea = set_pool("LEA")
    distinct = [card.name for card in lea.values() if card.name != "Swamp"][:60]
    game = _duel(
        set_pool, [*distinct, "Swamp", "Swamp", "Island"],
        interactive=False, spell=digger,
    )
    assert game.queue_from_hand(0, "Deep Excavation").supported

    resolve_stack(game)

    caster = game.players[0]
    assert len(caster.exile) == 62
    assert _names(caster.exile[-2:]) == ["Swamp", "Swamp"]
    assert _names(caster.library) == ["Island"]


def test_a_single_stopping_clause_is_read_without_whichever_comes_first(set_pool):
    scry = _mk_card(
        "Patient Dredging", "{B}", "Sorcery",
        "Exile the top card of your library. You may put that card into your "
        "hand. Repeat this process until you put a card into your hand.",
    )
    game = _duel(set_pool, ["Swamp", "Swamp", "Island"], spell=scry)

    _cast_and_pass(game, "Patient Dredging")
    game.confirm_optional_pay(0, accept=False)
    # No name clause was printed, so a second Swamp is offered like any card.
    assert _offer(game)[2] == "Put Swamp into your hand?"
    game.confirm_optional_pay(0, accept=True)

    caster = game.players[0]
    assert _names(caster.hand) == ["Swamp"]
    assert _names(caster.exile) == ["Swamp"]
    assert game.pending_choices == [] and game.stack == []


@pytest.mark.parametrize(
    ("line", "layer", "says"),
    [
        # A stopping clause must read a record the round writes.
        (
            "Target player mills a card. Repeat this process until you exile "
            "two cards with the same name.",
            "lowering", "no exile before it",
        ),
        (
            "Exile the top card of your library. Repeat this process until "
            "you put a card into your hand.",
            "lowering", "no step in this effect that puts one there",
        ),
        # A round that records nothing could never be seen to have stopped.
        (
            "Draw a card. Repeat this process until you put a card into your "
            "hand.",
            "lowering", "records nothing",
        ),
        # An offer anywhere but last would be answered after the question.
        (
            "You may draw a card. Exile the top card of your library. Repeat "
            "this process until you exile two cards with the same name.",
            "lowering", "not the round's last step",
        ),
        # The name relation is asked at one printed size.
        (
            "Exile the top card of your library. Repeat this process until "
            "you exile three cards with the same name.",
            "parse", "",
        ),
        # "Whichever comes first" is about two clauses.
        (
            "Exile the top card of your library. You may put that card into "
            "your hand. Repeat this process until you put a card into your "
            "hand, whichever comes first.",
            "parse", "",
        ),
    ],
)
def test_a_repeat_until_clause_this_cannot_bound_refuses(line, layer, says):
    result = compile_line(line, card_name="Loop Probe")

    assert not result.instructions
    if layer == "parse":
        assert result.parse_error
    else:
        assert not result.parse_error
        assert says in str(result.lowering_error)
