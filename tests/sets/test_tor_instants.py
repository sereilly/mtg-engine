"""Torment instants.

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
    _damage_dealt as _w1g7_damage_dealt, _nosick as _w1g7_nosick,
    resolve_stack as _w1g7_resolve_stack,
)


def _w1g7_equal_treatment_board(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    giant = _w1g7_nosick(_w1g7_Permanent(card=lea["Hill Giant"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", hand=[tor["Equal Treatment"], lea["Lightning Bolt"]],
            library=[lea["Forest"]] * 3,
        ),
        _w1g7_PlayerState(name="P1", battlefield=[giant]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    assert game.cast_from_hand(0, "Equal Treatment").supported
    _w1g7_resolve_stack(game)
    return game, giant


def test_w1g7_equal_treatment_makes_every_damage_event_two(set_pool):
    """"If any source would deal 1 or more damage to a permanent or player this
    turn, it deals 2 damage to that permanent or player instead. Draw a card."
    A Bolt to the face deals 2; 7 to a player and 1 to a creature are both 2
    (CR 120.4b, the damage dealt); the card is drawn."""
    game, giant = _w1g7_equal_treatment_board(set_pool)
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt", "Forest"]
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    assert game.players[1].life == 18
    assert "3 damage becomes 2 (Equal Treatment)" in game.log
    assert _w1g7_damage_dealt(game, game.players[1], 7) == 2
    assert _w1g7_damage_dealt(game, giant, 1) == 2
    assert _w1g7_damage_dealt(game, giant, 1, combat=True) == 2


def test_w1g7_equal_treatment_ends_with_the_turn(set_pool):
    """"This turn": the record is on its caster's seat and the cleanup step's
    one sweep ends it (CR 514.2)."""
    game, giant = _w1g7_equal_treatment_board(set_pool)
    game.resolve_cleanup_step(0)
    assert _w1g7_damage_dealt(game, game.players[1], 7) == 7
    assert _w1g7_damage_dealt(game, giant, 1) == 1


def test_w1g7_equal_treatment_and_a_shield_contend_by_cr_616(set_pool):
    """One contention set with the prevention shields (CR 616.1): by default
    the 2 is set first, so Hypochondria's "prevent the next 3" absorbs all of
    a 5 — and its last point still stops a later 1, which Equal Treatment has
    made a 2, to 1."""
    game, _ = _w1g7_equal_treatment_board(set_pool)
    target = game.players[1]
    game.players[1].battlefield.append(
        _w1g7_Permanent(card=set_pool("TOR")["Hypochondria"])
    )
    assert game.activate_permanent_ability(
        1, "Hypochondria", target_player_index=1, permanent_index=1,
        ability_index=1,
    ).supported
    _w1g7_resolve_stack(game)
    assert _w1g7_damage_dealt(game, target, 5) == 0
    assert _w1g7_damage_dealt(game, target, 1) == 1
    assert _w1g7_damage_dealt(game, target, 1) == 2


def _w1g7_plagiarize_board(set_pool, *, p0=("Plagiarize",), p1=(), p1_library=5):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", hand=[tor[n] for n in p0], library=[lea["Forest"]] * 5,
        ),
        _w1g7_PlayerState(
            name="P1", hand=[tor[n] for n in p1],
            library=[lea["Island"]] * p1_library,
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g7_hands(game):
    return [[c.name for c in player.hand] for player in game.players]


def test_w1g7_plagiarize_gives_each_of_a_players_draws_to_its_caster(set_pool):
    """"Until end of turn, if target player would draw a card, instead that
    player skips that draw and you draw a card." Two draws by P1 are two
    replaced draws (CR 121.2): P0 draws both, P1 none."""
    game = _w1g7_plagiarize_board(set_pool)
    assert game.cast_from_hand(0, "Plagiarize", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 2)
    assert _w1g7_hands(game) == [["Forest", "Forest"], []]
    assert [len(p.library) for p in game.players] == [3, 5]
    assert game.log.count("P1 skips a draw and P0 draws instead (Plagiarize)") == 2


def test_w1g7_two_plagiarizes_cast_at_each_other_cancel_out(set_pool):
    """The 2007-07-15 ruling: "the two spells effectively cancel each other
    out". P1's draw goes to P0, whose substitute draw the second Plagiarize
    hands back to P1 — and that one has been through both (CR 614.5)."""
    game = _w1g7_plagiarize_board(set_pool, p1=("Plagiarize",))
    game.cast_from_hand(0, "Plagiarize", target_player_index=1)
    _w1g7_resolve_stack(game)
    game.cast_from_hand(1, "Plagiarize", target_player_index=0)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1)
    assert _w1g7_hands(game) == [[], ["Island"]]
    game._draw_with_replacements(game.players[0], 1)
    assert _w1g7_hands(game) == [["Forest"], ["Island"]]


def test_w1g7_plagiarize_aimed_at_its_caster_does_nothing(set_pool):
    """The 2004-10-04 ruling: no loop, because the draw it makes is the one it
    may not replace (CR 614.5)."""
    game = _w1g7_plagiarize_board(set_pool)
    game.cast_from_hand(0, "Plagiarize", target_player_index=0)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[0], 1)
    assert _w1g7_hands(game) == [["Forest"], []]


def test_w1g7_plagiarize_spares_an_empty_library_until_cleanup(set_pool):
    """The 2007-07-15 ruling on an empty library: the target's draw is replaced,
    so they never draw from it and do not lose (CR 704.5b). After the cleanup
    sweep the next draw is their own, and it loses them the game."""
    game = _w1g7_plagiarize_board(set_pool, p1_library=0)
    game.cast_from_hand(0, "Plagiarize", target_player_index=1)
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1)
    game.check_state_based_actions()
    assert not game.players[1].lost
    assert _w1g7_hands(game) == [["Forest"], []]
    game.resolve_cleanup_step(0)
    game._draw_with_replacements(game.players[1], 1)
    game.check_state_based_actions()
    assert game.players[1].lost


def test_w1g7_plagiarize_takes_the_draw_step_draw(set_pool):
    """A turn-based draw is a draw (CR 504.1): cast in P1's upkeep, it takes
    P1's draw-step card."""
    game = _w1g7_plagiarize_board(set_pool)
    game.active_player_index = 1
    game._set_phase_and_step("beginning", "upkeep")
    assert game.cast_from_hand(0, "Plagiarize", target_player_index=1).supported
    _w1g7_resolve_stack(game)
    game._draw_with_replacements(game.players[1], 1, turn_based=True)
    assert _w1g7_hands(game) == [["Forest"], []]


def _w1g7_spirit_flare_board(set_pool, *, from_graveyard=False):
    """Seat 1's Gray Ogre attacking seat 0, who holds Spirit Flare and an
    untapped Hill Giant (3 power)."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    flare = tor["Spirit Flare"]
    giant = _w1g7_nosick(_w1g7_Permanent(card=lea["Hill Giant"]))
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", battlefield=[giant],
            hand=[] if from_graveyard else [flare],
            graveyard=[flare] if from_graveyard else [],
        ),
        _w1g7_PlayerState(name="P1", battlefield=[ogre]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    return game, flare, giant, ogre


def _w1g7_flare_roles(giant, ogre):
    return [{"permanent_id": giant.permanent_id}, {"permanent_id": ogre.permanent_id}]


def test_w1g7_spirit_flare_bites_with_the_creature_it_tapped(set_pool):
    """"Tap target untapped creature you control. If you do, it deals damage
    equal to its power to target attacking or blocking creature an opponent
    controls." "It" is the tapped Giant — a spell has no source to bite with,
    which is what the card did before: tapped its creature and dealt nothing."""
    game, _, giant, ogre = _w1g7_spirit_flare_board(set_pool)
    spec = game.cast_target_spec(0, set_pool("TOR")["Spirit Flare"])
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Hill Giant"]
    assert [entry["name"] for entry in spec["valid_targets"][0]["next"]] == ["Gray Ogre"]
    assert game.cast_from_hand(
        0, "Spirit Flare", target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    _w1g7_resolve_stack(game)
    assert giant.tapped
    assert "Hill Giant deals 3 damage to Gray Ogre" in game.log
    assert ogre not in game.players[1].battlefield


def test_w1g7_spirit_flare_does_nothing_if_its_creature_is_tapped_in_response(set_pool):
    """"If you do": the Giant tapped in response is no longer "untapped" — an
    illegal target as the spell resolves (CR 608.2b) — so it is not tapped by
    the spell and deals no damage (the 2004-10-04 ruling: "If either target is
    illegal when the spell resolves, it will do no damage")."""
    game, _, giant, ogre = _w1g7_spirit_flare_board(set_pool)
    assert game.queue_from_hand(
        0, "Spirit Flare", target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    game.become_tapped(giant)
    _w1g7_resolve_stack(game)
    assert ogre in game.players[1].battlefield and ogre.damage_marked == 0
    assert not any("deals 3 damage" in line for line in game.log)


def test_w1g7_spirit_flare_flashback_pays_mana_and_three_life(set_pool):
    """"Flashback—{1}{W}, Pay 3 life." From the graveyard for exactly that, the
    same bite, and the card is exiled."""
    game, flare, giant, ogre = _w1g7_spirit_flare_board(set_pool, from_graveyard=True)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["W"] = 2
    assert game.cast_from_hand(
        0, "Spirit Flare", from_zone="graveyard",
        target_role_refs=_w1g7_flare_roles(giant, ogre),
    ).supported
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 17
    assert game.players[0].exile == [flare]
    assert ogre not in game.players[1].battlefield


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
