"""Regression: "target **spell or permanent**" is one target in one of two
zones, on every card that prints it.

Found on Apocalypse's Illusion ("Target spell or permanent becomes the color
of your choice until end of turn"), and shipped a set earlier on Invasion's
**Blind Seer**, whose activated ability prints the same sentence. The noun
parser consumed the union and recorded nothing, so the phrase compiled as
"target permanent":

    Blind Seer, a Lightning Bolt on the stack, a Grizzly Bears beside it
      -> the picker offers Blind Seer and Grizzly Bears, never the Bolt;
         naming the Bolt is refused "no valid target".

The five Laces were never affected — their instruction kind carries a fixed
``spell_or_permanent`` picker — which is why the gap sat unseen behind a cycle
that worked. ``ObjectFilter.also_spell`` records the union now and each
lowering that meets it says what it does with the spell half.

Three shipped cards print the phrase for a **text** change (Sleight of Mind,
Magical Hack, Crystal Spray) and their spell half is still not built — a text
change needs a text channel on a stack object. They are held here to exactly
what they did before: a permanent picker, and a named spell refused at
announcement rather than accepted and dropped.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec
from tests.helpers import resolve_stack


def _duel(*, interactive=()):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _bolt(game, catalog_by_name):
    """Seat 1 puts a Lightning Bolt on the stack aimed at seat 0."""
    game.players[1].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game.stack[-1]


def test_blind_seer_derives_the_laces_picker(catalog_by_name):
    seer = catalog_by_name["Blind Seer"]
    (ability,) = compile_card_oracle(seer).activated_abilities

    assert derive_activation_spec(ability) == {"kind": "spell_or_permanent"}
    assert derive_cast_spec(
        catalog_by_name["Chaoslace"], compile_card_oracle(catalog_by_name["Chaoslace"])
    ) == {"kind": "spell_or_permanent"}


def test_blind_seer_recolours_the_spell_it_names(catalog_by_name):
    """The half that was unreachable: the Bolt is offered, named, and blue —
    to the picker of "counter target blue spell" as to everything else."""
    game = _duel(interactive=(0,))
    _put(game, 0, catalog_by_name["Blind Seer"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _bolt(game, catalog_by_name)

    offered = game.activation_target_spec(0, 0)
    assert offered["kind"] == "spell_or_permanent"
    assert sorted((entry["kind"], entry["name"]) for entry in offered["valid_targets"]) == [
        ("permanent", "Blind Seer"), ("permanent", "Grizzly Bears"),
        ("stack", "Lightning Bolt"),
    ]

    assert game.queue_permanent_ability(
        0, "Blind Seer", permanent_index=0, target_stack_index=0,
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="U")

    assert game._stack_item_colors(bolt) == ("U",)
    assert game._effective_colors(bears) == {"G"}
    assert "Lightning Bolt (on the stack) became U until end of turn (Blind Seer)" in game.log
    red_blast = catalog_by_name["Red Elemental Blast"]
    assert [
        entry["name"]
        for entry in game.cast_target_spec(0, red_blast, mode_index=0)["valid_targets"]
    ] == ["Lightning Bolt"]


def test_blind_seer_still_recolours_a_permanent_until_end_of_turn(catalog_by_name):
    game = _duel(interactive=(0,))
    _put(game, 0, catalog_by_name["Blind Seer"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Blind Seer", permanent_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="W")

    assert game._effective_colors(bears) == {"W"}
    game.resolve_cleanup_step(0)
    assert game._effective_colors(bears) == {"G"}


def test_blind_seer_names_a_spell_or_a_permanent_and_never_both(catalog_by_name):
    """One instance of the word "target": naming one of each is two answers to
    one question (CR 115.3), refused before the cost is paid."""
    game = _duel()
    seer = _put(game, 0, catalog_by_name["Blind Seer"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    _bolt(game, catalog_by_name)

    refused = game.queue_permanent_ability(
        0, "Blind Seer", permanent_index=0, target_stack_index=0,
        target_permanent_ids=[bears.permanent_id],
    )

    assert not refused.supported and "not one of each" in refused.details
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    assert not seer.tapped


def test_blind_seers_spell_that_has_left_is_not_swapped_for_a_permanent(catalog_by_name):
    """CR 608.2b: the named spell is gone, so nothing is recoloured — the scan
    that used to reach for a permanent is what recoloured a bystander."""
    game = _duel()
    _put(game, 0, catalog_by_name["Blind Seer"])
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _bolt(game, catalog_by_name)

    assert game.queue_permanent_ability(
        0, "Blind Seer", permanent_index=0, target_stack_index=0,
    ).supported
    game.counter_stack_object(bolt)
    resolve_stack(game)

    assert game._effective_colors(bears) == {"G"}
    assert "Blind Seer: no valid spell to recolour" in game.log
    assert not any("became" in line for line in game.log)


# --- The three text-changers: measured, and held where they were -----------


@pytest.mark.parametrize(
    "name", ["Crystal Spray", "Magical Hack", "Sleight of Mind"],
)
def test_a_text_change_still_offers_permanents_alone(catalog_by_name, name):
    """"Change the text of target spell or permanent…" The union is recorded
    and this lowering carries it without acting on the spell half, so the spec
    is the ``permanent`` one it always was — the spell half is declined, by
    name, in ``lowering/characteristics._lower_change_text``."""
    card = catalog_by_name[name]
    program = compile_card_oracle(card)

    assert program.supported
    assert derive_cast_spec(card, program) == {"kind": "permanent"}

    game = _duel()
    _put(game, 1, catalog_by_name["Grizzly Bears"])
    _bolt(game, catalog_by_name)
    offered = game.cast_target_spec(0, card)
    assert [(entry["kind"], entry["name"]) for entry in offered["valid_targets"]] == [
        ("permanent", "Grizzly Bears"),
    ]


@pytest.mark.parametrize(
    "name", ["Crystal Spray", "Magical Hack", "Sleight of Mind"],
)
def test_a_text_change_aimed_at_a_spell_is_refused_not_spent(catalog_by_name, name):
    """What the declined half looks like to a caller that names a spell
    anyway: the announcement is refused with the card in hand. It used to be
    accepted, the stack object recorded and ignored, and the card spent on a
    text change of nothing."""
    card = catalog_by_name[name]
    game = _duel()
    _put(game, 1, catalog_by_name["Grizzly Bears"])
    _bolt(game, catalog_by_name)
    game.players[0].hand = [card]

    refused = game.queue_from_hand(
        0, name, target_stack_index=0, new_color="U", old_color="R",
    )

    assert not refused.supported
    assert "targets nothing on the stack" in refused.details
    assert game.players[0].hand == [card]
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]


def test_unsubstantiate_keeps_its_own_union(catalog_by_name):
    """"Return target spell or creature to its owner's hand" reads its template
    whole and was never the noun parser's: both halves still work, and the
    one-of-each announcement is refused like the recolour's."""
    card = catalog_by_name["Unsubstantiate"]
    game = _duel()
    bears = _put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _bolt(game, catalog_by_name)
    game.players[0].hand = [card, card]

    both = game.queue_from_hand(
        0, "Unsubstantiate", target_stack_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not both.supported and "not one of each" in both.details

    assert game.queue_from_hand(0, "Unsubstantiate", target_stack_index=0).supported
    assert game.resolve_top_of_stack()
    assert not any(item is bolt for item in game.stack)
    assert [c.name for c in game.players[1].hand] == ["Lightning Bolt"]

    assert game.queue_from_hand(
        0, "Unsubstantiate", target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    assert game.players[1].battlefield == []
    assert sorted(c.name for c in game.players[1].hand) == [
        "Grizzly Bears", "Lightning Bolt",
    ]
