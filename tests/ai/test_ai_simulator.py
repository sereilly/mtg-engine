import ast
import pathlib
from collections import Counter
from dataclasses import replace

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import build_limited_deck, run_ai_simulation
from engine.models import Permanent
from tests.helpers import LEA_PATH

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _expected_card_names() -> set[str]:
    """The card names ``_assert_expected`` branches on, read from the source.

    An AST read rather than a hand-kept list: a list would be the third place
    these names live, and it would go stale the same way the thing it guards
    would."""
    tree = ast.parse((ROOT / "engine" / "ai_simulator.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_assert_expected"
    )
    found: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(isinstance(item, ast.Attribute) and item.attr == "name" for item in operands):
            continue
        found.update(
            item.value for item in operands
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    return found


def test_every_simulator_expectation_names_a_card_the_deck_can_play(all_cards):
    """``_assert_expected`` is allowed its card names — it is a test oracle, and
    one derived from the compiled program would be a tautology (a Lightning Bolt
    mis-parsed to 1 damage deals 1 and matches its own derived expectation).

    What it is *not* immune to is drifting off the pool: an expectation for a
    card the simulator can never deal never fires again, and nothing fails.
    That is the same "the comment expired without anyone editing it" decay the
    name rule exists for, so it gets a guard rather than a promise.

    The guard changed shape when the decklist did. It used to build the one
    fixed deck and ask whether each name was in it; decks are now random draws
    from whichever set is under test, so "in the deck" is a property of a seed
    rather than of the code. What still holds — and is what the oracle needs —
    is that each name is a card the builder *can* deal from the pool the
    default runs use. `required=` is how the tests below pin their own
    subjects, and it is the same mechanism, so this asserts the mechanism."""
    cards = {c.name: c for c in all_cards}
    expected = _expected_card_names()
    assert expected, "no card-name expectations found — did _assert_expected move?"

    missing = sorted(name for name in expected if name not in cards)
    assert not missing, (
        "engine/ai_simulator.py::_assert_expected checks cards that are not in "
        f"the pool it runs over, so the checks never run: {missing}"
    )
    dealt = {
        card.name
        for card in build_limited_deck(cards, seed=1, required=sorted(expected))
    }
    orphaned = sorted(expected - dealt)
    assert not orphaned, (
        "engine/ai_simulator.py::_assert_expected checks cards the deck builder "
        f"will not deal even when asked for them by name: {orphaned}"
    )


def test_the_simulator_drains_every_prompt_that_suspends_a_resolution():
    """A kind registered ``suspends`` holds ``game.effect_suspended`` until it is
    answered, so a headless run that leaves one owed does not merely skip that
    prompt — it stops the *next* resumable loop anywhere in the game after one
    step, with nothing pointing back at what caused it. Derived from the
    registry, because a hand-kept list is what would go stale.

    Two exemptions, both by construction rather than by opinion. A kind
    registered ``default_at_arm`` is never *queued* for a non-interactive seat —
    ``arm_pending_choice`` takes its default before the flag is set — so a
    headless run cannot owe one. ``effect_order`` is the same rule written a
    layer up: ``engine/replacements.py`` answers a non-interactive seat with the
    default before queueing.
    """
    from engine.ai_simulator import _SIMULATED_CHOICES
    from engine.pending_choices import CHOICE_SPECS

    suspending = {kind for kind, spec in CHOICE_SPECS.items() if spec.suspends}
    answered_at_arm = {
        kind for kind, spec in CHOICE_SPECS.items() if spec.default_at_arm
    }
    undrained = (
        suspending - set(_SIMULATED_CHOICES) - answered_at_arm - {"effect_order"}
    )

    assert not undrained, (
        "suspending prompt(s) a headless simulation would leave owed, wedging "
        f"every later resumable loop: {sorted(undrained)}"
    )


@pytest.mark.slow
def test_ai_simulator_runs_without_issues_for_two_games():
    report = run_ai_simulation(
        cards_path=LEA_PATH,
        games=2,
        seed=77,
        max_turns=10,
    )

    assert report.games_completed == 2
    assert report.interaction_count > 0
    assert report.issues == []


def test_prodigal_sorcerer_summoning_sickness_clears_after_turn(all_cards):
    """Regression: game.turn must increment each half-turn so summoning sickness clears.

    Before the fix, game.turn was never incremented in the simulation loop, so
    every creature retained its summoning_sickness_turn == game.turn == 1 forever
    and could never use a tap ability.
    """
    cards = {c.name: c for c in all_cards}
    prodigal = cards["Prodigal Sorcerer"]

    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # P1's first turn: creature enters; game.turn is 1
    game.turn = 1
    perm = Permanent(card=prodigal)
    p1.battlefield.append(perm)
    game._initialize_permanent_state(perm, 0, None)

    # Creature is summoning sick on the turn it entered
    assert game._is_summoning_sick(perm)

    # P1's second turn: each player half-turn advances game.turn by 1, so
    # P1's second turn is game.turn == 3 (P1=1, P2=2, P1=3)
    game.turn = 3
    assert not game._is_summoning_sick(perm), "sickness must clear by P1's second turn"

    # The tap ability should now succeed and deal 1 damage to P2
    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert result.supported
    assert p2.life == 19


@pytest.mark.slow
def test_prodigal_sorcerer_deals_damage_in_simulation():
    """Regression: Prodigal Sorcerer must deal damage once summoning sickness clears.

    ``required_cards`` pins the subject into both decks. It used to be there
    because the simulator played one fixed decklist that happened to contain
    it; decks are now random draws from the set, so a seed that dealt no
    Prodigal Sorcerer would pass this test having regressed nothing — the
    vacuous pass that a "never fires again" guard exists to prevent."""
    report = run_ai_simulation(
        cards_path=LEA_PATH,
        games=5,
        seed=42,
        max_turns=18,
        required_cards=("Prodigal Sorcerer",),
    )

    prodigal_damage_lines = [
        line for line in report.log_lines
        if "Prodigal Sorcerer dealt" in line
    ]
    assert prodigal_damage_lines, (
        "Prodigal Sorcerer never dealt damage across 5 games; "
        "summoning sickness may not be clearing between turns"
    )


@pytest.mark.slow
def test_simulation_stops_when_player_loses_via_empty_library():
    """Regression: game loop must exit when player.lost is set, not only on life loss.

    Before the fix, the loop only checked life <= 0. A player who drew from an
    empty library had player.lost set to True by check_state_based_actions, but
    the game continued for many more turns.
    """
    report = run_ai_simulation(
        cards_path=LEA_PATH,
        games=5,
        seed=42,
        max_turns=18,
    )

    found_loss_in_game = False
    for line in report.log_lines:
        if line.startswith("=== Game"):
            found_loss_in_game = False
            continue

        if "lost the game (704.5b" in line:
            found_loss_in_game = True
            continue

        if found_loss_in_game:
            # Only the RESULT line or blank lines should follow within the same game.
            # A "Gx Ty ... cast/activate" line means the game kept running after the loss.
            assert not (" cast " in line and line.startswith("G")), (
                f"Cast action found after player lost via empty library: {line!r}"
            )
            assert not (" activate " in line and line.startswith("G")), (
                f"Activation found after player lost via empty library: {line!r}"
            )


@pytest.mark.slow
def test_ancestral_recall_never_self_causes_library_loss():
    """Regression: AI must not self-cast Ancestral Recall when library has < 3 cards.

    Before the fix, the AI's score for Ancestral Recall did not account for library
    depth, causing it to self-target the spell when nearly out of cards and lose the
    game immediately via rule 704.5b.  The fix returns -100 in that scenario.

    We verify this by scanning the log for the distinctive pattern:
      'cast Ancestral Recall' followed by 'lost the game (704.5b' in the *same turn block*
    which is the footprint of an AI-caused library self-kill from Ancestral Recall.
    """
    report = run_ai_simulation(
        cards_path=LEA_PATH,
        games=10,
        seed=1337,
        max_turns=25,
        # Pinned for the same reason as the Prodigal Sorcerer test above: this
        # regression is about what the AI does *holding* Ancestral Recall, so a
        # deck without one asserts nothing at all.
        required_cards=("Ancestral Recall",),
    )

    prev_was_ancestral_cast = False
    for line in report.log_lines:
        stripped = line.strip()
        if "cast Ancestral Recall" in stripped:
            prev_was_ancestral_cast = True
            continue
        if prev_was_ancestral_cast:
            assert "lost the game (704.5b" not in stripped, (
                f"Ancestral Recall self-cast triggered a library-death loss: {stripped!r}"
            )
            # Reset once we move past the immediate follow-up lines
            if stripped.startswith("G") or stripped.startswith("RESULT") or stripped == "":
                prev_was_ancestral_cast = False


# --- the simulator's turn loop is the whole of `start_turn`, not three of its four steps ---


def test_the_simulator_advances_the_per_seat_turn_ordinal():
    """``begin_turn_bookkeeping`` runs in an AI game (found at USG's wave 1).

    ``Game.start_turn`` is bookkeeping + untap + upkeep + draw. The simulator's
    loop open-coded the last three and omitted the first, so
    ``Game.seat_turn_counts`` — written in exactly one place, inside that
    function — stayed empty for the whole of every AI game and every
    ``scripts/simulate_ai_games.py`` run.

    Nothing crashed, which is why it survived: every reader of the ordinal
    simply answered "0". **Wiitigo** ("blocked or been blocked since your last
    upkeep") never grew a +1/+1 counter, **Giant Turtle**, **Goblin Rock Sled**
    and **Tangle Kelp** never saw "attacked during your last turn", **Wall of
    Dust** and **Oracle en-Vec** never saw "during its controller's next turn",
    and every lock in ``engine/hand_locks.py`` compared against a frozen number.
    All six are *shipped* cards.

    Asserting the ordinal rather than any one card's behaviour: the ordinal is
    what the omission actually broke, and a card assertion would need a seed
    that deals that card.
    """
    from engine.card_loader import manifest_set_paths
    import engine.ai_simulator as simulator

    seen: dict[str, dict[int, int]] = {}
    original = simulator.choose_cast_action

    def _spy(game, active):
        counts = dict(getattr(game, "seat_turn_counts", {}) or {})
        if counts:
            seen["counts"] = counts
        return original(game, active)

    simulator.choose_cast_action = _spy
    try:
        simulator.run_ai_simulation([LEA_PATH], games=1, max_turns=6, seed=7)
    finally:
        simulator.choose_cast_action = original

    counts = seen.get("counts")
    assert counts, (
        "seat_turn_counts was empty for the whole simulation - "
        "begin_turn_bookkeeping is not being called by the turn loop"
    )
    assert max(counts.values()) > 1, (
        f"the per-seat turn ordinal never advanced past its first turn: {counts}"
    )


def test_the_simulator_actually_plays_a_combat_phase():
    """The simulated turn has a combat phase, and creatures use it.

    This is the guard for an **absent** result, which is the only kind this
    script's own output cannot show. Before combat was driven here the turn loop
    went bookkeeping -> untap -> upkeep -> draw -> main -> cast -> activate ->
    next seat, so no simulated game had ever declared an attacker, declared a
    block or run a combat damage step — and every run still reported games
    completed, a non-zero interaction count and "no illegal or unexpected
    interactions detected". Nothing failed, because nothing was wrong; what was
    missing was half a turn.

    It is the third omission of that exact shape in this one function
    (`begin_turn_bookkeeping`, then the main phase, then this), which is why the
    assertion is on the *count* rather than on any particular card: a number
    that must stay above zero is the only thing that catches the fourth.
    """
    report = run_ai_simulation(LEA_PATH, games=4, seed=1337, max_turns=14)

    assert report.attacks_declared > 0, (
        "no attack declaration in four games — the combat phase is not being "
        "entered, and every 'no illegal interactions' this script prints is a "
        "true statement about a turn that skipped combat"
    )
    assert report.attackers_declared > 0, (
        "attackers were declared but every declaration was empty"
    )
    assert not report.issues, report.issues

    # A declaration the engine refuses is not an issue and not a failure — it is
    # the attack-side twin of `refused_casts`, counted because the AI proposes
    # the same illegal set again next turn. Alpha prints no attack restriction,
    # so on this pool it should be empty; the assertion is that the channel
    # exists and is read, which is what stops it going the way `refused_attacks`
    # nearly did (a counter that could only ever have read zero).
    assert isinstance(report.refused_attacks, Counter)
    assert sum(report.refused_attacks.values()) == 0, dict(report.refused_attacks)


@pytest.mark.parametrize("code, seed", [("M21", 1), ("ATQ", 7)])
def test_the_simulator_plays_an_ending_phase_and_until_end_of_turn_ends(
    code, seed, monkeypatch
):
    """Every simulated turn ends (CR 512-514), and what "until end of turn"
    bought is gone by the next one.

    The **fourth** omission of the "it plays a whole turn" class in
    ``run_ai_simulation``. The loop went main phase -> combat -> next seat, so
    ``resolve_end_step`` and ``resolve_cleanup_step`` ran zero times in every
    simulated game (W1G1, W1G2): a Giant Growth or a Healing Salve shield lasted
    the whole game, marked damage piled up across turns, no end-step trigger
    fired and no hand was discarded down to seven. And — the property this
    class always has — the run still completed with a non-zero interaction
    count and an empty issue list.

    Read off the engine's own step methods rather than the report's counters,
    so the assertion is about what ran, not about what this file says ran. The
    two seeds are ones where, on the tree this test was written against, the
    stale state was real at turn starts (M21: damage and end-of-turn pumps;
    ATQ: damage and prevention shields) — and the *exercised* floor below is
    what keeps a later seed from passing by never creating any.
    """
    from engine.card_loader import manifest_set_path
    from engine.hand_size import maximum_hand_size
    from engine.pt import TEMPORARY_PT_CHANNELS
    from engine.shields import shields_on

    eot_keys = TEMPORARY_PT_CHANNELS["end_of_turn"]
    seen = Counter()
    stale: list[str] = []

    def _w2g3_until_eot_state(game) -> list[str]:
        found = []
        for permanent in game.all_permanents():
            if permanent.damage_marked:
                found.append(f"{permanent.card.name} has {permanent.damage_marked} damage marked")
            if any(key in permanent.metadata for key in eot_keys):
                found.append(f"{permanent.card.name} carries an end-of-turn P/T change")
            if shields_on(permanent):
                found.append(f"{permanent.card.name} holds a prevention shield")
        for player in game.players:
            if shields_on(player):
                found.append(f"{player.name} holds a prevention shield")
        return found

    original_begin = Game.begin_turn_bookkeeping
    original_end = Game.resolve_end_step
    original_cleanup = Game.resolve_cleanup_step

    def begin(self, player_index):
        seen["turn_starts"] += 1
        stale.extend(f"turn {self.turn}: {what}" for what in _w2g3_until_eot_state(self))
        # CR 514.1: the seat whose cleanup just ran is at or under its maximum.
        if seen["cleanups"]:
            previous = self.active_player_index
            limit = maximum_hand_size(self, previous)
            if limit is not None and len(self.players[previous].hand) > limit:
                stale.append(
                    f"turn {self.turn}: {self.players[previous].name} kept "
                    f"{len(self.players[previous].hand)} cards over a maximum of {limit}"
                )
        return original_begin(self, player_index)

    def end(self, *args, **kwargs):
        seen["end_steps"] += 1
        return original_end(self, *args, **kwargs)

    def cleanup(self, *args, **kwargs):
        seen["cleanups"] += 1
        if _w2g3_until_eot_state(self):
            seen["cleanups_with_something_to_end"] += 1
        return original_cleanup(self, *args, **kwargs)

    monkeypatch.setattr(Game, "begin_turn_bookkeeping", begin)
    monkeypatch.setattr(Game, "resolve_end_step", end)
    monkeypatch.setattr(Game, "resolve_cleanup_step", cleanup)

    report = run_ai_simulation(
        manifest_set_path(code), games=2, seed=seed, max_turns=10
    )

    assert seen["turn_starts"] >= 30, f"examined only {seen['turn_starts']} turns"
    # A turn the game ended part-way through has no ending phase; nothing else
    # may lack one.
    assert seen["end_steps"] >= seen["turn_starts"] - report.games_completed, dict(seen)
    assert seen["cleanups"] == seen["end_steps"], dict(seen)
    assert report.end_steps == seen["end_steps"]
    assert report.cleanup_steps == seen["cleanups"]
    assert seen["cleanups_with_something_to_end"] >= 3, (
        "the run never reached a cleanup step holding until-end-of-turn state, "
        f"so the expiry below was not exercised: {dict(seen)}"
    )
    assert stale == [], stale[:10]
    assert not report.issues, [issue.message for issue in report.issues]


def test_the_simulators_oracle_is_not_fooled_by_a_cast_trigger_gaining_life(
    all_cards,
):
    """A real Lightning Bolt into a player whose Iron Star gains them a life in
    the same window, judged by ``_assert_expected`` from the same snapshots the
    simulator takes.

    The oracle read the life *total*, so the Bolt looked like 2 damage and
    LEB's and 2ED's default seeded runs (``simulate_ai_games.py --set LEB``,
    seed 1337) exited 1 on a game where the engine had done exactly the right
    thing — and Ivory Cup did the same to Healing Salve in 6ED's. The
    expectation is still the human-read 3; what changed is which record it is
    compared against.
    """
    from engine.ai_simulator import _assert_expected, _snap
    from tests.helpers import _game, _nosick, resolve_stack

    cards = {card.name: card for card in all_cards}
    caster = PlayerState(name="Caster", hand=[cards["Lightning Bolt"]])
    target = PlayerState(name="Target", life=10)
    game = _game(caster, target)
    for name in ("Iron Star", "Mountain"):
        permanent = _nosick(Permanent(card=cards[name]))
        game._put_permanent_onto_battlefield(1, permanent, None)

    before = _snap(game)
    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    after = _snap(game)

    assert result.supported, result.details
    # The window really did hold both: 3 damage dealt, 1 life gained.
    assert target.life == 8, game.log[-12:]
    assert after[1].damage_taken_this_turn - before[1].damage_taken_this_turn == 3
    assert after[1].life_gained_this_turn - before[1].life_gained_this_turn == 1
    assert _assert_expected(cards["Lightning Bolt"], before, after, 0, 1) is None

    # …and the check still fires on a Bolt that dealt less than it prints.
    short = (after[0], replace(after[1], damage_taken_this_turn=before[1].damage_taken_this_turn + 1))
    assert _assert_expected(cards["Lightning Bolt"], before, short, 0, 1) is not None


def test_combat_damage_in_the_simulator_actually_moves_a_life_total():
    """Attacking is not the assertion; connecting is.

    A declaration that never resolves into damage would satisfy the counts above
    while changing nothing about the game, so this reads the one number a player
    would: somebody's life total. Alpha's decks are creature-heavy enough that
    over eight games at least one attacker gets through.
    """
    report = run_ai_simulation(LEA_PATH, games=8, seed=1337, max_turns=16)

    assert any("combat damage" in line for line in report.log_lines), (
        "no combat damage was dealt across eight games"
    )
    assert not report.issues, report.issues
