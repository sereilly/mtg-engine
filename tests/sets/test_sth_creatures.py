"""Stronghold creatures.

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

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_board() -> tuple[Game, PlayerState, PlayerState]:
    one, two = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[one, two])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, one, two


def test_g4_hermit_druid_stops_on_a_basic_land_and_bins_the_rest(set_pool):
    """"Reveal cards from the top of your library until you reveal a basic land
    card. Put that card into your hand and all other cards revealed this way
    into your graveyard."

    Sacred Guide's reveal-until with the rest's fate printed in the other word
    order — "and all other cards … *into your graveyard*" rather than "and
    *exile* all other cards …". One production reads both, because everything
    before that word is identical.
    """
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=set_pool("STH")["Hermit Druid"]))
    caster.library = [
        _G4_LEA[name] for name in
        ("Black Lotus", "Healing Salve", "Forest", "Mox Pearl")
    ]

    result = game.activate_permanent_ability(
        0, "Hermit Druid", ability_index=0,
    )
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [c.name for c in caster.hand] == ["Forest"]
    assert [c.name for c in caster.graveyard] == ["Black Lotus", "Healing Salve"]
    assert [c.name for c in caster.library] == ["Mox Pearl"], "the run stopped"


def test_g4_hermit_druid_reads_the_basic_supertype_not_the_land_type(set_pool):
    """"a **basic** land card". The supertype is the whole of what makes this
    card a combo piece rather than a land tutor — a run that stopped on the
    first land would stop on a nonbasic and leave the graveyard empty."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=set_pool("STH")["Hermit Druid"]))
    caster.library = [
        set_pool("STH")["Volrath's Stronghold"], _G4_LEA["Mountain"],
    ]

    game.activate_permanent_ability(0, "Hermit Druid", ability_index=0)
    game.resolve_top_of_stack()

    assert [c.name for c in caster.hand] == ["Mountain"]
    assert [c.name for c in caster.graveyard] == ["Volrath's Stronghold"]


def test_g4_hermit_druid_over_a_library_with_no_basic_mills_it_all(set_pool):
    """CR 701.20a's reveal is bounded by the library, so a run that never
    matches ends when the cards do — the whole library into the graveyard, and
    no loop."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=set_pool("STH")["Hermit Druid"]))
    caster.library = [_G4_LEA["Black Lotus"], _G4_LEA["Healing Salve"]]

    game.activate_permanent_ability(0, "Hermit Druid", ability_index=0)
    game.resolve_top_of_stack()

    assert caster.library == []
    assert caster.hand == []
    assert [c.name for c in caster.graveyard] == ["Black Lotus", "Healing Salve"]
