"""Guards for the upkeep-effect registry (engine/phases/upkeep_effects.py).

``resolve_upkeep`` used to dispatch interactive upkeep triggers with a
hand-written if-chain, so supporting a card meant editing turn-structure
control flow and precedence between two matching branches was decided by
source order. These pin the properties the registry replaced that with.
"""

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.phases.upkeep_effects import UPKEEP_EFFECTS, upkeep_effect


def _pool_trigger_pairs() -> dict[tuple[str, str], list[str]]:
    """Every (trigger condition, instruction kind) pair the compiler produces
    for the whole manifest pool, with the cards that produce it."""
    pairs: dict[tuple[str, str], list[str]] = {}
    for card in load_catalog():
        for trig in compile_card_oracle(card).triggered_abilities:
            if trig.instruction is None:
                continue
            pairs.setdefault((trig.condition.kind, trig.instruction.kind), []).append(card.name)
    return pairs


# Handlers written for a card whose set is implemented but not yet in the
# manifest. Pending is not the same as dead: each names the card it serves, and
# the entry has to be removed when that set lands — at which point the pair
# becomes reachable and the guard covers it again.
#
# An entry that outlives its set is exactly the stale exemption this file warns
# about, so keep the list short and delete on landing.
PENDING_A_SET: dict[tuple[str, str], str] = {
    ("upkeep_self", "set_source_base_pt_from_target_until_next_upkeep"):
        "Halfdane (LEG, still under `measured`) — delete on promotion",
}


def test_every_registered_upkeep_effect_is_reachable_from_the_pool():
    """A registry entry no card can produce is dead code that still reads as
    support. Each key must be one the compiler actually emits — which also
    means this fails loudly if a parser change renames a condition or kind out
    from under a handler, instead of the handler silently never running."""
    pairs = _pool_trigger_pairs()
    unreachable = sorted(
        key for key in UPKEEP_EFFECTS
        if key not in pairs and key not in PENDING_A_SET
    )

    assert not unreachable, (
        "upkeep effects registered for (condition, kind) pairs no card in the "
        f"pool produces: {unreachable}"
    )


def test_registering_two_handlers_for_one_pair_raises():
    """The if-chain resolved a collision by source order, silently. Two
    handlers for one pair is now an import-time error."""
    existing = next(iter(UPKEEP_EFFECTS))

    with pytest.raises(ValueError, match="already handled by"):
        upkeep_effect(*existing)(lambda self, ctx: None)


# Upkeep-shaped kinds the battlefield registry deliberately does not carry,
# each with the flow that does handle it. An entry that stops being produced
# fails the staleness check below, so this can only shrink.
HANDLED_ELSEWHERE: dict[str, str] = {
    # Ashes to Ashes-style recursion triggers fire from the *graveyard*, so they
    # are found by their own scan in resolve_upkeep rather than by the loop over
    # battlefield permanents this registry dispatches.
    "upkeep_return_self_from_graveyard": "graveyard-recursion scan (upkeep_step.py)",
}


def test_registry_covers_the_interactive_upkeep_kinds():
    """Every instruction kind whose name marks it as an interactive upkeep
    shape (``upkeep_*``) must have a handler, so a new one cannot be parsed
    into existence and then silently never run. An ordinary upkeep trigger goes
    on the stack through EFFECT_HANDLERS instead and is deliberately absent,
    which is why the check is scoped to the prefix."""
    handled = {kind for _cond, kind in UPKEEP_EFFECTS}
    produced = {
        kind
        for (cond, kind) in _pool_trigger_pairs()
        if kind.startswith("upkeep_") and cond.startswith(("upkeep_", "no_islands"))
    }
    unhandled = produced - handled - set(HANDLED_ELSEWHERE)

    assert not unhandled, (
        f"interactive upkeep kinds with no registered handler: {sorted(unhandled)}"
    )


def test_no_stale_handled_elsewhere_entries():
    """An acknowledgement for a kind nothing produces any more is a claim about
    code that no longer exists."""
    produced = {kind for (_cond, kind) in _pool_trigger_pairs()}
    stale = sorted(set(HANDLED_ELSEWHERE) - produced)

    assert not stale, f"HANDLED_ELSEWHERE entries no card produces: {stale}"
