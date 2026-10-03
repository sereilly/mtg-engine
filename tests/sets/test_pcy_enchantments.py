"""Prophecy enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_revel_table(set_pool, *, active):
    """Endbringer's Revel on seat 0; a creature card and an instant card in
    each graveyard; *active* in its main phase. W1G5's own."""
    lea = set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A", graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    them = _W1G5PlayerState(
        name="W1G5-B", graveyard=[lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=set_pool("PCY")["Endbringer's Revel"]), None,
    )
    game.active_player_index = active
    game.current_turn_phase = "precombat_main"
    return game, me, them


def _w1g5_revel(game, activator, *, seat, index):
    return game.activate_permanent_ability(
        activator, "Endbringer's Revel", ability_index=0,
        source_controller_index=0, target_player_index=seat,
        target_permanent_index=index,
    )


def test_w1g5_endbringers_revel_returns_to_the_owners_hand(set_pool):
    """"{4}: Return target creature card from a graveyard to its owner's hand."

    The picker offers the creature cards of **both** graveyards and no instant.
    The Revel's controller reaching into the opponent's pile hands the Hill
    Giant back to the *opponent* — its owner (CR 404.1, 400.3) — not to the
    activator.
    """
    game, me, them = _w1g5_revel_table(set_pool, active=0)
    spec = game.activation_target_spec(0, 0, 0)
    assert spec["kind"] == "graveyard_creature"
    assert sorted((t["seat"], t["name"]) for t in spec["valid_targets"]) == [
        (0, "Grizzly Bears"), (1, "Hill Giant"),
    ]

    assert _w1g5_revel(game, 0, seat=1, index=1).supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in them.hand] == ["Hill Giant"]
    assert me.hand == []
    assert [c.name for c in them.graveyard] == ["Lightning Bolt"]

    assert not _w1g5_revel(game, 0, seat=0, index=1).supported, "an instant card"


def test_w1g5_endbringers_revel_any_player_at_sorcery_speed(set_pool):
    """"Any player may activate this ability but only as a sorcery."

    The opponent activates it on their own main phase, pays the {4} from
    **their** pool, and gets their own creature card back; outside a main
    phase, or on the Revel controller's turn, the same activation is refused
    with nothing paid.
    """
    game, me, them = _w1g5_revel_table(set_pool, active=1)
    game.enforce_mana_costs = True
    them.mana_pool["B"] = 4

    game.current_turn_phase = "beginning_of_combat"
    assert not _w1g5_revel(game, 1, seat=1, index=1).supported
    assert them.mana_pool["B"] == 4, "a refused activation pays nothing"

    game.current_turn_phase = "precombat_main"
    assert _w1g5_revel(game, 1, seat=1, index=1).supported
    assert them.mana_pool["B"] == 0 and me.mana_pool["B"] == 0
    _w1g5_resolve_stack(game)
    assert [c.name for c in them.hand] == ["Hill Giant"]

    game, _me, them = _w1g5_revel_table(set_pool, active=0)
    assert not _w1g5_revel(game, 1, seat=1, index=1).supported, "not their turn"
    assert them.hand == []


def _w1g5_enchantment_in_play(set_pool, name, *, hand=(), mine=20, theirs=20):
    """Seat 0 casts *name* in its main phase with *hand* beside it; libraries
    of Plains/Islands to draw from. W1G5's own."""
    lea = set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A", hand=[set_pool("PCY")[name], *(lea[n] for n in hand)],
        library=[lea["Plains"]] * 20,
    )
    them = _W1G5PlayerState(name="W1G5-B", library=[lea["Island"]] * 20)
    me.life, them.life = mine, theirs
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.turn = 3
    assert game.cast_from_hand(0, name).supported
    _w1g5_resolve_stack(game)
    return game, me, them


def _w1g5_whole_turn(game, seat):
    """*seat*'s beginning phase, with everything it triggered resolved."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not _w1g5_resolve_stack(game):
            break


def _w1g5_converge(set_pool, *, mine, theirs):
    from engine.named_counters import counters_on

    game, me, them = _w1g5_enchantment_in_play(
        set_pool, "Celestial Convergence", mine=mine, theirs=theirs,
    )
    (convergence,) = [
        p for p in game.controlled_by(0) if p.card.name == "Celestial Convergence"
    ]
    assert counters_on(convergence, "omen") == 7
    seen = []
    for _ in range(7):
        _w1g5_whole_turn(game, 1)
        _w1g5_whole_turn(game, 0)
        seen.append((counters_on(convergence, "omen"), me.lost, them.lost))
    return game, me, them, seen


def test_w1g5_celestial_convergence_seventh_upkeep_crowns_the_life_leader(set_pool):
    """"This enchantment enters with seven omen counters on it. / At the
    beginning of your upkeep, remove an omen counter from this enchantment. If
    there are no omen counters on this enchantment, the player with the highest
    life total wins the game."

    Seven of its controller's upkeeps, one counter each (the opponent's upkeeps
    remove none), and nothing happens until the last. Then the leader wins —
    whichever seat that is: the controller on 20 against 15, the *opponent* on
    15 against 12 (CR 104.2b names a player, not the enchantment's controller).
    """
    _game, me, them, seen = _w1g5_converge(set_pool, mine=20, theirs=15)
    assert [count for count, _a, _b in seen] == [6, 5, 4, 3, 2, 1, 0]
    assert all(not a and not b for _c, a, b in seen[:-1])
    assert (me.lost, them.lost) == (False, True)

    game, me, them, _seen = _w1g5_converge(set_pool, mine=12, theirs=15)
    assert (me.lost, them.lost) == (True, False)
    assert not game.is_draw


def test_w1g5_celestial_convergence_tie_on_the_last_counter_is_a_draw(set_pool):
    """"If two or more players are tied for highest life total, the game is a
    draw." — the tie arm of the win, not a sentence of its own: level on 20
    for six upkeeps with counters left, and the game goes on; level when the
    last counter comes off, and it is a draw (CR 104.4c) with nobody winning.
    """
    game, me, them, seen = _w1g5_converge(set_pool, mine=20, theirs=20)
    assert all(not a and not b for _c, a, b in seen[:-1]), "counters left: no draw"
    assert game.is_draw
    assert not any("wins the game" in line for line in game.log)


def test_w1g5_heightened_awareness_discards_hand_then_draws_extra(set_pool):
    """"As this enchantment enters, discard your hand. / At the beginning of
    your draw step, draw an additional card."

    The hand goes as it enters (CR 614.1c), through the discard seam — every
    card reaches the graveyard, Awareness itself is on the battlefield — and the
    controller's next draw step draws two.
    """
    game, me, _them = _w1g5_enchantment_in_play(
        set_pool, "Heightened Awareness",
        hand=("Island", "Lightning Bolt", "Grizzly Bears"),
    )
    assert me.hand == []
    assert sorted(c.name for c in me.graveyard) == [
        "Grizzly Bears", "Island", "Lightning Bolt",
    ]
    assert [p.card.name for p in game.controlled_by(0)] == ["Heightened Awareness"]

    _w1g5_whole_turn(game, 1)
    _w1g5_whole_turn(game, 0)
    assert [c.name for c in me.hand] == ["Plains", "Plains"]
# end of the W1G5 enchantments block
