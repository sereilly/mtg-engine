"""CR 508.8 — a combat nobody attacked in has no declare blockers step and no
combat damage step.

"If no creatures are declared as attackers or put onto the battlefield
attacking, skip the declare blockers and combat damage steps." (CR 508.8.)

Since kg3 the log said the step was skipped, and the engine entered it all the
same: ``_leave_combat_step`` went from the declare attackers step into the
declare blockers step, wrote "No attackers; declare blockers step skipped", ran
that step's priority window, entered the combat damage step and ran its window
too, and only then reached the end of combat. Two windows a turn the rules do
not have, in every seeded game; a person who flagged declare blockers on the
phase rail was handed priority there on an AI's turn with no attack; and a
spell printed "only before the combat damage step" (Berserk) was castable in
them, where CR 506.8e says such a point that does not exist leaves the spell
castable "only before the declare attackers step ends".

The skip is decided by what was **declared** (or put onto the battlefield
attacking), not by what is attacking when the step ends: a declared attacker
removed from combat does not unmake the declaration, and that combat keeps both
steps (``Game.combat_creatures_attacked``).

And one window beside it, CR 506.8f: "If a spell states that it may be cast
'only during combat after blockers are declared,' but the declare blockers step
is skipped that combat phase …, then the spell may not be cast during that
combat phase" (CR 506.8g: the same for an ability). Chaotic Strike, Aleatory
and Trap Runner read "after blockers are declared" off the step they are in,
and the end of combat step came after a skipped one as well as after a real
one.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, _nosick

SKIPPED = ("declare_blockers", "combat_damage")
LINE = "No attackers; declare blockers and combat damage steps skipped (508.8)"


def _table(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Seat 0 to act, with *mine* and *theirs* (cards) on the battlefield."""
    players = [
        PlayerState(name="P1", hand=list(hands[0])),
        PlayerState(name="P2", hand=list(hands[1])),
    ]
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            _nosick(permanent)
            players[seat].battlefield.append(permanent)
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _entered(game, monkeypatch) -> list[str]:
    """Every combat step this game enters from now on, in order."""
    entered: list[str] = []
    original = Game._set_phase_and_step

    def spy(self, phase, step):
        if self is game and phase == "combat" and (phase, step) != (
            self.current_turn_phase, self.current_step
        ):
            entered.append(step)
        return original(self, phase, step)

    monkeypatch.setattr(Game, "_set_phase_and_step", spy)
    return entered


def _to_declare_attackers(game) -> None:
    for _ in range(3):
        if game.current_step == "declare_attackers":
            return
        game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.log[-4:]


@pytest.mark.cr("508.8", "511.1")
@pytest.mark.parametrize("interactive", [(), (0, 1)], ids=["headless", "interactive"])
def test_declaring_no_attackers_goes_straight_to_end_of_combat(monkeypatch, interactive):
    """Seat 0 could attack with its Bear and declares nobody. Leaving the
    declare attackers step enters the end of combat step, which gives the
    active player priority (CR 511.1); the two steps between are never
    entered and nothing is said about them having completed."""
    bear = _mk_creature_card("My Bear", 2, 2)
    game = _table([bear], [_mk_creature_card("Their Bear", 2, 2)], interactive=interactive)
    entered = _entered(game, monkeypatch)
    _to_declare_attackers(game)
    ok, why = game.declare_attackers(0, [])
    assert ok, why

    game.advance_combat_phase()

    assert game.current_step == "end_of_combat", game.log[-6:]
    assert not set(SKIPPED) & set(entered), entered
    assert game.priority_player_index == 0
    assert LINE in game.log
    assert not any(line.startswith("Declare blockers step complete") for line in game.log)
    assert not any("has no valid blockers" in line for line in game.log)

    game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main", game.log[-4:]
    assert not set(SKIPPED) & set(entered), entered


@pytest.mark.cr("508.8")
def test_a_seat_with_no_legal_attacker_skips_them_too(monkeypatch):
    """No creature to attack with: the engine locks the empty declaration
    itself (`has no valid attackers`), and the same two steps are skipped —
    the declare attackers step itself is not (CR 508.8 skips the two after
    it)."""
    game = _table([], [_mk_creature_card("Their Bear", 2, 2)])
    entered = _entered(game, monkeypatch)

    for _ in range(4):
        if game.current_step == "end_of_combat":
            break
        game.advance_combat_phase()

    assert game.current_step == "end_of_combat", game.log[-6:]
    assert "declare_attackers" in entered
    assert not set(SKIPPED) & set(entered), entered
    assert "P1 has no valid attackers" in game.log
    assert LINE in game.log
    assert "Declare attackers step complete: 0 creature(s) attacking" in game.log


@pytest.mark.cr("508.8", "506.4")
def test_an_attacker_removed_from_combat_does_not_unmake_the_declaration(monkeypatch, set_pool):
    """Seat 0 attacks with a Bear, and the Bear dies to a Lightning Bolt in
    the declare attackers step. A creature *was* declared as an attacker, so
    nothing is skipped: the declare blockers step and the combat damage step
    both happen — with nobody left to block or to deal damage — and each
    gives priority before the end of combat."""
    lea = set_pool("LEA")
    bear = _mk_creature_card("My Bear", 2, 2)
    game = _table(
        [bear], [_mk_creature_card("Their Bear", 2, 2)],
        hands=((), (lea["Lightning Bolt"],)),
    )
    entered = _entered(game, monkeypatch)
    _to_declare_attackers(game)
    ok, why = game.declare_attackers(0, [0])
    assert ok, why

    result = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
    assert result.supported, result.details
    from tests.helpers import resolve_stack

    resolve_stack(game)
    assert not game.combat_attackers, "the Bear left combat as it left the battlefield"

    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.log[-6:]
    for _ in range(4):
        if game.current_step == "end_of_combat":
            break
        game.advance_combat_phase()

    assert game.current_step == "end_of_combat"
    assert entered[-3:] == ["declare_blockers", "combat_damage", "end_of_combat"], entered
    assert LINE not in game.log


@pytest.mark.cr("506.8e", "508.8")
def test_a_point_that_does_not_exist_closes_its_window_with_the_declare_attackers_step(set_pool):
    """Berserk: "Cast this spell only before the combat damage step." With
    nothing attacking there is no combat damage step, and CR 506.8e makes the
    spell castable only before the declare attackers step ends — so the next
    window, the end of combat's, refuses it."""
    pool = set_pool("LEA")
    bear = _mk_creature_card("My Bear", 2, 2)
    game = _table([bear], [], hands=((pool["Berserk"],), ()))
    _to_declare_attackers(game)
    game.declare_attackers(0, [])
    game.advance_combat_phase()
    assert game.current_step == "end_of_combat"

    result = game.cast_from_hand(0, "Berserk", target_player_index=0, target_permanent_index=0)

    assert result.supported is False, result.details
    assert any(card.name == "Berserk" for card in game.players[0].hand)


def _after_blockers_game(set_pool, spell: str, *, attack: bool):
    pool = set_pool("INV") if spell == "Chaotic Strike" else set_pool("MIR")
    bear = _mk_creature_card("My Bear", 2, 2)
    game = _table([bear], [_mk_creature_card("Their Bear", 2, 2)], hands=((pool[spell],), ()))
    _to_declare_attackers(game)
    ok, why = game.declare_attackers(0, [0] if attack else [])
    assert ok, why
    game.advance_combat_phase()
    if attack:
        assert game.current_step == "declare_blockers"
        ok, why = game.declare_blockers(1, {})
        assert ok, why
        game.advance_combat_phase()
        assert game.current_step == "end_of_combat", game.log[-6:]
    assert game.current_step == "end_of_combat", game.log[-6:]
    return game


@pytest.mark.cr("506.8f", "508.8")
@pytest.mark.parametrize("spell", ["Chaotic Strike", "Aleatory"])
def test_after_blockers_is_shut_in_a_combat_whose_declare_blockers_step_was_skipped(set_pool, spell):
    """"Cast this spell only during combat after blockers are declared." —
    refused at the end of a combat nobody attacked in (CR 506.8f), and still
    cast at the end of one where blockers were declared, which is the same
    step reached the other way."""
    skipped = _after_blockers_game(set_pool, spell, attack=False)
    refused = skipped.cast_from_hand(0, spell, target_player_index=0, target_permanent_index=0)
    assert refused.supported is False, refused.details
    assert refused.details == "can only be cast during combat after blockers are declared"
    assert any(card.name == spell for card in skipped.players[0].hand)

    fought = _after_blockers_game(set_pool, spell, attack=True)
    cast = fought.cast_from_hand(0, spell, target_player_index=0, target_permanent_index=0)
    assert cast.supported is True, cast.details
    assert not any(card.name == spell for card in fought.players[0].hand)


@pytest.mark.cr("506.8g", "508.8")
def test_an_after_blockers_ability_is_shut_there_too(set_pool):
    """Trap Runner: "Activate only during combat after blockers are
    declared." The activation restriction is CR 506.8f's for an ability
    (506.8g): shut at the end of a combat whose declare blockers step was
    skipped, open at the end of one that had it."""
    from engine.activation_restrictions import activation_denial

    runner = set_pool("MMQ")["Trap Runner"]
    line = runner.oracle_text.split("(")[0].strip()
    for attack, shut in ((False, True), (True, False)):
        game = _table(
            [_mk_creature_card("My Bear", 2, 2)], [runner],
        )
        _to_declare_attackers(game)
        game.declare_attackers(0, [0] if attack else [])
        game.advance_combat_phase()
        if attack:
            game.declare_blockers(1, {})
            game.advance_combat_phase()
        assert game.current_step == "end_of_combat", game.log[-6:]
        source = next(p for p in game.controlled_by(1) if p.card.name == "Trap Runner")
        denial = activation_denial(game, 1, source, line)
        assert (denial is not None) is shut, (attack, denial)
