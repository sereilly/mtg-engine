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


# --- Horobi, Death's Wail -----------------------------------------------------
# "Whenever a creature becomes the target of a spell or ability, destroy that
# creature." The targeted permanent is the object the becomes-target event
# froze (CR 603.2, 603.10); the ruling (2023-04-14): "If the creature is the
# only target of the spell or ability, that spell or ability won't resolve."


def test_w1g8_horobi_destroys_a_creature_a_spell_targets(set_pool):
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    bears = set_pool("LEA")["Grizzly Bears"]
    growth = set_pool("LEA")["Giant Growth"]
    game, (bear,), (wail,) = _w1g8_table([bears], [horobi], hand=[growth])
    queued = game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    )
    assert queued.supported, queued.details
    # The trigger sits above the spell that set it off.
    assert [(item.card.name, item.ability_kind) for item in game.stack] == [
        ("Giant Growth", None), ("Horobi, Death's Wail", "triggered"),
    ]
    _w1g8_settle(game)
    assert not game.is_on_battlefield(bear)
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Grizzly Bears", "Giant Growth"]
    assert any("every target is illegal" in line for line in game.log)
    assert game.is_on_battlefield(wail)


def test_w1g8_horobis_trigger_resolves_after_horobi_has_left(set_pool):
    """The trigger is independent of its source once on the stack (CR
    113.7a): Horobi sacrificed in response still destroys the creature."""
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    bears = set_pool("LEA")["Grizzly Bears"]
    growth = set_pool("LEA")["Giant Growth"]
    game, (bear,), (wail,) = _w1g8_table([bears], [horobi], hand=[growth])
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    ).supported
    game.sacrifice_permanent(wail)
    assert not game.is_on_battlefield(wail)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(bear)


def test_w1g8_horobi_sees_an_abilitys_target_and_ignores_a_players(set_pool):
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    sorcerer = set_pool("LEA")["Prodigal Sorcerer"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (_, hill) = _w1g8_table([sorcerer], [horobi, giant])
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1
    ).supported
    _w1g8_settle(game)
    assert game.players[1].life == 19 and game.is_on_battlefield(hill)
    game.start_turn(0)
    _w1g8_settle(game)
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(hill)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Hill Giant"]
    assert any("every target is illegal" in line for line in game.log)


# --- Masako the Humorless -----------------------------------------------------
# "Tapped creatures you control can block as though they were untapped." CR
# 509.1a's untapped requirement waived for its controller's creatures, and
# nothing else (the 2004-12-01 ruling: "only if they could otherwise block").


def _w1g8_to_blocks(game):
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [
        slot for slot, perm in enumerate(game.players[0].battlefield)
        if perm.is_creature
    ]
    ok, why = game.declare_attackers(0, attackers, defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step


def _w1g8_slot(game, seat, permanent):
    return next(
        slot for slot, perm in enumerate(game.players[seat].battlefield)
        if perm is permanent
    )


def test_w1g8_masako_lets_a_tapped_creature_block(set_pool):
    masako = set_pool("CHK")["Masako the Humorless"]
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, (hill,), (_, wurm) = _w1g8_table([giant], [masako, craw])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert ok, why
    _w1g8_drive_combat(game)
    assert not game.is_on_battlefield(hill)
    assert game.players[1].life == 20
    # Blocking does not untap it.
    assert wurm.tapped and wurm.damage_marked == 3


def test_w1g8_without_masako_a_tapped_creature_cannot_block(set_pool):
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, _, (wurm, bear) = _w1g8_table([giant], [craw, bears])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert not ok and "is tapped" in why


def test_w1g8_masako_waives_nothing_but_the_untapped_requirement(set_pool):
    """Its controller's creatures only, and a tapped creature still can't
    block what it otherwise couldn't (a flier)."""
    masako = set_pool("CHK")["Masako the Humorless"]
    roc = set_pool("LEA")["Mahamoti Djinn"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (_, wurm) = _w1g8_table([roc], [masako, craw])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, _why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert not ok

    # An opponent's Masako lends nothing.
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (wurm2,) = _w1g8_table([giant, masako], [craw])
    wurm2.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm2): 0})
    assert not ok and "is tapped" in why


def test_w1g8_the_ai_blocks_with_a_tapped_creature_under_masako(set_pool):
    from engine.ai_declarations import choose_combat_blockers

    masako = set_pool("CHK")["Masako the Humorless"]
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (sage, wurm) = _w1g8_table([giant], [masako, craw])
    sage.tapped = True
    wurm.tapped = True
    _w1g8_to_blocks(game)
    blocks = choose_combat_blockers(game, 1)
    assert _w1g8_slot(game, 1, wurm) in blocks, blocks


# --- Sosuke, Son of Seshiro ---------------------------------------------------
# "Whenever a Warrior you control deals combat damage to a creature, destroy
# that creature at end of combat." The creature dealt damage (the only thing
# "that creature" can name beside "a Warrior"), destroyed by a delayed
# triggered ability as the end of combat step begins (CR 603.7, 511.2).


def test_w1g8_sosuke_destroys_what_a_warrior_hit_at_end_of_combat(set_pool):
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    ranger = set_pool("CHK")["Orochi Ranger"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, (_, scout), (wurm,) = _w1g8_table([sosuke, ranger], [craw])
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [_w1g8_slot(game, 0, scout)], defending_player_index=1
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, scout)})[0]
    # In the combat damage step: dealt, not yet destroyed.
    _w1g8_drive_combat(game, through="declare_blockers")
    assert wurm.damage_marked == 3 and game.is_on_battlefield(wurm)
    _w1g8_drive_combat(game)
    assert not game.is_on_battlefield(wurm)
    assert "Craw Wurm" in _w1g8_zone_names(game, 1, "graveyard")


def test_w1g8_sosuke_ignores_a_non_warrior_and_an_opponents_warrior(set_pool):
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    ranger = set_pool("CHK")["Orochi Ranger"]
    craw = set_pool("LEA")["Craw Wurm"]
    giant = set_pool("LEA")["Hill Giant"]
    # Sosuke itself is a Snake Warrior, so the non-Warrior is the Giant.
    game, (_, hill), (wurm,) = _w1g8_table([sosuke, giant], [craw])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [_w1g8_slot(game, 0, hill)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, hill)})[0]
    _w1g8_drive_combat(game)
    assert game.is_on_battlefield(wurm)

    # The opponent's Warrior blocking seat 0's creature fires nothing.
    game, (_, hill), (scout,) = _w1g8_table([sosuke, giant], [ranger])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [_w1g8_slot(game, 0, hill)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, hill)})[0]
    _w1g8_drive_combat(game)
    assert game.is_on_battlefield(hill)


# --- Kiki-Jiki, Mirror Breaker ------------------------------------------------
# "{T}: Create a token that's a copy of target nonlegendary creature you
# control, except it has haste. Sacrifice it at the beginning of the next end
# step." CR 707.9a's exception, part of the copiable values (CR 707.9b, the
# 2021-03-19 ruling: a copy of the token has haste too).


def test_w1g8_kiki_jiki_makes_a_hasty_copy_that_is_sacrificed_at_end_step(set_pool):
    from engine.copies import copiable_card

    kiki = set_pool("CHK")["Kiki-Jiki, Mirror Breaker"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (_, bear), _ = _w1g8_table([kiki, bears], [])
    used = game.activate_permanent_ability(
        0, "Kiki-Jiki, Mirror Breaker", target_permanent_ids=[bear.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    tokens = [
        p for p in game.controlled_by(game.players[0]) if p.metadata.get("is_token")
    ]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.effective_card.name == "Grizzly Bears"
    assert (token.effective_power, token.effective_toughness) == (2, 2)
    assert token.has_keyword("haste")
    assert game.can_attack(token, 1) and not game._is_summoning_sick(token)
    # The haste is a copiable value of the token (CR 707.9b).
    assert "Haste" in copiable_card(token).oracle_text.splitlines()
    # The original is untouched.
    assert not bear.has_keyword("haste")

    game._set_phase_and_step("ending", "end")
    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(token)
    assert game.is_on_battlefield(bear)


def test_w1g8_kiki_jiki_cannot_copy_a_legendary_or_an_opponents_creature(set_pool):
    kiki = set_pool("CHK")["Kiki-Jiki, Mirror Breaker"]
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (_, legend), (theirs,) = _w1g8_table([kiki, sosuke], [bears])
    for chosen in (legend, theirs):
        refused = game.activate_permanent_ability(
            0, "Kiki-Jiki, Mirror Breaker", target_permanent_ids=[chosen.permanent_id]
        )
        assert not refused.supported
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())


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

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), library=("Island",) * 12):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card(n) for n in library]),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = []
    for name in mine:
        permanent = _W1G9Permanent(card=card(name))
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed


def test_w1g9_godo_fetches_an_equipment_as_it_enters(set_pool):
    """"When Godo enters, you may search your library for an Equipment card,
    put it onto the battlefield, then shuffle." Cast, the entry trigger finds
    Tenza among the lands and puts it onto the battlefield."""
    game, _mine = _w1g9_table(
        set_pool, hand=["Godo, Bandit Warlord"],
        library=("Island", "Tenza, Godo's Maul", "Island", "Island"),
    )
    assert game.cast_from_hand(0, "Godo, Bandit Warlord").supported
    _w1g9_settle(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == ["Godo, Bandit Warlord", "Tenza, Godo's Maul"]
    assert "Tenza, Godo's Maul" not in [c.name for c in game.players[0].library]


def test_w1g9_godo_untaps_samurai_and_adds_a_combat_only_on_its_first_attack(set_pool):
    """"Whenever Godo attacks for the first time each turn, untap it and all
    Samurai you control. After this phase, there is an additional combat
    phase." (CR 500.8; no extra main phase, the 2020-08-07 ruling.) Godo and a
    tapped Samurai untap, a tapped Bear does not, and the turn's second combat
    follows the first; Godo attacking again there sets nothing off."""
    game, mine = _w1g9_table(
        set_pool, mine=["Godo, Bandit Warlord", "Kitsune Blademaster", "Grizzly Bears"],
    )
    godo, blademaster, bears = mine
    blademaster.tapped = True
    bears.tapped = True
    alice, bob = game.players
    game._set_phase_and_step("combat", "declare_attackers")
    slot = [p.permanent_id for p in alice.battlefield].index(godo.permanent_id)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert not godo.tapped and not blademaster.tapped and bears.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17
    assert game.current_turn_phase == "combat", "the additional combat phase"

    _w1g9_drive_combat(game, through="beginning_of_combat")
    assert game.current_step == "declare_attackers"
    slots = [
        i for i, p in enumerate(alice.battlefield) if p.is_creature and not p.tapped
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert game.stack == [] and godo.tapped and blademaster.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17 - 3 - 2
    assert game.current_turn_phase == "postcombat_main"

# ==== end w1g9 ======================================================
