"""Stronghold lands.

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
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_board() -> tuple[Game, PlayerState, PlayerState]:
    one, two = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[one, two])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, one, two


def test_g4_volraths_stronghold_ability_compiles_to_an_instruction(set_pool):
    """"{1}{B}, {T}: Put target creature card from your graveyard on top of
    your library."

    The card reported ``supported`` on its mana ability alone while this line
    lowered to nothing — a hollow ability part, an unclaimed sentence and a
    "target" with no picker, all one finding. The lowering refused the bare
    quantifier on the reading that this handler moves a *list*; it moves one
    card because the list is one long, and whether the announcement may be
    empty is the gate's question rather than the handler's.
    """
    program = compile_card_oracle(set_pool("STH")["Volrath's Stronghold"])
    ability = program.activated_abilities[1]

    assert ability.supported
    assert ability.instruction is not None
    assert ability.instruction.kind == "put_graveyard_cards_on_library_top"
    assert ability.instruction.payload["targets"] == {
        "quantifier": "target", "kind": "card", "count": 1,
    }
    assert ability.instruction.payload["graveyard_owner"] == "you"


@pytest.mark.cr("602.2b")
def test_g4_volraths_stronghold_offers_only_your_own_creature_cards(set_pool):
    """"from **your** graveyard": the picker is scoped to one pile, so the
    opponent's creature cards are never offered — and the handler indexes that
    same pile, so picker and payment cannot come to mean different graveyards.
    """
    game, caster, victim = _g4_board()
    caster.battlefield.append(
        Permanent(card=set_pool("STH")["Volrath's Stronghold"])
    )
    caster.graveyard = [
        _G4_LEA["Black Lotus"], _G4_LEA["Hurloon Minotaur"], _G4_LEA["Forest"],
    ]
    victim.graveyard = [_G4_LEA["Grizzly Bears"]]

    spec = game.activation_target_spec(0, 0, 1)
    assert spec["own_graveyard_only"] is True
    assert [t["name"] for t in spec["valid_targets"]] == ["Hurloon Minotaur"]

    result = game.activate_permanent_ability(
        0, "Volrath's Stronghold", ability_index=1, target_permanent_index=[1],
    )
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [c.name for c in caster.library] == ["Hurloon Minotaur"]
    assert [c.name for c in caster.graveyard] == ["Black Lotus", "Forest"]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("602.2b", "601.2c")
def test_g4_volraths_stronghold_with_no_creature_card_pays_nothing(set_pool):
    """A mandatory object target the board cannot fill refuses the activation
    before any cost is paid — the land is still untapped afterwards, which is
    the whole difference between "target" and "up to one"."""
    game, caster, _ = _g4_board()
    stronghold = Permanent(card=set_pool("STH")["Volrath's Stronghold"])
    caster.battlefield.append(stronghold)
    caster.graveyard = [_G4_LEA["Black Lotus"]]

    result = game.activate_permanent_ability(
        0, "Volrath's Stronghold", ability_index=1,
    )

    assert not result.supported
    assert not stronghold.tapped, "nothing was paid"
    assert [c.name for c in caster.graveyard] == ["Black Lotus"]
