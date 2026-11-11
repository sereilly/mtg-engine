"""The AI and the Couriers' "for as long as this creature remains tapped".

Two decisions, each derived from the compiled program rather than from a
card name:

- **Whom to send the bonus to.** Each Courier is its own printed type
  (Pearlspear Courier is a Human Soldier), so the strongest-friendly-target
  pick named the Courier itself nearly every time (15 of 16 activations in a
  seeded four-game run) — a +2/+2 on a creature that holds the effect by
  staying tapped, and a tapped creature neither attacks nor blocks (CR
  508.1a, 509.1a). The source is now not a candidate for such an ability.
- **Whether to untap it.** "You may choose not to untap this creature during
  your untap step": with no human to ask, the untap step keeps it tapped
  while its effect still reaches a creature (``untap_step``'s default, the
  one a linked steal and an untap lock already had).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack
from tests.helpers import action_target  # noqa: E402


def _board(set_pool, *names):
    pool = set_pool("ONS")
    mine = [_nosick(Permanent(card=pool[name])) for name in names]
    game = Game(players=[
        PlayerState(name="AI", battlefield=list(mine)),
        PlayerState(name="Other"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    game._settle()
    return game, mine


def test_the_ai_never_sends_a_courier_bonus_to_the_courier(set_pool):
    game, (courier,) = _board(set_pool, "Pearlspear Courier")
    action = choose_activation_action(game, 0)
    assert action is None or action.permanent_name != "Pearlspear Courier", (
        "the only Soldier is the Courier, and a bonus on its own tapped body "
        "can neither attack nor block"
    )


def test_the_ai_sends_a_courier_bonus_to_another_creature_of_its_type(set_pool):
    game, (courier, seeker) = _board(set_pool, "Pearlspear Courier", "Glory Seeker")
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Pearlspear Courier"
    target = action_target(game, action)
    assert target is seeker

    result = game.activate_permanent_ability(
        0, "Pearlspear Courier", target_player_index=0,
        target_permanent_ids=[seeker.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    # …and, asked nothing, the untap step keeps the Courier tapped.
    game.resolve_untap_step(0)
    assert courier.tapped
    game._recompute_continuous_effects()
    assert (seeker.effective_power, seeker.effective_toughness) == (4, 4)
