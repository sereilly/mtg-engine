"""Double — CR 701.10, the objects Fifth Dawn doubles.

``grammar/effects/characteristics._parse_double`` reads one arm per object:
power (Unleash Fury, 701.10b), counters (Solarion, 701.10e), unspent mana
(Doubling Cube, 701.10f) and a life total (Beacon of Immortality, 701.10d).
Solarion's and Beacon of Immortality's other lines are other groups' work
this wave, so their doubling sentences are driven here on invented cards
printing the sentence alone; Doubling Cube's whole card is in
``tests/sets/test_5dn_artifacts_later_groups.py``.

Each arm reads its noun before it commits, so a doubling of something no
arm reads keeps a refusal rather than being claimed by a neighbour.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_cards, manifest_set_path
from engine.mana_abilities import is_mana_ability
from engine.models import CardDefinition, Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle

from tests.helpers import settle


def _card(name: str, text: str, type_line: str, *, power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw.update(power=str(power), toughness=str(toughness))
    return CardDefinition(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


def _named(code: str, name: str) -> CardDefinition:
    return next(
        card for card in load_cards(manifest_set_path(code))
        if card.name == name
    )


def _game(*, hand=()) -> Game:
    island = _card("Island", "({T}: Add {U}.)", "Basic Land — Island")
    game = Game(players=[
        PlayerState("A", hand=list(hand), library=[island] * 20),
        PlayerState("B", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    settle(game)
    return game


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    settle(game)
    return permanent


_SOLARION_LINE = "{T}: Double the number of +1/+1 counters on this creature."
_BEACON_LINE = "Double target player's life total."


@pytest.mark.cr("701.10e")
def test_doubling_counters_gives_as_many_more_as_it_has():
    """"If Solarion had three +1/+1 counters on it, it would end up with six"
    (ruling 2004-12-01). Unlike the mana doubling it is no mana ability, so
    it goes on the stack."""
    creature = _card("Doubler", _SOLARION_LINE, "Artifact Creature — Construct",
                     power=1, toughness=1)
    game = _game()
    doubler = _put(game, 0, creature)
    game.place_plus1_counters(doubler, 3)

    result = game.activate_permanent_ability(0, "Doubler")
    assert result.supported, result
    settle(game)

    assert counters_on(doubler, "+1/+1") == 6
    assert doubler.effective_power == 7
    assert "Doubler ability added to stack" in game.log
    assert "Doubler gets 3 +1/+1 counters" in game.log


@pytest.mark.cr("701.10e")
def test_doubling_no_counters_puts_none():
    creature = _card("Doubler", _SOLARION_LINE, "Artifact Creature — Construct",
                     power=1, toughness=1)
    game = _game()
    doubler = _put(game, 0, creature)

    game.activate_permanent_ability(0, "Doubler")
    settle(game)

    assert counters_on(doubler, "+1/+1") == 0
    assert doubler in game.players[0].battlefield


@pytest.mark.cr("701.10d")
def test_doubling_a_life_total_is_a_gain_of_the_difference():
    """CR 701.10d, and the ruling (2007-07-15) that Beacon of Immortality's
    effect "counts as life gain": the target gains 7 and the gain is
    announced through the life-gain seam."""
    spell = _card("Doubling Beacon", _BEACON_LINE, "Instant")
    game = _game(hand=[spell])
    game.players[1].life = 7

    result = game.cast_from_hand(0, "Doubling Beacon", target_player_index=1)
    assert result.supported, result
    settle(game)

    assert game.players[1].life == 14
    assert game.players[0].life == 20
    assert "B gained 7 life from Doubling Beacon (7 -> 14)" in game.log


@pytest.mark.cr("701.10d", "107.1b")
def test_doubling_a_negative_life_total_is_a_loss():
    """"If you double a negative life total, you do the real math. A life
    total of -10 becomes -20." (ruling 2007-02-01; CR 107.1b keeps the
    negative number for an effect that doubles a life total.) Platinum Angel
    keeps the player in the game to be doubled."""
    spell = _card("Doubling Beacon", _BEACON_LINE, "Instant")
    game = _game(hand=[spell])
    _put(game, 0, _named("MRD", "Platinum Angel"))
    game.players[0].life = -10
    settle(game)

    game.cast_from_hand(0, "Doubling Beacon", target_player_index=0)
    settle(game)

    assert game.players[0].life == -20
    assert not game.players[0].lost


@pytest.mark.cr("701.10f", "605.1a")
def test_doubling_unspent_mana_is_a_mana_ability_under_a_mana_replacement():
    """CR 701.10f adds the mana, so CR 614.1a's False Dawn — "spells and
    abilities you control that would add colored mana instead add that much
    white mana" — meets the doubling: {B}{B} doubled adds {W}{W}. The
    ability targets nothing and could add mana, so it is a mana ability
    (CR 605.1a) and resolves without the stack."""
    cube = _card(
        "Doubling Rock", "{T}: Double the amount of each type of unspent mana you have.",
        "Artifact",
    )
    assert is_mana_ability(compile_card_oracle(cube).activated_abilities[0])
    game = _game(hand=[_named("APC", "False Dawn")])
    _put(game, 0, cube)
    game.cast_from_hand(0, "False Dawn")
    settle(game)
    game.players[0].mana_pool["B"] = 2

    game.activate_permanent_ability(0, "Doubling Rock")

    assert not game.stack
    pool = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    assert pool == {"B": 2, "W": 2}


@pytest.mark.cr("701.10e")
@pytest.mark.parametrize("line, type_line", [
    # No kind written: every kind at once is a different instruction.
    ("{T}: Double the number of counters on this creature.", "Creature — Test"),
    # Another permanent's pile: the count channel reads the source's.
    ("{T}: Double the number of +1/+1 counters on target creature.", "Creature — Test"),
    # A characteristic no arm reads.
    ("Double the toughness of target creature until end of turn.", "Instant"),
    # Somebody else's pool.
    ("Double the amount of each type of unspent mana target player has.", "Instant"),
])
def test_a_doubling_no_arm_reads_keeps_its_refusal(line, type_line):
    power = 1 if "Creature" in type_line else None
    card = _card("Refused", line, type_line, power=power, toughness=power)
    assert not compile_card_oracle(card).supported
