"""A **spell role** in a roles announcement, on the path no card prints yet.

Suffocating Blast ("Counter target spell and Suffocating Blast deals 3 damage
to target creature") is a *spell*, and its tests are in
``tests/sets/test_apc_instants.py``. The lowering that makes its two targets
roles is asked of every printed line, though — an activated ability printing
the same sentence gets the same description — and the activation path fills a
roles announcement through its own reader (``legality.named_role_objects``).
A path the lowering can reach and nothing drives is how a supported card comes
to do nothing, so it is driven here on an invented card: the bar SET_PLAYBOOK
sets for a general mechanism is that a card printing the words works.

Also here: the narrowed spell role (a counter keeps what narrows its spell on
its own payload, so the role has to be stamped with the picker's flags), whose
only printing is likewise hypothetical.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec, spec_roles
from tests.helpers import _mk_card, resolve_stack

_DJINN = _mk_card(
    "Stifling Djinn", "{2}{U}{R}", "Creature — Djinn",
    "{T}: Counter target spell and Stifling Djinn deals 1 damage to target creature.",
    power=2, toughness=2,
)

_CREATURE_BLAST = _mk_card(
    "Smothering Blast", "{1}{U}{U}{R}", "Instant",
    "Counter target creature spell and Smothering Blast deals 3 damage to "
    "target creature.",
)


def _table(catalog_by_name, *, spell="Lightning Bolt"):
    """Seat 0 controls the Djinn; seat 1 a Grizzly Bears and *spell* on the
    stack."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    djinn = Permanent(card=_DJINN)
    djinn.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(djinn)
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game.players[1].battlefield.append(bears)
    game._sync_control()
    game.players[1].hand = [catalog_by_name[spell]]
    announcement = {"target_player_index": 0} if spell == "Lightning Bolt" else {}
    assert game.queue_from_hand(1, spell, **announcement).supported
    return game, djinn, bears


def test_an_ability_printing_the_sentence_announces_the_same_two_roles():
    (ability,) = compile_card_oracle(_DJINN).activated_abilities

    roles = spec_roles(derive_activation_spec(ability))

    assert [(role["role"], role["kind"]) for role in roles] == [
        ("spell", "stack"), ("creature", "creature"),
    ]


@pytest.mark.parametrize("spelling", ["ids", "refs"])
def test_the_activation_fills_its_spell_role_from_the_stack_channel(
    catalog_by_name, spelling
):
    """Both spellings of the announcement — the positional id list with a hole
    where the spell is, and one ref per role — name the spell on the one stack
    channel an activation has, and both halves happen."""
    game, djinn, bears = _table(catalog_by_name)
    announcement = (
        {"target_permanent_ids": [None, bears.permanent_id]}
        if spelling == "ids"
        else {"target_role_refs": [{"stack": True}, {"permanent_id": bears.permanent_id}]}
    )

    result = game.queue_permanent_ability(
        0, "Stifling Djinn", permanent_index=0, target_stack_index=0, **announcement
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert game.players[0].life == 20
    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]
    assert bears.damage_marked == 1
    assert "Lightning Bolt was countered by Stifling Djinn and moved to graveyard" in game.log


@pytest.mark.parametrize(
    "why, announcement",
    [
        ("nothing named", {}),
        ("the spell alone", {"target_stack_index": 0}),
        ("the creature alone", {"target_permanent_ids": [None, "bears"]}),
        ("the Djinn's own slot shifted", {"target_stack_index": 0, "target_permanent_ids": ["bears"]}),
    ],
)
def test_half_an_announcement_is_refused_before_the_cost(
    catalog_by_name, why, announcement
):
    game, djinn, bears = _table(catalog_by_name)
    named = dict(announcement)
    if "target_permanent_ids" in named:
        named["target_permanent_ids"] = [
            bears.permanent_id if entry == "bears" else entry
            for entry in named["target_permanent_ids"]
        ]

    result = game.queue_permanent_ability(0, "Stifling Djinn", permanent_index=0, **named)

    assert not result.supported, why
    assert not djinn.tapped, why
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]


def test_a_narrowed_spell_role_offers_and_admits_only_the_spells_it_names(
    catalog_by_name,
):
    """"Counter target **creature** spell and … deals 3 damage to target
    creature." The counter's narrowing lives on its payload, so the role
    carries the picker's own flag — and the walk, which enumerates a role from
    its description alone, offers the creature spell and not the instant."""
    program = compile_card_oracle(_CREATURE_BLAST)
    assert program.supported
    roles = spec_roles(derive_cast_spec(_CREATURE_BLAST, program))
    assert roles[0] == {
        "kind": "stack", "stack_card_types": ["creature"], "role": "spell",
    }

    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    target = Permanent(card=catalog_by_name["Hill Giant"])
    game.players[1].battlefield.append(target)
    game._sync_control()
    game.players[1].hand = [
        catalog_by_name["Lightning Bolt"], catalog_by_name["Grizzly Bears"],
    ]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    game.players[0].hand = [_CREATURE_BLAST]

    offered = game.cast_target_spec(0, _CREATURE_BLAST)["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]

    at_the_bolt = game.queue_from_hand(
        0, "Smothering Blast", target_stack_index=0,
        target_permanent_ids=[None, target.permanent_id],
    )
    assert not at_the_bolt.supported
    assert game.queue_from_hand(
        0, "Smothering Blast", target_stack_index=1,
        target_permanent_ids=[None, target.permanent_id],
    ).supported
    assert game.resolve_top_of_stack()
    assert target.damage_marked == 3
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
