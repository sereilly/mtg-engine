"""Regression: "a card with the same name as target creature" reads the
target's **effective** name.

``handlers/zones._search_restrictions`` turned the chosen target into the
search's ``named`` restriction off ``chosen.card.name`` — the printed face. CR
707.2 lists the name first among the copiable values, so a Clone copying Serra
Angel *is named* Serra Angel, and Mask of the Mimic aimed at it searched the
library for "Clone" instead. The read is an assignment rather than a
comparison, so ``tests/engine/test_printed_name_reads.py``'s syntactic census
could not see it; Nemesis's Pack Hunt ("up to three cards with the same name as
target creature") shares the path and found it.

Validated backwards: on the tree before the fix this test reads ``'Clone'``.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_STH = {c.name: c for c in load_cards(manifest_set_path("STH"))}


def test_mask_of_the_mimic_searches_for_a_clones_copied_name():
    caster = PlayerState(
        name="Mimic",
        hand=[_STH["Mask of the Mimic"]],
        library=[_LEA["Clone"], _LEA["Serra Angel"]],
    )
    victim = PlayerState(name="Victim")
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._put_permanent_onto_battlefield(1, Permanent(card=_LEA["Serra Angel"]), None)
    clone = Permanent(card=_LEA["Clone"])
    game._put_permanent_onto_battlefield(1, clone, None)
    game.auto_resolve_pending_choices()
    assert clone.effective_card.name == "Serra Angel", "the Clone copied the Angel"
    # The additional cost's fodder, entered after the Clone so it was never a
    # candidate for the copy.
    game._put_permanent_onto_battlefield(
        0, Permanent(card=_LEA["Mons's Goblin Raiders"]), None
    )

    result = game.cast_from_hand(
        0, "Mask of the Mimic", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(clone),
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    search = game.pending_choice_of("search_library", 0)
    assert search.data["restrictions"]["named"] == "Serra Angel"
    assert not game.confirm_search_library(0, 0), "a card named Clone is not the name"
    assert game.confirm_search_library(0, 1)
    game._settle()
    assert "Serra Angel" in [p.card.name for p in game.controlled_by(0)]
