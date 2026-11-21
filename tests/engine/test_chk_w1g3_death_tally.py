"""The turn's death tally narrowed by creature type (``engine/death_tally.py``).

"…for each Zubera that died this turn" counts what each creature *was* as it
died (CR 603.10a's look-back), every seat's deaths, tokens included, reset each
turn — and the lowering admits exactly what the tally can count: every
creature, the nontoken ones, or one creature type. A narrowing it cannot apply
refuses the line rather than being counted as though it were not printed.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game
from engine.death_tally import died_this_turn_count
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.type_changes import gain_types

from tests.helpers import _nosick, settle


def _card(name, type_line, text="", cost=1, power="1", toughness="1"):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return CardDefinition(
        name=name, mana_cost="{%d}" % cost, cmc=float(cost), type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


_SWEEP = _card("Sweep Test", "Sorcery", "Destroy all creatures.")


def _game(mine=(), theirs=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=[_nosick(Permanent(card=c)) for c in mine],
                    hand=[_SWEEP], library=[_card("Land", "Land")] * 10),
        PlayerState(name="P2", battlefield=[_nosick(Permanent(card=c)) for c in theirs],
                    library=[_card("Land", "Land")] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game


def test_a_creature_is_counted_by_the_creature_types_it_had_as_it_died():
    """A Bear that became a Zubera until end of turn dies a Zubera; a Zubera
    that lost the type does not (CR 603.10a: the look-back reads the creature
    as it last existed, through the layers)."""
    bear = _card("Painted Bear", "Creature — Bear")
    zubera = _card("Plain Zubera", "Creature — Zubera Spirit")
    game = _game(mine=[bear, zubera], theirs=[_card("Their Zubera", "Creature — Zubera")])
    painted = next(p for p in game.controlled_by(0) if p.card.name == "Painted Bear")
    gain_types(painted, subtypes=("Zubera",))
    assert game.cast_from_hand(0, "Sweep Test").supported
    settle(game)
    spec = {"history": "creatures_died_this_turn", "creature_type": "zubera"}
    # Painted Bear (as it died), Plain Zubera and the opponent's Zubera.
    assert died_this_turn_count(game, spec) == 3
    assert died_this_turn_count(game, {"history": "creatures_died_this_turn",
                                       "creature_type": "bear"}) == 1
    assert died_this_turn_count(game, {"history": "creatures_died_this_turn"}) == 3


def test_the_tally_resets_with_the_turn():
    game = _game(mine=[_card("Plain Zubera", "Creature — Zubera")])
    assert game.cast_from_hand(0, "Sweep Test").supported
    settle(game)
    spec = {"history": "creatures_died_this_turn", "creature_type": "zubera"}
    assert died_this_turn_count(game, spec) == 1
    game.start_turn(1)
    assert died_this_turn_count(game, spec) == 0


def test_an_unknown_history_or_a_narrowed_nontoken_tally_counts_nothing():
    game = _game(mine=[_card("Plain Zubera", "Creature — Zubera")])
    assert game.cast_from_hand(0, "Sweep Test").supported
    settle(game)
    assert died_this_turn_count(game, {"history": "no_such_tally"}) == 0
    assert died_this_turn_count(game, {"history": "nontoken_creatures_died_this_turn",
                                       "creature_type": "zubera"}) == 0


@pytest.mark.parametrize("line", [
    "When this creature dies, draw a card for each green creature that died this turn.",
    "When this creature dies, draw a card for each Zubera Spirit that died this turn.",
    "When this creature dies, draw a card for each nontoken Zubera that died this turn.",
    "When this creature dies, you gain 2 life for each creature you control that died this turn.",
    "When this creature dies, it deals damage to any target equal to the number of artifacts that died this turn.",
])
def test_a_narrowing_the_tally_cannot_count_refuses_the_line(line):
    card = _card("Refused Test", "Creature — Zubera", line)
    assert not compile_card_oracle(card).supported, line


@pytest.mark.parametrize("line", [
    "When this creature dies, draw a card for each creature that died this turn.",
    "When this creature dies, target opponent discards a card for each Goblin that died this turn.",
    "When this creature dies, create a 1/1 colorless Spirit creature token for each nontoken creature that died this turn.",
    "When this creature dies, it deals damage to any target equal to the number of Zubera creatures that died this turn.",
])
def test_what_the_tally_can_count_compiles_in_every_position(line):
    card = _card("Admitted Test", "Creature — Zubera", line)
    assert compile_card_oracle(card).supported, line


def test_a_token_counts_as_a_creature_that_died():
    """CR 111.7: a token is put into the graveyard before it ceases to exist,
    so a Zubera token dying is a Zubera that died."""
    token_card = dataclasses.replace(_card("Zubera Token", "Creature — Zubera"))
    game = _game()
    token = _nosick(Permanent(card=token_card))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    game._sync_control()
    assert game.cast_from_hand(0, "Sweep Test").supported
    settle(game)
    assert died_this_turn_count(
        game, {"history": "creatures_died_this_turn", "creature_type": "zubera"}
    ) == 1
    assert died_this_turn_count(game, {"history": "nontoken_creatures_died_this_turn"}) == 0
