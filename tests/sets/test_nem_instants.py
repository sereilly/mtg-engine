"""Nemesis instants.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: combat restrictions and triggers ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _w1g3_body(name: str, power: int, toughness: int, *,
               text: str = "", keywords: tuple = ()) -> CardDefinition:
    """An invented creature to point these two instants at."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_duel(mine, theirs, *, hand_of_1=()):
    """Seat 0 holds *mine*, seat 1 holds *theirs* and *hand_of_1*; turn 0 open."""
    attackers = [m if isinstance(m, Permanent) else Permanent(card=m) for m in mine]
    defenders = [t if isinstance(t, Permanent) else Permanent(card=t) for t in theirs]
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(attackers)),
        PlayerState(name="P1", battlefield=list(defenders), hand=list(hand_of_1)),
    ])
    game.enforce_mana_costs = False
    for permanent in (*attackers, *defenders):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, attackers, defenders


def _w1g3_walk_combat_to(game, step: str) -> None:
    """Advance the combat phase, draining the stack, until *step* is current."""
    for _ in range(8):
        if game.current_step == step:
            return
        game.advance_combat_phase()
        resolve_stack(game)
    assert game.current_step == step, f"stuck at {game.current_step}"


# --- Off Balance -----------------------------------------------------------
# "Target creature can't attack or block this turn." One subject, two
# one-shot restrictions, each answered at its own step (CR 508.1c, 509.1b).


def test_w1g3_off_balance_stops_its_target_attacking(set_pool):
    game, (bear, other), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2), _w1g3_body("Other", 2, 2)], [],
        hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    result = game.cast_from_hand(
        1, "Off Balance", target_permanent_ids=[bear.permanent_id]
    )
    resolve_stack(game)
    assert result.supported, result.details
    game.advance_combat_phase()
    game.advance_combat_phase()

    refused = game.declare_attackers(0, [0])
    assert not refused[0], refused
    assert game.declare_attackers(0, [1])[0]


def test_w1g3_off_balance_stops_its_target_blocking(set_pool):
    game, (raider,), (wall, other) = _w1g3_duel(
        [_w1g3_body("Raider", 2, 2)],
        [_w1g3_body("Wall", 0, 4), _w1g3_body("Other", 1, 1)],
        hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    game.cast_from_hand(1, "Off Balance", target_permanent_ids=[wall.permanent_id])
    resolve_stack(game)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    assert not game._can_block_attacker(wall, raider)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g3_off_balance_ends_with_the_turn(set_pool):
    game, (bear,), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2)], [], hand_of_1=[set_pool("NEM")["Off Balance"]],
    )
    game.cast_from_hand(1, "Off Balance", target_permanent_ids=[bear.permanent_id])
    resolve_stack(game)
    assert bear.metadata.get("cant_block_until_eot")

    game.resolve_cleanup_step(0)

    assert not bear.metadata.get("cant_block_until_eot")
    assert not bear.metadata.get("cant_attack_until_eot_mark")


def test_w1g3_off_balance_announces_one_creature_target(set_pool):
    """Two instructions, one target: the picker asks once, for a creature."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("NEM")["Off Balance"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {"kind": "creature"}, spec


# --- Fog Patch -------------------------------------------------------------
# "Cast this spell only during the declare blockers step. / Attacking creatures
# become blocked." CR 509.1h: blocked with no blocker — no combat damage unless
# the creature has trample, which then assigns all of it to the player
# (CR 702.19d) — and the becomes-blocked triggers of the creatures that were
# unblocked fire (CR 509.3c).


def test_w1g3_fog_patch_blocks_every_attacker_including_the_unblockable(set_pool):
    game, (bear, ghost), _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2),
         _w1g3_body("Ghost", 3, 3, text="This creature can't be blocked.")],
        [], hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    game.declare_blockers(1, {})

    result = game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)

    assert result.supported, result.details
    assert bear.blocked and ghost.blocked
    _w1g3_walk_combat_to(game, "postcombat_main")
    assert game.players[1].life == 20


def test_w1g3_fog_patch_lets_a_trampler_through_in_full(set_pool):
    game, (trampler,), _ = _w1g3_duel(
        [_w1g3_body("Trampler", 4, 4, text="Trample", keywords=("Trample",))], [],
        hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    game.declare_blockers(1, {})
    game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)
    assert trampler.blocked

    _w1g3_walk_combat_to(game, "postcombat_main")

    assert game.players[1].life == 16


def test_w1g3_fog_patch_fires_becomes_blocked_once_for_the_unblocked(set_pool):
    """Flint Golem was unblocked, so CR 509.3c fires its trigger; the second
    Golem already had a blocker, so becoming blocked again announces nothing."""
    nem = set_pool("NEM")
    game, (free, held), (wall,) = _w1g3_duel(
        [nem["Flint Golem"], nem["Flint Golem"]], [_w1g3_body("Wall", 0, 5)],
        hand_of_1=[nem["Fog Patch"]],
    )
    game.players[1].library = [_w1g3_body(f"Card{i}", 1, 1) for i in range(9)]
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 1})[0]
    resolve_stack(game)
    assert len(game.players[1].library) == 6

    game.cast_from_hand(1, "Fog Patch")
    resolve_stack(game)

    assert free.blocked and held.blocked
    assert len(game.players[1].library) == 3
    assert sum(
        "Flint Golem triggered on becoming blocked" in line for line in game.log
    ) == 2


def test_w1g3_fog_patch_cannot_be_cast_before_blockers(set_pool):
    game, _, _ = _w1g3_duel(
        [_w1g3_body("Bear", 2, 2)], [], hand_of_1=[set_pool("NEM")["Fog Patch"]],
    )
    game.active_player_index = 0

    result = game.cast_from_hand(1, "Fog Patch")

    assert result.details != "resolved", result
    assert [card.name for card in game.players[1].hand] == ["Fog Patch"]


def test_w1g3_fog_patch_announces_no_target(set_pool):
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("NEM")["Fog Patch"]

    assert derive_cast_spec(card, compile_card_oracle(card)) is None
