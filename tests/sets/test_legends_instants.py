"""Per-card tests for Legends' instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _creature(name: str, colors: tuple[str, ...] = ("G",)) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )


# ---------------------------------------------------------------------------
# Colour change (round 3) — "One or more target creatures become <colour>
# until end of turn." CR 105.2, CR 613 layer 5.
# ---------------------------------------------------------------------------

_COLOR_SPELLS = {
    "Dwarven Song": "R",
    "Heaven's Gate": "W",
    "Sea Kings' Blessing": "U",
    "Sylvan Paradise": "G",
    "Touch of Darkness": "B",
}


@pytest.mark.parametrize("name,symbol", sorted(_COLOR_SPELLS.items()))
def test_the_colour_spells_compile_to_one_instruction(name, symbol, set_pool):
    """One sentence, five cards, one production — the colour is payload."""
    program = compile_card_oracle(set_pool("LEG")[name])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["recolor_targets_until_eot"]
    assert program.instructions[0].payload["target_color"] == symbol


def test_touch_of_darkness_recolours_every_creature_it_names(set_pool):
    """"One or more target creatures" — several, not one. A lowering that
    dropped the count would recolour the first and report itself supported."""
    spell = set_pool("LEG")["Touch of Darkness"]
    first = Permanent(card=_creature("First"))
    second = Permanent(card=_creature("Second"))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[first, second])
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(
        0, "Touch of Darkness", target_player_index=0, target_permanent_index=[0, 1]
    )
    game._settle()

    assert result.supported
    assert first.effective_colors == {"B"}
    assert second.effective_colors == {"B"}


def test_the_colour_change_wears_off_at_cleanup(set_pool):
    """"…until end of turn" is carried by its own metadata channel, so the
    cleanup sweep takes it and an indefinite lace beside it would survive."""
    spell = set_pool("LEG")["Sylvan Paradise"]
    bear = Permanent(card=_creature("Bear", colors=("R",)))
    p1 = PlayerState(name="P1", hand=[spell], battlefield=[bear])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Sylvan Paradise", target_player_index=0, target_permanent_index=[0])
    game._settle()
    assert bear.effective_colors == {"G"}

    game.resolve_cleanup_step(0)
    assert bear.effective_colors == {"R"}


def test_a_permanent_lace_outlives_a_turn_long_colour_change(set_pool):
    """The reason for two channels rather than one. Chaoslace's change is
    indefinite (CR 105 and the Lace cycle print no duration); Dwarven Song's
    ends with the turn. Sharing a key would make cleanup drop both."""
    laced = Permanent(card=_creature("Laced", colors=("G",)))
    laced.metadata["color_override"] = "R"
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Heaven's Gate"]], battlefield=[laced])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.cast_from_hand(0, "Heaven's Gate", target_player_index=0, target_permanent_index=[0])
    game._settle()
    assert laced.effective_colors == {"W"}, "the newer change wins while it lasts"

    game.resolve_cleanup_step(0)
    assert laced.effective_colors == {"R"}, "the indefinite lace is still there"
