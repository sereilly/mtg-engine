"""A card exiled face down is not named in the log (CR 406.3, CR 400.2).

``game.log`` is one list and every seat and spectator is sent it, so a line in
it is an announcement (``Game.find_is_public``'s rule for a find). Scourge's
Parallel Thoughts exiles seven cards "in a face-down pile" and hands them back
one per replaced draw; driving it found the engine naming each card three
times over — as the search exiled it, and as the pile's top went to a hand —
on every card that makes such a pile (Mangara's Tome, shipped) and on every
face-down exile off the top of a library (Necropotence, Knowledge Vault,
Duplicity, Kyren Archive, Three Wishes). The rulings say it of Parallel
Thoughts in as many words: "You can't look at the face down cards"
(2004-10-04).

Validated backwards on the tree before the fix: each test below read the
card's name in the log.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.linked_exile import linked_entries
from engine.models import Permanent
from tests.helpers import resolve_stack

_SECRET = "Shivan Dragon"


def _card(code: str, name: str):
    return next(
        c for c in load_cards(manifest_set_path(code, include_measured=True))
        if c.name == name
    )


def _game(*, mine=(), hand=(), library=()) -> Game:
    battlefield = []
    for card in mine:
        permanent = Permanent(card=card)
        permanent.metadata["summoning_sickness_turn"] = -99
        battlefield.append(permanent)
    me = PlayerState(
        name="P0", battlefield=battlefield, hand=list(hand), library=list(library),
    )
    game = Game(players=[me, PlayerState(name="P1", library=list(library))])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _named_in_log(game, name: str) -> list[str]:
    return [line for line in game.log if name in line]


def _library():
    return [_card("2ED", _SECRET)] * 9


def test_a_face_down_pile_search_and_its_return_name_no_card():
    for code, name in (("SCG", "Parallel Thoughts"), ("MIR", "Mangara's Tome")):
        enchantment = _card(code, name)
        game = _game(hand=[enchantment], library=_library())
        assert game.queue_from_hand(0, name).supported
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        source = next(p for p in game.controlled_by(0) if p.card.name == name)
        assert linked_entries(source), name
        # Back out of the pile the way each card prints it: Parallel Thoughts
        # on a draw, Mangara's Tome through the handler its ability arms.
        if name == "Parallel Thoughts":
            game._draw_with_replacements(game.players[0], 1)
        else:
            from engine.game_types import OracleExecutionContext
            from engine.oracle_types import OracleInstruction

            game._execute_oracle_instruction(
                OracleInstruction("put_exiled_pile_top_into_hand", "", {}),
                OracleExecutionContext(
                    caster=game.players[0], target=game.players[0],
                    card=enchantment, source_permanent=source,
                ),
            )
        assert game.players[0].hand == [_card("2ED", _SECRET)], name
        assert _named_in_log(game, _SECRET) == [], (name, _named_in_log(game, _SECRET))
        assert any("card(s) face down" in line for line in game.log), name
        assert any(
            "the top card goes from the exiled pile" in line for line in game.log
        ), name


def test_necropotence_exiles_the_top_card_without_naming_it():
    necropotence = _card("5ED", "Necropotence")
    game = _game(mine=[necropotence], library=_library())
    result = game.activate_permanent_ability(0, "Necropotence")
    assert result.supported, result.details
    resolve_stack(game)
    assert len(game.players[0].exile) == 1
    assert _named_in_log(game, _SECRET) == []
    assert any(
        "exiled 1 card(s) face down from the top of their library" in line
        for line in game.log
    )
