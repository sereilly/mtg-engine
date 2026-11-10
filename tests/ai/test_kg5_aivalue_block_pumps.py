"""The fight forecast reads what a block's own triggers do to the two
creatures before damage (``ai_compelled_blocks.block_pair_pumps``).

Flanking — "Whenever this creature becomes blocked by a creature without
flanking, the blocking creature gets -1/-1 until end of turn" (CR 702.25a) —
and Pygmy Troll's "+1/+1 when it becomes blocked by a creature" change who
dies, and ``fight_outcome`` read the printed P/T: a 2/2 blocking a flanking
2/2 "traded" where it died alone. Found by kg5's regeneration census, whose
two disagreeing rows were Cadaverous Knight and Pygmy Troll.

The census fights every shipped creature with such a trigger, as the
attacker, against vanilla blockers of five sizes, and holds the forecast to
the engine's combat.
"""

from __future__ import annotations

from functools import lru_cache

from engine import faces
from engine.ai_compelled_blocks import _BLOCKED_PUMP_CONDITIONS, _plain_steps, fight_outcome
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_creature_card, _nosick, drive_combat, stock_libraries

SIZES = ((1, 1), (2, 2), (3, 3), (2, 1), (1, 3))


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _pumped_when_blocked() -> list:
    found = []
    cards = sorted(_catalog().values(), key=lambda card: card.name)
    for unit in faces.compilation_units(cards):
        if "Creature" not in (unit.type_line or ""):
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if any(
            trigger.condition.kind in _BLOCKED_PUMP_CONDITIONS
            and any(step.kind in ("pump_self", "pump_block_pair") for step in _plain_steps(trigger.instruction))
            for trigger in program.triggered_abilities
        ):
            found.append(unit)
    return found


def _fought(attacker_card, blocker_card):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    stock_libraries(game)
    placed = []
    for seat, card in ((0, attacker_card), (1, blocker_card)):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, permanent, None)
        _nosick(permanent)
        placed.append(permanent)
    game.check_state_based_actions()
    attacker, blocker = placed
    if not game.can_attack(attacker, 1) or not game._can_block_attacker(blocker, attacker):
        return None
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(0, [game.battlefield_index_of(attacker)], defending_player_index=1)
    if not ok:
        return None
    game.advance_combat_phase()
    if game.current_step != "declare_blockers" or not (
        game.is_on_battlefield(blocker) and game.is_on_battlefield(attacker)
    ):
        return None
    # Asked where the defender asks it: the attack declared and its own
    # triggers resolved (Telim'Tor's +1/+1), the blocks still to come.
    forecast = fight_outcome(game, attacker, blocker)
    ok, _why = game.declare_blockers(
        1, {game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)},
    )
    if not ok:
        return None
    drive_combat(game)
    return forecast, (not game.is_on_battlefield(blocker), not game.is_on_battlefield(attacker))


def test_every_creature_pumped_by_its_own_block_is_forecast_as_the_engine_fights():
    """Every shipped creature with a "becomes blocked" P/T trigger, against
    vanilla blockers of five sizes: the forecast is the engine's combat.
    Validated backwards: on the tree before ``block_pair_pumps`` every
    flanker disagreed against the 2/2 (Cadaverous Knight, Pygmy Troll among
    them)."""
    attackers = _pumped_when_blocked()
    names = {card.name for card in attackers}
    assert len(attackers) >= 15, sorted(names)
    assert {"Cadaverous Knight", "Pygmy Troll"} <= names
    fought, wrong = 0, []
    for card in attackers:
        for power, toughness in SIZES:
            result = _fought(card, _mk_creature_card(f"Vanilla {power}/{toughness}", power, toughness))
            if result is None:
                continue
            fought += 1
            if result[0] != result[1]:
                wrong.append((card.name, (power, toughness), *result))
    assert fought >= 60, fought
    assert not wrong, wrong
