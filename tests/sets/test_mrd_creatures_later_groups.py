"""Mirrodin creatures, the later groups' sections (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.
#
# The drive list: Mirrodin creatures that compiled supported on arrival and
# had never been run, each given a game through the real entry points.

import pytest as _w1g12_pytest

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine.models import Permanent as _w1g12_Permanent
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import declare_attack as _w1g12_declare_attack
from tests.helpers import resolve_stack as _w1g12_resolve_stack

_w1g12_pytest_mark_parametrize = _w1g12_pytest.mark.parametrize


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                 graveyard=(), interactive=()):
    """Seat 0 (A) in its first main phase, mana off; each named permanent
    untapped and able to act."""
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
            graveyard=[card(n) for n in graveyard],
        ),
        _w1g12_PlayerState(
            "B", hand=[card(n) for n in opponent_hand],
            library=[card("Island")] * 12,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g12_rustmouth_ogre_destroys_an_artifact_the_damaged_player_controls(set_pool):
    # "…you may destroy target artifact that player controls." The seat is
    # the damage event's (pinned in test_stack_targets for that reason):
    # through a real combat damage step only B's artifacts are offered, A's
    # own Sol Ring is refused, and the one named is destroyed.
    game, (_ogre, sol), (scimitar, thopter) = _w1g12_table(
        set_pool, mine=["Rustmouth Ogre", "Sol Ring"],
        theirs=["Leonin Scimitar", "Ornithopter"], interactive=(0,),
    )
    _w1g12_declare_attack(game, 0)
    game.advance_combat_phase()
    assert game.players[1].life == 15
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target"
    offered = {entry["permanent_id"] for entry in choice.data["targets"]}
    assert offered == {scimitar.permanent_id, thopter.permanent_id}
    assert not game.confirm_trigger_target(0, permanent_id=sol.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=thopter.permanent_id)
    _w1g12_resolve_stack(game)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Leonin Scimitar"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Rustmouth Ogre", "Sol Ring"]


def test_w1g12_rustmouth_ogre_default_seat_takes_the_damaged_players_artifact(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Rustmouth Ogre", "Sol Ring"], theirs=["Leonin Scimitar"],
    )
    _w1g12_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == []
    assert "Sol Ring" in [p.card.name for p in game.controlled_by(0)]


def _w1g12_settle(game):
    _w1g12_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g12_resolve_stack(game)
    game._settle()


def _w1g12_into_blocks(game, attacker_seat, attacker_slots):
    """*attacker_seat* attacks with *attacker_slots*; the declare-blockers step
    is open and nothing is declared yet."""
    game.active_player_index = attacker_seat
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        attacker_seat, list(attacker_slots), defending_player_index=1 - attacker_seat,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


@_w1g12_pytest_mark_parametrize("name", [
    "Tel-Jilad Exile", "Troll Ascetic", "Flayed Nim",
])
def test_w1g12_a_self_regenerator_survives_lethal_damage(set_pool, name):
    game, (me,), _ = _w1g12_table(set_pool, mine=[name], hand=["Lightning Bolt"])
    assert game.activate_permanent_ability(0, name).supported
    _w1g12_settle(game)
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[me.permanent_id],
    ).supported
    _w1g12_settle(game)
    assert game.is_on_battlefield(me) and me.tapped and me.damage_marked == 0


def test_w1g12_loxodon_mender_regenerates_an_artifact(set_pool):
    game, (mender, myr), _ = _w1g12_table(
        set_pool, mine=["Loxodon Mender", "Alpha Myr"], hand=["Lightning Bolt"],
    )
    assert game.activate_permanent_ability(
        0, "Loxodon Mender", target_permanent_ids=[myr.permanent_id],
    ).supported
    _w1g12_settle(game)
    assert mender.tapped
    game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[myr.permanent_id])
    _w1g12_settle(game)
    assert game.is_on_battlefield(myr)


def test_w1g12_trolls_of_tel_jilad_regenerate_a_green_creature_only(set_pool):
    game, (_trolls, elves, angel), _ = _w1g12_table(
        set_pool, mine=["Trolls of Tel-Jilad", "Llanowar Elves", "Serra Angel"],
        hand=["Lightning Bolt"],
    )
    assert not game.activate_permanent_ability(
        0, "Trolls of Tel-Jilad", target_permanent_ids=[angel.permanent_id],
    ).supported
    assert game.activate_permanent_ability(
        0, "Trolls of Tel-Jilad", target_permanent_ids=[elves.permanent_id],
    ).supported
    _w1g12_settle(game)
    game.queue_from_hand(0, "Lightning Bolt", target_permanent_ids=[elves.permanent_id])
    _w1g12_settle(game)
    assert game.is_on_battlefield(elves)


def test_w1g12_wall_of_blood_pays_life_for_size_and_cannot_attack(set_pool):
    game, (wall,), _ = _w1g12_table(set_pool, mine=["Wall of Blood"])
    for _ in range(3):
        assert game.activate_permanent_ability(0, "Wall of Blood").supported
        _w1g12_settle(game)
    assert (wall.effective_power, wall.effective_toughness) == (3, 5)
    assert game.players[0].life == 17
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(0, [0], defending_player_index=1)[0]


@_w1g12_pytest_mark_parametrize("name", ["Tel-Jilad Archers", "Tel-Jilad Chosen"])
def test_w1g12_protection_from_artifacts_refuses_an_artifacts_target(set_pool, name):
    game, (me, _bomb), _ = _w1g12_table(set_pool, mine=[name, "Pyrite Spellbomb"])
    assert not game.activate_permanent_ability(
        0, "Pyrite Spellbomb", target_permanent_ids=[me.permanent_id], ability_index=0,
    ).supported
    assert game.is_on_battlefield(me)


def test_w1g12_tel_jilad_archers_reach_blocks_a_flyer(set_pool):
    game, _, _ = _w1g12_table(set_pool, mine=["Tel-Jilad Archers"], theirs=["Ornithopter"])
    _w1g12_into_blocks(game, 1, [0])
    assert game.declare_blockers(0, {0: 0})[0]


def test_w1g12_flayed_nim_drains_the_blocked_creatures_controller(set_pool):
    game, _, _ = _w1g12_table(set_pool, mine=["Flayed Nim"], theirs=["Grizzly Bears"])
    _w1g12_into_blocks(game, 1, [0])
    assert game.declare_blockers(0, {0: 0})[0]
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[1].life == 18


def test_w1g12_woebearer_returns_a_creature_card_and_has_fear(set_pool):
    game, _, _ = _w1g12_table(set_pool, mine=["Woebearer"], graveyard=["Grizzly Bears"])
    _w1g12_declare_attack(game, 0)
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[1].life == 18
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    game, _, _ = _w1g12_table(
        set_pool, mine=["Woebearer"], theirs=["Grizzly Bears", "Alpha Myr"],
    )
    _w1g12_into_blocks(game, 0, [0])
    assert not game.declare_blockers(1, {0: 0})[0]  # green, not artifact
    assert game.declare_blockers(1, {1: 0})[0]       # artifact creature


def test_w1g12_dross_prowler_has_fear(set_pool):
    game, _, _ = _w1g12_table(
        set_pool, mine=["Dross Prowler"], theirs=["Grizzly Bears", "Alpha Myr"],
    )
    _w1g12_into_blocks(game, 0, [0])
    assert not game.declare_blockers(1, {0: 0})[0]
    assert game.declare_blockers(1, {1: 0})[0]


@_w1g12_pytest_mark_parametrize("name", ["Vulshok Berserker", "Goblin Striker"])
def test_w1g12_a_haste_creature_attacks_the_turn_it_arrives(set_pool, name):
    game, _, _ = _w1g12_table(set_pool, hand=[name])
    assert game.queue_from_hand(0, name).supported
    _w1g12_settle(game)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why


def test_w1g12_goblin_striker_first_strike_kills_its_blocker_unharmed(set_pool):
    game, (striker,), (elves,) = _w1g12_table(
        set_pool, mine=["Goblin Striker"], theirs=["Llanowar Elves"],
    )
    _w1g12_into_blocks(game, 0, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert not game.is_on_battlefield(elves)
    assert game.is_on_battlefield(striker) and striker.damage_marked == 0


def test_w1g12_fangren_hunter_tramples_over_a_chump(set_pool):
    game, _, _ = _w1g12_table(set_pool, mine=["Fangren Hunter"], theirs=["Llanowar Elves"])
    _w1g12_into_blocks(game, 0, [0])
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    _w1g12_settle(game)
    assert game.players[1].life == 17


@_w1g12_pytest_mark_parametrize("name", ["Leonin Skyhunter", "Skyhunter Patrol"])
def test_w1g12_a_flyer_cannot_be_blocked_from_the_ground(set_pool, name):
    game, _, _ = _w1g12_table(set_pool, mine=[name], theirs=["Grizzly Bears"])
    _w1g12_into_blocks(game, 0, [0])
    assert not game.declare_blockers(1, {0: 0})[0]


def test_w1g12_hexproof_refuses_only_the_opponent(set_pool):
    for name in ("Plated Slagwurm", "Troll Ascetic"):
        game, _, (creature,) = _w1g12_table(set_pool, theirs=[name], hand=["Lightning Bolt"])
        assert not game.queue_from_hand(
            0, "Lightning Bolt", target_permanent_ids=[creature.permanent_id],
        ).supported
    game, (wurm,), _ = _w1g12_table(set_pool, mine=["Plated Slagwurm"], hand=["Giant Growth"])
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[wurm.permanent_id],
    ).supported


@_w1g12_pytest_mark_parametrize("name,size", [
    ("Lumengrid Warden", (1, 3)), ("Plated Slagwurm", (8, 8)),
])
def test_w1g12_a_creature_casts_at_its_printed_size(set_pool, name, size):
    game, _, _ = _w1g12_table(set_pool, hand=[name])
    assert game.queue_from_hand(0, name).supported
    _w1g12_settle(game)
    (perm,) = [p for p in game.controlled_by(0) if p.card.name == name]
    assert (perm.effective_power, perm.effective_toughness) == size

# ==== end W1G12 ======================================================
