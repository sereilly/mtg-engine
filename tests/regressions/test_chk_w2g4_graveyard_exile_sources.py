"""Forbidden Crypt and Yawgmoth's Agenda exile themselves when destroyed alone.

"If a card would be put into your graveyard from anywhere, exile that card
instead." (Forbidden Crypt; Yawgmoth's Agenda prints the same sentence with
"it".) "It will replace itself being sent to the graveyard, and exile itself."
(Forbidden Crypt, ruling 2004-10-04.) The replacement's source scan
(``replacements/zone_changes._graveyard_exile_permanents``) read only the
battlefield, and a targeted destruction or a sacrifice takes the permanent off
it before its card moves — so a Disenchanted Crypt went to the graveyard while
a Tranquility'd one (whose cards move while the sweep's departure event is
open) was exiled. Champions of Kamigawa's W1G2 measured it; W2G4 fixed it by
asking the event's own permanent and the open departure event, as Samurai of
the Pale Curtain's scan does.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, hand=(), mine=(), theirs=()):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand), library=[lea["Island"]] * 10),
        PlayerState(name="P1", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed[0], placed[1]


def test_a_disenchanted_forbidden_crypt_exiles_itself(set_pool):
    lea, crypt_card = set_pool("LEA"), set_pool("MIR")["Forbidden Crypt"]
    game, (crypt,), _ = _table(set_pool, hand=[lea["Disenchant"]], mine=[crypt_card])
    assert game.cast_from_hand(0, "Disenchant", target_permanent_ids=[crypt.permanent_id]).supported
    settle(game)
    assert [card.name for card in game.players[0].exile] == ["Forbidden Crypt"]
    # The Disenchant resolves after the Crypt has gone: nothing exiles it.
    assert [card.name for card in game.players[0].graveyard] == ["Disenchant"]
    assert any(
        "Forbidden Crypt was exiled instead of going to P0's graveyard" in line
        for line in game.log
    )


def test_a_disenchanted_yawgmoths_agenda_exiles_itself(set_pool):
    lea, agenda_card = set_pool("LEA"), set_pool("INV")["Yawgmoth's Agenda"]
    game, (agenda,), _ = _table(set_pool, hand=[lea["Disenchant"]], mine=[agenda_card])
    assert game.cast_from_hand(0, "Disenchant", target_permanent_ids=[agenda.permanent_id]).supported
    settle(game)
    assert [card.name for card in game.players[0].exile] == ["Yawgmoth's Agenda"]
    assert [card.name for card in game.players[0].graveyard] == ["Disenchant"]


def test_an_opponents_crypt_exiles_itself_into_its_owners_exile(set_pool):
    """"Your graveyard" is the Crypt's controller's (CR 109.5), read as it
    last existed (CR 608.2h) once it has left: P1's Crypt destroyed by P0's
    Disenchant is exiled from P1's graveyard, and P0's Disenchant is not."""
    lea, crypt_card = set_pool("LEA"), set_pool("MIR")["Forbidden Crypt"]
    game, _, (crypt,) = _table(set_pool, hand=[lea["Disenchant"]], theirs=[crypt_card])
    assert game.cast_from_hand(0, "Disenchant", target_permanent_ids=[crypt.permanent_id]).supported
    settle(game)
    assert [card.name for card in game.players[1].exile] == ["Forbidden Crypt"]
    assert game.players[1].graveyard == []
    assert [card.name for card in game.players[0].graveyard] == ["Disenchant"]


def test_the_sweep_still_exiles_both(set_pool):
    """The road that already worked: a Tranquility takes both off in one
    event, and each is exiled."""
    lea = set_pool("LEA")
    game, _, _ = _table(
        set_pool, hand=[lea["Tranquility"]],
        mine=[set_pool("MIR")["Forbidden Crypt"], set_pool("INV")["Yawgmoth's Agenda"]],
    )
    assert game.cast_from_hand(0, "Tranquility").supported
    settle(game)
    assert sorted(card.name for card in game.players[0].exile) == [
        "Forbidden Crypt", "Yawgmoth's Agenda",
    ]
    assert [card.name for card in game.players[0].graveyard] == ["Tranquility"]
