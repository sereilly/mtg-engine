"""CR 506.7 — "Cast this spell only [before/after] [a point in combat]".

The twin of ``tests/rules/test_activation_restrictions.py``, and it exists for
the same reason ``engine/cast_restrictions.py`` does: the clause reads the same
on every card that prints it, so it is a table of printed phrases rather than a
branch per card. CR 506.7 names the points a spell may be restricted to —
"attackers are declared", "blockers are declared", "the combat damage step",
"the end of combat step", "the combat phase", "combat" — and the pool prints
five of those wordings across Berserk, Blaze of Glory, Camouflage, False Orders
and Siren's Call.

Checked by *behaviour*, never by reading the table's rows back: an unenforced
timing restriction has no symptom. The spell resolves, the card reports
supported, and the game is simply wrong in its caster's favour.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog
from engine.cast_restrictions import check_cast_timing
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

_CATALOG = {card.name: card for card in load_catalog()}


def _duel() -> tuple[Game, PlayerState, PlayerState]:
    p1 = PlayerState(name="P1", library=[_CATALOG["Grizzly Bears"]])
    p2 = PlayerState(name="P2", library=[_CATALOG["Grizzly Bears"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def _denial(game: Game, seat: int, card_name: str) -> str | None:
    return check_cast_timing(game, seat, _CATALOG[card_name].oracle_text.lower())


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


# ---------------------------------------------------------------------------
# 506.7 — the restriction binds before its point and refuses after it
# ---------------------------------------------------------------------------

@pytest.mark.cr("506.7")
def test_506_7_before_the_combat_damage_step_is_refused_once_that_step_has_passed():
    """Berserk — "only before the combat damage step".

    The point named is a step of the turn, not a place inside combat, so the
    precombat main phase is legal (it is before that step) and the postcombat
    main phase is not.
    """
    game, _p1, _p2 = _duel()
    game.start_turn(0)
    assert _denial(game, 0, "Berserk") is None  # precombat main is still before it

    game.current_turn_phase = "postcombat_main"

    assert _denial(game, 0, "Berserk") == "can only be cast before the combat damage step"


@pytest.mark.cr("506.7")
def test_506_7_before_the_combat_damage_step_is_allowed_during_declare_attackers():
    """The same card in the window the clause opens — declare attackers is
    before the combat damage step, so nothing is denied."""
    game, _p1, _p2 = _duel()
    _to_declare_attackers(game)

    assert _denial(game, 0, "Berserk") is None


@pytest.mark.cr("506.7")
def test_506_7_the_ending_phase_is_also_past_the_combat_damage_step():
    """"Before the combat damage step" is a point the whole turn passes, so
    every phase after it is refused, not merely the postcombat main phase."""
    game, _p1, _p2 = _duel()
    game.start_turn(0)
    game.current_turn_phase = "ending"

    assert _denial(game, 0, "Berserk") == "can only be cast before the combat damage step"


@pytest.mark.cr("506.7")
def test_506_7_only_during_the_declare_blockers_step():
    """False Orders — "only during the declare blockers step". Declare
    attackers is the step before, and is refused."""
    game, _p1, _p2 = _duel()
    _to_declare_attackers(game)

    assert _denial(game, 0, "False Orders") == "can only be cast during the declare blockers step"

    game.advance_combat_phase()  # declare_blockers

    assert _denial(game, 0, "False Orders") is None


@pytest.mark.cr("506.7")
def test_506_7_only_during_combat_before_blockers_are_declared():
    """Blaze of Glory — the window closes once blockers are declared, which is
    a different point from the declare blockers step beginning."""
    game, _p1, _p2 = _duel()
    _to_declare_attackers(game)

    assert _denial(game, 0, "Blaze of Glory") is None

    game.advance_combat_phase()  # declare_blockers
    game.combat_blockers_locked = True

    assert _denial(game, 0, "Blaze of Glory") == (
        "can only be cast during combat before blockers are declared"
    )


@pytest.mark.cr("506.7")
def test_506_7_only_during_your_declare_attackers_step_is_yours_alone():
    """Camouflage — "your declare attackers step". The step is shared, so the
    restriction is about whose turn it is: the non-active player is refused in
    the very same step the active player may cast it in."""
    game, _p1, _p2 = _duel()
    _to_declare_attackers(game)

    assert _denial(game, 0, "Camouflage") is None
    assert _denial(game, 1, "Camouflage") == (
        "can only be cast during your declare attackers step"
    )


@pytest.mark.cr("506.7")
def test_506_7_only_during_an_opponents_turn_before_attackers_are_declared():
    """Siren's Call — the mirror image: legal only for the player whose turn it
    is *not*, and only before attackers are declared."""
    game, _p1, _p2 = _duel()
    game.start_turn(0)

    assert _denial(game, 1, "Siren's Call") is None
    assert _denial(game, 0, "Siren's Call") == (
        "can only be cast during an opponent's turn, before attackers are declared"
    )


@pytest.mark.cr("506.7")
def test_506_7_the_restriction_is_enforced_by_the_cast_path_not_only_reported():
    """The denial is what the caster actually meets.

    The table is only worth having if casting goes through it, so this drives
    the real entry point rather than the predicate: Berserk in the postcombat
    main phase is refused and stays in hand.
    """
    game, p1, _p2 = _duel()
    p1.hand.append(_CATALOG["Berserk"])
    bear = Permanent(card=_CATALOG["Grizzly Bears"])
    _nosick(bear)
    game.players[1].battlefield.append(bear)
    game._sync_control()
    game.start_turn(0)
    game.current_turn_phase = "postcombat_main"

    result = game.cast_from_hand(0, "Berserk", target_player_index=1, target_permanent_index=0)

    assert result.supported is False
    assert any(card.name == "Berserk" for card in p1.hand)


# --- W2G5: the whole of an opponent's turn (CR 102.1) ---


@pytest.mark.cr("601.3a", "102.1")
def test_601_3a_an_opponents_turn_is_the_whole_turn():
    """Delirium — "Cast this spell only during an opponent's turn."

    The window is a *turn* and not a step, which is what separates it from the
    two narrower rows beside it ("…, before attackers are declared" and "…after
    their upkeep step"): those name a point inside the turn as well, and this
    one names none. So the seat is the only test there is — and it is the right
    one in a multiplayer game too, because CR 102.1 gives every seat its own
    turn and "an opponent's turn" is every turn but the caster's.

    Checked by behaviour at both ends. A restriction that is claimed and not
    enforced has no symptom: the spell resolves, the card reports supported, and
    the game is wrong in its caster's favour.
    """
    game, _p1, _p2 = _duel()
    text = "cast this spell only during an opponent's turn."

    game.start_turn(0)
    assert check_cast_timing(game, 0, text) == (
        "can only be cast during an opponent's turn"
    )
    assert check_cast_timing(game, 1, text) is None

    game.start_turn(1)
    assert check_cast_timing(game, 0, text) is None
    assert check_cast_timing(game, 1, text) == (
        "can only be cast during an opponent's turn"
    )


@pytest.mark.cr("601.3a")
def test_601_3a_the_opponents_turn_window_is_not_narrowed_to_a_step():
    """Every step of that turn, not just the one the narrower rows name. Its
    own assertion because the near miss is silent: a window read as one step
    refuses a legal cast, which fails no test and simply makes the card worse
    than printed."""
    game, _p1, _p2 = _duel()
    text = "cast this spell only during an opponent's turn."
    game.start_turn(1)

    for phase in ("beginning", "precombat_main", "combat", "postcombat_main", "ending"):
        game.current_turn_phase = phase
        assert check_cast_timing(game, 0, text) is None, phase
