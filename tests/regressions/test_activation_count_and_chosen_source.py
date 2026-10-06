"""Three things an activation's announcement was not held to (CR 602.2b sends
an activation through CR 601.2b–i, so each is the cast side's rule asked of an
ability):

* **the printed count** (CR 601.2c). "{T}: Untap **two** target lands" named
  one and untapped one; "{X}, {T}: Untap **X** target lands" at X = 2 named
  one. The cast side has counted since ``cast_target_count_refusal``; the
  activation gate held only the ceiling.
* **every role** of a several-target announcement. Naming none was accepted,
  paid for, and resolved with each role unfilled.
* **a chosen source is not a target** (CR 609.7a). "The next time an
  **artifact source of your choice** would deal damage to you…" derived an
  "any target" picker — both players and every creature, for a shield that
  answers only to artifacts.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.legality import activation_target_obligation
from engine.models import Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.shields import shields_on
from engine.stack_targets import chosen_targets
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _nosick, resolve_stack


def _table(catalog_by_name, mine=(), theirs=()):
    island = catalog_by_name["Island"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 8) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=catalog_by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_nosick(permanent))
        rows.append(row)
    return game, rows[0], rows[1]


# ---------------------------------------------------------------------------
# CR 601.2c's count
# ---------------------------------------------------------------------------


def test_two_target_lands_names_two(catalog_by_name):
    game, (elder, *forests), _ = _table(
        catalog_by_name, ["Argothian Elder", "Forest", "Forest", "Forest"],
    )
    for forest in forests:
        forest.tapped = True

    one = game.activate_permanent_ability(
        0, "Argothian Elder", target_permanent_ids=[forests[0].permanent_id],
    )
    none = game.activate_permanent_ability(0, "Argothian Elder")

    assert not one.supported and one.details == "Argothian Elder needs 2 targets, not 1"
    assert not none.supported and none.details == "Argothian Elder needs 2 targets, not 0"
    assert not elder.tapped and all(forest.tapped for forest in forests)
    assert game.stack == []

    two = game.activate_permanent_ability(
        0, "Argothian Elder",
        target_permanent_ids=[forests[0].permanent_id, forests[2].permanent_id],
    )
    resolve_stack(game)

    assert two.supported and elder.tapped
    assert [forest.tapped for forest in forests] == [False, True, False]


def test_x_target_lands_names_the_x_it_announced(catalog_by_name):
    """"{X}, {T}: Untap X target lands." (Candelabra of Tawnos.) CR 601.2b
    announces X and CR 601.2c then fixes the number of targets at it."""
    game, (candelabra, *forests), _ = _table(
        catalog_by_name, ["Candelabra of Tawnos", "Forest", "Forest", "Forest"],
    )
    for forest in forests:
        forest.tapped = True

    short = game.activate_permanent_ability(
        0, "Candelabra of Tawnos", x_value=2,
        target_permanent_ids=[forests[0].permanent_id],
    )

    assert not short.supported
    assert short.details == "Candelabra of Tawnos needs 2 targets, not 1"
    assert not candelabra.tapped and all(forest.tapped for forest in forests)

    exact = game.activate_permanent_ability(
        0, "Candelabra of Tawnos", x_value=2,
        target_permanent_ids=[forests[0].permanent_id, forests[1].permanent_id],
    )
    resolve_stack(game)

    assert exact.supported
    assert [forest.tapped for forest in forests] == [False, False, True]


def test_x_of_zero_names_nobody_and_is_still_an_activation(catalog_by_name):
    """An activation that announced no X announced zero, and "zero target
    lands" is a legal announcement of none."""
    game, (candelabra, forest), _ = _table(
        catalog_by_name, ["Candelabra of Tawnos", "Forest"],
    )
    forest.tapped = True

    result = game.activate_permanent_ability(0, "Candelabra of Tawnos")
    resolve_stack(game)

    assert result.supported and candelabra.tapped and forest.tapped


def test_no_counted_activation_is_accepted_naming_fewer(catalog, catalog_by_name):
    """Every activated ability in the pool printing an exact count, announced
    with one target too few on a board that has enough: refused, nothing
    paid. (Ten abilities; a floor, because the pool grows.)"""
    from engine.legality import exact_target_count
    from engine.targeting import activation_target_slot

    examined = 0
    accepted: list[str] = []
    for card, program in compiled_units(catalog):
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            slot = activation_target_slot(ability)
            if slot is None:
                continue
            required = exact_target_count(slot[0], slot[1], 2)
            if required is None or required < 2:
                continue
            game, (source, *_rest), _ = _table(
                catalog_by_name,
                [card.name, "Forest", "Forest", "Grizzly Bears", "Hill Giant"],
                ["Forest", "Forest", "Grizzly Bears", "Hill Giant"],
            )
            if not game.is_on_battlefield(source):
                continue
            offered = [
                entry for entry in game.activation_target_spec(
                    0, game.battlefield_index_of(source), ability_index=index,
                ).get("valid_targets") or []
                if entry.get("kind") == "permanent"
            ]
            if len(offered) < required:
                continue    # outside combat, say: nothing to name at all
            named = [
                game.permanent_at(game.players[entry["seat"]], entry["index"]).permanent_id
                for entry in offered[:required - 1]
            ]
            examined += 1
            was_tapped = source.tapped    # Runed Arch enters tapped
            result = game.queue_permanent_ability(
                0, card.name, permanent_index=game.battlefield_index_of(source),
                ability_index=index, x_value=2, target_permanent_ids=named,
            )
            if result.supported or source.tapped != was_tapped or game.stack:
                accepted.append(f"{card.name}[{index}]: {result.details}")

    assert examined >= 6, examined
    assert accepted == []


# ---------------------------------------------------------------------------
# Every role
# ---------------------------------------------------------------------------


def test_a_several_role_activation_naming_nothing_is_refused(catalog_by_name):
    """"{T}: Choose target artifact a player controls and target artifact card
    in that player's graveyard." (Goblin Welder.) Two targets, both owed."""
    game, (welder, ring), _ = _table(catalog_by_name, ["Goblin Welder", "Sol Ring"])
    game.players[0].graveyard.append(catalog_by_name["Ornithopter"])

    result = game.activate_permanent_ability(0, "Goblin Welder")

    assert not result.supported
    assert result.details == "Goblin Welder requires 2 targets"
    assert not welder.tapped and game.is_on_battlefield(ring) and game.stack == []


# ---------------------------------------------------------------------------
# CR 609.7a: a chosen source
# ---------------------------------------------------------------------------

_TYPE_CIRCLES = {
    "Circle of Protection: Artifacts": {"Sol Ring", "Ornithopter"},
    "Rune of Protection: Artifacts": {"Sol Ring", "Ornithopter"},
    "Rune of Protection: Lands": {"Forest"},
    "Circle of Protection: Shadow": {"Dauthi Slayer"},
}


@pytest.mark.parametrize("name", sorted(_TYPE_CIRCLES))
def test_a_source_of_your_choice_is_chosen_from_the_sources_the_shield_answers(
    catalog_by_name, name
):
    game, (circle, *_mine), _theirs = _table(
        catalog_by_name,
        [name, "Sol Ring", "Grizzly Bears", "Forest"],
        ["Ornithopter", "Hill Giant", "Dauthi Slayer"],
    )
    ability = usable_activated_abilities(compile_card_oracle(circle.card))[0]
    spec = game.activation_target_spec(0, 0, ability_index=0)

    # Not "any target": no player is offered, and nothing the shield could
    # never answer to.
    assert derive_activation_spec(ability).get("source_of_choice") is True
    assert spec["kind"] != "any"
    assert {entry["name"] for entry in spec["valid_targets"]} == _TYPE_CIRCLES[name]
    assert all(entry["kind"] == "permanent" for entry in spec["valid_targets"])
    # A source is chosen, not targeted: nothing is owed, and a bare
    # activation is the ability's whole announcement.
    assert activation_target_obligation(ability) is None

    result = game.queue_permanent_ability(0, name)

    assert result.supported, result.details
    assert chosen_targets(game, game.stack[-1]) == ()
    resolve_stack(game)
    assert len(shields_on(game.players[0])) == 1
    assert not shields_on(game.players[1])


def test_a_chosen_source_named_outside_its_description_is_refused(catalog_by_name):
    game, (circle, _ring, bears), _ = _table(
        catalog_by_name, ["Circle of Protection: Artifacts", "Sol Ring", "Grizzly Bears"],
    )

    refused = game.queue_permanent_ability(
        0, "Circle of Protection: Artifacts",
        target_permanent_ids=[bears.permanent_id],
    )

    assert not refused.supported
    assert refused.details == "no valid target for Circle of Protection: Artifacts"
    assert game.stack == [] and not shields_on(game.players[0])
