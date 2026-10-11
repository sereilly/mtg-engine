"""What a seat nobody asks names for Brass Herald's creature type.

``ai_valuation.chosen_creature_type_side`` reads, off what a card does with
"the chosen type", whose creatures the type should name. Brass Herald prints
two readers that agree — an anthem (+1/+1, a gift) and a reveal that puts
cards of the type from its controller's **own library** into their hand. The
second is the row Apocalypse added: without it a card printing only that
sentence would take the opponents' most common type and turn its own text
into four cards milled to the bottom.

The sibling cases (Belbe's Portal, Urza's Incubator, An-Zerrin Ruins) are in
``test_ai_entry_choices.py``.
"""

from __future__ import annotations

from engine.ai_valuation import chosen_creature_type_side
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _mk_card, resolve_stack

_REVEAL = (
    "When this creature enters, reveal the top four cards of your library. "
    "Put all creature cards of the chosen type revealed this way into your "
    "hand and the rest on the bottom of your library in any order."
)


def _creature(name, subtype):
    return _mk_card(name=name, mana_cost="{1}", type_line=f"Creature — {subtype}")


def test_brass_herald_names_its_controller_s_type(set_pool):
    assert chosen_creature_type_side(set_pool("APC")["Brass Herald"]) == "you"


def test_an_invented_recruiter_of_the_chosen_type_names_its_controller_s_type():
    """The reveal alone, on a card that prints no anthem: the type worth
    naming is the one the controller's own deck holds, read off the compiled
    program and not off a name."""
    scout = _mk_card(
        name="Banner Scout", mana_cost="{3}", type_line="Artifact Creature — Scout",
        oracle_text=f"As this creature enters, choose a creature type.\n{_REVEAL}",
    )
    assert chosen_creature_type_side(scout) == "you"

    goblins = [_creature(f"Goblin {i}", "Goblin") for i in range(3)]
    elves = [Permanent(card=_creature(f"Elf {i}", "Elf")) for i in range(3)]
    game = Game(players=[
        PlayerState(name="AI", hand=[scout], library=goblins + [_mk_card("A Land", "Land")]),
        PlayerState(name="Opp", battlefield=elves),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    assert game.cast_from_hand(0, "Banner Scout").supported
    resolve_stack(game)

    permanent = next(p for p in game.controlled_by(0) if p.card.name == "Banner Scout")
    assert permanent.metadata.get("chosen_creature_type") == "goblin"
    assert [c.name for c in game.players[0].hand] == ["Goblin 0", "Goblin 1", "Goblin 2"]
    assert [c.name for c in game.players[0].library] == ["A Land"]
