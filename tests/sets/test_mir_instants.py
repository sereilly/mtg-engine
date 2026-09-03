"""Per-card tests for Mirage's instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 2: phasing (CR 702.26) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _r2_ripple_board(set_pool, victim_name: str):
    """Reality Ripple in hand on seat 0, one permanent to aim it at on seat 1."""
    pool = set_pool("MIR")
    victim = Permanent(card=pool[victim_name])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool["Reality Ripple"]],
            library=[pool["Island"]] * 6,
        ),
        PlayerState(name="P2", battlefield=[victim], library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, victim


@pytest.mark.parametrize(
    "victim_name", ["Sandbar Crocodile", "Island", "Charcoal Diamond"]
)
def test_reality_ripple_phases_out_all_three_printed_types(set_pool, victim_name):
    """"Target **artifact, creature, or land** phases out."

    The card was already reported supported, claimed every printed sentence and
    derived a correct picker — and the handler then declined two of the three
    types, because the type test was hardcoded to "creature" rather than read
    off the noun phrase the picker had already enumerated with. Nothing failed;
    the spell resolved and did nothing. That is the class only a game finds.
    """
    game, victim = _r2_ripple_board(set_pool, victim_name)

    result = game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(victim)
    assert victim in game.players[1].phased_out


def test_a_permanent_reality_ripple_phased_out_comes_back_once(set_pool):
    """The incoming half of CR 702.26a reads the holding list rather than the
    keyword, so a permanent with no phasing of its own returns exactly once and
    then stays."""
    game, victim = _r2_ripple_board(set_pool, "Island")
    game.cast_from_hand(
        0, "Reality Ripple", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    game.start_turn(1)
    assert game.is_on_battlefield(victim)

    game.start_next_turn()
    game.start_next_turn()
    assert game.is_on_battlefield(victim)


# --- Round 6: a handler that pinned a type its card did not print ---

def test_disempower_tucks_either_of_its_printed_types(set_pool):
    """"Put target **artifact or enchantment** on top of its owner's library."

    Reality Ripple's defect, one file over and found the same way. The tuck
    lowering demanded ``card_types == ("creature",)`` and the handler asked
    ``is_creature`` — two copies of a narrowing the printed noun phrase does not
    have, on an effect that is the same for every permanent type: CR 400.3's
    owner lookup and the library move do not care what was moved.
    """
    pool = set_pool("MIR")
    for host_name in ("Charcoal Diamond", "Armor of Thorns"):
        host = Permanent(card=pool[host_name])
        game = Game(players=[
            PlayerState(name="P1", hand=[pool["Disempower"]],
                        library=[pool["Island"]] * 5),
            PlayerState(name="P2", battlefield=[host],
                        library=[pool["Island"]] * 5),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        result = game.cast_from_hand(
            0, "Disempower", target_player_index=1, target_permanent_index=0
        )
        assert result.supported, result.details
        game.resolve_stack()

        assert not game.is_on_battlefield(host)
        assert game.players[1].library[0].name == host_name


def test_disempower_still_refuses_a_creature(set_pool):
    """The narrowing is carried, not dropped — which is the other half of the
    fix. Widening the lowering to any noun phrase would be worth nothing if the
    handler then moved whatever it was handed."""
    pool = set_pool("MIR")
    creature = Permanent(card=pool["Femeref Knight"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Disempower"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[creature], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.cast_from_hand(
        0, "Disempower", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()

    assert game.is_on_battlefield(creature)


# --- Round 9: the tutor cycle (CR 701.19 / 701.23) ---

from engine.search_filters import search_matches


def _r9_tutor(set_pool, spell: str, library_names: list[str]):
    """*spell* cast on seat 0 over a library built from *library_names*."""
    pool = set_pool("MIR")
    game = Game(players=[
        PlayerState(
            name="P1", hand=[pool[spell]],
            library=[pool[name] for name in library_names],
        ),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    (choice,) = game.pending_choices
    assert choice.kind == "search_library"
    return game, choice


_R9_LIBRARY = [
    "Island", "Femeref Knight", "Charcoal Diamond", "Armor of Thorns", "Island",
]


def test_enlightened_tutor_finds_either_of_its_two_types(set_pool):
    """"Search your library for an **artifact or enchantment** card…"

    A printed union is an OR — the reading `any_colors` beside it already gets,
    and the one every noun-phrase matcher in this engine gives a multi-type
    filter. The lowering used to refuse a union outright ("the search picker
    tests one card type"), which was the safe direction and cost all three
    tutors their cards.
    """
    _game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    assert choice.data["card_type"] == ("artifact", "enchantment")
    assert choice.data["destination"] == "library_top"


def test_enlightened_tutor_offers_only_the_matching_cards(set_pool):
    """The union narrows the search; it does not widen it."""
    game, choice = _r9_tutor(set_pool, "Enlightened Tutor", _R9_LIBRARY)

    legal = {
        card.name for card in game.players[0].library
        if search_matches(card, choice.data)
    }

    assert legal == {"Charcoal Diamond", "Armor of Thorns"}


def test_a_tutor_puts_its_find_on_top_after_the_shuffle(set_pool):
    """"…, reveal it, **then shuffle and put that card on top**."

    The order is the effect. Placing the find first and then shuffling — which
    is what falling through to the shared shuffle would do — is the card doing
    nothing at all, so the destination branch shuffles itself and returns.
    """
    game, _choice = _r9_tutor(set_pool, "Worldly Tutor", _R9_LIBRARY)
    index = next(
        i for i, card in enumerate(game.players[0].library)
        if card.name == "Femeref Knight"
    )

    assert game.confirm_search_library(0, index)

    assert game.players[0].library[0].name == "Femeref Knight"
    assert len(game.players[0].library) == len(_R9_LIBRARY)


# --- W1G2: "that turn's end step" is not the next end step there is ---

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle


def _w1g2_fortune_duel(set_pool, copies=2):
    game = Game(players=[
        PlayerState(
            name="P1",
            hand=[set_pool("MIR")["Final Fortune"] for _ in range(copies)],
            life=20,
        ),
        PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_final_fortune_does_not_end_the_turn_it_was_cast_in(set_pool):
    """"Take an extra turn after this one. At the beginning of **that turn's**
    end step, you lose the game."

    "That turn" is the turn the sentence in front of it queued (CR 500.7 puts it
    directly after this one), so it is neither ``next_end_step`` — the next end
    step there is, which on a main-phase cast is *this* turn's — nor
    ``controllers_next_end_step``. Its own delayed event, announced only on an
    extra turn.
    """
    program = compile_card_oracle(set_pool("MIR")["Final Fortune"])
    assert program.supported, program.reason

    game = _w1g2_fortune_duel(set_pool)
    assert game.cast_from_hand(0, "Final Fortune").supported
    game.resolve_stack()
    assert game.extra_turn_queue == [0], game.log

    game.resolve_end_step(0)
    game.resolve_stack()

    assert not game.players[0].lost, game.log


def test_final_fortune_ends_the_extra_turn_it_bought(set_pool):
    """The other half of the same assertion — a delay nothing announces is an
    ability that waits forever, which is what this event would be without the
    end step's fire site."""
    game = _w1g2_fortune_duel(set_pool)
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    game.resolve_end_step(0)
    game.resolve_stack()

    game.start_next_turn()
    assert game.current_turn_is_extra
    game.resolve_end_step(game.active_player_index)
    game.resolve_stack()

    assert game.players[0].lost, game.log


def test_a_second_final_fortune_does_not_fire_in_the_turn_it_was_cast(set_pool):
    """The card's whole use is chaining, so the second copy is cast **during**
    an extra turn — the very turn whose end step is about to be announced.

    ``delayed_triggers.EVENTS_AFTER_THIS_TURN`` is what keeps that entry
    waiting: it names a turn the creating effect had only just queued, so the
    announcement made in its own turn is not the one it is for. Without the
    guard the chain would end the game a full turn early.
    """
    game = _w1g2_fortune_duel(set_pool)
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    game.resolve_end_step(0)
    game.resolve_stack()
    game.start_next_turn()

    extra_turn = game.turn
    game.cast_from_hand(0, "Final Fortune")
    game.resolve_stack()
    entries = [e for e in game.delayed_triggers
               if e.event == "granted_extra_turns_end_step"]
    assert len(entries) == 2, entries
    assert {e.armed_turn for e in entries} == {extra_turn - 1, extra_turn}

    game.resolve_end_step(game.active_player_index)
    game.resolve_stack()

    # The first copy's ability fires here — this is the turn it bought. The
    # second is still waiting for the turn *it* bought.
    still_waiting = [e for e in game.delayed_triggers
                     if e.event == "granted_extra_turns_end_step"]
    assert len(still_waiting) == 1, game.log
    assert still_waiting[0].armed_turn == extra_turn


def test_that_turn_refuses_without_a_grant_in_front_of_it(set_pool):
    """A back-reference with no producer names nothing, and the ability it would
    arm answers to an event that only ever happens on somebody's extra turn — so
    it would sit on the waiting list for the rest of the game while the card
    compiled clean."""
    result = compile_line(
        "At the beginning of that turn's end step, you lose the game.",
        card_name="Invented Card",
    )
    assert result.parse_error is None
    assert result.lowering_error is not None
    assert "granted an extra turn" in result.lowering_error
