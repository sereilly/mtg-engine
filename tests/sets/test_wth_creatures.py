"""Weatherlight creatures.

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
    """One permanent on P1's battlefield and nothing else in the way.

    Built here rather than through a fixture because the point of every test in
    this block is the *upkeep step*, and a shared deck would leave which cards
    are on the board to the shuffle.
    """
    perm = Permanent(card=card)
    p1 = PlayerState(
        name="P1", battlefield=[perm], life=life,
        library=[library_card for _ in range(library)] if library_card else [],
    )
    p2 = PlayerState(name="P2", life=life)
    return Game(players=[p1, p2]), p1, perm


def test_aboroth_pays_its_upkeep_in_minus_counters_and_shrinks_to_death(set_pool):
    """"Cumulative upkeep—Put a -1/-1 counter on this creature."

    CR 702.24a's cost is paid **once per age counter**, so the 9/9 loses one
    point on its first upkeep, two more on its second and three more on its
    third — and the fourth kills it. A cost that scaled the payload instead of
    the repetition would put a single counter down every turn and leave an
    8/8 standing forever.
    """
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])
    assert (perm.effective_power, perm.effective_toughness) == (9, 9)

    seen = []
    for _ in range(4):
        game.resolve_upkeep(0)
        seen.append((counters_on(perm, "age"), perm.effective_power))
        if perm not in p1.battlefield:
            break

    assert seen == [(1, 8), (2, 6), (3, 3), (4, -1)]
    assert perm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Aboroth"]


def test_aboroths_upkeep_prompt_quotes_the_act_and_its_repetition(set_pool):
    """The offer is made before the trigger resolves, so the counter it is
    about to place is already in the quoted cost — the same rule the mana
    spelling follows, and the reason a player is not shown one cost and
    charged another."""
    game, p1, perm = _w1g3_solo_game(set_pool("WTH")["Aboroth"])

    first = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert first["cost_label"] == "put a -1/-1 counter on this creature"

    game.resolve_upkeep(0)
    second = next(c for c in game.get_upkeep_pay_triggers(0) if c["card_name"] == "Aboroth")
    assert second["cost_label"] == "put a -1/-1 counter on this creature 2 times"


def test_aboroth_compiles_its_keyword_into_one_upkeep_trigger(set_pool):
    """The keyword line is the *only* line on the card, so before this round it
    was refused outright and Aboroth was unsupported — not a permanent with a
    free upkeep, which is the direction a widened gate would have gone."""
    program = compile_card_oracle(set_pool("WTH")["Aboroth"])

    assert program.supported
    assert [
        (trig.condition.kind, trig.instruction.kind)
        for trig in program.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]
