"""The declare-attackers window (kg3 `aidefend`): what a seat does with the
priority CR 508.2 gives it once the attack is declared and before CR 509.1's
blocks — the defending seat's ambush blocker, an ability that changes who can
block whom — and the hamper an ability puts on its own source when the
rehearsal says it pays (Swooping Talon shedding its flying for the creature
it provoked; a phase-out or shroud in front of a removal spell).

**The defect.** `ai_priority.instant_speed_window` answered no priority in
the declare-attackers step, a rehearsal started there declared no blocks on
its copy (`_run_out_the_turn` stopped at the owed declaration, so that combat
dealt no damage at all), and the activation chooser skipped every ability
that hampers its own source. So no simulated seat cast a creature to block
with, and Swooping Talon's provoke was declined whenever its target could not
block a flier. Each test drives a `_SimulatedGame` built the way
`run_ai_simulation` builds one and reads the board, the life totals, the
game's log and the report.
"""
from collections import Counter
from dataclasses import replace

import pytest

from engine import ai_simulator
from engine import ai_priority
from engine.ai_abilities import choose_activation_action
from engine.ai_combat import run_ai_combat_phase
from engine.ai_rehearsal import blocks_still_to_come
from engine.models import Permanent, PlayerState
from tests.helpers import _mk_creature_card, _nosick


@pytest.fixture
def cards(set_pool):
    pool = {}
    for code in ("LEA", "WTH", "MIR", "LGN", "VIS", "FEM"):
        pool.update(set_pool(code))
    return pool


def _table(cards, *, boards=((), ()), hands=((), ()), tapped=()):
    """A two-seat table as `run_ai_simulation` builds one — mana enforced,
    both drivers set — in AI-A's precombat main phase. *boards* hold card
    names or invented cards; *tapped* names permanents to tap."""
    players = [
        PlayerState(
            name=name, hand=[cards[card] for card in hand],
            library=[cards["Forest"]] * 8,
        )
        for name, hand in zip(("AI-A", "AI-B"), hands)
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = 0
    for seat, board in enumerate(boards):
        for entry in board:
            permanent = Permanent(card=cards[entry] if isinstance(entry, str) else entry)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
            permanent.tapped = permanent.card.name in tapped
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, report


def _declare(game, *names):
    """Walk AI-A's combat to the declare-attackers step and declare *names*
    (every creature, with none named) at AI-B — the attack the board is
    about, whatever the attack chooser would have made of it."""
    while game.current_step != "declare_attackers":
        game.advance_combat_phase()
    slots = [
        game.battlefield_index_of(permanent)
        for permanent in game.controlled_by(0)
        if permanent.is_creature and (not names or permanent.card.name in names)
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def _flier(name, power, toughness):
    return replace(
        _mk_creature_card(name, power, toughness), oracle_text="Flying", keywords=("Flying",),
    )


# --- the window ---------------------------------------------------------------


@pytest.mark.parametrize("locked_blocks, stack, expected", [
    (False, False, "declare_attackers"),
    (True, False, None),
    (False, True, "response"),
])
@pytest.mark.parametrize("seat", [0, 1])
def test_the_window_is_the_declare_attackers_step_before_the_blocks(
    cards, seat, locked_blocks, stack, expected,
):
    """CR 508.2 then 509.1: once the attack is declared each seat gets
    priority before the blocks — the attacker too (Talon's toggle). With the
    blocks declared it is the declare-blockers step's business; with an
    object on the stack it is a response (AI-A's own Bolt: AI-A passes)."""
    from engine.game_types import StackItem

    game, _report = _table(cards, boards=(("Grizzly Bears",), ()))
    _declare(game)
    assert blocks_still_to_come(game)
    game.combat_blockers_locked = locked_blocks
    if stack:
        game.stack.append(StackItem(
            card=cards["Lightning Bolt"], caster_index=0,
            target_player_index=1, target_permanent_index=None, x_value=None,
        ))
    if stack and seat == 0:
        expected = None
    assert ai_priority.instant_speed_window(game, seat) == expected


# --- the defender's ambush ----------------------------------------------------


def test_a_flash_creature_is_cast_to_block_and_kills_the_attacker(cards):
    """AI-A attacks AI-B's empty board with a 1/2. AI-B holds Benalish Knight
    (flash, first strike, 2/2) and three Plains: cast in the declare-attackers
    step, it blocks, strikes first and lives; no damage reaches AI-B."""
    game, report = _table(
        cards, boards=((_mk_creature_card("Ambushed", 1, 2),), ("Plains",) * 3),
        hands=((), ("Benalish Knight",)),
    )
    _declare(game)
    run_ai_combat_phase(game, 0)

    assert _on(game, 0, "Ambushed") is None
    assert _on(game, 1, "Benalish Knight") is not None
    assert game.players[1].life == 20
    assert report.casts_before_blocks == 1
    assert report.casts_in_combat == 1 and report.casts_on_opponents_turn == 1
    assert report.log_lines == [
        "G1 T1 AI-B cast Benalish Knight -> queued [in the declare attackers step]"
    ]
    assert "AI-B declared 1 blocker(s)" in game.log


def test_a_flash_creature_that_could_only_chump_is_held(cards):
    """The same Knight against a 5/5 at twenty life: a block would trade the
    Knight for five life, worth less than the body it keeps by waiting for
    the end step. Nothing is cast before the blocks, and AI-B takes five."""
    game, report = _table(
        cards, boards=((_mk_creature_card("Too Big", 5, 5),), ("Plains",) * 3),
        hands=((), ("Benalish Knight",)),
    )
    _declare(game)
    run_ai_combat_phase(game, 0)

    assert report.casts_before_blocks == 0
    assert [card.name for card in game.players[1].hand] == ["Benalish Knight"]
    assert game.players[1].life == 15


def test_a_flash_creature_that_cannot_block_the_attacker_is_held(cards):
    """King Cheetah (3/2, flash, no reach) against a 1/3 **flier**: casting
    it before the blocks adds no block, so it waits for the end step."""
    game, report = _table(
        cards, boards=((_flier("Out of Reach", 1, 3),), ("Forest",) * 4),
        hands=((), ("King Cheetah",)),
    )
    _declare(game)
    run_ai_combat_phase(game, 0)

    assert report.casts_before_blocks == 0
    assert [card.name for card in game.players[1].hand] == ["King Cheetah"]
    assert game.players[1].life == 19


def test_an_instant_that_adds_no_block_waits_for_the_blocks(cards):
    """A Lightning Bolt held by the defender with no creature to block with:
    killing the 2/2 adds no block, so it is not cast before the blocks —
    it is cast in the declare-blockers step, as it always was."""
    game, report = _table(
        cards, boards=(("Grizzly Bears",), ("Mountain",)), hands=((), ("Lightning Bolt",)),
    )
    _declare(game)
    run_ai_combat_phase(game, 0)

    assert report.casts_before_blocks == 0
    assert report.log_lines == [
        "G1 T1 AI-B cast Lightning Bolt -> queued [in the declare blockers step]"
    ]
    assert _on(game, 0, "Grizzly Bears") is None and game.players[1].life == 20


def test_canopy_dragon_trades_its_trample_for_flying_to_block_a_flier(cards):
    """Canopy Dragon's "{1}{G}: gains flying and loses trample until end of
    turn" hampers its own source — skipped by the chooser outright until
    kg3. Against a declared 2/2 flier it is activated before the blocks,
    the Dragon blocks and the flier dies."""
    game, report = _table(
        cards, boards=((_flier("Test Flier", 2, 2),), ("Canopy Dragon", "Forest", "Forest")),
    )
    _declare(game)
    run_ai_combat_phase(game, 0)

    assert _on(game, 0, "Test Flier") is None
    assert game.players[1].life == 20
    assert report.activations_at_instant_speed == Counter({"declare_attackers": 1})
    assert "Canopy Dragon gains flying until end of turn" in game.log


# --- Swooping Talon -----------------------------------------------------------


def test_swooping_talon_sheds_its_flying_for_the_creature_it_provoked(cards):
    """Talon (2/6 flier, "{1}: loses flying until end of turn", provoke)
    attacks into a Grizzly Bears. The provoke is taken — the Bears can block
    Talon once its flying is shed (`ai_compelled_blocks._shed_for_the_block`)
    — and in the declare-attackers step AI-A pays {1}: the Bears must block,
    and dies. Talon is tapped (it attacked), and its {1} is no {T} cost."""
    game, report = _table(
        cards, boards=(("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",)),
    )
    _declare(game, "Swooping Talon")
    run_ai_combat_phase(game, 0)

    assert "Grizzly Bears blocks Swooping Talon this combat if able" in game.log
    assert "Swooping Talon loses flying until end of turn" in game.log
    assert report.activations_at_instant_speed == Counter({"declare_attackers": 1})
    assert _on(game, 1, "Grizzly Bears") is None
    assert _on(game, 0, "Swooping Talon") is not None
    assert game.players[1].life == 20


def test_swooping_talon_keeps_its_flying_where_shedding_it_loses_the_fight(cards):
    """Against three Grizzly Bears a grounded 2/6 is blocked by all three and
    dies, so Talon keeps its flying (the rehearsal through the fight says so)
    and deals its 2 over them."""
    game, report = _table(
        cards, boards=(
            ("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",) * 3,
        ),
    )
    _declare(game, "Swooping Talon")
    run_ai_combat_phase(game, 0)

    assert "Swooping Talon loses flying until end of turn" not in game.log
    assert _on(game, 0, "Swooping Talon") is not None
    assert game.players[1].life == 18


def test_the_main_phase_sheds_talons_flying_when_the_fight_pays(cards):
    """The same hamper weighed by the main-phase chooser, rehearsed through
    the turn's fight (`ai_abilities._land_ability_worth`): proposed against
    one Bears, not against three."""
    game, _report = _table(
        cards, boards=(("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",)),
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Swooping Talon"

    game, _report = _table(
        cards, boards=(("Swooping Talon", "Plains", "Plains"), ("Grizzly Bears",) * 3),
    )
    assert choose_activation_action(game, 0) is None


# --- a hamper in front of a removal spell -------------------------------------


def test_rainbow_efreet_phases_out_of_a_lightning_bolt(cards):
    """"{U}{U}: This creature phases out." In response to the Bolt aimed at
    it: the Bolt has no legal target left (CR 608.2b) and the Efreet lives."""
    game, report = _table(
        cards, boards=(("Mountain",), ("Rainbow Efreet", "Island", "Island")),
        hands=(("Lightning Bolt",), ()),
    )
    efreet = _on(game, 1, "Rainbow Efreet")
    game.players[0].mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[efreet.permanent_id])

    assert result.supported, result.details
    assert [p.card.name for p in game.players[1].phased_out] == ["Rainbow Efreet"]
    assert report.activations_at_instant_speed == Counter({"response": 1})
    assert report.log_lines == [
        "G1 T1 AI-B activate Rainbow Efreet -> queued [in response to Lightning Bolt]"
    ]


def test_deep_spawn_takes_shroud_in_front_of_a_terror(cards):
    """"{U}: gains shroud until end of turn and doesn't untap during your
    next untap step. Tap this creature." Terror fizzles; the Spawn lives."""
    game, report = _table(
        cards, boards=(("Swamp", "Swamp"), ("Deep Spawn", "Island")),
        hands=(("Terror",), ()),
    )
    spawn = _on(game, 1, "Deep Spawn")
    game.players[0].mana_pool.update({"B": 1, "C": 1})

    result = game.cast_from_hand(0, "Terror", target_permanent_ids=[spawn.permanent_id])

    assert result.supported, result.details
    assert _on(game, 1, "Deep Spawn") is spawn
    assert [card.name for card in game.players[0].graveyard] == ["Terror"]
    assert report.activations_at_instant_speed == Counter({"response": 1})


def test_a_tapped_creatures_regeneration_is_raised_in_front_of_a_bolt(cards):
    """A tapped Drudge Skeletons (it attacked) still has "{B}: Regenerate"
    — no {T} in the cost — and the instant-speed chooser passed over every
    tapped permanent. AI-B's Bolt in AI-A's turn is answered with the
    shield, and the Skeletons are kept."""
    game, report = _table(
        cards, boards=(("Drudge Skeletons", "Swamp"), ("Mountain",)),
        hands=((), ("Lightning Bolt",)), tapped=("Drudge Skeletons",),
    )
    skeletons = _on(game, 0, "Drudge Skeletons")
    game.players[1].mana_pool["R"] = 1

    result = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[skeletons.permanent_id])

    assert result.supported, result.details
    assert _on(game, 0, "Drudge Skeletons") is skeletons
    assert report.activations_at_instant_speed == Counter({"response": 1})


def test_an_own_hamper_with_nothing_to_gain_is_not_activated(cards, set_pool):
    """Ribbon Snake's "{2}: loses flying until end of turn" is printed for an
    opponent to pay; its own controller, given priority in the opponent's
    end step with mana up, has nothing to gain and pays nothing."""
    cards.update(set_pool("PCY"))
    game, report = _table(cards, boards=((), ("Ribbon Snake", "Island", "Island")))
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()

    assert report.activations_at_instant_speed == Counter()
    assert not _on(game, 1, "Island").tapped
