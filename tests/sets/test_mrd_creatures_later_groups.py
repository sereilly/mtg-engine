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

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def test_w1g5_arc_slogger_exiles_ten_to_deal_two(set_pool):
    """Drive list. "{R}, Exile the top ten cards of your library: This
    creature deals 2 damage to any target." With twelve cards the cost is
    paid and Bob takes 2; with nine it cannot be (CR 601.2h): nothing is paid,
    nothing exiled."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    for library, life, left in ((12, 18, 2), (9, 20, 9)):
        alice = _W1G5PlayerState(name="Alice", library=[lea["Plains"]] * library)
        bob = _W1G5PlayerState(name="Bob", library=[lea["Island"]] * 6)
        game = _W1G5Game(players=[alice, bob])
        game.enforce_mana_costs = True
        game.interactive_seats = {0}
        game.active_player_index = game.priority_player_index = 0
        game.current_phase = "main"
        game.current_turn_phase, game.current_step = "precombat_main", None
        slogger = _W1G5Permanent(card=mrd["Arc-Slogger"])
        game._put_permanent_onto_battlefield(0, slogger, None)
        slogger.metadata["summoning_sickness_turn"] = -99
        game._sync_control()
        alice.mana_pool["R"] = 1
        result = game.activate_permanent_ability(
            0, "Arc-Slogger", permanent_index=game.battlefield_index_of(slogger),
            ability_index=0, target_player_index=1,
        )
        assert result.supported is (library >= 10), result.details
        _w1g5_resolve_stack(game)
        assert (bob.life, len(alice.library)) == (life, left)
        assert len(alice.exile) == library - left

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


def _w1g8_usable_lines(game, perm):
    return [
        ability.source_line
        for ability in game.usable_abilities_of(perm, card=perm.effective_card)
    ]


def test_w1g8_quicksilver_elemental_gains_an_opponents_activated_abilities(set_pool):
    """2004-12-01: it gains the activated abilities of any creature it can
    target, whoever controls it; only activated ones (Shivan Dragon's flying
    stays behind); "this creature" in them is the Elemental. Its blue pays the
    gained {R} cost (its second ability, CR 609.4b), and the abilities are gone
    after the cleanup step (CR 514.2)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (quick, shivan, sorcerer) = _w1g8_board(
        set_pool, [mrd["Quicksilver Elemental"]],
        [lea["Shivan Dragon"], lea["Prodigal Sorcerer"]],
    )
    game.enforce_mana_costs = True
    game.players[0].mana_pool["U"] = 4
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", target_permanent_ids=[shivan.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    gained = _w1g8_usable_lines(game, quick)
    assert gained[1:] == ["{R}: This creature gets +1/+0 until end of turn."]
    assert not game._has_keyword(quick, "flying")
    firebreathing = gained.index("{R}: This creature gets +1/+0 until end of turn.")
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", ability_index=firebreathing
    ).supported
    _w1g8_resolve_stack(game)
    assert quick.effective_power == 4 and shivan.effective_power == 5
    assert game.players[0].mana_pool["U"] == 2
    # Collected from a second creature (2004-10-04: "collecting abilities from
    # multiple creatures"), and the ping is the Elemental's own.
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", ability_index=0,
        target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)
    gained = _w1g8_usable_lines(game, quick)
    ping = gained.index("{T}: This creature deals 1 damage to any target.")
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", ability_index=ping, target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 19 and quick.tapped and not sorcerer.tapped
    assert "Quicksilver Elemental dealt 1 damage to B" in game.log
    game.resolve_cleanup_step(0)
    assert len(_w1g8_usable_lines(game, quick)) == 1


def test_w1g8_quicksilver_elemental_uses_its_own_name_for_the_targets(set_pool):
    """The reminder text: "If any of the abilities use that creature's name,
    use this creature's name instead." Lord of Tresserhorn's "{B}: Regenerate
    Lord of Tresserhorn." becomes the Elemental's own regeneration."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    lord_card = set_pool("ALL")["Lord of Tresserhorn"]
    game, (quick, lord) = _w1g8_board(
        set_pool, [mrd["Quicksilver Elemental"]], [lord_card], hand=[lea["Fireball"]],
    )
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", target_permanent_ids=[lord.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    gained = _w1g8_usable_lines(game, quick)
    assert gained[1:] == ["{B}: Regenerate Quicksilver Elemental."]
    assert game.activate_permanent_ability(
        0, "Quicksilver Elemental", ability_index=1
    ).supported
    _w1g8_resolve_stack(game)
    # The shield is the Elemental's: four damage destroys nothing, it
    # regenerates (CR 701.19a).
    assert game.cast_from_hand(
        0, "Fireball", x_value=4, target_permanent_ids=[quick.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert game.is_on_battlefield(quick) and quick.tapped


def test_w1g8_quicksilver_blue_pays_only_its_own_abilities(set_pool):
    """The spending permission is scoped to this creature's abilities: blue
    still cannot pay a red pip anywhere else (a Shivan Dragon's own {R})."""
    from engine.restricted_mana import ACTIVATE, PaymentPurpose

    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (quick, shivan, _island) = _w1g8_board(
        set_pool, [mrd["Quicksilver Elemental"], lea["Shivan Dragon"], lea["Island"]],
    )
    game.enforce_mana_costs = True
    assert _w1g8_board_can_pay(
        game, 0, {"R": 1}, purpose=PaymentPurpose(ACTIVATE, source=quick),
    )
    assert not _w1g8_board_can_pay(
        game, 0, {"R": 1}, purpose=PaymentPurpose(ACTIVATE, source=shivan),
    )
    game.players[0].mana_pool["U"] = 1
    refused = game.activate_permanent_ability(0, "Shivan Dragon")
    assert not refused.supported and "insufficient mana" in refused.details
    assert game.players[0].mana_pool["U"] == 1

def test_w1g8_spikeshot_goblin_deals_its_power(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (goblin,) = _w1g8_board(set_pool, [mrd["Spikeshot Goblin"]], hand=[lea["Giant Growth"]])
    game.cast_from_hand(0, "Giant Growth", target_permanent_ids=[goblin.permanent_id])
    _w1g8_resolve_stack(game)
    assert game.activate_permanent_ability(
        0, "Spikeshot Goblin", target_player_index=1
    ).supported
    _w1g8_resolve_stack(game)
    assert game.players[1].life == 16


def test_w1g8_auriok_transfixer_taps_an_artifact(set_pool):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, (transfixer, ring) = _w1g8_board(
        set_pool, [mrd["Auriok Transfixer"]], [lea["Sol Ring"]],
    )
    assert game.activate_permanent_ability(
        0, "Auriok Transfixer", target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g8_resolve_stack(game)
    assert ring.tapped and transfixer.tapped


# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_peacekeeper(set_pool, lives, *, interactive=()):
    """Loxodon Peacekeeper on seat 0, the seats at *lives*."""
    keeper = _w1g9_Permanent(card=set_pool("MRD")["Loxodon Peacekeeper"])
    players = [
        _w1g9_PlayerState(name=f"P{seat}", battlefield=[keeper] if seat == 0 else [])
        for seat in range(len(lives))
    ]
    for player, life in zip(players, lives):
        player.life = life
    game = _w1g9_Game(players=players)
    game.interactive_seats = set(interactive)
    return game, keeper


def test_w1g9_loxodon_peacekeeper_goes_to_the_lowest_life_total(set_pool):
    """"At the beginning of your upkeep, the player with the lowest life total
    gains control of this creature." Read off the life totals as it resolves:
    at three seats the one lowest takes it, and on its new controller's upkeep
    it moves on when somebody else is lower."""
    game, keeper = _w1g9_peacekeeper(set_pool, [20, 12, 15])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 1
    assert "P1 gains control of Loxodon Peacekeeper" in game.log

    game.players[2].life = 3
    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 2


def test_w1g9_loxodon_peacekeeper_stays_with_a_controller_who_is_lowest(set_pool):
    game, keeper = _w1g9_peacekeeper(set_pool, [7, 20])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 0
    assert "Loxodon Peacekeeper is already controlled by P0" in game.log


def test_w1g9_loxodon_peacekeeper_tie_is_its_controllers_choice(set_pool):
    """"If two or more players are tied for lowest life total, you choose one
    of them, and that player gains control of this creature." An interactive
    controller is offered exactly the tied seats — not the player at 20 — and
    names one; nothing changes hands until the answer."""
    game, keeper = _w1g9_peacekeeper(set_pool, [10, 10, 20], interactive=(0,))
    game.resolve_upkeep(0)
    assert game.resolve_top_of_stack() is False
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("player_choice", 0)
    ]
    assert game.pending_choices[0].data["seats"] == [0, 1]
    assert game.controller_index_of(keeper) == 0
    assert game.confirm_player_choice(0, 2) is False   # not tied
    assert game.confirm_player_choice(0, 1) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 1


def test_w1g9_loxodon_peacekeeper_tie_default_keeps_it(set_pool):
    """A controller nobody asks names itself among the tied seats
    (``ai_prompt_picks.player_choice_pick``): the other answer gives the
    creature away."""
    game, keeper = _w1g9_peacekeeper(set_pool, [10, 10])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 0
    assert "Loxodon Peacekeeper: chose P0" in game.log

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _w1g10_Game, PlayerState as _w1g10_PlayerState
from engine.models import Permanent as _w1g10_Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_fatespinner_upkeep(set_pool, *, interactive=False):
    """P1 controls Fatespinner; P2's turn begins and its upkeep trigger is put
    on the stack (and, for a person, resolved to its question)."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20),
        _w1g10_PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {1}
    spinner = _w1g10_Permanent(card=set_pool("MRD")["Fatespinner"])
    game._put_permanent_onto_battlefield(0, spinner, None)
    game.active_player_index = 0
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.resolve_untap_step(1)
    game.resolve_upkeep(1)
    return game


def _w1g10_answer(game, mode_index):
    game.resolve_top_of_stack()          # held on the opponent's question
    prompt = game.pending_choice_of("mode_choice", 1)
    assert prompt is not None
    assert prompt.data["labels"] == ["draw step", "main phase", "combat phase"]
    assert game.resolve_pending_choice("mode_choice", 1, mode_index=mode_index)
    _w1g10_resolve_stack(game)


def test_w1g10_fatespinner_unasked_opponent_skips_the_draw_step(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool)
    _w1g10_resolve_stack(game)
    game.resolve_draw_step(1)
    assert game.players[1].hand == []
    assert "P2 skipped draw step" in game.log
    assert game.enter_next_turn_phase("beginning") == "precombat_main"


def test_w1g10_fatespinner_main_phase_skips_both_main_phases(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 1)
    game.resolve_draw_step(1)
    assert len(game.players[1].hand) == 1      # the draw step was not chosen
    # Straight from the beginning phase into combat, and from combat to the
    # ending phase: "each instance" is both main phases.
    assert game.enter_next_turn_phase("beginning") == "combat"
    assert game.current_turn_phase == "combat"
    assert game.next_unskipped_phase_after("combat") == "ending"


def test_w1g10_fatespinner_combat_phase_is_skipped_on_every_road(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 2)
    game.resolve_draw_step(1)
    assert game.enter_next_turn_phase("beginning") == "precombat_main"
    # The AI's combat walker names combat from the main phase rather than
    # asking the plan; the skip is honoured there too (CR 500.11).
    game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main"
    assert "P2 skipped the combat phase" in game.log


def test_w1g10_fatespinner_skips_a_combat_phase_added_after_it_resolved(set_pool):
    """The ruling (2004-12-01): "This is true even if a new step or phase is
    added to the turn after the ability resolves." An additional combat phase
    after the postcombat main phase (Relentless Assault's shape, CR 500.8) is
    skipped too."""
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 2)
    game.resolve_draw_step(1)
    assert game.enter_next_turn_phase("beginning") == "precombat_main"
    assert game.enter_next_turn_phase() == "postcombat_main"
    assert game.add_extra_phase(after_phase="postcombat_main", phase_name="combat")
    assert game.next_unskipped_phase_after("postcombat_main") == "ending"


def test_w1g10_fatespinner_skip_ends_with_its_turn(set_pool):
    """"This turn": the cleanup sweep ends the record, so the opponent's next
    turn has its draw step."""
    game = _w1g10_fatespinner_upkeep(set_pool)
    _w1g10_resolve_stack(game)
    assert game.skip_step_counts
    game.expire_stamped_phase_skips()
    assert not game.skip_step_counts and not game.skip_phase_counts


def test_w1g10_fatespinner_does_not_trigger_on_its_controllers_upkeep(set_pool):
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20),
        _w1g10_PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    spinner = _w1g10_Permanent(card=set_pool("MRD")["Fatespinner"])
    game._put_permanent_onto_battlefield(0, spinner, None)
    game.resolve_upkeep(0)
    assert not game.stack

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
