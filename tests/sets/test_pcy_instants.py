"""Prophecy instants.

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


def _w1g5_instant_table(set_pool, hand, *, mine=(), theirs=()):
    """Seat 0 to act in its main phase with *hand*; *mine*/*theirs* are card
    names put onto each battlefield, summoning sickness cleared. W1G5's own."""
    pool = {**set_pool("LEA"), **set_pool("PCY")}
    me = _W1G5PlayerState(name="W1G5-A", hand=[pool[n] for n in hand])
    them = _W1G5PlayerState(name="W1G5-B")
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            perm = _W1G5Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game, me, them


def _w1g5_on(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def test_w1g5_inflame_hits_only_creatures_dealt_damage_this_turn(set_pool):
    """"Inflame deals 2 damage to each creature dealt damage this turn."

    Prodigal Sorcerer pings Hill Giant for 1; Inflame then finishes it with 2
    and leaves the undamaged Grizzly Bears and the Sorcerer alone. The set is
    read off the per-turn damage record when Inflame resolves (CR 608.2), not
    off damage still marked — the Giant's 1 counts because it was *dealt*.
    """
    game, _me, them = _w1g5_instant_table(
        set_pool, ["Inflame"], mine=["Prodigal Sorcerer"],
        theirs=["Hill Giant", "Grizzly Bears"],
    )
    giant = _w1g5_on(game, 1, "Hill Giant")
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game.cast_from_hand(0, "Inflame").supported
    _w1g5_resolve_stack(game)

    assert [c.name for c in them.graveyard] == ["Hill Giant"]
    survivors = {p.card.name: p.damage_marked for p in game.all_permanents()}
    assert survivors == {"Prodigal Sorcerer": 0, "Grizzly Bears": 0}
    assert any("Inflame dealt 2 damage to Hill Giant" in line for line in game.log)


def test_w1g5_inflame_on_an_undamaged_board_does_nothing(set_pool):
    """No creature was dealt damage this turn, so the described set is empty
    and nothing is dealt — the reduced relative clause narrows, it is not
    dropped (a dropped clause would be a two-damage sweep)."""
    game, _me, _them = _w1g5_instant_table(
        set_pool, ["Inflame"], theirs=["Grizzly Bears", "Llanowar Elves"],
    )
    assert game.cast_from_hand(0, "Inflame").supported
    _w1g5_resolve_stack(game)
    assert sorted(p.card.name for p in game.all_permanents()) == [
        "Grizzly Bears", "Llanowar Elves",
    ]
    assert all(p.damage_marked == 0 for p in game.all_permanents())


def _w1g5_strike_combat(set_pool):
    """Seat 1 attacks seat 0 with Grizzly Bears and Hill Giant; seat 0's Wall
    of Stone blocks the Giant; stopped in the declare-blockers step with Mirror
    Strike in seat 0's hand. W1G5's own."""
    lea = set_pool("LEA")
    wall, bears, giant = (
        _W1G5Permanent(card=lea[n]) for n in ("Wall of Stone", "Grizzly Bears", "Hill Giant")
    )
    me = _W1G5PlayerState(
        name="W1G5-A", battlefield=[wall], hand=[set_pool("PCY")["Mirror Strike"]],
    )
    them = _W1G5PlayerState(name="W1G5-B", battlefield=[bears, giant])
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    for perm in (wall, bears, giant):
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {0: 1})[0]
    assert game.current_step == "declare_blockers"
    return game, me, them, bears, giant


def _w1g5_to_postcombat(game):
    for _ in range(6):
        if game.current_turn_phase == "postcombat_main":
            return
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)


def test_w1g5_mirror_strike_turns_an_unblocked_attacker_on_its_controller(set_pool):
    """"All combat damage that would be dealt to you this turn by target
    unblocked creature is dealt to its controller instead."

    CR 614.9: the Bears' 2 combat damage to the caster is dealt to the Bears'
    controller instead — still dealt by the Bears, in full. The picker offers
    only the unblocked attacker: the blocked Giant and the caster's own Wall are
    not "unblocked creatures" (CR 509.1h), and the announcement gate refuses
    them.
    """
    card = set_pool("PCY")["Mirror Strike"]
    game, me, them, bears, giant = _w1g5_strike_combat(set_pool)
    spec = game.cast_target_spec(0, card)
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]
    assert not game.cast_from_hand(
        0, "Mirror Strike", target_player_index=1,
        target_permanent_ids=[giant.permanent_id],
    ).supported

    assert game.cast_from_hand(
        0, "Mirror Strike", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_to_postcombat(game)

    assert (me.life, them.life) == (20, 18)
    assert any("dealt to W1G5-B instead (Mirror Strike)" in line for line in game.log)


def test_w1g5_mirror_strike_leaves_other_attackers_alone(set_pool):
    """Only the named creature's damage moves: with the Wall not blocking, the
    Giant's 3 still reach the caster while the Bears' 2 go back."""
    lea = set_pool("LEA")
    wall, bears, giant = (
        _W1G5Permanent(card=lea[n]) for n in ("Wall of Stone", "Grizzly Bears", "Hill Giant")
    )
    me = _W1G5PlayerState(
        name="W1G5-A", battlefield=[wall], hand=[set_pool("PCY")["Mirror Strike"]],
    )
    them = _W1G5PlayerState(name="W1G5-B", battlefield=[bears, giant])
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    for perm in (wall, bears, giant):
        perm.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]
    assert game.cast_from_hand(
        0, "Mirror Strike", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    _w1g5_to_postcombat(game)
    assert (me.life, them.life) == (17, 18)
# end of the W1G5 instants block
