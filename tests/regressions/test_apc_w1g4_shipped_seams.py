"""Shipped behaviour Apocalypse's library-and-hand group moved on the way to its
own cards — three seams, each with the shipped card that shows it.

None of these is an Apocalypse card. They are here because each changed under a
card that was already in the pool, and a change to a shipped card's game that
no test of its own notices is how a set's work rots the sets before it.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _sorcery(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{U}", cmc=1.0, type_line="Sorcery",
        oracle_text=text, colors=("U",), color_identity=("U",), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Sorcery"},
    )


def _duel(lea, *, hand0=(), lib0=(), lib1=(), mine=(), interactive=()):
    board = [Permanent(card=card) for card in mine]
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand0), battlefield=board,
                    library=[lea[name] for name in lib0]),
        PlayerState(name="P1", library=[lea[name] for name in lib1]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    return game


# -- the targeted look reads its printed number ------------------------------


def test_a_targeted_look_rearranges_the_number_of_cards_it_prints(set_pool):
    """``reorder_target_library_top`` read a literal 3 where its payload carried
    the printed number. Natural Selection and Portent both print three, so no
    game played differently — and an invented card printing two is now asked
    about two, where it was asked about three."""
    lea = set_pool("LEA")
    library = ["Forest", "Island", "Swamp", "Plains"]
    two = _sorcery(
        "Narrow Glance",
        "Look at the top two cards of target player's library, then put them "
        "back in any order.",
    )
    game = _duel(lea, hand0=[two], lib1=library, interactive=(0,))
    assert game.queue_from_hand(0, "Narrow Glance", target_player_index=1).supported
    game.resolve_top_of_stack()

    prompt = game.pending_reorder_library
    assert (prompt["target_index"], prompt["top_count"]) == (1, 2)
    assert not game.confirm_reorder_library(0, [2, 1, 0]), "three is not the look"
    assert game.confirm_reorder_library(0, [1, 0])
    resolve_stack(game)
    assert [card.name for card in game.players[1].library] == [
        "Island", "Forest", "Swamp", "Plains",
    ]


def test_natural_selection_still_looks_at_three(set_pool):
    lea = set_pool("LEA")
    library = ["Forest", "Island", "Swamp", "Plains"]
    game = _duel(lea, hand0=[lea["Natural Selection"]], lib1=library, interactive=(0,))
    assert game.queue_from_hand(0, "Natural Selection", target_player_index=1).supported
    game.resolve_top_of_stack()

    prompt = game.pending_reorder_library
    assert (prompt["target_index"], prompt["top_count"], prompt["may_shuffle"]) == (1, 3, True)
    assert game.confirm_reorder_library(0, [2, 0, 1])
    resolve_stack(game)
    assert [card.name for card in game.players[1].library] == [
        "Swamp", "Forest", "Island", "Plains",
    ]


# -- a spell a replacement sent elsewhere is not logged into a graveyard -----


def test_a_spell_exiled_by_forbidden_crypt_is_not_logged_as_reaching_a_graveyard(set_pool):
    """``_bin_spell_card`` announced "…and moved to graveyard" whatever the
    graveyard seam answered. Under Forbidden Crypt ("If a card would be put
    into your graveyard from anywhere, exile that card instead") the resolved
    spell is exiled, the seam says so, and the line that follows no longer
    contradicts it."""
    lea = set_pool("LEA")
    crypt = set_pool("MIR")["Forbidden Crypt"]
    game = _duel(lea, hand0=[lea["Healing Salve"]], mine=[crypt])
    assert game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported
    resolve_stack(game)

    assert [card.name for card in game.players[0].exile] == ["Healing Salve"]
    assert game.players[0].graveyard == []
    assert "Healing Salve resolved" in game.log
    assert not any(
        "Healing Salve" in line and "moved to graveyard" in line for line in game.log
    )
    assert any(
        "Healing Salve was exiled instead of going to P0's graveyard" in line
        for line in game.log
    )


def test_a_spell_with_nothing_in_its_way_is_still_logged_into_the_graveyard(set_pool):
    lea = set_pool("LEA")
    game = _duel(lea, hand0=[lea["Healing Salve"]])
    assert game.cast_from_hand(0, "Healing Salve", target_player_index=0).supported
    resolve_stack(game)

    assert [card.name for card in game.players[0].graveyard] == ["Healing Salve"]
    assert "Healing Salve resolved and moved to graveyard" in game.log


# -- a counted search names the seat that searched ---------------------------


def test_a_counted_search_of_another_library_is_logged_under_its_searcher(set_pool):
    """Jester's Cap: "Search target player's library for three cards and exile
    them." The counted path logged the *zone's owner* as the searcher ("P1
    searched library and found…" for a search P0 made), which the single-find
    path had stopped doing at Bribery."""
    lea = set_pool("LEA")
    cap = Permanent(card=set_pool("ICE")["Jester's Cap"])
    cap.metadata["summoning_sickness_turn"] = -99
    library = ["Forest", "Island", "Swamp", "Plains", "Mountain"]
    game = Game(players=[
        PlayerState(name="P0", battlefield=[cap]),
        PlayerState(name="P1", library=[lea[name] for name in library]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.queue_permanent_ability(
        0, "Jester's Cap", ability_index=0, target_player_index=1
    ).supported
    game.resolve_top_of_stack()
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": index} for index in (0, 2, 4)]
    )
    resolve_stack(game)

    assert sorted(card.name for card in game.players[1].exile) == [
        "Forest", "Mountain", "Swamp",
    ]
    assert "P0 searched P1's library and found Forest, Swamp, Mountain" in game.log
    assert not any(line.startswith("P1 searched") for line in game.log)
