"""``engine/target_requirements.py``: the sentence as a template, the shapes
of announcement it is asked of, and the seats that have to obey it without
being told.

The whole-pool half is ``test_target_requirement_census.py``. This file is the
table's own edges, driven with **invented** cards so nothing here can pass
against a card name: a requirement that names a Wall instead of a Flagbearer,
an announcement of two targets, one that may name none, and an AI seat.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_abilities import choose_activation_action
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.target_requirements import (must_choose_line, one_slot,
                                        requirements_binding)

from tests.helpers import _mk_card, _nosick, resolve_stack


_SENTENCE = (
    "While an opponent is choosing targets as part of casting a spell they "
    "control or activating an ability they control, that player must choose at "
    "least one {noun} on the battlefield if able."
)
_REFUSAL = "must be chosen as a target if able"


def _bannerman(noun="Flagbearer", type_line="Creature - Human Flagbearer"):
    return _mk_card(
        name=f"Test {noun} Herald", type_line=type_line,
        oracle_text=_SENTENCE.format(noun=noun), power=1, toughness=3,
    )


def _spell(name, text, type_line="Instant"):
    return _mk_card(name=name, mana_cost="{1}", type_line=type_line, oracle_text=text)


def _duel(mine=(), theirs=(), *, hand0=()):
    board0 = [_nosick(Permanent(card=card)) for card in mine]
    board1 = [_nosick(Permanent(card=card)) for card in theirs]
    filler = _mk_card(name="Filler", type_line="Land")
    game = Game(players=[
        PlayerState(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        PlayerState(name="P1", battlefield=board1, library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game, board0, board1


_BEARS = _mk_card(name="Test Bears", type_line="Creature - Bear", power=2, toughness=2)
_WALL = _mk_card(name="Test Wall", type_line="Creature - Wall", power=0, toughness=4)
_BOLT = _spell("Test Bolt", "Test Bolt deals 3 damage to any target.")
_GROWTH = _spell("Test Growth", "Target creature gets +3/+3 until end of turn.")
_PINGER = _mk_card(
    name="Test Pinger", type_line="Creature - Human Wizard", power=1, toughness=1,
    oracle_text="{T}: This creature deals 1 damage to any target.",
)


# -- the sentence ----------------------------------------------------------------

def test_the_sentence_is_read_whole_and_its_noun_is_payload():
    """The printed line, and the same line about another creature type: the
    noun goes through the grammar's noun parser, so a card printing "at least
    one Wall" needs no code. The noun comes back as printed, for the refusal a
    player reads."""
    described, noun = must_choose_line(_SENTENCE.format(noun="Flagbearer"))
    assert described == {"type_filter": "creature", "subtype_filter": "flagbearer"}
    assert noun == "Flagbearer"
    assert must_choose_line(_SENTENCE.format(noun="Wall"))[0] == {
        "type_filter": "creature", "subtype_filter": "wall",
    }
    # The lowercased, unpunctuated spelling the support gate hands it.
    assert must_choose_line(_SENTENCE.format(noun="Flagbearer").lower().rstrip(".")) is not None


@pytest.mark.parametrize("line", [
    # A seat the reader has no observer to answer: whose "you"?
    _SENTENCE.format(noun="creature you control"),
    # A word that is no type at all.
    _SENTENCE.format(noun="Glimmerer"),
    # A different count is a different rule.
    _SENTENCE.format(noun="Flagbearer").replace("at least one", "at least two"),
    # A rider nothing here carries out.
    _SENTENCE.format(noun="Flagbearer").replace("if able.", "if able and loses 1 life."),
    # Not "if able": an unconditional demand is not this sentence.
    _SENTENCE.format(noun="Flagbearer").replace(" if able", ""),
    "While an opponent is choosing targets, that player must choose a Flagbearer.",
])
def test_the_reader_refuses_a_line_it_does_not_carry_out_in_full(line):
    """Loud refusal over a silent partial: each of these compiles to an
    **unsupported** card naming the clause, never to a creature that enters
    play and demands nothing."""
    assert must_choose_line(line) is None
    card = _mk_card(name="Test Herald", type_line="Creature - Human", oracle_text=line)
    assert not compile_card_oracle(card).supported


def test_a_card_printing_the_sentence_is_supported_by_the_table_and_not_by_a_name():
    program = compile_card_oracle(_bannerman())
    assert program.supported
    wall_herald = _bannerman("Wall", "Creature - Human")
    assert compile_card_oracle(wall_herald).supported


# -- the board ------------------------------------------------------------------

def test_another_noun_binds_the_same_way():
    """An invented herald demanding "at least one Wall": the opponent's bolt
    has to find the Wall — the herald itself is no Wall and is not what must
    be chosen — and with no Wall anywhere it binds nothing."""
    herald = _bannerman("Wall", "Creature - Human")
    game, _mine, theirs = _duel([], [herald, _WALL, _BEARS], hand0=[_BOLT, _BOLT])
    _herald, wall, bears = theirs
    assert [noun for _described, noun, _source in requirements_binding(game, 0)] == ["Wall"]
    assert requirements_binding(game, 1) == []
    offered = game.cast_target_spec(0, _BOLT)["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Test Wall"]
    refused = game.queue_from_hand(0, "Test Bolt", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and "at least one Wall" in refused.details
    assert game.queue_from_hand(0, "Test Bolt", target_permanent_ids=[wall.permanent_id]).supported
    resolve_stack(game)
    assert wall.damage_marked == 3

    game.remove_from_battlefield(wall)
    assert game.cast_from_hand(0, "Test Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


def test_two_targets_owe_one_flagbearer_between_them():
    """"Two target creatures" names two; one of them has to be the Flagbearer
    and the other is free. The list is not narrowed — it could not say this —
    and carries what one of the choices must be."""
    pair = _spell("Test Pair", "Tap two target creatures.", "Sorcery")
    assert compile_card_oracle(pair).supported
    game, mine, theirs = _duel([_BEARS], [_bannerman(), _BEARS], hand0=[pair])
    bearer, their_bears = theirs
    spec = game.cast_target_spec(0, pair)
    assert not one_slot(spec)
    assert len(spec["valid_targets"]) == 3
    assert [entry["id"] for entry in spec["required_targets"]] == [bearer.permanent_id]

    refused = game.queue_from_hand(
        0, "Test Pair", target_permanent_ids=[mine[0].permanent_id, their_bears.permanent_id],
    )
    assert not refused.supported and _REFUSAL in refused.details, refused
    assert game.cast_from_hand(
        0, "Test Pair", target_permanent_ids=[bearer.permanent_id, their_bears.permanent_id],
    ).supported
    assert bearer.tapped and their_bears.tapped and not mine[0].tapped


def test_up_to_one_target_may_not_dodge_by_naming_none():
    """The reading the rulings do not settle, pinned so that changing it is a
    decision: "must choose at least one Flagbearer … if able", and a player
    who may name one target is able to. An "up to one" cast that names nobody
    is refused while the Flagbearer is a legal target, and accepted with none
    on the board."""
    maybe = _spell("Test Maybe", "Tap up to one target creature.")
    assert compile_card_oracle(maybe).supported
    game, _mine, theirs = _duel([], [_bannerman(), _BEARS], hand0=[maybe])
    refused = game.queue_from_hand(0, "Test Maybe")
    assert not refused.supported and _REFUSAL in refused.details, refused
    assert game.cast_from_hand(
        0, "Test Maybe", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    assert theirs[0].tapped

    free, _mine, _theirs = _duel([], [_BEARS], hand0=[maybe])
    assert free.cast_from_hand(0, "Test Maybe").supported


def test_a_flagbearer_the_spell_cannot_target_binds_nothing():
    """"If able" is the legal list. A Flagbearer with shroud is in nobody's
    list, so the bolt goes where its caster likes; the requirement gives no
    permission to target what could not be targeted."""
    hidden = dataclasses.replace(
        _mk_card(
            name="Test Hidden Herald", type_line="Creature - Human Flagbearer",
            oracle_text="Shroud\n" + _SENTENCE.format(noun="Flagbearer"),
            power=1, toughness=1,
        ),
        keywords=("Shroud",),
    )
    assert compile_card_oracle(hidden).supported
    game, _mine, theirs = _duel([], [hidden, _BEARS], hand0=[_BOLT])
    assert requirements_binding(game, 0)
    spec = game.cast_target_spec(0, _BOLT)
    assert "required_targets" not in spec
    assert not game.queue_from_hand(
        0, "Test Bolt", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    assert game.cast_from_hand(0, "Test Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


# -- the seats nobody tells -----------------------------------------------------

def test_an_ai_seat_aims_its_burn_at_the_flagbearer_and_holds_its_pump():
    """The policy asks the engine's own gate, so it never proposes a cast the
    gate refuses: a bolt it would have sent to the face is re-aimed at the
    Flagbearer on that board, and a pump it wanted on its own creature is not
    turned into a gift — with no Flagbearer of its own, the card stays in
    hand."""
    game, mine, theirs = _duel([_BEARS], [_bannerman(), _BEARS], hand0=[_BOLT])
    bearer = theirs[0]
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Test Bolt"
    assert action.target_permanent_ids == [bearer.permanent_id]
    assert game.queue_from_hand(0, action.card_name, **cast_announcement(action)).supported
    resolve_stack(game)
    assert bearer.damage_marked == 3 and game.players[1].life == 20

    pump, _mine, _theirs = _duel([_BEARS], [_bannerman()], hand0=[_GROWTH])
    assert choose_cast_action(pump, 0) is None
    own, _mine, _theirs = _duel([_BEARS, _bannerman()], [_bannerman()], hand0=[_GROWTH])
    aimed = choose_cast_action(own, 0)
    assert aimed is not None
    named = own.permanent_at(aimed.target_player_index, aimed.target_permanent_index)
    assert aimed.target_player_index == 0 and named.has_type("flagbearer")


def test_an_ai_seat_aims_an_any_target_ability_at_the_flagbearer():
    """…and the activation half: a pinger the policy would have pointed at the
    opposing face names the Flagbearer's slot instead, and the engine takes
    the activation."""
    game, _mine, theirs = _duel([_PINGER], [_bannerman()])
    bearer = theirs[0]
    action = choose_activation_action(game, 0)
    assert action is not None
    assert (action.target_player_index, action.target_permanent_index) == (
        1, game.battlefield_index_of(bearer),
    )
    assert game.queue_permanent_ability(
        0, action.permanent_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
    ).supported
    resolve_stack(game)
    assert bearer.damage_marked == 1 and game.players[1].life == 20
