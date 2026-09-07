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


@pytest.mark.cr("601.2f", "701.19a")
def test_g4_skeleton_scavengers_costs_one_mana_per_counter(set_pool):
    """"Pay {1} for each +1/+1 counter on this creature: Regenerate this
    creature. When it regenerates this way, put a +1/+1 counter on it."

    Only the *cost* was new. "When it regenerates this way" is Matopi Golem's
    delayed trigger and the regeneration is the ordinary shield — what nothing
    read was a mana payment written as prose, whose size is a board read rather
    than a printed number. Charged flat, the creature would regenerate for {1}
    however large it had grown.
    """
    game, caster, victim = _g4_board()
    victim.hand.append(_G4_LEA["Lightning Bolt"])
    game.enforce_mana_costs = True
    skeleton = Permanent(card=set_pool("STH")["Skeleton Scavengers"])
    game._put_permanent_onto_battlefield(0, skeleton, None)

    from engine.named_counters import counters_on

    assert counters_on(skeleton, "+1/+1") == 1, "it enters with one"

    caster.mana_pool["C"] = 1
    assert game.activate_permanent_ability(
        0, "Skeleton Scavengers", ability_index=0,
    ).supported
    game.resolve_top_of_stack()
    assert caster.mana_pool["C"] == 0, "one counter, one mana"
    assert skeleton.regeneration_shield == 1

    # The shield is spent, which is what "regenerates this way" watches for —
    # CR 701.19c is explicit that creating one is not regenerating.
    game.enforce_mana_costs = False
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=0,
    )
    game.resolve_top_of_stack()
    game._settle()
    assert any(perm is skeleton for perm in caster.battlefield), "it regenerated"
    assert skeleton.tapped
    assert counters_on(skeleton, "+1/+1") == 2

    # …and the second activation is priced off the board it now has.
    game.enforce_mana_costs = True
    caster.mana_pool["C"] = 1
    assert not game.activate_permanent_ability(
        0, "Skeleton Scavengers", ability_index=0,
    ).supported, "two counters is two mana"
    caster.mana_pool["C"] = 2
    assert game.activate_permanent_ability(
        0, "Skeleton Scavengers", ability_index=0,
    ).supported
    assert caster.mana_pool["C"] == 0


def test_g4_a_prose_mana_payment_with_no_rate_refuses_the_line():
    """The gate on the production above, written as its refusal.

    A bare "Pay {1}:" is the mana symbol spelled twice, and admitting it would
    make the grammar's reading and ``oracle.parse_activated_ability_cost``'s
    disagree: that reader charges a flat {1} for it, and this one would charge
    a rate over a counter nothing named. The positive case always passes; this
    is the one that finds the bug.
    """
    from engine.grammar.errors import GrammarError
    from engine.grammar.parser import parse_line

    with pytest.raises(GrammarError):
        parse_line("Pay {1}: Regenerate this creature.")
    with pytest.raises(GrammarError):
        parse_line(
            "Pay {1} for each +1/+1 counter on target creature: "
            "Regenerate this creature."
        )
