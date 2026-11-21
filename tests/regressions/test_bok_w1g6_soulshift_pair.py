"""Two soulshift triggers announced together name two different cards.

Found driving Forked-Branch Garami ("Soulshift 4, soulshift 4", BOK W1G6),
and true of the shipped Champions of Kamigawa soulshift creatures: two of
them dying to one Wrath of God put two dies triggers on the stack, each
choosing its own target as it goes there (CR 603.3d). A seat nobody asks
named the **same** card for both — the first offered — so once the first
resolved, the second's target was gone and it did nothing (CR 608.2b): legal
(Forked-Branch Garami's 2005-02-01 ruling allows it), and never worth more
than the card beside it. The default now ranks a card another of the seat's
waiting abilities already names behind the rest
(``ai_graveyard_returns.graveyard_slots_named_on_stack``).
"""

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import settle


def _table(set_pool, *, mine, graveyard, hand):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="Alice", hand=list(hand), graveyard=list(graveyard),
                    library=[lea["Island"]] * 10),
        PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    for card in mine:
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game


def test_two_chk_soulshifts_dying_together_return_two_spirit_cards(set_pool):
    """Hundred-Talon Kami (soulshift 4) and Scuttling Death (soulshift 4)
    die to one Wrath of God with Hana Kami and Kami of Ancient Law in the
    graveyard: each trigger names one, and both come back."""
    chk = set_pool("CHK")
    game = _table(
        set_pool,
        mine=[chk["Hundred-Talon Kami"], chk["Scuttling Death"]],
        graveyard=[chk["Hana Kami"], chk["Kami of Ancient Law"]],
        hand=[set_pool("LEA")["Wrath of God"]],
    )
    assert game.queue_from_hand(0, "Wrath of God").supported
    settle(game)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Hana Kami", "Kami of Ancient Law",
    ], game.log
    named = [line for line in game.log if ": targets " in line]
    assert len(named) == 2 and len(set(line.split(": targets ")[1] for line in named)) == 2


def test_with_one_spirit_card_both_still_name_it(set_pool):
    """With one legal card the ranking has nothing else to offer: both name
    it, the first returns it and the second does not resolve (CR 608.2b)."""
    chk = set_pool("CHK")
    game = _table(
        set_pool,
        mine=[chk["Hundred-Talon Kami"], chk["Scuttling Death"]],
        graveyard=[chk["Hana Kami"]],
        hand=[set_pool("LEA")["Wrath of God"]],
    )
    assert game.queue_from_hand(0, "Wrath of God").supported
    settle(game)
    assert [card.name for card in game.players[0].hand] == ["Hana Kami"]
    assert any("608.2b" in line for line in game.log), game.log
