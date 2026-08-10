"""Loops that survive a step stopping to ask a question — the rules half.

CR 616.1e's choice interrupts a damage event part-way, and answering re-runs it.
An event is usually one step of something larger: a divided Fireball's targets,
a spell's remaining resolution. What these pin is that the rest of that larger
thing still happens, and happens in the right order.

The loop bookkeeping underneath is tests/engine/test_resumption.py.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from engine import Game, PlayerState
from tests.helpers import CARDS_BY_NAME


def _shielded_player(life: int = 20):
    """A seat holding two shields that both apply to one red damage event — a
    Circle of Protection and a prevention pool, which is the CR 616.1e
    contention this pool reaches most easily."""
    player = PlayerState(name="P1", life=life)
    player.color_prevention_shields = ["R"]
    player.damage_prevention_pool = 5
    return player


# ---------------------------------------------------------------------------
# End to end: a spell whose damage stops to ask
# ---------------------------------------------------------------------------

@pytest.mark.cr("616.1e", "608.2m")
def test_616_1e_a_spell_whose_damage_asks_finishes_when_answered():
    """A red damage spell into a player holding two applicable shields. The
    event stops, and because it stops *before* applying anything the rest of the
    resolution has to stop with it — including CR 608.2m's "put the card into
    its owner's graveyard", which would otherwise bin a spell whose damage had
    not happened."""
    bolt = replace(CARDS_BY_NAME["Lightning Bolt"], colors=("R",))
    caster = PlayerState(name="P0", hand=[bolt])
    victim = _shielded_player()
    game = Game(players=[caster, victim])
    game.interactive_seats = {1}

    game.cast_from_hand(0, bolt.name, target_player_index=1)

    assert game.pending_choices_of("effect_order", 1), "the affected player was asked"
    assert victim.damage_prevention_pool == 5 and victim.color_prevention_shields == ["R"], (
        "nothing was spent while the question was open"
    )
    assert bolt not in caster.graveyard, "the spell is still resolving (CR 608.2m)"

    pool = game.pending_choices_of("effect_order", 1)[0].data["_keys"].index("_prevention_pool")
    game.resolve_pending_choice("effect_order", 1, option_index=pool)

    assert victim.damage_prevention_pool == 2, "the chosen shield absorbed the 3"
    assert victim.color_prevention_shields == ["R"], "the Circle was not spent"
    assert victim.life == 20
    assert bolt in caster.graveyard, "and the resolution finished"
    assert game.resume_stack == [] and not game.effect_suspended


@pytest.mark.cr("616.1e")
def test_616_1e_a_divided_spell_resumes_the_targets_behind_the_one_that_asked():
    """The case the loop machinery exists for. Fireball divided over two
    players: the first stops to ask, and the second must still be dealt to when
    the answer arrives rather than being dropped."""
    fireball = replace(CARDS_BY_NAME["Fireball"], colors=("R",))
    caster = PlayerState(name="P0", hand=[fireball])
    victim = _shielded_player()
    third = PlayerState(name="P2", life=20)
    game = Game(players=[caster, victim, third])
    game.interactive_seats = {1}

    game.cast_from_hand(
        0, fireball.name, target_player_index=1, x_value=6,
        divided_targets=[(1, None), (2, None)],
    )

    assert game.pending_choices_of("effect_order", 1), "the shielded seat was asked"
    assert third.life == 20, "the other target has not been dealt to yet"

    keys = game.pending_choices_of("effect_order", 1)[0].data["_keys"]
    game.resolve_pending_choice(
        "effect_order", 1, option_index=keys.index("_prevention_pool")
    )

    assert victim.damage_prevention_pool == 2, "3 of the pool absorbed the shielded seat's share"
    assert third.life == 17, "the target behind the question was not lost"
    assert game.resume_stack == [] and not game.effect_suspended
