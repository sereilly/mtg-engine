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


# --- W1G1 (NEM): a token whose own quoted ability defines its P/T ---


def _w1g1_token_maker(quoted: str):
    from engine.models import CardDefinition

    return CardDefinition(
        name="Spore Engine", mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=(
            "This enchantment enters with three spore counters on it.\n"
            "Remove a spore counter from this enchantment: Create a green "
            f'Saproling creature token. It has "{quoted}"'
        ),
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Spore Engine", "type_line": "Enchantment"},
    )


def test_a_token_with_no_printed_pt_takes_it_from_its_own_whole_cda():
    """Saproling Burst's shape on an invented card: the token states no P/T,
    its quoted CR 604.3 ability defines both halves, and the card's own name
    inside the quote becomes the relation it names — the token's maker."""
    program = compile_card_oracle(_w1g1_token_maker(
        "This token's power and toughness are each equal to the number of "
        "spore counters on Spore Engine."
    ))

    [ability] = program.activated_abilities
    assert ability.instruction.kind == "create_token"
    assert (ability.instruction.payload["power"],
            ability.instruction.payload["toughness"]) == ("*", "*")
    assert ability.instruction.payload["oracle_text"].endswith(
        "spore counters on the permanent that created this token"
    )


def test_a_token_whose_quoted_ability_defines_only_one_half_is_refused():
    """"…power is equal to …" leaves a toughness nothing printed, so the token
    is not admitted with one invented — the ability stays unimplemented and the
    card says so."""
    program = compile_card_oracle(_w1g1_token_maker(
        "This token's power is equal to the number of spore counters on "
        "Spore Engine."
    ))

    assert all(
        ability.instruction is None or ability.instruction.kind != "create_token"
        for ability in program.activated_abilities
    )

# --- end W1G1 ---
