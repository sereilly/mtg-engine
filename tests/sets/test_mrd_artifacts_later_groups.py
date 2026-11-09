"""Mirrodin artifacts, the later groups' sections.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Drive list: Rustspore Ram and Duskworker, the two artifact creatures among
# W1G2's supported-on-arrival cards, each given a headless game.
from engine import Game as _W1G2Game
from engine.aura_attachment import attach_aura as _w1g2_attach_aura
from engine.models import Permanent as _W1G2Permanent
from engine.models import PlayerState as _W1G2PlayerState

from tests.helpers import declare_attack as _w1g2_declare_attack
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    alice = _W1G2PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8)
    bob = _W1G2PlayerState(name="Bob", library=[lea["Island"]] * 8)
    game = _W1G2Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g2_put(game, seat, card, *, wearing=None):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    if wearing is not None:
        _w1g2_attach_aura(permanent, wearing)
        game._recompute_continuous_effects()
    return permanent


def _w1g2_drain(game):
    """Answer what blocks the game and drain the stack, until nothing does."""
    for _ in range(20):
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        elif game.stack:
            _w1g2_resolve_stack(game)
        else:
            return


def test_w1g2_rustspore_ram_destroys_an_equipment_as_it_enters(set_pool):
    """"When this creature enters, destroy target Equipment." The target is
    the trigger's (CR 603.3d): an opponent's Equipment is destroyed and the
    creature it equipped loses the bonus; with no Equipment anywhere the
    trigger is removed from the stack and nothing else is touched."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    _w1g2_put(game, 1, mrd["Leonin Scimitar"], wearing=bear)
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert [card.name for card in bob.graveyard] == ["Leonin Scimitar"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    game, _alice, bob = _w1g2_table(set_pool, hand=[mrd["Rustspore Ram"]])
    bear = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Rustspore Ram").supported
    _w1g2_drain(game)
    assert bob.graveyard == [] and game.is_on_battlefield(bear)
    assert any("no legal target (603.3d)" in line for line in game.log)


def test_w1g2_duskworker_regenerates_when_blocked_and_pumps_for_three(set_pool):
    """"Whenever this creature becomes blocked, regenerate it." Blocked by a
    Craw Wurm, the 2/2 takes lethal damage and regenerates (CR 701.19a:
    tapped, damage removed) instead of dying. "{3}: This creature gets +1/+0
    until end of turn." pays from the pool and pumps."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g2_table(set_pool)
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    _w1g2_put(game, 1, lea["Craw Wurm"])
    _w1g2_declare_attack(game, 0, blocks={0: 0})
    _w1g2_drain(game)
    assert duskworker.regeneration_shield == 1
    game.advance_combat_phase()
    _w1g2_drain(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(duskworker)
    assert duskworker.damage_marked == 0 and duskworker.tapped
    assert any(line == "Duskworker regenerated" for line in game.log)

    game, alice, _bob = _w1g2_table(set_pool)
    game.enforce_mana_costs = True
    duskworker = _w1g2_put(game, 0, mrd["Duskworker"])
    alice.mana_pool.update({"C": 3})
    result = game.activate_permanent_ability(
        0, "Duskworker", permanent_index=game.battlefield_index_of(duskworker),
    )
    assert result.supported, result.details
    _w1g2_drain(game)
    assert (duskworker.effective_power, duskworker.effective_toughness) == (3, 2)
    assert sum(alice.mana_pool.values()) == 0

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _w1g10_Game, PlayerState as _w1g10_PlayerState
from engine.models import Permanent as _w1g10_Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, hand=(), their_hand=()):
    """Two seats with Forests to draw, costs unenforced, P2 active so the
    next turn begun is P1's."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20, hand=list(hand)),
        _w1g10_PlayerState("P2", library=[forest] * 20, hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.turn = 1
    return game


def _w1g10_put(game, seat, card):
    permanent = _w1g10_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g10_mindstorm_crown_draws_when_the_turn_began_with_an_empty_hand(set_pool):
    game = _w1g10_table(set_pool)
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()            # P1: untap, upkeep (the Crown), draw step
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    # One from the Crown, one from the draw step.
    assert len(p1.hand) == 2
    assert "P1 drew 1 card(s) (Mindstorm Crown)" in game.log


def test_w1g10_mindstorm_crown_deals_one_when_the_turn_began_with_a_card(set_pool):
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest, forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    # "If you had a card in hand" is one *or more*: two cards still hurt.
    assert p1.life == 19
    assert len(p1.hand) == 3          # only the draw step drew
    assert "Mindstorm Crown dealt 1 damage to P1" in game.log


def test_w1g10_mindstorm_crown_reads_the_hand_the_turn_began_with(set_pool):
    """The 2004-12-01 ruling: two Crowns and an empty hand at the start of the
    turn draw two cards — the first Crown's draw does not turn the second
    into a damage trigger, because the hand asked about is the turn's first."""
    game = _w1g10_table(set_pool)
    crown = set_pool("MRD")["Mindstorm Crown"]
    _w1g10_put(game, 0, crown)
    _w1g10_put(game, 0, crown)
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    assert len(p1.hand) == 3
    assert game.log.count("P1 drew 1 card(s) (Mindstorm Crown)") == 2


def test_w1g10_mindstorm_crown_ignores_the_hand_at_the_upkeep(set_pool):
    """A hand emptied after the turn began is still a turn that began with a
    card: the record, not the hand at resolution, is asked."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.begin_turn_bookkeeping(0)
    game.turn += 1
    game.players[0].hand.clear()      # gone before the upkeep asks
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 19
    assert not game.players[0].hand


def test_w1g10_platinum_angel_keeps_its_controller_in_the_game(set_pool):
    """A Lightning Bolt to 0 life with the Angel out: no loss, and the game
    goes on; the Angel dies and the next state-based check takes the game.
    The whole of CR 104.3 is in tests/rules/test_mrd_w1g10_cant_lose_the_game.py."""
    game = _w1g10_table(set_pool, their_hand=[set_pool("LEA")["Lightning Bolt"]])
    angel = _w1g10_put(game, 0, set_pool("MRD")["Platinum Angel"])
    game.players[0].life = 2
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g10_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == -1
    assert not game.players[0].lost and not game.is_game_over()
    game.remove_from_battlefield(angel)
    game._permanent_to_graveyard(game.players[0], angel)
    game.check_state_based_actions()
    assert game.players[0].lost
    assert game.get_winner() is game.players[1]

def _w1g10_sifter_table(set_pool, top0, top1):
    """P1 controls Timesifter; each library is the named cards, top first."""
    lea = set_pool("LEA")
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[lea[name] for name in top0]),
        _w1g10_PlayerState("P2", library=[lea[name] for name in top1]),
    ])
    game.enforce_mana_costs = False
    sifter = _w1g10_put(game, 0, set_pool("MRD")["Timesifter"])
    return game, sifter


def test_w1g10_timesifter_gives_the_greatest_mana_value_an_extra_turn(set_pool):
    game, sifter = _w1g10_sifter_table(
        set_pool, ["Forest", "Forest", "Forest"], ["Shivan Dragon", "Forest", "Forest"],
    )
    game.active_player_index = 0
    game.turn = 1
    game.resolve_upkeep(0)            # P1's upkeep: each upkeep, not only yours
    _w1g10_resolve_stack(game)
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    assert [card.name for card in game.players[1].exile] == ["Shivan Dragon"]
    assert "P2 gained an extra turn" in game.log
    # The extra turn comes after this one, and then the turn that was next
    # anyway (the 2004-12-01 ruling: "Remember which player would have taken
    # the next turn").
    game.remove_from_battlefield(sifter)
    game._permanent_to_graveyard(game.players[0], sifter)
    game.players[0].library.extend([set_pool("LEA")["Forest"]] * 5)
    game.players[1].library.extend([set_pool("LEA")["Forest"]] * 5)
    assert game.start_next_turn() == 1
    assert game.current_turn_is_extra
    assert game.start_next_turn() == 1
    assert not game.current_turn_is_extra
    assert game.start_next_turn() == 0


def test_w1g10_timesifter_ties_repeat_among_the_tied_players(set_pool):
    game, _ = _w1g10_sifter_table(
        set_pool, ["Grizzly Bears", "Forest"], ["Grizzly Bears", "Hill Giant"],
    )
    game.resolve_upkeep(0)
    _w1g10_resolve_stack(game)
    assert "Timesifter: P1, P2 tied at mana value 2 and repeat the process" in game.log
    assert len(game.players[0].exile) == 2 and len(game.players[1].exile) == 2
    assert game.extra_turn_queue == [1]


def test_w1g10_timesifter_a_player_who_exiles_nothing_cannot_win(set_pool):
    """The ruling: "If a player fails to exile a card, they can't take the
    extra turn." The tie at 0 is repeated; P2 has nothing left to exile, so P1
    is the only one with a card, and wins."""
    game, _ = _w1g10_sifter_table(set_pool, ["Forest", "Forest"], ["Island"])
    game.resolve_upkeep(1)
    _w1g10_resolve_stack(game)
    assert "Timesifter: P2 has no card to exile" in game.log
    assert game.extra_turn_queue == [0]

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W2G1 ==========================================================
# W2G1's tests go between this line and the "end W2G1" line.
#
# Mindslaver — "{4}, {T}, Sacrifice Mindslaver: You control target player
# during that player's next turn." The CR 723 rules themselves are in
# tests/rules/test_mrd_w2g1_controlling_a_player.py; these are the card.
from engine import Game as _w2g1_Game, PlayerState as _w2g1_PlayerState
from engine.models import Permanent as _w2g1_Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile
from engine.targeting import derive_activation_spec as _w2g1_activation_spec
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_table(set_pool, *, their_hand=()):
    lea = set_pool("LEA")
    game = _w2g1_Game(players=[
        _w2g1_PlayerState("P1", library=[lea["Forest"]] * 20),
        _w2g1_PlayerState("P2", library=[lea["Forest"]] * 20, hand=list(their_hand)),
    ])
    game.active_player_index = 0
    game.turn = 1
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _w2g1_put(game, seat, card):
    permanent = _w2g1_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w2g1_mindslaver_picks_a_player_and_costs_four_tap_and_itself(set_pool):
    slaver = set_pool("MRD")["Mindslaver"]
    program = _w2g1_compile(slaver)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert ability.cost.mana["generic"] == 4
    assert ability.cost.requires_tap and ability.cost.sacrifice_self
    assert _w2g1_activation_spec(ability)["kind"] == "player"


def test_w2g1_mindslaver_paid_for_controls_the_opponents_next_turn(set_pool):
    lea = set_pool("LEA")
    game = _w2g1_table(set_pool, their_hand=[lea["Grizzly Bears"]])
    game.enforce_mana_costs = True
    _w2g1_put(game, 0, set_pool("MRD")["Mindslaver"])
    for _ in range(4):
        _w2g1_put(game, 0, lea["Forest"])
    for land in [p for p in game.players[0].battlefield if p.card.name == "Forest"]:
        assert game.tap_land_for_mana(0, "Forest", permanent_id=land.permanent_id)
    assert game.players[0].mana_pool.get("G") == 4
    result = game.activate_permanent_ability(0, "Mindslaver", target_player_index=1)
    assert result.supported, result.details
    _w2g1_resolve_stack(game)
    assert "Mindslaver" in [card.name for card in game.players[0].graveyard]
    assert "P1 will control P2 during P2's next turn" in game.log
    assert game.decider_of(1) == 1    # not yet: P1's own turn goes on
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    assert (game.active_player_index, game.decider_of(1)) == (1, 0)
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    assert game.decider_of(1) == 1


def test_w2g1_an_ai_controlling_the_opponent_casts_nothing_for_them(set_pool):
    """The controlled seat's whole main phase as the simulator plays it: the
    AI deciding for it plays no land, casts no creature and attacks with
    nothing (``engine/ai_player_control.py``); uncontrolled, it would."""
    from engine.ai_simulator import SimulationReport, _play_land_drops, _play_casts
    from engine.ai_declarations import choose_attackers

    lea = set_pool("LEA")
    game = _w2g1_table(set_pool, their_hand=[lea["Forest"], lea["Grizzly Bears"]])
    game.enforce_mana_costs = False
    bears = _w2g1_put(game, 1, lea["Grizzly Bears"])
    _w2g1_put(game, 0, set_pool("MRD")["Mindslaver"])
    assert game.activate_permanent_ability(0, "Mindslaver", target_player_index=1).supported
    _w2g1_resolve_stack(game)
    game.start_next_turn()
    _w2g1_resolve_stack(game)
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_land_drops(game, 1, report, 1, 1)
    _play_casts(game, 1, report, 1, 1)
    assert report.lands_played == 0
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert choose_attackers(game, 1) == []
    game.player_controls.clear()
    _play_land_drops(game, 1, report, 1, 1)
    assert report.lands_played >= 1
    assert bears in list(game.controlled_by(1))

# ==== end W2G1 ======================================================
