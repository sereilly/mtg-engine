"""Judgment instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
from engine import Game as _w1g8_Game
from engine import PlayerState as _w1g8_PlayerState
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_duel(*, active: int = 0) -> "_w1g8_Game":
    """Two seats, mana costs waived, seat *active*'s turn started for real."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P1"), _w1g8_PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(active)
    return game


def _w1g8_zone_names(zone) -> list[str]:
    return sorted(card.name for card in zone)


# --- Seedtime -------------------------------------------------------------

def test_w1g8_seedtime_takes_an_extra_turn_when_an_opponent_cast_a_blue_spell(set_pool):
    """"Take an extra turn after this one if an opponent cast a blue spell this
    turn." Ruling 2004-10-04: "an unresolved spell still counts" — the blue
    spell here is cast *in response*, so it is still on the stack above
    Seedtime when it is cast, and resolves before it."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(jud["Seedtime"])
    game.players[1].hand.append(lea["Ancestral Recall"])
    game.players[1].library.extend([lea["Island"]] * 3)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    _w1g8_resolve_stack(game)
    assert game.extra_turns.get(0, 0) == 1
    assert game.extra_turns.get(1, 0) == 0
    assert "P1 gained an extra turn" in game.log
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Seedtime"]


def test_w1g8_seedtime_without_a_blue_opposing_cast_takes_no_turn(set_pool):
    """The narrowing is enforced, not dropped: an opponent's *red* spell does
    not open it, and neither does a blue spell Seedtime's own caster cast."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.extend([jud["Seedtime"], lea["Ancestral Recall"]])
    game.players[0].library.extend([lea["Island"]] * 3)
    game.players[1].hand.append(lea["Lightning Bolt"])
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.queue_from_hand(0, "Seedtime").supported
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[0].life == 17                 # the Bolt resolved
    assert game.extra_turns.get(0, 0) == 0
    assert not any("gained an extra turn" in line for line in game.log)
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


def test_w1g8_seedtime_is_cast_only_during_its_casters_turn(set_pool):
    """"Cast this spell only during your turn." (CR 601.3.) Refused on the
    opponent's turn with the card still in hand, and legal again on the
    caster's own."""
    jud = set_pool("JUD")
    game = _w1g8_duel(active=1)
    game.players[0].hand.append(jud["Seedtime"])
    refused = game.cast_from_hand(0, "Seedtime")
    assert not refused.supported
    assert "can only be cast during your turn" in refused.details
    assert _w1g8_zone_names(game.players[0].hand) == ["Seedtime"]
    game.start_turn(0)
    assert game.cast_from_hand(0, "Seedtime").supported
    assert "Seedtime" in _w1g8_zone_names(game.players[0].graveyard)


# --- Laquatus's Disdain ---------------------------------------------------

def _w1g8_firebolt_flashed_back(set_pool) -> "_w1g8_Game":
    """Seat 0 flashes Firebolt back at seat 1, leaving it on the stack."""
    game = _w1g8_duel()
    game.players[0].graveyard.append(set_pool("ODY")["Firebolt"])
    assert game.queue_from_hand(
        0, "Firebolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert game.stack[-1].flashback and game.stack[-1].cast_from_zone == "graveyard"
    return game


def test_w1g8_laquatuss_disdain_counters_a_spell_cast_from_a_graveyard(set_pool):
    """"Counter target spell cast from a graveyard. Draw a card." A flashed-back
    Firebolt is countered (and, flashed back, exiled — CR 702.34a), and the
    Disdain's caster draws."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_firebolt_flashed_back(set_pool)
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    game.players[1].library.append(lea["Island"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Firebolt"]
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20                       # Firebolt never resolved
    assert _w1g8_zone_names(game.players[0].exile) == ["Firebolt"]
    assert _w1g8_zone_names(game.players[1].hand) == ["Island"]
    assert any(
        line.startswith("Firebolt was countered by Laquatus's Disdain")
        for line in game.log
    )


def test_w1g8_laquatuss_disdain_counters_any_graveyard_cast_not_only_flashback(set_pool):
    """Ruling 2004-10-04: "Can be used to counter a spell cast using the
    Flashback ability, **or cast from the graveyard using any other effect**."
    A graveyard opened by another permission (CR 601.3) is a graveyard cast."""
    from engine.cast_permissions import grant_permission

    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].graveyard.append(lea["Lightning Bolt"])
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast", cards=None,
        duration="end_of_turn", source_name="Test Opened Graveyard",
    )
    assert game.queue_from_hand(
        0, "Lightning Bolt", from_zone="graveyard", target_player_index=1,
    ).supported
    assert not game.stack[-1].flashback
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    assert game.queue_from_hand(1, "Laquatus's Disdain", target_stack_index=0).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 20
    assert _w1g8_zone_names(game.players[0].graveyard) == ["Lightning Bolt"]


def test_w1g8_laquatuss_disdain_cannot_be_cast_at_a_spell_cast_from_a_hand(set_pool):
    """The narrowing is the picker's and the gate's: a Lightning Bolt cast from
    a hand is not offered, and naming it anyway is refused before anything is
    spent (CR 601.2c) — the Disdain stays in hand and the Bolt resolves."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g8_duel()
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game.players[1].hand.append(jud["Laquatus's Disdain"])
    spec = game.cast_target_spec(1, jud["Laquatus's Disdain"])
    assert spec["valid_targets"] == []
    refused = game.cast_from_hand(1, "Laquatus's Disdain", target_stack_index=0)
    assert not refused.supported
    assert _w1g8_zone_names(game.players[1].hand) == ["Laquatus's Disdain"]
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 17

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
