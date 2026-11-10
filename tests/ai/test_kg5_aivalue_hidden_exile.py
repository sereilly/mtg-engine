"""A rehearsal copy does not know what a face-down exiled card is unless its
seat may look at it (CR 406.3; ``ai_scratch_copy.conceal_from``).

Shared Fate: "If a player would draw a card, that player exiles the top card
of one of their opponents' libraries face down instead. Each player may look
at cards they exiled with this enchantment, and they may play lands and cast
spells from among those cards." The cards A exiles off B's library are B's,
in B's exile, and face down to B — but a scratch copy for B carried them as
they were, so a rehearsal of B's knew which of its cards A could cast. Now
they are pooled with B's library and dealt back, the records that grant A's
play following the card dealt; A, who may look, keeps them.
"""

from __future__ import annotations

from functools import lru_cache

from engine.ai_scratch_copy import _scratch
from engine.card_loader import load_catalog
from engine.exiler_grants import exiler_play_permission
from engine.game import Game
from engine.linked_exile import face_down_exiled_cards
from engine.models import Permanent, PlayerState

from tests.helpers import _nosick, settle

A, B = 0, 1


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _shared_fate_table(b_library: list[str]) -> Game:
    """A controls Shared Fate and draws twice: the top two cards of B's
    library (*b_library*, top first) go to B's exile face down."""
    catalog = _catalog()
    game = Game(players=[
        PlayerState(name="A", library=[catalog["Island"]] * 10),
        PlayerState(name="B", library=[catalog[name] for name in b_library]),
    ])
    game.enforce_mana_costs = False
    fate = Permanent(card=catalog["Shared Fate"])
    game._put_permanent_onto_battlefield(A, fate, None)
    _nosick(fate)
    game.start_turn(A)
    settle(game)
    game._draw_with_replacements(game.players[A], 2)
    settle(game)
    assert len(game.players[B].exile) == 2
    return game


SPELLS = ["Lightning Bolt", "Shivan Dragon"]
LANDS = ["Forest"] * 6


def _names(cards) -> list[str]:
    return [card.name for card in cards]


def test_a_copy_for_the_owner_deals_its_face_down_exile_again():
    """Two tables that differ only in which of B's cards A exiled — the two
    spells, or two Forests with the spells left in B's library — give B the
    same copy: the same exile, the same library. Validated backwards: on
    59f133e63 the copy kept the spells in exile on the first table only."""
    spells_exiled = _shared_fate_table([*SPELLS, *LANDS])
    lands_exiled = _shared_fate_table(["Forest", "Forest", *SPELLS, "Forest", "Forest", "Forest", "Forest"])
    assert _names(face_down_exiled_cards(spells_exiled, B, viewer_index=B)) == SPELLS
    assert _names(spells_exiled.players[B].exile) == SPELLS
    copies = [_scratch(table, None, True, B)[0] for table in (spells_exiled, lands_exiled)]
    assert _names(copies[0].players[B].exile) == _names(copies[1].players[B].exile)
    assert _names(copies[0].players[B].library) == _names(copies[1].players[B].library)
    # The real game is untouched, and the cards stay face down on the copy.
    assert _names(spells_exiled.players[B].exile) == SPELLS
    assert len(face_down_exiled_cards(copies[0], B, viewer_index=B)) == 2


def test_the_exiler_keeps_what_it_may_look_at_and_its_play_follows_the_deal():
    """A copy for A — the seat that exiled the cards and may look at them —
    keeps them as they are; on B's copy, A's permission to play is held by
    whatever card was dealt in, through the same records."""
    game = _shared_fate_table([*SPELLS, *LANDS])
    mine = _scratch(game, None, True, A)[0]
    assert _names(mine.players[B].exile) == SPELLS
    assert all(exiler_play_permission(mine, A, card) is not None for card in mine.players[B].exile)
    theirs = _scratch(game, None, True, B)[0]
    assert all(
        exiler_play_permission(theirs, A, card) is not None for card in theirs.players[B].exile
    )
    assert sorted(_names([*theirs.players[B].exile, *theirs.players[B].library])) == sorted(
        [*SPELLS, *LANDS]
    )
