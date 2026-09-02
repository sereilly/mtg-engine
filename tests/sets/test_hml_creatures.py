"""Per-card tests for Homelands' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

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


# --- W1G4: filtered statics and block triggers ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g4_creature(
    name: str, colors: tuple[str, ...] = (), power: int = 2, toughness: int = 2,
) -> CardDefinition:
    """A vanilla creature of a named colour, for the far side of a block.

    Invented rather than pulled from the pool so the colour under test is the
    only thing that varies between the two halves of each pair below.
    """
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4_blocking(set_pool, own_name: str, *attackers: CardDefinition):
    """*own_name* on seat 1 blocking every one of *attackers* from seat 0.

    Stops in the declare-blockers step with the attack already declared, which
    is where a block trigger is announced (CR 509.1g).
    """
    mine = Permanent(card=set_pool("HML")[own_name])
    theirs = [Permanent(card=card) for card in attackers]
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(theirs)),
        PlayerState(name="P2", battlefield=[mine]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, list(range(len(theirs))))
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    assert game.current_step == "declare_blockers"
    return game, mine, theirs


def test_rashka_the_slayer_pumps_when_it_blocks_a_black_creature(set_pool):
    """"Whenever Rashka blocks one or more black creatures, Rashka gets +1/+2."

    The narrowed half. Rashka is a 3/3 and the trigger is the only thing on the
    board that could change that.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer", _w1g4_creature("Test Wight", ("B",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (4, 5)


def test_rashka_the_slayer_does_not_pump_blocking_a_creature_of_another_colour(set_pool):
    """The half the card was mis-playing.

    Rashka reported *supported* before this group — its Reach line carries the
    card — while the trigger condition fell through to the bare "whenever this
    creature blocks" row, so the +1/+2 arrived on any block at all. The census
    cannot see that (a card is supported when any of its lines is), which is
    what makes this test the one worth writing.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer", _w1g4_creature("Test Bear", ("G",))
    )

    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (3, 3)


def test_rashka_the_slayer_triggers_once_for_two_black_creatures(set_pool):
    """CR 509.3e: "one or more" is a threshold, so the ability fires **once**
    however many creatures answered — not once per creature, which is what the
    singular "blocks a creature" wording would have given.

    Rashka can block two attackers only because an effect says so, so the block
    is built by hand rather than through the declaration's one-attacker cap.
    """
    game, rashka, _attackers = _w1g4_blocking(
        set_pool, "Rashka the Slayer",
        _w1g4_creature("Test Wight", ("B",)),
        _w1g4_creature("Test Shade", ("B",)),
    )
    rashka.metadata["can_block_any_number_until_eot"] = True

    assert game.declare_blockers(1, {0: [0, 1]})[0]
    game.resolve_stack()
    game._settle()

    assert (rashka.effective_power, rashka.effective_toughness) == (4, 5)


def test_sea_troll_cannot_regenerate_without_a_blue_creature_in_the_block(set_pool):
    """"Activate only if this creature blocked or was blocked by a blue creature
    this turn." (CR 602.5.)

    The unenforced direction is the dangerous one — an ability that works more
    often than the card allows — so the refusal is asserted before the
    permission.
    """
    game, troll, _attackers = _w1g4_blocking(
        set_pool, "Sea Troll", _w1g4_creature("Test Bear", ("G",))
    )
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(1, "Sea Troll")

    assert not result.supported
    assert "block" in result.details
    assert troll.regeneration_shield == 0


def test_sea_troll_regenerates_after_blocking_a_blue_creature(set_pool):
    """The same board with the attacker's colour changed, which is the only
    thing the clause asks about."""
    game, troll, _attackers = _w1g4_blocking(
        set_pool, "Sea Troll", _w1g4_creature("Test Drake", ("U",))
    )
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(1, "Sea Troll")
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert troll.regeneration_shield == 1


def test_sea_troll_reads_the_block_from_the_other_side_too(set_pool):
    """"blocked **or was blocked by**" is one question about a symmetric
    relation (CR 509.1a), so the Troll attacking into a blue blocker answers it
    exactly as blocking a blue attacker does. Reading one of the two pair
    records would answer it for half the combats the creature was in.
    """
    troll = Permanent(card=set_pool("HML")["Sea Troll"])
    blocker = Permanent(card=_w1g4_creature("Test Drake", ("U",)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[troll]),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()

    result = game.activate_permanent_ability(0, "Sea Troll")
    game.resolve_stack()
    game._settle()

    assert result.supported, result.details
    assert troll.regeneration_shield == 1
