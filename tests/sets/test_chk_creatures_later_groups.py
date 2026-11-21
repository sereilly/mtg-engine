"""Champions of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    declare_attack as _w1g8_declare_attack,
    drive_combat as _w1g8_drive_combat,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel without a beginning phase run (so no
    upkeep trigger of theirs has fired), libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


# --- Shisato, Whispering Hunter ---------------------------------------------
# "Whenever Shisato deals combat damage to a player, that player skips their
# next untap step." The seat is the one the damage event froze (CR 603.10),
# and the skip is CR 614.10's one-shot: spent by the damaged player's next
# untap step, never by Shisato's controller's.


def test_w1g8_shisato_skips_the_damaged_players_next_untap_step(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (hunter,), (bear,) = _w1g8_table([shisato], [bears])
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 18
    hunter.tapped = True
    bear.tapped = True

    game.start_turn(1)
    _w1g8_settle(game)
    assert bear.tapped, game.log[-6:]
    assert "P2 skips their untap step" in game.log
    # Shisato's controller's untap step was not the one named.
    game.start_turn(0)
    _w1g8_settle(game)
    assert not hunter.tapped
    # Spent once: the damaged player's next untap step happens.
    game.start_turn(1)
    assert not bear.tapped


def test_w1g8_a_blocked_shisato_skips_nothing(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    wall = set_pool("LEA")["Wall of Stone"]
    game, _, _ = _w1g8_table([shisato], [wall])
    _w1g8_declare_attack(game, 0, blocks={0: 0})
    _w1g8_drive_combat(game)
    assert game.players[1].life == 20
    assert not game.skip_step_counts


def test_w1g8_shisato_sacrifices_a_snake_at_its_controllers_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice a Snake." Shisato is a
    Snake itself, so alone it is the one sacrificed."""
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    game, (hunter,), _ = _w1g8_table([shisato], [])
    game.start_turn(1)
    _w1g8_settle(game)
    assert game.is_on_battlefield(hunter)
    game.start_turn(0)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(hunter)
    assert shisato in game.players[0].graveyard


# --- Dosan the Falling Leaf ---------------------------------------------------
# "Players can cast spells only during their own turns." CR 601.3a on every
# battlefield's seats alike (its controller too), casting alone: the ruling
# (2004-12-01) — "It doesn't stop activated or triggered abilities."


def test_w1g8_dosan_stops_casting_on_another_players_turn(set_pool):
    from engine.cast_prohibitions import cast_prohibition

    dosan = set_pool("CHK")["Dosan the Falling Leaf"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, _, _ = _w1g8_table([], [dosan], hand=[bolt], opponent_hand=[bolt])
    # Seat 0's own turn: its instant is cast.
    assert cast_prohibition(game, 0, bolt) is None
    # On seat 0's turn the Dosan's own controller is bound as well.
    refused = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported
    assert "another player's turn" in refused.details
    assert game.players[0].life == 20
    assert [card.name for card in game.players[1].hand] == ["Lightning Bolt"]

    game.active_player_index = 1
    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Lightning Bolt"]
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_settle(game)
    assert game.players[0].life == 17


def test_w1g8_dosan_leaves_activated_abilities_alone(set_pool):
    dosan = set_pool("CHK")["Dosan the Falling Leaf"]
    sorcerer = set_pool("LEA")["Prodigal Sorcerer"]
    game, _, _ = _w1g8_table([sorcerer], [dosan])
    game.active_player_index = 1
    used = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.players[1].life == 19


# --- Frostwielder, Kumano's Pupils, Kumano, Master Yamabushi -------------------
# "If a creature dealt damage by this creature [Kumano] this turn would die,
# exile it instead." A static replacement of the damager (CR 614.1a), read
# off the turn's damage ledger at the death: by any means for the rest of the
# turn (CR 700.4), only while the source is on the battlefield — "even if
# it's going to the graveyard at the same time" (the 2004-12-01 rulings).


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


def test_w1g8_frostwielder_exiles_what_its_ping_kills(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    elves = set_pool("LEA")["Llanowar Elves"]
    game, _, (elf,) = _w1g8_table([frost], [elves])
    used = game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[elf.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_frostwielder_exiles_a_damaged_creature_destroyed_later_that_turn(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    game, _, (hill,) = _w1g8_table([frost], [giant], hand=[terror])
    assert game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.is_on_battlefield(hill)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]


def test_w1g8_frostwielder_must_be_on_the_battlefield_when_the_creature_dies(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    unsummon = set_pool("LEA")["Unsummon"]
    game, (wielder,), (hill,) = _w1g8_table(
        [frost], [giant], hand=[unsummon, terror]
    )
    assert game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(
        0, "Unsummon", target_permanent_ids=[wielder.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "exile") == []


def test_w1g8_frostwielder_does_not_exile_what_another_source_damaged(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    elves = set_pool("LEA")["Llanowar Elves"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, _, (elf,) = _w1g8_table([frost], [elves], hand=[bolt])
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[elf.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Llanowar Elves"]


def test_w1g8_kumanos_pupils_exiles_the_blocker_it_trades_with(set_pool):
    """The ruling: "even if it's going to the graveyard at the same time as
    Kumano's Pupils" — one state-based check, both seats swept, the Pupils'
    seat first."""
    pupils = set_pool("CHK")["Kumano's Pupils"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, _ = _w1g8_table([pupils], [giant])
    _w1g8_declare_attack(game, 0, blocks={0: 0})
    _w1g8_drive_combat(game)
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Kumano's Pupils"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_kumano_names_itself(set_pool):
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    elves = set_pool("LEA")["Llanowar Elves"]
    game, _, (elf,) = _w1g8_table([kumano], [elves])
    assert game.activate_permanent_ability(
        0, "Kumano, Master Yamabushi", target_permanent_ids=[elf.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]


def test_w1g8_wicked_akuba_targets_only_a_player_it_damaged_this_turn(set_pool):
    """"{B}: Target player dealt damage by this creature this turn loses 1
    life." The narrowing is the picker's (CR 601.2c), read off the turn's
    damage ledger from this Akuba to the seat."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    akuba = set_pool("CHK")["Wicked Akuba"]
    ability = compile_card_oracle(akuba).activated_abilities[0]
    assert derive_activation_spec(ability) == {
        "kind": "player", "did": {"kind": "dealt_damage_by_source_this_turn"},
    }
    game, _, _ = _w1g8_table([akuba], [])
    refused = game.activate_permanent_ability(0, "Wicked Akuba", target_player_index=1)
    assert not refused.supported
    assert game.players[1].life == 20

    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 18
    used = game.activate_permanent_ability(0, "Wicked Akuba", target_player_index=1)
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.players[1].life == 17
    # Its own controller was dealt nothing by it.
    assert not game.activate_permanent_ability(
        0, "Wicked Akuba", target_player_index=0
    ).supported

    # The window is the turn: the next one starts with an empty ledger.
    game.start_turn(1)
    _w1g8_settle(game)
    assert not game.activate_permanent_ability(
        0, "Wicked Akuba", target_player_index=1
    ).supported


def test_w1g8_the_dealt_damage_exile_reads_only_a_line_about_itself():
    """The subject is the card itself — "this creature" or its own name (CR
    201.5, the legend's short name included) — never another card's."""
    from engine.replacements import replacement_claims_line
    from engine.replacements.zone_changes import dealt_damage_exile_line

    line = "If a creature dealt damage by Kumano this turn would die, exile it instead."
    assert dealt_damage_exile_line(line, "Kumano, Master Yamabushi")
    assert replacement_claims_line(line, "Kumano, Master Yamabushi")
    assert not dealt_damage_exile_line(line, "Frostwielder")
    assert not replacement_claims_line(line)
    assert dealt_damage_exile_line(
        "If a creature dealt damage by this creature this turn would die, exile it instead."
    )

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
