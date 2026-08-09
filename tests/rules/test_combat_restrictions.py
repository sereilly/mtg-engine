"""Tests for Magic: The Gathering Comprehensive Rules Section 506.

Covers:
  506.3 — A creature can only attack if the game's restrictions allow it

These pin the *derivation* of combat restrictions from oracle text
(engine/combat_restrictions.py), which replaced an `elif` chain of exact string
comparisons inside the oracle compiler. That chain hardcoded Island, so this
uses an invented card printed with a different land type — a test naming only
Dandân would have passed against the broken version.
"""

import pytest

from engine import Game, PlayerState
from engine.combat_restrictions import combat_restriction_for
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line
from tests.helpers import _nosick


def _fish(land_type: str) -> CardDefinition:
    text = f"This creature can't attack unless defending player controls a {land_type}."
    return CardDefinition(
        name=f"{land_type} Fish", mana_cost="{U}{U}", cmc=2.0,
        type_line="Creature — Fish", oracle_text=text,
        colors=("U",), color_identity=("U",), keywords=(), produced_mana=(),
        raw={"name": f"{land_type} Fish", "type_line": "Creature — Fish",
             "power": "4", "toughness": "1"},
    )


@pytest.mark.cr("506.3")
def test_506_3_the_required_land_type_is_read_from_the_text():
    """The restriction names a land type, and that type is data. It used to be
    baked into the instruction's *name*, matched by exact string equality
    against the Island wording — so a card naming any other type compiled to a
    bare static line and attacked freely while still reporting supported."""
    for land_type in ("Island", "Mountain", "Forest", "Plains", "Swamp"):
        line = normalize_creature_line(
            f"This creature can't attack unless defending player controls a {land_type}."
        )
        restriction = combat_restriction_for(line)

        assert restriction is not None, land_type
        assert restriction.kind == "cant_attack_without_land_type"
        assert restriction.payload == {"land_type": land_type.lower()}


@pytest.mark.cr("506.3")
def test_506_3_a_non_island_restriction_is_actually_enforced():
    """The whole point: the restriction has to *stop the attack*, not merely
    parse. A creature needing a Mountain may attack a player who controls one
    and may not attack a player who controls an Island."""
    catalog = {c.name: c for c in __import__("engine.card_loader", fromlist=["x"]).load_catalog()}

    def can_attack(defender_land: str) -> bool:
        attacker = _nosick(Permanent(card=_fish("Mountain")))
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog[defender_land])])
        game = Game(players=[p1, p2])
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        return game.declare_attackers(0, [0])[0]

    assert can_attack("Mountain") is True
    assert can_attack("Island") is False


@pytest.mark.cr("506.3")
def test_506_3_unrelated_lines_impose_no_combat_restriction():
    """A loose match here would silently stop a creature attacking."""
    for line in (
        "this creature can't be blocked except by walls",
        "this creature gets +1/+1 as long as you control a swamp",
        "flying",
        "",
    ):
        assert combat_restriction_for(line) is None, line


# ---------------------------------------------------------------------------
# Characteristic-defining land-count P/T (CR 604.3)
# ---------------------------------------------------------------------------


def _orc(text: str) -> CardDefinition:
    return CardDefinition(
        name="Probe Orc", mana_cost="{1}{R}", cmc=2.0,
        type_line="Creature — Orc", oracle_text=text,
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "Probe Orc", "type_line": "Creature — Orc",
             "power": "2", "toughness": "2"},
    )


@pytest.mark.cr("509.1b")
def test_509_1b_cant_block_power_threshold_is_data_not_part_of_the_kind():
    """"Can't block creatures with power N or greater" is one restriction with a
    number in it. The threshold used to be baked into the instruction kind
    (`cant_block_power_2_or_greater`), so the identical restriction printed with
    any other number produced no instruction at all."""
    for threshold in (1, 2, 3, 4, 7):
        program = compile_card_oracle(
            _orc(f"This creature can't block creatures with power {threshold} or greater.")
        )
        assert program.supported
        blocks = [i for i in program.instructions if i.kind == "cant_block_power_n_or_greater"]
        assert len(blocks) == 1, f"power {threshold} produced {program.instructions}"
        assert blocks[0].payload["power"] == threshold


@pytest.mark.cr("509.1b")
def test_509_1b_a_higher_threshold_actually_gates_blocking():
    """Payload-correct is not behaviour-correct: drive the real block check."""
    blocker_card = _orc("This creature can't block creatures with power 4 or greater.")
    attacker_card = CardDefinition(
        name="Big Attacker", mana_cost="{3}{R}", cmc=4.0,
        type_line="Creature — Giant", oracle_text="", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "Big Attacker", "type_line": "Creature — Giant",
             "power": "3", "toughness": "3"},
    )
    attacker_p1, defender_p2 = PlayerState(name="A"), PlayerState(name="B")
    attacker = _nosick(Permanent(card=attacker_card))
    blocker = _nosick(Permanent(card=blocker_card))
    attacker_p1.battlefield.append(attacker)
    defender_p2.battlefield.append(blocker)
    game = Game(players=[attacker_p1, defender_p2])
    game.enforce_mana_costs = False

    # Power 3 is under the printed threshold of 4, so this block is legal —
    # against the old hardcoded "2 or greater" it would have been refused.
    assert game._can_block_attacker(blocker, attacker) is True

    attacker.metadata["derived_buff_power"] = 1   # now 4/3, at the threshold
    assert game._can_block_attacker(blocker, attacker) is False


@pytest.mark.cr("506.3")
def test_506_3_an_unrecognized_restriction_rider_is_unsupported_not_silently_dropped():
    """The gate and the dispatch must read the same table.

    The gate matched its literals by `startswith` while the dispatch patterns
    are anchored, so "can't block creatures with flying" was admitted by the
    prefix "this creature can't block", matched no anchored pattern, and fell
    through to a bare static line: supported, restriction absent. Failing loud
    is the contract — a card the engine cannot enforce must not claim support.
    """
    for text in (
        "This creature can't block creatures with flying.",
        "This creature can't attack unless you control a Wall.",
        "This creature can't attack unless defending player controls a Desert.",
    ):
        program = compile_card_oracle(_orc(text))
        assert not program.supported, f"silently admitted: {text}"
