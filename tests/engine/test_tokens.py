"""Tests for the generic create_token instruction and engine/tokens.py."""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.tokens import make_token_card
from tests.helpers import CARDS_BY_NAME, _mk_card


def test_make_token_card_defaults():
    token = make_token_card("Rukh", 4, 4, "Creature — Bird", colors=("R",), keywords=("Flying",))
    assert token.name == "Rukh"
    assert token.type_line == "Creature — Bird"
    assert token.colors == ("R",)
    assert token.keywords == ("Flying",)
    assert token.oracle_text == "Flying"
    assert token.raw["power"] == "4" and token.raw["toughness"] == "4"


def test_the_hive_compiles_to_generic_create_token():
    program = compile_card_oracle(CARDS_BY_NAME["The Hive"])
    kinds = [
        ab.instruction.kind
        for ab in program.activated_abilities
        if ab.instruction is not None
    ]
    assert "create_token" in kinds
    instr = next(
        ab.instruction for ab in program.activated_abilities
        if ab.instruction is not None and ab.instruction.kind == "create_token"
    )
    assert instr.payload["name"] == "Wasp"
    assert instr.payload["power"] == 1 and instr.payload["toughness"] == 1


def test_hive_wasp_enters_as_token_with_flying():
    hive = Permanent(card=CARDS_BY_NAME["The Hive"])
    p1 = PlayerState(name="P1", battlefield=[hive])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "The Hive", target_player_index=1)

    wasp = next(p for p in p1.battlefield if p.card.name == "Wasp")
    assert wasp.metadata.get("is_token") is True
    assert "Flying" in wasp.card.keywords


def test_dead_token_ceases_to_exist_not_graveyard():
    # CR 704.5d: a token that dies is removed from the game, never a graveyard
    # card. (Historically Wasps wrongly went to the graveyard because the
    # bespoke handler forgot the is_token stamp.)
    token = make_token_card("Wasp", 1, 1, "Artifact Creature — Insect", keywords=("Flying",))
    perm = Permanent(card=token, metadata={"is_token": True})
    p1 = PlayerState(name="P1", battlefield=[perm])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    p1.battlefield.remove(perm)
    game._permanent_to_graveyard(p1, perm)

    assert all(c.name != "Wasp" for c in p1.graveyard)
    assert all(c.name != "Wasp" for c in p1.exile)
