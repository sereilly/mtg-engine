from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _mk_card(
    name: str,
    mana_cost: str,
    type_line: str,
    oracle_text: str,
    produced_mana: tuple[str, ...] = (),
):
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=produced_mana,
        raw={"name": name, "type_line": type_line},
    )


def test_strict_mana_blocks_unpaid_cast():
    spell = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )

    p1 = PlayerState(name="P1", hand=[spell])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Bolt Test", target_player_index=1)

    assert not result.supported
    assert "insufficient mana" in result.details
    assert len(p1.hand) == 1
    assert p2.life == 20


def test_strict_mana_allows_cast_after_tapping_land():
    spell = _mk_card(
        name="Bolt Test",
        mana_cost="{R}",
        type_line="Instant",
        oracle_text="Bolt Test deals 3 damage to any target.",
    )
    mountain = _mk_card(
        name="Mountain",
        mana_cost="",
        type_line="Basic Land - Mountain",
        oracle_text="{T}: Add {R}.",
        produced_mana=("R",),
    )

    p1 = PlayerState(name="P1", hand=[spell], battlefield=[Permanent(card=mountain)])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Mountain")
    result = game.cast_from_hand(0, "Bolt Test", target_player_index=1)

    assert result.supported
    assert p2.life == 17
    assert p1.mana_pool["R"] == 0


def test_tapping_basic_land_without_produced_mana_uses_land_type():
    swamp = _mk_card(
        name="Swamp",
        mana_cost="",
        type_line="Basic Land - Swamp",
        oracle_text="({T}: Add {B}.)",
    )

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=swamp)])
    game = Game(players=[p1], enforce_mana_costs=True)

    assert game.tap_land_for_mana(0, "Swamp")
    assert p1.mana_pool["B"] == 1
