"""CR 702.38: amplify.

"Amplify N" means "As this object enters, reveal any number of cards from your
hand that share a creature type with it. This permanent enters with N +1/+1
counters on it for each card revealed this way. You can't reveal this card or
any other cards that are entering the battlefield at the same time as this
card." (702.38a) "If a creature has multiple instances of amplify, each one
works separately." (702.38b)

Built from invented cards, so each test is about the rule rather than about a
Legions printing (``tests/sets/test_lgn_creatures.py`` drives those).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

_CATALOG = {card.name: card for card in load_catalog()}


def _beast(name: str, text: str = "", type_line: str = "Creature — Beast"):
    return _mk_card(name, type_line, text)


def _game(hand, *, interactive=False, board=()):
    p1 = PlayerState(name="A", hand=list(hand), battlefield=list(board),
                     library=[_CATALOG["Island"]] * 5)
    p2 = PlayerState(name="B", library=[_CATALOG["Island"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game, p1


def _enter(game, card) -> Permanent:
    owner = game.players[0]
    assert game.take_card_from_hand(owner, card)
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, permanent, None)
    return permanent


@pytest.mark.cr("702.38a", "614.1c")
def test_amplify_n_is_n_counters_per_card_sharing_a_creature_type():
    amplifier = _beast("Amplify Probe", "Amplify 2")
    kin = _beast("Kindred Beast")
    stranger = _mk_card("Stranger", "Creature — Goblin", "")
    game, p1 = _game([amplifier, kin, kin, stranger])
    permanent = _enter(game, amplifier)
    assert counters_on(permanent, "+1/+1") == 4
    assert [c.name for c in p1.hand] == ["Kindred Beast", "Kindred Beast", "Stranger"]


@pytest.mark.cr("702.38a", "701.20a")
def test_the_revealed_cards_are_shown_to_every_player_and_stay_in_the_hand():
    amplifier = _beast("Amplify Probe", "Amplify 1")
    kin = _beast("Kindred Beast")
    game, p1 = _game([amplifier, kin])
    _enter(game, amplifier)
    assert game.reveal_events[-1] == {"id": game.reveal_events[-1]["id"], "seat": 0,
                                      "cards": ["Kindred Beast"]}
    assert "A revealed Kindred Beast for Amplify Probe's amplify" in game.log
    assert [c.name for c in p1.hand] == ["Kindred Beast"]


@pytest.mark.cr("702.38a")
def test_a_creature_of_several_types_shares_with_a_card_of_any_of_them():
    amplifier = _mk_card("Bird Soldier Probe", "Creature — Bird Soldier", "Amplify 1")
    bird = _mk_card("A Bird", "Creature — Bird", "")
    soldier = _mk_card("A Soldier", "Creature — Human Soldier", "")
    game, _p1 = _game([amplifier, bird, soldier])
    permanent = _enter(game, amplifier)
    assert counters_on(permanent, "+1/+1") == 2


@pytest.mark.cr("702.38a")
def test_any_number_includes_none_and_is_the_controllers_choice():
    amplifier = _beast("Amplify Probe", "Amplify 1")
    kin = _beast("Kindred Beast")
    game, _p1 = _game([amplifier, kin, kin], interactive=True)
    permanent = _enter(game, amplifier)
    (choice,) = game.pending_choices_of("entry_reveal", 0)
    assert game._entry_reveal_candidates(choice) == [0, 1]
    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[])
    assert counters_on(permanent, "+1/+1") == 0
    assert not game.pending_choices


@pytest.mark.cr("702.38a")
def test_a_card_sharing_no_creature_type_cannot_be_revealed():
    amplifier = _beast("Amplify Probe", "Amplify 1")
    stranger = _mk_card("Stranger", "Creature — Goblin", "")
    kin = _beast("Kindred Beast")
    game, _p1 = _game([amplifier, stranger, kin], interactive=True)
    permanent = _enter(game, amplifier)
    assert not game.resolve_pending_choice("entry_reveal", 0, hand_indices=[0])
    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[1])
    assert counters_on(permanent, "+1/+1") == 1


@pytest.mark.cr("702.38a")
def test_cards_entering_at_the_same_time_cannot_be_revealed():
    """The last sentence of the rule, through the road that puts several cards
    from a hand onto the battlefield at once (Manabond's "put all ... cards
    from it" spelling, here with creatures)."""
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction

    first = _beast("First Probe", "Amplify 1")
    second = _beast("Second Probe", "Amplify 1")
    kept = _mk_card("Kept Wolf", "Instant — Beast", "")
    game, p1 = _game([first, second, kept])
    instruction = OracleInstruction(
        "put_cards_from_hand_onto_battlefield", "",
        {"all": True, "card_types": ["creature"]},
    )
    context = OracleExecutionContext(caster=p1, target=game.players[1], card=first)
    EFFECT_HANDLERS["put_cards_from_hand_onto_battlefield"](game, instruction, context)
    entered = {p.card.name: counters_on(p, "+1/+1") for p in game.controlled_by(0)}
    # Neither reveals the other; each reveals the (tribal) Beast left in hand.
    assert entered == {"First Probe": 1, "Second Probe": 1}
    assert all(event["cards"] == ["Kept Wolf"] for event in game.reveal_events)


@pytest.mark.cr("702.38b")
def test_each_instance_of_amplify_works_separately():
    amplifier = _beast("Twice Probe", "Amplify 1\nAmplify 3")
    kin = _beast("Kindred Beast")
    game, _p1 = _game([amplifier, kin])
    permanent = _enter(game, amplifier)
    assert counters_on(permanent, "+1/+1") == 4
    assert len(game.reveal_events) == 2


@pytest.mark.cr("702.38b")
def test_each_instance_is_its_own_choice_for_a_person():
    amplifier = _beast("Twice Probe", "Amplify 1\nAmplify 3")
    kin = _beast("Kindred Beast")
    game, _p1 = _game([amplifier, kin], interactive=True)
    permanent = _enter(game, amplifier)
    first, second = game.pending_choices_of("entry_reveal", 0)
    assert (first.data["counters_each"], second.data["counters_each"]) == (1, 3)
    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[])
    assert game.resolve_pending_choice("entry_reveal", 0, hand_indices=[0])
    assert counters_on(permanent, "+1/+1") == 3


@pytest.mark.cr("702.38a")
def test_amplify_needs_its_number():
    """"Amplify N": a line naming no number is no ability the engine can carry
    out, and the card stays unsupported naming it rather than entering with
    its counters silently dropped."""
    assert compile_card_oracle(_beast("Numbered", "Amplify 2")).supported
    program = compile_card_oracle(_beast("Numberless", "Amplify"))
    assert not program.supported and "Amplify" in program.reason


@pytest.mark.cr("702.38a", "708.8")
def test_a_permanent_turned_face_up_does_not_amplify():
    from engine.face_down import face_down_card, turn_face_up

    amplifier = _beast("Amplify Probe", "Amplify 1")
    kin = _beast("Kindred Beast")
    game, _p1 = _game([kin])
    permanent = Permanent(card=face_down_card(amplifier))
    game._put_permanent_onto_battlefield(0, permanent, None)
    assert turn_face_up(game, permanent, how="test")
    assert counters_on(permanent, "+1/+1") == 0 and not game.reveal_events
