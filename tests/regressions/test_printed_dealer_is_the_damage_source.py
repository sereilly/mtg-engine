"""Regression: a damage sentence's printed subject is the damage's source.

"Destroy target artifact. **That artifact** deals damage equal to its mana
value to this creature." (Goblin Tinkerer, Mirage.) CR 120.7: the source of
damage is the object that dealt it — here the artifact, not the Goblin whose
ability said so. The lowering built ``deal_damage`` from the recipient and the
amount and never read the subject, so the Tinkerer burned *itself*: the number
was right and everything that asks **who dealt it** was wrong.

* a Tinkerer with protection from red took no damage (a red source, by
  mistake) where the card deals it colourless damage;
* a Tinkerer warded against artifact sources took the damage in full;
* an artifact creature with lifelink gained its controller nothing;
* and the log named the wrong object.

Nothing reported unsupported and no instrument could see it — the compiled
program was a well-formed ``deal_damage``. USG's wave fixed the general form
for a permanent's *own* ability (the dealer is the permanent, not the printed
card); this is the same rule for a dealer the sentence names by back-reference,
read from the record the destroy step froze about its victim (CR 608.2h).

The pool-wide half is ``tests/engine/test_damage_dealers.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent
from tests.helpers import _mk_card, _nosick, resolve_stack


def _w2g5_tinkerer_board(catalog_by_name, artifact_card, *, ward=None, beside=()):
    """A Goblin Tinkerer ready to activate, an opposing *artifact_card*, and
    optionally an Aura on the Tinkerer or extra permanents beside the artifact."""
    tinkerer = _nosick(Permanent(card=catalog_by_name["Goblin Tinkerer"]))
    artifact = Permanent(card=artifact_card)
    mine = [tinkerer]
    aura = Permanent(card=catalog_by_name[ward]) if ward else None
    if aura is not None:
        mine.append(aura)
    library = [catalog_by_name["Forest"]] * 10
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine, library=list(library)),
        PlayerState(name="P2", library=list(library)),
    ])
    game.enforce_mana_costs = False
    # Through the entry path rather than the constructor: a permanent that
    # leaves is controlled, as a damage source, by the seat it *entered* under
    # (``control.base_controller``), and a hand-built board records none.
    for entering in (artifact, *(Permanent(card=catalog_by_name[n]) for n in beside)):
        game._put_permanent_onto_battlefield(1, entering, None)
    if aura is not None:
        attach_aura(aura, tinkerer)
    game._sync_control()
    game._recompute_continuous_effects()
    game.active_player_index = 0
    game.priority_player_index = 0
    return game, tinkerer, artifact


def _w2g5_tinker(game, artifact):
    result = game.activate_permanent_ability(
        0, "Goblin Tinkerer", ability_index=0,
        target_permanent_ids=[artifact.permanent_id],
    )
    resolve_stack(game)
    assert result.supported, result.details
    return result


def test_w2g5_the_destroyed_artifact_deals_the_damage(catalog_by_name):
    game, tinkerer, ring = _w2g5_tinkerer_board(catalog_by_name, catalog_by_name["Sol Ring"])

    _w2g5_tinker(game, ring)

    assert not game.is_on_battlefield(ring)
    assert tinkerer.damage_marked == 1
    assert "Sol Ring dealt 1 damage to Goblin Tinkerer" in game.log
    assert "Goblin Tinkerer dealt 1 damage to Goblin Tinkerer" not in game.log


def test_w2g5_the_damage_is_the_artifacts_mana_value_and_can_kill(catalog_by_name):
    game, tinkerer, tome = _w2g5_tinkerer_board(
        catalog_by_name, catalog_by_name["Jayemdae Tome"]
    )

    _w2g5_tinker(game, tome)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(tinkerer), "4 damage to a 1/2"
    assert "Jayemdae Tome dealt 4 damage to Goblin Tinkerer" in game.log


def test_w2g5_protection_from_red_does_not_stop_an_artifacts_damage(catalog_by_name):
    """CR 702.16e prevents damage from sources *with the stated quality*. Sol
    Ring is colourless; the Tinkerer's own ability being red is beside the
    point, because the ability is not what deals the damage."""
    game, tinkerer, ring = _w2g5_tinkerer_board(
        catalog_by_name, catalog_by_name["Sol Ring"], ward="Red Ward"
    )

    _w2g5_tinker(game, ring)

    assert tinkerer.damage_marked == 1


def test_w2g5_a_ward_against_artifact_sources_prevents_it(catalog_by_name):
    """The same rule from the other side: "Prevent all damage that would be
    dealt to enchanted creature by artifact sources." (Artifact Ward.)"""
    game, tinkerer, ring = _w2g5_tinkerer_board(
        catalog_by_name, catalog_by_name["Sol Ring"], ward="Artifact Ward"
    )

    _w2g5_tinker(game, ring)

    assert not game.is_on_battlefield(ring)
    assert tinkerer.damage_marked == 0


def test_w2g5_an_artifact_that_survives_still_deals_the_damage(catalog_by_name):
    """The sentence names the object, not the outcome: an indestructible
    artifact (Guardian Beast beside it) is not destroyed and deals its mana
    value all the same — from the battlefield rather than from last known
    information."""
    game, tinkerer, ring = _w2g5_tinkerer_board(
        catalog_by_name, catalog_by_name["Sol Ring"], beside=("Guardian Beast",)
    )

    _w2g5_tinker(game, ring)

    assert game.is_on_battlefield(ring)
    assert tinkerer.damage_marked == 1
    assert "Sol Ring dealt 1 damage to Goblin Tinkerer" in game.log


def test_w2g5_the_dealers_lifelink_gains_its_controller_life(catalog_by_name):
    """CR 702.15b: "damage dealt by a source with lifelink causes that source's
    controller … to gain that much life." Both halves are the dealer's — the
    keyword and the seat — and both were the Tinkerer's until the dealer was
    read. On an invented artifact creature, so the test names no card for the
    quality it needs."""
    automaton = _mk_card(
        name="Probe Automaton", mana_cost="{3}", type_line="Artifact Creature - Construct",
        oracle_text="Lifelink", power=2, toughness=2,
    )
    automaton = type(automaton)(**{
        **{f: getattr(automaton, f) for f in automaton.__dataclass_fields__},
        "cmc": 3.0, "keywords": ("Lifelink",),
    })
    game, tinkerer, target = _w2g5_tinkerer_board(catalog_by_name, automaton)
    assert game._has_keyword(target, "lifelink")
    before = [player.life for player in game.players]

    _w2g5_tinker(game, target)

    assert tinkerer.damage_marked == 3
    assert [player.life for player in game.players] == [before[0], before[1] + 3]


@pytest.mark.parametrize("ward, expected", [(None, 1), ("Red Ward", 1), ("Artifact Ward", 0)])
def test_w2g5_the_three_boards_agree_about_one_source(catalog_by_name, ward, expected):
    """The matrix in one place. Before the dealer was read it came out
    ``1, 0, 1`` — right on the plain board, and backwards on both of the
    boards where the source matters."""
    game, tinkerer, ring = _w2g5_tinkerer_board(
        catalog_by_name, catalog_by_name["Sol Ring"], ward=ward
    )

    _w2g5_tinker(game, ring)

    assert tinkerer.damage_marked == expected
