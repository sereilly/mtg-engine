"""CR 602.5 — "Activate only …", the printed clauses that gate an activation.

The twin of `tests/rules/test_cast_restrictions.py`, and it exists for the same
reason `engine/activation_restrictions.py` does: these were a hand-written
if-chain of substring tests inside the activation path, so a printed clause
nobody had added a branch for was **unenforced**. That failure has no symptom —
the ability resolves, the card reports supported, and the game is simply wrong
in its controller's favour — which is why it survived five sets and why the
table is checked here by *behaviour* rather than by reading its rows back.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_restrictions import (
    ACTIVATION_RESTRICTIONS,
    activation_denial,
    unreadable_activation_clauses,
)
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

_CATALOG = {c.name: c for c in load_catalog()}


def _board(card_name: str, *, extra=()):
    source = Permanent(card=_CATALOG[card_name])
    p1 = PlayerState(name="P1", battlefield=[source, *extra])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    _nosick(source)
    return game, p1, p2, source


@pytest.mark.cr("602.5")
def test_602_5_an_unmet_activation_restriction_refuses_the_activation():
    """"Activate only if a creature died this turn." (Caged Zombie.)

    The half that had no enforcement at all: with nothing dead, activating drew
    no complaint and drained two life.
    """
    game, _p1, p2, _source = _board("Caged Zombie")

    result = game.activate_permanent_ability(0, "Caged Zombie", target_player_index=1)
    game._settle()

    assert not result.supported
    assert "no creature died this turn" in result.details
    assert p2.life == 20


@pytest.mark.cr("602.5")
def test_602_5_a_met_activation_restriction_permits_it():
    """The same board once a creature has died — paired with the refusal above,
    so what the pair reads is the condition and not the ability being broken."""
    game, _p1, p2, _source = _board("Caged Zombie")
    game.creatures_died_this_turn = 1

    result = game.activate_permanent_ability(0, "Caged Zombie", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert p2.life == 18


@pytest.mark.cr("602.5", "613.1")
def test_602_5_a_board_condition_reads_the_computed_characteristics():
    """"Activate only if you control a creature with flying." (Celestial
    Enforcer.) Through `is_creature` and `has_keyword`, so a granted flying
    counts (CR 613 layer 6) and an animated land is a creature — the printed
    type line is not what the clause asks about."""
    victim = Permanent(card=_CATALOG["Alpine Watchdog"])
    game, p1, _p2, _source = _board("Celestial Enforcer")
    game.players[1].battlefield = [victim]
    game._sync_control()

    refused = game.activate_permanent_ability(
        0, "Celestial Enforcer", target_player_index=1, target_permanent_index=0
    )
    assert not refused.supported
    assert not victim.tapped

    p1.battlefield.append(Permanent(card=_CATALOG["Concordia Pegasus"]))
    game._sync_control()

    allowed = game.activate_permanent_ability(
        0, "Celestial Enforcer", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert allowed.supported, allowed.details
    assert victim.tapped


@pytest.mark.cr("602.5")
def test_602_5_a_clause_is_matched_whole():
    """A pattern that matched a *prefix* would be a weaker restriction wearing
    the card's words: "…only if you control a creature with flying" satisfied by
    a rule written for "…only if you control a creature".

    Asked of the table rather than of a card, because the property is about the
    patterns and a card can only ever demonstrate one of them.
    """
    for entry in ACTIVATION_RESTRICTIONS:
        pattern = entry.pattern.pattern
        assert pattern.startswith("^") and pattern.endswith("$"), pattern

    others = [e for e in ACTIVATION_RESTRICTIONS]
    for entry in ACTIVATION_RESTRICTIONS:
        # A clause one pattern claims must not also be claimed by a different
        # one — two answers to "may this be activated?" is the ambiguity the
        # anchoring above is meant to remove.
        sample = entry.pattern.pattern.strip("^$").replace("\\", "")
        matching = [e for e in others if e.pattern.match(sample)]
        assert len(matching) <= 1, (sample, [m.pattern.pattern for m in matching])


@pytest.mark.cr("602.5")
def test_602_5_a_restriction_applies_only_to_the_ability_that_prints_it():
    """A permanent with two abilities prints its restrictions per ability, so
    the clause is read off *that* line. Testing the card's whole text would gate
    one ability with the other's rule — which for Chromatic Orrery's mana
    ability would be a lock-out."""
    game, _p1, _p2, _source = _board("Caged Zombie")

    other_line = "{T}: Add {C}."
    assert activation_denial(game, 0, _source, other_line) is None
    printed = "{1}{B}, {T}: Each opponent loses 2 life. Activate only if a creature died this turn."
    assert activation_denial(game, 0, _source, printed) is not None


@pytest.mark.cr("602.5")
def test_every_printed_activation_clause_in_the_pool_is_readable():
    """The gate half: a clause the table cannot read must make its card
    unsupported rather than admitted with the restriction ignored. Over the
    whole shipped pool, so a newly ingested set cannot add a silent one."""
    unreadable = {
        clause: card.name
        for card in _CATALOG.values()
        for clause in unreadable_activation_clauses(card.oracle_text or "")
    }

    assert not unreadable, (
        "printed activation clauses nothing enforces — add them to "
        f"ACTIVATION_RESTRICTIONS: {unreadable}"
    )
