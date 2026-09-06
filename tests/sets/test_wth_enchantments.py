"""Weatherlight enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: cumulative upkeep beyond a mana cost ---
from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g3_solo_game(card, *, library=0, life=20, library_card=None):
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_psychic_vortex_draws_one_card_per_age_counter_each_upkeep(set_pool):
    """"Cumulative upkeep—Draw a card."

    The card was **supported before this round** — its end-step trigger claimed
    it — and its upkeep did nothing at all, which is the failure mode a support
    census cannot see. Three upkeeps draw one, then two, then three.
    """
    pool = set_pool("WTH")
    game, p1, perm = _w1g3_solo_game(
        pool["Psychic Vortex"], library=12, library_card=pool["Fog Elemental"]
    )

    drawn = []
    for _ in range(3):
        game.resolve_upkeep(0)
        drawn.append((counters_on(perm, "age"), len(p1.hand)))

    assert drawn == [(1, 1), (2, 3), (3, 6)]
    assert perm in p1.battlefield


def test_psychic_vortexs_upkeep_is_a_cumulative_upkeep_trigger(set_pool):
    program = compile_card_oracle(set_pool("WTH")["Psychic Vortex"])

    assert program.supported
    assert sorted(
        trig.instruction.kind for trig in program.triggered_abilities
        if trig.instruction is not None
    ) == ["cumulative_upkeep", "sequence"]
