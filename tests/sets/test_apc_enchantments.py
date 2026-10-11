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

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5e_Game, PlayerState as _w1g5e_Player
from engine.models import Permanent as _w1g5e_Permanent
from tests.helpers import _mk_card as _w1g5e_mk_card
from tests.helpers import resolve_stack as _w1g5e_resolve_stack

_W1G5E_REQUIRED = "must be chosen as a target if able"


def _w1g5e_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0):
    """Two boards placed and unsick, *active*'s turn begun."""
    board0 = [_w1g5e_Permanent(card=card) for card in mine]
    board1 = [_w1g5e_Permanent(card=card) for card in theirs]
    filler = _w1g5e_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5e_Game(players=[
        _w1g5e_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5e_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 enchantments: the duel


def test_coalition_flag_makes_its_creature_a_flagbearer_and_the_only_target(set_pool):
    """Coalition Flag {W} Aura — "Enchant creature you control / Enchanted
    creature is a Flagbearer. / While an opponent is choosing targets …, that
    player must choose at least one Flagbearer on the battlefield if able."

    The Bears under the Flag are a Flagbearer **and no longer a Bear** (CR
    205.1a: a sentence that sets a subtype without "in addition to its other
    types" replaces the creature types it had). The opponent's Bolt may go
    nowhere else. Disenchant is not bound — the Bears are no legal target for
    it — and with the Flag gone the Bears are Bears and the next Bolt is free."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]],
        hand1=[lea["Lightning Bolt"], lea["Disenchant"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    flag = next(p for p in game.controlled_by(0) if p.card.name == "Coalition Flag")
    assert bears.has_type("flagbearer") and bears.is_creature
    assert not bears.has_type("bear")
    assert lions.has_type("cat") and not lions.has_type("flagbearer")

    offered = game.cast_target_spec(1, lea["Lightning Bolt"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    for announcement in (
        {"target_player_index": 0},
        {"target_permanent_ids": [lions.permanent_id]},
    ):
        refused = game.queue_from_hand(1, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5E_REQUIRED in refused.details, refused
        assert "Coalition Flag" in refused.details

    assert game.cast_from_hand(
        1, "Disenchant", target_permanent_ids=[flag.permanent_id]
    ).supported
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 17


def test_coalition_flag_enchants_only_its_controllers_own_creature(set_pool):
    """"Enchant creature **you control**": the picker offers the caster's own
    creatures, and a cast at an opponent's is refused with the Aura in hand."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"]], hand0=[apc["Coalition Flag"]],
    )
    offered = game.cast_target_spec(0, apc["Coalition Flag"])["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Grizzly Bears")]
    refused = game.queue_from_hand(
        0, "Coalition Flag", target_permanent_ids=[theirs[0].permanent_id]
    )
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Coalition Flag"]


def test_the_flags_own_controller_is_not_bound_by_it(set_pool):
    """"While **an opponent** is choosing targets": the Flag's controller pumps
    their other creature beside the flagged one."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"], lea["Giant Growth"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert (lions.effective_power, lions.effective_toughness) == (5, 4)


def test_shield_of_duty_and_reason_is_protection_from_green_and_from_blue(set_pool):
    """Shield of Duty and Reason {W} Aura: "Enchanted creature has protection
    from green and from blue." Both colours, each doing protection's work: a
    green Giant Growth and a blue Unsummon may not target the creature — its
    own controller's included — a green creature may not block it, and a red
    Bolt still kills it, taking the Aura to the graveyard with it."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5e_duel(
        [lea["Savannah Lions"]], [lea["Grizzly Bears"]],
        hand0=[apc["Shield of Duty and Reason"], lea["Giant Growth"]],
        hand1=[lea["Unsummon"], lea["Lightning Bolt"]],
    )
    lions, green_bears = mine[0], theirs[0]
    assert game.cast_from_hand(
        0, "Shield of Duty and Reason", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert game._protection_qualities(lions) == {("color", "G"), ("color", "U")}

    for seat, spell in ((0, "Giant Growth"), (1, "Unsummon")):
        refused = game.queue_from_hand(seat, spell, target_permanent_ids=[lions.permanent_id])
        assert not refused.supported, (spell, refused)
    assert lions.permanent_id not in [
        game.permanent_at(entry["seat"], entry["index"]).permanent_id
        for entry in game.cast_target_spec(1, lea["Unsummon"])["valid_targets"]
    ]

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(lions)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    declared = game.declare_blockers(1, {
        game.battlefield_index_of(green_bears): [game.battlefield_index_of(lions)],
    })
    assert declared[0] is False, declared

    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[lions.permanent_id]
    ).supported
    _w1g5e_resolve_stack(game)
    game._settle()
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Savannah Lions", "Shield of Duty and Reason",
    ]


def test_coalition_flag_falls_off_a_creature_its_controller_loses(set_pool):
    """"If this card is ever on a creature you don't control, it is put into
    the graveyard as a State-Based Action" (ruling, 2004-10-04; CR 704.5m).
    The opponent's Control Magic has to be aimed at the flagged Bears — the
    only target an Aura spell of theirs may choose — and taking them takes the
    Flag off: the Bears arrive as Bears, and the requirement is gone."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5e_duel(
        [lea["Grizzly Bears"], lea["Savannah Lions"]], [],
        hand0=[apc["Coalition Flag"]], hand1=[lea["Control Magic"], lea["Lightning Bolt"]],
    )
    bears, lions = mine
    assert game.cast_from_hand(
        0, "Coalition Flag", target_permanent_ids=[bears.permanent_id]
    ).supported
    offered = game.cast_target_spec(1, lea["Control Magic"])["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]
    stolen = game.queue_from_hand(1, "Control Magic", target_permanent_ids=[lions.permanent_id])
    assert not stolen.supported and _W1G5E_REQUIRED in stolen.details

    assert game.cast_from_hand(
        1, "Control Magic", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.controller_index_of(bears) == 1
    assert [card.name for card in game.players[0].graveyard] == ["Coalition Flag"]
    assert bears.has_type("bear") and not bears.has_type("flagbearer")
    assert "required_targets" not in game.cast_target_spec(1, lea["Lightning Bolt"])

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
