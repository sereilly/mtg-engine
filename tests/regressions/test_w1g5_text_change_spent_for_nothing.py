"""An AI seat does not cast a text change that would rewrite nothing (ONS W1G5).

``mark_text_modified`` marked its target (``metadata["text_modified"]``) as
soon as it found it, whatever the change then recorded, and the rehearsal reads
a permanent's fields as what a cast changed (``ai_rehearsal.position_digest``).
So a text change that rewrote nothing read as a change, and a seat with one in
hand cast it at its own Island with no words named — Magical Hack, Sleight of
Mind, Mind Bend, Whim of Volrath and Alter Reality, each a card spent for
nothing. Found when a seeded Onslaught run cast Artificial Evolution on turn
one at an Island. The mark is now written by the writer, with the record
(``text_changes._record``).

The census is every shipped spell whose only effect is a text change (Crystal
Spray also draws a card, and is a fair cast for that alone), on a board where
the only words in reach are the caster's own Islands' type lines and nothing
announces a word. Validated backwards: on the base this round started from,
every one of the five was proposed.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _only_a_text_change(card) -> bool:
    if card.primary_type not in ("instant", "sorcery"):
        return False
    kinds = {ins.kind for ins in compile_card_oracle(card).instructions}
    return "mark_text_modified" in kinds and kinds <= {
        "mark_text_modified", "derived_static_rule",
    }


@pytest.fixture(scope="module")
def shipped():
    return {card.name: card for card in load_catalog()}


def test_the_census_reaches_the_text_change_spells(shipped):
    found = sorted(name for name, card in shipped.items() if _only_a_text_change(card))
    assert len(found) >= 5, found
    assert {"Magical Hack", "Sleight of Mind", "Mind Bend"} <= set(found)


def test_no_text_change_spell_is_cast_to_rewrite_nothing(shipped):
    proposed = []
    for name, card in sorted(shipped.items()):
        if not _only_a_text_change(card):
            continue
        game = Game(players=[
            PlayerState(
                name="A", hand=[card],
                battlefield=[Permanent(card=shipped["Island"]) for _ in range(5)],
                library=[shipped["Island"]] * 8,
            ),
            PlayerState(
                name="B", battlefield=[Permanent(card=shipped["Grizzly Bears"])],
                library=[shipped["Island"]] * 8,
            ),
        ])
        game.interactive_seats = set()
        game.start_turn(0)
        game._sync_control()
        for permanent in game.all_permanents():
            permanent.metadata["summoning_sickness_turn"] = -99
        game.current_turn_phase = game.current_step = "precombat_main"
        action = choose_cast_action(game, 0)
        if action is not None and action.card_name == name:
            proposed.append(name)
    assert proposed == []
