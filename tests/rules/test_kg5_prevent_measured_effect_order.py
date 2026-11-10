"""CR 616.1e's default for a damage event is **measured**, not stated.

A seat nobody asks — an AI or headless seat, and a person's ``effect_order``
prompt answered by its default — took ``effect_ordering.choose_effect``'s
stated order: the lowest registration order. Veteran Bodyguard's redirect
("As long as this creature is untapped, all damage that would be dealt to you
by unblocked creatures is dealt to this creature instead", order 1) went ahead
of the Circle of Protection: Green its controller had armed against the
attacker (order 500): the Bodyguard took an unblocked Craw Wurm's 6 and died,
where the Circle first prevents all of it and keeps both. Each applicable
effect is now applied first on a scratch copy and what the affected seat
loses compared (``engine/measured_effect_order.py``); a tie — a gain alone
included, since what a shield left unspent is worth is unknowable — keeps the
stated order.

The census is where the default is taken: every ``choose_effect`` call and
every ``apply_in_order`` caller in ``engine/``, each named with what it does
for a seat nobody asks — the damage event measures, every other replacement
kind keeps the stated order (it has no result a copy can apply without its
caller). Validated backwards: on the base (``59f133e6``) the Bodyguard dies on
both boards; the tie board passes on both.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, drive_combat, settle

_ENGINE = Path("engine")

#: Every engine module calling ``choose_effect``, and why.
_CHOOSE_EFFECT_CALLERS = {
    "effect_ordering.py": "the definition and apply_in_order's later rounds "
                          "(the process no longer pure) and its no-default fallback",
    "measured_effect_order.py": "the stated order a tie and an unmeasurable "
                                "table keep",
    "replacements/registry.py": "order_prompt_asker's pick, given no default "
                                "(every replacement kind but damage)",
}
#: Every engine module calling ``apply_in_order``, and the default it passes.
_APPLY_IN_ORDER_CALLERS = {
    "damage_events.py": "measured_damage_default",
    "replacements/registry.py": None,
    "mixins/stack/resolution.py": None,
}


def _callers(pattern: str) -> set[str]:
    return {
        path.relative_to(_ENGINE).as_posix()
        for path in _ENGINE.rglob("*.py")
        if re.search(pattern, path.read_text(encoding="utf-8"))
    }


@pytest.mark.cr("616.1e")
def test_where_a_seat_nobody_asks_takes_the_default_is_known():
    """By the source: the default is taken at these call sites and no others,
    and the damage event's ``apply_in_order`` (and its prompt asker) passes the
    measured default while every other caller keeps the stated one."""
    choosers = _callers(r"\bchoose_effect\(")
    assert len(choosers) >= 3, choosers
    assert choosers == set(_CHOOSE_EFFECT_CALLERS), choosers
    appliers = _callers(r"\bapply_in_order\(") - {"effect_ordering.py"}
    assert appliers == set(_APPLY_IN_ORDER_CALLERS), appliers
    for where, default in _APPLY_IN_ORDER_CALLERS.items():
        text = (_ENGINE / where).read_text(encoding="utf-8")
        assert (f"default={default}" in text) == (default is not None), where


def _table(catalog_by_name, interactive):
    game = Game(players=[
        PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    return game


def _put(game, catalog_by_name, seat, name):
    permanent = Permanent(card=catalog_by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _bodyguard_board(catalog_by_name, interactive):
    """Alice's Craw Wurm attacks Bob unblocked; Bob controls an untapped
    Veteran Bodyguard and has armed Circle of Protection: Green against the
    Wurm."""
    game = _table(catalog_by_name, interactive)
    wurm = _put(game, catalog_by_name, 0, "Craw Wurm")
    guard = _put(game, catalog_by_name, 1, "Veteran Bodyguard")
    _put(game, catalog_by_name, 1, "Circle of Protection: Green")
    declare_attack(game, 0)
    armed = game.activate_permanent_ability(
        1, "Circle of Protection: Green", target_permanent_ids=[wurm.permanent_id],
    )
    assert armed.supported, armed.details
    settle(game)
    return game, guard


@pytest.mark.cr("616.1e", "614.9")
def test_nobody_asked_the_circle_goes_first_and_the_bodyguard_lives(catalog_by_name):
    game, guard = _bodyguard_board(catalog_by_name, set())
    state = random.getstate()
    drive_combat(game, through="combat_damage")
    assert game.is_on_battlefield(guard) and guard.damage_marked == 0, game.log
    assert game.players[1].life == 20, game.log
    assert any("Circle of Protection prevented 6 damage to Bob" in line for line in game.log)
    assert not any("Veteran Bodyguard takes" in line for line in game.log), game.log
    # Measuring consumed none of the game's randomness.
    assert random.getstate() == state


@pytest.mark.cr("616.1e", "614.9")
def test_a_person_s_prompt_defaults_to_the_measured_choice(catalog_by_name):
    """Bob is asked (an interactive seat): both options are offered, and the
    prompt's own default — what a seat that stops answering is given — is
    the Circle. Answered with it, the Bodyguard lives."""
    game, guard = _bodyguard_board(catalog_by_name, {1})
    offered = []

    def answer(game, choice):
        keys = list(choice.data["_keys"])
        offered.append((keys, choice.data["_default_key"]))
        assert game.resolve_pending_choice(
            "effect_order", choice.player_index,
            option_index=keys.index(choice.data["_default_key"]),
        )

    drive_combat(game, through="combat_damage", answers={"effect_order": answer})
    assert offered == [(
        ["_redirect_damage_to_bodyguard", "_circle_of_protection"], "_circle_of_protection",
    )], offered
    assert game.is_on_battlefield(guard) and guard.damage_marked == 0, game.log
    assert game.players[1].life == 20, game.log


@pytest.mark.cr("616.1e")
def test_a_tie_keeps_the_stated_order(catalog_by_name):
    """A Circle of Protection: Red against Bob's Hill Giant and a 5-point pool
    both stop its 3 to Alice whichever goes first: the standings tie, and the
    stated order stands — the Circle (order 500) ahead of the pool (600), so
    the pool is unspent."""
    from engine.shields import add_shield, make_numeric_pool

    game = _table(catalog_by_name, set())
    _put(game, catalog_by_name, 0, "Circle of Protection: Red")
    giant = _put(game, catalog_by_name, 1, "Hill Giant")
    armed = game.activate_permanent_ability(
        0, "Circle of Protection: Red", target_permanent_ids=[giant.permanent_id],
    )
    assert armed.supported, armed.details
    settle(game)
    pool = add_shield(game.players[0], make_numeric_pool(5, "a pool"))
    game._deal_damage_to_player(game.players[0], 3, source=giant, asks=True)
    settle(game)
    assert game.players[0].life == 20, game.log
    assert pool.amount == 5, game.log
