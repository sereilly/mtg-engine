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
from engine.named_counters import add_counters
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


# ---------------------------------------------------------------------------
# The three clauses Legends prints on their own. Each was *unreadable* by the
# table, which is the gate half of this module's failure mode: the sentence is
# printed, the card reports supported, and no row says what the sentence means.
# ---------------------------------------------------------------------------


@pytest.mark.cr("602.5")
@pytest.mark.parametrize(
    "phase, step, allowed",
    [
        ("beginning", "upkeep", True),
        ("precombat_main", "precombat_main", True),
        ("combat", "declare_attackers", True),
        ("combat", "declare_blockers", True),
        ("combat", "combat_damage", False),
        ("combat", "end_of_combat", False),
        ("postcombat_main", "postcombat_main", False),
    ],
)
def test_602_5_only_before_a_named_step_is_a_point_in_the_turn(phase, step, allowed):
    """"Activate only before the combat damage step." (Angus Mackenzie.)

    A window bounded by a point in the turn rather than by a phase name, so the
    answer has to be an *ordering*: read as "during combat" it would allow the
    end of combat step, which is after the damage this card is racing, and read
    as "your turn" it would refuse the activation on the turn Angus most wants
    it -- an opponent's.
    """
    game, _p1, _p2, _angus = _board("Angus Mackenzie")
    game.current_turn_phase = phase
    game.current_step = step

    result = game.activate_permanent_ability(0, "Angus Mackenzie")
    game._settle()

    assert result.supported is allowed, result.details
    if not allowed:
        assert "only before that step" in result.details


@pytest.mark.cr("602.5")
def test_602_5_the_named_step_is_payload_not_a_row_per_card():
    """The step alternation is built from the engine's own turn structure, so a
    card printed with a different step is the same sentence. Asked of invented
    clauses, because Legends prints only the one -- and a table needing a row
    per step would answer no to both of the first two."""
    from engine.activation_restrictions import activation_restriction_line

    assert activation_restriction_line("Activate only before the end step")
    assert activation_restriction_line("Activate only before the declare blockers step")
    # A step this engine does not have leaves the clause unmatched, which makes
    # its card unsupported rather than admitted with the timing ignored.
    assert not activation_restriction_line("Activate only before the mulligan step")


@pytest.mark.cr("602.5")
def test_602_5_a_counter_threshold_is_read_off_the_permanent():
    """"Activate only if there are two or more hatchling counters on this
    artifact." (Triassic Egg.) Count and counter word are both payload, and the
    counters are the *source's* -- so the answer changes as the card's other
    ability puts them on."""
    game, _p1, _p2, egg = _board("Triassic Egg")
    line = next(l for l in egg.card.oracle_text.splitlines() if "Activate only" in l)

    assert activation_denial(game, 0, egg, line) is not None
    add_counters(egg, "hatchling", 1)
    assert activation_denial(game, 0, egg, line) is not None, (
        "one is not two -- a threshold read as presence is a weaker restriction"
    )
    add_counters(egg, "hatchling", 1)
    assert activation_denial(game, 0, egg, line) is None


@pytest.mark.cr("602.5")
def test_602_5_once_each_turn_standing_alone_is_a_row_of_its_own():
    """"Activate only once each turn." (Dream Coat.)

    The two rows carrying this as an optional tail (Instill Energy, Gate to
    Phyrexia) could not read it standing alone, so the clause was unreadable
    while the words were nonetheless enforced by a substring test beside the
    table -- one fact with two representations. Both halves ask
    `activations_allowed_each_turn` now, over the state the permanent carries.
    """
    from engine.activation_restrictions import (
        activations_allowed_each_turn,
        mark_activated_this_turn,
    )

    game, _p1, _p2, coat = _board("Dream Coat")
    line = next(l for l in coat.card.oracle_text.splitlines() if "Activate only" in l)
    assert activations_allowed_each_turn(line) == 1

    assert activation_denial(game, 0, coat, line) is None
    mark_activated_this_turn(game, coat)
    assert activation_denial(game, 0, coat, line) == "only once each turn"
    # The limit is per turn, so the next one clears it.
    game.turn += 1
    assert activation_denial(game, 0, coat, line) is None


@pytest.mark.cr("602.5")
def test_602_5_the_once_each_turn_tail_is_still_read_as_the_same_clause():
    """Instill Energy prints the limit as a *tail* on a timing clause. The
    reader the stamp uses has to see all three printed spellings, or a card ends
    up stamped and never refused, or refused and never stamped."""
    from engine.activation_restrictions import activations_allowed_each_turn

    assert activations_allowed_each_turn(
        "{0}: Untap enchanted creature. Activate only during your turn and only "
        "once each turn."
    ) == 1
    assert activations_allowed_each_turn(
        "Sacrifice a creature: Destroy target artifact. Activate only during "
        "your upkeep and only once each turn."
    ) == 1
    assert activations_allowed_each_turn("{T}: Add {C}.") is None


@pytest.mark.cr("602.5")
def test_602_5_a_printed_cap_above_one_is_the_same_clause_with_a_number():
    """"Activate no more than twice each turn." (Vampire Bats.)

    The only clause in the pool that does not begin "Activate only", which is
    how it slipped every reader: `_clauses` collected by that prefix, so the
    support gate had nothing to refuse, and the grammar's restriction production
    consumed the sentence verbatim without asking this table. The ability was a
    {B} pump with no cap at all.

    The number is payload, so the row is every printed frequency -- and a
    frequency this module cannot read leaves the clause unmatched, which is what
    keeps the card unsupported rather than uncapped.
    """
    from engine.activation_restrictions import (
        activation_restriction_line,
        activations_allowed_each_turn,
        mark_activated_this_turn,
    )

    line = (
        "{B}: This creature gets +1/+0 until end of turn. "
        "Activate no more than twice each turn."
    )
    assert activations_allowed_each_turn(line) == 2
    assert activation_restriction_line("Activate no more than twice each turn.")
    assert (
        activations_allowed_each_turn(
            "{T}: Draw a card. Activate no more than three times each turn."
        )
        == 3
    )
    assert not activation_restriction_line("Activate no more than a bunch each turn.")

    game, _p1, _p2, bats = _board("Vampire Bats")
    assert activation_denial(game, 0, bats, line) is None
    mark_activated_this_turn(game, bats)
    assert activation_denial(game, 0, bats, line) is None
    mark_activated_this_turn(game, bats)
    assert activation_denial(game, 0, bats, line) == (
        "already activated as many times as it may be this turn"
    )
    game.turn += 1
    assert activation_denial(game, 0, bats, line) is None
