"""No step ends with its stack non-empty or a question owed (CR 500.2, 608.2).

Found in Legions' Phase 5, at a human-vs-AI table: three Essence Sliver
triggers and a Brood Sliver trigger carried into the AI's end step, the human's
own Brood Sliver offer arriving in end of combat, an AI's provoke resolving
after "Declare attackers step complete". Brood Sliver was recorded failing.

The cause was two questions that disagreed. ``_resolve_priority_window``
pauses for **any** seat's prompt at a table with a human at it (CR 608.2: a
resolution that stopped to ask is not finished), and the combat rail asked only
whether an *interactive* seat owed one — while the combat damage step, end of
combat, the main phases, the end step and the upkeep asked nothing at all. So an
AI seat's "you may" paused the window, the step ended around it, and the web
layer answered it a step late. Now every site that leaves a step after draining
its window asks one question (``Game.window_left_unfinished``), holds the step
when it must wait (``Game.held_step``), and resumes at the window once the
answer is in; the web layer answers an AI seat's held question in the same
request (``web/turn_steps._leave_step``).

The censuses drive every shipped card with a trigger of the shape on the web
layer's own stepping, with a spy on ``_on_step_or_phase_end``. Measured on the
tree before the fix (``a501c6c5``): **59 of 298** combat-trigger cards ended a
combat step owing, **37 of 57** end-step-trigger permanents left the end step
with their trigger still on the stack (it resolved in cleanup), and **65 of
422** upkeep/draw-trigger permanents ended the upkeep or draw step with an AI's
question held. All three are zero here.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import stable_sample
from web.game_flow import (
    _advance_ai_turn,
    _advance_phase,
    _ai_step,
    _auto_resolve_ai_pending,
    _run_priority_exchange,
)
from web.session_store import Session
from web.turn_steps import _resume_paused_beginning_phase, _start_next_turn

HUMAN, AI = 0, 1
_LANDS = ("Plains", "Island", "Swamp", "Mountain", "Forest")
_CATALOG = {card.name: card for card in load_catalog()}
_COMBAT_WORDS = ("attack", "block", "combat")
_END_KINDS = ("end_step", "end_step_self")
_BEGINNING_KINDS = ("upkeep_self", "upkeep_each", "draw_step_self", "draw_step_each")


def _triggers(card):
    program = compile_card_oracle(card)
    return program.triggered_abilities if program.supported else ()


def _combat_trigger_cards() -> list[str]:
    return sorted(
        card.name for card in _CATALOG.values()
        if "creature" in card.type_line.lower()
        and any(
            any(word in trig.condition.kind for word in _COMBAT_WORDS)
            or "combat damage" in trig.condition.raw_text
            for trig in _triggers(card)
        )
    )


def _step_trigger_permanents(kinds) -> list[str]:
    return sorted(
        card.name for card in _CATALOG.values()
        if "aura" not in card.type_line.lower()
        and card.primary_type not in ("instant", "sorcery")
        and any(trig.condition.kind in kinds for trig in _triggers(card))
    )


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_CATALOG[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(name: str, asker: int, active: int):
    """A human-vs-AI table: *asker* holds *name*, ten lands and nothing else;
    the other seat a Grizzly Bears and ten lands; *active*'s precombat main
    phase, entered the turn's own way."""
    def library():
        return [_CATALOG[_LANDS[i % 5]] for i in range(12)]

    def lands():
        return [_permanent(_LANDS[i % 5]) for i in range(10)]

    game = Game(players=[
        PlayerState(name="Human", library=library()),
        PlayerState(name="AI", library=library()),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {HUMAN}
    subject = _permanent(name)
    foe = _permanent("Grizzly Bears")
    game.players[asker].battlefield = [subject, *lands()]
    game.players[1 - asker].battlefield = [foe, *lands()]
    session = Session(
        id=f"c1-{name}-{asker}-{active}", mode="human_vs_ai", host_name="Human",
        guest_name="AI", game=game, seat_types={HUMAN: "human", AI: "ai"},
    )
    game._sync_control()
    session.current_turn = active
    game.active_player_index = active
    game.begin_turn_bookkeeping(active)
    game._set_phase_and_step("beginning", "draw")
    game.enter_next_turn_phase("beginning")
    game.start_priority_window(active)
    return session, subject, foe


@pytest.fixture
def step_spy(monkeypatch):
    """Every step of the watched game that ends with its stack non-empty or a
    prompt owed, and every prompt armed in it during combat. Class-level and
    keyed on the one game object, so the AI's rehearsal copies (deep copies,
    which run steps of their own) are neither recorded nor redirected."""
    watched: dict = {"game": None, "ended_owing": [], "asked": []}
    end = Game._on_step_or_phase_end
    arm = Game.arm_pending_choice

    def spy_end(self, phase, step):
        if self is watched["game"]:
            waiting = self.waiting_prompt()
            if self.stack or waiting is not None:
                watched["ended_owing"].append(
                    f"{phase}/{step} ended with stack="
                    f"{[item.card.name for item in self.stack]} owed="
                    f"{(waiting.kind, waiting.player_index) if waiting else None}"
                )
        return end(self, phase, step)

    def spy_arm(self, kind, player_index, **data):
        if self is watched["game"] and self.current_turn_phase == "combat":
            watched["asked"].append((kind, player_index))
        return arm(self, kind, player_index, **data)

    monkeypatch.setattr(Game, "_on_step_or_phase_end", spy_end)
    monkeypatch.setattr(Game, "arm_pending_choice", spy_arm)
    return watched


def _answer_as_the_human(session) -> bool:
    """The human's answer to whatever they owe, through the engine's answer
    funnel (the default response), and the action tail every request runs."""
    game = session.game
    owed = (
        game.trample_assignments_to_ask(HUMAN)
        if game.current_step == "combat_damage" and not game.combat_damage_resolved
        else []
    )
    if owed:
        # A trampler blocked by one creature asks its human assigner (CR
        # 702.19b, kg3/wire), and the web waits for the dialog: its
        # Auto-assign (the engine's own division, lethal to the blocker and
        # the rest past it), then Confirm Damage.
        ok, _ = game.resolve_combat_damage(HUMAN, attacker_damage={
            idx: game._default_attacker_division(idx) for idx in owed
        })
        _auto_resolve_ai_pending(session)
        return ok
    waiting = game.waiting_prompt()
    if waiting is None or waiting.player_index != HUMAN:
        return False
    game.auto_resolve_choice(waiting)
    _auto_resolve_ai_pending(session)
    _resume_paused_beginning_phase(session)
    return True


def _client_step(session) -> None:
    """One request of a client that passes priority and advances, as the
    browser does: the AI's turn through ``ai_step``, the human's through
    ``pass_priority`` over a stack and ``next_phase`` over an empty one."""
    game = session.game
    if session.current_turn == AI:
        if game.priority_player_index == HUMAN:
            _run_priority_exchange(session, HUMAN)
            return
        stepped = session.current_turn
        if _ai_step(session):
            _advance_phase(session)
            if session.current_turn == stepped:
                _advance_ai_turn(session)
        return
    if game.priority_player_index == HUMAN:
        if game.stack:
            _run_priority_exchange(session, HUMAN)
        else:
            _advance_phase(session)
        return
    if game.priority_player_index is None:
        _advance_phase(session)
        return
    _run_priority_exchange(session, game.priority_player_index)


def _declare(session, shape, asker, subject, foe, *, attackers: bool) -> None:
    from engine.ai_combat import declare_ai_blockers

    game = session.game
    active = game.active_player_index
    if attackers:
        attacker = subject if shape.startswith("attack") else foe
        seat = asker if shape.startswith("attack") else 1 - asker
        if game.controls(seat, attacker):
            game.declare_attackers(active, [game.battlefield_index_of(attacker)], 1 - active)
        return
    defender = 1 - active
    blocker = foe if shape == "attack_blocked" else subject if shape == "block" else None
    mapping = {}
    if blocker is not None and game.controls(defender, blocker) and game.combat_attackers:
        mapping = {game.battlefield_index_of(blocker): [next(iter(game.combat_attackers))]}
    ok, _ = game.declare_blockers(defender, mapping)
    if not ok and not declare_ai_blockers(game, defender):
        # A requirement (provoke) or a restriction ("can't be blocked except
        # by two or more") refused the scripted block: the AI chooser's
        # declaration, which honours both, stands in.
        game.declare_blockers(defender, {})


def _fight(session, shape, asker, subject, foe, spy) -> None:
    """Drive *session*'s turn from its precombat main phase to its ending
    phase, declaring as *shape* says; a stall is recorded as owing."""
    game = session.game
    spy["game"] = game
    active = session.current_turn
    declared_attackers = declared_blockers = False
    for _ in range(60):
        if session.current_turn != active or game.is_game_over():
            return
        if game.current_turn_phase == "ending":
            return
        if _answer_as_the_human(session):
            continue
        step = game.current_step
        if step == "declare_attackers" and not game.combat_attackers_locked and not declared_attackers:
            declared_attackers = True
            _declare(session, shape, asker, subject, foe, attackers=True)
            if active == HUMAN:
                continue
        if step == "declare_blockers" and not game.combat_blockers_locked and not declared_blockers:
            declared_blockers = True
            _declare(session, shape, asker, subject, foe, attackers=False)
            continue
        _client_step(session)
    spy["ended_owing"].append(
        f"stalled in {game.current_turn_phase}/{game.current_step}, stack="
        f"{[item.card.name for item in game.stack]}"
    )


_SHAPES = ("attack_unblocked", "attack_blocked", "block")


def test_no_combat_step_ends_owing_for_any_combat_trigger(step_spy):
    """Every combat-triggered creature, as the human's and as the AI's, three
    ways into a fight: no combat step (nor the main phase after it) ends with
    an object on the stack or a question owed, and no fight stalls."""
    names = [name for name in _combat_trigger_cards() if stable_sample(name, 8)]
    owing: list[str] = []
    asked_their_controller: set[tuple[str, int]] = set()
    for name in names:
        for asker in (HUMAN, AI):
            for shape in _SHAPES:
                active = asker if shape.startswith("attack") else 1 - asker
                session, subject, foe = _table(name, asker, active)
                step_spy["ended_owing"] = []
                step_spy["asked"] = []
                _fight(session, shape, asker, subject, foe, step_spy)
                owing.extend(
                    f"{name} ({'human' if asker == HUMAN else 'AI'}, {shape}): {line}"
                    for line in step_spy["ended_owing"]
                )
                if any(seat == asker for _kind, seat in step_spy["asked"]):
                    asked_their_controller.add((name, asker))
    assert not owing, "\n".join(owing)
    # Measured: 298 cards, 125 (card, seat) pairs asking their controller in
    # combat over the whole pool; 34 cards and 12 pairs in the one-in-eight
    # sample.
    assert len(names) >= 25, len(names)
    assert len(asked_their_controller) >= 8, sorted(asked_their_controller)


def _walk_to_next_turn(session, owner: int) -> None:
    game = session.game
    for _ in range(60):
        if session.current_turn != owner or game.is_game_over():
            return
        if _answer_as_the_human(session):
            continue
        _client_step(session)


def test_no_end_step_is_left_with_its_triggers_on_the_stack(step_spy):
    """Every permanent with an end-step trigger, on its controller's turn —
    the human's and the AI's — from the postcombat main phase to the next turn.
    On the AI's turn every one of them used to ride out of the end step and
    resolve in cleanup (``close_end_step`` only cleared the priority window)."""
    names = _step_trigger_permanents(_END_KINDS)
    owing: list[str] = []
    for name in names:
        for asker in (HUMAN, AI):
            session, _subject, _foe = _table(name, asker, asker)
            session.game._set_phase_and_step("postcombat_main", "postcombat_main")
            session.game.start_priority_window(asker)
            step_spy["game"] = session.game
            step_spy["ended_owing"] = []
            _walk_to_next_turn(session, asker)
            owing.extend(f"{name} (seat {asker}): {line}" for line in step_spy["ended_owing"])
    assert not owing, "\n".join(owing)
    # Measured: 57 permanents.
    assert len(names) >= 50, len(names)


def test_no_upkeep_or_draw_step_ends_with_an_ai_question_held(step_spy):
    """Every permanent with an upkeep or draw-step trigger, the AI's turn begun
    by the web layer at a table with a human. The web layer drained the held
    trigger before the next step, but the step had already ended around it —
    its mana pools emptied (CR 500.5) with the trigger still resolving."""
    names = [
        name for name in _step_trigger_permanents(_BEGINNING_KINDS)
        if stable_sample(name, 2)
    ]
    owing: list[str] = []
    for name in names:
        session, _subject, _foe = _table(name, AI, HUMAN)
        game = session.game
        game._set_phase_and_step("ending", "cleanup")
        step_spy["game"] = game
        step_spy["ended_owing"] = []
        _start_next_turn(session)
        for _ in range(40):
            if game.current_turn_phase != "beginning" or session.current_turn != AI:
                break
            if _answer_as_the_human(session):
                # "Any player may sacrifice two lands" (Worms of the Earth)
                # asks the human in the AI's upkeep.
                continue
            if game.priority_player_index == HUMAN:
                _run_priority_exchange(session, HUMAN)
            else:
                _advance_phase(session)
        owing.extend(f"{name}: {line}" for line in step_spy["ended_owing"])
        assert game.is_game_over() or game.current_turn_phase == "precombat_main", (
            name, game.current_step,
        )
    assert not owing, "\n".join(owing)
    # Measured: 422 permanents over the whole pool, 65 of them red before.
    assert len(names) >= 150, len(names)


# -- Brood Sliver and provoke, the cards Phase 5 watched -----------------------


def _slivers_attack(seat: int):
    """*seat*'s Brood, Plated and Blade Slivers, the other seat with no
    creature to block them, *seat*'s precombat main phase."""
    session, _brood, _bears = _table("Brood Sliver", seat, seat)
    game = session.game
    other = 1 - seat
    game.players[other].battlefield = [
        perm for perm in game.players[other].battlefield if not perm.is_creature
    ]
    for name in ("Plated Sliver", "Blade Sliver"):
        game.players[seat].battlefield.append(_permanent(name))
    game._sync_control()
    return session


def _attack_with_everything(session) -> None:
    game = session.game
    seat = game.active_player_index
    game.declare_attackers(
        seat,
        [game.battlefield_index_of(perm) for perm in game.controlled_by(seat) if perm.is_creature],
        1 - seat,
    )


def _sliver_tokens(game, seat: int) -> int:
    return sum(1 for perm in game.controlled_by(seat) if perm.card.name.startswith("Sliver"))


def _watch_step_end(monkeypatch, game, phase: str, step: str, read) -> list:
    """What *read* says of *game* each time its *phase*/*step* ends."""
    seen: list = []
    end = Game._on_step_or_phase_end

    def spy(self, ending_phase, ending_step):
        if self is game and (ending_phase, ending_step) == (phase, step):
            seen.append(read(self))
        return end(self, ending_phase, ending_step)

    monkeypatch.setattr(Game, "_on_step_or_phase_end", spy)
    return seen


def test_the_ais_brood_sliver_makes_every_token_in_the_damage_step(step_spy, monkeypatch):
    """The AI's three Slivers hit the human: three "its controller may create a
    1/1 Sliver token" triggers, each the AI's question. All three resolve in
    the combat damage step — the reproduction left two on the stack into the
    postcombat main phase, and Phase 5 watched them reach the AI's end step."""
    session = _slivers_attack(AI)
    game = session.game
    step_spy["game"] = game
    at_damage_end = _watch_step_end(
        monkeypatch, game, "combat", "combat_damage",
        lambda g: (_sliver_tokens(g, AI), len(g.stack)),
    )
    for _ in range(30):
        if game.current_turn_phase != "precombat_main" and game.current_turn_phase != "combat":
            break
        if game.current_step == "declare_attackers" and not game.combat_attackers_locked:
            _attack_with_everything(session)
        elif game.current_step == "declare_blockers" and not game.combat_blockers_locked:
            game.declare_blockers(HUMAN, {})
        _client_step(session)
    assert at_damage_end == [(3, 0)], game.log[-20:]
    assert not step_spy["ended_owing"], step_spy["ended_owing"]


def test_the_humans_brood_sliver_offer_is_made_in_the_damage_step(step_spy):
    """The human's Slivers hit the AI. The first offer holds the combat damage
    step — it used to arrive in end of combat — and once each offer is
    answered and priority passed, the step ends with three tokens and nothing
    on the stack."""
    session = _slivers_attack(HUMAN)
    game = session.game
    step_spy["game"] = game
    offers_seen_in: set[str] = set()
    for _ in range(40):
        if game.current_turn_phase in ("postcombat_main", "ending"):
            break
        waiting = game.waiting_prompt()
        if waiting is not None and waiting.player_index == HUMAN:
            offers_seen_in.add(game.current_step)
            assert game.step_held_open() or game.stack
            _answer_as_the_human(session)
            continue
        if game.current_step == "declare_attackers" and not game.combat_attackers_locked:
            _attack_with_everything(session)
            continue
        _client_step(session)
    assert offers_seen_in == {"combat_damage"}, offers_seen_in
    assert _sliver_tokens(game, HUMAN) == 3, game.log[-20:]
    assert game.current_turn_phase == "postcombat_main"
    assert not step_spy["ended_owing"], step_spy["ended_owing"]


def test_the_ais_provoke_resolves_in_the_declare_attackers_step(step_spy, monkeypatch):
    """Brontotherium's provoke, the AI's "you may", names the human's Goblin
    Grappler. It resolves before the declare attackers step ends — Phase 5
    watched it resolve after the step's "complete" line — and the step's line
    is written once, though its leaving stopped at the window and resumed."""
    from engine.combat_permissions import MUST_BLOCK_ATTACKERS_THIS_COMBAT

    session, _brontotherium, grappler = _table("Brontotherium", AI, AI)
    game = session.game
    step_spy["game"] = game
    at_attack_end = _watch_step_end(
        monkeypatch, game, "combat", "declare_attackers",
        lambda g: (bool(grappler.metadata.get(MUST_BLOCK_ATTACKERS_THIS_COMBAT)), len(g.stack)),
    )
    for _ in range(10):
        if game.current_step == "declare_blockers":
            break
        _client_step(session)
    assert game.current_step == "declare_blockers", game.log[-12:]
    assert at_attack_end == [(True, 0)], game.log[-12:]
    assert sum("Declare attackers step complete" in line for line in game.log) == 1
    assert not step_spy["ended_owing"], step_spy["ended_owing"]


def test_a_table_with_no_human_drains_as_it_always_did():
    """No interactive seat: the window resolves straight through and queues
    the AI's question for the caller, as every headless test and seeded game
    expects — nothing is held."""
    session = _slivers_attack(AI)
    game = session.game
    game.interactive_seats = set()
    game._close_current_priority_step()
    game.enter_next_turn_phase("precombat_main")
    game.advance_combat_phase()
    _attack_with_everything(session)
    game.advance_combat_phase()
    game.declare_blockers(HUMAN, {})
    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"
    assert game.held_step is None and not game.stack
    assert len(game.pending_choices_of("optional_pay")) == 3
