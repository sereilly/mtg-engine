"""Onslaught creatures (legendary ones too) — wave 1's groups W1G9 to W1G13.

Moved whole, section by section, out of `test_ons_creatures_later_groups.py`
when that file passed the 2,600-line cap at wave 1's close (each section
carries its own imports, so a move is exact). Earlier groups' sections stay there.

The set prints 174 creatures: W1G1 and W1G2 wrote in `test_ons_creatures.py`,
W1G3 to W1G8 in `test_ons_creatures_later_groups.py`, W1G9 to W1G13 here.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve


def _w1g9_table(seats=2):
    """*seats* players, seat 0 active, mana costs off."""
    w1g9_game = _w1g9_Game(
        players=[_w1g9_PlayerState(name=f"W1G9-{index}") for index in range(seats)]
    )
    w1g9_game.enforce_mana_costs = False
    w1g9_game.active_player_index = 0
    return w1g9_game


def _w1g9_enter(game, seat, card):
    """*card* onto *seat*'s battlefield through the entry seam, unsick, with
    its entry triggers (if any) resolved."""
    w1g9_entered = _w1g9_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g9_entered, None)
    w1g9_entered.metadata["summoning_sickness_turn"] = -99
    game.check_state_based_actions()
    _w1g9_resolve(game)
    return w1g9_entered


def _w1g9_attack(game, attackers, *, seat=0, defender=1):
    game._set_phase_and_step("combat", "declare_attackers")
    return game.declare_attackers(
        seat, [game.battlefield_index_of(a) for a in attackers],
        defending_player_index=defender,
    )


def _w1g9_block(game, blocks, *, seat=1):
    """``(blocker, [attackers])`` pairs for *seat*; the engine's answer."""
    game._set_phase_and_step("combat", "declare_blockers")
    return game.declare_blockers(seat, {
        game.battlefield_index_of(blocker): [
            game.battlefield_index_of(a) for a in attackers
        ]
        for blocker, attackers in blocks
    })


def _w1g9_settle(game):
    """Drain the stack, then answer what it left owed with the defaults, and
    make the state check the priority loop makes after a resolution
    (CR 704.3)."""
    _w1g9_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g9_resolve(game)
    game.check_state_based_actions()


def test_w1g9_gustcloak_savior_rescues_another_creature_you_control(set_pool):
    """"Whenever a creature you control becomes blocked, you may untap that
    creature and remove it from combat." The creature the event was about —
    not the Savior — is untapped and taken out of combat (CR 506.4), so it
    deals and takes no combat damage.
    """
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    savior = _w1g9_enter(game, 0, ons["Gustcloak Savior"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    assert _w1g9_attack(game, [seeker])[0]
    assert seeker.tapped and seeker.attacking
    assert _w1g9_block(game, [(bears, [seeker])])[0]
    assert [item.card.name for item in game.stack] == ["Gustcloak Savior"]
    _w1g9_settle(game)
    assert not seeker.tapped
    assert not seeker.attacking and not seeker.blocked
    assert game.battlefield_index_of(seeker) not in game.combat_attackers
    assert not savior.attacking and not savior.tapped
    assert "Glory Seeker untapped (Gustcloak Savior)" in game.log

    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    assert seeker.damage_marked == 0 and bears.damage_marked == 0
    assert game.is_on_battlefield(seeker) and game.is_on_battlefield(bears)


def test_w1g9_gustcloak_savior_ignores_an_opponents_blocked_creature(set_pool):
    """"A creature **you control**": the watcher on the defending side has
    nothing to do when the attacker it would rescue is not its controller's.
    """
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    _w1g9_enter(game, 1, ons["Gustcloak Savior"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    assert _w1g9_attack(game, [seeker])[0]
    assert _w1g9_block(game, [(bears, [seeker])])[0]
    assert game.stack == []
    assert seeker.tapped and seeker.attacking and seeker.blocked


def test_w1g9_gustcloak_savior_declined_leaves_the_fight(set_pool):
    """The offer is optional: declined, the creature stays blocked and tapped
    and the fight happens."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    game.interactive_seats = {0}
    _w1g9_enter(game, 0, ons["Gustcloak Savior"])
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    assert _w1g9_attack(game, [seeker])[0]
    assert _w1g9_block(game, [(bears, [seeker])])[0]
    game.resolve_top_of_stack()
    offers = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert len(offers) == 1 and offers[0].player_index == 0
    game._resolve_optional_pay(offers[0], False, None)
    _w1g9_resolve(game)
    assert seeker.tapped and seeker.attacking and seeker.blocked


def test_w1g9_the_untap_reads_the_event_and_refuses_without_one():
    """"Untap that creature" is the event's object only under an event that
    froze one; elsewhere the words name nobody and the line refuses."""
    from engine.grammar import compile_line

    bound = compile_line(
        "Whenever a creature you control becomes blocked, untap that creature.",
        card_name="Probe",
    )
    assert [i.kind for i in bound.instructions] == ["untap_event_subject"]
    unbound = compile_line(
        "At the beginning of your upkeep, untap that creature.", card_name="Probe",
    )
    assert unbound.lowering_error or unbound.parse_error
    narrowed = compile_line(
        "Whenever a creature you control becomes blocked, untap that red creature.",
        card_name="Probe",
    )
    assert not narrowed.instructions


def test_w1g9_spitfire_handler_cant_block_a_bigger_creature(set_pool):
    """"This creature can't block creatures with power greater than this
    creature's power." Both powers are read now, through the layers: a 1/1
    can't block a 2/2, and pumped to 2/1 it can — the strict "greater than"
    admits the tie.
    """
    ons = set_pool("ONS")
    game = _w1g9_table()
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    handler = _w1g9_enter(game, 1, ons["Spitfire Handler"])
    assert _w1g9_attack(game, [seeker])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    refused = game.declare_blockers(1, {
        game.battlefield_index_of(handler): [game.battlefield_index_of(seeker)]
    })
    assert not refused[0]
    assert handler.blocking_attacker_controller is None

    game.activate_permanent_ability(1, "Spitfire Handler")
    _w1g9_resolve(game)
    assert (handler.effective_power, handler.effective_toughness) == (2, 1)
    assert _w1g9_block(game, [(handler, [seeker])])[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    assert not game.is_on_battlefield(handler)
    assert not game.is_on_battlefield(seeker)


def test_w1g9_the_ai_never_proposes_the_block_spitfire_handler_forbids(set_pool):
    """The restriction is asked by the AI's proposal, not only by the gate:
    a 1/1 Handler facing a lone 2/2 attacker is never offered as its blocker."""
    from engine.ai_declarations import choose_combat_blockers

    ons = set_pool("ONS")
    game = _w1g9_table()
    seeker = _w1g9_enter(game, 0, ons["Glory Seeker"])
    handler = _w1g9_enter(game, 1, ons["Spitfire Handler"])
    assert _w1g9_attack(game, [seeker])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert not game._can_block_attacker(handler, seeker)
    assert game.battlefield_index_of(handler) not in choose_combat_blockers(game, 1)


def test_w1g9_tephraderm_sends_a_spells_damage_to_its_controller(set_pool):
    """"Whenever a spell deals damage to this creature, this creature deals
    that much damage to that spell's controller." A Shock aimed at it costs
    its caster 2 life; only the spell line fires (Shock is no creature)."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    tephraderm = _w1g9_enter(game, 1, ons["Tephraderm"])
    game.players[0].hand.append(ons["Shock"])
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.cast_from_hand(
        0, "Shock", target_player_index=1, target_permanent_ids=[tephraderm.permanent_id]
    )
    _w1g9_settle(game)
    assert tephraderm.damage_marked == 2
    assert game.players[0].life == 18
    assert "Tephraderm dealt 2 damage to W1G9-0" in game.log


def test_w1g9_tephraderm_answers_lethal_spell_damage_from_the_graveyard(set_pool):
    """Ruling (2004-10-04): "The second ability triggers even if this card is
    dealt lethal damage." It deals the damage as it last existed (CR 608.2h)."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    tephraderm = _w1g9_enter(game, 1, ons["Tephraderm"])
    game.players[0].hand.extend([ons["Shock"], ons["Pinpoint Avalanche"]])
    game._set_phase_and_step("precombat_main", "precombat_main")
    for name in ("Shock", "Pinpoint Avalanche"):
        game.cast_from_hand(
            0, name, target_player_index=1,
            target_permanent_ids=[tephraderm.permanent_id],
        )
        _w1g9_settle(game)
    assert not game.is_on_battlefield(tephraderm)
    assert game.players[0].life == 20 - 2 - 4


def test_w1g9_tephraderm_hits_back_the_creature_that_hit_it(set_pool):
    """"Whenever a creature deals damage to this creature, this creature deals
    that much damage to that creature." Combat damage from a 6/6 it blocks
    kills Tephraderm and leaves the 6/6 with 4; the trigger deals 6 more. The
    spell line stays silent: combat damage is a creature's, not a spell's."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    tephraderm = _w1g9_enter(game, 1, ons["Tephraderm"])
    shaker = _w1g9_enter(game, 0, ons["Krosan Groundshaker"])
    assert _w1g9_attack(game, [shaker])[0]
    assert _w1g9_block(game, [(tephraderm, [shaker])])[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(0)
    assert [item.card.name for item in game.stack] == ["Tephraderm"]
    assert not game.is_on_battlefield(tephraderm)
    assert game.is_on_battlefield(shaker) and shaker.damage_marked == 4
    _w1g9_settle(game)
    assert not game.is_on_battlefield(shaker)
    assert game.players[0].life == 20


def test_w1g9_tephraderm_tells_a_creatures_ability_from_an_artifacts(set_pool):
    """A creature's ability is a creature dealing damage (line one); an
    artifact's ability is neither a creature nor a spell (CR 113.3) and fires
    nothing."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    tephraderm = _w1g9_enter(game, 1, ons["Tephraderm"])
    sorcerer = _w1g9_enter(game, 0, lea["Prodigal Sorcerer"])
    rod = _w1g9_enter(game, 0, lea["Rod of Ruin"])
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.activate_permanent_ability(
        0, "Rod of Ruin", target_player_index=1,
        target_permanent_ids=[tephraderm.permanent_id],
    )
    _w1g9_settle(game)
    assert tephraderm.damage_marked == 1
    assert game.is_on_battlefield(rod) and game.players[0].life == 20
    game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1,
        target_permanent_ids=[tephraderm.permanent_id],
    )
    _w1g9_settle(game)
    assert tephraderm.damage_marked == 2
    assert not game.is_on_battlefield(sorcerer)
    assert game.players[0].life == 20


def _w1g9_arm_glarecaster(game, *, at_player=None, at_permanent=None):
    """Glarecaster on seat 0, its ability activated and resolved, aimed at
    *at_player* (a seat) or *at_permanent*."""
    game._set_phase_and_step("precombat_main", "precombat_main")
    if at_permanent is not None:
        result = game.activate_permanent_ability(
            0, "Glarecaster", target_player_index=1,
            target_permanent_ids=[at_permanent.permanent_id],
        )
    else:
        result = game.activate_permanent_ability(
            0, "Glarecaster", target_player_index=at_player,
        )
    assert result.supported
    _w1g9_settle(game)


def test_w1g9_glarecaster_moves_the_next_damage_to_you_once(set_pool):
    """"{5}{W}: The next time damage would be dealt to this creature and/or you
    this turn, that damage is dealt to any target instead." A Shock at its
    controller is dealt to the opponent it named (CR 614.9); the next Shock
    lands — the next time was spent, for both recipients."""
    ons = set_pool("ONS")
    game = _w1g9_table()
    glarecaster = _w1g9_enter(game, 0, ons["Glarecaster"])
    game.players[1].hand.extend([ons["Shock"], ons["Shock"]])
    _w1g9_arm_glarecaster(game, at_player=1)
    game.active_player_index = 1
    game.cast_from_hand(1, "Shock", target_player_index=0)
    _w1g9_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 18)
    assert "2 damage to W1G9-0 is dealt to W1G9-1 instead (Glarecaster)" in game.log
    game.cast_from_hand(
        1, "Shock", target_player_index=0,
        target_permanent_ids=[glarecaster.permanent_id],
    )
    _w1g9_settle(game)
    assert glarecaster.damage_marked == 2, "spent for the creature too"
    assert game.players[1].life == 18


def test_w1g9_glarecaster_moves_every_chunk_dealt_at_the_same_time(set_pool):
    """Ruling (2004-10-04): "if either you or this card would be dealt damage
    from multiple sources at the same time, the redirection will apply to both
    chunks of damage." Two unblocked attackers' combat damage (CR 510.2) is
    moved whole onto the creature it named; a Hurricane hitting the
    Glarecaster and its controller in one resolution is moved whole too."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Glarecaster"])
    seeker = _w1g9_enter(game, 1, ons["Glory Seeker"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    giant = _w1g9_enter(game, 1, lea["Hill Giant"])
    _w1g9_arm_glarecaster(game, at_permanent=giant)
    game.active_player_index = 1
    assert _w1g9_attack(game, [seeker, bears], seat=1, defender=0)[0]
    assert _w1g9_block(game, [], seat=0)[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(1)
    _w1g9_settle(game)
    assert game.players[0].life == 20
    assert not game.is_on_battlefield(giant)

    game = _w1g9_table()
    glarecaster = _w1g9_enter(game, 0, ons["Glarecaster"])
    game.players[1].hand.append(lea["Hurricane"])
    _w1g9_arm_glarecaster(game, at_player=1)
    game.active_player_index = 1
    game.cast_from_hand(1, "Hurricane", x_value=2)
    _w1g9_settle(game)
    assert glarecaster.damage_marked == 0
    assert (game.players[0].life, game.players[1].life) == (20, 14)


def test_w1g9_glarecasters_next_time_ends_with_its_combat_damage_step(set_pool):
    """A first-strike step and the regular step are two dealings (CR 510.4):
    the first striker's damage is moved, the other attacker's lands."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    _w1g9_enter(game, 0, ons["Glarecaster"])
    striker = _w1g9_enter(game, 1, lea["White Knight"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    _w1g9_arm_glarecaster(game, at_player=1)
    game.active_player_index = 1
    assert _w1g9_attack(game, [striker, bears], seat=1, defender=0)[0]
    assert _w1g9_block(game, [], seat=0)[0]
    game._set_phase_and_step("combat", "combat_damage")
    game.resolve_combat_damage(1)
    _w1g9_settle(game)
    if game.combat_damage_resolved is False:
        game.resolve_combat_damage(1)
        _w1g9_settle(game)
    assert game.players[1].life == 18, "the first striker's 2 moved"
    assert game.players[0].life == 18, "the regular step is another time"


def test_w1g9_a_second_protected_recipient_refuses_elsewhere():
    """The "and/or" recipient has one reader; a sentence routed to any other
    redirect lowering refuses rather than dropping it."""
    from engine.grammar import compile_line

    line = compile_line(
        "{5}{W}: The next time damage would be dealt to this creature and/or "
        "target player this turn, that damage is dealt to any target instead.",
        card_name="Probe",
    )
    assert not line.instructions


def _w1g9_orgg_fight(set_pool, *, blocked=True):
    """Butcher Orgg (seat 0) attacks into Wall of Stone, Grizzly Bears and Hill
    Giant; the Wall blocks it unless *blocked* is False. Returns the game at
    the combat damage step, damage not yet dealt."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w1g9_table()
    orgg = _w1g9_enter(game, 0, ons["Butcher Orgg"])
    wall = _w1g9_enter(game, 1, lea["Wall of Stone"])
    bears = _w1g9_enter(game, 1, lea["Grizzly Bears"])
    giant = _w1g9_enter(game, 1, lea["Hill Giant"])
    assert _w1g9_attack(game, [orgg])[0]
    assert _w1g9_block(game, [(wall, [orgg])] if blocked else [])[0]
    game._set_phase_and_step("combat", "combat_damage")
    return game, orgg, wall, bears, giant


def test_w1g9_butcher_orgg_divides_past_its_blocker(set_pool):
    """"You may assign this creature's combat damage divided as you choose
    among defending player and/or any number of creatures they control." Six
    damage, blocked by a 0/8 Wall: 2 to the Bears and 3 to the Giant (neither
    blocking) and 1 to the player. Combat damage all of it (CR 510.2)."""
    from engine.combat_assignment import DIVIDED_AMONG_DEFENDERS_LOG

    game, orgg, wall, bears, giant = _w1g9_orgg_fight(set_pool)
    ok, _ = game.resolve_combat_damage(0, divided_among_defenders={
        orgg.permanent_id: {bears.permanent_id: 2, giant.permanent_id: 3, "player": 1},
    })
    assert ok
    _w1g9_settle(game)
    assert not game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)
    assert wall.damage_marked == 0
    assert game.players[1].life == 19
    assert f"Butcher Orgg {DIVIDED_AMONG_DEFENDERS_LOG}" in game.log


def test_w1g9_butcher_orgg_divides_when_unblocked_and_declines_by_saying_nothing(set_pool):
    """Ruling (2004-10-04): "You can use the ability to divide damage even if
    it is not blocked." Unblocked, all six onto the Wall; declined (no
    division announced), a blocked Orgg assigns to its blocker as CR 510.1c
    says."""
    game, orgg, wall, _bears, _giant = _w1g9_orgg_fight(set_pool, blocked=False)
    assert game.resolve_combat_damage(0, divided_among_defenders={
        orgg.permanent_id: {wall.permanent_id: 6},
    })[0]
    assert wall.damage_marked == 6 and game.players[1].life == 20

    game, orgg, wall, _bears, _giant = _w1g9_orgg_fight(set_pool)
    assert game.resolve_combat_damage(0)[0]
    assert wall.damage_marked == 6 and game.players[1].life == 20


def test_w1g9_butcher_orgg_division_is_held_to_the_rulings(set_pool):
    """CR 510.1e: an illegal division is refused with nothing dealt — all six
    must be divided, each recipient takes at least 1 ("minimum 1 point per
    player or creature"), at least one is chosen, and only the defending
    player and their creatures may be."""
    for build in (
        lambda o, w, b, g: {o.permanent_id: {"player": 5}},
        lambda o, w, b, g: {o.permanent_id: {"player": 6, b.permanent_id: 0}},
        lambda o, w, b, g: {o.permanent_id: {o.permanent_id: 6}},
        lambda o, w, b, g: {o.permanent_id: {}},
        lambda o, w, b, g: {w.permanent_id: {"player": 6}},
    ):
        game, orgg, wall, bears, giant = _w1g9_orgg_fight(set_pool)
        ok, why = game.resolve_combat_damage(
            0, divided_among_defenders=build(orgg, wall, bears, giant)
        )
        assert not ok, why
        assert game.players[1].life == 20 and wall.damage_marked == 0
        assert not game.combat_damage_resolved


def test_w1g9_butcher_orgg_with_its_blocker_gone_has_nothing_to_divide(set_pool):
    """Ruling (2004-10-04): "If it is blocked but then all of its blockers are
    removed before combat damage is assigned, then it won't be able to deal
    combat damage and you won't be able to use its ability.\""""
    game, orgg, wall, bears, _giant = _w1g9_orgg_fight(set_pool)
    game.remove_from_battlefield(wall)
    game._set_phase_and_step("combat", "combat_damage")
    ok, why = game.resolve_combat_damage(0, divided_among_defenders={
        orgg.permanent_id: {bears.permanent_id: 6},
    })
    assert not ok and "nothing left blocking it" in why
    assert game.resolve_combat_damage(0)[0]
    assert game.is_on_battlefield(bears) and game.players[1].life == 20
# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# --- W1G10: control and the stack, on creatures -----------------------------
#
# Quicksilver Dragon is Meddle's sentence with Silver Wyvern's identity in the
# condition ("…and that target is **this creature**"); each card is put on the
# battlefield face up through the engine's own entry point (W1G1 owns the
# face-down half of the morphs).
from engine import Game as _w1g10_Game
from engine.models import Permanent as _w1g10_Permanent
from engine.models import PlayerState as _w1g10_PlayerState
from engine.oracle import compile_card_oracle as _w1g10_compile
from engine.targeting import derive_activation_spec as _w1g10_activation_spec
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_game(seats: int = 2):
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(name=f"P{seat + 1}", life=20) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _w1g10_put(game, seat: int, card):
    perm = _w1g10_Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w1g10_dragon_board(set_pool, set_cards):
    game = _w1g10_game()
    dragon = _w1g10_put(game, 0, set_pool("ONS")["Quicksilver Dragon"])
    bystander = _w1g10_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    giant = _w1g10_put(game, 1, set_pool("LEA")["Hill Giant"])
    return game, dragon, bystander, giant


def _w1g10_dragon_offered(game, set_pool, dragon):
    card = set_pool("ONS")["Quicksilver Dragon"]
    spec = _w1g10_activation_spec(_w1g10_compile(card).activated_abilities[0])
    return [
        entry["name"] for entry in game._enumerate_targets(
            0, card, spec, for_cast=True,
            source_permanent=dragon, ability_source=dragon,
        )
    ]


def test_w1g10_quicksilver_dragon_redirects_a_spell_aimed_at_it(set_pool, set_cards):
    """A Shock aimed at the Dragon is offered to the {U} ability, and resolves
    at another creature instead (CR 115.7a)."""
    game, dragon, bystander, giant = _w1g10_dragon_board(set_pool, set_cards)
    game.players[1].hand.append(set_pool("ONS")["Shock"])
    assert game.queue_from_hand(
        1, "Shock", target_permanent_ids=[dragon.permanent_id]
    ).supported
    assert _w1g10_dragon_offered(game, set_pool, dragon) == ["Shock"]
    assert game.queue_permanent_ability(
        0, "Quicksilver Dragon", target_stack_index=0, ability_index=0,
    ).supported
    _w1g10_resolve_stack(game)

    assert dragon.damage_marked == 0, game.log
    # "another creature": never the Dragon itself, and the headless default is
    # the first other creature the picker lists.
    assert bystander.damage_marked + giant.damage_marked == 2, game.log
    assert any("Shock now targets" in line for line in game.log), game.log


def test_w1g10_quicksilver_dragon_ignores_a_spell_aimed_elsewhere(set_pool, set_cards):
    """"…and that target is **this creature**": a Shock at the creature beside
    it is not offered, and an activation naming it is refused before {U} is
    spent — the clause read and dropped would re-aim every spell."""
    game, dragon, bystander, _giant = _w1g10_dragon_board(set_pool, set_cards)
    game.players[1].hand.append(set_pool("ONS")["Shock"])
    game.queue_from_hand(1, "Shock", target_permanent_ids=[bystander.permanent_id])
    assert _w1g10_dragon_offered(game, set_pool, dragon) == []
    assert not game.queue_permanent_ability(
        0, "Quicksilver Dragon", target_stack_index=0, ability_index=0,
    ).supported
    _w1g10_resolve_stack(game)
    assert bystander.damage_marked == 2, game.log
    assert dragon.damage_marked == 0


def test_w1g10_quicksilver_dragon_leaves_a_two_target_spell_alone(set_pool, set_cards):
    """"…has only one target" (CR 115.9a): a spell naming the Dragon and a
    second object is not the Dragon's to re-aim."""
    game, dragon, bystander, _giant = _w1g10_dragon_board(set_pool, set_cards)
    game.players[1].hand.append(set_pool("USG")["Arc Lightning"])
    # Dragon and bystander are seat 0's slots 0 and 1.
    assert game.queue_from_hand(
        1, "Arc Lightning", divided_targets=[(0, 0, 1), (0, 1, 2)],
    ).supported
    assert _w1g10_dragon_offered(game, set_pool, dragon) == []
    _w1g10_resolve_stack(game)
    assert dragon.damage_marked == 1, game.log


def _w1g10_entrancer_swing(set_pool):
    """A three-seat table: the Entrancer (seat 0) attacks seat 2 unblocked;
    seat 1 and seat 2 each control a creature. Returns at the trigger's
    target prompt, with seat 0 interactive."""
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 5,
        )
        for seat in range(3)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    entrancer = _w1g10_put(game, 0, set_pool("ONS")["Riptide Entrancer"])
    bears = _w1g10_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    giant = _w1g10_put(game, 2, set_pool("LEA")["Hill Giant"])
    for perm in (entrancer, bears, giant):
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=2)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(2, {})[0]
    game.advance_combat_phase()
    assert game.players[2].life == 19
    return game, entrancer, bears, giant


def test_w1g10_riptide_entrancer_takes_the_damaged_players_creature(set_pool):
    """"…you may sacrifice it. If you do, gain control of target creature
    **that player** controls." At three seats the picker offers only the
    damaged player's creature, refuses the other opponent's, and accepting
    the offer sacrifices the Entrancer and takes the creature for good."""
    game, entrancer, bears, giant = _w1g10_entrancer_swing(set_pool)
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert [t["name"] for t in prompt.data["targets"]] == ["Hill Giant"]
    assert not game.confirm_trigger_target(0, permanent_id=bears.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)

    game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, game.log
    assert game._resolve_optional_pay(offer, True, None)
    game._settle()

    assert not game.is_on_battlefield(entrancer)
    assert "Riptide Entrancer" in [c.name for c in game.players[0].graveyard]
    assert game.controller_index_of(giant) == 0, game.log
    assert game.controller_index_of(bears) == 1
    # "This effect lasts indefinitely": cleanup does not hand it back.
    game.start_next_turn()
    assert game.controller_index_of(giant) == 0, game.log


def test_w1g10_riptide_entrancer_declined_keeps_everything(set_pool):
    game, entrancer, bears, giant = _w1g10_entrancer_swing(set_pool)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, False, None)
    game._settle()
    assert game.is_on_battlefield(entrancer)
    assert game.controller_index_of(giant) == 2


def _w1g10_shieldmage_board(set_pool):
    """Shieldmage Elder and a second Wizard, both just arrived: tapping
    untapped Wizards is not a {T} cost, so summoning sickness does not stop it
    (the 2004-10-04 ruling: "including creatures that haven't been under your
    control continuously")."""
    game = _w1g10_Game(players=[
        _w1g10_PlayerState(
            name=f"P{seat + 1}", life=20,
            library=[set_pool("LEA")["Island"]] * 5,
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    elder = _w1g10_Permanent(card=set_pool("ONS")["Shieldmage Elder"])
    game._put_permanent_onto_battlefield(0, elder, None)
    wizard = _w1g10_Permanent(card=set_pool("LEA")["Prodigal Sorcerer"])
    game._put_permanent_onto_battlefield(0, wizard, None)
    return game, elder, wizard


def test_w1g10_shieldmage_elder_prevents_a_spells_damage(set_pool):
    """"Tap two untapped Wizards you control: Prevent all damage target spell
    would deal this turn." — a Lightning Bolt aimed at its controller deals
    nothing, and the two Wizards are what paid."""
    game, elder, wizard = _w1g10_shieldmage_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_permanent_ability(
        0, "Shieldmage Elder", target_stack_index=0, ability_index=1,
    ).supported
    assert elder.tapped and wizard.tapped
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 20, game.log


def test_w1g10_shieldmage_elder_shield_follows_a_permanent_spell(set_pool):
    """CR 400.7c (and the card's ruling): a shield on a creature spell keeps
    preventing the damage of the permanent it becomes, for the rest of the
    turn — and only this turn: after the cleanup the same ping lands."""
    game, _elder, _wizard = _w1g10_shieldmage_board(set_pool)
    game.players[1].hand.append(set_pool("LEA")["Prodigal Sorcerer"])
    assert game.queue_from_hand(1, "Prodigal Sorcerer").supported
    assert game.queue_permanent_ability(
        0, "Shieldmage Elder", target_stack_index=0, ability_index=1,
    ).supported
    _w1g10_resolve_stack(game)
    (theirs,) = game.controlled_by(1)
    assert theirs.card.name == "Prodigal Sorcerer"
    theirs.metadata["summoning_sickness_turn"] = -99
    assert game.queue_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0, ability_index=0,
    ).supported
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 20, game.log

    game.resolve_cleanup_step(0)
    game.start_next_turn()
    theirs.tapped = False
    assert game.queue_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0, ability_index=0,
    ).supported
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 19, game.log

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# Weathered Wayfarer's "Activate only if an opponent controls more lands than
# you." — a row of `engine/activation_restrictions.py` reading the clause
# through the grammar's condition reader (Land Tax's and Tithe's words) and
# answering it with their evaluator, asked before any cost (CR 602.5).

from engine import Game as _W1G11Game, PlayerState as _W1G11PlayerState
from engine.activation_restrictions import (
    activation_restriction_line as _w1g11_restriction_line,
)
from engine.models import Permanent as _W1G11Permanent
from tests.helpers import resolve_stack as _w1g11_resolve_stack


def _w1g11_wayfarer_table(set_pool, *, their_lands=0, my_lands=0):
    ons = set_pool("ONS")
    alice = _W1G11PlayerState(
        name="Alice", library=[ons["Island"], ons["Plains"], ons["Shock"]],
    )
    bob = _W1G11PlayerState(name="Bob", library=[ons["Mountain"]] * 3)
    game = _W1G11Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    for seat, count, land in ((0, my_lands, "Plains"), (1, their_lands, "Mountain")):
        for _ in range(count):
            game._put_permanent_onto_battlefield(seat, _W1G11Permanent(card=ons[land]), None)
    wayfarer = _W1G11Permanent(card=ons["Weathered Wayfarer"])
    game._put_permanent_onto_battlefield(0, wayfarer, None)
    wayfarer.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return game, wayfarer


def test_w1g11_weathered_wayfarer_is_refused_unless_an_opponent_has_more_lands(set_pool):
    """Two lands each: "more" is strict, and the activation is refused before
    its cost is paid — the Wayfarer stays untapped."""
    assert _w1g11_restriction_line(
        "Activate only if an opponent controls more lands than you."
    )
    game, wayfarer = _w1g11_wayfarer_table(set_pool, their_lands=2, my_lands=2)

    refused = game.activate_permanent_ability(0, "Weathered Wayfarer")

    assert not refused.supported
    assert "only if an opponent controls more lands than you" in refused.details
    assert not wayfarer.tapped and game.stack == []


def test_w1g11_weathered_wayfarer_searches_out_a_land_when_behind(set_pool):
    """Bob three lands to Alice's two: the search finds a land card, reveals it
    and puts it into Alice's hand, and the Shock stays in the library."""
    game, wayfarer = _w1g11_wayfarer_table(set_pool, their_lands=3, my_lands=2)
    alice = game.players[0]

    assert game.activate_permanent_ability(0, "Weathered Wayfarer").supported
    assert wayfarer.tapped
    _w1g11_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(alice.hand) == 1 and "land" in alice.hand[0].type_line.lower()
    assert "Shock" in [card.name for card in alice.library] and len(alice.library) == 2
    assert any(line.startswith("Alice revealed") for line in game.log)

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# --- W1G12: revealing ---------------------------------------------------------
from engine import Game as _w1g12_Game
from engine.models import Permanent as _w1g12_Permanent
from engine.models import PlayerState as _w1g12_PlayerState
from engine.oracle import compile_card_oracle as _w1g12_compile
from engine.targeting import derive_activation_spec as _w1g12_activation_spec

from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_table(set_pool, library, *, hands=None, interactive=(), seats=2):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara"][:seats]
    players = [
        _w1g12_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=(
                [ons[c] if isinstance(c, str) else c for c in library]
                if seat == 0 else [ons["Plains"]] * 5
            ),
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g12_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g12_put(game, seat, card):
    permanent = _w1g12_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g12_names(cards):
    return [card.name for card in cards]


def test_w1g12_goblin_machinist_pumps_by_the_first_nonland_and_bottoms_the_run(set_pool):
    """"{2}{R}: Reveal cards from the top of your library until you reveal a
    nonland card. This creature gets +X/+0 until end of turn, where X is that
    card's mana value. Put the revealed cards on the bottom of your library in
    any order." The run stops on Akroma's Vengeance (mana value 6) under two
    lands; the Machinist is 6/5; the three revealed cards — the find among
    them — go under the two cards that were never turned over, in the order
    the interactive owner chose (CR 401.4)."""
    game = _w1g12_table(
        set_pool,
        ["Mountain", "Island", "Akroma's Vengeance", "Forest", "Goblin Taskmaster"],
        interactive={0},
    )
    machinist = _w1g12_put(game, 0, set_pool("ONS")["Goblin Machinist"])
    assert game.activate_permanent_ability(0, "Goblin Machinist").supported
    assert not game.resolve_top_of_stack()
    order = game.pending_choice_of("reorder_library", 0)
    assert order is not None and order.data["position"] == "bottom"
    assert order.data["top_count"] == 3
    # Before the order is answered the pump has already happened (CR 608.2c:
    # the pump is printed before the bottom).
    assert (machinist.effective_power, machinist.effective_toughness) == (6, 5)
    assert game.confirm_reorder_library(0, [2, 1, 0])
    _w1g12_resolve_stack(game)
    assert _w1g12_names(game.players[0].library) == [
        "Forest", "Goblin Taskmaster", "Akroma's Vengeance", "Island", "Mountain",
    ]
    assert (machinist.effective_power, machinist.effective_toughness) == (6, 5)
    assert any("stopped on Akroma's Vengeance" in line for line in game.log)


def test_w1g12_goblin_machinist_over_an_all_land_library_is_zero(set_pool):
    """The ruling (2004-10-04): "If all the cards in your library are lands, X
    is zero." The whole library is revealed and put back, in the order a
    headless owner leaves it; the Machinist stays 0/5."""
    game = _w1g12_table(set_pool, ["Mountain", "Island", "Forest"])
    machinist = _w1g12_put(game, 0, set_pool("ONS")["Goblin Machinist"])
    assert game.activate_permanent_ability(0, "Goblin Machinist").supported
    _w1g12_resolve_stack(game)
    assert (machinist.effective_power, machinist.effective_toughness) == (0, 5)
    assert _w1g12_names(game.players[0].library) == ["Mountain", "Island", "Forest"]
    assert game.pending_choices == []


def test_w1g12_riptide_shapeshifter_digs_for_the_type_it_names(set_pool):
    """"{2}{U}{U}, Sacrifice this creature: Choose a creature type. Reveal
    cards from the top of your library until you reveal a creature card of
    that type. Put that card onto the battlefield and shuffle the rest into
    your library." Named Goblin, the run passes the Elf (a creature card, but
    not of that type) and stops on the Goblin under it; the Elf and the land
    are shuffled back, the Goblin under the bottom stays in the library."""
    game = _w1g12_table(
        set_pool,
        ["Forest", "Wellwisher", "Goblin Taskmaster", "Island", "Skirk Commando"],
        interactive={0},
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    # It targets nothing: no picker for the client to fill in.
    assert _w1g12_activation_spec(
        _w1g12_compile(set_pool("ONS")["Riptide Shapeshifter"]).activated_abilities[0]
    ) is None
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    assert _w1g12_names(game.players[0].graveyard) == ["Riptide Shapeshifter"]
    assert not game.resolve_top_of_stack()
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Goblin Taskmaster"]
    assert sorted(_w1g12_names(game.players[0].library)) == [
        "Forest", "Island", "Skirk Commando", "Wellwisher",
    ]


def test_w1g12_riptide_shapeshifter_naming_a_type_nothing_has_finds_nothing(set_pool):
    """A type no card in the library has: the whole library is revealed,
    nothing enters, and every card is shuffled back — never the first creature
    card of some other type. And the default a seat nobody asks takes is its
    own library's commonest type (two Goblins against one Elf)."""
    game = _w1g12_table(
        set_pool, ["Forest", "Wellwisher", "Island"], interactive={0},
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    assert not game.resolve_top_of_stack()
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g12_resolve_stack(game)
    assert list(game.all_permanents()) == []
    assert sorted(_w1g12_names(game.players[0].library)) == [
        "Forest", "Island", "Wellwisher",
    ]

    game = _w1g12_table(
        set_pool,
        ["Forest", "Wellwisher", "Goblin Taskmaster", "Island", "Skirk Commando"],
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Goblin Taskmaster"]


def _w1g12_ogre_numbers(set_pool, numbers, *, seats=2):
    """Cast Menacing Ogre with every seat interactive and answer each seat's
    secret number; the Ogre and the table after the trigger resolves."""
    game = _w1g12_table(
        set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]},
        interactive=set(range(seats)), seats=seats,
    )
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    assert len(game.stack) == 1, "the entry trigger is on the stack (CR 603.3)"
    assert not game.resolve_top_of_stack()
    owed = sorted(c.player_index for c in game.pending_choices if c.kind == "secret_number")
    assert owed == list(range(seats))
    # Answered last seat first: no number is shown before the last exists.
    for seat in reversed(range(seats)):
        assert not any(
            line.startswith("Menacing Ogre: ") and " revealed " in line
            for line in game.log
        ), "a secret number was shown before every seat had one"
        assert game.confirm_secret_number(seat, numbers[seat])
    _w1g12_resolve_stack(game)
    ogre = next(p for p in game.all_permanents() if p.card.name == "Menacing Ogre")
    return game, ogre


def test_w1g12_menacing_ogre_a_tie_for_highest_costs_both_and_feeds_the_ogre(set_pool):
    """"When this creature enters, each player secretly chooses a number. Then
    those numbers are revealed. Each player with the highest number loses that
    much life. If you are one of those players, put two +1/+1 counters on this
    creature." Alice and Bob both name 3: each loses 3, and Alice — one of
    those players — gets her two counters. The reveal is one line, every
    number at once, after the last answer."""
    game, ogre = _w1g12_ogre_numbers(set_pool, [3, 3])
    assert [p.life for p in game.players] == [17, 17]
    assert (ogre.effective_power, ogre.effective_toughness) == (5, 5)
    assert any("Alice revealed 3, Bob revealed 3" in line for line in game.log)


def test_w1g12_menacing_ogre_only_the_highest_pays_and_a_loser_gets_nothing(set_pool):
    """Bob's 4 beats Alice's 1: Bob alone loses 4, Alice nothing, and the Ogre
    stays 3/3. At three seats Bob and Cara tie on 6 over Alice's 2: both lose
    6 and Alice is not one of those players."""
    game, ogre = _w1g12_ogre_numbers(set_pool, [1, 4])
    assert [p.life for p in game.players] == [20, 16]
    assert (ogre.effective_power, ogre.effective_toughness) == (3, 3)

    game, ogre = _w1g12_ogre_numbers(set_pool, [2, 6, 6], seats=3)
    assert [p.life for p in game.players] == [20, 14, 14]
    assert (ogre.effective_power, ogre.effective_toughness) == (3, 3)


def test_w1g12_menacing_ogre_numbers_are_whole_and_not_negative(set_pool):
    """The ruling (2004-10-04): "You have to choose zero or a positive number.
    It must be an integer number." Minus one and a fraction are refused with
    the prompt kept; zero is an answer. And seats nobody asks name the floor —
    the highest pays, so any more is life lost for nothing — which ties them
    at 0 and gives the Ogre its counters for free."""
    game = _w1g12_table(
        set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]}, interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    assert not game.resolve_top_of_stack()
    assert not game.confirm_secret_number(0, -1)
    assert not game.confirm_secret_number(0, "1.5")
    assert game.pending_choice_of("secret_number", 0) is not None
    assert game.confirm_secret_number(0, 0)

    game = _w1g12_table(set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]})
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    _w1g12_resolve_stack(game)
    ogre = next(p for p in game.all_permanents() if p.card.name == "Menacing Ogre")
    assert [p.life for p in game.players] == [20, 20]
    assert (ogre.effective_power, ogre.effective_toughness) == (5, 5)


def test_w1g12_stag_beetle_counts_the_other_creatures_as_it_enters(set_pool):
    """"This creature enters with X +1/+1 counters on it, where X is the
    number of other creatures on the battlefield." Three others (one Alice's,
    two Bob's) make it 3/3 — never itself, and never the cast's X, which its
    cost does not have: it was admitted by a prefix row and entered 0/0
    whatever was there. The ruling (2004-10-04): "The value of X is
    calculated once, as Stag Beetle is entering" — a fourth creature later
    changes nothing. Alone it is 0/0 and dies (CR 704.5f)."""
    from tests.helpers import _mk_creature_card as _w1g12_creature

    game = _w1g12_table(set_pool, ["Forest"] * 5, hands={0: ["Stag Beetle"]})
    _w1g12_put(game, 0, _w1g12_creature("Alice's Bear", 2, 2))
    _w1g12_put(game, 1, _w1g12_creature("Bob's Bear", 2, 2))
    _w1g12_put(game, 1, _w1g12_creature("Bob's Elf", 1, 1))
    assert game.cast_from_hand(0, "Stag Beetle").supported
    _w1g12_resolve_stack(game)
    beetle = next(p for p in game.all_permanents() if p.card.name == "Stag Beetle")
    assert (beetle.effective_power, beetle.effective_toughness) == (3, 3)
    _w1g12_put(game, 1, _w1g12_creature("Bob's Giant", 3, 3))
    assert (beetle.effective_power, beetle.effective_toughness) == (3, 3)

    game = _w1g12_table(set_pool, ["Forest"] * 5, hands={0: ["Stag Beetle"]})
    assert game.cast_from_hand(0, "Stag Beetle").supported
    _w1g12_resolve_stack(game)
    assert list(game.all_permanents()) == []
    assert _w1g12_names(game.players[0].graveyard) == ["Stag Beetle"]


def test_w1g12_silklash_spider_hits_every_flyer_and_nothing_else(set_pool):
    """"Reach / {X}{G}{G}: This creature deals X damage to each creature with
    flying." X=2: both sides' flyers take 2 (Alice's 2/2 dies, Bob's 1/3
    survives damaged); the Bear and the Spider itself — reach is not flying —
    are untouched."""
    from tests.helpers import _mk_creature_card as _w1g12_creature

    game = _w1g12_table(set_pool, ["Forest"] * 5)
    spider = _w1g12_put(game, 0, set_pool("ONS")["Silklash Spider"])
    bobs_bird = _w1g12_put(game, 1, _w1g12_creature("Bob's Bird", 1, 3, "Flying"))
    alices_bird = _w1g12_put(game, 0, _w1g12_creature("Alice's Bird", 2, 2, "Flying"))
    bear = _w1g12_put(game, 1, _w1g12_creature("Bob's Bear", 2, 2))
    assert game.activate_permanent_ability(0, "Silklash Spider", x_value=2).supported
    _w1g12_resolve_stack(game)
    assert bobs_bird.damage_marked == 2 and game.is_on_battlefield(bobs_bird)
    assert not game.is_on_battlefield(alices_bird)
    assert bear.damage_marked == 0 and spider.damage_marked == 0

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# --- W1G13: each player, and graveyards --------------------------------------
from engine import Game as _w1g13_Game
from engine.models import Permanent as _w1g13_Permanent
from engine.models import PlayerState as _w1g13_PlayerState

from tests.helpers import _mk_creature_card as _w1g13_creature
from tests.helpers import resolve_stack as _w1g13_resolve_stack


def _w1g13_table(set_pool, hands=None, *, interactive=(), seats=3):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g13_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[ons["Plains"]] * 5,
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g13_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g13_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_entrails_feaster_exiles_from_any_graveyard_it_names(set_pool):
    """"At the beginning of your upkeep, you may exile a creature card from a
    graveyard. If you do, put a +1/+1 counter on this creature." Any pile:
    the controller names Cara's graveyard and the creature card in it, never
    the land beside it, and the Feaster grows."""
    game = _w1g13_table(set_pool, interactive={0})
    alice, bob, cara = game.players
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    cara.graveyard.extend([set_pool("ONS")["Plains"], _w1g13_creature("Cara's Giant", 3, 3)])
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=True)
    pile = game.pending_choice_of("graveyard_pile_choice", 0)
    assert pile is not None and sorted(pile.data["seats"]) == [1, 2]
    assert game.confirm_graveyard_pile_choice(0, 2)
    assert game.confirm_graveyard_exile_pick(0, [1])
    _w1g13_resolve_stack(game)
    assert [c.name for c in cara.exile] == ["Cara's Giant"]
    assert [c.name for c in cara.graveyard] == ["Plains"]
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]
    assert (feaster.effective_power, feaster.effective_toughness) == (2, 2)
    assert not feaster.tapped


def test_w1g13_entrails_feaster_taps_when_it_does_not_exile(set_pool):
    """"If you don't, tap this creature." Declining taps it; and with no
    creature card in any graveyard there is nothing to exile, so the offer is
    never made and it taps all the same."""
    game = _w1g13_table(set_pool, interactive={0})
    bob = game.players[1]
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=False)
    _w1g13_resolve_stack(game)
    assert feaster.tapped and feaster.effective_power == 1
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]

    game = _w1g13_table(set_pool)
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    game.players[1].graveyard.append(set_pool("ONS")["Plains"])
    game.resolve_upkeep(0)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.pending_choices == []
    assert feaster.tapped and feaster.effective_power == 1


def test_w1g13_gigapede_returns_from_the_graveyard_for_a_discard(set_pool):
    """"At the beginning of your upkeep, if this card is in your graveyard,
    you may discard a card. If you do, return this card to your hand." The
    graveyard-trigger census's red on the ingest was the census, not the card:
    the discard pays, and the Gigapede is in the hand."""
    gigapede = set_pool("ONS")["Gigapede"]
    game = _w1g13_table(set_pool, {0: ["Plains"]}, interactive={0})
    alice = game.players[0]
    alice.graveyard.append(gigapede)
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Gigapede", accept=True)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0], to_library=False,
    )
    _w1g13_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Gigapede"]
    assert [c.name for c in alice.graveyard] == ["Plains"]


def _w1g13_quiet_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game.players[seat].battlefield.append(permanent)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_tempting_wurm_each_opponent_puts_cards_from_their_hand(set_pool):
    """"When this creature enters, each opponent may put any number of
    artifact, creature, enchantment, and/or land cards from their hand onto
    the battlefield." Each opponent in APNAP order, Bob before Cara, offered
    only the four printed types (never the instant), the Wurm's controller
    never asked; the chosen cards enter together under their owners, after
    the last choice, and an Aura enters attached to a creature already there
    (CR 303.4f) — its controller asked which."""
    ons = set_pool("ONS")
    giant = _w1g13_creature("Bob's Giant", 3, 3)
    game = _w1g13_table(
        set_pool,
        {0: ["Tempting Wurm"], 1: [giant, "Pacifism", "Shock", "Forest"],
         2: ["Plains"]},
        interactive={0, 1, 2},
    )
    alice, bob, cara = game.players
    alices = _w1g13_quiet_put(game, 0, _w1g13_creature("Alice's Bear", 2, 2))
    assert game.cast_from_hand(0, "Tempting Wurm").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 1),
    ]
    offered = game.live_choose_cards_in_hand(game.pending_choices[0])
    assert [bob.hand[i].name for i in offered] == ["Bob's Giant", "Pacifism", "Forest"]
    assert game.confirm_choose_cards_in_hand(1, offered)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 2),
    ]
    assert not any(perm.card is giant for perm in game.controlled_by(1)), (
        "nothing enters before the last opponent has chosen"
    )
    assert game.confirm_choose_cards_in_hand(2, [])
    host = game.pending_choice_of("permanent_choice", 1)
    assert host is not None, "Bob chooses what his Pacifism enchants"
    assert game.confirm_permanent_choice(1, alices.permanent_id)
    _w1g13_resolve_stack(game)
    assert sorted(perm.card.name for perm in game.controlled_by(1)) == [
        "Bob's Giant", "Forest", "Pacifism",
    ]
    assert [c.name for c in bob.hand] == ["Shock"]
    pacifism = next(p for p in game.controlled_by(1) if p.card is ons["Pacifism"])
    assert pacifism.metadata.get("attached_to") is alices
    assert [c.name for c in cara.hand] == ["Plains"]
    assert [perm.card.name for perm in game.controlled_by(2)] == []


def test_w1g13_tempting_wurm_an_aura_with_nothing_to_enchant_stays_in_hand(set_pool):
    """CR 303.4g: with no creature already on the battlefield besides the
    Wurm — here none at all once the Wurm is gone — an Aura stays in the hand.
    A seat nobody asks takes every card the sentence offers."""
    ons = set_pool("ONS")
    game = _w1g13_table(set_pool, {0: ["Tempting Wurm"], 1: ["Pacifism", "Forest"]})
    bob = game.players[1]
    assert game.queue_from_hand(0, "Tempting Wurm").supported
    game.resolve_top_of_stack()
    wurm = next(p for p in game.controlled_by(0) if p.card.name == "Tempting Wurm")
    game.remove_from_battlefield(wurm)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Forest"]
    assert [c.name for c in bob.hand] == ["Pacifism"]
    assert any("303.4g" in line for line in game.log)
    assert ons["Pacifism"] in bob.hand

# ==== end W1G13 ======================================================


# ==== W2G3 ==========================================================
# W2G3's tests go between this line and the "end W2G3" line.
from engine import Game as _w2g3_Game, PlayerState as _w2g3_PlayerState
from engine.combat_assignment import (
    DIVIDED_AMONG_DEFENDERS_LOG as _W2G3_DIVIDED_LOG,
)
from engine.models import Permanent as _w2g3_Permanent


def _w2g3_orgg_at_damage(set_pool, *, interactive, block=False, first_striker=False):
    """Butcher Orgg (seat 0) attacks seat 1, who controls a Wall of Stone and
    Grizzly Bears; the Wall blocks it when *block*. With *first_striker* a
    White Knight attacks beside it, so the combat has two damage steps. The
    turn is driven through the engine's own rail (``advance_combat_phase``)
    into the combat damage step, which is where the wait is decided."""
    ons, lea = set_pool("ONS"), set_pool("LEA")
    game = _w2g3_Game(players=[_w2g3_PlayerState(name="Orgg"), _w2g3_PlayerState(name="Wall")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)

    def put(seat, card):
        perm = _w2g3_Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        return perm

    orgg = put(0, ons["Butcher Orgg"])
    attackers = [orgg] + ([put(0, lea["White Knight"])] if first_striker else [])
    wall = put(1, lea["Wall of Stone"])
    bears = put(1, lea["Grizzly Bears"])
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.declare_attackers(
        0, [game.battlefield_index_of(a) for a in attackers], defending_player_index=1,
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(wall): [game.battlefield_index_of(orgg)]} if block else {},
    )[0]
    game.advance_combat_phase()
    return game, orgg, wall, bears


def _w2g3_waiting(game) -> bool:
    return game.current_step == "combat_damage" and not game.combat_damage_resolved


def test_w2g3_an_unblocked_orgg_waits_for_the_person_who_controls_it(set_pool):
    """"You can use the ability to divide damage even if it is not blocked"
    (ruling 2004-10-04). The step used to deal an unblocked Orgg's damage as
    it was entered — the offer declined over the head of the one player
    allowed to take it. Now it stops, advancing again does not run past the
    question, and the answer is the assignment: here 2 to the Bears, 4 to the
    player."""
    game, orgg, wall, bears = _w2g3_orgg_at_damage(set_pool, interactive=(0,))
    assert _w2g3_waiting(game), "the step resolved without asking"
    assert game.divided_assignments_to_ask() == [game.battlefield_index_of(orgg)]
    assert game.divided_assignments_to_ask(1) == [], "the offer is the attacker's"
    game.advance_combat_phase()
    assert _w2g3_waiting(game) and game.players[1].life == 20

    assert game.resolve_combat_damage(0, divided_among_defenders={
        orgg.permanent_id: {bears.permanent_id: 2, "player": 4},
    })[0]
    game.check_state_based_actions()
    assert game.players[1].life == 16
    assert not game.is_on_battlefield(bears) and wall.damage_marked == 0
    assert f"Butcher Orgg {_W2G3_DIVIDED_LOG}" in game.log
    assert game.divided_assignments_to_ask() == [], "answered"


def test_w2g3_a_single_blocked_orgg_waits_and_declining_assigns_to_its_blocker(set_pool):
    """One blocker used to resolve at once too (CR 510.1c leaves no division to
    ask for). The offer is still open, so the step stops; saying nothing about
    the Orgg is the offer declined, and all six go to the Wall."""
    game, orgg, wall, bears = _w2g3_orgg_at_damage(set_pool, interactive=(0,), block=True)
    assert _w2g3_waiting(game)
    assert game._manual_assignment_has_declared_multiblock(), (
        "the web layer is told a dialog can surface it, so it does not auto-resolve"
    )
    assert game.resolve_combat_damage(0)[0]
    assert wall.damage_marked == 6 and game.players[1].life == 20
    assert game.is_on_battlefield(bears)
    assert not any(_W2G3_DIVIDED_LOG in line for line in game.log)


def test_w2g3_a_seat_nobody_sits_in_is_not_stopped(set_pool):
    """A seat nobody asks is answered as the step resolves, so an AI or
    headless combat resolves as the step is entered — nothing waits on a
    prompt nobody would answer.

    *What* it answers is the AI's chooser's
    (``ai_combat.choose_combat_damage_announcement``, whose valuation
    ``tests/ai/test_ai_ons_w2g5_policy.py``'s Orgg tests hold): this test once
    read the offer declined (the player at 14), which held until the chooser
    learned to take the division. Taken or declined, all six are dealt now."""
    game, _orgg, _wall, _bears = _w2g3_orgg_at_damage(set_pool, interactive=())
    assert game.combat_damage_resolved
    taken = any(_W2G3_DIVIDED_LOG in line for line in game.log)
    life = game.players[1].life
    assert (14 <= life < 20) if taken else life == 14
    assert game.divided_assignments_to_ask() == []

    game, _orgg, wall, _bears = _w2g3_orgg_at_damage(set_pool, interactive=(1,), block=True)
    assert game.combat_damage_resolved, "a person defending is not the one asked"
    # Declined, the blocking Wall takes all six; taken, the split is the
    # chooser's (the printed text divides among the defending player and any
    # creatures they control, blocking or not).
    if not any(_W2G3_DIVIDED_LOG in line for line in game.log):
        assert wall.damage_marked == 6


def test_w2g3_a_first_strike_combat_asks_again_for_the_second_step(set_pool):
    """CR 510.4: with a first striker beside it there are two combat damage
    steps, and each is its own announcement. The Orgg deals its damage in the
    second; the step waits there too, and a division announced for it lands."""
    game, orgg, _wall, bears = _w2g3_orgg_at_damage(
        set_pool, interactive=(0,), first_striker=True,
    )
    assert _w2g3_waiting(game) and not game.combat_first_strike_done
    assert game.resolve_combat_damage(0)[0]
    assert game.combat_first_strike_done and not game.combat_damage_resolved
    assert game.players[1].life == 18, "the White Knight's first strike"
    game.advance_combat_phase()
    assert _w2g3_waiting(game), "the second step ran past the question"
    assert game.divided_assignments_to_ask() == [game.battlefield_index_of(orgg)]
    assert game.resolve_combat_damage(0, divided_among_defenders={
        orgg.permanent_id: {bears.permanent_id: 3, "player": 3},
    })[0]
    game.check_state_based_actions()
    assert game.combat_damage_resolved
    assert game.players[1].life == 15 and not game.is_on_battlefield(bears)
# ==== end W2G3 ======================================================


# ==== W2G6 ==========================================================
# Gravespawn Sovereign, the card the reanimation agreement ratchet names at
# Onslaught's promotion (tests/engine/test_targeting.py). Supported on
# arrival and never given a test until then.
from engine import Game as _W2G6Game
from engine import PlayerState as _W2G6PlayerState
from engine.models import Permanent as _W2G6Permanent
from engine.targeting import derive_activation_spec as _w2g6_derive_activation_spec
from engine.oracle import compile_card_oracle as _w2g6_compile
from tests.helpers import resolve_stack as _w2g6_resolve_stack


def _w2g6_sovereign_table(set_pool, catalog_by_name, *, zombies=4):
    """The Sovereign and *zombies* other Zombies on seat 0's board, a Hill
    Giant and a Swamp in its graveyard, a Serra Angel, a Lightning Bolt and a
    Forest in the opponent's."""
    ons = set_pool("ONS")
    game = _W2G6Game(players=[
        _W2G6PlayerState(
            name="A", graveyard=[catalog_by_name["Hill Giant"], catalog_by_name["Swamp"]],
            library=[ons["Swamp"]] * 5,
        ),
        _W2G6PlayerState(
            name="B",
            graveyard=[
                catalog_by_name["Serra Angel"], catalog_by_name["Lightning Bolt"],
                catalog_by_name["Forest"],
            ],
            library=[ons["Swamp"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    tribe = []
    for card in [ons["Gravespawn Sovereign"]] + [ons["Gluttonous Zombie"]] * zombies:
        perm = _W2G6Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        tribe.append(perm)
    return game, tribe


def test_w2g6_gravespawn_sovereign_reanimates_from_either_graveyard(set_pool, catalog_by_name):
    """"Tap five untapped Zombies you control: Put target creature card from
    a graveyard onto the battlefield under your control." The program says
    which graveyard - any (no ``own_graveyard_only``) - and the picker offers
    the creature cards in both and nothing else; the opponent's Angel comes
    back under the Sovereign's controller, five Zombies tapped for it."""
    (ability,) = _w2g6_compile(set_pool("ONS")["Gravespawn Sovereign"]).activated_abilities
    spec = _w2g6_derive_activation_spec(ability)
    assert spec["kind"] == "graveyard_creature" and not spec.get("own_graveyard_only")

    game, tribe = _w2g6_sovereign_table(set_pool, catalog_by_name)
    offered = game.activation_target_spec(0, game.battlefield_index_of(tribe[0]))
    assert sorted((entry["seat"], entry["name"]) for entry in offered["valid_targets"]) == [
        (0, "Hill Giant"), (1, "Serra Angel"),
    ]
    assert game.activate_permanent_ability(
        0, "Gravespawn Sovereign", target_player_index=1, target_permanent_index=0,
    ).supported
    assert all(perm.tapped for perm in tribe)
    _w2g6_resolve_stack(game)
    assert "Serra Angel" in [perm.card.name for perm in game.controlled_by(0)]
    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt", "Forest"]


def test_w2g6_gravespawn_sovereign_refuses_a_noncreature_card_and_four_zombies(
    set_pool, catalog_by_name,
):
    """Naming the Forest card is refused before the cost is paid, and with
    four Zombies in all the cost cannot be paid: nothing is tapped either
    way."""
    game, tribe = _w2g6_sovereign_table(set_pool, catalog_by_name)
    assert not game.activate_permanent_ability(
        0, "Gravespawn Sovereign", target_player_index=1, target_permanent_index=2,
    ).supported
    assert not any(perm.tapped for perm in tribe)

    game, tribe = _w2g6_sovereign_table(set_pool, catalog_by_name, zombies=3)
    assert not game.activate_permanent_ability(
        0, "Gravespawn Sovereign", target_player_index=1, target_permanent_index=0,
    ).supported
    assert not any(perm.tapped for perm in tribe)
    assert game.stack == []

# ==== end W2G6 ======================================================


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

# --- W2G4: which opponent chooses --------------------------------------------
from engine import Game as _w2g4_Game
from engine.models import Permanent as _w2g4_Permanent
from engine.models import PlayerState as _w2g4_PlayerState


def _w2g4_oppressor_table(set_pool, seats, interactive, *, controller=0):
    names = ["Alice", "Bob", "Cara"][:seats]
    game = _w2g4_Game(players=[_w2g4_PlayerState(name=name) for name in names])
    game.enforce_mana_costs = False
    game.active_player_index = controller
    game.interactive_seats = set(interactive)
    oppressor = _w2g4_Permanent(card=set_pool("ONS")["Callous Oppressor"])
    game._put_permanent_onto_battlefield(controller, oppressor, None)
    return game, oppressor


def test_w2g4_callous_oppressor_asks_its_controller_which_opponent(set_pool):
    """"As this creature enters, an opponent chooses a creature type." With two
    opponents the controller decides which (CR 601.7a, 602.3a, 700.2e): Alice
    is offered Bob and Cara, names Cara, and Cara — not Bob — names the type.
    No chosen *player* is recorded (the card names none)."""
    game, oppressor = _w2g4_oppressor_table(set_pool, 3, {0, 1, 2})
    (ask,) = game.pending_choices
    assert (ask.kind, ask.player_index, ask.data["opponents"]) == ("enter_choice", 0, [1, 2])
    assert game.confirm_enter_choice(0, opponent_index=2)
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("enter_choice", 2)
    assert pick.data["needs_creature_type"]
    assert not game.confirm_enter_choice(1, creature_type="goblin"), "Bob was not chosen"
    assert game.confirm_enter_choice(2, creature_type="goblin")
    assert oppressor.metadata["chosen_creature_type"] == "goblin"
    assert "chosen_player_index" not in oppressor.metadata
    assert "Callous Oppressor: Alice has Cara choose a creature type" in game.log


def test_w2g4_callous_oppressor_with_one_opponent_or_nobody_to_ask(set_pool):
    """A duel has one answer, so the opponent is asked at once; a controller
    nobody asks takes the next opponent in turn order (Cara after Bob's turn
    seat), which is the stated default."""
    game, _ = _w2g4_oppressor_table(set_pool, 2, {0, 1})
    assert [(c.player_index, bool(c.data.get("needs_creature_type")))
            for c in game.pending_choices] == [(1, True)]

    # Bob controls it and nobody sits in his seat: Cara, the next opponent in
    # turn order after Bob, is asked the type directly.
    game, oppressor = _w2g4_oppressor_table(set_pool, 3, {0, 2}, controller=1)
    assert [(c.player_index, bool(c.data.get("needs_creature_type")))
            for c in game.pending_choices] == [(2, True)]
    # Cara is a person: asked with nothing recorded (CR 614.12a), the
    # default on the prompt.
    assert "chosen_creature_type" not in oppressor.metadata
    assert game.pending_choices[0].data["default_creature_type"]

# ==== end W2G4 ======================================================
