"""Tempest enchantments (Auras included — the printed type is the axis).

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


# --- W1G1: shadow (CR 702.28) ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def test_w1g1_dauthi_embrace_grants_shadow_to_a_creature_in_a_game(set_pool):
    """"{B}{B}: Target creature gains shadow until end of turn."

    A repeatable grant, so the assertion is on the block it changes rather than
    on the instruction it compiles — and on *both* halves of CR 702.28b, because
    the creature it makes unblockable is thereby also unable to block. That
    second consequence is the one a player notices and the one an evasion-only
    reading would have got wrong.
    """
    tmp = set_pool("TMP")
    embrace = _nosick(Permanent(card=tmp["Dauthi Embrace"]))
    bear = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p0 = PlayerState(
        name="P0", battlefield=[embrace, bear], life=20, mana_pool={"B": 2}
    )
    blocker = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[blocker], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game._can_block_attacker(blocker, bear)

    game.activate_permanent_ability(
        0, "Dauthi Embrace", ability_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert game._has_keyword(bear, "shadow")
    assert not game._can_block_attacker(blocker, bear)
    assert not game._can_block_attacker(bear, blocker), (
        "CR 702.28b's second half: the creature it just made evasive can no "
        "longer block a creature without shadow"
    )


def test_w1g1_dauthi_embrace_may_target_an_opponents_creature(set_pool):
    """The ability says "target creature", not "target creature you control",
    and the drawback half of shadow is what makes that a *removal* of a blocker.

    Asserted because the picker is derived from the compiled program: a
    `type_filter` narrowed to the controller's own board would have made the
    card unable to do the thing it is most often played for, and the compiled
    payload is the only place that narrowing would show.
    """
    program = compile_card_oracle(set_pool("TMP")["Dauthi Embrace"])
    ability = program.activated_abilities[0]

    assert ability.instruction.kind == "grant_target_keyword_until_eot"
    assert ability.instruction.payload["keywords"] == ("shadow",)
    assert ability.instruction.payload["targets"]["filter"] == {
        "type_filter": "creature"
    }
