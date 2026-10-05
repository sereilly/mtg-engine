"""'You may cast this spell as though it had flash **if you pay {2} more to
cast it**' — the price is charged, on every card that prints the sentence.

Invasion prints it on five sorceries (Breaking Wave, Ghitu Fire, Rout,
Saproling Symbiosis, Twilight's Call). ``cast_timing._FLASH_PERMISSION`` is
*searched for*, so it matched the first nine words of the priced sentence:
``casts_at_instant_speed`` opened the instant window and nothing charged the
{2}. Four of the five reported supported with every sentence claimed — the
coverage census asked the same searching reader — and were instant-speed spells
for their sorcery price.

Pool-wide and by behaviour: the sweep reads the price off the printed line and
asks ``cost_modifiers.spell_cost_tax``, the one function the cast path, the AI
and the client's castable badge all read a spell's extra cost from.
"""

import re

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_timing import (casts_at_instant_speed, flash_permission_sentence,
                                flash_surcharge)
from engine.cost_modifiers import spell_cost_tax

_PRICED = re.compile(r"as though it had flash if you pay \{(\d+)\} more", re.I)


def _priced_cards():
    seen = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            match = _PRICED.search(card.oracle_text or "")
            if match is not None:
                seen.setdefault(card.name, (card, int(match.group(1))))
    return list(seen.values())


def _game(active: int, phase: str) -> Game:
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = active
    game.current_turn_phase = phase
    return game


def test_every_priced_flash_permission_charges_its_price():
    cards = _priced_cards()
    assert len(cards) >= 5, "the sweep must see Invasion's five"
    for card, price in cards:
        assert flash_surcharge(card.oracle_text) == price, card.name
        assert casts_at_instant_speed(card), card.name
        # The caster's own main phase with an empty stack: sorcery timing, so
        # the permission is not being used and nothing is owed.
        assert spell_cost_tax(_game(0, "precombat_main"), 0, card)[0] == 0, card.name
        # The opponent's turn, and the caster's own combat: both are times a
        # sorcery could not be cast.
        assert spell_cost_tax(_game(1, "precombat_main"), 0, card)[0] == price, card.name
        assert spell_cost_tax(_game(0, "combat"), 0, card)[0] == price, card.name


def test_the_census_reader_does_not_claim_a_rider_it_cannot_price():
    """The coverage channel matches the sentence whole, so a permission with a
    rider nothing implements is left unclaimed rather than credited on its
    first nine words."""
    assert flash_permission_sentence("you may cast this spell as though it had flash")
    assert flash_permission_sentence(
        "you may cast this spell as though it had flash if you pay {2} more to cast it"
    )
    assert not flash_permission_sentence(
        "you may cast this spell as though it had flash if you sacrifice a creature"
    )
    assert not flash_permission_sentence(
        "you may cast this spell as though it had flash if you pay {1}{u} more to cast it"
    )
