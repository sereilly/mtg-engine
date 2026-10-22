"""A simulated seat is given priority where the engine gives it, and answers
it with the chooser the web AI seat answers with.

Before round 4 the AI simulator's seats cast in their own main phases and
nowhere else: the engine's headless window was "both players pass", so no
instant had ever been cast in a simulated game in response to anything, during
combat, or on the opponent's turn (0 of 273 instants cast over the seven
seeded runs). The engine now asks `Game.priority_driver` for each player in
turn before every resolution and as every step's window closes
(`Game.offer_priority`), and the simulator's driver answers through
`ai_policy.choose_combat_instant_cast_action` in the three windows it takes
(`ai_simulator._instant_speed_window`).

Each test plays a real cast or step on a `_SimulatedGame` built the way
`run_ai_simulation` builds one — mana enforced, both drivers set — and reads
the board, the graveyards, the life totals and the report.
"""
from collections import Counter

import pytest

from engine import ai_rehearsal, ai_simulator
from engine.ai_combat import run_ai_combat_phase
from engine.ai_actions import CastAction
from engine.models import Permanent, PlayerState
from tests.helpers import CARDS_BY_NAME, _nosick


def _table(*, active=0, hands=((), ()), boards=((), ())):
    """A two-seat table as `run_ai_simulation` builds one, with *active*'s
    precombat main phase in progress."""
    players = []
    for name, hand in zip(("AI-A", "AI-B"), hands):
        players.append(PlayerState(
            name=name,
            hand=[CARDS_BY_NAME[card] for card in hand],
            library=[CARDS_BY_NAME["Forest"]] * 8,
        ))
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    game.priority_driver = ai_simulator._priority_answerer(game, report, 1, [1])
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate(boards):
        for name in board:
            permanent = Permanent(card=CARDS_BY_NAME[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            # After it has entered: entering stamps the turn it arrived.
            _nosick(permanent)
    return game, report


def _on(game, seat, name):
    return next(
        (p for p in game.controlled_by(seat) if p.card.name == name), None,
    )


def _graveyard(game, seat):
    return sorted(card.name for card in game.players[seat].graveyard)


def test_a_seat_answers_the_other_seats_spell_before_it_resolves():
    """CR 117.4 / 117.7: AI-A's Lightning Bolt at AI-B's Grizzly Bears waits
    for both seats to pass, AI-B casts Giant Growth on top of it, the Growth
    resolves first, and the Bears take the Bolt as a 5/5 and live."""
    game, report = _table(
        hands=(("Lightning Bolt",), ("Giant Growth",)),
        boards=(("Mountain",), ("Grizzly Bears", "Forest")),
    )
    bears = _on(game, 1, "Grizzly Bears")
    game.players[0].mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])

    assert result.supported, result.details
    assert _on(game, 1, "Grizzly Bears") is bears
    assert bears.damage_marked == 3
    assert _graveyard(game, 1) == ["Giant Growth"]
    assert _graveyard(game, 0) == ["Lightning Bolt"]
    assert _on(game, 1, "Forest").tapped
    assert report.casts_in_response == 1
    assert report.casts_on_opponents_turn == 1
    assert report.casts_in_combat == 0
    assert report.log_lines == [
        "G1 T1 AI-B cast Giant Growth -> queued [in response to Lightning Bolt]"
    ]


def test_a_counterspell_is_cast_at_the_spell_it_counters():
    """The window a counterspell exists for, which no simulated game had: the
    Serra Angel never reaches the battlefield."""
    game, report = _table(
        hands=(("Serra Angel",), ("Counterspell",)),
        boards=((), ("Island", "Island")),
    )
    game.players[0].mana_pool.update({"W": 5})

    result = game.cast_from_hand(0, "Serra Angel")

    assert result.supported, result.details
    assert _on(game, 0, "Serra Angel") is None
    assert _graveyard(game, 0) == ["Serra Angel"]
    assert _graveyard(game, 1) == ["Counterspell"]
    assert report.casts_in_response == 1
    assert report.log_lines[0].startswith(
        "G1 T1 AI-B cast Counterspell -> queued [in response to Serra Angel]"
    )


def test_a_counter_war_counters_the_counterspell_not_the_casters_own_spell():
    """CR 117.3c, both ways: AI-A's Ancestral Recall is met by AI-B's
    Counterspell, and AI-A answers *that* with its own — aimed at the
    Counterspell, which is the spell worth countering. The chooser left a
    spell-targeting spell's target to the engine's bare-announcement default,
    whose list puts the caster's own seat first: in the first seeded PLS run
    with windows a Gainsay countered its caster's own Sisay's Ingenuity
    under the Confound it was cast to answer."""
    game, report = _table(
        hands=(("Ancestral Recall", "Counterspell"), ("Counterspell",)),
        boards=(("Island", "Island"), ("Island", "Island")),
    )
    game.players[0].mana_pool["U"] = 1

    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=0)

    assert result.supported, result.details
    assert _graveyard(game, 0) == ["Ancestral Recall", "Counterspell"]
    assert _graveyard(game, 1) == ["Counterspell"]
    # The Recall resolved: three cards drawn, nothing left in hand but them.
    assert [card.name for card in game.players[0].hand] == ["Forest"] * 3
    assert report.casts_in_response == 2
    assert [line.split(" -> ")[0] for line in report.log_lines] == [
        "G1 T1 AI-B cast Counterspell",
        "G1 T1 AI-A cast Counterspell",
    ]
    assert report.log_lines[1].endswith("[in response to Counterspell]")


def test_the_defending_seat_casts_in_the_declare_blockers_step():
    """CR 509.2: once blockers are declared each player gets priority before
    damage. AI-A swings with a Grizzly Bears into an empty board; AI-B, with a
    Lightning Bolt and a Mountain, kills the attacker before it deals its
    damage."""
    game, report = _table(
        hands=((), ("Lightning Bolt",)),
        boards=(("Grizzly Bears",), ("Mountain",)),
    )

    run_ai_combat_phase(game, 0)

    assert _on(game, 0, "Grizzly Bears") is None
    assert _graveyard(game, 0) == ["Grizzly Bears"]
    assert _graveyard(game, 1) == ["Lightning Bolt"]
    assert game.players[1].life == 20
    assert report.casts_in_combat == 1
    assert report.casts_on_opponents_turn == 1
    assert report.casts_in_response == 0
    assert report.log_lines == [
        "G1 T1 AI-B cast Lightning Bolt -> queued [in the declare blockers step]"
    ]


def test_the_opponent_casts_its_removal_in_the_end_step():
    """The creature AI-A cast this turn cannot attack, so the first moment
    AI-B has priority with it on the battlefield is AI-A's end step — and
    Terror is cast there, before AI-A untaps."""
    game, report = _table(
        hands=((), ("Terror",)),
        boards=(("Grizzly Bears",), ("Swamp", "Swamp")),
    )
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()

    assert _on(game, 0, "Grizzly Bears") is None
    assert _graveyard(game, 1) == ["Terror"]
    assert report.casts_on_opponents_turn == 1
    assert report.casts_in_response == 0 and report.casts_in_combat == 0
    assert report.log_lines == ["G1 T1 AI-B cast Terror -> queued [in the end step]"]


def test_a_refused_response_is_counted_and_the_window_goes_on(monkeypatch):
    """Rule 3 of the round: a response the engine refuses is now possible, so
    it is driven. The seat's taps are spent, nothing goes on the stack, the
    refusal is counted like ``refused_casts`` — and the spell it would have
    answered still resolves."""
    game, report = _table(
        hands=(("Lightning Bolt",), ("Terror",)),
        boards=(("Mountain",), ("Swamp", "Swamp", "Grizzly Bears")),
    )
    bears = _on(game, 1, "Grizzly Bears")
    # Terror aimed at nothing at all: refused at announcement (CR 601.2c).
    refused = CastAction(
        card_name="Terror", target_player_index=None, x_value=None,
        land_tap_indices=(), score=5.0, hand_index=0,
    )
    monkeypatch.setattr(
        ai_simulator, "choose_combat_instant_cast_action",
        lambda table, seat: refused if seat == 1 else None,
    )
    monkeypatch.setattr(
        ai_simulator, "holds_an_instant_it_could_pay_for", lambda table, seat: True,
    )
    game.players[0].mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])

    assert result.supported, result.details
    assert _on(game, 1, "Grizzly Bears") is None
    assert [card.name for card in game.players[1].hand] == ["Terror"]
    assert report.casts_in_response == 0
    assert sum(report.refused_instant_casts.values()) >= 1
    assert all(key.startswith("Terror: ") for key in report.refused_instant_casts)
    assert report.log_lines[0].startswith("G1 T1 AI-B cast Terror -> ")
    assert "[in response to Lightning Bolt]" in report.log_lines[0]


def test_a_copy_of_the_game_is_never_answered_for():
    """A rehearsal deep-copies the game, driver and all. The driver answers
    only for the table it was made for, so a copy's priority is passed — as
    every copy's was before there was a driver — and a response is never
    carried out on a scratch table, nor the real report written from one."""
    game, report = _table(
        hands=((), ("Lightning Bolt",)),
        boards=(("Grizzly Bears",), ("Mountain",)),
    )
    game._set_phase_and_step("ending", "end")
    copy = ai_rehearsal.scratch_copy(game)

    assert copy.priority_driver is game.priority_driver
    assert copy.priority_driver(copy, 1) is False
    assert [card.name for card in copy.players[1].hand] == ["Lightning Bolt"]
    assert report.priority_offers == 0 and report.log_lines == []


def test_a_regeneration_shield_is_raised_in_front_of_the_burn_spell():
    """CR 117.1b, an ability rather than a spell: AI-A Bolts AI-B's Drudge
    Skeletons, and AI-B pays {B} to regenerate them before the Bolt resolves
    — the ability on top resolves first, so the 3 damage destroys a creature
    with a shield and it is tapped, healed and kept."""
    game, report = _table(
        hands=(("Lightning Bolt",), ()),
        boards=(("Mountain",), ("Drudge Skeletons", "Swamp")),
    )
    skeletons = _on(game, 1, "Drudge Skeletons")
    game.players[0].mana_pool["R"] = 1

    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[skeletons.permanent_id])

    assert result.supported, result.details
    assert _on(game, 1, "Drudge Skeletons") is skeletons
    assert skeletons.tapped and skeletons.damage_marked == 0
    assert _graveyard(game, 1) == []
    assert _on(game, 1, "Swamp").tapped
    assert report.activations_at_instant_speed == Counter({"response": 1})
    assert report.log_lines == [
        "G1 T1 AI-B activate Drudge Skeletons -> queued [in response to Lightning Bolt]"
    ]


def test_an_untapped_pinger_is_used_in_the_opponents_end_step():
    """A Prodigal Sorcerer its controller never tapped in its own turn is
    tapped in the opponent's end step, before it would untap for nothing."""
    game, report = _table(
        boards=((), ("Prodigal Sorcerer",)),
    )
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()

    assert _on(game, 1, "Prodigal Sorcerer").tapped
    assert game.players[0].life == 19
    assert report.activations_at_instant_speed == Counter({"end_step": 1})
    assert report.log_lines == [
        "G1 T1 AI-B activate Prodigal Sorcerer -> queued [in the end step]"
    ]


def test_an_ability_whose_effect_ends_with_the_turn_is_not_activated():
    """The rehearsal is a veto as well as a reason: a Shivan Dragon's
    "+1/+0 until end of turn" in the opponent's end step, and a regeneration
    shield with nothing coming, each change nothing that outlasts the turn —
    the mana stays in the lands and nothing is logged."""
    game, report = _table(
        boards=((), ("Shivan Dragon", "Drudge Skeletons", "Mountain", "Swamp")),
    )
    game._set_phase_and_step("ending", "end")

    game._resolve_priority_window()

    assert not _on(game, 1, "Mountain").tapped
    assert not _on(game, 1, "Swamp").tapped
    assert report.priority_offers >= 1
    assert report.activations_at_instant_speed == Counter()
    assert report.log_lines == []


@pytest.mark.parametrize("where, seat, stack_owner, expected", [
    (("precombat_main", "precombat_main"), 1, 0, "response"),
    (("precombat_main", "precombat_main"), 0, 0, None),
    (("beginning", "upkeep"), 1, None, None),
    (("combat", "declare_attackers"), 1, None, None),
    (("combat", "declare_blockers"), 0, None, "combat"),
    (("combat", "declare_blockers"), 1, None, "combat"),
    (("ending", "end"), 1, None, "end_step"),
    (("ending", "end"), 0, None, None),
])
def test_the_windows_the_simulator_answers(where, seat, stack_owner, expected):
    """Which moments a seat spends a deliberation on: another seat's object
    on the stack, the declare-blockers step with attackers in it (both
    seats), and the opponent's end step. A seat does not answer its own
    object, and every other step is passed."""
    from engine.game_types import StackItem

    game, _report = _table(boards=(("Grizzly Bears",), ()))
    game._set_phase_and_step(*where)
    if where[1] == "declare_blockers":
        game.combat_attackers = {0: 1}
    if stack_owner is not None:
        game.stack.append(StackItem(
            card=CARDS_BY_NAME["Lightning Bolt"], caster_index=stack_owner,
            target_player_index=1, target_permanent_index=None, x_value=None,
        ))

    assert ai_simulator._instant_speed_window(game, seat) == expected


def test_the_report_counts_what_the_windows_offered():
    """The honesty pair beside the casts: offers in the simulator's windows
    and how many of them held an instant the seat could pay for."""
    game, report = _table(
        hands=(("Lightning Bolt",), ("Giant Growth",)),
        boards=(("Mountain",), ("Grizzly Bears",)),
    )
    bears = _on(game, 1, "Grizzly Bears")
    game.players[0].mana_pool["R"] = 1

    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])

    # AI-B was offered the Bolt once and held a Giant Growth with no land.
    assert report.priority_offers == 1
    assert report.priority_offers_weighed == 0
    assert report.casts_in_response == 0
    assert _on(game, 1, "Grizzly Bears") is None
    assert report.refused_instant_casts == Counter()
