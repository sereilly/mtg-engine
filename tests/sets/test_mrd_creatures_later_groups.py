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
#
# Activated abilities: X equal to this creature's power (Auriok Bladewarden),
# mana equal to it (Viridian Joiner), unspent mana as a number (Glissa
# Sunseeker), and the tap abilities on arrival this family drives.
from engine import Game as _W1G8Game
from engine.board_payment import board_can_pay as _w1g8_board_can_pay
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_board(set_pool, mine, theirs=(), *, hand=()):
    """A duel at seat 0's first main phase, *mine* and *theirs* on the
    battlefield and ready to tap; mana costs off unless a test turns them on."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8PlayerState(name="A", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G8PlayerState(name="B", library=[lea["Plains"]] * 8),
    ])
    game.enforce_mana_costs = False
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            perm = _W1G8Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            placed.append(perm)
    _w1g8_resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.current_step == "precombat_main"
    return game, placed


def test_w1g8_auriok_bladewarden_pumps_by_its_own_power(set_pool):
    """X is the Bladewarden's power as the ability resolves (CR 608.2h): pumped
    to 4 by Giant Growth, it gives the Bears +4/+4, not +1/+1 and not the
    Bears' own power."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (blade, bears) = _w1g8_board(
        set_pool, [mrd["Auriok Bladewarden"], lea["Grizzly Bears"]],
        hand=[lea["Giant Growth"]],
    )
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[blade.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert blade.effective_power == 4
    assert game.activate_permanent_ability(
        0, "Auriok Bladewarden", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert blade.tapped
    assert "Auriok Bladewarden gives Grizzly Bears +4/+4 until end of turn" in game.log


def test_w1g8_auriok_bladewarden_reads_last_known_power_after_it_dies(set_pool):
    """Killed in response, the Bladewarden's ability still resolves (CR 113.7a)
    and reads the power it last had on the battlefield (CR 608.2h)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (blade, bears) = _w1g8_board(
        set_pool, [mrd["Auriok Bladewarden"], lea["Grizzly Bears"]],
        hand=[lea["Giant Growth"], lea["Terror"]],
    )
    game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[blade.permanent_id])
    _w1g8_resolve_stack(game)
    queued = game.queue_permanent_ability(
        0, "Auriok Bladewarden", target_permanent_ids=[bears.permanent_id]
    )
    assert queued.supported and len(game.stack) == 1
    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[blade.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert not game.is_on_battlefield(blade)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)


def test_w1g8_viridian_joiner_adds_green_equal_to_its_power(set_pool):
    """One {G} per point of the Joiner's power, read off it as the mana ability
    resolves — and the payment planner counts the same number."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (joiner,) = _w1g8_board(set_pool, [mrd["Viridian Joiner"]])
    assert game.activate_permanent_ability(0, "Viridian Joiner").supported
    assert game.players[0].mana_pool["G"] == 1
    assert "Viridian Joiner produced {G}" in game.log

    game, (joiner, _forest) = _w1g8_board(
        set_pool, [mrd["Viridian Joiner"], lea["Forest"]],
        hand=[lea["Giant Growth"], lea["Ironroot Treefolk"]],
    )
    game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[joiner.permanent_id])
    _w1g8_resolve_stack(game)
    game.enforce_mana_costs = True
    # 4 from the Joiner and 1 from the Forest pay {4}{G}; {5}{G} is one short.
    assert _w1g8_board_can_pay(game, 0, {"generic": 3, "G": 2}, nonland_sources=True)
    assert not _w1g8_board_can_pay(game, 0, {"generic": 5, "G": 1}, nonland_sources=True)
    assert game.activate_permanent_ability(0, "Viridian Joiner").supported
    assert game.players[0].mana_pool["G"] == 4
    assert game.tap_land_for_mana(0, "Forest")
    assert game.cast_from_hand(0, "Ironroot Treefolk").supported
    _w1g8_resolve_stack(game)
    assert "Ironroot Treefolk" in [p.card.name for p in game.players[0].battlefield]
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g8_glissa_sunseeker_destroys_only_on_an_exact_match(set_pool):
    """2004-12-01: the artifact's mana value must be exactly the unspent mana
    when the ability resolves — more or less and it survives. Floating mana is
    read, not spent; a restricted bucket is unspent mana too."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for pool, name, destroyed in (
        ({"G": 1}, "Sol Ring", True),
        ({"G": 2}, "Sol Ring", False),
        ({}, "Ornithopter", True),
        ({"U": 1}, "Ornithopter", False),
    ):
        game, (_glissa, ring, thopter) = _w1g8_board(
            set_pool, [mrd["Glissa Sunseeker"]],
            [lea["Sol Ring"], mrd["Ornithopter"]],
        )
        target = ring if name == "Sol Ring" else thopter
        game.players[0].mana_pool.update(pool)
        assert game.activate_permanent_ability(
            0, "Glissa Sunseeker", target_permanent_ids=[target.permanent_id]
        ).supported
        _w1g8_resolve_stack(game)
        assert game.is_on_battlefield(target) is not destroyed, (pool, name)
        assert sum(game.players[0].mana_pool.values()) == sum(pool.values())
    game, (_glissa, vise) = _w1g8_board(
        set_pool, [mrd["Glissa Sunseeker"]], [lea["Black Vise"]],
    )
    game.players[0].restricted_mana["creature"] = {"G": 1}
    game.activate_permanent_ability(
        0, "Glissa Sunseeker", target_permanent_ids=[vise.permanent_id]
    )
    _w1g8_resolve_stack(game)
    assert not game.is_on_battlefield(vise)
    assert "Glissa Sunseeker destroyed Black Vise" in game.log

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

# ==== end W1G12 ======================================================
