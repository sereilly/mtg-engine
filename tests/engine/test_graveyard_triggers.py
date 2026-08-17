"""A trigger that declares it functions from the graveyard must fire from one.

`tests/engine/test_trigger_dispatchers.py` asks its question per *condition
kind*, and cannot see this gap: Silversmote Ghoul's condition is
``end_step_self``, which has had a dispatcher since round 68 — over battlefields.
Measured while building round 76: with the grammar, the lowering and the handler
in place but the graveyard scan omitted, the card **compiled supported, the full
suite passed, and all five `--check` gates passed, while the ability never once
fired.** That is round 58's `draws_card` failure on a new axis.

So this guard asks the question behaviourally instead of comparing two lists: it
puts the card in a graveyard, arms its condition, runs the step, and looks at
what happened. CR 113.6m is the rule being enforced — an ability whose effect
moves its own source out of a zone functions from that zone, and nowhere else.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.events import FUNCTIONS_FROM
from engine.models import PlayerState
from engine.oracle import compile_card_oracle


def _graveyard_functioning_triggers():
    """Every (card, trigger) in the whole pool declaring it works from a graveyard.

    Over the manifest including measured sets, deliberately. The shipped pool has
    no such card yet, so a shipped-only fixture would make this guard vacuous on
    the very day it was written — which is the failure it exists to prevent.
    """
    for card in load_cards(manifest_set_paths(include_measured=True)):
        for trig in compile_card_oracle(card).triggered_abilities:
            if not trig.supported or trig.instruction is None:
                continue
            if (trig.instruction.payload or {}).get(FUNCTIONS_FROM) == "graveyard":
                yield card, trig


def test_the_pool_has_at_least_one_such_trigger():
    """The guard below is a loop over a generated set, so it passes trivially if
    the set is empty. This is what says it is not."""
    assert list(_graveyard_functioning_triggers())


def test_every_graveyard_functioning_trigger_reaches_the_battlefield():
    """Put it in a graveyard, satisfy its condition, run its step, and look."""
    for card, trig in _graveyard_functioning_triggers():
        p1 = PlayerState(name="P1", graveyard=[card])
        game = Game(players=[p1, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.start_turn(0)

        # Arm whatever this trigger's intervening-if asks about. Only the shapes
        # the pool actually prints; an unknown one fails loudly below rather than
        # being silently treated as satisfied.
        gate = (trig.instruction.payload or {}).get("intervening_if")
        if gate is not None:
            assert gate["kind"] == "life_gained_this_turn", (
                f"{card.name}: this guard cannot arm {gate['kind']!r} yet"
            )
            p1.life_gained_this_turn = int(gate.get("amount", 1))

        game.resolve_end_step(0)
        game._settle()

        assert any(p.card is card for p in p1.battlefield), (
            f"{card.name}: declares {FUNCTIONS_FROM}='graveyard' under "
            f"{trig.condition.kind!r} and nothing fired it from a graveyard"
        )
        assert p1.graveyard == [], f"{card.name}: left a copy behind in the graveyard"
