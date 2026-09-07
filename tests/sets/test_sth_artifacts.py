"""Stronghold artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.cost_modifiers import (cost_modifier_claims_line,
                                   cost_modifier_reduction_sentences,
                                   cost_modifiers_for)
from engine.models import Permanent

_G4_ATQ = {c.name: c for c in load_cards(manifest_set_path("ATQ"))}
_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_G4_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG"))}


def _g4_board() -> tuple[Game, PlayerState, PlayerState]:
    """Mana enforcement **on**: this block is about what a cost costs, so a
    game that charges nothing would pass every assertion below."""
    one, two = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[one, two])
    game.active_player_index = 0
    game.enforce_mana_costs = True
    return game, one, two


@pytest.mark.cr("601.2f", "118.7a")
def test_g4_heartstone_reads_the_reduction_and_its_floor_as_one_clause(set_pool):
    """"Activated abilities of creatures cost {1} less to activate. This effect
    can't reduce the mana in that cost to less than one mana."

    Both sentences or neither. The floor is what stops a {1} ability becoming
    free, so a reader claiming only the first sentence would leave the second
    unclaimed while quietly implementing a cheaper card — the same pairing
    ``engine/auras.py`` makes for Power Artifact's identical rider.
    """
    text = set_pool("STH")["Heartstone"].oracle_text

    modifiers = cost_modifiers_for(text)
    assert len(modifiers) == 1
    assert modifiers[0].reduces is True
    assert modifiers[0].applies_to == "activate"
    assert modifiers[0].amount == 1
    assert modifiers[0].card_types == ("creature",)
    assert modifiers[0].floor == 1
    assert cost_modifier_claims_line(text)
    assert len(cost_modifier_reduction_sentences(text)) == 2


@pytest.mark.cr("601.2f")
def test_g4_heartstone_takes_one_generic_off_a_creature_s_ability(set_pool):
    """Clay Statue regenerates for {2}, and for {1} beside a Heartstone."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_ATQ["Clay Statue"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    caster.mana_pool["C"] = 2

    result = game.activate_permanent_ability(0, "Clay Statue", ability_index=0)

    assert result.supported, result.details
    assert caster.mana_pool["C"] == 1, "one mana left over"


@pytest.mark.cr("601.2f")
def test_g4_heartstone_cannot_make_an_ability_free(set_pool):
    """The printed floor, enforced rather than dropped: Carrion Ants pumps for
    {1}, and beside a Heartstone it still pumps for {1}. The failure a dropped
    rider makes is not a crash — it is an ability that works more often than
    the card allows.
    """
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_LEG["Carrion Ants"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))

    refused = game.activate_permanent_ability(0, "Carrion Ants", ability_index=0)
    assert not refused.supported, "an empty pool cannot pay the floor"

    caster.mana_pool["C"] = 1
    paid = game.activate_permanent_ability(0, "Carrion Ants", ability_index=0)
    assert paid.supported, paid.details
    assert caster.mana_pool["C"] == 0, "the floor was charged in full"


@pytest.mark.cr("601.2f")
def test_g4_heartstone_reads_the_printed_noun_and_not_every_permanent(set_pool):
    """"Activated abilities of **creatures**": an artifact that is not a
    creature pays what it prints. Basalt Monolith untaps for {3} beside a
    Heartstone, which is the narrowing the modifier carries as payload."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_LEA["Basalt Monolith"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    caster.mana_pool["C"] = 2

    refused = game.activate_permanent_ability(
        0, "Basalt Monolith", ability_index=1,
    )
    assert not refused.supported, "{3} is not reduced to {2}"

    caster.mana_pool["C"] = 3
    assert game.activate_permanent_ability(
        0, "Basalt Monolith", ability_index=1,
    ).supported


@pytest.mark.cr("601.2f")
def test_g4_heartstone_is_symmetrical(set_pool):
    """The sentence names no controller, so it cheapens an opponent's creature
    too — the scan covers every battlefield, which is what a cost modifier
    without a printed seat means."""
    game, caster, victim = _g4_board()
    victim.battlefield.append(Permanent(card=_G4_ATQ["Clay Statue"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    victim.mana_pool["C"] = 1

    result = game.activate_permanent_ability(1, "Clay Statue", ability_index=0)

    assert result.supported, result.details
    assert victim.mana_pool["C"] == 0
