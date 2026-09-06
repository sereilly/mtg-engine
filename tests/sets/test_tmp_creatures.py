"""Tempest creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: the Slivers — a quoted activated ability granted to a tribe ---
# CR 113.3: what a card grants in quotes is a whole printed ability, not a
# keyword. Five Tempest Slivers print the shape and the engine's one reader of a
# printed ability is the compiler, so the grant rides as *text* on the derived
# layer-6 channel (`engine/keywords.py`'s DERIVED_ABILITY_LINES) and
# `Permanent.effective_card` folds it in. Everything downstream — the cost
# parser, the target picker, `activation_restrictions.py` — then reads it
# without knowing a lord granted it.
#
# The three things the grant must not lose, one test each: the cost, the
# self-reference, and Mindwhip Sliver's "Activate only as a sorcery."
import pytest

from engine import Game, PlayerState
from engine.keywords import derived_ability_lines
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W1G3_SLIVERS = (
    "Armor Sliver",
    "Barbed Sliver",
    "Clot Sliver",
    "Mnemonic Sliver",
    "Mindwhip Sliver",
)


def _w1g3_board(set_pool, names, *, enforce_mana=False):
    """*names* on seat 0's battlefield, none summoning sick, layers recomputed."""
    pool = set_pool("TMP")
    seats = [PlayerState(name="A"), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = enforce_mana
    for name in names:
        perm = Permanent(card=pool[name])
        perm.metadata["summoning_sickness_turn"] = -99
        seats[0].battlefield.append(perm)
    game._recompute_continuous_effects()
    return game, seats


@pytest.mark.parametrize("name", _W1G3_SLIVERS)
def test_w1g3_every_sliver_lord_compiles_its_grant(set_pool, name):
    program = compile_card_oracle(set_pool("TMP")[name])
    assert program.supported, program.reason
    granted = [
        instruction.payload.get("granted_ability")
        for instruction in program.instructions
        if instruction.kind == "lord_buff"
    ]
    assert granted and granted[0], program.instructions


def test_w1g3_the_grant_reaches_every_sliver_and_leaves_with_the_lord(set_pool):
    """CR 611.3a/611.3b — derived, so the lord leaving takes it back."""
    game, seats = _w1g3_board(set_pool, ["Clot Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert derived_ability_lines(mate) == ("{2}: regenerate this permanent.",)
    # "All Slivers" names no "other", so the lord reaches itself too.
    assert derived_ability_lines(lord) == ("{2}: regenerate this permanent.",)

    game.remove_from_battlefield(lord)
    game._recompute_continuous_effects()
    assert derived_ability_lines(mate) == ()
    assert "regenerate" not in mate.effective_card.oracle_text.lower()


def test_w1g3_the_grant_does_not_reach_a_non_sliver(set_pool, cards):
    game, seats = _w1g3_board(set_pool, ["Clot Sliver"])
    bear = Permanent(card=cards["Grizzly Bears"])
    seats[0].battlefield.append(bear)
    game._recompute_continuous_effects()
    assert derived_ability_lines(bear) == ()


def test_w1g3_this_creature_inside_the_quotes_is_the_holder(set_pool):
    """The self-reference names the permanent that *has* the granted ability,
    never the Sliver granting it. Armor Sliver is 2/2 and Metallic Sliver 1/1,
    so the +0/+1 landing on the wrong one is visible in the numbers."""
    game, seats = _w1g3_board(set_pool, ["Armor Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert (mate.effective_power, mate.effective_toughness) == (1, 1)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    game._recompute_continuous_effects()
    assert (mate.effective_power, mate.effective_toughness) == (1, 2)
    assert (lord.effective_power, lord.effective_toughness) == (2, 2)


def test_w1g3_the_granted_mana_cost_is_charged(set_pool):
    """{2}, with no mana available. The dict this replaced was keyed on the
    whole quoted text *including* the cost, and the reader charged {B} in
    words — so a differently-costed printing was unsupported rather than
    charged."""
    game, seats = _w1g3_board(
        set_pool, ["Armor Sliver", "Metallic Sliver"], enforce_mana=True
    )
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    assert not result.supported
    assert "insufficient mana" in result.details


def test_w1g3_the_granted_sacrifice_cost_is_charged(set_pool):
    """Mnemonic Sliver grants "{2}, Sacrifice this permanent: Draw a card." —
    the sacrifice is a cost, so the holder leaves the battlefield paying it."""
    game, seats = _w1g3_board(set_pool, ["Mnemonic Sliver", "Metallic Sliver"])
    seats[0].library.extend([set_pool("TMP")["Metallic Sliver"]] * 3)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    assert [p.card.name for p in seats[0].battlefield] == ["Mnemonic Sliver"]
    assert len(seats[0].hand) == 1


def test_w1g3_mindwhip_sorcery_restriction_is_enforced(set_pool):
    """CR 602.5d. A parsed-and-dropped restriction is an ability that works
    more often than the card allows — wrong in the player's favour, and
    silent. `engine/activation_restrictions.py` reads the granted line's own
    text, so the rider travels with the grant."""
    game, seats = _w1g3_board(set_pool, ["Mindwhip Sliver", "Metallic Sliver"])
    game.active_player_index = 1
    game.current_phase = "precombat_main"
    refused = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    assert not refused.supported
    assert "sorcery-speed" in refused.details

    game.active_player_index = 0
    seats[1].hand.append(set_pool("TMP")["Metallic Sliver"])
    allowed = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert allowed.supported, allowed
    assert seats[1].hand == []
