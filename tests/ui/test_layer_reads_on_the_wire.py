"""Every characteristic the wire sends is the layers' answer, not the card's.

``tests/engine/test_layer_reads.py`` guards the class this file is about —
"what type/colour/P/T is this?" asked of ``card.type_line`` or a metadata flag
instead of the CR 613 accessors — and it **scans ``engine/`` only**. So
``web/serialization.py`` has been outside it since it was written, and the two
defects that found their way out did so through a promotion smoke test rather
than through a guard:

* Tempest's, in ``_effective_keywords``, which asked ``perm.card.type_line``
  whether the permanent was a creature and so gave an animated land no
  keywords.
* Stronghold's, in ``is_aura``. A **Licid** activates "this creature loses this
  ability and becomes an Aura enchantment with enchant creature" — a CR 613
  layer-4 type change, which moves nothing on the card. Both
  ``perm.card.type_line`` and ``perm.effective_card.type_line`` still read
  "Creature — Licid" afterwards, because layer 1 folds a *copy* and layer 3 a
  *text change* and this is neither. The engine had it right at every seam it
  owns; the client alone was told the thing attached to its creature was not an
  Aura, and no engine instrument could see it.

This file is the wire-side answer: a driven game, the real serializer, and the
fields a player actually reads. It is not the widened scan — that is a round of
its own, recorded in SET_PLAYBOOK.md's Known gaps — but it pins the two sites
that have already cost something.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.layer_bridge import displayed_type_line
from engine.models import Permanent
from web.serialization import _serialize_permanent

from ..helpers import resolve_stack


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


def _attached_licid(pool):
    """A Gliding Licid mid-transformation, attached to a Grizzly Bears."""
    licid = Permanent(card=pool["Gliding Licid"])
    licid.metadata["summoning_sick"] = False
    host = Permanent(card=pool["Grizzly Bears"])
    host.metadata["summoning_sick"] = False
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=[licid, host]),
            PlayerState(name="P2"),
        ],
        enforce_mana_costs=False,
    )
    assert game.queue_permanent_ability(
        0, "Gliding Licid", ability_index=0,
        target_permanent_ids=[host.permanent_id],
    ).supported
    resolve_stack(game)
    return game, licid, host


def test_a_licid_that_became_an_aura_reaches_the_client_as_one(pool):
    """The defect, from the far side.

    Asserted against the *printed* type line as well, because that is what makes
    this a layer read rather than a spelling: the card still says "Creature —
    Licid" and the answer still has to be "Aura".
    """
    game, licid, host = _attached_licid(pool)

    assert "Licid" in licid.card.type_line          # the card has not moved
    assert not licid.is_creature                    # the layers have
    assert licid.has_type("enchantment")

    wire = _serialize_permanent(licid, game)
    assert wire["is_aura"] is True, wire
    assert wire["type"] == displayed_type_line(licid)
    assert wire["is_creature"] is False
    assert wire["attached_to_id"] == host.permanent_id


def test_the_licids_host_is_not_itself_reported_as_an_aura(pool):
    """The negative the positive needs: reading the layer-aware type line must
    not make every permanent in the attachment an Aura."""
    game, _licid, host = _attached_licid(pool)

    wire = _serialize_permanent(host, game)
    assert wire["is_aura"] is False, wire
    assert wire["is_creature"] is True


def test_an_ordinary_aura_and_an_ordinary_creature_are_unchanged(pool):
    """The direction this fix must never move: a printed Aura is still an Aura
    and a printed creature is still not one."""
    aura = Permanent(card=pool["Pacifism"])
    bears = Permanent(card=pool["Grizzly Bears"])
    game = Game(
        players=[PlayerState(name="P1", battlefield=[aura, bears]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )
    assert _serialize_permanent(aura, game)["is_aura"] is True
    assert _serialize_permanent(bears, game)["is_aura"] is False


def test_an_animated_land_keeps_its_keywords_on_the_wire(pool):
    """Tempest's site, kept here beside Stronghold's because they are one class.

    Stalking Stones becomes "a 3/3 Elemental creature that's still a land", so a
    reader asking the printed type line whether it is a creature answers no and
    drops every keyword it has.
    """
    stones = Permanent(card=pool["Stalking Stones"])
    stones.metadata["summoning_sick"] = False
    game = Game(
        players=[PlayerState(name="P1", battlefield=[stones]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )
    assert "Land" in stones.card.type_line
    wire = _serialize_permanent(stones, game)
    # Untouched it is not a creature, and that is the honest answer.
    assert wire["is_creature"] is False
    assert wire["is_aura"] is False


def test_protection_from_a_card_type_reaches_the_wire(pool):
    """Urza's Legacy's site, and the fourth of this class.

    Not a type-line read this time but its sibling: `_effective_keywords` asked
    `game._protection_colors`, which is the *deliberate colour slice* of
    `_protection_qualities` and was right for as long as every protection in the
    pool was from a colour. Urza's Legacy printed two from a **card type** and
    the wire went silent about both — Angelic Curator reached the client showing
    only "Flying", and Yavimaya Scion, whose entire printed text is "Protection
    from artifacts", reached it carrying **no badge at all** — while the engine
    had the shield right at every seam it owns.

    That is this class exactly: an accessor whose narrower sibling answers a
    strictly smaller question, read by the client because it was sufficient when
    it was written. Found by Phase 5's "read what the wire carries for one card
    of the set's new mechanic", which is the same step that found the other
    three.

    The badge says "artifact**s**" because the card does: `protection_quality`
    canonicalizes to the singular to match the catalogs it looks words up in.
    """
    curator = Permanent(card=pool["Angelic Curator"])
    scion = Permanent(card=pool["Yavimaya Scion"])
    knight = Permanent(card=pool["White Knight"])
    game = Game(
        players=[PlayerState(name="P1", battlefield=[curator, scion, knight]),
                 PlayerState(name="P2")],
        enforce_mana_costs=False,
    )

    curator_wire = _serialize_permanent(curator, game)["keywords"]
    assert "Protection from artifacts" in curator_wire
    assert "Flying" in curator_wire

    # The one whose whole text is the protection: a badge or nothing at all.
    assert _serialize_permanent(scion, game)["keywords"] == ["Protection from artifacts"]

    # And the colour half still spells out the way it always did.
    assert "Protection from black" in _serialize_permanent(knight, game)["keywords"]
