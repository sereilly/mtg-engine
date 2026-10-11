"""Apocalypse enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.control import change_control as _w1g2_change_control
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand=(), mana=None, opp_hand=(), opp_mana=None):
    """A two-seat game with mana costs enforced. *hand* names Apocalypse cards
    (or Alpha ones); *opp_hand* is Alpha."""
    lea, apc = set_pool("LEA"), set_pool("APC")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[apc[name] if name in apc else lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (enchantments)


def _w1g2_put(game, set_pool, seat, name, code="LEA"):
    """*name* onto *seat*'s battlefield, able to act this turn."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (enchantments)


def _w1g2_slot(game, seat, permanent):
    return list(game.controlled_by(seat)).index(permanent)  # _w1g2_slot (enchantments)


# Bloodfire Infusion ---------------------------------------------------------


def _w1g2_infused(set_pool, extra_hand=(), extra_mana=None):
    """Bloodfire Infusion cast onto the caster's Hill Giant and resolved, with
    one {R} left for its ability. Across the table: a 0/8 Wall of Stone and a
    Hill Giant. Returns ``(game, aura, host, wall, their_giant)``."""
    game = _w1g2_table(
        set_pool, ["Bloodfire Infusion", *extra_hand],
        {"R": 4, **(extra_mana or {})},
    )
    host = _w1g2_put(game, set_pool, 0, "Hill Giant")
    wall = _w1g2_put(game, set_pool, 1, "Wall of Stone")
    their_giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    result = game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[host.permanent_id],
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Bloodfire Infusion")
    return game, aura, host, wall, their_giant  # _w1g2_infused


def test_w1g2_bloodfire_infusion_enchants_only_a_creature_its_caster_controls(set_pool):
    """"Enchant creature you control": the picker offers the caster's own
    creatures, and an opponent's creature is refused with nothing spent."""
    game = _w1g2_table(set_pool, ["Bloodfire Infusion"], {"R": 3})
    mine = _w1g2_put(game, set_pool, 0, "Hill Giant")
    theirs = _w1g2_put(game, set_pool, 1, "Hill Giant")
    spec = game.cast_target_spec(0, set_pool("APC")["Bloodfire Infusion"])
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [(0, "Hill Giant")]

    refused = game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[theirs.permanent_id],
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == 3

    assert game.cast_from_hand(
        0, "Bloodfire Infusion", target_permanent_ids=[mine.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    (aura,) = [p for p in game.controlled_by(0) if p.card.name == "Bloodfire Infusion"]
    assert aura.metadata.get("attached_to") is mine


def test_w1g2_bloodfire_infusion_deals_the_sacrificed_creatures_power_to_each_creature(
    set_pool,
):
    """"{R}, Sacrifice enchanted creature: This Aura deals damage equal to the
    sacrificed creature's power to each creature." The host is paid as the
    cost, the Aura follows it to the graveyard as a state-based action
    (CR 704.5m) with its ability still on the stack (CR 113.7a), and the
    ability then deals 3 — the Hill Giant's power — to every creature on both
    sides. This card arrived dealing 0: the host was sacrificed and never
    recorded."""
    game, aura, host, wall, their_giant = _w1g2_infused(set_pool)
    mine = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    queued = game.queue_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )
    assert queued.supported, queued.details
    assert "Caster sacrificed Hill Giant to activate Bloodfire Infusion" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(aura)
    assert [item.card.name for item in game.stack] == ["Bloodfire Infusion"]

    _w1g2_resolve_stack(game)
    assert (mine.damage_marked, wall.damage_marked, their_giant.damage_marked) == (3, 3, 3)
    game.check_state_based_actions()

    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Bloodfire Infusion", "Grizzly Bears", "Hill Giant",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert game.is_on_battlefield(wall)
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g2_bloodfire_infusion_reads_the_power_the_creature_last_had(set_pool):
    """CR 608.2h: last known information. A Giant Growth on the host makes it
    6/6, and the 6 is what each creature is dealt — off the permanent as it
    last existed, not off the card in the graveyard."""
    game, aura, host, wall, _their_giant = _w1g2_infused(
        set_pool, extra_hand=["Giant Growth"], extra_mana={"G": 1},
    )
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[host.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert host.effective_power == 6

    result = game.activate_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )

    assert result.supported, result.details
    assert wall.damage_marked == 6


def test_w1g2_bloodfire_infusion_refused_activation_sacrifices_nothing(set_pool):
    """Without {R} the ability is refused and the whole cost with it: the
    enchanted creature is still there, still enchanted."""
    game, aura, host, wall, _their_giant = _w1g2_infused(set_pool)
    game.players[0].mana_pool["R"] = 0

    result = game.activate_permanent_ability(
        0, "Bloodfire Infusion", permanent_index=_w1g2_slot(game, 0, aura),
    )

    assert not result.supported
    assert game.is_on_battlefield(host) and game.is_on_battlefield(aura)
    assert aura.metadata.get("attached_to") is host
    assert wall.damage_marked == 0


def test_w1g2_bloodfire_infusion_falls_off_a_creature_its_controller_lost(set_pool):
    """The card's ruling: "If this card is ever on a creature you don't
    control, it is put into the graveyard as a State-Based Action."
    (CR 704.5m: the Aura no longer enchants what its enchant ability names.)"""
    game, aura, host, _wall, _their_giant = _w1g2_infused(set_pool)

    _w1g2_change_control(host, 1, source="a control effect")
    game._sync_control()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(aura)
    assert [card.name for card in game.players[0].graveyard] == ["Bloodfire Infusion"]
    assert game.controller_index_of(host) == 1


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_bloodfire_infusion_and_its_neighbours_through_whole_games():
    """Bloodfire Infusion and four of this group's spells pinned into both
    decks of three simulated games. They are cast and resolve, none is refused
    at the cast or the activation gate, and none leaves a step owing a prompt.
    (Apocalypse is a measured set, so other cards' unsupported casts are in the
    report; only these cards' lines are read.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Bloodfire Infusion", "Captain's Maneuver", "Consume Strength",
        "Strength of Night", "Aether Mutation",
    ]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("APC", include_measured=True)],
        games=3, seed=1337, max_turns=22, required_cards=names,
    )

    assert report.games_completed == 3
    resolved = sorted(
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    )
    assert len(resolved) >= 3, resolved
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        key for key in report.refused_activations if key.split(":")[0] in names
    ] == []
    assert [
        issue.message for issue in report.issues
        if any(name in issue.message for name in names)
    ] == []
    w1g2_owing = [
        key for key in report.steps_left_owing if any(name in str(key) for name in names)
    ]
    assert w1g2_owing == [], report.steps_left_owing


# Martyrs' Tomb --------------------------------------------------------------


def test_w1g2_martyrs_tomb_trades_two_life_for_one_point_of_prevention(set_pool):
    """"Pay 2 life: Prevent the next 1 damage that would be dealt to target
    creature this turn." Twice for 4 life: a Lightning Bolt at the Bears has 2
    of its 3 prevented and the Bears survive with 1 marked."""
    game = _w1g2_table(set_pool, opp_hand=["Lightning Bolt"], opp_mana={"R": 1})
    tomb = _w1g2_put(game, set_pool, 0, "Martyrs' Tomb", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    for _ in range(2):
        result = game.activate_permanent_ability(
            0, "Martyrs' Tomb", permanent_index=_w1g2_slot(game, 0, tomb),
            target_permanent_ids=[bears.permanent_id],
        )
        assert result.supported, result.details
    assert game.players[0].life == 16

    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()

    assert "Prevented 2 damage to Grizzly Bears" in game.log
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears)


def test_w1g2_martyrs_tomb_cost_and_target_are_both_enforced(set_pool):
    """CR 119.4: a player can pay life only if their total is at least the
    payment — at 1 life the ability is refused and the life is kept; at 2 it
    is paid and its controller is at 0. And "target creature" is not a land:
    that activation is refused before the life is paid."""
    game = _w1g2_table(set_pool)
    tomb = _w1g2_put(game, set_pool, 0, "Martyrs' Tomb", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    land = _w1g2_put(game, set_pool, 0, "Forest")
    slot = _w1g2_slot(game, 0, tomb)

    assert not game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[land.permanent_id],
    ).supported
    assert game.players[0].life == 20

    game.players[0].life = 1
    assert not game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[0].life == 1

    game.players[0].life = 2
    assert game.activate_permanent_ability(
        0, "Martyrs' Tomb", permanent_index=slot,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.players[0].life == 0

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
