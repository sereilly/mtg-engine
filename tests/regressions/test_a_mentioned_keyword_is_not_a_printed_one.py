"""Regression: a keyword a card *mentions* is not a keyword the card *has*.

Ten shipped creatures carried an ability they do not print, because the seed of
CR 613 layer 6 searched every static line for keyword words
(``layer_bridge._printed_abilities``). The sweep that holds the pool is
``tests/engine/test_printed_keyword_seed.py``; this file is the same ten cards
in a game, because a seed is only wrong where something reads it:

* **combat** -- a Gliding Licid could not be blocked by a creature on the
  ground, a Corrupting Licid by a green one, and a Quickening Licid killed its
  blocker before it struck back;
* **summoning sickness** -- an Enraging Licid had haste, so its own
  ``{R}, {T}`` ability could be activated the turn it arrived;
* **destruction** -- Guardian Beast survived Wrath of God, indestructible on
  the strength of a sentence about the artifacts beside it;
* **the wire** -- ``web/serialization._effective_keywords`` badges what layer 6
  holds, so the client showed each of these.

Nothing here is new behaviour for the *host*: a Licid that has become an Aura
still gives its creature the keyword, through ``engine/auras.py`` -- the reader
that knows whose keyword it is.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack
from web.serialization import _effective_keywords


def _w2g5_duel(catalog_by_name, mine, theirs=(), *, hand=()):
    library = [catalog_by_name["Forest"]] * 10
    p1 = PlayerState(name="P1", battlefield=list(mine), library=list(library))
    p2 = PlayerState(
        name="P2", battlefield=list(theirs), library=list(library), hand=list(hand),
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _w2g5_attack_into(catalog_by_name, attacker_name, blocker_name):
    """*attacker_name* attacks alone and *blocker_name* blocks it, through the
    turn structure's own steps; returns the game after combat damage."""
    attacker = _nosick(Permanent(card=catalog_by_name[attacker_name]))
    blocker = Permanent(card=catalog_by_name[blocker_name])
    game, _p1, _p2 = _w2g5_duel(catalog_by_name, [attacker], [blocker])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    declared = game.declare_blockers(1, {0: 0})
    game.advance_combat_phase()
    game.check_state_based_actions()
    return game, attacker, blocker, declared


def test_w2g5_gliding_licid_is_blocked_on_the_ground(catalog_by_name):
    """"Enchanted creature has flying" -- and an unattached Licid is a 2/2 a
    Grizzly Bears blocks and trades with."""
    game, licid, bears, declared = _w2g5_attack_into(
        catalog_by_name, "Gliding Licid", "Grizzly Bears"
    )
    assert declared[0], declared
    assert not game.is_on_battlefield(licid) and not game.is_on_battlefield(bears)


def test_w2g5_corrupting_licid_is_blocked_by_a_green_creature(catalog_by_name):
    """Fear (CR 702.36b) would have refused the nonblack, nonartifact Bears."""
    game, licid, _bears, declared = _w2g5_attack_into(
        catalog_by_name, "Corrupting Licid", "Grizzly Bears"
    )
    assert declared[0], declared
    assert not game._has_keyword(licid, "fear")


def test_w2g5_quickening_licid_trades_with_its_blocker(catalog_by_name):
    """A 1/1 with first strike kills a 1/1 and lives; a 1/1 without trades."""
    game, licid, raiders, declared = _w2g5_attack_into(
        catalog_by_name, "Quickening Licid", "Mons's Goblin Raiders"
    )
    assert declared[0], declared
    assert not game.is_on_battlefield(raiders)
    assert not game.is_on_battlefield(licid), "it dealt its damage in the same step"


def test_w2g5_enraging_licid_is_summoning_sick_the_turn_it_arrives(catalog_by_name):
    """Haste belongs to the creature it enchants. The Licid's own ability costs
    {T}, so CR 302.6 keeps it from being activated -- or from attacking -- on
    the turn it comes under its controller's control."""
    licid = Permanent(card=catalog_by_name["Enraging Licid"])
    host = _nosick(Permanent(card=catalog_by_name["Grizzly Bears"]))
    game, p1, _p2 = _w2g5_duel(catalog_by_name, [host])
    game.start_turn(0)
    game._put_permanent_onto_battlefield(0, licid, None)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        0, "Enraging Licid", ability_index=0,
        target_permanent_ids=[host.permanent_id],
    )

    assert not result.supported and "summoning sickness" in result.details
    assert not game.can_attack(licid, 1)
    assert licid.is_creature and not licid.tapped
    assert not game._has_keyword(host, "haste")


def test_w2g5_gliding_licid_gives_flying_to_its_host_and_never_has_it(catalog_by_name):
    """The grant is the Aura reader's, before and after the fix: the host flies
    while the Licid is attached, and the Licid flies at no point."""
    licid = _nosick(Permanent(card=catalog_by_name["Gliding Licid"]))
    host = _nosick(Permanent(card=catalog_by_name["Grizzly Bears"]))
    blocker = Permanent(card=catalog_by_name["Grizzly Bears"])
    game, _p1, _p2 = _w2g5_duel(catalog_by_name, [licid, host], [blocker])
    game.active_player_index = 0
    game.priority_player_index = 0
    assert game._can_block_attacker(blocker, licid)
    assert _effective_keywords(licid, game) == []

    result = game.activate_permanent_ability(
        0, "Gliding Licid", ability_index=0,
        target_permanent_ids=[host.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert licid.metadata.get("attached_to") is host
    assert game._has_keyword(host, "flying")
    assert not game._can_block_attacker(blocker, host)
    assert "Flying" in _effective_keywords(host, game)
    assert not game._has_keyword(licid, "flying")
    assert "Flying" not in _effective_keywords(licid, game)


def test_w2g5_guardian_beast_is_destroyed_and_its_artifact_is_not(catalog_by_name):
    """"…they have indestructible" names the noncreature artifacts. Wrath of
    God destroys the Beast; Shatter, cast while the Beast is still untapped,
    does not destroy the Lotus."""
    beast = Permanent(card=catalog_by_name["Guardian Beast"])
    lotus = Permanent(card=catalog_by_name["Black Lotus"])
    game, p1, _p2 = _w2g5_duel(
        catalog_by_name, [beast, lotus],
        hand=[catalog_by_name["Shatter"], catalog_by_name["Wrath of God"]],
    )
    game.start_turn(1)
    assert _effective_keywords(beast, game) == []
    assert _effective_keywords(lotus, game) == ["Indestructible"]

    game.cast_from_hand(1, "Shatter", target_permanent_ids=[lotus.permanent_id])
    resolve_stack(game)
    assert game.is_on_battlefield(lotus)

    game.cast_from_hand(1, "Wrath of God")
    resolve_stack(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(beast)
    assert "Guardian Beast" in [card.name for card in p1.graveyard]


@pytest.mark.parametrize("name, mentioned, badges", [
    # "Creatures with islandwalk can be blocked as though they didn't have
    # islandwalk." -- the walk these three print is the one they switch off.
    ("Gosta Dirk", ("islandwalk",), ["First Strike"]),
    ("Lord Magnus", ("forestwalk", "plainswalk"), ["First Strike"]),
    ("Ur-Drago", ("swampwalk",), ["First Strike"]),
    # "You may cast Aura spells with enchant creature as though they had flash."
    ("Rootwater Shaman", ("flash",), []),
])
def test_w2g5_a_card_about_a_keyword_does_not_have_it(
    catalog_by_name, name, mentioned, badges
):
    permanent = Permanent(card=catalog_by_name[name])
    game, _p1, _p2 = _w2g5_duel(catalog_by_name, [])
    game._put_permanent_onto_battlefield(0, permanent, None)

    assert [word for word in mentioned if game._has_keyword(permanent, word)] == []
    assert _effective_keywords(permanent, game) == badges


@pytest.mark.parametrize("body, shape, badges", [
    (0, (3, 3), []),
    (1, (2, 2), ["Flying"]),
    (2, (1, 6), ["Defender"]),
])
def test_w2g5_primal_clay_has_the_keyword_of_the_body_it_chose(
    catalog_by_name, body, shape, badges
):
    """"…a 2/2 artifact creature with flying, or a 1/6 Wall artifact creature
    with defender". The seed held both words and the entry choice took them
    away again; with the seed empty the chosen body's grant is the only source,
    so each body has to be asked for by itself."""
    clay = Permanent(card=catalog_by_name["Primal Clay"])
    game, _p1, _p2 = _w2g5_duel(catalog_by_name, [])
    game._put_permanent_onto_battlefield(0, clay, None)
    game._apply_chosen_body(clay, clay.metadata["body_options"][body])

    assert (clay.effective_power, clay.effective_toughness) == shape
    assert _effective_keywords(clay, game) == badges
    assert game.can_attack(_nosick(clay), 1) is (body != 2)
