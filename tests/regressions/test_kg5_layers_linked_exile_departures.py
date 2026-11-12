"""A linked-exile entry ends when its card leaves exile (CR 400.7, 406.3).

"Pay 1 life: Exile the top card of your library face down. Put that card into
your hand at the beginning of your next end step." (Necropotence.) The face-down
fact lives on the exiling permanent's record (``engine/linked_exile.py``),
because two copies of one card are the same ``CardDefinition`` object and only
the record of the exiling can tell them apart. Necropotence's card leaves exile
by its **delayed** ability (``put_exiled_cards_into_zone``), which reads the
cards its creation captured and never drains the record — so the entry stayed,
still saying "face down", naming a card now in its owner's hand. The record is
read by identity, so the next time that same object went to exile it was face
down again: discarded (Necropotence's whole hand comes from its own exile, and
cleanup discards it), Necropotence's other ability exiles it from the
graveyard **face up**, and every seat — its owner included — was shown a card
back (``web.player_view.exile_hidden_flags``).

W2G2 had added ``linked_exile.forget_exiler_entries`` to the one departure seam
(``Game.take_card_from_exile``) for Shared Fate's exiler entries alone; the
seam now forgets every entry naming the card that left
(``linked_exile.forget_linked_entries``). A linked ability that moves its own
cards drains its entries first, so it is untouched.

Round kg5's census (``scratch/kg5/layers/census_fd.py``) of every pool card
exiling face down onto a permanent's record: Knowledge Vault, Kyren Archive,
Duplicity, Gustha's Scepter, Scroll Rack, Parallel Thoughts and Mangara's Tome
drain their entries before moving a card; Memory Jar's record is on a
permanent its own cost sacrificed; Necropotence was the live road. Backwards on
the base (59f133e63) the Necropotence board and the seam census fail.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.exiler_grants import EXILER_KEY
from engine.linked_exile import (LEAVES, RECORD_KEY, face_down_exiled_cards,
                                 is_exiled_face_down, link_exiled_card,
                                 linked_entries)
from engine.models import Permanent
from tests.helpers import settle
from web.player_view import exile_hidden_flags

_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _necropotence_table():
    library = [_POOL["Lightning Bolt"]] + [_POOL["Swamp"]] * 9
    game = Game(players=[
        PlayerState("A", library=list(library)),
        PlayerState("B", library=[_POOL["Swamp"]] * 10),
    ])
    game.enforce_mana_costs = False
    necro = Permanent(card=_POOL["Necropotence"])
    game._put_permanent_onto_battlefield(0, necro, None)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, necro


def test_kg5_layers_necropotences_card_is_face_up_when_it_is_exiled_again():
    game, necro = _necropotence_table()
    bolt = game.players[0].library[0]
    assert game.activate_permanent_ability(0, "Necropotence").supported
    settle(game)
    assert [entry["card"] for entry in linked_entries(necro)] == [bolt]
    assert is_exiled_face_down(game, bolt)
    assert exile_hidden_flags(game, game.players[0], 1, 0) == [True]

    # The end step: the delayed ability puts it into its owner's hand.
    game.resolve_end_step(0)
    settle(game)
    assert any(card is bolt for card in game.players[0].hand)
    assert "A put 1 face-down card(s) into their hand from exile" in game.log
    assert linked_entries(necro) == ()

    # Discarded, it goes to the graveyard and Necropotence exiles it — face up.
    game._discard_card(game.players[0], bolt)
    settle(game)
    assert any(card is bolt for card in game.players[0].exile)
    assert "Lightning Bolt was exiled from A's graveyard (Necropotence)" in game.log
    assert not is_exiled_face_down(game, bolt)
    for viewer in (0, 1, None):
        assert face_down_exiled_cards(game, 0, viewer) == []
        assert exile_hidden_flags(game, game.players[0], viewer, 0) == [False]


#: Every key ``link_exiled_card`` can write, one entry each.
_ENTRY_SHAPES = {
    "plain": {},
    "face_down": {"face_down": True},
    "looked_at": {"face_down": True, "looker_index": 0},
    "exiler": {"face_down": True, "exiler_index": 1},
    "until_it_leaves": {"to": "battlefield", "ends_on": (LEAVES,)},
    "tapped_with_counters": {"tapped": True, "counters": {"+1/+1": 2}},
    "attach_to_returned": {"attach_to_returned": True},
}


@pytest.mark.parametrize("shape", sorted(_ENTRY_SHAPES))
def test_kg5_layers_the_departure_seam_forgets_every_entry_naming_its_card(shape):
    """The seam census: an entry of every shape, on a permanent on the
    battlefield and on one phased out (CR 702.26d: still the object it was),
    is gone once its card leaves exile — and an entry naming another card, or
    the same object in another seat's exile, stays."""
    game = Game(players=[PlayerState("A"), PlayerState("B")])
    holder = Permanent(card=_POOL["Kyren Archive"])
    asleep = Permanent(card=_POOL["Kyren Archive"])
    game._put_permanent_onto_battlefield(0, holder, None)
    game._sync_control()
    game.players[0].phased_out.append(asleep)
    leaving, staying = _POOL["Lightning Bolt"], _POOL["Giant Growth"]
    game.players[0].exile.extend([leaving, staying])
    game.players[1].exile.append(leaving)  # the same object, another owner
    for source in (holder, asleep):
        link_exiled_card(source, leaving, 0, **_ENTRY_SHAPES[shape])
        link_exiled_card(source, staying, 0, **_ENTRY_SHAPES[shape])
        link_exiled_card(source, leaving, 1, **_ENTRY_SHAPES[shape])
    assert (EXILER_KEY in linked_entries(holder)[0]) == (shape == "exiler")

    assert game.take_card_from_exile(0, leaving)

    for source in (holder, asleep):
        named = [(entry["card"], entry["owner_index"]) for entry in linked_entries(source)]
        assert (leaving, 0) not in named, (shape, source is asleep)
        assert (staying, 0) in named and (leaving, 1) in named
    # Nothing is left to speak for the card that left.
    assert all(
        not (entry["card"] is leaving and entry["owner_index"] == 0)
        for source in (holder, asleep)
        for entry in source.metadata.get(RECORD_KEY) or ()
    )
