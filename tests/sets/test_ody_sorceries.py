"""Odyssey sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_duel(set_pool, hand, *, graveyard=0):
    """A two-seat game with costs off, seat 0 holding *hand* (card names from
    Odyssey) with *graveyard* cards in its graveyard, in its main phase."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[ody[name] for name in hand],
        ),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g2_names


# ---------------------------------------------------------------------------
# Epicenter
# ---------------------------------------------------------------------------

def test_epicenter_below_threshold_costs_the_target_one_land(set_pool):
    """"Target player sacrifices a land of their choice." One land, the
    targeted player's, and the caster's own lands are untouched."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=6)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Forest"] * 3
    assert _w1g2_names(game, 1) == ["Grizzly Bears", "Island", "Island"]
    assert game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Island"]


def test_epicenter_at_threshold_takes_every_land_instead(set_pool):
    """"Threshold — **Each player** sacrifices all lands they control
    **instead** if there are seven or more cards in your graveyard." The
    replacement names somebody else outright: every land on both sides goes,
    creatures stay, and the one-land sacrifice does not happen as well — the
    targeted player loses three lands, not four of a larger board's."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=7)
    for _ in range(3):
        _w1g2_put(game, 0, lea["Forest"])
        _w1g2_put(game, 1, lea["Island"])
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_from_hand(0, "Epicenter", target_player_index=1).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g2_names(game, 0) == ["Grizzly Bears"]
    assert _w1g2_names(game, 1) == ["Grizzly Bears"]
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs)
    assert len(game.players[1].graveyard) == 3
    assert len(game.players[0].graveyard) == 7 + 3 + 1
    assert sum("sacrificed" in line for line in game.log) == 2


def test_epicenter_still_announces_its_target_player_at_threshold(set_pool):
    """The target is chosen as the spell is cast (CR 601.2c), when nobody
    knows which sentence will run: the picker offers players whichever the
    graveyard says, and a permanent is not a legal announcement."""
    lea = set_pool("LEA")
    card = set_pool("ODY")["Epicenter"]
    for graveyard in (0, 7):
        game = _w1g2_duel(set_pool, ["Epicenter"], graveyard=graveyard)
        island = _w1g2_put(game, 1, lea["Island"])
        spec = game.cast_target_spec(0, card)
        assert spec["requires_target"], graveyard
        assert {entry["kind"] for entry in spec["valid_targets"]} == {"player"}
        refused = game.queue_from_hand(
            0, "Epicenter", target_permanent_ids=[island.permanent_id],
        )
        assert not refused.supported, (graveyard, refused.details)
        assert game.players[0].hand == [card]


# ---------------------------------------------------------------------------
# Kirtar's Wrath
# ---------------------------------------------------------------------------

def _w1g2_wrath_board(set_pool, graveyard):
    """Kirtar's Wrath in hand over a board with a regeneration shield up on
    the opponent's Drudge Skeletons."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Kirtar's Wrath"], graveyard=graveyard)
    mine = _w1g2_put(game, 0, lea["Grizzly Bears"])
    theirs = _w1g2_put(game, 1, lea["Craw Wurm"])
    skeletons = _w1g2_put(game, 1, lea["Drudge Skeletons"])
    assert game.activate_permanent_ability(1, "Drudge Skeletons").supported
    return game, (mine, theirs, skeletons)  # _w1g2_wrath_board


@_w1g2_pytest.mark.parametrize("graveyard, spirits", [(6, 0), (7, 2)])
def test_kirtars_wrath_destroys_everything_and_regeneration_does_not_help(
    set_pool, graveyard, spirits,
):
    """"Destroy all creatures. They can't be regenerated. / Threshold — If
    there are seven or more cards in your graveyard, **instead** destroy all
    creatures, then create two 1/1 white Spirit creature tokens with flying.
    Creatures destroyed this way can't be regenerated." Either way every
    creature dies and a regeneration shield is no answer (CR 701.19c); at
    threshold two Spirits arrive *after* the sweep and survive it."""
    game, creatures = _w1g2_wrath_board(set_pool, graveyard)

    assert game.cast_from_hand(0, "Kirtar's Wrath").supported

    assert not any(game.is_on_battlefield(creature) for creature in creatures)
    assert _w1g2_names(game, 1) == []
    tokens = list(game.controlled_by(0))
    assert len(tokens) == spirits
    for token in tokens:
        assert token.card.name == "Spirit Token"
        assert (token.effective_power, token.effective_toughness) == (1, 1)
        assert set(token.effective_colors) == {"W"}
        assert game._has_keyword(token, "flying")
    assert sum("were destroyed" in line for line in game.log) == 1, "one sweep, not two"


def test_kirtars_wrath_marks_the_replacing_sweep_unregenerable_too(set_pool):
    """The rider is printed twice, once per sentence, and each has to reach
    its own sweep: "Creatures destroyed this way can't be regenerated" follows
    a "…, then create …" sentence, so it marks the destroy inside it. Read
    onto the replaced arm alone, the threshold sweep could be regenerated
    from."""
    program = _w1g2_compile(set_pool("ODY")["Kirtar's Wrath"])
    (gate,) = program.instructions
    assert gate.kind == "if_then"
    then, otherwise = gate.payload["then"], gate.payload["else"]
    assert [step.kind for step in then] == ["destroy_all_creatures", "create_token"]
    assert [step.kind for step in otherwise] == ["destroy_all_creatures"]
    assert then[0].payload.get("bypass_regeneration") is True
    assert otherwise[0].payload.get("bypass_regeneration") is True
    assert then[1].payload["count"] == 2


def test_both_threshold_sorceries_compile_every_printed_sentence(set_pool):
    """Neither is supported on its first sentence alone: the whole card is
    one conditional whose condition is the graveyard count."""
    ody = set_pool("ODY")
    for name in ("Epicenter", "Kirtar's Wrath"):
        program = _w1g2_compile(ody[name])
        assert program.supported, name
        assert [i.kind for i in program.instructions] == ["if_then"], name
        assert program.instructions[0].payload["condition"]["value"] == 7

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

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
