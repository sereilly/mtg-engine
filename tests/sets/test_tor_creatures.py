"""Torment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import (
    _nosick as _w1g7_nosick, declare_attack as _w1g7_declare_attack,
    resolve_stack as _w1g7_resolve_stack,
)


def _w1g7_illusionist_board(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    illusionist = _w1g7_nosick(_w1g7_Permanent(card=tor["Cephalid Illusionist"]))
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    giant = _w1g7_Permanent(card=lea["Hill Giant"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", battlefield=[illusionist, ogre],
            library=[lea[n] for n in ("Forest", "Island", "Swamp", "Plains", "Mountain")],
        ),
        _w1g7_PlayerState(name="P1", battlefield=[giant]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, illusionist, ogre, giant


def test_w1g7_cephalid_illusionist_targets_only_a_creature_you_control(set_pool):
    """"…target creature **you control**": the picker offers the caster's two
    creatures and not the opponent's, and naming the opponent's Giant is
    refused with nothing paid (CR 602.2b/601.2c)."""
    game, illusionist, ogre, giant = _w1g7_illusionist_board(set_pool)
    spec = game.activation_target_spec(0, 0, 0)
    assert {entry["name"] for entry in spec["valid_targets"]} == {
        "Cephalid Illusionist", "Gray Ogre",
    }
    refused = game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert not illusionist.tapped and not game.stack


def test_w1g7_cephalid_illusionist_targeting_itself_mills_three(set_pool):
    """Its own ability aimed at itself is "becomes the target of a spell or
    ability": three cards off its controller's library, and the shield is
    still armed when the ability resolves."""
    game, illusionist, _, _ = _w1g7_illusionist_board(set_pool)
    assert game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[illusionist.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Island", "Swamp"]
    assert len(game.players[0].library) == 2
    assert illusionist.tapped
    assert any(
        "dealt to and dealt by Cephalid Illusionist" in line for line in game.log
    )


def test_w1g7_cephalid_illusionist_shields_both_ends_of_a_fight(set_pool):
    """"Prevent all combat damage that would be dealt to **and dealt by**
    target creature you control this turn." The shielded Ogre is blocked by a
    Hill Giant: neither is dealt any damage."""
    game, illusionist, ogre, giant = _w1g7_illusionist_board(set_pool)
    assert game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[ogre.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert game.players[0].graveyard == []   # the Ogre is not the Illusionist
    # The Illusionist is tapped; only the Ogre attacks, and the Giant blocks it.
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [1], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 1})
    assert ok, why
    game.resolve_combat_damage(0)
    assert ogre.damage_marked == 0 and giant.damage_marked == 0
    assert ogre in game.players[0].battlefield and giant in game.players[1].battlefield


def _w1g7_snitch_board(set_pool):
    """Seat 0: Cephalid Snitch and two Terrors. Seat 1: a White Knight
    (protection from black)."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    snitch = _w1g7_nosick(_w1g7_Permanent(card=tor["Cephalid Snitch"]))
    knight = _w1g7_nosick(_w1g7_Permanent(card=lea["White Knight"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[snitch], hand=[lea["Terror"]] * 2),
        _w1g7_PlayerState(name="P1", battlefield=[knight]),
    ])
    game.enforce_mana_costs = False
    return game, snitch, knight


def test_w1g7_cephalid_snitch_takes_protection_from_black_away(set_pool):
    """"Sacrifice this creature: Target creature loses protection from black
    until end of turn." The White Knight's printed protection was read off its
    line and the removal never asked, so the log said it lost the ability and
    a Terror still could not target it. Now it can."""
    game, snitch, knight = _w1g7_snitch_board(set_pool)
    refused = game.cast_from_hand(0, "Terror", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert snitch not in game.players[0].battlefield
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[knight.permanent_id]).supported
    _w1g7_resolve_stack(game)
    assert knight not in game.players[1].battlefield


def test_w1g7_cephalid_snitch_loss_ends_with_the_turn(set_pool):
    """Until end of turn: after cleanup the Knight has its protection back."""
    game, _, knight = _w1g7_snitch_board(set_pool)
    game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    )
    _w1g7_resolve_stack(game)
    assert ("color", "B") not in game._protection_qualities(knight)
    game.resolve_cleanup_step(0)
    assert ("color", "B") in game._protection_qualities(knight)


def test_w1g7_a_protection_granted_after_the_loss_stays(set_pool):
    """CR 613.7: the later effect wins. Protection from black granted after
    the Snitch's removal (Floating Shield's sacrifice, black named) is kept;
    the printed one, older than the removal, is not."""
    from engine.keywords import grant_protection_flag

    game, _, knight = _w1g7_snitch_board(set_pool)
    game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    )
    _w1g7_resolve_stack(game)
    assert ("color", "B") not in game._protection_qualities(knight)
    grant_protection_flag(knight, "black")
    assert ("color", "B") in game._protection_qualities(knight)


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
