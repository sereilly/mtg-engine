"""A copy-as-enters permanent named its object by id alone copies that object.

"You may have this creature enter as a copy of any creature on the
battlefield" (Clone, Vesuvan Doppelganger) and "…as a copy of any artifact on
the battlefield" (Copy Artifact) are CR 707.5 replacements whose choice this
engine takes from the cast's announcement (``cast_targets``' copy picker).
``StackResolutionMixin._resolve_card`` recorded that choice for the entry
(``copy_target``, read by ``_resolve_copy_target``, which prefers the id) only
when the cast named a battlefield **slot**. A cast that named the object by
``target_permanent_ids`` alone — the identity CLAUDE.md asks every caller to
address a permanent by — recorded nothing, and the entry fell back to the
first creature or artifact on the board: a Clone aimed at a Brass Herald
entered as the Soul Warden beside it (found by
``test_kg3_entryfix_choice_then_trigger.py``'s copy road).

Every copy-as-enters card in the pool, derived from its text, cast at both
tables with a decoy of the right type first on the board and the named object
behind it. Backwards: on the tree before the fix every row copies the decoy.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.enter_effects import copy_on_enter_type
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_C = {card.name: card for card in load_catalog()}
#: What each copy type is offered, the decoy first.
_BOARD = {
    "creature": ("Soul Warden", "Grizzly Bears"),
    "artifact": ("Sol Ring", "Ornithopter"),
}


def _copiers() -> list:
    return sorted(
        {
            unit.name: unit for unit in compilation_units(_C.values())
            if compile_card_oracle(unit).supported
            and copy_on_enter_type(compile_card_oracle(unit).normalized_text or "")
        }.values(),
        key=lambda card: card.name,
    )


def _table(person: bool, kind: str) -> tuple[Game, Permanent]:
    game = Game(players=[
        PlayerState(name="P0", library=[_C["Plains"]] * 10),
        PlayerState(name="P1", library=[_C["Plains"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0} if person else set()
    game._sync_control()
    placed = []
    for name in _BOARD[kind]:
        permanent = Permanent(card=_C[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        resolve_stack(game)
        placed.append(permanent)
    return game, placed[-1]


@pytest.mark.parametrize("person", [False, True], ids=["nobody_asked", "a_person"])
def test_a_copy_named_by_id_alone_copies_what_it_named(person):
    copiers = _copiers()
    # Clone, Copy Artifact, Vesuvan Doppelganger (November 2026). A floor.
    assert len(copiers) >= 3, [card.name for card in copiers]
    wrong = []
    for card in copiers:
        kind = copy_on_enter_type(compile_card_oracle(card).normalized_text)
        game, named = _table(person, kind)
        game.players[0].hand = [card]
        result = game.queue_from_hand(0, card.name, target_permanent_ids=[named.permanent_id])
        assert result.supported, (card.name, result.details)
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        copies = [
            permanent.effective_card.name for permanent in game.controlled_by(0)
            if permanent.card is card
        ]
        if copies != [named.card.name]:
            wrong.append(f"{card.name}: named {named.card.name}, entered as {copies}")
    assert not wrong, wrong
