"""Per-card tests for Alliances' lands.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card — Alliances prints no basics of its own."""
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def test_w1g5_thawing_glaciers_arms_a_cleanup_step_delay(set_pool):
    """CR 514.3a names this ability shape in the rule itself: the cleanup step's
    exception to "no player receives priority" exists because a trigger can be
    waiting for it."""
    glaciers = set_pool("ALL")["Thawing Glaciers"]
    program = compile_card_oracle(glaciers)
    assert program.supported
    ability = program.activated_abilities[0]
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == ["search_library", "create_delayed_trigger"]
    assert steps[1].payload["event"] == "next_cleanup_step"


def test_w1g5_thawing_glaciers_returns_itself_in_the_cleanup_step(set_pool):
    """Give the delay a game. The whole failure mode of a delayed trigger is
    being registered and never fired, and every static instrument reports that
    as success."""
    glaciers = set_pool("ALL")["Thawing Glaciers"]
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    p1 = game.players[0]
    land = Permanent(card=glaciers)
    p1.battlefield.append(land)
    p1.library.append(_w1g5_lea("Forest"))
    game._sync_control()
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Thawing Glaciers", ability_index=0)
    # The search suspends the resolution (CR 608.2e), so the delay is armed
    # by the *rest* of the ability after the pile has been answered for.
    game.auto_resolve_pending_choices()
    game._settle()
    assert any(perm.card.name == "Forest" for perm in p1.battlefield)
    # Still on the battlefield: the delay names a step that has not come.
    assert any(perm.card.name == "Thawing Glaciers" for perm in p1.battlefield)

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert all(perm.card.name != "Thawing Glaciers" for perm in p1.battlefield)
    assert [card.name for card in p1.hand] == ["Thawing Glaciers"]
